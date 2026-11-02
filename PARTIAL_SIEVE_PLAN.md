# Partial sieve + primality test engine, D/P storage -- spec

Branch: `feature/partial-sieve-bpsw` (from `main` 815b8f0).

## Goal

Deep floors cost v5 one fixed pass over every sieving prime up to sqrt(N) per run
(F, measured at 10^25: 67 s of which ~45 s is generating those primes, ~12 s their
phase). F grows ~3.2x per floor, and the RAM-bound window count caps how far it is
amortized. A second engine sieves each window only by the primes up to B = N^(1/4) and
tests the survivors with BPSW. Its throughput is the same on every floor (measured
~0.17 G numbers/s on 24 threads at 10^18..10^30, every survivor cross-checked against
GMP), so it overtakes v5 around floor 28-29 (floor 29: ~1.1 h vs ~2.7 h for ~7e11
numbers; floor 30: ~7x) and needs no floor-sized buffer.

Above the bound where a deterministic test exists, its output is a probable prime list.
Such results are kept apart from proven ones: two stores, D (deterministic) and P
(probable), never mixed in one file.

## Definitions

- **MR bound** `MR_DET_BOUND = 3_317_044_064_679_887_385_961_981` (Sorenson-Webster):
  strong probable primes to the 13 bases 2..41 below it are prime.
- **D window**: every number of the window lies below `MR_DET_BOUND` and was tested with
  those 13 bases, or the window comes from a sieve engine (v3..v5, primesieve). Proven.
- **P window**: written by the new engine with BPSW (MR base 2 + strong Lucas,
  Selfridge A) where the window reaches `MR_DET_BOUND` or above. No BPSW counterexample
  is known, none exists below 2^64; it is not proven above that.
- The label follows the proof status, not the engine: the new engine writes D below the
  bound.

## Storage layout

- D: unchanged, `10p{N}/source_primes/shard_NNNNN/PRIME_WINDOW_10p{N}_off_{tag}.bin`.
  No existing file is renamed or moved.
- P: `10p{N}/source_primes_P/shard_NNNNN/PRIME_WINDOW_10p{N}_off_{tag}_P.bin`, same
  sharding (window_sharding.py), same PGS2 format, same window grid.
- The `_P` suffix keeps a P file from matching any D reader's filename pattern even if
  it is copied into the wrong folder.
- Totals cache: per floor, D and P counts and bytes are kept separately; the global
  total counts D only, plus a separate P total.

## Acceptance criteria

### Engine
1. New engine id `pt1` ("partial sieve + primality test") in the Generation engine
   selector next to v4.1 / v5, and in `PRIMEATLAS_SCANNER_VERSION`; v5 stays default.
2. `pt1` output for a D window is byte-identical (gaps; header except `generated_at`)
   to v5's for the same window -- checked by a test at floors 10, 19, 22 and one window
   straddling 2^64.
3. For P windows: every prime of a v5 window at floor 25 is in the `pt1` P window and
   vice versa (test on at least one window); a sample at floors 26-30 agrees with GMP.
4. B is a user setting (GUI field + CLI flag / env), default `floor(N^(1/4))`,
   documented as arbitrary. Thread count follows the existing workers field.
5. `pt1` has no floor-sized buffer: its RAM is per-thread chunks, so the Auto window
   count is not RAM-capped for it (only by the existing per-run window cap and disk).
6. A window is D or P as a whole: one straddling `MR_DET_BOUND` is P.

### Storage and UI
7. Prime numbers -> Storage: one floor node per floor as today; its file list shows D
   and P files together, sorted by offset, with a D/P column; a window present in both
   stores is shown as two rows.
8. Floor totals show D and P separately (e.g. "D: 1.2e9 primes, P: 3.4e8").
9. Every engine plans its windows ("continue floor", new range, gap fill) from the
   store it writes into and ignores the other one, so both engines can generate the
   same ranges: v5 (and every sieve engine) sees D only; `pt1` sees the store its next
   window goes to -- P on floors >= 25, D below `MR_DET_BOUND` (on floor 24 D up to the
   bound, P above it).
10. Delete floor, full backup, restore, integrate and manifest include `source_primes_P/`.

### D proves P
11. When a D window is written and a P window for the same offset exists, the two are
    compared (decoded prime lists). Equal -> the P file is removed, the D window is
    listed as D/P in `10p{N}/DP_PROVEN.txt` and the totals move to D (the range is now
    proven, stored once, and still counts as present in the P store for `pt1`). Different -> both files are kept, the run log
    prints an ERROR line with the window and the first differing number, and the window
    is listed in `10p{N}/DP_MISMATCH.txt`. Never silently resolved.
12. A manual "Verify P against D" action in Storage runs 11 over a whole floor.

