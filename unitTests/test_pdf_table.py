"""PDF reports: every cell and header printed in full, column bands with repeated key
columns, pagination, the Benchmark log's logical tables and its one-metric charts whose
value labels never overlap. Pure checks on pdf_table.py, chart_pdf.py and the two reports
(Benchmark log, Constellation records):
    python unitTests/test_pdf_table.py
"""
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from primeatlas.benchmark import benchmark, chart_pdf, chart_series
from primeatlas.constellations import constellations
from primeatlas.core import pdf_table

PAGE_RIGHT = 841.89 - 30
TEXT_RE = re.compile(r"/(\S+) ([\d.]+) Tf 1 0 0 1 ([\d.-]+) ([\d.-]+) Tm \(((?:[^\\)]|\\.)*)\) Tj")

FIELDNAMES = [
    "run_timestamp_utc", "base_exponent", "target_idx_start", "target_idx_end",
    "windows_written", "total_seconds", "seconds_per_window", "total_primes",
    "avg_primes_per_window", "primes_per_second", "l_final", "sieving_primes_count",
    "max_child_rss_mb", "instance_of_n", "loop_session_seconds", "loop_numbers_per_second",
    "loop_seconds_per_window", "write_files", "base_gen_seconds", "sieve_seconds",
    "write_seconds", "bytes_written", "engine", "numbers_processed", "run_status",
    "sieve_count_basis", "kind",
]


def _bench_row(i):
    return {
        "run_timestamp_utc": f"2026-11-02 15:{i // 60:02d}:{i % 60:02d} UTC",
        "base_exponent": str(20 + i % 6), "target_idx_start": "1000000000000000000",
        "target_idx_end": "1000000000000000999", "windows_written": "619",
        "total_seconds": "53.778", "seconds_per_window": "0.0869",
        "total_primes": "107531261", "avg_primes_per_window": "173717.7",
        "primes_per_second": "1999532.19", "l_final": "123456789012345",
        "sieving_primes_count": "1234567890123", "max_child_rss_mb": "240.9",
        "instance_of_n": "1/1", "loop_session_seconds": "54.389",
        "loop_numbers_per_second": "183860296.29", "loop_seconds_per_window": "0.0544",
        "write_files": "1", "base_gen_seconds": "12.3456", "sieve_seconds": "40.12345",
        "write_seconds": "13.4567", "bytes_written": "118540930", "engine": "pt1",
        "numbers_processed": "1000000000000", "run_status": "completed",
        "sieve_count_basis": "unavailable", "kind": "D",
    }


def _texts(pdf_bytes):
    """[(page index, font, size, x, y, text)] of every text op, page by page."""
    text = pdf_bytes.decode("latin-1")
    out = []
    for page, stream in enumerate(re.findall(r"stream\n(.*?)\nendstream", text, re.S)):
        for font, size, x, y, s in TEXT_RE.findall(stream):
            s = re.sub(r"\\(.)", r"\1", s)
            out.append((page, font, float(size), float(x), float(y), s))
    return out


def _bench_pdf(rows, fieldnames=FIELDNAMES):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "report.pdf"
        benchmark.render_benchmark_pdf(str(path), benchmark.aggregate_benchmark_growth(rows),
                                       fieldnames, rows,
                                       sieve_points=benchmark.aggregate_benchmark_sieve_nps(rows))
        return path.read_bytes()


