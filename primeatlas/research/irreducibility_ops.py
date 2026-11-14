"""
irreducibility_ops.py -- the operations of Research -> Irreducibility -> Arithmetic, on block
representations: sum and difference with the overflow / underflow flag and the period of the
repeated step, product with the preperiod and period of A, AB, ABB, ..., power with the
rhythm of A, A^2, ..., division (exact, or the solutions of b x = A mod W), the address
(i, k) with respect to T, and appending powers of a prime p (Lean: lcm_append_prime_powers).

The results are residues computed by irreducibility_residues.py. Periods are lcm values of
per-modulus cycles and the appended-power rows are lcm values: those are formed here, as is
residues_match, the check against a value computed with ordinary integers.
"""
from .irreducibility_core import euclid, prod_mod
from .irreducibility_layout import lcm_all
from . import irreducibility_residues as res


def common_of(x, y):
    """Both numbers on the sorted union of their flattened moduli: (moduli, xs, ys)."""
    fx, fy = res.flatten(x), res.flatten(y)
    moduli = sorted(set(fx[0]) | set(fy[0]))
    return moduli, res.base_extend(*fx, moduli), res.base_extend(*fy, moduli)


def cycle_on(m, x0, step):
    """(preperiod, period) of x0, x0 * step, x0 * step^2, ... modulo m."""
    seen = {}
    x, j = x0 % m, 0
    while x not in seen:
        seen[x] = j
        x, j = x * step % m, j + 1
    return seen[x], j - seen[x]


def _rhythm(moduli, starts, steps):
    mu, lams = 0, []
    for m, x0, st in zip(moduli, starts, steps):
        a, lam = cycle_on(m, x0, st)
        mu = max(mu, a)
        lams.append(lam)
    return mu, lcm_all(lams)


def op_add(x, y, sign):
    """A + B (sign 1) or A - B (sign -1) on the common moduli; wrap is the overflow /
    underflow read by comparing residue vectors; period of the repeated step = W / gcd(W, B)."""
    moduli, xs, ys = common_of(x, y)
    if sign > 0:
        out, wrap = res.add_res(moduli, xs, ys), res.add_overflow(moduli, xs, ys)
    else:
        out, wrap = res.sub_res(moduli, xs, ys), res.sub_underflow(moduli, xs, ys)
    period = lcm_all([m // euclid(m, b if b else m) for m, b in zip(moduli, ys)])
    return {"moduli": moduli, "residues": out, "wrap": wrap, "period": period}


def op_mul(x, y):
    """A * B on the common moduli, with the preperiod and period of A, AB, ABB, ..."""
    moduli, xs, ys = common_of(x, y)
    mu, lam = _rhythm(moduli, xs, ys)
    return {"moduli": moduli, "residues": res.mul_res(moduli, xs, ys),
            "preperiod": mu, "period": lam}


def op_pow(x, e):
    """A^e on the moduli of A (square-and-multiply per modulus, equal to powRes), with the
    preperiod and period of A, A^2, A^3, ..."""
    moduli, xs = res.flatten(x)
    mu, lam = _rhythm(moduli, xs, xs)
    return {"moduli": moduli, "residues": [pow(s, e, m) for m, s in zip(moduli, xs)],
            "preperiod": mu, "period": lam}


def op_div(x, b):
    """A / b. kind 'exact' when b divides A (residues on m / gcd(m, b)); else 'modular': the
    solutions of b x = A (mod W), d = gcd(b, W) of them modulo W / d, residues on
    m / gcd(m, b); 'none' when gcd(b, W) does not divide A. remainder is A mod b."""
    moduli, xs = res.flatten(x)
    ds = res.to_mixed_radix(moduli, xs)
    rem = res.eval_mod(ds, b)
    out = {"source_moduli": moduli, "remainder": rem, "moduli": res.div_moduli(moduli, b)}
    if rem == 0:
        out.update(kind="exact", residues=res.exact_div_res(moduli, xs, b))
        return out
    gs = [euclid(m, b) for m in moduli]
    if any(s % g for s, g in zip(xs, gs)):
        out.update(kind="none", residues=None)
        return out
    sols = []
    for m, s, g in zip(moduli, xs, gs):
        r = m // g
        sols.append(s // g * res.inv_mod(b // g % r, r) % r)
    d = euclid(prod_mod([r for _, r in ds], b) or b, b)
    out.update(kind="modular", residues=sols, d=d)
    return out


def op_address(x, t):
    """The address (i, [k]) of A with respect to T, or None unless T divides W (then the
    block index k is determined)."""
    moduli, xs = res.flatten(x)
    ds = res.to_mixed_radix(moduli, xs)
    if prod_mod([r for _, r in ds], t) != 0:
        return None
    i, k = res.address_res(moduli, xs, t)
    return {"source_moduli": moduli, "moduli": res.div_moduli(moduli, t), "i": i, "k": k}


def max_power_in(moduli, p):
    """The largest v with p^v dividing some modulus: the exponent of p in W."""
    best = 0
    for m in moduli:
        v = 0
        while m % p == 0:
            m //= p
            v += 1
        best = max(best, v)
    return best


def chapters(x, p, n):
    """Appending p^(v+1), ..., p^(v+n-1) to the moduli of A, v the exponent of p in W: one
    row per step j = 1..n with the modulus added (None for j = 1) and the lcm reached."""
    moduli = list(res.flatten(x)[0])
    v = max_power_in(moduli, p)
    rows = []
    for j in range(1, n + 1):
        added = None if j == 1 else p ** (v + j - 1)
        if added is not None:
            moduli.append(added)
        rows.append({"j": j, "added": added, "w": lcm_all(moduli)})
    return {"v": v, "rows": rows}


def residues_match(moduli, residues, value):
    """Whether the residues are those of value (an ordinary integer) on the moduli."""
    return all(s == value % m for m, s in zip(moduli, residues))
