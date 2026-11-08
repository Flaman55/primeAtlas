"""The interactive Benchmark HTML report (primeatlas/benchmark/report_html.py, report_chart.js).

Checks, Python side: the page's data carries every run it is given with its filter values
(purpose values translated) and floor, and the records of each chart reduce (last row per
floor and line among the runs a selection keeps) to exactly the Series the tab draws for that
selection; the page starts in the tab's view (log scale, references, hidden lines, pins,
zoom); an exported page holds only the runs the tab's filter keeps, its own filter starting
at All over them, and its tables list exactly those runs; "</" in the data cannot close its
script element.

Through node (skipped without it): the script's reduction gives the Python Series for several
selections; its filter clicks follow chart_filter.toggle_value()/select_all() (All or single
values, there and back) and its summary shows the translated values; its chart drawing is the SVG chart_svg.chart_svg() writes for the same series
(linear, log and pinned axes), apart from the legend's click groups and the points' hover
titles; its zoom, pan and zoomed floor ticks match chart_view.py; zoomed
charts (both axes, lines cut at every plot edge) match too.
    python unitTests/test_benchmark_report_html.py
"""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from primeatlas.benchmark import chart_filter, chart_view, report_export, report_html  # noqa: E402
from primeatlas.benchmark.benchmark import benchmark_series, report_chart_pages  # noqa: E402
from primeatlas.benchmark.chart_svg import chart_svg  # noqa: E402
from primeatlas.core.i18n import Translator  # noqa: E402

NODE = shutil.which("node")
SCRIPT = report_html.SCRIPT_PATH


def _row(floor, engine, nps, threads="24", write="8", numbers="10000000000", ram="2048"):
    return dict(base_exponent=str(floor), engine=engine, loop_numbers_per_second=str(nps),
                numbers_processed=numbers, windows_written="10", sieve_seconds="1.5",
                bytes_written="20000000", write_seconds="2", max_child_rss_mb=ram,
                threads=threads, write_threads=write, run_status="")


ROWS = [_row(f, e, nps * f, threads=th, numbers=n)
        for f in (18, 20, 22, 24)
        for e, nps, th, n in (("v5", 1.1e7, "24", "10000000000"), ("v6", 1.7e7, "24", "10000000000"),
                              ("v6", 1.3e7, "15", "100000000000"), ("v4.1", 7.3e6, "24", "10000000000"))]
ROWS.append(_row(22, "v6", 2.9e8, threads="24", numbers="100000000000"))   # a later v6 run wins
FIELDNAMES = list(ROWS[0])
OPTIONS = dict(sieve_points=[(18, 1.0)], references=True, log_y=False)


def _series_map(series):
    return {s.name: [list(p) for p in s.points] for s in series}


def _python_series(rows, selection, metric):
    return _series_map(benchmark_series(chart_filter.apply(rows, selection), metric))


def _data(rows=ROWS, selection=None, **view):
    t = Translator("en").t
    pages = report_chart_pages(rows, [(18, 1.0)], view.get("references", True))
    return pages, report_html.report_data(rows, pages, t, 900, 260, selection=selection,
                                          **view)


def _node(task):
    driver = ("const m = require(process.argv[2]); let s = '';"
              "process.stdin.on('data', c => s += c); process.stdin.on('end', () => {"
              " const task = JSON.parse(s); const out = task.cases.map(c => run(c));"
              " process.stdout.write(JSON.stringify(out)); });"
              "function run(c) {"
              " if (c.kind === 'series') { const sel = {};"
              "  for (const k in c.selection) sel[k] = new Set(c.selection[k]);"
              "  const kept = m.keptRuns(c.data, sel);"
              "  return m.reduce(c.data.pages[c.page].charts[c.chart].records, kept); }"
              " if (c.kind === 'svg') return m.chartSvg(c.w, c.h, c.opts).svg;"
              " if (c.kind === 'zoom') return m.zoomStep(c.view, c.level, c.base, c.anchor, c.steps, c.span);"
              " if (c.kind === 'pan') return m.pan(c.view, c.span, c.delta);"
              " if (c.kind === 'ticks') return m.tickFloors(...c.args);"
              " if (c.kind === 'toggle') { let sel = {}; return c.ops.map(op => {"
              "  sel = op[0] === 'all' ? m.selectAll(sel, op[1]) : m.toggleValue(sel, op[1], op[2]);"
              "  const o = {}; for (const k in sel) o[k] = [...sel[k]].sort(); return o; }); }"
              " if (c.kind === 'summary') { const sel = {};"
              "  for (const k in c.selection) sel[k] = new Set(c.selection[k]);"
              "  return m.filterSummary(c.data, sel); } }")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "driver.js"
        path.write_text(driver, encoding="utf-8")
        done = subprocess.run([NODE, str(path), SCRIPT], input=json.dumps(task), text=True,
                              capture_output=True, encoding="utf-8", timeout=60)
    if done.returncode:
        raise AssertionError(done.stderr)
    return json.loads(done.stdout)


