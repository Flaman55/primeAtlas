"""Work plan of one v7.1 sieve run: v7.0's job split with the jump threshold from a cost model.

Slices, segmented primes, the classic bucketed pieces and the jump pieces are planned as in
v7.0 (work_plan_v7.py). Only the threshold p* where the jump gear takes over differs. Per
integer q of the sieving range, a classic prime costs about 1 / ln q (one phase per prime,
density 1 / ln q); the gear costs about (a * sqrt(first / span) + b * span) / q: its block
setups (as many per octave of q as sqrt(first / span), block length ~ q * sqrt(span / first))
plus its landing candidates (span / q per q). Both in units of one classic prime. They meet at

    p* = ln p* * (a * sqrt(first / span) + b * span),

so narrow runs and deep floors (block term) move p* up, wide runs (landing term) too. v7.0's
p* = K * span * ln p* had the landing term only.

Knobs, v7.1's own (the rest are v7.0's PRIMEATLAS_V7_* knobs, same defaults):
  - PRIMEATLAS_V7_JUMP_MODEL_PCT: p* in percent of the model, 0 = gear off;
  - PRIMEATLAS_V7_JUMP_BLOCK_COST: a, one block setup in classic primes;
  - PRIMEATLAS_V7_JUMP_LANDING_COST_PCT: b in percent, one landing in classic primes.
The defaults are arbitrary, fitted on one machine (24 threads, count-only): a = 300 from the
narrow sweep (1e10 numbers, floors 26-28: best p* / sqrt(first / span) ~ 8200-9100), b = 0.10
from the wide sweep (2e11 numbers, floor 26: best threshold factor ~ 0.1).

stage_weights() and progress() weight the run's progress bar by the same model: pieces are
handed out in order, so the finished count maps to a share of the estimated cost, not of
the piece count (v7.0's classic and jump pieces are equal in number, not in cost).
"""
import math

from work_plan_v5 import _cumulative_cost_function, _positive_int_from_env
from work_plan_v7 import (BUCKET_MB_ENV, DEFAULT_BUCKET_MB, DEFAULT_JUMP_BLOCK_PCT,  # noqa: F401
                          DEFAULT_PIECES_PER_THREAD, DEFAULT_REGION_KB, DEFAULT_SEGMENT_KB,
                          DEFAULT_WRITE_THREADS, JUMP_BLOCK_PCT_ENV, PIECES_PER_THREAD_ENV,
                          REGION_KB_ENV, SEGMENT_KB_ENV, WRITE_THREADS_ENV, bucket_mb_from_env,
                          jump_block_pct_from_env, pieces_per_thread_from_env, plan_bucketed,
                          plan_jump_pieces, plan_slices, region_bits, region_kb_from_env,
                          segment_bits, segment_kb_from_env, small_prime_stop,
                          write_threads_from_env)

JUMP_MODEL_PCT_ENV = "PRIMEATLAS_V7_JUMP_MODEL_PCT"
DEFAULT_JUMP_MODEL_PCT = 100
JUMP_BLOCK_COST_ENV = "PRIMEATLAS_V7_JUMP_BLOCK_COST"
DEFAULT_JUMP_BLOCK_COST = 300
JUMP_LANDING_COST_PCT_ENV = "PRIMEATLAS_V7_JUMP_LANDING_COST_PCT"
DEFAULT_JUMP_LANDING_COST_PCT = 10

# Progress weights only, in units of one iteration of a bucketed prime above the buffer size:
# one segmented mark (primes 7..small_stop, segment in cache) and one bucketed hit of a prime
# below the buffer size. Fitted to the stage times of floor 27 and 28 runs (2e11 numbers,
# 24 threads), arbitrary elsewhere; the run prints each stage's wall time.
SEGMENTED_MARK_COST = 0.03
BUCKET_HIT_COST = 0.45


def _int_from_env(environ, name, default, lowest, what):
    raw = environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = lowest - 1
    if value < lowest:
        raise ValueError(f"{name} must be an integer >= {lowest} ({what}), got {raw!r}")
    return value


def jump_model_pct_from_env(environ):
    """p* in percent of the model, DEFAULT_JUMP_MODEL_PCT when unset; 0 turns the gear off."""
    return _int_from_env(environ, JUMP_MODEL_PCT_ENV, DEFAULT_JUMP_MODEL_PCT, 0,
                         "percent of the model, 0 = off")


def jump_block_cost_from_env(environ):
    return _positive_int_from_env(environ, JUMP_BLOCK_COST_ENV, DEFAULT_JUMP_BLOCK_COST,
                                  "classic primes")


def jump_landing_cost_pct_from_env(environ):
    return _int_from_env(environ, JUMP_LANDING_COST_PCT_ENV, DEFAULT_JUMP_LANDING_COST_PCT, 0,
                         "percent of a classic prime")


def jump_cost(first, span, block_cost, landing_cost_pct):
    """a * sqrt(first / span) + b * span: the gear's cost times q per integer q, in classic
    primes."""
    return block_cost * math.sqrt(first / max(span, 1)) + landing_cost_pct / 100 * span


def jump_from(first, span, model_pct, block_cost, landing_cost_pct):
    """Lowest sieving prime the jump gear takes for a run of `span` numbers starting at
    `first`: the fixed point p* = s * ln p* * jump_cost(), s = model_pct / 100, raised to the
    gear's own limits (2 * span and first / 2^62 + 1, see prime_sieve_engine_v7_0.c). 0 when
    model_pct is 0 (gear off)."""
    if model_pct <= 0:
        return 0
    c = model_pct / 100 * jump_cost(first, span, block_cost, landing_cost_pct)
    p = max(c, 3.0)
    for _ in range(60):   # p -> c * ln p contracts near the upper fixed point
        p = max(c * math.log(p), 3.0)
    return max(int(p), 2 * span, (first >> 62) + 1)


def stage_weights(n_slices, classic, jumped, combined_size, small_stop, L_final, first, span,
                  block_cost, landing_cost_pct):
    """(slice weights, piece weights), all summing to 1: the estimated cost share of each
    segmented slice (equal, SEGMENTED_MARK_COST per mark of primes 7..small_stop) and of each
    bucketed piece in order (classic: v5's Mertens/li cost, its Mertens hits below the buffer
    size at BUCKET_HIT_COST; jump: jump_cost() * ln(hi / lo))."""
    threshold = min(combined_size, L_final)
    upto = _cumulative_cost_function(threshold, combined_size)

    def classic_cost(x):
        hits = upto(min(x, threshold))
        return BUCKET_HIT_COST * hits + upto(max(x, threshold)) - upto(threshold)
    c = jump_cost(first, span, block_cost, landing_cost_pct)
    pieces = ([classic_cost(hi) - classic_cost(lo) for lo, hi in classic]
              + [c * math.log(hi / lo) for lo, hi in jumped])
    pieces = [max(w, 0.0) for w in pieces]
    marks = combined_size * max(math.log(math.log(max(small_stop, 8))) - math.log(math.log(7)),
                                1e-6)
    slices = [SEGMENTED_MARK_COST * marks / max(n_slices, 1)] * n_slices
    total = sum(slices) + sum(pieces)
    return [w / total for w in slices], [w / total for w in pieces]


def progress(weights, done):
    """Share of the estimated cost finished once the first `done` jobs are done (1.0 for no
    jobs)."""
    if not weights:
        return 1.0
    return min(1.0, sum(weights[:max(done, 0)]))
