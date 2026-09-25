"""
test_ring_viz_pattern_mode.py -- tests for the "line" viz-mode k-tuple
pattern-slide feature added to primeatlas/rings/ring_viz/: the pure
offset-derivation/geometry functions in ring_geometry.py, the vertex-data
builder in geometry_draw.py, and RenderSession's line-mode state in
session.py. No moderngl/glfw import anywhere -- same "pure logic, GPU-free"
convention as every other ring_viz test in this folder.

Usage: python unitTests\\test_ring_viz_pattern_mode.py
"""
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _test_next_prime_at_or_above():
    from primeatlas.rings.ring_geometry import next_prime_at_or_above

    check(next_prime_at_or_above(2) == 2, "next_prime_at_or_above(2) == 2 (already prime)")
    check(next_prime_at_or_above(4) == 5, "next_prime_at_or_above(4) == 5")
    check(next_prime_at_or_above(11) == 11, "next_prime_at_or_above(11) == 11 (already prime)")
    check(next_prime_at_or_above(24) == 29, "next_prime_at_or_above(24) == 29")


def _test_pattern_offsets_from_seed():
    from primeatlas.rings.ring_geometry import pattern_offsets_from_seed

    # Regression anchors: these must match constellation/pattern_catalog_v1.py's
    # own catalog entries exactly, since both this function and the catalog
    # describe the SAME real prime clusters (11,13,17,19,23,29,31 and 5,7,11).
    check(pattern_offsets_from_seed(7, 11) == [0, 2, 6, 8, 12, 18, 20],
          "pattern_offsets_from_seed(7, 11) matches catalog k=7 id=1")
    check(pattern_offsets_from_seed(3, 5) == [0, 2, 6],
          "pattern_offsets_from_seed(3, 5) matches catalog k=3")
    check(pattern_offsets_from_seed(2, 5) == [0, 2],
          "pattern_offsets_from_seed(2, 5) == [0, 2] (twin primes 5,7)")

    # p0 need not itself be prime -- treated as a lower bound.
    check(pattern_offsets_from_seed(3, 4) == pattern_offsets_from_seed(3, 5),
          "a non-prime seed start is treated as a lower bound (next real prime >= p0)")

    try:
        pattern_offsets_from_seed(1, 5)
        check(False, "pattern_offsets_from_seed(k=1, ...) should reject k < 2")
    except ValueError:
        check(True, "pattern_offsets_from_seed(k=1, ...) raises ValueError")

    try:
        pattern_offsets_from_seed(3, 2)
        check(False, "pattern_offsets_from_seed(..., p0=2) should reject p0 <= 2")
    except ValueError:
        check(True, "pattern_offsets_from_seed(..., p0=2) raises ValueError")


def _test_line_positions_and_value_to_line_x():
    from primeatlas.rings.ring_geometry import line_positions, value_to_line_x
    import numpy as np

    primes = np.array([11, 13, 17, 19, 23], dtype=np.int64)
    line = line_positions(primes, world_width=1000.0)
    check(len(line["x"]) == 5, "line_positions returns one x per input prime")
    check(all(y == 0.0 for y in line["y"]), "line_positions places every dot at y=0")
    check(line["x"][0] < line["x"][-1], "line_positions x is ascending for ascending primes")
    check(abs(line["x"][0] - (-500.0)) < 1e-6, "first prime maps to the left edge of world_width")
    check(abs(line["x"][-1] - 500.0) < 1e-6, "last prime maps to the right edge of world_width")

    mid_x = value_to_line_x(17, line["lo"], line["span"], 1000.0)
    check(abs(mid_x - line["x"][2]) < 1e-6,
          "value_to_line_x reproduces line_positions' own mapping for a value already in the array")


def _test_line_positions_archive_scale_precision():
    """Regression (2026-09-18, Artur's own real report against a real
    26-digit --load-range: "the space is empty ... only two points
    travel, not three, for the chosen k3"): line_positions used to cast
    to float64 BEFORE subtracting `lo`, so at real floor-25+ archive
    scale (~26-digit values), each value's own float64 rounding error
    (up to ~value * 2**-52, here ~2.7e9) dwarfed the whole loaded
    window's actual span (~1.15e8), collapsing every point -- including
    a k-tuple pattern's own few-unit-wide members -- onto the same pixel.
    Fixed to subtract in exact integer arithmetic first."""
    from primeatlas.rings.ring_geometry import line_positions
    import numpy as np

    base = 12345678901234567890000023
    primes = np.array([base + i for i in (0, 5507, 100000, 115514730)], dtype=object)
    pos = line_positions(primes, world_width=1600.0)
    check(len(set(pos["x"])) == 4,
          f"four values spanning a real 26-digit archive window each map to a DISTINCT x position, "
          f"not collapsed by float64 precision loss (got {pos['x']})")
    check(abs(pos["x"][0] - (-800.0)) < 1e-6, "the smallest value still maps to the left edge exactly")
    check(abs(pos["x"][-1] - 800.0) < 1e-6, "the largest value still maps to the right edge exactly")


def _test_value_to_ring_axis_xy():
    """Spec for ring_geometry.value_to_ring_axis_xy (2026-09-18, Artur's
    own follow-up: "wizualne zwinięcie w pierścień ... początkiem i
    końcem będzie pionowa linia czerwona" -- a purely visual curved-axis
    layout, values keep their exact linear order, only the on-screen
    shape bends into a circle). t=0 (value==lo) and t=1 (value==lo+span)
    must coincide at the exact same point -- the seam a real, non-cyclic
    loaded range needs a boundary marker for."""
    from primeatlas.rings.ring_geometry import value_to_ring_axis_xy
    import math

    lo, span, radius = 1000, 2000, 800.0

    x0, y0 = value_to_ring_axis_xy(lo, lo, span, radius)
    check(abs(x0 - 0.0) < 1e-9, f"t=0 sits at x=0 (12 o'clock), got x={x0}")
    check(abs(y0 - (-radius)) < 1e-9, f"t=0 sits at y=-radius (12 o'clock), got y={y0}")

    x1, y1 = value_to_ring_axis_xy(lo + span, lo, span, radius)
    check(abs(x1 - x0) < 1e-9 and abs(y1 - y0) < 1e-9,
          f"t=1 (value=lo+span) coincides EXACTLY with t=0 -- the seam (got ({x1},{y1}) vs ({x0},{y0}))")

    xh, yh = value_to_ring_axis_xy(lo + span / 2, lo, span, radius)
    check(abs(xh - 0.0) < 1e-9 and abs(yh - radius) < 1e-9,
          f"t=0.5 sits diametrically opposite the seam, at (0, +radius) (got ({xh},{yh}))")

    for t in (0.1, 0.3, 0.7, 0.9):
        value = lo + t * span
        x, y = value_to_ring_axis_xy(value, lo, span, radius)
        dist = math.hypot(x, y)
        check(abs(dist - radius) < 1e-6, f"every mapped point lies exactly on the circle of radius {radius} (t={t}, got dist={dist})")


def _test_line_positions_windowed_ring():
    """Spec for ring_geometry.line_positions_windowed_ring: same [lo, lo+span]
    binary-search filter as line_positions_windowed, but each surviving
    value is placed via value_to_ring_axis_xy's circular math instead of a
    straight y=0 row."""
    from primeatlas.rings.ring_geometry import line_positions_windowed_ring, value_to_ring_axis_xy
    import numpy as np
    import math

    primes = np.array([5, 11, 13, 17, 19, 23, 29, 1000], dtype=np.int64)
    win = line_positions_windowed_ring(primes, lo=10, span=20, radius=800.0)
    check(len(win["x"]) == 6, f"same filtering as the straight variant: 6 values inside [10, 30] (got {len(win['x'])})")
    check(win["lo"] == 10 and win["span"] == 20, "line_positions_windowed_ring reports back the CALLER's own lo/span")
    check(any(abs(y) > 1e-6 for y in win["y"]),
          f"the curved layout genuinely uses non-zero y (unlike the straight layout) (got y={win['y']})")

    for x, y in zip(win["x"], win["y"]):
        dist = math.hypot(x, y)
        check(abs(dist - 800.0) < 1e-6, f"every background dot lies exactly on the circle (got dist={dist})")

    expected_x, expected_y = value_to_ring_axis_xy(11, 10, 20, 800.0)
    check(abs(win["x"][0] - expected_x) < 1e-6 and abs(win["y"][0] - expected_y) < 1e-6,
          "line_positions_windowed_ring's own mapping matches value_to_ring_axis_xy for the same lo/span")


def _test_value_to_spiral_xy():
    """Spec for ring_geometry.value_to_spiral_xy (2026-09-19, Artur's own
    spiral follow-up): each `period`-sized chunk of the axis gets its own
    lap at a bigger radius; every lap's own phase-zero point (value ≡ lo
    mod period) lands at the SAME angle (-pi/2) regardless of which lap,
    only the radius differs -- this is what lets a single straight radial
    line mark phase-zero on every lap at once."""
    from primeatlas.rings.ring_geometry import value_to_spiral_xy
    import math

    lo, period, base_radius, pitch = 1000, 100, 800.0, 800.0

    x0, y0 = value_to_spiral_xy(lo, lo, period, base_radius, pitch)
    check(abs(x0 - 0.0) < 1e-9 and abs(y0 - (-base_radius)) < 1e-9,
          f"lap 0, phase 0 sits at (0, -base_radius) (got ({x0},{y0}))")

    x1, y1 = value_to_spiral_xy(lo + period, lo, period, base_radius, pitch)
    check(abs(x1 - 0.0) < 1e-9 and abs(y1 - (-(base_radius + pitch))) < 1e-9,
          f"lap 1, phase 0 sits at the SAME angle, one pitch further out (got ({x1},{y1}))")

    x2, y2 = value_to_spiral_xy(lo + 2 * period, lo, period, base_radius, pitch)
    check(abs(x2 - 0.0) < 1e-9 and abs(y2 - (-(base_radius + 2 * pitch))) < 1e-9,
          f"lap 2, phase 0 sits at the SAME angle again, two pitches further out (got ({x2},{y2}))")

    # A value halfway through lap 1's own period sits diametrically
    # opposite lap 1's own phase-zero point, at lap 1's own radius.
    xh, yh = value_to_spiral_xy(lo + period + period // 2, lo, period, base_radius, pitch)
    check(abs(xh - 0.0) < 1e-6 and abs(yh - (base_radius + pitch)) < 1e-6,
          f"lap 1's own halfway point sits at (0, +radius_of_lap_1) (got ({xh},{yh}))")

    for value, expected_lap in ((lo + 5, 0), (lo + period + 5, 1), (lo + 4 * period + 5, 4)):
        x, y = value_to_spiral_xy(value, lo, period, base_radius, pitch)
        dist = math.hypot(x, y)
        expected_radius = base_radius + expected_lap * pitch
        check(abs(dist - expected_radius) < 1e-6,
              f"value in lap {expected_lap} lands at that lap's own radius (got dist={dist}, expected={expected_radius})")


def _test_line_positions_windowed_spiral():
    from primeatlas.rings.ring_geometry import line_positions_windowed_spiral, value_to_spiral_xy
    import numpy as np
    import math

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47], dtype=np.int64)
    period, base_radius, pitch = 10, 800.0, 800.0
    win = line_positions_windowed_spiral(primes, lo=2, span=45, period=period, base_radius=base_radius, pitch=pitch)
    check(len(win["x"]) == len(primes), "every value in [2, 47] is kept (span exactly covers the whole array)")

    radii = [math.hypot(x, y) for x, y in zip(win["x"], win["y"])]
    distinct_radii = sorted(set(round(r, 6) for r in radii))
    check(len(distinct_radii) > 1,
          f"a window spanning multiple periods produces MULTIPLE distinct lap radii, not just one circle (got {distinct_radii})")
    check(min(distinct_radii) == base_radius,
          f"the innermost lap sits at exactly base_radius (got {min(distinct_radii)})")

    expected_x, expected_y = value_to_spiral_xy(37, 2, period, base_radius, pitch)
    idx = list(primes).index(37)
    check(abs(win["x"][idx] - expected_x) < 1e-6 and abs(win["y"][idx] - expected_y) < 1e-6,
          "line_positions_windowed_spiral's own mapping matches value_to_spiral_xy for the same lo/period")


def _test_spiral_outer_radius():
    from primeatlas.rings.ring_geometry import spiral_outer_radius

    check(spiral_outer_radius(span=5, period=10, base_radius=800.0, pitch=800.0) == 800.0,
          "a span smaller than one period stays at the innermost (lap 0) radius")
    check(spiral_outer_radius(span=10, period=10, base_radius=800.0, pitch=800.0) == 1600.0,
          "a span exactly one period reaches lap 1's own radius")
    check(spiral_outer_radius(span=35, period=10, base_radius=800.0, pitch=800.0) == 800.0 + 3 * 800.0,
          "a span of 3.5 periods reaches lap 3's own radius (floor division)")
    check(spiral_outer_radius(span=0, period=10, base_radius=800.0, pitch=800.0) == 800.0,
          "a degenerate zero span still returns the innermost radius, not a crash")


