"""Width advisor: the run width the Quick-gen line proposes for the Floor and Explore modes, next
to the engine proposal (engine_advisor.py). No tkinter.

A run's prep cost (every sieving prime up to sqrt of its end, time_model.py) does not depend on
its width, so a wider run spreads it over more numbers:
  - Benchmark (no storage writes), Floor or Explore mode: BENCHMARK_WINDOWS windows, lowered to
    the widest run that fits (cap); a wider run measures a higher sieving speed, while the prep
    time of one run stays the same. Never narrower than the typed width; the iterations stay.
  - Explore mode writing into the storage, more than one iteration: the same total range in
    fewer, wider runs, which saves whole preps (plan_split under the cap: the exact total first,
    else the fewest runs with a few windows more). No proposal when the iteration count does
    not drop or the model times the new plan no faster.
  - Floor mode writing into the storage: the width is the person's choice, no proposal.
The proposal is advice: only its Use button writes the fields.
"""
import math
from collections import namedtuple

BENCHMARK_WINDOWS = 10_000
"""Width a benchmark run is proposed (10^11 numbers); arbitrary, wide enough that the prep cost
no longer dominates the measured speed on the floors a benchmark usually covers."""

KIND_BENCHMARK = "benchmark"
KIND_EXPLORE = "explore"              # the exact total
KIND_EXPLORE_WIDER = "explore_wider"  # the fewest runs, a few windows more

SPLIT_EXACT = "exact"
SPLIT_WIDER = "wider"
SPLIT_TYPED = "typed"

SplitPlan = namedtuple("SplitPlan", "kind windows iterations")

WidthAdvice = namedtuple(
    "WidthAdvice", "kind windows iterations new_windows new_iterations seconds new_seconds "
    "speed new_speed")


def _field(estimate, windows, name):
    est = estimate(windows)
    return None if est is None else getattr(est, name)


def split_total(total, widest, max_iterations=None):
    """(windows, iterations) with windows x iterations == total exactly, windows at most widest
    and the fewest iterations such a split allows: the smallest divisor of total that is at
    least ceil(total / widest). None when that divisor passes max_iterations (None: no
    ceiling) or total or widest is below 1. A total with few divisors can split narrower than
    widest (997 windows under 500: 997 x 1)."""
    if total < 1 or widest < 1:
        return None
    least = -(-total // widest)
    best = total
    for small in range(1, math.isqrt(total) + 1):
        if total % small:
            continue
        for divisor in (small, total // small):
            if least <= divisor < best:
                best = divisor
    if max_iterations is not None and best > max_iterations:
        return None
    return total // best, best


def plan_split(windows, iterations, widest, max_iterations=None):
    """SplitPlan for Explore's typed width x iterations under the widest run, by priority:
    SPLIT_EXACT, the exact total (split_total), when it lowers the iterations or brings a width
    above widest under it; else SPLIT_WIDER, the fewest iterations ceil(total / widest) with
    the width rounded up (fewer extra windows than iterations), on the same condition; else
    SPLIT_TYPED, the typed values. max_iterations (None: no ceiling) bounds both splits."""
    over = windows > widest
    total = windows * iterations
    exact = split_total(total, widest, max_iterations)
    if exact is not None and (exact[1] < iterations or over):
        return SplitPlan(SPLIT_EXACT, *exact)
    fewest = -(-total // widest)
    if (max_iterations is None or fewest <= max_iterations) and (fewest < iterations or over):
        return SplitPlan(SPLIT_WIDER, -(-total // fewest), fewest)
    return SplitPlan(SPLIT_TYPED, windows, iterations)


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
    plan = plan_split(windows, iterations, cap)
    if plan.iterations >= iterations:
        return None
    new_windows, new_iterations = plan.windows, plan.iterations
    run, new_run = (_field(estimate, windows, "run_seconds"),
                    _field(estimate, new_windows, "run_seconds"))
    seconds = None if run is None else iterations * run
    new_seconds = None if new_run is None else new_iterations * new_run
    if seconds is not None and new_seconds is not None and new_seconds >= seconds:
        return None
    kind = KIND_EXPLORE if plan.kind == SPLIT_EXACT else KIND_EXPLORE_WIDER
    return WidthAdvice(kind, windows, iterations, new_windows, new_iterations, seconds,
                       new_seconds, None, None)
