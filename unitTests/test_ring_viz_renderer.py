"""
test_ring_viz_renderer.py -- unit tests for primeatlas/ring_viz/renderer.py's
Faza 2 hardened load_magazyn() (see that function's own docstring and
PLAN.md's Faza 2 section): real floor enumeration via storage.list_pietra(),
batched reads, optional progress_callback.

Builds a synthetic portal folder with real PGS window files (same fixture
convention as unitTests/test_storage.py's own _test_round_trip_bump_matches_
full_rescan -- prime_sieve_v1.write_prime_window() + window_sharding.shard_dir()),
so this exercises the actual on-disk read path, not a mocked one.

Deliberately does NOT import moderngl/glfw (renderer.py only imports those
inside run(), which this test never calls) -- so this test runs fine in a
headless sandbox with no GPU/display, same as every other pure-logic test in
this package.

Usage (Windows, real Python):
    python unitTests\\test_ring_viz_renderer.py

Usage (this sandbox, headless):
    python3 unitTests/test_ring_viz_renderer.py
"""
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

import numpy as np

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _write_floor(portal_dir, base_exponent, windows):
    """windows: list of lists of ints, one shard-0 PRIME_WINDOW_*.bin per
    entry, named so list_source_filenames()'s offset-based sort places them
    in the given order (offsets 0, 1_000_000, 2_000_000, ... -- comfortably
    apart, real widths don't matter for this test since load_magazyn reads
    whatever's actually in each file, not the offset in the filename)."""
    import window_sharding
    import prime_sieve_v1

    source_dir = os.path.join(portal_dir, f"10p{base_exponent}", "source_primes")
    shard0 = window_sharding.shard_dir(source_dir, 0)
    os.makedirs(shard0, exist_ok=True)
    for i, primes in enumerate(windows):
        name = f"PRIME_WINDOW_off_{i}M.bin" if i > 0 else "PRIME_WINDOW_off_0.bin"
        prime_sieve_v1.write_prime_window(os.path.join(shard0, name), primes)


def _test_basic_multi_floor_load():
    from primeatlas.ring_viz.renderer import load_magazyn

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        # Floor 0: numbers below 10 -- one window, [2,3,5,7].
        _write_floor(portal_dir, 0, [[2, 3, 5, 7]])
        # Floor 1: numbers in [10, 100) -- two windows.
        _write_floor(portal_dir, 1, [[11, 13, 17], [19, 23, 29]])

        result = load_magazyn(portal_dir, upto=30)
        check(list(result) == [2, 3, 5, 7, 11, 13, 17, 19, 23, 29],
              f"load_magazyn(upto=30) across two floors returns every prime "
              f"<=30 in ascending order (got {list(result)!r})")
        check(result.dtype == np.int64, "load_magazyn result is int64")

        result_partial = load_magazyn(portal_dir, upto=20)
        check(list(result_partial) == [2, 3, 5, 7, 11, 13, 17, 19],
              f"load_magazyn(upto=20) correctly excludes primes above the "
              f"cutoff, including trimming WITHIN the second floor-1 window "
              f"(got {list(result_partial)!r})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_gap_between_floors():
    """The exact case the old blind floor+=1 loop handled inefficiently but
    correctly, and the new list_pietra()-based enumeration must ALSO handle
    correctly (not just efficiently): floor 0 populated, floor 1 MISSING
    entirely (e.g. never generated), floor 2 populated."""
    from primeatlas.ring_viz.renderer import load_magazyn

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        _write_floor(portal_dir, 0, [[2, 3, 5, 7]])
        # floor 1 (10p1) deliberately not created at all.
        _write_floor(portal_dir, 2, [[101, 103, 107]])

        result = load_magazyn(portal_dir, upto=200)
        check(list(result) == [2, 3, 5, 7, 101, 103, 107],
              f"load_magazyn skips a missing floor cleanly instead of "
              f"stalling or erroring on the gap (got {list(result)!r})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_batching_does_not_change_result():
    """The whole point of Faza 2's batching is an internal memory-shape
    change, not a behavior change -- a tiny batch_files=1 (forces one file
    per batch) must return the EXACT SAME array as a large batch_files that
    reads everything in one batch."""
    from primeatlas.ring_viz.renderer import load_magazyn

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        _write_floor(portal_dir, 0, [[2, 3, 5, 7]])
        _write_floor(portal_dir, 1, [[11, 13], [17, 19], [23, 29], [31, 37]])

        big_batch = load_magazyn(portal_dir, upto=100, batch_files=1000)
        small_batch = load_magazyn(portal_dir, upto=100, batch_files=1)
        check(list(big_batch) == list(small_batch),
              f"batch_files=1 (one file per batch) and batch_files=1000 (one "
              f"giant batch) return identical results "
              f"(big={list(big_batch)!r} small={list(small_batch)!r})")
        check(list(big_batch) == [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37],
              "sanity: the actual content is correct regardless of batching")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_progress_callback_invoked():
    from primeatlas.ring_viz.renderer import load_magazyn

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        _write_floor(portal_dir, 0, [[2, 3, 5, 7]])
        _write_floor(portal_dir, 1, [[11, 13], [17, 19], [23, 29]])

        calls = []

        def on_progress(base_exponent, files_read_in_floor, primes_loaded_so_far):
            calls.append((base_exponent, files_read_in_floor, primes_loaded_so_far))

        result = load_magazyn(portal_dir, upto=30, progress_callback=on_progress, batch_files=1)
        check(len(calls) > 0, "progress_callback was invoked at least once")
        check(all(c[0] in (0, 1) for c in calls),
              f"every progress_callback call reports a real base_exponent that was actually "
              f"visited (got floors {sorted(set(c[0] for c in calls))!r})")
        # primes_loaded_so_far must be monotonically non-decreasing across all calls
        # (batch_files=1 here means one call per file, in read order).
        loaded_values = [c[2] for c in calls]
        check(loaded_values == sorted(loaded_values),
              f"primes_loaded_so_far is monotonically non-decreasing across progress "
              f"callback calls (got {loaded_values!r})")
        check(loaded_values[-1] == len(result),
              f"the final progress_callback call's primes_loaded_so_far matches the "
              f"actual returned array length (got {loaded_values[-1]} vs {len(result)})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_load_magazyn_from_n():
    """[ADDED, Artur 2026-09-11: "bufor bedzie podrozowal wraz z n z
    wyprzedzeniem"] The `from_n` parameter is what lets
    extend_buffer_if_needed() fetch only the NEW primes past what's already
    loaded instead of re-reading/re-returning everything from scratch on
    every extension -- covers both halves of that: the whole-floor skip
    (floor 0 here is entirely below from_n) and the within-floor trim
    (floor 1's first window is partially below from_n)."""
    from primeatlas.ring_viz.renderer import load_magazyn

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        _write_floor(portal_dir, 0, [[2, 3, 5, 7]])
        _write_floor(portal_dir, 1, [[11, 13, 17], [19, 23, 29]])
        _write_floor(portal_dir, 2, [[101, 103, 107]])

        result = load_magazyn(portal_dir, upto=200, from_n=17)
        check(list(result) == [19, 23, 29, 101, 103, 107],
              f"from_n=17 skips floor 0 entirely (all <=17) and trims floor "
              f"1's first window down to just 19 (got {list(result)!r})")

        result_zero = load_magazyn(portal_dir, upto=200, from_n=0)
        result_default = load_magazyn(portal_dir, upto=200)
        check(list(result_zero) == list(result_default),
              "from_n=0 (explicit) reproduces the default (omitted) behavior exactly")
        check(list(result_default) == [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 101, 103, 107],
              f"sanity: the from_n=0/default baseline itself is still correct "
              f"(got {list(result_default)!r})")

        result_exhausted = load_magazyn(portal_dir, upto=200, from_n=107)
        check(len(result_exhausted) == 0,
              "from_n at the true end of stored data returns an empty array "
              "(the extend_state['exhausted'] case in extend_buffer_if_needed)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_empty_portal():
    from primeatlas.ring_viz.renderer import load_magazyn

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        os.makedirs(portal_dir, exist_ok=True)  # exists, but no 10p* floors at all
        result = load_magazyn(portal_dir, upto=1000)
        check(len(result) == 0, "load_magazyn on a portal folder with no floors returns an empty array")
        check(result.dtype == np.int64, "the empty result is still int64, not a generic empty array")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Faza 4 (see PLAN.md): build_vertex_data's window-highlight-color blending
# and hud_lines_for_n's HUD text -- both pure numpy/Python, no moderngl/glfw
# import (the module only imports those inside run(), which none of these
# tests call), so they're fully exercisable in this headless sandbox.
# Cross-checked against ring_geometry's own already-tested functions
# directly, not hand-picked expected values -- see test_ring_geometry.py's
# own docstring note about why (an earlier hand-derived-expectation mistake
# in that file, caught and fixed the same way).
# ---------------------------------------------------------------------------

def _test_build_vertex_data_no_windows_matches_old_behavior():
    from primeatlas.ring_viz.renderer import build_vertex_data
    from primeatlas.ring_geometry import ring_positions

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23], dtype=np.int64)
    n = 20
    active = primes[primes <= n]
    max_radius = 100.0

    expected_pos = ring_positions(active, n, max_radius)
    data, count, pos = build_vertex_data(active, n, max_radius)

    check(count == len(active), f"ring count matches active prime count (got {count})")
    check(np.array_equal(pos["is_hit"], expected_pos["is_hit"]),
          "returned pos dict's is_hit matches a direct ring_positions() call")
    check(np.allclose(data[:, 0], expected_pos["x"]) and np.allclose(data[:, 1], expected_pos["y"]),
          "vertex x/y matches ring_positions() output exactly")

    for i, p in enumerate(active):
        is_hit = bool(expected_pos["is_hit"][i])
        rgb = data[i, 2:5]
        if not is_hit:
            check(np.allclose(rgb, (0.0, 188 / 255, 212 / 255), atol=1e-6),
                  f"non-hit ring (prime={p}) is plain cyan with no windows enabled (got {rgb})")
        elif p >= 11:
            check(np.allclose(rgb, (1.0, 215 / 255, 0.0), atol=1e-6),
                  f"hit ring prime={p} (>=11) is gold with no windows enabled (got {rgb})")
        else:
            check(np.allclose(rgb, (1.0, 87 / 255, 34 / 255), atol=1e-6),
                  f"hit ring prime={p} (<11) is orange with no windows enabled (got {rgb})")


def _test_build_vertex_data_bertrand_highlight():
    from primeatlas.ring_viz.renderer import build_vertex_data
    from primeatlas.ring_geometry import compute_highlight_colors

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37], dtype=np.int64)
    n = 40  # bertrand window (20, 40] -- matches 23,29,31,37 among these primes
    max_radius = 100.0

    expected_colors, expected_matched = compute_highlight_colors(primes, n, {"bertrand"})
    check(expected_matched.any(), "sanity: the chosen n/primes actually produce a non-empty Bertrand match")

    data, count, _pos = build_vertex_data(primes, n, max_radius, enabled_ids={"bertrand"})
    for i, p in enumerate(primes):
        rgb = data[i, 2:5]
        if expected_matched[i]:
            expected_rgb = expected_colors[i] / 255.0
            check(np.allclose(rgb, expected_rgb, atol=1e-6),
                  f"Bertrand-matched ring prime={p} gets compute_highlight_colors' own blended "
                  f"color (got {rgb}, expected {expected_rgb})")
        else:
            check(not np.allclose(rgb, (255, 51, 204) / np.array([255.0, 255.0, 255.0]), atol=1e-6) or p > n,
                  f"non-Bertrand-matched ring prime={p} does not carry the Bertrand pink color")


