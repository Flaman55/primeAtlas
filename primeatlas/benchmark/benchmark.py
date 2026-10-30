"""
benchmark.py -- pure-logic backend for the Benchmark tab: reading/normalizing
benchmark_log.csv, reducing its rows into chart series and per-floor stats, and
rendering the standalone PDF report. No tkinter dependency -- exercisable/unit-tested
without a display, same convention as every other module in this package except
settings_tab.py/benchmark_tab.py (see this package's __init__.py's docstring).

primeatlas/benchmark/benchmark_tab.py (the UI half, built on top of this module) is the ONLY
caller of everything below except read_benchmark_log(), which
prime_atlas_v2.py's own reload_primes_tree()/_primes_tree_scan() also calls directly
(for the "Prime numbers" tab's own generation-time column) -- see that function's own
docstring.

The low-level PDF-writing primitives (_pdf_text_op/_pdf_line_op/_pdf_rect_op/
_pdf_dot_op/_write_pdf/_pdf_ascii_fold) live in primeatlas/core/pdf_writer.py instead of
here -- they're shared with render_constellation_records_pdf (still in
prime_atlas_v2.py, the Constellations tab's own PDF export), so neither renderer
"owns" them; see that module's own docstring.

QUICK_GEN_MAX_WINDOW_WIDTH below is a deliberately DUPLICATED constant, not imported
from prime_atlas_v2.py -- same precedent as that file's own LOW_FLOOR_CUTOFF comment
("duplicated rather than imported"): importing it back from prime_atlas_v2.py would be
circular (that file imports BenchmarkTab, which imports this module), and it's a
single stable literal (the fixed window width every generation engine in this project
uses), not logic that could drift out of sync in a way worth the import wiring.
"""
import csv
import datetime
import math
import os
import re

from ..core.i18n import Translator, DEFAULT_LANGUAGE
from ..core.pdf_writer import _pdf_ascii_fold, _pdf_rect_op, _pdf_text_op, _write_pdf
from .chart_pdf import chart_ops
from .chart_series import engine_lines, engine_series
from .reference_points import REFERENCES, reference_series

QUICK_GEN_MAX_WINDOW_WIDTH = 10_000_000  # see this module's own docstring for why this
                                          # is a duplicate, not an import, of
                                          # prime_atlas_v2.py's own constant of the
                                          # same name.

BENCHMARK_TREE_HIDDEN_COLUMNS = {"base_exponent", "run_timestamp_utc"}  # columns dropped
                                # from the Benchmark tab's tree (not from the CSV, PDF
                                # export, or growth chart -- those still use every column).
                                # base_exponent is redundant once rows are grouped under a
                                # "10p{N}" floor node (every row repeats the same value).
                                # run_timestamp_utc is dropped as a COLUMN but not lost --
                                # it moves into the #0 "Floor / run" tree label for
                                # individual rows instead (that column sits empty for data
                                # -- see _order_benchmark_tree_columns() below for the one
                                # column whose DISPLAY position also gets adjusted
                                # rows otherwise, see BenchmarkTab._show_benchmark_page),
                                # freeing a whole column's width for the other fields that
                                # don't fit on screen at once.

BENCHMARK_PAGE_SIZE = 200  # benchmark_log.csv rows shown per page when a floor node is
                            # expanded in the Benchmark tab's tree -- same reasoning as
                            # FLOOR_PAGE_SIZE in prime_atlas_v2.py. benchmark_log.csv now
                            # gets a row per orchestrator run (including count-only/
                            # no-write benchmarking runs, which are cheap to run
                            # repeatedly), so it grows much faster than one row per floor
                            # -- inserting every row as a flat Treeview row on load is
                            # what would freeze this tab the same way the old
                            # un-paginated primes tree used to.


def _order_benchmark_tree_columns(fieldnames):
    """Reorders the Benchmark tab's visible tree columns so loop_seconds_per_window sits
    immediately after seconds_per_window, instead of trailing at the end where it
    physically lives in benchmark_log.csv. Only the DISPLAY order changes here -- the
    CSV's own column order (and BENCHMARK_FIELDNAMES in orchestrator_v3.py etc.) is
    untouched, still append-only per the established schema-migration pattern. A no-op if
    either column is missing (older schema / already filtered out), so this is safe to
    call unconditionally."""
    fieldnames = list(fieldnames)
    if "engine" in fieldnames:
        fieldnames.remove("engine")
        fieldnames.insert(0, "engine")
    if "loop_seconds_per_window" not in fieldnames or "seconds_per_window" not in fieldnames:
        return fieldnames
    fieldnames.remove("loop_seconds_per_window")
    insert_at = fieldnames.index("seconds_per_window") + 1
    fieldnames.insert(insert_at, "loop_seconds_per_window")
    return fieldnames


