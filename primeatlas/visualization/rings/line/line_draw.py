"""
line_draw.py -- pure, GL-context-free vertex data for the line mode: the prime
dot row on a straight, ring-bent or spiral axis with the sliding k-tuple pattern,
the curved-axis boundary marker, and the pattern-match flash color.

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

from primeatlas.visualization.shared.bigint import to_prime_array
from primeatlas.visualization.rings.line.line_geometry import (
    line_view_bounds, line_positions_windowed, line_positions_windowed_ring,
    line_positions_windowed_spiral, value_to_line_x, value_to_ring_axis_xy, value_to_spiral_xy,
    spiral_outer_radius, pattern_positions_and_match,
)


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

    `curved` -- a PURELY visual choice between laying the same lo/span-mapped
    positions out on a straight line (y=0, the default) or bent into a circle
    (line_positions_windowed_ring/value_to_ring_axis_xy). Does not touch which
    positions are computed, which count as a match, or any navigation/wheel/seek
    logic -- those operate on the same `n`/`offsets`/`primes_set` either way.

    `wheel_modulus` -- when `curved` AND this is a real wheel modulus
    (> 1, i.e. ring_geometry.pattern_wheel_residues actually found one --
    see RenderSession's own `self.pattern_wheel_modulus`), the curved
    layout becomes a SPIRAL instead of a single circle
    (line_positions_windowed_spiral/value_to_spiral_xy): each full
    `wheel_modulus`-sized chunk of the axis gets its own lap, at a bigger
    radius than the previous one, so a window spanning multiple wheel
    periods shows that structure directly instead of always normalizing
    the whole window onto one loop: a range shorter than one period gives an
    incomplete circle, several periods a multi-lap spiral. None or <= 1 (no
    pattern set, or a pattern whose wheel excludes nothing) falls back to the
    plain single-circle layout.

    `primes_set` -- optional pre-built `set(int(v) for v in range_primes)`
    for the match check below; a caller holding `range_primes` fixed
    across many calls (RenderSession, whose own `_pattern_primes_set` is
    already built once at construction for the wheel/founding-coincidence
    logic) should pass it through here too, instead of this function
    silently rebuilding the same set from scratch on every single N-change
    -- a real cost once `range_primes` is a real archive-scale array.
    Built fresh when omitted.

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
_FLASH_PATTERN_RGB = (0.0, 230.0, 118.0)    # same green as _LINE_MATCH_RGB -- line mode, full pattern match
