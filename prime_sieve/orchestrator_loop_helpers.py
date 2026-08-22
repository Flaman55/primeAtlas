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
import re
import csv


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


def find_auto_start(base_exponent, portal_folder, window_m):
    """Looks for already-written PRIME_WINDOW_*.bin files for this base_exponent under
    portal_folder/10p{N}/source_primes/. Returns the target_idx right AFTER the highest
    window already done -- a safe continuation point with no manual offset arithmetic.
    Returns None if nothing was found (caller should then use the fallback)."""
    pattern = re.compile(rf"^PRIME_WINDOW_10p{base_exponent}_off_(\d+)(M)?\.bin$")
    highest_target_idx = None

    source_dir = os.path.join(portal_folder, f"10p{base_exponent}", "source_primes")
    if os.path.isdir(source_dir):
        for name in os.listdir(source_dir):
            m = pattern.match(name)
            if not m:
                continue
            number = int(m.group(1))
            offset = number * 1_000_000 if m.group(2) else number
            target_idx = offset // window_m
            if highest_target_idx is None or target_idx > highest_target_idx:
                highest_target_idx = target_idx

    if highest_target_idx is None:
        return None
    return highest_target_idx + 1


WINDOW_M = 10 ** 7

BENCHMARK_FIELDNAMES = [
    "run_timestamp_utc", "base_exponent", "target_idx_start", "target_idx_end",
    "windows_written", "total_seconds", "seconds_per_window", "total_primes",
    "avg_primes_per_window", "primes_per_second",
    "l_final", "sieving_primes_count", "max_child_rss_mb",
    "instance_of_n", "loop_session_seconds", "loop_numbers_per_second",
    "loop_seconds_per_window",
]


def _ensure_benchmark_log_schema(log_path):
    """Same schema-migration logic as orchestrator_v1.py -- see that file's docstring.
    Rewrite is ATOMIC (temp file + os.replace()) -- see that file's docstring for why."""
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
