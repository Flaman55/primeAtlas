// marking_chunked_parallel_poc.cu -- sixth-step proof of concept, built directly in response to
// marking_chunked_poc's real-hardware FULL-mode result (2026-08-28): TOTAL=1316.729s vs
// production's 176.018s at the same combined_size (~7.5x slower). The breakdown showed
// generate=670.486s (single CPU thread) as the single biggest cost, larger even than
// kernel=576.403s, and generate+kernel were fully SERIALIZED (no overlap at all) -- the previous
// file's host loop does: generate a chunk -> upload it -> run kernel -> generate the next chunk.
//
// Rather than leave that as a "well, if we parallelized generation and pipelined it, maybe..." --
// Artur's explicit direction was to actually finish the attempt and measure the real number, not
// speculate. This file does two concrete, real things instead of one hypothetical thing:
//
//   1. PARALLEL CPU GENERATION: split [2, l_final) into `num_gen_threads` contiguous, disjoint,
//      roughly-equal-WIDTH sub-ranges (equal numeric width, not equal prime count -- primesieve's
//      segmented-sieve cost for a sub-range is driven mainly by the range's width, not by how
//      many primes it happens to contain, so equal-width splitting is a reasonable, honest
//      approximation of equal CPU cost per thread; not perfectly balanced, but far better than
//      one thread doing 100% of the work). Each thread gets its OWN primesieve_iterator (the
//      library supports this -- iterators are independent, thread-safe as long as each thread
//      has its own instance) and pushes primes, in `chunk_size`-sized batches, onto a shared
//      thread-safe queue. Correctness of this split does not depend on primes being produced in
//      numeric order across threads: marking is a pure per-prime, order-independent union into
//      the shared output buffer (same argument already used to justify chunking in the previous
//      file), so interleaved arrival order from N producer threads changes nothing about the
//      final result.
//
//   2. DOUBLE-BUFFERED GPU PIPELINE: the consumer (main thread, owns the persistent CUDA
//      context and the persistent d_bits output buffer) pops batches off the queue and drives
//      TWO device primes-buffers + TWO CUDA streams in a ping-pong pattern, so that chunk i+1's
//      host->device upload can be issued (async, from pinned host memory) while chunk i's kernel
//      is still running on the GPU, instead of strictly serializing upload/kernel/upload/kernel
//      as the previous file did. A given buffer index is only reused once its own stream has
//      been explicitly synchronized, so there is no read-before-write hazard.
//
// This intentionally does NOT attempt full N-way concurrent kernel execution across many
// streams, nor does it try to exactly load-balance generation threads by real prime density --
// both are further optimizations left on the table. What this DOES do is remove the two
// concrete, measured bottlenecks from marking_chunked_poc's FULL-mode run (single-threaded
// generation, and zero overlap between generation/upload/kernel) and report the real resulting
// number, not an estimate.
//
// Correctness claim (same as marking_chunked_poc.cu, re-verified here independently): splitting
// the sieving-prime range across N generator threads AND M pipelined GPU chunks, all OR-ing into
// one shared persistent output buffer, produces IDENTICAL output to processing the whole range
// in one single-threaded shot. Verified via the same byte-for-byte comparison against the real,
// unmodified prime_sieve_engine_v4.c, across cases that specifically exercise multiple generator
// threads (not just multiple GPU chunks) -- see marking_chunked_parallel_poc.py's EXACT mode.

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

// marking_kernel -- byte-identical to marking_poc.cu / marking_chunked_poc.cu's fixed version
// (thread 0 computes phase+guard once, broadcasts via shared memory). Unchanged by this file's
// parallel-generation/pipelining work -- only the HOST-side feeding of this kernel changed.
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
//   uint64_t l_final          (sieving-prime range is [2, l_final))
//   uint64_t distance_hi
//   uint64_t distance_lo
//   uint64_t combined_size
//   uint64_t chunk_size       (max primes per GPU kernel launch / per generator batch)
//   uint64_t num_gen_threads  (requested CPU generator thread count; clamped internally)
//
// Output file format:
//   uint64_t combined_bytes
//   uint8_t  bits[combined_bytes]
//   uint64_t total_primes_processed
//   uint64_t n_chunks
//   uint64_t n_gen_threads_used   (after internal clamping -- what actually ran)
//   double   t_generate_wall      (wall-clock: spawn all generator threads -> last one joins)
//   double   t_gpu_wall           (wall-clock: first chunk dispatched -> final device sync done)
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

