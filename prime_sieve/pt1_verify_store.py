"""pt1_verify_store.py -- proves the P windows of one floor's store: P becomes D (pt1_verify.py).

    python pt1_verify_store.py <base_exponent> <threads> <window_m> [<max_windows>]

Takes the floor's P windows in offset order (the first max_windows of them; 0 or absent =
all), groups adjacent ones into slabs like the pt1 scan (pt1_plan.plan_slabs()) and proves
each slab: sieved again to the bound s, every survivor decided by the pseudosquares proof.
A window whose proven primes equal its file's becomes D/P: its tag is listed in
DP_PROVEN.txt, then its file moves to the D store (an entry without a D file is ignored, so
a kill between the two steps leaves the window P). A different one stays P and is listed in
DP_MISMATCH.txt. Skipped: a window with a D file already (the Storage tab's "Verify P
against D" compares those) and a window whose primes reach past window_m (written with
another width).

Each slab's outcomes are recorded before the next starts, so a stop (the GUI's stop request,
checked between slabs, or a kill) keeps every finished slab. The run logs one
benchmark_log.csv row: engine pt1_verify, the proof time in verify_seconds and the whole
run in total_seconds; it is a storage run, never on the Benchmark charts.

Environment: CONSTELLATION_PORTAL_DIR (storage folder), PRIMEATLAS_PT1_B (the scan's bound,
the default floor(N^(1/4)) when unset), PRIMEATLAS_PT1_CHUNK_KB.
"""
import datetime
import os
import sys
import time

import numpy as np

import dp_verify
import generation_stop
import native_tool_run
import prime_sieve_v1
import pt1_lib
import pt1_plan
import pt1_verify
import storage_kinds
from benchmark_log_schema import BENCHMARK_FIELDNAMES, RUN_PURPOSE_STORAGE
from floor_meta_store import append_benchmark_row_to_floor_meta

VERSION = "pt1.1"
PROGRESS_SECONDS = 10


def _windows(portal_folder, base_exponent, window_m, max_windows):
    """[(offset, path)] of the floor's P windows on the window_m grid, ascending, the first
    max_windows of them (0: all)."""
    found = storage_kinds.p_windows_on_grid(portal_folder, base_exponent, window_m)
    return found[:max_windows] if max_windows else found


def _runs(windows, window_m):
    """windows split into runs of adjacent ones."""
    runs = []
    for offset, path in windows:
        if runs and runs[-1][-1][0] + window_m == offset:
            runs[-1].append((offset, path))
        else:
            runs.append([(offset, path)])
    return runs


def _file_offsets(path, lo):
    """The window file's primes as an ascending int64 array of p - lo."""
    return np.array([p - lo for p in prime_sieve_v1.read_prime_window(path)], dtype=np.int64)


