/* iterator_chunk_gen.c -- small, standalone helper (NOT part of the production engine) that
 * exposes libprimesieve's primesieve_iterator to Python via ctypes, for
 * phase_mod_chunked_poc.py to use instead of prime_sieve_primesieve.py's
 * generate_primes_in_range() (which calls primesieve_generate_primes(), the "materialize a
 * full array" API).
 *
 * WHY THIS EXISTS (2026-08-28): Artur pointed out that the ACTUAL production engine
 * (prime_sieve_engine_v4.c's generate_and_sieve_segment_bits()) already does exactly the
 * "kubełkowanie"/streaming this GPU PoC series has been trying to achieve -- via
 * primesieve_iterator, one prime at a time, zero array materialization, fused directly with
 * phase computation and marking in one tight C loop (see that function, lines ~89-113). THAT
 * is why floor 25's real sieve_seconds is 113s total, not the multi-hour figure
 * phase_mod_chunked_poc.py's first run extrapolated to at true scale -- that extrapolation
 * was measuring the cost of prime_sieve_primesieve.py's generate_primes_in_range() (the
 * array-building API), not libprimesieve's actual internal streaming speed, which the
 * production engine already benefits from and this PoC series had not been using.
 *
 * fill_chunk() below streams primes the SAME way generate_and_sieve_segment_bits() does
 * (primesieve_iterator / primesieve_jump_to / primesieve_next_prime -- literally the same
 * three calls, same order), but stores each prime into a caller-supplied buffer instead of
 * immediately computing phase+marking, since here the buffer's destination is a GPU upload,
 * not an in-process C loop. This is the only functional difference from the production
 * function; everything about how primes are streamed is unchanged.
 *
 * Build: gcc -O3 -shared -fPIC iterator_chunk_gen.c -o iterator_chunk_gen.so -lprimesieve
 * (same flags as prime_sieve_engine_v4.c's own build command, minus -lstdc++/-lm which that
 * file needs for unrelated reasons this one doesn't have -- see prime_sieve_v4_1.py's own
 * _load_lib() docstring for that exact command).
 */
#include <stdint.h>
#include <primesieve.h>

/* fill_chunk -- streams up to max_n primes strictly greater than or equal to start_after,
 * via primesieve_iterator, into out_buf (caller-allocated, must hold at least max_n
 * uint64_t). Writes *next_start_after = (last prime written) + 1, so the caller can pass
 * that straight back in for the next chunk with no gap or overlap (same contract as
 * phase_mod_chunked_poc.py's own next_chunk() had, just implemented in C instead of
 * Python+ctypes-array-building).
 *
 * Returns the number of primes actually written (== max_n in every normal case -- primes
 * never run out), or -1 if libprimesieve itself reported an error (it.is_error, checked
 * ONCE after the loop -- same pattern as generate_and_sieve_segment_bits(), not checked
 * per-prime, since primesieve's own convention is to only set this flag on genuine
 * internal failure, not as a per-call return code).
 */
int64_t fill_chunk(uint64_t start_after, uint64_t max_n, uint64_t* out_buf,
                    uint64_t* next_start_after) {
    if (max_n == 0) {
        *next_start_after = start_after;
        return 0;
    }

    primesieve_iterator it;
    primesieve_init(&it);
    /* stop_hint is only a sizing hint for libprimesieve's internal segment buffer, not a
     * hard limit -- the iterator happily continues past it if asked (see libprimesieve's own
     * docs for primesieve_jump_to). A generous but not wildly oversized hint avoids
     * unnecessary internal buffer growth. */
    uint64_t stop_hint = start_after + max_n * 40 + 1000;  /* generous flat margin -- see
                                                              module header for why exactness
                                                              here doesn't matter */
    primesieve_jump_to(&it, start_after, stop_hint);

    uint64_t p_val = 0;
    uint64_t n = 0;
    while (n < max_n) {
        p_val = primesieve_next_prime(&it);
        out_buf[n] = p_val;
        n++;
    }

    *next_start_after = p_val + 1;

    int err = it.is_error;
    primesieve_free_iterator(&it);
    return err ? -1 : (int64_t)n;
}
