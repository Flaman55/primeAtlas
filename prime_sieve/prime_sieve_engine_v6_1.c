/* ==========================================================================================
 * prime_sieve_engine_v6_1.c -- sieve-generation core, v6.1.
 *
 * Loaded by prime_sieve_v6_1.py. v6.0's engine (prime_sieve_engine_v6.c) with two changes,
 * output bit for bit the same:
 *   - the segmented path marks a prime's multiples a whole wheel turn at a time: one turn
 *     (30p numbers) moves each of its 8 marks by exactly p bytes and keeps its bit, so the
 *     8 byte offsets and masks are computed once per prime and segment and the loop does 8
 *     byte ORs per turn, with no division per mark (primes below a segment's numbers / 32;
 *     the larger ones, with few marks per segment, keep v6.0's mark-by-mark loop);
 *   - the bucketed path stages each region's hits in one 64-byte line (16 slots) and writes
 *     a full line to the region's slots with non-temporal stores, so the slots are not read
 *     into the cache before they are overwritten (a round end copies the partial lines).
 * Measured on 24 threads, count-only, 4096 MiB buckets: floor 19, 1e11 numbers, sieve
 * 15.4-18.5 s -> 13.2-14.2 s; floor 25, 2e11 numbers, 147-155 s -> 134-141 s.
 *
 * The rest is v6.0's: the buffer below is the same wheel-30 bitmap, built the same way. The shared output buffer is a wheel-30 bitmap (layout in
 * wheel30_layout.py): byte b covers the numbers [base + 30*b, base + 30*b + 30), base a
 * multiple of 30, and its bit j stands for base + 30*b + RESIDUES[j], the eight residues
 * coprime to 30. A set bit means composite. 8 bits per 30 numbers, against 15 in v5's
 * odd-only buffer, so the same memory holds a run 1.875 times as long; every run pays the
 * generation of all sieving primes below sqrt(top) once, so a longer run spreads that cost
 * over more numbers. 2, 3 and 5 have no bit and are never sieved.
 *
 * A sieving prime p >= 7 marks the multiples p*k whose cofactor k is coprime to 30 (the
 * others have no bit), k > 1. Its state is (x, w): x is the next multiple's offset from the
 * dividend the phase was computed for, w the index of k mod 30 in RESIDUES; the next
 * multiple is x + GAP[w] * p. The phase (first mod p) is computed as in v5: a double-precision
 * quotient corrected by one p, or an exact division where the double path does not apply.
 *
 * sieve_wheel_segmented() marks the small sieving primes inside one slice of the buffer,
 * segment by segment in a private cache-sized word array, with a presieve pattern for
 * 7, 11, 13 and 17; each finished segment is ORed into the shared buffer one 64-bit word at a
 * time (lock-prefixed: slices run in parallel worker processes).
 *
 * sieve_wheel_bucketed() marks the primes from work_plan_v6.small_prime_stop() up with the
 * bucket scheme of v5 (threads append each hit's bit offset to a per-region bucket and apply
 * the buckets region by region while the region is cache resident).
 *
 * count_sieving_primes() / count_sieving_primes_range() are the same as in v5.
 *
 * wheel_window_gaps() turns one window of the finished buffer into the PGS2 gap stream:
 * the unmarked bits in ascending order become offsets from the window start, the first one
 * is returned apart and the gaps between consecutive ones are LEB128 varints. It reads the
 * buffer only, so writer threads call it in parallel (ctypes releases the GIL).
 *
 * BUILD (WSL, after building+installing libprimesieve):
 *   gcc -O3 -shared -fPIC prime_sieve_engine_v6_1.c -o prime_sieve_engine_v6_1.so \
 *       -lprimesieve -lstdc++ -lm
 * ========================================================================================== */

#include <primesieve.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <emmintrin.h>

typedef unsigned __int128 u128;

/* ------------------------------------------------------------------------------------------
 * Phase: first mod p, exactly (same arithmetic as prime_sieve_engine_v5.c, see its header).
 * ------------------------------------------------------------------------------------------ */
static inline uint64_t udiv128_rem(uint64_t hi, uint64_t lo, uint64_t divisor) {
    uint64_t quot, rem;
    __asm__("divq %[divisor]"
            : "=a"(quot), "=d"(rem)
            : "a"(lo), "d"(hi), [divisor] "rm"(divisor));
    (void)quot;
    return rem;
}

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
    if (c->hi < p_val) return udiv128_rem(c->hi, c->lo, p_val);
    return (uint64_t)(c->first % (u128)p_val);
}

