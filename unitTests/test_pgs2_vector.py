"""pgs2_vector produces exactly the bytes of the per-prime PGS2 writer in prime_sieve_v4_1.

Checks encode_varints() against encode_varint() on varint byte-length boundaries and random
values, and write_prime_window_offsets() against write_prime_window() on an empty window, a
single prime, small primes, and windows whose base is above 2**64. Pure Python + NumPy, runs
on Windows and WSL:
    python unitTests/test_pgs2_vector.py
"""
import os
import random
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

import prime_sieve_v4_1 as reference  # noqa: E402
import pgs2_vector  # noqa: E402


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def check_varints():
    passed = True
    boundaries = [0, 1, 127, 128, 255, 16383, 16384, 2 ** 21 - 1, 2 ** 21, 2 ** 28,
                  2 ** 35 - 1, 2 ** 56, 2 ** 63 - 1, 2 ** 63, 2 ** 64 - 1]
    rng = random.Random(7)
    randoms = [rng.randrange(0, 1 << rng.randrange(1, 64)) for _ in range(5000)]
    for label, values in (("boundaries", boundaries), ("random", randoms), ("empty", [])):
        expected = b"".join(reference.encode_varint(v) for v in values)
        got = pgs2_vector.encode_varints(np.array(values, dtype=np.uint64))
        passed &= check(got == expected, f"encode_varints {label} ({len(values)} values)")
    return passed


def primes_between(lo, hi):
    """Primes of [lo, hi) by trial division; the test windows are small."""
    def is_prime(n):
        if n < 2:
            return False
        if n % 2 == 0:
            return n == 2
        f = 3
        while f * f <= n:
            if n % f == 0:
                return False
            f += 2
        return True
    return [n for n in range(lo, hi) if is_prime(n)]


def check_windows(tmp):
    passed = True
    big = 10 ** 25
    cases = [
        ("empty", 1000, []),
        ("single prime", 1000, [1009]),
        ("small primes from 2", 0, primes_between(0, 5000)),
        ("primes 10^6..", 10 ** 6, primes_between(10 ** 6, 10 ** 6 + 20000)),
        # Not primes: values above 2**64 with gaps across varint byte-length boundaries.
        ("base above 2**64", big, [big + 1, big + 128, big + 129, big + 16513, big + 2 ** 22]),
    ]
    for label, lo, primes in cases:
        ref_path = os.path.join(tmp, "ref.bin")
        new_path = os.path.join(tmp, "new.bin")
        reference.write_prime_window(ref_path, primes, generated_at=1234567890)
        offsets = np.array([p - lo for p in primes], dtype=np.int64)
        pgs2_vector.write_prime_window_offsets(new_path, lo, offsets, generated_at=1234567890)
        with open(ref_path, "rb") as f:
            expected = f.read()
        with open(new_path, "rb") as f:
            got = f.read()
        passed &= check(got == expected, f"write_prime_window_offsets {label} "
                                         f"({len(primes)} primes, {len(expected)} bytes)")
    return passed


def main():
    passed = check_varints()
    with tempfile.TemporaryDirectory(prefix="pgs2_vector_") as tmp:
        passed &= check_windows(tmp)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
