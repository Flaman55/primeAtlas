"""
ring_geometry.py -- pure numpy port of Structural Sieve's drum/ring geometry
(js/core/SieveModel.js + js/render/DrumRenderer.js in the RelationalMathematics
repo), independent of the browser app. This is the math half only: given a
sorted array of primes and a step N, compute where every ring's single "hit
tooth" sits in 2D space. No rendering, no I/O, no tkinter dependency -- same
convention as every other module in this package except settings_tab.py/
benchmark_tab.py/primes_tab.py/widgets.py (see this package's __init__.py's
own docstring) -- see primeatlas/visualization/shared/renderer.py for the GPU-rendered
interactive consumer of this module's output.

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

import math

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


def legendre_level_at(n):
    """k such that k*k < n <= (k+1)*(k+1); 0 for n <= 1.
    Ports SieveModel.legendreLevelAt (see its own doc-comment for the
    off-by-one-at-perfect-squares history -- floor(sqrt(n-1)), NOT
    floor(sqrt(n))).

    Uses math.isqrt rather than `int(np.floor(np.sqrt(n - 1)))`: np.sqrt
    cannot operate on a Python int outside float64's representable range
    (numpy falls back to an object-dtype ufunc loop that calls `.sqrt()` on
    the value itself, which a plain int has no such method for) -- this
    matters at real storage-floor scale (N ~10**25, far beyond what
    float64/np.sqrt can represent), where that path raises a TypeError.
    math.isqrt is the exact integer-only equivalent of floor(sqrt(...)) for
    any non-negative Python int, arbitrarily large, with no float
    conversion (and thus no precision loss either, unlike the np.sqrt path
    even when it does work) -- the same big-int-safe approach
    ring_positions/to_prime_array already use."""
    if n <= 1:
        return 0
    return math.isqrt(n - 1)


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
    None where the JS returns null).

    Two RIGID modes ignore theta entirely: 'bertrand' reproduces is_bertrand_member's
    lo (n//2) exactly, 'legendre' reproduces is_legendre_member's lo (k*k) exactly --
    unlike stepped/sliding's theta-parameterized curves. See general_law_anchor_at for
    why the ANCHOR also delegates directly for 'bertrand'."""
    if mode == "bertrand":
        return n // 2, n, None, None
    if mode == "legendre":
        k = legendre_level_at(n)
        return k * k, n, k, None
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


def _fade_previous_level(primes_arr, k, exposure_count, live):
    """Shared fade-continuity core behind is_legendre_highlighted and
    is_general_law_highlighted's 'stepped' branch. Treats the PREVIOUS level's
    members ((k-1)^2, k^2]) as a queue, oldest (smallest) first: for every
    member the CURRENT level has exposed the viewer to so far
    (`exposure_count`), retires exactly one -- the smallest still-
    surviving -- member of that queue. A previous-level member is therefore
    still highlighted iff its rank among the previous level's own members
    (sorted ascending) is >= exposure_count.

    `exposure_count` is deliberately a SEPARATE argument from `live`
    (the mask this call ultimately OR's the survivors into), not simply
    `count_nonzero(live)` -- see is_general_law_highlighted's own 'stepped'
    branch for why: a family's own CURRENT-level membership test can be
    narrower than Legendre's plain (k^2, n] and can therefore FLICKER a
    prime back OUT of membership later in the same level (its own `lo`
    keeps creeping up as n grows, unlike Legendre's fixed-for-the-level
    k^2), which would make a naive `count_nonzero(live)` NON-monotonic
    within a level and let it retire FEWER previous-level members than it
    already had -- i.e. resurrect an already-retired one. `exposure_count`
    must be a monotonically non-decreasing count of DISTINCT primes the
    current level has EVER exposed the viewer to (up to and including
    y=n), which for plain Legendre happens to equal `count_nonzero(live)`
    exactly (its own raw membership test never flickers within a level:
    once a prime is included, it can never fail (k^2, n] again as n only
    grows and k stays fixed) -- see is_legendre_highlighted's own call
    below, which passes exactly that.

    k<2 (no previous level exists; only reachable while the window is still very
    narrow) returns `live` unchanged -- no fabricated previous level."""
    if k < 2:
        return live
    prev_lo = (k - 1) * (k - 1)
    prev_hi = k * k
    old_mask = (primes_arr > prev_lo) & (primes_arr <= prev_hi)
    old_members = np.sort(primes_arr[old_mask])
    if old_members.size == 0 or exposure_count >= old_members.size:
        return live
    threshold = old_members[exposure_count]
    old_survive_mask = old_mask & (primes_arr >= threshold)
    return live | old_survive_mask


def is_legendre_highlighted(primes, n):
    """The RENDERING variant of Legendre membership, used for the ring's
    highlight (teeth) color -- is_legendre_member stays the strict mathematical
    test.

    With is_legendre_member alone, every highlighted prime of a level goes dark in
    the same step the level advances, before the new level has produced any member
    of its own. (Bertrand needs no such layer: consecutive Bertrand windows always
    overlap, see is_bertrand_member.)

    Rule (mechanics in _fade_previous_level): the previous level's members form a
    queue, oldest (smallest) first; for every member the current level has produced
    so far, exactly one survivor is retired. The fade therefore never outlasts the
    previous level's own population -- a bound tied to the level structure, not a
    per-prime multiple. It also shows whether the new level is richer or sparser: with
    FEWER members, exposure never catches up and some old members stay lit; with MORE,
    the old queue empties before the new level finishes.

    A PURE function of n -- both the previous level's membership and the current
    level's count so far are recomputable from n and the prime list -- so it stays
    consistent under rewind/backward steps, where a stateful per-tick queue would
    desync (same "everything is a pure function of n" convention as
    bertrand_anchor_at)."""
    primes_arr = np.asarray(primes)
    live = is_legendre_member(primes_arr, n)
    k = legendre_level_at(n)
    exposure_count = int(np.count_nonzero(live))
    return _fade_previous_level(primes_arr, k, exposure_count, live)


