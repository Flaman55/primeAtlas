/* prime_sieve_engine_pt1.c -- partial sieve + primality test (engine pt1).
 *
 * The partial sieve of engine_pt_core.h with every survivor tested:
 *   - det != 0: strong probable prime to the 13 bases 2..41 (deterministic below
 *     3.317e24, Sorenson-Webster);
 *   - det == 0: BPSW = strong probable prime to base 2 + strong Lucas test with
 *     Selfridge's method A (P = 1, Q = (1 - D) / 4, first D of 5, -7, 9, ... with
 *     Jacobi(D / n) = -1); a perfect square has no such D and is rejected.
 *
 * PRECONDITION: every number of the slab is larger than B and than 41, so no sieving
 * prime or base is a member of the slab (prime_sieve_pt1.py clamps B to isqrt of the
 * lowest number).
 *
 * Build: gcc -O3 -Wall -shared -fPIC prime_sieve_engine_pt1.c -o prime_sieve_engine_pt1.so
 *        -lprimesieve -lpthread -lm
 */

#include "engine_pt_core.h"

static int test_det(u128 n, const void *arg) { (void)arg; return is_prime_det(n); }
static int test_bpsw(u128 n, const void *arg) { (void)arg; return is_prime_bpsw(n); }

/* sieving primes 3..b (b < 2^32); NULL on allocation failure */
void *pt1_ctx_new(u64 b) { return pt_ctx_new(b); }

u64 pt1_ctx_count(void *ctx) { return pt_ctx_count(ctx); }

void pt1_ctx_free(void *ctx) { pt_ctx_free(ctx); }

/* Composite bitmap of the n_odd odd numbers from first_odd (u128 as hi/lo halves) into
 * out_bits ((n_odd + 7) / 8 bytes). chunk_odd is rounded up to a multiple of 8;
 * *chunks_done counts finished chunks for progress. Returns 0, or -1 on bad arguments or
 * allocation failure. */
int pt1_sieve_odd(void *ctx, u64 first_hi, u64 first_lo, u64 n_odd, int det, u64 n_threads,
                  u64 chunk_odd, unsigned char *out_bits, volatile u64 *chunks_done) {
    return pt_sieve_odd(ctx, first_hi, first_lo, n_odd, det ? test_det : test_bpsw, NULL,
                        n_threads, chunk_odd, out_bits, chunks_done);
}
