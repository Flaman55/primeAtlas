/* ==========================================================================================
 * prime_sieve_engine_v5.c -- sieve-generation core, v5.
 *
 * Loaded by prime_sieve_v5.py. The shared output buffer holds odd numbers only (one bit per
 * odd number, see sieve_odd_bits_atomic()): half the memory of a bit per number, and every
 * sieving prime strides it by p bits instead of p numbers, so p = 2 and half of each odd
 * prime's hits disappear. count_sieving_primes() is the same as in prime_sieve_engine_v4.c.
 *
 * For every sieving prime p, the engine needs first_odd mod p (the phase of the combined
 * range's first odd number relative to p, i.e. which residue class p first strikes inside
 * the range). first_odd is a 128-bit value (unsigned __int128); p is 64-bit. Compiled plainly,
 * `first_odd % (u128)p_val` becomes a call into libgcc's __umodti3 for EVERY sieving prime.
 * The common case (dividend's high 64 bits less than the divisor, so the quotient fits in
 * 64 bits) is one hardware `divq`, inlined at the call site via a small asm block; the full
 * u128 division remains as the fallback, so results are exact in every case.
 *
 * The u128 `first_odd` value is still used for the self-elimination guard (the first odd
 * multiple equal to p itself); only the modulo goes through the fast path. u128 addition and
 * comparison involve no division and generate no library calls.
 *
 * sieve_odd_segmented() marks the small sieving primes inside one slice of the buffer, segment
 * by segment in a private cache-sized word array, with a stored next offset per prime and a
 * presieve pattern for 3..13; each finished segment is ORed into the shared buffer one 64-bit
 * word at a time. Primes from work_plan_v5.small_prime_stop() up take the full-buffer stride
 * of sieve_odd_bits_atomic(). Both paths use lock-prefixed ORs on the same memory (8-bit and
 * 64-bit); x86 keeps mixed-size locked operations atomic and coherent.
 *
 * count_sieving_primes_range() alongside count_sieving_primes() counts only the primes in
 * [start, stop], so repeat pi(L_final) requests on the same floor can reuse a previously
 * counted prefix (see prime_sieve_v5.py's count_sieving_primes_cached()).
 *
 * BUILD (WSL, after building+installing libprimesieve):
 *   gcc -O3 -shared -fPIC prime_sieve_engine_v5.c -o prime_sieve_engine_v5.so \
 *       -lprimesieve -lstdc++ -lm
 * ========================================================================================== */

#include <primesieve.h>
#include <stdint.h>
#include <stdlib.h>

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
 * first_multiple_bit -- bit index (relative to the odd number `first`) of the first odd
 * multiple of p at or above `first`:
 *   k = (-first) mod p      offset of the first multiple of p at or above first;
 *   k odd -> k += p          that multiple is even, the next one (k + p) is odd;
 *   i = k / 2                its bit.
 * first_marked_bit -- the same, skipping p itself (first + 2*i == p -> i += p): p stays
 * unmarked and the next odd multiple is 3p.
 * ------------------------------------------------------------------------------------------ */
static inline uint64_t first_multiple_bit(u128 first, uint64_t first_hi, uint64_t first_lo,
                                          uint64_t p_val) {
    uint64_t rem = phase_mod(first, first_hi, first_lo, p_val);
    uint64_t k = (rem == 0) ? 0 : (p_val - rem);
    if (k & 1) k += p_val;
    return k >> 1;
}

static inline uint64_t first_marked_bit(u128 first, uint64_t first_hi, uint64_t first_lo,
                                        uint64_t p_val) {
    uint64_t i = first_multiple_bit(first, first_hi, first_lo, p_val);
    if (first + 2 * (u128)i == (u128)p_val) i += p_val;
    return i;
}

