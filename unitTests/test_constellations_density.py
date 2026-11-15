"""
test_constellations_density.py -- primeatlas/constellations/hl_density.py and density_scan.py:
the Hardy-Littlewood integral and constant, the covered spans of a floor, the hits counted
inside them and the scan over floors.

  - hl_integral() equals li differences (k = 1) and the closed form li(x) - x / ln x (k = 2),
    is additive, clips below 2, and keeps precision on a span 10^8 wide at 10^25;
  - the twin constant is 1.32032; an inadmissible pattern has C = 0 and no ratio;
  - twin primes up to 10^6 (8169) sit within 2 % below the prediction;
  - window_span() trusts the next window only when the prime count reaches it, decodes
    otherwise and below DECODE_BELOW; merge_spans() and the interval helpers at their edges;
  - end to end on a portal scanned by the real constellation_finder_v2_3.py: covered spans,
    hit counts and expectations equal a brute-force count over the same windows, with a
    window gap, a floor-wide window, a floor with no scan progress, a stray hit inside the
    gap (left out), a corrupt window, a partial scan, a paged hit file (whole pages counted
    from headers) and both adjacency paths (count check and decoding);
  - Stop before and during a scan leaves out every partial floor.

Usage:
    python unitTests\\test_constellations_density.py
"""
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "constellation"))

import hit_paging
import pattern_catalog_v1
import prime_sieve_v1
import window_sharding
from primeatlas.constellations import density_scan, hl_density
from primeatlas.research.pi_approx_window import li

FINDER = os.path.join(_REPO_ROOT, "constellation", "constellation_finder_v2_3.py")
LIMIT = 10 ** 6

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _close(a, b, rel):
    return abs(a - b) <= rel * max(abs(a), abs(b))


def _sieve(limit):
    flags = bytearray([1]) * (limit + 1)
    flags[0] = flags[1] = 0
    for p in range(2, math.isqrt(limit) + 1):
        if flags[p]:
            flags[p * p::p] = bytearray(len(flags[p * p::p]))
    return flags


FLAGS = _sieve(LIMIT)


def _primes(lo, hi):
    return [n for n in range(lo, hi) if FLAGS[n]]


# --- hl_density ---------------------------------------------------------------------------

def test_integral():
    for a, b in ((2, 10 ** 3), (10 ** 4, 10 ** 6), (2, 10 ** 12)):
        want = float(li(b)) - float(li(a))
        got = hl_density.hl_integral(a, b, 1)
        check(_close(got, want, 1e-9), f"k=1 over [{a}, {b}) equals li(b) - li(a) ({got} vs {want})")
    x = 10 ** 6
    want = (float(li(x)) - x / math.log(x)) - (float(li(2)) - 2 / math.log(2))
    check(_close(hl_density.hl_integral(2, x, 2), want, 1e-9), "k=2 equals li(x) - x/ln x")
    whole = hl_density.hl_integral(10, 10 ** 7, 3)
    parts = hl_density.hl_integral(10, 12345, 3) + hl_density.hl_integral(12345, 10 ** 7, 3)
    check(_close(whole, parts, 1e-10), "the integral is additive over a split point")
    check(hl_density.hl_integral(5, 5, 2) == 0.0 and hl_density.hl_integral(9, 5, 2) == 0.0,
          "an empty or reversed span integrates to 0")
    check(hl_density.hl_integral(0, 10, 2) == hl_density.hl_integral(2, 10, 2),
          "the part below 2 is left out")
    a = 10 ** 25
    narrow = hl_density.hl_integral(a, a + 10 ** 8, 15)
    flat = 10 ** 8 / math.log(a) ** 15
    check(_close(narrow, flat, 1e-6), f"a span 10^8 wide at 10^25 keeps precision ({narrow} vs {flat})")