// ---- shared producer/consumer state -----------------------------------------------------------

struct Batch {
    std::vector<unsigned long long> primes;
};

// BOUNDED queue depth -- FIX (2026-08-28, after Artur's real-hardware run OOM-killed WSL on the
// first attempt at --mode full): the original version of this file used an UNBOUNDED
// std::queue<Batch>. With 24 producer threads each sieving their own numeric sub-range in
// parallel, generation runs vastly faster than the single GPU consumer can drain it (parallel
// generation at floor-25 scale finishes its ~113.8 billion primes in well under a minute, while
// the GPU consumer processes roughly one 20-million-prime chunk every ~100ms, i.e. ~10 chunks/
// sec -- around 5700 chunks total, so full drain takes ~9.5 minutes). With no backpressure, the
// 24 producers would queue up nearly the ENTIRE ~113.8B-prime range (each batch ~160 MB at
// chunk_size=20,000,000) before the consumer could catch up -- hundreds of GB of host RAM,
// trivially exceeding WSL's memory budget and getting the whole VM killed by the OOM killer,
// exactly what was observed. The fix: cap the queue at MAX_QUEUE_BATCHES batches; producers
// BLOCK (wait on the same condition variable) once the queue is full, instead of piling up
// unboundedly. At chunk_size=20,000,000 (160 MB/batch), 8 batches caps queued RAM at ~1.28 GB
// regardless of how many generator threads are racing ahead -- once the queue fills, producers
// naturally throttle down to the GPU's real consumption rate, which is exactly the intended
// steady-state behavior (the GPU kernel, not generation, is the actual long pole once the queue
// is primed -- see this file's own header comment).
#define MAX_QUEUE_BATCHES 8

static std::mutex g_queue_mutex;
static std::condition_variable g_queue_cv;
static std::queue<Batch> g_queue;
static std::atomic<int> g_active_generators(0);
static std::atomic<bool> g_error(false);
static unsigned long long g_safe_limit = 0;

