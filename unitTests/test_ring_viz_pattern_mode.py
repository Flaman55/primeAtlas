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


def _test_build_line_vertex_data():
    from primeatlas.rings.ring_viz.geometry_draw import build_line_vertex_data
    import numpy as np

    range_primes = np.array([11, 13, 17, 19, 23, 29, 31, 37], dtype=np.int64)

    data, count, hit_mask, all_match = build_line_vertex_data(range_primes, 11, [0, 2, 6, 8, 12, 18, 20])
    check(count == len(range_primes) + 7,
          f"vertex data has one row per background prime plus one per pattern member (got {count})")
    check(hit_mask.sum() == 7, "hit_mask marks exactly the pattern-member rows, not the background dots")
    check(all_match is True, "build_line_vertex_data reports all_match for a real occurrence")
    check(data.shape == (count, 5), "vertex data is the standard (count, 5) [x,y,r,g,b] layout")

    data2, count2, hit_mask2, all_match2 = build_line_vertex_data(range_primes, 12, [0, 2, 6])
    check(count2 == len(range_primes) + 3, "background dots are unaffected by a non-matching anchor")
    check(all_match2 is False, "all_match False when the anchored pattern doesn't land on real primes")

    data3, count3, hit_mask3, all_match3 = build_line_vertex_data(range_primes, 11, [])
    check(count3 == len(range_primes), "no pattern offsets -> only the background dot row, no extra markers")
    check(all_match3 is False, "all_match False with no pattern active")


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
    _test_pattern_positions_and_match()
    _test_clamp_pattern_anchor()
    _test_pattern_wheel_residues()
    _test_next_wheel_n()
    _test_render_session_anchor_always_reachable()
    _test_build_line_vertex_data()
    _test_render_session_line_mode()
    _test_render_session_wheel_scrub()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
