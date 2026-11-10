"""ctypes binding of engine v7.2, prime_sieve_engine_v7_2.so: engine v7.0's functions and
signatures (engine_v7_lib.py) except sieve_wheel_bucketed(), which takes the gear span after
jump_from. Loaded on first use (a forked worker process loads its own copy unless the parent
loaded it before the fork)."""
import ctypes

import engine_v6_lib

V7_2 = "prime_sieve_engine_v7_2.so"
_lib = None


def load_lib():
    global _lib
    if _lib is None:
        lib = engine_v6_lib.load_lib(V7_2)
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
            ctypes.c_uint64,                  # jump_from (0 = gear off)
            ctypes.c_uint64,                  # gear_span (<= buffer span: the buffer's)
            ctypes.c_double,                  # block_factor
            ctypes.POINTER(ctypes.c_ubyte),   # out_bits (SHARED buffer)
            ctypes.POINTER(ctypes.c_uint64),  # pieces_done (progress counter)
        ]
        _lib = lib
    return _lib
