"""
ring_windows.py -- the three window laws of the ring visualization (Bertrand,
Legendre, General Law): numeric bounds, per-ring membership, the fade-continuity
highlight layer, the per-family registries, and the HUD label / nested-shell colors.
Pure numpy ports of Structural Sieve's SieveModel.js / StructuralSieveApp.js; no
rendering, no I/O, no tkinter. Ported formulas:

  - Bertrand window: primeValue in (floor(n/2), n]              (isBertrandWindowMember)
  - Legendre level k: floor(sqrt(n-1)) for n>=2, else 0          (legendreLevelAt)
  - Legendre window: primeValue in (k*k, n]                      (isLegendreWindowMember)
  - General Law tent factor: piecewise-linear, 0 at theta=0.1,
    1 at theta=0.5, 0 at theta=1                                 (#generalLawTentFactor)
  - General Law window (stepped mode): lo = n - (n - k*k)*factor,
    clamped to lo < n; (sliding mode): lo = max(0, n - n**theta)
    (generalLawWindowBounds)
"""

import math

import numpy as np


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
