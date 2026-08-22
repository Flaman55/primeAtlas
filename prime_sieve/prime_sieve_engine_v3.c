/* ==========================================================================================
 * prime_sieve_engine_v3.c -- sieve-generation core, v3 (atomic shared-buffer variant).
 *
 * LINEAGE: prime_sieve_engine_v1.c (this folder), with ONE change, mirroring the versioning
 * pattern prime_sieve_v2.py's own header documents (separate vN file for a structural change
 * to the performance-critical core, not a git-commit-only change -- v1/v2 stay fully
 * untouched and independently runnable).
 *
 * WHAT CHANGED: generate_and_sieve_segment_bits_atomic() is bit-for-bit IDENTICAL to v1's
 * generate_and_sieve_segment_bits(), except the bit-set operation
 *     out_dense_bits[pos >> 3] |= (unsigned char)(1u << (pos & 7));
 * is now an atomic fetch-or:
 *     __atomic_fetch_or(&out_dense_bits[pos >> 3], (unsigned char)(1u << (pos & 7)),
 *                        __ATOMIC_RELAXED);
 *
 * WHY: v3's orchestration (prime_sieve_v3.py) allocates ONE shared output buffer
 * (mmap(MAP_SHARED|MAP_ANONYMOUS), allocated in the parent BEFORE forking worker processes)
 * instead of giving each worker process its own PRIVATE buffer that gets pickled back to the
 * parent for a sequential OR-merge (v1/v2's mechanism). Different batches partition the
 * SIEVING-PRIME axis, not the output axis -- two different batches' primes CAN strike the
 * same output byte -- so once multiple worker PROCESSES write into the SAME shared buffer
 * concurrently, a plain `|=` is a genuine data race (non-atomic read-modify-write across
 * process boundaries). The atomic instruction closes that race.
 *
 * WHY THIS IS WORTH THE NEW ENGINE FILE: at production scale, measuring the old return-and-
 * merge step end to end (not just in isolation) showed 24-way process parallelism delivering
 * almost NO real speedup over a single-threaded pass over the same range, because the
 * parent's sequential return+OR-merge of dozens of large private buffers ate essentially all
 * of the parallel savings. Switching to this shared-buffer mechanism roughly halved total
 * wall time, while producing bit-for-bit identical output (verified against a single-
 * threaded ground-truth pass).
 *
 * What did NOT change: L_final/window_m semantics, the marking algorithm itself (self-
 * elimination guard, mod-arithmetic start position, striding), count_sieving_primes(). v1's
 * plain (non-atomic) functions are also still present here UNCHANGED (copy-pasted, not
 * imported -- this file has zero dependency on prime_sieve_engine_v1.c/.so) so this file
 * remains a complete, independently buildable engine, matching v1/v2's own "no cross-file
 * source dependency" convention.
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
 * generate_and_sieve_segment_bits -- UNCHANGED copy of v1's function (see
 * prime_sieve_engine_v1.c for the full original docstring). Kept here so v3 has no build-time
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
 * count_sieving_primes -- UNCHANGED from v1 (see that file for the full docstring).
 * ========================================================================================== */
uint64_t count_sieving_primes(uint64_t limit) {
    return primesieve_count_primes(0, limit);
}
