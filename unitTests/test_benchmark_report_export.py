"""Benchmark report export beside the PDF: CSV, SVG, a standalone HTML page and an embeddable
HTML snippet (primeatlas/benchmark/report_export.py, chart_svg.py).

Checks: an SVG chart is well-formed XML, flips y (a larger value sits higher), keeps Unicode
text unfolded and draws a dashed series dashed; the CSV round-trips every row and column;
the SVG report holds one chart per report metric (four without RAM rows, six with them and
references on) and leaves out a line hidden in the tab; the HTML page is a full document
with the charts inline and one table per logical table, every cell escaped; the snippet is
one <div class="primeatlas-benchmark"> with a style scoped to it and no document tags; the
Benchmark tab's export menu writes each format to the chosen path.

Usability of the page and the snippet: every run table and the Computers section is a
<details> closed by default with its title in the <summary>; a navigation bar under the
subtitle links Charts and each table and section the page holds, in page order, never one it
left out; every anchor starts with "pa-" (a computer cell links to "pa-pc-..."); a cell a run
lacks is marked for the page's script; a chart no exported run has a point on is left out
(HTML, SVG and PDF; in the PDF the other chart of the page takes the page), a chart emptied
by hidden lines stays; with no runs at all the whole-run charts stay with "no data", no table
and no Computers section. Chart labels and ticks from a million up are short ("350 M"), the
exact value is the point's <title>; the tables keep exact numbers. Windows, real display
(the tab part):
    python unitTests/test_benchmark_report_export.py
"""
import csv
from html import escape
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from app_sandbox import fresh_ui_store  # noqa: E402

from primeatlas.benchmark import chart_series, report_export, table_columns  # noqa: E402
from primeatlas.benchmark.chart_svg import chart_svg  # noqa: E402
from primeatlas.core.i18n import Translator  # noqa: E402

SVG_NS = "{http://www.w3.org/2000/svg}"


def _row(floor, engine, nps, ram="", windows="10", note=""):
    return dict(base_exponent=str(floor), engine=engine, loop_numbers_per_second=nps,
                loop_seconds_per_window="0.1", numbers_processed="100",
                windows_written=windows, sieve_seconds="1", bytes_written="2000000",
                write_seconds="1", max_child_rss_mb=ram, run_status=note)


ROWS = [_row(20, "v4.1", "5e7", ram="1024"), _row(20, "v5", "3.5e8", ram="4096"),
        _row(25, "v5", "1.4e8", ram="8192", windows="1000", note="<b>&")]
NO_RAM = [_row(20, "v4.1", "5e7"), _row(20, "v5", "3.5e8")]


def _charts(svg_text):
    root = ET.fromstring(svg_text)
    return [el for el in root.iter(f"{SVG_NS}svg")][1:]


class SvgChartTests(unittest.TestCase):
    def test_svg_chart(self):
        T = Translator("pl")
        s = chart_svg(600, 240, translator=T, label_key1="bench.axis_floor",
                      series1=[chart_series.Series("v5", "v5", [(20, 1.0), (25, 9.0)],
                                                   "#1f77b4", False)],
                      series2=[chart_series.Series("ref", "ref", [(20, 1.0), (25, 2.0)],
                                                   "#ff7f0e", True)])
        root = ET.fromstring(s)
        # The legend's marker sits in the top row (y < 20); the rest are data points.
        circles = [c for c in root.iter(f"{SVG_NS}circle")
                   if c.get("fill") == "#1f77b4" and float(c.get("cy")) > 20]
        ys = [float(c.get("cy")) for c in sorted(circles, key=lambda c: float(c.get("cx")))]
        self.assertEqual(len(ys), 2)
        self.assertLess(ys[1], ys[0], "the larger value sits higher")
        texts = "".join(t.text or "" for t in root.iter(f"{SVG_NS}text"))
        self.assertIn(T("bench.axis_floor"), texts)
        self.assertTrue(any(el.get("stroke-dasharray") for el in root.iter(f"{SVG_NS}line")),
                        "the dashed series is dashed")


