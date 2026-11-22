"""
wrapped_check.py -- a ttk Checkbutton whose text wraps to the width it has (the rule of
core/wrap_label.py), so a long option label fits a small window and follows resizes and the
font scale.
"""
from tkinter import ttk

from .wrap_label import INITIAL_WRAP_PX, RoomFollower

INDICATOR_PX = 40
"""Room for the check indicator and the padding beside the text; arbitrary."""


def wrapped_checkbutton(parent, style_name, **kw):
    """A Checkbutton in `parent` with its own style `style_name`.TCheckbutton (ttk reads
    wraplength only from a style), its wrap width following its room. The caller places
    it."""
    style = f"{style_name}.TCheckbutton"
    ttk.Style(parent).configure(style, wraplength=INITIAL_WRAP_PX)
    check = ttk.Checkbutton(parent, style=style, **kw)
    check.room = RoomFollower(
        check, lambda width: ttk.Style(parent).configure(style, wraplength=width),
        inset=INDICATOR_PX)
    return check
