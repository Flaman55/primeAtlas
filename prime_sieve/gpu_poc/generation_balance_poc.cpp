// generation_balance_poc.cpp -- CPU-only diagnostic, no GPU involved. Direct follow-up to
// marking_bucketed_poc's real-hardware FULL-mode result: TOTAL=196.448s, a REGRESSION from the
// unbucketed two-tier's 169.623s -- confirming the predicted risk (losing cross-chunk upload/
// kernel overlap cost more than bucketing's isolated 2.34x per-chunk win saved).
//
// But a bigger, previously-deferred discrepancy stands out in that same run's numbers:
// [sparse-bucketed] generate_wall=185.944s for the sparse tier ALONE (113,528,483,264 primes,
// range [10^10, 3.16*10^12), 24 threads, EQUAL-WIDTH range splitting -- this codebase's
// splitting logic since marking_chunked_parallel_poc.cu, unchanged through every file in this
// series). Production's real sieve step -- covering BOTH tiers, ALL ~113.8 billion primes, PLUS
// the phase_mod computation and the actual marking, not just raw generation -- takes 113.352s
// total. Our generation-ONLY step for 99.6% of that same prime volume takes 64% LONGER than
// production's entire sieve step. That gap was flagged as a deferred, lower-priority item back
// when the atomic-write bottleneck was still the open question (see README's "previously-
// identified, still-deferred axis" note) -- with that bottleneck now understood and the
// bucketing integration net-negative, this is very likely the real remaining lever.
//
// THE SUSPECT: this codebase splits the generator-thread range by EQUAL WIDTH
// (`boundaries[i] = range_lo + (total_width * i) / n_gen_threads`, unchanged since
// marking_chunked_parallel_poc.cu). Production instead uses Mertens-weighted cost-balanced
// batches (`_build_equal_cost_batches`, noted in prior research but never re-implemented here).
// Prime density ~1/ln(x) falls off slowly across this range (ln(10^10)~23 to ln(3.16*10^12)
// ~28.8), so equal-WIDTH sub-ranges do NOT have equal prime COUNTS -- the thread covering the
// low end of the range has more primes to generate than the thread covering the high end. If
// the imbalance is severe enough, parallel wall time is dominated by the single slowest thread,
// wasting a large fraction of the other 23 threads' idle time at the tail of the phase.
//
// THIS FILE tests that hypothesis directly and cheaply, with NO GPU and no marking -- just raw
// primesieve_iterator generation, parallelized across 24 threads two ways over the exact real
// floor-25 sparse range:
//   (A) equal-width split (current behavior, unchanged from every prior file in this series)
//   (B) equal-COUNT split, via numerically inverting the prime-counting approximation Li(x) =
//       integral(2 to x) of 1/ln(t) dt -- the same Mertens/logarithmic-integral idea production
//       uses, computed here via simple numerical integration (no primesieve counting calls
//       needed to build the boundaries -- fast, approximate, good enough to fix a large
//       imbalance even if not exactly balanced).
//
// Reports each thread's actual prime count under both splits (to show the imbalance directly,
// not just infer it from wall time) and the real parallel wall-clock time for both. If (B) is
// meaningfully faster, that's the next fix to make to run_dense_phase/run_sparse_bucketed_phase
// (and every earlier file's run_phase) before drawing further conclusions about GPU-side marking
// strategies -- since any GPU improvement is currently capped by this same generation floor.

#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cmath>
#include <chrono>
#include <thread>
#include <vector>
#include <atomic>
#include <primesieve.h>

