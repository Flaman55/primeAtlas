"""
test_hit_insert_out_of_order.py -- constellation hits from a window that lies BELOW (or
between) already-scanned windows must be stored, not dropped as "duplicates".

Artur's report (2026-10-01): floor 25 had been scanned from 1.2345...e25 upward; he then
generated the first 1000 windows of the floor (from 10^25) and ran the k-tuple search.
It processed exactly those 1000 new windows (the done-range diff works), but every hit
was filtered as a duplicate -- _append_hits_deduped() treated "<= the file's last
value" as "already stored", which only holds while windows arrive in increasing order.
His rule: a window may be generated anywhere on a floor, even a single file between two
existing ranges, and the search must store whatever is new relative to what was already
searched -- not whatever is larger.

Spec covered here:
  hit_paging.insert_hits_paged()  -- sorted union into a paged pattern, touching only
      the pages the new values fall into; true duplicates skipped; an over-grown page
      split; legacy (uniform page_size) PAGES_META.json still readable and upgraded;
      no orphaned page files; plain appends keep working afterwards.
  hit_paging.page_start()         -- global position of a page's first entry once pages
      differ in size (records tab "position in file").
  constellation_finder_v2._append_hits_deduped() -- unpaged and paged patterns, the
      in-memory and on-disk last-value caches, a merge that crosses PAGE_SIZE.
  constellations.find_constellation_participation()/hit_pattern_page_start() -- readers
      over merged/split pages.

Usage:
    python unitTests\\test_hit_insert_out_of_order.py
"""
import os
import re
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "constellation"))
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


def _all_paged_values(vdir, b, k, v):
    meta = hit_paging.read_meta(vdir)
    out = []
    for i in range(hit_paging.page_count(meta)):
        out.extend(hit_paging.read_page(vdir, b, k, v, i))
    return out


def _page_files_on_disk(vdir):
    return sorted(f for f in os.listdir(vdir) if re.match(r"^HITS_.*_page\d+\.bin$", f))


def _legacy_paged(tmpdir, values, page_size=3):
    """A pattern paged the pre-2026-10-01 way: uniform page_size, no per-page list."""
    vdir = hit_paging.variant_dir(tmpdir, 3, 2, 1)
    meta = {"base_exponent": 3, "k": 2, "variant_id": 1, "page_size": page_size,
            "total_count": 0, "first_value": None, "last_value": None}
    hit_paging.append_hits_paged(vdir, 3, 2, 1, values, meta=meta)
    return vdir


def _check_meta_consistent(vdir, label):
    meta = hit_paging.read_meta(vdir)
    values = _all_paged_values(vdir, 3, 2, 1)
    check(values == sorted(set(values)), f"{label}: values strictly increasing across pages")
    check(meta["total_count"] == len(values),
          f"{label}: total_count == values on disk ({meta['total_count']} vs {len(values)})")
    check(meta["first_value"] == (values[0] if values else None)
          and meta["last_value"] == (values[-1] if values else None),
          f"{label}: first/last_value match the data")
    starts_ok = all(
        hit_paging.page_start(meta, i)
        == sum(len(hit_paging.read_page(vdir, 3, 2, 1, j)) for j in range(i))
        for i in range(hit_paging.page_count(meta)))
    check(starts_ok, f"{label}: page_start(i) == number of entries on pages before i")
    expected_files = sorted(os.path.basename(hit_paging.page_file(vdir, meta, i))
                            for i in range(hit_paging.page_count(meta)))
    check(_page_files_on_disk(vdir) == expected_files,
          f"{label}: no orphaned/missing page files (disk {_page_files_on_disk(vdir)} vs meta {expected_files})")
    biggest = max((len(hit_paging.read_page(vdir, 3, 2, 1, i))
                   for i in range(hit_paging.page_count(meta))), default=0)
    check(biggest <= 2 * meta["page_size"], f"{label}: no page above 2*page_size (largest {biggest})")
    return values


