"""
wrap_label.py -- WrapLabel, the app's one static text that wraps to the width it has (a
section's description, a hint, a status line): its wrap width follows the window, a sash
drag and the font scale instead of a fixed number of pixels.

A WrapLabel (through RoomFollower, also used by core/wrapped_check.py) is an element of the
layout coordinator (core/responsive.py), registered on its reference -- the nearest ancestor
whose width does not follow its content: the scrollable page's canvas, a pane of a
panedwindow, or the window -- so a width change of the reference lays it out again.

Its room is measured in its box: the nearest ancestor that its own parent stretches to a
width (packed top/bottom with fill x, or left/right with fill x and expand; gridded sticky
east-west in a column of weight; a notebook tab or a pane), or the reference. A frame on the
way that only fits its content is passed by: its width comes from the label, and reading it
would make the two shrink each other. The room runs from the label's left edge to the box's
right edge, less the box's inner border (taken equal to its left one), the right padding of
every widget on the way, and the siblings packed beside one of them that is packed on the
left side (after it, or before it on the right side). On a scrollable page the room is
measured as with the page's scrollbar shown (ScrollablePage.steady_width()), and never runs
past the reference's right edge.
"""
import tkinter as tk
from tkinter import ttk

from . import responsive

INITIAL_WRAP_PX = 760
"""Wrap width until the first layout; arbitrary."""

MIN_WRAP_PX = 120
"""Narrowest wrap width; arbitrary, about a dozen characters."""

TEXT_INSET_PX = 4
"""Room the label keeps beside its text for ttk's padding; arbitrary."""


def _reference(widget):
    """The nearest of `widget` and its ancestors whose width does not follow its content."""
    w = widget
    while w is not None:
        if isinstance(w, (tk.Canvas, tk.Tk, tk.Toplevel)):
            return w
        if isinstance(w.master, (ttk.Panedwindow, tk.PanedWindow)):
            return w
        w = w.master
    return widget.winfo_toplevel()


def _pads(value):
    """(left, right) of a padx option, given as one number or two."""
    parts = [int(float(p)) for p in str(value).replace("(", " ").replace(")", " ")
             .replace(",", " ").split()]
    return (parts[0], parts[-1]) if parts else (0, 0)


def _manager_info(widget):
    try:
        manager = widget.winfo_manager()
        if manager == "pack":
            return manager, widget.pack_info()
        if manager == "grid":
            return manager, widget.grid_info()
        if manager == "place":
            return manager, widget.place_info()
        return manager, {}
    except tk.TclError:
        return "", {}


def _stretched(widget):
    """True when `widget`'s parent gives it a width that does not follow its content."""
    manager, info = _manager_info(widget)
    if manager in ("notebook", "panedwindow"):
        return True
    if manager == "pack":
        if str(info.get("fill")) not in ("x", "both"):
            return False
        return str(info.get("side")) in ("top", "bottom") or str(info.get("expand")) in (
            "1", "True", "true")
    if manager == "grid":
        sticky = str(info.get("sticky", ""))
        if "e" not in sticky or "w" not in sticky:
            return False
        column, span = int(info.get("column", 0)), int(info.get("columnspan", 1))
        return any(float(widget.master.columnconfigure(c)["weight"]) > 0
                   for c in range(column, column + span))
    if manager == "place":
        return float(info.get("relwidth") or 0) > 0
    return False


def _beside(widget):
    """Width taken by the siblings packed beside `widget`, a left-side one: those packed
    after it on either side and those packed before it on the right side."""
    manager, info = _manager_info(widget)
    if manager != "pack" or str(info.get("side")) != "left":
        return 0
    slaves = widget.master.pack_slaves()
    index = slaves.index(widget)
    taken = 0
    for position, other in enumerate(slaves):
        side = str(other.pack_info().get("side"))
        if (position > index and side in ("left", "right")) or (position < index
                                                                and side == "right"):
            other_info = other.pack_info()
            taken += (other.winfo_reqwidth() + 2 * int(other_info.get("ipadx", 0))
                      + sum(_pads(other_info.get("padx", 0))))
    return taken


class RoomFollower:
    """Calls apply(width) with `widget`'s room (see the module docstring) whenever it
    changes: on a width change of the reference and once `widget` is shown."""

    def __init__(self, widget, apply, inset=0):
        self.widget = widget
        self._apply = apply
        self._inset = inset
        self._reference = _reference(widget.master)
        self._watched = set()
        self.layout_item = responsive.coordinator(widget).add(
            self._reference, self._apply, width=self._room, key=self._measure)
        widget.bind("<Map>", lambda _e: self.layout_item.request(), add="+")

    def _measure(self):
        """(room, box) once `widget` is shown, else None; box is the measured box's left
        edge and width, so a change of either lays the widget out again."""
        w = self.widget
        if not w.winfo_ismapped():
            return None
        taken = 0
        node = w
        while True:
            taken += _pads(_manager_info(node)[1].get("padx", 0))[1] + _beside(node)
            box = node.master
            if box is self._reference or _stretched(box) or box.master is None:
                break
            node = box
        if box is not self._reference and str(box) not in self._watched:
            self._watched.add(str(box))
            self.layout_item.watch(box)  # its width can settle after the layout
        border = node.winfo_rootx() - box.winfo_rootx() - _pads(
            _manager_info(node)[1].get("padx", 0))[0]
        right = box.winfo_rootx() + box.winfo_width() - max(0, border)
        ref = self._reference
        page = getattr(ref, "wheel_target", None)
        ref_width = page.steady_width() if hasattr(page, "steady_width") else ref.winfo_width()
        if hasattr(page, "steady_width"):
            right -= max(0, ref.winfo_width() - ref_width)
        # A box can be wider than the reference for a moment (a page's content before the
        # canvas hands it the window's width); the room never runs past the reference.
        right = min(right, ref.winfo_rootx() + ref_width - max(0, border))
        room = right - taken - w.winfo_rootx() - TEXT_INSET_PX - self._inset
        return max(MIN_WRAP_PX, room), box.winfo_rootx(), box.winfo_width()

    def _room(self):
        measured = self._measure()
        return 0 if measured is None else measured[0]  # 0: laid out once shown (<Map>)


class WrapLabel(ttk.Label):
    """A ttk.Label whose text wraps to its room (see the module docstring); left-justified
    unless `justify` is given. The caller places it as any label."""

    def __init__(self, master, **kw):
        kw.setdefault("wraplength", INITIAL_WRAP_PX)
        kw.setdefault("justify", "left")
        super().__init__(master, **kw)
        self.room = RoomFollower(self, self._wrap)

    def _wrap(self, width):
        if str(self.cget("wraplength")) != str(width):
            self.configure(wraplength=width)
