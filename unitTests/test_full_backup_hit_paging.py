"""
test_full_backup_hit_paging.py -- proves primeatlas/settings/manifest.py's ConstellationSnapshot
and primeatlas/settings/full_backup.py's copy_floor_increment()/restore_floor_from_full_backup()
correctly see and round-trip a PAGED constellation pattern (prime_sieve/hit_paging.py),
not just the original single-cumulative-file case every existing full_backup.py user
already relied on.

Why this exists: manifest.py's ConstellationSnapshot used a hit-file regex
("^HITS_10p\\d+_k\\d+_v\\d+\\.bin$") that does NOT match a paged pattern's page files
(f"..._page{P:05d}.bin") or its PAGES_META.json -- meaning, before this fix,
copy_floor_increment() would silently back up NOTHING for any pattern migrated to
pages (floor 25's k=2 being the real, motivating case -- see hit_paging.py's own
module docstring), and a floor's *existing* full backup would look complete
(list_destination_hit_filenames() using the same kind of narrow match) while actually
missing that pattern's data entirely. No existing test in this repo covered
manifest.py or full_backup.py at all before this file (verified via a repo-wide
grep for "full_backup"/"manifest" imports in unitTests/ turning up nothing) -- adding
this alongside the fix rather than leaving the gap in place.

Usage:
    python unitTests\\test_full_backup_hit_paging.py
"""
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

import prime_sieve_v1
import hit_paging
from primeatlas.settings.manifest import ConstellationSnapshot
from primeatlas.settings import full_backup

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _seed_floor(storage_path, base_exponent):
    """One UNPAGED pattern (k=3/v=1, small) and one PAGED pattern (k=2/v=1, migrated
    via the real migrate_hit_file_to_pages(), page_size small enough to force multiple
    pages) -- so every assertion below distinguishes "did the paging fix regress the
    common unpaged case" from "does the paging fix actually work"."""
    const_dir = os.path.join(storage_path, f"10p{base_exponent}", "constellations")

    unpaged_vdir = os.path.join(const_dir, "k3", "variant1")
    os.makedirs(unpaged_vdir, exist_ok=True)
    unpaged_path = os.path.join(unpaged_vdir, f"HITS_10p{base_exponent}_k3_v1.bin")
    unpaged_values = [10 ** base_exponent + 7, 10 ** base_exponent + 31]
    prime_sieve_v1.write_prime_window(unpaged_path, unpaged_values)

    paged_vdir = os.path.join(const_dir, "k2", "variant1")
    os.makedirs(paged_vdir, exist_ok=True)
    paged_source = os.path.join(paged_vdir, f"HITS_10p{base_exponent}_k2_v1.bin")
    paged_values = [10 ** base_exponent + 2 * i for i in range(1, 18)]  # 17 values
    prime_sieve_v1.write_prime_window(paged_source, paged_values)
    hit_paging.migrate_hit_file_to_pages(
        paged_source, paged_vdir, base_exponent, 2, 1, page_size=5)  # -> 4 pages

    return unpaged_values, paged_values


def test_snapshot_sees_paged_files():
    tmpdir = tempfile.mkdtemp(prefix="full_backup_paging_snapshot_")
    try:
        base_exponent = 3
        _seed_floor(tmpdir, base_exponent)

        snap = ConstellationSnapshot.scan(tmpdir, base_exponent)
        rel_paths = set(snap.hit_files)

        check(f"k3/variant1/HITS_10p{base_exponent}_k3_v1.bin" in rel_paths,
              "the unpaged pattern's single file is still seen (got %r)" % sorted(rel_paths))

        page_paths = [p for p in rel_paths if p.startswith("k2/variant1/") and "_page" in p]
        check(len(page_paths) == 4, f"all 4 page files of the paged pattern are seen (got {len(page_paths)})")
        check("k2/variant1/PAGES_META.json" in rel_paths,
              "the paged pattern's PAGES_META.json is seen (got %r)" % sorted(rel_paths))
        check(f"k2/variant1/HITS_10p{base_exponent}_k2_v1.bin" not in rel_paths,
              "the paged pattern's now-renamed-away original file is correctly NOT seen")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_backup_then_restore_round_trips_paged_pattern():
    storage_dir = tempfile.mkdtemp(prefix="full_backup_paging_storage_")
    dest_dir = tempfile.mkdtemp(prefix="full_backup_paging_dest_")
    restore_dir = tempfile.mkdtemp(prefix="full_backup_paging_restore_")
    try:
        base_exponent = 3
        _unpaged_values, paged_values = _seed_floor(storage_dir, base_exponent)

        result = full_backup.copy_floor_increment(storage_dir, dest_dir, base_exponent)
        check(not result["cancelled"], "backup run was not cancelled")
        check(result["copied_hits"] >= 6,
              f"backup copied the unpaged file + 4 pages + PAGES_META.json (got copied_hits={result['copied_hits']})")

        dest_const_dir = full_backup._dest_const_dir(dest_dir, base_exponent)
        dest_meta_gz = os.path.join(dest_const_dir, "k2", "variant1", "PAGES_META.json.gz")
        check(os.path.exists(dest_meta_gz), "PAGES_META.json.gz physically exists at the backup destination")
        dest_page0_gz = os.path.join(
            dest_const_dir, "k2", "variant1", f"HITS_10p{base_exponent}_k2_v1_page00000.bin.gz")
        check(os.path.exists(dest_page0_gz), "page 0's .gz physically exists at the backup destination")

        plan_again = full_backup.plan_floor_backup_update(storage_dir, dest_dir, base_exponent)
        check(plan_again["missing_hits"] == [],
              f"a second backup run finds nothing new to copy (got {plan_again['missing_hits']})")

        restore_result = full_backup.restore_floor_from_full_backup(restore_dir, dest_dir, base_exponent)
        check(not restore_result["cancelled"], "restore run was not cancelled")
        check(restore_result["restored_hits"] >= 6,
              f"restore copied back the unpaged file + 4 pages + PAGES_META.json (got restored_hits={restore_result['restored_hits']})")

        restored_vdir = os.path.join(
            restore_dir, f"10p{base_exponent}", "constellations", "k2", "variant1")
        check(hit_paging.is_paged(restored_vdir), "restored copy is recognized as paged")
        restored_meta = hit_paging.read_meta(restored_vdir)
        check(restored_meta["total_count"] == len(paged_values),
              f"restored PAGES_META.json has the right total_count (got {restored_meta['total_count']})")

        reconstructed = []
        for i in range(hit_paging.page_count(restored_meta)):
            reconstructed.extend(hit_paging.read_page(restored_vdir, base_exponent, 2, 1, i))
        check(reconstructed == paged_values,
              f"every page's values round-trip through backup+restore intact (got {reconstructed})")
    finally:
        shutil.rmtree(storage_dir, ignore_errors=True)
        shutil.rmtree(dest_dir, ignore_errors=True)
        shutil.rmtree(restore_dir, ignore_errors=True)


def main():
    test_snapshot_sees_paged_files()
    test_backup_then_restore_round_trips_paged_pattern()

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
