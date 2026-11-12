"""Seed rows of the engine advisor: measured runs that stand in for an engine's calibration
until benchmark_log.csv holds two rows of it (engine_advisor.calibrations()).

Each entry is (floor, numbers per run, seconds of the run), measured with files off on one
machine (16 threads); a run of the engine logged here replaces them. v7's rows were measured
with v7.2, whose time is almost all preparation (sieving primes up to sqrt(N)), so they fix
its per-floor prep cost; pt1 and pt1-pss have almost no preparation, their rows hold the
speed on each floor.
"""
from . import time_model

_V7 = ((28, 10 ** 9, 138.0), (28, 10 ** 10, 151.0), (28, 10 ** 11, 268.0),
       (30, 10 ** 9, 746.0), (30, 10 ** 10, 773.0), (30, 10 ** 11, 1059.0))
# Millions of numbers per second, measured on 10^10 numbers.
_PT1_PSS_RATE = {25: 21.0, 26: 18.0, 28: 17.0, 30: 15.4, 32: 14.4}
_PT1_RATE = {25: 170.0, 30: 151.5}
_RATE_SPANS = (10 ** 9, 10 ** 10)

SEED_ROWS = {
    "v7": _V7,
    "pt1-pss": tuple((floor, span, span / (rate * 1e6))
                     for floor, rate in _PT1_PSS_RATE.items() for span in _RATE_SPANS),
    "pt1": tuple((floor, span, span / (rate * 1e6))
                 for floor, rate in _PT1_RATE.items() for span in _RATE_SPANS),
}


def seed_samples(engine):
    """time_model.Sample rows of `engine`'s seed, [] for an engine without one."""
    return [time_model.Sample(engine, floor, span, 10 ** floor + span, seconds, None, False,
                              seconds)
            for floor, span, seconds in SEED_ROWS.get(engine, ())]
