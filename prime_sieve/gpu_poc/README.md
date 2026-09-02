# phase_mod_poc -- GPU phase-computation proof of concept

Branch: `v5-gpu-phase-poc` (off `main`, post cudasieve-v2 merge at `290178f`).
Status: **not committed yet** -- these are new, untracked files. Please review, build, and run
this on your own hardware first; I'll commit once you've had a look (per the usual rule: no
commit without your go-ahead in chat).

## Why this exists

This is the first concrete artifact from the 2026-08-27/28 conversation about using the RTX
5070 to accelerate PrimeAtlas's sieve. Recap of where that conversation left off:

- The CPU-side cost that's exploding at high floors is `distance mod p` for every sieving
  prime `p` (see `prime_sieve_engine_v4.c`'s own `phase_mod()`, lines ~64-76) -- specifically,
  the 128-bit-dividend case, which falls back to libgcc's software `__umodti3` whenever
  `distance_hi >= p_val`. That fallback gets hit for an increasing share of sieving primes as
  the floor grows, since `distance` grows with the floor but sieving primes (bounded by
  `L_final = isqrt(10**floor)`) grow much slower.
- Your proposal: do this computation on the GPU instead, using a "przesunieta skala"
  (shifted-scale) approach at native uint64 speed, avoiding conditional branching, with the
  CPU reconstructing the true phase for high floors.
- I confirmed this is a genuinely different lever than anything in the prior
  `primeatlas-offset-optimization-ceiling` investigation (that one concluded the offset step
  was at its *algorithmic* floor on CPU -- this is a *hardware throughput* lever, not an
  algorithm change, so it doesn't re-tread that ground).
- You then asked me to confirm agreement before creating a branch/plan. I did, and asked
  whether you had a profiled root-cause confirmation (active-sieving-prime-count explosion
  specifically, vs. something else) behind the floor-24-to-30 throughput collapse. **That
  question is still open** -- this PoC does not answer it, and isn't meant to. It only tests
  the arithmetic/GPU-mechanics side of your proposal in isolation.
- You then redirected: build something you can test on your own hardware, rather than keep
  talking about it. This is that.

## What I assumed "przesunieta skala" means

I don't have an exact formula from you for "przesunieta skala," so I made my own best-effort
reconstruction and built that -- **please tell me if this isn't what you meant**, before any
more time goes into this direction.

My reconstruction: a **branch-free 128-bit-mod-64-bit reduction using a double-precision
reciprocal**, a technique used in existing GPU primality/factorization tools for exactly this
reason (GPUs have no fast hardware 64-bit divide either -- both the CPU's software
`__umodti3` and a hypothetical naive GPU 128-bit divide would be slow, and worse, a
CPU-style `if (distance_hi < p_val) fast else slow` branch would cause *warp divergence* on
GPU, which is far more costly than the division itself since all 32 threads in a warp stall
together). Concretely:

```
distance mod p = ( (distance_hi mod p) * (2**64 mod p)  +  (distance_lo mod p) ) mod p
```

Every single-value `mod p` above is a native, branch-uniform 64/64 operation (same instruction
count on every GPU thread regardless of the actual values -- not divergent, even though it's
not a single opcode). The one piece that doesn't fit in 64 bits is the middle multiply, which
is reduced via `mulmod64()` in `phase_mod_poc.cu`: multiply by a double-precision estimate of
`1/m`, subtract, then up to two branch-lean corrections (`r -= (r>=m)?m:0`, which compiles to a
predicated select on GPU, not a real branch).

I did NOT implement full Barrett/Montgomery reduction (precomputed 128-bit reciprocals per
prime) -- that's the more "production-grade" version of the same idea and worth considering
next if this simpler version's numbers look promising, but it's a bigger lift and I wanted the
smallest real test first, per how we've approached everything else in this project.

## Validated range -- read this before raising any floor past ~28-30

I could not compile or run CUDA in my own environment (no GPU here), so before writing a single
line of `.cu`, I validated the *exact same double-reciprocal arithmetic* in plain Python
(IEEE754 binary64 -- identical semantics to CUDA's `double`) against 200,000+ random cases per
prime bit-width, from p ~ 2^24 up to p ~ 2^64:

| p magnitude | max corrections needed (of the 2 hard-coded) | mismatches |
|---|---|---|
| up to 2^50  | 1 | 0 |
| 2^55        | 7 | 0 |
| 2^60        | 217 | 0 |
| 2^64        | ~2,600-3,100 | 0 |

Below 2^50 the double estimate is always within 1 correction of exact -- safe with the 2
hard-coded corrections in `mulmod64()`. Above that it degrades fast and the kernel as written
would silently produce wrong answers if given a prime that large. `PHASE_MOD_MAX_SAFE_PRIME_BITS
= 50` in `phase_mod_poc.cu` enforces this (the host driver refuses to run any prime at or above
2^50 rather than trust it). Real PrimeAtlas sieving primes are bounded by
`L_final = isqrt(10**floor)`: ~3*10^12 (~42 bits) at floor 25, ~3*10^15 (~52 bits, just over the
safe line) at a hypothetical floor 30. So this specific kernel is honestly good up to roughly
floor 28-29 and would need the full Barrett version beyond that -- flagged, not hidden.

## What this test actually does

`phase_mod_poc.py`:
1. Generates a real sample of the smallest 20,000,000 primes via primesieve (see the big note
   in that file's own docstring for why it's a *sample*, not the full sieving-prime set --
   materializing all ~1*10^11 sieving primes a real floor-25 run would need is physically
   impossible, ~800+ GB just to store the values).
2. Builds a real `distance = 10**floor` value for the floor you pick.
3. Runs `phase_mod_poc.cu`'s GPU kernel on that sample, timing kernel-only and
   kernel+PCIe-transfer separately.
4. Checks **every single result** against Python's own arbitrary-precision `%` (exact,
   zero-tolerance ground truth).
5. Also times the same computation in plain Python, purely as a rough first-order reference
   point (see the next section for why this is NOT the comparison that actually matters).
6. If you pass `--count-true-total`, also reports the *true* pi(L_final) for that floor (a
   real sieve pass via `count_primes_in_range()`, not instant -- refused by default above
   floor 18 unless forced, same caution the production code already takes at this same call
   site) so you can see the sample throughput extrapolated against the real target scale.

`build_and_run.sh` compiles with `nvcc -O3` and runs floors 16, 25, and 28 automatically,
teeing everything to a timestamped log.

## What this does NOT prove

- **Not a fair GPU-vs-production-C comparison.** The "CPU (Python, ref)" number is Python's
  interpreter doing `%` in a loop -- much slower than the actual C engine's `phase_mod()`,
  which is already a single native DIV instruction whenever `distance_hi < p_val` (the common
  case at low-to-mid floors). If the GPU number beats Python by 50x, that does NOT mean it
  beats the real C engine by 50x -- it might not beat it at all at floors where the C fast
  path still applies. The floors where this matters are the ones where the C code's own slow
  path (`__umodti3`) is already firing for a large share of primes -- that's the real
  comparison to make next, once this PoC's basic mechanics check out.
- **Does not touch the write bottleneck.** Your other stated goal -- overlapping GPU sieving
  with CPU-side writing -- isn't tested here at all. This is purely the arithmetic core.
- **Does not confirm or refute the root-cause question I asked and you haven't answered yet**
  (whether active-sieving-prime-count growth, specifically, is what's driving the floor
  24-to-30 throughput collapse, vs. something else). This PoC is orthogonal to that -- it's
  useful regardless of the answer, since GPU-accelerating `distance mod p` helps either way if
  that operation is on the critical path at all.
- **Sample-based, not full-scale.** See "What this test actually does," point 1. The
  extrapolated total (sample throughput x true pi(L_final)) at the bottom of each floor's
  output is a naive linear extrapolation -- real GPU throughput at 100x the batch size could
  be better (more parallelism to hide latency) or worse (memory bandwidth limits, PCIe
  saturation) than what a 20M-prime sample shows. Worth treating as a rough first signal, not
  a promise.

## How to run it

```
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run.sh
```

(adjust the `/mnt/h/...` prefix if this repo is mounted somewhere else in your WSL2 session --
everything else in the script is path-independent).

Needs the same CUDA Toolkit already set up for `cudasieve` (`nvcc` on PATH).

## Resident-primes follow-up (2026-08-28, after the first real-hardware run)

The first run (see git history on this branch) passed correctness on all three floors, but
found kernel-only throughput (5-6.6 billion primes/s) was almost irrelevant: PCIe transfer
was ~97% of wall time, because that version re-uploads the full 20,000,000-prime sample on
every single call. Extrapolated to a real floor-25 run's true ~1.1*10^11 sieving primes, that
specific model would be *slower* than today's CPU sieve, not faster.

Your fix, and the reason it should work: sieving primes barely change between windows
(`L_final` grows far slower than the windows do -- see `prime_sieve_v4.py`'s own comment on
this), and the card has 12 GB of VRAM to keep them resident in. `phase_mod_resident_poc.cu` /
`.py` test exactly that: upload the sample ONCE, then compute phases for 1000 windows (floor
25, window width 10^7 -- 10^10 numbers total, the same scale as the real "10 billion in 3
minutes" floor-25 benchmark) against that same resident array in a single kernel launch.

Since materializing the full 1000-window x 20,000,000-prime phase matrix would be 160 GB
(doesn't fit in 12 GB, and wouldn't be realistic anyway -- a real engine consumes each phase
immediately to mark a bit, never keeps the raw value), most windows only produce a per-window
CHECKSUM (branch-free block-reduction + one atomicAdd per block, not per thread) -- 8 KB total
comes back for all 1000 windows. Three windows (first/middle/last) additionally get their full
phase array captured for an exact, zero-tolerance check against Python, and 20 more random
windows get checksum-only verification against Python. See `phase_mod_resident_poc.cu`'s own
header for the full reasoning.

Run:
```
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_resident.sh
```

What to look at in the output: the `amortized per-window (excluding one-time primes upload)`
line, and the line comparing GPU TOTAL against the real 113.352s sieve + 62.666s write from
the 2026-08-16 benchmark at this same floor/span. That comparison is the actual answer to
whether this direction is worth pursuing into a real v5 engine design, or not.

Both `.cu`/`.py` file input/output binary framing were round-trip tested by hand (small fake
data, byte-for-byte) before this was handed off, so a failure on your run more likely means a
real bug in the kernel/reduction logic than a format mismatch -- but flag which either way.

## Chunked/streaming follow-up (2026-08-28, "kubełkowanie")

The resident-primes test above proved the arithmetic is essentially free once transfer is
amortized, but also exposed a hard wall: floor 25's TRUE sieving-prime count is
pi(3,162,277,660,169) =~ 1.1*10^11, which at 8 bytes each is ~880 GB -- doesn't fit in the RTX
5070's 12 GB VRAM no matter what, even alone. Your framing (2026-08-28): "kubełkowanie jak w
primesieve, żeby przepchnąć wszystko przez ograniczone zasoby" -- bucket/stream the primes
through the fixed VRAM budget the way primesieve itself streams segments internally, rather
than needing the whole set resident at once.

`phase_mod_chunked_poc.py` tests exactly that, reusing the SAME already-verified
`phase_mod_resident_poc` binary unchanged: it generates and processes primes in disjoint
chunks (default: 10 x 20,000,000 = 200,000,000 total), one chunk resident at a time, summing
each chunk's per-window checksum into a running total (correct by plain uint64 wraparound
addition over disjoint prime subsets) and verifying a handful of windows per chunk against
Python ground truth for that chunk's own primes.

The chunking/streaming logic itself (which primes land in which chunk, no gaps/overlaps/
duplicates) was verified by hand against a direct sieve before handing this off -- exact
match on a 50-prime/5-chunk test case.

Known simplification, flagged not hidden: each chunk is a SEPARATE process invocation (own
CUDA context init/teardown), not a persistent in-process stream with async double-buffering --
see the script's own docstring for why, and what a real engine would do differently.

Run (builds `phase_mod_resident_poc` first if not already built):
```
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_chunked.sh
```

Once that default (200M total, still technically fits in 12GB as one block -- this run's job
is to prove the mechanism, not necessity) passes, scale up to actually cross the 12 GB ceiling
and confirm peak VRAM stays flat regardless of total:
```
bash .../build_and_run_chunked.sh --n-chunks 700    # ~14B primes, ~112GB total data,
                                                      # nowhere close to fitting as one block
```

## Marking-kernel follow-up (2026-08-28, real MARKING not just phase computation)

Every PoC above only tested phase computation (`distance mod p`) in isolation. The actual
dominant cost in a real sieve run is the MARKING step -- striding through every multiple of
each sieving prime and setting a bit -- not computing the initial phase. You confirmed
(2026-08-28, "idź w to") this is the right next step, after I flagged a GPU-specific design
problem marking has that phase computation doesn't:

**The load-balancing problem.** On CPU, one core handles one sieving prime's entire stride
loop sequentially -- for p=2 across a 10-billion-number range, that's 5 billion loop
iterations on a single core, fine because all 24 CPU workers are similarly unbalanced across
their own primes and equal-COST batching already accounts for it (see
`_build_equal_cost_batches()`). On GPU, one-thread-per-prime would put p=2's 5-billion-iteration
thread in the same warp as a large prime's few-iteration thread -- the whole warp stalls for as
long as its slowest thread, catastrophic. **Fix:** one BLOCK per prime, `MARK_THREADS=256`
threads within that block cooperatively striding through that same prime's multiples (thread
`t` starts at `start_pos + t*p`, steps by `256*p`) -- spreads even p=2's workload across 256
threads, costs almost nothing extra for large primes with few hits.

**Verification methodology -- the strongest one used in this PoC series so far.** Rather than
checking the GPU kernel against my own re-derivation of the algorithm, `marking_poc.py`
compiles (if needed) and calls the REAL, unmodified `prime_sieve_engine_v4.c` -- the exact file
production uses -- via ctypes, and compares the GPU kernel's output byte-for-byte against it.
Not "matches my own understanding of the algorithm" but "matches the actual shipped engine,
called unmodified, on the same input."

This caught something worth flagging honestly: an initial sandbox-only (no GPU) investigation
into the self-elimination guard (`if (distance + start_pos <= p) start_pos += p;` -- the logic
that stops a prime from marking itself as composite -- see `prime_sieve_engine_v4.c` lines
~100) seemed to find a real bug, using a small hand-written Python check against the compiled
engine. A follow-up re-check with 211 randomized + hand-picked edge cases (including the exact
case that first looked broken: `distance=0, p=317`) found **zero mismatches** -- the original
finding was an off-by-one in that throwaway test script's own sieving-prime boundary
(`L_final+1` vs `L_final`), not a bug in the guard logic itself. The guard as written in
`marking_poc.cu` already matches the real engine exactly. Flagging this here so the history is
honest: a real bug was suspected, investigated hard, and found not to exist -- rather than
quietly dropping the thread.

`marking_poc.py` has two modes:
1. **EXACT** -- 8 cases (self-elimination edge cases, `distance` at/near a multiple of a
   sieving prime, a realistic floor-9-shaped batch, the `distance_hi != 0` branch) checked
   byte-for-byte against the real engine.
2. **THROUGHPUT** -- one realistic-shaped batch (20,000,000 sample primes marking a 10^8-wide
   combined range at floor 25) timed on real hardware. This is NOT a full floor-25
   extrapolation (the composite CPU-generation + GPU-marking pipeline number is a separate,
   later integration step, once CPU-side parallel chunk generation -- the other axis you asked
   about -- is also in place) -- it answers a narrower question: how fast is one
   block-per-prime marking kernel at a realistic prime-count/combined-size shape.

Run:
```
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_marking.sh
```

The harness logic itself (file I/O, byte-comparison, CLI flow) was tested end-to-end in the
sandbox using a pure-Python stand-in implementing the identical algorithm in place of the real
CUDA binary (no GPU available here) -- including a negative-control run with a deliberately
broken guard, confirming the harness actually detects mismatches rather than always reporting
PASS. What was NOT tested outside your hardware: the real CUDA kernel itself (grid/block
launch, the byte-level `atomicOr`, `mulmod64` on real GPU floating-point hardware).

## Marking-kernel real-hardware result (2026-08-28) + the cost-decomposition follow-up

You ran `build_and_run_marking.sh` on the RTX 5070. **EXACT mode: 8/8 PASS**, including every
self-elimination-guard edge case -- this is the first time the real compiled CUDA kernel
itself (not a Python stand-in) was checked byte-for-byte against the real production engine,
and it matched exactly. The kernel design is confirmed correct on real hardware.

THROUGHPUT mode reported "5,456,450 billion work-units/s" -- **don't trust that number, it's a
bug in `marking_poc.py`'s own metric formula**, not a real measurement. It computes
`n_primes * combined_size / kernel_time`, which assumes every one of the 20,000,000 sample
primes' 256 threads walks the full 100,000,000-position range -- but real per-prime work is
only about `combined_size / p` (huge for p=2, often zero for the larger primes in that sample,
since many of the 20-millionth-smallest primes are themselves bigger than the 10^8 window).
The formula overstates real throughput by orders of magnitude. Flagging this plainly rather
than let a wrong number stand.

What IS a real, informative data point from that run: the two THROUGHPUT-mode-shaped
measurements collected so far --
```
3,417 primes      / combined_size=10,000,000  -> kernel 2.97ms   (from the floor-9-like EXACT case)
20,000,000 primes / combined_size=100,000,000 -> kernel 366.5ms  (from THROUGHPUT mode)
```
n_primes grew ~5854x, kernel time grew only ~123x -- neither linear in block count nor in
window size alone, because both variables changed at once. That's not enough to tell whether
the cost is dominated by (a) the GPU's own per-block launch/scheduling overhead (one block per
prime, so more primes = more blocks), (b) a real inefficiency spotted while re-reading
`marking_kernel`: it computes `phase_mod_gpu()` and the self-elimination guard REDUNDANTLY on
all 256 threads per block (nothing restricts that to thread 0), which is pure waste whenever a
block's prime has few or zero real hits, or (c) genuine stride-marking work scaling with
`combined_size`.

