/* ==========================================================================================
 * engine_jump_gear.h -- the jump gear of engines v7.0 and v7.2 (included by their C cores).
 *
 * For a buffer of span numbers starting at first (first > q^2 / q for every q used, q coprime
 * to 30, q >= 2 * span), a q has at most one multiple in [first, first + span), and it has
 * one exactly when frac(-first / q) < span / q. Instead of computing first mod q for every
 * sieving prime, the gear walks blocks q = Q + 30 j, j < J, of all numbers coprime to 30 in
 * one residue class mod 30 and finds only the j whose multiple lands in the buffer:
 *   - on a block, first / q ~ X0 - S j with X0 = first / Q and S = 30 first / Q^2, both in
 *     64.64 fixed point; the error first d^2 / (Q^2 (Q + d)), d = 30 j, is >= 0 and at most
 *     first d^2 / Q^3, and the truncations of X0 and S add less than 2 j + 1 units of 2^-64;
 *   - so every landing has v(j) = (A + B j) mod 2^64 < T, with B = S mod 2^64,
 *     A = -X0 + slack and T covering span / Q, the error and both slacks;
 *   - the first such j comes from a Euclid-like search (first_in), the next ones from the
 *     three-gap theorem: consecutive solutions of v < T differ by ga, gc or ga + gc;
 *   - each candidate is checked exactly (k = floor(x) + 1, k q - first corrected by one q),
 *     so a candidate that does not land costs one check and nothing else.
 * Composite q land too (about 7.5 times as many landings as prime q): their multiple is
 * composite and has a prime factor >= 7 below sqrt that marks it as well, so marking it again
 * changes no bit. The block length J = factor * Q * sqrt(span / (2 first)) / 30 keeps the
 * error below a quarter of span / Q at factor 0.5; longer blocks mean fewer block setups and
 * more candidates.
 *
 * jump_block_quick() (engine v7.2) gives jump_block()'s landings with a cheaper block setup:
 * the first solution comes from the same search in 64-bit arithmetic (below the top level
 * every value fits 64 bits), and the two three-gap steps ga, gc from one subtractive Euclid
 * walk on the one-sided distances of B j mod 2^64 instead of two searches. Where that walk
 * cannot decide (B j = 0 mod 2^64 for a small j) it hands the block to jump_block().
 * ========================================================================================== */
#ifndef ENGINE_JUMP_GEAR_H
#define ENGINE_JUMP_GEAR_H

#include <math.h>
#include <stdint.h>

#define JUMP_NONE ((u128)0 - 1)
#define JUMP_MAX_BLOCK 65536u   /* landings buffered per block; longer blocks are cut */

/* Smallest x >= 0 with l <= (a x) mod m <= r, 0 <= l <= r < m; JUMP_NONE if none. */
static u128 jump_first_in(u128 a, u128 m, u128 l, u128 r) {
    if (l == 0) return 0;
    a %= m;
    if (a == 0) return JUMP_NONE;
    u128 k = (l + a - 1) / a;
    if (a * k <= r) return k;
    u128 y = jump_first_in(m % a, a, (a - r % a) % a, (a - l % a) % a);
    if (y == JUMP_NONE) return JUMP_NONE;
    return (l + m * y + a - 1) / a;
}

/* Smallest x >= 0 with (a x + b) mod 2^64 in [lo, hi], lo <= hi < 2^64; JUMP_NONE if none. */
static u128 jump_first_range(uint64_t a, uint64_t b, uint64_t lo, uint64_t hi) {
    const u128 m = (u128)1 << 64;
    u128 s = ((u128)lo + m - b) % m, e = s + (hi - lo);
    if (e < m) return jump_first_in(a, m, s, e);
    u128 x1 = jump_first_in(a, m, s, m - 1), x2 = jump_first_in(a, m, 0, e - m);
    return x1 < x2 ? x1 : x2;
}

/* Exact offset k q - first of the first multiple of q at or above first, from an estimate
 * k of first / q that is off by at most a few units. */
static inline uint64_t jump_landing(u128 first, uint64_t q, uint64_t k) {
    u128 kq = (u128)k * q;
    while (kq < first) kq += q;
    while (kq - first >= q) kq -= q;
    return (uint64_t)(kq - first);
}

/* Block length for the block starting at Q: factor * Q * sqrt(span / (2 first)) / 30, at
 * least 1, at most JUMP_MAX_BLOCK and at most the j left below q_hi. */
