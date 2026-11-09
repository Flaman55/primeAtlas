"""Which logged runs the Benchmark charts compare.

A selection is {dimension: set of values} for the filtered dimensions: a run stays when its
value is selected in every one of them; a dimension left out is at All and filters nothing,
one with nothing selected keeps nothing. The Filter window edits it with toggle_value() and
select_all(): All or single values, never All minus some. The charts then reduce the kept runs
to one point per line and x (chart_points.py), so choosing one width compares every engine on
that width and choosing floors compares them floor by floor. Values come from line_names, so
they read like the chart lines ("v6.0", "15 thr", "2x24 thr", write "8", width "10^11"), the
floor as its exponent ("28"); "" is a run from before that column. The run purpose
(benchmark_log_schema.row_purpose(): a benchmark run that only measured, or a storage run) is
shown translated (value_label()). No tkinter here.
"""
import re

import benchmark_log_schema as schema

from . import line_names

DIMENSIONS = ("purpose", "floor", "engine", "threads", "write_threads", "width")
PURPOSE_LABEL_KEYS = {schema.RUN_PURPOSE_BENCHMARK: "bench.purpose_benchmark",
                      schema.RUN_PURPOSE_STORAGE: "bench.purpose_storage"}
DIMENSION_KEYS = {"purpose": "bench.filter_dim_purpose", "floor": "bench.filter_dim_floor",
                  "engine": "bench.filter_dim_engine", "threads": "bench.filter_dim_threads",
                  "write_threads": "bench.filter_dim_write_threads",
                  "width": "bench.filter_dim_width"}

_VALUE = {
    "purpose": schema.row_purpose,
    "floor": lambda row: str(row.get("base_exponent") or "").strip(),
    "engine": line_names.base_name,
    "threads": line_names.sieve_threads_label,
    "write_threads": line_names.write_threads_label,
    "width": lambda row: line_names.width_label(row.get("numbers_processed")),
}


def row_value(row, dimension):
    return _VALUE[dimension](row)


def _order(dimension, value):
    if dimension == "width":
        m = re.fullmatch(r"(?:([\d.]+)x)?10\^(\d+)", value)
        return (0, float(m.group(1) or 1) * 10 ** int(m.group(2))) if m else (-1, 0)
    if dimension == "threads":
        m = re.fullmatch(r"(?:(\d+)x)?(\d+) thr", value)
        return (0, int(m.group(1) or 1), int(m.group(2))) if m else (-1, value)
    if dimension in ("write_threads", "floor"):
        return (0, int(value)) if value.isdigit() else (-1, value)
    return (0, value)


def value_label(dimension, value, t):
    """How the Filter window and the summary show `value` of `dimension`."""
    if dimension == "purpose" and value in PURPOSE_LABEL_KEYS:
        return t(PURPOSE_LABEL_KEYS[value])
    return value or t("bench.filter_blank")


def dimension_values(rows, dimension):
    """The values `rows` hold for `dimension`, in numeric order ("" and "?" first)."""
    values = {row_value(row, dimension) for row in rows}
    return sorted(values, key=lambda v: _order(dimension, v))


def keeps(row, selection):
    """True when the row's value is selected in every enabled dimension of `selection`."""
    return all(row_value(row, dim) in chosen for dim, chosen in selection.items())


def toggle_value(selection, dimension, value):
    """The selection after `value` of `dimension` is clicked: from All (dimension absent)
    only that value; otherwise the value is added or removed, and removing the last one
    goes back to All. Returns a new selection; the given one is not changed."""
    result = {dim: set(chosen) for dim, chosen in selection.items()}
    if dimension not in result:
        result[dimension] = {value}
    elif value in result[dimension]:
        result[dimension].discard(value)
        if not result[dimension]:
            del result[dimension]
    else:
        result[dimension].add(value)
    return result


def select_all(selection, dimension):
    """The selection with `dimension` back at All (no filter on it)."""
    return {dim: set(chosen) for dim, chosen in selection.items() if dim != dimension}


def apply(rows, selection):
    """The rows whose value is selected in every enabled dimension of `selection`."""
    return [row for row in rows if keeps(row, selection)]


def summary(selection, t):
    """One line naming the enabled dimensions and their values, for the tab and the PDF."""
    if not selection:
        return t("bench.filter_off")
    parts = []
    for dim in DIMENSIONS:
        if dim in selection:
            chosen = sorted(selection[dim], key=lambda v: _order(dim, v))
            shown = ", ".join(value_label(dim, v, t) for v in chosen)
            parts.append(f"{t(DIMENSION_KEYS[dim])}: {shown or '-'}")
    return t("bench.filter_on", parts="; ".join(parts))