class LayoutTests(unittest.TestCase):
    def test_wrap_header_breaks_after_separators(self):
        self.assertEqual(pdf_table.wrap_header("loop_numbers_per_second", 12),
                         ["loop_", "numbers_per_", "second"])
        self.assertEqual(pdf_table.wrap_header("engine", 3), ["engine"])
        for name in FIELDNAMES:
            for n in (4, 9, 15):
                self.assertEqual("".join(pdf_table.wrap_header(name, n)), name)

    def test_column_fits_value_and_header_part(self):
        self.assertEqual(pdf_table.column_chars("write_files", [{"write_files": "1"}]), 6)
        self.assertEqual(pdf_table.column_chars("x", [{"x": "12345"}, {"x": None}]), 5)

    def test_bands_fit_and_repeat_keys(self):
        rows = [_bench_row(0)]
        keys = ("run_timestamp_utc", "base_exponent", "engine")
        layout = pdf_table.TableLayout(FIELDNAMES, rows, 781.89, 6.5, keys)
        self.assertGreater(len(layout.bands), 1)
        seen = []
        for band in layout.bands:
            self.assertLessEqual(sum(layout.widths[n] for n in band), 781.89)
            for k in keys:
                self.assertIn(k, band)
            seen += [n for n in band if n not in keys]
        self.assertEqual(sorted(seen + list(keys)), sorted(FIELDNAMES))
        for band in layout.bands:
            self.assertEqual(band[:len(keys)], list(keys))
            rest = band[len(keys):]
            self.assertEqual(rest, [n for n in FIELDNAMES if n in rest])

    def test_narrow_table_is_one_band(self):
        layout = pdf_table.TableLayout(["a", "b"], [{"a": "1", "b": "2"}], 781.89, 6.5, ("a",))
        self.assertEqual(layout.bands, [["a", "b"]])
        layout = pdf_table.TableLayout(["a", "b"], [{"a": "1", "b": "2"}], 781.89, 6.5, ("b",))
        self.assertEqual(layout.bands, [["b", "a"]])


class BenchmarkReportTests(unittest.TestCase):
    def test_every_value_printed_in_full(self):
        rows = [_bench_row(i) for i in range(3)]
        texts = _texts(_bench_pdf(rows))
        printed = {t[5] for t in texts if t[1] == "Courier"}
        for row in rows:
            for name in FIELDNAMES:
                self.assertIn(row[name], printed, name)
        self.assertFalse([t for t in texts if t[1] == "Courier" and t[5].endswith("...")])

    def test_missing_value_prints_a_dash(self):
        rows = [dict(_bench_row(0), max_child_rss_mb="", engine="")]
        texts = _texts(_bench_pdf(rows))
        printed = [t[5] for t in texts if t[1] == "Courier"]
        self.assertIn("-", printed, "a value the run lacks prints a dash")
        self.assertFalse([s for s in printed if "?" in s], "no unprintable character")

    def test_headers_printed_in_full(self):
        texts = _texts(_bench_pdf([_bench_row(0)]))
        header_lines = {t[5] for t in texts if t[1] == "Courier-Bold"}
        for name in FIELDNAMES:
            for n in range(1, 30):
                if set(pdf_table.wrap_header(name, n)) <= header_lines:
                    break
            else:
                self.fail(f"header {name} not printed in full")

    def test_text_stays_on_the_page_at_readable_size(self):
        texts = _texts(_bench_pdf([_bench_row(i) for i in range(3)]))
        for _page, font, size, x, _y, s in texts:
            if font.startswith("Courier"):
                self.assertGreaterEqual(size, 6.5)
                self.assertLessEqual(x + len(s) * 0.6 * size, PAGE_RIGHT + 0.01, s)

    def test_key_columns_repeat_per_band_and_all_rows_paginate(self):
        rows = [_bench_row(i) for i in range(150)]
        texts = _texts(_bench_pdf(rows))
        tables = benchmark.benchmark_pdf_tables(FIELDNAMES)
        stamps = [t for t in texts if t[1] == "Courier" and t[5].endswith(" UTC")]
        for row in rows:
            self.assertEqual(len([t for t in stamps if t[5] == row["run_timestamp_utc"]]),
                             len(tables), row["run_timestamp_utc"])

    def test_logical_tables_cover_every_column_once_and_fit_the_page(self):
        tables = benchmark.benchmark_pdf_tables(FIELDNAMES + ["zz_new"])
        keys = list(benchmark.BENCHMARK_PDF_KEY_COLUMNS)
        self.assertEqual(len(tables), 5)                       # 4 tables + "other"
        self.assertEqual(tables[-1][1], keys + ["zz_new"])
        seen = []
        for _title_key, columns in tables:
            self.assertEqual(columns[:3], keys)
            seen += columns[3:]
            layout = pdf_table.TableLayout(columns, [_bench_row(0)], 781.89, 6.5, keys)
            self.assertEqual(len(layout.bands), 1, columns)
        self.assertEqual(sorted(seen + keys), sorted(FIELDNAMES + ["zz_new"]))
        self.assertEqual(len(benchmark.benchmark_pdf_tables(FIELDNAMES)), 4)

    def test_each_table_starts_a_page_under_its_title(self):
        texts = _texts(_bench_pdf([_bench_row(i) for i in range(3)]))
        tr = benchmark.Translator("en").t
        for title_key, columns in benchmark.benchmark_pdf_tables(FIELDNAMES):
            title = [t for t in texts if t[5] == tr(title_key)]
            self.assertEqual(len(title), 1, title_key)
            page = title[0][0]
            headers = {t[5] for t in texts if t[0] == page and t[1] == "Courier-Bold"}
            for name in columns:
                self.assertTrue(set(pdf_table.wrap_header(name, 99)) <= headers
                                or any(h.startswith(name.split("_")[0]) for h in headers),
                                name)


