# Engine series 2026-11-16: v7.2, v7.4, pt1 and the Pseudosquares Prime Sieve

One session on one machine, 2026-11-16 00:00–05:51 (local time), 204 runs, every run rc 0,
prime counts equal between repeats and between engines wherever two engines share a point.

- [`bench_engines.py`](bench_engines.py): the series (plan, order, scratch storage, CSV).
- [`results.csv`](results.csv): one row per run, the run's own `benchmark_log.csv` row
  plus the protocol fields (order, wall time, peak PSS).
- [`results_meta.txt`](results_meta.txt): tool versions, `lscpu`, `free -m`, engine
  library hashes; [`commit.txt`](commit.txt): the measured tree.
- [`tables.py`](tables.py): the tables below, computed from `results.csv`.

## Machine

| | |
|---|---|
| CPU | AMD Ryzen 9 5900X, 12 cores / 24 threads, L3 32 MB |
| RAM | 64 GB DDR4-3600 CL18 (WSL sees 48 GB) |
| OS | Windows 11 + WSL 2, kernel 6.18.33.2-microsoft-standard-WSL2, Ubuntu 26.04 |
| Tools | Python 3.14.4, numpy 2.5.1, gcc 15.2.0, primesieve 12.16 |
| Pseudosquares Prime Sieve | 1.2 (commit fccb96e), count mode |

## Method

- Every run sieves the given number of consecutive numbers from `10^floor` in windows of
  10^7, with 24 threads (24 workers, 1 batch per worker), through
  `prime_sieve/orchestrator_v3.py` exactly as the GUI launches it, or through
  `prime_sieve/pseudosquares_native.py` for the Pseudosquares Prime Sieve.
- Order: Pseudosquares Prime Sieve at 10^9 numbers; then for each size and floor
  v7.2, v7.4, v7.4, v7.2; then pt1, pt1-pss, pt1-pss, pt1 at 10^9 numbers (pt1 alone twice at
  floor 35, which pt1-pss refuses); then the Pseudosquares Prime Sieve again. Each engine
  takes an early and a late slot, so slow drifts of the machine cancel.
- The Atlas engines write their windows; pt1 runs without the verification P -> D.
- **Speed = numbers / (run time - write time)**, the mean of the two runs of a point. The
  write phase is left out because it depends on the disk, not on the engine, and because the
  Pseudosquares Prime Sieve in count mode writes nothing. In this series the scratch storage
  was on a Windows drive reached through `/mnt/h`, where writing 10^11 numbers' windows
  took 15–24 s per run (about 1.5 s in earlier runs from the GUI); the times are in
  `results.csv` (`write_seconds`).
- Each program runs in its own configuration: the Pseudosquares Prime Sieve at 10^9 numbers,
  as in its own repository; the Atlas engines at the widths they are built for (10^11 for
  v7).
- In the tables `v7` is v7.4 (`PRIMEATLAS_SCANNER_VERSION=v7`).
- pt1 writes probable primes (BPSW); pt1-pss and the Pseudosquares Prime Sieve prove theirs;
  v7.2 and v7.4 are exact sieves.

### v7.4, v7.2 and the Pseudosquares Prime Sieve (M numbers/s)

| floor | PSS 10^9 | v7.4 10^9 | v7.4 10^10 | v7.4 10^11 | v7.2 10^11 | v7.4 / v7.2 at 10^11 |
|---|---|---|---|---|---|---|
| 18 | 203 | 2,054 | 7,310 | 7,920 | 7,989 | 0.99 |
| 19 | 145 | 1,753 | 6,224 | 8,282 | 7,707 | 1.07 |
| 20 | 43.9 | 1,324 | 4,858 | 7,838 | 7,558 | 1.04 |
| 21 | 41.4 | 959 | 3,263 | 6,831 | 7,032 | 0.97 |
| 22 | 36.8 | 632 | 1,783 | 5,043 | 5,391 | 0.94 |
| 23 | 34.2 | 383 | 1,172 | 3,744 | 3,639 | 1.03 |
| 24 | 29.7 | 200 | 855 | 2,377 | 2,349 | 1.01 |
| 25 | 33.0 | 95.1 | 534 | 1,594 | 1,600 | 1.00 |
| 26 | 28.5 | 42.7 | 308 | 1,120 | 1,083 | 1.03 |
| 27 | 25.2 | 19.0 | 156 | 746 | 707 | 1.05 |
| 28 | 25.4 | 8.2 | 73.8 | 458 | 407 | 1.13 |
| 29 | 22.9 | 3.5 | 33.3 | 248 | 219 | 1.13 |
| 30 | 21.7 | 1.5 | 14.7 | 124 | 115 | 1.08 |

