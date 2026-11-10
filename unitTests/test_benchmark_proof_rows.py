"""A pt1 run with the verification P -> D (proof_seconds) is drawn twice on the Benchmark charts
(primeatlas/benchmark/proof_rows.py): "pt1.1 P" without the proof and "pt1.1 D proof" with it.

A. split(): the P copy has total, loop and per-second fields without the proof, the D proof
   copy has the proof added to sieve_seconds; both name the logged row (source()); the logged
   row is unchanged; a row without proof_seconds (blank, 0, unreadable) stays one row; a copy
   is never split again.
B. The charts: the sieve and whole-run charts have both lines with the expected values; the
   table's row kind of the logged row is D/P; a pt1_verify row (store verification) is on no
   chart; a pt1 row without a proof stays one P line.
C. Selecting the logged row marks the points of both lines.
D. Breaking attempts: proof_seconds larger than total_seconds leaves the total as it is
   (never a negative time); missing loop fields stay blank.
E. The time model counts a pt1 row without its proof time.
Pure, any platform:
    python unitTests/test_benchmark_proof_rows.py
"""
import csv
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from primeatlas.benchmark import benchmark, chart_points as cp, proof_rows  # noqa: E402
from primeatlas.generation import time_model as tm  # noqa: E402
from benchmark_log_schema import BENCHMARK_FIELDNAMES  # noqa: E402

N = 100_000_000


def _row(proof="8.0", engine="pt1", version="pt1.1", total="9.0", sieve="0.9"):
    row = {name: "" for name in BENCHMARK_FIELDNAMES}
    row.update(base_exponent="29", target_idx_start="0", target_idx_end="9",
               windows_written="10", total_seconds=total, seconds_per_window="0.9",
               total_primes="1500000", primes_per_second=f"{1_500_000 / float(total):.2f}",
               loop_session_seconds="10.0", loop_numbers_per_second=f"{N / 10:.2f}",
               loop_seconds_per_window="1.0", write_files="0", sieve_seconds=sieve,
               write_seconds="0.1", engine=engine, engine_version=version,
               numbers_processed=str(N), threads="24", write_threads="1",
               run_purpose="benchmark", proof_seconds=proof, run_status="completed")
    return row


class SplitTest(unittest.TestCase):
    def test_two_copies(self):
        row = _row()
        logged = dict(row)
        p, d = proof_rows.split(row)
        self.assertEqual(row, logged, "the logged row is unchanged")
        self.assertEqual(p["kind"], "P")
        self.assertEqual(d["kind"], proof_rows.KIND_PROOF)
        self.assertAlmostEqual(float(p["total_seconds"]), 1.0)
        self.assertAlmostEqual(float(p["primes_per_second"]), 1_500_000, delta=1)
        self.assertAlmostEqual(float(p["loop_session_seconds"]), 2.0)
        self.assertAlmostEqual(float(p["loop_numbers_per_second"]), N / 2, delta=1)
        self.assertAlmostEqual(float(p["seconds_per_window"]), 0.1)
        self.assertAlmostEqual(float(p["loop_seconds_per_window"]), 0.2)
        self.assertEqual(p["sieve_seconds"], "0.9", "the sieve alone has no proof in it")
        self.assertAlmostEqual(float(d["sieve_seconds"]), 8.9)
        self.assertEqual(d["total_seconds"], "9.0")
        self.assertIs(proof_rows.source(p), row)
        self.assertIs(proof_rows.source(d), row)
        self.assertIs(proof_rows.source(row), row)

    def test_no_proof_one_row(self):
        for proof in ("", "0", "0.000", "abc", "-1"):
            row = _row(proof=proof)
            self.assertEqual(proof_rows.split(row), [row], proof)

    def test_copy_not_split_again(self):
        copies = proof_rows.chart_rows([_row()])
        self.assertEqual(len(proof_rows.chart_rows(copies)), 2)

    def test_breaking_proof_longer_than_total(self):
        p, _d = proof_rows.split(_row(proof="20", total="9.0"))
        self.assertEqual(p["total_seconds"], "9.0")
        row = _row()
        row.update(loop_session_seconds="", loop_numbers_per_second="")
        p, _d = proof_rows.split(row)
        self.assertEqual(p["loop_session_seconds"], "")
        self.assertEqual(p["loop_numbers_per_second"], "")


def _logged(*rows):
    """The rows as read_benchmark_log() hands them over: with their table kind."""
    return [dict(row, kind=benchmark.benchmark_row_kind(row)) for row in rows]


class ChartTest(unittest.TestCase):
    def test_lines(self):
        rows = _logged(_row(), _row(proof="", version="pt1.1"),
                       _row(engine="pt1_verify", proof="", sieve=""))
        sieve = benchmark.benchmark_engine_lines(rows, "sieve")
        self.assertEqual(sorted(sieve), ["pt1.1 D proof, 24 thr, write 1", "pt1.1 P, 24 thr, write 1"])
        self.assertAlmostEqual(sieve["pt1.1 D proof, 24 thr, write 1"][0][1], N / 8.9, delta=1)
        self.assertAlmostEqual(sieve["pt1.1 P, 24 thr, write 1"][0][1], N / 0.9, delta=1)
        growth = benchmark.benchmark_engine_lines(rows[:1], "growth")
        self.assertAlmostEqual(growth["pt1.1 P, 24 thr, write 1"][0][1], N / 2, delta=1)
        self.assertAlmostEqual(growth["pt1.1 D proof, 24 thr, write 1"][0][1], N / 10, delta=1)
        for metric in ("growth", "sieve", "sieve_spw", "write", "ram"):
            lines = benchmark.benchmark_engine_lines(rows[2:], metric)
            self.assertEqual(lines, {}, f"pt1_verify on no chart ({metric})")
        engines = benchmark.benchmark_line_engines(rows[:1])
        self.assertEqual(set(engines.values()), {"pt1 P", "pt1 D proof"})

    def test_table_kind(self):
        self.assertEqual(benchmark.benchmark_row_kind(_row()), "D/P")
        self.assertEqual(benchmark.benchmark_row_kind(_row(proof="")), "P")

    def test_selection_marks_both(self):
        rows = _logged(_row(), _row(proof="0", version="pt1.1"))
        view = cp.PointView(cp.X_FLOOR, cp.SELECTED, rows[0])
        marks = benchmark.selected_marks(rows, "sieve", view)
        self.assertEqual({name for name, _x, _y in marks},
                         {"pt1.1 D proof, 24 thr, write 1", "pt1.1 P, 24 thr, write 1"})

    def test_read_log_keeps_one_row(self):
        with tempfile.TemporaryDirectory() as portal:
            with open(os.path.join(portal, "benchmark_log.csv"), "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=BENCHMARK_FIELDNAMES)
                writer.writeheader()
                writer.writerow(_row())
            _fields, rows = benchmark.read_benchmark_log(portal)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "D/P")


class TimeModelTest(unittest.TestCase):
    def test_proof_not_counted(self):
        with_proof = tm._sample(_row())
        without = tm._sample(_row(proof=""))
        self.assertAlmostEqual(with_proof.total_seconds, 1.0)
        self.assertAlmostEqual(without.total_seconds, 9.0)


if __name__ == "__main__":
    unittest.main()
