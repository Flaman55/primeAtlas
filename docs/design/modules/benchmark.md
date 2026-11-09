# Module: benchmark (Benchmark tab)

Charts of generation speed per floor and engine from `benchmark_log.csv`, a full table of the log, and
a PDF report.

## Files

| Part | Files |
|---|---|
| Tab | `primeatlas/benchmark/benchmark_tab.py` and its mixins `benchmark_filter.py` (Filter window), `benchmark_points.py` (x axis, point choices, selected run), `benchmark_ram_chart.py` (RAM chart), `chart_zoom_controls.py` (zoom and pan), `chart_hover.py` (hover tooltip), `benchmark_chart_windows.py` (a chart in its own window) |
| Exports | `benchmark_export.py` (tab mixin: Save PDF, Export menu), `report_export.py` (CSV, SVG, HTML page, HTML snippet), `report_html.py` + `report_chart.js` (the interactive HTML), `chart_svg.py` (SVG backend of `chart_pdf.chart_ops()`) |
| Backend | `benchmark.py` (reading and normalizing rows, D/P kind, PDF report, `report_chart_pages()`, `benchmark_line_records()`), `line_names.py` (a row's line and charts), `chart_filter.py` (which runs the charts compare), `chart_points.py` (which runs become a chart's points and where they sit on x), `sieve_measure.py` (which time the sieve chart measures), `table_cells.py` (a cell as the tables show it), `chart_view.py` (the zoomed part of a chart), `chart_series.py`, `chart_pdf.py`, `reference_points.py` |

## Contract

| In | Out |
|---|---|
| `benchmark_log.csv` | charts (linear/log, pinned axes, per-line toggles, zoom, own windows), table, PDF, CSV, SVG, interactive HTML page and snippet |

Reads only; the log's header belongs to `prime_sieve/benchmark_log_schema.py`.

Three charts one under another, full width, one line per engine build and thread setup, last row per
floor and line: on top the sieve (sieve n/s, s/window, reference points; the measure below), then the
whole run (`loop_numbers_per_second`, write MB/s), then RAM (`max_child_rss_mb`, the largest process's
peak, and that divided by `windows_written`, so runs of different widths compare). RAM has its own
chart so its megabytes do not share an axis with a speed. Each chart has its hint above it; the page
is taller than the default 1050x680 window and scrolls (ScrollablePage), the table below the charts
10 rows high. Each chart keeps its own hidden lines and pinned axes and names the floors where it
sets points of different widths; the PDF draws the RAM pair on its own page when any row measured it.

