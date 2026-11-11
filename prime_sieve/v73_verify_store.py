"""v73_verify_store.py -- proves the P windows of one floor's store with engine v7.2's sieve:
P becomes D (the pt1.1 proof's counterpart, pt1_verify_store.py).

    python v73_verify_store.py <base_exponent> <threads> <window_m> [<max_windows>]
                               [<pass_numbers>] [--range <start_idx> <stop_idx>]

Takes the floor's P windows in offset order (only target_idx start_idx..stop_idx with
--range, as after a pt1 run, run_verify.py; the first max_windows of them; 0 or absent =
all), splits the runs of adjacent ones into passes of at most pass_numbers numbers (whole
windows, at least one; default DEFAULT_PASS_NUMBERS) and sieves each pass completely, in
memory, with v7.2's segmented and bucketed marking (prime_sieve_v7_2._run_sieve()). The
sieve is deterministic, so its primes are proven; the windows settle as
store_verify.settle() says: equal ones become D/P, different ones stay P and are listed in
DP_MISMATCH.txt, a window with a D file or of another width is skipped.

A v7.2 sieve costs a near fixed time per pass (the jump gear walks every sieving prime's
range once, whatever the width) plus a small part per number, so one wide pass is much
cheaper than several narrow ones; the pass width is bounded by RAM: the wheel-30 buffer
takes pass_numbers / 30 bytes (about 3.3 GB for 10^11), next to v7.2's buckets.

Each pass's outcomes are recorded before the next starts, so a stop (the GUI's stop request,
checked between passes, or a kill) keeps every finished pass. The run logs one
benchmark_log.csv row: engine v73_verify, the sieve time in verify_seconds and the whole run
in total_seconds; it is a storage run, never on the Benchmark charts.

Environment: CONSTELLATION_PORTAL_DIR (storage folder) and v7.2's PRIMEATLAS_V7_* knobs
(work_plan_v7_2.py).
"""
import datetime
import math
import os
import sys
import time

import numpy as np

import generation_stop
import prime_sieve_v7_2 as v72
import run_verify
import store_verify
import wheel30_layout
import work_plan_v7_2
from benchmark_log_schema import ENGINE_V73_VERIFY

VERSION = "v7.3"
DEFAULT_PASS_NUMBERS = run_verify.DEFAULT_PASS_NUMBERS
# primesieve generates sieving primes below 2^64, so a pass ends below (2^64)^2.
SIEVE_LIMIT = 2 ** 128


def knobs_from_env(environ):
    """v7.2's sieve knobs, as prime_sieve_v7_2.py reads them."""
    return {"segment_kb": work_plan_v7_2.segment_kb_from_env(environ),
            "region_kb": work_plan_v7_2.region_kb_from_env(environ),
            "bucket_mb": work_plan_v7_2.bucket_mb_from_env(environ),
            "pieces_per_thread": work_plan_v7_2.pieces_per_thread_from_env(environ),
            "jump_model_pct": work_plan_v7_2.jump_model_pct_from_env(environ),
            "jump_block_cost": work_plan_v7_2.jump_block_cost_from_env(environ),
            "jump_landing_cost_pct": work_plan_v7_2.jump_landing_cost_pct_from_env(environ),
            "block_model_pct": work_plan_v7_2.block_model_pct_from_env(environ)}


def _sieve_and_settle(portal_folder, base_exponent, window_m, items, lo, hi, threads, knobs):
    """Sieves [lo, hi) into a fresh shared buffer and settles its windows. Returns
    (sieve seconds, settle result) or None on an engine error (nothing settled)."""
    v72.MAX_WORKERS = threads
    base = wheel30_layout.buffer_base(lo)
    n_bytes = wheel30_layout.buffer_bytes(lo, hi)
    v72._init_shared_buffer(n_bytes)
    v72._load_lib()   # loaded before the fork, inherited by every worker
    t_sieve = time.perf_counter()
    errors = v72._run_sieve(base, n_bytes * 8, math.isqrt(hi) + 1, hi - lo, **knobs)
    sieve_seconds = time.perf_counter() - t_sieve
    result = None
    if not errors:
        buf = np.frombuffer(v72._shm_mmap, dtype=np.uint8, count=n_bytes)
        result = store_verify.settle(
            portal_folder, base_exponent, window_m, items,
            lambda w_lo, w_hi: wheel30_layout.window_prime_offsets(buf, base, w_lo, w_hi))
        del buf   # the mapping cannot close while a NumPy view still exports it
    v72._shm_mmap.close()
    return None if errors else (sieve_seconds, result)


