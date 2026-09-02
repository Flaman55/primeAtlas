// marking_two_tier_poc.cu -- seventh-step proof of concept, built directly off reading the REAL
// production engine's own source after marking_chunked_parallel_poc's real-hardware FULL-mode
// result (TOTAL=580.386s, only 2.27x faster than the fully-serial version, still ~3.3x slower
// than production's 176.018s) showed that `generate_wall` and `gpu_wall` converged to nearly
// the SAME value (579.1s vs 579.0s) -- meaning the pipeline had become purely GPU-kernel-bound,
// and further pipelining/parallel-generation work could not help. Artur's explicit direction:
// keep verifying rather than stop at a hypothesis -- his direction was to exhaust the topic
// fully: if there is still room to verify something, it should be verified rather than left as
// an educated guess. He also asked whether this was still testing the right thing (GPU offloading a
// real CPU-heavy task) -- confirmed by reading prime_sieve_engine_v4.c directly: production's
// real algorithm is EXACTLY "iterate each sieving prime once, mark into one shared buffer
// spanning the whole batch" (generate_and_sieve_segment_bits_atomic(), called with prime-range
// slices across 24 workers) -- the identical algorithm shape this whole PoC series has been
// implementing on GPU. So yes, still on-topic; the question was WHY GPU loses at that identical
// algorithm, not whether it's the right algorithm.
//
// THE FINDING (in prime_sieve_engine_v4.c's generate_and_sieve_segment_bits(), around line 104):
//
//     if (p_val >= window_m) {
//         out_dense_bits[start_pos >> 3] |= (1u << (start_pos & 7));      // O(1): one write
//     } else {
//         uint64_t pos = start_pos;
//         while (pos < window_m) {                                        // loop: many writes
//             out_dense_bits[pos >> 3] |= (1u << (pos & 7));
//             pos += p_val;
//         }
//     }
//
// Production ALREADY splits primes into two cost tiers. At real floor-25 scale, combined_size
// (window_m) = 10^10 and l_final ~= 3.16*10^12 -- so primes >= 10^10 (the "sparse" tier) are
// ~99.6% of the ~113.8 BILLION total sieving primes (only ~4.5*10^8 fall below 10^10, in the
// "dense" tier). For that 99.6% majority, production does a single branch + single array write
// per prime, in a tight CPU loop -- essentially free per item.
//
// This GPU codebase's marking_kernel (unchanged since marking_poc.cu) launches ONE FULL
// 256-THREAD COOPERATIVE BLOCK PER PRIME, regardless of tier -- for the sparse-tier majority,
// that is a full block launch + shared-memory broadcast + syncthreads barrier to do what is,
// mathematically, at most a single conditional write. The measured numbers support this as the
// real bottleneck: marking_overhead_poc's own post-fix measurement was ~4.69 ns/block
// (93.8ms / 20,000,000 primes at combined_size=10^8). At floor-25 scale, ~113.8*10^9 blocks *
// 4.69 ns/block ~= 534s -- matching the measured kernel/gpu_wall time (576-579s) almost exactly.
// The kernel's cost tracks BLOCK COUNT (== prime count), not actual marking work done.
//
// THE FIX, mirroring production's own branch exactly: two kernels.
//   - marking_kernel (dense, unchanged) -- one block per prime, MARK_THREADS-wide cooperative
//     striding -- used ONLY for primes p < combined_size (the tier that can have multiple hits
//     and genuinely benefits from parallel striding).
//   - sparse_kernel (new) -- one THREAD per prime, flat 1D grid (no shared memory, no
//     syncthreads, no cooperation needed) -- used for primes p >= combined_size (the tier where
//     each prime does at most one conditional write). This amortizes block-launch overhead
//     across SPARSE_THREADS=256 primes per block instead of paying a full block launch per
//     prime, directly targeting the measured bottleneck.
//
// Host structure: two sequential PHASES over the same persistent d_bits buffer and the same
// bounded producer/consumer pipeline (parallel CPU generation + double-buffered GPU streams,
// unchanged from marking_chunked_parallel_poc.cu) -- phase 1 covers [2, combined_size) with the
// dense kernel, phase 2 covers [combined_size, l_final) with the sparse kernel. The split point
// is mathematically exact: a prime p has at most one multiple in any window of width
// combined_size iff p >= combined_size, so this partition changes nothing about correctness,
// only which kernel processes which primes -- verified byte-for-byte against the real,
// unmodified prime_sieve_engine_v4.c, same as every prior step in this series.

