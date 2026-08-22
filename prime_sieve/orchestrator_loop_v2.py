import subprocess
import sys
import os
import csv
import time
from datetime import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
# This app copy imports the small, dependency-free orchestrator_loop_helpers.py extraction
# (find_auto_start()/WINDOW_M/_parse_bool_arg()/_ensure_benchmark_log_schema()) rather than a
# full orchestrator module, so this self-contained copy doesn't need to carry unused scanning/
# CLI logic or its ctypes sieve-engine dependency just to reach four small helper functions.
import orchestrator_loop_helpers as orch  # noqa: E402  -- doesn't run anything on import.

# ==========================================================================================
# orchestrator_loop_v2.py -- parallel-instance loop runner for orchestrator_v3.py.
#
# Instead of running ONE orchestrator instance per loop iteration (sequentially, each
# covering WINDOW_COUNT_PER_RUN windows via auto-resume), this splits EACH iteration's
# windows across N_INSTANCES separate orchestrator subprocesses, launched CONCURRENTLY
# (via subprocess.Popen, not a blocking subprocess.run), each covering a contiguous,
# non-overlapping slice of roughly WINDOW_COUNT_PER_RUN/N_INSTANCES windows.
#
# These are genuinely separate OS processes, unlike the scanner's own internal batch/worker
# split (many batches sharing ONE ProcessPoolExecutor per scanner invocation): each instance
# spins up its own WORKERS-sized worker pool, so e.g. N_INSTANCES=2 with a target
# orchestrator WORKERS=24 means 48 worker processes contending for the same CPU/memory
# bandwidth at once, potentially well past the physical core count. Whether narrower-but-
# more-numerous instances net win or lose against one wide instance (memory-bandwidth
# contention under real many-way parallelism is the leading factor) is what this file exists
# to let you measure. Each instance logs its OWN row to benchmark_log.csv (same as any other
# orchestrator run), so results land in the same growth-tracking dataset as everything else.
#
# Ranges are assigned MANUALLY (auto=0 on every instance), not via find_auto_start() per
# instance -- one piece of code (this file) decides the full split up front, so instances
# never have to negotiate/detect each other's progress from disk (which would race between
# concurrently-running instances, and wouldn't work reliably in write_files=False/count-only
# mode, since nothing is written to disk to detect). The starting point for the WHOLE
# session (iteration 1, instance 1) still comes from find_auto_start() once, up front --
# every iteration after that continues from an in-memory cursor (the target_idx right after
# the previous iteration's LAST instance), not a fresh disk scan, so progress chains
# correctly across iterations even when write_files=False leaves nothing on disk to detect.
#
# HANDOFF-FILE CAVEAT: each orchestrator instance's scanner subprocess hands back
# l_final/sieving_primes_count/total_primes_found via a small JSON handoff file at a fixed,
# shared path (last_scan_metrics.json), written non-atomically. With n_instances=1 that's
# harmless (one writer, ever). With n_instances>1 it's a genuine race: concurrently-running
# instances can stomp on each other's handoff file, so an orchestrator may read back a
# SIBLING instance's numbers instead of its own. build_instance_cmd() below generates a
# per-instance-unique suffix and passes it as an optional trailing CLI argument for an
# orchestrator that implements per-instance handoff filenames; orchestrator_v3.py (the
# current ORCHESTRATOR_PATH target) does not read that argument, so this mitigation is only
# active against an orchestrator variant that consumes it.
#
# Usage (WSL):
#   python3 orchestrator_loop_v2.py <base_exponent> <run_count> <n_instances>
#       [<write_files 0/1> [<compute_sieving_primes_count 0/1> [<window_count_per_run>
#       [<workers> [<batches_per_worker>]]]]]
#
#   base_exponent -- which floor (10^N) to run against, e.g. 20
#   run_count     -- how many loop ITERATIONS to run. Each iteration launches n_instances
#                    orchestrators CONCURRENTLY, together covering window_count_per_run
#                    windows -- so run_count=10 with the default window_count_per_run=1000
#                    sweeps 10*1000 = 10000 windows total, same total as
#                    `orchestrator_loop_v1.py <base_exponent> 10`, just each 1000-window
#                    slice gets internally parallelized across n_instances concurrent
#                    orchestrators instead of run sequentially by one.
#   n_instances   -- how many orchestrator subprocesses to launch CONCURRENTLY per
#                    iteration. n_instances=2 means each iteration's window_count_per_run
#                    windows get split into 2 contiguous halves (e.g. 500 -> 250 + 250),
#                    launched at the same time as two separate OS processes.
#   write_files   -- optional, default 1 (write PGS2 files as normal). Pass 0 for count-only
#                    benchmarking.
#   compute_sieving_primes_count -- optional, default 0. See prime_sieve_v3.py's
#                    COMPUTE_SIEVING_PRIMES_COUNT comment (pi(L_final), a diagnostic stat).
#   window_count_per_run -- optional, default WINDOW_COUNT_PER_RUN (1000).
#   workers       -- optional, default WORKERS (24). Worker processes per orchestrator
#                    instance.
#   batches_per_worker -- optional, default BATCHES_PER_WORKER (2).
#
# Example:
#   python3 orchestrator_loop_v2.py 20 10 2 0
#   -> floor 20, 10 iterations, 2 concurrent instances/iteration (250 windows each),
#      count-only (no PGS2 files written).
# ==========================================================================================

