"""dp_verify: a D window proves or refutes the P window of the same offset.

Checks: counterpart paths map D <-> P within the same shard; an equal pair (different
generation timestamps) removes the P file, reports "equal" and lists the D window as D/P
in DP_PROVEN.txt (once, also when compared again); a differing pair keeps both
files, prints an ERROR line naming the window and the smallest number in only one list, and lists the
window in DP_MISMATCH.txt once even when compared twice; a later equal comparison removes
that line, while a mismatch of a D/P window drops its D/P entry; a P window without D and a D window without P are left alone; verify_floor()
runs the comparison over every P window of a floor and counts the outcomes;
reconcile_many() gives the outcome of reconcile() on every path (statuses, files, both
lists) with 1 and with several threads, writes each list once, prints one ERROR line per
mismatch and progress lines, and removes a proven P only after DP_PROVEN.txt lists it. Pure Python,
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


def _many_fixture(portal):
    """P windows 20..31: even = equal pair, 21/23 = mismatch, 25 = P without D; 33 = D
    without P (its P path is passed too); 27 was listed in DP_MISMATCH.txt and is now
    equal, 29 was D/P and now mismatches."""
    p_paths = []
    for idx in range(20, 32):
        if idx in (21, 23, 29):
            _write(portal, idx, "D", PRIMES, 1000)
            p_paths.append(_write(portal, idx, "P", PRIMES[:-1] + [97], 2000))
        elif idx == 25:
            p_paths.append(_write(portal, idx, "P", PRIMES, 2000))
        else:
            _write(portal, idx, "D", PRIMES, 1000)
            p_paths.append(_write(portal, idx, "P", PRIMES, 2000))
    d33 = _write(portal, 33, "D", PRIMES, 1000)
    p_paths.append(dp_verify.counterpart_p_path(d33))
    sk.add_proven_tags(portal, FLOOR, {"PRIME_WINDOW_10p25_off_290M"})
    os.makedirs(os.path.join(portal, f"10p{FLOOR}"), exist_ok=True)
    with open(os.path.join(portal, f"10p{FLOOR}", dp_verify.MISMATCH_FILENAME), "w",
              encoding="utf-8") as f:
        f.write("PRIME_WINDOW_10p25_off_270M first_difference=1 d_count=6 p_count=6\n")
    return p_paths


def _snapshot(portal):
    files = sorted(os.path.relpath(os.path.join(d, n), portal)
                   for d, _s, names in os.walk(portal) for n in names)
    return files, sk.read_proven_tags(portal, FLOOR), _mismatch_lines(portal)


def check_many():
    """reconcile_many() gives the outcome of reconcile() on every path, with one write of
    each list and progress lines; the same with 1 and with several threads."""
    passed = True
    reference = tempfile.mkdtemp(prefix="dp_many_ref_")
    try:
        paths = _many_fixture(reference)
        statuses = {}
        for p in paths:
            status = _quiet(dp_verify.reconcile, reference, FLOOR, p)[0].status
            statuses[status] = statuses.get(status, 0) + 1
        want = _snapshot(reference)
    finally:
        shutil.rmtree(reference, ignore_errors=True)
    for workers in (1, 5):
        tmp = tempfile.mkdtemp(prefix="dp_many_")
        writes = {"proven": 0, "mismatch": 0}
        real_proven, real_mismatch = sk._write_proven_tags, dp_verify._write_mismatch_lines

        def _count_proven(*args):
            writes["proven"] += 1
            return real_proven(*args)

        def _count_mismatch(*args):
            writes["mismatch"] += 1
            return real_mismatch(*args)

        try:
            paths = _many_fixture(tmp)
            sk._write_proven_tags, dp_verify._write_mismatch_lines = _count_proven, _count_mismatch
            lines = []
            summary, out = _quiet(dp_verify.reconcile_many, tmp, FLOOR, paths, workers,
                                  lines.append)
            sk._write_proven_tags, dp_verify._write_mismatch_lines = real_proven, real_mismatch
            passed &= check(summary == statuses,
                            f"{workers} thread(s): same statuses as reconcile() ({summary})")
            passed &= check(_snapshot(tmp) == want,
                            f"{workers} thread(s): same files, D/P list and mismatch list")
            passed &= check(writes == {"proven": 1, "mismatch": 1},
                            f"{workers} thread(s): each list written once ({writes})")
            passed &= check(out.count("[ERROR] D/P mismatch") == 3,
                            f"{workers} thread(s): one ERROR line per mismatch")
            passed &= check(lines and all(ln.startswith(dp_verify.PROGRESS_PREFIX) for ln in lines)
                            and f"{len(paths)}/{len(paths)}" in lines[-1],
                            f"{workers} thread(s): progress lines ({lines[-1] if lines else None})")
        finally:
            sk._write_proven_tags, dp_verify._write_mismatch_lines = real_proven, real_mismatch
            shutil.rmtree(tmp, ignore_errors=True)
    tmp = tempfile.mkdtemp(prefix="dp_many_empty_")
    try:
        lines = []
        summary, _ = _quiet(dp_verify.reconcile_many, tmp, FLOOR, [], 4, lines.append)
        passed &= check(summary == {} and lines == [] and not os.path.exists(sk.proven_path(tmp, FLOOR)),
                        "no paths: empty summary, no progress, no list written")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return passed


def check_removal_after_list(tmp):
    """The P file of an equal pair goes only after DP_PROVEN.txt lists its D window, so an
    interruption never leaves a removed P without its D/P entry."""
    _write(tmp, 40, "D", PRIMES, 1000)
    p = _write(tmp, 40, "P", PRIMES, 2000)
    seen = []
    real_remove = dp_verify.os.remove

    def _remove(path):
        if path == p:
            seen.append("PRIME_WINDOW_10p25_off_400M" in sk.read_proven_tags(tmp, FLOOR))
        return real_remove(path)

    dp_verify.os.remove = _remove
    try:
        _quiet(dp_verify.reconcile_many, tmp, FLOOR, [p], 2, None)
    finally:
        dp_verify.os.remove = real_remove
    return check(seen == [True], f"P removed after its D/P entry is written ({seen})")


def main():
    tmp = tempfile.mkdtemp(prefix="dp_verify_")
    try:
        passed = check_counterparts(tmp)
        passed &= check_equal(tmp)
        passed &= check_mismatch(tmp)
        passed &= check_lonely(tmp)
        passed &= check_floor(tmp)
        passed &= check_removal_after_list(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    passed &= check_many()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
