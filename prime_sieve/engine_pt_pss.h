/* engine_pt_pss.h -- the pseudosquares primality proof (included after engine_pt_core.h).
 *
 * Lukes, Patterson and Williams, with Sorenson's sieve bound s: for odd n with every prime
 * factor above s and n / s < L_p, where L_p is the pseudosquare of the prime p (the
 * n_bases-th prime of the table), n is prime or a prime power iff
 *   (a) q^((n-1)/2) = +-1 (mod n) for every prime q <= p,
 *   (b) n = 5 (mod 8): 2^((n-1)/2) = -1;
 *       n = 1 (mod 8): some q <= p gives -1. When every q <= p gives +1, a prime n would be a
 *       quadratic residue modulo every prime <= p, so n >= L_p: n < L_p is composite;
 *       otherwise the primes q > p are tried one at a time until one gives -1 (prime), a
 *       value other than +-1 (composite) or all give +1 with L_q > n (composite).
 * A prime power passes only above 6.4e37 (Sorenson). The sieve bound s stays below 2^32
 * (engine_pt_core.h), so n / s < L_373 holds only for n below about 1.8e34: far below that.
 * The caller guarantees n odd, n > 373 (no base is n itself) and the two conditions on s.
 */
#ifndef ENGINE_PT_PSS_H
#define ENGINE_PT_PSS_H

/* The pseudosquares L_p (OEIS A002189) for the primes p <= 373: L_p is the smallest non-square
 * n = 1 (mod 8) that is a quadratic residue modulo every odd prime <= p. */
