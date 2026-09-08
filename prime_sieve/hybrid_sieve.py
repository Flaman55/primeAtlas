"""Hybrid generator CLI for PrimeAtlas.

Usage: ``hybrid_sieve.py <floor> <iterations> <width_windows>
<filter_prime_count> <write_files 0|1>``.

The mathematical MAIN/filter base is planned independently.  PGS2 storage is
only the normal output cache: empty, partial and gapped storage are valid, and
only missing complete windows are written.  The native v4 MAIN plus C tuple
filter is preferred when both shared libraries are present; the Python
reference remains the correctness fallback.
"""

from __future__ import annotations

import math
import os
import re
import sys
import time
import csv
import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from hybrid_policy import check_target, MAX_FILTER
from hybrid_planner import HybridPlanError, plan_hybrid_boundaries
from hybrid_reference import HybridReferenceError, sieve_reference_segment, write_new_pgs2_floor_window
from prime_sieve_primesieve import generate_primes_in_range, write_scan_metrics_handoff
from prime_sieve_v1 import format_offset, read_prime_window
import window_sharding


WINDOW_M = 10_000_000
LOW_FLOOR_CUTOFF = 7
_WINDOW_FILE_RE = re.compile(r"^PRIME_WINDOW_10p(?P<floor>\d+)_off_(?P<offset>\d+)(?P<million>M)?\.bin$")
BENCHMARK_FIELDNAMES = [
    "run_timestamp_utc", "base_exponent", "target_idx_start", "target_idx_end",
    "windows_written", "total_seconds", "seconds_per_window", "total_primes",
    "avg_primes_per_window", "primes_per_second", "l_final", "sieving_primes_count",
    "max_child_rss_mb", "instance_of_n", "loop_session_seconds", "loop_numbers_per_second",
    "loop_seconds_per_window", "write_files", "base_gen_seconds", "sieve_seconds",
    "write_seconds", "bytes_written", "engine", "numbers_processed",
]


