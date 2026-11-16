"""
run_load.py -- the machine and CPU load columns of a benchmark_log.csv row: which computer ran
the run (machine_id) and how busy its CPU was before the run (cpu_busy_before_pct) and while
it ran (cpu_busy_during_pct), both as the percentage of the whole Windows CPU, Atlas included.

The GUI measures; the engines only copy. At launch the GUI names, in the run's environment:
- MACHINE_ID_ENV: this computer's id (windows_hardware.this_machine_id());
- CPU_BUSY_BEFORE_ENV: the busy share over the seconds before the launch (cpu_load);
- LOAD_FILE_ENV: the run's load file, where the GUI keeps the current Windows CPU counters
  (one line "idle total", 100 ns ticks of all CPUs, total = kernel + user), written before
  the process starts and about once a second while it runs.
A process importing this module reads the file once (START_COUNTERS); row_fields() reads it
again when the row is written, so the during share covers that process's own run, also for
each orchestrator of a Loop. A value the environment does not name, or cannot be read, stays
blank: a run started outside the GUI has blank columns, never a guess.

Standard library only, like benchmark_log_schema.py: the engines run under WSL with only
prime_sieve/ on sys.path.
"""
import math
import os
import re

MACHINE_ID_ENV = "PRIMEATLAS_MACHINE_ID"
CPU_BUSY_BEFORE_ENV = "PRIMEATLAS_CPU_BUSY_BEFORE_PCT"
LOAD_FILE_ENV = "PRIMEATLAS_RUN_LOAD_FILE"

COLUMNS = ("machine_id", "cpu_busy_before_pct", "cpu_busy_during_pct")

_MACHINE_ID_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def busy_pct(start, end):
    """The busy share in percent between two (idle, total) counter pairs; None when either is
    missing, no time passed, or the counters do not move forward consistently."""
    if start is None or end is None:
        return None
    total = end[1] - start[1]
    idle = end[0] - start[0]
    if total <= 0 or idle < 0 or idle > total:
        return None
    return 100.0 * (total - idle) / total


def format_pct(value):
    """A share in percent as the log keeps it ("12.3"); "" for None."""
    return "" if value is None else f"{value:.1f}"


def write_counters(path, counters):
    """Writes the (idle, total) pair to the load file at `path`, replacing it whole (temp file
    + os.replace()), so a reader sees the old pair or the new one, never half of one."""
    tmp_path = f"{path}.tmp{os.getpid()}"
    with open(tmp_path, "w", encoding="ascii") as f:
        f.write(f"{int(counters[0])} {int(counters[1])}\n")
    os.replace(tmp_path, path)


def read_counters(path):
    """The (idle, total) pair in the load file at `path`; None when there is no such file or
    it holds anything but two non-negative integers."""
    if not path:
        return None
    try:
        with open(path, encoding="ascii") as f:
            parts = f.read().split()
    except (OSError, UnicodeDecodeError):
        return None
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    return int(parts[0]), int(parts[1])


def start_counters(environ):
    """The pair in the load file `environ` names, or None."""
    return read_counters(environ.get(LOAD_FILE_ENV))


START_COUNTERS = start_counters(os.environ)


def _machine_id(environ):
    value = str(environ.get(MACHINE_ID_ENV) or "").strip()
    return value if _MACHINE_ID_RE.fullmatch(value) else ""


def _before(environ):
    try:
        value = float(str(environ.get(CPU_BUSY_BEFORE_ENV) or "").strip())
    except ValueError:
        return ""
    if not math.isfinite(value) or not 0.0 <= value <= 100.0:
        return ""
    return format_pct(value)


def row_fields(environ, start=START_COUNTERS):
    """{column: value} of the three columns for a row written now: the machine id and the
    before share as the environment names them, the during share from `start` to the load
    file's current pair; "" for what is not known."""
    during = busy_pct(start, read_counters(environ.get(LOAD_FILE_ENV)))
    return {"machine_id": _machine_id(environ), "cpu_busy_before_pct": _before(environ),
            "cpu_busy_during_pct": format_pct(during)}
