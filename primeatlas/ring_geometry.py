"""
ring_geometry.py -- pure numpy port of Structural Sieve's drum/ring geometry
(js/core/SieveModel.js + js/render/DrumRenderer.js in the RelationalMathematics
repo), independent of the browser app. This is the math half only: given a
sorted array of primes and a step N, compute where every ring's single "hit
tooth" sits in 2D space. No rendering, no I/O, no tkinter dependency -- same
convention as every other module in this package except settings_tab.py/
benchmark_tab.py/primes_tab.py/widgets.py (see this package's __init__.py's
own docstring) -- see primeatlas/ring_viz/renderer.py for the GPU-rendered
interactive consumer of this module's output.

Why this exists: Artur's proposal (2026-09-04) is that PrimeAtlas's own prime
storage ("magazyn") plus native compute/GPU could drive this same ring
visualization at a scale a browser tab never could. A standalone feasibility
prototype (structural_rings_poc.py, this file's original form before landing
in this package -- see PLAN.md's "Feasibility already confirmed" section)
was built and run on Artur's real hardware BEFORE this plan was written: 20
million rings, loaded in 0.27s, pan/zoom held 50+ fps even at a fast scroll,
N-change rebuild ~1.3s. This module is the "port the math correctly" half of
that already-proven result; get this wrong and nothing built on top of it
means anything.

Ported formulas (see SieveModel.js/DrumRenderer.js for the original JS +
Artur's own design-history comments on each -- not reproduced here to avoid
two copies drifting apart; this file trusts that one as the reference and
just translates it):

  - Ring i (0-indexed, ascending prime order) among `count` active rings has
    radius = max_radius * ((i+1)/count) ** 0.85               (DrumRenderer.draw)
  - Its single drawn "tooth" sits at phase = n % prime, angle =
    phase * 2*pi/prime - pi/2                                  (DrumRenderer.#drawRingTeeth)
  - "Active" rings at step n = every prime <= n (sequential mode -- the only
    mode this module ports; SieveModel.js's "range" mode, a fixed already-
    loaded slice, is a trivial special case of "the caller decides which
    primes array to pass in", so it needs no separate code path here).
  - Bertrand window: primeValue in (floor(n/2), n]              (isBertrandWindowMember)
  - Legendre level k: floor(sqrt(n-1)) for n>=2, else 0          (legendreLevelAt)
  - Legendre window: primeValue in (k*k, n]                      (isLegendreWindowMember)
  - General Law tent factor: piecewise-linear, 0 at theta=0.1,
    1 at theta=0.5, 0 at theta=1                                 (#generalLawTentFactor)
  - General Law window (stepped mode): lo = n - (n - k*k)*factor,
    clamped to lo < n; (sliding mode): lo = max(0, n - n**theta)
    (generalLawWindowBounds)

All functions below are vectorized (numpy arrays in, numpy arrays out) so they
stay cheap at the ring counts this feature exists to push (millions to tens
of millions) -- a Python-level loop per ring would defeat the entire point of
the GPU-scale ring count already proven feasible.
"""

import numpy as np


def ring_radii(count, max_radius):
    """radius array for `count` rings, ring i (0-indexed) at
    max_radius * ((i+1)/count) ** 0.85 -- see DrumRenderer.draw's `radius` line.
    Returns an empty array for count == 0 (no division-by-zero: numpy just
    returns an empty result for an empty `idx`)."""
    if count == 0:
        return np.empty(0, dtype=np.float64)
    idx = np.arange(1, count + 1, dtype=np.float64)
    t = idx / count
    return max_radius * np.power(t, 0.85)


