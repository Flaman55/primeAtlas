"""
test_orchestrator_verify_after_run.py -- the run row of a pt1 run with the verification
P -> D after it (orchestrator_v3.py, run_verify.py) and the loop's tagging of the rows next
to it (orchestrator_loop_v2._tag_benchmark_rows_by_range()).

A. Ticked, the verification follows the run before its row is logged: the pt1 row carries
   the verification's time in proof_seconds, part of total_seconds; the verifier gets the
   run's own target_idx range; the summary prints the run speed without and with the
   verification and the speed it costs.
B. A verification that fails: the orchestrator returns False, the row still carries the time
   the verification took.
C. Unticked, a failed batch, a stop request: no verification, no proof_seconds.
D. The loop stamps its session time on the pipeline's rows only: a store verification row of
   the same target_idx range keeps its own times, loop columns blank.

run_batch and verify_run are replaced by fakes (windows written the way a scanner does, a
verifier that sleeps), so no WSL or real engine is needed.

Usage:
    python unitTests/test_orchestrator_verify_after_run.py
"""
import contextlib
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
PROOF_SLEEP = 0.3


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _write(portal, target_idx):
    import storage_kinds
    import prime_sieve_v1
    from pgs2_vector import write_prime_window_offsets
    offset = target_idx * WINDOW_M
    path = storage_kinds.window_path(portal, FLOOR, offset, WINDOW_M,
                                     prime_sieve_v1.format_offset(offset))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_prime_window_offsets(path, 10 ** FLOOR + offset, np.asarray([1, 3], dtype=np.int64),
                               generated_at=int(time.time()))


