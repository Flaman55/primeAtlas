/* engine_pt_core.h -- the core shared by engines pt1 and pt2 (included by their C files).
 *
 * Montgomery arithmetic with R = 2^128 for odd n < 2^127 (sums of two residues stay below
 * 2^128), the strong probable prime tests (13 bases 2..41, deterministic below 3.317e24 by
 * Sorenson-Webster; BPSW = base 2 + strong Lucas with Selfridge's method A), and the partial
 * sieve of a slab: the odd numbers are cut into chunks, each thread claims chunks one at a
 * time, marks the multiples of the sieving primes 3..B in a byte-per-odd-number flag array and
 * hands every survivor to the engine's test. The result is packed into out_bits, bit i (LSB
 * first) = 1 when first_odd + 2*i is composite, the convention of prime_sieve_engine_v5.c's
 * buffer.
 *
 * PRECONDITION: every number of the slab is larger than B and than the test's largest base,
 * so no sieving prime or base is a member of the slab.
 */
#ifndef ENGINE_PT_CORE_H
#define ENGINE_PT_CORE_H

#include <math.h>
#include <primesieve.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned __int128 u128;
typedef uint64_t u64;
typedef uint32_t u32;

/* ---- Montgomery arithmetic, R = 2^128, odd n < 2^127 ---- */
typedef struct { u128 n, ninv, one, r2; } mont;

static inline void mul256(u128 a, u128 b, u128 *hi, u128 *lo) {
    u64 a0 = (u64)a, a1 = (u64)(a >> 64), b0 = (u64)b, b1 = (u64)(b >> 64);
    u128 p00 = (u128)a0 * b0, p01 = (u128)a0 * b1, p10 = (u128)a1 * b0, p11 = (u128)a1 * b1;
    u128 mid = (p00 >> 64) + (u64)p01 + (u64)p10;
    *lo = (u64)p00 | (mid << 64);
    *hi = p11 + (p01 >> 64) + (p10 >> 64) + (mid >> 64);
}

/* a * b / R mod n for a, b < n */
static inline u128 mmul(const mont *m, u128 a, u128 b) {
    u128 hi, lo, mh, ml;
    mul256(a, b, &hi, &lo);
    u128 q = lo * m->ninv;
    mul256(q, m->n, &mh, &ml);
    u128 t = hi + mh + (lo != 0);
    return t >= m->n ? t - m->n : t;
}

static inline u128 madd(const mont *m, u128 a, u128 b) { u128 t = a + b; return t >= m->n ? t - m->n : t; }
static inline u128 msub(const mont *m, u128 a, u128 b) { return a >= b ? a - b : a + m->n - b; }
static inline u128 mhalf(const mont *m, u128 a) { return (a & 1) ? (a + m->n) >> 1 : a >> 1; }

static inline void mont_init(mont *m, u128 n) {
    m->n = n;
    u128 x = n;                      /* n * n = 1 mod 8: 3 correct bits, doubled per step */
    for (int i = 0; i < 7; i++) x *= 2 - n * x;
    m->ninv = -x;                    /* -n^-1 mod R */
    m->one = (-n) % n;               /* R mod n */
    u128 r = m->one;
    for (int i = 0; i < 128; i++) r = madd(m, r, r);
    m->r2 = r;                       /* R^2 mod n */
}

static inline u128 to_mont(const mont *m, u128 a) { return mmul(m, a % m->n, m->r2); }

static inline int bit_length(u128 x) {
    u64 h = (u64)(x >> 64);
    return h ? 128 - __builtin_clzll(h) : 64 - __builtin_clzll((u64)x);
}

/* strong probable prime to base a (Montgomery form am), n - 1 = d * 2^s */
static inline int sprp(const mont *m, u128 am, u128 d, int s) {
    u128 x = am;
    for (int i = bit_length(d) - 2; i >= 0; i--) {
        x = mmul(m, x, x);
        if ((d >> i) & 1) x = mmul(m, x, am);
    }
    u128 mone = m->n - m->one;
    if (x == m->one || x == mone) return 1;
    for (int r = 1; r < s; r++) {
        x = mmul(m, x, x);
        if (x == mone) return 1;
    }
    return 0;
}

/* base 2: multiplying by 2 is a doubling */
static inline int sprp2(const mont *m, u128 d, int s) {
    u128 x = madd(m, m->one, m->one);
    for (int i = bit_length(d) - 2; i >= 0; i--) {
        x = mmul(m, x, x);
        if ((d >> i) & 1) x = madd(m, x, x);
    }
    u128 mone = m->n - m->one;
    if (x == m->one || x == mone) return 1;
    for (int r = 1; r < s; r++) {
        x = mmul(m, x, x);
        if (x == mone) return 1;
    }
    return 0;
}

