"""Benchmark report formats beside the PDF: CSV, SVG, a standalone HTML page and an HTML
snippet to embed in another page. Pure functions, no tkinter.

All of them follow the Benchmark tab's view like the PDF does: the runs the tab's Filter
window keeps (`selection`, chart_filter.apply() of the log's rows), the report charts of
benchmark.report_chart_pages() (one metric per chart, the sieve in the chosen measure), log
scale, pinned axes, reference series, the lines hidden in the legends and the zoomed floor
range (chart_view.py). The HTML names the filter under its title, the sieve measure over the
sieve charts and, over a page's charts, the floors where they set points of different range
widths. The charts are chart_svg.chart_svg() drawings, the same layout as the PDF's; the
tables are benchmark.benchmark_pdf_tables(), one per question, every cell in full and
HTML-escaped.

  - csv: the kept rows and the log's columns as the tab read them
    (benchmark.read_benchmark_log() adds the D/P "kind" column);
  - svg: every report chart stacked in one SVG image;
  - html: a UTF-8 page with a title, the charts inline and the tables;
  - snippet: the page's content as one <div class="primeatlas-benchmark">, with a style
    whose every rule is scoped to that class, so it can be pasted into another page.

The page and the snippet are interactive (report_html.py, report_chart.js): they carry the
runs the tab's filter keeps, so the filter decides what a page holds (All in every dimension
exports the whole log), and a script redraws the charts with their own filter over those runs
(starting at All, clicked like the tab's), log scale and reference toggles, legend toggles and
the zoom gestures of the tab; the tables hide the rows of the runs the page's filter drops.
Without scripts they show the tab's view as drawn here: the charts and the tables of the kept
runs.
"""
import csv
import datetime
from html import escape

from ..core.i18n import Translator, DEFAULT_LANGUAGE
from . import chart_filter, report_html, sieve_measure, table_cells
from .benchmark import (benchmark_pdf_tables, report_chart_pages, report_chart_series,
                        report_mixed_note, report_references)
from .chart_series import axis_pins
from .chart_svg import chart_svg
from .reference_points import reference_series

KINDS = ("csv", "svg", "html", "snippet")
EXTENSIONS = {"csv": ".csv", "svg": ".svg", "html": ".html", "snippet": ".html"}
CHART_WIDTH = 900
CHART_HEIGHT = 260

_STYLE = """
.primeatlas-benchmark { font-family: sans-serif; color: #111; background: #fff; }
.primeatlas-benchmark h1 { font-size: 1.4em; margin: 0 0 0.2em; }
.primeatlas-benchmark h2 { font-size: 1.1em; margin: 1.2em 0 0.4em; }
.primeatlas-benchmark p { color: #555; margin: 0 0 1em; }
.primeatlas-benchmark svg { display: block; max-width: 100%; height: auto; margin: 0 0 8px; }
.primeatlas-benchmark .tables { overflow-x: auto; }
.primeatlas-benchmark table { border-collapse: collapse; font-size: 12px; }
.primeatlas-benchmark th, .primeatlas-benchmark td { border: 1px solid #ccc; padding: 2px 6px; text-align: right; white-space: nowrap; }
.primeatlas-benchmark th { background: #eee; }
.primeatlas-benchmark .pa-heading:empty { display: none; }
.primeatlas-benchmark .pa-chart { user-select: none; cursor: grab; }
.primeatlas-benchmark .pa-legend { cursor: pointer; }
.primeatlas-benchmark .pa-controls { font-size: 13px; margin: 0 0 1em; }
.primeatlas-benchmark .pa-row { margin: 0 0 4px; }
.primeatlas-benchmark .pa-row label { margin-right: 12px; white-space: nowrap; }
.primeatlas-benchmark .pa-row button { margin-right: 8px; }
.primeatlas-benchmark .pa-dim-name { font-weight: bold; }
.primeatlas-benchmark .pa-hint { font-size: 12px; }
"""


def report_pages_svg(rows, translator=None, sieve_points=None, references=False, log_y=False,
                     hidden_lines=None, y_pins=None, measure=sieve_measure.DEFAULT,
                     x_view=None, y_views=None, pages=None):
    """[(page heading, [<svg> element])] of the report pages, in report order: the heading
    names the sieve measure on the sieve page and the floors of mixed widths, "" otherwise.
    pages: the report_chart_pages() to draw, those of `rows` when omitted."""
    t = (translator or Translator(DEFAULT_LANGUAGE)).t
    y_pins = y_pins or {}
    with_refs = report_references(references, measure)
    if pages is None:
        pages = report_chart_pages(rows, sieve_points, references, measure)
    out = []
    for kind, charts in pages:
        svgs = []
        for i, spec in enumerate(charts):
            chart_key, axis, _metric, label_key, fmt = spec
            extra = reference_series(t) if kind == "sieve" and with_refs and i == 0 else ()
            svgs.append(chart_svg(
                CHART_WIDTH, CHART_HEIGHT,
                series1=report_chart_series(rows, spec, hidden_lines, extra),
                translator=translator, label_key1=label_key, fmt1=fmt, log_y=log_y,
                pins1=axis_pins(y_pins.get(chart_key), axis),
                x_view=x_view, y_view=(y_views or {}).get(chart_key)))
        parts = [sieve_measure.heading(measure, t)] if kind == "sieve" else []
        parts += [note for note in (report_mixed_note(rows, charts, t, x_view),) if note]
        out.append(("  |  ".join(parts), svgs))
    return out


