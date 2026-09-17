"""
constellations.py -- pure-logic backend for constellation (k-tuple) hit storage:
locating/reading HITS_*.bin files, grouping them for the tree UI, building the
pzktupel.de-style records table + its full-detail export rows, rendering that table
to PDF, and checking whether a searched number participates in any recorded hit.

Split out of prime_atlas_v1.py alongside the Constellations tab's own UI split into
primeatlas/constellations/constellations_hits_tab.py / constellations_calc_tab.py /
constellations_records_tab.py -- these functions have no tkinter dependency and are
exercisable without a display, same reasoning as primeatlas/core/storage.py's own split for
the Prime numbers tab. Only find_constellation_participation is still called from
prime_atlas_v1.py itself (the shared search worker's _search_job, off the GUI thread),
so it and everything it depends on (list_constellation_hits/hit_file_path) are imported
back at that file's top; the records-table builders/PDF renderer are used exclusively
by primeatlas/constellations/constellations_records_tab.py.
"""
import csv
import datetime
import os

import pattern_catalog_v1
import prime_sieve_v1
import hit_paging

from ..core.storage import list_floors
from ..core.pdf_writer import _pdf_ascii_fold, _pdf_rect_op, _pdf_text_op, _write_pdf
from ..core.i18n import Translator, DEFAULT_LANGUAGE


def hit_file_path(portal_folder, base_exponent, k, variant_id):
    """Same layout as constellation_finder_v1.hit_file_path() -- not imported from there
    directly (a browsing tool depending on the heavy analysis script felt backwards); this
    is deliberately kept in sync with that function instead."""
    return os.path.join(
        portal_folder, f"10p{base_exponent}", "constellations", f"k{k}", f"variant{variant_id}",
        f"HITS_10p{base_exponent}_k{k}_v{variant_id}.bin")


def floor_has_constellation_hits(portal_folder, base_exponent):
    """Cheap existence check -- does floor `base_exponent` have AT LEAST ONE constellation
    hit file on disk, without reading the pattern catalog or any file header (unlike
    list_constellation_hits() below, which is only called once a floor's tree node is
    actually expanded). Used by reload_constellations_tree() to decide which floors to
    list AT ALL -- a floor can have plenty of prime data but zero constellation hits (the
    finder hasn't been run against it yet, or ran and found nothing), and listing it
    anyway with an empty "no hits" placeholder just clutters the tree with entries there is
    nothing to actually browse. Short-circuits on the first hit file found rather than
    counting every one, same reasoning find_highest_populated_floor() short-circuits
    on the first (highest) populated floor."""
    const_dir = os.path.join(portal_folder, f"10p{base_exponent}", "constellations")
    if not os.path.isdir(const_dir):
        return False
    for k_name in os.listdir(const_dir):
        k_path = os.path.join(const_dir, k_name)
        if not os.path.isdir(k_path):
            continue
        for variant_name in os.listdir(k_path):
            variant_path = os.path.join(k_path, variant_name)
            if not os.path.isdir(variant_path):
                continue
            for fname in os.listdir(variant_path):
                if fname.startswith("HITS_") and fname.endswith(".bin"):
                    return True
    return False


def _header_from_paging_meta(meta):
    """Builds a read_prime_window_header()-shaped dict out of a hit_paging.py metadata
    dict, so every caller that already knows how to consume a header (count/base_prime)
    keeps working unchanged whether a pattern is paged or not -- see hit_paging.py's own
    module docstring for why a paged pattern's original single file stops existing
    (renamed to "*.pre_page_migration.bak" by migrate_hit_file_to_pages()), so
    read_prime_window_header() itself can no longer be called on it directly.
    generated_at/generated_at_iso have no paging equivalent (PAGES_META.json doesn't
    track it -- see hit_paging.py's own field list) -- left as None/"" rather than
    guessing at a page file's own timestamp, which would mean something different (last
    page write time, not the pattern's original creation time)."""
    return {
        "base_prime": meta["first_value"],
        "count": meta["total_count"],
        "generated_at": None,
        "generated_at_iso": "",
    }


