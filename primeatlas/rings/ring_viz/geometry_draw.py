"""
geometry_draw.py -- pure, GL-context-free vertex/color/geometry math for
primeatlas/rings/ring_viz/renderer.py: per-ring vertex color/position data, the
hit/normal buffer split, Load Range slicing, tracked-ring outline geometry,
the center marker and flash-overlay shapes, camera zoom-to-cursor/fit-to-
viewport math, and initial-N selection.

Everything here takes plain arrays/scalars and returns plain arrays/tuples
-- no moderngl/glfw call anywhere, so every function is unit-testable in a
headless sandbox with no GPU/display (see test_ring_viz_renderer.py, which
already does exactly that). renderer.py's own `_run_visualization` is the
only caller that turns this module's output into actual GL buffers/draw
calls.

Self-contained sys.path bootstrap (mirrors renderer.py's own -- see that
file's module docstring for the full "why plain-script-path" explanation):
needed so `from primeatlas.rings.ring_geometry import ...` below works whether
this module is imported after renderer.py has already run its own
bootstrap, or on its own (e.g. directly from a test).
"""

import os
import sys

import numpy as np

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # ring_viz/ now lives one directory deeper, under primeatlas/rings/
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_PRIME_SIEVE_DIR = os.path.join(_REPO_ROOT, "prime_sieve")
if _PRIME_SIEVE_DIR not in sys.path:
    sys.path.insert(0, _PRIME_SIEVE_DIR)

from primeatlas.rings.ring_geometry import (
    ring_positions,
    compute_highlight_colors,
    compute_tracked_colors,
    tracked_ring_mask,
    to_prime_array,
    line_positions,
    line_view_bounds,
    line_positions_windowed,
    line_positions_windowed_ring,
    line_positions_windowed_spiral,
    value_to_line_x,
    value_to_ring_axis_xy,
    value_to_spiral_xy,
    spiral_outer_radius,
    pattern_positions_and_match,
)


_CYAN_RGB = (0.0, 188.0, 212.0)      # "#00bcd4"
_GOLD_RGB = (255.0, 215.0, 0.0)      # "#ffd700" -- hit, prime >= 11
_ORANGE_RGB = (255.0, 87.0, 34.0)    # "#ff5722" -- hit, prime < 11
_TRACKED_WHITE_RGB = (255.0, 255.0, 255.0)

# "line" viz-mode colors -- see build_line_vertex_data below.
_LINE_BASE_RGB = (0.0, 188.0, 212.0)  # background dot row, same cyan as ring mode's base
_LINE_MATCH_RGB = (0.0, 230.0, 118.0)  # "#00e676" -- pattern member IS a real prime
_LINE_MISS_RGB = (255.0, 23.0, 68.0)   # "#ff1744" -- pattern member is NOT prime here

#: Curved-axis boundary marker -- opaque red, see axis_boundary_marker_vertices.
_AXIS_BOUNDARY_RGBA = (1.0, 0.0, 0.0, 1.0)


def axis_boundary_marker_vertices():
    """(2, 2) float32 unit-space array for "line" viz-mode's curved-axis
    boundary marker: a straight line from the circle's own center (0,0)
    out to its "12 o'clock" edge point (0,-1), in the SAME unit-vector
    convention unit_circle_vertices already uses for the tracked-ring
    outline (both are scaled by a per-draw-call `u_radius` uniform in
    OUTLINE_VERTEX_SHADER, drawn through the SAME prog_outline program --
    this marker just uses moderngl.LINES instead of LINE_LOOP as its draw
    mode, and a single shared 2-vertex buffer instead of unit_circle_
    vertices' `segments`-point one).

    (0,-1) is exactly where value_to_ring_axis_xy places t=0 AND t=1 alike
    (angle -pi/2, "12 o'clock") -- see that function's own doc-comment for
    why a real, non-cyclic loaded range needs this seam marked at all:
    unlike ring mode's genuinely periodic n % p, a line-mode window's own
    `lo` and `lo+span` are NOT the same value, just drawn at the same
    point once the axis is bent into a circle."""
    return np.array([[0.0, 0.0], [0.0, -1.0]], dtype=np.float32)


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


