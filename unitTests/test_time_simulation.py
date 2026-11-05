"""The Generation tab's Time simulation window: two sliders bound both ways to the Quick-gen
Floor and Width fields, the engine selector shared with the pipeline form, and the times of
time_model.py calibrated from the storage folder's benchmark_log.csv.

Drives the real app (tkinter, temp storage folder seeded with a synthetic v5 log). Checks:
the Quick-gen panel has the button; it opens one window, a second click returns the same
one; the floor slider fills the Floor field and a typed floor moves the slider; the width
slider (log scale up to its cap: the engine's, lowered to the RAM budget) fills the Width field and a typed width moves
it; the engine var is the pipeline form's own, and switching to v4.1 caps the width at
1000; with v5 rows the times, the gross speed and the net sieving
speed are filled and the note names the rows; speeds scale their unit (n/s .. Gn/s) and
durations under a second show in ms / µs; an engine without
rows shows the no-data note and no times; the floor's measured runs (count, windows,
time, speed, the model's time for them) are shown, or that there are none; the whole-floor
line names the floor's size; the predicted RAM of the run (GB and % of the free WSL RAM,
read in the background when the window opens) is shown, the width slider stops at the widest
run that fits the advanced form's RAM budget and follows a budget edit, a typed width above
it is flagged, the info tip names the budget field and the recommended value, pt1 and an
unread RAM leave the slider at the engine's cap; the Explore mode rebinds the window to its own
pair; closing removes the window's traces; the log is never written. Windows, real display:
    python unitTests/test_time_simulation.py
"""
import csv
import math
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))

W = 10_000_000
FAKE_FREE_RAM = 64 * 10 ** 9


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def _seed_log(portal):
    from benchmark_log_schema import BENCHMARK_FIELDNAMES
    rows = []
    for floor, windows, sieve in ((13, 1000, 0.9), (19, 1000, 2.4), (25, 5000, 198.6),
                                  (27, 5000, 944.4), (28, 44228, 3848.7)):
        rows.append({"engine": "v5", "base_exponent": str(floor),
                     "windows_written": str(windows), "numbers_processed": str(windows * W),
                     "target_idx_start": "0", "sieve_seconds": str(sieve),
                     "write_seconds": str(windows * W * 2e-9), "write_files": "1",
                     "run_status": "completed"})
    path = os.path.join(portal, "benchmark_log.csv")
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BENCHMARK_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in BENCHMARK_FIELDNAMES})
    return path


def _find_buttons(widget, text):
    found = []
    for child in widget.winfo_children():
        try:
            if child.winfo_class() == "TButton" and child.cget("text") == text:
                found.append(child)
        except Exception:  # noqa: BLE001
            pass
        found += _find_buttons(child, text)
    return found


def _bound_widgets(widget, var):
    found = []
    for child in widget.winfo_children():
        try:
            if str(child.cget("textvariable")) == str(var):
                found.append(child)
        except Exception:  # noqa: BLE001 -- widgets without a textvariable option
            pass
        found.extend(_bound_widgets(child, var))
    return found


def check_floor_spinboxes(gen):
    """Every Quick-gen Floor field is a Spinbox (arrows and the mouse wheel step the floor);
    a starting point makes the Floor-only field read-only, and clearing it gives it back."""
    from tkinter import ttk
    passed = True
    for name in ("quick_floor_var", "quick_explore_floor_var", "quick_hybrid_target_floor_var",
                 "quick_primesieve_floor_var", "quick_cudasieve_floor_var"):
        widgets = _bound_widgets(gen, getattr(gen, name))
        passed &= check(widgets and all(isinstance(w, ttk.Spinbox) for w in widgets),
                        f"{name}: every field is a Spinbox ({[type(w).__name__ for w in widgets]})")
    floor_fields = _bound_widgets(gen, gen.quick_floor_var)
    gen.quick_floor_start_var.set("10**17")
    passed &= check(gen.quick_floor_var.get() == "17"
                    and all(str(w.cget("state")) == "readonly" for w in floor_fields),
                    "a starting point fills the Floor spinbox and makes it read-only")
    gen.quick_floor_start_var.set("")
    passed &= check(all(str(w.cget("state")) == "normal" for w in floor_fields),
                    "clearing the starting point gives the Floor spinbox back")
    return passed


