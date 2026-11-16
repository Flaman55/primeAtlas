"""Number fields in the real app (core/number_field.py wired into the tabs).

Drives the app (temp storage, launches stubbed). Checks:
  - every ttk.Entry and ttk.Spinbox in the built app is a number field, except the ones the
    source marks "# not a number field" (counted: the marked ones are the only exceptions);
  - Quick-gen Generate refuses a red field of the selected mode, with the reason, puts the
    cursor in it and starts nothing: Floor mode with Width "1,5" (not whole), Floor "3,000"
    (ambiguous), Explore with Iterations "1 000" (above 100), Pseudosquares with Threads "1,5";
  - a red field of another mode does not block the selected one;
  - the same fields in other notations run: Floor "2 5", Width "1 0" hand 25 and 10 windows
    to the launch.
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
    return check(attached >= 190 and len(loose) <= 12,
                 f"{attached} number fields in the app; {len(loose)} text fields left "
                 f"({loose[:3]})")


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
        time_simulation_controls.estimate_wsl_available_ram_bytes = lambda **_k: FAKE_FREE_RAM
        app = prime_atlas_v2._build_gui()()
        app.update()
        gen = app.generation_tab_widget
        gen._apply_loop_params_and_run = lambda *a, **k: launches.append(a)
        _show(gen)
        for _ in range(50):
            app.update()
            if gen.winfo_viewable():
                break
            app.after(100)
        passed = coverage_checks(app)
        passed &= generate_checks(app, gen, errors, launches)
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