### pt1 and pt1-pss, 10^9 numbers (M numbers/s)

| floor | pt1 (P, BPSW) | pt1-pss (proved) |
|---|---|---|
| 30 | 210 | 17.4 |
| 31 | 215 | 17.4 |
| 32 | 205 | 16.4 |
| 33 | 205 | 16.9 |
| 34 | 194 | 15.1 |
| 35 | 178 | refuses floors 35-37 |

### Peak RAM, largest over the floors (GB, PSS of the process tree)

| engine | 10^9 | 10^10 | 10^11 |
|---|---|---|---|
| v7 | 1.9 | 8.2 | 11.2 |
| v7.2 | 1.9 | 8.2 | 11.2 |
| pss | 0.8 |  |  |
| pt1 | 0.3 |  |  |
| pt1-pss | 0.6 |  |  |

### Spread above 2 % (two runs of one point)

| engine | floor | numbers | spread % | mean seconds without write |
|---|---|---|---|---|
| pss | 18 | 10^9 | 2.5 | 4.9 |
| pt1 | 33 | 10^9 | 2.3 | 4.9 |
| v7 | 18 | 10^9 | 6.8 | 0.5 |
| v7.2 | 18 | 10^9 | 4.5 | 0.5 |
| v7.2 | 23 | 10^9 | 2.5 | 2.8 |
| v7.2 | 24 | 10^9 | 2.3 | 5.3 |
| v7 | 18 | 10^10 | 5.3 | 1.4 |
| v7 | 19 | 10^10 | 4.3 | 1.6 |
| v7 | 21 | 10^10 | 2.8 | 3.1 |
| v7 | 22 | 10^10 | 7.1 | 5.6 |
| v7 | 24 | 10^10 | 4.4 | 11.7 |
| v7.2 | 19 | 10^10 | 4.0 | 1.6 |
| v7.2 | 21 | 10^10 | 4.6 | 3.1 |
| v7.2 | 24 | 10^10 | 6.4 | 12.1 |
| v7 | 18 | 10^11 | 3.4 | 12.6 |
| v7 | 19 | 10^11 | 6.9 | 12.1 |
| v7 | 20 | 10^11 | 13.2 | 12.8 |
| v7 | 21 | 10^11 | 9.6 | 14.6 |
| v7 | 22 | 10^11 | 13.0 | 19.8 |
| v7 | 23 | 10^11 | 4.1 | 26.7 |
| v7 | 24 | 10^11 | 3.3 | 42.1 |
| v7 | 25 | 10^11 | 5.1 | 62.7 |
| v7.2 | 18 | 10^11 | 8.9 | 12.5 |
| v7.2 | 19 | 10^11 | 13.7 | 13.0 |
| v7.2 | 20 | 10^11 | 15.8 | 13.2 |
| v7.2 | 22 | 10^11 | 8.7 | 18.5 |
| v7.2 | 23 | 10^11 | 7.9 | 27.5 |
| v7.2 | 27 | 10^11 | 2.0 | 141.3 |
| v7.2 | 28 | 10^11 | 11.0 | 245.7 |
| v7.2 | 29 | 10^11 | 11.3 | 456.7 |

Write phase at 10^11 numbers, scratch storage on /mnt/h: 15.4-23.5 s per run (not included above).
