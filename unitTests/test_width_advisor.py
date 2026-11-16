"""The width proposal (primeatlas/generation/width_advisor.py): which run width the Quick-gen
line proposes for the Floor and Explore modes.

Rules checked:
  - Benchmark (no storage writes), Floor or Explore mode: BENCHMARK_WINDOWS windows (10^11
    numbers), lowered to the widest run that fits (cap); never narrower than the typed width,
    so a typed width at or above the target (or a cap below it) gives no proposal; the
    iterations stay as typed; the speeds come from the estimate (None without one).
  - split_total: a total of windows as iterations x width with exactly that total, the width
    at most the widest run, the fewest iterations an exact split allows; None when no exact
    split fits under a given iteration ceiling or the inputs are below 1. A sweep checks it
    against a brute-force search.
  - plan_split: Explore's typed width x iterations re-split by priority: the exact total
    (split_total) when it lowers the iterations or brings a too-wide width under the widest
    run; else the fewest iterations at the widest run, the width rounded up (a few windows
    more, fewer than the new iteration count) when that lowers the iterations or brings the
    width under the widest run; else the fields as typed. The iteration ceiling bounds both
    splits. A sweep checks it against a reference.
  - Explore mode writing into the storage, more than one iteration: plan_split under the cap;
    an exact split is KIND_EXPLORE, a wider one KIND_EXPLORE_WIDER; no proposal when the plan
    does not lower the iteration count or the model says the new plan is not faster; the total
    times come from the estimate (None without one).
  - Floor mode writing into the storage, one Explore iteration, every other mode, a width,
    iteration count or cap below 1: no proposal.
A sweep over widths, iterations and caps checks the Explore bounds on every combination.
    python unitTests/test_width_advisor.py
"""
import os
import sys
from collections import namedtuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

W = 10_000_000
Est = namedtuple("Est", "run_seconds numbers_per_second")


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def linear(prep=5.0, per_number=1e-9):
    """A run of w windows costs prep + per_number * span, like time_model.estimate()."""
    def estimate(windows):
        run = prep + per_number * windows * W
        return Est(run, windows * W / run)
    return estimate


def no_estimate(_windows):
    return None


def benchmark_checks(wa):
    passed = True
    est = linear()
    for mode in ("floor", "explore"):
        a = wa.advise_width(mode, False, 100, 1, 100_000, est)
        passed &= check(a is not None and a.kind == wa.KIND_BENCHMARK
                        and a.new_windows == wa.BENCHMARK_WINDOWS == 10_000
                        and a.windows == 100 and a.new_iterations == 1,
                        f"{mode}, benchmark, 100 windows: propose 10,000 ({a})")
        passed &= check(a is not None and a.speed == est(100).numbers_per_second
                        and a.new_speed == est(10_000).numbers_per_second
                        and a.new_speed > a.speed,
                        f"{mode}, benchmark: speeds from the estimate, wider is faster")
    a = wa.advise_width("explore", False, 100, 7, 100_000, est)
    passed &= check(a is not None and a.new_iterations == 7 and a.iterations == 7,
                    "benchmark in Explore: the iteration count stays as typed")
    a = wa.advise_width("floor", False, 100, 1, 3000, est)
    passed &= check(a is not None and a.new_windows == 3000,
                    f"a RAM cap of 3000 windows lowers the target to 3000 ({a})")
    for windows, cap, why in ((10_000, 100_000, "typed width equals the target"),
                              (20_000, 100_000, "typed width above the target"),
                              (5000, 3000, "cap below the typed width"),
                              (3000, 3000, "typed width already at the cap")):
        passed &= check(wa.advise_width("floor", False, windows, 1, cap, est) is None,
                        f"benchmark, {why}: no proposal (never narrower)")
    a = wa.advise_width("floor", False, 100, 1, 100_000, no_estimate)
    passed &= check(a is not None and a.new_windows == 10_000
                    and a.speed is None and a.new_speed is None,
                    "benchmark without an estimate: proposal, speeds None")
    return passed


def _brute_split(total, widest, max_iterations=None):
    for iterations in range(1, total + 1):
        if max_iterations is not None and iterations > max_iterations:
            return None
        if total % iterations == 0 and total // iterations <= widest:
            return total // iterations, iterations
    return None


