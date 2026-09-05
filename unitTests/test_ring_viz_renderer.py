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


def _test_hud_lines_for_n_tracked_active():
    """[ADDED Faza 6, see PLAN.md] hud_lines_for_n's new tracked_active param
    -- a HUD line appears only when non-empty, listing exactly the given
    (already-filtered) primes in the given order."""
    from primeatlas.ring_viz.renderer import hud_lines_for_n, build_vertex_data

    primes = np.array([2, 3, 5, 7, 11, 13], dtype=np.int64)
    n = 41
    max_radius = 100.0
    _data, _count, pos = build_vertex_data(primes, n, max_radius, set(), 0.5, "stepped")

    lines_none = hud_lines_for_n(primes, n, pos, set(), 0.5, "stepped")
    check(not any("Tracked" in line for line in lines_none),
          f"no tracked_active given -> no 'Tracked' HUD line at all (got {lines_none!r})")

    lines_empty = hud_lines_for_n(primes, n, pos, set(), 0.5, "stepped", tracked_active=[])
    check(not any("Tracked" in line for line in lines_empty),
          f"empty tracked_active -> no 'Tracked' HUD line (got {lines_empty!r})")

    lines_some = hud_lines_for_n(primes, n, pos, set(), 0.5, "stepped", tracked_active=[7, 2])
    joined = "\n".join(lines_some)
    check("Tracked (active): 7, 2" in joined,
          f"non-empty tracked_active produces a 'Tracked (active): ...' line in the "
          f"exact given order (got lines={lines_some!r})")


def main():
    _test_basic_multi_floor_load()
    _test_gap_between_floors()
    _test_batching_does_not_change_result()
    _test_progress_callback_invoked()
    _test_empty_portal()
    _test_build_vertex_data_no_windows_matches_old_behavior()
    _test_build_vertex_data_bertrand_highlight()
    _test_hud_lines_for_n()
    _test_initial_n_for_source()
    _test_zoom_to_point()
    _test_filter_active_tracked()
    _test_hud_lines_for_n_tracked_active()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
