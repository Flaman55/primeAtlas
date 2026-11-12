"""WSL test: engine pt1-pss (prime_sieve_pt1.py with PRIMEATLAS_SCANNER_VERSION=pt1-pss): the
partial sieve with every survivor decided by a proof in the same pass, so every window is
proven and goes to the D store.

- Below MR_DET_BOUND the D windows are byte-identical to prime_sieve_v5.py's (floors 10, 19
  across 2^64, 22, count-only, small B and chunk).
- Above it the windows hold exactly the primes of gmpy2.is_prime (floor 24 across the bound,
  25, 28, 30, 32, 33, 34), all in source_primes/, none in source_primes_P/, and the handoff's
  prime count equals the files'. On floors 33 and 34 the default B and a too small requested B
  are raised to the smallest B the proof accepts, and the run says so.
- Floors 35..37 (past the pseudosquares table) and 0..6 are refused: non-zero exit, no files.
- orchestrator_v3.py: a pt1-pss run logs engine pt1-pss in benchmark_log.csv, writes D, runs no
  P -> D verification, and auto-continues from its D windows.

Run inside WSL from the repo root:
    python3 unitTests/test_engine_pt1_pss.py
"""
import csv
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
V5 = "prime_sieve_v5.py"
ENGINE = "pt1-pss"
PSS_ENV = {"PRIMEATLAS_SCANNER_VERSION": ENGINE}
SMALL_ENV = dict(PSS_ENV, PRIMEATLAS_PT1_B="100", PRIMEATLAS_PT1_CHUNK_KB="1")
BOUND = 3_317_044_064_679_887_385_961_981
GMP_W = 200_000

