"""
irreducibility_core.py -- residues, Euclid's algorithm and the radices of a mixed-radix
system over arbitrary moduli, mirroring the definitions of the Irreducibility repository
(lean/Irreducibility/Defs.lean: countMod, resid, euclid, prodMod, gcdProd, radices).

Each modulus m receives the radix m / gcd(m, product of the radices before it). The gcd is
computed by Euclid's algorithm on the residue of that product modulo m, built factor by
factor, so no intermediate value exceeds max(modulus) ** 2 and the product itself is never
formed. Nothing here refers to primes.
"""


def count_mod(d, t):
    """The residue of t modulo d by counting: add 1 per step, reset to 0 on reaching d."""
    r = 0
    for _ in range(t):
        r = 0 if r + 1 == d else r + 1
    return r


def resid(a, b):
    """The residue of a modulo b. Equal to count_mod(b, a) (Lean: countMod_eq); the
    built-in % keeps long lists fast."""
    return a % b


def euclid(a, b):
    """The gcd of a and b by Euclid's algorithm on residues."""
    while b:
        a, b = b, resid(a, b)
    return a


def prod_mod(radices, c):
    """The residue modulo c of the product of radices, factor by factor."""
    acc = 1 % c
    for r in radices:
        acc = (resid(r, c) * acc) % c
    return acc


def gcd_prod(radices, m):
    """The gcd of m with the product of radices, without forming the product."""
    return euclid(prod_mod(radices, m), m)


def radices(moduli):
    """The radices of the mixed-radix system of moduli, in order."""
    out = []
    for m in moduli:
        out.append(m // gcd_prod(out, m))
    return out
