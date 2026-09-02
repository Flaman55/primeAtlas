// phase_stream_parallel_poc.cu -- tenth-step proof of concept, direct follow-up to
// phase_stream_poc's real-hardware FULL-mode result.
//
// phase_stream_poc (single CPU marker thread) measured TOTAL=677.942s at real floor-25 scale --
// worse than the best-so-far unbucketed two-tier's 169.623s. But the breakdown was decisive:
// cpu_mark_wall=568.427s out of TOTAL=677.942s -- single-threaded CPU marking is 84% of the
// total time and clearly the dominant cost, NOT GPU phase computation. Artur's own read: with a
// SINGLE marking thread already only ~3.8x slower than production's real 176.018s benchmark
// (which uses 24 workers for its own marking step), there is real room to close that gap by
// parallelizing the CPU marking side to match.
//
// THE FIX PRODUCTION ALREADY USES, confirmed by reading prime_sieve_engine_v4.c directly rather
// than guessing: `generate_and_sieve_segment_bits_atomic()` (used by the real v3/v4
// orchestration, multiple WORKER PROCESSES writing into one shared mmap'd output buffer) marks
// every single bit -- both the O(1) sparse-tier write AND every iteration of the dense-tier loop
// -- via `__atomic_fetch_or(&out_dense_bits[pos >> 3], mask, __ATOMIC_RELAXED)`. Confirms two
// things: (1) concurrent writers into one shared buffer DO need atomics for correctness (a race
// on the same byte between two workers is a real, not theoretical, risk), and (2) CPU atomic OR
// under RELAXED ordering, with 24-way parallelism, is exactly what gets production to 113.352s in
// the first place -- so this specific operation, at this specific parallelism, is already proven
// fast on real hardware. Not a new idea -- applying production's own proven technique to the
// phase-stream architecture's marking step.
//
// DESIGN: keeps phase_stream_poc's GPU-phase-only, no-atomics-on-GPU-side kernel completely
// unchanged. What changes is what happens to a completed segment's results: instead of one
// thread synchronously marking it before moving to the next chunk (the serialization that made
// GPU wall time and CPU mark time effectively additive, matching the observed
// generate_wall~=gpu_wall~=677s signature of a consumer-bound pipeline), the GPU-driving thread
// now copies each completed segment's (primes, positions) pair into a MarkJob and pushes it onto
// a SECOND bounded queue (`g_mark_queue`, same backpressure pattern as the existing prime-batch
// queue). A POOL of CPU marker threads (`--marker-threads`, independently tunable from
// `--gen-threads` -- generation is now known-cheap at ~54.5s total per generation_balance_poc, so
// the right split of a 24-core machine is an empirical question, not something to guess) drains
// that queue and marks each job via CPU atomic OR, exactly mirroring production's own
// `__atomic_fetch_or`/`__ATOMIC_RELAXED` line.
//
// This is now a THREE-STAGE pipeline, each stage decoupled by its own bounded queue: CPU
// generator threads -> [prime batch queue] -> GPU phase kernel (single driver thread) ->
// [mark job queue] -> CPU marker thread pool. Each stage can run at its own pace, bounded only by
// queue depth, rather than the previous two-stage design where GPU and the single marker were
// forced into lockstep.

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
#include <cuda_runtime.h>
#include <primesieve.h>

#define PHASE_MOD_MAX_SAFE_PRIME_BITS 50
#define PHASE_THREADS 256
#define MAX_QUEUE_BATCHES 8
#define MAX_MARK_QUEUE 8

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

// unchanged from phase_stream_poc.cu -- phase-only, no combined_size/tier logic, no atomics.
__global__ void compute_phase_kernel(const unsigned long long* __restrict__ primes, int n_primes,
                                      unsigned long long distance_hi,
                                      unsigned long long distance_lo,
                                      unsigned long long* __restrict__ out_start_pos) {
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
    out_start_pos[idx] = start_pos;
}

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

// -------- stage 1->2: prime batches from generator threads --------

struct Batch {
    std::vector<unsigned long long> primes;
};

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