def split_hit_normal_vertex_data(data, hit_mask):
    """Splits `data` (build_vertex_data's own (count, 5) array) into two
    row subsets by `hit_mask` (pos["is_hit"], same row order/length as
    `data`) -- rings ON the vertical reference line (real divisors of N)
    vs everything else.

    Why this exists: hit rings can be sized independently of the rest
    (--hit-point-size vs --point-size). u_point_size is a single shared
    shader uniform (see VERTEX_SHADER) -- there is no per-vertex point-size
    attribute in this pipeline -- so getting two different on-screen sizes
    means two separate draw calls over two separate vertex buffers, each
    with its own u_point_size value set immediately before its own
    render() call (see run()'s own main loop). This function is the
    CPU-side half of that split (kept pure/GL-free so it's unit-testable
    without a display); the GL-side half (two ctx.buffer()/vertex_array()
    pairs, two render calls) lives entirely in run() since it needs a real
    moderngl context.

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


def build_line_vertex_data(range_primes, n, offsets, world_width=1600.0, primes_set=None, curved=False,
                            wheel_modulus=None):
    """"line" viz-mode counterpart of build_vertex_data: a fixed horizontal
    row of point-sprites, one per real prime in `range_primes` (the base
    cyan dots), plus -- when `offsets` is non-empty -- the sliding
    pattern's own `n, n+offsets[1], ...` member positions appended as
    EXTRA rows (not recoloring an existing dot: a non-matching member has
    no real-prime dot to recolor in the first place), green where that
    position is a real prime and red where it isn't.

    The coordinate mapping itself comes from line_view_bounds (see that
    function's own doc-comment for the float32-precision reasoning): the
    WHOLE loaded window when its span is small enough for float32 to
    resolve every point distinctly, or else a small, FIXED-width slice
    camera-anchored on `n` -- in the local case, ONLY the background dots
    actually inside that slice are drawn (line_positions_windowed's own
    filter), never the full `range_primes` array's every row, since
    anything outside the slice would round to the exact same handful of
    float32 x positions anyway.

    `curved` -- Artur's own follow-up request (2026-09-18): a PURELY
    visual choice between laying the very same lo/span-mapped positions
    out on a straight line (y=0, the default, unchanged) or bent into a
    circle (line_positions_windowed_ring/value_to_ring_axis_xy) -- see
    those functions' own doc-comments. Does not touch which positions are
    computed, which ones count as a match, or ANY navigation/wheel/seek
    logic -- those all operate on the same `n`/`offsets`/`primes_set`
    either way, exactly Artur's own spec ("w samym działaniu nic się nie
    zmieni poza samą wizualizacją osi" -- nothing changes in the actual
    behavior, only the axis's own visualization).

    `wheel_modulus` -- when `curved` AND this is a real wheel modulus
    (> 1, i.e. ring_geometry.pattern_wheel_residues actually found one --
    see RenderSession's own `self.pattern_wheel_modulus`), the curved
    layout becomes a SPIRAL instead of a single circle
    (line_positions_windowed_spiral/value_to_spiral_xy): each full
    `wheel_modulus`-sized chunk of the axis gets its own lap, at a bigger
    radius than the previous one, so a window spanning multiple wheel
    periods shows that structure directly instead of always normalizing
    the whole window onto one loop -- Artur's own follow-up
    (2026-09-18/19): "jeśli zakres starcza na niepełny okrąg ... mamy
    niepełny okrąg, jeśli periodyk powoduje spiralę o kilku stopniach
    zagnieżdżenia to tak to będzie wyglądać." None or <= 1 (no pattern
    set, or a pattern whose wheel excludes nothing) falls back to the
    plain single-circle layout, unchanged.

    `primes_set` -- optional pre-built `set(int(v) for v in range_primes)`
    for the match check below; a caller holding `range_primes` fixed
    across many calls (RenderSession, whose own `_pattern_primes_set` is
    already built once at construction for the wheel/founding-coincidence
    logic) should pass it through here too, instead of this function
    silently rebuilding the same set from scratch on every single N-change
    -- a real cost once `range_primes` is a real archive-scale array.
    Built fresh (the original behavior) when omitted.

    Returns (data, count, hit_mask, all_match, view_mode, boundary_radius):
    `data`/`count` are build_vertex_data's own flat (count, 5) float32
    [x,y,r,g,b] layout and row count, `hit_mask` is a bool ndarray marking
    the pattern-member rows (True for every one of them, matched or not --
    this is what buys them the independent --hit-point-size sizing via the
    same split_hit_normal_vertex_data/u_point_size mechanism ring mode's
    own hit rings already use, so no new GL uniform is needed), `all_match`
    is pattern_positions_and_match's own flag (False, not an error, when
    `offsets` is empty), `view_mode` is line_view_bounds' own "full"/
    "local" flag (for the HUD to report which one is active -- forced to
    "full" whenever the spiral layout is used, see below), and
    `boundary_radius` is the radius the curved-axis boundary marker should
    be drawn at (world_width/2 for the plain-circle case, spiral_outer_
    radius's own value for the spiral case, None when `curved` is False --
    a caller has nothing to draw then).

    The spiral case deliberately does NOT use line_view_bounds' own
    "local" anchor-centered viewport fallback the straight/plain-circle
    layouts still do: that fallback exists because a plain linear (or
    single-circle) mapping loses precision once the loaded window's span
    is astronomically wider than a k-tuple's own internal spacing (see
    line_view_bounds' own doc-comment) -- but the spiral's own precision
    is RADIUS-INDEPENDENT by construction (value_to_spiral_xy's own
    doc-comment: the value-delta-to-float32-ULP ratio only depends on the
    wheel period, never on how big any given lap's radius is), so there is
    nothing for a local viewport to protect against here. Using the LOCAL
    window's own tiny span (a few thousand, deliberately kept well under
    a realistic wheel period so the plain layouts stay precise) would
    instead just make a real, multi-period-wide loaded window look like a
    single near-empty partial arc every time, silently hiding the exact
    multi-lap structure the spiral exists to show -- so the spiral always
    maps the WHOLE loaded window (`range_lo`, `range_hi`) instead."""
    primes_arr = to_prime_array(range_primes)
    range_lo = int(primes_arr[0]) if len(primes_arr) else 0
    range_hi = int(primes_arr[-1]) if len(primes_arr) else 0
    view_mode, lo, span = line_view_bounds(range_lo, range_hi, n, offsets)
    radius = world_width / 2.0
    use_spiral = curved and wheel_modulus is not None and wheel_modulus > 1
    boundary_radius = None
    if use_spiral:
        lo, span = range_lo, max(range_hi - range_lo, 1)
        view_mode = "full"
        line = line_positions_windowed_spiral(primes_arr, lo, span, wheel_modulus, radius, radius)
        boundary_radius = spiral_outer_radius(span, wheel_modulus, radius, radius)
    elif curved:
        line = line_positions_windowed_ring(primes_arr, lo, span, radius)
        boundary_radius = radius
    else:
        line = line_positions_windowed(primes_arr, lo, span, world_width)
    bg_count = len(line["x"])

    bg_data = np.empty((bg_count, 5), dtype=np.float32)
    bg_data[:, 0] = line["x"]
    bg_data[:, 1] = line["y"]
    bg_data[:, 2:5] = np.array(_LINE_BASE_RGB, dtype=np.float64) / 255.0
    bg_hit_mask = np.zeros(bg_count, dtype=bool)

    if not offsets:
        return bg_data, bg_count, bg_hit_mask, False, view_mode, boundary_radius

    if primes_set is None:
        primes_set = set(int(v) for v in primes_arr)
    positions, hit_flags, all_match = pattern_positions_and_match(n, offsets, primes_set)

    pat_count = len(positions)
    pat_data = np.empty((pat_count, 5), dtype=np.float32)
    for i, (value, is_hit) in enumerate(zip(positions, hit_flags)):
        if use_spiral:
            pat_data[i, 0], pat_data[i, 1] = value_to_spiral_xy(value, line["lo"], wheel_modulus, radius, radius)
        elif curved:
            pat_data[i, 0], pat_data[i, 1] = value_to_ring_axis_xy(value, line["lo"], line["span"], radius)
        else:
            pat_data[i, 0] = value_to_line_x(value, line["lo"], line["span"], world_width)
            pat_data[i, 1] = 0.0
        pat_data[i, 2:5] = np.array(_LINE_MATCH_RGB if is_hit else _LINE_MISS_RGB, dtype=np.float64) / 255.0
    pat_hit_mask = np.ones(pat_count, dtype=bool)

    data = np.concatenate([bg_data, pat_data], axis=0)
    hit_mask = np.concatenate([bg_hit_mask, pat_hit_mask])
    return data, bg_count + pat_count, hit_mask, all_match, view_mode, boundary_radius


# ---------------------------------------------------------------------------
# Load Range: switch to a FIXED ring set (a slice of already-loaded primes
# in [from, to]), independent of N, mirroring
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
# Tracked-ring outline circles, birth/resonance flash overlays, center
# marker. Ports DrumRenderer.draw's `if (ring.tracked) {...}` outline-stroke
# branch, #drawCenterMarker, and the #drawFlashOverlay/triggerBirthFlash/
# triggerResonanceFlash trio.
#
# All of the ANCHOR/COLOR math these draw calls need (compute_tracked_colors)
# already lives in ring_geometry.py -- the only new pure-math surface here is
# the small amount below that is specific to the GL layer itself (unit-circle
# geometry, screen-space marker offsets, flash decay/alpha), kept as plain
# functions so it can be unit-tested without a GPU (see run()'s own GL
# wiring further down for the untestable-without-a-display half of this).
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

    `anchor_overrides` -- forwarded verbatim to
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
_FLASH_PATTERN_RGB = (0.0, 230.0, 118.0)    # same green as _LINE_MATCH_RGB -- line mode, full pattern match
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
    """Shared (N, 6) float32 (pos.xy, color.rgba) stamper for the small,
    flat-colored screen-space shapes drawn via SCREEN_VERTEX_SHADER --
    build_center_marker_vertex_data's triangle/line and
    build_flash_quad_vertex_data's quad both use this same (N, 6) layout;
    every vertex in one call shares the same `rgba`, only its (x, y)
    position differs."""
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

    The vertex shader computes
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
    it is tall. Using min(width, height) as the constraint is exactly that
    rule: whichever dimension is the tighter one is the one the (roughly
    circular) ring field gets fit against, so it's never clipped on either
    axis.

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

    For --source sieve/archive, the user has a real target N in mind
    (rings_tab.py's N field, passed through verbatim as --upto) -- the view
    must open exactly there, not on whatever the last loaded prime happens
    to be. ring_positions() computes is_hit as n % prime == 0 (real divisors
    of N), so N is not required to be prime itself; snapping to primes[-1]
    would silently show the wrong number (e.g. typing 1000 would open on
    N=997, the largest prime <=1000, with "Factors of N: 997" -- itself,
    since 997 is prime -- instead of 1000's real factors 2 and 5).

    --source synthetic has no user-specified target N at all (only --count,
    an arbitrary ring COUNT -- see load_synthetic's own docstring), so there
    is no "the value the user asked for" to open on; it keeps using the last
    generated value instead."""
    if source == "synthetic":
        return int(primes[-1]) if len(primes) else 0
    return upto
