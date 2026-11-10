# Module: prime-sieve (sieve engines and orchestrators, WSL)

`prime_sieve/` produces the prime windows: the sieve engines (v6 by default, v7, v5, pt1, primesieve,
cudasieve, Hybrid; older numbered versions kept), the orchestrators that run them in batches, and the
storage helpers both the engines and the GUI import. Runs under WSL; the GUI imports only the
standard-library helpers.

## Files

| Part | Files |
|---|---|
| Format | `prime_sieve_v1.py` (PGS2 read/write, varints), `pgs2_vector.py`, `window_integrity.py` |
| Engines | `prime_sieve_v6_1.py` + `engine_v6_lib.py` + `work_plan_v6.py` + `wheel30_layout.py` + `wheel30_writer.py` (default, code v6.1; `prime_sieve_v6.py`, v6.0, kept for comparison), `prime_sieve_v7_2.py` + `work_plan_v7_2.py` + `engine_v7_2_lib.py` (`prime_sieve_engine_v7_2.c` + `engine_jump_gear.h`, code v7.2; `prime_sieve_v7_1.py` + `work_plan_v7_1.py`, v7.1, and `prime_sieve_v7_0.py` + `work_plan_v7.py` + `engine_v7_lib.py` on `prime_sieve_engine_v7_0.c`, v7.0, kept for comparison), `prime_sieve_v5_2.py` + `engine_v5_lib.py` + `work_plan_v5.py` (code v5.2), `parallel_window_writer.py` (write phase of v5.2, v6 and v7), `prime_sieve_pt1.py` + `pt1_plan.py` + `pt1_lib.py` (`prime_sieve_engine_pt1.c` + `engine_pt_core.h` + `engine_pt_pss.h`, code pt1.1), `pt1_verify.py` + `pt1_verify_store.py` (the verification P -> D), `prime_sieve_primesieve.py`, `prime_sieve_cudasieve.py`, `hybrid_*.py`; frozen `prime_sieve_v3.py`, `prime_sieve_v4.py`, `prime_sieve_v4_1.py`, `prime_sieve_v5.py` (v5.1, still the home of helpers v6 and pt1 import) |
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

## How pt1 proves its P windows

pt1 tests the survivors of its partial sieve with 13 Miller-Rabin bases below `MR_DET_BOUND`
(3.3e24, a proof: D windows) and with BPSW above it (P windows). The verification turns a P
window into D: the window is sieved again by the primes 3..s and every survivor is decided by
the pseudosquares test (`engine_pt_pss.h`, Lukes-Patterson-Williams with Sorenson's sieve
bound; table L_p up to p = 373). The test needs no prime factor of n up to s and n / s < L_373
(about 4.2e24), so s = max(B, top / L_373) and s < 2^32: numbers below about 1.8e34. The proven
list is compared with the BPSW list window by window:

| Outcome | Store | Lists |
|---|---|---|
| equal | the window goes to the D store | its tag in `DP_PROVEN.txt` (D/P: also counts as present in P) |
| different | stays in the P store | `DP_MISMATCH.txt` with the first differing number; never resolved automatically |

Two ways to run it:

- `PRIMEATLAS_PT1_VERIFY=1` (the pt1 checkbox "Verify P -> D after sieving"): each P slab is
  proven right after its sieve, in memory, so count-only runs verify too. The proof's time is
  measured on its own: `proof_seconds` in the handoff and in the benchmark row, not part of
  `sieve_seconds`; the scanner prints the sieve speed alone, with the proof, and the drop.
  Floor 29, 1e8 numbers, 24 threads: sieve 0.9 s, proof 8 s.
- `pt1_verify_store.py` (Generation Section D): the floor's P windows already in the store,
  grouped into slabs of adjacent windows. Each slab's outcomes are recorded before the next
  slab starts (the tag first, then the file move: a tag without a D file counts for nothing),
  so a stop between slabs or a kill keeps every finished slab. A window with a D file already
  is left to "Verify P against D"; a window whose primes reach past the window width is
  skipped. A slab smaller than four chunks per thread gets smaller chunks
  (`pt1_verify.MIN_CHUNK_ODD`), since the proof costs far more per number than the sieve. One
  `pt1_verify` row per run, its proof time in `verify_seconds`.

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
"primesieve Atlas" on the charts) logs one row per call: `total_seconds` is the wall time of
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

