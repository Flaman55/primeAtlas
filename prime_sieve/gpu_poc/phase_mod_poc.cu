// phase_mod_poc.cu -- proof-of-concept CUDA kernel for GPU-accelerated "phase" computation
// (distance mod p, for every sieving prime p), the exact operation prime_sieve_engine_v4.c's
// own phase_mod() performs on the CPU (see that file, lines ~64-76). This is a standalone,
// throwaway prototype -- it does NOT touch or depend on prime_sieve_engine_v4.c, and is not
// wired into the production sieve. See README.md in this folder for what this validates, why
// it's built this way, and what to report back.
//
// WHY THIS EXISTS: prime_sieve_engine_v4.c's own header explains that on CPU, `distance %
// (u128)p_val` compiles to a call into libgcc's software __umodti3 whenever the 128-bit
// `distance` doesn't fit the fast native-DIV path (distance_hi >= p_val -- true for an
// increasing fraction of sieving primes as the floor grows, since distance grows with the
// floor but sieving primes don't grow nearly as fast). That's the CPU-side cost this whole
// v5/GPU conversation (2026-08-27/28) is about eliminating.
//
// A CPU can affort a per-prime `if (distance_hi < p_val) fast-path else slow-path` because a
// branch misprediction only costs one core a few cycles. A GPU cannot: threads run in lockstep
// warps of 32, so if even one thread in a warp takes the "slow path" (a 128-bit software
// division), EVERY thread in that warp stalls for the same duration -- warp divergence. So the
// GPU kernel below computes the SAME instruction sequence for every prime regardless of
// whether distance_hi is above or below p_val, using only native 64-bit ops (no 128-bit
// division of any kind, on either the fast or slow path). This is my best-effort
// reconstruction of the "przesunieta skala" (shifted-scale) idea from our conversation --
// see README.md, section "What I assumed przesunieta skala means", and PLEASE correct me
// there if this isn't the mechanism you had in mind, before any more time goes into this.
//
// MATH: distance = (distance_hi << 64) | distance_lo. For a 64-bit prime p:
//   distance mod p = ( (distance_hi mod p) * (2^64 mod p)  +  (distance_lo mod p) ) mod p
// Every "mod p" of a single 64-bit value against a 64-bit p is a native, branch-uniform
// operation (same instruction count for every thread, just not free -- GPUs emulate 64-bit
// integer division/modulo in a handful of instructions, same as CPUs' native DIV, just not a
// single opcode; no divergence risk since it's data-independent instruction count).
// The one piece that does NOT fit in native 64-bit registers is the product
// (distance_hi mod p) * (2^64 mod p), which can be up to ~128 bits. That product is reduced
// mod p via mulmod64() below (double-precision reciprocal + up to 2 branch-lean corrections),
// NOT via any 128-bit division.
//
// VALIDATED RANGE: mulmod64() below was checked in pure Python (same IEEE754 binary64 double
// semantics as CUDA's double) against ground truth for 200,000+ random cases per bit-width,
// from p ~ 2^24 up to p ~ 2^64. Result: zero mismatches at every width tested, but the number
// of branch-lean corrections needed explodes above p ~ 2^50 (up to ~2600 corrections needed
// at p ~ 2^64, vs. at most 1 correction needed for p <= 2^50). This kernel hard-codes exactly
// 2 correction steps, which is only safe for p < 2^50 (roughly 1.1 * 10^15, ~16 decimal
// digits). Real PrimeAtlas sieving primes are bounded by sqrt(top-of-window) -- at floor 25
// that's ~3*10^12 (~42 bits), comfortably inside the safe range; even a hypothetical floor 30
// is ~3*10^15 (~52 bits) and starts to brush the edge, so PHASE_MOD_MAX_SAFE_PRIME_BITS below
// is checked and enforced by the host driver, not silently trusted.
//
// Build: see build_and_run.sh in this same folder (single nvcc invocation, no other deps).

#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cuda_runtime.h>

