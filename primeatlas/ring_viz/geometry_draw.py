"""
geometry_draw.py -- pure, GL-context-free vertex/color/geometry math for
primeatlas/ring_viz/renderer.py: per-ring vertex color/position data, the
hit/normal buffer split, Load Range slicing, tracked-ring outline geometry,
the center marker and flash-overlay shapes, camera zoom-to-cursor/fit-to-
viewport math, and initial-N selection. [ADDED Faza 2 of the renderer.py
split, see renderer.py's own module docstring for the overall refactor
plan.]

Everything here takes plain arrays/scalars and returns plain arrays/tuples
-- no moderngl/glfw call anywhere, so every function is unit-testable in a
headless sandbox with no GPU/display (see test_ring_viz_renderer.py, which
already does exactly that). renderer.py's own `_run_visualization` is the
only caller that turns this module's output into actual GL buffers/draw
calls.

Self-contained sys.path bootstrap (mirrors renderer.py's own -- see that
file's module docstring for the full "why plain-script-path" explanation):
needed so `from primeatlas.ring_geometry import ...` below works whether
this module is imported after renderer.py has already run its own
bootstrap, or on its own (e.g. directly from a test).
"""

import os
import sys

import numpy as np

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_PRIME_SIEVE_DIR = os.path.join(_REPO_ROOT, "prime_sieve")
if _PRIME_SIEVE_DIR not in sys.path:
    sys.path.insert(0, _PRIME_SIEVE_DIR)

from primeatlas.ring_geometry import (
    ring_positions,
    compute_highlight_colors,
    compute_tracked_colors,
    tracked_ring_mask,
    to_prime_array,
)


_CYAN_RGB = (0.0, 188.0, 212.0)      # "#00bcd4"
_GOLD_RGB = (255.0, 215.0, 0.0)      # "#ffd700" -- hit, prime >= 11
_ORANGE_RGB = (255.0, 87.0, 34.0)    # "#ff5722" -- hit, prime < 11
_TRACKED_WHITE_RGB = (255.0, 255.0, 255.0)


def build_vertex_data(primes, n, max_radius, enabled_ids=(), theta=0.5, mode="stepped", track_primes=()):
    """ring_geometry.ring_positions() -> flat (x,y,r,g,b) float32 array ready
    for a moderngl buffer.

    [Faza 0] Originally just cyan/gold based on hit status.
    [Faza 4, see PLAN.md] Now also layers in window-highlight colors via
    ring_geometry.compute_highlight_colors (already-tested Bertrand pink /
    Legendre green / General Law violet additive blend, ported in Faza 1) --
    ports DrumRenderer's own priority chain: base cyan, then hit recolors to
    gold/orange, then `ring.highlightColor` (if any family matches) OVERRIDES
    whatever came before, hit or not -- see #drawRingTeeth's own doc-comment
    ("This file no longer knows Bertrand's pink or Legendre's green as
    literals... it just paints whatever color... the app already computed").
    `enabled_ids` empty (the Faza-0/3 default, no window UI wired yet at
    launch time) reproduces the exact old cyan/gold-only behavior since
    compute_highlight_colors returns matched=all-False for an empty family
    set.

    [ADDED 2026-09-11, closes the gap the paragraph above used to flag as
    deferred] `track_primes` -- the SAME effective-tracked-ring set
    rebuild_buffer feeds build_tracked_outline_draws (rings.py's
    resolve_effective_track_primes: whichever rings are the currently
    active anchors, from a window family, auto-orbit, or a manual --track-
    primes list) -- gets its own DOT forced to plain white, ONE more link
    in the same override chain, applied AFTER (so it wins over) the window-
    highlight color above. Artur's own reasoning (2026-09-11): the tracked-
    ring OUTLINE circle (build_tracked_outline_draws) already carries the
    active window's own color (green for Legendre, violet for General Law,
    additively blended when both happen to coincide) -- deliberately
    UNCHANGED by this -- but the ring's actual POINT used to just blend
    into every other same-colored member of that window; a plain white dot
    makes the one ring actually being tracked/anchored instantly
    identifiable at a glance, regardless of whatever window color its
    surroundings carry. Empty (the default) reproduces the exact prior
    behavior -- tracked_ring_mask (ring_geometry.py) already returns all-
    False for an empty `track_primes`, so this is a no-op then, same
    convention as `enabled_ids=()` above."""
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

    data = np.empty((count, 5), dtype=np.float32)
    data[:, 0] = pos["x"]
    data[:, 1] = pos["y"]
    data[:, 2:5] = rgb / 255.0
    return data, count, pos


