"""prime_sieve_pt1.py -- batch scanner for engine pt1 (partial sieve + primality test),
driven by orchestrator_v3.py when SCANNER_VERSION = "pt1". Same CLI and metrics handoff as
prime_sieve_v5.py.

Each window is sieved only by the primes 3..B and its survivors are tested in
prime_sieve_engine_pt1.c (see pt1_plan.py for B, the chunk knob and the slab grouping). A
window wholly below storage_kinds.MR_DET_BOUND is tested with 13 Miller-Rabin bases and
written to the D store (byte-identical to v5's output; unitTests/test_engine_pt1.py checks
that); any other window is tested with BPSW and written to the P store
(10p{N}/source_primes_P/, filenames ending in _P.bin).

With PRIMEATLAS_PT1_VERIFY=1 every P slab is verified right after its sieve (pt1_verify.py):
sieved again to the bound s and every survivor decided by the pseudosquares proof. A window
whose proven list equals its BPSW list is written to the D store and listed as D/P; a
different one is written to the P store and listed in DP_MISMATCH.txt. The proof's time is
measured on its own (proof_seconds in the metrics handoff, sieve_seconds without it), so a
run reports the sieve alone and the sieve with the proof. A count-only run verifies too and
only reports.

Memory is two slab bitmaps (slab k+1 is sieved while slab k is written, overlap_pipeline.py)
plus one flag chunk per thread, independent of the run length.
Floors 0..6 (the scanners' low-floor path) and floors above 37 (n >= 2^127) are refused.
"""
import datetime
import json
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



def _add_to_handoff(portal_folder, **fields):
    """Adds fields to the metrics handoff prime_sieve_v5.write_scan_metrics_handoff() just
    wrote (that writer is frozen with v5)."""
    path = os.path.join(portal_folder, SCAN_METRICS_FILENAME)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data.update(fields)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except (OSError, ValueError) as e:
        print(f"[!] WARNING: could not extend the scan metrics handoff ({e})")


