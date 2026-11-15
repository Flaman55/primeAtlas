"""
test_irreducibility_core.py -- tests for the pure modules of Research -> Irreducibility:
irreducibility_core.py (residues, Euclid, radices, multiplicative counting),
irreducibility_comb.py (sech comb) and irreducibility_multiplicative.py (the cycle of g modulo q,
its order, the discrete-log step and the square reading of T9).

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
from primeatlas.research import irreducibility_multiplicative as mult

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
    for name in ("irreducibility_core.py", "irreducibility_comb.py",
                 "irreducibility_multiplicative.py"):
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


def test_mul_count():
    check(all(core.mul_count(g, q, t) == pow(g, t, q) for g in range(40) for q in range(1, 40)
              for t in range(50)), "mul_count(g, q, t) == g^t mod q for g < 40, q < 40, t < 50")
    check(core.mul_count(7, 1, 0) == 0 and core.mul_count(0, 5, 0) == 1,
          "step 0 is resid(1, q): 0 for q = 1, 1 otherwise")
    src = open(os.path.join(_REPO_ROOT, "primeatlas", "research", "irreducibility_core.py"),
               encoding="utf-8").read()
    body = src.split("def mul_count", 1)[1].split("\ndef ", 1)[0]
    check("pow(" not in body and "**" not in body, "mul_count counts: no power is taken")


def _order(g, q):
    if math.gcd(g, q) != 1:
        return None
    return next(t for t in range(1, q + 1) if pow(g, t, q) == 1 % q)


def _least_root(q):
    """The least primitive root of the prime q, by the prime factors of q - 1."""
    if q == 2:
        return 1
    n, ps, p = q - 1, [], 2
    while p * p <= n:
        if n % p == 0:
            ps.append(p)
            while n % p == 0:
                n //= p
        p += 1
    if n > 1:
        ps.append(n)
    return next(g for g in range(2, q) if all(pow(g, (q - 1) // p, q) != 1 for p in ps))


def test_order_and_auto():
    check(all(mult.mul_order(g, q) == _order(g, q) for q in range(2, 80) for g in range(1, q)),
          "mul_order(g, q) == the least t > 0 with g^t = 1 mod q, None when gcd(g, q) > 1")
    primes = [q for q in range(2, mult.MAX_Q + 1) if _is_prime(q)]
    worst = max(_least_root(q) for q in primes)
    check(worst <= mult.AUTO_MAX_G,
          f"AUTO_MAX_G covers the least primitive root of every prime up to MAX_Q ({worst})")
    sample = [q for q in primes if q < 3000] + primes[-20:] + [71761]
    check(all(mult.auto_generator(q) == (_least_root(q), q - 1) for q in sample),
          "Auto on a prime q: the least primitive root, order q - 1")
    check(mult.auto_generator(2) == (1, 1) and mult.auto_generator(3) == (2, 2),
          "Auto: q = 2 gives g = 1 (order 1), q = 3 gives g = 2")
    for q in (4, 9, 15, 91, 1001):
        orders = {g: _order(g, q) for g in range(1, min(q, mult.AUTO_MAX_G + 1))}
        best = max(o for o in orders.values() if o)
        want = min(g for g, o in orders.items() if o == best)
        check(mult.auto_generator(q) == (want, best),
              f"Auto on composite q = {q}: the smallest g of the largest order ({want}, {best})")


def test_cycle():
    a = mult.analyze(23, 5, 10)
    check(a["values"] == [pow(5, t, 23) for t in range(23)]
          and a["counts"] == [t % 22 for t in range(23)],
          "q = 23, g = 5: values g^t mod q and counts t mod (q - 1) over t = 0..q - 1")
    check(a["order"] == 22 and a["primitive"] and a["pairs_break"] is None,
          "a primitive root: order q - 1, equal values at the same pairs of steps")
    t = a["step"]
    check(a["r"] == 10 and pow(5, t, 23) == 10 and 0 <= t < 22
          and a["square"] is (t % 2 == 0) and a["square"] is (pow(10, 11, 23) == 1),
          f"N = 10: the step reaching N mod q, its parity is Euler's criterion (t = {t})")
    ok = True
    for q in [q for q in range(3, 200) if _is_prime(q)]:
        g = _least_root(q)
        for n in range(0, 3 * q):
            a = mult.analyze(q, g, n)
            want = None if n % q == 0 else pow(n, (q - 1) // 2, q) == 1
            ok &= a["square"] is want and (a["step"] is None) == (n % q == 0)
    check(ok, "every odd prime q < 200, every N < 3q: parity of the step == Euler, q | N: no step")
    a = mult.analyze(23, 2, 5)
    check(a["order"] == 11 and not a["primitive"] and a["pairs_break"] == (0, 11)
          and a["square"] is None,
          "g = 2 mod 23 (order 11): pairs break at steps 0 and 11, no square claim")
    check(a["step"] is None, "5 is not reached by 2 mod 23 (5 is not a square)")
    a = mult.analyze(9, 2, 4)
    check(a["order"] == 6 and not a["primitive"] and a["pairs_break"] == (0, 6)
          and a["square"] is None, "q = 9 (not prime): order 6 < 8, pairs break, no claim")
    a = mult.analyze(10, 2, 3)
    check(a["order"] is None and not a["primitive"] and a["pairs_break"] is not None
          and a["square"] is None, "gcd(g, q) > 1: no order, pairs break, no claim")
    a = mult.analyze(2, 1, 7)
    check(a["values"] == [1, 1] and a["counts"] == [0, 0] and a["order"] == 1 and a["primitive"]
          and a["pairs_break"] is None and a["step"] == 0 and a["square"] is None,
          "q = 2: g = 1, order 1, pairs equal; no square question")
    a = mult.analyze(23, 5, 46)
    check(a["r"] == 0 and a["step"] is None and a["square"] is None, "q | N: N mod q = 0, no step")
    big = 10 ** 40 + 7
    a = mult.analyze(23, 5, big)
    check(a["r"] == big % 23, "N far above q: N mod q from its residue")


def test_table_steps():
    check(mult.table_steps(23, 7) == list(range(23)), "q = 23: every step is a row")
    q = 1009
    head = list(range(mult.HEAD_ROWS))
    tail = list(range(q - mult.TAIL_ROWS, q))
    check(mult.table_steps(q, 500) == head + [None] + list(range(498, 503)) + [None] + tail,
          "q = 1009, step 500: head rows, the step with 2 around it, tail rows")
    check(mult.table_steps(q, 3) == head + [None] + tail, "a step inside the head adds no rows")
    check(mult.table_steps(q, None) == head + [None] + tail, "no step: head and tail")
    check(mult.table_steps(q, q - mult.TAIL_ROWS - 3)
          == head + [None] + list(range(q - mult.TAIL_ROWS - 5, q)),
          "a step next to the tail joins it without a gap")
    check(mult.table_steps(mult.TABLE_ALL, 0) == list(range(mult.TABLE_ALL))
          and None in mult.table_steps(mult.TABLE_ALL + 1, 0),
          "up to TABLE_ALL steps every row is shown")


def test_comb_returns():
    for q in [q for q in range(2, mult.COMB_MAX_Q + 1) if _is_prime(q)]:
        g = _least_root(q)
        for s in (comb.PROVED_SCALE, 8.0):
            peaks, ones = mult.comb_returns(s, q, g)
            if peaks != ones or ones[0] != 0 or ones[-1] != 2 * (q - 1):
                check(False, f"q = {q}, scale {s}: peaks {peaks[:5]} vs returns {ones[:5]}")
                return
    check(True, "every prime q up to COMB_MAX_Q: comb peaks of modulus q - 1 over 0..2(q - 1) "
                "== the steps where g^t mod q returns to 1")
    peaks, ones = mult.comb_returns(8.0, 23, 2)
    check(set(peaks) < set(ones) and 11 in ones,
          "g = 2 mod 23 (order 11) returns to 1 also between the peaks")


def main():
    test_count_mod_and_euclid()
    test_radices_consecutive()
    test_radices_arbitrary()
    test_no_product_formed()
    test_core_imports()
    test_comb()
    test_mul_count()
    test_order_and_auto()
    test_cycle()
    test_table_steps()
    test_comb_returns()
    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
