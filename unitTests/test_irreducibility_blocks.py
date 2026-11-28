"""
test_irreducibility_blocks.py -- tests for the residue-level modules of Research ->
Irreducibility beyond the radices: irreducibility_residues.py (mixed radix, comparison, blocks,
interval atoms, arithmetic; mirrors Defs.lean), irreducibility_layout.py (block layouts, W,
fitting a layout to a number, the parameter sweep), irreducibility_ops.py (the operations
shown in the Arithmetic sub-tab), irreducibility_primality.py (a run of isPrimeRes in slices,
for the Primality sub-tab) and irreducibility_selftest.py (the random self-tests).
Every result is compared with plain integer arithmetic. Numbers past Python's 4300-digit
str/int limit (lifted by the primeatlas package) are shown, counted and powered without an
exception: fmt_big, digit_count, layout_info of a layout whose W has about 8700 digits, and
power_size, which tells whether A^e fits W exactly and its digits (exact when it fits, from
the logarithm otherwise) without forming a huge A^e.

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
from primeatlas.research import irreducibility_primality as primality
from primeatlas.research import irreducibility_residues as res
from primeatlas.research import irreducibility_multiplicative as mult
from primeatlas.research import irreducibility_selftest as selftest

# fmt_big output holds a middle dot, which a cp1250 console cannot print.
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
    check(layout.fmt_big(1234567) == "1,234,567"
          and layout.fmt_big(10 ** 24) == "1.000·10^24", "fmt_big: grouped, or mantissa·10^e")


def _info_T(key, **kw):
    return key + " " + " ".join(f"{k}={v}" for k, v in kw.items())


def test_big_numbers():
    import time
    from primeatlas.research.irreducibility_numbers import layout_info
    w = 10 ** 5000
    try:
        ok = (layout.fmt_big(w) == "1.000·10^5000"
              and layout.fmt_big(1234 * 10 ** 4996 + 5) == "1.234·10^4999"
              and layout.digit_count(w) == 5000 and layout.digit_count(w + 1) == 5001)
    except ValueError as error:
        ok = repr(error)[:60]
    check(ok is True, f"fmt_big and digit_count past 4300 digits ({ok})")
    D, K = layout.blocks(2, 50, 400), layout.blocks(20002, 1, 1)
    big_w = layout.capacity(D, K)
    try:
        text = layout_info(_info_T, D, K, 12345678)
        ok = "·10^" in text and f"digits={len(str(big_w - 1))}" in text
    except ValueError as error:
        text, ok = repr(error)[:60], False
    check(ok and big_w.bit_length() > 4300 * 3.33,
          f"layout_info of ds=2, dz=50, dc=400: W as m.mmm·10^e and its digits ({text[:90]!r})")

    size = getattr(ops, "power_size", None)
    check(size is not None, "irreducibility_ops.power_size exists")
    if size is None:
        return
    x = 12345678
    X = x ** 3
    check(size(x, 3, X + 1) == (True, len(str(X))) and size(x, 3, X)[0] is False
          and size(x, 3, X - 1)[0] is False,
          "power_size: A^e = W - 1 fits with its exact digits, A^e = W and W + 1 wrap")
    check(size(0, 5, 7) == (True, 1) and size(1, 10000, 2) == (True, 1)
          and size(1, 1, 1)[0] is False and size(7, 1, 8) == (True, 1),
          "power_size: A = 0 and A = 1, e = 1")
    worst = 0
    for a in (2, 3, 7, 10, 99, 12345678, 10 ** 12 - 1, 3 ** 200):
        for e in (1, 2, 538, 600, 4999, 10000):
            fits, digits = size(a, e, 2520)
            if a ** e < 2520:
                continue
            worst = max(worst, abs(digits - len(str(a ** e))))
            if fits:
                worst = 99
    check(worst <= 1, f"power_size: a wrapping A^e has its digits from the logarithm, at most "
                      f"one off (worst {worst})")
    start = time.perf_counter()
    fits, digits = size(10 ** 4000 + 7, 10000, big_w)
    seconds = time.perf_counter() - start
    check(not fits and abs(digits - 40_000_001) <= 1 and seconds < 1.0,
          f"power_size: a 4000-digit A to e = 10000 wraps, about 40,000,001 digits, in under "
          f"1 s ({digits}, {seconds:.2f} s)")


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


def _lean_is_prime_res(fuel, moduli, residues):
    """A literal transcription of isPrimeRes / isPrimeResAux (Defs.lean): compareRes on the
    residues of m and of m * m, evalMod of the mixed-radix digits."""
    ds = res.to_mixed_radix(moduli, residues)
    if ds is None:
        return None

    def aux(fuel, m):
        if fuel == 0:
            return None
        c = res.compare_res(moduli, [core.resid(m, x) for x in moduli], residues)
        if c is None:
            return None
        if c == 0:
            return True
        if c == 1:
            return False
        c2 = res.compare_res(moduli, [core.resid(m, x) * core.resid(m, x) % x for x in moduli],
                             residues)
        if c2 is None:
            return None
        if c2 == 1:
            return True
        return False if res.eval_mod(ds, m) == 0 else aux(fuel - 1, m + 1)
    return aux(fuel, 2)


_PRIME_MODULI = ([4, 9, 5], [6, 10, 15], [2, 3, 5, 7], [8, 3], [12], [7, 7, 2], [3, 4],
                 [2, 49])


def test_is_prime_res():
    rng = random.Random(11)
    same = True
    for moduli in _PRIME_MODULI:
        w = _lcm(moduli)
        for n in range(w):
            rs = [n % m for m in moduli]
            for fuel in (0, 1, 2, 3, n + 1, rng.randint(0, n + 2)):
                same &= res.is_prime_res(fuel, moduli, rs) == _lean_is_prime_res(fuel, moduli, rs)
    for _ in range(300):
        moduli = _random_moduli(rng, rng.randint(1, 4), 12)
        rs = [rng.randrange(m) for m in moduli]
        fuel = rng.randint(0, 40)
        same &= res.is_prime_res(fuel, moduli, rs) == _lean_is_prime_res(fuel, moduli, rs)
    check(same, "is_prime_res equals the literal transcription of isPrimeRes, every fuel, "
                "random residues (incompatible ones included)")
    sound = all(res.is_prime_res(n + 1, moduli, [n % m for m in moduli]) == _is_prime(n)
                for moduli in _PRIME_MODULI if _lcm(moduli) > 2
                for n in range(_lcm(moduli)))
    check(sound, "n < W, W > 2, fuel n + 1: the answer is whether n is prime (every n < W)")
    short = all(res.is_prime_res(max(math.isqrt(n), 1), moduli, [n % m for m in moduli])
                == _is_prime(n)
                for moduli in _PRIME_MODULI for n in range(_lcm(moduli))
                if (math.isqrt(n) + 1) ** 2 < _lcm(moduli))
    check(short, "(isqrt(n) + 1)^2 < W: fuel isqrt(n) already answers")
    check(res.is_prime_res(5, [4, 6], [1, 2]) is None, "incompatible residues: no answer")
    check(res.is_prime_res(0, [2, 3, 5, 7], [1, 1, 1, 1]) is None, "fuel 0: no answer")
    steps = list(res.is_prime_res_steps([4, 9, 5], [1, 0, 4]))   # n = 9
    check(steps == [(2, -1, -1, 1, None), (3, -1, 0, 0, False)],
          f"steps of n = 9: m = 2 (m < n, m^2 < n, 9 mod 2 = 1), m = 3 (m^2 = n, divides) "
          f"({steps})")
    check(list(res.is_prime_res_steps([4, 9, 5], [2, 2, 2])) == [(2, 0, None, None, True)],
          "n = 2: one step, m = n")
    check(list(res.is_prime_res_steps([4, 9, 5], [1, 1, 1])) == [(2, 1, None, None, False)],
          "n = 1: one step, m > n")
    check(list(res.is_prime_res_steps([4, 9, 5], [3, 3, 3])) == [(2, -1, 1, None, True)],
          "n = 3: one step, m^2 > n")
    check(list(res.is_prime_res_steps([4, 6], [1, 2])) == [], "incompatible residues: no step")


def _run(n, moduli, fuel, slice_steps=None, **kw):
    run = primality.PrimalityRun(moduli, [n % m for m in moduli], fuel, **kw)
    if slice_steps is None:
        run.advance(10 ** 9)
    else:
        while not run.advance(slice_steps):
            pass
    return run


def test_primality_run():
    big = [7 * 11 * 13, 17 * 19, 23 * 29, 31 * 37, 41 * 43, 47 * 53]   # W > 10^14
    p = 1000003
    run = _run(p, big, 10 ** 6)
    check(run.done and run.answer is True and run.reason == "square"
          and run.steps == math.isqrt(p),
          f"prime 1000003: prime by the square test at m = isqrt(n) + 1 "
          f"({run.answer}, {run.reason}, {run.steps})")
    check([s[0] for s in run.first] == list(range(1, primality.HEAD_ROWS + 1))
          and [s[1] for s in run.first] == list(range(2, primality.HEAD_ROWS + 2)),
          "the first HEAD_ROWS steps are kept with their index and m")
    check(len(run.last) == primality.TAIL_ROWS and run.last[-1][0] == run.steps
          and run.last[-1][1] == math.isqrt(p) + 1,
          "the last TAIL_ROWS steps are kept, the last one at m = isqrt(n) + 1")
    sliced = _run(p, big, 10 ** 6, slice_steps=7)
    check((sliced.answer, sliced.reason, sliced.steps, sliced.first, list(sliced.last))
          == (run.answer, run.reason, run.steps, run.first, list(run.last)),
          "advancing in slices of 7 steps gives the same run")
    run = _run(1000003 * 3, big, 10 ** 6)
    check(run.answer is False and run.reason == "divisor" and run.steps == 2
          and run.first[-1] == (2, 3, -1, -1, 0), "3 * 1000003: divisor m = 3 at step 2")
    for n, answer, reason in ((0, False, "below"), (1, False, "below"), (2, True, "equal"),
                              (3, True, "square"), (4, False, "divisor")):
        run = _run(n, big, 5)
        check(run.answer is answer and run.reason == reason and run.steps == 1,
              f"n = {n}: {reason} at the first step")
    run = _run(97, [2, 49], 200)
    check(run.answer is True and run.steps <= 96,
          f"97 on W = 98 (square test unreliable): still prime ({run.reason}, "
          f"{run.steps} steps)")
    check(not primality.square_test_holds(97, 98) and primality.square_test_holds(97, 101)
          and not primality.square_test_holds(97, 100), "square_test_holds: (isqrt(n)+1)^2 < W")
    run = _run(p, big, 3)
    check(run.done and run.answer is None and run.reason == "fuel" and run.steps == 3,
          "fuel 3: no answer after 3 steps")
    run = primality.PrimalityRun([4, 6], [1, 2], 10)
    run.advance(5)
    check(run.done and run.answer is None and run.reason == "incompatible" and run.steps == 0,
          "incompatible residues: no answer, no step")
    run = primality.PrimalityRun(big, [p % m for m in big], 10 ** 6)
    run.advance(50)
    run.stop()
    check(run.done and run.answer is None and run.reason == "stopped" and run.steps == 50,
          "stopped after 50 steps: no answer, steps kept")
    check(run.advance(10) and run.steps == 50, "a stopped run does not advance")
    check(primality.fit_target(p) == (math.isqrt(p) + 1) ** 2 and primality.fit_target(0) == 1,
          "fit_target: (isqrt(n) + 1)^2")


def test_selftest():
    out = selftest.compare_test(300, random.Random(1))
    check(out["count"] == 300 and out["wrong"] == 0, f"compare_test: 300 pairs, 0 wrong ({out})")
    out = selftest.ops_test(180, random.Random(2))
    check(sum(s["tries"] for s in out["kinds"]) == 180 and out["wrong"] == 0
          and len(out["kinds"]) == 9 and all(s["tries"] == 20 for s in out["kinds"]),
          f"ops_test: 180 operations over 9 kinds, 0 wrong ({out['wrong']})")
    out = selftest.primality_test(120, random.Random(5))
    cases = out.get("cases", [])
    check(out["count"] == 120 and out["wrong"] == 0 and len(cases) == 120,
          f"primality_test: 120 numbers, 0 wrong ({out['wrong']})")
    check(all(set(c) >= {"task", "residues", "integers", "ok", "detail"} and c["ok"]
              and c["residues"] == c["integers"] and "m:" in c["detail"] for c in cases),
          "every number: the answer from residues equals the integer answer, residues listed")
    check(any("∈ ℙ" == c["integers"] for c in cases)
          and any(c["integers"].startswith("∉ ℙ") for c in cases),
          "the numbers include primes and composites")
    check(sum(c["near_w"] for c in cases) >= 20,
          "a quarter of the numbers lie just below W, where the square test may not stop")
    check({0, 1, 2, 3} <= {c["n"] for c in cases}, "n = 0, 1, 2, 3 are among the numbers")
    real = res.is_prime_res_steps

    def flipped(moduli, residues):
        for m, a, b, r, ans in real(moduli, residues):
            yield m, a, b, r, (None if ans is None else not ans)
    res.is_prime_res_steps = flipped
    try:
        bad = selftest.primality_test(40, random.Random(5))
    finally:
        res.is_prime_res_steps = real
    check(bad["wrong"] == 40, f"a flipped answer is caught on every number ({bad['wrong']})")

    out = selftest.multiplicative_test(300, random.Random(6))
    cases = out.get("cases", [])
    check(out["count"] == 300 and out["wrong"] == 0 and len(cases) == 300,
          f"multiplicative_test: 300 cases, 0 wrong ({out['wrong']})")
    check(all(set(c) >= {"q", "n", "task", "residues", "integers", "ok", "detail"} and c["ok"]
              and c["residues"].split(": ")[-1] == c["integers"].split(": ")[-1]
              and "t:" in c["detail"] for c in cases),
          "every case: the reading from the step equals Euler's criterion, the cycle listed")
    kinds = {c["integers"].split(": ")[-1] for c in cases}
    check(kinds == {"square", "not a square", "q | N", "q = 2"},
          f"the cases include squares, non-squares, q | N and q = 2 ({sorted(kinds)})")
    check(all(c["q"] <= selftest.MUL_TEST_MAX_Q for c in cases)
          and len({c["q"] for c in cases}) > 50, "q runs over many primes up to MUL_TEST_MAX_Q")
    real = mult.analyze

    def flipped(q, g, n):
        a = real(q, g, n)
        return dict(a, square=None if a["square"] is None else not a["square"])
    mult.analyze = flipped
    try:
        bad = selftest.multiplicative_test(60, random.Random(6))
    finally:
        mult.analyze = real
    claims = sum(c["integers"].split(": ")[-1] in ("square", "not a square") for c in bad["cases"])
    check(bad["wrong"] == claims > 0,
          f"a flipped parity is caught on every square question ({bad['wrong']} of {claims})")


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
    test_big_numbers()
    test_ops()
    test_is_prime_res()
    test_primality_run()
    test_selftest()
    test_selftest_cases()
    test_imports()
    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