A chart line is one engine build on one thread setup (`line_names.line_name()`): the version when
it names the engine (`v6.0`), else the engine label and version, the store kind of P runs, then the
sieve threads (`24 thr`, `2x24 thr` for two instances side by side, `GPU`) and the write threads
(`write 8`). Names are ASCII, the PDF font has no other characters. Rows from before those columns
keep the bare engine name. The color and draw order follow the engine. Last row per floor and line
wins. primesieve rows say how they were measured: `primesieve (Atlas format)` (wrapper, conversion
into Atlas windows in its time), `primesieve count (native)` and `primesieve print (native)` (the
program). A native count sieves the range and counts the bits, the work of an engine's sieve phase:
it is on the sieve charts, its seconds per window over 10^7-number windows. A native print
sieves and outputs every prime with no split between the two, a whole run: it is on the whole-run
chart. Both log the program's peak RAM and write no Atlas windows: they are on RAM per run, not per
window. No static primesieve reference is kept (a figure from another range length misleads:
primesieve's ~0.7 s setup at floor 19 dominates a short range); PARI/GP stays on the sieve chart.
A cell the run leaves empty -- a value its engine does not log, e.g. the per-window time of primesieve's count mode -- shows a dash (`table_cells.MISSING`) in the tab's table and the HTML and PDF tables (folded to "-" in the PDF); the CSV export keeps it empty. The PDF run table lists `engine_version`, `threads` and `write_threads`. A writing row from before
`write_threads` reads `write ?`. Each point names the range it was measured on (`@ 10^11`,
`line_names.width_label()`); on the floor axis a chart can set points of different widths side by
side, and `mixed_width_floors()` lists those floors: the tab shows them under the chart, the PDF
next to the page heading.

Points (`chart_points.py`, `benchmark_points.py`): the runs on the same line and x form a group and
the chart's point choice picks its point -- the last run in log order (default), the lowest or the
highest value of that chart (ties to the later run), the run selected in the tab's table
(`SELECTED`: the selected run's group shows it, the others their last run), or every run (`ALL`:
each its own point in log order, repeated runs one above the other, a point's note joining the
widths of its x). The choice is per chart (whole run, sieve, RAM); the selected run is one for all
three charts: clicking a run in the table switches every chart to `SELECTED` (one on `ALL` keeps
it) and rings the points from that run (`selected_marks()`), since the table sits below the
charts; the Filter window goes back to another choice. The x axis is one for all
charts: the floor (a line per engine build and threads), or log10 of the run's width
(`numbers_processed`; a line per engine build, threads and floor, "v7.1, 24 thr @ f28", the floors
of one engine in shades of its hue, `chart_points.shade()`, dashes staying for the references). On
the width axis a run without a known width has no point and the note under the chart counts those
runs; the mixed-width note is a floor-axis note. Changing the axis shows the whole charts (the zoom
of one axis means nothing on the other); y pins stay. In the table up/down move between runs and
left/right turn the floor's page, selecting its first run. The Filter window sets the axis and the
choices; its summary and the PDF subtitle name them when not the defaults; every export follows
them.

The charts zoom like a picture (`chart_view.py`, `chart_zoom_controls.py`): unzoomed, a chart
shows all of itself, the furthest zoom out; the wheel zooms the part under the pointer on both
axes, a left drag moves the visible part, a double or middle click shows the whole charts. Zoom
goes in notches (`chart_view.zoom_step()`): a level counts them from the whole chart (0) to 18,
and the width is the whole chart's times 0.8 per level, so a notch out undoes a notch in exactly
and as many notches out as in are the whole chart again. The floor axis is shared: one floor
range for the three charts, zoomed from the floors of the chart zoomed first; the floors of all
their points (references included while on) bound its panning. Each chart has its own y view
and level, fractions of its full y scale (pins included), on both of its axes
(`YScale.zoomed()`). Lines run on to the plot edges and are cut there (`clip_polyline()` with x
bounds), so a part between two logged floors shows the line passing through; points outside it
are not drawn, a zoomed floor axis ticks the whole floors in view, and the mixed-width notes
count only the floors in it. A drag can move the view past the data until its far edge reaches
the opposite edge (the last floor at the left edge, the first at the right; the highest value at
the bottom edge, the lowest at the top, `chart_view.data_fracs()` -- a linear scale starts at
zero, and the part below the data is empty), so any part can be centred and the data never leaves
the view on either axis. The canvas bindings return "break", so the wheel over a chart does not
scroll the page. A point's tooltip (`chart_hover.py`) lists every point drawn on the same spot,
so a right-axis square lying on another line's circle can still be read: one line each in its
color, ● left axis, ■ right axis. "Open in new window" above each chart
(`benchmark_chart_windows.py`) opens a resizable window with a second canvas of that chart, raised
instead of doubled on another click; `_draw_chart()` draws both canvases with one state, so zoom,
legend toggles, pins, filter and toggles act on both, and zooming in the window zooms the tab.

The Filter window picks the runs the charts compare (`chart_filter.py`): each dimension -- run
purpose (benchmark or storage, `benchmark_log_schema.row_purpose()`, shown translated), engine
build, sieve threads, write threads, range width -- lists an All checkbox and its values from the
log, all clickable at once. A dimension is at All until a value is clicked: that value alone is
kept, further clicks add or remove values, removing the last one or clicking All goes back to All
(`toggle_value()`, `select_all()`): All or single values, never All minus some. A run stays when
its value is selected in every filtered dimension; the kept runs are then reduced to one point
per line and x (see Points), so one width compares every engine on that width. The floor dimension
lists the floors of the log ("28"), so floors 27-29 alone compare on the width axis.
Changes apply at once;
the summary next to the Filter button and the PDF subtitle name the selection; the PDF tables
and the tab's table list the kept runs (a floor with none is left out; nothing kept shows one
explanatory row), rebuilt on every change. Session only, like the other chart toggles.

