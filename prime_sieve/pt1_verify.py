"""pt1_verify.py -- the verification that turns pt1's P windows into D.

A P window holds pt1's BPSW verdicts above storage_kinds.MR_DET_BOUND. The verification
sieves the window again by the primes 3..s and decides every survivor with the pseudosquares
proof (prime_sieve_engine_pt1.c, pt1_verify_odd()): a proven prime list. Equal to the P list,
the window is proven and becomes D/P (storage_kinds.py): its file moves to the D store and
its tag is listed in DP_PROVEN.txt, so it still counts as present in the P store. Different,
it is a BPSW counterexample or an engine error: the P window stays and is listed in
DP_MISMATCH.txt (dp_verify.record()), never resolved automatically.

The caller is pt1_verify_store.py: it proves the P windows already in a floor's store, from
Section D or after a pt1 run (run_verify.py).

The bound s: the proof needs every prime factor of n above s and n / s < L_373 (about
4.2e24), so s = max(B, the smallest s with top / s < L_373), at most isqrt of the lowest
number (the sieve never removes a prime of the window) and below 2^32 (the sieving primes are
32-bit): verifiable below L_373 * 2^32, about 1.8e34 (LIMIT_TEXT), part of floor 34.
"""
import math

import numpy as np

import pt1_lib
import pt1_plan
from benchmark_log_schema import ENGINE_PT1_VERIFY

LIMIT_TEXT = "about 1.8e34"  # L_373 * 2^32: the largest top bound() accepts
ENGINE_VERIFY = ENGINE_PT1_VERIFY  # benchmark_log.csv engine of a store verification run
# Smallest proof chunk: each chunk recomputes one phase per sieving prime (arbitrary).
MIN_CHUNK_ODD = 64 * 1024


def bound(b, lo, hi):
    """Sieve bound s of the verification of [lo, hi) for a scan bound b; None when the
    range cannot be verified (s would pass isqrt(lo) or 2^32 - 1)."""
    s = max(b, pt1_lib.load().pt1_verify_min_s(*pt1_lib.split(hi - 1)))
    return s if s <= min(math.isqrt(lo), pt1_plan.MAX_B) else None


def verify_slab(ctx, lo, hi, n_threads, chunk_odd, on_progress):
    """(first_odd, proven composite bitmap) of the odd numbers of [lo, hi); ctx holds the
    sieving primes 3..s. Raises RuntimeError on an engine error or a survivor the
    pseudosquares table cannot decide. The proof costs far more per number than the sieve,
    so a slab too small for CHUNKS_PER_THREAD_PER_SLAB chunks per thread of chunk_odd gets
    smaller chunks (at least MIN_CHUNK_ODD) and keeps every thread busy."""
    lib = pt1_lib.load()
    n_odd = (hi - (lo | 1) + 1) // 2
    per_thread = max(1, n_threads) * pt1_plan.CHUNKS_PER_THREAD_PER_SLAB
    chunk = max(MIN_CHUNK_ODD, min(chunk_odd, -(-n_odd // per_thread)))
    return pt1_lib.run_slab(
        lambda first_hi, first_lo, n_odd, bits, done: lib.pt1_verify_odd(
            ctx, first_hi, first_lo, n_odd, n_threads, chunk, bits, done),
        lo, hi, on_progress)


def first_difference(lo, offsets_a, offsets_b):
    """Smallest number lo + offset in exactly one of the two ascending offset arrays, or
    None when they are equal."""
    only = np.setxor1d(offsets_a, offsets_b, assume_unique=True)
    return lo + int(only[0]) if only.size else None