class ExportTests(unittest.TestCase):
    def _export(self, kind, rows, **kw):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "report")
            report_export.export(kind, path, list(rows[0]), rows, translator=Translator("en"),
                                 **kw)
            return Path(path).read_text(encoding="utf-8")

    def test_csv_round_trip(self):
        # The CSV holds the run table's columns: their keys as the header, raw values.
        text = self._export("csv", ROWS)
        back = list(csv.DictReader(text.splitlines()))
        self.assertEqual(tuple(back[0]), table_columns.EXPORT_COLUMNS)
        self.assertEqual(back, [{c: table_columns.raw(r, c) for c in table_columns.EXPORT_COLUMNS}
                                for r in ROWS])
        self.assertEqual([r["engine"] for r in back], ["v4.1", "v5", "v5"])
        self.assertEqual([r["status"] for r in back], ["completed", "completed", "<b>&"])

    def test_svg_report_has_one_chart_per_metric(self):
        self.assertEqual(len(_charts(self._export("svg", NO_RAM, sieve_points=[(20, 1.0)]))), 4)
        self.assertEqual(len(_charts(self._export("svg", ROWS, references=True))), 6)
        self.assertEqual(len(_charts(self._export("svg", NO_RAM))), 2)

    def test_svg_report_leaves_out_hidden_lines(self):
        plain = self._export("svg", ROWS)
        self.assertIn("50,000,000 [v4.1] @ 10^2", plain)
        self.assertIn("1,024 [v4.1] @ 10^2", plain)
        hidden = self._export("svg", ROWS, hidden_lines={
            "run": {chart_series.line_key("primary", "v4.1")},
            "ram": {chart_series.line_key("primary", "v4.1")}})
        self.assertNotIn("50,000,000 [v4.1] @ 10^2", hidden)
        self.assertNotIn("1,024 [v4.1] @ 10^2", hidden)

    def test_html_names_filter_measure_and_mixed_widths(self):
        # Like the PDF: the filter under the title, the sieve measure over the sieve charts,
        # the floors of mixed widths over a page's charts; the sieve charts use the measure.
        t = Translator("en").t
        rows = [dict(ROWS[0], sieve_wall_seconds="2"),
                dict(ROWS[1], numbers_processed="1000", sieve_wall_seconds="2")]
        page = self._export("html", rows, sieve_points=[(20, 1.0)], measure="wall",
                            filter_note="threads: 24 thr")
        self.assertIn("  |  threads: 24 thr</p>", page)
        self.assertIn(t("bench.measure_heading", measure=t("bench.measure_wall")), page)
        self.assertIn(t("bench.axis_sieve_wall_nps"), page)
        self.assertNotIn(t("bench.axis_sieve_nps") + "<", page)
        self.assertIn(escape(t("bench.mixed_widths", floors="20")), page)
        plain = self._export("html", ROWS, sieve_points=[(20, 1.0)])
        self.assertNotIn(t("bench.mixed_widths", floors="20")[:20], plain)
        self.assertIn(t("bench.axis_sieve_nps"), plain)

    def test_html_page(self):
        page = self._export("html", ROWS)
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertIn('<meta charset="utf-8">', page)
        self.assertEqual(page.split("<script", 1)[0].count("<svg"), 4)   # whole run and RAM; no sieve data
        self.assertGreaterEqual(page.count("<table"), 1)
        t = Translator("en").t
        for column in [c for _k, cs in table_columns.report_tables(ROWS) for c in cs]:
            self.assertIn(f"<th>{escape(t(table_columns.header_key(column)))}</th>", page)
        self.assertIn("&lt;b&gt;&amp;", page)
        self.assertNotIn("<b>&", page)

    def test_missing_values_show_a_dash(self):
        page = self._export("html", NO_RAM)
        tables = page.split('<div class="tables">', 1)[1]
        self.assertNotIn("<td></td>", tables, "no empty cell in the tables")
        self.assertIn('<td class="pa-none">\u2014</td>', tables, "a value the run lacks is a dash")
        back = list(csv.DictReader(self._export("csv", NO_RAM).splitlines()))
        self.assertEqual([r["ram_mb"] for r in back], ["", ""], "the CSV keeps the empty values")

    def test_html_snippet(self):
        snippet = self._export("snippet", ROWS).strip()
        self.assertTrue(snippet.startswith('<div class="primeatlas-benchmark">'))
        self.assertTrue(snippet.endswith("</div>"))
        for tag in ("<html", "<head", "<body", "<!DOCTYPE"):
            self.assertNotIn(tag, snippet)
        self.assertIn("<style>", snippet)
        style = snippet.split("<style>", 1)[1].split("</style>", 1)[0]
        rules = [r.strip() for r in style.split("}") if r.strip()]
        self.assertTrue(rules and all(r.startswith(".primeatlas-benchmark") for r in rules),
                        "every style rule is scoped to the snippet")
        self.assertIn("<svg", snippet)
        self.assertIn("<table", snippet)

    def test_kinds_and_extensions(self):
        self.assertEqual(report_export.EXTENSIONS,
                         {"csv": ".csv", "svg": ".svg", "html": ".html", "snippet": ".html"})