`marking_overhead_poc.cu`/`.py` decomposes this by running three kernel variants back-to-back
on the SAME uploaded primes per case: `null_kernel` (identical grid/block shape, does nothing
but one atomicAdd per block -- isolates pure launch overhead), `phase_only_kernel` (copies
`marking_kernel`'s redundant phase+guard computation exactly, but skips the marking loop --
isolates launch overhead + the redundant-computation cost), and the real `marking_kernel`
(isolates the remainder: real stride-marking work). Two clean sweeps, changing ONE variable at
a time (unlike the two data points above):
- **SWEEP A** -- fixed `combined_size=10^8`, `n_primes` sweeping 3,417 / 20,000 / 200,000 /
  2,000,000 / 20,000,000. Isolates whether cost scales with block count.
- **SWEEP B** -- fixed `n_primes=20,000,000`, `combined_size` sweeping 10^6 / 10^7 / 10^8.
  Isolates whether cost scales with real per-block marking work.

Each kernel variant is timed with 5 repeats per case, reporting the minimum (least-perturbed
run) -- standard practice when subtracting small differences between runs.

Run:
```
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_overhead.sh
```

Harness I/O (multi-case input/output file format, sweep construction, table printing) was
tested end-to-end in the sandbox with a Python stand-in producing fake-but-structured timings,
confirming the round-trip and table output are correct. What was NOT tested outside your
hardware: the real timing behavior of all three kernel variants (that's the entire point of
this test).

## Cost-decomposition result (2026-08-28) + the shared-memory-broadcast fix

You ran `build_and_run_overhead.sh`. The result was unambiguous: at `n_primes=20,000,000` /
`combined_size=10^8`, `null`=11.9ms, `redundant_phase`=350.6ms, `real_marking`=1.8ms -- **96% of
total kernel time was the redundant per-thread phase computation**, not launch overhead and not
real marking work. SWEEP B confirmed `real_marking` scales with `combined_size` as expected
(small, as designed, in this parameter range) while `null`/`phase_only` stayed flat -- the
decomposition model holds together cleanly (the three components sum to `full_marking` almost
exactly in every row).

**Correction to my own first-pass reasoning:** I initially described this as "256x redundant"
in the code comments (once per thread instead of once per block). That's wrong for how GPUs
actually execute -- threads run in 32-wide warps, so `MARK_THREADS=256` is 8 warps, and a
branch-free computation like `phase_mod_gpu()` costs the same whether 1 or 32 threads in a warp
"need" the result (SIMT lockstep). The real reducible cost is ~8x (256/32), not ~256x. Flagging
my own overcorrection here rather than let the more dramatic, wrong number stand.

**The fix**, applied to `marking_kernel` in both `marking_poc.cu` and `marking_overhead_poc.cu`
(kept in sync): only `threadIdx.x == 0` computes `phase_mod_gpu()` + the self-elimination
guard, stores the result in `__shared__ unsigned long long s_start_pos`, then a single
`__syncthreads()` (reached uniformly by all 256 threads, not nested inside the `threadIdx.x==0`
branch -- required for `__syncthreads()` correctness) makes it visible before every thread
reads it and proceeds to the stride loop. This is a pure performance restructuring -- the value
computed is identical, so output should be bit-for-bit unchanged from before. In
`marking_overhead_poc.cu`, variant 2 (`phase_only_kernel`) was DELIBERATELY left un-fixed as a
stable "old design" baseline, so re-running the same two sweeps directly shows the real,
measured improvement rather than a theoretical estimate.

I also fixed a second issue while in this area: `marking_poc.py`'s THROUGHPUT mode was
reporting a "work-units/s" number computed as `n_primes * combined_size / kernel_time` --
wrong, since it assumes every prime's block walks the full `combined_size` range, when real
work per prime is closer to `combined_size / p`. Replaced with two honest numbers computed
directly from the actual sample: estimated real marking work (`sum(combined_size // p for p in
primes)`) and its rate, plus a separately-labeled raw block-dispatch rate.

**Re-verified on your hardware (2026-08-28):** `marking_poc.py --mode exact` still PASSED 8/8 --
the restructuring is confirmed bit-for-bit identical to the old output. `marking_overhead_poc.py`
re-run measured the real achieved improvement directly: `full(ms)` at `n_primes=20,000,000`
dropped from 364.3ms to **93.8ms (~3.9x)**, consistent (~3.9-4.0x) across all three
`combined_size` values in SWEEP B, confirming the fix targets per-block cost specifically, not
the marking loop. This came in below the ~5.5-6x theoretical estimate above -- real GPU
scheduling (latency hiding, warp occupancy) is more complex than the simple 8-warp model
predicts, worth noting honestly rather than claiming the estimate was exact. Both fixed kernels
were committed (`3809649`) after this real-hardware confirmation.

## Chunked marking (2026-08-28): combining VRAM-bounded streaming with real marking

Every marking test so far (`marking_poc`, `marking_overhead_poc`) uploads its full prime sample
to GPU memory at once -- fine for the scales tested (up to 20,000,000 primes, ~160 MB), but a
real floor-25 batch's full sieving-prime range ([2, L_final), L_final ~ 3*10^12) has ~1.1*10^11
primes -- ~880 GB, nowhere close to fitting in 12 GB VRAM. `phase_mod_chunked_poc.py` solved
this for phase-checksum verification earlier in the series, but as a SEPARATE PROCESS per chunk
(fresh CUDA context each time) -- fine when the only output is a scalar checksum to sum, but
marking's output is a bit-packed buffer that every chunk's primes must OR into the SAME
positions, so chunks are not independent the way checksums were.

