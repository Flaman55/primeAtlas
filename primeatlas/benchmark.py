"""
benchmark.py -- pure-logic backend for the Benchmark tab: reading/normalizing
benchmark_log.csv, reducing its rows into chart series and per-floor stats, and
rendering the standalone PDF report. No tkinter dependency -- exercisable/unit-tested
without a display, same convention as every other module in this package except
settings_tab.py/benchmark_tab.py (see this package's __init__.py's docstring).

Extracted from prime_atlas_v1.py during the refactor branch's Faza 3 (tab-by-tab
backend/UI split, 2026-08-23) -- the Benchmark tab was the smallest of the five tabs
still living directly in that file (~350 lines vs. 1300-2400+ for the other four), so
it went first. primeatlas/benchmark_tab.py (the UI half, built on top of this module)
is the ONLY caller of everything below except read_benchmark_log(), which
prime_atlas_v1.py's own reload_primes_tree()/_primes_tree_scan() also calls directly
(for the "Prime numbers" tab's own generation-time column) -- see that function's own
docstring.

The low-level PDF-writing primitives (_pdf_text_op/_pdf_line_op/_pdf_rect_op/
_pdf_dot_op/_write_pdf/_pdf_ascii_fold) live in primeatlas/pdf_writer.py instead of
here -- they're shared with render_constellation_records_pdf (still in
prime_atlas_v1.py, the Constellations tab's own PDF export), so neither renderer
"owns" them; see that module's own docstring.

QUICK_GEN_MAX_WINDOW_WIDTH below is a deliberately DUPLICATED constant, not imported
from prime_atlas_v1.py -- same precedent as that file's own LOW_FLOOR_CUTOFF comment
("duplicated rather than imported"): importing it back from prime_atlas_v1.py would be
circular (that file imports BenchmarkTab, which imports this module), and it's a
single stable literal (the fixed window width every generation engine in this project
uses), not logic that could drift out of sync in a way worth the import wiring.
"""
import csv
import datetime
import math
import os
import re

from .i18n import Translator, DEFAULT_LANGUAGE
from .pdf_writer import _pdf_ascii_fold, _pdf_dot_op, _pdf_line_op, _pdf_rect_op, _pdf_text_op, _write_pdf

QUICK_GEN_MAX_WINDOW_WIDTH = 10_000_000  # see this module's own docstring for why this
                                          # is a duplicate, not an import, of
                                          # prime_atlas_v1.py's own constant of the
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
                            # FLOOR_PAGE_SIZE in prime_atlas_v1.py. benchmark_log.csv now
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
    CSV's own column order (and BENCHMARK_FIELDNAMES in orchestrator_v1.py etc.) is
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
    exactly (e.g. "1/1" in instance_of_n, or a plain int like "1000", are left alone) --
    same regex used for the one-off CSV repair that fixed the existing file. Mutates and
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
    return fieldnames, rows


def benchmark_metric_engines(rows, metric):
    """Engine of the last valid measurement, matching chart reduction."""
    latest = {}
    for row in rows:
        try:
            floor = int(row.get("base_exponent", ""))
            value = float(row.get(metric, ""))
        except (TypeError, ValueError):
            continue
        if not math.isnan(value):
            latest[floor] = row.get("engine") or ("hybrid" if row.get("instance_of_n") == "hybrid" else "unknown")
    return latest


