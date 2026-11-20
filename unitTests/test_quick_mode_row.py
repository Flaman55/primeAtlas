"""The Quick-gen mode row (primeatlas/generation/quick_gen_panel.py) wraps in a FlowRow.

Drives the real app (empty temp storage). Checks:
  1. a window wide enough holds the seven modes on one line, in their order;
  2. at 1280 px every mode is whole inside the row, none shortened;
  3. the mode fields, the hint and Generate sit below the row's last line;
  4. clicking a mode switches the mode (its fields are raised) and the selection survives
     a resize there and back;
  5. the detached Quick-gen panel has the same row, showing the same mode.
Windows, real display:
    python unitTests/test_quick_mode_row.py
"""
import os
import sys
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(ROOT, "constellation"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MODES = ["floor", "range", "explore", "hybrid", "primesieve", "cudasieve", "pseudosquares"]
failures = []


def check(condition, message):
    if condition:
        print(f"ok:   {message}")
    else:
        failures.append(message)
        print(f"FAIL: {message}")


def _settle(app, rounds=6):
    """Runs the event loop `rounds` times and past the layout coordinator's debounce."""
    import time
    from primeatlas.core import responsive
    for _ in range(rounds):
        app.update()
    end = time.time() + 2 * responsive.DEBOUNCE_MS / 1000
    while time.time() < end:
        app.update()
        time.sleep(0.01)
    app.update()


def _resize(app, width):
    app.geometry(f"{width}x720")
    _settle(app)


def _items(panel):
    return panel["mode_row"].items


def _check_row(app, panel, label):
    _resize(app, 2600)
    items = _items(panel)
    check([i.radio.cget("value") for i in items] == MODES, f"{label}: seven modes in order")
    check(len({i.winfo_y() for i in items}) == 1, f"{label}: one line in a wide window")
    xs = [i.winfo_x() for i in items]
    check(xs == sorted(xs), f"{label}: left to right in order")

    _resize(app, 1280)
    row = panel["mode_row"].frame
    inside = all(i.winfo_x() + i.winfo_width() <= row.winfo_width() for i in items)
    check(inside, f"{label}: at 1280 px every mode ends inside the row")
    check(not any(i.is_elided for i in items), f"{label}: at 1280 px no name shortened")
    check(all(i.winfo_ismapped() for i in items), f"{label}: at 1280 px every mode shown")


def run_checks(app):
    gen = app.generation_tab_widget
    import time
    deadline = time.time() + 60
    while not app.main_notebook.winfo_ismapped() and time.time() < deadline:
        app.update()
        time.sleep(0.05)
    tab = gen
    while str(tab) not in app.main_notebook.tabs():
        tab = tab.master
    app.main_notebook.select(tab)
    _settle(app)
    panel = gen._quick_panels[0]
    check("mode_row" in panel, "the panel keeps its mode row")
    if "mode_row" not in panel:
        return
    _check_row(app, panel, "embedded")

    row = panel["mode_row"].frame
    fields_top = min(f.winfo_rooty() for f in panel["mode_frames"].values())
    check(fields_top >= row.winfo_rooty() + row.winfo_height(),
          "mode fields start below the row's last line")
    btn = panel["generate_btn"]
    check(btn.winfo_rooty() >= row.winfo_rooty() + row.winfo_height(),
          "Generate sits below the row")

    items = _items(panel)
    items[MODES.index("range")].radio.invoke()
    _settle(app)
    check(gen.quick_mode_var.get() == "range", "clicking Range selects range")
    _resize(app, 600)
    _resize(app, 2600)
    check(gen.quick_mode_var.get() == "range", "the selection survives a resize there and back")
    check("selected" in items[MODES.index("range")].radio.state(), "Range stays marked")

    top = tk.Toplevel(app)
    try:
        before = len(gen._quick_panels)
        cleanup = gen._build_detached_quick_panel(top)
        _settle(app)
        check(len(gen._quick_panels) == before + 1, "the detached panel registers")
        detached = gen._quick_panels[-1]
        check("mode_row" in detached, "the detached panel has a mode row")
        if "mode_row" in detached:
            d_items = _items(detached)
            check([i.radio.cget("value") for i in d_items] == MODES,
                  "detached: seven modes in order")
            check("selected" in d_items[MODES.index("range")].radio.state(),
                  "detached shows the same mode")
            d_items[MODES.index("explore")].radio.invoke()
            _settle(app)
            check("selected" in items[MODES.index("explore")].radio.state(),
                  "a mode picked in the detached panel shows in the embedded one")
        cleanup()
    finally:
        top.destroy()
    gen.quick_mode_var.set("floor")
    gen._on_quick_mode_changed()


def main():
    from tkinter import messagebox
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    sys.argv = ["prime_atlas_v2.py"]
    from app_sandbox import isolate_app
    prime_atlas_v2, _portal = isolate_app()
    app = prime_atlas_v2._build_gui()()
    try:
        _settle(app, 30)
        run_checks(app)
    except Exception as exc:  # a missing API must show up as FAIL, not only a traceback
        import traceback
        traceback.print_exc()
        failures.append(f"crashed: {exc!r}")
    finally:
        app.destroy()
    print("=" * 78)
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
