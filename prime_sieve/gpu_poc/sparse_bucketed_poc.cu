// sparse_bucketed_poc.cu -- direct follow-up to sparse_overhead_poc's real-hardware result:
// 85.3% of the sparse kernel's cost is the atomic write itself (dispatch=2.6%, phase=12.0%,
// write=85.3%, at n_primes=50,000,000). Every one of ~113.8 billion sparse-tier primes writes
// to an essentially RANDOM position across a 1.25 GB `d_bits` buffer -- far larger than any GPU
// L2 cache, so almost every atomicOr misses cache and pays full DRAM round-trip latency.
// Measured effective throughput (~2.43 billion writes/s * 8 bytes/write ~= 19.4 GB/s) is a small
// fraction of the GPU's real memory bandwidth (RTX 5070: ~600+ GB/s) -- consistent with
// uncoalesced, cache-hostile random access being the bottleneck, not raw bandwidth.
//
// THIS FILE tests a fix: bucket-sort primes' target positions by which SHARD of `d_bits` they
// fall into (shard = a contiguous sub-range of the combined bit-range, small enough to plausibly
// fit in GPU L2 cache) BEFORE writing, so that writes landing in the same shard happen close
// together in the kernel's execution order -- giving the L2 cache a chance to actually hold that
// shard hot across many writes, instead of constantly evicting/reloading essentially-random 4-
// byte words from DRAM. This is the GPU-native analogue of what the CPU gets "for free" from its
// much larger cache relative to its (much lower) thread count.
//
// Pipeline (three kernels + one small host-side prefix sum, per chunk of primes):
//   1. compute_positions_kernel -- phase_mod each prime once (same math as sparse_kernel),
//      store `start_pos` into d_positions[idx] (or a sentinel if out of range), and atomicAdd
//      into a small per-shard counter array (d_bucket_counts, one uint32 per shard -- typically
//      only hundreds to low thousands of shards, trivial to download+scan on the host).
//   2. Host: download d_bucket_counts, compute an exclusive prefix sum -> d_bucket_offsets,
//      upload as the initial d_bucket_cursor (same values, will be atomically incremented as a
//      write index by the next kernel).
//   3. scatter_kernel -- re-reads each prime's precomputed start_pos (no recomputation), and for
//      valid ones, atomicAdd's a slot within its shard's segment of d_sorted_positions, writing
//      its position there. After this kernel, d_sorted_positions is grouped by shard.
//   4. write_kernel -- flat pass over d_sorted_positions (now shard-grouped), doing the actual
//      atomic_or_bit() into d_bits. Consecutive threads/blocks now target the SAME or nearby
//      shard, which is the whole point.
//
// Compared against the existing naive "full" (unsorted, scattered) write from sparse_overhead_
// poc.cu, on the exact same sample of real sparse-tier primes, sweeping a few shard sizes to
// find what actually helps on the real hardware (not assumed from a guessed L2 cache size).

#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <chrono>
#include <vector>
#include <cuda_runtime.h>
#include <primesieve.h>

#define SPARSE_THREADS 256
#define SENTINEL 0xFFFFFFFFFFFFFFFFULL

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
    unsigned long long hi_r = (distance_hi < p) ? distance_hi : (distance_hi % p);
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

static __device__ __forceinline__ unsigned long long compute_start_pos(
        unsigned long long p, unsigned long long distance_hi, unsigned long long distance_lo) {
    unsigned long long rem = phase_mod_gpu(distance_hi, distance_lo, p);
    unsigned long long start_pos = (rem == 0) ? 0ULL : (p - rem);
    if (distance_hi == 0) {
        unsigned long long sum = distance_lo + start_pos;
        bool overflowed = sum < distance_lo;
        if (!overflowed && sum <= p) {
            start_pos += p;
        }
    }
    return start_pos;
}

// -------- baseline: naive scattered write (same as sparse_kernel_full in sparse_overhead_poc) --

