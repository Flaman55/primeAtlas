"""
density_scan.py -- hit counts of k-tuple patterns next to their Hardy-Littlewood prediction,
over exactly the spans the constellation finder has scanned. No tkinter; reads storage,
never writes it.

Coverage. A done window (DONE_WINDOWS.txt / CHECKPOINT.txt, resolved by
constellation_progress_v2_3.resolve_done_names()) holds every prime from its first one
(header base_prime) to its last. Its span runs from its base_prime to the base_prime of the
next window on disk, or to 10^(N+1) for the floor's last window: no primes lie between two
adjacent windows. Window widths are not stored, so adjacency is checked by the window's own
prime count against the prime count the span predicts, li(end) - li(base). A window whose
count falls short by more than ADJACENCY_SIGMAS, or that is small enough to decode
cheaply, is decoded: it reaches the next window when its last prime lies within (ln x)^2
of it, else (a gap follows) it ends after its last prime.

Hits. Only hits whose base lies inside the covered spans count: the targeted k-tuple sieve
writes into the same hit files from scattered locations outside them. A paged pattern adds
a whole page by its header count when the page lies inside one span, and decodes only the
pages that cross a span's edge.
"""
import bisect
import math

import constellation_progress_v2_3
import hit_paging
import pattern_catalog_v1
import prime_sieve_v1

from ..core.storage import list_floors, list_source_filenames
from .constellations import hit_file_path
from .hl_density import compare, expected_count, hl_integral

ADJACENCY_SIGMAS = 3.0
"""A window whose prime count is below li(span) - ADJACENCY_SIGMAS * sqrt(li(span)) is not
adjacent to the next one; arbitrary."""

DECODE_BELOW = 100_000
"""Windows with fewer primes are decoded for their last prime, never judged by count;
arbitrary, bounds the count check's slack to about 1 % of a span."""


def _floor_end(base_exponent):
    return 10 ** (base_exponent + 1)


def window_span(base, count, next_base, read_last):
    """[start, end) of one done window: base to next_base when the window reaches it, else
    base to its last prime + 1. The prime count decides without decoding; otherwise
    read_last() decodes the last prime, and a distance to next_base of at most (ln x)^2,
    the scale of the largest prime gaps, still counts as reaching it."""
    if count >= DECODE_BELOW:
        expected = hl_integral(base, next_base, 1)
        if count >= expected - ADJACENCY_SIGMAS * math.sqrt(expected):
            return base, next_base
    last = read_last()
    if next_base - last <= math.log(next_base) ** 2:
        return base, next_base
    return base, last + 1


def merge_spans(spans):
    """Sorted, merged union of [a, b) spans."""
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def covered_intervals(portal, base_exponent, stop_event=None):
    """(intervals, info) for one floor: the merged spans of its done windows and
    {"windows": all windows, "done": done ones, "decoded": windows whose last prime was
    decoded, "unreadable": windows without a readable header}. intervals is [] when the
    floor has no scan progress."""
    info = {"windows": 0, "done": 0, "decoded": 0, "unreadable": 0}
    if (constellation_progress_v2_3.read_done_log(portal, base_exponent) is None
            and not constellation_progress_v2_3.read_done_ranges(portal, base_exponent)):
        return [], info
    entries = []
    for name, path in list_source_filenames(portal, base_exponent):
        try:
            header = prime_sieve_v1.read_prime_window_header(path)
        except Exception:
            header = None
        if header is None or header["base_prime"] is None:
            info["unreadable"] += 1
            continue
        entries.append((header["base_prime"], name, path, header["count"]))
    entries.sort()
    info["windows"] = len(entries)
    names = [name for _base, name, _path, _count in entries]
    done = constellation_progress_v2_3.resolve_done_names(portal, base_exponent, names)
    spans = []
    for i, (base, name, path, count) in enumerate(entries):
        if stop_event is not None and stop_event.is_set():
            break
        if name not in done:
            continue
        info["done"] += 1
        next_base = entries[i + 1][0] if i + 1 < len(entries) else _floor_end(base_exponent)

        def read_last(path=path):
            info["decoded"] += 1
            return prime_sieve_v1.read_prime_window(path)[-1]

        spans.append(window_span(base, count, next_base, read_last))
    return merge_spans(spans), info