def test_paged_insert():
    print("\n--- hit_paging.insert_hits_paged ---")
    tmpdir = tempfile.mkdtemp(prefix="hit_insert_paged_")
    try:
        vdir = _legacy_paged(tmpdir, [11, 13, 17, 19, 23, 29, 31])

        meta, added, dup = hit_paging.insert_hits_paged(vdir, 3, 2, 1, [2, 3, 5])
        check((added, dup) == (3, 0), f"values below the first stored value are added (got {(added, dup)})")
        values = _check_meta_consistent(vdir, "below first")
        check(values == [2, 3, 5, 11, 13, 17, 19, 23, 29, 31], f"sorted union (got {values})")

        meta, added, dup = hit_paging.insert_hits_paged(vdir, 3, 2, 1, [12, 20, 24])
        check((added, dup) == (3, 0), f"values between stored ones are added (got {(added, dup)})")
        _check_meta_consistent(vdir, "between pages")

        before = _page_files_on_disk(vdir)
        meta, added, dup = hit_paging.insert_hits_paged(vdir, 3, 2, 1, [13, 23, 31])
        check((added, dup) == (0, 3), f"exact re-scan: all duplicates (got {(added, dup)})")
        check(_page_files_on_disk(vdir) == before, "a pure-duplicate insert rewrites no page")

        meta, added, dup = hit_paging.insert_hits_paged(vdir, 3, 2, 1, [4, 13, 30, 37, 41])
        check((added, dup) == (4, 1), f"mixed: below, duplicate, between, beyond last (got {(added, dup)})")
        values = _check_meta_consistent(vdir, "mixed")
        check(values == [2, 3, 4, 5, 11, 12, 13, 17, 19, 20, 23, 24, 29, 30, 31, 37, 41],
              f"mixed sorted union (got {values})")

        many = list(range(100, 200, 2))  # 50 values beyond last -> plain append path
        hit_paging.insert_hits_paged(vdir, 3, 2, 1, many)
        dense = list(range(101, 160, 2))  # 30 values all inside one region -> split
        meta, added, dup = hit_paging.insert_hits_paged(vdir, 3, 2, 1, dense)
        check((added, dup) == (30, 0), f"dense insert added (got {(added, dup)})")
        values = _check_meta_consistent(vdir, "after split")
        check(len(values) == 17 + 50 + 30, f"nothing lost across splits (got {len(values)})")

        meta = hit_paging.append_hits_paged(vdir, 3, 2, 1, [500, 501, 502, 503])
        values = _check_meta_consistent(vdir, "append after insert")
        check(values[-4:] == [500, 501, 502, 503], "append_hits_paged still appends after inserts")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_finder_unpaged():
    print("\n--- _append_hits_deduped, unpaged pattern ---")
    import constellation_finder_v2 as cf2
    tmp_portal = tempfile.mkdtemp(prefix="hit_insert_unpaged_")
    try:
        cf2.PORTAL_FOLDER = tmp_portal
        b, k, v = 3, 6, 1
        cache, disk = {}, {}
        check(cf2._append_hits_deduped(b, k, v, [100, 110, 120], last_value_cache=cache, disk_cache=disk)
              == (3, 0), "first (upper) windows' hits stored")
        # Artur's case: a window generated later at the START of the floor.
        got = cf2._append_hits_deduped(b, k, v, [50, 60], last_value_cache=cache, disk_cache=disk)
        check(got == (2, 0), f"hits from a lower, newly generated window are stored (got {got})")
        got = cf2._append_hits_deduped(b, k, v, [105], last_value_cache=cache, disk_cache=disk)
        check(got == (1, 0), f"a hit between stored ones is stored (got {got})")
        got = cf2._append_hits_deduped(b, k, v, [50, 105, 120], last_value_cache=cache, disk_cache=disk)
        check(got == (0, 3), f"re-scanning covered windows still skips true duplicates (got {got})")
        values = prime_sieve_v1.read_prime_window(cf2.hit_file_path(b, k, v))
        check(values == [50, 60, 100, 105, 110, 120], f"file holds the sorted union (got {values})")
        check(cache[(k, v)] == (120, 6) and disk[(k, v)] == (120, 6),
              f"both caches track (last_value, count) after a merge (got {cache[(k, v)]}, {disk[(k, v)]})")
        got = cf2._append_hits_deduped(b, k, v, [60, 130], last_value_cache={}, disk_cache=dict(disk))
        check(got == (1, 1), f"a fresh run (empty memory cache) stays correct (got {got})")
    finally:
        shutil.rmtree(tmp_portal, ignore_errors=True)