#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <chrono>
#include <thread>
#include <mutex>
#include <condition_variable>
#include <queue>
#include <vector>
#include <atomic>
#include <algorithm>
#include <cuda_runtime.h>
#include <primesieve.h>

#define PHASE_MOD_MAX_SAFE_PRIME_BITS 50
#define MARK_THREADS 256
#define SPARSE_THREADS 256

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

// FIX (2026-08-28, in response to Artur asking where the GPU kernel still adds overhead vs the
// CPU code): prime_sieve_engine_v4.c's own phase_mod() has a fast path -- `if (distance_hi <
// p_val) return udiv128_rem(...)` -- a SINGLE x86 `divq` instruction for the whole 128/64
// division whenever the high half is smaller than the divisor (guaranteed here: distance_hi is
// tiny -- e.g. 542101 at floor 25 -- while every sieving prime is far larger). This GPU version
// was unconditionally computing `distance_hi % p` even though, in that same common case, the
// division is WASTED: the answer is just distance_hi unchanged. GPU has no equivalent single-
// instruction 128/64 divide (unlike x86), so it cannot match the CPU's fast path exactly, but it
// CAN stop paying for a division whose result it already knows -- skip it when distance_hi < p,
// matching the CPU's own condition exactly, changing nothing about correctness.
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

// dense kernel -- byte-identical to every prior file's fixed marking_kernel. Used ONLY for
// primes p < combined_size (can have multiple hits in the window).
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

// sparse kernel -- NEW. One thread per prime, flat 1D grid, no shared memory / no syncthreads
// (no cooperation needed). Used ONLY for primes p >= combined_size, where the window can
// contain AT MOST ONE multiple of p -- mirrors prime_sieve_engine_v4.c's own `if (p_val >=
// window_m)` branch exactly (single conditional write, no loop).
__global__ void sparse_kernel(const unsigned long long* __restrict__ primes, int n_primes,
                               unsigned long long distance_hi, unsigned long long distance_lo,
                               unsigned long long combined_size,
                               unsigned char* __restrict__ out_bits) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= n_primes) return;
    unsigned long long p = primes[idx];

    unsigned long long rem = phase_mod_gpu(distance_hi, distance_lo, p);
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

// ---------------------------------------------------------------------------------------------
// Host driver.
//
// Input file format (little-endian):
//   uint64_t l_final
//   uint64_t distance_hi
//   uint64_t distance_lo
//   uint64_t combined_size    (also the dense/sparse tier boundary -- see header comment)
//   uint64_t chunk_size
//   uint64_t num_gen_threads
//
// Output file format:
//   uint64_t combined_bytes
//   uint8_t  bits[combined_bytes]
//   uint64_t total_primes
//   uint64_t n_dense_primes
//   uint64_t n_sparse_primes
//   uint64_t n_dense_chunks
//   uint64_t n_sparse_chunks
//   uint64_t n_gen_threads_used
//   double   t_dense_generate_wall
//   double   t_dense_gpu_wall
//   double   t_sparse_generate_wall
//   double   t_sparse_gpu_wall
//   double   t_download
//   double   t_total
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

// ---- shared producer/consumer state (same bounded-queue design as marking_chunked_parallel_
// poc.cu -- see that file's header for the real-hardware OOM this fixes) --------------------

struct Batch {
    std::vector<unsigned long long> primes;
};

#define MAX_QUEUE_BATCHES 8

static std::mutex g_queue_mutex;
static std::condition_variable g_queue_cv;
static std::queue<Batch> g_queue;
static std::atomic<int> g_active_generators(0);
static std::atomic<bool> g_error(false);
static unsigned long long g_safe_limit = 0;

static bool push_batch_blocking(Batch&& b) {
    std::unique_lock<std::mutex> lock(g_queue_mutex);
    g_queue_cv.wait(lock, [] {
        return g_queue.size() < MAX_QUEUE_BATCHES || g_error.load(std::memory_order_relaxed);
    });
    if (g_error.load(std::memory_order_relaxed)) return false;
    g_queue.push(std::move(b));
    lock.unlock();
    g_queue_cv.notify_all();
    return true;
}

