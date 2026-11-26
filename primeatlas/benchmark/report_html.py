"""The interactive part of the Benchmark HTML report: the data its script redraws the charts
from, and the script (the parts in report_js/, joined into one). Pure functions, no tkinter.

The page carries the runs it is given -- report_export passes the ones the tab's Filter
window keeps: per run its floor and its value in each filter dimension (chart_filter.py, with
the label the tab shows), and per chart the records of benchmark.benchmark_line_records() --
(run, line, floor, value, width, log10 of the width or None). The script repeats the charts'
reduction in the browser (chart_points.py): the runs the page's filter keeps, then one point
per line and x chosen by the chart's point choice, so the page's filter compares runs as the
tab's does, with the same clicks (All or single values, chart_filter.toggle_value()/
select_all()). The page opens in the tab's view: log scale, references, hidden lines, pinned
axes, zoomed x range, the x axis (floor or width) and each chart's point choice; the run
selected in the tab's table stays the selected run. The page holds what the tab shows: a line
hidden in the tab is not in its data (on the width axis only its hidden floor), nor are the
reference series when the tab has them off. On the width axis a line is a line of the
floor axis on one floor, named and shaded as benchmark.benchmark_series() does (width_lines).
The sieve measure, the pinned axes and the set of report pages stay as exported.
"""
import json
import math
import os

from ..core import number_format, number_format_dynamic
from . import chart_filter, sieve_measure
from . import chart_points
from . import line_colors, line_names, proof_rows
from .benchmark import (benchmark_line_engines, benchmark_line_records, report_references,
                        width_floors)
from .chart_series import axis_pins, engine_series, is_hidden
from .reference_points import reference_series

X_MODE_LABEL_KEYS = {chart_points.X_FLOOR: "bench.x_axis_floor",
                     chart_points.X_WIDTH: "bench.x_axis_width"}
CHART_NAME_KEYS = {"run": "bench.chart_name_run", "sieve": "bench.chart_name_sieve",
                   "ram": "bench.chart_name_ram"}
SCRIPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_js")
# The script's parts in join order; they share one function scope, and report_main.js, which
# starts the page, comes last so every value it reaches is set.
SCRIPT_PARTS = ("report_format.js", "report_scale.js", "report_svg.js", "report_runs.js",
                "report_view.js", "report_controls.js", "report_page.js", "report_main.js")


def number_marks():
    """{group, mark}: the digit group separator and decimal mark of the app's notation,
    with which the script writes the charts' numbers."""
    group, mark = number_format.STYLES.get(number_format_dynamic.STYLE,
                                           number_format.STYLES[number_format.DEFAULT_STYLE])
    return {"group": group, "mark": mark}


def _js_key(x):
    """x as JavaScript names a number used as an object key: 10, 11.301029995663981."""
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def series_json(s):
    return {"name": s.name, "tag": s.tag, "color": s.color, "dashed": s.dashed,
            "points": [[x, y] for x, y in s.points],
            "notes": {_js_key(x): note for x, note in (s.notes or {}).items()}}


def _floor(row):
    try:
        return int(row.get("base_exponent", ""))
    except (TypeError, ValueError):
        return None


