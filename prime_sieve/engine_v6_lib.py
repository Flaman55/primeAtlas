"""ctypes binding of prime_sieve_engine_v6.so, loaded on first use (a forked worker process
loads its own copy unless the parent loaded it before the fork)."""
import ctypes
import os

_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prime_sieve_engine_v6.so")
_lib = None  # lazily loaded, SEPARATELY in each worker process


def load_lib():
    global _lib
    if _lib is None:
        if not os.path.exists(_LIB_PATH):
            raise RuntimeError(
                f"Missing {_LIB_PATH} -- build it first: gcc -O3 -shared -fPIC "
                f"prime_sieve_engine_v6.c -o prime_sieve_engine_v6.so -lprimesieve -lstdc++ -lm")
        lib = ctypes.CDLL(_LIB_PATH)
        lib.sieve_wheel_bucketed.argtypes = [
            ctypes.POINTER(ctypes.c_uint64),  # piece_lo
            ctypes.POINTER(ctypes.c_uint64),  # piece_hi
            ctypes.c_uint64,                  # n_pieces
            ctypes.c_uint64,                  # base_hi
            ctypes.c_uint64,                  # base_lo
            ctypes.c_uint64,                  # n_bits
            ctypes.c_uint64,                  # region_bits
            ctypes.c_uint64,                  # n_threads
            ctypes.c_uint64,                  # bucket_bytes (all threads)
            ctypes.POINTER(ctypes.c_ubyte),   # out_bits (SHARED buffer)
            ctypes.POINTER(ctypes.c_uint64),  # pieces_done (progress counter)
        ]
        lib.sieve_wheel_bucketed.restype = ctypes.c_int
        lib.sieve_wheel_segmented.argtypes = [
            ctypes.c_uint64,                  # stop (segmented primes are 7..stop-1)
            ctypes.c_uint64,                  # base_hi
            ctypes.c_uint64,                  # base_lo
            ctypes.c_uint64,                  # bit_lo (multiple of 64)
            ctypes.c_uint64,                  # bit_hi
            ctypes.c_uint64,                  # segment_words
            ctypes.POINTER(ctypes.c_uint64),  # out_words (SHARED buffer)
        ]
        lib.sieve_wheel_segmented.restype = ctypes.c_int
        lib.wheel_first_marked.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64,
                                           ctypes.POINTER(ctypes.c_uint64)]
        lib.wheel_first_marked.restype = ctypes.c_uint64
        lib.count_sieving_primes.argtypes = [ctypes.c_uint64]
        lib.count_sieving_primes.restype = ctypes.c_uint64
        lib.count_sieving_primes_range.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
        lib.count_sieving_primes_range.restype = ctypes.c_uint64
        lib.wheel_window_gaps.argtypes = [
            ctypes.c_void_p,                  # buf (first byte of the window)
            ctypes.c_uint64,                  # n_bytes
            ctypes.c_int64,                   # first_rel
            ctypes.c_int64,                   # span
            ctypes.c_void_p,                  # out
            ctypes.c_uint64,                  # out_cap
            ctypes.POINTER(ctypes.c_uint64),  # count_out
            ctypes.POINTER(ctypes.c_uint64),  # first_out
        ]
        lib.wheel_window_gaps.restype = ctypes.c_int64
        _lib = lib
    return _lib