// Sets g_error and notifies BOTH stage queues' condition variables, always locking the mutex that
// corresponds to each cv before the store -- see the real definition below (after g_mark_mutex/
// g_mark_cv are declared) for why this is required rather than just an atomic store followed by
// an unlocked notify_all().
static void signal_fatal_error();

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
            signal_fatal_error();
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
        signal_fatal_error();
    }
    primesieve_free_iterator(&it);

    // The decrement must happen under g_queue_mutex, not as a bare atomic op followed by an
    // unlocked notify: see signal_fatal_error()'s comment for the general hazard this avoids.
    {
        std::lock_guard<std::mutex> lock(g_queue_mutex);
        g_active_generators.fetch_sub(1, std::memory_order_relaxed);
    }
    g_queue_cv.notify_all();
}

// -------- stage 2->3: completed (primes, positions) jobs for the marker pool --------

struct MarkJob {
    std::vector<unsigned long long> primes;
    std::vector<unsigned long long> positions;
};

static std::mutex g_mark_mutex;
static std::condition_variable g_mark_cv;
static std::queue<MarkJob> g_mark_queue;
static std::atomic<bool> g_gpu_done(false);

static bool push_mark_job_blocking(MarkJob&& job) {
    std::unique_lock<std::mutex> lock(g_mark_mutex);
    g_mark_cv.wait(lock, [] {
        return g_mark_queue.size() < MAX_MARK_QUEUE || g_error.load(std::memory_order_relaxed);
    });
    if (g_error.load(std::memory_order_relaxed)) return false;
    g_mark_queue.push(std::move(job));
    lock.unlock();
    g_mark_cv.notify_all();
    return true;
}

// Real definition (declared earlier, before g_mark_mutex/g_mark_cv existed, so generator_thread_
// func could call it). Locks each stage's own mutex before storing g_error=true, then notifies
// that stage's cv outside the lock. This matters because a bare `g_error.store(true, relaxed)`
// with NO lock at all, followed by an unlocked notify_all(), has a real lost-wakeup window: a
// waiter thread can check its predicate (false), and be in the middle of condition_variable::
// wait()'s atomic unlock-and-block transition, at the exact moment this function's store+notify
// happens -- if the notify fires before the waiter finishes registering as a listener, that
// notify is gone, and the waiter blocks forever with nothing left to wake it. Storing under the
// SAME mutex the waiter holds during its predicate check closes that window: the store cannot
// land in between the waiter's check and its registration, because both threads serialize on that
// mutex around exactly that boundary.
static void signal_fatal_error() {
    {
        std::lock_guard<std::mutex> lock(g_queue_mutex);
        g_error.store(true, std::memory_order_relaxed);
    }
    g_queue_cv.notify_all();
    {
        std::lock_guard<std::mutex> lock(g_mark_mutex);
        g_error.store(true, std::memory_order_relaxed);
    }
    g_mark_cv.notify_all();
}

// matches prime_sieve_engine_v4.c's generate_and_sieve_segment_bits_atomic() exactly: every
// write -- the single O(1) sparse-tier write and every iteration of the dense-tier loop -- goes
// through __atomic_fetch_or/__ATOMIC_RELAXED, since multiple marker threads write into the same
// shared `bits` buffer concurrently.
static inline void mark_one_atomic(unsigned long long p, unsigned long long start_pos,
                                    unsigned long long combined_size, unsigned char* bits,
                                    std::atomic<uint64_t>* n_loop, std::atomic<uint64_t>* n_single) {
    if (p >= combined_size) {
        n_single->fetch_add(1, std::memory_order_relaxed);
        if (start_pos < combined_size) {
            unsigned char mask = (unsigned char)(1u << (unsigned int)(start_pos & 7));
            __atomic_fetch_or(&bits[start_pos >> 3], mask, __ATOMIC_RELAXED);
        }
    } else {
        n_loop->fetch_add(1, std::memory_order_relaxed);
        for (unsigned long long pos = start_pos; pos < combined_size; pos += p) {
            unsigned char mask = (unsigned char)(1u << (unsigned int)(pos & 7));
            __atomic_fetch_or(&bits[pos >> 3], mask, __ATOMIC_RELAXED);
        }
    }
}

