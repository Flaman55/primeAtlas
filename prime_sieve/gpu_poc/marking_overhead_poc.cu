// marking_overhead_poc.cu -- follow-up diagnostic to marking_poc.cu's real-hardware run
// (2026-08-28). That run measured marking_kernel at two (n_primes, combined_size) points:
//   3,417 primes / combined_size=10,000,000   -> kernel 2.97ms
//   20,000,000 primes / combined_size=100,000,000 -> kernel 366.5ms
// n_primes grew ~5854x, kernel time grew only ~123x -- not linear either way in the two
// variables that both changed at once (n_primes AND combined_size), so that comparison alone
// cannot say WHY. This file decomposes marking_kernel's cost into three components by running
// three kernel variants, same grid/block shape, back-to-back on the SAME uploaded primes:
//
//   1. null_kernel        -- launches the identical grid (one block per prime, MARK_THREADS
//                             threads per block), each block does one trivial atomicAdd and
//                             nothing else. Isolates PURE grid-launch/block-scheduling
//                             overhead, independent of n_primes' actual values or
//                             combined_size.
//   2. phase_only_kernel  -- INTENTIONALLY the OLD, pre-fix phase_mod_gpu + self-elimination
//                             -guard computation, run redundantly by all MARK_THREADS threads
//                             per block (kept exactly as it was, NOT updated to match
//                             marking_kernel's 2026-08-28 fix below), skipping the
//                             stride-marking loop. Kept as a fixed baseline so re-running this
//                             sweep after the fix shows the achieved improvement directly.
//   3. marking_kernel     -- kept IN SYNC with marking_poc.cu's own copy (see that file's
//                             header comment on this kernel for the full fix rationale).
//
// UPDATE (2026-08-28, after this file's FIRST real-hardware run found the redundant-phase cost
// was ~96% of total kernel time at 20,000,000-prime scale): marking_kernel above is now the
// FIXED version (thread 0 computes phase+guard once, broadcasts via shared memory). Variant 2
// deliberately stays un-fixed as a stable comparison point. Re-running the same two sweeps
// after this change directly measures the real achieved speedup on your hardware, rather than
// trusting the theoretical ~6-8x estimate (see chat/README for why it's ~8x, not the naively
// GPU-oblivious ~256x a first pass at this reasoning suggested -- GPUs execute in 32-thread
// warps, so 256 redundant threads is 8 redundant warps, not 256 independent repetitions).
//
// Subtracting these pairwise gives an estimated breakdown:
//   launch_overhead_ms   = null_kernel time
//   redundant_phase_ms   = phase_only_kernel time - null_kernel time   (OLD design's cost)
//   real_marking_ms      = marking_kernel time - phase_only_kernel time   (now includes the
//                          NEW, cheap broadcast-based phase cost plus real marking -- no longer
//                          "real marking work" alone once variant 3 is fixed and variant 2
//                          isn't; read this column post-fix as "everything variant 2 doesn't
//                          already cover", not literally isolated marking-only time)
//
// This is a rough additive model (kernels aren't perfectly composable due to scheduling
// interaction effects), but it is the standard first-order way to decompose a GPU kernel's
// cost when you cannot profile with nsight on the target machine directly.
//
// Runs a SWEEP of cases in one process (one CUDA context, uploaded once per case) to avoid
// confounding the comparison with process-startup variance between separate binary
// invocations -- see marking_overhead_poc.py for the two sweeps it drives (fixed
// combined_size/varying n_primes, and fixed n_primes/varying combined_size).

#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cuda_runtime.h>

#define PHASE_MOD_MAX_SAFE_PRIME_BITS 50
#define MARK_THREADS 256
#define N_REPEATS 5   // per kernel per case -- report the MIN (least-perturbed run), standard
                       // practice for microbenchmarks where we're subtracting small
                       // differences and want to minimize OS/driver scheduling noise

__device__ __forceinline__ unsigned long long mulmod64(unsigned long long a,
                                                         unsigned long long b,
                                                         unsigned long long m) {
    double da = (double)a, db = (double)b, dm = (double)m;
    unsigned long long q = (unsigned long long)(da * db / dm);
    unsigned long long r = a * b - q * m;
    r -= (r >= m) ? m : 0ULL;
    r -= (r >= m) ? m : 0ULL;
    return r;
}

