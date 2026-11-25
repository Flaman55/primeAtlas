"""Benchmark report formats beside the PDF: CSV, SVG, a standalone HTML page and an HTML
snippet to embed in another page. Pure functions, no tkinter.

All of them follow the Benchmark tab's view like the PDF does: the runs the tab's Filter
window keeps (`selection`, chart_filter.apply() of the log's rows), the report charts of
benchmark.report_chart_pages() (one metric per chart, the sieve in the chosen measure), log
scale, pinned axes, reference series, the lines hidden in the legends and the zoomed floor
range (chart_view.py). The HTML names the filter under its title, the sieve measure over the
sieve charts and, over a page's charts, the floors where they set points of different range
widths. The charts are chart_svg.chart_svg() drawings, the same layout as the PDF's, without
a chart no kept run sets a point on (benchmark.report_drawn_pages()); the tables are the
tab's run table (table_columns.report_tables() of the kept runs: no column no run has a value
in, no table left with only its key columns) in its four groups, each led by the floor, the
run and the engine, with the tab's headers, every cell in full and HTML-escaped. A run's
computer cell links to its computer in the "Computers" section after the tables
(computer_table.py: a table per computer of the kept runs, from `machines`), which a page
without a computer leaves out.

The page reads top down: the title, the subtitle, a navigation bar linking the charts and
each table and section the page holds, the charts, then each table and the Computers section
as a <details> closed by default, its title in the <summary>. Every id starts with "pa-", so
a snippet pasted into another page keeps clear of that page's ids.

  - csv: the kept runs in the run table's columns (table_columns.EXPORT_COLUMNS: the floor,
    the run, then the tab's columns), column keys as the header and raw values (an empty
    cell for a value the run lacks); benchmark_log.csv itself keeps every logged column;
    export() also writes <name>_computers.csv beside it (computer_table.computers_csv());
  - svg: every report chart stacked in one SVG image;
  - html: a UTF-8 page with a title, the charts inline and the tables;
  - snippet: the page's content as one <div class="primeatlas-benchmark">, with a style
    whose every rule is scoped to that class, so it can be pasted into another page.

The page and the snippet are interactive (report_html.py, report_js/): they carry the
runs the tab's filter keeps, so the filter decides what a page holds (All in every dimension
exports the whole log), and a script redraws the charts with their own filter over those runs
(starting at All, clicked like the tab's), log scale and reference toggles, legend toggles and
the zoom gestures of the tab; the tables hide the rows of the runs the page's filter drops.
Without scripts they show the tab's view as drawn here: the charts and the tables of the kept
runs.
"""
import csv
import datetime
import os
from html import escape

from ..core.i18n import Translator, DEFAULT_LANGUAGE
from . import (chart_filter, chart_points, computer_table, report_html, sieve_measure,
               table_cells, table_columns)
from .benchmark import (report_chart_pages, report_chart_series, report_drawn_pages,
                        report_mixed_note, report_references)
from .chart_series import axis_pins
from .chart_svg import chart_svg
from .reference_points import reference_series

KINDS = ("csv", "svg", "html", "snippet")
EXTENSIONS = {"csv": ".csv", "svg": ".svg", "html": ".html", "snippet": ".html"}
CHART_WIDTH = 900
CHART_HEIGHT = 260

# The <details> id of a report table, from its title key.
SECTION_IDS = {"bench.pdf_table_speed": "pa-table-speed", "bench.pdf_table_run": "pa-table-run",
               "bench.pdf_table_phases": "pa-table-phases",
               "bench.pdf_table_results": "pa-table-results"}
NAV_KEYS = {"bench.pdf_table_speed": "bench.report_nav_speed",
            "bench.pdf_table_run": "bench.report_nav_run",
            "bench.pdf_table_phases": "bench.report_nav_phases",
            "bench.pdf_table_results": "bench.report_nav_results"}
CHARTS_ID = "pa-charts"
COMPUTERS_ID = "pa-computers"

