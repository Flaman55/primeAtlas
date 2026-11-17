"""ElidedRadiobutton in a FlowRow (primeatlas/core/elided_choice.py, core/widgets.py).

A radio whose name does not fit the row's width is shortened with an ellipsis, an "i" marker
appears beside it and hovering the name or the marker shows the full name; a name that fits
shows in full with no marker and no tip. In a FlowRow:
  1. a wide row holds every item on one line, in order, with the gaps given to add();
  2. a narrower row wraps only between whole items, every item inside the row's width;
  3. an item wider than the whole row stands alone on its line, shortened to fit;
  4. narrow -> wide -> narrow, repeated, gives the same layout; widening restores full names;
  5. the row's height grows with its lines;
  6. clicking an item selects its value, and the selection survives a reflow.
Windows, real display:
    python unitTests/test_elided_choice.py
"""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from primeatlas.core import elided_choice  # noqa: E402
from primeatlas.core.widgets import FlowRow  # noqa: E402

NAMES = ["Floor only", "Range -- from/to", "Exploration (floor + iterations)",
         "Hybrid (tuple filter)", "primesieve (uint64 range only)",
         "cudasieve (GPU, fast, range >= 2^40 only)",
         "Pseudosquares (native, up to 1.73*10^33)"]
GAP = 16


class ElidedChoiceTests(unittest.TestCase):

    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry("1400x400+40+40")
        self.var = tk.StringVar(self.root, value="0")
        self.host = ttk.Frame(self.root)
        self.host.pack(fill="x")
        self.row = FlowRow(self.host)
        self.row.frame.pack(fill="x")
        self.items = []
        for i, name in enumerate(NAMES):
            item = elided_choice.ElidedRadiobutton(self.row.frame, name, value=str(i),
                                                   variable=self.var)
            self.row.add(item, padx_left=GAP if i else 0)
            self.items.append(item)
        below = ttk.Label(self.host, text="fields below")
        below.pack(anchor="w")
        self.below = below
        self.settle()

    def tearDown(self):
        self.root.destroy()

    def settle(self):
        for _ in range(4):
            self.root.update()

    def resize(self, width):
        self.root.geometry(f"{width}x400")
        self.settle()

    def layout(self):
        return [(i.winfo_x(), i.winfo_y(), i.radio.cget("text"), i.is_elided)
                for i in self.items]

    def assert_inside(self, width):
        for item in self.items:
            right = item.winfo_x() + item.winfo_width()
            self.assertLessEqual(right, self.row.frame.winfo_width(),
                                 f"{item.full_text!r} ends at {right} in a {width} px row")
            self.assertGreaterEqual(item.winfo_x(), 0)

    def test_fitting_name_is_full_with_no_marker_or_tip(self):
        self.resize(2400)
        for item, name in zip(self.items, NAMES):
            self.assertEqual(item.radio.cget("text"), name)
            self.assertFalse(item.is_elided)
            self.assertFalse(item.icon.winfo_ismapped(), f"no marker beside {name!r}")
            self.assertEqual(item.tip_text(), "", f"no tip on {name!r}")

    def test_wide_row_is_one_line_in_order_with_gaps(self):
        self.resize(2400)
        ys = {i.winfo_y() for i in self.items}
        self.assertEqual(len(ys), 1, "one line")
        xs = [i.winfo_x() for i in self.items]
        self.assertEqual(xs, sorted(xs), "add() order left to right")
        for left, right in zip(self.items, self.items[1:]):
            self.assertEqual(right.winfo_x() - (left.winfo_x() + left.winfo_width()), GAP)

    def test_narrow_row_wraps_between_whole_items(self):
        for width in (1000, 800, 600, 500):
            self.resize(width)
            self.assert_inside(width)
            lines = sorted({i.winfo_y() for i in self.items})
            self.assertGreater(len(lines), 1, f"{width} px wraps")
            for item in self.items:
                if item.winfo_width() < self.row.frame.winfo_width():
                    self.assertFalse(item.is_elided, f"{item.full_text!r} fits, kept whole")

    def test_item_wider_than_row_stands_alone_shortened(self):
        self.resize(220)
        self.assert_inside(220)
        long_item = self.items[5]
        self.assertTrue(long_item.is_elided)
        text = long_item.radio.cget("text")
        self.assertTrue(text.endswith("…"), text)
        self.assertTrue(NAMES[5].startswith(text[:-1].rstrip()), text)
        self.assertEqual(long_item.winfo_x(), 0, "alone, at the left edge")
        same_line = [i for i in self.items if i.winfo_y() == long_item.winfo_y()]
        self.assertEqual(same_line, [long_item], "alone on its line")
        self.assertTrue(long_item.icon.winfo_ismapped(), "marker beside a shortened name")
        self.assertEqual(long_item.tip_text(), NAMES[5], "tip shows the full name")
        self.assertEqual(long_item.icon_tip.text(), NAMES[5], "marker's tip shows it too")

    def test_tiny_row_keeps_every_item_inside(self):
        self.resize(60)
        self.assert_inside(60)
        for item in self.items:
            self.assertTrue(item.radio.cget("text"), "some text stays")

    def test_there_and_back_is_stable(self):
        self.resize(2400)
        wide = self.layout()
        self.resize(500)
        narrow = self.layout()
        for _ in range(3):
            self.resize(2400)
            self.assertEqual(self.layout(), wide)
            self.resize(500)
            self.assertEqual(self.layout(), narrow)
        self.resize(220)
        self.resize(2400)
        self.assertEqual(self.layout(), wide, "widening restores full names")
        self.assertFalse(any(i.icon.winfo_ismapped() for i in self.items))

    def test_row_height_grows_and_pushes_what_follows(self):
        self.resize(2400)
        one_line = self.row.frame.winfo_height()
        self.resize(500)
        self.assertGreater(self.row.frame.winfo_height(), one_line)
        bottom = max(i.winfo_y() + i.winfo_height() for i in self.items)
        self.assertLessEqual(bottom, self.row.frame.winfo_height())
        self.assertGreaterEqual(self.below.winfo_y(),
                                self.row.frame.winfo_y() + self.row.frame.winfo_height())

    def test_item_that_grows_is_laid_out_again(self):
        label = ttk.Label(self.row.frame, text="")
        self.row.add(label, padx_left=GAP)
        self.resize(900)
        label.configure(text="a page subtotal written after the layout " * 3)
        self.settle()
        self.assertEqual(label.winfo_width(), label.winfo_reqwidth(), "shown whole")
        self.assertLessEqual(label.winfo_x() + label.winfo_width(), self.row.frame.winfo_width())
        self.assertGreater(label.winfo_y(), self.items[0].winfo_y(), "wrapped below")

    def test_click_selects_and_survives_reflow(self):
        self.resize(2400)
        self.items[6].radio.invoke()
        self.assertEqual(self.var.get(), "6")
        self.resize(220)
        self.assertEqual(self.var.get(), "6")
        self.assertIn("selected", self.items[6].radio.state())
        self.items[2].radio.invoke()
        self.resize(2400)
        self.assertEqual(self.var.get(), "2")
        self.assertIn("selected", self.items[2].radio.state())


if __name__ == "__main__":
    unittest.main()
