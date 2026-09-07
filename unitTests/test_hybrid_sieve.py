"""Executable integration checks for the storage-backed hybrid reference runner.

Usage (WSL or a Python environment with this repository on disk):
    python3 unitTests/test_hybrid_sieve.py
"""
import csv
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

import hybrid_sieve
from hybrid_reference import write_new_pgs2_floor_window
from prime_sieve_v1 import read_prime_window
import window_sharding


def ordinary_primes(lo, hi):
    marked = bytearray(hi)
    marked[:2] = b"\x01\x01"
    for p in range(2, int((hi - 1) ** 0.5) + 1):
        if not marked[p]:
            marked[p * p:hi:p] = b"\x01" * len(marked[p * p:hi:p])
    return [value for value in range(lo, hi) if not marked[value]]


def check(condition, message):
    print(("ok:   " if condition else "FAIL: ") + message)
    return bool(condition)


def main():
    passed = True
    with tempfile.TemporaryDirectory(prefix="primeatlas_hybrid_sieve_") as portal:
        # A real continuous PGS2 seed through 10 is sufficient for a tiny,
        # deterministic reference stage.  window_m=10 keeps this test tiny;
        # production always uses the runner's 10,000,000 default.
        write_new_pgs2_floor_window(portal, 0, 0, 10, [2, 3, 5, 7])
        original_benchmark = hybrid_sieve.write_hybrid_benchmark_row
        original_metrics = hybrid_sieve.write_scan_metrics_handoff
        hybrid_sieve.write_hybrid_benchmark_row = lambda *args: None
        hybrid_sieve.write_scan_metrics_handoff = lambda *args, **kwargs: None
        try:
            hybrid_sieve.run_hybrid_sieve(0, 1, 10, 1, True, portal, window_m=10)
        finally:
            hybrid_sieve.write_hybrid_benchmark_row = original_benchmark
            hybrid_sieve.write_scan_metrics_handoff = original_metrics
        result = []
        source = os.path.join(portal, "10p1", "source_primes")
        for _name, path in window_sharding.list_sharded_files(source):
            result.extend(read_prime_window(path))
        passed &= check(result == ordinary_primes(10, 100),
                        "runner writes ordinary PGS2 windows with hybrid survivors only")

        # A later file without its predecessor is not a MAIN prefix.  The runner
        # must reject it, never infer continuity from the last file it sees.
        bad = os.path.join(portal, "bad")
        write_new_pgs2_floor_window(bad, 0, 0, 10, [2, 3, 5, 7])
        write_new_pgs2_floor_window(bad, 1, 1, 10, [])
        try:
            hybrid_sieve.load_contiguous_main_prefix(bad, 1, window_m=10)
        except hybrid_sieve.HybridSieveError as exc:
            passed &= check("gap" in str(exc), "runner rejects a gapped selected MAIN floor")
        else:
            passed &= check(False, "runner rejects a gapped selected MAIN floor")

    # Storage is output only: an empty portal is valid, a rerun leaves existing
    # windows byte-identical, and a single missing output window is regenerated.
    with tempfile.TemporaryDirectory(prefix="primeatlas_hybrid_output_") as portal:
        hybrid_sieve.write_hybrid_benchmark_row = lambda *args: None
        hybrid_sieve.write_scan_metrics_handoff = lambda *args, **kwargs: None
        try:
            hybrid_sieve.run_hybrid_sieve(0, 1, 10, 1, True, portal, window_m=10)
            floor0 = hybrid_sieve._window_path(hybrid_sieve.Path(portal), 0, 0, 10)
            floor1 = hybrid_sieve._window_path(hybrid_sieve.Path(portal), 1, 0, 10)
            passed &= check(floor0.is_file() and floor1.is_file(),
                            "empty magazyn generates and routes floor-0/floor-1 output separately")
            # Floors below LOW_FLOOR_CUTOFF each have one whole-floor PGS2
            # window, even when this test deliberately uses window_m=10.
            all_paths = [
                hybrid_sieve._window_path(hybrid_sieve.Path(portal), 0, 0, 10),
                hybrid_sieve._window_path(hybrid_sieve.Path(portal), 1, 0, 10),
            ]
            preserved = {path: path.read_bytes() for path in all_paths}
            hybrid_sieve.run_hybrid_sieve(0, 1, 10, 1, True, portal, window_m=10)
            passed &= check(all(path.read_bytes() == data for path, data in preserved.items()),
                            "rerun skips complete PGS2 windows rather than overwriting them")
            missing = all_paths[1]
            missing.unlink()
            hybrid_sieve.run_hybrid_sieve(0, 1, 10, 1, True, portal, window_m=10)
            passed &= check(missing.is_file() and missing.read_bytes() == preserved[missing],
                            "a gapped magazyn regenerates only the missing standard window")
            passed &= check(all(path == missing or path.read_bytes() == data
                                for path, data in preserved.items()),
                            "filling a gap leaves every other output window unchanged")
        finally:
            hybrid_sieve.write_hybrid_benchmark_row = original_benchmark
            hybrid_sieve.write_scan_metrics_handoff = original_metrics

    # Hybrid must append into exactly the same 4.1 CSV schema used by the
    # Benchmark tab and the established engines.  In particular, timing must
    # not shift into unrelated columns when an older shorter header exists.
    with tempfile.TemporaryDirectory(prefix="primeatlas_hybrid_benchmark_") as portal:
        log_path = os.path.join(portal, "benchmark_log.csv")
        old_fields = hybrid_sieve.BENCHMARK_FIELDNAMES[:18]
        with open(log_path, "w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=old_fields)
            writer.writeheader()
            writer.writerow({"base_exponent": "9", "total_seconds": "1.25"})
        hybrid_sieve.write_hybrid_benchmark_row(
            portal, 10, 2, 3.0, 123, True, 0.1, 1.2, 1.7, 456)
        with open(log_path, newline="") as stream:
            reader = csv.DictReader(stream)
            fields, rows = reader.fieldnames, list(reader)
        passed &= check(fields == hybrid_sieve.BENCHMARK_FIELDNAMES,
                        "hybrid benchmark writer preserves the canonical 4.1 CSV schema")
        new_row = rows[-1]
        passed &= check(new_row["instance_of_n"] == "hybrid"
                        and new_row["base_gen_seconds"] == "0.100"
                        and new_row["sieve_seconds"] == "1.200"
                        and new_row["write_seconds"] == "1.700"
                        and new_row["bytes_written"] == "456",
                        "hybrid benchmark timings and bytes land in their named columns")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
