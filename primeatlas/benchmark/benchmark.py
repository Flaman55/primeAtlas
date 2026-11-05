"""
benchmark.py -- pure-logic backend for the Benchmark tab: reading/normalizing
benchmark_log.csv, reducing its rows into chart series and per-floor stats, and
rendering the standalone PDF report. No tkinter dependency -- exercisable/unit-tested
without a display, same convention as every non-GUI module in this package (the
tkinter code lives in the tab, section and widget modules).

primeatlas/benchmark/benchmark_tab.py (the UI half, built on top of this module) is the ONLY
caller of everything below except read_benchmark_log(), which
PortalBrowserApp's own reload_primes_tree()/_primes_tree_scan() also calls directly
(for the "Prime numbers" tab's own generation-time column) -- see that function's own
docstring.

The low-level PDF-writing primitives (_pdf_text_op/_pdf_line_op/_pdf_rect_op/
_pdf_dot_op/_write_pdf/_pdf_ascii_fold) live in primeatlas/core/pdf_writer.py instead of
here -- they're shared with render_constellation_records_pdf (still in
primeatlas/app/, the Constellations tab's own PDF export), so neither renderer
"owns" them; see that module's own docstring.

QUICK_GEN_MAX_WINDOW_WIDTH below is a deliberately DUPLICATED constant, not imported
from primeatlas/app/ -- same precedent as that file's own LOW_FLOOR_CUTOFF comment
("duplicated rather than imported"): importing it back from primeatlas/app/ would be
circular (that file imports BenchmarkTab, which imports this module), and it's a
single stable literal (the fixed window width every generation engine in this project
uses), not logic that could drift out of sync in a way worth the import wiring.
"""
import csv
import datetime
import math
import os
import re

import storage_kinds

from ..core.i18n import Translator, DEFAULT_LANGUAGE
from ..core.pdf_table import TableLayout, table_pages
from ..core.pdf_writer import _pdf_ascii_fold, _pdf_text_op, _write_pdf
from .chart_pdf import chart_ops
from .chart_series import axis_pins, engine_lines, engine_series, visible_series
from . import line_names, sieve_measure
from .reference_points import REFERENCES, reference_series

QUICK_GEN_MAX_WINDOW_WIDTH = 10_000_000  # see this module's own docstring for why this
                                          # is a duplicate, not an import, of
                                          # PortalBrowserApp's own constant of the
                                          # same name.

BENCHMARK_PDF_KEY_COLUMNS = ("run_timestamp_utc", "base_exponent", "engine")  # first in
                                # every PDF table, to match a run's rows across tables
# The PDF report's logical tables: (i18n title key, columns), one question each -- what
# was run, how fast, where the time and memory went, what the sieve found. A log column
# in none of them goes to a final "other" table (benchmark_pdf_tables()).
BENCHMARK_PDF_TABLES = (
    ("bench.pdf_table_run", ("engine_version", "threads", "kind", "run_status",
                             "instance_of_n", "target_idx_start", "target_idx_end",
                             "windows_written", "numbers_processed", "write_files")),
    ("bench.pdf_table_speed", ("total_seconds", "seconds_per_window", "loop_session_seconds",
                               "loop_seconds_per_window", "loop_numbers_per_second",
                               "primes_per_second")),
    ("bench.pdf_table_phases", ("base_gen_seconds", "sieve_seconds", "sieve_wall_seconds",
                                "write_seconds", "bytes_written", "max_child_rss_mb")),
    ("bench.pdf_table_results", ("total_primes", "avg_primes_per_window", "l_final",
                                 "sieving_primes_count", "sieve_count_basis")),
)
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
                            # FLOOR_PAGE_SIZE in app_const.py. benchmark_log.csv now
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
        if "kind" in fieldnames:
            fieldnames.remove("kind")
            fieldnames.insert(1, "kind")
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
    for row in rows:
        row["kind"] = benchmark_row_kind(row)
    if "kind" not in fieldnames:
        fieldnames.append("kind")
    return fieldnames, rows


