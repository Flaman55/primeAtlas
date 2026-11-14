"""
test_irreducibility_blocks.py -- tests for the residue-level modules of Research ->
Irreducibility beyond the radices: irreducibility_residues.py (mixed radix, comparison, blocks,
interval atoms, arithmetic; mirrors Defs.lean), irreducibility_layout.py (block layouts, W,
fitting a layout to a number, the parameter sweep), irreducibility_ops.py (the operations
shown in the Arithmetic sub-tab) and irreducibility_selftest.py (the random self-tests).
Every result is compared with plain integer arithmetic.

Usage:
    python unitTests/test_irreducibility_blocks.py
"""
import ast
import math
import os
import random
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from primeatlas.research import irreducibility_core as core
from primeatlas.research import irreducibility_layout as layout
from primeatlas.research import irreducibility_ops as ops
from primeatlas.research import irreducibility_residues as res
from primeatlas.research import irreducibility_selftest as selftest

# fmt_big output holds a thin space and a middle dot, which a cp1250 console cannot print.
sys.stdout.reconfigure(errors="backslashreplace")

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _is_prime(n):
    return n >= 2 and all(n % d for d in range(2, math.isqrt(n) + 1))


def _lcm(xs):
    return math.lcm(*xs) if xs else 1


def _cmp(x, y):
    return (x > y) - (x < y)


def _random_moduli(rng, count, top):
    return [rng.randint(1, top) for _ in range(count)]


def test_mixed_radix():
    rng = random.Random(11)
    ok_digits = ok_eval = ok_radices = True
    for _ in range(400):
        mods = _random_moduli(rng, rng.randint(1, 7), 40)
        w = _lcm(mods)
        n = rng.randrange(w)
        ds = res.to_mixed_radix(mods, [n % m for m in mods])
        ok_digits &= ds is not None and all(d < s for d, s in ds)
        ok_radices &= ds is not None and [s for _, s in ds] == core.radices(mods)
        ok_eval &= ds is not None and res.eval_digits(ds) == n
        for c in (1, 2, 7, 30, 97):
            ok_eval &= ds is not None and res.eval_mod(ds, c) == n % c
    check(ok_digits, "to_mixed_radix: every digit below its radix")
    check(ok_radices, "to_mixed_radix: the radices are radices(moduli)")
    check(ok_eval, "eval of the digits == n, eval_mod(c) == n % c")
    check(res.to_mixed_radix([4, 6], [1, 2]) is None,
          "incompatible residues (odd mod 4, even mod 6) give None")
    check(res.to_mixed_radix([], []) == [], "no moduli: empty representation")


def test_inv_mod():
    ok = all(a * res.inv_mod(a, b) % b == 1 for b in range(2, 80) for a in range(1, 200)
             if math.gcd(a, b) == 1)
    check(ok, "inv_mod(a, b) * a == 1 mod b for coprime a, b")
    check(res.inv_mod(5, 1) == 0 and res.inv_mod(4, 6) == 0,
          "inv_mod is 0 for b = 1 and for a non-invertible a (Lean invMod)")
    check(all(1 <= res.inv_mod(a, 13) < 13 for a in range(1, 13)), "inverse lies in 1..b-1")


def test_compare():
    rng = random.Random(12)
    ok = True
    for _ in range(500):
        mods = _random_moduli(rng, rng.randint(1, 6), 30)
        w = _lcm(mods)
        x, y = rng.randrange(w), rng.randrange(w)
        if rng.random() < 0.2:
            y = x
        elif rng.random() < 0.3:
            y = min(w - 1, x + 1)
        ok &= res.compare_res(mods, [x % m for m in mods], [y % m for m in mods]) == _cmp(x, y)
    check(ok, "compare_res == compare(x, y) for x, y < W")