def _rows(portal):
    path = os.path.join(portal, "benchmark_log.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _done_batch(portal):
    def batch(_scanner, _floor, start, stop, *_a, **_k):
        import json
        import orchestrator_v3
        for idx in range(start, stop + 1):
            _write(portal, idx)
        handoff = os.path.join(portal, orchestrator_v3.prime_sieve_module.SCAN_METRICS_FILENAME)
        with open(handoff, "w", encoding="utf-8") as f:
            json.dump({"numbers_processed": (stop - start + 1) * WINDOW_M}, f)
        return True
    return batch


def _failed_batch(*_a, **_k):
    return False


def _run(orch, portal, env, batch, verify_result=True):
    """run_orchestrator() of a pt1 run over target_idx 0..1: (rc, output, verifier calls)."""
    calls = []

    def fake_verify(*args):
        calls.append(args)
        print("FAKE VERIFY")
        time.sleep(PROOF_SLEEP)
        return verify_result

    saved = (orch.run_batch, orch.verify_run, orch.SCANNER_VERSION, dict(os.environ))
    orch.run_batch, orch.verify_run, orch.SCANNER_VERSION = batch, fake_verify, "pt1"
    os.environ["CONSTELLATION_PORTAL_DIR"] = portal
    for key in ("PRIMEATLAS_PT1_VERIFY", "PRIMEATLAS_VERIFY_METHOD"):
        os.environ.pop(key, None)
    os.environ.update(env)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            rc = orch.run_orchestrator(
                base_exponent=FLOOR, window_count=2, start_auto=False, start_window=0,
                write_files=True, compute_sieving_primes_count=False, workers=2,
                batches_per_worker=1, window_m=WINDOW_M)
    finally:
        orch.run_batch, orch.verify_run, orch.SCANNER_VERSION = saved[:3]
        os.environ.clear()
        os.environ.update(saved[3])
    return rc, out.getvalue(), calls


def _float(row, key):
    try:
        return float(row.get(key) or "")
    except ValueError:
        return None


def part_a(orch):
    tmp = tempfile.mkdtemp(prefix="primeatlas_verify_after_")
    try:
        rc, out, calls = _run(orch, tmp, {"PRIMEATLAS_PT1_VERIFY": "1",
                                          "PRIMEATLAS_VERIFY_METHOD": "sieve"}, _done_batch(tmp))
        rows = _rows(tmp)
        check(rc is True, "A: ticked run returns True")
        check(len(calls) == 1 and calls[0][2:4] == (0, 1) and calls[0][6] == "sieve",
              f"A: the verifier gets the run's range 0..1 and the method ({calls})")
        row = rows[0] if len(rows) == 1 else {}
        proof, total = _float(row, "proof_seconds"), _float(row, "total_seconds")
        check(proof is not None and PROOF_SLEEP <= proof < PROOF_SLEEP + 1.0,
              f"A: proof_seconds holds the verification time ({row.get('proof_seconds')})")
        check(proof is not None and total is not None and total >= proof,
              f"A: total_seconds includes it ({total} >= {proof})")
        check(row.get("engine") == "pt1" and row.get("windows_written") == "2",
              "A: one pt1 row of the run's two windows")
        lines = [line for line in out.splitlines() if "without the verification" in line]
        check(len(lines) == 1 and "with it" in lines[0] and "n/s slower" in lines[0],
              f"A: the summary names both speeds and the speed it costs ({lines})")
        check("FAKE VERIFY" in out and "[BENCHMARK] total time" in out
              and out.index("FAKE VERIFY") < out.index("[BENCHMARK] total time"),
              "A: the verification runs before the summary")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def part_b(orch):
    tmp = tempfile.mkdtemp(prefix="primeatlas_verify_after_")
    try:
        rc, _out, calls = _run(orch, tmp, {"PRIMEATLAS_PT1_VERIFY": "1"}, _done_batch(tmp),
                               verify_result=False)
        rows = _rows(tmp)
        check(rc is False and len(calls) == 1, "B: a failed verification returns False")
        check(len(rows) == 1 and (_float(rows[0], "proof_seconds") or 0) >= PROOF_SLEEP,
              "B: the row still carries the verification's time")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def part_c(orch):
    import generation_stop
    for name, env, batch_of, stop in (
            ("unticked", {}, _done_batch, False),
            ("failed batch", {"PRIMEATLAS_PT1_VERIFY": "1"}, lambda _p: _failed_batch, False),
            ("stop request", {"PRIMEATLAS_PT1_VERIFY": "1"}, _done_batch, True)):
        tmp = tempfile.mkdtemp(prefix="primeatlas_verify_after_")
        try:
            if stop:
                with open(generation_stop.stop_request_path(tmp), "w") as f:
                    f.write("stop")
            _rc, _out, calls = _run(orch, tmp, env, batch_of(tmp))
            rows = _rows(tmp)
            check(not calls and all(not r.get("proof_seconds") for r in rows),
                  f"C: {name}: no verification, no proof_seconds ({len(rows)} rows)")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def part_d():
    import orchestrator_loop_v2 as loop
    import benchmark_log_schema as schema
    tmp = tempfile.mkdtemp(prefix="primeatlas_verify_after_")
    try:
        path = os.path.join(tmp, "benchmark_log.csv")
        base = {name: "" for name in schema.BENCHMARK_FIELDNAMES}
        rows = [dict(base, engine="pt1", target_idx_start="0", target_idx_end="1",
                     total_seconds="10.000"),
                dict(base, engine=schema.ENGINE_V73_VERIFY, target_idx_start="0",
                     target_idx_end="1", total_seconds="3.000", verify_seconds="2.500"),
                dict(base, engine=schema.ENGINE_PT1_VERIFY, target_idx_start="0",
                     target_idx_end="1", total_seconds="4.000", verify_seconds="3.500")]
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=schema.BENCHMARK_FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)
        loop._tag_benchmark_rows_by_range(tmp, 0, [(0, 2)], 14.0, window_m=WINDOW_M)
        pipe, v73, pt1v = _rows(tmp)
        check(pipe["loop_session_seconds"] == "14.000" and pipe["instance_of_n"] == "1/1",
              "D: the pipeline row gets the session time")
        for name, row in (("v73_verify", v73), ("pt1_verify", pt1v)):
            check(not row["loop_session_seconds"] and not row["loop_numbers_per_second"]
                  and not row["instance_of_n"],
                  f"D: the {name} row of the same range keeps its own times")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    import orchestrator_v3
    part_a(orchestrator_v3)
    part_b(orchestrator_v3)
    part_c(orchestrator_v3)
    part_d()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
