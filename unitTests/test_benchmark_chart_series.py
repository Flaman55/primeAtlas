"""Benchmark charts: one line per engine, engine tags, log scale and reference points.

Pure checks on chart_series.py / reference_points.py / chart_pdf.py and the PDF report,
plus a real BenchmarkTab (tkinter, temp portal) for the canvas hover, the two toggles and
the PDF export following them. Windows, real display:
    python unitTests/test_benchmark_chart_series.py
"""
import csv
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from primeatlas.benchmark import benchmark, chart_pdf, chart_series, reference_points
from primeatlas.core.i18n import Translator


def _row(floor, engine, nps="", spw="", sieve_seconds="", write_seconds=""):
    return dict(base_exponent=str(floor), engine=engine, loop_numbers_per_second=nps,
                loop_seconds_per_window=spw, numbers_processed="100", windows_written="10",
                sieve_seconds=sieve_seconds, bytes_written="2000000",
                write_seconds=write_seconds)


ROWS = [
    _row(20, "v4.1", nps="5e7", spw="0.2", sieve_seconds="1", write_seconds="1"),
    _row(20, "v5", nps="3.5e8", spw="0.03", sieve_seconds="0.5", write_seconds="0"),
    _row(25, "v5", nps="1.4e8", spw="0.07", sieve_seconds="2", write_seconds="2"),
    _row(25, "v4.1", nps="nan", spw="0.18", sieve_seconds="4", write_seconds="1"),
    _row(10, "", nps="4e7", spw="0.25"),
]


class EngineLinesTests(unittest.TestCase):
    def test_one_line_per_engine_last_valid_row_per_floor(self):
        self.assertEqual(benchmark.benchmark_engine_lines(ROWS, "growth"),
                         {"v4.1": [(20, 5e7)], "v5": [(20, 3.5e8), (25, 1.4e8)],
                          "unknown": [(10, 4e7)]})
        self.assertEqual(benchmark.benchmark_engine_lines(ROWS, "sieve"),
                         {"v4.1": [(20, 100.0), (25, 25.0)], "v5": [(20, 200.0), (25, 50.0)]})
        self.assertEqual(benchmark.benchmark_engine_lines(ROWS, "write"),
                         {"v4.1": [(20, 2.0), (25, 2.0)], "v5": [(25, 1.0)]})
        # Sieve seconds per window: sieve_seconds / windows_written.
        self.assertEqual(benchmark.benchmark_engine_lines(ROWS, "sieve_spw"),
                         {"v4.1": [(20, 0.1), (25, 0.4)], "v5": [(20, 0.05), (25, 0.2)]})
        broken = [dict(_row(9, "v5", sieve_seconds="1"), windows_written=w)
                  for w in ("", "0", "x")]
        self.assertEqual(benchmark.benchmark_engine_lines(broken, "sieve_spw"), {})

    def test_series_order_tags_and_colors(self):
        series = chart_series.engine_series(benchmark.benchmark_engine_lines(ROWS, "growth"))
        self.assertEqual([s.name for s in series], ["unknown", "v4.1", "v5"])
        self.assertEqual([s.tag for s in series], ["", "v4.1", "v5"])
        self.assertFalse(any(s.dashed for s in series))
        # One color per engine on both axes; the axis shows in the marker shape.
        write = chart_series.engine_series(benchmark.benchmark_engine_lines(ROWS, "write"))
        self.assertEqual({s.name: s.color for s in write},
                         {s.name: s.color for s in series if s.name in ("v4.1", "v5")})

    def test_legend_lists_each_engine_once_in_engine_order(self):
        sieve = chart_series.engine_series({"v5": [(20, 1.0)], "v4.1": [(20, 2.0)]})
        write = chart_series.engine_series({"unknown": [(9, 1.0)], "v5": [(20, 3.0)]})
        refs = reference_points.reference_series(Translator("en").t)
        names = [s.name for s in chart_series.legend_series(sieve + refs, write)]
        self.assertEqual(names, ["unknown", "v4.1", "v5"] + [r.name for r in refs])

    def test_every_drawn_color_is_far_from_the_others(self):
        colors = dict(chart_series.ENGINE_COLORS, other=chart_series.OTHER_ENGINE_COLOR)
        colors.update({r.tag: r.color for r in reference_points.REFERENCES})
        rgb = {k: [int(v[i:i + 2], 16) for i in (1, 3, 5)] for k, v in colors.items()}
        names = sorted(rgb)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                distance = sum((p - q) ** 2 for p, q in zip(rgb[a], rgb[b])) ** 0.5
                self.assertGreaterEqual(distance, 90, f"{a} {colors[a]} vs {b} {colors[b]}")


