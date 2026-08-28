// phase_mod_resident_poc.cu -- second-step proof of concept, testing the fix for what
// phase_mod_poc.cu's own real-hardware run (RTX 5070, 2026-08-28) found: kernel-only
// throughput was enormous (5-6.6 billion primes/s) but wall time was ~97% PCIe transfer,
// because that first PoC re-uploads the full sieving-prime array on every single call. This
// version uploads the sieving primes ONCE, then computes phases for MANY windows against
// that same resident array -- testing whether that's what actually needed to happen for this
// approach to pay off, per Artur's own reasoning (2026-08-28: sieving primes barely change
// between windows -- L_final grows far slower than the windows do, see
// prime_sieve_v4.py's own comment on that -- so re-uploading them per window is pure waste).
//
// SCALE CHOSEN: floor 25, window width 10^7, 1000 windows -- 1000 * 10^7 = 10^10 numbers,
// matching the real "10 billion numbers in 3 minutes" floor-25 benchmark scale discussed
// 2026-08-27/28, so the total GPU time this reports is directly comparable to that ~113s
// CPU sieve time (see benchmark_report_20260816_120741.pdf, floor 25 row) and ~62s write
// time from the SAME real run, not an arbitrary made-up size.
//
// WHY NOT MATERIALIZE THE FULL (windows x primes) PHASE ARRAY: 1000 windows * 20,000,000
// primes * 8 bytes = 160 GB -- doesn't fit in the RTX 5070's 12 GB VRAM, and wouldn't be
// useful to fully retrieve even if it did (in a real engine, each phase value is consumed
// immediately to mark a bit in that window's output bitmap, never kept around as a raw
// number). So this kernel does NOT write a full phase array to global memory at all in the
// common case. Instead:
//   - Every thread's phase is folded into a per-window CHECKSUM (block-level shared-memory
//     reduction, one atomicAdd per block instead of one per thread -- avoids serializing
//     20,000,000 threads on one address) -- unsigned 64-bit wraparound sum, exactly
//     reproducible on the Python side for verification (see phase_mod_resident_poc.py).
//     Only 1000 * 8 bytes = 8 KB comes back to the host for this.
//   - A SMALL number of windows (see CAPTURE_WINDOWS in the .py driver -- default: first,
//     middle, last) ALSO get their full phase array written out, purely so the host can do
//     an exact, zero-tolerance comparison against Python's ground truth for at least a few
//     complete windows, not just trust the checksum blindly.
//
// This file reuses phase_mod_gpu()/mulmod64() verbatim from phase_mod_poc.cu (copy, not
// #include, to keep each PoC file independently buildable/readable -- see that file's own
// header for the full derivation and the 2026-08-28 real-hardware validation of this exact
// math; nothing about the arithmetic changes here, only how many windows/how the output is
// collected).

#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cuda_runtime.h>

#define PHASE_MOD_MAX_SAFE_PRIME_BITS 50   // see phase_mod_poc.cu's own "VALIDATED RANGE"
#define REDUCE_THREADS 256                 // block size; REDUCE_THREADS must be a power of 2
                                            // for the shared-memory reduction loop below

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

