"""WSL test: engine pt1 (partial sieve + primality test, prime_sieve_pt1.py).

D windows (wholly below MR_DET_BOUND) must be byte-identical to prime_sieve_v5.py's output
for the same windows (PGS2 timestamp excluded), including the handoff's prime count: floors
10, 19 and 22, a window straddling 2^64, an odd window width, count-only mode and a small B
and chunk (env PRIMEATLAS_PT1_B / PRIMEATLAS_PT1_CHUNK_KB), so primes carry across many
chunks. P windows go to source_primes_P/ with the _P suffix and nothing to source_primes/;
their primes must equal gmpy2.is_prime over every number of the window: floor 24 across the
bound (P), floor 24 just below it (D), floors 25-30 and 37. With stdout redirected to a file (as
the GUI launches it) a progress line reaches the file while the run is still going. Floors
0..6 and above 37 are
refused with a non-zero exit and no files. PRIMEATLAS_TEST_DEEP=1 adds one floor-25 window
whose P primes must equal v5's D primes. orchestrator_v3.py: D proves P after a v5 batch
(equal P removed, differing P kept and reported) and pt1 auto-continues from P (about a minute and a half on 24 threads).

Run inside WSL from the repo root:
    python3 unitTests/test_engine_pt1.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIEVE_DIR = os.path.join(ROOT, "prime_sieve")
sys.path.insert(0, SIEVE_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_engine_v5_identity import check, run_scanner, snapshot  # noqa: E402

PT1 = "prime_sieve_pt1.py"
V5 = "prime_sieve_v5.py"
SMALL_ENV = {"PRIMEATLAS_PT1_B": "100", "PRIMEATLAS_PT1_CHUNK_KB": "1"}

# (label, floor, first target_idx, last target_idx, window_m, write_files, env)
IDENTITY_CASES = [
    ("floor 10", 10, 0, 2, 10 ** 6, True, {}),
    ("floor 10 odd width", 10, 0, 2, 999_999, True, {}),
    ("floor 10 count-only", 10, 3, 5, 10 ** 6, False, {}),
    ("floor 19", 19, 0, 2, 10 ** 6, True, {}),
    ("floor 19 across 2^64", 19, 8446744073708, 8446744073710, 10 ** 6, True, {}),
    ("floor 22", 22, 5, 7, 10 ** 6, True, {}),
    ("floor 19 small B and chunk", 19, 0, 2, 10 ** 6, True, SMALL_ENV),
]
DEEP_FLOOR, DEEP_W = 25, 10 ** 6
BOUND = 3_317_044_064_679_887_385_961_981
GMP_W = 200_000
# (label, floor, target_idx, expected kind)
GMP_CASES = [
    ("floor 24 below the bound", 24, (BOUND - 10 ** 24) // GMP_W - 3, "D"),
    ("floor 24 across the bound", 24, (BOUND - 10 ** 24) // GMP_W, "P"),
    ("floor 25", 25, 0, "P"),
    ("floor 26", 26, 7, "P"),
    ("floor 28", 28, 3, "P"),
    ("floor 30", 30, 1, "P"),
    ("floor 37", 37, 0, "P"),
]


def _source_files(files):
    d = {p: b for p, b in files.items() if os.sep + "source_primes" + os.sep in os.sep + p}
    pp = {p: b for p, b in files.items() if os.sep + "source_primes_P" + os.sep in os.sep + p}
    return d, pp


def identity_case(tmp, label, floor, idx_lo, idx_hi, window_m, write_files, env):
    passed = True
    snaps = []
    for script, extra in ((V5, {}), (PT1, env)):
        portal = os.path.join(tmp, f"{label.replace(' ', '_')}_{script}")
        os.makedirs(portal)
        rc, tail = run_scanner(script, portal, floor, idx_lo, idx_hi, window_m, write_files, extra)
        if rc != 0:
            print(tail)
        passed &= check(rc == 0, f"{label}: {script} exits 0")
        snaps.append(snapshot(portal))
    (ref_files, ref_metrics), (new_files, new_metrics) = snaps
    if write_files:
        passed &= check(len(ref_files) > 0, f"{label}: v5 wrote output files")
    passed &= check(sorted(new_files) == sorted(ref_files),
                    f"{label}: same file set ({len(ref_files)} files, all D)")
    differing = [p for p in ref_files if new_files.get(p) != ref_files[p]]
    passed &= check(not differing, f"{label}: every file byte-identical {differing[:3]}")
    passed &= check(new_metrics.get("total_primes_found") == ref_metrics.get("total_primes_found")
                    and new_metrics.get("windows_processed") == ref_metrics.get("windows_processed"),
                    f"{label}: same prime count ({ref_metrics.get('total_primes_found')})")
    return passed


def gmp_case(tmp, label, floor, idx, kind):
    import gmpy2
    import prime_sieve_v1
    passed = True
    portal = os.path.join(tmp, label.replace(" ", "_"))
    os.makedirs(portal)
    rc, tail = run_scanner(PT1, portal, floor, idx, idx, GMP_W, True, {})
    if rc != 0:
        print(tail)
    passed &= check(rc == 0, f"{label}: pt1 exits 0")
    d, p = _source_files(snapshot(portal)[0])
    expect_d, expect_p = (1, 0) if kind == "D" else (0, 1)
    passed &= check(len(d) == expect_d and len(p) == expect_p,
                    f"{label}: one {kind} window, nothing in the other store ({list(d) + list(p)})")
    if kind == "P" and p:
        name = os.path.basename(next(iter(p)))
        passed &= check(name.endswith("_P.bin"), f"{label}: P filename {name}")
    files = list(d) + list(p)
    if not files:
        return False
    got = prime_sieve_v1.read_prime_window(os.path.join(portal, files[0]))
    lo = 10 ** floor + idx * GMP_W
    want = [n for n in range(lo | 1, lo + GMP_W, 2) if gmpy2.is_prime(n, 50)]
    passed &= check(got == want, f"{label}: primes equal gmpy2 ({len(want)} primes)")
    return passed


def deep_case(tmp):
    """One floor-25 window: v5's D file and pt1's P file hold the same primes."""
    import prime_sieve_v1
    passed = True
    primes = {}
    for script in (V5, PT1):
        portal = os.path.join(tmp, f"deep_{script}")
        os.makedirs(portal)
        rc, tail = run_scanner(script, portal, DEEP_FLOOR, 0, 0, DEEP_W, True, {})
        if rc != 0:
            print(tail)
        passed &= check(rc == 0, f"floor {DEEP_FLOOR} deep: {script} exits 0")
        d, p = _source_files(snapshot(portal)[0])
        files = list(p if script == PT1 else d)
        passed &= check(len(files) == 1, f"floor {DEEP_FLOOR} deep: {script} wrote one "
                        f"{'P' if script == PT1 else 'D'} window ({files})")
        if files:
            primes[script] = prime_sieve_v1.read_prime_window(os.path.join(portal, files[0]))
    passed &= check(len(primes) == 2 and primes[V5] == primes[PT1],
                    f"floor {DEEP_FLOOR} deep: P primes equal v5's D primes "
                    f"({len(primes.get(V5, []))} primes)")
    return passed


def orchestrator_case(tmp):
    """orchestrator_v3.py with v5 on floor 10: a P window equal to the new D window is
    removed, a differing one is kept and listed in DP_MISMATCH.txt; pt1 auto-continues
    floor 25 from its P store, past a D window it ignores."""
    import subprocess
    import shutil as sh
    import storage_kinds as sk
    passed = True
    portal = os.path.join(tmp, "orch")
    os.makedirs(portal)
    w = 10 ** 6

    def orch(engine, floor, count, auto, start):
        env = dict(os.environ, CONSTELLATION_PORTAL_DIR=portal, PRIMEATLAS_SCANNER_VERSION=engine)
        cmd = [sys.executable, "orchestrator_v3.py", str(floor), str(count), auto, str(start),
               "1", "0", "4", "2", str(w)]
        proc = subprocess.run(cmd, cwd=SIEVE_DIR, env=env, capture_output=True, text=True)
        return proc.returncode, proc.stdout + proc.stderr

    rc, out = orch("pt1", 10, 2, "0", 0)          # D windows 0, 1 written by pt1
    passed &= check(rc == 0, "orchestrator pt1 floor 10 exits 0")
    d0 = sk.window_path(portal, 10, 0, w, "0")
    d1 = sk.window_path(portal, 10, w, w, "1M")
    p0, p1 = (d.replace("source_primes", "source_primes_P").replace(".bin", "_P.bin") for d in (d0, d1))
    for d, p in ((d0, p0), (d1, p1)):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        sh.copyfile(d, p)
    with open(p1, "r+b") as f:                    # flip the last gap byte
        f.seek(-1, 2)
        last = f.read(1)[0]
        f.seek(-1, 2)
        f.write(bytes([last ^ 0x02]))
    rc, out = orch("v5", 10, 2, "0", 0)
    passed &= check(rc == 0, "orchestrator v5 floor 10 exits 0")
    passed &= check(not os.path.exists(p0) and os.path.exists(p1),
                    "equal P removed, differing P kept")
    passed &= check("[ERROR] D/P mismatch in PRIME_WINDOW_10p10_off_1M" in out,
                    "mismatch printed as ERROR in the run log")
    passed &= check(os.path.exists(os.path.join(portal, "10p10", "DP_MISMATCH.txt")),
                    "mismatch listed in DP_MISMATCH.txt")
    # pt1 continues floor 25 from P (window 3), not from D (window 7)
    for idx, kind in ((3, "P"), (7, "D")):
        path = sk.window_path(portal, 25, idx * w, w, f"{idx}M", kind)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"PGS2" + bytes(9))
    rc, out = orch("pt1", 25, 1, "1", 0)
    passed &= check(rc == 0 and "continuing from target_idx=4" in out,
                    "pt1 auto-continues floor 25 from its P store")
    passed &= check(os.path.exists(sk.window_path(portal, 25, 4 * w, w, "4M", "P")),
                    "pt1 wrote P window 4")
    return passed


def live_progress_case(tmp):
    """One thread on floor 25 runs well past the 10 s progress interval; the run is killed
    as soon as its first progress line is in the log file."""
    portal = os.path.join(tmp, "live_progress")
    os.makedirs(portal)
    log_path = os.path.join(tmp, "live_progress.log")
    env = dict(os.environ, CONSTELLATION_PORTAL_DIR=portal)
    cmd = [sys.executable, PT1, "25", "0", "19", "1", "2", "0", "0", str(10 ** 7)]
    seen_alive = False
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(cmd, cwd=SIEVE_DIR, env=env, stdout=log,
                                stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 120
            while proc.poll() is None and time.monotonic() < deadline:
                with open(log_path, encoding="utf-8") as f:
                    if "[+] Progress:" in f.read():
                        seen_alive = True
                        break
                time.sleep(0.5)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
    return check(seen_alive, "pt1 progress line reaches a redirected stdout during the run")


def refusal_case(tmp, floor):
    portal = os.path.join(tmp, f"refuse_{floor}")
    os.makedirs(portal)
    rc, _tail = run_scanner(PT1, portal, floor, 0, 0, 10 ** 7, True, {})
    files, _ = snapshot(portal)
    return check(rc != 0 and not files, f"floor {floor} refused (rc={rc}, {len(files)} files)")


def main():
    passed = check(os.path.exists(os.path.join(SIEVE_DIR, PT1)), f"{PT1} exists")
    if not passed:
        print("SOME CHECKS FAILED")
        return 1
    tmp = tempfile.mkdtemp(prefix="engine_pt1_")
    try:
        for case in IDENTITY_CASES:
            passed &= identity_case(tmp, *case)
        if os.environ.get("PRIMEATLAS_TEST_DEEP") == "1":
            passed &= deep_case(tmp)
        for case in GMP_CASES:
            passed &= gmp_case(tmp, *case)
        passed &= orchestrator_case(tmp)
        passed &= live_progress_case(tmp)
        for floor in (0, 6, 38):
            passed &= refusal_case(tmp, floor)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    if os.name == "nt":
        print("SKIPPED (WSL-only test: runs the Linux engines)")
        raise SystemExit(0)
    raise SystemExit(main())
