"""Reference CLI for PrimeAtlas's storage-backed hybrid extension.

Usage: ``hybrid_sieve.py <floor> <iterations> <filter_prime_count> <write_files 0|1>``.

This is deliberately a correctness-first bridge to :mod:`hybrid_reference`, not
the native tuple-filter backend.  It accepts only a continuous PGS2 prefix from
floor 0 through the selected continuation point.  That check is material: an
arbitrary high floor alone is not a valid MAIN base, because it does not contain
all primes below its last prime.
"""

from __future__ import annotations

import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from hybrid_planner import HybridPlanError, plan_hybrid_extension
from hybrid_reference import HybridReferenceError, sieve_reference_segment, write_new_pgs2_floor_window
from prime_sieve_primesieve import generate_primes_in_range, write_benchmark_row, write_scan_metrics_handoff
from prime_sieve_v1 import format_offset, read_prime_window
import window_sharding


WINDOW_M = 10_000_000
LOW_FLOOR_CUTOFF = 7


class HybridSieveError(RuntimeError):
    """Raised for an unsafe or incomplete storage-backed hybrid request."""


@dataclass(frozen=True)
class MainPrefix:
    primes: tuple[int, ...]
    coverage_hi: int
    current_floor: int
    next_target_idx: int


def _floor_window_count(floor: int, window_m: int) -> int:
    return (9 * 10 ** floor) // window_m


def _window_path(portal: Path, floor: int, target_idx: int, window_m: int) -> Path:
    source = portal / f"10p{floor}" / "source_primes"
    offset = target_idx * window_m
    shard = Path(window_sharding.shard_dir(str(source), target_idx))
    return shard / f"PRIME_WINDOW_10p{floor}_off_{format_offset(offset)}.bin"


def _read_checked_window(path: Path, lo: int, hi: int) -> list[int]:
    if not path.is_file():
        raise HybridSieveError(f"missing required MAIN window: {path}")
    try:
        values = read_prime_window(str(path))
    except Exception as exc:  # PGS2 decoding error must not be turned into a guessed base.
        raise HybridSieveError(f"cannot read MAIN PGS2 window {path}: {exc}") from exc
    if any(value < lo or value >= hi for value in values):
        raise HybridSieveError(f"MAIN window contains value outside its numeric range: {path}")
    if any(right <= left for left, right in zip(values, values[1:])):
        raise HybridSieveError(f"MAIN window is not strictly ordered: {path}")
    return values


def load_contiguous_main_prefix(portal_folder: str | os.PathLike[str], requested_floor: int,
                                window_m: int = WINDOW_M) -> MainPrefix:
    """Load and verify the exact PGS2 prefix usable as MAIN.

    Earlier floors must be complete.  On the selected floor only an initial
    consecutive run is permitted; an interior later file is an explicit error,
    not a reason to skip ahead.  This is intentionally memory-heavy because it
    serves the reference backend; the native implementation will stream/compact
    this information separately.
    """
    if requested_floor < 0 or window_m < 1:
        raise HybridSieveError("floor must be non-negative and window_m positive")
    portal = Path(portal_folder)
    all_primes: list[int] = []
    for floor in range(requested_floor + 1):
        base = 10 ** floor
        if floor < LOW_FLOOR_CUTOFF:
            expected = 1
        else:
            expected = _floor_window_count(floor, window_m)
        count = 0
        while count < expected and _window_path(portal, floor, count, window_m).is_file():
            lo = base if floor < LOW_FLOOR_CUTOFF else base + count * window_m
            hi = 10 ** (floor + 1) if floor < LOW_FLOOR_CUTOFF else lo + window_m
            all_primes.extend(_read_checked_window(_window_path(portal, floor, count, window_m), lo, hi))
            count += 1
        if floor < requested_floor and count != expected:
            raise HybridSieveError(f"MAIN prefix stops inside completed prerequisite floor 10p{floor}")
        if floor == requested_floor:
            # Any later file proves a gap rather than an ordinary continuation boundary.
            source = portal / f"10p{floor}" / "source_primes"
            # list_sharded_files() intentionally returns ordinary string paths,
            # while this runner otherwise uses pathlib internally.
            present = {Path(path).name for _name, path in window_sharding.list_sharded_files(str(source))}
            expected_names = {_window_path(portal, floor, index, window_m).name for index in range(count)}
            if any(name.startswith("PRIME_WINDOW_") and name not in expected_names for name in present):
                raise HybridSieveError(f"MAIN contains a gap in selected floor 10p{floor}")
            if count == 0:
                raise HybridSieveError(f"selected floor 10p{floor} has no continuous MAIN window")
            coverage_hi = 10 ** (floor + 1) if floor < LOW_FLOOR_CUTOFF else base + count * window_m
            if count == expected:
                # Complete floor: the next stage must be filed under the next floor.
                return MainPrefix(tuple(all_primes), coverage_hi, floor + 1, 0)
            return MainPrefix(tuple(all_primes), coverage_hi, floor, count)
    raise AssertionError("unreachable")


