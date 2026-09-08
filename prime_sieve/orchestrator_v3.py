import subprocess
import sys
import os
import re
import csv
import json
import time
from datetime import datetime, timezone

try:
    import resource  # POSIX-only (WSL/Linux) -- used for peak child-process RAM tracking.
except ImportError:
    resource = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import window_sharding

# ------------------------------------------------------------------------------------------
# ENGINE SWITCH -- change ONLY this one flag to flip which scanner generation (v3, v4, or
# v4.1) this orchestrator drives. Previously this meant editing SCRIPT_NAME (below) AND the
# `import prime_sieve_v3` line above it separately -- easy to change one and forget the
# other, which is exactly what happened testing v4 (SCRIPT_NAME pointed at
# prime_sieve_v4.py, but the module import -- used for format_offset()/
# read_prime_window_header()/SCAN_METRICS_FILENAME in the benchmark-summary code further
# down -- was still silently reading v3's copies of those, harmless in practice since v4
# duplicates them byte-for-byte identically, but not an honest "actually switched" state).
# v3/v4/v4.1 all write files in the SAME PGS2 format/filename convention and share the same
# benchmark_log.csv, so flipping this is safe at any time, including mid-floor.
# v4 = v3 plus an inlined fast-path modulo in the C core for the per-sieving-prime phase
# computation (see prime_sieve_v4.py's own header) -- should be faster or equal, never
# slower, so there's rarely a reason to run v3 except for an A/B comparison like this one.
# v4.1 = v4 plus direct base-gen/sieve/write timing and a bytes-written counter, threaded
# through into four NEW benchmark_log.csv columns (base_gen_seconds/sieve_seconds/
# write_seconds/bytes_written, see BENCHMARK_FIELDNAMES below) -- no change to the sieve
# itself, purely additive instrumentation (see prime_sieve_v4_1.py's own header). Not yet
# run against real libprimesieve as of this flag's addition -- the timing/handoff logic
# has no libprimesieve dependency and was exercised with synthetic data instead, but a
# real WSL run is still needed before trusting the actual timing numbers it reports.
SCANNER_VERSION = "v4.1"   # "v3", "v4", or "v4.1"

if SCANNER_VERSION == "v3":
    import prime_sieve_v3 as prime_sieve_module  # noqa: E402
    SCRIPT_NAME = "prime_sieve_v3.py"
elif SCANNER_VERSION == "v4":
    import prime_sieve_v4 as prime_sieve_module  # noqa: E402
    SCRIPT_NAME = "prime_sieve_v4.py"
elif SCANNER_VERSION == "v4.1":
    import prime_sieve_v4_1 as prime_sieve_module  # noqa: E402
    SCRIPT_NAME = "prime_sieve_v4_1.py"
else:
    raise ValueError(f"SCANNER_VERSION must be 'v3', 'v4', or 'v4.1', got {SCANNER_VERSION!r}")
# format_offset() and read_prime_window_header() (PGS2 fast header peek) are reused here
# for the benchmark summary, instead of duplicating them -- see prime_sieve_module's own
# usages below.


# ==========================================================================================
# orchestrator_v3.py
#
# LINEAGE: orchestrator_v2.py (this folder), with ONE change: SCRIPT_NAME points at
# prime_sieve_v3.py instead of prime_sieve_v2.py, and the module import follows suit. Kept
# as a SEPARATE file (not a git commit to orchestrator_v2.py) for the same explicit reason
# prime_sieve_v3.py is a separate file -- see that file's header. orchestrator_v1.py and
# orchestrator_v2.py are untouched and still fully usable against their respective scanners.
#
# Nothing about batching/sequencing/benchmarking logic changed here -- this file's whole job
# is launching a scanner subprocess and logging what it did, and that job is identical
# regardless of which scanner (v2's per-worker-private-buffer return+merge, or v3's shared
# mmap buffer with atomic OR, no merge step) is doing the actual sieving. All three write to
# the SAME CONSTELLATION_PORTAL/benchmark_log.csv -- deliberately not forked, so the existing
# growth chart keeps showing one continuous cross-floor history.
# ==========================================================================================


def _parse_bool_arg(value):
    """Unchanged from orchestrator_v2.py -- see that file's docstring."""
    v = value.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"expected 0/1 (or true/false, yes/no, on/off) for auto mode, got: {value!r}")


