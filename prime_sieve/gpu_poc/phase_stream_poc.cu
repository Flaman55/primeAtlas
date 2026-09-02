// phase_stream_poc.cu -- ninth-step proof of concept, built directly from Artur's architecture
// after marking_bucketed_poc.cu's integration regressed (196.448s vs the unbucketed two-tier's
// 169.623s) and generation_balance_poc.cpp disproved the "generator-thread imbalance" hypothesis
// (equal-width vs equal-count split gave IDENTICAL wall time, 54.543s vs 54.618s, for raw
// generation of the real sparse-tier range) -- meaning the ~186s "generate_wall" measured inside
// the real pipeline was mostly generator threads BLOCKED on backpressure from a slow GPU
// consumer, not real generation cost. Real generation is fast; CPU was starved by GPU, not the
// other way around.
//
// ARTUR'S ARCHITECTURE (his own words, paraphrased): every design in this series so far has GPU
// do TWO things per prime -- compute the phase, AND perform the write. The write (specifically,
// atomic writes from thousands of concurrent GPU threads into a shared 1.25 GB buffer) has been
// the dominant cost throughout (85.3% of the plain sparse kernel; the entire reason bucketing
// was tried, and bucketing's own scatter step hit the same problem one level down). Once a
// prime's phase (target position) is known, the ACTUAL marking step is cheap -- production's own
// C code does it as a single conditional array write (O(1) tier) or a tight native loop (dense
// tier), and generation_balance_poc just confirmed CPU has real throughput headroom.
//
// So: let GPU do ONLY the phase computation (cheap, no atomics needed -- each thread's result is
// independent, writes to its own unique output slot) and stream results to CPU, which does the
// actual marking -- exactly mirroring production's own per-prime branch (no separate dense/
// sparse GPU kernels needed anymore; the branch lives on the CPU side, same as production).
// Artur's refinement: size the handoff so GPU stays a SMALL, bounded lookahead ahead of CPU (not
// a huge batch, not a trickle) using memory both sides can access with low, comparable latency --
// concretely, pinned + mapped host memory that GPU writes into directly (no explicit
// cudaMemcpy D2H step for the output at all) and CPU reads directly, so CPU is fed continuously
// and GPU never idles waiting for CPU nor races arbitrarily far ahead.
//
// DESIGN: two ping-pong SEGMENTs (SEGMENT_PRIMES primes each). For chunk N: primes are uploaded
// to device memory as in every prior file (cheap, small), `compute_phase_kernel` computes
// start_pos for each prime with NO combined_size/tier logic at all (phase computation is
// independent of tier) and writes directly into pinned+mapped output[N%2] via the device-mapped
// pointer -- no D2H copy. While that kernel runs asynchronously on stream[N%2], the CPU thread
// marks chunk N-1's ALREADY-COMPUTED results (output[(N-1)%2], synced just-in-time) into the
// real `bits` output buffer, doing EXACTLY production's branch:
//   if (p >= combined_size) { if (start_pos < combined_size) bits[start_pos>>3] |= mask; }
//   else { for (pos = start_pos; pos < combined_size; pos += p) bits[pos>>3] |= mask; }
// No atomics anywhere -- CPU marking is single-threaded here (a real limitation flagged in the
// header below, not hidden), so there's no write race to guard against.
//
// HONEST LIMITATIONS, stated up front rather than discovered later:
//   - CPU marking here is single-threaded. Production uses 24 CPU workers for its own marking
//     step; a single CPU thread draining this pipeline cannot match that parallelism. This PoC
//     tests whether the CORE mechanism (mapped-memory handoff, GPU staying ahead, real overlap)
//     actually works and is fast BEFORE investing in parallelizing the CPU consumer side too --
//     consistent with this series' pattern of proving a mechanism small before scaling it.
//   - Mapped pinned memory requires cudaSetDeviceFlags(cudaDeviceMapHost) before any CUDA
//     context work, and the device must report canMapHostMemory -- checked and reported, not
//     assumed.

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

// unchanged fast-path fix from marking_two_tier_poc.cu (2026-08-28).
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

