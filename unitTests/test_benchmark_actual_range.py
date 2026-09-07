"""Benchmark throughput must follow actual sieve work, not storage capacity."""
import csv
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve")]

from primeatlas.benchmark import aggregate_benchmark_sieve_nps
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
            row = dict(base_exponent="9", windows_written="1",
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


if __name__ == "__main__":
    unittest.main()
