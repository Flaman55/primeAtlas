"""
irreducibility_widgets.py -- small widget helpers shared by the Research -> Irreducibility
sub-tabs: a label that wraps at its parent's width, a labelled remembered entry, and a
read-only text area for results.
"""
import tkinter as tk
from tkinter import ttk

from ..core.ui_state import remember


def wrapped_label(parent, padx=0, pady=0, **kw):
    """A left-aligned label packed across parent that wraps at the parent's current width,
    so it follows window resizes and the font scale."""
    label = ttk.Label(parent, justify="left", **kw)
    label.pack(anchor="w", fill="x", padx=padx, pady=pady)
    parent.bind("<Configure>",
                lambda e: label.configure(wraplength=max(e.width - 2 * padx - 8, 200)), add="+")
    return label


def entry(row, label, default, key=None, width=8, textvariable=None, on_return=None):
    """A label and an entry packed left in row; remembered under key when given."""
    if label:
        ttk.Label(row, text=label).pack(side="left", padx=(0, 4))
    e = ttk.Entry(row, width=width, textvariable=textvariable)
    if textvariable is None:
        e.insert(0, default)
    e.pack(side="left", padx=(0, 12))
    if key:
        remember(key, e)
    if on_return:
        e.bind("<Return>", lambda _e: on_return())
    return e


class OutputText(tk.Text):
    """Read-only result area. write(text, tag) appends; clear() empties. Tags: heading,
    ok, err, quiet."""

    def __init__(self, parent, palette, height=14):
        super().__init__(parent, height=height, wrap="word", background=palette["console_bg"],
                         foreground=palette["console_fg"], relief="flat",
                         highlightthickness=1, highlightbackground=palette["border"])
        self.tag_configure("heading", font=("TkDefaultFont", 10, "bold"))
        self.tag_configure("ok", foreground="#2ca02c")
        self.tag_configure("err", foreground="#c0392b")
        self.tag_configure("quiet", foreground=palette["hint_fg"])
        self.configure(state="disabled")

    def clear(self):
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.configure(state="disabled")

    def write(self, text, tag=None):
        self.configure(state="normal")
        self.insert("end", text, (tag,) if tag else ())
        self.configure(state="disabled")

    def text(self):
        return self.get("1.0", "end")