def check_ram(gen, app, win, T):
    from primeatlas.generation import engine_options, run_budget, run_ram
    passed = True
    knob = gen._engine_fields.knob_vars[engine_options.RAM_BUDGET_KNOB]
    for _ in range(200):
        app.update()
        if win.available_ram is not None:
            break
        app.after(10)
    passed &= check(win.available_ram == FAKE_FREE_RAM,
                    f"the free WSL RAM is read when the window opens ({win.available_ram})")
    gen._engine_fields.engine_var.set("v5")
    knob.set("50")
    gen.quick_floor_width_var.set("5000")
    app.update()
    choice = gen._engine_fields.choice(5000)[0]
    ram = run_ram.run_ram_bytes(choice, 5000, W)
    text = win.result_vars["ram"].get()
    passed &= check(f"{ram / 1e9:.1f} GB" in text and f"{ram / FAKE_FREE_RAM * 100:.0f} %" in text
                    and T("timesim.ram_over_budget") not in text,
                    f"predicted RAM in GB and % of the free WSL RAM ({text!r})")
    fit = run_ram.max_windows_in_budget(gen._engine_fields.choice_for_windows, FAKE_FREE_RAM,
                                        gen._quick_width_cap(), W)
    passed &= check(0 < fit < gen._quick_width_cap() and win.slider_cap() == fit,
                    f"the slider's cap is the widest run in the budget ({win.slider_cap()} vs {fit})")
    win._on_width_slider("1.0")
    passed &= check(gen.quick_floor_width_var.get() == str(fit),
                    f"the slider's right end fills the widest run ({gen.quick_floor_width_var.get()})")
    win._on_width_slider("1.5")
    passed &= check(int(gen.quick_floor_width_var.get()) <= fit, "the slider cannot pass the budget")
    knob.set("25")
    app.update()
    passed &= check(win.slider_cap() < fit, f"a budget edit moves the cap ({win.slider_cap()})")
    knob.set("50")
    gen.quick_floor_width_var.set(str(fit + 1000))
    app.update()
    passed &= check(T("timesim.ram_over_budget") in win.result_vars["ram"].get()
                    and float(win.width_scale.get()) == 1.0,
                    "a typed width above the budget is flagged, the slider stays at its end")
    tip = win.ram_info.text()
    passed &= check(T("gen.field_ram_budget_pct").rstrip(":") in tip and T("gen.advanced_show")
                    .replace("[+] ", "") in tip
                    and f"{round(run_budget.DEFAULT_SAFETY_FRACTION * 100)} %" in tip,
                    f"the info tip names the budget field and the recommended value ({tip!r})")
    gen._engine_fields.engine_var.set("pt1")
    app.update()
    passed &= check(win.result_vars["ram"].get() == T("timesim.ram_pt1")
                    and win.slider_cap() == gen._quick_width_cap(),
                    "pt1: no RAM prediction, the slider keeps the engine's cap")
    gen._engine_fields.engine_var.set("v5")
    win.set_available_ram(None)
    app.update()
    passed &= check(T("timesim.ram_free_unknown") in win.result_vars["ram"].get()
                    and win.slider_cap() == gen._quick_width_cap(),
                    "unread free RAM: said so, the slider keeps the engine's cap")
    win.set_available_ram(FAKE_FREE_RAM)
    gen.quick_floor_width_var.set("5000")
    app.update()
    return passed


