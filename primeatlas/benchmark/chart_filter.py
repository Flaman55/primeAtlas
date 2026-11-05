"""Which logged runs the Benchmark charts compare.

A selection is {dimension: set of values} for the enabled dimensions: a run stays when its
value is selected in every one of them; a dimension left out filters nothing, an enabled one
with nothing selected keeps nothing. The charts then take the last row per floor and line
from the kept runs, so choosing one width compares every engine on that width. Values come
from line_names, so they read like the chart lines ("v6.0", "15 thr", "2x24 thr", write "8",
width "10^11"); "" is a run from before that column. No tkinter here.
"""
import re

from . import line_names

DIMENSIONS = ("engine", "threads", "write_threads", "width")
DIMENSION_KEYS = {"engine": "bench.filter_dim_engine", "threads": "bench.filter_dim_threads",
                  "write_threads": "bench.filter_dim_write_threads",
                  "width": "bench.filter_dim_width"}

_VALUE = {
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
    if dimension == "write_threads":
        return (0, int(value)) if value.isdigit() else (-1, value)
    return (0, value)


def dimension_values(rows, dimension):
    """The values `rows` hold for `dimension`, in numeric order ("" and "?" first)."""
    values = {row_value(row, dimension) for row in rows}
    return sorted(values, key=lambda v: _order(dimension, v))


def keeps(row, selection):
    """True when the row's value is selected in every enabled dimension of `selection`."""
    return all(row_value(row, dim) in chosen for dim, chosen in selection.items())


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
            shown = ", ".join(v or t("bench.filter_blank") for v in chosen)
            parts.append(f"{t(DIMENSION_KEYS[dim])}: {shown or '-'}")
    return t("bench.filter_on", parts="; ".join(parts))
