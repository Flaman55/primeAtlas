"""Benchmark charts zoom like a picture (primeatlas/benchmark/chart_view.py, the tab's canvas
bindings): unzoomed a chart shows all of itself (the furthest zoom out), the wheel zooms the part
under the pointer on both axes, a left drag moves the visible part, a middle or double click
shows the whole charts again.

Checks, pure: a wheel notch moves the zoom level by one and the level alone sets the width,
so zooming out retraces zooming in notch by notch and as many notches out as in are the whole
chart; zooming keeps the point under the pointer in place and stops at MAX_LEVEL; the first
notch zooms from the floors of the chart under the pointer; pan shifts and clamps; a zoomed floor axis ticks
whole floors; YScale.zoomed() narrows a scale to a part of it; clip_polyline() cuts lines at
the left and right plot edges too. On a real BenchmarkTab: a wheel notch zooms the floor axis of
all three charts and the y axis of that chart only, the wheel does not reach the page behind
the chart, a drag moves both axes, a double or middle click resets; with logged floors 11 and
13 only, zooming between them shows the line passing through (no "no data"); the PDF/SVG
exports draw the zoomed part. Windows, real display (the tab part):
    python unitTests/test_benchmark_chart_zoom.py
"""
import csv
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from app_sandbox import fresh_ui_store  # noqa: E402

from primeatlas.benchmark import chart_view, report_export  # noqa: E402
from primeatlas.benchmark.chart_series import YScale, clip_polyline  # noqa: E402
from primeatlas.core.i18n import Translator  # noqa: E402