__device__ __forceinline__ unsigned long long phase_mod_gpu(unsigned long long distance_hi,
                                                              unsigned long long distance_lo,
                                                              unsigned long long p) {
    unsigned long long hi_r = distance_hi % p;
    unsigned long long lo_r = distance_lo % p;
    unsigned long long two64_mod_p = (0xFFFFFFFFFFFFFFFFULL % p) + 1ULL;
    two64_mod_p -= (two64_mod_p >= p) ? p : 0ULL;
    unsigned long long term = mulmod64(hi_r, two64_mod_p, p);
    unsigned long long result = term + lo_r;
    result -= (result >= p) ? p : 0ULL;
    return result;
}

__device__ __forceinline__ void atomic_or_bit(unsigned char* bits_buf, unsigned long long pos) {
    unsigned long long byte_idx = pos >> 3;
    unsigned int bit_mask = 1u << (unsigned int)(pos & 7);
    unsigned long long word_idx = byte_idx >> 2;
    unsigned int byte_in_word = (unsigned int)(byte_idx & 3ULL);
    unsigned int shifted_mask = bit_mask << (byte_in_word * 8);
    unsigned int* word_ptr = ((unsigned int*)bits_buf) + word_idx;
    atomicOr(word_ptr, shifted_mask);
}

// --- Variant 1: pure launch/scheduling overhead, zero per-thread work beyond one atomicAdd
// per BLOCK (not per thread) so the compiler cannot eliminate the kernel as dead code. ---
__global__ void null_kernel(int n_primes, unsigned int* touch) {
    int prime_idx = blockIdx.x;
    if (prime_idx >= n_primes) return;
    if (threadIdx.x == 0) {
        atomicAdd(touch, 1u);
    }
}

// --- Variant 2: intentionally the OLD, pre-fix marking_kernel header (phase_mod_gpu + guard
// computed redundantly by all MARK_THREADS threads per block, no shared-memory broadcast) --
// but no stride-marking loop. This is DELIBERATELY kept as the un-fixed baseline (not updated
// to match marking_poc.cu's 2026-08-28 fix below) so re-running this sweep after the fix shows
// the ACHIEVED improvement: compare this variant's cost against variant 3's new, much cheaper
// phase-computation share. Thread 0 writes start_pos to `touch` so the compiler cannot
// eliminate the computation as dead code. ---
__global__ void phase_only_kernel(const unsigned long long* __restrict__ primes, int n_primes,
                                   unsigned long long distance_hi, unsigned long long distance_lo,
                                   unsigned long long combined_size, unsigned int* touch) {
    int prime_idx = blockIdx.x;
    if (prime_idx >= n_primes) return;
    unsigned long long p = primes[prime_idx];

    unsigned long long rem = phase_mod_gpu(distance_hi, distance_lo, p);
    unsigned long long start_pos = (rem == 0) ? 0ULL : (p - rem);

    if (distance_hi == 0) {
        unsigned long long sum = distance_lo + start_pos;
        bool overflowed = sum < distance_lo;
        if (!overflowed && sum <= p) {
            start_pos += p;
        }
    }

    if (threadIdx.x == 0) {
        atomicAdd(touch, (unsigned int)(start_pos & 0xFFFFFFFFULL));
    }
    // deliberately no marking loop, no early "start_pos >= combined_size" return either --
    // keeping ALL threads alive through the same instruction count as marking_kernel's
    // header, for the cleanest possible subtraction against variant 3 below
    (void)combined_size;
}

