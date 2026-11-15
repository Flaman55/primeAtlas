"""
hl_density.py -- the Hardy-Littlewood prediction for a k-tuple pattern: its singular series
constant C and the integral of 1 / (ln t)^k over a span, so the expected count of pattern
bases in [a, b) is C * hl_integral(a, b, k). No tkinter and no file I/O.

The constant comes from ktuple_wheel_v2_2.singular_series_constant(), the same one the
targeted k-tuple sieve sizes its fragments with.
"""
import functools
import math

import numpy as np

import ktuple_wheel_v2_2

SERIES_LIMIT = 200_000
"""Primes up to this bound enter the singular series product; arbitrary, the truncated tail
moves C by about 1e-4 relative at k = 15."""

SEGMENT_RATIO = 1.1
"""The integral splits [a, b) into segments whose ends differ by at most this factor;
arbitrary, keeps 1 / (ln t)^k smooth enough for an 8-point Gauss-Legendre rule."""

_NODES, _WEIGHTS = np.polynomial.legendre.leggauss(8)
_NODES01 = [(float(x) + 1.0) / 2.0 for x in _NODES]
_WEIGHTS01 = [float(w) / 2.0 for w in _WEIGHTS]


def hl_integral(a, b, k):
    """The integral of 1 / (ln t)^k over [a, b), integers a and b; the part below 2 is left
    out (1 / ln t has its pole at t = 1). Each segment [s, e) evaluates ln t as
    ln s + log1p((t - s) / s), so a span narrow next to its magnitude (10^8 wide at 10^25)
    keeps full precision."""
    a = max(int(a), 2)
    b = int(b)
    total = 0.0
    s = a
    while s < b:
        e = min(b, s + max(1, int(s * (SEGMENT_RATIO - 1.0))))
        width = e - s
        ln_s = math.log(s)
        part = 0.0
        for x, w in zip(_NODES01, _WEIGHTS01):
            part += w / (ln_s + math.log1p(width * x / s)) ** k
        total += part * width
        s = e
    return total


@functools.lru_cache(maxsize=None)
def _constant(offsets):
    return ktuple_wheel_v2_2.singular_series_constant(list(offsets), len(offsets),
                                                      limit=SERIES_LIMIT)


def pattern_constant(offsets):
    """C for this offset pattern; 0.0 for an inadmissible one (it covers every residue
    modulo some prime)."""
    return _constant(tuple(offsets))


def expected_count(offsets, intervals):
    """The predicted number of pattern bases in the union of the disjoint [a, b) spans."""
    c = pattern_constant(offsets)
    if c == 0.0:
        return 0.0
    k = len(offsets)
    return c * sum(hl_integral(a, b, k) for a, b in intervals)


def compare(hits, expected):
    """(ratio, sigma): hits / expected and (hits - expected) / sqrt(expected), the Poisson
    deviation; both None when expected is 0."""
    if expected <= 0:
        return None, None
    return hits / expected, (hits - expected) / math.sqrt(expected)
