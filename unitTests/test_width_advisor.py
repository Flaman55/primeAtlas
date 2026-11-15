"""The width proposal (primeatlas/generation/width_advisor.py): which run width the Quick-gen
line proposes for the Floor and Explore modes.

Rules checked:
  - Benchmark (no storage writes), Floor or Explore mode: BENCHMARK_WINDOWS windows (10^11
    numbers), lowered to the widest run that fits (cap); never narrower than the typed width,
    so a typed width at or above the target (or a cap below it) gives no proposal; the
    iterations stay as typed; the speeds come from the estimate (None without one).
  - Explore mode writing into the storage, more than one iteration: the same total range in
    fewer, wider runs: the fewest iterations the cap allows, the width rounded up, so the
    total never shrinks and the width never passes the cap; no proposal when the cap leaves
    the iteration count unchanged or the model says the new plan is not faster; the total
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
    passed &= check(a is not None and (a.new_iterations, a.new_windows) == (3, 2334),
                    f"Explore 7 x 1000, cap 3000: 3 x 2334 (7002 >= 7000) ({a})")
    a = wa.advise_width("explore", True, 1000, 10, 1000, est)
    passed &= check(a is None, "Explore already at the cap: no proposal")
    a = wa.advise_width("explore", True, 1000, 10, 1500, est)
    passed &= check(a is not None and (a.new_iterations, a.new_windows) == (7, 1429),
                    f"Explore 10 x 1000, cap 1500: 7 x 1429 ({a})")
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
                total = windows * iterations
                if a is None:
                    if -(-total // cap) < iterations and cap > windows:
                        bad.append(("missing", windows, iterations, cap))
                    continue
                if (a.new_windows > cap or a.new_iterations * a.new_windows < total
                        or a.new_iterations >= iterations
                        or a.new_iterations != -(-total // cap)
                        or (a.new_iterations - 1) * a.new_windows >= total):
                    bad.append((windows, iterations, cap, a.new_iterations, a.new_windows))
    passed &= check(not bad, f"sweep: total never shrinks, width <= cap, fewest iterations, "
                             f"no idle iteration ({bad[:5]})")
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
    passed &= explore_checks(wa)
    passed &= no_proposal_checks(wa)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
