/* ==========================================================================================
 * prime_sieve_engine_v1.c -- sieve-generation core for the prime warehouse project, v1.
 *
 * Instead of reading sieving primes from a warehouse file on disk (measured as a hard
 * speed ceiling -- ~99% of wall time, ~45s/chunk regardless of language/thread
 * architecture), this GENERATES them on the fly via primesieve_iterator
 * (segmented sieve of Eratosthenes + mod-210 wheel, zero disk access) and uses them
 * immediately to sieve the combined window [distance, distance+window_m) -- one function,
 * one ctypes call from Python, no intermediate buffers of raw sieving primes.
 *
 * Segmentation of the sieving-prime axis [2, L_final] into chunks [start, stop) is done
 * ON THE PYTHON SIDE (orchestration via ProcessPoolExecutor -- proven in this project to be
 * free of the contention that plagued multi-pthread-in-one-process designs).
 * Cost of primesieve_jump_to(start) is O(sqrt(start) * log log sqrt(start)) -- at
 * start~10^12 that's generating ~10^6 "bootstrap" primes, on the order of milliseconds --
 * so fine-grained segmentation (many small, independent segments) does not pay a repeated
 * "primesieve spin-up" penalty.
 *
 * ARCHITECTURAL SIMPLIFICATION vs. the old warehouse: NO anchor/higher-layer distinction.
 * Every generated segment sieves the WHOLE combined window directly (window_m =
 * combined_size). Rationale: L_1 (smallest sieving-prime limit in a batch) and L_N
 * (largest) differ by a negligible fraction at this depth (10^7 window vs ~10^25 position
 * -> L difference on the order of 10^-6) -- splitting into anchor/layers would be a
 * practically useless micro-optimization at the cost of complexity.
 *
 * BUILD (WSL, after building+installing libprimesieve):
 *   gcc -O3 -shared -fPIC prime_sieve_engine_v1.c -o prime_sieve_engine_v1.so \
 *       -lprimesieve -lstdc++ -lm
 * ========================================================================================== */

#include <primesieve.h>
#include <stdint.h>

typedef unsigned __int128 u128;

/* start, stop: range of sieving primes to generate (half-open interval [start, stop))
 * distance_hi/distance_lo: start of the COMBINED window (128-bit, split into 2x uint64 --
 *   ctypes from Python has no native 128-bit int)
 * window_m: width of the combined window (bytes in out_dense)
 * out_dense: OUTPUT buffer of length >= window_m, MUST be zeroed BEFORE calling --
 *   this function only SETS bytes to 1, never clears them (same convention as the other
 *   C scanners in this project)
 *
 * Returns: 0 = success, -1 = error in libprimesieve (e.g. invalid range)
 */
int generate_and_sieve_segment(uint64_t start, uint64_t stop,
                                uint64_t distance_hi, uint64_t distance_lo,
                                uint64_t window_m, unsigned char *out_dense) {
    if (start >= stop) return 0;  /* empty segment -- nothing to do */

    u128 distance = ((u128)distance_hi << 64) | (u128)distance_lo;

    primesieve_iterator it;
    primesieve_init(&it);
    /* stop_hint = stop -- primesieve only buffers up to this limit, saving memory and
       some generation time compared to jump_to without a hint */
    primesieve_jump_to(&it, start, stop);

    uint64_t p_val;
    while ((p_val = primesieve_next_prime(&it)) < stop) {
        if (p_val < 2) continue;

        uint64_t rem = (uint64_t)(distance % (u128)p_val);
        uint64_t start_pos = (rem == 0) ? 0 : (p_val - rem);

        /* self-elimination guard -- at production scale (distance >> p_val) this
           practically never triggers */
        if (distance + start_pos <= (u128)p_val) start_pos += p_val;

        if (start_pos >= window_m) continue;

        if (p_val >= window_m) {
            out_dense[start_pos] = 1;
        } else {
            uint64_t pos = start_pos;
            while (pos < window_m) {
                out_dense[pos] = 1;
                pos += p_val;
            }
        }
    }

    int err = it.is_error;
    primesieve_free_iterator(&it);
    return err ? -1 : 0;
}

/* ==========================================================================================
 * generate_and_sieve_segment_bits -- bit-packed output buffer (OOM fix from the original
 * v5.2 lineage).
 *
 * The byte-per-position version above, at 200 windows (combined_size=2 billion bytes),
 * killed the process (OOM): the result buffer was 1 BYTE/position, allocated in EACH of
 * 24 worker processes -- up to 24 x 2GB = 48GB of buffers at once. This version packs the
 * result BIT-WISE (1 BIT/position, exactly how primesieve represents its own sieve
 * internally) -- 8x less memory: 200 windows -> 250MB/process instead of 2GB/process. The
 * rest of the logic is identical.
 *
 * out_dense_bits: OUTPUT buffer of length >= ceil(window_m/8) bytes, MUST be zeroed BEFORE
 *   calling. Bit `pos` (0-indexed from the start of the window) lives in byte
 *   out_dense_bits[pos>>3], bit position (pos&7), counting from LSB=bit0 -- NOTE on the
 *   Python side: np.unpackbits(..., bitorder='little') to match this convention.
 */
int generate_and_sieve_segment_bits(uint64_t start, uint64_t stop,
                                     uint64_t distance_hi, uint64_t distance_lo,
                                     uint64_t window_m, unsigned char *out_dense_bits) {
    if (start >= stop) return 0;  /* empty segment -- nothing to do */

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

/* ==========================================================================================
 * count_sieving_primes -- benchmark metric: how many distinct sieving primes p in [2, limit]
 * were actually used to sieve a combined window (limit = L_final = isqrt(combined_hi) + 1,
 * computed on the Python side exactly as before -- this doesn't change that logic, just
 * reports pi(limit) so it can be recorded alongside the timing/throughput numbers already in
 * benchmark_log.csv).
 *
 * Thin wrapper around primesieve_count_primes(), which uses libprimesieve's own fast prime-
 * COUNTING algorithm (not iteration/generation) -- negligible cost next to the actual sieve
 * pass above, safe to call once per batch even at deep floor levels where L_final itself is
 * large.
 * ========================================================================================== */
uint64_t count_sieving_primes(uint64_t limit) {
    return primesieve_count_primes(0, limit);
}
