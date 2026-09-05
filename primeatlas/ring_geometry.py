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

import math

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


# ---------------------------------------------------------------------------
# Highlight-color blending -- [ADDED Faza 1, PLAN.md] ports
# StructuralSieveApp.js's #windowHighlightFamilies / #computeHighlightColor /
# #computeTrackedColor / #activeWindowCount into vectorized numpy form. See
# that file for the full design rationale (Artur's own quotes on why the
# blend is additive-RGB and why Legendre's own highlight test is "sticky").
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


def _legendre_level_at_vec(values):
    """Vectorized counterpart of legendre_level_at, applied elementwise to a
    numpy array (needed because isLegendreHighlighted applies legendreLevelAt
    to the RING's own prime value, not to n -- see that JS method's own
    doc-comment). Same floor(sqrt(v-1)) formula, v<=1 -> 0."""
    values_arr = np.asarray(values, dtype=np.float64)
    result = np.zeros_like(values_arr, dtype=np.int64)
    mask = values_arr > 1
    result[mask] = np.floor(np.sqrt(values_arr[mask] - 1)).astype(np.int64)
    return result


def is_legendre_highlighted(primes, n):
    """Vectorized port of isLegendreHighlighted -- the STICKY variant used
    for the ring's own highlight color (not the strict membership test): a
    ring stays green after its own Legendre window closes until it crosses
    its next self-multiple. Superset of is_legendre_member (every strict
    match is also sticky) -- see that JS method's own doc-comment for why
    this matters to the strict/sticky blend tiering below."""
    primes_arr = np.asarray(primes, dtype=np.int64)
    strict = is_legendre_member(primes_arr, n)
    k = _legendre_level_at_vec(primes_arr)
    close_edge = (k + 1) * (k + 1)
    next_crossing = (close_edge // primes_arr + 1) * primes_arr
    return strict | (n < next_crossing)


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
    primes_arr = np.asarray(primes, dtype=np.int64)
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
    primes_arr = np.asarray(primes, dtype=np.int64)
    if len(primes_arr) == 0:
        return None
    k = legendre_level_at(n)
    return _largest_below(primes_arr, k * k)


def general_law_anchor_at(primes, n, theta, mode):
    """Ports SieveModel.generalLawAnchorAt: largest active prime at or below
    the window's own current opening edge `lo` (computed as "strictly below
    floor(lo)+1", equivalent for integer primes -- see the JS method's own
    doc-comment)."""
    primes_arr = np.asarray(primes, dtype=np.int64)
    if len(primes_arr) == 0:
        return None
    lo, _hi, _k, _factor = general_law_window_bounds(n, theta, mode)
    return _largest_below(primes_arr, int(np.floor(lo)) + 1)


ANCHOR_FUNCTIONS = {
    "bertrand": lambda primes, n, theta, mode: bertrand_anchor_at(primes, n),
    "legendre": lambda primes, n, theta, mode: legendre_anchor_at(primes, n),
    "generalLaw": lambda primes, n, theta, mode: general_law_anchor_at(primes, n, theta, mode),
}


def _blend_family_colors(masks_by_family):
    """Shared additive-RGB blend core used by both compute_highlight_colors
    and compute_tracked_colors below -- ports the summation half of
    #computeHighlightColor / #computeTrackedColor (channel sum, clamp to
    255), factored out because both JS methods do exactly this arithmetic
    and differ only in HOW each family's per-ring participation mask is
    derived (strict/sticky tiering for highlight color; plain anchor-equality
    for tracked color -- see the two callers below).

    `masks_by_family` -- dict of family_id -> boolean numpy array (same
    length, one entry per ring): True where that family contributes its
    color to that ring.

    Returns (colors, matched) -- colors is an (N, 3) float64 array (channel
    values already clamped to [0, 255], NOT yet cast to uint8 so a caller can
    still do further math before quantizing for a GPU buffer -- see
    build_vertex_data's own float32 buffer for why this module leaves that
    choice to the renderer), matched is an (N,) boolean array, True where at
    least one family contributed (the null/None case in the JS version)."""
    if not masks_by_family:
        n = 0
    else:
        n = len(next(iter(masks_by_family.values())))
    colors = np.zeros((n, 3), dtype=np.float64)
    matched = np.zeros(n, dtype=bool)
    for family_id, mask in masks_by_family.items():
        color = np.asarray(WINDOW_FAMILY_COLORS[family_id], dtype=np.float64)
        colors[mask] += color
        matched |= mask
    np.clip(colors, 0, 255, out=colors)
    return colors, matched


def compute_highlight_colors(primes, n, enabled_ids, theta=0.5, mode="stepped"):
    """Vectorized port of #computeHighlightColor for every ring in `primes`
    at once. `enabled_ids` is an iterable of family ids from
    WINDOW_FAMILY_COLORS currently toggled on (e.g. {"bertrand", "legendre"}).

    Implements the exact two-tier strict/sticky precedence rule from the JS
    version (see #computeHighlightColor's own doc-comment for the full
    rationale and the motivating bug it fixes): PER RING, if any enabled
    family's STRICT membership test matches, only strictly-matching families
    blend for that ring; a family that merely `isHighlighted` (sticky) but
    does not strictly match is excluded from that ring's blend in that case.
    Only when NO family strictly matches a given ring does the sticky-only
    fallback apply. Bertrand and General Law have no separate sticky
    variant (their strict and highlighted tests are identical); only
    Legendre does (is_legendre_highlighted vs is_legendre_member).

    Returns (colors, matched) -- see _blend_family_colors's own docstring for
    the exact shape; `matched[i] is False` is this function's counterpart to
    the JS version returning null for ring i."""
    primes_arr = np.asarray(primes, dtype=np.int64)
    count = len(primes_arr)

    strict_by_family = {}
    highlighted_by_family = {}
    for family_id in enabled_ids:
        if family_id == "bertrand":
            strict = is_bertrand_member(primes_arr, n)
            highlighted = strict
        elif family_id == "legendre":
            strict = is_legendre_member(primes_arr, n)
            highlighted = is_legendre_highlighted(primes_arr, n)
        elif family_id == "generalLaw":
            strict = is_general_law_member(primes_arr, n, theta, mode)
            highlighted = strict
        else:
            raise ValueError(f"unknown window family id {family_id!r}")
        strict_by_family[family_id] = strict
        highlighted_by_family[family_id] = highlighted

    if not strict_by_family:
        return np.zeros((count, 3), dtype=np.float64), np.zeros(count, dtype=bool)

    any_strict = np.zeros(count, dtype=bool)
    for strict in strict_by_family.values():
        any_strict |= strict

    # Per ring: if any_strict, only THIS family's own strict flag decides its
    # contribution (even if it is also sticky-highlighted); otherwise THIS
    # family's own highlighted flag decides -- exactly the
    # `matches = strictMatches.length > 0 ? strictMatches : stickyMatches`
    # rule from #computeHighlightColor, applied per family per ring via
    # np.where instead of per-ring family-list branching.
    effective_masks = {
        family_id: np.where(any_strict, strict_by_family[family_id], highlighted_by_family[family_id])
        for family_id in enabled_ids
    }
    return _blend_family_colors(effective_masks)


def compute_tracked_colors(primes, n, enabled_ids, theta=0.5, mode="stepped"):
    """Vectorized port of #computeTrackedColor: for each ring, sums the
    colors of every enabled family whose OWN anchor (bertrand_anchor_at /
    legendre_anchor_at / general_law_anchor_at) is exactly that ring's prime.
    Deliberately a DIFFERENT question from compute_highlight_colors (window
    membership) -- see that JS method's own doc-comment for the exact bug
    this distinction fixes (two different anchors collapsing to the same
    blended color because both happened to satisfy each other's window-
    membership test).

    Returns (colors, matched) -- same shape as compute_highlight_colors."""
    primes_arr = np.asarray(primes, dtype=np.int64)
    count = len(primes_arr)

    masks = {}
    for family_id in enabled_ids:
        anchor = ANCHOR_FUNCTIONS[family_id](primes_arr, n, theta, mode)
        masks[family_id] = (primes_arr == anchor) if anchor is not None else np.zeros(count, dtype=bool)

    if not masks:
        return np.zeros((count, 3), dtype=np.float64), np.zeros(count, dtype=bool)
    return _blend_family_colors(masks)


def active_window_count(enabled_ids):
    """Ports #activeWindowCount: trivial here since `enabled_ids` already IS
    the set of currently-on families (the JS version derives this by
    checking each family's isOn() closure; this module's callers pass the
    already-resolved set directly), kept as a named function purely so a
    caller mirrors the JS call site 1:1 rather than inlining `len(...)`."""
    return len(enabled_ids)


# ---------------------------------------------------------------------------
# Resonance -- [ADDED Faza 1, PLAN.md] ports SieveModel.resonanceEventsInRange,
# the bulk "goto catch-up" resonance-flash finder used by
# StructuralSieveApp's resonance log. See that JS method's own extensive
# doc-comment (SieveModel.js) for the full algorithm rationale and the
# long-standing toy bug it fixes (goto silently skipping every resonance
# event strictly before the jumped-to n). Ported here as a near-literal
# translation rather than further-vectorized, because the JS algorithm is
# itself already the efficient form (a marking pass, not O(range * primes)
# trial division) -- the one place numpy helps is the per-prime multiple
# marking (a slice increment instead of a per-multiple Python loop).
# ---------------------------------------------------------------------------

def resonance_events_in_range(primes, from_n, to_n):
    """Every "resonance" step n in [from_n, to_n] (inclusive): n is a
    resonance step when every prime whose leading primorial product still
    fits under n also divides n (getStepState's own doc-comment has the
    full definition; this is the BULK finder for a whole span at once, not
    a per-n test).

    Returns a list of {"n": int, "factors": [int, ...]} dicts in ascending n
    order, factors listing every dividing prime for that n (same shape as
    the JS version's plain objects).
    """
    if to_n < from_n:
        return []
    primes_arr = np.asarray(primes, dtype=np.int64)
    size = to_n - from_n + 1
    factor_count = np.zeros(size, dtype=np.int64)

    # Marking pass: for each active prime p, bump every multiple of p inside
    # [from_n, to_n] by 1 (a numpy slice add instead of the JS version's own
    # per-multiple loop -- same O((to_n-from_n) log log to_n) shape overall).
    for p in primes_arr:
        p_int = int(p)
        if p_int > to_n:
            break
        m = max(from_n, p_int)
        m += (p_int - (m % p_int)) % p_int  # round m up to the next multiple of p
        if m > to_n:
            continue
        start = m - from_n
        factor_count[start::p_int] += 1

    # maxResonance(n) only changes at the handful of n where the running
    # primorial crosses n (Python ints here, not int64, so this stays exact
    # well past where a naive int64 accumulator would silently overflow --
    # a correctness improvement over the JS version's plain float64 numbers,
    # though not one expected to matter at the N scale this module targets).
    thresholds = []
    primorial = 1
    for p in primes_arr:
        primorial *= int(p)
        if primorial > to_n:
            break
        thresholds.append(primorial)

    events = []
    threshold_idx = 0
    for offset in range(size):
        n = from_n + offset
        while threshold_idx < len(thresholds) and thresholds[threshold_idx] <= n:
            threshold_idx += 1
        max_resonance = threshold_idx
        count = int(factor_count[offset])
        if max_resonance > 0 and count >= max_resonance:
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
# Tracked primes -- [ADDED Faza 6, PLAN.md] foundation shared by Faza 7 (LCM/
# resonance HUD) and Faza 8 (tracked-ring outline circles/flash overlays).
# Ports the filtering half of StructuralSieveApp.js's #trackedResonanceState
# (see that method's own doc-comment): "which of the primes the user asked
# to track are actually active (born) yet at the current N". Deliberately
# does NOT port the LCM/phase/to-resonance computation itself -- that's
# Faza 7's own scope, kept separate so this foundation stays a pure,
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
    small, user-authored sequence where "the order Artur typed them in" is
    itself meaningful (e.g. for a future Track-P text field round-trip).

    Returns a plain list of ints -- deliberately not a numpy array, since
    the tracked list is always small (user-typed or capped, see Faza 7's
    own max_tracked) and every caller (HUD text formatting, LCM product)
    wants plain Python ints, not numpy scalars.
    """
    active_set = {int(p) for p in active_primes}
    return [int(p) for p in tracked if int(p) in active_set]


# ---------------------------------------------------------------------------
# Tracked-primes LCM/resonance -- [ADDED Faza 7A, PLAN.md] pure port of
# StructuralSieveApp.js's #trackedResonanceState / SieveModel.js's
# lcmOfListBig / #formatBig. See PLAN.md's own design note: the JS's
# bitmask/lookup-table idea does NOT apply here (its own cap defaults to
# 500 tracked primes, only tractable in the teens/twenties for a real
# lookup table) -- this is a straight product-based LCM port instead.
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


def format_big(value, digit_threshold=15):
    """Port of StructuralSieveApp.js's #formatBig: below digit_threshold
    digits (JS default 15, ~Number.MAX_SAFE_INTEGER's own digit count),
    the plain digit string; past it, "mantissa×10^exponent (N digits)"
    since NWW/Faza/Do-rezonancy can genuinely reach hundreds or thousands
    of digits once dozens of pairwise-coprime primes are multiplied
    together, and printing all of them would be noise, not information.
    English-only wording (unlike the JS's #t()-localized string) since
    this is a console/HUD diagnostic string on the Python side, not
    user-facing app chrome with its own PL/EN locale files."""
    value = int(value)
    negative = value < 0
    s = str(-value if negative else value)
    if len(s) <= digit_threshold:
        return ("-" if negative else "") + s
    mantissa = f"{s[0]}.{s[1:5]}"
    exponent = len(s) - 1
    return ("-" if negative else "") + f"{mantissa}×10^{exponent} ({len(s)} digits)"