// --- Variant 3: the real marking_kernel from marking_poc.cu, kept in sync with that file --
// as of 2026-08-28 this is the FIXED version (thread 0 computes phase+guard once, broadcasts
// via shared memory, see marking_poc.cu's own header comment on this kernel for the full
// rationale and the real-hardware numbers that motivated it). ---
__global__ void marking_kernel(const unsigned long long* __restrict__ primes, int n_primes,
                                unsigned long long distance_hi, unsigned long long distance_lo,
                                unsigned long long combined_size,
                                unsigned char* __restrict__ out_bits) {
    int prime_idx = blockIdx.x;
    if (prime_idx >= n_primes) return;
    unsigned long long p = primes[prime_idx];

    __shared__ unsigned long long s_start_pos;
    if (threadIdx.x == 0) {
        unsigned long long rem = phase_mod_gpu(distance_hi, distance_lo, p);
        unsigned long long start_pos = (rem == 0) ? 0ULL : (p - rem);

        if (distance_hi == 0) {
            unsigned long long sum = distance_lo + start_pos;
            bool overflowed = sum < distance_lo;
            if (!overflowed && sum <= p) {
                start_pos += p;
            }
        }
        s_start_pos = start_pos;
    }
    __syncthreads();
    unsigned long long start_pos = s_start_pos;

    if (start_pos >= combined_size) return;

    for (unsigned long long pos = start_pos + (unsigned long long)threadIdx.x * p;
         pos < combined_size;
         pos += (unsigned long long)MARK_THREADS * p) {
        atomic_or_bit(out_bits, pos);
    }
}

// ---------------------------------------------------------------------------------------------
// Host driver.
//
// Input file format (little-endian):
//   uint64_t n_cases
//   for each case:
//     uint64_t n_primes
//     uint64_t primes[n_primes]
//     uint64_t distance_hi
//     uint64_t distance_lo
//     uint64_t combined_size
//
// Output file format:
//   uint64_t n_cases
//   for each case:
//     uint64_t n_primes
//     uint64_t combined_size
//     double   null_ms          (min of N_REPEATS)
//     double   phase_only_ms    (min of N_REPEATS)
//     double   full_marking_ms  (min of N_REPEATS)
// ---------------------------------------------------------------------------------------------

#define CUDA_CHECK(call) do { \
    cudaError_t _e = (call); \
    if (_e != cudaSuccess) { \
        fprintf(stderr, "CUDA error at %s:%d: %s\n", __FILE__, __LINE__, cudaGetErrorString(_e)); \
        exit(1); \
    } \
} while (0)

static float time_kernel_min(int repeats, void (*launch)(void*), void* ctx) {
    float best = -1.0f;
    cudaEvent_t t0, t1;
    CUDA_CHECK(cudaEventCreate(&t0));
    CUDA_CHECK(cudaEventCreate(&t1));
    for (int r = 0; r < repeats; r++) {
        CUDA_CHECK(cudaEventRecord(t0));
        launch(ctx);
        CUDA_CHECK(cudaEventRecord(t1));
        CUDA_CHECK(cudaEventSynchronize(t1));
        float ms;
        CUDA_CHECK(cudaEventElapsedTime(&ms, t0, t1));
        if (best < 0.0f || ms < best) best = ms;
    }
    CUDA_CHECK(cudaEventDestroy(t0));
    CUDA_CHECK(cudaEventDestroy(t1));
    return best;
}

struct NullCtx { int n_primes; unsigned int* touch; };
static void launch_null(void* vctx) {
    NullCtx* c = (NullCtx*)vctx;
    dim3 grid(c->n_primes);
    dim3 block(MARK_THREADS);
    null_kernel<<<grid, block>>>(c->n_primes, c->touch);
}

struct PhaseCtx {
    const unsigned long long* d_primes; int n_primes;
    unsigned long long distance_hi, distance_lo, combined_size;
    unsigned int* touch;
};
static void launch_phase(void* vctx) {
    PhaseCtx* c = (PhaseCtx*)vctx;
    dim3 grid(c->n_primes);
    dim3 block(MARK_THREADS);
    phase_only_kernel<<<grid, block>>>(c->d_primes, c->n_primes, c->distance_hi, c->distance_lo,
                                        c->combined_size, c->touch);
}

struct MarkCtx {
    const unsigned long long* d_primes; int n_primes;
    unsigned long long distance_hi, distance_lo, combined_size;
    unsigned char* out_bits;
};
static void launch_mark(void* vctx) {
    MarkCtx* c = (MarkCtx*)vctx;
    dim3 grid(c->n_primes);
    dim3 block(MARK_THREADS);
    marking_kernel<<<grid, block>>>(c->d_primes, c->n_primes, c->distance_hi, c->distance_lo,
                                     c->combined_size, c->out_bits);
}

