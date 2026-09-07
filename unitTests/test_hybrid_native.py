"""WSL test for native tuple filtering against the Phase-3 reference.

Build first:
    cd /mnt/h/PrimeAtlas_gpt/primeAtlas/prime_sieve
    gcc -O3 -shared -fPIC hybrid_filter_engine.c -o hybrid_filter_engine.so

Then run:
    cd /mnt/h/PrimeAtlas_gpt/primeAtlas
    python3 unitTests/test_hybrid_native.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

from hybrid_planner import plan_hybrid_extension
from hybrid_native import sieve_native_segment
from hybrid_reference import sieve_reference_segment
from prime_sieve_primesieve import generate_primes_in_range


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def main():
    passed = True
    cases = [
        ([2, 3, 5, 7], [11, 13], 17),
        ([2, 3], [5, 7, 11, 13, 17, 19, 23, 29], 31),
    ]
    for main_primes, filter_primes, successor in cases:
        plan = plan_hybrid_extension(main_primes, filter_primes, successor,
                                     base_is_contiguous=True, filter_is_consecutive=True)
        for lo in (0, max(1, plan.limit // 2)):
            reference = sieve_reference_segment(plan, main_primes, lo, plan.limit + 1)
            native = sieve_native_segment(plan, main_primes, lo, plan.limit + 1)
            if native.primes != reference.primes:
                missing = sorted(set(reference.primes) - set(native.primes))[:12]
                extra = sorted(set(native.primes) - set(reference.primes))[:12]
                print(f"       native mismatch detail: missing={missing}, extra={extra}")
            passed &= check(native.primes == reference.primes,
                            f"native survivors match reference for lo={lo}, tuples<={plan.required_tuple_order}")
            passed &= check(native.tuple_product_counts == reference.tuple_product_counts,
                            f"native tuple counters match reference for lo={lo}")
        direct = generate_primes_in_range(0, plan.limit + 1)
        native_full = sieve_native_segment(plan, main_primes, 0, plan.limit + 1)
        passed &= check(list(native_full.primes) == direct,
                        f"native output matches libprimesieve through N={plan.limit}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
