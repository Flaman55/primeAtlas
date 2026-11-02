"""dp_verify: a D window proves or refutes the P window of the same offset.

Checks: counterpart paths map D <-> P within the same shard; an equal pair (different
generation timestamps) removes the P file, reports "equal" and lists the D window as D/P
in DP_PROVEN.txt (once, also when compared again); a differing pair keeps both
files, prints an ERROR line naming the window and the smallest number in only one list, and lists the
window in DP_MISMATCH.txt once even when compared twice; a later equal comparison removes
that line, while a mismatch of a D/P window drops its D/P entry; a P window without D and a D window without P are left alone; verify_floor()
runs the comparison over every P window of a floor and counts the outcomes. Pure Python,
runs on Windows and WSL:
    python unitTests/test_dp_verify.py
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

import dp_verify  # noqa: E402
import storage_kinds as sk  # noqa: E402
from pgs2_vector import write_prime_window_offsets  # noqa: E402

FLOOR = 25
W = 10 ** 7
LO = 10 ** FLOOR
PRIMES = [37, 39, 49, 61, 73, 91]   # offsets only; the values need not be prime here


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def _write(portal, idx, kind, offsets, generated_at):
    offset = idx * W
    path = sk.window_path(portal, FLOOR, offset, W, f"{offset // 10 ** 6}M" if offset else "0", kind)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_prime_window_offsets(path, LO + offset, np.array(offsets, dtype=np.int64),
                               generated_at=generated_at)
    return path


def _mismatch_lines(portal):
    path = os.path.join(portal, f"10p{FLOOR}", dp_verify.MISMATCH_FILENAME)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [line for line in f.read().splitlines() if line.strip()]


def _quiet(fn, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = fn(*args)
    return result, out.getvalue()


def check_counterparts(tmp):
    d = sk.window_path(tmp, FLOOR, 3 * W, W, "30M", "D")
    p = sk.window_path(tmp, FLOOR, 3 * W, W, "30M", "P")
    return check(dp_verify.counterpart_p_path(d) == p and dp_verify.counterpart_d_path(p) == d,
                 "D <-> P counterpart paths")


def check_equal(tmp):
    passed = True
    d = _write(tmp, 1, "D", PRIMES, 1000)
    p = _write(tmp, 1, "P", PRIMES, 2000)
    result, out = _quiet(dp_verify.reconcile, tmp, FLOOR, p)
    passed &= check(result.status == "equal", f"equal pair -> equal ({result})")
    passed &= check(not os.path.exists(p) and os.path.exists(d), "equal pair: P removed, D kept")
    passed &= check("ERROR" not in out, "equal pair prints no ERROR")
    tag = "PRIME_WINDOW_10p25_off_10M"
    passed &= check(sk.read_proven_tags(tmp, FLOOR) == {tag}, "equal pair: D window marked D/P")
    _write(tmp, 1, "P", PRIMES, 3000)
    _quiet(dp_verify.reconcile, tmp, FLOOR, p)
    with open(sk.proven_path(tmp, FLOOR), encoding="utf-8") as f:
        lines = [line for line in f.read().splitlines() if line.strip()]
    passed &= check(lines == [tag], f"D/P listed once after a second equal comparison ({lines})")
    _write(tmp, 1, "P", PRIMES[1:], 4000)
    _quiet(dp_verify.reconcile, tmp, FLOOR, p)
    passed &= check(sk.read_proven_tags(tmp, FLOOR) == set(),
                    "a later mismatch of a D/P window drops its D/P entry")
    _write(tmp, 1, "P", PRIMES, 5000)
    _quiet(dp_verify.reconcile, tmp, FLOOR, p)
    return passed


def check_mismatch(tmp):
    passed = True
    d = _write(tmp, 2, "D", PRIMES, 1000)
    p = _write(tmp, 2, "P", PRIMES[:3] + [55] + PRIMES[3:], 2000)
    result, out = _quiet(dp_verify.reconcile, tmp, FLOOR, p)
    passed &= check(result.status == "mismatch" and result.first_difference == LO + 2 * W + 55,
                    f"differing pair -> mismatch at the smallest number in one list only ({result})")
    passed &= check(os.path.exists(p) and os.path.exists(d), "mismatch keeps both files")
    passed &= check("ERROR" in out and "PRIME_WINDOW_10p25_off_20M" in out
                    and str(LO + 2 * W + 55) in out, f"ERROR line names window and number ({out.strip()})")
    _quiet(dp_verify.reconcile, tmp, FLOOR, p)
    lines = _mismatch_lines(tmp)
    passed &= check(len(lines) == 1 and "PRIME_WINDOW_10p25_off_20M" in lines[0],
                    f"DP_MISMATCH.txt lists the window once ({lines})")
    _write(tmp, 2, "P", PRIMES, 3000)
    result, _ = _quiet(dp_verify.reconcile, tmp, FLOOR, p)
    passed &= check(result.status == "equal" and not os.path.exists(p),
                    "fixed pair compares equal, P removed")
    passed &= check(_mismatch_lines(tmp) == [], "equal comparison removes the mismatch line")
    # a shorter P (D has one prime more at the end): first difference is D's extra prime
    _write(tmp, 4, "D", PRIMES, 1000)
    p4 = _write(tmp, 4, "P", PRIMES[:-1], 2000)
    result, _ = _quiet(dp_verify.reconcile, tmp, FLOOR, p4)
    passed &= check(result.status == "mismatch" and result.first_difference == LO + 4 * W + 91,
                    f"missing last prime found ({result})")
    return passed


def check_lonely(tmp):
    passed = True
    p = _write(tmp, 7, "P", PRIMES, 2000)
    result, _ = _quiet(dp_verify.reconcile, tmp, FLOOR, p)
    passed &= check(result.status == "no_d" and os.path.exists(p), "P without D is left alone")
    d = _write(tmp, 8, "D", PRIMES, 1000)
    result, _ = _quiet(dp_verify.reconcile_d, tmp, FLOOR, d)
    passed &= check(result.status == "no_p" and os.path.exists(d), "D without P is left alone")
    return passed


def check_floor(tmp):
    passed = True
    _write(tmp, 10, "D", PRIMES, 1000)
    _write(tmp, 10, "P", PRIMES, 2000)
    _write(tmp, 11, "D", PRIMES, 1000)
    _write(tmp, 11, "P", PRIMES[1:], 2000)
    summary, _ = _quiet(dp_verify.verify_floor, tmp, FLOOR)
    # P windows now: 4 (mismatch), 7 (no D), 10 (equal), 11 (mismatch)
    passed &= check(summary == {"equal": 1, "mismatch": 2, "no_d": 1},
                    f"verify_floor counts every P window ({summary})")
    return passed


def main():
    tmp = tempfile.mkdtemp(prefix="dp_verify_")
    try:
        passed = check_counterparts(tmp)
        passed &= check_equal(tmp)
        passed &= check_mismatch(tmp)
        passed &= check_lonely(tmp)
        passed &= check_floor(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