class ChartTests(unittest.TestCase):
    def _dense_rows(self):
        rows = []
        for floor in range(10, 30):
            for i, engine in enumerate(("v4.1", "v5", "pt1", "")):
                rows.append(dict(base_exponent=str(floor), engine=engine,
                                 loop_numbers_per_second=str(1e8 + i * 1e6 + floor),
                                 loop_seconds_per_window="0.1", numbers_processed="100",
                                 windows_written="10", sieve_seconds=str(1 + i * 0.01),
                                 bytes_written="2000000", write_seconds=str(1 + i * 0.01)))
        return rows

    def test_one_metric_per_chart(self):
        rows = self._dense_rows()
        texts = _texts(_bench_pdf(rows, ["base_exponent"]))
        tr = benchmark.Translator("en").t
        titles = [t for t in texts if t[1] == "Helvetica-Bold" and t[5] in {
            tr("bench.axis_total_nps"), tr("bench.axis_write_mbps"),
            tr("bench.axis_sieve_nps"), tr("bench.axis_sieve_spw")}]
        self.assertEqual(len(titles), 4)
        self.assertEqual(len({(t[0], t[4]) for t in titles}), 4)   # four separate boxes

    def test_value_labels_never_overlap_and_each_line_keeps_its_last(self):
        rows = self._dense_rows()
        series = chart_series.engine_series(benchmark.benchmark_engine_lines(rows, "growth"))
        ops = chart_pdf.chart_ops(0, 0, 780, 230, series)
        stream = "stream\n" + "\n".join(ops) + "\nendstream"
        labels = [t for t in _texts(stream.encode("latin-1"))
                  if t[1] == "Courier" and t[2] == 7 and "," in t[5]]
        boxes = [(x, y, x + len(s) * 0.6 * 7, y + 7) for _p, _f, _z, x, y, s in labels]
        for x, y, x2, y2 in boxes:              # inside the box, above the x axis (y 30)
            self.assertTrue(0 <= x and x2 <= 780 and 30 < y and y2 < 230, (x, y))
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3],
                                 (a, b))
        texts = {t[5] for t in labels}
        for s in series:
            self.assertIn(chart_series.point_label("{:,.0f}", s.points[-1][1], s), texts)
        self.assertLess(len(labels), sum(len(s.points) for s in series))


class ConstellationReportTests(unittest.TestCase):
    def test_long_number_printed_in_full(self):
        number = "1" + "0" * 44 + "7"
        rows = [{"exp": "45", "id": "3", "offset": "7", "number": number}]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "records.pdf"
            constellations.render_constellation_records_pdf(
                str(path), 2, ["exp", "id", "offset", "number"], rows)
            texts = _texts(path.read_bytes())
        self.assertIn(number, {t[5] for t in texts if t[1] == "Courier"})


def main():
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
    for case in (LayoutTests, BenchmarkReportTests, ChartTests, ConstellationReportTests):
        suite.addTests(loader.loadTestsFromTestCase(case))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
