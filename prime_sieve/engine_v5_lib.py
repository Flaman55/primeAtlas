"""ctypes binding of prime_sieve_engine_v5.so, loaded on first use (a forked worker process
loads its own copy unless the parent loaded it before the fork)."""
import ctypes
import os

_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prime_sieve_engine_v5.so")
_lib = None  # lazily loaded, SEPARATELY in each worker process


def load_lib():
    global _lib
    if _lib is None:
        if not os.path.exists(_LIB_PATH):
            raise RuntimeError(
                f"Missing {_LIB_PATH} -- build it first: gcc -O3 -shared -fPIC "
                f"prime_sieve_engine_v5.c -o prime_sieve_engine_v5.so -lprimesieve -lstdc++ -lm")
        lib = ctypes.CDLL(_LIB_PATH)
        lib.sieve_odd_bucketed.argtypes = [
            ctypes.POINTER(ctypes.c_uint64),  # piece_lo
            ctypes.POINTER(ctypes.c_uint64),  # piece_hi
            ctypes.c_uint64,                  # n_pieces
            ctypes.c_uint64,                  # first_odd_hi
            ctypes.c_uint64,                  # first_odd_lo
            ctypes.c_uint64,                  # n_bits
            ctypes.c_uint64,                  # region_bits
            ctypes.c_uint64,                  # n_threads
            ctypes.c_uint64,                  # bucket_bytes (all threads)
            ctypes.POINTER(ctypes.c_ubyte),   # out_bits (SHARED buffer)
            ctypes.POINTER(ctypes.c_uint64),  # pieces_done (progress counter)
        ]
        lib.sieve_odd_bucketed.restype = ctypes.c_int
        lib.sieve_odd_segmented.argtypes = [
            ctypes.c_uint64,                  # stop (segmented primes are 3..stop-1)
            ctypes.c_uint64,                  # first_odd_hi
            ctypes.c_uint64,                  # first_odd_lo
            ctypes.c_uint64,                  # bit_lo (multiple of 64)
            ctypes.c_uint64,                  # bit_hi
            ctypes.c_uint64,                  # segment_words
            ctypes.POINTER(ctypes.c_uint64),  # out_words (SHARED buffer)
        ]
        lib.sieve_odd_segmented.restype = ctypes.c_int
        lib.count_sieving_primes.argtypes = [ctypes.c_uint64]
        lib.count_sieving_primes.restype = ctypes.c_uint64
        lib.count_sieving_primes_range.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
        lib.count_sieving_primes_range.restype = ctypes.c_uint64
        _lib = lib
    return _lib
