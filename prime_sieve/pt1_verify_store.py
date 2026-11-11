"""pt1_verify_store.py -- proves the P windows of one floor's store: P becomes D (pt1_verify.py).

    python pt1_verify_store.py <base_exponent> <threads> <window_m> [<max_windows>]
                               [--range <start_idx> <stop_idx>]

Takes the floor's P windows in offset order (only target_idx start_idx..stop_idx with
--range, as after a pt1 run, run_verify.py; the first max_windows of them; 0 or absent =
all), groups adjacent ones into slabs like the pt1 scan (pt1_plan.plan_slabs()) and proves
each slab: sieved again to the bound s, every survivor decided by the pseudosquares proof.
The proven windows settle as store_verify.settle() says: equal ones become D/P, different
ones stay P and are listed in DP_MISMATCH.txt, a window with a D file or of another width is
skipped.

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

import generation_stop
import pt1_lib
import pt1_plan
import pt1_verify
import run_verify
import storage_kinds
import store_verify

VERSION = "pt1.1"
PROGRESS_SECONDS = 10


def verify_floor(portal_folder, base_exponent, threads, window_m, max_windows=0,
                 requested_b=0, chunk_kb=pt1_plan.DEFAULT_CHUNK_KB, start_idx=0, stop_idx=None):
    """Proves the floor's P windows (module docstring). Returns 0, 2 when the floor is past
    the verification's limit (pt1_verify.LIMIT_TEXT) or has no P window, 3 when stopped on
    request."""
    from prime_sieve_v5 import _window_prime_offsets
    base = 10 ** base_exponent
    windows = store_verify.windows(portal_folder, base_exponent, window_m, max_windows,
                                   start_idx, stop_idx)
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
        for run in store_verify.runs(windows, window_m):
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
                n_proven, mismatches, n_skipped, n_primes = store_verify.settle(
                    portal_folder, base_exponent, window_m, [run[i] for i in ix],
                    lambda w_lo, w_hi: _window_prime_offsets(bits, first_odd, w_lo, w_hi))
                skipped += n_skipped
                primes += n_primes
                proven += n_proven
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
        store_verify.log_run(portal_folder, base_exponent, pt1_verify.ENGINE_VERIFY, VERSION,
                             windows, done, window_m, total, proof_seconds, primes, numbers,
                             threads, stopped)
    return 3 if stopped else 0


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
    args, start_idx, stop_idx = run_verify.pop_range(sys.argv)
    print("Start time:", datetime.datetime.now().strftime("%H:%M:%S"))
    sys.exit(verify_floor(portal, int(args[1]), int(args[2]), int(args[3]),
                          int(args[4]) if len(args) > 4 else 0, requested_b, chunk_kb,
                          start_idx, stop_idx))
