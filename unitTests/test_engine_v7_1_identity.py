"""WSL test: prime_sieve_v7_1.py produces exactly what prime_sieve_v6_1.py (v6.1) produces.

v7.1 runs v7.0's C engine (prime_sieve_engine_v7_0.so), whose engine calls
test_engine_v7_0_identity.py compares bit for bit; v7.1 changes only the threshold and the
progress line. So whole runs: both scanners on the cases of test_engine_v6_identity, each into
its own empty portal, every output file compared byte for byte (PGS2 timestamp zeroed) and the
handoff's result fields; v7.1 runs them with the model at 1 %, block cost 1 and landing cost 0
(the gear takes every bucketed prime from its lower limits up), at the defaults, and with small
segments and the gear on. One run's console must show the model line, both stage times and
progress percents that never fall and end at 100 %.

Run inside WSL from the repo root:
    python3 unitTests/test_engine_v7_1_identity.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_engine_v6_identity as v6_cases  # noqa: E402
import test_engine_v7_0_identity as v7_0  # noqa: E402

check = v6_cases.check
CANDIDATE = "prime_sieve_v7_1.py"
JUMP_ON_ENV = {"PRIMEATLAS_V7_JUMP_MODEL_PCT": "1", "PRIMEATLAS_V7_JUMP_BLOCK_COST": "1",
               "PRIMEATLAS_V7_JUMP_LANDING_COST_PCT": "0"}


def check_console(tmp):
    """The model line, the stage times and the weighted percents of one gear-on run."""
    portal = os.path.join(tmp, "console")
    os.makedirs(portal)
    env = dict(os.environ, CONSTELLATION_PORTAL_DIR=portal, **JUMP_ON_ENV)
    cmd = [sys.executable, CANDIDATE, "19", "0", "2", str(v6_cases.WORKERS), "2", "0", "0",
           str(10 ** 6)]
    proc = subprocess.run(cmd, cwd=v6_cases.SIEVE_DIR, env=env, capture_output=True, text=True)
    tail = proc.stdout + proc.stderr   # the whole console: the gear line comes early
    passed = check(proc.returncode == 0, "console run exits 0")
    passed &= check(re.search(r"Jump gear: \d+ of the pieces.*1 % of the model, block cost 1, "
                              r"landing cost 0 %.*estimated cost share [\d.]+ %", tail)
                    is not None, "the jump gear line names the model and its cost share")
    passed &= check("Segmented slices done in" in tail and "Bucketed pieces done in" in tail,
                    "both stage times are printed")
    percents = [float(x) for x in re.findall(r"\[\+\] Progress: ([\d.]+)% \(\d+/\d+ batches\)",
                                             tail)]
    passed &= check(percents and percents == sorted(percents) and percents[-1] == 100.0,
                    f"weighted percents never fall and end at 100 % ({percents[-3:]})")
    if not passed:
        print(tail)
    return passed


def main():
    passed = check(os.path.exists(os.path.join(v6_cases.SIEVE_DIR, CANDIDATE)),
                   f"{CANDIDATE} exists")
    tmp = tempfile.mkdtemp(prefix="engine_v7_1_identity_")
    try:
        passed &= check_console(tmp)
        for case in v6_cases.CASES:
            passed &= v7_0.compare_runs(tmp, case[0] + " gear 1 %", *case[1:],
                                        extra_env=JUMP_ON_ENV, candidate=CANDIDATE)
        for case in v6_cases.CASES[:3]:
            passed &= v7_0.compare_runs(tmp, *case, candidate=CANDIDATE)
        for case in v6_cases.SMALL_SEGMENT_CASES:
            passed &= v7_0.compare_runs(tmp, *case,
                                        extra_env={**v7_0.SMALL_SEGMENT_ENV, **JUMP_ON_ENV},
                                        candidate=CANDIDATE)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    import engine_v7_lib
    from _native_skip import exit_if_skipped
    exit_if_skipped([engine_v7_lib.load_lib])
    raise SystemExit(main())