def _svg_report(charts):
    height = CHART_HEIGHT * len(charts)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{CHART_WIDTH}" '
             f'height="{height}" viewBox="0 0 {CHART_WIDTH} {height}">']
    for i, chart in enumerate(charts):
        parts.append(chart.replace("<svg ", f'<svg y="{i * CHART_HEIGHT}" ', 1))
    parts.append("</svg>")
    return "".join(parts)


def _tables_html(fieldnames, rows, t):
    """The tables of `rows` (data-run: a row's index in `rows`, so the page's script hides the
    runs its filter drops); a value a run lacks is table_cells.MISSING."""
    parts = []
    for title_key, columns in benchmark_pdf_tables(fieldnames):
        parts.append(f"<h2>{escape(t(title_key))}</h2><table><thead><tr>"
                     + "".join(f"<th>{escape(c)}</th>" for c in columns)
                     + "</tr></thead><tbody>")
        for i, row in enumerate(rows):
            parts.append(f'<tr data-run="{i}">'
                         + "".join(f"<td>{escape(table_cells.cell(row, c))}</td>"
                                   for c in columns) + "</tr>")
        parts.append("</tbody></table>")
    return "".join(parts)


def _content(fieldnames, rows, selection, t, filter_note, svg_options, data_options):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    kept = chart_filter.apply(rows, selection)
    floors = len({row.get("base_exponent") for row in kept})
    subtitle = t("bench.pdf_subtitle", now=now, runs=len(kept), depths=floors)
    if filter_note:
        subtitle += "  |  " + filter_note
    pages = report_chart_pages(rows, svg_options["sieve_points"], svg_options["references"],
                               svg_options["measure"])
    svg_pages = report_pages_svg(kept, pages=pages, **svg_options)
    data = report_html.report_data(
        kept, pages, t, CHART_WIDTH, CHART_HEIGHT,
        subtitle=t("bench.pdf_subtitle", now=now, runs="{runs}", depths="{depths}"),
        **data_options)
    charts = "".join(
        f'<p class="pa-heading" data-page="{i}">{escape(heading)}</p>'
        + "".join(f'<div class="pa-chart" data-page="{i}" data-chart="{j}">{svg}</div>'
                  for j, svg in enumerate(svgs))
        for i, (heading, svgs) in enumerate(svg_pages))
    return (f'<div class="primeatlas-benchmark"><style>{_STYLE}</style>'
            f"<h1>{escape(t('bench.pdf_title'))}</h1>"
            f'<p class="pa-subtitle">{escape(subtitle)}</p><div class="pa-controls"></div>'
            + charts
            + f'<div class="tables">{_tables_html(fieldnames, kept, t)}</div>'
            + report_html.data_script(data) + report_html.chart_script() + "</div>")


def render(kind, fieldnames, rows, translator=None, sieve_points=None, references=False,
           log_y=False, hidden_lines=None, y_pins=None, filter_note="",
           measure=sieve_measure.DEFAULT, selection=None, x_view=None, y_views=None,
           zoom_levels=None):
    """The report in `kind` (one of KINDS) as text. rows: the log's rows; selection: the
    tab's filter (chart_filter.apply()), None for every run; x_view/y_views: the tab's zoom
    (chart_view.py), None for the whole charts; zoom_levels: their notch levels for the
    interactive page (report_html.report_data())."""
    t = (translator or Translator(DEFAULT_LANGUAGE)).t
    selection = selection or {}
    kept = chart_filter.apply(rows, selection)
    if kind == "csv":
        lines = []

        class _Sink:
            def write(self, text):
                lines.append(text)

        writer = csv.DictWriter(_Sink(), fieldnames=fieldnames, extrasaction="ignore",
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(kept)
        return "".join(lines)
    svg_options = dict(translator=translator, sieve_points=sieve_points, references=references,
                       log_y=log_y, hidden_lines=hidden_lines, y_pins=y_pins, measure=measure,
                       x_view=x_view, y_views=y_views)
    if kind == "svg":
        pages = report_pages_svg(kept, **svg_options)
        return _svg_report([svg for _heading, svgs in pages for svg in svgs])
    sieve_note = sieve_measure.note(measure, t)
    content = _content(fieldnames, rows, selection, t, filter_note, svg_options,
                       dict(references=references, measure=measure, log_y=log_y,
                            hidden_lines=hidden_lines, y_pins=y_pins, x_view=x_view,
                            y_views=y_views, zoom_levels=zoom_levels,
                            measure_note=sieve_note))
    if kind == "snippet":
        return content + "\n"
    if kind == "html":
        return ('<!DOCTYPE html>\n<html><head><meta charset="utf-8">'
                f"<title>{escape(t('bench.pdf_title'))}</title></head>"
                f"<body>{content}</body></html>\n")
    raise ValueError(f"unknown report kind {kind!r}")


def export(kind, path, fieldnames, rows, **options):
    """Writes the report in `kind` to `path` (UTF-8); options: see render()."""
    text = render(kind, fieldnames, rows, **options)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
