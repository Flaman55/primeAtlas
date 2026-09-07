"""Correctness-first implementation of one hybrid sieve segment.

This is intentionally a reference backend, not the eventual high-throughput C
engine.  It exists to make the hybrid proof executable and to provide a stable
oracle for Phase 5.  It marks one requested numeric segment with two independent
sources of compositeness:

* every multiple of each trusted MAIN prime; and
* every filter-prime product of each tuple order the validated plan requires.

The final survivors can be written through the normal PGS2 writer.  The helper
never overwrites an existing window: it writes a sibling temporary file then
atomically publishes it with ``os.replace`` only after a complete encoding is
available.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from hybrid_planner import HybridExtensionPlan
from prime_sieve_v1 import format_offset, read_prime_window, write_prime_window
import window_sharding


class HybridReferenceError(ValueError):
    """Raised when a reference segment or PGS2 publication is unsafe."""


@dataclass(frozen=True)
class ReferenceSegmentResult:
    lo: int
    hi: int
    primes: tuple[int, ...]
    tuple_product_counts: tuple[tuple[int, int], ...]


def _strict_positive_primes(values: Iterable[int], field: str) -> tuple[int, ...]:
    result = tuple(values)
    if not result:
        raise HybridReferenceError(f"{field} must contain at least one prime")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 2 for value in result):
        raise HybridReferenceError(f"{field} must contain integer values >= 2")
    if any(right <= left for left, right in zip(result, result[1:])):
        raise HybridReferenceError(f"{field} must be strictly increasing")
    return result


def _mark_main_composites(bits: bytearray, lo: int, hi: int, main_primes: tuple[int, ...]) -> None:
    for prime in main_primes:
        # p itself must remain a survivor if a diagnostic segment includes it.
        first = max(prime * prime, ((lo + prime - 1) // prime) * prime)
        for value in range(first, hi, prime):
            bits[value - lo] = 1


def _mark_filter_tuple_products(
    bits: bytearray,
    lo: int,
    hi: int,
    plan: HybridExtensionPlan,
) -> dict[int, int]:
    """Mark all nondecreasing filter-prime products that land in ``[lo, hi)``.

    Reusing the same index permits powers such as p³; advancing it prevents
    duplicate permutations.  Unique prime factorisation means each product is
    visited exactly once under that rule.
    """
    counts = {order: 0 for order in plan.tuple_orders}
    values = plan.filter_primes

    def extend(product: int, first_index: int, depth: int) -> None:
        for index in range(first_index, len(values)):
            prime = values[index]
            # Division form avoids multiplying a value that would already exceed hi.
            if product > (hi - 1) // prime:
                break
            candidate = product * prime
            next_depth = depth + 1
            if next_depth >= 2:
                # A tuple product can precede this particular segment while a
                # longer product made by extending it still lands inside it.  Do
                # not use a negative bytearray index for the earlier product.
                if candidate >= lo:
                    bits[candidate - lo] = 1
                    counts[next_depth] += 1
            if next_depth < plan.required_tuple_order:
                extend(candidate, index, next_depth)

    extend(1, 0, 0)
    return counts


def sieve_reference_segment(
    plan: HybridExtensionPlan,
    main_primes: Iterable[int],
    lo: int,
    hi: int,
) -> ReferenceSegmentResult:
    """Return all primes in one half-open segment inside a hybrid plan's limit.

    The runner must split a large extension into practical windows before calling
    this function.  A deliberately bounded bytearray makes the reference model
    easy to inspect and prevents it from quietly pretending to be a huge-range
    production engine.
    """
    if isinstance(lo, bool) or isinstance(hi, bool) or not isinstance(lo, int) or not isinstance(hi, int):
        raise HybridReferenceError("segment bounds must be integers")
    if lo < 0 or hi <= lo:
        raise HybridReferenceError("segment must be a non-empty non-negative [lo, hi) range")
    if hi - 1 > plan.limit:
        raise HybridReferenceError(
            f"segment ends at {hi - 1}, beyond hybrid plan limit {plan.limit}")

    main = _strict_positive_primes(main_primes, "main_primes")
    if main[-1] != plan.main_last_prime:
        raise HybridReferenceError(
            "main_primes must end at the plan's trusted MAIN boundary "
            f"{plan.main_last_prime}")

    composite = bytearray(hi - lo)
    for value in range(lo, min(hi, 2)):
        composite[value - lo] = 1
    _mark_main_composites(composite, lo, hi, main)
    tuple_counts = _mark_filter_tuple_products(composite, lo, hi, plan)
    primes = tuple(lo + offset for offset, marked in enumerate(composite) if not marked)
    return ReferenceSegmentResult(
        lo=lo,
        hi=hi,
        primes=primes,
        tuple_product_counts=tuple(sorted(tuple_counts.items())),
    )


def write_new_pgs2_window(path: str | os.PathLike[str], primes: Iterable[int]) -> None:
    """Publish one new PGS2 window atomically without changing an existing file."""
    target = Path(path)
    # Empty PGS2 windows are valid in the established format, so publication
    # deliberately permits an empty sequence even though MAIN/filter inputs may not
    # be empty.  A non-empty value list still needs the same strict ordering proof.
    values = tuple(primes)
    if values:
        _strict_positive_primes(values, "primes")
    if target.exists():
        raise HybridReferenceError(f"refusing to overwrite existing PGS2 window: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}-{time.time_ns()}")
    try:
        write_prime_window(str(temporary), list(values))
        # Re-read before publication: a failure cannot replace a valid existing window.
        if read_prime_window(str(temporary)) != list(values):
            raise HybridReferenceError("temporary PGS2 verification failed")
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_new_pgs2_floor_window(
    portal_folder: str | os.PathLike[str],
    base_exponent: int,
    target_idx: int,
    window_m: int,
    primes: Iterable[int],
) -> Path:
    """Write a new window using Atlas's ordinary PGS2 name and shard layout.

    The caller owns numeric-range validation; this helper owns only the stable
    storage convention shared by all engines.  Keeping it here means Phase 3
    proves that hybrid output is consumable without Storage/Constellations changes.
    """
    if (isinstance(base_exponent, bool) or not isinstance(base_exponent, int) or base_exponent < 0
            or isinstance(target_idx, bool) or not isinstance(target_idx, int) or target_idx < 0
            or isinstance(window_m, bool) or not isinstance(window_m, int) or window_m < 1):
        raise HybridReferenceError("floor, target_idx and window_m must be non-negative valid integers")
    offset = target_idx * window_m
    source_folder = Path(portal_folder) / f"10p{base_exponent}" / "source_primes"
    shard_folder = Path(window_sharding.shard_dir(str(source_folder), target_idx))
    filename = f"PRIME_WINDOW_10p{base_exponent}_off_{format_offset(offset)}.bin"
    path = shard_folder / filename
    write_new_pgs2_window(path, primes)
    return path
