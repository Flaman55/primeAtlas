"""
ring_draw.py -- pure, GL-context-free vertex data for the rings mode: per-ring
position/color vertices (window-family highlights, tracked primes, resonance),
tracked-ring outline draws, and the ring-mode flash colors.

Self-contained sys.path bootstrap (mirrors renderer.py's own -- see that
file's module docstring for the full "why plain-script-path" explanation):
needed so the primeatlas.* imports below work whether this module is imported
after renderer.py has already run its own bootstrap, or on its own (e.g.
directly from a test).
"""

import os
import sys

import numpy as np

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_PRIME_SIEVE_DIR = os.path.join(_REPO_ROOT, "prime_sieve")
if _PRIME_SIEVE_DIR not in sys.path:
    sys.path.insert(0, _PRIME_SIEVE_DIR)

from primeatlas.visualization.rings.ring.ring_geometry import (
    ring_positions, compute_highlight_colors, compute_tracked_colors, tracked_ring_mask,
)
from primeatlas.visualization.shared.bigint import to_prime_array


_CYAN_RGB = (0.0, 188.0, 212.0)      # "#00bcd4"
_GOLD_RGB = (255.0, 215.0, 0.0)      # "#ffd700" -- hit, prime >= 11
_ORANGE_RGB = (255.0, 87.0, 34.0)    # "#ff5722" -- hit, prime < 11
_TRACKED_WHITE_RGB = (255.0, 255.0, 255.0)


def build_vertex_data(primes, n, max_radius, enabled_ids=(), theta=0.5, mode="stepped", track_primes=(),
                       resonance_track_primes=()):
    """ring_geometry.ring_positions() -> flat (x,y,r,g,b) float32 array ready
    for a moderngl buffer.

    Colors are layered in priority order: base cyan, then hit rings recolor
    to gold/orange, then a matched window-highlight color (via
    ring_geometry.compute_highlight_colors -- Bertrand pink / Legendre green
    / General Law violet additive blend) OVERRIDES whatever came before, hit
    or not. `enabled_ids` empty reproduces the plain cyan/gold-only behavior
    since compute_highlight_colors returns matched=all-False for an empty
    family set.

    `track_primes` -- the SAME effective-tracked-ring set
    rebuild_buffer feeds build_tracked_outline_draws (rings.py's
    resolve_effective_track_primes: whichever rings are the currently
    active anchors, from a window family, auto-orbit, or a manual --track-
    primes list) -- gets its own DOT forced to plain white, ONE more link
    in the same override chain, applied AFTER (so it wins over) the window-
    highlight color above. The tracked-ring OUTLINE circle
    (build_tracked_outline_draws) already carries the active window's own
    color (green for Legendre, violet for General Law, additively blended
    when both happen to coincide) -- deliberately UNCHANGED by this -- but
    the ring's actual POINT would otherwise just blend into every other
    same-colored member of that window; a plain white dot makes the one
    ring actually being tracked/anchored instantly identifiable at a
    glance, regardless of whatever window color its surroundings carry.
    Empty (the default) reproduces the exact prior behavior --
    tracked_ring_mask (ring_geometry.py) already returns all-False for an
    empty `track_primes`, so this is a no-op then, same convention as
    `enabled_ids=()` above.

    `resonance_track_primes` -- the caller's
    ring_geometry.tracked_resonance_state()["tracked"] list, but ONLY when
    that state's own `to_resonance == 0` (this exact N IS the tracked set's
    LCM/resonance step -- every one of them is hit here, all sitting on the
    same vertical line), empty otherwise. Gets its dot forced to the same
    orange flash_overlay_rgba already uses for the full-screen resonance
    flash (_FLASH_RESONANCE_RGB), applied LAST (so it wins over even the
    plain white tracked dot above) -- the resonance flash already washes
    the whole screen orange for a few frames, but the flash decays fast and
    the tracked dots themselves would otherwise stay plain white through
    it, making it easy to miss exactly which rings just resonated. Empty
    (the default) is a no-op, same convention as `track_primes=()` above."""
    pos = ring_positions(primes, n, max_radius)
    count = len(pos["x"])
    hit = pos["is_hit"]

    rgb = np.empty((count, 3), dtype=np.float64)
    rgb[:] = _CYAN_RGB
    primes_arr = to_prime_array(primes)
    hit_gold = hit & (primes_arr >= 11)
    hit_orange = hit & (primes_arr < 11)
    rgb[hit_gold] = _GOLD_RGB
    rgb[hit_orange] = _ORANGE_RGB

    if enabled_ids:
        highlight_colors, matched = compute_highlight_colors(primes_arr, n, enabled_ids, theta, mode)
        rgb[matched] = highlight_colors[matched]

    if track_primes:
        rgb[tracked_ring_mask(primes_arr, track_primes)] = _TRACKED_WHITE_RGB

    if resonance_track_primes:
        rgb[tracked_ring_mask(primes_arr, resonance_track_primes)] = _FLASH_RESONANCE_RGB

    data = np.empty((count, 5), dtype=np.float32)
    data[:, 0] = pos["x"]
    data[:, 1] = pos["y"]
    data[:, 2:5] = rgb / 255.0
    return data, count, pos


_TRACKED_OUTLINE_GRAY = (180.0 / 255.0, 180.0 / 255.0, 180.0 / 255.0)
_TRACKED_OUTLINE_ALPHA = 0.5