# (label, floor, first target_idx, last target_idx, window_m, write_files, env)
IDENTITY_CASES = [
    ("floor 10", 10, 0, 2, 10 ** 6, True, PSS_ENV),
    ("floor 10 count-only", 10, 3, 5, 10 ** 6, False, PSS_ENV),
    ("floor 19 across 2^64", 19, 8446744073708, 8446744073710, 10 ** 6, True, PSS_ENV),
    ("floor 22", 22, 5, 7, 10 ** 6, True, PSS_ENV),
    ("floor 19 small B and chunk", 19, 0, 2, 10 ** 6, True, SMALL_ENV),
]
# (label, floor, target_idx, extra env, B raised)
GMP_CASES = [
    ("floor 24 across the bound", 24, (BOUND - 10 ** 24) // GMP_W, {}, False),
    ("floor 25", 25, 0, {}, False),
    ("floor 28", 28, 3, {}, False),
    ("floor 30", 30, 1, {}, False),
    ("floor 32", 32, 0, {}, False),
    ("floor 33 default B", 33, 0, {}, True),
    ("floor 33 small requested B", 33, 2, {"PRIMEATLAS_PT1_B": "1000"}, True),
    ("floor 34", 34, 0, {}, True),
]


def _stores(files):
    d = [p for p in files if os.sep + "source_primes" + os.sep in os.sep + p]
    pp = [p for p in files if os.sep + "source_primes_P" + os.sep in os.sep + p]
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
    passed &= check(sorted(new_files) == sorted(ref_files),
                    f"{label}: same file set ({len(ref_files)} files, all D)")
    differing = [p for p in ref_files if new_files.get(p) != ref_files[p]]
    passed &= check(not differing, f"{label}: every file byte-identical {differing[:3]}")
    passed &= check(new_metrics.get("total_primes_found") == ref_metrics.get("total_primes_found"),
                    f"{label}: same prime count ({ref_metrics.get('total_primes_found')})")
    return passed


def gmp_case(tmp, label, floor, idx, env, raised):
    import gmpy2
    import prime_sieve_v1
    passed = True
    portal = os.path.join(tmp, label.replace(" ", "_"))
    os.makedirs(portal)
    rc, tail = run_scanner(PT1, portal, floor, idx, idx, GMP_W, True, dict(PSS_ENV, **env))
    if rc != 0:
        print(tail)
    passed &= check(rc == 0, f"{label}: pt1-pss exits 0")
    if raised:
        passed &= check("raised to" in tail, f"{label}: the run reports B raised for the proof")
    files, metrics = snapshot(portal)
    d, p = _stores(files)
    passed &= check(len(d) == 1 and not p, f"{label}: one D window, no P window ({d + p})")
    if not d:
        return False
    passed &= check(not os.path.basename(d[0]).endswith("_P.bin"), f"{label}: D filename")
    got = prime_sieve_v1.read_prime_window(os.path.join(portal, d[0]))
    lo = 10 ** floor + idx * GMP_W
    want = [n for n in range(lo | 1, lo + GMP_W, 2) if gmpy2.is_prime(n, 50)]
    passed &= check(got == want, f"{label}: primes equal gmpy2 ({len(want)} primes)")
    passed &= check(metrics.get("total_primes_found") == len(want),
                    f"{label}: handoff count {metrics.get('total_primes_found')}")
    return passed


def refusal_case(tmp, floor):
    portal = os.path.join(tmp, f"refuse_{floor}")
    os.makedirs(portal)
    rc, _tail = run_scanner(PT1, portal, floor, 0, 0, GMP_W, True, PSS_ENV)
    files, _ = snapshot(portal)
    return check(rc != 0 and not files, f"floor {floor} refused (rc={rc}, {len(files)} files)")


def orchestrator_case(tmp):
    import storage_kinds as sk
    passed = True
    portal = os.path.join(tmp, "orch")
    os.makedirs(portal)
    w = 10 ** 6

    def orch(floor, count, auto, start):
        env = dict(os.environ, CONSTELLATION_PORTAL_DIR=portal, PRIMEATLAS_SCANNER_VERSION=ENGINE,
                   PRIMEATLAS_PT1_VERIFY="1")
        cmd = [sys.executable, "orchestrator_v3.py", str(floor), str(count), auto, str(start),
               "1", "0", "4", "2", str(w)]
        proc = subprocess.run(cmd, cwd=SIEVE_DIR, env=env, capture_output=True, text=True)
        return proc.returncode, proc.stdout + proc.stderr

    rc, out = orch(25, 2, "0", 0)
    if rc != 0:
        print(out[-3000:])
    passed &= check(rc == 0, "orchestrator pt1-pss floor 25 exits 0")
    for idx, label in ((0, "0"), (1, "1M")):
        passed &= check(os.path.exists(sk.window_path(portal, 25, idx * w, w, label)),
                        f"orchestrator pt1-pss wrote D window {idx}")
    passed &= check(not sk.list_window_files(portal, 25, sk.KIND_P), "no P window written")
    log = os.path.join(portal, "benchmark_log.csv")
    rows = list(csv.DictReader(open(log, encoding="utf-8"))) if os.path.exists(log) else []
    engines = [r.get("engine") for r in rows]
    passed &= check(ENGINE in engines, f"benchmark_log engine pt1-pss ({engines})")
    passed &= check("pt1_verify" not in engines and "v73_verify" not in engines,
                    "no P -> D verification after a pt1-pss run")
    rc, out = orch(25, 1, "1", 0)
    passed &= check(rc == 0 and "continuing from target_idx=2" in out,
                    "pt1-pss auto-continues floor 25 from its D windows")
    return passed


def main():
    passed = True
    tmp = tempfile.mkdtemp(prefix="engine_pt1_pss_")
    try:
        for case in IDENTITY_CASES:
            passed &= identity_case(tmp, *case)
        for case in GMP_CASES:
            passed &= gmp_case(tmp, *case)
        for floor in (0, 6, 35, 37):
            passed &= refusal_case(tmp, floor)
        passed &= orchestrator_case(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    if os.name == "nt":
        print("SKIPPED (WSL-only test: runs the Linux engines)")
        raise SystemExit(0)
    raise SystemExit(main())
