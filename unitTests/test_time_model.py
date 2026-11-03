"""time_model estimates how a run's width and its floor set the generation time.

Checks: pi(x) is exact (and flagged exact) at powers of ten from the mirrored table, which
equals prime_sieve/sieving_prime_count_v5.KNOWN_PI_10N, and R(x) elsewhere (within 0.1 %
of a sieved count, flagged approximate); the prep limit is isqrt(top) for v4.1/v5 and the
pt1 B knob or the integer fourth root of top for pt1; the sieving-prime count grows about
3x per floor; benchmark rows are read without raising (missing file, stopped runs, rows
without an engine, numbers or sieve time, and combined low floors are skipped) and each
row's top is the floor base plus the window offset plus the span, and its time is
total_seconds without the optional sieving-prime count (base_gen_seconds); calibration recovers
synthetic coefficients, reproduces measured runs (two widths on one floor split prep and
per-number cost, floors between measured ones interpolate), reports a floor's measured runs
and the model's time for them, needs at least two rows of the engine and reports rows, floors and
its worst relative error; an estimate splits a run into prep, sieving and writing, its
speed grows with the width while prep costs anything, writing off removes the write time,
one floor up multiplies the prep by the sieving-prime ratio, a floor outside the
calibrated ones is flagged extrapolated, and without calibration only the prime count is
given; the whole-floor time is one run when the width covers the floor and falls as the
width grows. Pure Python:
    python unitTests/test_time_model.py
"""
import ast
import csv
import math
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

from primeatlas.generation import time_model as tm  # noqa: E402
from primeatlas.generation.window_planning import QUICK_GEN_MAX_WINDOW_WIDTH  # noqa: E402
from benchmark_log_schema import BENCHMARK_FIELDNAMES  # noqa: E402

W = QUICK_GEN_MAX_WINDOW_WIDTH


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def _engine_table():
    path = os.path.join(ROOT, "prime_sieve", "sieving_prime_count_v5.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "KNOWN_PI_10N" for t in node.targets):
            return ast.literal_eval(node.value)
    return {}


def _sieve_count(limit):
    flags = bytearray([1]) * (limit + 1)
    flags[0:2] = b"\x00\x00"
    for p in range(2, math.isqrt(limit) + 1):
        if flags[p]:
            flags[p * p::p] = bytearray(len(flags[p * p::p]))
    return sum(flags)


def check_prime_count():
    passed = True
    engine = _engine_table()
    passed &= check(engine and all(engine.get(n) == v for n, v in tm.KNOWN_PI_10N.items()),
                    "KNOWN_PI_10N mirrors the engine table")
    passed &= check(max(tm.KNOWN_PI_10N) >= 15, "table reaches 10^15 (sqrt of floor 29's top)")
    value, exact = tm.prime_count(10 ** 14)
    passed &= check(value == 3204941750802 and exact, "pi(10^14) exact from the table")
    x = 1_000_003
    value, exact = tm.prime_count(x)
    truth = _sieve_count(x)
    passed &= check(not exact and abs(value - truth) / truth < 1e-3,
                    f"pi({x:,}) from R(x) within 0.1 % ({value:,} vs {truth:,})")
    passed &= check(tm.prime_count(1) == (0, True), "pi(1) = 0")
    ratios = []
    for floor in range(18, 29):
        hi = tm.prime_count(tm.prep_limit("v5", 10 ** (floor + 1)))[0]
        lo = tm.prime_count(tm.prep_limit("v5", 10 ** floor))[0]
        ratios.append(hi / lo)
    passed &= check(all(2.9 < r < 3.3 for r in ratios),
                    f"sieving primes grow ~3x per floor ({min(ratios):.2f}..{max(ratios):.2f})")
    return passed


def check_prep_limit():
    passed = True
    top = 10 ** 25 + 12345
    passed &= check(tm.prep_limit("v5", top) == math.isqrt(top), "v5 limit = isqrt(top)")
    passed &= check(tm.prep_limit("v4.1", top) == math.isqrt(top), "v4.1 limit = isqrt(top)")
    root4 = tm.prep_limit("pt1", top)
    passed &= check(root4 ** 4 <= top < (root4 + 1) ** 4, "pt1 default limit = 4th root of top")
    passed &= check(tm.prep_limit("pt1", top, pt1_b=1000) == 1000, "pt1 B knob wins when set")
    return passed


def _write_log(path, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BENCHMARK_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in BENCHMARK_FIELDNAMES})


def _row(engine, floor, windows, idx_start, sieve, write="1.0", status="completed",
         write_files="1"):
    return {"engine": engine, "base_exponent": str(floor), "windows_written": str(windows),
            "numbers_processed": str(windows * W), "target_idx_start": str(idx_start),
            "sieve_seconds": str(sieve), "write_seconds": write, "run_status": status,
            "write_files": write_files}


