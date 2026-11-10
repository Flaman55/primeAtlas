"""WSL test: pt1's verification P -> D (pt1_verify.py, prime_sieve_pt1.py with
PRIMEATLAS_PT1_VERIFY=1, pt1_verify_store.py).

A. PRIMEATLAS_PT1_VERIFY accepts 1, 0, blank and unset; anything else is an error.
B. The bound s: the scan's B when that already gives top / B < L_373 (floors 25, 31), raised
   to top / L_373 when not (floor 33), None from L_373 * 2^32 (about 1.8e34, inside floor 34)
   or when s would pass isqrt(lo).
C. The proven bitmap of pt1_verify_odd() equals gmpy2 on floors 25 and 30.
D. A verifying scan writes every P window to the D store, lists it in DP_PROVEN.txt, leaves
   nothing in the P store; its bytes equal the P files of a scan without the verification;
   the handoff carries proof_seconds and windows_proven. Count-only verifies and writes
   nothing, with the same prime count. Below the bound (floor 23) nothing is proven (D by 13
   Miller-Rabin bases). 2e34 (floor 34) with the verification is refused (exit 2, no files),
   without it pt1 still runs there.
E. The store verification: equal windows move to D and become D/P; a window with a prime
   removed stays P and is listed in DP_MISMATCH.txt with that prime as first difference; a
   window with a D file already and one written with another width are skipped; the run logs
   one pt1_verify row with verify_seconds; a second run changes nothing and lists the mismatch
   again; max_windows limits the run; a stop request before the first slab exits 3 and
   changes nothing.
F. orchestrator_v3.py with pt1 and the verification: the row has proof_seconds, the windows
   are counted from the D store.

Run inside WSL from the repo root:
    python3 unitTests/test_engine_pt1_verify.py
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIEVE_DIR = os.path.join(ROOT, "prime_sieve")
sys.path.insert(0, SIEVE_DIR)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_engine_v5_identity import check, run_scanner, snapshot  # noqa: E402

PT1 = "prime_sieve_pt1.py"
STORE = "pt1_verify_store.py"
W = 200_000
VERIFY = {"PRIMEATLAS_PT1_VERIFY": "1"}


def _env_case():
    import pt1_verify
    passed = True
    for raw, want in (("1", True), ("0", False), ("", False), (None, False)):
        env = {} if raw is None else {pt1_verify.VERIFY_ENV: raw}
        passed &= check(pt1_verify.verify_from_env(env) is want, f"A: {raw!r} -> {want}")
    for raw in ("2", "yes", "-1"):
        try:
            pt1_verify.verify_from_env({pt1_verify.VERIFY_ENV: raw})
            passed &= check(False, f"A: {raw!r} raises")
        except ValueError:
            passed &= check(True, f"A: {raw!r} raises")
    return passed


def _bound_case():
    import math
    import pt1_plan
    import pt1_verify
    passed = True
    for floor in (25, 31):
        lo, hi = 10 ** floor, 10 ** floor + W
        b = pt1_plan.effective_b(0, lo, hi)
        passed &= check(pt1_verify.bound(b, lo, hi) == b, f"B: floor {floor} keeps B = {b:,}")
    lo, hi = 9 * 10 ** 33, 9 * 10 ** 33 + W
    b = pt1_plan.effective_b(0, lo, hi)
    s = pt1_verify.bound(b, lo, hi)
    passed &= check(s is not None and s > b and (hi - 1) // s < 4235025223080597503519329,
                    f"B: floor 33 raises s above B ({s} > {b})")
    passed &= check(pt1_verify.bound(0, 10 ** 34, 10 ** 34 + W) is not None,
                    "B: the start of floor 34 is verifiable")
    passed &= check(pt1_verify.bound(0, 2 * 10 ** 34, 2 * 10 ** 34 + W) is None,
                    "B: 2e34 refused")
    passed &= check(pt1_verify.bound(math.isqrt(10 ** 25) + 1, 10 ** 25, 10 ** 25 + W) is None,
                    "B: s past isqrt(lo) refused")
    return passed


def _proof_case():
    import gmpy2
    import pt1_lib
    import pt1_plan
    import pt1_verify
    from prime_sieve_v5 import _window_prime_offsets
    passed = True
    lib = pt1_lib.load()
    for floor, idx in ((25, 3), (30, 1)):
        lo = 10 ** floor + idx * W
        hi = lo + W
        s = pt1_verify.bound(pt1_plan.effective_b(0, lo, hi), lo, hi)
        ctx = lib.pt1_ctx_new(s)
        try:
            first_odd, bits = pt1_verify.verify_slab(ctx, lo, hi, 8, 4096, lambda _d: None)
        finally:
            lib.pt1_ctx_free(ctx)
        got = [lo + int(o) for o in _window_prime_offsets(bits, first_odd, lo, hi)]
        want = [n for n in range(lo | 1, hi, 2) if gmpy2.is_prime(n, 50)]
        passed &= check(got == want, f"C: floor {floor} proof equals gmpy2 ({len(want)} primes)")
    return passed


def _metrics(portal):
    path = os.path.join(portal, "last_scan_metrics.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _stores(portal):
    files, _ = snapshot(portal)
    d = {p: b for p, b in files.items() if f"{os.sep}source_primes{os.sep}" in os.sep + p}
    p = {k: b for k, b in files.items() if f"{os.sep}source_primes_P{os.sep}" in os.sep + k}
    return d, p


def _proven(portal, floor):
    path = os.path.join(portal, f"10p{floor}", "DP_PROVEN.txt")
    return set(open(path).read().split()) if os.path.exists(path) else set()


def _scan_case(tmp):
    passed = True
    plain, verified = os.path.join(tmp, "plain"), os.path.join(tmp, "verified")
    for portal, env in ((plain, {}), (verified, VERIFY)):
        os.makedirs(portal)
        rc, tail = run_scanner(PT1, portal, 25, 0, 2, W, True, env)
        if rc:
            print(tail)
        passed &= check(rc == 0, f"D: scan {'with' if env else 'without'} verification exits 0")
    plain_d, plain_p = _stores(plain)
    d, p = _stores(verified)
    passed &= check(len(plain_p) == 3 and not plain_d, "D: plain scan writes 3 P windows")
    passed &= check(len(d) == 3 and not p, "D: verifying scan writes 3 D windows, no P")
    same = sorted(plain_p.values()) == sorted(d.values())
    passed &= check(same, "D: verified D bytes equal the plain P bytes")
    passed &= check(len(_proven(verified, 25)) == 3, "D: 3 tags in DP_PROVEN.txt")
    m = _metrics(verified)
    passed &= check(m.get("proof_seconds", 0) > 0 and m.get("windows_proven") == 3
                    and m.get("proof_mismatches") == 0, f"D: handoff proof fields ({m})")

    count_only = os.path.join(tmp, "count_only")
    os.makedirs(count_only)
    rc, _ = run_scanner(PT1, count_only, 25, 0, 2, W, False, VERIFY)
    d, p = _stores(count_only)
    m = _metrics(count_only)
    passed &= check(rc == 0 and not d and not p and m.get("windows_proven") == 3
                    and m.get("total_primes_found") == _metrics(verified).get("total_primes_found"),
                    "D: count-only verifies 3 windows, writes nothing, same prime count")

    below = os.path.join(tmp, "below")
    os.makedirs(below)
    rc, _ = run_scanner(PT1, below, 23, 0, 0, W, True, VERIFY)
    d, p = _stores(below)
    passed &= check(rc == 0 and len(d) == 1 and not p and "proof_seconds" not in _metrics(below)
                    and not _proven(below, 23), "D: floor 23 is D without a proof")

    idx = 10 ** 34 // W  # 2e34
    for env, want in ((VERIFY, 2), ({}, 0)):
        portal = os.path.join(tmp, f"f34_{bool(env)}")
        os.makedirs(portal)
        rc, _ = run_scanner(PT1, portal, 34, idx, idx, W, True, env)
        d, p = _stores(portal)
        ok = rc == want and (bool(p) == (want == 0)) and not d
        passed &= check(ok, f"D: 2e34 {'with' if env else 'without'} verification: rc {rc}")
    return passed


def _store(portal, floor, max_windows=0):
    env = dict(os.environ, CONSTELLATION_PORTAL_DIR=portal)
    proc = subprocess.run([sys.executable, STORE, str(floor), "8", str(W), str(max_windows)],
                          cwd=SIEVE_DIR, env=env, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def _log_rows(portal):
    path = os.path.join(portal, "benchmark_log.csv")
    return list(csv.DictReader(open(path, newline=""))) if os.path.exists(path) else []


def _store_case(tmp):
    import prime_sieve_v1
    import storage_kinds as sk
    passed = True
    portal = os.path.join(tmp, "store")
    os.makedirs(portal)
    rc, _ = run_scanner(PT1, portal, 26, 0, 4, W, True, {})
    passed &= check(rc == 0, "E: pt1 writes 5 P windows on floor 26")
    label = lambda i: prime_sieve_v1.format_offset(i * W)  # noqa: E731
    p_path = lambda i: sk.window_path(portal, 26, i * W, W, label(i), sk.KIND_P)  # noqa: E731
    d_path = lambda i: sk.window_path(portal, 26, i * W, W, label(i), sk.KIND_D)  # noqa: E731
    passed &= check(all(os.path.exists(p_path(i)) for i in range(5)), "E: P paths as expected")
    primes = prime_sieve_v1.read_prime_window(p_path(2))
    prime_sieve_v1.write_prime_window(p_path(2), primes[1:])
    os.makedirs(os.path.dirname(d_path(3)), exist_ok=True)
    shutil.copyfile(p_path(3), d_path(3))
    odd = sk.window_path(portal, 26, 7 * W, W, label(7), sk.KIND_P)
    wide = list(range(10 ** 26 + 7 * W + 1, 10 ** 26 + 9 * W, 2))[:5] + [10 ** 26 + 8 * W + 1]
    prime_sieve_v1.write_prime_window(odd, wide)

    stop = os.path.join(portal, "GENERATION_STOP_REQUEST.txt")
    open(stop, "w").close()
    rc, _ = _store(portal, 26)
    os.remove(stop)
    passed &= check(rc == 3 and all(os.path.exists(p_path(i)) for i in range(5))
                    and not _log_rows(portal), "E: stop before the first slab: rc 3, no change")

    rc, out = _store(portal, 26, 1)
    passed &= check(rc == 0 and os.path.exists(d_path(0)) and not os.path.exists(p_path(0))
                    and os.path.exists(p_path(1)), "E: max_windows 1 proves only window 0")

    rc, out = _store(portal, 26)
    if rc:
        print(out[-2000:])
    passed &= check(rc == 0, "E: store verification exits 0")
    for i in (1, 4):
        passed &= check(os.path.exists(d_path(i)) and not os.path.exists(p_path(i)),
                        f"E: window {i} moved to D")
    tags = _proven(portal, 26)
    passed &= check({sk.window_tag(os.path.basename(d_path(i))) for i in (0, 1, 4)} <= tags
                    and sk.window_tag(os.path.basename(p_path(2))) not in tags,
                    "E: proven windows listed in DP_PROVEN.txt, the corrupted one not")
    passed &= check(os.path.exists(p_path(2)) and not os.path.exists(d_path(2)),
                    "E: corrupted window stays P")
    mismatch = os.path.join(portal, "10p26", "DP_MISMATCH.txt")
    text = open(mismatch).read() if os.path.exists(mismatch) else ""
    passed &= check(f"first_difference={primes[0]}" in text,
                    "E: mismatch lists the removed prime as first difference")
    passed &= check(os.path.exists(p_path(3)) and os.path.exists(odd),
                    "E: window with D and window of another width skipped, still P")
    rows = [r for r in _log_rows(portal) if r["engine"] == "pt1_verify"]
    passed &= check(len(rows) == 2 and float(rows[-1]["verify_seconds"]) > 0
                    and rows[-1]["engine_version"] == "pt1.1", "E: pt1_verify rows logged")

    before = {i: os.path.exists(p_path(i)) for i in range(5)}
    rc, out = _store(portal, 26)
    after = {i: os.path.exists(p_path(i)) for i in range(5)}
    passed &= check(rc == 0 and before == after and "1 mismatches" in out,
                    "E: second run changes nothing, reports the mismatch again")
    return passed


def _orchestrator_case(tmp):
    import storage_kinds as sk
    portal = os.path.join(tmp, "orch")
    os.makedirs(portal)
    env = dict(os.environ, CONSTELLATION_PORTAL_DIR=portal, PRIMEATLAS_SCANNER_VERSION="pt1",
               **VERIFY)
    cmd = [sys.executable, "orchestrator_v3.py", "25", "2", "0", "0", "1", "0", "8", "1", str(W)]
    proc = subprocess.run(cmd, cwd=SIEVE_DIR, env=env, capture_output=True, text=True)
    rows = _log_rows(portal)
    passed = check(proc.returncode == 0, "F: orchestrator pt1 with verification exits 0")
    passed &= check(len(rows) == 1 and float(rows[0]["proof_seconds"] or 0) > 0
                    and rows[0]["windows_written"] == "2" and rows[0]["engine_version"] == "pt1.1",
                    f"F: row has proof_seconds and 2 windows ({rows[:1]})")
    passed &= check(os.path.exists(sk.window_path(portal, 25, W, W, "200k")),
                    "F: proven window in the D store")
    return passed


def main():
    passed = _env_case() & _bound_case() & _proof_case()
    tmp = tempfile.mkdtemp(prefix="engine_pt1_verify_")
    try:
        passed &= _scan_case(tmp)
        passed &= _store_case(tmp)
        passed &= _orchestrator_case(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    if os.name == "nt":
        print("SKIPPED (WSL-only test: runs the Linux engines)")
        raise SystemExit(0)
    raise SystemExit(main())
