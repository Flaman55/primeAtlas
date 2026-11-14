"""
test_primesieve_native_controls.py -- Quick-gen primesieve mode's "Native" checkbox and its
print/count choice, on the real Generation tab (isolated app, no WSL).

Checks: the checkbox starts off and the print/count list is disabled until it is on; with
primesieve mode selected and Native on, the Benchmark checkbox is disabled (a
native run is always a benchmark) and it comes back when Native is off or another mode is
chosen; Generate launches primesieve_native.py with the chosen mode when Native is on and
prime_sieve_primesieve.py otherwise; both info texts exist in English and Polish, the native
one names the storage and thread facts, the wrapper one names the overhead, and neither
claims a speed primesieve does not have.

Planning with Native on never reads the storage (a native run writes nothing there): on a
floor whose first windows exist, a blank From starts at the floor's start and leaves From
blank, a From inside existing windows launches those windows, and the status says nothing is
written; a range past 2^64 is clamped and noted, a From past it refused. With Native off the
same request still reports the windows as already in storage.

Usage (Windows, real display):
    python unitTests/test_primesieve_native_controls.py
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
        keys = ("quick.field_primesieve_native", "quick.info_primesieve_native",
                "quick.info_primesieve_wrapper", "quick.primesieve_mode_print",
                "quick.primesieve_mode_count")
        check(all(strings.get(k) for k in keys), f"{lang}: native-mode strings exist")
        native = strings.get("quick.info_primesieve_native", "")
        wrapper = strings.get("quick.info_primesieve_wrapper", "")
        check("primesieve/10p" in native, f"{lang}: native info names the primesieve folder")
        check("1" in native and "π" in native, f"{lang}: native info: print one thread, "
                                                f"count gives pi(x)")
        for word in ("not sieving", "nie wynik sitowania", "nie jest sitowaniem"):
            check(word not in native, f"{lang}: native info does not call count non-sieving")
        for word in ("faster", "szybsz", "would be"):
            check(word not in native.lower(), f"{lang}: native info claims no speed ({word})")
        check(wrapper and ("overhead" in wrapper or "narzut" in wrapper),
              f"{lang}: wrapper info names the overhead")


def planning_checks(gen, portal):
    from test_generation_launch_planning import _touch_window
    W = 10_000_000
    for idx in range(3):
        _touch_window(portal, 12, idx)
    calls, errors = [], []
    gen._apply_primesieve_params_and_run = lambda *a: calls.append(a)
    tkinter.messagebox.showerror = lambda *a, **k: errors.append(a)
    gen.quick_mode_var.set("primesieve")

    def generate(native, frm, floor="12", width="3"):
        calls.clear()
        errors.clear()
        gen.quick_status_var.set("")
        gen.quick_primesieve_native_var.set(native)
        gen.quick_primesieve_from_var.set(frm)
        gen.quick_primesieve_floor_var.set(floor)
        gen.quick_primesieve_width_var.set(width)
        gen._on_quick_generate_clicked()
        return gen.quick_status_var.get()

    status = generate(True, "")
    check(calls == [(12, 0, 3)], f"Native, blank From: floor start, 3 windows (got {calls})")
    check(gen.quick_primesieve_from_var.get() == "", "Native, blank From stays blank")
    nothing = gen.T("quick.summary_primesieve_native", mode="x", lo="x", hi="x", floor="x",
                    count="x").splitlines()[-1]
    check(nothing in status, f"Native: the status says nothing is written (got {status!r})")
    generate(True, str(10 ** 12 + W + 5), width="1")
    check(calls == [(12, 1, 1)], f"Native, From in an existing window: launched (got {calls})")
    status = generate(True, str(2 ** 64 - 3), floor="", width="4")
    check(len(calls) == 1 and calls[0][2] == 1 and "2^64" in status.replace("2⁶⁴", "2^64"),
          f"Native: past 2^64 clamped to one window and noted (got {calls}, {status!r})")
    generate(True, str(2 ** 64), floor="")
    check(not calls and errors, "Native: From past 2^64 - 1 refused")
    status = generate(False, str(10 ** 12), width="3")
    check(not calls and "10,000,000,000,000" not in status and status,
          f"Native off: windows already in storage reported, not launched (got {calls})")
    gen.quick_primesieve_native_var.set(False)
    gen.quick_primesieve_from_var.set("")


def main():
    tkinter.messagebox.showinfo = lambda *a, **k: None
    tkinter.messagebox.showerror = lambda *a, **k: None
    locale_checks()

    from app_sandbox import isolate_app
    prime_atlas_v2, portal = isolate_app()
    app = prime_atlas_v2._build_gui()()
    app.update()
    gen = app.generation_tab_widget
    try:
        check(gen.quick_primesieve_native_var.get() is False, "Native starts off")
        check(gen.quick_primesieve_native_mode_var.get() == "print", "print is the default")
        check(str(gen.quick_primesieve_native_mode_combo.cget("state")) == "disabled",
              "print/count list disabled while Native is off")

        gen.quick_mode_var.set("primesieve")
        gen.quick_primesieve_native_var.set(True)
        app.update()
        check(str(gen.quick_primesieve_native_mode_combo.cget("state")) == "readonly",
              "print/count list usable when Native is on")
        check(str(gen._benchmark_checkbuttons[0].cget("state")) == "disabled",
              "Benchmark disabled for native primesieve")
        gen.quick_mode_var.set("floor")
        app.update()
        check(str(gen._benchmark_checkbuttons[0].cget("state")) == "normal",
              "Benchmark back in another mode")
        gen.quick_mode_var.set("primesieve")
        gen.quick_primesieve_native_var.set(False)
        app.update()
        check(str(gen._benchmark_checkbuttons[0].cget("state")) == "normal",
              "Benchmark back with Native off")

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
            gen.quick_primesieve_native_var.set(True)
            gen.quick_primesieve_native_mode_var.set("count")
            gen._on_run_primesieve(19, 0, 10)
            gen._loop_runner = None
            gen.quick_primesieve_native_var.set(False)
            gen._on_run_primesieve(19, 0, 10)
            gen._loop_runner = None
        finally:
            generation_tab_mod.WslLoggedRunner = orig_runner
            runs_mod.build_wsl_logged_command = orig_cmd
        check(len(launched) == 2, "two launches")
        if len(launched) == 2:
            check(launched[0][2].endswith("primesieve_native.py")
                  and launched[0][3:] == ["19", "0", "10", "10000000", "count"],
                  f"Native: primesieve_native.py <floor> <start> <count> <width> count "
                  f"(got {launched[0]})")
            check(launched[1][2].endswith("prime_sieve_primesieve.py"),
                  "Native off: the Atlas-format wrapper")
        planning_checks(gen, portal)
    finally:
        app.destroy()

    if failures:
        print(f"\n{len(failures)} FAILED")
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
