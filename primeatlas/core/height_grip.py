"""
height_grip.py -- HeightGrip, the app's one height control: a drag handle under a terminal,
list, table, multi-line field or chart that sets its height, remembered per place
(layout_memory.py, defaults in layout_const.py). widgets.py re-exports it.
"""
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from . import layout_const, layout_memory


class HeightGrip:
    """A thin drag handle that sets the height of one or more widgets: line-sized ones
    (Text, Listbox, Treeview -- `height` counts lines or rows), stepped by whole lines, or
    charts (Canvas -- `height` in pixels), stepped by layout_const.CHART_STEP_PX. Every
    target changes by the same number of steps from where the drag started, clamped to
    [min_lines, max_lines] (pixels for a chart); on_change (no args) fires once when the
    drag ends.

    `place` names the grip's layout_const.GRIPS entry: default, min and max come from it,
    the height the person set is saved on release and restored when the grip is built
    (layout_memory.py), and reset_layout() puts the default back. A default of None leaves
    the height to the owner until the person drags (`value` stays None).

    `targets` is a widget, a list of widgets, or a no-argument callable returning either
    (for a widget that is destroyed and rebuilt later; the owner calls apply() on the new
    one). The grip lives in `parent`; when `after` is given it is packed right below that
    widget, otherwise the caller packs it with pack()."""

    def __init__(self, parent, targets, *, after=None, min_lines=3, max_lines=200,
                 on_change=None, padx=0, pady=(0, 4), place=None):
        self._targets = targets
        self.min_lines = min_lines
        self.max_lines = max_lines
        self._on_change = on_change
        self._pack_options = {"fill": "x", "padx": padx, "pady": pady}
        self._drag = None
        self.place = place
        self.default = None
        self.value = None
        self.frame = ttk.Frame(parent, height=8, cursor="sb_v_double_arrow")
        line = ttk.Separator(self.frame, orient="horizontal")
        line.place(relx=0.35, rely=0.5, relwidth=0.3)
        for widget in (self.frame, line):
            widget.configure(cursor="sb_v_double_arrow")
            widget.bind("<ButtonPress-1>", self._on_press)
            widget.bind("<B1-Motion>", self._on_drag)
            widget.bind("<ButtonRelease-1>", self._on_release)
        if place is not None:
            self.default, self.min_lines, self.max_lines = layout_const.GRIPS[place]
            self.value = layout_memory.load_int(layout_memory.grip_key(place), self.default,
                                                self.min_lines, self.max_lines)
            self.apply()
            layout_memory.register(self)
        if after is not None:
            self.pack(after=after)

    def pack(self, after=None):
        options = dict(self._pack_options)
        if after is not None:
            options["after"] = after
        self.frame.pack(**options)

    def pack_forget(self):
        self.frame.pack_forget()

    def targets(self):
        targets = self._targets() if callable(self._targets) else self._targets
        if not isinstance(targets, (list, tuple)):
            targets = [targets]
        return [t for t in targets if t is not None and t.winfo_exists()]

    def apply(self):
        """Gives every target the grip's value (nothing while it is None)."""
        if self.value is None:
            return
        for target in self.targets():
            if _height_option(target) != self.value:
                target.configure(height=self.value)

    def reset_layout(self):
        self.value = self.default
        self.apply()
        if self._on_change is not None:
            self._on_change()

    def _steps_in_pixels(self):
        targets = self.targets()
        return bool(targets) and isinstance(targets[0], tk.Canvas)

    def line_height(self):
        """Pixels per step: CHART_STEP_PX for a chart, else the first target's line: the
        Treeview style's row height, or the target font's line spacing."""
        targets = self.targets()
        if not targets:
            return 1
        target = targets[0]
        if isinstance(target, tk.Canvas):
            return layout_const.CHART_STEP_PX
        if isinstance(target, ttk.Treeview):
            style = target.cget("style") or "Treeview"
            try:
                rowheight = int(ttk.Style(target).lookup(style, "rowheight") or 0)
            except (TypeError, ValueError):
                rowheight = 0
            if rowheight > 0:
                return rowheight
            return tkfont.nametofont("TkDefaultFont", root=target).metrics("linespace") + 4
        return max(1, tkfont.Font(root=target, font=target.cget("font")).metrics("linespace"))

    def _on_press(self, event):
        targets = self.targets()
        if targets:
            self._drag = (event.y_root, [_height_option(t) for t in targets],
                          self.line_height(), self._steps_in_pixels())

    def _on_drag(self, event):
        if self._drag is None:
            return
        start_y, start_heights, step, pixels = self._drag
        delta = int((event.y_root - start_y) / step) * (step if pixels else 1)
        for target, height in zip(self.targets(), start_heights):
            height = max(self.min_lines, min(self.max_lines, height + delta))
            if height != _height_option(target):
                target.configure(height=height)

    def _on_release(self, _event):
        if self._drag is None:
            return
        start_heights = self._drag[1]
        self._drag = None
        targets = self.targets()
        if self.place is not None and targets:
            height = _height_option(targets[0])
            if height != start_heights[0]:
                self.value = height
                layout_memory.save(layout_memory.grip_key(self.place), height,
                                   self.default)
        if self._on_change is not None:
            self._on_change()


def _height_option(widget):
    """The widget's `height` option as an int: lines or rows, or pixels for a Canvas (whose
    option can be a screen distance such as Tk's default "7c")."""
    value = widget.cget("height")
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(widget.winfo_pixels(value))