def format_duration(seconds):
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def find_auto_start(base_exponent, portal_folder, window_m):
    """Unchanged from orchestrator_v2.py -- see that file's docstring. The on-disk PGS2
    window format/filename convention is unchanged by v3 (only how the sieve gets there
    internally changed).

    source_primes/ is sharded into shard_NNNNN subfolders (see window_sharding.py, task
    #405) -- a bare os.listdir(source_dir) would only ever see those subfolder names,
    never match this function's own filename pattern, silently breaking auto-continue.
    window_sharding.list_sharded_files() walks each shard subfolder instead."""
    pattern = re.compile(rf"^PRIME_WINDOW_10p{base_exponent}_off_(\d+)(M)?\.bin$")
    highest_target_idx = None

    source_dir = os.path.join(portal_folder, f"10p{base_exponent}", "source_primes")
    for name, _path in window_sharding.list_sharded_files(source_dir):
        m = pattern.match(name)
        if not m:
            continue
        number = int(m.group(1))
        offset = number * 1_000_000 if m.group(2) else number
        target_idx = offset // window_m
        if highest_target_idx is None or target_idx > highest_target_idx:
            highest_target_idx = target_idx

    if highest_target_idx is None:
        return None
    return highest_target_idx + 1


# ==============================================================================
# JOB CONFIGURATION -- same defaults/meaning as orchestrator_v1.py/v2.py's block.
# ==============================================================================
VERSION = "v3.1"   # see prime_sieve_v3.py's VERSION comment -- same reasoning/bump here.
BASE_EXPONENT = 17
START_WINDOW_AUTO = True
START_WINDOW = 0
WINDOW_COUNT = 200
BATCH_SIZE = WINDOW_COUNT
WORKERS = 24
# SCRIPT_NAME is set by the ENGINE SWITCH block near the top of this file (SCANNER_VERSION),
# NOT here -- this used to be the one line that differed from orchestrator_v2.py, but having
# it set a second time in this JOB CONFIGURATION block too (while the scanner MODULE import
# was a separate, easy-to-forget line elsewhere) is exactly what caused a v3/v4 switch to be
# only half-applied. Left unset here on purpose so accidentally reintroducing a second
# assignment is more likely to be noticed.
WINDOW_M = 10 ** 7
BATCHES_PER_WORKER = 2
WRITE_FILES = True
# count_sieving_primes(L_final) toggle -- see prime_sieve_v3.py's COMPUTE_SIEVING_PRIMES_COUNT
# comment for the full rationale (554s real cost at extreme depth, pure diagnostic stat).
# Default OFF, passed through to the scanner subprocess as CLI position 7.
COMPUTE_SIEVING_PRIMES_COUNT = False
# ==============================================================================


def run_batch(scanner_path, base_exponent, target_idx_start, target_idx_stop, workers,
              batches_per_worker, write_files, compute_sieving_primes_count, window_m):
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
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"[-] ERROR: batch {target_idx_start}..{target_idx_stop} exited with code "
              f"{result.returncode} -- stopping.")
        return False
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Batch {target_idx_start}..{target_idx_stop} "
          f"DONE.")
    return True


BENCHMARK_FIELDNAMES = [
    "run_timestamp_utc", "base_exponent", "target_idx_start", "target_idx_end",
    "windows_written", "total_seconds", "seconds_per_window", "total_primes",
    "avg_primes_per_window", "primes_per_second", "l_final", "sieving_primes_count",
    "max_child_rss_mb", "instance_of_n", "loop_session_seconds", "loop_numbers_per_second",
    "loop_seconds_per_window", "write_files", "base_gen_seconds", "sieve_seconds",
    "write_seconds", "bytes_written", "engine", "numbers_processed",
]
# write_files: lets the GUI's floor list show total REAL generation time per floor, which
# requires distinguishing actual disk-writing runs from write_files=False count-only
# benchmark runs (the same base_exponent/range can get run both ways). "1"/"0", same
# convention as this file's own CLI encoding of the flag (see run_batch()). Rows written
# before this column existed have it blank -- _ensure_benchmark_log_schema() leaves old rows
# blank rather than guessing.
#
# base_gen_seconds/sieve_seconds/write_seconds/bytes_written: ONLY populated by
# prime_sieve_v4_1.py (SCANNER_VERSION="v4.1") -- see that file's own header for what each
# phase covers. Blank for every row logged by v3/v4 (they never measured a write-phase timer
# at all, and only ever PRINTED base_gen/sieve time rather than handing it back here) -- same
# "leave old/unmeasured rows blank rather than guessing" rule _ensure_benchmark_log_schema()
# already applies to write_files. Together these four are what let the Benchmark tab draw a
# sieve-speed/write-speed breakdown instead of just one combined total_seconds figure.


