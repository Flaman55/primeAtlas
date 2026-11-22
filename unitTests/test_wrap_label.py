"""WrapLabel: a static text that wraps to the width it has, laid out by the coordinator.

  1. on a scrollable page, nested in padded frames, the text wraps and ends inside the page:
     never past its right edge, never narrower than it asks for;
  2. widening the window lets the text use the room (fewer lines), narrowing it again gives
     the same wrap as before (there and back), and a width change repeated in steps ends on
     the same wrap as one jump;
  3. a label to the right of another widget in its row ends inside the page;
  4. a label in a pane of a panedwindow wraps to the pane, not to the whole window, and
     follows a sash drag;
  5. a label hidden while the window changed width wraps to the current width when shown;
  6. a longer text set later still ends inside the page;
  7. at a window narrower than any text the wrap width never drops below MIN_WRAP_PX;
  8. once laid out, an idle window runs no further passes (no layout loop), and nothing is
     logged;
  9. a wrapped Checkbutton (core/wrapped_check.py) wraps by the same rule: inside the page
     at every width, wider when the window is wider;
  10. labels in two side-by-side grid columns of equal weight each wrap inside their own
     column; a label in a frame that only fits its content (not stretched) still wraps to
     the stretched section around it, without shrinking step by step on later passes;
  11. a widget packed to the right of a label (an info marker after it, or a button packed
     on the right side before it) stays whole and shown;
  12. on a scrollable page the wrap is the same whether the page scrolls or not (the
     scrollbar shown or hidden), so a page cannot settle in two states, one wrapped
     narrower and scrolling, one wrapped wider and fitting;
  13. a box wider than the page for a moment (content wider than the window before the page
     takes the window's width) never gives a wrap past the page's right edge.
Windows, real display:
    python unitTests/test_wrap_label.py
"""
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from primeatlas.core import responsive  # noqa: E402
from primeatlas.core.widgets import ScrollablePage  # noqa: E402
from primeatlas.core.wrap_label import MIN_WRAP_PX, WrapLabel  # noqa: E402
from primeatlas.core.wrapped_check import wrapped_checkbutton  # noqa: E402

LONG = ("A long description of what this section does, written to be wider than any window "
        "the app may get, so it has to wrap onto several lines. ") * 3


class _Base(unittest.TestCase):

    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry("900x500+40+40")
        self.page = ScrollablePage(self.root)
        self.warnings = []
        self._log_warning = responsive.log.warning
        responsive.log.warning = lambda *a: self.warnings.append(a)

    def tearDown(self):
        responsive.log.warning = self._log_warning
        self.root.destroy()

    def pump(self):
        end = time.time() + 3 * responsive.DEBOUNCE_MS / 1000
        self.root.update()
        while time.time() < end:
            self.root.update()
            time.sleep(0.01)
        self.root.update()

    def resize(self, width):
        self.root.geometry(f"{width}x500")
        self.pump()

    def right_edge(self):
        return self.page.canvas.winfo_rootx() + self.page.canvas.winfo_width()

    def assert_inside(self, label, edge=None, what=""):
        edge = self.right_edge() if edge is None else edge
        self.assertLessEqual(label.winfo_rootx() + label.winfo_width(), edge,
                             f"{what}: ends inside")
        self.assertLessEqual(label.winfo_reqwidth(), label.winfo_width() + 2,
                             f"{what}: not cut")

    def lines(self, label):
        return label.winfo_reqheight()

    def nested_label(self, text=LONG):
        outer = ttk.LabelFrame(self.page.body, text="section")
        outer.pack(fill="x", padx=10, pady=4)
        inner = ttk.Frame(outer)
        inner.pack(fill="x", padx=6)
        label = WrapLabel(inner, text=text)
        label.pack(anchor="w", padx=6, pady=2)
        return label