def test_finder_unpaged_merge_crosses_page_size():
    print("\n--- _append_hits_deduped, merge crossing PAGE_SIZE ---")
    import constellation_finder_v2 as cf2
    tmp_portal = tempfile.mkdtemp(prefix="hit_insert_cross_")
    original = hit_paging.PAGE_SIZE
    hit_paging.PAGE_SIZE = 5
    try:
        cf2.PORTAL_FOLDER = tmp_portal
        b, k, v = 3, 2, 1
        cache = {}
        cf2._append_hits_deduped(b, k, v, [100, 101, 102, 103], last_value_cache=cache)
        got = cf2._append_hits_deduped(b, k, v, [10, 11, 12], last_value_cache=cache)
        check(got == (3, 0), f"lower hits stored across the PAGE_SIZE crossing (got {got})")
        vdir = hit_paging.variant_dir(tmp_portal, b, k, v)
        check(hit_paging.is_paged(vdir), "pattern auto-migrated to pages once the merge exceeded PAGE_SIZE")
        values = _all_paged_values(vdir, b, k, v)
        check(values == [10, 11, 12, 100, 101, 102, 103], f"paged sorted union (got {values})")
        check(cache[(k, v)] == (103, 7), f"cache after the crossing (got {cache[(k, v)]})")
    finally:
        hit_paging.PAGE_SIZE = original
        shutil.rmtree(tmp_portal, ignore_errors=True)


def test_finder_paged():
    print("\n--- _append_hits_deduped, paged pattern (k=2/3/4 on floor 25) ---")
    import constellation_finder_v2 as cf2
    tmp_portal = tempfile.mkdtemp(prefix="hit_insert_finder_paged_")
    try:
        cf2.PORTAL_FOLDER = tmp_portal
        vdir = _legacy_paged(tmp_portal, list(range(1000, 1030)), page_size=4)
        cache = {}
        got = cf2._append_hits_deduped(3, 2, 1, [7, 8, 9], last_value_cache=cache)
        check(got == (3, 0), f"lower window's hits stored in a paged pattern (got {got})")
        got = cf2._append_hits_deduped(3, 2, 1, [7, 1015, 1031], last_value_cache=cache)
        check(got == (1, 2), f"duplicates skipped, new tail appended (got {got})")
        values = _all_paged_values(vdir, 3, 2, 1)
        check(values == [7, 8, 9] + list(range(1000, 1030)) + [1031], f"paged sorted union (got {values[:6]}...)")
        check(cache[(2, 1)] == (1031, 34), f"cache (last_value, count) (got {cache[(2, 1)]})")
    finally:
        shutil.rmtree(tmp_portal, ignore_errors=True)


