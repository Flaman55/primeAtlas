"""
test_run_guard.py -- primeatlas/generation/run_guard.py and prime_sieve/generation_stop.py:
the stage label of a job's output tail, the generation stop request, the active-run
marker, the scanner kill pattern per engine, window_integrity.repair_recent(), and the
recovery of an unfinished run on the next start (totals from new benchmark rows, or a
rescan plus cleanup of truncated windows written at most 60 s before the run's newest one
when the run logged nothing; marker kept while the process is still alive). Stage labels
include the constellation / k-tuple progress lines ("searching").

Pure logic, no tkinter, no WSL: is_alive and the floor rescan are injected.

Usage:
    python unitTests/test_run_guard.py
"""
import csv
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


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def stage_case():
    from primeatlas.generation.run_guard import job_stage
    check(job_stage([]) == ("idle", None), "empty tail -> idle")
    check(job_stage(["[+] Progress: 42.10% (421/1000 chunks) | time: 3.00s | ETA ~4s"])
          == ("sieving", "42.10%"), "pt1 progress line -> sieving 42.10%")
    check(job_stage(["[+] Progress: 7.50% (3/40 batches) | time: 1s"]) == ("sieving", "7.50%"),
          "v5 progress line -> sieving 7.50%")
    check(job_stage(["[*] Counting the primes of the written windows (100,000 headers, "
                     "24 threads)..."]) == ("counting", None),
          "counting line -> counting written windows")
    check(job_stage(["[*] D proves P for target_idx 0..9: equal=10"]) == ("verifying", None),
          "D proves P line -> verifying")
    check(job_stage(["[10:00:00] Launching batch target_idx 0..9 (10 windows)..."])
          == ("starting_batch", None), "launching line -> starting batch")
    mixed = ["[10:00:00] Launching batch target_idx 0..9 (10 windows)...",
             "[+] Progress: 99.00% (99/100 chunks) | time: 9s",
             "[*] Sieve + test 9.00s, unpack + write 1.00s",
             "[*] Counting the primes of the written windows (10 headers, 4 threads)...",
             "", "   "]
    check(job_stage(mixed) == ("counting", None),
          "mixed tail: the last matching line wins, blank lines ignored")
    check(job_stage(["[*] Counting the primes of the written windows (10 headers)...",
                     "[+] Progress: 5.00% (1/20 chunks) | time: 1s"]) == ("sieving", "5.00%"),
          "a progress line after a counting line -> sieving (last matching line wins)")
    const = "[CONSTELLATIONS v2] 12/40: PRIME_WINDOW_10p20_off_120M.bin -- 3 hit(s)"
    check(job_stage([const]) == ("searching", const),
          f"constellation progress line -> searching with the line ({job_stage([const])})")
    ktuple = "[KTUPLE SIEVE v2] batch 1, 5/100: base=123 candidates=7"
    check(job_stage([ktuple]) == ("searching", ktuple),
          f"k-tuple progress line -> searching with the line ({job_stage([ktuple])})")
    long_line = "x" * 200
    key, detail = job_stage(["something unrelated", long_line])
    check(key == "line" and detail == "x" * 80, "unknown last line -> line, cut to 80 chars")


