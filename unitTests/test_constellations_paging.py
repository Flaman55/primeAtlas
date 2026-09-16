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


def test_iter_detail_rows_matches_list_version_and_count():
    tmpdir = tempfile.mkdtemp(prefix="const_paging_iter_")
    try:
        base = 10 ** 3
        values = [base + 2 * i for i in range(1, 13)]
        _make_paged_floor(tmpdir, 3, 2, 1, values, page_size=5)

        streamed = list(constellations.iter_constellation_records_detail_rows(tmpdir, 2))
        _variant_ids, _variant_meta, listed = constellations.build_constellation_records_detail_rows(
            tmpdir, 2)
        check(streamed == listed,
              "iter_constellation_records_detail_rows() yields the exact same rows "
              "build_constellation_records_detail_rows() returns as a list")

        total = constellations.count_constellation_records_detail_rows(tmpdir, 2)
        check(total == len(values), f"count_constellation_records_detail_rows() == 12 (got {total})")
        check(total == len(streamed),
              "count_constellation_records_detail_rows() matches the actual row count")

        # A generator never materializes -- calling it twice starts a FRESH stream
        # rather than reusing exhausted state, exactly like build_...()'s own list
        # would be freshly rebuilt on a second call.
        streamed_again = list(constellations.iter_constellation_records_detail_rows(tmpdir, 2))
        check(streamed_again == listed, "a second iteration reproduces the same rows")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_page_range_export_scopes_to_one_pattern_and_page_window():
    tmpdir = tempfile.mkdtemp(prefix="const_paging_range_")
    try:
        base = 10 ** 3
        # page_size=5 -> pages [0:0-4] [1:5-9] [2:10-11] (12 values total, 3 pages)
        values = [base + 2 * i for i in range(1, 13)]
        _make_paged_floor(tmpdir, 3, 2, 1, values, page_size=5)

        # A second, UNRELATED pattern on the same floor -- proves the range export
        # stays scoped to (base_exponent, k, variant_id) and never leaks another
        # pattern's rows in.
        other_dir = os.path.join(tmpdir, "10p3", "constellations", "k3", "variant1")
        os.makedirs(other_dir, exist_ok=True)
        prime_sieve_v1.write_prime_window(
            os.path.join(other_dir, "HITS_10p3_k3_v1.bin"), [base + 999])

        middle_page = list(constellations.iter_hit_pattern_page_range_rows(tmpdir, 3, 2, 1, 1, 1))
        check([r["number"] for r in middle_page] == values[5:10],
              f"page range [1,1] returns exactly page 1's values (got {[r['number'] for r in middle_page]})")
        check(all(r["variant_id"] == 1 and r["base_exponent"] == 3 for r in middle_page),
              "every row in the range stays scoped to the requested pattern/floor")
        check([r["position_in_file"] for r in middle_page] == [5, 6, 7, 8, 9],
              f"position_in_file continues from where page 1 actually starts (got {[r['position_in_file'] for r in middle_page]})")

        full_range = list(constellations.iter_hit_pattern_page_range_rows(tmpdir, 3, 2, 1, 0, 2))
        check([r["number"] for r in full_range] == values,
              "page range [0,2] (every page) returns every value in order")

        clamped = list(constellations.iter_hit_pattern_page_range_rows(tmpdir, 3, 2, 1, -5, 999))
        check([r["number"] for r in clamped] == values,
              "an out-of-bounds range is clamped to the real [0, page_count-1] instead of raising")

        empty = list(constellations.iter_hit_pattern_page_range_rows(tmpdir, 3, 2, 1, 5, 2))
        check(empty == [], f"page_from > page_to (after clamping) yields nothing (got {empty})")

        missing = list(constellations.iter_hit_pattern_page_range_rows(tmpdir, 3, 2, 99, 0, 0))
        check(missing == [], "a nonexistent variant yields nothing rather than raising")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_write_constellation_detail_rows_csv():
    tmpdir = tempfile.mkdtemp(prefix="const_paging_csvwrite_")
    try:
        base = 10 ** 3
        values = [base + 2 * i for i in range(1, 13)]
        _make_paged_floor(tmpdir, 3, 2, 1, values, page_size=5)

        csv_path = os.path.join(tmpdir, "out.csv")
        rows = constellations.iter_hit_pattern_page_range_rows(tmpdir, 3, 2, 1, 0, 1)
        constellations.write_constellation_detail_rows_csv(csv_path, rows)
        with open(csv_path, encoding="utf-8") as f:
            lines = f.read().strip().splitlines()
        check(len(lines) == 1 + 10, f"CSV has a header + 10 rows for pages [0,1] (got {len(lines)})")
        check(lines[0] == "exp,variant_id,offset,number,position_in_file,count_in_file,is_record_floor",
              f"CSV header matches the documented column order (got {lines[0]!r})")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    test_list_constellation_hits_sees_paged_pattern()
    test_records_table_sees_paged_pattern()
    test_detail_rows_span_every_page()
    test_participation_search_finds_paged_hits()
    test_iter_detail_rows_matches_list_version_and_count()
    test_page_range_export_scopes_to_one_pattern_and_page_window()
    test_write_constellation_detail_rows_csv()

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