def _js_series(data, page, chart, reduced):
    lines = data["lines"]
    return {lines[int(i)]["name"]: [[p[0], p[1]] for p in points] for i, points in reduced.items()}


SELECTIONS = [{}, {"engine": {"v6"}}, {"threads": {"15 thr"}}, {"width": {"10^10"}},
              {"engine": {"v6", "v5"}, "width": {"10^11"}}, {"engine": set()}]


class DataTests(unittest.TestCase):
    def test_records_reduce_to_the_tab_series(self):
        pages, data = _data()
        self.assertEqual(data["runs"], len(ROWS))
        self.assertEqual(data["floor_of_run"][-1], 22)
        for selection in SELECTIONS:
            keep = [chart_filter.keeps(row, selection) for row in ROWS]
            for (kind, charts), page in zip(pages, data["pages"]):
                for spec, chart in zip(charts, page["charts"]):
                    latest = {}
                    for run, line, floor, value, _width in chart["records"]:
                        if keep[run]:
                            latest.setdefault(data["lines"][line]["name"], {})[floor] = value
                    got = {name: sorted([f, v] for f, v in points.items())
                           for name, points in latest.items()}
                    self.assertEqual(got, _python_series(ROWS, selection, spec[2]),
                                     (selection, spec[2]))

    def test_starts_in_the_tab_view(self):
        _pages, data = _data(selection={"engine": {"v6"}}, log_y=True, references=False,
                             hidden_lines={"run": {("primary", "v5, 24 thr, write 8")}},
                             y_pins={"run": {"primary": (None, 5e8)}}, x_view=(19.0, 23.0),
                             zoom_levels=(3, (18, 24), {"run": 2}))
        self.assertEqual((data["x_level"], data["x_base"]), (3, [18, 24]),
                         "the page zooms on from the tab's notch")
        self.assertEqual([c["y_level"] for c in data["pages"][0]["charts"]], [2, 2])
        self.assertEqual(data["selection"], {"engine": ["v6"]}, "report_data keeps a given selection")
        self.assertTrue(data["log"])
        self.assertFalse(data["refs_on"])
        self.assertTrue(data["refs_available"])
        run = data["pages"][0]["charts"]
        self.assertEqual(run[0]["hidden"], ["v5, 24 thr, write 8"])
        self.assertEqual(run[1]["hidden"], [], "the hidden line is on the primary axis only")
        self.assertEqual(run[0]["pins"], [None, 5e8])
        self.assertEqual(data["view"], [19.0, 23.0])
        engine = [d for d in data["dims"] if d["key"] == "engine"][0]
        self.assertEqual(engine["values"], ["v4.1", "v5", "v6"])

    def test_page_tables_and_escaping(self):
        rows = ROWS + [dict(_row(26, "v6", 1e9), run_status="</script><b>")]   # kept by the filter
        page = report_export.render("html", FIELDNAMES, rows, translator=Translator("en"),
                                    selection={"engine": {"v6"}}, **OPTIONS)
        root = page.split("<body>", 1)[1]
        self.assertEqual(root.count('class="pa-data"'), 1)
        self.assertEqual(root.count("<script>"), 1)
        self.assertLess(root.index("<script>"), root.rindex("</div>"), "inside the report div")
        payload = re.search(r'class="pa-data">(.*?)</script>', root, re.S).group(1)
        self.assertNotIn("</", payload)
        data = json.loads(payload)
        kept = [r for r in rows if r["engine"] == "v6"]
        self.assertEqual(data["runs"], len(kept), "only the runs the tab's filter keeps")
        self.assertEqual(data["selection"], {}, "the page's own filter starts at All")
        engine = [d for d in data["dims"] if d["key"] == "engine"][0]
        self.assertEqual(engine["values"], ["v6"], "the page's filter offers the kept values")
        visible = re.findall(r'<tr data-run="(\d+)">', page)
        hidden = re.findall(r'<tr data-run="(\d+)" hidden>', page)
        self.assertEqual(hidden, [], "no dropped run hidden in the tables")
        self.assertEqual(len(visible), len(kept) * page.count("<h2>"))
        self.assertTrue(all(kept[int(i)]["engine"] == "v6" for i in visible))
        self.assertTrue(page.count("<h2>"))
        whole = report_export.render("html", FIELDNAMES, rows, translator=Translator("en"),
                                     **OPTIONS)
        whole_data = json.loads(re.search(r'class="pa-data">(.*?)</script>', whole, re.S).group(1))
        self.assertEqual(whole_data["runs"], len(rows), "no filter in the tab: every run")
        self.assertIn("&lt;/script&gt;&lt;b&gt;", page)
        self.assertNotIn("</script><b>", page)
        csv_text = report_export.render("csv", FIELDNAMES, rows, selection={"engine": {"v6"}})
        self.assertEqual(len(csv_text.strip().splitlines()) - 1,
                         sum(r["engine"] == "v6" for r in rows), "CSV: the kept runs")

    def test_purpose_labels(self):
        rows = [dict(ROWS[0], run_purpose="benchmark"), dict(ROWS[1], run_purpose="storage")]
        for lang, words in (("en", ["Benchmark", "Storage"]), ("pl", ["Benchmark", "Magazyn"])):
            t = Translator(lang).t
            pages = report_chart_pages(rows, [(18, 1.0)], True)
            data = report_html.report_data(rows, pages, t, 900, 260)
            purpose = [d for d in data["dims"] if d["key"] == "purpose"][0]
            self.assertEqual(purpose["values"], ["benchmark", "storage"])
            self.assertEqual(purpose["labels"], words, lang)
            threads = [d for d in data["dims"] if d["key"] == "threads"][0]
            self.assertEqual(threads["labels"], threads["values"])

    def test_data_script_escapes_closing_tags(self):
        html = report_html.data_script({"a": "</script><script>alert(1)</script>"})
        self.assertEqual(html.count("</script>"), 1)
        inner = html.split(">", 1)[1].rsplit("</script>", 1)[0]
        self.assertEqual(json.loads(inner)["a"], "</script><script>alert(1)</script>")