/* ------------------------------------------------------------------------------------------
 * Wheel tables. RESIDUES[j] is bit j's residue; BIT_OF[r] the bit of residue r (0xFF where r
 * shares a factor with 30); GAP[w] = RESIDUES[w + 1] - RESIDUES[w] (cyclic, 29 -> 31);
 * ADVANCE[r] the distance from r to the next residue coprime to 30 (0 when r is one);
 * INV30[r] the inverse of r mod 30 for r coprime to 30.
 * ------------------------------------------------------------------------------------------ */
static const uint8_t RESIDUES[8] = {1, 7, 11, 13, 17, 19, 23, 29};
static const uint8_t GAP[8] = {6, 4, 2, 4, 2, 4, 6, 2};
static const uint8_t BIT_OF[30] = {
    0xFF, 0, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 1, 0xFF, 0xFF, 0xFF, 2, 0xFF, 3, 0xFF,
    0xFF, 0xFF, 4, 0xFF, 5, 0xFF, 0xFF, 0xFF, 6, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 7};
static const uint8_t ADVANCE[30] = {
    1, 0, 5, 4, 3, 2, 1, 0, 3, 2, 1, 0, 1, 0, 3, 2, 1, 0, 1, 0, 3, 2, 1, 0, 5, 4, 3, 2, 1, 0};
static const uint8_t INV30[30] = {
    0, 1, 0, 0, 0, 0, 0, 13, 0, 0, 0, 11, 0, 7, 0, 0, 0, 23, 0, 19, 0, 0, 0, 17, 0, 0, 0, 0, 0,
    29};

/* ------------------------------------------------------------------------------------------
 * first_wheel_multiple -- for the dividend c->first (a multiple of 30) and a prime p >= 7:
 * the offset x from c->first of the smallest multiple p*k >= c->first with k coprime to 30
 * and k > 1, and w = the index of k mod 30 in RESIDUES. Returns x; the caller compares it
 * with its span before using w. x can exceed 2^64 only when the span is irrelevant
 * (x >= p * 7 > every span); it is then clamped to UINT64_MAX.
 * ------------------------------------------------------------------------------------------ */
static inline uint64_t first_wheel_multiple(const phase_ctx *c, uint64_t p, unsigned *w_out) {
    uint64_t rem = phase_rem(c, p);
    uint64_t x = rem ? p - rem : 0;
    /* first + x = p*k; first = 0 mod 30, so k = x * p^-1 (mod 30). */
    unsigned k = (unsigned)((x % 30) * INV30[p % 30] % 30);
    unsigned d = ADVANCE[k];
    u128 xx = (u128)x + (u128)d * p;
    k = (k + d) % 30;
    if (c->first + xx == (u128)p) {   /* k == 1: p itself, never marked; next k is 7 */
        xx += (u128)6 * p;
        k = 7;
    }
    *w_out = BIT_OF[k];
    return (xx >> 64) ? UINT64_MAX : (uint64_t)xx;
}

/* Bit index (8 * byte + bit) of the number at offset x from a multiple of 30. */
static inline uint64_t wheel_bit(uint64_t x) {
    uint64_t b = x / 30;
    return (b << 3) | BIT_OF[x - 30 * b];
}

uint64_t wheel_first_marked(uint64_t first_hi, uint64_t first_lo, uint64_t p_val,
                            uint64_t *w_out) {
    phase_ctx c;
    phase_init(&c, ((u128)first_hi << 64) | (u128)first_lo);
    unsigned w;
    uint64_t x = first_wheel_multiple(&c, p_val, &w);
    *w_out = w;
    return x;
}

