"""
test_ring_viz_sources.py -- the storage readers of the visualizations
(primeatlas/visualization/shared/sources.py and range_data.py): load_archive() and
load_archive_before() over real floor enumeration, batched reads, the progress
callback, floor gaps and boundaries, floors beyond uint64, the initial N per source,
the prime-range slice, and the slide chunk size defaulting to max_load_count.

Builds a synthetic portal folder with real PGS window files (ring_viz_fixtures.
write_floor(): prime_sieve_v1.write_prime_window() + window_sharding.shard_dir()), so
this exercises the actual on-disk read path, not a mocked one. No moderngl/glfw import.

Usage: python unitTests\\test_ring_viz_sources.py
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

from ring_viz_fixtures import write_floor  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _test_basic_multi_floor_load():
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        # Floor 0: numbers below 10 -- one window, [2,3,5,7].
        write_floor(portal_dir, 0, [[2, 3, 5, 7]])
        # Floor 1: numbers in [10, 100) -- two windows.
        write_floor(portal_dir, 1, [[11, 13, 17], [19, 23, 29]])

        result = load_archive(portal_dir, upto=30)
        check(list(result) == [2, 3, 5, 7, 11, 13, 17, 19, 23, 29],
              f"load_archive(upto=30) across two floors returns every prime "
              f"<=30 in ascending order (got {list(result)!r})")
        # uint64, not int64 -- see to_prime_array's own doc-comment
        # (shared/bigint.py): the fast path doubled its ceiling from int64's
        # ~9.2e18 to uint64's ~1.8e19 by dropping the sign bit primes never
        # used, since a real archive floor (10p25/10p27) needs every bit of
        # headroom before falling back to the slow `object` path.
        check(result.dtype == np.uint64, "load_archive result is uint64")

        result_partial = load_archive(portal_dir, upto=20)
        check(list(result_partial) == [2, 3, 5, 7, 11, 13, 17, 19],
              f"load_archive(upto=20) correctly excludes primes above the "
              f"cutoff, including trimming WITHIN the second floor-1 window "
              f"(got {list(result_partial)!r})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_gap_between_floors():
    """The exact case the old blind floor+=1 loop handled inefficiently but
    correctly, and the new list_floors()-based enumeration must ALSO handle
    correctly (not just efficiently): floor 0 populated, floor 1 MISSING
    entirely (e.g. never generated), floor 2 populated."""
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        write_floor(portal_dir, 0, [[2, 3, 5, 7]])
        # floor 1 (10p1) deliberately not created at all.
        write_floor(portal_dir, 2, [[101, 103, 107]])

        result = load_archive(portal_dir, upto=200)
        check(list(result) == [2, 3, 5, 7, 101, 103, 107],
              f"load_archive skips a missing floor cleanly instead of "
              f"stalling or erroring on the gap (got {list(result)!r})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_batching_does_not_change_result():
    """Batching load_archive's reads is an internal memory-shape change, not
    a behavior change -- a tiny batch_files=1 (forces one file
    per batch) must return the EXACT SAME array as a large batch_files that
    reads everything in one batch."""
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        write_floor(portal_dir, 0, [[2, 3, 5, 7]])
        write_floor(portal_dir, 1, [[11, 13], [17, 19], [23, 29], [31, 37]])

        big_batch = load_archive(portal_dir, upto=100, batch_files=1000)
        small_batch = load_archive(portal_dir, upto=100, batch_files=1)
        check(list(big_batch) == list(small_batch),
              f"batch_files=1 (one file per batch) and batch_files=1000 (one "
              f"giant batch) return identical results "
              f"(big={list(big_batch)!r} small={list(small_batch)!r})")
        check(list(big_batch) == [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37],
              "sanity: the actual content is correct regardless of batching")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_progress_callback_invoked():
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        write_floor(portal_dir, 0, [[2, 3, 5, 7]])
        write_floor(portal_dir, 1, [[11, 13], [17, 19], [23, 29]])

        calls = []

        def on_progress(base_exponent, files_read_in_floor, primes_loaded_so_far):
            calls.append((base_exponent, files_read_in_floor, primes_loaded_so_far))

        result = load_archive(portal_dir, upto=30, progress_callback=on_progress, batch_files=1)
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


def _test_load_archive_from_n():
    """The `from_n` parameter is what lets extend_buffer_if_needed() fetch
    only the NEW primes past what's already loaded instead of
    re-reading/re-returning everything from scratch on every extension --
    covers both halves of that: the whole-floor skip (floor 0 here is
    entirely below from_n) and the within-floor trim (floor 1's first
    window is partially below from_n)."""
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        write_floor(portal_dir, 0, [[2, 3, 5, 7]])
        write_floor(portal_dir, 1, [[11, 13, 17], [19, 23, 29]])
        write_floor(portal_dir, 2, [[101, 103, 107]])

        result = load_archive(portal_dir, upto=200, from_n=17)
        check(list(result) == [19, 23, 29, 101, 103, 107],
              f"from_n=17 skips floor 0 entirely (all <=17) and trims floor "
              f"1's first window down to just 19 (got {list(result)!r})")

        result_zero = load_archive(portal_dir, upto=200, from_n=0)
        result_default = load_archive(portal_dir, upto=200)
        check(list(result_zero) == list(result_default),
              "from_n=0 (explicit) reproduces the default (omitted) behavior exactly")
        check(list(result_default) == [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 101, 103, 107],
              f"sanity: the from_n=0/default baseline itself is still correct "
              f"(got {list(result_default)!r})")

        result_exhausted = load_archive(portal_dir, upto=200, from_n=107)
        check(len(result_exhausted) == 0,
              "from_n at the true end of stored data returns an empty array "
              "(the extend_state['exhausted'] case in extend_buffer_if_needed)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_load_archive_max_load_count():
    """`max_load_count` truncates a load from the TOP once the cap is hit --
    covers truncation splitting a batch mid-window, truncation landing
    exactly on a window/floor boundary, a cap bigger than the whole result
    (no-op), and combining with `from_n` (jumping straight to a high floor,
    the actual arbitrary-range-viewing use case)."""
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        write_floor(portal_dir, 0, [[2, 3, 5, 7]])
        write_floor(portal_dir, 1, [[11, 13, 17], [19, 23, 29]])
        write_floor(portal_dir, 2, [[101, 103, 107]])

        result_mid_window = load_archive(portal_dir, upto=200, max_load_count=5)
        check(list(result_mid_window) == [2, 3, 5, 7, 11],
              f"max_load_count=5 cuts mid-window, keeping only the first 5 "
              f"primes overall (got {list(result_mid_window)!r})")

        result_on_boundary = load_archive(portal_dir, upto=200, max_load_count=4)
        check(list(result_on_boundary) == [2, 3, 5, 7],
              "max_load_count landing exactly on a window boundary stops cleanly there")

        result_generous = load_archive(portal_dir, upto=200, max_load_count=1000)
        result_unbounded = load_archive(portal_dir, upto=200)
        check(list(result_generous) == list(result_unbounded),
              "a cap bigger than the whole available result is a no-op")

        result_none = load_archive(portal_dir, upto=200, max_load_count=None)
        check(list(result_none) == list(result_unbounded),
              "max_load_count=None (explicit) reproduces the default (omitted) behavior exactly")

        # The actual feature this backs: jump straight to a high floor
        # (from_n) AND cap how much of it gets materialized, without ever
        # reading floor 0 or 1's files at all.
        result_combined = load_archive(portal_dir, upto=200, from_n=100, max_load_count=2)
        check(list(result_combined) == [101, 103],
              f"from_n + max_load_count combine: skip straight to floor 2, "
              f"then cap at 2 primes (got {list(result_combined)!r})")

        result_zero_cap = load_archive(portal_dir, upto=200, max_load_count=0)
        check(len(result_zero_cap) == 0, "max_load_count=0 returns an empty array without error")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_load_archive_high_floor_beyond_uint64():
    """A real archive has floors far past floor 18 (portal data at
    10p25/10p27 is ~10**25-10**27 magnitude), which a `dtype=np.int64` cast in
    load_archive's per-file loop would overflow. A floor whose own values
    exceed uint64 must load correctly (as `object` dtype, exact values, no
    OverflowError), including when combined with a low floor that still fits
    uint64 (np.concatenate must promote the WHOLE result to object, never
    silently truncate/wrap the high values)."""
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        base = 10 ** 25
        high_values = [base, base + 4, base + 6, base + 10]
        write_floor(portal_dir, 25, [high_values])

        result = load_archive(portal_dir, upto=base + 1000, from_n=base - 1)
        check(list(result) == high_values,
              f"load_archive loads a real floor-25-scale floor without raising OverflowError "
              f"(got {list(result)!r})")
        check(result.dtype == object,
              "load_archive: a floor whose values exceed the uint64 ceiling returns object dtype")

        # Mixed: a low floor (fits uint64) plus the high one above, loaded
        # together in one call (the from_n=0/default sequential path).
        portal_dir2 = os.path.join(tmp, "portal2")
        write_floor(portal_dir2, 0, [[2, 3, 5, 7]])
        write_floor(portal_dir2, 25, [high_values])
        result_mixed = load_archive(portal_dir2, upto=base + 1000)
        check(list(result_mixed) == [2, 3, 5, 7] + high_values,
              f"load_archive: a low floor (uint64-safe) plus a high floor (needs object) concatenate "
              f"correctly, in ascending order (got {list(result_mixed)!r})")
        check(result_mixed.dtype == object,
              "load_archive: mixing a uint64-safe floor with an object-dtype floor promotes the WHOLE "
              "result to object (numpy's own concatenate dtype-promotion rule), never silently truncating "
              "the high values down to a fixed-width type")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_empty_portal():
    from primeatlas.visualization.shared.sources import load_archive

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        os.makedirs(portal_dir, exist_ok=True)  # exists, but no 10p* floors at all
        result = load_archive(portal_dir, upto=1000)
        check(len(result) == 0, "load_archive on a portal folder with no floors returns an empty array")
        # uint64, not int64 -- see the sibling check in
        # _test_basic_multi_floor_load above for why.
        check(result.dtype == np.uint64, "the empty result is still uint64, not a generic empty array")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_slide_chunk_size_defaults_to_max_load_count():
    """--slide-chunk-size defaults to None at the argparse level and is
    resolved to args.max_load_count's value right after parsing, unless an
    explicit --slide-chunk-size overrides it -- so a user who only sets
    --max-load-count (or the GUI's "Max loaded rings" field) gets that value
    for every chunk loaded via sliding, not just the first one.

    Exercises main()'s real argparse parsing/validation path (not just
    build_renderer_argv's argv construction) by monkeypatching renderer.run
    to a no-op that just records the resolved `args`, and sys.argv to a
    fake invocation -- main() never reaches any GL/moderngl code before
    calling run(args), so this is safe in this headless sandbox (same
    "no GL/glfw import until run()" guarantee this whole test file's own
    docstring already relies on)."""
    from primeatlas.visualization.shared import renderer

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        os.makedirs(portal_dir, exist_ok=True)

        captured = {}

        def fake_run(args):
            captured["args"] = args

        real_run = renderer.run
        real_argv = sys.argv
        renderer.run = fake_run
        try:
            # No explicit --slide-chunk-size -- must inherit --max-load-count.
            sys.argv = ["renderer.py", "--source", "archive", "--portal-folder", portal_dir,
                        "--load-range", "10,1000", "--slide-load-range", "--max-load-count", "12345"]
            renderer.main()
            check(captured["args"].slide_chunk_size == 12345,
                  f"--slide-chunk-size with no explicit value inherits --max-load-count's own "
                  f"value (12345), not a separate hardcoded 2,000,000 default "
                  f"(got {captured['args'].slide_chunk_size})")

            # An explicit --slide-chunk-size still overrides the inherited default.
            captured.clear()
            sys.argv = ["renderer.py", "--source", "archive", "--portal-folder", portal_dir,
                        "--load-range", "10,1000", "--slide-load-range", "--max-load-count", "12345",
                        "--slide-chunk-size", "999"]
            renderer.main()
            check(captured["args"].slide_chunk_size == 999,
                  f"an explicit --slide-chunk-size still overrides the inherited default "
                  f"(got {captured['args'].slide_chunk_size})")

            # Neither given -- both fall back to argparse's own shared 2,000,000.
            captured.clear()
            sys.argv = ["renderer.py", "--source", "archive", "--portal-folder", portal_dir,
                        "--load-range", "10,1000", "--slide-load-range"]
            renderer.main()
            check(captured["args"].slide_chunk_size == 2_000_000,
                  f"with neither flag given, --slide-chunk-size still resolves to "
                  f"--max-load-count's own argparse default (2,000,000) "
                  f"(got {captured['args'].slide_chunk_size})")
        finally:
            renderer.run = real_run
            sys.argv = real_argv
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# load_archive_before(): the backward-walking counterpart to load_archive(),
# used by the ring_viz sliding window (chunk_back). Symmetric
# fixture convention to load_archive's own tests above; `before_n` is
# EXCLUSIVE (mirrors load_archive's own `from_n` exclusivity), so a
# chunk_back ending at some value X and a chunk_current starting at
# before_n=X never duplicate or gap at the seam.
# ---------------------------------------------------------------------------

def _test_load_archive_before_basic():
    from primeatlas.visualization.shared.sources import load_archive_before

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        write_floor(portal_dir, 0, [[2, 3, 5, 7]])
        write_floor(portal_dir, 1, [[11, 13, 17], [19, 23, 29]])

        result = load_archive_before(portal_dir, before_n=23, count=3)
        check(list(result) == [13, 17, 19],
              f"load_archive_before(before_n=23, count=3) returns the 3 largest "
              f"primes strictly below 23, ascending (got {list(result)!r})")

        result_exclusive = load_archive_before(portal_dir, before_n=19, count=100)
        check(19 not in list(result_exclusive),
              "before_n itself is EXCLUSIVE -- a real stored prime exactly at "
              "before_n is never included (mirrors load_archive's own from_n exclusivity)")
        check(list(result_exclusive) == [2, 3, 5, 7, 11, 13, 17],
              f"count larger than what's available below before_n returns "
              f"everything that qualifies, not an error (got {list(result_exclusive)!r})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_load_archive_before_gap_between_floors():
    from primeatlas.visualization.shared.sources import load_archive_before

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        write_floor(portal_dir, 0, [[2, 3, 5, 7]])
        # floor 1 (10p1) deliberately not created at all.
        write_floor(portal_dir, 2, [[101, 103, 107]])

        result = load_archive_before(portal_dir, before_n=107, count=10)
        check(list(result) == [2, 3, 5, 7, 101, 103],
              f"load_archive_before skips a missing floor cleanly walking "
              f"backward too, not just forward (got {list(result)!r})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_load_archive_before_floor_boundary():
    """before_n landing EXACTLY on a floor's own lower bound (10**base_exponent)
    must fall through to the PREVIOUS floor entirely -- nothing in the
    boundary floor itself can be < before_n when before_n IS that floor's
    own lower bound."""
    from primeatlas.visualization.shared.sources import load_archive_before

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        write_floor(portal_dir, 0, [[2, 3, 5, 7]])
        write_floor(portal_dir, 1, [[11, 13, 17]])

        result = load_archive_before(portal_dir, before_n=10, count=10)
        check(list(result) == [2, 3, 5, 7],
              f"before_n exactly on floor 1's own lower bound (10) pulls "
              f"only from floor 0 (got {list(result)!r})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_load_archive_before_not_below_is_a_hard_boundary():
    """`not_below` makes the range's own FROM a hard boundary for
    load_archive_before: without it the reader would keep walking into
    EARLIER floors as long as the portal has data there (scrubbing backward
    past the start of a --load-range would then hang the renderer). Portal here has real data in floor 0
    (1..97, deliberately MUCH earlier/more than a naive reader might
    expect) plus floor 1 (101..) -- `not_below` pinned to a value INSIDE
    floor 1 must never let ANY floor-0 value leak into the result, no
    matter how large `count` is."""
    from primeatlas.visualization.shared.sources import load_archive_before

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        floor1_values = [11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97]
        write_floor(portal_dir, 0, [[2, 3, 5, 7]])
        write_floor(portal_dir, 1, [floor1_values])
        write_floor(portal_dir, 2, [[101, 103, 107, 109, 113]])

        # not_below=90 sits INSIDE floor 1 itself -- floor 2 contributes in
        # full (all below before_n=113), floor 1 contributes only its own
        # values > 90 (just 97), and floor 0 (single-digit primes) is NEVER
        # reached at all, even though it holds plenty of real data and
        # count is nowhere near satisfied by floors 1+2 alone.
        result = load_archive_before(portal_dir, before_n=113, count=1000, not_below=90)
        check(list(result) == [97, 101, 103, 107, 109],
              f"not_below=90 stops the walk inside floor 1, correctly excluding every floor-1 "
              f"value <=90 AND every floor-0 value entirely (got {list(result)!r})")
        check(all(v > 90 for v in result), "no returned value is at or below not_below")
        check(2 not in result and 3 not in result and 5 not in result and 7 not in result,
              "not a single floor-0 value leaked through")

        # count is generously large but not_below is the thing that actually
        # stops the search -- never an infinite/unbounded walk to the portal's
        # true start (2/3) when not_below is set.
        result2 = load_archive_before(portal_dir, before_n=113, count=10**9, not_below=90)
        check(list(result2) == [97, 101, 103, 107, 109],
              "an enormous count does not override not_below's own hard stop")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_load_archive_before_walks_off_the_start():
    """before_n at or below the true start of the portal's own data --
    returns whatever's available (possibly empty), never errors or loops
    forever."""
    from primeatlas.visualization.shared.sources import load_archive_before

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        write_floor(portal_dir, 0, [[2, 3, 5, 7]])

        result = load_archive_before(portal_dir, before_n=2, count=10)
        check(len(result) == 0,
              "before_n at the true first stored value returns an empty array, not an error")

        result_far_below = load_archive_before(portal_dir, before_n=1, count=10)
        check(len(result_far_below) == 0,
              "before_n below every stored value returns an empty array, not an error")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_load_archive_before_empty_portal():
    from primeatlas.visualization.shared.sources import load_archive_before

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        os.makedirs(portal_dir, exist_ok=True)
        result = load_archive_before(portal_dir, before_n=1000, count=10)
        check(len(result) == 0, "load_archive_before on a portal with no floors returns an empty array")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_load_archive_before_window_boundary_exact():
    """count landing exactly on a window-file boundary stops cleanly there
    (no off-by-one pulling in one extra/missing value)."""
    from primeatlas.visualization.shared.sources import load_archive_before

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        write_floor(portal_dir, 1, [[11, 13, 17], [19, 23, 29]])

        result = load_archive_before(portal_dir, before_n=19, count=3)
        check(list(result) == [11, 13, 17],
              f"before_n exactly at the second window's own base_prime pulls "
              f"exactly the first window's contents, no off-by-one across the "
              f"boundary (got {list(result)!r})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_load_archive_before_high_floor_beyond_uint64():
    """Real floor-25/27-scale magnitude (see load_archive's own sibling test)
    -- must not overflow, correct object dtype, exact values, walking
    backward within a single high floor."""
    from primeatlas.visualization.shared.sources import load_archive_before

    tmp = tempfile.mkdtemp(prefix="primeatlas_ring_viz_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        base = 10 ** 25
        high_values = [base, base + 4, base + 6, base + 10]
        write_floor(portal_dir, 25, [high_values])

        result = load_archive_before(portal_dir, before_n=base + 10, count=2)
        check(list(result) == [base + 4, base + 6],
              f"load_archive_before at real floor-25 magnitude returns the correct "
              f"exact-value slice without overflow (got {list(result)!r})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_initial_n_for_source():
    """run() must open the ring view on the N the user actually asked for,
    not on the last loaded prime.
    Regression test for initial_n_for_source()'s extraction of that fix --
    see that function's own docstring for the full bug description."""
    from primeatlas.visualization.shared.range_data import initial_n_for_source

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37], dtype=np.int64)

    # sieve/archive: real user-specified upto (e.g. 1000, typed in rings_tab's
    # N field) -- must open exactly there, even though 1000 itself isn't
    # prime and the largest actual prime <=1000 among these primes is 37.
    check(initial_n_for_source("archive", 1000, primes) == 1000,
          "source=archive opens on --upto verbatim, not primes[-1] (was the bug: "
          "typing 1000 silently opened on 997/whatever the largest loaded prime was)")
    check(initial_n_for_source("sieve", 1000, primes) == 1000,
          "source=sieve opens on --upto verbatim too (same real-target-N semantics as archive)")

    # An upto that happens to BE prime should still just be itself, not
    # accidentally "work" only by coincidence.
    check(initial_n_for_source("archive", 37, primes) == 37,
          "source=archive with a prime --upto still returns --upto itself, not primes[-1]")

    # synthetic: no real user-specified N (only --count) -- keeps the old
    # primes[-1] behavior, since there is nothing else meaningful to open on.
    check(initial_n_for_source("synthetic", 1000, primes) == int(primes[-1]),
          f"source=synthetic still opens on the last generated value (got "
          f"{initial_n_for_source('synthetic', 1000, primes)}, expected {int(primes[-1])})")

    empty = np.empty(0, dtype=np.int64)
    check(initial_n_for_source("synthetic", 1000, empty) == 0,
          "source=synthetic with an empty array falls back to 0, does not crash")
    check(initial_n_for_source("archive", 1000, empty) == 1000,
          "source=archive with an empty array still opens on --upto (an empty ring field "
          "at the requested N, not a crash or a silent fallback to 0)")