`marking_chunked_poc.cu` combines both pieces properly: ONE persistent CUDA context, ONE
resident output bit buffer for the entire run, looping over chunks internally -- only the
(small, fixed-size) primes buffer is re-uploaded per chunk, `chunk_size` primes at a time,
regardless of how many total chunks run. This file also links libprimesieve DIRECTLY (same
library, same `primesieve_iterator`/`primesieve_jump_to`/`primesieve_next_prime` calls as
`prime_sieve_engine_v4.c`'s own `generate_and_sieve_segment_bits()` and `iterator_chunk_gen.c`)
-- prime generation happens on the host side of this same binary, not shuttled through Python
and a separate `.so` file, avoiding a real (and avoidable) round-trip cost at hundreds-of-
millions-of-primes scale.

**Correctness claim being tested:** splitting a sieving-prime range into N independent kernel
launches, each marking its own chunk's primes into a shared, persistent buffer, produces
IDENTICAL output to processing the whole range in one shot. This must be true mathematically
(marking is a pure union of independent per-prime bit sets, and CUDA's default stream
serializes sequential kernel launches, so there's no cross-chunk race) -- verified here by a
Python simulation of the exact same host-loop logic (including the tricky exhausted-flag
chunk-boundary handling) against the real, unmodified `prime_sieve_engine_v4.so`, across 7
cases: the usual guard-exercising edge cases, plus three specifically targeting chunk-boundary
arithmetic (`chunk_size=1`, worst case with 95 chunks for 95 primes; `chunk_size` exactly
dividing the prime count; `chunk_size` larger than the total, degenerate single-chunk case).
All 7 passed with zero mismatches. The actual CUDA kernel launch/shared-memory/sync mechanics
are unchanged from the already-hardware-verified `marking_poc.cu` -- only the host-side
chunking loop around it is new, and that's what this Python-level check specifically targets.

`marking_chunked_poc.py` has the same EXACT/STRESS split as before:
1. **EXACT** -- 5 small cases, each forced into several chunks via a deliberately small
   `chunk_size` (as low as 50), checked byte-for-byte against a single unchunked real-engine
   call.
2. **STRESS** -- one large-scale run: `l_final=20,000,000,000` (expect roughly 8-9*10^8 real
   sieving primes -- pi(2*10^10) is in that neighborhood, not asserted exactly since it depends
   on the actual generation), `chunk_size=20,000,000`, `combined_size=10^8` at floor 25. Watch
   the binary's own "allocated once, resident for the whole run" stderr line -- it prints GPU
   free/total memory right after allocating the (fixed-size) buffers, ONCE, not per chunk,
   directly demonstrating that VRAM usage does not grow with total primes processed. This is
   the first test in the whole PoC series that exercises the ORIGINAL motivating problem
   directly at real scale, not a small sample.
3. **FULL** (added 2026-08-28, `--mode full`, not part of default "both") -- the actual real
   floor-25 scale, not a smaller stand-in range: `distance=10**25`, `combined_size=10**10`
   (matching the real production benchmark span: 1000 windows x 10^7),
   `l_final = isqrt(distance+combined_size)+1 = 3,162,277,660,169`, `chunk_size=20,000,000`.
   Expect ~113.8 billion real sieving primes across ~5,691 chunks. This is a genuinely large
   run -- pre-run estimate is on the order of ~15-20 minutes total (roughly ~9 min CPU-side
   `primesieve` generation + ~9 min cumulative GPU kernel time, each independently estimated;
   see `run_full_scale_mode()`'s own docstring in `marking_chunked_poc.py` for why a naive
   linear extrapolation from STRESS mode's own numbers would be unreliable -- primesieve's
   generation cost scales with the swept numeric range, not linearly with prime count, and
   floor-25's range is ~158x larger than STRESS mode's despite "only" ~125-129x more primes).
   This is explicitly uncertain, not a promise -- report the real numbers once it finishes.
   The density computation was switched from a naive per-byte Python loop to
   `int.from_bytes(bits, "little").bit_count()` specifically for this mode, since the naive
   loop would add real extra minutes at this mode's ~1.25 GB output size (STRESS mode's ~12.5
   MB output keeps the naive loop fine there, so it was left as-is).

Harness I/O (multi-chunk-aware file format, EXACT case construction, STRESS mode printing) was
tested end-to-end in the sandbox with a Python stand-in implementing the identical
chunking+marking algorithm in place of the real CUDA binary, including a negative-control run
with a deliberately broken guard (correctly caught on exactly the two guard-exercising cases,
left the other three passing -- confirming the harness discriminates real bugs rather than
rubber-stamping).

Run:
```
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_chunked_marking.sh
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_chunked_marking.sh --mode exact     # skip the large stress run
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_chunked_marking.sh --mode full      # REAL floor-25 scale, ~15-20 min (uncertain)
```

## Parallel chunked marking (2026-08-28): real parallel CPU generation + pipelined GPU

Direct, real-hardware follow-up to the FULL-mode result above. That run measured
TOTAL=1316.729s vs production's 176.018s (~7.5x slower) at combined_size=10^10, with
generate=670.486s (single CPU thread) as the single biggest cost -- bigger even than
kernel=576.403s -- and zero overlap between generate/upload/kernel (the previous file's host
loop is strictly serial: generate a chunk, then upload it, then run the kernel, then generate
the next chunk). Rather than leave "would probably be faster if we parallelized generation and
pipelined it" as a guess, `marking_chunked_parallel_poc.cu`/`.py` actually does both and reports
the real, measured result:

1. **Parallel CPU generation** -- splits `[2, l_final)` into `num_gen_threads` contiguous,
   disjoint, roughly-equal-WIDTH sub-ranges (equal numeric width, not equal prime count --
   primesieve's segmented-sieve cost for a sub-range tracks the range's width more than how many
   primes it contains, so this is a reasonable, honestly-imperfect approximation of balanced CPU
   cost per thread). Each thread owns its own `primesieve_iterator` (independent, thread-safe per
   instance) and pushes `chunk_size`-sized batches onto a shared thread-safe queue. Correctness
   does not depend on cross-thread ordering: marking is a pure per-prime, order-independent union
   into the shared output buffer, so batches can arrive from N threads in any interleaving.
2. **Double-buffered GPU pipeline** -- the consumer (main thread, owns the persistent CUDA
   context and the persistent `d_bits` buffer) pops batches and drives two device primes-buffers
   + two CUDA streams in a ping-pong pattern, so chunk i+1's async H2D upload (from pinned host
   memory) can be issued while chunk i's kernel is still running, instead of strictly serializing
   upload -> kernel -> upload -> kernel.

This deliberately does NOT attempt full N-way concurrent kernel execution across many streams,
nor exact density-aware load balancing of generator threads -- both remain on the table. It does
remove the two concrete, measured bottlenecks from the serial run and report the real resulting
number.

**Real-hardware fix (2026-08-28, same day): unbounded queue OOM'd WSL.** EXACT mode passed
6/6 on the first real-hardware run. FULL mode (`--gen-threads 24`) killed WSL on the first
attempt and (per Artur) barely survived on a retry -- root cause: the producer/consumer queue
was unbounded. With 24 threads sieving in parallel, generation finishes its ~113.8 billion
primes in well under a minute, while the single GPU consumer only drains about one 20-million-
prime chunk every ~100ms (~10 chunks/sec, ~5700 chunks total, ~9.5 minutes to fully drain). With
no backpressure, producers would queue up nearly the entire prime range before the consumer
could catch up -- hundreds of GB of host RAM at ~160 MB/batch, trivially exceeding WSL's memory
budget. Fixed by capping the queue at `MAX_QUEUE_BATCHES=8` (~1.28 GB of host RAM regardless of
thread count); producers now block once the queue is full instead of piling up, which also
matches the actually-intended steady state (GPU kernel time, not generation, is the real long
pole once the queue is primed).

**Correctness verification, two layers:**
1. The numeric-range partitioning math (the one genuinely new correctness risk in this file --
   the marking kernel itself, atomics, and guard logic are byte-identical to the
   already-hardware-verified version) was validated in the sandbox with a pure-Python simulation
   of the exact same integer boundary arithmetic used in the `.cu` file, across 508 randomized +
   edge cases (including `num_gen_threads` far exceeding the range width, to exercise the
   internal clamp) -- zero mismatches against a plain sequential sieve.
2. `marking_chunked_parallel_poc.py`'s EXACT mode adds 6 cases (vs. the previous file's 5),
   specifically varying `gen_threads` from 1 to 16 (including a deliberately-oversized 16 on a
   tiny ~200-number range to exercise the clamp on real hardware, not just in the Python
   simulation), each checked byte-for-byte against a single unchunked, single-threaded call to
   the real, unmodified `prime_sieve_engine_v4.c`.

Run:
```
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_chunked_marking_parallel.sh
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_chunked_marking_parallel.sh --mode exact
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_chunked_marking_parallel.sh --mode stress
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_chunked_marking_parallel.sh --mode full --gen-threads 24
```
`--gen-threads` defaults to `os.cpu_count()` on the machine running it if not given.

**Real-hardware FULL-mode result (2026-08-28), post-OOM-fix:** EXACT 6/6 PASS. FULL mode
(`--gen-threads 24`) completed cleanly, bounded RAM confirmed in Task Manager (GPU 99% busy,
CPU ~13% -- exactly the predicted steady state, see below). Result:
`total_primes=113,983,535,775` across 5711 chunks, `generate_wall=579.141s`,
`gpu_wall=579.019s`, `download=0.589s`, **TOTAL=580.386s** -- a real **2.27x** speedup over the
prior serial run's 1316.729s, but still **~3.3x slower** than production's 176.018s.

The near-EXACT equality of `generate_wall` (579.141s) and `gpu_wall` (579.019s) is the key
signal: parallel generation is no longer on the critical path at all -- it finishes fast, then
the 24 CPU threads spend nearly all their time BLOCKED on the bounded queue waiting for the GPU
to drain (hence CPU ~13% in Task Manager, "underutilized" is a direct, correct read of that
number). The pipeline is now purely GPU-kernel-bound, and `gpu_wall` (579s) matches the earlier
serial run's isolated `kernel=576.403s` almost exactly -- confirming the GPU marking kernel's
raw cost is fixed and was never really about pipelining or generation.

