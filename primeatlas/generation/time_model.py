"""Time model of one sieve run, calibrated from benchmark_log.csv: how the run width (windows
per run) and the floor set the prep cost, the speed and the total time.

A run of span S numbers ending at `top` at floor f costs
    prep  = k(f) * pi(L)      sieve = m(f) * S      write = w(f) * S (when files are written)
where L is the largest sieving prime the engine needs (prep_limit(): isqrt(top) for v4.1
and v5, the B bound for pt1, raised for pt1-pss's proof). prep is the per-run fixed cost F (iterating every sieving
prime up to L and its phase), so a wider run amortizes it and a floor up multiplies it by
about 3; m is the marking cost per number, which grows with the floor (bucketed hits of
large primes); w is the write cost per number.

calibrate() derives k, m and w for every floor the engine has rows of:
  - a floor with runs of two or more widths: F and m by least squares of the sieve time
    against the span on that floor alone;
  - a floor with one width: m from a baseline fit over all the engine's rows (least
    squares on the relative error over every subset of the terms run, prime * pi(L),
    number * S, number * S * ln ln L with non-negative coefficients; the smallest subset
    within FIT_TOLERANCE of the best worst-case error), and F as the rest of the time
    (when the rest is negative: F = 0 and m = time / span);
  - w as the wall time per number the floor's file-writing runs took beyond prep and
    sieving (total_seconds based: writing may overlap sieving, so the engines'
    write_seconds busy time is not added); a floor without such runs takes the nearest
    floor's w.
Every measured run is so reproduced; k, m and w of other floors are interpolated
log-linearly in the floor between measured ones and held at the nearest one outside them.
pi(x) is exact at powers of ten (KNOWN_PI_10N, the engine's table) and Riemann's R(x)
elsewhere, which is off by less than 1e-7 relative at the sizes a floor needs.
"""
import csv
import itertools
import math
from collections import namedtuple

import pt1_plan

from ..research.pi_approx_window import riemann_r
from .run_budget import ENGINE_PT1, ENGINE_PT1_PSS
from .window_planning import QUICK_GEN_MAX_WINDOW_WIDTH

WINDOW_WIDTH = QUICK_GEN_MAX_WINDOW_WIDTH
LOW_FLOOR_CUTOFF = 7          # floors 0..6 run as one combined range, not floor-sized runs
FIT_TOLERANCE = 0.01          # a smaller term subset wins when its worst error is this close
FLOOR_SAMPLE_RUNS = 64        # runs evaluated across a floor for its total time

# pi(10^n), mirrored from prime_sieve/sieving_prime_count_v5.py (kept equal by
# unitTests/test_time_model.py): the GUI does not import engine modules.
KNOWN_PI_10N = {
    1: 4,
    2: 25,
    3: 168,
    4: 1229,
    5: 9592,
    6: 78498,
    7: 664579,
    8: 5761455,
    9: 50847534,
    10: 455052511,
    11: 4118054813,
    12: 37607912018,
    13: 346065536839,
    14: 3204941750802,
    15: 29844570422669,
}
_POWER_OF_TEN = {10 ** n: value for n, value in KNOWN_PI_10N.items()}

TERMS = ("run", "prime", "number", "number_lnln")

Sample = namedtuple(
    "Sample", "engine floor span top sieve_seconds write_seconds write_files total_seconds "
    "version", defaults=("",))
FloorPoint = namedtuple("FloorPoint",
                        "floor prime_seconds number_seconds write_seconds_per_number")
Calibration = namedtuple("Calibration", "engine points rows floors spans max_error version",
                         defaults=(None,))
MeasuredRuns = namedtuple("MeasuredRuns", "count windows seconds model_seconds")
Estimate = namedtuple(
    "Estimate",
    "span limit primes primes_exact prep_seconds sieve_seconds write_seconds run_seconds "
    "window_seconds numbers_per_second extrapolated write_known")


def prime_count(x):
    """(pi(x), exact): exact from KNOWN_PI_10N at a power of ten, else round(R(x))."""
    x = int(x)
    if x < 2:
        return 0, True
    if x in _POWER_OF_TEN:
        return _POWER_OF_TEN[x], True
    return int(round(riemann_r(x))), False


