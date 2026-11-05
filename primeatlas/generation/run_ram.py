"""Predicted RAM of one run and the widest run that fits the RAM budget (the time simulation's
RAM line and width-slider cap).

The prediction is run_budget.run_footprint_bytes() with the knobs the run launches with:
choice_for(windows) gives the engine_options.EngineChoice at that width, so an auto knob
profile's bucket memory follows the width. engine_options.recommend() differs on purpose:
it may lower the bucket memory to fit, which the run only uses once Auto has written it
into the form. pt1 holds no run-sized buffer and has no prediction.
"""
from . import engine_options, run_budget


def run_ram_bytes(choice, windows, window_m):
    """Peak memory of one run of `windows` windows with this EngineChoice; None for pt1."""
    if choice.engine == engine_options.ENGINE_PT1:
        return None
    bucket_key = engine_options.bucket_knob(choice.engine)
    bucket_mb = choice.knobs[bucket_key] if bucket_key else 0
    return run_budget.run_footprint_bytes(choice.engine, windows, window_m, bucket_mb)


def budget_bytes(choice, available_ram_bytes):
    """ram_budget_pct percent of the RAM free in WSL."""
    return available_ram_bytes * choice.knobs[engine_options.RAM_BUDGET_KNOB] / 100


def max_windows_in_budget(choice_for, available_ram_bytes, cap, window_m):
    """The widest run (at most `cap` windows) whose prediction fits the budget; 0 when not even
    one window fits, None for pt1 or without a RAM reading. The footprint grows with the
    width (an auto profile's bucket memory never shrinks as the width grows), so a binary
    search finds the edge."""
    if not available_ram_bytes or available_ram_bytes <= 0:
        return None
    first = choice_for(1)
    if first.engine == engine_options.ENGINE_PT1:
        return None
    budget = budget_bytes(first, available_ram_bytes)

    def fits(windows):
        return run_ram_bytes(choice_for(windows), windows, window_m) <= budget

    if not fits(1):
        return 0
    lo, hi = 1, cap
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo
