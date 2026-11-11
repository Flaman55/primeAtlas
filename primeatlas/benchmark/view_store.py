"""The Benchmark tab's view kept across restarts, as one JSON value under KEY in the
remembered-fields store (ui_state_dynamic.STORE): the Filter window's selection, the sieve
measure, the x axis, each chart's point choice and the lines hidden from each chart's legend.

The selected run is not kept, so a chart on SELECTED is saved as its choice from before the
selection (LAST when none). load() checks every part on its own: a part of the wrong type or
naming an unknown dimension, measure, x axis, chart or choice falls back to its default and
leaves the other parts as saved. prune() drops the filter values the log no longer holds
(a dimension left with none is at All), so a stale value cannot empty the charts.
No tkinter here.
"""
from . import chart_filter, chart_points, sieve_measure

KEY = "benchmark.view"
CHARTS = ("run", "sieve", "ram")
_AXES = ("primary", "secondary")


def save(store, selection, measure, x_mode, choices, choices_before_select, hidden):
    store.set(KEY, {
        "selection": {dim: sorted(values) for dim, values in selection.items()},
        "measure": measure,
        "x_mode": x_mode,
        "choices": {chart: choices_before_select.get(chart, chart_points.LAST)
                    if choice == chart_points.SELECTED else choice
                    for chart, choice in choices.items()},
        "hidden": {chart: sorted([axis, name] for axis, name in keys)
                   for chart, keys in hidden.items()},
    })


def _part(saved, name):
    return saved.get(name) if isinstance(saved, dict) else None


def _selection(value):
    if not isinstance(value, dict):
        return {}
    return {dim: set(values) for dim, values in value.items()
            if dim in chart_filter.DIMENSIONS and isinstance(values, list) and values
            and all(isinstance(v, str) for v in values)}


def _choices(value):
    value = value if isinstance(value, dict) else {}
    usable = set(chart_points.CHOICES) - {chart_points.SELECTED}
    return {chart: value[chart] if value.get(chart) in usable else chart_points.LAST
            for chart in CHARTS}


def _hidden(value):
    value = value if isinstance(value, dict) else {}
    result = {}
    for chart in CHARTS:
        keys = value.get(chart)
        keys = keys if isinstance(keys, list) else []
        result[chart] = {(k[0], k[1]) for k in keys
                         if isinstance(k, list) and len(k) == 2 and k[0] in _AXES
                         and isinstance(k[1], str)}
    return result


def load(store):
    """{selection, measure, x_mode, choices, hidden} as saved, each part checked."""
    saved = store.get(KEY)
    measure = _part(saved, "measure")
    x_mode = _part(saved, "x_mode")
    return {"selection": _selection(_part(saved, "selection")),
            "measure": measure if measure in sieve_measure.MEASURES else sieve_measure.DEFAULT,
            "x_mode": x_mode if x_mode in chart_points.X_MODES else chart_points.X_FLOOR,
            "choices": _choices(_part(saved, "choices")),
            "hidden": _hidden(_part(saved, "hidden"))}


def prune(selection, rows):
    """`selection` without the values `rows` do not hold; a dimension left empty is dropped."""
    result = {}
    for dim, values in selection.items():
        kept = set(values) & set(chart_filter.dimension_values(rows, dim))
        if kept:
            result[dim] = kept
    return result
