"""Benchmark exports hold what the tab shows, and store verifications are on the whole-run chart.

A. A store verification (pt1_verify, v73_verify) is one line on the whole-run chart and on
   no other chart; its value is the table's run speed (numbers_processed / total_seconds);
   it keeps its own name and is never paired with the run that wrote the windows; its color
   is the color of other engines (no palette entry), the user's color on top; on the width axis each floor gets its own shade; a filter keeping
   verifications only exports the whole-run chart alone.
B. HTML, SVG and PDF draw only the lines the tab shows: a chart without a visible line
   (no points, its axis hidden, every line hidden one by one, its runs hidden, a reference
   hidden or switched off) is left out with no "no data"/"all hidden" box; a page left
   without a chart is left out with its heading; a hidden line is absent from the legend
   and from the page's data (on the width axis only its hidden floor); with no chart left
   the HTML has no chart section and no chart link, the PDF starts its tables under the
   title, and an SVG export writes nothing and the tab says so. With nothing hidden the
   export is as before.
C. The page script: a chart shows when the page's filter leaves it a point and hides when it
   leaves none; hiding the last line by its legend keeps the chart and its legend; a page
   with no chart builds only its filter controls.
D. A verified pt1 run (D/P) exports in every format; the save error names no format.
    python unitTests/test_benchmark_export_visible.py
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation"),
                str(ROOT / "unitTests")]

from app_sandbox import fresh_ui_store  # noqa: E402
from benchmark_log_schema import BENCHMARK_FIELDNAMES  # noqa: E402
from primeatlas.core import open_path  # noqa: E402
from primeatlas.benchmark import (benchmark, chart_filter, chart_points, chart_series,  # noqa: E402
                                  line_colors, report_export, report_html, sieve_measure,
                                  table_columns)
from primeatlas.core.i18n import Translator  # noqa: E402
from primeatlas.core.ui_state_store import UiStateStore  # noqa: E402

NODE = shutil.which("node")
T = Translator("en").t
ALL_METRICS = ("write", "sieve", "sieve_spw", "sieve_wall", "sieve_wall_spw", "sieve_overhead",
               "sieve_overhead_pct", "ram", "ram_per_window")
NO_BOX = (T("bench.no_data_chart"), T("bench.all_lines_hidden"))


def _row(floor, engine, version="", loop="5e7", total="10.0", numbers="100000000",
         threads="24", write="8", proof="", sieve="1.0", wall="", ram="2048", windows="10",
         write_s="1", bytes_="20000000", verify=""):
    row = {name: "" for name in BENCHMARK_FIELDNAMES}
    row.update(base_exponent=str(floor), target_idx_start="0", target_idx_end=str(int(windows) - 1),
               windows_written=windows, total_seconds=total, loop_numbers_per_second=loop,
               loop_session_seconds=total if loop else "", numbers_processed=numbers,
               sieve_seconds=sieve, sieve_wall_seconds=wall, write_seconds=write_s,
               bytes_written=bytes_, max_child_rss_mb=ram, engine=engine,
               engine_version=version, threads=threads, write_threads=write,
               proof_seconds=proof, verify_seconds=verify, run_status="completed",
               run_purpose="benchmark")
    return dict(row, kind=benchmark.benchmark_row_kind(row))


def _verify(floor, engine="pt1_verify", version="pt1.1", total="0.708", numbers="10000000"):
    return _row(floor, engine, version, loop="", total=total, numbers=numbers, write="",
                sieve="", ram="", windows="1", write_s="", bytes_="", verify="0.641")


V5 = [_row(20, "v5", "5.0", loop="3e8"), _row(22, "v5", "5.0", loop="2e8")]
V6 = [_row(20, "v6", "6.0", loop="4e8"), _row(22, "v6", "6.0", loop="3e8")]
RUNS = V5 + V6
V5_NAME = "v5 5.0, 24 thr, write 8"
V6_NAME = "v6 6.0, 24 thr, write 8"
PT1_DP = _row(29, "pt1", "pt1.1", proof="8.0", total="9.0", loop="1e7", sieve="0.9", write="1")
VERIFY = [_verify(29), _verify(30, numbers="100000000", total="6.368"),
          _verify(31, numbers="1000000000", total="60.5")]
VERIFY_NAME = "pt1_verify pt1.1, 24 thr"


def _hide(**charts):
    """{"run" | "sieve" | "ram": [(axis, name)]} -> the tab's hidden_lines."""
    return {key: {chart_series.line_key(axis, name) for axis, name in keys}
            for key, keys in charts.items()}


