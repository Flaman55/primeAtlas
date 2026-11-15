"""Width advisor: the run width the Quick-gen line proposes for the Floor and Explore modes, next
to the engine proposal (engine_advisor.py). No tkinter.

A run's prep cost (every sieving prime up to sqrt of its end, time_model.py) does not depend on
its width, so a wider run spreads it over more numbers:
  - Benchmark (no storage writes), Floor or Explore mode: BENCHMARK_WINDOWS windows, lowered to
    the widest run that fits (cap); a wider run measures a higher sieving speed, while the prep
    time of one run stays the same. Never narrower than the typed width; the iterations stay.
  - Explore mode writing into the storage, more than one iteration: the same total range in
    fewer, wider runs, which saves whole preps: the fewest iterations the cap allows,
    ceil(total / cap), with the width rounded up so the total never shrinks. No proposal when
    the iteration count stays or the model times the new plan no faster.
  - Floor mode writing into the storage: the width is the person's choice, no proposal.
The proposal is advice: only its Use button writes the fields.
"""
from collections import namedtuple

BENCHMARK_WINDOWS = 10_000
"""Width a benchmark run is proposed (10^11 numbers); arbitrary, wide enough that the prep cost
no longer dominates the measured speed on the floors a benchmark usually covers."""

KIND_BENCHMARK = "benchmark"
KIND_EXPLORE = "explore"

WidthAdvice = namedtuple(
    "WidthAdvice", "kind windows iterations new_windows new_iterations seconds new_seconds "
    "speed new_speed")


def _field(estimate, windows, name):
    est = estimate(windows)
    return None if est is None else getattr(est, name)


def advise_width(mode, write_files, windows, iterations, cap, estimate):
    """WidthAdvice for the Quick-gen fields, or None. mode: the Quick-gen mode; windows and
    iterations: the typed width and iteration count (Floor mode: 1); cap: the widest run the
    engine and the RAM budget allow; estimate(windows): a time_model.Estimate of one run
    (run_seconds, numbers_per_second) or None without a calibration."""
    if mode not in ("floor", "explore") or min(windows, iterations, cap) < 1:
        return None
    if not write_files:
        target = min(BENCHMARK_WINDOWS, cap)
        if windows >= target:
            return None
        return WidthAdvice(KIND_BENCHMARK, windows, iterations, target, iterations, None, None,
                           _field(estimate, windows, "numbers_per_second"),
                           _field(estimate, target, "numbers_per_second"))
    if mode != "explore" or iterations < 2:
        return None
    total = windows * iterations
    new_iterations = -(-total // cap)
    if new_iterations >= iterations:
        return None
    new_windows = -(-total // new_iterations)
    run, new_run = (_field(estimate, windows, "run_seconds"),
                    _field(estimate, new_windows, "run_seconds"))
    seconds = None if run is None else iterations * run
    new_seconds = None if new_run is None else new_iterations * new_run
    if seconds is not None and new_seconds is not None and new_seconds >= seconds:
        return None
    return WidthAdvice(KIND_EXPLORE, windows, iterations, new_windows, new_iterations, seconds,
                       new_seconds, None, None)