COUNT_ONLY = [dict(r, bytes_written="0", write_seconds="2.3", write_files="0") for r in NO_RAM]
MACHINE = [dict(r, machine_id="3f9a0c1d2e4b") for r in ROWS]


def _sections(page):
    """The ids of the page's <details> sections and the hrefs of its navigation bar (None
    without one)."""
    details = re.findall(r'<details class="pa-section" id="([^"]+)">', page)
    nav = re.search(r'<nav class="pa-nav">(.*?)</nav>', page, re.S)
    hrefs = re.findall(r'href="#([^"]+)"', nav.group(1)) if nav else None
    return details, hrefs


def _before_script(page):
    return page.split("<script", 1)[0]


class UsabilityTests(unittest.TestCase):
    def _page(self, rows, kind="html", **kw):
        return report_export.render(kind, list(rows[0]), rows, translator=Translator("en"),
                                    **kw)

    def test_tables_are_closed_details(self):
        t = Translator("en").t
        page = self._page(MACHINE)
        details, _hrefs = _sections(page)
        tables = [title for title, _c in table_columns.report_tables(MACHINE)]
        self.assertEqual(details, [report_export.section_id(k) for k in tables] + ["pa-computers"])
        self.assertNotIn("<details open", page)
        self.assertNotIn(" open>", page)
        for key in tables + ["computer.section_title"]:
            self.assertIn(f"<summary><h2>{escape(t(key))}</h2></summary>", page)
        self.assertEqual(page.count("<table"), len(tables), "no machine data: no computer table")

    def test_navigation_bar(self):
        t = Translator("en").t
        page = self._page(MACHINE)
        details, hrefs = _sections(page)
        self.assertEqual(hrefs, ["pa-charts"] + details)
        nav = re.search(r'<nav class="pa-nav">(.*?)</nav>', page, re.S).group(1)
        tables = [k for k, _c in table_columns.report_tables(MACHINE)]
        labels = re.findall(r'">([^<]*)</a>', nav)
        self.assertEqual(labels, [escape(t(k)) for k in ["bench.report_nav_charts"]
                                  + [report_export.NAV_KEYS[k] for k in tables]
                                  + ["computer.section_title"]])
        for key in ["bench.report_nav_charts"] + list(report_export.NAV_KEYS.values()):
            for lang in ("en", "pl"):
                self.assertNotEqual(Translator(lang).t(key), key, (lang, key))
        self.assertLess(page.index("pa-subtitle"), page.index('<nav class="pa-nav">'))
        self.assertLess(page.index('<nav class="pa-nav">'), page.index('id="pa-charts"'))
        for row_set in (ROWS, NO_RAM):
            details, hrefs = _sections(self._page(row_set))
            self.assertNotIn("pa-computers", details + hrefs, "no computer: no section, no link")
            self.assertEqual(hrefs, ["pa-charts"] + details)

    def test_anchors_carry_the_prefix(self):
        page = _before_script(self._page(MACHINE, kind="snippet"))
        ids = re.findall(r'\bid="([^"]+)"', page)
        self.assertTrue(ids and all(i.startswith("pa-") for i in ids), ids)
        self.assertEqual(len(ids), len(set(ids)), "ids are unique")
        links = set(re.findall(r'href="#([^"]+)"', page))
        self.assertTrue(links <= set(ids), links - set(ids))
        self.assertIn('href="#pa-pc-3f9a0c1d2e4b"', page)

    def test_empty_cells_are_marked(self):
        page = self._page(NO_RAM)
        tables = page.split('id="pa-table-', 1)[1]
        self.assertNotIn("<td>—</td>", tables)
        self.assertIn('<td class="pa-none">—</td>', tables)
        self.assertIn('<table data-keys="3">', page)

    def test_a_chart_without_points_is_left_out(self):
        t = Translator("en").t
        page = self._page(COUNT_ONLY)
        self.assertNotIn(t("bench.axis_write_mbps"), _before_script(page))
        self.assertIn(t("bench.axis_total_nps"), page)
        self.assertEqual(_before_script(page).count("<svg"), 1)
        data = json.loads(re.search(r'class="pa-data">(.*?)</script>', page, re.S).group(1))
        self.assertEqual([len(p["charts"]) for p in data["pages"]], [1])
        self.assertEqual(len(_charts(self._page(COUNT_ONLY, kind="svg"))), 1)
        # Every line hidden in the tab: the chart is left out too, with no "no data" box.
        hidden = self._page(NO_RAM, hidden_lines={"run": {
            chart_series.line_key("secondary", "v4.1"), chart_series.line_key("secondary", "v5")}})
        self.assertEqual(_before_script(hidden).count("<svg"), 1)
        self.assertNotIn(t("bench.no_data_chart"), _before_script(hidden))
        self.assertEqual(_before_script(self._page(NO_RAM)).count("<svg"), 2)

    def test_no_runs(self):
        t = Translator("en").t
        page = self._page(ROWS, selection={"engine": set()})
        self.assertEqual(_sections(page), ([], None), "no chart, no table, no navigation")
        self.assertNotIn("<table", page)
        self.assertNotIn(escape(t("bench.no_data_chart")), _before_script(page))
        self.assertEqual(_before_script(page).count("<svg"), 0)

    def test_short_chart_labels_and_exact_titles(self):
        root = ET.fromstring(self._page(NO_RAM, kind="svg"))
        texts = [el.text for el in root.iter(f"{SVG_NS}text")]
        titles = [el.text for el in root.iter(f"{SVG_NS}title")]
        self.assertIn("350 M [v5] @ 10^2", texts)
        self.assertNotIn("350,000,000 [v5] @ 10^2", texts)
        self.assertIn("10^20: 350,000,000 [v5] @ 10^2", titles)
        self.assertTrue(any(x and x.endswith(" M") and "[" not in x for x in texts),
                        "a short tick")
        self.assertFalse(any(x and re.search(r"\d{3},\d{3},\d{3}", x) for x in texts),
                         "no long number drawn on the chart")
        tables = self._page(NO_RAM).split('id="pa-table-', 1)[1]
        self.assertIn("350,000,000", tables, "the tables keep the exact number")

    def test_pdf_follows(self):
        from primeatlas.benchmark import benchmark
        t = Translator("en").t
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "r.pdf")
            benchmark.render_benchmark_pdf(path, [], list(COUNT_ONLY[0]), COUNT_ONLY,
                                           translator=Translator("en"))
            data = open(path, "rb").read()
            self.assertNotIn(t("bench.axis_write_mbps").encode(), data)
            self.assertIn(t("bench.axis_total_nps").encode(), data)
            self.assertIn(b"350 M [v5]", data)
            self.assertNotIn(b"350,000,000 [v5]", data)
            benchmark.render_benchmark_pdf(path, [], list(NO_RAM[0]), NO_RAM,
                                           translator=Translator("en"))
            self.assertIn(t("bench.axis_write_mbps").encode(), open(path, "rb").read())


