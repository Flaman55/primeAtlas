"""
orchestrator_loop_helpers.py -- the 4 symbols orchestrator_loop_v2.py actually uses
(find_auto_start, WINDOW_M, _parse_bool_arg, _ensure_benchmark_log_schema), extracted into
their own tiny, dependency-free module.

This self-contained app copy of the pipeline doesn't need to import a full orchestrator
module (with its own scanning/CLI logic and ctypes sieve-engine dependency) just to reach
four small helper functions, so they live here instead as a standalone extraction.

If a bug is ever found in one of these four functions, the equivalent logic in the full
orchestrator module(s) elsewhere in the project likely needs the same fix.
"""
import os
import csv

import storage_kinds


def _parse_bool_arg(value):
    """Parses a CLI flag as a boolean. Primary form: 0/1 -- quicker to type on the WSL
    command line than true/false. Also accepts true/false/yes/no/on/off (case-insensitive)
    if you'd rather spell it out. Raises ValueError on anything else, so a typo in the WSL
    invocation fails loudly instead of silently picking the wrong mode."""
    v = value.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"expected 0/1 (or true/false, yes/no, on/off) for auto mode, got: {value!r}")


def find_auto_start(base_exponent, portal_folder, window_m, engine=None):
    """The target_idx right AFTER the highest window `engine` already counts as done on
    this floor (storage_kinds.engine_target_idxs(): the store that engine writes into), or
    None if there is none (caller should then use the fallback). engine defaults to
    PRIMEATLAS_SCANNER_VERSION, as orchestrator_v3.py's SCANNER_VERSION does."""
    if engine is None:
        engine = os.environ.get("PRIMEATLAS_SCANNER_VERSION") or "v5"
    idxs = storage_kinds.engine_target_idxs(portal_folder, base_exponent, window_m, engine)
    return max(idxs) + 1 if idxs else None


WINDOW_M = 10 ** 7

BENCHMARK_FIELDNAMES = [
    "run_timestamp_utc", "base_exponent", "target_idx_start", "target_idx_end",
    "windows_written", "total_seconds", "seconds_per_window", "total_primes",
    "avg_primes_per_window", "primes_per_second", "l_final", "sieving_primes_count",
    "max_child_rss_mb", "instance_of_n", "loop_session_seconds", "loop_numbers_per_second",
    "loop_seconds_per_window", "write_files", "base_gen_seconds", "sieve_seconds",
    "write_seconds", "bytes_written", "engine", "numbers_processed", "run_status",
]


def _ensure_benchmark_log_schema(log_path):
    """Migrates benchmark_log.csv's header to the current BENCHMARK_FIELDNAMES (adding
    missing columns to every existing row). Rewrite is ATOMIC (temp file + os.replace()):
    the file holds the whole benchmark history."""
    if not os.path.exists(log_path):
        return
    with open(log_path, newline="") as f:
        reader = csv.DictReader(f)
        existing_fields = reader.fieldnames or []
        rows = list(reader)
    if existing_fields == BENCHMARK_FIELDNAMES:
        return
    if not all(field in BENCHMARK_FIELDNAMES for field in existing_fields):
        return
    tmp_path = f"{log_path}.tmp{os.getpid()}"
    with open(tmp_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BENCHMARK_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in BENCHMARK_FIELDNAMES})
    os.replace(tmp_path, log_path)