/* Jacobi symbol (a / n) for small a, odd n */
static inline int jacobi_small(long a, u128 n) {
    int t = 1;
    if (a < 0) { a = -a; if ((u64)(n & 3) == 3) t = -t; }
    u64 aa = (u64)a;
    while (!(aa & 1)) { aa >>= 1; u64 r = (u64)(n & 7); if (r == 3 || r == 5) t = -t; }
    if (aa == 1) return t;
    if ((aa & 3) == 3 && (u64)(n & 3) == 3) t = -t;   /* reciprocity: (aa / n) = +-(n / aa) */
    u64 x = (u64)(n % aa), y = aa;
    while (x) {
        while (!(x & 1)) { x >>= 1; u64 r = y & 7; if (r == 3 || r == 5) t = -t; }
        u64 tmp = x; x = y; y = tmp;
        if ((x & 3) == 3 && (y & 3) == 3) t = -t;
        x %= y;
    }
    return y == 1 ? t : 0;
}

static inline int is_square(u128 n) {
    u128 r = (u128)sqrtl((long double)n);
    while (r * r > n) r--;
    while ((r + 1) * (r + 1) <= n) r++;
    return r * r == n;
}

static inline int strong_lucas(const mont *m) {
    u128 n = m->n;
    long D = 5;
    for (int k = 0;; k++) {
        int j = jacobi_small(D, n);
        if (j == -1) break;
        if (j == 0) return 0;            /* n > |D| shares a factor with D */
        D = D > 0 ? -(D + 2) : -D + 2;
        if (k == 20 && is_square(n)) return 0;
    }
    long Q = (1 - D) / 4;
    u128 Dm = D > 0 ? to_mont(m, (u128)D) : msub(m, 0, to_mont(m, (u128)(-D)));
    u128 Qm = Q > 0 ? to_mont(m, (u128)Q) : msub(m, 0, to_mont(m, (u128)(-Q)));
    u128 d = n + 1;
    int s = 0;
    while (!(d & 1)) { d >>= 1; s++; }
    u128 U = m->one, V = m->one, Qk = Qm;   /* index 1, P = 1 */
    for (int i = bit_length(d) - 2; i >= 0; i--) {
        U = mmul(m, U, V);                                    /* U_2k = U_k V_k */
        V = msub(m, mmul(m, V, V), madd(m, Qk, Qk));          /* V_2k = V_k^2 - 2 Q^k */
        Qk = mmul(m, Qk, Qk);
        if ((d >> i) & 1) {                                   /* index + 1 */
            u128 nu = mhalf(m, madd(m, U, V));                /* (P U + V) / 2 */
            V = mhalf(m, madd(m, mmul(m, Dm, U), V));         /* (D U + P V) / 2 */
            U = nu;
            Qk = mmul(m, Qk, Qm);
        }
    }
    if (U == 0 || V == 0) return 1;
    for (int r = 1; r < s; r++) {
        V = msub(m, mmul(m, V, V), madd(m, Qk, Qk));
        if (V == 0) return 1;
        Qk = mmul(m, Qk, Qk);
    }
    return 0;
}

static const u32 DET_BASES[13] = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41};

static inline int is_prime_det(u128 n) {
    mont m;
    mont_init(&m, n);
    u128 d = n - 1;
    int s = 0;
    while (!(d & 1)) { d >>= 1; s++; }
    if (!sprp2(&m, d, s)) return 0;
    for (int i = 1; i < 13; i++)
        if (!sprp(&m, to_mont(&m, DET_BASES[i]), d, s)) return 0;
    return 1;
}

static inline int is_prime_bpsw(u128 n) {
    mont m;
    mont_init(&m, n);
    u128 d = n - 1;
    int s = 0;
    while (!(d & 1)) { d >>= 1; s++; }
    return sprp2(&m, d, s) && strong_lucas(&m);
}


/* ---- sieving primes ---- */
typedef struct { u32 *p; u64 n, b; } pt_ctx;  /* the primes 3..b */

/* sieving primes 3..b (b < 2^32); NULL on allocation failure */
static inline void *pt_ctx_new(u64 b) {
    pt_ctx *c = calloc(1, sizeof *c);
    if (!c) return NULL;
    c->b = b;
    if (b < 3) return c;
    size_t n = 0;
    u32 *p = (u32 *)primesieve_generate_primes(3, b, &n, UINT32_PRIMES);
    if (!p) { free(c); return NULL; }
    c->p = p;
    c->n = n;
    return c;
}