static void marker_thread_func(unsigned char* bits, unsigned long long combined_size,
                                std::atomic<uint64_t>* n_loop, std::atomic<uint64_t>* n_single,
                                double* out_busy_seconds) {
    double busy = 0.0;
    while (true) {
        MarkJob job;
        {
            std::unique_lock<std::mutex> lock(g_mark_mutex);
            g_mark_cv.wait(lock, [] {
                return !g_mark_queue.empty() ||
                       (g_gpu_done.load(std::memory_order_relaxed)) ||
                       g_error.load(std::memory_order_relaxed);
            });
            if (g_mark_queue.empty()) {
                if (g_gpu_done.load(std::memory_order_relaxed) ||
                    g_error.load(std::memory_order_relaxed)) {
                    break;
                }
                continue;
            }
            job = std::move(g_mark_queue.front());
            g_mark_queue.pop();
        }
        g_mark_cv.notify_all();
        double t0 = now_seconds();
        uint64_t n = job.primes.size();
        for (uint64_t i = 0; i < n; i++) {
            mark_one_atomic(job.primes[i], job.positions[i], combined_size, bits, n_loop,
                             n_single);
        }
        busy += now_seconds() - t0;
    }
    *out_busy_seconds = busy;
}

// ---------------------------------------------------------------------------------------------
// Host driver.
//
// Input file format (little-endian):
//   uint64_t l_final
//   uint64_t distance_hi
//   uint64_t distance_lo
//   uint64_t combined_size
//   uint64_t chunk_size
//   uint64_t num_gen_threads
//   uint64_t num_marker_threads
//
// Output file format:
//   uint64_t combined_bytes
//   uint8_t  bits[combined_bytes]
//   uint64_t total_primes
//   uint64_t n_loop_primes
//   uint64_t n_single_primes
//   uint64_t n_chunks
//   uint64_t n_gen_threads_used
//   uint64_t n_marker_threads_used
//   double   t_generate_wall
//   double   t_gpu_wall
//   double   t_marker_busy_total   (SUM across all marker threads of time spent actually
//                                   marking, not wall time -- divide by n_marker_threads_used
//                                   for a rough per-thread utilization sense)
//   double   t_total
// ---------------------------------------------------------------------------------------------

