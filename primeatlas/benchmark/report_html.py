"""The interactive part of the Benchmark HTML report: the data its script redraws the charts
from, and the script (report_chart.js). Pure functions, no tkinter.

The page carries every logged run, not only the ones the tab's Filter window keeps: per run
its floor and its value in each filter dimension (chart_filter.py), and per chart the records
of benchmark.benchmark_line_records() -- (run, line, floor, value, width). The script repeats
the charts' reduction in the browser: the runs the page's filter keeps, then the last row per
floor and line, so the page's filter compares runs as the tab's does. The page opens in the
tab's view: filter selection, log scale, references, hidden lines, pinned axes and zoomed
floors. The sieve measure, the pinned axes and the set of report pages stay as exported.
"""
import json
import math
import os
import re

from . import chart_filter, sieve_measure
from .benchmark import benchmark_line_engines, benchmark_line_records, report_references
from .chart_series import axis_pins, engine_series
from .reference_points import reference_series

SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_chart.js")
_FORMAT = re.compile(r"\{:,\.(\d+)f\}")


def decimals(fmt):
    """The decimals of a chart value format "{:,.Nf}", the only form the charts use."""
    m = _FORMAT.fullmatch(fmt)
    if not m:
        raise ValueError(f"unsupported chart value format {fmt!r}")
    return int(m.group(1))


def series_json(s):
    return {"name": s.name, "tag": s.tag, "color": s.color, "dashed": s.dashed,
            "points": [[x, y] for x, y in s.points], "notes": dict(s.notes or {})}


def _floor(row):
    try:
        return int(row.get("base_exponent", ""))
    except (TypeError, ValueError):
        return None


def report_data(rows, pages, t, width, height, selection=None, references=False,
                measure=sieve_measure.DEFAULT, log_y=False, hidden_lines=None, y_pins=None,
                x_view=None, y_views=None, zoom_levels=None, subtitle="", measure_note=""):
    """The JSON-ready data of the page's script. pages: benchmark.report_chart_pages() of
    `rows`; width/height: the chart size in points; subtitle: bench.pdf_subtitle with {runs}
    and {depths} left as placeholders; the other options are the tab's view, as in
    report_export.render(); zoom_levels: the tab's (x level, x base, {chart: y level}), so the
    page zooms on from the tab's notch (chart_view.zoom_step())."""
    x_level, x_base, y_levels = zoom_levels or (0, None, {})
    hidden_lines = hidden_lines or {}
    y_pins = y_pins or {}
    engines = benchmark_line_engines(rows)
    ordered = engine_series({name: [(0, 0)] for name in engines}, engines)
    index = {s.name: i for i, s in enumerate(ordered)}
    dims = []
    for dim in chart_filter.DIMENSIONS:
        values = chart_filter.dimension_values(rows, dim)
        position = {v: i for i, v in enumerate(values)}
        dims.append({"key": dim, "label": t(chart_filter.DIMENSION_KEYS[dim]), "values": values,
                     "of_run": [position[chart_filter.row_value(row, dim)] for row in rows]})
    refs_available = report_references(True, measure)
    out_pages = []
    for kind, charts in pages:
        out_charts = []
        for i, (chart_key, axis, metric, label_key, fmt) in enumerate(charts):
            records = [[run, index[line], floor, value, width_label]
                       for run, line, floor, value, width_label
                       in benchmark_line_records(rows, metric) if math.isfinite(value)]
            out_charts.append({
                "title": t(label_key), "decimals": decimals(fmt),
                "pins": list(axis_pins(y_pins.get(chart_key), axis)),
                "hidden": sorted(name for a, name in hidden_lines.get(chart_key, ()) if a == axis),
                "refs": kind == "sieve" and i == 0 and refs_available,
                "y_view": list((y_views or {}).get(chart_key) or ()) or None,
                "y_level": y_levels.get(chart_key, 0),
                "records": records})
        out_pages.append({"heading": sieve_measure.heading(measure, t) if kind == "sieve" else "",
                          "charts": out_charts})
    text = {key: t(i18n) for key, i18n in (
        ("floor", "bench.axis_floor"), ("pinned", "bench.axis_pinned"),
        ("no_data", "bench.no_data_chart"), ("all_hidden", "bench.all_lines_hidden"),
        ("filter_off", "bench.filter_off"), ("blank", "bench.filter_blank"),
        ("log", "bench.log_scale"), ("refs", "bench.show_references"),
        ("all_runs", "bench.html_all_runs"), ("all_floors", "bench.html_all_floors"),
        ("text_size", "bench.html_text_size"),
        ("hint", "bench.html_hint"))}
    text.update(filter_on=t("bench.filter_on", parts="{parts}"),
                mixed=t("bench.mixed_widths", floors="{floors}"),
                subtitle=subtitle, measure_note=measure_note)
    return {"runs": len(rows), "floor_of_run": [_floor(row) for row in rows], "dims": dims,
            "selection": {dim: sorted(values) for dim, values in (selection or {}).items()},
            "lines": [{"name": s.name, "tag": s.tag, "color": s.color} for s in ordered],
            "refs": [series_json(s) for s in reference_series(t)] if refs_available else [],
            "refs_available": refs_available, "refs_on": bool(references), "log": bool(log_y),
            "view": list(x_view) if x_view is not None else None,
            "x_level": x_level, "x_base": list(x_base) if x_base else None,
            "width": width, "height": height, "pages": out_pages, "text": text}


def data_script(data):
    """The data as a <script type="application/json"> element; "</" is escaped so no value
    can close the element."""
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    return f'<script type="application/json" class="pa-data">{payload}</script>'


def chart_script():
    with open(SCRIPT_PATH, encoding="utf-8") as f:
        return f"<script>{f.read()}</script>"
