"""The Benchmark run table's heading row and column widths (primeatlas/benchmark/
benchmark_table_layout.py, core/wrapped_heading.py, core/heading_wrap.py).

The tree's own headings are hidden; a WrappedHeading above it draws #0, the copy box column and
the table's columns, in that order. Each column is as wide as its widest value among the runs
the filter keeps (the floor's summary in s/window, the box glyphs in the copy column), or as its
heading on two lines, whichever is wider, plus CELL_PAD; so no heading takes more than two
lines, and a heading longer than its values (run n/s without the verification) is narrower than
on one line. #0 fits the floor labels and the indented run labels. A filter change fits the
widths again. A click on the copy column's heading cell marks every run.
Windows, real display:
    python unitTests/test_benchmark_table_layout.py
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation"),
                str(ROOT / "unitTests")]

from primeatlas.benchmark import benchmark_table_layout as layout  # noqa: E402
from primeatlas.benchmark import table_columns, table_copy  # noqa: E402
import test_benchmark_chart_points as chart_points_tests  # noqa: E402

# total_seconds gives each floor an s/window summary.
ROWS = [dict(r, total_seconds=str(100 + i)) for i, r in enumerate(
    chart_points_tests.ROWS + [chart_points_tests._row(29, 10 ** 10, 2000.0, version="v7.2",
                                                       ts="h")])]


class LayoutTests(unittest.TestCase):

    def setUp(self):
        from primeatlas.core import ui_state_dynamic
        from primeatlas.core.ui_state_store import UiStateStore
        self._saved_store = ui_state_dynamic.STORE
        ui_state_dynamic.STORE = UiStateStore(None)

    def tearDown(self):
        from primeatlas.core import ui_state_dynamic
        ui_state_dynamic.STORE = self._saved_store

    def check_widths(self, tab, rows):
        from tkinter import font as tkfont
        tree = tab.benchmark_tree
        cell = tkfont.nametofont("TkDefaultFont").measure
        heading = tkfont.nametofont("TkHeadingFont").measure
        for column in table_columns.TREE_COLUMNS:
            width = int(tree.column(column, "width"))
            texts = [table_columns.shown(r, column, tab.T) for r in rows]
            if column == "seconds_per_window":
                texts += layout.floor_summaries(rows, tab.T)
            widest = max(map(cell, texts))
            self.assertGreaterEqual(width, widest + layout.CELL_PAD, column)
            title = tab.T(table_columns.header_key(column))
            self.assertLessEqual(width, max(widest, heading(title)) + layout.CELL_PAD,
                                 f"{column}: no wider than needed")
        for _c, _x0, _x1, lines in tab.benchmark_heading.cells():
            self.assertLessEqual(len(lines), 2, lines)
        return {c: int(tree.column(c, "width")) for c in table_columns.TREE_COLUMNS}

    def test_0_style_lookups_left_as_text(self):
        """Reading the tree's indent and indicator must not turn the shared Tcl values into
        lists: other tabs (Primes) read them with ttk.Style().lookup() and expect text. Runs
        first (unittest sorts by name): only the process's first Tk hands out the shared
        pixel objects that showed it."""
        import tkinter as tk
        from tkinter import ttk
        root = tk.Tk()
        try:
            style = ttk.Style(root)
            style.theme_use("clam")   # the app's theme
            tree = ttk.Treeview(root)  # drawing it gives the values their pixel type
            node = tree.insert("", "end", text="a", open=True)
            tree.insert(node, "end", text="b")
            tree.pack()
            root.update()
            self.assertEqual(type(root.tk.call("ttk::style", "lookup", "Treeview", "-indent"))
                             .__name__, "Tcl_Obj", "the case that broke: a pixel object")
            for element, option, default in (("Treeview", "indent", "20"),
                                             ("Treeview.Item", "indicatorsize", "12"),
                                             ("Treeview.Item", "indicatormargins", "2 2 4 2")):
                pixels = layout._style_pixels(tree, element, option, default)
                self.assertTrue(pixels and all(p > 0 for p in pixels), (option, pixels))
                value = style.lookup(element, option)
                if len(default.split()) == 1:  # one distance; the margins are a list anyway
                    self.assertNotIsInstance(value, tuple, f"{element} {option}: {value!r}")
            root.winfo_fpixels(str(style.lookup("Treeview", "indent")))
        finally:
            root.destroy()

    def test_layout(self):
        def body(tab, root, points):
            from tkinter import font as tkfont
            tree, head = tab.benchmark_tree, tab.benchmark_heading
            self.assertNotIn("headings", str(tree.cget("show")))
            root.update()
            self.assertEqual([c for c, *_rest in head.cells()],
                             ["#0", table_copy.CHECK_COLUMN] + list(table_columns.TREE_COLUMNS))
            self.check_widths(tab, ROWS)
            title = tab.T(table_columns.header_key("run_nps_unverified"))
            one_line = tkfont.nametofont("TkHeadingFont").measure(title)
            self.assertLess(int(tree.column("run_nps_unverified", "width")),
                            one_line + layout.CELL_PAD, "a long heading over short values")
            lines = {c: lines for c, *_x, lines in head.cells()}
            self.assertEqual(len(lines["run_nps_unverified"]), 2)
            summaries = layout.floor_summaries(ROWS, tab.T)
            self.assertEqual(len(summaries), 2, "a summary per floor with windows (27 has none)")
            self.assertGreaterEqual(int(tree.column("seconds_per_window", "width")),
                                    max(map(tkfont.nametofont("TkDefaultFont").measure,
                                            summaries)), "the floor summaries fit")
            label = tab.T("bench.floor_measurements", base_exponent=29, count=4)
            self.assertGreaterEqual(int(tree.column("#0", "width")),
                                    tkfont.nametofont("TkDefaultFont").measure(label),
                                    "#0 fits the floor labels")
            tab._set_filter({"floor": {"27"}})
            root.update()
            self.check_widths(tab, [r for r in ROWS if r["base_exponent"] == "27"])
            tab._set_filter({})
            root.update()
            x0, x1, _lines = next(c[1:] for c in head.cells()
                                  if c[0] == table_copy.CHECK_COLUMN)
            y = head.winfo_height() // 2
            head.event_generate("<ButtonPress-1>", x=(x0 + x1) // 2, y=y)
            head.event_generate("<ButtonRelease-1>", x=(x0 + x1) // 2, y=y)
            self.assertEqual(len(tab._copy_marks), len(ROWS), "heading click marks all")
        chart_points_tests.TabTests._tab(self, ROWS, body)


if __name__ == "__main__":
    unittest.main()