/* ------------------------------------------------------------------------------------------
 * sieve_wheel_segmented -- marks the composites of bits [bit_lo, bit_hi) of the shared
 * wheel buffer (whose byte 0 starts at base, see the header) that have a prime factor in
 * [7, stop). bit_lo must be a multiple of 64, so the slice owns whole 64-bit words of
 * out_words except where bit_hi cuts the last one; that word is masked to the slice.
 *
 * The slice is processed in segments of segment_words 64-bit words in a private array:
 *   - presieve: PRESIEVE_PRIMES (7..17) repeat every PRESIEVE_WORDS words (their product in
 *     bytes, times 8 bytes per word), so a pattern built once per slice is copied word by
 *     word; a presieve prime that lies inside the segment is cleared again afterwards;
 *   - primes FIRST_SEGMENTED_PRIME..stop-1 keep their (x, w) across segments;
 *   - the segment is ORed into out_words with one atomic 64-bit OR per nonzero word.
 * Returns 0, -1 on a primesieve or allocation failure, -2 when bit_lo is not word aligned.
 * ------------------------------------------------------------------------------------------ */
#define PRESIEVE_WORDS 17017u   /* 7 * 11 * 13 * 17 bytes repeat; 8 repeats fill whole words */
static const uint64_t PRESIEVE_PRIMES[] = {7, 11, 13, 17};
#define N_PRESIEVE_PRIMES (sizeof(PRESIEVE_PRIMES) / sizeof(PRESIEVE_PRIMES[0]))
#define FIRST_SEGMENTED_PRIME 19