_DECIMAL_COMMA_RE = re.compile(r'^-?\d+,\d+$')


def _normalize_decimal_commas(row):
    """Fixes numeric fields that got re-written with a comma decimal separator (e.g.
    "236228657,66" instead of "236228657.66") -- happens if benchmark_log.csv is ever opened
    and re-saved in a spreadsheet app under a locale that uses comma-as-decimal (e.g.
    deleting rows in Excel under a Polish locale re-exports every numeric field this way,
    silently breaking the growth chart -- aggregate_benchmark_growth()/
    aggregate_benchmark_fair_spw()/benchmark_row_stats() all call float() on these columns,
    which raises ValueError on a comma decimal and gets caught+skipped, so the chart just
    quietly lost almost every point). Only touches values matching digits-comma-digits
    exactly (e.g. "1/1" in instance_of_n, or a plain int like "1000", are left alone).
    Mutates and
    returns `row` in place."""
    for k, v in row.items():
        if v and _DECIMAL_COMMA_RE.match(v):
            row[k] = v.replace(",", ".")
    return row


def read_benchmark_log(portal_folder):
    """Returns (fieldnames, rows) from CONSTELLATION_PORTAL/benchmark_log.csv, or
    ([], []) if the file doesn't exist yet (no benchmarked runs so far). Numeric fields are
    normalized to a period decimal separator on read (see _normalize_decimal_commas()) --
    tolerates the file having been re-saved with comma decimals by a spreadsheet app,
    regardless of whether the on-disk file itself has been repaired."""
    log_path = os.path.join(portal_folder, "benchmark_log.csv")
    if not os.path.exists(log_path):
        return [], []
    with open(log_path, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = [_normalize_decimal_commas(row) for row in reader]
    if "engine" not in fieldnames:
        fieldnames.append("engine")
    for row in rows:
        row["engine"] = row.get("engine") or ("hybrid" if row.get("instance_of_n") == "hybrid" else "unknown")
        _, row["sieve_count_basis"] = benchmark_sieve_count(row)
    if "sieve_count_basis" not in fieldnames:
        fieldnames.append("sieve_count_basis")
    return fieldnames, rows


def _row_engine(row):
    return row.get("engine") or ("hybrid" if row.get("instance_of_n") == "hybrid" else "unknown")


def _metric_value(row, metric):
    try:
        value = float(row.get(metric, ""))
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else value




def aggregate_benchmark_growth(rows):
    """Reduces benchmark_log.csv rows to one (base_exponent, loop_numbers_per_second) point per
    floor, for the "cost growth by depth" chart. loop_numbers_per_second is the real
    session-level throughput (total numbers swept across all concurrent instances / real
    wall-clock time of the orchestrator_loop run -- see _tag_single_benchmark_row() /
    _tag_benchmark_rows_by_range() in orchestrator_loop_v2.py), used directly as the
    y-value -- higher is better (seconds_per_window, by contrast, gets WORSE as more
    concurrent instances are added even when wall-clock throughput improves). When a
    floor has multiple logged runs (re-benchmarked after a
    scanner change, or just run again), the LAST row for that floor wins: rows are appended
    in chronological order, so this reflects the most recent measurement instead of blending
    old and new tool versions together into one misleading average. Rows predating this
    column (blank loop_numbers_per_second) or with unparseable values are skipped rather than
    raising -- older floor depths simply won't have a point until re-benchmarked through
    orchestrator_loop. Returns a list of (base_exponent, loop_numbers_per_second) sorted
    ascending by base_exponent."""
    latest = {}
    for row in rows:
        try:
            base_exponent = int(row.get("base_exponent", ""))
            numbers_per_second = float(row.get("loop_numbers_per_second", ""))
        except (TypeError, ValueError):
            continue
        if math.isnan(numbers_per_second):
            continue
        latest[base_exponent] = numbers_per_second
    return sorted(latest.items())


def aggregate_benchmark_fair_spw(rows):
    """Same reduction as aggregate_benchmark_growth() (last row per floor wins, missing/
    unparseable values skipped), but for loop_seconds_per_window instead of
    loop_numbers_per_second -- a second growth-chart line restoring a seconds/window-shaped
    view alongside n/s, but computed FAIRLY (loop_total_seconds / total_windows across the
    whole concurrent group) instead of the old
    per-instance seconds_per_window, which punished splitting into more instances. Independent
    reduction from aggregate_benchmark_growth() -- a floor could in principle have one column
    populated and not the other (shouldn't happen for rows written after this feature, both
    get stamped together, but kept independent for the same robustness reason the two columns
    are independent in the CSV). Returns (base_exponent, loop_seconds_per_window) pairs sorted
    ascending by base_exponent."""
    latest = {}
    for row in rows:
        try:
            base_exponent = int(row.get("base_exponent", ""))
            seconds_per_window_fair = float(row.get("loop_seconds_per_window", ""))
        except (TypeError, ValueError):
            continue
        if math.isnan(seconds_per_window_fair):
            continue
        latest[base_exponent] = seconds_per_window_fair
    return sorted(latest.items())


def benchmark_sieve_count(row):
    """Return count and provenance without altering historical measurements.

    main never recorded actual range widths. Keep those rows intact, but do not
    invent computational work from storage capacity. Only measured or exactly
    recoverable counts participate in sieve throughput. Invalid counts never
    fall back to estimates.
    """
    try:
        raw = row.get("numbers_processed")
        if raw not in (None, ""):
            count = int(raw)
            return (count, "measured") if count > 0 else (None, "unavailable")
        floor = int(row.get("base_exponent", ""))
        windows = int(row.get("windows_written", ""))
        if floor < 0 or windows <= 0:
            return None, "unavailable"
        engine = row.get("engine")
        is_hybrid = engine == "hybrid" or (engine in (None, "", "unknown")
                                          and row.get("instance_of_n") == "hybrid")
        if is_hybrid:
            if floor < 7 and windows == 1 and int(row.get("target_idx_start", "")) == 0:
                return 9 * 10 ** floor, "whole_floor"
            return None, "unavailable"
        return None, "unavailable"
    except (TypeError, ValueError):
        return None, "unavailable"


def aggregate_benchmark_sieve_nps(rows):
    """Actual target integers swept / sieve phase seconds, last valid row per floor.

    Storage window sizes do not measure computational work. Legacy Hybrid rows
    for one complete low floor have an exact recoverable count (9 * 10**floor).
    Older Atlas rows lacking recoverable counts remain in the table and report,
    marked unavailable by sieve_count_basis, but have no sieve throughput point.
    """
    return _aggregate_last_per_floor(rows, _row_sieve_nps)


def _row_sieve_nps(row):
    try:
        sieve_seconds = float(row.get("sieve_seconds", ""))
    except (TypeError, ValueError):
        return None
    numbers_processed, _ = benchmark_sieve_count(row)
    if not math.isfinite(sieve_seconds) or sieve_seconds <= 0 or numbers_processed is None:
        return None
    return numbers_processed / sieve_seconds


def _row_write_mbps(row):
    try:
        bytes_written = float(row.get("bytes_written", ""))
        write_seconds = float(row.get("write_seconds", ""))
    except (TypeError, ValueError):
        return None
    if write_seconds <= 0 or math.isnan(write_seconds) or math.isnan(bytes_written):
        return None
    return bytes_written / write_seconds / 1e6


def _aggregate_last_per_floor(rows, row_value):
    latest = {}
    for row in rows:
        try:
            base_exponent = int(row.get("base_exponent", ""))
        except (TypeError, ValueError):
            continue
        value = row_value(row)
        if value is not None:
            latest[base_exponent] = value
    return sorted(latest.items())


def _row_sieve_spw(row):
    """Sieve-phase seconds per window: sieve_seconds / windows_written."""
    try:
        sieve_seconds = float(row.get("sieve_seconds", ""))
        windows = int(row.get("windows_written", ""))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(sieve_seconds) or sieve_seconds <= 0 or windows <= 0:
        return None
    return sieve_seconds / windows


_LINE_VALUES = {
    "growth": lambda row: _metric_value(row, "loop_numbers_per_second"),
    "write": _row_write_mbps,
    "sieve": _row_sieve_nps,
    "sieve_spw": _row_sieve_spw,
}


def benchmark_engine_lines(rows, metric):
    """{engine: [(base_exponent, value)]} for one chart metric ("growth", "write",
    "sieve", "sieve_spw"): the same per-row value as the matching aggregate_* reduction, but
    the last row per floor AND engine, so each engine gets its own chart line."""
    return engine_lines(rows, _LINE_VALUES[metric], _row_engine)


def aggregate_benchmark_write_mbps(rows):
    """Same reduction as aggregate_benchmark_sieve_nps() (last row per floor wins, only
    v4.1 and v5 engine rows have this data, missing/unparseable/non-positive values
    skipped), but for the disk-write phase: bytes_written / write_seconds, in MB/s -- the
    same figure orchestrator_v3.py's print_benchmark_summary() already prints inline next
    to 'write {write_seconds}s', just aggregated per floor here for the chart/PDF. Returns
    (base_exponent, write_mb_per_second) pairs sorted ascending by base_exponent."""
    return _aggregate_last_per_floor(rows, _row_write_mbps)


def group_benchmark_rows_by_floor(rows):
    """Splits benchmark_log.csv rows into {base_exponent: [rows...]}, preserving each
    floor's rows in their original (chronological, CSV-append) order. Rows with a missing
    or unparseable base_exponent are skipped -- same defensive approach as
    aggregate_benchmark_growth(). Used by the Benchmark tab to build one lazily-expandable
    tree node per floor (mirroring the "Prime numbers" tab's floor tree) instead of
    dumping every row into one flat, ever-growing table."""
    grouped = {}
    for row in rows:
        try:
            base_exponent = int(row.get("base_exponent", ""))
        except (TypeError, ValueError):
            continue
        grouped.setdefault(base_exponent, []).append(row)
    return grouped


def benchmark_row_stats(rows):
    """Reduces a floor's benchmark rows to {count, avg, min, max} of seconds_per_window --
    the "how fast is this floor, at a glance" summary shown at the top of an expanded
    floor node in the Benchmark tab, so the user doesn't have to page through potentially
    dozens of runs (including quick count-only benchmarking runs) to see the spread. Rows
    with a missing/unparseable/NaN seconds_per_window are skipped. Returns None if no row
    had a usable value (e.g. an empty or all-unparseable floor)."""
    values = []
    for row in rows:
        try:
            v = float(row.get("seconds_per_window", ""))
        except (TypeError, ValueError):
            continue
        if math.isnan(v):
            continue
        values.append(v)
    if not values:
        return None
    return {
        "count": len(values),
        "avg": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
    }


def render_benchmark_pdf(path, points, fieldnames, rows, points2=None, translator=None,
                          sieve_points=None, write_points=None, references=False,
                          log_y=False):
    """Writes a standalone PDF report -- the same growth chart(s) shown in the Benchmark tab
    plus the FULL benchmark_log.csv table (every row, every column) -- to `path`. The table
    continues onto as many additional (landscape A4) pages as needed, repeating the column
    header row on each one, since a project running for months can accumulate far more rows
    than fit on one page. Pure function (no tkinter) so it can be exercised/tested without a
    display -- the GUI layer (BenchmarkTab._export_benchmark_pdf) just gathers the same
    points/fieldnames/rows this module already computed for the on-screen chart/table and
    hands them here unchanged.

    The charts draw one line per engine from `rows` (benchmark_engine_lines()): the first
    one the whole run (sieve + write: loop n/s, with write MB/s on the right axis), the
    second one the sieve phase alone (sieve n/s, with sieve seconds per window on the right
    axis). points/points2/sieve_points/write_points are the per-floor reductions, used for
    the subtitle's floor count and to decide whether the second chart is drawn.

    references: also draw reference_points.py's series on the sieve chart -- PARI/GP and
    primesieve sieve or iterate in memory and write nothing, so they compare with the sieve
    phase -- with a footnote line per reference (full name and source) above the table.
    log_y: log10 y-axes on both charts -- the Benchmark tab's two toggles.

    sieve_points (optional): aggregate_benchmark_sieve_nps(), only populated for floors
    benchmarked with the v4.1 or v5 engine. The sieve chart takes space away from the
    table, so it is drawn only when sieve_points is non-empty or references is on.
    write_points: aggregate_benchmark_write_mbps(), kept for the callers' symmetry.

    translator (optional): a primeatlas.core.i18n.Translator instance, threaded into
    chart_ops() and used for the title/subtitle/continuation-page header below --
    defaults to DEFAULT_LANGUAGE if not given. The title/subtitle/continuation text and
    axis labels are all translator-driven so the report is consistently in one language,
    matching whatever the app's language setting actually is, rather than mixing
    languages across different pieces of chrome. Table column headers (`fieldnames`) are
    deliberately left alone -- they're the raw benchmark_log.csv
    column names, same untranslated technical identifiers already shown as-is in the
    on-screen Benchmark tab's own Treeview (see BenchmarkTab.benchmark_tree.heading(col,
    text=col)), not app-owned UI vocabulary."""
    t = (translator or Translator(DEFAULT_LANGUAGE)).t
    page_w, page_h = 841.89, 595.28  # A4 landscape, points
    margin = 30
    content_left = margin
    content_width = page_w - 2 * margin
    content_top = page_h - margin
    content_bottom = margin

    font_size = 6.5
    row_h = 12
    header_h = 14
    n_cols = max(1, len(fieldnames))
    col_w = content_width / n_cols
    max_chars = max(3, int(col_w / (0.6 * font_size)))  # ~0.6*size = Courier's fixed
                                                          # advance width per character

    def cell_text(value):
        s = "" if value is None else str(value)
        if len(s) > max_chars:
            s = s[:max(0, max_chars - 3)] + "..."
        return s

    def draw_table_header(ops, y_top):
        ops.append(_pdf_rect_op(content_left, y_top - header_h, content_width, header_h,
                                 fill_rgb=(0.90, 0.90, 0.90)))
        for i, name in enumerate(fieldnames):
            ops.append(_pdf_text_op(content_left + i * col_w + 2, y_top - header_h + 3,
                                     font_size, "Helvetica-Bold", cell_text(name)))
        return y_top - header_h

    def draw_table_rows(ops, y_top, row_slice):
        y = y_top
        for row in row_slice:
            for i, name in enumerate(fieldnames):
                ops.append(_pdf_text_op(content_left + i * col_w + 2, y - row_h + 3,
                                         min(font_size, (col_w - 4) / (0.6 * max(1, len(str(row.get(name, "")))))) if name == "engine" else font_size, "Courier", str(row.get(name, "")) if name == "engine" else cell_text(row.get(name, ""))))
            y -= row_h
        return y

    pages = []

    # --- page 1: title + chart + as many table rows as fit below it ---
    ops = []
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ops.append(_pdf_text_op(content_left, content_top - 14, 14, "Helvetica-Bold",
                             _pdf_ascii_fold(t("bench.pdf_title"))))
    ops.append(_pdf_text_op(content_left, content_top - 30, 9, "Helvetica",
                             _pdf_ascii_fold(t("bench.pdf_subtitle", now=now_str,
                                               runs=len(rows), depths=len(points)))))
    has_speed_chart = bool(sieve_points) or references
    chart_h = 140 if has_speed_chart else 180
    chart_top = content_top - 40
    chart_y0 = chart_top - chart_h
    ops.extend(chart_ops(content_left, chart_y0, content_width, chart_h,
                         engine_series(benchmark_engine_lines(rows, "growth")),
                         engine_series(benchmark_engine_lines(rows, "write")),
                         translator=translator,
                         label_key1="bench.axis_total_nps", label_key2="bench.axis_write_mbps",
                         fmt1="{:,.0f}", fmt2="{:,.1f}", log_y=log_y))

    if has_speed_chart:
        chart2_h = 140
        chart2_top = chart_y0 - 16
        chart2_y0 = chart2_top - chart2_h
        sieve_series = engine_series(benchmark_engine_lines(rows, "sieve"))
        if references:
            sieve_series += reference_series(t)
        ops.extend(chart_ops(
            content_left, chart2_y0, content_width, chart2_h, sieve_series,
            engine_series(benchmark_engine_lines(rows, "sieve_spw")),
            translator=translator,
            label_key1="bench.axis_sieve_nps", label_key2="bench.axis_sieve_spw",
            fmt1="{:,.0f}", fmt2="{:,.4f}", log_y=log_y))
        table_top = chart2_y0 - 12
    else:
        table_top = chart_y0 - 12
    if references:
        for ref in REFERENCES:
            table_top -= 8
            ops.append(_pdf_text_op(content_left, table_top, 6, "Helvetica", _pdf_ascii_fold(
                f"{ref.tag}: {ref.name} -- {ref.source}")))
        table_top -= 6
    y_after_header = draw_table_header(ops, table_top)
    available = y_after_header - content_bottom
    rows_fit = max(0, int(available // row_h))
    draw_table_rows(ops, y_after_header, rows[:rows_fit])
    pages.append(ops)

    # --- continuation pages: just the table, repeating the header row ---
    remaining = rows[rows_fit:]
    page_num = 2
    while remaining:
        ops = []
        ops.append(_pdf_text_op(content_left, content_top - 12, 10, "Helvetica-Bold",
                                 _pdf_ascii_fold(t("bench.pdf_continued", page=page_num))))
        table_top = content_top - 22
        y_after_header = draw_table_header(ops, table_top)
        available = y_after_header - content_bottom
        rows_fit = max(1, int(available // row_h))  # at least 1, so a single
                                                       # oversized/edge-case row can't loop
                                                       # forever without making progress
        chunk = remaining[:rows_fit]
        draw_table_rows(ops, y_after_header, chunk)
        pages.append(ops)
        remaining = remaining[len(chunk):]
        page_num += 1

    _write_pdf(path, pages, page_size=(page_w, page_h))