static inline uint64_t jump_block_len(uint64_t Q, uint64_t q_hi, double c) {
    double jd = (double)Q * c / 30.0;
    uint64_t J = jd < 1.0 ? 1 : (jd > JUMP_MAX_BLOCK ? JUMP_MAX_BLOCK : (uint64_t)jd);
    uint64_t left = (q_hi - Q + 29) / 30;
    return J < left ? J : left;
}

/* Offsets g < span of the landings of the block q = Q + 30 j, j < J, written to out (room
 * for J entries) in ascending j; returns their number. */
static uint64_t jump_block(u128 first, uint64_t span, uint64_t Q, uint64_t J, uint64_t *out) {
    uint64_t n = 0;
    u128 K0 = first / Q, R0 = first - K0 * Q;
    if (K0 >> 64) return 0;   /* the caller keeps Q above first / 2^63 */
    u128 X0 = (K0 << 64) | (uint64_t)((R0 << 64) / Q);
    u128 f30 = (u128)30 * first, a = f30 / Q, r1 = f30 - a * Q;
    u128 S = ((a / Q) << 64) + ((a % Q) << 64) / Q + (r1 << 64) / ((u128)Q * Q);
    uint64_t d_max = 30 * (J - 1);
    double e_ulp = (double)first * (double)d_max * (double)d_max /
                   ((double)Q * (double)Q * (double)Q) * 18446744073709551616.0;
    uint64_t slack = 2 * J + 8;
    double t_d = (double)span / (double)Q * 18446744073709551616.0 + e_ulp * 1.001 +
                 2.0 * slack + 1;
    if (t_d >= 1.8e19) {
        /* Too wide for the candidate search: every j is checked. */
        for (uint64_t j = 0; j < J; j++) {
            uint64_t q = Q + 30 * j;
            uint64_t g = jump_landing(first, q, (uint64_t)(first / q));
            if (g < span) out[n++] = g;
        }
        return n;
    }
    uint64_t T = (uint64_t)t_d;
    uint64_t A = (uint64_t)0 - (uint64_t)X0 + slack, B = (uint64_t)S;

    u128 j0 = jump_first_range(B, A, 0, T - 1);
    if (j0 == JUMP_NONE || j0 >= J) return 0;
    u128 ga = jump_first_range(B, B, 0, T - 1), gc = jump_first_range(B, B, -T + 1, -1);
    if (ga == JUMP_NONE || gc == JUMP_NONE) {
        for (uint64_t j = (uint64_t)j0; j < J; j++) {
            uint64_t q = Q + 30 * j;
            uint64_t g = jump_landing(first, q, (uint64_t)(first / q));
            if (g < span) out[n++] = g;
        }
        return n;
    }
    ga += 1;
    gc += 1;
    uint64_t alpha = B * (uint64_t)ga, beta = (uint64_t)0 - B * (uint64_t)gc;
    uint64_t j = (uint64_t)j0, v = A + B * j;
    for (;;) {
        uint64_t q = Q + 30 * j;
        u128 x = X0 - S * j;
        uint64_t g = jump_landing(first, q, (uint64_t)(x >> 64) + 1);
        if (g < span) out[n++] = g;
        /* three-gap step to the next j with v < T */
        if (v + alpha < T && v + alpha >= v) {
            j += (uint64_t)ga;
            v += alpha;
        } else if (v >= beta) {
            j += (uint64_t)gc;
            v -= beta;
        } else {
            j += (uint64_t)(ga + gc);
            v += alpha - beta;
        }
        if (j >= J) break;
    }
    return n;
}

#define JUMP_NONE64 UINT64_MAX

/* jump_first_in() for 0 <= l <= r < m < 2^64, a < m, in 64-bit arithmetic; JUMP_NONE64 if
 * none. */
static uint64_t jump_first_in64(uint64_t a, uint64_t m, uint64_t l, uint64_t r) {
    if (l == 0) return 0;
    if (a == 0) return JUMP_NONE64;
    uint64_t k = l / a + (l % a != 0);
    if ((u128)a * k <= r) return k;
    uint64_t y = jump_first_in64(m % a, a, (a - r % a) % a, (a - l % a) % a);
    if (y == JUMP_NONE64) return JUMP_NONE64;
    return (uint64_t)(((u128)l + (u128)m * y + a - 1) / a);
}

