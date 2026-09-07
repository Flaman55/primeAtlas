"""Pure planning rules for PrimeAtlas's hybrid prime-filter extension.

This module deliberately does *not* sieve, call libprimesieve, read PGS2 files or
construct tuple products.  It turns already trusted prime boundaries into one
immutable plan.  Keeping that mathematical contract separate lets the later WSL
runner and C backend share exactly the same safety checks.

Let ``a`` be the last prime in a contiguous existing MAIN base, ``b`` the first
trusted bootstrap/filter prime after it, ``c`` the last prime in the requested
filter prefix, and ``d`` the next trusted prime after ``c``.  The extension is
bounded by

    N = b * d - 1.

For a composite ``n <= N`` whose least prime factor is greater than ``a``, all
of its prime factors are below ``d``: otherwise ``n >= b*d``.  Consequently all
such factors belong to the trusted filter prefix ``[b, c]``.  The filter must
cover every factor count ``r`` for which ``b**r <= N``.  MAIN still marks every
multiple of every prime <= ``a`` in the new numeric range.

``base_is_contiguous`` is an explicit caller assertion.  A finite list of prime
values cannot prove that a storage prefix has no missing PGS2 window; Phase 3's
storage adapter will establish that fact from window coverage before it calls
this pure planner.  ``filter_is_consecutive`` is the matching bootstrap
assertion: the supplied list begins with the immediate successor of MAIN and
ends immediately before ``next_prime_after_filter``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class HybridPlanError(ValueError):
    """Raised when a proposed hybrid extension lacks a complete proof contract."""


def _as_strictly_increasing_positive_ints(values: Iterable[int], field: str) -> tuple[int, ...]:
    result = tuple(values)
    if not result:
        raise HybridPlanError(f"{field} must contain at least one trusted prime")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 2 for value in result):
        raise HybridPlanError(f"{field} must contain integer values >= 2")
    if any(right <= left for left, right in zip(result, result[1:])):
        raise HybridPlanError(f"{field} must be strictly increasing")
    return result


def required_tuple_order(filter_start: int, limit: int) -> int:
    """Return the largest ``r`` such that ``filter_start**r <= limit``.

    This uses only exact integer division, not floating-point logarithms, so a
    limit exactly equal to a power is never assigned to the wrong tuple order.
    ``r`` is at least two for every valid hybrid plan, but this low-level helper
    also has a useful definition for smaller arbitrary limits.
    """
    if isinstance(filter_start, bool) or not isinstance(filter_start, int) or filter_start < 2:
        raise HybridPlanError("filter_start must be an integer >= 2")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise HybridPlanError("limit must be a positive integer")

    order = 0
    power = 1
    while power <= limit // filter_start:
        power *= filter_start
        order += 1
    return order


@dataclass(frozen=True)
class HybridExtensionPlan:
    """Validated, backend-neutral contract for one hybrid extension stage."""

    main_last_prime: int
    filter_primes: tuple[int, ...]
    next_prime_after_filter: int
    limit: int
    required_tuple_order: int
    tuple_orders: tuple[int, ...]

    @property
    def filter_start(self) -> int:
        return self.filter_primes[0]

    @property
    def filter_end(self) -> int:
        return self.filter_primes[-1]

    @property
    def bootstrap_bounds(self) -> tuple[int, int]:
        """Inclusive numeric interval whose primes supply ``filter_primes``."""
        return self.filter_start, self.filter_end


def plan_hybrid_extension(
    main_primes: Iterable[int],
    filter_primes: Iterable[int],
    next_prime_after_filter: int,
    *,
    base_is_contiguous: bool,
    filter_is_consecutive: bool,
    tuple_order_cap: int | None = None,
) -> HybridExtensionPlan:
    """Validate and create a single hybrid-stage plan.

    ``main_primes`` and ``filter_primes`` are trusted prime lists supplied by
    the storage/bootstrap layers; primality is intentionally not recomputed
    here.  Their boundaries are checked rigorously.  The caller must establish
    that MAIN represents a complete continuous magazyn prefix by passing
    ``base_is_contiguous=True``.  Likewise the bootstrap layer must establish
    that no prime is skipped between MAIN, the filter list and its successor by
    passing ``filter_is_consecutive=True``.

    ``tuple_order_cap`` represents a backend implementation limit.  Refusing a
    plan that needs triples/four-tuples beyond that cap is mandatory: silently
    running only pairs would emit composites as primes.
    """
    if base_is_contiguous is not True:
        raise HybridPlanError("hybrid extension requires a contiguous MAIN base")
    if filter_is_consecutive is not True:
        raise HybridPlanError("hybrid extension requires a consecutive filter-prime prefix")

    main = _as_strictly_increasing_positive_ints(main_primes, "main_primes")
    advanced = _as_strictly_increasing_positive_ints(filter_primes, "filter_primes")
    return plan_hybrid_boundaries(
        main[-1], advanced, next_prime_after_filter,
        base_is_contiguous=base_is_contiguous,
        filter_is_consecutive=filter_is_consecutive,
        tuple_order_cap=tuple_order_cap)


def plan_hybrid_boundaries(
    main_last_prime: int,
    filter_primes: Iterable[int],
    next_prime_after_filter: int,
    *,
    base_is_contiguous: bool,
    filter_is_consecutive: bool,
    tuple_order_cap: int | None = None,
) -> HybridExtensionPlan:
    """Create the same proof contract from trusted MAIN/filter boundaries.

    Native MAIN marks the complete interval ``P_{<= a}`` internally.  At high
    floors, materialising every MAIN prime in Python only to recover its known
    last boundary costs more than the sieve.  This form preserves the exact
    proof while avoiding that representation cost.
    """
    if base_is_contiguous is not True:
        raise HybridPlanError("hybrid extension requires a contiguous MAIN base")
    if filter_is_consecutive is not True:
        raise HybridPlanError("hybrid extension requires a consecutive filter-prime prefix")
    if (isinstance(main_last_prime, bool) or not isinstance(main_last_prime, int)
            or main_last_prime < 2):
        raise HybridPlanError("main_last_prime must be a trusted prime integer >= 2")
    a = main_last_prime
    advanced = _as_strictly_increasing_positive_ints(filter_primes, "filter_primes")
    b = advanced[0]
    c = advanced[-1]

    if b <= a:
        raise HybridPlanError("filter_primes must begin strictly after the MAIN base")
    if (isinstance(next_prime_after_filter, bool)
            or not isinstance(next_prime_after_filter, int)
            or next_prime_after_filter <= c):
        raise HybridPlanError("next_prime_after_filter must be an integer strictly after filter_primes")
    if tuple_order_cap is not None:
        if (isinstance(tuple_order_cap, bool)
                or not isinstance(tuple_order_cap, int)
                or tuple_order_cap < 2):
            raise HybridPlanError("tuple_order_cap must be None or an integer >= 2")

    limit = b * next_prime_after_filter - 1
    order = required_tuple_order(b, limit)
    if order < 2:
        raise HybridPlanError("hybrid bound unexpectedly requires fewer than pair products")
    if tuple_order_cap is not None and order > tuple_order_cap:
        raise HybridPlanError(
            f"extension through {limit} requires tuple order {order}, "
            f"but the backend cap is {tuple_order_cap}")

    return HybridExtensionPlan(
        main_last_prime=a,
        filter_primes=advanced,
        next_prime_after_filter=next_prime_after_filter,
        limit=limit,
        required_tuple_order=order,
        tuple_orders=tuple(range(2, order + 1)),
    )
