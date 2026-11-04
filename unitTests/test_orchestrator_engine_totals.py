"""
test_orchestrator_engine_totals.py -- orchestrator_v3 takes a written run's prime count from
the engine's own report instead of re-reading every window header.

run_batch() copies the scanner's stdout through unchanged and picks up its
"[*] TOTAL PRIMES FOUND this run: N across W windows" line (each scanner process has its own
stdout, so parallel instances never see each other's report). run_orchestrator() logs that
count when every batch reported one and the reported windows add up to the run; otherwise
(a batch without the line, a low-floor run reporting floors, a stopped run) it counts the
headers as before.

The scanner is a tiny script for run_batch() and a fake run_batch for run_orchestrator(),
so no WSL or real engine is needed.

Usage:
    python unitTests/test_orchestrator_engine_totals.py
"""
import csv
import io
import os
import shutil
import sys
import tempfile
import time

import numpy as np

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []

FLOOR = 13
WINDOW_M = 10_000_000

_FAKE_SCANNER = """\
import sys
print("[*] sieving...", flush=True)
print("\\n[*] TOTAL PRIMES FOUND this run: 1,234,567 across 3 windows", flush=True)
print("[*] after the total line")
sys.exit(int(__file__.endswith("failing_scanner.py")))
"""


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _write(portal, target_idx, offsets):
    import prime_sieve_v1
    import storage_kinds
    from pgs2_vector import write_prime_window_offsets
    offset = target_idx * WINDOW_M
    path = storage_kinds.window_path(portal, FLOOR, offset, WINDOW_M,
                                     prime_sieve_v1.format_offset(offset))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_prime_window_offsets(path, 10 ** FLOOR + offset,
                               np.asarray(offsets, dtype=np.int64), generated_at=int(time.time()))


def _rows(portal):
    path = os.path.join(portal, "benchmark_log.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _run(orchestrator_v3, portal, fake_batch, window_count=4):
    os.environ["CONSTELLATION_PORTAL_DIR"] = portal
    real = orchestrator_v3.run_batch
    orchestrator_v3.run_batch = fake_batch
    captured = io.StringIO()
    saved_stdout = sys.stdout
    sys.stdout = captured
    try:
        ok = orchestrator_v3.run_orchestrator(
            base_exponent=FLOOR, window_count=window_count, start_auto=False, start_window=0,
            write_files=True, compute_sieving_primes_count=False, workers=2,
            batches_per_worker=1, window_m=WINDOW_M)
    finally:
        sys.stdout = saved_stdout
        orchestrator_v3.run_batch = real
    return ok, captured.getvalue()


def run_batch_case(orchestrator_v3):
    tmp = tempfile.mkdtemp(prefix="primeatlas_engine_totals_scanner_")
    try:
        scanner = os.path.join(tmp, "fake_scanner.py")
        with open(scanner, "w", encoding="utf-8") as f:
            f.write(_FAKE_SCANNER)
        raw = io.BytesIO()
        saved_stdout = sys.stdout
        wrapper = sys.stdout = io.TextIOWrapper(raw, encoding="utf-8")
        totals = []
        try:
            ok = orchestrator_v3.run_batch(scanner, FLOOR, 0, 2, 2, batches_per_worker=1,
                                           write_files=True, compute_sieving_primes_count=False,
                                           window_m=WINDOW_M, engine_totals=totals)
        finally:
            sys.stdout = saved_stdout
            wrapper.flush()
            wrapper.detach()
        out = raw.getvalue().decode("utf-8")
        check(ok is True, f"the scanner's exit code 0 -> True ({ok})")
        check(totals == [(1_234_567, 3)], f"the engine's total is picked up ({totals})")
        check("[*] sieving..." in out and "[*] after the total line" in out
              and "TOTAL PRIMES FOUND this run: 1,234,567 across 3 windows" in out,
              "the scanner's stdout is copied through unchanged")
        check(out.index("Launching batch") < out.index("[*] sieving..."),
              "the orchestrator's own lines keep their order around the scanner's")

        failing = os.path.join(tmp, "failing_scanner.py")
        shutil.copy(scanner, failing)
        totals = []
        sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        try:
            ok = orchestrator_v3.run_batch(failing, FLOOR, 0, 2, 2, batches_per_worker=1,
                                           write_files=True, compute_sieving_primes_count=False,
                                           window_m=WINDOW_M, engine_totals=totals)
        finally:
            sys.stdout = saved_stdout
        check(ok is False, f"a non-zero exit code -> False ({ok})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def orchestrator_cases(orchestrator_v3):
    # 1) every batch reports and the windows add up: the engine's count is logged (the
    # headers would give 2 per window)
    tmp = tempfile.mkdtemp(prefix="primeatlas_engine_totals_used_")
    try:
        reported = []

        def reporting_batch(_scanner, _floor, start, stop, *_a, engine_totals=None, **_k):
            for idx in range(start, stop + 1):
                _write(tmp, idx, [1, 3])
            reported.append((1000 + start, stop - start + 1))
            engine_totals.append(reported[-1])
            return True

        ok, out = _run(orchestrator_v3, tmp, reporting_batch, window_count=4)
        rows = _rows(tmp)
        expected = sum(primes for primes, _w in reported)
        check(ok is True and len(rows) == 1, f"one row ({len(rows)})")
        if rows:
            check(rows[0]["total_primes"] == str(expected) and rows[0]["windows_written"] == "4",
                  f"engine count logged ({rows[0]['total_primes']}, "
                  f"{rows[0]['windows_written']} windows; expected {expected}, 4)")
        check("Counting the primes of the written windows" not in out,
              "no header pass when the engine reported the run")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 2) no report line (a low-floor run reports floors): the headers are counted
    tmp = tempfile.mkdtemp(prefix="primeatlas_engine_totals_missing_")
    try:
        def silent_batch(_scanner, _floor, start, stop, *_a, engine_totals=None, **_k):
            for idx in range(start, stop + 1):
                _write(tmp, idx, [1, 3])
            return True

        ok, out = _run(orchestrator_v3, tmp, silent_batch, window_count=4)
        rows = _rows(tmp)
        check(rows and rows[0]["total_primes"] == "8",
              f"no report -> header count 8 "
              f"({rows[0]['total_primes'] if rows else None})")
        check("Counting the primes of the written windows" in out, "header pass ran")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 3) reported windows do not add up to the run: the headers are counted
    tmp = tempfile.mkdtemp(prefix="primeatlas_engine_totals_short_")
    try:
        def short_batch(_scanner, _floor, start, stop, *_a, engine_totals=None, **_k):
            for idx in range(start, stop + 1):
                _write(tmp, idx, [1, 3, 7])
            engine_totals.append((5, 1))
            return True

        ok, _out = _run(orchestrator_v3, tmp, short_batch, window_count=4)
        rows = _rows(tmp)
        check(rows and rows[0]["total_primes"] == "12",
              f"windows reported != run -> header count 12 "
              f"({rows[0]['total_primes'] if rows else None})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    import orchestrator_v3
    run_batch_case(orchestrator_v3)
    orchestrator_cases(orchestrator_v3)
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