def read_hit_pattern_header(portal_folder, base_exponent, k, variant_id):
    """Paging-transparent replacement for a bare `os.path.exists(path) and
    read_prime_window_header(path)`: tries the single-file path first (the common
    case -- most patterns never grow large enough to be paged, see hit_paging.py's own
    "dual-mode by design" docstring), falls back to this pattern's PAGES_META.json if
    it's been migrated. Returns None if neither exists (no hits recorded for this
    pattern on this floor at all)."""
    path = hit_file_path(portal_folder, base_exponent, k, variant_id)
    if os.path.exists(path):
        try:
            return prime_sieve_v1.read_prime_window_header(path)
        except Exception:
            return None
    vdir = hit_paging.variant_dir(portal_folder, base_exponent, k, variant_id)
    if hit_paging.is_paged(vdir):
        return _header_from_paging_meta(hit_paging.read_meta(vdir))
    return None


def hit_pattern_page_count(portal_folder, base_exponent, k, variant_id):
    """How many browsing "pages" this pattern has -- an unpaged pattern is always
    exactly 1 "page" (its whole file, read in one shot, same as before this whole
    paging mechanism existed) so every caller can loop `for i in range(page_count):
    read_hit_pattern_page(..., i)` uniformly regardless of whether the pattern has
    actually been migrated. Returns 0 if the pattern has no hit file at all (nothing to
    page through)."""
    path = hit_file_path(portal_folder, base_exponent, k, variant_id)
    if os.path.exists(path):
        return 1
    vdir = hit_paging.variant_dir(portal_folder, base_exponent, k, variant_id)
    if hit_paging.is_paged(vdir):
        return hit_paging.page_count(hit_paging.read_meta(vdir))
    return 0


def hit_pattern_is_paged(portal_folder, base_exponent, k, variant_id):
    """True once this pattern has been migrated to pages (hit_paging.py) -- the ONE
    check a GUI-thread caller needs BEFORE attempting an interactive read, to decide
    whether read_hit_pattern_page() page 0 is safe (bounded to hit_paging.PAGE_SIZE) or
    would still be a full, unbounded decode of the ORIGINAL single file (true for any
    pattern that hasn't been migrated yet, no matter how large it's grown -- see
    read_hit_pattern_page()'s own docstring: for an unpaged pattern page 0 IS the whole
    file). A caller about to read on the GUI thread specifically (not a background
    worker) should also check the pattern's header count against hit_paging.PAGE_SIZE
    when this returns False, and refuse rather than attempt the read -- see
    constellations_records_tab.py's _on_cell_activate() and
    constellations_hits_tab.py's load_preview() for that guard: without it, k=2 on
    floor 25 (~2.15 billion hits, not yet migrated) hangs the whole app's GUI thread
    decoding on a plain double-click."""
    vdir = hit_paging.variant_dir(portal_folder, base_exponent, k, variant_id)
    return hit_paging.is_paged(vdir)


def read_hit_pattern_page(portal_folder, base_exponent, k, variant_id, page_index):
    """Returns the decoded values for browsing page `page_index` (see
    hit_pattern_page_count() above for the page count to iterate up to) -- for an
    unpaged pattern this is the WHOLE file (page_index must be 0, same one-shot
    read_prime_window() cost this whole browsing path always had for a small/medium
    pattern), for a paged one it's exactly that hit_paging page, bounded to
    hit_paging.PAGE_SIZE entries regardless of the pattern's total_count. This is the
    ONE place the records tab drill-down, its PDF/CSV export, and the Magazyn tab's own
    preview loader should all read hit values through, instead of calling
    prime_sieve_v1.read_prime_window() on hit_file_path() directly (which silently
    breaks -- FileNotFoundError -- the instant a pattern is migrated to pages, and
    which is exactly the unbounded full-file decode that made a dense k=2 floor freeze
    the GUI thread or OOM-crash a background worker in the first place)."""
    path = hit_file_path(portal_folder, base_exponent, k, variant_id)
    if os.path.exists(path):
        if page_index != 0:
            raise IndexError(f"unpaged pattern has only page 0, got page_index={page_index}")
        return prime_sieve_v1.read_prime_window(path)
    vdir = hit_paging.variant_dir(portal_folder, base_exponent, k, variant_id)
    return hit_paging.read_page(vdir, base_exponent, k, variant_id, page_index)


