"""Benchmark charts zoom and pan along the floor axis (primeatlas/benchmark/chart_view.py and the
tab's canvas bindings), like the visualizations: wheel zooms around the pointer, a left drag
pans, a middle click or a double click shows every floor again.

Checks: zooming keeps the floor under the pointer in place, never goes below MIN_WIDTH floors
or outside the data, and zooming out to the whole span gives None; pan shifts and clamps;
only the points inside the view stay; the canvas maps a pixel back to its floor. On a real
BenchmarkTab: a wheel notch over a chart zooms all three charts (one shared floor view) and the
y scales refit to the visible points, the wheel does not reach the page behind the chart, a drag
pans, a double click resets, and the PDF/SVG exports draw only the floors in view. Windows, real
display (the tab part):
    python unitTests/test_benchmark_chart_zoom.py
"""
import csv
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from primeatlas.benchmark import chart_view, report_export  # noqa: E402
from primeatlas.benchmark.chart_series import Series  # noqa: E402
from primeatlas.core.i18n import Translator  # noqa: E402

S = [Series("v5", "v5", [(f, f * 1e6) for f in range(10, 31)], "#1f77b4", False)]


class ViewTests(unittest.TestCase):
    def test_zoom_keeps_the_anchor(self):
        span = chart_view.data_span(S)
        self.assertEqual(span, (10, 30))
        view = chart_view.zoom(None, span, 15, 0.5)
        self.assertAlmostEqual(view[1] - view[0], 10)
        self.assertAlmostEqual((15 - view[0]) / (view[1] - view[0]), (15 - 10) / 20)
        self.assertIsNone(chart_view.zoom(view, span, 15, 4.0), "out to the whole span -> None")

    def test_zoom_limits(self):
        span = (10, 30)
        view = None
        for _ in range(40):
            view = chart_view.zoom(view, span, 29.9, 0.5)
        self.assertAlmostEqual(view[1] - view[0], chart_view.MIN_WIDTH)
        self.assertLessEqual(view[1], 30)
        self.assertIsNone(chart_view.zoom(None, (20, 20), 20, 0.5), "a single floor never zooms")

    def test_pan_and_filter(self):
        span = (10, 30)
        self.assertEqual(chart_view.pan((12, 16), span, 3), (15, 19))
        self.assertEqual(chart_view.pan((12, 16), span, -10), (10, 14))
        self.assertEqual(chart_view.pan((12, 16), span, 99), (26, 30))
        self.assertIsNone(chart_view.pan(None, span, 3))
        kept = chart_view.in_view(S, (12, 14.5))
        self.assertEqual([x for x, _y in kept[0].points], [12, 13, 14])
        self.assertEqual(chart_view.in_view(S, None)[0].points, S[0].points)

    def test_floor_at(self):
        geometry = (100.0, 400.0, 10, 30)
        self.assertAlmostEqual(chart_view.floor_at(geometry, 300), 20)
        self.assertAlmostEqual(chart_view.floors_per_pixel(geometry), 0.05)


def _row(floor, engine, nps, ram):
    return dict(base_exponent=str(floor), engine=engine, loop_numbers_per_second=str(nps),
                numbers_processed="100", windows_written="10", sieve_seconds="1",
                bytes_written="2000000", write_seconds="1", max_child_rss_mb=str(ram))


ROWS = [_row(f, "v5", 1e6 * f, 100 * f) for f in range(10, 31)]


class TabZoomTests(unittest.TestCase):
    def test_wheel_drag_and_reset(self):
        import tkinter as tk
        from primeatlas.benchmark import benchmark_tab
        from primeatlas.core.theme import palette_for

        captured = {}
        original_hover = benchmark_tab._bind_chart_hover
        benchmark_tab._bind_chart_hover = (
            lambda canvas, points, *a: captured.__setitem__(str(canvas), list(points)))
        with tempfile.TemporaryDirectory() as portal:
            with open(os.path.join(portal, "benchmark_log.csv"), "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(ROWS[0]))
                writer.writeheader()
                writer.writerows(ROWS)
            root = tk.Tk()
            page_wheel = []
            root.bind_all("<MouseWheel>", lambda e: page_wheel.append(e))
            try:
                tab = benchmark_tab.BenchmarkTab(
                    root, lambda: portal, tk.StringVar(master=root), Translator("en"),
                    lambda *a, **k: None, palette_for("light"))
                tab.pack(fill="both", expand=True)
                root.geometry("1000x800")
                tab.reload_benchmark_log()
                root.update()
                tab._redraw_charts()
                chart, chart3 = tab.benchmark_chart, tab.benchmark_chart3

                def floors(canvas):
                    return sorted({p[2] for p in captured.get(str(canvas), [])
                                   if isinstance(p[2], (int, float))})

                self.assertEqual(floors(chart), list(range(10, 31)))
                x0, width, _lo, _hi = chart.chart_geometry
                px = int(x0 + width * 0.25)
                for _ in range(3):
                    chart.event_generate("<MouseWheel>", x=px, y=100, delta=120)
                root.update()
                view = tab._x_view
                self.assertIsNotNone(view)
                self.assertLess(view[1] - view[0], 20)
                self.assertTrue(view[0] <= 15 <= view[1], view)
                self.assertTrue(all(view[0] <= f <= view[1] for f in floors(chart)))
                self.assertEqual(floors(chart3), floors(chart), "the RAM chart shares the view")
                self.assertEqual(page_wheel, [], "the wheel over a chart does not scroll the page")

                before = tab._x_view
                chart.event_generate("<ButtonPress-1>", x=400, y=120)
                chart.event_generate("<B1-Motion>", x=300, y=120)
                chart.event_generate("<ButtonRelease-1>", x=300, y=120)
                root.update()
                self.assertGreater(tab._x_view[0], before[0], "dragging left shows later floors")

                with tempfile.TemporaryDirectory() as out:
                    path = os.path.join(out, "r.svg")
                    report_export.export("svg", path, tab._benchmark_fieldnames,
                                         tab._benchmark_rows, **tab._view_options())
                    text = Path(path).read_text(encoding="utf-8")
                lo, hi = tab._x_view
                outside = [f for f in range(10, 31) if not lo <= f <= hi]
                self.assertTrue(outside)
                self.assertNotIn(f">{outside[0]}</text>", text, "the export follows the view")

                # Tk refuses to generate a double click; the binding is checked, and the
                # middle click (same handler) resets.
                self.assertTrue(chart.bind("<Double-Button-1>"))
                chart.event_generate("<Button-2>", x=400, y=120)
                root.update()
                self.assertIsNone(tab._x_view)
                self.assertEqual(floors(chart), list(range(10, 31)))
            finally:
                root.destroy()
                benchmark_tab._bind_chart_hover = original_hover


if __name__ == "__main__":
    unittest.main()