# ---------------------------------------------------------------------------
# Load Range -- load_prime_range_slice is the only pure function here; the
# rest (n reset to 0, auto-tracking, switching rebuild_buffer's active-set
# source) lives in run()'s own closures, exercised only by the CLI/argv
# wiring tests in test_rings_tab.py and by manual/real-hardware verification,
# same GL-adjacent split as every other piece in this file.
# ---------------------------------------------------------------------------

def _test_load_prime_range_slice():
    from primeatlas.visualization.shared.range_data import load_prime_range_slice

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


def main():
    _test_basic_multi_floor_load()
    _test_gap_between_floors()
    _test_batching_does_not_change_result()
    _test_progress_callback_invoked()
    _test_load_archive_from_n()
    _test_load_archive_max_load_count()
    _test_load_archive_high_floor_beyond_uint64()
    _test_empty_portal()
    _test_slide_chunk_size_defaults_to_max_load_count()
    _test_load_archive_before_basic()
    _test_load_archive_before_gap_between_floors()
    _test_load_archive_before_floor_boundary()
    _test_load_archive_before_not_below_is_a_hard_boundary()
    _test_load_archive_before_walks_off_the_start()
    _test_load_archive_before_empty_portal()
    _test_load_archive_before_window_boundary_exact()
    _test_load_archive_before_high_floor_beyond_uint64()
    _test_initial_n_for_source()
    _test_load_prime_range_slice()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