_STYLE = """
.primeatlas-benchmark { font-family: sans-serif; color: #111; background: #fff; }
.primeatlas-benchmark .pa-nav { font-size: 13px; margin: 0 0 1em; }
.primeatlas-benchmark .pa-nav a { margin-right: 14px; white-space: nowrap; }
.primeatlas-benchmark .pa-section { margin: 0.6em 0; }
.primeatlas-benchmark .pa-section > summary { cursor: pointer; }
.primeatlas-benchmark .pa-section > summary h2 { display: inline; }
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


def section_id(title_key):
    """The anchor of the report table titled `title_key`."""
    return SECTION_IDS[title_key]


def report_pages_svg(rows, translator=None, sieve_points=None, references=False, log_y=False,
                     hidden_lines=None, y_pins=None, measure=sieve_measure.DEFAULT,
                     x_view=None, y_views=None, pages=None, point_views=None):
    """[(page heading, [<svg> element])] of the report pages, in report order: the heading
    names the sieve measure on the sieve page and the floors of mixed widths, "" otherwise.
    pages: the pages to draw, report_drawn_pages() of `rows` when omitted; point_views: as
    in benchmark.render_benchmark_pdf()."""
    t = (translator or Translator(DEFAULT_LANGUAGE)).t
    y_pins = y_pins or {}
    point_views = point_views or {}
    with_refs = report_references(references, measure)
    if pages is None:
        pages = report_drawn_pages(rows, report_chart_pages(rows, sieve_points, references,
                                                            measure),
                                   references, measure, point_views)
    out = []
    for kind, charts in pages:
        svgs = []
        for i, spec in enumerate(charts):
            chart_key, axis, _metric, label_key, places = spec
            extra = reference_series(t) if kind == "sieve" and with_refs and i == 0 else ()
            svgs.append(chart_svg(
                CHART_WIDTH, CHART_HEIGHT,
                series1=report_chart_series(rows, spec, hidden_lines, extra, point_views),
                translator=translator, label_key1=label_key, places1=places, log_y=log_y,
                pins1=axis_pins(y_pins.get(chart_key), axis),
                x_view=x_view, y_view=(y_views or {}).get(chart_key),
                x_mode=(point_views.get(chart_key) or chart_points.DEFAULT).x_mode))
        parts = [sieve_measure.heading(measure, t)] if kind == "sieve" else []
        parts += [note for note in (report_mixed_note(rows, charts, t, x_view, point_views),) if note]
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


def _computer_id(machine_id):
    return "pa-" + computer_table.anchor(machine_id)


def _cell_html(row, column, t):
    """A table cell; a value the run lacks is marked pa-none for the page's script."""
    shown = table_columns.shown(row, column, t)
    if shown == table_cells.MISSING:
        return f'<td class="pa-none">{escape(shown)}</td>'
    text = escape(shown)
    machine_id = str(row.get("machine_id") or "").strip()
    if column == "machine" and machine_id:
        text = f'<a href="#{_computer_id(machine_id)}">{text}</a>'
    return f"<td>{text}</td>"


def _section(section_id, title, body):
    return (f'<details class="pa-section" id="{section_id}"><summary><h2>{escape(title)}'
            f"</h2></summary>{body}</details>")


def _computers_html(rows, machines, t):
    """The Computers section: a table per computer of `rows`, under its anchor; "" when no
    run has a computer."""
    machine_ids = computer_table.computers_in(rows)
    if not machine_ids:
        return ""
    parts = []
    for machine_id in machine_ids:
        history = machines.get(machine_id) or []
        parts.append(f'<h3 id="{_computer_id(machine_id)}">'
                     f"{escape(computer_table.heading(machine_id, history, t))}</h3>")
        shown = computer_table.table(history, t)
        if shown is None:
            parts.append(f"<p>{escape(t('computer.no_data'))}</p>")
            continue
        headers, body = shown
        parts.append("<table><thead><tr>" + "".join(f"<th>{escape(h)}</th>" for h in headers)
                     + "</tr></thead><tbody>"
                     + "".join("<tr>" + "".join(f"<td>{escape(v)}</td>" for v in line)
                               + "</tr>" for line in body)
                     + "</tbody></table>")
    return _section(COMPUTERS_ID, t("computer.section_title"), "".join(parts))


def _tables_html(tables, rows, t):
    """The `tables` (table_columns.report_tables()) of `rows`, each in its section (data-run: a
    row's index in `rows`, so the page's script hides the runs its filter drops; data-keys:
    the key columns, which the script never hides); a value a run lacks is
    table_cells.MISSING."""
    parts = []
    for title_key, columns in tables:
        body = [f'<table data-keys="{len(table_columns.KEY_COLUMNS)}"><thead><tr>'
                + "".join(f"<th>{escape(t(table_columns.header_key(c)))}</th>"
                          for c in columns)
                + "</tr></thead><tbody>"]
        for i, row in enumerate(rows):
            body.append(f'<tr data-run="{i}">' + "".join(_cell_html(row, c, t) for c in columns)
                        + "</tr>")
        body.append("</tbody></table>")
        parts.append(_section(section_id(title_key), t(title_key), "".join(body)))
    return "".join(parts)


def _nav_html(tables, computers, t):
    """The navigation bar: the charts, each table of `tables`, the Computers section when
    the page has one."""
    links = [(CHARTS_ID, t("bench.report_nav_charts"))]
    links += [(section_id(key), t(NAV_KEYS[key])) for key, _columns in tables]
    if computers:
        links.append((COMPUTERS_ID, t("computer.section_title")))
    return ('<nav class="pa-nav">'
            + "".join(f'<a href="#{target}">{escape(label)}</a>' for target, label in links)
            + "</nav>")


