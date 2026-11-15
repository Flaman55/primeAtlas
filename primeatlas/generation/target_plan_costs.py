"""Costs of the target planner (target_planner.py) from the time model: the seconds of one
Atlas run of the engine selected in the Generation form, writing into the storage, and of one
Pseudosquares print run, which writes nothing. No tkinter.

The Atlas engine has its logged calibration or, without one, its seed (flagged estimated, as
in the engine proposal). Pseudosquares takes its print calibration, else its count
calibration (pss_engine names which); a range past the program's stop has no cost.
"""
from collections import namedtuple

import pseudosquares_const
from benchmark_log_schema import ENGINE_PSEUDOSQUARES_COUNT, ENGINE_PSEUDOSQUARES_PRINT

from . import engine_advisor, engine_options, time_model

Costs = namedtuple("Costs", "atlas pss atlas_estimated pss_engine")

_PSS_ENGINES = (ENGINE_PSEUDOSQUARES_PRINT, ENGINE_PSEUDOSQUARES_COUNT)


def make_costs(samples, engine, pt1_b=0):
    """Costs for `engine` from benchmark_log samples (time_model.read_samples())."""
    width = time_model.WINDOW_WIDTH
    b = pt1_b if engine in engine_options.PT1_ENGINES else 0
    cal, atlas_estimated = None, False
    if engine in engine_options.ENGINES:
        found = engine_advisor.calibrations(samples, b, guests=()).get(engine)
        if found is not None:
            cal, atlas_estimated = found

    per_run_cap = engine_options.max_windows_per_run(engine) if cal is not None else 0
    by_end = {}  # (floor, end window) -> (prep seconds, seconds per window) or None

    def atlas(floor, idx, windows):
        """A run's prep depends only on its end, its sieving and writing on its span: one
        estimate per end gives every width ending there (the planner asks for many)."""
        if cal is None or windows > per_run_cap:
            return None
        end = idx + windows
        key = (floor, end)
        if key not in by_end:
            start = 10 ** floor + (end - 1) * width
            by_end[key] = None
            if engine_advisor.fits_floor(engine, floor, 1, b, start):
                est = time_model.estimate(cal, engine, floor, 1, True, b, start=start)
                by_end[key] = (est.prep_seconds, est.run_seconds - est.prep_seconds)
        line = by_end[key]
        return None if line is None else (line[0] + line[1] * windows, engine)

    pss_engine = pss_cal = None
    for name in _PSS_ENGINES:
        pss_cal = time_model.calibrate(samples, name)
        if pss_cal is not None:
            pss_engine = name
            break

    def pss(floor, idx, windows):
        if pss_cal is None or floor > pseudosquares_const.MAX_FLOOR:
            return None
        start = 10 ** floor + idx * width
        if start + windows * width - 1 > pseudosquares_const.MAX_STOP:
            return None
        return time_model.estimate(pss_cal, pss_engine, floor, windows, False,
                                   start=start).run_seconds

    return Costs(atlas, pss, atlas_estimated and cal is not None, pss_engine)