def _axes(*axes):
    return {chart_series.axis_key(axis) for axis in axes}


def _all_hidden():
    return {key: _axes("primary", "secondary") for key in ("run", "sieve", "ram")}


def _before_script(page):
    return page.split("<script", 1)[0]


def _data(page):
    return json.loads(re.search(r'class="pa-data">(.*?)</script>', page, re.S).group(1))


def _html(rows, **options):
    return report_export.render("html", list(rows[0]), rows, translator=Translator("en"),
                                **options)


def _svg(rows, **options):
    return report_export.render("svg", list(rows[0]), rows, translator=Translator("en"),
                                **options)


def _pdf(rows, **options):
    options.setdefault("translator", Translator("en"))
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "r.pdf")
        benchmark.render_benchmark_pdf(path, [], list(rows[0]), rows, **options)
        return open(path, "rb").read()


def _titles_in(text):
    """The report chart titles (axis titles) found in `text`."""
    keys = ("bench.axis_total_nps", "bench.axis_write_mbps", "bench.axis_ram_mb",
            "bench.axis_ram_mb_window", sieve_measure.chart(sieve_measure.DEFAULT).label_key1,
            sieve_measure.chart(sieve_measure.DEFAULT).label_key2)
    return {key for key in keys if T(key) in text}


def _pdf_titles(data):
    return {key for key in _titles_in(data.decode("latin-1"))}


class VerifyLineTests(unittest.TestCase):
    def test_whole_run_chart_only(self):
        for engine, version in (("pt1_verify", "pt1.1"), ("v73_verify", "v7.3")):
            rows = [_verify(29, engine, version)]
            growth = benchmark.benchmark_engine_lines(rows, "growth")
            self.assertEqual(list(growth), [f"{engine} {version}, 24 thr"], engine)
            for metric in ALL_METRICS:
                self.assertEqual(benchmark.benchmark_engine_lines(rows, metric), {},
                                 f"{engine} not on {metric}")

    def test_value_is_the_table_run_speed(self):
        for row in VERIFY:
            (points,) = benchmark.benchmark_engine_lines([row], "growth").values()
            expected = int(row["numbers_processed"]) / float(row["total_seconds"])
            self.assertAlmostEqual(points[0][1], expected, delta=1e-6 * expected)
            self.assertAlmostEqual(points[0][1], table_columns.run_nps(row),
                                   delta=1e-6 * expected)
        for broken in (dict(total=""), dict(total="0"), dict(total="-3"), dict(total="x"),
                       dict(numbers=""), dict(numbers="0")):
            row = _verify(29, **broken)
            self.assertEqual(benchmark.benchmark_engine_lines([row], "growth"), {}, broken)

    def test_own_line_never_paired(self):
        alone = benchmark.benchmark_engine_lines(VERIFY[:1], "growth")
        both = benchmark.benchmark_engine_lines([PT1_DP] + VERIFY[:1], "growth")
        self.assertEqual(sorted(both), ["pt1.1 D proof, 24 thr, write 1",
                                        "pt1.1 P, 24 thr, write 1", VERIFY_NAME])
        self.assertEqual(both[VERIFY_NAME], alone[VERIFY_NAME])
        self.assertNotIn(", write", VERIFY_NAME)

    def test_colors(self):
        for engine in ("pt1_verify", "v73_verify"):
            for theme in ("dark", "light"):
                self.assertNotIn(engine, line_colors.PALETTES[theme])
                self.assertEqual(line_colors.default_color(engine, theme),
                                 line_colors.OTHER_COLORS[theme],
                                 f"{engine}: other engines' color")
        (series,) = benchmark.benchmark_series(VERIFY[:1], "growth",
                                               theme=line_colors.EXPORT_THEME)
        self.assertEqual((series.engine, series.color),
                         ("pt1_verify", line_colors.OTHER_COLORS["light"]))
        store = UiStateStore(os.path.join(tempfile.mkdtemp(), "ui_state.json"))
        line_colors.set_color(store, "pt1_verify", "#123456", theme="light")
        self.assertEqual(line_colors.engine_color("pt1_verify", store, "light"), "#123456")
        self.assertEqual(line_colors.engine_color("pt1_verify", store, "dark"),
                         line_colors.OTHER_COLORS["dark"])

    def test_width_axis_shades(self):
        view = chart_points.PointView(chart_points.X_WIDTH, chart_points.LAST, None)
        series = benchmark.benchmark_series(VERIFY, "growth", view, line_colors.EXPORT_THEME)
        self.assertEqual([s.name for s in series],
                         [VERIFY_NAME + chart_points.floor_suffix(f) for f in (29, 30, 31)])
        self.assertEqual([s.color for s in series],
                         [chart_points.shade(line_colors.OTHER_COLORS["light"], i)
                          for i in range(3)])

    def test_filter_on_verifications_only(self):
        rows = RUNS + VERIFY
        selection = {"engine": {chart_filter.row_value(VERIFY[0], "engine")}}
        page = _html(rows, selection=selection)
        self.assertEqual(_titles_in(_before_script(page)), {"bench.axis_total_nps"})
        self.assertEqual([len(p["charts"]) for p in _data(page)["pages"]], [1])
        self.assertEqual(_titles_in(_svg(rows, selection=selection)), {"bench.axis_total_nps"})
        self.assertEqual(_pdf_titles(_pdf(VERIFY)), {"bench.axis_total_nps"})


