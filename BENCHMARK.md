# PrimeAtlas sieve benchmark (2026-10-29)

How fast the PrimeAtlas generation pipeline sieves, what it costs in RAM and disk, how that
cost is built up, and how it compares with primesieve and PARI/GP. Every number here comes
from the raw files in [`benchmarks/2026-10-29/results/`](benchmarks/2026-10-29/results/),
produced by [`benchmarks/2026-10-29/bench_atlas.py`](benchmarks/2026-10-29/bench_atlas.py).

## Summary

On one home desktop (Ryzen 9 5900X, 64 GB RAM), sieving 10^10 consecutive numbers:

| Start of range | PrimeAtlas, 24 workers | Peak RAM | primesieve 12.15, 24 threads |
|---|---|---|---|
| 10^19 | 63 s (159 M numbers/s) | 2.4 GB | 3.0 s |
| 10^22 | 76 s (132 M numbers/s) | 2.3 GB | not supported (> 2^64) |
| 10^25 | 121 s (82 M numbers/s) | 1.5 GB | not supported (> 2^64) |

- Above 2^64 (about 1.8·10^19) primesieve rejects the input; PrimeAtlas keeps going.
- With the primes written to disk as indexed, searchable files: 154–196 s per 10^10 numbers
  on every floor from 10^13 to 10^25. 427 million primes take 428 MB (about one byte per
  prime); primesieve's text output for the same primes is 5.13 GB.
- Sieving consecutive windows as one run is what makes deep floors practical: at 10^25 a
  single window of 10^7 numbers takes 72 s, a thousand consecutive windows take 121 s
  (about 600 times faster per number).
