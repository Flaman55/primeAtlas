"""work_plan_v7_2 gives v7's jump gear a virtual gear span where the cost model says.

Checks:
  - optimal_gear_span(): V* = (a / (2 b))^(2/3) * first^(1/3) is the minimum of a * sqrt(first
    / V) + b * V (cheaper than at 0.5 V*, 0.9 V*, 1.1 V* and 2 V*); None when b is 0;
  - gear_span(): never below the buffer span (a run wider than V* keeps its own span, v7.1);
    0 % and a model without a minimum give the buffer span; the percent scales V*; capped at
    MAX_GEAR_SPAN far from zero (10^37); for a one-number span on floor 0 it stays 1;
  - narrow runs on deep floors get a virtual span: 1e10 numbers on floor 28 about 28 x the
    buffer, the model cheaper per q by about 3.5 x, on floor 25 about 2.8 x and 1.2 x;
  - jump_from_v7_2(): 0 at model 0 %; at least 2 * gear span; equal to v7.1's jump_from()
    when the gear span is the buffer span; lower than v7.1's on a narrow deep-floor run
    (cheaper gear) and the same fixed point priced at V where that lies above 2 V;
  - gear_gain(): 1 at V = span, > 1 on a virtual span, largest at V*;
  - the knob: PRIMEATLAS_V7_GEAR_SPAN_PCT accepts 0, rejects negatives, fractions and text;
    unset -> DEFAULT_GEAR_SPAN_PCT (100); v7.1's knobs keep their variables and defaults.
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


def cost(first, v, a=A, b_pct=B_PCT):
    return a * math.sqrt(first / v) + b_pct / 100 * v


def check_optimum():
    passed = True
    for floor in (19, 25, 28, 32):
        first = 10 ** floor
        best = wp.optimal_gear_span(first, A, B_PCT)
        want = (A / (2 * B_PCT / 100)) ** (2 / 3) * first ** (1 / 3)
        passed &= check(abs(best - want) <= 1e-9 * want, f"f{floor}: V* = {best:.4g}")
        passed &= check(all(cost(first, best) < cost(first, best * k)
                            for k in (0.5, 0.9, 1.1, 2.0)),
                        f"f{floor}: V* is the cost minimum (0.5, 0.9, 1.1, 2 x are dearer)")
    passed &= check(wp.optimal_gear_span(10 ** 28, A, 0) is None,
                    "landing cost 0 -> no minimum (None)")
    return passed


def check_gear_span():
    passed = True
    first, narrow, wide = 10 ** 28, 10 ** 10, 10 ** 12
    best = wp.optimal_gear_span(first, A, B_PCT)
    g = wp.gear_span(first, narrow, 100, A, B_PCT)
    passed &= check(g == int(best), f"narrow f28 run: V = V* ({g:.4g})")
    passed &= check(25 <= g / narrow <= 32, f"1e10 at f28: V about 28 x the buffer "
                                            f"({g / narrow:.1f})")
    passed &= check(wp.gear_span(first, wide, 100, A, B_PCT) == wide,
                    "run wider than V* keeps its own span (v7.1)")
    passed &= check(wp.gear_span(first, narrow, 0, A, B_PCT) == narrow, "0 % -> buffer span")
    passed &= check(wp.gear_span(first, narrow, 100, A, 0) == narrow,
                    "no landing cost (no minimum) -> buffer span")
    half = wp.gear_span(first, narrow, 50, A, B_PCT)
    passed &= check(abs(half - best / 2) <= 1, f"50 % halves V* ({half:.4g})")
    tiny = wp.gear_span(first, narrow, 1, A, B_PCT)
    passed &= check(tiny == narrow, "1 % of V* below the buffer span -> buffer span")
    far = wp.gear_span(10 ** 37, 10, 10 ** 9, A, B_PCT)
    passed &= check(far == wp.MAX_GEAR_SPAN, "far from zero, huge %: capped at MAX_GEAR_SPAN")
    passed &= check(wp.gear_span(1, 1, 100, A, B_PCT) >= 1 and
                    wp.gear_span(0, 1, 100, A, B_PCT) == 1, "floor 0, one number: stays valid")
    for floor, lo, hi in ((25, 2.5, 3.2), (28, 25, 32)):
        f = 10 ** floor
        v = wp.gear_span(f, narrow, 100, A, B_PCT)
        passed &= check(lo <= v / narrow <= hi, f"f{floor} 1e10: V / span = {v / narrow:.1f}")
    return passed


def check_jump_from():
    passed = True
    first, span = 10 ** 28, 10 ** 10
    g = wp.gear_span(first, span, 100, A, B_PCT)
    passed &= check(wp.jump_from_v7_2(first, span, g, 0, A, B_PCT) == 0, "model 0 % -> 0")
    p = wp.jump_from_v7_2(first, span, g, 100, A, B_PCT)
    old = work_plan_v7_1.jump_from(first, span, 100, A, B_PCT)
    passed &= check(p >= 2 * g, f"p* >= 2 V ({p:.4g} vs {2 * g:.4g})")
    passed &= check(p < old / 2, f"narrow f28: p* well below v7.1's ({p:.4g} < {old:.4g} / 2)")
    passed &= check(abs(p - math.log(p) * cost(first, g)) <= 1e-6 * p,
                    "p* is the fixed point priced at V")
    for floor, s in ((19, 3 * 10 ** 6), (26, 10 ** 10), (28, 2 * 10 ** 11), (37, 10)):
        f = 10 ** floor
        passed &= check(wp.jump_from_v7_2(f, s, s, 100, A, B_PCT)
                        == work_plan_v7_1.jump_from(f, s, 100, A, B_PCT),
                        f"f{floor}: V = span -> v7.1's p*")
    return passed


def check_gain():
    first, span = 10 ** 28, 10 ** 10
    best = wp.gear_span(first, span, 100, A, B_PCT)
    gains = [wp.gear_gain(first, span, int(best * k), A, B_PCT) for k in (0.5, 1, 2)]
    passed = check(wp.gear_gain(first, span, span, A, B_PCT) == 1.0, "V = span: gain 1")
    passed &= check(3.2 <= gains[1] <= 3.9, f"f28 1e10 at V*: {gains[1]:.2f} x cheaper per q")
    passed &= check(gains[1] > gains[0] and gains[1] > gains[2], "largest at V*")
    g25 = wp.gear_gain(10 ** 25, span, wp.gear_span(10 ** 25, span, 100, A, B_PCT), A, B_PCT)
    return passed & check(1.1 <= g25 <= 1.4, f"f25 1e10: {g25:.2f} x")


def _rejects(raw):
    try:
        wp.gear_span_pct_from_env({wp.GEAR_SPAN_PCT_ENV: raw})
    except ValueError:
        return True
    return False


def check_knob():
    passed = check(wp.GEAR_SPAN_PCT_ENV == "PRIMEATLAS_V7_GEAR_SPAN_PCT", "knob variable name")
    passed &= check(wp.gear_span_pct_from_env({}) == wp.DEFAULT_GEAR_SPAN_PCT == 100,
                    "unset -> 100")
    passed &= check(wp.gear_span_pct_from_env({wp.GEAR_SPAN_PCT_ENV: "0"}) == 0, "0 accepted")
    passed &= check(wp.gear_span_pct_from_env({wp.GEAR_SPAN_PCT_ENV: "250"}) == 250,
                    "250 accepted")
    passed &= check(all(_rejects(r) for r in ("-1", "1.5", "abc", "")),
                    "negatives, fractions and text rejected")
    for name in ("JUMP_MODEL_PCT_ENV", "JUMP_BLOCK_COST_ENV", "JUMP_LANDING_COST_PCT_ENV",
                 "JUMP_BLOCK_PCT_ENV", "SEGMENT_KB_ENV", "WRITE_THREADS_ENV"):
        passed &= check(getattr(wp, name) == getattr(work_plan_v7_1, name),
                        f"{name} is v7.1's ({getattr(wp, name)})")
    passed &= check((wp.DEFAULT_JUMP_MODEL_PCT, wp.DEFAULT_JUMP_BLOCK_COST,
                     wp.DEFAULT_JUMP_LANDING_COST_PCT) == (100, 300, 10), "v7.1's defaults")
    return passed


def main():
    passed = True
    for part in (check_optimum, check_gear_span, check_jump_from, check_gain, check_knob):
        passed &= part()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
