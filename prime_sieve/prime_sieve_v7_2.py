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
import work_plan_v7_2
import engine_v7_2_lib
from prime_sieve_v5 import (LOW_FLOOR_CUTOFF, SCAN_METRICS_FILENAME,  # noqa: F401
                            _low_floor_segments, format_offset, read_prime_window_header,
                            write_scan_metrics_handoff)


VERSION = "v7.2"   # bump this whenever this file changes, so console output alone identifies
                    # exactly which iteration of the code produced it.

MAX_WORKERS = 24
BATCHES_PER_WORKER = 2    # how many contiguous cost-equal batches per worker

# pi(L_final) is a diagnostic statistic only (see prime_sieve_v5.py); off by default.
COMPUTE_SIEVING_PRIMES_COUNT = False

# ==========================================================================================
# prime_sieve_v7_2.py
#
# Batch scanner for engine v7.2, driven by orchestrator_v3.py when SCANNER_VERSION = "v7". It is
# prime_sieve_v7_1.py (v7.1) on engine v7.2 (prime_sieve_engine_v7_2.c: v7.0's with a cheaper
# block setup) with the jump gear's block factor from work_plan_v7_2.block_factor(), the
# optimum of the gear's cost between block setups and candidates, instead of the fixed 0.5;
# p* and the progress weights use the gear's cost at that factor. Knob:
# PRIMEATLAS_V7_BLOCK_MODEL_PCT (the factor in percent of the model's).
#
# v7.1 is prime_sieve_v7_0.py (v7.0) with two changes:
#   - the jump threshold p* comes from work_plan_v7_2.jump_from(): a cost model with the gear's
#     block setups (~ sqrt(first / span)) next to its landings (~ span), p* = ln p* * (a *
#     sqrt(first / span) + b * span), the knob being a percentage of the model;
#   - the progress line's percent and ETA follow the estimated cost of the finished jobs
#     (work_plan_v7_2.stage_weights()), not their count; the counts stay in the line. Each
#     stage's wall time is printed when it ends.
# Output (PGS2 files, metrics handoff, benchmark_log.csv columns) is byte-identical to v6.1's
# apart from the PGS2 generation timestamp; unitTests/test_engine_v7_2_identity.py checks that.
#
# The jump gear (engine_jump_gear.h): the bucketed sieving primes from p* up are not walked
# prime by prime; the gear walks their range in blocks and finds only the q whose one multiple
# lands in the run's buffer. The classic primes below keep v6.1's path. Knobs: work_plan_v7_2.py
# (v7.0's PRIMEATLAS_V7_* knobs plus _JUMP_MODEL_PCT, _JUMP_BLOCK_COST, _JUMP_LANDING_COST_PCT,
# _BLOCK_MODEL_PCT; v7.0's fixed _JUMP_BLOCK_PCT is not read).
#
# The rest is v6.1's (see prime_sieve_v6_1.py): the wheel-30 buffer, segmented slices in
# forked worker processes, one multi-threaded sieve_wheel_bucketed() call, the parallel
# window writer, the low-floor split and the metrics handoff.
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
    return engine_v7_2_lib.load_lib()


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


