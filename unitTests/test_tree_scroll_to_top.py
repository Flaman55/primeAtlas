"""StripedTreeview.scroll_to_top() and the Benchmark run table that uses it: a selected row
moves to the top of the view, directly under the column headings, and the rows stay
scrollable above and below it.

scroll_to_top(item): the item becomes the first visible row (the row before it in display
order is scrolled out, the item is in view) for the first row, a middle row, a child of an
open node and a row after a collapsed node; an item in the last screenful too (the last row
included): blank pad rows after the last row let it reach the top, as many as the view needs
and no more (none for a row higher up; the item at the top and the last row in view), never
striped and never selectable (selecting one, alone or with a row, leaves only the row); there
and back (down, up, down) lands each time; an item inside a closed node, a deleted item and an unknown id
leave the view where it is; scrolling with the scrollbar afterwards still moves the view.
On a real BenchmarkTab: selecting a run scrolls it to the top (clicks and arrow keys select
through the same <<TreeviewSelect>>), also one row down; selecting a floor header scrolls
the header to the top with its runs below.
Windows, real display:
    python unitTests/test_tree_scroll_to_top.py
"""
import csv
import os
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation"),
                str(ROOT / "unitTests")]

from primeatlas.core.widgets import StripedTreeview  # noqa: E402


def display_order(tree):
    order, stack = [], list(reversed(tree.get_children("")))
    while stack:
        item = stack.pop()
        order.append(item)
        if tree.item(item, "open"):
            stack.extend(reversed(tree.get_children(item)))
    return order


def at_top(tree, item):
    """True when `item` is in view and the row before it is not."""
    order = display_order(tree)
    index = order.index(item)
    return tree.bbox(item) != "" and (index == 0 or tree.bbox(order[index - 1]) == "")


class ScrollToTopTests(unittest.TestCase):

    def setUp(self):
        self.root = tk.Tk()
        self.tree = StripedTreeview(self.root, show="tree headings", height=8, columns=("a",))
        self.tree.heading("a", text="A")
        self.tree.pack(fill="both", expand=True)
        self.closed = self.tree.insert("", "end", text="closed", open=False)
        self.hidden = self.tree.insert(self.closed, "end", text="hidden")
        self.group = self.tree.insert("", "end", text="group", open=True)
        self.rows = [self.tree.insert(self.group, "end", text=f"row {n}") for n in range(60)]
        self.tail = [self.tree.insert("", "end", text=f"tail {n}") for n in range(3)]
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def scroll(self, item):
        self.tree.scroll_to_top(item)
        self.root.update()

    def test_rows_go_to_top(self):
        for item in (self.closed, self.rows[30], self.group, self.rows[0], self.rows[45],
                     self.rows[10], self.rows[45]):  # first, middle, down, up, down again
            self.scroll(item)
            self.assertTrue(at_top(self.tree, item), self.tree.item(item, "text"))

    def test_after_a_collapsed_node(self):
        self.tree.item(self.closed, open=True)
        self.tree.item(self.closed, open=False)
        self.root.update()
        self.scroll(self.rows[20])
        self.assertTrue(at_top(self.tree, self.rows[20]))

    def pads(self):
        return [i for i in self.tree.get_children("") if i not in
                (self.closed, self.group, *self.tail)]

    def test_last_screenful(self):
        for item in (self.tail[2], self.rows[59], self.tail[0], self.rows[10], self.tail[2]):
            self.scroll(item)
            self.assertTrue(at_top(self.tree, item), self.tree.item(item, "text"))
            if item == self.rows[10]:
                self.assertEqual(self.pads(), [], "a row higher up needs no pad")
            else:
                self.assertNotEqual(self.tree.bbox(self.tail[2]), "", "last row in view")
                self.assertTrue(self.pads(), "pad rows added")
                self.assertEqual(self.tree.bbox(self.pads()[-1]) == "", False,
                                 "no more pad than the view needs")

    def test_pad_rows_inert(self):
        self.scroll(self.tail[2])
        self.root.update()
        pads = self.pads()
        for pad in pads:
            self.assertNotIn("stripe", self.tree.item(pad, "tags"), "never striped")
            self.assertEqual(self.tree.item(pad, "text"), "")
        self.tree.selection_set(pads[0])
        self.root.update()
        self.assertEqual(self.tree.selection(), (), "a pad alone: nothing selected")
        self.tree.selection_set((self.rows[3], pads[1]))
        self.root.update()
        self.assertEqual(self.tree.selection(), (self.rows[3],), "a pad with a row: the row")
        before = self.tree.yview()
        self.tree.scroll_to_top(pads[0])
        self.root.update()
        self.assertEqual(self.tree.yview(), before, "scrolling to a pad does nothing")

    def test_nothing_to_scroll_to(self):
        self.scroll(self.rows[30])
        before = self.tree.yview()
        self.scroll(self.hidden)
        self.assertEqual(self.tree.yview(), before, "inside a closed node")
        self.tree.delete(self.rows[40])
        self.root.update()
        before = self.tree.yview()
        self.tree.scroll_to_top(self.rows[40])
        self.root.update()
        self.assertEqual(self.tree.yview(), before, "deleted")
        self.tree.scroll_to_top("no such item")
        self.root.update()
        self.assertEqual(self.tree.yview(), before, "unknown id")

    def test_still_scrollable(self):
        self.scroll(self.rows[30])
        self.tree.yview_scroll(-5, "units")
        self.root.update()
        self.assertNotEqual(self.tree.bbox(self.rows[25]), "", "rows above reachable")
        self.tree.yview_scroll(10, "units")
        self.root.update()
        self.assertEqual(self.tree.bbox(self.rows[30]), "", "and further down")