class ViewTests(unittest.TestCase):
    def test_zoom_keeps_the_anchor(self):
        step = chart_view.zoom_step
        view, level = step(None, 0, (10, 30), 15, 1, (10, 30))
        self.assertEqual(level, 1)
        self.assertAlmostEqual(view[1] - view[0], 20 * chart_view.WHEEL_STEP)
        self.assertAlmostEqual((15 - view[0]) / (view[1] - view[0]), (15 - 10) / 20)
        y, _y_level = step(None, 0, chart_view.FULL_Y, 0.25, 1, chart_view.FULL_Y)
        self.assertAlmostEqual(y[1] - y[0], chart_view.WHEEL_STEP)
        self.assertAlmostEqual(y[0], 0.25 - 0.25 * 0.8)

    def test_zoom_from_the_chart_zoomed_first(self):
        # A chart showing floors 11..13 of a 11..27 span zooms from 11..13.
        view, _level = chart_view.zoom_step(None, 0, (11, 13), 12, 1, (11, 27))
        self.assertAlmostEqual(view[1] - view[0], 1.6)
        self.assertTrue(11 <= view[0] < 12 < view[1] <= 13)

    def test_zoom_out_retraces_zoom_in(self):
        """The notch level sets the width: each notch out gives back the width of the notch
        before, and as many notches out as in are the whole chart."""
        step = chart_view.zoom_step
        view, level, widths = None, 0, []
        for anchor in (12, 12.3, 11.8, 12.6):
            view, level = step(view, level, (11, 13), anchor, 1, (11, 27))
            widths.append(view[1] - view[0])
        self.assertEqual(level, 4)
        for expected in reversed(widths[:-1]):
            view, level = step(view, level, (11, 13), 12, -1, (11, 27))
            self.assertAlmostEqual(view[1] - view[0], expected)
        view, level = step(view, level, (11, 13), 12, -1, (11, 27))
        self.assertEqual((view, level), (None, 0))
        self.assertEqual(step(None, 0, (11, 13), 12, -1, (11, 27)), (None, 0),
                         "zooming out of the whole chart stays whole")

    def test_points_at_one_spot_share_the_tooltip(self):
        from primeatlas.benchmark.chart_hover import _hover_points_at
        circle = (100, 50, 11, 300.0, "{:,.0f}", "#00c8c8", "k1", "primary")
        square = (101, 51, 11, 19.8, "{:,.1f}", "#7f00ff", "k2", "secondary")
        other = (140, 50, 13, 290.0, "{:,.0f}", "#00c8c8", "k1", "primary")
        self.assertEqual(_hover_points_at([square, other, circle], 101, 51),
                         [circle, square], "both points under the pointer, left axis first")
        self.assertEqual(_hover_points_at([square, other, circle], 139, 50), [other])
        self.assertEqual(_hover_points_at([square], 300, 300), [])

    def test_zoom_limits(self):
        view, level = None, 0
        for _ in range(60):
            view, level = chart_view.zoom_step(view, level, (10, 30), 29.9, 1, (10, 30))
        self.assertEqual(level, chart_view.MAX_LEVEL)
        self.assertAlmostEqual(view[1] - view[0], 20 * 0.8 ** chart_view.MAX_LEVEL)
        self.assertEqual(chart_view.zoom_step(None, 0, (20, 20), 20, 1, (20, 20)), (None, 0),
                         "a single floor never zooms")

    def test_pan(self):
        full = (10, 29)
        self.assertEqual(chart_view.pan((12, 16), full, 3), (15, 19))
        # The last floor can travel to the view's left edge, the first to its right edge,
        # never further: the data never leaves the view.
        self.assertEqual(chart_view.pan((24, 28), full, 3), (27, 31))
        self.assertEqual(chart_view.pan((24, 28), full, 99), (29, 33))
        self.assertEqual(chart_view.pan((12, 16), full, -99), (6, 10))
        self.assertIsNone(chart_view.pan(None, full, 3))
        y = chart_view.pan((0.6, 0.9), chart_view.FULL_Y, 0.5)
        self.assertAlmostEqual(y[0], 1.0)
        self.assertAlmostEqual(y[1], 1.3)
        # Zooming a view panned past the data keeps it where it is.
        view, _level = chart_view.zoom_step((27, 31), 1, (21, 26), 29, 1, full)
        self.assertAlmostEqual(view[0], 29 - 0.5 * 5 * 0.64)
        self.assertGreater(view[1], full[1], "still past the last floor")

    def test_ticks_geometry_scale_and_clip(self):
        self.assertEqual(chart_view.tick_floors(11.3, 12.6, 0.1), [12])
        self.assertEqual(chart_view.tick_floors(10.95, 13.0, 0.1), [11, 12, 13])
        many = chart_view.tick_floors(0, 100, 0)
        self.assertLessEqual(len(many), chart_view.MAX_X_TICKS)
        self.assertEqual(many[:3], [0, 5, 10])
        geometry = (100.0, 400.0, 10, 30, 40, 200, (0.5, 1.0))
        self.assertAlmostEqual(chart_view.floor_at(geometry, 300), 20)
        self.assertAlmostEqual(chart_view.floors_per_pixel(geometry), 0.05)
        self.assertAlmostEqual(chart_view.y_frac_at(geometry, 240), 0.5)
        self.assertAlmostEqual(chart_view.y_frac_at(geometry, 40), 1.0)
        self.assertAlmostEqual(chart_view.y_fracs_per_pixel(geometry), 0.0025)
        scale = YScale([0, 100])
        part = scale.zoomed((0.5, 1.0))
        self.assertAlmostEqual(part.frac(50), 0.0)
        self.assertAlmostEqual(part.frac(100), 1.0)
        self.assertIs(scale.zoomed(None), scale)
        self.assertEqual(clip_polyline([(0, 0.5), (10, 0.5)], 2, 6), [[(2.0, 0.5), (6.0, 0.5)]])
        self.assertEqual(clip_polyline([(0, 0.5), (10, 0.5)], 12, 16), [])
        self.assertEqual(clip_polyline([(0, 0.0), (10, 2.0)], 2, 8), [[(2.0, 0.4), (5.0, 1.0)]])


def _row(floor, engine, nps, ram):
    return dict(base_exponent=str(floor), engine=engine, loop_numbers_per_second=str(nps),
                numbers_processed="100", windows_written="10", sieve_seconds="1",
                bytes_written="2000000", write_seconds="1", max_child_rss_mb=str(ram))


