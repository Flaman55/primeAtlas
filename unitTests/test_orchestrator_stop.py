"""
test_orchestrator_stop.py -- orchestrator_v3.run_orchestrator()'s stop-on-request path
(CLOSE_GUARD_PLAN.md section 3): a batch that fails while GENERATION_STOP_REQUEST.txt
exists is a stop, not an error -- rc True, the window cut by the scanner kill deleted, one
benchmark row with run_status=stopped over the windows that exist (counts and bytes from
their headers, no stale scanner handoff metrics). Without the request a failed batch stays
an error (False, no row). A completed batch logs run_status=completed, and the schema
migration adds run_status to an existing log without changing its old rows. The Storage
times and the Benchmark chart functions read a stopped row like a completed one, and
orchestrator_loop_v2._run_loop starts no iteration while the stop request exists.

run_batch is replaced by a fake that writes PGS2 windows the way a scanner does, so no
WSL or real engine is needed.

Usage:
    python unitTests/test_orchestrator_stop.py
"""
import csv
import json
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


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _window_path(portal, target_idx):
    import storage_kinds
    import prime_sieve_v1
    offset = target_idx * WINDOW_M
    return storage_kinds.window_path(portal, FLOOR, offset, WINDOW_M,
                                     prime_sieve_v1.format_offset(offset))


def _write(portal, target_idx, offsets):
    from pgs2_vector import write_prime_window_offsets
    path = _window_path(portal, target_idx)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_prime_window_offsets(path, 10 ** FLOOR + target_idx * WINDOW_M,
                               np.asarray(offsets, dtype=np.int64), generated_at=int(time.time()))
    return path


def _rows(portal):
    path = os.path.join(portal, "benchmark_log.csv")
    if not os.path.exists(path):
        return None, []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def _run(orchestrator_v3, portal, fake_batch, window_count=4):
    os.environ["CONSTELLATION_PORTAL_DIR"] = portal
    real = orchestrator_v3.run_batch
    orchestrator_v3.run_batch = fake_batch
    try:
        return orchestrator_v3.run_orchestrator(
            base_exponent=FLOOR, window_count=window_count, start_auto=False, start_window=0,
            write_files=True, compute_sieving_primes_count=False, workers=2,
            batches_per_worker=1, window_m=WINDOW_M)
    finally:
        orchestrator_v3.run_batch = real


def _run_loop(portal, on_iteration, run_count=3):
    """orchestrator_loop_v2.main() with run_iteration replaced; returns (iterations, rc)."""
    import orchestrator_loop_v2 as loop
    calls = []

    def fake_iteration(_floor, start_idx, *_a, **_k):
        calls.append(start_idx)
        on_iteration(len(calls))
        return start_idx + 10, True, []

    saved = (loop.run_iteration, loop.PORTAL_FOLDER, loop.orch.find_auto_start,
             loop._tag_benchmark_rows_by_range, sys.argv)
    loop.run_iteration = fake_iteration
    loop.PORTAL_FOLDER = portal
    loop.orch.find_auto_start = lambda *a, **k: None
    loop._tag_benchmark_rows_by_range = lambda *a, **k: None
    sys.argv = ["orchestrator_loop_v2.py", str(FLOOR), str(run_count), "1"]
    rc = None
    try:
        loop.main()
    except SystemExit as exc:
        rc = exc.code
    finally:
        (loop.run_iteration, loop.PORTAL_FOLDER, loop.orch.find_auto_start,
         loop._tag_benchmark_rows_by_range, sys.argv) = saved
    return len(calls), rc