static const struct { u32 p; u64 hi, lo; } PSS[] = {
    {2, 0x0u, 0x0000000000000011u},   /* 17 */
    {3, 0x0u, 0x0000000000000049u},   /* 73 */
    {5, 0x0u, 0x00000000000000f1u},   /* 241 */
    {7, 0x0u, 0x00000000000003f1u},   /* 1009 */
    {11, 0x0u, 0x0000000000000a51u},   /* 2641 */
    {13, 0x0u, 0x0000000000001f99u},   /* 8089 */
    {17, 0x0u, 0x0000000000004651u},   /* 18001 */
    {19, 0x0u, 0x000000000000d279u},   /* 53881 */
    {23, 0x0u, 0x00000000000155b9u},   /* 87481 */
    {29, 0x0u, 0x000000000001c939u},   /* 117049 */
    {31, 0x0u, 0x000000000007deb1u},   /* 515761 */
    {37, 0x0u, 0x0000000000108799u},   /* 1083289 */
    {41, 0x0u, 0x000000000030edf1u},   /* 3206641 */
    {43, 0x0u, 0x00000000003a45b1u},   /* 3818929 */
    {47, 0x0u, 0x00000000008d4171u},   /* 9257329 */
    {53, 0x0u, 0x00000000014fb4a1u},   /* 22000801 */
    {59, 0x0u, 0x0000000002e3a719u},   /* 48473881 */
    {61, 0x0u, 0x0000000002e3a719u},   /* 48473881 */
    {67, 0x0u, 0x000000000a7203f9u},   /* 175244281 */
    {71, 0x0u, 0x00000000197eb151u},   /* 427733329 */
    {73, 0x0u, 0x00000000197eb151u},   /* 427733329 */
    {79, 0x0u, 0x0000000035915281u},   /* 898716289 */
    {83, 0x0u, 0x00000000a73936e9u},   /* 2805544681 */
    {89, 0x0u, 0x00000000a73936e9u},   /* 2805544681 */
    {97, 0x0u, 0x00000000a73936e9u},   /* 2805544681 */
    {101, 0x0u, 0x00000002668a2291u},   /* 10310263441 */
    {103, 0x0u, 0x000000057fa49ee1u},   /* 23616331489 */
    {107, 0x0u, 0x00000013d3ca03a9u},   /* 85157610409 */
    {109, 0x0u, 0x00000013d3ca03a9u},   /* 85157610409 */
    {113, 0x0u, 0x0000002db24faf61u},   /* 196265095009 */
    {127, 0x0u, 0x0000002db24faf61u},   /* 196265095009 */
    {131, 0x0u, 0x0000029ca72c28b1u},   /* 2871842842801 */
    {137, 0x0u, 0x0000029ca72c28b1u},   /* 2871842842801 */
    {139, 0x0u, 0x0000029ca72c28b1u},   /* 2871842842801 */
    {149, 0x0u, 0x000017e002cbcc71u},   /* 26250887023729 */
    {151, 0x0u, 0x000017e002cbcc71u},   /* 26250887023729 */
    {157, 0x0u, 0x000066424050a651u},   /* 112434732901969 */
    {163, 0x0u, 0x000066424050a651u},   /* 112434732901969 */
    {167, 0x0u, 0x000066424050a651u},   /* 112434732901969 */
    {173, 0x0u, 0x0000a2bdd5fb5579u},   /* 178936222537081 */
    {179, 0x0u, 0x0000a2bdd5fb5579u},   /* 178936222537081 */
    {181, 0x0u, 0x00027927a3ae3219u},   /* 696161110209049 */
    {191, 0x0u, 0x00027927a3ae3219u},   /* 696161110209049 */
    {193, 0x0u, 0x000a24867370e9c9u},   /* 2854909648103881 */
    {197, 0x0u, 0x0016ea483fcdcaf1u},   /* 6450045516630769 */
    {199, 0x0u, 0x0016ea483fcdcaf1u},   /* 6450045516630769 */
    {211, 0x0u, 0x00295bca7adcc891u},   /* 11641399247947921 */
    {223, 0x0u, 0x00295bca7adcc891u},   /* 11641399247947921 */
    {227, 0x0u, 0x02a5392dfc789491u},   /* 190621428905186449 */
    {229, 0x0u, 0x02ba9b2c41634399u},   /* 196640148121928601 */
    {233, 0x0u, 0x09e3c00e9fa45911u},   /* 712624335095093521 */
    {239, 0x0u, 0x189e0071c5a604d1u},   /* 1773855791877850321 */
    {241, 0x0u, 0x204d9b0d5d694449u},   /* 2327687064124474441 */
    {251, 0x0u, 0x589c0c47877cd311u},   /* 6384991873059836689 */
    {257, 0x0u, 0x6f49f026e24427f1u},   /* 8019204661305419761 */
    {263, 0x0u, 0x8d86ee729092c749u},   /* 10198100582046287689 */
    {269, 0x0u, 0x8d86ee729092c749u},   /* 10198100582046287689 */
    {271, 0x0u, 0x8d86ee729092c749u},   /* 10198100582046287689 */
    {277, 0x3u, 0xc956f827e0524359u},   /* 69848288320900186969 */
    {281, 0xbu, 0x539315b3b1268d59u},   /* 208936365799044975961 */
    {283, 0x1cu, 0xec87d86ca60b50a1u},   /* 533552663339828203681 */
    {293, 0x32u, 0xc6d3496f20db3d81u},   /* 936664079266714697089 */
    {307, 0x32u, 0xc6d3496f20db3d81u},   /* 936664079266714697089 */
    {311, 0x74u, 0x210967a12ba94be1u},   /* 2142202860370269916129 */
    {313, 0x74u, 0x210967a12ba94be1u},   /* 2142202860370269916129 */
    {317, 0x74u, 0x210967a12ba94be1u},   /* 2142202860370269916129 */
    {331, 0x2e3u, 0xec11ddc09fd65c51u},   /* 13649154491558298803281 */
    {337, 0x753u, 0x641c14b397c27bf1u},   /* 34594858801670127778801 */
    {347, 0x1511u, 0x85fdf38d1fc9ce21u},   /* 99492945930479213334049 */
    {349, 0x1511u, 0x85fdf38d1fc9ce21u},   /* 99492945930479213334049 */
    {353, 0x3e8bu, 0xaba417e222ca5091u},   /* 295363187400900310880401 */
    {359, 0x3e8bu, 0xaba417e222ca5091u},   /* 295363187400900310880401 */
    {367, 0x3060cu, 0x1394318d9bee0a99u},   /* 3655334429477057460046489 */
    {373, 0x380cdu, 0x2d681a84541eaa61u},   /* 4235025223080597503519329 */
};
#define PSS_COUNT ((int)(sizeof PSS / sizeof PSS[0]))