/* ------------------------------------------------------------------------------------------
 * sieve_odd_bits_atomic -- marks every odd composite of the combined range in the shared
 * odd-only buffer (multiple worker processes write into one mmap'd buffer; see
 * prime_sieve_engine_v3.c's header for why the write must be atomic).
 *
 * Bit i stands for the odd number first_odd + 2*i (first_odd = (first_odd_hi:first_odd_lo),
 * odd); n_bits bits in total. Even numbers are not stored, so p = 2 is skipped and every odd
 * prime p in [start, stop) strides the buffer by p bits (2p numbers) from first_marked_bit().
 * ------------------------------------------------------------------------------------------ */
int sieve_odd_bits_atomic(uint64_t start, uint64_t stop,
                          uint64_t first_odd_hi, uint64_t first_odd_lo,
                          uint64_t n_bits, unsigned char *out_odd_bits) {
    if (start >= stop) return 0;

    u128 first_odd = ((u128)first_odd_hi << 64) | (u128)first_odd_lo;

    primesieve_iterator it;
    primesieve_init(&it);
    primesieve_jump_to(&it, start, stop);

    uint64_t p_val;
    while ((p_val = primesieve_next_prime(&it)) < stop) {
        if (p_val < 3) continue;

        uint64_t i = first_marked_bit(first_odd, first_odd_hi, first_odd_lo, p_val);
        while (i < n_bits) {
            unsigned char mask = (unsigned char)(1u << (i & 7));
            __atomic_fetch_or(&out_odd_bits[i >> 3], mask, __ATOMIC_RELAXED);
            i += p_val;
        }
    }

    int err = it.is_error;
    primesieve_free_iterator(&it);
    return err ? -1 : 0;
}

/* ------------------------------------------------------------------------------------------
 * sieve_odd_segmented -- marks the odd composites of bits [bit_lo, bit_hi) of the shared
 * odd-only buffer (bit i = first_odd + 2*i, as in sieve_odd_bits_atomic()) that have an odd
 * prime factor below `stop`. bit_lo must be a multiple of 64, so the slice owns whole words
 * of out_words except where bit_hi cuts the last one; that word is masked to the slice.
 *
 * The slice is processed in segments of segment_words 64-bit words in a private array:
 *   - presieve: PRESIEVE_PRIMES (3..13) repeat with a period of PRESIEVE_WORDS words (their
 *     product, in 64-bit words), so a pattern built once per slice is copied word by word;
 *     a presieve prime that lies inside the segment is cleared again afterwards;
 *   - primes FIRST_SEGMENTED_PRIME..stop-1: each keeps its next bit offset across segments,
 *     so its phase is computed once per slice;
 *   - the segment is ORed into out_words with one atomic 64-bit OR per nonzero word.
 * Returns 0, -1 on a primesieve or allocation failure, -2 when bit_lo is not word aligned.
 * ------------------------------------------------------------------------------------------ */
#define PRESIEVE_WORDS 15015u   /* 3 * 5 * 7 * 11 * 13 */
static const uint64_t PRESIEVE_PRIMES[] = {3, 5, 7, 11, 13};
#define N_PRESIEVE_PRIMES (sizeof(PRESIEVE_PRIMES) / sizeof(PRESIEVE_PRIMES[0]))
#define FIRST_SEGMENTED_PRIME 17

