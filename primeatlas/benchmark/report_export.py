"""Benchmark report formats beside the PDF: CSV, SVG, a standalone HTML page and an HTML
snippet to embed in another page. Pure functions, no tkinter.

All of them follow the Benchmark tab's view like the PDF does: the report charts of
benchmark.report_chart_pages() (one metric per chart), log scale, pinned axes, reference
series, the lines hidden in the legends and the zoomed floor range (the CSV keeps every
row). The charts are chart_svg.chart_svg() drawings,
the same layout as the PDF's; the tables are benchmark.benchmark_pdf_tables(), one per
question, every cell in full and HTML-escaped.

  - csv: the log's rows and columns as the tab read them (benchmark.read_benchmark_log()
    adds the D/P "kind" column);
  - svg: every report chart stacked in one SVG image;
  - html: a UTF-8 page with a title, the charts inline and the tables;
  - snippet: the page's content as one <div class="primeatlas-benchmark">, with a style
    whose every rule is scoped to that class, so it can be pasted into another page.
"""
import csv
import datetime
from html import escape

from ..core.i18n import Translator, DEFAULT_LANGUAGE
from .benchmark import benchmark_pdf_tables, report_chart_pages, report_chart_series
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
"""


def report_charts_svg(rows, translator=None, sieve_points=None, references=False, log_y=False,
                      hidden_lines=None, y_pins=None, x_view=None):
    """[<svg> element] of every report chart, in report order."""
    t = (translator or Translator(DEFAULT_LANGUAGE)).t
    y_pins = y_pins or {}
    out = []
    for kind, charts in report_chart_pages(rows, sieve_points, references):
        for i, spec in enumerate(charts):
            chart_key, axis, _metric, label_key, fmt = spec
            extra = reference_series(t) if kind == "sieve" and references and i == 0 else ()
            out.append(chart_svg(
                CHART_WIDTH, CHART_HEIGHT,
                series1=report_chart_series(rows, spec, hidden_lines, extra, x_view),
                translator=translator, label_key1=label_key, fmt1=fmt, log_y=log_y,
                pins1=axis_pins(y_pins.get(chart_key), axis)))
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
    parts = []
    for title_key, columns in benchmark_pdf_tables(fieldnames):
        parts.append(f"<h2>{escape(t(title_key))}</h2><table><thead><tr>"
                     + "".join(f"<th>{escape(c)}</th>" for c in columns)
                     + "</tr></thead><tbody>")
        for row in rows:
            parts.append("<tr>" + "".join(f"<td>{escape(str(row.get(c, '') or ''))}</td>"
                                           for c in columns) + "</tr>")
        parts.append("</tbody></table>")
    return "".join(parts)


def _content(fieldnames, rows, t, charts):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    floors = len({row.get("base_exponent") for row in rows})
    return (f'<div class="primeatlas-benchmark"><style>{_STYLE}</style>'
            f"<h1>{escape(t('bench.pdf_title'))}</h1>"
            f"<p>{escape(t('bench.pdf_subtitle', now=now, runs=len(rows), depths=floors))}</p>"
            + "".join(charts)
            + f'<div class="tables">{_tables_html(fieldnames, rows, t)}</div></div>')


def render(kind, fieldnames, rows, translator=None, sieve_points=None, references=False,
           log_y=False, hidden_lines=None, y_pins=None, x_view=None):
    """The report in `kind` (one of KINDS) as text."""
    t = (translator or Translator(DEFAULT_LANGUAGE)).t
    if kind == "csv":
        lines = []

        class _Sink:
            def write(self, text):
                lines.append(text)

        writer = csv.DictWriter(_Sink(), fieldnames=fieldnames, extrasaction="ignore",
                                lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        return "".join(lines)
    charts = report_charts_svg(rows, translator, sieve_points, references, log_y,
                               hidden_lines, y_pins, x_view)
    if kind == "svg":
        return _svg_report(charts)
    content = _content(fieldnames, rows, t, charts)
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
