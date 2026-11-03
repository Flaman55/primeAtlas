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

## Parameters and texts

Texts `bench.*`, `pdf.*`.

## Kept data

None of its own.

## Specs and tests

`test_benchmark_tab`, `test_benchmark_chart_series`, `test_benchmark_actual_range`,
`test_benchmark_run_status`, `test_benchmark_main_compatibility`, `test_benchmark_log_schema`.

## Known gaps

None.