// phase-only kernel -- NO combined_size, NO tier branch, NO atomics. Every sieving prime
// (dense or sparse) goes through this same, uniform computation; the tier branch happens on
// the CPU side, per production's own design. Writes directly into mapped pinned memory.
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

// ---------------------------------------------------------------------------------------------
// Host driver.
//
// Input file format (little-endian):
//   uint64_t l_final
//   uint64_t distance_hi
//   uint64_t distance_lo
//   uint64_t combined_size
//   uint64_t chunk_size       (== SEGMENT_PRIMES for this file -- one segment per chunk)
//   uint64_t num_gen_threads
//
// Output file format:
//   uint64_t combined_bytes
//   uint8_t  bits[combined_bytes]
//   uint64_t total_primes
//   uint64_t n_loop_primes      (dense-style: p < combined_size, CPU did the striding loop)
//   uint64_t n_single_primes    (sparse-style: p >= combined_size, CPU did at most one write)
//   uint64_t n_chunks
//   uint64_t n_gen_threads_used
//   double   t_generate_wall
//   double   t_gpu_wall         (wall time the GPU-kernel/upload side was active)
//   double   t_cpu_mark_wall    (wall time CPU spent in the marking loop, should overlap with
//                                t_gpu_wall by design -- both reported so the overlap is visible)
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

