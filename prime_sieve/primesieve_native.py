"""
primesieve_native.py -- primesieve mode, native: runs the primesieve program itself.

The timed part is the primesieve process alone, from its start to its exit, so the logged
speed is primesieve's own; nothing of Atlas runs inside it.
- count: `primesieve <start> <stop> --count --time` -- sieves the range (segmented sieve of
  Eratosthenes) on the threads primesieve picks for it and counts the unmarked bits;
  writes nothing. That is the work of an Atlas engine's sieve phase (a bitmap of the range,
  no primes extracted), so the row has the wall time as sieve time and goes on the sieve
  charts.
- print: `primesieve <start> <stop> --print` into portal/primesieve/10p<N>/<start>_<stop>.txt
  -- sieves and prints every prime as primesieve's own text, one per line, NOT the Atlas
  storage format (no window files, nothing for Atlas to read). That is a whole run (sieve +
  output) with no split between the two, so the row has the wall time as loop time
  (loop_numbers_per_second) and goes on the whole-run chart. primesieve prints on one
  thread (PRINT_THREADS). The primes are counted from the file after the clock stops.
Both log one benchmark_log.csv row (engine ENGINE_PRIMESIEVE_COUNT / ENGINE_PRIMESIEVE_PRINT,
engine_version = the program's version, threads, write_threads). primesieve's own --time
figure is printed for comparison. Stop: SIGTERM ends the primesieve child too.

ATTRIBUTION: primesieve is an independent open-source program by Kim Walisch (BSD license),
https://github.com/kimwalisch/primesieve -- installed separately, not part of this project.

Run inside WSL:
    python3 primesieve_native.py <base_exponent> <target_idx_start> <target_idx_count>
                                 <window_m> <print|count>
"""
import os
import re
import subprocess
import sys

import native_tool_run
from benchmark_log_schema import ENGINE_PRIMESIEVE_COUNT, ENGINE_PRIMESIEVE_PRINT

MODES = native_tool_run.MODES
ENGINES = {"print": ENGINE_PRIMESIEVE_PRINT, "count": ENGINE_PRIMESIEVE_COUNT}
PRINT_THREADS = 1
PRIMESIEVE = "primesieve"
MAX_STOP = 2 ** 64 - 1  # primesieve's largest stop (inclusive)


def native_range(base_exponent, target_idx_start, target_idx_count, window_m):
    """[lo, hi) of the request, hi clamped to MAX_STOP + 1."""
    lo = 10 ** base_exponent + target_idx_start * window_m
    return lo, min(lo + target_idx_count * window_m, MAX_STOP + 1)


def argv(mode, lo, hi):
    """primesieve's command line for [lo, hi); its stop is inclusive."""
    tail = ["--count", "--time"] if mode == "count" else ["--print"]
    return [PRIMESIEVE, str(lo), str(hi - 1)] + tail


def print_path(portal_folder, base_exponent, lo, hi):
    return os.path.join(portal_folder, "primesieve", f"10p{base_exponent}", f"{lo}_{hi - 1}.txt")


def parse_count_report(text):
    """{threads, seconds, primes} from primesieve's --count --time output."""
    def grab(pattern, cast):
        m = re.search(pattern, text, re.M)
        return cast(m.group(1)) if m else None
    return {"threads": grab(r"^Threads = (\d+)", int),
            "seconds": grab(r"^Seconds: ([\d.]+)", float),
            "primes": grab(r"^Primes: (\d+)", int)}


def parse_version(text):
    m = re.search(r"primesieve (\d+(?:\.\d+)*)", text)
    return m.group(1) if m else ""


def benchmark_row(mode, base_exponent, target_idx_start, target_idx_count, window_m,
                  wall_seconds, primes, threads, version, bytes_written, max_rss_mb):
    """The log row of one native run (native_tool_run.benchmark_row): count has the wall
    time as sieve time, print as loop time, written by the printing thread."""
    lo, hi = native_range(base_exponent, target_idx_start, target_idx_count, window_m)
    return native_tool_run.benchmark_row(
        mode, ENGINES[mode], base_exponent, target_idx_start, target_idx_count, lo, hi,
        wall_seconds, primes, threads, version, bytes_written, max_rss_mb,
        write_threads=PRINT_THREADS)


def run(mode, base_exponent, target_idx_start, target_idx_count, window_m, portal_folder):
    """One native run; logs and returns its row."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    lo, hi = native_range(base_exponent, target_idx_start, target_idx_count, window_m)
    if hi <= lo:
        raise ValueError("empty range")
    version = parse_version(subprocess.run([PRIMESIEVE, "--version"], capture_output=True,
                                           text=True).stdout)
    cmd = argv(mode, lo, hi)
    print(f"[*] primesieve {version} (native, github.com/kimwalisch/primesieve, BSD): "
          f"{' '.join(cmd)}")
    print(f"[*] Range: [{lo:,}, {hi:,})  size={hi - lo:,}")
    out_path = None
    if mode == "print":
        out_path = print_path(portal_folder, base_exponent, lo, hi)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        print(f"[*] Text output (primesieve format, not Atlas storage): {out_path}")
    returncode, wall, out = native_tool_run.run_timed(cmd, out_path)
    if returncode != 0:
        print(f"[!] primesieve exited with code {returncode}; no row logged")
        sys.exit(returncode or 1)
    if mode == "count":
        report = parse_count_report(out.decode("ascii", "replace"))
        primes, threads, bytes_written = report["primes"], report["threads"], None
        print(f"[*] primesieve's own time: {report['seconds']} s, threads: {threads}")
    else:
        primes, threads = native_tool_run.count_lines(out_path), PRINT_THREADS
        bytes_written = os.path.getsize(out_path)
        print(f"[*] {bytes_written:,} bytes of text, threads: {threads} (--print)")
    print(f"[BENCHMARK] {primes:,} primes, wall {wall:.3f} s, "
          f"{(hi - lo) / wall / 1e6:,.1f} M numbers/s")
    row = benchmark_row(mode, base_exponent, target_idx_start, target_idx_count, window_m,
                        wall, primes, threads, version, bytes_written,
                        native_tool_run.child_rss_mb())
    native_tool_run.append_row(portal_folder, row)
    return row


if __name__ == "__main__":
    if len(sys.argv) != 6 or sys.argv[5] not in MODES:
        sys.exit(__doc__)
    portal = os.environ.get("CONSTELLATION_PORTAL_DIR") or "/mnt/c/CONSTELLATION_PORTAL"
    run(sys.argv[5], int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]),
        portal)