def _test_build_vertex_data_track_primes_white_dot():
    """[ADDED 2026-09-11, Artur's report: with only Legendre on, the tracked/
    anchor ring's own DOT just blended into the sea of same-colored (green)
    window-member dots -- "punkt aktywnego pierscienia niech bedzie bialy
    tak samo jak jest dla aktywnego pierscienia w innych przypadkach", i.e.
    the tracked ring's POINT (not its separate outline circle, which stays
    the window's own color -- see build_tracked_outline_draws/
    tracked_outline_color, unchanged by this) should be plain white so it's
    instantly identifiable regardless of the window color around it. Covers
    the new `track_primes` param build_vertex_data now takes."""
    from primeatlas.ring_viz.renderer import build_vertex_data
    from primeatlas.ring_geometry import compute_highlight_colors

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37], dtype=np.int64)
    n = 40  # same fixture as the Bertrand-highlight test above: window (20,40]
    max_radius = 100.0

    expected_colors, expected_matched = compute_highlight_colors(primes, n, {"bertrand"})
    check(expected_matched.any(), "sanity: the chosen n/primes actually produce a non-empty Bertrand match")

    # Anchor is 23 (see _test_anchor_functions in test_ring_geometry.py's
    # own n=40 fixture) -- a genuine Bertrand-strict member, so this also
    # proves the white override WINS over the window-highlight color, not
    # just over the plain cyan/gold/orange base.
    data, count, _pos = build_vertex_data(primes, n, max_radius, enabled_ids={"bertrand"}, track_primes=[23])

    idx23 = int(np.where(primes == 23)[0][0])
    check(np.allclose(data[idx23, 2:5], (1.0, 1.0, 1.0), atol=1e-6),
          f"tracked ring (prime=23) gets a plain white dot, overriding its own Bertrand-pink "
          f"highlight color (got {data[idx23, 2:5]})")

    for i, p in enumerate(primes):
        if p == 23:
            continue
        if expected_matched[i]:
            expected_rgb = expected_colors[i] / 255.0
            check(np.allclose(data[i, 2:5], expected_rgb, atol=1e-6),
                  f"non-tracked ring prime={p} keeps its normal window-highlight color, "
                  f"unaffected by the other ring's white override (got {data[i, 2:5]})")

    # track_primes=() (the default) reproduces the exact prior behavior --
    # no white anywhere, identical to the plain Bertrand-highlight test above.
    data_no_track, _count2, _pos2 = build_vertex_data(primes, n, max_radius, enabled_ids={"bertrand"})
    check(not np.allclose(data_no_track[idx23, 2:5], (1.0, 1.0, 1.0), atol=1e-6),
          "with no track_primes given (the default), ring 23 is NOT forced white -- it just "
          "keeps its normal Bertrand highlight color")
    check(np.array_equal(data_no_track[:, 2:5], data[:, 2:5]) is False,
          "sanity: the two calls above actually produced different output (the white override "
          "did something observable)")


def _test_split_hit_normal_vertex_data():
    from primeatlas.ring_viz.renderer import build_vertex_data, split_hit_normal_vertex_data

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23], dtype=np.int64)
    n = 20  # hits (divisors of 20): 2, 5 -- everything else is a normal ring
    active = primes[primes <= n]
    data, count, pos = build_vertex_data(active, n, 100.0)

    data_normal, data_hit, count_hit = split_hit_normal_vertex_data(data, pos["is_hit"])
    expected_hit = int(np.count_nonzero(pos["is_hit"]))
    check(count_hit == expected_hit, f"count_hit matches pos['is_hit']'s own true-count (got {count_hit}, expected {expected_hit})")
    check(data_hit.shape[0] == count_hit and data_normal.shape[0] == count - count_hit,
          f"row counts add up: hit={data_hit.shape[0]}, normal={data_normal.shape[0]}, total={count} "
          f"(expected hit={count_hit}, normal={count - count_hit})")
    # Every hit row's (x, y) must appear in expected_pos's hit-masked rows and
    # nowhere in the normal split, and vice versa -- proves the split didn't
    # scramble which row went where (not just that the counts happen to add up).
    hit_xy_expected = set(zip(data[pos["is_hit"], 0].tolist(), data[pos["is_hit"], 1].tolist()))
    hit_xy_actual = set(zip(data_hit[:, 0].tolist(), data_hit[:, 1].tolist()))
    check(hit_xy_actual == hit_xy_expected,
          f"data_hit contains exactly the rows pos['is_hit'] marks true, no more/fewer/wrong (got {hit_xy_actual}, expected {hit_xy_expected})")

    # Empty-array edge case (0 active rings, e.g. after R/reset lands N=1) --
    # must not raise, and must return an empty (not error-triggering) split.
    empty_data = np.empty((0, 5), dtype=np.float32)
    empty_mask = np.empty((0,), dtype=bool)
    d_normal, d_hit, c_hit = split_hit_normal_vertex_data(empty_data, empty_mask)
    check(d_normal.shape[0] == 0 and d_hit.shape[0] == 0 and c_hit == 0,
          f"0 active rings splits into two empty arrays and count_hit=0, no crash (got normal={d_normal.shape[0]}, hit={d_hit.shape[0]}, count_hit={c_hit})")


def _test_hud_lines_for_n():
    from primeatlas.ring_viz.renderer import hud_lines_for_n, build_vertex_data
    from primeatlas.ring_geometry import legendre_level_at, general_law_window_bounds

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37], dtype=np.int64)
    n = 30  # divisible by 2, 3, 5 among these primes -- a real "factors of N" case
    max_radius = 100.0
    enabled_ids = {"bertrand", "legendre", "generalLaw"}
    theta, mode = 0.5, "stepped"

    _data, _count, pos = build_vertex_data(primes, n, max_radius, enabled_ids, theta, mode)
    lines = hud_lines_for_n(primes, n, pos, enabled_ids, theta, mode)
    joined = "\n".join(lines)

    expected_factors = [int(p) for p in primes if n % int(p) == 0]
    check(bool(expected_factors), "sanity: n=30 has at least one active-prime factor among the test primes")
    check(any(str(f) in joined for f in expected_factors) and "Factors of N" in joined,
          f"hud_lines_for_n includes a 'Factors of N' line mentioning the real divisors "
          f"(expected {expected_factors}, got lines={lines!r})")

    lo_bertrand = n // 2
    check(f"({lo_bertrand:,}, {n:,}]" in joined,
          f"Bertrand window range text uses the real (floor(n/2), n] bounds (got lines={lines!r})")

    k = legendre_level_at(n)
    check(f"k={k}" in joined and f"({k * k:,}, {n:,}]" in joined,
          f"Legendre window range text uses legendre_level_at's own k and k^2 bound "
          f"(got lines={lines!r})")

    lo, hi, gl_k, _factor = general_law_window_bounds(n, theta, mode)
    lo_floor = int(np.floor(lo))
    check(f"({lo_floor:,}, {hi:,}]" in joined,
          f"General Law window range text uses general_law_window_bounds' own lo/hi "
          f"(got lines={lines!r})")

    # No enabled families, no divisors -> no lines at all (n prime, e.g. 31 is
    # itself an active prime here, so it IS a factor of itself -- pick a
    # value with none of the test primes dividing it and no families on).
    _data2, _count2, pos2 = build_vertex_data(primes, 41, max_radius, set(), theta, mode)
    empty_lines = hud_lines_for_n(primes, 41, pos2, set(), theta, mode)
    check(empty_lines == [], f"no enabled families and no active-prime factors -> no HUD lines (got {empty_lines!r})")


def _test_initial_n_for_source():
    """[ADDED, see Artur's 2026-09-04 bug report] run() must open the ring
    view on the N the user actually asked for, not on the last loaded prime.
    Regression test for initial_n_for_source()'s extraction of that fix --
    see that function's own docstring for the full bug description."""
    from primeatlas.ring_viz.renderer import initial_n_for_source

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37], dtype=np.int64)

    # sieve/magazyn: real user-specified upto (e.g. 1000, typed in rings_tab's
    # N field) -- must open exactly there, even though 1000 itself isn't
    # prime and the largest actual prime <=1000 among these primes is 37.
    check(initial_n_for_source("magazyn", 1000, primes) == 1000,
          "source=magazyn opens on --upto verbatim, not primes[-1] (was the bug: "
          "typing 1000 silently opened on 997/whatever the largest loaded prime was)")
    check(initial_n_for_source("sieve", 1000, primes) == 1000,
          "source=sieve opens on --upto verbatim too (same real-target-N semantics as magazyn)")

    # An upto that happens to BE prime should still just be itself, not
    # accidentally "work" only by coincidence.
    check(initial_n_for_source("magazyn", 37, primes) == 37,
          "source=magazyn with a prime --upto still returns --upto itself, not primes[-1]")

    # synthetic: no real user-specified N (only --count) -- keeps the old
    # primes[-1] behavior, since there is nothing else meaningful to open on.
    check(initial_n_for_source("synthetic", 1000, primes) == int(primes[-1]),
          f"source=synthetic still opens on the last generated value (got "
          f"{initial_n_for_source('synthetic', 1000, primes)}, expected {int(primes[-1])})")

    empty = np.empty(0, dtype=np.int64)
    check(initial_n_for_source("synthetic", 1000, empty) == 0,
          "source=synthetic with an empty array falls back to 0, does not crash")
    check(initial_n_for_source("magazyn", 1000, empty) == 1000,
          "source=magazyn with an empty array still opens on --upto (an empty ring field "
          "at the requested N, not a crash or a silent fallback to 0)")