def list_constellation_hits(portal_folder, base_exponent):
    """Returns [(pattern_dict, path, header_or_None), ...] for every catalog pattern that
    has an existing hit file for this floor (i.e. constellation_finder_v1 has found at
    least one match), sorted by (k, id). `path` still points at the (possibly no-longer-
    existing, once migrated -- see hit_paging.py) single-file location: callers display
    it as a label/tooltip and pass it to hit_file_path()-shaped code elsewhere, but
    should read actual VALUES via read_hit_pattern_page() instead of this path
    directly."""
    entries = []
    for pattern in sorted(pattern_catalog_v1.PATTERN_CATALOG, key=lambda w: (w["k"], w["id"])):
        path = hit_file_path(portal_folder, base_exponent, pattern["k"], pattern["id"])
        header = read_hit_pattern_header(portal_folder, base_exponent, pattern["k"], pattern["id"])
        if header is None:
            continue
        entries.append((pattern, path, header))
    return entries


def group_constellation_hits_by_k(entries):
    """Groups list_constellation_hits()'s flat (pattern, path, header) list into
    [(k, k_total, [(pattern, path, header), ...]), ...] sorted ascending by k -- fills in
    the "how many k-tuples do I have in total for this k" figure that the tree's per-variant
    hit counts alone don't show (e.g. k=7 v=1: 136, k=7 v=2: 131, but never their sum).
    Cheap by construction -- the pattern catalog itself is
    small (currently 48 entries across all k), so list_constellation_hits() already reads
    every existing hit file's header for a floor in one shot; this just re-groups that
    already-fetched data, no extra I/O. Rows with header=None (corrupt/unreadable hit file)
    count as 0 toward k_total rather than breaking the sum."""
    groups = {}
    for pattern, path, header in entries:
        k = pattern["k"]
        groups.setdefault(k, []).append((pattern, path, header))
    result = []
    for k in sorted(groups):
        variants = groups[k]
        k_total = sum(header["count"] for _pattern, _path, header in variants if header is not None)
        result.append((k, k_total, variants))
    return result


