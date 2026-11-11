"""The columns of the Benchmark run table: the tab's tree, the PDF and HTML report tables and
the CSV export show these, in this order, from the rows of benchmark_log.csv (which keeps
every logged column; a view never writes it).

Left to right, the most used for analysis first: the engine (line_names.base_name(), the
legend's name, with the build commit), the sieve speed (numbers / sieve_seconds, the sieve
chart's phase measure), the whole-run speed (loop_numbers_per_second, the whole-run chart's
value; numbers / total_seconds for a row without it), the run time (loop_session_seconds,
else total_seconds), seconds per window (loop_seconds_per_window, else seconds_per_window,
else time / windows), the numbers covered (line_names.width_label()), the windows ("1000
(0-999)": windows_written, or the range's count for a run that writes none); then what
kind of run it was: purpose (row_purpose(): storage or benchmark), status (blank = completed),
threads (line_names.threads_label(): instances, sieve and write threads); then the phases:
sieve, sieve with startup, write, write MB/s, verify, proof, peak RAM; last the results:
primes, pi(L), L.

Columns the log has and the table leaves out: each is one of the shown columns under another
name or a quotient of two of them (write_files, run_purpose, kind, engine_version,
instance_of_n, write_threads, target_idx_start/end, total_seconds or loop_session_seconds,
seconds_per_window or loop_seconds_per_window, avg_primes_per_window, primes_per_second,
bytes_written, sieve_count_basis), or base_gen_seconds, the sieving-prime generation of
hundredths of a second.

raw(row, key): the value as the CSV export writes it ("" when the run has none); shown(row,
key, t): as the tables show it (table_cells.MISSING when the run has none). The reports add
the floor and the run's timestamp in front (KEY_COLUMNS); the tree groups runs by floor and
names each by its timestamp. No tkinter here.
"""
import math

import benchmark_log_schema as schema

from . import line_names, table_cells
from .benchmark import benchmark_sieve_count

FLOOR, RUN, ENGINE = "floor", "run", "engine"
KEY_COLUMNS = (FLOOR, RUN, ENGINE)

# (i18n title key, columns) of the report tables, in column order; their concatenation is the
# tree's column order.
GROUPS = (
    ("bench.pdf_table_speed", (ENGINE, "sieve_nps", "run_nps", "seconds",
                               "seconds_per_window", "numbers", "windows")),
    ("bench.pdf_table_run", ("purpose", "status", "threads")),
    ("bench.pdf_table_phases", ("sieve_seconds", "sieve_wall_seconds", "write_seconds",
                                "write_mbps", "verify_seconds", "proof_seconds", "ram_mb")),
    ("bench.pdf_table_results", ("primes", "pi_l", "l_final")),
)
TREE_COLUMNS = tuple(c for _title, columns in GROUPS for c in columns)
EXPORT_COLUMNS = KEY_COLUMNS + TREE_COLUMNS[1:]

# Tree column widths in pixels; a column not named here gets DEFAULT_WIDTH.
WIDTHS = {ENGINE: 150, "threads": 140, "windows": 130, "sieve_nps": 130, "run_nps": 130}
DEFAULT_WIDTH = 100

# Log columns shown as they are.
_COPIED = {"sieve_seconds": "sieve_seconds", "sieve_wall_seconds": "sieve_wall_seconds",
           "write_seconds": "write_seconds", "verify_seconds": "verify_seconds",
           "proof_seconds": "proof_seconds", "ram_mb": "max_child_rss_mb",
           "primes": "total_primes", "pi_l": "sieving_primes_count", "l_final": "l_final",
           RUN: "run_timestamp_utc", FLOOR: "base_exponent"}


def header_key(column):
    return f"bench.table_col_{column}"


def _float(row, column):
    try:
        value = float(row.get(column, ""))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _text(row, column):
    value = row.get(column)
    return "" if value is None else str(value).strip()


def _first(row, *columns):
    """The first of `columns` the row has a number in, as its log text."""
    for column in columns:
        if _float(row, column) is not None:
            return _text(row, column)
    return ""