// Blocks until there is room in the queue (or an error was flagged elsewhere), then pushes.
// Returns false if it gave up because of an error (caller should stop generating).
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

    // double-buffered device primes buffers + pinned host staging buffers + 2 streams, so
    // chunk i+1's upload can be issued while chunk i's kernel is still running.
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

    // -------- split [2, l_final) into num_gen_threads roughly-equal-WIDTH sub-ranges --------
    uint64_t range_lo = 2, range_hi = (l_final > 2) ? l_final : 2;
    uint64_t total_width = range_hi - range_lo;
    unsigned int hw_threads = std::thread::hardware_concurrency();
    uint64_t n_gen_threads = num_gen_threads_req;
    if (n_gen_threads < 1) n_gen_threads = 1;
    if (total_width > 0 && n_gen_threads > total_width) n_gen_threads = total_width;
    if (n_gen_threads < 1) n_gen_threads = 1;

    fprintf(stderr, "[cpu] hardware_concurrency()=%u -- using %llu generator thread(s) "
                     "(requested %llu), splitting [2, %llu) into that many roughly-equal-width "
                     "sub-ranges\n",
            hw_threads, (unsigned long long)n_gen_threads, (unsigned long long)num_gen_threads_req,
            (unsigned long long)l_final);
    fprintf(stderr, "[cpu] bounded producer/consumer queue: max %d batches queued at once "
                     "(~%.2f GB of host RAM at chunk_size=%llu) -- producers BLOCK once full, "
                     "so parallel generation cannot outrun the GPU consumer and exhaust host "
                     "RAM (see this file's header comment for the real-hardware OOM this fixes)\n",
            MAX_QUEUE_BATCHES,
            (MAX_QUEUE_BATCHES * (double)(sizeof(unsigned long long) * chunk_size)) / 1e9,
            (unsigned long long)chunk_size);

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

    // -------- consumer: pop batches, ping-pong upload+kernel across 2 streams --------
    uint64_t total_primes = 0, n_chunks = 0;
    double t_gpu_start = -1.0;
    double t_generate_wall = -1.0;

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
            if (g_queue.empty()) continue;  // spurious wake with nothing ready yet
            batch = std::move(g_queue.front());
            g_queue.pop();
        }
        // wake any producer(s) blocked in push_batch_blocking() waiting for queue space
        g_queue_cv.notify_all();
        uint64_t n = batch.primes.size();
        if (n == 0) continue;

        if (t_gpu_start < 0.0) t_gpu_start = now_seconds();

        int idx = (int)(n_chunks % 2);
        CUDA_CHECK(cudaStreamSynchronize(stream[idx]));  // buffer idx free for reuse
        memcpy(h_pinned[idx], batch.primes.data(), sizeof(unsigned long long) * n);
        CUDA_CHECK(cudaMemcpyAsync(d_primes[idx], h_pinned[idx], sizeof(unsigned long long) * n,
                                    cudaMemcpyHostToDevice, stream[idx]));
        marking_kernel<<<(int)n, MARK_THREADS, 0, stream[idx]>>>(
            d_primes[idx], (int)n, distance_hi, distance_lo, combined_size, d_bits);
        CUDA_CHECK(cudaGetLastError());

        total_primes += n;
        n_chunks++;
        if (n_chunks % 20 == 0) {
            size_t qdepth;
            { std::lock_guard<std::mutex> lock(g_queue_mutex); qdepth = g_queue.size(); }
            fprintf(stderr, "[gpu] chunk %llu: %llu primes (running total %llu primes, "
                             "%.3fs elapsed, queue depth=%zu)\n",
                    (unsigned long long)n_chunks, (unsigned long long)n,
                    (unsigned long long)total_primes, now_seconds() - t_start, qdepth);
        }
    }

    for (auto& t : gen_threads) t.join();
    t_generate_wall = now_seconds() - t_gen_start;

    CUDA_CHECK(cudaStreamSynchronize(stream[0]));
    CUDA_CHECK(cudaStreamSynchronize(stream[1]));
    double t_gpu_wall = (t_gpu_start >= 0.0) ? (now_seconds() - t_gpu_start) : 0.0;

    if (g_error.load(std::memory_order_relaxed)) {
        fprintf(stderr, "aborting: a generator thread reported an error (see above)\n");
        return 1;
    }

    unsigned char* h_bits = (unsigned char*)malloc(combined_bytes);
    double td0 = now_seconds();
    CUDA_CHECK(cudaMemcpy(h_bits, d_bits, combined_bytes, cudaMemcpyDeviceToHost));
    double t_download = now_seconds() - td0;

    double t_total = now_seconds() - t_start;
    fprintf(stderr, "[gpu] DONE: %llu primes in %llu chunks, %llu generator thread(s) -- "
                     "generate_wall=%.3fs gpu_wall=%.3fs download=%.3fs TOTAL=%.3fs\n",
            (unsigned long long)total_primes, (unsigned long long)n_chunks,
            (unsigned long long)n_gen_threads, t_generate_wall, t_gpu_wall, t_download, t_total);

    FILE* fout = fopen(argv[2], "wb");
    if (!fout) { fprintf(stderr, "cannot open output %s\n", argv[2]); return 1; }
    fwrite(&combined_bytes, 8, 1, fout);
    fwrite(h_bits, 1, combined_bytes, fout);
    fwrite(&total_primes, 8, 1, fout);
    fwrite(&n_chunks, 8, 1, fout);
    fwrite(&n_gen_threads, 8, 1, fout);
    fwrite(&t_generate_wall, sizeof(double), 1, fout);
    fwrite(&t_gpu_wall, sizeof(double), 1, fout);
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