def build_constellation_records_table(portal_folder, k, floor_min=None, floor_max=None):
    """Scans the user's OWN storage (constellations/k{k}/variant{id}/HITS_....bin -- NOT
    pzktupel.de) for every floor that has at least one hit file for pattern `k`, building
    a pzktupel.de-style exp x variant table: for each floor and each of k's catalog
    variants, the SMALLEST offset above that floor's own 10**base_exponent found among
    this project's own hits so far (hit files store sorted ascending starting values --
    see constellation_finder_v1.py's own module header -- so the smallest is simply the
    first stored value, no need to read/compare the whole file by hand).

    `floor_min`/`floor_max` (both optional, inclusive): scope the scan to a specific
    piętro/floor range instead of every floor in storage. Added because a project with
    many populated floors makes the unscoped table both slow to build and noisy to read
    (mostly "-" cells for floors the user isn't currently interested in) -- passing
    bounds lets the caller match the curated exp range pzktupel.de's own reference
    tables show (e.g. only exp 10..19) instead of dumping the whole storage. None means
    unbounded on that side, matching the pre-existing (pre-filter) behaviour when both
    are omitted.

    `is_record_floor` flags a cell whose floor happens to equal the pzktupel.de catalog's
    own record_digits - 1 (a D-digit record lives in floor D-1, since floor N holds
    [10**N, 10**(N+1))) -- this is a same-floor COINCIDENCE flag, not a verified match:
    the catalog only stores the record holder's digit count, not its exact offset, so
    there's no way to confirm this project's own find is the SAME number as the cited
    record without that offset. Still useful context (a hit on that exact floor is
    exactly where pzktupel.de's own record-holder would live), so it's surfaced as
    `pattern_meta[vid]` (discoverer/date/record_digits) for the caller to display
    alongside the flag rather than making a claim this function can't back up.

    Returns (variant_ids, variant_meta, rows):
      variant_ids: this k's catalog ids in order (column order for a table/tree/export)
      variant_meta: {id: pattern_dict} (offsets/record_digits/discoverer/date)
      rows: [{"base_exponent": int, "cells": {id: cell_or_None}}, ...] sorted ascending
            by base_exponent, one row per floor (within [floor_min, floor_max] when
            given) that has AT LEAST ONE hit for this k (floors with zero hits for k,
            even if they have hits for some OTHER k, are skipped -- nothing to show).
            cell_or_None is None when this floor has no hit file for that particular
            variant, else {"offset": int, "count": int, "is_record_floor": bool}.

    Pure function (no tkinter), reusing list_floors()/floor_has_constellation_hits()/
    hit_file_path() exactly as reload_constellations_tree() already does, so this is
    consistent with (and no more expensive than) the existing storage browser -- the one
    added cost is prime_sieve_v1.read_prime_window_header() per (floor, variant) that
    actually has a hit file, a fixed-size (~264 byte) header read that returns both
    base_prime (the smallest stored value -- hit files are sorted ascending, see
    constellation_finder_v1.py's own module header) and count directly, without decoding
    the gap-encoded body. Previously this called read_prime_window() (full decode) just
    to read values[0] and len(values) -- for k2 on floor 25's 2.9GB/~1.5 billion-entry
    hit file that meant decoding the entire file to read two numbers already available
    in the header; see list_constellation_hits() above, which already used the header
    form for the same reason."""
    variants = pattern_catalog_v1.patterns_for_k(k)
    variant_ids = [w["id"] for w in variants]
    variant_meta = {w["id"]: w for w in variants}
    rows = []
    for base_exponent in list_floors(portal_folder):
        if floor_min is not None and base_exponent < floor_min:
            continue
        if floor_max is not None and base_exponent > floor_max:
            continue
        if not floor_has_constellation_hits(portal_folder, base_exponent):
            continue
        cells = {}
        any_hit = False
        for vid in variant_ids:
            cell = None
            header = read_hit_pattern_header(portal_folder, base_exponent, k, vid)
            if header is not None and header["count"] > 0:
                smallest = header["base_prime"]
                offset = smallest - 10 ** base_exponent
                record_digits = variant_meta[vid]["record_digits"]
                is_record_floor = (record_digits is not None
                                    and base_exponent == record_digits - 1)
                cell = {"offset": offset, "count": header["count"],
                        "is_record_floor": is_record_floor}
                any_hit = True
            cells[vid] = cell
        if any_hit:
            rows.append({"base_exponent": base_exponent, "cells": cells})
    return variant_ids, variant_meta, rows


def count_constellation_records_detail_rows(portal_folder, k, floor_min=None, floor_max=None):
    """Cheap O(1)-per-pattern total of how many rows
    build_constellation_records_detail_rows()/iter_constellation_records_detail_rows()
    would produce for this k/floor range -- sums read_hit_pattern_header()'s own
    `count` per (floor, variant), never touching a single hit VALUE. Added so the
    records tab's PDF export (which, unlike CSV, needs every row laid out on paginated
    pages up front -- see render_constellation_records_pdf()) can refuse a range whose
    row count would make an absurd (or outright OOM-risking) PDF, e.g. floor 25's k=2
    alone: ~2.16 billion rows, an obviously unusable multi-hundred-million-page PDF
    even setting memory aside -- BEFORE attempting to build it, rather than after
    already having decoded everything."""
    variants = pattern_catalog_v1.patterns_for_k(k)
    variant_ids = [w["id"] for w in variants]
    total = 0
    for base_exponent in list_floors(portal_folder):
        if floor_min is not None and base_exponent < floor_min:
            continue
        if floor_max is not None and base_exponent > floor_max:
            continue
        if not floor_has_constellation_hits(portal_folder, base_exponent):
            continue
        for vid in variant_ids:
            header = read_hit_pattern_header(portal_folder, base_exponent, k, vid)
            if header is not None:
                total += header["count"]
    return total