def stop_request_case(tmp):
    import generation_stop
    from primeatlas.generation import run_guard
    check(not generation_stop.stop_requested(tmp), "no stop request in a fresh folder")
    check(run_guard.write_stop_request(tmp), "write_stop_request returns True")
    check(generation_stop.stop_requested(tmp), "stop request seen after writing it")
    check(generation_stop.stop_request_time(tmp) is not None, "stop request has a time")
    run_guard.clear_stop_request(tmp)
    check(not generation_stop.stop_requested(tmp), "stop request gone after clearing")
    run_guard.clear_stop_request(tmp)  # clearing twice is harmless
    check(not run_guard.write_stop_request(os.path.join(tmp, "missing", "dir")),
          "write_stop_request into an unreachable folder returns False")

    check(generation_stop.scanner_script("v5") == "prime_sieve_v5_2.py", "v5 scanner script (v5.2)")
    check(generation_stop.scanner_script("v6") == "prime_sieve_v6_1.py",
          "v6 scanner script is v6.1's (v6.0's prime_sieve_v6.py stays for comparison)")
    check(generation_stop.scanner_script("pt1") == "prime_sieve_pt1.py", "pt1 scanner script")
    check(generation_stop.scanner_script("v4.1") == "prime_sieve_v4_1.py", "v4.1 scanner script")
    import orchestrator_v3
    check(orchestrator_v3.SCRIPT_NAME == generation_stop.scanner_script(
        orchestrator_v3.SCANNER_VERSION), "orchestrator SCRIPT_NAME comes from the same map")
    if orchestrator_v3.SCANNER_VERSION == "v6":
        check(orchestrator_v3.prime_sieve_module.VERSION == "v6.1",
              "the v6 engine logs engine_version v6.1")


def marker_case(tmp):
    from primeatlas.generation import run_guard
    check(run_guard.read_active_run(tmp) is None, "no marker in a fresh folder")
    info = {"base_exponent": 25, "engine": "pt1", "kill_pattern": "orchestrator_v3.py"}
    run_guard.write_active_run(tmp, info)
    back = run_guard.read_active_run(tmp)
    check(back is not None and back["base_exponent"] == 25 and back["engine"] == "pt1",
          "marker reads back what was written")
    run_guard.clear_active_run(tmp)
    check(run_guard.read_active_run(tmp) is None, "marker gone after clearing")
    path = run_guard.active_run_path(tmp)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    check(run_guard.read_active_run(tmp) is None, "corrupt marker reads as None")
    run_guard.clear_active_run(tmp)


def _write_window(portal, floor, target_idx, window_m, offsets, generated_at, kind="D"):
    import storage_kinds
    import prime_sieve_v1
    from pgs2_vector import write_prime_window_offsets
    offset = target_idx * window_m
    path = storage_kinds.window_path(portal, floor, offset, window_m,
                                     prime_sieve_v1.format_offset(offset), kind)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_prime_window_offsets(path, 10 ** floor + offset, np.asarray(offsets, dtype=np.int64),
                               generated_at=generated_at)
    return path


def _truncate(path):
    with open(path, "rb") as f:
        data = f.read()
    with open(path, "wb") as f:
        f.write(data[:len(data) - 1])


def repair_case(tmp):
    import window_integrity
    floor, window_m = 13, 10_000_000
    now = int(time.time())
    old = _write_window(tmp, floor, 0, window_m, [1, 3, 7], now - 3600)
    old_cut = _write_window(tmp, floor, 1, window_m, [1, 3, 7], now - 3600)
    _truncate(old_cut)  # outside the window: not even read in full
    fresh = _write_window(tmp, floor, 2, window_m, [1, 3, 7, 9], now - 5)
    fresh_cut = _write_window(tmp, floor, 3, window_m, [1, 3, 7, 9, 13], now - 1)
    _truncate(fresh_cut)
    deleted = window_integrity.repair_recent([old, old_cut, fresh, fresh_cut],
                                             reference_time=now, window_seconds=60)
    check(deleted == [fresh_cut], f"repair_recent deletes only the recent truncated window "
                                  f"(deleted {len(deleted)})")
    check(os.path.exists(old) and os.path.exists(fresh) and os.path.exists(old_cut)
          and not os.path.exists(fresh_cut), "complete and old windows are kept")

    # reference_time None: relative to the newest generated_at among the readable headers
    cut2 = _write_window(tmp, floor, 4, window_m, [1, 3], now)
    with open(cut2, "rb") as f:
        data = f.read()
    with open(cut2, "wb") as f:
        f.write(data[:6])  # header cut: does not parse at all
    deleted = window_integrity.repair_recent([old, fresh, cut2], reference_time=None)
    check(deleted == [cut2], "a window whose header does not parse is deleted")