class Wrapping(_Base):

    def test_nested_label_wraps_inside_the_page(self):
        label = self.nested_label()
        one_line = ttk.Label(self.root, text="x").winfo_reqheight()
        self.pump()
        for width in (900, 1200, 800, 600):
            self.resize(width)
            self.assert_inside(label, what=f"{width} px")
            self.assertGreater(self.lines(label), one_line, f"{width} px: wraps onto more lines")

    def test_widen_uses_the_room_and_back_restores(self):
        label = self.nested_label()
        self.resize(800)
        narrow = (int(str(label.cget("wraplength"))), self.lines(label))
        self.resize(1300)
        wide = (int(str(label.cget("wraplength"))), self.lines(label))
        self.assertGreater(wide[0], narrow[0], "wraps wider when the window is wider")
        self.assertLess(wide[1], narrow[1], "fewer lines when wider")
        self.resize(800)
        self.assertEqual((int(str(label.cget("wraplength"))), self.lines(label)), narrow,
                         "back at 800 px: the same wrap")
        for width in (1100, 1000, 900, 800):
            self.root.geometry(f"{width}x500")
            self.root.update()
        self.pump()
        self.assertEqual((int(str(label.cget("wraplength"))), self.lines(label)), narrow,
                         "steps end on the same wrap as one jump")

    def test_label_right_of_a_widget_ends_inside(self):
        row = ttk.Frame(self.page.body)
        row.pack(fill="x", padx=8)
        ttk.Button(row, text="A wide button on the left").pack(side="left")
        label = WrapLabel(row, text=LONG)
        label.pack(side="left", padx=(8, 4))
        for width in (900, 700):
            self.resize(width)
            self.assert_inside(label, what=f"{width} px")

    def test_label_in_a_pane_wraps_to_the_pane(self):
        paned = ttk.Panedwindow(self.page.body, orient="horizontal")
        paned.pack(fill="x")
        left, right = ttk.Frame(paned), ttk.Frame(paned)
        paned.add(left, weight=1)
        paned.add(right, weight=1)
        label = WrapLabel(left, text=LONG)
        label.pack(anchor="w", padx=4)
        ttk.Label(right, text="right pane").pack()
        self.pump()
        paned.sashpos(0, 300)
        self.pump()
        self.assert_inside(label, edge=left.winfo_rootx() + left.winfo_width(), what="300")
        paned.sashpos(0, 500)
        self.pump()
        self.assert_inside(label, edge=left.winfo_rootx() + left.winfo_width(), what="500")
        self.assertGreater(int(str(label.cget("wraplength"))), 300, "follows the sash")

    def test_hidden_label_wraps_when_shown(self):
        holder = ttk.Frame(self.page.body)
        label = WrapLabel(holder, text=LONG)
        label.pack(anchor="w", padx=4)
        self.pump()
        self.resize(700)
        holder.pack(fill="x", padx=8)
        self.pump()
        self.assert_inside(label, what="shown after a resize")
        holder.pack_forget()
        self.resize(1200)
        holder.pack(fill="x", padx=8)
        self.pump()
        self.assertGreater(int(str(label.cget("wraplength"))), 900,
                           "shown again at a wider window: wraps wider")

    def test_longer_text_later_stays_inside(self):
        var = tk.StringVar(self.root, "short")
        outer = ttk.Frame(self.page.body)
        outer.pack(fill="x", padx=12)
        label = WrapLabel(outer, textvariable=var)
        label.pack(anchor="w")
        self.resize(600)
        var.set(LONG)
        self.pump()
        self.assert_inside(label, what="longer text")

    def test_wrap_never_below_minimum(self):
        label = self.nested_label()
        self.root.minsize(1, 1)
        self.resize(120)
        self.assertGreaterEqual(int(str(label.cget("wraplength"))), MIN_WRAP_PX)