def prep_limit(engine, top, pt1_b=0):
    """Largest sieving prime bound of a run ending at `top`: isqrt(top) for v4.1, v5 and v6;
    for pt1 the B knob, or floor(top^(1/4)) when the knob is 0; for pt1-pss that B raised to
    the smallest bound its proof accepts (pt1_plan.proof_b())."""
    if engine in (ENGINE_PT1, ENGINE_PT1_PSS):
        b = pt1_b if pt1_b > 0 else math.isqrt(math.isqrt(top))
        return pt1_plan.proof_b(b, top) if engine == ENGINE_PT1_PSS else b
    return math.isqrt(top)


def _lnln(limit):
    return math.log(math.log(max(limit, 16)))


def _features(engine, span, top, pt1_b=0):
    limit = prep_limit(engine, top, pt1_b)
    primes = prime_count(limit)[0]
    return {"run": 1.0, "prime": float(primes), "number": float(span),
            "number_lnln": span * _lnln(limit)}


def read_samples(csv_path):
    """Usable rows of a benchmark_log.csv: completed runs with an engine, a span and a sieve
    time, at floors from LOW_FLOOR_CUTOFF up. [] for a missing or unreadable file."""
    samples = []
    try:
        with open(csv_path, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                sample = _sample(row)
                if sample is not None:
                    samples.append(sample)
    except (OSError, csv.Error):
        return []
    return samples


def _float_or_none(text):
    try:
        return float(text or "")
    except ValueError:
        return None


def _sample(row):
    engine = (row.get("engine") or "").strip()
    if not engine or (row.get("run_status") or "").strip() == "stopped":
        return None
    try:
        floor = int(row["base_exponent"])
        span = int(float(row["numbers_processed"]))
        windows = int(row["windows_written"])
        idx_start = int(row["target_idx_start"])
        sieve = float(row["sieve_seconds"])
    except (KeyError, TypeError, ValueError):
        return None
    if floor < LOW_FLOOR_CUTOFF or span <= 0 or windows <= 0 or sieve <= 0:
        return None
    write = _float_or_none(row.get("write_seconds"))
    # base_gen_seconds of v4.1/v5 rows times the optional pi(L) count (a diagnostic the
    # Generation form can switch on), not generation work.
    total = _float_or_none(row.get("total_seconds"))
    if total is None:
        total = sieve + (write or 0.0)
    else:
        total -= _float_or_none(row.get("base_gen_seconds")) or 0.0
    # pt1's verification (proof_seconds) is no sieving: the model times the P run alone.
    total -= _float_or_none(row.get("proof_seconds")) or 0.0
    top = 10 ** floor + idx_start * (span // windows) + span
    return Sample(engine, floor, span, top, sieve, write,
                  (row.get("write_files") or "").strip() == "1", total,
                  (row.get("engine_version") or "").strip())


def _solve(matrix, rhs):
    """Least squares for matrix * c = rhs via normal equations on max-scaled columns; None
    when singular."""
    n = len(matrix[0])
    scale = [max(abs(r[i]) for r in matrix) or 1.0 for i in range(n)]
    rows = [[r[i] / scale[i] for i in range(n)] for r in matrix]
    a = [[sum(r[i] * r[j] for r in rows) for j in range(n)] for i in range(n)]
    b = [sum(r[i] * y for r, y in zip(rows, rhs)) for i in range(n)]
    for i in range(n):
        pivot = max(range(i, n), key=lambda k: abs(a[k][i]))
        a[i], a[pivot] = a[pivot], a[i]
        b[i], b[pivot] = b[pivot], b[i]
        if abs(a[i][i]) < 1e-12:
            return None
        for k in range(n):
            if k != i:
                factor = a[k][i] / a[i][i]
                a[k] = [x - factor * y for x, y in zip(a[k], a[i])]
                b[k] -= factor * b[i]
    return [b[i] / a[i][i] / scale[i] for i in range(n)]


def _baseline(own, engine, pt1_b):
    """Coefficients of the all-floors fit (see the module docstring), or None."""
    features = [_features(engine, s.span, s.top, pt1_b) for s in own]
    times = [s.sieve_seconds for s in own]
    fits = []
    for size in range(1, min(len(TERMS), len(own) - 1) + 1):
        for subset in itertools.combinations(TERMS, size):
            matrix = [[f[t] / y for t in subset] for f, y in zip(features, times)]
            coeffs = _solve(matrix, [1.0] * len(own))
            if coeffs is None or any(c < 0 for c in coeffs):
                continue
            error = max(abs(sum(c * f[t] for c, t in zip(coeffs, subset)) / y - 1)
                        for f, y in zip(features, times))
            fits.append((error, size, dict(zip(subset, coeffs))))
    if not fits:
        return None
    best = min(error for error, _size, _c in fits)
    return min((fit for fit in fits if fit[0] <= best + FIT_TOLERANCE),
               key=lambda fit: (fit[1], fit[0]))[2]


def _floor_fit(group, baseline, engine, pt1_b):
    """(F, m) of one floor's samples: least squares when they cover two or more widths,
    else m from the baseline and F as the rest of the time; both clamped to >= 0."""
    n = len(group)
    spans = [float(s.span) for s in group]
    times = [s.sieve_seconds for s in group]
    if len(set(spans)) >= 2:
        mean_s, mean_t = sum(spans) / n, sum(times) / n
        m = (sum((x - mean_s) * (y - mean_t) for x, y in zip(spans, times))
             / sum((x - mean_s) ** 2 for x in spans))
        prep = mean_t - m * mean_s
        if m < 0:
            return mean_t, 0.0
        if prep < 0:
            return 0.0, sum(times) / sum(spans)
        return prep, m
    limit = prep_limit(engine, group[0].top, pt1_b)
    m = baseline.get("number", 0.0) + baseline.get("number_lnln", 0.0) * _lnln(limit)
    prep = sum(t - m * x for x, t in zip(spans, times)) / n
    if prep < 0:
        return 0.0, sum(times) / sum(spans)
    return prep, m


def _write_extra(group, prep, m):
    """Wall time per number that writing adds on top of prep + sieving in the group's runs
    that wrote files (writing may overlap sieving), or None without such runs."""
    written = [s for s in group if s.write_files]
    if not written:
        return None
    extra = sum(s.total_seconds - prep - m * s.span for s in written)
    return max(0.0, extra / sum(s.span for s in written))


def calibration_rows(samples, engine):
    """(rows, version) that calibrate `engine`: the rows of its newest version (the version
    of its last row; the log is appended in run order) once that version has two rows, so
    a faster release is not averaged with the old one; else every row of the engine, with
    version None."""
    own = [s for s in samples if s.engine == engine]
    newest = own[-1].version if own else ""
    if newest:
        same = [s for s in own if s.version == newest]
        if len(same) >= 2:
            return same, newest
    return own, None


def calibrate(samples, engine, pt1_b=0):
    """Calibration of `engine` from calibration_rows(), or None with fewer than two rows."""
    own, version = calibration_rows(samples, engine)
    if len(own) < 2:
        return None
    baseline = _baseline(own, engine, pt1_b)
    if baseline is None:
        return None
    points = []
    for floor in sorted({s.floor for s in own}):
        group = [s for s in own if s.floor == floor]
        prep, m = _floor_fit(group, baseline, engine, pt1_b)
        primes = sum(prime_count(prep_limit(engine, s.top, pt1_b))[0] for s in group) / len(group)
        points.append(FloorPoint(floor, prep / primes if primes else 0.0, m,
                                 _write_extra(group, prep, m)))
    known = [p for p in points if p.write_seconds_per_number is not None]
    if known:
        points = [p if p.write_seconds_per_number is not None else p._replace(
            write_seconds_per_number=min(known, key=lambda q: abs(q.floor - p.floor))
            .write_seconds_per_number) for p in points]
    calibration = Calibration(engine, tuple(points), len(own),
                              (min(s.floor for s in own), max(s.floor for s in own)),
                              (min(s.span for s in own), max(s.span for s in own)), 0.0,
                              version)
    error = 0.0
    for s in own:
        est = estimate(calibration, engine, s.floor, s.span // WINDOW_WIDTH, s.write_files,
                       pt1_b, start=s.top - s.span)
        if s.total_seconds > 0:
            error = max(error, abs(est.run_seconds / s.total_seconds - 1))
    return calibration._replace(max_error=error)


def _interpolate(points, floor, field):
    """`field` of the calibrated points at `floor`: log-linear between the neighbours, the
    nearest point's value outside them."""
    values = [(p.floor, getattr(p, field)) for p in points]
    if floor <= values[0][0]:
        return values[0][1]
    if floor >= values[-1][0]:
        return values[-1][1]
    for (f0, v0), (f1, v1) in zip(values, values[1:]):
        if f0 <= floor <= f1:
            if v0 is None or v1 is None:
                return v1 if v0 is None else v0
            share = (floor - f0) / (f1 - f0)
            if v0 > 0 and v1 > 0:
                return math.exp(math.log(v0) + share * (math.log(v1) - math.log(v0)))
            return v0 + share * (v1 - v0)
    return values[-1][1]


def estimate(calibration, engine, floor, windows, write_files, pt1_b=0, start=None):
    """Estimate of one run of `windows` windows from `start` (default 10^floor). Without a
    calibration only span, limit and the prime count are given; the times are None."""
    span = windows * WINDOW_WIDTH
    first = 10 ** floor if start is None else start
    top = first + span
    limit = prep_limit(engine, top, pt1_b)
    primes, exact = prime_count(limit)
    if calibration is None:
        return Estimate(span, limit, primes, exact, None, None, None, None, None, None,
                        False, False)
    points = calibration.points
    prep = _interpolate(points, floor, "prime_seconds") * primes
    sieve = _interpolate(points, floor, "number_seconds") * span
    write_rate = _interpolate(points, floor, "write_seconds_per_number")
    write_known = write_rate is not None
    write = span * write_rate if write_files and write_known else 0.0
    run = prep + sieve + write
    lo_floor, hi_floor = calibration.floors
    lo_span, hi_span = calibration.spans
    extrapolated = not (lo_floor <= floor <= hi_floor and lo_span <= span <= hi_span)
    return Estimate(span, limit, primes, exact, prep, sieve, write, run, run / windows,
                    span / run if run > 0 else None, extrapolated, write_known)


def measured_runs(samples, engine, floor, pt1_b=0):
    """MeasuredRuns of `engine` at `floor` in the log: run count, windows, measured seconds
    and the model's seconds for the same runs (None without a calibration or runs)."""
    own = [s for s in samples if s.engine == engine and s.floor == floor]
    calibration = calibrate(samples, engine, pt1_b)
    model = None
    if calibration is not None and own:
        model = sum(estimate(calibration, engine, floor, s.span // WINDOW_WIDTH, s.write_files,
                             pt1_b, start=s.top - s.span).run_seconds for s in own)
    return MeasuredRuns(len(own), sum(s.span // WINDOW_WIDTH for s in own),
                        sum(s.total_seconds for s in own), model)


def floor_windows(floor):
    """Windows of WINDOW_WIDTH in floor [10^floor, 10^(floor+1))."""
    return 9 * 10 ** floor // WINDOW_WIDTH


def floor_seconds(calibration, engine, floor, windows, write_files, pt1_b=0):
    """Time to generate the whole floor in runs of `windows` windows: the sum over its runs,
    from FLOOR_SAMPLE_RUNS evenly spaced runs when there are more. None without calibration."""
    if calibration is None:
        return None
    total_windows = floor_windows(floor)
    windows = max(1, min(windows, total_windows))
    runs = -(-total_windows // windows)
    base = 10 ** floor
    if runs <= FLOOR_SAMPLE_RUNS:
        total = 0.0
        for i in range(runs):
            width = min(windows, total_windows - i * windows)
            total += estimate(calibration, engine, floor, width, write_files, pt1_b,
                              start=base + i * windows * WINDOW_WIDTH).run_seconds
        return total
    step = runs / FLOOR_SAMPLE_RUNS
    sampled = sum(estimate(calibration, engine, floor, windows, write_files, pt1_b,
                           start=base + int((i + 0.5) * step) * windows * WINDOW_WIDTH).run_seconds
                  for i in range(FLOOR_SAMPLE_RUNS))
    return sampled * runs / FLOOR_SAMPLE_RUNS