Pseudosquares mode (`pseudosquares_native.py`) runs the Pseudosquares Prime Sieve program (Kim
Walisch, BSD 2-Clause) the same way, with rows `pseudosquares_count` / `pseudosquares_print`:
count runs `pseudosquares_prime_sieve START STOP [--threads=N]` (threads parsed from its
report), print adds `--print` into `pseudosquares/10p{N}/<start>_<stop>.txt` (one thread, the
program sets it). The range stays inside its floor and under the program's stop, `pseudosquares_const.MAX_STOP` =
int(1.73 * 1e33), the double bound its code checks (`--help` rounds it to 10^33); floor 33 is the
last, `MAX_FLOOR`, up to that stop. `engine_version` is the program's version plus
the commit of the installer's clone ("1.2 (fccb96e)"), version alone for a binary found
elsewhere. Both native runners share `native_tool_run.py`: the timed child (`run_timed`), the
printed file's line count, the child's peak RSS and the row itself. The program is found at
`$PSEUDOSQUARES_BIN`, then the installer's build, then PATH. `pseudosquares_install.py`
`--status` prints one JSON line (missing build tools, clone and its commit, at the pin, binary
and version); `--build` clones the repository into `~/.primeatlas/pseudosquares` (fresh
install), fetches and checks out `pseudosquares_const.PIN_COMMIT` and builds it with CMake
(Release, all cores). Its CMake configure fetches the program's own pinned dependencies from
the network.

## How v7 finds the deep-floor hits

On deep floors the bucket stage is nearly the whole sieve, and nearly all of it goes to primes
that never hit: at floor 25 a run of 2e11 numbers sieves with the 1.1e11 primes below
sqrt(top) = 3.2e12, and every prime above the run's width has at most one multiple in it.
v6 computes first mod p for each of them anyway (primesieve generates them at about 7 ns a
prime, the phase adds the rest), so this stage costs in proportion to the primes below
sqrt(top), whatever the run's width.

v7.0 (`prime_sieve_engine_v7_0.c`, run by `prime_sieve_v7_0.py`) keeps v6.1's engine and adds
the jump gear (`engine_jump_gear.h`) for the bucketed primes from p* up. It asks which q land
in the run instead of where each p lands:

- q runs over blocks Q + 30 j of the numbers coprime to 30 in one residue class, composites
  included; a composite q's multiple is composite with a prime factor >= 7 below sqrt(top),
  which marks it too, so the extra marks change no bit;
- over a block first / q is a line X0 - S j (64.64 fixed point) plus an error >= 0 below
  first d^2 / Q^3 (d = 30 j); a q lands when frac(-first / q) < span / q, so every landing has
  (A + B j) mod 2^64 < T, with T covering span / Q, the error and the truncations;
- the first such j comes from a Euclid-like search, the next ones from the three-gap theorem
  (consecutive solutions differ by one of three fixed steps); each candidate is checked exactly
  with one multiply and at most two corrections, no division;
- the gear is used only where it is exact: q >= 2 * span (one multiple at most) and
  first / q < 2^62.

A classic prime costs one phase whether it hits or not; a jump costs per landing candidate,
about span / q per q (block setup included). The two meet at a q proportional to span * ln q,
so `work_plan_v7.jump_from()` puts p* = K * span * ln p*, K the threshold knob (default 1.0,
`PRIMEATLAS_V7_JUMP_PCT` = 100; 0 turns the gear off). The bucketed primes are split at p*:
v6's cost-equal pieces below it, pieces of equal ratio hi / lo above it (equal jump cost); the
gear's hits go through v6.1's staged buckets like any other.

Measured in a C prototype of the gear (12 bands sieved at once on a 12-core Zen 3, 2e11 numbers
per run, the prototype's classic path cheaper than v6.1's): p* about 5e12 at floor 26, 5.7e12 at
27, 7e12 at 28 (single-threaded about 2.5e12: under full load the gear's marks wait on memory
more); bucket stage on 12 threads:

| | classic only | with the gear |
|---|---|---|
| floor 26 | 541 s | 446 s (1.2x) |
| floor 27 | 1986 s | 981 s (2.0x) |
| floor 28 | 5297 s | 1304 s (4.1x) |

Real engines, count-only, 2e11 numbers, 24 threads, empty store, v6.1 then v7.0 on the same
run (whole sieve):

