"""Window count (and v5 bucket memory) of one sieve run, from the floor and the RAM free in WSL.

Two limits, the smaller one wins:
  - target: how long a tape pays off. Each run pays a fixed cost F (iterating the sieving
    primes below L_final and one 128-bit phase division per prime), so a run should cover
    enough windows to amortize it. v4.1 stays at 1000 windows: its random atomic marking
    makes longer tapes no faster. v5 scales the tape with F, which grows like
    pi(isqrt(10^floor)) ~ L / ln L: the knob is the window count at floor 25 (10^7-wide
    windows), never below 1000;
  - RAM: the run's footprint must fit in safety_fraction of the RAM free in WSL. v4.1 holds
    a full bit buffer (window_m // 8 bytes per window); v5 holds an odd-only buffer
    (window_m // 16 per window), its bucket memory and a fixed overhead (worker processes,
    sieving-prime iterators). When RAM is short, v5's buckets shrink first (down to
    MIN_BUCKET_MB, never above the knob): a longer tape gains more than bigger buckets.

The defaults are arbitrary, picked by measurement (24 threads @1e25: 1000 -> 5000 windows
triples throughput; 256 -> 4096 MiB buckets at 5000 windows gains about 15 %).
"""
import math
from collections import namedtuple

ENGINE_V41 = "v4.1"
ENGINE_V5 = "v5"
BASE_WINDOWS = 1000                  # target at shallow floors and v4.1's ceiling
DEFAULT_TARGET_WINDOWS_AT_25 = 5000
REFERENCE_WINDOW_M = 10_000_000      # window width the floor-25 knob is counted in
DEFAULT_BUCKET_MB = 1024             # matches work_plan_v5.DEFAULT_BUCKET_MB
MIN_BUCKET_MB = 64
BUCKET_BUDGET_SHARE = 4              # buckets take at most 1/4 of the RAM budget
V5_OVERHEAD_BYTES = 128 * 2 ** 20    # measured peak PSS minus buffer and buckets: ~70 MiB
DEFAULT_SAFETY_FRACTION = 0.5        # stands in for whatever the model leaves out

RunBudget = namedtuple("RunBudget", "windows bucket_mb")


def _fixed_cost(base_exponent):
    """Relative fixed cost of a run at this floor: the sieving-prime count estimate L / ln L."""
    limit = max(3, math.isqrt(10 ** base_exponent))
    return limit / math.log(limit)


def target_windows(engine, base_exponent, window_m, target_at_25=DEFAULT_TARGET_WINDOWS_AT_25):
    """Windows one run should cover when RAM is no limit."""
    if engine != ENGINE_V5:
        return BASE_WINDOWS
    tape = target_at_25 * REFERENCE_WINDOW_M * _fixed_cost(base_exponent) / _fixed_cost(25)
    return max(BASE_WINDOWS, math.ceil(tape / window_m))


def run_footprint_bytes(engine, windows, window_m, bucket_mb):
    """Peak memory of one run with this many windows."""
    if engine != ENGINE_V5:
        return windows * (window_m // 8)
    return windows * (window_m // 16) + bucket_mb * 2 ** 20 + V5_OVERHEAD_BYTES


def recommend_run(available_ram_bytes, engine, base_exponent, window_m,
                  bucket_mb=DEFAULT_BUCKET_MB, target_at_25=DEFAULT_TARGET_WINDOWS_AT_25,
                  safety_fraction=DEFAULT_SAFETY_FRACTION, max_windows=None):
    """RunBudget(windows, bucket_mb) for one run, or None without a RAM reading. windows is at
    least 1, even when not even one window fits (the caller still needs a value to show).
    bucket_mb is the knob's value, or less when RAM is short; v4.1 has no buckets and keeps
    the knob's value unused."""
    if not available_ram_bytes or available_ram_bytes <= 0:
        return None
    budget = available_ram_bytes * safety_fraction
    target = target_windows(engine, base_exponent, window_m, target_at_25)
    if max_windows is not None:
        target = min(target, max_windows)
    if engine != ENGINE_V5:
        fit = int(budget // run_footprint_bytes(engine, 1, window_m, 0))
        return RunBudget(max(1, min(target, fit)), bucket_mb)
    bucket_cap = int(budget / BUCKET_BUDGET_SHARE) // 2 ** 20
    bucket = min(bucket_mb, max(MIN_BUCKET_MB, bucket_cap))
    room = budget - run_footprint_bytes(engine, 0, window_m, bucket)
    fit = int(room // (window_m // 16)) if room > 0 else 0
    return RunBudget(max(1, min(target, fit)), bucket)
