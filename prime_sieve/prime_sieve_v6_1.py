import ctypes
import datetime
import mmap
import multiprocessing
import numpy as np
import time
import os
import math
import concurrent.futures
import threading
from concurrent.futures import ProcessPoolExecutor

import window_sharding
import wheel30_layout
import wheel30_writer
import work_plan_v6
import engine_v6_lib
from prime_sieve_v5 import (LOW_FLOOR_CUTOFF, SCAN_METRICS_FILENAME,  # noqa: F401
                            _low_floor_segments, format_offset, read_prime_window_header,
                            write_scan_metrics_handoff)


VERSION = "v6.1"   # bump this whenever this file changes, so console output alone identifies
                    # exactly which iteration of the code produced it.

MAX_WORKERS = 24
BATCHES_PER_WORKER = 2    # how many contiguous cost-equal batches per worker

# pi(L_final) is a diagnostic statistic only (see prime_sieve_v5.py); off by default.
COMPUTE_SIEVING_PRIMES_COUNT = False

# ==========================================================================================
# prime_sieve_v6_1.py
#
# Batch scanner for engine v6.1 (prime_sieve_engine_v6_1.c), driven by orchestrator_v3.py when
# SCANNER_VERSION = "v6". It is prime_sieve_v6.py (v6.0, frozen) on the v6.1 engine: the
# unrolled wheel-turn marking of the segmented primes and the staged bucket writes (see the
# engine's header). Output (PGS2 files, metrics handoff, benchmark_log.csv columns) is
# byte-identical to v6.0's apart from the PGS2 generation timestamp;
# unitTests/test_engine_v6_1_identity.py checks that. The write phase (wheel30_writer.py)
# encodes windows with v6.0's wheel_window_gaps(), which v6.1 does not change.
#
# What differs from v5 is the buffer: a wheel-30 bitmap (wheel30_layout.py), 8 bits per 30
# numbers instead of one bit per odd number, so a run of the same memory covers 1.875 times
# as many numbers. Every run generates all sieving primes below sqrt(top) once (the fixed
# cost that dominates deep floors), so the longer run spreads it over more numbers. The rest
# of the pipeline is v5's:
#   - segmented slices of the buffer sieved in cache-sized segments by the small primes in
#     worker processes, then one multi-threaded sieve_wheel_bucketed() call for the other
#     sieving primes (work_plan_v6.py);
#   - a shared mmap output buffer inherited by the forked workers, per-window unpacking
#     straight from the mapping (wheel30_layout.window_prime_offsets()), low-floor splitting
#     by real floor boundary, PGS2 output through pgs2_vector;
#   - format_offset(), read_prime_window_header(), the low-floor split and the metrics
#     handoff are v5's own functions, imported.
# ==========================================================================================

# The shared mmap output buffer: a module-level global set BEFORE the ProcessPoolExecutor is
# created, so the forked workers inherit it (mmap objects are not picklable).
_shm_mmap = None
_shm_size = 0
BASE_STORAGE_10PN = None


