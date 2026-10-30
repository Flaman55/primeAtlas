"""Benchmark throughput must follow actual sieve work, not storage capacity."""
import csv
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve")]

from primeatlas.benchmark import benchmark
from primeatlas.benchmark.benchmark import aggregate_benchmark_sieve_nps
from hybrid_sieve import write_hybrid_benchmark_row


class ActualRangeTests(unittest.TestCase):
    def test_measured_count_overrides_window_capacity(self):
        for windows in (1, 2, 100):
            row = dict(base_exponent="7", windows_written=str(windows),
                       numbers_processed="99", sieve_seconds="0.004")
            self.assertEqual(aggregate_benchmark_sieve_nps([row]), [(7, 24750.0)])

    def test_existing_single_low_floor_hybrid_measurements(self):
        rows = [dict(base_exponent=str(floor), engine="hybrid", windows_written="1",
                     target_idx_start="0", sieve_seconds="0.004") for floor in range(4)]
        self.assertEqual(aggregate_benchmark_sieve_nps(rows),
                         [(0, 2250.0), (1, 22500.0), (2, 225000.0), (3, 2250000.0)])

    def test_unknown_or_invalid_work_is_not_estimated(self):
        for count in (None, "", "nan", "-1", "0"):
            row = dict(base_exponent="9", windows_written="1", engine="hybrid",
                       numbers_processed=count, sieve_seconds="1")
            self.assertEqual(aggregate_benchmark_sieve_nps([row]), [])
        for seconds in ("0", "-1", "nan", "inf"):
            self.assertEqual(aggregate_benchmark_sieve_nps([
                dict(base_exponent="9", numbers_processed="99", sieve_seconds=seconds)]), [])

    def test_writer_preserves_small_phase_times_and_schema(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "benchmark_log.csv"
            path.write_text("base_exponent,engine\n8,v4.1\n")
            write_hybrid_benchmark_row(folder, 0, 0, 1, 0.03, 4, False,
                                       0, 0.000004, 0, 0, 9)
            with path.open() as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["engine"], "v4.1")
            self.assertEqual(rows[1]["numbers_processed"], "9")
            self.assertEqual(float(rows[1]["loop_numbers_per_second"]), 300)
            self.assertEqual(aggregate_benchmark_sieve_nps(rows), [(0, 2250000.0)])


def _phase_row(floor, engine, sieve_seconds="1", write_seconds="1"):
    return dict(base_exponent=str(floor), engine=engine, numbers_processed="100",
                sieve_seconds=sieve_seconds, bytes_written="2000000",
                write_seconds=write_seconds)


class PhaseChartEngineTests(unittest.TestCase):
    """The phase-breakdown chart names the engine of every point it draws."""

    def test_engine_follows_the_row_each_reduction_keeps(self):
        rows = [_phase_row(25, "v4.1"), _phase_row(25, "v5", write_seconds="0"),
                _phase_row(20, "v5"), _phase_row(20, "v4.1", sieve_seconds="nan")]
        self.assertEqual(benchmark.benchmark_sieve_engines(rows), {25: "v5", 20: "v5"})
        self.assertEqual(benchmark.benchmark_write_engines(rows), {25: "v4.1", 20: "v4.1"})
        self.assertEqual(set(benchmark.benchmark_sieve_engines(rows)),
                         {f for f, _ in benchmark.aggregate_benchmark_sieve_nps(rows)})
        self.assertEqual(set(benchmark.benchmark_write_engines(rows)),
                         {f for f, _ in benchmark.aggregate_benchmark_write_mbps(rows)})

    def test_pdf_tags_both_series_and_skips_unknown(self):
        ops = "\n".join(benchmark._pdf_chart_ops(
            [(20, 5.0), (21, 6.0)], 0, 0, 800, 140, points2=[(20, 1.5), (21, 2.5)],
            engines={20: "v5", 21: "unknown"}, engines2={20: "v4.1", 21: "unknown"},
            fmt2="{:,.1f}"))
        self.assertIn("5 [v5]", ops)
        self.assertIn("1.5 [v4.1]", ops)
        self.assertNotIn("[unknown]", ops)

    def test_pdf_report_tags_phase_chart(self):
        rows = [_phase_row(20, "v5")]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "report.pdf"
            benchmark.render_benchmark_pdf(
                str(path), [], ["base_exponent"], rows,
                sieve_points=benchmark.aggregate_benchmark_sieve_nps(rows),
                write_points=benchmark.aggregate_benchmark_write_mbps(rows))
            text = path.read_bytes().decode("latin-1")
        self.assertIn("100 [v5]", text)
        self.assertIn("2.0 [v5]", text)

    def test_hint_no_longer_claims_v4_1_only(self):
        import json
        for lang in ("en", "pl"):
            strings = json.loads((ROOT / "primeatlas" / "core" / "locales"
                                  / f"strings_{lang}.json").read_text(encoding="utf-8"))
            self.assertNotIn("v4_1", strings["bench.chart2_hint"])

    def test_canvas_hover_tags_both_series(self):
        import tkinter as tk
        from primeatlas.benchmark import benchmark_tab
        captured = []
        original = benchmark_tab._bind_chart_hover
        benchmark_tab._bind_chart_hover = lambda canvas, points, *a: captured.extend(points)
        try:
            root = tk.Tk()
            try:
                canvas = tk.Canvas(root)
                benchmark_tab._draw_growth_chart(
                    canvas, [(20, 5.0)], 900, 200, points2=[(20, 1.5)],
                    engines={20: "v5"}, engines2={20: "v4.1"})
            finally:
                root.destroy()
        finally:
            benchmark_tab._bind_chart_hover = original
        fmts = [p[4] for p in captured]
        self.assertTrue(any(f.endswith(" [v5]") for f in fmts), fmts)
        self.assertTrue(any(f.endswith(" [v4.1]") for f in fmts), fmts)


if __name__ == "__main__":
    unittest.main()