class VisibleExportTests(unittest.TestCase):
    def _all(self, rows, **options):
        """(html, svg, pdf) of the same tab view."""
        pdf_options = {k: v for k, v in options.items() if k != "selection"}
        return _html(rows, **options), _svg(rows, **options), _pdf(rows, **pdf_options)

    def _assert_charts(self, rows, titles, **options):
        page, svg, pdf = self._all(rows, **options)
        before = _before_script(page)
        self.assertEqual(_titles_in(before), titles, "html")
        self.assertEqual(_titles_in(svg), titles, "svg")
        self.assertEqual(_pdf_titles(pdf), titles, "pdf")
        for box in NO_BOX:
            self.assertFalse(box in before, box)
            self.assertFalse(box in svg, box)
            self.assertFalse(box.encode() in pdf, box.encode())
        self.assertEqual(sum(len(p["charts"]) for p in _data(page)["pages"]), len(titles))
        return page

    def test_nothing_hidden_keeps_every_chart(self):
        self._assert_charts(RUNS, {"bench.axis_total_nps", "bench.axis_write_mbps",
                                   "bench.axis_ram_mb", "bench.axis_ram_mb_window"})
        for hidden in (None, {}, _hide(run=[("primary", "no such line")])):
            self.assertEqual(_titles_in(_svg(RUNS, hidden_lines=hidden)),
                             _titles_in(_svg(RUNS)))

    def test_hidden_axis_leaves_the_chart_out(self):
        self._assert_charts(RUNS, {"bench.axis_total_nps", "bench.axis_ram_mb",
                                   "bench.axis_ram_mb_window"},
                            hidden_lines={"run": _axes("secondary")})

    def test_every_line_hidden_one_by_one(self):
        hidden = _hide(run=[("secondary", V5_NAME), ("secondary", V6_NAME)],
                       ram=[("primary", V5_NAME), ("primary", V6_NAME)])
        self._assert_charts(RUNS, {"bench.axis_total_nps", "bench.axis_ram_mb_window"},
                            hidden_lines=hidden)

    def test_hidden_runs(self):
        hidden = {key: {chart_series.run_key(V5_NAME), chart_series.run_key(V6_NAME)}
                  for key in ("run",)}
        self._assert_charts(RUNS, {"bench.axis_ram_mb", "bench.axis_ram_mb_window"},
                            hidden_lines=hidden)

    def test_a_hidden_line_is_absent(self):
        page = self._assert_charts(RUNS, {"bench.axis_total_nps", "bench.axis_write_mbps",
                                          "bench.axis_ram_mb", "bench.axis_ram_mb_window"},
                                   hidden_lines=_hide(run=[("primary", V5_NAME)]))
        data = _data(page)
        index = {line["name"]: i for i, line in enumerate(data["lines"])}
        primary, secondary = data["pages"][0]["charts"]
        self.assertFalse(index[V5_NAME] in {r[1] for r in primary["records"]}, index[V5_NAME])
        self.assertTrue(index[V5_NAME] in {r[1] for r in secondary["records"]}, index[V5_NAME])
        self.assertTrue(all(not chart.get("hidden") for p in data["pages"]
                            for chart in p["charts"]), "nothing left to hide on the page")
        charts = re.findall(r'<div class="pa-chart".*?</div>', _before_script(page), re.S)
        self.assertFalse(V5_NAME in charts[0], V5_NAME)
        self.assertTrue(V5_NAME in charts[1], V5_NAME)
        # Hidden on every chart: the line is nowhere in the page's data or drawings.
        everywhere = {key: {chart_series.run_key(V5_NAME)} for key in ("run", "ram")}
        page = _html(RUNS, hidden_lines=everywhere)
        self.assertNotIn(V5_NAME, json.dumps(_data(page)))
        self.assertNotIn(V5_NAME, _before_script(page).split('class="tables"')[0])
        self.assertFalse(V5_NAME in _svg(RUNS, hidden_lines=everywhere), V5_NAME)
        self.assertFalse(V5_NAME.encode() in _pdf(RUNS, hidden_lines=everywhere), V5_NAME)

    def test_width_axis_hides_one_floor(self):
        view = chart_points.PointView(chart_points.X_WIDTH, chart_points.LAST, None)
        views = {key: view for key in ("run", "sieve", "ram")}
        hidden = _hide(run=[("primary", V5_NAME + chart_points.floor_suffix(20))])
        data = _data(_html(RUNS, point_views=views, hidden_lines=hidden))
        index = {line["name"]: i for i, line in enumerate(data["lines"])}
        primary = data["pages"][0]["charts"][0]
        v5 = {r[2] for r in primary["records"] if r[1] == index[V5_NAME]}
        self.assertEqual(v5, {22})
        v6 = {r[2] for r in primary["records"] if r[1] == index[V6_NAME]}
        self.assertEqual(v6, {20, 22})

    def test_references(self):
        sieve = [_row(20, "v5", "5.0", sieve="1.0", ram="")]
        points = [(20, 1.0)]
        refs = [s.name for s in report_html.reference_series(T)]
        sieve_title = sieve_measure.chart(sieve_measure.DEFAULT).label_key1
        hide_engine = _hide(sieve=[("primary", V5_NAME)])
        # The references alone keep the sieve chart.
        page = _html(sieve, sieve_points=points, references=True, hidden_lines=hide_engine)
        self.assertIn(sieve_title, _titles_in(_before_script(page)))
        # Hidden references are absent; with the engine hidden too the chart goes.
        hide_refs = _hide(sieve=[("primary", name) for name in refs])
        page = _html(sieve, sieve_points=points, references=True, hidden_lines=hide_refs)
        self.assertEqual(_data(page)["refs"], [])
        self.assertFalse(any(name in _before_script(page) for name in refs))
        both = {"sieve": hide_engine["sieve"] | hide_refs["sieve"]}
        self.assertNotIn(sieve_title,
                         _titles_in(_before_script(_html(sieve, sieve_points=points,
                                                         references=True, hidden_lines=both))))
        # Switched off in the tab: not shown, so not exported.
        off = _html(sieve, sieve_points=points, references=False)
        self.assertEqual((_data(off)["refs"], _data(off)["refs_available"]), ([], False))
        self.assertFalse(any(name in _before_script(off) for name in refs))

    def test_a_page_without_charts_goes_with_its_heading(self):
        sieve = [_row(20, "v5", "5.0", sieve="1.0", ram="")]
        heading = sieve_measure.heading(sieve_measure.DEFAULT, T)
        hidden = {"sieve": _axes("primary", "secondary")}
        page = _html(sieve, sieve_points=[(20, 1.0)], hidden_lines=hidden)
        self.assertFalse(heading in _before_script(page), heading)
        self.assertEqual(len(_data(page)["pages"]), 1)
        self.assertNotIn(heading.encode(), _pdf(sieve, sieve_points=[(20, 1.0)],
                                                hidden_lines=hidden))
        self.assertIn(heading, _before_script(_html(sieve, sieve_points=[(20, 1.0)])))

    def test_nothing_left(self):
        for rows, options in ((RUNS, {"hidden_lines": _all_hidden()}),
                              (RUNS, {"selection": {"engine": set()}})):
            page = _html(rows, **options)
            before = _before_script(page)
            self.assertTrue(T("bench.pdf_title") in before, T("bench.pdf_title"))
            self.assertTrue('class="pa-subtitle"' in before, 'class="pa-subtitle"')
            self.assertFalse('id="pa-charts"' in before, 'id="pa-charts"')
            self.assertFalse('href="#pa-charts"' in before, 'href="#pa-charts"')
            self.assertFalse("<svg" in before, "<svg")
            for box in NO_BOX:
                self.assertFalse(box in before, box)
            self.assertEqual(_data(page)["pages"], [])
            with self.assertRaises(report_export.NothingToExport):
                _svg(rows, **options)
        page = _before_script(_html(RUNS, hidden_lines=_all_hidden()))
        self.assertIn('id="pa-table-speed"', page, "the tables stay")
        pdf = _pdf(RUNS, hidden_lines=_all_hidden())
        self.assertEqual(_pdf_titles(pdf), set())
        self.assertTrue(T("bench.pdf_title").encode() in pdf, T("bench.pdf_title").encode())
        self.assertTrue(T("bench.pdf_table_speed").encode() in pdf, "the tables stay")
        for box in NO_BOX:
            self.assertFalse(box.encode() in pdf, box.encode())
        self.assertFalse(report_export.has_charts(RUNS, hidden_lines=_all_hidden()))
        self.assertTrue(report_export.has_charts(RUNS))