def _ensure_benchmark_log_schema(log_path):
    """Same schema-migration logic as orchestrator_v1.py/v2.py -- see orchestrator_v1.py's
    docstring. Rewrite is ATOMIC (temp file + os.replace())."""
    if not os.path.exists(log_path):
        return
    with open(log_path, newline="") as f:
        reader = csv.DictReader(f)
        existing_fields = reader.fieldnames or []
        rows = list(reader)
    if existing_fields == BENCHMARK_FIELDNAMES:
        return
    if not all(field in BENCHMARK_FIELDNAMES for field in existing_fields):
        return
    tmp_path = f"{log_path}.tmp{os.getpid()}"
    with open(tmp_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BENCHMARK_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in BENCHMARK_FIELDNAMES})
    os.replace(tmp_path, log_path)


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
    """Unchanged from orchestrator_v1.py/v2.py."""
    if resource is None:
        return None
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    return ru.ru_maxrss / 1024


def _append_floor_meta_row(portal_folder, base_exponent, row):
    """Small self-contained duplicate of primeatlas/floor_meta.py's
    append_benchmark_row_to_floor_meta() -- deliberately NOT imported from there: this
    engine runs standalone (possibly under WSL, a different sys.path than the Windows-side
    GUI package), same reasoning every other cross-folder duplication in this project
    already follows (see e.g. _ensure_benchmark_log_schema()'s own docstring). Writes
    10p{base_exponent}/floor_meta.json so this floor's generation history travels with its
    own directory if it's ever copied into a different storage (magazyn) -- see
    floor_meta.py's module docstring for the full rationale. Best-effort/non-fatal: any
    failure here must never break benchmark logging itself, which already succeeded by the
    time this is called."""
    key_fields = ("run_timestamp_utc", "base_exponent", "target_idx_start", "target_idx_end")

    def _key(r):
        return tuple(str(r.get(k, "")) for k in key_fields)

    floor_dir = os.path.join(portal_folder, f"10p{base_exponent}")
    path = os.path.join(floor_dir, "floor_meta.json")
    try:
        rows = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                rows = list(data.get("benchmark_rows", []))
        if _key(row) in {_key(r) for r in rows}:
            return
        rows.append(dict(row))
        os.makedirs(floor_dir, exist_ok=True)
        tmp_path = f"{path}.tmp{os.getpid()}"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"base_exponent": base_exponent, "benchmark_rows": rows}, f,
                      indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        pass


def print_benchmark_summary(base_exponent, start_idx, end_idx, total_seconds, portal_folder,
                             l_final=None, sieving_primes_count=None, max_child_rss_mb=None,
                             write_files=True, total_primes_found=None, windows_processed=None,
                             window_m=None, base_gen_seconds=None, sieve_seconds=None,
                             write_seconds=None, bytes_written=None, numbers_processed=None):
    """Logs to the SAME benchmark_log.csv used by every orchestrator variant (see this file's
    header for why that's deliberately shared, not forked).

    window_m must match whatever WINDOW_M the actual scan used -- reading back a floor's
    PRIME_WINDOW_*.bin filenames (which encode ABSOLUTE offsets, not window_m itself)
    requires knowing the same window_m used to write them, to recompute each target_idx's
    expected filename below. Defaults to the module WINDOW_M when omitted, same as
    everywhere else in this file."""
    window_m = WINDOW_M if window_m is None else window_m
    if write_files:
        total_primes = 0
        windows_found = 0

        # Sharded (see window_sharding.py, task #405): a window at this offset now lives
        # under source_dir/shard_NNNNN/, not directly in source_dir -- this loop used to
        # os.path.exists() a flat source_dir path for every window, which is ALWAYS False
        # post-sharding, silently zeroing out total_primes/windows_found (and therefore
        # this run's whole benchmark_log.csv row) even though the files were written
        # correctly. Missed in the original task #405 sweep because this function re-derives
        # counts from disk instead of trusting write_scan_metrics_handoff()'s numbers --
        # caught 2026-08-27 from a real generation run on 10^13 reporting "0 windows
        # written" despite prime_sieve_v4_1.py's own console output showing 1000 windows/
        # 334M primes written correctly.
        source_dir = os.path.join(portal_folder, f"10p{base_exponent}", "source_primes")
        for target_idx in range(start_idx, end_idx):
            offset = target_idx * window_m
            tag = f"10p{base_exponent}_off_{prime_sieve_module.format_offset(offset)}"
            window_index = window_sharding.shard_index_for_offset(offset, window_m)
            shard_folder = window_sharding.shard_dir(source_dir, window_index)
            path = os.path.join(shard_folder, f"PRIME_WINDOW_{tag}.bin")
            if not os.path.exists(path):
                continue
            header = prime_sieve_module.read_prime_window_header(path)
            total_primes += header["count"]
            windows_found += 1
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
          f"({seconds_per_window:.3f} s/window)")
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
        if write_seconds is not None:
            parts.append(f"write {write_seconds:.2f}s")
            if bytes_written and write_seconds > 0:
                parts.append(f"({bytes_written / write_seconds / 1e6:.1f} MB/s)")
        print(f"[BENCHMARK] phase breakdown: {' | '.join(parts)}")
    print(f"{'='*60}")

    log_path = os.path.join(portal_folder, "benchmark_log.csv")
    try:
        os.makedirs(portal_folder, exist_ok=True)
        _ensure_benchmark_log_schema(log_path)
        is_new = not os.path.exists(log_path)
        with open(log_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=BENCHMARK_FIELDNAMES)
            if is_new:
                writer.writeheader()
            row = {
                "engine": SCANNER_VERSION,
                "numbers_processed": numbers_processed if numbers_processed is not None else "",
                "run_timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "base_exponent": base_exponent,
                "target_idx_start": start_idx,
                "target_idx_end": end_idx - 1,
                "windows_written": windows_found,
                "total_seconds": f"{total_seconds:.3f}",
                "seconds_per_window": f"{seconds_per_window:.4f}",
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
            }
            writer.writerow(row)
        print(f"[BENCHMARK] logged to {log_path} (for cross-floor growth analysis)")
        _append_floor_meta_row(portal_folder, base_exponent, row)
    except OSError as e:
        print(f"[BENCHMARK] WARNING: could not write benchmark log ({e})")