static void generator_thread_func(uint64_t sub_start, uint64_t sub_end, uint64_t chunk_size) {
    primesieve_iterator it;
    primesieve_init(&it);
    primesieve_jump_to(&it, sub_start, sub_end);

    Batch batch;
    batch.primes.reserve(chunk_size);

    while (!g_error.load(std::memory_order_relaxed)) {
        uint64_t p_val = primesieve_next_prime(&it);
        if (p_val >= sub_end) break;
        if (p_val >= g_safe_limit) {
            fprintf(stderr, "REFUSING: prime %llu >= 2^%d safe limit\n",
                    (unsigned long long)p_val, PHASE_MOD_MAX_SAFE_PRIME_BITS);
            g_error.store(true, std::memory_order_relaxed);
            break;
        }
        batch.primes.push_back(p_val);
        if (batch.primes.size() >= chunk_size) {
            if (!push_batch_blocking(std::move(batch))) break;
            batch = Batch();
            batch.primes.reserve(chunk_size);
        }
    }
    if (!batch.primes.empty() && !g_error.load(std::memory_order_relaxed)) {
        push_batch_blocking(std::move(batch));
    }
    if (it.is_error) {
        fprintf(stderr, "primesieve reported an internal error on one generator thread\n");
        g_error.store(true, std::memory_order_relaxed);
    }
    primesieve_free_iterator(&it);

    g_active_generators.fetch_sub(1, std::memory_order_relaxed);
    g_queue_cv.notify_all();
}

// One phase: generate+consume all primes in [phase_lo, phase_hi) using either the dense or the
// sparse kernel. Reuses the persistent d_bits buffer and the double-buffered device/pinned
// primes buffers + streams passed in. Returns via out-params.
static void run_phase(const char* phase_name, bool use_sparse, uint64_t phase_lo,
                       uint64_t phase_hi, uint64_t chunk_size, uint64_t num_gen_threads_req,
                       unsigned long long distance_hi, unsigned long long distance_lo,
                       unsigned long long combined_size, unsigned char* d_bits,
                       unsigned long long* d_primes[2], unsigned long long* h_pinned[2],
                       cudaStream_t stream[2], uint64_t* out_primes, uint64_t* out_chunks,
                       uint64_t* out_gen_threads_used, double* out_generate_wall,
                       double* out_gpu_wall) {
    *out_primes = 0; *out_chunks = 0; *out_generate_wall = 0.0; *out_gpu_wall = 0.0;

    uint64_t range_lo = phase_lo, range_hi = (phase_hi > phase_lo) ? phase_hi : phase_lo;
    uint64_t total_width = range_hi - range_lo;
    if (total_width == 0) {
        fprintf(stderr, "[%s] empty range [%llu, %llu) -- skipping\n", phase_name,
                (unsigned long long)phase_lo, (unsigned long long)phase_hi);
        *out_gen_threads_used = 0;
        return;
    }

    uint64_t n_gen_threads = num_gen_threads_req;
    if (n_gen_threads < 1) n_gen_threads = 1;
    if (n_gen_threads > total_width) n_gen_threads = total_width;
    *out_gen_threads_used = n_gen_threads;

    fprintf(stderr, "[%s] range=[%llu, %llu)  width=%llu  using %llu generator thread(s), "
                     "kernel=%s\n",
            phase_name, (unsigned long long)range_lo, (unsigned long long)range_hi,
            (unsigned long long)total_width, (unsigned long long)n_gen_threads,
            use_sparse ? "sparse (1 thread/prime)" : "dense (1 block/prime)");

    std::vector<uint64_t> boundaries(n_gen_threads + 1);
    boundaries[0] = range_lo;
    for (uint64_t i = 1; i < n_gen_threads; i++) {
        boundaries[i] = range_lo + (total_width * i) / n_gen_threads;
    }
    boundaries[n_gen_threads] = range_hi;

    g_active_generators.store((int)n_gen_threads, std::memory_order_relaxed);
    double t_gen_start = now_seconds();
    std::vector<std::thread> gen_threads;
    gen_threads.reserve(n_gen_threads);
    for (uint64_t i = 0; i < n_gen_threads; i++) {
        gen_threads.emplace_back(generator_thread_func, boundaries[i], boundaries[i + 1],
                                  chunk_size);
    }

    uint64_t total_primes = 0, n_chunks = 0;
    double t_gpu_start = -1.0;
    double t_phase_start = now_seconds();

    while (true) {
        Batch batch;
        {
            std::unique_lock<std::mutex> lock(g_queue_mutex);
            g_queue_cv.wait(lock, [] {
                return !g_queue.empty() || g_active_generators.load(std::memory_order_relaxed) == 0;
            });
            if (g_queue.empty() && g_active_generators.load(std::memory_order_relaxed) == 0) {
                break;
            }
            if (g_queue.empty()) continue;
            batch = std::move(g_queue.front());
            g_queue.pop();
        }
        g_queue_cv.notify_all();
        uint64_t n = batch.primes.size();
        if (n == 0) continue;

        if (t_gpu_start < 0.0) t_gpu_start = now_seconds();

        int idx = (int)(n_chunks % 2);
        CUDA_CHECK(cudaStreamSynchronize(stream[idx]));
        memcpy(h_pinned[idx], batch.primes.data(), sizeof(unsigned long long) * n);
        CUDA_CHECK(cudaMemcpyAsync(d_primes[idx], h_pinned[idx], sizeof(unsigned long long) * n,
                                    cudaMemcpyHostToDevice, stream[idx]));
        if (use_sparse) {
            int grid = (int)((n + SPARSE_THREADS - 1) / SPARSE_THREADS);
            sparse_kernel<<<grid, SPARSE_THREADS, 0, stream[idx]>>>(
                d_primes[idx], (int)n, distance_hi, distance_lo, combined_size, d_bits);
        } else {
            marking_kernel<<<(int)n, MARK_THREADS, 0, stream[idx]>>>(
                d_primes[idx], (int)n, distance_hi, distance_lo, combined_size, d_bits);
        }
        CUDA_CHECK(cudaGetLastError());

        total_primes += n;
        n_chunks++;
        if (n_chunks % 50 == 0) {
            fprintf(stderr, "[%s] chunk %llu: running total %llu primes, %.3fs since phase "
                             "start\n",
                    phase_name, (unsigned long long)n_chunks, (unsigned long long)total_primes,
                    now_seconds() - t_phase_start);
        }
    }

    for (auto& t : gen_threads) t.join();
    *out_generate_wall = now_seconds() - t_gen_start;

    CUDA_CHECK(cudaStreamSynchronize(stream[0]));
    CUDA_CHECK(cudaStreamSynchronize(stream[1]));
    *out_gpu_wall = (t_gpu_start >= 0.0) ? (now_seconds() - t_gpu_start) : 0.0;

    *out_primes = total_primes;
    *out_chunks = n_chunks;
    fprintf(stderr, "[%s] DONE: %llu primes in %llu chunks -- generate_wall=%.3fs "
                     "gpu_wall=%.3fs\n",
            phase_name, (unsigned long long)total_primes, (unsigned long long)n_chunks,
            *out_generate_wall, *out_gpu_wall);
}