def report_data(rows, pages, t, width, height, selection=None, references=False,
                measure=sieve_measure.DEFAULT, log_y=False, hidden_lines=None, y_pins=None,
                x_view=None, y_views=None, zoom_levels=None, subtitle="", measure_note="",
                point_views=None):
    """The JSON-ready data of the page's script. pages: benchmark.report_chart_pages() of
    `rows`; width/height: the chart size in points; subtitle: bench.pdf_subtitle with {runs}
    and {depths} left as placeholders; the other options are the tab's view, as in
    report_export.render(); zoom_levels: the tab's (x level, x base, {chart: y level}), so the
    page zooms on from the tab's notch (chart_view.zoom_step()); point_views: {"run" | "sieve"
    | "ram": chart_points.PointView}, the tab's x axis, point choices and selected run."""
    x_level, x_base, y_levels = zoom_levels or (0, None, {})
    hidden_lines = hidden_lines or {}
    y_pins = y_pins or {}
    point_views = point_views or {}
    views = [point_views.get(key) or chart_points.DEFAULT for key in ("run", "sieve", "ram")]
    x_mode = views[0].x_mode
    selected = next((v.selected for v in views if v.selected is not None), None)
    refs_on = report_references(references, measure)
    refs = [s for s in (reference_series(t) if refs_on else ())
            if not is_hidden(hidden_lines.get("sieve"), "primary", s.name)]
    charts_records = [[_shown_records(rows, spec, hidden_lines.get(spec[0]),
                                      dict(zip(("run", "sieve", "ram"), views))[spec[0]])
                       for spec in charts] for _kind, charts in pages]
    shown = {record[1] for charts in charts_records for records in charts
             for record in records}
    engines = {name: key for name, key in benchmark_line_engines(rows).items() if name in shown}
    ordered = engine_series({name: [(0, 0)] for name in engines}, engines,
                            theme=line_colors.EXPORT_THEME)
    index = {s.name: i for i, s in enumerate(ordered)}
    dims = []
    for dim in chart_filter.DIMENSIONS:
        values = chart_filter.dimension_values(rows, dim)
        position = {v: i for i, v in enumerate(values)}
        dims.append({"key": dim, "label": t(chart_filter.DIMENSION_KEYS[dim]), "values": values,
                     "labels": [chart_filter.value_label(dim, v, t) for v in values],
                     "of_run": [position[chart_filter.row_value(row, dim)] for row in rows]})
    width_lines = _width_lines(rows, ordered, index,
                               {(index[r[1]], r[2]) for charts in charts_records
                                for records in charts for r in records})
    out_pages = []
    for (kind, charts), records_of in zip(pages, charts_records):
        out_charts = []
        for i, ((chart_key, axis, metric, label_key, places), shown_records) in enumerate(
                zip(charts, records_of)):
            records = [[run, index[line], floor, value, width_label,
                        math.log10(numbers) if numbers else None]
                       for run, line, floor, value, width_label, numbers in shown_records]
            out_charts.append({
                "title": t(label_key), "decimals": places,
                "pins": list(axis_pins(y_pins.get(chart_key), axis)),
                "refs": kind == "sieve" and i == 0 and bool(refs),
                "y_view": list((y_views or {}).get(chart_key) or ()) or None,
                "y_level": y_levels.get(chart_key, 0), "key": chart_key,
                "records": records})
        out_pages.append({"heading": sieve_measure.heading(measure, t) if kind == "sieve" else "",
                          "charts": out_charts})
    text = {key: t(i18n) for key, i18n in (
        ("floor", "bench.axis_floor"), ("width", "bench.axis_width"),
        ("x_axis", "bench.x_axis_title"), ("point", "bench.point_title"),
        ("pinned", "bench.axis_pinned"),
        ("no_data", "bench.no_data_chart"), ("all_hidden", "bench.all_lines_hidden"),
        ("filter_off", "bench.filter_off"), ("blank", "bench.filter_blank"),
        ("all", "bench.filter_all"),
        ("log", "bench.log_scale"), ("refs", "bench.show_references"),
        ("all_runs", "bench.html_all_runs"), ("all_floors", "bench.html_all_floors"),
        ("text_size", "bench.html_text_size"),
        ("hint", "bench.html_hint"))}
    text.update({"x_" + mode: t(key) for mode, key in X_MODE_LABEL_KEYS.items()})
    text.update({"point_" + c: t(key) for c, key in chart_points.CHOICE_LABEL_KEYS.items()})
    text.update({"chart_" + key: t(i18n) for key, i18n in CHART_NAME_KEYS.items()})
    text.update(filter_on=t("bench.filter_on", parts="{parts}"),
                mixed=t("bench.mixed_widths", floors="{floors}"),
                subtitle=subtitle, measure_note=measure_note)
    return {"runs": len(rows), "floor_of_run": [_floor(row) for row in rows], "dims": dims,
            "selection": {dim: sorted(values) for dim, values in (selection or {}).items()},
            "lines": [{"name": s.name, "tag": s.tag, "color": s.color} for s in ordered],
            "refs": [series_json(s) for s in refs],
            "refs_available": bool(refs), "refs_on": bool(refs), "log": bool(log_y),
            "view": list(x_view) if x_view is not None else None,
            "x_level": x_level, "x_base": list(x_base) if x_base else None,
            "width": width, "height": height, "pages": out_pages, "text": text,
            "number_marks": number_marks(),
            "x_mode": x_mode, "width_lines": width_lines,
            "choices": {key: view.choice for key, view in zip(("run", "sieve", "ram"), views)},
            "selected_run": next((i for i, row in enumerate(rows) if row is selected), None)}


def _shown_records(rows, chart, hidden, view):
    """benchmark_line_records() of one report chart without the lines hidden in the tab: on
    the width axis a line is one floor of a floor-axis line (chart_points.line_name())."""
    chart_key, axis, metric = chart[:3]
    width = view.x_mode == chart_points.X_WIDTH
    return [record for record in benchmark_line_records(rows, metric)
            if math.isfinite(record[3]) and not is_hidden(
                hidden, axis, record[1] + chart_points.floor_suffix(record[2]) if width
                else record[1])]


def _width_lines(rows, ordered, index, shown):
    """{"line index/floor": {name, color}}: each floor-axis line on each floor with a known
    width among `shown` ({(line index, floor)} the page's records hold), named and shaded as
    on the tab's width axis (benchmark.benchmark_series())."""
    floors = width_floors(rows)
    out = {}
    for row in proof_rows.chart_rows(rows):
        floor = chart_points.floor_of(row)
        name = line_names.line_name(row)
        if (floor is None or chart_points.numbers_of(row) is None
                or (index.get(name), floor) not in shown):
            continue
        s = ordered[index[name]]
        out[f"{index[s.name]}/{floor}"] = {
            "name": chart_points.line_name(row, chart_points.X_WIDTH),
            "color": chart_points.shade(s.color, floors[s.engine].index(floor))}
    return out


def data_script(data):
    """The data as a <script type="application/json"> element; "</" is escaped so no value
    can close the element."""
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    return f'<script type="application/json" class="pa-data">{payload}</script>'


def chart_source():
    """The script: the parts of SCRIPT_PARTS in one function wrapper, so their names stay out
    of the page's global scope."""
    parts = []
    for name in SCRIPT_PARTS:
        with open(os.path.join(SCRIPT_DIR, name), encoding="utf-8") as f:
            parts.append(f.read())
    return '(function () {\n"use strict";\n' + "\n".join(parts) + "})();\n"


def chart_script():
    return f"<script>{chart_source()}</script>"
