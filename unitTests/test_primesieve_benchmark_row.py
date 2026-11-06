"""
test_primesieve_benchmark_row.py -- primesieve mode's benchmark_log.csv row carries what the
Benchmark charts and the time model read, so the mode compares live with the other engines.

A. write_benchmark_row() with the phase times: numbers_processed, sieve_seconds,
   write_seconds, bytes_written and the loop_* speed columns are filled; total_seconds is
   the wall time of both phases; the Benchmark tab's sieve-speed and write-speed functions
   and time_model.read_samples() each take the row.
B. Count-only run (write_files off): write_seconds 0, bytes_written 0, still a sieve point.
C. (WSL only) generate_floor_windows() over two windows of floor 10 writes such a row with
   bytes_written equal to the files' size on disk.

Usage:
    python unitTests/test_primesieve_benchmark_row.py      (A, B; C runs only under WSL)
"""
import csv
import glob
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "constellation"))

failures = []
W = 10_000_000


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _rows(portal):
    with open(os.path.join(portal, "benchmark_log.csv"), newline="") as f:
        return list(csv.DictReader(f))


def _test_row_columns():
    print("\n--- A/B. write_benchmark_row() fills the chart columns ---")
    import prime_sieve_primesieve as ps
    from primeatlas.benchmark import benchmark
    from primeatlas.generation import time_model

    portal = tempfile.mkdtemp(prefix="ps_bench_row_")
    try:
        ps.write_benchmark_row(20, 0, 3, 1.5, 9000, 3, True, portal,
                               sieve_seconds=1.0, write_seconds=0.5,
                               bytes_written=123456, numbers_processed=3 * W,
                               max_rss_mb=512.25)
        row = _rows(portal)[0]
        check(row["numbers_processed"] == str(3 * W), "numbers_processed is the range size")
        check(float(row["sieve_seconds"]) == 1.0 and float(row["write_seconds"]) == 0.5,
              "sieve and write phases logged")
        check(row["bytes_written"] == "123456", "bytes_written logged")
        check(row["max_child_rss_mb"] == "512.2" or row["max_child_rss_mb"] == "512.3",
              f"peak RSS logged as max_child_rss_mb ({row['max_child_rss_mb']})")
        check(float(row["total_seconds"]) == 1.5, "total_seconds is the wall time of both phases")
        check(abs(float(row["loop_numbers_per_second"]) - 3 * W / 1.5) < 1,
              "loop_numbers_per_second = numbers / total time")
        check(abs(float(row["loop_seconds_per_window"]) - 0.5) < 1e-9,
              "loop_seconds_per_window = total time / windows")
        check(benchmark._row_sieve_nps(row) == 3 * W / 1.0, "the sieve-speed chart takes the row")
        check(abs(benchmark._row_write_mbps(row) - 123456 / 0.5 / 1e6) < 1e-9,
              "the write-speed chart takes the row")
        samples = time_model.read_samples(os.path.join(portal, "benchmark_log.csv"))
        check(len(samples) == 1 and samples[0].engine == "primesieve",
              "time_model reads the row as a primesieve sample")

        ps.write_benchmark_row(20, 3, 2, 0.8, 6000, 2, False, portal,
                               sieve_seconds=0.8, write_seconds=0.0,
                               bytes_written=0, numbers_processed=2 * W)
        row = _rows(portal)[1]
        check(row["write_files"] == "0" and float(row["write_seconds"]) == 0.0
              and row["bytes_written"] == "0", "count-only run logs no writing")
        check(benchmark._row_sieve_nps(row) == 2 * W / 0.8, "count-only run is still a sieve point")
    finally:
        shutil.rmtree(portal, ignore_errors=True)


def _test_generate_in_wsl():
    print("\n--- C. generate_floor_windows() row (WSL) ---")
    if not sys.platform.startswith("linux"):
        print("SKIPPED (WSL-only)")
        return
    import prime_sieve_primesieve as ps
    portal = tempfile.mkdtemp(prefix="ps_bench_gen_")
    try:
        ps.generate_floor_windows(10, 0, 2, W, write_files=True, portal_folder=portal)
        row = _rows(portal)[-1]
        files = glob.glob(os.path.join(portal, "10p10", "source_primes", "**", "*.bin"),
                          recursive=True)
        on_disk = sum(os.path.getsize(p) for p in files)
        check(len(files) == 2, f"two window files written ({len(files)})")
        check(int(row["bytes_written"]) == on_disk,
              f"bytes_written = size on disk ({row['bytes_written']} vs {on_disk})")
        check(int(row["numbers_processed"]) == 2 * W, "numbers_processed = 2 windows")
        check(float(row["max_child_rss_mb"]) > 10, f"peak RSS measured ({row['max_child_rss_mb']})")
        total = float(row["total_seconds"])
        parts = float(row["sieve_seconds"]) + float(row["write_seconds"])
        check(total >= float(row["sieve_seconds"]) and abs(total - parts) < 0.05 + 0.1 * total,
              f"total covers sieving and writing ({total} vs {parts})")
    finally:
        shutil.rmtree(portal, ignore_errors=True)


def main():
    _test_row_columns()
    _test_generate_in_wsl()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
