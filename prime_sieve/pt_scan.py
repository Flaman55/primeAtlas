"""pt_scan.py -- the batch loop shared by engines pt1 and pt2 (partial sieve + test).

A run's windows are grouped into slabs of consecutive windows with the same test
(pt1_plan.plan_slabs()); each slab is one odd-only composite bitmap filled by the engine's C
call, and slab k+1 is sieved while slab k is unpacked and written (overlap_pipeline.py).
The engine supplies the C call per slab, the store each slab's windows go to and the lines
of its banner; this module prints the progress, writes the windows (PGS2) and hands the
metrics to the orchestrator. Memory is two slab bitmaps plus one flag chunk per thread,
independent of the run length.
"""
import ctypes
import math
import os
import threading
import time

import numpy as np

import storage_kinds
from overlap_pipeline import run_overlapped
from prime_sieve_v5 import (_window_prime_count, _window_prime_offsets, format_offset,
                            write_scan_metrics_handoff)


def sieve_slab(engine_call, lo, hi, on_progress, poll_seconds=0.5):
    """(first_odd, composite bitmap as a uint8 array) for the odd numbers of [lo, hi), or
    raises RuntimeError when engine_call(first_odd, n_odd, bits_ptr, done) returns non-zero.
    The call runs in a helper thread (ctypes releases the GIL) so on_progress(chunks_done)
    can report meanwhile."""
    first_odd = lo | 1
    n_odd = max(0, (hi - first_odd + 1) // 2)
    bits = np.zeros((n_odd + 7) // 8, dtype=np.uint8)
    done = (ctypes.c_uint64 * 1)(0)
    result = {}

    def _call():
        result["code"] = engine_call(first_odd, n_odd,
                                     bits.ctypes.data_as(ctypes.POINTER(ctypes.c_ubyte)), done)

    worker = threading.Thread(target=_call, daemon=True)
    worker.start()
    while worker.is_alive():
        worker.join(poll_seconds)
        on_progress(done[0])
    if result.get("code", -1) != 0:
        raise RuntimeError("engine error")
    return first_odd, bits


def run_slabs(*, version, portal, base_power, windows, window_m, slabs, store_kind, slab_call,
              chunk_odd, b, sieving_primes_count, base_gen_seconds, write_files,
              compute_sieving_primes_count):
    """Sieves and writes `slabs` ([(test, [window indices])]) of `windows` ([(lo, hi)]):
    slab_call(test) is the C call (first_odd, n_odd, bits_ptr, done) -> code for a slab of
    that test, store_kind(test) the store its windows go to. Prints progress and the totals,
    writes the metrics handoff. Returns 0."""
    base = 10 ** base_power
    n_chunks_total = sum(
        math.ceil(((windows[ix[-1]][1] - (windows[ix[0]][0] | 1) + 1) // 2) / chunk_odd)
        for _test, ix in slabs)
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
        test, ix = slab
        slab_lo, slab_hi = windows[ix[0]][0], windows[ix[-1]][1]
        sieved = sieve_slab(slab_call(test), slab_lo, slab_hi, _progress)
        chunks_before += math.ceil(((slab_hi - sieved[0] + 1) // 2) / chunk_odd)
        return sieved

    def _write(slab, sieved):
        nonlocal total_primes_found, bytes_written
        test, ix = slab
        first_odd, bits = sieved
        for i in ix:
            lo, hi = windows[i]
            if write_files:
                offset = lo - base
                path = storage_kinds.window_path(portal, base_power, offset, window_m,
                                                 format_offset(offset), store_kind(test))
                offsets = _window_prime_offsets(bits, first_odd, lo, hi)
                total_primes_found += len(offsets)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                write_prime_window_offsets(path, lo, offsets, generated_at=int(time.time()))
                bytes_written += os.path.getsize(path)
            else:
                total_primes_found += _window_prime_count(bits, first_odd, lo, hi)

    # Slab k+1 is sieved while slab k is unpacked and written (overlap_pipeline.py).
    timings = run_overlapped(slabs, _sieve, _write)
    t_sieve, t_write = timings.produce_seconds, timings.consume_seconds
    _progress(0)

    print(f"\n[*] Sieve + test {t_sieve:.2f}s, unpack + write {t_write:.2f}s (overlapped with "
          f"the sieve; {timings.wait_seconds:.2f}s not hidden)")
    print(f"[*] TOTAL PRIMES FOUND this run: {total_primes_found:,} across {len(windows)} windows"
          + ("" if write_files else "  (NO FILES WRITTEN -- count-only mode)"))
    combined_lo, combined_hi = windows[0][0], windows[-1][1]
    write_scan_metrics_handoff(portal, b,
                               sieving_primes_count if compute_sieving_primes_count else None,
                               total_primes_found=total_primes_found,
                               windows_processed=len(windows), write_files=write_files,
                               base_gen_seconds=base_gen_seconds, sieve_seconds=t_sieve,
                               write_seconds=t_write, bytes_written=bytes_written,
                               numbers_processed=combined_hi - combined_lo)
    print("=" * 70)
    return 0


def adjacent_windows(base_power, target_idx_list, window_m):
    """[(lo, hi)] of the sorted target windows; asserts they are adjacent."""
    base = 10 ** base_power
    idxs = sorted(target_idx_list)
    windows = [(base + idx * window_m, base + (idx + 1) * window_m) for idx in idxs]
    for i in range(1, len(windows)):
        assert windows[i][0] == windows[i - 1][1], (
            f"Batch mode requires ADJACENT windows (consecutive target_idx) -- gap before "
            f"target_idx={idxs[i]}")
    return windows
