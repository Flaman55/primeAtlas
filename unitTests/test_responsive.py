"""The layout coordinator (primeatlas/core/responsive.py) and FlowRow on it (core/widgets.py).

Model: one coordinator per window lays registered elements out top-down (outer before inner);
an element gets the width it lays out for, lays itself out once per pass and is marked laid
out with that width and its content sizes. Checks:
  1. order and no self-layout: in one pass outer elements lay out before inner ones; a
     <Configure> of an element never lays it out on the spot;
  2. container width never from content: a row's own height change (wrapping) and a
     height-only change of its container start no layout;
  3. triggers: a resize, however many steps (dragging the window edge), gives one layout
     once the steps stop; an element not shown (a tab not selected) is laid out when it
     first shows, and showing it again at the same width lays nothing out; an explicit
     request lays out only when the width or a content size changed;
  4/10. round limit: an element that asks for another layout of itself (or of an element
     not deeper than the last round's) in the same pass is stopped and logged; a chain of
     deeper requests stops at MAX_ROUNDS and is logged; after either the window still
     responds and later passes work;
  5. width classes from the window's width, thresholds in one place; apply_min_width()
     keeps the window from being made narrower than MIN_WINDOW_WIDTH (the screen's width
     when that is less), its minimum height unchanged;
  6. FlowRow on the coordinator: wraps whole items, a line starts at the left edge (its gap
     dropped), an item wider than the row is shortened by fit_width(); a row given a width
     callable lays out for that width, not its frame's;
  11. keep_sash_share(): a two-pane panedwindow keeps the first pane's share of the width
     across resizes, the second pane never under its minimum, so narrow -> wide gives the
     starting layout back; a sash drag sets the share (clamped to the minimum).
Windows, real display:
    python unitTests/test_responsive.py
"""
import logging
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from primeatlas.core import responsive  # noqa: E402
from primeatlas.core.widgets import FlowRow  # noqa: E402