def verify_floor(portal_folder, base_exponent, threads, window_m, max_windows=0,
                 requested_b=0, chunk_kb=pt1_plan.DEFAULT_CHUNK_KB):
    """Proves the floor's P windows (module docstring). Returns 0, 2 when the floor is past
    the verification's limit (pt1_verify.LIMIT_TEXT) or has no P window, 3 when stopped on
    request."""
    from prime_sieve_v5 import _window_prime_offsets, format_offset
    base = 10 ** base_exponent
    windows = _windows(portal_folder, base_exponent, window_m, max_windows)
    print("=" * 70)
    print(f"[*] VERIFY P -> D {VERSION}: floor 10^{base_exponent}, {len(windows)} P windows of "
          f"{window_m:,} numbers, {threads} threads")
    if not windows:
        print("[-] No P window on this floor to verify.")
        return 2
    first_lo = base + windows[0][0]
    last_hi = base + windows[-1][0] + window_m
    b = pt1_plan.effective_b(requested_b, first_lo, last_hi)
    s = pt1_verify.bound(b, first_lo, last_hi)
    if s is None:
        print(f"[-] ERROR: the verification proves numbers below {pt1_verify.LIMIT_TEXT}, the "
              f"windows end at {last_hi:,}.")
        return 2
    print(f"[*] Pseudosquares proof, sieve bound s = {s:,}")
    print("=" * 70)
    lib = pt1_lib.load()
    ctx = lib.pt1_ctx_new(s)
    if not ctx:
        print("[-] ERROR: could not allocate the sieving primes.")
        return 1
    chunk_odd = pt1_plan.chunk_odd(chunk_kb)
    slab_size = pt1_plan.slab_numbers(threads, chunk_kb)
    t_start = last = time.perf_counter()
    proof_seconds = 0.0
    done = proven = primes = numbers = 0
    mismatched, skipped = [], 0
    stopped = False
    try:
        for run in _runs(windows, window_m):
            spans = [(base + off, base + off + window_m) for off, _p in run]
            for _kind, ix in pt1_plan.plan_slabs(spans, [storage_kinds.KIND_P] * len(spans),
                                                 slab_size):
                if generation_stop.stop_requested(portal_folder):
                    stopped = True
                    break
                lo, hi = spans[ix[0]][0], spans[ix[-1]][1]
                t_proof = time.perf_counter()
                first_odd, bits = pt1_verify.verify_slab(ctx, lo, hi, threads, chunk_odd,
                                                         lambda _done: None)
                proof_seconds += time.perf_counter() - t_proof
                moves, tags, mismatches = [], set(), []
                for i in ix:
                    w_lo, w_hi = spans[i]
                    offset, p_path = run[i]
                    d_path = storage_kinds.window_path(portal_folder, base_exponent, offset,
                                                       window_m, format_offset(offset))
                    file_offsets = _file_offsets(p_path, w_lo)
                    if os.path.exists(d_path) or (file_offsets.size
                                                  and file_offsets[-1] >= window_m):
                        skipped += 1
                        continue
                    proven_offsets = _window_prime_offsets(bits, first_odd, w_lo, w_hi)
                    first = pt1_verify.first_difference(w_lo, file_offsets, proven_offsets)
                    tag = storage_kinds.window_tag(os.path.basename(p_path))
                    if first is None:
                        tags.add(tag)
                        moves.append((p_path, d_path))
                    else:
                        mismatches.append((tag, first, len(proven_offsets), len(file_offsets)))
                    primes += len(proven_offsets)
                dp_verify.record(portal_folder, base_exponent, tags, mismatches)
                for p_path, d_path in moves:
                    os.makedirs(os.path.dirname(d_path), exist_ok=True)
                    os.replace(p_path, d_path)
                proven += len(moves)
                mismatched += mismatches
                done += len(ix)
                numbers += hi - lo
                now = time.perf_counter()
                if now - last >= PROGRESS_SECONDS or done == len(windows):
                    last = now
                    rate = done / (now - t_start)
                    print(f"[+] Progress: {done / len(windows) * 100:.2f}% ({done}/{len(windows)} "
                          f"windows) | time: {now - t_start:.2f}s | ETA "
                          f"~{(len(windows) - done) / rate:.0f}s", flush=True)
            if stopped:
                break
    finally:
        lib.pt1_ctx_free(ctx)
    total = time.perf_counter() - t_start
    speed = numbers / proof_seconds if proof_seconds > 0 else float("nan")
    print("\n" + "=" * 70)
    if stopped:
        print("[!] STOPPED ON REQUEST: the finished slabs are kept.")
    print(f"[*] Verified {done} of {len(windows)} P windows: {proven} proven (now D/P), "
          f"{len(mismatched)} mismatches, {skipped} skipped")
    print(f"[*] Proof {proof_seconds:.2f}s ({speed:,.0f} n/s), run {total:.2f}s, "
          f"{primes:,} primes proven")
    print("=" * 70)
    if done:
        _log(portal_folder, base_exponent, windows, done, window_m, total, proof_seconds,
             primes, numbers, threads, stopped)
    return 3 if stopped else 0


def _log(portal_folder, base_exponent, windows, done, window_m, total, proof_seconds, primes,
         numbers, threads, stopped):
    row = {name: "" for name in BENCHMARK_FIELDNAMES}
    row.update({
        "run_timestamp_utc": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"),
        "base_exponent": base_exponent,
        "target_idx_start": windows[0][0] // window_m,
        "target_idx_end": windows[done - 1][0] // window_m,
        "windows_written": done,
        "total_seconds": f"{total:.3f}",
        "seconds_per_window": f"{total / done:.6f}",
        "total_primes": primes,
        "avg_primes_per_window": f"{primes / done:.1f}",
        "primes_per_second": f"{primes / total:.2f}" if total > 0 else "",
        "write_files": "1",
        "verify_seconds": f"{proof_seconds:.3f}",
        "engine": pt1_verify.ENGINE_VERIFY,
        "engine_version": VERSION,
        "threads": str(threads),
        "numbers_processed": numbers,
        "run_status": "stopped" if stopped else "completed",
        "run_purpose": RUN_PURPOSE_STORAGE,
    })
    native_tool_run.append_row(portal_folder, row)
    append_benchmark_row_to_floor_meta(portal_folder, base_exponent, row)


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    portal = os.environ.get("CONSTELLATION_PORTAL_DIR") or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "CONSTELLATION_PORTAL"))
    try:
        requested_b = pt1_plan.b_from_env(os.environ)
        chunk_kb = pt1_plan.chunk_kb_from_env(os.environ)
    except ValueError as e:
        print(f"[-] ERROR: {e}")
        sys.exit(2)
    print("Start time:", datetime.datetime.now().strftime("%H:%M:%S"))
    sys.exit(verify_floor(portal, int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]),
                          int(sys.argv[4]) if len(sys.argv) > 4 else 0, requested_b, chunk_kb))
