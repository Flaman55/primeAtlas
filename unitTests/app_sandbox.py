"""
app_sandbox.py -- runs the full PrimeAtlas GUI (prime_atlas_v2._build_gui()) in a test
without touching the user's real data.

isolate_app() must run before the app is constructed: PortalBrowserApp.__init__ scans
the storage folder for both trees (the notebook is packed only once both scans finish,
see test_loading_screen.py), reads benchmark_log.csv, and settles the previous session's
unfinished Generation run (run_guard.recover_unfinished_run(), which can delete windows
and rewrite floor totals). Pointed at a fresh empty folder, all of that is fast and
harmless, and the test's timing no longer depends on the size of the real storage.

The free-RAM probe of the Generation tab (time_simulation_controls) returns None and the CPU
probe (wsl_resources.estimate_wsl_available_cpu_count, read at startup and at a launch with
workers Max) FAKE_WSL_CPUS, so no test starts wsl.exe; the CPU/RAM details read
(core.hardware_details.read_hardware_details) knows nothing, so no test starts PowerShell; a
test that needs another reading replaces them after this. AppSettings.save() is
replaced by a no-op, so the redirected storage_path and any setting
a test changes never reach primeatlas/locales/app_settings.json. A test that counts
saves replaces save() again after this. The remembered-fields store
(primeatlas/core/ui_state_dynamic.STORE) is replaced by an in-memory one, so the user's
ui_state.json is neither read nor written; a test of persistence installs its own. It holds
a normal window state, so the window opens normal (not maximized) and takes the size a test
gives it. Message boxes stay the caller's business: tests patch them their own way (some record what was shown).

isolate_app() also arms a watchdog: a test process still running timeout_s seconds later
(default APP_TEST_TIMEOUT_S) prints a FAIL line and exits with code 1, so a hung layout or a
dialog nobody closes shows as a failure instead of silence. A later call re-arms it.

fresh_ui_store() gives a tab built without the app (straight from its class) an empty
in-memory remembered-fields store, so what one test's tab remembered (the Benchmark view)
does not reach the next test in the same process.
"""
import atexit
import os
import shutil
import sys
import tempfile
import threading

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# More CPUs than any test's thread count, so no field is capped under a test.
FAKE_WSL_CPUS = 64
# Longest run of one app test before the watchdog stops it. Arbitrary: several times the
# slowest app test file.
APP_TEST_TIMEOUT_S = 900

_watchdog = None


def _timed_out(timeout_s):
    print(f"FAIL: test timed out after {timeout_s} s (app_sandbox watchdog)", flush=True)
    os._exit(1)


def arm_watchdog(timeout_s=APP_TEST_TIMEOUT_S):
    global _watchdog
    if _watchdog is not None:
        _watchdog.cancel()
    _watchdog = threading.Timer(timeout_s, _timed_out, args=(timeout_s,))
    _watchdog.daemon = True
    _watchdog.start()


def fresh_ui_store():
    from primeatlas.core import ui_state_dynamic
    from primeatlas.core.ui_state_store import UiStateStore
    ui_state_dynamic.STORE = UiStateStore(None)


def isolate_app(portal=None, prefix="primeatlas_test_portal_", timeout_s=APP_TEST_TIMEOUT_S):
    """Imports prime_atlas_v2 with its storage folder redirected to `portal` -- a folder
    the test has seeded and removes itself -- or, when None, to a new empty temp folder
    removed when the test process exits, and arms the watchdog for `timeout_s`. Returns
    (prime_atlas_v2 module, portal folder)."""
    arm_watchdog(timeout_s)
    for path in (_REPO_ROOT, os.path.join(_REPO_ROOT, "prime_sieve")):
        if path not in sys.path:
            sys.path.insert(0, path)
    sys.argv = ["prime_atlas_v2.py"]
    import prime_atlas_v2
    from primeatlas.app import app_dynamic
    if portal is None:
        portal = tempfile.mkdtemp(prefix=prefix)
        atexit.register(shutil.rmtree, portal, True)
    from primeatlas.core import ui_state_dynamic
    from primeatlas.core.ui_state import UiStateStore
    ui_state_dynamic.STORE = UiStateStore(None)
    # A normal window, not the maximized default: tests size the window with geometry().
    ui_state_dynamic.STORE.set("layout.window.state", "normal")
    from primeatlas.generation import time_simulation_controls
    time_simulation_controls.estimate_free_ram_bytes = lambda **_k: None
    from primeatlas.generation import wsl_resources
    wsl_resources.estimate_wsl_available_cpu_count = lambda *_a, **_k: FAKE_WSL_CPUS
    from primeatlas.core import hardware_details
    hardware_details.read_hardware_details = lambda *_a, **_k: hardware_details.HardwareDetails()
    from primeatlas.core import number_format, number_format_dynamic
    number_format_dynamic.STYLE = number_format.DEFAULT_STYLE
    app_dynamic.APP_SETTINGS.save = lambda: None
    app_dynamic.APP_SETTINGS.set_storage_path(portal)
    app_dynamic.PORTAL_FOLDER = portal
    return prime_atlas_v2, portal