### Consumers (this branch)
13. Constellations, Research tabs, visualizations and the search box read D only, as
    today. P data is invisible to them until a later branch adds "prefer D, fall back to
    P with a visible marker" -- also for constellation hits found in P windows, which
    are P themselves and need their own store.

## Edge cases

- Floors 0..6 (the low-floor single-window path, B below 40): `pt1` refuses them;
  v5 handles them.
- Survivors that are perfect squares: the strong Lucas test needs a D with Jacobi = -1;
  a square never has one, so squares are rejected explicitly.
- Window straddling 2^64: arithmetic is u128 Montgomery (R = 2^128) for odd n < 2^127,
  which covers floor 37 (10^38 < 2^127); `pt1` refuses floors above 37.
- A run interrupted between writing a D window and removing the matching P file:
  the next comparison redoes it (idempotent).
- P window present, D generation for it fails mid-run: P stays, nothing removed.
- `DP_MISMATCH.txt` already lists a window: a later equal comparison removes its line.

## Implementation outline

- `prime_sieve/prime_sieve_engine_pt1.c`: chunked odd-only sieve to B + u128 Montgomery
  MR(13 bases)/BPSW; returns survivors' offsets per window.
- `prime_sieve/prime_sieve_pt1.py`: CLI of the other engines, writes through
  `pgs2_vector.py`, chooses the store per window.
- `prime_sieve/storage_kinds.py` (new, next to `window_sharding.py` because the WSL
  engines import it as well as the GUI): D/P folder names, filename patterns, label
  rule, each engine's planning view.
- `prime_sieve/pt1_plan.py` (new): B and chunk knobs, slab grouping.
- `prime_sieve/dp_verify.py` (new): the D-vs-P comparison of 11 and 12.
- `engine_options.py` / `engine_fields.py`: `pt1` and its B and chunk fields.
- Tests: `unitTests/test_engine_pt1.py`, `test_storage_kinds.py`, `test_dp_verify.py`,
  `test_primes_tab_dp.py`, `test_dp_settings.py`, plus updates to the engine-selector,
  storage, primes-tab and totals-bump tests.

## Decisions taken during implementation

- D proves P runs in `orchestrator_v3.py` after each batch, for every engine it drives,
  so the frozen engines stay untouched. Runs that bypass it (primesieve mode, Hybrid)
  are covered by the manual "Verify P against D".
- Only a new D window triggers the comparison. A P window written where D already
  exists is kept as is: comparing (and removing) it on write would make `pt1`'s
  continuation regenerate the same windows forever.
- An equal pair becomes one D/P window: the P file is removed and the D file's tag is
  listed in `10p{N}/DP_PROVEN.txt` (a marker, since D files keep their names). `pt1`
  plans with the D/P windows as part of its store, so a proven window is neither stored
  twice nor regenerated; an entry counts only while its D file exists. A later mismatch
  drops the entry. Full backup, restore and integrate merge the lists as a union. The
  Storage tab shows such a window as "D/P"; its primes count in the D total, not in
  "P primes".
- `pt1` knobs: B (`PRIMEATLAS_PT1_B`, 0 = floor(N^(1/4)), clamped to isqrt of the run's
  lowest number and below 2^32) and the chunk size (`PRIMEATLAS_PT1_CHUNK_KB`, default
  4096), both GUI fields.
- Full backup / restore and integrate copy both stores (routed by the `_P` suffix); the
  metadata manifest lists D only, since restoring it regenerates windows with a sieve
  engine. Restore never uses `pt1` even when it is the persisted engine.
- Benchmark: every benchmark_log.csv row gets a kind (D, P, or D+P for a `pt1` run on
  floor 24 across the bound), derived on read from the engine and the window range, so
  older rows and the frozen engines' rows need no new column. The table shows it next
  to the engine; a `pt1` P run is its own chart line ("pt1 P"), never sharing a line
  with D measurements.
- The Generation tab's incremental total bumps skip `pt1` runs from floor 24 on (their
  windows are P, or mixed on floor 24); P totals come from the P store's rescan.
- Storage tab: the prime columns stay per store (D in "Primes", P in "P primes"); Files,
  Size and the status bar's disk total count both stores, since they describe the disk.
  Generation times are not split by store.
- `pt1` progress: the line reads "(done/total chunks)", which the Generation tab's progress
  bar parses like the engines' "batches"; stdout is line-buffered because the GUI log is a
  file.
- The benchmark row's prime count is re-read from the written windows' headers (parallel
  instances share the scanner handoff file), unbuffered and by `workers` threads: one open
  per window over WSL's /mnt drive, about 27 s for 100,000 windows instead of minutes.

## Open decisions (default = recommendation, taken on silence)

- Existing D files are not renamed to carry `_D`: D is implicit in today's name and
  shown as "D" in the UI. Renaming means rewriting hundreds of thousands of files and
  every backup.