# ==============================================================================
# Defaults for CLI positions 6-8 (see build_instance_cmd()'s docstring): how many windows
# each loop ITERATION covers IN TOTAL split across N_INSTANCES concurrent orchestrator
# subprocesses (see split_windows()), and the workers/batches_per_worker every instance's
# orchestrator_v3.py subprocess gets launched with. All three are CLI-overridable; these are
# just the fallback values when the CLI position is omitted.
WINDOW_COUNT_PER_RUN = 1000
WORKERS = 24
BATCHES_PER_WORKER = 2
# ==============================================================================

VERSION = "v3.1"   # see prime_sieve_v3.py's VERSION comment -- same convention here (an
                    # at-a-glance iteration marker for this file).

# count_sieving_primes(L_final) toggle, passed through to each instance's orchestrator CLI --
# see prime_sieve_v3.py's COMPUTE_SIEVING_PRIMES_COUNT comment for the full rationale (a pure
# diagnostic stat that can take minutes at extreme depth; default OFF).
COMPUTE_SIEVING_PRIMES_COUNT = False

ORCHESTRATOR_PATH = os.path.join(_SCRIPT_DIR, "orchestrator_v3.py")
# CONSTELLATION_PORTAL_DIR: the GUI's Settings tab lets the user point the whole portal at a
# different disk/folder -- see prime_sieve_v3.py's __main__ block for the full rationale.
# This process's own subprocesses (orchestrator_v3.py instances, spawned below) inherit this
# environment automatically, so setting it here once is enough to propagate all the way down
# the chain to prime_sieve_v3.py too. Falls back to a CONSTELLATION_PORTAL folder next to the
# application root (one level up from this script) when the env var isn't set, matching
# AppSettings.default_storage_path.
PORTAL_FOLDER = os.environ.get("CONSTELLATION_PORTAL_DIR") or os.path.abspath(
    os.path.join(_SCRIPT_DIR, "..", "CONSTELLATION_PORTAL"))
BENCHMARK_LOG_FILENAME = "benchmark_log.csv"


def highest_written_target_idx(base_exponent, window_m=None):
    """Ground truth from disk: the highest PRIME_WINDOW_*.bin target_idx currently written
    for this floor, or None if nothing's been written yet. Used ONCE, up front, to find the
    session's starting point; every iteration after that chains from an in-memory cursor
    instead (see this file's header).

    window_m defaults to orch.WINDOW_M when omitted, same as everywhere else in this file --
    see main()'s own window_m CLI position for the full rationale."""
    window_m = orch.WINDOW_M if window_m is None else window_m
    next_idx = orch.find_auto_start(base_exponent, PORTAL_FOLDER, window_m)
    return None if next_idx is None else next_idx - 1


