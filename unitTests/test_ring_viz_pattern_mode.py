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
import sys

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
