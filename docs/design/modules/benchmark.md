# Module: benchmark (Benchmark tab)

Charts of generation speed per floor and engine from `benchmark_log.csv`, a full table of the log, and
a PDF report.

## Files

| Part | Files |
|---|---|
| Tab | `primeatlas/benchmark/benchmark_tab.py` and its mixin `benchmark_filter.py` (Filter window) |
| Backend | `benchmark.py` (reading and normalizing rows, D/P kind, PDF report), `line_names.py` (a row's line and charts), `chart_filter.py` (which runs the charts compare), `sieve_measure.py` (which time the sieve chart measures), `chart_series.py`, `chart_pdf.py`, `reference_points.py` |

## Contract

| In | Out |
|---|---|
| `benchmark_log.csv` | charts (linear/log, pinned axes, per-line toggles), table, PDF |

Reads only; the log's header belongs to `prime_sieve/benchmark_log_schema.py`.

A chart line is one engine build on one thread setup (`line_names.line_name()`): the version when
it names the engine (`v6.0`), else the engine label and version, the store kind of P runs, then the
sieve threads (`24 thr`, `2x24 thr` for two instances side by side, `GPU`) and the write threads
(`write 8`). Names are ASCII, the PDF font has no other characters. Rows from before those columns
keep the bare engine name. The color and draw order follow the engine. Last row per floor and line
wins. primesieve rows say how they were measured: `primesieve (Atlas format)` (wrapper, conversion
into Atlas windows in its time), `primesieve count (native)` and `primesieve print (native)` (the
program). A native count sieves the range and counts the bits, the work of an engine's sieve phase:
it is on the sieve charts only, its seconds per window over 10^7-number windows. A native print
sieves and outputs every prime with no split between the two, a whole run: it is on the whole-run
chart only. No static primesieve reference is kept (a figure from another range length misleads:
primesieve's ~0.7 s setup at floor 19 dominates a short range); PARI/GP stays on the sieve chart.
The PDF run table lists `engine_version`, `threads` and `write_threads`. A writing row from before
`write_threads` reads `write ?`. Each point names the range it was measured on (`@ 10^11`,
`line_names.width_label()`); since the last row per floor wins, a chart can set points of different
widths side by side, and `mixed_width_floors()` lists those floors: the tab shows them under the
chart, the PDF next to the page heading.

The Filter window picks the runs the charts compare (`chart_filter.py`): each dimension -- engine
build, sieve threads, write threads, range width -- is a checkbox; checked, its values from the log
appear, all selected at first, each with its own checkbox. A run stays when its value is selected in
every checked dimension; the last row per floor and line is then taken among the kept runs, so one
width compares every engine on that width. Changes apply at once; the summary next to the Filter
button and the PDF subtitle name the selection; the PDF tables list the kept runs, the tab's table
the whole log. Session only, like the other chart toggles.

Its "Sieve measure" radio (`sieve_measure.py`, with an info tip) sets what the lower chart and the
PDF's sieve page measure: the engine's sieve phase (`sieve_seconds`, default), the sieve with
startup overhead (`sieve_wall_seconds`), or the overhead alone (the sieve speed the startup
takes: phase n/s minus wall n/s, and on the second axis that as % of the phase n/s). A row
without the time a measure needs has no point on it. Native primesieve count is timed as one
whole process, its ~0.7 s setup at floor 19 included: the same time is its point under the
engine phase and the sieve with startup, and it has no point under the overhead (no split
between setup and sieve to measure from outside). PARI/GP references go with those two
measures too. A change clears the chart's y pins; the summary and the PDF subtitle name a measure other than the default, the PDF
sieve page heading always names it.

## Parameters and texts

Texts `bench.*`, `pdf.*`.

## Kept data

None of its own.

## Specs and tests

`test_benchmark_tab`, `test_benchmark_chart_series`, `test_benchmark_actual_range`,
`test_benchmark_run_status`, `test_benchmark_main_compatibility`, `test_benchmark_log_schema`,
`test_benchmark_line_names`, `test_benchmark_auto_reload`, `test_benchmark_filter`,
`test_benchmark_sieve_measure`; `test_orchestrator_sieve_wall` (prime-sieve).

## Known gaps

None.
