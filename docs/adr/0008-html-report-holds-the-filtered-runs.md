# 0008. The HTML report holds the runs the tab's filter keeps

Date: 2026-11-08. Status: accepted. Amends [0007](0007-interactive-html-report.md) (what the page
carries).

## Context
The interactive page carried every logged run and opened with the tab's selection, so an export
always held the whole log, whatever the Filter window showed. A log now holds two kinds of runs
(benchmark runs that only measure, storage runs), and a reader may want a page of one kind only.
The Filter window works as All or single values in every dimension.

## Decision
- `report_export` passes the page only the runs the tab's filter keeps (`chart_filter.apply()`);
  its tables list exactly those runs. All in every dimension exports the whole log.
- The page's own filter starts at All over the exported runs and is clicked like the tab's (All or
  single values: `toggleValue()`/`selectAll()` in `report_chart.js`, matching
  `chart_filter.toggle_value()`/`select_all()`, checked through node); the subtitle still names the
  tab's filter.

## Options rejected
- Keep every run and only start the page at the tab's selection: the filter could not limit what an
  exported file contains.

## Consequences
A page filtered at export cannot show the runs left out; exporting again with All brings them back.
The page is as large as the kept runs, not the whole log.
