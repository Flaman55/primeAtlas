"""
test_console_controls.py -- every in-app terminal is a GenerationConsole (Clear, Open in new
window, a height grip under the output), and every height bar in the app is a HeightGrip.

A. GenerationConsole visibility: collapsed by default, start_visible=True shows it; the
   grip is packed exactly while the output is.
B. Console grip drag: height follows the pointer in whole lines, clamped to [min_lines,
   max_lines]; on_change fires once on release, not during the drag.
C. Settings tab: the six logs (restore, full backup, storage integrate, libs, primecount,
   CUDASieve) are visible consoles with Clear/detach/grip; their log methods write into
   every mirror, Clear empties every mirror.
D. Source: settings_tab.py builds no bare ScrolledText log any more (only the license
   text in the CUDASieve consent dialog).
E. HeightGrip on value lists: Listbox and Treeview targets, several targets at once, a
   callable target (a widget rebuilt later), clamping, on_change on release.
F. Height bars are grips everywhere: the Generation tab and the Records table tab build
   no paned window; fixed-height value lists (Settings backup lists, hits search
   results, primality results, Records table) carry a grip.

Usage:
    python unitTests/test_console_controls.py
"""
import os
import sys
import tempfile
import tkinter as tk
from tkinter import ttk

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from primeatlas.core.widgets import HeightGrip  # noqa: E402
from primeatlas.generation.generation_console import GenerationConsole  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


class FakeEvent:
    def __init__(self, y_root):
        self.y_root = y_root


def _packed(widget):
    return widget.winfo_manager() == "pack"


def _lines(widget):
    return int(widget.cget("height"))


def _drag(grip, lines):
    line = grip.line_height()
    grip._on_press(FakeEvent(0))
    grip._on_drag(FakeEvent(lines * line))
    grip._on_release(FakeEvent(0))


def _test_visibility(root):
    print("\n--- A. visibility ---")
    T = lambda key, **kw: key
    hidden = GenerationConsole(tk.Frame(root), T, height=8)
    check(not _packed(hidden.text.frame) and not _packed(hidden.grip),
          "default console starts collapsed, grip hidden with it")
    shown = GenerationConsole(tk.Frame(root), T, height=8, start_visible=True)
    check(_packed(shown.text.frame) and _packed(shown.grip),
          "start_visible=True packs the output and its grip")
    check(shown.toggle_btn.cget("text") == "gen.terminal_hide",
          "start_visible=True labels the toggle as hide")
    shown.hide()
    check(not _packed(shown.text.frame) and not _packed(shown.grip), "hide() unpacks the grip too")
    shown.show()
    check(_packed(shown.grip), "show() packs the grip again")
    check(shown.clear_btn is not None and shown.detach_btn is not None,
          "console has Clear and Open-in-new-window buttons")


