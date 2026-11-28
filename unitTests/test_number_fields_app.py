"""Number fields in the real app (core/number_field.py wired into the tabs).

Drives the app (temp storage, launches stubbed). Checks:
  - every ttk.Entry and ttk.Spinbox in the built app is a number field, except the ones the
    source marks "# not a number field" (counted: the marked ones are the only exceptions);
  - every number field names its purpose, a locale key with English and Polish text;
  - Quick-gen Generate refuses a red field of the selected mode, with the reason, puts the
    cursor in it and starts nothing: Floor mode with Width "1,5" (not whole), Floor "3,000"
    (ambiguous), Explore with Iterations "1 000" (above 100), Pseudosquares with Threads "1,5";
  - a red field of another mode does not block the selected one;
  - the same fields in other notations run: Floor "2 5", Width "1 0" hand 25 and 10 windows
    to the launch;
  - Floor mode's Starting point has the minimum 10^7 (floors 0..6 hold one window, set by the
    Floor field): a smaller start (-5, -1e3, -10^3, 0, -0, 9 999 999) is red, Generate refuses
    it (twice: two refusals, nothing else), the Floor field is then empty and editable and the
    engine advice ignores the start; 10^7 is fine (floor 7, read-only); negative -> positive ->
    negative switches the Floor field each time; the planner itself, reached past the refusal,
    rejects a start below 10^7 with its own message and launches nothing.
Windows, real display:
    python unitTests/test_number_fields_app.py
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

from test_time_simulation import FAKE_FREE_RAM, check  # noqa: E402


def _entries(widget, found):
    from tkinter import ttk
    for child in widget.winfo_children():
        if isinstance(child, (ttk.Entry, ttk.Spinbox)) and not isinstance(child, ttk.Combobox):
            found.append(child)
        _entries(child, found)
    return found


def _show(widget):
    """Selects every notebook tab on the way up to `widget`, so it is on screen."""
    from tkinter import ttk
    while widget.master is not None:
        if isinstance(widget.master, ttk.Notebook):
            widget.master.select(widget)
        widget = widget.master


def coverage_checks(app):
    entries = _entries(app, [])
    loose = [str(e) for e in entries if getattr(e, "number_field", None) is None]
    attached = len(entries) - len(loose)
    passed = check(attached >= 190 and len(loose) <= 12,
                   f"{attached} number fields in the app; {len(loose)} text fields left "
                   f"({loose[:3]})")
    return passed & purpose_checks(entries)


def purpose_checks(entries):
    """Every live number field names its purpose, a locale key with text in both languages
    (keys built at run time, e.g. one per engine knob, included)."""
    import json
    folder = os.path.join(ROOT, "primeatlas", "core", "locales")
    locales = {}
    for lang in ("en", "pl"):
        with open(os.path.join(folder, f"strings_{lang}.json"), encoding="utf-8") as f:
            locales[lang] = json.load(f)
    fields = [e.number_field for e in entries if getattr(e, "number_field", None) is not None]
    missing = sorted({f"{lang}:{getattr(field, 'purpose', None)}" for field in fields
                      for lang, strings in locales.items()
                      if not str(strings.get(getattr(field, "purpose", None), "")).strip()})
    purposes = {getattr(field, "purpose", None) for field in fields}
    return check(not missing and len(purposes) >= 60,
                 f"{len(fields)} live fields, {len(purposes)} purposes, each with English and "
                 f"Polish text (missing: {missing[:5]}, {len(missing)} in all)")


def generate_checks(app, gen, errors, launches):
    from primeatlas.core import number_field as nf
    passed = True
    T = gen.T

    def generate():
        errors.clear()
        launches.clear()
        app.update()
        gen._on_quick_generate_clicked()
        app.update()

    def set_mode(mode):
        gen.quick_mode_var.set(mode)
        gen._on_quick_mode_changed()
        app.update()

    def refused(what, var):
        field = nf.problem_field([var])
        parts = {
            "message": bool(errors)
            and T("number_field.fix_field", reason="").split("\n")[0] in errors[0],
            "no launch": not launches,
            "reason": field is not None and bool(errors) and field.problem_text() in errors[0],
            "cursor": field is not None and app.focus_lastfor() is field.entry}
        return check(all(parts.values()),
                     f"{what}: refused with the reason, cursor in the field ({parts})")

    set_mode("floor")
    gen.quick_floor_start_var.set("")
    gen.quick_floor_var.set("25")
    gen.quick_floor_width_var.set("1,5")
    generate()
    passed &= refused("Floor mode, Width 1,5", gen.quick_floor_width_var)
    gen.quick_floor_width_var.set("2")
    gen.quick_floor_var.set("3,000")
    generate()
    passed &= refused("Floor mode, Floor 3,000", gen.quick_floor_var)

    set_mode("explore")
    gen.quick_explore_floor_var.set("25")
    gen.quick_iterations_var.set("1 000")
    generate()
    passed &= refused("Explore, Iterations 1 000", gen.quick_iterations_var)
    gen.quick_iterations_var.set("1")

    set_mode("pseudosquares")
    gen.quick_pseudosquares_threads_var.set("1,5")
    generate()
    passed &= refused("Pseudosquares, Threads 1,5", gen.quick_pseudosquares_threads_var)
    gen.quick_pseudosquares_threads_var.set("Auto")

    set_mode("floor")
    gen.quick_floor_var.set("2 5")
    gen.quick_floor_width_var.set("1 0")
    gen.quick_from_var.set("junk")
    generate()
    passed &= check(not errors and launches and launches[0][0] == 25 and launches[0][2] == 10,
                    f"Floor 2 5, Width 1 0 run (a red Range field does not block Floor mode): "
                    f"{launches} {errors[:1]}")
    gen.quick_from_var.set("")
    return passed


def floor_start_checks(app, gen, errors, launches):
    from primeatlas.core import number_field as nf
    passed = True
    T = gen.T
    var = gen.quick_floor_start_var
    floor_entries = [panel["floor_entry"] for panel in gen._quick_panels]

    def floor_shown():
        return gen.quick_floor_var.get(), {str(e.cget("state")) for e in floor_entries}

    def generate():
        errors.clear()
        launches.clear()
        app.update()
        gen._on_quick_generate_clicked()
        app.update()

    gen.quick_mode_var.set("floor")
    gen._on_quick_mode_changed()
    gen.quick_floor_width_var.set("1")
    for text in ("-5", "-1e3", "-10^3", "0", "9999999"):
        var.set(text)
        app.update()
        field = nf.problem_field([var])
        passed &= check(field is not None and field.problem == "range",
                        f"Starting point {text}: red, below the minimum")
        passed &= check(floor_shown() == ("", {"normal"}),
                        f"Starting point {text}: the Floor field is empty and editable "
                        f"({floor_shown()})")
        passed &= check(gen._advice_start("floor", 25) == 10 ** 25,
                        f"Starting point {text}: the advice ignores it "
                        f"({gen._advice_start('floor', 25)})")
    var.set("-5")
    app.update()
    for click in (1, 2):
        generate()
        passed &= check(len(errors) == 1 and T("number_field.fix_field", reason="").split("\n")[0]
                        in errors[0] and not launches,
                        f"Starting point -5, click {click}: refused, nothing launched ({errors})")
    for text in ("0", "-0", "9999999"):
        var.set(text)
        app.update()
        passed &= check(nf.problem_field([var]) is not None and floor_shown() == ("", {"normal"}),
                        f"Starting point {text}: red, Floor empty and editable ({floor_shown()})")
    var.set("10^7")
    app.update()
    passed &= check(nf.problem_field([var]) is None and floor_shown() == ("7", {"readonly"}),
                    f"Starting point 10^7: fine, floor 7 read-only ({floor_shown()})")
    for text, shown in (("-5", ("", {"normal"})), ("123456789", ("8", {"readonly"})),
                        ("-5", ("", {"normal"}))):
        var.set(text)
        app.update()
        passed &= check(floor_shown() == shown,
                        f"Starting point {text} after a change: Floor {floor_shown()}")
    from primeatlas.core import number_format
    for text in ("-5", "9999999"):
        var.set(text)
        app.update()
        errors.clear()
        launches.clear()
        gen._plan_quick_floor()
        app.update()
        passed &= check(errors == [T("quick.error_floor_start_low",
                                     minimum=number_format.whole(10 ** 7))] and not launches,
                        f"the planner rejects start {text} on its own ({errors} {launches})")
    var.set("")
    gen.quick_floor_var.set("25")
    app.update()
    return passed


def main():
    import prime_atlas_v2
    from tkinter import messagebox
    errors, launches = [], []
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showwarning = lambda *a, **k: None
    messagebox.showerror = lambda title, text, **k: errors.append(text)
    messagebox.askyesno = lambda *a, **k: True
    messagebox.askokcancel = lambda *a, **k: True
    portal = tempfile.mkdtemp(prefix="primeatlas_number_fields_")
    app = None
    passed = False
    try:
        sys.argv = ["prime_atlas_v2.py"]
        from app_sandbox import isolate_app
        isolate_app(portal)
        from primeatlas.generation import time_simulation_controls
        time_simulation_controls.estimate_free_ram_bytes = lambda **_k: FAKE_FREE_RAM
        app = prime_atlas_v2._build_gui()()
        app.update()
        gen = app.generation_tab_widget
        gen._apply_loop_params_and_run = lambda *a, **k: launches.append(a)
        gen._launch_direct_window_range = lambda *a, **k: launches.append(a)
        _show(gen)
        for _ in range(50):
            app.update()
            if gen.winfo_viewable():
                break
            app.after(100)
        passed = coverage_checks(app)
        passed &= generate_checks(app, gen, errors, launches)
        passed &= floor_start_checks(app, gen, errors, launches)
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