// non-atomic, single-threaded CPU marking -- exactly production's per-prime branch.
static inline void mark_one(unsigned long long p, unsigned long long start_pos,
                             unsigned long long combined_size, unsigned char* bits,
                             uint64_t* n_loop, uint64_t* n_single) {
    if (p >= combined_size) {
        (*n_single)++;
        if (start_pos < combined_size) {
            bits[start_pos >> 3] |= (unsigned char)(1u << (start_pos & 7));
        }
    } else {
        (*n_loop)++;
        for (unsigned long long pos = start_pos; pos < combined_size; pos += p) {
            bits[pos >> 3] |= (unsigned char)(1u << (pos & 7));
        }
    }
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

    // mapped pinned memory requires this flag set before any context-creating CUDA call.
    CUDA_CHECK(cudaSetDeviceFlags(cudaDeviceMapHost));
    cudaDeviceProp prop;
    CUDA_CHECK(cudaGetDeviceProperties(&prop, 0));
    if (!prop.canMapHostMemory) {
        fprintf(stderr, "[ABORT] device does not support mapped host memory (canMapHostMemory=0)\n");
        return 1;
    }
    fprintf(stderr, "[gpu] device '%s' supports mapped host memory -- using zero-copy phase "
                     "output (no D2H memcpy for results)\n", prop.name);

    uint64_t combined_bytes = (combined_size + 7) / 8;
    combined_bytes = ((combined_bytes + 3) / 4) * 4;
    unsigned char* bits = (unsigned char*)calloc(1, combined_bytes);

    unsigned long long* d_primes[2];
    unsigned long long* h_pinned_primes[2];
    unsigned long long* h_pinned_output[2];   // mapped, GPU writes here directly
    unsigned long long* d_output_mapped[2];   // device-side alias of the same memory
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
    fprintf(stderr, "[gpu] resident buffers: d_primes(x2)=%.3f MB  pinned mapped output(x2)=%.3f MB"
                     "  (GPU free=%.1f MB / total=%.1f MB)\n",
            2.0 * sizeof(unsigned long long) * chunk_size / 1e6,
            2.0 * sizeof(unsigned long long) * chunk_size / 1e6, free_bytes / 1e6,
            total_bytes / 1e6);
    fprintf(stderr, "[cpu] bits buffer (host, marked directly, no GPU involvement): %.3f MB\n",
            combined_bytes / 1e6);

    uint64_t n_gen_threads = num_gen_threads_req;
    if (n_gen_threads < 1) n_gen_threads = 1;
    uint64_t range_lo = 2, range_hi = l_final;
    uint64_t total_width = (range_hi > range_lo) ? (range_hi - range_lo) : 0;
    if (n_gen_threads > total_width && total_width > 0) n_gen_threads = total_width;

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

    uint64_t total_primes = 0, n_chunks = 0, n_loop_primes = 0, n_single_primes = 0;
    double t_gpu_start = -1.0, t_cpu_mark_total = 0.0;

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
        CUDA_CHECK(cudaStreamSynchronize(stream[idx]));  // ensure this slot's prior use is done
        memcpy(h_pinned_primes[idx], batch.primes.data(), sizeof(unsigned long long) * n);
        CUDA_CHECK(cudaMemcpyAsync(d_primes[idx], h_pinned_primes[idx],
                                    sizeof(unsigned long long) * n, cudaMemcpyHostToDevice,
                                    stream[idx]));
        int grid = (int)((n + PHASE_THREADS - 1) / PHASE_THREADS);
        compute_phase_kernel<<<grid, PHASE_THREADS, 0, stream[idx]>>>(
            d_primes[idx], (int)n, distance_hi, distance_lo, d_output_mapped[idx]);
        CUDA_CHECK(cudaGetLastError());

        if (have_pending) {
            // this chunk's kernel (idx) is running async on GPU; mark the PREVIOUS chunk's
            // already-computed results now, overlapping with it
            CUDA_CHECK(cudaStreamSynchronize(stream[prev_idx]));
            double tm0 = now_seconds();
            uint64_t pn = prev_batch.primes.size();
            for (uint64_t i = 0; i < pn; i++) {
                mark_one(prev_batch.primes[i], h_pinned_output[prev_idx][i], combined_size, bits,
                         &n_loop_primes, &n_single_primes);
            }
            t_cpu_mark_total += now_seconds() - tm0;
        }

        prev_batch = std::move(batch);
        prev_idx = idx;
        have_pending = true;

        total_primes += n;
        n_chunks++;
        if (n_chunks % 200 == 0) {
            fprintf(stderr, "[phase-stream] chunk %llu: running total %llu primes, "
                             "%.3fs since gpu start\n",
                    (unsigned long long)n_chunks, (unsigned long long)total_primes,
                    now_seconds() - t_gpu_start);
        }
    }

    for (auto& t : gen_threads) t.join();
    double t_generate_wall = now_seconds() - t_gen_start;

    // final pending chunk
    if (have_pending) {
        CUDA_CHECK(cudaStreamSynchronize(stream[prev_idx]));
        double tm0 = now_seconds();
        uint64_t pn = prev_batch.primes.size();
        for (uint64_t i = 0; i < pn; i++) {
            mark_one(prev_batch.primes[i], h_pinned_output[prev_idx][i], combined_size, bits,
                     &n_loop_primes, &n_single_primes);
        }
        t_cpu_mark_total += now_seconds() - tm0;
    }

    double t_gpu_wall = (t_gpu_start >= 0.0) ? (now_seconds() - t_gpu_start) : 0.0;

    if (g_error.load(std::memory_order_relaxed)) {
        fprintf(stderr, "aborting: a generator thread reported an error (see above)\n");
        return 1;
    }

    double t_total = now_seconds() - t_start;
    fprintf(stderr, "[cpu] DONE: %llu primes total (%llu loop-style + %llu single-write-style) "
                     "in %llu chunks -- generate_wall=%.3fs  gpu_wall=%.3fs  "
                     "cpu_mark_wall=%.3fs (overlaps with gpu_wall by design)  TOTAL=%.3fs\n",
            (unsigned long long)total_primes, (unsigned long long)n_loop_primes,
            (unsigned long long)n_single_primes, (unsigned long long)n_chunks, t_generate_wall,
            t_gpu_wall, t_cpu_mark_total, t_total);

    FILE* fout = fopen(argv[2], "wb");
    if (!fout) { fprintf(stderr, "cannot open output %s\n", argv[2]); return 1; }
    fwrite(&combined_bytes, 8, 1, fout);
    fwrite(bits, 1, combined_bytes, fout);
    fwrite(&total_primes, 8, 1, fout);
    fwrite(&n_loop_primes, 8, 1, fout);
    fwrite(&n_single_primes, 8, 1, fout);
    fwrite(&n_chunks, 8, 1, fout);
    fwrite(&n_gen_threads, 8, 1, fout);
    fwrite(&t_generate_wall, sizeof(double), 1, fout);
    fwrite(&t_gpu_wall, sizeof(double), 1, fout);
    fwrite(&t_cpu_mark_total, sizeof(double), 1, fout);
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