class ScaleTests(unittest.TestCase):
    def test_log_scale_fits_the_data_range(self):
        scale = chart_series.YScale([2.6e6, 2.8e9], log=True)
        self.assertTrue(0 < scale.frac(2.6e6) < 0.1, scale.frac(2.6e6))
        self.assertTrue(0.9 < scale.frac(2.8e9) < 1, scale.frac(2.8e9))
        self.assertEqual(scale.ticks(), [1e7, 1e8, 1e9])
        self.assertEqual(scale.tick_label(1e9, "{:,.0f}"), "1e9")
        self.assertFalse(scale.usable(0))

    def test_narrow_log_range_gets_1_2_5_ticks(self):
        scale = chart_series.YScale([4e7, 3.5e8], log=True)
        self.assertTrue(0 < scale.frac(4e7) < 0.1 and 0.9 < scale.frac(3.5e8) < 1)
        self.assertEqual(scale.ticks(), [5e7, 1e8, 2e8])
        self.assertEqual([scale.tick_label(v, "") for v in scale.ticks()], ["5e7", "1e8", "2e8"])
        flat = chart_series.YScale([7.0, 7.0], log=True)
        self.assertGreaterEqual(len(flat.ticks()), 2)
        self.assertAlmostEqual(flat.frac(7.0), 0.5)

    def test_linear_scale_anchors_at_zero(self):
        scale = chart_series.YScale([5.0, 10.0])
        self.assertEqual(scale.lo, 0)
        self.assertEqual(len(scale.ticks()), 6)
        self.assertTrue(scale.usable(0))


class ReferenceTests(unittest.TestCase):
    def test_reference_values_and_sources(self):
        refs = reference_points.REFERENCES
        self.assertEqual(len({r.tag for r in refs}), len(refs))
        for ref in refs:
            self.assertIn(ref.kind, ("public", "own"))
            self.assertTrue(ref.source)
            self.assertTrue(ref.points and all(v > 0 for _, v in ref.points))
        forprime = dict(refs[0].points)
        self.assertAlmostEqual(forprime[25], 1e9 / (0.025 * 25 ** 2.5 + 310))
        self.assertEqual(sorted(forprime), list(range(19, 28)))

    def test_reference_series_are_dashed_and_name_their_kind(self):
        t = Translator("pl").t
        series = reference_points.reference_series(t)
        self.assertTrue(all(s.dashed for s in series))
        self.assertTrue(series[0].name.endswith("(" + t("bench.ref_public") + ")"))
        self.assertTrue(series[-1].name.endswith("(" + t("bench.ref_own") + ")"))

    def test_locales_have_the_new_keys(self):
        for lang in ("en", "pl"):
            strings = json.loads((ROOT / "primeatlas" / "core" / "locales"
                                  / f"strings_{lang}.json").read_text(encoding="utf-8"))
            for key in ("bench.show_references", "bench.log_scale", "bench.ref_public",
                        "bench.ref_own", "bench.axis_total_nps", "bench.axis_sieve_spw"):
                self.assertTrue(strings.get(key), f"{lang}: {key}")
            self.assertNotIn("v4_1", strings["bench.chart2_hint"])


