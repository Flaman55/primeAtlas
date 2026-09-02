/* ==========================================================================================
 * dual_window_engine_poc.c -- additive engine variant for cpu_gpu_split_poc.py's "CPU bonus
 * round" (2026-08-29), built after the round1/round2 pool-reuse attempt (run_split_three_way())
 * was measured on real hardware to be a net LOSS: t_wall=298.712s at combined_size=13.5*10**9,
 * cpu_bonus_fraction=0.15, vs. ~233s for a plain 50/50 split at the same scale. Root cause found
 * by reading the numbers, not guessing: cs_cpu1=5.7375*10**9 took cpu1_elapsed=172.034s, and
 * cs_cpu2=2.025*10**9 -- a window only 35% as big -- still took cpu2_elapsed=124.689s (73% as
 * long). Reusing the SAME already-forked ProcessPoolExecutor for round 2 avoided re-forking, but
 * did nothing about the actual dominant cost: each worker walking the sieving-prime range from 2
 * up to l_final via primesieve a SECOND time for round 2, on top of the first walk for round 1.
 * That walk barely depends on window size once l_final is much bigger than either window (here
 * l_final=3.16*10**12), so round 2 duplicated most of round 1's cost instead of avoiding it.
 *
 * THIS FILE's FIX: walk the sieving-prime range from `start` to `stop` EXACTLY ONCE per worker,
 * and mark BOTH windows (two independent (distance, window_m, out_bits) triples) per prime found
 * in that single walk. The expensive part -- primesieve_next_prime() -- is now paid exactly once
 * no matter how many logical CPU "rounds" get folded into a single call; marking twice per prime
 * found is cheap by comparison (a few extra branches and, at most, one extra stride loop), since
 * marking cost has never been the dominant term anywhere in this whole PoC series.
 *
 * DELIBERATELY ADDITIVE, NOT A MODIFICATION: prime_sieve_engine_v4.c (the real, unmodified
 * production engine) is left untouched, same as every other engine variant in this series
 * (marking_two_tier_poc.cu is the GPU-side precedent for this pattern). This file duplicates
 * prime_sieve_engine_v4.c's phase/self-elimination-guard/dense-vs-sparse marking logic verbatim
 * per window (see mark_one() below), generalized to run twice per prime instead of once, rather
 * than sharing code with the production file -- keeping the PoC fully self-contained and the
 * production engine's own correctness argument completely unaffected by this experiment.
 *
 * `window_m == 0` on either window makes this degenerate correctly to a single-window call
 * (mark_one() returns immediately for that window) -- lets the same function be used even when
 * cpu_bonus_fraction=0.0 (round 2 empty) without a separate code path.
 *
 * BUILD (WSL, after building+installing libprimesieve, same flags as prime_sieve_engine_v4.c):
 *   gcc -O3 -shared -fPIC dual_window_engine_poc.c -o dual_window_engine_poc.so \
 *       -lprimesieve -lstdc++ -lm
 * ========================================================================================== */

#include <primesieve.h>
#include <stdint.h>

typedef unsigned __int128 u128;

/* ------------------------------------------------------------------------------------------
 * mark_one -- marks a single prime's hit into ONE window's output buffer. Verbatim port of
 * prime_sieve_engine_v4.c's generate_and_sieve_segment_bits_atomic() inner body (phase_mod via
 * the plain u128 modulo -- this PoC doesn't need the inlined-divq fast path prime_sieve_engine_v4
 * added, since generation cost here is dominated by primesieve_next_prime() itself, not by the
 * per-prime phase computation), generalized into a helper so generate_and_sieve_dual_window*()
 * below can call it twice per prime found instead of duplicating the marking logic inline twice.
 * `atomic` selects the atomic (multi-process, shared-buffer) vs plain (single-threaded,
 * ground-truth-style) write, mirroring prime_sieve_engine_v4.c's own atomic/non-atomic pair.
 * ------------------------------------------------------------------------------------------ */