/* jump_first_in() with m = 2^64: the top level in 128 bits, the rest in 64 (2^64 mod a). */
static uint64_t jump_first_in_top(uint64_t a, uint64_t l, uint64_t r) {
    if (l == 0) return 0;
    if (a == 0) return JUMP_NONE64;
    uint64_t k = l / a + (l % a != 0);
    if ((u128)a * k <= r) return k;
    uint64_t y = jump_first_in64((0 - a) % a, a, (a - r % a) % a, (a - l % a) % a);
    if (y == JUMP_NONE64) return JUMP_NONE64;
    u128 x = ((u128)l + ((u128)y << 64) + a - 1) / a;
    return (x >> 64) ? JUMP_NONE64 : (uint64_t)x;
}

/* jump_first_range() in 64-bit arithmetic; JUMP_NONE64 if none. */
static uint64_t jump_first_range64(uint64_t a, uint64_t b, uint64_t lo, uint64_t hi) {
    uint64_t s = lo - b, width = hi - lo;
    if (s <= UINT64_MAX - width) return jump_first_in_top(a, s, s + width);
    uint64_t x1 = jump_first_in_top(a, s, UINT64_MAX), x2 = jump_first_in_top(a, 0, s + width);
    return x1 < x2 ? x1 : x2;
}

/* The three-gap steps for v < T: ga = the smallest j > 0 with B j mod 2^64 in (0, T), gc =
 * the smallest j > 0 with -B j mod 2^64 in (0, T). Subtractive Euclid on da = qa B mod 2^64
 * and dc = -qc B mod 2^64: the larger distance takes as many of the smaller as keep it
 * positive and stop it at its first value below T, so no smaller q on either side is
 * skipped. Returns 0 when a distance reaches 0 first (the caller falls back). */
static int jump_gaps(uint64_t B, uint64_t T, uint64_t *ga, uint64_t *gc) {
    if (B == 0) return 0;
    uint64_t qa = 1, da = B, qc = 1, dc = 0 - B;
    while (da >= T || dc >= T) {
        if (da >= dc) {
            uint64_t k = (da - T) / dc + 1, kmax = (da - 1) / dc;
            if (k > kmax) k = kmax;
            if (k == 0) return 0;
            da -= k * dc;
            qa += k * qc;
        } else {
            uint64_t k = (dc - T) / da + 1, kmax = (dc - 1) / da;
            if (k > kmax) k = kmax;
            if (k == 0) return 0;
            dc -= k * da;
            qc += k * qa;
        }
    }
    *ga = qa;
    *gc = qc;
    return 1;
}

/* jump_block() with the cheaper setup (header); the same landings in the same order. */
static uint64_t jump_block_quick(u128 first, uint64_t span, uint64_t Q, uint64_t J,
                                 uint64_t *out) {
    uint64_t n = 0;
    u128 K0 = first / Q, R0 = first - K0 * Q;
    if (K0 >> 64) return 0;   /* the caller keeps Q above first / 2^63 */
    u128 X0 = (K0 << 64) | (uint64_t)((R0 << 64) / Q);
    u128 f30 = (u128)30 * first, a = f30 / Q, r1 = f30 - a * Q;
    u128 S = ((a / Q) << 64) + ((a % Q) << 64) / Q + (r1 << 64) / ((u128)Q * Q);
    uint64_t d_max = 30 * (J - 1);
    double e_ulp = (double)first * (double)d_max * (double)d_max /
                   ((double)Q * (double)Q * (double)Q) * 18446744073709551616.0;
    uint64_t slack = 2 * J + 8;
    double t_d = (double)span / (double)Q * 18446744073709551616.0 + e_ulp * 1.001 +
                 2.0 * slack + 1;
    if (t_d >= 1.8e19) return jump_block(first, span, Q, J, out);
    uint64_t T = (uint64_t)t_d;
    uint64_t A = (uint64_t)0 - (uint64_t)X0 + slack, B = (uint64_t)S;
    uint64_t j = jump_first_range64(B, A, 0, T - 1), ga, gc;
    if (j == JUMP_NONE64 || j >= J) return 0;
    if (!jump_gaps(B, T, &ga, &gc)) return jump_block(first, span, Q, J, out);
    uint64_t alpha = B * ga, beta = (uint64_t)0 - B * gc, v = A + B * j;
    for (;;) {
        uint64_t q = Q + 30 * j;
        u128 x = X0 - S * j;
        uint64_t g = jump_landing(first, q, (uint64_t)(x >> 64) + 1);
        if (g < span) out[n++] = g;
        if (v + alpha < T && v + alpha >= v) {
            j += ga;
            v += alpha;
        } else if (v >= beta) {
            j += gc;
            v -= beta;
        } else {
            j += ga + gc;
            v += alpha - beta;
        }
        if (j >= J) break;
    }
    return n;
}

#endif
