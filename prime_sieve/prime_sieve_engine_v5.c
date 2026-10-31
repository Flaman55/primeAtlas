/* ==========================================================================================
 * prime_sieve_engine_v5.c -- sieve-generation core, v5.
 *
 * Loaded by prime_sieve_v5.py. The shared output buffer holds odd numbers only: bit i stands
 * for the odd number first_odd + 2*i (first_odd = (first_odd_hi:first_odd_lo), odd), n_bits
 * bits in total. That is half the memory of a bit per number, and every sieving prime strides
 * it by p bits instead of p numbers, so p = 2 and half of each odd prime's hits disappear.
 * count_sieving_primes() is the same as in prime_sieve_engine_v4.c.
 *
 * For every sieving prime p, the engine needs first_odd mod p (the phase of the combined
 * range's first odd number relative to p, i.e. which residue class p first strikes inside
 * the range). first_odd is a 128-bit value (unsigned __int128); p is 64-bit. Deep floors have
 * about 10^11 sieving primes, so this phase is a fixed per-prime cost of every run, next to
 * generating the prime itself. phase_rem() computes it exactly by one of two paths:
 *   - double: the quotient first_odd / p is estimated in double precision and the remainder
 *     corrected by at most one p (a pipelined floating-point division);
 *   - divq: one hardware 128-by-64 `divq` when the quotient fits in 64 bits, else the full
 *     u128 modulo (a libgcc __umodti3 call).
 * phase_first_marked_bit() exposes the result for tests.
 *
 * sieve_odd_segmented() marks the small sieving primes inside one slice of the buffer, segment
 * by segment in a private cache-sized word array, with a stored next offset per prime and a
 * presieve pattern for 3..13; each finished segment is ORed into the shared buffer one 64-bit
 * word at a time. Slices run in parallel worker processes, so the ORs are lock-prefixed.
 *
 * sieve_odd_bucketed() marks the primes from work_plan_v5.small_prime_stop() up. Their hits
 * land at random places of a buffer far larger than any cache, so a direct OR per hit costs a
 * DRAM line read and write-back; 24 threads saturate at roughly 230 million such ORs per
 * second, locked or not, with or without prefetching. Instead, threads append every hit as a
 * 32-bit offset to a per-region bucket (sequential writes) and, in rounds, apply the buckets
 * region by region while the region is cache resident. It runs alone on the buffer (after the
 * segmented slices), so the apply step uses plain ORs.
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
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

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
 * phase_ctx -- the fixed dividend of every phase computation of a call (`first`, an odd
 * number) in the forms phase_rem() needs.
 *
 * phase_rem -- first mod p. The double path applies when p >= dbl_min_p (so the true
 * quotient Q = first / p is below 2^DBL_QUOT_BITS) and p < 2^53 (p is exact as a double):
 * fd = first rounded to double has a relative error of at most 2^-53 and fd / p adds another
 * 2^-53, so the computed quotient is within Q * 2^-52 * (1 + 2^-53) < 0.26 of Q. Truncated,
 * it is floor(Q) - 1, floor(Q) or floor(Q) + 1, so first - q*p lies in [-p, 2p) and fits an
 * int64; it is computed modulo 2^64 from the low word and corrected by one p. Otherwise
 * phase_mod() divides exactly.
 * ------------------------------------------------------------------------------------------ */
#define DBL_QUOT_BITS 50
#define DBL_EXACT_LIMIT (1ull << 53)

typedef struct {
    u128 first;
    uint64_t hi, lo;
    double fd;
    uint64_t dbl_min_p, dbl_width;   /* double path: p - dbl_min_p < dbl_width */
} phase_ctx;

static void phase_init(phase_ctx *c, u128 first) {
    c->first = first;
    c->hi = (uint64_t)(first >> 64);
    c->lo = (uint64_t)first;
    c->fd = (double)first;
    u128 min_p = (first >> DBL_QUOT_BITS) + 1;
    c->dbl_min_p = (min_p >= DBL_EXACT_LIMIT) ? DBL_EXACT_LIMIT : (uint64_t)min_p;
    c->dbl_width = DBL_EXACT_LIMIT - c->dbl_min_p;
}