def _test_build_line_vertex_data_spiral():
    """Spec for build_line_vertex_data's `wheel_modulus` parameter: once a
    real wheel is given (modulus > 1) AND curved=True, the layout promotes
    from a single circle to a spiral -- multiple distinct lap radii for a
    window spanning multiple periods, and the boundary_radius reaching the
    outermost lap actually drawn (spiral_outer_radius's own value, not the
    plain world_width/2)."""
    from primeatlas.rings.ring_viz.geometry_draw import build_line_vertex_data
    from primeatlas.rings.ring_geometry import spiral_outer_radius
    import numpy as np
    import math

    # A synthetic "range_primes" spanning 4+ periods of a small, ARBITRARY
    # test modulus (10) -- doesn't need to be a real wheel value, since
    # build_line_vertex_data trusts whatever wheel_modulus its caller
    # (RenderSession) already computed, same as it already trusts a
    # caller-supplied primes_set.
    range_primes = np.array([2 + i for i in range(0, 45, 3)], dtype=np.int64)  # 2..44 step 3
    modulus = 10

    data, count, hit_mask, all_match, view_mode, boundary_radius = build_line_vertex_data(
        range_primes, 2, [], curved=True, wheel_modulus=modulus
    )
    radii = [math.hypot(float(x), float(y)) for x, y in zip(data[:, 0], data[:, 1])]
    distinct_radii = sorted(set(round(r, 6) for r in radii))
    check(len(distinct_radii) > 1,
          f"a real wheel_modulus promotes the layout to a spiral: multiple lap radii, not one circle (got {distinct_radii})")

    span = int(range_primes[-1]) - int(range_primes[0])
    expected_outer = spiral_outer_radius(span, modulus, 800.0, 800.0)
    check(boundary_radius == expected_outer,
          f"boundary_radius matches spiral_outer_radius's own computation for this window (got {boundary_radius}, expected {expected_outer})")
    check(boundary_radius > 800.0, "the spiral's outer radius reaches further out than a plain single circle would")

    # wheel_modulus <= 1 (no real wheel, e.g. an unset/dead pattern) must
    # fall back to the plain single-circle layout, unchanged.
    _d, _c, _h, _m, _v, boundary_radius_flat = build_line_vertex_data(
        range_primes, 2, [], curved=True, wheel_modulus=1
    )
    check(boundary_radius_flat == 800.0, "wheel_modulus<=1 falls back to the plain-circle boundary radius")


def _test_axis_boundary_marker_vertices():
    from primeatlas.rings.ring_viz.geometry_draw import axis_boundary_marker_vertices
    import numpy as np

    verts = axis_boundary_marker_vertices()
    check(verts.shape == (2, 2), f"boundary marker is a 2-vertex (center, edge) segment (got shape {verts.shape})")
    check(verts.dtype == np.float32, f"boundary marker vertices are float32, ready for a GL buffer (got {verts.dtype})")
    check(tuple(verts[0]) == (0.0, 0.0), f"first vertex is the circle's own center (got {tuple(verts[0])})")
    check(tuple(verts[1]) == (0.0, -1.0), f"second vertex is the unit-radius '12 o'clock' edge point (got {tuple(verts[1])})")


def _test_pattern_positions_and_match():
    from primeatlas.rings.ring_geometry import pattern_positions_and_match

    primes_set = {11, 13, 17, 19, 23, 29, 31}
    positions, hits, all_match = pattern_positions_and_match(11, [0, 2, 6, 8, 12, 18, 20], primes_set)
    check(positions == [11, 13, 17, 19, 23, 29, 31], "pattern_positions_and_match computes n+offset positions")
    check(all(hits), "every position is a hit when the pattern is anchored at its own real occurrence")
    check(all_match is True, "all_match is True when every offset lands on a real prime")

    positions2, hits2, all_match2 = pattern_positions_and_match(12, [0, 2, 6], primes_set)
    check(hits2 == [False, False, False], "anchoring one past a real cluster gives all misses here")
    check(all_match2 is False, "all_match is False when not every offset hits")

    _, _, all_match_empty = pattern_positions_and_match(11, [], primes_set)
    check(all_match_empty is False, "all_match is False (not vacuously True) for an empty offset list")


def _test_clamp_pattern_anchor():
    from primeatlas.rings.ring_geometry import clamp_pattern_anchor

    check(clamp_pattern_anchor(5, 100, 200, [0, 2, 6]) == 100,
          "clamp_pattern_anchor pulls n up to range_from when it's below the window")
    check(clamp_pattern_anchor(199, 100, 200, [0, 2, 6]) == 194,
          "clamp_pattern_anchor pulls n down so n+offsets[-1] never exceeds range_to")
    check(clamp_pattern_anchor(150, 100, 200, [0, 2, 6]) == 150,
          "clamp_pattern_anchor leaves n unchanged when already inside bounds")
    check(clamp_pattern_anchor(150, 100, 200, []) == 150,
          "clamp_pattern_anchor is a no-op with no pattern offsets")


def _test_pattern_wheel_residues():
    from primeatlas.rings.ring_geometry import pattern_wheel_residues

    # {0,2} (twin primes): classic "n == 5 mod 6" result -- every twin
    # prime pair above (3,5) has the smaller member of that exact form.
    modulus, residues = pattern_wheel_residues([0, 2], wheel_primes=(2, 3))
    check(modulus == 6, f"pattern_wheel_residues([0,2], (2,3)) modulus == 6 (got {modulus})")
    check(residues == [5], f"pattern_wheel_residues([0,2], (2,3)) residues == [5] (got {residues})")

    # {0,2,6} (catalog k=3): same 5-mod-6 result -- both 5,7,11 and
    # 11,13,17 (n=5 and n=11, one full period apart) are real occurrences.
    modulus2, residues2 = pattern_wheel_residues([0, 2, 6], wheel_primes=(2, 3))
    check(residues2 == [5], f"pattern_wheel_residues([0,2,6], (2,3)) residues == [5] (got {residues2})")

    # {0,2,4} (3,5,7's own pattern): mod 3, offsets cover ALL THREE
    # residues (0,2,4 mod 3 == 0,2,1) -- this pattern can NEVER repeat
    # past its own founding coincidence at n=3 (see shift_correlation_
    # experiment_v1.py's own empirical finding of the exact same fact).
    modulus3, residues3 = pattern_wheel_residues([0, 2, 4], wheel_primes=(2, 3))
    check(residues3 == [], f"pattern_wheel_residues([0,2,4], (2,3)) residues == [] -- dead pattern (got {residues3})")

    # A prime that excludes nothing is dropped from the wheel entirely
    # rather than needlessly inflating the modulus.
    modulus4, residues4 = pattern_wheel_residues([0, 2], wheel_primes=(2,))
    check(modulus4 == 2, f"pattern_wheel_residues([0,2], (2,)) modulus == 2 (got {modulus4})")


def _test_next_wheel_n():
    from primeatlas.rings.ring_geometry import next_wheel_n

    # Wheel from {0,2,6}: residues=[5], modulus=6 -- exactly one
    # candidate per period of 6.
    check(next_wheel_n(5, True, 6, [5], 0, 100) == 11,
          "next_wheel_n jumps a full period forward (5 -> 11), skipping 6..10 entirely")
    check(next_wheel_n(11, False, 6, [5], 0, 100) == 5,
          "next_wheel_n jumps a full period backward (11 -> 5)")
    check(next_wheel_n(5, True, 6, [5], 0, 10) == 5,
          "next_wheel_n returns n unchanged when the next candidate would exceed hi")
    check(next_wheel_n(5, True, 6, [], 0, 100) == 5,
          "next_wheel_n always returns n unchanged for an empty (dead-pattern) residue set")

    # Regression (2026-09-18, Artur's own real report: "the jump in the
    # period is shifted"): residues are ABSOLUTE n-mod-modulus conditions,
    # so `lo` must be a pure window bound, never a phase reference -- the
    # candidate sequence for {0,2} (residues=[5], modulus=6, i.e. the
    # classic twin-prime "n == 5 mod 6") must come out the same
    # regardless of where the search window happens to start.
    check(next_wheel_n(3, True, 6, [5], 0, 100) == 5,
          "next_wheel_n(3, lo=0) finds the real next twin-prime candidate, n=5")
    check(next_wheel_n(3, True, 6, [5], 2, 100) == 5,
          "next_wheel_n(3, lo=2 -- NOT a multiple of 6) still finds n=5, not shifted by lo")
    check(next_wheel_n(29, True, 6, [5], 2, 100) == 35,
          "next_wheel_n continues the SAME 5,11,17,23,29,35,... sequence regardless of lo")


def _sieve_primes_upto(n):
    is_composite = bytearray(n + 1)
    primes = []
    for p in range(2, n + 1):
        if not is_composite[p]:
            primes.append(p)
            if p * p <= n:
                is_composite[p * p:n + 1:p] = b"\x01" * len(range(p * p, n + 1, p))
    return primes


def _test_pattern_step_mode_and_stop_on_match():
    """Artur's own 2026-09-18 spec (corrected after a real report -- his
    first phrasing of this was mis-implemented as "auto+unchecked = single
    step", not seek-for-non-match; his own real k=6 sequence 7 -> 97 -> 1357
    (7 and 97 are both real matches, 1357 isn't) is what exposed it): a
    Manual/Auto radio (`pattern_step_mode`) plus a "MATCH!" checkbox
    (`pattern_stop_on_match`) -- "manual" ALWAYS takes a single wheel step,
    showing every candidate whether it's a match or not, regardless of the
    checkbox; "auto" ALWAYS seeks -- for the next real MATCH! when checked,
    or specifically for the next NON-match when unchecked (skipping real
    matches on the way, e.g. 97 here). k=6 offsets [0,4,6,10,12,16] seeded
    at p0=7 is Artur's own real example, verified here against a real
    sieve rather than just re-asserting whatever _pattern_seek itself would
    compute."""
    from primeatlas.rings.ring_viz.session import RenderSession
    import numpy as np

    range_primes = np.array(_sieve_primes_upto(1400), dtype=np.int64)

    def make_session(step_mode, stop_on_match):
        return RenderSession(
            primes=range_primes, n=7, ceiling=10000, range_mode=True,
            range_primes=range_primes, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=False,
            portal_folder=None, viz_mode="line", pattern_offsets=[0, 4, 6, 10, 12, 16],
            pattern_step_mode=step_mode, pattern_stop_on_match=stop_on_match,
        )

    manual_off = make_session("manual", False)
    check(manual_off._pattern_uses_seek() is False, "manual mode never seeks, regardless of the checkbox")
    manual_off.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    check(manual_off.n == 97, f"manual + unchecked takes a single wheel step, 7 -> 97 (got {manual_off.n})")

    manual_on = make_session("manual", True)
    check(manual_on._pattern_uses_seek() is False,
          "manual mode ALSO never seeks with the checkbox CHECKED -- the radio is the master switch")
    manual_on.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    check(manual_on.n == 97, f"manual + checked still takes a single wheel step, 7 -> 97 (got {manual_on.n})")

    auto_on = make_session("auto", True)
    check(auto_on._pattern_uses_seek() is True, "auto mode always seeks")
    auto_on.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    check(auto_on.n == 97, f"auto + checked seeks the next real MATCH!, which is 97 -- the very first "
                           f"wheel candidate already qualifies (got {auto_on.n})")

    auto_off = make_session("auto", False)
    check(auto_off._pattern_uses_seek() is True, "auto mode always seeks, checkbox unchecked too")
    auto_off.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    check(auto_off.n == 1357,
          f"auto + unchecked seeks the next NON-match, skipping straight OVER the real match at 97 "
          f"(a wheel candidate, but not what was asked for) to land on 1357 (got {auto_off.n})")

    # tick() and bump_n must agree with scrub_advance on the same regime.
    auto_off_tick = make_session("auto", False)
    auto_off_tick.playback_running = True
    stopped = auto_off_tick.tick()
    check(stopped is False, "tick() in seek-non-match mode doesn't stop playback just because it skipped a match")
    check(auto_off_tick.n == 1357, f"tick() in seek-non-match mode also skips 97, landing on 1357 (got {auto_off_tick.n})")

    auto_off_bump = make_session("auto", False)
    auto_off_bump.bump_n(1000)
    check(auto_off_bump.n == 1357,
          f"bump_n in seek-non-match mode also skips 97, ignoring its own delta magnitude (got {auto_off_bump.n})")