def bootstrap_following_primes(main_last_prime: int, count: int) -> tuple[int, ...]:
    """Obtain exactly ``count`` filter primes plus their successor using libprimesieve."""
    wanted = count + 1
    found: list[int] = []
    lo = main_last_prime + 1
    # A conservative PNT-sized first chunk; repeat instead of assuming any gap bound.
    width = max(128, int((math.log(max(3, lo)) + 3) * wanted * 2))
    while len(found) < wanted:
        hi = lo + width
        batch = generate_primes_in_range(lo, hi)
        found.extend(batch)
        lo = hi
        width *= 2
    return tuple(found[:wanted])


def _stage_complete_window_hi(prefix: MainPrefix, limit: int, window_m: int) -> int:
    """Return the last *whole* Atlas window proven by this stage's mathematical limit."""
    floor_end = 10 ** (prefix.current_floor + 1)
    candidate_hi = min(limit + 1, floor_end)
    full = prefix.coverage_hi + ((candidate_hi - prefix.coverage_hi) // window_m) * window_m
    if full <= prefix.coverage_hi:
        raise HybridSieveError(
            "filter stage does not reach one complete Atlas window; increase k_adv or use a smaller MAIN boundary")
    return full


def run_hybrid_sieve(base_exponent: int, iterations: int, filter_prime_count: int, write_files: bool,
                     portal_folder: str | os.PathLike[str], window_m: int = WINDOW_M) -> None:
    """Run one or more safe reference stages and publish only complete new windows."""
    if iterations < 1 or filter_prime_count < 1:
        raise HybridSieveError("iterations and filter_prime_count must be positive")
    prefix = load_contiguous_main_prefix(portal_folder, base_exponent, window_m)
    all_main = list(prefix.primes)
    if not all_main or all_main[0] != 2:
        raise HybridSieveError("MAIN prefix must begin with prime 2")
    started = time.perf_counter()
    total_primes = 0
    total_windows = 0
    native_backend = False
    native_segment = None
    try:
        from hybrid_native import native_library_available, sieve_native_segment_timed
        if native_library_available():
            native_segment = sieve_native_segment_timed
            native_backend = True
    except (ImportError, OSError):
        # The reference path remains a complete correctness fallback when a C
        # compiler/library is unavailable on the current machine.
        native_backend = False
    print("[HYBRID] backend: native tuple filter" if native_backend
          else "[HYBRID] backend: Python reference tuple filter", flush=True)
    for stage in range(1, iterations + 1):
        stage_started = time.perf_counter()
        # MAIN is immutable throughout this stage.  Its newly found survivors
        # become eligible MAIN primes only for the following stage and must not
        # silently alter the boundary a that the current plan proves.
        stage_main = tuple(all_main)
        bootstrap_started = time.perf_counter()
        bootstrap = bootstrap_following_primes(stage_main[-1], filter_prime_count)
        bootstrap_seconds = time.perf_counter() - bootstrap_started
        plan = plan_hybrid_extension(stage_main, bootstrap[:-1], bootstrap[-1],
                                     base_is_contiguous=True, filter_is_consecutive=True)
        write_hi = _stage_complete_window_hi(prefix, plan.limit, window_m)
        print(f"[HYBRID] stage {stage}/{iterations}: [{prefix.coverage_hi:,}, {write_hi:,}) "
              f"MAIN<= {plan.main_last_prime:,}; filter {plan.filter_start:,}..{plan.filter_end:,}; "
              f"tuples<= {plan.required_tuple_order}", flush=True)
        stage_tuple_counts: dict[int, int] = {order: 0 for order in plan.tuple_orders}
        stage_main_seconds = 0.0
        stage_filter_seconds = 0.0
        stage_write_seconds = 0.0
        lo = prefix.coverage_hi
        while lo < write_hi:
            hi = lo + window_m
            if native_backend:
                result, main_seconds, filter_seconds = native_segment(plan, stage_main, lo, hi)
                stage_main_seconds += main_seconds
                stage_filter_seconds += filter_seconds
            else:
                result = sieve_reference_segment(plan, stage_main, lo, hi)
            target_idx = (lo - 10 ** prefix.current_floor) // window_m
            if write_files:
                write_started = time.perf_counter()
                write_new_pgs2_floor_window(portal_folder, prefix.current_floor, target_idx,
                                            window_m, result.primes)
                stage_write_seconds += time.perf_counter() - write_started
            all_main.extend(result.primes)
            total_primes += len(result.primes)
            total_windows += 1
            for order, count in result.tuple_product_counts:
                stage_tuple_counts[order] += count
            lo = hi
        print("[HYBRID] stage tuples: " + ", ".join(
            f"{order}: {stage_tuple_counts[order]:,}" for order in sorted(stage_tuple_counts)), flush=True)
        if native_backend:
            print(f"[HYBRID] stage timing: bootstrap {bootstrap_seconds:.3f}s; "
                  f"MAIN {stage_main_seconds:.3f}s; filter {stage_filter_seconds:.3f}s; "
                  f"write {stage_write_seconds:.3f}s; total {time.perf_counter() - stage_started:.3f}s",
                  flush=True)
        else:
            print(f"[HYBRID] stage timing: bootstrap {bootstrap_seconds:.3f}s; "
                  f"reference sieve+filter; write {stage_write_seconds:.3f}s; "
                  f"total {time.perf_counter() - stage_started:.3f}s", flush=True)
        prefix = MainPrefix(tuple(all_main), write_hi, prefix.current_floor,
                            prefix.next_target_idx + (write_hi - prefix.coverage_hi) // window_m)
        if prefix.coverage_hi == 10 ** (prefix.current_floor + 1) and stage < iterations:
            prefix = MainPrefix(prefix.primes, prefix.coverage_hi, prefix.current_floor + 1, 0)
    elapsed = time.perf_counter() - started
    print(f"[HYBRID] done: {total_primes:,} primes, {total_windows} window(s), {elapsed:.3f}s", flush=True)
    write_scan_metrics_handoff(str(portal_folder), total_primes_found=total_primes,
                               windows_processed=total_windows, write_files=write_files)
    write_benchmark_row(base_exponent, 0, total_windows, elapsed, total_primes, total_windows,
                        write_files, str(portal_folder))


def _main(argv: Iterable[str]) -> int:
    args = list(argv)
    if len(args) != 4:
        print("Usage: hybrid_sieve.py <floor> <iterations> <filter_prime_count> <write_files 0|1>")
        return 2
    try:
        floor, iterations, count, write_raw = (int(value) for value in args)
        if write_raw not in (0, 1):
            raise ValueError("write_files must be 0 or 1")
        portal = os.environ.get("CONSTELLATION_PORTAL_DIR", "/mnt/c/CONSTELLATION_PORTAL")
        run_hybrid_sieve(floor, iterations, count, bool(write_raw), portal)
        return 0
    except (ValueError, HybridPlanError, HybridReferenceError, HybridSieveError, RuntimeError) as exc:
        print(f"[HYBRID] ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