def main_batch_scanner(base_power, target_idx_list, window_m, write_files=True,
                        compute_sieving_primes_count=False, requested_b=0,
                        chunk_kb=pt1_plan.DEFAULT_CHUNK_KB, verify=False):
    """Returns 0, or 2 when the floor or B is outside pt1's range or a P window of a
    verifying run cannot be verified (pt1_verify.LIMIT_TEXT)."""
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
    kinds = [storage_kinds.written_kind(storage_kinds.ENGINE_PT1, lo, hi) for lo, hi in windows]
    chunk_odd = pt1_plan.chunk_odd(chunk_kb)
    slabs = pt1_plan.plan_slabs(windows, kinds, pt1_plan.slab_numbers(MAX_WORKERS, chunk_kb))
    p_windows = [w for w, kind in zip(windows, kinds) if kind == storage_kinds.KIND_P]
    verify = verify and bool(p_windows)
    s = pt1_verify.bound(b, p_windows[0][0], combined_hi) if verify else None
    if verify and s is None:
        print(f"[-] ERROR: the verification proves numbers below {pt1_verify.LIMIT_TEXT}, the "
              f"range ends at {combined_hi:,}; untick the verification for this range.")
        return 2

    def _slab_chunks(kind, ix):
        n = math.ceil(((windows[ix[-1]][1] - (windows[ix[0]][0] | 1) + 1) // 2) / chunk_odd)
        return 2 * n if verify and kind == storage_kinds.KIND_P else n
    n_chunks_total = sum(_slab_chunks(kind, ix) for kind, ix in slabs)

    print("\n" + "=" * 70)
    print(f"[*] BATCH {VERSION} (partial sieve to B + primality test, PGS2 binary output): "
          f"{len(windows)} windows (target_idx {target_idx_list[0]}..{target_idx_list[-1]}), "
          f"level 10^{base_power}")
    print(f"[*] Combined range: [{combined_lo:,}, {combined_hi:,})  "
          f"size={combined_hi - combined_lo:,}")
    print(f"[*] Sieve limit B = {b:,}" + (" (default floor(N^(1/4)))" if not requested_b else
                                          f" (requested {requested_b:,})"))
    n_d = kinds.count(storage_kinds.KIND_D)
    print(f"[*] Windows: {n_d} D (13 Miller-Rabin bases, proven), {len(windows) - n_d} P "
          f"(BPSW, probable) | {len(slabs)} slabs, {chunk_kb} KiB chunks, {MAX_WORKERS} threads")
    if verify:
        print(f"[*] Verification P -> D after each P slab: pseudosquares proof, sieve bound "
              f"s = {s:,}")
    if not write_files:
        print("[*] WRITE_FILES=False -- no PGS2 files will be written this run; only "
              "aggregate prime counts will be reported.")
    print("=" * 70)

    t_base = time.perf_counter()
    lib = pt1_lib.load()
    ctx = lib.pt1_ctx_new(b)
    verify_ctx = (lib.pt1_ctx_new(s) if s > b else ctx) if verify else None
    if not ctx or (verify and not verify_ctx):
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
    verify_seconds = 0.0
    proven_tags, mismatches = set(), []
    windows_proven = 0
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
        nonlocal chunks_before, verify_seconds
        kind, ix = slab
        slab_lo, slab_hi = windows[ix[0]][0], windows[ix[-1]][1]
        det = 1 if kind == storage_kinds.KIND_D else 0
        sieved = pt1_lib.run_slab(
            lambda first_hi, first_lo, n_odd, bits, done: lib.pt1_sieve_odd(
                ctx, first_hi, first_lo, n_odd, det, MAX_WORKERS, chunk_odd, bits, done),
            slab_lo, slab_hi, _progress)
        n_chunks = math.ceil(((slab_hi - sieved[0] + 1) // 2) / chunk_odd)
        chunks_before += n_chunks
        proven = None
        if verify and kind == storage_kinds.KIND_P:
            t_verify = time.perf_counter()
            proven = pt1_verify.verify_slab(verify_ctx, slab_lo, slab_hi, MAX_WORKERS, chunk_odd,
                                            _progress)
            verify_seconds += time.perf_counter() - t_verify
            chunks_before += n_chunks
        return sieved, proven

    def _write(slab, sieved_proven):
        nonlocal total_primes_found, bytes_written, windows_proven
        kind, ix = slab
        (first_odd, bits), proven = sieved_proven
        for i in ix:
            lo, hi = windows[i]
            offset = lo - BASE
            out_kind = kind
            offsets = None
            if proven is not None:
                offsets = _window_prime_offsets(bits, first_odd, lo, hi)
                proven_offsets = _window_prime_offsets(proven[1], proven[0], lo, hi)
                first = pt1_verify.first_difference(lo, offsets, proven_offsets)
                tag = storage_kinds.window_tag(storage_kinds.window_filename(
                    base_power, format_offset(offset), kind))
                if first is None:
                    out_kind = storage_kinds.KIND_D
                    windows_proven += 1
                    proven_tags.add(tag)
                else:
                    mismatches.append((tag, first, len(proven_offsets), len(offsets)))
            if write_files:
                path = storage_kinds.window_path(BASE_STORAGE_10PN, base_power, offset, window_m,
                                                 format_offset(offset), out_kind)
                if offsets is None:
                    offsets = _window_prime_offsets(bits, first_odd, lo, hi)
                total_primes_found += len(offsets)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                write_prime_window_offsets(path, lo, offsets, generated_at=int(time.time()))
                bytes_written += os.path.getsize(path)
            elif offsets is not None:
                total_primes_found += len(offsets)
            else:
                total_primes_found += _window_prime_count(bits, first_odd, lo, hi)

    # Slab k+1 is sieved while slab k is unpacked and written (overlap_pipeline.py).
    try:
        timings = run_overlapped(slabs, _sieve, _write)
    finally:
        lib.pt1_ctx_free(ctx)
        if verify_ctx and verify_ctx != ctx:
            lib.pt1_ctx_free(verify_ctx)
    t_sieve, t_write = timings.produce_seconds - verify_seconds, timings.consume_seconds
    _progress(0)
    if write_files and (proven_tags or mismatches):
        import dp_verify
        dp_verify.record(BASE_STORAGE_10PN, base_power, proven_tags, mismatches)

    print(f"\n[*] Sieve + test {t_sieve:.2f}s, unpack + write {t_write:.2f}s (overlapped with "
          f"the sieve; {timings.wait_seconds:.2f}s not hidden)")
    if verify:
        numbers = combined_hi - combined_lo
        alone = numbers / t_sieve if t_sieve > 0 else float("nan")
        both = numbers / (t_sieve + verify_seconds) if t_sieve + verify_seconds > 0 else float("nan")
        print(f"[*] Verification P -> D: {windows_proven} of {len(p_windows)} P windows proven "
              f"(D/P), {len(mismatches)} mismatches | proof {verify_seconds:.2f}s | sieve "
              f"alone {alone:,.0f} n/s, sieve + proof {both:,.0f} n/s "
              f"({(1 - both / alone) * 100:.1f}% slower)")
    print(f"[*] TOTAL PRIMES FOUND this run: {total_primes_found:,} across {len(windows)} windows"
          + ("" if write_files else "  (NO FILES WRITTEN -- count-only mode)"))
    write_scan_metrics_handoff(BASE_STORAGE_10PN, b,
                                sieving_primes_count if compute_sieving_primes_count else None,
                                total_primes_found=total_primes_found,
                                windows_processed=len(windows), write_files=write_files,
                                base_gen_seconds=base_gen_seconds, sieve_seconds=t_sieve,
                                write_seconds=t_write, bytes_written=bytes_written,
                                numbers_processed=combined_hi - combined_lo)
    if verify:
        _add_to_handoff(BASE_STORAGE_10PN, proof_seconds=verify_seconds,
                        windows_proven=windows_proven, proof_mismatches=len(mismatches))
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
        VERIFY = pt1_verify.verify_from_env(os.environ)
    except ValueError as e:
        print(f"[-] ERROR: {e}")
        sys.exit(2)

    print("Start time:", datetime.datetime.now().strftime("%H:%M:%S"))
    sys.exit(main_batch_scanner(base_exponent, target_idx_list, WINDOW_M, write_files=WRITE_FILES,
                                compute_sieving_primes_count=COMPUTE_SIEVING_PRIMES_COUNT,
                                requested_b=REQUESTED_B, chunk_kb=CHUNK_KB, verify=VERIFY))
