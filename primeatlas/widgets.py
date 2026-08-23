"""
widgets.py -- small, generic tkinter widget helpers with no application-specific state,
shared by more than one tab. Extracted from prime_atlas_v1.py during the refactor
branch's Faza 3 (tab-by-tab backend/UI split, 2026-08-23) when the "Prime numbers" tab
extraction (primeatlas/primes_tab.py) needed FlowRow but the Constellations tab (still
in prime_atlas_v1.py at the time) also uses it -- moving it here instead of duplicating
it into primes_tab.py avoids exactly the kind of copy-paste this whole refactor branch
exists to undo. prime_atlas_v1.py imports it back as `from primeatlas.widgets import
FlowRow as _FlowRow` to keep its own existing call sites unchanged.

This is one of a small number of files in primeatlas/ that import tkinter -- see
settings_tab.py's own docstring for the general "pure logic elsewhere" convention this
package otherwise follows; FlowRow is UI-only by nature (it lays out already-built
widgets), so there is no non-tkinter half to split it into.
"""
from tkinter import ttk


class FlowRow:
    """A button-row container that wraps its children onto additional lines instead of
    running them off the edge of the window. The Prime numbers and Constellations tabs'
    preview-navigation rows (Load preview / Prev / page label / Next / page-goto entry)
    used to use a plain ttk.Frame with every child .pack(side="left")'d onto ONE line --
    on a narrow window (or a narrow detail pane after the split-view divider is dragged),
    the rightmost controls simply ran past the frame's right edge and became invisible/
    unreachable, with no way to get to them short of resizing the whole window. Reported
    via screenshot: page-nav buttons in the Constellations tab cut off outside the app
    window's right edge.

    Children are added via .add(widget, padx_left=...) instead of widget.pack(...); this
    class lays them out itself using place() (which, unlike pack/grid, doesn't force a
    single line or a fixed grid) and re-flows on every <Configure> of its own frame --
    same 'safe to call again on resize' pattern used by the Benchmark tab's own growth-
    chart canvas binding (see primeatlas/benchmark_tab.py's _draw_growth_chart). .frame
    is what the caller packs/grids into its own parent, exactly like a plain ttk.Frame
    would be."""

    ROW_GAP = 4

    def __init__(self, parent):
        self.frame = ttk.Frame(parent)
        self._items = []  # [(widget, padx_left)], in add() order
        self.frame.bind("<Configure>", self._reflow)

    def add(self, widget, padx_left=0):
        self._items.append((widget, padx_left))
        return widget

    def _reflow(self, event):
        width = event.width
        if width <= 1 or not self._items:
            return
        x = 0
        y = 0
        row_height = 0
        for widget, padx_left in self._items:
            widget.update_idletasks()
            w = widget.winfo_reqwidth()
            h = widget.winfo_reqheight()
            if x > 0 and x + padx_left + w > width:
                x = 0
                y += row_height + self.ROW_GAP
                row_height = 0
            widget.place(x=x + padx_left, y=y, width=w, height=h)
            x += padx_left + w
            row_height = max(row_height, h)
        self.frame.configure(height=y + row_height)