def _init_shared_buffer(n_bytes):
    """Allocates the one shared output buffer, rounded up to whole 64-bit words for the
    segmented path's word-wide ORs. MUST run before the worker pool forks."""
    global _shm_mmap, _shm_size
    n_bytes = max(8, (n_bytes + 7) // 8 * 8)
    _shm_mmap = mmap.mmap(-1, n_bytes, flags=mmap.MAP_SHARED)
    _shm_size = n_bytes
    return _shm_mmap


def _load_lib():
    return engine_v6_lib.load_lib(engine_v6_lib.V6_1)


def _split128(n):
    return n >> 64, n & 0xFFFFFFFFFFFFFFFF


def process_slice(bit_lo, bit_hi, base, small_stop, segment_words):
    """Sieves bits [bit_lo, bit_hi) of the shared buffer with the primes 7..small_stop-1
    (sieve_wheel_segmented()); returns True on an engine error."""
    lib = _load_lib()
    words = (ctypes.c_uint64 * (_shm_size // 8)).from_buffer(_shm_mmap)
    out_ptr = ctypes.cast(words, ctypes.POINTER(ctypes.c_uint64))
    code = lib.sieve_wheel_segmented(small_stop, *_split128(base), bit_lo, bit_hi,
                                     segment_words, out_ptr)
    return code != 0


def _run_bucketed(pieces, base, n_bits, region_bits, n_threads, bucket_mb, on_progress,
                  poll_seconds=0.5):
    """Marks the sieving primes of `pieces` with one sieve_wheel_bucketed() call in a helper
    thread (ctypes releases the GIL), reporting on_progress(finished_pieces) meanwhile.
    Returns True on an engine error. No other job may write the buffer meanwhile."""
    if not pieces:
        return False
    lib = _load_lib()
    n = len(pieces)
    piece_lo = (ctypes.c_uint64 * n)(*[lo for lo, _ in pieces])
    piece_hi = (ctypes.c_uint64 * n)(*[hi for _, hi in pieces])
    done = (ctypes.c_uint64 * 1)(0)
    result = {}

    def _call():
        # The array view lives only inside this call, so the mmap has no exported pointer
        # left once the thread ends; main_batch_scanner() closes the mmap later.
        buf = (ctypes.c_ubyte * _shm_size).from_buffer(_shm_mmap)
        result["code"] = lib.sieve_wheel_bucketed(
            piece_lo, piece_hi, n, *_split128(base), n_bits, region_bits, n_threads,
            bucket_mb * 1024 * 1024, buf, done)

    worker = threading.Thread(target=_call, daemon=True)
    worker.start()
    reported = 0
    while worker.is_alive():
        worker.join(poll_seconds)
        if done[0] != reported:
            reported = done[0]
            on_progress(reported)
    if done[0] != reported:
        on_progress(done[0])
    return result.get("code", -1) != 0


def _run_sieve(base, n_bits, L_final, combined_size, segment_kb, region_kb, bucket_mb,
               pieces_per_thread):
    """Sieves the whole buffer: segmented slices in worker processes, then the bucketed
    primes. Returns the number of jobs that reported an engine error."""
    n_batches = max(1, MAX_WORKERS * BATCHES_PER_WORKER)
    seg_bits = work_plan_v6.segment_bits(segment_kb)
    small_stop = work_plan_v6.small_prime_stop(seg_bits, L_final)
    slices = work_plan_v6.plan_slices(n_bits, n_batches, min_slice_bits=seg_bits)
    pieces = work_plan_v6.plan_pieces(L_final, combined_size, small_stop, MAX_WORKERS,
                                      pieces_per_thread)
    jobs = [(lo, hi, base, small_stop, seg_bits // 64) for lo, hi in slices]
    n_processes = max(1, min(MAX_WORKERS, len(jobs)))
    n_total = len(jobs) + len(pieces)

    print(f"[*] Segmented slices: {len(slices)} ({segment_kb} KiB segments, primes "
          f"7..{small_stop - 1:,}, {n_processes} parallel processes); bucketed pieces: "
          f"{len(pieces)} (primes {small_stop:,}..{L_final - 1:,}, {MAX_WORKERS} threads, "
          f"{region_kb} KiB regions, {bucket_mb} MiB buckets)", flush=True)

    errors = 0
    print_interval = max(1, n_total // 30)
    t_start = time.perf_counter()
    t_last = [t_start]

    def _print_progress(done_count):
        t_now = time.perf_counter()
        rate = done_count / (t_now - t_start) if (t_now - t_start) > 0 else 0
        remaining = (n_total - done_count) / rate if rate > 0 else float("inf")
        print(f"[+] Progress: {done_count / n_total * 100:.2f}% ({done_count}/{n_total} "
              f"batches) | time: {t_now - t_start:.2f}s (+{t_now - t_last[0]:.2f}s since last "
              f"print) | ETA ~{remaining:.0f}s" + (f" | ERRORS={errors}" if errors else ""),
              flush=True)
        t_last[0] = t_now

    ctx = multiprocessing.get_context("fork")   # the shared mmap needs fork(), not spawn
    with ProcessPoolExecutor(max_workers=n_processes, mp_context=ctx) as executor:
        futures = [executor.submit(process_slice, *args) for args in jobs]
        done_count = 0
        for fut in concurrent.futures.as_completed(futures):
            if fut.result():
                errors += 1
            done_count += 1
            if done_count % print_interval == 0 or done_count == len(jobs):
                _print_progress(done_count)

    slices_done = len(jobs)
    last_printed = [slices_done]

    def _on_pieces(pieces_done):
        count = slices_done + pieces_done
        if count - last_printed[0] >= print_interval or count == n_total:
            last_printed[0] = count
            _print_progress(count)

    if _run_bucketed(pieces, base, n_bits, work_plan_v6.region_bits(region_kb), MAX_WORKERS,
                     bucket_mb, _on_pieces):
        errors += 1
    return errors


def main_batch_scanner(base_power, target_idx_list, window_m, write_files=True,
                       compute_sieving_primes_count=True, use_known_pi_seed=False,
                       segment_kb=work_plan_v6.DEFAULT_SEGMENT_KB,
                       region_kb=work_plan_v6.DEFAULT_REGION_KB,
                       bucket_mb=work_plan_v6.DEFAULT_BUCKET_MB,
                       pieces_per_thread=work_plan_v6.DEFAULT_PIECES_PER_THREAD,
                       write_threads=work_plan_v6.DEFAULT_WRITE_THREADS):
    target_idx_list = sorted(target_idx_list)
    BASE = 10 ** base_power
    windows = [(BASE + idx * window_m, window_m) for idx in target_idx_list]
    for i in range(1, len(windows)):
        assert windows[i][0] == windows[i - 1][0] + window_m, (
            f"Batch mode requires ADJACENT windows (consecutive target_idx) -- gap between "
            f"window {i-1} (target_idx={target_idx_list[i-1]}) and {i} "
            f"(target_idx={target_idx_list[i]})")

    combined_lo = windows[0][0]
    combined_hi = windows[-1][0] + window_m
    N = len(windows)
    combined_size = combined_hi - combined_lo
    base = wheel30_layout.buffer_base(combined_lo)
    combined_bytes = wheel30_layout.buffer_bytes(combined_lo, combined_hi)
    n_bits = combined_bytes * 8

    print("\n" + "=" * 70)
    print(f"[*] BATCH {VERSION} (primesieve, SHARED mmap wheel-30 buffer, segmented + "
          f"bucketed marking, double-precision phase, PGS2 binary output): {N} windows "
          f"(target_idx {target_idx_list[0]}..{target_idx_list[-1]}), level 10^{base_power}")
    print(f"[*] Combined range: [{combined_lo:,}, {combined_hi:,})  size={combined_size:,}  "
          f"({combined_bytes/1e6:.1f} MB, 8 bits per 30 numbers)")
    if not write_files:
        print("[*] WRITE_FILES=False -- no PGS2 files will be written this run; only "
              "aggregate prime counts will be reported.")
    print("=" * 70)

    L_final = math.isqrt(combined_hi) + 1
    print(f"[*] L_final (sieving-prime base limit): {L_final:,}")
    if compute_sieving_primes_count:
        from sieving_prime_count_v5 import count_sieving_primes_cached
        t_count_start = time.perf_counter()
        sieving_primes_count, count_mode = count_sieving_primes_cached(
            BASE_STORAGE_10PN, base_power, L_final, use_known_pi_seed=use_known_pi_seed)
        base_gen_seconds = time.perf_counter() - t_count_start
        print(f"[*] Active sieving primes used (pi(L_final)): {sieving_primes_count:,} "
              f"(computed in {base_gen_seconds:.3f}s, {count_mode})")
    else:
        sieving_primes_count = None
        base_gen_seconds = None   # not measured: blank in the CSV, not a misleading 0.0
        print("[*] Active sieving primes count (pi(L_final)): SKIPPED (diagnostic only; CLI "
              "position 7 = 1 computes it).")
    print(f"[*] Shared output buffer: {combined_bytes/1e6:.1f} MB, one copy total.", flush=True)

    _init_shared_buffer(combined_bytes)
    _load_lib()   # loaded once here, inherited by every forked worker
    t_start = time.perf_counter()
    errors = _run_sieve(base, n_bits, L_final, combined_size, segment_kb, region_kb, bucket_mb,
                        pieces_per_thread)
    t_sieve = time.perf_counter() - t_start
    print(f"\n[*] Batch sieve done in {t_sieve:.2f}s. Unpacking result and writing windows...",
          flush=True)
    if errors:
        print(f"[!] WARNING: {errors} jobs returned an engine error -- results INCOMPLETE.")

    # From here to write_scan_metrics_handoff() is the "write" phase (unpack -> offsets ->
    # PGS2 file). bytes_written stays 0 in count-only mode.
    t_write_start = time.perf_counter()
    bytes_written = 0
    if write_files:
        from pgs2_vector import write_prime_window_offsets
    buf = np.frombuffer(_shm_mmap, dtype=np.uint8, count=combined_bytes)

    def _emit(path, lo, hi):
        nonlocal bytes_written
        if not write_files:
            return wheel30_layout.window_prime_count(buf, base, lo, hi)
        offsets = wheel30_layout.window_prime_offsets(buf, base, lo, hi)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_prime_window_offsets(path, lo, offsets, generated_at=int(time.time()))
        bytes_written += os.path.getsize(path)
        return len(offsets)

    low_floor_segments = _low_floor_segments(base_power, combined_lo, combined_hi)
    total_primes_found = 0
    if low_floor_segments:
        # The combined range spans several real floors: each complete one is written as
        # its own 10p{floor} window (see prime_sieve_v5._low_floor_segments()).
        floor_counts = []
        for floor, floor_lo, floor_hi in low_floor_segments:
            shard = window_sharding.shard_dir(
                os.path.join(BASE_STORAGE_10PN, f"10p{floor}", "source_primes"), 0)
            count = _emit(os.path.join(shard, f"PRIME_WINDOW_10p{floor}_off_0.bin"),
                          floor_lo, floor_hi)
            total_primes_found += count
            floor_counts.append((floor, count))
        windows_processed = len(low_floor_segments)
        print(f"\n[*] Low-floor batch: floor(s) {low_floor_segments[0][0]}-"
              f"{low_floor_segments[-1][0]} written complete, each as its own 10p{{N}} "
              f"window; floor {low_floor_segments[-1][0] + 1} is cut off by this batch's "
              f"range and skipped.")
        for floor, count in floor_counts:
            print(f"    10p{floor}: {count:,} primes")
    else:
        floor_folder = os.path.join(BASE_STORAGE_10PN, f"10p{base_power}", "source_primes")
        jobs = []
        for distance, w in windows:
            offset = distance - BASE
            shard = window_sharding.shard_dir(
                floor_folder, window_sharding.shard_index_for_offset(offset, window_m))
            path = os.path.join(shard,
                                f"PRIME_WINDOW_10p{base_power}_off_{format_offset(offset)}.bin")
            jobs.append((path, distance, distance + w))
        if write_files:
            bytes_written, total_primes_found = wheel30_writer.write_windows(
                buf, base, jobs, int(time.time()), write_threads,
                progress=lambda line: print(line, flush=True))
        else:
            total_primes_found = sum(_emit(*job) for job in jobs)
        windows_processed = N

    del buf  # the mapping cannot close while a NumPy view still exports it
    _shm_mmap.close()
    t_write = time.perf_counter() - t_write_start
    print(f"\n[*] TOTAL PRIMES FOUND this run: {total_primes_found:,} across "
          f"{windows_processed} {'floor(s)' if low_floor_segments else 'windows'}"
          + ("" if write_files else "  (NO FILES WRITTEN -- count-only mode)"))
    write_scan_metrics_handoff(BASE_STORAGE_10PN, L_final, sieving_primes_count,
                               total_primes_found=total_primes_found,
                               windows_processed=windows_processed, write_files=write_files,
                               base_gen_seconds=base_gen_seconds, sieve_seconds=t_sieve,
                               write_seconds=t_write, bytes_written=bytes_written,
                               numbers_processed=combined_size)
    print("=" * 70)


if __name__ == "__main__":
    import sys

    print("=" * 70)
    print(f"[*] PRIME SIEVE -- {VERSION} (primesieve, shared mmap wheel-30 buffer, segmented "
          f"+ bucketed marking, PGS2 binary output)")
    print("=" * 70)

    # CONSTELLATION_PORTAL_DIR: the storage folder set in the GUI's Settings tab (see
    # prime_sieve_v5.py); unset -> CONSTELLATION_PORTAL next to the application root.
    BASE_STORAGE_10PN = os.environ.get("CONSTELLATION_PORTAL_DIR") or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "CONSTELLATION_PORTAL"))
    print(f"[*] Windows written to: {BASE_STORAGE_10PN}\\10p{{N}}\\source_primes\\")

    if len(sys.argv) > 4:
        base_exponent = int(sys.argv[1])
        target_idx_start = int(sys.argv[2])
        target_idx_stop = int(sys.argv[3])
        MAX_WORKERS = int(sys.argv[4])
    else:
        base_exponent, target_idx_start, target_idx_stop, MAX_WORKERS = 25, 49, 52, 24
    if len(sys.argv) > 5:
        BATCHES_PER_WORKER = int(sys.argv[5])
    WRITE_FILES = bool(int(sys.argv[6])) if len(sys.argv) > 6 else True
    if len(sys.argv) > 7:
        COMPUTE_SIEVING_PRIMES_COUNT = bool(int(sys.argv[7]))
    # WINDOW_M: numbers per target_idx step, CLI position 8 (same as v5).
    WINDOW_M = int(sys.argv[8]) if len(sys.argv) > 8 else 10 ** 7
    target_idx_list = list(range(target_idx_start, target_idx_stop + 1))

    USE_KNOWN_PI_SEED = bool(int(os.environ.get("PRIMEATLAS_USE_KNOWN_PI_SEED", "0")))
    SEGMENT_KB = work_plan_v6.segment_kb_from_env(os.environ)
    REGION_KB = work_plan_v6.region_kb_from_env(os.environ)
    BUCKET_MB = work_plan_v6.bucket_mb_from_env(os.environ)
    PIECES_PER_THREAD = work_plan_v6.pieces_per_thread_from_env(os.environ)
    WRITE_THREADS = work_plan_v6.write_threads_from_env(os.environ)

    print("Start time:", datetime.datetime.now().strftime("%H:%M:%S"))
    main_batch_scanner(base_exponent, target_idx_list, WINDOW_M, write_files=WRITE_FILES,
                       compute_sieving_primes_count=COMPUTE_SIEVING_PRIMES_COUNT,
                       use_known_pi_seed=USE_KNOWN_PI_SEED, segment_kb=SEGMENT_KB,
                       region_kb=REGION_KB, bucket_mb=BUCKET_MB,
                       pieces_per_thread=PIECES_PER_THREAD, write_threads=WRITE_THREADS)
