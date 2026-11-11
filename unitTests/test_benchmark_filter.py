"""Benchmark charts filter the runs they compare: run purpose (benchmark or storage), engine
build, sieve threads, write threads, range width (primeatlas/benchmark/chart_filter.py and the
tab's Filter window).

Run purpose: a row's run_purpose, else write_files 0 for a benchmark (count-only rows logged
before the column), else storage; the window and the summary show it translated; selecting
benchmark keeps only the benchmark runs on the charts and storage only the storage ones.

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

from app_sandbox import fresh_ui_store  # noqa: E402

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


PURPOSE_ROWS = [
    dict(ROWS[0], run_timestamp_utc="p1", run_purpose="benchmark", write_files="0"),
    dict(ROWS[1], run_timestamp_utc="p2", run_purpose="storage", write_files="1"),
    dict(ROWS[2], run_timestamp_utc="p3", write_files="0"),
    dict(ROWS[3], run_timestamp_utc="p4", write_files="1"),
    dict(ROWS[4], run_timestamp_utc="p5", engine="v4.1"),
]


class PurposeTests(unittest.TestCase):
    def test_purpose_values_and_fallback(self):
        self.assertEqual([chart_filter.row_value(r, "purpose") for r in PURPOSE_ROWS],
                         ["benchmark", "storage", "benchmark", "storage", "storage"])
        self.assertEqual(chart_filter.dimension_values(PURPOSE_ROWS, "purpose"),
                         ["benchmark", "storage"])
        self.assertEqual(chart_filter.DIMENSIONS[0], "purpose", "purpose is the first dimension")
        native = [dict(ROWS[4], run_purpose="", write_files=""),
                  dict(ROWS[4], engine="primesieve_print", run_purpose="storage", write_files="1"),
                  dict(ROWS[4], engine="pseudosquares_print", run_purpose="benchmark")]
        self.assertEqual([chart_filter.row_value(r, "purpose") for r in native],
                         ["benchmark"] * 3,
                         "a native program's run is a benchmark, an old print row too")

    def test_apply_both_ways(self):
        ts = lambda rows: [r["run_timestamp_utc"] for r in rows]
        self.assertEqual(ts(chart_filter.apply(PURPOSE_ROWS, {"purpose": {"benchmark"}})),
                         ["p1", "p3"])
        self.assertEqual(ts(chart_filter.apply(PURPOSE_ROWS, {"purpose": {"storage"}})),
                         ["p2", "p4", "p5"])
        self.assertEqual(chart_filter.apply(PURPOSE_ROWS, {"purpose": {"benchmark", "storage"}}),
                         PURPOSE_ROWS)

    def test_translated_labels(self):
        for lang, words in (("en", ("Benchmark", "Storage")), ("pl", ("Benchmark", "Magazyn"))):
            t = Translator(lang).t
            self.assertEqual([chart_filter.value_label("purpose", v, t)
                              for v in ("benchmark", "storage")], list(words))
            self.assertIn(words[0], chart_filter.summary({"purpose": {"benchmark"}}, t))
            self.assertNotIn("benchmark,", chart_filter.summary({"purpose": {"benchmark"}}, t))
        t = Translator("en").t
        self.assertEqual(chart_filter.value_label("threads", "15 thr", t), "15 thr")
        self.assertEqual(chart_filter.value_label("threads", "", t), t("bench.filter_blank"))


class PurposeExportTests(unittest.TestCase):
    def test_csv_export_lists_only_the_kept_purpose(self):
        from primeatlas.benchmark import report_export
        fields = sorted({k for r in PURPOSE_ROWS for k in r})
        for purpose, kept in (("benchmark", {"p1", "p3"}), ("storage", {"p2", "p4", "p5"})):
            text = report_export.render("csv", fields, PURPOSE_ROWS, Translator("en"),
                                        selection={"purpose": {purpose}})
            present = {ts for ts in ("p1", "p2", "p3", "p4", "p5") if f"{ts}," in text
                       or f",{ts}" in text}
            self.assertEqual(present, kept, f"CSV export under purpose {purpose}")


class ToggleTests(unittest.TestCase):
    """All or single values: a dimension starts at All (absent from the selection); the
    first value clicked leaves only it, each further click adds or removes one value;
    removing the last value or clicking All goes back to All."""

    def test_sequence_there_and_back(self):
        sel = {}
        sel = chart_filter.toggle_value(sel, "width", "10^11")
        self.assertEqual(sel, {"width": {"10^11"}}, "first click from All: only that value")
        sel = chart_filter.toggle_value(sel, "width", "10^10")
        self.assertEqual(sel, {"width": {"10^10", "10^11"}}, "second click adds")
        sel = chart_filter.toggle_value(sel, "width", "10^11")
        self.assertEqual(sel, {"width": {"10^10"}}, "click on a selected value removes it")
        sel = chart_filter.toggle_value(sel, "width", "10^10")
        self.assertEqual(sel, {}, "removing the last value goes back to All")
        sel = chart_filter.toggle_value(sel, "width", "10^10")
        sel = chart_filter.select_all(sel, "width")
        self.assertEqual(sel, {}, "All clears the dimension")

    def test_dimensions_independent_and_input_untouched(self):
        start = {"threads": {"15 thr"}}
        sel = chart_filter.toggle_value(start, "width", "10^11")
        self.assertEqual(sel, {"threads": {"15 thr"}, "width": {"10^11"}})
        self.assertEqual(start, {"threads": {"15 thr"}}, "the given selection is not changed")
        sel2 = chart_filter.toggle_value(sel, "width", "2x10^11")
        self.assertEqual(sel["width"], {"10^11"}, "sets are copied, not shared")
        self.assertEqual(chart_filter.select_all(sel2, "threads"), {"width": {"10^11", "2x10^11"}})
        self.assertEqual(chart_filter.select_all({}, "width"), {}, "All on All: nothing changes")

    def test_every_value_selected_by_hand_stays_a_choice(self):
        sel = {}
        for value in ("10^10", "10^11", "2x10^11"):
            sel = chart_filter.toggle_value(sel, "width", value)
        self.assertEqual(sel, {"width": {"10^10", "10^11", "2x10^11"}},
                         "a hand-picked full set is kept, not turned into All")


class WindowTests(unittest.TestCase):
    """The Filter window: every value checkbox is clickable without enabling its dimension;
    each dimension shows All checked at first; clicks follow ToggleTests and drive the tab;
    reopening shows the tab's selection; Clear goes back to All everywhere."""

    def test_clicks(self):
        import tkinter as tk
        from primeatlas.benchmark import benchmark_tab
        from primeatlas.core.theme import palette_for

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
                tab.reload_benchmark_log()
                window = tab._open_filter_window()
                root.update()

                def checked(button):
                    return "selected" in button.state()

                def shown(dim):
                    return ({v for v, b in window.value_buttons[dim].items() if checked(b)},
                            checked(window.all_buttons[dim]))

                for dim in chart_filter.DIMENSIONS:
                    self.assertTrue(all(str(b.cget("state")) == "normal"
                                        for b in window.value_buttons[dim].values()),
                                    f"{dim}: values clickable at once")
                    self.assertEqual(shown(dim), (set(), True), f"{dim}: All at first")
                buttons = window.value_buttons["width"]
                buttons["10^11"].invoke()
                self.assertEqual(tab._filter_selection, {"width": {"10^11"}})
                self.assertEqual(shown("width"), ({"10^11"}, False))
                buttons["10^10"].invoke()
                self.assertEqual(shown("width"), ({"10^10", "10^11"}, False))
                buttons["10^11"].invoke()
                buttons["10^10"].invoke()
                self.assertEqual(tab._filter_selection, {}, "last value off: All")
                self.assertEqual(shown("width"), (set(), True))
                buttons["2x10^11"].invoke()
                window.value_buttons["threads"]["15 thr"].invoke()
                window.all_buttons["width"].invoke()
                self.assertEqual(tab._filter_selection, {"threads": {"15 thr"}}, "All on width")
                self.assertEqual(shown("width"), (set(), True))
                window.all_buttons["threads"].invoke()
                window.all_buttons["threads"].invoke()
                self.assertEqual(shown("threads"), (set(), True),
                                 "clicking a checked All keeps All")
                window.value_buttons["threads"]["24 thr"].invoke()
                window.destroy()
                window = tab._open_filter_window()
                root.update()
                self.assertEqual(shown("threads"), ({"24 thr"}, False), "reopened: tab's choice")
                window._clear()
                self.assertEqual(tab._filter_selection, {})
                self.assertTrue(all(shown(d) == (set(), True) for d in chart_filter.DIMENSIONS))
                window.destroy()
            finally:
                root.destroy()


