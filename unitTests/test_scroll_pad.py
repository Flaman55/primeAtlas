"""
test_scroll_pad.py -- a strip along the right edge of every scrollable page (next to its
scrollbar) where the mouse wheel always scrolls the page, whatever self-scrolling
terminals or lists sit under the rest of the page.

A. ScrollPad: entering binds the wheel app-wide, leaving unbinds it; a wheel notch calls
   scroll(units) with -3 up / +3 down (Windows delta and X11 Button-4/5).
   It is 40px wide by default and shows its label vertically, read top to bottom (rotated 270 degrees).
B. Every page container has one, packed between the page and its scrollbar: each Settings
   sub-tab, the Generation tab, the visualization tabs. A wheel notch over the pad scrolls
   a page whose content does not fit, and does nothing on a page that fits.

Usage:
    python unitTests/test_scroll_pad.py
"""
import os
import sys
import time
import tkinter as tk
from tkinter import ttk

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from primeatlas.core.widgets import SCROLL_PAD_WIDTH, ScrollPad  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


class FakeEvent:
    def __init__(self, delta=0, num=0):
        self.delta = delta
        self.num = num


def _test_pad(root):
    print("\n--- A. ScrollPad ---")
    calls = []
    pad = ScrollPad(root, calls.append, text="Scroll area")
    check(SCROLL_PAD_WIDTH == 40, f"default width is 40px (got {SCROLL_PAD_WIDTH})")
    check(int(pad.frame.cget("width")) == SCROLL_PAD_WIDTH, f"default width {SCROLL_PAD_WIDTH}px")
    pad.frame.pack(side="right", fill="y")
    root.update_idletasks()
    pad._draw_label()
    items = [i for i in pad.frame.find_all() if pad.frame.type(i) == "text"]
    check(len(items) == 1 and pad.frame.itemcget(items[0], "text") == "Scroll area",
          "pad shows its label")
    check(items and float(pad.frame.itemcget(items[0], "angle")) == 270.0, "label is vertical, read top to bottom")
    pad._on_enter(None)
    check(root.bind_all("<MouseWheel>") != "", "entering the pad binds the wheel")
    pad.wheel(FakeEvent(delta=120))
    pad.wheel(FakeEvent(delta=-240))
    pad.wheel(FakeEvent(num=4))
    pad.wheel(FakeEvent(num=5))
    check(calls == [-3, 6, -3, 3], f"wheel notches -> scroll units (got {calls})")
    pad._on_leave(None)
    check(root.bind_all("<MouseWheel>") == "" and root.bind_all("<Button-4>") == "",
          "leaving the pad unbinds the wheel")
    narrow = ScrollPad(root, calls.append, width=12)
    check(int(narrow.frame.cget("width")) == 12, "width is configurable")


def _pages(app):
    settings = app.settings_tab
    pages = [(f"Settings page {i}", pad) for i, pad in enumerate(settings._scroll_pads)]
    pages.append(("Generation", app.generation_tab_widget._scroll_pad))
    for name in ("rings_tab_widget", "tree_tab_widget", "sphere_tab_widget"):
        tab = getattr(app, name, None)
        if tab is not None:
            pages.append((name, getattr(tab, "_scroll_pad", None)))
    return pages


def _canvas_of(pad):
    for child in pad.frame.master.winfo_children():
        if isinstance(child, tk.Canvas):
            return child
    return None


def _wait_mapped(app, widget, timeout=8.0):
    """The main window maps its notebook a moment after construction."""
    deadline = time.time() + timeout
    while not widget.winfo_ismapped() and time.time() < deadline:
        app.update()
        time.sleep(0.05)


def _show(widget):
    """Selects every notebook tab on the way from `widget` up to the root."""
    child, parent = widget, widget.master
    while parent is not None:
        if isinstance(parent, ttk.Notebook):
            parent.select(child)
        child, parent = parent, parent.master


def _test_containers():
    print("\n--- B. page containers ---")
    import tkinter.messagebox as messagebox
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    import prime_atlas_v2
    sys.argv = ["prime_atlas_v2.py"]
    app = prime_atlas_v2._build_gui()()
    try:
        app.geometry("1050x500")
        app.update()
        check(len(app.settings_tab._scroll_pads) == 3, "each of the three Settings sub-tabs has a pad")
        expected = app.settings_tab.T("common.scroll_pad")
        check(expected != "common.scroll_pad", f"locale has common.scroll_pad ({expected!r})")
        for label, pad in _pages(app):
            check(isinstance(pad, ScrollPad), f"{label}: has a ScrollPad")
            if not isinstance(pad, ScrollPad):
                continue
            check(pad.text == expected, f"{label}: pad label comes from the locale")
            check(pad.frame.winfo_manager() == "pack", f"{label}: pad is packed")
            canvas = _canvas_of(pad)
            check(canvas is not None, f"{label}: pad sits next to the page canvas")
        _wait_mapped(app, app.settings_tab.master.master)
        _show(app.settings_tab)
        app.update()
        backup_pad = app.settings_tab._scroll_pads[1]
        canvas = _canvas_of(backup_pad)
        app.settings_tab.update_idletasks()
        notebook = app.settings_tab.winfo_children()[0].winfo_children()[0]
        notebook.select(1)
        app.update()
        before = canvas.yview()[0]
        backup_pad.wheel(FakeEvent(delta=-120))
        app.update()
        after = canvas.yview()[0]
        check(after > before, f"wheel over the pad scrolls the tall Backup page ({before} -> {after})")
        general_pad = app.settings_tab._scroll_pads[0]
        notebook.select(0)
        app.update()
        gcanvas = _canvas_of(general_pad)
        general_pad.wheel(FakeEvent(delta=-120))
        app.update()
        check(gcanvas.yview()[0] == 0.0, f"a page that fits does not scroll (canvas {gcanvas.winfo_height()}px, view {gcanvas.yview()})")
    finally:
        app.destroy()


def main():
    root = tk.Tk()
    root.withdraw()
    try:
        _test_pad(root)
    finally:
        root.destroy()
    _test_containers()


if __name__ == "__main__":
    main()
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  FAIL: {f}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