static inline u128 pss_l(int k) { return ((u128)PSS[k].hi << 64) | PSS[k].lo; }

/* x^e in Montgomery form, x = bm */
static inline u128 mpow(const mont *m, u128 bm, u128 e) {
    u128 x = bm;
    for (int i = bit_length(e) - 2; i >= 0; i--) {
        x = mmul(m, x, x);
        if ((e >> i) & 1) x = mmul(m, x, bm);
    }
    return x;
}

/* four bases at once: the independent product chains overlap in the pipeline */
static inline void mpow4(const mont *m, const u128 *bm, u128 e, u128 *out) {
    u128 x0 = bm[0], x1 = bm[1], x2 = bm[2], x3 = bm[3];
    for (int i = bit_length(e) - 2; i >= 0; i--) {
        x0 = mmul(m, x0, x0); x1 = mmul(m, x1, x1); x2 = mmul(m, x2, x2); x3 = mmul(m, x3, x3);
        if ((e >> i) & 1) {
            x0 = mmul(m, x0, bm[0]); x1 = mmul(m, x1, bm[1]);
            x2 = mmul(m, x2, bm[2]); x3 = mmul(m, x3, bm[3]);
        }
    }
    out[0] = x0; out[1] = x1; out[2] = x2; out[3] = x3;
}

/* 2^e in Montgomery form: multiplying by 2 is a doubling */
static inline u128 mpow2(const mont *m, u128 e) {
    u128 x = madd(m, m->one, m->one);
    for (int i = bit_length(e) - 2; i >= 0; i--) {
        x = mmul(m, x, x);
        if ((e >> i) & 1) x = madd(m, x, x);
    }
    return x;
}

/* The pseudosquares test with the bases PSS[0 .. n_bases - 1] (header): 1 prime, 0 composite,
 * -1 undecided past the table. The caller guarantees n odd, n > 373, no prime factor <= s and
 * n / s < L_p for p = PSS[n_bases - 1].p. */
static inline int pss_prove(u128 n, int n_bases) {
    mont m;
    mont_init(&m, n);
    u128 e = (n - 1) >> 1, one = m.one, mone = n - m.one;
    u128 r = mpow2(&m, e);                 /* base 2 first: most composites stop here */
    if (r != one && r != mone) return 0;
    if ((n & 7) == 5 && r != mone) return 0;
    int minus1 = r == mone, k = 1;
    for (; k + 4 <= n_bases; k += 4) {
        u128 b[4], v[4];
        for (int t = 0; t < 4; t++) b[t] = to_mont(&m, PSS[k + t].p);
        mpow4(&m, b, e, v);
        for (int t = 0; t < 4; t++) {
            if (v[t] != one && v[t] != mone) return 0;
            minus1 |= v[t] == mone;
        }
    }
    for (; k < n_bases; k++) {
        r = mpow(&m, to_mont(&m, PSS[k].p), e);
        if (r != one && r != mone) return 0;
        minus1 |= r == mone;
    }
    if ((n & 7) != 1 || minus1) return 1;
    if (pss_l(n_bases - 1) > n) return 0;
    for (k = n_bases; k < PSS_COUNT; k++) {
        r = mpow(&m, to_mont(&m, PSS[k].p), e);
        if (r == mone) return 1;
        if (r != one) return 0;
        if (pss_l(k) > n) return 0;
    }
    return -1;
}

/* Number of table bases the proof needs for numbers up to top with sieve bound s: the k + 1 of
 * the first L_{p_k} > top / s; 0 when even L_373 is too small. */
static inline int pss_bases(u128 top, u64 s) {
    if (s < 1) return 0;
    u128 q = top / s;
    for (int k = 0; k < PSS_COUNT; k++)
        if (pss_l(k) > q) return k + 1;
    return 0;
}

/* Smallest sieve bound s with top / s < L_373, saturated at 2^64 - 1. */
static inline u64 pss_min_s(u128 top) {
    u128 s = top / pss_l(PSS_COUNT - 1) + 1;
    return s >> 64 ? UINT64_MAX : (u64)s;
}

#endif