class PdfTests(unittest.TestCase):
    def test_chart_ops_tag_both_engines_at_one_floor(self):
        series1 = chart_series.engine_series(benchmark.benchmark_engine_lines(ROWS, "growth"))
        series2 = chart_series.engine_series(benchmark.benchmark_engine_lines(ROWS, "write"))
        ops = "\n".join(chart_pdf.chart_ops(0, 0, 800, 140, series1, series2, fmt2="{:,.1f}"))
        self.assertIn("350,000,000 [v5]", ops)
        self.assertIn("50,000,000 [v4.1]", ops)
        self.assertIn("1.0 [v5]", ops)
        self.assertNotIn("[unknown]", ops)
        self.assertIn("(v4.1) Tj", ops)   # legend
        self.assertEqual(ops.count("(v5) Tj"), 1)   # one legend entry per engine
        self.assertNotIn("[3 2] 0 d", ops)
        self.assertEqual(ops.count("4.60 4.60 re f"),        # secondary-axis square markers
                         sum(len(s.points) for s in series2))

    def test_chart_ops_log_and_references(self):
        series = chart_series.engine_series(benchmark.benchmark_engine_lines(ROWS, "growth"))
        series += reference_points.reference_series(Translator("en").t)
        ops = "\n".join(chart_pdf.chart_ops(0, 0, 800, 140, series, log_y=True))
        self.assertIn("[3 2] 0 d", ops)
        self.assertIn("(1e8) Tj", ops)
        self.assertIn("[PARI forprime]", ops)

    def test_references_alone_still_draw_the_sieve_chart(self):
        rows = [_row(10, "", nps="4e7")]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "report.pdf"
            benchmark.render_benchmark_pdf(str(path), benchmark.aggregate_benchmark_growth(rows),
                                           ["base_exponent"], rows, references=True)
            text = path.read_bytes().decode("latin-1")
        self.assertIn("(sieve: n / s) Tj", text)
        self.assertIn(r"PARI forprime \(published\)", text)

    def _report(self, **kwargs):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "report.pdf"
            benchmark.render_benchmark_pdf(
                str(path), benchmark.aggregate_benchmark_growth(ROWS), ["base_exponent"], ROWS,
                sieve_points=benchmark.aggregate_benchmark_sieve_nps(ROWS),
                write_points=benchmark.aggregate_benchmark_write_mbps(ROWS), **kwargs)
            return path.read_bytes().decode("latin-1")

    def test_report_follows_the_toggles(self):
        plain = self._report()
        self.assertIn("[v4.1]", plain)
        self.assertIn("200 [v5]", plain)       # sieve chart, v5 line
        self.assertNotIn("PARI forprime", plain)
        self.assertNotIn("(1e8) Tj", plain)
        toggled = self._report(references=True, log_y=True)
        self.assertIn(r"PARI forprime \(published\)", toggled)          # legend, PDF-escaped
        # Chart 1: whole run with its write speed; chart 2: sieve alone, with the references.
        self.assertLess(toggled.index("(total: n / s) Tj"), toggled.index("(write: MB / s) Tj"))
        self.assertLess(toggled.index("(write: MB / s) Tj"), toggled.index("(sieve: n / s) Tj"))
        self.assertLess(toggled.index("(sieve: n / s) Tj"), toggled.index("(sieve: s / window) Tj"))
        self.assertLess(toggled.index("(sieve: n / s) Tj"),
                        toggled.index(r"PARI forprime \(published\)"))
        self.assertIn("PARI forprime: PARI/GP forprime, 1 thread", toggled)  # footnote
        self.assertIn("pari-dev-2409/msg00016", toggled)
        self.assertIn("(1e8) Tj", toggled)


