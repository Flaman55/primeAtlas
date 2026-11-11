"""InfoTip's popup stays inside the app window (primeatlas/core/info_tip.py).

The popup sits OFFSET_PX right of and below its marker when it fits; past the window's right
edge it moves left until its right edge meets the window's; past the bottom it goes above the
marker; wider than the window, it starts at the window's left edge. Every corner of the window
is tried, short and long texts.
Windows, real display:
    python unitTests/test_info_tip.py
"""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from primeatlas.core import info_tip  # noqa: E402

LONG = " ".join(["a long tip line that wraps"] * 40)


class InfoTipTests(unittest.TestCase):

    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry("600x400+80+80")
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def tip_at(self, text, **place):
        frame = ttk.Frame(self.root)
        frame.place(**place)
        tip = info_tip.InfoTip(frame, text)
        tip.label.pack()
        self.root.update()
        tip.show()
        self.root.update()
        popup = tip.popup
        box = (popup.winfo_rootx(), popup.winfo_rooty(), popup.winfo_width(),
               popup.winfo_height())
        label = tip.label
        marker = (label.winfo_rootx(), label.winfo_rooty(), label.winfo_height())
        tip.hide()
        frame.destroy()
        return box, marker

    def window(self):
        r = self.root
        return r.winfo_rootx(), r.winfo_rooty(), r.winfo_width(), r.winfo_height()

    def assert_inside(self, box, name):
        wx, wy, ww, wh = self.window()
        x, y, w, h = box
        self.assertGreaterEqual(x, wx, f"{name}: left")
        self.assertGreaterEqual(y, wy, f"{name}: top")
        self.assertLessEqual(x + w, wx + ww, f"{name}: right")
        self.assertLessEqual(y + h, wy + wh, f"{name}: bottom")

    def test_fits_next_to_the_marker(self):
        box, (lx, ly, _lh) = self.tip_at("short", relx=0.0, rely=0.0, x=10, y=10)
        self.assertEqual(box[:2], (lx + info_tip.OFFSET_PX, ly + info_tip.OFFSET_PX))

    def test_every_corner(self):
        for name, place in (("top left", dict(relx=0.0, rely=0.0)),
                            ("top right", dict(relx=1.0, rely=0.0, anchor="ne")),
                            ("bottom left", dict(relx=0.0, rely=1.0, anchor="sw")),
                            ("bottom right", dict(relx=1.0, rely=1.0, anchor="se"))):
            for text in ("short", "a medium tip " * 8):
                box, _label = self.tip_at(text, **place)
                self.assert_inside(box, f"{name}, {len(text)} chars")

    def test_right_edge_moves_left(self):
        box, (lx, ly, _lh) = self.tip_at("a medium tip " * 8, relx=1.0, rely=0.0, anchor="ne")
        wx, _wy, ww, _wh = self.window()
        self.assertEqual(box[0] + box[2], wx + ww, "right edge on the window's")
        self.assertEqual(box[1], ly + info_tip.OFFSET_PX, "height unchanged")

    def test_bottom_goes_above(self):
        box, (_lx, ly, _lh) = self.tip_at("a medium tip " * 8, relx=0.0, rely=1.0, anchor="sw")
        self.assertLessEqual(box[1] + box[3], ly, "above the marker")

    def test_wider_than_the_window(self):
        self.root.geometry("200x400+80+80")
        self.root.update()
        box, _label = self.tip_at(LONG, relx=1.0, rely=0.0, anchor="ne")
        self.assertEqual(box[0], self.window()[0], "starts at the window's left edge")


if __name__ == "__main__":
    unittest.main()
