"""work_plan_v7 splits the bucketed primes of a v7 run between v6's classic path and the jump gear.

Checks:
  - jump_from(): 0 at threshold 0 (gear off); otherwise never below the engine's own limits
    (2 * span and first / 2^62 + 1), equal to the fixed point p = K * span * ln p where that
    is higher, growing with the threshold and with the span, the same for spans of one and of
    10^12 numbers far from zero;
  - plan_jump_pieces(): ascending, contiguous, covering [lo, hi) exactly, at most threads *
    pieces per thread, of near-equal ratio hi / lo; empty for lo >= hi; one number wide;
  - plan_bucketed(): classic pieces end where the jump pieces start, both together cover
    [small_stop, L_final) once; jump_lo 0, at L_final or above -> all classic, the same as
    v6's plan; jump_lo below small_stop -> raised to it, never a jump piece below the
    segmented primes;
  - the knobs: threshold accepts 0 and positive integers and rejects negatives, fractions and
    text; block factor rejects 0; unset -> the documented defaults.
Pure Python, runs on Windows and WSL:
    python unitTests/test_work_plan_v7.py
"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

import work_plan_v6  # noqa: E402
import work_plan_v7 as wp  # noqa: E402


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def contiguous(pieces, lo, hi):
    return (bool(pieces) and pieces[0][0] == lo and pieces[-1][1] == hi
            and all(a < b for a, b in pieces)
            and all(pieces[i][1] == pieces[i + 1][0] for i in range(len(pieces) - 1)))


def check_jump_from():
    passed = True
    span, first = 2 * 10 ** 11, 10 ** 28
    passed &= check(wp.jump_from(span, 0, first) == 0, "threshold 0 -> gear off (0)")
    p = wp.jump_from(span, 100, first)
    passed &= check(abs(p - span * math.log(p)) <= 1e-6 * p,
                    f"threshold 100 % -> fixed point p = span * ln p ({p:.4g})")
    passed &= check(5e12 < p < 7e12, f"floor 28, span 2e11: p* {p:.3g} near the measured ~6e12")
    passed &= check(wp.jump_from(span, 1, first) == 2 * span,
                    "threshold 1 % -> the 2 * span floor of the engine")
    huge = 10 ** 37
    passed &= check(wp.jump_from(1000, 1, huge) == (huge >> 62) + 1,
                    "far from zero the first / 2^62 + 1 limit wins")
    seq = [wp.jump_from(span, pct, first) for pct in (1, 10, 50, 100, 200, 1000)]
    passed &= check(seq == sorted(seq) and seq[-1] > seq[0],
                    f"grows with the threshold ({[f'{x:.3g}' for x in seq]})")
    spans = [wp.jump_from(s, 100, first) for s in (10 ** 6, 10 ** 9, 10 ** 12)]
    passed &= check(spans == sorted(spans) and spans[0] < spans[-1],
                    "grows with the span (cost per q ~ span / q)")
    for s in (1, 30, 10 ** 12):
        got = wp.jump_from(s, 100, first)
        passed &= check(got >= 2 * s and got >= (first >> 62) + 1,
                        f"span {s}: never below the engine's limits ({got:.4g})")
    return passed


def check_jump_pieces():
    passed = True
    lo, hi = 7 * 10 ** 12, 10 ** 14
    pieces = wp.plan_jump_pieces(lo, hi, 24, 16)
    passed &= check(contiguous(pieces, lo, hi) and len(pieces) <= 24 * 16,
                    f"{len(pieces)} pieces cover [lo, hi) contiguously, at most 384")
    ratios = [b / a for a, b in pieces]
    passed &= check(max(ratios) / min(ratios) < 1 + 1e-6, "pieces of equal ratio hi / lo")
    passed &= check(wp.plan_jump_pieces(hi, hi, 24, 16) == []
                    and wp.plan_jump_pieces(hi + 1, hi, 24, 16) == [], "lo >= hi -> no pieces")
    one = wp.plan_jump_pieces(lo, lo + 1, 24, 16)
    passed &= check(one == [(lo, lo + 1)], f"one number wide -> one piece ({one})")
    few = wp.plan_jump_pieces(100, 103, 24, 16)
    passed &= check(contiguous(few, 100, 103) and len(few) <= 3,
                    f"fewer numbers than pieces -> no empty piece ({few})")
    passed &= check(contiguous(wp.plan_jump_pieces(lo, hi, 0, 0), lo, hi),
                    "0 threads / pieces -> still one covering piece")
    return passed


def check_bucketed():
    passed = True
    L_final, size, small = 10 ** 14 + 1, 2 * 10 ** 11, 31_000
    want_classic = work_plan_v6.plan_pieces(L_final, size, small, 24, 16)
    for jump_lo in (0, L_final, L_final + 5):
        classic, jumped = wp.plan_bucketed(L_final, size, small, 24, 16, jump_lo)
        passed &= check(classic == want_classic and jumped == [],
                        f"jump_lo {jump_lo}: all classic, the same as v6's plan")
    for jump_lo in (6 * 10 ** 12, small + 1, L_final - 1):
        classic, jumped = wp.plan_bucketed(L_final, size, small, 24, 16, jump_lo)
        passed &= check(contiguous(classic + jumped, small, L_final)
                        and classic[-1][1] == jumped[0][0] == jump_lo,
                        f"jump_lo {jump_lo}: classic up to it, jump from it, [small, L_final) once")
    classic, jumped = wp.plan_bucketed(L_final, size, small, 24, 16, 1000)
    passed &= check(classic == [] and contiguous(jumped, small, L_final),
                    "jump_lo below small_stop -> raised to it, nothing below the segmented primes")
    return passed


def check_knobs():
    passed = True
    passed &= check((wp.jump_pct_from_env({}), wp.jump_block_pct_from_env({})) == (100, 50),
                    "unset -> threshold 100 %, block 50 %")
    passed &= check(wp.jump_pct_from_env({wp.JUMP_PCT_ENV: "0"}) == 0
                    and wp.jump_pct_from_env({wp.JUMP_PCT_ENV: "250"}) == 250,
                    "threshold 0 and 250 accepted")
    for raw in ("-1", "1.5", "x", ""):
        try:
            wp.jump_pct_from_env({wp.JUMP_PCT_ENV: raw})
            ok = False
        except ValueError:
            ok = True
        passed &= check(ok, f"threshold {raw!r} rejected")
    for raw in ("0", "-2", "y"):
        try:
            wp.jump_block_pct_from_env({wp.JUMP_BLOCK_PCT_ENV: raw})
            ok = False
        except ValueError:
            ok = True
        passed &= check(ok, f"block factor {raw!r} rejected")
    passed &= check(all(getattr(wp, f"DEFAULT_{k}") == getattr(work_plan_v6, f"DEFAULT_{k}")
                        for k in ("SEGMENT_KB", "REGION_KB", "BUCKET_MB", "PIECES_PER_THREAD",
                                  "WRITE_THREADS")),
                    "v7's v6-style knobs default to v6's values")
    passed &= check(all(getattr(wp, f"{k}_ENV").startswith("PRIMEATLAS_V7_")
                        for k in ("SEGMENT_KB", "REGION_KB", "BUCKET_MB", "PIECES_PER_THREAD",
                                  "WRITE_THREADS", "JUMP_PCT", "JUMP_BLOCK_PCT")),
                    "every v7 knob has its own PRIMEATLAS_V7_* variable")
    return passed


def main():
    passed = check_jump_from()
    passed &= check_jump_pieces()
    passed &= check_bucketed()
    passed &= check_knobs()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
