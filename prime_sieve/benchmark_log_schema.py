"""
benchmark_log_schema.py -- the one header of benchmark_log.csv and its migration.

Every engine writes to the same benchmark_log.csv at the storage root, so the Benchmark tab
sees one history whichever engine produced which floor. The writers (orchestrator_v3.py,
orchestrator_loop_helpers.py, prime_sieve_primesieve.py, prime_sieve_cudasieve.py,
hybrid_sieve.py) and the GUI's floor_meta.py import the header from here. This module
depends only on the standard library, so the engines stay runnable standalone under WSL
with only prime_sieve/ on sys.path.

Column notes:
- write_files: "1"/"0"; separates disk-writing runs from count-only benchmark runs of the
  same floor/range, so a floor's real generation time sums only the first kind.
- base_gen_seconds/sieve_seconds/write_seconds/bytes_written: the phase breakdown the
  Benchmark tab charts; blank in rows from engines that never measured it.
- engine, numbers_processed: which engine wrote the row and how many integers it covered.
- run_status: RUN_STATUS_COMPLETED, or RUN_STATUS_STOPPED for a run ended by the GUI's stop
  request (generation_stop.py), whose counts cover the windows written before the stop.
- verify_seconds: the D-proves-P comparison time (dp_verify.py) included in total_seconds;
  blank in rows from writers that do not compare and in rows from before the column.
Rows written before a column existed keep it blank: a migration never guesses old values,
and a blank run_status means completed.

The order is the order of the existing logs. A writer whose list differed in order would
rewrite every log it touches, so a new column goes at the end.
"""
import csv
import os

BENCHMARK_FIELDNAMES = [
    "run_timestamp_utc", "base_exponent", "target_idx_start", "target_idx_end",
    "windows_written", "total_seconds", "seconds_per_window", "total_primes",
    "avg_primes_per_window", "primes_per_second", "l_final", "sieving_primes_count",
    "max_child_rss_mb", "instance_of_n", "loop_session_seconds", "loop_numbers_per_second",
    "loop_seconds_per_window", "write_files", "base_gen_seconds", "sieve_seconds",
    "write_seconds", "bytes_written", "engine", "numbers_processed", "run_status",
    "verify_seconds",
]

RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_STOPPED = "stopped"


def ensure_benchmark_log_schema(log_path):
    """Brings an existing log's header to BENCHMARK_FIELDNAMES, adding the missing columns
    (blank) to every old row. Returns True when the log is absent or now has the current
    header; False when its header has a column this schema does not know -- then the file
    is left as it is, since rewriting it would drop that column. The rewrite is atomic
    (temp file + os.replace()): the file holds the whole benchmark history."""
    if not os.path.exists(log_path):
        return True
    with open(log_path, newline="") as f:
        reader = csv.DictReader(f)
        existing_fields = reader.fieldnames or []
        rows = list(reader)
    if existing_fields == BENCHMARK_FIELDNAMES:
        return True
    if not all(field in BENCHMARK_FIELDNAMES for field in existing_fields):
        return False
    tmp_path = f"{log_path}.tmp{os.getpid()}"
    try:
        with open(tmp_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=BENCHMARK_FIELDNAMES)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in BENCHMARK_FIELDNAMES})
        os.replace(tmp_path, log_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return True
