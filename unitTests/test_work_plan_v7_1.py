"""work_plan_v7_1 puts v7's jump threshold where the cost model says and weights the progress bar
by estimated cost.

Checks:
  - jump_from(): 0 at model 0 % (gear off); otherwise the fixed point p = s * ln p * (a *
    sqrt(first / span) + b * span) where that lies above the engine's own limits (2 * span,
    first / 2^62 + 1), never below them; growing with the model %, the block cost, the landing
    cost, the floor and (on wide runs) the span; the defaults land on the measured best
    thresholds (narrow 1e10 runs at floors 26-28, the wide 2e11 run at floor 26); far from
    zero (10^37) and for a one-number span the limits win;
  - the knobs: model % and landing cost accept 0, block cost does not; negatives, fractions
    and text are rejected; unset -> the documented defaults; v7.0's v6-style knobs and block
    factor keep their PRIMEATLAS_V7_* variables and defaults;
  - stage_weights(): one weight per slice and per piece, none negative, summing to 1; equal
    within the slices and within the jump pieces; the jump pieces carry the model's jump cost
    against the classic cost (not their count share), classic pieces their bucketed hits at
    BUCKET_HIT_COST plus one iteration per prime above the buffer size; the shares land near
    the stage times measured at floors 27 and 28 (2e11 numbers); no jump pieces -> all classic; no
    pieces at all -> all on the slices;
  - progress(): 0 at 0 done, 1 at all done and beyond, never decreasing.
Pure Python, runs on Windows and WSL:
    python unitTests/test_work_plan_v7_1.py
"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

import work_plan_v7  # noqa: E402
import work_plan_v7_1 as wp  # noqa: E402

A, B_PCT = wp.DEFAULT_JUMP_BLOCK_COST, wp.DEFAULT_JUMP_LANDING_COST_PCT


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def jf(first, span, pct=100, a=A, b_pct=B_PCT):
    return wp.jump_from(first, span, pct, a, b_pct)


def check_jump_from():
    passed = True
    span, first = 2 * 10 ** 11, 10 ** 28
    passed &= check(jf(first, span, pct=0) == 0, "model 0 % -> gear off (0)")
    p = jf(first, span)
    cost = A * math.sqrt(first / span) + B_PCT / 100 * span
    passed &= check(abs(p - math.log(p) * cost) <= 1e-6 * p,
                    f"100 % -> fixed point p = ln p * (a sqrt(first/span) + b span) ({p:.4g})")
    half = jf(first, span, pct=50)
    passed &= check(abs(half - 0.5 * math.log(half) * cost) <= 1e-6 * half,
                    f"50 % scales the model ({half:.4g})")
    # Measured best thresholds (count-only, 24 threads): narrow 1e10 runs f26 ~8.2e11,
    # f27 ~2.9e12, f28 >= 8.9e12; the wide 2e11 run at f26 ~5.4e11 (sweep minimum).
    for floor, s, lo, hi in ((26, 10 ** 10, 5e11, 1.3e12), (27, 10 ** 10, 1.8e12, 4.5e12),
                             (28, 10 ** 10, 6e12, 1.4e13), (26, 2 * 10 ** 11, 4e11, 1.1e12)):
        got = jf(10 ** floor, s)
        passed &= check(lo < got < hi, f"floor {floor}, span {s:.0e}: p* {got:.3g} near the "
                                       f"measured best ({lo:.2g}..{hi:.2g})")
    passed &= check(jf(first, span, pct=1) == 2 * span, "1 % -> the 2 * span limit")
    huge = 10 ** 37
    passed &= check(jf(huge, 1000, pct=1, a=1, b_pct=0) == (huge >> 62) + 1,
                    "far from zero the first / 2^62 + 1 limit wins")
    for s in (1, 30, 10 ** 12):
        got = jf(first, s)
        passed &= check(got >= 2 * s and got >= (first >> 62) + 1,
                        f"span {s}: never below the engine's limits ({got:.4g})")
    seq = [jf(first, span, pct=x) for x in (10, 50, 100, 200, 1000)]
    passed &= check(seq == sorted(seq) and seq[-1] > seq[0], "grows with the model %")
    seq = [jf(first, span, a=x) for x in (30, 300, 3000)]
    passed &= check(seq == sorted(seq) and seq[-1] > seq[0], "grows with the block cost")
    seq = [jf(first, span, b_pct=x) for x in (0, 10, 100)]
    passed &= check(seq == sorted(seq) and seq[-1] > seq[0], "grows with the landing cost")
    seq = [jf(10 ** f, 10 ** 10) for f in (25, 27, 29, 31, 33)]
    passed &= check(seq == sorted(seq) and seq[-1] > seq[0],
                    "grows with the floor (block term ~ sqrt(first / span))")
    seq = [jf(10 ** 26, s) for s in (2 * 10 ** 11, 10 ** 12, 10 ** 13)]
    passed &= check(seq == sorted(seq), "wide runs: grows with the span (landing term)")
    passed &= check(jf(10 ** 28, 10 ** 10) > jf(10 ** 28, 2 * 10 ** 11),
                    "floor 28: a narrow run moves p* up (fewer numbers, as many blocks)")
    return passed


def _rejects(fn, env_name, raw):
    try:
        fn({env_name: raw})
        return False
    except ValueError:
        return True


def check_knobs():
    passed = True
    passed &= check((wp.jump_model_pct_from_env({}), wp.jump_block_cost_from_env({}),
                     wp.jump_landing_cost_pct_from_env({}), wp.jump_block_pct_from_env({}))
                    == (100, 300, 10, 50),
                    "unset -> model 100 %, block cost 300, landing cost 10 %, block 50 %")
    passed &= check(wp.jump_model_pct_from_env({wp.JUMP_MODEL_PCT_ENV: "0"}) == 0
                    and wp.jump_landing_cost_pct_from_env({wp.JUMP_LANDING_COST_PCT_ENV: "0"})
                    == 0 and wp.jump_block_cost_from_env({wp.JUMP_BLOCK_COST_ENV: "1"}) == 1,
                    "model 0 %, landing cost 0 and block cost 1 accepted")
    for raw in ("-1", "1.5", "x", ""):
        for fn, env in ((wp.jump_model_pct_from_env, wp.JUMP_MODEL_PCT_ENV),
                        (wp.jump_landing_cost_pct_from_env, wp.JUMP_LANDING_COST_PCT_ENV),
                        (wp.jump_block_cost_from_env, wp.JUMP_BLOCK_COST_ENV)):
            passed &= check(_rejects(fn, env, raw), f"{env}={raw!r} rejected")
    passed &= check(_rejects(wp.jump_block_cost_from_env, wp.JUMP_BLOCK_COST_ENV, "0"),
                    "block cost 0 rejected")
    names = ("SEGMENT_KB", "REGION_KB", "BUCKET_MB", "PIECES_PER_THREAD", "WRITE_THREADS",
             "JUMP_BLOCK_PCT")
    passed &= check(all(getattr(wp, f"{k}_ENV") == getattr(work_plan_v7, f"{k}_ENV")
                        and getattr(wp, f"DEFAULT_{k}") == getattr(work_plan_v7, f"DEFAULT_{k}")
                        for k in names),
                    "v7.0's other knobs: same variables and defaults")
    passed &= check(all(getattr(wp, f"{k}_ENV").startswith("PRIMEATLAS_V7_")
                        for k in ("JUMP_MODEL_PCT", "JUMP_BLOCK_COST", "JUMP_LANDING_COST_PCT")),
                    "the model knobs are PRIMEATLAS_V7_* variables")
    passed &= check(wp.JUMP_MODEL_PCT_ENV != work_plan_v7.JUMP_PCT_ENV,
                    "the model % is a new variable, not v7.0's threshold factor")
    return passed


def _plan(floor, span, pct=100):
    first = 10 ** floor
    L_final = math.isqrt(first + span) + 1
    small = 31_000
    jump_lo = jf(first, span, pct=pct)
    classic, jumped = wp.plan_bucketed(L_final, span, small, 24, 16, jump_lo)
    weights = wp.stage_weights(48, classic, jumped, span, small, L_final, first, span, A,
                               B_PCT)
    return classic, jumped, weights, L_final, small


def check_weights():
    passed = True
    classic, jumped, (sw, pw), L_final, small = _plan(28, 2 * 10 ** 11)
    passed &= check(len(sw) == 48 and len(pw) == len(classic) + len(jumped),
                    "one weight per slice and per piece")
    passed &= check(min(sw + pw) >= 0 and abs(sum(sw) + sum(pw) - 1) < 1e-9,
                    "no negative weight, all of them sum to 1")
    passed &= check(max(sw) - min(sw) < 1e-12, "slices weigh the same")
    jw = pw[len(classic):]
    passed &= check(jumped and max(jw) - min(jw) < 1e-6 * max(jw),
                    "jump pieces (equal ratio) weigh the same")
    cw = pw[:len(classic)]
    cost = A * math.sqrt(10 ** 28 / (2 * 10 ** 11)) + B_PCT / 100 * 2 * 10 ** 11
    want_jump = cost * math.log(L_final / jumped[0][0])
    from work_plan_v5 import _cumulative_cost_function, _mert
    size = 2 * 10 ** 11
    upto = _cumulative_cost_function(min(size, L_final), size)
    hits = size * (_mert(size) - _mert(small))   # primes below the buffer size: Mertens hits
    want_classic = wp.BUCKET_HIT_COST * hits + upto(jumped[0][0]) - upto(size)
    got = sum(jw) / sum(cw)
    passed &= check(abs(got / (want_jump / want_classic) - 1) < 1e-6,
                    f"jump : classic weight = model cost ratio ({got:.3f}), not the count share "
                    f"({len(jumped) / len(classic):.3f})")
    passed &= check(0 < wp.BUCKET_HIT_COST < 1 and 0 < wp.SEGMENTED_MARK_COST < wp.BUCKET_HIT_COST,
                    "a bucketed hit costs less than a big prime's iteration, a segmented mark "
                    "less than a bucketed hit")
    for floor, slice_time, jump_time in ((27, 0.065, 0.68), (28, 0.026, 0.76)):
        first, span = 10 ** floor, 2 * 10 ** 11
        L_final = math.isqrt(first + span) + 1
        small = wp.small_prime_stop(wp.segment_bits(wp.DEFAULT_SEGMENT_KB), L_final)
        classic, jumped = wp.plan_bucketed(L_final, span, small, 24, 16, jf(first, span))
        sw, pw = wp.stage_weights(48, classic, jumped, span, small, L_final, first, span, A,
                                  B_PCT)
        jump_share = sum(pw[len(classic):])
        passed &= check(abs(sum(sw) - slice_time) < 0.05 and abs(jump_share - jump_time) < 0.2,
                        f"floor {floor}, 2e11: slice share {sum(sw):.3f} and jump share "
                        f"{jump_share:.3f} near the measured stage times ({slice_time}, "
                        f"{jump_time})")
    classic, jumped, (sw, pw), _, _ = _plan(28, 2 * 10 ** 11, pct=0)
    passed &= check(not jumped and abs(sum(sw) + sum(pw) - 1) < 1e-9 and min(pw) > 0,
                    "gear off: every piece classic, weights still sum to 1")
    sw, pw = wp.stage_weights(5, [], [], 10 ** 6, 31_000, 1000, 10 ** 12, 10 ** 6, A, B_PCT)
    passed &= check(pw == [] and len(sw) == 5 and abs(sum(sw) - 1) < 1e-12,
                    "no bucketed pieces: the slices carry the whole bar")
    return passed


def check_progress():
    passed = True
    _, _, (sw, pw), _, _ = _plan(28, 2 * 10 ** 11)
    weights = sw + pw
    seq = [wp.progress(weights, k) for k in range(len(weights) + 3)]
    passed &= check(seq[0] == 0 and abs(seq[len(weights)] - 1) < 1e-9 and seq[-1] == seq[-2],
                    "0 at the start, 1 at all done and beyond")
    passed &= check(all(a <= b for a, b in zip(seq, seq[1:])), "never decreasing")
    passed &= check(wp.progress([], 0) == 1.0, "nothing to do -> done")
    return passed


def main():
    passed = check_jump_from()
    passed &= check_knobs()
    passed &= check_weights()
    passed &= check_progress()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