def _test_pattern_seek_has_no_artificial_step_cap():
    """Regression (2026-09-25, Artur's real report, ROUND TWO -- his own
    correction of a first attempted fix): --pattern-stop-on-match's seek
    used to give up after a fixed _PATTERN_SEEK_MAX_STEPS (50,000) "safety
    bound" and land on a bare non-match wheel candidate ("mimo zaznaczonego
    match! potrafi zatrzymac sie na wheel"). A FIRST fix made bump_n/
    scrub_advance/tick refuse to move at all once that budget was
    exhausted -- Artur's own correction: that just froze playback/scrub
    entirely at real archive scale, where a genuine match can legitimately
    need MORE than 50,000 wheel-hops. His actual spec: "przy zatrzymaniu
    niech nastapi weryfikacja czy jest match i czy jest zaznaczone match!
    jesli nie niech idzie dalej" -- at a stop, verify whether it's a match
    and whether MATCH! is checked; if not, keep going. That's exactly what
    _pattern_seek's own loop already did per-candidate -- the ONLY bug was
    the artificial cap cutting that loop short. Fix: removed the cap
    entirely; the loop's only termination conditions now are finding the
    desired kind, or _pattern_wheel_step reporting the genuine window edge
    (see _pattern_seek's own updated doc-comment for why that still always
    terminates).

    Proves the "many steps before a real match" half of this directly: a
    real match is manually placed 500 wheel-hops from the anchor (past any
    small-cap philosophy) in an otherwise permanently-synthetic-non-
    matching loaded range, and the seek must still reach it."""
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_geometry import pattern_positions_and_match
    import numpy as np

    base_values = [6 * k + 1 for k in range(1, 20000)]  # only == 1 mod 6 -- never a match on its own

    def make_session(extra_values=()):
        values = sorted(set(base_values) | set(extra_values))
        range_primes = np.array(values, dtype=np.int64)
        session = RenderSession(
            primes=range_primes, n=11, ceiling=1_000_000, range_mode=True,
            range_primes=range_primes, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=False,
            portal_folder=None, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
        )
        return session, range_primes

    # Walk 500 real wheel-hops forward from the anchor via plain single steps
    # (bypassing _pattern_seek itself) to find a concrete, deep candidate.
    probe_session, _ = make_session()
    target = 11
    for _ in range(500):
        target = probe_session._pattern_wheel_step(target, True)
    check(target != 11, "test setup: 500 wheel-hops actually moved somewhere")

    matched_session, range_primes = make_session(extra_values=(target, target + 2))
    _positions, _hits, all_match = pattern_positions_and_match(
        target, [0, 2], set(int(v) for v in range_primes))
    check(all_match is True, "test setup: the manually-inserted pair really is a match")

    matched_session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    check(matched_session.n == target,
          f"_pattern_seek reaches a real match 500 wheel-hops away instead of giving up early "
          f"(expected {target}, got {matched_session.n})")


def _test_pattern_seek_stays_on_last_real_match_at_genuine_window_edge():
    """Companion to the "no artificial cap" test above, and Artur's own
    follow-up correction (2026-09-25): "jesli w nastepnym kroku jest
    bledne a kolejnego nie ma bo koniec zakresu to zostaje na ostatnim
    poprawnym" -- if the next step is wrong and there's no further one
    because the range ended, stay on the last CORRECT one. A first version
    of this fix let tick()/bump_n/scrub_advance apply _pattern_seek's own
    `new_n` even when it returned found=False -- landing on the last
    non-match wheel candidate reached on the way to the edge, not on the
    last real match. tick()/bump_n/scrub_advance must now discard that
    non-match landing and leave `n` exactly where it was (the last
    confirmed MATCH!) when the seek can't find another one before running
    out of loaded window.

    Built with the same "only == 1 mod 6" synthetic base as the no-cap
    test (guarantees zero INCIDENTAL matches), plus exactly ONE real match
    manually inserted at the anchor itself (n=11, by adding 11 to the set
    -- its partner 13 == 1 mod 6 is already there) -- so there is a real
    "last correct" position to stay on, and definitively no further one
    anywhere ahead of it in this tiny window."""
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_geometry import pattern_positions_and_match
    import numpy as np

    values = sorted(set(6 * k + 1 for k in range(1, 200)) | {11})  # tiny window, one real match at 11
    range_primes = np.array(values, dtype=np.int64)

    def make_session():
        return RenderSession(
            primes=range_primes, n=11, ceiling=100000, range_mode=True,
            range_primes=range_primes, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=False,
            portal_folder=None, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
        )

    _positions, _hits, all_match = pattern_positions_and_match(
        11, [0, 2], set(int(v) for v in range_primes))
    check(all_match is True, "test setup: n=11 really is a genuine match")

    seek_session = make_session()
    _final_n, found = seek_session._pattern_seek(11, True)
    check(found is False, "no FURTHER real match exists ahead of 11 in this tiny window")

    tick_session = make_session()
    tick_session.playback_running = True
    stopped = tick_session.tick()
    check(stopped is True, "tick() stops immediately rather than advancing to a non-match candidate")
    check(tick_session.n == 11, f"tick() leaves n on the last real match (11), not a non-match candidate "
                                f"further along (got {tick_session.n})")

    bump_session = make_session()
    bump_session.bump_n(1000)
    check(bump_session.n == 11, f"bump_n leaves n on the last real match too (got {bump_session.n})")

    scrub_session = make_session()
    scrub_session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    check(scrub_session.n == 11, f"scrub_advance leaves n on the last real match too (got {scrub_session.n})")


# ---------------------------------------------------------------------------
# Bidirectional sliding/traveling window (chunk_back/chunk_current/
# chunk_forward) over --load-range -- see memory file
# primeatlas-ring-viz-sliding-range-window-plan.md, Faza 1/2. Needs REAL
# on-disk PGS window files (sliding does real I/O via load_archive/
# load_archive_before), same fixture convention as
# unitTests/test_ring_viz_renderer.py's own `_write_floor` helper.
# ---------------------------------------------------------------------------

def _write_floor(portal_dir, base_exponent, windows):
    """Same convention as test_ring_viz_renderer.py's own helper of this
    name -- kept as a separate local copy since these are independent
    plain-script test files (no shared test-utility import), not real
    prime data (arbitrary ascending ints), one PRIME_WINDOW_*.bin per
    `windows` entry."""
    import window_sharding
    import prime_sieve_v1

    source_dir = os.path.join(portal_dir, f"10p{base_exponent}", "source_primes")
    shard0 = window_sharding.shard_dir(source_dir, 0)
    os.makedirs(shard0, exist_ok=True)
    for i, values in enumerate(windows):
        name = f"PRIME_WINDOW_off_{i}M.bin" if i > 0 else "PRIME_WINDOW_off_0.bin"
        prime_sieve_v1.write_prime_window(os.path.join(shard0, name), values)


def _test_sliding_forward_multi_chunk_seek_finds_distant_match():
    """The actual feature this whole plan exists for: Artur's own report
    (2026-09-25) that a --load-range covering nearly a whole floor only
    ever showed "a few points" near the low end, because --max-load-count
    truncated the loaded slice to a razor-thin sliver with no way to reach
    the rest. This proves a seek can now cross MULTIPLE chunk boundaries
    in a single call (Faza 2's own "seek must swap mid-loop" requirement)
    and land on a real match several chunks past the initially-loaded one,
    instead of stopping dead at what used to be a hard buffer edge.

    Data: 70 values of the form 6k+1 (k=0..69, i.e. 1..415) -- by
    construction no two of these are ever 2 apart, so (same convention as
    the no-artificial-cap test above) every wheel-compatible candidate
    fails the [0,2] match check until it reaches a manually-inserted real
    pair. That pair (359, 361) is placed so it lands as chunk index 6's own
    FIRST element once split into chunk_size=10 chunks (verified via a
    throwaway simulation before writing this test) -- reaching it from the
    initial chunk (chunk 0) requires 6 real forward slides."""
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_viz.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        base_values = [6 * k + 1 for k in range(0, 70)]
        target = 359
        all_values = sorted(set(base_values) | {target, target + 2})
        check(all_values[60] == target,
              f"test setup: target lands exactly at chunk index 6's own first element "
              f"(got index of {target}: {all_values.index(target)})")
        _write_floor(portal_dir, 0, [all_values])

        chunk_size = 10
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)
        check(len(initial_chunk) == chunk_size, "test setup: the initial chunk loaded exactly chunk_size values")

        session = RenderSession(
            primes=initial_chunk, n=1, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )
        check(session.sliding_enabled is True, "sliding_enabled turns on when every required kwarg is given")
        check(session.chunk_back is not None and len(session.chunk_back) == 0,
              "chunk_back is confirmed empty (not None/unattempted) at the true start of range_load_from")
        check(session.chunk_forward is not None and len(session.chunk_forward) > 0,
              "chunk_forward is EAGERLY preloaded at construction, not left as None until first needed")

        session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
        # With sliding enabled, a multi-chunk seek now runs on a background
        # thread (see _start_pattern_seek's own doc-comment, 2026-09-25
        # follow-up) instead of blocking this call -- join it before
        # asserting the outcome, same as a real caller waits via the main
        # loop's own n_force_rebuild-triggered rebuild.
        check(session._seek_thread is not None, "test setup: the seek actually moved to a background thread")
        session._seek_thread.join(timeout=5)
        check(session._seek_thread is None, "the seek thread clears itself once the search resolves")
        check(session.n == target,
              f"a single scrub_advance call crosses multiple chunk boundaries and reaches a real "
              f"match several chunks away (expected {target}, got {session.n})")
        check(int(session.chunk_current[0]) == target,
              f"chunk_current itself has slid forward so the found match is its own first element "
              f"(got chunk_current[0]={int(session.chunk_current[0]) if len(session.chunk_current) else None})")
        check(target in session._pattern_primes_set and (target + 2) in session._pattern_primes_set,
              "the matched pair is present in the rebuilt _pattern_primes_set after sliding")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_backward_swap_mirror():
    """Mirror of the forward slide: _slide_backward swaps chunk_current
    into chunk_forward, promotes chunk_back into chunk_current, and reloads
    a fresh chunk_back via load_archive_before -- called directly (not via
    a full wheel-seek) since the forward test above already proves the
    higher-level integration; this pins the backward primitive itself."""
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_viz.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        all_values = [6 * k + 1 for k in range(0, 40)]  # 1..235, no real [0,2] matches anywhere
        _write_floor(portal_dir, 0, [all_values])

        chunk_size = 10
        # Start on the SECOND chunk (values[10:20]) so there's real data
        # both behind and ahead of the initial window.
        second_chunk = load_archive(portal_dir, upto=1000, from_n=all_values[9], max_load_count=chunk_size)
        check(list(second_chunk) == all_values[10:20], "test setup: second_chunk is exactly values[10:20]")

        session = RenderSession(
            primes=second_chunk, n=int(second_chunk[0]), ceiling=100000, range_mode=True,
            range_primes=second_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=False,
            # range_load_from=0, not 1: `not_below` is EXCLUSIVE (mirrors
            # load_archive's own `from_n` convention) -- 0 sits safely below
            # every real all_values entry (which start at 1) so it never
            # collides with a real loaded value the way range_load_from=1
            # would (all_values[0] is exactly 1).
            range_load_from=0, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )
        check(list(session.chunk_current) == all_values[10:20], "chunk_current starts as the second chunk")
        check(list(session.chunk_back) == all_values[0:10],
              f"chunk_back is eagerly preloaded as the FIRST chunk at construction "
              f"(got {list(session.chunk_back)!r})")
        check(list(session.chunk_forward) == all_values[20:30],
              f"chunk_forward is eagerly preloaded as the third chunk at construction "
              f"(got {list(session.chunk_forward)!r})")

        slid = session._slide_backward()
        check(slid is True, "_slide_backward reports success when a real back chunk was available")
        check(list(session.chunk_current) == all_values[0:10],
              "chunk_back was promoted into chunk_current")
        check(list(session.chunk_forward) == all_values[10:20],
              "the old chunk_current was demoted into chunk_forward (swap, not reload)")
        # The fresh chunk_back kicked off right after the swap runs in the
        # BACKGROUND (see _ensure_back_chunk's own doc-comment) -- _slide_
        # backward itself doesn't wait for it, by design, so explicitly
        # wait here before checking its final contents (mirrors how a
        # REAL caller eventually resolves it via another _slide_backward/
        # _wait_for_back_chunk call).
        session._wait_for_back_chunk()
        check(session.chunk_back is not None and len(session.chunk_back) == 0,
              "a fresh chunk_back was loaded right after the swap and correctly found the true "
              "start of range_load_from (nothing before value 1)")

        slid_again = session._slide_backward()
        check(slid_again is False,
              "a further _slide_backward at the true start of range_load_from correctly reports no-op")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_neighbor_chunk_loads_in_background_not_blocking():
    """Regression (2026-09-25, Artur's own real report AFTER the sliding
    feature above was already committed: "przelaczenie miedzy nimi trwa
    dosc dlugo" -- switching between them takes quite a while): the FIRST
    version of _ensure_forward_chunk/_ensure_back_chunk did a plain
    synchronous load_archive/load_archive_before call, which -- since the
    real renderer's GLFW loop is single-threaded -- blocked the entire
    window for however long that disk read took, on EVERY swap, even
    though the swap itself used already-ready data. Fixed to run the
    neighbor load on a background daemon thread instead.

    Proves the actual async contract directly (not just that the final
    DATA ends up correct, which the other sliding tests above already
    cover): monkeypatches session.load_archive with an artificially slow
    stand-in, and checks that _ensure_forward_chunk returns almost
    instantly regardless (the whole point), that chunk_forward is
    genuinely still None with a real thread running immediately
    afterward (not silently already finished), and that
    _wait_for_forward_chunk both waits for and returns the real result."""
    from primeatlas.rings.ring_viz import session as session_module
    from primeatlas.rings.ring_viz.session import RenderSession
    import numpy as np
    import time

    range_primes = np.array([11, 13, 17, 19, 23], dtype=np.int64)
    session = RenderSession(
        primes=range_primes, n=11, ceiling=100000, range_mode=True,
        range_primes=range_primes, range_step=1,
        track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
        max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=False,
        portal_folder="/fake/portal", viz_mode="line", pattern_offsets=[0, 2],
        pattern_step_mode="auto", pattern_stop_on_match=True,
        range_load_from=1, range_load_to=1000, chunk_size=10, sliding_enabled=False,
    )
    # sliding_enabled is False here (portal_folder is fake, no real disk to
    # read) -- flip it on by hand purely to drive _ensure_forward_chunk
    # directly without needing a real portal on disk for this specific test.
    session.sliding_enabled = True

    real_load_archive = session_module.load_archive
    slow_load_delay = 0.3

    def _slow_load_archive(*args, **kwargs):
        time.sleep(slow_load_delay)
        return np.array([29, 31, 37], dtype=np.uint64)

    session_module.load_archive = _slow_load_archive
    try:
        t0 = time.perf_counter()
        session._ensure_forward_chunk()
        elapsed = time.perf_counter() - t0
        check(elapsed < slow_load_delay / 2,
              f"_ensure_forward_chunk returns almost instantly, NOT blocking for the load's own "
              f"{slow_load_delay}s duration (got {elapsed:.3f}s)")
        check(session.chunk_forward is None,
              "chunk_forward is genuinely still None right after kickoff -- the slow load hasn't "
              "actually finished yet, this isn't a race that happened to complete instantly")
        check(session._forward_load_thread is not None,
              "a real background thread handle is set while the load is in flight")

        session._wait_for_forward_chunk()
        check(list(session.chunk_forward) == [29, 31, 37],
              f"_wait_for_forward_chunk blocks until the background load actually finishes and "
              f"the real result is available (got {list(session.chunk_forward) if session.chunk_forward is not None else None!r})")
        check(session._forward_load_thread is None,
              "the thread handle is cleared again once the load completes")
    finally:
        session_module.load_archive = real_load_archive