def test_process_floor_lower_windows_later():
    """Artur's exact sequence at test scale: the upper part of a floor is scanned first,
    the windows at the floor's start are generated afterwards and scanned in batches
    (--max-windows). Out-of-order hits are written in one merge per batch (not one page
    rewrite per window), and a window only counts as done once its hits are stored."""
    print("\n--- process_floor: windows generated below an already-scanned range ---")
    import window_sharding
    import constellation_finder_v2 as cf2
    tmp_portal = tempfile.mkdtemp(prefix="hit_insert_process_floor_")
    try:
        cf2.PORTAL_FOLDER = tmp_portal
        floor = 61

        def write_window(name, primes):
            shard = window_sharding.shard_dir(os.path.join(tmp_portal, f"10p{floor}", "source_primes"), 0)
            os.makedirs(shard, exist_ok=True)
            prime_sieve_v1.write_prime_window(os.path.join(shard, name), sorted(primes))

        def twins():
            path = cf2.hit_file_path(floor, 2, 1)
            return prime_sieve_v1.read_prime_window(path) if os.path.exists(path) else []

        write_window("PRIME_WINDOW_D.bin", [701, 703])
        write_window("PRIME_WINDOW_E.bin", [901, 903])
        cf2.process_floor(floor)
        check(twins() == [701, 901], f"upper windows scanned first (got {twins()})")

        write_window("PRIME_WINDOW_A.bin", [101, 103])
        write_window("PRIME_WINDOW_B.bin", [301, 303])
        write_window("PRIME_WINDOW_C.bin", [501, 503])

        inserts = []
        real_insert = cf2._insert_hits_sorted

        def counting_insert(*args):
            inserts.append(args)
            return real_insert(*args)

        cf2._insert_hits_sorted = counting_insert
        try:
            remaining = cf2.process_floor(floor, max_windows=2)
        finally:
            cf2._insert_hits_sorted = real_insert
        check(remaining == 1, f"batch of 2 leaves 1 window pending (got {remaining})")
        check(twins() == [101, 301, 701, 901],
              f"hits of the lower, later-generated windows are stored (got {twins()})")
        check(len([a for a in inserts if a[1] == 2]) == 1,
              f"one merge per pattern per batch, not one per window (k=2 merges: "
              f"{len([a for a in inserts if a[1] == 2])})")

        def boom(*args):
            raise RuntimeError("simulated crash while merging")

        cf2._insert_hits_sorted = boom
        try:
            try:
                cf2.process_floor(floor)
            except RuntimeError:
                pass
        finally:
            cf2._insert_hits_sorted = real_insert
        names = [w[0] for w in cf2.list_source_windows(floor)]
        done = cf2.resolve_done_names(floor, names)
        check("PRIME_WINDOW_C.bin" not in done,
              "a window whose out-of-order hits were never stored is not marked done")

        cf2.process_floor(floor)
        check(twins() == [101, 301, 501, 701, 901], f"the re-run stores the missing hit (got {twins()})")
        done = cf2.resolve_done_names(floor, names)
        check(done == set(names), "every window done after the re-run")
    finally:
        shutil.rmtree(tmp_portal, ignore_errors=True)


def test_process_floor_window_inserted_between():
    """A single window generated between two already-scanned neighbours: constellations
    that straddle its boundaries with them must be found. Its successor is already done
    (so it is not the next window of this batch) and its predecessor was scanned while
    this window did not exist yet (so that scan could not look into it)."""
    print("\n--- process_floor: one window inserted between scanned neighbours ---")
    import window_sharding
    import constellation_finder_v2 as cf2
    tmp_portal = tempfile.mkdtemp(prefix="hit_insert_between_")
    try:
        cf2.PORTAL_FOLDER = tmp_portal
        floor = 62

        def write_window(name, primes):
            shard = window_sharding.shard_dir(os.path.join(tmp_portal, f"10p{floor}", "source_primes"), 0)
            os.makedirs(shard, exist_ok=True)
            prime_sieve_v1.write_prime_window(os.path.join(shard, name), sorted(primes))

        def twins():
            path = cf2.hit_file_path(floor, 2, 1)
            return prime_sieve_v1.read_prime_window(path) if os.path.exists(path) else []

        write_window("PRIME_WINDOW_P.bin", [1001, 1009, 1019])   # ends with 1019
        write_window("PRIME_WINDOW_S.bin", [1061, 1069, 1087])   # starts with 1061
        cf2.process_floor(floor)
        check(twins() == [], f"no twins inside P or S on their own (got {twins()})")

        # W fills the gap: 1019|1021 straddles P->W, 1059|1061 straddles W->S.
        write_window("PRIME_WINDOW_W.bin", [1021, 1031, 1039, 1049, 1051, 1059])
        cf2.process_floor(floor)
        got = twins()
        check(1019 in got, f"twin straddling the scanned predecessor and the new window found (got {got})")
        check(1059 in got, f"twin straddling the new window and the scanned successor found (got {got})")
        check(got == [1019, 1049, 1059], f"exactly the twins of the joined range (got {got})")
    finally:
        shutil.rmtree(tmp_portal, ignore_errors=True)