def loop_case():
    """orchestrator_loop_v2 starts no new iteration while the stop request exists."""
    import generation_stop

    def request(portal):
        with open(generation_stop.stop_request_path(portal), "w", encoding="utf-8") as f:
            f.write("stop\n")

    tmp = tempfile.mkdtemp(prefix="primeatlas_loop_stop_")
    try:
        n, rc = _run_loop(tmp, lambda i: request(tmp) if i == 1 else None)
        check(n == 1, f"stop during iteration 1 of 3 -> no further iteration ({n} run)")
        check(rc in (0, None), f"a stopped loop exits 0 ({rc})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp(prefix="primeatlas_loop_stop_before_")
    try:
        request(tmp)
        n, _rc = _run_loop(tmp, lambda i: None)
        check(n == 0, f"stop request before the first iteration -> no iteration ({n} run)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp(prefix="primeatlas_loop_no_stop_")
    try:
        n, rc = _run_loop(tmp, lambda i: None)
        check(n == 3 and rc in (0, None), f"no stop request -> all 3 iterations ({n}, rc {rc})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    import orchestrator_v3
    import generation_stop
    check("run_status" in orchestrator_v3.BENCHMARK_FIELDNAMES,
          "benchmark schema has a run_status column")

    # 1) stop on request: two complete windows, the third cut by the kill
    tmp = tempfile.mkdtemp(prefix="primeatlas_orch_stop_")
    try:
        with open(os.path.join(tmp, orchestrator_v3.prime_sieve_module.SCAN_METRICS_FILENAME),
                  "w", encoding="utf-8") as f:
            json.dump({"sieve_seconds": 123.0, "write_seconds": 4.0,
                       "total_primes_found": 999999}, f)  # stale, from an earlier run
        kept = []

        def stopped_batch(*_a, **_k):
            kept.append(_write(tmp, 0, [1, 3, 7]))
            kept.append(_write(tmp, 1, [3, 9]))
            cut = _write(tmp, 2, [1, 3, 7, 9, 13, 19])
            with open(cut, "rb") as f:
                data = f.read()
            with open(cut, "wb") as f:
                f.write(data[:-2])
            with open(generation_stop.stop_request_path(tmp), "w", encoding="utf-8") as f:
                f.write("stop\n")
            return False

        ok = _run(orchestrator_v3, tmp, stopped_batch)
        check(ok is True, f"stop on request -> run_orchestrator returns True ({ok})")
        check(not os.path.exists(_window_path(tmp, 2)), "the window cut by the kill is deleted")
        check(all(os.path.exists(p) for p in kept), "complete windows are kept")
        _fields, rows = _rows(tmp)
        check(len(rows) == 1, f"one benchmark row ({len(rows)})")
        if rows:
            row = rows[0]
            check(row["run_status"] == "stopped", f"run_status stopped ({row['run_status']!r})")
            check(row["windows_written"] == "2" and row["total_primes"] == "5",
                  f"counts of the kept windows (windows {row['windows_written']}, "
                  f"primes {row['total_primes']})")
            size = sum(os.path.getsize(p) for p in kept)
            check(row["bytes_written"] == str(size),
                  f"bytes from the kept windows ({row['bytes_written']} vs {size})")
            check(row["sieve_seconds"] == "" and row["write_seconds"] == "",
                  "no stale handoff metrics in a stopped row")
            # criterion 10: Benchmark charts and Storage times read a stopped row like a
            # completed one
            from primeatlas.core.storage import aggregate_write_seconds_by_floor
            from primeatlas.benchmark import benchmark
            check(FLOOR in aggregate_write_seconds_by_floor(rows),
                  f"Storage times count the stopped row (write_files={row['write_files']!r}, "
                  f"total_seconds={row['total_seconds']!r})")
            completed = dict(row, run_status="completed")
            for name in ("aggregate_benchmark_growth", "aggregate_benchmark_fair_spw",
                         "aggregate_benchmark_sieve_nps", "aggregate_benchmark_write_mbps",
                         "benchmark_row_stats"):
                fn = getattr(benchmark, name)
                check(fn([row]) == fn([completed]),
                      f"{name} reads a stopped row like a completed one")
            grouped = {k: len(v) for k, v in benchmark.group_benchmark_rows_by_floor([row]).items()}
            check(grouped == {k: len(v) for k, v in
                              benchmark.group_benchmark_rows_by_floor([completed]).items()},
                  "group_benchmark_rows_by_floor groups a stopped row like a completed one")
            check(benchmark.benchmark_row_kind(row) == benchmark.benchmark_row_kind(completed),
                  "benchmark_row_kind of a stopped row = of a completed one")
        check(generation_stop.stop_requested(tmp),
              "the orchestrator leaves the stop request for the GUI to delete")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 2) stop on request before any window: no row
    tmp = tempfile.mkdtemp(prefix="primeatlas_orch_stop_empty_")
    try:
        def empty_batch(*_a, **_k):
            with open(generation_stop.stop_request_path(tmp), "w", encoding="utf-8") as f:
                f.write("stop\n")
            return False

        ok = _run(orchestrator_v3, tmp, empty_batch)
        check(ok is True, "stop before any window -> True")
        check(_rows(tmp)[1] == [], "stop before any window -> no row")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 2b) stop request already there before the first batch (Stop before the scanner
    # started, so pkill found nothing): no batch is launched
    tmp = tempfile.mkdtemp(prefix="primeatlas_orch_stop_before_")
    try:
        with open(generation_stop.stop_request_path(tmp), "w", encoding="utf-8") as f:
            f.write("stop\n")
        launched = []

        def recording_batch(*_a, **_k):
            launched.append(1)
            return True

        ok = _run(orchestrator_v3, tmp, recording_batch)
        check(ok is True and launched == [], f"request before the first batch -> no batch "
                                              f"launched ({len(launched)}), True")
        check(_rows(tmp)[1] == [], "request before the first batch -> no row")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 3) failed batch without a stop request: error as before
    tmp = tempfile.mkdtemp(prefix="primeatlas_orch_error_")
    try:
        def failed_batch(*_a, **_k):
            _write(tmp, 0, [1, 3])
            return False

        ok = _run(orchestrator_v3, tmp, failed_batch)
        check(ok is False, "failed batch without a request -> False")
        check(_rows(tmp)[1] == [], "failed batch without a request -> no row")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 4) completed batch + schema migration of an older log
    tmp = tempfile.mkdtemp(prefix="primeatlas_orch_done_")
    try:
        old_fields = [f for f in orchestrator_v3.BENCHMARK_FIELDNAMES if f != "run_status"]
        with open(os.path.join(tmp, "benchmark_log.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=old_fields)
            w.writeheader()
            w.writerow({"base_exponent": "12", "windows_written": "7", "total_primes": "70",
                        "write_files": "1"})

        def done_batch(_scanner, _floor, start, stop, *_a, **_k):
            for idx in range(start, stop + 1):
                _write(tmp, idx, [1, 3])
            return True

        ok = _run(orchestrator_v3, tmp, done_batch, window_count=2)
        check(ok is True, "completed batch -> True")
        fields, rows = _rows(tmp)
        check(fields == orchestrator_v3.BENCHMARK_FIELDNAMES, "old log migrated to the new header")
        check(len(rows) == 2 and rows[0]["run_status"] == "" and rows[0]["total_primes"] == "70",
              "old row unchanged, run_status blank")
        check(len(rows) == 2 and rows[1]["run_status"] == "completed",
              "completed run logs run_status=completed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    loop_case()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
