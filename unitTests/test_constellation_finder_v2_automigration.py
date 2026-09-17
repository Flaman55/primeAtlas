"""
test_constellation_finder_v2_automigration.py -- integration tests for
constellation_finder_v2.py's append_hits() AUTO-MIGRATING an unpaged pattern to pages
(prime_sieve/hit_paging.py) the moment an append would push its count past
hit_paging.PAGE_SIZE, so a future floor's dense k=2 pattern never needs the same
manual migrate_hit_file_to_pages() run previously required by hand for floor 25's
k=2 (~2.16 billion hits) and several other already-huge patterns.

hit_paging.PAGE_SIZE is monkeypatched down to a small number for these tests so the
crossing can be exercised in a handful of small appends -- the actual migration codepath
(migrate_hit_file_to_pages(), same one a manual run uses) is completely size-agnostic,
so this is representative of the real threshold, just faster to test.

Two levels covered:
  1. append_hits() itself -- the append that crosses PAGE_SIZE auto-migrates BEFORE
     writing, and every value (both sides of the crossing) is still readable afterward,
     with the original single file preserved as a .pre_page_migration.bak safety copy.
  2. _append_hits_deduped() -- the real call path process_floor() actually uses,
     including its last_value_cache/disk_cache bookkeeping and re-scan-safety dedup
     filter, across the SAME migration boundary (a real scan re-processing an
     already-covered window right after a pattern just crossed the threshold must
     still correctly skip already-known values, not crash or duplicate them).

Usage (Windows, real Python -- no Tk/display dependency):
    python unitTests\\test_constellation_finder_v2_automigration.py

Usage (this sandbox, headless):
    python3 unitTests/test_constellation_finder_v2_automigration.py
"""
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "constellation"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def test_append_hits_auto_migrates_at_the_crossing():
    import hit_paging
    import constellation_finder_v2 as cf2

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_v2_automig_append_test_")
    original_page_size = hit_paging.PAGE_SIZE
    hit_paging.PAGE_SIZE = 5
    try:
        cf2.PORTAL_FOLDER = tmp_portal
        base_exponent, k, vid = 3, 2, 1
        vdir = hit_paging.variant_dir(tmp_portal, base_exponent, k, vid)

        cf2.append_hits(base_exponent, k, vid, [100, 101, 102])
        cf2.append_hits(base_exponent, k, vid, [103, 104])  # count now == 5, exactly PAGE_SIZE
        check(not hit_paging.is_paged(vdir),
              "hitting PAGE_SIZE exactly (not exceeding it) does not trigger migration yet")

        cf2.append_hits(base_exponent, k, vid, [105])  # 5 + 1 > 5 -> crosses, auto-migrates first
        check(hit_paging.is_paged(vdir),
              "the append that pushes count past PAGE_SIZE auto-migrates the pattern")

        meta = hit_paging.read_meta(vdir)
        check(meta["total_count"] == 6, f"post-migration total_count reflects every value (got {meta['total_count']})")
        check(hit_paging.page_count(meta) == 2, f"6 values at page_size=5 makes 2 pages (got {hit_paging.page_count(meta)})")

        page0 = hit_paging.read_page(vdir, base_exponent, k, vid, 0)
        page1 = hit_paging.read_page(vdir, base_exponent, k, vid, 1)
        check(page0 == [100, 101, 102, 103, 104], f"page 0 holds exactly the pre-crossing values (got {page0})")
        check(page1 == [105], f"page 1 holds exactly the value that triggered the crossing (got {page1})")

        original_path = cf2.hit_file_path(base_exponent, k, vid)
        backup_path = original_path + ".pre_page_migration.bak"
        check(not os.path.exists(original_path), "the original single file no longer exists at its old name")
        check(os.path.exists(backup_path), "the original single file survives as a .pre_page_migration.bak safety copy")

        # A further append past the crossing goes straight to the paged path (no
        # second migration attempt, which hit_paging.migrate_hit_file_to_pages() would
        # refuse with ValueError if it were mistakenly re-triggered).
        cf2.append_hits(base_exponent, k, vid, [106, 107])
        meta2 = hit_paging.read_meta(vdir)
        check(meta2["total_count"] == 8, f"appends after the crossing keep accumulating normally (got {meta2['total_count']})")
        page1_again = hit_paging.read_page(vdir, base_exponent, k, vid, 1)
        check(page1_again == [105, 106, 107], f"the still-open page keeps filling (got {page1_again})")
    finally:
        hit_paging.PAGE_SIZE = original_page_size
        shutil.rmtree(tmp_portal, ignore_errors=True)


