"""
test_generation_ram_guard.py -- Generate checks a run's predicted RAM against the RAM budget
before it launches, and the free WSL RAM is read without opening the Time simulation window.

A. run_ram.over_budget(): None when the run fits, without a RAM reading and for pt1 / pt1-pss
   (no run-sized buffer); (ram, budget) when it does not; n_instances parallel instances count
   n times, so a width that fits once can be over the budget twice.
B. The real Generation tab (isolated app, WSL stubbed: the RAM probe returns a fixed reading
   and counts its calls, the runner records commands):
   - the free RAM is read when the tab is built and again when a run ends;
   - a pipeline run over the budget asks first (the question names the predicted GB, the
     budget and the free RAM); No launches nothing, Yes launches; a run that fits, a run
     without a RAM reading and a pt1 run launch without a question;
   - two parallel instances of a width that fits once ask;
   - a Quick-gen run launched directly (orchestrator_v3.py) over the budget asks too, and No
     launches nothing;
   - the question exists in English and Polish.

Usage (Windows, real display):
    python unitTests/test_generation_ram_guard.py
"""
import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))
sys.path.insert(0, _SCRIPT_DIR)

RAM = 3_500_000_000   # free RAM in WSL: a budget of 50 % is 1.75 GB
W = 10_000_000
failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


class _Runner:
    commands = []

    def __init__(self, cmd, *args, **kwargs):
        _Runner.commands.append(cmd)

    def start(self):
        pass

    def is_running(self):
        return True

    def stop(self):
        pass


def part_a():
    from primeatlas.generation import engine_options, run_ram
    v6 = engine_options.resolve({"engine": "v6"}, 100)
    fit = run_ram.max_windows_in_budget(
        lambda w: engine_options.resolve({"engine": "v6"}, w), RAM, 100_000, W)
    check(fit and fit > 1, f"v6 fits some windows in a 1.75 GB budget ({fit})")
    check(run_ram.over_budget(v6, fit, W, RAM) is None, "the widest fitting run: no warning")
    over = run_ram.over_budget(engine_options.resolve({"engine": "v6"}, fit + 1000),
                               fit + 1000, W, RAM)
    check(over is not None and over[0] > over[1] == RAM * 0.5,
          f"wider than that: (ram, budget) with ram above the budget ({over})")
    check(run_ram.over_budget(v6, 10 ** 6, W, None) is None, "no RAM reading: no warning")
    pt1 = engine_options.resolve({"engine": "pt1"}, 10 ** 6)
    check(run_ram.over_budget(pt1, 10 ** 6, W, RAM) is None, "pt1: no warning")
    twice = run_ram.over_budget(v6, fit, W, RAM, instances=2)
    check(twice is not None and twice[0] > twice[1],
          "two parallel instances of the widest fitting run: over the budget")
    return fit


def locale_checks():
    for lang in ("en", "pl"):
        with open(os.path.join(_REPO_ROOT, "primeatlas", "core", "locales",
                               f"strings_{lang}.json"), encoding="utf-8") as f:
            text = json.load(f).get("gen.confirm_ram_over_budget", "")
        check(all(f"{{{k}}}" in text for k in ("ram", "budget", "pct", "free")),
              f"{lang}: the question names the run's RAM, the budget and the free RAM")


def part_b(fit):
    import prime_atlas_v2  # noqa: F401
    from tkinter import messagebox
    from app_sandbox import isolate_app
    prime_atlas_v2, _portal = isolate_app()
    from primeatlas.generation import generation_tab, time_simulation_controls
    reads = []
    time_simulation_controls.estimate_wsl_available_ram_bytes = (
        lambda **_k: reads.append(1) or RAM)
    generation_tab.WslLoggedRunner = _Runner
    asked = []
    answer = {"yes": False}
    messagebox.askyesno = lambda *a, **k: asked.append(a) or answer["yes"]
    messagebox.showerror = lambda *a, **k: None
    messagebox.showinfo = lambda *a, **k: None
    app = prime_atlas_v2._build_gui()()
    try:
        gen = app.generation_tab_widget
        for _ in range(50):
            app.update()
            if gen._advice_free_ram is not None:
                break
            app.after(20)
        check(reads and gen._advice_free_ram == RAM,
              f"the free RAM is read when the tab is built ({len(reads)} reads)")

        def run(engine, windows, instances=1, yes=False):
            gen._engine_fields.engine_var.set(engine)
            gen._loop_vars["base_exponent"].set("25")
            gen._loop_vars["window_count_per_run"].set(str(windows))
            gen._loop_vars["n_instances"].set(str(instances))
            asked.clear()
            answer["yes"] = yes
            _Runner.commands.clear()
            gen._loop_runner = None
            gen._on_run_loop()
            gen._loop_runner = None
            return bool(asked), bool(_Runner.commands)

        check(run("v6", fit) == (False, True), "a v6 run that fits: launched, no question")
        check(run("v6", fit + 2000) == (True, False), "over the budget: asked, No launches nothing")
        if asked:
            text = asked[0][1]
            check("GB" in text and "3.5" in text, f"the question names GB and the free RAM ({text!r})")
        check(run("v6", fit + 2000, yes=True) == (True, True), "over the budget, Yes: launched")
        check(run("v6", fit, instances=2) == (True, False),
              "two instances of a width that fits once: asked")
        check(run("pt1", 2000) == (False, True), "pt1: no question")
        gen._set_engine_advice_ram(None)
        check(run("v6", fit + 2000) == (False, True), "no RAM reading: no question")
        gen._set_engine_advice_ram(RAM)

        gen._engine_fields.engine_var.set("v6")
        asked.clear()
        answer["yes"] = False
        _Runner.commands.clear()
        gen._on_run_orchestrator_direct(25, 0, fit + 2000)
        gen._loop_runner = None
        check(asked and not _Runner.commands, "Quick-gen direct run over the budget: asked, No")

        before = len(reads)
        gen._on_loop_finished(0)
        for _ in range(50):
            app.update()
            if len(reads) > before:
                break
            app.after(20)
        check(len(reads) > before, "a finished run reads the free RAM again")
    finally:
        app.destroy()


def main():
    fit = part_a()
    locale_checks()
    part_b(fit)
    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