int main(int argc, char** argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s <input.bin> <output.bin>\n", argv[0]);
        return 1;
    }
    FILE* fin = fopen(argv[1], "rb");
    if (!fin) { fprintf(stderr, "cannot open input %s\n", argv[1]); return 1; }
    uint64_t l_final, distance_hi, distance_lo, combined_size, chunk_size, num_gen_threads_req;
    uint64_t num_marker_threads_req;
    if (fread(&l_final, 8, 1, fin) != 1 || fread(&distance_hi, 8, 1, fin) != 1 ||
        fread(&distance_lo, 8, 1, fin) != 1 || fread(&combined_size, 8, 1, fin) != 1 ||
        fread(&chunk_size, 8, 1, fin) != 1 || fread(&num_gen_threads_req, 8, 1, fin) != 1 ||
        fread(&num_marker_threads_req, 8, 1, fin) != 1) {
        fprintf(stderr, "bad input header\n"); return 1;
    }
    fclose(fin);

    g_safe_limit = 1ULL << PHASE_MOD_MAX_SAFE_PRIME_BITS;

    double t_start = now_seconds();

    CUDA_CHECK(cudaSetDeviceFlags(cudaDeviceMapHost));
    cudaDeviceProp prop;
    CUDA_CHECK(cudaGetDeviceProperties(&prop, 0));
    if (!prop.canMapHostMemory) {
        fprintf(stderr, "[ABORT] device does not support mapped host memory\n");
        return 1;
    }

    uint64_t combined_bytes = (combined_size + 7) / 8;
    combined_bytes = ((combined_bytes + 3) / 4) * 4;
    unsigned char* bits = (unsigned char*)calloc(1, combined_bytes);

    unsigned long long* d_primes[2];
    unsigned long long* h_pinned_primes[2];
    unsigned long long* h_pinned_output[2];
    unsigned long long* d_output_mapped[2];
    cudaStream_t stream[2];
    for (int i = 0; i < 2; i++) {
        CUDA_CHECK(cudaMalloc(&d_primes[i], sizeof(unsigned long long) * chunk_size));
        CUDA_CHECK(cudaMallocHost(&h_pinned_primes[i], sizeof(unsigned long long) * chunk_size));
        CUDA_CHECK(cudaHostAlloc(&h_pinned_output[i], sizeof(unsigned long long) * chunk_size,
                                  cudaHostAllocMapped));
        CUDA_CHECK(cudaHostGetDevicePointer(&d_output_mapped[i], h_pinned_output[i], 0));
        CUDA_CHECK(cudaStreamCreate(&stream[i]));
    }

    size_t free_bytes, total_bytes;
    CUDA_CHECK(cudaMemGetInfo(&free_bytes, &total_bytes));
    fprintf(stderr, "[gpu] device '%s'  d_primes(x2)=%.3f MB  pinned mapped output(x2)=%.3f MB  "
                     "(GPU free=%.1f MB / total=%.1f MB)\n",
            prop.name, 2.0 * sizeof(unsigned long long) * chunk_size / 1e6,
            2.0 * sizeof(unsigned long long) * chunk_size / 1e6, free_bytes / 1e6,
            total_bytes / 1e6);
    fprintf(stderr, "[cpu] bits buffer (marked atomically by the marker pool): %.3f MB\n",
            combined_bytes / 1e6);

    uint64_t n_gen_threads = num_gen_threads_req;
    if (n_gen_threads < 1) n_gen_threads = 1;
    uint64_t n_marker_threads = num_marker_threads_req;
    if (n_marker_threads < 1) n_marker_threads = 1;

    uint64_t range_lo = 2, range_hi = l_final;
    uint64_t total_width = (range_hi > range_lo) ? (range_hi - range_lo) : 0;
    if (n_gen_threads > total_width && total_width > 0) n_gen_threads = total_width;

    std::vector<uint64_t> boundaries(n_gen_threads + 1);
    boundaries[0] = range_lo;
    for (uint64_t i = 1; i < n_gen_threads; i++) {
        boundaries[i] = range_lo + (total_width * i) / n_gen_threads;
    }
    boundaries[n_gen_threads] = range_hi;

    std::atomic<uint64_t> n_loop_primes(0), n_single_primes(0);
    std::vector<double> marker_busy(n_marker_threads, 0.0);
    std::vector<std::thread> marker_threads;
    marker_threads.reserve(n_marker_threads);
    for (uint64_t i = 0; i < n_marker_threads; i++) {
        marker_threads.emplace_back(marker_thread_func, bits, combined_size, &n_loop_primes,
                                     &n_single_primes, &marker_busy[i]);
    }

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

    Batch prev_batch;
    bool have_pending = false;
    int prev_idx = -1;

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
        memcpy(h_pinned_primes[idx], batch.primes.data(), sizeof(unsigned long long) * n);
        CUDA_CHECK(cudaMemcpyAsync(d_primes[idx], h_pinned_primes[idx],
                                    sizeof(unsigned long long) * n, cudaMemcpyHostToDevice,
                                    stream[idx]));
        int grid = (int)((n + PHASE_THREADS - 1) / PHASE_THREADS);
        compute_phase_kernel<<<grid, PHASE_THREADS, 0, stream[idx]>>>(
            d_primes[idx], (int)n, distance_hi, distance_lo, d_output_mapped[idx]);
        CUDA_CHECK(cudaGetLastError());

        if (have_pending) {
            CUDA_CHECK(cudaStreamSynchronize(stream[prev_idx]));
            MarkJob job;
            job.primes = std::move(prev_batch.primes);
            uint64_t pn = job.primes.size();
            job.positions.assign(h_pinned_output[prev_idx], h_pinned_output[prev_idx] + pn);
            if (!push_mark_job_blocking(std::move(job))) break;
        }

        prev_batch = std::move(batch);
        prev_idx = idx;
        have_pending = true;

        total_primes += n;
        n_chunks++;
        if (n_chunks % 200 == 0) {
            fprintf(stderr, "[phase-stream-parallel] chunk %llu: running total %llu primes, "
                             "%.3fs since gpu start (mark queue depth=%zu)\n",
                    (unsigned long long)n_chunks, (unsigned long long)total_primes,
                    now_seconds() - t_gpu_start, g_mark_queue.size());
        }
    }

    for (auto& t : gen_threads) t.join();
    double t_generate_wall = now_seconds() - t_gen_start;

    if (have_pending && !g_error.load(std::memory_order_relaxed)) {
        CUDA_CHECK(cudaStreamSynchronize(stream[prev_idx]));
        MarkJob job;
        job.primes = std::move(prev_batch.primes);
        uint64_t pn = job.primes.size();
        job.positions.assign(h_pinned_output[prev_idx], h_pinned_output[prev_idx] + pn);
        push_mark_job_blocking(std::move(job));
    }

    double t_gpu_wall = (t_gpu_start >= 0.0) ? (now_seconds() - t_gpu_start) : 0.0;

    // Same lock-before-store requirement as signal_fatal_error() -- see that function's comment.
    {
        std::lock_guard<std::mutex> lock(g_mark_mutex);
        g_gpu_done.store(true, std::memory_order_relaxed);
    }
    g_mark_cv.notify_all();
    for (auto& t : marker_threads) t.join();

    if (g_error.load(std::memory_order_relaxed)) {
        fprintf(stderr, "aborting: an error was reported (see above)\n");
        return 1;
    }

    double marker_busy_total = 0.0;
    for (double b : marker_busy) marker_busy_total += b;

    double t_total = now_seconds() - t_start;
    fprintf(stderr, "[cpu] DONE: %llu primes total (%llu loop-style + %llu single-write-style) "
                     "in %llu chunks -- generate_wall=%.3fs  gpu_wall=%.3fs  "
                     "marker_busy_total=%.3fs (summed across %llu threads, avg=%.3fs/thread)  "
                     "TOTAL=%.3fs\n",
            (unsigned long long)total_primes, (unsigned long long)n_loop_primes.load(),
            (unsigned long long)n_single_primes.load(), (unsigned long long)n_chunks,
            t_generate_wall, t_gpu_wall, marker_busy_total,
            (unsigned long long)n_marker_threads, marker_busy_total / (double)n_marker_threads,
            t_total);

    FILE* fout = fopen(argv[2], "wb");
    if (!fout) { fprintf(stderr, "cannot open output %s\n", argv[2]); return 1; }
    fwrite(&combined_bytes, 8, 1, fout);
    fwrite(bits, 1, combined_bytes, fout);
    fwrite(&total_primes, 8, 1, fout);
    uint64_t n_loop_out = n_loop_primes.load(), n_single_out = n_single_primes.load();
    fwrite(&n_loop_out, 8, 1, fout);
    fwrite(&n_single_out, 8, 1, fout);
    fwrite(&n_chunks, 8, 1, fout);
    fwrite(&n_gen_threads, 8, 1, fout);
    fwrite(&n_marker_threads, 8, 1, fout);
    fwrite(&t_generate_wall, sizeof(double), 1, fout);
    fwrite(&t_gpu_wall, sizeof(double), 1, fout);
    fwrite(&marker_busy_total, sizeof(double), 1, fout);
    fwrite(&t_total, sizeof(double), 1, fout);
    fclose(fout);

    free(bits);
    for (int i = 0; i < 2; i++) {
        cudaFree(d_primes[i]);
        cudaFreeHost(h_pinned_primes[i]);
        cudaFreeHost(h_pinned_output[i]);
        cudaStreamDestroy(stream[i]);
    }
    return 0;
}