def _test_sliding_disabled_by_default_without_full_wiring():
    """sliding_enabled must degrade gracefully to False -- reproducing
    today's fixed-slice behavior exactly -- whenever the caller passes
    sliding_enabled=True but omits any of the OTHER kwargs actually needed
    to do it safely (portal_folder, chunk_size, range_load_to). Every
    existing pre-sliding test in this file constructs RenderSession without
    ANY of these new kwargs at all and must keep passing unchanged (already
    proven by this file's own full run), so this specifically pins the
    "explicitly asked for it but incompletely" case, e.g. Faza 4 wiring
    landing on the GUI side before the CLI side, or vice versa."""
    from primeatlas.rings.ring_viz.session import RenderSession
    import numpy as np

    range_primes = np.array([11, 13, 17, 19, 23], dtype=np.int64)

    def make(**kwargs):
        return RenderSession(
            primes=range_primes, n=11, ceiling=100000, range_mode=True,
            range_primes=range_primes, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=False,
            portal_folder=None, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            sliding_enabled=True, **kwargs,
        )

    check(make().sliding_enabled is False, "sliding_enabled=True alone (no portal_folder/chunk_size/range_load_to) still degrades to False")
    check(make(chunk_size=10).sliding_enabled is False, "still False without a real range_load_to")
    check(make(chunk_size=10, range_load_to=1000).sliding_enabled is False,
          "still False without a real portal_folder (portal_folder=None here)")


