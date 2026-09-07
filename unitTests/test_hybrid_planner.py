"""Executable tests for the pure hybrid-extension planner.

No WSL, PGS2 storage, C backend or primality library is needed here.  These
tests pin down the integer boundary proof which later phases may optimize but
must not weaken.

Usage (Windows or WSL):
    python unitTests\\test_hybrid_planner.py
"""

import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from hybrid_planner import HybridPlanError, plan_hybrid_extension, required_tuple_order


failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"ok:   {message}")
    else:
        failures.append(message)
        print(f"FAIL: {message}")


def expects_error(fn, expected_fragment: str, label: str) -> None:
    try:
        fn()
    except HybridPlanError as exc:
        check(expected_fragment in str(exc),
              f"{label}: error explains the violated invariant (got {str(exc)!r})")
    else:
        check(False, f"{label}: expected HybridPlanError")


def main() -> int:
    # Exact power thresholds: no floating log rounding at b**3 = 125.
    check(required_tuple_order(5, 124) == 2,
          "N=124 below 5**3 requires pairs only")
    check(required_tuple_order(5, 125) == 3,
          "N=125 exactly at 5**3 requires triples")
    check(required_tuple_order(3, 80) == 3,
          "N=80 below 3**4 requires triples only")
    check(required_tuple_order(3, 81) == 4,
          "N=81 exactly at 3**4 requires four-tuples")

    # Pair plan: a=7, b=11, c=13, d=17, N=11*17-1=186.
    pair = plan_hybrid_extension(
        [2, 3, 5, 7], [11, 13], 17,
        base_is_contiguous=True, filter_is_consecutive=True)
    check(pair.limit == 186 and pair.required_tuple_order == 2
          and pair.tuple_orders == (2,),
          f"pair plan derives N=186 and exactly order (2,), got {pair!r}")
    check(pair.bootstrap_bounds == (11, 13),
          "pair plan exposes the inclusive bootstrap interval [b,c]")

    # Triple plan: b=5, c=29, d=31 gives N=154; 5**3 <= N < 5**4.
    triple = plan_hybrid_extension(
        [2, 3], [5, 7, 11, 13, 17, 19, 23, 29], 31,
        base_is_contiguous=True, filter_is_consecutive=True)
    check(triple.limit == 154 and triple.required_tuple_order == 3
          and triple.tuple_orders == (2, 3),
          f"triple plan derives all required orders (2,3), got {triple!r}")

    # Four-factor plan: b=3, c=29, d=31 gives N=92; 3**4 <= N < 3**5.
    quadruple = plan_hybrid_extension(
        [2], [3, 5, 7, 11, 13, 17, 19, 23, 29], 31,
        base_is_contiguous=True, filter_is_consecutive=True)
    check(quadruple.limit == 92 and quadruple.required_tuple_order == 4
          and quadruple.tuple_orders == (2, 3, 4),
          f"four-factor plan derives all required orders (2,3,4), got {quadruple!r}")
    check(quadruple == plan_hybrid_extension(
        [2], [3, 5, 7, 11, 13, 17, 19, 23, 29], 31,
        base_is_contiguous=True, filter_is_consecutive=True),
        "identical trusted inputs produce an immutable deterministic plan")

    expects_error(
        lambda: plan_hybrid_extension(
            [2, 3], [5, 7], 11,
            base_is_contiguous=False, filter_is_consecutive=True),
        "contiguous MAIN base", "gapped base")
    expects_error(
        lambda: plan_hybrid_extension(
            [2, 3, 5], [5, 7], 11,
            base_is_contiguous=True, filter_is_consecutive=True),
        "strictly after", "filter overlapping MAIN")
    expects_error(
        lambda: plan_hybrid_extension(
            [2, 3], [5, 11, 7], 13,
            base_is_contiguous=True, filter_is_consecutive=True),
        "strictly increasing", "unordered filter prefix")
    expects_error(
        lambda: plan_hybrid_extension(
            [2, 3], [5, 7], 7,
            base_is_contiguous=True, filter_is_consecutive=True),
        "strictly after", "missing next prime after filter")
    expects_error(
        lambda: plan_hybrid_extension(
            [2, 3], [5, 7, 11, 13, 17, 19, 23, 29], 31,
            base_is_contiguous=True, filter_is_consecutive=True, tuple_order_cap=2),
        "requires tuple order 3", "backend tuple-order cap")
    expects_error(
        lambda: plan_hybrid_extension(
            [2, 3], [5, 7], 11,
            base_is_contiguous=True, filter_is_consecutive=False),
        "consecutive filter-prime prefix", "incomplete filter prefix")

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