def iter_constellation_records_detail_rows(portal_folder, k, floor_min=None, floor_max=None):
    """Streaming sibling of build_constellation_records_detail_rows() below: yields the
    same per-hit row dicts ONE AT A TIME instead of collecting them into one big list
    first. Added because build_constellation_records_detail_rows() already reads hit
    VALUES through paging-transparent, per-page-bounded reads (see
    read_hit_pattern_page()'s own docstring) -- but it still accumulates every row dict
    into one Python list before returning, which for a pattern the scale of floor 25's
    k=2 (~2.16 billion hits) would try to hold billions of dicts in memory at once, an
    OOM risk on a completely different axis than the per-page DECODE cost that function
    already addresses. CSV export (see constellations_records_tab.py's _write_detail_csv)
    is the one consumer large-scale enough for this to matter -- it iterates this
    directly and writes each row as it arrives, never holding more than one hit-file
    page's worth of rows in memory at once. Same row shape/ordering as
    build_constellation_records_detail_rows() -- see its own docstring."""
    variants = pattern_catalog_v1.patterns_for_k(k)
    variant_ids = [w["id"] for w in variants]
    variant_meta = {w["id"]: w for w in variants}
    for base_exponent in list_floors(portal_folder):
        if floor_min is not None and base_exponent < floor_min:
            continue
        if floor_max is not None and base_exponent > floor_max:
            continue
        if not floor_has_constellation_hits(portal_folder, base_exponent):
            continue
        base = 10 ** base_exponent
        for vid in variant_ids:
            header = read_hit_pattern_header(portal_folder, base_exponent, k, vid)
            if header is None:
                continue
            total_count = header["count"]
            record_digits = variant_meta[vid]["record_digits"]
            is_record_floor = (record_digits is not None
                                and base_exponent == record_digits - 1)
            position = 0
            for page_index in range(hit_pattern_page_count(portal_folder, base_exponent, k, vid)):
                try:
                    values = read_hit_pattern_page(portal_folder, base_exponent, k, vid, page_index)
                except Exception:
                    values = []
                for value in values:
                    yield {
                        "base_exponent": base_exponent, "variant_id": vid,
                        "offset": value - base, "number": value,
                        "position_in_file": position, "count_in_file": total_count,
                        "is_record_floor": is_record_floor,
                    }
                    position += 1


def hit_pattern_actual_page_size(portal_folder, base_exponent, k, variant_id):
    """Returns the real page_size a paged pattern was migrated with (from its own
    PAGES_META.json), or hit_paging.PAGE_SIZE as a harmless default for an unpaged
    pattern -- an unpaged pattern's only "page" is index 0, so whatever multiplier
    this feeds into (position_in_file math) never actually matters there. Reads the
    pattern's own metadata rather than assuming hit_paging.PAGE_SIZE applies to every
    pattern (that's only the default for NEWLY migrated ones, not necessarily what an
    already-migrated pattern was actually written with)."""
    vdir = hit_paging.variant_dir(portal_folder, base_exponent, k, variant_id)
    pattern_meta = hit_paging.read_meta(vdir)
    return pattern_meta["page_size"] if pattern_meta is not None else hit_paging.PAGE_SIZE


def write_constellation_detail_rows_csv(path, rows):
    """Writes per-hit detail rows (the shape iter_constellation_records_detail_rows()
    yields, or an equivalent plain list of the same dicts) to a CSV file at `path`,
    iterating `rows` exactly once and writing each one as it arrives -- safe to hand
    either a plain list or a generator, and never holds more than the current row in
    memory regardless of how many there are. Shared by every CSV export path in
    ConstellationsRecordsTab (whole-range and on-screen-page-scoped alike) so the
    column set/order lives in exactly one place instead of being duplicated per
    caller."""
    fieldnames = ["exp", "variant_id", "offset", "number",
                  "position_in_file", "count_in_file", "is_record_floor"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "exp": f"10p{r['base_exponent']}",
                "variant_id": r["variant_id"],
                "offset": r["offset"],
                "number": r["number"],
                "position_in_file": r["position_in_file"],
                "count_in_file": r["count_in_file"],
                "is_record_floor": r["is_record_floor"],
            })


