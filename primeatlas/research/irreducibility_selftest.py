"""
irreducibility_selftest.py -- the random self-tests of Research -> Irreducibility: comparisons
of numbers in random block layouts, random operations of every kind, primality read from
residues and the square reading of multiplicative counting, each result checked against
ordinary integer arithmetic.
"""
import math

from . import irreducibility_layout as layout
from . import irreducibility_multiplicative as mult
from . import irreducibility_ops as ops
from . import irreducibility_primality as primality
from . import irreducibility_residues as res

PRIMALITY_MAX_N = 20000
"""Largest number of the primality self-test away from W; bounds its trial division."""

MUL_TEST_MAX_Q = 1000
"""Largest prime q of the multiplicative self-test; bounds one cycle; arbitrary."""

MUL_DETAIL_STEPS = 24
"""Steps of the cycle listed in a case's detail; arbitrary."""

OP_KINDS = ("add", "sub", "mul", "div_exact", "div_modular", "address", "pow", "periods",
            "chapters")


def _rand_below(cap, rng):
    return rng.randrange(cap) if cap > 0 else 0


def _random_layout(rng, size_hi=3, count_hi=2, gap=7):
    D = layout.blocks(2, 2 + rng.randint(0, size_hi - 2), 2 + rng.randint(0, count_hi - 1))
    top = D[-1][-1] + 1 + rng.randint(0, gap - 1)
    return D, layout.blocks(top, 2 + rng.randint(0, 1), 1 + rng.randint(0, 1))


def _blocks_text(bs):
    return " ".join("{" + ",".join(map(str, b)) + "}" for b in bs)


def _side_text(n, D, K):
    return f"{n}  {_blocks_text(D)} · {_blocks_text(K)}"


def _verdict_text(v):
    return {-1: "A < B", 0: "A = B", 1: "A > B"}[v]


def compare_test(n, rng):
    """n comparisons: random layouts for each number, every tenth pair equal, the rest
    neighbours n +- 1 or random. Returns {count, wrong, cases}; a case holds both sides
    (number and blocks), the verdict read from residues (with the deciding modulus), the
    integer verdict, ok and detail (moduli, radices and both mixed-radix digit rows)."""
    cases = []
    for t in range(n):
        (D, K), (D2, K2) = _random_layout(rng, 4), _random_layout(rng, 4)
        cap = min(layout.capacity(D, K), layout.capacity(D2, K2))
        x = _rand_below(cap, rng)
        y = x if t % 10 == 0 else (x + rng.choice([1, cap - 1, _rand_below(cap, rng)])) % cap
        v = res.compare_blocks(layout.block_rep_of(x, D, K), layout.block_rep_of(y, D2, K2))
        got = _verdict_text(v["verdict"])
        if v["at"] >= 0:
            got += f" (m = {v['moduli'][v['at']]})"
        want = _verdict_text((x > y) - (x < y))
        detail = _detail(v["moduli"], [("r", v["radices"]), ("A", v["digits_x"]),
                                       ("B", v["digits_y"])])
        cases.append({"a": _side_text(x, D, K), "b": _side_text(y, D2, K2), "residues": got,
                      "integers": want, "ok": v["verdict"] == (x > y) - (x < y),
                      "detail": detail})
    return {"count": n, "wrong": sum(not c["ok"] for c in cases), "cases": cases}


def _small_layout(rng):
    return layout.blocks(2, 2, 2), layout.blocks(6 + rng.randint(0, 2), 1 + rng.randint(0, 1),
                                                 1 + rng.randint(0, 1))


def _cycle(x0, step, w):
    seen, x, j = {}, x0, 0
    while x not in seen:
        seen[x] = j
        x, j = x * step % w, j + 1
    return seen[x], j - seen[x]


def _value(moduli, residues):
    """The integer below lcm(moduli) with these residues, or '?' when they disagree."""
    ds = res.to_mixed_radix(moduli, residues)
    return "?" if ds is None else res.eval_digits(ds)


