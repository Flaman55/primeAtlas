"""pt1_lib.py -- ctypes binding of prime_sieve_engine_pt1.so and its slab call.

The library sieves a slab of odd numbers by the primes 3..B and decides every survivor:
pt1_sieve_odd() with 13 Miller-Rabin bases or BPSW (the pt1 scan, prime_sieve_pt1.py),
pt1_verify_odd() with the pseudosquares proof (the verification, pt1_verify.py). Both fill
the same composite bitmap, bit i (LSB first) = 1 when first_odd + 2*i is composite.
"""
import ctypes
import os
import threading

import numpy as np

LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prime_sieve_engine_pt1.so")
BUILD_HINT = ("gcc -O3 -Wall -shared -fPIC prime_sieve_engine_pt1.c -o "
              "prime_sieve_engine_pt1.so -lprimesieve -lpthread -lm")
_U64_MASK = (1 << 64) - 1
_lib = None


def load():
    global _lib
    if _lib is None:
        if not os.path.exists(LIB_PATH):
            raise RuntimeError(f"Missing {LIB_PATH} -- build it first: {BUILD_HINT}")
        lib = ctypes.CDLL(LIB_PATH)
        u64, ptr = ctypes.c_uint64, ctypes.c_void_p
        bits_t, done_t = ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(ctypes.c_uint64)
        lib.pt1_ctx_new.argtypes = [u64]
        lib.pt1_ctx_new.restype = ptr
        lib.pt1_ctx_count.argtypes = [ptr]
        lib.pt1_ctx_count.restype = u64
        lib.pt1_ctx_free.argtypes = [ptr]
        lib.pt1_ctx_free.restype = None
        # ctx, first_odd hi/lo, n_odd, det (13 MR bases) or BPSW, threads, chunk_odd, bits, done
        lib.pt1_sieve_odd.argtypes = [ptr, u64, u64, u64, ctypes.c_int, u64, u64, bits_t, done_t]
        lib.pt1_sieve_odd.restype = ctypes.c_int
        # ctx, first_odd hi/lo, n_odd, threads, chunk_odd, bits, done
        lib.pt1_verify_odd.argtypes = [ptr, u64, u64, u64, u64, u64, bits_t, done_t]
        lib.pt1_verify_odd.restype = ctypes.c_int
        lib.pt1_verify_bases.argtypes = [u64, u64, u64]
        lib.pt1_verify_bases.restype = ctypes.c_int
        lib.pt1_verify_min_s.argtypes = [u64, u64]
        lib.pt1_verify_min_s.restype = u64
        _lib = lib
    return _lib


def split(n):
    """(hi, lo) 64-bit halves of n < 2^128."""
    return n >> 64, n & _U64_MASK


def run_slab(engine_call, lo, hi, on_progress, poll_seconds=0.5):
    """(first_odd, composite bitmap as a uint8 array) for the odd numbers of [lo, hi).
    engine_call(first_hi, first_lo, n_odd, bits_ptr, done) runs the library; it runs in a
    helper thread (ctypes releases the GIL) so on_progress(chunks_done) can report
    meanwhile. Raises RuntimeError when it returns non-zero."""
    first_odd = lo | 1
    n_odd = max(0, (hi - first_odd + 1) // 2)
    bits = np.zeros((n_odd + 7) // 8, dtype=np.uint8)
    done = (ctypes.c_uint64 * 1)(0)
    result = {}
    first_hi, first_lo = split(first_odd)

    def _call():
        result["code"] = engine_call(first_hi, first_lo, n_odd,
                                     bits.ctypes.data_as(ctypes.POINTER(ctypes.c_ubyte)), done)

    worker = threading.Thread(target=_call, daemon=True)
    worker.start()
    while worker.is_alive():
        worker.join(poll_seconds)
        on_progress(done[0])
    if result.get("code", -1) != 0:
        raise RuntimeError("pt1 engine error")
    return first_odd, bits
