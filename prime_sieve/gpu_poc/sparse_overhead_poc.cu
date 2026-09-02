// sparse_overhead_poc.cu -- cost-decomposition diagnostic for sparse_kernel (from
// marking_two_tier_poc.cu), built in direct response to Artur's question: since the CPU code
// gets true 128/64 division in a single `divq` instruction (see prime_sieve_engine_v4.c's
// udiv128_rem) while GPU has no equivalent hardware instruction and must synthesize the same
// result from several operations, WHERE exactly does the GPU sparse-tier per-prime cost go --
// dispatch overhead, the phase computation itself, or the atomic write? The FULL-mode two-tier
// result already showed the tier split alone bought a 3.43x speedup (580.386s -> 169.179s), but
// GPU marking-only TOTAL is still ~1.49x slower than production's CPU sieve step alone
// (169.179s vs 113.352s) -- this diagnostic decomposes the ~1.4 ns/prime sparse-tier cost to
// show exactly which piece to attack next, following the same three-variant methodology already
// used (and already valuable) in marking_overhead_poc.cu.
//
// Four kernel variants, run back-to-back on the SAME uploaded sample of real sparse-tier primes
// (sampled from libprimesieve in the real floor-25 sparse range [combined_size, l_final)):
//   1. null_kernel          -- index check only. Pure dispatch/launch overhead.
//   2. phase_only_old_kernel -- phase_mod computed via the ORIGINAL (unconditional-division)
//                                formula, no write. null + phase(old).
//   3. phase_only_new_kernel -- phase_mod computed via the FIXED (skip-wasted-division-when-
//                                distance_hi<p) formula, no write. null + phase(new) -- the
//                                pairwise difference (old - new) isolates exactly how much the
//                                2026-08-28 fast-path fix saved per prime.
//   4. sparse_kernel_full    -- phase(new) + the actual conditional atomic write, i.e. the real
//                                sparse_kernel from marking_two_tier_poc.cu. null + phase(new) +
//                                write -- the difference from variant 3 isolates the write cost.
//
// N_REPEATS=5 per variant, minimum reported (standard microbenchmark practice, matches
// marking_overhead_poc.cu's own methodology).

#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <chrono>
#include <cuda_runtime.h>
#include <primesieve.h>

#define SPARSE_THREADS 256
#define N_REPEATS 5

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

__device__ __forceinline__ unsigned long long phase_mod_old(unsigned long long distance_hi,
                                                              unsigned long long distance_lo,
                                                              unsigned long long p) {
    unsigned long long hi_r = distance_hi % p;  // unconditional -- the pre-fix version
    unsigned long long lo_r = distance_lo % p;
    unsigned long long two64_mod_p = (0xFFFFFFFFFFFFFFFFULL % p) + 1ULL;
    two64_mod_p -= (two64_mod_p >= p) ? p : 0ULL;
    unsigned long long term = mulmod64(hi_r, two64_mod_p, p);
    unsigned long long result = term + lo_r;
    result -= (result >= p) ? p : 0ULL;
    return result;
}

__device__ __forceinline__ unsigned long long phase_mod_new(unsigned long long distance_hi,
                                                              unsigned long long distance_lo,
                                                              unsigned long long p) {
    unsigned long long hi_r = (distance_hi < p) ? distance_hi : (distance_hi % p);  // fixed
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

__global__ void null_kernel(const unsigned long long* __restrict__ primes, int n_primes) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= n_primes) return;
    volatile unsigned long long touch = primes[idx];  // force the load, nothing else
    (void)touch;
}

__global__ void phase_only_old_kernel(const unsigned long long* __restrict__ primes,
                                       int n_primes, unsigned long long distance_hi,
                                       unsigned long long distance_lo) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= n_primes) return;
    unsigned long long p = primes[idx];
    volatile unsigned long long r = phase_mod_old(distance_hi, distance_lo, p);
    (void)r;
}

__global__ void phase_only_new_kernel(const unsigned long long* __restrict__ primes,
                                       int n_primes, unsigned long long distance_hi,
                                       unsigned long long distance_lo) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= n_primes) return;
    unsigned long long p = primes[idx];
    volatile unsigned long long r = phase_mod_new(distance_hi, distance_lo, p);
    (void)r;
}

