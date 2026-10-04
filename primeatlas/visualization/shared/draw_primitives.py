"""
draw_primitives.py -- pure, GL-context-free geometry shared by every visualization:
the hit/normal vertex-buffer split, the unit circle, the center marker and
flash-overlay shapes and their decay, and camera zoom-to-cursor/fit-to-viewport
math. Plain arrays/scalars in, plain arrays/tuples out -- no moderngl/glfw call, so
every function is unit-testable without a GPU/display.
"""

import numpy as np


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
    Multiplying zoom alone would leave world position (0,0) -- the ring field's
    mathematical center -- pinned to whatever screen point `pan` is, regardless of
    the cursor or viewport center, so every zoom would anchor on the ring field's
    center (zooming in on a panned-to tail would race back toward the center).

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