def split_hit_normal_vertex_data(data, hit_mask):
    """Splits `data` (build_vertex_data's own (count, 5) array) into two
    row subsets by `hit_mask` (pos["is_hit"], same row order/length as
    `data`) -- rings ON the vertical reference line (real divisors of N)
    vs everything else.

    [ADDED Faza 11C, see PLAN.md] Why this exists: Artur, 2026-09-07, wants
    hit rings sized independently of the rest (--hit-point-size vs
    --point-size). u_point_size is a single shared shader uniform (see
    VERTEX_SHADER) -- there is no per-vertex point-size attribute in this
    pipeline -- so getting two different on-screen sizes means two separate
    draw calls over two separate vertex buffers, each with its own
    u_point_size value set immediately before its own render() call (see
    run()'s own main loop). This function is the CPU-side half of that
    split (kept pure/GL-free so it's unit-testable without a display); the
    GL-side half (two ctx.buffer()/vertex_array() pairs, two render calls)
    lives entirely in run() since it needs a real moderngl context.

    Returns (data_normal, data_hit, count_hit) -- `data_normal`/`data_hit`
    are plain row-subset views (numpy fancy-indexing copies, not views, but
    that distinction doesn't matter to the caller, which immediately calls
    .tobytes() on each), `count_hit` is `data_hit`'s own row count (the
    caller already has `data`'s total row count separately, so there's no
    matching `count_normal` -- `total - count_hit` is cheaper than a second
    redundant field). An empty `data`/`hit_mask` (0 active rings) returns
    two empty arrays and count_hit=0, never raises."""
    if len(hit_mask) == 0:
        return data, data[:0], 0
    count_hit = int(np.count_nonzero(hit_mask))
    return data[~hit_mask], data[hit_mask], count_hit


# ---------------------------------------------------------------------------
# Faza 9 (see PLAN.md) -- Load Range: switch to a FIXED ring set (a slice of
# already-loaded primes in [from, to]), independent of N, mirroring
# SieveModel's "range"/slice mode (see that class's own module doc-comment:
# sequential mode's ring set is primesUpTo(n) and grows with n; range mode's
# ring set is a fixed array chosen once and never re-filtered by n again --
# only each ring's phase/hit status still depends on n via ring_positions,
# which doesn't care how its `primes` argument was derived).
# ---------------------------------------------------------------------------

def load_prime_range_slice(primes, from_n, to_n):
    """The ascending sub-array of `primes` (this renderer's own already-
    loaded array -- there is no separate always-larger data source here the
    way the JS's PrimeDataSource is, so `primes` itself plays that role)
    whose values fall in [from_n, to_n] inclusive. Ports
    SieveModel.loadPrimeRange's slicing half only -- the mode-switching side
    effects (n reset to 0, auto-populating Track P, printing an info line)
    are run()'s own job, kept out of this pure function the same way this
    module keeps every other GL-adjacent decision out of its pure helpers.

    Raises ValueError (Python's RangeError-equivalent) for the same two
    cases SieveModel.loadPrimeRange throws for: an inverted range (`from_n
    > to_n`), or a `to_n` beyond what is actually loaded (`to_n >
    primes[-1]`, or `primes` is empty) -- ports the "exceeds the loaded
    ceiling" check using THIS renderer's own loaded array as the ceiling."""
    if from_n > to_n:
        raise ValueError(f"load_prime_range_slice: invalid range [{from_n}, {to_n}] (from > to)")
    primes_arr = to_prime_array(primes)
    ceiling = int(primes_arr[-1]) if len(primes_arr) else -1
    if to_n > ceiling:
        raise ValueError(f"load_prime_range_slice: {to_n} exceeds the loaded ceiling ({ceiling})")
    lo = int(np.searchsorted(primes_arr, from_n, side="left"))
    hi = int(np.searchsorted(primes_arr, to_n, side="right"))
    return primes_arr[lo:hi]


