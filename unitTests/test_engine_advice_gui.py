"""The engine proposal in the Generation tab (engine_advice_controls.py): the line under the
Quick-gen panel and the same proposal in the Time simulation window.

Drives the real app (tkinter, temp storage folder seeded with a synthetic v5 log). Checks:
the Quick-gen line shows engine_advisor.advise()'s proposal for the Floor and Width fields
(floor 30, 100 windows: pt1 with the BPSW warning at the default offset 3); the Time
simulation window shows the very same text; Use selects the proposed engine and is then
disabled; the advanced form's BPSW offset field (default 3, persisted with the form) moves
the proposal (20: pt1-pss, no warning) and an invalid value counts as the default; the line
hides in modes without a floor and width (Range) and comes back unchanged; a RAM budget too
small for the bucketed engines removes them from the options; rows a finished run adds
replace the seed estimate. The proposal is for the run's real start: an empty floor from its
start, a floor with windows from one past the last one (the first gap with "fill gaps
first"), a typed starting point from that number, and clearing it goes back. Windows, real
display:
    python unitTests/test_engine_advice_gui.py
"""
import csv
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_time_simulation import FAKE_FREE_RAM, W, _bound_widgets, _seed_log, check  # noqa: E402


def _mapped(widget):
    return widget.winfo_manager() != ""


def _expected(gen, floor, windows):
    from primeatlas.generation import engine_advisor, time_model
    samples = time_model.read_samples(os.path.join(gen._get_portal_folder(), "benchmark_log.csv"))
    return engine_advisor.advise(samples, floor, windows,
                                 bool(gen._loop_write_files_var.get()), 0,
                                 gen._advice_offset(), lambda _e: True)


def _append_rows(log_path, rows):
    from benchmark_log_schema import BENCHMARK_FIELDNAMES
    with open(log_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BENCHMARK_FIELDNAMES)
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in BENCHMARK_FIELDNAMES})


def start_checks(gen, app):
    from primeatlas.generation import engine_advice_controls as controls
    from test_generation_launch_planning import _touch_window
    passed = True
    starts = []
    real = controls.engine_advisor.advise

    def spy(*a, **k):
        starts.append(k.get("start"))
        return real(*a, **k)

    controls.engine_advisor.advise = spy
    try:
        def start_for(floor="30", typed="", gaps=False):
            gen.quick_floor_start_var.set(typed)
            if not typed:
                gen.quick_floor_var.set(floor)
            gen.quick_floor_fill_gaps_var.set(gaps)
            starts.clear()
            gen._refresh_engine_advice()
            app.update()
            return starts[-1] if starts else "none"

        gen._engine_fields.engine_var.set("v7")  # a sieve engine continues its D store
        gen.quick_mode_var.set("floor")
        gen._on_quick_mode_changed()
        gen.quick_floor_width_var.set("100")
        passed &= check(start_for() == 10 ** 30, "empty floor 30: from 10^30")
        for idx in (0, 1, 2, 4):
            _touch_window(gen._get_portal_folder(), 30, idx)
        passed &= check(start_for() == 10 ** 30 + 5 * W,
                        f"windows 0-2 and 4 stored: from one past the last ({start_for()})")
        passed &= check(start_for(gaps=True) == 10 ** 30 + 3 * W,
                        "fill gaps first: from the first gap (window 3)")
        typed = 10 ** 30 + 123 * W + 7
        passed &= check(start_for(typed=str(typed)) == typed, "typed starting point: from it")
        gen.quick_floor_start_var.set("")
        passed &= check(start_for() == 10 ** 30 + 5 * W, "starting point cleared: back")
    finally:
        controls.engine_advisor.advise = real
        gen.quick_floor_fill_gaps_var.set(False)
    return passed


