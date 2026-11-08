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
   prime_sieve_cudasieve, hybrid_sieve, primesieve_native) tags the row it logs with
   run_purpose: a storage run (files written; native print) and a benchmark run (count-only;
   native count). An Atlas engine's storage row goes into floor_meta.json too, equal to the
   row in benchmark_log.csv; its benchmark run leaves the storage without a floor folder.
   Native primesieve has no Atlas floor folder either way.
E. append_benchmark_row_to_floor_meta() refuses a benchmark row (run_purpose, or a legacy
   row with write_files 0), and every script in prime_sieve/ that writes benchmark log rows
   sets run_purpose, so an engine added later cannot log without it.

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


def _writers():
    import orchestrator_v3
    import prime_sieve_primesieve
    import prime_sieve_cudasieve
    import hybrid_sieve
    import primesieve_native

    def native(mode):
        def write(tmp, write_files):
            primesieve_native.append_row(tmp, primesieve_native.benchmark_row(
                mode, 13, 0, 2, 10_000_000, 10.0, 50, 4, "test", None, None))
        return write
    return {
        "orchestrator_v3": lambda tmp, wf: orchestrator_v3.print_benchmark_summary(
            13, 0, 2, 10.0, tmp, write_files=wf, total_primes_found=50, windows_processed=2),
        "prime_sieve_primesieve": lambda tmp, wf: prime_sieve_primesieve.write_benchmark_row(
            13, 0, 2, 10.0, 50, 2, wf, tmp),
        "prime_sieve_cudasieve": lambda tmp, wf: prime_sieve_cudasieve.write_benchmark_row(
            13, 0, 2, 10.0, 50, 2, wf, tmp),
        "hybrid_sieve": lambda tmp, wf: hybrid_sieve.write_hybrid_benchmark_row(
            tmp, 13, 0, 2, 10.0, 50, wf, 0.1, 5.0, 1.0, 100),
        "primesieve_native print": native("print"),
        "primesieve_native count": native("count"),
    }


def _test_engines():
    print("\n--- D. every engine tags its row; only storage runs fill floor_meta.json ---")
    for name, write in _writers().items():
        purposes = ((True, "storage"), (False, "benchmark"))
        if name.startswith("primesieve_native"):
            purposes = ((name.endswith("print"), "storage" if name.endswith("print") else "benchmark"),)
        for write_files, purpose in purposes:
            tmp = tempfile.mkdtemp(prefix="primeatlas_floor_meta_engine_")
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    write(tmp, write_files)
                with open(os.path.join(tmp, "benchmark_log.csv"), newline="") as f:
                    logged = list(csv.DictReader(f))
                check(len(logged) == 1 and logged[0].get("run_purpose") == purpose,
                      f"{name}, write_files={write_files}: logged row has run_purpose={purpose}")
                if name.startswith("primesieve_native"):
                    continue
                if purpose == "storage":
                    try:
                        stored = _stored_rows(tmp, 13)
                    except OSError:
                        stored = None
                    check(stored is not None and len(stored) == 1
                          and {k: str(v) for k, v in stored[0].items()}
                          == {k: v for k, v in logged[0].items() if k in stored[0]},
                          f"{name}: floor_meta.json holds the logged storage row")
                else:
                    check(not os.path.exists(os.path.join(tmp, "10p13")),
                          f"{name}: a benchmark run leaves no floor folder in the storage")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)


def _test_benchmark_rows_refused(store):
    print("\n--- E. benchmark rows never reach floor_meta.json ---")
    tmp = tempfile.mkdtemp(prefix="primeatlas_floor_meta_purpose_")
    try:
        for label, row in (("run_purpose benchmark", dict(ROW_A, run_purpose="benchmark")),
                           ("legacy write_files 0", dict(ROW_A, write_files="0")),
                           ("legacy write_files 0 as int", dict(ROW_A, write_files=0))):
            check(store.append_benchmark_row_to_floor_meta(tmp, 12, row) is False
                  and not os.path.exists(os.path.join(tmp, "10p12")),
                  f"{label}: refused, no floor folder created")
        check(store.append_benchmark_row_to_floor_meta(
                  tmp, 12, dict(ROW_A, run_purpose="storage", write_files="1")) is True,
              "run_purpose storage: appended")
        check(store.append_benchmark_row_to_floor_meta(tmp, 12, dict(ROW_B)) is True,
              "legacy row without run_purpose or write_files: appended (storage)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    frozen = re.compile(r"^(prime_sieve_v\d|repair_)")
    writes_rows = re.compile(r"DictWriter\([^)]*BENCHMARK_FIELDNAMES")
    missing = []
    for path in sorted(glob.glob(os.path.join(_REPO_ROOT, "prime_sieve", "*.py"))):
        if frozen.match(os.path.basename(path)):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if writes_rows.search(text) and "run_purpose" not in text:
            missing.append(os.path.basename(path))
    check(not missing, f"every benchmark log writer in prime_sieve/ sets run_purpose ({missing})")


def main():
    try:
        import floor_meta_store as store
    except ImportError as exc:
        check(False, f"prime_sieve/floor_meta_store.py imports ({exc})")
    else:
        _test_append(store)
        _test_load(store)
        _test_single_source(store)
        _test_benchmark_rows_refused(store)
    _test_engines()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
