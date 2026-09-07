"""Reproducible whole-pipeline benchmark for the native hybrid tuple filter.

Example matching the original 997/10,000 proof-of-concept scale:
    cd /mnt/h/PrimeAtlas_gpt/primeAtlas
    python3 unitTests/benchmark_hybrid_native.py --main-limit 997 --filter-count 10000

This is deliberately a measurement script, not a pass/fail unit test.  It verifies
the final count independently with libprimesieve and reports every component that
belongs to the hybrid operation; it never compares just the tuple-filter time.
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

from hybrid_planner import plan_hybrid_extension
from hybrid_sieve import bootstrap_following_primes
from hybrid_native import sieve_native_segment_timed
from prime_sieve_primesieve import generate_primes_in_range


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-limit", type=int, default=997)
    parser.add_argument("--filter-count", type=int, default=10_000)
    parser.add_argument("--segment-size", type=int, default=10_000_000)
    args = parser.parse_args()
    if args.main_limit < 2 or args.filter_count < 1 or args.segment_size < 1:
        parser.error("all numeric parameters must be positive (main-limit >= 2)")

    started = time.perf_counter()
    bootstrap_started = time.perf_counter()
    main_primes = generate_primes_in_range(2, args.main_limit + 1)
    if not main_primes:
        parser.error("main-limit contains no prime")
    bootstrap = bootstrap_following_primes(main_primes[-1], args.filter_count)
    plan = plan_hybrid_extension(main_primes, bootstrap[:-1], bootstrap[-1],
                                 base_is_contiguous=True, filter_is_consecutive=True)
    bootstrap_seconds = time.perf_counter() - bootstrap_started

    main_seconds = 0.0
    filter_seconds = 0.0
    materialize_seconds = 0.0
    hybrid_count = 0
    lo = 0
    while lo <= plan.limit:
        hi = min(plan.limit + 1, lo + args.segment_size)
        materialize_started = time.perf_counter()
        result, segment_main, segment_filter = sieve_native_segment_timed(plan, main_primes, lo, hi)
        materialize_seconds += time.perf_counter() - materialize_started - segment_main - segment_filter
        main_seconds += segment_main
        filter_seconds += segment_filter
        hybrid_count += len(result.primes)
        lo = hi

    hybrid_total_seconds = time.perf_counter() - started
    primesieve_started = time.perf_counter()
    primesieve_count = len(generate_primes_in_range(0, plan.limit + 1))
    primesieve_seconds = time.perf_counter() - primesieve_started

    print("# HYBRID NATIVE WHOLE-PIPELINE BENCHMARK")
    print(f"MAIN <= {plan.main_last_prime:,}; filter {plan.filter_start:,}..{plan.filter_end:,}; "
          f"next={plan.next_prime_after_filter:,}; N={plan.limit:,}; tuples<= {plan.required_tuple_order}")
    print(f"bootstrap + plan: {bootstrap_seconds:.6f}s")
    print(f"MAIN marking:     {main_seconds:.6f}s")
    print(f"tuple filter C:  {filter_seconds:.6f}s")
    print(f"result build:     {materialize_seconds:.6f}s")
    print(f"hybrid total:     {hybrid_total_seconds:.6f}s; pi(N)={hybrid_count:,}")
    print(f"primesieve count: {primesieve_count:,} ({primesieve_seconds:.6f}s)")
    print("✅ COUNT AGREES" if hybrid_count == primesieve_count else "❌ COUNT MISMATCH")
    return 0 if hybrid_count == primesieve_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