def run_checks(gen, app, log_path):
    from primeatlas.generation import engine_options, generation_settings
    T = gen.T
    passed = True
    view = gen._quick_advice_views[0]
    gen._engine_fields.engine_var.set("v5")
    gen.quick_mode_var.set("floor")
    gen._on_quick_mode_changed()
    gen._loop_write_files_var.set(False)
    gen.quick_floor_var.set("30")
    gen.quick_floor_width_var.set("100")
    app.update()
    want = _expected(gen, 30, 100)
    passed &= check(_mapped(view) and want.engine == "pt1"
                    and view.proposal_var.get().startswith("pt1,"),
                    f"Quick-gen line: floor 30, 100 windows -> pt1 ({view.proposal_var.get()!r})")
    passed &= check(_mapped(view.warning_label)
                    and view.warning_var.get() == T("advisor.warning_bpsw"),
                    "the BPSW warning shows with a probabilistic proposal")
    gen._open_time_simulation()
    app.update()
    win = gen._time_simulation_window
    passed &= check(win.advice_view is not None
                    and win.advice_view.proposal_var.get() == view.proposal_var.get()
                    and win.advice_view.warning_var.get() == view.warning_var.get(),
                    "the Time simulation window shows the same proposal")
    passed &= check(str(view.use_button.cget("state")) == "normal",
                    "Use is enabled while another engine is selected")
    view.use_button.invoke()
    app.update()
    passed &= check(gen._engine_fields.engine() == "pt1"
                    and str(view.use_button.cget("state")) == "disabled"
                    and str(win.advice_view.use_button.cget("state")) == "disabled",
                    f"Use selects the proposal ({gen._engine_fields.engine()}) and disables itself")

    key = engine_options.ADVISOR_OFFSET_KEY
    passed &= check(generation_settings.DEFAULT_GENERATION_SETTINGS["loop"][key] == "3"
                    and _bound_widgets(gen, gen._advice_offset_var),
                    "the advanced form has the offset field, default 3")
    gen._advice_offset_var.set("20")
    app.update()
    passed &= check(view.proposal_var.get().startswith("pt1-pss,")
                    and not _mapped(view.warning_label)
                    and win.advice_view.proposal_var.get() == view.proposal_var.get(),
                    f"offset 20 -> pt1-pss, no warning, both views ({view.proposal_var.get()!r})")
    gen._advice_offset_var.set("abc")
    app.update()
    passed &= check(view.proposal_var.get().startswith("pt1,"),
                    "an invalid offset counts as the default")
    gen._advice_offset_var.set("3")
    app.update()
    first = view.proposal_var.get()
    gen.quick_mode_var.set("range")
    gen._on_quick_mode_changed()
    app.update()
    passed &= check(not _mapped(view), "the line hides in Range mode")
    gen.quick_mode_var.set("floor")
    gen._on_quick_mode_changed()
    app.update()
    passed &= check(_mapped(view) and view.proposal_var.get() == first,
                    "back in Floor mode: the same proposal")

    knob = gen._engine_fields.knob_vars[engine_options.RAM_BUDGET_KNOB]
    gen._set_engine_advice_ram(FAKE_FREE_RAM)
    knob.set("100")
    advice = gen.engine_advice(28, 10_000)
    passed &= check("v7" in {o.engine for o in advice.options},
                    "a full RAM budget keeps v7 at floor 28, 10^11 numbers")
    knob.set("1")
    advice = gen.engine_advice(28, 10_000)
    left = {o.engine for o in advice.options}
    passed &= check(not left & set(engine_options.BUCKETED_ENGINES) and "pt1-pss" in left,
                    f"a 1 % RAM budget removes the bucketed engines ({sorted(left)})")
    knob.set("50")

    def pss_option():
        return next(o for o in gen.engine_advice(30, 100).options if o.engine == "pt1-pss")

    passed &= check(pss_option().estimated, "pt1-pss without rows: seed estimate")
    _append_rows(log_path, [
        {"engine": "pt1-pss", "base_exponent": "30", "windows_written": str(n),
         "numbers_processed": str(n * W), "target_idx_start": "0",
         "sieve_seconds": str(n * W / 15e6), "total_seconds": str(n * W / 15e6),
         "write_files": "0", "run_status": "completed"} for n in (100, 1000)])
    gen._on_loop_finished(0)
    app.update()
    passed &= check(not pss_option().estimated, "rows of a finished run replace the seed")
    return passed


def main():
    import prime_atlas_v2
    from tkinter import messagebox
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    portal = tempfile.mkdtemp(prefix="primeatlas_advice_test_")
    log_path = _seed_log(portal)
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
        passed = run_checks(app.generation_tab_widget, app, log_path)
        passed &= start_checks(app.generation_tab_widget, app)
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
