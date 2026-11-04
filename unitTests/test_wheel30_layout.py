"""prime_sieve/wheel30_layout.py: the wheel-30 buffer layout of engine v6 and its window
unpacking, against a plain sieve.

A reference buffer is built in Python (every composite coprime to 30 marked) for ranges that
start at 0, 1, a non-multiple of 30 and above 10^12; window_prime_offsets() and
window_prime_count() must give exactly the primes of each window, for windows that cut bytes
at both ends, hold 1, 2, 3, 5, one number, or none. buffer_bytes() covers the range and
nothing more than one byte beyond it. Runs anywhere (no native library):
    python unitTests/test_wheel30_layout.py
"""
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

import wheel30_layout as wl  # noqa: E402


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def is_prime(n):
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13):
        if n % p == 0:
            return n == p
    for d in range(17, math.isqrt(n) + 1, 2):
        if n % d == 0:
            return False
    return True


def reference_buffer(lo, hi):
    base = wl.buffer_base(lo)
    buf = np.zeros(wl.buffer_bytes(lo, hi), dtype=np.uint8)
    for b in range(len(buf)):
        for j, r in enumerate(wl.RESIDUES):
            n = base + wl.WHEEL * b + r
            if n > 1 and not is_prime(n):
                buf[b] |= 1 << j
    return base, buf


def check_range(lo, hi, windows):
    base, buf = reference_buffer(lo, hi)
    passed = check(base % 30 == 0 and base <= lo < base + 30, f"[{lo}, {hi}): base {base}")
    passed &= check(base + 30 * len(buf) >= hi > base + 30 * (len(buf) - 1),
                    f"[{lo}, {hi}): {len(buf)} bytes cover the range and no more")
    for a, b in windows:
        want = [n - a for n in range(a, b) if is_prime(n)]
        got = wl.window_prime_offsets(buf, base, a, b)
        passed &= check(got.dtype == np.int64 and got.tolist() == want,
                        f"window [{a}, {b}): offsets of its {len(want)} primes")
        passed &= check(wl.window_prime_count(buf, base, a, b) == len(want),
                        f"window [{a}, {b}): count {len(want)}")
    return passed


def main():
    passed = check(wl.buffer_bytes(10, 10) == 0, "empty range has no bytes")
    passed &= check_range(0, 1000, [(0, 1000), (0, 1), (1, 2), (2, 3), (0, 7), (5, 6),
                                    (3, 4), (6, 7), (29, 31), (100, 100), (997, 1000)])
    passed &= check_range(1, 1001, [(1, 1001), (1, 31), (31, 61), (7, 8), (8, 9)])
    passed &= check_range(47, 2047, [(47, 547), (547, 1047), (1047, 2047), (49, 50)])
    big = 10 ** 12 + 7
    passed &= check_range(big, big + 3000, [(big, big + 1000), (big + 1000, big + 2000),
                                           (big + 2000, big + 3000), (big + 11, big + 12)])
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