def test_deduped_wrapper_survives_the_crossing():
    """The real call path process_floor() uses -- _append_hits_deduped() -- including
    its last_value_cache bookkeeping and re-scan-safety dedup filter, exercised across
    the SAME auto-migration boundary tested above."""
    import hit_paging
    import constellation_finder_v2 as cf2

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_v2_automig_dedup_test_")
    original_page_size = hit_paging.PAGE_SIZE
    hit_paging.PAGE_SIZE = 5
    try:
        cf2.PORTAL_FOLDER = tmp_portal
        base_exponent, k, vid = 3, 2, 1
        vdir = hit_paging.variant_dir(tmp_portal, base_exponent, k, vid)
        last_value_cache = {}

        appended1, skipped1 = cf2._append_hits_deduped(
            base_exponent, k, vid, [100, 101, 102], last_value_cache=last_value_cache)
        check((appended1, skipped1) == (3, 0), f"first window's hits all appended (got {(appended1, skipped1)})")

        appended2, skipped2 = cf2._append_hits_deduped(
            base_exponent, k, vid, [103, 104, 105], last_value_cache=last_value_cache)
        check((appended2, skipped2) == (3, 0),
              f"second window's hits append across the auto-migration crossing transparently (got {(appended2, skipped2)})")
        check(hit_paging.is_paged(vdir), "the pattern is paged after this window's append")
        check(last_value_cache[(k, vid)] == (105, 6),
              f"last_value_cache reflects the post-migration state correctly (got {last_value_cache[(k, vid)]})")

        # Re-scan safety: the checkpoint regresses (or a storage merge re-introduces a
        # window) and the SAME window gets processed again -- its hits must be
        # silently skipped, not re-appended (which would hit append_prime_window()'s/
        # append_hits_paged()'s own strict-increase assertion), same guarantee this
        # wrapper already gave before any of this pattern was ever paged.
        appended3, skipped3 = cf2._append_hits_deduped(
            base_exponent, k, vid, [103, 104, 105], last_value_cache=last_value_cache)
        check((appended3, skipped3) == (0, 3),
              f"re-scanning an already-covered window post-migration is a safe no-op (got {(appended3, skipped3)})")

        # A genuinely NEW window's hits (some already-known values mixed with new
        # ones, exactly the partial-overlap case _append_hits_deduped() exists for)
        # still append correctly on the paged side.
        appended4, skipped4 = cf2._append_hits_deduped(
            base_exponent, k, vid, [104, 105, 106, 107], last_value_cache=last_value_cache)
        check((appended4, skipped4) == (2, 2),
              f"a partially-overlapping window keeps only the genuinely new values (got {(appended4, skipped4)})")

        meta = hit_paging.read_meta(vdir)
        check(meta["total_count"] == 8, f"final total_count is correct after every window (got {meta['total_count']})")
        all_values = []
        for i in range(hit_paging.page_count(meta)):
            all_values.extend(hit_paging.read_page(vdir, base_exponent, k, vid, i))
        check(all_values == [100, 101, 102, 103, 104, 105, 106, 107],
              f"every value across every window is present exactly once, in order (got {all_values})")

        # A FRESH run (last_value_cache empty again, as it would be on process restart)
        # must still resolve the correct last value via _resolve_last_value()'s own
        # is_paged() fast path (see that function's own docstring), not fall back to a
        # stale/absent LAST_VALUES.tsv disk cache entry.
        fresh_last_value_cache = {}
        appended5, skipped5 = cf2._append_hits_deduped(
            base_exponent, k, vid, [106, 107, 108], last_value_cache=fresh_last_value_cache)
        check((appended5, skipped5) == (1, 2),
              f"a fresh run (empty in-memory cache) still resolves the paged pattern's real last "
              f"value correctly via is_paged(), not a stale disk cache (got {(appended5, skipped5)})")
    finally:
        hit_paging.PAGE_SIZE = original_page_size
        shutil.rmtree(tmp_portal, ignore_errors=True)


def main():
    test_append_hits_auto_migrates_at_the_crossing()
    test_deduped_wrapper_survives_the_crossing()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"FAIL: {f}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