@unittest.skipUnless(NODE, "node not installed")
class PageScriptTests(unittest.TestCase):
    def _node(self, cases):
        driver = ("const m = require(process.argv[2]); let s = '';"
                  "process.stdin.on('data', c => s += c); process.stdin.on('end', () => {"
                  " const out = JSON.parse(s).map(c => {"
                  "  if (c.kind === 'shown') return m.shownCharts(c.pages);"
                  "  if (c.kind === 'controls') return m.controlsHtml(c.data, c.state);"
                  "  if (c.kind === 'svg') return m.chartSvg(c.w, c.h, c.opts).svg; });"
                  " process.stdout.write(JSON.stringify(out)); });")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "driver.js"
            path.write_text(driver, encoding="utf-8")
            script = Path(tmp) / "report.js"
            script.write_text(report_html.chart_source(), encoding="utf-8")
            done = subprocess.run([NODE, str(path), str(script)], input=json.dumps(cases),
                                  text=True, capture_output=True, encoding="utf-8", timeout=60)
        if done.returncode:
            raise AssertionError(done.stderr)
        return json.loads(done.stdout)

    def test_shown_charts_follow_the_data(self):
        point = {"points": [[20, 1.0]]}
        empty = {"points": []}
        pages = [[{"series": [point, empty]}, {"series": []}], [{"series": [empty]}],
                 [{"series": [empty, point]}]]
        self.assertEqual(self._node([{"kind": "shown", "pages": pages}])[0],
                         [[True, False], [False], [True]])
        # The data comes back: the chart shows again.
        again = [[{"series": [point]}, {"series": [point]}], [{"series": [point]}],
                 [{"series": [point]}]]
        self.assertEqual(self._node([{"kind": "shown", "pages": again}])[0],
                         [[True, True], [True], [True]])

    def test_legend_hiding_the_last_line_keeps_the_chart(self):
        legend = [{"name": V5_NAME, "color": "#1f3fb0", "dashed": False, "hidden": True}]
        text = {key: T(i18n) for key, i18n in (("floor", "bench.axis_floor"),
                                                 ("width", "bench.axis_width"),
                                                 ("pinned", "bench.axis_pinned"),
                                                 ("no_data", "bench.no_data_chart"),
                                                 ("all_hidden", "bench.all_lines_hidden"))}
        svg = self._node([{"kind": "svg", "w": 900, "h": 260, "opts": {
            "series": [], "legend": legend, "title": "t", "decimals": 0, "log": False,
            "pins": [None, None], "view": None, "xMode": "floor", "yView": None,
            "text": text}}])[0]
        self.assertIn(V5_NAME, svg, "the legend stays, so the line can come back")
        self.assertTrue(T("bench.all_lines_hidden") in svg, T("bench.all_lines_hidden"))

    def test_controls_without_charts(self):
        with_charts = _data(_html(RUNS))
        without = _data(_html(RUNS, hidden_lines=_all_hidden()))
        state = {"log": False, "refs": False, "scale": 1.5, "xMode": "floor", "choices": {}}
        full, bare = self._node([{"kind": "controls", "data": with_charts, "state": state},
                                 {"kind": "controls", "data": without, "state": state}])
        chart_only = ('data-toggle="log"', 'data-toggle="scale"', 'data-toggle="xmode"',
                      "data-choice=", 'data-act="floors"', 'class="pa-hint"')
        for mark in chart_only + ("data-dim-all=", "data-dim-value=", 'data-act="runs"'):
            self.assertTrue(mark in full, mark)
        for mark in chart_only + ('data-toggle="refs"',):
            self.assertFalse(mark in bare, mark)
        for mark in ("data-dim-all=", "data-dim-value=", 'data-act="runs"'):
            self.assertIn(mark, bare, "the page filter stays")