def _tab(rows, portal, root):
    from primeatlas.benchmark import benchmark_tab
    from primeatlas.core.theme import palette_for
    import tkinter as tk
    with open(os.path.join(portal, "benchmark_log.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    fresh_ui_store()
    tab = benchmark_tab.BenchmarkTab(root, lambda: portal, tk.StringVar(master=root),
                                     Translator("en"), lambda *a, **k: None,
                                     palette_for("light"))
    tab.pack(fill="both", expand=True)
    root.geometry("1000x800")
    tab.reload_benchmark_log()
    root.update()
    tab._redraw_charts()
    return tab


def _texts(canvas):
    return [canvas.itemcget(i, "text") for i in canvas.find_all() if canvas.type(i) == "text"]


def _lines_of(canvas, width):
    return [i for i in canvas.find_all()
            if canvas.type(i) == "line" and float(canvas.itemcget(i, "width")) == width]


class TabZoomTests(unittest.TestCase):
    def setUp(self):
        from primeatlas.benchmark import benchmark_tab
        self.captured = {}
        self.module = benchmark_tab
        self.original_hover = benchmark_tab._bind_chart_hover
        benchmark_tab._bind_chart_hover = (
            lambda canvas, points, *a: self.captured.__setitem__(str(canvas), list(points)))

    def tearDown(self):
        self.module._bind_chart_hover = self.original_hover

    def floors(self, canvas):
        return sorted({p[2] for p in self.captured.get(str(canvas), [])})

    def test_wheel_drag_and_reset(self):
        import tkinter as tk
        rows = [_row(f, "v5", 1e6 * f, 100 * f) for f in range(10, 31)]
        with tempfile.TemporaryDirectory() as portal:
            root = tk.Tk()
            page_wheel = []
            root.bind_all("<MouseWheel>", lambda e: page_wheel.append(e))
            try:
                tab = _tab(rows, portal, root)
                chart, chart3 = tab.benchmark_chart, tab.benchmark_chart3
                self.assertEqual(self.floors(chart), list(range(10, 31)))
                x0, width, _lo, _hi, top, height, _yv = chart.chart_geometry[:7]
                for _ in range(3):
                    chart.event_generate("<MouseWheel>", x=int(x0 + width * 0.25),
                                         y=int(top + height * 0.75), delta=120)
                root.update()
                view, y_view = tab._x_view, tab._y_views["run"]
                self.assertIsNotNone(view)
                self.assertLess(view[1] - view[0], 20)
                self.assertTrue(view[0] <= 15 <= view[1], view)
                self.assertIsNotNone(y_view, "the wheel zooms the y axis too")
                self.assertLess(y_view[1] - y_view[0], 1)
                self.assertIsNone(tab._y_views["ram"], "other charts keep their y axis")
                self.assertEqual(chart3.chart_geometry[2:4], view, "the RAM chart shares x")
                self.assertLess(len(self.floors(chart3)), 21)
                self.assertEqual(page_wheel, [], "the wheel over a chart does not scroll the page")

                before_x, before_y = tab._x_view, tab._y_views["run"]
                chart.event_generate("<ButtonPress-1>", x=400, y=120)
                chart.event_generate("<B1-Motion>", x=300, y=160)
                chart.event_generate("<ButtonRelease-1>", x=300, y=160)
                root.update()
                self.assertGreater(tab._x_view[0], before_x[0], "dragging left shows later floors")
                self.assertGreater(tab._y_views["run"][0], before_y[0],
                                   "dragging down shows higher values")

                with tempfile.TemporaryDirectory() as out:
                    path = os.path.join(out, "r.svg")
                    report_export.export("svg", path, tab._benchmark_fieldnames,
                                         tab._benchmark_rows, **tab._view_options())
                    text = Path(path).read_text(encoding="utf-8")
                lo, hi = tab._x_view
                outside = [f for f in range(10, 31) if not lo - 1 <= f <= hi + 1]
                self.assertTrue(outside)
                self.assertNotIn(f">{outside[0]}</text>", text, "the export follows the zoom")

                # Tk refuses to generate a double click; the binding is checked, and the
                # middle click (same handler) resets.
                self.assertTrue(chart.bind("<Double-Button-1>"))
                chart.event_generate("<Button-2>", x=400, y=120)
                root.update()
                self.assertIsNone(tab._x_view)
                self.assertEqual(set(tab._y_views.values()), {None})
                self.assertEqual(self.floors(chart), list(range(10, 31)))
            finally:
                root.destroy()

    def test_zoom_out_goes_back_one_notch_at_a_time(self):
        import tkinter as tk
        rows = [_row(f, "v5", 1e6 * f, 100 * f) for f in range(10, 31)]
        with tempfile.TemporaryDirectory() as portal:
            root = tk.Tk()
            try:
                tab = _tab(rows, portal, root)
                chart = tab.benchmark_chart
                x0, width, _lo, _hi, top, height = chart.chart_geometry[:6]
                at = dict(x=int(x0 + width / 2), y=int(top + height / 2))
                widths = []
                for _ in range(4):
                    chart.event_generate("<MouseWheel>", delta=120, **at)
                    root.update()
                    widths.append(tab._x_view[1] - tab._x_view[0])
                for expected in reversed(widths[:-1]):
                    chart.event_generate("<MouseWheel>", delta=-120, **at)
                    root.update()
                    self.assertIsNotNone(tab._x_view, "one notch out, not the whole chart")
                    self.assertAlmostEqual(tab._x_view[1] - tab._x_view[0], expected)
                    self.assertIsNotNone(tab._y_views["run"])
                chart.event_generate("<MouseWheel>", delta=-120, **at)
                root.update()
                self.assertIsNone(tab._x_view, "the last notch out is the whole chart")
                self.assertIsNone(tab._y_views["run"])
            finally:
                root.destroy()

    def test_drag_never_takes_the_data_out_of_view(self):
        """Values far above zero (the linear scale starts at 0): a long drag in any of the four
        directions stops with the data at the view's edge, a point still drawn."""
        import tkinter as tk
        rows = [_row(f, "v6", 1.3e7 + 1e5 * f, 43) for f in range(11, 20)]
        with tempfile.TemporaryDirectory() as portal:
            root = tk.Tk()
            try:
                tab = _tab(rows, portal, root)
                chart = tab.benchmark_chart
                for dx, dy in ((0, -2000), (0, 2000), (-2000, 0), (2000, 0)):
                    tab._reset_chart_view()
                    x0, width, _lo, _hi, top, height = chart.chart_geometry[:6]
                    for _ in range(4):
                        chart.event_generate("<MouseWheel>", x=int(x0 + width / 2),
                                             y=int(top + height / 2), delta=120)
                    root.update()
                    chart.event_generate("<ButtonPress-1>", x=400, y=120)
                    chart.event_generate("<B1-Motion>", x=400 + dx, y=120 + dy)
                    chart.event_generate("<ButtonRelease-1>", x=400 + dx, y=120 + dy)
                    root.update()
                    self.assertTrue(self.captured.get(str(chart)),
                                    (dx, dy, tab._x_view, tab._y_views["run"]))
            finally:
                root.destroy()

    def test_zoom_between_sparse_floors_keeps_the_line(self):
        """Floors 11 and 13 only, the PARI references on: zooming into the part between the
        floors shows the line passing through, never "no data"."""
        import tkinter as tk
        rows = [_row(11, "v6", 1.3e7, 43), _row(13, "v6", 1.4e7, 43)]
        no_data = Translator("en").t("bench.no_data_chart")
        with tempfile.TemporaryDirectory() as portal:
            root = tk.Tk()
            try:
                tab = _tab(rows, portal, root)
                tab.references_var.set(True)
                tab._redraw_charts()
                chart = tab.benchmark_chart
                x0, width, lo, hi, top, height, _yv = chart.chart_geometry[:7]
                self.assertEqual((lo, hi), (11, 13))
                px = int(x0 + width * 0.5)
                for _ in range(5):
                    x0, width, lo, hi, top, height, _yv = chart.chart_geometry[:7]
                    # Keep the pointer on the line: halfway in x, where the line is in y.
                    scale_px = [chart.coords(i) for i in _lines_of(chart, 3.0)]
                    y_line = scale_px[0][1] if scale_px else top + height / 2
                    chart.event_generate("<MouseWheel>", x=px, y=int(y_line), delta=120)
                    root.update()
                view = tab._x_view
                self.assertTrue(11 < view[0] and view[1] < 13, view)
                self.assertEqual(self.floors(chart), [], "no logged floor in view")
                self.assertNotIn(no_data, _texts(chart))
                self.assertTrue(_lines_of(chart, 3.0), "the v6 line passes through the view")
                for x1, _y1, x2, _y2 in (chart.coords(i) for i in _lines_of(chart, 3.0)):
                    self.assertGreaterEqual(min(x1, x2), x0 - width, "cut at the plot edge")
                ticks = [s for s in _texts(chart) if re.fullmatch(r"\d+", s)]
                self.assertEqual(ticks, ["12"], "a zoomed axis ticks the whole floor in it")
            finally:
                root.destroy()


if __name__ == "__main__":
    unittest.main()
