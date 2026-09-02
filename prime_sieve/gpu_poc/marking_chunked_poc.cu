// marking_chunked_poc.cu -- fifth-step proof of concept: combines the two pieces built so far
// into one real, VRAM-bounded, single-process pipeline:
//   1. phase_mod_chunked_poc.py's insight -- stream sieving primes through libprimesieve's
//      primesieve_iterator in bounded chunks, since a real floor-25 batch's full sieving-prime
//      range ([2, L_final), L_final = isqrt(distance+combined_size) ~ 3*10^12) has ~1.1*10^11
//      primes -- ~880 GB at 8 bytes each, nowhere close to fitting in 12 GB VRAM.
//   2. marking_poc.cu's real, FIXED marking_kernel -- actual stride-marking into a bit-packed
//      output buffer, not just a phase checksum.
//
// WHY A NEW FILE INSTEAD OF REUSING phase_mod_chunked_poc.py's approach directly: that script
// processed each chunk as a SEPARATE process invocation (fresh CUDA context per chunk),
// acceptable when the only output is a small scalar checksum to sum across chunks. Marking's
// output is a bit-packed buffer that every chunk's primes must OR into the SAME positions --
// chunks are not independent, they accumulate into one shared result. So this file keeps ONE
// persistent CUDA context and ONE resident `d_bits` output buffer for the entire run, looping
// over chunks internally (primes buffer is the only thing re-uploaded per chunk; small and
// fixed-size, `chunk_size` primes at a time, regardless of how many total chunks run) --
// exactly mirroring how a real GPU-accelerated engine would need to work, and directly
// addressing the "each chunk is a separate process invocation" simplification that
// phase_mod_chunked_poc.py's own docstring flagged as a known gap.
//
// This is also, deliberately, C++/CUDA linking libprimesieve DIRECTLY (same library, same
// primesieve_iterator/primesieve_jump_to/primesieve_next_prime calls, same semantics as
// prime_sieve_engine_v4.c's own generate_and_sieve_segment_bits() and iterator_chunk_gen.c) --
// prime generation happens on the HOST side of this same binary, not shuttled through Python
// and a separate .so, since at real scale (hundreds of millions to billions of primes) even a
// binary-file round-trip through Python would be real, avoidable overhead.
//
// Correctness claim being tested: splitting a sieving-prime range into N independent GPU
// kernel launches, each cooperatively marking multiples of its own chunk's primes into a
// SHARED, persistent, resident output buffer via the same atomicOr-based atomic_or_bit() as
// marking_poc.cu, produces IDENTICAL output to processing the whole range in one shot. This
// must be true mathematically (marking is a pure union of independent per-prime bit sets,
// order-independent, and CUDA's default stream serializes these launches so there is no
// cross-chunk race), but is verified here byte-for-byte against the real, unmodified
// prime_sieve_engine_v4.c's generate_and_sieve_segment_bits() called ONCE over the full range
// -- see marking_chunked_poc.py's EXACT mode.

#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <chrono>
#include <cuda_runtime.h>
#include <primesieve.h>

#define PHASE_MOD_MAX_SAFE_PRIME_BITS 50
#define MARK_THREADS 256

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

// marking_kernel -- kept IN SYNC with marking_poc.cu's fixed version (thread 0 computes
// phase+guard once, broadcasts via shared memory -- see that file's header comment for the
// full rationale and the real-hardware numbers that motivated it). Called once per CHUNK here,
// each call covering only that chunk's primes, all writing into the SAME persistent d_bits
// buffer across the whole run (see module header).
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
//   uint64_t l_final        (sieving-prime range is [2, l_final) -- same convention as
//                             generate_and_sieve_segment_bits()'s own `stop` parameter)
//   uint64_t distance_hi
//   uint64_t distance_lo
//   uint64_t combined_size
//   uint64_t chunk_size     (max primes uploaded to the GPU per kernel launch -- this, not
//                             l_final's true prime count, is what bounds VRAM usage)
//
// Output file format:
//   uint64_t combined_bytes
//   uint8_t  bits[combined_bytes]
//   uint64_t total_primes_processed
//   uint64_t n_chunks
//   double   t_generate_total_seconds   (CPU-side primesieve_next_prime time, all chunks)
//   double   t_upload_total_seconds     (GPU upload time, all chunks)
//   double   t_kernel_total_seconds     (GPU kernel time, all chunks)
//   double   t_download_seconds         (single download at the end)
//   double   t_total_seconds
// ---------------------------------------------------------------------------------------------

#define CUDA_CHECK(call) do { \
    cudaError_t _e = (call); \
    if (_e != cudaSuccess) { \
        fprintf(stderr, "CUDA error at %s:%d: %s\n", __FILE__, __LINE__, cudaGetErrorString(_e)); \
        exit(1); \
    } \
} while (0)