class _Records(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


class _Base(unittest.TestCase):

    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry("900x400+40+40")
        self.records = _Records()
        responsive.log.addHandler(self.records)
        self.coordinator = responsive.coordinator(self.root)

    def tearDown(self):
        responsive.log.removeHandler(self.records)
        self.root.destroy()

    def pump(self, ms=None):
        """Runs the event loop until the debounce delay (or `ms`) has passed twice."""
        end = time.time() + 2 * (ms if ms is not None else responsive.DEBOUNCE_MS) / 1000
        self.root.update()
        while time.time() < end:
            self.root.update()
            time.sleep(0.01)
        self.root.update()

    def resize(self, width, height=400):
        self.root.geometry(f"{width}x{height}")
        self.pump()

    def element(self, parent, calls, name, **pack):
        frame = ttk.Frame(parent, height=20)
        frame.pack(fill="x", **pack)

        def layout(width):
            calls.append((name, width))
        item = self.coordinator.add(frame, layout)
        return frame, item


class OrderAndTriggers(_Base):

    def test_outer_lays_out_before_inner(self):
        calls = []
        outer, outer_item = self.element(self.root, calls, "outer")
        inner, inner_item = self.element(outer, calls, "inner")
        self.pump()
        self.assertEqual([c[0] for c in calls], ["outer", "inner"])
        self.assertGreater(inner_item.depth, outer_item.depth)
        calls.clear()
        inner_item.request()
        outer_item.request()
        self.root.geometry("700x400")
        self.pump()
        self.assertEqual([c[0] for c in calls], ["outer", "inner"], "outer first again")

    def test_configure_never_lays_out_on_the_spot(self):
        calls = []
        self.element(self.root, calls, "row")
        self.pump()
        calls.clear()
        self.root.geometry("600x400")
        self.root.update_idletasks()
        self.root.update_idletasks()
        self.assertEqual(calls, [], "no layout inside the resize itself")
        self.pump()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 600)

    def test_drag_gives_one_layout_after_it_stops(self):
        calls = []
        self.element(self.root, calls, "row")
        self.pump()
        calls.clear()
        for width in range(900, 600, -15):
            self.root.geometry(f"{width}x400")
            self.root.update()
        self.pump()
        self.assertEqual(len(calls), 1, f"one layout after the drag (got {calls})")
        self.assertEqual(calls[0][1], self.root.winfo_width())

    def test_height_only_change_lays_nothing_out(self):
        calls = []
        self.element(self.root, calls, "row")
        self.pump()
        calls.clear()
        self.resize(900, 300)
        self.resize(900, 500)
        self.assertEqual(calls, [])

    def test_no_change_no_pass(self):
        calls = []
        _frame, item = self.element(self.root, calls, "row")
        self.pump()
        calls.clear()
        item.request()
        item.request()
        self.pump()
        self.assertEqual(calls, [], "same width, same content")
        self.resize(900)
        self.assertEqual(calls, [], "same window size")

    def test_explicit_request_lays_out_on_a_content_change(self):
        calls = []
        sizes = [1]
        frame = ttk.Frame(self.root, height=20)
        frame.pack(fill="x")
        item = self.coordinator.add(frame, lambda w: calls.append(w), key=lambda: tuple(sizes))
        self.pump()
        calls.clear()
        sizes.append(2)
        item.request()
        self.pump()
        self.assertEqual(len(calls), 1)

    def test_hidden_element_waits_until_shown(self):
        calls = []
        book = ttk.Notebook(self.root)
        book.pack(fill="both", expand=True)
        first = ttk.Frame(book)
        second = ttk.Frame(book)
        book.add(first, text="one")
        book.add(second, text="two")
        self.element(first, calls, "first")
        self.element(second, calls, "second")
        self.pump()
        self.assertEqual([c[0] for c in calls], ["first"], "the hidden tab waits")
        book.select(second)
        self.pump()
        self.assertEqual([c[0] for c in calls], ["first", "second"], "laid out when shown")
        for tab in (first, second, first, second):
            book.select(tab)
            self.pump()
        self.assertEqual(len(calls), 2, "showing again at the same width lays nothing out")
        book.select(first)
        self.resize(700)
        book.select(second)
        self.pump()
        self.assertEqual([c[0] for c in calls][-2:], ["first", "second"],
                         "a tab shown at a new width is laid out again")

    def test_destroyed_element_is_dropped(self):
        calls = []
        frame, item = self.element(self.root, calls, "row")
        self.pump()
        item.request()
        frame.destroy()
        self.pump()
        self.resize(700)
        self.assertEqual(len(calls), 1)


class RoundLimit(_Base):

    def test_element_asking_for_itself_is_stopped_and_logged(self):
        calls = []
        frame = ttk.Frame(self.root, height=20)
        frame.pack(fill="x")
        holder = {}

        def layout(width):
            calls.append(width)
            frame.configure(height=20 + len(calls))
            holder["item"].request()
        holder["item"] = self.coordinator.add(frame, layout, key=lambda: (len(calls),))
        self.pump()
        self.assertEqual(len(calls), 1, "laid out once in the pass")
        self.assertTrue(any(str(frame) in m for m in self.records.messages),
                        f"the looping element is named in the log ({self.records.messages})")
        self.root.update()
        self.assertTrue(self.root.winfo_exists(), "the window still responds")

    def test_deeper_chain_stops_at_max_rounds(self):
        calls = []
        parent = self.root
        frames = []
        for _ in range(responsive.MAX_ROUNDS + 5):
            parent = ttk.Frame(parent, height=20)
            parent.pack(fill="x")
            frames.append(parent)
        items = []

        def make(i):
            def layout(width):
                calls.append(i)
                if i + 1 < len(items):
                    items[i + 1].request()
            return layout
        for i, frame in enumerate(frames):
            items.append(self.coordinator.add(frame, make(i), key=lambda i=i: (i,)))
        self.pump()
        for item in items:
            item.last = None
        calls.clear()
        self.records.messages.clear()
        items[0].request()
        self.pump()
        self.assertEqual(calls, list(range(responsive.MAX_ROUNDS)),
                         "one element per round, MAX_ROUNDS rounds")
        self.assertTrue(self.records.messages, "the limit is logged")
        # Later passes still work.
        calls.clear()
        items[0].last = None
        self.coordinator.add(ttk.Frame(self.root), lambda w: calls.append("new"))
        items[0].request()
        self.pump()
        self.assertTrue(calls, "a later pass runs")

    def test_shallower_request_in_a_later_round_is_refused(self):
        calls = []
        outer = ttk.Frame(self.root, height=20)
        outer.pack(fill="x")
        inner = ttk.Frame(outer, height=20)
        inner.pack(fill="x")
        items = {}
        count = {"n": 0}

        def outer_layout(width):
            calls.append("outer")
            count["n"] += 1
            items["inner"].request()

        def inner_layout(width):
            calls.append("inner")
            count["n"] += 1
            items["outer"].request()
        items["outer"] = self.coordinator.add(outer, outer_layout, key=lambda: (count["n"],))
        items["inner"] = self.coordinator.add(inner, inner_layout, key=lambda: (count["n"],))
        self.pump()
        self.assertEqual(calls, ["outer", "inner"])
        self.assertTrue(any(str(outer) in m for m in self.records.messages))