def is_general_law_highlighted(primes, n, theta, mode):
    """General Law's rendering-highlight test, same role as is_legendre_highlighted
    for Legendre -- is_general_law_member stays the strict test for every mode.

    'bertrand'/'sliding' use plain is_general_law_member: both already creep
    smoothly ('sliding' has no level to reset from; 'bertrand' delegates to
    is_bertrand_member's always-overlapping window).

    'legendre' delegates to is_legendre_highlighted -- an exact reproduction of the
    Legendre checkbox, fade included, which is the point of a RIGID mode.

    'stepped' reuses the same _fade_previous_level core as 'legendre', except that
    the `exposure_count` passed to it is NOT count_nonzero of stepped's own (narrower)
    live mask. Stepped's `lo` keeps creeping up throughout a level (a blend of n and
    Legendre's lo), so a prime can enter stepped's window when born and leave it later
    in the SAME level; a count of the live mask would be non-monotonic within a level
    and could retire FEWER previous-level members than before, resurrecting one.

    Instead `exposure_count` is Legendre's plain membership count, provably exact.
    Proof: at the exact moment a
    prime p is born (n=p), stepped's own lo(p) = p*(1-factor) +
    legendre_lo*factor < p whenever factor > 0 and p > legendre_lo (both
    always true for an active prime inside the current level -- and even
    at the tent's own factor=0 edges, general_law_window_bounds' own
    empty-window guard clamps lo to n-1 < n = p) -- i.e. EVERY prime in the
    current level satisfies stepped's own window at least momentarily, right
    when it's born, regardless of theta. So "how many distinct primes has
    stepped's own window EVER exposed the viewer to during this level" is
    always exactly equal to plain Legendre's own (monotonic) membership
    count for the same level -- the two are provably identical, not just
    coincidentally close. `live` itself (what gets OR'd with the surviving
    previous-level members) stays stepped's own narrower, possibly-flickering
    test, unaffected -- that within-level flicker is a separate, already-
    accepted property of a narrow window (same as 'sliding' mode's own
    sparse, one-prime-at-a-time look), not something this fade layer is
    meant to smooth over."""
    if mode == "legendre":
        return is_legendre_highlighted(primes, n)
    if mode == "stepped":
        primes_arr = np.asarray(primes)
        live = is_general_law_member(primes_arr, n, theta, mode)
        k = legendre_level_at(n)
        exposure_count = int(np.count_nonzero(is_legendre_member(primes_arr, n)))
        return _fade_previous_level(primes_arr, k, exposure_count, live)
    return is_general_law_member(primes, n, theta, mode)


# ---------------------------------------------------------------------------
# Highlight-color blending -- ports StructuralSieveApp.js's
# #windowHighlightFamilies / #computeHighlightColor / #computeTrackedColor /
# #activeWindowCount into vectorized numpy form. See that file for the full
# design rationale on why the blend is additive-RGB. Legendre's (and General
# Law's 'legendre' mode's) own highlight test is is_legendre_highlighted --
# see that function's own doc-comment for the fade-continuity design (a fade bounded
# by the previous level's population, not a per-prime grace period, which would
# light up a band nearly as wide as Bertrand's window).
# The JS versions operate per single (n, prime) pair, called once per ring
# per animation tick; this module instead computes highlight color for EVERY
# active ring at once (a whole-frame batch), which is what the ring-count
# scale this feature exists for actually needs -- a Python-level loop over
# millions of rings would defeat that scale the same way it would for
# ring_positions() above.
# ---------------------------------------------------------------------------

#: Same three families, same colors, as StructuralSieveApp.js's
#: #windowHighlightFamilies registry (bertrand=#ff33cc, legendre=#39ff14,
#: generalLaw=#a855f7). A caller enables a subset via `enabled_ids` on the
#: functions below -- this list itself never needs to change to add/remove a
#: family from a given render, only to add an entirely new family type.
WINDOW_FAMILY_COLORS = {
    "bertrand": (255, 51, 204),
    "legendre": (57, 255, 20),
    "generalLaw": (168, 85, 247),
}


