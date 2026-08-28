// marking_poc.cu -- fourth-step proof of concept: GPU MARKING (not just phase computation),
// matching prime_sieve_engine_v4.c's generate_and_sieve_segment_bits() exactly in algorithm
// shape: ONE phase computation per sieving prime for the WHOLE combined range (not per
// window -- see phase_mod_resident_poc.cu's own commit history / README.md's "Resident-primes
// follow-up" for why the earlier per-window design was wrong), then striding through every
// multiple of that prime within the combined range, setting a bit for each -- exactly the
// CPU engine's own `pos += p_val` loop, just parallelized.
//
// WHY THIS EXISTS (2026-08-28): every PoC so far only tested phase computation in isolation.
// The actual dominant cost in a real sieve run is the MARKING step (striding through
// multiples), not computing the initial phase. Artur confirmed (2026-08-28) this is the right
// next step: "idź w to" (go for it), after I flagged that GPU marking has a load-balancing
// problem CPU marking doesn't need to worry about in the same way -- see below.
//
// THE LOAD-BALANCING PROBLEM AND ITS FIX: on CPU, ONE core handles one sieving prime's ENTIRE
// stride loop sequentially -- for p=2 across a 10-billion-number range, that's 5 billion loop
// iterations on a single core, but that's fine because ALL 24 CPU workers are doing similarly
// unbalanced work across their own primes, and equal-COST batching (not equal-COUNT) already
// accounts for this (see prime_sieve_v4_1.py's own _build_equal_cost_batches()). On a GPU, if
// I assigned one thread per prime the same way, the thread handling p=2 would take ~5 billion
// sequential iterations while a thread handling a large prime near L_final might do only a
// handful -- a single warp containing both would be catastrophically imbalanced (the whole
// warp stalls for as long as its slowest thread). Fix: ONE BLOCK per prime, with all threads
// in that block cooperatively striding through that SAME prime's multiples (thread t starts at
// start_pos + t*p, steps by blockDim.x*p) -- spreads even p=2's huge workload across up to
// 256 threads, and costs almost nothing extra for large primes with few hits (most threads in
// that block simply do 0-1 iterations and exit).
//
// OUTPUT FORMAT: byte-packed bits, IDENTICAL convention to prime_sieve_engine_v4.c's own
// out_dense_bits (byte = pos>>3, bit = pos&7) -- done via a byte-level atomic OR built on top
// of a 32-bit atomicOr (CUDA has no native 8-bit atomic op), so this kernel's output can be
// compared BYTE-FOR-BYTE directly against the real, unmodified, already-in-production
// prime_sieve_engine_v4.so's own generate_and_sieve_segment_bits() -- see marking_poc.py for
// exactly that comparison. This is the strongest verification available: not "matches my own
// re-derivation" but "matches the actual shipped engine, called unmodified, on the same input".

#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cuda_runtime.h>

#define PHASE_MOD_MAX_SAFE_PRIME_BITS 50   // see phase_mod_poc.cu's own "VALIDATED RANGE"
#define MARK_THREADS 256                   // threads per block == threads cooperating on ONE
                                            // prime's stride loop (see module header)

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

// atomic_or_bit -- sets bit `pos` (byte=pos>>3, bit=pos&7, same convention as
// prime_sieve_engine_v4.c's out_dense_bits) via a byte-level OR built on a 32-bit atomicOr
// (CUDA has no native 8-bit atomic). Assumes bits_buf is 4-byte aligned (true for any
// cudaMalloc'd pointer) and little-endian byte order within each 32-bit word (true on
// CUDA/x86_64/WSL2).
__device__ __forceinline__ void atomic_or_bit(unsigned char* bits_buf, unsigned long long pos) {
    unsigned long long byte_idx = pos >> 3;
    unsigned int bit_mask = 1u << (unsigned int)(pos & 7);
    unsigned long long word_idx = byte_idx >> 2;
    unsigned int byte_in_word = (unsigned int)(byte_idx & 3ULL);
    unsigned int shifted_mask = bit_mask << (byte_in_word * 8);
    unsigned int* word_ptr = ((unsigned int*)bits_buf) + word_idx;
    atomicOr(word_ptr, shifted_mask);
}