class LineToggleTests(unittest.TestCase):
    """Each line (series x axis) of a chart can be hidden from its legend on its own."""

    def setUp(self):
        self.left = chart_series.engine_series({"v5": [(20, 1.0)], "v4.1": [(20, 2.0)]})
        self.right = chart_series.engine_series({"v5": [(20, 3.0)], "unknown": [(9, 1.0)]})
        self.refs = reference_points.reference_series(Translator("en").t)

    def test_legend_entries_name_the_axes_of_each_series(self):
        entries = chart_series.legend_entries(self.left + self.refs, self.right)
        self.assertEqual([(s.name, axes) for s, axes in entries][:3],
                         [("unknown", ("secondary",)), ("v4.1", ("primary",)),
                          ("v5", ("primary", "secondary"))])
        self.assertEqual([(s.name, axes) for s, axes in entries][3:],
                         [(r.name, ("primary",)) for r in self.refs])

    def test_visible_series_drop_hidden_lines_of_that_axis_only(self):
        hidden = {chart_series.line_key("primary", "v5")}
        self.assertEqual([s.name for s in chart_series.visible_series(self.left, hidden, "primary")],
                         ["v4.1"])
        self.assertEqual([s.name for s in
                          chart_series.visible_series(self.right, hidden, "secondary")],
                         ["unknown", "v5"])
        self.assertEqual(chart_series.visible_series(self.left, None, "primary"), self.left)

    def test_toggle_hides_all_or_shows_all(self):
        both = [chart_series.line_key("primary", "v5"), chart_series.line_key("secondary", "v5")]
        hidden = chart_series.toggle_lines(set(), both[:1])
        self.assertEqual(hidden, set(both[:1]))
        # A name click with one line hidden hides the other one too, then shows both.
        hidden = chart_series.toggle_lines(hidden, both)
        self.assertEqual(hidden, set(both))
        self.assertEqual(chart_series.toggle_lines(hidden, both), set())
        self.assertEqual(chart_series.toggle_lines(set(both), both[1:]), set(both[:1]))

    def test_report_leaves_out_hidden_lines(self):
        rows = ROWS
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "report.pdf"
            benchmark.render_benchmark_pdf(
                str(path), benchmark.aggregate_benchmark_growth(rows), ["base_exponent"], rows,
                sieve_points=benchmark.aggregate_benchmark_sieve_nps(rows), references=True,
                hidden_lines={"sieve": {chart_series.line_key("primary", "v5"),
                                        chart_series.line_key("primary",
                                                              self.refs[0].name)}})
            text = path.read_bytes().decode("latin-1")
        self.assertNotIn("(200 [v5]) Tj", text)          # sieve n/s of v5: hidden
        self.assertIn("(0.0500 [v5]) Tj", text)          # its sieve s/window: shown
        self.assertIn("(350,000,000 [v5]) Tj", text)     # whole-run chart: untouched
        self.assertNotIn("[" + self.refs[0].tag + "]) Tj", text)
        self.assertIn("[" + self.refs[1].tag + "]) Tj", text)