| | v6.1 | v7.0 |
|---|---|---|
| floor 25 | 141.1 s | 143.2 s (gear off: p* 5.4e12 above sqrt(top)) |
| floor 26 | 330.5 s | 240.7 s (1.37x) |
| floor 27 | 926.7 s | 320.3 s (2.89x) |
| floor 28 | 3206.5 s | 603.8 s (5.31x) |

The real gain exceeds the prototype's because v6.1's classic path costs more per prime than
the prototype's. When p* lies above sqrt(top) (floor 25 at 2e11 numbers; with 1e10 numbers p* is 2.6e11
and the gear is on there too) a v7 run is v6.1's. On narrow runs the default threshold is too
low: at 1e10 numbers the best K was 3 at floor 26, 10 at 27, 30 or more at 28. Its output is v6.1's bit for
bit (`test_engine_v7_0_identity`: whole runs with the gear forced on; engine calls whose pieces
cover every sieving prime, buffer equal; engine calls on partial pieces at floors 16-30, every
v6.1 bit marked and every extra bit a composite, the multiple of a composite q).

v7.1 (`prime_sieve_v7_1.py`, `work_plan_v7_1.py`) runs v7.0's C engine.
Its threshold adds the block term v7.0's model lacks. Per integer q a classic prime costs about
1 / ln q (one phase, prime density 1 / ln q), the gear about (a * sqrt(first / span) + b * span)
/ q in classic primes: block setups (about sqrt(first / span) per doubling of q) plus landings
(span / q per q). They meet at

    p* = ln p* * (a * sqrt(first / span) + b * span),

so narrow runs and deep floors move p* up. The knob is p* in percent of the model
(`PRIMEATLAS_V7_JUMP_MODEL_PCT`, default 100, 0 = off); a and b are knobs too
(`PRIMEATLAS_V7_JUMP_BLOCK_COST`, default 300; `PRIMEATLAS_V7_JUMP_LANDING_COST_PCT`, default 10
= 0.10). The defaults are fitted on one machine (24 threads, count-only), from v7.0's threshold
sweeps:

| run | model p* | best measured threshold |
|---|---|---|
| 1e10 numbers, floor 26 | 8.5e11 | 8.2e11 (K 3) |
| 1e10 numbers, floor 27 | 2.75e12 | 2.9e12 (K 10) |
| 1e10 numbers, floor 28 | 9.0e12 | 8.9e12 or above (K 30, the highest tried) |
| 2e11 numbers, floor 26 | 7.3e11 | 5.4e11 (K 0.1, the lowest tried) |

b is pinned loosely: on wide runs the best threshold sits near the gear's 2 * span limit. At
the defaults, without tuning, v7.1 matches the best hand-picked v7.0 threshold on narrow runs
(1e10 numbers, count-only): floor 26 95 s (v7.0 best 101 s, default 116 s), floor 27 253 s
(264 s, 374 s), floor 28 717 s (756 s, 1178 s). On wide runs (2e11 numbers, count-only, same machine) v7.1 against v7.0 at its default: floor 27
268 -> 235 s, floor 28 462 -> 446 s (within run-to-run noise), the same prime counts.

The same model weights the progress line (`work_plan_v7_1.stage_weights()`): threads take the
pieces in order, so the finished count maps to a share of the estimated cost, in units of one
iteration of a bucketed prime above the buffer size: classic pieces by v5's Mertens/li cost with
the Mertens hits below the buffer size at `BUCKET_HIT_COST` (0.45), jump pieces by the model's
jump_cost() * ln(hi / lo), segmented slices by their marks times `SEGMENTED_MARK_COST` (0.03).
The two constants are fitted to the stage times of the floor 27 and 28 runs above (the bar then
stays within about 7 points of elapsed time, against 15-23 with equal hit costs); elsewhere they
are arbitrary. There the jump pieces took about 1.2-1.4 times their model cost. The line's
percent and ETA follow that share; the job counts stay in the line. Each stage's wall time is printed when it ends. Output
is v6.1's bit for bit (`test_engine_v7_1_identity`: whole runs with the gear forced on, at the
defaults and with small segments).

v7.2 (`prime_sieve_v7_2.py`, `work_plan_v7_2.py`, `prime_sieve_engine_v7_2.c`) is what the GUI's
`v7` runs. It sets the gear's block factor f from the model instead of v7.0's fixed 0.5. A block
f times longer means 1 / f as many block setups; its linear estimate drifts by up to
f^2 * span / 2 numbers, and the candidate window is the buffer plus that drift, so candidates grow
as span * (1 + f^2 / 2). With a and b fitted at f = 0.5:

    cost(f) = a * sqrt(first / span) * 0.5 / f + b * span * (1 + f^2 / 2) / 1.125,
    f* = (0.5625 * a * sqrt(first / span) / (b * span))^(1/3).