def _content(fieldnames, rows, selection, t, filter_note, svg_options, data_options,
             machines):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    kept = chart_filter.apply(rows, selection)
    floors = len({row.get("base_exponent") for row in kept})
    subtitle = t("bench.pdf_subtitle", now=now, runs=len(kept), depths=floors)
    if filter_note:
        subtitle += "  |  " + filter_note
    pages = report_drawn_pages(kept, report_chart_pages(rows, svg_options["sieve_points"],
                                                        svg_options["references"],
                                                        svg_options["measure"]),
                               svg_options["references"], svg_options["measure"],
                               svg_options["point_views"])
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
    tables = table_columns.report_tables(kept)
    computers = _computers_html(kept, machines, t)
    return (f'<div class="primeatlas-benchmark"><style>{_STYLE}</style>'
            f"<h1>{escape(t('bench.pdf_title'))}</h1>"
            f'<p class="pa-subtitle">{escape(subtitle)}</p>'
            + _nav_html(tables, computers, t)
            + f'<div class="pa-controls"></div><div id="{CHARTS_ID}">{charts}</div>'
            + f'<div class="tables">{_tables_html(tables, kept, t)}{computers}</div>'
            + report_html.data_script(data) + report_html.chart_script() + "</div>")


def render(kind, fieldnames, rows, translator=None, sieve_points=None, references=False,
           log_y=False, hidden_lines=None, y_pins=None, filter_note="",
           measure=sieve_measure.DEFAULT, selection=None, x_view=None, y_views=None,
           zoom_levels=None, point_views=None, machines=None):
    """The report in `kind` (one of KINDS) as text. rows: the log's rows; selection: the
    tab's filter (chart_filter.apply()), None for every run; x_view/y_views: the tab's zoom
    (chart_view.py), None for the whole charts; zoom_levels: their notch levels for the
    interactive page (report_html.report_data()); point_views: the tab's x axis and point
    choices (benchmark.render_benchmark_pdf()); machines: machines_file.load() for the
    Computers section, None for none."""
    t = (translator or Translator(DEFAULT_LANGUAGE)).t
    selection = selection or {}
    kept = chart_filter.apply(rows, selection)
    if kind == "csv":
        lines = []

        class _Sink:
            def write(self, text):
                lines.append(text)

        writer = csv.writer(_Sink(), lineterminator="\n")
        writer.writerow(table_columns.EXPORT_COLUMNS)
        writer.writerows([table_columns.raw(row, c) for c in table_columns.EXPORT_COLUMNS]
                         for row in kept)
        return "".join(lines)
    svg_options = dict(translator=translator, sieve_points=sieve_points, references=references,
                       log_y=log_y, hidden_lines=hidden_lines, y_pins=y_pins, measure=measure,
                       x_view=x_view, y_views=y_views, point_views=point_views)
    if kind == "svg":
        pages = report_pages_svg(kept, **svg_options)
        return _svg_report([svg for _heading, svgs in pages for svg in svgs])
    sieve_note = sieve_measure.note(measure, t)
    content = _content(fieldnames, rows, selection, t, filter_note, svg_options,
                       dict(references=references, measure=measure, log_y=log_y,
                            hidden_lines=hidden_lines, y_pins=y_pins, x_view=x_view,
                            y_views=y_views, zoom_levels=zoom_levels, point_views=point_views,
                            measure_note=sieve_note), machines or {})
    if kind == "snippet":
        return content + "\n"
    if kind == "html":
        return ('<!DOCTYPE html>\n<html><head><meta charset="utf-8">'
                f"<title>{escape(t('bench.pdf_title'))}</title></head>"
                f"<body>{content}</body></html>\n")
    raise ValueError(f"unknown report kind {kind!r}")


def computers_path(path):
    stem, extension = os.path.splitext(path)
    return f"{stem}_computers{extension or '.csv'}"


def export(kind, path, fieldnames, rows, **options):
    """Writes the report in `kind` to `path` (UTF-8), for csv also the computers of the kept
    runs to computers_path(); returns the written paths. options: see render()."""
    text = render(kind, fieldnames, rows, **options)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    if kind != "csv":
        return [path]
    kept = chart_filter.apply(rows, options.get("selection") or {})
    second = computers_path(path)
    with open(second, "w", encoding="utf-8", newline="") as f:
        f.write(computer_table.computers_csv(computer_table.computers_in(kept),
                                             options.get("machines") or {}))
    return [path, second]
