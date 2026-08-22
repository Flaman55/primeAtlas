/* ==========================================================================================
 * prime_sieve_engine_v4.c -- sieve-generation core, v4 (inlined 128/64 phase modulo).
 *
 * LINEAGE: prime_sieve_engine_v3.c (this folder), with ONE change to the per-prime phase
 * computation described below. The marking algorithm, atomic shared-buffer write, and
 * count_sieving_primes() are otherwise unchanged.
 *
 * WHAT CHANGED: for every sieving prime p, the engine needs distance mod p (the phase of the
 * combined window's start relative to p, i.e. which residue class p first strikes inside the
 * window). distance is a 128-bit value (unsigned __int128); p is 64-bit. Disassembly of the
 * v3 build showed `distance % (u128)p_val` compiling to a call into libgcc's __umodti3 for
 * EVERY sieving prime -- a real function-call cost (argument marshalling, call/ret, no
 * inlining) paid inside the single hottest loop in the program, independent of how deep the
 * floor is.
 *
 * __umodti3 itself already special-cases the common situation (dividend's high 64 bits less
 * than the divisor, which guarantees the quotient fits in 64 bits) down to one hardware
 * `divq` instruction; it only falls back to a full multi-word division when that guarantee
 * doesn't hold. This file inlines that same fast case directly at the call site via a small
 * asm block, so the common case pays for exactly one `divq` and nothing else -- no call, no
 * argument shuffling, no libgcc dependency for that path. The full u128 division remains as a
 * fallback for the (rare) case where the guarantee doesn't hold, so results are identical to
 * v3 in every case, not just the fast one.
 *
 * The u128 `distance` value itself is still constructed and used for the subsequent
 * self-elimination guard (`distance + start_pos <= p_val`); only the modulo operation is
 * routed through the fast path. u128 addition and comparison do not involve division and were
 * not observed to generate library calls.
 *
 * ALSO ADDED (later, purely additive, does not touch the above): count_sieving_primes_range()
 * alongside the original count_sieving_primes() -- lets the Python side count only the primes
 * in [start, stop] instead of always recounting from 0, so repeat pi(L_final) requests on the
 * same floor can reuse a previously counted prefix instead of paying the full count again.
 * See count_sieving_primes_range()'s own comment below and prime_sieve_v4.py's
 * count_sieving_primes_cached().
 *
 * BUILD (WSL, after building+installing libprimesieve):
 *   gcc -O3 -shared -fPIC prime_sieve_engine_v4.c -o prime_sieve_engine_v4.so \
 *       -lprimesieve -lstdc++ -lm
 * ========================================================================================== */

#include <primesieve.h>
#include <stdint.h>

typedef unsigned __int128 u128;

/* ------------------------------------------------------------------------------------------
 * udiv128_rem -- remainder of (hi:lo) / divisor via a single `divq`. Caller MUST guarantee
 * hi < divisor, which is exactly the condition under which the quotient fits in 64 bits and
 * the instruction does not fault (#DE). Standard extended-asm idiom for a 128-by-64 division
 * with a 64-bit result: dividend supplied across RAX:RDX (lo, hi), quotient/remainder read
 * back from RAX/RDX after the instruction.
 * ------------------------------------------------------------------------------------------ */
static inline uint64_t udiv128_rem(uint64_t hi, uint64_t lo, uint64_t divisor) {
    uint64_t quot, rem;
    __asm__("divq %[divisor]"
            : "=a"(quot), "=d"(rem)
            : "a"(lo), "d"(hi), [divisor] "rm"(divisor));
    (void)quot;
    return rem;
}

/* ------------------------------------------------------------------------------------------
 * phase_mod -- distance mod p_val, taking the inlined fast path whenever the quotient is
 * guaranteed to fit in 64 bits (distance_hi < p_val -- always true for every floor where the
 * combined window's start fits in 64 bits, i.e. distance_hi == 0, and for most primes at
 * greater depth too, since L_final grows far slower than distance). Falls back to the full
 * u128 modulo (identical to v3) otherwise.
 * ------------------------------------------------------------------------------------------ */
static inline uint64_t phase_mod(u128 distance, uint64_t distance_hi, uint64_t distance_lo,
                                  uint64_t p_val) {
    if (distance_hi < p_val) {
        return udiv128_rem(distance_hi, distance_lo, p_val);
    }
    return (uint64_t)(distance % (u128)p_val);
}