def _detail(moduli, rows, head="m"):
    """The moduli and one line per (label, residues) row, each column right-aligned under
    its modulus, the labels padded to one width; head labels the first line."""
    table = [(head, moduli)] + [(label, r) for label, r in rows if r is not None]
    widths = [max(len(str(r[i])) for _, r in table) for i in range(len(moduli))]
    lw = max(len(label) for label, _ in table)
    return "\n".join(f"{label}: ".ljust(lw + 2) + " ".join(str(v).rjust(w)
                                                          for v, w in zip(r, widths))
                     for label, r in table)


def _one(kind, rng):
    """One random operation of the kind: (task, read from residues, integer result, detail),
    the middle two as text in the same notation, equal exactly when the residue result is
    right; detail lists the moduli and the residues the operation worked on."""
    small = kind == "periods"
    (D, K) = _small_layout(rng) if small else _random_layout(rng)
    (D2, K2) = _small_layout(rng) if small else _random_layout(rng)
    x = _rand_below(layout.capacity(D, K), rng)
    y = _rand_below(layout.capacity(D2, K2), rng)
    A, B = layout.block_rep_of(x, D, K), layout.block_rep_of(y, D2, K2)
    moduli = res.flatten(A)[0]
    w = layout.lcm_all(moduli)
    if kind in ("add", "sub"):
        sign = 1 if kind == "add" else -1
        out = ops.op_add(A, B, sign)
        wc = layout.lcm_all(out["moduli"])
        if sign > 0:
            flags, wrap = ("A + B < W", "A + B ≥ W"), x + y >= wc
        else:
            flags, wrap = ("A ≥ B", "A < B"), x < y
        _, xs, ys = ops.common_of(A, B)
        return (f"{x} {'⊕' if sign > 0 else '⊖'} {y}   W = {wc}",
                f"{_value(out['moduli'], out['residues'])}; {flags[out['wrap']]}",
                f"{(x + sign * y) % wc}; {flags[wrap]}",
                _detail(out["moduli"], [("A", xs), ("B", ys), ("=", out["residues"])]))
    if kind == "mul":
        out = ops.op_mul(A, B)
        wc = layout.lcm_all(out["moduli"])
        _, xs, ys = ops.common_of(A, B)
        return (f"{x} ⊗ {y}   W = {wc}", str(_value(out["moduli"], out["residues"])),
                str(x * y % wc),
                _detail(out["moduli"], [("A", xs), ("B", ys), ("=", out["residues"])]))
    if kind == "div_exact":
        b = rng.randint(2, 41)
        xr = x - x % b
        out = ops.op_div(layout.block_rep_of(xr, D, K), b)
        got = (str(_value(out["moduli"], out["residues"])) if out["kind"] == "exact"
               else out["kind"])
        src = res.flatten(layout.block_rep_of(xr, D, K))[1]
        return (f"{xr} ⊘ {b}", got, str(xr // b % layout.lcm_all(out["moduli"])),
                _detail(out["source_moduli"], [("A", src)]) + "\n"
                + _detail(out["moduli"], [("=", out["residues"])]))
    if kind == "div_modular":
        b = rng.randint(2, 61)
        out, d = ops.op_div(A, b), math.gcd(b, w)
        task = f"{x} ⊘ {b}   W = {w}"
        if out["kind"] == "exact":
            got = f"{b} | A"
        elif out["kind"] == "none":
            got = f"gcd(b, W) = {math.gcd(b, w)} ∤ A"
        else:
            wd = layout.lcm_all(out["moduli"])
            got = f"{_value(out['moduli'], out['residues'])} mod {wd}, d = {out['d']}"
        if x % b == 0:
            want = f"{b} | A"
        elif x % d:
            want = f"gcd(b, W) = {d} ∤ A"
        else:
            wd = w // d
            sol = (x // d) * pow(b // d, -1, wd) % wd if wd > 1 else 0
            want = f"{sol} mod {wd}, d = {d}"
        detail = _detail(moduli, [("A", res.flatten(A)[1])])
        if out["residues"] is not None:
            detail += "\n" + _detail(out["moduli"], [("=", out["residues"])])
        return task, got, want, detail
    if kind == "address":
        t = rng.choice(moduli) * (1 if rng.random() < 0.5 else moduli[0])
        out = ops.op_address(A, t)
        task = f"addr({x}, T = {t})   W = {w}"
        got = ("T ∤ W" if out is None
               else f"i = {out['i']}, k = {_value(out['moduli'], out['k'])}")
        detail = _detail(moduli, [("A", res.flatten(A)[1])])
        if out is not None:
            detail += "\n" + _detail(out["moduli"], [("k", out["k"])])
        if w % t:
            return task, got, "T ∤ W", detail
        i, k = (t, 0) if x == 0 else ((x - 1) % t + 1, (x - 1) // t + 1)
        return (task, got, f"i = {i}, k = {k % layout.lcm_all(res.div_moduli(moduli, t))}",
                detail)
    if kind == "pow":
        e = rng.randint(2, 7)
        out = ops.op_pow(A, e)
        return (f"{x}^{e}   W = {w}", str(_value(out["moduli"], out["residues"])),
                str(pow(x, e, w)),
                _detail(moduli, [("A", res.flatten(A)[1]), ("=", out["residues"])]))
    if kind == "periods":
        mul, pw = ops.op_mul(A, B), ops.op_pow(A, 2)
        wc = layout.lcm_all(mul["moduli"])
        f = "A·B^j: μ = {}, λ = {};  A^j: μ = {}, λ = {}"
        return (f"A = {x}, B = {y}   W = {wc}",
                f.format(mul["preperiod"], mul["period"], pw["preperiod"], pw["period"]),
                f.format(*_cycle(x % wc, y % wc, wc), *_cycle(x % w, x % w, w)),
                _detail(mul["moduli"], [("A", ops.common_of(A, B)[1]),
                                        ("B", ops.common_of(A, B)[2])]))
    p = rng.choice([2, 3, 5, 7, 11, 13])
    out = ops.chapters(A, p, 4)
    return (f"W = {w}, p = {p}, j = 0..3", " → ".join(str(row["w"]) for row in out["rows"]),
            " → ".join(str(w * p ** j) for j in range(4)),
            _detail(moduli + [row["added"] for row in out["rows"] if row["added"]], []))


def ops_test(n, rng):
    """n operations, the kinds of OP_KINDS in turn. Returns {kinds: [{name, tries, wrong}],
    wrong, cases}; a case holds kind, task, residues (the result read from residues),
    integers (the integer result in the same notation), ok and detail (the residues)."""
    stats = [{"name": k, "tries": 0, "wrong": 0} for k in OP_KINDS]
    cases = []
    for t in range(n):
        s = stats[t % len(OP_KINDS)]
        task, got, want, detail = _one(s["name"], rng)
        s["tries"] += 1
        s["wrong"] += got != want
        cases.append({"kind": s["name"], "task": task, "residues": got, "integers": want,
                      "ok": got == want, "detail": detail})
    return {"kinds": stats, "wrong": sum(s["wrong"] for s in stats), "cases": cases}


def _prime_text(n, divisor):
    """'∈ ℙ', '∉ ℙ (n < 2)' or '∉ ℙ (d | n)' for the least divisor d."""
    if divisor is None:
        return "∈ ℙ"
    return "∉ ℙ (n < 2)" if n < 2 else f"∉ ℙ ({divisor} | n)"


def _least_divisor(n):
    """The least divisor d >= 2 of n, 0 for n < 2, None for a prime."""
    if n < 2:
        return 0
    return next((d for d in range(2, math.isqrt(n) + 1) if n % d == 0), None)


def primality_test(n, rng):
    """n numbers checked by isPrimeRes with fuel n + 1, which always answers: every fourth
    just below W of a small layout (where the square test may not stop the run early), n =
    0, 1, 2, 3 among the first, the rest below PRIMALITY_MAX_N on random layouts. The answer
    and, for a composite, the divisor that ended the run (the least one) are compared with
    trial division. Returns {count, wrong, cases}; a case holds n, near_w, task, residues,
    integers, ok and detail (the moduli, the residues of n and the step count)."""
    cases = []
    for t in range(n):
        near_w = t % 4 == 0
        if near_w:
            D, K = layout.blocks(2, 2, 2), layout.blocks(6 + rng.randint(0, 2), 1, 1)
        else:
            D, K = _random_layout(rng)
        w = layout.capacity(D, K)
        if near_w:
            x = w - 1 - rng.randint(0, 9)
        elif t % 4 == 1 and t < 16:
            x = t // 4
        else:
            x = rng.randrange(min(w, PRIMALITY_MAX_N))
        moduli, residues = res.flatten(layout.block_rep_of(x, D, K))
        run = primality.PrimalityRun(moduli, residues, x + 1)
        run.advance(x + 1)
        if run.answer is None:
            got = "?"
        else:
            got = _prime_text(x, None if run.answer else run.current_m())
        want = _prime_text(x, _least_divisor(x))
        detail = _detail(moduli, [("n", residues)]) + f"\nsteps: {run.steps}"
        cases.append({"n": x, "near_w": near_w, "task": f"n = {x}   W = {w}", "residues": got,
                      "integers": want, "ok": got == want, "detail": detail})
    return {"count": n, "wrong": sum(not c["ok"] for c in cases), "cases": cases}


def _square_text(square):
    return "square" if square else "not a square"


def multiplicative_test(n, rng):
    """n readings of T9: q a random prime up to MUL_TEST_MAX_Q (q = 2 every 25th case), g by
    Auto, N random (a multiple of q every fifth case). The square reading from the parity of
    the step reaching N mod q is compared with Euler's criterion N^((q - 1)/2) mod q; g must
    have order q - 1 and the counters equal values at the same pairs of steps. Returns
    {count, wrong, cases}; a case holds q, n, task, residues, integers, ok and detail (the
    first steps of the cycle)."""
    primes = [q for q in range(2, MUL_TEST_MAX_Q + 1)
              if all(q % d for d in range(2, math.isqrt(q) + 1))]
    cases = []
    for t in range(n):
        q = 2 if t % 25 == 0 else rng.choice(primes[1:])
        x = q * rng.randrange(10 ** 6) if t % 5 == 1 else rng.randrange(10 ** 12)
        g, _order = mult.auto_generator(q)
        a = mult.analyze(q, g, x)
        if q == 2:
            got = want = "q = 2"
            ok = a["primitive"]
        elif a["r"] == 0:
            got = want = "N mod q = 0: q | N"
            ok = a["step"] is None and a["square"] is None
        else:
            e = pow(x, (q - 1) // 2, q)
            parity = "?" if a["step"] is None else ("even" if a["step"] % 2 == 0 else "odd")
            got = (f"t = {a['step']} ({parity}): "
                   + ("?" if a["square"] is None else _square_text(a["square"])))
            want = f"N^{(q - 1) // 2} mod q = {e}: " + _square_text(e == 1)
            ok = got.split(": ")[-1] == want.split(": ")[-1]
        ok = ok and a["primitive"] and a["pairs_break"] is None
        k = min(q, MUL_DETAIL_STEPS)
        detail = _detail(list(range(k)), [("g^t", a["values"][:k]),
                                          ("t mod (q-1)", a["counts"][:k])], head="t")
        detail += f"\norder of g: {a['order']}   N mod q: {a['r']}"
        cases.append({"q": q, "n": x, "task": f"q = {q}, g = {g}, N = {x}", "residues": got,
                      "integers": want, "ok": ok, "detail": detail})
    return {"count": n, "wrong": sum(not c["ok"] for c in cases), "cases": cases}