class TabExportTests(unittest.TestCase):
    def test_export_menu_writes_each_format(self):
        import tkinter as tk
        from tkinter import filedialog, messagebox
        from primeatlas.benchmark import benchmark_tab
        from primeatlas.core.theme import palette_for

        originals = {name: getattr(messagebox, name) for name in ("showinfo", "showerror")}
        for name in originals:
            setattr(messagebox, name, lambda *a, **k: None)
        original_save = filedialog.asksaveasfilename
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
                tab.pack()
                tab.reload_benchmark_log()
                labels = [tab.export_menu.entrycget(i, "label")
                          for i in range(tab.export_menu.index("end") + 1)]
                t = Translator("en").t
                self.assertEqual(labels, [t("bench.export_csv"), t("bench.export_svg"),
                                          t("bench.export_html"), t("bench.export_snippet")])
                for kind in ("csv", "svg", "html", "snippet"):
                    path = os.path.join(portal, f"out_{kind}{report_export.EXTENSIONS[kind]}")
                    filedialog.asksaveasfilename = lambda path=path, **kw: path
                    tab._export_report(kind)
                    self.assertTrue(os.path.getsize(path) > 0, kind)
                    self.assertIn(path, tab.status.get())
                # The exports follow the Filter window like the PDF: only the kept runs.
                window = tab._open_filter_window()
                window.value_buttons["engine"]["v5"].invoke()
                path = os.path.join(portal, "filtered.csv")
                filedialog.asksaveasfilename = lambda **kw: path
                tab._export_report("csv")
                kept = list(csv.DictReader(Path(path).read_text(encoding="utf-8").splitlines()))
                self.assertEqual([r["engine"] for r in kept], ["v5", "v5"])
                path = os.path.join(portal, "filtered.html")
                filedialog.asksaveasfilename = lambda **kw: path
                tab._export_report("html")
                self.assertIn(escape(tab._filter_note()), Path(path).read_text(encoding="utf-8"))
            finally:
                root.destroy()
                filedialog.asksaveasfilename = original_save
                for name, fn in originals.items():
                    setattr(messagebox, name, fn)


if __name__ == "__main__":
    unittest.main()
