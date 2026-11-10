"""ctypes binding of engine v7.2, prime_sieve_engine_v7_2.so: the same functions and signatures
as engine v7.0 (engine_v7_lib.py), only the .so differs. Loaded on first use (a forked worker
process loads its own copy unless the parent loaded it before the fork)."""
import engine_v7_lib

V7_2 = "prime_sieve_engine_v7_2.so"


def load_lib():
    return engine_v7_lib.load_lib(V7_2)
