"""
test_settings_scroll.py -- the Settings tab's page-level mouse-wheel handler must leave the
wheel to widgets that scroll themselves.

Artur (2026-10-01): with the pointer over the sympy installer's log (a ScrolledText on
Settings > Updates), scrolling down moved BOTH the log and the whole page; scrolling up
looked right only because the page was already at its top. The page's handler is bound
with bind_all while the pointer is over the page canvas, so it also fires for wheel events
over the log, whose own Text class binding scrolls it at the same time. The Generation tab
solved the same thing with its own exclusion check; the Settings tab now asks
settings_tab.event_over_own_scroller() before scrolling the page.

Usage:
    python unitTests/test_settings_scroll.py
"""
import os
import sys
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from primeatlas.settings import settings_tab  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


class FakeEvent:
    def __init__(self, widget):
        self.widget = widget


def main():
    root = tk.Tk()
    root.withdraw()
    try:
        page = ttk.Frame(root)
        label = ttk.Label(page, text="x")
        log = ScrolledText(page)
        listbox = tk.Listbox(page)
        tree = ttk.Treeview(page)
        entry = ttk.Entry(page)
        over = settings_tab.event_over_own_scroller

        check(over(FakeEvent(log)) is True,
              "wheel over a ScrolledText log (e.g. the sympy installer output) is left to it")
        check(over(FakeEvent(listbox)) is True and over(FakeEvent(tree)) is True,
              "wheel over a Listbox / Treeview is left to it")
        check(over(FakeEvent(label)) is False and over(FakeEvent(page)) is False,
              "wheel over plain page content scrolls the page")
        check(over(FakeEvent(entry)) is False, "an Entry does not scroll itself -> page scrolls")
        check(over(FakeEvent(str(log))) is False and over(FakeEvent(None)) is False,
              "a string/None event.widget (Tk-internal popdowns) never raises")

        with open(os.path.join(_REPO_ROOT, "primeatlas", "settings", "settings_tab.py"),
                  encoding="utf-8") as f:
            src = f.read()
        handler = src[src.find("def _on_mousewheel(event):"):]
        handler = handler[:handler.find("canvas.bind(")]
        check("event_over_own_scroller(event)" in handler,
              "the Settings page's _on_mousewheel consults event_over_own_scroller first")
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