class Columns(_Base):

    def test_side_by_side_columns_wrap_in_their_column(self):
        cards = ttk.Frame(self.page.body)
        cards.pack(fill="x", padx=10)
        cards.columnconfigure(0, weight=1, uniform="side")
        cards.columnconfigure(1, weight=1, uniform="side")
        labels = []
        for col in (0, 1):
            box = ttk.LabelFrame(cards, text=f"column {col}")
            box.grid(row=0, column=col, sticky="nsew", padx=(0, 6) if col == 0 else (6, 0))
            label = WrapLabel(box, text=LONG)
            label.pack(anchor="w", fill="x", padx=4)
            labels.append((box, label))
        for width in (1300, 900, 700):
            self.resize(width)
            for box, label in labels:
                self.assert_inside(label, edge=box.winfo_rootx() + box.winfo_width(),
                                   what=f"{width} px, {box.cget('text')}")

    def test_unstretched_frame_wraps_to_the_section_and_holds(self):
        section = ttk.LabelFrame(self.page.body, text="section")
        section.pack(fill="x", padx=10)
        tight = ttk.Frame(section)
        tight.pack(anchor="w", padx=4)
        label = WrapLabel(tight, text=LONG)
        label.pack(side="left")
        self.resize(900)
        self.assert_inside(label, edge=section.winfo_rootx() + section.winfo_width(),
                           what="900 px")
        wrap = int(str(label.cget("wraplength")))
        self.assertGreater(wrap, 700, "uses the section's width")
        label.room.layout_item.request()
        self.pump()
        label.room.layout_item.request()
        self.pump()
        self.assertEqual(int(str(label.cget("wraplength"))), wrap, "no shrinking on later passes")

    def test_marker_right_of_the_label_stays_shown(self):
        row = ttk.Frame(self.page.body)
        row.pack(fill="x", padx=10)
        label = WrapLabel(row, text=LONG)
        label.pack(side="left")
        marker = ttk.Label(row, text="(i) more")
        marker.pack(side="left", padx=(4, 0))
        for width in (1300, 800):
            self.resize(width)
            self.assertTrue(marker.winfo_ismapped(), f"{width} px: marker shown")
            self.assertGreaterEqual(marker.winfo_width(), marker.winfo_reqwidth(),
                                    f"{width} px: marker whole")
            self.assert_inside(marker, what=f"{width} px: marker")

    def test_button_packed_right_before_the_label_stays_shown(self):
        header = ttk.Frame(self.page.body)
        header.pack(fill="x", padx=6)
        button = ttk.Button(header, text="Open in a window")
        button.pack(side="right")
        label = WrapLabel(header, text=LONG)
        label.pack(side="left", anchor="w")
        for width in (1300, 800):
            self.resize(width)
            self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth(),
                                    f"{width} px: button whole")
            self.assertLessEqual(label.winfo_rootx() + label.winfo_width(), button.winfo_rootx(),
                                 f"{width} px: label left of the button")
            self.assert_inside(label, what=f"{width} px: label")


class ScrollbarIndependent(_Base):

    def test_wrap_does_not_follow_the_scrollbar(self):
        label = self.nested_label()
        self.resize(900)
        self.assertFalse(self.page.scrolls(), "fits at first")
        wrap = int(str(label.cget("wraplength")))
        spacer = ttk.Frame(self.page.body, height=2000)
        spacer.pack()
        self.pump()
        self.assertTrue(self.page.scrolls(), "scrolls with the spacer")
        self.assertEqual(int(str(label.cget("wraplength"))), wrap, "same wrap while scrolling")
        self.assert_inside(label, what="scrolling")
        spacer.destroy()
        self.pump()
        self.assertFalse(self.page.scrolls())
        self.assertEqual(int(str(label.cget("wraplength"))), wrap, "same wrap fitting again")


class WideBox(_Base):

    def test_box_wider_than_the_page_is_capped_at_the_page(self):
        label = self.nested_label()
        self.resize(900)
        # The page's content for a moment wider than the page, as before the canvas hands
        # it the window's width.
        self.page.canvas.itemconfigure(self.page.window_item, width=5000)
        for _ in range(5):
            self.root.update()
        label.room.layout_item.request()
        for _ in range(5):
            self.root.update()
        page_right = self.page.canvas.winfo_rootx() + self.page.steady_width()
        self.assertLessEqual(label.winfo_rootx() + int(str(label.cget("wraplength"))),
                             page_right, "wrap ends inside the page")


class WrappedCheck(_Base):

    def test_checkbutton_wraps_inside_the_page(self):
        outer = ttk.LabelFrame(self.page.body, text="section")
        outer.pack(fill="x", padx=10)
        check = wrapped_checkbutton(outer, "TestWrap", text=LONG)
        check.pack(anchor="w", padx=4)
        wraps = []
        for width in (1300, 800, 600):
            self.resize(width)
            self.assert_inside(check, what=f"{width} px")
            wraps.append(int(str(ttk.Style(self.root).lookup("TestWrap.TCheckbutton",
                                                               "wraplength"))))
        self.assertGreater(wraps[0], wraps[1], "wider window, wider wrap")


class NoLoop(_Base):

    def test_idle_window_runs_no_more_passes(self):
        labels = [self.nested_label() for _ in range(4)]
        self.resize(850)
        coordinator = responsive.coordinator(self.root)
        passes = coordinator.passes
        self.pump()
        self.pump()
        self.assertEqual(coordinator.passes, passes, "no pass while idle")
        self.assertEqual(self.warnings, [], "nothing logged")
        for label in labels:
            self.assert_inside(label, what="settled")


if __name__ == "__main__":
    unittest.main()
