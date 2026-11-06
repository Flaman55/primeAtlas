# Module: prime-sieve (sieve engines and orchestrators, WSL)

`prime_sieve/` produces the prime windows: the sieve engines (v6 by default, v5, pt1, primesieve,
cudasieve, Hybrid; older numbered versions kept), the orchestrators that run them in batches, and the
storage helpers both the engines and the GUI import. Runs under WSL; the GUI imports only the
standard-library helpers.

## Files

| Part | Files |
|---|---|
| Format | `prime_sieve_v1.py` (PGS2 read/write, varints), `pgs2_vector.py`, `window_integrity.py` |
| Engines | `prime_sieve_v6_1.py` + `engine_v6_lib.py` + `work_plan_v6.py` + `wheel30_layout.py` + `wheel30_writer.py` (default, code v6.1; `prime_sieve_v6.py`, v6.0, kept for comparison), `prime_sieve_v5_2.py` + `engine_v5_lib.py` + `work_plan_v5.py` (code v5.2), `parallel_window_writer.py` (write phase of v5.2 and v6), `prime_sieve_pt1.py` + `pt1_plan.py`, `prime_sieve_primesieve.py`, `prime_sieve_cudasieve.py`, `hybrid_*.py`; frozen `prime_sieve_v3.py`, `prime_sieve_v4.py`, `prime_sieve_v4_1.py`, `prime_sieve_v5.py` (v5.1, still the home of helpers v6 and pt1 import) |
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

v6.1 (`prime_sieve_engine_v6_1.c`, run by `prime_sieve_v6_1.py`, which is v6.0's script on
the new engine) changes how the marks are made, not which: its output is v6.0's bit for bit
(`test_engine_v6_1_identity` compares whole runs and both engine calls on boundary inputs).
On floor 19 the segmented primes took most of v6.0's sieve (10 of 18 s per 1e11 numbers),
about 4 ns per mark: each mark divided its offset by 30 and looked up its bit. One wheel
turn of a prime p (30p numbers) moves each of its 8 marks by exactly p bytes and keeps its
bit, so v6.1 computes the 8 byte offsets and masks once per prime and segment and marks a
whole turn with 8 byte ORs (primes below a segment's numbers / 32; the larger ones have few
marks per segment and keep the per-mark loop). In the bucket stage the slot writes cost more
than computing the hits (floor 19: hits 1.1 s, slot writes 3.3 s, apply 2.0 s, measured by
switching parts off): every write missed the cache and first read the line it overwrote.
v6.1 stages each region's hits in one 64-byte line and writes full lines with non-temporal
stores. Measured (count-only, 24 threads, 4096 MiB buckets, interleaved rounds):

| | v6.0 | v6.1 |
|---|---|---|
| floor 19, 1e11 numbers, sieve | 15.4-18.5 s | 13.2-14.2 s |
| floor 25, 2e11 numbers, sieve | 147-155 s | 134-141 s |

The gain shrinks with the floor: the unrolled loop speeds up the segmented primes, and the
higher the floor, the more of the sieve is the bucket stage. In full generation runs from
the GUI (store empty, same floor for both) v6.1 is faster on the low floors and practically
equal to v6.0 from floor 26 up.

Tried and left out (no gain beyond noise on floor 19): presieve tables up to 167, L1/L2 tiles
for the small primes inside a segment (-10 % of the segmented part before the unrolled loop,
nothing after it), huge pages for the bucket slots.

v6 writes its windows in parallel (`wheel30_writer.py` on `parallel_window_writer.py`): the native
`wheel_window_gaps()` turns a window's bytes into the PGS2 gap stream in one pass, and a thread pool
overlaps the encoding
with the per-file latency of the /mnt drives (about 13 ms a file). Each shard folder is created
once and the written size comes from the encoded bytes, so a window costs one open, write and
close. 1,000 windows at floor 19 on a /mnt drive: 29 s with the NumPy path and a stat and
mkdir per window, 7.6 s with the native encoder on one thread, 2.3 s on 8 threads (ext4:
0.9 s). v5.2 runs v5.1's NumPy encoder on the same thread pool (`PRIMEATLAS_V5_WRITE_THREADS`,
default 8): 1,000 windows at floor 19 on a /mnt drive, four interleaved rounds each, write phase
about 25 s in v5.1 and 4.8 s in v5.2, whole run about 29 s and 7.9 s, same bytes.