def _reference_plan(windows, iterations, widest, ceiling=None):
    over = windows > widest
    total = windows * iterations
    exact = _brute_split(total, widest, ceiling)
    if exact is not None and (exact[1] < iterations or over):
        return "exact", exact[0], exact[1]
    fewest = -(-total // widest)
    if (ceiling is None or fewest <= ceiling) and (fewest < iterations or over):
        return "wider", -(-total // fewest), fewest
    return "typed", windows, iterations


def plan_checks(wa):
    passed = True
    for typed, widest, ceiling, want in (
            ((1000, 7), 3000, 100, (wa.SPLIT_EXACT, 1750, 4)),
            ((40_000, 13), 10_000, 100, (wa.SPLIT_EXACT, 10_000, 52)),
            ((1, 13), 10_000, 100, (wa.SPLIT_EXACT, 13, 1)),
            ((997, 2), 500, 100, (wa.SPLIT_WIDER, 499, 4)),
            ((997, 7), 5000, 100, (wa.SPLIT_WIDER, 3490, 2)),
            ((50_000, 100), 10_000, 100, (wa.SPLIT_TYPED, 50_000, 100)),
            ((997, 3), 997, 100, (wa.SPLIT_TYPED, 997, 3)),
            ((1000, 2), 1999, 100, (wa.SPLIT_TYPED, 1000, 2)),
            ((10_000, 2), 10_000, 100, (wa.SPLIT_TYPED, 10_000, 2))):
        got = wa.plan_split(typed[0], typed[1], widest, ceiling)
        passed &= check(tuple(got) == want, f"plan {typed[1]} x {typed[0]} under {widest}: "
                                            f"{want} ({tuple(got)})")
    got = wa.plan_split(997, 2, 500, 100)
    passed &= check(got.windows * got.iterations - 1994 == 2,
                    "the wider plan of 2 x 997 under 500 adds 2 windows (4 x 499 = 1996)")
    bad = []
    for windows in (1, 2, 7, 97, 500, 997, 1000, 4321, 10_000, 50_000):
        for iterations in (1, 2, 3, 7, 13, 50, 99, 100):
            for widest in (1, 7, 500, 999, 1000, 3000, 10_000, 100_000):
                for ceiling in (None, 100):
                    got = tuple(wa.plan_split(windows, iterations, widest, ceiling))
                    want = _reference_plan(windows, iterations, widest, ceiling)
                    if got != want:
                        bad.append((windows, iterations, widest, ceiling, got, want))
                        continue
                    kind, w, i = got
                    total = windows * iterations
                    if kind == "exact" and (w * i != total or w > widest):
                        bad.append(("exact", windows, iterations, widest, got))
                    if kind == "wider" and (w > widest or not 0 <= w * i - total < i):
                        bad.append(("wider", windows, iterations, widest, got))
                    if kind != "typed" and ceiling is not None and i > ceiling:
                        bad.append(("ceiling", windows, iterations, widest, got))
    passed &= check(not bad, f"sweep: priority exact > wider > typed, exact keeps the total, "
                             f"wider adds fewer windows than its iterations, both under the "
                             f"widest run and the ceiling ({bad[:3]})")
    return passed


def split_checks(wa):
    passed = True
    for total, widest, want in ((13, 10_000, (13, 1)), (520_000, 10_000, (10_000, 52)),
                                (13_000, 10_000, (6500, 2)), (7000, 3000, (1750, 4)),
                                (10_000, 10_000, (10_000, 1)), (10_001, 10_000, (137, 73)),
                                (6979, 5000, (997, 7)), (1, 1, (1, 1)), (5, 1, (1, 5))):
        got = wa.split_total(total, widest)
        passed &= check(got == want, f"split {total} under {widest}: {want} ({got})")
    passed &= check(wa.split_total(520_000, 10_000, 100) == (10_000, 52)
                    and wa.split_total(520_000, 10_000, 51) is None,
                    "the iteration ceiling: 52 runs fit under 100, none fits under 51")
    passed &= check(wa.split_total(997, 500, 100) is None,
                    "997 windows (a prime) under 500: only 997 x 1, above 100 iterations: None")
    for total, widest in ((0, 10), (10, 0), (-3, 10), (10, -1)):
        passed &= check(wa.split_total(total, widest) is None,
                        f"split {total} under {widest}: None")
    bad = []
    for total in list(range(1, 400)) + [9973, 10_000, 19_998, 65_536, 520_000, 1_000_000]:
        for widest in (1, 2, 3, 7, 10, 64, 999, 1000, 10_000):
            for ceiling in (None, 100):
                got = wa.split_total(total, widest, ceiling)
                if got is not None and (got[0] * got[1] != total or got[0] > widest
                                        or (ceiling is not None and got[1] > ceiling)):
                    bad.append((total, widest, ceiling, got))
                elif total <= 20_000 and got != _brute_split(total, widest, ceiling):
                    bad.append((total, widest, ceiling, got))
    passed &= check(not bad, f"sweep: exact total, width <= widest, fewest iterations, "
                             f"ceiling kept ({bad[:5]})")
    return passed


def explore_checks(wa):
    passed = True
    est = linear()
    a = wa.advise_width("explore", True, 1000, 10, 100_000, est)
    passed &= check(a is not None and a.kind == wa.KIND_EXPLORE
                    and (a.new_iterations, a.new_windows) == (1, 10_000)
                    and (a.iterations, a.windows) == (10, 1000),
                    f"Explore 10 x 1000, cap 100,000: 1 x 10,000 ({a})")
    passed &= check(a is not None and a.seconds == 10 * est(1000).run_seconds
                    and a.new_seconds == est(10_000).run_seconds
                    and a.new_seconds < a.seconds,
                    "Explore: total times from the estimate, the new plan is shorter")
    a = wa.advise_width("explore", True, 1000, 7, 3000, est)
    passed &= check(a is not None and (a.new_iterations, a.new_windows) == (4, 1750),
                    f"Explore 7 x 1000, cap 3000: 4 x 1750, exactly 7000 ({a})")
    a = wa.advise_width("explore", True, 1000, 10, 1000, est)
    passed &= check(a is None, "Explore already at the cap: no proposal")
    a = wa.advise_width("explore", True, 1000, 10, 1500, est)
    passed &= check(a is not None and (a.new_iterations, a.new_windows) == (8, 1250),
                    f"Explore 10 x 1000, cap 1500: 8 x 1250, exactly 10,000 ({a})")
    a = wa.advise_width("explore", True, 1, 13, 10_000, est)
    passed &= check(a is not None and (a.new_iterations, a.new_windows) == (1, 13),
                    f"Explore 13 x 1, cap 10,000: 1 x 13 ({a})")
    a = wa.advise_width("explore", True, 997, 7, 5000, est)
    passed &= check(a is not None and a.kind == wa.KIND_EXPLORE_WIDER
                    and (a.new_iterations, a.new_windows) == (2, 3490),
                    f"Explore 7 x 997, cap 5000: no exact split with fewer iterations, the "
                    f"wider 2 x 3490 ({a})")
    a = wa.advise_width("explore", True, 1000, 7, 3000, est)
    passed &= check(a is not None and a.kind == wa.KIND_EXPLORE,
                    "an exact split is KIND_EXPLORE")
    a = wa.advise_width("explore", True, 1000, 2, 1999, est)
    passed &= check(a is None,
                    "Explore 2 x 1000, cap 1999: still 2 iterations, no proposal")

    def rising(windows):  # no prep, the per-number cost grows with the width
        run = 1e-9 * windows * W * (1 + windows / 1000)
        return Est(run, windows * W / run)

    passed &= check(wa.advise_width("explore", True, 1000, 10, 100_000, rising) is None,
                    "the model says the wider plan is slower: no proposal")
    a = wa.advise_width("explore", True, 1000, 10, 100_000, no_estimate)
    passed &= check(a is not None and (a.new_iterations, a.new_windows) == (1, 10_000)
                    and a.seconds is None and a.new_seconds is None,
                    "Explore without an estimate: proposal, times None")
    passed &= check(wa.advise_width("explore", True, 1000, 1, 100_000, est) is None,
                    "Explore with one iteration: no proposal")

    bad = []
    for windows in (1, 7, 999, 1000, 4321):
        for iterations in range(2, 101, 7):
            for cap in (1, 2, 999, 1000, 1001, 4999, 10_000, 100_000):
                a = wa.advise_width("explore", True, windows, iterations, cap, no_estimate)
                kind, w, i = _reference_plan(windows, iterations, cap)
                if i >= iterations:
                    if a is not None:
                        bad.append(("extra", windows, iterations, cap, a))
                    continue
                want_kind = wa.KIND_EXPLORE if kind == "exact" else wa.KIND_EXPLORE_WIDER
                if a is None or (a.kind, a.new_windows, a.new_iterations) != (want_kind, w, i):
                    bad.append((windows, iterations, cap, a))
    passed &= check(not bad, f"sweep: the proposal is plan_split's whenever it lowers the "
                             f"iterations ({bad[:3]})")
    return passed


def no_proposal_checks(wa):
    passed = True
    est = linear()
    passed &= check(wa.advise_width("floor", True, 100, 1, 100_000, est) is None,
                    "Floor mode writing into the storage: no proposal")
    for mode in ("range", "hybrid", "primesieve", "cudasieve", "pseudosquares"):
        passed &= check(wa.advise_width(mode, False, 100, 1, 100_000, est) is None
                        and wa.advise_width(mode, True, 100, 10, 100_000, est) is None,
                        f"mode {mode}: no proposal")
    for windows, iterations, cap in ((0, 1, 100_000), (100, 0, 100_000), (100, 1, 0),
                                     (-5, 1, 100_000), (100, 10, -1)):
        passed &= check(wa.advise_width("floor", False, windows, iterations, cap, est) is None
                        and wa.advise_width("explore", True, windows, iterations, cap, est)
                        is None,
                        f"width {windows}, iterations {iterations}, cap {cap}: no proposal")
    return passed


def main():
    from primeatlas.generation import width_advisor as wa
    passed = benchmark_checks(wa)
    passed &= split_checks(wa)
    passed &= plan_checks(wa)
    passed &= explore_checks(wa)
    passed &= no_proposal_checks(wa)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