def build_constellation_records_detail_rows(portal_folder, k, floor_min=None, floor_max=None):
    """Full-detail companion to build_constellation_records_table(): instead of just the
    smallest offset per (floor, variant) cell, returns ONE row per individual hit --
    every tuple-start value found in every hit file for `k` within the given floor
    range, not only the record-setting smallest one. Same floor_min/floor_max
    semantics (inclusive, None = unbounded) as build_constellation_records_table().

    Added for the PDF/CSV export buttons specifically (user request: the exported
    file should contain every hit this project has found for the currently displayed
    floor range, not just the compact one-cell-per-floor summary) -- the on-screen
    tree keeps showing the compact view (see build_constellation_records_table()'s own
    docstring for why that's the right shape for browsing), and the records tab's own
    cell drill-down gives the same full list on-demand for a single cell inside the
    GUI itself without needing an export.

    Just materializes iter_constellation_records_detail_rows() (see its own docstring
    for why that exists as a separate generator) into a list -- kept as a thin wrapper
    since the on-screen "how many rows would this be" checks and PDF export (which
    needs the whole laid-out list, unlike streamed CSV) still want a plain list.
    Large-scale callers (CSV export) should use the generator directly instead; see
    count_constellation_records_detail_rows() for a PDF-sized guard BEFORE calling this
    at all for a range that would be excessive either way.

    Returns (variant_ids, variant_meta, rows):
      rows: [{"base_exponent": int, "variant_id": int, "offset": int, "number": int,
              "position_in_file": int, "count_in_file": int, "is_record_floor": bool},
             ...] sorted by (base_exponent, variant_id, offset) ascending -- offset
      ascending is automatic since hit files store values sorted ascending (see
      constellation_finder_v1.py's own module header) and offset = number - floor's
      10**base_exponent preserves that ordering."""
    variants = pattern_catalog_v1.patterns_for_k(k)
    variant_ids = [w["id"] for w in variants]
    variant_meta = {w["id"]: w for w in variants}
    rows = list(iter_constellation_records_detail_rows(
        portal_folder, k, floor_min=floor_min, floor_max=floor_max))
    return variant_ids, variant_meta, rows