// phase_kernel_resident: 2D grid -- blockIdx.y selects the window, blockIdx.x/threadIdx.x
// selects the prime within that window. `primes` is uploaded ONCE by the host driver and
// reused for every window in this single launch (that's the entire point of this PoC).
//
// capture_slot[w] is -1 for most windows (checksum only) or a small non-negative index into
// full_output for the handful of spot-check windows (see module header).
__global__ void phase_kernel_resident(const unsigned long long* __restrict__ primes,
                                       int n_primes,
                                       const unsigned long long* __restrict__ distance_hi,
                                       const unsigned long long* __restrict__ distance_lo,
                                       unsigned long long* __restrict__ window_checksum,
                                       const int* __restrict__ capture_slot,
                                       unsigned long long* __restrict__ full_output) {
    int w = blockIdx.y;
    int i = blockIdx.x * blockDim.x + threadIdx.x;

    // No early return before __syncthreads() below -- every thread in the block must reach
    // that barrier, including threads whose i is out of range for the last (partial) block
    // of a window's prime range. Out-of-range threads contribute 0 to the reduction, which
    // is correct and harmless for the checksum.
    unsigned long long phase = 0ULL;
    if (i < n_primes) {
        unsigned long long p = primes[i];
        phase = phase_mod_gpu(distance_hi[w], distance_lo[w], p);

        int slot = capture_slot[w];
        if (slot >= 0) {
            full_output[(long long)slot * (long long)n_primes + (long long)i] = phase;
        }
    }

    __shared__ unsigned long long sdata[REDUCE_THREADS];
    sdata[threadIdx.x] = phase;
    __syncthreads();
    for (int s = REDUCE_THREADS / 2; s > 0; s >>= 1) {
        if (threadIdx.x < s) sdata[threadIdx.x] += sdata[threadIdx.x + s];
        __syncthreads();
    }
    if (threadIdx.x == 0) {
        atomicAdd(&window_checksum[w], sdata[0]);   // one atomic per BLOCK, not per thread --
                                                      // several blocks may cover one window's
                                                      // primes when n_primes > REDUCE_THREADS,
                                                      // so this still needs to be atomic, just
                                                      // far less contended than per-thread would be
    }
}

// ---------------------------------------------------------------------------------------------
// Host driver. Input/output binary formats are documented in phase_mod_resident_poc.py (the
// counterpart that writes/reads these files) -- kept in sync by hand, this is a PoC not a
// stable interface.
// ---------------------------------------------------------------------------------------------

#define CUDA_CHECK(call) do { \
    cudaError_t _e = (call); \
    if (_e != cudaSuccess) { \
        fprintf(stderr, "CUDA error at %s:%d: %s\n", __FILE__, __LINE__, cudaGetErrorString(_e)); \
        exit(1); \
    } \
} while (0)

