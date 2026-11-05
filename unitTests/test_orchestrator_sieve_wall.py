"""
test_orchestrator_sieve_wall.py -- orchestrator_v3 times the sieve from outside the scanner.

sieve_wall_seconds is the time from launching the scanner process to its "Batch sieve done"
line, taken in the orchestrator process as the line arrives on the scanner's stdout; the
scanner's own code, arguments and output stay as they are.

A. run_batch(): the scanner gets the same argv as before and PYTHONUNBUFFERED=1 in its
   environment, so a scanner that does not flush that line still delivers it when printed;
   the time is taken when the line arrives (a scanner sleeping after the line does not add
   to it), for written and count-only runs alike; a scanner without the line (pt1) adds
   nothing; the scanner's stdout is copied through unchanged.
B. run_orchestrator(): the row's sieve_wall_seconds is the batches' sum minus the
   scanner's base_gen_seconds (the optional pi(L_final) diagnostic, not sieving work);
   blank when a batch had no line; count-only runs log it too.

Usage:
    python unitTests/test_orchestrator_sieve_wall.py
"""
import csv
import io
import json
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []

FLOOR = 13
WINDOW_M = 10_000_000

# No flush on the sieve line, as in v4.1 and v5: it reaches the pipe only unbuffered.
_FAKE_SCANNER = """\
import json, os, sys, time
with open(sys.argv[0] + ".seen.json", "w") as f:
    json.dump({"argv": sys.argv[1:], "unbuffered": os.environ.get("PYTHONUNBUFFERED")}, f)
time.sleep(0.3)
print("\\n[*] Batch sieve done in 0.30s. Unpacking result and writing windows...")
time.sleep(0.6)
print("[*] TOTAL PRIMES FOUND this run: 12 across 3 windows")
"""

_SILENT_SCANNER = """\
print("[*] TOTAL PRIMES FOUND this run: 12 across 3 windows")
"""


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _quiet_batch(orchestrator_v3, scanner, write_files, sieve_walls):
    raw = io.BytesIO()
    saved_stdout = sys.stdout
    wrapper = sys.stdout = io.TextIOWrapper(raw, encoding="utf-8")
    try:
        ok = orchestrator_v3.run_batch(scanner, FLOOR, 0, 2, 2, batches_per_worker=1,
                                       write_files=write_files,
                                       compute_sieving_primes_count=False, window_m=WINDOW_M,
                                       engine_totals=[] if write_files else None,
                                       sieve_walls=sieve_walls)
    finally:
        sys.stdout = saved_stdout
        wrapper.flush()
        wrapper.detach()
    return ok, raw.getvalue().decode("utf-8")


def run_batch_cases(orchestrator_v3):
    print("\n--- A. run_batch() ---")
    tmp = tempfile.mkdtemp(prefix="primeatlas_sieve_wall_scanner_")
    try:
        scanner = os.path.join(tmp, "fake_scanner.py")
        with open(scanner, "w", encoding="utf-8") as f:
            f.write(_FAKE_SCANNER)
        for write_files in (True, False):
            walls = []
            ok, out = _quiet_batch(orchestrator_v3, scanner, write_files, walls)
            with open(scanner + ".seen.json") as f:
                seen = json.load(f)
            check(ok is True, f"write_files={write_files}: exit code 0 -> True")
            check(seen["argv"] == [str(FLOOR), "0", "2", "2", "1", "1" if write_files else "0",
                                   "0", str(WINDOW_M)],
                  f"write_files={write_files}: scanner argv unchanged ({seen['argv']})")
            check(seen["unbuffered"] == "1",
                  f"write_files={write_files}: scanner runs with PYTHONUNBUFFERED=1")
            check(len(walls) == 1 and 0.3 <= walls[0] < 0.85,
                  f"write_files={write_files}: time taken at the sieve line, not at exit "
                  f"({walls})")
            check("Batch sieve done in 0.30s" in out and "TOTAL PRIMES FOUND" in out,
                  f"write_files={write_files}: scanner stdout copied through")

        silent = os.path.join(tmp, "silent_scanner.py")
        with open(silent, "w", encoding="utf-8") as f:
            f.write(_SILENT_SCANNER)
        walls = []
        ok, _out = _quiet_batch(orchestrator_v3, silent, True, walls)
        check(ok is True and walls == [], f"no sieve line -> nothing appended ({walls})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _rows(portal):
    path = os.path.join(portal, "benchmark_log.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _run(orchestrator_v3, portal, fake_batch, write_files):
    os.environ["CONSTELLATION_PORTAL_DIR"] = portal
    real = orchestrator_v3.run_batch
    real_summary_reader = orchestrator_v3.read_scan_metrics_handoff
    orchestrator_v3.run_batch = fake_batch
    saved_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        return orchestrator_v3.run_orchestrator(
            base_exponent=FLOOR, window_count=3, start_auto=False, start_window=0,
            write_files=write_files, compute_sieving_primes_count=False, workers=2,
            batches_per_worker=1, window_m=WINDOW_M)
    finally:
        sys.stdout = saved_stdout
        orchestrator_v3.run_batch = real
        orchestrator_v3.read_scan_metrics_handoff = real_summary_reader


def _handoff(portal, orchestrator_v3, **metrics):
    path = os.path.join(portal, orchestrator_v3.prime_sieve_module.SCAN_METRICS_FILENAME)
    metrics.setdefault("total_primes_found", 12)
    metrics.setdefault("windows_processed", 3)
    metrics.setdefault("numbers_processed", 3 * WINDOW_M)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metrics, f)


def orchestrator_cases(orchestrator_v3):
    print("\n--- B. run_orchestrator() logs sieve_wall_seconds ---")
    for write_files in (False, True):
        tmp = tempfile.mkdtemp(prefix="primeatlas_sieve_wall_row_")
        try:
            def timed_batch(_s, _f, start, stop, *_a, engine_totals=None, sieve_walls=None,
                            **_k):
                _handoff(tmp, orchestrator_v3, sieve_seconds=1.0, base_gen_seconds=0.2)
                sieve_walls.append(1.7)
                if engine_totals is not None:
                    engine_totals.append((12, stop - start + 1))
                return True

            _run(orchestrator_v3, tmp, timed_batch, write_files)
            rows = _rows(tmp)
            check(len(rows) == 1 and rows[0].get("sieve_wall_seconds") == "1.500",
                  f"write_files={write_files}: launch-to-sieve-line minus base-gen "
                  f"({rows[0].get('sieve_wall_seconds') if rows else None})")
            if rows:
                check(rows[0]["sieve_seconds"] == "1.000",
                      "the engine's own sieve_seconds is logged unchanged")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp(prefix="primeatlas_sieve_wall_blank_")
    try:
        def lineless_batch(_s, _f, start, stop, *_a, engine_totals=None, sieve_walls=None,
                           **_k):
            _handoff(tmp, orchestrator_v3, sieve_seconds=1.0)
            return True

        _run(orchestrator_v3, tmp, lineless_batch, False)
        rows = _rows(tmp)
        check(len(rows) == 1 and rows[0].get("sieve_wall_seconds") == "",
              f"no sieve line (pt1) -> blank "
              f"({rows[0].get('sieve_wall_seconds') if rows else None})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    import orchestrator_v3
    run_batch_cases(orchestrator_v3)
    orchestrator_cases(orchestrator_v3)
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
