"""Engine advisor: the engine a run of a given floor and width should use, from the time model
(time_model.py: prep + span * per-number cost + writing, calibrated from benchmark_log.csv).

Every own engine (engine_options.ENGINES) that fits the floor, the width and the RAM budget is
an option with its estimated run time; an engine with fewer than two logged rows is estimated
from its seed (engine_advisor_seeds.py) and flagged estimated, one with neither is left out.
pt1 tests with BPSW above the deterministic Miller-Rabin bound, so a run reaching past it is
probabilistic; every other option is deterministic.

choose(): the proposal is the fastest deterministic option, unless pt1 with BPSW is faster
by at least the offset (t(deterministic) / t(pt1) >= offset; the default is arbitrary and
user-adjustable), or no deterministic option fits. The proposal is advice: nothing switches
the engine by itself.

Guest tools (GUEST_ENGINES, Quick-gen modes of programs Atlas does not own) are never an
option and never the proposal: a guest that the log calibrates, that fits the floor and
that is faster than the fastest deterministic option is reported next to the proposal with
its speed-up (both timed without writing: a guest writes nothing into the storage). Without
guests every proposal stays the same.
"""
import math
from collections import namedtuple

import pt1_plan
import pseudosquares_const
from benchmark_log_schema import ENGINE_PSEUDOSQUARES_COUNT
from storage_kinds import MR_DET_BOUND

from . import engine_advisor_seeds, engine_options, time_model

DEFAULT_BPSW_OFFSET = engine_options.DEFAULT_BPSW_OFFSET
GUEST_ENGINES = (ENGINE_PSEUDOSQUARES_COUNT,)
_GUEST_MAX_FLOOR = {ENGINE_PSEUDOSQUARES_COUNT: pseudosquares_const.MAX_FLOOR}

REASON_DETERMINISTIC = "deterministic"
REASON_BPSW_FASTER = "bpsw_faster"
REASON_NO_DETERMINISTIC = "no_deterministic"

Option = namedtuple("Option", "engine seconds deterministic estimated")
Guest = namedtuple("Guest", "engine seconds rival rival_seconds speedup")
Advice = namedtuple(
    "Advice", "engine seconds deterministic estimated reason ratio deterministic_engine "
    "deterministic_seconds options guest", defaults=((), None))


def parse_offset(raw):
    """The offset as a float >= 1; DEFAULT_BPSW_OFFSET when blank; None when invalid."""
    text = "" if raw is None else str(raw).strip()
    if not text:
        return DEFAULT_BPSW_OFFSET
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) and value >= 1.0 else None


def calibrations(samples, pt1_b=0, guests=GUEST_ENGINES):
    """{engine: (Calibration, estimated)}: each own engine's calibration from `samples`, or
    from its seed (estimated True); each guest's from `samples` only. Engines with neither
    are absent."""
    result = {}
    for engine in engine_options.ENGINES:
        b = pt1_b if engine in engine_options.PT1_ENGINES else 0
        cal = time_model.calibrate(samples, engine, b)
        if cal is not None:
            result[engine] = (cal, False)
            continue
        cal = time_model.calibrate(engine_advisor_seeds.seed_samples(engine), engine, b)
        if cal is not None:
            result[engine] = (cal, True)
    for engine in guests:
        cal = time_model.calibrate(samples, engine)
        if cal is not None:
            result[engine] = (cal, False)
    return result


def _top(floor, windows):
    return 10 ** floor + windows * time_model.WINDOW_WIDTH


def _fits_floor(engine, floor, windows, pt1_b):
    top = _top(floor, windows)
    if engine in _GUEST_MAX_FLOOR:
        return floor <= _GUEST_MAX_FLOOR[engine]
    if windows > engine_options.max_windows_per_run(engine):
        return False
    if engine in engine_options.PT1_ENGINES:
        if not pt1_plan.MIN_FLOOR <= floor <= pt1_plan.MAX_FLOOR:
            return False
        if engine == engine_options.ENGINE_PT1_PSS:
            b = pt1_b if pt1_b > 0 else math.isqrt(math.isqrt(top))
            return pt1_plan.proof_b(b, top) <= pt1_plan.MAX_B
    return True


def _deterministic(engine, floor, windows):
    return engine != engine_options.ENGINE_PT1 or _top(floor, windows) <= MR_DET_BOUND


def _seconds(cals, engine, floor, windows, write_files, pt1_b):
    cal = cals[engine][0]
    b = pt1_b if engine in engine_options.PT1_ENGINES else 0
    return time_model.estimate(cal, engine, floor, windows, write_files, b).run_seconds


def options(cals, floor, windows, write_files, pt1_b=0, ram_fits=None):
    """[Option] of every own engine in `cals` that fits the floor, the width (its per-run
    cap) and `ram_fits(engine)` (None: no RAM limit), fastest first."""
    found = []
    for engine in engine_options.ENGINES:
        if engine not in cals or not _fits_floor(engine, floor, windows, pt1_b):
            continue
        if ram_fits is not None and not ram_fits(engine):
            continue
        seconds = _seconds(cals, engine, floor, windows, write_files, pt1_b)
        if seconds is not None:
            found.append(Option(engine, seconds, _deterministic(engine, floor, windows),
                                cals[engine][1]))
    return sorted(found, key=lambda o: o.seconds)


def choose(found, offset):
    """Advice from [Option] (see the module docstring), None without options."""
    if not found:
        return None
    det = min((o for o in found if o.deterministic), key=lambda o: o.seconds, default=None)
    bpsw = min((o for o in found if not o.deterministic), key=lambda o: o.seconds, default=None)
    if det is None:
        return Advice(bpsw.engine, bpsw.seconds, False, bpsw.estimated, REASON_NO_DETERMINISTIC,
                      None, None, None, tuple(found))
    if bpsw is not None and bpsw.seconds > 0 and det.seconds / bpsw.seconds >= offset:
        return Advice(bpsw.engine, bpsw.seconds, False, bpsw.estimated, REASON_BPSW_FASTER,
                      det.seconds / bpsw.seconds, det.engine, det.seconds, tuple(found))
    return Advice(det.engine, det.seconds, True, det.estimated, REASON_DETERMINISTIC, None,
                  det.engine, det.seconds, tuple(found))


def _guest(cals, advice, floor, windows, pt1_b, guests):
    """The fastest guest faster than the deterministic reference, timed without writing."""
    if advice.deterministic_engine is None:
        return None
    rival = _seconds(cals, advice.deterministic_engine, floor, windows, False, pt1_b)
    best = None
    for engine in guests:
        if engine not in cals or not _fits_floor(engine, floor, windows, pt1_b):
            continue
        seconds = _seconds(cals, engine, floor, windows, False, pt1_b)
        if seconds and rival and seconds < rival and (best is None or seconds < best.seconds):
            best = Guest(engine, seconds, advice.deterministic_engine, rival, rival / seconds)
    return best


def advise(samples, floor, windows, write_files, pt1_b=0, offset=DEFAULT_BPSW_OFFSET,
           ram_fits=None, guests=GUEST_ENGINES, cals=None):
    """Advice for one run of `windows` windows from 10^floor, None without options. `cals`
    reuses calibrations() of the same samples, pt1_b and guests."""
    if cals is None:
        cals = calibrations(samples, pt1_b, guests)
    advice = choose(options(cals, floor, windows, write_files, pt1_b, ram_fits), offset)
    if advice is None:
        return None
    return advice._replace(guest=_guest(cals, advice, floor, windows, pt1_b, guests))
