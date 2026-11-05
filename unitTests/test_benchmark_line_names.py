"""Benchmark chart lines say what was measured: engine (or its version), threads, and for
primesieve whether the run went through the Atlas-format wrapper or the native program.

Checks: a row's line name carries the version, the sieve threads (instances when more than
one ran) and the write threads; old rows without them keep the bare engine name; names are
ASCII (the PDF font); primesieve wrapper rows read "primesieve (Atlas format)", native rows
"primesieve count (native)" / "primesieve print (native)". A native count sieves the range
and counts the bits, the work of an engine's sieve phase: it is on the sieve charts only
(n/s and s/window, the window being 10^7 numbers). A native print sieves and outputs every
prime, a whole run: it is on the whole-run chart only (no sieve/write split). The line keeps
its engine's color and draw order; no static primesieve reference is left (Atlas measures
primesieve on the same range instead). Each point names the range it was measured on
("@ 10^11", "@ 2x10^11"); the floors where a chart compares points of different widths are
listed (the tab shows them under the chart, the PDF next to its heading). A row with sieve
threads but no write threads says "write ?". Pure, no display:
    python unitTests/test_benchmark_line_names.py
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from primeatlas.benchmark import benchmark, chart_series, line_names, reference_points  # noqa: E402
from primeatlas.core.i18n import Translator  # noqa: E402

W = 10_000_000


def _row(engine, floor=19, version="", threads="", instance="", **kw):
    row = dict(base_exponent=str(floor), engine=engine, engine_version=version,
               threads=threads, instance_of_n=instance, loop_numbers_per_second="1e9",
               numbers_processed=str(100 * W), windows_written="100", sieve_seconds="2",
               write_seconds="1", bytes_written="2000000")
    row.update(kw)
    return row


class LineNameTests(unittest.TestCase):
    def test_version_and_threads(self):
        self.assertEqual(line_names.line_name(_row("v6", version="v6.0", threads="24",
                                                   write_threads="8", instance="1/1")),
                         "v6.0, 24 thr, write 8")
        self.assertEqual(line_names.line_name(_row("v6", version="v6.0", threads="1",
                                                   write_threads="8")),
                         "v6.0, 1 thr, write 8", "write threads named next to sieve threads")
        self.assertEqual(line_names.line_name(_row("v6", version="v6.0", threads="24",
                                                   write_threads="8", instance="1/2")),
                         "v6.0, 2x24 thr, write 8")
        self.assertEqual(line_names.line_name(_row("v6")), "v6", "old rows keep the engine name")
        self.assertEqual(line_names.line_name(_row("cuda", version="v1.0", threads="GPU",
                                                   write_threads="1")),
                         "cuda v1.0, GPU, write 1")

    def test_names_are_ascii_for_the_pdf(self):
        rows = [_row("v6", version="v6.0", threads="24", instance="1/2"),
                _row("primesieve_print", version="12.15", threads="1")]
        self.assertTrue(all(line_names.line_name(r).isascii() for r in rows))

    def test_primesieve_labels(self):
        self.assertEqual(line_names.line_name(_row("primesieve")), "primesieve (Atlas format)")
        self.assertEqual(line_names.line_name(_row("primesieve", version="v1.0", threads="1",
                                                   write_threads="1")),
                         "primesieve (Atlas format) v1.0, 1 thr, write 1")
        self.assertEqual(line_names.line_name(_row("primesieve_print", version="12.15",
                                                   threads="1", write_threads="1")),
                         "primesieve print (native) 12.15, 1 thr, write 1")

    def test_p_runs_keep_their_kind(self):
        row = _row("pt1", version="pt1", threads="24", write_threads="1", kind="P")
        self.assertEqual(line_names.line_name(row), "pt1 P, 24 thr, write 1")


class ChartFilterTests(unittest.TestCase):
    ROWS = [
        _row("v6", version="v6.0", threads="24", write_threads="8"),
        _row("primesieve_print", version="12.15", threads="1", write_threads="1",
             windows_written="0", loop_numbers_per_second="2.5e8", write_seconds="", sieve_seconds=""),
        _row("primesieve_count", version="12.15", threads="15", windows_written="0",
             loop_numbers_per_second="", write_seconds="", sieve_seconds="4"),
    ]

    def lines(self, metric):
        return benchmark.benchmark_engine_lines(self.ROWS, metric)

    def test_count_is_on_the_sieve_charts_only(self):
        name = "primesieve count (native) 12.15, 15 thr"
        self.assertEqual(self.lines("sieve")[name], [(19, 100 * W / 4)])
        self.assertEqual(self.lines("sieve_spw")[name], [(19, 4 / 100)],
                         "s/window over 10^7-number windows")
        self.assertNotIn(name, self.lines("growth"))
        self.assertNotIn(name, self.lines("write"))

    def test_print_is_on_the_whole_run_chart_only(self):
        name = "primesieve print (native) 12.15, 1 thr, write 1"
        self.assertEqual(self.lines("growth")[name], [(19, 2.5e8)])
        for metric in ("write", "sieve", "sieve_spw"):
            self.assertNotIn(name, self.lines(metric), metric)

    def test_series_keep_the_engine_color(self):
        series = benchmark.benchmark_series(self.ROWS, "sieve")
        by_name = {s.name: s for s in series}
        self.assertEqual(by_name["v6.0, 24 thr, write 8"].color, chart_series.ENGINE_COLORS["v6"])
        self.assertEqual(by_name["v6.0, 24 thr, write 8"].tag, "v6.0, 24 thr, write 8",
                         "the point label names version and threads")
        native = by_name["primesieve count (native) 12.15, 15 thr"]
        self.assertEqual(native.color, chart_series.ENGINE_COLORS["primesieve_count"])
        colors = {chart_series.ENGINE_COLORS[e]
                  for e in ("primesieve", "primesieve_print", "primesieve_count")}
        self.assertEqual(len(colors), 3, "the three primesieve paths have their own colors")
        self.assertEqual([s.name for s in chart_series.legend_series(series)],
                         [s.name for s in series], "legend in engine draw order")


class WidthTests(unittest.TestCase):
    ROWS = [
        _row("v6", version="v6.0", threads="15", write_threads="8",
             numbers_processed=str(10 ** 11)),
        _row("primesieve_count", version="12.15", threads="15", windows_written="0",
             loop_numbers_per_second="", sieve_seconds="3", numbers_processed=str(10 ** 10)),
        _row("v5", version="v5.1", threads="24", write_threads="1", floor=20,
             numbers_processed=str(2 * 10 ** 11)),
        _row("v6", version="v6.0", threads="15", write_threads="8", floor=20,
             numbers_processed=str(2 * 10 ** 11)),
    ]

    def test_width_label(self):
        self.assertEqual(line_names.width_label(10 ** 11), "10^11")
        self.assertEqual(line_names.width_label(2 * 10 ** 11), "2x10^11")
        self.assertEqual(line_names.width_label(15 * 10 ** 9), "1.5x10^10")
        self.assertEqual(line_names.width_label(None), "")

    def test_points_name_their_width(self):
        series = {s.name: s for s in benchmark.benchmark_series(self.ROWS, "sieve")}
        v6 = series["v6.0, 15 thr, write 8"]
        self.assertEqual(chart_series.point_label("{:,.0f}", 5.0, v6, x=19),
                         "5 [v6.0, 15 thr, write 8] @ 10^11")
        self.assertEqual(chart_series.point_label("{:,.0f}", 5.0, v6, x=20),
                         "5 [v6.0, 15 thr, write 8] @ 2x10^11")
        self.assertEqual(chart_series.point_label("{:,.0f}", 5.0, v6), "5 [v6.0, 15 thr, write 8]")

    def test_mixed_widths_are_listed(self):
        self.assertEqual(benchmark.mixed_width_floors(self.ROWS, "sieve"), [19],
                         "floor 19 compares 10^10 with 10^11; floor 20 is one width")
        self.assertEqual(benchmark.mixed_width_floors(self.ROWS[2:], "sieve"), [])

    def test_unknown_write_threads(self):
        self.assertEqual(line_names.line_name(_row("v6", version="v6.0", threads="1")),
                         "v6.0, 1 thr, write ?")
        self.assertEqual(line_names.line_name(_row("primesieve_count", version="12.15",
                                                   threads="15")),
                         "primesieve count (native) 12.15, 15 thr", "a count writes nothing")


class ReferenceTests(unittest.TestCase):
    def test_no_static_primesieve_reference(self):
        t = Translator("en").t
        self.assertTrue(reference_points.reference_series(t))
        self.assertFalse([r for r in reference_points.REFERENCES if "primesieve" in r.name])


if __name__ == "__main__":
    unittest.main()
