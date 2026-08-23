"""
test_const_records_worker.py -- functional regression test for the constellation-
records-table worker (Constellations -> Tabela rekordow sub-tab, Faza 4) in
prime_atlas_v1.py, migrated onto primeatlas/background.py's PersistentWorker during
the refactor branch's Faza 1 (background-job consolidation, 2026-08-23). This is the
SIXTH and LAST of the six originally hand-rolled worker-thread patterns to be
migrated -- see primeatlas_refactor_branch memory / commit history for the other
five (totals, search, primesieve_calc, primality, goldbach).

Uses a throwaway EMPTY portal folder for the "scan" case -- build_constellation_
records_table()'s own docstring says it returns an empty rows list (not an error)
when a floor has no hit files for the requested k, so this exercises the worker
plumbing end to end without needing to fabricate real HITS_*.bin constellation
files. The export cases are driven by calling _const_records_start_job(...) directly
with a fixed path instead of clicking the real "Eksportuj" buttons -- those buttons
open a native filedialog.asksaveasfilename() dialog, which (like tkinter.messagebox)
enters its own nested event loop under Xvfb with no human to dismiss it.

See test_search_worker.py's own module docstring for why AppSettings.save() must be
neutered before touching storage_path in a test like this.

Usage (Windows, real display):
    python unitTests\\test_const_records_worker.py

Usage (this sandbox, headless):
    PYTHONPATH="/tmp/tkextract/usr/lib/python3.10:/tmp/tkextract/usr/lib/python3.10/lib-dynload:$PYTHONPATH" \\
    LD_LIBRARY_PATH="/tmp/tkextract/usr/lib:$LD_LIBRARY_PATH" \\
    xvfb-run -a python3 unitTests/test_const_records_worker.py
"""
import os
import shutil
import sys
import tempfile
import time
import tkinter.messagebox

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "constellation"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _patch_app_settings(app_settings):
    app_settings.save = lambda: None


def _patch_messageboxes():
    shown = []
    tkinter.messagebox.showinfo = lambda *a, **k: shown.append(("info", a, k))
    tkinter.messagebox.showerror = lambda *a, **k: shown.append(("error", a, k))
    return shown


def _pump(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def main():
    import pattern_catalog_v1

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_const_records_worker_test_")
    try:
        shown = _patch_messageboxes()

        sys.argv = ["prime_atlas_v1.py"]
        import prime_atlas_v1
        app_cls = prime_atlas_v1._build_gui()
        app = app_cls()
        app.update()

        settings_tab = app.settings_tab
        _patch_app_settings(settings_tab.app_settings)
        settings_tab.app_settings.set_storage_path(tmp_portal)
        settings_tab.wsl["set_portal_folder"](tmp_portal)
        app.update()

        k = pattern_catalog_v1.all_k()[0]

        # --- "scan" op: empty portal folder -> empty rows, not an error --------------
        app.const_records_k_combo.set(str(k))
        app._on_const_records_scan_clicked()
        check(app._const_records_busy, "'scan' job marked busy immediately after dispatch")
        _pump(app, 3.0)
        check(not app._const_records_busy, "'scan' job settles after a PersistentWorker result")
        check(app._const_records_last is not None,
              "'scan' job populated _const_records_last (even with zero rows)")
        check(app._const_records_last[0] == k,
              f"'scan' result carries the requested k (got {app._const_records_last[0]!r})")

        # --- "export_csv" op: bypass the file-dialog button, call the dispatcher ----
        # directly with a fixed path (see module docstring for why).
        csv_path = os.path.join(tmp_portal, "export_test.csv")
        app._const_records_start_job(
            {"mode": "export_csv", "k": k, "floor_min": None, "floor_max": None,
             "path": csv_path},
            "exporting (test)")
        check(app._const_records_busy, "'export_csv' job marked busy immediately after dispatch")
        _pump(app, 3.0)
        check(not app._const_records_busy, "'export_csv' job settles without hanging or crashing")
        check(os.path.exists(csv_path), "'export_csv' job actually wrote the CSV file")
        check(any("info" == kind for kind, _a, _k in shown),
              f"a 'saved' confirmation was recorded via messagebox.showinfo (got: {shown})")

        # --- error path: force _const_records_job's own try/except to fire ---------
        # Mirrors test_primality_worker.py / test_goldbach_worker.py's forced-
        # exception case: monkeypatching a module-level function so it raises
        # exercises the exact path _const_records_job's docstring documents (catches
        # its own exception, returns (mode, k, False, str(e)) instead of relying on
        # PersistentWorker's last-resort net).
        original_build_table = prime_atlas_v1.build_constellation_records_table

        def fake_raise(portal_folder, k, floor_min=None, floor_max=None):
            raise RuntimeError("fake failure for this test")

        prime_atlas_v1.build_constellation_records_table = fake_raise
        shown.clear()
        app._const_records_worker.submit({"mode": "scan", "k": k})
        app._const_records_busy = True  # mirror what _const_records_start_job sets;
                                         # submit() alone (bypassing the dispatcher)
                                         # doesn't touch this flag
        _pump(app, 3.0)
        prime_atlas_v1.build_constellation_records_table = original_build_table
        check(not app._const_records_busy, "'scan' job settles even after an internal exception")
        check(any("fake failure for this test" in str(call) for call in shown),
              f"the fake exception was surfaced via messagebox.showerror (got: {shown})")

        app.destroy()
    finally:
        shutil.rmtree(tmp_portal, ignore_errors=True)

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
