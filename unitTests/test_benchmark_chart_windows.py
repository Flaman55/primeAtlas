"""Any Benchmark chart opens in a window of its own (primeatlas/benchmark/benchmark_chart_windows.py).

Checks on a real BenchmarkTab: each chart has an "Open in new window" button; the window is
titled with the chart's name and draws the same points as the tab's canvas; a second click
raises the open window instead of a second copy; zooming in the window zooms the tab's charts
(one shared floor view); a legend toggle, the filter and the log scale redraw the window too;
closing the window drops its canvas and later redraws leave it alone. Windows, real display:
    python unitTests/test_benchmark_chart_windows.py
"""
import csv
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from app_sandbox import fresh_ui_store  # noqa: E402

from primeatlas.core.i18n import Translator  # noqa: E402


def _row(floor, engine, nps):
    return dict(base_exponent=str(floor), engine=engine, loop_numbers_per_second=str(nps),
                numbers_processed="100", windows_written="10", sieve_seconds="1",
                bytes_written="2000000", write_seconds="1", max_child_rss_mb=str(10 * floor))


ROWS = [_row(f, e, k * 1e6 * f) for f in range(10, 25) for e, k in (("v5", 1), ("v6", 2))]


class ChartWindowTests(unittest.TestCase):
    def test_windows_mirror_the_tab_charts(self):
        import tkinter as tk
        from tkinter import ttk
        from primeatlas.benchmark import benchmark_tab
        from primeatlas.core.theme import palette_for

        t = Translator("en").t
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
            try:
                fresh_ui_store()
                tab = benchmark_tab.BenchmarkTab(
                    root, lambda: portal, tk.StringVar(master=root), Translator("en"),
                    lambda *a, **k: None, palette_for("light"))
                tab.pack(fill="both", expand=True)
                root.geometry("1000x800")
                tab.reload_benchmark_log()
                root.update()

                def points(canvas):
                    return sorted((p[2], p[3]) for p in captured.get(str(canvas), []))

                def buttons(widget):
                    for child in widget.winfo_children():
                        if isinstance(child, ttk.Button):
                            yield child.cget("text")
                        yield from buttons(child)

                self.assertEqual(list(buttons(tab)).count(t("bench.chart_open_window")), 3)

                canvases = {"run": tab.benchmark_chart, "sieve": tab.benchmark_chart2,
                            "ram": tab.benchmark_chart3}
                windows = {}
                for chart, canvas in canvases.items():
                    win = tab._open_chart_window(chart)
                    root.update()
                    windows[chart] = win
                    self.assertEqual(win.title(), t("bench.chart_window_title",
                                                    chart=t(f"bench.chart_name_{chart}")))
                    (mirror,) = tab._chart_window_canvases(chart)
                    self.assertGreater(mirror.winfo_width(), canvas.winfo_width() - 200)
                    self.assertTrue(points(mirror))
                    self.assertEqual(points(mirror), points(canvas), chart)
                    self.assertIs(tab._open_chart_window(chart), win, "raised, not a second copy")

                (mirror,) = tab._chart_window_canvases("run")
                x0, width = mirror.chart_geometry[:2]
                for _ in range(3):
                    mirror.event_generate("<MouseWheel>", x=int(x0 + width * 0.3), y=100,
                                          delta=120)
                root.update()
                view = tab._x_view
                self.assertIsNotNone(view, "the window zooms the shared floor view")
                for canvas in list(canvases.values()) + [mirror]:
                    self.assertEqual(canvas.chart_geometry[2:4], view, "one shared floor range")
                self.assertEqual(points(mirror), points(tab.benchmark_chart))
                tab._reset_chart_view()

                before = len(points(mirror))
                v5 = [name for name in {s.name for s in tab._chart_series("growth")}
                      if name.startswith("v5")]
                tab._toggle_lines("run", [("primary", n) for n in v5])
                root.update()
                self.assertEqual(points(mirror), points(tab.benchmark_chart))
                self.assertTrue(0 < len(points(mirror)) < before, "the v5 line left the window")

                tab.log_scale_var.set(True)
                tab._redraw_charts()
                root.update()
                self.assertEqual(points(mirror), points(tab.benchmark_chart))

                tab._set_filter({"engine": {"v6"}})
                root.update()
                ram_mirror, = tab._chart_window_canvases("ram")
                self.assertEqual(points(ram_mirror), points(tab.benchmark_chart3))

                windows["run"].tk.call(windows["run"].protocol("WM_DELETE_WINDOW"))
                root.update()
                self.assertEqual(tab._chart_window_canvases("run"), [])
                tab._redraw_charts()   # no TclError from the destroyed canvas
                root.update()
                self.assertEqual(len(tab._chart_window_canvases("sieve")), 1)
            finally:
                root.destroy()
                benchmark_tab._bind_chart_hover = original_hover


if __name__ == "__main__":
    unittest.main()
