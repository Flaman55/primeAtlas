"""Window count (and v5/v6 bucket memory) of one sieve run, from the floor and the RAM free in WSL.

pt1 and pt2 (partial sieve + primality test or proof) have neither limit: they fill the
per-run cap. For v4.1,
v5 and v6 two limits apply, the smaller one wins:
  - target: how long a tape pays off. Each run pays a fixed cost F (generating the sieving
    primes below L_final and one 128-bit phase division per prime), so a run should cover
    enough windows to amortize it. v4.1 stays at 1000 windows: its random atomic marking
    makes longer tapes no faster. v5 and v6 scale the tape with F, which grows like
    pi(isqrt(10^floor)) ~ L / ln L: the knob is the window count at floor 25 (10^7-wide
    windows), never below 1000;
  - RAM: the run's footprint must fit in safety_fraction of the RAM free in WSL (the
    Generation tab's RAM budget field, in percent). v4.1 holds a full bit buffer
    (window_m // 8 bytes per window); v5 an odd-only buffer (window_m // 16 per window), v6
    a wheel-30 buffer (one byte per 30 numbers), each plus its bucket memory and a fixed
    overhead (worker processes, sieving-prime iterators). When RAM is short, the buckets
    shrink first (down to MIN_BUCKET_MB, at most a quarter of the budget, never above the
    knob): a longer tape gains more than bigger buckets.

The defaults are arbitrary, picked by measurement (24 threads, floor 25: v5 5000 -> 20000
windows nearly doubles throughput, v6 at 37500 windows beats 20000 by 11 %); the 50 % RAM
budget is arbitrary, a margin for what the footprint model leaves out.
"""
import math
from collections import namedtuple

ENGINE_V41 = "v4.1"
ENGINE_V5 = "v5"
ENGINE_V6 = "v6"
ENGINE_V7 = "v7"                     # v6's buffer and footprint plus the jump gear
ENGINE_PT1 = "pt1"                   # no fixed cost, no run-sized buffer: never RAM-capped
ENGINE_PT2 = "pt2"                   # pt1's sieve with a proof: never RAM-capped either
PARTIAL_SIEVE_ENGINES = (ENGINE_PT1, ENGINE_PT2)
BUCKETED_ENGINES = (ENGINE_V5, ENGINE_V6, ENGINE_V7)
BASE_WINDOWS = 1000                  # target at shallow floors and v4.1's ceiling
DEFAULT_TARGET_WINDOWS_AT_25 = {ENGINE_V5: 20_000, ENGINE_V6: 40_000, ENGINE_V7: 40_000}
REFERENCE_WINDOW_M = 10_000_000      # window width the floor-25 knob is counted in
DEFAULT_BUCKET_MB = 8192             # matches work_plan_v5/_v6.DEFAULT_BUCKET_MB
WHEEL_NUMBERS_PER_BYTE = 30          # v6, v7 buffer: one byte per 30 numbers
MIN_BUCKET_MB = 64
BUCKET_BUDGET_SHARE = 4              # buckets take at most 1/4 of the RAM budget
V5_OVERHEAD_BYTES = 128 * 2 ** 20    # v5, v6: peak PSS minus buffer and buckets ~70 MiB
DEFAULT_SAFETY_FRACTION = 0.5        # stands in for whatever the model leaves out

RunBudget = namedtuple("RunBudget", "windows bucket_mb")


def _fixed_cost(base_exponent):
    """Relative fixed cost of a run at this floor: the sieving-prime count estimate L / ln L."""
    limit = max(3, math.isqrt(10 ** base_exponent))
    return limit / math.log(limit)


def target_windows(engine, base_exponent, window_m, target_at_25=None):
    """Windows one run should cover when RAM is no limit. target_at_25 None: the engine's
    default."""
    if engine not in BUCKETED_ENGINES:
        return BASE_WINDOWS
    if target_at_25 is None:
        target_at_25 = DEFAULT_TARGET_WINDOWS_AT_25[engine]
    tape = target_at_25 * REFERENCE_WINDOW_M * _fixed_cost(base_exponent) / _fixed_cost(25)
    return max(BASE_WINDOWS, math.ceil(tape / window_m))


def run_footprint_bytes(engine, windows, window_m, bucket_mb):
    """Peak memory of one run with this many windows."""
    if engine in (ENGINE_V6, ENGINE_V7):
        buffer = -(-windows * window_m // WHEEL_NUMBERS_PER_BYTE)
    elif engine == ENGINE_V5:
        buffer = windows * (window_m // 16)
    else:
        return windows * (window_m // 8)
    return buffer + bucket_mb * 2 ** 20 + V5_OVERHEAD_BYTES


def recommend_run(available_ram_bytes, engine, base_exponent, window_m,
                  bucket_mb=DEFAULT_BUCKET_MB, target_at_25=None,
                  safety_fraction=DEFAULT_SAFETY_FRACTION, max_windows=None):
    """RunBudget(windows, bucket_mb) for one run, or None without a RAM reading. windows is at
    least 1, even when not even one window fits (the caller still needs a value to show).
    bucket_mb is the knob's value, or less when RAM is short; v4.1 has no buckets and keeps
    the knob's value unused. target_at_25 None: the engine's default."""
    if not available_ram_bytes or available_ram_bytes <= 0:
        return None
    if engine in PARTIAL_SIEVE_ENGINES:
        return RunBudget(max_windows if max_windows is not None else BASE_WINDOWS, bucket_mb)
    budget = available_ram_bytes * safety_fraction
    target = target_windows(engine, base_exponent, window_m, target_at_25)
    if max_windows is not None:
        target = min(target, max_windows)
    if engine not in BUCKETED_ENGINES:
        fit = int(budget // run_footprint_bytes(engine, 1, window_m, 0))
        return RunBudget(max(1, min(target, fit)), bucket_mb)
    bucket_cap = int(budget / BUCKET_BUDGET_SHARE) // 2 ** 20
    bucket = min(bucket_mb, max(MIN_BUCKET_MB, bucket_cap))
    room = budget - run_footprint_bytes(engine, 0, window_m, bucket)
    per_window = run_footprint_bytes(engine, 1, window_m, 0) - V5_OVERHEAD_BYTES
    fit = int(room // per_window) if room > 0 else 0
    while fit > 0 and run_footprint_bytes(engine, fit, window_m, bucket) > budget:
        fit -= 1   # v6's per-window bytes are rounded up; the total must still fit
    return RunBudget(max(1, min(target, fit)), bucket)
