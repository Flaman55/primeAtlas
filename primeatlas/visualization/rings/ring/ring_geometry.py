"""
ring_geometry.py -- pure numpy port of Structural Sieve's drum/ring geometry
(js/core/SieveModel.js + js/render/DrumRenderer.js in the RelationalMathematics
repo), independent of the browser app. This is the math half only: given a
sorted array of primes and a step N, compute where every ring's single "hit
tooth" sits in 2D space. No rendering, no I/O, no tkinter dependency -- same
convention as every non-GUI module in this package (the tkinter code lives in
the tab, section and widget modules) -- see primeatlas/visualization/shared/renderer.py
for the GPU-rendered interactive consumer of this module's output.

This module lets PrimeAtlas's own prime storage plus native compute/GPU drive the ring
visualization at a scale a browser tab cannot (target: ~20 million rings, interactive
pan/zoom). Correctness of these formulas is what everything rendered on top depends on.

Ported formulas (SieveModel.js/DrumRenderer.js are the reference and keep their own
design comments; they are not duplicated here):

  - Ring i (0-indexed, ascending prime order) among `count` active rings has
    radius = max_radius * ((i+1)/count) ** 0.85               (DrumRenderer.draw)
  - Its single drawn "tooth" sits at phase = n % prime, angle =
    phase * 2*pi/prime - pi/2                                  (DrumRenderer.#drawRingTeeth)
  - "Active" rings at step n = every prime <= n (sequential mode -- the only
    mode this module ports; SieveModel.js's "range" mode, a fixed already-
    loaded slice, is a trivial special case of "the caller decides which
    primes array to pass in", so it needs no separate code path here).

All functions below are vectorized (numpy arrays in, numpy arrays out) so they
stay cheap at the ring counts this feature exists to push (millions to tens
of millions) -- a Python-level loop per ring would defeat the entire point of
the GPU-scale ring count already proven feasible.

The window laws, anchors, highlight colors, resonance scan and tracked-prime
state built on these positions live in the sibling modules ring_windows.py,
ring_window_anchors.py, ring_window_colors.py, ring_resonance.py and
ring_tracked.py.
"""

import numpy as np

from primeatlas.visualization.shared.bigint import UINT64_MAX, to_prime_array


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

    Phase precision note: `n % primes` needs EXACT integer modulo, not a
    float64 approximation, for `is_hit` (phase == 0) to ever be correct at
    real storage-floor scale -- see to_prime_array's own doc-comment for why
    `primes_arr` itself is uint64 (fast, native, the common case, good for
    primes up to ~1.8e19) or `object` (exact Python ints, the slower
    fallback a real floor 25+ value needs; see that function's own
    doc-comment for why the cost is only ever paid when actually needed).

    A dtype-aware branch handles `n` past uint64 range: unconditionally
    reducing n via `n_int % (1 << 63)` before taking it mod a prime is
    silently WRONG (not just imprecise) for any `n >= 2**63`, since `(n %
    2**63) % p != n % p` in general (nothing makes 2**63 a multiple of an
    arbitrary prime p) -- such a reduction is only ever a no-op safety net
    for n already < 2**63, never a valid shortcut past it, which real
    floor-25+ viewing needs `n` to reach. Instead: `primes_arr` uint64 AND
    `n` fits uint64 keeps the fast vectorized `np.mod` path; anything
    past either ceiling routes through one `object`-dtype `np.mod` call
    (numpy dispatches this via Python's own exact int `%` per element --
    correct at any magnitude, paid only in this branch)."""
    count = len(primes)
    if count == 0:
        empty = np.empty(0, dtype=np.float64)
        return {
            "x": empty, "y": empty, "phase": empty.astype(np.uint64),
            "is_hit": empty.astype(bool), "radius": empty, "angle": empty,
        }

    primes_arr = to_prime_array(primes)
    radius = ring_radii(count, max_radius)

    n_int = int(n)
    if primes_arr.dtype == object or n_int > UINT64_MAX:
        phase = np.mod(n_int, primes_arr.astype(object) if primes_arr.dtype != object else primes_arr)
        if primes_arr.dtype != object:
            # primes all fit uint64 (only n itself was the oversized operand
            # above) -- phase < prime <= UINT64_MAX always, so it is safe (and
            # keeps every downstream consumer, e.g. build_vertex_data's own
            # `primes_arr >= 11` comparisons, on the cheap native dtype) to
            # bring the RESULT back down once the exact object-dtype mod
            # above has already done the actual work correctly.
            phase = phase.astype(np.uint64)
    else:
        phase = np.mod(np.uint64(n_int), primes_arr)

    angle = phase.astype(np.float64) * (2.0 * np.pi) / primes_arr.astype(np.float64) - (np.pi / 2.0)
    x = cx + radius * np.cos(angle)
    y = cy + radius * np.sin(angle)
    is_hit = phase == 0

    return {"x": x, "y": y, "phase": phase, "is_hit": is_hit, "radius": radius, "angle": angle}