def _test_sliding_found_false_means_true_range_edge_not_chunk_edge():
    """Core Faza 1 correctness requirement: once sliding is enabled,
    `found=False` from tick()/_pattern_seek must mean the TRUE
    range_load_to edge was reached (chunk_forward genuinely empty), not
    merely the INITIALLY loaded chunk's own edge -- the whole point of this
    feature. Uses a small range_load_to so the true edge is reachable
    quickly: no real [0,2] match exists anywhere in this data (same 6k+1
    trick), so the seek must slide all the way to the actual end of
    range_load_to and only THEN report found=False/stop, proving it didn't
    stop early at chunk 0's own boundary."""
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_viz.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        all_values = [6 * k + 1 for k in range(0, 30)]  # 1..175, no real [0,2] match anywhere
        _write_floor(portal_dir, 0, [all_values])

        chunk_size = 10
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)

        session = RenderSession(
            primes=initial_chunk, n=1, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )
        playback_session_ceiling_before_slide = int(session.chunk_current[-1])

        final_n, found = session._pattern_seek(1, True)
        check(found is False, "no real match exists anywhere in range_load_from..range_load_to")
        check(int(session.chunk_current[-1]) > playback_session_ceiling_before_slide,
              f"the search actually SLID forward past the initial chunk's own edge before giving up "
              f"(initial edge={playback_session_ceiling_before_slide}, "
              f"final chunk_current[-1]={int(session.chunk_current[-1])})")
        check(session.chunk_forward is not None and len(session.chunk_forward) == 0,
              "gives up only once chunk_forward is confirmed genuinely empty -- the TRUE range_load_to "
              "edge, not just wherever the initially-loaded chunk happened to end")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_forward_respects_range_load_to_hard_boundary():
    """Symmetric counterpart to the backward not_below fix (Artur's own
    follow-up, 2026-09-25: "to samo ograniczenie powinno byc do wartosci do
    by znow nie pojsc dalej niz ustawiony zakres" -- the same restriction
    should apply to the TO value too, so it again doesn't go further than
    the set range). Unlike backward (which needed a brand-new loader with
    no boundary awareness at all until that fix), forward sliding reuses
    load_archive(upto=range_load_to) exactly as-is, and that function has
    ALWAYS hard-bounded by `upto` (`arr <= upto`, plus a floor-level
    `floor_lo > upto: break`) -- this test exists to PROVE that already-
    correct behavior at the RenderSession/sliding level with the same
    rigor as the backward regression test, not because a bug was found
    here: floor 1 holds real data FAR beyond range_load_to, and sliding
    forward must never reach it."""
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_viz.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        floor0_values = [6 * k + 1 for k in range(0, 30)]  # 1..175
        _write_floor(portal_dir, 0, [floor0_values])
        _write_floor(portal_dir, 1, [[181, 187, 193, 199, 211]])  # real data well past range_load_to

        chunk_size = 5
        range_load_to = 49  # strictly inside floor 0's own span
        initial_chunk = load_archive(portal_dir, upto=range_load_to, max_load_count=chunk_size)
        check(list(initial_chunk) == floor0_values[:5],
              f"test setup: the initial chunk is the first 5 values (got {list(initial_chunk)!r})")

        session = RenderSession(
            primes=initial_chunk, n=1, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=0, range_load_to=range_load_to, chunk_size=chunk_size, sliding_enabled=True,
        )
        # Slide forward as many times as it'll allow -- must stop cleanly,
        # never returning a chunk containing anything > range_load_to, and
        # NEVER anything from floor 1 (181+) leaking in no matter how many
        # times we try.
        for _ in range(10):
            session._slide_forward()
        check(all(int(v) <= range_load_to for v in session.chunk_current),
              f"chunk_current never holds a value past range_load_to={range_load_to} "
              f"(got {list(session.chunk_current)!r})")
        check(all(int(v) < 181 for v in session.chunk_current),
              "not a single floor-1 value (>=181) ever leaked into chunk_current")
        check(session.chunk_forward is not None and len(session.chunk_forward) == 0,
              "chunk_forward is confirmed genuinely empty at the true range_load_to edge")

        final_n, found = session._pattern_seek(1, True)
        check(found is False, "no real match exists in this synthetic data")
        check(all(int(v) <= range_load_to for v in session.chunk_current),
              "a full seek to the genuine forward edge still never exceeds range_load_to")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_edge_reached_prints_explicit_message():
    """Artur's own explicit request, 2026-09-25: "jawna informacja jesli
    nie da sie isc dalej bo to przekroczy wartosc od albo do" -- explicit
    information when a move is refused because it would exceed FROM or TO.
    Console-output test (this module's own convention elsewhere, e.g.
    HUD/rebuild lines, already prints rather than returning strings) --
    captures stdout around a call that's already AT the genuine edge in
    each direction and checks the exact boundary value appears."""
    import contextlib
    import io
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_viz.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        all_values = [6 * k + 1 for k in range(0, 10)]  # 1..55
        _write_floor(portal_dir, 0, [all_values])

        chunk_size = 100  # bigger than the whole dataset -- one chunk covers everything
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)

        session = RenderSession(
            primes=initial_chunk, n=1, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=0, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            slid_fwd = session._slide_forward()
            slid_fwd_again = session._slide_forward()
        check(slid_fwd is False and slid_fwd_again is False, "test setup: already at the true forward edge")
        out = buf.getvalue()
        check("TO edge" in out and "1,000" in out,
              f"the forward edge message names the real TO value (got {out!r})")
        check(out.count("TO edge") == 1,
              f"the message is printed exactly ONCE, not once per repeated call at the same edge "
              f"(deduped) (got {out.count('TO edge')} times in {out!r})")

        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            slid_back = session._slide_backward()
            slid_back_again = session._slide_backward()
        check(slid_back is False and slid_back_again is False, "test setup: already at the true backward edge")
        out2 = buf2.getvalue()
        check("FROM edge" in out2 and "(0)" in out2,
              f"the backward edge message names the real FROM value (got {out2!r})")
        check(out2.count("FROM edge") == 1,
              f"the backward message is also deduped to exactly once (got {out2.count('FROM edge')} "
              f"times in {out2!r})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_edge_reached_shows_in_hud_not_just_console():
    """Artur's own direct follow-up to the console-message fix above,
    2026-09-25: "jedynie w oknie gui nic sie nie pojawia ze wstecz nie da
    sie isc dalej" -- only in the GUI window nothing appears that you
    can't go further backward. The console print alone was never enough:
    he's watching the actual GL window, not tailing console text. N
    staying unchanged at a genuine edge means renderer.py's own main-loop
    rebuild gate (`session.n != last_n`) never fires by itself, so without
    `n_force_rebuild` being set, rebuild_line (the only place that
    refreshes `hud_lines`) would never even run. Proves both halves:
    n_force_rebuild becomes True, and calling rebuild_line (as the main
    loop would) actually surfaces an edge line in hud_lines."""
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_viz.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        # 12 values, chunk_size=3: enough room for a REAL forward slide to
        # actually swap (not just hit its own edge too) -- needed so the
        # test's own final "moved away, HUD line disappears" check
        # exercises a genuine swap, not another edge-hit.
        all_values = [6 * k + 1 for k in range(0, 12)]  # 1..67
        _write_floor(portal_dir, 0, [all_values])

        chunk_size = 3
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)
        check(list(initial_chunk) == all_values[:3], "test setup: initial chunk is the first 3 values")

        session = RenderSession(
            primes=initial_chunk, n=1, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=0, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )
        session.n_force_rebuild = False  # construction may have left leftover state -- start clean

        session._slide_backward()
        check(session.n_force_rebuild is True,
              "n_force_rebuild is set the first time a genuine edge is newly reached, so "
              "renderer.py's own main loop refreshes the HUD even though N itself didn't move")

        session.rebuild_line(session.n)
        check(any("FROM edge" in line for line in session.hud_lines),
              f"rebuild_line's own hud_lines includes the FROM-edge indicator once the flag "
              f"is set, not just the console print (got {session.hud_lines!r})")

        # Sliding away from the edge clears both the flag and, on the NEXT
        # rebuild, the HUD line -- it must not linger forever once the
        # user has moved on.
        session._slide_forward()
        session.rebuild_line(session.n)
        check(not any("FROM edge" in line for line in session.hud_lines),
              f"the edge HUD line disappears again once the session has moved away from it "
              f"(got {session.hud_lines!r})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_edge_message_clears_on_in_chunk_step_no_slide_needed():
    """Regression (2026-09-25, Artur's own real report, follow-up to the
    HUD-visibility fix): "po wykonaniu kroku w przeciwnym kierunku komunikat
    powinien zniknac ... a komunikat zostaje zamrozony" -- after a step in
    the OPPOSITE direction the message should disappear, but it stays
    frozen. The previous fix only cleared the edge flags/HUD line inside
    _slide_forward/_slide_backward's own SUCCESS path -- a step that stays
    within the ALREADY-loaded chunk_current (no chunk crossing needed at
    all, the common case for a small step right after bouncing off an
    edge) never called either method, so the flag/message never cleared.

    Forces a small, dense wheel (modulus=6, residues=[1]) directly onto a
    real session so multiple wheel-compatible positions exist WITHIN one
    small chunk -- proving the fix covers the in-chunk case specifically,
    not just a chunk-crossing move (the OTHER sliding tests above already
    cover that half)."""
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_viz.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        all_values = [6 * k + 1 for k in range(0, 12)]  # 1..67, all ≡1 mod 6
        _write_floor(portal_dir, 0, [all_values])

        chunk_size = 3
        initial_chunk = load_archive(portal_dir, upto=1000, from_n=all_values[2], max_load_count=chunk_size)
        check(list(initial_chunk) == all_values[3:6], "test setup: initial chunk is values[3:6] ([19,25,31])")

        session = RenderSession(
            primes=initial_chunk, n=int(initial_chunk[0]), ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=False,
            range_load_from=0, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )
        # Force a small, dense wheel so a step within a single chunk (no
        # slide) is actually possible -- every all_values entry (all ≡1
        # mod 6) is itself wheel-compatible under this forced wheel.
        session.pattern_wheel_modulus = 6
        session.pattern_wheel_residues = [1]

        # Reach the TRUE FROM edge: first slide is a real chunk crossing
        # (values[0:3]=[1,7,13] is real data), second slide hits the
        # genuine start.
        session._slide_backward()
        check(session._back_edge_reported is False, "test setup: one real back chunk still remained")
        session._slide_backward()
        check(session._back_edge_reported is True, "test setup: now genuinely at the true FROM edge")
        check(list(session.chunk_current) == [1, 7, 13], "test setup: chunk_current is now the true-first chunk")
        session.n = int(session.chunk_current[0])  # keep n in sync -- _slide_backward itself never touches it

        # One step FORWARD, opposite direction -- with chunk_current
        # holding THREE wheel-compatible entries, this must resolve
        # entirely WITHIN it, no slide needed at all.
        new_n = session._pattern_wheel_step(session.n, True)
        check(new_n == 7, f"the forward step found the next in-chunk candidate, no slide needed (got {new_n})")
        check(list(session.chunk_current) == [1, 7, 13],
              "sanity: chunk_current itself did NOT change -- this really was an in-chunk step")
        check(session._back_edge_reported is False,
              "the stale FROM-edge flag is cleared by an in-chunk step too, not just a real slide")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_to_edge_message_clears_on_in_chunk_step_no_slide_needed():
    """Symmetric counterpart to the FROM-edge in-chunk test above (Artur's
    own explicit follow-up, 2026-09-25: "i analogicznie jest dla at range
    to?" -- and is it analogous for 'at range TO'?) -- same fix
    (_pattern_wheel_step clears BOTH edge flags on any genuine move,
    regardless of direction), same in-chunk-step scenario, mirrored for
    the TO/forward edge instead."""
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_viz.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        all_values = [6 * k + 1 for k in range(0, 12)]  # 1..67, all ≡1 mod 6
        _write_floor(portal_dir, 0, [all_values])

        chunk_size = 3
        range_load_to = 45  # strictly between values[6]=37 and values[7]=43 -- true forward edge inside floor 0
        initial_chunk = load_archive(portal_dir, upto=range_load_to, from_n=all_values[2], max_load_count=chunk_size)
        check(list(initial_chunk) == all_values[3:6], "test setup: initial chunk is values[3:6] ([19,25,31])")

        session = RenderSession(
            primes=initial_chunk, n=int(initial_chunk[0]), ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=False,
            range_load_from=0, range_load_to=range_load_to, chunk_size=chunk_size, sliding_enabled=True,
        )
        session.pattern_wheel_modulus = 6
        session.pattern_wheel_residues = [1]

        # Reach the TRUE TO edge: first slide is real (values[6:9] =
        # [37,43], both <= range_load_to=45), second slide hits the
        # genuine end (nothing left <= 45 past that).
        session._slide_forward()
        check(session._forward_edge_reported is False, "test setup: one real forward chunk still remained")
        session._slide_forward()
        check(session._forward_edge_reported is True, "test setup: now genuinely at the true TO edge")
        check(list(session.chunk_current) == [37, 43], "test setup: chunk_current is now the true-last chunk")
        session.n = int(session.chunk_current[-1])  # keep n in sync -- _slide_forward itself never touches it

        # One step BACKWARD, opposite direction -- chunk_current holds TWO
        # wheel-compatible entries, so this resolves entirely within it.
        new_n = session._pattern_wheel_step(session.n, False)
        check(new_n == 37, f"the backward step found the next in-chunk candidate, no slide needed (got {new_n})")
        check(list(session.chunk_current) == [37, 43],
              "sanity: chunk_current itself did NOT change -- this really was an in-chunk step")
        check(session._forward_edge_reported is False,
              "the stale TO-edge flag is cleared by an in-chunk step too, not just a real slide")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Background pattern seek (2026-09-25 follow-up to the sliding-window plan
# above) -- Artur's own real report: chunk_size=500 + a sparse k=5 pattern
# could need MANY real chunk crossings to reach the next MATCH!, each one a
# real blocking disk load, freezing the GLFW window for however long that
# whole chain took since _pattern_seek ran synchronously on the main thread.
# See session.py's own _start_pattern_seek doc-comment for the full design.
# ---------------------------------------------------------------------------

def _test_sliding_seek_runs_in_background_not_blocking_main_thread():
    """The actual async contract this feature exists for: scrub_advance()
    (or bump_n/tick) returns almost instantly even while the underlying
    multi-chunk crawl is artificially slowed down, self.n stays untouched
    until the background search resolves, and joining the thread afterward
    still reaches the same correct match this file's own synchronous
    _test_sliding_forward_multi_chunk_seek_finds_distant_match already
    proves for the DATA side -- same fixture (target=359, 6 real chunk
    crossings away)."""
    from primeatlas.rings.ring_viz import session as session_module
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_viz.sources import load_archive
    import time

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        base_values = [6 * k + 1 for k in range(0, 70)]
        target = 359
        all_values = sorted(set(base_values) | {target, target + 2})
        _write_floor(portal_dir, 0, [all_values])

        chunk_size = 10
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)
        start_n = int(initial_chunk[0])

        session = RenderSession(
            primes=initial_chunk, n=start_n, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )

        real_load_archive = session_module.load_archive
        slow_delay = 0.2

        def _slow_load_archive(*args, **kwargs):
            time.sleep(slow_delay)
            return real_load_archive(*args, **kwargs)

        session_module.load_archive = _slow_load_archive
        try:
            t0 = time.perf_counter()
            session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
            elapsed = time.perf_counter() - t0
            check(elapsed < slow_delay,
                  f"scrub_advance returns almost instantly even though the underlying multi-chunk "
                  f"crawl needs several {slow_delay}s-slow loads (got {elapsed:.3f}s)")
            check(session._seek_thread is not None, "the seek is genuinely still running in the background")
            check(session.n == start_n, "self.n is untouched while the background search is still in flight")

            session._seek_thread.join(timeout=10)
            check(session._seek_thread is None, "the seek thread clears itself once the search resolves")
            check(session.n == target,
                  f"the background search still reaches the correct real match (expected {target}, got {session.n})")
        finally:
            session_module.load_archive = real_load_archive
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_seek_ignores_further_nav_input_while_in_flight():
    """No true cancellation in v1 (see _start_pattern_seek's own
    doc-comment) -- a second nav call arriving while a seek is already
    running must be a pure no-op, not start a second, concurrent thread
    (chunk_back/chunk_current/chunk_forward have no locking of their own).
    Proven by identity-checking that _seek_thread stays the SAME thread
    object across the extra calls, and that self.n stays untouched until
    the one real seek eventually resolves."""
    from primeatlas.rings.ring_viz import session as session_module
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_viz.sources import load_archive
    import time

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        base_values = [6 * k + 1 for k in range(0, 70)]
        target = 359
        all_values = sorted(set(base_values) | {target, target + 2})
        _write_floor(portal_dir, 0, [all_values])

        chunk_size = 10
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)
        start_n = int(initial_chunk[0])

        session = RenderSession(
            primes=initial_chunk, n=start_n, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )

        real_load_archive = session_module.load_archive
        slow_delay = 0.2

        def _slow_load_archive(*args, **kwargs):
            time.sleep(slow_delay)
            return real_load_archive(*args, **kwargs)

        session_module.load_archive = _slow_load_archive
        try:
            session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
            first_thread = session._seek_thread
            check(first_thread is not None, "test setup: the first seek is running")

            session.bump_n(50)
            session.scrub_advance(is_right=False, ctrl_held=False, is_first_press=True)
            check(session._seek_thread is first_thread,
                  "extra nav input while a seek is in flight is ignored -- no second thread is started")
            check(session.n == start_n, "n stays untouched by the ignored extra input")

            first_thread.join(timeout=10)
            check(session.n == target,
                  f"the original (only) seek still resolves correctly once the extra input was ignored "
                  f"(expected {target}, got {session.n})")
        finally:
            session_module.load_archive = real_load_archive
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_seek_hud_shows_searching_while_in_flight():
    """rebuild_line's own edge_lines addition must surface a "Searching..."
    line while _seek_thread is running, and it must disappear again once
    the search resolves -- a background search is only actually reassuring
    (versus looking frozen) if the user can SEE it's working."""
    from primeatlas.rings.ring_viz import session as session_module
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_viz.sources import load_archive
    import time

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        base_values = [6 * k + 1 for k in range(0, 70)]
        target = 359
        all_values = sorted(set(base_values) | {target, target + 2})
        _write_floor(portal_dir, 0, [all_values])

        chunk_size = 10
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)
        start_n = int(initial_chunk[0])

        session = RenderSession(
            primes=initial_chunk, n=start_n, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )

        real_load_archive = session_module.load_archive
        slow_delay = 0.2

        def _slow_load_archive(*args, **kwargs):
            time.sleep(slow_delay)
            return real_load_archive(*args, **kwargs)

        session_module.load_archive = _slow_load_archive
        try:
            session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
            check(session._seek_thread is not None, "test setup: the seek is in flight")
            session.rebuild_line(session.n)
            check(any("Searching" in line for line in session.hud_lines),
                  f"the HUD shows a searching indicator while the seek is running (got {session.hud_lines!r})")

            session._seek_thread.join(timeout=10)
            session.rebuild_line(session.n)
            check(not any("Searching" in line for line in session.hud_lines),
                  f"the searching indicator disappears again once the seek resolves (got {session.hud_lines!r})")
        finally:
            session_module.load_archive = real_load_archive
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_seek_tick_not_found_stops_playback_in_background():
    """tick()'s own not-found stop (previously synchronous: the main
    loop's own `if should_stop: print(...)` branch reacting to tick()'s
    True return) must still happen once sliding moves the search to a
    background thread -- just a frame or more later, once the worker
    itself resolves. Reuses the same "no real [0,2] match anywhere, real
    range_load_to edge" fixture as
    _test_sliding_found_false_means_true_range_edge_not_chunk_edge."""
    import contextlib
    import io
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_viz.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        all_values = [6 * k + 1 for k in range(0, 30)]  # 1..175, no real [0,2] match anywhere
        _write_floor(portal_dir, 0, [all_values])

        chunk_size = 10
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)
        start_n = int(initial_chunk[0])

        session = RenderSession(
            primes=initial_chunk, n=start_n, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )
        session.playback_running = True

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            stopped = session.tick()
            check(stopped is False,
                  "tick() never synchronously reports 'stopped' once sliding is on -- the background "
                  "worker owns that decision now")
            check(session._seek_thread is not None, "test setup: the search moved to a background thread")
            check(session.playback_running is True, "playback still looks 'running' while the search is in flight")
            session._seek_thread.join(timeout=10)
        out = buf.getvalue()
        check(session.playback_running is False,
              "the background worker itself stops playback once it confirms the genuine range edge, "
              "with no further match found")
        check(session.n == start_n, "n is left untouched -- no non-match candidate is ever committed")
        check("Playback stopped" in out, f"a message explaining the stop still gets printed (got {out!r})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_seek_bump_and_scrub_not_found_leave_n_unchanged_async():
    """bump_n/scrub_advance's own found-gated commit (self.n = new_n only
    if found) still holds once the search is backgrounded -- reuses the
    same real-edge, no-match fixture as the tick() test above, exercised
    via both entry points."""
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_viz.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        all_values = [6 * k + 1 for k in range(0, 30)]  # 1..175, no real [0,2] match anywhere
        _write_floor(portal_dir, 0, [all_values])
        chunk_size = 10

        def make_session():
            initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)
            return RenderSession(
                primes=initial_chunk, n=int(initial_chunk[0]), ceiling=100000, range_mode=True,
                range_primes=initial_chunk, range_step=1,
                track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
                max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
                portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
                pattern_step_mode="auto", pattern_stop_on_match=True,
                range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
            ), int(initial_chunk[0])

        bump_session, start_n = make_session()
        bump_session.bump_n(1000)
        check(bump_session._seek_thread is not None, "test setup: bump_n also moved the search to the background")
        bump_session._seek_thread.join(timeout=10)
        check(bump_session.n == start_n,
              f"bump_n leaves n unchanged once the background search confirms no match (got {bump_session.n})")

        scrub_session, start_n2 = make_session()
        scrub_session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
        scrub_session._seek_thread.join(timeout=10)
        check(scrub_session.n == start_n2, f"scrub_advance leaves n unchanged too (got {scrub_session.n})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_seek_reset_during_flight_discards_stale_result():
    """Regression coverage for `_seek_epoch` (see reset()'s own
    doc-comment): a background pattern seek started BEFORE reset() must
    not clobber the fresh post-reset state (n=1, playback stopped,
    viz_mode back to "rings") once it finally resolves -- even though the
    search itself keeps running to completion in the background (v1 has
    no true cancellation, see _start_pattern_seek's own doc-comment), its
    result must be silently discarded."""
    from primeatlas.rings.ring_viz import session as session_module
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_viz.sources import load_archive
    import time

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        base_values = [6 * k + 1 for k in range(0, 70)]
        target = 359
        all_values = sorted(set(base_values) | {target, target + 2})
        _write_floor(portal_dir, 0, [all_values])

        chunk_size = 10
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)
        start_n = int(initial_chunk[0])

        session = RenderSession(
            primes=initial_chunk, n=start_n, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )

        real_load_archive = session_module.load_archive
        slow_delay = 0.1

        def _slow_load_archive(*args, **kwargs):
            time.sleep(slow_delay)
            return real_load_archive(*args, **kwargs)

        session_module.load_archive = _slow_load_archive
        try:
            session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
            check(session._seek_thread is not None, "test setup: the seek is running in the background")
            in_flight_thread = session._seek_thread

            session.reset()
            check(session.n == 1 and session.range_mode is False and session.viz_mode == "rings",
                  "reset() applies its own state synchronously regardless of the in-flight seek")

            in_flight_thread.join(timeout=10)
            check(session.n == 1,
                  f"the stale seek result (the real match at {target}) is discarded, not applied on top "
                  f"of reset()'s own state (got n={session.n})")
            check(session.range_mode is False, "reset()'s own range_mode=False also survives the late finisher")
        finally:
            session_module.load_archive = real_load_archive
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_seek_exception_clears_seek_thread_not_wedged_forever():
    """Regression (2026-09-25, Artur's own real report: one scrub step
    landed on a non-match and navigation was then stuck in BOTH
    directions): `_start_pattern_seek`'s worker used to clear
    `_seek_thread` only at the very end of its normal body -- any
    exception raised anywhere inside `_pattern_seek`'s own crawl killed
    the thread WITHOUT ever reaching that line, so `_seek_thread` stayed
    permanently non-None and every future tick/bump_n/scrub_advance call
    silently no-op'd forever (the "already running" guard treats any
    non-None value the same, whether the thread is genuinely still
    working or simply died). Fixed with a try/except/finally wrapping the
    whole worker body. Proven here by monkeypatching `_pattern_seek`
    itself to raise, then confirming (a) the thread still clears and (b)
    a SECOND, real seek afterward is not blocked by the first one's
    crash."""
    from primeatlas.rings.ring_viz.session import RenderSession
    import numpy as np

    range_primes = np.array([11, 13, 17, 19, 23, 29, 31, 37], dtype=np.int64)
    session = RenderSession(
        primes=range_primes, n=11, ceiling=100000, range_mode=True,
        range_primes=range_primes, range_step=1,
        track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
        max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=False,
        portal_folder="/fake/portal", viz_mode="line", pattern_offsets=[0, 2],
        pattern_step_mode="auto", pattern_stop_on_match=True,
        range_load_from=1, range_load_to=1000, chunk_size=10, sliding_enabled=False,
    )
    # sliding_enabled is False here (fake portal_folder, no real disk) --
    # flip it on by hand purely to drive _start_pattern_seek directly,
    # same trick _test_sliding_neighbor_chunk_loads_in_background_not_blocking
    # already uses.
    session.sliding_enabled = True

    real_pattern_seek = session._pattern_seek

    def _raising_pattern_seek(n, is_right):
        raise RuntimeError("simulated crawl failure")

    session._pattern_seek = _raising_pattern_seek
    session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    check(session._seek_thread is not None, "test setup: the (about-to-crash) seek is running")
    session._seek_thread.join(timeout=5)
    check(session._seek_thread is None,
          "the seek thread clears itself even when _pattern_seek raises -- navigation is not wedged")

    session._pattern_seek = real_pattern_seek
    start_n = session.n
    session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    # This second seek is real and can resolve near-instantly (11,13 is
    # already a match within the already-loaded window, no chunk crossing
    # needed) -- it may already be done by the time we get back here, so
    # only join IF a thread handle is still present rather than asserting
    # one always is (that would be a race, not a real property to test).
    if session._seek_thread is not None:
        session._seek_thread.join(timeout=5)
    check(session.n != start_n or session._seek_thread is not None,
          "a SECOND, real seek is not permanently blocked by the first one's crash -- it either "
          "already resolved (n moved) or is still genuinely running")


