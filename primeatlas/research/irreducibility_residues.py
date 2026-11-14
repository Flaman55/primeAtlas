"""
irreducibility_residues.py -- numbers given by their residues on a list of moduli, mirroring
lean/Irreducibility/Defs.lean of the Irreducibility repository: mixed-radix representation
(evalMod, invMod, digitStep, toMixedRadix, eval), comparison (compareDigits, compareRes),
blocks (blockModulus, blockModuli, baseExtend, flatten, union, compareBlocks), interval atoms
(firstMultipleFrom, intervalAtoms) and arithmetic (addRes, subRes, addOverflow, subUnderflow,
mulRes, powRes, divModuli, exactDivRes, divModRes, addressRes).

A mixed-radix representation is a list of (digit, radix) pairs, least significant first.
Functions that Lean returns as Option return None here. A block representation is a dict with
the fields of Lean's BlockRep: blocks, residues, quot_blocks, quot_residues. Nothing here
refers to primes.
"""
from .irreducibility_core import euclid, gcd_prod, prod_mod, resid


def eval_mod(digits, c):
    """The residue modulo c of the value of a mixed-radix representation (Horner's rule from
    the most significant digit, every radix reduced modulo c)."""
    acc = 0
    for d, r in reversed(digits):
        acc = (d + resid(r, c) * acc) % c
    return acc


def inv_mod(a, b):
    """The least x >= 1 with x * a = 1 (mod b); 0 when b = 1 or a is not invertible. Lean
    finds it by repeated addition of a modulo b (invMod); here the extended Euclidean
    algorithm gives the same x (invMod_spec) in O(log b)."""
    if b == 1 or euclid(a % b, b) != 1:
        return 0
    return pow(a, -1, b)


def digit_step(acc, m, s):
    """The (digit, radix) that modulus m with residue s appends to acc; None when s is
    incompatible with the residues already represented."""
    rads = [r for _, r in acc]
    g = gcd_prod(rads, m)
    r = m // g
    y = (s + m - eval_mod(acc, m)) % m
    if y % g:
        return None
    if r > 1:
        return y // g * inv_mod(prod_mod(rads, m) // g % r, r) % r, r
    return 0, r


def to_mixed_radix(moduli, residues):
    """The mixed-radix representation of residues on moduli, or None."""
    acc = []
    for m, s in zip(moduli, residues):
        dr = digit_step(acc, m, s)
        if dr is None:
            return None
        acc.append(dr)
    return acc


def eval_digits(digits):
    """The value of a mixed-radix representation, below the product of its radices."""
    acc = 0
    for d, r in reversed(digits):
        acc = d + r * acc
    return acc


def compare_digits(dx, dy):
    """-1, 0 or 1 comparing two representations with the same radices, from the most
    significant digit."""
    for (a, _), (b, _) in zip(reversed(dx), reversed(dy)):
        if a != b:
            return -1 if a < b else 1
    return 0


def compare_res(moduli, xs, ys):
    """-1, 0 or 1 comparing two residue vectors on the same moduli, or None."""
    dx, dy = to_mixed_radix(moduli, xs), to_mixed_radix(moduli, ys)
    if dx is None or dy is None:
        return None
    return compare_digits(dx, dy)


def block_modulus(moduli, residues):
    """A block as one modulus: (product of the radices, value of the representation)."""
    ds = to_mixed_radix(moduli, residues)
    if ds is None:
        return None
    period = 1
    for _, r in ds:
        period *= r
    return period, eval_digits(ds)


def block_moduli(blocks, residues):
    """(block moduli, block residues) of a list of blocks, or None."""
    mods, vals = [], []
    for members, rs in zip(blocks, residues):
        b = block_modulus(members, rs)
        if b is None:
            return None
        mods.append(b[0])
        vals.append(b[1])
    return mods, vals


def base_extend(moduli, residues, target):
    """The residues on target of the number given by residues on moduli, or None."""
    ds = to_mixed_radix(moduli, residues)
    if ds is None:
        return None
    return [eval_mod(ds, c) for c in target]


def flatten(rep):
    """(moduli, residues) of a block representation: the block moduli followed by the
    quotient block moduli; a quotient block of modulus c with residue k receives
    (k * L + r) mod c, L being the lcm of the blocks and r the value they represent."""
    d = block_moduli(rep["blocks"], rep["residues"])
    k = block_moduli(rep["quot_blocks"], rep["quot_residues"])
    if d is None or k is None:
        return None
    dd = to_mixed_radix(*d)
    if dd is None:
        return None
    rads = [r for _, r in dd]
    quot = [(kc * prod_mod(rads, c) + eval_mod(dd, c)) % c for c, kc in zip(*k)]
    return d[0] + k[0], d[1] + quot


