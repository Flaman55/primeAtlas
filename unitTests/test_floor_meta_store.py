"""
test_floor_meta_store.py -- a floor's floor_meta.json is read and appended by one module,
prime_sieve/floor_meta_store.py.

A. append_benchmark_row_to_floor_meta(): creates the file with the row; skips a row whose
   key is already there; appends a second distinct row; leaves a corrupt or non-floor_meta
   file byte-for-byte and returns False; leaves no temp file behind.
B. load_floor_meta(): None for a missing or corrupt file, the stored rows otherwise.
C. The GUI's floor_meta.py uses the same functions (the same objects), and no file outside
   floor_meta_store.py defines its own appender.
D. Every engine's benchmark writer (orchestrator_v3, prime_sieve_primesieve,
   prime_sieve_cudasieve, hybrid_sieve) puts the row it logs into floor_meta.json too, equal
   to the row in benchmark_log.csv.

Usage:
    python unitTests/test_floor_meta_store.py
"""
import contextlib
import csv
import glob
import io
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

ROW_A = {"run_timestamp_utc": "2026-01-01 00:00:00 UTC", "base_exponent": 12,
         "target_idx_start": 0, "target_idx_end": 3, "total_primes": 70}
ROW_B = dict(ROW_A, run_timestamp_utc="2026-01-02 00:00:00 UTC")


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _bytes(path):
    with open(path, "rb") as f:
        return f.read()


def _stored_rows(storage, base_exponent):
    with open(os.path.join(storage, f"10p{base_exponent}", "floor_meta.json"),
              encoding="utf-8") as f:
        return json.load(f)["benchmark_rows"]


def _test_append(store):
    print("\n--- A. append_benchmark_row_to_floor_meta() ---")
    tmp = tempfile.mkdtemp(prefix="primeatlas_floor_meta_")
    try:
        path = store.floor_meta_path(tmp, 12)
        check(store.append_benchmark_row_to_floor_meta(tmp, 12, ROW_A) is True
              and _stored_rows(tmp, 12) == [ROW_A], "new file: True, holds the row")
        with open(path, encoding="utf-8") as f:
            check(json.load(f)["base_exponent"] == 12, "the file records base_exponent")
        before = _bytes(path)
        check(store.append_benchmark_row_to_floor_meta(tmp, 12, dict(ROW_A)) is False
              and _bytes(path) == before, "same key again: False, file unchanged")
        check(store.append_benchmark_row_to_floor_meta(tmp, 12, ROW_B) is True
              and _stored_rows(tmp, 12) == [ROW_A, ROW_B], "distinct row: appended after the first")
        check(os.listdir(os.path.dirname(path)) == ["floor_meta.json"], "no temp file left behind")

        for label, content in (("corrupt JSON", '{"benchmark_rows": [ {'),
                               ("a JSON list", "[1, 2]"),
                               ("benchmark_rows not a list", '{"benchmark_rows": 5}')):
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            before = _bytes(path)
            check(store.append_benchmark_row_to_floor_meta(tmp, 12, ROW_A) is False
                  and _bytes(path) == before, f"{label}: False, file left byte-for-byte")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_load(store):
    print("\n--- B. load_floor_meta() ---")
    tmp = tempfile.mkdtemp(prefix="primeatlas_floor_meta_load_")
    try:
        check(store.load_floor_meta(tmp, 12) is None, "missing file: None")
        store.append_benchmark_row_to_floor_meta(tmp, 12, ROW_A)
        check(store.load_floor_meta(tmp, 12) == {"base_exponent": 12, "benchmark_rows": [ROW_A]},
              "valid file: its rows")
        with open(store.floor_meta_path(tmp, 12), "w", encoding="utf-8") as f:
            f.write("not json")
        check(store.load_floor_meta(tmp, 12) is None, "corrupt file: None")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _test_single_source(store):
    print("\n--- C. one appender, used by the GUI too ---")
    from primeatlas.settings import floor_meta
    for name in ("FLOOR_META_FILENAME", "floor_meta_path", "load_floor_meta", "save_floor_meta",
                 "append_benchmark_row_to_floor_meta"):
        check(getattr(floor_meta, name, None) is getattr(store, name),
              f"floor_meta.{name} is floor_meta_store.{name}")
    sources = [p for pattern in ("*.py", "prime_sieve/*.py", "constellation/*.py",
                                 "primeatlas/**/*.py")
               for p in glob.glob(os.path.join(_REPO_ROOT, pattern), recursive=True)]
    own = os.path.join(_REPO_ROOT, "prime_sieve", "floor_meta_store.py")
    own_appender = re.compile(
        r"^\s*def (_append_floor_meta_row|append_benchmark_row_to_floor_meta|_?row_key)\(", re.M)
    copies = []
    for path in sources:
        if os.path.samefile(path, own) or os.path.basename(path).startswith("prime_sieve_v"):
            continue
        with open(path, encoding="utf-8") as f:
            if own_appender.search(f.read()):
                copies.append(os.path.relpath(path, _REPO_ROOT))
    check(not copies, f"no floor_meta appender outside floor_meta_store.py ({copies})")


def _test_engines():
    print("\n--- D. every engine's benchmark writer fills floor_meta.json ---")
    import orchestrator_v3
    import prime_sieve_primesieve
    import prime_sieve_cudasieve
    import hybrid_sieve
    writers = {
        "orchestrator_v3": lambda tmp: orchestrator_v3.print_benchmark_summary(
            13, 0, 2, 10.0, tmp, write_files=False, total_primes_found=50, windows_processed=2),
        "prime_sieve_primesieve": lambda tmp: prime_sieve_primesieve.write_benchmark_row(
            13, 0, 2, 10.0, 50, 2, False, tmp),
        "prime_sieve_cudasieve": lambda tmp: prime_sieve_cudasieve.write_benchmark_row(
            13, 0, 2, 10.0, 50, 2, False, tmp),
        "hybrid_sieve": lambda tmp: hybrid_sieve.write_hybrid_benchmark_row(
            tmp, 13, 0, 2, 10.0, 50, False, 0.1, 5.0, 1.0, 100),
    }
    for name, write in writers.items():
        tmp = tempfile.mkdtemp(prefix=f"primeatlas_floor_meta_{name}_")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                write(tmp)
            with open(os.path.join(tmp, "benchmark_log.csv"), newline="") as f:
                logged = list(csv.DictReader(f))
            try:
                stored = _stored_rows(tmp, 13)
            except OSError:
                stored = None
            check(stored is not None and len(stored) == 1 and len(logged) == 1
                  and {k: str(v) for k, v in stored[0].items()}
                  == {k: v for k, v in logged[0].items() if k in stored[0]},
                  f"{name}: floor_meta.json holds the logged row")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def main():
    try:
        import floor_meta_store as store
    except ImportError as exc:
        check(False, f"prime_sieve/floor_meta_store.py imports ({exc})")
    else:
        _test_append(store)
        _test_load(store)
        _test_single_source(store)
    _test_engines()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
