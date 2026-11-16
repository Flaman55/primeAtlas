"""The Quick-gen Auto buttons: v7's widest-run knob and Explore's exact re-split.

Drives the real app (tkinter, temp portal folder) with the free-RAM probe stubbed and the
Auto buttons clicked through their real widgets. Checks:
  - Floor only, v7, plenty of RAM on floor 25: Auto fills the widest-run knob (10,000 windows
    = 10^11 numbers), not the 40,000 RAM and the floor target allow; a raised knob raises it;
    the dialog names the result;
  - Explore, one iteration: Auto widens the width like Floor only, the iterations stay 1;
  - Explore, more iterations: Auto keeps iterations x width exactly and re-splits it into the
    widest window an exact split allows and the fewest iterations (13 x 1 -> 1 x 13,
    13 x 40,000 -> 52 x 10,000, 13 x 7000 -> 10 x 9100), and the dialog names the total;
  - no exact split with fewer iterations: the fewest iterations at the widest window, a few
    windows more (2 x 997 under 500 -> 4 x 499), the dialog says so; neither split within the
    iteration field's ceiling: the fields stay as typed, the dialog says so;
  - a bad iteration or width field: an error, both fields stay;
  - pt1 (not RAM-capped): Explore 3 x 100 -> 1 x 300;
  - Explore's Auto never touches Floor only's width, and Range's Auto touches no width field.
Windows, real display:
    python unitTests/test_quick_auto_split.py
"""
import os
import shutil
import sys
import tempfile
from tkinter import ttk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))

RAM = 64 * 10 ** 9


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def _buttons(widget):
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button):
            yield child
        yield from _buttons(child)


def _auto_button(gen, mode):
    frame = gen._quick_panels[0]["mode_frames"][mode]
    label = gen.T("quick.auto_button")
    return next(b for b in _buttons(frame) if b.cget("text") == label)


def _check_floor(gen, fields, shown):
    passed = True
    gen.quick_floor_var.set("25")
    gen.quick_floor_width_var.set("1")
    shown.clear()
    _auto_button(gen, "floor").invoke()
    passed &= check(gen.quick_floor_width_var.get() == "10000",
                    f"Floor only, v7 @25, 64 GB: Auto stops at 10,000 windows "
                    f"({gen.quick_floor_width_var.get()})")
    passed &= check(shown and shown[-1][0] == "info" and "10,000" in str(shown[-1][1]),
                    "the Auto dialog names 10,000 windows")
    fields.knob_vars["v7_auto_max_windows"].set("20000")
    _auto_button(gen, "floor").invoke()
    passed &= check(gen.quick_floor_width_var.get() == "20000",
                    f"the knob raised to 20,000: Auto fills 20,000 "
                    f"({gen.quick_floor_width_var.get()})")
    fields.knob_vars["v7_auto_max_windows"].set("10000")
    return passed


def _explore(gen, iterations, width):
    gen.quick_iterations_var.set(iterations)
    gen.quick_explore_width_var.set(width)
    _auto_button(gen, "explore").invoke()
    return gen.quick_iterations_var.get(), gen.quick_explore_width_var.get()


def _check_explore(gen, fields, shown):
    passed = True
    gen.quick_explore_floor_var.set("25")
    gen.quick_floor_width_var.set("777")
    passed &= check(_explore(gen, "1", "1") == ("1", "10000"),
                    "Explore, 1 iteration: Auto widens to 10,000 like Floor only, 1 iteration")
    for typed, want in ((("13", "1"), ("1", "13")), (("13", "40000"), ("52", "10000")),
                        (("13", "7000"), ("10", "9100")), (("4", "2500"), ("1", "10000")),
                        (("2", "10000"), ("2", "10000"))):
        shown.clear()
        got = _explore(gen, *typed)
        passed &= check(got == want, f"Explore {typed[0]} x {typed[1]}: Auto gives "
                                     f"{want[0]} x {want[1]}, the same total ({got})")
        total = f"{int(typed[0]) * int(typed[1]):,}"
        passed &= check(shown and shown[-1][0] == "info" and total in str(shown[-1][1]),
                        f"the dialog names the kept total {total}")
    passed &= check(gen.quick_floor_width_var.get() == "777",
                    "Explore's Auto leaves Floor only's width alone")

    fields.knob_vars["v7_auto_max_windows"].set("500")
    shown.clear()
    passed &= check(_explore(gen, "2", "997") == ("4", "499"),
                    "2 x 997 under a 500-window knob: no exact split within 100 iterations, "
                    "the wider 4 x 499")
    passed &= check(shown and shown[-1][0] == "info"
                    and gen.T("quick.auto_split_wider", total="1,994", widest="500",
                              iterations=4, windows="499", new_total="1,996", extra="2")
                    in str(shown[-1][1]),
                    "the dialog names the wider split and the 2 extra windows")
    fields.knob_vars["v7_auto_max_windows"].set("10000")
    shown.clear()
    passed &= check(_explore(gen, "100", "50000") == ("100", "50000"),
                    "100 x 50,000 under 10,000: both splits need 500 iterations, the fields "
                    "stay as typed")
    passed &= check(shown and shown[-1][0] == "info"
                    and gen.T("quick.auto_split_typed", total="5,000,000", widest="10,000",
                              max_iterations=100) in str(shown[-1][1]),
                    "the dialog says the fields stay as typed")

    for typed in (("abc", "100"), ("0", "100"), ("3", "abc"), ("3", "")):
        shown.clear()
        got = _explore(gen, *typed)
        passed &= check(got == typed and shown and shown[-1][0] == "error",
                        f"Explore {typed}: an error, both fields stay ({got})")

    fields.engine_var.set("pt1")
    passed &= check(_explore(gen, "3", "100") == ("1", "300"),
                    "pt1, Explore 3 x 100: 1 x 300 (not RAM-capped)")
    fields.engine_var.set("v7")
    return passed


def _check_range(gen, shown):
    gen.quick_from_var.set("10^25")
    gen.quick_floor_width_var.set("5")
    gen.quick_explore_width_var.set("6")
    shown.clear()
    _auto_button(gen, "range").invoke()
    return check(gen.quick_floor_width_var.get() == "5" and gen.quick_explore_width_var.get()
                 == "6" and shown and shown[-1][0] == "info",
                 "Range's Auto only reports, no width field changes")


def main():
    import prime_atlas_v2
    from primeatlas.generation import quick_gen_panel
    from tkinter import messagebox

    shown = []
    messagebox.showinfo = lambda *a, **k: shown.append(("info", a))
    messagebox.showerror = lambda *a, **k: shown.append(("error", a))
    quick_gen_panel.estimate_free_ram_bytes = lambda *a, **k: RAM

    portal = tempfile.mkdtemp(prefix="primeatlas_quick_auto_test_")
    passed = True
    app = None
    try:
        sys.argv = ["prime_atlas_v2.py"]
        from app_sandbox import isolate_app
        isolate_app(portal)
        app = prime_atlas_v2._build_gui()()
        app.update()
        gen = app.generation_tab_widget
        fields = gen._engine_fields
        fields.engine_var.set("v7")
        app.update()
        passed &= _check_floor(gen, fields, shown)
        passed &= _check_explore(gen, fields, shown)
        passed &= _check_range(gen, shown)
    finally:
        if app is not None:
            app.destroy()
        shutil.rmtree(portal, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
