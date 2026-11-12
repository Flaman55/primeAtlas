"""Test: the pseudosquares table and the deterministic decision of prime_sieve/engine_pt_pss.h.

A. The table PSS[] (parsed from the header, runs anywhere): every entry's hex words equal its
   decimal comment; L_p = 1 (mod 8), not a square, a quadratic residue modulo every odd prime
   <= p; the primes are the primes 2..373 in order and the values never decrease; where the
   value changes from L_p to the next entry, L_p is a non-residue modulo the next prime (so it
   could not stay); every entry below 10^7 is the smallest such number (brute force);
   pt1_plan.PSS_L_373 (the Python side's copy for pt1-pss) equals the last entry.
B. is_square() and is_cube() (engine_pt_core.h, WSL: compiled into a small driver with gcc):
   k^2 and k^3 are found, k^2 +- 1 and k^3 +- 1 are not, for small k, random k and the largest
   k with k^2 resp. k^3 below 2^127.
C. pss_decide() (engine_pt_pss.h, WSL): squares and cubes of primes above 373 are rejected
   with the bases a sieve bound of n^(1/4) needs, primes are accepted, products of two
   primes above n^(1/4) are rejected (floors 12-32); without bases (n / s past L_373) the
   answer is -1, undecided.

Run from the repo root (B and C only inside WSL):
    python unitTests/test_engine_pt_pss.py
"""
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIEVE_DIR = os.path.join(ROOT, "prime_sieve")
HEADER = os.path.join(SIEVE_DIR, "engine_pt_pss.h")
U64_MAX = (1 << 64) - 1
LIMIT = 1 << 127
BRUTE_FORCE_MAX = 10 ** 7


def check(cond, label):
    print(("ok:   " if cond else "FAIL: ") + label)
    return bool(cond)


def small_primes(n):
    sieve = bytearray([1]) * (n + 1)
    sieve[0:2] = b"\x00\x00"
    for p in range(2, math.isqrt(n) + 1):
        if sieve[p]:
            sieve[p * p::p] = bytearray(len(sieve[p * p::p]))
    return [p for p in range(n + 1) if sieve[p]]


def table():
    """[(p, hex value, decimal comment)] of PSS[]."""
    with open(HEADER) as f:
        src = f.read()
    rows = re.findall(r"\{(\d+), 0x([0-9a-f]+)u, 0x([0-9a-f]+)u\},\s*/\* (\d+) \*/", src)
    return [(int(p), (int(hi, 16) << 64) | int(lo, 16), int(dec)) for p, hi, lo, dec in rows]


def is_residue(n, q):
    return pow(n % q, (q - 1) // 2, q) == 1


def pseudosquare_like(n, odd_primes):
    return n % 8 == 1 and math.isqrt(n) ** 2 != n and all(is_residue(n, q) for q in odd_primes)


def smallest_pseudosquare(odd_primes, limit):
    """Smallest non-square n = 1 (mod 8), n <= limit, residue modulo every prime given."""
    for n in range(9, limit + 1, 8):
        if pseudosquare_like(n, odd_primes):
            return n
    return None


def table_case():
    rows = table()
    primes = small_primes(373)
    passed = check([p for p, _, _ in rows] == primes, f"A: table primes are 2..373 ({len(rows)})")
    passed &= check(all(v == d for _, v, d in rows),
                    "A: every hex value equals its decimal comment "
                    f"{[p for p, v, d in rows if v != d]}")
    bad = [p for p, v, _ in rows if not pseudosquare_like(v, [q for q in primes[1:] if q <= p])]
    passed &= check(not bad, f"A: every L_p = 1 mod 8, non-square, residue mod odd q <= p {bad}")
    passed &= check(all(rows[k][1] <= rows[k + 1][1] for k in range(len(rows) - 1)),
                    "A: values never decrease")
    stays = [rows[k][0] for k in range(len(rows) - 1)
             if rows[k][1] != rows[k + 1][1] and is_residue(rows[k][1], rows[k + 1][0])]
    passed &= check(not stays, f"A: a value that changes is a non-residue mod the next prime "
                    f"{stays}")
    small = [(p, v) for p, v, _ in rows if v <= BRUTE_FORCE_MAX]
    wrong = [p for p, v in small
             if smallest_pseudosquare([q for q in primes[1:] if q <= p], v) != v]
    passed &= check(len(small) > 10 and not wrong,
                    f"A: the {len(small)} entries below 10^7 are minimal {wrong}")
    sys.path.insert(0, SIEVE_DIR)
    import pt1_plan
    passed &= check(pt1_plan.PSS_L_373 == rows[-1][1], "A: pt1_plan.PSS_L_373 equals L_373")
    return passed


DRIVER = r"""
#include <stdio.h>
#include "engine_pt_core.h"
#include "engine_pt_pss.h"

int main(void) {
    char op[16];
    unsigned long long hi, lo;
    while (scanf("%15s %llu %llu", op, &hi, &lo) == 3) {
        u128 n = ((u128)hi << 64) | lo;
        if (op[0] == 's') printf("%d\n", is_square(n));
        else if (op[0] == 'c') printf("%d\n", is_cube(n));
        else {
            unsigned long long s;
            if (scanf("%llu", &s) != 1) return 1;
            printf("%d\n", pss_decide(n, pss_bases(n, s)));
        }
        fflush(stdout);
    }
    return 0;
}
"""


class Driver:
    def __init__(self, exe):
        self.proc = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     text=True)

    def ask(self, op, n, *extra):
        line = " ".join(str(x) for x in (op, n >> 64, n & U64_MAX) + extra)
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()
        return int(self.proc.stdout.readline())

    def close(self):
        self.proc.stdin.close()
        self.proc.wait()


