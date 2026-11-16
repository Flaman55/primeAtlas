"""
test_run_load.py -- prime_sieve/run_load.py, the engine side of a run's machine and CPU load
columns in benchmark_log.csv (machine_id, cpu_busy_before_pct, cpu_busy_during_pct).

A. busy_pct(start, end) of two (idle, total) counter pairs: all idle -> 0, no idle -> 100,
   half -> 50; no time passed, counters going back, or more idle than total -> None.
B. The load file: write_counters() then read_counters() gives the pair back; a missing,
   empty, foreign, negative or one-number file reads as None; writing replaces the old
   pair and leaves no temp file.
C. row_fields(environ, start): every column present, blank when the environment names
   nothing; machine_id kept only as a plain token; the before value kept only as a number
   in 0..100 (one decimal); the during value from the start pair to the file's current pair.
   A missing start pair, a missing file or a file gone back leaves during blank.
D. START_COUNTERS: a process that imports run_load reads the file named in its environment
   at import time, so its during value covers the process's own run.
E. Every column is in BENCHMARK_FIELDNAMES, at its end, in COLUMNS order.

Usage:
    python unitTests/test_run_load.py
"""
import json
import os
import subprocess
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

import benchmark_log_schema  # noqa: E402
import run_load  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _test_busy_pct():
    print("\n--- A. busy_pct ---")
    check(run_load.busy_pct((100, 1000), (200, 1100)) == 0.0, "all idle -> 0")
    check(run_load.busy_pct((100, 1000), (100, 1100)) == 100.0, "no idle -> 100")
    check(run_load.busy_pct((100, 1000), (150, 1100)) == 50.0, "half idle -> 50")
    check(run_load.busy_pct((10 ** 15, 10 ** 16), (10 ** 15 + 3, 10 ** 16 + 4)) == 25.0,
          "large counters, small step -> 25")
    check(run_load.busy_pct((100, 1000), (100, 1000)) is None, "no time passed -> None")
    check(run_load.busy_pct((100, 1000), (90, 1100)) is None, "idle going back -> None")
    check(run_load.busy_pct((100, 1000), (200, 900)) is None, "total going back -> None")
    check(run_load.busy_pct((100, 1000), (300, 1100)) is None, "more idle than total -> None")
    check(run_load.busy_pct(None, (1, 2)) is None and run_load.busy_pct((1, 2), None) is None,
          "a missing pair -> None")


def _test_file(folder):
    print("\n--- B. the load file ---")
    path = os.path.join(folder, "run.load")
    run_load.write_counters(path, (123, 4567))
    check(run_load.read_counters(path) == (123, 4567), "written pair reads back")
    run_load.write_counters(path, (124, 4600))
    check(run_load.read_counters(path) == (124, 4600), "a new write replaces the pair")
    check(sorted(os.listdir(folder)) == ["run.load"], f"no temp file left ({os.listdir(folder)})")
    check(run_load.read_counters(os.path.join(folder, "missing.load")) is None,
          "missing file -> None")
    check(run_load.read_counters(None) is None and run_load.read_counters("") is None,
          "no path -> None")
    for name, text in (("empty", ""), ("foreign", "hello world\n"), ("one", "17\n"),
                       ("negative", "-1 20\n"), ("three", "1 2 3\n"), ("float", "1.5 3\n")):
        bad = os.path.join(folder, f"{name}.load")
        with open(bad, "w", encoding="ascii") as f:
            f.write(text)
        check(run_load.read_counters(bad) is None, f"{name} file -> None")


def _test_row_fields(folder):
    print("\n--- C. row_fields ---")
    empty = run_load.row_fields({}, start=None)
    check(empty == {"machine_id": "", "cpu_busy_before_pct": "", "cpu_busy_during_pct": ""},
          f"nothing named -> every column blank ({empty})")
    path = os.path.join(folder, "row.load")
    run_load.write_counters(path, (400, 2000))
    env = {run_load.MACHINE_ID_ENV: " 3f9a0c1d2e4b ", run_load.CPU_BUSY_BEFORE_ENV: "12.345",
           run_load.LOAD_FILE_ENV: path}
    fields = run_load.row_fields(env, start=(100, 1000))
    check(fields == {"machine_id": "3f9a0c1d2e4b", "cpu_busy_before_pct": "12.3",
                     "cpu_busy_during_pct": "70.0"},
          f"named values -> machine id, before 12.3, during 70.0 ({fields})")
    for bad in ("a b", "x;rm", "", "é", "z" * 65):
        got = run_load.row_fields({run_load.MACHINE_ID_ENV: bad}, start=None)["machine_id"]
        check(got == "", f"machine id {bad[:12]!r} -> blank")
    for bad, want in (("-0.1", ""), ("100.1", ""), ("abc", ""), ("nan", ""), ("inf", ""),
                      ("0", "0.0"), ("100", "100.0"), ("99.96", "100.0")):
        got = run_load.row_fields({run_load.CPU_BUSY_BEFORE_ENV: bad}, start=None)
        check(got["cpu_busy_before_pct"] == want, f"before {bad!r} -> {want!r}")
    check(run_load.row_fields(env, start=None)["cpu_busy_during_pct"] == "",
          "no start pair -> during blank")
    gone = dict(env, **{run_load.LOAD_FILE_ENV: os.path.join(folder, "gone.load")})
    check(run_load.row_fields(gone, start=(100, 1000))["cpu_busy_during_pct"] == "",
          "missing file -> during blank")
    check(run_load.row_fields(env, start=(500, 3000))["cpu_busy_during_pct"] == "",
          "file gone back -> during blank")


_CHILD = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
import run_load
run_load.write_counters(os.environ[run_load.LOAD_FILE_ENV], (150, 1200))
print(json.dumps(run_load.row_fields(os.environ)))
"""


def _test_start_counters(folder):
    print("\n--- D. START_COUNTERS at import ---")
    path = os.path.join(folder, "child.load")
    run_load.write_counters(path, (100, 1000))
    env = dict(os.environ, **{run_load.LOAD_FILE_ENV: path})
    out = subprocess.run([sys.executable, "-c", _CHILD, os.path.join(_REPO_ROOT, "prime_sieve")],
                         env=env, capture_output=True, text=True, timeout=60)
    try:
        fields = json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        fields = {}
    check(fields.get("cpu_busy_during_pct") == "75.0",
          f"the pair read at import is the start (75.0; got {fields}, {out.stderr[-300:]})")
    check(run_load.start_counters({}) is None, "no file named -> no start pair")
    check(run_load.start_counters({run_load.LOAD_FILE_ENV: path}) == (150, 1200),
          "start_counters reads the named file")


def _test_columns():
    print("\n--- E. the columns in the header ---")
    names = benchmark_log_schema.BENCHMARK_FIELDNAMES
    check(tuple(run_load.COLUMNS) == ("machine_id", "cpu_busy_before_pct", "cpu_busy_during_pct"),
          "COLUMNS names the three columns")
    check(tuple(names[-len(run_load.COLUMNS):]) == tuple(run_load.COLUMNS),
          "the columns close the header, in COLUMNS order")


def main():
    with tempfile.TemporaryDirectory() as folder:
        _test_busy_pct()
        file_folder = os.path.join(folder, "file")
        os.makedirs(file_folder)
        _test_file(file_folder)
        _test_row_fields(folder)
        _test_start_counters(folder)
    _test_columns()
    print()
    if failures:
        print(f"{len(failures)} FAILED")
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