def _test_zoom_to_point():
    """[ADDED, see Artur's 2026-09-04 bug report] Regression test for
    zoom_to_point()'s fix -- see that function's own docstring for the full
    before/after bug description (old on_scroll only multiplied zoom, never
    adjusted pan, so every zoom anchored on the ring field's mathematical
    center instead of the cursor -- zooming in on a panned-to tail raced
    back toward the center, zooming out flew the view away entirely)."""
    from primeatlas.ring_viz.renderer import zoom_to_point

    # Core invariant: whatever world-space point sits under `cursor` before
    # the zoom must map back to that SAME screen point after the zoom, for
    # any old_zoom/old_pan/cursor/factor combination -- that's the actual
    # definition of "zoom to cursor".
    cases = [
        (1.0, (400.0, 300.0), (400.0, 300.0), (800.0, 600.0), 1.1),   # cursor at screen/viewport center
        (1.0, (400.0, 300.0), (700.0, 550.0), (800.0, 600.0), 1.1),   # cursor near a corner, zooming in
        (2.5, (100.0, 900.0), (50.0, 20.0), (800.0, 600.0), 1 / 1.1), # panned far off-origin, zooming out
        (0.3, (-500.0, 1200.0), (0.0, 0.0), (800.0, 600.0), 1.1),     # extreme pan+zoom, cursor at origin
    ]
    for old_zoom, old_pan, cursor, viewport, factor in cases:
        cx, cy = cursor
        old_pan_x, old_pan_y = old_pan
        world_x = (cx - old_pan_x) / old_zoom
        world_y = (cy - old_pan_y) / old_zoom

        new_zoom, new_pan = zoom_to_point(old_zoom, old_pan, cursor, viewport, factor)
        new_pan_x, new_pan_y = new_pan

        check(abs(new_zoom - old_zoom * factor) < 1e-9,
              f"zoom itself still scales by factor exactly (old={old_zoom}, factor={factor}, "
              f"got new_zoom={new_zoom})")

        screen_after_x = world_x * new_zoom + new_pan_x
        screen_after_y = world_y * new_zoom + new_pan_y
        check(abs(screen_after_x - cx) < 1e-6 and abs(screen_after_y - cy) < 1e-6,
              f"the world point under the cursor before the zoom stays under the cursor "
              f"after it (cursor={cursor}, old_zoom={old_zoom}, old_pan={old_pan}, factor={factor}: "
              f"world=({world_x},{world_y}) maps to screen=({screen_after_x},{screen_after_y}) "
              f"after zoom, expected ({cx},{cy}))")

    # Regression check for the OLD (buggy) behavior specifically: with the
    # bug, new_pan == old_pan always (pan never adjusted) -- confirm the fix
    # actually changes pan whenever the cursor isn't exactly at world (0,0)'s
    # current screen position (the one case where old and new coincidentally
    # agree, since that point's own zoom-anchor never needed correcting).
    old_zoom, old_pan, cursor, viewport, factor = 1.0, (400.0, 300.0), (700.0, 550.0), (800.0, 600.0), 1.1
    _new_zoom, new_pan = zoom_to_point(old_zoom, old_pan, cursor, viewport, factor)
    check(new_pan != old_pan,
          f"pan is actually adjusted by the zoom (not left untouched, which was the bug) -- "
          f"got new_pan={new_pan}, old_pan={old_pan}")


def _test_fit_zoom_for_viewport():
    """[ADDED, Artur 2026-09-11: "przejście w tryb pełnoekranowy jak i
    okienkowy wizualizację ustawiało na wartości zoom tak by zajmowało pełną
    wysokość okna lub szerokość jeśli okno będzie węższe od wysokości"] --
    fit_zoom_for_viewport() is the pure computation behind both the F11
    fullscreen<->windowed re-fit and the middle-click recenter action."""
    from primeatlas.ring_viz.renderer import fit_zoom_for_viewport, _FIT_MARGIN

    max_radius = 900.0  # e.g. min(1920, 1080) * 0.45, a plausible real launch size

    # Landscape viewport (wider than tall): the SMALLER dimension (height)
    # is the constraint -- "fills the full height" per Artur's own wording.
    zoom = fit_zoom_for_viewport(max_radius, 1920.0, 1080.0)
    expected = (1080.0 * _FIT_MARGIN) / max_radius
    check(abs(zoom - expected) < 1e-9,
          f"landscape viewport (1920x1080): height is the limiting/smaller dimension, "
          f"got zoom={zoom}, expected={expected}")

    # Portrait viewport (narrower than tall): now WIDTH is the smaller
    # dimension -- "or width if the window is narrower than tall".
    zoom = fit_zoom_for_viewport(max_radius, 600.0, 1200.0)
    expected = (600.0 * _FIT_MARGIN) / max_radius
    check(abs(zoom - expected) < 1e-9,
          f"portrait viewport (600x1200): width is the limiting/smaller dimension, "
          f"got zoom={zoom}, expected={expected}")

    # Square viewport: either dimension is equally the constraint (same
    # value either way), just confirms no landscape/portrait branch bug.
    zoom = fit_zoom_for_viewport(max_radius, 1000.0, 1000.0)
    expected = (1000.0 * _FIT_MARGIN) / max_radius
    check(abs(zoom - expected) < 1e-9,
          f"square viewport: width == height == the constraint, got zoom={zoom}, expected={expected}")

    # Core invariant tying this function back to how max_radius itself is
    # computed at launch (max_radius = min(args.width, args.height) *
    # _FIT_MARGIN, see _run_visualization): re-fitting to the EXACT launch
    # window size must return zoom == 1.0 exactly -- "the view as it already
    # opens" and "the view after an explicit re-fit" are provably the same
    # computation, not two independently hand-tuned constants that could
    # drift apart over time.
    launch_width, launch_height = 1920.0, 1080.0
    launch_max_radius = min(launch_width, launch_height) * _FIT_MARGIN
    zoom = fit_zoom_for_viewport(launch_max_radius, launch_width, launch_height)
    check(abs(zoom - 1.0) < 1e-9,
          f"re-fitting to the exact launch window size reproduces the launch zoom (1.0) exactly, "
          f"got {zoom}")

    # Degenerate inputs fall back to 1.0 rather than raising or returning
    # something nonsensical (a transient 0-sized framebuffer during a
    # resize is the realistic trigger for this, not user-facing input).
    check(fit_zoom_for_viewport(0.0, 1920.0, 1080.0) == 1.0,
          "max_radius <= 0 falls back to zoom=1.0")
    check(fit_zoom_for_viewport(max_radius, 0.0, 1080.0) == 1.0,
          "width <= 0 falls back to zoom=1.0")
    check(fit_zoom_for_viewport(max_radius, 1920.0, 0.0) == 1.0,
          "height <= 0 falls back to zoom=1.0")

    # A custom margin is honored (not hardcoded past its default parameter).
    zoom_default = fit_zoom_for_viewport(max_radius, 1920.0, 1080.0)
    zoom_custom = fit_zoom_for_viewport(max_radius, 1920.0, 1080.0, margin=0.9)
    check(abs(zoom_custom - zoom_default * 2.0) < 1e-9,
          f"doubling margin (0.45 -> 0.9) doubles the resulting zoom, "
          f"got default={zoom_default}, custom={zoom_custom}")


def _test_filter_active_tracked():
    """[ADDED Faza 6, see PLAN.md] filter_active_tracked's own docstring:
    preserves tracked's order (not active_primes's), keeps duplicates as
    typed, drops anything not yet active."""
    from primeatlas.ring_geometry import filter_active_tracked

    active = np.array([2, 3, 5, 7, 11], dtype=np.int64)

    result = filter_active_tracked([7, 2, 11], active)
    check(result == [7, 2, 11],
          f"preserves the caller's own order, not active_primes's ascending order "
          f"(got {result!r})")

    result_not_yet_active = filter_active_tracked([2, 13, 17], active)
    check(result_not_yet_active == [2],
          f"primes not yet active (born) at this N are dropped, only 2 survives "
          f"(got {result_not_yet_active!r})")

    result_dupes = filter_active_tracked([3, 3, 5], active)
    check(result_dupes == [3, 3, 5],
          f"duplicates in the tracked list are preserved as typed, not deduped "
          f"(got {result_dupes!r})")

    result_empty_tracked = filter_active_tracked([], active)
    check(result_empty_tracked == [], f"empty tracked list -> empty result (got {result_empty_tracked!r})")

    result_empty_active = filter_active_tracked([2, 3], [])
    check(result_empty_active == [], f"empty active set -> empty result (got {result_empty_active!r})")

    check(all(isinstance(p, int) for p in result),
          f"returns plain Python ints, not numpy scalars (got types {[type(p) for p in result]!r})")


