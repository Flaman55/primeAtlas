"""
test_primesieve_native.py -- primesieve mode's native path runs the primesieve program
itself, so its benchmark row is primesieve's own speed with no Atlas code in the timed part.

A. Pure: the range of (floor, start, count, window_m) with the uint64 clamp; the argv of
   both modes (count: --count --time, print: --print); the text file path of a print run;
   parsing primesieve's --time report and --version; the log row of each mode: engine tag,
   program version, threads as reported, no Atlas windows. count (sieve + bit count, what
   the sieve phase of an Atlas engine does) has the wall time as total and sieve time, no
   loop_* columns, no write threads; print (sieve + prime output, a whole run) has the wall
   time as total and loop time, numbers/s in loop_numbers_per_second, no sieve time (no
   split), 1 thread and 1 write thread, the text file's bytes.
B. The log header gains `threads`; the row writer keeps old rows and appends one row.
C. (WSL only, primesieve program installed) a count run and a print run over two windows
   of floor 10: the count equals the number of lines the print run wrote, the print file
   is primesieve's own text output, and the rows carry what A expects.

Usage:
    python unitTests/test_primesieve_native.py      (A, B; C runs only under WSL)
"""
import csv
import os
import shutil
import subprocess
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []
W = 10_000_000

COUNT_REPORT = """Sieve size = 256 KiB
Threads = 15
0%1%2%50%99%100%
Seconds: 2.952
Primes: 2285680140
"""


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def part_a():
    import benchmark_log_schema as schema
    import primesieve_native as nat

    check(nat.native_range(10, 0, 2, W) == (10 ** 10, 10 ** 10 + 2 * W),
          "range: floor start plus start/count windows, hi exclusive")
    lo, hi = nat.native_range(19, 0, 10 ** 12, W)
    check(hi == 2 ** 64, "range: clamped to primesieve's uint64 stop (hi exclusive)")
    check(nat.argv("count", 100, 200) == ["primesieve", "100", "199", "--count", "--time"],
          "count argv: inclusive stop, --count --time")
    check(nat.argv("print", 100, 200) == ["primesieve", "100", "199", "--print"],
          "print argv: inclusive stop, --print only (nothing else in the output)")
    path = nat.print_path("/p", 10, 10 ** 10, 10 ** 10 + W)
    check(path.replace("\\", "/") == f"/p/primesieve/10p10/{10 ** 10}_{10 ** 10 + W - 1}.txt",
          "print file: portal/primesieve/10pNN/<start>_<stop>.txt")
    report = nat.parse_count_report(COUNT_REPORT)
    check(report == {"threads": 15, "seconds": 2.952, "primes": 2285680140},
          "count report: threads, seconds and primes as primesieve printed them")
    check(nat.parse_version("primesieve 12.15, <https://github.com/kimwalisch/primesieve>\n")
          == "12.15", "version: the program's own number")
    check(nat.PRINT_THREADS == 1, "print runs on one thread")

    row = nat.benchmark_row("count", 19, 5, 1000, W, wall_seconds=3.0, primes=228568014,
                            threads=15, version="12.15", bytes_written=None, max_rss_mb=40.0)
    check(row["engine"] == schema.ENGINE_PRIMESIEVE_COUNT == "primesieve_count",
          "count row: engine primesieve_count")
    check(row["engine_version"] == "12.15" and row["threads"] == "15",
          "count row: program version and the threads primesieve reported")
    check(row["numbers_processed"] == 1000 * W and row["target_idx_start"] == 5
          and row["target_idx_end"] == 1004, "count row: range columns")
    check(row["total_seconds"] == row["sieve_seconds"] == "3.000",
          "count row: wall time is total and sieve time")
    check(row["sieve_wall_seconds"] == "",
          "count row: no sieve-with-startup time (one process, no split to measure)")
    check(row["run_purpose"] == "benchmark", "count row: a benchmark run (writes nothing)")
    check(row["windows_written"] == 0 and row["write_files"] == "0"
          and row["write_seconds"] == "" and row["bytes_written"] == "",
          "count row: no windows, nothing written")
    check(all(row[c] == "" for c in ("loop_session_seconds", "loop_numbers_per_second",
                                     "loop_seconds_per_window", "seconds_per_window")),
          "count row: no loop/window speed columns")
    check(row["write_threads"] == "", "count row: no write threads (nothing written)")
    check(set(row) <= set(schema.BENCHMARK_FIELDNAMES), "count row: only log columns")

    row = nat.benchmark_row("print", 19, 0, 10, W, wall_seconds=1.2, primes=2285000,
                            threads=1, version="12.15", bytes_written=48000000,
                            max_rss_mb=None)
    check(row["engine"] == schema.ENGINE_PRIMESIEVE_PRINT == "primesieve_print",
          "print row: engine primesieve_print")
    check(row["threads"] == "1" and row["write_files"] == "1"
          and row["bytes_written"] == 48000000 and row["windows_written"] == 0,
          "print row: one thread, the text file's bytes, no Atlas windows")
    check(row["max_child_rss_mb"] == "", "print row: unknown RSS stays blank")
    check(row["write_threads"] == "1", "print row: written by the same single thread")
    check(row["run_purpose"] == "storage", "print row: a storage run (its text into the storage)")
    check(row["total_seconds"] == row["loop_session_seconds"] == "1.200"
          and row["sieve_seconds"] == row["sieve_wall_seconds"] == "",
          "print row: wall time is total and loop time, no sieve/write split")
    check(row["loop_numbers_per_second"] == f"{10 * W / 1.2:.2f}",
          "print row: whole-run numbers/s")