__global__ void naive_write_kernel(const unsigned long long* __restrict__ primes, int n_primes,
                                    unsigned long long distance_hi, unsigned long long distance_lo,
                                    unsigned long long combined_size,
                                    unsigned char* __restrict__ out_bits) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= n_primes) return;
    unsigned long long start_pos = compute_start_pos(primes[idx], distance_hi, distance_lo);
    if (start_pos < combined_size) {
        atomic_or_bit(out_bits, start_pos);
    }
}

// -------- bucketed pipeline --------

__global__ void compute_positions_kernel(const unsigned long long* __restrict__ primes,
                                          int n_primes, unsigned long long distance_hi,
                                          unsigned long long distance_lo,
                                          unsigned long long combined_size,
                                          unsigned long long shard_size,
                                          unsigned long long* __restrict__ d_positions,
                                          unsigned int* __restrict__ d_bucket_counts) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= n_primes) return;
    unsigned long long start_pos = compute_start_pos(primes[idx], distance_hi, distance_lo);
    if (start_pos < combined_size) {
        d_positions[idx] = start_pos;
        unsigned long long bucket = start_pos / shard_size;
        atomicAdd(&d_bucket_counts[bucket], 1u);
    } else {
        d_positions[idx] = SENTINEL;
    }
}

__global__ void scatter_kernel(const unsigned long long* __restrict__ d_positions, int n_primes,
                                unsigned long long shard_size,
                                unsigned int* __restrict__ d_bucket_cursor,
                                unsigned long long* __restrict__ d_sorted_positions) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= n_primes) return;
    unsigned long long pos = d_positions[idx];
    if (pos == SENTINEL) return;
    unsigned long long bucket = pos / shard_size;
    unsigned int slot = atomicAdd(&d_bucket_cursor[bucket], 1u);
    d_sorted_positions[slot] = pos;
}

__global__ void write_sorted_kernel(const unsigned long long* __restrict__ d_sorted_positions,
                                     int n_valid, unsigned char* __restrict__ out_bits) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= n_valid) return;
    atomic_or_bit(out_bits, d_sorted_positions[idx]);
}

#define CUDA_CHECK(call) do { \
    cudaError_t _e = (call); \
    if (_e != cudaSuccess) { \
        fprintf(stderr, "CUDA error at %s:%d: %s\n", __FILE__, __LINE__, cudaGetErrorString(_e)); \
        exit(1); \
    } \
} while (0)

static float time_kernel_ms(cudaEvent_t e0, cudaEvent_t e1) {
    float ms;
    CUDA_CHECK(cudaEventElapsedTime(&ms, e0, e1));
    return ms;
}