def test_constant_and_compare():
    c2 = hl_density.pattern_constant([0, 2])
    check(abs(c2 - 1.3203236) < 1e-5, f"twin constant is 1.32032 (got {c2})")
    check(hl_density.pattern_constant([0, 2, 4]) == 0.0, "inadmissible (0, 2, 4) has C = 0")
    check(hl_density.expected_count([0, 2, 4], [(10, 10 ** 6)]) == 0.0,
          "inadmissible pattern expects 0")
    check(hl_density.compare(3, 0.0) == (None, None), "no ratio or sigma when 0 is expected")
    ratio, sigma = hl_density.compare(12, 9.0)
    check(ratio == 12 / 9 and sigma == 1.0, f"ratio 12/9 and sigma (12-9)/3 (got {ratio}, {sigma})")
    for pattern in pattern_catalog_v1.PATTERN_CATALOG:
        check(hl_density.pattern_constant(pattern["offsets"]) > 0,
              f"catalog pattern k={pattern['k']} v={pattern['id']} is admissible")


def test_twins_against_prediction():
    twins = sum(1 for p in range(3, LIMIT - 2) if FLAGS[p] and FLAGS[p + 2])
    check(twins == 8169, f"8169 twin prime pairs below 10^6 (got {twins})")
    expected = hl_density.expected_count([0, 2], [(2, LIMIT)])
    ratio = twins / expected
    check(0.98 < ratio < 1.0, f"twins / prediction in (0.98, 1.0) (got {ratio:.4f})")


# --- spans and interval helpers -----------------------------------------------------------

def test_window_span():
    calls = []

    def read_last():
        calls.append(1)
        return 4999

    base = 10 ** 9
    next_base = base + 10 ** 7
    count = round(hl_density.hl_integral(base, next_base, 1))
    check(density_scan.window_span(base, count, next_base, read_last) == (base, next_base)
          and not calls, "a full prime count trusts the next window without decoding")
    far = base + 10 ** 9
    check(density_scan.window_span(base, count, far, read_last) == (base, 5000) and calls,
          "a count far short of the span (a gap follows) decodes the last prime")
    calls.clear()
    small = density_scan.DECODE_BELOW - 1
    check(density_scan.window_span(10, small, 10 ** 7, read_last) == (10, 5000) and calls,
          "a window below DECODE_BELOW is always decoded")
    edge = max(n for n in range(5000, 5200) if n - 4999 <= math.log(n) ** 2)
    check(density_scan.window_span(10, small, edge, read_last) == (10, edge),
          f"a decoded last prime within (ln x)^2 of the next window reaches it ({edge})")
    check(density_scan.window_span(10, small, edge + 1, read_last) == (10, 5000),
          "one past (ln x)^2 is a gap")


def test_merge_and_helpers():
    merged = density_scan.merge_spans([(20, 30), (0, 10), (10, 15), (25, 40), (50, 60)])
    check(merged == [(0, 15), (20, 40), (50, 60)], f"spans merge when touching or overlapping ({merged})")
    iv = [(0, 15), (20, 40)]
    check(density_scan._inside_one(20, 40, iv) and not density_scan._inside_one(14, 21, iv)
          and not density_scan._inside_one(15, 20, iv), "inside one interval, at its edges")
    check(density_scan._disjoint(15, 20, iv) and density_scan._disjoint(40, 99, iv)
          and not density_scan._disjoint(14, 16, iv) and not density_scan._disjoint(-5, 1, iv),
          "disjoint from all intervals, at their edges")
    check(density_scan._count_sorted([0, 14, 15, 19, 20, 39, 40], iv) == 4,
          "values counted half-open per interval")


# --- end to end over a scanned portal -----------------------------------------------------

LAYOUT = {
    4: [(10 ** 4, 10 ** 5)],
    5: [(100_000, 150_000), (150_000, 200_000), (200_000, 250_000),
        (400_000, 450_000), (450_000, 500_000)],
    6: [(10 ** 6 - 50_000, 10 ** 6)],
}


def _write_windows(portal):
    for floor, windows in LAYOUT.items():
        shard = window_sharding.shard_dir(os.path.join(portal, f"10p{floor}", "source_primes"), 0)
        os.makedirs(shard, exist_ok=True)
        for lo, hi in windows:
            name = f"PRIME_WINDOW_10p{floor}_off_{prime_sieve_v1.format_offset(lo - 10 ** floor)}.bin"
            prime_sieve_v1.write_prime_window(os.path.join(shard, name), _primes(lo, hi))