After each batch `orchestrator_v3.py` lets every new D window prove its P counterpart
(`dp_verify.reconcile_many()`, also behind the Storage tab's "Verify P against D"). The pairs
are compared by the run's worker threads, then `DP_PROVEN.txt` and `DP_MISMATCH.txt` are
written once and the proven P files removed; an interrupted batch leaves at worst a pair that
is compared again. 2,000 pairs of 160 KB on a /mnt drive with 30,000 listed D/P windows: 140 s
when the list was rewritten per window, 21 s on one thread, 8 s on 24. The time goes to the
benchmark row as `verify_seconds`, inside `total_seconds`.

The row's prime count comes from the scanner's closing line (`TOTAL PRIMES FOUND this run: N
across W windows`): `run_batch()` copies the scanner's stdout through and reads that line from
the process's own output, so parallel instances never take each other's count (the scan-metrics
handoff file is shared). When a batch printed no such line (a low-floor run reports floors) or
the reported windows do not add up to the range, the headers of the written windows are read
instead, one file open each (about 13 ms on a /mnt drive, overlapped by `workers` threads).
Per-window times print in ms below a second.

`sieve_wall_seconds` times the sieve from outside the engine: `_run_teed()` takes the clock
before launching the scanner and again when its `[*] Batch sieve done in` line arrives on the
pipe, in the orchestrator process; the batches' sum minus `base_gen_seconds` (the optional
pi(L_final) diagnostic, no sieve work) goes to the row next to the engine's own `sieve_seconds`,
so the gap is the startup the engine's timer leaves out (Python start, imports, buffer
allocation, library load, sieving primes). The scanner's code and argv are unchanged; it runs with
`PYTHONUNBUFFERED=1` so the line arrives when printed (v4.1 and v5 do not flush it), which costs
nothing measurable at a few dozen lines per run. Count-only runs are read the same way. pt1
prints no such line (it overlaps sieve and write) and keeps the column blank; a stopped run too.

Every row records `threads` (sieve): the worker count of v4.1/v5/v6/pt1 (`orchestrator_v3.py`), 1
for hybrid and the primesieve wrapper, `GPU` for cudasieve, the count primesieve reports for a
native count; and `write_threads`: the write-thread knob of v6 or v5.2 (`scanner_write_threads()`
reads it from the environment the scanner inherits), 1 for every other writer, blank for a native
count.

Primesieve mode has two paths. The wrapper (`prime_sieve_primesieve.py`, engine tag `primesieve`,
"primesieve (Atlas format)" on the charts) logs one row per call: `total_seconds` is the wall time of
`primesieve_generate_primes()` plus splitting and writing the windows, `sieve_seconds` and
`write_seconds` the two phases, `bytes_written` the files' size on disk, `numbers_processed` the
range, `max_child_rss_mb` the process's peak RSS (the whole prime list is in it), `threads` 1. Its
sieve time includes copying the library's array into a Python list, so it is not primesieve's own
speed. Native (`primesieve_native.py`) runs the primesieve program: `print` sends `primesieve
--print` into `primesieve/10p{N}/<start>_<stop>.txt` (primesieve's text, not Atlas storage, one
thread), `count` runs `primesieve --count --time` (sieve + bit count, threads parsed from its
report). The timed part is the primesieve process alone; its row (`primesieve_print` /
`primesieve_count`) has the program's version and no windows. count: the wall time is total and
sieve time (the work of a sieve phase), no `loop_*` columns. print: the wall time is total and loop
time (`loop_numbers_per_second`, a whole run), no sieve time. SIGTERM (the Stop button) ends the
child too.

## Kept data

Prime windows, `benchmark_log.csv`, `floor_meta.json`, `last_scan_metrics.json`, sieving-prime cache,
hit pages ([data.md](../data.md)).

## Specs and tests

`test_prime_window`, `test_pgs2_vector`, `test_window_integrity`, `test_window_sharding`,
`test_storage_kinds`, `test_dp_verify`, `test_engine_v5_identity`, `test_engine_v5_phase`,
`test_engine_v6_identity`, `test_engine_v6_1_identity`, `test_engine_v5_2_identity`,
`test_parallel_window_writer`, `test_wheel30_layout`, `test_wheel30_writer`, `test_work_plan_v6`,
`test_engine_pt1`, `test_work_plan_v5`, `test_overlap_pipeline`, `test_orchestrator_stop`,
`test_hybrid_*`, `test_cudasieve_integration`, `test_hit_paging`, `test_floor_meta_store`,
`test_benchmark_log_schema`, `test_print_benchmark_summary`, `test_primesieve_benchmark_row`,
`test_primesieve_native`, `test_pi_seed`. See also BENCHMARK.md.

## Known gaps

- The bucket stage is now the larger part of a floor-19 sieve and nearly all of a floor-25 one.
  Each prime streams its hits across the whole buffer, so a thread writes to every region's
  bucket at once and every hit goes to RAM and back. The next step: per-slice buckets that
  hold each medium prime for the segment of its next hit (primesieve's scheme), RAM per
  thread growing with the primes kept (primesieve's floor-19 count peaks at 19 GB).
- Presieve stops at 17 (measured: tables up to 167 gain nothing once the wheel turn is
  unrolled); the wheel is fixed at 30 (210 / 2310 would hold 1.17 / 1.28 times more numbers
  per byte).
- v5.2 encodes each window through NumPy on the write threads; v6's native gap encoder is not
  ported to the odd-only buffer.
- The write phase starts after the sieve; overlapping it with the next run's sieve (pt1 does this)
  is not built for v6.
- D proves P runs inside the generation run; a detached verifier draining a per-floor queue
  (one per floor, since both lists are read-modify-write) is not built.
- The Benchmark tab's total speed includes `verify_seconds`; it has no view without it.