int sieve_wheel_segmented(uint64_t stop, uint64_t base_hi, uint64_t base_lo, uint64_t bit_lo,
                          uint64_t bit_hi, uint64_t segment_words, uint64_t *out_words) {
    if (bit_lo >= bit_hi) return 0;
    if (bit_lo & 63) return -2;
    if (segment_words == 0) segment_words = 1;

    /* The slice starts at byte bit_lo / 8, i.e. at number first (a multiple of 30). */
    u128 first = (((u128)base_hi << 64) | (u128)base_lo) + (u128)30 * (bit_lo >> 3);
    phase_ctx ph;
    phase_init(&ph, first);
    uint64_t n = bit_hi - bit_lo;
    uint64_t *out = out_words + (bit_lo >> 6);
    uint64_t span = 30 * ((n + 7) >> 3);   /* numbers covered by the slice's bytes */

    size_t n_primes = 0;
    uint64_t *primes = NULL;
    if (stop > FIRST_SEGMENTED_PRIME) {
        primes = (uint64_t *)primesieve_generate_primes(FIRST_SEGMENTED_PRIME, stop - 1,
                                                        &n_primes, UINT64_PRIMES);
        if (!primes) return -1;
    }
    size_t cnt = n_primes ? n_primes : 1;
    uint64_t *next = (uint64_t *)malloc(cnt * sizeof(uint64_t));
    uint8_t *wheel = (uint8_t *)malloc(cnt);
    uint64_t *pattern = (uint64_t *)calloc(PRESIEVE_WORDS, sizeof(uint64_t));
    uint64_t *seg = (uint64_t *)malloc(segment_words * sizeof(uint64_t));
    int rc = 0;
    if (!next || !wheel || !pattern || !seg) {
        rc = -1;
        goto done;
    }

    for (size_t k = 0; k < n_primes; k++) {
        unsigned w;
        next[k] = first_wheel_multiple(&ph, primes[k], &w);
        wheel[k] = (uint8_t)w;
    }

    for (size_t t = 0; t < N_PRESIEVE_PRIMES; t++) {
        uint64_t q = PRESIEVE_PRIMES[t];
        unsigned w;
        uint64_t limit = (uint64_t)PRESIEVE_WORDS * 64 / 8 * 30;   /* numbers in the pattern */
        /* The pattern marks every multiple q*k (k coprime to 30) including q itself; q is
         * cleared per segment below where it lies inside the range. */
        uint64_t rem = phase_rem(&ph, q);
        uint64_t x = rem ? q - rem : 0;
        unsigned k = (unsigned)((x % 30) * INV30[q % 30] % 30);
        x += ADVANCE[k] * q;
        k = (k + ADVANCE[k]) % 30;
        for (w = BIT_OF[k]; x < limit; x += GAP[w] * q, w = (w + 1) & 7) {
            uint64_t b = wheel_bit(x);
            pattern[b >> 6] |= 1ull << (b & 63);
        }
    }

    uint64_t seg_bits = segment_words * 64;
    /* Primes below a segment's numbers / 32 have at least 8 wheel turns in a segment and mark
     * them with the unrolled loop; on floor 19, limits from 1/128 to 1/8 of the segment's
     * numbers measured within 5 % of each other. */
    const uint64_t unroll_max = seg_bits / 8 * 30 / 32;
    for (uint64_t s = 0; s < n; s += seg_bits) {
        uint64_t e = (n - s < seg_bits) ? n : s + seg_bits;
        uint64_t nw = (e - s + 63) >> 6;
        uint64_t x_end = 30 * ((e + 7) >> 3);   /* first offset past the segment's bytes */
        if (x_end > span) x_end = span;

        uint64_t pw = (s >> 6) % PRESIEVE_WORDS;
        for (uint64_t w = 0; w < nw; w++) {
            seg[w] = pattern[pw];
            if (++pw == PRESIEVE_WORDS) pw = 0;
        }
        for (size_t t = 0; t < N_PRESIEVE_PRIMES; t++) {
            u128 q = PRESIEVE_PRIMES[t];
            if (q < first || q - first >= span) continue;
            uint64_t idx = wheel_bit((uint64_t)(q - first));
            if (idx >= s && idx < e) seg[(idx - s) >> 6] &= ~(1ull << ((idx - s) & 63));
        }

        uint8_t *seg8 = (uint8_t *)seg;
        const uint64_t s_byte = s >> 3;
        const uint64_t seg_bytes = ((e + 7) >> 3) - s_byte;
        for (size_t k = 0; k < n_primes; k++) {
            uint64_t p = primes[k], x = next[k];
            unsigned w = wheel[k];
            if (p < unroll_max && x < x_end) {
                /* One wheel turn of p (30p numbers, k -> k + 30) moves every mark by exactly
                 * p bytes and keeps its bit: the 8 marks from (x, w) on are 8 fixed byte
                 * offsets and masks, repeated every p bytes. */
                uint64_t xb = x / 30;
                unsigned xr = (unsigned)(x - 30 * xb);
                uint64_t off[8];
                uint8_t m[8];
                uint64_t d = 0;
                unsigned ww = w;
                for (unsigned j = 0; j < 8; j++) {
                    uint64_t t = xr + d;
                    off[j] = t / 30;
                    m[j] = (uint8_t)(1u << BIT_OF[t % 30]);
                    d += GAP[ww] * p;
                    ww = (ww + 1) & 7;
                }
                uint64_t i = xb - s_byte;
                const uint64_t o1 = off[1], o2 = off[2], o3 = off[3], o4 = off[4], o5 = off[5],
                               o6 = off[6], o7 = off[7];
                const uint8_t m0 = m[0], m1 = m[1], m2 = m[2], m3 = m[3], m4 = m[4], m5 = m[5],
                              m6 = m[6], m7 = m[7];
                while (i + o7 < seg_bytes) {
                    uint8_t *const bp = seg8 + i;
                    bp[0] |= m0;
                    bp[o1] |= m1;
                    bp[o2] |= m2;
                    bp[o3] |= m3;
                    bp[o4] |= m4;
                    bp[o5] |= m5;
                    bp[o6] |= m6;
                    bp[o7] |= m7;
                    i += p;
                }
                x = (i + s_byte) * 30 + xr;
            }
            while (x < x_end) {
                uint64_t r = wheel_bit(x) - s;
                seg[r >> 6] |= 1ull << (r & 63);
                x += GAP[w] * p;
                w = (w + 1) & 7;
            }
            next[k] = x;
            wheel[k] = (uint8_t)w;
        }

        if ((e - s) & 63) seg[nw - 1] &= (1ull << ((e - s) & 63)) - 1;
        uint64_t *dst = out + (s >> 6);
        for (uint64_t w = 0; w < nw; w++)
            if (seg[w]) __atomic_fetch_or(&dst[w], seg[w], __ATOMIC_RELAXED);
    }

done:
    free(seg);
    free(pattern);
    free(wheel);
    free(next);
    if (primes) primesieve_free(primes);
    return rc;
}

/* ------------------------------------------------------------------------------------------
 * sieve_wheel_bucketed -- marks the composites of the whole wheel buffer (n_bits bits, byte 0
 * at base) that have a prime factor in one of the pieces [piece_lo[k], piece_hi[k]) of
 * sieving primes (all >= 7), with n_threads threads. Scheduling, regions, rounds and the
 * apply step are those of v5's sieve_odd_bucketed() (see prime_sieve_engine_v5.c); a hit is
 * stored as its wheel bit's offset within its region. Primes with p >= span (the numbers the
 * buffer covers) hit at most once, so their step is never added, and it cannot overflow.
 * PRECONDITION: no other writer touches out_bits during the call.
 * Returns 0, -1 on a primesieve, allocation or thread failure.
 * ------------------------------------------------------------------------------------------ */