int main(int argc, char** argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s <input.bin> <output.bin>\n", argv[0]);
        return 1;
    }
    FILE* fin = fopen(argv[1], "rb");
    if (!fin) { fprintf(stderr, "cannot open input %s\n", argv[1]); return 1; }

    uint64_t n_cases;
    if (fread(&n_cases, 8, 1, fin) != 1) { fprintf(stderr, "bad header\n"); return 1; }

    FILE* fout = fopen(argv[2], "wb");
    if (!fout) { fprintf(stderr, "cannot open output %s\n", argv[2]); return 1; }
    fwrite(&n_cases, 8, 1, fout);

    unsigned long long safe_limit = 1ULL << PHASE_MOD_MAX_SAFE_PRIME_BITS;

    for (uint64_t ci = 0; ci < n_cases; ci++) {
        uint64_t n_primes64;
        if (fread(&n_primes64, 8, 1, fin) != 1) { fprintf(stderr, "bad case header\n"); return 1; }
        int n_primes = (int)n_primes64;
        unsigned long long* h_primes =
            (unsigned long long*)malloc(sizeof(unsigned long long) * n_primes);
        if (fread(h_primes, 8, n_primes, fin) != (size_t)n_primes) {
            fprintf(stderr, "malformed input: expected %d primes\n", n_primes); return 1;
        }
        for (int i = 0; i < n_primes; i++) {
            if (h_primes[i] >= safe_limit) {
                fprintf(stderr, "REFUSING: prime[%d]=%llu >= 2^%d safe limit\n",
                        i, h_primes[i], PHASE_MOD_MAX_SAFE_PRIME_BITS);
                return 1;
            }
        }
        unsigned long long distance_hi, distance_lo, combined_size;
        if (fread(&distance_hi, 8, 1, fin) != 1 || fread(&distance_lo, 8, 1, fin) != 1 ||
            fread(&combined_size, 8, 1, fin) != 1) {
            fprintf(stderr, "bad case header (distance/combined_size)\n"); return 1;
        }

        unsigned long long combined_bytes = (combined_size + 7) / 8;
        combined_bytes = ((combined_bytes + 3) / 4) * 4;

        fprintf(stderr, "[case %llu] n_primes=%d combined_size=%llu\n",
                (unsigned long long)ci, n_primes, combined_size);

        unsigned long long* d_primes;
        unsigned char* d_bits;
        unsigned int* d_touch;
        CUDA_CHECK(cudaMalloc(&d_primes, sizeof(unsigned long long) * n_primes));
        CUDA_CHECK(cudaMalloc(&d_bits, combined_bytes));
        CUDA_CHECK(cudaMalloc(&d_touch, sizeof(unsigned int)));
        CUDA_CHECK(cudaMemcpy(d_primes, h_primes, sizeof(unsigned long long) * n_primes,
                               cudaMemcpyHostToDevice));

        NullCtx nctx = { n_primes, d_touch };
        float null_ms = time_kernel_min(N_REPEATS, launch_null, &nctx);

        PhaseCtx pctx = { d_primes, n_primes, distance_hi, distance_lo, combined_size, d_touch };
        float phase_ms = time_kernel_min(N_REPEATS, launch_phase, &pctx);

        MarkCtx mctx = { d_primes, n_primes, distance_hi, distance_lo, combined_size, d_bits };
        float mark_ms = time_kernel_min(N_REPEATS, launch_mark, &mctx);

        fprintf(stderr, "         null=%.4fms  phase_only=%.4fms  full_marking=%.4fms  "
                        "(redundant_phase=%.4fms  real_marking=%.4fms)\n",
                null_ms, phase_ms, mark_ms, phase_ms - null_ms, mark_ms - phase_ms);

        double d_null = null_ms, d_phase = phase_ms, d_mark = mark_ms;
        fwrite(&n_primes64, 8, 1, fout);
        fwrite(&combined_size, 8, 1, fout);
        fwrite(&d_null, sizeof(double), 1, fout);
        fwrite(&d_phase, sizeof(double), 1, fout);
        fwrite(&d_mark, sizeof(double), 1, fout);

        free(h_primes);
        cudaFree(d_primes); cudaFree(d_bits); cudaFree(d_touch);
    }

    fclose(fin);
    fclose(fout);
    return 0;
}
