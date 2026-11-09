"""Benchmark charts choose their points per group of runs and put them on a floor or a width
axis (primeatlas/benchmark/chart_points.py, benchmark.benchmark_series(), the "floor" filter
dimension of chart_filter.py).

Floor axis, last run: the old reduction (last row per floor and line). MIN/MAX: the lowest or
highest value of the group, ties to the later run. SELECTED: the selected run's group shows
that run, every other group its last run; a selected run outside the kept rows changes
nothing. ALL: every run its own point, in log order, repeated runs one above the other, the
widths of one x joined in the point's note. Width axis: x = log10(numbers_processed), one line per engine build and floor, a run
without a width left out and counted; the same width twice on a line is one group. Lines of
one engine on different floors share its hue in distinct shades. Breaking attempts: unknown
modes, a row without a floor, a zero or blank width, one point, every choice on a one-run
group, there and back between the modes. Pure, any platform:
    python unitTests/test_benchmark_chart_points.py
"""
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from primeatlas.benchmark import benchmark, chart_filter, chart_points as cp  # noqa: E402
from primeatlas.benchmark.chart_series import ENGINE_COLORS  # noqa: E402
from primeatlas.core.i18n import Translator  # noqa: E402

W = 10_000_000


def _row(floor, numbers, sieve, version="v7.1", engine="v7", ts=""):
    return dict(run_timestamp_utc=ts, base_exponent=str(floor), engine=engine,
                engine_version=version, threads="24", write_threads="8", instance_of_n="1/1",
                numbers_processed=str(numbers) if numbers is not None else "",
                windows_written=str((numbers or 0) // W), sieve_seconds=str(sieve),
                loop_numbers_per_second=str((numbers or 0) / (sieve + 1)),
                write_seconds="1", bytes_written="1000000")


# f29: the three widths of the live runs; f28: two runs at one width (min/max/selected).
ROWS = [
    _row(29, 10 ** 10, 2262.7, ts="a"),
    _row(29, 10 ** 11, 1412.5, ts="b"),
    _row(29, 2 * 10 ** 11, 1159.3, ts="c"),
    _row(28, 10 ** 10, 717.0, ts="d"),
    _row(28, 10 ** 10, 702.0, ts="e"),
    _row(28, 10 ** 10, 748.0, ts="f"),
    _row(27, None, 50.0, ts="g"),
]
LINE = "v7.1, 24 thr, write 8"
NPS = {r["run_timestamp_utc"]: int(r["numbers_processed"]) / float(r["sieve_seconds"])
       for r in ROWS if r["numbers_processed"]}


def lines(rows, view, metric="sieve"):
    return {s.name: s.points for s in benchmark.benchmark_series(rows, metric, view)}


class FloorAxis(unittest.TestCase):
    def test_last_is_the_old_reduction(self):
        got = lines(ROWS, cp.DEFAULT)
        self.assertEqual(got, {LINE: [(28, NPS["f"]), (29, NPS["c"])]})
        self.assertEqual(got, lines(ROWS, None), "no view = the default")

    def test_min_max_pick_by_value(self):
        self.assertEqual(lines(ROWS, cp.PointView(choice=cp.MIN))[LINE],
                         [(28, NPS["f"]), (29, NPS["a"])])
        self.assertEqual(lines(ROWS, cp.PointView(choice=cp.MAX))[LINE],
                         [(28, NPS["e"]), (29, NPS["c"])])

    def test_tie_goes_to_the_later_run(self):
        a, b = _row(25, 10 ** 10, 10.0, ts="x"), _row(25, 10 ** 10, 10.0, ts="y")
        for choice in (cp.MIN, cp.MAX, cp.LAST):
            pts = cp.chart_points([a, b], lambda r: 1.0, cp.PointView(choice=choice))
            self.assertIs(pts[LINE][0][2], b, choice)

    def test_selected(self):
        selected = ROWS[4]
        got = lines(ROWS, cp.PointView(choice=cp.SELECTED, selected=selected))[LINE]
        self.assertEqual(got, [(28, NPS["e"]), (29, NPS["c"])], "own group shows it, rest last")
        none = lines(ROWS, cp.PointView(choice=cp.SELECTED))[LINE]
        self.assertEqual(none, lines(ROWS, cp.DEFAULT)[LINE], "nothing selected = last")
        outside = dict(ROWS[4])   # equal content, not the same run
        self.assertEqual(lines(ROWS, cp.PointView(choice=cp.SELECTED, selected=outside))[LINE],
                         lines(ROWS, cp.DEFAULT)[LINE], "identity, not equality")
        kept = [r for r in ROWS if r is not selected]
        self.assertEqual(lines(kept, cp.PointView(choice=cp.SELECTED, selected=selected))[LINE],
                         lines(kept, cp.DEFAULT)[LINE], "filtered out: no effect")

    def test_one_run_group_every_choice(self):
        one = [_row(26, 10 ** 10, 100.0)]
        for choice in cp.CHOICES:
            self.assertEqual(lines(one, cp.PointView(choice=choice, selected=one[0])),
                             {LINE: [(26, 10 ** 8)]}, choice)

    def test_all_keeps_every_run(self):
        got = lines(ROWS, cp.PointView(choice=cp.ALL))[LINE]
        self.assertEqual(got, [(28, NPS["d"]), (28, NPS["e"]), (28, NPS["f"]),
                               (29, NPS["a"]), (29, NPS["b"]), (29, NPS["c"])])
        width = lines(ROWS, cp.PointView(cp.X_WIDTH, cp.ALL))
        self.assertEqual(len(width[LINE + " @ f28"]), 3, "same width: three points")
        notes = benchmark.benchmark_line_widths(ROWS, "sieve", cp.PointView(choice=cp.ALL))
        self.assertEqual(notes[LINE][29], "10^10/10^11/2x10^11")
        self.assertEqual(notes[LINE][28], "10^10")

    def test_selected_marks(self):
        selected = ROWS[4]
        for choice, want in ((cp.SELECTED, {(LINE, 28, NPS["e"])}),
                             (cp.ALL, {(LINE, 28, NPS["e"])}),
                             (cp.LAST, set())):
            self.assertEqual(benchmark.selected_marks(
                ROWS, "sieve", cp.PointView(choice=choice, selected=selected)), want, choice)
        self.assertEqual(benchmark.selected_marks(ROWS, "sieve", cp.DEFAULT), set())

    def test_mixed_width_note_only_on_floor_axis(self):
        rows = [_row(29, 10 ** 10, 1.0), _row(29, 10 ** 11, 1.0, version="v7.0")]
        self.assertEqual(benchmark.mixed_width_floors(rows, "sieve"), [29])
        self.assertEqual(benchmark.mixed_width_floors(rows, "sieve",
                                                      cp.PointView(x_mode=cp.X_WIDTH)), [])


class WidthAxis(unittest.TestCase):
    VIEW = cp.PointView(x_mode=cp.X_WIDTH)

    def test_one_line_per_floor_x_is_log_width(self):
        got = lines(ROWS, self.VIEW)
        self.assertEqual(sorted(got), [LINE + " @ f28", LINE + " @ f29"])
        f29 = got[LINE + " @ f29"]
        self.assertEqual([round(x, 6) for x, _ in f29], [10.0, 11.0, round(math.log10(2e11), 6)])
        self.assertEqual([y for _, y in f29], [NPS["a"], NPS["b"], NPS["c"]])
        self.assertEqual(got[LINE + " @ f28"], [(10.0, NPS["f"])], "same width = one group")

    def test_choice_applies_per_width(self):
        got = lines(ROWS, self.VIEW._replace(choice=cp.MAX))[LINE + " @ f28"]
        self.assertEqual(got, [(10.0, NPS["e"])])

    def test_width_less_runs_left_out_and_counted(self):
        value = benchmark.line_value("growth")
        self.assertEqual(cp.unplaced(ROWS, value, self.VIEW), 1)
        self.assertEqual(cp.unplaced(ROWS, value, cp.DEFAULT), 0)
        zero = [_row(26, 0, 1.0)]
        self.assertEqual(lines(zero, self.VIEW, "growth"), {})
        self.assertEqual(cp.unplaced(zero, value, self.VIEW), 1)

    def test_row_without_floor_ignored(self):
        bad = dict(ROWS[0], base_exponent="")
        self.assertEqual(lines([bad], self.VIEW), {})
        self.assertEqual(cp.unplaced([bad], benchmark.line_value("growth"), self.VIEW), 0)

    def test_there_and_back(self):
        before = lines(ROWS, cp.DEFAULT)
        lines(ROWS, self.VIEW)
        self.assertEqual(lines(ROWS, cp.DEFAULT), before)

    def test_shades_per_floor(self):
        series = benchmark.benchmark_series(ROWS, "sieve", self.VIEW)
        colors = {s.name: s.color for s in series}
        self.assertEqual(colors[LINE + " @ f28"], ENGINE_COLORS["v7"], "first floor: the hue")
        self.assertNotEqual(colors[LINE + " @ f29"], ENGINE_COLORS["v7"])
        again = {s.name: s.color for s in benchmark.benchmark_series(ROWS, "growth", self.VIEW)}
        self.assertEqual(again, colors, "same floors, same shades on every chart")
        self.assertTrue(all(not s.dashed for s in series), "dashes stay for references")

    def test_labels(self):
        self.assertEqual(cp.x_label(11.0, cp.X_WIDTH), "10^11")
        self.assertEqual(cp.x_label(math.log10(2e11), cp.X_WIDTH), "2x10^11")
        self.assertEqual(cp.x_label(math.log10(1.5e10), cp.X_WIDTH), "1.5x10^10")
        self.assertEqual(cp.x_label(28, cp.X_FLOOR), "28")


class Shade(unittest.TestCase):
    def test_distinct_and_valid(self):
        got = [cp.shade("#ff00ff", i) for i in range(6)]
        self.assertEqual(len(set(got)), 6)
        self.assertEqual(got[0], "#ff00ff")
        for c in got:
            self.assertRegex(c, r"^#[0-9a-f]{6}$")


class Breaking(unittest.TestCase):
    def test_unknown_modes(self):
        with self.assertRaises(ValueError):
            cp.chart_points(ROWS, lambda r: 1.0, cp.PointView(x_mode="time"))
        with self.assertRaises(ValueError):
            cp.chart_points(ROWS, lambda r: 1.0, cp.PointView(choice="mean"))


class FloorFilter(unittest.TestCase):
    def test_floor_dimension(self):
        self.assertIn("floor", chart_filter.DIMENSIONS)
        rows = ROWS + [_row(9, 10 ** 9, 1.0)]
        self.assertEqual(chart_filter.dimension_values(rows, "floor"), ["9", "27", "28", "29"])
        kept = chart_filter.apply(rows, {"floor": {"28", "29"}})
        self.assertEqual({r["base_exponent"] for r in kept}, {"28", "29"})
        t = Translator("en").t
        self.assertIn("28, 29", chart_filter.summary({"floor": {"29", "28"}}, t))


class TabTests(unittest.TestCase):
    """The Filter window sets the x axis and the point choices; the table selects the run."""

    def _tab(self, rows, body):
        import csv
        import os
        import tempfile
        import tkinter as tk
        from primeatlas.benchmark import benchmark_tab
        from primeatlas.core.theme import palette_for

        captured = {}
        original = benchmark_tab._bind_chart_hover
        benchmark_tab._bind_chart_hover = (
            lambda canvas, points, *a: captured.__setitem__(str(canvas), list(points)))
        with tempfile.TemporaryDirectory() as portal:
            with open(os.path.join(portal, "benchmark_log.csv"), "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            root = tk.Tk()
            try:
                tab = benchmark_tab.BenchmarkTab(
                    root, lambda: portal, tk.StringVar(master=root), Translator("en"),
                    lambda *a, **k: None, palette_for("light"))
                tab.pack(fill="both", expand=True)
                tab.reload_benchmark_log()
                root.update()

                def points(canvas):
                    return sorted((round(p[2], 6), p[3]) for p in captured.get(str(canvas), [])
                                  if p[7] == "primary")
                body(tab, root, points)
            finally:
                root.destroy()
                benchmark_tab._bind_chart_hover = original

    @staticmethod
    def _row_item(tab, floor, ts):
        tree = tab.benchmark_tree
        node = next(n for n in tree.get_children("")
                    if tree.item(n, "text").startswith(f"10p{floor} "))
        tab._populate_benchmark_floor_node(node)
        return next(i for i in tree.get_children(node)
                    if tree.item(i, "text").startswith(ts + " "))

    def test_window_axis_and_choices(self):
        growth = {r["run_timestamp_utc"]: float(r["loop_numbers_per_second"]) for r in ROWS}

        def body(tab, root, points):
            window = tab._open_filter_window()
            self.assertEqual(points(tab.benchmark_chart2), [(28, NPS["f"]), (29, NPS["c"])],
                             "floor axis, last run")
            tab._x_view, tab._x_level, tab._x_base = (27.5, 29.5), 2, (28, 29)
            tab._y_pins["sieve"] = {"primary": (1.0, None)}
            window.x_mode_var.set(cp.X_WIDTH)
            window.apply_points()
            root.update()
            self.assertEqual(tab._x_mode, cp.X_WIDTH)
            self.assertIsNone(tab._x_view, "a new x axis shows the whole charts")
            self.assertEqual(tab._y_pins["sieve"], {"primary": (1.0, None)}, "pins kept")
            xs = {x for x, _y in points(tab.benchmark_chart2)}
            self.assertEqual(xs, {10.0, 11.0, round(math.log10(2e11), 6)})
            canvas = tab.benchmark_chart2
            texts = {canvas.itemcget(i, "text") for i in canvas.find_all()
                     if canvas.type(i) == "text"}
            self.assertTrue({"10^10", "10^11", "2x10^11",
                             Translator("en").t("bench.axis_width")} <= texts, texts)
            self.assertIn("1 run(s) without a known width", tab.mixed_widths_vars["run"].get())
            self.assertIn("X axis: Width", tab.filter_summary_var.get())
            window.choice_vars["sieve"].set(cp.MAX)
            window.apply_points()
            root.update()
            self.assertIn((10.0, NPS["e"]), points(tab.benchmark_chart2), "f28: the max run")
            self.assertIn("Max", tab.filter_summary_var.get())
            self.assertIn((10.0, growth["f"]), points(tab.benchmark_chart),
                          "the run chart keeps its own choice (last)")
            window.x_mode_var.set(cp.X_FLOOR)
            window.apply_points()
            root.update()
            self.assertEqual(points(tab.benchmark_chart2), [(28, NPS["e"]), (29, NPS["c"])],
                             "there and back: floor axis, max per floor")
            self.assertEqual(tab.mixed_widths_vars["run"].get(), "")
            window.destroy()
        self._tab(ROWS, body)

    def test_selected_run_drives_all_three_charts(self):
        rows = [dict(r, max_child_rss_mb=str(100 + i)) for i, r in enumerate(ROWS)]

        def rings(canvas):
            return len(canvas.find_withtag("selected_mark"))

        def body(tab, root, points):
            window = tab._open_filter_window()
            window.choice_vars["ram"].set(cp.ALL)
            window.apply_points()
            root.update()
            self.assertEqual(rings(tab.benchmark_chart2), 0, "nothing selected: no ring")
            item = self._row_item(tab, 28, "d")
            tab.benchmark_tree.selection_set(item)
            root.update()
            self.assertIs(tab._selected_run, tab._tree_item_rows[item])
            self.assertEqual(tab._point_choice, {"run": cp.SELECTED, "sieve": cp.SELECTED,
                                                 "ram": cp.ALL}, "a click switches, ALL stays")
            self.assertEqual({c: v.get() for c, v in window.choice_vars.items()},
                             tab._point_choice, "the open window shows it")
            self.assertIn("Selected", tab.filter_summary_var.get())
            for canvas in (tab.benchmark_chart, tab.benchmark_chart2, tab.benchmark_chart3):
                self.assertGreaterEqual(rings(canvas), 1, "its points are ringed")
            self.assertIn((28, NPS["d"]), points(tab.benchmark_chart2))
            self.assertIn((28, float(rows[3]["loop_numbers_per_second"])),
                          points(tab.benchmark_chart), "the run chart too")
            self.assertIn((28, 103.0), points(tab.benchmark_chart3), "and the RAM chart")
            window.choice_vars["sieve"].set(cp.LAST)
            window.apply_points()
            root.update()
            self.assertEqual(rings(tab.benchmark_chart2), 0, "back to Last: f28 shows run f")
            window.destroy()
        self._tab(rows, body)

    def test_arrows_turn_pages_and_select(self):
        from primeatlas.benchmark.benchmark import BENCHMARK_PAGE_SIZE
        n = BENCHMARK_PAGE_SIZE
        rows = [_row(26, 10 ** 10, 100.0 + i, ts=f"r{i:03d}") for i in range(n + 5)]

        def body(tab, root, points):
            tab._point_choice = {chart: cp.SELECTED for chart in tab._point_choice}
            tree = tab.benchmark_tree
            item = self._row_item(tab, 26, "r003")
            tree.selection_set(item)
            tree.focus(item)
            root.update()
            self.assertEqual(tab._selected_run["run_timestamp_utc"], "r003")
            self.assertEqual(tab._turn_row_page(1), "break")
            root.update()
            self.assertEqual(tab._selected_run["run_timestamp_utc"], f"r{n:03d}")
            self.assertEqual(points(tab.benchmark_chart2), [(26, 10 ** 10 / (100.0 + n))])
            self.assertEqual(tab._turn_row_page(1), "break", "no page after the last")
            root.update()
            self.assertEqual(tab._selected_run["run_timestamp_utc"], f"r{n:03d}")
            tab._turn_row_page(-1)
            root.update()
            self.assertEqual(tab._selected_run["run_timestamp_utc"], "r000")
            tree.focus(tree.parent(tree.focus()))
            self.assertIsNone(tab._turn_row_page(1), "on a floor header the keys stay Tk's")
        self._tab(rows, body)

    def test_pdf_follows_the_axis(self):
        import os
        import tempfile

        def body(tab, root, points):
            tab._set_points(cp.X_WIDTH, {})
            with tempfile.TemporaryDirectory() as out:
                path = os.path.join(out, "r.pdf")
                tab._render_pdf(path)
                text = Path(path).read_bytes().decode("latin-1")
            self.assertIn("(2x10^11) Tj", text)
            self.assertIn("(numbers sieved \\(log\\)) Tj", text)
            self.assertIn("@ f29", text)
        self._tab(ROWS, body)


class HoverTests(unittest.TestCase):
    def test_tooltip_names_the_x(self):
        import tkinter as tk
        from primeatlas.benchmark.chart_hover import _bind_chart_hover
        t = Translator("en").t
        root = tk.Tk()
        try:
            canvas = tk.Canvas(root, width=400, height=200)
            canvas.pack()
            root.update()
            for mode, x, want in ((cp.X_WIDTH, math.log10(2e11), "2x10^11"),
                                  (cp.X_FLOOR, 28, "28")):
                point = (100, 100, x, 5.0, "{:,.0f}", "#ff00ff", "bench.axis_nps", "primary")
                _bind_chart_hover(canvas, [point], t, "#000000", "#ffffff", 400, 200, mode)
                canvas.event_generate("<Motion>", x=100, y=100)
                root.update()
                texts = [canvas.itemcget(i, "text") for i in canvas.find_withtag("hover_tip")
                         if canvas.type(i) == "text"]
                self.assertIn(f"{t(cp.AXIS_TITLE_KEYS[mode])} {want}: 5", " ".join(texts))
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
