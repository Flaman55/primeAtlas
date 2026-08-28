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

**Not yet re-verified on your hardware** (this fix was applied after your last run, in the same
sitting as this decomposition result): both `marking_poc.py --mode exact` (to confirm the
restructuring didn't change output -- should still be 8/8 PASS) and
`marking_overhead_poc.py` (to see the real achieved speedup vs. the ~5.5-6x estimate above,
directly in the "full(ms)" column of a fresh SWEEP A run) need to run again.

## What to report back

Re-run both:
```
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_marking.sh --mode exact
bash /mnt/h/PrimeAtlas_refactor/primeAtlas/prime_sieve/gpu_poc/build_and_run_overhead.sh
```
Report: EXACT mode PASS/FAIL (should still be 8/8), and the new SWEEP A/B tables -- specifically
whether `full(ms)` at `n_primes=20,000,000` dropped meaningfully below the old 364.3ms, and by
how much (that's the real, measured answer to whether this fix was worth it, vs. the ~5.5-6x
estimate above).

For the earlier phase-only steps (floors 16/25/28, resident-primes, chunked/streaming), see
each of their own sections above for what to report -- still relevant if you want to revisit
those numbers, but this fix's re-verification is the current priority.