def _test_hud_lines_for_n_tracked_state():
    """[ADDED Faza 6, EXTENDED Faza 7B, see PLAN.md] hud_lines_for_n's
    tracked_state param (renamed/extended from Faza 6's tracked_active --
    see hud_lines_for_n's own doc-comment): None means no lines at all, a
    too_large dict produces the single overflow line, and a real state dict
    produces the full tracked/LCM/phase/to-resonance block, using format_big
    for the numeric values."""
    from primeatlas.ring_viz.renderer import hud_lines_for_n, build_vertex_data
    from primeatlas.ring_geometry import tracked_resonance_state

    primes = np.array([2, 3, 5, 7, 11, 13], dtype=np.int64)
    n = 41
    max_radius = 100.0
    _data, _count, pos = build_vertex_data(primes, n, max_radius, set(), 0.5, "stepped")

    lines_none = hud_lines_for_n(primes, n, pos, set(), 0.5, "stepped")
    check(not any("Tracked" in line for line in lines_none),
          f"no tracked_state given -> no 'Tracked' HUD line at all (got {lines_none!r})")

    lines_none2 = hud_lines_for_n(primes, n, pos, set(), 0.5, "stepped", tracked_state=None)
    check(not any("Tracked" in line for line in lines_none2),
          f"explicit tracked_state=None -> no 'Tracked' HUD line (got {lines_none2!r})")

    too_large = {"too_large": True, "tracked": [2, 3, 5], "limit": 2}
    lines_large = hud_lines_for_n(primes, n, pos, set(), 0.5, "stepped", tracked_state=too_large)
    joined_large = "\n".join(lines_large)
    check("too many active" in joined_large and "3" in joined_large and "2" in joined_large,
          f"too_large state produces a single overflow-explanation line, no LCM/phase "
          f"attempted (got lines={lines_large!r})")

    state = tracked_resonance_state([7, 2], primes, n)
    check(state is not None, "sanity: 7 and 2 are both active at n=41")
    lines_full = hud_lines_for_n(primes, n, pos, set(), 0.5, "stepped", tracked_state=state)
    joined_full = "\n".join(lines_full)
    check("Tracked (active): 7, 2" in joined_full,
          f"full state produces the tracked-list line in the state's own order "
          f"(got lines={lines_full!r})")
    check(f"LCM: {state['lcm']}" in joined_full, f"LCM line uses the state's lcm (got lines={lines_full!r})")
    check(f"Phase: {state['phase']} / {state['lcm']}" in joined_full,
          f"phase line shows phase / lcm (got lines={lines_full!r})")
    check(f"To resonance: {state['to_resonance']}" in joined_full,
          f"to-resonance line uses the state's own value (got lines={lines_full!r})")


def _test_lcm_of_list():
    """[ADDED Faza 7A, see PLAN.md] Mirrors SieveModel.js's lcmOfList/
    lcmOfListBig: 0 for empty, exact product-based LCM otherwise (duplicates
    and non-coprime values handled correctly, not just pairwise-coprime
    primes)."""
    from primeatlas.ring_geometry import lcm_of_list

    check(lcm_of_list([]) == 0, f"empty list -> 0, not 1 (matches JS's lcmOfList/lcmOfListBig) (got {lcm_of_list([])!r})")
    check(lcm_of_list([2, 3, 5]) == 30, f"LCM of pairwise-coprime primes is their product (got {lcm_of_list([2, 3, 5])!r})")
    check(lcm_of_list([4, 6]) == 12, f"LCM of non-coprime values is exact, not naive product (got {lcm_of_list([4, 6])!r})")
    check(lcm_of_list([7, 7, 7]) == 7, f"duplicates don't inflate the LCM (got {lcm_of_list([7, 7, 7])!r})")
    big = lcm_of_list(list(range(2, 100)))
    check(isinstance(big, int) and big > 10**20,
          f"large tracked lists produce an exact arbitrary-precision int, no overflow "
          f"(got type {type(big)!r}, value has {len(str(big))} digits)")


def _test_tracked_resonance_state():
    """[ADDED Faza 7A, see PLAN.md] Port of StructuralSieveApp.js's
    #trackedResonanceState -- mirrors its None-return conditions (auto_orbit,
    empty tracked, none active), too_large case, and the phase/to_resonance
    math itself."""
    from primeatlas.ring_geometry import tracked_resonance_state

    active = [2, 3, 5, 7, 11]

    check(tracked_resonance_state([2, 3], active, 100, auto_orbit=True) is None,
          "auto_orbit=True always returns None, regardless of tracked/active")
    check(tracked_resonance_state([], active, 100) is None, "empty tracked list -> None")
    check(tracked_resonance_state([13, 17], active, 100) is None,
          "tracked primes that aren't active yet at this N -> None")

    state = tracked_resonance_state([2, 3, 5], active, 100)
    check(state is not None and state["lcm"] == 30,
          f"LCM of the tracked-and-active primes (got {state!r})")
    check(state["phase"] == 100 % 30, f"phase = n mod lcm (got {state!r})")
    check(state["to_resonance"] == 30 - (100 % 30),
          f"to_resonance = lcm - phase when phase != 0 (got {state!r})")

    state_exact = tracked_resonance_state([2, 3, 5], active, 90)
    check(state_exact["phase"] == 0 and state_exact["to_resonance"] == 0,
          f"phase=0 at an exact multiple of the LCM gives to_resonance=0, not lcm "
          f"(got {state_exact!r})")

    state_partial = tracked_resonance_state([2, 13], active, 100)
    check(state_partial is not None and state_partial["tracked"] == [2],
          f"only the active subset of tracked is used, order preserved "
          f"(got {state_partial!r})")

    too_large = tracked_resonance_state([2, 3, 5], active, 100, max_tracked_for_exact_lcm=2)
    check(too_large == {"too_large": True, "tracked": [2, 3, 5], "limit": 2},
          f"exceeding max_tracked_for_exact_lcm returns the too_large marker instead "
          f"of computing the LCM (got {too_large!r})")


def _test_format_big():
    """[ADDED Faza 7A, see PLAN.md] Port of StructuralSieveApp.js's
    #formatBig -- plain digits below the threshold, mantissa×10^exp (N
    digits) past it, sign handled either way."""
    from primeatlas.ring_geometry import format_big

    check(format_big(0) == "0", f"zero (got {format_big(0)!r})")
    check(format_big(30) == "30", f"small positive value stays a plain digit string (got {format_big(30)!r})")
    check(format_big(-30) == "-30", f"small negative value keeps its sign, plain digits (got {format_big(-30)!r})")

    fourteen_nines = int("9" * 14)
    check(format_big(fourteen_nines, digit_threshold=15) == str(fourteen_nines),
          "exactly at the threshold (14 <= 15) still prints plain digits")

    big = int("123456789" * 6)  # 54 digits, well past the default threshold
    formatted = format_big(big, digit_threshold=15)
    check("×10^" in formatted and formatted.endswith(f"({len(str(big))} digits)"),
          f"past the threshold, switches to mantissa×10^exponent (N digits) "
          f"(got {formatted!r})")
    check(formatted.startswith("1.234"), f"mantissa uses the first digit + next 4 (got {formatted!r})")

    formatted_neg = format_big(-big, digit_threshold=15)
    check(formatted_neg.startswith("-1.234"), f"sign preserved past the threshold too (got {formatted_neg!r})")


# ---------------------------------------------------------------------------
# Faza 8 (see PLAN.md): tracked-ring outline circles, center marker, flash
# overlays. Only the PURE GEOMETRY/COLOR/DECAY math is tested here -- the
# actual GL draw calls in run() need a real GPU/display this sandbox does
# not have (see PLAN.md's own Faza 8 risk note), same split as every other
# GL-adjacent phase in this file.
# ---------------------------------------------------------------------------

def _test_tracked_ring_mask():
    """[ADDED Faza 8] ring_geometry.tracked_ring_mask -- plain per-ring list
    membership (DrumRenderer's `ring.tracked`), a different question from
    filter_active_tracked (which returns tracked VALUES, not a mask)."""
    from primeatlas.ring_geometry import tracked_ring_mask

    active = np.array([2, 3, 5, 7, 11], dtype=np.int64)
    mask = tracked_ring_mask(active, [7, 2])
    check(list(mask) == [True, False, False, True, False],
          f"marks exactly the rings whose prime is in the tracked list, in `active`'s own "
          f"order (got {list(mask)!r})")

    empty_tracked = tracked_ring_mask(active, [])
    check(not empty_tracked.any() and len(empty_tracked) == len(active),
          f"empty tracked list -> all-False mask of the right length (got {list(empty_tracked)!r})")

    empty_active = tracked_ring_mask(np.empty(0, dtype=np.int64), [2, 3])
    check(len(empty_active) == 0, f"empty active array -> empty mask (got {list(empty_active)!r})")

    none_active_match = tracked_ring_mask(active, [13, 17])
    check(not none_active_match.any(),
          f"tracked primes not present among active rings at all -> all-False (got {list(none_active_match)!r})")


def _test_unit_circle_vertices():
    """[ADDED Faza 8] unit_circle_vertices -- every point on the unit circle,
    ascending angle from 0, first point at angle 0 (i.e. (1,0))."""
    from primeatlas.ring_viz.renderer import unit_circle_vertices

    verts = unit_circle_vertices(segments=8)
    check(verts.shape == (8, 2), f"returns (segments, 2) shaped array (got shape {verts.shape})")
    check(verts.dtype == np.float32, f"float32, ready for a GL buffer (got dtype {verts.dtype})")
    check(np.allclose(verts[0], (1.0, 0.0), atol=1e-6), f"first point is angle 0 -> (1,0) (got {verts[0]!r})")
    radii = np.sqrt(verts[:, 0] ** 2 + verts[:, 1] ** 2)
    check(np.allclose(radii, 1.0, atol=1e-6), f"every point lies exactly on the unit circle (got radii {radii!r})")


def _test_tracked_outline_color():
    """[CHANGED 2026-09-10, see Artur's report: with only one window family
    enabled, the HUD's own window-range label already shows that family's
    full color (window_label_colors), so the matching tracked-ring outline
    should too -- "skoro okno w hud ma kolor to pierscien niech go tez ma
    tak samo". This is now a deliberate departure from the original site's
    own `(state.activeWindowCount > 1 && ring.trackedColor) ? ... : gray`
    gate (see tracked_outline_color's own doc-comment) -- `matched` alone
    now decides the color, `active_window_count` is no longer a parameter
    at all."""
    from primeatlas.ring_viz.renderer import tracked_outline_color

    gray = tracked_outline_color(False, (255.0, 51.0, 204.0))
    check(gray == (180 / 255.0, 180 / 255.0, 180 / 255.0, 0.5),
          f"not matched -> flat gray regardless of the color that would have been used (got {gray!r})")

    # [CHANGED 2026-09-10] Exactly ONE window family enabled and matched --
    # used to fall back to gray (activeWindowCount > 1 was required); now
    # gets that single family's own color, same as the HUD label does.
    colored_single_window = tracked_outline_color(True, (255.0, 51.0, 204.0))
    check(colored_single_window == (1.0, 51 / 255.0, 204 / 255.0, 0.5),
          f"matched with only a single window family active now gets that family's "
          f"own color, not gray (got {colored_single_window!r})")

    colored = tracked_outline_color(True, (255.0, 51.0, 204.0))
    check(colored == (1.0, 51 / 255.0, 204 / 255.0, 0.5),
          f"matched -> the family's own (or blended) color at alpha 0.5 (got {colored!r})")


