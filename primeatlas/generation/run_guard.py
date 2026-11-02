"""
run_guard.py -- the tkinter-free half of the close guard (CLOSE_GUARD_PLAN.md): the stage
label of a job's output tail, the generation stop request the GUI writes, the active-run
marker every generation launch leaves in .generation_logs/, and the recovery of a run that
never reported back to the GUI (the app was closed or killed while WSL kept going).

  - job_stage(lines) -> (key, detail)         stage of a job from its last output lines
  - write_stop_request / clear_stop_request    generation_stop.py's request file
  - write_active_run / read_active_run / clear_active_run
  - recover_unfinished_run(portal, is_alive, rescan_floor) -> dict
  - wsl_process_alive(pattern), rescan_floor_totals(portal, floor): the real
    is_alive / rescan_floor used by the app
  - kill_wsl_processes(pattern)                the scanner kill of the save-point stop
"""
import json
import os
import re
import subprocess
import time

import generation_stop
import storage_kinds
import window_integrity

from ..core.storage import (load_totals_cache, save_totals_cache, bump_floor_total,
                            update_floor_totals_cache)
from ..benchmark.benchmark import read_benchmark_log
from .generation import (GENERATION_LOGS_DIRNAME, _GEN_CONST_PROGRESS_RE, _GEN_SIEVE_PROGRESS_RE,
                         _popen_kwargs_no_window, compute_totals_bumps_from_new_rows)

ACTIVE_RUN_FILENAME = "ACTIVE_RUN.json"
STAGE_LINE_MAX = 80

# (stage key, pattern); the last line matching any of them gives the stage.
_STAGE_PATTERNS = (
    ("counting", re.compile(r"\[\*\] Counting the primes of the written windows")),
    ("checking", re.compile(r"\[\*\] Checking the windows written before the stop")),
    ("verifying", re.compile(r"\[\*\] D proves P")),
    ("starting_batch", re.compile(r"Launching batch target_idx")),
)
# Progress lines of the search tools; the stage shows the line itself.
_SEARCH_PATTERNS = (
    _GEN_CONST_PROGRESS_RE,
    re.compile(r"\[KTUPLE SIEVE v2\] batch \d+, \d+/\d+:"),
)


def job_stage(lines):
    """(key, detail) of the last stage-bearing line of `lines`: ("sieving", "42.10%") for a
    scanner progress line, ("counting" | "checking" | "verifying" | "starting_batch", None)
    for the orchestrator's own stage lines, ("searching", line) for a constellation /
    k-tuple progress line; with no such line, ("line", text) with the last non-blank line;
    both texts cut to STAGE_LINE_MAX characters. ("idle", None) for no output."""
    last_text = None
    for line in reversed(list(lines)):
        text = line.strip()
        if not text:
            continue
        if last_text is None:
            last_text = text
        m = _GEN_SIEVE_PROGRESS_RE.search(text)
        if m:
            return "sieving", f"{m.group(1)}%"
        for key, pattern in _STAGE_PATTERNS:
            if pattern.search(text):
                return key, None
        if any(pattern.search(text) for pattern in _SEARCH_PATTERNS):
            return "searching", text[:STAGE_LINE_MAX]
    if last_text is None:
        return "idle", None
    return "line", last_text[:STAGE_LINE_MAX]


def write_stop_request(portal_folder):
    """Writes the generation stop request; False when the storage folder is unreachable."""
    try:
        with open(generation_stop.stop_request_path(portal_folder), "w", encoding="utf-8") as f:
            f.write(f"stop requested by the GUI at {time.time():.0f}\n")
        return True
    except OSError:
        return False


def clear_stop_request(portal_folder):
    try:
        os.remove(generation_stop.stop_request_path(portal_folder))
    except OSError:
        pass


def active_run_path(portal_folder):
    return os.path.join(portal_folder, GENERATION_LOGS_DIRNAME, ACTIVE_RUN_FILENAME)


def write_active_run(portal_folder, info):
    """Writes the marker of the generation run being launched (CLOSE_GUARD_PLAN.md
    section 5); best-effort, a run without a marker just cannot be recovered."""
    path = active_run_path(portal_folder)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(info, f)
    except OSError:
        pass


