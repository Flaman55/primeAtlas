"""
test_storage.py -- unit tests for primeatlas/storage.py's persisted-totals feature added
2026-08-27: the incremental bump_pietro_total()/remove_pietro_total() pair and the
persisted GLOBAL total (get_global_total()/recompute_global_total()), added after Artur
pointed out that update_pietro_totals_cache() (the full per-floor directory-listing +
os.stat()-every-file rescan) being the ONLY way any total ever got refreshed meant that
cost ran for EVERY floor on every startup/reload, even when nothing had changed. See
storage.py's own module docstring for the full feature rationale.

Pure logic tests first (plain dicts, no disk I/O at all), then a real round-trip against
load_totals_cache()/save_totals_cache()/update_pietro_totals_cache() in a temp directory
to confirm the incremental path and the full-rescan path agree on the same numbers.

Usage (Windows, real Python):
    python unitTests\\test_storage.py

Usage (this sandbox, headless):
    python3 unitTests/test_storage.py
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


def _test_bump_and_global():
    from primeatlas import storage

    cache = {}
    storage.bump_pietro_total(cache, 5, delta_count=100, delta_file_count=1, delta_bytes=800)
    check(cache["10p5"]["total"] == 100, "bump on a brand-new floor entry sets total from 0")
    check(cache["10p5"]["file_count"] == 1, "bump on a brand-new floor entry sets file_count from 0")
    check(cache["10p5"]["total_bytes"] == 800, "bump on a brand-new floor entry sets total_bytes from 0")
    check(cache["10p5"]["files"] == {},
          "bump does NOT touch entry['files'] -- it only adjusts the aggregate fields "
          "(see bump_pietro_total's own docstring on why per-file granularity is skipped)")
    check(storage.get_global_total(cache) == (100, 1, 800),
          "bump also bumps the persisted global summary by the same delta")

    storage.bump_pietro_total(cache, 5, delta_count=50, delta_file_count=1, delta_bytes=400)
    check(cache["10p5"]["total"] == 150, "a second bump on the SAME floor accumulates (doesn't overwrite)")
    check(storage.get_global_total(cache) == (150, 2, 1200),
          "global summary accumulates across multiple bumps to the same floor")

    storage.bump_pietro_total(cache, 9, delta_count=30, delta_file_count=1, delta_bytes=240)
    check(cache["10p9"]["total"] == 30, "bump on a SECOND, different floor creates its own independent entry")
    check(storage.get_global_total(cache) == (180, 3, 1440),
          "global summary sums across DIFFERENT floors too, not just repeated bumps to one")

    removed = storage.remove_pietro_total(cache, 5)
    check(removed == (150, 2, 1200), f"remove_pietro_total returns the removed floor's last totals (got {removed!r})")
    check("10p5" not in cache, "remove_pietro_total drops the floor's own cache entry entirely")
    check(storage.get_global_total(cache) == (30, 1, 240),
          "removing a floor subtracts exactly its own contribution from the global summary, "
          "leaving the other floor's contribution untouched")

    removed_again = storage.remove_pietro_total(cache, 5)
    check(removed_again is None,
          "remove_pietro_total on a floor with no cache entry at all returns None "
          "(nothing to subtract) instead of raising or corrupting the global summary")
    check(storage.get_global_total(cache) == (30, 1, 240),
          "a no-op remove (floor never had an entry) leaves the global summary unchanged")


def _test_get_global_total_missing():
    from primeatlas import storage

    check(storage.get_global_total({}) is None,
          "get_global_total on a cache with no '_global' key yet returns None -- "
          "callers must treat this as 'never computed, fall back to a real recompute', "
          "same missing-cache contract as load_totals_cache()")
    check(storage.get_global_total({"10p0": {"total": 4}}) is None,
          "get_global_total returns None even when per-floor entries exist, as long as "
          "'_global' itself was never written (e.g. an old cache file from before this "
          "feature existed)")


def _test_recompute_global_total():
    from primeatlas import storage

    cache = {
        "10p0": {"total": 4, "file_count": 1, "total_bytes": 40},
        "10p1": {"total": 21, "file_count": 1, "total_bytes": 100},
        "10p2": {"total": 143, "file_count": 2, "total_bytes": 900},
        # A floor entry with no prior real scan at all (e.g. created by a bare bump with
        # no "total" key ever set some other way) must contribute 0, not raise.
        "10p3": {"files": {}},
    }
    result = storage.recompute_global_total(cache)
    check(result == (168, 4, 1040), f"recompute_global_total sums every floor's cached total (got {result!r})")
    check(storage.get_global_total(cache) == (168, 4, 1040),
          "recompute_global_total writes the '_global' key so get_global_total sees it immediately")

    # Deliberately WRONG '_global' left over from stale bumps -- recompute must overwrite
    # it wholesale (self-healing), not merge/add into the wrong number.
    cache["_global"] = {"sum": 999999, "file_count": 999, "bytes": 999999}
    result2 = storage.recompute_global_total(cache)
    check(result2 == (168, 4, 1040),
          "recompute_global_total OVERWRITES a stale/wrong '_global' entry from scratch "
          "rather than trusting or merging into it -- this is exactly the self-healing "
          "the manual 'Zweryfikuj sumy' verify action relies on")

    check(storage.recompute_global_total({}) == (0, 0, 0),
          "recompute_global_total on a completely empty cache returns (0, 0, 0), not an error")


def _test_global_key_never_collides_with_a_real_floor():
    from primeatlas import storage

    check(storage.GLOBAL_TOTAL_KEY == "_global",
          "GLOBAL_TOTAL_KEY is a fixed, non-'10p'-prefixed string, so it can never be "
          "mistaken for a real floor key (every real floor key is '10p{N}', see "
          "list_pietra()'s own naming convention)")
    check(not storage.GLOBAL_TOTAL_KEY.startswith("10p"),
          "GLOBAL_TOTAL_KEY must never start with '10p' -- callers that iterate cache.items() "
          "looking for floor entries (see recompute_global_total's own skip-check) rely on this")


def _test_round_trip_bump_matches_full_rescan():
    """The real end-to-end guarantee this whole feature depends on: after a generation
    run adds new window files to a floor, calling bump_pietro_total() with that run's
    known delta must land on the EXACT SAME total a full update_pietro_totals_cache()
    rescan would have found by actually reading every file's header -- otherwise the fast
    incremental path and the manual verify path would disagree, which is exactly the kind
    of silent drift Artur's "Zweryfikuj sumy" safety net exists to catch, not something
    this feature should be introducing on its own on the very first day."""
    from primeatlas import storage
    import prime_sieve_v1
    import window_sharding

    tmp = tempfile.mkdtemp(prefix="primeatlas_storage_totals_test_")
    try:
        portal_dir = os.path.join(tmp, "portal")
        base_exponent = 7
        source_dir = os.path.join(portal_dir, f"10p{base_exponent}", "source_primes")
        # source_primes/ is sharded into shard_NNNNN subfolders (window_sharding.py,
        # task #405) -- files must live under a real shard dir, not flat, or
        # list_source_filenames() (which this round-trip test exercises via
        # update_pietro_totals_cache) finds nothing at all (see test_window_sharding.py
        # for the same convention).
        shard0 = window_sharding.shard_dir(source_dir, 0)
        os.makedirs(shard0, exist_ok=True)

        # Two window files already "generated" before this test's incremental bump --
        # simulates a floor that was already visited/scanned once in the past.
        prime_sieve_v1.write_prime_window(os.path.join(shard0, "PRIME_WINDOW_a.bin"), [2, 3, 5])
        prime_sieve_v1.write_prime_window(os.path.join(shard0, "PRIME_WINDOW_b.bin"), [7, 11])

        cache = {}
        total, file_count, new_read, total_bytes = storage.update_pietro_totals_cache(
            portal_dir, base_exponent, cache)
        check((total, file_count, new_read) == (5, 2, 2),
              f"baseline full rescan finds 5 primes across 2 files (got {(total, file_count, new_read)!r})")
        storage.recompute_global_total(cache)
        check(storage.get_global_total(cache) == (5, 2, total_bytes),
              "recompute_global_total after the baseline rescan matches the floor's own total")

        # Now simulate a NEW generation run writing one more window file -- the real write
        # path already knows this file's exact count/size without re-reading anything, so
        # bump_pietro_total() is given that delta directly instead of triggering a rescan.
        new_file_path = os.path.join(shard0, "PRIME_WINDOW_c.bin")
        prime_sieve_v1.write_prime_window(new_file_path, [13, 17, 19, 23])
        new_file_bytes = os.path.getsize(new_file_path)
        storage.bump_pietro_total(cache, base_exponent, delta_count=4, delta_file_count=1,
                                   delta_bytes=new_file_bytes)

        check(cache[f"10p{base_exponent}"]["total"] == 9,
              f"incremental bump lands on 9 primes (5 baseline + 4 new) "
              f"(got {cache[f'10p{base_exponent}']['total']!r})")
        check(storage.get_global_total(cache)[0] == 9,
              "persisted global total reflects the bump immediately, no rescan needed")

        # Now run a REAL full rescan (what the manual "Zweryfikuj sumy" button does) and
        # confirm it independently arrives at the exact same number the incremental bump
        # already produced -- this is the actual cross-check, not just trusting the bump.
        total2, file_count2, new_read2, total_bytes2 = storage.update_pietro_totals_cache(
            portal_dir, base_exponent, cache)
        check((total2, file_count2, new_read2) == (9, 3, 1),
              f"full rescan after the new file exists independently confirms 9 primes "
              f"across 3 files, having only needed to read the ONE new file's header "
              f"(got {(total2, file_count2, new_read2)!r})")
        check(total2 == cache[f"10p{base_exponent}"]["total"],
              "full rescan's own total agrees exactly with what the incremental bump had "
              "already produced -- no drift between the fast path and the verify path")

        storage.recompute_global_total(cache)
        check(storage.get_global_total(cache) == (9, 3, total_bytes2),
              "recompute_global_total after the follow-up rescan still agrees with the "
              "incrementally-bumped number")

        # Round-trip through save/load, same as a real app restart would do.
        storage.save_totals_cache(portal_dir, cache)
        reloaded = storage.load_totals_cache(portal_dir)
        check(storage.get_global_total(reloaded) == (9, 3, total_bytes2),
              "the persisted global total survives a save_totals_cache()/load_totals_cache() "
              "round trip exactly, the same as the per-floor totals already did")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    _test_bump_and_global()
    _test_get_global_total_missing()
    _test_recompute_global_total()
    _test_global_key_never_collides_with_a_real_floor()
    _test_round_trip_bump_matches_full_rescan()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