def benchmark_row_kind(row):
    """Store a run wrote into (storage_kinds.py): "D", "P", or "D+P" for a pt1 run on
    floor 24 whose windows lie on both sides of MR_DET_BOUND. Derived from the engine and
    the run's window range (fixed width QUICK_GEN_MAX_WINDOW_WIDTH; the whole floor when
    the range is unreadable); a "kind" value already in the row wins."""
    if row.get("kind"):
        return row["kind"]
    engine = _row_engine(row)
    if engine != storage_kinds.ENGINE_PT1:
        return storage_kinds.KIND_D
    try:
        floor = int(row.get("base_exponent", ""))
    except (TypeError, ValueError):
        return ""
    base = 10 ** floor
    w = QUICK_GEN_MAX_WINDOW_WIDTH
    try:
        lo = base + int(row.get("target_idx_start", "")) * w
        hi = base + (int(row.get("target_idx_end", "")) + 1) * w
    except (TypeError, ValueError):
        lo, hi = base, 10 * base
    first = storage_kinds.written_kind(engine, lo, lo + w)
    last = storage_kinds.written_kind(engine, hi - w, hi)
    return first if first == last else f"{first}+{last}"


def _row_engine(row):
    return row.get("engine") or ("hybrid" if row.get("instance_of_n") == "hybrid" else "unknown")


def _row_line_engine(row):
    """Color/draw-order key of a row's line: the engine for D runs, "engine kind" otherwise
    ("pt1 P"), so D and P measurements never share a line."""
    kind = row.get("kind") or storage_kinds.KIND_D
    engine = _row_engine(row)
    return engine if kind == storage_kinds.KIND_D else f"{engine} {kind}"


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


def _row_sieve_nps(row, field="sieve_seconds"):
    """Numbers swept per second of `field`: the engine's sieve_seconds, or
    sieve_wall_seconds (the sieve timed from the scanner's launch)."""
    try:
        sieve_seconds = float(row.get(field, ""))
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


def _row_sieve_spw(row, field="sieve_seconds"):
    """Sieve seconds (`field`, as in _row_sieve_nps()) per window: / windows_written; a row
    that wrote no Atlas windows (native primesieve count) counts windows of
    QUICK_GEN_MAX_WINDOW_WIDTH numbers over its numbers_processed."""
    try:
        sieve_seconds = float(row.get(field, ""))
        windows = int(row.get("windows_written", ""))
    except (TypeError, ValueError):
        return None
    if windows <= 0 and line_names.row_engine(row) in line_names.NO_WINDOW_ENGINES:
        numbers, _ = benchmark_sieve_count(row)
        windows = numbers / QUICK_GEN_MAX_WINDOW_WIDTH if numbers else 0
    if not math.isfinite(sieve_seconds) or sieve_seconds <= 0 or windows <= 0:
        return None
    return sieve_seconds / windows


def _row_sieve_overhead(row):
    """(n/s, % of the engine-phase n/s) the startup takes from the sieve speed: the speed
    over the engine's own sieve timer minus the speed over the sieve timed from the
    scanner's launch; None without both times."""
    phase = _row_sieve_nps(row)
    wall = _row_sieve_nps(row, "sieve_wall_seconds")
    if phase is None or wall is None:
        return None
    return phase - wall, (phase - wall) / phase * 100


def _overhead_part(index):
    def value(row):
        overhead = _row_sieve_overhead(row)
        return None if overhead is None else overhead[index]
    return value


def _wall_field(row):
    """The column holding a row's sieve time with startup: sieve_seconds for an engine timed
    as one whole process (line_names.WHOLE_PROCESS_SIEVE), else sieve_wall_seconds."""
    return ("sieve_seconds" if line_names.row_engine(row) in line_names.WHOLE_PROCESS_SIEVE
            else "sieve_wall_seconds")


def _row_ram_mb(row):
    """The run's peak RAM: max_child_rss_mb (the largest child process's RSS); None when
    the writer did not measure it."""
    return _metric_value(row, "max_child_rss_mb")


def _row_ram_mb_per_window(row):
    """Peak RAM per window of the run, so runs of different widths compare."""
    ram = _row_ram_mb(row)
    try:
        windows = int(row.get("windows_written", ""))
    except (TypeError, ValueError):
        return None
    return ram / windows if ram is not None and windows > 0 else None


