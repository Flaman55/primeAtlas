# PrimeAtlas sieve benchmark

How fast the PrimeAtlas generation pipeline sieves, what it costs in RAM and disk, how that
cost is built up, and how it compares with primesieve and PARI/GP. Two engines are measured
on the same machine with the same harness and run shapes:

- **v4.1** (2026-10-29): raw files in [`benchmarks/2026-10-29/results/`](benchmarks/2026-10-29/results/),
  produced by [`benchmarks/2026-10-29/bench_atlas.py`](benchmarks/2026-10-29/bench_atlas.py);
- **v5** (2026-10-31): raw files in [`benchmarks/2026-10-31_v5/results/`](benchmarks/2026-10-31_v5/results/),
  produced by [`benchmarks/2026-10-31_v5/bench_atlas.py`](benchmarks/2026-10-31_v5/bench_atlas.py)
  through [`run_v5b.sh`](benchmarks/2026-10-31_v5/run_v5b.sh) and
  [`run_low24.sh`](benchmarks/2026-10-31_v5/run_low24.sh).

Both engines produce byte-identical PGS2 files and the same prime counts on every floor
(`unitTests/test_engine_v5_identity.py`; every count in both result sets agrees).

## Summary

On one home desktop (Ryzen 9 5900X, 64 GB RAM), sieving 10^10 consecutive numbers with
24 workers:

| Start of range | v4.1 | v5 | Peak RAM, v5 | primesieve 12.15, 24 threads |
|---|---|---|---|---|
| 10^19 | 63 s (159 M numbers/s) | 5.8 s (1.74 G numbers/s) | 1.7 GB | 3.0 s |
| 10^22 | 76 s (132 M numbers/s) | 7.9 s (1.27 G numbers/s) | 1.7 GB | not supported (> 2^64) |
| 10^25 | 121 s (82 M numbers/s) | 70 s (143 M numbers/s) | 1.7 GB | not supported (> 2^64) |

- v5 is faster than v4.1 at every measured point: 1.7–13 times on 10^10 numbers with
  24 workers, 1.02–6.8 times on one thread.
- Above 2^64 (about 1.8·10^19) primesieve rejects the input; PrimeAtlas keeps going.
- With the primes written to disk as indexed, searchable files: v5 takes 31–36 s per 10^10
  numbers from 10^10 to 10^23 and 92 s at 10^25 (v4.1: 154–196 s). 427 million primes take
  428 MB (about one byte per prime); primesieve's text output for the same primes is 5.13 GB.
- Sieving consecutive windows as one run is what makes deep floors practical: at 10^25 a
  single window of 10^7 numbers takes 63 s with v5, a thousand consecutive windows take
  70 s (about 900 times faster per number).
