"""Work plan of one v7 sieve run: v6's job split plus the jump gear's share of the bucketed primes.

Slices, segmented primes and the classic bucketed pieces are planned as in v6
(work_plan_v6.py). The bucketed primes from jump_from() up go to the jump gear
(engine_jump_gear.h) in pieces of their own (plan_jump_pieces()). Perf knobs, v7's own:
  - PRIMEATLAS_V7_SEGMENT_KB, _REGION_KB, _BUCKET_MB, _PIECES_PER_THREAD, _WRITE_THREADS:
    as v6's PRIMEATLAS_V6_* knobs, defaults equal to v6's;
  - PRIMEATLAS_V7_JUMP_PCT: the jump threshold factor K in percent, 0 = gear off. The gear
    takes the sieving primes from p* = K * span * ln(p*) up, span = the numbers of the run:
    a classic prime costs one phase, a jump costs per landing candidate (about span / q of
    them per q), so the two costs meet at a q proportional to span * ln q;
  - PRIMEATLAS_V7_JUMP_BLOCK_PCT: block length factor in percent (engine_jump_gear.h).
The defaults are arbitrary, picked by measurement in a C prototype of the gear: K = 1.0 puts
p* at the measured crossover on 12 busy threads at floors 26-28 (span 2e11: ~5e12, ~5.7e12,
~7e12); block factor 0.5 was the fastest of 0.25-2.
"""
import math

import work_plan_v6
from work_plan_v5 import _positive_int_from_env
from work_plan_v6 import (plan_pieces, plan_slices, region_bits, segment_bits,  # noqa: F401
                          segment_numbers, small_prime_stop)

SEGMENT_KB_ENV = "PRIMEATLAS_V7_SEGMENT_KB"
DEFAULT_SEGMENT_KB = work_plan_v6.DEFAULT_SEGMENT_KB
REGION_KB_ENV = "PRIMEATLAS_V7_REGION_KB"
DEFAULT_REGION_KB = work_plan_v6.DEFAULT_REGION_KB
BUCKET_MB_ENV = "PRIMEATLAS_V7_BUCKET_MB"
DEFAULT_BUCKET_MB = work_plan_v6.DEFAULT_BUCKET_MB
PIECES_PER_THREAD_ENV = "PRIMEATLAS_V7_PIECES_PER_THREAD"
DEFAULT_PIECES_PER_THREAD = work_plan_v6.DEFAULT_PIECES_PER_THREAD
WRITE_THREADS_ENV = "PRIMEATLAS_V7_WRITE_THREADS"
DEFAULT_WRITE_THREADS = work_plan_v6.DEFAULT_WRITE_THREADS
JUMP_PCT_ENV = "PRIMEATLAS_V7_JUMP_PCT"
DEFAULT_JUMP_PCT = 100
JUMP_BLOCK_PCT_ENV = "PRIMEATLAS_V7_JUMP_BLOCK_PCT"
DEFAULT_JUMP_BLOCK_PCT = 50


def segment_kb_from_env(environ):
    return _positive_int_from_env(environ, SEGMENT_KB_ENV, DEFAULT_SEGMENT_KB, "KiB")


def region_kb_from_env(environ):
    return _positive_int_from_env(environ, REGION_KB_ENV, DEFAULT_REGION_KB, "KiB")


def bucket_mb_from_env(environ):
    return _positive_int_from_env(environ, BUCKET_MB_ENV, DEFAULT_BUCKET_MB, "MiB")


def pieces_per_thread_from_env(environ):
    return _positive_int_from_env(environ, PIECES_PER_THREAD_ENV, DEFAULT_PIECES_PER_THREAD,
                                  "pieces")


def write_threads_from_env(environ):
    return _positive_int_from_env(environ, WRITE_THREADS_ENV, DEFAULT_WRITE_THREADS, "threads")


def jump_pct_from_env(environ):
    """Jump threshold factor in percent, DEFAULT_JUMP_PCT when unset; 0 turns the gear off.
    Raises ValueError unless the value is an integer >= 0."""
    raw = environ.get(JUMP_PCT_ENV)
    if raw is None:
        return DEFAULT_JUMP_PCT
    try:
        value = int(raw)
    except ValueError:
        value = -1
    if value < 0:
        raise ValueError(f"{JUMP_PCT_ENV} must be an integer >= 0 (percent, 0 = off), "
                         f"got {raw!r}")
    return value


def jump_block_pct_from_env(environ):
    return _positive_int_from_env(environ, JUMP_BLOCK_PCT_ENV, DEFAULT_JUMP_BLOCK_PCT,
                                  "percent")


def jump_from(span, jump_pct, first):
    """Lowest sieving prime the jump gear takes for a run of `span` numbers starting at
    `first`: p* = K * span * ln(p*), K = jump_pct / 100, raised to the gear's own limits
    (2 * span and first / 2^62 + 1, see prime_sieve_engine_v7_0.c). 0 when jump_pct is 0
    (gear off)."""
    if jump_pct <= 0:
        return 0
    k = jump_pct / 100
    p = max(float(span), 3.0)
    for _ in range(20):   # fixed point of p = k * span * ln p; converges in a few steps
        p = max(k * span * math.log(p), 3.0)
    return max(int(p), 2 * span, (first >> 62) + 1)


def plan_jump_pieces(lo, hi, n_threads, pieces_per_thread=DEFAULT_PIECES_PER_THREAD):
    """Ascending, contiguous (piece_lo, piece_hi) ranges covering [lo, hi), n_threads *
    pieces_per_thread of them at most. A jump costs about span / q per q, so the pieces are
    of equal ratio hi / lo (equal estimated cost). Empty when lo >= hi."""
    if lo >= hi:
        return []
    n = max(1, n_threads) * max(1, pieces_per_thread)
    ratio = hi / lo
    cuts = sorted({lo, hi} | {int(lo * ratio ** (i / n)) for i in range(1, n)})
    cuts = [c for c in cuts if lo <= c <= hi]
    return list(zip(cuts, cuts[1:]))


def plan_bucketed(L_final, combined_size, small_stop, n_threads, pieces_per_thread, jump_lo):
    """(classic pieces, jump pieces) of the bucketed primes [small_stop, L_final): the
    classic ones below jump_lo planned as in v6, the jump ones from jump_lo up
    (plan_jump_pieces()). jump_lo = 0 or >= L_final: all classic."""
    if not jump_lo or jump_lo >= L_final:
        return plan_pieces(L_final, combined_size, small_stop, n_threads,
                           pieces_per_thread), []
    jump_lo = max(jump_lo, small_stop)
    classic = plan_pieces(jump_lo, combined_size, small_stop, n_threads, pieces_per_thread)
    return classic, plan_jump_pieces(jump_lo, L_final, n_threads, pieces_per_thread)