def build(tmp):
    src, exe = os.path.join(tmp, "pss_driver.c"), os.path.join(tmp, "pss_driver")
    with open(src, "w") as f:
        f.write(DRIVER)
    subprocess.run(["gcc", "-O2", "-I", SIEVE_DIR, src, "-o", exe, "-lprimesieve", "-lm"],
                   check=True)
    return exe


def iroot(n, k):
    r = int(round(n ** (1.0 / k)))
    while r ** k > n:
        r -= 1
    while (r + 1) ** k <= n:
        r += 1
    return r


def power_case(d, rng):
    passed = True
    for op, k in (("sq", 2), ("cube", 3)):
        top = iroot(LIMIT - 2, k)
        roots = list(range(2, 2000)) + [rng.randrange(2, top) for _ in range(3000)] + \
            [top - i for i in range(50)]
        hits = [r for r in roots if d.ask(op, r ** k) != 1]
        near = [r for r in roots if d.ask(op, r ** k - 1) or d.ask(op, r ** k + 1)]
        passed &= check(not hits, f"B: {op}: r^{k} found for {len(roots)} roots up to {top} "
                        f"{hits[:3]}")
        passed &= check(not near, f"B: {op}: r^{k} +- 1 not a power {near[:3]}")
    return passed


def is_prime(n):
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41):
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while d % 2 == 0:
        d, s = d // 2, s + 1
    for a in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41):
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def next_prime(n):
    n |= 1
    while not is_prime(n):
        n += 2
    return n


def decide(d, n):
    """pss_decide(n) with the sieve bound n^(1/4) the pt1 default gives."""
    return d.ask("det", n, iroot(n, 4))


def decide_case(d, rng):
    passed = True
    squares, cubes, primes, semis = [], [], [], []
    for _ in range(300):
        p = next_prime(rng.randrange(400, 10 ** 10))   # p^3 < 10^30: inside the table
        squares.append(p * p)
        cubes.append(p ** 3)
    for floor in (12, 18, 25, 30, 32):
        for _ in range(40):
            primes.append(next_prime(rng.randrange(10 ** floor, 2 * 10 ** floor)))
            a = next_prime(rng.randrange(10 ** (floor // 4 + 1), 10 ** (floor // 2)))
            semis.append(a * next_prime(rng.randrange(10 ** floor // a, 2 * 10 ** floor // a)))
    passed &= check(all(decide(d, n) == 0 for n in squares), "C: p^2 (p > 373) rejected")
    passed &= check(all(decide(d, n) == 0 for n in cubes), "C: p^3 (p > 373) rejected")
    passed &= check(all(decide(d, n) == 1 for n in primes),
                    f"C: {len(primes)} primes on floors 12-32 accepted")
    passed &= check(all(decide(d, n) == 0 for n in semis),
                    f"C: {len(semis)} products of two primes above n^(1/4) rejected")
    big = next_prime(1 << 54)
    passed &= check(decide(d, big * big) == 0 and decide(d, big) == 1,
                    "C: p ~ 2^54: p^2 rejected, p accepted")
    passed &= check(d.ask("det", primes[-1], 1) == -1, "C: no bases (n / s past L_373) -> -1")
    return passed


def main():
    passed = table_case()
    if not sys.platform.startswith("linux"):
        print("SKIPPED B, C (WSL-only)")
    elif shutil.which("gcc") is None:
        passed = check(False, "gcc found")
    else:
        rng = random.Random(20261112)
        tmp = tempfile.mkdtemp(prefix="pt_pss_")
        try:
            d = Driver(build(tmp))
            passed &= power_case(d, rng)
            passed &= decide_case(d, rng)
            d.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if not passed:
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
