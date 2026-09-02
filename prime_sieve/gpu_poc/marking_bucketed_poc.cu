// marking_bucketed_poc.cu -- eighth-step proof of concept, integrating sparse_bucketed_poc's
// real-hardware win into the full two-tier pipeline from marking_two_tier_poc.cu.
//
// BACKGROUND: marking_two_tier_poc's sparse_kernel (one thread per prime, single conditional
// atomic write) still left the two-tier FULL-mode result ~1.49x slower than production's
// sieve-only step. sparse_overhead_poc.cu's real-hardware decomposition (n=50,000,000) found the
// atomic write itself is 85.3% of sparse_kernel's cost (dispatch=2.6%, phase=12.0%) -- consistent
// with scattered, essentially-random-address atomic writes into a 1.25 GB buffer far larger than
// any GPU L2 cache.
//
// sparse_bucketed_poc.cu tested a fix: bucket-sort each chunk's primes by which SHARD of the
// output buffer their target position falls into, before the actual atomic writes, so writes
// landing in the same shard cluster together in execution order. Two real-hardware sweeps
// (n=50,000,000) found a clear, non-monotonic optimum -- NOT "smaller is always better":
//
//   shard bits   shard size   n_buckets   TOTAL      vs. naive (24.1ms)
//   16384        2 KB         610,352     28.728ms   0.84x (SLOWER)
//   65536        8 KB         152,588     16.297ms   1.48x
//   262144       32 KB        38,147      11.838ms   2.04x
//   1048576      128 KB       9,537       10.316ms   2.34x   <-- best
//   8388608      1 MB         1,193       13.110ms   1.84x
//   67108864     8 MB         150         20.266ms   1.19x
//   536870912    64 MB        19          31.126ms   0.77x (SLOWER)
//
// The U-shape has a real mechanism on both sides, not just noise:
//   - Too FEW buckets (large shards): the final write still touches a working set too big for
//     L2 to hold hot across many concurrent atomic writes -- the original problem, only
//     partially mitigated.
//   - Too MANY buckets (small shards): `scatter_kernel`'s own atomicAdd into the per-bucket
//     write-cursor array (`d_bucket_cursor`) becomes the new scattered/cache-hostile random-
//     address write -- the SAME problem this whole design was meant to fix, just one level down,
//     on a smaller-but-still-too-big array once bucket count gets into the hundreds of thousands.
//     (Measured directly: at 610,352 buckets, `scatter` alone cost 20.358ms -- ~10x its cost at
//     the 9,537-bucket optimum.)
// 128 KB shards (9,537 buckets at combined_size=10^10) is the confirmed real-hardware optimum
// for THIS scale; SPARSE_SHARD_BITS below is configurable via the input file so this can be
// re-swept if combined_size changes.
//
// THIS FILE integrates that bucketed sparse write into the full pipeline: the dense phase is
// byte-identical to marking_two_tier_poc.cu (run_phase(), unchanged marking_kernel). The sparse
// phase is a NEW function, run_sparse_bucketed_phase(), replacing the single sparse_kernel
// launch per chunk with the four-step bucketed pipeline (compute positions + count buckets ->
// host prefix sum -> scatter -> grouped write), still driven by the same bounded producer/
// consumer parallel-generation queue as every prior step in this series.
//
// HONEST TRADEOFF, flagged rather than hidden: the host round trip (D2H bucket counts, host
// prefix sum, H2D offsets) forces a synchronization point in the middle of each chunk's GPU
// work, so this phase does NOT use the double-buffered cross-chunk upload/kernel overlap that
// run_phase() gets for the dense tier and that marking_chunked_parallel_poc.cu introduced for
// the (then single-kernel) sparse tier. Each chunk's primes are uploaded and processed serially
// before the next chunk starts its own upload. Whether the ~2.34x per-chunk speedup from
// bucketing outweighs the lost overlap is exactly what FULL mode on real hardware answers --
// not assumed here.

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

// unchanged from marking_two_tier_poc.cu's fast-path fix (2026-08-28).
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