Its "Sieve measure" radio (`sieve_measure.py`, with an info tip) sets what the sieve chart and the
PDF's sieve page measure: the engine's sieve phase (`sieve_seconds`, default), the sieve with
startup overhead (`sieve_wall_seconds`), or the overhead alone (the sieve speed the startup
takes: phase n/s minus wall n/s, and on the second axis that as % of the phase n/s). A row
without the time a measure needs has no point on it. A native count (primesieve, Pseudosquares;
`line_names.NATIVE_COUNT_ENGINES`) is timed as one whole process, primesieve's ~0.7 s setup at
floor 19 included: the same time is its point under the
engine phase and the sieve with startup, and it has no point under the overhead (no split
between setup and sieve to measure from outside). PARI/GP references go with those two
measures too. A change clears the chart's y pins; the summary and the PDF subtitle name a measure other than the default, the PDF
sieve page heading always names it.

Reports: `report_chart_pages()` lists the report's charts (one metric each: the whole run, the
sieve in the chosen measure when there is sieve data or the references are on, RAM when a row
measured it), and every format draws them with the tab's view: the runs the Filter window keeps
(charts and tables), the sieve measure, toggles, hidden lines, pins and the zoom. `chart_pdf.chart_ops()` lays a chart out once and
draws through a backend, PDF content ops or SVG elements (`chart_svg.py`, y flipped, Unicode text),
so the PDF and SVG/HTML charts match. The HTML page and the snippet hold the charts inline and the
PDF's logical tables (`benchmark_pdf_tables()`), every cell escaped; the snippet is one
`<div class="primeatlas-benchmark">` whose style rules are all scoped to that class; like the PDF,
the HTML names the filter under the title, the sieve measure over the sieve charts and the floors of
mixed widths over a page's charts (`report_mixed_note()`). CSV writes the kept rows as the tab read
them (with the D/P `kind` column).

The HTML page and snippet are interactive (`report_html.py`, `report_chart.js`, ADR 0007, 0008). They
carry the runs the tab's filter keeps (All everywhere exports the whole log): per run its floor and
filter values (with the tab's labels), and per chart the records of `benchmark_line_records()`
(run, line, floor, value, width, log10 of the width); the tables list those runs. The script
repeats the reduction in the browser -- the runs its filter keeps, then one point per line and x
by the chart's point choice -- and redraws with a port of `chart_ops()`; it starts from the tab's
view (log scale, references, hidden lines, pins, zoom, x axis, point choices, the selected run)
with its own filter at All, and has its own x axis and point choice selectors (`width_lines` names
and shades the width-axis lines as the tab does).
The page has the Filter window's dimensions, clicked like the tab's
(All or single values, `toggleValue()`/`selectAll()`), log scale and reference toggles, "All runs" and
"All floors", a chart text size (100-200 %, the chart drawn on a canvas 1/k as large and shown at
its usual width), legend toggles per chart and the tab's zoom gestures over all charts at once,
taken only over a chart's picture (the wheel beside it scrolls the page); the
headings and the subtitle follow, and the tables hide the rows of dropped runs. The sieve measure,
pins and the set of pages stay as exported. Without scripts the page shows the tab's view as
exported (the Python SVG, the kept rows).

## Parameters and texts

Texts `bench.*`, `pdf.*`.

## Kept data

None of its own.

## Specs and tests

`test_benchmark_tab`, `test_benchmark_chart_series`, `test_benchmark_report_export`,
`test_benchmark_report_html` (the script through node), `test_benchmark_chart_zoom`,
`test_benchmark_chart_windows`,
`test_benchmark_actual_range`,
`test_benchmark_run_status`, `test_benchmark_main_compatibility`, `test_benchmark_log_schema`,
`test_benchmark_line_names`, `test_benchmark_auto_reload`, `test_benchmark_filter`,
`test_benchmark_sieve_measure`; `test_orchestrator_sieve_wall` (prime-sieve).

## Known gaps

- `benchmark_tab.py` has 799 lines; a fourth chart needs the three redraw methods folded into
  one chart table first.
- The chart layout exists twice, `chart_pdf.chart_ops()` and its port in `report_chart.js`; the
  parity test in `test_benchmark_report_html` holds them together (ADR 0007).
- Primesieve and cudasieve rows log no RAM, so they have no RAM points.