static inline u64 pt_ctx_count(void *ctx) { return ((pt_ctx *)ctx)->n; }

static inline void pt_ctx_free(void *ctx) {
    pt_ctx *c = ctx;
    if (!c) return;
    if (c->p) primesieve_free(c->p);
    free(c);
}

/* ---- slab ---- */
/* 1: prime, 0: composite, < 0: the test cannot decide (the slab fails) */
typedef int (*pt_test_fn)(u128 n, const void *arg);

typedef struct {
    const pt_ctx *ctx;
    u128 first;
    u64 n_odd, chunk, n_chunks, next;
    pt_test_fn test;
    const void *arg;
    int error;
    unsigned char *out;
    volatile u64 *done;
} pt_job;

static inline void *pt_worker(void *arg) {
    pt_job *j = arg;
    unsigned char *flag = malloc(j->chunk);
    if (!flag) { __atomic_store_n(&j->error, 1, __ATOMIC_RELAXED); return NULL; }
    for (;;) {
        u64 c = __atomic_fetch_add(&j->next, 1, __ATOMIC_RELAXED);
        if (c >= j->n_chunks) break;
        u64 lo = c * j->chunk, len = j->n_odd - lo < j->chunk ? j->n_odd - lo : j->chunk;
        u128 base = j->first + 2 * (u128)lo;       /* odd; flag[i] stands for base + 2i */
        memset(flag, 0, len);
        for (u64 k = 0; k < j->ctx->n; k++) {
            u64 p = j->ctx->p[k];
            u64 r = (u64)(base % p);
            u64 off = r ? p - r : 0;               /* base + off is a multiple of p */
            if (off & 1) off += p;                 /* first odd multiple */
            for (u64 i = off >> 1; i < len; i += p) flag[i] = 1;
        }
        for (u64 i = 0; i < len; i++) {
            if (flag[i]) continue;
            int t = j->test(base + 2 * (u128)i, j->arg);
            if (t < 0) __atomic_store_n(&j->error, 1, __ATOMIC_RELAXED);
            if (t != 1) flag[i] = 1;
        }
        unsigned char *dst = j->out + lo / 8;      /* chunk is a multiple of 8 */
        for (u64 b = 0; b < len; b += 8) {
            unsigned char v = 0;
            u64 e = len - b < 8 ? len - b : 8;
            for (u64 t = 0; t < e; t++) v |= (unsigned char)(flag[b + t] << t);
            dst[b / 8] = v;
        }
        __atomic_fetch_add(j->done, 1, __ATOMIC_RELAXED);
    }
    free(flag);
    return NULL;
}

/* Composite bitmap of the n_odd odd numbers from first_odd (u128 as hi/lo halves) into
 * out_bits ((n_odd + 7) / 8 bytes), every survivor of the sieve decided by test(n, arg).
 * chunk_odd is rounded up to a multiple of 8; *chunks_done counts finished chunks for
 * progress. Returns 0, or -1 on bad arguments, allocation failure or an undecided test. */
static inline int pt_sieve_odd(void *ctx, u64 first_hi, u64 first_lo, u64 n_odd, pt_test_fn test,
                        const void *arg, u64 n_threads, u64 chunk_odd, unsigned char *out_bits,
                        volatile u64 *chunks_done) {
    if (!ctx || !(first_lo & 1) || (first_hi >> 63) || n_threads < 1 || chunk_odd < 1) return -1;
    pt_job j;
    memset(&j, 0, sizeof j);
    j.ctx = ctx;
    j.first = ((u128)first_hi << 64) | first_lo;
    j.n_odd = n_odd;
    j.chunk = (chunk_odd + 7) / 8 * 8;
    j.n_chunks = (n_odd + j.chunk - 1) / j.chunk;
    j.test = test;
    j.arg = arg;
    j.out = out_bits;
    j.done = chunks_done;
    if (n_threads > j.n_chunks) n_threads = j.n_chunks ? j.n_chunks : 1;
    pthread_t *th = malloc(sizeof *th * n_threads);
    if (!th) return -1;
    u64 started = 0;
    for (; started < n_threads; started++)
        if (pthread_create(&th[started], NULL, pt_worker, &j)) break;
    if (!started) { free(th); return -1; }
    for (u64 i = 0; i < started; i++) pthread_join(th[i], NULL);
    free(th);
    return j.error ? -1 : 0;
}

#endif