**Working hypothesis for why the kernel itself is the bottleneck (not yet tested):** production's
segmented CPU sieve marks each window (10^7 bits, ~1.25 MB) fully in CPU cache before moving on,
so for each sieving prime the multiples-marking loop is cache-resident. This GPU design instead
marks directly into the FULL 1.25 GB `d_bits` buffer for the whole [0, 10^10) range at once --
every atomic write is scattered across a buffer far larger than GPU L2 cache, likely making this
memory-bandwidth-bound rather than compute-bound, which would explain why a GPU with vastly more
raw throughput than 24 CPU cores still loses here. A GPU kernel restructured to process
`combined_size` in cache-sized windows (primes as the inner loop, windows as the outer loop --
the same shape as production's own algorithm) would be the natural next experiment if this is
worth pursuing further, but that is a materially bigger redesign than anything tried so far and
has not been started.

## Two-tier dense/sparse kernel (2026-08-28): mirroring production's own O(1)-vs-loop split

Direct follow-up to the parallel chunked marking result above, which converged to
`generate_wall`=579.141s, `gpu_wall`=579.019s -- confirming the pipeline was purely
GPU-kernel-bound, with no more pipelining or generation-parallelism gains left to find. Artur's
explicit direction at that point: keep verifying rather than settle for a hypothesis, and he
raised a fair question about whether this was still testing the right thing (GPU offloading a
real CPU-heavy production task). Both were resolved by reading `prime_sieve_engine_v4.c`
directly rather than assuming: production's real algorithm is exactly the same shape this whole
PoC series implements (iterate each sieving prime once, mark into one shared buffer spanning the
whole batch -- confirmed via `generate_and_sieve_segment_bits_atomic`'s prime-range-per-worker
split, not a per-window split as originally assumed) -- so yes, still on-topic. But that same
function (`generate_and_sieve_segment_bits`, around line 104) revealed something this GPU code
was missing:

```c
if (p_val >= window_m) {
    out_dense_bits[start_pos >> 3] |= (1u << (start_pos & 7));      // O(1): one write
} else {
    uint64_t pos = start_pos;
    while (pos < window_m) {                                        // loop: many writes
        out_dense_bits[pos >> 3] |= (1u << (pos & 7));
        pos += p_val;
    }
}
```

Production already splits primes into two cost tiers. At real floor-25 scale
(`combined_size`=10^10, `l_final`~=3.16*10^12), primes >= `combined_size` are ~99.6% of the
~113.8 billion total sieving primes -- and every one of them does a single O(1) write on
production's CPU path. This GPU codebase's `marking_kernel` had been launching a full
256-thread cooperative block per prime regardless of tier, paying a full block-launch +
shared-memory-broadcast + `__syncthreads()` cost for what is, for that 99.6% majority,
mathematically a single conditional write. The measured numbers support this as the real
bottleneck: `marking_overhead_poc`'s own post-fix measurement was ~4.69 ns/block
(93.8ms / 20,000,000 primes); 113.8*10^9 blocks * 4.69ns ~= 534s, matching the measured
kernel/`gpu_wall` time (576-579s) almost exactly -- the kernel's cost tracks BLOCK COUNT, not
actual marking work.

`marking_two_tier_poc.cu` mirrors production's own branch exactly: `marking_kernel` (dense,
unchanged, one block/prime, cooperative striding) for primes < `combined_size`; a NEW
`sparse_kernel` (one thread per prime, flat 1D grid, no shared memory, no `__syncthreads()`) for
primes >= `combined_size`, amortizing block-launch overhead across `SPARSE_THREADS=256` primes
per block instead of paying a full block per prime. The host runs two sequential phases over the
same persistent `d_bits` buffer and the same bounded producer/consumer pipeline (parallel CPU
generation + double-buffered GPU streams, unchanged from `marking_chunked_parallel_poc.cu`):
phase 1 covers `[2, combined_size)` with the dense kernel, phase 2 covers
`[combined_size, l_final)` with the sparse kernel. The split point is mathematically exact: a
prime `p` has at most one multiple in any window of width `combined_size` iff
`p >= combined_size`, so this changes nothing about correctness, only which kernel processes
which primes.

**Correctness verification, two layers, both before spending real GPU time:**
1. A pure-Python simulation of the exact tier-split math (dense loop vs. sparse single-check),
   compared against a brute-force ground truth across 400 randomized + boundary-focused cases
   (including `combined_size` set to an actual prime value, to specifically exercise the
   `p == combined_size` edge -- must land in the sparse tier and still produce exactly one hit)
   -- zero mismatches.
2. `marking_two_tier_poc.py`'s EXACT mode adds 7 cases specifically covering dense-only
   (`combined_size > l_final`, sparse phase empty), sparse-heavy, mixed, the `distance_hi != 0`
   branch, and the same prime-boundary edge, each checked byte-for-byte against a single
   unchunked, single-threaded call to the real, unmodified `prime_sieve_engine_v4.c`. Not yet
   run on real hardware.

Run:
```
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_two_tier_marking.sh --mode exact
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_two_tier_marking.sh --mode full --gen-threads 24
```

**Real-hardware FULL-mode result (2026-08-28):** EXACT 7/7 PASS. FULL mode:
`total_primes=113,983,535,775` (455,052,511 dense + 113,528,483,264 sparse), **TOTAL=169.179s**
-- a **3.43x** speedup over the no-split parallel result (580.386s) from the tier split alone.
Honest comparison: this TOTAL is GPU marking only, no disk write yet, vs. production's
113.352s sieve-only step (also no write) -- GPU is now only **~1.49x slower** than the CPU sieve
step alone (down from ~5.12x before the tier split). Not yet a win, but the gap narrowed
dramatically from one change.

## Sparse-kernel cost decomposition (2026-08-28): finding the remaining ~1.49x

Artur's direct follow-up question: if the GPU code doesn't yet do everything the CPU code does,
we can't claim to be at "full speed" yet -- and if GPU can beat CPU at smaller scales, something
specific must be adding disproportionate overhead at floor-25 scale. Reading
`prime_sieve_engine_v4.c`'s `phase_mod()` (and its `udiv128_rem` helper) directly, rather than
guessing, found a concrete, real difference: the CPU gets the ENTIRE 128-bit-by-64-bit modulo in
a SINGLE `divq` x86 instruction whenever `distance_hi < p_val` (always true here -- distance_hi
is tiny, e.g. 542101 at floor 25, while every sieving prime is far larger). GPU has no equivalent
single-instruction 128/64 divide, so `phase_mod_gpu` synthesizes the same result from several
64-bit operations -- but it was doing so WASTEFULLY: it unconditionally computed
`distance_hi % p` even in the common case where the answer is trivially `distance_hi` itself
(exactly the condition the CPU's fast path already checks for).

**Fix:** `phase_mod_gpu` now skips that division when `distance_hi < p` (verified
mathematically identical to the original formula and to true 128-bit modulo across 200,000
randomized cases including edge values around `p-1`/`p`/`p+1`) -- applied to both `marking_
kernel` and the new `sparse_kernel`.

**`sparse_overhead_poc.cu`/`.py`** -- a new, focused diagnostic (same three/four-variant
methodology as `marking_overhead_poc.cu`) built to directly show WHERE the sparse tier's
remaining ~1.4 ns/prime goes, rather than guess: `null_kernel` (dispatch only) vs.
`phase_only_old_kernel` (pre-fix formula) vs. `phase_only_new_kernel` (post-fix formula) vs.
`sparse_kernel_full` (phase + the real atomic write), all run on the SAME sample of real
sparse-tier primes (sampled live via libprimesieve from the real floor-25 sparse range
`[combined_size, l_final)`), `N_REPEATS=5`, minimum reported. The pairwise differences isolate:
dispatch overhead, the fast-path fix's actual per-prime savings, and the atomic write's own
cost -- not yet run on real hardware.

Run:
```
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_sparse_overhead.sh
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_two_tier_marking.sh --mode exact
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_two_tier_marking.sh --mode full --gen-threads 24
```

## Real-hardware result: sparse_overhead_poc decomposition (2026-08-28)

Both re-runs are in. `marking_two_tier_poc --mode full` with the fast-path fix applied: TOTAL=
169.623s, essentially unchanged from the pre-fix 169.179s -- Artur's own read was "nie widze
roznicy" (no visible difference), and the decomposition below explains exactly why: the fix only
ever touched the phase-computation slice, which turns out to be small next to the write cost.

`sparse_overhead_poc` (n=50,000,000 real sparse-tier primes) gave a precise breakdown of
`sparse_kernel`'s real cost:

| component                | share of full cost |
|---------------------------|--------------------|
| dispatch/launch overhead   | 2.6%               |
| phase computation (post-fix) | 12.0%            |
| atomic write                | **85.3%**          |

The atomic write dominates. Back-of-envelope effective throughput from the measured write-cost
slice: roughly 2.43 billion atomic writes/s, i.e. ~19.4 GB/s of effective bandwidth if each write
touches one 4-byte word -- a small fraction of the RTX 5070's likely peak memory bandwidth (on
the order of 600+ GB/s for this class of card). That gap is consistent with what you'd expect
from scattered, effectively-random-address atomic writes into a 1.25 GB buffer that's far larger
than any GPU's L2 cache: most writes miss cache and pay a full DRAM round trip, and neighboring
threads in the same warp are very unlikely to land in the same cache line, so there's little
coalescing to help.

This is the precise, now-understood root cause of the remaining ~1.49x gap between the two-tier
kernel (169s) and production's sieve-only step (113.352s): not dispatch, not the phase-computation
math, but memory-access pattern on the write itself.

## sparse_bucketed_poc.cu/.py -- does grouping writes by target region help? (2026-08-28)

Direct follow-up to the decomposition above. Idea: bucket-sort each chunk's primes by which
*shard* (a configurable contiguous sub-range) of the `d_bits` buffer their target position falls
into, before doing the actual atomic writes -- so that writes landing in the same shard happen
close together in the kernel's execution order, giving the GPU's L2 cache an actual chance to
keep that shard hot across many writes, instead of constantly evicting/reloading essentially-
random words from DRAM. This is the GPU-native analogue of what the CPU's segmented sieve gets
"for free" from cache locality.

Pipeline per chunk (three kernels + one small host-side prefix sum):

1. `compute_positions_kernel` -- phase_mod each prime once, store `start_pos` (or a sentinel if
   out of range), and atomically count how many positions land in each shard (`d_bucket_counts`
   -- typically only hundreds to low thousands of shards, trivially small).
2. Host: download the small `d_bucket_counts` array, compute an exclusive prefix sum
   (`d_bucket_offsets`), upload as the initial per-shard write cursor.
3. `scatter_kernel` -- re-reads each prime's precomputed `start_pos` (no recomputation), and for
   valid ones, atomically claims a slot within its shard's segment of `d_sorted_positions`.
4. `write_sorted_kernel` -- flat pass over `d_sorted_positions` (now grouped by shard), doing the
   real `atomic_or_bit()` into `d_bits`.

Since the real L2 cache size on your RTX 5070 isn't something I want to assume, the harness
sweeps four shard sizes (128 KB / 1 MB / 8 MB / 64 MB of the bit-buffer per shard) and reports
which one (if any) actually beats the naive scattered write, on the same sample of real
sparse-tier primes used throughout this series.

**Correctness, verified before hardware**: a 500-case randomized Python simulation confirmed the
bucket-sorted output contains exactly the same set of write positions as the naive approach, and
that consecutive entries in the sorted output are always non-decreasing in shard id (the grouping
property the whole approach depends on) -- both 500/500 pass. Not yet run on real hardware.

This is explicitly the "bigger, uncertain-payoff" step flagged before starting it -- unlike every
prior fix in this series (which were small, targeted, and had an obvious mechanism), this one
adds real pipeline complexity (three kernels, a host round-trip) on a bet that memory locality is
fixable at all for this access pattern. If none of the four shard sizes beat the naive write, that
itself is a useful, precise answer: it would mean the atomic-write cost is dominated by something
bucketing doesn't address (e.g., cross-warp contention on the same cache line rather than cold
DRAM misses), narrowing where a real fix would have to look next.

Run:
```
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_sparse_bucketed.sh
```

## Real-hardware result: bucketing works, and the trend was still climbing (2026-08-28)

First real run (n=50,000,000, 4 shard sizes from 128 KB to 67 MB): bucketing won decisively at
every size except the largest, and the win got BIGGER as the shard got SMALLER -- monotonic
across all three components (compute, scatter, write), not just the write step the whole
experiment targeted:

| shard size | n_buckets | compute | scatter | write | TOTAL | vs. naive (24.103ms) |
|---|---|---|---|---|---|---|
| 128 KB | 9,537 | 3.982ms | 2.066ms | 4.209ms | 10.257ms | **2.35x faster** |
| 1 MB | 1,193 | 3.988ms | 4.781ms | 4.273ms | 13.042ms | 1.85x faster |
| 8 MB | 150 | 6.892ms | 7.430ms | 5.943ms | 20.266ms | 1.19x faster |
| 67 MB | 19 | 6.490ms | 7.068ms | 17.568ms | 31.126ms | 0.77x (SLOWER) |

