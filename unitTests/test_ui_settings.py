"""
test_ui_settings.py -- Settings > General > User interface: the scroll-area (ScrollPad)
width is a persisted user setting applied live to every pad in the app.

A. AppSettings.scroll_pad_width: SCROLL_PAD_WIDTH_DEFAULT on a fresh install; a set value
   survives a new AppSettings instance; values are clamped to
   [SCROLL_PAD_WIDTH_MIN, SCROLL_PAD_WIDTH_MAX]; garbage falls back to the default.
B. widgets.set_scroll_pad_width(px): resizes every live ScrollPad, pads built afterwards
   get the new width by default, destroyed pads (also those of a destroyed Tk root) are
   skipped, the value is clamped.
C. Settings tab: General has a User interface section whose spinbox starts at the saved
   width; applying a new value saves it and resizes every pad in the app (Settings
   sub-tabs, Generation, visualization tabs); an invalid entry changes nothing.

Usage:
    python unitTests/test_ui_settings.py
"""
import os
import sys
import tempfile
import tkinter as tk

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from primeatlas.core import app_settings as app_settings_module  # noqa: E402
from primeatlas.core import widgets  # noqa: E402
from primeatlas.core.app_settings import (  # noqa: E402
    SCROLL_PAD_WIDTH_DEFAULT, SCROLL_PAD_WIDTH_MAX, SCROLL_PAD_WIDTH_MIN, AppSettings)
from primeatlas.core.widgets import ScrollPad, set_scroll_pad_width  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _width(pad):
    return int(pad.frame.cget("width"))


def _test_app_settings():
    print("\n--- A. AppSettings.scroll_pad_width ---")
    orig = app_settings_module.LOCALES_DIR
    app_settings_module.LOCALES_DIR = tempfile.mkdtemp(prefix="ui_settings_test_")
    try:
        settings = AppSettings(_REPO_ROOT)
        check(settings.scroll_pad_width == SCROLL_PAD_WIDTH_DEFAULT == 40,
              f"fresh install -> default 40px (got {settings.scroll_pad_width})")
        settings.set_scroll_pad_width(64)
        check(AppSettings(_REPO_ROOT).scroll_pad_width == 64, "a set width survives a reload")
        settings.set_scroll_pad_width(1)
        check(settings.scroll_pad_width == SCROLL_PAD_WIDTH_MIN, "too small -> clamped to min")
        settings.set_scroll_pad_width(10_000)
        check(settings.scroll_pad_width == SCROLL_PAD_WIDTH_MAX, "too large -> clamped to max")
        settings._data["scroll_pad_width"] = "wide"
        check(settings.scroll_pad_width == SCROLL_PAD_WIDTH_DEFAULT, "garbage -> default")
        check(SCROLL_PAD_WIDTH_MIN < SCROLL_PAD_WIDTH_DEFAULT < SCROLL_PAD_WIDTH_MAX,
              "default lies inside the bounds")
    finally:
        app_settings_module.LOCALES_DIR = orig


def _test_live_resize(root):
    print("\n--- B. set_scroll_pad_width ---")
    first = ScrollPad(root, lambda _u: None, text="a")
    gone = ScrollPad(root, lambda _u: None)
    gone.frame.destroy()
    other_root = tk.Tk()
    other_root.withdraw()
    orphan = ScrollPad(other_root, lambda _u: None)  # still referenced, like a tab's pad
    other_root.destroy()
    try:
        set_scroll_pad_width(70)
    except tk.TclError as exc:
        check(False, f"destroyed pads and pads of a destroyed Tk root are skipped ({exc})")
    check(_width(first) == 70, f"an existing pad is resized (got {_width(first)})")
    later = ScrollPad(root, lambda _u: None)
    check(_width(later) == 70, f"a pad built afterwards gets the new width (got {_width(later)})")
    explicit = ScrollPad(root, lambda _u: None, width=12)
    check(_width(explicit) == 12, "an explicit width still wins at construction")
    set_scroll_pad_width(5)
    check(_width(first) == SCROLL_PAD_WIDTH_MIN, "the live value is clamped too")
    set_scroll_pad_width(SCROLL_PAD_WIDTH_DEFAULT)
    check(widgets.SCROLL_PAD_WIDTH == SCROLL_PAD_WIDTH_DEFAULT, "widgets default follows the setting")


def _all_pads(app):
    pads = list(app.settings_tab._scroll_pads) + [app.generation_tab_widget._scroll_pad]
    for name in ("rings_tab_widget", "tree_tab_widget", "sphere_tab_widget"):
        tab = getattr(app, name, None)
        if tab is not None and getattr(tab, "_scroll_pad", None) is not None:
            pads.append(tab._scroll_pad)
    return pads


def _test_settings_tab():
    print("\n--- C. Settings > General > User interface ---")
    import tkinter.messagebox as messagebox
    messagebox.showinfo = lambda *a, **k: None
    messagebox.showerror = lambda *a, **k: None
    import prime_atlas_v2
    sys.argv = ["prime_atlas_v2.py"]
    app = prime_atlas_v2._build_gui()()
    try:
        app.update()
        tab = app.settings_tab
        saved = []
        tab.app_settings.save = lambda: saved.append(1)
        check(tab.T("settings.ui_frame") != "settings.ui_frame", "locale has settings.ui_frame")
        check(tab.T("settings.scroll_pad_width_label") != "settings.scroll_pad_width_label",
              "locale has settings.scroll_pad_width_label")
        var = getattr(tab, "scroll_pad_width_var", None)
        check(var is not None, "General has a scroll-area width field")
        if var is None:
            return
        check(int(var.get()) == tab.app_settings.scroll_pad_width,
              "the field starts at the saved width")
        pads = _all_pads(app)
        check(len(pads) >= 5, f"pads found across the app ({len(pads)})")
        check(all(_width(p) == tab.app_settings.scroll_pad_width for p in pads),
              "every pad is built at the saved width")
        var.set("72")
        tab._on_scroll_pad_width_changed()
        check(tab.app_settings.scroll_pad_width == 72 and saved, "applying saves the width")
        check(all(_width(p) == 72 for p in pads), "applying resizes every pad in the app")
        var.set("abc")
        tab._on_scroll_pad_width_changed()
        check(tab.app_settings.scroll_pad_width == 72 and all(_width(p) == 72 for p in pads),
              "an invalid entry changes nothing")
        check(var.get() == "72", "an invalid entry is reverted in the field")
    finally:
        set_scroll_pad_width(SCROLL_PAD_WIDTH_DEFAULT)
        app.destroy()


def main():
    _test_app_settings()
    root = tk.Tk()
    root.withdraw()
    try:
        _test_live_resize(root)
    finally:
        root.destroy()
    _test_settings_tab()


if __name__ == "__main__":
    main()
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  FAIL: {f}")
        sys.exit(1)
    print("ALL CHECKS PASSED")