class ProofAndErrorTests(unittest.TestCase):
    def test_verified_pt1_run_exports(self):
        rows = [PT1_DP] + VERIFY
        width = chart_points.PointView(chart_points.X_WIDTH, chart_points.LAST, None)
        for views in (None, {key: width for key in ("run", "sieve", "ram")}):
            page = _html(rows, point_views=views)
            names = {line["name"] for line in _data(page)["width_lines"].values()}
            self.assertTrue({"pt1.1 P, 24 thr, write 1 @ f29",
                             "pt1.1 D proof, 24 thr, write 1 @ f29"} <= names, names)
            report_export.render("snippet", list(rows[0]), rows, translator=Translator("en"),
                                 point_views=views)
            self.assertTrue("pt1.1 D proof" in _svg(rows, point_views=views), "pt1.1 D proof")
            self.assertTrue(b"pt1.1 D proof" in _pdf(rows, point_views=views), b"pt1.1 D proof")

    def test_save_error_names_no_format(self):
        for language in ("en", "pl"):
            text = Translator(language).t("bench.save_error", error="E")
            self.assertNotIn("PDF", text, language)
            self.assertTrue(text.endswith("E"), language)


class TabTests(unittest.TestCase):
    def test_svg_without_charts_writes_nothing(self):
        import csv
        import tkinter as tk
        from tkinter import filedialog, messagebox
        from primeatlas.benchmark import benchmark_tab
        from primeatlas.core.theme import palette_for

        shown, asked = [], []
        originals = {name: getattr(messagebox, name) for name in ("showinfo", "showerror")}
        # The saved dialog waits for its window: it reports as an info message here.
        saved_dialog = open_path.show_saved
        open_path.show_saved = lambda parent, title, paths, T: messagebox.showinfo(
            title, "\n".join(paths))
        messagebox.showinfo = lambda title, text, **k: shown.append(("info", text))
        messagebox.showerror = lambda title, text, **k: shown.append(("error", text))
        original_save = filedialog.asksaveasfilename
        with tempfile.TemporaryDirectory() as portal:
            path = os.path.join(portal, "out.svg")
            filedialog.asksaveasfilename = lambda **k: asked.append(k) or path
            with open(os.path.join(portal, "benchmark_log.csv"), "w", newline="",
                      encoding="utf-8") as f:
                fields = [name for name in RUNS[0] if name != "kind"]
                writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(RUNS)
            root = tk.Tk()
            try:
                fresh_ui_store()
                tab = benchmark_tab.BenchmarkTab(
                    root, lambda: portal, tk.StringVar(master=root), Translator("en"),
                    lambda *a, **k: None, palette_for("light"))
                tab.pack()
                tab.reload_benchmark_log()
                tab._hidden_lines = _all_hidden()
                tab._export_report("svg")
                self.assertEqual(shown, [("info", T("bench.export_nothing"))])
                self.assertEqual(asked, [], "no file dialog for nothing to save")
                self.assertFalse(os.path.exists(path))
                shown.clear()
                tab._hidden_lines = {}
                tab._export_report("svg")
                self.assertTrue(os.path.exists(path), "with a chart the SVG is written")
                self.assertEqual([kind for kind, _ in shown], ["info"])
            finally:
                root.destroy()
                filedialog.asksaveasfilename = original_save
                open_path.show_saved = saved_dialog
                for name, fn in originals.items():
                    setattr(messagebox, name, fn)


def main():
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