def test_blocks():
    rng = random.Random(13)
    ok_block = ok_extend = ok_flat = ok_cmp = True
    for _ in range(300):
        members = _random_moduli(rng, rng.randint(1, 4), 12)
        n = rng.randrange(10 ** 6)
        ok_block &= res.block_modulus(members, [n % m for m in members]) == (
            _lcm(members), n % _lcm(members))
        target = _random_moduli(rng, 5, 50)
        mods = _random_moduli(rng, rng.randint(1, 5), 25)
        x = rng.randrange(_lcm(mods))
        ok_extend &= res.base_extend(mods, [x % m for m in mods], target) == [x % t for t in target]
    for _ in range(300):
        D = layout.blocks(2, rng.randint(1, 3), rng.randint(1, 3))
        K = layout.blocks(D[-1][-1] + 1 + rng.randint(0, 4), rng.randint(1, 3), rng.randint(1, 2))
        n = rng.randrange(layout.capacity(D, K))
        rep = layout.block_rep_of(n, D, K)
        q = [_lcm(b) for b in D + K]
        ok_flat &= res.flatten(rep) == (q, [n % c for c in q])
        D2 = layout.blocks(2, rng.randint(1, 3), rng.randint(1, 3))
        K2 = layout.blocks(D2[-1][-1] + 1 + rng.randint(0, 4), rng.randint(1, 3), 1)
        cap = min(layout.capacity(D, K), layout.capacity(D2, K2))
        x = rng.randrange(cap)
        y = rng.choice([x, (x + 1) % cap, (x + cap - 1) % cap, rng.randrange(cap)])
        verdict = res.compare_blocks(layout.block_rep_of(x, D, K), layout.block_rep_of(y, D2, K2))
        ok_cmp &= verdict["verdict"] == _cmp(x, y)
    check(ok_block, "block_modulus(M, [n]_M) == (W(M), n mod W(M))")
    check(ok_extend, "base_extend gives [x]_T")
    check(ok_flat, "flatten(BlockRep.of(n, D, K)) == (Q, [n]_Q)")
    check(ok_cmp, "compare_blocks == compare(n, n') on different layouts")
    v = res.compare_blocks(layout.block_rep_of(12345678, layout.blocks(2, 3, 3),
                                               layout.blocks(11, 3, 3)),
                           layout.block_rep_of(12345679, layout.blocks(2, 4, 2),
                                               layout.blocks(13, 3, 3)))
    check(v["verdict"] == -1 and 0 <= v["at"] < len(v["moduli"])
          and v["digits_x"][v["at"]] < v["digits_y"][v["at"]]
          and all(a == b for a, b in zip(v["digits_x"][v["at"] + 1:], v["digits_y"][v["at"] + 1:])),
          "12345678 vs 12345679: decided at the first differing digit from the top")
    check(res.union([2, 3, 4], [4, 5, 3, 6]) == [2, 3, 4, 5, 6], "union keeps order, no repeats")


def test_atoms():
    ok = True
    for lo in range(1, 60):
        for hi in range(lo, lo + 70):
            expected = [p for p in range(2, hi - lo + 1) if _is_prime(p)
                        and res.first_multiple_from(lo, p) + p <= hi]
            ok &= res.interval_atoms(lo, hi) == expected
    check(ok, "interval_atoms(lo, hi) == primes p with a, a + p in [lo, hi], p | a")
    check(all(lo <= res.first_multiple_from(lo, k) < lo + k
              and res.first_multiple_from(lo, k) % k == 0
              for lo in range(0, 50) for k in range(1, 20)),
          "first_multiple_from: least multiple of k >= lo")
    check(res.interval_atoms(5, 5) == [], "one-point interval has no atoms")