- On one thread at 10^25: 113 s per 10^9 numbers including all preparation, about 3.4 times
  faster than stock PARI/GP's `forprime` on a CPU with practically the same single-thread
  score (see [Single thread and PARI/GP](#single-thread-and-parigp)).

## Environment

| | |
|---|---|
| CPU | AMD Ryzen 9 5900X, 12 cores / 24 threads |
| RAM | 64 GB DDR4-3600 CL18 (WSL sees 54.9 GB) |
| Disk | Samsung 990 EVO Plus 2 TB NVMe |
| OS | Windows 11 + WSL 2.7.11, kernel 6.18.33.2-microsoft-standard-WSL2 |
| PrimeAtlas | 1.1.0, engine `prime_sieve_v4_1.py` driven by `orchestrator_v3.py` |
| primesieve | 12.15 (command-line tool) |

The output folder is on the Windows drive, reached from WSL through `/mnt/h`, which is
where a PrimeAtlas storage normally lives.

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
  so its write test was run once, at 10^10.
- Prime counts of both tools agree on every floor where both run.

Series:

| Series | Workers | Run shape | Numbers per run | Floors |
|---|---|---|---|---|
| A | 24 | 1000 windows × 10^7 | 10^10 | 10, 13, 16, 19–25 |
| B | 24 and 1 | 1 window × 10^7 | 10^7 | 10, 13, 16, 19–25 |
| C | 24 | 1 window × 10^10 | 10^10 | 10, 13, 16, 19, 20, 22, 25 |
| D | 1 | 100 windows × 10^7 | 10^9 | 10, 13, 16, 19–25 |
| E | 1 | 1000 windows × 10^7 | 10^10 | 25 |

## Results: 10^10 numbers, 24 workers (series A)

| Floor | Count only | Rate | With write | Sieve / write phase | Peak RAM | primesieve count |
|---|---|---|---|---|---|---|
| 10^10 | 34.9 s | 287 M/s | 183.9 s | 30.7 / 146.9 s | 1.3–1.6 GB | 0.10 s |
| 10^13 | 45.2 s | 221 M/s | 165.8 s | 41.3 / 118.5 s | 1.6 GB | 0.22 s |
| 10^16 | 53.9 s | 185 M/s | 156.3 s | 50.0 / 100.4 s | 1.3–1.9 GB | 0.69 s |
| 10^19 | 62.7 s | 159 M/s | 153.8 s | 59.6 / 87.8 s | 1.3–2.4 GB | 3.0 s |
| 10^20 | 67.4 s | 148 M/s | 156.8 s | 66.5 / 84.1 s | 1.6–1.9 GB | — |
| 10^21 | 71.7 s | 139 M/s | | | 1.3 GB | — |
| 10^22 | 75.9 s | 132 M/s | 157.3 s | 73.0 / 78.2 s | 1.9–2.3 GB | — |
| 10^23 | 79.1 s | 126 M/s | | | 2.3 GB | — |
| 10^24 | 84.2 s | 119 M/s | | | 1.6 GB | — |
| 10^25 | 121.2 s | 82 M/s | 195.7 s | 118.7 / 70.7 s | 1.5–2.3 GB | — |

**Storage at 10^10:** primesieve `--print` writes 427,154,205 primes as 5.13 GB of decimal
text in 30.6 s. PrimeAtlas writes the same primes as 428 MB in 1,000 indexed PGS2 window
files (gap-delta + varint), the format the Storage, Search and Research tabs read directly.

## Consecutive windows versus a single window (series B and C)

| Floor | 1 window of 10^7, sieve phase (24 workers) | 1000 windows of 10^7, whole run | Per-number speed-up |
|---|---|---|---|
| 10^19 | 0.11 s | 62.7 s | ~2× |
| 10^22 | 1.96 s | 75.9 s | ~26× |
| 10^24 | 19.7 s | 84.2 s | ~230× |
| 10^25 | 71.5 s | 121.2 s | ~590× |

One window of width 10^10 (series C) covers the same numbers as 1000 windows of 10^7 but
is slower (137.7 s at 10^25) and needs about 20 GB RAM instead of about 2 GB. What matters
is the length of the contiguous range handled by one run, not the width of a window; the
default of 1000 windows of 10^7 stays.

## Cost model

A run over Δ numbers starting at N costs

    T(N, Δ) = F(N) + Δ · m(N)

- **F(N), preparation:** for every sieving prime p ≤ √N, the engine gets p from the
  primesieve iterator and computes once, in 128-bit arithmetic, where p first strikes the
  range. That phase is then reused across the whole range. F does not depend on Δ.
- **m(N), marking:** the cost per number of crossing off multiples inside the range.

F is measured by series B (one window of 10^7, where Δ·m is negligible), m by the
difference between series D or E and series B:

| Floor | π(√N), sieving primes | F, 1 worker | F per sieving prime | m, 1 worker (s per 10^9) | F, 24 workers | m, 24 workers (s per 10^9) |
|---|---|---|---|---|---|---|
| 10^10 | 9,592 | 0.07 s | — | 7.6 | 0.06 s | 3.2 |
| 10^13 | 227,647 | 0.07 s | — | 9.8 | 0.06 s | 4.2 |
| 10^16 | 5,761,455 | 0.10 s | — | 11.5 | 0.06 s | 5.1 |
| 10^19 | 151,876,932 | 0.70 s | 4.6 ns | 14.2 | 0.11 s | 6.0 |
| 10^20 | 455,052,511 | 2.1 s | 4.6 ns | 16.8 | 0.24 s | 6.4 |
| 10^21 | 1,367,199,811 | 6.6 s | 4.8 ns | 19.9 | 0.68 s | 6.8 |
| 10^22 | 4,118,054,813 | 21.7 s | 5.3 ns | 23.7 | 1.96 s | 7.1 |
| 10^23 | 12,431,880,460 | 71.0 s | 5.7 ns | 29.2 | 6.4 s | 7.0 |
| 10^24 | 37,607,912,018 | 238.6 s | 6.3 ns | 31.4 | 19.7 s | 6.2 |
| 10^25 | 113,983,535,775 | 799.5 s | 7.0 ns | 32.8 | 71.5 s | 4.7 |

(π(√N) counted with primesieve up to ⌊√(10^N)⌋. m at 10^25 with one worker comes from
series E, the others from series D.)

What the table shows:

- **F grows with π(√N), about 3.2 times per floor.** From 10^19 upward one sieving prime
  costs 4.6–7.0 ns on one thread; F reaches 800 s at 10^25. With 24 workers F scales 11–12
  times, about the 5900X's 12 physical cores.
- **m grows slowly.** On one thread it rises from 7.6 to 32.8 s per 10^9 between 10^10 and
  10^25, as more of the crossing-off goes to large primes whose strikes land far apart in
  memory. With 24 workers m stays at 3–7 s per 10^9. Its dip at 10^24–10^25 is measured but
  not yet explained.
- **The longer the range, the more F is amortized.** At 10^25 with 24 workers a run of 10^10
  numbers spends 71.5 s on F and 47 s on marking; the model puts the limit for very long
  ranges near 210 M numbers/s at that floor. RAM grows with the range (one bit per number in
  the shared buffer), so the range a run can take is bounded by memory.

## Single thread and PARI/GP

| Floor | PrimeAtlas, 1 worker, s per 10^9 | Stock PARI/GP `forprime`, s per 10^9 ¹ | Ratio |
|---|---|---|---|
| 10^19 | 15.6 (run of 10^9) | ~349 | ~22× |
| 10^20 | 19.6 (run of 10^9) | ~355 | ~18× |
| 10^22 | 46.3 (run of 10^9) | ~367 | ~8× |
| 10^25 | 113 (run of 10^10) | ~388 | ~3.4× |
| 10^25, long-range limit | ~33 (m only) | ~388 | ~12× |

¹ From Ilya Zakharevich's measurements, pari-dev, September 2024: "the measured timing for
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

## Above 2^64

- primesieve, the fastest prime sieve available and the source of PrimeAtlas's sieving
  primes, works up to 2^64.
- Harald Helfgott, *An improved sieve of Eratosthenes* (arXiv:1712.09130, section 6):
  "on the range n > 2^64, it seems harder to find highly optimized implementations of the
  traditional algorithm for comparison."
- Zakharevich's experimental (pre-alpha) PARI/GP sieving patch reports 11.3 s per 10^9
  numbers up to 10^25 with a 110 GB prime table and an 11 GB arena, excluding the
  preparation of primes up to √N; the thread count is not stated. PrimeAtlas with 24
  workers spends 12.1 s per 10^9 at 10^25 including all preparation, in 1.5–2.4 GB.
- For counting primes without listing them, primecount computes π(x) far faster than any
  sieve at every scale; PrimeAtlas's π(x) research tab uses it as a data source.

## Scope

- Below 2^64, primesieve counts a range 20–350 times faster than PrimeAtlas (the gap
  narrows towards 2^64) and prints it faster. PrimeAtlas's marking is a plain loop over a shared bit buffer; primesieve's
  cache-sized segments, wheel and bucket sieve are not used for marking.
- The write phase is bounded by the WSL-to-Windows file system (`/mnt/h`); it is 60–80 % of
  a write run on low floors.
- Times are single runs, not averages.

## Reproduce

Inside WSL, from the repository root, with primesieve and psutil installed:

    cd benchmarks/2026-10-29
    BENCH_TMP=/mnt/<drive>/bench_tmp_new python3 bench_atlas.py a.json 10,13,16,19,20,22,25 1000 10000000 count,write 1 24
    BENCH_TMP=/mnt/<drive>/bench_tmp_new python3 bench_atlas.py b.json 10,13,16,19,20,22,25 1 10000000 count 0 24
    BENCH_TMP=/mnt/<drive>/bench_tmp_new python3 bench_atlas.py d.json 10,13,16,19,20,22,25 100 10000000 count 1 1

Arguments: output file, floors, windows per run, window width, modes, run primesieve (0/1),
workers. Each series takes from a few minutes to about an hour.

## Sources

- primesieve: https://github.com/kimwalisch/primesieve
- primecount: https://github.com/kimwalisch/primecount
- H. A. Helfgott, *An improved sieve of Eratosthenes*: https://arxiv.org/abs/1712.09130
- I. Zakharevich, pari-dev, September 2024: https://pari.math.u-bordeaux.fr/archives/pari-dev-2409/msg00016.html
- PassMark, Ryzen 9 5900X vs Core i5-13500T (retrieved 2026-10-29): https://www.cpubenchmark.net/compare/3870vs5239/AMD-Ryzen-9-5900X-vs-Intel-i5-13500T