def union(rx, ry):
    """The moduli of rx followed by the moduli of ry not among them."""
    return rx + [c for c in ry if c not in rx]


def compare_blocks(x, y):
    """Compares two numbers in different block representations: flatten both, extend both
    to the union of their moduli, compare from the most significant digit. Returns a dict:
    verdict (-1, 0, 1), at (index of the deciding digit, -1 when equal), moduli, radices,
    digits_x, digits_y; None for incompatible residues."""
    fx, fy = flatten(x), flatten(y)
    if fx is None or fy is None:
        return None
    moduli = union(fx[0], fy[0])
    ex, ey = base_extend(*fx, moduli), base_extend(*fy, moduli)
    dx, dy = to_mixed_radix(moduli, ex), to_mixed_radix(moduli, ey)
    verdict, at = 0, -1
    for i in range(len(moduli) - 1, -1, -1):
        if dx[i][0] != dy[i][0]:
            verdict, at = (-1 if dx[i][0] < dy[i][0] else 1), i
            break
    return {"verdict": verdict, "at": at, "moduli": moduli, "radices": [r for _, r in dx],
            "digits_x": [d for d, _ in dx], "digits_y": [d for d, _ in dy]}


def first_multiple_from(lo, k):
    """The least multiple of k that is at least lo, from one residue."""
    r = resid(lo, k)
    return lo if r == 0 else lo + (k - r)


def interval_atoms(lo, hi):
    """The atoms of the interval lo..hi: the differences k = 2, ..., hi - lo for which the
    interval holds a and a + k with k | a, kept when no atom found before divides k."""
    atoms = []
    for k in range(2, hi - lo + 1):
        if first_multiple_from(lo, k) + k <= hi and all(resid(k, p) != 0 for p in atoms):
            atoms.append(k)
    return atoms


def add_res(moduli, xs, ys):
    return [(a + b) % m for m, a, b in zip(moduli, xs, ys)]


def sub_res(moduli, xs, ys):
    return [(a + (m - b)) % m for m, a, b in zip(moduli, xs, ys)]


def add_overflow(moduli, xs, ys):
    """The sum reaches the lcm of the moduli: its residues compare below the first term's."""
    return compare_res(moduli, add_res(moduli, xs, ys), xs) == -1


def sub_underflow(moduli, xs, ys):
    """The difference goes below 0: the first term compares below the second."""
    return compare_res(moduli, xs, ys) == -1


def mul_res(moduli, xs, ys):
    return [a * b % m for m, a, b in zip(moduli, xs, ys)]


def pow_res(moduli, xs, e):
    """The e-th power: e products modulus by modulus, from the residues of 1."""
    out = [resid(1, m) for m in moduli]
    for _ in range(e):
        out = mul_res(moduli, out, xs)
    return out


def div_moduli(moduli, t):
    """The moduli of the quotient by t: each m becomes m / gcd(m, t)."""
    return [m // euclid(m, t) for m in moduli]


def exact_div_res(moduli, residues, t):
    """Exact division by t (t divides the number), modulus by modulus."""
    out = []
    for m, s in zip(moduli, residues):
        g = euclid(m, t)
        r = m // g
        out.append(s // g * inv_mod(t // g % r, r) % r)
    return out


def div_mod_res(moduli, residues, t):
    """(remainder, residues of the quotient on div_moduli(moduli, t)) of the division by t,
    or None."""
    ds = to_mixed_radix(moduli, residues)
    if ds is None:
        return None
    r = eval_mod(ds, t)
    return r, exact_div_res(moduli, sub_res(moduli, residues, [resid(r, m) for m in moduli]), t)


def address_res(moduli, residues, t):
    """The address (i, [k]) with x = t (k - 1) + i, 1 <= i <= t; the residues of k are on
    div_moduli(moduli, t). None for incompatible residues."""
    dm = div_mod_res(moduli, residues, t)
    if dm is None:
        return None
    r, qs = dm
    if r == 0:
        return t, qs
    qm = div_moduli(moduli, t)
    return r, add_res(qm, qs, [resid(1, m) for m in qm])