def test_arithmetic():
    rng = random.Random(14)
    ok_ring = ok_flags = ok_div = ok_addr = True
    for _ in range(400):
        mods = _random_moduli(rng, rng.randint(1, 5), 30)
        w = _lcm(mods)
        x, y = rng.randrange(w), rng.randrange(w)
        rx, ry = [x % m for m in mods], [y % m for m in mods]
        e = rng.randint(0, 7)
        ok_ring &= res.add_res(mods, rx, ry) == [(x + y) % m for m in mods]
        ok_ring &= res.sub_res(mods, rx, ry) == [(x - y) % m for m in mods]
        ok_ring &= res.mul_res(mods, rx, ry) == [x * y % m for m in mods]
        ok_ring &= res.pow_res(mods, rx, e) == [pow(x, e, m) for m in mods]
        ok_flags &= res.add_overflow(mods, rx, ry) == (x + y >= w)
        ok_flags &= res.sub_underflow(mods, rx, ry) == (x < y)
        t = rng.randint(1, 40)
        xt = x - x % t
        qm = res.div_moduli(mods, t)
        ok_div &= res.exact_div_res(mods, [xt % m for m in mods], t) == [xt // t % m for m in qm]
        r, q = res.div_mod_res(mods, rx, t)
        ok_div &= r == x % t and q == [x // t % m for m in qm]
        if x > 0:
            i, k = res.address_res(mods, rx, t)
            kk = (x - 1) // t + 1
            ok_addr &= i == (x - 1) % t + 1 and k == [kk % m for m in qm]
    check(ok_ring, "add/sub/mul/pow_res == the integer result on every modulus")
    check(ok_flags, "add_overflow <=> x + y >= W, sub_underflow <=> x < y")
    check(ok_div, "exact_div_res and div_mod_res == x / t and (x mod t, x // t)")
    check(ok_addr, "address_res == (i, [k]) with x = T(k - 1) + i, 1 <= i <= T")


def test_layout():
    check(layout.blocks(2, 3, 3) == [[2, 3, 4], [5, 6, 7], [8, 9, 10]], "blocks(2, 3, 3)")
    D, K = layout.blocks(2, 3, 3), layout.blocks(11, 3, 3)
    r = layout.ranges(D, K)
    check(r["w_blocks"] == 2520 and r["w_quot"] == _lcm(range(11, 20))
          and r["w"] == _lcm(range(2, 20)) and r["nominal"] == r["w_blocks"] * r["w_quot"]
          and r["max_block"] == _lcm([17, 18, 19]),
          "ranges: W(D), W(K), W of all moduli, nominal W(D)·W(K), largest block modulus")
    rep = layout.block_rep_of(12345678, D, K)
    check(rep["residues"] == [[12345678 % m for m in b] for b in D]
          and rep["quot_residues"] == [[12345678 // 2520 % m for m in b] for b in K],
          "block_rep_of: member residues of n and of n // W(D)")
    ok = True
    for n in (1, 2, 99, 12345678, 10 ** 12, 10 ** 24, 3 ** 50):
        for z in (1, 2, 3, 5):
            f = layout.fit_for(n, z, z)
            w_d = _lcm([m for b in f["D"] for m in b])
            ok &= layout.capacity(f["D"], f["K"]) > n and (w_d > math.isqrt(n) or f["dc"] == 80)
            ok &= f["ks"] == f["ds"] + f["dz"] * f["dc"] and f["K"] == layout.blocks(
                f["ks"], f["kz"], f["kc"])
    check(ok, "fit_for(n): W(D) > sqrt(n), W > n, quotient blocks start right after D")
    params = dict(ds=2, dz=3, dc=3, ks=11, kz=3, kc=3)
    rows = layout.sweep(params)
    check([row["key"] for row in rows] == ["ds", "dz", "dc", "ks", "kz", "kc"]
          and all(len(row["cells"]) == 7 for row in rows), "sweep: 6 parameters x 7 steps")
    base = layout.capacity(D, K)
    check(all(row["cells"][3]["w"] == base and row["cells"][3]["delta"] == 0 for row in rows),
          "sweep: the middle column is the current W")
    check(rows[0]["cells"][0] is None and rows[1]["cells"][0] is None,
          "sweep: values below the minimum (start 2, size 1) are empty")
    check(layout.fmt_big(1234567) == "1 234 567"
          and layout.fmt_big(10 ** 24) == "1,000·10^24", "fmt_big: grouped, or mantissa·10^e")


def test_ops():
    rng = random.Random(15)
    D, K = layout.blocks(2, 2, 2), layout.blocks(6, 1, 2)
    D2, K2 = layout.blocks(2, 3, 2), layout.blocks(9, 2, 1)
    ok_add = ok_mul = ok_pow = ok_div = ok_addr = ok_ch = True
    for _ in range(120):
        x = rng.randrange(layout.capacity(D, K))
        y = rng.randrange(layout.capacity(D2, K2))
        A, B = layout.block_rep_of(x, D, K), layout.block_rep_of(y, D2, K2)
        for sign in (1, -1):
            out = ops.op_add(A, B, sign)
            w = _lcm(out["moduli"])
            exp = (x + sign * y) % w
            ok_add &= out["residues"] == [exp % m for m in out["moduli"]]
            ok_add &= out["wrap"] == ((x + y >= w) if sign > 0 else (x < y))
            ok_add &= out["period"] == w // math.gcd(w, y)
        out = ops.op_mul(A, B)
        w = _lcm(out["moduli"])
        ok_mul &= out["residues"] == [x * y % m for m in out["moduli"]]
        seen, v, j = {}, x % w, 0
        while v not in seen:
            seen[v] = j
            v, j = v * y % w, j + 1
        ok_mul &= (out["preperiod"], out["period"]) == (seen[v], j - seen[v])
        e = rng.randint(1, 6)
        out = ops.op_pow(A, e)
        w = _lcm(out["moduli"])
        ok_pow &= out["residues"] == [pow(x, e, m) for m in out["moduli"]]
        seen, v, j = {}, x % w, 0
        while v not in seen:
            seen[v] = j
            v, j = v * x % w, j + 1
        ok_pow &= (out["preperiod"], out["period"]) == (seen[v], j - seen[v])
        b = rng.randint(1, 30)
        out = ops.op_div(A, b)
        w = _lcm(out["source_moduli"])
        if x % b == 0:
            ok_div &= out["kind"] == "exact" and out["residues"] == [
                x // b % m for m in out["moduli"]]
        else:
            d = math.gcd(b, w)
            if x % d:
                ok_div &= out["kind"] == "none"
            else:
                wd = w // d
                sol = (x // d) * pow(b // d, -1, wd) % wd if wd > 1 else 0
                ok_div &= out["kind"] == "modular" and out["d"] == d and out["residues"] == [
                    sol % m for m in out["moduli"]] and (b * sol - x) % w == 0
        t = rng.choice([2, 3, 4, 6, 12, 7 * 11, 13])
        out = ops.op_address(A, t)
        w = _lcm(res.flatten(A)[0])
        if w % t or x == 0:
            ok_addr &= out is None or (x == 0 and w % t == 0)
        else:
            kk = (x - 1) // t + 1
            ok_addr &= out["i"] == (x - 1) % t + 1 and out["k"] == [kk % m for m in out["moduli"]]
        p = rng.choice([2, 3, 5, 7, 11])
        out = ops.chapters(A, p, 4)
        w = _lcm(res.flatten(A)[0])
        v = 0
        while w % p ** (v + 1) == 0:
            v += 1
        ok_ch &= out["v"] == v and [row["w"] for row in out["rows"]] == [
            w * p ** j for j in range(4)]
    check(ok_add, "op_add: residues, wrap flag, period W / gcd(W, B)")
    check(ok_mul, "op_mul: residues, preperiod and period of A, AB, ABB, ...")
    check(ok_pow, "op_pow: residues, rhythm of A, A^2, A^3, ...")
    check(ok_div, "op_div: exact division, or the solutions of b x = A mod W, or none")
    check(ok_addr, "op_address: (i, [k]) when T | W")
    check(ok_ch, "chapters: highest power p^v in W, appending p^(v+j) multiplies W by p^j")


def test_selftest():
    out = selftest.compare_test(300, random.Random(1))
    check(out["count"] == 300 and out["wrong"] == 0, f"compare_test: 300 pairs, 0 wrong ({out})")
    out = selftest.ops_test(180, random.Random(2))
    check(sum(s["tries"] for s in out["kinds"]) == 180 and out["wrong"] == 0
          and len(out["kinds"]) == 9 and all(s["tries"] == 20 for s in out["kinds"]),
          f"ops_test: 180 operations over 9 kinds, 0 wrong ({out['wrong']})")


_CASE_KEYS = {"kind", "task", "residues", "integers", "ok"}


def test_selftest_cases():
    out = selftest.compare_test(200, random.Random(3))
    cases = out.get("cases", [])
    check(len(cases) == 200 and all(set(c) >= {"a", "b", "residues", "integers", "ok"}
                                    for c in cases),
          f"compare_test lists every pair ({len(cases)} cases)")
    check(all(c["ok"] and c["residues"].split(" (")[0] == c["integers"] for c in cases),
          "every pair: the residue verdict equals the integer verdict and is marked ok")
    check(sum(c["integers"] == "A = B" for c in cases) >= 20,
          "every tenth pair is equal (A = B)")
    check(all("{" in c["a"] and "{" in c["b"] for c in cases),
          "each side shows its number and its blocks")
    real = res.compare_blocks
    res.compare_blocks = lambda x, y: dict(real(x, y), verdict=-real(x, y)["verdict"])
    try:
        bad = selftest.compare_test(50, random.Random(3))
    finally:
        res.compare_blocks = real
    equal = sum(c["integers"] == "A = B" for c in bad["cases"])
    check(bad["wrong"] == 50 - equal and sum(not c["ok"] for c in bad["cases"]) == 50 - equal,
          f"a flipped verdict is caught on every unequal pair ({bad['wrong']} of {50 - equal})")

    out = selftest.ops_test(90, random.Random(4))
    cases = out.get("cases", [])
    check(len(cases) == 90 and all(set(c) >= _CASE_KEYS for c in cases),
          f"ops_test lists every operation ({len(cases)} cases)")
    check([c["kind"] for c in cases[:9]] == list(selftest.OP_KINDS),
          "the kinds come in turn")
    check(all(c["ok"] and c["residues"] == c["integers"] for c in cases),
          "every operation: the result read from residues equals the integer result")
    check(all(c["task"] and c["residues"] for c in cases), "every case has a task and a result")
    real_mul = ops.op_mul
    ops.op_mul = lambda x, y: dict(real_mul(x, y), residues=[(s + 1) % m for m, s in zip(
        real_mul(x, y)["moduli"], real_mul(x, y)["residues"])])
    try:
        bad = selftest.ops_test(90, random.Random(4))
    finally:
        ops.op_mul = real_mul
    muls = [c for c in bad["cases"] if c["kind"] == "mul"]
    check(muls and all(not c["ok"] and c["residues"] != c["integers"] for c in muls)
          and bad["kinds"][2]["wrong"] == len(muls),
          "a wrong product is caught and shown next to the integer result")


def test_imports():
    path = os.path.join(_REPO_ROOT, "primeatlas", "research", "irreducibility_residues.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
    bad = [m for m in mods if any(k in m for k in ("prim", "sieve", "sympy", "oracle", "layout"))]
    check(not bad, f"irreducibility_residues.py imports nothing about primes ({sorted(mods)})")


def main():
    test_mixed_radix()
    test_inv_mod()
    test_compare()
    test_blocks()
    test_atoms()
    test_arithmetic()
    test_layout()
    test_ops()
    test_selftest()
    test_selftest_cases()
    test_imports()
    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
