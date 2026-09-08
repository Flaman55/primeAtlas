/* Native tuple-product marking core for PrimeAtlas hybrid sieve.
 *
 * Build (WSL):
 *   gcc -O3 -shared -fPIC hybrid_filter_engine.c -o hybrid_filter_engine.so
 *
 * This deliberately has no dependency on prime_sieve_engine_v4.c or libprimesieve.
 * The caller supplies an already trusted, ascending filter-prime list.  Recursion uses
 * nondecreasing indexes, so unique factorisation visits every product exactly once while
 * still allowing powers p^r.  Multiplication is guarded in division form before it occurs.
 */

#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint64_t lo;
    uint64_t hi;
    const uint64_t *primes;
    size_t prime_count;
    uint32_t max_order;
    unsigned char *bits;
    uint64_t *counts;
} tuple_context;

static void visit_products(tuple_context *ctx, uint64_t product, size_t first, uint32_t depth) {
    for (size_t index = first; index < ctx->prime_count; ++index) {
        uint64_t prime = ctx->primes[index];
        if (product > (ctx->hi - 1) / prime) break;
        uint64_t candidate = product * prime;
        uint32_t next_depth = depth + 1;

        if (next_depth >= 2 && candidate >= ctx->lo) {
            uint64_t offset = candidate - ctx->lo;
            unsigned char mask = (unsigned char)(1u << (offset & 7));
            __atomic_fetch_or(&ctx->bits[offset >> 3], mask, __ATOMIC_RELAXED);
            ctx->counts[next_depth] += 1;
        }
        if (next_depth < ctx->max_order)
            visit_products(ctx, candidate, index, next_depth);
    }
}

/* Returns 0 on success.  The bit buffer is supplied by the caller and is OR-only: this
 * makes it safe to combine with independently run MAIN marking and with other workers. */
int mark_filter_tuple_products_atomic(uint64_t segment_lo, uint64_t segment_size,
                                      const uint64_t *filter_primes, size_t filter_count,
                                      uint32_t max_order, unsigned char *out_dense_bits,
                                      uint64_t *out_counts) {
    if (!filter_primes || !out_dense_bits || !out_counts || filter_count == 0 || max_order < 2)
        return -1;
    if (segment_size == 0 || segment_lo > UINT64_MAX - segment_size)
        return -2;
    for (size_t i = 1; i < filter_count; ++i)
        if (filter_primes[i] <= filter_primes[i - 1]) return -3;

    for (uint32_t order = 0; order <= max_order; ++order) out_counts[order] = 0;
    tuple_context ctx = {
        .lo = segment_lo,
        .hi = segment_lo + segment_size,
        .primes = filter_primes,
        .prime_count = filter_count,
        .max_order = max_order,
        .bits = out_dense_bits,
        .counts = out_counts,
    };
    visit_products(&ctx, 1, 0, 0);
    return 0;
}