/* ------------------------------------------------------------------------------------------
 * generate_and_sieve_segment_bits -- non-atomic variant, for single-threaded/ground-truth
 * callers. Same phase-computation change as the atomic variant below.
 * ------------------------------------------------------------------------------------------ */
int generate_and_sieve_segment_bits(uint64_t start, uint64_t stop,
                                     uint64_t distance_hi, uint64_t distance_lo,
                                     uint64_t window_m, unsigned char *out_dense_bits) {
    if (start >= stop) return 0;

    u128 distance = ((u128)distance_hi << 64) | (u128)distance_lo;

    primesieve_iterator it;
    primesieve_init(&it);
    primesieve_jump_to(&it, start, stop);

    uint64_t p_val;
    while ((p_val = primesieve_next_prime(&it)) < stop) {
        if (p_val < 2) continue;

        uint64_t rem = phase_mod(distance, distance_hi, distance_lo, p_val);
        uint64_t start_pos = (rem == 0) ? 0 : (p_val - rem);

        if (distance + start_pos <= (u128)p_val) start_pos += p_val;

        if (start_pos >= window_m) continue;

        if (p_val >= window_m) {
            out_dense_bits[start_pos >> 3] |= (unsigned char)(1u << (start_pos & 7));
        } else {
            uint64_t pos = start_pos;
            while (pos < window_m) {
                out_dense_bits[pos >> 3] |= (unsigned char)(1u << (pos & 7));
                pos += p_val;
            }
        }
    }

    int err = it.is_error;
    primesieve_free_iterator(&it);
    return err ? -1 : 0;
}

/* ------------------------------------------------------------------------------------------
 * generate_and_sieve_segment_bits_atomic -- shared-buffer variant used by the v3/v4
 * orchestration (multiple worker processes writing into one mmap'd output buffer; see
 * prime_sieve_engine_v3.c's header for why the write must be atomic).
 * ------------------------------------------------------------------------------------------ */
int generate_and_sieve_segment_bits_atomic(uint64_t start, uint64_t stop,
                                            uint64_t distance_hi, uint64_t distance_lo,
                                            uint64_t window_m, unsigned char *out_dense_bits) {
    if (start >= stop) return 0;

    u128 distance = ((u128)distance_hi << 64) | (u128)distance_lo;

    primesieve_iterator it;
    primesieve_init(&it);
    primesieve_jump_to(&it, start, stop);

    uint64_t p_val;
    while ((p_val = primesieve_next_prime(&it)) < stop) {
        if (p_val < 2) continue;

        uint64_t rem = phase_mod(distance, distance_hi, distance_lo, p_val);
        uint64_t start_pos = (rem == 0) ? 0 : (p_val - rem);

        if (distance + start_pos <= (u128)p_val) start_pos += p_val;

        if (start_pos >= window_m) continue;

        if (p_val >= window_m) {
            unsigned char mask = (unsigned char)(1u << (start_pos & 7));
            __atomic_fetch_or(&out_dense_bits[start_pos >> 3], mask, __ATOMIC_RELAXED);
        } else {
            uint64_t pos = start_pos;
            while (pos < window_m) {
                unsigned char mask = (unsigned char)(1u << (pos & 7));
                __atomic_fetch_or(&out_dense_bits[pos >> 3], mask, __ATOMIC_RELAXED);
                pos += p_val;
            }
        }
    }

    int err = it.is_error;
    primesieve_free_iterator(&it);
    return err ? -1 : 0;
}

/* ==========================================================================================
 * count_sieving_primes -- unchanged from v1/v3.
 *
 * count_sieving_primes_range -- ADDITIVE, does not touch anything above. Counts primes in
 * [start, stop] instead of always starting at 0. Lets the Python side turn "count primes up
 * to L_final" into "count primes up to the PREVIOUSLY cached L, plus only the new primes
 * between that L and the new, slightly larger L_final" for repeat runs on the same floor --
 * see prime_sieve_v4.py's count_sieving_primes_cached() for the caching layer built on top of
 * this. primesieve_count_primes(start, stop) already supports an arbitrary start for free;
 * this just exposes that through ctypes instead of hardcoding start=0.
 * ========================================================================================== */
uint64_t count_sieving_primes(uint64_t limit) {
    return primesieve_count_primes(0, limit);
}

uint64_t count_sieving_primes_range(uint64_t start, uint64_t stop) {
    return primesieve_count_primes(start, stop);
}