Best (128 KB shards): 10.257ms vs. naive's 24.103ms.

Two things worth being precise about before pushing further:

1. **Why compute and scatter also got cheaper, not just write**: fewer buckets means more primes
   collide on the same `atomicAdd` counter/cursor (in `compute_positions_kernel`'s bucket-count
   and `scatter_kernel`'s per-bucket write cursor) -- so smaller shards (= more buckets) reduce
   atomic contention on those small housekeeping arrays too, independent of the write-locality
   effect on `d_bits` itself. Both effects point the same direction, which is why the win compounds
   as shards shrink.
2. **A gap in the first measurement, fixed before pushing further**: the host round trip between
   `compute_positions_kernel` and `scatter_kernel` (download `d_bucket_counts`, prefix-sum on the
   host, upload `d_bucket_offsets`) was NOT wrapped in a timer in the first version of this file --
   it was assumed negligible rather than measured. That's exactly backwards for a sweep that's
   about to test far smaller shards (= far more buckets = a bigger array to round-trip). **Fixed**:
   `sparse_bucketed_poc.cu` now times this round trip directly (`t_roundtrip`, via `std::chrono`,
   included in `TOTAL`) so the honest cost is visible instead of assumed away.

Since every size tried so far kept improving as it got smaller, the sweep now pushes further down
(2 KB / 8 KB / 32 KB shards added, keeping the two best sizes from the first run as anchors) to
find where it actually turns over -- rather than declaring 128 KB the answer just because it was
the smallest size tried.

Run:
```
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_sparse_bucketed.sh
```

## Real-hardware result: the U-shaped optimum, confirmed (2026-08-28)

Second sweep (2 KB to 1 MB shards, roundtrip now measured) reversed at the bottom, giving a clean
U-shape with a real optimum instead of an open-ended "smaller is better" trend:

| shard size | n_buckets | compute | roundtrip | scatter | write | TOTAL | vs. naive (24.1ms) |
|---|---|---|---|---|---|---|---|
| 2 KB | 610,352 | 3.984ms | 0.644ms | 20.358ms | 3.742ms | 28.728ms | 0.84x (SLOWER) |
| 8 KB | 152,588 | 3.981ms | 0.192ms | 8.158ms | 3.967ms | 16.297ms | 1.48x |
| 32 KB | 38,147 | 3.994ms | 0.094ms | 3.597ms | 4.153ms | 11.838ms | 2.04x |
| **128 KB** | **9,537** | 3.993ms | 0.062ms | 2.064ms | 4.197ms | **10.316ms** | **2.34x (best)** |
| 1 MB | 1,193 | 3.988ms | 0.051ms | 4.784ms | 4.287ms | 13.110ms | 1.84x |

Combined with the first sweep's larger sizes (1 MB through 64 MB, all worse than 128 KB in the
same direction as this table), **128 KB shards (1,048,576 bits, 9,537 buckets at
combined_size=10^10) is now a confirmed real-hardware optimum on both sides**, not just the
smallest or largest size tried. The mechanism is precise: `scatter`'s cost (not `write`'s) is what
explodes at small shard sizes -- 20.358ms at 610,352 buckets vs. 2.064ms at the optimum, a ~10x
difference -- because `scatter_kernel`'s own `atomicAdd` into the per-bucket cursor array becomes
a scattered, cache-hostile access pattern once the bucket count gets into the hundreds of
thousands, i.e. the exact same problem this whole design fixed for the main write, recurring one
level down once you push bucketing too far. `roundtrip`, which this sweep specifically added
honest timing for, turned out never to matter (0.05-0.64ms, a rounding error next to the
10-30ms totals) -- so the earlier "untimed, assumed negligible" version's numbers were not
actually misleading, just not fully honest about why.

## marking_bucketed_poc.cu/.py -- integrating the confirmed win into the full pipeline (2026-08-28)