// dense kernel -- byte-identical to marking_two_tier_poc.cu. Used ONLY for primes p < combined_size.
__global__ void marking_kernel(const unsigned long long* __restrict__ primes, int n_primes,
                                unsigned long long distance_hi, unsigned long long distance_lo,
                                unsigned long long combined_size,
                                unsigned char* __restrict__ out_bits) {
    int prime_idx = blockIdx.x;
    if (prime_idx >= n_primes) return;
    unsigned long long p = primes[prime_idx];

    __shared__ unsigned long long s_start_pos;
    if (threadIdx.x == 0) {
        s_start_pos = compute_start_pos(p, distance_hi, distance_lo);
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

// -------- sparse tier: bucketed pipeline (from sparse_bucketed_poc.cu, real-hardware verified) --

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

// ---------------------------------------------------------------------------------------------
// Host driver.
//
// Input file format (little-endian):
//   uint64_t l_final
//   uint64_t distance_hi
//   uint64_t distance_lo
//   uint64_t combined_size    (also the dense/sparse tier boundary)
//   uint64_t chunk_size
//   uint64_t num_gen_threads
//   uint64_t sparse_shard_bits   (shard size, in bits of combined_size's range, for the sparse
//                                 tier's bucket-sort; 1048576 = 128 KB is the confirmed
//                                 real-hardware optimum from sparse_bucketed_poc at this scale)
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
//   uint64_t n_sparse_buckets
//   double   t_dense_generate_wall
//   double   t_dense_gpu_wall
//   double   t_sparse_generate_wall
//   double   t_sparse_gpu_wall       (includes compute+roundtrip+scatter+write for all chunks)
//   double   t_sparse_roundtrip_total  (the host-roundtrip slice of t_sparse_gpu_wall, broken
//                                       out separately so it's visible, not just folded in)
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

// ---- shared producer/consumer state (same bounded-queue design as every prior step) ----------

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

static void spawn_generators_and_get_boundaries(uint64_t range_lo, uint64_t range_hi,
                                                 uint64_t n_gen_threads, uint64_t chunk_size,
                                                 std::vector<std::thread>* gen_threads) {
    uint64_t total_width = range_hi - range_lo;
    std::vector<uint64_t> boundaries(n_gen_threads + 1);
    boundaries[0] = range_lo;
    for (uint64_t i = 1; i < n_gen_threads; i++) {
        boundaries[i] = range_lo + (total_width * i) / n_gen_threads;
    }
    boundaries[n_gen_threads] = range_hi;

    g_active_generators.store((int)n_gen_threads, std::memory_order_relaxed);
    gen_threads->reserve(n_gen_threads);
    for (uint64_t i = 0; i < n_gen_threads; i++) {
        gen_threads->emplace_back(generator_thread_func, boundaries[i], boundaries[i + 1],
                                   chunk_size);
    }
}

// dense phase -- unchanged in spirit from marking_two_tier_poc.cu's run_phase(), specialized to
// only the dense (marking_kernel) path since the sparse path now needs a very different body.
static void run_dense_phase(uint64_t phase_lo, uint64_t phase_hi, uint64_t chunk_size,
                             uint64_t num_gen_threads_req, unsigned long long distance_hi,
                             unsigned long long distance_lo, unsigned long long combined_size,
                             unsigned char* d_bits, unsigned long long* d_primes[2],
                             unsigned long long* h_pinned[2], cudaStream_t stream[2],
                             uint64_t* out_primes, uint64_t* out_chunks,
                             uint64_t* out_gen_threads_used, double* out_generate_wall,
                             double* out_gpu_wall) {
    *out_primes = 0; *out_chunks = 0; *out_generate_wall = 0.0; *out_gpu_wall = 0.0;

    uint64_t range_lo = phase_lo, range_hi = (phase_hi > phase_lo) ? phase_hi : phase_lo;
    uint64_t total_width = range_hi - range_lo;
    if (total_width == 0) {
        fprintf(stderr, "[dense] empty range [%llu, %llu) -- skipping\n",
                (unsigned long long)phase_lo, (unsigned long long)phase_hi);
        *out_gen_threads_used = 0;
        return;
    }

    uint64_t n_gen_threads = num_gen_threads_req;
    if (n_gen_threads < 1) n_gen_threads = 1;
    if (n_gen_threads > total_width) n_gen_threads = total_width;
    *out_gen_threads_used = n_gen_threads;

    fprintf(stderr, "[dense] range=[%llu, %llu)  width=%llu  using %llu generator thread(s)\n",
            (unsigned long long)range_lo, (unsigned long long)range_hi,
            (unsigned long long)total_width, (unsigned long long)n_gen_threads);

    double t_gen_start = now_seconds();
    std::vector<std::thread> gen_threads;
    spawn_generators_and_get_boundaries(range_lo, range_hi, n_gen_threads, chunk_size,
                                         &gen_threads);

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
        marking_kernel<<<(int)n, MARK_THREADS, 0, stream[idx]>>>(
            d_primes[idx], (int)n, distance_hi, distance_lo, combined_size, d_bits);
        CUDA_CHECK(cudaGetLastError());

        total_primes += n;
        n_chunks++;
        if (n_chunks % 50 == 0) {
            fprintf(stderr, "[dense] chunk %llu: running total %llu primes, %.3fs since phase "
                             "start\n",
                    (unsigned long long)n_chunks, (unsigned long long)total_primes,
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
    fprintf(stderr, "[dense] DONE: %llu primes in %llu chunks -- generate_wall=%.3fs "
                     "gpu_wall=%.3fs\n",
            (unsigned long long)total_primes, (unsigned long long)n_chunks, *out_generate_wall,
            *out_gpu_wall);
}

// sparse phase -- bucketed pipeline. See file header for the honest tradeoff: each chunk is
// processed fully serially (upload -> compute+count -> host roundtrip -> scatter -> write) with
// no cross-chunk upload/kernel overlap, since the host roundtrip forces a sync point per chunk
// regardless. CPU generation still overlaps with GPU consumption via the same bounded queue.
static void run_sparse_bucketed_phase(uint64_t phase_lo, uint64_t phase_hi, uint64_t chunk_size,
                                       uint64_t num_gen_threads_req,
                                       unsigned long long distance_hi,
                                       unsigned long long distance_lo,
                                       unsigned long long combined_size, uint64_t shard_size,
                                       unsigned char* d_bits, uint64_t* out_primes,
                                       uint64_t* out_chunks, uint64_t* out_gen_threads_used,
                                       uint64_t* out_n_buckets, double* out_generate_wall,
                                       double* out_gpu_wall, double* out_roundtrip_total) {
    *out_primes = 0; *out_chunks = 0; *out_generate_wall = 0.0; *out_gpu_wall = 0.0;
    *out_roundtrip_total = 0.0;

    uint64_t range_lo = phase_lo, range_hi = (phase_hi > phase_lo) ? phase_hi : phase_lo;
    uint64_t total_width = range_hi - range_lo;
    uint64_t n_buckets = (combined_size + shard_size - 1) / shard_size;
    *out_n_buckets = n_buckets;
    if (total_width == 0) {
        fprintf(stderr, "[sparse-bucketed] empty range [%llu, %llu) -- skipping\n",
                (unsigned long long)phase_lo, (unsigned long long)phase_hi);
        *out_gen_threads_used = 0;
        return;
    }

    uint64_t n_gen_threads = num_gen_threads_req;
    if (n_gen_threads < 1) n_gen_threads = 1;
    if (n_gen_threads > total_width) n_gen_threads = total_width;
    *out_gen_threads_used = n_gen_threads;

    fprintf(stderr, "[sparse-bucketed] range=[%llu, %llu)  width=%llu  "
                     "using %llu generator thread(s)  shard_size=%llu bits (%.3f MB)  "
                     "n_buckets=%llu\n",
            (unsigned long long)range_lo, (unsigned long long)range_hi,
            (unsigned long long)total_width, (unsigned long long)n_gen_threads,
            (unsigned long long)shard_size, shard_size / 8.0 / 1e6,
            (unsigned long long)n_buckets);

    unsigned long long* d_primes_local;
    unsigned long long* h_pinned_local;
    unsigned long long* d_positions;
    unsigned long long* d_sorted_positions;
    unsigned int* d_bucket_counts;
    unsigned int* d_bucket_offsets_dev;
    CUDA_CHECK(cudaMalloc(&d_primes_local, sizeof(unsigned long long) * chunk_size));
    CUDA_CHECK(cudaMallocHost(&h_pinned_local, sizeof(unsigned long long) * chunk_size));
    CUDA_CHECK(cudaMalloc(&d_positions, sizeof(unsigned long long) * chunk_size));
    CUDA_CHECK(cudaMalloc(&d_sorted_positions, sizeof(unsigned long long) * chunk_size));
    CUDA_CHECK(cudaMalloc(&d_bucket_counts, sizeof(unsigned int) * n_buckets));
    CUDA_CHECK(cudaMalloc(&d_bucket_offsets_dev, sizeof(unsigned int) * n_buckets));
    std::vector<unsigned int> h_counts(n_buckets), h_offsets(n_buckets);

    double t_gen_start = now_seconds();
    std::vector<std::thread> gen_threads;
    spawn_generators_and_get_boundaries(range_lo, range_hi, n_gen_threads, chunk_size,
                                         &gen_threads);

    uint64_t total_primes = 0, n_chunks = 0;
    double t_gpu_start = -1.0;
    double t_phase_start = now_seconds();
    double roundtrip_total = 0.0;

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

        memcpy(h_pinned_local, batch.primes.data(), sizeof(unsigned long long) * n);
        CUDA_CHECK(cudaMemcpy(d_primes_local, h_pinned_local, sizeof(unsigned long long) * n,
                               cudaMemcpyHostToDevice));

        int grid = (int)((n + SPARSE_THREADS - 1) / SPARSE_THREADS);
        CUDA_CHECK(cudaMemset(d_bucket_counts, 0, sizeof(unsigned int) * n_buckets));
        compute_positions_kernel<<<grid, SPARSE_THREADS>>>(
            d_primes_local, (int)n, distance_hi, distance_lo, combined_size, shard_size,
            d_positions, d_bucket_counts);
        CUDA_CHECK(cudaGetLastError());

        double rt_start = now_seconds();
        CUDA_CHECK(cudaMemcpy(h_counts.data(), d_bucket_counts, sizeof(unsigned int) * n_buckets,
                               cudaMemcpyDeviceToHost));
        unsigned int running = 0;
        for (uint64_t b = 0; b < n_buckets; b++) {
            h_offsets[b] = running;
            running += h_counts[b];
        }
        uint64_t n_valid = running;
        CUDA_CHECK(cudaMemcpy(d_bucket_offsets_dev, h_offsets.data(), sizeof(unsigned int) * n_buckets,
                               cudaMemcpyHostToDevice));
        roundtrip_total += now_seconds() - rt_start;

        scatter_kernel<<<grid, SPARSE_THREADS>>>(d_positions, (int)n, shard_size,
                                                   d_bucket_offsets_dev, d_sorted_positions);
        CUDA_CHECK(cudaGetLastError());

        // n_valid (how many of this chunk's primes actually land inside combined_size) can be
        // legitimately 0 for a small/early chunk -- a sparse-tier prime has AT MOST one hit in
        // the window, so most chunks have plenty of primes that hash outside combined_size and
        // it's easy for ALL of them to, especially at EXACT mode's tiny scale. A <<<0, N>>>
        // launch is rejected as an invalid argument on this toolkit, so skip the launch entirely
        // when there's nothing to write -- caught by EXACT mode against the tiny cases the
        // real-hardware FULL-mode run (n_valid always >0 there) never exercised.
        if (n_valid > 0) {
            int grid_valid = (int)((n_valid + SPARSE_THREADS - 1) / SPARSE_THREADS);
            write_sorted_kernel<<<grid_valid, SPARSE_THREADS>>>(d_sorted_positions, (int)n_valid,
                                                                  d_bits);
            CUDA_CHECK(cudaGetLastError());
        }

        total_primes += n;
        n_chunks++;
        if (n_chunks % 50 == 0) {
            fprintf(stderr, "[sparse-bucketed] chunk %llu: running total %llu primes, %.3fs "
                             "since phase start\n",
                    (unsigned long long)n_chunks, (unsigned long long)total_primes,
                    now_seconds() - t_phase_start);
        }
    }

    for (auto& t : gen_threads) t.join();
    *out_generate_wall = now_seconds() - t_gen_start;

    CUDA_CHECK(cudaDeviceSynchronize());
    *out_gpu_wall = (t_gpu_start >= 0.0) ? (now_seconds() - t_gpu_start) : 0.0;
    *out_roundtrip_total = roundtrip_total;

    *out_primes = total_primes;
    *out_chunks = n_chunks;
    fprintf(stderr, "[sparse-bucketed] DONE: %llu primes in %llu chunks -- generate_wall=%.3fs "
                     "gpu_wall=%.3fs (of which roundtrip=%.3fs)\n",
            (unsigned long long)total_primes, (unsigned long long)n_chunks, *out_generate_wall,
            *out_gpu_wall, roundtrip_total);

    cudaFree(d_primes_local);
    cudaFreeHost(h_pinned_local);
    cudaFree(d_positions);
    cudaFree(d_sorted_positions);
    cudaFree(d_bucket_counts);
    cudaFree(d_bucket_offsets_dev);
}

int main(int argc, char** argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s <input.bin> <output.bin>\n", argv[0]);
        return 1;
    }
    FILE* fin = fopen(argv[1], "rb");
    if (!fin) { fprintf(stderr, "cannot open input %s\n", argv[1]); return 1; }
    uint64_t l_final, distance_hi, distance_lo, combined_size, chunk_size, num_gen_threads_req;
    uint64_t sparse_shard_bits;
    if (fread(&l_final, 8, 1, fin) != 1 || fread(&distance_hi, 8, 1, fin) != 1 ||
        fread(&distance_lo, 8, 1, fin) != 1 || fread(&combined_size, 8, 1, fin) != 1 ||
        fread(&chunk_size, 8, 1, fin) != 1 || fread(&num_gen_threads_req, 8, 1, fin) != 1 ||
        fread(&sparse_shard_bits, 8, 1, fin) != 1) {
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
                     "d_bits=%.3f MB  d_primes(x2 ping-pong, dense)=%.3f MB  "
                     "(GPU free=%.1f MB / total=%.1f MB right after allocation)\n",
            combined_bytes / 1e6, 2.0 * (sizeof(unsigned long long) * chunk_size) / 1e6,
            free_bytes / 1e6, total_bytes / 1e6);
    fprintf(stderr, "[cpu] bounded producer/consumer queue: max %d batches queued at once "
                     "(~%.2f GB of host RAM at chunk_size=%llu)\n",
            MAX_QUEUE_BATCHES,
            (MAX_QUEUE_BATCHES * (double)(sizeof(unsigned long long) * chunk_size)) / 1e9,
            (unsigned long long)chunk_size);

    uint64_t dense_hi = (combined_size < l_final) ? combined_size : l_final;
    if (dense_hi < 2) dense_hi = 2;
    uint64_t sparse_lo = dense_hi;

    uint64_t n_dense_primes, n_dense_chunks, n_dense_gen_threads_used;
    double t_dense_generate_wall, t_dense_gpu_wall;
    run_dense_phase(2, dense_hi, chunk_size, num_gen_threads_req, distance_hi, distance_lo,
                     combined_size, d_bits, d_primes, h_pinned, stream, &n_dense_primes,
                     &n_dense_chunks, &n_dense_gen_threads_used, &t_dense_generate_wall,
                     &t_dense_gpu_wall);

    uint64_t n_sparse_primes = 0, n_sparse_chunks = 0, n_sparse_gen_threads_used = 0;
    uint64_t n_sparse_buckets = 0;
    double t_sparse_generate_wall = 0.0, t_sparse_gpu_wall = 0.0, t_sparse_roundtrip_total = 0.0;
    if (!g_error.load(std::memory_order_relaxed) && sparse_lo < l_final) {
        run_sparse_bucketed_phase(sparse_lo, l_final, chunk_size, num_gen_threads_req,
                                   distance_hi, distance_lo, combined_size, sparse_shard_bits,
                                   d_bits, &n_sparse_primes, &n_sparse_chunks,
                                   &n_sparse_gen_threads_used, &n_sparse_buckets,
                                   &t_sparse_generate_wall, &t_sparse_gpu_wall,
                                   &t_sparse_roundtrip_total);
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
                     "dense: gen=%.3fs gpu=%.3fs | sparse: gen=%.3fs gpu=%.3fs (roundtrip=%.3fs) "
                     "| download=%.3fs TOTAL=%.3fs\n",
            (unsigned long long)total_primes, (unsigned long long)n_dense_primes,
            (unsigned long long)n_sparse_primes, t_dense_generate_wall, t_dense_gpu_wall,
            t_sparse_generate_wall, t_sparse_gpu_wall, t_sparse_roundtrip_total, t_download,
            t_total);

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
    fwrite(&n_sparse_buckets, 8, 1, fout);
    fwrite(&t_dense_generate_wall, sizeof(double), 1, fout);
    fwrite(&t_dense_gpu_wall, sizeof(double), 1, fout);
    fwrite(&t_sparse_generate_wall, sizeof(double), 1, fout);
    fwrite(&t_sparse_gpu_wall, sizeof(double), 1, fout);
    fwrite(&t_sparse_roundtrip_total, sizeof(double), 1, fout);
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