static inline void mark_one(u128 distance, uint64_t p_val, uint64_t window_m,
                             unsigned char *out_bits, int atomic) {
    if (window_m == 0 || out_bits == 0) return;

    uint64_t rem = (uint64_t)(distance % (u128)p_val);
    uint64_t start_pos = (rem == 0) ? 0 : (p_val - rem);
    if (distance + start_pos <= (u128)p_val) start_pos += p_val;
    if (start_pos >= window_m) return;

    if (p_val >= window_m) {
        unsigned char mask = (unsigned char)(1u << (start_pos & 7));
        if (atomic) {
            __atomic_fetch_or(&out_bits[start_pos >> 3], mask, __ATOMIC_RELAXED);
        } else {
            out_bits[start_pos >> 3] |= mask;
        }
    } else {
        uint64_t pos = start_pos;
        while (pos < window_m) {
            unsigned char mask = (unsigned char)(1u << (pos & 7));
            if (atomic) {
                __atomic_fetch_or(&out_bits[pos >> 3], mask, __ATOMIC_RELAXED);
            } else {
                out_bits[pos >> 3] |= mask;
            }
            pos += p_val;
        }
    }
}

/* ------------------------------------------------------------------------------------------
 * generate_and_sieve_dual_window[_atomic] -- ONE primesieve walk over [start, stop), marking
 * into TWO independent (distance, window_m, out_bits) targets per prime found. This is the
 * whole point of this file: the walk itself (the dominant cost, per every measurement in this
 * PoC series) happens exactly once, regardless of how many logical CPU "rounds" the caller
 * conceptually wants -- see this file's header for the real-hardware measurement that motivated
 * this over the two-separate-invocations approach (run_split_three_way() in
 * cpu_gpu_split_poc.py).
 * ------------------------------------------------------------------------------------------ */
static int gen_sieve_dual(uint64_t start, uint64_t stop,
                           uint64_t distance1_hi, uint64_t distance1_lo, uint64_t window_m1,
                           unsigned char *out_bits1,
                           uint64_t distance2_hi, uint64_t distance2_lo, uint64_t window_m2,
                           unsigned char *out_bits2, int atomic) {
    if (start >= stop) return 0;

    u128 distance1 = ((u128)distance1_hi << 64) | (u128)distance1_lo;
    u128 distance2 = ((u128)distance2_hi << 64) | (u128)distance2_lo;

    primesieve_iterator it;
    primesieve_init(&it);
    primesieve_jump_to(&it, start, stop);

    uint64_t p_val;
    while ((p_val = primesieve_next_prime(&it)) < stop) {
        if (p_val < 2) continue;
        mark_one(distance1, p_val, window_m1, out_bits1, atomic);
        mark_one(distance2, p_val, window_m2, out_bits2, atomic);
    }

    int err = it.is_error;
    primesieve_free_iterator(&it);
    return err ? -1 : 0;
}

int generate_and_sieve_dual_window(uint64_t start, uint64_t stop,
                                    uint64_t distance1_hi, uint64_t distance1_lo,
                                    uint64_t window_m1, unsigned char *out_bits1,
                                    uint64_t distance2_hi, uint64_t distance2_lo,
                                    uint64_t window_m2, unsigned char *out_bits2) {
    return gen_sieve_dual(start, stop, distance1_hi, distance1_lo, window_m1, out_bits1,
                           distance2_hi, distance2_lo, window_m2, out_bits2, 0);
}

int generate_and_sieve_dual_window_atomic(uint64_t start, uint64_t stop,
                                           uint64_t distance1_hi, uint64_t distance1_lo,
                                           uint64_t window_m1, unsigned char *out_bits1,
                                           uint64_t distance2_hi, uint64_t distance2_lo,
                                           uint64_t window_m2, unsigned char *out_bits2) {
    return gen_sieve_dual(start, stop, distance1_hi, distance1_lo, window_m1, out_bits1,
                           distance2_hi, distance2_lo, window_m2, out_bits2, 1);
}