_LINE_VALUES = {
    "growth": lambda row: _metric_value(row, "loop_numbers_per_second"),
    "write": _row_write_mbps,
    "sieve": _row_sieve_nps,
    "sieve_spw": _row_sieve_spw,
    "ram": _row_ram_mb,
    "ram_per_window": _row_ram_mb_per_window,
    "sieve_wall": lambda row: _row_sieve_nps(row, _wall_field(row)),
    "sieve_wall_spw": lambda row: _row_sieve_spw(row, _wall_field(row)),
    "sieve_overhead": _overhead_part(0),
    "sieve_overhead_pct": _overhead_part(1),
}


def benchmark_engine_lines(rows, metric):
    """{line name: [(base_exponent, value)]} for one chart metric ("growth", "write",
    "sieve", "sieve_spw", the other sieve measures of sieve_measure.py, "ram",
    "ram_per_window"): the same per-row value as the matching aggregate_* reduction, but
    the last row per floor AND line (line_names.line_name(): engine or version, the store
    for P runs, threads), so each engine build and thread setup gets its own chart line.
    Rows whose engine is not drawn on this metric (line_names.on_chart()) are left out."""
    value = _LINE_VALUES[metric]
    return engine_lines(rows, lambda row: value(row) if line_names.on_chart(row, metric)
                        else None, line_names.line_name)


def benchmark_line_engines(rows):
    """{line name: color/draw-order key} for the rows' lines."""
    return {line_names.line_name(row): _row_line_engine(row) for row in rows}


def benchmark_line_widths(rows, metric):
    """{line name: {floor: width label}} of the points benchmark_engine_lines() draws: the
    range of the row each point comes from (line_names.width_label())."""
    value = _LINE_VALUES[metric]
    lines = engine_lines(
        rows, lambda row: (line_names.width_label(row.get("numbers_processed"))
                           if line_names.on_chart(row, metric) and value(row) is not None
                           else None), line_names.line_name)
    return {name: dict(points) for name, points in lines.items()}


def mixed_width_floors(rows, metric):
    """Floors where the chart of `metric` sets points of different range widths side by
    side, so their speeds do not compare on an equal range."""
    widths = {}
    for points in benchmark_line_widths(rows, metric).values():
        for floor, width in points.items():
            if width:
                widths.setdefault(floor, set()).add(width)
    return sorted(floor for floor, found in widths.items() if len(found) > 1)


def benchmark_series(rows, metric):
    """[Series] of one chart metric, colored by engine, each point noting its width."""
    return engine_series(benchmark_engine_lines(rows, metric), benchmark_line_engines(rows),
                         benchmark_line_widths(rows, metric))


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


# A report chart: (tab chart key, axis, metric of benchmark_engine_lines(), axis title key,
# value format). The report draws one metric per chart, two charts per page.
_RUN_CHARTS = (("run", "primary", "growth", "bench.axis_total_nps", "{:,.0f}"),
               ("run", "secondary", "write", "bench.axis_write_mbps", "{:,.1f}"))
_RAM_CHARTS = (("ram", "primary", "ram", "bench.axis_ram_mb", "{:,.0f}"),
               ("ram", "secondary", "ram_per_window", "bench.axis_ram_mb_window", "{:,.2f}"))


def _sieve_charts(measure):
    spec = sieve_measure.chart(measure)
    return (("sieve", "primary", spec.metric1, spec.label_key1, spec.fmt1),
            ("sieve", "secondary", spec.metric2, spec.label_key2, spec.fmt2))


def report_chart_pages(rows, sieve_points=None, references=False,
                       measure=sieve_measure.DEFAULT):
    """[(page kind, (first chart, second chart))] of the report (PDF, SVG, HTML): the whole
    run always; the sieve, in `measure`, when sieve_points is non-empty or references is on;
    RAM when any row measured it."""
    pages = [("run", _RUN_CHARTS)]
    if sieve_points or references:
        pages.append(("sieve", _sieve_charts(measure)))
    if benchmark_engine_lines(rows, "ram"):
        pages.append(("ram", _RAM_CHARTS))
    return pages


def report_references(references, measure=sieve_measure.DEFAULT):
    """Whether the reference series go on the sieve page's first chart: the toggle is on and
    the measure is a sieve speed (sieve_measure.chart().references)."""
    return bool(references) and sieve_measure.chart(measure).references


