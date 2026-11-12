"""prime_sieve_pt1.py -- batch scanner for engine pt1 (partial sieve + primality test),
driven by orchestrator_v3.py when SCANNER_VERSION = "pt1". Same CLI and metrics handoff as
prime_sieve_v5.py.

Each window is sieved only by the primes 3..B and its survivors are tested in
prime_sieve_engine_pt1.c (see pt1_plan.py for B, the chunk knob and the slab grouping). A
window wholly below storage_kinds.MR_DET_BOUND is tested with 13 Miller-Rabin bases and
written to the D store (byte-identical to v5's output; unitTests/test_engine_pt1.py checks
that); any other window is tested with BPSW and written to the P store
(10p{N}/source_primes_P/, filenames ending in _P.bin).

The verification P -> D is no part of the scan: orchestrator_v3.py runs it after the whole
run (run_verify.py), so it can prove the run's P windows in one wide v7.3 pass.

Engine pt1-pss (PRIMEATLAS_SCANNER_VERSION=pt1-pss) proves in the same pass instead: a window
at or above MR_DET_BOUND is decided by the pseudosquares proof (pt1_verify_odd(), the
verification's own call) and every window goes to the D store. The proof needs a larger B on
floors 33 and 34 (pt1_verify.bound(): B is raised to the smallest value it accepts) and cannot
reach past about 1.8e34, so floors 35..37 are refused.

Memory is two slab bitmaps (slab k+1 is sieved while slab k is written, overlap_pipeline.py)
plus one flag chunk per thread, independent of the run length.
Floors 0..6 (the scanners' low-floor path) and floors above 37 (n >= 2^127) are refused.
"""
import datetime
import math
import os
import sys
import time

import pt1_lib
import pt1_plan
import pt1_verify
import storage_kinds
from overlap_pipeline import run_overlapped
from prime_sieve_v5 import (SCAN_METRICS_FILENAME, _window_prime_count,  # noqa: F401
                            _window_prime_offsets, format_offset, read_prime_window_header,
                            write_scan_metrics_handoff)

VERSION = "pt1.1"
MAX_WORKERS = 24