def write_hybrid_benchmark_row(portal_folder, base_exponent, target_idx_start, windows_written, total_seconds,
                               total_primes, write_files, bootstrap_seconds, sieve_seconds,
                               write_seconds, bytes_written, numbers_processed=None):
    """Append a schema-aligned Atlas 4.1 benchmark row for a hybrid run."""
    if windows_written == 0:
        return
    path = os.path.join(portal_folder, "benchmark_log.csv")
    rows = []
    if os.path.exists(path):
        with open(path, newline="") as stream:
            reader = csv.DictReader(stream)
            old_fields = reader.fieldnames or []
            rows = list(reader)
        if old_fields != BENCHMARK_FIELDNAMES:
            if not all(field in BENCHMARK_FIELDNAMES for field in old_fields):
                raise HybridSieveError("benchmark_log.csv has an incompatible schema")
            with open(path, "w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=BENCHMARK_FIELDNAMES)
                writer.writeheader()
                for old_row in rows:
                    writer.writerow({field: old_row.get(field, "") for field in BENCHMARK_FIELDNAMES})
    is_new = not os.path.exists(path)
    with open(path, "a", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=BENCHMARK_FIELDNAMES)
        if is_new:
            writer.writeheader()
        row = {
            "run_timestamp_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "base_exponent": base_exponent, "target_idx_start": target_idx_start,
            "target_idx_end": target_idx_start + windows_written - 1, "windows_written": windows_written,
            "total_seconds": f"{total_seconds:.3f}",
            "seconds_per_window": f"{total_seconds / windows_written:.4f}",
            "total_primes": total_primes,
            "avg_primes_per_window": f"{total_primes / windows_written:.1f}",
            "primes_per_second": f"{total_primes / total_seconds:.2f}" if total_seconds else "",
            "l_final": "", "sieving_primes_count": "", "max_child_rss_mb": "",
            "engine": "hybrid", "instance_of_n": "1/1",
            "numbers_processed": numbers_processed if numbers_processed is not None else "",
            "loop_session_seconds": f"{total_seconds:.6f}",
            "loop_numbers_per_second": f"{numbers_processed / total_seconds:.2f}" if total_seconds > 0 and numbers_processed is not None else "",
            "loop_seconds_per_window": f"{total_seconds / windows_written:.6f}", "write_files": "1" if write_files else "0",
            "base_gen_seconds": f"{bootstrap_seconds:.3f}",
            "sieve_seconds": f"{sieve_seconds:.9f}", "write_seconds": f"{write_seconds:.3f}",
            "bytes_written": bytes_written,
        }
        writer.writerow(row)
    print(f"[BENCHMARK] logged to {path} (schema-aligned hybrid row)")


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


def _continuation_target_idx(portal_folder: str | os.PathLike[str], floor: int,
                             window_m: int) -> int:
    """Return the index immediately after the selected floor's highest PGS2 window.

    This is deliberately an *output-position* query, not a mathematical MAIN
    input.  It gives repeated Hybrid launches the same continuation behaviour
    as the other Atlas generators without making the correctness proof depend
    on whether storage is empty, partial or gapped.
    """
    source = Path(portal_folder) / f"10p{floor}" / "source_primes"
    highest = -1
    for name, _path in window_sharding.list_sharded_files(str(source)):
        match = _WINDOW_FILE_RE.match(name)
        if not match or int(match.group("floor")) != floor:
            continue
        offset = int(match.group("offset"))
        if match.group("million"):
            offset *= 1_000_000
        if offset % window_m == 0:
            highest = max(highest, offset // window_m)
    return highest + 1


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


def first_prime_at_or_after(value: int) -> int:
    """Find one prime at/above ``value`` without materialising a prefix [2,value]."""
    lo = max(2, value)
    # The interval grows defensively rather than relying on an unproved prime-gap
    # estimate.  At Atlas scales this normally succeeds in the first tiny probe.
    width = max(128, int(math.log(lo + 1) * 32))
    while True:
        found = generate_primes_in_range(lo, lo + width)
        if found:
            return found[0]
        lo += width
        width *= 2


def last_prime_at_or_before(value: int) -> int:
    """Find the MAIN boundary locally, never by listing the full prefix."""
    hi = value + 1
    width = max(128, int(math.log(max(3, value)) * 32))
    while hi > 2:
        lo = max(2, hi - width)
        found = generate_primes_in_range(lo, hi)
        if found:
            return found[-1]
        hi = lo
        width *= 2
    raise HybridSieveError("could not establish a positive MAIN prime boundary")


def _stage_complete_window_hi(prefix: MainPrefix, limit: int, window_m: int) -> int:
    """Return the last *whole* Atlas window proven by this stage's mathematical limit."""
    floor_end = 10 ** (prefix.current_floor + 1)
    candidate_hi = min(limit + 1, floor_end)
    full = prefix.coverage_hi + ((candidate_hi - prefix.coverage_hi) // window_m) * window_m
    if full <= prefix.coverage_hi:
        raise HybridSieveError(
            "filter stage does not reach one complete Atlas window; increase k_adv or use a smaller MAIN boundary")
    return full


def _floor_for(value: int) -> int:
    return len(str(value)) - 1


def _iter_output_windows(start: int, stop: int, window_m: int):
    """Yield complete Atlas windows, routing each one to its actual digit floor."""
    lo = start
    while lo < stop:
        floor = _floor_for(lo)
        floor_lo, floor_hi = 10 ** floor, 10 ** (floor + 1)
        if floor < LOW_FLOOR_CUTOFF:
            if lo != floor_lo or floor_hi > stop:
                break
            yield floor, 0, floor_lo, floor_hi
            lo = floor_hi
            continue
        if (lo - floor_lo) % window_m:
            raise HybridSieveError("output range is not aligned to the floor window grid")
        hi = min(lo + window_m, floor_hi, stop)
        if hi - lo != window_m:
            break
        yield floor, (lo - floor_lo) // window_m, lo, hi
        lo = hi


def build_independent_plan(target_hi: int, filter_prime_count: int):
    """Build one fixed MAIN/filter base that proves the entire requested output."""
    if target_hi < 3:
        raise HybridSieveError("target_hi must exceed 2")
    # b is the first prime after a and d is after the filter.  Choosing a at
    # or above sqrt(target_hi-1) guarantees b*d > target_hi-1.  Crucially, C
    # MAIN can generate P_{<=a} itself: making a Python list of every such
    # prime was the dominant high-floor bootstrap cost and is mathematically
    # unnecessary.
    main_last_prime = first_prime_at_or_after(math.isqrt(target_hi - 1))
    bootstrap = bootstrap_following_primes(main_last_prime, filter_prime_count)
    plan = plan_hybrid_boundaries(main_last_prime, bootstrap[:-1], bootstrap[-1],
                                  base_is_contiguous=True, filter_is_consecutive=True)
    if plan.limit < target_hi - 1:
        raise HybridSieveError("boundary planner failed to cover its requested output")
    return plan


def build_narrow_plan(main_cap: int, filter_prime_count: int):
    """Build the explicit small MAIN/filter contract for one Hybrid window."""
    main_last_prime = last_prime_at_or_before(main_cap)
    bootstrap = bootstrap_following_primes(main_last_prime, filter_prime_count)
    return plan_hybrid_boundaries(main_last_prime, bootstrap[:-1], bootstrap[-1],
                                  base_is_contiguous=True, filter_is_consecutive=True)


def run_hybrid_narrow(start: int, end: int, main_cap: int, filter_prime_count: int,
                      write_files: bool, portal_folder: str | os.PathLike[str],
                      window_m: int = WINDOW_M) -> None:
    """Run one rounded PGS2 window under an explicit, intentionally small plan."""
    if start < 0 or end <= start:
        raise HybridSieveError("narrow hybrid accepts one non-empty standard output window only")
    floor = _floor_for(start)
    if floor < LOW_FLOOR_CUTOFF:
        rounded_start, rounded_end = 10 ** floor, 10 ** (floor + 1)
    else:
        rounded_start = (start // window_m) * window_m
        rounded_end = -(-end // window_m) * window_m
    if rounded_end - rounded_start > window_m:
        raise HybridSieveError("narrow hybrid accepts one non-empty standard output window only")
    check_target(rounded_end)
    if not 1 <= filter_prime_count <= MAX_FILTER:
        raise HybridSieveError("Filtr: dozwolone od 1 do 1 000 000 liczb pierwszych.")
    started = time.perf_counter()
    bootstrap_started = time.perf_counter()
    plan = build_narrow_plan(main_cap, filter_prime_count)
    bootstrap_seconds = time.perf_counter() - bootstrap_started
    if rounded_end - 1 > plan.limit:
        raise HybridSieveError(
            f"window ends at {rounded_end - 1:,}, beyond this filter proof limit {plan.limit:,}")
    print(f"[HYBRID] narrow: requested [{start:,}, {end:,}); output [{rounded_start:,}, {rounded_end:,}) "
          f"MAIN<= {plan.main_last_prime:,}; filter {plan.filter_start:,}..{plan.filter_end:,}", flush=True)
    from hybrid_native import native_library_available, sieve_native_segment_timed
    native = native_library_available()
    reference_main = None if native else tuple(generate_primes_in_range(2, plan.main_last_prime + 1))
    total_primes = total_windows = skipped_windows = 0
    total_main_seconds = total_filter_seconds = total_write_seconds = 0.0
    total_numbers = 0
    total_bytes_written = 0
    for floor, target_idx, lo, hi in _iter_output_windows(rounded_start, rounded_end, window_m):
        path = _window_path(Path(portal_folder), floor, target_idx, window_m)
        if path.is_file():
            skipped_windows += 1
            continue
        if native:
            result, main_seconds, filter_seconds = sieve_native_segment_timed(plan, lo, hi)
            total_main_seconds += main_seconds
            total_filter_seconds += filter_seconds
        else:
            sieve_started = time.perf_counter()
            result = sieve_reference_segment(plan, reference_main or (), lo, hi)
            total_main_seconds += time.perf_counter() - sieve_started
        if write_files:
            write_started = time.perf_counter()
            write_new_pgs2_floor_window(portal_folder, floor, target_idx, window_m, result.primes)
            total_write_seconds += time.perf_counter() - write_started
            total_bytes_written += path.stat().st_size
        total_primes += len(result.primes)
        total_windows += 1
        total_numbers += hi - lo
    elapsed = time.perf_counter() - started
    print(f"[HYBRID] timing: bootstrap {bootstrap_seconds:.3f}s; MAIN {total_main_seconds:.3f}s; "
          f"filter {total_filter_seconds:.3f}s; write {total_write_seconds:.3f}s; total {elapsed:.3f}s", flush=True)
    print(f"[HYBRID] done: {total_primes:,} primes, {total_windows} new window(s), "
          f"{skipped_windows} existing window(s)", flush=True)
    write_scan_metrics_handoff(str(portal_folder), total_primes_found=total_primes,
                               windows_processed=total_windows, write_files=write_files)
    target_floor = _floor_for(rounded_start)
    target_idx = 0 if target_floor < LOW_FLOOR_CUTOFF else (rounded_start - 10 ** target_floor) // window_m
    write_hybrid_benchmark_row(str(portal_folder), target_floor, target_idx, total_windows, elapsed,
                               total_primes, write_files, bootstrap_seconds,
                               total_main_seconds + total_filter_seconds,
                               total_write_seconds, total_bytes_written, total_numbers)


def run_hybrid_sieve(base_exponent: int, iterations: int, width_windows: int, filter_prime_count: int, write_files: bool,
                     portal_folder: str | os.PathLike[str], window_m: int = WINDOW_M) -> None:
    """Generate missing windows; PGS2 storage is output/cache, never mathematical input."""
    if base_exponent < 0 or iterations < 1 or width_windows < 1 or filter_prime_count < 1:
        raise HybridSieveError("floor, iterations, width and filter_prime_count must be positive")
    # Like the established generators, a repeated launch for a normal
    # windowed floor extends after that floor's highest existing output.  The
    # files only decide WHERE to resume; build_independent_plan() below still
    # constructs the complete mathematical MAIN/filter base from scratch.
    start_target_idx = 0
    if base_exponent >= LOW_FLOOR_CUTOFF:
        start_target_idx = _continuation_target_idx(portal_folder, base_exponent, window_m)
        capacity = _floor_window_count(base_exponent, window_m)
        if start_target_idx >= capacity:
            raise HybridSieveError(f"selected floor 10p{base_exponent} is complete; select 10p{base_exponent + 1}")
    start = 10 ** base_exponent + start_target_idx * window_m
    stage_width = width_windows * window_m
    target_hi = start + iterations * stage_width
    check_target(target_hi)
    bootstrap_started = time.perf_counter()
    plan = build_independent_plan(target_hi, filter_prime_count)
    bootstrap_seconds = time.perf_counter() - bootstrap_started
    started = time.perf_counter()
    total_primes = 0
    total_windows = 0
    total_main_seconds = 0.0
    total_filter_seconds = 0.0
    total_write_seconds = 0.0
    total_numbers = 0
    total_bytes_written = 0
    native_backend = False
    native_segment = None
    reference_main: tuple[int, ...] | None = None
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
    if not native_backend:
        reference_main = tuple(generate_primes_in_range(2, plan.main_last_prime + 1))
    for stage in range(1, iterations + 1):
        stage_started = time.perf_counter()
        stage_lo = start + (stage - 1) * stage_width
        stage_hi = stage_lo + stage_width
        output_windows = tuple(_iter_output_windows(stage_lo, stage_hi, window_m))
        if not output_windows:
            raise HybridSieveError("requested block contains no complete Atlas output window")
        emitted_lo, emitted_hi = output_windows[0][2], output_windows[-1][3]
        print(f"[HYBRID] stage {stage}/{iterations}: requested [{stage_lo:,}, {stage_hi:,}); "
              f"complete output [{emitted_lo:,}, {emitted_hi:,}) "
              f"MAIN<= {plan.main_last_prime:,}; filter {plan.filter_start:,}..{plan.filter_end:,}; "
              f"tuples<= {plan.required_tuple_order}", flush=True)
        stage_tuple_counts: dict[int, int] = {order: 0 for order in plan.tuple_orders}
        stage_main_seconds = 0.0
        stage_filter_seconds = 0.0
        stage_write_seconds = 0.0
        skipped_windows = 0
        for output_floor, target_idx, lo, hi in output_windows:
            if _window_path(Path(portal_folder), output_floor, target_idx, window_m).is_file():
                skipped_windows += 1
                continue
            if native_backend:
                result, main_seconds, filter_seconds = native_segment(plan, lo, hi)
                stage_main_seconds += main_seconds
                stage_filter_seconds += filter_seconds
            else:
                sieve_started = time.perf_counter()
                result = sieve_reference_segment(plan, reference_main or (), lo, hi)
                stage_main_seconds += time.perf_counter() - sieve_started
            if write_files:
                write_started = time.perf_counter()
                write_new_pgs2_floor_window(portal_folder, output_floor, target_idx,
                                            window_m, result.primes)
                stage_write_seconds += time.perf_counter() - write_started
                total_bytes_written += _window_path(Path(portal_folder), output_floor, target_idx, window_m).stat().st_size
            total_primes += len(result.primes)
            total_windows += 1
            total_numbers += hi - lo
            for order, count in result.tuple_product_counts:
                stage_tuple_counts[order] += count
        print("[HYBRID] stage tuples: " + ", ".join(
            f"{order}: {stage_tuple_counts[order]:,}" for order in sorted(stage_tuple_counts)), flush=True)
        print(f"[HYBRID] stage storage: skipped {skipped_windows} existing window(s)", flush=True)
        total_main_seconds += stage_main_seconds
        total_filter_seconds += stage_filter_seconds
        total_write_seconds += stage_write_seconds
        if native_backend:
            print(f"[HYBRID] stage timing: bootstrap {bootstrap_seconds:.3f}s; "
                  f"MAIN {stage_main_seconds:.3f}s; filter {stage_filter_seconds:.3f}s; "
                  f"write {stage_write_seconds:.3f}s; total {time.perf_counter() - stage_started:.3f}s",
                  flush=True)
        else:
            print(f"[HYBRID] stage timing: bootstrap {bootstrap_seconds:.3f}s; "
                  f"reference sieve+filter; write {stage_write_seconds:.3f}s; "
                  f"total {time.perf_counter() - stage_started:.3f}s", flush=True)
    elapsed = time.perf_counter() - started
    print(f"[HYBRID] done: {total_primes:,} primes, {total_windows} window(s), {elapsed:.3f}s", flush=True)
    write_scan_metrics_handoff(str(portal_folder), total_primes_found=total_primes,
                               windows_processed=total_windows, write_files=write_files)
    write_hybrid_benchmark_row(str(portal_folder), base_exponent, start_target_idx, total_windows, elapsed,
                               total_primes, write_files, bootstrap_seconds,
                               total_main_seconds + total_filter_seconds,
                               total_write_seconds, total_bytes_written, total_numbers)


def _main(argv: Iterable[str]) -> int:
    args = list(argv)
    if args and args[0] == "narrow":
        if len(args) != 6:
            print("Usage: hybrid_sieve.py narrow <start> <end> <main_cap> <filter_prime_count> <write_files 0|1>")
            return 2
        try:
            start, end, main_cap, count, write_raw = (int(value) for value in args[1:])
            if write_raw not in (0, 1):
                raise ValueError("write_files must be 0 or 1")
            portal = os.environ.get("CONSTELLATION_PORTAL_DIR", "/mnt/c/CONSTELLATION_PORTAL")
            run_hybrid_narrow(start, end, main_cap, count, bool(write_raw), portal)
            return 0
        except (ValueError, HybridPlanError, HybridReferenceError, HybridSieveError, RuntimeError, OSError) as exc:
            print(f"[HYBRID] ERROR: {exc}", file=sys.stderr)
            return 2
    if len(args) != 5:
        print("Usage: hybrid_sieve.py <floor> <iterations> <width_windows> <filter_prime_count> <write_files 0|1>")
        return 2
    try:
        floor, iterations, width_windows, count, write_raw = (int(value) for value in args)
        if write_raw not in (0, 1):
            raise ValueError("write_files must be 0 or 1")
        portal = os.environ.get("CONSTELLATION_PORTAL_DIR", "/mnt/c/CONSTELLATION_PORTAL")
        run_hybrid_sieve(floor, iterations, width_windows, count, bool(write_raw), portal)
        return 0
    except (ValueError, HybridPlanError, HybridReferenceError, HybridSieveError, RuntimeError, OSError) as exc:
        print(f"[HYBRID] ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