static double now_seconds() {
    return std::chrono::duration<double>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

// -------- split A: equal width (current behavior everywhere in this series) --------

static std::vector<uint64_t> equal_width_boundaries(uint64_t lo, uint64_t hi, uint64_t n) {
    uint64_t width = hi - lo;
    std::vector<uint64_t> b(n + 1);
    b[0] = lo;
    for (uint64_t i = 1; i < n; i++) b[i] = lo + (width * i) / n;
    b[n] = hi;
    return b;
}

// -------- split B: equal estimated prime count, via numerical Li(x) inversion --------

static std::vector<uint64_t> equal_count_boundaries(uint64_t lo, uint64_t hi, uint64_t n) {
    const int N_SAMPLES = 400000;
    double dlo = (double)lo, dhi = (double)hi;
    double step = (dhi - dlo) / N_SAMPLES;

    // cumulative trapezoidal integral of 1/ln(t) from lo to each sample point
    std::vector<double> cum(N_SAMPLES + 1);
    cum[0] = 0.0;
    double prev_t = dlo;
    double prev_f = 1.0 / std::log(prev_t);
    for (int i = 1; i <= N_SAMPLES; i++) {
        double t = dlo + step * i;
        double f = 1.0 / std::log(t);
        cum[i] = cum[i - 1] + 0.5 * (prev_f + f) * step;
        prev_t = t;
        prev_f = f;
    }
    double total = cum[N_SAMPLES];

    std::vector<uint64_t> b(n + 1);
    b[0] = lo;
    b[n] = hi;
    for (uint64_t i = 1; i < n; i++) {
        double target = total * ((double)i / (double)n);
        // binary search cum[] for target, then linearly interpolate within the bracketing
        // sample interval to get a real-valued x, rounded to the nearest integer boundary
        int loIdx = 0, hiIdx = N_SAMPLES;
        while (loIdx < hiIdx) {
            int mid = (loIdx + hiIdx) / 2;
            if (cum[mid] < target) loIdx = mid + 1; else hiIdx = mid;
        }
        int idx = loIdx;
        if (idx == 0) {
            b[i] = lo;
        } else {
            double c0 = cum[idx - 1], c1 = cum[idx];
            double t0 = dlo + step * (idx - 1), t1 = dlo + step * idx;
            double frac = (c1 > c0) ? (target - c0) / (c1 - c0) : 0.0;
            double x = t0 + frac * (t1 - t0);
            b[i] = (uint64_t)llround(x);
        }
        if (b[i] < b[i - 1]) b[i] = b[i - 1];  // monotonicity guard against numerical noise
    }
    return b;
}

static void gen_thread_count_only(uint64_t sub_lo, uint64_t sub_hi, uint64_t* out_count,
                                   double* out_seconds) {
    double t0 = now_seconds();
    primesieve_iterator it;
    primesieve_init(&it);
    primesieve_jump_to(&it, sub_lo, sub_hi);
    uint64_t count = 0;
    while (true) {
        uint64_t p = primesieve_next_prime(&it);
        if (p >= sub_hi) break;
        count++;
    }
    primesieve_free_iterator(&it);
    *out_count = count;
    *out_seconds = now_seconds() - t0;
}

static void run_split(const char* label, const std::vector<uint64_t>& boundaries, uint64_t n) {
    std::vector<uint64_t> counts(n);
    std::vector<double> seconds(n);
    std::vector<std::thread> threads;
    threads.reserve(n);

    double t_start = now_seconds();
    for (uint64_t i = 0; i < n; i++) {
        threads.emplace_back(gen_thread_count_only, boundaries[i], boundaries[i + 1], &counts[i],
                              &seconds[i]);
    }
    for (auto& t : threads) t.join();
    double t_wall = now_seconds() - t_start;

    uint64_t total = 0, min_c = UINT64_MAX, max_c = 0;
    double min_s = 1e18, max_s = 0.0;
    for (uint64_t i = 0; i < n; i++) {
        total += counts[i];
        if (counts[i] < min_c) min_c = counts[i];
        if (counts[i] > max_c) max_c = counts[i];
        if (seconds[i] < min_s) min_s = seconds[i];
        if (seconds[i] > max_s) max_s = seconds[i];
    }
    double imbalance = (min_c > 0) ? (double)max_c / (double)min_c : -1.0;

    fprintf(stderr, "[%s] WALL=%.3fs  total_primes=%llu  "
                     "per-thread count: min=%llu max=%llu (max/min ratio=%.3f)  "
                     "per-thread time: min=%.3fs max=%.3fs\n",
            label, t_wall, (unsigned long long)total, (unsigned long long)min_c,
            (unsigned long long)max_c, imbalance, min_s, max_s);
    fprintf(stderr, "  per-thread breakdown: ");
    for (uint64_t i = 0; i < n; i++) {
        fprintf(stderr, "%llu%s", (unsigned long long)counts[i], (i + 1 < n) ? "," : "\n");
    }
}

int main(int argc, char** argv) {
    uint64_t lo = 10000000000ULL;
    uint64_t hi = 3162277660169ULL;
    uint64_t n_threads = 24;
    if (argc >= 3) {
        lo = strtoull(argv[1], nullptr, 10);
        hi = strtoull(argv[2], nullptr, 10);
    }
    if (argc >= 4) {
        n_threads = strtoull(argv[3], nullptr, 10);
    }

    fprintf(stderr, "================================================================\n");
    fprintf(stderr, "generation_balance_poc -- equal-width vs equal-count thread split\n");
    fprintf(stderr, "range=[%llu, %llu)  n_threads=%llu\n", (unsigned long long)lo,
            (unsigned long long)hi, (unsigned long long)n_threads);
    fprintf(stderr, "================================================================\n");

    fprintf(stderr, "\n[*] computing equal-count boundaries (numerical Li(x) inversion)...\n");
    double tb0 = now_seconds();
    std::vector<uint64_t> boundaries_b = equal_count_boundaries(lo, hi, n_threads);
    fprintf(stderr, "[*] boundary computation took %.3fs (host-side math only, no primesieve "
                     "calls)\n", now_seconds() - tb0);

    std::vector<uint64_t> boundaries_a = equal_width_boundaries(lo, hi, n_threads);

    fprintf(stderr, "\n--- (A) EQUAL WIDTH (current behavior in every file this series) ---\n");
    run_split("equal-width", boundaries_a, n_threads);

    fprintf(stderr, "\n--- (B) EQUAL COUNT (Mertens/Li(x)-weighted, production's approach) ---\n");
    run_split("equal-count", boundaries_b, n_threads);

    fprintf(stderr, "\n[*] DONE. If (B)'s WALL time is meaningfully lower than (A)'s, the "
                     "equal-width split is a real bottleneck worth fixing in every run_phase-"
                     "style function in this series before drawing further conclusions about "
                     "GPU-side marking strategies.\n");
    return 0;
}
