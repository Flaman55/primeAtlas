"""
wsl_resources.py -- best-effort RAM and CPU probes INSIDE WSL (where the sieve runs, with
its own .wslconfig limits), the window-count/worker-count recommendations the Quick-gen
panel's Auto buttons derive from them, and the pipeline form's workers field (a number or
WORKERS_MAX) as a worker count.
"""
import os
import subprocess

from . import run_budget
from .window_planning import QUICK_GEN_MAX_WINDOW_WIDTH


def estimate_wsl_available_ram_bytes(timeout=10):
    """Best-effort read of MemAvailable from /proc/meminfo INSIDE WSL -- deliberately not
    the native Windows process's own memory, since the actual sieve run happens as a WSL
    subprocess (see wsl_command.build_wsl_logged_command()) and WSL2's memory cap is configured
    independently of the host (.wslconfig, defaults to roughly half the host's RAM) --
    querying Windows-side RAM would silently overstate what the run this estimate is FOR
    can actually use. Returns None on any failure (WSL not installed/reachable, parse
    failure, timeout) -- callers must treat that as "couldn't determine, don't guess",
    never fall back to a made-up number."""
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            ["wsl.exe", "-e", "bash", "-c", "cat /proc/meminfo"],
            capture_output=True, text=True, timeout=timeout, **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if line.startswith("MemAvailable:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1]) * 1024  # /proc/meminfo reports kB
    return None


def recommended_max_windows(available_ram_bytes, window_m=QUICK_GEN_MAX_WINDOW_WIDTH,
                             safety_fraction=run_budget.DEFAULT_SAFETY_FRACTION):
    """Conservative "how many windows should fit in one v4.1 run" recommendation: half the
    free RAM over the shared bit buffer's window_m // 8 bytes per window, clamped to the
    same [1, 1000] range every width spinbox in the Quick-gen panel enforces. run_budget.py holds the
    model (and v5's floor-scaled target and footprint); treat the result as a starting point
    to try on a small run first, not a guarantee -- the benchmark log's peak-RAM column is
    the feedback loop. Returns None if available_ram_bytes is None/non-positive."""
    budget = run_budget.recommend_run(available_ram_bytes, run_budget.ENGINE_V41, 0, window_m,
                                      safety_fraction=safety_fraction)
    return budget.windows if budget else None


def estimate_wsl_available_cpu_count(timeout=10):
    """Best-effort read of the CPU count INSIDE WSL (via `nproc`) -- same reasoning as
    estimate_wsl_available_ram_bytes() above: the sieve itself runs as a WSL subprocess
    (see wsl_command.build_wsl_logged_command()), and WSL2 can be configured (`.wslconfig`'s own
    `processors` setting) with fewer virtual CPUs than the host actually has, so reading
    Windows-side CPU count (e.g. `os.cpu_count()` in this native process) would silently
    overstate what a run launched INTO WSL can actually use in parallel. Returns None on
    any failure (WSL not installed/reachable, parse failure, timeout) -- callers must
    treat that as "couldn't determine, don't guess", never fall back to a made-up
    number, same as the RAM probe."""
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            ["wsl.exe", "-e", "bash", "-c", "nproc"],
            capture_output=True, text=True, timeout=timeout, **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    if not output.isdigit():
        return None
    count = int(output)
    return count if count > 0 else None


def recommended_worker_count(available_cpu_count):
    """The "workers" CLI parameter (orchestrator_loop_v2.py/orchestrator_v3.py) spawns
    that many OS-level parallel processes, each pinned to sieving its own batch of the
    combined range -- unlike window count (which trades RAM for throughput with no
    natural ceiling other than memory), there is no benefit to requesting more workers
    than there are CPUs to actually run them concurrently; anything beyond that just
    adds process-scheduling overhead without adding real parallelism. The
    recommendation is therefore simply the detected CPU count itself, clamped to a
    sane [1, 256] display range (defensive only -- guards against a corrupt/absurd
    `nproc` read, not a real architectural limit). Returns None if
    available_cpu_count is None/non-positive, same "couldn't determine" contract as
    recommended_max_windows()."""
    if not available_cpu_count or available_cpu_count <= 0:
        return None
    return max(1, min(256, int(available_cpu_count)))


WORKERS_MAX = "Max"
"""The workers field's value meaning every CPU WSL sees, read at each launch."""


def wants_cpu_count(text):
    """Whether the workers field `text` is WORKERS_MAX, so a launch must probe the CPUs."""
    return str(text or "").strip().lower() == WORKERS_MAX.lower()


def resolve_workers(text, available_cpu_count):
    """The worker count of the workers field `text`: WORKERS_MAX -> the recommended count
    for `available_cpu_count` (None when it is unknown), a positive whole number as typed,
    anything else None."""
    if wants_cpu_count(text):
        return recommended_worker_count(available_cpu_count)
    raw = str(text or "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else None