def test_process_floor_far_neighbours():
    """Artur's real floor 25 after the fix (2026-10-01): the last of the 1000 low windows
    (ending near 10^25 + 10^10) has, as its real successor, the old floor start at
    1.2345e25. Peeking into it made match_patterns_vectorized() turn values ~2.3e24 away
    into int64 offsets -- OverflowError, run aborted. Neighbours only matter within
    max_span of the window; farther values must be ignored, not crash."""
    print("\n--- process_floor: real neighbours far away (floor-25 magnitudes) ---")
    import window_sharding
    import constellation_finder_v2 as cf2
    tmp_portal = tempfile.mkdtemp(prefix="hit_insert_far_")
    try:
        cf2.PORTAL_FOLDER = tmp_portal
        floor = 25
        low = 10 ** 25
        high = 12345678901234567890000023

        def write_window(name, primes):
            shard = window_sharding.shard_dir(os.path.join(tmp_portal, f"10p{floor}", "source_primes"), 0)
            os.makedirs(shard, exist_ok=True)
            prime_sieve_v1.write_prime_window(os.path.join(shard, name), sorted(primes))

        def twins():
            path = cf2.hit_file_path(floor, 2, 1)
            return prime_sieve_v1.read_prime_window(path) if os.path.exists(path) else []

        write_window("PRIME_WINDOW_HIGH.bin", [high, high + 2])
        cf2.process_floor(floor)
        write_window("PRIME_WINDOW_LOW.bin", [low + 559, low + 561])
        try:
            cf2.process_floor(floor)
            crashed = None
        except OverflowError as e:
            crashed = e
        check(crashed is None, f"a far successor does not crash the scan (got {crashed!r})")
        check(twins() == [low + 559, high], f"both windows' twins stored (got {twins()})")
    finally:
        shutil.rmtree(tmp_portal, ignore_errors=True)


def test_readers():
    print("\n--- readers over merged/split pages ---")
    from primeatlas.constellations import constellations
    tmpdir = tempfile.mkdtemp(prefix="hit_insert_readers_")
    try:
        vdir = _legacy_paged(tmpdir, list(range(1000, 1012)), page_size=3)
        hit_paging.insert_hits_paged(vdir, 3, 2, 1, list(range(1, 8)))
        meta = hit_paging.read_meta(vdir)
        starts = [constellations.hit_pattern_page_start(tmpdir, 3, 2, 1, i)
                  for i in range(hit_paging.page_count(meta))]
        check(starts == [hit_paging.page_start(meta, i) for i in range(hit_paging.page_count(meta))],
              f"hit_pattern_page_start follows the real page sizes (got {starts})")
        check(constellations.hit_pattern_page_start(tmpdir, 3, 9, 1, 0) == 0,
              "unpaged/missing pattern: page 0 starts at 0")
        found = constellations._find_value_in_paged_pattern(vdir, 3, 2, 1, meta, 4)
        found_high = constellations._find_value_in_paged_pattern(vdir, 3, 2, 1, meta, 1011)
        missing = constellations._find_value_in_paged_pattern(vdir, 3, 2, 1, meta, 500)
        check(found and found_high and not missing,
              "value lookup finds inserted and original values, not absent ones")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    test_paged_insert()
    test_finder_unpaged()
    test_finder_unpaged_merge_crosses_page_size()
    test_finder_paged()
    test_process_floor_lower_windows_later()
    test_process_floor_window_inserted_between()
    test_process_floor_far_neighbours()
    test_readers()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"FAIL: {f}")
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