// Input file: uint64 n_primes_req, distance_hi, distance_lo, combined_size, sparse_lo,
//             sparse_hi, n_shard_sizes; then n_shard_sizes x uint64 shard_size (in BITS).
// Output file: double t_naive_full (min over N_REPEATS);
//              then n_shard_sizes x { uint64 shard_size, uint64 n_buckets,
//                                      double t_compute, double t_roundtrip, double t_scatter,
//                                      double t_write, double t_bucketed_total }
//              (t_roundtrip = host-side D2H bucket-counts + prefix sum + H2D offsets; real wall
//              time, included in t_bucketed_total -- an earlier version of this file left it
//              untimed on an unverified "negligible" assumption; it is now measured directly)
int main(int argc, char** argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s <input.bin> <output.bin>\n", argv[0]);
        return 1;
    }
    FILE* fin = fopen(argv[1], "rb");
    if (!fin) { fprintf(stderr, "cannot open input %s\n", argv[1]); return 1; }
    uint64_t n_primes_req, distance_hi, distance_lo, combined_size, sparse_lo, sparse_hi;
    uint64_t n_shard_sizes;
    if (fread(&n_primes_req, 8, 1, fin) != 1 || fread(&distance_hi, 8, 1, fin) != 1 ||
        fread(&distance_lo, 8, 1, fin) != 1 || fread(&combined_size, 8, 1, fin) != 1 ||
        fread(&sparse_lo, 8, 1, fin) != 1 || fread(&sparse_hi, 8, 1, fin) != 1 ||
        fread(&n_shard_sizes, 8, 1, fin) != 1) {
        fprintf(stderr, "bad input header\n"); return 1;
    }
    std::vector<uint64_t> shard_sizes(n_shard_sizes);
    if (fread(shard_sizes.data(), 8, n_shard_sizes, fin) != n_shard_sizes) {
        fprintf(stderr, "bad shard size list\n"); return 1;
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
    fprintf(stderr, "[cpu] sampled %llu real primes from [%llu, %llu)\n",
            (unsigned long long)n, (unsigned long long)sparse_lo, (unsigned long long)sparse_hi);
    if (n == 0) { fprintf(stderr, "no primes sampled -- aborting\n"); return 1; }

    unsigned long long* d_primes;
    unsigned char* d_bits;
    uint64_t combined_bytes = ((combined_size + 7) / 8 + 3) / 4 * 4;
    CUDA_CHECK(cudaMalloc(&d_primes, sizeof(unsigned long long) * n));
    CUDA_CHECK(cudaMemcpy(d_primes, h_primes, sizeof(unsigned long long) * n,
                           cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMalloc(&d_bits, combined_bytes));

    int grid = (int)((n + SPARSE_THREADS - 1) / SPARSE_THREADS);
    cudaEvent_t e0, e1;
    CUDA_CHECK(cudaEventCreate(&e0));
    CUDA_CHECK(cudaEventCreate(&e1));

    const int N_REPEATS = 5;

    // -------- baseline: naive scattered write --------
    double best_naive = 1e18;
    for (int rep = 0; rep < N_REPEATS; rep++) {
        CUDA_CHECK(cudaMemset(d_bits, 0, combined_bytes));
        CUDA_CHECK(cudaEventRecord(e0));
        naive_write_kernel<<<grid, SPARSE_THREADS>>>(d_primes, (int)n, distance_hi, distance_lo,
                                                       combined_size, d_bits);
        CUDA_CHECK(cudaEventRecord(e1));
        CUDA_CHECK(cudaGetLastError());
        CUDA_CHECK(cudaEventSynchronize(e1));
        double ms = time_kernel_ms(e0, e1);
        if (ms < best_naive) best_naive = ms;
    }
    fprintf(stderr, "[gpu] naive scattered write (baseline): %.3f ms\n", best_naive);

    unsigned long long* d_positions;
    CUDA_CHECK(cudaMalloc(&d_positions, sizeof(unsigned long long) * n));

    FILE* fout = fopen(argv[2], "wb");
    if (!fout) { fprintf(stderr, "cannot open output %s\n", argv[2]); return 1; }
    fwrite(&best_naive, sizeof(double), 1, fout);

    for (uint64_t si = 0; si < n_shard_sizes; si++) {
        uint64_t shard_size = shard_sizes[si];
        uint64_t n_buckets = (combined_size + shard_size - 1) / shard_size;

        unsigned int* d_bucket_counts;
        unsigned int* d_bucket_offsets_dev;  // used as the cursor for scatter_kernel
        unsigned long long* d_sorted_positions;
        CUDA_CHECK(cudaMalloc(&d_bucket_counts, sizeof(unsigned int) * n_buckets));
        CUDA_CHECK(cudaMalloc(&d_bucket_offsets_dev, sizeof(unsigned int) * n_buckets));
        CUDA_CHECK(cudaMalloc(&d_sorted_positions, sizeof(unsigned long long) * n));

        double best_compute = 1e18, best_scatter = 1e18, best_write = 1e18;
        double best_roundtrip = 1e18;
        for (int rep = 0; rep < N_REPEATS; rep++) {
            CUDA_CHECK(cudaMemset(d_bucket_counts, 0, sizeof(unsigned int) * n_buckets));

            CUDA_CHECK(cudaEventRecord(e0));
            compute_positions_kernel<<<grid, SPARSE_THREADS>>>(
                d_primes, (int)n, distance_hi, distance_lo, combined_size, shard_size,
                d_positions, d_bucket_counts);
            CUDA_CHECK(cudaEventRecord(e1));
            CUDA_CHECK(cudaGetLastError());
            CUDA_CHECK(cudaEventSynchronize(e1));
            double ms_compute = time_kernel_ms(e0, e1);
            if (ms_compute < best_compute) best_compute = ms_compute;

            // host-side round trip: D2H the (small but not free, grows with n_buckets) bucket
            // counts, exclusive prefix sum on host, H2D the offsets. Earlier draft of this file
            // left this untimed on the theory that it's negligible -- that was an assumption,
            // not a measurement, and this sweep specifically probes SMALLER shards (= MORE
            // buckets), where this cost is least likely to stay negligible. Measure it for real.
            auto rt_start = std::chrono::high_resolution_clock::now();
            std::vector<unsigned int> h_counts(n_buckets), h_offsets(n_buckets);
            CUDA_CHECK(cudaMemcpy(h_counts.data(), d_bucket_counts,
                                   sizeof(unsigned int) * n_buckets, cudaMemcpyDeviceToHost));
            unsigned int running = 0;
            for (uint64_t b = 0; b < n_buckets; b++) {
                h_offsets[b] = running;
                running += h_counts[b];
            }
            uint64_t n_valid = running;
            CUDA_CHECK(cudaMemcpy(d_bucket_offsets_dev, h_offsets.data(),
                                   sizeof(unsigned int) * n_buckets, cudaMemcpyHostToDevice));
            auto rt_end = std::chrono::high_resolution_clock::now();
            double ms_roundtrip =
                std::chrono::duration<double, std::milli>(rt_end - rt_start).count();
            if (ms_roundtrip < best_roundtrip) best_roundtrip = ms_roundtrip;

            CUDA_CHECK(cudaEventRecord(e0));
            scatter_kernel<<<grid, SPARSE_THREADS>>>(d_positions, (int)n, shard_size,
                                                       d_bucket_offsets_dev, d_sorted_positions);
            CUDA_CHECK(cudaEventRecord(e1));
            CUDA_CHECK(cudaGetLastError());
            CUDA_CHECK(cudaEventSynchronize(e1));
            double ms_scatter = time_kernel_ms(e0, e1);
            if (ms_scatter < best_scatter) best_scatter = ms_scatter;

            CUDA_CHECK(cudaMemset(d_bits, 0, combined_bytes));
            int grid_valid = (int)((n_valid + SPARSE_THREADS - 1) / SPARSE_THREADS);
            CUDA_CHECK(cudaEventRecord(e0));
            write_sorted_kernel<<<grid_valid, SPARSE_THREADS>>>(d_sorted_positions, (int)n_valid,
                                                                  d_bits);
            CUDA_CHECK(cudaEventRecord(e1));
            CUDA_CHECK(cudaGetLastError());
            CUDA_CHECK(cudaEventSynchronize(e1));
            double ms_write = time_kernel_ms(e0, e1);
            if (ms_write < best_write) best_write = ms_write;
        }

        double total_bucketed = best_compute + best_roundtrip + best_scatter + best_write;
        fprintf(stderr, "[gpu] shard_size=%llu bits (%.3f MB)  n_buckets=%llu  "
                         "compute=%.3fms  roundtrip=%.3fms  scatter=%.3fms  write=%.3fms  "
                         "TOTAL=%.3fms  (naive baseline=%.3fms, %.2fx if faster)\n",
                (unsigned long long)shard_size, shard_size / 8.0 / 1e6,
                (unsigned long long)n_buckets, best_compute, best_roundtrip, best_scatter,
                best_write, total_bucketed, best_naive, best_naive / total_bucketed);

        fwrite(&shard_size, 8, 1, fout);
        fwrite(&n_buckets, 8, 1, fout);
        fwrite(&best_compute, sizeof(double), 1, fout);
        fwrite(&best_roundtrip, sizeof(double), 1, fout);
        fwrite(&best_scatter, sizeof(double), 1, fout);
        fwrite(&best_write, sizeof(double), 1, fout);
        fwrite(&total_bucketed, sizeof(double), 1, fout);

        cudaFree(d_bucket_counts);
        cudaFree(d_bucket_offsets_dev);
        cudaFree(d_sorted_positions);
    }
    fclose(fout);

    free(h_primes);
    cudaFree(d_primes);
    cudaFree(d_bits);
    cudaFree(d_positions);
    return 0;
}