static inline uint64_t phase_rem(const phase_ctx *c, uint64_t p_val) {
    if (__builtin_expect(p_val - c->dbl_min_p < c->dbl_width, 1)) {
        uint64_t q = (uint64_t)(c->fd / (double)p_val);
        int64_t r = (int64_t)(c->lo - q * p_val);
        if (r < 0)
            r += (int64_t)p_val;
        else if ((uint64_t)r >= p_val)
            r -= (int64_t)p_val;
        return (uint64_t)r;
    }
    return phase_mod(c->first, c->hi, c->lo, p_val);
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
static inline uint64_t first_multiple_offset(const phase_ctx *c, uint64_t p_val) {
    uint64_t rem = phase_rem(c, p_val);
    return (rem == 0) ? 0 : (p_val - rem);
}

static inline uint64_t odd_multiple_bit(uint64_t k, uint64_t p_val) {
    if (k & 1) k += p_val;
    return k >> 1;
}

static inline uint64_t skip_self(const phase_ctx *c, uint64_t i, uint64_t p_val) {
    if (c->first + 2 * (u128)i == (u128)p_val) i += p_val;
    return i;
}

static inline uint64_t first_multiple_bit(const phase_ctx *c, uint64_t p_val) {
    return odd_multiple_bit(first_multiple_offset(c, p_val), p_val);
}

static inline uint64_t first_marked_bit(const phase_ctx *c, uint64_t p_val) {
    return skip_self(c, first_multiple_bit(c, p_val), p_val);
}

uint64_t phase_first_marked_bit(uint64_t first_hi, uint64_t first_lo, uint64_t p_val) {
    phase_ctx c;
    phase_init(&c, ((u128)first_hi << 64) | (u128)first_lo);
    return first_marked_bit(&c, p_val);
}

/* ------------------------------------------------------------------------------------------
 * sieve_odd_segmented -- marks the odd composites of bits [bit_lo, bit_hi) of the shared
 * odd-only buffer (bit i = first_odd + 2*i, see the header) that have an odd
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
    phase_ctx ph;
    phase_init(&ph, first);
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
        next[k] = first_marked_bit(&ph, primes[k]);

    for (size_t t = 0; t < N_PRESIEVE_PRIMES; t++) {
        uint64_t q = PRESIEVE_PRIMES[t];
        for (uint64_t j = first_multiple_bit(&ph, q);
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

/* ------------------------------------------------------------------------------------------
 * sieve_odd_bucketed -- marks the odd composites of the whole buffer that have a prime factor
 * in one of the pieces [piece_lo[k], piece_hi[k]) of sieving primes, with n_threads threads.
 * Each thread claims the next unclaimed piece (atomic counter) whenever it finishes one, so a
 * thread that runs slower takes fewer pieces and all threads run out of work together.
 *
 * The buffer is cut into regions of 2^shift bits, 2^shift the largest power of two not above
 * region_bits. Each thread owns cap 32-bit slots per region (cap from bucket_bytes, the
 * memory of all threads together). Every round:
 *   1. scatter: each thread walks its primes and appends every hit's offset within its region
 *      to its bucket of that region. A thread stops when one of its buckets is full (it keeps
 *      its prime and next bit for the next round) and raises round_over; the others stop
 *      before their next prime with a hit. Primes whose first hit lies beyond the buffer
 *      (most of them on deep floors) are skipped in a tight loop that touches no bucket.
 *   2. barrier, then apply: thread t ORs the buckets of every thread for the regions
 *      [R*t/T, R*(t+1)/T) into out_bits, one region at a time.
 *   3. barrier; each thread empties its buckets. The run ends after the round in which every
 *      thread ran out of pieces.
 * pieces_done[0] counts finished pieces (atomic) so the caller can report progress.
 * PRECONDITION: no other writer touches out_bits during the call (the apply step uses plain
 * ORs; regions are exclusive between the threads of this call).
 * Returns 0, -1 on a primesieve, allocation or thread failure.
 * ------------------------------------------------------------------------------------------ */
#define MIN_BUCKET_SLOTS 16u

typedef struct bucket_shared bucket_shared;

typedef struct {
    bucket_shared *sh;
    uint64_t index;
    uint64_t piece;          /* piece being walked (valid while in_piece) */
    int in_piece;            /* the iterator is positioned inside sh->piece_lo[piece] */
    primesieve_iterator it;
    uint64_t p, i;           /* prime being marked (0: none) and its next bit */
    uint32_t *slots;         /* R * cap offsets */
    uint32_t *fill;          /* R counters */
    int exhausted, err;
} bucket_thread;

struct bucket_shared {
    const uint64_t *piece_lo, *piece_hi;
    uint64_t n_pieces, n_threads;
    phase_ctx phase;
    uint64_t n_bits;
    unsigned shift;
    uint64_t n_regions, cap;
    unsigned char *out;
    uint64_t *pieces_done;
    uint64_t next_piece;         /* first unclaimed piece */
    int round_over;
    pthread_barrier_t barrier;
    bucket_thread *threads;
    pthread_mutex_t gate_lock;   /* threads start once the caller has fixed n_threads */
    pthread_cond_t gate_cond;
    int gate_open;
};

static void bucket_scatter(bucket_shared *sh, bucket_thread *th) {
    const unsigned shift = sh->shift;
    const uint64_t mask = (1ull << shift) - 1, cap = sh->cap, n_bits = sh->n_bits;
    const uint64_t span = 2 * n_bits;
    const phase_ctx ph = sh->phase;
    uint32_t *const slots = th->slots, *const fill = th->fill;
    primesieve_iterator *const it = &th->it;
    uint64_t p = th->p, i = th->i;
    th->p = 0;
    for (;;) {
        if (p) {
            if (__atomic_load_n(&sh->round_over, __ATOMIC_RELAXED)) {
                th->p = p;
                th->i = i;
                return;
            }
            for (; i < n_bits; i += p) {
                uint64_t r = i >> shift;
                uint32_t f = fill[r];
                if (f == cap) {
                    th->p = p;
                    th->i = i;
                    __atomic_store_n(&sh->round_over, 1, __ATOMIC_RELAXED);
                    return;
                }
                slots[r * cap + f] = (uint32_t)(i & mask);
                fill[r] = f + 1;
            }
            p = 0;
        }
        if (!th->in_piece) {
            if (__atomic_load_n(&sh->round_over, __ATOMIC_RELAXED)) return;
            th->piece = __atomic_fetch_add(&sh->next_piece, 1, __ATOMIC_RELAXED);
            if (th->piece >= sh->n_pieces) {
                th->exhausted = 1;
                return;
            }
            /* Starting at 3 or above keeps 2 out of the per-prime loop below. */
            uint64_t start = sh->piece_lo[th->piece];
            primesieve_jump_to(it, start < 3 ? 3 : start, sh->piece_hi[th->piece]);
            th->in_piece = 1;
        }
        /* The loop reads the iterator's buffer directly, as primesieve_next_prime() does:
         * primes[it->i] is the current prime, primes[it->i + 1 .. size) the next ones, and
         * after primesieve_generate_next_primes() the next prime is primes[it->i]. On an error
         * the buffer holds PRIMESIEVE_ERROR (UINT64_MAX), which ends the loop like the end of
         * the piece does. */
        const uint64_t hi = sh->piece_hi[th->piece];
        size_t j = it->i + 1;
        for (;;) {
            if (j >= it->size) {
                primesieve_generate_next_primes(it);
                j = it->i;
            }
            const uint64_t *const primes = it->primes;
            const size_t n = it->size;
            for (; j < n; j++) {
                uint64_t q = primes[j];
                if (__builtin_expect(q >= hi, 0)) goto piece_end;
                /* The first multiple at offset k >= span (2 * n_bits numbers) puts the first
                 * odd one, k or k + p, past the buffer too: one compare rejects most
                 * deep-floor primes. */
                uint64_t k = first_multiple_offset(&ph, q);
                if (__builtin_expect(k >= span, 1)) continue;
                uint64_t b = skip_self(&ph, odd_multiple_bit(k, q), q);
                if (b < n_bits) {
                    it->i = j;
                    p = q;
                    i = b;
                    goto next_prime;
                }
            }
        }
    piece_end:
        it->i = j;
        if (it->is_error) {
            th->err = 1;
            th->exhausted = 1;
            return;
        }
        th->in_piece = 0;
        __atomic_fetch_add(sh->pieces_done, 1, __ATOMIC_RELAXED);
    next_prime:;
    }
}

static void bucket_apply(bucket_shared *sh, uint64_t t) {
    uint64_t r0 = sh->n_regions * t / sh->n_threads, r1 = sh->n_regions * (t + 1) / sh->n_threads;
    for (uint64_t r = r0; r < r1; r++) {
        uint64_t base = r << sh->shift;
        for (uint64_t s = 0; s < sh->n_threads; s++) {
            const bucket_thread *src = &sh->threads[s];
            const uint32_t *b = src->slots + r * sh->cap;
            uint32_t n = src->fill[r];
            for (uint32_t k = 0; k < n; k++) {
                uint64_t bit = base + b[k];
                sh->out[bit >> 3] |= (unsigned char)(1u << (bit & 7));
            }
        }
    }
}

static void *bucket_worker(void *arg) {
    bucket_thread *th = (bucket_thread *)arg;
    bucket_shared *sh = th->sh;
    pthread_mutex_lock(&sh->gate_lock);
    while (!sh->gate_open) pthread_cond_wait(&sh->gate_cond, &sh->gate_lock);
    pthread_mutex_unlock(&sh->gate_lock);
    if (th->index >= sh->n_threads) return NULL;
    for (;;) {
        if (!th->exhausted) bucket_scatter(sh, th);
        pthread_barrier_wait(&sh->barrier);
        /* Between the barriers nobody scatters: round_over and every exhausted flag are
         * stable, so all threads reach the same verdict on `all_done`. */
        if (th->index == 0) __atomic_store_n(&sh->round_over, 0, __ATOMIC_RELAXED);
        int all_done = 1;
        for (uint64_t s = 0; s < sh->n_threads; s++)
            if (!sh->threads[s].exhausted) all_done = 0;
        bucket_apply(sh, th->index);
        pthread_barrier_wait(&sh->barrier);
        memset(th->fill, 0, sh->n_regions * sizeof(uint32_t));
        if (all_done) return NULL;
    }
}

int sieve_odd_bucketed(const uint64_t *piece_lo, const uint64_t *piece_hi, uint64_t n_pieces,
                       uint64_t first_odd_hi, uint64_t first_odd_lo, uint64_t n_bits,
                       uint64_t region_bits, uint64_t n_threads, uint64_t bucket_bytes,
                       unsigned char *out_bits, uint64_t *pieces_done) {
    if (n_pieces == 0 || n_bits == 0) return 0;
    if (n_threads == 0) n_threads = 1;
    if (n_threads > n_pieces) n_threads = n_pieces;

    bucket_shared sh;
    memset(&sh, 0, sizeof(sh));
    sh.piece_lo = piece_lo;
    sh.piece_hi = piece_hi;
    sh.n_pieces = n_pieces;
    sh.n_threads = n_threads;
    phase_init(&sh.phase, ((u128)first_odd_hi << 64) | (u128)first_odd_lo);
    sh.n_bits = n_bits;
    sh.shift = 6;
    while (sh.shift < 32 && (2ull << sh.shift) <= region_bits) sh.shift++;
    sh.n_regions = ((n_bits - 1) >> sh.shift) + 1;
    sh.cap = bucket_bytes / sizeof(uint32_t) / n_threads / sh.n_regions;
    if (sh.cap < MIN_BUCKET_SLOTS) sh.cap = MIN_BUCKET_SLOTS;
    sh.out = out_bits;
    sh.pieces_done = pieces_done;

    int rc = 0;
    uint64_t made = 0;
    pthread_t *tids = (pthread_t *)calloc(n_threads, sizeof(pthread_t));
    sh.threads = (bucket_thread *)calloc(n_threads, sizeof(bucket_thread));
    if (!tids || !sh.threads) {
        free(tids);
        free(sh.threads);
        return -1;
    }
    for (uint64_t t = 0; t < n_threads; t++) {
        bucket_thread *th = &sh.threads[t];
        th->sh = &sh;
        th->index = t;
        primesieve_init(&th->it);
        th->slots = (uint32_t *)malloc(sh.n_regions * sh.cap * sizeof(uint32_t));
        th->fill = (uint32_t *)calloc(sh.n_regions, sizeof(uint32_t));
        if (!th->slots || !th->fill) rc = -1;
    }
    pthread_mutex_init(&sh.gate_lock, NULL);
    pthread_cond_init(&sh.gate_cond, NULL);
    if (rc == 0) {
        for (; made < n_threads; made++)
            if (pthread_create(&tids[made], NULL, bucket_worker, &sh.threads[made]) != 0) break;
        /* Fewer threads than asked: the started ones claim all pieces between them. */
        uint64_t run = made;
        if (run == 0 || pthread_barrier_init(&sh.barrier, NULL, (unsigned)run) != 0) {
            rc = -1;
            run = 0;
        }
        pthread_mutex_lock(&sh.gate_lock);
        sh.n_threads = run;   /* run == 0: every started thread returns at the gate */
        sh.gate_open = 1;
        pthread_cond_broadcast(&sh.gate_cond);
        pthread_mutex_unlock(&sh.gate_lock);
        for (uint64_t t = 0; t < made; t++) pthread_join(tids[t], NULL);
        if (run) pthread_barrier_destroy(&sh.barrier);
    }
    pthread_mutex_destroy(&sh.gate_lock);
    pthread_cond_destroy(&sh.gate_cond);
    for (uint64_t t = 0; t < n_threads; t++) {
        bucket_thread *th = &sh.threads[t];
        if (th->err) rc = -1;
        primesieve_free_iterator(&th->it);
        free(th->slots);
        free(th->fill);
    }
    free(sh.threads);
    free(tids);
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