With a real, confirmed shard-size optimum in hand, next step: does bucketing survive integration
into the actual streaming two-tier pipeline, where it has to compete with an architectural cost it
didn't pay in isolation? `marking_two_tier_poc.cu`'s sparse phase used double-buffered cross-chunk
upload/kernel overlap (upload chunk N+1 while chunk N's kernel runs) -- the bucketed pipeline's
host round trip forces a sync point mid-chunk, so `marking_bucketed_poc.cu`'s new
`run_sparse_bucketed_phase()` processes each chunk fully serially instead. Whether the ~2.34x
per-chunk win (measured with no upload cost in the loop) outweighs losing that overlap is
precisely what real hardware needs to answer -- not assumed.

Dense phase is untouched (`run_dense_phase()`, byte-identical logic to the old `run_phase()`'s
dense branch). Sparse phase reuses the confirmed-optimal 128 KB shard by default (configurable via
`--shard-bits`, since it's an input-file parameter, not hardcoded).

**Correctness, verified before hardware** (two layers, since this file has two things that could
be wrong independently of what `sparse_bucketed_poc.cu` already proved correct):
- The compute/scatter/write math itself: unchanged from `sparse_bucketed_poc.cu`, already proven
  correct via that file's 500-case simulation.
- The NEW part -- multiple chunks, each independently bucket-sorted, OR'd into one shared
  persistent buffer, arriving from parallel generator threads in whatever order the queue happens
  to deliver them: a new 300-case simulation (varying `combined_size`, `shard_size`, `chunk_size`
  down to 1, and prime count up to 2,000) confirms that processing primes split into chunks --
  BOTH in original order and in a fully shuffled order (simulating real multi-threaded generation,
  where chunk arrival order isn't guaranteed) -- always produces the exact same position set as a
  single naive unchunked pass. 300/300 pass on both orderings.

Not yet run on real hardware (EXACT mode -- the only thing that validates the actual
primesieve+CUDA integration, not just the arithmetic -- and FULL mode are both pending).

Run:
```
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_bucketed_marking.sh --mode exact
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_bucketed_marking.sh --mode full --gen-threads 24
```

## Real-hardware result: EXACT 7/7 PASS, but FULL mode regressed (2026-08-28)

One real bug found and fixed on the way: `write_sorted_kernel`'s grid size is based on `n_valid`
(how many of a chunk's primes actually land inside `combined_size`), which can legitimately be 0
for a small/early chunk -- a sparse-tier prime has at most one hit in the window, so it's easy
for a whole small chunk to miss entirely. A `<<<0, N>>>` launch is rejected as an invalid argument
on this toolkit. Fixed by skipping the launch when `n_valid == 0` -- exactly the kind of edge case
EXACT mode's tiny-scale cases exist to catch (FULL mode, where chunks have 20 million primes each,
never hits `n_valid == 0` and never would have surfaced this). After the fix: EXACT 7/7 PASS.

FULL mode: **TOTAL=196.448s -- a regression from the unbucketed two-tier's 169.623s (0.86x, i.e.
slower)**, and 1.12x slower than production's full 176.018s (sieve+write). Sparse phase:
`generate_wall=185.944s`, `gpu_wall=185.697s` (of which `roundtrip=9.546s`, only 5.1% -- as
expected, never the issue). This confirms the honest risk flagged before running: bucketing's
~2.34x per-chunk win (measured with zero upload cost in the loop) did NOT survive losing the
cross-chunk upload/kernel overlap that the now-serialized bucketed pipeline gives up. Net,
integrating bucketing here was the wrong move -- the unbucketed two-tier result (169.623s) remains
the best real number in this series so far.

## A bigger, previously-deferred lever surfaces: generator-thread load imbalance

`generate_wall=185.944s` for the sparse tier ALONE (113,528,483,264 primes) is 64% MORE than
production's ENTIRE real sieve step (113.352s, both tiers, ~113.8 billion primes, INCLUDING the
phase_mod computation and the actual marking -- not just raw generation). Our number is generation
alone, doing less work, on a comparable prime volume, and taking substantially longer. That's not
explained by anything found so far in this series.

The suspect, flagged as a deferred item several steps back and never revisited: every file in this
series splits the `n_gen_threads` generator range by EQUAL WIDTH
(`boundaries[i] = range_lo + (total_width * i) / n_gen_threads`). Prime density falls off as
`1/ln(x)`, so equal-width sub-ranges do NOT have equal prime counts -- production instead uses
Mertens-weighted cost-balanced batches (`_build_equal_cost_batches`). If the imbalance is severe,
parallel wall time is dominated by whichever thread got the densest (lowest) sub-range, wasting a
large fraction of the other 23 threads' time once they finish early and sit idle.

`generation_balance_poc.cpp` (new, CPU-only, no GPU/nvcc needed) tests this directly and cheaply:
raw `primesieve_iterator` generation (no marking, no GPU) over the exact real floor-25 sparse
range, 24 threads, comparing (A) the current equal-width split against (B) an equal-COUNT split
via numerically inverting the logarithmic-integral approximation `Li(x) = integral(1/ln(t))` (the
same idea behind production's Mertens weighting, computed here via simple trapezoidal integration
-- no primesieve counting calls needed to build the boundaries, so building them is fast).

**Correctness/soundness, checked before hardware**: syntax-verified via `g++ -fsyntax-only`
against a stub `primesieve.h` (no primesieve installed in this sandbox) -- clean, no errors or
warnings. The boundary-search logic (binary search over a cumulative trapezoidal-integral array,
linear interpolation within the bracketing interval, monotonicity guard against numerical noise)
is straightforward enough that a dedicated correctness harness wasn't built for it -- what matters
here is whether it measurably reduces per-thread imbalance and wall time, which only real hardware
can answer.

Run:
```
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_generation_balance.sh
```

## Artur's proposal: GPU as a phase-precomputation stream feeding CPU (not a marking engine)

Worth recording precisely, since it reframes the whole marking side of this investigation. Artur's
observation: once a prime's target position is known, the CPU's own marking step is essentially
free (a single conditional array write -- production's own code does this in its O(1) branch).
What's actually expensive is computing the phase (`distance mod p`) at scale. Every GPU design in
this series so far has tried to make GPU do BOTH phase computation AND the write -- and the write,
specifically the atomic write into a shared 1.25 GB buffer, is what's been the dominant cost
throughout (85.3% of the unbucketed sparse kernel's cost; the entire reason bucketing was tried at
all). His proposal: have GPU compute ONLY the phases (cheap, ~12-15% of the old sparse kernel's
cost per the `sparse_overhead_poc` decomposition, no atomics needed since each thread's result is
independent) and stream the resulting positions directly to CPU, which does the actual marking --
avoiding the atomic-write bottleneck entirely rather than trying to out-optimize it. His follow-up
refinement: size the transfer/staging buffer to fit in memory that both GPU and CPU can access
fastest (i.e., pinned/page-locked host memory, which GPU can DMA into directly and CPU can read
without an explicit extra copy step), with GPU running only a light, bounded lead ahead of CPU
(mirroring this series' established bounded-queue pattern, but with the roles reversed: GPU
produces, CPU consumes-and-marks) so CPU is never starved and GPU never races arbitrarily far
ahead.

This is sound and consistent with everything measured so far -- but it's capped by the SAME
generation floor as everything else in this file: GPU can't compute a phase for a prime it hasn't
been given, and primes still have to come from parallelized `primesieve_iterator` generation on
CPU. If that step alone is the ~186s bottleneck the imbalance investigation above suggests, no
GPU-side restructuring -- bucketing, phase-streaming, or otherwise -- can bring the total below
that floor until generation itself is fixed. Sequencing: `generation_balance_poc`'s result first,
since it's cheap to get and determines whether the phase-streaming architecture is worth building
against a fair baseline, or whether it would be evaluated against an artificially bottlenecked one.

## Real-hardware result: the imbalance hypothesis was wrong -- and it revealed something bigger

`generation_balance_poc`'s real-hardware run: (A) equal-width WALL=54.543s, per-thread count
imbalance ratio 1.157 (real, but modest). (B) equal-count (Mertens/Li-weighted) WALL=54.618s,
imbalance ratio 1.000 (essentially perfect). **The two are statistically identical in wall time.**
The imbalance hypothesis was wrong -- fixing it changes nothing.

But this result answers a bigger question by itself: RAW generation of the entire real sparse-tier
range (113.5 billion primes, 24 threads) takes only ~54.5s. Yet `marking_bucketed_poc`'s FULL-mode
run measured `generate_wall=185.944s` for that exact same range. The gap (185.944s vs ~54.5s) is
not generation cost at all -- it's generator threads spending most of their time BLOCKED inside
`push_batch_blocking()` on the bounded queue (`MAX_QUEUE_BATCHES=8`), because the GPU/consumer
side (185.697s `gpu_wall`, nearly identical to `generate_wall`, which is itself the signature of a
consumer-bound pipeline) couldn't keep up. **CPU was starved by a slow GPU, not the other way
around.** This matches Artur's own read of the situation exactly, stated independently before this
result came in: CPU is fast enough that it would sieve small sieving primes (2, 3, 5, ...) across
a 10-million-wide window quickly, well within what a properly-paced GPU could keep it fed for.

## phase_stream_poc.cu/.py -- Artur's architecture: GPU computes phase only, CPU marks (2026-08-28)

With CPU's real headroom now confirmed (~54.5s raw generation, and production's own 113.352s
proves CPU marking-once-phase-is-known is cheap too), this file builds Artur's proposed
architecture precisely, in his own words (paraphrased): every design so far had GPU do BOTH phase
computation AND the write. The write -- specifically atomic writes from thousands of concurrent
GPU threads into a shared 1.25 GB buffer -- has been the dominant cost throughout this whole
series (85.3% of the plain sparse kernel; the entire reason bucketing was tried and still hit the
same wall one level down in `scatter_kernel`). His proposal: GPU computes ONLY the phase (cheap,
no atomics -- each thread's result is independent) and streams results to CPU, which does the
actual marking, exactly like production's own per-prime branch. His refinement, added after
walking through a concrete example (segmented-sieve phase setup: to jump into a window without
starting from scratch, every sieving prime up to sqrt of the window needs its phase established
first): size the handoff using memory both GPU and CPU can access with comparably low latency, and
keep GPU's lookahead SMALL and bounded -- GPU must take enough primes at a time that CPU is never
left waiting with no phase ready, but without stockpiling arbitrarily far ahead -- with the
explicit self-check that the handoff
must be a REAL net win, not large enough that CPU computing its own phases would just be faster.

**Design**: `compute_phase_kernel` -- no `combined_size`, no tier branch, no atomics at all;
every sieving prime (dense or sparse) goes through the SAME uniform phase computation and writes
its `start_pos` directly into a pinned + mapped ("zero-copy") host buffer via a GPU-visible device
pointer (`cudaHostAlloc(..., cudaHostAllocMapped)` + `cudaHostGetDevicePointer`) -- no explicit
`cudaMemcpy` D2H for results at all. Two ping-pong segments (`chunk_size` primes each, tunable --
this IS Artur's "lookahead size" knob). While chunk N's kernel runs asynchronously, the CPU thread
marks chunk N-1's already-computed results into the real output buffer via a single, non-atomic,
single-threaded pass that's byte-for-byte production's own branch:
```
if (p >= combined_size) { if (start_pos < combined_size) bits[start_pos>>3] |= mask; }
else { for (pos = start_pos; pos < combined_size; pos += p) bits[pos>>3] |= mask; }
```
This also eliminates the whole dense/sparse GPU-kernel split from every prior file in this
series -- the branch now lives on the CPU side, same as production, so there's only one GPU kernel
again.

**Honest limitation, stated up front**: CPU-side marking here is single-threaded. Production uses
24 CPU workers for its own marking step; a single consumer thread cannot match that parallelism.
This first PoC tests whether the CORE mechanism -- mapped-memory handoff, real overlap, GPU
actually staying fast enough to keep a single CPU thread fed -- works and is fast, before
investing in parallelizing the CPU consumer too. If the core mechanism proves out, that's the
obvious next lever (matching production's 24-worker marking scale).

**Correctness, not yet run on real hardware**: mirrors the established EXACT-mode pattern (7
cases, byte-for-byte against `prime_sieve_engine_v4.c`'s own unmodified function), reusing the
verbatim-copied `phase_mod_gpu` (already validated across 200,000 randomized cases in an earlier
segment) and self-elimination guard. `chunk_size` is exposed as a CLI sweep knob
(`--chunk-size`), since the right lookahead size is an empirical question, not something to guess.

Run:
```
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_phase_stream.sh --mode exact
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_phase_stream.sh --mode full --gen-threads 24
```

## Real-hardware result: phase_stream_poc regressed, but precisely located the bottleneck (2026-08-28)

EXACT mode: 7/7 PASS. FULL mode: **TOTAL=677.942s** -- a regression from the unbucketed two-tier's
169.623s, and from the single-threaded-marking-was-expected-to-cost-something-but-not-this-much
perspective, worse than hoped. But the decomposition is exactly what makes this result useful
rather than a dead end: `generate_wall=677.700s` and `gpu_wall=677.681s` are nearly identical --
the same consumer-bound signature seen earlier in this series, confirming the GPU-phase-only
kernel and the pinned/mapped-memory handoff mechanism themselves are NOT the bottleneck (they keep
pace with whatever is consuming their output). **`cpu_mark_wall=568.427s` is 84% of TOTAL** --
single-threaded CPU marking, not GPU phase computation, not the handoff, is the dominant cost.

Artur's own quick math on this result: a single marking thread here is only about 3.82x slower
than production's real 176.018s benchmark, which does its own marking step across 24 workers.
That ratio is the actionable signal -- it means the architecture (GPU computes phase only, CPU
marks) is fundamentally sound, and the single remaining gap is exactly the kind of thing thread
parallelism should close, not something requiring a different design.

## phase_stream_parallel_poc.cu/.py -- decoupling CPU marking into a thread pool (2026-08-28)

Direct follow-up, keeping `phase_stream_poc`'s GPU-phase-only kernel completely unchanged (no
atomics, no `combined_size`/tier branch on the GPU side -- already confirmed not the bottleneck)
and turning the previous single-threaded, in-lockstep marking step into a THREE-STAGE pipeline,
each stage decoupled by its own bounded queue: CPU generator threads -> [prime batch queue] -> GPU
phase kernel (single driver thread, ping-pong pinned+mapped buffers, unchanged) -> [NEW mark job
queue] -> a POOL of CPU marker threads (`--marker-threads`, independently tunable from
`--gen-threads`). Each marker thread pulls a `MarkJob` (a chunk's primes + GPU-computed positions,
copied out of the pinned buffer so it can be freed quickly for reuse) and marks it via CPU atomic
OR.

The synchronization mechanism was not invented from scratch: `prime_sieve_engine_v4.c`'s
`generate_and_sieve_segment_bits_atomic()` -- production's own function for multiple WORKER
PROCESSES writing concurrently into one shared mmap'd output buffer -- was read directly to confirm
exactly how it handles this. It uses `__atomic_fetch_or(&out_dense_bits[pos >> 3], mask,
__ATOMIC_RELAXED)` on every single write, both tiers. `mark_one_atomic()` in this file mirrors that
line exactly. This is proven-fast on real hardware already: it's precisely what gets production to
its own 113.352s sieve step at 24-way parallelism -- reusing a known-good technique rather than
inventing a new synchronization scheme for this PoC.

Since generation is now known-cheap (~54.5s total per `generation_balance_poc`), the right split of
a 24-core machine between generation / GPU-driving / marking threads is an empirical question --
`--marker-threads` is exposed as an independently-tunable knob from `--gen-threads`, meant to be
swept.

**Correctness verification**: brace-balance and Polish-text scans passed clean on the full file.
The underlying per-prime phase math and marking branch are byte-identical to `phase_stream_poc`
(already validated: 7/7 EXACT PASS on real hardware, and the phase computation itself was validated
across 200,000 randomized cases in an earlier segment). The genuinely new risk here is concurrency
correctness -- multiple marker threads writing into the same shared `bits` buffer -- which is
addressed by reusing production's own proven atomic-OR mechanism rather than a new one, but has
**not yet been run on real hardware**. EXACT mode's 7 cases (mirroring `phase_stream_poc`'s cases,
each now also specifying a small `--marker-threads` value so the pool path is exercised even at
tiny scale, including a case with more marker threads than chunks available) is the first real test
of this.

Run:
```
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_phase_stream_parallel.sh --mode exact
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_phase_stream_parallel.sh --mode full --gen-threads 24 --marker-threads 24
```

Worth sweeping `--marker-threads` independently of `--gen-threads` once EXACT passes -- e.g.
`--gen-threads 4 --marker-threads 20` (generation is cheap, so it shouldn't need many threads) is
one plausible split worth trying alongside the naive `24/24` starting point.

## What to report back (phase-stream-parallel architecture, superseded by cpu_gpu_split_poc below)

From `--mode exact`: PASS/FAIL per case (expect 7/7 -- this is the first real-hardware check of
the NEW concurrency structure, the marker thread pool and its queue, not just the already-verified
phase math). From `--mode full`: `generate_wall`, `gpu_wall`, `marker_busy_total` (summed across
all marker threads -- divide by `n_marker_threads_used` for a rough per-thread utilization sense),
and above all the new TOTAL against the reference points now on the table: best-so-far (169.623s,
unbucketed two-tier), the single-marker phase-stream result (677.942s, cpu_mark_wall=568.427s was
84% of it), and the raw-generation floor (~54.5s). If TOTAL drops meaningfully below 677.942s
that confirms parallelizing CPU marking was the right lever; if it also beats 169.623s, that's a
new best result in this whole series. If `marker_busy_total`'s per-thread average stays high even
with many marker threads, that points at contention on the atomic writes themselves (the same
cache-locality problem bucketing tried to fix on the GPU side) as the next thing to investigate,
rather than thread count.

This line of investigation (all GPU-does-the-marking-work architectures, from `marking_poc.cu`
through `phase_stream_parallel_poc.cu`) was set aside in favor of a structurally different idea
below, not because it failed outright -- it's still an open thread if revisited.

## cpu_gpu_split_poc.py -- Artur's idea: stop sharing a buffer, split the RANGE instead (2026-08-28)

Every architecture above (from the very first `phase_mod_poc` through `phase_stream_parallel_poc`)
tried to make CPU and GPU cooperate on the SAME shared output buffer for the SAME window -- and
every one of them hit some version of the same wall: contention, either on the atomic write itself
(85.3% of the plain sparse kernel's cost) or, once that was routed around via phase-streaming,
on the CPU-side marking queue. Artur's reframing: stop making them share anything. Split the
`combined_size` range into two disjoint sub-windows up front, give one to the REAL unmodified CPU
engine (`prime_sieve_engine_v4.c` via ctypes) and the other to the REAL unmodified GPU two-tier
binary (`marking_two_tier_poc`, already hardware-proven at 169.623s solo), run both **at once**,
concatenate the two bitstrings at the end. Zero shared-buffer contention, zero cross-device sync
during the run -- the same kind of independent-window decomposition production already does across
its own 1000 separate windows today, just with the two halves of one window assigned to different
hardware instead of all windows going to one CPU.

**EXACT-mode bug found and fixed, not in the split logic itself**: cases 5/6/7 initially failed
byte-for-byte against ground truth. Root cause, found by tracing actual mismatched bit positions
back to real prime values: `prime_sieve_engine_v4.c`'s self-elimination guard
(`if (distance + start_pos <= p_val) start_pos += p_val;`) has a latent quirk specifically at
`distance=0` -- `start_pos` also starts at 0 there, so the guard condition is unconditionally true
for every positive prime, self-marking every prime `p < window_m` as composite at its own position.
Invisible at real floor scale (distance=10^25 dwarfs any sieving prime) and invisible even in
`marking_two_tier_poc.py`'s own EXACT tests (both sides of that comparison shared the same
distance=0, reproducing the identical quirk identically on both sides). The split exposed it only
because splitting shifts the GPU sub-window's distance away from 0, so its guard correctly stops
self-marking while unsplit ground truth (still distance=0) kept the bug -- a real, localized
divergence, not a flaw in the split mechanism. Fixed by changing those three cases' `distance` from
`0` to `10**6` (orthogonal to what each case actually tests). Re-run: **EXACT 7/7 PASS** on real
hardware -- the split-then-concatenate mechanism itself was correct all along.

**Multi-worker CPU side**, added once EXACT was clean: the initial CPU side was single-threaded,
an unfair comparison against GPU's already-parallel two-tier kernel. `prepare_cpu_side_parallel()`/
`wait_cpu_side_parallel()` mirror production's own `prime_sieve_v4_1.py` exactly -- equal-COST
(Mertens-weighted) batching of the sieving-prime range, `ProcessPoolExecutor(max_workers=24)`,
atomic `__atomic_fetch_or` writes into one shared `mmap.mmap(MAP_SHARED)` buffer allocated before
the pool forks. One real, GPU-independent hazard was designed around here: `run_split()`'s GPU
thread constantly `print()`s while streaming subprocess output, and `fork()` only clones the
calling thread -- if the print lock is held by another thread at the exact fork instant, the
forked child inherits it stuck forever. Fixed by doing all forking in `prepare_cpu_side_parallel()`
BEFORE the GPU thread starts, confirmed deadlock-free across 5 repeated concurrent CPU+GPU sandbox
trials.

**Real-hardware FULL-mode results, cpu_fraction=0.5, cpu_workers=24, swept via the new
`run_full_sweep_mode()` (one invocation, back-to-back runs, one summary table)**:

| combined_size | t_wall | cpu_elapsed | gpu_total | vs. seq. CPU (n x 176.018s) | vs. seq. GPU (n x 169.623s) |
|---|---|---|---|---|---|
| 10 billion | 230.508s | -- | -- | 1.31x SLOWER | 1.36x SLOWER |
| 20 billion | 268.349s | 189.614s | 258.706s | 0.76x -- 24% FASTER | 0.79x -- 21% FASTER |
| 30 billion | 312.617s | 276.387s | 298.169s | 0.59x -- 41% FASTER | 0.61x -- 39% FASTER |
| 40 billion | 349.470s | 323.074s | 330.204s | 0.50x -- 50% FASTER | 0.52x -- 48% FASTER |

("vs. seq. CPU/GPU" = this run's `t_wall` against running production CPU or GPU-solo
SEQUENTIALLY `n = combined_size / 10^10` times to cover the same total range -- the fair
comparison, since the question is "one big split run" vs. "N separate solo runs," not vs. a solo
run at the same combined_size.)

**Why the trend reverses between 10B and 20B**: at floor-25 scale, `l_final =
isqrt(distance+combined_size)+1` barely moves across this whole 10B-40B range, since `distance`
(10^25) dominates it by ~15 orders of magnitude. The dominant real cost is GENERATING the
sieving-prime base up to `l_final` (~219s at the 10B baseline) -- a cost that depends on
`l_final`/`distance`, essentially fixed regardless of window size, NOT on `combined_size`. Splitting
the WINDOW between CPU and GPU does not split this fixed cost -- it DUPLICATES it, since both
sides independently regenerate the full `[2, l_final)` sieving-prime range. Only the much smaller,
window-size-dependent MARKING cost actually gets divided by the split. At 10B that fixed,
duplicated generation cost dominates and the split loses. As `combined_size` grows, the same fixed
generation cost gets amortized over more marked numbers per run, while running solo devices
sequentially N times pays that fixed generation cost N times over -- so the split's relative
advantage should widen indefinitely... in principle. Measured marginal cost between the 30B and
40B points: only 3.6852s of extra wall time per extra billion numbers covered -- confirming the
curve is genuinely flattening, not a fluke of two data points.

Run:
```
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_cpu_gpu_split.sh --mode exact
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_cpu_gpu_split.sh --mode full --combined-size 10000000000
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_cpu_gpu_split.sh --mode full --combined-size 30000000000,40000000000
```

## Break-even bisection, first pass (2026-08-29): ~14.7-14.8B, under a budget bug

Artur's framing, and the right one: every real tradeoff like this has a crossover point somewhere
-- "tak wyglada rzeczywistosc" (that's what reality looks like). A bisection sweep (10/12/13/14/
15/16/18*10**9, all at the default `cpu_workers=24`, `gpu_gen_threads=12`) pinned the crossover at
roughly combined_size~=14.7-14.8*10**9 -- 14B still measured slightly slower (0.98x/1.02x), 15B
the first point faster on both references. **This number turned out to be measured under a real
bug -- see the next section before trusting it.**

## CPU-core contention bug found and fixed (2026-08-29)

While chasing a follow-up question (does skewing `cpu_fraction` away from 0.5 help, since GPU
visibly sat as the "long pole" at every 50/50 point above), something backwards showed up: raising
`cpu_fraction` made `gpu_total` go UP even though `cs_gpu` was shrinking. For two supposedly
independent devices (that's the whole premise of this design -- disjoint sub-windows, zero shared
buffer), GPU getting LESS work should never make it slower.

Root cause: this whole break-even sweep ran with the default `cpu_workers=24` (real CPU marking
processes) running CONCURRENTLY with `gpu_gen_threads=12` (GPU's own host-side prime generation
threads) -- 36 total OS threads/processes competing for cores on Artur's real 24-logical-core WSL
machine (`nproc` confirmed). A 1.5x oversubscription, present in every FULL-mode number measured in
this file up to this point. The two "independent" devices were fighting over physical cores the
whole time.

**Corrected re-run** (`cpu_workers=12`, `gpu_gen_threads=12` -- sums to exactly 24), same 10-15B
range for a clean before/after:

| combined_size | t_wall (old 24+12) | t_wall (corrected 12+12) | vs seq CPU | vs seq GPU |
|---|---|---|---|---|
| 10B | 230.508s | **220.085s** | 1.25x slower | 1.30x slower |
| 12B | 241.951s | **232.575s** | 1.10x slower | 1.14x slower |
| 13B | 244.847s | **232.847s** | 1.02x slower | 1.06x slower |
| 14B | 241.246s | **233.541s** | 0.95x FASTER | 0.98x FASTER |
| 15B | 251.293s | **240.693s** | 0.91x FASTER | 0.95x FASTER |

Every single point landed 8-12s faster than the identical `combined_size` measured under the
oversubscribed 24+12 budget -- a real, consistent effect across the whole range, not noise. The
break-even crossover moved down accordingly: vs seq CPU now crosses between 13B (1.02x) and 14B
(0.95x) -- linear estimate ~13.25B; vs seq GPU crosses the same two points -- linear estimate
~13.77B. **Corrected practical break-even: roughly combined_size~=13.3-13.8B**, down from the
~14.7-14.8B measured under the thread-budget bug. Lesson for any future sweep in this file:
`cpu_workers + gpu_gen_threads` should sum to <= the real logical core count, or the measurement
becomes the thing being studied.

## Load-balance sweep: 50/50 already near-optimal here (2026-08-29)

Natural follow-up question once GPU was visibly the "long pole" at every 50/50 point: does shifting
`cpu_fraction` toward CPU (giving GPU less, since it's slower per-share) reduce `t_wall`? Built
`run_fraction_sweep_mode()` (sweeps `cpu_fraction` at a FIXED `combined_size`, reports where
`cpu_elapsed` and `gpu_total` cross, i.e. the load-balanced ratio) and tested at combined_size=12B
with the corrected 12+12 thread budget, `cpu_fraction` in {0.5, 0.6, 0.7, 0.8, 0.9}:

| cpu_fraction | t_wall | cpu_elapsed | gpu_total |
|---|---|---|---|
| 0.5 | **233.803s** (fastest) | 179.449s | 227.908s |
| 0.6 | 240.666s | 227.432s | 236.037s |
| 0.7 | 241.705s | 240.673s | 236.676s |
| 0.8 | 255.698s | 254.408s | 244.736s |
| 0.9 | 290.956s | 289.441s | 255.826s |

Result: 0.5 (plain 50/50) was the FASTEST of the five, and `t_wall` got monotonically WORSE as
`cpu_fraction` rose -- the opposite of the naive "GPU is idle longer so give it less" intuition.
Why: CPU's own per-share marking cost grows faster than what shifting share away from GPU actually
saves (CPU's dense-tier marking cost scales roughly with `cs_cpu*ln(ln(cs_cpu))`, not linearly, so
giving CPU a bigger share costs progressively more per additional unit). Simple fraction-skewing is
not the lever that helps here -- see the next section for the architecture that Artur and I think
actually would.

## The real fix, not yet built: a shared work queue instead of a fixed split ratio (2026-08-29)

Artur's own framing, working through a concrete example live: instead of committing to ONE fixed
`cpu_fraction` up front, divide `combined_size` into many small fragments and let CPU and GPU each
pull a new fragment from a shared queue the instant they finish their current one -- the system
self-balances (the faster device naturally pulls more fragments before the slower one finishes)
without ever needing to measure or interpolate a "right" ratio. This generalizes both the plain
50/50 split AND any fixed-ratio load-balance attempt as special/degenerate cases of the same idea.

The math backs the intuition: for N identical-cost fragments split between two devices with
per-fragment costs `tc` (CPU) and `tg` (GPU), the theoretically optimal continuous allocation gives
makespan `T = N * tc*tg/(tc+tg)` -- meaningfully better than any fixed a-priori split, and it
requires no tuning at all, just a live queue.

**The real blocker, not yet solved**: every engine invocation in this file re-pays a large FIXED
cost (generating the full sieving-prime base up to `l_final`) once per invocation. Handing a device
"one more fragment" as a fresh `run_split()`/process call would re-pay that fixed cost per
fragment -- catastrophic, exactly the duplication problem the whole `combined_size`-scaling
hypothesis was built around avoiding. Making the queue idea real requires keeping each device's
worker pool (and its already-generated prime base) ALIVE across multiple fragment assignments,
feeding it more marking work on the same base rather than spawning a fresh invocation per fragment
-- a genuine architecture change, bigger than anything built in this file so far. Not started;
recorded here as the clear next target once the current split mode's basic viability is fully
settled.

## CPU "bonus round" (three-way split): tried, confirmed correct, confirmed a net LOSS (2026-08-29)

A concrete, smaller first stab at the shared-queue idea above: instead of the full N-fragment
queue, give CPU just ONE extra "bonus" slice on top of its normal round -- carved out of
`combined_size` via `--cpu-bonus-fraction` -- that CPU picks up the moment its first round
finishes, submitted to the SAME already-forked `ProcessPoolExecutor` (no second `fork()`, so no
risk of forking while the GPU thread is concurrently printing its subprocess's stderr -- see
`prepare_cpu_side_parallel()`'s docstring for why that ordering matters). See
`split_window_three_way()`/`run_split_three_way()`/`run_full_scale_mode_three_way()` in
`cpu_gpu_split_poc.py`.

EXACT mode: 14/14 cases PASS (7 plain 2-way regression + 7 new three-way cases, including
`cpu_bonus_fraction=0.0` degenerating to the plain split, `cpu_fraction=0.0` with a nonzero bonus
exercising the no-round-1 pool-startup path, and the u128-distance branch) -- the split/concatenate
mechanism itself is genuinely correct.

FULL mode (`combined_size=13.5*10**9`, `cpu_fraction=0.5`, `cpu_bonus_fraction=0.15`,
`cpu_workers=12`, `gpu_gen_threads=12`): **NEGATIVE**. `t_wall=298.712s` -- roughly 28% SLOWER
than a plain 50/50 split at the same scale (~233s interpolated from the corrected 13B/14B sweep
points above). `cs_cpu1=5.7375*10**9` took `cpu1_elapsed=172.034s`; `cs_cpu2=2.025*10**9` -- a
window only 35% as big -- still took `cpu2_elapsed=124.689s` (73% as long).

**Root cause**: reusing the same forked pool avoids re-paying the process-STARTUP cost, but does
nothing about the actual dominant cost this whole file has been chasing since its first FULL run
-- each worker walking the sieving-prime range from 2 up to `l_final` (here 3.16*10**12) to find
which primes even need checking. That walk is genuinely redone, in full, for round 2, because
`_build_equal_cost_batches()`+`process_batch_cpu()` gets invoked a SECOND time over the same
`[2, l_final)` range. Submitting to an already-alive pool only sidesteps the fork-safety hazard,
not the actual duplicated generation work, which barely depends on window size once `l_final` is
this much bigger than either window. This confirms the design-phase worry (see
`run_fraction_sweep_mode()`'s docstring) was right for the wrong reason solved: pool-reuse alone
was never going to be enough.

**What would actually fix it, not yet built**: a single primesieve walk per worker that marks
into BOTH windows' output buffers in the SAME pass -- a new engine function taking two
`(distance, window_m, byte_offset)` tuples instead of one, checking both per prime found, so the
expensive part (walking to `l_final`) is paid exactly once no matter how many logical CPU
"rounds" get folded into it. This is a real engineering step up (a new additive C function, same
pattern as `marking_two_tier_poc.cu` never touching the production engine) rather than a pure
Python-orchestration change like this attempt was.

## CPU "bonus round" v2: dual-window single-pass marking (2026-08-29, sandbox-verified, not yet on real hardware)

The fix the previous section said was "not yet built": `dual_window_engine_poc.c`, a new additive
C engine (does NOT modify `prime_sieve_engine_v4.c`, same discipline as `marking_two_tier_poc.cu`
on the GPU side). Its `generate_and_sieve_dual_window[_atomic]()` walks the sieving-prime range
from `start` to `stop` via `primesieve_next_prime()` **exactly once** per worker, and marks into
TWO independent `(distance, window_m, out_bits)` targets per prime found (`mark_one()`, a verbatim
port of the production engine's phase/self-elimination-guard/dense-sparse marking logic, called
twice per prime instead of once). This removes the round1/round2 architecture entirely: there is
no "CPU finishes round 1, then submits round 2" anymore, just one pass that marks both windows as
it goes -- so the walk-to-`l_final` cost that `run_split_three_way()` was shown to duplicate
(172.034s + 124.689s for two rounds instead of ~172s total) is structurally paid only once,
regardless of how the total CPU share is divided between the "normal" and "bonus" windows.

Python-side wiring in `cpu_gpu_split_poc.py`: `split_window_three_way()` is reused unchanged for
the window layout (same `cpu_fraction`/`cpu_bonus_fraction` carve-up as the round-based version,
so the two mechanisms are directly comparable at identical scale). `run_split_dual_window()` is
the new orchestrator -- CPU side is a single dual-marking pass (`_create_dual_cpu_executor()` +
`_submit_cpu_round_dual()` for the real multi-process path, `run_cpu_side_dual()` for the
single-threaded EXACT-mode ground-truth path), GPU side is unchanged (same `marking_two_tier_poc`
binary, same window). New CLI flag `--dual-window` selects this path (only takes effect together
with `--cpu-bonus-fraction F > 0`); without it, `--cpu-bonus-fraction` still uses the older,
already-confirmed-negative round-based mechanism from the previous section.

**Explicit open question, not yet answered -- documented directly in `run_split_dual_window()`'s
and `run_full_scale_mode_dual_window()`'s docstrings so it isn't mistaken for a promised win**:
removing the double-generation-cost bug only isolates whether that bug was the WHOLE reason the
three-way split lost. It's still an open question whether a CPU-heavier split (bigger total CPU
share, whether as two windows or one) can beat or even match the plain 50/50 baseline once that
bug is gone -- `run_fraction_sweep_mode()` already found that skewing `cpu_fraction` above 0.5
makes wall time monotonically WORSE in the plain 2-way split, because CPU's own dense-tier marking
cost grows faster (`~cs*ln(ln(cs))`) than what it saves GPU. Both outcomes (dual-window matches/
beats 50/50, or dual-window still loses because the fraction-skew cost dominates regardless of the
generation-duplication fix) are informative and neither was assumed going in.

**Sandbox verification (no real libprimesieve/GPU in this environment, same fake-trial-division-
engine technique used for the three-way split)**: `dual_window_engine_poc.c` syntax-checked clean
(`gcc -fsyntax-only`) against a stub header matching the real `primesieve.h` API shape. A from-
scratch test harness ran all three EXACT-mode suites together -- plain 2-way (7/7), three-way
(7/7), and the new dual-window suite (14/14 -- same 7 case definitions as three-way, each run twice:
once through `generate_and_sieve_dual_window` single-threaded, once through the atomic
multi-process path via `generate_and_sieve_dual_window_atomic`) -- 28/28 total, no regressions from
the refactoring needed to add the dual-window path. A direct correctness cross-check confirmed
`run_split_three_way()` and `run_split_dual_window()` produce byte-identical `combined_bits` for
the same window layout. A synthetic small-scale cost comparison (`combined_size=4000,
l_final=60000`, chosen so `l_final >> combined_size` to mirror the real floor-25 shape where
generation cost dominates) found dual-window's CPU total cost 0.950x the three-way mechanism's --
directionally supportive of the fix, though not scale-representative of real hardware.

**REAL-HARDWARE RESULT (2026-09-02)**: EXACT mode **28/28 PASS**. FULL mode
(`combined_size=13.5*10**9`, `cpu_fraction=0.5`, `cpu_bonus_fraction=0.15`, `cpu_workers=12`,
`gpu_gen_threads=12`): `cs_cpu1=5,737,500,032`, `cs_cpu2=2,025,000,000` marked in ONE dual pass
took `cpu_elapsed=250.181s`, vs `296.723s` (172.034s+124.689s) for the SAME two windows under the
round-based mechanism's two separate passes -- confirming the double-generation-cost bug is fixed:
a real **46.5s / 15.7% CPU-side improvement**. `t_wall=251.981s` vs `298.712s` for the round-based
run at the same scale/split -- **46.7s / 15.6% faster overall**. But `t_wall=251.981s` is still NOT
competitive with the plain 50/50 baseline (`~233.2s` interpolated at 13.5B from the corrected
13B/14B sweep) -- about **8.1% SLOWER** (printed by the script as `1.06x` vs. the sequential-CPU
reference and `1.10x` vs. the sequential-GPU reference, both "still slower").

**Conclusion**: both outcomes the docstrings flagged as open landed at once. The double-generation
bug was real and this mechanism fixes it -- `run_split_dual_window()` should always be preferred
over `run_split_three_way()`'s round-based mechanism whenever a CPU bonus round is used at all.
But fixing that bug alone does not make a CPU-heavier split beat plain 50/50 -- CPU's own
dense-tier marking cost (the same effect `run_fraction_sweep_mode()` already found: cost grows
faster than linear as `cpu_fraction` rises, here the effective CPU share is ~57.5%) still dominates
and still loses, independent of mechanism. The "CPU bonus round" idea, in both its forms, is now a
closed question: it does not beat plain 50/50 at this scale. **The shared work-queue idea above
("The real fix, not yet built") remains the more promising direction** -- it lets the faster device
naturally absorb more work without ever over-committing a fixed a-priori share to the slower one,
which is exactly the failure mode both bonus-round mechanisms hit.

Per Artur's standing instruction ("najpierw test nowego kodu potem komit" -- test first, then
commit): real-hardware testing is now done and the result is documented above; no commit has been
made yet -- pending Artur's explicit go-ahead.

Run (WSL, real hardware):
```
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_cpu_gpu_split.sh --mode exact
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_cpu_gpu_split.sh --mode full --combined-size 13500000000 --cpu-fraction 0.5 --cpu-bonus-fraction 0.15 --cpu-workers 12 --gpu-gen-threads 12 --dual-window
```

## What to report back (cpu_gpu_split_poc, current priority)

From `--mode exact`: PASS/FAIL per case (expect 28/28 as of the dual-window addition -- 7 plain
2-way + 7 three-way round-based + 14 dual-window sub-cases). For further break-even narrowing on
the plain 2-way split, sweep `--combined-size` around the corrected ~13.3-13.8B estimate (e.g.
`13000000000,13500000000,14000000000`) WITH `--cpu-workers 12 --gpu-gen-threads 12` (or whatever
sums to the real core count on the machine running it -- confirm via `nproc`) to avoid
re-introducing the oversubscription bug. Do NOT use `--cpu-bonus-fraction` WITHOUT `--dual-window`
expecting a speedup -- that's the round-based mechanism, a confirmed net loss (see above). The
NEW priority is the real-hardware FULL-mode run for `--cpu-bonus-fraction 0.15 --dual-window` at
`combined_size=13.5*10**9` (command above) -- this is the first real test of whether removing the
double-generation-cost bug lets a CPU-heavier split match or beat plain 50/50, an open question,
not a guaranteed win (see the dual-window section above for why).

## What to report back (parallel chunked marking, superseded by the two-tier section above)

EXACT mode PASS/FAIL per case (should be PASS on all 6 -- this is the one that matters most,
since it's the only real-hardware confirmation of the new partitioning logic; the Python
simulation only proves the arithmetic, not the actual primesieve+CUDA behavior). For FULL mode:
`n_gen_threads` actually used, `t_generate_wall` (parallel), `t_gpu_wall` (pipelined), TOTAL, and
the direct ratio against the prior serial run's 1316.729s -- that answers whether parallel
generation + pipelining closes the gap with production's 176.018s, narrows it, or reveals a
different bottleneck entirely (e.g. if generation is still the long pole even parallelized, or if
GPU kernel time alone -- independent of generation -- already exceeds production's total, which
would point at a more fundamental algorithmic mismatch between full-range marking and
production's segmented-sieve approach rather than a pipelining problem).

## What to report back (superseded steps below)

For this step: EXACT mode PASS/FAIL per case (should be PASS on all 5). For STRESS mode: total
primes processed, chunk count, the full timing breakdown (generate/upload/kernel/download/
total), and the "allocated once" VRAM line -- that combination answers whether the design
actually holds up at real scale (correct output, flat VRAM, and a real sense of how long
generating + marking ~8-9*10^8 primes actually takes end to end on your hardware, which is the
first number in this whole series directly comparable to production's real floor-25 timings).

For FULL mode: total primes processed, chunk count, the full timing breakdown, marked-composite
density, and whether it completed without error (VRAM exhaustion, `is_error` from primesieve,
etc.). This is the number that matters most right now -- it's the real floor-25 scale, directly
comparable (with the caveats printed by the run itself: no disk-write yet, single-threaded CPU
generation not yet parallelized) to the real 2026-08-16 production benchmark's 176.018s total
(113.352s sieve + 62.666s write) at this exact same `combined_size`.

For the earlier steps (phase-only floors, resident-primes, marking-kernel fix), see each of
their own sections above -- still relevant background, but this chunked-marking step is the
current priority since it's the first one exercising real scale end to end.

For the earlier phase-only steps (floors 16/25/28, resident-primes, chunked/streaming), see
each of their own sections above for what to report -- still relevant if you want to revisit
those numbers, but this fix's re-verification is the current priority.
