"""
irreducibility_comb.py -- the sech comb and the residue read from it, mirroring
lean/Irreducibility/SechComb.lean of the Irreducibility repository (sech, sechComb,
lastPeak, combResid).

sech_comb(s, d, t) sums the pulses sech(s * (t - d * j)) for j = t // d - 1, ..., t // d + 2.
Step t is a peak for d when the comb exceeds 1/2. From scale 3 on, the peaks are exactly the
multiples of d, so a minus the last peak up to a is a % b (Lean: combResid_eq). Below
scale 3 neighbouring pulses can overlap and the reading can fail.
"""
import math

PEAK_LEVEL = 0.5
"""A step is a peak when the comb exceeds this level."""

PROVED_SCALE = 3.0
"""From this scale on the comb reading equals the residue (Lean: combResid_eq)."""


def sech(x):
    """Hyperbolic secant; 0.0 where cosh overflows a float."""
    if abs(x) > 700.0:
        return 0.0
    return 1.0 / math.cosh(x)


def sech_comb(s, d, t):
    """The sech comb of modulus d at scale s and step t."""
    q = t // d
    return sum(sech(s * (t - d * (q + i))) for i in (-1, 0, 1, 2))


def last_peak(s, d, t):
    """The last step 1, ..., t at which the comb exceeds PEAK_LEVEL, or 0."""
    for u in range(t, 0, -1):
        if sech_comb(s, d, u) > PEAK_LEVEL:
            return u
    return 0


def comb_resid(s, a, b):
    """The residue of a modulo b read from the comb: the steps from the last peak to a."""
    return a - last_peak(s, b, a)