class SashShare(_Base):
    """keep_sash_share(): a two-pane panedwindow keeps the first pane's share of its width
    across window resizes (the second pane never under its minimum), so narrow -> wide gives
    the starting layout back; a sash drag sets the share."""

    def make(self, share=1 / 3, minimum=300):
        from primeatlas.core.widgets import keep_sash_share
        paned = ttk.Panedwindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True)
        first, second = ttk.Frame(paned), ttk.Frame(paned)
        paned.add(first, weight=1)
        paned.add(second, weight=2)
        keep_sash_share(paned, share, minimum)
        return paned

    def test_share_is_kept_across_resizes(self):
        paned = self.make()
        self.resize(1200)
        start = paned.sashpos(0)
        self.assertAlmostEqual(start, paned.winfo_width() / 3, delta=8)
        self.resize(900)
        self.assertAlmostEqual(paned.sashpos(0), paned.winfo_width() / 3, delta=8)
        self.resize(400)
        self.assertLessEqual(paned.sashpos(0), paned.winfo_width() - 300 + 8,
                             "the second pane keeps its minimum")
        self.resize(1200)
        self.assertEqual(paned.sashpos(0), start, "back to the starting layout")

    def test_drag_sets_the_share(self):
        paned = self.make()
        self.resize(1200)
        paned.sashpos(0, 600)
        paned.event_generate("<ButtonRelease-1>", x=600, y=5)
        self.pump()
        self.assertAlmostEqual(paned.sashpos(0), 600, delta=8, msg="the drag stays")
        self.resize(800)
        self.assertAlmostEqual(paned.sashpos(0), paned.winfo_width() / 2, delta=8,
                               msg="half the width after the drag to half")
        self.resize(1200)
        self.assertAlmostEqual(paned.sashpos(0), 600, delta=8)

    def test_drag_past_the_minimum_is_clamped(self):
        paned = self.make()
        self.resize(1200)
        paned.sashpos(0, 1150)
        paned.event_generate("<ButtonRelease-1>", x=1150, y=5)
        self.pump()
        self.assertLessEqual(paned.sashpos(0), paned.winfo_width() - 300 + 8)
        clamped = paned.sashpos(0)
        self.resize(900)
        self.resize(1200)
        self.assertAlmostEqual(paned.sashpos(0), clamped, delta=8)


class MinWidth(_Base):

    def test_window_cannot_be_narrower_than_the_minimum(self):
        self.root.minsize(1, 300)
        responsive.apply_min_width(self.root)
        expected = min(responsive.MIN_WINDOW_WIDTH, self.root.winfo_screenwidth())
        self.assertEqual(self.root.minsize(), (expected, 300), "height minimum unchanged")
        self.resize(600)
        self.assertGreaterEqual(self.root.winfo_width(), expected)
        self.resize(expected + 200)
        self.assertEqual(self.root.winfo_width(), expected + 200, "wider stays free")

    def test_minimum_is_the_verified_width(self):
        self.assertEqual(responsive.MIN_WINDOW_WIDTH, responsive.MEDIUM_MIN)


