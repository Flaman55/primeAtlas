"""
app_sandbox.py -- runs the full PrimeAtlas GUI (prime_atlas_v2._build_gui()) in a test
without touching the user's real data.

isolate_app() must run before the app is constructed: PortalBrowserApp.__init__ scans
the storage folder for both trees (the notebook is packed only once both scans finish,
see test_loading_screen.py), reads benchmark_log.csv, and settles the previous session's
unfinished Generation run (run_guard.recover_unfinished_run(), which can delete windows
and rewrite floor totals). Pointed at a fresh empty folder, all of that is fast and
harmless, and the test's timing no longer depends on the size of the real storage.

AppSettings.save() is replaced by a no-op, so the redirected storage_path and any setting
a test changes never reach primeatlas/locales/app_settings.json. A test that counts
saves replaces save() again after this. The remembered-fields store
(primeatlas/core/ui_state_dynamic.STORE) is replaced by an in-memory one, so the user's
ui_state.json is neither read nor written; a test of persistence installs its own. Message
boxes stay the caller's business: tests patch them their own way (some record what was shown).

fresh_ui_store() gives a tab built without the app (straight from its class) an empty
in-memory remembered-fields store, so what one test's tab remembered (the Benchmark view)
does not reach the next test in the same process.
"""
import atexit
import os
import shutil
import sys
import tempfile

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fresh_ui_store():
    from primeatlas.core import ui_state_dynamic
    from primeatlas.core.ui_state_store import UiStateStore
    ui_state_dynamic.STORE = UiStateStore(None)


def isolate_app(portal=None, prefix="primeatlas_test_portal_"):
    """Imports prime_atlas_v2 with its storage folder redirected to `portal` -- a folder
    the test has seeded and removes itself -- or, when None, to a new empty temp folder
    removed when the test process exits. Returns (prime_atlas_v2 module, portal folder)."""
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
    app_dynamic.APP_SETTINGS.save = lambda: None
    app_dynamic.APP_SETTINGS.set_storage_path(portal)
    app_dynamic.PORTAL_FOLDER = portal
    return prime_atlas_v2, portal