def ring_positions(primes, n, max_radius, cx=0.0, cy=0.0):
    """Vectorized port of DrumRenderer's per-frame ring-position computation.

    `primes` -- ascending 1-D array (any int dtype) of every ACTIVE prime at
        step n (i.e. already filtered to primes <= n by the caller -- this
        function does not filter, so a caller keeping the full sorted array
        in memory should slice it first, the same way SieveModel.js's
        `primesUpTo(n)` already returns a pre-filtered ascending view rather
        than this module re-deriving it).
    `n` -- the current step (Python int, may exceed float64 precision for
        very large N -- see the phase computation note below).
    `max_radius`, `cx`, `cy` -- same meaning as DrumRenderer.draw's
        `maxRadius`/`cx`/`cy` (already resolved from canvas size * zoomValue
        and pan offset by the caller; this function has no opinion on camera).

    Returns a dict of same-length numpy arrays: x, y (position of each ring's
    single hit tooth), phase (n % prime), is_hit (phase == 0, i.e. this ring's
    tooth currently sits exactly at its "top" -- DrumRenderer's gold/orange
    dot case), radius, angle. Caller decides colors/highlighting on top of
    this (kept out of this module -- see module docstring: this is geometry
    only, same split as DrumRenderer.js deliberately not importing SieveModel.js).

    Phase precision note: `n % primes` is computed with Python's arbitrary-
    precision int modulo against each numpy element via `np.mod`, which
    upcasts to float64 for the division -- exact for any prime that fits in
    float64's 53-bit mantissa (i.e. primes below 2**53, far beyond any prime
    count a magazyn floor or GPU point budget will reach), but `n` itself
    should be reduced mod each prime in integer arithmetic, not float, once N
    itself grows past 2**53 (a floor-index concern, not a ring-count concern).
    This function uses `np.mod` on an int64 primes array (safe up to primes
    < 2**63) with a Python-int `n` reduced via plain integer mod first (see
    the implementation below for the exact guard).
    """
    count = len(primes)
    if count == 0:
        empty = np.empty(0, dtype=np.float64)
        return {
            "x": empty, "y": empty, "phase": empty.astype(np.int64),
            "is_hit": empty.astype(bool), "radius": empty, "angle": empty,
        }

    primes_arr = np.asarray(primes, dtype=np.int64)
    radius = ring_radii(count, max_radius)

    # Reduce n to a plain Python int first (safe for arbitrary size), then let
    # numpy's integer mod handle the elementwise part -- avoids float64
    # rounding entirely as long as `primes_arr` fits int64 (true for any
    # prime this project's magazyn will ever hold; see LOW_FLOOR_CUTOFF-style
    # floor scale in storage.py, nowhere near int64's ~9.2e18 ceiling).
    n_int = int(n)
    n_mod = n_int % (1 << 63)  # numpy int64 wraps past this; primes stay well below it
    phase = np.mod(n_mod, primes_arr)

    angle = phase.astype(np.float64) * (2.0 * np.pi) / primes_arr.astype(np.float64) - (np.pi / 2.0)
    x = cx + radius * np.cos(angle)
    y = cy + radius * np.sin(angle)
    is_hit = phase == 0

    return {"x": x, "y": y, "phase": phase, "is_hit": is_hit, "radius": radius, "angle": angle}


def legendre_level_at(n):
    """k such that k*k < n <= (k+1)*(k+1); 0 for n <= 1.
    Ports SieveModel.legendreLevelAt (see its own doc-comment for the
    off-by-one-at-perfect-squares history -- floor(sqrt(n-1)), NOT
    floor(sqrt(n)))."""
    if n <= 1:
        return 0
    return int(np.floor(np.sqrt(n - 1)))


def is_bertrand_member(primes, n):
    """Vectorized port of isBertrandWindowMember: primeValue in (floor(n/2), n]."""
    primes_arr = np.asarray(primes)
    lo = n // 2
    return (primes_arr > lo) & (primes_arr <= n)


def is_legendre_member(primes, n):
    """Vectorized port of isLegendreWindowMember: primeValue in (k*k, n]."""
    primes_arr = np.asarray(primes)
    k = legendre_level_at(n)
    lo = k * k
    return (primes_arr > lo) & (primes_arr <= n)


def general_law_tent_factor(theta):
    """Piecewise-linear tent: 0 at theta=0.1, 1 at theta=0.5, 0 at theta=1.
    Ports SieveModel.#generalLawTentFactor exactly (see that method's own
    doc-comment for why the two legs are not symmetric in raw theta units)."""
    if theta >= 0.5:
        return (1 - theta) / 0.5
    return (theta - 0.1) / 0.4


def general_law_window_bounds(n, theta, mode):
    """Ports SieveModel.generalLawWindowBounds. Returns (lo, hi, k, factor)
    with the same null-as-None conventions as the JS version (k/factor are
    None where the JS returns null)."""
    k = None
    factor = None
    if mode == "stepped":
        legendre_k = legendre_level_at(n)
        k = legendre_k
        if legendre_k == 0:
            lo = 0.0
        else:
            legendre_lo = legendre_k * legendre_k
            factor = general_law_tent_factor(theta)
            lo = n - (n - legendre_lo) * factor
            if lo >= n:
                lo = n - 1
    else:
        lo = n - (n ** theta)
        if lo < 0:
            lo = 0.0
    return lo, n, k, factor


def is_general_law_member(primes, n, theta, mode):
    """Vectorized port of isGeneralLawWindowMember."""
    primes_arr = np.asarray(primes)
    lo, hi, _k, _factor = general_law_window_bounds(n, theta, mode)
    return (primes_arr > lo) & (primes_arr <= hi)