def _test_resolve_effective_track_primes():
    """[ADDED, see Artur's 2026-09-10 bug report: "pierscienie sa dla
    sledzonych i dla auto orbit ale nie ma dla bertranda legendre i dla
    general law"] resolve_effective_track_primes's own docstring: window
    anchors win outright whenever any family is on (even an empty anchor
    list), else auto-orbit's current pick, else the plain track_primes
    fallback -- exact precedence ported from StructuralSieveApp.js's
    #renderFrame."""
    from primeatlas.ring_viz.renderer import resolve_effective_track_primes

    # Any window family on -> window_anchors wins, regardless of auto_orbit
    # or track_primes both also being populated.
    result = resolve_effective_track_primes(
        window_anchors=[23, 31], enabled_ids={"bertrand", "legendre"},
        auto_orbit=True, orbit_current_prime=7, track_primes=[2, 3])
    check(result == [23, 31],
          f"window anchors take precedence over both auto-orbit and track_primes (got {result!r})")

    # A window family on but not yet resolved to any anchor -> empty list
    # wins outright too (matches the JS's unconditional overwrite, not a
    # "fall through if empty" special case).
    result_empty_anchor = resolve_effective_track_primes(
        window_anchors=[], enabled_ids={"generalLaw"},
        auto_orbit=True, orbit_current_prime=7, track_primes=[2, 3])
    check(result_empty_anchor == [],
          f"an active window family with no resolved anchor yet still wins outright with "
          f"an empty list, does not fall back to auto-orbit or track_primes (got {result_empty_anchor!r})")

    # No window family on, auto-orbit on -> its current pick, as a single-item list.
    result_orbit = resolve_effective_track_primes(
        window_anchors=[], enabled_ids=set(),
        auto_orbit=True, orbit_current_prime=17, track_primes=[2, 3])
    check(result_orbit == [17], f"no window family on -> auto-orbit's current pick (got {result_orbit!r})")

    # No window family on, auto-orbit on but with no current pick yet (e.g.
    # a single-prime active set, see advance_auto_orbit's own no-op case).
    result_orbit_none = resolve_effective_track_primes(
        window_anchors=[], enabled_ids=set(),
        auto_orbit=True, orbit_current_prime=None, track_primes=[2, 3])
    check(result_orbit_none == [],
          f"auto-orbit on but no current pick resolved yet -> empty, not a crash or "
          f"fallback to track_primes (got {result_orbit_none!r})")

    # Neither window family nor auto-orbit on -> the plain launch-time
    # --track-primes / Track P field list passes through unchanged.
    result_manual = resolve_effective_track_primes(
        window_anchors=[], enabled_ids=set(),
        auto_orbit=False, orbit_current_prime=None, track_primes=[5, 11])
    check(result_manual == [5, 11],
          f"neither window family nor auto-orbit on -> plain track_primes list (got {result_manual!r})")

    # Nothing at all active -> empty list, not None or an error.
    result_nothing = resolve_effective_track_primes(
        window_anchors=[], enabled_ids=set(),
        auto_orbit=False, orbit_current_prime=None, track_primes=[])
    check(result_nothing == [], f"nothing active at all -> empty list (got {result_nothing!r})")


def _test_build_tracked_outline_draws():
    """[ADDED Faza 8, CHANGED 2026-09-10] build_tracked_outline_draws -- one
    (radius, rgba) tuple per tracked-and-active ring, using
    compute_tracked_colors under the hood, matching tracked_outline_color's
    own gating rules (matched -> colored, unmatched/no-window -> gray;
    see that function's own doc-comment for the 2026-09-10 change dropping
    the old ">1 window family" requirement)."""
    from primeatlas.ring_viz.renderer import build_tracked_outline_draws
    from primeatlas.ring_geometry import ring_positions, bertrand_anchor_at, WINDOW_FAMILY_COLORS

    primes = np.array([2, 3, 5, 7, 11], dtype=np.int64)
    n = 10
    max_radius = 100.0
    pos = ring_positions(primes, n, max_radius)

    no_tracked = build_tracked_outline_draws(primes, n, set(), 0.5, "stepped", [], pos["radius"])
    check(no_tracked == [], f"no tracked primes -> no draws at all (got {no_tracked!r})")

    draws = build_tracked_outline_draws(primes, n, set(), 0.5, "stepped", [7, 2], pos["radius"])
    check(len(draws) == 2, f"one draw per tracked-and-active ring (got {len(draws)} draws: {draws!r})")
    radii_drawn = sorted(r for r, _c in draws)
    expected_radii = sorted(float(pos["radius"][i]) for i, p in enumerate(primes) if p in (2, 7))
    check(np.allclose(radii_drawn, expected_radii),
          f"each draw's radius matches that ring's own ring_positions() radius "
          f"(got {radii_drawn!r}, expected {expected_radii!r})")
    check(all(c == (180 / 255.0, 180 / 255.0, 180 / 255.0, 0.5) for _r, c in draws),
          f"no window families enabled -> every tracked outline is the flat gray fallback "
          f"(got colors {[c for _r, c in draws]!r})")

    not_active = build_tracked_outline_draws(primes, n, set(), 0.5, "stepped", [13, 17], pos["radius"])
    check(not_active == [], f"tracked primes not active yet -> no draws (got {not_active!r})")

    # [ADDED 2026-09-10, see Artur's report] Exactly ONE window family
    # enabled: the tracked prime that IS that family's own anchor must get
    # its full solid color end-to-end through build_tracked_outline_draws,
    # not gray -- this is the real regression case (tracked_outline_color's
    # own unit test covers the same rule in isolation; this covers the
    # whole pipeline that used to silently re-introduce activeWindowCount).
    anchor = bertrand_anchor_at(primes, n)
    check(anchor is not None, "sanity: n=10 already has a resolved Bertrand anchor")
    single_window_draws = build_tracked_outline_draws(primes, n, {"bertrand"}, 0.5, "stepped", [int(anchor)], pos["radius"])
    check(len(single_window_draws) == 1, f"exactly one tracked-and-active ring (got {single_window_draws!r})")
    expected_rgb = tuple(c / 255.0 for c in WINDOW_FAMILY_COLORS["bertrand"])
    check(single_window_draws[0][1] == expected_rgb + (0.5,),
          f"with only Bertrand enabled, its own anchor ring gets Bertrand's full color, "
          f"not gray (got {single_window_draws[0][1]!r}, expected {expected_rgb + (0.5,)!r})")


def _test_center_marker_triangle_offsets():
    """[ADDED Faza 8] center_marker_triangle_offsets -- ports DrumRenderer's
    #drawCenterMarker fixed arrow shape: tip at the anchor itself, two back
    corners at (+-12s, -35s)."""
    from primeatlas.ring_viz.renderer import center_marker_triangle_offsets

    offsets = center_marker_triangle_offsets(2.0)
    check(offsets.shape == (3, 2), f"three (dx, dy) offsets (got shape {offsets.shape})")
    check(tuple(offsets[0]) == (0.0, 0.0), f"tip offset is (0,0) -- at the anchor itself (got {offsets[0]!r})")
    check(tuple(offsets[1]) == (-24.0, -70.0) and tuple(offsets[2]) == (24.0, -70.0),
          f"back corners scale linearly with s (s=2.0 -> +-24, -70) (got {offsets[1]!r}, {offsets[2]!r})")


def _test_marker_device_scale():
    """[ADDED Faza 8] marker_device_scale -- ports DrumRenderer's
    `s = min(w, h) / REFERENCE_MIN_DIM` (REFERENCE_MIN_DIM = 2160)."""
    from primeatlas.ring_viz.renderer import marker_device_scale

    check(abs(marker_device_scale(3840, 2160) - 1.0) < 1e-9,
          f"the JS's own reference resolution (3840x2160) gives scale 1.0 (got {marker_device_scale(3840, 2160)!r})")
    check(abs(marker_device_scale(1600, 1000) - (1000 / 2160)) < 1e-9,
          f"uses min(w,h) (got {marker_device_scale(1600, 1000)!r}, expected {1000 / 2160!r})")


def _test_build_center_marker_vertex_data():
    """[ADDED Faza 8] build_center_marker_vertex_data -- triangle at the
    anchor with the right offsets/color, line from the anchor straight up to
    screen y=0."""
    from primeatlas.ring_viz.renderer import build_center_marker_vertex_data

    triangle, line = build_center_marker_vertex_data(cx=400.0, cy=300.0, s=1.0)
    check(triangle.shape == (3, 6) and line.shape == (2, 6),
          f"triangle has 3 vertices, line has 2, both (pos.xy, color.rgba) (got shapes "
          f"{triangle.shape!r}, {line.shape!r})")
    check(tuple(triangle[0, :2]) == (400.0, 300.0), f"triangle tip sits exactly at the anchor (got {triangle[0, :2]!r})")
    check(tuple(line[0, :2]) == (400.0, 300.0) and tuple(line[1, :2]) == (400.0, 0.0),
          f"line runs from the anchor straight up to screen y=0, same x (got {line[:, :2]!r})")
    check(triangle[0, 5] == 1.0, f"triangle fill is fully opaque (alpha=1.0) (got alpha={triangle[0, 5]!r})")
    check(0.0 < line[0, 5] < 1.0, f"line is semi-transparent (got alpha={line[0, 5]!r})")


def _test_build_flash_quad_vertex_data():
    """[ADDED Faza 8] build_flash_quad_vertex_data -- 4 corners covering the
    full viewport, all sharing the given rgba."""
    from primeatlas.ring_viz.renderer import build_flash_quad_vertex_data

    quad = build_flash_quad_vertex_data(800.0, 600.0, (1.0, 0.5, 0.0, 0.25))
    check(quad.shape == (4, 6), f"4 vertices, (pos.xy, color.rgba) each (got shape {quad.shape})")
    corners = {tuple(quad[i, :2]) for i in range(4)}
    check(corners == {(0.0, 0.0), (800.0, 0.0), (800.0, 600.0), (0.0, 600.0)},
          f"the four corners exactly cover the given viewport (got {corners!r})")
    check(all(tuple(quad[i, 2:6]) == (1.0, 0.5, 0.0, 0.25) for i in range(4)),
          f"every vertex shares the same flat color (got {[tuple(quad[i, 2:6]) for i in range(4)]!r})")