def run_orchestrator(base_exponent=None, window_count=None, start_auto=None, start_window=None,
                      write_files=None, batches_per_worker=None,
                      compute_sieving_primes_count=None, workers=None, window_m=None):
    """Returns True/False so __main__ can turn it into a real process exit code.

    workers/batches_per_worker/window_m are all CLI-overridable (see __main__ below) rather
    than fixed module constants, so a caller (e.g. the GUI's Generation tab) can set every
    tunable this pipeline has without touching source. They still default to the module
    constants below when omitted, so direct `python orchestrator_v3.py <base_exponent>
    <window_count>` calls keep working exactly as before.

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
    while current < end_at:
        batch_stop = min(current + batch_size, end_at) - 1
        ok = run_batch(scanner_path, base_exponent, current, batch_stop, workers,
                        batches_per_worker=batches_per_worker, write_files=write_files,
                        compute_sieving_primes_count=compute_sieving_primes_count,
                        window_m=window_m)
        if not ok:
            interrupted = True
            break
        current = batch_stop + 1

    t_end_orchestrator = time.perf_counter()
    total_seconds = t_end_orchestrator - t_start_orchestrator
    total_duration = format_duration(total_seconds)
    windows_done = current - actual_start_window
    seconds_per_window = total_seconds / windows_done if windows_done > 0 else float("nan")

    print(f"\n{'='*60}")
    if interrupted:
        print(f"[!] STOPPED AFTER ERROR. target_idx {actual_start_window}..{current - 1} "
              f"({windows_done} windows completed before the error).")
        print(f"[!] Orchestrator run time: {total_duration} "
              f"({clock_start} -> {datetime.now().strftime('%H:%M:%S')}) "
              f"-- {seconds_per_window:.2f} s/window")
    else:
        print(f"[!] ALL JOBS DONE. target_idx {actual_start_window}..{end_at - 1} "
              f"({window_count} windows, {window_count * 10} million).")
        print(f"[!] Total orchestrator run time: {total_duration} "
              f"({clock_start} -> {datetime.now().strftime('%H:%M:%S')}) "
              f"-- {seconds_per_window:.2f} s/window")
    print(f"{'='*60}")

    if current > actual_start_window:
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
        print_benchmark_summary(base_exponent, actual_start_window, current,
                                 total_seconds, portal_folder,
                                 l_final=l_final, sieving_primes_count=sieving_primes_count,
                                 max_child_rss_mb=max_rss_mb, write_files=write_files,
                                 total_primes_found=total_primes_found,
                                 windows_processed=windows_processed, window_m=window_m,
                                 base_gen_seconds=base_gen_seconds, sieve_seconds=sieve_seconds,
                                 write_seconds=write_seconds, bytes_written=bytes_written,
                                 numbers_processed=metrics.get("numbers_processed"))

    return not interrupted


if __name__ == "__main__":
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
