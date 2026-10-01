/* ==========================================================================================
 * prime_sieve_engine_v3.c -- sieve-generation core, v3 (atomic shared-buffer variant).
 *
 * generate_and_sieve_segment_bits_atomic() is prime_sieve_engine_v1.c's
 * generate_and_sieve_segment_bits() with the bit-set operation
 *     out_dense_bits[pos >> 3] |= (unsigned char)(1u << (pos & 7));
 * replaced by an atomic fetch-or:
 *     __atomic_fetch_or(&out_dense_bits[pos >> 3], (unsigned char)(1u << (pos & 7)),
 *                        __ATOMIC_RELAXED);
 *
 * WHY: prime_sieve_v3.py allocates ONE shared output buffer (mmap(MAP_SHARED|MAP_ANONYMOUS),
 * allocated in the parent BEFORE forking worker processes) instead of a private buffer per
 * worker that is pickled back to the parent for a sequential OR-merge. Batches partition
 * the SIEVING-PRIME axis, not the output axis -- two batches' primes CAN strike the same
 * output byte -- so with multiple worker PROCESSES writing into the SAME buffer, a plain
 * `|=` is a data race (non-atomic read-modify-write across processes). The atomic
 * instruction closes that race; output is bit-for-bit identical to a single-threaded pass.
 *
 * L_final/window_m semantics, the marking algorithm (self-elimination guard, mod-arithmetic
 * start position, striding) and count_sieving_primes() are the same as v1. The plain
 * (non-atomic) functions are also present here as copies (not imported -- no dependency on
 * prime_sieve_engine_v1.c/.so), so this file is a complete, independently buildable engine.
 *
 * BUILD (WSL, after building+installing libprimesieve):
 *   gcc -O3 -shared -fPIC prime_sieve_engine_v3.c -o prime_sieve_engine_v3.so \
 *       -lprimesieve -lstdc++ -lm
 * ========================================================================================== */

#include <primesieve.h>
#include <stdint.h>

/* PRIME_SIEVE_ENGINE_VERSION -- see prime_sieve_v3.py's VERSION comment for the full
 * rationale (an at-a-glance iteration marker). This C file's own logic is unaffected by the
 * count_sieving_primes toggle -- that toggle is purely a Python-side call-site decision
 * (whether to call count_sieving_primes() at all); the version marker here just stays in
 * step with the Python side's. */
#define PRIME_SIEVE_ENGINE_VERSION "v3.1"

typedef unsigned __int128 u128;

/* ------------------------------------------------------------------------------------------
 * generate_and_sieve_segment_bits -- copy of prime_sieve_engine_v1.c's function (see that
 * file for the full docstring). Kept here so v3 has no build-time
 * dependency on v1 -- used by prime_sieve_v3.py's ground-truth/ correctness-anchor path and
 * anywhere a single-threaded, non-shared-buffer call is wanted.
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

        uint64_t rem = (uint64_t)(distance % (u128)p_val);
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
 * generate_and_sieve_segment_bits_atomic -- the v3 change. Called once per batch, same as
 * v1's function, but into a buffer that MULTIPLE PROCESSES may be writing into concurrently
 * (see module header) -- hence the atomic fetch-or.
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

        uint64_t rem = (uint64_t)(distance % (u128)p_val);
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
 * count_sieving_primes -- pi(limit) via primesieve_count_primes() (same as v1).
 * ========================================================================================== */
uint64_t count_sieving_primes(uint64_t limit) {
    return primesieve_count_primes(0, limit);
}