#: Registry of family_id -> callable(n, theta, mode) -> (lo, hi) numeric bounds -- the
#: same shape ANCHOR_FUNCTIONS uses for anchors. A new window family needs one entry
#: here (plus WINDOW_FAMILY_COLORS and WINDOW_MEMBER_FUNCTIONS entries);
#: window_label_colors/compute_highlight_colors iterate `enabled_ids` through these
#: registries and need no change. theta/mode are unused by bertrand/legendre (uniform
#: call signature across families).
WINDOW_BOUNDS_FUNCTIONS = {
    "bertrand": lambda n, theta, mode: (n // 2, n),
    "legendre": lambda n, theta, mode: (legendre_level_at(n) ** 2, n),
    "generalLaw": lambda n, theta, mode: general_law_window_bounds(n, theta, mode)[:2],
}

#: Registry of family_id -> callable(primes_arr, n, theta, mode) -> bool array, for
#: compute_highlight_colors' per-ring highlight test. "legendre"/"generalLaw" go through
#: is_legendre_highlighted/is_general_law_highlighted (the fade-continuity layer);
#: "bertrand" uses its strict test (its window overlap already gives continuity).
#: WINDOW_BOUNDS_FUNCTIONS stays the plain mathematical lo/hi: nested_shell_colors'
#: containment logic needs the real window bounds, not the rendering-only fade.
WINDOW_MEMBER_FUNCTIONS = {
    "bertrand": lambda primes_arr, n, theta, mode: is_bertrand_member(primes_arr, n),
    "legendre": lambda primes_arr, n, theta, mode: is_legendre_highlighted(primes_arr, n),
    "generalLaw": lambda primes_arr, n, theta, mode: is_general_law_highlighted(primes_arr, n, theta, mode),
}

#: The plain STRICT mathematical membership test per family, no fade layer -- mirrors
#: StructuralSieveApp.js's `isStrictMember` field on #windowHighlightFamilies (Bertrand
#: has no separate strict test there either: its isHighlighted already is strict). Used
#: by compute_highlight_colors' two-tier precedence to decide, per ring, whether a
#: family's fade-only match may blend in or is overridden by another family's live match.
STRICT_MEMBER_FUNCTIONS = {
    "bertrand": lambda primes_arr, n, theta, mode: is_bertrand_member(primes_arr, n),
    "legendre": lambda primes_arr, n, theta, mode: is_legendre_member(primes_arr, n),
    "generalLaw": lambda primes_arr, n, theta, mode: is_general_law_member(primes_arr, n, theta, mode),
}


def window_label_colors(enabled_ids, n, theta=0.5, mode="stepped"):
    """Colors for the HUD's window-range text lines (e.g. "Bertrand window:
    (70, 141]") -- each enabled family's own WINDOW_FAMILY_COLORS entry,
    unconditionally, never blended: a label identifies one window, and must stay
    readable as that family's color even though rings can be inside 2+ windows at once
    (Bertrand's window always contains Legendre's, so no ring is ever pure green).
    Blends are shown separately, by nested_shell_colors' legend lines.

    Returns dict family_id -> (r, g, b) int 0-255 tuple, one entry per id in
    `enabled_ids` that is a real WINDOW_FAMILY_COLORS key (unknown ids are
    silently skipped, same permissive convention window_anchor_primes
    uses)."""
    return {
        family_id: tuple(int(c) for c in WINDOW_FAMILY_COLORS[family_id])
        for family_id in enabled_ids
        if family_id in WINDOW_FAMILY_COLORS
    }


def nested_shell_colors(enabled_ids, n, theta=0.5, mode="stepped"):
    """A small color LEGEND for the HUD: one entry per distinct NESTING LEVEL among
    `enabled_ids`' real windows at this n, mapping frozenset(family ids active from
    that level inward) to the AVERAGED (r, g, b) of their registered colors.

    Every window family shares the same right edge n (see isBertrandWindowMember), so
    of any two enabled windows one always contains the other (never a crossing
    overlap) and comparing `lo` gives a total order. Enabled families therefore form a
    chain of nested shells, outermost (smallest lo) to innermost (largest lo). The
    widest shell is a single family (already shown by its own solid-color line in
    window_label_colors), and each narrower shell adds one family to the blend --
    len(distinct lo values) - 1 entries, not every subset or pair (3 families with 3
    distinct `lo` give 2 entries: Bertrand+Legendre, then +General Law). Families whose
    `lo` ties exactly (e.g. General Law at theta=0.5, identical to Legendre) open the
    same shell together, since their windows are the same set of primes.

    Same dynamic-registry convention as WINDOW_BOUNDS_FUNCTIONS/WINDOW_
    MEMBER_FUNCTIONS/ANCHOR_FUNCTIONS: a future 4th window family needs only
    its own WINDOW_BOUNDS_FUNCTIONS/WINDOW_FAMILY_COLORS entries -- this
    function automatically grows to however many shells that family's own
    `lo` creates. Relies on every registered family sharing n as its right edge; a
    family that did not would break the total order the shell chain depends on."""
    bounds_by_family = {}
    for family_id in enabled_ids:
        if family_id not in WINDOW_BOUNDS_FUNCTIONS or family_id not in WINDOW_FAMILY_COLORS:
            continue
        bounds_by_family[family_id] = WINDOW_BOUNDS_FUNCTIONS[family_id](n, theta, mode)

    registry_order = list(WINDOW_FAMILY_COLORS.keys())
    by_lo = {}
    for family_id, (lo, _hi) in bounds_by_family.items():
        by_lo.setdefault(lo, []).append(family_id)
    for lo in by_lo:
        by_lo[lo].sort(key=registry_order.index)

    result = {}
    running = []
    for lo in sorted(by_lo.keys()):
        running = running + by_lo[lo]
        if len(running) >= 2:
            colors = np.array([WINDOW_FAMILY_COLORS[fid] for fid in running], dtype=np.float64)
            averaged = colors.mean(axis=0)
            result[frozenset(running)] = tuple(int(round(c)) for c in averaged)
    return result


def _largest_below(sorted_arr, bound):
    """Largest element of ascending `sorted_arr` strictly less than `bound`,
    or None if none exists. Ports SieveModel's private #largestBelow binary
    search via np.searchsorted (equivalent asymptotics, no Python-level loop)."""
    if len(sorted_arr) == 0:
        return None
    idx = np.searchsorted(sorted_arr, bound, side="left")
    return int(sorted_arr[idx - 1]) if idx > 0 else None


def bertrand_anchor_at(primes, n):
    """Ports SieveModel.bertrandAnchorAt: the frozen/jumping Bertrand witness
    at step n (see that method's own doc-comment for the freeze/jump rule).
    Returns a single int or None (no active primes yet)."""
    primes_arr = to_prime_array(primes)
    if len(primes_arr) == 0:
        return None
    anchor = int(primes_arr[0])
    while n >= 2 * anchor:
        candidate = _largest_below(primes_arr, 2 * anchor)
        if candidate is None or candidate <= anchor:
            break
        anchor = candidate
    return anchor


def legendre_anchor_at(primes, n):
    """Ports SieveModel.legendreAnchorAt: largest active prime strictly below
    the current level's own opening edge k*k. Returns None if none exists
    (k in {0,1})."""
    primes_arr = to_prime_array(primes)
    if len(primes_arr) == 0:
        return None
    k = legendre_level_at(n)
    return _largest_below(primes_arr, k * k)


def general_law_anchor_at(primes, n, theta, mode):
    """Ports SieveModel.generalLawAnchorAt: largest active prime at or below
    the window's own current opening edge `lo` (computed as "strictly below
    floor(lo)+1", equivalent for integer primes -- see the JS method's own
    doc-comment).

    'bertrand' delegates to bertrand_anchor_at's own
    stateful witness-doubling chain, NOT this generic "largest active prime
    <= floor(lo)" recompute -- these can genuinely disagree (n=10:
    floor(10/2)=5, largest active prime <=5 is 5, but the real chain
    2->3->5->7 lands on 7, since n=10 >= 2*5 one more time -- see
    bertrand_anchor_at's own doc-comment for why the anchor is a jump chain,
    not a plain threshold). 'legendre' delegates to legendre_anchor_at too --
    already provably equal to the generic recompute, but delegating directly
    makes "pure Legendre underneath" literal rather than an indirect
    equivalence."""
    if mode == "bertrand":
        return bertrand_anchor_at(primes, n)
    if mode == "legendre":
        return legendre_anchor_at(primes, n)
    primes_arr = to_prime_array(primes)
    if len(primes_arr) == 0:
        return None
    lo, _hi, _k, _factor = general_law_window_bounds(n, theta, mode)
    return _largest_below(primes_arr, int(np.floor(lo)) + 1)


ANCHOR_FUNCTIONS = {
    "bertrand": lambda primes, n, theta, mode: bertrand_anchor_at(primes, n),
    "legendre": lambda primes, n, theta, mode: legendre_anchor_at(primes, n),
    "generalLaw": lambda primes, n, theta, mode: general_law_anchor_at(primes, n, theta, mode),
}


def cyclic_window_anchor_at(anchor_state, family_id, primes, n, theta=0.5, mode="stepped"):
    """Legendre/General Law's tracked-ring anchor -- not a port of SieveModel.js.
    Used by renderer.py for the tracked-ring OUTLINE of "legendre"/"generalLaw";
    legendre_anchor_at/general_law_anchor_at and ANCHOR_FUNCTIONS remain for Bertrand
    and other callers.

    Bertrand's freeze/jump rule (jump once n >= 2*anchor) works on its wide (n/2, n]
    window, but Legendre/General Law's window is only a few dozen points wide near the
    start of the axis and narrows as N grows, too narrow for a 2x condition. A plain
    per-call recomputation (whatever prime sits at the window's edge) selects a
    different ring almost every step.

    Rule: the anchor freezes at the window's RIGHT edge (the largest active prime <= n)
    when a new window opens and stays there while that window is open; newer rings
    enter to its right. When a new window opens, it re-freezes at the new right edge.

    "A new window opens" differs by family. Legendre's `lo` (= k*k) is constant per
    level and jumps only at perfect squares, so it means legendre_level_at(n) changed.
    General Law's `lo` (general_law_window_bounds) is not constant per level in
    general: "sliding" has no levels (`lo = n - n**theta` creeps on every n), and
    "stepped" (`lo = n - (n - legendre_lo) * factor`, factor =
    general_law_tent_factor(theta)) equals Legendre's constant `lo` only at theta=0.5
    (factor == 1); for any other theta, `lo` creeps within a level. Keying stepped mode
    on the Legendre level for every theta would give it exactly Legendre's anchor even
    when the two windows differ (e.g. Legendre (1156,1199] vs. General Law theta=0.3
    (1177,1199]). Hence:

      - family_id == "legendre", or "generalLaw" with mode == "stepped"
        AND theta == 0.5 exactly (factor == 1.0, `lo` piecewise-constant
        per level, identical to Legendre's own): keyed on
        legendre_level_at(n) -- re-anchor at the window's own right edge
        exactly when the level differs from the level the currently-frozen
        anchor was picked under (an immediate re-freeze right after re-anchoring is
        expected: the new anchor's level equals the level just entered, so the next
        call at the same level leaves it untouched).
      - family_id == "generalLaw" with mode == "sliding", OR "stepped" with
        any theta != 0.5: keyed on the numeric `lo` from
        general_law_window_bounds -- re-anchor whenever the frozen anchor
        is <= the CURRENT call's `lo` (which, since it creeps up by a
        little on every single n in both these cases, is what makes the
        anchor eventually "become the window's own left edge").

    `anchor_state` is a plain per-family-id dict the CALLER owns and keeps
    across rebuild_buffer calls (renderer.py's run() holds one, same
    convention as its own orbit_state/resonance_log_state dicts) -- this
    function is otherwise a pure function of (state, n). Calling it twice
    in a row with the same n is idempotent (the re-anchor condition, re-
    evaluated against the just-updated state, no longer holds). Calling it
    after an arbitrary FORWARD jump in n (goto/load range, not just a live-
    playback tick) self-corrects on that very call, since both the level
    and `lo` are always recomputed fresh from the actual current n rather
    than accumulated incrementally step by step.

    family_id must be "legendre" or "generalLaw" -- Bertrand has no cyclic
    state of its own and keeps using bertrand_anchor_at (via
    ANCHOR_FUNCTIONS) directly."""
    primes_arr = to_prime_array(primes)
    if family_id not in ("legendre", "generalLaw"):
        raise ValueError(f"cyclic_window_anchor_at does not support family_id {family_id!r}")

    if family_id == "legendre":
        # Legendre proper has no separate sliding variant (mirrors
        # ANCHOR_FUNCTIONS["legendre"] itself ignoring mode/theta) -- always
        # level-keyed.
        level_keyed = True
    elif mode == "bertrand":
        # generalLaw's rigid 'bertrand' mode has no cyclic state either (same reason
        # family_id=="bertrand" is rejected below): bertrand_anchor_at's freeze/jump
        # chain is already a complete cadence computed from (primes, n). A second
        # level/lo freeze on top would conflict with it, so anchor_state is bypassed and
        # the call delegated, like ANCHOR_FUNCTIONS["bertrand"] for the checkbox.
        return bertrand_anchor_at(primes_arr, n)
    elif mode == "legendre":
        # generalLaw's own rigid 'legendre' mode has EXACTLY Legendre's own
        # level concept (lo=k*k, piecewise-constant per level) -- same
        # level-keyed branch as family_id=="legendre" itself, not the
        # numeric lo-creep branch below (which would still converge to the
        # same visual result almost always, per the numeric-creep analysis,
        # but level-keying it directly makes the equivalence exact and
        # explicit rather than an emergent coincidence).
        level_keyed = True
    else:
        # generalLaw: level-keyed ONLY when its own `lo` is provably
        # identical to Legendre's constant-per-level `lo` (see this
        # function's own doc-comment for why any other theta must NOT take
        # this branch).
        level_keyed = mode == "stepped" and general_law_tent_factor(theta) == 1.0

    entry = anchor_state.setdefault(family_id, {"anchor": None, "level": None})
    if level_keyed:
        level = legendre_level_at(n)
        if entry["anchor"] is None or entry["level"] != level:
            entry["anchor"] = _largest_below(primes_arr, n + 1)
            entry["level"] = level
    else:
        lo, _hi, _k, _factor = general_law_window_bounds(n, theta, mode)
        if entry["anchor"] is None or entry["anchor"] <= lo:
            entry["anchor"] = _largest_below(primes_arr, n + 1)
    return entry["anchor"]


def _blend_family_colors(masks_by_family):
    """Shared color-blend core used by both compute_highlight_colors and
    compute_tracked_colors below, factored out because both differ only in
    HOW each family's per-ring participation mask is derived (strict window
    membership for highlight color; plain anchor-equality for tracked
    color -- see the two callers below).

    Colors are AVERAGED per matched ring, not summed and clamped to 255: summing
    already-saturated 0-255 channels clips toward white almost immediately (e.g.
    Bertrand+Legendre+General Law -> (255,255,224), which reads as "unhighlighted").
    Averaging lets each contributing family visibly pull the result toward its own
    color (pink+green -> muted olive) and scales to any number of matched families.

    `masks_by_family` -- dict of family_id -> boolean numpy array (same
    length, one entry per ring): True where that family contributes its
    color to that ring.

    Returns (colors, matched) -- colors is an (N, 3) float64 array (channel
    values already in [0, 255] by construction -- an average of values each
    already in that range can never leave it, the np.clip below is a
    defensive no-op, not load-bearing -- NOT yet cast to uint8 so a caller
    can still do further math before quantizing for a GPU buffer -- see
    build_vertex_data's own float32 buffer for why this module leaves that
    choice to the renderer), matched is an (N,) boolean array, True where at
    least one family contributed (the null/None case in the JS version)."""
    if not masks_by_family:
        n = 0
    else:
        n = len(next(iter(masks_by_family.values())))
    colors = np.zeros((n, 3), dtype=np.float64)
    counts = np.zeros(n, dtype=np.float64)
    matched = np.zeros(n, dtype=bool)
    for family_id, mask in masks_by_family.items():
        color = np.asarray(WINDOW_FAMILY_COLORS[family_id], dtype=np.float64)
        colors[mask] += color
        counts[mask] += 1
        matched |= mask
    if np.any(matched):
        colors[matched] /= counts[matched][:, None]
    np.clip(colors, 0, 255, out=colors)
    return colors, matched


def compute_highlight_colors(primes, n, enabled_ids, theta=0.5, mode="stepped"):
    """Vectorized port of #computeHighlightColor for every ring in `primes`
    at once. `enabled_ids` is an iterable of family ids from
    WINDOW_FAMILY_COLORS currently toggled on (e.g. {"bertrand", "legendre"}).

    WINDOW_MEMBER_FUNCTIONS includes a fade-continuity layer for Legendre/General Law
    (see is_legendre_highlighted), so this applies the same two-tier strict/sticky
    precedence as the JS reference's #computeHighlightColor: for each ring, every
    enabled family's STRICT_MEMBER_FUNCTIONS test is checked first; if ANY family
    strictly matches, ONLY the strictly-matching families contribute to the blend (a
    family matching only through its fade layer is excluded); otherwise every family's
    WINDOW_MEMBER_FUNCTIONS result (fade included) is used. This keeps a ring strictly
    inside Bertrand's window pure Bertrand pink instead of blending with Legendre's
    fading remnants.

    Returns (colors, matched) -- see _blend_family_colors's own docstring for
    the exact shape; `matched[i] is False` is this function's counterpart to
    the JS version returning null for ring i.

    The per-family membership dispatch is the WINDOW_MEMBER_FUNCTIONS/
    STRICT_MEMBER_FUNCTIONS registries instead of a hardcoded if/elif/raise --
    same "add a family, don't touch this function" convention ANCHOR_
    FUNCTIONS/WINDOW_BOUNDS_FUNCTIONS already established."""
    primes_arr = to_prime_array(primes)
    count = len(primes_arr)

    strict_by_family = {}
    sticky_by_family = {}
    for family_id in enabled_ids:
        if family_id not in WINDOW_MEMBER_FUNCTIONS:
            raise ValueError(f"unknown window family id {family_id!r}")
        strict_by_family[family_id] = STRICT_MEMBER_FUNCTIONS[family_id](primes_arr, n, theta, mode)
        sticky_by_family[family_id] = WINDOW_MEMBER_FUNCTIONS[family_id](primes_arr, n, theta, mode)

    if not strict_by_family:
        return np.zeros((count, 3), dtype=np.float64), np.zeros(count, dtype=bool)

    any_strict = np.zeros(count, dtype=bool)
    for mask in strict_by_family.values():
        any_strict |= mask

    masks_by_family = {
        family_id: strict_by_family[family_id] | (sticky_by_family[family_id] & ~any_strict)
        for family_id in enabled_ids
    }
    return _blend_family_colors(masks_by_family)


def compute_tracked_colors(primes, n, enabled_ids, theta=0.5, mode="stepped", anchor_overrides=None):
    """Vectorized port of #computeTrackedColor: for each ring, sums the
    colors of every enabled family whose OWN anchor (bertrand_anchor_at /
    legendre_anchor_at / general_law_anchor_at, or `anchor_overrides` below)
    is exactly that ring's prime. A different question from compute_highlight_colors
    (window membership): two anchors that satisfy each other's window-membership test
    must still get their own colors.

    `anchor_overrides` -- optional {family_id: anchor}
    dict; when a family_id is a key here (even with value None), its value
    is used directly instead of calling ANCHOR_FUNCTIONS[family_id] -- this
    is how renderer.py feeds in cyclic_window_anchor_at's own stateful
    "legendre"/"generalLaw" anchors (see that function's own doc-comment)
    while Bertrand keeps resolving through ANCHOR_FUNCTIONS. A family_id absent from
    this dict falls back to ANCHOR_FUNCTIONS; None (the default) means no overrides.

    Returns (colors, matched) -- same shape as compute_highlight_colors."""
    primes_arr = to_prime_array(primes)
    count = len(primes_arr)

    masks = {}
    for family_id in enabled_ids:
        if anchor_overrides is not None and family_id in anchor_overrides:
            anchor = anchor_overrides[family_id]
        else:
            anchor = ANCHOR_FUNCTIONS[family_id](primes_arr, n, theta, mode)
        masks[family_id] = (primes_arr == anchor) if anchor is not None else np.zeros(count, dtype=bool)

    if not masks:
        return np.zeros((count, 3), dtype=np.float64), np.zeros(count, dtype=bool)
    return _blend_family_colors(masks)


def window_anchor_primes(primes, n, enabled_ids, theta=0.5, mode="stepped", anchor_overrides=None):
    """Ports #renderFrame's anchor-collection loop:

        const anchors = [];
        for (const family of this.#windowHighlightFamilies) {
          if (!family.isOn()) continue;
          const a = family.anchorAt(this.#n);
          if (a !== null && !anchors.includes(a)) anchors.push(a);
        }
        this.#trackedPrimes = anchors;

    i.e. the deduplicated, order-preserving list of every ENABLED family's own
    anchor prime at n, in WINDOW_FAMILY_COLORS' own registry order (bertrand,
    legendre, generalLaw -- a plain dict preserves insertion order, same as
    the JS's #windowHighlightFamilies array order). This is what the JS
    unconditionally overwrites #trackedPrimes with whenever ANY window family
    is on (see that method's own doc-comment) -- ring_geometry.py had
    bertrand_anchor_at/legendre_anchor_at/general_law_anchor_at and
    compute_tracked_colors (the per-ring OUTLINE COLOR once a ring is already
    tracked) since Phase 1, but computing WHICH rings should be tracked in
    the first place -- when a window family, rather than a manual
    --track-primes list or auto-orbit, is what's naming the anchor -- needed
    this separate collection step: Bertrand/Legendre/General Law's own
    highlight color rendered fine, but their own anchor ring never got the
    gray/colored OUTLINE CIRCLE tracked rings and auto-orbit's current ring
    both get, because nothing ever added that anchor to the tracked set.
    See renderer.py's rebuild_buffer for the
    caller that wires this into effective_track_primes with the correct
    precedence (window anchors, when any family is on, take over from BOTH
    auto-orbit and a launch-time --track-primes list -- exactly like the JS's
    own `if (anyWindowOn) {...}` block runs unconditionally ahead of, and
    instead of, #advanceAutoOrbit).

    Returns [] if enabled_ids is empty -- caller falls back to whatever OTHER
    trackedPrimes source applies, mirroring the JS's own `if (anyWindowOn)`
    gate (no families on: this function contributes nothing, same as the JS
    block simply not running that turn).

    `anchor_overrides` -- same {family_id: anchor} dict
    compute_tracked_colors accepts (see that function's own doc-comment) --
    a family_id present here (even with value None) uses that value
    directly instead of calling ANCHOR_FUNCTIONS[family_id], so renderer.py
    can feed cyclic_window_anchor_at's stateful "legendre"/"generalLaw"
    anchors through the exact same collection loop Bertrand still resolves
    through ANCHOR_FUNCTIONS."""
    if not enabled_ids:
        return []
    primes_arr = to_prime_array(primes)
    anchors = []
    for family_id in WINDOW_FAMILY_COLORS:
        if family_id not in enabled_ids:
            continue
        if anchor_overrides is not None and family_id in anchor_overrides:
            anchor = anchor_overrides[family_id]
        else:
            anchor = ANCHOR_FUNCTIONS[family_id](primes_arr, n, theta, mode)
        if anchor is not None and anchor not in anchors:
            anchors.append(anchor)
    return anchors


def active_window_count(enabled_ids):
    """Ports #activeWindowCount: trivial here since `enabled_ids` already IS
    the set of currently-on families (the JS version derives this by
    checking each family's isOn() closure; this module's callers pass the
    already-resolved set directly), kept as a named function purely so a
    caller mirrors the JS call site 1:1 rather than inlining `len(...)`."""
    return len(enabled_ids)


# ---------------------------------------------------------------------------
# Resonance -- ports SieveModel.resonanceEventsInRange, the bulk "goto catch-up"
# resonance-flash finder used by StructuralSieveApp's resonance log (a goto must not
# skip resonance events strictly before the jumped-to n; see SieveModel.js for the
# algorithm). A marking pass, not O(range * primes) trial division; numpy is used for
# the per-prime multiple marking (see resonance_events_in_range for the vectorization).
# ---------------------------------------------------------------------------

#: Hard ceiling on resonance_events_in_range's O(to_n-from_n) marking-pass array --
#: 20M int64 entries is ~160MB. Beyond this a dense per-n marking pass is not viable
#: regardless of memory (see that function's docstring).
_RESONANCE_SCAN_MAX_SIZE = 20_000_000

#: resonance_events_in_range's marking pass: primes with more multiples than this
#: in the span get their own numpy slice add; the rest are counted together via
#: np.bincount (one numpy call per chunk instead of one per prime).
_RESONANCE_SCAN_DENSE_MULTIPLES = 64

#: Upper bound on how many flat multiple-indices one np.bincount chunk expands
#: (~32 MB per int64 temporary), keeping peak memory near the factor_count array.
_RESONANCE_SCAN_CHUNK = 4_000_000


def resonance_events_in_range(primes, from_n, to_n):
    """Every "resonance" step n in [from_n, to_n] (inclusive): n is a
    resonance step when every prime whose leading primorial product still
    fits under n also divides n (getStepState's own doc-comment has the
    full definition; this is the BULK finder for a whole span at once, not
    a per-n test).

    Returns a list of {"n": int, "factors": [int, ...]} dicts in ascending n
    order, factors listing every dividing prime for that n (same shape as
    the JS version's plain objects).

    The marking pass is O(to_n - from_n) by design. tick_next_n's `range_step` can
    make a single range-mode tick's gap ~10**21 once storage-floor primes are loaded,
    which no dense array can hold. TWO guards below, cheapest first:
      1. A resonance step needs `primorial(smallest active prime) <= to_n` (see
         `thresholds` below) -- if even the SMALLEST active prime's threshold exceeds
         to_n, no resonance is possible anywhere in the span, so this returns without
         allocating anything. A high-floor range (active primes ~10**25, to_n ~10**21)
         hits this on every tick at O(1) cost.
      2. A hard cap on `size` itself, for any other combination that still
         slips past guard 1 (e.g. small-enough primes but an enormous gap
         some other way) -- past this, resonance events genuinely cannot be
         found by this approach at all; returning [] (same contract as the
         to_n<from_n case above) is the correct result, since a marking pass over a
         span this size cannot finish regardless of memory."""
    if to_n < from_n:
        return []
    primes_arr = to_prime_array(primes)
    if len(primes_arr) == 0 or int(primes_arr[0]) > to_n:
        return []
    size = to_n - from_n + 1
    if size > _RESONANCE_SCAN_MAX_SIZE:
        return []

    # Everything below is vectorized: the old per-n Python loop over the whole
    # span (plus one numpy slice call per active prime) took 4.4 s at N=20M,
    # all of it inside the ring-viz GLFW loop on every scrub jump (known bug:
    # Esc/window-close could not be processed until it finished).
    if primes_arr.dtype == object:
        candidates = np.array([int(p) for p in primes_arr if int(p) <= to_n], dtype=np.int64)
    else:
        candidates = primes_arr[primes_arr <= to_n].astype(np.int64)
    first = np.maximum(candidates, from_n)
    first += (-first) % candidates  # round up to the next multiple of p
    in_span = first <= to_n
    candidates, first = candidates[in_span], first[in_span]
    multiples = (to_n - first) // candidates + 1

    # Marking pass: factor_count[i] = number of active primes dividing
    # from_n + i. Primes with many multiples in the span get a slice add each;
    # the (typically far more numerous) primes with only a few multiples are
    # expanded into flat index arrays and counted with np.bincount, in chunks
    # of at most _RESONANCE_SCAN_CHUNK indices to bound peak memory.
    factor_count = np.zeros(size, dtype=np.int64)
    dense = multiples > _RESONANCE_SCAN_DENSE_MULTIPLES
    for p, m in zip(candidates[dense].tolist(), first[dense].tolist()):
        factor_count[m - from_n::p] += 1
    sparse_p, sparse_first, sparse_count = candidates[~dense], first[~dense], multiples[~dense]
    i = 0
    while i < len(sparse_p):
        running = np.cumsum(sparse_count[i:])
        j = i + max(1, int(np.searchsorted(running, _RESONANCE_SCAN_CHUNK, side="right")))
        counts = sparse_count[i:j]
        k = np.arange(int(counts.sum()), dtype=np.int64) - np.repeat(np.cumsum(counts) - counts, counts)
        offsets = np.repeat(sparse_first[i:j] - from_n, counts) + k * np.repeat(sparse_p[i:j], counts)
        factor_count += np.bincount(offsets, minlength=size)
        i = j

    # maxResonance(n) only changes at the handful of n where the running
    # primorial crosses n (Python ints here, not int64, so this stays exact
    # well past where a naive int64 accumulator would silently overflow --
    # a correctness improvement over the JS version's plain float64 numbers,
    # though not one expected to matter at the N scale this module targets).
    # Each crossing bumps max_resonance for the rest of the span.
    max_resonance = np.zeros(size, dtype=np.int8)
    primorial = 1
    for p in primes_arr:
        primorial *= int(p)
        if primorial > to_n:
            break
        max_resonance[max(primorial - from_n, 0):] += 1

    hits = np.nonzero((max_resonance > 0) & (factor_count >= max_resonance))[0]
    events = []
    for offset in hits.tolist():
        n = from_n + offset
        count = int(factor_count[offset])
        factors = []
        for p in primes_arr:
            p_int = int(p)
            if p_int > n or len(factors) >= count:
                break
            if n % p_int == 0:
                factors.append(p_int)
        events.append({"n": n, "factors": factors})
    return events


# ---------------------------------------------------------------------------
# Resonance log + surviving-primes panel text -- ports
# StructuralSieveApp.js's #resonanceLog formatting and #renderLogPanel's
# text-truncation rules to plain strings for renderer.py's console-pane
# prints (NOT the on-canvas HUD/HUD_STATE path -- this is a console-pane
# port, same precedent as the plain print() HUD lines Phase 4/7B already
# emit). No new math: resonance_log_lines is a
# thin formatter over resonance_events_in_range above; format_log_panel_text
# is generic and used for both the resonance-log lines and the raw
# surviving-primes list.
# ---------------------------------------------------------------------------

LOG_PANEL_TRUNCATE_THRESHOLD = 50  # mirrors JS's own LOG_PANEL_TRUNCATE_THRESHOLD


def resonance_log_lines(primes, from_n, to_n):
    """Ports #resonanceLog's own entry format exactly (`${e.n} = ${e.factors
    .join(" × ")}`) -- turns resonance_events_in_range's structured events
    for [from_n, to_n] into the same human-readable strings the HTML
    reference's Resonances panel shows, one per resonance step, ascending n
    order (resonance_events_in_range's own order, unchanged)."""
    events = resonance_events_in_range(primes, from_n, to_n)
    return [f"{e['n']} = {' × '.join(str(f) for f in e['factors'])}" for e in events]


def format_log_panel_text(items, threshold=LOG_PANEL_TRUNCATE_THRESHOLD):
    """Ports StructuralSieveApp.js's #renderLogPanel text-formatting rules
    (see that method's own doc-comment for the full rationale) for a plain
    console-pane line rather than a DOM panel with a live collapse/expand
    toggle: the console pane is a scrolling text stream, not an interactive
    widget, so there is nothing to click here -- this always renders the
    COLLAPSED view once a list exceeds `threshold` items (JS's own default
    state for a freshly rendered long panel), which is strictly more useful
    for a scrollback than dumping a potentially huge comma-separated line.

    Returns a (count, text) tuple: `count` is len(items) (for the caller's
    own "(count)" header, matching JS's `els.count.textContent`); `text` is
    "-" for an empty list, the full ", "-joined list at or below
    `threshold` items, or the first `threshold` items joined by ", "
    followed by " (+K more)" above it -- K is the omitted remainder,
    mirroring JS's own "+N more" wording (ss-log-panel-truncated)."""
    count = len(items)
    if count == 0:
        return count, "-"
    if count <= threshold:
        return count, ", ".join(str(x) for x in items)
    shown = items[:threshold]
    remaining = count - threshold
    return count, ", ".join(str(x) for x in shown) + f" (+{remaining} more)"


# ---------------------------------------------------------------------------
# Tracked primes -- foundation shared by Phase 7 (LCM/resonance HUD) and
# Phase 8 (tracked-ring outline circles/flash overlays).
# Ports the filtering half of StructuralSieveApp.js's #trackedResonanceState
# (see that method's own doc-comment): "which of the primes the user asked
# to track are actually active (born) yet at the current N". Deliberately
# does NOT port the LCM/phase/to-resonance computation itself -- that's
# Phase 7's own scope, kept separate so this foundation stays a pure,
# single-purpose filter usable by both later phases without either one
# depending on the other's math.
# ---------------------------------------------------------------------------

def filter_active_tracked(tracked, active_primes):
    """Which of `tracked` (an iterable of prime values, in whatever order the
    user entered them) are present in `active_primes` (the ring array's
    current active/born set at this N).

    Mirrors `#trackedResonanceState`'s own `tracked.filter((p) =>
    activePrimes.includes(p))` line exactly: preserves `tracked`'s original
    order (NOT sorted, NOT deduplicated beyond whatever duplicates the user
    typed) rather than active_primes's order, since the tracked list is a
    small, user-authored sequence where the order the user typed them in is
    itself meaningful (e.g. for a future Track-P text field round-trip).

    Returns a plain list of ints -- deliberately not a numpy array, since
    the tracked list is always small (user-typed or capped, see Phase 7's
    own max_tracked) and every caller (HUD text formatting, LCM product)
    wants plain Python ints, not numpy scalars.
    """
    active_set = {int(p) for p in active_primes}
    return [int(p) for p in tracked if int(p) in active_set]


def tracked_ring_mask(primes, tracked):
    """Boolean mask into `primes` (an active ring array, same array
    ring_positions()/build_vertex_data() were called with) marking every
    ring whose OWN prime literally appears in `tracked`.

    Ports DrumRenderer's own per-ring `ring.tracked = trackedSet.has(r.prime)`
    (see StructuralSieveApp.js's per-frame ring-state construction) -- plain
    list membership, a DIFFERENT and narrower question from
    filter_active_tracked above: that function answers "which tracked VALUES
    are active" (used for the LCM/resonance HUD block, order-preserving,
    plain list); this one answers "which RING INDICES are tracked" so a
    caller can index a position/radius/color array (e.g.
    ring_geometry.ring_positions()'s own "radius" array) directly to draw
    something at each tracked ring's location (the tracked-ring outline
    circles in ring_draw.build_tracked_outline_draws).

    Returns an all-False bool array (length len(primes)) when `tracked` is
    empty, matching np.isin's own behavior against an empty second operand
    -- no special-casing needed, but spelled out here since an empty
    `tracked` is the common "nothing tracked yet" case."""
    primes_arr = to_prime_array(primes)
    if len(primes_arr) == 0 or not tracked:
        return np.zeros(len(primes_arr), dtype=bool)
    tracked_arr = to_prime_array(sorted(tracked))
    return np.isin(primes_arr, tracked_arr)


# ---------------------------------------------------------------------------
# Tracked-primes LCM/resonance -- pure port of
# StructuralSieveApp.js's #trackedResonanceState / SieveModel.js's
# lcmOfListBig / #formatBig. The JS's bitmask/lookup-table idea does NOT apply
# here (its cap defaults to 500 tracked primes, while a lookup table is only
# tractable in the teens/twenties) -- this is a straight product-based LCM port.
#
# Python has no Number/BigInt split -- `int` is already arbitrary-precision
# -- so unlike the JS (which keeps lcmOfList/lcmOfListBig as two separate
# implementations for a plain-Number fast path vs. an exact BigInt path)
# there is only one lcm_of_list here, and it is exact by construction.
# ---------------------------------------------------------------------------

def lcm_of_list(values):
    """LCM of a list of positive ints, or 0 for an empty list -- mirrors
    SieveModel.js's lcmOfList/lcmOfListBig (both return 0/0n for an empty
    list, not 1, so callers can use `lcm <= 0` as the same "nothing to
    show" signal the JS uses)."""
    values = [int(v) for v in values]
    if not values:
        return 0
    return math.lcm(*values)


def tracked_resonance_state(tracked, active_primes, n, auto_orbit=False,
                             max_tracked_for_exact_lcm=500):
    """Port of StructuralSieveApp.js's #trackedResonanceState -- the single
    computation behind both the HUD's tracked/LCM/phase/to-resonance lines
    and (in the JS) the live chime trigger.

    Returns None under the same conditions the JS returns null: auto_orbit
    is on, `tracked` is empty, or none of `tracked` is active yet at this N
    (via filter_active_tracked above -- same filtering, not reimplemented).
    Returns `{"too_large": True, "tracked": [...], "limit": ...}` when the
    tracked-and-active count exceeds max_tracked_for_exact_lcm (mirrors the
    JS's own device-calibrated cap, passed in here rather than calibrated,
    since there is no equivalent "how fast is this specific machine" probe
    on this side yet -- callers pick a value, see renderer.py's own default).
    Otherwise returns `{"tracked": [...], "lcm": int, "phase": int,
    "to_resonance": int}` -- plain Python ints throughout, no BigInt/Number
    distinction needed (see lcm_of_list's own doc-comment)."""
    if auto_orbit or not tracked:
        return None
    tracked_active = filter_active_tracked(tracked, active_primes)
    if not tracked_active:
        return None
    if len(tracked_active) > max_tracked_for_exact_lcm:
        return {"too_large": True, "tracked": tracked_active, "limit": max_tracked_for_exact_lcm}
    lcm = lcm_of_list(tracked_active)
    if lcm <= 0:
        return None
    n_int = int(n)
    phase = n_int % lcm
    to_resonance = 0 if phase == 0 else lcm - phase
    return {"tracked": tracked_active, "lcm": lcm, "phase": phase, "to_resonance": to_resonance}