def check_read_samples():
    passed = True
    passed &= check(tm.read_samples(os.path.join(tempfile.gettempdir(), "no_such_log.csv")) == [],
                    "missing log -> no samples")
    folder = tempfile.mkdtemp(prefix="primeatlas_time_model_")
    path = os.path.join(folder, "benchmark_log.csv")
    _write_log(path, [
        _row("v5", 20, 1000, 2000, 3.5),
        _row("v5", 20, 1000, 3000, 3.5, status="stopped"),
        _row("", 20, 1000, 0, 3.5),
        {**_row("v5", 20, 1000, 0, 3.5), "numbers_processed": ""},
        {**_row("v5", 20, 1000, 0, 3.5), "sieve_seconds": ""},
        _row("v5", 6, 1, 0, 0.1),
        {**_row("pt1", 19, 1000, 0, 150.0), "run_status": "", "total_seconds": "151.6",
         "base_gen_seconds": "1.6"},
    ])
    samples = tm.read_samples(path)
    passed &= check(len(samples) == 2, f"two usable rows kept ({len(samples)})")
    s = samples[0]
    passed &= check(s.engine == "v5" and s.floor == 20 and s.span == 1000 * W
                    and s.top == 10 ** 20 + 2000 * W + 1000 * W,
                    "row top = floor base + window offset + span")
    passed &= check(s.sieve_seconds == 3.5 and s.write_seconds == 1.0 and s.write_files,
                    "row times and write flag parsed")
    passed &= check(s.total_seconds == 4.5, "total time = sieve + write when total_seconds is blank")
    passed &= check(abs(samples[1].total_seconds - 150.0) < 1e-9,
                    "total_seconds read without base_gen_seconds (the optional pi(L) count)")
    passed &= check(samples[1].engine == "pt1", "blank run_status counts as completed")
    with open(path, "w") as f:
        f.write("garbage\n\x00\x01")
    passed &= check(tm.read_samples(path) == [], "malformed log -> no samples")
    return passed


def _synthetic(engine, coeffs, write_rate):
    samples = []
    for floor, windows in ((13, 1000), (16, 1000), (19, 1000), (19, 10000), (25, 5000),
                           (27, 5000), (28, 44000)):
        span = windows * W
        top = 10 ** floor + span
        limit = tm.prep_limit(engine, top)
        sieve = (coeffs["run"] + coeffs["prime"] * tm.prime_count(limit)[0]
                 + coeffs["number"] * span)
        write = span / write_rate
        samples.append(tm.Sample(engine, floor, span, top, sieve, write, True, sieve + write))
    return samples


