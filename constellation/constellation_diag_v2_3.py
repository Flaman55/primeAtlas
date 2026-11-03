"""
constellation_diag_v2_3.py -- crash-diagnosis helpers of the constellation search: process
resource numbers (peak RSS, open file descriptors) and a print that is fsynced to the log,
so the log of a WSL process that dies without a traceback shows where it was.
"""
import os
import sys

try:
    import resource  # POSIX-only -- this script always runs for real inside WSL, but
                      # is also imported directly on Windows by
                      # unitTests/test_constellation_finder_engine.py, so the import
                      # itself must not blow up there.
except ImportError:
    resource = None


def _proc_diag():
    """Cheap process-level diagnostics -- peak RSS memory and open file-descriptor
    count -- printed at key points in process_floor(). A WSL process dying from resource
    exhaustion (memory, file descriptors, the 9P filesystem driver) exits with no Python
    traceback; these numbers show which resource was growing.

    RSS via `resource.getrusage` (POSIX-only; `resource` is None on Windows, which only
    matters for unit tests importing this module) and open-FD count via `/proc/self/fd`
    (Linux-only, present inside WSL). Both are cheap enough to read once per window."""
    if resource is None:
        return "rss=n/a open_fds=n/a (non-POSIX)"
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    try:
        open_fds = len(os.listdir("/proc/self/fd"))
    except OSError:
        open_fds = -1
    return f"rss={rss_mb:.1f}MB open_fds={open_fds}"


def _diag_fsync_print(msg):
    """print() + explicit flush/fsync. Inside WSL a returned write() can still sit in a
    dirty page not yet synced across the 9P mount to the Windows-side log file when the
    VM dies. Used for diagnostics printed right before or during an expensive operation
    (e.g. a full hit-file decode in _resolve_last_value()), so the log shows where a run
    died."""
    print(msg)
    try:
        sys.stdout.flush()
        os.fsync(sys.stdout.fileno())
    except OSError:
        pass  # best-effort -- must never crash the run over a diagnostic nicety