int sieve_odd_segmented(uint64_t stop, uint64_t first_odd_hi, uint64_t first_odd_lo,
                        uint64_t bit_lo, uint64_t bit_hi, uint64_t segment_words,
                        uint64_t *out_words) {
    if (bit_lo >= bit_hi) return 0;
    if (bit_lo & 63) return -2;
    if (segment_words == 0) segment_words = 1;

    u128 first = (((u128)first_odd_hi << 64) | (u128)first_odd_lo) + 2 * (u128)bit_lo;
    uint64_t first_hi = (uint64_t)(first >> 64), first_lo = (uint64_t)first;
    uint64_t n = bit_hi - bit_lo;
    uint64_t *out = out_words + (bit_lo >> 6);

    size_t n_primes = 0;
    uint64_t *primes = NULL;
    if (stop > FIRST_SEGMENTED_PRIME) {
        primes = (uint64_t *)primesieve_generate_primes(FIRST_SEGMENTED_PRIME, stop - 1,
                                                        &n_primes, UINT64_PRIMES);
        if (!primes) return -1;
    }
    uint64_t *next = (uint64_t *)malloc((n_primes ? n_primes : 1) * sizeof(uint64_t));
    uint64_t *pattern = (uint64_t *)calloc(PRESIEVE_WORDS, sizeof(uint64_t));
    uint64_t *seg = (uint64_t *)malloc(segment_words * sizeof(uint64_t));
    int rc = 0;
    if (!next || !pattern || !seg) {
        rc = -1;
        goto done;
    }

    for (size_t k = 0; k < n_primes; k++)
        next[k] = first_marked_bit(first, first_hi, first_lo, primes[k]);

    for (size_t t = 0; t < N_PRESIEVE_PRIMES; t++) {
        uint64_t q = PRESIEVE_PRIMES[t];
        for (uint64_t j = first_multiple_bit(first, first_hi, first_lo, q);
             j < (uint64_t)PRESIEVE_WORDS * 64; j += q)
            pattern[j >> 6] |= 1ull << (j & 63);
    }

    uint64_t seg_bits = segment_words * 64;
    for (uint64_t s = 0; s < n; s += seg_bits) {
        uint64_t e = (n - s < seg_bits) ? n : s + seg_bits;
        uint64_t nw = (e - s + 63) >> 6;

        uint64_t pw = (s >> 6) % PRESIEVE_WORDS;
        for (uint64_t w = 0; w < nw; w++) {
            seg[w] = pattern[pw];
            if (++pw == PRESIEVE_WORDS) pw = 0;
        }
        for (size_t t = 0; t < N_PRESIEVE_PRIMES; t++) {
            u128 q = PRESIEVE_PRIMES[t];
            if (q < first) continue;
            uint64_t idx = (uint64_t)((q - first) >> 1);
            if (idx >= s && idx < e) seg[(idx - s) >> 6] &= ~(1ull << ((idx - s) & 63));
        }

        for (size_t k = 0; k < n_primes; k++) {
            uint64_t p = primes[k], j = next[k];
            while (j < e) {
                uint64_t r = j - s;
                seg[r >> 6] |= 1ull << (r & 63);
                j += p;
            }
            next[k] = j;
        }

        if ((e - s) & 63) seg[nw - 1] &= (1ull << ((e - s) & 63)) - 1;
        uint64_t *dst = out + (s >> 6);
        for (uint64_t w = 0; w < nw; w++)
            if (seg[w]) __atomic_fetch_or(&dst[w], seg[w], __ATOMIC_RELAXED);
    }

done:
    free(seg);
    free(pattern);
    free(next);
    if (primes) primesieve_free(primes);
    return rc;
}

/* ==========================================================================================
 * count_sieving_primes -- pi(limit) via primesieve_count_primes() (same as v1/v3).
 *
 * count_sieving_primes_range -- ADDITIVE, does not touch anything above. Counts primes in
 * [start, stop] instead of always starting at 0. Lets the Python side turn "count primes up
 * to L_final" into "count primes up to the PREVIOUSLY cached L, plus only the new primes
 * between that L and the new, slightly larger L_final" for repeat runs on the same floor --
 * see prime_sieve_v5.py's count_sieving_primes_cached() for the caching layer built on top of
 * this. primesieve_count_primes(start, stop) already supports an arbitrary start for free;
 * this just exposes that through ctypes instead of hardcoding start=0.
 * ========================================================================================== */
uint64_t count_sieving_primes(uint64_t limit) {
    return primesieve_count_primes(0, limit);
}

uint64_t count_sieving_primes_range(uint64_t start, uint64_t stop) {
    return primesieve_count_primes(start, stop);
}
