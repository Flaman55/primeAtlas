# Module: benchmark (Benchmark tab)

Charts of generation speed per floor and engine from `benchmark_log.csv`, a full table of the log, and
a PDF report.

## Files

| Part | Files |
|---|---|
| Tab | `primeatlas/benchmark/benchmark_tab.py` |
| Exports | `benchmark_export.py` (tab mixin: Save PDF, Export menu), `report_export.py` (CSV, SVG, HTML page, HTML snippet), `chart_svg.py` (SVG backend of `chart_pdf.chart_ops()`) |
| Backend | `benchmark.py` (reading and normalizing rows, D/P kind, PDF report, `report_chart_pages()`), `chart_series.py`, `chart_pdf.py`, `reference_points.py` |

## Contract

| In | Out |
|---|---|
| `benchmark_log.csv` | charts (linear/log, pinned axes, per-line toggles), table, PDF, CSV, SVG, HTML page, HTML snippet |

Reads only; the log's header belongs to `prime_sieve/benchmark_log_schema.py`.

Three charts, one line per engine, last row per floor and line: the whole run (`loop_numbers_per_second`,
write MB/s), the sieve phase (sieve n/s, s/window, reference points), and RAM (`max_child_rss_mb`, the
largest process's peak, and that divided by `windows_written`, so runs of different widths compare). RAM
has its own chart so its megabytes do not share an axis with a speed. Each chart keeps its own hidden
lines and pinned axes; the PDF draws the RAM pair on its own page when any row measured it.

Reports: `report_chart_pages()` lists the report's charts (one metric each: the whole run, the
sieve phase when there is sieve data or the references are on, RAM when a row measured it), and
every format draws them with the tab's view. `chart_pdf.chart_ops()` lays a chart out once and
draws through a backend, PDF content ops or SVG elements (`chart_svg.py`, y flipped, Unicode text),
so the PDF and SVG/HTML charts match. The HTML page and the snippet hold the charts inline and the
PDF's logical tables (`benchmark_pdf_tables()`), every cell escaped; the snippet is one
`<div class="primeatlas-benchmark">` whose style rules are all scoped to that class. CSV writes the
rows as the tab read them (with the D/P `kind` column).

## Parameters and texts

Texts `bench.*`, `pdf.*`.

## Kept data

None of its own.

## Specs and tests

`test_benchmark_tab`, `test_benchmark_chart_series`, `test_benchmark_report_export`,
`test_benchmark_actual_range`,
`test_benchmark_run_status`, `test_benchmark_main_compatibility`, `test_benchmark_log_schema`.

## Known gaps

- `benchmark_tab.py` has 944 lines; a fourth chart needs the three redraw methods folded into
  one chart table first.
- Primesieve and cudasieve rows log no RAM, so they have no RAM points.