def _count_benchmark_rows(portal_folder):
    """Row count of benchmark_log.csv right now (0 if the file doesn't exist yet) -- the
    baseline _sum_new_benchmark_primes() diffs against. Same mechanism as
    orchestrator_loop_v1.py's write-toggle grand-total feature -- see that file for the full
    rationale (each orchestrator instance appends exactly one row, write_files-agnostic)."""
    path = os.path.join(portal_folder, BENCHMARK_LOG_FILENAME)
    if not os.path.exists(path):
        return 0
    with open(path, newline="", encoding="utf-8") as f:
        return sum(1 for _ in csv.DictReader(f))


def _sum_new_benchmark_primes(portal_folder, rows_before):
    """Sums the total_primes column across every benchmark_log.csv row appended SINCE
    rows_before was captured -- i.e. every row this session's instances produced (one row
    per instance, not per iteration -- N_INSTANCES concurrent orchestrators each log their
    own row). Returns (total_primes_sum, new_row_count)."""
    path = os.path.join(portal_folder, BENCHMARK_LOG_FILENAME)
    if not os.path.exists(path):
        return 0, 0
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    new_rows = rows[rows_before:]
    total = 0
    for row in new_rows:
        try:
            total += int(row.get("total_primes", 0) or 0)
        except ValueError:
            continue
    return total, len(new_rows)


def _tag_benchmark_rows_by_range(portal_folder, rows_before, instance_ranges, loop_total_seconds,
                                  window_m=None):
    """Patches the new benchmark_log.csv rows THIS iteration's concurrent instances just
    appended with instance_of_n="<rank>/<n_instances>" and loop_session_seconds -- the REAL
    wall-clock time for the whole iteration (all instances ran concurrently via Popen), unlike
    each row's own total_seconds column which only covers that ONE instance's own slice of
    the range. Averaging per-instance seconds_per_window into a growth chart would make
    splitting into more concurrent instances look like a regression even when wall-clock
    throughput across the whole session actually improves, since each instance's own
    total_seconds only reflects its own (smaller) slice. Downstream (e.g. the portal's
    Benchmark tab) can group rows sharing the same loop_session_seconds + denominator and sum
    their windows_written to get a true numbers/second figure.

    Rows are matched to their instance rank by (target_idx_start, target_idx_end), NOT by
    append order -- concurrently-running instances finish and write their own row in whatever
    order the OS scheduler lets them, not necessarily instance-index order. instance_ranges
    is the (start_idx, window_count) list this iteration assigned, in RANK order (index 0 =
    rank 1, etc.) -- exactly what build_instance_cmd() launched each instance with, so the
    target_idx_start/target_idx_end reconstructed here are guaranteed to match what that
    instance's own orchestrator logged.

    Requires the instance_of_n column to already exist in the CSV header -- a no-op against
    an older schema, or if no new rows matched any of instance_ranges (fails safe: leaves
    those rows' instance_of_n blank rather than mislabeling).

    Also stamps loop_numbers_per_second = sum(window_count for instance_ranges) * WINDOW_M /
    loop_total_seconds on every matched row -- the "numbers of the axis swept per real second"
    figure for the whole concurrent group, computed ONCE here from instance_ranges (already
    known exactly, no need to re-read windows_written back from the CSV) rather than left for
    downstream chart code to re-derive every time. Returns that value (None if it couldn't be
    computed, e.g. loop_total_seconds<=0) so the caller can also print it.

    Also stamps loop_seconds_per_window = WINDOW_M / loop_numbers_per_second -- a "fair"
    seconds-per-window figure for the group, derived directly from
    total_windows/loop_total_seconds rather than averaged from individual rows -- exact even
    if instances didn't split the window count perfectly evenly (equal-cost partitioning
    usually gets close but not guaranteed identical), where a mean-then-divide approach over
    individual rows would drift slightly."""
    path = os.path.join(portal_folder, BENCHMARK_LOG_FILENAME)
    if not os.path.exists(path):
        return None
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    if not fieldnames or "instance_of_n" not in fieldnames or len(rows) <= rows_before:
        return None
    window_m = orch.WINDOW_M if window_m is None else window_m
    n = len(instance_ranges)
    total_windows = sum(window_count for _, window_count in instance_ranges)
    numbers_per_second = (total_windows * window_m / loop_total_seconds
                           if loop_total_seconds > 0 else None)
    seconds_per_window_fair = (window_m / numbers_per_second
                                if numbers_per_second else None)
    label_by_range = {}
    for rank, (start_idx, window_count) in enumerate(instance_ranges, start=1):
        end_idx = start_idx + window_count - 1
        label_by_range[(str(start_idx), str(end_idx))] = f"{rank}/{n}"
    changed = False
    for row in rows[rows_before:]:
        key = (row.get("target_idx_start"), row.get("target_idx_end"))
        label = label_by_range.get(key)
        if label is not None:
            row["instance_of_n"] = label
            row["loop_session_seconds"] = f"{loop_total_seconds:.3f}"
            if numbers_per_second is not None:
                row["loop_numbers_per_second"] = f"{numbers_per_second:.2f}"
            if seconds_per_window_fair is not None:
                row["loop_seconds_per_window"] = f"{seconds_per_window_fair:.4f}"
            changed = True
    if not changed:
        return None
    tmp_path = f"{path}.tmp{os.getpid()}"
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp_path, path)  # atomic -- see orchestrator_v1.py's
                                 # _ensure_benchmark_log_schema() docstring for why this
                                 # matters for a file holding the whole benchmark history
    return numbers_per_second