def check_calibration():
    passed = True
    coeffs = {"run": 2.0, "prime": 1e-9, "number": 2e-9}
    samples = _synthetic("v5", coeffs, 5e8)
    cal = tm.calibrate(samples, "v5")
    passed &= check(cal is not None, "calibrates from synthetic v5 rows")
    if cal is None:
        return False
    passed &= check(cal.rows == len(samples) and cal.floors == (13, 28),
                    "reports row count and floor range")
    passed &= check(cal.max_error < 0.01, f"worst relative error ~0 ({cal.max_error:.4f})")
    passed &= check(all(abs(p.write_seconds_per_number - 1 / 5e8) < 1e-15 for p in cal.points),
                    "write time per number from the rows")
    for s in samples:
        est = tm.estimate(cal, "v5", s.floor, s.span // W, True, start=s.top - s.span)
        if abs(est.sieve_seconds + est.prep_seconds - s.sieve_seconds) > 0.01 * s.sieve_seconds:
            passed &= check(False, f"prediction matches floor {s.floor}")
    passed &= check(tm.calibrate(samples, "pt1") is None, "no rows of the engine -> None")
    passed &= check(tm.calibrate(samples[:1], "v5") is None, "one row -> None")
    return passed


def check_estimate():
    passed = True
    cal = tm.calibrate(_synthetic("v5", {"run": 2.0, "prime": 1e-9, "number": 2e-9}, 5e8), "v5")
    small = tm.estimate(cal, "v5", 25, 1000, True)
    big = tm.estimate(cal, "v5", 25, 10000, True)
    passed &= check(small.span == 1000 * W, "span = windows x 10^7")
    passed &= check(abs(small.run_seconds - (small.prep_seconds + small.sieve_seconds
                                             + small.write_seconds)) < 1e-9,
                    "run = prep + sieve + write")
    passed &= check(abs(small.window_seconds - small.run_seconds / 1000) < 1e-12,
                    "window time = run / windows")
    passed &= check(abs(small.numbers_per_second - small.span / small.run_seconds) < 1e-6,
                    "speed = span / run time")
    passed &= check(big.numbers_per_second > small.numbers_per_second,
                    "wider run -> higher speed while prep costs anything")
    no_write = tm.estimate(cal, "v5", 25, 1000, False)
    passed &= check(no_write.write_seconds == 0 and no_write.run_seconds < small.run_seconds,
                    "writing off removes the write time")
    above = tm.estimate(cal, "v5", 30, 1000, True)
    up = tm.estimate(cal, "v5", 31, 1000, True)
    ratio = up.primes / above.primes
    passed &= check(abs(up.prep_seconds / above.prep_seconds - ratio) < 1e-6 and 2.9 < ratio < 3.3,
                    f"above the measured floors one floor up multiplies the prep by the prime "
                    f"ratio ({ratio:.2f})")
    passed &= check(not small.extrapolated and tm.estimate(cal, "v5", 31, 1000, True).extrapolated,
                    "floor outside the calibrated range flagged extrapolated")
    bare = tm.estimate(None, "v5", 25, 1000, True)
    passed &= check(bare.run_seconds is None and bare.primes == small.primes,
                    "no calibration -> prime count only")
    return passed


def _deep_rows():
    """Two widths at floor 29 and one at floor 25, from a real v5 log: per-number cost at
    floor 29 is far above the shallow floors'."""
    rows = []
    for floor, windows, idx, sieve, write in ((29, 50000, 0, 9729.4, 826.5),
                                              (29, 70000, 50000, 10524.9, 1178.5),
                                              (25, 5000, 0, 198.6, 89.2),
                                              (13, 1000, 5000, 0.95, 24.6),
                                              (13, 10000, 6000, 13.25, 253.2)):
        span = windows * W
        top = 10 ** floor + idx * W + span
        rows.append(tm.Sample("v5", floor, span, top, sieve, write, True, sieve + write))
    return rows


def check_local_calibration():
    passed = True
    rows = _deep_rows()
    cal = tm.calibrate(rows, "v5")
    passed &= check(cal is not None and cal.max_error < 0.05,
                    f"every measured run reproduced within 5 % ({cal.max_error if cal else None}; "
                    f"floor 13 grows faster than linearly with the width)")
    for s in rows:
        est = tm.estimate(cal, "v5", s.floor, s.span // W, True, start=s.top - s.span)
        if abs(est.run_seconds - s.total_seconds) > 0.05 * s.total_seconds:
            passed &= check(False, f"floor {s.floor} {s.span // W} windows reproduced "
                                   f"({est.run_seconds:.0f} vs {s.total_seconds:.0f})")
    m = (10524.9 - 9729.4) / (20000 * W)
    prep = 9729.4 - m * 50000 * W
    wide = tm.estimate(cal, "v5", 29, 100000, False)
    passed &= check(abs(wide.sieve_seconds - m * 100000 * W) < 0.01 * wide.sieve_seconds
                    and abs(wide.prep_seconds - prep) < 0.02 * prep,
                    f"two widths on a floor split prep and per-number cost "
                    f"(prep {wide.prep_seconds:.0f} ~ {prep:.0f}, sieve {wide.sieve_seconds:.0f})")
    mid = tm.estimate(cal, "v5", 27, 5000, False)
    lo = tm.estimate(cal, "v5", 25, 5000, False)
    hi = tm.estimate(cal, "v5", 29, 5000, False)
    passed &= check(lo.sieve_seconds < mid.sieve_seconds < hi.sieve_seconds,
                    "per-number cost between measured floors lies between theirs")
    runs = tm.measured_runs(rows, "v5", 29)
    passed &= check(runs.count == 2 and runs.windows == 120000
                    and abs(runs.seconds - (9729.4 + 826.5 + 10524.9 + 1178.5)) < 1e-6,
                    "measured runs of a floor: count, windows, seconds")
    passed &= check(abs(runs.model_seconds - runs.seconds) < 0.01 * runs.seconds,
                    "model time of the measured runs")
    passed &= check(tm.measured_runs(rows, "v5", 27).count == 0, "floor without runs -> 0")
    return passed


def check_floor_seconds():
    passed = True
    cal = tm.calibrate(_synthetic("v5", {"run": 2.0, "prime": 1e-9, "number": 2e-9}, 5e8), "v5")
    floor_windows = 9 * 10 ** 12 // W
    one = tm.floor_seconds(cal, "v5", 12, floor_windows, True)
    run = tm.estimate(cal, "v5", 12, floor_windows, True)
    passed &= check(one is not None and abs(one - run.run_seconds) < 1e-6 * one,
                    "width covering the floor -> one run")
    narrow = tm.floor_seconds(cal, "v5", 25, 1000, True)
    wide = tm.floor_seconds(cal, "v5", 25, 10000, True)
    passed &= check(narrow > wide > 0, "whole floor gets faster with a wider run")
    passed &= check(tm.floor_seconds(None, "v5", 25, 1000, True) is None,
                    "no calibration -> no floor time")
    return passed


def main():
    passed = check_prime_count()
    passed &= check_prep_limit()
    passed &= check_read_samples()
    passed &= check_calibration()
    passed &= check_estimate()
    passed &= check_local_calibration()
    passed &= check_floor_seconds()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
