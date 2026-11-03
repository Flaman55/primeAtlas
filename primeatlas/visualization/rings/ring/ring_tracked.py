"""
ring_tracked.py -- the user's tracked primes: which are active at the current n,
the per-ring tracked mask, and their LCM / resonance state for the HUD. Pure
numpy and exact ints, no rendering, no I/O, no tkinter.
"""

import math

import numpy as np

from primeatlas.visualization.shared.bigint import to_prime_array


# ---------------------------------------------------------------------------
# Tracked primes -- shared by the LCM/resonance HUD (tracked_resonance_state)
# and the tracked-ring outline circles/flash overlays (tracked_ring_mask).
# filter_active_tracked ports the filtering half of StructuralSieveApp.js's
# #trackedResonanceState (see that method's own doc-comment): "which of the
# primes the user asked to track are actually active (born) yet at the
# current N". The LCM/phase/to-resonance computation lives in
# tracked_resonance_state, so the filter stays a pure, single-purpose
# function usable by both consumers.
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
    the tracked list is always small (user-typed or capped, see
    tracked_resonance_state's max_tracked_for_exact_lcm) and every caller (HUD text formatting, LCM product)
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
