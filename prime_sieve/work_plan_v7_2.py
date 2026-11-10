"""Work plan of one v7.2 sieve run: v7.1's plan with the jump gear's block length from the model.

v7.1 (work_plan_v7_1.py) prices the gear per integer q of the sieving range at
(a * sqrt(first / span) + b * span) / q classic primes, at v7.0's fixed block factor 0.5: block
setups ~ sqrt(first / span), landing candidates ~ span. The block factor f sets both terms. A
block is f times longer than at f = 1, so there are 1 / f as many setups; its linear estimate
drifts by up to f^2 * span / 2 numbers over the block (engine_jump_gear.h), and the candidate
window covers the buffer plus that drift, so candidates grow as span * (1 + f^2 / 2). With a and
b fitted at f = 0.5:

    cost(f) = a * sqrt(first / span) * 0.5 / f + b * span * (1 + f^2 / 2) / 1.125,

smallest at

    f* = (0.5625 * a * sqrt(first / span) / (b * span))^(1/3).

f* is about 0.47 for 2e11 numbers at floor 25 (the prototype's best was 0.5) and grows on narrow
runs and deep floors (2.6 for 1e10 numbers at floor 26, 5.5 at floor 28). The threshold p* is
v7.1's fixed point with cost(f) in place of the gear's cost at f = 0.5, so a cheaper gear takes
more primes. cost(f) has v7.1's form a' * sqrt(first / span) + b' * span with a' = a * 0.5 / f
and b' = b * (1 + f^2 / 2) / 1.125 (effective_costs()), so v7.1's jump_from() and
stage_weights() take it unchanged.

Knob, v7.2's own (the rest are v7.1's PRIMEATLAS_V7_* knobs, same defaults, except v7.0's fixed
block factor PRIMEATLAS_V7_JUMP_BLOCK_PCT, which v7.2 does not read):
  - PRIMEATLAS_V7_BLOCK_MODEL_PCT: the block factor in percent of f*, default 100 (the model's
    optimum with v7.1's fitted a and b, arbitrary in the same sense as they are).
"""
import math

from work_plan_v7_1 import (BUCKET_MB_ENV, DEFAULT_BUCKET_MB, DEFAULT_JUMP_BLOCK_COST,  # noqa: F401
                            DEFAULT_JUMP_LANDING_COST_PCT, DEFAULT_JUMP_MODEL_PCT,
                            DEFAULT_PIECES_PER_THREAD, DEFAULT_REGION_KB, DEFAULT_SEGMENT_KB,
                            DEFAULT_WRITE_THREADS, JUMP_BLOCK_COST_ENV,
                            JUMP_LANDING_COST_PCT_ENV, JUMP_MODEL_PCT_ENV,
                            PIECES_PER_THREAD_ENV, REGION_KB_ENV, SEGMENT_KB_ENV,
                            WRITE_THREADS_ENV, _int_from_env, bucket_mb_from_env, jump_cost,
                            jump_block_cost_from_env, jump_from,
                            jump_landing_cost_pct_from_env, jump_model_pct_from_env,
                            pieces_per_thread_from_env, plan_bucketed, plan_slices, progress,
                            region_bits, region_kb_from_env, segment_bits, segment_kb_from_env,
                            small_prime_stop, stage_weights, write_threads_from_env)

BLOCK_MODEL_PCT_ENV = "PRIMEATLAS_V7_BLOCK_MODEL_PCT"
DEFAULT_BLOCK_MODEL_PCT = 100
# The block factor a and b were fitted at (v7.0's default, PRIMEATLAS_V7_JUMP_BLOCK_PCT = 50).
FITTED_BLOCK_FACTOR = 0.5
# Bounds of the factor handed to the engine: below MIN a block is a handful of q; above MAX the
# drift covers many times the buffer, and with b = 0 the model has no optimum at all.
MIN_BLOCK_FACTOR = 0.05
MAX_BLOCK_FACTOR = 64.0


def block_model_pct_from_env(environ):
    """The block factor in percent of the model's f*, DEFAULT_BLOCK_MODEL_PCT when unset."""
    return _int_from_env(environ, BLOCK_MODEL_PCT_ENV, DEFAULT_BLOCK_MODEL_PCT, 1,
                         "percent of the model's block factor")


def _drift_share(f):
    """Candidates at block factor f relative to those at the fitted factor."""
    return (1 + f * f / 2) / (1 + FITTED_BLOCK_FACTOR ** 2 / 2)


def block_factor(first, span, block_pct, block_cost, landing_cost_pct):
    """The block factor for a run of `span` numbers starting at `first`: block_pct percent of
    f* = (0.5625 a sqrt(first / span) / (b span))^(1/3), within [MIN_BLOCK_FACTOR,
    MAX_BLOCK_FACTOR] (MAX when b is 0)."""
    b = landing_cost_pct / 100
    if b <= 0:
        return MAX_BLOCK_FACTOR
    span = max(span, 1)
    k = FITTED_BLOCK_FACTOR * (1 + FITTED_BLOCK_FACTOR ** 2 / 2)   # 0.5625
    best = (k * block_cost * math.sqrt(max(first, 0) / span) / (b * span)) ** (1 / 3)
    return min(max(best * block_pct / 100, MIN_BLOCK_FACTOR), MAX_BLOCK_FACTOR)


def effective_costs(factor, block_cost, landing_cost_pct):
    """(a', b' in percent): v7.1's block and landing costs at block factor `factor`, so that
    work_plan_v7_1.jump_cost(first, span, a', b') is the gear's cost at that factor."""
    return (block_cost * FITTED_BLOCK_FACTOR / factor,
            landing_cost_pct * _drift_share(factor))


def gear_gain(first, span, factor, block_cost, landing_cost_pct):
    """How many times cheaper per q the gear is at `factor` than at the fitted factor."""
    at_fitted = jump_cost(first, span, block_cost, landing_cost_pct)
    a, b = effective_costs(factor, block_cost, landing_cost_pct)
    return at_fitted / max(jump_cost(first, span, a, b), 1e-300)


def jump_from_v7_2(first, span, model_pct, factor, block_cost, landing_cost_pct):
    """v7.1's threshold (work_plan_v7_1.jump_from()) at the gear's cost for block factor
    `factor`, raised to 2 * span * (1 + factor^2 / 2): from there the candidate window (the
    buffer plus the block's drift) stays below half a turn of q, where the engine's candidate
    search works (below it every q of a block is checked). 0 when model_pct is 0 (gear off)."""
    if model_pct <= 0:
        return 0
    a, b = effective_costs(factor, block_cost, landing_cost_pct)
    return max(jump_from(first, span, model_pct, a, b),
               int(2 * max(span, 1) * (1 + factor * factor / 2)))
