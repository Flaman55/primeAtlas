"""
test_pi_count_notice_controls.py -- the pi(L) notice on the real Generation tab (isolated
app, no WSL; the dialog is replaced by a recorder that answers Enable or Leave disabled).

On an empty storage (no floor has a pi(L) cache):
  - counting off: a pipeline run and a direct run show nothing and launch with the count off;
  - ticking a pi checkbox or switching Benchmark on shows nothing (the notice belongs to the
    run, whose range is known only at its start);
  - a pipeline run (_on_run_loop) with counting on, on a floor without a cache, asks before
    launching: Leave disabled launches with the count off (argv position 7 = "0") and
    unticks the box, Enable with it on ("1"); once the floor has its cache the next run
    does not ask; the direct run (_on_run_orchestrator_direct) the same (argv position 8);
    a low floor without a cache asks too;
  - the seeded box alone: Leave disabled launches with neither the count nor the seed
    environment variable and unticks it, Enable with both;
  - no notice and no launch for a form field that is not a number or while a run is in
    flight; no notice for a floor whose store is full;
  - a continuation in the middle of a floor: the range starts where the store ends, the
    first batch is one instance's slice; a run above the floor's cached L shows nothing,
    one below it (counted from zero) shows the notice;
  - the real dialog: Enable gives True, Leave disabled and closing the window give False;
  - the notice strings exist in English and Polish, the body with its {time} placeholder,
    and the default of both pi fields stays off.

Usage (Windows, real display):
    python unitTests/test_pi_count_notice_controls.py
"""
import json
import os
import sys
import tkinter.messagebox

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []
KEYS = ("gen.pi_notice_title", "gen.pi_notice_body", "gen.pi_notice_enable",
        "gen.pi_notice_leave_off")


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def locale_checks():
    for lang in ("en", "pl"):
        with open(os.path.join(_REPO_ROOT, "primeatlas", "core", "locales",
                               f"strings_{lang}.json"), encoding="utf-8") as f:
            strings = json.load(f)
        missing = [k for k in KEYS if not strings.get(k)]
        check(not missing, f"{lang}: notice strings exist ({missing})")
        check("{time}" in strings.get("gen.pi_notice_body", ""),
              f"{lang}: the body names the estimated time")
    from primeatlas.generation.generation_settings import DEFAULT_GENERATION_SETTINGS
    loop = DEFAULT_GENERATION_SETTINGS["loop"]
    check(loop["compute_sieving_primes_count"] is False and loop["use_known_pi_seed"] is False,
          "both pi fields default to off")