def verify_floor(portal_folder, base_exponent, threads, window_m, max_windows=0,
                 pass_numbers=DEFAULT_PASS_NUMBERS, knobs=None, start_idx=0, stop_idx=None):
    """Proves the floor's P windows (module docstring). Returns 0, 1 on an engine error, 2
    when the floor has no P window or ends past SIEVE_LIMIT, 3 when stopped on request."""
    knobs = knobs if knobs is not None else knobs_from_env({})
    base = 10 ** base_exponent
    windows = store_verify.windows(portal_folder, base_exponent, window_m, max_windows,
                                   start_idx, stop_idx)
    passes = store_verify.passes(windows, window_m, pass_numbers)
    print("=" * 70)
    print(f"[*] VERIFY P -> D {VERSION} (v7.2 sieve): floor 10^{base_exponent}, "
          f"{len(windows)} P windows of {window_m:,} numbers, {len(passes)} passes of up to "
          f"{max(pass_numbers, window_m):,} numbers, {threads} threads")
    if not windows:
        print("[-] No P window on this floor to verify.")
        return 2
    if base + windows[-1][0] + window_m > SIEVE_LIMIT:
        print("[-] ERROR: the sieve's primes end below 2^64, so it proves numbers below 2^128.")
        return 2
    print("=" * 70)
    t_start = time.perf_counter()
    sieve_seconds = 0.0
    done = proven = primes = numbers = skipped = 0
    mismatched = []
    stopped = failed = False
    for number, items in enumerate(passes, 1):
        if generation_stop.stop_requested(portal_folder):
            stopped = True
            break
        lo, hi = base + items[0][0], base + items[-1][0] + window_m
        print(f"\n[*] Pass {number}/{len(passes)}: [{lo:,}, {hi:,}), {len(items)} windows",
              flush=True)
        outcome = _sieve_and_settle(portal_folder, base_exponent, window_m, items, lo, hi,
                                    threads, knobs)
        if outcome is None:
            print("[-] ERROR: the sieve reported an engine error; this pass settles nothing.")
            failed = True
            break
        seconds, (n_proven, mismatches, n_skipped, n_primes) = outcome
        sieve_seconds += seconds
        proven += n_proven
        mismatched += mismatches
        skipped += n_skipped
        primes += n_primes
        done += len(items)
        numbers += hi - lo
        now = time.perf_counter() - t_start
        rate = done / now
        print(f"[+] Progress: {done / len(windows) * 100:.2f}% ({done}/{len(windows)} windows, "
              f"pass {number}/{len(passes)}) | time: {now:.2f}s | ETA "
              f"~{(len(windows) - done) / rate:.0f}s", flush=True)
    total = time.perf_counter() - t_start
    speed = numbers / sieve_seconds if sieve_seconds > 0 else float("nan")
    print("\n" + "=" * 70)
    if stopped:
        print("[!] STOPPED ON REQUEST: the finished passes are kept.")
    print(f"[*] Verified {done} of {len(windows)} P windows: {proven} proven (now D/P), "
          f"{len(mismatched)} mismatches, {skipped} skipped")
    print(f"[*] Sieve {sieve_seconds:.2f}s ({speed:,.0f} n/s), run {total:.2f}s, "
          f"{primes:,} primes proven")
    print("=" * 70)
    if done:
        store_verify.log_run(portal_folder, base_exponent, ENGINE_V73_VERIFY, VERSION, windows,
                             done, window_m, total, sieve_seconds, primes, numbers, threads,
                             stopped)
    return 1 if failed else 3 if stopped else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)
    portal = os.environ.get("CONSTELLATION_PORTAL_DIR") or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "CONSTELLATION_PORTAL"))
    try:
        env_knobs = knobs_from_env(os.environ)
    except ValueError as e:
        print(f"[-] ERROR: {e}")
        sys.exit(2)
    args, start_idx, stop_idx = run_verify.pop_range(sys.argv)
    print("Start time:", datetime.datetime.now().strftime("%H:%M:%S"))
    sys.exit(verify_floor(portal, int(args[1]), int(args[2]), int(args[3]),
                          int(args[4]) if len(args) > 4 else 0,
                          int(args[5]) if len(args) > 5 else DEFAULT_PASS_NUMBERS,
                          env_knobs, start_idx, stop_idx))
