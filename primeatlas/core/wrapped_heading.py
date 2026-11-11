"""WrappedHeading -- a Treeview's heading row drawn on a Canvas, so a heading can wrap.

A ttk.Treeview heading shows one line of text, so a long heading over short values forces a wide
column. WrappedHeading hides the tree's own headings and draws one cell per shown column (#0
when the tree shows it, then displaycolumns) at the tree's column positions and widths, with
the text the tree's heading holds, wrapped to the cell (heading_wrap.wrap()); the canvas is as
tall as the most lines need. The tree stays the single source of texts, commands and widths:
tree.heading(), tree.column() and tree.configure() calls that change something redraw it on the
next idle cycle, and follow() wraps the tree's xscrollcommand so the cells scroll with it.

A click inside a cell runs the heading's command; a drag within EDGE_PX of a cell's right edge
sets that column's width (never below MIN_WIDTH) and runs nothing. Colors are the palette's
heading colors (tab_bg, fg, border), fixed at build like the rest of the theme.
"""
import tkinter as tk
from tkinter import font as tkfont

from . import heading_wrap

MIN_WIDTH = 30
EDGE_PX = 4
PAD_X = 4
PAD_Y = 3


class WrappedHeading(tk.Canvas):

    def __init__(self, master, tree, palette):
        self._font = tkfont.nametofont("TkHeadingFont", root=master)
        super().__init__(master, height=self._height(1), highlightthickness=0, borderwidth=0,
                         background=palette["tab_bg"])
        self.tree = tree
        self._palette = palette
        self._cells = []
        self._pending = False
        self._press = None   # ("click", column) or ("resize", column, start x, start width)
        tree.configure(show=tuple(p for p in _show(tree) if p != "headings") or "")
        for name in ("heading", "column", "configure"):
            self._redraw_after(name)
        tree.bind("<Configure>", lambda _e: self.schedule(), add="+")
        self.bind("<Configure>", lambda _e: self.schedule())
        self.bind("<Motion>", self._on_motion)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.schedule()

    def _redraw_after(self, name):
        """Makes the tree's `name` method redraw the heading when a call changes something."""
        original = getattr(self.tree, name)

        def call(*args, **kw):
            result = original(*args, **kw)
            if kw or (args and isinstance(args[-1], dict)):
                self.schedule()
            return result
        setattr(self.tree, name, call)

    def _height(self, lines):
        return lines * self._font.metrics("linespace") + 2 * PAD_Y + 1

    def follow(self, scroll_set):
        """An xscrollcommand for the tree: `scroll_set` (the scrollbar's set) and a redraw."""
        def command(first, last):
            scroll_set(first, last)
            self.refresh()
        return command

    def schedule(self):
        if not self._pending:
            self._pending = True
            self.after_idle(self.refresh)

    def columns(self):
        tree = self.tree
        shown = tree.cget("displaycolumns")
        if tuple(shown) in (("#all",), ()):
            shown = tree.cget("columns")
        lead = ("#0",) if "tree" in _show(tree) else ()
        return lead + tuple(shown)

    def cells(self):
        """[(column, x0, x1, lines)] as last drawn, x in the canvas (= the tree's) pixels."""
        return list(self._cells)

    def refresh(self):
        self._pending = False
        if not self.winfo_exists():
            return
        tree = self.tree
        columns = self.columns()
        widths = [int(tree.column(c, "width")) for c in columns]
        first = float(tree.xview()[0]) if widths else 0.0
        x = _inset(tree, columns) - round(first * sum(widths))
        cells = []
        for column, width in zip(columns, widths):
            text = str(tree.heading(column, "text"))
            lines = heading_wrap.wrap(text, width - 2 * PAD_X, self._font.measure)
            cells.append((column, x, x + width, lines))
            x += width
        self._cells = cells
        height = self._height(max([len(lines) for *_x, lines in cells] + [1]))
        if int(self.cget("height")) != height:
            self.configure(height=height)
        self._draw(height)

    def _draw(self, height):
        p = self._palette
        self.delete("all")
        for _column, x0, x1, lines in self._cells:
            self.create_rectangle(x0, 0, x1 - 1, height - 1, fill=p["tab_bg"],
                                  outline=p["border"])
            self.create_text((x0 + x1) // 2, height // 2, text="\n".join(lines),
                             justify="center", anchor="center", font=self._font,
                             fill=p["fg"])

    def _cell_at(self, x):
        return next((cell for cell in self._cells if cell[1] <= x < cell[2]), None)

    def _edge_at(self, x):
        return next((cell for cell in self._cells if abs(x - cell[2]) <= EDGE_PX), None)

    def _on_motion(self, event):
        self.configure(cursor="sb_h_double_arrow" if self._edge_at(event.x) else "")

    def _on_press(self, event):
        edge = self._edge_at(event.x)
        if edge:
            column = edge[0]
            self._press = ("resize", column, event.x, int(self.tree.column(column, "width")))
            return
        cell = self._cell_at(event.x)
        self._press = ("click", cell[0]) if cell else None

    def _on_drag(self, event):
        if self._press and self._press[0] == "resize":
            _kind, column, start, width = self._press
            self.tree.column(column, width=max(MIN_WIDTH, width + event.x - start))
            self.refresh()

    def _on_release(self, event):
        press, self._press = self._press, None
        if not press or press[0] != "click":
            return
        cell = self._cell_at(event.x)
        if cell and cell[0] == press[1]:
            command = self.tree.heading(press[1], "command")
            if command:
                self.tree.tk.call(command)


def _show(tree):
    show = tree.cget("show")
    return tuple(show.split()) if isinstance(show, str) else tuple(str(p) for p in show)


def _inset(tree, columns):
    """x of the first column's left edge at no scroll: the tree's border, taken from a visible
    row's cell when there is one."""
    first = tree.xview()[0] if columns else 0
    for item in tree.get_children(""):
        box = tree.bbox(item, columns[0]) if columns else ""
        if box:
            widths = sum(int(tree.column(c, "width")) for c in columns)
            return box[0] + round(float(first) * widths)
    return 1
