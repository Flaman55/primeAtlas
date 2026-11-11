"""WSL test: the v7.3 store verification (v73_verify_store.py): P windows proven by a v7.2 sieve.

A. Equal windows move to D and become D/P; a window with a prime removed stays P and is
   listed in DP_MISMATCH.txt with that prime as first difference; a window with a D file
   already and one written with another width are skipped; the run logs one v73_verify row
   with verify_seconds; a second run changes nothing and lists the mismatch again;
   max_windows limits the run; a stop request before the first pass exits 3 and changes
   nothing.
B. The same store proven by pt1.1 (pt1_verify_store.py) and by v7.3 ends equal: the same D
   bytes and the same DP_PROVEN.txt tags, whatever the pass width (one window per pass,
   two, all at once).
C. A gap between windows starts a new pass; windows past a gap are proven too.
D. Floor 7 holds only D windows (pt1 writes P from the 13 Miller-Rabin bases' bound up):
   exit 2, nothing changed.

Run inside WSL from the repo root:
    python3 unitTests/test_engine_v73_verify.py
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
V73 = "v73_verify_store.py"
PT11 = "pt1_verify_store.py"
W = 200_000


def _verify(script, portal, floor, max_windows=0, pass_numbers=None):
    env = dict(os.environ, CONSTELLATION_PORTAL_DIR=portal)
    cmd = [sys.executable, script, str(floor), "8", str(W), str(max_windows)]
    if pass_numbers is not None:
        cmd.append(str(pass_numbers))
    proc = subprocess.run(cmd, cwd=SIEVE_DIR, env=env, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def _stores(portal):
    files, _ = snapshot(portal)
    d = {p: b for p, b in files.items() if f"{os.sep}source_primes{os.sep}" in os.sep + p}
    p = {k: b for k, b in files.items() if f"{os.sep}source_primes_P{os.sep}" in os.sep + k}
    return d, p


def _proven(portal, floor):
    path = os.path.join(portal, f"10p{floor}", "DP_PROVEN.txt")
    return set(open(path).read().split()) if os.path.exists(path) else set()


def _log_rows(portal):
    path = os.path.join(portal, "benchmark_log.csv")
    return list(csv.DictReader(open(path, newline=""))) if os.path.exists(path) else []


def _paths(portal, floor):
    import prime_sieve_v1
    import storage_kinds as sk
    label = lambda i: prime_sieve_v1.format_offset(i * W)  # noqa: E731
    p_path = lambda i: sk.window_path(portal, floor, i * W, W, label(i), sk.KIND_P)  # noqa: E731
    d_path = lambda i: sk.window_path(portal, floor, i * W, W, label(i), sk.KIND_D)  # noqa: E731
    return label, p_path, d_path


def _store_case(tmp):
    import prime_sieve_v1
    import storage_kinds as sk
    passed = True
    portal = os.path.join(tmp, "store")
    os.makedirs(portal)
    rc, _ = run_scanner(PT1, portal, 26, 0, 4, W, True, {})
    passed &= check(rc == 0, "A: pt1 writes 5 P windows on floor 26")
    label, p_path, d_path = _paths(portal, 26)
    primes = prime_sieve_v1.read_prime_window(p_path(2))
    prime_sieve_v1.write_prime_window(p_path(2), primes[1:])
    os.makedirs(os.path.dirname(d_path(3)), exist_ok=True)
    shutil.copyfile(p_path(3), d_path(3))
    odd = sk.window_path(portal, 26, 7 * W, W, label(7), sk.KIND_P)
    wide = list(range(10 ** 26 + 7 * W + 1, 10 ** 26 + 9 * W, 2))[:5] + [10 ** 26 + 8 * W + 1]
    prime_sieve_v1.write_prime_window(odd, wide)

    stop = os.path.join(portal, "GENERATION_STOP_REQUEST.txt")
    open(stop, "w").close()
    rc, _ = _verify(V73, portal, 26)
    os.remove(stop)
    passed &= check(rc == 3 and all(os.path.exists(p_path(i)) for i in range(5))
                    and not _log_rows(portal), "A: stop before the first pass: rc 3, no change")

    rc, out = _verify(V73, portal, 26, 1)
    passed &= check(rc == 0 and os.path.exists(d_path(0)) and not os.path.exists(p_path(0))
                    and os.path.exists(p_path(1)), "A: max_windows 1 proves only window 0")

    rc, out = _verify(V73, portal, 26, 0, 2 * W)
    if rc:
        print(out[-2000:])
    passed &= check(rc == 0, "A: v7.3 store verification exits 0")
    for i in (1, 4):
        passed &= check(os.path.exists(d_path(i)) and not os.path.exists(p_path(i)),
                        f"A: window {i} moved to D")
    tags = _proven(portal, 26)
    passed &= check({sk.window_tag(os.path.basename(d_path(i))) for i in (0, 1, 4)} <= tags
                    and sk.window_tag(os.path.basename(p_path(2))) not in tags,
                    "A: proven windows listed in DP_PROVEN.txt, the corrupted one not")
    passed &= check(os.path.exists(p_path(2)) and not os.path.exists(d_path(2)),
                    "A: corrupted window stays P")
    mismatch = os.path.join(portal, "10p26", "DP_MISMATCH.txt")
    text = open(mismatch).read() if os.path.exists(mismatch) else ""
    passed &= check(f"first_difference={primes[0]}" in text,
                    "A: mismatch lists the removed prime as first difference")
    passed &= check(os.path.exists(p_path(3)) and os.path.exists(odd),
                    "A: window with D and window of another width skipped, still P")
    rows = [r for r in _log_rows(portal) if r["engine"] == "v73_verify"]
    passed &= check(len(rows) == 2 and float(rows[-1]["verify_seconds"]) > 0
                    and rows[-1]["engine_version"] == "v7.3" and rows[-1]["threads"] == "8"
                    and rows[-1]["run_purpose"] == "storage",
                    "A: v73_verify rows logged")

    before = {i: os.path.exists(p_path(i)) for i in range(5)}
    rc, out = _verify(V73, portal, 26)
    after = {i: os.path.exists(p_path(i)) for i in range(5)}
    passed &= check(rc == 0 and before == after and "1 mismatches" in out,
                    "A: second run changes nothing, reports the mismatch again")
    return passed


def _equal_case(tmp):
    passed = True
    source = os.path.join(tmp, "source")
    os.makedirs(source)
    rc, _ = run_scanner(PT1, source, 25, 0, 4, W, True, {})
    passed &= check(rc == 0, "B: pt1 writes 5 P windows on floor 25")
    results = {}
    for name, script, pass_numbers in (("pt1.1", PT11, None), ("v7.3 x1", V73, W),
                                       ("v7.3 x2", V73, 2 * W), ("v7.3 all", V73, 10 ** 11)):
        portal = os.path.join(tmp, name.replace(" ", "_"))
        shutil.copytree(source, portal)
        rc, out = _verify(script, portal, 25, 0, pass_numbers)
        if rc:
            print(out[-2000:])
        d, p = _stores(portal)
        passed &= check(rc == 0 and len(d) == 5 and not p, f"B: {name} proves all 5 windows")
        results[name] = (sorted(d.values()), _proven(portal, 25))
    first = results["pt1.1"]
    for name, result in results.items():
        passed &= check(result == first, f"B: {name} ends equal to pt1.1")
    return passed


def _gap_case(tmp):
    passed = True
    portal = os.path.join(tmp, "gap")
    os.makedirs(portal)
    rc, _ = run_scanner(PT1, portal, 25, 0, 4, W, True, {})
    _label, p_path, d_path = _paths(portal, 25)
    os.remove(p_path(2))
    rc, out = _verify(V73, portal, 25, 0, 10 ** 11)
    passed &= check(rc == 0 and "2 passes" in out, "C: windows 0-1 and 3-4 take 2 passes")
    passed &= check(all(os.path.exists(d_path(i)) and not os.path.exists(p_path(i))
                        for i in (0, 1, 3, 4)), "C: windows on both sides of the gap proven")
    return passed


def _low_floor_case(tmp):
    portal = os.path.join(tmp, "low")
    os.makedirs(portal)
    rc, _ = run_scanner(PT1, portal, 7, 0, 2, W, True, {})
    before = _stores(portal)
    rc2, out = _verify(V73, portal, 7)
    return check(rc == 0 and rc2 == 2 and len(before[0]) == 3 and not before[1]
                 and _stores(portal) == before and "No P window" in out,
                 "D: floor 7 has only D windows: exit 2, no change")


def main():
    tmp = tempfile.mkdtemp(prefix="engine_v73_verify_")
    try:
        passed = _store_case(tmp)
        passed &= _equal_case(tmp)
        passed &= _gap_case(tmp)
        passed &= _low_floor_case(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    if os.name == "nt":
        print("SKIPPED (WSL-only test: runs the Linux engines)")
        raise SystemExit(0)
    raise SystemExit(main())