def _test_sliding_seek_searches_with_bigger_stride_then_recenters_to_chunk_size():
    """Artur's own proposal, 2026-09-25 ("a gdyby przeszukiwanie dzialalo
    na tych domyslnych 2 milionach ale samo renderowanie bylo dla
    wyznaczonej liczby" -- what if the SEARCH worked on the default 2
    million while the RENDERING stayed at the configured, possibly much
    smaller, chunk_size): a background seek should crawl with a bigger
    internal stride (fewer real chunk crossings for a sparse pattern) and
    only shrink back down to the user's own small chunk_size once a real
    match is found, so what actually gets rendered still respects that
    budget. Monkeypatches the module's own `_SEEK_STRIDE_CHUNK_SIZE`
    (real default 2,000,000 would need an impractically large synthetic
    fixture) down to 30 against the same target=359/chunk_size=10 fixture
    the plain multi-chunk seek test above already uses (6 real chunk_size=10
    crossings away) -- with stride=30, this needs far fewer real chunk
    loads to get there, and the FINAL chunk_current must still come back
    down to chunk_size=10, not stay stride-sized."""
    from primeatlas.rings.ring_viz import session as session_module
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_viz.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        base_values = [6 * k + 1 for k in range(0, 70)]
        target = 359
        all_values = sorted(set(base_values) | {target, target + 2})
        _write_floor(portal_dir, 0, [all_values])

        chunk_size = 10
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)
        start_n = int(initial_chunk[0])

        session = RenderSession(
            primes=initial_chunk, n=start_n, ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )

        real_stride = session_module._SEEK_STRIDE_CHUNK_SIZE
        session_module._SEEK_STRIDE_CHUNK_SIZE = 30
        try:
            session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
            check(session._seek_thread is not None, "test setup: the seek is running")
            session._seek_thread.join(timeout=10)
        finally:
            session_module._SEEK_STRIDE_CHUNK_SIZE = real_stride

        check(session.n == target, f"the stride-search still reaches the correct real match (expected {target}, got {session.n})")
        check(len(session.chunk_current) <= chunk_size,
              f"chunk_current is recentered back down to the user's own chunk_size after the match "
              f"(expected <= {chunk_size}, got {len(session.chunk_current)})")
        check(int(session.chunk_current[0]) == target,
              f"chunk_current's own first element is still the matched value after recentering "
              f"(got {int(session.chunk_current[0]) if len(session.chunk_current) else None})")
        check(target in session._pattern_primes_set and (target + 2) in session._pattern_primes_set,
              "the matched pair is present in the rebuilt _pattern_primes_set after recentering")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_sliding_seek_fast_in_chunk_match_skips_recenter():
    """When a match is found entirely within the already-loaded
    chunk_current (no chunk crossing needed at all), `_effective_chunk_size`
    is never even called -- `_seek_used_stride` stays False, so
    `_recenter_render_chunks` is skipped and chunk_current is exactly
    whatever it already was, not needlessly reloaded."""
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_viz.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        all_values = _sieve_primes_upto(200)
        _write_floor(portal_dir, 0, [all_values])

        chunk_size = 100
        initial_chunk = load_archive(portal_dir, upto=1000, max_load_count=chunk_size)

        session = RenderSession(
            primes=initial_chunk, n=int(initial_chunk[0]), ceiling=100000, range_mode=True,
            range_primes=initial_chunk, range_step=1,
            track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
            max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=True,
            portal_folder=portal_dir, viz_mode="line", pattern_offsets=[0, 2],
            pattern_step_mode="auto", pattern_stop_on_match=True,
            range_load_from=1, range_load_to=1000, chunk_size=chunk_size, sliding_enabled=True,
        )
        chunk_current_before = session.chunk_current

        session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
        # An in-chunk match can resolve near-instantly (no real I/O at
        # all) -- the thread may already be done by the time we get back
        # here, so only join IF a handle is still present (same race
        # avoidance as the exception-safety test's own "second seek" check).
        if session._seek_thread is not None:
            session._seek_thread.join(timeout=10)

        check(session.chunk_current is chunk_current_before,
              "an in-chunk match (no slide needed) never reloads chunk_current at all -- "
              "_recenter_render_chunks is skipped since the stride was never actually used")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_render_session_wheel_prime_matches_not_skipped():
    """Regression (2026-09-18, Artur's own real report): a k=5 pattern
    seeded at p0=5 (offsets [0,2,6,8,12]) has a REAL match at n=11 (11,13,
    17,19,23 all prime) -- but 11 is itself one of the wheel's own small
    primes, so pure residue arithmetic excludes it (the same "founding
    coincidence" class as the launch-anchor fix above), and
    --pattern-stop-on-match's own seek silently skipped straight from 5 to
    101 without ever considering it. The wheel must patch in ANY of
    DEFAULT_WHEEL_PRIMES that independently checks out as a real match,
    not just the launch anchor itself."""
    from primeatlas.rings.ring_viz.session import RenderSession
    import numpy as np

    range_primes = np.array(_sieve_primes_upto(200), dtype=np.int64)
    session = RenderSession(
        primes=range_primes, n=5, ceiling=1000, range_mode=True,
        range_primes=range_primes, range_step=1,
        track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
        max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=False,
        portal_folder=None, viz_mode="line", pattern_offsets=[0, 2, 6, 8, 12],
        pattern_step_mode="auto", pattern_stop_on_match=True,
    )
    check(11 % session.pattern_wheel_modulus in session.pattern_wheel_residues,
          "n=11's own residue is patched into the wheel because it's independently a real match")

    session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    check(session.n == 11, f"seeking forward from the anchor (5) now lands on the real match at 11, "
                            f"not skipping straight past it (got {session.n})")


def _test_render_session_anchor_always_reachable():
    """Regression (2026-09-18, Artur's own real report: "I can't get back
    to the value I started from"): the k=2 twin-prime pattern seeded at
    p0=3 anchors at n=3 -- but 3 is itself one of the wheel's own primes
    (a "founding coincidence", see pattern_wheel_residues' own
    doc-comment), so pure residue arithmetic excludes n=3's own residue
    class, making it unreachable once you scrub away from it. The
    session must patch its own launch anchor back into the wheel."""
    from primeatlas.rings.ring_viz.session import RenderSession
    import numpy as np

    range_primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61],
                             dtype=np.int64)
    session = RenderSession(
        primes=range_primes, n=3, ceiling=100, range_mode=True,
        range_primes=range_primes, range_step=1,
        track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
        max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=False,
        portal_folder=None, viz_mode="line", pattern_offsets=[0, 2],
    )
    check(3 % session.pattern_wheel_modulus in session.pattern_wheel_residues,
          "the launch anchor's own residue (n=3) is patched into the wheel's residue set")

    session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    n_after_forward = session.n
    check(n_after_forward != 3, f"scrub forward actually left the anchor (got {n_after_forward})")

    session.scrub_advance(is_right=False, ctrl_held=False, is_first_press=True)
    check(session.n == 3, f"scrub backward from the very next candidate returns exactly to the launch anchor (got {session.n})")


def _test_resolve_pattern_anchor():
    """2026-09-18: Artur asked whether this works for an arbitrary
    --load-range at real archive scale (e.g. a 22-digit to 23-digit
    window) while the pattern seed stays a small number like 7 or 11 --
    the seed only picks the pattern's SHAPE, so it should compute the
    phase and land on the first genuinely wheel-compatible candidate
    inside that huge, disjoint window instead of naively clamping to the
    window's raw lower edge (which has no guarantee of being wheel-
    compatible at all)."""
    from primeatlas.rings.ring_geometry import (
        resolve_pattern_anchor, pattern_offsets_from_seed, next_prime_at_or_above,
        pattern_wheel_residues,
    )

    offsets = pattern_offsets_from_seed(3, 5)  # [0, 2, 6], seed_prime=5
    seed_prime = next_prime_at_or_above(5)

    check(resolve_pattern_anchor(seed_prime, offsets, 2, 1000) == 5,
          "seed's own occurrence is used directly when the window actually contains it")

    # A real archive-scale window nowhere near the small seed.
    lo, hi = 10 ** 22, 10 ** 22 + 10 ** 6
    anchor = resolve_pattern_anchor(seed_prime, offsets, lo, hi)
    check(anchor != seed_prime, f"the tiny seed occurrence (5) is NOT reused when it's nowhere near the "
                                 f"window (got {anchor})")
    check(lo <= anchor <= hi, f"the computed anchor stays inside the requested window (got {anchor})")
    modulus, residues = pattern_wheel_residues(offsets)
    check(anchor % modulus in residues,
          f"the computed anchor is genuinely phase-compatible with the pattern's own wheel, not just "
          f"the window's raw lower edge (got {anchor}, residue {anchor % modulus})")
    check(all(x % modulus not in residues for x in range(lo, anchor)),
          f"anchor is the FIRST compatible candidate at/after lo, not some arbitrarily later one (got {anchor})")


