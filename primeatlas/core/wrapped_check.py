"""
wrapped_check.py -- a ttk Checkbutton whose text wraps at its parent's width, so a long
option label fits a small window and follows resizes and the font scale.
"""
from tkinter import ttk

INITIAL_WRAP_PX = 600
"""Wrap width until the parent is first laid out; arbitrary."""

MIN_WRAP_PX = 200
"""Narrowest wrap width; arbitrary."""

INDICATOR_PX = 40
"""Room for the check indicator and the padding beside the text; arbitrary."""


def wrapped_checkbutton(parent, style_name, **kw):
    """A Checkbutton in `parent` with its own style `style_name`.TCheckbutton (ttk reads
    wraplength only from a style), its wrap width following the parent's width. The caller
    places it."""
    style = f"{style_name}.TCheckbutton"
    ttk.Style(parent).configure(style, wraplength=INITIAL_WRAP_PX)
    check = ttk.Checkbutton(parent, style=style, **kw)
    parent.bind("<Configure>", lambda e: ttk.Style(parent).configure(
        style, wraplength=max(e.width - INDICATOR_PX, MIN_WRAP_PX)), add="+")
    return check
