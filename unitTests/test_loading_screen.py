"""
test_loading_screen.py -- functional regression test for the Faza 2 startup loading
screen + async tree-scan split in prime_atlas_v1.py (refactor branch, 2026-08-23).

Faza 2 changed __init__ to: (1) show a loading_frame (title + caption + indeterminate
progress bar) BEFORE building any of the six tabs, updating its caption as each tab is
built; (2) leave status_frame/main_notebook unpacked until BOTH startup tree scans
(reload_primes_tree() and reload_constellations_tree()) have completed; (3) split those
two reload functions so the actual disk scan runs on background.run_in_background()
instead of the GUI thread, with a busy/pending flag pair coalescing re-entrant calls.

This test exercises the real PortalBrowserApp() constructor end to end (not a mock),
against a real on-disk portal folder with one seeded floor, and checks:
  1. The loading screen is gone and the real UI (status_frame + notebook) is revealed
     once construction settles.
  2. The seeded floor actually shows up in both trees (i.e. the async scans really did
     run and their on_done callbacks really did populate the widgets, not just leave
     the loading screen up forever or silently do nothing).
  3. reload_primes_tree() called again while a scan is still in flight sets the
     "pending" flag instead of spawning a second overlapping scan, and settles cleanly
     once the in-flight one finishes (the busy/pending re-entrancy guard actually
     works, not just compiles).

See test_goldbach_worker.py's own module docstring for the PGS1 filename convention
this test's seeded window file must follow, and test_search_worker.py's for why
AppSettings.save() must be neutered before touching storage_path in a test like this.

Usage (Windows, real display):
    python unitTests\\test_loading_screen.py

Usage (this sandbox, headless):
    PYTHONPATH="/tmp/tkextract/usr/lib/python3.10:/tmp/tkextract/usr/lib/python3.10/lib-dynload:$PYTHONPATH" \\
    LD_LIBRARY_PATH="/tmp/tkextract/usr/lib:$LD_LIBRARY_PATH" \\
    xvfb-run -a python3 unitTests/test_loading_screen.py
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
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

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
    import prime_sieve_v1

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_loading_screen_test_")
    try:
        source_dir = os.path.join(tmp_portal, "10p0", "source_primes")
        os.makedirs(source_dir, exist_ok=True)
        prime_sieve_v1.write_prime_window(
            os.path.join(source_dir, "PRIME_WINDOW_10p0_off_0.bin"), [2, 3, 5, 7])

        _patch_messageboxes()

        # sys.argv/import must happen fresh so PORTAL_FOLDER (a module-level global
        # loaded from AppSettings before PortalBrowserApp exists -- see the file's own
        # header comment) starts out pointing wherever the real AppSettings.json last
        # left it, THEN gets redirected to tmp_portal below via set_portal_path/
        # set_portal_folder before any tree-affecting assertion is made -- exactly the
        # same pattern every other test in this folder uses.
        sys.argv = ["prime_atlas_v1.py"]
        import prime_atlas_v1

        # Point PORTAL_FOLDER (and the underlying APP_SETTINGS it was seeded from --
        # same object SettingsTab receives, see _build_settings_tab's own wiring) at
        # tmp_portal BEFORE constructing the app -- the constructor's own startup
        # reload_primes_tree()/reload_constellations_tree() calls read the module
        # global directly (see reload_primes_tree()'s own docstring: PORTAL_FOLDER is
        # captured at dispatch time), so redirecting it only AFTER construction would be
        # too late for this test's very first scan. save() is neutered FIRST so
        # set_storage_path() below never touches the real on-disk app_settings.json.
        _patch_app_settings(prime_atlas_v1.APP_SETTINGS)
        prime_atlas_v1.APP_SETTINGS.set_storage_path(tmp_portal)
        prime_atlas_v1.PORTAL_FOLDER = tmp_portal

        app_cls = prime_atlas_v1._build_gui()
        app = app_cls()
        # Constructor returns immediately after DISPATCHING the two startup scans (see
        # __init__'s own comment on _loading_startup_pending) -- they haven't
        # necessarily finished yet, so the loading screen may still legitimately be up
        # right here.

        _pump(app, 5.0)

        # --- loading screen actually finishes and reveals the real UI --------------
        check(not app._loading_frame.winfo_exists(),
              "loading_frame was destroyed once both startup scans settled")
        check(app._status_frame.winfo_ismapped(),
              "status_frame is packed/visible after the loading screen finished")
        check(app.main_notebook.winfo_ismapped(),
              "main_notebook is packed/visible after the loading screen finished")
        check(not app._loading_startup_pending,
              f"_loading_startup_pending emptied out (got {app._loading_startup_pending!r})")

        # --- the seeded floor actually made it into BOTH trees ----------------------
        check(0 in app.primes_tab_widget._pietro_node_by_exp,
              f"seeded floor 10p0 shows up in the Prime numbers tree "
              f"(got exponents: {list(app.primes_tab_widget._pietro_node_by_exp.keys())})")
        # Not asserting on app.status.get()'s CONTENT here -- by the time the 5s pump
        # above finishes, the totals worker kicked off at the end of
        # _on_primes_tree_scan_done has typically already overwritten the "N floors
        # found" message with its own "GRAND TOTAL" summary (both are legitimate,
        # sequential status states, not a bug). The grand total itself is a better,
        # non-timing-dependent proxy that the seeded floor was genuinely read: 4
        # primes (2,3,5,7) were written into it above.
        check(app._grand_total_sum == 4,
              f"totals worker actually summed the seeded floor's real prime count "
              f"(got _grand_total_sum={app._grand_total_sum!r})")

        # --- re-entrancy: a reload triggered while one is still in flight coalesces -
        # into a single pending rerun, not a second overlapping scan thread.
        original_scan = app._primes_tree_scan

        def slow_scan(portal_folder, report_progress):
            time.sleep(0.4)
            return original_scan(portal_folder, report_progress)

        app._primes_tree_scan = slow_scan
        app.reload_primes_tree()
        check(app._primes_tree_reload_busy, "first reload_primes_tree() call marks busy")
        app.reload_primes_tree()  # fired WHILE the slow scan above is still running
        check(app._primes_tree_reload_pending,
              "second reload_primes_tree() call while busy sets 'pending' instead of "
              "starting a second scan")
        _pump(app, 3.0)
        app._primes_tree_scan = original_scan
        check(not app._primes_tree_reload_busy,
              "re-entrant reload sequence settles (busy cleared) without hanging")
        check(not app._primes_tree_reload_pending,
              "re-entrant reload sequence clears 'pending' once the coalesced rerun finishes")
        check(0 in app.primes_tab_widget._pietro_node_by_exp,
              "tree is still correctly populated after the re-entrant reload sequence")

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