def tracked_outline_color(matched, tracked_color_rgb):
    """Per-ring outline stroke (r, g, b, a) in 0..1.

    Uses the matched window family's own color whenever any family matches,
    regardless of how many window families are currently active -- a
    deliberate deviation from DrumRenderer's original `ring.tracked` branch
    (`(state.activeWindowCount > 1 && ring.trackedColor) ? ... : gray`),
    which only used the tracked color once MORE than one family was
    enabled. This keeps a ring's outline consistent with the HUD's own
    window-range label, which already shows the active family's full solid
    color regardless of count (window_label_colors always returns one, see
    that function's own doc-comment).

    `tracked_color_rgb` is a plain 0..255 (r, g, b) triple, already summed by
    ring_geometry.compute_tracked_colors for this ring -- this function only
    decides WHETHER to use it (via the `matched` flag from that same call):
    a real "no family matched" zero vector and a genuinely matched color are
    otherwise indistinguishable by value alone, so `matched` (not a
    non-zero check) is what compute_tracked_colors already returns for
    exactly this reason. `matched` is already False whenever NO window
    family is enabled at all (build_tracked_outline_draws sets it to an
    all-False array in that case), so a plain auto-orbit/manual-tracking
    ring with no window context still falls through to gray here, same as
    before -- only the ">1 windows" requirement is gone."""
    if matched:
        r, g, b = tracked_color_rgb
        return (r / 255.0, g / 255.0, b / 255.0, _TRACKED_OUTLINE_ALPHA)
    return (_TRACKED_OUTLINE_GRAY[0], _TRACKED_OUTLINE_GRAY[1], _TRACKED_OUTLINE_GRAY[2], _TRACKED_OUTLINE_ALPHA)


def resolve_effective_track_primes(window_anchors, enabled_ids, auto_orbit, orbit_current_prime, track_primes):
    """Pure precedence rule for which primes get an outline ring THIS frame.

    When any window family is on, the result is the UNION
    of window_anchors and track_primes (window_anchors first, in their own
    order, then any track_primes not already in that list, deduplicated) --
    both are shown together instead of one hiding the other. A ring present
    in both still renders as its window's own color (compute_tracked_colors
    matches on window-anchor membership, not on this list), so this only
    ever ADDS rings that would otherwise have disappeared; it never removes
    or recolors anything the window-only behavior already showed.

    Only when NO window family is on does auto-orbit or a plain
    --track-primes list apply on their own -- see
    rebuild_buffer's own call site for why auto-orbit's cycling itself is
    ALSO gated on `not enabled_ids` (a family being on must fully stop
    auto-orbit from advancing in the background, not just from being shown,
    mirroring the JS's `if (!anyWindowOn) { this.#advanceAutoOrbit(...) }`)."""
    if enabled_ids:
        combined = list(window_anchors)
        for prime in track_primes:
            if prime not in combined:
                combined.append(prime)
        return combined
    if auto_orbit:
        return [orbit_current_prime] if orbit_current_prime is not None else []
    return track_primes


def build_tracked_outline_draws(primes_active, n, enabled_ids, theta, mode, track_primes, radii,
                                 anchor_overrides=None):
    """Everything the GL layer needs to draw one outline circle per tracked-
    AND-active ring, computed ONCE per N-change inside rebuild_buffer (same
    convention as build_vertex_data -- see module docstring's architecture
    note: geometry/color recompute on N-change only, camera/GPU work every
    frame).

    `radii` -- ring_geometry.ring_positions()["radius"] for this same
    `primes_active` array (same indexing), i.e. the caller's already-computed
    `pos["radius"]`; not recomputed here to avoid doing ring_positions' own
    trig twice per N-change.

    `anchor_overrides` -- forwarded verbatim to
    compute_tracked_colors (see that function's own doc-comment) -- lets
    rebuild_buffer's cyclic_window_anchor_at result color the SAME ring
    window_anchor_primes already chose to track, instead of
    compute_tracked_colors recomputing "legendre"/"generalLaw"'s anchor its
    own way via ANCHOR_FUNCTIONS, which would pick a different ring.

    Returns a list of (radius, (r, g, b, a)) tuples, one per tracked-and-
    active ring, in `primes_active`'s own ascending order (matching how
    `radii` is indexed) -- NOT `track_primes`'s user-typed order, unlike
    filter_active_tracked's LCM-facing list."""
    primes_arr = to_prime_array(primes_active)
    mask = tracked_ring_mask(primes_arr, track_primes)
    if not mask.any():
        return []
    if enabled_ids:
        colors, matched = compute_tracked_colors(primes_arr, n, enabled_ids, theta, mode, anchor_overrides)
    else:
        colors = np.zeros((len(primes_arr), 3), dtype=np.float64)
        matched = np.zeros(len(primes_arr), dtype=bool)
    draws = []
    for i in np.nonzero(mask)[0]:
        draws.append((float(radii[i]), tracked_outline_color(bool(matched[i]), tuple(colors[i]))))
    return draws


_FLASH_RESONANCE_RGB = (255.0, 140.0, 0.0)  # "rgba(255,140,0,{a})" -- orange, resonance
_FLASH_PRIME_RGB = (60.0, 60.0, 60.0)       # "rgba(60,60,60,{a})" -- dark gray, prime birth


def resonance_is_active(pos):
    """Whether EVERY currently active ring's tooth sits at phase 0 -- ports
    SieveModel.getStepState's `resonance.active` condition (`maxResonance >
    0 && factors.length >= maxResonance`, which reduces to "every active
    prime divides n" once at least one ring exists -- see that method's own
    doc-comment for why the maxResonance>0 guard exists, to avoid a
    spurious resonance at n=0/no active primes). `pos` is
    ring_geometry.ring_positions()'s own return dict; an empty ring set
    (count==0) is never a resonance, matching the JS guard."""
    hit = pos["is_hit"]
    return bool(len(hit)) and bool(np.all(hit))
