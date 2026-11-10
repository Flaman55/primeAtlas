"""work_plan_v7_2 sets the jump gear's block factor where the cost model says.

Checks:
  - block_factor(): f* = (0.5625 a sqrt(first / span) / (b span))^(1/3) is the minimum of
    cost(f) = a sqrt(first / span) 0.5 / f + b span (1 + f^2 / 2) / 1.125 (cheaper than at
    0.5, 0.9, 1.1 and 2 times f*); the percent scales it; it stays within [MIN_BLOCK_FACTOR,
    MAX_BLOCK_FACTOR]; landing cost 0 (no optimum) gives MAX; far from zero (10^37 with a
    one-number span) and on floor 0 it stays in range;
  - the measured best lands near the model: about 0.5 at 2e11 numbers on floor 25 (the
    prototype's best), larger on narrow runs and deep floors (1e10 numbers: floor 26 ~2.6,
    floor 28 ~5.5);
  - effective_costs(): v7.1's jump_cost() with (a', b') equals cost(f) and, at f = 0.5, is v7.1's
    own cost;
  - jump_from_v7_2(): 0 at model 0 %; v7.1's threshold at f = 0.5 (when the drift floor stays
    below it); at f* lower than v7.1's on narrow deep-floor runs; never below 2 span (1 + f^2 /
    2), the engine's candidate-search limit, nor first / 2^62 + 1;
  - gear_gain(): 1 at 0.5, largest at f*, about 7 x at floor 28 with 1e10 numbers;
  - the knob: PRIMEATLAS_V7_BLOCK_MODEL_PCT, unset -> 100, rejects 0, negatives, fractions and
    text; v7.1's other knobs keep their variables and defaults.
Pure Python, runs on Windows and WSL:
    python unitTests/test_work_plan_v7_2.py
"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

import work_plan_v7_1  # noqa: E402
import work_plan_v7_2 as wp  # noqa: E402

A, B_PCT = wp.DEFAULT_JUMP_BLOCK_COST, wp.DEFAULT_JUMP_LANDING_COST_PCT


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def cost(first, span, f, a=A, b_pct=B_PCT):
    return a * math.sqrt(first / span) * 0.5 / f + b_pct / 100 * span * (1 + f * f / 2) / 1.125


def check_factor():
    passed = True
    for floor, span in ((25, 2 * 10 ** 11), (26, 10 ** 10), (28, 10 ** 10), (30, 10 ** 9)):
        first = 10 ** floor
        f = wp.block_factor(first, span, 100, A, B_PCT)
        want = (0.5625 * A * math.sqrt(first / span) / (B_PCT / 100 * span)) ** (1 / 3)
        passed &= check(abs(f - min(want, wp.MAX_BLOCK_FACTOR)) <= 1e-9 * want,
                        f"f{floor} span {span:.0e}: f* = {f:.3f}")
        passed &= check(all(cost(first, span, f) < cost(first, span, f * k)
                            for k in (0.5, 0.9, 1.1, 2.0)),
                        f"f{floor} span {span:.0e}: f* is the cost minimum")
    for floor, span, lo, hi in ((25, 2 * 10 ** 11, 0.35, 0.6), (26, 10 ** 10, 2.3, 2.9),
                                (28, 10 ** 10, 5.0, 6.0)):
        f = wp.block_factor(10 ** floor, span, 100, A, B_PCT)
        passed &= check(lo <= f <= hi, f"f{floor} span {span:.0e}: f* {f:.2f} in [{lo}, {hi}]")
    f28 = wp.block_factor(10 ** 28, 10 ** 10, 100, A, B_PCT)
    passed &= check(abs(wp.block_factor(10 ** 28, 10 ** 10, 50, A, B_PCT) - f28 / 2) < 1e-9,
                    "50 % halves f*")
    passed &= check(wp.block_factor(10 ** 28, 10 ** 10, 100, A, 0) == wp.MAX_BLOCK_FACTOR,
                    "landing cost 0 -> MAX_BLOCK_FACTOR")
    passed &= check(wp.block_factor(10 ** 37, 1, 100, A, B_PCT) == wp.MAX_BLOCK_FACTOR,
                    "far from zero, one number: capped at MAX_BLOCK_FACTOR")
    passed &= check(wp.block_factor(0, 10, 100, A, B_PCT) == wp.MIN_BLOCK_FACTOR
                    and wp.block_factor(1, 10 ** 6, 1, A, B_PCT) == wp.MIN_BLOCK_FACTOR,
                    "floor 0 / tiny percent: raised to MIN_BLOCK_FACTOR")
    return passed


def check_costs():
    passed = True
    first, span = 10 ** 28, 10 ** 10
    for f in (0.5, 1.7, 5.53):
        a, b = wp.effective_costs(f, A, B_PCT)
        got = work_plan_v7_1.jump_cost(first, span, a, b)
        passed &= check(abs(got - cost(first, span, f)) <= 1e-9 * got,
                        f"effective costs at f = {f} give cost(f)")
    passed &= check(wp.effective_costs(0.5, A, B_PCT) == (A, B_PCT),
                    "at f = 0.5 the effective costs are v7.1's a and b")
    return passed


def check_jump_from():
    passed = True
    first, span = 10 ** 28, 10 ** 10
    f = wp.block_factor(first, span, 100, A, B_PCT)
    passed &= check(wp.jump_from_v7_2(first, span, 0, f, A, B_PCT) == 0, "model 0 % -> 0")
    old = work_plan_v7_1.jump_from(first, span, 100, A, B_PCT)
    passed &= check(wp.jump_from_v7_2(first, span, 100, 0.5, A, B_PCT) == old,
                    "f = 0.5 -> v7.1's threshold")
    p = wp.jump_from_v7_2(first, span, 100, f, A, B_PCT)
    passed &= check(p < old / 4, f"f28 1e10 at f*: p* {p:.3g} well below v7.1's {old:.3g}")
    for floor, s, pct in ((19, 3 * 10 ** 6, 100), (22, 10 ** 6, 400), (37, 10, 100),
                          (28, 10 ** 10, 1000)):
        fl = 10 ** floor
        ff = wp.block_factor(fl, s, pct, A, B_PCT)
        q = wp.jump_from_v7_2(fl, s, 100, ff, A, B_PCT)
        passed &= check(q >= 2 * s * (1 + ff * ff / 2) - 1 and q >= (fl >> 62) + 1,
                        f"f{floor} span {s:.0e} factor {ff:.2f}: p* {q:.3g} above the "
                        f"engine's limits")
    return passed


def check_gain():
    first, span = 10 ** 28, 10 ** 10
    f = wp.block_factor(first, span, 100, A, B_PCT)
    passed = check(abs(wp.gear_gain(first, span, 0.5, A, B_PCT) - 1) < 1e-12, "gain 1 at 0.5")
    g = wp.gear_gain(first, span, f, A, B_PCT)
    passed &= check(6 <= g <= 8.5, f"f28 1e10: {g:.2f} x cheaper per q at f*")
    return passed & check(all(g > wp.gear_gain(first, span, f * k, A, B_PCT) for k in (0.5, 2)),
                          "largest at f*")


def _rejects(raw):
    try:
        wp.block_model_pct_from_env({wp.BLOCK_MODEL_PCT_ENV: raw})
    except ValueError:
        return True
    return False


def check_knob():
    passed = check(wp.BLOCK_MODEL_PCT_ENV == "PRIMEATLAS_V7_BLOCK_MODEL_PCT", "knob name")
    passed &= check(wp.block_model_pct_from_env({}) == wp.DEFAULT_BLOCK_MODEL_PCT == 100,
                    "unset -> 100")
    passed &= check(wp.block_model_pct_from_env({wp.BLOCK_MODEL_PCT_ENV: "250"}) == 250,
                    "250 accepted")
    passed &= check(all(_rejects(r) for r in ("0", "-1", "1.5", "abc", "")),
                    "0, negatives, fractions and text rejected")
    for name in ("JUMP_MODEL_PCT_ENV", "JUMP_BLOCK_COST_ENV", "JUMP_LANDING_COST_PCT_ENV",
                 "SEGMENT_KB_ENV", "WRITE_THREADS_ENV"):
        passed &= check(getattr(wp, name) == getattr(work_plan_v7_1, name),
                        f"{name} is v7.1's ({getattr(wp, name)})")
    passed &= check((wp.DEFAULT_JUMP_MODEL_PCT, wp.DEFAULT_JUMP_BLOCK_COST,
                     wp.DEFAULT_JUMP_LANDING_COST_PCT) == (100, 300, 10), "v7.1's defaults")
    return passed


def main():
    passed = True
    for part in (check_factor, check_costs, check_jump_from, check_gain, check_knob):
        passed &= part()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
