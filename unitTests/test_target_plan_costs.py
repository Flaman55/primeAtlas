"""The target planner's costs (primeatlas/generation/target_plan_costs.py): the seconds of an
Atlas run and of a Pseudosquares run of given windows, from the time model.

Rules checked:
  - Atlas: the selected engine's estimate of one run from the group's first window, writing
    into the storage, with that engine named; a seed calibration is used and flagged
    estimated; no calibration or a floor the engine does not run -> None;
  - Pseudosquares: the print calibration, else the count calibration (flagged), else None;
    a range past the program's stop -> None; timed without writing into the storage;
  - a plan of 1000 dense targets with these costs takes under a second.
    python unitTests/test_target_plan_costs.py
"""
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))

W = 10_000_000


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def samples_of(time_model, engine, rows):
    """time_model.Sample rows at floor 25: (windows, seconds) each, no file writing."""
    return [time_model.Sample(engine, 25, w * W, 10 ** 25 + w * W, s, None, False, s, "x")
            for w, s in rows]


def main():
    from benchmark_log_schema import ENGINE_PSEUDOSQUARES_COUNT, ENGINE_PSEUDOSQUARES_PRINT
    import pseudosquares_const

    from primeatlas.generation import (engine_advisor, target_plan_costs as tpc,
                                       target_planner as tp, time_model)
    passed = True
    v7 = samples_of(time_model, "v7", [(1000, 263.0), (2500, 343.0)])
    pss_print = samples_of(time_model, ENGINE_PSEUDOSQUARES_PRINT, [(1, 6.0), (100, 230.0)])
    pss_count = samples_of(time_model, ENGINE_PSEUDOSQUARES_COUNT, [(1, 5.0), (100, 220.0)])
    samples = v7 + pss_print + pss_count

    costs = tpc.make_costs(samples, "v7")
    cal = time_model.calibrate(samples, "v7")
    want = time_model.estimate(cal, "v7", 25, 300, True, start=10 ** 25 + 40 * W).run_seconds
    got = costs.atlas(25, 40, 300)
    passed &= check(got is not None and abs(got[0] - want) < 1e-9 and got[1] == "v7",
                    f"Atlas: the v7 estimate from the group's first window ({got} vs {want})")
    passed &= check(not costs.atlas_estimated, "a logged engine is not flagged estimated")
    worst = 0.0
    for engine in ("v7", "pt1", "pt1-pss"):
        c = tpc.make_costs(samples, engine)
        cal_e = engine_advisor.calibrations(samples, 0, guests=()).get(engine)
        for floor, idx, windows in ((25, 0, 1), (25, 999, 37), (25, 5, 40_000), (25, 5, 1),
                                    (19, 123, 456), (28, 10 ** 9, 3)):
            got = c.atlas(floor, idx, windows)
            ok_floor = cal_e is not None and engine_advisor.fits_floor(
                engine, floor, windows, 0, 10 ** floor + idx * W)
            if not ok_floor:
                worst = max(worst, 0.0 if got is None else float("inf"))
                continue
            want = time_model.estimate(cal_e[0], engine, floor, windows, True,
                                       start=10 ** floor + idx * W).run_seconds
            worst = max(worst, abs(got[0] / want - 1))
    passed &= check(worst < 1e-9, f"v7, pt1, pt1-pss over ends and widths: the cost equals the "
                                  f"run's estimate (worst relative gap {worst})")
    pcal = time_model.calibrate(samples, ENGINE_PSEUDOSQUARES_PRINT)
    want = time_model.estimate(pcal, ENGINE_PSEUDOSQUARES_PRINT, 25, 3, False,
                               start=10 ** 25 + 7 * W).run_seconds
    passed &= check(abs(costs.pss(25, 7, 3) - want) < 1e-9
                    and costs.pss_engine == ENGINE_PSEUDOSQUARES_PRINT,
                    "Pseudosquares: the print calibration, no writing")

    costs = tpc.make_costs(v7 + pss_count, "v7")
    passed &= check(costs.pss(25, 0, 1) is not None
                    and costs.pss_engine == ENGINE_PSEUDOSQUARES_COUNT,
                    "no print rows: the count calibration, named")
    costs = tpc.make_costs(v7, "v7")
    passed &= check(costs.pss(25, 0, 1) is None and costs.pss_engine is None,
                    "no Pseudosquares rows: no Pseudosquares cost")

    costs = tpc.make_costs(pss_print, "v7")
    seeded = engine_advisor.calibrations([], 0).get("v7")
    passed &= check((costs.atlas(25, 0, 10) is not None) == (seeded is not None)
                    and costs.atlas_estimated == (seeded is not None),
                    "no v7 rows: the seed estimate, flagged estimated")
    costs = tpc.make_costs(samples, "no-such-engine")
    passed &= check(costs.atlas(25, 0, 10) is None, "an engine without any calibration: None")

    costs = tpc.make_costs(samples, "v4.1")
    passed &= check(costs.atlas(25, 0, 2000) is None,
                    "a run wider than the engine's per-run cap: None")
    costs = tpc.make_costs(samples, "v7")
    stop = pseudosquares_const.MAX_STOP
    floor = pseudosquares_const.MAX_FLOOR
    last = (stop - 10 ** floor) // W
    passed &= check(costs.pss(floor, last + 1, 1) is None and costs.pss(floor, 0, 1) is not None
                    and costs.pss(floor + 1, 0, 1) is None,
                    "Pseudosquares past its stop or floor: None")

    rng = random.Random(5)
    targets = [tp.Target(i, 10 ** 25 + rng.randrange(40_000 * W), 0) for i in range(1000)]
    targets = [t._replace(hi=t.lo) for t in targets]
    t0 = time.perf_counter()
    tp.plan_targets(targets, W, lambda f: set(), lambda f: 40_000, costs.atlas, costs.pss)
    seconds = time.perf_counter() - t0
    passed &= check(seconds < 1.0, f"1000 dense targets with the model's costs: {seconds:.2f} s")

    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
