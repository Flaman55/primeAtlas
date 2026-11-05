# Module: benchmark (Benchmark tab)

Charts of generation speed per floor and engine from `benchmark_log.csv`, a full table of the log, and
a PDF report.

## Files

| Part | Files |
|---|---|
| Tab | `primeatlas/benchmark/benchmark_tab.py` |
| Backend | `benchmark.py` (reading and normalizing rows, D/P kind, PDF report), `chart_series.py`, `chart_pdf.py`, `reference_points.py` |

## Contract

| In | Out |
|---|---|
| `benchmark_log.csv` | charts (linear/log, pinned axes, per-line toggles), table, PDF |

Reads only; the log's header belongs to `prime_sieve/benchmark_log_schema.py`.

Three charts, one line per engine, last row per floor and line: the whole run (`loop_numbers_per_second`,
write MB/s), the sieve phase (sieve n/s, s/window, reference points), and RAM (`max_child_rss_mb`, the
largest process's peak, and that divided by `windows_written`, so runs of different widths compare). RAM
has its own chart so its megabytes do not share an axis with a speed; it shares a row with the sieve chart, half the width each, so the page still fits the default 1050x680 window. Each chart keeps its own hidden
lines and pinned axes; the PDF draws the RAM pair on its own page when any row measured it.

## Parameters and texts

Texts `bench.*`, `pdf.*`.

## Kept data

None of its own.

## Specs and tests

`test_benchmark_tab`, `test_benchmark_chart_series`, `test_benchmark_actual_range`,
`test_benchmark_run_status`, `test_benchmark_main_compatibility`, `test_benchmark_log_schema`.

## Known gaps

- `benchmark_tab.py` is near the 1000-line ceiling (985 lines); a fourth chart needs the three
  redraw methods folded into one chart table first.
- Primesieve and cudasieve rows log no RAM, so they have no RAM points.