def _test_build_line_vertex_data():
    from primeatlas.rings.ring_viz.geometry_draw import build_line_vertex_data
    import numpy as np

    range_primes = np.array([11, 13, 17, 19, 23, 29, 31, 37], dtype=np.int64)

    data, count, hit_mask, all_match, view_mode, boundary_radius = build_line_vertex_data(
        range_primes, 11, [0, 2, 6, 8, 12, 18, 20]
    )
    check(count == len(range_primes) + 7,
          f"vertex data has one row per background prime plus one per pattern member (got {count})")
    check(hit_mask.sum() == 7, "hit_mask marks exactly the pattern-member rows, not the background dots")
    check(all_match is True, "build_line_vertex_data reports all_match for a real occurrence")
    check(data.shape == (count, 5), "vertex data is the standard (count, 5) [x,y,r,g,b] layout")
    check(view_mode == "full", "a small loaded window stays in 'full' view mode (span well under the precision threshold)")
    check(boundary_radius is None, "boundary_radius is None when curved is False (nothing to draw)")

    data2, count2, hit_mask2, all_match2, view_mode2, _br2 = build_line_vertex_data(range_primes, 12, [0, 2, 6])
    check(count2 == len(range_primes) + 3, "background dots are unaffected by a non-matching anchor")
    check(all_match2 is False, "all_match False when the anchored pattern doesn't land on real primes")

    data3, count3, hit_mask3, all_match3, view_mode3, _br3 = build_line_vertex_data(range_primes, 11, [])
    check(count3 == len(range_primes), "no pattern offsets -> only the background dot row, no extra markers")
    check(all_match3 is False, "all_match False with no pattern active")

    # primes_set override: passing a pre-built set must give the exact same
    # match result as letting the function build it from range_primes itself.
    primes_set = set(int(v) for v in range_primes)
    data4, count4, hit_mask4, all_match4, view_mode4, _br4 = build_line_vertex_data(
        range_primes, 11, [0, 2, 6, 8, 12, 18, 20], primes_set=primes_set
    )
    check(all_match4 is True, "an explicit primes_set override gives the same match result as the default")


def _test_build_line_vertex_data_curved():
    """Spec for build_line_vertex_data's `curved` parameter (2026-09-18,
    Artur's own spec: "w samym działaniu nic się nie zmieni poza samą
    wizualizacją osi" -- nothing changes in the actual behavior, only the
    axis's own visualization). Compares curved=True directly against
    curved=False for the IDENTICAL inputs: match results, hit_mask, and
    row counts must be byte-for-byte identical; only the (x,y) positions
    themselves may differ."""
    from primeatlas.rings.ring_viz.geometry_draw import build_line_vertex_data
    import numpy as np
    import math

    range_primes = np.array([11, 13, 17, 19, 23, 29, 31, 37], dtype=np.int64)
    offsets = [0, 2, 6, 8, 12, 18, 20]

    data_s, count_s, hit_s, match_s, view_s, br_s = build_line_vertex_data(range_primes, 11, offsets, curved=False)
    data_c, count_c, hit_c, match_c, view_c, br_c = build_line_vertex_data(range_primes, 11, offsets, curved=True)

    check(count_s == count_c, f"curved vs straight produce the same row count (got {count_s} vs {count_c})")
    check(bool((hit_s == hit_c).all()), "curved vs straight mark exactly the same rows as pattern members")
    check(match_s == match_c == True, "curved vs straight report the identical all_match result")  # noqa: E712
    check(view_s == view_c, "curved vs straight pick the identical view_mode (this flag is orthogonal to it)")
    check(bool((data_s[:, 2:5] == data_c[:, 2:5]).all()), "curved vs straight assign the identical colors per row")
    check(br_s is None, "boundary_radius is None for the straight layout")
    check(br_c == 800.0, f"boundary_radius is world_width/2 for the plain-circle case (no wheel_modulus given) (got {br_c})")

    # Straight layout: every y is exactly 0. Curved layout: not all y are 0,
    # and every (x,y) pair lies on the circle of radius world_width/2=800.
    check(bool((data_s[:, 1] == 0.0).all()), "the straight (default) layout keeps every y at exactly 0")
    check(not bool((data_c[:, 1] == 0.0).all()), "the curved layout genuinely uses non-zero y for at least some rows")
    for x, y in zip(data_c[:, 0], data_c[:, 1]):
        dist = math.hypot(float(x), float(y))
        check(abs(dist - 800.0) < 1e-3, f"every curved-layout point lies on the circle of radius 800 (got dist={dist})")


def _test_line_view_bounds():
    """Spec for ring_geometry.line_view_bounds (2026-09-18, Artur's own
    "wrap the axis into a phase/ring coordinate" fix for the float32
    GPU-vertex-buffer precision ceiling): stay in 'full' whole-window mode
    below LINE_PRECISION_SAFE_SPAN, switch to a 'local', anchor-centered,
    FIXED-width slice above it -- and that local slice must always be wide
    enough to hold the active pattern's own full diameter."""
    from primeatlas.rings.ring_geometry import (
        line_view_bounds, LINE_PRECISION_SAFE_SPAN, LINE_LOCAL_VIEW_RADIUS,
    )

    mode, lo, span = line_view_bounds(1000, 1000 + LINE_PRECISION_SAFE_SPAN, 5000)
    check(mode == "full", "a span exactly at the safe threshold stays in 'full' mode")
    check((lo, span) == (1000, LINE_PRECISION_SAFE_SPAN), "'full' mode maps lo/span straight from range_lo/range_hi")

    range_lo = 10 ** 25
    range_hi = range_lo + 10 ** 8
    anchor = range_lo + 12345
    mode2, lo2, span2 = line_view_bounds(range_lo, range_hi, anchor)
    check(mode2 == "local", "a real archive-scale span (1e8) switches to 'local' mode")
    check(span2 == 2 * LINE_LOCAL_VIEW_RADIUS, "'local' mode's span is the fixed default radius, doubled")
    check(lo2 == anchor - LINE_LOCAL_VIEW_RADIUS, "'local' mode is centered exactly on the anchor")

    # An unusually wide pattern (diameter*4 > the default radius) must
    # still fit entirely inside the local viewport, not get clipped.
    wide_offsets = [0, 30_000]
    mode3, lo3, span3 = line_view_bounds(range_lo, range_hi, anchor, wide_offsets)
    check(span3 >= wide_offsets[-1] * 4,
          f"local viewport widens to hold an unusually wide pattern's own diameter (span={span3})")
    check(anchor - lo3 == span3 / 2, "the widened viewport is still centered exactly on the anchor")


def _test_line_positions_windowed():
    """Spec for ring_geometry.line_positions_windowed: filters an ascending
    array down to [lo, lo+span] via binary search and maps ONLY that
    slice, using the caller-supplied lo/span rather than the array's own
    min/max -- the piece line_view_bounds' local mode actually needs to
    render just the anchor-centered neighborhood instead of the whole
    loaded array."""
    from primeatlas.rings.ring_geometry import line_positions_windowed, value_to_line_x
    import numpy as np

    primes = np.array([5, 11, 13, 17, 19, 23, 29, 1000], dtype=np.int64)
    win = line_positions_windowed(primes, lo=10, span=20, world_width=1000.0)
    # [10, 30] inclusive on both ends: 11, 13, 17, 19, 23, 29 -- six values.
    check(len(win["x"]) == 6, f"only the 6 values genuinely inside [10, 30] are kept (got {len(win['x'])})")
    check(win["lo"] == 10 and win["span"] == 20, "line_positions_windowed reports back the CALLER's own lo/span")

    expected_first_x = value_to_line_x(11, 10, 20, 1000.0)
    check(abs(win["x"][0] - expected_first_x) < 1e-6,
          "line_positions_windowed's own mapping matches value_to_line_x for the same lo/span")

    empty = line_positions_windowed(primes, lo=10_000, span=5, world_width=1000.0)
    check(len(empty["x"]) == 0, "a window with no primes inside it returns an empty (not crashing) result")


def _test_line_positions_windowed_archive_scale_precision():
    """The actual regression this whole feature exists to fix (2026-09-18,
    Artur's own real report against a real 26-digit --load-range, k=4:
    "again one point short... and the spacing between them doesn't match
    the pattern, since the pattern isn't spaced that evenly"). Unlike
    _test_line_positions_archive_scale_precision (which only proved the
    float64 math inside line_positions itself was exact), THIS test casts
    the result to float32 -- exactly like build_line_vertex_data's own
    GPU vertex buffer does -- and checks the pattern's own UNEVEN internal
    spacing ([0,2,6,8]: gaps 2,4,2) survives that cast distinctly, which a
    naive whole-window linear map (span ~1e8) provably cannot do at
    world_width/2 magnitude (~800): a value-delta of 2 there maps to a
    world-x delta far below float32's own ULP and several members collapse
    onto the same float32 x -- this is the failure line_view_bounds' local,
    anchor-centered viewport (this function's own `lo`/`span` inputs) is
    meant to avoid entirely, by keeping the mapped span small (a few
    thousand) regardless of the loaded window's real, huge span."""
    from primeatlas.rings.ring_geometry import (
        line_positions_windowed, value_to_line_x, line_view_bounds,
    )
    import numpy as np

    range_lo = 10 ** 26
    range_hi = range_lo + 10 ** 9
    offsets = [0, 2, 6, 8]
    anchor = range_lo + 55_555_555

    mode, lo, span = line_view_bounds(range_lo, range_hi, anchor, offsets)
    check(mode == "local", "a real 1e9-wide archive window triggers the local viewport")

    xs_f32 = np.array(
        [value_to_line_x(anchor + o, lo, span, 1600.0) for o in offsets], dtype=np.float32
    )
    check(len(set(xs_f32.tolist())) == 4,
          f"all 4 pattern-member x positions stay DISTINCT even after casting to float32 (got {xs_f32})")

    gap1 = xs_f32[1] - xs_f32[0]  # offset delta 2
    gap2 = xs_f32[2] - xs_f32[1]  # offset delta 4
    gap3 = xs_f32[3] - xs_f32[2]  # offset delta 2
    check(abs(gap1 - gap3) < 1e-4,
          f"the two offset-delta-2 gaps render as equal to each other (got {gap1} vs {gap3})")
    check(abs(gap2 - 2 * gap1) < 1e-4,
          f"the offset-delta-4 gap renders as exactly double an offset-delta-2 gap, "
          f"preserving the pattern's own UNEVEN spacing instead of looking evenly spaced (got gap2={gap2}, gap1={gap1})")

    # Also confirm the naive WHOLE-window mapping (the pre-fix behavior)
    # really does collapse these same 4 positions at this scale, so this
    # test is provably exercising the bug it claims to fix.
    naive_xs_f32 = np.array(
        [value_to_line_x(anchor + o, range_lo, range_hi - range_lo, 1600.0) for o in offsets], dtype=np.float32
    )
    check(len(set(naive_xs_f32.tolist())) < 4,
          f"sanity check: the OLD whole-window mapping at this scale really does collapse "
          f"some of these 4 positions together (got {naive_xs_f32}) -- confirms the local "
          f"viewport is fixing a real, reproducible failure, not a hypothetical one")


