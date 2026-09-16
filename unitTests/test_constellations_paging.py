"""
test_constellations_paging.py -- proves primeatlas/constellations.py's records-table/
detail-rows/participation-search backend stays CORRECT once a pattern's hit file has
been migrated to pages (prime_sieve/hit_paging.py), not just that it doesn't crash.
Complements unitTests/test_hit_paging.py (pure hit_paging.py mechanics, no
primeatlas involvement) and unitTests/test_constellations_tab.py (the real Tkinter
GUI, but only ever exercises the small, UNPAGED path -- its own fixture is a single
seeded hit). No display needed here -- constellations.py's records-table/detail-rows/
participation functions are pure (no tkinter), same reasoning that file's own
docstring gives.

Usage:
    python unitTests\\test_constellations_paging.py
"""
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "constellation"))

import prime_sieve_v1
import hit_paging
from primeatlas import constellations

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _make_paged_floor(portal_folder, base_exponent, k, variant_id, values, page_size):
    """Seeds a floor's k/variant hit file the normal way (write_prime_window), then
    migrates it to pages -- so this test exercises the exact same migration path a
    real magazyn would go through, not a hand-built PAGES_META.json."""
    vdir = os.path.join(portal_folder, f"10p{base_exponent}", "constellations",
                         f"k{k}", f"variant{variant_id}")
    os.makedirs(vdir, exist_ok=True)
    source_path = os.path.join(
        vdir, f"HITS_10p{base_exponent}_k{k}_v{variant_id}.bin")
    prime_sieve_v1.write_prime_window(source_path, values)
    hit_paging.migrate_hit_file_to_pages(source_path, vdir, base_exponent, k, variant_id,
                                          page_size=page_size)
    return vdir


def test_list_constellation_hits_sees_paged_pattern():
    tmpdir = tempfile.mkdtemp(prefix="const_paging_list_")
    try:
        base = 10 ** 3
        values = [base + 2 * i for i in range(1, 13)]  # 12 values, twin-prime-ish bases
        _make_paged_floor(tmpdir, 3, 2, 1, values, page_size=5)

        entries = constellations.list_constellation_hits(tmpdir, 3)
        matches = [(p, path, h) for p, path, h in entries if p["k"] == 2 and p["id"] == 1]
        check(len(matches) == 1, f"paged k=2/v=1 pattern shows up exactly once (got {len(matches)})")
        _pattern, _path, header = matches[0]
        check(header is not None, "paged pattern's header is not None")
        check(header["count"] == 12, f"paged pattern's header count == 12 (got {header['count']})")
        check(header["base_prime"] == values[0],
              f"paged pattern's header base_prime == smallest value (got {header['base_prime']})")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_records_table_sees_paged_pattern():
    tmpdir = tempfile.mkdtemp(prefix="const_paging_table_")
    try:
        base = 10 ** 3
        values = [base + 2 * i for i in range(1, 13)]
        _make_paged_floor(tmpdir, 3, 2, 1, values, page_size=5)

        variant_ids, _variant_meta, rows = constellations.build_constellation_records_table(tmpdir, 2)
        check(1 in variant_ids, f"variant 1 present in table columns (got {variant_ids})")
        check(len(rows) == 1, f"exactly one floor row (got {len(rows)})")
        cell = rows[0]["cells"][1]
        check(cell is not None, "cell for the paged pattern is populated, not None")
        check(cell["count"] == 12, f"cell count == 12 (got {cell['count']})")
        check(cell["offset"] == values[0] - base, f"cell offset == smallest value's offset (got {cell['offset']})")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_detail_rows_span_every_page():
    tmpdir = tempfile.mkdtemp(prefix="const_paging_detail_")
    try:
        base = 10 ** 3
        values = [base + 2 * i for i in range(1, 13)]
        _make_paged_floor(tmpdir, 3, 2, 1, values, page_size=5)

        _variant_ids, _variant_meta, rows = constellations.build_constellation_records_detail_rows(tmpdir, 2)
        numbers = [r["number"] for r in rows]
        check(numbers == values, f"detail rows cover every value across all 3 pages, in order (got {numbers})")
        check(all(r["count_in_file"] == 12 for r in rows),
              "every detail row reports the PATTERN-wide count_in_file (12), not a per-page count")
        positions = [r["position_in_file"] for r in rows]
        check(positions == list(range(12)),
              f"position_in_file is a global running index across pages (got {positions})")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_participation_search_finds_paged_hits():
    tmpdir = tempfile.mkdtemp(prefix="const_paging_search_")
    try:
        base = 10 ** 3
        values = [base + 2 * i for i in range(1, 13)]
        _make_paged_floor(tmpdir, 3, 2, 1, values, page_size=5)

        target = values[7]  # deliberately from a LATER page (page index 1, 0-based)
        results = constellations.find_constellation_participation(tmpdir, 3, target)
        matches = [r for r in results if r["pattern"]["k"] == 2 and r["pattern"]["id"] == 1
                   and r["position"] == 0]
        check(len(matches) == 1,
              f"a value stored on a LATER page is still found by participation search (got {len(matches)})")

        not_a_hit = base + 999999
        results2 = constellations.find_constellation_participation(tmpdir, 3, not_a_hit)
        matches2 = [r for r in results2 if r["pattern"]["k"] == 2 and r["pattern"]["id"] == 1]
        check(len(matches2) == 0, "a value never stored is correctly reported as no match")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    test_list_constellation_hits_sees_paged_pattern()
    test_records_table_sees_paged_pattern()
    test_detail_rows_span_every_page()
    test_participation_search_finds_paged_hits()

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
