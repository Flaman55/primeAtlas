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


def main():
    _test_basic_multi_floor_load()
    _test_gap_between_floors()
    _test_batching_does_not_change_result()
    _test_progress_callback_invoked()
    _test_empty_portal()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
