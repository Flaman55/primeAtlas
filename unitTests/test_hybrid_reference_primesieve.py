"""Optional-library integration test: hybrid reference output vs libprimesieve.

Run this in the same WSL environment that has PrimeAtlas's libprimesieve
dependency installed.  Unlike test_hybrid_reference.py, this script deliberately
uses the real library and is therefore the final small-range correctness check
before the reference backend may be committed.

Usage (WSL):
    python3 unitTests/test_hybrid_reference_primesieve.py
"""

import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from hybrid_planner import plan_hybrid_extension
from hybrid_reference import sieve_reference_segment
from prime_sieve_primesieve import generate_primes_in_range


def check(condition: bool, message: str) -> None:
    print(("ok:   " if condition else "FAIL: ") + message)
    if not condition:
        raise SystemExit(1)


def main() -> int:
    cases = [
        ([2, 3, 5, 7], [11, 13], 17),
        ([2, 3], [5, 7, 11, 13, 17, 19, 23, 29], 31),
        ([2], [3, 5, 7, 11, 13, 17, 19, 23, 29], 31),
    ]
    for main_primes, filter_primes, successor in cases:
        plan = plan_hybrid_extension(
            main_primes, filter_primes, successor,
            base_is_contiguous=True, filter_is_consecutive=True)
        actual = sieve_reference_segment(plan, main_primes, 0, plan.limit + 1).primes
        expected = tuple(generate_primes_in_range(0, plan.limit + 1))
        check(actual == expected,
              f"hybrid reference matches libprimesieve value-for-value through N={plan.limit}")
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
