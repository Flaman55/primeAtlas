"""
test_print_benchmark_summary.py -- regression test for a real production bug found
2026-08-27: orchestrator_v3.py's print_benchmark_summary() (write_files=True branch)
re-derives windows_found/total_primes by checking os.path.exists() for each expected
window's filename, built from a FLAT "source_dir/PRIME_WINDOW_....bin" path. Task #405
sharded source_primes/ into shard_NNNNN subfolders, but this ONE function was missed in
that sweep (every other reader in the codebase was fixed) -- so every real, correctly
written, sharded generation run since then logged windows_written=0 / total_primes=0 to
benchmark_log.csv, even though the actual PGS2 files on disk were completely correct.

Caught by Artur running a real 1000-window generation on 10^13 against live H:/Goldbach
storage: prime_sieve_v4_1.py's own console output correctly printed "TOTAL PRIMES FOUND
this run: 334,053,075 across 1000 windows", but the very next benchmark summary line
printed "0 windows written" / "0 primes found" -- exactly this bug.

Pure logic, no tkinter, no real prime data needed beyond a couple of tiny PGS2 fixture
windows written via prime_sieve_v1.write_prime_window() into the CORRECT sharded location
(window_sharding.shard_dir), matching what a real engine run actually produces on disk.

Usage:
    python unitTests/test_print_benchmark_summary.py
"""
import csv
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def main():
    import prime_sieve_v1
    import window_sharding
    import orchestrator_v3

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_benchmark_summary_test_")
    try:
        base_exponent = 13
        window_m = 10_000_000
        start_idx = 2000
        end_idx = 2002  # two windows: target_idx 2000 and 2001

        source_dir = os.path.join(tmp_portal, f"10p{base_exponent}", "source_primes")

        # Seed exactly what a real engine run writes: PGS2 files under the CORRECT
        # shard_NNNNN subfolder (not flat) -- mirrors prime_sieve_v4_1.py's own write
        # loop (offset = target_idx * window_m, format_offset() naming convention).
        for target_idx, primes in ((2000, [10_020_000_000_037, 10_020_000_000_041]),
                                    (2001, [10_020_010_000_003])):
            offset = target_idx * window_m
            window_index = window_sharding.shard_index_for_offset(offset, window_m)
            shard_folder = window_sharding.shard_dir(source_dir, window_index)
            os.makedirs(shard_folder, exist_ok=True)
            tag = f"10p{base_exponent}_off_{orchestrator_v3.prime_sieve_module.format_offset(offset)}"
            prime_sieve_v1.write_prime_window(
                os.path.join(shard_folder, f"PRIME_WINDOW_{tag}.bin"), primes)

        orchestrator_v3.print_benchmark_summary(
            base_exponent, start_idx, end_idx, total_seconds=12.5, portal_folder=tmp_portal,
            l_final=1000, sieving_primes_count=168, max_child_rss_mb=256.0,
            write_files=True, window_m=window_m,
            base_gen_seconds=0.1, sieve_seconds=10.0, write_seconds=2.4, bytes_written=4096)

        log_path = os.path.join(tmp_portal, "benchmark_log.csv")
        check(os.path.exists(log_path), "benchmark_log.csv was written")
        with open(log_path, newline="") as f:
            rows = list(csv.DictReader(f))
        check(len(rows) == 1, f"exactly one row logged (got {len(rows)})")
        row = rows[0]

        check(row["windows_written"] == "2",
              f"windows_written counts BOTH sharded windows actually on disk, not 0 "
              f"(got {row['windows_written']!r}) -- this is the exact regression: before "
              f"the fix, os.path.exists() checked a flat path that never matches a "
              f"sharded file, so this was always '0'")
        check(row["total_primes"] == "3",
              f"total_primes sums the real per-window PGS2 header counts (2+1=3) "
              f"(got {row['total_primes']!r})")
        check(row["seconds_per_window"] == "6.2500",
              f"seconds_per_window = 12.5s / 2 windows, not nan (got "
              f"{row['seconds_per_window']!r})")

        # --- Same call, but against an EMPTY portal (no windows on disk at all) should
        # still behave sanely: 0 windows, 0 primes, no crash, nan-safe division.
        tmp_portal2 = tempfile.mkdtemp(prefix="primeatlas_benchmark_summary_test_empty_")
        try:
            orchestrator_v3.print_benchmark_summary(
                base_exponent, start_idx, end_idx, total_seconds=5.0, portal_folder=tmp_portal2,
                l_final=None, sieving_primes_count=None, write_files=True, window_m=window_m)
            log_path2 = os.path.join(tmp_portal2, "benchmark_log.csv")
            with open(log_path2, newline="") as f:
                rows2 = list(csv.DictReader(f))
            check(rows2[0]["windows_written"] == "0",
                  f"a floor with genuinely no files on disk still correctly reports 0 "
                  f"(not a crash, not a stale/wrong count) (got {rows2[0]['windows_written']!r})")
        finally:
            shutil.rmtree(tmp_portal2, ignore_errors=True)
    finally:
        shutil.rmtree(tmp_portal, ignore_errors=True)

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