def _write_benchmark_rows(portal, rows):
    import orchestrator_v3
    path = os.path.join(portal, "benchmark_log.csv")
    is_new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=orchestrator_v3.BENCHMARK_FIELDNAMES)
        if is_new:
            w.writeheader()
        for row in rows:
            w.writerow(row)


def recovery_case():
    from primeatlas.generation import run_guard
    from primeatlas.core import storage
    floor, window_m = 13, 10_000_000

    # a) process still alive: marker kept, nothing touched
    tmp = tempfile.mkdtemp(prefix="primeatlas_run_guard_alive_")
    try:
        run_guard.write_active_run(tmp, {"base_exponent": floor, "engine": "v5",
                                          "kill_pattern": "orchestrator_v3.py",
                                          "rows_before": 0, "first_target_idx": 0,
                                          "window_m": window_m, "started_at": time.time()})
        result = run_guard.recover_unfinished_run(tmp, is_alive=lambda pattern: True,
                                                  rescan_floor=lambda p, f: None)
        check(result["status"] == "alive", f"live process -> status alive ({result['status']})")
        check(run_guard.read_active_run(tmp) is not None, "live process -> marker kept")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # b) no marker
    tmp = tempfile.mkdtemp(prefix="primeatlas_run_guard_none_")
    try:
        result = run_guard.recover_unfinished_run(tmp, is_alive=lambda pattern: False,
                                                  rescan_floor=lambda p, f: None)
        check(result["status"] == "none", "no marker -> status none")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # c) process gone, the run logged a row after the GUI closed: totals bumped from it
    tmp = tempfile.mkdtemp(prefix="primeatlas_run_guard_row_")
    try:
        _write_benchmark_rows(tmp, [{"base_exponent": 12, "windows_written": 1,
                                     "total_primes": 5, "write_files": "1", "engine": "v5",
                                     "bytes_written": 40}])
        logs = os.path.join(tmp, ".generation_logs")
        os.makedirs(logs)
        log_path, exit_path = os.path.join(logs, "loop_1.log"), os.path.join(logs, "loop_1.exit")
        for p in (log_path, exit_path):
            with open(p, "w") as f:
                f.write("0\n")
        run_guard.write_stop_request(tmp)
        run_guard.write_active_run(tmp, {"base_exponent": floor, "engine": "v5",
                                          "kill_pattern": "orchestrator_v3.py",
                                          "rows_before": 1, "first_target_idx": 0,
                                          "window_m": window_m, "started_at": time.time(),
                                          "log_path": log_path, "exit_path": exit_path})
        _write_benchmark_rows(tmp, [{"base_exponent": floor, "windows_written": 3,
                                     "total_primes": 1234, "write_files": "1", "engine": "v5",
                                     "bytes_written": 999, "run_status": "completed"}])
        rescans = []
        result = run_guard.recover_unfinished_run(
            tmp, is_alive=lambda pattern: False,
            rescan_floor=lambda p, f: rescans.append(f))
        cache = storage.load_totals_cache(tmp)
        entry = cache.get(f"10p{floor}", {})
        check(result["status"] == "recovered" and result["bumped_rows"] == 1,
              f"gone + new row -> recovered, 1 row bumped ({result})")
        check(entry.get("total") == 1234, f"floor total bumped by the new row ({entry})")
        check(rescans == [], "a logged row needs no rescan")
        check(not os.path.exists(log_path) and not os.path.exists(exit_path),
              "leftover log/exit files deleted")
        import generation_stop
        check(not generation_stop.stop_requested(tmp), "leftover stop request deleted")
        check(run_guard.read_active_run(tmp) is None, "marker deleted after recovery")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # d) process gone, no row (hard-killed orchestrator): truncated windows deleted, rescan
    tmp = tempfile.mkdtemp(prefix="primeatlas_run_guard_rescan_")
    try:
        started = int(time.time()) - 100
        before = _write_window(tmp, floor, 0, window_m, [1, 3], started - 3600)
        kept = _write_window(tmp, floor, 1, window_m, [1, 3, 7], started + 10)
        cut = _write_window(tmp, floor, 2, window_m, [1, 3, 7, 9], started + 20)
        _truncate(cut)
        run_guard.write_active_run(tmp, {"base_exponent": floor, "engine": "v5",
                                          "kill_pattern": "orchestrator_v3.py",
                                          "rows_before": 0, "first_target_idx": 1,
                                          "window_m": window_m, "started_at": started})
        rescans = []
        result = run_guard.recover_unfinished_run(
            tmp, is_alive=lambda pattern: False,
            rescan_floor=lambda p, f: rescans.append(f))
        check(result["status"] == "recovered" and result["bumped_rows"] == 0,
              f"gone + no row -> recovered without rows ({result})")
        check(result["deleted_windows"] == [cut], "truncated window of the run deleted")
        check(os.path.exists(before) and os.path.exists(kept), "complete windows kept")
        check(rescans == [floor], f"floor rescanned ({rescans})")
        check(run_guard.read_active_run(tmp) is None, "marker deleted after recovery")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # e) criterion 9: only windows written at most 60 s before the run's newest window are
    # read; a cut one among them is deleted, older windows are not read
    tmp = tempfile.mkdtemp(prefix="primeatlas_run_guard_early_cut_")
    try:
        started = int(time.time()) - 1000
        early_cut = _write_window(tmp, floor, 1, window_m, [1, 3, 7], started + 10)
        _truncate(early_cut)
        late_cut = _write_window(tmp, floor, 3, window_m, [1, 3, 7, 9], started + 870)
        _truncate(late_cut)
        newest = _write_window(tmp, floor, 2, window_m, [1, 3], started + 900)
        run_guard.write_active_run(tmp, {"base_exponent": floor, "engine": "v5",
                                          "kill_pattern": "orchestrator_v3.py",
                                          "rows_before": 0, "first_target_idx": 1,
                                          "window_m": window_m, "started_at": started})
        result = run_guard.recover_unfinished_run(tmp, is_alive=lambda pattern: False,
                                                  rescan_floor=lambda p, f: None)
        check(not os.path.exists(late_cut) and result["deleted_windows"] == [late_cut],
              f"truncated window 30 s before the newest deleted ({result['deleted_windows']})")
        check(os.path.exists(early_cut), "window 890 s before the newest is not read")
        check(os.path.exists(newest), "complete window of the run kept")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # f) the app's real floor rescan adds the totals of the windows kept
    tmp = tempfile.mkdtemp(prefix="primeatlas_run_guard_real_rescan_")
    try:
        started = int(time.time()) - 100
        _write_window(tmp, floor, 0, window_m, [1, 3, 7], started + 10)
        _write_window(tmp, floor, 1, window_m, [1, 3], started + 20)
        cut = _write_window(tmp, floor, 2, window_m, [1, 3, 7, 9], started + 30)
        _truncate(cut)
        run_guard.write_active_run(tmp, {"base_exponent": floor, "engine": "v5",
                                          "kill_pattern": "orchestrator_v3.py",
                                          "rows_before": 0, "first_target_idx": 0,
                                          "window_m": window_m, "started_at": started})
        run_guard.recover_unfinished_run(tmp, is_alive=lambda pattern: False,
                                         rescan_floor=run_guard.rescan_floor_totals)
        entry = storage.load_totals_cache(tmp).get(f"10p{floor}", {})
        check(entry.get("total") == 5 and entry.get("file_count") == 2,
              f"real rescan: floor total = primes of the kept windows ({entry.get('total')}, "
              f"{entry.get('file_count')} files)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    stage_case()
    tmp = tempfile.mkdtemp(prefix="primeatlas_run_guard_test_")
    try:
        stop_request_case(tmp)
        marker_case(tmp)
        repair_case(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    recovery_case()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