class TabTests(unittest.TestCase):
    def test_tab_hover_toggles_and_pdf_export(self):
        import tkinter as tk
        from tkinter import filedialog, messagebox
        from primeatlas.benchmark import benchmark_tab
        from primeatlas.core.theme import palette_for

        captured = {}
        original_hover = benchmark_tab._bind_chart_hover
        original_save = filedialog.asksaveasfilename
        originals = {name: getattr(messagebox, name) for name in ("showinfo", "showerror")}
        for name in originals:
            setattr(messagebox, name, lambda *a, **k: None)
        benchmark_tab._bind_chart_hover = (
            lambda canvas, points, *a: captured.__setitem__(str(canvas), list(points)))
        with tempfile.TemporaryDirectory() as portal:
            with open(os.path.join(portal, "benchmark_log.csv"), "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(ROWS[0]))
                writer.writeheader()
                writer.writerows(ROWS)
            pdf_path = os.path.join(portal, "report.pdf")
            filedialog.asksaveasfilename = lambda **kw: pdf_path
            root = tk.Tk()
            try:
                tab = benchmark_tab.BenchmarkTab(
                    root, lambda: portal, tk.StringVar(master=root), Translator("en"),
                    lambda *a, **k: None, palette_for("light"))
                tab.pack()
                tab.reload_benchmark_log()

                def hover_texts(canvas):
                    return [p[4] for p in captured.get(str(canvas), [])]

                tab._redraw_benchmark_chart()
                texts = hover_texts(tab.benchmark_chart)
                self.assertTrue(any(x.endswith("[v4.1]") for x in texts), texts)
                self.assertTrue(any(x.endswith("[v5]") for x in texts), texts)
                self.assertTrue(any(x.endswith("[unknown]") for x in texts), texts)
                self.assertFalse(any("PARI" in x for x in texts), texts)

                chart = tab.benchmark_chart
                squares = [i for i in chart.find_all() if chart.type(i) == "rectangle"]
                self.assertTrue(squares, "secondary-axis points are squares")
                legend = [chart.itemcget(i, "text") for i in chart.find_all()
                          if chart.type(i) == "text"]
                self.assertEqual(legend.count("v5"), 1)

                tab._redraw_benchmark_chart2()
                texts2 = hover_texts(tab.benchmark_chart2)
                self.assertTrue(any(x.endswith("[v5]") for x in texts2), texts2)

                self.assertFalse(any("PARI" in x for x in texts2), texts2)

                tab.references_var.set(True)
                tab.log_scale_var.set(True)
                tab._redraw_charts()
                self.assertFalse(any("PARI" in x for x in hover_texts(tab.benchmark_chart)))
                chart2 = tab.benchmark_chart2
                texts2 = hover_texts(chart2)
                self.assertTrue(any(x.endswith("[PARI forprime]") for x in texts2), texts2)
                dashed = [i for i in chart2.find_all()
                          if chart2.type(i) == "line" and chart2.itemcget(i, "dash")]
                self.assertTrue(dashed, "reference lines are dashed")
                labels = [chart2.itemcget(i, "text") for i in chart2.find_all()
                          if chart2.type(i) == "text"]
                self.assertIn("1e8", labels)

                tab._export_benchmark_pdf()
                text = Path(pdf_path).read_bytes().decode("latin-1")
                self.assertIn("PARI/GP forprime", text)
                self.assertIn("(1e8) Tj", text)

                # Legend clicks: the circle hides v5's left-axis line, the square its
                # right-axis line, the name toggles both; the other chart keeps its lines.
                tab.references_var.set(False)
                tab.log_scale_var.set(False)
                root.update()  # synthetic clicks reach canvas items only once mapped
                tab._redraw_charts()

                def click(canvas, tag):
                    items = canvas.find_withtag(tag)
                    self.assertTrue(items, tag)
                    x1, y1, x2, y2 = canvas.bbox(items[0])
                    canvas.event_generate("<Motion>", x=(x1 + x2) // 2, y=(y1 + y2) // 2)
                    canvas.event_generate("<Button-1>", x=(x1 + x2) // 2, y=(y1 + y2) // 2)
                    root.update()

                def v5_hover(canvas):
                    return sorted(p[6] for p in captured.get(str(canvas), [])
                                  if p[4].endswith("[v5]"))

                self.assertEqual(v5_hover(chart2), ["bench.axis_sieve_nps"] * 2
                                 + ["bench.axis_sieve_spw"] * 2)
                click(chart2, "legend:primary:v5")
                self.assertEqual(v5_hover(chart2), ["bench.axis_sieve_spw"] * 2)
                click(chart2, "legend:secondary:v5")
                self.assertEqual(v5_hover(chart2), [])
                # Every line hidden: the legend stays, so the lines can come back.
                click(chart2, "legend:secondary:v4.1")
                click(chart2, "legend:primary:v4.1")
                self.assertEqual(captured.get(str(chart2)), [])
                self.assertTrue(chart2.find_withtag("legend:name:v5"))
                hint = [chart2.itemcget(i, "text") for i in chart2.find_all()
                        if chart2.type(i) == "text"]
                self.assertIn(Translator("en").t("bench.all_lines_hidden"), hint)
                click(chart2, "legend:name:v5")
                self.assertEqual(len(v5_hover(chart2)), 4)
                self.assertEqual(len([p for p in captured[str(tab.benchmark_chart)]
                                      if p[4].endswith("[v5]")]), 3)
                # Hidden lines survive a reload and leave the PDF.
                tab.reload_benchmark_log()
                tab._redraw_charts()
                self.assertFalse(any(p[4].endswith("[v4.1]")
                                     for p in captured.get(str(chart2), [])))
                tab._export_benchmark_pdf()
                text = Path(pdf_path).read_bytes().decode("latin-1")
                self.assertIn("(200 [v5]) Tj", text)
                self.assertNotIn("(100 [v4.1]) Tj", text)
            finally:
                root.destroy()
                benchmark_tab._bind_chart_hover = original_hover
                filedialog.asksaveasfilename = original_save
                for name, fn in originals.items():
                    setattr(messagebox, name, fn)


if __name__ == "__main__":
    unittest.main()