def _run_finder(portal, floor, max_windows=None):
    args = [sys.executable, FINDER, str(floor)]
    if max_windows is not None:
        args += ["--max-windows", str(max_windows)]
    env = dict(os.environ, CONSTELLATION_PORTAL_DIR=portal)
    result = subprocess.run(args, capture_output=True, text=True, env=env, timeout=300)
    if result.returncode != 0:
        print(result.stdout[-2000:], result.stderr[-2000:])
    return result.returncode


def _truth(floor, done_windows):
    """Brute force over the same windows: spans from each done window's first prime to the
    next window's first prime when adjacent, to 10^(N+1) when the window ends the floor,
    else past its last prime; a base counts when every member is a prime of a written
    window."""
    windows = LAYOUT[floor]
    written = set()
    for lo, hi in windows:
        written.update(_primes(lo, hi))
    spans = []
    for i, (lo, hi) in enumerate(windows):
        if i not in done_windows:
            continue
        first = _primes(lo, hi)[0]
        if i + 1 < len(windows) and windows[i + 1][0] == hi:
            spans.append((first, _primes(*windows[i + 1])[0]))
        elif hi == 10 ** (floor + 1):
            spans.append((first, hi))
        else:
            spans.append((first, _primes(lo, hi)[-1] + 1))
    spans = density_scan.merge_spans(spans)
    hits = {}
    for pattern in pattern_catalog_v1.patterns_for_k(2) + pattern_catalog_v1.patterns_for_k(7):
        hits[(pattern["k"], pattern["id"])] = sum(
            1 for a, b in spans for p in _primes(a, b)
            if all(p + d in written for d in pattern["offsets"]))
    return spans, hits


def _rows_by_key(rows):
    return {(r["base_exponent"], r["k"], r["variant_id"]): r for r in rows}


def _check_floor(portal, floor, done, label):
    spans, hits = _truth(floor, done)
    got, info = density_scan.covered_intervals(portal, floor)
    check(got == spans, f"{label}: covered spans equal brute force ({got} vs {spans})")
    for (k, vid), want in hits.items():
        n = density_scan.count_hits_in(portal, floor, k, vid, got)
        check(n == want, f"{label}: k={k} v={vid} hits in spans = {want} (got {n})")
    return got, info


