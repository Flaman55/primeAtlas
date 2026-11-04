# Module: prime-sieve (sieve engines and orchestrators, WSL)

`prime_sieve/` produces the prime windows: the sieve engines (v6 by default, v5, pt1, primesieve,
cudasieve, Hybrid; older numbered versions kept), the orchestrators that run them in batches, and the
storage helpers both the engines and the GUI import. Runs under WSL; the GUI imports only the
standard-library helpers.

## Files

| Part | Files |
|---|---|
| Format | `prime_sieve_v1.py` (PGS2 read/write, varints), `pgs2_vector.py`, `window_integrity.py` |
| Engines | `prime_sieve_v6.py` + `engine_v6_lib.py` + `work_plan_v6.py` + `wheel30_layout.py` + `wheel30_writer.py` (default, code v6.0), `prime_sieve_v5.py` + `engine_v5_lib.py` + `work_plan_v5.py` (code v5.1), `prime_sieve_pt1.py` + `pt1_plan.py`, `prime_sieve_primesieve.py`, `prime_sieve_cudasieve.py`, `hybrid_*.py`; frozen `prime_sieve_v3.py`, `prime_sieve_v4.py`, `prime_sieve_v4_1.py` |
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

## How v5 and v6 spend a run

A run is two costs. The fixed one is generating every sieving prime below sqrt(top) (primesieve,
about 9 ns per prime per core; the phase division adds about 1 ns): on floor 29 about 9000 s
per run, whatever its length. The per-number one is marking: small primes in cache-sized
segments, the others through buckets. Every round of the bucket stage applies the collected
hits region by region and touches most lines of the buffer, and the number of rounds is the
hits over the bucket memory, so at a fixed bucket memory the bucket stage grows with the square
of the run length; hence v5.1's larger default segments (more primes in the segmented stage)
and buckets. v6 keeps that pipeline and stores 30 numbers per byte instead of 16, so the same
RAM holds a 1.875 times longer run and the fixed cost is paid that much less often.

Measured on a 12-core Zen 3 with 64 GB (count-only, 24 threads, same peak RAM 20.7 GB):

| | v5 defaults before v5.1 | v5.1 | v6.0 |
|---|---|---|---|
| floor 25 | about 0.48 G numbers/s | 0.75 G | 1.47 G |
| floor 27 | about 0.05 G | 0.20 G | 0.37 G |

v6 writes its windows in parallel (`wheel30_writer.py`): the native `wheel_window_gaps()` turns a
window's bytes into the PGS2 gap stream in one pass, and a thread pool overlaps the encoding
with the per-file latency of the /mnt drives (about 13 ms a file). Each shard folder is created
once and the written size comes from the encoded bytes, so a window costs one open, write and
close. 1,000 windows at floor 19 on a /mnt drive: 29 s with the NumPy path and a stat and
mkdir per window, 7.6 s with the native encoder on one thread, 2.3 s on 8 threads (ext4:
0.9 s). v5's write phase is still serial NumPy.

After each batch `orchestrator_v3.py` lets every new D window prove its P counterpart
(`dp_verify.reconcile_many()`, also behind the Storage tab's "Verify P against D"). The pairs
are compared by the run's worker threads, then `DP_PROVEN.txt` and `DP_MISMATCH.txt` are
written once and the proven P files removed; an interrupted batch leaves at worst a pair that
is compared again. 2,000 pairs of 160 KB on a /mnt drive with 30,000 listed D/P windows: 140 s
when the list was rewritten per window, 21 s on one thread, 8 s on 24. The time goes to the
benchmark row as `verify_seconds`, inside `total_seconds`.

## Kept data

Prime windows, `benchmark_log.csv`, `floor_meta.json`, `last_scan_metrics.json`, sieving-prime cache,
hit pages ([data.md](../data.md)).

## Specs and tests

`test_prime_window`, `test_pgs2_vector`, `test_window_integrity`, `test_window_sharding`,
`test_storage_kinds`, `test_dp_verify`, `test_engine_v5_identity`, `test_engine_v5_phase`,
`test_engine_v6_identity`, `test_wheel30_layout`, `test_wheel30_writer`, `test_work_plan_v6`,
`test_engine_pt1`, `test_work_plan_v5`, `test_overlap_pipeline`, `test_orchestrator_stop`,
`test_hybrid_*`, `test_cudasieve_integration`, `test_hit_paging`, `test_floor_meta_store`,
`test_benchmark_log_schema`, `test_print_benchmark_summary`, `test_pi_seed`. See also BENCHMARK.md.

## Known gaps

- The bucket stage still needs more bucket memory for a longer run (v6.1 plan: L3-sized chunks of
  the buffer with carried per-prime state for the medium primes, one round per chunk).
- Presieve stops at 17 in v6 (19 fits L2 too); the wheel is fixed at 30 (210 / 2310 would hold
  1.17 / 1.28 times more numbers per byte).
- v5 writes its windows serially through NumPy; v6's native parallel writer is not ported to it.
- The write phase starts after the sieve; overlapping it with the next run's sieve (pt1 does this)
  is not built for v6.
- D proves P runs inside the generation run; a detached verifier draining a per-floor queue
  (one per floor, since both lists are read-modify-write) is not built.
- The Benchmark tab's total speed includes `verify_seconds`; it has no view without it.