int main(int argc, char** argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s <input.bin> <output.bin>\n", argv[0]);
        return 1;
    }

    FILE* fin = fopen(argv[1], "rb");
    if (!fin) { fprintf(stderr, "cannot open input %s\n", argv[1]); return 1; }

    unsigned long long n_primes64, n_windows64, n_capture64;
    if (fread(&n_primes64, 8, 1, fin) != 1) { fprintf(stderr, "bad header\n"); return 1; }
    int n_primes = (int)n_primes64;
    unsigned long long* h_primes = (unsigned long long*)malloc(sizeof(unsigned long long) * n_primes);
    if (fread(h_primes, 8, n_primes, fin) != (size_t)n_primes) {
        fprintf(stderr, "malformed input: expected %d primes\n", n_primes); return 1;
    }

    unsigned long long safe_limit = 1ULL << PHASE_MOD_MAX_SAFE_PRIME_BITS;
    for (int i = 0; i < n_primes; i++) {
        if (h_primes[i] >= safe_limit) {
            fprintf(stderr, "REFUSING: prime[%d]=%llu >= 2^%d safe limit\n",
                    i, h_primes[i], PHASE_MOD_MAX_SAFE_PRIME_BITS);
            return 1;
        }
    }

    if (fread(&n_windows64, 8, 1, fin) != 1) { fprintf(stderr, "bad header\n"); return 1; }
    int n_windows = (int)n_windows64;
    unsigned long long* h_dist_hi = (unsigned long long*)malloc(sizeof(unsigned long long) * n_windows);
    unsigned long long* h_dist_lo = (unsigned long long*)malloc(sizeof(unsigned long long) * n_windows);
    if (fread(h_dist_hi, 8, n_windows, fin) != (size_t)n_windows ||
        fread(h_dist_lo, 8, n_windows, fin) != (size_t)n_windows) {
        fprintf(stderr, "malformed input: expected %d window distances\n", n_windows); return 1;
    }

    if (fread(&n_capture64, 8, 1, fin) != 1) { fprintf(stderr, "bad header\n"); return 1; }
    int n_capture = (int)n_capture64;
    int* h_capture_slot = (int*)malloc(sizeof(int) * n_windows);
    for (int w = 0; w < n_windows; w++) h_capture_slot[w] = -1;
    for (int c = 0; c < n_capture; c++) {
        long long window_idx64;
        if (fread(&window_idx64, 8, 1, fin) != 1) { fprintf(stderr, "bad capture list\n"); return 1; }
        int window_idx = (int)window_idx64;
        if (window_idx < 0 || window_idx >= n_windows) {
            fprintf(stderr, "capture window index %d out of range\n", window_idx); return 1;
        }
        h_capture_slot[window_idx] = c;
    }
    fclose(fin);

    fprintf(stderr, "[gpu] n_primes=%d n_windows=%d n_capture=%d "
                     "(full-output size for captured windows: %.1f MB)\n",
            n_primes, n_windows, n_capture,
            (double)n_capture * n_primes * 8.0 / 1e6);

    cudaEvent_t t0, t_primes_up, t_dist_up, t_kernel_done, t_checksum_down, t_full_down;
    CUDA_CHECK(cudaEventCreate(&t0));
    CUDA_CHECK(cudaEventCreate(&t_primes_up));
    CUDA_CHECK(cudaEventCreate(&t_dist_up));
    CUDA_CHECK(cudaEventCreate(&t_kernel_done));
    CUDA_CHECK(cudaEventCreate(&t_checksum_down));
    CUDA_CHECK(cudaEventCreate(&t_full_down));

    unsigned long long *d_primes, *d_dist_hi, *d_dist_lo, *d_checksum, *d_full_output;
    int* d_capture_slot;
    CUDA_CHECK(cudaMalloc(&d_primes, sizeof(unsigned long long) * n_primes));
    CUDA_CHECK(cudaMalloc(&d_dist_hi, sizeof(unsigned long long) * n_windows));
    CUDA_CHECK(cudaMalloc(&d_dist_lo, sizeof(unsigned long long) * n_windows));
    CUDA_CHECK(cudaMalloc(&d_checksum, sizeof(unsigned long long) * n_windows));
    CUDA_CHECK(cudaMalloc(&d_capture_slot, sizeof(int) * n_windows));
    CUDA_CHECK(cudaMalloc(&d_full_output, sizeof(unsigned long long) * (long long)n_capture * n_primes));

    CUDA_CHECK(cudaEventRecord(t0));

    // The ONE upload this PoC is specifically testing the cost/benefit of amortizing: primes
    // go up once, then get reused by every window in the kernel launch below.
    CUDA_CHECK(cudaMemcpy(d_primes, h_primes, sizeof(unsigned long long) * n_primes,
                           cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaEventRecord(t_primes_up));

    CUDA_CHECK(cudaMemcpy(d_dist_hi, h_dist_hi, sizeof(unsigned long long) * n_windows,
                           cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_dist_lo, h_dist_lo, sizeof(unsigned long long) * n_windows,
                           cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemcpy(d_capture_slot, h_capture_slot, sizeof(int) * n_windows,
                           cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemset(d_checksum, 0, sizeof(unsigned long long) * n_windows));
    CUDA_CHECK(cudaEventRecord(t_dist_up));

    dim3 block(REDUCE_THREADS);
    dim3 grid((n_primes + REDUCE_THREADS - 1) / REDUCE_THREADS, n_windows);
    phase_kernel_resident<<<grid, block>>>(d_primes, n_primes, d_dist_hi, d_dist_lo,
                                            d_checksum, d_capture_slot, d_full_output);
    CUDA_CHECK(cudaEventRecord(t_kernel_done));
    CUDA_CHECK(cudaGetLastError());

    unsigned long long* h_checksum = (unsigned long long*)malloc(sizeof(unsigned long long) * n_windows);
    CUDA_CHECK(cudaMemcpy(h_checksum, d_checksum, sizeof(unsigned long long) * n_windows,
                           cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaEventRecord(t_checksum_down));

    unsigned long long* h_full_output = NULL;
    if (n_capture > 0) {
        h_full_output = (unsigned long long*)malloc(
            sizeof(unsigned long long) * (long long)n_capture * n_primes);
        CUDA_CHECK(cudaMemcpy(h_full_output, d_full_output,
                               sizeof(unsigned long long) * (long long)n_capture * n_primes,
                               cudaMemcpyDeviceToHost));
    }
    CUDA_CHECK(cudaEventRecord(t_full_down));
    CUDA_CHECK(cudaEventSynchronize(t_full_down));

    float ms_primes_up, ms_dist_up, ms_kernel, ms_checksum_down, ms_full_down, ms_total;
    CUDA_CHECK(cudaEventElapsedTime(&ms_primes_up, t0, t_primes_up));
    CUDA_CHECK(cudaEventElapsedTime(&ms_dist_up, t_primes_up, t_dist_up));
    CUDA_CHECK(cudaEventElapsedTime(&ms_kernel, t_dist_up, t_kernel_done));
    CUDA_CHECK(cudaEventElapsedTime(&ms_checksum_down, t_kernel_done, t_checksum_down));
    CUDA_CHECK(cudaEventElapsedTime(&ms_full_down, t_checksum_down, t_full_down));
    CUDA_CHECK(cudaEventElapsedTime(&ms_total, t0, t_full_down));

    fprintf(stderr,
        "[gpu] primes_upload=%.6fs (ONE-TIME)  distances_upload=%.6fs  kernel=%.6fs  "
        "checksum_download=%.6fs  full_output_download=%.6fs  TOTAL=%.6fs\n"
        "[gpu] amortized per-window (excluding one-time primes upload): %.6fs/window "
        "(%d windows)\n",
        ms_primes_up/1000.0, ms_dist_up/1000.0, ms_kernel/1000.0,
        ms_checksum_down/1000.0, ms_full_down/1000.0, ms_total/1000.0,
        (ms_total - ms_primes_up) / 1000.0 / n_windows, n_windows);

    FILE* fout = fopen(argv[2], "wb");
    if (!fout) { fprintf(stderr, "cannot open output %s\n", argv[2]); return 1; }
    fwrite(&n_windows64, 8, 1, fout);
    fwrite(h_checksum, 8, n_windows, fout);
    fwrite(&n_capture64, 8, 1, fout);
    if (n_capture > 0) fwrite(h_full_output, 8, (size_t)n_capture * n_primes, fout);
    double d_primes_up = ms_primes_up/1000.0, d_dist_up_s = ms_dist_up/1000.0,
           d_kernel = ms_kernel/1000.0, d_checksum_down = ms_checksum_down/1000.0,
           d_full_down = ms_full_down/1000.0, d_total = ms_total/1000.0;
    fwrite(&d_primes_up, sizeof(double), 1, fout);
    fwrite(&d_dist_up_s, sizeof(double), 1, fout);
    fwrite(&d_kernel, sizeof(double), 1, fout);
    fwrite(&d_checksum_down, sizeof(double), 1, fout);
    fwrite(&d_full_down, sizeof(double), 1, fout);
    fwrite(&d_total, sizeof(double), 1, fout);
    fclose(fout);

    free(h_primes); free(h_dist_hi); free(h_dist_lo); free(h_capture_slot); free(h_checksum);
    if (h_full_output) free(h_full_output);
    cudaFree(d_primes); cudaFree(d_dist_hi); cudaFree(d_dist_lo);
    cudaFree(d_checksum); cudaFree(d_capture_slot); cudaFree(d_full_output);
    return 0;
}