def _run_bucketed(pieces, base, n_bits, region_bits, n_threads, bucket_mb, jump_lo,
                  block_factor, on_progress, poll_seconds=0.5):
    """Marks the sieving primes of `pieces` with one sieve_wheel_bucketed() call in a helper
    thread (ctypes releases the GIL), reporting on_progress(finished_pieces) meanwhile.
    Pieces from jump_lo up go to the jump gear (jump_lo = 0: none). Returns True on an
    engine error. No other job may write the buffer meanwhile."""
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
            bucket_mb * 1024 * 1024, jump_lo, block_factor, buf, done)

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
               pieces_per_thread, jump_model_pct, jump_block_cost, jump_landing_cost_pct,
               block_model_pct):
    """Sieves the whole buffer: segmented slices in worker processes, then the bucketed
    primes. Returns the number of jobs that reported an engine error."""
    n_batches = max(1, MAX_WORKERS * BATCHES_PER_WORKER)
    seg_bits = work_plan_v7_2.segment_bits(segment_kb)
    small_stop = work_plan_v7_2.small_prime_stop(seg_bits, L_final)
    slices = work_plan_v7_2.plan_slices(n_bits, n_batches, min_slice_bits=seg_bits)
    span = 30 * ((n_bits + 7) // 8)   # numbers the buffer covers, as the engine counts them
    factor = work_plan_v7_2.block_factor(base, span, block_model_pct, jump_block_cost,
                                         jump_landing_cost_pct)
    eff_block, eff_landing = work_plan_v7_2.effective_costs(factor, jump_block_cost,
                                                            jump_landing_cost_pct)
    jump_lo = work_plan_v7_2.jump_from_v7_2(base, span, jump_model_pct, factor,
                                            jump_block_cost, jump_landing_cost_pct)
    classic, jumped = work_plan_v7_2.plan_bucketed(L_final, combined_size, small_stop,
                                                 MAX_WORKERS, pieces_per_thread, jump_lo)
    pieces = classic + jumped
    jump_lo = jumped[0][0] if jumped else 0
    jobs = [(lo, hi, base, small_stop, seg_bits // 64) for lo, hi in slices]
    n_processes = max(1, min(MAX_WORKERS, len(jobs)))
    n_total = len(jobs) + len(pieces)
    slice_weights, piece_weights = work_plan_v7_2.stage_weights(
        len(jobs), classic, jumped, combined_size, small_stop, L_final, base, span,
        eff_block, eff_landing)
    weights = slice_weights + piece_weights

    print(f"[*] Segmented slices: {len(slices)} ({segment_kb} KiB segments, primes "
          f"7..{small_stop - 1:,}, {n_processes} parallel processes); bucketed pieces: "
          f"{len(pieces)} (primes {small_stop:,}..{L_final - 1:,}, {MAX_WORKERS} threads, "
          f"{region_kb} KiB regions, {bucket_mb} MiB buckets)", flush=True)
    gain = work_plan_v7_2.gear_gain(base, span, factor, jump_block_cost, jump_landing_cost_pct)
    model = (f"{jump_model_pct} % of the model, block cost {jump_block_cost}, landing cost "
             f"{jump_landing_cost_pct} %, block factor {factor:.2f} ({block_model_pct} % of the "
             f"model), {gain:.2f} x cheaper per q than at 0.5")
    if jumped:
        print(f"[*] Jump gear: {len(jumped)} of the pieces, primes {jump_lo:,}..{L_final - 1:,} "
              f"({model}); estimated cost share "
              f"{sum(piece_weights[len(classic):]) * 100:.1f} %", flush=True)
    else:
        print(f"[*] Jump gear: off for this run ({model})", flush=True)

    errors = 0
    print_interval = max(1, n_total // 30)
    t_start = time.perf_counter()
    t_last = [t_start]

    def _print_progress(done_count):
        t_now = time.perf_counter()
        share = work_plan_v7_2.progress(weights, done_count)
        elapsed = t_now - t_start
        remaining = elapsed * (1 - share) / share if share > 0 else float("inf")
        print(f"[+] Progress: {share * 100:.2f}% ({done_count}/{n_total} "
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

    t_slices = time.perf_counter() - t_start
    print(f"[*] Segmented slices done in {t_slices:.2f}s", flush=True)
    slices_done = len(jobs)
    last_printed = [slices_done]

    def _on_pieces(pieces_done):
        count = slices_done + pieces_done
        if count - last_printed[0] >= print_interval or count == n_total:
            last_printed[0] = count
            _print_progress(count)

    if _run_bucketed(pieces, base, n_bits, work_plan_v7_2.region_bits(region_kb), MAX_WORKERS,
                     bucket_mb, jump_lo, factor, _on_pieces):
        errors += 1
    print(f"[*] Bucketed pieces done in {time.perf_counter() - t_start - t_slices:.2f}s",
          flush=True)
    return errors


def main_batch_scanner(base_power, target_idx_list, window_m, write_files=True,
                       compute_sieving_primes_count=True, use_known_pi_seed=False,
                       segment_kb=work_plan_v7_2.DEFAULT_SEGMENT_KB,
                       region_kb=work_plan_v7_2.DEFAULT_REGION_KB,
                       bucket_mb=work_plan_v7_2.DEFAULT_BUCKET_MB,
                       pieces_per_thread=work_plan_v7_2.DEFAULT_PIECES_PER_THREAD,
                       write_threads=work_plan_v7_2.DEFAULT_WRITE_THREADS,
                       jump_model_pct=work_plan_v7_2.DEFAULT_JUMP_MODEL_PCT,
                       jump_block_cost=work_plan_v7_2.DEFAULT_JUMP_BLOCK_COST,
                       jump_landing_cost_pct=work_plan_v7_2.DEFAULT_JUMP_LANDING_COST_PCT,
                       block_model_pct=work_plan_v7_2.DEFAULT_BLOCK_MODEL_PCT):
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
                        pieces_per_thread, jump_model_pct, jump_block_cost,
                        jump_landing_cost_pct, block_model_pct)
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
    SEGMENT_KB = work_plan_v7_2.segment_kb_from_env(os.environ)
    REGION_KB = work_plan_v7_2.region_kb_from_env(os.environ)
    BUCKET_MB = work_plan_v7_2.bucket_mb_from_env(os.environ)
    PIECES_PER_THREAD = work_plan_v7_2.pieces_per_thread_from_env(os.environ)
    WRITE_THREADS = work_plan_v7_2.write_threads_from_env(os.environ)
    JUMP_MODEL_PCT = work_plan_v7_2.jump_model_pct_from_env(os.environ)
    JUMP_BLOCK_COST = work_plan_v7_2.jump_block_cost_from_env(os.environ)
    JUMP_LANDING_COST_PCT = work_plan_v7_2.jump_landing_cost_pct_from_env(os.environ)
    BLOCK_MODEL_PCT = work_plan_v7_2.block_model_pct_from_env(os.environ)

    print("Start time:", datetime.datetime.now().strftime("%H:%M:%S"))
    main_batch_scanner(base_exponent, target_idx_list, WINDOW_M, write_files=WRITE_FILES,
                       compute_sieving_primes_count=COMPUTE_SIEVING_PRIMES_COUNT,
                       use_known_pi_seed=USE_KNOWN_PI_SEED, segment_kb=SEGMENT_KB,
                       region_kb=REGION_KB, bucket_mb=BUCKET_MB,
                       pieces_per_thread=PIECES_PER_THREAD, write_threads=WRITE_THREADS,
                       jump_model_pct=JUMP_MODEL_PCT, jump_block_cost=JUMP_BLOCK_COST,
                       jump_landing_cost_pct=JUMP_LANDING_COST_PCT,
                       block_model_pct=BLOCK_MODEL_PCT)