def render_constellation_records_pdf(path, k, fieldnames, rows, translator=None):
    """Writes a standalone PDF report of one k's records table (see
    build_constellation_records_table()) to `path` -- same low-level PDF-writing
    machinery (_write_pdf/_pdf_text_op/_pdf_rect_op, cell-truncation table layout) as
    render_benchmark_pdf(), just without a chart (this table has no time-series data to
    plot) and with a dynamic column count (1 + however many catalog variants k has,
    instead of a fixed benchmark_log.csv column set). `fieldnames`/`rows` are plain
    dicts, same shape render_benchmark_pdf() takes, built by the records tab from the
    last computed records table -- pure function (no tkinter), exercisable directly
    without a display.

    translator (optional): a primeatlas.core.i18n.Translator instance, for the title/subtitle/
    continuation-page chrome -- defaults to DEFAULT_LANGUAGE if not given, same as
    render_benchmark_pdf()."""
    t = (translator or Translator(DEFAULT_LANGUAGE)).t
    page_w, page_h = 841.89, 595.28  # A4 landscape, points -- same as render_benchmark_pdf
    margin = 30
    content_left = margin
    content_width = page_w - 2 * margin
    content_top = page_h - margin
    content_bottom = margin

    font_size = 8
    row_h = 14
    header_h = 16
    n_cols = max(1, len(fieldnames))
    col_w = content_width / n_cols
    max_chars = max(3, int(col_w / (0.6 * font_size)))

    def cell_text(value):
        s = "" if value is None else str(value)
        if len(s) > max_chars:
            s = s[:max(0, max_chars - 3)] + "..."
        return s

    def draw_table_header(ops, y_top):
        ops.append(_pdf_rect_op(content_left, y_top - header_h, content_width, header_h,
                                 fill_rgb=(0.90, 0.90, 0.90)))
        for i, name in enumerate(fieldnames):
            ops.append(_pdf_text_op(content_left + i * col_w + 2, y_top - header_h + 4,
                                     font_size, "Helvetica-Bold", cell_text(name)))
        return y_top - header_h

    def draw_table_rows(ops, y_top, row_slice):
        y = y_top
        for row in row_slice:
            for i, name in enumerate(fieldnames):
                ops.append(_pdf_text_op(content_left + i * col_w + 2, y - row_h + 4,
                                         font_size, "Courier", cell_text(row.get(name, ""))))
            y -= row_h
        return y

    pages = []
    ops = []
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ops.append(_pdf_text_op(content_left, content_top - 14, 14, "Helvetica-Bold",
                             _pdf_ascii_fold(t("const_records.pdf_title", k=k))))
    ops.append(_pdf_text_op(content_left, content_top - 30, 9, "Helvetica",
                             _pdf_ascii_fold(t("const_records.pdf_subtitle", now=now_str,
                                               rows=len(rows)))))
    table_top = content_top - 46
    y_after_header = draw_table_header(ops, table_top)
    available = y_after_header - content_bottom
    rows_fit = max(0, int(available // row_h))
    draw_table_rows(ops, y_after_header, rows[:rows_fit])
    pages.append(ops)

    remaining = rows[rows_fit:]
    page_num = 2
    while remaining:
        ops = []
        ops.append(_pdf_text_op(content_left, content_top - 12, 10, "Helvetica-Bold",
                                 _pdf_ascii_fold(t("const_records.pdf_continued", page=page_num))))
        table_top = content_top - 22
        y_after_header = draw_table_header(ops, table_top)
        available = y_after_header - content_bottom
        rows_fit = max(1, int(available // row_h))
        chunk = remaining[:rows_fit]
        draw_table_rows(ops, y_after_header, chunk)
        pages.append(ops)
        remaining = remaining[len(chunk):]
        page_num += 1

    _write_pdf(path, pages, page_size=(page_w, page_h))


def find_constellation_participation(portal_folder, base_exponent, number, hit_set_cache=None,
                                      progress_callback=None):
    """For every catalog pattern with an existing hit file at this floor, checks whether
    `number` participates in any recorded hit -- either as the BASE (offset +0) or as any
    other fixed-offset member (base = number - offset). A number can legitimately show up
    in more than one pattern at once (e.g. any k=4 hit's base is also, by construction, a
    k=3 and k=2 hit's base -- sub-tuples of a longer pattern), so this returns every match,
    not just the first.

    `hit_set_cache`, if given, is a dict keyed by (base_exponent, k, id) -> set of decoded
    starting values; reused across repeated searches in the same session so each hit file
    is only decoded once rather than on every search. Owned by the Constellations tab's
    Magazyn widget (ConstellationsHitsTab.hit_set_cache) -- passed in explicitly by
    prime_atlas_v1.py's own _search_job rather than kept as module state here, so this
    function stays pure and reusable regardless of which tab (or a future test) calls it.

    `progress_callback(done, total)`, if given, is called once per pattern AFTER it's been
    processed (whether that meant a fresh, potentially slow prime_sieve_v1.read_prime_window()
    decode or a cache hit) -- a floor's FIRST-ever constellation search can decode dozens
    of full hit files synchronously (nothing cached yet), which is the actual slow part of
    this feature (find_prime_in_floor's own binary search is fast in comparison). The GUI
    thread never calls this directly; prime_atlas_v1's _search_job does, off the main
    thread (via a PersistentWorker, see primeatlas/core/background.py), and turns each
    progress_callback invocation into a report_progress() call that drives the shared
    status/progress bar.

    Returns a list of dicts: {pattern, offset, position, base} (position is 0-indexed --
    0 means "this IS the base of the tuple").
    """
    if hit_set_cache is None:
        hit_set_cache = {}
    entries = list_constellation_hits(portal_folder, base_exponent)
    total = len(entries)
    results = []
    for done, (pattern, path, header) in enumerate(entries, start=1):
        if header is None or header.get("count", 0) == 0:
            if progress_callback is not None:
                progress_callback(done, total)
            continue
        key = (base_exponent, pattern["k"], pattern["id"])
        if key not in hit_set_cache:
            try:
                values = set()
                for page_index in range(hit_pattern_page_count(
                        portal_folder, base_exponent, pattern["k"], pattern["id"])):
                    values.update(read_hit_pattern_page(
                        portal_folder, base_exponent, pattern["k"], pattern["id"], page_index))
                hit_set_cache[key] = values
            except Exception:
                hit_set_cache[key] = set()
        starts = hit_set_cache[key]
        for position, offset in enumerate(pattern["offsets"]):
            base = number - offset
            if base in starts:
                results.append({"pattern": pattern, "offset": offset, "position": position, "base": base})
        if progress_callback is not None:
            progress_callback(done, total)
    return results