def _test_decay_flash():
    """[ADDED Faza 8] decay_flash -- ports DrumRenderer's own
    `value *= factor; if (value < 0.01) value = 0;` epsilon-snap exactly."""
    from primeatlas.ring_viz.renderer import decay_flash

    check(abs(decay_flash(1.0, 0.65) - 0.65) < 1e-9, f"one frame of 0.65 decay from 1.0 (got {decay_flash(1.0, 0.65)!r})")
    check(decay_flash(0.001, 0.65) == 0.0, f"snaps to exactly 0 once below the 0.01 epsilon (got {decay_flash(0.001, 0.65)!r})")
    check(decay_flash(0.0, 0.85) == 0.0, "already-zero stays zero")

    # Repeated decay from 1.0 must reach exactly 0.0 in finite steps (not
    # asymptotically hover just above it forever) -- the epsilon snap is
    # what guarantees the flash overlay actually stops drawing eventually.
    v = 1.0
    steps = 0
    while v > 0.0 and steps < 1000:
        v = decay_flash(v, 0.65)
        steps += 1
    check(v == 0.0 and steps < 1000, f"decay reaches exactly 0.0 in a bounded number of steps (got steps={steps}, final={v!r})")


def _test_flash_overlay_rgba():
    """[ADDED Faza 8] flash_overlay_rgba -- ports DrumRenderer's
    #drawFlashOverlay: alpha = flash_value * max_alpha, color unchanged."""
    from primeatlas.ring_viz.renderer import flash_overlay_rgba, _FLASH_RESONANCE_RGB, _FLASH_PRIME_RGB

    rgba = flash_overlay_rgba(1.0, _FLASH_RESONANCE_RGB, max_alpha=0.25)
    check(abs(rgba[3] - 0.25) < 1e-9, f"alpha = flash_value(1.0) * max_alpha(0.25) (got {rgba!r})")
    check(np.allclose(rgba[:3], (1.0, 140 / 255.0, 0.0)), f"rgb comes from the given base color, normalized to 0..1 (got {rgba!r})")

    rgba_half = flash_overlay_rgba(0.5, _FLASH_PRIME_RGB, max_alpha=0.25)
    check(abs(rgba_half[3] - 0.125) < 1e-9, f"alpha scales linearly with flash_value (got {rgba_half!r})")

    rgba_zero = flash_overlay_rgba(0.0, _FLASH_RESONANCE_RGB)
    check(rgba_zero[3] == 0.0, f"flash_value=0 -> fully transparent (got {rgba_zero!r})")


def _test_resonance_is_active():
    """[ADDED Faza 8] resonance_is_active -- ports SieveModel's
    `resonance.active` (every active ring's tooth at phase 0), with the
    same maxResonance>0 guard against a spurious resonance when there are
    no active rings at all."""
    from primeatlas.ring_viz.renderer import resonance_is_active
    from primeatlas.ring_geometry import ring_positions

    # n=6 divisible by both 2 and 3 -> both active rings hit -> resonance.
    pos_all_hit = ring_positions(np.array([2, 3], dtype=np.int64), 6, 100.0)
    check(resonance_is_active(pos_all_hit), f"every active ring divides n -> resonance active (is_hit={pos_all_hit['is_hit']!r})")

    # n=7 with active primes [2,3] -> neither divides 7 -> not a resonance.
    pos_none_hit = ring_positions(np.array([2, 3], dtype=np.int64), 7, 100.0)
    check(not resonance_is_active(pos_none_hit), f"no active ring divides n -> not a resonance (is_hit={pos_none_hit['is_hit']!r})")

    # n=10 with active primes [2,3,5] -> 2 and 5 divide, 3 doesn't -> partial, not resonance.
    pos_partial = ring_positions(np.array([2, 3, 5], dtype=np.int64), 10, 100.0)
    check(not resonance_is_active(pos_partial), f"a partial hit is not a resonance (is_hit={pos_partial['is_hit']!r})")

    # No active rings at all -> guarded False, not a vacuous True.
    pos_empty = ring_positions(np.empty(0, dtype=np.int64), 0, 100.0)
    check(not resonance_is_active(pos_empty), "no active rings at all -> not a resonance (guards the vacuous-True case)")


# ---------------------------------------------------------------------------
# Faza 9 (see PLAN.md): Load Range -- load_prime_range_slice, the only pure
# function this phase needed (the rest -- n reset to 0, auto-tracking,
# switching rebuild_buffer's active-set source -- lives in run()'s own
# closures, exercised only by the CLI/argv wiring tests in test_rings_tab.py
# and by manual/real-hardware verification, same GL-adjacent split as every
# other phase in this file).
# ---------------------------------------------------------------------------

def _test_load_prime_range_slice():
    from primeatlas.ring_viz.renderer import load_prime_range_slice

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29], dtype=np.int64)

    sliced = load_prime_range_slice(primes, 5, 19)
    check(list(sliced) == [5, 7, 11, 13, 17, 19],
          f"returns the ascending sub-array within [from, to] inclusive (got {list(sliced)!r})")

    exact_edges = load_prime_range_slice(primes, 2, 29)
    check(list(exact_edges) == list(primes), f"[from, to] spanning the whole array returns everything (got {list(exact_edges)!r})")

    between = load_prime_range_slice(primes, 4, 6)
    check(list(between) == [5], f"a range with no primes at its own edges still finds an interior one (got {list(between)!r})")

    empty_slice = load_prime_range_slice(primes, 24, 28)
    check(list(empty_slice) == [], f"a range entirely inside the loaded ceiling but with no primes in it -> empty, no error (got {list(empty_slice)!r})")

    try:
        load_prime_range_slice(primes, 20, 10)
        check(False, "from > to should raise ValueError")
    except ValueError as e:
        check("invalid range" in str(e), f"from > to raises ValueError mentioning the invalid range (got {e!r})")

    try:
        load_prime_range_slice(primes, 5, 1000)
        check(False, "to beyond the loaded ceiling should raise ValueError")
    except ValueError as e:
        check("exceeds the loaded ceiling" in str(e), f"to > primes[-1] raises ValueError mentioning the ceiling (got {e!r})")

    try:
        load_prime_range_slice(np.empty(0, dtype=np.int64), 0, 10)
        check(False, "an empty primes array with any to >= 0 should raise ValueError (ceiling is -1)")
    except ValueError as e:
        check("exceeds the loaded ceiling" in str(e), f"empty primes array -> ceiling -1 -> any to >= 0 raises (got {e!r})")


def _test_clamp_tempo_ms():
    from primeatlas.ring_viz.renderer import clamp_tempo_ms, _TEMPO_MS_DEFAULT, _TEMPO_MS_MIN, _TEMPO_MS_MAX

    check(clamp_tempo_ms(120) == 120, "a value already inside [30,2000] passes through unchanged")
    check(clamp_tempo_ms(5) == _TEMPO_MS_MIN, f"a too-low value clamps up to the min ({_TEMPO_MS_MIN})")
    check(clamp_tempo_ms(9999) == _TEMPO_MS_MAX, f"a too-high value clamps down to the max ({_TEMPO_MS_MAX})")
    check(clamp_tempo_ms(30) == 30, "the min boundary itself is accepted as-is")
    check(clamp_tempo_ms(2000) == 2000, "the max boundary itself is accepted as-is")
    check(clamp_tempo_ms(None) == _TEMPO_MS_DEFAULT, f"a missing value falls back to the JS's own default ({_TEMPO_MS_DEFAULT})")


def _test_arrow_scrub_delta():
    """[ADDED, Artur 2026-09-11: "strzalka lewo prawo ... o n+1 z wcisnietym
    ctrl o n+10"] arrow_scrub_delta() is the pure delta computation behind
    the LEFT/RIGHT scrub keys -- the pause/resume state machine around it
    (scrub_state's held-count bookkeeping in run()) is plain closure state,
    not extracted, same as on_mouse_button's own state["dragging"]."""
    from primeatlas.ring_viz.renderer import arrow_scrub_delta

    check(arrow_scrub_delta(is_right=True, ctrl_held=False) == 1,
          "RIGHT without Ctrl steps by +1")
    check(arrow_scrub_delta(is_right=False, ctrl_held=False) == -1,
          "LEFT without Ctrl steps by -1")
    check(arrow_scrub_delta(is_right=True, ctrl_held=True) == 10,
          "RIGHT with Ctrl held steps by +10")
    check(arrow_scrub_delta(is_right=False, ctrl_held=True) == -10,
          "LEFT with Ctrl held steps by -10")


def _test_clamp_scrub_n():
    """[ADDED, fixing a real break Artur hit, 2026-09-11: "na uruchomionym
    przewijalem do przodu do tylu z ctrl bez i sie zatrzymalo bez resetu nie
    ma mozliwosci wznowienia"] clamp_scrub_n() is the guard that stops the
    LEFT/RIGHT scrub keys' OS key-repeat from running N so far past the
    loaded ceiling that can_start_playback() could never resume afterward."""
    from primeatlas.ring_viz.renderer import clamp_scrub_n, can_start_playback

    check(clamp_scrub_n(50, range_mode=False, ceiling=100) == 50,
          "a value already well within bounds passes through unchanged")
    check(clamp_scrub_n(-5, range_mode=False, ceiling=100) == 0,
          "never goes negative, same floor as Up/Down/PageUp/PageDown")
    check(clamp_scrub_n(9999, range_mode=False, ceiling=100) == 100,
          "sequential mode: a huge overshoot (many rapid key-repeat deltas) clamps to the ceiling exactly")
    check(clamp_scrub_n(100, range_mode=False, ceiling=100) == 100,
          "landing exactly on the ceiling is left as-is (the same terminal state real forward playback reaches on its own)")
    check(clamp_scrub_n(9999, range_mode=True, ceiling=100) == 9999,
          "range mode has no ceiling at all -- an equally large value is NOT clamped")

    # The actual bug this fixes, end to end: an unclamped overshoot would
    # leave N somewhere can_start_playback() refuses to resume from; the
    # clamped value must always stay resumable's own upper bound (n <
    # ceiling) OR sit exactly at the expected "nothing left" edge -- never
    # further out where even a full reset-free recovery would be unclear.
    clamped = clamp_scrub_n(50_000, range_mode=False, ceiling=100)
    check(clamped == 100,
          f"clamped result never exceeds the ceiling, regardless of how large the raw overshoot was (got {clamped})")