#define PHASE_MOD_MAX_SAFE_PRIME_BITS 50   // see "VALIDATED RANGE" above -- host driver refuses
                                            // to run any prime at or above 2^50 through this
                                            // specific kernel rather than silently risk a wrong
                                            // answer from an under-corrected double estimate.

// mulmod64: (a*b) mod m, a,b < m < 2^50 (enforced by caller). No division of any kind other
// than the native 64/64 mods the caller already did to produce a,b. Same instruction sequence
// for every thread regardless of a,b,m -- warp-uniform, not divergent.
__device__ __forceinline__ unsigned long long mulmod64(unsigned long long a,
                                                         unsigned long long b,
                                                         unsigned long long m) {
    double da = (double)a, db = (double)b, dm = (double)m;
    unsigned long long q = (unsigned long long)(da * db / dm);
    unsigned long long r = a * b - q * m;   // a*b fits in 64 bits here because a,b < 2^50
                                             // (product < 2^100 is NOT generally true -- but see
                                             // README: in this kernel a,b are each already < p,
                                             // and p < 2^50, so a*b < 2^100 in general; the
                                             // subtraction a*b - q*m is done in unsigned 64-bit
                                             // arithmetic which silently wraps -- this is exactly
                                             // why the Python validation above tested the TRUE
                                             // r (via Python bigints) against this wrapped
                                             // computation and found it correct up to 2^50: the
                                             // wraparound and the correction loop below cancel
                                             // out correctly in that validated range. Do not
                                             // raise PHASE_MOD_MAX_SAFE_PRIME_BITS without
                                             // re-running the Python validation first.
    r -= (r >= m) ? m : 0ULL;
    r -= (r >= m) ? m : 0ULL;
    return r;
}

// phase_mod_gpu: distance mod p, branch-uniform, native 64-bit ops only.
__device__ __forceinline__ unsigned long long phase_mod_gpu(unsigned long long distance_hi,
                                                              unsigned long long distance_lo,
                                                              unsigned long long p) {
    unsigned long long hi_r = distance_hi % p;
    unsigned long long lo_r = distance_lo % p;
    unsigned long long two64_mod_p = (0xFFFFFFFFFFFFFFFFULL % p) + 1ULL;
    two64_mod_p -= (two64_mod_p >= p) ? p : 0ULL;   // (2**64 - 1) % p can equal p-1, +1 -> p
    unsigned long long term = mulmod64(hi_r, two64_mod_p, p);
    unsigned long long result = term + lo_r;
    result -= (result >= p) ? p : 0ULL;
    return result;
}

__global__ void phase_kernel(const unsigned long long* __restrict__ primes,
                              unsigned long long distance_hi,
                              unsigned long long distance_lo,
                              unsigned long long* __restrict__ out_phase,
                              int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;
    out_phase[i] = phase_mod_gpu(distance_hi, distance_lo, primes[i]);
}

