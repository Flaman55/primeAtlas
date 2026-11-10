"""Work plan of one pt2 run (partial sieve + primality proof, prime_sieve_pt2.py).

pt2 sieves the odd numbers of a window by the primes 3..B, as pt1 does (pt1_plan.py), and
proves every survivor, so every window goes to the D store:
  - a window wholly below storage_kinds.MR_DET_BOUND: the 13 Miller-Rabin bases 2..41, a proof
    there (pt1's D test);
  - any other window: the pseudosquares test (prime_sieve_engine_pt2.c). It needs every prime
    factor of a survivor above B and top / B below the largest known pseudosquare L_373
    (~4.2e24), so B is raised to the engine's pt2_min_s(top) when that is larger; the number
    of bases follows from top / B (larger B, fewer bases). B stays at most isqrt of the run's
    lowest number and below 2^32, which bounds pt2 at floor 33.

Perf knobs (environment variables; the defaults are arbitrary):
  - PRIMEATLAS_PT2_B: the sieve limit B. 0 or unset = floor(N^(1/4)) for the top N of the run,
    raised to the proof's minimum;
  - PRIMEATLAS_PT2_CHUNK_KB: odd numbers per thread task, in KiB of the per-thread flag array.
"""
import math

import pt1_plan
import storage_kinds

B_ENV = "PRIMEATLAS_PT2_B"
CHUNK_KB_ENV = "PRIMEATLAS_PT2_CHUNK_KB"
DEFAULT_CHUNK_KB = pt1_plan.DEFAULT_CHUNK_KB
MAX_B = pt1_plan.MAX_B
MIN_FLOOR = pt1_plan.MIN_FLOOR
MAX_FLOOR = 33   # floor 34 needs B > 2^32 for top / B < L_373

PROOF_MR = "mr"     # 13 Miller-Rabin bases, below MR_DET_BOUND
PROOF_PSS = "pss"   # pseudosquares test


def b_from_env(environ):
    return pt1_plan.b_from_env(environ, B_ENV)


def chunk_kb_from_env(environ):
    return pt1_plan.chunk_kb_from_env(environ, CHUNK_KB_ENV)


def proof_for_window(lo, hi):
    """PROOF_MR for a window [lo, hi) wholly below MR_DET_BOUND, else PROOF_PSS."""
    return PROOF_MR if hi <= storage_kinds.MR_DET_BOUND else PROOF_PSS


def effective_b(requested, run_lo, run_hi, min_s):
    """The B a run uses: `requested`, or floor((run_hi - 1)^(1/4)) for 0, clamped to
    isqrt(run_lo) and MAX_B, then raised to min_s (the proof's minimum, 0 when no window needs
    it); None when min_s is above that clamp (the run cannot be proven)."""
    cap = min(math.isqrt(run_lo), MAX_B)
    b = max(min(requested or pt1_plan.default_b(run_hi - 1), cap), min_s)
    return b if b <= cap else None


chunk_odd = pt1_plan.chunk_odd
plan_slabs = pt1_plan.plan_slabs
slab_numbers = pt1_plan.slab_numbers
