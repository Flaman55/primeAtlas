"""WSL test: prime_sieve_v5.py produces exactly what prime_sieve_v4_1.py produces.

Each case runs both scanners as subprocesses on the same windows, each into its own empty
portal (CONSTELLATION_PORTAL_DIR), then compares every output file byte for byte (except
the PGS2 generation timestamp) and the
result fields of the metrics handoff (timings excluded). Cases cover a low floor split across
real floor boundaries, the top end of a floor, floors 10/19/22, count-only mode, and floor 25
when PRIMEATLAS_TEST_DEEP=1 (about two minutes on 24 threads).

Run inside WSL from the repo root:
    python3 unitTests/test_engine_v5_identity.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIEVE_DIR = os.path.join(ROOT, "prime_sieve")
sys.path.insert(0, SIEVE_DIR)

WORKERS = 8
METRICS_FILE = "last_scan_metrics.json"
RESULT_FIELDS = ("l_final", "sieving_primes_count", "total_primes_found", "windows_processed",
                 "write_files", "bytes_written", "numbers_processed")

# (label, floor, first target_idx, last target_idx, window_m, write_files)
CASES = [
    ("low floor split 10^5..", 5, 0, 0, 10 ** 7, True),
    ("floor 10 start", 10, 0, 2, 10 ** 6, True),
    ("floor 10 top end", 10, 89997, 89999, 10 ** 6, True),
    ("floor 19", 19, 0, 2, 10 ** 6, True),
    ("floor 22", 22, 5, 7, 10 ** 6, True),
    ("floor 19 count-only", 19, 3, 5, 10 ** 6, False),
]
DEEP_CASES = [
    ("floor 25", 25, 0, 1, 10 ** 6, True),
]


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def run_scanner(script, portal, floor, idx_lo, idx_hi, window_m, write_files):
    env = dict(os.environ, CONSTELLATION_PORTAL_DIR=portal)
    cmd = [sys.executable, script, str(floor), str(idx_lo), str(idx_hi), str(WORKERS), "2",
           "1" if write_files else "0", "0", str(window_m)]
    proc = subprocess.run(cmd, cwd=SIEVE_DIR, env=env, capture_output=True, text=True)
    return proc.returncode, proc.stdout[-2000:] + proc.stderr[-2000:]


def without_timestamp(data):
    """PGS2 bytes with the 4-byte generated_at field zeroed. Header layout: magic "PGS2",
    1-byte base length L, L base bytes, 4-byte count, 4-byte generated_at."""
    if data[:4] != b"PGS2" or len(data) < 5:
        return data
    at = 4 + 1 + data[4] + 4
    return data[:at] + b"\0\0\0\0" + data[at + 4:]


def snapshot(portal):
    """{relative path: bytes} for every output file (PGS2 timestamps zeroed: two runs a
    second apart differ only there), plus the handoff's result fields."""
    files, metrics = {}, {}
    for root, _dirs, names in os.walk(portal):
        for name in names:
            path = os.path.join(root, name)
            if name == METRICS_FILE:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                metrics = {k: data.get(k) for k in RESULT_FIELDS}
                continue
            with open(path, "rb") as f:
                files[os.path.relpath(path, portal)] = without_timestamp(f.read())
    return files, metrics


def compare_case(tmp, label, floor, idx_lo, idx_hi, window_m, write_files):
    passed = True
    snaps = {}
    for script in ("prime_sieve_v4_1.py", "prime_sieve_v5.py"):
        portal = os.path.join(tmp, f"{label.replace(' ', '_')}_{script}")
        os.makedirs(portal)
        if not os.path.exists(os.path.join(SIEVE_DIR, script)):
            return check(False, f"{label}: {script} exists")
        rc, tail = run_scanner(script, portal, floor, idx_lo, idx_hi, window_m, write_files)
        if rc != 0:
            print(tail)
        passed &= check(rc == 0, f"{label}: {script} exits 0")
        snaps[script] = snapshot(portal)
    (ref_files, ref_metrics), (new_files, new_metrics) = snaps.values()
    if write_files:
        passed &= check(len(ref_files) > 0, f"{label}: v4.1 wrote output files")
    passed &= check(sorted(new_files) == sorted(ref_files),
                    f"{label}: same file set ({len(ref_files)} files)")
    differing = [p for p in ref_files if new_files.get(p) != ref_files[p]]
    if differing:
        print(f"       differing files: {differing[:5]}")
    passed &= check(not differing, f"{label}: every file byte-identical")
    passed &= check(ref_metrics.get("total_primes_found") is not None,
                    f"{label}: v4.1 reported total_primes_found")
    passed &= check(new_metrics == ref_metrics, f"{label}: handoff result fields equal "
                    f"(total_primes_found={ref_metrics.get('total_primes_found')})")
    return passed


def main():
    cases = CASES + (DEEP_CASES if os.environ.get("PRIMEATLAS_TEST_DEEP") == "1" else [])
    passed = True
    tmp = tempfile.mkdtemp(prefix="engine_v5_identity_")
    try:
        for case in cases:
            passed &= compare_case(tmp, *case)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    import prime_sieve_v4_1
    from _native_skip import exit_if_skipped
    exit_if_skipped([prime_sieve_v4_1._load_lib])
    raise SystemExit(main())