def aggregate_benchmark_growth(rows):
    """Reduces benchmark_log.csv rows to one (base_exponent, loop_numbers_per_second) point per
    floor, for the "cost growth by depth" chart. loop_numbers_per_second is the real
    session-level throughput (total numbers swept across all concurrent instances / real
    wall-clock time of the orchestrator_loop run -- see _tag_single_benchmark_row() /
    _tag_benchmark_rows_by_range() in orchestrator_loop_v1.py/v2.py), used directly as the
    y-value -- higher is better, unlike the old seconds_per_window metric which got WORSE
    (higher) as more concurrent instances were added even though wall-clock throughput
    actually improved. When a floor has multiple logged runs (re-benchmarked after a
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


def aggregate_benchmark_sieve_nps(rows):
    """Actual target integers swept / sieve phase seconds, last valid row per floor.

    Storage window sizes do not measure computational work. Legacy Hybrid rows
    for one complete low floor have an exact recoverable count (9 * 10**floor).
    Other legacy rows without measured counts are omitted rather than guessed.
    """
    latest = {}
    for row in rows:
        try:
            base_exponent = int(row.get("base_exponent", ""))
            sieve_seconds = float(row.get("sieve_seconds", ""))
            raw_count = row.get("numbers_processed")
            if raw_count in (None, ""):
                engine = row.get("engine") or row.get("instance_of_n")
                if (engine == "hybrid" and 0 <= base_exponent < 7
                        and int(row.get("windows_written", "")) == 1
                        and int(row.get("target_idx_start", "")) == 0):
                    numbers_processed = 9 * 10 ** base_exponent
                else:
                    continue
            else:
                numbers_processed = int(raw_count)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(sieve_seconds) or sieve_seconds <= 0 or numbers_processed <= 0:
            continue
        latest[base_exponent] = numbers_processed / sieve_seconds
    return sorted(latest.items())


def aggregate_benchmark_write_mbps(rows):
    """Same reduction as aggregate_benchmark_sieve_nps() (last row per floor wins, only
    prime_sieve_v4_1.py rows have this data, missing/unparseable/non-positive values
    skipped), but for the disk-write phase: bytes_written / write_seconds, in MB/s -- the
    same figure orchestrator_v3.py's print_benchmark_summary() already prints inline next
    to 'write {write_seconds}s', just aggregated per floor here for the chart/PDF. Returns
    (base_exponent, write_mb_per_second) pairs sorted ascending by base_exponent."""
    latest = {}
    for row in rows:
        try:
            base_exponent = int(row.get("base_exponent", ""))
            bytes_written = float(row.get("bytes_written", ""))
            write_seconds = float(row.get("write_seconds", ""))
        except (TypeError, ValueError):
            continue
        if write_seconds <= 0 or math.isnan(write_seconds) or math.isnan(bytes_written):
            continue
        latest[base_exponent] = bytes_written / write_seconds / 1e6
    return sorted(latest.items())


def group_benchmark_rows_by_pietro(rows):
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


def _pdf_chart_ops(points, x0, y0, w, h, points2=None, translator=None,
                    label_key1="bench.axis_nps", label_key2="bench.axis_spw",
                    fmt1="{:,.0f}", fmt2="{:,.3f}", engines=None):
    """Returns PDF content-stream ops drawing a (pietro, primary-series) growth chart as
    benchmark_tab.py's own _draw_growth_chart() (same axis/tick/point layout logic),
    inside the box [x0, x0+w] x [y0, y0+h] in PDF's bottom-left-origin point space --
    kept as a SEPARATE function rather than sharing code with the canvas version, since
    tkinter's Canvas anchors ("e", "sw", ...) and y-down coordinate system have no PDF
    equivalent.

    points2 (optional): a SECOND series sharing the x-axis (pietro) -- by default the 'fair'
    loop_seconds_per_window figure shown alongside n/s, but label_key2/fmt2 (see below) let
    a caller reuse this for a different pair, e.g. sieve-numbers/s + write-MB/s. Drawn as a
    red line with its OWN right-hand y-axis and its own independent scale (values are a
    different order of magnitude from the primary series, so sharing one axis would flatten
    one of the two lines into a straight line at the bottom). The x-tick set is the UNION of
    both series' base_exponent values, so a pietro present in only one series still gets an
    x-tick.

    label_key1/label_key2: i18n keys for the primary/secondary axis titles (see
    _draw_growth_chart()'s matching parameters for the full rationale) -- default to the
    original n/s + s/window pair so existing callers are unaffected.

    fmt1/fmt2: str.format() templates used for every value label drawn next to a point and
    every y-axis tick on that series' axis -- default to the original ",.0f"/",.3f"
    precision (huge integer n/s counts vs. tiny decimal s/window figures); a caller with a
    different value shape (e.g. MB/s) passes its own template instead of getting a
    precision that doesn't fit its numbers.

    translator (optional): a primeatlas.i18n.Translator instance -- axis labels reuse the
    SAME on-screen chart's i18n keys (bench.axis_pietro/no_data_chart plus whichever
    label_key1/label_key2 resolve to, see _draw_growth_chart()) instead of separate
    hardcoded PDF text, then ASCII-fold the result (see _pdf_ascii_fold()), so every axis
    label tracks the app's actual language selection instead of a fixed one. Defaults to
    DEFAULT_LANGUAGE if not given (e.g. direct/test calls)."""
    t = (translator or Translator(DEFAULT_LANGUAGE)).t
    points = points or []
    points2 = points2 or []
    ops = [_pdf_rect_op(x0, y0, w, h, stroke_rgb=(0.8, 0.8, 0.8), width=0.5)]
    if not points and not points2:
        ops.append(_pdf_text_op(x0 + w / 2 - 60, y0 + h / 2, 10, "Helvetica",
                                 _pdf_ascii_fold(t("bench.no_data_chart"))))
        return ops

    has_secondary = bool(points2)
    pad_left = 55
    pad_right = 55 if has_secondary else 15
    pad_top, pad_bottom = 20, 30
    plot_x0 = x0 + pad_left
    plot_y0 = y0 + pad_bottom
    plot_w = max(1, w - pad_left - pad_right)
    plot_h = max(1, h - pad_top - pad_bottom)

    all_xs = sorted({p[0] for p in points} | {p[0] for p in points2})
    x_min, x_max = min(all_xs), max(all_xs)
    if x_min == x_max:
        x_min -= 1
        x_max += 1

    def y_bounds(pts):
        ys = [p[1] for p in pts]
        ylo, yhi = min(ys), max(ys)
        if ylo == yhi:
            pad = max(1.0, abs(ylo) * 0.1)
            ylo -= pad
            yhi += pad
        return min(ylo, 0), yhi

    if points:
        y_min, y_max = y_bounds(points)
    if has_secondary:
        y2_min, y2_max = y_bounds(points2)

    # Horizontal inset so the leftmost/rightmost points don't sit flush against the y-axis /
    # right edge -- their value labels (drawn centered above each point) would otherwise
    # collide with the y-axis tick labels at the same height. Numbers/second values are wide
    # (12-14 digit strings), so this collision is far more visible than it was with the old
    # short 1-2 digit s/10M values.
    inset_x = max(15.0, plot_w * 0.05)

    def sx(x):
        return plot_x0 + inset_x + (x - x_min) / (x_max - x_min) * (plot_w - 2 * inset_x)

    def sy(y):
        return plot_y0 + (y - y_min) / (y_max - y_min) * plot_h

    def sy2(y):
        return plot_y0 + (y - y2_min) / (y2_max - y2_min) * plot_h

    axis_gray = (0.4, 0.4, 0.4)
    red = (0.75, 0.2, 0.2)
    ops.append(_pdf_line_op(plot_x0, plot_y0, plot_x0, plot_y0 + plot_h, rgb=axis_gray))
    ops.append(_pdf_line_op(plot_x0, plot_y0, plot_x0 + plot_w, plot_y0, rgb=axis_gray))
    if has_secondary:
        ops.append(_pdf_line_op(plot_x0 + plot_w, plot_y0, plot_x0 + plot_w, plot_y0 + plot_h,
                                 rgb=red))

    if points:
        for i in range(6):
            y_val = y_min + (y_max - y_min) * i / 5
            y_px = sy(y_val)
            ops.append(_pdf_line_op(plot_x0 - 3, y_px, plot_x0, y_px, rgb=axis_gray))
            ops.append(_pdf_text_op(plot_x0 - 50, y_px - 3, 7, "Courier", fmt1.format(y_val)))

    if has_secondary:
        for i in range(6):
            y_val = y2_min + (y2_max - y2_min) * i / 5
            y_px = sy2(y_val)
            ops.append(_pdf_line_op(plot_x0 + plot_w, y_px, plot_x0 + plot_w + 3, y_px, rgb=red))
            ops.append(_pdf_text_op(plot_x0 + plot_w + 5, y_px - 3, 7, "Courier",
                                     fmt2.format(y_val)))

    for x_val in all_xs:
        x_px = sx(x_val)
        ops.append(_pdf_line_op(x_px, plot_y0, x_px, plot_y0 - 3, rgb=axis_gray))
        ops.append(_pdf_text_op(x_px - 8, plot_y0 - 14, 7, "Courier", str(x_val)))

    ops.append(_pdf_text_op(plot_x0 + plot_w / 2 - 30, y0 + 4, 8, "Helvetica-Bold",
                             _pdf_ascii_fold(t("bench.axis_pietro"))))
    if points:
        ops.append(_pdf_text_op(x0 + 2, y0 + h - 10, 8, "Helvetica-Bold",
                                 _pdf_ascii_fold(t(label_key1))))
    if has_secondary:
        ops.append(_pdf_text_op(x0 + w - 62, y0 + h - 10, 8, "Helvetica-Bold",
                                 _pdf_ascii_fold(t(label_key2)), rgb=red))

    if points:
        if len(points) > 1:
            coords = [(sx(xv), sy(yv)) for xv, yv in points]
            for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
                ops.append(_pdf_line_op(x1, y1, x2, y2, width=1.5, rgb=(0.29, 0.56, 0.85)))
        for x_val, y_val in points:
            cx, cy = sx(x_val), sy(y_val)
            ops.append(_pdf_dot_op(cx, cy, 2.5, rgb=(0.11, 0.37, 0.66)))
            ops.append(_pdf_text_op(cx - 10, cy + 8, 7, "Courier", fmt1.format(y_val) + (" [" + engines.get(x_val, "unknown") + "]" if engines else "")))

    if has_secondary:
        if len(points2) > 1:
            coords2 = [(sx(xv), sy2(yv)) for xv, yv in points2]
            for (x1, y1), (x2, y2) in zip(coords2, coords2[1:]):
                ops.append(_pdf_line_op(x1, y1, x2, y2, width=1.5, rgb=red))
        for x_val, y_val in points2:
            cx, cy = sx(x_val), sy2(y_val)
            ops.append(_pdf_dot_op(cx, cy, 2.5, rgb=red))
            ops.append(_pdf_text_op(cx - 12, cy - 14, 7, "Courier", fmt2.format(y_val), rgb=red))

    return ops


def render_benchmark_pdf(path, points, fieldnames, rows, points2=None, translator=None,
                          sieve_points=None, write_points=None):
    """Writes a standalone PDF report -- the same growth chart(s) shown in the Benchmark tab
    plus the FULL benchmark_log.csv table (every row, every column) -- to `path`. The table
    continues onto as many additional (landscape A4) pages as needed, repeating the column
    header row on each one, since a project running for months can accumulate far more rows
    than fit on one page. Pure function (no tkinter) so it can be exercised/tested without a
    display -- the GUI layer (BenchmarkTab._export_benchmark_pdf) just gathers the same
    points/fieldnames/rows this module already computed for the on-screen chart/table and
    hands them here unchanged.

    points2 (optional): second (base_exponent, loop_seconds_per_window) series, drawn as a
    second red line on its own right-hand y-axis -- see _pdf_chart_ops().

    sieve_points/write_points (optional): the sieve-numbers/s and write-MB/s series from
    aggregate_benchmark_sieve_nps()/aggregate_benchmark_write_mbps() -- only populated for
    floors re-benchmarked with prime_sieve_v4_1.py, so most projects will have this empty
    for a while yet. A SECOND chart, same layout as the primary one, is only drawn (taking
    space away from the table below it) when at least one of the two is non-empty --
    otherwise page 1 looks exactly as it did before this pair of series existed, rather
    than reserving blank chart space no data will ever fill.

    translator (optional): a primeatlas.i18n.Translator instance, threaded into
    _pdf_chart_ops() and used for the title/subtitle/continuation-page header below --
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
    has_speed_chart = bool(sieve_points) or bool(write_points)
    chart_h = 140 if has_speed_chart else 180
    chart_top = content_top - 40
    chart_y0 = chart_top - chart_h
    ops.extend(_pdf_chart_ops(points, content_left, chart_y0, content_width, chart_h,
                               points2=points2, translator=translator,
                               engines=benchmark_metric_engines(rows, "loop_numbers_per_second")))

    if has_speed_chart:
        chart2_h = 140
        chart2_top = chart_y0 - 16
        chart2_y0 = chart2_top - chart2_h
        ops.extend(_pdf_chart_ops(
            sieve_points, content_left, chart2_y0, content_width, chart2_h,
            points2=write_points, translator=translator,
            label_key1="bench.axis_sieve_nps", label_key2="bench.axis_write_mbps",
            fmt1="{:,.0f}", fmt2="{:,.1f}"))
        table_top = chart2_y0 - 12
    else:
        table_top = chart_y0 - 12
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