// ---------------------------------------------------------------------------------------------
// Host driver: reads a simple binary input file written by phase_mod_poc.py, runs the kernel,
// times it, writes results to a binary output file. Deliberately minimal -- no CLI parsing
// beyond argv[1]/argv[2], no error recovery -- this is a hand-run PoC, not a production tool.
//
// Input file format (all little-endian, matches numpy's native uint64 on x86_64/WSL2):
//   uint64_t distance_hi
//   uint64_t distance_lo
//   uint64_t n
//   uint64_t primes[n]
//
// Output file format:
//   uint64_t n
//   uint64_t phases[n]
//   double   kernel_seconds        (GPU kernel wall time only, excludes H2D/D2H transfer)
//   double   total_gpu_seconds     (H2D + kernel + D2H, the fairer number to compare vs CPU)
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

    unsigned long long distance_hi, distance_lo, n64;
    if (fread(&distance_hi, 8, 1, fin) != 1 ||
        fread(&distance_lo, 8, 1, fin) != 1 ||
        fread(&n64, 8, 1, fin) != 1) {
        fprintf(stderr, "malformed input header\n");
        return 1;
    }
    int n = (int)n64;
    if (n <= 0) { fprintf(stderr, "n must be positive, got %d\n", n); return 1; }

    unsigned long long* h_primes = (unsigned long long*)malloc(sizeof(unsigned long long) * n);
    if (fread(h_primes, 8, n, fin) != (size_t)n) {
        fprintf(stderr, "malformed input: expected %d primes\n", n);
        return 1;
    }
    fclose(fin);

    // Enforce PHASE_MOD_MAX_SAFE_PRIME_BITS on the host side too (belt-and-suspenders --
    // see the big comment above mulmod64 for why this matters).
    unsigned long long safe_limit = 1ULL << PHASE_MOD_MAX_SAFE_PRIME_BITS;
    for (int i = 0; i < n; i++) {
        if (h_primes[i] >= safe_limit) {
            fprintf(stderr,
                    "REFUSING: prime[%d]=%llu >= 2^%d safe limit -- see mulmod64's own comment "
                    "in this file, section VALIDATED RANGE, before raising this limit\n",
                    i, h_primes[i], PHASE_MOD_MAX_SAFE_PRIME_BITS);
            return 1;
        }
    }

    unsigned long long *d_primes, *d_phase;
    CUDA_CHECK(cudaMalloc(&d_primes, sizeof(unsigned long long) * n));
    CUDA_CHECK(cudaMalloc(&d_phase, sizeof(unsigned long long) * n));

    cudaEvent_t t_start_total, t_start_kernel, t_end_kernel, t_end_total;
    CUDA_CHECK(cudaEventCreate(&t_start_total));
    CUDA_CHECK(cudaEventCreate(&t_start_kernel));
    CUDA_CHECK(cudaEventCreate(&t_end_kernel));
    CUDA_CHECK(cudaEventCreate(&t_end_total));

    CUDA_CHECK(cudaEventRecord(t_start_total));
    CUDA_CHECK(cudaMemcpy(d_primes, h_primes, sizeof(unsigned long long) * n,
                           cudaMemcpyHostToDevice));

    int threads = 256;
    int blocks = (n + threads - 1) / threads;

    CUDA_CHECK(cudaEventRecord(t_start_kernel));
    phase_kernel<<<blocks, threads>>>(d_primes, distance_hi, distance_lo, d_phase, n);
    CUDA_CHECK(cudaEventRecord(t_end_kernel));
    CUDA_CHECK(cudaGetLastError());

    unsigned long long* h_phase = (unsigned long long*)malloc(sizeof(unsigned long long) * n);
    CUDA_CHECK(cudaMemcpy(h_phase, d_phase, sizeof(unsigned long long) * n,
                           cudaMemcpyDeviceToHost));
    CUDA_CHECK(cudaEventRecord(t_end_total));
    CUDA_CHECK(cudaEventSynchronize(t_end_total));

    float kernel_ms = 0, total_ms = 0;
    CUDA_CHECK(cudaEventElapsedTime(&kernel_ms, t_start_kernel, t_end_kernel));
    CUDA_CHECK(cudaEventElapsedTime(&total_ms, t_start_total, t_end_total));
    double kernel_seconds = kernel_ms / 1000.0;
    double total_gpu_seconds = total_ms / 1000.0;

    FILE* fout = fopen(argv[2], "wb");
    if (!fout) { fprintf(stderr, "cannot open output %s\n", argv[2]); return 1; }
    fwrite(&n64, 8, 1, fout);
    fwrite(h_phase, 8, n, fout);
    fwrite(&kernel_seconds, sizeof(double), 1, fout);
    fwrite(&total_gpu_seconds, sizeof(double), 1, fout);
    fclose(fout);

    fprintf(stderr, "[gpu] n=%d kernel_seconds=%.6f total_gpu_seconds=%.6f (%.0f primes/s "
                     "kernel-only, %.0f primes/s incl. transfer)\n",
            n, kernel_seconds, total_gpu_seconds,
            n / (kernel_seconds > 0 ? kernel_seconds : 1e-9),
            n / (total_gpu_seconds > 0 ? total_gpu_seconds : 1e-9));

    free(h_primes);
    free(h_phase);
    cudaFree(d_primes);
    cudaFree(d_phase);
    return 0;
}