class WidthClasses(unittest.TestCase):

    def test_thresholds(self):
        self.assertEqual(responsive.WIDE_MIN, 1600)
        self.assertEqual(responsive.MEDIUM_MIN, 1280)
        for width, expected in ((3840, "wide"), (1600, "wide"), (1599, "medium"),
                                (1280, "medium"), (1279, "narrow"), (800, "narrow"),
                                (0, "narrow")):
            self.assertEqual(responsive.width_class(width), expected, width)


class FlowRowOnCoordinator(_Base):

    def make_row(self, count=6, width=None):
        row = FlowRow(self.root, width=width)
        row.frame.pack(fill="x")
        buttons = []
        for i in range(count):
            button = ttk.Button(row.frame, text=f"Button number {i}")
            row.add(button, padx_left=12 if i else 0)
            buttons.append(button)
        below = ttk.Label(self.root, text="below")
        below.pack(anchor="w")
        return row, buttons, below

    def test_wraps_whole_items_line_starts_at_left_edge(self):
        row, buttons, below = self.make_row()
        self.resize(2000)
        self.assertEqual(len({b.winfo_y() for b in buttons}), 1)
        one_line = row.frame.winfo_height()
        self.resize(400)
        lines = sorted({b.winfo_y() for b in buttons})
        self.assertGreater(len(lines), 1)
        for y in lines:
            first = min((b for b in buttons if b.winfo_y() == y), key=lambda b: b.winfo_x())
            self.assertEqual(first.winfo_x(), 0, "a line starts at the left edge")
        for b in buttons:
            self.assertLessEqual(b.winfo_x() + b.winfo_width(), row.frame.winfo_width())
            self.assertEqual(b.winfo_width(), b.winfo_reqwidth(), "whole")
        self.assertGreater(row.frame.winfo_height(), one_line, "the row grows")
        self.assertGreaterEqual(below.winfo_y(), row.frame.winfo_y() + row.frame.winfo_height())

    def test_wrap_starts_no_second_layout(self):
        row, _buttons, _below = self.make_row()
        self.pump()
        count = {"n": 0}
        original = row._place

        def counting(width):
            count["n"] += 1
            original(width)
        row.layout_item.layout = counting
        self.resize(400)
        self.resize(400, 500)
        self.assertEqual(count["n"], 1, "the row's height change lays nothing out again")

    def test_there_and_back_is_stable(self):
        row, buttons, _below = self.make_row()
        self.resize(2000)
        wide = [(b.winfo_x(), b.winfo_y()) for b in buttons]
        self.resize(400)
        narrow = [(b.winfo_x(), b.winfo_y()) for b in buttons]
        for _ in range(3):
            self.resize(2000)
            self.assertEqual([(b.winfo_x(), b.winfo_y()) for b in buttons], wide)
            self.resize(400)
            self.assertEqual([(b.winfo_x(), b.winfo_y()) for b in buttons], narrow)

    def test_width_callable_wins_over_the_frame(self):
        room = {"w": 2000}
        row, buttons, _below = self.make_row(width=lambda: room["w"])
        self.resize(500)
        self.assertEqual(len({b.winfo_y() for b in buttons}), 1, "laid out for 2000 px")
        room["w"] = 300
        row.relayout()
        self.pump()
        self.assertGreater(len({b.winfo_y() for b in buttons}), 1, "laid out for 300 px")

    def test_grown_item_is_laid_out_on_relayout(self):
        row, buttons, _below = self.make_row(count=2)
        label = ttk.Label(row.frame, text="")
        row.add(label, padx_left=12)
        self.resize(600)
        label.configure(text="a subtotal written after the layout " * 3)
        row.relayout()
        self.pump()
        self.assertEqual(label.winfo_width(), label.winfo_reqwidth())
        self.assertGreater(label.winfo_y(), buttons[0].winfo_y(), "wrapped below")
        self.assertEqual(label.winfo_x(), 0)

    def test_fit_width_item_is_given_the_row_width(self):
        seen = []

        class Fitting(ttk.Label):
            def fit_width(self, room):
                seen.append(room)
        row = FlowRow(self.root)
        row.frame.pack(fill="x")
        row.add(Fitting(row.frame, text="x"))
        self.resize(640)
        self.assertTrue(seen)
        self.assertEqual(seen[-1], row.frame.winfo_width())


if __name__ == "__main__":
    unittest.main()
