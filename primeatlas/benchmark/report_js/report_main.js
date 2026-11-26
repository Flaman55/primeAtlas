/* report_main.js -- the interactive charts of the Benchmark HTML report (report_html.py
joins report_js/ into one script).

The page carries the runs the app's filter kept at export (script.pa-data, JSON) and this script redraws its charts in
the browser: the runs the page's filter keeps, then one point per line and x chosen by the
chart's point choice (the reduction of chart_points.chart_points(): last, min or max value,
the selected run in its own group, or every run; x the floor or log10 of the run's width, a width line per
floor), drawn with the layout of chart_pdf.chart_ops()
ported line by line, so with nothing hidden and no zoom a chart is the SVG the report's Python
side writes (unitTests/test_benchmark_report_html.py compares the two through node).

Gestures as in the Benchmark tab (chart_view.py), zooming like a picture: the mouse wheel over a
chart zooms the part under the pointer on both axes (the floor axis of every chart, the y axis of
that chart), a left drag moves the visible part, a double or middle click shows the whole
charts; a legend entry hides or shows its line. The wheel zooms only over a chart's picture; elsewhere
it scrolls the page. "Chart text" sets the text size: the charts are drawn on a canvas 1/k as
large and shown at their usual width, so text, markers and lines grow k times. The filter (per
dimension All and its values, clicked like the app's: toggleValue(), selectAll()), the x axis
(a change shows the whole charts), each chart's point choice, log scale and reference toggles
redraw the charts, the page headings and the tables (rows of runs the filter
drops are hidden, and so is a column none of the shown runs has a value in -- with a table left
with its key columns alone and its link in the navigation bar -- emptyColumns()). A link to
an anchor inside a closed table section opens it. Chart labels and ticks from a million up
are short (formatCompact(), number_format.compact()); a point's hover title has the exact
value.

Pure parts (scale, labels, reduction, zoom, chart drawing) are exported for node; the page
part runs only in a browser, on the .primeatlas-benchmark element holding this script.
*/
var api = {YScale: YScale, clipPolyline: clipPolyline, placeLabels: placeLabels,
           chartSvg: chartSvg, keptRuns: keptRuns, reduce: reduce, mixedFloors: mixedFloors,
           pick: pick, widthLabel: widthLabel, xLabel: xLabel,
           filterSummary: filterSummary, toggleValue: toggleValue, selectAll: selectAll, zoomStep: zoomStep, pan: pan, tickFloors: tickFloors,
           formatNumber: formatNumber, formatCompact: formatCompact,
           emptyColumns: emptyColumns, shownCharts: shownCharts, controlsHtml: controlsHtml};
if (typeof module === "object" && module.exports) module.exports = api;
if (typeof document !== "undefined" && document.currentScript) {
  var root = document.currentScript.closest(".primeatlas-benchmark");
  var dataEl = root && root.querySelector("script.pa-data");
  if (dataEl) new Report(root, JSON.parse(dataEl.textContent));
}
