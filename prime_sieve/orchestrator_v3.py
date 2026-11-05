import subprocess
import sys
import os
import csv
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

try:
    import resource  # POSIX-only (WSL/Linux) -- used for peak child-process RAM tracking.
except ImportError:
    resource = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import generation_stop
from floor_meta_store import append_benchmark_row_to_floor_meta
import storage_kinds
from benchmark_log_schema import (BENCHMARK_FIELDNAMES, RUN_STATUS_COMPLETED,
                                  RUN_STATUS_STOPPED, ensure_benchmark_log_schema)
import window_integrity

# ------------------------------------------------------------------------------------------
# ENGINE SWITCH -- the one flag selecting which scanner (v3, v4, v4.1, v5, v6 or pt1) this orchestrator
# drives; it sets both SCRIPT_NAME and the scanner module import below, so the two can't
# disagree. All scanners write the SAME PGS2 format/filename convention and share
# benchmark_log.csv, so switching is safe at any time, including mid-floor.
# v4 = v3 plus an inlined fast-path modulo for the per-sieving-prime phase computation (see
# prime_sieve_v4.py's header). v4.1 = v4 plus base-gen/sieve/write timing and a
# bytes-written counter in four benchmark_log.csv columns (base_gen_seconds/sieve_seconds/
# write_seconds/bytes_written, see benchmark_log_schema.py). v5 = prime_sieve_v5.py (code
# version v5.1), output identical to v4.1. v6 = the default engine (prime_sieve_v6.py,
# wheel-30 buffer), output identical to v5. pt1 = partial sieve + primality test
# (prime_sieve_pt1.py): D windows identical to v5, BPSW windows from MR_DET_BOUND on go to
# the P store (see storage_kinds.py).
# PRIMEATLAS_SCANNER_VERSION, when set, overrides the default (benchmarks compare engines
# without editing this file).
SCANNER_VERSION = os.environ.get("PRIMEATLAS_SCANNER_VERSION") or "v6"

if SCANNER_VERSION == "v3":
    import prime_sieve_v3 as prime_sieve_module  # noqa: E402
elif SCANNER_VERSION == "v4":
    import prime_sieve_v4 as prime_sieve_module  # noqa: E402
elif SCANNER_VERSION == "v4.1":
    import prime_sieve_v4_1 as prime_sieve_module  # noqa: E402
elif SCANNER_VERSION == "v5":
    import prime_sieve_v5 as prime_sieve_module  # noqa: E402
elif SCANNER_VERSION == "v6":
    import prime_sieve_v6 as prime_sieve_module  # noqa: E402
elif SCANNER_VERSION == "pt1":
    import prime_sieve_pt1 as prime_sieve_module  # noqa: E402
else:
    raise ValueError(f"SCANNER_VERSION must be 'v3', 'v4', 'v4.1', 'v5', 'v6' or 'pt1', "
                     f"got {SCANNER_VERSION!r}")
# The GUI's save-point stop kills processes by this name (generation_stop.py).
SCRIPT_NAME = generation_stop.scanner_script(SCANNER_VERSION)
# format_offset() and read_prime_window_header() (PGS2 fast header peek) are reused here
# for the benchmark summary, instead of duplicating them -- see prime_sieve_module's own
# usages below.


# ==========================================================================================
# orchestrator_v3.py
#
# Launches a scanner subprocess (selected by SCANNER_VERSION above) for a range of windows
# and logs what it did to CONSTELLATION_PORTAL/benchmark_log.csv -- one shared log for every
# scanner, so the growth chart shows one continuous cross-floor history.
# ==========================================================================================


def _parse_bool_arg(value):
    """Parses a 0/1 (or true/false, yes/no, on/off) CLI flag; raises ValueError otherwise."""
    v = value.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"expected 0/1 (or true/false, yes/no, on/off) for auto mode, got: {value!r}")