def _count_sorted(values, intervals):
    return sum(bisect.bisect_left(values, b) - bisect.bisect_left(values, a)
               for a, b in intervals)


def _inside_one(a, b, intervals):
    """True when [a, b) lies inside one of the sorted disjoint intervals."""
    i = bisect.bisect_right(intervals, (a, float("inf"))) - 1
    return i >= 0 and intervals[i][0] <= a and b <= intervals[i][1]


def _disjoint(a, b, intervals):
    """True when [a, b) meets none of the sorted disjoint intervals."""
    i = bisect.bisect_right(intervals, (a, float("inf"))) - 1
    if i >= 0 and intervals[i][1] > a:
        return False
    return i + 1 >= len(intervals) or intervals[i + 1][0] >= b


def count_hits_in(portal, base_exponent, k, variant_id, intervals, stop_event=None):
    """Hits of one pattern whose base lies in the intervals."""
    if not intervals:
        return 0
    vdir = hit_paging.variant_dir(portal, base_exponent, k, variant_id)
    if not hit_paging.is_paged(vdir):
        try:
            values = prime_sieve_v1.read_prime_window(
                hit_file_path(portal, base_exponent, k, variant_id))
        except OSError:
            return 0
        return _count_sorted(values, intervals)
    meta = hit_paging.read_meta(vdir)
    pages = []
    for i in range(hit_paging.page_count(meta)):
        header = prime_sieve_v1.read_prime_window_header(hit_paging.page_file(vdir, meta, i))
        pages.append((header["base_prime"], header["count"]))
    total = 0
    for i, (first, count) in enumerate(pages):
        if stop_event is not None and stop_event.is_set():
            break
        if count == 0 or first is None:
            continue
        end = pages[i + 1][0] if i + 1 < len(pages) else meta["last_value"] + 1
        if _inside_one(first, end, intervals):
            total += count
        elif not _disjoint(first, end, intervals):
            total += _count_sorted(
                hit_paging.read_page(vdir, base_exponent, k, variant_id, i), intervals)
    return total


def _row(base_exponent, k, variant_id, width, hits, expected):
    ratio, sigma = compare(hits, expected)
    return {"base_exponent": base_exponent, "k": k, "variant_id": variant_id,
            "width": width, "hits": hits, "expected": expected, "ratio": ratio,
            "sigma": sigma}


def floor_rows(portal, base_exponent, k, intervals, stop_event=None):
    """One row per catalog variant of k, plus a sum row (variant_id None) when k has more
    than one variant. Every row carries the floor's covered width."""
    width = sum(b - a for a, b in intervals)
    rows = []
    for pattern in pattern_catalog_v1.patterns_for_k(k):
        hits = count_hits_in(portal, base_exponent, k, pattern["id"], intervals, stop_event)
        expected = expected_count(pattern["offsets"], intervals)
        rows.append(_row(base_exponent, k, pattern["id"], width, hits, expected))
    if len(rows) > 1:
        rows.append(_row(base_exponent, k, None, width, sum(r["hits"] for r in rows),
                         sum(r["expected"] for r in rows)))
    return rows


def scan_density(portal, k, floor_min=None, floor_max=None, stop_event=None,
                 report_progress=None):
    """(rows, notes, stopped) over the floors in [floor_min, floor_max] with scan progress.
    notes: [(base_exponent, info)] for every floor visited, info as covered_intervals()
    returns it. report_progress((floors done, floors total)) after each floor."""
    floors = [f for f in list_floors(portal)
              if (floor_min is None or f >= floor_min) and (floor_max is None or f <= floor_max)]
    def stopped():
        return stop_event is not None and stop_event.is_set()

    rows, notes = [], []
    for i, floor in enumerate(floors):
        intervals, info = covered_intervals(portal, floor, stop_event)
        found = floor_rows(portal, floor, k, intervals, stop_event) if intervals else []
        if stopped():
            # A floor cut off midway would show partial counts; it is left out whole.
            return rows, notes, True
        notes.append((floor, info))
        rows.extend(found)
        if report_progress is not None:
            report_progress((i + 1, len(floors)))
    return rows, notes, False