__global__ void sparse_kernel_full(const unsigned long long* __restrict__ primes, int n_primes,
                                    unsigned long long distance_hi, unsigned long long distance_lo,
                                    unsigned long long combined_size,
                                    unsigned char* __restrict__ out_bits) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= n_primes) return;
    unsigned long long p = primes[idx];
    unsigned long long rem = phase_mod_new(distance_hi, distance_lo, p);
    unsigned long long start_pos = (rem == 0) ? 0ULL : (p - rem);
    if (distance_hi == 0) {
        unsigned long long sum = distance_lo + start_pos;
        bool overflowed = sum < distance_lo;
        if (!overflowed && sum <= p) {
            start_pos += p;
        }
    }
    if (start_pos < combined_size) {
        atomic_or_bit(out_bits, start_pos);
    }
}

#define CUDA_CHECK(call) do { \
    cudaError_t _e = (call); \
    if (_e != cudaSuccess) { \
        fprintf(stderr, "CUDA error at %s:%d: %s\n", __FILE__, __LINE__, cudaGetErrorString(_e)); \
        exit(1); \
    } \
} while (0)

static double now_ms() {
    return std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

// Input file: uint64_t n_primes, uint64_t distance_hi, uint64_t distance_lo,
//             uint64_t combined_size, uint64_t sparse_lo, uint64_t sparse_hi
// (primes are generated HERE, on the GPU host side, sampled evenly from [sparse_lo, sparse_hi)
// via libprimesieve, so the caller doesn't need to ship a huge primes file for this diagnostic)
//
// Output file: 4x double (min ms across N_REPEATS for null/phase_old/phase_new/full),
//              uint64_t actual_n_primes_used
int main(int argc, char** argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s <input.bin> <output.bin>\n", argv[0]);
        return 1;
    }
    FILE* fin = fopen(argv[1], "rb");
    if (!fin) { fprintf(stderr, "cannot open input %s\n", argv[1]); return 1; }
    uint64_t n_primes_req, distance_hi, distance_lo, combined_size, sparse_lo, sparse_hi;
    if (fread(&n_primes_req, 8, 1, fin) != 1 || fread(&distance_hi, 8, 1, fin) != 1 ||
        fread(&distance_lo, 8, 1, fin) != 1 || fread(&combined_size, 8, 1, fin) != 1 ||
        fread(&sparse_lo, 8, 1, fin) != 1 || fread(&sparse_hi, 8, 1, fin) != 1) {
        fprintf(stderr, "bad input header\n"); return 1;
    }
    fclose(fin);

    unsigned long long* h_primes =
        (unsigned long long*)malloc(sizeof(unsigned long long) * n_primes_req);
    uint64_t n = 0;
    primesieve_iterator it;
    primesieve_init(&it);
    primesieve_jump_to(&it, sparse_lo, sparse_hi);
    while (n < n_primes_req) {
        uint64_t p_val = primesieve_next_prime(&it);
        if (p_val >= sparse_hi) break;
        h_primes[n++] = p_val;
    }
    primesieve_free_iterator(&it);
    fprintf(stderr, "[cpu] sampled %llu real primes from [%llu, %llu) for the diagnostic\n",
            (unsigned long long)n, (unsigned long long)sparse_lo, (unsigned long long)sparse_hi);
    if (n == 0) { fprintf(stderr, "no primes sampled -- aborting\n"); return 1; }

    unsigned long long* d_primes;
    unsigned char* d_bits;
    uint64_t combined_bytes = ((combined_size + 7) / 8 + 3) / 4 * 4;
    CUDA_CHECK(cudaMalloc(&d_primes, sizeof(unsigned long long) * n));
    CUDA_CHECK(cudaMemcpy(d_primes, h_primes, sizeof(unsigned long long) * n,
                           cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMalloc(&d_bits, combined_bytes));
    CUDA_CHECK(cudaMemset(d_bits, 0, combined_bytes));

    int grid = (int)((n + SPARSE_THREADS - 1) / SPARSE_THREADS);

    double best_null = 1e18, best_phase_old = 1e18, best_phase_new = 1e18, best_full = 1e18;
    cudaEvent_t e0, e1;
    CUDA_CHECK(cudaEventCreate(&e0));
    CUDA_CHECK(cudaEventCreate(&e1));

    for (int rep = 0; rep < N_REPEATS; rep++) {
        CUDA_CHECK(cudaEventRecord(e0));
        null_kernel<<<grid, SPARSE_THREADS>>>(d_primes, (int)n);
        CUDA_CHECK(cudaEventRecord(e1));
        CUDA_CHECK(cudaGetLastError());
        CUDA_CHECK(cudaEventSynchronize(e1));
        float ms; CUDA_CHECK(cudaEventElapsedTime(&ms, e0, e1));
        if (ms < best_null) best_null = ms;
    }
    for (int rep = 0; rep < N_REPEATS; rep++) {
        CUDA_CHECK(cudaEventRecord(e0));
        phase_only_old_kernel<<<grid, SPARSE_THREADS>>>(d_primes, (int)n, distance_hi,
                                                          distance_lo);
        CUDA_CHECK(cudaEventRecord(e1));
        CUDA_CHECK(cudaGetLastError());
        CUDA_CHECK(cudaEventSynchronize(e1));
        float ms; CUDA_CHECK(cudaEventElapsedTime(&ms, e0, e1));
        if (ms < best_phase_old) best_phase_old = ms;
    }
    for (int rep = 0; rep < N_REPEATS; rep++) {
        CUDA_CHECK(cudaEventRecord(e0));
        phase_only_new_kernel<<<grid, SPARSE_THREADS>>>(d_primes, (int)n, distance_hi,
                                                          distance_lo);
        CUDA_CHECK(cudaEventRecord(e1));
        CUDA_CHECK(cudaGetLastError());
        CUDA_CHECK(cudaEventSynchronize(e1));
        float ms; CUDA_CHECK(cudaEventElapsedTime(&ms, e0, e1));
        if (ms < best_phase_new) best_phase_new = ms;
    }
    for (int rep = 0; rep < N_REPEATS; rep++) {
        CUDA_CHECK(cudaMemset(d_bits, 0, combined_bytes));
        CUDA_CHECK(cudaEventRecord(e0));
        sparse_kernel_full<<<grid, SPARSE_THREADS>>>(d_primes, (int)n, distance_hi, distance_lo,
                                                       combined_size, d_bits);
        CUDA_CHECK(cudaEventRecord(e1));
        CUDA_CHECK(cudaGetLastError());
        CUDA_CHECK(cudaEventSynchronize(e1));
        float ms; CUDA_CHECK(cudaEventElapsedTime(&ms, e0, e1));
        if (ms < best_full) best_full = ms;
    }

    fprintf(stderr, "[gpu] n_primes=%llu  null=%.3fms  phase_old=%.3fms  phase_new=%.3fms  "
                     "full=%.3fms\n",
            (unsigned long long)n, best_null, best_phase_old, best_phase_new, best_full);
    fprintf(stderr, "[gpu] decomposition: dispatch_overhead=%.3fms  "
                     "phase_cost_old=%.3fms  phase_cost_new=%.3fms  "
                     "fast_path_fix_saved=%.3fms  write_cost=%.3fms\n",
            best_null, best_phase_old - best_null, best_phase_new - best_null,
            best_phase_old - best_phase_new, best_full - best_phase_new);

    FILE* fout = fopen(argv[2], "wb");
    if (!fout) { fprintf(stderr, "cannot open output %s\n", argv[2]); return 1; }
    double null_d = best_null, phase_old_d = best_phase_old, phase_new_d = best_phase_new,
           full_d = best_full;
    fwrite(&null_d, sizeof(double), 1, fout);
    fwrite(&phase_old_d, sizeof(double), 1, fout);
    fwrite(&phase_new_d, sizeof(double), 1, fout);
    fwrite(&full_d, sizeof(double), 1, fout);
    fwrite(&n, 8, 1, fout);
    fclose(fout);

    free(h_primes);
    cudaFree(d_primes);
    cudaFree(d_bits);
    return 0;
}
