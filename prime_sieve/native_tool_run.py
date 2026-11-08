"""
native_tool_run.py -- the shared part of running an external prime program natively
(primesieve_native.py, pseudosquares_native.py): the timed child process, the prime count of
a printed text file, the child's peak RAM, and the one benchmark_log.csv row of the run.

A native run writes no Atlas windows and is always a benchmark (run_purpose), print
included: its text is the program's own format, not Atlas storage. Its mode decides what its
one wall time means:
- count: the program sieves the range and reports the number of primes, writing nothing --
  the work of an Atlas engine's sieve phase -- so the wall time is total and sieve time
  (sieve_seconds); one process timed from outside has no startup/sieve split, so
  sieve_wall_seconds stays blank.
- print: the program sieves and prints every prime as its own text, one per line, into a
  file -- a whole run with no sieve/output split -- so the wall time is total and loop time
  (loop_session_seconds, loop_numbers_per_second), and the row names its text bytes and its
  one printing thread.
"""
import csv
import datetime
import os
import signal
import subprocess
import time

from benchmark_log_schema import (BENCHMARK_FIELDNAMES, RUN_PURPOSE_BENCHMARK,
                                  ensure_benchmark_log_schema)

MODES = ("print", "count")


def benchmark_row(mode, engine, base_exponent, target_idx_start, target_idx_count, lo, hi,
                  wall_seconds, primes, threads, version, bytes_written, max_rss_mb,
                  write_threads=""):
    """The log row of one native run over [lo, hi): `engine` tag, the program's `version`,
    the `threads` it ran on; print rows also name `write_threads` (the printing thread)."""
    row = {name: "" for name in BENCHMARK_FIELDNAMES}
    row.update({
        "run_timestamp_utc": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"),
        "base_exponent": base_exponent,
        "target_idx_start": target_idx_start,
        "target_idx_end": target_idx_start + target_idx_count - 1,
        "windows_written": 0,
        "total_seconds": f"{wall_seconds:.3f}",
        "total_primes": primes,
        "primes_per_second": f"{primes / wall_seconds:.2f}" if wall_seconds > 0 else "",
        "max_child_rss_mb": "" if max_rss_mb is None else f"{max_rss_mb:.1f}",
        "write_files": "1" if mode == "print" else "0",
        "run_purpose": RUN_PURPOSE_BENCHMARK,
        "bytes_written": "" if bytes_written is None else bytes_written,
        "engine": engine,
        "engine_version": version,
        "threads": str(threads),
        "write_threads": str(write_threads) if mode == "print" else "",
        "numbers_processed": hi - lo,
        "run_status": "completed",
    })
    if mode == "count":
        row["sieve_seconds"] = f"{wall_seconds:.3f}"
    else:
        row["loop_session_seconds"] = f"{wall_seconds:.3f}"
        row["loop_numbers_per_second"] = (f"{(hi - lo) / wall_seconds:.2f}"
                                          if wall_seconds > 0 else "")
    return row


def append_row(portal_folder, row):
    log_path = os.path.join(portal_folder, "benchmark_log.csv")
    os.makedirs(portal_folder, exist_ok=True)
    if not ensure_benchmark_log_schema(log_path):
        print(f"[BENCHMARK] WARNING: {log_path} has a column this version does not know; "
              f"row not written")
        return
    is_new = not os.path.exists(log_path)
    with open(log_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BENCHMARK_FIELDNAMES)
        if is_new:
            writer.writeheader()
        writer.writerow(row)
    print(f"[BENCHMARK] logged to {log_path}")


def count_lines(path):
    lines = 0
    with open(path, "rb") as f:
        while chunk := f.read(1 << 24):
            lines += chunk.count(b"\n")
    return lines


def child_rss_mb():
    import resource  # Linux only; the pure part of the native runners also runs on Windows
    return resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024


def run_timed(cmd, out_path=None):
    """Runs `cmd` to its exit: stdout into `out_path` when given, else captured.
    Returns (returncode, wall seconds, captured stdout bytes or None). SIGTERM to this
    process ends the child too (the app's Stop)."""
    stdout = open(out_path, "wb") if out_path else subprocess.PIPE
    try:
        t0 = time.perf_counter()
        proc = subprocess.Popen(cmd, stdout=stdout, stderr=subprocess.STDOUT)
        previous = signal.signal(signal.SIGTERM, lambda *_: proc.terminate())
        out, _ = proc.communicate()
        wall = time.perf_counter() - t0
        signal.signal(signal.SIGTERM, previous)
    finally:
        if out_path:
            stdout.close()
    return proc.returncode, wall, out