def read_active_run(portal_folder):
    """The marker's dict, or None when there is none or it does not parse."""
    try:
        with open(active_run_path(portal_folder), encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        return None
    return info if isinstance(info, dict) else None


def clear_active_run(portal_folder):
    try:
        os.remove(active_run_path(portal_folder))
    except OSError:
        pass


def _run_window_paths(portal_folder, info):
    """Window files of the marker's floor at or after its first target_idx, both stores."""
    floor = info.get("base_exponent")
    if floor is None:
        return []
    first_offset = int(info.get("first_target_idx") or 0) * int(info.get("window_m") or 0)
    paths = []
    for kind in storage_kinds.KINDS:
        for name, path in storage_kinds.list_window_files(portal_folder, floor, kind):
            offset = storage_kinds.offset_from_name(name)
            if offset is None or offset >= first_offset:
                paths.append(path)
    return paths


def recover_unfinished_run(portal_folder, is_alive, rescan_floor):
    """Settles a generation run whose marker is still on disk at start-up.

    Returns {"status": "none" | "alive" | "recovered", "bumped_rows": n,
    "deleted_windows": [paths], "rescanned": bool, "info": marker or None}.
    - no marker: "none".
    - is_alive(kill_pattern) True: "alive", marker kept for the next start.
    - otherwise: the totals cache is bumped from the benchmark rows logged since the
      marker's row count; with none, the windows written after the marker's start and at
      most 60 s before the newest of them are checked (window_integrity.repair_recent,
      cut ones deleted) and rescan_floor(portal,
      floor) recounts the floor. Leftover log / exit / stop-request files and the marker
      are deleted."""
    result = {"status": "none", "bumped_rows": 0, "deleted_windows": [], "rescanned": False,
              "info": None}
    info = read_active_run(portal_folder)
    if info is None:
        return result
    result["info"] = info
    pattern = info.get("kill_pattern")
    if pattern and is_alive(pattern):
        result["status"] = "alive"
        return result

    _fieldnames, rows = read_benchmark_log(portal_folder)
    bumps = compute_totals_bumps_from_new_rows(rows, int(info.get("rows_before") or 0))
    new_rows = rows[int(info.get("rows_before") or 0):]
    if bumps:
        cache = load_totals_cache(portal_folder)
        for base_exponent, delta_count, delta_files, delta_bytes in bumps:
            bump_floor_total(cache, base_exponent, delta_count, delta_files, delta_bytes)
        save_totals_cache(portal_folder, cache)
        result["bumped_rows"] = len(bumps)
    if not new_rows and info.get("base_exponent") is not None:
        # The kill time is unknown: windows written within a minute of the newest one
        # get the full check (window_integrity.repair_recent's default reference).
        result["deleted_windows"] = window_integrity.repair_recent(
            _run_window_paths(portal_folder, info))
        rescan_floor(portal_folder, info["base_exponent"])
        result["rescanned"] = True

    for key in ("log_path", "exit_path"):
        path = info.get(key)
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
    clear_stop_request(portal_folder)
    clear_active_run(portal_folder)
    result["status"] = "recovered"
    return result


def wsl_process_alive(pattern, timeout=20):
    """True when a WSL process whose command line contains `pattern` runs. pgrep's own
    `bash -lc` would match itself, so pgrep runs directly through `wsl.exe -e`. An
    unreachable WSL counts as alive: the marker then waits for the next start instead of
    a recovery racing a run that may still be going."""
    try:
        proc = subprocess.run(["wsl.exe", "-e", "pgrep", "-f", pattern],
                              timeout=timeout, **_popen_kwargs_no_window())
    except (OSError, subprocess.SubprocessError):
        return True
    return proc.returncode != 1  # pgrep: 0 = found, 1 = none, other = error


def kill_wsl_processes(pattern):
    """Fire-and-forget `pkill -f pattern` inside WSL; False when wsl.exe cannot start."""
    try:
        subprocess.Popen(["wsl.exe", "-e", "pkill", "-f", pattern], **_popen_kwargs_no_window())
        return True
    except OSError:
        return False


def rescan_floor_totals(portal_folder, base_exponent):
    """Recounts one floor's D and P totals (storage.update_floor_totals_cache, which reads
    only headers it has not cached) and saves the cache."""
    cache = load_totals_cache(portal_folder)
    for kind in storage_kinds.KINDS:
        update_floor_totals_cache(portal_folder, base_exponent, cache, kind=kind)
    save_totals_cache(portal_folder, cache)