int main(int argc, char** argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s <input.bin> <output.bin>\n", argv[0]);
        return 1;
    }
    FILE* fin = fopen(argv[1], "rb");
    if (!fin) { fprintf(stderr, "cannot open input %s\n", argv[1]); return 1; }
    uint64_t l_final, distance_hi, distance_lo, combined_size, chunk_size, num_gen_threads_req;
    if (fread(&l_final, 8, 1, fin) != 1 || fread(&distance_hi, 8, 1, fin) != 1 ||
        fread(&distance_lo, 8, 1, fin) != 1 || fread(&combined_size, 8, 1, fin) != 1 ||
        fread(&chunk_size, 8, 1, fin) != 1 || fread(&num_gen_threads_req, 8, 1, fin) != 1) {
        fprintf(stderr, "bad input header\n"); return 1;
    }
    fclose(fin);

    g_safe_limit = 1ULL << PHASE_MOD_MAX_SAFE_PRIME_BITS;

    double t_start = now_seconds();

    uint64_t combined_bytes = (combined_size + 7) / 8;
    combined_bytes = ((combined_bytes + 3) / 4) * 4;

    unsigned char* d_bits;
    CUDA_CHECK(cudaMalloc(&d_bits, combined_bytes));
    CUDA_CHECK(cudaMemset(d_bits, 0, combined_bytes));

    unsigned long long* d_primes[2];
    unsigned long long* h_pinned[2];
    cudaStream_t stream[2];
    for (int i = 0; i < 2; i++) {
        CUDA_CHECK(cudaMalloc(&d_primes[i], sizeof(unsigned long long) * chunk_size));
        CUDA_CHECK(cudaMallocHost(&h_pinned[i], sizeof(unsigned long long) * chunk_size));
        CUDA_CHECK(cudaStreamCreate(&stream[i]));
    }

    size_t free_bytes, total_bytes;
    CUDA_CHECK(cudaMemGetInfo(&free_bytes, &total_bytes));
    fprintf(stderr, "[gpu] allocated once, resident for the whole run: "
                     "d_bits=%.3f MB  d_primes(x2 ping-pong)=%.3f MB  "
                     "(GPU free=%.1f MB / total=%.1f MB right after allocation)\n",
            combined_bytes / 1e6, 2.0 * (sizeof(unsigned long long) * chunk_size) / 1e6,
            free_bytes / 1e6, total_bytes / 1e6);
    fprintf(stderr, "[cpu] bounded producer/consumer queue: max %d batches queued at once "
                     "(~%.2f GB of host RAM at chunk_size=%llu)\n",
            MAX_QUEUE_BATCHES,
            (MAX_QUEUE_BATCHES * (double)(sizeof(unsigned long long) * chunk_size)) / 1e9,
            (unsigned long long)chunk_size);

    // dense/sparse split point == combined_size itself: a prime p has at most one multiple in
    // any window of width combined_size iff p >= combined_size (see header comment).
    uint64_t dense_hi = (combined_size < l_final) ? combined_size : l_final;
    if (dense_hi < 2) dense_hi = 2;
    uint64_t sparse_lo = dense_hi;

    uint64_t n_dense_primes, n_dense_chunks, n_dense_gen_threads_used;
    double t_dense_generate_wall, t_dense_gpu_wall;
    run_phase("dense", false, 2, dense_hi, chunk_size, num_gen_threads_req, distance_hi,
              distance_lo, combined_size, d_bits, d_primes, h_pinned, stream,
              &n_dense_primes, &n_dense_chunks, &n_dense_gen_threads_used,
              &t_dense_generate_wall, &t_dense_gpu_wall);

    uint64_t n_sparse_primes = 0, n_sparse_chunks = 0, n_sparse_gen_threads_used = 0;
    double t_sparse_generate_wall = 0.0, t_sparse_gpu_wall = 0.0;
    if (!g_error.load(std::memory_order_relaxed) && sparse_lo < l_final) {
        run_phase("sparse", true, sparse_lo, l_final, chunk_size, num_gen_threads_req,
                  distance_hi, distance_lo, combined_size, d_bits, d_primes, h_pinned, stream,
                  &n_sparse_primes, &n_sparse_chunks, &n_sparse_gen_threads_used,
                  &t_sparse_generate_wall, &t_sparse_gpu_wall);
    }

    if (g_error.load(std::memory_order_relaxed)) {
        fprintf(stderr, "aborting: a generator thread reported an error (see above)\n");
        return 1;
    }

    uint64_t n_gen_threads_used = n_dense_gen_threads_used > n_sparse_gen_threads_used
                                       ? n_dense_gen_threads_used : n_sparse_gen_threads_used;
    uint64_t total_primes = n_dense_primes + n_sparse_primes;

    unsigned char* h_bits = (unsigned char*)malloc(combined_bytes);
    double td0 = now_seconds();
    CUDA_CHECK(cudaMemcpy(h_bits, d_bits, combined_bytes, cudaMemcpyDeviceToHost));
    double t_download = now_seconds() - td0;

    double t_total = now_seconds() - t_start;
    fprintf(stderr, "[gpu] DONE: %llu primes total (%llu dense + %llu sparse) -- "
                     "dense: gen=%.3fs gpu=%.3fs | sparse: gen=%.3fs gpu=%.3fs | "
                     "download=%.3fs TOTAL=%.3fs\n",
            (unsigned long long)total_primes, (unsigned long long)n_dense_primes,
            (unsigned long long)n_sparse_primes, t_dense_generate_wall, t_dense_gpu_wall,
            t_sparse_generate_wall, t_sparse_gpu_wall, t_download, t_total);

    FILE* fout = fopen(argv[2], "wb");
    if (!fout) { fprintf(stderr, "cannot open output %s\n", argv[2]); return 1; }
    fwrite(&combined_bytes, 8, 1, fout);
    fwrite(h_bits, 1, combined_bytes, fout);
    fwrite(&total_primes, 8, 1, fout);
    fwrite(&n_dense_primes, 8, 1, fout);
    fwrite(&n_sparse_primes, 8, 1, fout);
    fwrite(&n_dense_chunks, 8, 1, fout);
    fwrite(&n_sparse_chunks, 8, 1, fout);
    fwrite(&n_gen_threads_used, 8, 1, fout);
    fwrite(&t_dense_generate_wall, sizeof(double), 1, fout);
    fwrite(&t_dense_gpu_wall, sizeof(double), 1, fout);
    fwrite(&t_sparse_generate_wall, sizeof(double), 1, fout);
    fwrite(&t_sparse_gpu_wall, sizeof(double), 1, fout);
    fwrite(&t_download, sizeof(double), 1, fout);
    fwrite(&t_total, sizeof(double), 1, fout);
    fclose(fout);

    free(h_bits);
    for (int i = 0; i < 2; i++) {
        cudaFree(d_primes[i]);
        cudaFreeHost(h_pinned[i]);
        cudaStreamDestroy(stream[i]);
    }
    cudaFree(d_bits);
    return 0;
}