def _test_should_extend_buffer():
    """[ADDED, Artur 2026-09-11, see next_buffer_ceiling's own doc-comment
    for the full quote] should_extend_buffer is the trigger condition for
    extend_buffer_if_needed's own real (disk-hitting) extension call --
    covers the lookahead-margin threshold itself, the range_mode/source
    bypasses, and the strict-inequality boundary that stops a runaway
    re-extend-every-frame loop right after a successful extension (see
    that function's own doc-comment for why `>` and not `>=`)."""
    from primeatlas.ring_viz.renderer import should_extend_buffer

    check(should_extend_buffer(n=50, ceiling=1000, margin=100, range_mode=False, can_extend_source=True) is False,
          "far from the ceiling (n well below ceiling-margin): no extension needed yet")
    check(should_extend_buffer(n=901, ceiling=1000, margin=100, range_mode=False, can_extend_source=True) is True,
          "n has closed to within margin of the ceiling: extend now")
    check(should_extend_buffer(n=900, ceiling=1000, margin=100, range_mode=False, can_extend_source=True) is False,
          "n exactly AT ceiling-margin does not yet trigger (strict > only) -- "
          "this is the boundary that prevents re-triggering the very frame "
          "after a fresh extension lands exactly here")
    check(should_extend_buffer(n=999, ceiling=1000, margin=100, range_mode=True, can_extend_source=True) is False,
          "range mode never extends -- it has no ceiling concept at all")
    check(should_extend_buffer(n=999, ceiling=1000, margin=100, range_mode=False, can_extend_source=False) is False,
          "a data source that can't be extended (synthetic/sieve) never extends, no matter how close n is")
    check(should_extend_buffer(n=999, ceiling=1000, margin=0, range_mode=False, can_extend_source=True) is False,
          "a zero margin never triggers (nothing to look ahead by)")


def _test_next_buffer_ceiling():
    """[ADDED, Artur 2026-09-11: "wystarczy ze bufor bedzie podrozowal wraz
    z n z wyprzedzeniem nawet tym jaki jest teraz ustawiony na
    uruchomieniu dzieki temu nie da sie dojsc do sciany o ile magazyn
    zapewnia dane"] Each extension advances the ceiling by exactly one more
    margin's worth, reusing the SAME margin figure every time (not a
    growing/shrinking one) -- see extend_buffer_if_needed's own call site
    for where that reused figure (buffer_margin) actually comes from."""
    from primeatlas.ring_viz.renderer import next_buffer_ceiling

    check(next_buffer_ceiling(1000, 100) == 1100, "advances by exactly one margin's worth")
    check(next_buffer_ceiling(next_buffer_ceiling(1000, 100), 100) == 1200,
          "repeated extensions keep advancing by the SAME margin each time, not a growing one")


def _test_can_start_playback():
    from primeatlas.ring_viz.renderer import can_start_playback

    check(can_start_playback(n=50, range_mode=False, ceiling=100) is True,
          "sequential mode below the ceiling can start")
    check(can_start_playback(n=100, range_mode=False, ceiling=100) is False,
          "sequential mode already AT the ceiling refuses to start (ports #toggleRunning's own guard)")
    check(can_start_playback(n=150, range_mode=False, ceiling=100) is False,
          "sequential mode past the ceiling (shouldn't normally happen, but) also refuses")
    check(can_start_playback(n=0, range_mode=True, ceiling=100) is True,
          "range mode has no ceiling concept -- always allowed to start")
    check(can_start_playback(n=100, range_mode=True, ceiling=100) is True,
          "range mode still allowed to start even at a value equal to some unrelated ceiling")


def _test_tick_next_n():
    from primeatlas.ring_viz.renderer import tick_next_n

    new_n, stop = tick_next_n(n=50, range_mode=False, ceiling=100)
    check((new_n, stop) == (51, False), f"sequential mode below ceiling advances by exactly 1 (got {(new_n, stop)!r})")

    new_n, stop = tick_next_n(n=100, range_mode=False, ceiling=100)
    check((new_n, stop) == (100, True), f"sequential mode AT the ceiling stops instead of advancing (got {(new_n, stop)!r})")

    new_n, stop = tick_next_n(n=150, range_mode=False, ceiling=100)
    check((new_n, stop) == (150, True), f"sequential mode past the ceiling also stops (got {(new_n, stop)!r})")

    new_n, stop = tick_next_n(n=999, range_mode=True, ceiling=100)
    check((new_n, stop) == (1000, False), f"range mode ignores the ceiling entirely and always advances (got {(new_n, stop)!r})")


def _test_advance_auto_orbit():
    from primeatlas.ring_viz.renderer import advance_auto_orbit

    active = np.array([2, 3, 5, 7, 11], dtype=np.int64)

    # A single active prime is a no-op (mirrors the JS's own early-return guard).
    idx, cnt, chosen = advance_auto_orbit(np.array([2], dtype=np.int64), index=0, counter=0)
    check((idx, cnt, chosen) == (0, 0, None), f"len<=1 is a no-op (got {(idx, cnt, chosen)!r})")

    # gap(2->3) == 1, so the very first tick already crosses it.
    idx, cnt, chosen = advance_auto_orbit(active, index=0, counter=0)
    check((idx, cnt, chosen) == (1, 0, 3),
          f"gap of 1 (3-2) advances on the very first tick, landing on index 1/prime 3 (got {(idx, cnt, chosen)!r})")

    # gap(3->5) == 2: one tick short of crossing (counter goes 0->1, no advance yet).
    idx, cnt, chosen = advance_auto_orbit(active, index=1, counter=0)
    check((idx, cnt, chosen) == (1, 1, None),
          f"gap of 2 (5-3) does not advance after only 1 tick (got {(idx, cnt, chosen)!r})")
    # ...and the second tick crosses it.
    idx, cnt, chosen = advance_auto_orbit(active, index=1, counter=1)
    check((idx, cnt, chosen) == (2, 0, 5),
          f"gap of 2 (5-3) advances on the 2nd tick, landing on index 2/prime 5 (got {(idx, cnt, chosen)!r})")

    # Wrapping past the last index uses the fixed gap of 10 (ports the JS's
    # own `nextIndex === 0 ? 10 : ...` line).
    idx, cnt, chosen = advance_auto_orbit(active, index=4, counter=8)
    check((idx, cnt, chosen) == (4, 9, None),
          f"wrap-around gap of 10 does not advance after only 9 ticks (got {(idx, cnt, chosen)!r})")
    idx, cnt, chosen = advance_auto_orbit(active, index=4, counter=9)
    check((idx, cnt, chosen) == (0, 0, 2),
          f"wrap-around gap of 10 advances on the 10th tick, landing back on index 0/prime 2 (got {(idx, cnt, chosen)!r})")


def _test_update_resonance_log():
    from primeatlas.ring_viz.renderer import update_resonance_log
    from primeatlas.ring_geometry import resonance_log_lines

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47], dtype=np.int64)

    # First call ever (last_n is None) is always a jump: full backfill from
    # from_n=1 (sequential mode).
    state = {"lines": [], "last_n": None, "last_range_mode": None}
    active = primes[primes <= 30]
    update_resonance_log(state, active, n_value=30, range_mode=False, advancing=False)
    expected = resonance_log_lines(active, 1, 30)
    check(state["lines"] == expected,
          f"first-ever call backfills the full [1, n] range (sequential mode) (got {state['lines']!r})")
    check(state["last_n"] == 30 and state["last_range_mode"] is False,
          "state's last_n/last_range_mode are updated after the call")

    # A manual jump (advancing=False) forces a fresh full backfill, even if
    # last_n was already set -- e.g. jumping backwards or skipping ahead.
    state = {"lines": ["stale", "data"], "last_n": 10, "last_range_mode": False}
    active = primes[primes <= 30]
    update_resonance_log(state, active, n_value=30, range_mode=False, advancing=False)
    check(state["lines"] == resonance_log_lines(active, 1, 30),
          "a manual jump (advancing=False) REPLACES stale lines with a fresh full backfill, "
          "not an append")

    # A forward tick (advancing=True) does NOT rescan -- it only checks
    # whether the new n_value itself is a resonance step, appending at most
    # one line, never touching earlier entries.
    state = {"lines": ["previous entry"], "last_n": 29, "last_range_mode": False}
    active = primes[primes <= 30]
    update_resonance_log(state, active, n_value=30, range_mode=False, advancing=True)
    tick_addition = resonance_log_lines(active, 30, 30)
    check(state["lines"] == ["previous entry"] + tick_addition,
          f"a forward tick only appends n_value's own resonance line(s) (if any) after existing entries "
          f"(got {state['lines']!r}, expected append of {tick_addition!r})")

    # A tick that produces NO new resonance event leaves the log untouched.
    # (n=8 is confirmed NOT a resonance step for this prime list -- the
    # earlier full-backfill assertion's own printed event list, over
    # [1, 30], never includes 8.)
    state = {"lines": ["kept as-is"], "last_n": 7, "last_range_mode": False}
    active = primes[primes <= 8]
    update_resonance_log(state, active, n_value=8, range_mode=False, advancing=True)
    check(state["lines"] == ["kept as-is"],
          f"a tick landing on a non-resonance n leaves state['lines'] unchanged (got {state['lines']!r})")

    # A tick is never double-appended if called twice with the same n_value
    # (defensive dedupe, mirrors #logResonance's own last-entry check).
    state = {"lines": [], "last_n": 29, "last_range_mode": False}
    active = primes[primes <= 30]
    update_resonance_log(state, active, n_value=30, range_mode=False, advancing=True)
    before = list(state["lines"])
    state["last_n"] = 29  # simulate calling again for the "same" tick
    update_resonance_log(state, active, n_value=30, range_mode=False, advancing=True)
    check(state["lines"] == before,
          "calling update_resonance_log twice for the same n_value tick does not duplicate the entry")

    # A mode switch (sequential -> range) forces a jump even with advancing=True.
    state = {"lines": ["sequential data"], "last_n": 30, "last_range_mode": False}
    range_active = np.array([101, 103, 107], dtype=np.int64)
    update_resonance_log(state, range_active, n_value=2, range_mode=True, advancing=True)
    check(state["lines"] == resonance_log_lines(range_active, 0, 2),
          f"a mode switch forces a full backfill (from_n=0 for range mode) even with advancing=True "
          f"(got {state['lines']!r})")
    check(state["last_range_mode"] is True, "last_range_mode reflects the new mode after the switch")