def numbers(row):
    """The integers the run covered: numbers_processed, or the exact count of an old hybrid
    row (benchmark.benchmark_sieve_count()); None when unknown."""
    return benchmark_sieve_count(row)[0]


def _per_second(count, seconds):
    if count is None or seconds is None or seconds <= 0:
        return None
    return count / seconds


def sieve_nps(row):
    return _per_second(numbers(row), _float(row, "sieve_seconds"))


def run_nps(row):
    loop = _float(row, "loop_numbers_per_second")
    if loop is not None:
        return loop
    return _per_second(numbers(row), _float(row, "total_seconds"))


def write_mbps(row):
    written = _float(row, "bytes_written")
    return None if written is None else _per_second(written / 1e6, _float(row, "write_seconds"))


def window_count(row):
    """The windows the run covered: windows_written, or the count of its target range for a
    run that writes none (a native count); None when neither is known."""
    written = _float(row, "windows_written")
    if written:
        return int(written)
    start, end = _float(row, "target_idx_start"), _float(row, "target_idx_end")
    if start is None or end is None or end < start:
        return None
    return int(end - start) + 1


def _windows(row):
    count = window_count(row)
    start, end = _text(row, "target_idx_start"), _text(row, "target_idx_end")
    if count is None:
        return ""
    return f"{count} ({start}-{end})" if start and end else str(count)


def _seconds_per_window(row):
    logged = _first(row, "loop_seconds_per_window", "seconds_per_window")
    if logged:
        return logged
    seconds, windows = _float(row, "total_seconds"), window_count(row)
    if not seconds or seconds < 0 or not windows:
        return ""
    return _number_text(seconds / windows, 6)


def _status(row):
    return _text(row, "run_status") or schema.RUN_STATUS_COMPLETED


def _number_text(value, digits):
    return "" if value is None else f"{value:.{digits}f}"


_RAW = {
    ENGINE: lambda row: line_names.base_name(row, keep_commit=True),
    "sieve_nps": lambda row: _number_text(sieve_nps(row), 0),
    "run_nps": lambda row: _number_text(run_nps(row), 0),
    "seconds": lambda row: _first(row, "loop_session_seconds", "total_seconds"),
    "seconds_per_window": _seconds_per_window,
    "numbers": lambda row: "" if numbers(row) is None else str(numbers(row)),
    "windows": _windows,
    "purpose": schema.row_purpose,
    "status": _status,
    "threads": line_names.threads_label,
    "write_mbps": lambda row: _number_text(write_mbps(row), 1),
}


def raw(row, column):
    """`row`'s value in `column` as the CSV export writes it; "" when the run has none."""
    if column in _COPIED:
        return _text(row, _COPIED[column])
    return _RAW[column](row)


_SHOWN = {
    "sieve_nps": lambda row, t: f"{sieve_nps(row):,.0f}",
    "run_nps": lambda row, t: f"{run_nps(row):,.0f}",
    "numbers": lambda row, t: line_names.width_label(numbers(row)),
    "purpose": lambda row, t: t(f"bench.purpose_{schema.row_purpose(row)}"),
    "status": lambda row, t: t(f"bench.run_status_{_status(row)}"),
}


def shown(row, column, t):
    """`row`'s value in `column` as the tables show it: grouped thousands for the speeds,
    "10^10" for the numbers, purpose and status in the user's language;
    table_cells.MISSING when the run has none."""
    if not raw(row, column):
        return table_cells.MISSING
    if column in _SHOWN:
        return _SHOWN[column](row, t)
    return raw(row, column)


def report_tables():
    """[(i18n title key, columns)] of the report tables, each led by the key columns."""
    return [(title, KEY_COLUMNS + tuple(c for c in columns if c not in KEY_COLUMNS))
            for title, columns in GROUPS]


def stats(rows):
    """{count, avg, min, max} of the seconds-per-window column over `rows`, None when no row
    has a value: the summary at the top of a floor in the tree."""
    values = [float(v) for v in (raw(row, "seconds_per_window") for row in rows) if v]
    if not values:
        return None
    return {"count": len(values), "avg": sum(values) / len(values),
            "min": min(values), "max": max(values)}
