"""
irreducibility_selftest.py -- the random self-tests of Research -> Irreducibility: comparisons
of numbers in random block layouts, and random operations of every kind, each result checked
against ordinary integer arithmetic.
"""
import math

from . import irreducibility_layout as layout
from . import irreducibility_ops as ops
from . import irreducibility_residues as res

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


def _detail(moduli, rows):
    """The moduli and one line per (label, residues) row, each column right-aligned under
    its modulus."""
    table = [("m", moduli)] + [(label, r) for label, r in rows if r is not None]
    widths = [max(len(str(r[i])) for _, r in table) for i in range(len(moduli))]
    return "\n".join(f"{label}: " + " ".join(str(v).rjust(w) for v, w in zip(r, widths))
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
