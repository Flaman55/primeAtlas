"""WSL test: the v5 engine's per-prime phase (phase_first_marked_bit() in
prime_sieve_engine_v5.c) equals exact integer arithmetic.

phase_first_marked_bit(first_hi, first_lo, p) is the bit index, relative to the odd number
`first`, of the first odd multiple of p at or above `first` that is not p itself. The engine
computes first mod p by a double-precision quotient with a one-p correction when
first / p < 2^50 and p < 2^53, and by an exact division otherwise. Cases cover both paths and
their boundaries (p around first >> 50 and around 2^53), p dividing first, p above first
(low floors, where the guard skips p itself), first just above 2^64 and near 2^127, and
random pairs over every floor up to 10^38. p stays below 2^62: sieving primes are at most
sqrt(first + range), far below that on every floor the engine runs.

Run inside WSL from the repo root:
    python3 unitTests/test_engine_v5_phase.py
"""
import ctypes
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_PATH = os.path.join(ROOT, "prime_sieve", "prime_sieve_engine_v5.so")
MASK64 = (1 << 64) - 1
failures = []


def expected(first, p):
    k = (-first) % p
    if k & 1:
        k += p
    i = k >> 1
    if first + 2 * i == p:
        i += p
    return i


def odd(n):
    return n | 1


def cases():
    rng = random.Random(20261031)
    out = []
    firsts = [1, 3, 5, 15, 2 ** 64 - 1, 2 ** 64 + 1, 2 ** 64 + 3, 2 ** 127 - 1]
    for floor in range(0, 39):
        firsts += [odd(10 ** floor), odd(10 ** floor + 1), odd(10 ** floor - 1)]
    small_p = [3, 5, 7, 11, 13, 17, 19, 23, 1009, 65537, 1000003]
    for first in firsts:
        boundary = first >> 50
        ps = list(small_p)
        ps += [odd(boundary + d) for d in range(-4, 5) if boundary + d >= 3]
        ps += [odd(2 ** 53 + d) for d in (-5, -3, -1, 1, 3)]
        ps += [odd(2 ** 62 - 1)]
        ps += [odd(rng.randrange(3, 2 ** 62)) for _ in range(40)]
        ps += [odd(rng.randrange(max(3, boundary), max(4, boundary * 1000))) for _ in range(40)]
        out += [(first, p) for p in ps if 3 <= p < 2 ** 62]
    # p dividing first: first = p * m with m odd.
    for _ in range(3000):
        p = odd(rng.randrange(3, 2 ** rng.randrange(3, 62)))
        m = odd(rng.randrange(1, 2 ** rng.randrange(1, 64)))
        if p * m < 2 ** 128:
            out.append((p * m, p))
            out.append((p * m + 2 * p, p))
    for _ in range(20000):
        first = odd(rng.randrange(1, 10 ** rng.randrange(1, 39)))
        p = odd(rng.randrange(3, 2 ** rng.randrange(2, 63)))
        out.append((first, p))
    return out


def main():
    lib = ctypes.CDLL(LIB_PATH)
    fn = getattr(lib, "phase_first_marked_bit", None)
    if fn is None:
        print("FAIL: phase_first_marked_bit is not exported by prime_sieve_engine_v5.so")
        sys.exit(1)
    fn.restype = ctypes.c_uint64
    fn.argtypes = [ctypes.c_uint64] * 3
    all_cases = cases()
    for first, p in all_cases:
        got = fn(first >> 64, first & MASK64, p)
        want = expected(first, p)
        if got != want:
            failures.append((first, p, got, want))
    for first, p, got, want in failures[:20]:
        print(f"FAIL: first={first} p={p}: got {got}, expected {want}")
    if failures:
        print(f"FAIL: {len(failures)} of {len(all_cases)} cases differ")
        sys.exit(1)
    print(f"{len(all_cases)} cases match")
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    if not sys.platform.startswith("linux"):
        print("SKIPPED (WSL-only)")
        sys.exit(0)
    main()
