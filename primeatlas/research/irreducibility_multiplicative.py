"""
irreducibility_multiplicative.py -- multiplicative counting modulo q, mirroring
lean/Irreducibility/Multiplicative.lean of the Irreducibility repository (T9): the values
mulCount g q t of one cycle next to the additive counter countMod (q - 1) t, the order of g,
whether both counters take equal values at the same pairs of steps, the step reaching N mod q
(the discrete logarithm) and its parity, and the steps where the sech comb of modulus q - 1
peaks next to those where the cycle returns to 1.

Every value comes from counting: one multiplication by g and one residue per step, never a
power. Nothing here uses a list of primes or a primality test: g of order q - 1 exists only
for a prime q, and the square reading is given only for such g (mulCount_eq_mulCount_iff,
isSquare_iff_even).
"""
from .irreducibility_comb import PEAK_LEVEL, sech_comb
from .irreducibility_core import euclid, resid

MAX_Q = 10 ** 5
"""Largest accepted q; arbitrary, bounds one cycle to MAX_Q steps."""

AUTO_MAX_G = 100
"""Candidates g = 1..AUTO_MAX_G tried by Auto; arbitrary, above the least primitive root of
every prime up to MAX_Q (the largest is 44, of 71761)."""

COMB_MAX_Q = 101
"""Largest q whose comb is drawn: two cycles of q - 1 steps stay readable; arbitrary."""

TABLE_ALL = 200
"""Up to this many steps every step is a table row; arbitrary."""

HEAD_ROWS = 20
"""First steps shown for a longer cycle; arbitrary."""

TAIL_ROWS = 3
"""Last steps shown for a longer cycle (the return to 1 at q - 1); arbitrary."""

AROUND_ROWS = 2
"""Steps shown on each side of the step reaching N mod q; arbitrary."""


def mul_counts(g, q, steps):
    """mulCount g q t for t = 0..steps - 1, by counting."""
    out, v = [], resid(1, q)
    for _ in range(steps):
        out.append(v)
        v = resid(v * g, q)
    return out


def count_mods(d, steps):
    """countMod d t for t = 0..steps - 1, by counting."""
    out, c = [], 0
    for _ in range(steps):
        out.append(c)
        c = 0 if c + 1 == d else c + 1
    return out


def mul_order(g, q):
    """The least t > 0 with mulCount g q t = 1, or None when g and q share a factor (the
    counter never returns to 1). Within q steps for q >= 2."""
    if euclid(resid(g, q), q) != 1:
        return None
    v = resid(1, q)
    for t in range(1, q + 1):
        v = resid(v * g, q)
        if v == 1:
            return t
    return None


def auto_generator(q):
    """(g, order): among g = 1..min(q - 1, AUTO_MAX_G) the smallest g of the largest order;
    the search stops at the first g of order q - 1, which for a prime q is its least
    primitive root."""
    best_g, best = None, 0
    for g in range(1, min(q - 1, AUTO_MAX_G) + 1):
        o = mul_order(g, q)
        if o is not None and o > best:
            best_g, best = g, o
            if o == q - 1:
                break
    return best_g, best


def _pairs_break(values, counts):
    """None when values[t] = values[u] exactly when counts[t] = counts[u]; else (u, t), t the
    first step whose equal-value class differs, u the earlier step of the differing pair."""
    first_v, first_c = {}, {}
    for t, (v, c) in enumerate(zip(values, counts)):
        u, w = first_v.setdefault(v, t), first_c.setdefault(c, t)
        if u != w:
            return min(u, w), t
    return None


def analyze(q, g, n):
    """One cycle of g modulo q (q >= 2) and the reading of n. Returns a dict: values and counts
    (t = 0..q - 1), order (None without a return to 1), primitive (order = q - 1), pairs_break
    (None or the differing pair), r = n mod q, step (the first t < max(q - 1, 1) with value
    r; None for r = 0 or r not reached) and square (n a square modulo q by the parity of step;
    None unless g is primitive, q > 2 and step exists)."""
    values = mul_counts(g, q, q)
    counts = count_mods(q - 1, q)
    order = mul_order(g, q)
    primitive = order == q - 1
    r = resid(n, q)
    step = None
    if r != 0:
        step = next((t for t, v in enumerate(values[:max(q - 1, 1)]) if v == r), None)
    square = None
    if primitive and q > 2 and step is not None:
        square = step % 2 == 0
    return {"values": values, "counts": counts, "order": order, "primitive": primitive,
            "pairs_break": _pairs_break(values, counts), "r": r, "step": step,
            "square": square}


def table_steps(q, step):
    """The steps t = 0..q - 1 shown as table rows, None marking a gap: every step up to
    TABLE_ALL, else the first HEAD_ROWS, the step with AROUND_ROWS on each side, and the last
    TAIL_ROWS."""
    if q <= TABLE_ALL:
        return list(range(q))
    keep = set(range(HEAD_ROWS)) | set(range(q - TAIL_ROWS, q))
    if step is not None:
        keep |= set(range(max(step - AROUND_ROWS, 0), min(step + AROUND_ROWS + 1, q)))
    out = []
    for t in sorted(keep):
        if out and t != out[-1] + 1:
            out.append(None)
        out.append(t)
    return out


def comb_returns(s, q, g):
    """(peaks, returns) over the steps 0..2(q - 1): the steps where the sech comb of modulus
    q - 1 at scale s exceeds PEAK_LEVEL, and those where mulCount g q t = 1. Equal for a
    primitive root from scale 3 on (one_half_lt_sechComb_iff_mulCount_eq_one)."""
    top = 2 * (q - 1)
    peaks = [t for t in range(top + 1) if sech_comb(s, q - 1, t) > PEAK_LEVEL]
    returns = [t for t, v in enumerate(mul_counts(g, q, top + 1)) if v == 1]
    return peaks, returns
