"""
test_pseudosquares_controls.py -- Quick-gen Pseudosquares mode on the real Generation tab
(isolated app, no WSL).

Checks: the mode has its own radio button and frame; count is the default mode and Threads
starts at Auto; Threads is usable for count and disabled for print (the program prints on
one thread); while a native mode is selected (Pseudosquares, native primesieve; count and
print) the Benchmark checkbox is disabled and shows checked -- a native run is always a
benchmark -- without changing the user's own setting, which it shows and sets again in
another mode; Generate launches pseudosquares_native.py with the
planned floor/start/count, the mode and the thread count (0 = Auto), from From or from a
Floor with From blank; a bad Threads value, a From past 10^33 and a blank From and Floor
launch nothing; the mode's fields are remembered; the strings exist in English and Polish,
the attribution names Kim Walisch and the BSD 2-Clause License, and the info text names the
text folder, one print thread and claims no speed.

Usage (Windows, real display):
    python unitTests/test_pseudosquares_controls.py
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
errors = []

KEYS = ("quick.mode_pseudosquares", "quick.hint_pseudosquares", "quick.field_threads",
        "quick.info_pseudosquares", "quick.pseudosquares_mode_print",
        "quick.pseudosquares_mode_count", "quick.attribution_pseudosquares",
        "quick.summary_pseudosquares", "quick.note_pseudosquares_clamped",
        "quick.error_pseudosquares_from_required", "quick.error_pseudosquares_range_negative",
        "quick.error_pseudosquares_beyond_ceiling", "quick.error_pseudosquares_width_invalid",
        "quick.error_pseudosquares_threads")


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
        check(not missing, f"{lang}: Pseudosquares strings exist ({missing})")
        attribution = strings.get("quick.attribution_pseudosquares", "")
        check("Walisch" in attribution and "BSD 2-Clause" in attribution,
              f"{lang}: attribution names Kim Walisch and the BSD 2-Clause License")
        info = strings.get("quick.info_pseudosquares", "")
        check("pseudosquares/10p" in info and "1" in info,
              f"{lang}: info names the text folder and one print thread")
        for word in ("faster", "szybsz", "would be"):
            check(word not in info.lower(), f"{lang}: info claims no speed ({word})")


def main():
    tkinter.messagebox.showinfo = lambda *a, **k: None
    tkinter.messagebox.showerror = lambda *a, **k: errors.append(a)
    locale_checks()

    from app_sandbox import isolate_app
    prime_atlas_v2, _portal = isolate_app()
    app = prime_atlas_v2._build_gui()()
    app.update()
    gen = app.generation_tab_widget
    try:
        panel = gen._quick_panels[0]
        check("pseudosquares" in panel["mode_frames"], "Pseudosquares has its own frame")
        check(gen.quick_pseudosquares_mode_var.get() == "count", "count is the default")
        check(gen.quick_pseudosquares_threads_var.get() == "Auto", "Threads starts at Auto")

        gen.quick_mode_var.set("pseudosquares")
        gen._on_quick_mode_changed()
        app.update()
        cb = gen._benchmark_checkbuttons[0]
        gen._loop_write_files_var.set(True)  # the user's setting: Benchmark off
        app.update()
        check(cb.instate(["selected"]), "count: the locked Benchmark shows checked")
        check(gen._loop_write_files_var.get() is True, "count: the user's setting is kept")
        gen.quick_pseudosquares_mode_var.set("print")
        app.update()
        check(cb.instate(["selected"]), "print: the locked Benchmark shows checked too")
        gen.quick_pseudosquares_mode_var.set("count")
        app.update()
        threads = gen._pseudosquares_threads_spinboxes[0]
        check(str(threads.cget("state")) == "normal", "Threads usable for count")
        check(str(gen._benchmark_checkbuttons[0].cget("state")) == "disabled",
              "Benchmark disabled for Pseudosquares")
        gen.quick_pseudosquares_mode_var.set("print")
        app.update()
        check(str(threads.cget("state")) == "disabled", "Threads disabled for print")
        gen.quick_pseudosquares_mode_var.set("count")
        gen.quick_mode_var.set("floor")
        app.update()
        check(str(gen._benchmark_checkbuttons[0].cget("state")) == "normal",
              "Benchmark back in another mode")
        check(not cb.instate(["selected"]) and gen._loop_write_files_var.get() is True,
              "another mode: the checkbox shows the user's own setting again")
        cb.invoke()
        check(gen._loop_write_files_var.get() is False, "another mode: clicking still sets it")
        cb.invoke()
        gen.quick_mode_var.set("primesieve")
        gen.quick_primesieve_native_var.set(True)
        app.update()
        check(str(gen._benchmark_checkbuttons[0].cget("state")) == "disabled",
              "native primesieve still locks Benchmark")
        gen.quick_primesieve_native_mode_var.set("count")
        app.update()
        check(cb.instate(["selected"]), "native primesieve count: shows checked")
        gen.quick_primesieve_native_mode_var.set("print")
        app.update()
        check(cb.instate(["selected"]), "native primesieve print: shows checked")
        gen.quick_primesieve_native_var.set(False)
        app.update()
        check(str(gen._benchmark_checkbuttons[0].cget("state")) == "normal",
              "native primesieve off: Benchmark back")

        import primeatlas.generation.generation_tab as generation_tab_mod
        import primeatlas.generation.quick_gen_pseudosquares as pss_mod

        class _FakeRunner:
            def __init__(self, *a, **k):
                pass

            def start(self):
                pass

            def is_running(self):
                return False

        launched = []
        orig_runner = generation_tab_mod.WslLoggedRunner
        orig_cmd = pss_mod.build_wsl_logged_command
        generation_tab_mod.WslLoggedRunner = _FakeRunner
        pss_mod.build_wsl_logged_command = lambda argv, *a, **k: launched.append(argv) or argv

        def generate(**fields):
            for name, value in fields.items():
                getattr(gen, f"quick_pseudosquares_{name}_var").set(value)
            gen._loop_runner = None
            before = len(launched)
            gen._on_quick_generate_clicked()
            return launched[-1][3:] if len(launched) > before else None

        try:
            gen.quick_mode_var.set("pseudosquares")
            gen.quick_pseudosquares_from_var.set(str(10 ** 25 + 3 * 10 ** 7))
            got = generate(width="2", mode="count", threads="8")
            check(got == ["25", "3", "2", "10000000", "count", "8"],
                  f"From: floor 25, window 3, 2 windows, count, 8 threads (got {got})")
            gen.quick_pseudosquares_from_var.set("")
            got = generate(floor="28", width="1", mode="count", threads="Auto")
            check(got == ["28", "0", "1", "10000000", "count", "0"],
                  f"blank From: the Floor's start, Auto = 0 (got {got})")
            got = generate(floor="28", width="1", mode="print", threads="8")
            check(got == ["28", "0", "1", "10000000", "print", "0"],
                  f"print: no thread count passed (got {got})")
            errors.clear()
            check(generate(floor="28", mode="count", threads="many") is None and errors,
                  "bad Threads: error, no launch")
            errors.clear()
            gen.quick_pseudosquares_from_var.set(str(10 ** 33))
            check(generate(threads="Auto") is None and errors, "From 10^33: error, no launch")
            errors.clear()
            gen.quick_pseudosquares_from_var.set("")
            check(generate(floor="") is None and errors, "blank From and Floor: error, no launch")
        finally:
            generation_tab_mod.WslLoggedRunner = orig_runner
            pss_mod.build_wsl_logged_command = orig_cmd
            gen._loop_runner = None

        from primeatlas.generation import quick_gen_panel
        remembered = set(quick_gen_panel._REMEMBERED_QUICK_VARS)
        check({"quick_pseudosquares_floor_var", "quick_pseudosquares_from_var",
               "quick_pseudosquares_width_var", "quick_pseudosquares_mode_var",
               "quick_pseudosquares_threads_var"} <= remembered, "mode fields remembered")
    finally:
        app.destroy()

    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