# ---------------------------------------------------------------------------
# Faza 8 (see PLAN.md) -- tracked-ring outline circles, birth/resonance flash
# overlays, center marker. Ports DrumRenderer.draw's `if (ring.tracked) {...}`
# outline-stroke branch, #drawCenterMarker, and the #drawFlashOverlay/
# triggerBirthFlash/triggerResonanceFlash trio.
#
# All of the ANCHOR/COLOR math these draw calls need (compute_tracked_colors)
# already existed in ring_geometry.py from Faza 1 -- this phase's only new
# pure-math surface is the small amount below that is
# specific to the GL layer itself (unit-circle geometry, screen-space marker
# offsets, flash decay/alpha), everything kept as plain functions so it can
# be unit-tested without a GPU (see run()'s own GL wiring further down for
# the untestable-without-a-display half of this phase).
# ---------------------------------------------------------------------------

def unit_circle_vertices(segments=64):
    """(segments, 2) float32 array of (cos, sin) pairs around the unit
    circle, ascending angle from 0 -- the shared base geometry for every
    tracked-ring outline. Each tracked ring's actual on-screen circle is
    this SAME buffer scaled by a per-draw-call `u_radius` uniform (see
    OUTLINE_VERTEX_SHADER / run()'s tracked-outline draw loop) rather than
    rebuilding a new vertex buffer per ring: moderngl has no built-in arc
    primitive the way Canvas 2D's `ctx.arc(cx, cy, radius, 0, 2*PI)` does
    (DrumRenderer's own tracked-ring stroke), so this is the GL equivalent
    -- a GL_LINE_LOOP over `segments` points -- computed once and reused."""
    angles = np.linspace(0.0, 2.0 * np.pi, num=segments, endpoint=False, dtype=np.float64)
    return np.stack([np.cos(angles), np.sin(angles)], axis=1).astype(np.float32)


_TRACKED_OUTLINE_GRAY = (180.0 / 255.0, 180.0 / 255.0, 180.0 / 255.0)
_TRACKED_OUTLINE_ALPHA = 0.5


