"""Executable integration checks for the storage-backed hybrid reference runner.

Usage (WSL or a Python environment with this repository on disk):
    python3 unitTests/test_hybrid_sieve.py
"""
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
        original_bootstrap = hybrid_sieve.bootstrap_following_primes
        original_benchmark = hybrid_sieve.write_benchmark_row
        original_metrics = hybrid_sieve.write_scan_metrics_handoff
        hybrid_sieve.bootstrap_following_primes = lambda _a, _k: (11, 13)
        hybrid_sieve.write_benchmark_row = lambda *args: None
        hybrid_sieve.write_scan_metrics_handoff = lambda *args, **kwargs: None
        try:
            hybrid_sieve.run_hybrid_sieve(0, 1, 1, True, portal, window_m=10)
        finally:
            hybrid_sieve.bootstrap_following_primes = original_bootstrap
            hybrid_sieve.write_benchmark_row = original_benchmark
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
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
