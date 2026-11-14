"""
test_irreducibility_core.py -- tests for the pure modules of Research -> Irreducibility:
irreducibility_core.py (residues, Euclid, radices) and irreducibility_comb.py (sech comb).

Usage:
    python unitTests/test_irreducibility_core.py
"""
import ast
import math
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
# primeatlas/__init__.py imports manifest.py, which needs prime_sieve on the path.
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from primeatlas.research import irreducibility_core as core
from primeatlas.research import irreducibility_comb as comb

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _is_prime(n):
    return n >= 2 and all(n % d for d in range(2, math.isqrt(n) + 1))


def _exp_lambda(m):
    """p when m = p^k for a prime p, else 1 (by trial division)."""
    for p in range(2, m + 1):
        if m % p == 0:
            while m % p == 0:
                m //= p
            return p if m == 1 else 1
    return 1


def test_count_mod_and_euclid():
    check(all(core.count_mod(d, t) == t % d for d in range(1, 30) for t in range(200)),
          "count_mod(d, t) == t % d for d < 30, t < 200")
    check(all(core.euclid(a, b) == math.gcd(a, b) for a in range(60) for b in range(60)),
          "euclid(a, b) == gcd(a, b) for a, b < 60, zeros included")


def test_radices_consecutive():
    for n in (2, 3, 60, 500):
        mods = list(range(2, n + 1))
        rads = core.radices(mods)
        check(rads == [_exp_lambda(m) for m in mods],
              f"radices(2..{n}) == exp(Lambda(m)) for every m")
        check(all((r == m) == _is_prime(m) for m, r in zip(mods, rads)),
              f"2..{n}: radix == modulus exactly for primes")


def test_radices_arbitrary():
    check(core.radices([6, 35]) == [6, 35], "[6, 35]: both receive their whole value")
    check(core.radices([4, 4]) == [4, 1], "[4, 4]: the repeated modulus receives radix 1")
    check(core.radices([6, 4]) == [6, 2], "[6, 4]: 4 receives radix 2")
    check(core.radices([]) == [], "empty list: no radices")
    shuffled = [7, 4, 9, 2, 8, 3, 6, 5, 10]
    rads = core.radices(shuffled)
    check(math.prod(rads) == math.lcm(*shuffled),
          "permuted 2..10: product of radices == lcm (radices themselves differ)")
    check(rads != [_exp_lambda(m) for m in shuffled],
          "permuted 2..10: radices follow the order, not exp(Lambda(m))")


def test_no_product_formed():
    # Every intermediate value in prod_mod / gcd_prod stays below c ** 2, so the product of
    # the radices is never formed: a wrapper int that records the largest operand seen.
    seen = []

    class Traced(int):
        def __mul__(self, other):
            res = int(self) * int(other)
            seen.append(res)
            return Traced(res)
        __rmul__ = __mul__

        def __mod__(self, other):
            return Traced(int(self) % int(other))

        def __rmod__(self, other):
            return Traced(int(other) % int(self))

        def __floordiv__(self, other):
            return Traced(int(self) // int(other))

    mods = list(range(2, 200))
    core.radices([Traced(m) for m in mods])
    check(seen and max(seen) < max(mods) ** 2,
          f"radices(2..199): largest product formed {max(seen) if seen else 0} < {max(mods) ** 2}")


def test_core_imports():
    for name in ("irreducibility_core.py", "irreducibility_comb.py"):
        path = os.path.join(_REPO_ROOT, "primeatlas", "research", name)
        tree = ast.parse(open(path, encoding="utf-8").read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                mods.add(node.module or "")
        bad = [m for m in mods if any(k in m for k in ("prim", "sieve", "sympy", "layout"))]
        check(not bad, f"{name} imports nothing about primes ({sorted(mods)})")


def test_comb():
    ok = all(comb.comb_resid(3.0, a, b) == a % b for a in range(301) for b in range(1, 301))
    check(ok, "comb_resid(3, a, b) == a % b for a <= 300, 1 <= b <= 300")
    check(comb.comb_resid(2.0, 3, 2) != 3 % 2, "scale 2: reading 3 mod 2 from the comb fails")
    check(abs(comb.sech(0.0) - 1.0) < 1e-12 and comb.sech(1000.0) == 0.0
          and comb.sech(-1000.0) == 0.0, "sech(0) == 1, no overflow far from 0")
    peaks = [t for t in range(31) if comb.sech_comb(3.0, 7, t) > comb.PEAK_LEVEL]
    check(peaks == [0, 7, 14, 21, 28], "comb peaks over 0..30 at scale 3 == multiples of 7")
    check(comb.last_peak(3.0, 7, 30) == 28 and comb.last_peak(3.0, 7, 0) == 0,
          "last_peak(3, 7, 30) == 28, last_peak(.., 0) == 0")
    check(comb.sech_comb(3.0, 5, 5) > 0.5 > comb.sech_comb(3.0, 5, 4)
          and comb.sech_comb(3.0, 5, 7.5) < 0.5, "the comb at real steps: peak at 5, low between")


def main():
    test_count_mod_and_euclid()
    test_radices_consecutive()
    test_radices_arbitrary()
    test_no_product_formed()
    test_core_imports()
    test_comb()
    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