def report_chart_series(rows, chart, hidden_lines=None, extra=()):
    """The visible Series of one report chart (see report_chart_pages()), its reference
    series (`extra`) included, the lines hidden in the tab's legend left out."""
    chart_key, axis, metric = chart[:3]
    series = benchmark_series(rows, metric) + list(extra)
    return visible_series(series, (hidden_lines or {}).get(chart_key), axis)


def report_mixed_note(rows, charts, t):
    """The "points of different widths" note of a report page's charts, "" when none."""
    floors = sorted({f for chart in charts for f in mixed_width_floors(rows, chart[2])})
    return t("bench.mixed_widths", floors=", ".join(map(str, floors))) if floors else ""


def render_benchmark_pdf(path, points, fieldnames, rows, points2=None, translator=None,
                          sieve_points=None, write_points=None, references=False,
                          log_y=False, hidden_lines=None, y_pins=None, filter_note="",
                          measure=sieve_measure.DEFAULT):
    """Writes a standalone PDF report -- the Benchmark tab's charts plus the FULL
    benchmark_log.csv (every row, every column, every cell in full) -- to `path`, A4
    landscape. Pure function (no tkinter): the GUI layer (BenchmarkTab._export_benchmark_pdf)
    hands over the points/fieldnames/rows it already computed for the tab.

    Charts: one metric per chart, two charts per page, one line per engine from `rows`
    (benchmark_engine_lines()): the whole run (loop n/s), its write speed (MB/s), and --
    when sieve_points is non-empty or references is on -- the sieve phase alone (sieve n/s)
    and its seconds per window, then -- when a row measured it -- each run's peak RAM and
    its RAM per window. The tab's two-axis charts are split in two here so that
    each chart has room for its value labels (chart_pdf.place_labels()).

    Tables: BENCHMARK_PDF_TABLES, one logical table per question, each starting on its own
    page with BENCHMARK_PDF_KEY_COLUMNS first, continuing over as many pages as the rows
    need (core/pdf_table.py). Column headers are the raw benchmark_log.csv names, as in the
    tab's tree.

    references: also draw reference_points.py's series on the sieve n/s chart -- PARI/GP
    iterates in memory and writes nothing, so it compares with the sieve phase -- with a
    footnote line per reference (full name and source). A page whose charts set points of
    different range widths on one floor says so next to its heading (mixed_width_floors()).
    log_y: log10 y-axes on every chart -- the Benchmark tab's two toggles.
    hidden_lines: {"run" | "sieve" | "ram": set of chart_series.line_key()} -- the lines switched
    off in the tab's legends, left out of the charts and their scales.
    y_pins: {"run" | "sieve" | "ram": {axis: (min, max)}} -- the tab's pinned y-axis bounds
    (chart_series.pin_bound()); each axis' pins apply to the chart of that metric.

    points: aggregate_benchmark_growth(), for the subtitle's floor count. points2 and
    write_points are kept for the callers' symmetry.

    filter_note: the tab's filter summary (chart_filter.summary()), added to the subtitle
    when the rows are a filtered selection of the log.
    measure: the time the sieve page charts (sieve_measure.py), named in its heading; the
    references go on it only for the n/s measures.

    translator (optional): a primeatlas.core.i18n.Translator instance for every title,
    axis label and continuation header -- DEFAULT_LANGUAGE if not given."""
    t = (translator or Translator(DEFAULT_LANGUAGE)).t
    page_w, page_h = 841.89, 595.28  # A4 landscape, points
    margin = 30
    content_left = margin
    content_width = page_w - 2 * margin
    content_top = page_h - margin
    content_bottom = margin
    chart_gap = 15
    hidden_lines = hidden_lines or {}
    y_pins = y_pins or {}

    def chart(spec, y0, h, extra=()):
        chart_key, axis, _metric, label_key, fmt = spec
        return chart_ops(content_left, y0, content_width, h,
                         report_chart_series(rows, spec, hidden_lines, extra),
                         translator=translator, label_key1=label_key, fmt1=fmt,
                         log_y=log_y, pins1=axis_pins(y_pins.get(chart_key), axis))

    def chart_pair(ops, top, bottom, charts, extra=()):
        h = (top - bottom - chart_gap) / 2
        ops.extend(chart(charts[0], top - h, h, extra=extra))
        ops.extend(chart(charts[1], bottom, h))

    def mixed_note(charts):
        note = report_mixed_note(rows, charts, t)
        return "  |  " + note if note else ""

    pages_charts = dict(report_chart_pages(rows, sieve_points, references, measure))

    # --- page 1: title, the whole run's two charts ---
    ops = []
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ops.append(_pdf_text_op(content_left, content_top - 14, 14, "Helvetica-Bold",
                             _pdf_ascii_fold(t("bench.pdf_title"))))
    ops.append(_pdf_text_op(content_left, content_top - 30, 9, "Helvetica",
                             _pdf_ascii_fold(t("bench.pdf_subtitle", now=now_str,
                                               runs=len(rows), depths=len(points))
                                             + ("  |  " + filter_note if filter_note else "")
                                             + mixed_note(pages_charts["run"]))))
    chart_pair(ops, content_top - 40, content_bottom, pages_charts["run"])
    pages = [ops]

    # --- page 2: the sieve's two charts, reference footnotes below them ---
    if "sieve" in pages_charts:
        references = report_references(references, measure)
        ops = [_pdf_text_op(content_left, content_top - 12, 10, "Helvetica-Bold",
                            _pdf_ascii_fold(t("bench.pdf_continued", page=2)
                                            + "  |  " + sieve_measure.heading(measure, t)
                                            + mixed_note(pages_charts["sieve"])))]
        bottom = content_bottom
        if references:
            for i, ref in enumerate(reversed(REFERENCES)):
                ops.append(_pdf_text_op(content_left, content_bottom + 8 * i, 6, "Helvetica",
                                        _pdf_ascii_fold(f"{ref.tag}: {ref.name} -- {ref.source}")))
            bottom = content_bottom + 8 * len(REFERENCES) + 4
        chart_pair(ops, content_top - 22, bottom, pages_charts["sieve"],
                   extra=reference_series(t) if references else ())
        pages.append(ops)

    # --- the RAM page: each run's peak RAM and its RAM per window ---
    if "ram" in pages_charts:
        ops = [_pdf_text_op(content_left, content_top - 12, 10, "Helvetica-Bold",
                            _pdf_ascii_fold(t("bench.pdf_continued", page=len(pages) + 1)
                                            + mixed_note(pages_charts["ram"])))]
        chart_pair(ops, content_top - 22, content_bottom, pages_charts["ram"])
        pages.append(ops)

    # --- the logical tables, each from a new page ---
    for title_key, columns in benchmark_pdf_tables(fieldnames):
        title = t(title_key)
        layout = TableLayout(columns, rows, content_width, 6.5, BENCHMARK_PDF_KEY_COLUMNS)
        first = [_pdf_text_op(content_left, content_top - 12, 12, "Helvetica-Bold",
                              _pdf_ascii_fold(title))]
        offset = len(pages)
        pages += table_pages(
            layout, rows, first, content_top - 22, content_top, content_bottom, content_left,
            lambda page, part, parts, title=title, offset=offset:
            t("bench.pdf_table_continued", title=title, page=offset + page)
            + (t("pdf.columns_part", part=part, parts=parts) if parts > 1 else ""))
    _write_pdf(path, pages, page_size=(page_w, page_h))


def benchmark_pdf_tables(fieldnames):
    """[(i18n title key, columns)] of the PDF report's tables for this log's fieldnames:
    each BENCHMARK_PDF_TABLES entry with at least one of its columns present, the key
    columns first, then a "bench.pdf_table_other" table of every remaining column (also
    when no logical table applies, so a log of only key columns still gets a table)."""
    keys = [k for k in BENCHMARK_PDF_KEY_COLUMNS if k in fieldnames]
    grouped = set(keys)
    tables = []
    for title_key, columns in BENCHMARK_PDF_TABLES:
        own = [c for c in columns if c in fieldnames]
        grouped.update(own)
        if own:
            tables.append((title_key, keys + own))
    rest = [c for c in fieldnames if c not in grouped]
    if rest or not tables:
        tables.append(("bench.pdf_table_other", keys + rest))
    return tables
