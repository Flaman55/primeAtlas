/* ==========================================================================================
 * engine_jump_gear.h -- the jump gear of engine v7.0 (included by prime_sieve_engine_v7_0.c).
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

#endif