class WindowSizeTests(unittest.TestCase):
    """The Filter window on a log with many values: it opens no larger than the screen, its
    Clear and Close buttons stay inside the window at any height down to its minimum, the
    dimensions scroll once they do not fit and the last choice can be scrolled into view; it
    cannot be made narrower than its content."""

    def test_fit_size(self):
        from primeatlas.benchmark.benchmark_filter import fit_size
        self.assertEqual(fit_size(600, 500, 1920, 1080), (600, 500), "fits: content size")
        w, h = fit_size(600, 3000, 1920, 1080)
        self.assertEqual(w, 600)
        self.assertTrue(0 < h < 1080, f"taller than the screen: capped ({h})")
        w, h = fit_size(4000, 500, 1920, 1080)
        self.assertTrue(0 < w < 1920 and h == 500, f"wider than the screen: capped ({w})")
        self.assertTrue(all(v > 0 for v in fit_size(600, 3000, 200, 150)), "tiny screen")

    def test_buttons_stay_and_body_scrolls(self):
        import tkinter as tk
        from primeatlas.benchmark import benchmark_tab
        from primeatlas.core.theme import palette_for

        rows = [_row(f"v{e}", f"v{e}.{k}", str(t), str(k + 1), 10 ** (7 + k), 1.0,
                     floor=f, ts=f"{e}{k}{t}{f}")
                for e in range(4, 8) for k in range(4) for t in (8, 16, 24)
                for f in range(5, 34, 3)]
        with tempfile.TemporaryDirectory() as portal:
            with open(os.path.join(portal, "benchmark_log.csv"), "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            root = tk.Tk()
            try:
                fresh_ui_store()
                tab = benchmark_tab.BenchmarkTab(
                    root, lambda: portal, tk.StringVar(master=root), Translator("en"),
                    lambda *a, **k: None, palette_for("light"))
                tab.reload_benchmark_log()
                window = tab._open_filter_window()
                root.update()
                self.assertLessEqual(window.winfo_height(), window.winfo_screenheight(),
                                     "opens no taller than the screen")
                self.assertGreaterEqual(window.winfo_rooty(), 0, "top edge on the screen")
                min_w, min_h = window.minsize()
                self.assertGreaterEqual(min_w, window.page.body.winfo_reqwidth(),
                                        "cannot be narrowed past its content")

                def inside(widget):
                    top = widget.winfo_rooty() - window.winfo_rooty()
                    return top >= 0 and top + widget.winfo_height() <= window.winfo_height()

                for height in (window.page.body.winfo_reqheight() // 2, 400, min_h):
                    window.geometry(f"{max(min_w, 700)}x{height}")
                    root.update()
                    for button in (window.clear_button, window.close_button):
                        self.assertTrue(inside(button), f"height {height}: button inside")
                    self.assertTrue(window.page.scrolls(), f"height {height}: body scrolls")
                    last = window.last_choice
                    window.page._on_scrollbar("moveto", 1.0)  # the scrollbar dragged to the end
                    root.update()
                    canvas = window.page.canvas
                    top = last.winfo_rooty() - canvas.winfo_rooty()
                    self.assertTrue(0 <= top and top + last.winfo_height()
                                    <= canvas.winfo_height(),
                                    f"height {height}: last choice scrolls into view")
                window.destroy()
            finally:
                root.destroy()


class PureTests(unittest.TestCase):
    def test_values(self):
        self.assertEqual(chart_filter.dimension_values(ROWS, "threads"),
                         ["15 thr", "24 thr", "15x24 thr"])
        self.assertEqual(chart_filter.dimension_values(ROWS, "width"), ["10^10", "10^11", "2x10^11"])
        self.assertEqual(chart_filter.dimension_values(ROWS, "write_threads"), ["", "1", "8"])
        self.assertIn("primesieve count 12.15",
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
        self.assertEqual(lines["primesieve count 12.15, 15 thr"], [(19, 10 ** 10 / 3.2)],
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
                fresh_ui_store()
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
                window.value_buttons["threads"]["15 thr"].invoke()
                window.value_buttons["width"]["10^11"].invoke()
                root.update()
                self.assertEqual(tags(tab.benchmark_chart2),
                                 {"v6.0, 15 thr, write 8", "v5.1, 15 thr, write 1",
                                  "primesieve count 12.15, 15 thr"})
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


class TableTests(unittest.TestCase):
    """The tab's table lists the runs the filter keeps: both purposes = every run, one
    purpose = only its runs, a floor with no kept run is left out, nothing kept = one
    explanatory row; a filter change rebuilds it at once, there and back."""

    def test_table_follows_the_filter(self):
        import tkinter as tk
        from primeatlas.benchmark import benchmark_tab
        from primeatlas.core.theme import palette_for

        rows = [dict(r, base_exponent="19") for r in PURPOSE_ROWS[:3]] + [
            dict(PURPOSE_ROWS[3], base_exponent="20"), dict(PURPOSE_ROWS[4], base_exponent="20")]
        fields = sorted({k for r in rows for k in r}, key=lambda k: (k != "run_timestamp_utc", k))
        with tempfile.TemporaryDirectory() as portal:
            with open(os.path.join(portal, "benchmark_log.csv"), "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            root = tk.Tk()
            try:
                fresh_ui_store()
                tab = benchmark_tab.BenchmarkTab(
                    root, lambda: portal, tk.StringVar(master=root), Translator("en"),
                    lambda *a, **k: None, palette_for("light"))
                tab.pack(fill="both", expand=True)
                tab.reload_benchmark_log()
                root.update()
                tree = tab.benchmark_tree

                def floors():
                    return [tree.item(n, "text") for n in tree.get_children("")]

                def opened_timestamps(floor_text_prefix):
                    node = next(n for n in tree.get_children("")
                                if tree.item(n, "text").startswith(floor_text_prefix))
                    tree.focus(node)
                    tab._populate_benchmark_floor_node(node)
                    return sorted(r["run_timestamp_utc"]
                                  for r in tab._benchmark_floor_state[node]["rows"])

                t = Translator("en").t
                all_floors = [t("bench.floor_measurements", base_exponent=19, count=3),
                              t("bench.floor_measurements", base_exponent=20, count=2)]
                self.assertEqual(floors(), all_floors, "no filter: every run")
                for selection, expected, opened in (
                        ({"purpose": {"benchmark", "storage"}}, all_floors, ["p1", "p2", "p3"]),
                        ({"purpose": {"storage"}},
                         [t("bench.floor_measurements", base_exponent=19, count=1),
                          t("bench.floor_measurements", base_exponent=20, count=2)], ["p2"]),
                        ({"purpose": {"benchmark"}},
                         [t("bench.floor_measurements", base_exponent=19, count=2)],
                         ["p1", "p3"]),
                        ({}, all_floors, ["p1", "p2", "p3"])):
                    tab._set_filter(selection)
                    root.update()
                    self.assertEqual(floors(), expected, f"table under {selection}")
                    self.assertEqual(opened_timestamps("10p19"), opened,
                                     f"floor 19 rows under {selection}")
                tab._set_filter({"purpose": set()})
                root.update()
                self.assertEqual(floors(), [t("bench.filter_no_rows")],
                                 "nothing kept: one explanatory row")
                tab._set_filter({})
                root.update()
                self.assertEqual(floors(), all_floors, "back to every run")
            finally:
                root.destroy()


if __name__ == "__main__":
    unittest.main()