class BenchmarkTabTests(unittest.TestCase):

    def test_tab(self):
        import tkinter.messagebox
        tkinter.messagebox.showinfo = lambda *a, **k: None
        from app_sandbox import isolate_app

        rows = [dict(run_timestamp_utc=f"2026-11-10 10:{m:02d}:00 UTC", base_exponent=str(f),
                     engine="pt1", engine_version="pt1.1", numbers_processed="10000000",
                     windows_written="1", target_idx_start=str(m), target_idx_end=str(m),
                     sieve_seconds=str(1 + m / 100), total_seconds=str(2 + m / 100))
                 for f in (28, 29, 30) for m in range(30)]
        tmp = tempfile.mkdtemp(prefix="primeatlas_scroll_to_top_")
        with open(os.path.join(tmp, "benchmark_log.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        prime_atlas_v2, _portal = isolate_app(tmp)
        app = prime_atlas_v2._build_gui()()
        app.update()
        try:
            tab = app.benchmark_tab_widget
            tab.reload_benchmark_log()
            tree = tab.benchmark_tree
            tree.configure(height=6)
            floors = tree.get_children("")
            for node in floors:
                tree.item(node, open=True)
                tab._populate_benchmark_floor_node(node)
            app.update()
            runs = [i for i in tree.get_children(floors[1]) if i in tab._tree_item_rows]
            for run in (runs[12], runs[3], runs[20]):  # down, up, down
                tree.selection_set(run)
                app.update()
                self.assertTrue(at_top(tree, run), tree.item(run, "text"))
            tree.selection_set(runs[21])  # what an arrow key does: one row down
            app.update()
            self.assertTrue(at_top(tree, runs[21]), "one row down")
            tree.selection_set(floors[2])
            app.update()
            self.assertTrue(at_top(tree, floors[2]), "floor header")
            last = [i for i in tree.get_children(floors[2]) if i in tab._tree_item_rows][-1]
            tree.selection_set(last)
            app.update()
            self.assertTrue(at_top(tree, last), "the last run of the last floor")
            tab.reload_benchmark_log()
            app.update()
            self.assertEqual(len(tree.get_children("")), 3, "a reload drops the pad rows")
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
