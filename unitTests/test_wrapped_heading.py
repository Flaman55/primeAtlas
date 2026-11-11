"""A Treeview's own heading row replaced by WrappedHeading (primeatlas/core/wrapped_heading.py).

The tree's built-in headings are hidden; the canvas above it draws one cell per shown column
(#0 first, then displaycolumns) at the tree's column positions and widths, with the text the
tree's heading holds, wrapped to the cell; the canvas is as tall as the most lines need. A
heading or column change on the tree redraws it. Horizontal scrolling moves the cells by the
same pixels as the tree's. A click inside a cell runs the heading's command; a drag on a
cell's right edge sets that column's width (never below MIN_WIDTH) and runs no command.
Windows, real display:
    python unitTests/test_wrapped_heading.py
"""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from primeatlas.core import wrapped_heading  # noqa: E402
from primeatlas.core.theme import palette_for  # noqa: E402

COLUMNS = ("a", "b", "c")


class WrappedHeadingTests(unittest.TestCase):

    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry("300x200+60+60")
        self.clicks = []
        frame = ttk.Frame(self.root)
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=COLUMNS, show="tree headings")
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        hsb.pack(side="bottom", fill="x")
        self.head = wrapped_heading.WrappedHeading(frame, self.tree, palette_for("light"))
        self.tree.configure(xscrollcommand=self.head.follow(hsb.set))
        self.head.pack(side="top", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.heading("#0", text="Floor / run")
        self.tree.column("#0", width=90, stretch=False)
        for c in COLUMNS:
            self.tree.column(c, width=80, stretch=False)
            self.tree.heading(c, text=c.upper(), command=lambda c=c: self.clicks.append(c))
        self.item = self.tree.insert("", "end", text="row", values=("1", "2", "3"))
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def cells(self):
        self.root.update()
        return {c: (x0, x1, lines) for c, x0, x1, lines in self.head.cells()}

    def test_native_headings_hidden(self):
        self.assertNotIn("headings", str(self.tree.cget("show")))

    def test_cells_follow_the_columns(self):
        cells = self.cells()
        self.assertEqual(list(cells), ["#0"] + list(COLUMNS))
        for c in COLUMNS:
            tx = self.tree.bbox(self.item, c)[0]
            x0, x1, lines = cells[c]
            self.assertEqual(x0, tx, f"{c} starts where the tree's column does")
            self.assertEqual(x1 - x0, self.tree.column(c, "width"))
            self.assertEqual(lines, [c.upper()])

    def test_wrap_and_height(self):
        one = self.head.winfo_height()
        from tkinter import font as tkfont
        from primeatlas.core import heading_wrap
        text = "Run n/s without verify"
        two = heading_wrap.min_width(text, tkfont.nametofont("TkHeadingFont").measure)
        self.tree.column("b", width=two + 2 * wrapped_heading.PAD_X)
        self.tree.heading("b", text=text)
        cells = self.cells()
        self.assertEqual(len(cells["b"][2]), 2, cells["b"])
        self.assertGreater(self.head.winfo_height(), one, "taller for two lines")
        self.tree.heading("b", text="B")
        self.cells()
        self.assertEqual(self.head.winfo_height(), one, "back to one line")

    def test_horizontal_scroll(self):
        before = self.cells()["c"][0]
        self.tree.xview_moveto(0.3)
        after = self.cells()["c"][0]
        self.assertEqual(after, self.tree.bbox(self.item, "c")[0])
        self.assertLess(after, before)

    def test_click_and_resize(self):
        x0, x1, _lines = self.cells()["b"]
        y = self.head.winfo_height() // 2
        self.head.event_generate("<ButtonPress-1>", x=(x0 + x1) // 2, y=y)
        self.head.event_generate("<ButtonRelease-1>", x=(x0 + x1) // 2, y=y)
        self.assertEqual(self.clicks, ["b"])
        self.head.event_generate("<ButtonPress-1>", x=x1 - 1, y=y)
        self.head.event_generate("<B1-Motion>", x=x1 + 30, y=y)
        self.head.event_generate("<ButtonRelease-1>", x=x1 + 30, y=y)
        self.assertEqual(self.tree.column("b", "width"), 80 + 31)
        self.assertEqual(self.clicks, ["b"], "a drag runs no command")
        x0, x1, _lines = self.cells()["b"]
        self.head.event_generate("<ButtonPress-1>", x=x1 - 1, y=y)
        self.head.event_generate("<B1-Motion>", x=x0 - 200, y=y)
        self.head.event_generate("<ButtonRelease-1>", x=x0 - 200, y=y)
        self.assertEqual(self.tree.column("b", "width"), wrapped_heading.MIN_WIDTH)


if __name__ == "__main__":
    unittest.main()
