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
from hybrid_reference import HybridReferenceError, ReferenceSegmentResult, _mark_main_composites, _strict_positive_primes


_LIB_PATH = Path(__file__).with_name("hybrid_filter_engine.so")
_lib = None


def native_build_command() -> str:
    return "gcc -O3 -shared -fPIC hybrid_filter_engine.c -o hybrid_filter_engine.so"


def native_library_available() -> bool:
    """Whether the optional C library is present beside this bridge."""
    return _LIB_PATH.is_file()


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


def sieve_native_segment(plan: HybridExtensionPlan, main_primes: Iterable[int], lo: int, hi: int) -> ReferenceSegmentResult:
    main = _strict_positive_primes(main_primes, "main_primes")
    if main[-1] != plan.main_last_prime:
        raise HybridReferenceError("main_primes must end at the plan's trusted MAIN boundary")
    result, _main_seconds, _filter_seconds = sieve_native_segment_timed(plan, main_primes, lo, hi)
    return result


def sieve_native_segment_timed(plan: HybridExtensionPlan, main_primes: Iterable[int], lo: int, hi: int) -> tuple[ReferenceSegmentResult, float, float]:
    """Native segment result plus isolated Python-MAIN/C-filter wall times."""
    main = _strict_positive_primes(main_primes, "main_primes")
    if main[-1] != plan.main_last_prime:
        raise HybridReferenceError("main_primes must end at the plan's trusted MAIN boundary")
    t_filter = time.perf_counter()
    bits, counts = mark_filter_tuple_products_native(plan, lo, hi)
    filter_seconds = time.perf_counter() - t_filter
    t_main = time.perf_counter()
    for value in range(lo, min(hi, 2)):
        bits[(value - lo) >> 3] |= 1 << ((value - lo) & 7)
    # Reference's MAIN marker uses one byte per candidate.  Merge it into the compact
    # C bitset instead of changing either source's independently testable semantics.
    main_marks = bytearray(hi - lo)
    _mark_main_composites(main_marks, lo, hi, main)
    for offset, marked in enumerate(main_marks):
        if marked:
            bits[offset >> 3] |= 1 << (offset & 7)
    primes = tuple(value for value in range(lo, hi) if not (bits[(value - lo) >> 3] & (1 << ((value - lo) & 7))))
    main_seconds = time.perf_counter() - t_main
    return (ReferenceSegmentResult(lo=lo, hi=hi, primes=primes, tuple_product_counts=counts),
            main_seconds, filter_seconds)
