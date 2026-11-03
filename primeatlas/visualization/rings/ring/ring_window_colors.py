"""
ring_window_colors.py -- per-ring highlight and tracked colors for every active
ring at once, blended from the enabled window families (ring_windows.py) and
their anchors (ring_window_anchors.py). Pure numpy, no rendering, no I/O, no
tkinter.
"""

import numpy as np

from primeatlas.visualization.shared.bigint import to_prime_array
from primeatlas.visualization.rings.ring.ring_window_anchors import ANCHOR_FUNCTIONS
from primeatlas.visualization.rings.ring.ring_windows import (
    STRICT_MEMBER_FUNCTIONS, WINDOW_FAMILY_COLORS, WINDOW_MEMBER_FUNCTIONS)


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
# ring_positions() in ring_geometry.py.
# ---------------------------------------------------------------------------


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


def active_window_count(enabled_ids):
    """Ports #activeWindowCount: trivial here since `enabled_ids` already IS
    the set of currently-on families (the JS version derives this by
    checking each family's isOn() closure; this module's callers pass the
    already-resolved set directly), kept as a named function purely so a
    caller mirrors the JS call site 1:1 rather than inlining `len(...)`."""
    return len(enabled_ids)