def main_batch_scanner(base_power, target_idx_list, window_m, write_files=True,
                        compute_sieving_primes_count=False, requested_b=0,
                        chunk_kb=pt1_plan.DEFAULT_CHUNK_KB, prove=False):
    """Returns 0, or 2 when the floor or B is outside pt1's range. prove: engine pt1-pss
    (every window proven and written to D)."""
    if not pt1_plan.MIN_FLOOR <= base_power <= pt1_plan.MAX_FLOOR:
        print(f"[-] ERROR: pt1 covers floors {pt1_plan.MIN_FLOOR}..{pt1_plan.MAX_FLOOR}, "
              f"got {base_power}; use v5 for this floor.")
        return 2
    target_idx_list = sorted(target_idx_list)
    BASE = 10 ** base_power
    windows = [(BASE + idx * window_m, BASE + (idx + 1) * window_m) for idx in target_idx_list]
    for i in range(1, len(windows)):
        assert windows[i][0] == windows[i - 1][1], (
            f"Batch mode requires ADJACENT windows (consecutive target_idx) -- gap before "
            f"target_idx={target_idx_list[i]}")
    combined_lo, combined_hi = windows[0][0], windows[-1][1]
    if combined_hi > 2 ** 127:
        print(f"[-] ERROR: pt1 needs every number below 2^127, the range ends at {combined_hi:,}.")
        return 2
    b = pt1_plan.effective_b(requested_b, combined_lo, combined_hi)
    b_note = " (default floor(N^(1/4)))" if not requested_b else f" (requested {requested_b:,})"
    if prove:
        proof_b = pt1_verify.bound(b, combined_lo, combined_hi)
        if proof_b is None:
            print(f"[-] ERROR: pt1-pss proves numbers below {pt1_verify.LIMIT_TEXT}, the range ends "
                  f"at {combined_hi:,}; use pt1 for this floor.")
            return 2
        if proof_b > b:
            b_note += f", raised to {proof_b:,} for the proof"
            b = proof_b
    # The test of each window (D: 13 Miller-Rabin bases; P: BPSW, or the proof for pt1-pss)
    # and the store it is written to (pt1-pss: always D).
    kinds = [storage_kinds.written_kind(storage_kinds.ENGINE_PT1, lo, hi) for lo, hi in windows]
    store_kind = storage_kinds.KIND_D if prove else None
    chunk_odd = pt1_plan.chunk_odd(chunk_kb)
    slabs = pt1_plan.plan_slabs(windows, kinds, pt1_plan.slab_numbers(MAX_WORKERS, chunk_kb))
    n_chunks_total = sum(
        math.ceil(((windows[ix[-1]][1] - (windows[ix[0]][0] | 1) + 1) // 2) / chunk_odd)
        for _kind, ix in slabs)

    print("\n" + "=" * 70)
    print(f"[*] BATCH {VERSION} (partial sieve to B + primality test, PGS2 binary output): "
          f"{len(windows)} windows (target_idx {target_idx_list[0]}..{target_idx_list[-1]}), "
          f"level 10^{base_power}")
    print(f"[*] Combined range: [{combined_lo:,}, {combined_hi:,})  "
          f"size={combined_hi - combined_lo:,}")
    print(f"[*] Sieve limit B = {b:,}{b_note}")
    n_d = kinds.count(storage_kinds.KIND_D)
    upper = "D (pseudosquares proof)" if prove else "P (BPSW, probable)"
    print(f"[*] Windows: {n_d} D (13 Miller-Rabin bases, proven), {len(windows) - n_d} {upper} "
          f"| {len(slabs)} slabs, {chunk_kb} KiB chunks, {MAX_WORKERS} threads")
    if not write_files:
        print("[*] WRITE_FILES=False -- no PGS2 files will be written this run; only "
              "aggregate prime counts will be reported.")
    print("=" * 70)

    t_base = time.perf_counter()
    lib = pt1_lib.load()
    ctx = lib.pt1_ctx_new(b)
    if not ctx:
        print("[-] ERROR: could not allocate the sieving primes.")
        return 1
    sieving_primes_count = lib.pt1_ctx_count(ctx)
    base_gen_seconds = time.perf_counter() - t_base
    print(f"[*] Sieving primes 3..B: {sieving_primes_count:,} ({base_gen_seconds:.3f}s)")

    if write_files:
        from pgs2_vector import write_prime_window_offsets
    t_start = time.perf_counter()
    bytes_written = total_primes_found = 0
    chunks_before = 0
    last_print = [t_start, -1]

    def _progress(done_in_slab):
        done = chunks_before + done_in_slab
        now = time.perf_counter()
        if done == last_print[1] or (now - last_print[0] < 10 and done < n_chunks_total):
            return
        rate = done / (now - t_start) if now > t_start else 0
        eta = (n_chunks_total - done) / rate if rate > 0 else float("inf")
        print(f"[+] Progress: {done / n_chunks_total * 100:.2f}% ({done}/{n_chunks_total} "
              f"chunks) | time: {now - t_start:.2f}s | ETA ~{eta:.0f}s")
        last_print[0], last_print[1] = now, done

    def _sieve(slab):
        nonlocal chunks_before
        kind, ix = slab
        slab_lo, slab_hi = windows[ix[0]][0], windows[ix[-1]][1]
        det = 1 if kind == storage_kinds.KIND_D else 0
        if prove and not det:
            def call(first_hi, first_lo, n_odd, bits, done):
                return lib.pt1_verify_odd(ctx, first_hi, first_lo, n_odd, MAX_WORKERS, chunk_odd,
                                          bits, done)
        else:
            def call(first_hi, first_lo, n_odd, bits, done):
                return lib.pt1_sieve_odd(ctx, first_hi, first_lo, n_odd, det, MAX_WORKERS,
                                         chunk_odd, bits, done)
        sieved = pt1_lib.run_slab(call, slab_lo, slab_hi, _progress)
        chunks_before += math.ceil(((slab_hi - sieved[0] + 1) // 2) / chunk_odd)
        return sieved

    def _write(slab, sieved):
        nonlocal total_primes_found, bytes_written
        kind, ix = slab
        first_odd, bits = sieved
        for i in ix:
            lo, hi = windows[i]
            offset = lo - BASE
            if write_files:
                path = storage_kinds.window_path(BASE_STORAGE_10PN, base_power, offset, window_m,
                                                 format_offset(offset), store_kind or kind)
                offsets = _window_prime_offsets(bits, first_odd, lo, hi)
                total_primes_found += len(offsets)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                write_prime_window_offsets(path, lo, offsets, generated_at=int(time.time()))
                bytes_written += os.path.getsize(path)
            else:
                total_primes_found += _window_prime_count(bits, first_odd, lo, hi)

    # Slab k+1 is sieved while slab k is unpacked and written (overlap_pipeline.py).
    try:
        timings = run_overlapped(slabs, _sieve, _write)
    finally:
        lib.pt1_ctx_free(ctx)
    t_sieve, t_write = timings.produce_seconds, timings.consume_seconds
    _progress(0)

    print(f"\n[*] Sieve + test {t_sieve:.2f}s, unpack + write {t_write:.2f}s (overlapped with "
          f"the sieve; {timings.wait_seconds:.2f}s not hidden)")
    print(f"[*] TOTAL PRIMES FOUND this run: {total_primes_found:,} across {len(windows)} windows"
          + ("" if write_files else "  (NO FILES WRITTEN -- count-only mode)"))
    write_scan_metrics_handoff(BASE_STORAGE_10PN, b,
                                sieving_primes_count if compute_sieving_primes_count else None,
                                total_primes_found=total_primes_found,
                                windows_processed=len(windows), write_files=write_files,
                                base_gen_seconds=base_gen_seconds, sieve_seconds=t_sieve,
                                write_seconds=t_write, bytes_written=bytes_written,
                                numbers_processed=combined_hi - combined_lo)
    print("=" * 70)
    return 0


if __name__ == "__main__":
    # The GUI redirects stdout to a log file: line buffering lets each progress line reach
    # it (and the progress bar) when printed, not when an 8 KiB block fills.
    sys.stdout.reconfigure(line_buffering=True)
    print("=" * 70)
    print(f"[*] PRIME SIEVE -- {VERSION} (partial sieve + Miller-Rabin / BPSW, PGS2 binary "
          f"output)")
    print("=" * 70)
    # CONSTELLATION_PORTAL_DIR and the positional CLI: as in prime_sieve_v5.py. Position 5
    # (batches per worker) is accepted and unused: pt1 has no worker batches.
    env_override = os.environ.get("CONSTELLATION_PORTAL_DIR")
    BASE_STORAGE_10PN = env_override or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "CONSTELLATION_PORTAL"))
    print(f"[*] Windows written to: {BASE_STORAGE_10PN}\\10p{{N}}\\source_primes(_P)\\")

    base_exponent = int(sys.argv[1])
    target_idx_list = list(range(int(sys.argv[2]), int(sys.argv[3]) + 1))
    if len(sys.argv) > 4:
        MAX_WORKERS = int(sys.argv[4])
    WRITE_FILES = bool(int(sys.argv[6])) if len(sys.argv) > 6 else True
    COMPUTE_SIEVING_PRIMES_COUNT = bool(int(sys.argv[7])) if len(sys.argv) > 7 else False
    WINDOW_M = int(sys.argv[8]) if len(sys.argv) > 8 else 10 ** 7
    try:
        REQUESTED_B = pt1_plan.b_from_env(os.environ)
        CHUNK_KB = pt1_plan.chunk_kb_from_env(os.environ)
    except ValueError as e:
        print(f"[-] ERROR: {e}")
        sys.exit(2)

    print("Start time:", datetime.datetime.now().strftime("%H:%M:%S"))
    sys.exit(main_batch_scanner(base_exponent, target_idx_list, WINDOW_M, write_files=WRITE_FILES,
                                compute_sieving_primes_count=COMPUTE_SIEVING_PRIMES_COUNT,
                                requested_b=REQUESTED_B, chunk_kb=CHUNK_KB,
                                prove=os.environ.get("PRIMEATLAS_SCANNER_VERSION")
                                == storage_kinds.ENGINE_PT1_PSS))