def format_duration(seconds):
    """Whole seconds from a minute up; one decimal below it, where a low floor's run lasts
    a few seconds."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    return f"{minutes}m {secs}s"


def format_per_window(seconds):
    """Time per window: milliseconds below a second, so a fast floor's run does not read
    0.00 s/window."""
    if seconds != seconds:
        return "n/a s/window"
    if seconds < 1:
        return f"{seconds * 1000:.2f} ms/window"
    return f"{seconds:.2f} s/window"


def find_auto_start(base_exponent, portal_folder, window_m, engine=None):
    """Target_idx to continue this floor from with `engine` (default SCANNER_VERSION): one
    past the highest window of the store that engine writes into
    (storage_kinds.engine_target_idxs()), or None if there is none."""
    idxs = storage_kinds.engine_target_idxs(portal_folder, base_exponent, window_m,
                                            engine or SCANNER_VERSION)
    return max(idxs) + 1 if idxs else None


def reconcile_batch(portal_folder, base_exponent, target_idx_start, target_idx_stop, window_m,
                    workers=None):
    """D proves P (dp_verify.py) for every D window of the batch that has a P counterpart,
    compared by `workers` threads (default WORKERS); returns the {status: count} of the
    comparisons made."""
    import dp_verify
    base = 10 ** base_exponent
    p_dir = storage_kinds.source_dir(portal_folder, base_exponent, storage_kinds.KIND_P)
    if not os.path.isdir(p_dir):
        return {}
    p_paths = []
    for target_idx in range(target_idx_start, target_idx_stop + 1):
        offset = target_idx * window_m
        lo = base + offset
        if storage_kinds.written_kind(SCANNER_VERSION, lo, lo + window_m) != storage_kinds.KIND_D:
            continue
        d_path = storage_kinds.window_path(portal_folder, base_exponent, offset, window_m,
                                           prime_sieve_module.format_offset(offset))
        p_paths.append(dp_verify.counterpart_p_path(d_path))
    if not p_paths:
        return {}
    print(f"[*] D proves P: comparing {len(p_paths):,} windows with their P counterparts...",
          flush=True)
    summary = dp_verify.reconcile_many(portal_folder, base_exponent, p_paths,
                                       WORKERS if workers is None else workers,
                                       progress=lambda line: print(line, flush=True))
    summary = {k: v for k, v in summary.items() if k not in ("no_p", "no_d")}
    if summary:
        print(f"[*] D proves P for target_idx {target_idx_start}..{target_idx_stop}: "
              + ", ".join(f"{k}={v}" for k, v in sorted(summary.items())))
    return summary


# ==============================================================================
# JOB CONFIGURATION
# ==============================================================================
VERSION = "v3.1"   # see prime_sieve_v3.py's VERSION comment -- same reasoning/bump here.
BASE_EXPONENT = 17
START_WINDOW_AUTO = True
START_WINDOW = 0
WINDOW_COUNT = 200
BATCH_SIZE = WINDOW_COUNT
WORKERS = 24
# SCRIPT_NAME is set by the ENGINE SWITCH block near the top of this file (SCANNER_VERSION),
# not here, so the scanner script and the scanner module import always switch together.
WINDOW_M = 10 ** 7
BATCHES_PER_WORKER = 2
WRITE_FILES = True
# count_sieving_primes(L_final) toggle -- see prime_sieve_v3.py's COMPUTE_SIEVING_PRIMES_COUNT
# comment for the full rationale (554s real cost at extreme depth, pure diagnostic stat).
# Default OFF, passed through to the scanner subprocess as CLI position 7.
COMPUTE_SIEVING_PRIMES_COUNT = False
# ==============================================================================


# The scanners' closing report; a low-floor run reports floors, not windows, and does not match.
_ENGINE_TOTAL_RE = re.compile(
    rb"\[\*\] TOTAL PRIMES FOUND this run: ([\d,]+) across (\d+) windows")


# The line every scanner but pt1 prints once, right after its sieve phase.
_SIEVE_DONE = b"[*] Batch sieve done in "


def _engine_total(line):
    m = _ENGINE_TOTAL_RE.search(line)
    return (int(m.group(1).replace(b",", b"")), int(m.group(2))) if m else None


def _run_teed(cmd):
    """Runs cmd with its stdout copied through to ours as it arrives; returns (exit code,
    (total primes, windows) of the scanner's closing report or None, seconds from launch
    to the scanner's _SIEVE_DONE line or None). The report comes from the scanner's own
    stdout, so parallel instances never read each other's (unlike the shared scan-metrics
    handoff file). The scanner runs with PYTHONUNBUFFERED=1 so each line arrives when
    printed (v4.1 and v5 do not flush the sieve line; a scanner prints a few dozen lines
    per run, none per window); the time is read in this process, the scanner's code and
    argv are unchanged."""
    sys.stdout.flush()
    out = getattr(sys.stdout, "buffer", None)
    t_launch = time.perf_counter()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            env=dict(os.environ, PYTHONUNBUFFERED="1"))
    totals = None
    sieve_wall = None
    pending = b""
    fd = proc.stdout.fileno()
    while True:
        chunk = os.read(fd, 65536)
        t_chunk = time.perf_counter()
        if not chunk:
            break
        if out is not None:
            out.write(chunk)
            out.flush()
        else:
            sys.stdout.write(chunk.decode("utf-8", errors="replace"))
            sys.stdout.flush()
        *lines, pending = (pending + chunk).split(b"\n")
        for line in lines:
            totals = _engine_total(line) or totals
            if sieve_wall is None and _SIEVE_DONE in line:
                sieve_wall = t_chunk - t_launch
    totals = _engine_total(pending) or totals
    proc.stdout.close()
    return proc.wait(), totals, sieve_wall


def run_batch(scanner_path, base_exponent, target_idx_start, target_idx_stop, workers,
              batches_per_worker, write_files, compute_sieving_primes_count, window_m,
              engine_totals=None, sieve_walls=None):
    """Runs one scanner batch through _run_teed(); True on exit code 0. The scanner's
    (total primes, windows) report is appended to engine_totals and its launch-to-sieve-
    done seconds to sieve_walls, for the lists given and the lines it prints."""
    cmd = [
        sys.executable,
        scanner_path,
        str(base_exponent),
        str(target_idx_start),
        str(target_idx_stop),
        str(workers),
        str(batches_per_worker),
        "1" if write_files else "0",
        "1" if compute_sieving_primes_count else "0",
        str(window_m),
    ]
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Launching batch target_idx "
          f"{target_idx_start}..{target_idx_stop} "
          f"({target_idx_stop - target_idx_start + 1} windows)"
          + ("" if write_files else ", WRITE_FILES=False (count-only)") + "...")
    returncode, totals, sieve_wall = _run_teed(cmd)
    if engine_totals is not None and totals is not None:
        engine_totals.append(totals)
    if sieve_walls is not None and sieve_wall is not None:
        sieve_walls.append(sieve_wall)
    if returncode != 0:
        print(f"[-] ERROR: batch {target_idx_start}..{target_idx_stop} exited with code "
              f"{returncode} -- stopping.")
        return False
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Batch {target_idx_start}..{target_idx_stop} "
          f"DONE.")
    return True


def read_scan_metrics_handoff(portal_folder):
    """Reads whatever metrics the active scanner's (see SCANNER_VERSION near the top of this
    file) write_scan_metrics_handoff() left behind -- same handoff file/format as v1/v2,
    just written by whichever of v3/v4 actually ran."""
    path = os.path.join(portal_folder, prime_sieve_module.SCAN_METRICS_FILENAME)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def peak_child_rss_mb():
    """Peak resident set size of finished child processes in MB, or None where the
    `resource` module is unavailable."""
    if resource is None:
        return None
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    return ru.ru_maxrss / 1024


def scanner_write_threads(scanner_version, environ):
    """Threads the scanner writes its windows with: v6 uses its write-thread knob
    (work_plan_v6, read from the environment the scanner inherits); v3, v4, v4.1, v5 and
    pt1 write on one thread (pt1 overlaps it with sieving, still one writer)."""
    if scanner_version == "v6":
        import work_plan_v6
        return work_plan_v6.write_threads_from_env(environ)
    return 1


def print_benchmark_summary(base_exponent, start_idx, end_idx, total_seconds, portal_folder,
                             l_final=None, sieving_primes_count=None, max_child_rss_mb=None,
                             write_files=True, total_primes_found=None, windows_processed=None,
                             window_m=None, base_gen_seconds=None, sieve_seconds=None,
                             write_seconds=None, bytes_written=None, numbers_processed=None,
                             workers=None, run_status=RUN_STATUS_COMPLETED,
                             verify_seconds=None, engine_counted=None,
                             sieve_wall_seconds=None):
    """Logs to the SAME benchmark_log.csv used by every orchestrator variant (see this file's
    header for why that's deliberately shared, not forked).

    window_m must match whatever WINDOW_M the actual scan used -- reading back a floor's
    PRIME_WINDOW_*.bin filenames (which encode ABSOLUTE offsets, not window_m itself)
    requires knowing the same window_m used to write them, to recompute each target_idx's
    expected filename below. Defaults to the module WINDOW_M when omitted, same as
    everywhere else in this file.

    The headers are read by `workers` threads (default WORKERS, the run's worker count):
    each read is one file open over WSL's /mnt drive, latency-bound, so the threads
    overlap the waits. With bytes_written None the sizes of the windows read are summed
    instead (a stopped run has no scanner handoff). A stopped run with no window found
    logs no row. verify_seconds is the D-proves-P time of the run (reconcile_batch()),
    part of total_seconds; it gets its own column so charts can tell it from the engine.
    engine_counted, (total primes, windows) reported by the scanners for the whole range,
    replaces the header pass of a written run (one file open per window).
    sieve_wall_seconds: the sieve timed from the scanner's launch (_run_teed()), logged
    next to the engine's own sieve_seconds."""
    window_m = WINDOW_M if window_m is None else window_m
    workers = WORKERS if workers is None else workers
    if write_files and engine_counted is not None:
        total_primes, windows_found = engine_counted
        print(f"[*] Prime count from the scanner's report ({windows_found:,} windows), "
              f"headers not re-read.")
    elif write_files:
        # Counts are re-derived from disk (the store each window was written into, see
        # storage_kinds.written_kind()) rather than taken from write_scan_metrics_handoff():
        # parallel instances share that file (orchestrator_loop_v2.py header).
        from pgs2_vector import read_window_count_and_size
        base = 10 ** base_exponent

        def _count(target_idx):
            offset = target_idx * window_m
            kind = storage_kinds.written_kind(SCANNER_VERSION, base + offset,
                                              base + offset + window_m)
            path = storage_kinds.window_path(portal_folder, base_exponent, offset, window_m,
                                             prime_sieve_module.format_offset(offset), kind)
            try:
                return read_window_count_and_size(path)
            except FileNotFoundError:
                return None

        print(f"[*] Counting the primes of the written windows ({end_idx - start_idx:,} "
              f"headers, {workers} threads)...")
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            found = [c for c in pool.map(_count, range(start_idx, end_idx)) if c is not None]
        total_primes = sum(count for count, _size in found)
        windows_found = len(found)
        if bytes_written is None:
            bytes_written = sum(size for _count, size in found)
        if run_status == RUN_STATUS_STOPPED and windows_found == 0:
            print("[*] No window was written before the stop -- nothing to log.")
            return
    else:
        total_primes = total_primes_found if total_primes_found is not None else 0
        windows_found = windows_processed if windows_processed is not None else (end_idx - start_idx)

    seconds_per_window = total_seconds / windows_found if windows_found else float("nan")
    primes_per_second = total_primes / total_seconds if total_seconds > 0 else float("nan")
    avg_primes_per_window = total_primes / windows_found if windows_found else float("nan")

    windows_label = "windows written" if write_files else "windows processed (NOT written)"
    print(f"\n{'='*60}")
    if not write_files:
        print(f"[BENCHMARK] (count-only mode -- totals from scanner handoff, not disk)")
    print(f"[BENCHMARK] 10^{base_exponent}, target_idx {start_idx}..{end_idx - 1} "
          f"({windows_found} {windows_label})")
    print(f"[BENCHMARK] total time: {format_duration(total_seconds)} "
          f"({format_per_window(seconds_per_window)})")
    print(f"[BENCHMARK] total primes found: {total_primes:,} "
          f"(avg {avg_primes_per_window:,.0f}/window, {primes_per_second:,.0f} primes/sec)")
    if sieving_primes_count is not None:
        print(f"[BENCHMARK] active sieving primes used: {sieving_primes_count:,} "
              f"(pi(L_final), L_final={l_final:,})")
    if max_child_rss_mb is not None:
        print(f"[BENCHMARK] peak child-process RAM: {max_child_rss_mb:,.0f} MB "
              f"(single largest worker, not the simultaneous total across all workers)")
    if sieve_seconds is not None or write_seconds is not None:
        # Only ever both-or-neither in practice (both come from the same v4.1 handoff), but
        # printed independently in case a future engine only measures one of the two.
        parts = []
        if base_gen_seconds is not None:
            parts.append(f"base-gen {base_gen_seconds:.2f}s")
        if sieve_seconds is not None:
            parts.append(f"sieve {sieve_seconds:.2f}s")
        if sieve_wall_seconds is not None:
            parts.append(f"sieve from launch {sieve_wall_seconds:.2f}s")
        if write_seconds is not None:
            parts.append(f"write {write_seconds:.2f}s")
            if bytes_written and write_seconds > 0:
                parts.append(f"({bytes_written / write_seconds / 1e6:.1f} MB/s)")
        if verify_seconds:
            parts.append(f"D proves P {verify_seconds:.2f}s")
        print(f"[BENCHMARK] phase breakdown: {' | '.join(parts)}")
    print(f"{'='*60}")

    log_path = os.path.join(portal_folder, "benchmark_log.csv")
    try:
        os.makedirs(portal_folder, exist_ok=True)
        ensure_benchmark_log_schema(log_path)
        is_new = not os.path.exists(log_path)
        with open(log_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=BENCHMARK_FIELDNAMES)
            if is_new:
                writer.writeheader()
            row = {
                "engine": SCANNER_VERSION,
                "engine_version": prime_sieve_module.VERSION,
                "threads": workers,
                "write_threads": scanner_write_threads(SCANNER_VERSION, os.environ),
                "numbers_processed": numbers_processed if numbers_processed is not None else "",
                "run_timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "base_exponent": base_exponent,
                "target_idx_start": start_idx,
                "target_idx_end": end_idx - 1,
                "windows_written": windows_found,
                "total_seconds": f"{total_seconds:.3f}",
                "seconds_per_window": f"{seconds_per_window:.6f}",
                "total_primes": total_primes,
                "avg_primes_per_window": f"{avg_primes_per_window:.1f}",
                "primes_per_second": f"{primes_per_second:.2f}",
                "l_final": l_final if l_final is not None else "",
                "sieving_primes_count": sieving_primes_count if sieving_primes_count is not None else "",
                "max_child_rss_mb": f"{max_child_rss_mb:.1f}" if max_child_rss_mb is not None else "",
                "write_files": "1" if write_files else "0",
                "base_gen_seconds": f"{base_gen_seconds:.3f}" if base_gen_seconds is not None else "",
                "sieve_seconds": f"{sieve_seconds:.3f}" if sieve_seconds is not None else "",
                "write_seconds": f"{write_seconds:.3f}" if write_seconds is not None else "",
                "bytes_written": bytes_written if bytes_written is not None else "",
                "run_status": run_status,
                "verify_seconds": f"{verify_seconds:.3f}" if verify_seconds is not None else "",
                "sieve_wall_seconds": (f"{sieve_wall_seconds:.3f}"
                                       if sieve_wall_seconds is not None else ""),
            }
            writer.writerow(row)
        print(f"[BENCHMARK] logged to {log_path} (for cross-floor growth analysis)")
        append_benchmark_row_to_floor_meta(portal_folder, base_exponent, row)
    except OSError as e:
        print(f"[BENCHMARK] WARNING: could not write benchmark log ({e})")


def run_orchestrator(base_exponent=None, window_count=None, start_auto=None, start_window=None,
                      write_files=None, batches_per_worker=None,
                      compute_sieving_primes_count=None, workers=None, window_m=None):
    """Returns True/False so __main__ can turn it into a real process exit code.

    workers/batches_per_worker/window_m are all CLI-overridable (see __main__ below) rather
    than fixed module constants, so a caller (e.g. the GUI's Generation tab) can set every
    tunable this pipeline has without touching source. They default to the module
    constants below when omitted (e.g. a direct `python orchestrator_v3.py <base_exponent>
    <window_count>` call).

    window_m is how many numbers each target_idx step covers -- threaded from the GUI's
    "Generation pipeline" field all the way down through here to the active scanner's (see
    SCANNER_VERSION near the top of this file) own CLI. CAUTION: changing this for a floor
    that already has PRIME_WINDOW_*.bin files written
    with a DIFFERENT window_m will make find_auto_start() below compute a wrong/misaligned
    resume point (it reverse-engineers target_idx from each file's stored absolute offset
    using THIS window_m) -- only safe to change for a floor with no existing data yet."""
    base_exponent = BASE_EXPONENT if base_exponent is None else base_exponent
    window_count = WINDOW_COUNT if window_count is None else window_count
    start_auto = START_WINDOW_AUTO if start_auto is None else start_auto
    start_window = START_WINDOW if start_window is None else start_window
    write_files = WRITE_FILES if write_files is None else write_files
    batches_per_worker = BATCHES_PER_WORKER if batches_per_worker is None else batches_per_worker
    workers = WORKERS if workers is None else workers
    compute_sieving_primes_count = (COMPUTE_SIEVING_PRIMES_COUNT
                                     if compute_sieving_primes_count is None
                                     else compute_sieving_primes_count)
    window_m = WINDOW_M if window_m is None else window_m
    batch_size = window_count

    script_dir = os.path.dirname(os.path.abspath(__file__))
    scanner_path = os.path.join(script_dir, SCRIPT_NAME)
    # CONSTELLATION_PORTAL_DIR: same override as the active scanner's (SCRIPT_NAME / see
    # SCANNER_VERSION near the top of this file) own BASE_STORAGE_10PN -- see that file's
    # __main__ block for the full rationale. Since this script's own subprocess (SCRIPT_NAME,
    # via run_batch() below) inherits this process's environment by default, setting this once
    # in the launching GUI process propagates all the way down through this script to the
    # scanner subprocess without needing to also thread it through as a CLI arg. Falls back
    # to a CONSTELLATION_PORTAL folder next to the
    # application root (one level up from this script) when the env var isn't set, matching
    # AppSettings.default_storage_path.
    env_override = os.environ.get("CONSTELLATION_PORTAL_DIR")
    portal_folder = (env_override if env_override else
                      os.path.abspath(os.path.join(
                          script_dir, "..", "CONSTELLATION_PORTAL")))

    print(f"{'='*60}")
    print(f"[*] ORCHESTRATOR {VERSION} (shared mmap buffer, atomic OR, via {SCRIPT_NAME}) | "
          f"START: 10^{base_exponent}")
    print(f"[*] {window_count} windows total, in batches of {batch_size}, "
          f"{workers} workers per batch"
          + ("" if write_files else " -- WRITE_FILES=False (count-only, no PGS2 files)")
          + ("" if compute_sieving_primes_count else " -- SIEVING_PRIMES_COUNT=False (skip pi(L_final))"))
    print(f"[*] TARGET: {scanner_path}")
    print(f"{'='*60}\n")

    if not os.path.exists(scanner_path):
        print(f"[-] ERROR: scanner not found at:\n    {scanner_path}")
        return False

    if start_auto and not write_files:
        print(f"[!] NOTE: auto mode + WRITE_FILES=False -- disk-based auto-resume can't see "
              f"progress from previous no-write runs (nothing was written for it to find). "
              f"It will still find real files left by any prior write-enabled runs.\n")

    if start_auto:
        found = find_auto_start(base_exponent, portal_folder, window_m)
        if found is not None:
            actual_start_window = found
            print(f"[*] auto mode: highest already-computed target_idx for "
                  f"10^{base_exponent} found on disk -- continuing from "
                  f"target_idx={actual_start_window}\n")
        else:
            actual_start_window = start_window
            print(f"[*] auto mode: nothing found for 10^{base_exponent} in "
                  f"{portal_folder} -- using fallback start_window={actual_start_window}\n")
    else:
        actual_start_window = start_window
        print(f"[*] manual mode: starting at target_idx={actual_start_window} (given explicitly)\n")

    t_start_orchestrator = time.perf_counter()
    clock_start = datetime.now().strftime('%H:%M:%S')

    end_at = actual_start_window + window_count
    current = actual_start_window
    interrupted = False
    stopped = False
    verify_seconds = 0.0
    engine_totals = [] if write_files else None
    sieve_walls = []
    batches_launched = 0
    while current < end_at:
        if generation_stop.stop_requested(portal_folder):
            # Stop requested before this batch's scanner existed for the GUI to kill.
            stopped = True
            break
        batch_stop = min(current + batch_size, end_at) - 1
        batches_launched += 1
        ok = run_batch(scanner_path, base_exponent, current, batch_stop, workers,
                        batches_per_worker=batches_per_worker, write_files=write_files,
                        compute_sieving_primes_count=compute_sieving_primes_count,
                        window_m=window_m, engine_totals=engine_totals,
                        sieve_walls=sieve_walls)
        if not ok and generation_stop.stop_requested(portal_folder):
            stopped = True
            if write_files:
                _delete_cut_windows(portal_folder, base_exponent, current, batch_stop,
                                    window_m, workers)
            current = batch_stop + 1
            break
        if not ok:
            interrupted = True
            break
        if write_files:
            t_verify = time.perf_counter()
            reconcile_batch(portal_folder, base_exponent, current, batch_stop, window_m, workers)
            verify_seconds += time.perf_counter() - t_verify
        current = batch_stop + 1

    t_end_orchestrator = time.perf_counter()
    total_seconds = t_end_orchestrator - t_start_orchestrator
    total_duration = format_duration(total_seconds)
    windows_done = current - actual_start_window
    seconds_per_window = total_seconds / windows_done if windows_done > 0 else float("nan")

    print(f"\n{'='*60}")
    if stopped:
        print(f"[!] STOPPED ON REQUEST. target_idx {actual_start_window}..{current - 1}: the "
              f"windows written before the stop are kept." if current > actual_start_window
              else "[!] STOPPED ON REQUEST before any batch started.")
        print(f"[!] Orchestrator run time: {total_duration} "
              f"({clock_start} -> {datetime.now().strftime('%H:%M:%S')})")
    elif interrupted:
        print(f"[!] STOPPED AFTER ERROR. target_idx {actual_start_window}..{current - 1} "
              f"({windows_done} windows completed before the error).")
        print(f"[!] Orchestrator run time: {total_duration} "
              f"({clock_start} -> {datetime.now().strftime('%H:%M:%S')}) "
              f"-- {format_per_window(seconds_per_window)}")
    else:
        print(f"[!] ALL JOBS DONE. target_idx {actual_start_window}..{end_at - 1} "
              f"({window_count} windows, {window_count * 10} million).")
        print(f"[!] Total orchestrator run time: {total_duration} "
              f"({clock_start} -> {datetime.now().strftime('%H:%M:%S')}) "
              f"-- {format_per_window(seconds_per_window)}")
    print(f"{'='*60}")

    if stopped:
        # The killed scanner wrote no handoff (one left on disk belongs to an earlier
        # run), so the row takes everything from the window headers.
        if write_files:
            print_benchmark_summary(base_exponent, actual_start_window, current,
                                    total_seconds, portal_folder,
                                    max_child_rss_mb=peak_child_rss_mb(),
                                    write_files=write_files, window_m=window_m,
                                    workers=workers, run_status=RUN_STATUS_STOPPED)
    elif current > actual_start_window:
        metrics = read_scan_metrics_handoff(portal_folder)
        l_final = metrics.get("l_final")
        sieving_primes_count = metrics.get("sieving_primes_count")
        total_primes_found = metrics.get("total_primes_found")
        windows_processed = metrics.get("windows_processed")
        # base_gen_seconds/sieve_seconds/write_seconds/bytes_written: only present in the
        # handoff when SCANNER_VERSION="v4.1" actually wrote them (see that file's own
        # write_scan_metrics_handoff() docstring) -- .get() with no default already yields
        # None for v3/v4 runs, which print_benchmark_summary()/the CSV row both already
        # treat as "not measured, leave blank" throughout.
        base_gen_seconds = metrics.get("base_gen_seconds")
        sieve_seconds = metrics.get("sieve_seconds")
        write_seconds = metrics.get("write_seconds")
        bytes_written = metrics.get("bytes_written")
        max_rss_mb = peak_child_rss_mb()
        # The scanners' own reports replace the header pass when every batch printed one
        # and their windows add up to the range.
        engine_counted = None
        if write_files and engine_totals and len(engine_totals) == batches_launched:
            counted = (sum(p for p, _w in engine_totals), sum(w for _p, w in engine_totals))
            if counted[1] == current - actual_start_window:
                engine_counted = counted
        # Launch-to-sieve-done of every batch, without the optional pi(L_final) diagnostic
        # (base_gen_seconds), which the scanner runs before sieving and which is no sieve work.
        sieve_wall_seconds = None
        if len(sieve_walls) == batches_launched:
            sieve_wall_seconds = sum(sieve_walls) - (base_gen_seconds or 0.0)
        print_benchmark_summary(base_exponent, actual_start_window, current,
                                 total_seconds, portal_folder,
                                 l_final=l_final, sieving_primes_count=sieving_primes_count,
                                 max_child_rss_mb=max_rss_mb, write_files=write_files,
                                 total_primes_found=total_primes_found,
                                 windows_processed=windows_processed, window_m=window_m,
                                 base_gen_seconds=base_gen_seconds, sieve_seconds=sieve_seconds,
                                 write_seconds=write_seconds, bytes_written=bytes_written,
                                 numbers_processed=metrics.get("numbers_processed"),
                                 workers=workers,
                                 verify_seconds=verify_seconds if write_files else None,
                                 engine_counted=engine_counted,
                                 sieve_wall_seconds=sieve_wall_seconds)

    return not interrupted


def _delete_cut_windows(portal_folder, base_exponent, target_idx_start, target_idx_stop,
                        window_m, workers):
    """Deletes the windows of a stopped batch that the scanner kill cut mid-write
    (window_integrity.repair_recent(), relative to the stop request's time)."""
    base = 10 ** base_exponent
    paths = []
    for target_idx in range(target_idx_start, target_idx_stop + 1):
        offset = target_idx * window_m
        kind = storage_kinds.written_kind(SCANNER_VERSION, base + offset, base + offset + window_m)
        paths.append(storage_kinds.window_path(portal_folder, base_exponent, offset, window_m,
                                               prime_sieve_module.format_offset(offset), kind))
    print(f"[*] Checking the windows written before the stop ({len(paths):,} headers)...")
    deleted = window_integrity.repair_recent(
        paths, reference_time=generation_stop.stop_request_time(portal_folder),
        workers=workers)
    for path in deleted:
        print(f"[!] Deleted the window cut by the stop: {os.path.basename(path)}")
    return deleted


if __name__ == "__main__":
    # The GUI tails stdout from a file; line buffering makes each stage visible when printed.
    sys.stdout.reconfigure(line_buffering=True)
    if len(sys.argv) > 2:
        cli_base_exponent = int(sys.argv[1])
        cli_window_count = int(sys.argv[2])
        cli_start_auto = _parse_bool_arg(sys.argv[3]) if len(sys.argv) > 3 else None
        cli_start_window = int(sys.argv[4]) if len(sys.argv) > 4 else None
        cli_write_files = _parse_bool_arg(sys.argv[5]) if len(sys.argv) > 5 else None
        cli_compute_sieving = _parse_bool_arg(sys.argv[6]) if len(sys.argv) > 6 else None
        cli_workers = int(sys.argv[7]) if len(sys.argv) > 7 else None
        cli_batches_per_worker = int(sys.argv[8]) if len(sys.argv) > 8 else None
        # window_m: position 9. NOT position 10 -- an optional instance_suffix that
        # orchestrator_loop_v2.py's build_instance_cmd() may append after this is not read
        # anywhere in this file's own __main__ regardless of what position it lands at, so
        # there's no collision to worry about here -- see build_instance_cmd()'s own
        # docstring in orchestrator_loop_v2.py for the full reasoning.
        cli_window_m = int(sys.argv[9]) if len(sys.argv) > 9 else None
        # WSL invocation: python orchestrator_v3.py <base_exponent> <window_count>
        #                 [<auto 0/1> [<start_window> [<write_files 0/1>
        #                 [<compute_sieving_primes_count 0/1> [<workers>
        #                 [<batches_per_worker> [<window_m>]]]]]]]
        ok = run_orchestrator(base_exponent=cli_base_exponent, window_count=cli_window_count,
                               start_auto=cli_start_auto, start_window=cli_start_window,
                               write_files=cli_write_files,
                               compute_sieving_primes_count=cli_compute_sieving,
                               workers=cli_workers, batches_per_worker=cli_batches_per_worker,
                               window_m=cli_window_m)
    else:
        ok = run_orchestrator()
    sys.exit(0 if ok else 1)
