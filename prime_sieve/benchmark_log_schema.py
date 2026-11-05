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
- engine_version: the writing script's own VERSION (v5.1, v6.0, primesieve mode v1.0, ...),
  while `engine` keeps the selector name (v5, v6, primesieve); the time model calibrates
  each engine from the rows of its newest version.
- threads: the CPU threads (or processes) one run of the engine sieved on -- the worker
  count of v4.1/v5/v6/pt1, the count primesieve reports for a native count, 1 for runs that
  sieve on one thread (native print, the primesieve wrapper, hybrid), THREADS_GPU for GPU
  engines. Several instances of orchestrator_loop_v2 each log their own count;
  instance_of_n says how many ran side by side.
- write_threads: the threads that wrote the output -- v6's write-thread knob, 1 for every
  other writer; blank for runs that write nothing (native count).
- engine tags of primesieve mode: ENGINE_PRIMESIEVE_ATLAS for the wrapper that converts the
  library's result into Atlas windows (its time includes that conversion),
  ENGINE_PRIMESIEVE_PRINT and ENGINE_PRIMESIEVE_COUNT for the native primesieve program
  (primesieve_native.py): its own --print text output (sieve + every prime printed, a
  whole run), or its --count (sieve + bit count, the work of an engine's sieve phase).
- sieve_wall_seconds: the sieve timed from outside the engine -- orchestrator_v3 takes the
  time from launching the scanner process to its "Batch sieve done" line (Python start,
  imports, buffer allocation, library load and sieving primes included; the optional
  base_gen_seconds diagnostic left out), while sieve_seconds is the engine's own timer
  around the sieve alone. Blank for engines with no such line (pt1 overlaps sieve and
  write) and for other writers, native primesieve included: its one process has no split
  between setup and sieve to measure.
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
    "verify_seconds", "engine_version", "threads", "write_threads", "sieve_wall_seconds",
]

ENGINE_PRIMESIEVE_ATLAS = "primesieve"
ENGINE_PRIMESIEVE_PRINT = "primesieve_print"
ENGINE_PRIMESIEVE_COUNT = "primesieve_count"
THREADS_GPU = "GPU"

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