#define MIN_BUCKET_SLOTS 16u

typedef struct bucket_shared bucket_shared;

typedef struct {
    bucket_shared *sh;
    uint64_t index;
    uint64_t piece;
    int in_piece;
    primesieve_iterator it;
    uint64_t p, x;           /* prime being marked (0: none), its next offset and wheel index */
    unsigned w;
    uint32_t *slots;
    uint32_t *fill;
    uint32_t *stage;         /* one 64-byte staging line (16 slots) per region */
    int exhausted, err;
} bucket_thread;

struct bucket_shared {
    const uint64_t *piece_lo, *piece_hi;
    uint64_t n_pieces, n_threads;
    phase_ctx phase;
    uint64_t n_bits, span;
    unsigned shift;
    uint64_t n_regions, cap;
    unsigned char *out;
    uint64_t *pieces_done;
    uint64_t next_piece;
    int round_over;
    pthread_barrier_t barrier;
    bucket_thread *threads;
    pthread_mutex_t gate_lock;
    pthread_cond_t gate_cond;
    int gate_open;
};

static void bucket_scatter(bucket_shared *sh, bucket_thread *th) {
    const unsigned shift = sh->shift;
    const uint64_t mask = (1ull << shift) - 1, cap = sh->cap, span = sh->span;
    const phase_ctx ph = sh->phase;
    uint32_t *const slots = th->slots, *const fill = th->fill, *const stage = th->stage;
    primesieve_iterator *const it = &th->it;
    uint64_t p = th->p, x = th->x;
    unsigned w = th->w;
    th->p = 0;
    for (;;) {
        if (p) {
            if (__atomic_load_n(&sh->round_over, __ATOMIC_RELAXED)) {
                th->p = p;
                th->x = x;
                th->w = w;
                return;
            }
            while (x < span) {
                uint64_t bit = wheel_bit(x);
                uint64_t r = bit >> shift;
                uint32_t f = fill[r];
                if (f == cap) {
                    th->p = p;
                    th->x = x;
                    th->w = w;
                    __atomic_store_n(&sh->round_over, 1, __ATOMIC_RELAXED);
                    return;
                }
                uint32_t *line = stage + (r << 4);
                line[f & 15] = (uint32_t)(bit & mask);
                if ((f & 15) == 15) {
                    __m128i *dst = (__m128i *)(slots + r * cap + (f & ~15u));
                    const __m128i *src = (const __m128i *)line;
                    _mm_stream_si128(dst, _mm_load_si128(src));
                    _mm_stream_si128(dst + 1, _mm_load_si128(src + 1));
                    _mm_stream_si128(dst + 2, _mm_load_si128(src + 2));
                    _mm_stream_si128(dst + 3, _mm_load_si128(src + 3));
                }
                fill[r] = f + 1;
                if (p >= span) break;
                x += GAP[w] * p;
                w = (w + 1) & 7;
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
            /* Starting at 7 or above keeps 2, 3 and 5 out of the per-prime loop below. */
            uint64_t start = sh->piece_lo[th->piece];
            primesieve_jump_to(it, start < 7 ? 7 : start, sh->piece_hi[th->piece]);
            th->in_piece = 1;
        }
        /* Reads the iterator's buffer directly, as in v5 (see prime_sieve_engine_v5.c). */
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
                /* The first multiple at offset >= span puts every wheel multiple past the
                 * buffer too: one compare rejects most deep-floor primes. */
                uint64_t rem = phase_rem(&ph, q);
                if (__builtin_expect((rem ? q - rem : 0) >= span, 1)) continue;
                unsigned qw;
                uint64_t qx = first_wheel_multiple(&ph, q, &qw);
                if (qx < span) {
                    it->i = j;
                    p = q;
                    x = qx;
                    w = qw;
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

/* Copies every region's partly filled staging line to its slots (round end). */
static void bucket_flush(bucket_shared *sh, bucket_thread *th) {
    for (uint64_t r = 0; r < sh->n_regions; r++) {
        uint32_t f = th->fill[r], n = f & 15u;
        if (n) memcpy(th->slots + r * sh->cap + (f & ~15u), th->stage + (r << 4), n * 4);
    }
    _mm_sfence();
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
        bucket_flush(sh, th);
        pthread_barrier_wait(&sh->barrier);
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

int sieve_wheel_bucketed(const uint64_t *piece_lo, const uint64_t *piece_hi, uint64_t n_pieces,
                         uint64_t base_hi, uint64_t base_lo, uint64_t n_bits,
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
    phase_init(&sh.phase, ((u128)base_hi << 64) | (u128)base_lo);
    sh.n_bits = n_bits;
    sh.span = 30 * ((n_bits + 7) >> 3);
    sh.shift = 6;
    while (sh.shift < 32 && (2ull << sh.shift) <= region_bits) sh.shift++;
    sh.n_regions = ((n_bits - 1) >> sh.shift) + 1;
    sh.cap = bucket_bytes / sizeof(uint32_t) / n_threads / sh.n_regions;
    if (sh.cap < MIN_BUCKET_SLOTS) sh.cap = MIN_BUCKET_SLOTS;
    sh.cap &= ~15u;   /* whole 64-byte lines per region */
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
        void *sp = NULL, *gp = NULL;
        if (posix_memalign(&sp, 64, sh.n_regions * sh.cap * sizeof(uint32_t)) != 0) sp = NULL;
        if (posix_memalign(&gp, 64, sh.n_regions * 64) != 0) gp = NULL;
        th->slots = (uint32_t *)sp;
        th->stage = (uint32_t *)gp;
        if (!th->stage) rc = -1;
        th->fill = (uint32_t *)calloc(sh.n_regions, sizeof(uint32_t));
        if (!th->slots || !th->fill) rc = -1;
    }
    pthread_mutex_init(&sh.gate_lock, NULL);
    pthread_cond_init(&sh.gate_cond, NULL);
    if (rc == 0) {
        for (; made < n_threads; made++)
            if (pthread_create(&tids[made], NULL, bucket_worker, &sh.threads[made]) != 0) break;
        uint64_t run = made;
        if (run == 0 || pthread_barrier_init(&sh.barrier, NULL, (unsigned)run) != 0) {
            rc = -1;
            run = 0;
        }
        pthread_mutex_lock(&sh.gate_lock);
        sh.n_threads = run;
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
        free(th->stage);
        free(th->fill);
    }
    free(sh.threads);
    free(tids);
    return rc;
}

uint64_t count_sieving_primes(uint64_t limit) {
    return primesieve_count_primes(0, limit);
}

uint64_t count_sieving_primes_range(uint64_t start, uint64_t stop) {
    return primesieve_count_primes(start, stop);
}

/* Window [lo, hi) of the buffer, given relative to its first byte b0: first_rel = base +
 * 30*b0 - lo (in -29..0), span = hi - lo, n_bytes the bytes covering the window. Writes the
 * varint gaps to out (capacity out_cap) and the count and first offset to *count_out and
 * *first_out (first: 0 when count is 0). Returns the bytes written, or -1 when out is too
 * small. 2, 3, 5 have no bit and 1 is never marked: the caller handles windows below 7. */
int64_t wheel_window_gaps(const uint8_t *buf, uint64_t n_bytes, int64_t first_rel, int64_t span,
                          uint8_t *out, uint64_t out_cap, uint64_t *count_out,
                          uint64_t *first_out) {
    uint64_t pos = 0, count = 0;
    int64_t prev = 0;
    *first_out = 0;
    for (uint64_t b = 0; b < n_bytes; b++) {
        unsigned free_bits = (unsigned)(uint8_t)~buf[b];
        int64_t byte_rel = first_rel + 30 * (int64_t)b;
        while (free_bits) {
            unsigned j = (unsigned)__builtin_ctz(free_bits);
            free_bits &= free_bits - 1;
            int64_t rel = byte_rel + RESIDUES[j];
            if (rel < 0 || rel >= span)
                continue;
            if (count == 0) {
                *first_out = (uint64_t)rel;
            } else {
                uint64_t gap = (uint64_t)(rel - prev);
                if (pos + 10 > out_cap)
                    return -1;
                while (gap >= 0x80) {
                    out[pos++] = (uint8_t)(gap | 0x80);
                    gap >>= 7;
                }
                out[pos++] = (uint8_t)gap;
            }
            prev = rel;
            count++;
        }
    }
    *count_out = count;
    return (int64_t)pos;
}