def test_end_to_end():
    portal = tempfile.mkdtemp(prefix="primeatlas_density_")
    try:
        _write_windows(portal)
        check(_run_finder(portal, 5, max_windows=2) == 0, "finder: first two windows of 10^5")
        _check_floor(portal, 5, {0, 1}, "partial scan")

        check(_run_finder(portal, 5) == 0 and _run_finder(portal, 4) == 0,
              "finder: the rest of 10^5 and all of 10^4")
        spans5, info5 = _check_floor(portal, 5, {0, 1, 2, 3, 4}, "full scan")
        check(len(spans5) == 2, f"the window gap splits 10^5 into two spans (got {spans5})")
        check(info5["windows"] == 5 and info5["done"] == 5, f"window counts ({info5})")
        spans4, _info4 = _check_floor(portal, 4, {0}, "floor-wide window")
        check(spans4 == [(_primes(10 ** 4, 10 ** 5)[0], 10 ** 5)], f"10^4 reaches the floor end ({spans4})")

        intervals6, info6 = density_scan.covered_intervals(portal, 6)
        check(intervals6 == [] and info6["done"] == 0, "a floor without scan progress has no spans")

        saved = density_scan.DECODE_BELOW
        density_scan.DECODE_BELOW = 0
        try:
            by_count, info_c = density_scan.covered_intervals(portal, 5)
        finally:
            density_scan.DECODE_BELOW = saved
        check(by_count == spans5 and info_c["decoded"] == 2,
              f"the count check reaches the same spans, decoding only the 2 run ends ({info_c})")

        # A stray hit in the gap, as the targeted k-tuple sieve writes it, is left out.
        hit_path = os.path.join(portal, "10p5", "constellations", "k2", "variant1",
                                "HITS_10p5_k2_v1.bin")
        values = prime_sieve_v1.read_prime_window(hit_path)
        stray = next(p for p in range(300_000, 400_000) if FLAGS[p] and FLAGS[p + 2])
        prime_sieve_v1.write_prime_window(hit_path, sorted(values + [stray]))
        _spans, hits5 = _truth(5, {0, 1, 2, 3, 4})
        n = density_scan.count_hits_in(portal, 5, 2, 1, spans5)
        check(n == hits5[(2, 1)], f"a stray hit in the gap is left out ({n})")

        # Paged: whole pages come from their headers, only edge pages are decoded.
        vdir = hit_paging.variant_dir(portal, 5, 2, 1)
        hit_paging.migrate_hit_file_to_pages(hit_path, vdir, 5, 2, 1, page_size=40)
        decoded = []
        original_read_page = hit_paging.read_page

        def counting_read_page(*args):
            decoded.append(args[-1])
            return original_read_page(*args)

        hit_paging.read_page = counting_read_page
        try:
            n = density_scan.count_hits_in(portal, 5, 2, 1, spans5)
        finally:
            hit_paging.read_page = original_read_page
        pages = hit_paging.page_count(hit_paging.read_meta(vdir))
        check(n == hits5[(2, 1)], f"paged hit file counts the same ({n})")
        check(0 < len(decoded) <= 4 < pages,
              f"only edge pages are decoded ({len(decoded)} of {pages})")

        rows, notes, stopped = density_scan.scan_density(portal, 2)
        keys = _rows_by_key(rows)
        check(not stopped and set(keys) == {(4, 2, 1), (5, 2, 1)},
              f"k=2 scan: one row per scanned floor, no sum row for one variant ({sorted(keys)})")
        check([f for f, _info in notes] == [4, 5, 6], "every floor is visited")
        row = keys[(5, 2, 1)]
        want_expected = hl_density.expected_count([0, 2], spans5)
        check(row["hits"] == hits5[(2, 1)] and _close(row["expected"], want_expected, 1e-12)
              and row["width"] == sum(b - a for a, b in spans5),
              f"k=2 row on 10^5: hits, expected and width ({row})")
        rows7, _notes, _stopped = density_scan.scan_density(portal, 7, floor_min=5, floor_max=5)
        keys7 = _rows_by_key(rows7)
        variants7 = [p["id"] for p in pattern_catalog_v1.patterns_for_k(7)]
        check(set(keys7) == {(5, 7, v) for v in variants7} | {(5, 7, None)},
              f"k=7: a row per variant plus a sum row ({sorted(keys7, key=str)})")
        total = keys7[(5, 7, None)]
        check(total["hits"] == sum(keys7[(5, 7, v)]["hits"] for v in variants7)
              and _close(total["expected"], sum(keys7[(5, 7, v)]["expected"] for v in variants7), 1e-12),
              "the sum row adds hits and expectations")

        # A corrupt window inside the gap: reported as unreadable, the spans stay the same.
        shard = window_sharding.shard_dir(os.path.join(portal, "10p5", "source_primes"), 0)
        corrupt = os.path.join(shard, "PRIME_WINDOW_10p5_off_200k.bin")
        with open(corrupt, "wb") as f:
            f.write(b"junk")
        spans_c, info_c = density_scan.covered_intervals(portal, 5)
        check(info_c["unreadable"] == 1 and spans_c == spans5,
              f"a corrupt window is reported, the spans stay the same ({info_c})")

        # Stop before the scan and after the first floor.
        event = threading.Event()
        event.set()
        rows_s, notes_s, stopped_s = density_scan.scan_density(portal, 2, stop_event=event)
        check(stopped_s and rows_s == [] and notes_s == [], "Stop before the scan returns nothing")
        event = threading.Event()
        seen = []

        def report(progress):
            seen.append(progress)
            event.set()

        rows_s, notes_s, stopped_s = density_scan.scan_density(
            portal, 2, stop_event=event, report_progress=report)
        check(stopped_s and [r["base_exponent"] for r in rows_s] == [4] and seen == [(1, 3)],
              f"Stop after the first floor keeps only that floor ({rows_s}, {seen})")
    finally:
        shutil.rmtree(portal, ignore_errors=True)


def main():
    test_integral()
    test_constant_and_compare()
    test_twins_against_prediction()
    test_window_span()
    test_merge_and_helpers()
    test_end_to_end()
    if failures:
        print(f"\n{len(failures)} check(s) FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