def check_formats():
    from primeatlas.core.i18n import Translator
    from primeatlas.generation.time_simulation_window import format_long_duration, format_rate
    T = Translator("en")
    passed = check(format_rate(990.0) == "990.0 n/s" and format_rate(990_000.0) == "990.0 kn/s"
                   and format_rate(81.4e6) == "81.4 Mn/s" and format_rate(2.5e9) == "2.5 Gn/s",
                   "speed unit scales n/s, kn/s, Mn/s, Gn/s")
    passed &= check(format_rate(None) == "?", "unknown speed -> ?")
    passed &= check(format_long_duration(0.04, T) == "40.0 ms"
                    and format_long_duration(0.00004, T) == "40.0 µs"
                    and format_long_duration(42, T) == "42s",
                    "durations under a second in ms / µs")
    return passed


def main():
    passed = check_formats()
    import prime_atlas_v2
    from tkinter import messagebox
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None

    portal = tempfile.mkdtemp(prefix="primeatlas_time_sim_test_")
    log_path = _seed_log(portal)
    with open(log_path, "rb") as f:
        log_before = f.read()
    app = None
    try:
        sys.argv = ["prime_atlas_v2.py"]
        from app_sandbox import isolate_app
        isolate_app(portal)
        from primeatlas.generation import time_simulation_controls
        time_simulation_controls.estimate_wsl_available_ram_bytes = lambda **_k: FAKE_FREE_RAM
        app = prime_atlas_v2._build_gui()()
        app.update()
        gen = app.generation_tab_widget
        T = gen.T
        buttons = _find_buttons(gen, T("timesim.open_button"))
        passed &= check(len(buttons) >= 1, "Quick-gen panel has the Time simulation button")
        if not buttons:
            return 1
        passed &= check_floor_spinboxes(gen)
        gen._engine_fields.engine_var.set("v5")
        gen.quick_mode_var.set("floor")
        gen._on_quick_mode_changed()
        gen.quick_floor_var.set("25")
        gen.quick_floor_width_var.set("5000")
        buttons[0].invoke()
        app.update()
        win = gen._time_simulation_window
        passed &= check(win is not None and win.winfo_exists(), "button opens the window")
        buttons[0].invoke()
        passed &= check(gen._time_simulation_window is win, "second click reuses the window")

        win._on_floor_slider("27.2")
        passed &= check(gen.quick_floor_var.get() == "27", "floor slider fills the Floor field")
        gen.quick_floor_var.set("22")
        app.update()
        passed &= check(round(float(win.floor_scale.get())) == 22,
                        "typed floor moves the floor slider")

        cap = win.slider_cap()
        win._on_width_slider(str(math.log(2000) / math.log(cap)))
        passed &= check(gen.quick_floor_width_var.get() == "2000",
                        f"width slider fills the Width field ({gen.quick_floor_width_var.get()})")
        gen.quick_floor_width_var.set("5000")
        app.update()
        passed &= check(abs(float(win.width_scale.get()) - math.log(5000) / math.log(cap)) < 1e-6,
                        "typed width moves the width slider")

        passed &= check(win.engine_var is gen._engine_fields.engine_var,
                        "engine var shared with the pipeline form")
        gen.quick_floor_var.set("25")
        app.update()
        v = win.result_vars
        passed &= check(v["run"].get() not in ("", "?") and v["speed"].get() != "?",
                        f"v5 times filled (run {v['run'].get()}, speed {v['speed'].get()})")
        net = v["speed_net"].get()
        passed &= check(net not in ("", "?") and net != v["speed"].get(),
                        f"net sieving speed shown apart from the gross one ({net} vs {v['speed'].get()})")
        passed &= check("5" in v["model"].get() and "v5" in v["model"].get(),
                        f"note names the engine and rows ({v['model'].get()!r})")
        gen.quick_floor_var.set("26")
        app.update()
        passed &= check(v["measured"].get() == T("timesim.measured_none"),
                        f"floor without runs says so ({v['measured'].get()!r})")
        gen.quick_floor_var.set("28")
        app.update()
        passed &= check("44,228" in v["measured"].get() and "1" in v["measured"].get(),
                        f"measured runs of the floor shown ({v['measured'].get()!r})")
        passed &= check("9e+28" in v["floor_total"].get(),
                        f"whole-floor line names its size ({v['floor_total'].get()!r})")
        gen.quick_floor_var.set("25")
        app.update()
        passed &= check(T("timesim.exact") in v["primes"].get() or T("timesim.approx")
                        in v["primes"].get(), "prime count says exact or approximate")

        gen._engine_fields.engine_var.set("v4.1")
        app.update()
        passed &= check(win.windows() == 1000, "v4.1 caps the width at 1000")
        passed &= check(v["model"].get() == T("timesim.model_none", engine="v4.1")
                        and v["run"].get() == "?", "engine without rows -> no-data note, no times")
        gen._engine_fields.engine_var.set("v5")
        passed &= check_ram(gen, app, win, T)

        # a run finishing while the window is open: the run's end reloads the log
        gen.quick_floor_var.set("26")
        app.update()
        passed &= check(not any("_poll" in name for name in dir(win)),
                        "the window does not poll the log")
        from benchmark_log_schema import BENCHMARK_FIELDNAMES
        with open(log_path, "a", newline="") as f:
            csv.DictWriter(f, fieldnames=BENCHMARK_FIELDNAMES).writerow(
                {k: {"engine": "v5", "base_exponent": "26", "windows_written": "3333",
                     "numbers_processed": str(3333 * W), "target_idx_start": "0",
                     "sieve_seconds": "700.0", "write_seconds": "1.0", "write_files": "1",
                     "run_status": "completed"}.get(k, "") for k in BENCHMARK_FIELDNAMES})
        with open(log_path, "rb") as f:
            log_before = f.read()
        passed &= check("3,333" not in v["measured"].get(), "the new row is not read before the run ends")
        gen._on_loop_finished(0)
        app.update()
        passed &= check("3,333" in v["measured"].get(),
                        f"a row added while open shows when the run ends ({v['measured'].get()!r})")
        with open(log_path, "a", newline="") as f:
            for floor, windows, sieve in ((25, 5000, 150.0), (27, 5000, 700.0)):
                csv.DictWriter(f, fieldnames=BENCHMARK_FIELDNAMES).writerow(
                    {k: {"engine": "v5", "engine_version": "v5.1", "base_exponent": str(floor),
                         "windows_written": str(windows),
                         "numbers_processed": str(windows * W), "target_idx_start": "0",
                         "sieve_seconds": str(sieve), "write_seconds": "1.0",
                         "write_files": "1", "run_status": "completed"}.get(k, "")
                     for k in BENCHMARK_FIELDNAMES})
        gen._on_loop_finished(0)
        app.update()
        passed &= check("v5.1" in v["model"].get() and "2" in v["model"].get(),
                        f"note names the newest version and its own rows ({v['model'].get()!r})")
        with open(log_path, "rb") as f:
            log_before = f.read()
        gen.quick_floor_var.set("25")
        app.update()

        gen.quick_mode_var.set("explore")
        gen._on_quick_mode_changed()
        app.update()
        win = gen._time_simulation_window
        passed &= check(win.floor_var is gen.quick_explore_floor_var
                        and win.width_var is gen.quick_explore_width_var,
                        "Explore mode rebinds the window to its own fields")

        knob = gen._engine_fields.knob_vars["ram_budget_pct"]
        before = len(gen.quick_explore_floor_var.trace_info())
        knob_before = len(knob.trace_info())
        win.close()
        app.update()
        passed &= check(len(gen.quick_explore_floor_var.trace_info()) == before - 1
                        and len(knob.trace_info()) == knob_before - 1,
                        "closing removes the window's traces")
        gen._on_loop_finished(0)
        app.update()
        passed &= check(gen._time_simulation_window is None or not gen._time_simulation_is_open(),
                        "a run ending with the window closed reopens nothing")
        with open(log_path, "rb") as f:
            passed &= check(f.read() == log_before, "benchmark_log.csv untouched")
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
