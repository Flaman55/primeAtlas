"""Read-only legacy display and append-only schema upgrade across Atlas engines."""
import csv
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'prime_sieve')]
import hybrid_sieve
import orchestrator_v3
import orchestrator_loop_helpers
import prime_sieve_primesieve
import prime_sieve_cudasieve
from primeatlas.benchmark import read_benchmark_log, aggregate_benchmark_sieve_nps

FIELDS = hybrid_sieve.BENCHMARK_FIELDNAMES[:-2]  # main schema, before engine/count


class CompatibilityTests(unittest.TestCase):
    def seed(self, folder):
        path = Path(folder) / 'benchmark_log.csv'
        rows = [dict(base_exponent='8', windows_written='2', sieve_seconds='0.5',
                     write_files='1', total_seconds='1.25', instance_of_n='1/1'),
                dict(base_exponent='3', windows_written='1', sieve_seconds='0.01',
                     write_files='0')]
        with path.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        with path.open() as stream:
            return path, list(csv.DictReader(stream))

    def test_legacy_read_preserves_rows_without_inventing_throughput(self):
        with tempfile.TemporaryDirectory() as folder:
            path, original = self.seed(folder)
            before = path.read_bytes()
            fields, rows = read_benchmark_log(folder)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(aggregate_benchmark_sieve_nps(rows), [])
            for row, old in zip(rows, original):
                self.assertEqual({k: row[k] for k in FIELDS}, old)
                self.assertEqual(row['engine'], 'unknown')
                self.assertEqual(row['sieve_count_basis'], 'unavailable')

    def test_mixed_engine_append_preserves_history_and_storage(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            path, original = self.seed(folder)
            storage = Path(folder) / '10p8' / 'source_primes' / 'shard_00000'
            storage.mkdir(parents=True)
            from hybrid_reference import write_new_pgs2_floor_window
            write_new_pgs2_floor_window(folder, 8, 0, 10_000_000, [100000007])
            before = {p: p.read_bytes() for p in storage.glob('*.bin')}
            self.assertTrue(before)
            hybrid_sieve.write_hybrid_benchmark_row(folder, 8, 1, 1, 1, 1, False,
                                                   0, 0.5, 0, 0, 99)
            orchestrator_v3.print_benchmark_summary(8, 2, 3, 1, folder, write_files=False,
                total_primes_found=1, windows_processed=1, sieve_seconds=0.5,
                numbers_processed=10_000_000)
            for module in (prime_sieve_primesieve, prime_sieve_cudasieve):
                module.write_benchmark_row(8, 3, 1, 1, 1, 1, False, folder)
            orchestrator_loop_helpers._ensure_benchmark_log_schema(str(path))
            with path.open() as stream:
                reader = csv.DictReader(stream)
                rows = list(reader)
                self.assertEqual(reader.fieldnames, hybrid_sieve.BENCHMARK_FIELDNAMES)
            for row, old in zip(rows, original):
                self.assertEqual({k: row[k] for k in FIELDS}, old)
                self.assertEqual(row['engine'], '')
                self.assertEqual(row['numbers_processed'], '')
            self.assertEqual([r['engine'] for r in rows[2:]], ['hybrid', 'v4.1', 'primesieve', 'cuda'])
            self.assertEqual({p: p.read_bytes() for p in storage.glob('*.bin')}, before)
            _, displayed = read_benchmark_log(folder)
            self.assertEqual(displayed[2]['sieve_count_basis'], 'measured')
            self.assertEqual(aggregate_benchmark_sieve_nps(displayed), [(8, 20_000_000.0)])

    def test_failed_upgrade_keeps_original_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path, _ = self.seed(folder)
            before = path.read_bytes()
            with patch.object(hybrid_sieve.os, 'replace', side_effect=OSError('simulated failure')):
                with self.assertRaises(OSError):
                    hybrid_sieve.write_hybrid_benchmark_row(folder, 8, 1, 1, 1, 1, False,
                                                           0, 0.5, 0, 0, 99)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(folder).glob('.benchmark_*')), [])


if __name__ == '__main__':
    unittest.main()