def _normalize(svg):
    svg = re.sub(r'<g class="pa-legend" data-line="[^"]*"( opacity="[^"]*")?>', "", svg)
    return re.sub(r"><title>[^<]*</title></circle>", "/>", svg.replace("</g>", ""))


@unittest.skipUnless(NODE, "node not installed")
class ScriptTests(unittest.TestCase):
    def test_reduction_matches_python(self):
        _pages, data = _data()
        cases, expected = [], []
        for selection in SELECTIONS:
            for p, page in enumerate(data["pages"]):
                for c, _chart in enumerate(page["charts"]):
                    cases.append({"kind": "series", "data": data, "page": p, "chart": c,
                                  "selection": {k: sorted(v) for k, v in selection.items()}})
                    expected.append(selection)
        results = _node({"cases": cases})
        pages, _ = _data()
        for case, selection, reduced in zip(cases, expected, results):
            spec = pages[case["page"]][1][case["chart"]]
            self.assertEqual(_js_series(data, case["page"], case["chart"], reduced),
                             _python_series(ROWS, selection, spec[2]), (selection, spec[2]))

    def test_filter_clicks_match_python(self):
        sequences = [
            [["value", "width", "10^11"], ["value", "width", "10^10"], ["value", "width", "10^11"],
             ["value", "width", "10^10"]],
            [["value", "width", "10^10"], ["all", "width"], ["all", "width"]],
            [["value", "threads", "15 thr"], ["value", "width", "10^11"], ["all", "threads"],
             ["value", "width", "2x10^11"], ["value", "width", "10^11"]],
        ]
        results = _node({"cases": [{"kind": "toggle", "ops": ops} for ops in sequences]})
        for ops, got in zip(sequences, results):
            sel, want = {}, []
            for op in ops:
                sel = (chart_filter.select_all(sel, op[1]) if op[0] == "all"
                       else chart_filter.toggle_value(sel, op[1], op[2]))
                want.append({k: sorted(v) for k, v in sel.items()})
            self.assertEqual(got, want, ops)

    def test_summary_shows_labels(self):
        rows = [dict(ROWS[0], run_purpose="benchmark"), dict(ROWS[1], run_purpose="storage")]
        t = Translator("pl").t
        pages = report_chart_pages(rows, [(18, 1.0)], True)
        data = report_html.report_data(rows, pages, t, 900, 260)
        got = _node({"cases": [{"kind": "summary", "data": data,
                                "selection": {"purpose": ["storage"]}}]})[0]
        self.assertEqual(got, chart_filter.summary({"purpose": {"storage"}}, t))

    def test_chart_matches_python_svg(self):
        t = Translator("en")
        text = {"floor": t.t("bench.axis_floor"), "pinned": t.t("bench.axis_pinned"),
                "no_data": t.t("bench.no_data_chart"), "all_hidden": t.t("bench.all_lines_hidden")}
        series = benchmark_series(ROWS, "growth")
        refs = report_html.reference_series(t.t)
        cases, expected = [], []
        # (log, pins, format, extra series, x view, y view): unzoomed and zoomed, a zoomed
        # part between two floors (19.2..21.4) and one cutting the lines on every edge.
        for log_y, pins, fmt, extra, x_view, y_view in (
                (False, (None, None), "{:,.0f}", [], None, None),
                (True, (None, None), "{:,.0f}", refs, None, None),
                (False, (1e8, 5e9), "{:,.3f}", [], None, None),
                (True, (2e8, None), "{:,.1f}", [], None, None),
                (False, (None, None), "{:,.0f}", [], (19.2, 21.4), None),
                (False, (None, None), "{:,.0f}", [], (19.2, 21.4), (0.3, 0.55)),
                (True, (None, None), "{:,.0f}", refs, (17.5, 23.1), (0.2, 0.9)),
                (False, (1e8, 5e9), "{:,.3f}", [], (21.0, 24.0), (0.0, 0.4))):
            drawn = series + list(extra)
            opts = {"series": [report_html.series_json(s) for s in drawn],
                    "legend": [{"name": s.name, "color": s.color, "dashed": s.dashed,
                                "hidden": False} for s in sorted(drawn, key=lambda s: s.dashed)],
                    "title": t.t("bench.axis_total_nps"), "decimals": report_html.decimals(fmt),
                    "log": log_y, "pins": list(pins), "view": x_view, "yView": y_view,
                    "text": text}
            cases.append({"kind": "svg", "w": 900, "h": 260, "opts": opts})
            expected.append(chart_svg(900, 260, series1=drawn, translator=t,
                                      label_key1="bench.axis_total_nps", fmt1=fmt,
                                      log_y=log_y, pins1=pins, x_view=x_view, y_view=y_view))
        self.assertGreater(expected[4].count("stroke-width=\"1.80\""), 3,
                           "lines pass through the zoomed part between floors 19 and 21")
        for got, want in zip(_node({"cases": cases}), expected):
            self.assertEqual(_normalize(got), want)

    def test_zoom_and_pan_match_chart_view(self):
        span = (10, 30)
        cases = [{"kind": "zoom", "view": None, "level": 0, "base": [10, 30], "anchor": 15,
                  "steps": 1, "span": span},
                 {"kind": "zoom", "view": [12, 16], "level": 7, "base": [10, 30],
                  "anchor": 29.9, "steps": 1, "span": span},
                 {"kind": "zoom", "view": [12, 16], "level": 7, "base": [10, 30],
                  "anchor": 14, "steps": -1, "span": span},
                 {"kind": "zoom", "view": [12, 16], "level": 1, "base": [10, 30],
                  "anchor": 14, "steps": -1, "span": span},
                 {"kind": "zoom", "view": [20, 20.5], "level": 18, "base": [10, 30],
                  "anchor": 20.2, "steps": 1, "span": span},
                 {"kind": "zoom", "view": None, "level": 0, "base": [11, 13], "anchor": 12,
                  "steps": 1, "span": [11, 27]},
                 {"kind": "zoom", "view": None, "level": 0, "base": [11, 13], "anchor": 12,
                  "steps": -1, "span": [11, 27]},
                 {"kind": "zoom", "view": None, "level": 0, "base": [0, 1], "anchor": 0.25,
                  "steps": 1, "span": [0.4, 0.9]},
                 {"kind": "zoom", "view": [27, 33], "level": 2, "base": [11, 27],
                  "anchor": 29, "steps": 1, "span": span},
                 {"kind": "pan", "view": [12, 16], "span": span, "delta": 3},
                 {"kind": "pan", "view": [12, 16], "span": span, "delta": -10},
                 {"kind": "pan", "view": [12, 16], "span": span, "delta": 99},
                 {"kind": "pan", "view": [24, 28], "span": span, "delta": 3},
                 {"kind": "ticks", "args": [11.3, 12.6, 0.1]},
                 {"kind": "ticks", "args": [0, 100, 0]},
                 {"kind": "ticks", "args": [10.95, 13.0, 0.1]}]
        for case, got in zip(cases, _node({"cases": cases})):
            if case["kind"] == "ticks":
                self.assertEqual(got, chart_view.tick_floors(*case["args"]), case)
                continue
            view = tuple(case["view"]) if case["view"] else None
            full = tuple(case["span"])
            if case["kind"] == "zoom":
                want_view, want_level = chart_view.zoom_step(
                    view, case["level"], tuple(case["base"]), case["anchor"], case["steps"], full)
                got_view, got_level = got
                self.assertEqual(got_level, want_level, case)
                self.assertEqual(tuple(got_view) if got_view else None, want_view, case)
                continue
            want = chart_view.pan(view, full, case["delta"])
            self.assertEqual(tuple(got) if got else None, want, case)

if __name__ == "__main__":
    unittest.main()
