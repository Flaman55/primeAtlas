"""
ring_window_anchors.py -- each window family's anchor prime (the ring its
tracked-ring outline sits on): the per-step anchors ported from SieveModel.js,
the cyclic Legendre/General Law anchor, and the per-frame anchor list. Pure
numpy, no rendering, no I/O, no tkinter.
"""

import numpy as np

from primeatlas.visualization.shared.bigint import to_prime_array
from primeatlas.visualization.rings.ring.ring_windows import (
    WINDOW_FAMILY_COLORS, general_law_tent_factor, general_law_window_bounds, legendre_level_at)


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
    is on (see that method's own doc-comment). The per-family anchor functions
    above and compute_tracked_colors (ring_window_colors.py) give a tracked
    ring's OUTLINE COLOR; this collection step decides WHICH rings are tracked
    when a window family, rather than a manual --track-primes list or
    auto-orbit, names the anchor -- without it a family's anchor ring would get
    its highlight color but not the gray/colored OUTLINE CIRCLE tracked rings
    and auto-orbit's current ring get.
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