static double now_seconds() {
    return std::chrono::duration<double>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

int main(int argc, char** argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s <input.bin> <output.bin>\n", argv[0]);
        return 1;
    }
    FILE* fin = fopen(argv[1], "rb");
    if (!fin) { fprintf(stderr, "cannot open input %s\n", argv[1]); return 1; }
    uint64_t l_final, distance_hi, distance_lo, combined_size, chunk_size;
    if (fread(&l_final, 8, 1, fin) != 1 || fread(&distance_hi, 8, 1, fin) != 1 ||
        fread(&distance_lo, 8, 1, fin) != 1 || fread(&combined_size, 8, 1, fin) != 1 ||
        fread(&chunk_size, 8, 1, fin) != 1) {
        fprintf(stderr, "bad input header\n"); return 1;
    }
    fclose(fin);

    double t_start = now_seconds();

    uint64_t combined_bytes = (combined_size + 7) / 8;
    combined_bytes = ((combined_bytes + 3) / 4) * 4;

    unsigned char* d_bits;
    unsigned long long* d_primes;
    CUDA_CHECK(cudaMalloc(&d_bits, combined_bytes));
    CUDA_CHECK(cudaMemset(d_bits, 0, combined_bytes));
    CUDA_CHECK(cudaMalloc(&d_primes, sizeof(unsigned long long) * chunk_size));

    size_t free_bytes, total_bytes;
    CUDA_CHECK(cudaMemGetInfo(&free_bytes, &total_bytes));
    fprintf(stderr, "[gpu] allocated once, resident for the whole run: "
                     "d_bits=%.3f MB  d_primes(chunk buffer)=%.3f MB  "
                     "(GPU free=%.1f MB / total=%.1f MB right after allocation -- this does "
                     "NOT grow as more chunks are processed)\n",
            combined_bytes / 1e6, (sizeof(unsigned long long) * chunk_size) / 1e6,
            free_bytes / 1e6, total_bytes / 1e6);

    unsigned long long* h_primes =
        (unsigned long long*)malloc(sizeof(unsigned long long) * chunk_size);

    primesieve_iterator it;
    primesieve_init(&it);
    primesieve_jump_to(&it, 2, l_final);

    unsigned long long safe_limit = 1ULL << PHASE_MOD_MAX_SAFE_PRIME_BITS;
    uint64_t total_primes = 0, n_chunks = 0;
    double t_generate_total = 0.0, t_upload_total = 0.0, t_kernel_total = 0.0;

    cudaEvent_t ke0, ke1;
    CUDA_CHECK(cudaEventCreate(&ke0));
    CUDA_CHECK(cudaEventCreate(&ke1));

    bool exhausted = false;
    while (!exhausted) {
        double tg0 = now_seconds();
        uint64_t n = 0;
        while (n < chunk_size) {
            uint64_t p_val = primesieve_next_prime(&it);
            if (p_val >= l_final) { exhausted = true; break; }
            if (p_val >= safe_limit) {
                fprintf(stderr, "REFUSING: prime %llu >= 2^%d safe limit\n",
                        (unsigned long long)p_val, PHASE_MOD_MAX_SAFE_PRIME_BITS);
                return 1;
            }
            h_primes[n++] = p_val;
        }
        t_generate_total += now_seconds() - tg0;

        if (n == 0) break;

        double tu0 = now_seconds();
        CUDA_CHECK(cudaMemcpy(d_primes, h_primes, sizeof(unsigned long long) * n,
                               cudaMemcpyHostToDevice));
        t_upload_total += now_seconds() - tu0;

        CUDA_CHECK(cudaEventRecord(ke0));
        marking_kernel<<<(int)n, MARK_THREADS>>>(d_primes, (int)n, distance_hi, distance_lo,
                                                  combined_size, d_bits);
        CUDA_CHECK(cudaEventRecord(ke1));
        CUDA_CHECK(cudaGetLastError());
        CUDA_CHECK(cudaEventSynchronize(ke1));
        float ms;
        CUDA_CHECK(cudaEventElapsedTime(&ms, ke0, ke1));
        t_kernel_total += ms / 1000.0;

        total_primes += n;
        n_chunks++;
        if (n_chunks % 20 == 0 || n < chunk_size) {
            fprintf(stderr, "[gpu] chunk %llu: %llu primes (running total %llu primes, "
                             "%.3fs generate, %.3fs upload, %.3fs kernel so far)\n",
                    (unsigned long long)n_chunks, (unsigned long long)n,
                    (unsigned long long)total_primes, t_generate_total, t_upload_total,
                    t_kernel_total);
        }
    }

    int err = it.is_error;
    primesieve_free_iterator(&it);
    if (err) {
        fprintf(stderr, "primesieve reported an internal error\n");
        return 1;
    }

    unsigned char* h_bits = (unsigned char*)malloc(combined_bytes);
    double td0 = now_seconds();
    CUDA_CHECK(cudaMemcpy(h_bits, d_bits, combined_bytes, cudaMemcpyDeviceToHost));
    double t_download = now_seconds() - td0;

    double t_total = now_seconds() - t_start;
    fprintf(stderr, "[gpu] DONE: %llu primes in %llu chunks -- "
                     "generate=%.3fs upload=%.3fs kernel=%.3fs download=%.3fs TOTAL=%.3fs\n",
            (unsigned long long)total_primes, (unsigned long long)n_chunks,
            t_generate_total, t_upload_total, t_kernel_total, t_download, t_total);

    FILE* fout = fopen(argv[2], "wb");
    if (!fout) { fprintf(stderr, "cannot open output %s\n", argv[2]); return 1; }
    fwrite(&combined_bytes, 8, 1, fout);
    fwrite(h_bits, 1, combined_bytes, fout);
    fwrite(&total_primes, 8, 1, fout);
    fwrite(&n_chunks, 8, 1, fout);
    fwrite(&t_generate_total, sizeof(double), 1, fout);
    fwrite(&t_upload_total, sizeof(double), 1, fout);
    fwrite(&t_kernel_total, sizeof(double), 1, fout);
    fwrite(&t_download, sizeof(double), 1, fout);
    fwrite(&t_total, sizeof(double), 1, fout);
    fclose(fout);

    free(h_primes); free(h_bits);
    cudaFree(d_primes); cudaFree(d_bits);
    return 0;
}
