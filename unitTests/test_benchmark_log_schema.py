"""
test_benchmark_log_schema.py -- benchmark_log.csv has one header, defined once in
prime_sieve/benchmark_log_schema.py.

A. BENCHMARK_FIELDNAMES is the header the live log already has (same columns, same order),
   so no writer migrates an existing log just to reorder it.
B. Every writer and floor_meta.py use that one list (the same object, not an equal copy),
   and no file outside benchmark_log_schema.py defines a BENCHMARK_FIELDNAMES literal or
   its own (_)ensure_benchmark_log_schema().
C. ensure_benchmark_log_schema(): a missing log stays missing (True); the current header
   is left byte-for-byte (True); an older header that is a subset gains the missing
   columns with every old row unchanged (True); a header with a foreign column is left
   byte-for-byte (False).
D. floor_meta.merge_floor_meta_into_benchmark_log() growing a log from scratch writes
   exactly BENCHMARK_FIELDNAMES as its header.
E. Every row writer fills engine_version; orchestrator_v3 takes it from the scanner
   module's own VERSION (v5.1, v6.0, ...), so the engine files stay untouched.

Usage:
    python unitTests/test_benchmark_log_schema.py
"""
import csv
import glob
import json
import os
import re
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []

LIVE_HEADER = [
    "run_timestamp_utc", "base_exponent", "target_idx_start", "target_idx_end",
    "windows_written", "total_seconds", "seconds_per_window", "total_primes",
    "avg_primes_per_window", "primes_per_second", "l_final", "sieving_primes_count",
    "max_child_rss_mb", "instance_of_n", "loop_session_seconds", "loop_numbers_per_second",
    "loop_seconds_per_window", "write_files", "base_gen_seconds", "sieve_seconds",
    "write_seconds", "bytes_written", "engine", "numbers_processed", "run_status",
    "verify_seconds", "engine_version",
]
OLD_ROW = {"run_timestamp_utc": "2026-01-01 00:00:00 UTC", "base_exponent": "12",
           "windows_written": "7", "total_primes": "70", "total_seconds": "3.5"}


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _write_log(path, fieldnames, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _read_log(path):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def _test_header(schema):
    print("\n--- A. the header the live log has ---")
    check(schema.BENCHMARK_FIELDNAMES == LIVE_HEADER,
          f"BENCHMARK_FIELDNAMES = the live 27-column header ({len(schema.BENCHMARK_FIELDNAMES)})")
    check(schema.RUN_STATUS_COMPLETED == "completed" and schema.RUN_STATUS_STOPPED == "stopped",
          "run_status values completed / stopped")


def _test_single_source(schema):
    print("\n--- B. one definition, imported everywhere ---")
    import orchestrator_v3
    import orchestrator_loop_helpers
    import prime_sieve_primesieve
    import prime_sieve_cudasieve
    import hybrid_sieve
    from primeatlas.settings import floor_meta
    for module in (orchestrator_v3, orchestrator_loop_helpers, prime_sieve_primesieve,
                   prime_sieve_cudasieve, hybrid_sieve, floor_meta):
        check(getattr(module, "BENCHMARK_FIELDNAMES", None) is schema.BENCHMARK_FIELDNAMES,
              f"{module.__name__} imports BENCHMARK_FIELDNAMES from benchmark_log_schema")
    sources = [p for pattern in ("*.py", "prime_sieve/*.py", "constellation/*.py",
                                 "primeatlas/**/*.py")
               for p in glob.glob(os.path.join(_REPO_ROOT, pattern), recursive=True)]
    own = os.path.join(_REPO_ROOT, "prime_sieve", "benchmark_log_schema.py")
    literal = re.compile(r"^\s*\w*BENCHMARK_FIELDNAMES\s*=\s*\[", re.M)
    own_migration = re.compile(r"^\s*def _?ensure_benchmark_log_schema\(", re.M)
    copies = []
    for path in sources:
        if os.path.samefile(path, own):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if literal.search(text) or own_migration.search(text):
            copies.append(os.path.relpath(path, _REPO_ROOT))
    check(not copies, f"no copy of the header or its migration outside benchmark_log_schema.py "
                      f"({copies})")


def _test_migration(schema):
    print("\n--- C. ensure_benchmark_log_schema() ---")
    tmp = tempfile.mkdtemp(prefix="primeatlas_log_schema_")
    try:
        path = os.path.join(tmp, "benchmark_log.csv")
        check(schema.ensure_benchmark_log_schema(path) is True and not os.path.exists(path),
              "missing log: True, nothing created")

        _write_log(path, LIVE_HEADER, [OLD_ROW])
        before = _bytes(path)
        check(schema.ensure_benchmark_log_schema(path) is True and _bytes(path) == before,
              "current header: True, file unchanged")

        old_fields = [f for f in LIVE_HEADER if f not in ("engine", "run_status")]
        _write_log(path, old_fields, [OLD_ROW])
        ok = schema.ensure_benchmark_log_schema(path)
        fields, rows = _read_log(path)
        check(ok is True and fields == LIVE_HEADER, "older subset header: True, migrated")
        check(len(rows) == 1 and all(rows[0][k] == v for k, v in OLD_ROW.items())
              and rows[0]["engine"] == "" and rows[0]["run_status"] == "",
              "older subset header: the old row is unchanged, new columns blank")
        check(not [n for n in os.listdir(tmp) if n != "benchmark_log.csv"],
              "migration leaves no temp file behind")

        _write_log(path, LIVE_HEADER + ["foreign"], [dict(OLD_ROW, foreign="x")])
        before = _bytes(path)
        check(schema.ensure_benchmark_log_schema(path) is False and _bytes(path) == before,
              "foreign column: False, file unchanged")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_floor_meta_new_log(schema):
    print("\n--- D. floor_meta grows a new log with the shared header ---")
    from primeatlas.settings import floor_meta
    tmp = tempfile.mkdtemp(prefix="primeatlas_log_schema_meta_")
    try:
        os.makedirs(os.path.join(tmp, "10p12"))
        with open(floor_meta.floor_meta_path(tmp, 12), "w", encoding="utf-8") as f:
            json.dump({"base_exponent": 12, "benchmark_rows": [dict(OLD_ROW, engine="v5")]}, f)
        imported = floor_meta.merge_floor_meta_into_benchmark_log(tmp, 12)
        fields, rows = _read_log(os.path.join(tmp, "benchmark_log.csv"))
        check(imported == 1 and len(rows) == 1, "one row imported")
        check(fields == schema.BENCHMARK_FIELDNAMES, f"header = BENCHMARK_FIELDNAMES ({fields})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_engine_version_writers():
    print("\n--- E. every row writer fills engine_version ---")
    for name in ("orchestrator_v3.py", "prime_sieve_primesieve.py", "prime_sieve_cudasieve.py",
                 "hybrid_sieve.py"):
        with open(os.path.join(_REPO_ROOT, "prime_sieve", name), encoding="utf-8") as f:
            text = f.read()
        check('"engine_version":' in text, f"{name} writes engine_version in its row")
    with open(os.path.join(_REPO_ROOT, "prime_sieve", "orchestrator_v3.py"),
              encoding="utf-8") as f:
        text = f.read()
    check('"engine_version": prime_sieve_module.VERSION' in text,
          "orchestrator_v3 logs the scanner module's own VERSION")


def main():
    try:
        import benchmark_log_schema as schema
    except ImportError as exc:
        check(False, f"prime_sieve/benchmark_log_schema.py imports ({exc})")
    else:
        _test_header(schema)
        _test_single_source(schema)
        _test_migration(schema)
        _test_floor_meta_new_log(schema)
        _test_engine_version_writers()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
