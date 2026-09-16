"""
test_hit_paging.py -- unit tests for prime_sieve/hit_paging.py (constellation hit-file
paging, Problem B of the 2026-09-15/16 magazyn/records-table browsing fix) and its
prime_sieve_v1.iter_prime_window_chunks() streaming-decode dependency.

Usage:
    python unitTests\\test_hit_paging.py
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

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def test_iter_prime_window_chunks():
    tmpdir = tempfile.mkdtemp(prefix="hit_paging_chunks_")
    try:
        primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]
        path = os.path.join(tmpdir, "w.bin")
        prime_sieve_v1.write_prime_window(path, primes)

        for chunk_size in (1, 3, 10, 100):
            chunks = list(prime_sieve_v1.iter_prime_window_chunks(path, chunk_size))
            flat = [v for chunk in chunks for v in chunk]
            check(flat == primes, f"chunk_size={chunk_size}: flattened chunks == full list")
            check(all(len(c) <= chunk_size for c in chunks),
                  f"chunk_size={chunk_size}: no chunk exceeds chunk_size")
            if chunk_size < len(primes):
                check(len(chunks) > 1, f"chunk_size={chunk_size}: split into multiple chunks")

        empty_path = os.path.join(tmpdir, "empty.bin")
        prime_sieve_v1.write_prime_window(empty_path, [])
        check(list(prime_sieve_v1.iter_prime_window_chunks(empty_path, 5)) == [],
              "empty window yields no chunks")

        exact_path = os.path.join(tmpdir, "exact.bin")
        prime_sieve_v1.write_prime_window(exact_path, [2, 3, 5, 7])
        chunks = list(prime_sieve_v1.iter_prime_window_chunks(exact_path, 2))
        check(chunks == [[2, 3], [5, 7]], f"exact multiple of chunk_size splits cleanly (got {chunks})")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_append_hits_paged_within_one_page():
    tmpdir = tempfile.mkdtemp(prefix="hit_paging_append_")
    try:
        vdir = os.path.join(tmpdir, "10p3", "constellations", "k2", "variant1")
        meta = hit_paging.append_hits_paged(vdir, 3, 2, 1, [101, 103, 107])
        check(meta["total_count"] == 3, f"total_count after first append (got {meta['total_count']})")
        check(meta["first_value"] == 101, f"first_value set on first append (got {meta['first_value']})")
        check(meta["last_value"] == 107, f"last_value after first append (got {meta['last_value']})")
        check(hit_paging.page_count(meta) == 1, f"page_count == 1 (got {hit_paging.page_count(meta)})")

        meta = hit_paging.append_hits_paged(vdir, 3, 2, 1, [109, 113], meta=meta)
        check(meta["total_count"] == 5, f"total_count after second append (got {meta['total_count']})")
        check(meta["last_value"] == 113, f"last_value after second append (got {meta['last_value']})")

        values = hit_paging.read_page(vdir, 3, 2, 1, 0)
        check(values == [101, 103, 107, 109, 113], f"page 0 holds every appended value (got {values})")

        disk_meta = hit_paging.read_meta(vdir)
        check(disk_meta == meta, "read_meta() round-trips exactly what append_hits_paged() wrote")
        check(hit_paging.is_paged(vdir), "is_paged() true once a PAGES_META.json exists")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_append_hits_paged_spans_pages():
    tmpdir = tempfile.mkdtemp(prefix="hit_paging_span_")
    try:
        vdir = os.path.join(tmpdir, "10p3", "constellations", "k2", "variant1")
        meta = {"base_exponent": 3, "k": 2, "variant_id": 1, "page_size": 3,
                 "total_count": 0, "first_value": None, "last_value": None}

        all_values = [11, 13, 17, 19, 23, 29, 31]
        meta = hit_paging.append_hits_paged(vdir, 3, 2, 1, all_values, meta=meta)
        check(meta["total_count"] == 7, f"total_count across a page-spanning append (got {meta['total_count']})")
        check(hit_paging.page_count(meta) == 3,
              f"7 values at page_size=3 makes 3 pages (got {hit_paging.page_count(meta)})")

        page0 = hit_paging.read_page(vdir, 3, 2, 1, 0)
        page1 = hit_paging.read_page(vdir, 3, 2, 1, 1)
        page2 = hit_paging.read_page(vdir, 3, 2, 1, 2)
        check(page0 == [11, 13, 17], f"page 0 full at page_size (got {page0})")
        check(page1 == [19, 23, 29], f"page 1 full at page_size (got {page1})")
        check(page2 == [31], f"page 2 holds the remainder (got {page2})")

        more = hit_paging.append_hits_paged(vdir, 3, 2, 1, [37, 41, 43, 47], meta=meta)
        check(more["total_count"] == 11, f"total_count after a further page-spanning append (got {more['total_count']})")
        page2_again = hit_paging.read_page(vdir, 3, 2, 1, 2)
        page3 = hit_paging.read_page(vdir, 3, 2, 1, 3)
        check(page2_again == [31, 37, 41], f"appending continues filling the still-open page (got {page2_again})")
        check(page3 == [43, 47], f"overflow starts a fresh page (got {page3})")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_migrate_hit_file_to_pages():
    tmpdir = tempfile.mkdtemp(prefix="hit_paging_migrate_")
    try:
        vdir = os.path.join(tmpdir, "10p3", "constellations", "k2", "variant1")
        os.makedirs(vdir, exist_ok=True)
        source_path = os.path.join(vdir, "HITS_10p3_k2_v1.bin")
        original_values = [101 + 2 * i for i in range(23)]  # 23 odd-ish stand-in values
        prime_sieve_v1.write_prime_window(source_path, original_values)

        dry = hit_paging.migrate_hit_file_to_pages(source_path, vdir, 3, 2, 1, page_size=5, dry_run=True)
        check(dry["dry_run"] is True, "dry_run result flags dry_run")
        check(dry["total_count"] == len(original_values),
              f"dry_run reports the real total_count (got {dry['total_count']})")
        check(dry["page_count"] == 5, f"dry_run reports correct page_count (got {dry['page_count']})")
        check(not hit_paging.is_paged(vdir), "dry_run writes nothing (still unpaged)")
        check(os.path.exists(source_path), "dry_run leaves the original file untouched")

        result = hit_paging.migrate_hit_file_to_pages(source_path, vdir, 3, 2, 1, page_size=5)
        check(result["dry_run"] is False, "real migration result flags dry_run=False")
        check(result["total_count"] == len(original_values),
              f"real migration preserves total_count (got {result['total_count']})")
        check(result["page_count"] == 5, f"real migration created 5 pages (got {result['page_count']})")
        check(hit_paging.is_paged(vdir), "is_paged() true after real migration")
        check(not os.path.exists(source_path), "original single file renamed away after migration")
        check(os.path.exists(source_path + ".pre_page_migration.bak"), "backup of original file exists")

        reconstructed = []
        meta = hit_paging.read_meta(vdir)
        for i in range(hit_paging.page_count(meta)):
            reconstructed.extend(hit_paging.read_page(vdir, 3, 2, 1, i))
        check(reconstructed == original_values,
              f"reconstructed values across all pages == original (got {reconstructed})")

        raised = False
        try:
            hit_paging.migrate_hit_file_to_pages(source_path + ".pre_page_migration.bak", vdir, 3, 2, 1, page_size=5)
        except ValueError:
            raised = True
        check(raised, "migrating an already-paged pattern again raises ValueError")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_migrate_empty_file():
    tmpdir = tempfile.mkdtemp(prefix="hit_paging_migrate_empty_")
    try:
        vdir = os.path.join(tmpdir, "10p3", "constellations", "k9", "variant1")
        os.makedirs(vdir, exist_ok=True)
        source_path = os.path.join(vdir, "HITS_10p3_k9_v1.bin")
        prime_sieve_v1.write_prime_window(source_path, [])

        result = hit_paging.migrate_hit_file_to_pages(source_path, vdir, 3, 9, 1, page_size=5)
        check(result["total_count"] == 0, "migrating an empty hit file preserves total_count=0")
        check(result["page_count"] == 0, "migrating an empty hit file creates zero pages")
        meta = hit_paging.read_meta(vdir)
        check(meta["total_count"] == 0, "meta for an empty migrated pattern has total_count=0")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    test_iter_prime_window_chunks()
    test_append_hits_paged_within_one_page()
    test_append_hits_paged_spans_pages()
    test_migrate_hit_file_to_pages()
    test_migrate_empty_file()

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
