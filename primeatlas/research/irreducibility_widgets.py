"""
irreducibility_widgets.py -- small widget helpers shared by the Research -> Irreducibility
sub-tabs: a wrapping label packed across its parent, a labelled remembered number field, and
a read-only text area for results.
"""
import tkinter as tk
from tkinter import ttk

from ..core import number_field
from ..core.ui_state import remember
from ..core.wrap_label import WrapLabel


def wrapped_label(parent, padx=0, pady=0, **kw):
    """A WrapLabel packed across parent, left-aligned."""
    label = WrapLabel(parent, **kw)
    label.pack(anchor="w", fill="x", padx=padx, pady=pady)
    return label


def entry(T, purpose, row, label, default, key=None, width=8, textvariable=None,
          on_return=None, fraction=False, words=()):
    """A label and a number field packed left in row, its tip opening with T(purpose);
    remembered under key when given."""
    if label:
        ttk.Label(row, text=label).pack(side="left", padx=(0, 4))
    e = ttk.Entry(row, width=width, textvariable=textvariable)
    number_field.attach(e, T, purpose, fraction=fraction, words=words)
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
