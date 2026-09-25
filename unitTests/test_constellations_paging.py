"""
test_constellations_paging.py -- proves primeatlas/constellations/constellations.py's records-table/
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
from primeatlas.constellations import constellations

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
    real archive would go through, not a hand-built PAGES_META.json."""
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


def test_hit_pattern_actual_page_size():
    tmpdir = tempfile.mkdtemp(prefix="const_paging_actualsize_")
    try:
        base = 10 ** 3
        values = [base + 2 * i for i in range(1, 13)]
        _make_paged_floor(tmpdir, 3, 2, 1, values, page_size=5)
        check(constellations.hit_pattern_actual_page_size(tmpdir, 3, 2, 1) == 5,
              f"a paged pattern's real page_size is read from its own metadata "
              f"(got {constellations.hit_pattern_actual_page_size(tmpdir, 3, 2, 1)})")

        unpaged_dir = os.path.join(tmpdir, "10p3", "constellations", "k9", "variant1")
        os.makedirs(unpaged_dir, exist_ok=True)
        prime_sieve_v1.write_prime_window(
            os.path.join(unpaged_dir, "HITS_10p3_k9_v1.bin"), [base + 1])
        check(constellations.hit_pattern_actual_page_size(tmpdir, 3, 9, 1) == hit_paging.PAGE_SIZE,
              "an unpaged pattern falls back to hit_paging.PAGE_SIZE (irrelevant there, but harmless)")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_write_constellation_detail_rows_csv():
    tmpdir = tempfile.mkdtemp(prefix="const_paging_csvwrite_")
    try:
        base = 10 ** 3
        values = [base + 2 * i for i in range(1, 13)]
        _make_paged_floor(tmpdir, 3, 2, 1, values, page_size=5)

        csv_path = os.path.join(tmpdir, "out.csv")
        rows = constellations.iter_constellation_records_detail_rows(tmpdir, 2)
        constellations.write_constellation_detail_rows_csv(csv_path, rows)
        with open(csv_path, encoding="utf-8") as f:
            lines = f.read().strip().splitlines()
        check(len(lines) == 1 + 12, f"CSV has a header + all 12 rows (got {len(lines)})")
        check(lines[0] == "exp,variant_id,offset,number,position_in_file,count_in_file,is_record_floor",
              f"CSV header matches the documented column order (got {lines[0]!r})")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_participation_search_bounded_page_reads_for_large_paged_pattern():
    """Regression test for the reported floor-25 bug: with ~100 billion numbers in
    storage, a search for a number or constellation used to grind to a halt because
    find_constellation_participation() decoded EVERY page of EVERY populated pattern
    into one big in-memory set before checking membership (k=2 on floor 25 alone is
    ~2 billion hits across ~2,000 pages). Simulates that shape at a tiny, fast scale
    (10 pages instead of thousands) and asserts the fixed lookup stays bounded --
    a handful of cheap page-HEADER reads (bisecting by each page's own first value,
    same trick storage.py's find_prime_in_floor already uses across whole window
    files) plus at most one or two full PAGE decodes, never one-per-page."""
    tmpdir = tempfile.mkdtemp(prefix="const_paging_bounded_")
    try:
        base = 10 ** 3
        values = [base + 2 * i for i in range(1, 51)]  # 50 bases -> 10 pages @ page_size=5
        _make_paged_floor(tmpdir, 3, 2, 1, values, page_size=5)

        page_read_calls = []
        header_read_calls = []
        real_read_page = hit_paging.read_page
        real_read_page_header = hit_paging.read_page_header

        def counting_read_page(*a, **k):
            page_read_calls.append(a)
            return real_read_page(*a, **k)

        def counting_read_page_header(*a, **k):
            header_read_calls.append(a)
            return real_read_page_header(*a, **k)

        hit_paging.read_page = counting_read_page
        hit_paging.read_page_header = counting_read_page_header
        try:
            target = values[27]  # deliberately deep into the pattern, not page 0
            results = constellations.find_constellation_participation(tmpdir, 3, target)
        finally:
            hit_paging.read_page = real_read_page
            hit_paging.read_page_header = real_read_page_header

        matches = [r for r in results if r["pattern"]["k"] == 2 and r["pattern"]["id"] == 1]
        # k=2's offsets are [0, 2] and these bases are themselves spaced 2 apart, so
        # `target` legitimately matches TWICE: as offset=0's own base (position 0),
        # and as offset=2's base (position 1, i.e. target is the previous pair's
        # "+2" member) -- see find_constellation_participation's own docstring on a
        # number showing up in more than one match, not just the first.
        positions = sorted(m["position"] for m in matches)
        check(positions == [0, 1],
              f"both legitimate offset matches still found under the bounded lookup (got {matches})")
        check(len(page_read_calls) <= 2,
              f"at most a couple of full PAGE decodes for a single-number search against "
              f"a 10-page pattern (got {len(page_read_calls)}) -- the old behavior decoded "
              f"all 10 pages into one big set for every search")
        # k=2 has two offsets, so this is up to TWO independent binary searches over
        # 10 pages (~ceil(log2(10))=4 probes each) -- bounded well under a one-header-
        # per-page linear scan (10), not down at a single search's own ~4.
        check(len(header_read_calls) <= 10,
              f"page-header reads stay logarithmic in page count, not linear "
              f"(10 pages, 2 offsets -> ~8 probes expected, got {len(header_read_calls)})")

        not_a_hit = base + 999999
        page_read_calls.clear()
        header_read_calls.clear()
        hit_paging.read_page = counting_read_page
        hit_paging.read_page_header = counting_read_page_header
        try:
            results2 = constellations.find_constellation_participation(tmpdir, 3, not_a_hit)
        finally:
            hit_paging.read_page = real_read_page
            hit_paging.read_page_header = real_read_page_header
        matches2 = [r for r in results2 if r["pattern"]["k"] == 2 and r["pattern"]["id"] == 1]
        check(len(matches2) == 0, "a value never stored still correctly reports no match")
        check(len(page_read_calls) <= 2,
              f"a NOT-FOUND search is bounded too, not just a found one (got {len(page_read_calls)})")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_participation_search_paged_pattern_does_not_grow_hit_set_cache():
    """hit_set_cache exists to make REPEATED searches against a small pattern cheap by
    decoding it once and reusing the in-memory set -- but for a dense, paged pattern
    (floor 25's k=2: ~2 billion values) building and keeping that set resident for the
    rest of the session is itself the OOM/latency risk this fix removes. A paged
    pattern's bounded per-offset page lookup should never populate hit_set_cache at
    all."""
    tmpdir = tempfile.mkdtemp(prefix="const_paging_cache_")
    try:
        base = 10 ** 3
        values = [base + 2 * i for i in range(1, 51)]
        _make_paged_floor(tmpdir, 3, 2, 1, values, page_size=5)

        cache = {}
        constellations.find_constellation_participation(tmpdir, 3, values[10], hit_set_cache=cache)
        key = (3, 2, 1)
        check(key not in cache,
              f"a paged (large) pattern's full value set is never cached in memory "
              f"(cache keys: {list(cache.keys())})")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_participation_search_multi_offset_pattern_across_pages():
    """k=3/v=1's offsets are [0, 2, 6] -- exercises the position>0 lookup branch (the
    number found is not itself the tuple's stored BASE, but base+2 or base+6) under
    paging, which the k=2 tests above (only offsets [0, 2]) don't reliably cover."""
    tmpdir = tempfile.mkdtemp(prefix="const_paging_multioffset_")
    try:
        base_floor = 10 ** 3
        values = [base_floor + 10 * i for i in range(1, 21)]  # 20 bases -> 4 pages @5
        _make_paged_floor(tmpdir, 3, 3, 1, values, page_size=5)

        target_base = values[13]  # deliberately from a later page
        for position, offset in enumerate((0, 2, 6)):
            number = target_base + offset
            results = constellations.find_constellation_participation(tmpdir, 3, number)
            matches = [r for r in results if r["pattern"]["k"] == 3 and r["pattern"]["id"] == 1]
            check(len(matches) == 1 and matches[0]["position"] == position,
                  f"offset index {position} (offset={offset}) correctly resolves to "
                  f"position={position} for a value on a later page (got {matches})")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_participation_search_finds_real_floor25_scale_number():
    """Regression test anchored on the exact number Artur reported the bug against (a
    real floor-25-scale value, 26 digits -- digit_count_floor() == 25): proves the
    bounded page lookup finds a value of THIS magnitude correctly, not just the small
    fixture values (~1000) the other tests above use, and stays bounded doing it."""
    tmpdir = tempfile.mkdtemp(prefix="const_paging_real_number_")
    try:
        number = 12345678901234709681436547
        base_exponent = 25
        check(len(str(number)) - 1 == base_exponent,
              f"sanity: this really is a floor-{base_exponent}-scale number "
              f"(got digit_count_floor={len(str(number)) - 1})")

        # A synthetic but realistically-shaped k=2 pattern anchored around the real
        # number: 25,000 twin-prime-ish bases, 25 pages @ page_size=1000, with
        # `number` itself planted partway through so it's found via offset=0.
        anchor = number - 2 * 12500
        values = [anchor + 2 * i for i in range(1, 25001)]
        check(number in values, "test setup: the real number is actually one of the seeded values")
        _make_paged_floor(tmpdir, base_exponent, 2, 1, values, page_size=1000)

        page_read_calls = []
        real_read_page = hit_paging.read_page

        def counting_read_page(*a, **k):
            page_read_calls.append(a)
            return real_read_page(*a, **k)

        hit_paging.read_page = counting_read_page
        try:
            results = constellations.find_constellation_participation(tmpdir, base_exponent, number)
        finally:
            hit_paging.read_page = real_read_page

        matches = [r for r in results if r["pattern"]["k"] == 2 and r["pattern"]["id"] == 1
                   and r["position"] == 0]
        check(len(matches) == 1,
              f"the real reported number is found at floor 25 scale (got {matches})")
        check(len(page_read_calls) <= 2,
              f"finding it decodes at most a couple of the 25 pages, not all of them "
              f"(got {len(page_read_calls)})")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    test_list_constellation_hits_sees_paged_pattern()
    test_records_table_sees_paged_pattern()
    test_detail_rows_span_every_page()
    test_participation_search_finds_paged_hits()
    test_iter_detail_rows_matches_list_version_and_count()
    test_hit_pattern_actual_page_size()
    test_write_constellation_detail_rows_csv()
    test_participation_search_bounded_page_reads_for_large_paged_pattern()
    test_participation_search_paged_pattern_does_not_grow_hit_set_cache()
    test_participation_search_multi_offset_pattern_across_pages()
    test_participation_search_finds_real_floor25_scale_number()

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
