"""store_verify.py -- the part shared by the store verifications (pt1_verify_store.py,
v73_verify_store.py): which P windows of a floor they take, how a proven range settles its
windows, and the benchmark_log.csv row of a run.

The windows: the floor's P windows on the window_m grid in offset order, within the
target_idx range start_idx..stop_idx when given (a pt1 run's own windows, run_verify.py), the
first max_windows of them (0 = all), split into runs of adjacent ones (a verifier proves a
contiguous range at a time) and, for a verifier with a width limit, into passes.

settle(): for each window of a proven range, the proven primes are compared with its P file.
Equal: its tag is listed in DP_PROVEN.txt, then its file moves to the D store (an entry
without a D file is ignored, so a kill between the two steps leaves the window P). Different:
it stays P and is listed in DP_MISMATCH.txt. Skipped: a window with a D file already (the
Storage tab's "Verify P against D" compares those) and a window whose primes reach past
window_m (written with another width).
"""
import datetime
import os

import numpy as np

import dp_verify
import native_tool_run
import prime_sieve_v1
import pt1_verify
import storage_kinds
from benchmark_log_schema import BENCHMARK_FIELDNAMES, RUN_PURPOSE_STORAGE
from floor_meta_store import append_benchmark_row_to_floor_meta


def windows(portal_folder, base_exponent, window_m, max_windows, start_idx=0, stop_idx=None):
    """[(offset, path)] of the floor's P windows on the window_m grid with a target_idx in
    start_idx..stop_idx (None: no upper end), ascending, the first max_windows of them (0:
    all)."""
    found = [(offset, path) for offset, path
             in storage_kinds.p_windows_on_grid(portal_folder, base_exponent, window_m)
             if offset // window_m >= start_idx
             and (stop_idx is None or offset // window_m <= stop_idx)]
    return found[:max_windows] if max_windows else found


def runs(window_list, window_m):
    """window_list split into runs of adjacent windows."""
    result = []
    for offset, path in window_list:
        if result and result[-1][-1][0] + window_m == offset:
            result[-1].append((offset, path))
        else:
            result.append([(offset, path)])
    return result


def passes(window_list, window_m, pass_numbers):
    """window_list's runs cut into passes of at most pass_numbers numbers: whole windows,
    at least one per pass."""
    size = max(1, pass_numbers // window_m)
    return [run[i:i + size] for run in runs(window_list, window_m)
            for i in range(0, len(run), size)]


def _file_offsets(path, lo):
    """The window file's primes as an ascending int64 array of p - lo."""
    return np.array([p - lo for p in prime_sieve_v1.read_prime_window(path)], dtype=np.int64)


def settle(portal_folder, base_exponent, window_m, items, proven_offsets):
    """Settles the windows `items` ([(offset, p_path)]) of one proven range: proven_offsets(lo,
    hi) gives the proven primes of [lo, hi) as ascending offsets from lo. Returns (proven,
    mismatches [(tag, first, proven count, file count)], skipped, primes proven)."""
    from prime_sieve_v5 import format_offset
    base = 10 ** base_exponent
    moves, tags, mismatches = [], set(), []
    skipped = primes = 0
    for offset, p_path in items:
        w_lo = base + offset
        d_path = storage_kinds.window_path(portal_folder, base_exponent, offset, window_m,
                                           format_offset(offset))
        file_offsets = _file_offsets(p_path, w_lo)
        if os.path.exists(d_path) or (file_offsets.size and file_offsets[-1] >= window_m):
            skipped += 1
            continue
        proven = proven_offsets(w_lo, w_lo + window_m)
        first = pt1_verify.first_difference(w_lo, file_offsets, proven)
        tag = storage_kinds.window_tag(os.path.basename(p_path))
        if first is None:
            tags.add(tag)
            moves.append((p_path, d_path))
        else:
            mismatches.append((tag, first, len(proven), len(file_offsets)))
        primes += len(proven)
    dp_verify.record(portal_folder, base_exponent, tags, mismatches)
    for p_path, d_path in moves:
        os.makedirs(os.path.dirname(d_path), exist_ok=True)
        os.replace(p_path, d_path)
    return len(moves), mismatches, skipped, primes


def log_run(portal_folder, base_exponent, engine, version, window_list, done, window_m, total,
            verify_seconds, primes, numbers, threads, stopped):
    """Appends the run's benchmark_log.csv row (a storage run) and its floor_meta copy."""
    row = {name: "" for name in BENCHMARK_FIELDNAMES}
    row.update({
        "run_timestamp_utc": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"),
        "base_exponent": base_exponent,
        "target_idx_start": window_list[0][0] // window_m,
        "target_idx_end": window_list[done - 1][0] // window_m,
        "windows_written": done,
        "total_seconds": f"{total:.3f}",
        "seconds_per_window": f"{total / done:.6f}",
        "total_primes": primes,
        "avg_primes_per_window": f"{primes / done:.1f}",
        "primes_per_second": f"{primes / total:.2f}" if total > 0 else "",
        "write_files": "1",
        "verify_seconds": f"{verify_seconds:.3f}",
        "engine": engine,
        "engine_version": version,
        "threads": str(threads),
        "numbers_processed": numbers,
        "run_status": "stopped" if stopped else "completed",
        "run_purpose": RUN_PURPOSE_STORAGE,
    })
    native_tool_run.append_row(portal_folder, row)
    append_benchmark_row_to_floor_meta(portal_folder, base_exponent, row)
