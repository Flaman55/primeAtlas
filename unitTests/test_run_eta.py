"""
test_run_eta.py -- the remaining time of a running generation run, from the time model.

A. run_eta.RunEta (pure):
   - before any progress it counts down the modelled total by the wall clock, never below 0;
   - a run ahead of the model (progress past the clock) counts from the progress;
   - once the reported work reaches TRUST_SHARE of the model, the modelled rest is scaled
     by the measured pace (elapsed / modelled work done);
   - iterations add up: iteration 2 at 50 % counts iteration 1 whole plus half of 2's
     sieve and write after its prep;
   - progress never moves back (interleaved instances print lower percents), a percent
     over 100 and an iteration past the count are clamped, an iteration's done line counts
     it whole;
   - no iterations or a zero total: no estimate (None).
B. The real Generation tab (isolated app, v7 calibrated from its seed rows):
   - a direct Quick-gen run starts the estimate for its own range; the status shows
     "running" and an ETA, counting down from the model before any progress line;
   - a progress line moves the estimate; the status keeps the progress text in front;
   - the clock refreshes the status about once a second, but leaves a message another
     part of the app wrote meanwhile;
   - the run's done line ends the estimate: the status is the plain done text;
   - an engine without a calibration shows the running time only;
   - a pipeline (loop) run models one run per iteration from the store's continuation,
     each iteration further by instances x windows; its iteration lines advance it.

Usage (Windows, real display):
    python unitTests/test_run_eta.py
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))
sys.path.insert(0, _SCRIPT_DIR)

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def near(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol


def part_a():
    from primeatlas.generation.run_eta import RunEta, TRUST_SHARE
    check(TRUST_SHARE == 0.1, "the measured pace is trusted from 10 % of the modelled work")
    eta = RunEta([(10.0, 90.0)])
    check(near(eta.total, 100.0), "total = prep + sieve and write")
    check(near(eta.remaining(0.0), 100.0), "at launch: the modelled total")
    check(near(eta.remaining(30.0), 70.0), "no progress yet: counts down by the clock")
    check(eta.remaining(250.0) == 0.0, "past the model without progress: 0, never negative")
    eta.mark_sieve(1, 5.0)          # done = 10 + 4.5 = 14.5 > 10 % of 100
    check(near(eta.remaining(5.0), 85.5 * 5.0 / 14.5),
          "ahead of the model past the trust share: the rest scaled by the measured pace")
    slow = RunEta([(10.0, 90.0)])
    slow.mark_sieve(1, 50.0)        # done = 55
    check(near(slow.remaining(110.0), 45.0 * 2.0), "twice slower than the model: rest x 2")
    early = RunEta([(0.0, 100.0)])
    early.mark_sieve(1, 5.0)        # done = 5 < 10: not trusted yet
    check(near(early.remaining(2.0), 95.0), "under the trust share, ahead: counts from the progress")
    check(near(early.remaining(20.0), 80.0), "under the trust share, behind: counts by the clock")

    loop = RunEta([(10.0, 90.0)] * 3)
    check(near(loop.total, 300.0), "three iterations: three runs")
    loop.mark_sieve(2, 50.0)        # 100 + 10 + 45
    check(near(loop.done, 155.0), "iteration 2 at 50 %: iteration 1 whole + prep + half")
    loop.mark_sieve(2, 20.0)
    check(near(loop.done, 155.0), "a lower percent later never moves the progress back")
    loop.mark_sieve(1, 100.0)
    check(near(loop.done, 155.0), "an earlier iteration's line never moves it back")
    loop.mark_iteration_done(2)
    check(near(loop.done, 200.0), "iteration 2's done line: two iterations whole")
    loop.mark_sieve(3, 250.0)
    check(near(loop.done, 300.0), "a percent over 100 is clamped")
    loop.mark_sieve(9, 10.0)
    check(near(loop.done, 300.0), "an iteration past the count is clamped")
    check(loop.remaining(400.0) == 0.0, "all modelled work done: 0")

    check(RunEta([]).remaining(5.0) is None, "no iterations: no estimate")
    check(RunEta([(0.0, 0.0)]).remaining(5.0) is None, "a zero total: no estimate")


def part_b():
    import time
    import tkinter.messagebox
    tkinter.messagebox.showinfo = lambda *a, **k: None
    tkinter.messagebox.showerror = lambda *a, **k: None
    tkinter.messagebox.askyesno = lambda *a, **k: True
    from app_sandbox import isolate_app
    prime_atlas_v2, _portal = isolate_app()
    from primeatlas.generation import (engine_advisor_seeds, generation_tab, run_eta,
                                       time_model)

    class _Runner:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

        def is_running(self):
            return True

        def stop(self):
            pass

    generation_tab.WslLoggedRunner = _Runner
    cal = time_model.calibrate(engine_advisor_seeds.seed_samples("v7"), "v7")
    app = prime_atlas_v2._build_gui()()
    clock = {"now": 1000.0}
    run_eta.now = lambda: clock["now"]
    try:
        gen = app.generation_tab_widget
        gen._loop_runner_factory = _Runner
        gen._advice_cals = (gen._advice_pt1_b(), {"v7": (cal, False)})
        gen._engine_fields.engine_var.set("v7")
        gen._loop_write_files_var.set(False)
        tpl = gen.T("gen.status_elapsed_eta", elapsed="@E@", eta="@T@")
        running = tpl.split("@E@")[0]                    # "| running: "
        eta_mark = tpl.split("@E@")[1].split("@T@")[0]   # ", ETA: "

        def shows_eta(text):
            return running in text and eta_mark in text

        floor, idx, windows = 22, 40, 500
        lo = 10 ** floor + idx * time_model.WINDOW_WIDTH
        est = time_model.estimate(cal, "v7", floor, windows, False, start=lo)
        gen._loop_runner = None
        gen._on_run_orchestrator_direct(floor, idx, windows)
        eta = gen._run_eta
        check(eta is not None and near(eta.total, est.run_seconds, 1e-6 * est.run_seconds),
              f"direct run: the estimate is the model's run from its own start "
              f"({eta and eta.total} vs {est.run_seconds})")

        status = gen.status.get()
        check(shows_eta(status),
              f"before any progress line: running time and ETA shown ({status!r})")
        clock["now"] += 0.3 * est.run_seconds
        gen._update_shared_progress_from_generation_chunk(
            "[+] Progress: 50.00% (5/10 batches) | time: 1.00s | ETA ~1s\n")
        status = gen.status.get()
        check(status.startswith(gen.T("gen.status_progress_sieve", percent="50.00", done=5,
                                      total=10)) and shows_eta(status),
              f"a progress line: progress text first, ETA after it ({status!r})")
        check(near(eta.done, est.prep_seconds + 0.5 * (est.run_seconds - est.prep_seconds),
                   1e-6 * est.run_seconds), "the progress line moved the estimate")

        clock["now"] += 0.5
        before = gen.status.get()
        gen._tick_run_status()
        check(gen.status.get() == before, "under a second: the clock does not rewrite")
        clock["now"] += 1.0
        gen._tick_run_status()
        check(gen.status.get() != before and running in gen.status.get(),
              f"a second later: the clock refreshes ({gen.status.get()!r})")
        gen.status.set("search message")
        clock["now"] += 2.0
        gen._tick_run_status()
        check(gen.status.get() == "search message",
              "another part's message is left alone by the clock")

        gen._update_shared_progress_from_generation_chunk(
            "[*] TOTAL PRIMES FOUND this run: 12 across 500 windows\n")
        check(gen.status.get() == gen.T("gen.status_progress_done") and gen._run_eta is None,
              "the done line ends the estimate: the plain done text")
        gen._on_loop_finished(0)

        gen._advice_cals = (gen._advice_pt1_b(), {})
        gen._loop_runner = None
        gen._on_run_orchestrator_direct(floor, idx, windows)
        status = gen.status.get()
        check(running in status and eta_mark not in status,
              f"no calibration: the running time only ({status!r})")
        gen._update_shared_progress_from_generation_chunk(
            "[*] TOTAL PRIMES FOUND this run: 12 across 500 windows\n")
        gen._on_loop_finished(0)

        gen._advice_cals = (gen._advice_pt1_b(), {"v7": (cal, False)})
        gen._loop_vars["base_exponent"].set(str(floor))
        gen._loop_vars["run_count"].set("3")
        gen._loop_vars["n_instances"].set("2")
        gen._loop_vars["window_count_per_run"].set(str(windows))
        gen._loop_vars["window_m"].set(str(time_model.WINDOW_WIDTH))
        gen._loop_runner = None
        gen._on_run_loop()
        eta = gen._run_eta
        step = 2 * windows * time_model.WINDOW_WIDTH
        first = 10 ** floor   # the isolated store is empty: the loop starts at the floor
        expected = sum(time_model.estimate(cal, "v7", floor, windows, False,
                                           start=first + k * step).run_seconds
                       for k in range(3))
        check(eta is not None and len(eta.iterations) == 3
              and near(eta.total, expected, 1e-6 * expected),
              f"loop: one modelled run per iteration, each instances x windows further "
              f"({eta and eta.total} vs {expected})")
        clock["now"] += 0.3 * expected
        gen._update_shared_progress_from_generation_chunk(
            "[LOOP] orchestrator_loop_v2 v2 (parallel instances): 3 iteration(s), 2 instance(s)"
            "/iteration, 500 windows/iteration\n"
            "[LOOP] iteration 2/3: launching 2 instance(s) concurrently -- target_idx 1000..1999\n"
            "[+] Progress: 50.00% (5/10 batches) | time: 1.00s | ETA ~1s\n")
        it = eta.iterations
        check(near(eta.done, it[0][0] + it[0][1] + it[1][0] + 0.5 * it[1][1], 1e-6 * expected),
              "loop: iteration 2 at 50 % advances the estimate past iteration 1")
        check(shows_eta(gen.status.get()), f"loop status shows the ETA ({gen.status.get()!r})")
        gen._update_shared_progress_from_generation_chunk(
            "[LOOP] All iterations complete in 12.0s total.\n")
        check(gen._run_eta is None, "the loop's done line ends the estimate")
        gen._on_loop_finished(0)
    finally:
        app.destroy()


def main():
    part_a()
    part_b()
    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
