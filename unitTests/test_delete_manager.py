"""
test_delete_manager.py -- unit tests for primeatlas/delete_manager.py's totals-cache
hook, added 2026-08-27 alongside storage.py's persisted-totals feature (see that
module's own docstring): deleting a floor must subtract its last-known total from the
persisted global sum and drop its own cache entry (FloorWiper.execute_delete_floor(),
via storage.remove_pietro_total()); wiping the WHOLE storage must remove the totals
cache file outright (PortalWiper.execute()), since every floor it describes is gone at
once.

Real temp directories (delete_manager.py does real filesystem operations) -- same
convention as test_storage_integrate.py.

Usage (Windows, real Python):
    python unitTests\\test_delete_manager.py

Usage (this sandbox, headless):
    python3 unitTests/test_delete_manager.py
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


def _write_window(portal, base_exponent, offset, primes, window_m=10_000_000):
    import prime_sieve_v1
    import window_sharding
    source_dir = os.path.join(portal, f"10p{base_exponent}", "source_primes")
    target_idx = offset // window_m
    shard_dir = window_sharding.shard_dir(source_dir, target_idx)
    os.makedirs(shard_dir, exist_ok=True)
    suffix = f"{offset // 1_000_000}M" if offset and offset % 1_000_000 == 0 else str(offset)
    name = f"PRIME_WINDOW_10p{base_exponent}_off_{suffix}.bin"
    prime_sieve_v1.write_prime_window(os.path.join(shard_dir, name), primes)


def main():
    from primeatlas import storage
    from primeatlas.delete_manager import FloorWiper, PortalWiper

    tmp = tempfile.mkdtemp(prefix="primeatlas_delete_manager_test_")
    try:
        portal = os.path.join(tmp, "portal")
        os.makedirs(portal, exist_ok=True)

        # === FloorWiper.execute_delete_floor: subtracts from the persisted global ====
        _write_window(portal, 5, 0, [2, 3, 5])
        _write_window(portal, 9, 0, [7, 11])

        cache = {}
        storage.update_pietro_totals_cache(portal, 5, cache)
        storage.update_pietro_totals_cache(portal, 9, cache)
        storage.recompute_global_total(cache)
        storage.save_totals_cache(portal, cache)
        check(storage.get_global_total(cache) == (5, 2, cache["10p5"]["total_bytes"] + cache["10p9"]["total_bytes"]),
              f"baseline: floor 5 (3 primes) + floor 9 (2 primes) = 5 total, 2 files "
              f"(got {storage.get_global_total(cache)!r})")

        wiper = FloorWiper(portal)
        ok, error = wiper.execute_delete_floor(5)
        check(ok and error is None, f"execute_delete_floor(5) succeeds (got ok={ok!r}, error={error!r})")
        check(not os.path.isdir(os.path.join(portal, "10p5")),
              "10p5's directory is actually gone from disk")

        reloaded = storage.load_totals_cache(portal)
        check("10p5" not in reloaded,
              "deleting floor 5 drops its OWN entry from the persisted totals cache")
        check("10p9" in reloaded,
              "deleting floor 5 leaves floor 9's own cache entry completely untouched")
        check(storage.get_global_total(reloaded) == (2, 1, reloaded["10p9"]["total_bytes"]),
              f"the persisted global total is subtracted down to JUST floor 9's "
              f"contribution (2 primes, 1 file), not zeroed or left at the stale 5 "
              f"(got {storage.get_global_total(reloaded)!r})")

        # Deleting a floor that was never in the cache at all (e.g. generated before
        # this feature existed, or never opened in the Primes tab) must be a safe no-op
        # on the cache side, not raise or corrupt the global total.
        _write_window(portal, 12, 0, [13])
        ok2, error2 = wiper.execute_delete_floor(12)
        check(ok2 and error2 is None, "deleting a floor with NO prior cache entry still succeeds")
        after_noop = storage.load_totals_cache(portal)
        check(storage.get_global_total(after_noop) == (2, 1, after_noop["10p9"]["total_bytes"]),
              "deleting a floor absent from the cache leaves the persisted global total "
              "completely unchanged (nothing to subtract)")

        # Deleting a floor that doesn't exist on disk at all is a no-op, untouched by
        # this feature -- must not create a bogus cache entry or touch the global sum.
        ok3, error3 = wiper.execute_delete_floor(999)
        check(ok3 is False and error3 is None,
              "deleting a nonexistent floor returns (False, None), same as before this feature")

        # === PortalWiper.execute(): removes the totals cache file outright ===========
        check(os.path.exists(os.path.join(portal, storage.TOTALS_CACHE_FILENAME)),
              "sanity check: the totals cache file exists on disk before the full wipe")
        _write_window(portal, 20, 0, [17, 19])  # something for PortalWiper to actually delete
        deleted, errors = PortalWiper(portal).execute()
        check("10p9" in deleted and "10p20" in deleted and not errors,
              f"PortalWiper.execute() deletes every floor directory with no errors "
              f"(got deleted={deleted!r}, errors={errors!r})")
        check(not os.path.exists(os.path.join(portal, storage.TOTALS_CACHE_FILENAME)),
              "a full portal wipe removes the totals cache FILE entirely -- every floor "
              "it described is gone at once, so there's nothing left for it to track")

        if failures:
            print(f"\n{len(failures)} FAILURE(S)")
            return 1
        print("\nALL CHECKS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