def tracked_outline_color(matched, tracked_color_rgb):
    """Per-ring outline stroke (r, g, b, a) in 0..1.

    [CHANGED 2026-09-10, see Artur's report: with only ONE window family
    enabled, the HUD's own window-range label already shows that family's
    full solid color (window_label_colors always returns one, regardless
    of how many families are on -- see that function's own doc-comment),
    but the matching tracked-ring outline still drew flat gray. Artur's own
    words: "trzymajmy sie jednej zasady, ze skoro okno w hud ma kolor to
    pierscien niech go tez ma tak samo" (one consistent rule: whenever a
    window has a color in the HUD, its ring should carry that same color).
    Originally this ported DrumRenderer's `ring.tracked` branch literally --
    `(state.activeWindowCount > 1 && ring.trackedColor) ? ... : gray` --
    which the ORIGINAL site actually does gate on more than one active
    family; this is now a deliberate, explicit DEVIATION from that 1:1 port,
    per Artur's above instruction, not a bug fix in the porting sense.

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
    """[ADDED 2026-09-10, CHANGED 2026-09-12] Pure precedence rule for which
    primes get an outline ring THIS frame.

    [CHANGED 2026-09-12, Artur's bug report: "ustawione są pierścienie jakie
    mają być śledzone ale przez to że włączone są okna jak bertrand legendre
    to te śledzone nie są wyświetlone a powinny skoro są wypisane jakie mają
    być śledzone"] Originally this ported #renderFrame's `if (anyWindowOn) {
    this.#trackedPrimes = anchors; }` LITERALLY -- any window family on made
    window_anchors fully REPLACE a manual --track-primes list, so a ring the
    user explicitly asked to track would vanish the moment any window family
    was enabled. Now: when any window family is on, the result is the UNION
    of window_anchors and track_primes (window_anchors first, in their own
    order, then any track_primes not already in that list, deduplicated) --
    both are shown together instead of one hiding the other. A ring present
    in both still renders as its window's own color (compute_tracked_colors
    matches on window-anchor membership, not on this list), so this only
    ever ADDS rings that would otherwise have disappeared; it never removes
    or recolors anything the window-only behavior already showed.

    Only when NO window family is on does auto-orbit or a plain
    --track-primes list apply on their own, unchanged from before -- see
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

    `anchor_overrides` -- [ADDED 2026-09-11] forwarded verbatim to
    compute_tracked_colors (see that function's own doc-comment) -- lets
    rebuild_buffer's cyclic_window_anchor_at result color the SAME ring
    window_anchor_primes already chose to track, instead of
    compute_tracked_colors recomputing "legendre"/"generalLaw"'s anchor its
    own (now stale) way via ANCHOR_FUNCTIONS.

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


def center_marker_triangle_offsets(s):
    """(3, 2) float32 array of (dx, dy) triangle-vertex offsets from the
    view's screen-space center point (cx, cy) -- ports DrumRenderer's
    #drawCenterMarker filled triangle exactly: tip pointing toward the ring
    field (0,0 offset, i.e. AT the center point itself) with two back
    corners 35*s pixels toward the top of the screen and 12*s pixels to
    each side.

    `s` is DrumRenderer's own resolution-only device scale (`min(w,h) /
    REFERENCE_MIN_DIM`) -- NOT the interactive camera zoom (state.zoomValue
    / this module's u_zoom) -- see run()'s caller for where `s` comes from
    on the Python side; the marker's size tracks window resolution, not how
    far the user has zoomed the ring field."""
    return np.array([[0.0, 0.0], [-12.0 * s, -35.0 * s], [12.0 * s, -35.0 * s]], dtype=np.float32)


def decay_flash(value, factor):
    """One frame's worth of exponential decay for a flash-overlay alpha
    accumulator. Ports DrumRenderer's own
        this.#flashResonance *= 0.65; if (this.#flashResonance < 0.01) this.#flashResonance = 0;
    (and the analogous 0.85-factor line for #flashPrime) as a single pure
    function, so run()'s render loop calls one thing instead of duplicating
    the epsilon-snap-to-zero rule inline at both call sites."""
    value = value * factor
    return 0.0 if value < 0.01 else value


_FLASH_RESONANCE_RGB = (255.0, 140.0, 0.0)  # "rgba(255,140,0,{a})" -- orange, resonance
_FLASH_PRIME_RGB = (60.0, 60.0, 60.0)       # "rgba(60,60,60,{a})" -- dark gray, prime birth
_FLASH_MAX_ALPHA = 0.25


def flash_overlay_rgba(flash_value, base_rgb, max_alpha=_FLASH_MAX_ALPHA):
    """(r, g, b, a) in 0..1 for a full-screen flash-overlay quad at the given
    accumulator value -- ports DrumRenderer's #drawFlashOverlay (a filled
    rect over the whole canvas, alpha = flash_value * max_alpha, wired
    through a `rgba(...,{a})` template string there) as a plain tuple for a
    GL uniform instead of a CSS color string. `flash_value <= 0` (the
    resting state most frames are in) yields alpha 0 -- callers can skip
    the draw call entirely in that case rather than drawing an invisible
    quad every frame, since flash_value is 0 the overwhelming majority of
    the time (only nonzero for a few frames after a trigger, per
    decay_flash's own decay rate)."""
    r, g, b = base_rgb
    return (r / 255.0, g / 255.0, b / 255.0, flash_value * max_alpha)


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


_MARKER_REFERENCE_MIN_DIM = 2160.0  # ports DrumRenderer's own REFERENCE_MIN_DIM constant


def marker_device_scale(width, height):
    """DrumRenderer's own `s = Math.min(w, h) / REFERENCE_MIN_DIM` -- the
    resolution-only proportion scale every absolute-pixel marker constant is
    multiplied by (see that module's own doc-comment: its reference layout
    was 3840x2160)."""
    return min(width, height) / _MARKER_REFERENCE_MIN_DIM


_MARKER_TRIANGLE_RGBA = (1.0, 0.067, 0.067, 1.0)      # DrumRenderer's opaque marker fill, "#ff1111"
_MARKER_LINE_RGBA = (1.0, 0.157, 0.157, 0.55)         # DrumRenderer's "rgba(255,40,40,0.55)" glow line


def _screen_vertex_data(xy_pairs, rgba):
    """[ADDED Faza 0 refactor] Shared (N, 6) float32 (pos.xy, color.rgba)
    stamper for the small, flat-colored screen-space shapes drawn via
    SCREEN_VERTEX_SHADER -- build_center_marker_vertex_data's triangle/line
    and build_flash_quad_vertex_data's quad used to each hand-build this same
    (N, 6) layout separately; every vertex in one call shares the same
    `rgba`, only its (x, y) position differs."""
    data = np.empty((len(xy_pairs), 6), dtype=np.float32)
    for i, (x, y) in enumerate(xy_pairs):
        data[i, 0] = x
        data[i, 1] = y
    data[:, 2:6] = rgba
    return data


def build_center_marker_vertex_data(cx, cy, s):
    """(triangle_data, line_data) -- two small float32 (pos.xy, color.rgba)
    arrays ready for a moderngl buffer via SCREEN_VERTEX_SHADER, at the
    given screen-space anchor (cx, cy) -- the ring field's own world-origin
    screen position, i.e. the SAME value already computed each frame as
    run()'s `prog["u_pan"]` (see center_marker_triangle_offsets' own
    doc-comment for why zoom does not enter into this) -- and device scale
    `s` (see marker_device_scale).

    triangle_data: 3 vertices, ports #drawCenterMarker's filled arrow.
    line_data: 2 vertices, from the anchor itself up to screen y=0 -- ports
    `ctx.moveTo(cx, cy); ctx.lineTo(cx, 0)`. Recomputed fresh every frame
    (this function is cheap: 5 vertices total) since both cx/cy (camera pan)
    and the line's own length (cy's distance to the top of the window) can
    change every frame -- there is no fixed buffer to reuse the way the
    tracked-ring outline's shared unit circle is."""
    offsets = center_marker_triangle_offsets(s)
    triangle = _screen_vertex_data(
        [(cx + offsets[i, 0], cy + offsets[i, 1]) for i in range(offsets.shape[0])],
        _MARKER_TRIANGLE_RGBA,
    )
    line = _screen_vertex_data([(cx, cy), (cx, 0.0)], _MARKER_LINE_RGBA)
    return triangle, line


def build_flash_quad_vertex_data(width, height, rgba):
    """4-vertex float32 (pos.xy, color.rgba) array covering the full
    viewport (a TRIANGLE_FAN quad: corners in order (0,0),(w,0),(w,h),(0,h))
    at a single flat color -- ports DrumRenderer's #drawFlashOverlay
    (`ctx.fillRect(0, 0, w, h)` at that color). All four vertices share the
    same `rgba` (see flash_overlay_rgba for how that's derived from the
    current flash accumulator) since the overlay is a flat wash, not a
    gradient."""
    return _screen_vertex_data([(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)], rgba)


def zoom_to_point(old_zoom, old_pan, cursor, viewport, factor):
    """Computes the new (zoom, pan) that keeps the WORLD-space point
    currently under `cursor` fixed on screen after multiplying zoom by
    `factor` -- i.e. real "zoom to cursor" (or, called with the viewport's
    own center as `cursor`, "zoom to screen center").

    [FIXED, see Artur's 2026-09-04 bug report] The vertex shader computes
    screen = world*zoom + pan (see VERTEX_SHADER's u_pan/u_zoom uniforms),
    where `pan` here is the EFFECTIVE pan already including the viewport-
    center offset (i.e. exactly the u_pan value -- run()'s render loop adds
    state["pan"] + viewport/2 to get this; see this function's own callers).
    Naively multiplying zoom alone (the old on_scroll behavior) leaves world
    position (0,0) -- the ring field's own mathematical center -- pinned to
    whatever screen point `pan` currently is, regardless of where the cursor
    or the viewport center actually are. That made every zoom anchor on the
    ring field's center: zooming in on a panned-to tail raced back toward
    that center instead of staying under the cursor, and zooming out from
    there flew the view away from the ring field entirely.

    `old_pan`, returned `new_pan` -- (x, y) tuples, the EFFECTIVE pan (world
    origin's current screen position), NOT run()'s `state["pan"]` (which is
    that value minus viewport/2 -- see run()'s on_scroll for the conversion
    at both ends of a call to this function).
    `cursor`, `viewport` -- (x, y) tuples in the same screen-pixel space as
    `old_pan`.
    `factor` -- zoom multiplier (>1 to zoom in, <1 to zoom out).

    Returns (new_zoom, (new_pan_x, new_pan_y))."""
    new_zoom = old_zoom * factor
    cx, cy = cursor
    old_pan_x, old_pan_y = old_pan
    world_x = (cx - old_pan_x) / old_zoom
    world_y = (cy - old_pan_y) / old_zoom
    new_pan_x = cx - world_x * new_zoom
    new_pan_y = cy - world_y * new_zoom
    return new_zoom, (new_pan_x, new_pan_y)


# Fraction of the viewport's SMALLER dimension the ring field's own radius
# should fill -- 0.45 means the full ring-field DIAMETER (2*max_radius) ends
# up covering 90% of that dimension, leaving a modest 5%-per-side margin.
# This is the same 0.45 _run_visualization already used, inline, to size
# max_radius itself from the LAUNCH window (max_radius = min(args.width,
# args.height) * 0.45) -- pulling it out into a named constant shared with
# fit_zoom_for_viewport below guarantees the two stay in lockstep: calling
# fit_zoom_for_viewport(max_radius, launch_width, launch_height) returns
# exactly 1.0, so "the view as it already opens" and "the view after an
# explicit re-fit" are provably the same computation, not two independently
# hand-tuned constants that could drift apart.
_FIT_MARGIN = 0.45


def fit_zoom_for_viewport(max_radius, width, height, margin=_FIT_MARGIN):
    """Zoom multiplier that makes a ring field of world-space radius
    `max_radius` fill `margin` of the viewport's SMALLER dimension -- i.e.
    the full window HEIGHT, or the full WIDTH if the window is narrower than
    it is tall (Artur, 2026-09-11: "zajmowało pełną wysokość okna lub
    szerokość jeśli okno będzie węższe od wysokości"). Using min(width,
    height) as the constraint is exactly that rule: whichever dimension is
    the tighter one is the one the (roughly circular) ring field gets fit
    against, so it's never clipped on either axis.

    Used for two things that both need the same "make it fit again"
    computation: (1) re-fitting after an F11 fullscreen<->windowed
    transition changes the viewport size/aspect ratio out from under a zoom
    value that was only ever correct for the OLD size, and (2) the explicit
    recenter action (middle mouse button, see on_mouse_button below) that
    snaps a zoomed/panned-away view back to "the whole picture, centered" in
    one action.

    Degenerate inputs (a non-positive radius or viewport dimension -- should
    not happen in practice, but a GLFW framebuffer query returning 0 during
    a transient resize is exactly the kind of thing worth not crashing on)
    fall back to zoom=1.0 rather than dividing by zero or returning a
    negative/infinite zoom."""
    if max_radius <= 0 or width <= 0 or height <= 0:
        return 1.0
    return (min(width, height) * margin) / max_radius


def initial_n_for_source(source, upto, primes):
    """Picks the N the ring view should OPEN on, given how the ring array was
    sourced.

    [FIXED, see Artur's 2026-09-04 bug report] For --source sieve/magazyn,
    the user has a real target N in mind (rings_tab.py's N field, passed
    through verbatim as --upto) -- the view must open exactly there, not on
    whatever the last loaded prime happens to be. ring_positions() computes
    is_hit as n % prime == 0 (real divisors of N), so N is not required to be
    prime itself; snapping to primes[-1] silently showed the wrong number
    (e.g. typing 1000 opened on N=997, the largest prime <=1000, with
    "Factors of N: 997" -- itself, since 997 is prime -- instead of 1000's
    real factors 2 and 5).

    --source synthetic has no user-specified target N at all (only --count,
    an arbitrary ring COUNT -- see load_synthetic's own docstring), so there
    is no "the value the user asked for" to open on; it keeps using the last
    generated value instead, same as before this fix."""
    if source == "synthetic":
        return int(primes[-1]) if len(primes) else 0
    return upto