def part_b():
    import benchmark_log_schema as schema
    import primesieve_native as nat

    check(schema.BENCHMARK_FIELDNAMES[-4:] == ["threads", "write_threads",
                                               "sieve_wall_seconds", "run_purpose"],
          "log header ends with threads, write_threads, sieve_wall_seconds, run_purpose")
    check(schema.THREADS_GPU == "GPU", "GPU engines log threads as GPU")
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "benchmark_log.csv")
        old = schema.BENCHMARK_FIELDNAMES[:-1]
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=old)
            w.writeheader()
            w.writerow({c: "" for c in old} | {"engine": "v6", "base_exponent": "19"})
        nat.append_row(tmp, nat.benchmark_row("count", 19, 0, 1, W, wall_seconds=0.7,
                                              primes=228609, threads=1, version="12.15",
                                              bytes_written=None, max_rss_mb=None))
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        check(len(rows) == 2 and rows[0]["engine"] == "v6" and rows[0]["threads"] == "",
              "append: old row kept, its threads blank")
        check(rows[1]["engine"] == "primesieve_count" and rows[1]["threads"] == "1",
              "append: native row written with threads")
    finally:
        shutil.rmtree(tmp)


def part_c():
    if os.name == "nt" or shutil.which("primesieve") is None:
        print("SKIPPED (WSL-only, primesieve program): part C")
        return
    import primesieve_native as nat

    tmp = tempfile.mkdtemp()
    try:
        count_row = nat.run("count", 10, 0, 2, W, tmp)
        print_row = nat.run("print", 10, 0, 2, W, tmp)
        text = nat.print_path(tmp, 10, 10 ** 10, 10 ** 10 + 2 * W)
        with open(text, "rb") as f:
            lines = f.read().split()
        check(count_row["total_primes"] == len(lines) == print_row["total_primes"],
              "WSL: count equals the primes the print run wrote")
        check(int(lines[0]) == 10000000019, "WSL: first prime of floor 10 in the text file")
        expected = subprocess.run(["primesieve", str(10 ** 10), str(10 ** 10 + 2 * W - 1),
                                   "--print"], capture_output=True).stdout
        with open(text, "rb") as f:
            check(f.read() == expected, "WSL: the file is primesieve's own --print output")
        check(print_row["bytes_written"] == os.path.getsize(text),
              "WSL: bytes_written is the file size")
        check(count_row["threads"].isdigit() and int(count_row["threads"]) >= 1,
              "WSL: count row has the reported thread count")
        with open(os.path.join(tmp, "benchmark_log.csv"), newline="") as f:
            engines = [r["engine"] for r in csv.DictReader(f)]
        check(engines == ["primesieve_count", "primesieve_print"], "WSL: both rows logged")
        check(not os.path.exists(os.path.join(tmp, "10p10")),
              "WSL: nothing written into Atlas storage")
    finally:
        shutil.rmtree(tmp)


def main():
    part_a()
    part_b()
    part_c()
    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
