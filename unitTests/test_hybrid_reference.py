"""Executable correctness and PGS2-safety tests for the hybrid reference backend.

Usage (Windows or WSL):
    python unitTests\\test_hybrid_reference.py
"""

import os
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from hybrid_planner import plan_hybrid_extension
import hybrid_reference as reference
from hybrid_reference import (
    HybridReferenceError,
    sieve_reference_segment,
    write_new_pgs2_floor_window,
    write_new_pgs2_window,
)
from prime_sieve_v1 import read_prime_window


failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"ok:   {message}")
    else:
        failures.append(message)
        print(f"FAIL: {message}")


def ordinary_primes(lo: int, hi: int) -> tuple[int, ...]:
    """Small independent Eratosthenes oracle for this test only."""
    marked = bytearray(hi)
    if hi > 0:
        marked[0] = 1
    if hi > 1:
        marked[1] = 1
    for p in range(2, hi):
        if marked[p]:
            continue
        if p * p < hi:
            for value in range(p * p, hi, p):
                marked[value] = 1
    return tuple(value for value in range(max(2, lo), hi) if not marked[value])


def expects_error(fn, fragment: str, label: str) -> None:
    try:
        fn()
    except HybridReferenceError as exc:
        check(fragment in str(exc), f"{label}: error preserves the safety reason ({str(exc)!r})")
    else:
        check(False, f"{label}: expected HybridReferenceError")


def main() -> int:
    pair_plan = plan_hybrid_extension(
        [2, 3, 5, 7], [11, 13], 17,
        base_is_contiguous=True, filter_is_consecutive=True)
    pair = sieve_reference_segment(pair_plan, [2, 3, 5, 7], 0, pair_plan.limit + 1)
    check(pair.primes == ordinary_primes(0, pair_plan.limit + 1),
          "pair-filter segment agrees value-for-value with an independent ordinary sieve")
    check(dict(pair.tuple_product_counts).get(2, 0) > 0,
          "pair-filter segment recorded actual pair-product eliminations")

    triple_plan = plan_hybrid_extension(
        [2, 3], [5, 7, 11, 13, 17, 19, 23, 29], 31,
        base_is_contiguous=True, filter_is_consecutive=True)
    triple = sieve_reference_segment(triple_plan, [2, 3], 0, triple_plan.limit + 1)
    check(triple.primes == ordinary_primes(0, triple_plan.limit + 1),
          "triple-filter segment agrees value-for-value with an independent ordinary sieve")
    check(dict(triple.tuple_product_counts).get(3, 0) > 0,
          "triple-filter segment recorded actual triple-product eliminations")
    # A later window has many filter products below its left boundary.  They
    # must be ignored for THIS window, not treated as Python negative indexes.
    later_lo = 80
    later = sieve_reference_segment(triple_plan, [2, 3], later_lo, triple_plan.limit + 1)
    check(later.primes == ordinary_primes(later_lo, triple_plan.limit + 1),
          "later segment ignores earlier tuple products without corrupting its bytearray")

    expects_error(
        lambda: sieve_reference_segment(pair_plan, [2, 3, 5], 0, 10),
        "trusted MAIN boundary", "wrong MAIN boundary")
    expects_error(
        lambda: sieve_reference_segment(pair_plan, [2, 3, 5, 7], 0, pair_plan.limit + 2),
        "beyond hybrid plan limit", "segment beyond plan limit")

    with tempfile.TemporaryDirectory(prefix="primeatlas_hybrid_reference_") as folder:
        path = os.path.join(folder, "PRIME_WINDOW_10p2_off_0.bin")
        values = list(pair.primes)
        write_new_pgs2_window(path, values)
        check(read_prime_window(path) == values,
              "new hybrid output round-trips through the ordinary PGS2 reader")
        before = open(path, "rb").read()
        expects_error(lambda: write_new_pgs2_window(path, values),
                      "refusing to overwrite", "existing PGS2 preservation")
        after = open(path, "rb").read()
        check(before == after,
              "an overwrite refusal leaves the existing PGS2 bytes unchanged")
        invalid_path = os.path.join(folder, "invalid.bin")
        expects_error(lambda: write_new_pgs2_window(invalid_path, [3, 2]),
                      "strictly increasing", "invalid PGS2 input")
        check(not os.path.exists(invalid_path),
              "invalid PGS2 input publishes no partial file")
        interrupted_path = os.path.join(folder, "interrupted.bin")
        original_writer = reference.write_prime_window
        try:
            def _interrupted_writer(*_args, **_kwargs):
                raise OSError("simulated interrupted PGS2 write")

            reference.write_prime_window = _interrupted_writer
            try:
                write_new_pgs2_window(interrupted_path, values)
            except OSError:
                pass
            else:
                check(False, "interrupted PGS2 write propagates its failure")
        finally:
            reference.write_prime_window = original_writer
        check(not os.path.exists(interrupted_path)
              and not any(name.startswith(".interrupted.bin.tmp-") for name in os.listdir(folder)),
              "interrupted PGS2 write leaves neither a published nor a temporary file")
        sharded = write_new_pgs2_floor_window(folder, 12, 3, 10_000_000, values)
        check(sharded.name == "PRIME_WINDOW_10p12_off_30M.bin"
              and sharded.parent.name == "shard_00000"
              and read_prime_window(str(sharded)) == values,
              "hybrid output uses the ordinary PGS2 filename, shard and reader contract")

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
