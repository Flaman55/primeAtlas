"""Work plan of one v7.2 sieve run: v7.1's plan with a virtual gear span.

v7.1 (work_plan_v7_1.py) prices the jump gear per integer q of the sieving range at
(a * sqrt(first / span) + b * span) / q classic primes: block setups ~ sqrt(first / span),
landing candidates ~ span. The gear's span need not be the buffer's: the engine
(prime_sieve_engine_v7_2.c) walks a gear span V >= span starting at the buffer's first number
and keeps only the landings inside the buffer. The cost a * sqrt(first / V) + b * V is
smallest at

    V* = (a / (2 b))^(2/3) * first^(1/3),

so a run narrower than V* lets the gear plan for V* (fewer, longer blocks) while its buffer,
segmented slices and classic pieces keep the run's own size. A run at least V* wide keeps
V = span, which is v7.1. The threshold p* is v7.1's fixed point with V in place of span, and
the engine raises it to 2 V (one multiple at most in the gear span).

Knob, v7.2's own (the rest are v7.1's PRIMEATLAS_V7_* knobs, same defaults):
  - PRIMEATLAS_V7_GEAR_SPAN_PCT: V in percent of V*, never below the buffer span; 0 = the
    buffer span (v7.1's gear). The default 100 is the model's optimum with v7.1's fitted a and
    b; it is arbitrary in the same sense as they are.
"""
from work_plan_v7_1 import (BUCKET_MB_ENV, DEFAULT_BUCKET_MB, DEFAULT_JUMP_BLOCK_COST,  # noqa: F401
                            DEFAULT_JUMP_BLOCK_PCT, DEFAULT_JUMP_LANDING_COST_PCT,
                            DEFAULT_JUMP_MODEL_PCT, DEFAULT_PIECES_PER_THREAD,
                            DEFAULT_REGION_KB, DEFAULT_SEGMENT_KB, DEFAULT_WRITE_THREADS,
                            JUMP_BLOCK_COST_ENV, JUMP_BLOCK_PCT_ENV,
                            JUMP_LANDING_COST_PCT_ENV, JUMP_MODEL_PCT_ENV,
                            PIECES_PER_THREAD_ENV, REGION_KB_ENV, SEGMENT_KB_ENV,
                            WRITE_THREADS_ENV, _int_from_env, bucket_mb_from_env, jump_cost,
                            jump_block_cost_from_env, jump_block_pct_from_env,
                            jump_from, jump_landing_cost_pct_from_env,
                            jump_model_pct_from_env, pieces_per_thread_from_env,
                            plan_bucketed, plan_slices, progress, region_bits,
                            region_kb_from_env, segment_bits, segment_kb_from_env,
                            small_prime_stop, stage_weights, write_threads_from_env)

GEAR_SPAN_PCT_ENV = "PRIMEATLAS_V7_GEAR_SPAN_PCT"
DEFAULT_GEAR_SPAN_PCT = 100
# The engine keeps q >= 2 V in 64-bit integers and V / q * 2^64 below 2^63.
MAX_GEAR_SPAN = 1 << 61


def gear_span_pct_from_env(environ):
    """V in percent of the model's V*, DEFAULT_GEAR_SPAN_PCT when unset; 0 = the buffer span."""
    return _int_from_env(environ, GEAR_SPAN_PCT_ENV, DEFAULT_GEAR_SPAN_PCT, 0,
                         "percent of the model's gear span, 0 = the buffer span")


def optimal_gear_span(first, block_cost, landing_cost_pct):
    """V* = (a / (2 b))^(2/3) * first^(1/3), the minimum of a * sqrt(first / V) + b * V; None
    when b is 0 (landings cost nothing in the model, so it has no minimum)."""
    if landing_cost_pct <= 0 or first <= 0:
        return None
    b = landing_cost_pct / 100
    return (block_cost / (2 * b)) ** (2 / 3) * float(first) ** (1 / 3)


def gear_span(first, span, span_pct, block_cost, landing_cost_pct):
    """The gear span V for a run of `span` numbers starting at `first`: span_pct percent of
    V*, at least span, at most MAX_GEAR_SPAN (and never below span). span_pct 0 or a model
    without a minimum gives span."""
    best = optimal_gear_span(first, block_cost, landing_cost_pct)
    if span_pct <= 0 or best is None:
        return span
    return max(span, min(int(best * span_pct / 100), MAX_GEAR_SPAN))


def jump_from_v7_2(first, span, gear, model_pct, block_cost, landing_cost_pct):
    """v7.1's threshold (work_plan_v7_1.jump_from()) priced at the gear span `gear`, raised to
    2 * gear (the engine's limit for the virtual span). 0 when model_pct is 0 (gear off)."""
    if model_pct <= 0:
        return 0
    return max(jump_from(first, max(gear, span), model_pct, block_cost, landing_cost_pct),
               2 * max(gear, span))


def gear_gain(first, span, gear, block_cost, landing_cost_pct):
    """How many times cheaper per q the gear is at `gear` than at the buffer span (1.0 when
    they are equal)."""
    at_span = jump_cost(first, span, block_cost, landing_cost_pct)
    return at_span / max(jump_cost(first, gear, block_cost, landing_cost_pct), 1e-300)

