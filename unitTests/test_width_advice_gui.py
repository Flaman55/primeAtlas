"""The width proposal line in the Generation tab's Quick-gen panel (width_advisor.py through
engine_advice_controls.py and width_advice_view.py).

Drives the real app (tkinter, temp storage folder seeded with a synthetic v5 log, a fake
64 GB of free WSL RAM). Checks:
  - Floor mode writing into the storage: no width line; Benchmark ticked: the line proposes
    10,000 windows with the speed note, Use writes it into Width and the line hides; Width
    typed at 10,000 or more: no line;
  - Explore, writing, 10 iterations x 1000 windows: the line proposes 1 x 10,000 with the
    total times, Use writes both fields and the line hides; one iteration: no line; the
    iteration field alone refreshes the line;
  - a small RAM budget lowers the proposal to run_ram.max_windows_in_budget();
  - Range mode hides the line; every Quick-gen panel copy has its own width line;
  - the engine line in Explore with more than one iteration says its time is one
    iteration's; in Floor mode and with one iteration it does not;
  - the Floor and Explore hints give the width maximum the engines take (100,000), not
    1000.
Windows, real display:
    python unitTests/test_width_advice_gui.py
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_time_simulation import FAKE_FREE_RAM, _seed_log, check  # noqa: E402


def _mapped(widget):
    return widget.winfo_manager() != ""


def _set_mode(gen, app, mode):
    gen.quick_mode_var.set(mode)
    gen._on_quick_mode_changed()
    app.update()


def floor_checks(gen, app):
    passed = True
    view = gen._quick_width_views[0]
    _set_mode(gen, app, "floor")
    gen._loop_write_files_var.set(True)
    gen.quick_floor_var.set("25")
    gen.quick_floor_width_var.set("100")
    app.update()
    passed &= check(not _mapped(view), "Floor mode writing into the storage: no width line")
    gen._loop_write_files_var.set(False)
    app.update()
    text = view.text_var.get()
    passed &= check(_mapped(view) and "10,000" in text
                    and gen.T("width_advice.benchmark_note") in text,
                    f"Benchmark ticked: 10,000 windows with the speed note ({text!r})")
    passed &= check(str(view.use_button.cget("state")) == "normal", "Use is enabled")
    view.use_button.invoke()
    app.update()
    passed &= check(gen.quick_floor_width_var.get() == "10000" and not _mapped(view),
                    f"Use writes 10000 into Width and the line hides "
                    f"({gen.quick_floor_width_var.get()})")
    gen.quick_floor_width_var.set("20000")
    app.update()
    passed &= check(not _mapped(view), "Width 20,000 typed: no line (never narrower)")
    engine_line = gen._quick_advice_views[0].proposal_var.get()
    passed &= check(gen.T("advisor.per_iteration") not in engine_line,
                    "Floor mode: the engine line has no one-iteration note")
    gen._loop_write_files_var.set(True)
    return passed


def explore_checks(gen, app):
    passed = True
    view = gen._quick_width_views[0]
    _set_mode(gen, app, "explore")
    gen._loop_write_files_var.set(True)
    gen.quick_explore_floor_var.set("25")
    gen.quick_explore_width_var.set("1000")
    gen.quick_iterations_var.set("10")
    app.update()
    text = view.text_var.get()
    passed &= check(_mapped(view) and "10,000" in text and "10 x 1,000" in text
                    and "1 x 10,000" in text,
                    f"Explore 10 x 1000: proposes 1 x 10,000 ({text!r})")
    engine_line = gen._quick_advice_views[0].proposal_var.get()
    passed &= check(gen.T("advisor.per_iteration") in engine_line,
                    f"Explore, 10 iterations: the engine line says one iteration "
                    f"({engine_line!r})")
    gen.quick_iterations_var.set("1")
    app.update()
    passed &= check(not _mapped(view)
                    and gen.T("advisor.per_iteration")
                    not in gen._quick_advice_views[0].proposal_var.get(),
                    "one iteration: no width line, no one-iteration note (iterations "
                    "field alone refreshes)")
    gen.quick_iterations_var.set("10")
    app.update()
    view.use_button.invoke()
    app.update()
    passed &= check((gen.quick_iterations_var.get(), gen.quick_explore_width_var.get())
                    == ("1", "10000") and not _mapped(view),
                    f"Use writes 1 iteration x 10000 and the line hides "
                    f"({gen.quick_iterations_var.get()} x {gen.quick_explore_width_var.get()})")

    from primeatlas.generation import engine_options, run_ram
    from primeatlas.generation.window_planning import QUICK_GEN_MAX_WINDOW_WIDTH
    knob = gen._engine_fields.knob_vars[engine_options.RAM_BUDGET_KNOB]
    old = knob.get()
    knob.set("2")
    gen.quick_explore_width_var.set("100")
    gen.quick_iterations_var.set("50")
    app.update()
    fields = gen._engine_fields
    cap = run_ram.max_windows_in_budget(
        lambda w: fields.choice_for_engine(fields.engine(), w), gen._advice_free_ram,
        engine_options.max_windows_per_run(fields.engine()), QUICK_GEN_MAX_WINDOW_WIDTH)
    iterations = -(-5000 // cap)
    width = -(-5000 // iterations)
    text = view.text_var.get()
    passed &= check(cap is not None and 100 < cap < 5000
                    and f"{iterations} x {width:,}" in text,
                    f"a 2 % RAM budget caps the run at {cap}: {iterations} x {width:,} ({text!r})")
    knob.set(old)
    _set_mode(gen, app, "range")
    passed &= check(not _mapped(view), "Range mode: the line hides")
    passed &= check(len(gen._quick_width_views) == len(gen._quick_advice_views) >= 1,
                    "every Quick-gen panel copy has its own width line")
    return passed


def hint_checks():
    from primeatlas.core.i18n import Translator
    passed = True
    for lang, old, new in (("en", "max 1000", "100,000"), ("pl", "maks. 1000", "100 000")):
        T = Translator(lang)
        for key in ("quick.hint_floor", "quick.hint_explore"):
            passed &= check(old not in T(key) and new in T(key),
                            f"{lang} {key}: the maximum is {new}, not 1000")
    return passed


def main():
    import prime_atlas_v2
    from tkinter import messagebox
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    portal = tempfile.mkdtemp(prefix="primeatlas_width_test_")
    _seed_log(portal)
    app = None
    passed = False
    try:
        sys.argv = ["prime_atlas_v2.py"]
        from app_sandbox import isolate_app
        isolate_app(portal)
        from primeatlas.generation import time_simulation_controls
        time_simulation_controls.estimate_wsl_available_ram_bytes = lambda **_k: FAKE_FREE_RAM
        app = prime_atlas_v2._build_gui()()
        app.update()
        gen = app.generation_tab_widget
        gen._engine_fields.engine_var.set("v7")
        gen._set_engine_advice_ram(FAKE_FREE_RAM)
        passed = floor_checks(gen, app)
        passed &= explore_checks(gen, app)
        passed &= hint_checks()
    finally:
        if app is not None:
            try:
                app.destroy()
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(portal, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
