# 0007. The interactive HTML report redraws its charts in the browser with a port of chart_ops

Date: 2026-11-05. Status: accepted.

## Context
The Benchmark HTML page and snippet were static: SVG charts of the tab's view. A reader of the
exported page wants what the tab offers: zoom and pan like a picture, lines switched on and off,
the runs filtered by engine build, threads and range width. Filtering changes which row is the last
one per floor and line, so the drawn points cannot be precomputed for every selection, and zoom is
continuous. The page must stay one file with no server, and the snippet must work inside another
page.

## Decision
- The page carries every logged run: its floor and filter values, and per chart the records
  (run, line, floor, value, width) of `benchmark.benchmark_line_records()` (`report_html.py`).
- `report_chart.js`, inlined in the page, repeats the reduction (kept runs, then last row per floor
  and line) and draws each chart with a line-by-line port of `chart_pdf.chart_ops()` and
  `chart_series.YScale`. The Python SVG stays in the page as the view without scripts.
- `unitTests/test_benchmark_report_html.py` runs the script's pure part in node: its reduction gives
  the Series Python computes for several selections, and its chart SVG equals `chart_svg.chart_svg()`
  for linear, log and pinned axes.

## Options rejected
- Toggling elements of the Python SVG with CSS/JS: hiding lines works, but a filter moves points
  (another run becomes the last one) and zoom rescales the axes.
- A charting library from a CDN: the page would need the network, and its charts would no longer
  match the tab and the PDF.

## Consequences
The chart layout has two implementations (Python for PDF/SVG, JS for the page); a layout change to
`chart_ops()` needs the same change in `report_chart.js`, and the parity test fails until both match.
The page grows with the log (a record per run and chart). The sieve measure, the pinned axes and the
set of report pages stay as exported.