def _test_grip(root):
    print("\n--- B. console grip drag ---")
    T = lambda key, **kw: key
    calls = []
    console = GenerationConsole(tk.Frame(root), T, height=8, start_visible=True,
                                on_change=lambda: calls.append(1))
    calls.clear()
    grip = console.height_grip
    check(isinstance(grip, HeightGrip) and console.grip is grip.frame,
          "console's grip is a shared HeightGrip")
    line = grip.line_height()
    check(line > 0, f"line height is positive ({line}px)")
    grip._on_press(FakeEvent(500))
    grip._on_drag(FakeEvent(500 + 5 * line))
    check(_lines(console.text) == 13, f"dragging down 5 lines -> 13 lines (got {_lines(console.text)})")
    grip._on_drag(FakeEvent(500 + 5 * line + line // 3))
    check(_lines(console.text) == 13, "a partial line does not change the height")
    grip._on_drag(FakeEvent(500 - 100 * line))
    check(_lines(console.text) == grip.min_lines,
          f"dragging far up clamps to min_lines={grip.min_lines} (got {_lines(console.text)})")
    grip._on_drag(FakeEvent(500 + 10_000 * line))
    check(_lines(console.text) == grip.max_lines,
          f"dragging far down clamps to max_lines={grip.max_lines} (got {_lines(console.text)})")
    check(calls == [], "on_change does not fire during the drag")
    grip._on_release(FakeEvent(0))
    check(calls == [1], "on_change fires once on release")
    grip._on_drag(FakeEvent(0))
    check(_lines(console.text) == grip.max_lines, "motion after release changes nothing")


def _test_value_grips(root):
    print("\n--- E. HeightGrip on value lists ---")
    frame = ttk.Frame(root)
    row = ttk.Frame(frame)
    row.pack(fill="x")
    left = tk.Listbox(row, height=5)
    right = tk.Listbox(row, height=5)
    left.pack(side="left")
    right.pack(side="left")
    calls = []
    grip = HeightGrip(frame, [left, right], after=row, on_change=lambda: calls.append(1))
    check(_packed(grip.frame) and grip.frame.master is frame, "grip is packed under its row")
    _drag(grip, 4)
    check(_lines(left) == 9 and _lines(right) == 9, "one grip resizes every target together")
    check(calls == [1], "on_change fires on release")
    _drag(grip, -50)
    check(_lines(left) == grip.min_lines, "clamped to min_lines")

    tree = ttk.Treeview(frame, height=4)
    tree.pack()
    tgrip = HeightGrip(frame, tree, after=tree)
    tline = tgrip.line_height()
    check(tline >= 10, f"Treeview grip uses the row height ({tline}px)")
    _drag(tgrip, 3)
    check(_lines(tree) == 7, f"Treeview grows by 3 rows (got {_lines(tree)})")

    holder = {"w": tk.Listbox(frame, height=4)}
    cgrip = HeightGrip(frame, lambda: [holder["w"]], after=row)
    holder["w"] = tk.Listbox(frame, height=6)
    _drag(cgrip, 2)
    check(_lines(holder["w"]) == 8, "a callable target follows the rebuilt widget")


_SETTINGS_CONSOLES = (
    ("restore_console", "_restore_log"),
    ("full_backup_console", "_full_backup_log"),
    ("storage_integrate_console", "_storage_integrate_log"),
    ("libs_console", "_libs_log"),
    ("primecount_console", "_primecount_log"),
    ("cudasieve_console", "_cudasieve_log"),
)

_SETTINGS_GRIPS = ("backup_list_grip", "incomplete_list_grip", "full_backup_lists_grip",
                   "storage_integrate_results_grip")


def _build_app():
    import tkinter.messagebox as messagebox
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    import prime_atlas_v2
    sys.argv = ["prime_atlas_v2.py"]
    app = prime_atlas_v2._build_gui()()
    app.update()
    return app


def _test_settings(app):
    print("\n--- C. Settings tab consoles ---")
    tab = app.settings_tab
    tab.app_settings.save = lambda: None
    tab.wsl["set_portal_folder"](tempfile.mkdtemp(prefix="console_controls_test_"))
    for attr, log_name in _SETTINGS_CONSOLES:
        console = getattr(tab, attr, None)
        check(isinstance(console, GenerationConsole), f"{attr} is a GenerationConsole")
        if not isinstance(console, GenerationConsole):
            continue
        check(console._visible, f"{attr} starts visible")
        check(str(console.clear_btn.cget("command")) != "" and
              str(console.detach_btn.cget("command")) != "",
              f"{attr} has working Clear / detach buttons")
        getattr(tab, log_name)("alpha\n")
        console.open_detached()
        mirror = console._mirrors[-1]
        check(mirror is not console.text and "alpha" in mirror.get("1.0", "end"),
              f"{attr}: detached window is seeded with the existing log")
        getattr(tab, log_name)("beta\n")
        check("beta" in mirror.get("1.0", "end") and "beta" in console.text.get("1.0", "end"),
              f"{log_name} writes into the embedded log and the detached window")
        console.clear()
        check(console.text.get("1.0", "end").strip() == "" and
              mirror.get("1.0", "end").strip() == "",
              f"{attr}: Clear empties both")
        console._detached_win.destroy()
        console._detached_win = None
        console._mirrors.remove(mirror)


def _test_grip_sites(app):
    print("\n--- F. grips everywhere ---")
    gen = app.generation_tab_widget
    for name in ("loop_console", "const_console", "ktuple_console"):
        console = getattr(gen, name)
        check(isinstance(console.height_grip, HeightGrip), f"Generation {name} has a grip")
        console.show()
        check(_packed(console.grip), f"Generation {name}: grip shown with the output")
    check(not hasattr(gen, "_generation_paned"), "Generation tab has no paned window")
    settings = app.settings_tab
    for name in _SETTINGS_GRIPS:
        check(isinstance(getattr(settings, name, None), HeightGrip), f"Settings {name}")
    check(isinstance(getattr(app.constellations_hits_tab_widget, "search_results_grip", None),
                     HeightGrip), "hits search results have a grip")
    check(isinstance(getattr(app.primality_tab_widget, "results_grip", None), HeightGrip),
          "primality results have a grip")
    records = app.constellations_records_tab_widget
    rgrip = getattr(records, "tree_grip", None)
    check(isinstance(rgrip, HeightGrip), "Records table has a grip")
    if isinstance(rgrip, HeightGrip):
        _drag(rgrip, 5)
        dragged = _lines(records.tree)
        records._rebuild_tree([1, 2], row_count=2)
        check(_lines(records.tree) == dragged,
              f"Records table keeps the dragged height across a rebuild "
              f"({_lines(records.tree)} vs {dragged})")


def _test_source():
    print("\n--- D. source ---")
    def read(*rel):
        with open(os.path.join(_REPO_ROOT, "primeatlas", *rel), encoding="utf-8") as f:
            return f.read()
    src = read("settings", "settings_tab.py")
    check(src.count("ScrolledText(") == 1,
          f"only the consent dialog builds a bare ScrolledText (found {src.count('ScrolledText(')})")
    for rel in (("generation", "generation_tab.py"),
                ("constellations", "constellations_records_tab.py")):
        src = read(*rel)
        check("Panedwindow(" not in src and "PanedWindow(" not in src,
              f"{rel[1]} builds no paned window")


def main():
    root = tk.Tk()
    root.withdraw()
    try:
        _test_visibility(root)
        _test_grip(root)
        _test_value_grips(root)
    finally:
        root.destroy()
    app = _build_app()
    try:
        _test_settings(app)
        _test_grip_sites(app)
    finally:
        app.destroy()
    _test_source()


if __name__ == "__main__":
    main()
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  FAIL: {f}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
