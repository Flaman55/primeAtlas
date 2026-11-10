"""ctypes binding of engine v7.0, prime_sieve_engine_v7_0.so (and of any .so with its
signatures, such as v7.2's): v6.1's functions and signatures (engine_v6_lib.py) except
sieve_wheel_bucketed(), which takes the jump gear's jump_from and block factor before the
output buffer. Loaded on first use, once per .so (a forked worker process loads its own copy
unless the parent loaded it before the fork)."""
import ctypes

import engine_v6_lib

V7_0 = "prime_sieve_engine_v7_0.so"
_libs = {}


def load_lib(name=V7_0):
    lib = _libs.get(name)
    if lib is None:
        lib = engine_v6_lib.load_lib(name)
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
            ctypes.c_double,                  # block_factor
            ctypes.POINTER(ctypes.c_ubyte),   # out_bits (SHARED buffer)
            ctypes.POINTER(ctypes.c_uint64),  # pieces_done (progress counter)
        ]
        _libs[name] = lib
    return lib
