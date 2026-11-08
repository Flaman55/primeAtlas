"""
test_benchmark_mode_controls.py -- the Generation tab's "Benchmark (no storage writes)"
checkbox, on the real tab (isolated app, no WSL).

Checks: the checkbox sits next to Generate in every Quick-gen panel copy, and the advanced
form no longer has a write-files checkbox (one control per role); checked means the shared
write_files setting is off, in both directions and there-and-back; the choice is remembered
under generation.loop.write_files, so an install that had files switched off opens in
benchmark mode; it is disabled and shows checked while native primesieve mode is selected (a
native run is always a benchmark) and usable again in another mode or with Native
off; a run launched with it checked passes write_files 0 to the engine, unchecked 1; the
label and its info text exist in English and Polish and the old "PGS2 files" wording is gone.

Usage (Windows, real display):
    python unitTests/test_benchmark_mode_controls.py
"""
import json
import os
import sys
import tkinter.messagebox

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, _SCRIPT_DIR)

failures = []


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
        label = strings.get("gen.check_benchmark", "")
        info = strings.get("gen.info_benchmark", "")
        check(label.startswith("Benchmark"), f"{lang}: checkbox label starts with Benchmark")
        check(bool(info) and "benchmark_log.csv" in info,
              f"{lang}: info text names benchmark_log.csv")
        check("gen.check_write_files" not in strings, f"{lang}: old write-files label removed")
        check(not any("PGS2 files" in v or "plików PGS2" in v for v in strings.values()
                      if isinstance(v, str)), f"{lang}: no 'PGS2 files' wording left")


def _checkbuttons(widget):
    found = []
    for child in widget.winfo_children():
        if child.winfo_class() == "TCheckbutton":
            found.append(child)
        found.extend(_checkbuttons(child))
    return found


def _is_checked(cb):
    return "selected" in cb.state()


def main():
    tkinter.messagebox.showinfo = lambda *a, **k: None
    tkinter.messagebox.showerror = lambda *a, **k: None
    locale_checks()

    from app_sandbox import isolate_app
    prime_atlas_v2, _portal = isolate_app()
    app = prime_atlas_v2._build_gui()()
    app.update()
    gen = app.generation_tab_widget
    T = gen.T
    try:
        cbs = gen._benchmark_checkbuttons
        check(len(cbs) == len(gen._quick_panels) >= 1,
              "one Benchmark checkbox per Quick-gen panel copy")
        check(all(str(cb.cget("text")) == T("gen.check_benchmark") for cb in cbs),
              "the checkbox carries the Benchmark label")
        panel_btn = gen._quick_panels[0]["generate_btn"]
        check(cbs[0].master is panel_btn.master, "it sits in the Generate button's row")
        labels = [str(cb.cget("text")) for cb in _checkbuttons(gen)]
        check(labels.count(T("gen.check_benchmark")) == len(cbs),
              "no second Benchmark checkbox elsewhere on the tab")
        check(not hasattr(gen, "_loop_write_files_cb"),
              "the advanced form has no write-files checkbox of its own")

        cb = cbs[0]
        for write_files in (True, False, True):
            gen._loop_write_files_var.set(write_files)
            app.update()
            check(_is_checked(cb) is (not write_files),
                  f"write_files {write_files}: checkbox {'off' if write_files else 'on'}")
        for _ in range(2):
            before = gen._loop_write_files_var.get()
            cb.invoke()
            app.update()
            check(gen._loop_write_files_var.get() is (not before) and _is_checked(cb) is before,
                  f"click flips benchmark (write_files {before} -> {not before})")

        from primeatlas.core import ui_state_dynamic
        gen._loop_write_files_var.set(True)
        cb.invoke()
        app.update()
        stored = ui_state_dynamic.STORE.get("generation.loop.write_files")
        check(stored in (False, "0", 0), f"benchmark on is remembered as write_files off ({stored!r})")

        gen.quick_mode_var.set("primesieve")
        gen.quick_primesieve_native_var.set(True)
        app.update()
        check(all(str(c.cget("state")) == "disabled" for c in cbs),
              "disabled for native primesieve")
        gen.quick_mode_var.set("floor")
        app.update()
        check(all(str(c.cget("state")) == "normal" for c in cbs), "usable in another mode")
        gen.quick_mode_var.set("primesieve")
        gen.quick_primesieve_native_var.set(False)
        app.update()
        check(all(str(c.cget("state")) == "normal" for c in cbs), "usable with Native off")

        import primeatlas.generation.generation_tab as generation_tab_mod
        import primeatlas.generation.quick_gen_runs as runs_mod

        class _FakeRunner:
            def __init__(self, *a, **k):
                pass

            def start(self):
                pass

            def is_running(self):
                return False

        launched = []
        orig_runner = generation_tab_mod.WslLoggedRunner
        orig_cmd = runs_mod.build_wsl_logged_command
        generation_tab_mod.WslLoggedRunner = _FakeRunner
        runs_mod.build_wsl_logged_command = lambda argv, *a, **k: launched.append(argv) or argv
        try:
            for write_files in (False, True):
                gen._loop_write_files_var.set(write_files)
                gen._on_run_primesieve(19, 0, 10)
                gen._loop_runner = None
        finally:
            generation_tab_mod.WslLoggedRunner = orig_runner
            runs_mod.build_wsl_logged_command = orig_cmd
        check(len(launched) == 2 and launched[0][-1] == "0" and launched[1][-1] == "1",
              f"benchmark on launches write_files 0, off 1 ({[a[-1] for a in launched]})")
    finally:
        app.destroy()

    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