def main():
    tkinter.messagebox.showinfo = lambda *a, **k: None
    tkinter.messagebox.showerror = lambda *a, **k: print("error dialog:", a)
    locale_checks()

    from app_sandbox import isolate_app
    prime_atlas_v2, _portal = isolate_app()
    app = prime_atlas_v2._build_gui()()
    app.update()
    gen = app.generation_tab_widget

    asked = []
    answers = []

    def recorder(time_text):
        asked.append(time_text)
        return answers.pop(0) if answers else False

    gen._ask_pi_count = recorder
    count_var, seed_var = gen._loop_count_sieving_var, gen._loop_use_pi_seed_var
    write_var = gen._loop_write_files_var

    def form(floor):
        for key, value in (("base_exponent", floor), ("run_count", 1), ("n_instances", 1),
                           ("window_count_per_run", 100), ("window_m", 10_000_000)):
            gen._loop_vars[key].set(str(value))

    def reset(count=False, seed=False, write=True):
        write_var.set(write)
        count_var.set(count)
        seed_var.set(seed)
        asked.clear()
        answers.clear()

    def cache(floor):
        folder = os.path.join(gen._get_portal_folder(), f"10p{floor}")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "sieving_primes_count_cache.json"), "w") as f:
            json.dump({"l_final": 1, "count": 0}, f)

    try:
        form(27)
        reset()
        count_var.set(True)
        seed_var.set(True)
        write_var.set(False)
        write_var.set(True)
        check(asked == [] and seed_var.get(),
              f"ticking a pi box or switching Benchmark shows nothing ({asked})")

        import primeatlas.generation.generation_tab as generation_tab_mod
        import primeatlas.generation.loop_section as loop_mod
        import primeatlas.generation.quick_gen_runs as runs_mod

        class _FakeRunner:
            def __init__(self, *a, **k):
                pass

            def start(self):
                pass

            def is_running(self):
                return False

        launched = []
        orig = (generation_tab_mod.WslLoggedRunner, loop_mod.build_wsl_logged_command,
                runs_mod.build_wsl_logged_command)
        generation_tab_mod.WslLoggedRunner = _FakeRunner
        seed_env = []

        def fake_cmd(argv, *a, **k):
            seed_env.append(bool(k.get("use_known_pi_seed")))
            launched.append(argv)
            return argv

        loop_mod.build_wsl_logged_command = fake_cmd
        runs_mod.build_wsl_logged_command = loop_mod.build_wsl_logged_command

        def run(kind, floor=27, answer=None):
            if answer is not None:
                answers.append(answer)
            gen._loop_runner = None
            before = len(launched)
            if kind == "loop":
                gen._on_run_loop()
                pos = 7
            else:
                gen._on_run_orchestrator_direct(floor, 0, 5)
                pos = 8
            return launched[-1][pos] if len(launched) > before else None

        try:
            form(27)
            reset()
            check(run("loop") == "0" and asked == [], "counting off: pipeline run, no notice, count off")
            check(run("direct") == "0" and asked == [], "counting off: direct run, no notice, count off")

            for kind, floor in (("loop", 27), ("direct", 28)):
                form(floor)
                reset(count=True)
                got = run(kind, floor, answer=False)
                check(got == "0" and len(asked) == 1 and not count_var.get(),
                      f"{kind}: Leave disabled -> count off, box unticked ({got}, {asked})")
                reset(count=True)
                got = run(kind, floor, answer=True)
                check(got == "1" and len(asked) == 1,
                      f"{kind}: Enable -> launched with the count on ({got}, {asked})")
                cache(floor)
                reset(count=True)
                got = run(kind, floor)
                check(got == "1" and asked == [],
                      f"{kind}: the floor has its cache -> no notice ({got}, {asked})")
            form(12)
            reset(count=True)
            got = run("loop", 12, answer=True)
            check(got == "1" and len(asked) == 1, f"low floor without a cache asks too ({asked})")

            import primeatlas.generation.pi_count_notice_controls as controls_mod
            for kind, floor in (("loop", 20), ("direct", 21)):
                form(floor)
                reset(seed=True)
                got = run(kind, floor, answer=False)
                check(got == "0" and not seed_env[-1] and not seed_var.get() and len(asked) == 1,
                      f"{kind}, seeded box: Leave disabled -> no count, no seed env, box unticked")
                reset(seed=True)
                got = run(kind, floor, answer=True)
                check(got == "1" and seed_env[-1] and seed_var.get() and len(asked) == 1,
                      f"{kind}, seeded box: Enable -> count on with the seed env")

            form(22)
            gen._loop_vars["run_count"].set("x")
            reset(count=True)
            before = len(launched)
            gen._loop_runner = None
            gen._on_run_loop()
            check(asked == [] and len(launched) == before,
                  "a field that is not a number: no notice, no launch (the form's own error)")

            class _Busy(_FakeRunner):
                def is_running(self):
                    return True

            form(22)
            reset(count=True)
            gen._loop_runner = _Busy()
            before = len(launched)
            gen._on_run_loop()
            gen._on_run_orchestrator_direct(22, 0, 5)
            check(asked == [] and len(launched) == before,
                  "a run already in flight: only the error, no notice, no launch")
            gen._loop_runner = None

            orig_find = controls_mod.find_continuation_target_idx
            try:
                controls_mod.find_continuation_target_idx = lambda *a, **k: 9 * 10 ** 16
                form(23)
                check(gen._pi_loop_form_range() is None, "floor 23 already full: no range")
                reset(count=True)
                check(run("loop", 23) == "1" and asked == [],
                      "full floor: no notice (the loop decides what to do)")
                mid = 5 * 10 ** 13
                controls_mod.find_continuation_target_idx = lambda *a, **k: mid
                form(24)
                for key, value in (("n_instances", 4), ("window_count_per_run", 100),
                                   ("run_count", 3)):
                    gen._loop_vars[key].set(str(value))
                floor, lo, hi, first_hi = gen._pi_loop_form_range()
                W = 10_000_000
                check((floor, lo, hi, first_hi) == (24, 10 ** 24 + mid * W,
                                                    10 ** 24 + mid * W + 300 * W,
                                                    10 ** 24 + mid * W + 25 * W),
                      "continuation mid-floor; 4 instances: first batch is one slice of 25")
                folder = os.path.join(gen._get_portal_folder(), "10p24")
                os.makedirs(folder, exist_ok=True)
                cache_path = os.path.join(folder, "sieving_primes_count_cache.json")
                with open(cache_path, "w") as f:
                    json.dump({"l_final": 10 ** 12 + 1, "count": 1}, f)
                reset(count=True)
                check(run("loop", 24) == "1" and asked == [],
                      "mid-floor run above the floor's cached L: no notice")
                with open(cache_path, "w") as f:
                    json.dump({"l_final": 2 * 10 ** 12, "count": 1}, f)
                reset(count=True)
                got = run("loop", 24, answer=True)
                check(got == "1" and len(asked) == 1,
                      "mid-floor run below the cached L (counts from zero): notice")
            finally:
                controls_mod.find_continuation_target_idx = orig_find

            real_ask = type(gen)._ask_pi_count
            for label_key, close, want in (("gen.pi_notice_enable", False, True),
                                           ("gen.pi_notice_leave_off", False, False),
                                           (None, True, False)):
                def answer_dialog(label_key=label_key, close=close):
                    dialogs = [w for w in gen.winfo_children()
                               if w.winfo_class() == "Toplevel" and w.winfo_exists()]
                    if not dialogs:
                        gen.after(50, answer_dialog)
                        return
                    dialog = dialogs[-1]
                    if close:
                        dialog.tk.eval(dialog.wm_protocol("WM_DELETE_WINDOW"))
                        return
                    stack = [dialog]
                    while stack:
                        w = stack.pop()
                        stack.extend(w.winfo_children())
                        if w.winfo_class() == "TButton" and w.cget("text") == gen.T(label_key):
                            w.invoke()
                            return

                gen.after(50, answer_dialog)
                got = real_ask(gen, "~9 min")
                what = "closing the window" if close else gen.T(label_key)
                check(got is want, f"real dialog: {what} -> {want} (got {got})")
        finally:
            (generation_tab_mod.WslLoggedRunner, loop_mod.build_wsl_logged_command,
             runs_mod.build_wsl_logged_command) = orig
            gen._loop_runner = None
    finally:
        reset()
        app.destroy()

    if failures:
        print(f"\n{len(failures)} FAILED")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