def split_windows(total_windows, n_instances):
    """Splits `total_windows` into `n_instances` contiguous, non-overlapping, as-equal-as-
    possible chunk SIZES (a list of ints summing exactly to total_windows). Earlier chunks
    get the +1 extra when it doesn't divide evenly (e.g. 500/3 -> [167, 167, 166], not
    [166, 166, 168] -- which end gets the remainder doesn't matter, this just picks one
    consistent rule so the split is deterministic/reproducible). A chunk size can be 0 if
    n_instances > total_windows -- callers should skip those rather than launch a pointless
    subprocess for an empty range (see run_iteration())."""
    n = max(1, n_instances)
    base, remainder = divmod(max(0, total_windows), n)
    return [base + 1 if i < remainder else base for i in range(n)]


def build_instance_cmd(orchestrator_path, base_exponent, start_idx, window_count, write_files,
                        compute_sieving_primes_count=False, workers=WORKERS,
                        batches_per_worker=BATCHES_PER_WORKER, window_m=None,
                        instance_suffix=None):
    """Builds the CLI invocation for ONE orchestrator instance covering EXACTLY
    [start_idx, start_idx + window_count) -- auto=0 (manual mode) always, since this file
    decides the whole split itself (see this file's header for why auto-resume-per-instance
    would be wrong here). Positional order must match orchestrator_v3.py's __main__ CLI:
    <base_exponent> <window_count> <auto 0/1> <start_window> <write_files 0/1>
    <compute_sieving_primes_count 0/1> <workers> <batches_per_worker> <window_m> -- a 9-arg
    signature (see orchestrator_v3.py's run_orchestrator() docstring for how each of these
    became CLI-overridable rather than a hardcoded module constant).

    compute_sieving_primes_count/workers/batches_per_worker/window_m are ALWAYS appended
    explicitly (never omitted) so they occupy fixed positions 6/7/8/9 -- leaving any of them
    optional/skippable would shift instance_suffix (below) into the wrong slot.

    instance_suffix (handoff-file race mitigation, see this file's header): appended as an
    OPTIONAL 10th positional arg, understood only by an orchestrator variant that routes the
    scan-metrics handoff through a per-instance-unique file. orchestrator_v3.py (the current
    ORCHESTRATOR_PATH target) does not read a 10th arg at all, so appending one here is
    harmless/ignored (Python's argv doesn't error on unused trailing elements) but not
    actually wired up for it -- the mitigation only takes effect against an orchestrator that
    implements it."""
    window_m = orch.WINDOW_M if window_m is None else window_m
    cmd = [
        sys.executable, orchestrator_path,
        str(base_exponent), str(window_count), "0", str(start_idx),
        "1" if write_files else "0",
        "1" if compute_sieving_primes_count else "0",
        str(workers), str(batches_per_worker), str(window_m),
    ]
    if instance_suffix is not None:
        cmd.append(str(instance_suffix))
    return cmd


