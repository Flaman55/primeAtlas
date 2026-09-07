"""ctypes bridge for the optional native hybrid tuple-filter core.

The classical MAIN marking remains intentionally explicit here.  The C library
accelerates only the filter's nondecreasing product enumeration, letting tests
compare it directly with the Phase-3 reference before it is used by the runner.
"""

from __future__ import annotations

import ctypes
import os
import time
from pathlib import Path
from typing import Iterable

from hybrid_planner import HybridExtensionPlan
from hybrid_reference import HybridReferenceError, ReferenceSegmentResult, _strict_positive_primes


_LIB_PATH = Path(__file__).with_name("hybrid_filter_engine.so")
_MAIN_LIB_PATH = Path(__file__).with_name("prime_sieve_engine_v4.so")
_lib = None
_main_lib = None


def native_build_command() -> str:
    return "gcc -O3 -shared -fPIC hybrid_filter_engine.c -o hybrid_filter_engine.so"


def native_library_available() -> bool:
    """Whether both native filter and established v4 MAIN cores are available."""
    return _LIB_PATH.is_file() and _MAIN_LIB_PATH.is_file()


def _load_lib():
    global _lib
    if _lib is None:
        if not _LIB_PATH.is_file():
            raise RuntimeError(f"Missing {_LIB_PATH}; build it in WSL: {native_build_command()}")
        lib = ctypes.CDLL(str(_LIB_PATH))
        lib.mark_filter_tuple_products_atomic.argtypes = [
            ctypes.c_uint64, ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t, ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(ctypes.c_uint64),
        ]
        lib.mark_filter_tuple_products_atomic.restype = ctypes.c_int
        _lib = lib
    return _lib


def _load_main_lib():
    """Load v4's existing atomic marking ABI without changing that engine's source."""
    global _main_lib
    if _main_lib is None:
        if not _MAIN_LIB_PATH.is_file():
            raise RuntimeError(f"Missing {_MAIN_LIB_PATH}; build the established v4.1 MAIN backend first")
        lib = ctypes.CDLL(str(_MAIN_LIB_PATH))
        lib.generate_and_sieve_segment_bits_atomic.argtypes = [
            ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64,
            ctypes.c_uint64, ctypes.POINTER(ctypes.c_ubyte),
        ]
        lib.generate_and_sieve_segment_bits_atomic.restype = ctypes.c_int
        _main_lib = lib
    return _main_lib


def mark_filter_tuple_products_native(plan: HybridExtensionPlan, lo: int, hi: int) -> tuple[bytearray, tuple[tuple[int, int], ...]]:
    if lo < 0 or hi <= lo or hi - 1 > plan.limit:
        raise HybridReferenceError("native segment must be a non-empty range inside the hybrid plan")
    values = (ctypes.c_uint64 * len(plan.filter_primes))(*plan.filter_primes)
    bits = bytearray((hi - lo + 7) // 8)
    counts = (ctypes.c_uint64 * (plan.required_tuple_order + 1))()
    raw_bits = (ctypes.c_ubyte * len(bits)).from_buffer(bits)
    code = _load_lib().mark_filter_tuple_products_atomic(
        lo, hi - lo, values, len(plan.filter_primes), plan.required_tuple_order,
        raw_bits, counts)
    if code != 0:
        raise RuntimeError(f"native tuple filter rejected its validated inputs (code {code})")
    return bits, tuple((order, int(counts[order])) for order in plan.tuple_orders)


def sieve_native_segment(plan: HybridExtensionPlan, main_primes: Iterable[int] | None, lo: int, hi: int) -> ReferenceSegmentResult:
    result, _main_seconds, _filter_seconds = sieve_native_segment_timed(plan, lo, hi, main_primes)
    return result


def sieve_native_segment_timed(plan: HybridExtensionPlan, lo: int, hi: int,
                               main_primes: Iterable[int] | None = None) -> tuple[ReferenceSegmentResult, float, float]:
    """Native segment result plus isolated C-MAIN/C-filter wall times.

    ``main_primes`` exists only for the `lo == 0` reference diagnostic, where
    the production v4 MAIN convention needs its self-marked primes restored.
    Real Atlas windows begin at one or above, so no Python MAIN list is needed.
    """
    t_filter = time.perf_counter()
    bits, counts = mark_filter_tuple_products_native(plan, lo, hi)
    filter_seconds = time.perf_counter() - t_filter
    t_main = time.perf_counter()
    for value in range(lo, min(hi, 2)):
        bits[(value - lo) >> 3] |= 1 << ((value - lo) & 7)
    # This is the exact v4/v4.1 C marking primitive, constrained to MAIN's
    # trusted p <= a interval.  Its atomic OR shares the compact bit buffer
    # already populated by the tuple filter, so the two elimination sources
    # commute without a Python per-multiple loop.
    raw_bits = (ctypes.c_ubyte * len(bits)).from_buffer(bits)
    ptr = ctypes.cast(raw_bits, ctypes.POINTER(ctypes.c_ubyte))
    code = _load_main_lib().generate_and_sieve_segment_bits_atomic(
        2, plan.main_last_prime + 1, lo >> 64, lo & 0xFFFFFFFFFFFFFFFF,
        hi - lo, ptr)
    if code != 0:
        raise RuntimeError(f"v4 MAIN engine failed for hybrid segment (code {code})")
    # v4/v4.1 always launches Atlas ranges from 1.  The reference test also
    # admits the mathematical diagnostic range starting at 0; under that one
    # convention the engine's self-elimination guard marks the MAIN primes
    # themselves.  Restore only those exact prime positions.  Real output
    # windows begin at 1 or above and never enter this compatibility branch.
    if lo == 0:
        if main_primes is None:
            raise HybridReferenceError("main_primes are required only for the lo=0 diagnostic segment")
        main = _strict_positive_primes(main_primes, "main_primes")
        if main[-1] != plan.main_last_prime:
            raise HybridReferenceError("main_primes must end at the plan's trusted MAIN boundary")
        for prime in main:
            if prime >= hi:
                break
            bits[prime >> 3] &= ~(1 << (prime & 7))
    primes = tuple(value for value in range(lo, hi) if not (bits[(value - lo) >> 3] & (1 << ((value - lo) & 7))))
    main_seconds = time.perf_counter() - t_main
    return (ReferenceSegmentResult(lo=lo, hi=hi, primes=primes, tuple_product_counts=counts),
            main_seconds, filter_seconds)