// marking_kernel -- one BLOCK per sieving prime (blockIdx.x = prime index). Mirrors
// generate_and_sieve_segment_bits()'s own logic line for line (phase_mod -> start_pos ->
// self-elimination guard -> stride-mark), the only difference being MARK_THREADS-way
// cooperative striding instead of one sequential loop -- see module header.
//
// FIX (2026-08-28, after marking_overhead_poc.cu's real-hardware cost decomposition): the
// original version computed phase_mod_gpu()+guard on EVERY one of the MARK_THREADS=256
// threads in the block, redundantly -- all 256 threads need the SAME start_pos value, only
// one needs to compute it. On real hardware this was measured to be ~96% of total kernel time
// at 20,000,000-prime scale (350.6ms of 364.3ms total), because phase_mod_gpu's mulmod64() is
// not free (a double-precision multiply plus branch-lean corrections), and GPUs execute in
// 32-thread warps -- 256 threads is 8 warps all doing that same non-trivial computation, not
// 1. Fix: only threadIdx.x==0 computes it, stores the result to shared memory, then a single
// __syncthreads() (reached uniformly by all 256 threads -- NOT inside the `threadIdx.x==0`
// branch, which is required for __syncthreads() correctness: every thread in the block must
// reach the same barrier) makes it visible to every thread before the stride loop. This is a
// pure performance restructuring -- the VALUE computed is identical, just computed once and
// broadcast instead of recomputed 256 times, so output is expected to be bit-identical to the
// old version (re-verify via marking_poc.py's EXACT mode on real hardware to confirm).
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

        // Self-elimination guard: matches generate_and_sieve_segment_bits()'s own
        // `if (distance + start_pos <= (u128)p_val) start_pos += p_val;` exactly for the ONLY
        // case that can ever be true -- distance_hi == 0 (at any floor high enough that
        // distance_hi != 0, distance alone already vastly exceeds any sieving prime p <=
        // L_final = isqrt(distance), so the sum can never be <= p_val; the real engine's own
        // u128 compare would likewise always be false there -- see this kernel's own module
        // header comment on why this only matters for small floors).
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

    if (start_pos >= combined_size) return;   // this prime has no hit at all in this range --
                                                // matches the CPU engine's own `continue`; safe
                                                // for every thread in the block to take the
                                                // same branch here since start_pos is now
                                                // identical across all of them (broadcast above)

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
//   uint64_t n_primes
//   uint64_t primes[n_primes]
//   uint64_t distance_hi
//   uint64_t distance_lo
//   uint64_t combined_size
//
// Output file format:
//   uint64_t combined_bytes
//   uint8_t  bits[combined_bytes]      (byte=pos>>3, bit=pos&7 -- same as production)
//   double   primes_upload_seconds
//   double   kernel_seconds
//   double   bits_download_seconds
//   double   total_gpu_seconds
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

    uint64_t n_primes64;
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

    unsigned long long distance_hi, distance_lo, combined_size;
    if (fread(&distance_hi, 8, 1, fin) != 1 || fread(&distance_lo, 8, 1, fin) != 1 ||
        fread(&combined_size, 8, 1, fin) != 1) {
        fprintf(stderr, "bad header (distance/combined_size)\n"); return 1;
    }
    fclose(fin);

    unsigned long long combined_bytes = (combined_size + 7) / 8;
    combined_bytes = ((combined_bytes + 3) / 4) * 4;   // round up to a multiple of 4 -- the
                                                         // byte-level atomicOr trick reads/
                                                         // writes 4-byte words, must not run
                                                         // past the allocation's end

    fprintf(stderr, "[gpu] n_primes=%d combined_size=%llu combined_bytes=%llu (%.3f MB)\n",
            n_primes, combined_size, combined_bytes, combined_bytes / 1e6);

    unsigned long long *d_primes;
    unsigned char *d_bits;
    CUDA_CHECK(cudaMalloc(&d_primes, sizeof(unsigned long long) * n_primes));
    CUDA_CHECK(cudaMalloc(&d_bits, combined_bytes));

    cudaEvent_t t0, t_upload, t_kernel, t_download;
    CUDA_CHECK(cudaEventCreate(&t0));
    CUDA_CHECK(cudaEventCreate(&t_upload));
    CUDA_CHECK(cudaEventCreate(&t_kernel));
    CUDA_CHECK(cudaEventCreate(&t_download));

    CUDA_CHECK(cudaEventRecord(t0));
    CUDA_CHECK(cudaMemcpy(d_primes, h_primes, sizeof(unsigned long long) * n_primes,
                           cudaMemcpyHostToDevice));
    CUDA_CHECK(cudaMemset(d_bits, 0, combined_bytes));
    CUDA_CHECK(cudaEventRecord(t_upload));

    dim3 grid(n_primes);
    dim3 block(MARK_THREADS);
    marking_kernel<<<grid, block>>>(d_primes, n_primes, distance_hi, distance_lo,
                                     combined_size, d_bits);
    CUDA_CHECK(cudaEventRecord(t_kernel));
    CUDA_CHECK(cudaGetLastError());

    unsigned char* h_bits = (unsigned char*)malloc(combined_bytes);
    CUDA_CHECK(cudaMemcpy(h_bits, d_bits, combined_bytes, cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaEventRecord(t_download));
    CUDA_CHECK(cudaEventSynchronize(t_download));

    float ms_upload, ms_kernel, ms_download, ms_total;
    CUDA_CHECK(cudaEventElapsedTime(&ms_upload, t0, t_upload));
    CUDA_CHECK(cudaEventElapsedTime(&ms_kernel, t_upload, t_kernel));
    CUDA_CHECK(cudaEventElapsedTime(&ms_download, t_kernel, t_download));
    CUDA_CHECK(cudaEventElapsedTime(&ms_total, t0, t_download));

    fprintf(stderr, "[gpu] primes_upload=%.6fs  kernel=%.6fs  bits_download=%.6fs  "
                     "TOTAL=%.6fs\n",
            ms_upload/1000.0, ms_kernel/1000.0, ms_download/1000.0, ms_total/1000.0);

    FILE* fout = fopen(argv[2], "wb");
    if (!fout) { fprintf(stderr, "cannot open output %s\n", argv[2]); return 1; }
    fwrite(&combined_bytes, 8, 1, fout);
    fwrite(h_bits, 1, combined_bytes, fout);
    double d_upload = ms_upload/1000.0, d_kernel = ms_kernel/1000.0,
           d_download = ms_download/1000.0, d_total = ms_total/1000.0;
    fwrite(&d_upload, sizeof(double), 1, fout);
    fwrite(&d_kernel, sizeof(double), 1, fout);
    fwrite(&d_download, sizeof(double), 1, fout);
    fwrite(&d_total, sizeof(double), 1, fout);
    fclose(fout);

    free(h_primes); free(h_bits);
    cudaFree(d_primes); cudaFree(d_bits);
    return 0;
}
