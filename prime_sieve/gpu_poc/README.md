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

## What to report back

For each floor (16, 25, 28):
- PASS or FAIL (should be PASS at all three -- if not, that's a real bug to fix before
  anything else)
- The three throughput lines (GPU kernel-only, GPU incl. transfer, CPU/Python reference)
- The extrapolated total if you also run with `--count-true-total` on at least one floor

That's enough for me to tell you honestly whether this specific approach (double-reciprocal
mulmod, sample-based) is worth pushing toward a real Barrett-reduction version and eventual
integration into a v5 engine, or whether it's a dead end and we should think differently.
