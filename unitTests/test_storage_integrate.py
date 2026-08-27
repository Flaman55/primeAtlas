"""
test_storage_integrate.py -- unit tests for primeatlas/storage_integrate.py's
integrate_floor(), focused specifically on the totals-cache bump added 2026-08-27 (see
storage.py's own module docstring for the full "persisted totals, updated incrementally
instead of by a full rescan" feature). Artur's explicit request for the merge case was:
sum the destination's and the external storage's already-KNOWN totals instead of
recounting every prime -- this suite pins down exactly that, plus the "external doesn't
know this file's count" fallback (skip it, don't guess/read the file to find out).

Uses real temporary directories on both the "external" and "destination" sides -- unlike
storage.py's own bump_pietro_total()/remove_pietro_total() (pure, dict-only, see
test_storage.py), integrate_floor() is a real file-copying operation, so this suite
exercises it end to end the same way test_window_sharding.py does for the sharded
layout it also depends on.

Usage (Windows, real Python):
    python unitTests\\test_storage_integrate.py

Usage (this sandbox, headless):
    python3 unitTests/test_storage_integrate.py
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
    path = os.path.join(shard_dir, name)
    prime_sieve_v1.write_prime_window(path, primes)
    return name, path


def main():
    from primeatlas import storage, storage_integrate

    tmp = tempfile.mkdtemp(prefix="primeatlas_storage_integrate_test_")
    try:
        external = os.path.join(tmp, "external")
        destination = os.path.join(tmp, "destination")
        os.makedirs(external, exist_ok=True)
        os.makedirs(destination, exist_ok=True)

        # === Case 1: brand-new floor at destination, external's cache knows BOTH files =
        base_exponent = 7
        name_a, _path_a = _write_window(external, base_exponent, 0, [2, 3, 5])
        name_b, _path_b = _write_window(external, base_exponent, 10_000_000, [7, 11])
        # Third file on disk but DELIBERATELY left out of external's own totals cache --
        # simulates a file the external side's own PrimeAtlas never got around to
        # scanning/opening (see integrate_floor()'s own docstring on this fallback).
        name_c, _path_c = _write_window(external, base_exponent, 20_000_000, [13, 17, 19])

        ext_cache = {}
        # Real scan for name_a/name_b only -- mimics "external side already visited this
        # floor once", then we DELETE name_c's entry to simulate it being unseen there.
        storage.update_pietro_totals_cache(external, base_exponent, ext_cache)
        del ext_cache[f"10p{base_exponent}"]["files"][name_c]
        ext_cache[f"10p{base_exponent}"]["total"] -= 5  # keep the entry internally consistent
        ext_cache[f"10p{base_exponent}"]["file_count"] -= 1
        storage.save_totals_cache(external, ext_cache)

        result = storage_integrate.integrate_floor(destination, external, base_exponent)
        check(result["copied_windows"] == 3 and not result["cancelled"],
              f"integrate_floor copies all 3 real files regardless of totals-cache "
              f"knowledge (got {result!r})")

        dest_cache = storage.load_totals_cache(destination)
        dest_entry = dest_cache.get(f"10p{base_exponent}", {})
        check(dest_entry.get("total") == 5,
              f"destination's bumped total is 3+2=5 (name_a+name_b only) -- name_c's "
              f"3 primes are NOT counted since the external cache didn't know its count "
              f"(got {dest_entry.get('total')!r})")
        check(dest_entry.get("file_count") == 2,
              f"destination's bumped file_count is 2 (only the two KNOWN files), even "
              f"though 3 files were actually copied to disk (got {dest_entry.get('file_count')!r})")
        check(storage.get_global_total(dest_cache) == (5, 2, dest_entry.get("total_bytes")),
              "the persisted global total reflects the same known-only bump")

        # A real full rescan (the manual 'Zweryfikuj sumy' safety net) must independently
        # confirm the TRUE total once it actually reads every file's header, including
        # name_c -- proving the bump under-counted safely rather than over-counting.
        real_cache = dict(dest_cache)
        real_total, real_file_count, _new_read, _bytes = storage.update_pietro_totals_cache(
            destination, base_exponent, real_cache)
        check((real_total, real_file_count) == (8, 3),
              f"a full verify rescan finds the TRUE total of 8 across all 3 files "
              f"(name_a=3 + name_b=2 + name_c=3 primes), proving the earlier bump's "
              f"under-count (5) was a safe UNDER-estimate, not an over-count "
              f"(got {(real_total, real_file_count)!r})")

        # === Case 2: an EXISTING destination floor gains more files (not a brand-new
        # floor this time) -- same bump mechanism, just starting from a nonzero base. ===
        base_exponent2 = 9
        name_d, _ = _write_window(external, base_exponent2, 0, [2, 3])
        name_e, _ = _write_window(external, base_exponent2, 10_000_000, [5])
        ext_cache2 = {}
        storage.update_pietro_totals_cache(external, base_exponent2, ext_cache2)
        storage.save_totals_cache(external, ext_cache2)

        # Destination already has ITS OWN unrelated total for this floor (as if it had
        # generated some of its own primes there before ever merging anything in).
        pre_cache = storage.load_totals_cache(destination)
        storage.bump_pietro_total(pre_cache, base_exponent2, delta_count=100,
                                   delta_file_count=1, delta_bytes=800)
        storage.save_totals_cache(destination, pre_cache)

        storage_integrate.integrate_floor(destination, external, base_exponent2)
        post_cache = storage.load_totals_cache(destination)
        post_entry = post_cache[f"10p{base_exponent2}"]
        check(post_entry["total"] == 103,
              f"merging into an EXISTING floor ADDS the newly-known total (2+1=3) onto "
              f"the destination's own prior total (100), landing on 103, not overwriting "
              f"it (got {post_entry['total']!r})")

        if failures:
            print(f"\n{len(failures)} FAILURE(S)")
            return 1
        print("\nALL CHECKS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