- On one thread at 10^25: 81 s per 10^9 numbers including all preparation (v4.1: 113 s),
  about 4.8 times faster than stock PARI/GP's `forprime` on a CPU with practically the same
  single-thread score (see [Single thread and PARI/GP](#single-thread-and-parigp)).

## Environment

| | |
|---|---|
| CPU | AMD Ryzen 9 5900X, 12 cores / 24 threads |
| RAM | 64 GB DDR4-3600 CL18 (WSL sees 54.9 GB) |
| Disk | Samsung 990 EVO Plus 2 TB NVMe |
| OS | Windows 11 + WSL 2.7.11, kernel 6.18.33.2-microsoft-standard-WSL2 |
| PrimeAtlas v4.1 | 1.1.0, engine `prime_sieve_v4_1.py` driven by `orchestrator_v3.py` |
| PrimeAtlas v5 | commit cc71d97, engine `prime_sieve_v5.py` driven by `orchestrator_v3.py` with `PRIMEATLAS_SCANNER_VERSION=v5` ¹ |
| primesieve | 12.15 (command-line tool) |

¹ `benchmarks/2026-10-31_v5/commit.txt` records the measured tree as 6697ae0 plus the
uncommitted changes later committed as cc71d97; the `prime_sieve_engine_v5.so` hash it
records is the one in cc71d97.

The output folder is on the Windows drive, reached from WSL through `/mnt/h`, which is
where a PrimeAtlas storage normally lives. The engine is chosen in the Generation settings
(v4.1 is the default).

## What v5 changes

v4.1 marks one bit per number in a shared buffer, and every sieving prime strides the whole
buffer with an atomic OR per hit. v5 keeps the shared buffer and the per-prime 128-bit phase,
and changes how the buffer is marked:

- the buffer holds odd numbers only (half the bits, p = 2 never sieved);
- primes below one segment (128 KiB of bits by default) mark cache-sized segments of buffer
  slices in the worker processes, after the segmented sieve of Bays and Hudson (1977);
- the remaining sieving primes go through one multi-threaded bucket pass: hits are grouped
  per buffer region and applied while that region is in cache;
- the phase `first mod p` comes from a double-precision quotient with an exact correction;
- PGS2 window files are written by a vectorized writer.

Segment size, bucket region size and bucket memory are user settings (Generation settings,
`PRIMEATLAS_V5_SEGMENT_KB`, `PRIMEATLAS_V5_REGION_KB`, `PRIMEATLAS_V5_BUCKET_MB`); all
numbers here use the defaults (128 KiB, 1024 KiB, 1024 MiB).

## Method

- Each run sieves `windows × window width` consecutive numbers starting at 10^N, in two
  modes: **count** (nothing written) and **write** (prime windows written as PGS2 files).
- PrimeAtlas runs exactly as the GUI launches it (`orchestrator_v3.py`, 2 batches per
  worker), into an empty scratch storage deleted after every run.
- Time is wall-clock time of the whole pipeline. The pipeline's own log splits it into the
  sieve phase and the unpack/write phase.
- RAM is the peak summed PSS of the whole process tree, sampled every 0.5 s; a buffer shared
  by all workers counts once.
- primesieve times are its own reported `Seconds:`. `--print` is single-threaded by design,
  so its write test was run once, at 10^10. primesieve was not rerun for v5.
- v5 times are single runs except: series E is the median of three runs; one run of
  series C at 10^20 (26.9 s, its unpack phase 23.2 s against 3–5 s on the other floors) was
  repeated three times and the table gives their median (8.3 s); all four files are in the
  results. Runs under one second are compared in [Short runs](#short-runs).

Series:

| Series | Workers | Run shape | Numbers per run | Floors |
|---|---|---|---|---|
| A | 24 | 1000 windows × 10^7 | 10^10 | 10, 13, 16, 19–25 |
| B | 24 and 1 | 1 window × 10^7 | 10^7 | 10, 13, 16, 19–25 |
| C | 24 | 1 window × 10^10 | 10^10 | 10, 13, 16, 19, 20, 22, 25 |
| D | 1 | 100 windows × 10^7 | 10^9 | 10, 13, 16, 19–25 |
| E | 1 | 1000 windows × 10^7 | 10^10 | 25 |

## Results: 10^10 numbers, 24 workers (series A)

Count only:

| Floor | v4.1 | v5 | v5 rate | Speed-up | Peak RAM v4.1 / v5 | primesieve count |
|---|---|---|---|---|---|---|
| 10^10 | 34.9 s | 3.9 s | 2.59 G/s | 9.0× | 1.4 / 0.6 GB | 0.10 s |
| 10^13 | 45.2 s | 4.3 s | 2.32 G/s | 10.5× | 1.6 / 0.8 GB | 0.22 s |
| 10^16 | 53.9 s | 4.3 s | 2.32 G/s | 12.5× | 1.9 / 1.6 GB | 0.69 s |
| 10^19 | 62.7 s | 5.8 s | 1.74 G/s | 10.9× | 2.4 / 1.7 GB | 3.0 s |
| 10^20 | 67.4 s | 5.4 s | 1.87 G/s | 12.6× | 1.9 / 1.7 GB | — |
| 10^21 | 71.7 s | 6.2 s | 1.62 G/s | 11.6× | 1.3 / 1.7 GB | — |
| 10^22 | 75.9 s | 7.9 s | 1.27 G/s | 9.6× | 2.3 / 1.7 GB | — |
| 10^23 | 79.1 s | 12.1 s | 826 M/s | 6.5× | 2.3 / 1.7 GB | — |
| 10^24 | 84.2 s | 26.4 s | 379 M/s | 3.2× | 1.6 / 1.7 GB | — |
| 10^25 | 121.2 s | 70.0 s | 143 M/s | 1.7× | 1.5 / 1.7 GB | — |

With write (sieve / write phase in brackets):

| Floor | v4.1 | v5 | Speed-up | Files, both engines |
|---|---|---|---|---|
| 10^10 | 183.9 s (30.7 / 146.9) | 31.2 s (0.4 / 25.1) | 5.9× | 428 MB |
| 10^13 | 165.8 s (41.3 / 118.5) | 32.5 s (0.9 / 25.8) | 5.1× | 337 MB |
| 10^16 | 156.3 s (50.0 / 100.4) | 33.8 s (1.7 / 25.9) | 4.6× | 278 MB |
| 10^19 | 153.8 s (59.6 / 87.8) | 31.3 s (2.4 / 22.8) | 4.9× | 239 MB |
| 10^20 | 156.8 s (66.5 / 84.1) | 31.8 s (2.8 / 22.4) | 4.9× | 229 MB |
| 10^21 | | 34.5 s (3.9 / 24.2) | | 220 MB |
| 10^22 | 157.3 s (73.0 / 78.2) | 32.7 s (5.5 / 21.3) | 4.8× | 212 MB |
| 10^23 | | 36.0 s (9.7 / 20.4) | | 204 MB |
| 10^24 | | 50.7 s (25.7 / 19.2) | | 198 MB |
| 10^25 | 195.7 s (118.7 / 70.7) | 91.9 s (67.8 / 18.5) | 2.1× | 192 MB |

The files of both engines have the same size to the byte on every floor where both wrote.

**Storage at 10^10:** primesieve `--print` writes 427,154,205 primes as 5.13 GB of decimal
text in 30.6 s. PrimeAtlas writes the same primes as 428 MB in 1,000 indexed PGS2 window
files (gap-delta + varint), the format the Storage, Search and Research tabs read directly.

## Consecutive windows versus a single window (series B and C)

| Floor | 1 window of 10^7, sieve phase (24 workers), v4.1 / v5 | 1000 windows of 10^7, whole run, v4.1 / v5 | Per-number speed-up, v5 |
|---|---|---|---|
| 10^19 | 0.11 / 0.07 s | 62.7 / 5.8 s | ~13× |
| 10^22 | 1.96 / 1.59 s | 75.9 / 7.9 s | ~200× |
| 10^24 | 19.7 / 18.2 s | 84.2 / 26.4 s | ~690× |
| 10^25 | 71.5 / 63.1 s | 121.2 / 70.0 s | ~900× |

One window of width 10^10 (series C) covers the same numbers as 1000 windows of 10^7:

| Floor | 10^10 | 10^13 | 10^16 | 10^19 | 10^20 | 10^22 | 10^25 |
|---|---|---|---|---|---|---|---|
| v4.1 | 46.5 s | 60.4 s | 65.9 s | 74.7 s | 80.9 s | 87.5 s | 137.7 s |
| v5 | 5.9 s | 4.6 s | 7.1 s | 8.2 s | 8.3 s | 11.6 s | 75.3 s |

It needs about 10 GB RAM with v5 (20 GB with v4.1) instead of 1.7 GB and is not faster than
1000 windows of 10^7. What matters is the length of the contiguous range handled by one run,
not the width of a window; the default of 1000 windows of 10^7 stays.

## Cost model

A run over Δ numbers starting at N costs

    T(N, Δ) = F(N) + Δ · m(N)

- **F(N), preparation:** for every sieving prime p ≤ √N, the engine gets p from the
  primesieve iterator and computes once, in 128-bit arithmetic, where p first strikes the
  range. That phase is then reused across the whole range. F does not depend on Δ.
- **m(N), marking:** the cost per number of crossing off multiples inside the range.

F is measured by series B (one window of 10^7, where Δ·m is negligible), m by the
difference between series D or E and series B. v4.1 / v5:

| Floor | π(√N), sieving primes | F, 1 worker | F per sieving prime | m, 1 worker (s per 10^9) | F, 24 workers | m, 24 workers (s per 10^9) |
|---|---|---|---|---|---|---|
| 10^10 | 9,592 | 0.07 / 0.01 s | — | 7.6 / 0.4 | 0.06 / 0.01 s | 3.2 / 0.04 |
| 10^13 | 227,647 | 0.07 / 0.02 s | — | 9.8 / 0.8 | 0.06 / 0.02 s | 4.2 / 0.08 |
| 10^16 | 5,761,455 | 0.10 / 0.07 s | — | 11.5 / 1.3 | 0.06 / 0.02 s | 5.1 / 0.15 |
| 10^19 | 151,876,932 | 0.70 / 0.64 s | 4.6 / 4.2 ns | 14.2 / 2.9 | 0.11 / 0.07 s | 6.0 / 0.22 |
| 10^20 | 455,052,511 | 2.1 / 1.9 s | 4.6 / 4.1 ns | 16.8 / 4.4 | 0.24 / 0.17 s | 6.4 / 0.25 |
| 10^21 | 1,367,199,811 | 6.6 / 5.9 s | 4.8 / 4.3 ns | 19.9 / 4.7 | 0.68 / 0.50 s | 6.8 / 0.30 |
| 10^22 | 4,118,054,813 | 21.7 / 19.2 s | 5.3 / 4.7 ns | 23.7 / 6.8 | 1.96 / 1.59 s | 7.1 / 0.36 |
| 10^23 | 12,431,880,460 | 71.0 / 63.4 s | 5.7 / 5.1 ns | 29.2 / 6.8 | 6.4 / 5.3 s | 7.0 / 0.41 |
| 10^24 | 37,607,912,018 | 238.6 / 216.5 s | 6.3 / 5.8 ns | 31.4 / 5.3 | 19.7 / 18.2 s | 6.2 / 0.48 |
| 10^25 | 113,983,535,775 | 799.5 / 734.4 s | 7.0 / 6.4 ns | 32.8 / 7.5 | 71.5 / 63.1 s | 4.7 / 0.34 |

(π(√N) counted with primesieve up to ⌊√(10^N)⌋. m at 10^25 with one worker comes from
series E, the others from series D.)

What the table shows:

- **v5 cuts m, not F.** Marking is 4–19 times cheaper on one thread and 13–80 times cheaper
  with 24 workers; F, the per-prime iterator and phase, is 8–12 % lower on deep floors and
  grows with π(√N), about 3.2 times per floor, as before. With 24 workers F scales 11–12
  times, about the 5900X's 12 physical cores.
- **At deep floors a v5 run is almost all F.** At 10^25 with 24 workers a run of 10^10
  numbers spends 63 s on F and about 3 s on marking (v4.1: 71.5 s and 47 s). m is that
  small next to F there that its run-to-run spread is of the same order as its
  floor-to-floor differences, so its dip at 10^24–10^25 says little.
- **The longer the range, the more F is amortized**, and with v5 this matters more than
  with v4.1: a run of 10^11 numbers at 10^25 would cost about 63 + 34 s by the model, about
  seven times the throughput of a run of 10^10 (not measured). RAM grows with the range (one bit per odd number
  in the shared buffer, plus the buckets), so the range a run can take is bounded by memory.

## Single thread and PARI/GP

| Floor | v4.1, 1 worker, s per 10^9 | v5, 1 worker, s per 10^9 | Stock PARI/GP `forprime`, s per 10^9 ² | Ratio, v5 |
|---|---|---|---|---|
| 10^19 | 15.6 (run of 10^9) | 4.4 (run of 10^9) | ~349 | ~79× |
| 10^20 | 19.6 (run of 10^9) | 7.3 (run of 10^9) | ~355 | ~49× |
| 10^22 | 46.3 (run of 10^9) | 26.9 (run of 10^9) | ~367 | ~14× |
| 10^25 | 113 (run of 10^10) | 81 (run of 10^10) | ~388 | ~4.8× |
| 10^25, long-range limit | ~33 (m only) | ~7.5 (m only) | ~388 | ~52× |

² From Ilya Zakharevich's measurements, pari-dev, September 2024: "the measured timing for
forprime via nextprime() is >400 sec/giganumber", with the fit
`0.025·log10(N)^2.5 + 310` s per 10^9 for N ≫ 10^19, used here. They were measured on an
Intel Core i5-13500T. PassMark rates its single thread at 3,576 and the 5900X at 3,465, so
the two CPUs are within 3% per thread. All threads: 22,418 versus 38,880.

PARI/GP's cost per number barely depends on N, because `nextprime` tests candidates one by
one (trial division, then BPSW) and both 10^19 and 10^25 fit in two 64-bit words. A sieve's
preparation cost grows with √N instead, which is why the ratio falls with depth and why a
long contiguous range matters.

PARI/GP can also run in parallel (`parforprime`); how that scales over this range has not
been measured, so this table compares one thread with one thread only.

## Short runs

Runs under one second are mostly process start-up (the orchestrator and the engine module
take about 0.3 s before any sieving). The v4.1 harness of 2026-10-29 rounded these runs up
to its 0.5 s sampling step, so v4.1 and v5 were rerun alternately with the same harness
(medians; files `ab_*` and `low24_*`):

| Floor | 1 window of 10^7, 24 workers (10 rounds), v4.1 / v5 | 1 window of 10^7, 1 worker (3 rounds), v4.1 / v5 |
|---|---|---|
| 10^10 | 0.576 / 0.538 s | 0.643 / 0.602 s |
| 10^13 | 0.578 / 0.555 s | 0.648 / 0.592 s |
| 10^16 | 0.574 / 0.551 s | 0.728 / 0.674 s |
| 10^19 | 0.621 / 0.613 s | 1.304 / 1.280 s |
| 10^20 | 0.776 / 0.752 s ³ | 2.608 / 2.512 s |
| 10^21 | 1.104 / 1.068 s ³ | 7.292 / 6.350 s |

³ 3 rounds.

## Above 2^64

- primesieve, the source of PrimeAtlas's sieving primes, works up to 2^64.
- Harald Helfgott, *An improved sieve of Eratosthenes* (arXiv:1712.09130, section 6):
  "on the range n > 2^64, it seems harder to find highly optimized implementations of the
  traditional algorithm for comparison."
- Zakharevich's experimental (pre-alpha) PARI/GP sieving patch reports 11.3 s per 10^9
  numbers up to 10^25 with a 110 GB prime table and an 11 GB arena, excluding the
  preparation of primes up to √N; the thread count is not stated. PrimeAtlas v5 with 24
  workers spends 7.0 s per 10^9 at 10^25 including all preparation (v4.1: 12.1 s), in
  1.7 GB.
- For counting primes without listing them, primecount computes π(x) far faster than any
  sieve at every scale; PrimeAtlas's π(x) research tab uses it as a data source.

## Scope

- Below 2^64, primesieve counts a range 2–40 times faster than PrimeAtlas v5 (v4.1: 20–350
  times); the gap narrows towards 2^64. primesieve also uses a wheel, which PrimeAtlas does
  not.
- The write phase is bounded by the WSL-to-Windows file system (`/mnt/h`); with v5 it is
  55–80 % of a write run up to 10^23.
- Peak RAM of v5 on one thread is higher than v4.1's (series D: up to 1.1 GB against 0.2 GB),
  most of it the bucket memory; `PRIMEATLAS_V5_BUCKET_MB` lowers it.

## Reproduce

Inside WSL, from the repository root, with primesieve and psutil installed:

    BENCH_ROOT=/mnt/<drive> bash benchmarks/2026-10-31_v5/run_v5b.sh
    BENCH_ROOT=/mnt/<drive> bash benchmarks/2026-10-31_v5/run_low24.sh

or one series at a time:

    cd benchmarks/2026-10-31_v5
    PRIMEATLAS_SCANNER_VERSION=v5 BENCH_TMP=/mnt/<drive>/bench_tmp_new python3 bench_atlas.py a.json 10,13,16,19,20,22,25 1000 10000000 count,write 0 24

Arguments: output file, floors, windows per run, window width, modes, run primesieve (0/1),
workers. `PRIMEATLAS_SCANNER_VERSION=v4.1` measures v4.1 with the same harness. The full v5
set takes about two hours.

## Sources

- C. Bays, R. H. Hudson, *The segmented sieve of Eratosthenes and primes in arithmetic
  progressions to 10^12*, BIT 17 (1977), 121–127.
- primesieve: https://github.com/kimwalisch/primesieve
- primecount: https://github.com/kimwalisch/primecount
- H. A. Helfgott, *An improved sieve of Eratosthenes*: https://arxiv.org/abs/1712.09130
- I. Zakharevich, pari-dev, September 2024: https://pari.math.u-bordeaux.fr/archives/pari-dev-2409/msg00016.html
- PassMark, Ryzen 9 5900X vs Core i5-13500T (retrieved 2026-10-29): https://www.cpubenchmark.net/compare/3870vs5239/AMD-Ryzen-9-5900X-vs-Intel-i5-13500T
