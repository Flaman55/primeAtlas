"""
font_scale.py -- the app's font scale as a multiple of `tk scaling` (pixels per point), kept
across display changes.

Tk sets `tk scaling` back to the system's value when Windows sends WM_DISPLAYCHANGE (a monitor
woken up, a resolution change) and tells the app nothing, so widgets measured after it come out
smaller. The scale is checked only when the app does something: at the start of a layout pass
(responsive.py), when a window is activated, and on a key or mouse press, which comes before
any window the press builds. Nothing runs while the app is idle. A check that finds `tk scaling`
differing from the value set last takes it as the new base (a real DPI change gives a new one),
sets base * percent again and re-applies the ttk theme and the named fonts, so widgets measured
in between get their sizes back.
"""
import tkinter.font as tkfont
from tkinter import ttk


def apply(root, percent):
    """Multiplies `tk scaling` by percent/100 before any widget is built, so every point-sized
    font (named fonts and explicit ("Consolas", 9) tuples, canvas text included) grows by the
    same factor, and keeps it so (see the module docstring). Pixel sizes (column widths,
    wraplength, paddings) are unaffected. Nothing is set up at 100 %."""
    if percent == 100:
        return
    root._font_scale = {"percent": percent, "set": None}
    _set(root, float(root.tk.call("tk", "scaling")))
    for event in ("<KeyPress>", "<ButtonPress>"):
        root.bind_all(event, lambda _e: check(root), add="+")
    for cls in ("Tk", "Toplevel"):
        root.bind_class(cls, "<Activate>", lambda _e: check(root), add="+")


def check(root):
    """Sets the scale again when `tk scaling` is no longer the value set last."""
    state = getattr(root, "_font_scale", None)
    if state is None or float(root.tk.call("tk", "scaling")) == state["set"]:
        return
    _set(root, float(root.tk.call("tk", "scaling")))
    style = ttk.Style(root)
    style.theme_use(style.theme_use())


def _set(root, base):
    """Sets base * percent; the named fonts re-resolve their point size under it."""
    state = root._font_scale
    root.tk.call("tk", "scaling", base * state["percent"] / 100)
    state["set"] = float(root.tk.call("tk", "scaling"))
    for name in tkfont.names(root):
        named = tkfont.nametofont(name, root=root)
        named.configure(size=named.cget("size"))