def run_iteration(base_exponent, start_idx, n_instances, write_files, iteration_label,
                   iteration_number, compute_sieving_primes_count=False,
                   window_count_per_run=WINDOW_COUNT_PER_RUN, workers=WORKERS,
                   batches_per_worker=BATCHES_PER_WORKER, window_m=None):
    """Launches n_instances orchestrator subprocesses CONCURRENTLY (all started via Popen
    BEFORE any of them is waited on -- that's what makes them actually run at the same time,
    not one-after-another), each covering a contiguous slice of WINDOW_COUNT_PER_RUN windows,
    starting right after the previous instance's slice ends. Blocks until every instance in
    this iteration has finished. Returns (next_start_idx, all_ok, instance_ranges) --
    next_start_idx is the target_idx right after this iteration's LAST instance (where the
    next iteration, or the final summary, should continue from); all_ok is False if any
    instance exited non-zero; instance_ranges is the (start_idx, window_count) list in RANK
    order, handed back so the caller can tag this iteration's new benchmark_log.csv rows
    with the correct instance_of_n label (see _tag_benchmark_rows_by_range()) -- this
    function doesn't do that tagging itself since it doesn't know its own total elapsed time
    (timed by the caller, in main(), not in here).

    iteration_number feeds each instance's unique handoff-file suffix (concurrent-instance
    fix, see this file's header) -- combined with the instance's own index within the
    iteration, e.g. "i3n2" (iteration 3, instance 2), so every concurrently-running process
    across the WHOLE session gets a filesystem-unique last_scan_metrics_<suffix>.json, not
    just unique within one iteration (harmless overkill once iterations no longer overlap,
    but free and makes stray leftover files self-explanatory if you ever go looking)."""
    chunk_sizes = [s for s in split_windows(window_count_per_run, n_instances) if s > 0]
    instance_ranges = []
    cursor = start_idx
    for size in chunk_sizes:
        instance_ranges.append((cursor, size))
        cursor += size

    print(f"\n[LOOP] {iteration_label}: launching {len(instance_ranges)} instance(s) "
          f"concurrently -- target_idx {start_idx}..{cursor - 1} "
          f"({cursor - start_idx} windows total)"
          + ("" if write_files else " -- WRITE_FILES=False (count-only)"))

    procs = []
    for idx, (inst_start, size) in enumerate(instance_ranges, start=1):
        instance_suffix = f"i{iteration_number}n{idx}"
        cmd = build_instance_cmd(ORCHESTRATOR_PATH, base_exponent, inst_start, size,
                                  write_files,
                                  compute_sieving_primes_count=compute_sieving_primes_count,
                                  workers=workers, batches_per_worker=batches_per_worker,
                                  window_m=window_m, instance_suffix=instance_suffix)
        print(f"[LOOP]   instance {idx}/{len(instance_ranges)}: target_idx "
              f"{inst_start}..{inst_start + size - 1} ({size} windows)")
        # No capture_output -- every instance's (and, underneath it, its scanner's) progress
        # prints stream straight to this terminal live, same as orchestrator_loop_v1.py.
        # With multiple instances running at once, their output WILL interleave -- that's
        # expected, not a bug: these are genuinely separate, concurrently-running processes.
        procs.append(subprocess.Popen(cmd))

    all_ok = True
    for idx, p in enumerate(procs, start=1):
        rc = p.wait()
        if rc != 0:
            all_ok = False
            print(f"[LOOP]   instance {idx}/{len(instance_ranges)} exited with code {rc}")

    return cursor, all_ok, instance_ranges


