"""Benchmark charts filter the runs they compare: engine build, sieve threads, write threads,
range width (primeatlas/benchmark/chart_filter.py and the tab's Filter window).

Pure: each run's value per dimension (engine build "v6.0", "15 thr" / "2x24 thr", write "8",
width "10^11"); the values the log holds, in numeric order; a selection keeps the runs whose
value is selected in every enabled dimension, a disabled dimension filters nothing, and the
last row per floor is chosen among the kept runs; the summary names the enabled dimensions.
On a real BenchmarkTab: no filter shows every line; selecting 15 threads and width 10^11 in
the Filter window leaves only those lines on both charts, the summary shows it, the mixed-
width note goes away, and the PDF export draws only those lines and names the filter in its
subtitle. Windows, real display (the tab part):
    python unitTests/test_benchmark_filter.py
"""
import csv
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from primeatlas.benchmark import benchmark, chart_filter  # noqa: E402
from primeatlas.core.i18n import Translator  # noqa: E402

W = 10_000_000


def _row(engine, version, threads, write, numbers, sieve, floor=19, instance="1/1", ts="1"):
    return dict(run_timestamp_utc=ts, base_exponent=str(floor), engine=engine,
                engine_version=version, threads=threads, write_threads=write,
                instance_of_n=instance, numbers_processed=str(numbers),
                windows_written=str(numbers // W), sieve_seconds=str(sieve),
                loop_numbers_per_second=str(numbers / (sieve + 1)), write_seconds="1",
                bytes_written="1000000")


ROWS = [
    _row("v6", "v6.0", "15", "8", 10 ** 11, 26.5, ts="a"),
    _row("v6", "v6.0", "24", "8", 2 * 10 ** 11, 29.9, ts="b"),
    _row("v5", "v5.1", "15", "1", 10 ** 11, 30.0, ts="c"),
    _row("v4.1", "v4.1", "24", "1", 10 ** 10, 58.6, instance="1/15", ts="d"),
    _row("primesieve_count", "12.15", "15", "", 10 ** 10, 3.2, ts="e"),
    _row("primesieve_count", "12.15", "15", "", 10 ** 11, 25.0, ts="f"),
]


class PureTests(unittest.TestCase):
    def test_values(self):
        self.assertEqual(chart_filter.dimension_values(ROWS, "threads"),
                         ["15 thr", "24 thr", "15x24 thr"])
        self.assertEqual(chart_filter.dimension_values(ROWS, "width"), ["10^10", "10^11", "2x10^11"])
        self.assertEqual(chart_filter.dimension_values(ROWS, "write_threads"), ["", "1", "8"])
        self.assertIn("primesieve count (native) 12.15",
                      chart_filter.dimension_values(ROWS, "engine"))

    def test_apply(self):
        self.assertEqual(chart_filter.apply(ROWS, {}), ROWS, "no dimension enabled: all runs")
        kept = chart_filter.apply(ROWS, {"threads": {"15 thr"}, "width": {"10^11"}})
        self.assertEqual([r["run_timestamp_utc"] for r in kept], ["a", "c", "f"])
        self.assertEqual(chart_filter.apply(ROWS, {"threads": set()}), [],
                         "an enabled dimension with nothing selected keeps nothing")

    def test_last_row_per_floor_among_the_kept_runs(self):
        kept = chart_filter.apply(ROWS, {"width": {"10^10"}})
        lines = benchmark.benchmark_engine_lines(kept, "sieve")
        self.assertEqual(lines["primesieve count (native) 12.15, 15 thr"], [(19, 10 ** 10 / 3.2)],
                         "the 10^10 count, not the later 10^11 one")

    def test_summary(self):
        t = Translator("en").t
        self.assertEqual(chart_filter.summary({}, t), t("bench.filter_off"))
        text = chart_filter.summary({"threads": {"15 thr"}, "width": {"10^11", "10^10"}}, t)
        self.assertIn("15 thr", text)
        self.assertIn("10^10, 10^11", text)


class TabTests(unittest.TestCase):
    def test_filter_window_drives_charts_and_pdf(self):
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
            try:
                tab = benchmark_tab.BenchmarkTab(
                    root, lambda: portal, tk.StringVar(master=root), Translator("en"),
                    lambda *a, **k: None, palette_for("light"))
                tab.pack(fill="both", expand=True)
                tab.reload_benchmark_log()
                root.update()

                def tags(canvas):
                    return {p[4].split("[", 1)[1].split("]")[0]
                            for p in captured.get(str(canvas), []) if "[" in p[4]}

                tab._redraw_charts()
                self.assertIn("v4.1, 15x24 thr, write 1", tags(tab.benchmark_chart2))
                self.assertTrue(tab.mixed_widths_vars["sieve"].get())

                window = tab._open_filter_window()
                window.enabled["threads"].set(True)
                window.enabled["width"].set(True)
                for dim, keep in (("threads", "15 thr"), ("width", "10^11")):
                    for value, var in window.values[dim].items():
                        var.set(value == keep)
                window.apply()
                root.update()
                self.assertEqual(tags(tab.benchmark_chart2),
                                 {"v6.0, 15 thr, write 8", "v5.1, 15 thr, write 1",
                                  "primesieve count (native) 12.15, 15 thr"})
                self.assertIn("15 thr", tab.filter_summary_var.get())
                self.assertEqual(tab.mixed_widths_vars["sieve"].get(), "")

                with tempfile.TemporaryDirectory() as out:
                    path = os.path.join(out, "r.pdf")
                    tab._render_pdf(path)
                    text = Path(path).read_bytes().decode("latin-1")
                self.assertNotIn("24 thr, write 8]", text)
                self.assertIn("15 thr, write 8]", text)
                self.assertIn("10^11", text.split("Tj", 2)[1], "the subtitle names the filter")
                window.destroy()
            finally:
                root.destroy()
                benchmark_tab._bind_chart_hover = original_hover


if __name__ == "__main__":
    unittest.main()