def _test_build_line_vertex_data_local_view_integration():
    """End-to-end version of the archive-scale precision test above,
    through the ACTUAL build_line_vertex_data entry point (not just
    line_view_bounds/value_to_line_x directly): a real archive-scale
    `range_primes` array (span 1e6, well past LINE_PRECISION_SAFE_SPAN)
    must render in 'local' view mode, drawing only the background dots
    inside the local viewport (not the full loaded array), while the
    pattern's own 4 members still land on 4 distinct float32 x positions
    in the actual GPU vertex buffer `data`."""
    from primeatlas.rings.ring_viz.geometry_draw import build_line_vertex_data
    from primeatlas.rings.ring_geometry import LINE_LOCAL_VIEW_RADIUS
    import numpy as np

    range_lo = 10 ** 26
    span = 1_000_000
    step = 100
    offsets = [0, 2, 6, 8]
    anchor = range_lo + span // 2
    values = {range_lo + i * step for i in range(span // step)}
    values |= {anchor + o for o in offsets}  # the pattern's own occurrence must be real data
    range_primes = np.array(sorted(values), dtype=object)

    data, count, hit_mask, all_match, view_mode, _boundary_radius = build_line_vertex_data(range_primes, anchor, offsets)
    check(view_mode == "local", "an archive-scale loaded window (span 1e6) renders in local view mode")
    check(all_match is True, "the inserted pattern positions are genuine matches")

    bg_count = int(count - hit_mask.sum())
    check(bg_count < len(range_primes),
          f"local mode renders only the background dots inside the local viewport, "
          f"not the whole loaded array ({bg_count} of {len(range_primes)})")
    check(bg_count <= (2 * LINE_LOCAL_VIEW_RADIUS) // step + 10,
          f"background dot count roughly matches the local viewport's own width / spacing (got {bg_count})")

    xs = data[hit_mask][:, 0]
    check(len(set(xs.tolist())) == 4,
          f"the 4 pattern-member x positions in the actual float32 GPU buffer are distinct (got {xs})")


def _test_render_session_line_mode():
    from primeatlas.rings.ring_viz.session import RenderSession
    import numpy as np

    range_primes = np.array([11, 13, 17, 19, 23, 29, 31, 37, 41, 43], dtype=np.int64)
    session = RenderSession(
        primes=range_primes, n=11, ceiling=100, range_mode=True,
        range_primes=range_primes, range_step=1,
        track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
        max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=False,
        portal_folder=None, viz_mode="line", pattern_offsets=[0, 2, 6, 8, 12, 18, 20],
    )
    data_normal, data_hit, count, count_hit = session.rebuild_line(11)
    check(count_hit == 7, "rebuild_line's hit split carries exactly the 7 pattern-member rows")
    check(session.pattern_match is True, "session.pattern_match reflects the last rebuild_line's all_match")
    check(session.flash_pattern == 1.0, "a full pattern match triggers flash_pattern")

    color = session.pattern_flash_color()
    check(color is not None, "pattern_flash_color() returns a color while flash_pattern > 0")
    session.decay_pattern_flash()
    check(session.flash_pattern < 1.0, "decay_pattern_flash reduces the accumulator")

    # Scrub past the window's own last valid anchor (range_to=43, offsets[-1]=20 -> max anchor 23).
    for _ in range(50):
        session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=False)
    check(session.n <= 23, f"scrub_advance never pushes the pattern's last member past range_to (n={session.n})")

    session.reset()
    check(session.viz_mode == "rings", "reset() falls back to rings mode")
    check(session.pattern_offsets is None, "reset() clears the active pattern")
    check(session.pattern_wheel_modulus is None, "reset() clears the wheel modulus")
    check(session.pattern_wheel_residues is None, "reset() clears the wheel residues")


def _test_render_session_line_axis_curved():
    """Spec: RenderSession.line_axis_curved is a purely cosmetic, launch-
    time toggle -- constructing two otherwise-identical sessions (one
    curved, one not) and rebuilding at the same N must produce IDENTICAL
    pattern_match/count_hit (i.e. the SAME set of matches/misses), only
    differing in the actual (x,y) positions rendered. reset() must clear
    it back to False, same "clean baseline" contract as every other line-
    mode launch parameter."""
    from primeatlas.rings.ring_viz.session import RenderSession
    import numpy as np

    range_primes = np.array([11, 13, 17, 19, 23, 29, 31, 37, 41, 43], dtype=np.int64)
    kwargs = dict(
        primes=range_primes, n=11, ceiling=100, range_mode=True,
        range_primes=range_primes, range_step=1,
        track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
        max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=False,
        portal_folder=None, viz_mode="line", pattern_offsets=[0, 2, 6, 8, 12, 18, 20],
    )
    session_straight = RenderSession(**kwargs, line_axis_curved=False)
    session_curved = RenderSession(**kwargs, line_axis_curved=True)

    check(session_straight.line_axis_curved is False, "line_axis_curved defaults to/honors False")
    check(session_curved.line_axis_curved is True, "line_axis_curved honors True when passed at construction")

    _dn_s, _dh_s, _count_s, count_hit_s = session_straight.rebuild_line(11)
    _dn_c, _dh_c, _count_c, count_hit_c = session_curved.rebuild_line(11)
    check(count_hit_s == count_hit_c == 7, "curved vs straight sessions carry the identical hit-row count")
    check(session_straight.pattern_match == session_curved.pattern_match == True,  # noqa: E712
          "curved vs straight sessions report the identical pattern_match result")

    session_curved.reset()
    check(session_curved.line_axis_curved is False, "reset() clears line_axis_curved back to False")


def _test_render_session_spiral_axis():
    """Session-level check that a REAL pattern's own wheel modulus
    (computed once at construction, see RenderSession.__init__) actually
    drives the spiral layout end to end through rebuild_line -- not just
    the pure geometry_draw-level test above with an arbitrary test
    modulus. Uses a synthetic range spanning multiple real wheel periods
    (30,030 for this k=2 pattern) so the spiral genuinely has more than
    one lap to show."""
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_geometry import pattern_offsets_from_seed, pattern_wheel_residues
    import numpy as np
    import math

    offsets = pattern_offsets_from_seed(2, 5)  # [0, 2] -- twin-prime shape
    modulus, _residues = pattern_wheel_residues(offsets)
    check(modulus > 0, "sanity: a real k=2 pattern has a nonzero wheel modulus")

    # Synthetic ascending "primes" spanning just over 2 real wheel periods
    # -- not actually prime, but this is pure geometry/state wiring, same
    # convention as this file's other synthetic-array tests.
    lo = 1_000_000
    span = int(2.5 * modulus)
    range_primes = np.array(sorted({lo, lo + span} | {lo + i * 977 for i in range(span // 977)}), dtype=np.int64)

    session = RenderSession(
        primes=range_primes, n=int(range_primes[0]), ceiling=int(range_primes[-1]), range_mode=True,
        range_primes=range_primes, range_step=1,
        track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
        max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=False,
        portal_folder=None, viz_mode="line", pattern_offsets=offsets, line_axis_curved=True,
    )
    session.rebuild_line(int(range_primes[0]))

    check(session.pattern_axis_boundary_radius is not None, "spiral mode sets a real boundary_radius")
    check(session.pattern_axis_boundary_radius > 800.0,
          f"a window spanning multiple real wheel periods produces a spiral reaching past the innermost lap "
          f"(got {session.pattern_axis_boundary_radius})")
    check(any("[axis: spiral]" in line for line in session.hud_lines),
          f"the HUD reports the spiral axis explicitly (got {session.hud_lines})")

    session.reset()
    check(session.pattern_axis_boundary_radius is None, "reset() clears the boundary radius back to None")


def _test_render_session_wheel_scrub():
    """Session-level check that scrub_advance/tick actually WIRE into
    next_wheel_n correctly (right modulus/residues/bounds at the right
    moment) -- the wheel math itself is already covered directly by
    _test_pattern_wheel_residues/_test_next_wheel_n above, so this compares
    session's own outcome against calling that same pure function
    independently, rather than hand-computing an expected n (the DEFAULT
    wheel_primes pull in 5/7/11/13 too, not just 2/3, so the real modulus
    for a real pattern is generally much larger than a small hand example
    -- see pattern_wheel_residues' own doc-comment on primes coinciding
    with an actual member for why small test primes like 5,7,11 would be
    the wrong choice here)."""
    from primeatlas.rings.ring_viz.session import RenderSession
    from primeatlas.rings.ring_geometry import next_wheel_n
    import numpy as np

    range_primes = np.array([101, 103, 107, 109, 113, 127, 131, 137, 139], dtype=np.int64)
    session = RenderSession(
        primes=range_primes, n=101, ceiling=100000, range_mode=True,
        range_primes=range_primes, range_step=1,
        track_primes=[], auto_orbit=False, enabled_ids=set(), theta=0.5, law_mode="stepped",
        max_radius=800.0, tempo_ms=120, buffer_margin=0, can_extend_buffer=False,
        portal_folder=None, viz_mode="line", pattern_offsets=[0, 2, 6],
    )
    check(session.pattern_wheel_modulus > 1, "session computed a meaningful wheel modulus at construction")
    check(session._has_pattern_wheel() is True, "session recognizes a meaningful wheel is active")

    lo = int(range_primes[0])
    hi = int(range_primes[-1]) - 6
    modulus, residues = session.pattern_wheel_modulus, session.pattern_wheel_residues

    expected_forward = next_wheel_n(101, True, modulus, residues, lo, hi)
    session.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    check(session.n == expected_forward,
          f"scrub_advance forward matches next_wheel_n's own computation (expected {expected_forward}, got {session.n})")

    expected_backward = next_wheel_n(session.n, False, modulus, residues, lo, hi)
    session.scrub_advance(is_right=False, ctrl_held=False, is_first_press=True)
    check(session.n == expected_backward,
          f"scrub_advance backward matches next_wheel_n's own computation (expected {expected_backward}, got {session.n})")

    # Regression: Up/Down/PageUp/PageDown (bump_n) used to add its raw
    # n_step delta (e.g. 1000) unconditionally, landing on an arbitrary
    # position the wheel would never have picked -- looked like "the
    # period jump is shifted" (Artur's own real bug report, 2026-09-18).
    # bump_n must now take exactly one wheel step, ignoring delta's
    # magnitude, same as scrub_advance.
    session.n = 101
    expected_bump_forward = next_wheel_n(101, True, modulus, residues, lo, hi)
    session.bump_n(1000)
    check(session.n == expected_bump_forward,
          f"bump_n with a large positive delta (n_step) still takes exactly one wheel step forward, "
          f"ignoring the delta's own magnitude (expected {expected_bump_forward}, got {session.n})")
    expected_bump_backward = next_wheel_n(session.n, False, modulus, residues, lo, hi)
    session.bump_n(-1000)
    check(session.n == expected_bump_backward,
          f"bump_n with a large negative delta still takes exactly one wheel step backward "
          f"(expected {expected_bump_backward}, got {session.n})")

    session.n = hi
    expected_tick_n = next_wheel_n(hi, True, modulus, residues, lo, hi)
    should_stop_expected = (expected_tick_n == hi)
    session.playback_running = True
    stopped = session.tick()
    check(stopped == should_stop_expected,
          f"tick()'s stop/continue decision from the window edge matches next_wheel_n's own computation "
          f"(expected stop={should_stop_expected}, got {stopped})")
    check(session.n == expected_tick_n,
          f"tick() lands exactly where next_wheel_n says it should (expected {expected_tick_n}, got {session.n})")


def main():
    _test_next_prime_at_or_above()
    _test_pattern_offsets_from_seed()
    _test_line_positions_and_value_to_line_x()
    _test_line_positions_archive_scale_precision()
    _test_value_to_ring_axis_xy()
    _test_line_positions_windowed_ring()
    _test_value_to_spiral_xy()
    _test_line_positions_windowed_spiral()
    _test_spiral_outer_radius()
    _test_axis_boundary_marker_vertices()
    _test_pattern_positions_and_match()
    _test_clamp_pattern_anchor()
    _test_pattern_wheel_residues()
    _test_next_wheel_n()
    _test_pattern_step_mode_and_stop_on_match()
    _test_pattern_seek_has_no_artificial_step_cap()
    _test_pattern_seek_stays_on_last_real_match_at_genuine_window_edge()
    _test_sliding_forward_multi_chunk_seek_finds_distant_match()
    _test_sliding_backward_swap_mirror()
    _test_sliding_neighbor_chunk_loads_in_background_not_blocking()
    _test_sliding_disabled_by_default_without_full_wiring()
    _test_sliding_found_false_means_true_range_edge_not_chunk_edge()
    _test_sliding_forward_respects_range_load_to_hard_boundary()
    _test_sliding_edge_reached_prints_explicit_message()
    _test_sliding_edge_reached_shows_in_hud_not_just_console()
    _test_sliding_edge_message_clears_on_in_chunk_step_no_slide_needed()
    _test_sliding_to_edge_message_clears_on_in_chunk_step_no_slide_needed()
    _test_sliding_seek_runs_in_background_not_blocking_main_thread()
    _test_sliding_seek_ignores_further_nav_input_while_in_flight()
    _test_sliding_seek_hud_shows_searching_while_in_flight()
    _test_sliding_seek_tick_not_found_stops_playback_in_background()
    _test_sliding_seek_bump_and_scrub_not_found_leave_n_unchanged_async()
    _test_sliding_seek_reset_during_flight_discards_stale_result()
    _test_sliding_seek_exception_clears_seek_thread_not_wedged_forever()
    _test_sliding_seek_searches_with_bigger_stride_then_recenters_to_chunk_size()
    _test_sliding_seek_fast_in_chunk_match_skips_recenter()
    _test_render_session_wheel_prime_matches_not_skipped()
    _test_render_session_anchor_always_reachable()
    _test_resolve_pattern_anchor()
    _test_build_line_vertex_data()
    _test_build_line_vertex_data_curved()
    _test_build_line_vertex_data_spiral()
    _test_line_view_bounds()
    _test_line_positions_windowed()
    _test_line_positions_windowed_archive_scale_precision()
    _test_build_line_vertex_data_local_view_integration()
    _test_render_session_line_mode()
    _test_render_session_line_axis_curved()
    _test_render_session_spiral_axis()
    _test_render_session_wheel_scrub()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