def _test_compose_hud_canvas_lines():
    from primeatlas.ring_viz.renderer import compose_hud_canvas_lines

    lines = compose_hud_canvas_lines(n=1234567, count=42, lines=["Factors of N: 7, 11"],
                                      running=False, tempo_ms=120)
    check(lines[0] == "N = 1,234,567    rings = 42    [Stopped]",
          f"header line formats N/count with thousands separators and 'Stopped' status (got {lines[0]!r})")
    check(lines[1:] == ["Factors of N: 7, 11"],
          f"hud_lines_for_n's own lines pass through verbatim, in order (got {lines[1:]!r})")

    lines = compose_hud_canvas_lines(n=5, count=0, lines=[], running=True, tempo_ms=250)
    check(lines == ["N = 5    rings = 0    [Running (250ms/tick)]"],
          f"running status includes the tempo, empty extra-lines list is fine (got {lines!r})")


def _test_hud_line_colors():
    """[ADDED, see Artur's 2026-09-10 report on colorizing HUD window-range
    labels] hud_line_colors matches lines by their own fixed leading text
    (see _HUD_WINDOW_LINE_PREFIXES), independent of what comes before them
    -- Factors-of-N and Tracked-block lines, and the header line
    compose_hud_canvas_lines prepends, all fall through to the flat
    default _HUD_TEXT_RGB."""
    from primeatlas.ring_viz.renderer import hud_line_colors, _HUD_TEXT_RGB
    from primeatlas.ring_geometry import window_label_colors

    window_colors = window_label_colors({"bertrand", "legendre"}, 141)
    lines = [
        "N = 141    rings = 34    [Stopped]",
        "Factors of N: 3, 47",
        "Bertrand window: (70, 141]",
        "Legendre window: k=11  (121, 141]",
    ]
    colors = hud_line_colors(lines, window_colors)
    check(len(colors) == len(lines), "one color per input line, same length")
    check(colors[0] == _HUD_TEXT_RGB, f"the header line gets the flat default color (got {colors[0]!r})")
    check(colors[1] == _HUD_TEXT_RGB, f"a Factors-of-N line gets the flat default color (got {colors[1]!r})")
    check(colors[2] == window_colors["bertrand"],
          f"the Bertrand window line gets Bertrand's own color from window_colors (got {colors[2]!r})")
    check(colors[3] == window_colors["legendre"],
          f"the Legendre window line gets Legendre's own color from window_colors (got {colors[3]!r})")

    # General Law's line has extra parenthesized text before the colon
    # (theta=..., k=... in stepped mode) -- the prefix match must still
    # fire on just "General Law window", not the full literal string.
    gl_colors = window_label_colors({"generalLaw"}, 141, theta=0.5, mode="stepped")
    gl_line = "General Law window (theta=0.5, k=11): (121, 141]"
    check(hud_line_colors([gl_line], gl_colors) == [gl_colors["generalLaw"]],
          "General Law's line matches by its fixed leading text even with extra "
          "parenthesized theta/k detail before the colon")

    # A family present in window_colors but with no matching line at all
    # (e.g. caller passed a stale/mismatched dict) must not crash or leak
    # into an unrelated line -- every line either matches its own family's
    # prefix or falls back to default, nothing else.
    check(hud_line_colors(["Tracked (active): 2, 3"], window_colors) == [_HUD_TEXT_RGB],
          "a Tracked-block line never accidentally matches a window prefix")

    check(hud_line_colors([], window_colors) == [], "empty lines list -> empty colors list")


def _test_hud_quad_vertex_data():
    from primeatlas.ring_viz.renderer import hud_quad_vertex_data

    verts = hud_quad_vertex_data(100.0, 50.0, x=10.0, y=20.0)
    check(verts.shape == (6, 4), f"two triangles = 6 vertices, each (pos_x, pos_y, uv_x, uv_y) (got shape {verts.shape})")
    xs, ys = verts[:, 0], verts[:, 1]
    check(xs.min() == 10.0 and xs.max() == 110.0, f"quad spans x in [10, 110] (anchor + width) (got [{xs.min()}, {xs.max()}])")
    check(ys.min() == 20.0 and ys.max() == 70.0, f"quad spans y in [20, 70] (anchor + height) (got [{ys.min()}, {ys.max()}])")
    # Top-left corner (min x, min y) must carry uv (0, 0) -- matches PIL's
    # own top-left-origin image layout, so the rasterized bitmap shows up
    # right-side-up with no manual flip anywhere in the pipeline.
    top_left_rows = verts[(xs == 10.0) & (ys == 20.0)]
    check(bool(np.all(top_left_rows[:, 2:4] == 0.0)), f"top-left corner has uv=(0,0) (got {top_left_rows[:, 2:4].tolist()})")
    bottom_right_rows = verts[(xs == 110.0) & (ys == 70.0)]
    check(bool(np.all(bottom_right_rows[:, 2:4] == 1.0)), f"bottom-right corner has uv=(1,1) (got {bottom_right_rows[:, 2:4].tolist()})")


def _test_rasterize_hud_text():
    from primeatlas.ring_viz.renderer import rasterize_hud_text, _PIL_AVAILABLE

    check(rasterize_hud_text([]) is None, "empty line list rasterizes to None (nothing to draw)")

    if not _PIL_AVAILABLE:
        print("skip: Pillow not installed in this environment -- rasterize_hud_text's "
              "real-bitmap behavior is untested here (renderer.py itself degrades "
              "gracefully in this case, see its own _PIL_AVAILABLE guard)")
        return

    rgba = rasterize_hud_text(["N = 100", "Factors of N: 2, 5"])
    check(rgba is not None, "non-empty lines produce a real bitmap")
    check(rgba.ndim == 3 and rgba.shape[2] == 4, f"result is an (H, W, 4) RGBA array (got shape {rgba.shape})")
    check(rgba.dtype == np.uint8, f"result is uint8 (got {rgba.dtype})")
    check(rgba.shape[0] > 0 and rgba.shape[1] > 0, f"non-empty text produces a non-degenerate image (got shape {rgba.shape})")
    # Two lines of text must be taller than a single line of the same text,
    # otherwise the per-line layout loop isn't actually stacking anything.
    one_line = rasterize_hud_text(["N = 100"])
    check(rgba.shape[0] > one_line.shape[0],
          f"two lines are taller than one line ({rgba.shape[0]} vs {one_line.shape[0]})")
    # Some pixel must actually be opaque (alpha > 0) -- otherwise this drew
    # nothing (e.g. a font/color bug silently producing a blank image).
    check(bool((rgba[:, :, 3] > 0).any()), "at least one pixel has non-zero alpha (text was actually drawn)")

    # Faza 11C: font_size must actually change the rasterized bitmap size --
    # this is the whole point of the --hud-font-size CLI param (Artur's
    # "hud jest mikroskopijny" report), so a bug here would silently make
    # the new flag a no-op.
    small = rasterize_hud_text(["N = 100"], font_size=10)
    big = rasterize_hud_text(["N = 100"], font_size=40)
    check(big.shape[0] > small.shape[0] and big.shape[1] > small.shape[1],
          f"font_size=40 produces a taller AND wider bitmap than font_size=10 "
          f"(got small={small.shape}, big={big.shape})")

    # [ADDED 2026-09-10, see Artur's report on colorizing HUD window labels]
    # line_colors must actually change the rasterized pixel color, not just
    # be accepted and ignored -- render the SAME single line twice with two
    # very different colors and confirm the resulting opaque pixels differ.
    pink = rasterize_hud_text(["Bertrand window: (70, 141]"], line_colors=[(255, 51, 204)])
    green = rasterize_hud_text(["Bertrand window: (70, 141]"], line_colors=[(57, 255, 20)])
    check(pink.shape == green.shape, "line_colors changes pixel color only, not the bitmap's own size")
    pink_opaque = pink[pink[:, :, 3] > 0]
    green_opaque = green[green[:, :, 3] > 0]
    check(len(pink_opaque) > 0 and len(green_opaque) > 0, "sanity: both renders actually drew something")
    check(tuple(pink_opaque[0][:3]) == (255, 51, 204),
          f"an opaque text pixel carries the requested line_colors RGB exactly (got {tuple(pink_opaque[0][:3])!r})")
    check(tuple(green_opaque[0][:3]) == (57, 255, 20),
          f"a different line_colors value produces a different opaque pixel RGB (got {tuple(green_opaque[0][:3])!r})")

    # No line_colors given (None, the default) keeps the old flat
    # _HUD_TEXT_RGB behavior completely unchanged -- a real regression
    # guard, not just an absence-of-crash check.
    from primeatlas.ring_viz.renderer import _HUD_TEXT_RGB
    default_rgba = rasterize_hud_text(["N = 100"])
    default_opaque = default_rgba[default_rgba[:, :, 3] > 0]
    check(tuple(default_opaque[0][:3]) == _HUD_TEXT_RGB,
          f"omitting line_colors still renders the old flat _HUD_TEXT_RGB color (got {tuple(default_opaque[0][:3])!r})")


def main():
    _test_basic_multi_floor_load()
    _test_gap_between_floors()
    _test_batching_does_not_change_result()
    _test_progress_callback_invoked()
    _test_load_magazyn_from_n()
    _test_empty_portal()
    _test_build_vertex_data_no_windows_matches_old_behavior()
    _test_build_vertex_data_bertrand_highlight()
    _test_build_vertex_data_track_primes_white_dot()
    _test_split_hit_normal_vertex_data()
    _test_hud_lines_for_n()
    _test_initial_n_for_source()
    _test_zoom_to_point()
    _test_fit_zoom_for_viewport()
    _test_filter_active_tracked()
    _test_hud_lines_for_n_tracked_state()
    _test_lcm_of_list()
    _test_tracked_resonance_state()
    _test_format_big()
    _test_tracked_ring_mask()
    _test_unit_circle_vertices()
    _test_tracked_outline_color()
    _test_resolve_effective_track_primes()
    _test_build_tracked_outline_draws()
    _test_center_marker_triangle_offsets()
    _test_marker_device_scale()
    _test_build_center_marker_vertex_data()
    _test_build_flash_quad_vertex_data()
    _test_decay_flash()
    _test_flash_overlay_rgba()
    _test_resonance_is_active()
    _test_load_prime_range_slice()
    _test_clamp_tempo_ms()
    _test_arrow_scrub_delta()
    _test_clamp_scrub_n()
    _test_should_extend_buffer()
    _test_next_buffer_ceiling()
    _test_can_start_playback()
    _test_tick_next_n()
    _test_advance_auto_orbit()
    _test_update_resonance_log()
    _test_compose_hud_canvas_lines()
    _test_hud_line_colors()
    _test_hud_quad_vertex_data()
    _test_rasterize_hud_text()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