def print_session_summary(base_exponent, session_start_idx, final_idx, run_count,
                           n_instances, total_primes_sum, benchmark_rows_counted,
                           write_files, window_count_per_run=WINDOW_COUNT_PER_RUN,
                           window_m=None):
    window_m = orch.WINDOW_M if window_m is None else window_m
    print(f"\n{'='*70}")
    label = f"10^{base_exponent}"
    print(f"[LOOP] Session summary ({label}):")
    print(f"[LOOP]   target_idx {session_start_idx:,}..{final_idx - 1:,} "
          f"({final_idx - session_start_idx:,} windows swept, "
          f"{(final_idx - session_start_idx) * window_m:,} numbers)")
    print(f"[LOOP]   ({run_count} iteration(s) x up to {n_instances} concurrent instance(s), "
          f"{window_count_per_run} windows/iteration)")
    if total_primes_sum is not None:
        print(f"[LOOP]   TOTAL PRIMES FOUND across {benchmark_rows_counted} instance-run(s) "
              f"this session: {total_primes_sum:,} (summed from benchmark_log.csv, "
              f"write_files-agnostic)")
    if not write_files:
        print(f"[LOOP]   WRITE_FILES=False -- no PGS2 files written this session.")
    print(f"{'='*70}")


def main():
    if (len(sys.argv) not in (4, 5, 6, 7, 8, 9, 10) or not sys.argv[1].isdigit()
            or not sys.argv[2].isdigit() or not sys.argv[3].isdigit()
            or int(sys.argv[2]) < 1 or int(sys.argv[3]) < 1):
        print(f"Usage: python3 {os.path.basename(__file__)} <base_exponent> <run_count> "
              f"<n_instances> [<write_files 0/1> [<compute_sieving_primes_count 0/1> "
              f"[<window_count_per_run> [<workers> [<batches_per_worker> [<window_m>]]]]]]")
        print("  base_exponent -- which floor (10^N) to run against, e.g. 20")
        print("  run_count     -- how many loop ITERATIONS to run (each launching")
        print(f"                   n_instances orchestrators concurrently, together covering")
        print(f"                   window_count_per_run windows)")
        print("  n_instances   -- how many orchestrator subprocesses to launch CONCURRENTLY")
        print("                   per iteration -- each covers roughly")
        print("                   window_count_per_run/n_instances windows")
        print("  write_files   -- optional, default 1. Pass 0 for count-only benchmarking.")
        print("  compute_sieving_primes_count -- optional, default 0 (matches prime_sieve_v3")
        print("                   .py's default). Pass 1 to compute pi(L_final) exactly --")
        print("                   can take minutes at extreme depth, pure diagnostic stat.")
        print(f"  window_count_per_run -- optional, default {WINDOW_COUNT_PER_RUN}. How many")
        print("                   windows each loop iteration covers in total, split across")
        print("                   n_instances.")
        print(f"  workers       -- optional, default {WORKERS}. Worker processes per")
        print("                   orchestrator instance (see orchestrator_v3.py's")
        print("                   run_orchestrator() docstring).")
        print(f"  batches_per_worker -- optional, default {BATCHES_PER_WORKER}. Equal-cost")
        print("                   batches per worker (same meaning as prime_sieve_v3.py's")
        print("                   own CLI position 5).")
        print(f"  window_m      -- optional, default {orch.WINDOW_M:,}. How many numbers each")
        print("                   target_idx step covers (see prime_sieve_v3.py's __main__")
        print("                   block). CAUTION: only safe to change for a floor with NO")
        print("                   existing PRIME_WINDOW_*.bin files yet -- changing it for a")
        print("                   floor that already has data written with a DIFFERENT")
        print("                   window_m breaks auto-resume.")
        sys.exit(1)

    base_exponent = int(sys.argv[1])
    run_count = int(sys.argv[2])
    n_instances = int(sys.argv[3])
    write_files = orch._parse_bool_arg(sys.argv[4]) if len(sys.argv) > 4 else True
    compute_sieving_primes_count = (orch._parse_bool_arg(sys.argv[5]) if len(sys.argv) > 5
                                     else COMPUTE_SIEVING_PRIMES_COUNT)
    window_count_per_run = int(sys.argv[6]) if len(sys.argv) > 6 else WINDOW_COUNT_PER_RUN
    workers = int(sys.argv[7]) if len(sys.argv) > 7 else WORKERS
    batches_per_worker = int(sys.argv[8]) if len(sys.argv) > 8 else BATCHES_PER_WORKER
    window_m = int(sys.argv[9]) if len(sys.argv) > 9 else orch.WINDOW_M

    if not os.path.exists(ORCHESTRATOR_PATH):
        print(f"[-] ERROR: orchestrator not found at:\n    {ORCHESTRATOR_PATH}")
        sys.exit(1)

    if not write_files:
        print(f"[!] NOTE: WRITE_FILES=False -- auto-resume (used ONCE below, for this "
              f"session's very first instance) can't see progress from previous no-write "
              f"sessions. It will still find real files left by any prior write-enabled "
              f"runs. Progress WITHIN this session chains correctly regardless (in-memory "
              f"cursor, not disk detection) -- see this file's header.\n")

    found = orch.find_auto_start(base_exponent, PORTAL_FOLDER, window_m)
    start_idx = found if found is not None else 0
    if found is not None:
        print(f"[LOOP] auto-detected start: target_idx={start_idx} "
              f"(highest already-computed window for 10^{base_exponent}, found on disk, + 1)")
    else:
        print(f"[LOOP] nothing found on disk for 10^{base_exponent} -- starting at "
              f"target_idx=0")
    session_start_idx = start_idx

    benchmark_rows_before = _count_benchmark_rows(PORTAL_FOLDER)

    # One-time schema migration up front (not per-instance): with n_instances>1, several
    # orchestrator subprocesses could otherwise each try to migrate benchmark_log.csv's
    # header to the new instance_of_n/loop_session_seconds schema at the same time, the very
    # first time this runs after those columns were added. After this call, every instance's
    # own (per-invocation) _ensure_benchmark_log_schema() check is a cheap no-op (header
    # already current) -- avoids that narrow race entirely rather than just tolerating it.
    orch._ensure_benchmark_log_schema(os.path.join(PORTAL_FOLDER, BENCHMARK_LOG_FILENAME))

    print("=" * 70)
    print(f"[LOOP] orchestrator_loop_v2 {VERSION} (parallel instances): {run_count} "
          f"iteration(s), {n_instances} instance(s)/iteration, {window_count_per_run} "
          f"windows/iteration, {workers} workers x {batches_per_worker} batches/worker "
          f"per instance, window_m={window_m:,}"
          + ("" if write_files else " -- WRITE_FILES=False (count-only)")
          + ("" if compute_sieving_primes_count else " -- SIEVING_PRIMES_COUNT=False"))
    print(f"[LOOP] target orchestrator: {ORCHESTRATOR_PATH}")
    print("=" * 70)

    t_loop_start = time.time()
    interrupted = False
    for i in range(1, run_count + 1):
        rows_before_this_iteration = _count_benchmark_rows(PORTAL_FOLDER)
        t0 = time.time()
        next_start, ok, instance_ranges = run_iteration(
            base_exponent, start_idx, n_instances, write_files,
            f"iteration {i}/{run_count}", iteration_number=i,
            compute_sieving_primes_count=compute_sieving_primes_count,
            window_count_per_run=window_count_per_run, workers=workers,
            batches_per_worker=batches_per_worker, window_m=window_m)
        elapsed = time.time() - t0
        numbers_per_second = _tag_benchmark_rows_by_range(
            PORTAL_FOLDER, rows_before_this_iteration, instance_ranges, elapsed,
            window_m=window_m)
        throughput_note = (f" -- {numbers_per_second:,.0f} numbers/sec (real wall-clock)"
                            if numbers_per_second is not None else "")
        print(f"[LOOP] iteration {i}/{run_count} finished in {elapsed:.1f}s "
              f"(target_idx now at {next_start}){throughput_note}")
        start_idx = next_start
        if not ok:
            print(f"[LOOP] at least one instance failed in iteration {i}/{run_count} -- "
                  f"stopping the loop early.")
            interrupted = True
            break

    total_elapsed = time.time() - t_loop_start
    print(f"\n[LOOP] {'Stopped early' if interrupted else 'All iterations complete'} "
          f"in {total_elapsed:.1f}s total.")

    total_primes_sum, new_row_count = _sum_new_benchmark_primes(
        PORTAL_FOLDER, benchmark_rows_before)
    print_session_summary(base_exponent, session_start_idx, start_idx, run_count,
                           n_instances, total_primes_sum, new_row_count, write_files,
                           window_count_per_run=window_count_per_run, window_m=window_m)

    sys.exit(1 if interrupted else 0)


if __name__ == "__main__":
    main()
