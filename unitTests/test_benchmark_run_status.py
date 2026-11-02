"""
test_benchmark_run_status.py -- the run_status column of benchmark_log.csv across every
writer (CLOSE_GUARD_PLAN.md acceptance criterion 10): orchestrator_v3,
orchestrator_loop_helpers, prime_sieve_primesieve, prime_sieve_cudasieve and hybrid_sieve
share one header, each one's migration adds run_status to an existing log without changing
its old rows, and a completed row of every engine is logged with run_status=completed.

No WSL and no engine run: the writers' own log functions are called on a temp folder.

Usage:
    python unitTests/test_benchmark_run_status.py
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

OLD_ROW = {"base_exponent": "12", "windows_written": "7", "total_primes": "70",
           "write_files": "1", "total_seconds": "3.5"}


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _read(path):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def _old_log(folder, fieldnames):
    """A log written before run_status existed, with one row."""
    path = os.path.join(folder, "benchmark_log.csv")
    old_fields = [f for f in fieldnames if f != "run_status"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=old_fields)
        w.writeheader()
        w.writerow(OLD_ROW)
    return path


def _old_row_unchanged(row):
    return (all(row.get(k) == v for k, v in OLD_ROW.items())
            and row.get("run_status", "") == "")


def main():
    import orchestrator_v3
    import orchestrator_loop_helpers
    import prime_sieve_primesieve
    import prime_sieve_cudasieve
    import hybrid_sieve

    modules = {"orchestrator_v3": orchestrator_v3,
               "orchestrator_loop_helpers": orchestrator_loop_helpers,
               "prime_sieve_primesieve": prime_sieve_primesieve,
               "prime_sieve_cudasieve": prime_sieve_cudasieve,
               "hybrid_sieve": hybrid_sieve}
    reference = orchestrator_v3.BENCHMARK_FIELDNAMES
    for name, module in modules.items():
        check(module.BENCHMARK_FIELDNAMES == reference,
              f"{name}: same benchmark header as orchestrator_v3")

    # migration alone
    for name in ("orchestrator_v3", "orchestrator_loop_helpers", "prime_sieve_primesieve",
                 "prime_sieve_cudasieve"):
        module = modules[name]
        tmp = tempfile.mkdtemp(prefix=f"primeatlas_run_status_{name}_")
        try:
            path = _old_log(tmp, module.BENCHMARK_FIELDNAMES)
            module._ensure_benchmark_log_schema(path)
            fields, rows = _read(path)
            check("run_status" in (fields or []), f"{name}: migration adds run_status")
            check(len(rows) == 1 and _old_row_unchanged(rows[0]),
                  f"{name}: migration keeps the old row unchanged")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # a completed row of each engine with its own writer, on an old log
    writers = {
        "prime_sieve_primesieve": lambda tmp: prime_sieve_primesieve.write_benchmark_row(
            13, 0, 2, 10.0, 50, 2, True, tmp),
        "prime_sieve_cudasieve": lambda tmp: prime_sieve_cudasieve.write_benchmark_row(
            13, 0, 2, 10.0, 50, 2, True, tmp),
        "hybrid_sieve": lambda tmp: hybrid_sieve.write_hybrid_benchmark_row(
            tmp, 13, 0, 2, 10.0, 50, True, 0.1, 5.0, 1.0, 100),
    }
    for name, write in writers.items():
        tmp = tempfile.mkdtemp(prefix=f"primeatlas_run_status_row_{name}_")
        try:
            path = _old_log(tmp, modules[name].BENCHMARK_FIELDNAMES)
            write(tmp)
            fields, rows = _read(path)
            check(fields == reference, f"{name}: log header after a write = the shared header")
            check(len(rows) == 2 and _old_row_unchanged(rows[0]),
                  f"{name}: the old row is unchanged after a write")
            status = rows[1].get("run_status") if len(rows) == 2 else None
            check(status == "completed", f"{name}: a completed run logs run_status=completed "
                                         f"({status!r})")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