f* is about 0.47 for 2e11 numbers at floor 25 (the prototype's best was 0.5), 1.24 for 2e11 at
floor 28, 2.6 for 1e10 at floor 26 and 5.5 for 1e10 at floor 28. p* is v7.1's fixed point with
cost(f*) (as v7.1's form with a' = a * 0.5 / f, b' = b * (1 + f^2 / 2) / 1.125), so the cheaper
gear takes more primes, and at least 2 * span * (1 + f^2 / 2), where the candidate window stays
below half a turn of q. The knob is f in percent of f* (`PRIMEATLAS_V7_BLOCK_MODEL_PCT`, default
100); v7.0's fixed `PRIMEATLAS_V7_JUMP_BLOCK_PCT` is not read. Longer blocks leave the block setup a
larger share, so the engine sets blocks up with `jump_block_quick()` (`engine_jump_gear.h`): the
same landings, the first-solution search in 64-bit arithmetic and both three-gap steps from one
subtractive Euclid walk, about a third cheaper per block. Measured (count-only, 24 threads, same
machine as above), v7.1 -> v7.2 at the defaults, the same prime counts:

| run | v7.1 | v7.2 |
|---|---|---|
| 1e10 numbers, floor 25 | about 33 s | 17.7 s |
| 1e10 numbers, floor 26 | 95 s | 32.0 s |
| 1e10 numbers, floor 27 | 253 s | 64.8 s |
| 1e10 numbers, floor 28 | 717 s | 140.0 s |
| 1e10 numbers, floor 29 | about 2260 s | 312.1 s |
| 2e11 numbers, floor 28 | 446 s | 312.5 s |

The floor 29 count equals pt1's and Pseudosquares' on the same range. The knob around the model
at floor 28, 1e10 numbers: 50 % 167 s, 100 % 140 s, 200 % 264 s.
Output is v6.1's bit for bit (`test_engine_v7_2_identity`: engine calls with block factors 0.05
to 20, full pieces bit-identical, partial pieces at floors 16-30 with every v6.1 bit marked,
every extra bit composite and nothing past the buffer; whole runs with the gear on nearly every
bucketed prime at the model's factor and at 4 times it, at the defaults and with small segments).

## Kept data

Prime windows, `benchmark_log.csv`, `floor_meta.json`, `last_scan_metrics.json`, sieving-prime cache,
hit pages ([data.md](../data.md)).

## Specs and tests

`test_prime_window`, `test_pgs2_vector`, `test_window_integrity`, `test_window_sharding`,
`test_storage_kinds`, `test_dp_verify`, `test_engine_v5_identity`, `test_engine_v5_phase`,
`test_engine_v6_identity`, `test_engine_v6_1_identity`, `test_engine_v7_0_identity`,
`test_work_plan_v7`, `test_engine_v7_1_identity`, `test_work_plan_v7_1`,
`test_engine_v7_2_identity`, `test_work_plan_v7_2`, `test_engine_v5_2_identity`,
`test_parallel_window_writer`, `test_wheel30_layout`, `test_wheel30_writer`, `test_work_plan_v6`,
`test_engine_pt1`, `test_engine_pt1_verify`, `test_work_plan_v5`, `test_overlap_pipeline`, `test_orchestrator_stop`,
`test_hybrid_*`, `test_cudasieve_integration`, `test_hit_paging`, `test_floor_meta_store`,
`test_benchmark_log_schema`, `test_print_benchmark_summary`, `test_primesieve_benchmark_row`,
`test_primesieve_native`, `test_pseudosquares_native`, `test_pseudosquares_install`,
`test_pi_seed`. See also BENCHMARK.md.

## Known gaps

- v7's threshold depends only on the run's width and the knob; its best value also depends on
  the floor and the thread count, so on narrow runs the knob has to be raised by hand.
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
- The time model calibrates pt1 without `proof_seconds`; it has no estimate of the proof.
- Above top / L_373 > B (floors 32-34) the verification sieves to s up to 2^32: up to 2e8
  sieving primes, about 0.8 GB, and a long setup per slab.
