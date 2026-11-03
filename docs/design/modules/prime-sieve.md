# Module: prime-sieve (sieve engines and orchestrators, WSL)

`prime_sieve/` produces the prime windows: the sieve engines (v5 by default, pt1, primesieve,
cudasieve, Hybrid; older numbered versions kept), the orchestrators that run them in batches, and the
storage helpers both the engines and the GUI import. Runs under WSL; the GUI imports only the
standard-library helpers.

## Files

| Part | Files |
|---|---|
| Format | `prime_sieve_v1.py` (PGS2 read/write, varints), `pgs2_vector.py`, `window_integrity.py` |
| Engines | `prime_sieve_v5.py` + `engine_v5_lib.py` + `work_plan_v5.py` (default), `prime_sieve_pt1.py` + `pt1_plan.py`, `prime_sieve_primesieve.py`, `prime_sieve_cudasieve.py`, `hybrid_*.py`; frozen `prime_sieve_v3.py`, `prime_sieve_v4.py`, `prime_sieve_v4_1.py` |
| Orchestrators | `orchestrator_loop_v2.py`, `orchestrator_v3.py`, `orchestrator_loop_helpers.py`, `overlap_pipeline.py` |
| Shared storage helpers | `window_sharding.py`, `storage_kinds.py` (D/P stores), `dp_verify.py`, `benchmark_log_schema.py`, `floor_meta_store.py`, `hit_paging.py`, `generation_stop.py`, `sieving_prime_count_v5.py` |
| Queries | `primesieve_query.py`, `primecount_query.py`, `prime_count_primecount.py` |

## Contract

| In | Out |
|---|---|
| argv and `PRIMEATLAS_*` / `CONSTELLATION_PORTAL_DIR` environment from the GUI | PGS2 windows, benchmark rows, floor_meta rows, progress lines on stdout |

The orchestrators read `GENERATION_STOP_REQUEST.txt` and never write it. Shared helpers import only
the standard library, so engines stay runnable standalone with only `prime_sieve/` on sys.path.

## Parameters and texts

[generation-loop](../parameters/generation-loop.md) (the GUI's view of these knobs); engine-side
defaults are mirrored in `primeatlas/generation/engine_options.py`.

## Kept data

Prime windows, `benchmark_log.csv`, `floor_meta.json`, `last_scan_metrics.json`, sieving-prime cache,
hit pages ([data.md](../data.md)).

## Specs and tests

`test_prime_window`, `test_pgs2_vector`, `test_window_integrity`, `test_window_sharding`,
`test_storage_kinds`, `test_dp_verify`, `test_engine_v5_identity`, `test_engine_v5_phase`,
`test_engine_pt1`, `test_work_plan_v5`, `test_overlap_pipeline`, `test_orchestrator_stop`,
`test_hybrid_*`, `test_cudasieve_integration`, `test_hit_paging`, `test_floor_meta_store`,
`test_benchmark_log_schema`, `test_print_benchmark_summary`, `test_pi_seed`. See also BENCHMARK.md.

## Known gaps

- Engine ideas from the 2026-10-29 benchmark (longer range per run, odd-only buffer, ext4 storage) are
  not built.
