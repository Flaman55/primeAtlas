"""
test_search_worker.py -- functional regression test for the "prime"/"const" search
worker, migrated onto primeatlas/background.py's PersistentWorker during the refactor
branch's Faza 1 (background-job consolidation, 2026-08-23), then moved off
PortalBrowserApp entirely into primeatlas/totals_search_coordinator.py's
TotalsSearchCoordinator during the refactor-phase2 branch's "God object" reduction
(2026-08-26) -- app._start_search_job/_search_busy are now
app._totals_search.start_search_job/.search_busy.

Builds the REAL PortalBrowserApp (same as tests/smoke_test.py) against a throwaway
portal folder seeded with a real PGS1 prime window, then drives
app._totals_search.start_search_job() directly -- exactly what clicking the "Szukaj"
button in the Liczby pierwsze / Konstelacje tabs does -- and asserts the result lands
back on the UI (search buttons re-enabled, status text set, preview populated) via the
PersistentWorker-based path.

Also includes a DETERMINISTIC regression test for the status-bar race (task #404,
fixed 2026-08-26 in TotalsSearchCoordinator): a floor-totals batch scan and a search
share one status bar, and a stale/slow totals completion used to be able to overwrite
a just-shown search result. That race's real-world timing is unreliable to exercise
directly (it depends on how fast a real background disk scan happens to settle
relative to a search -- see that test block's own comment), so it monkeypatches
update_pietro_totals_cache to force one totals job to take ~1.5 real seconds,
guaranteeing the exact interleaving the fix targets on every run.

IMPORTANT -- do not call app_settings.set_storage_path() directly on a live app's
AppSettings instance: AppSettings.save() persists unconditionally to the REAL
primeatlas/locales/app_settings.json shipped in this repo, which would silently
overwrite Artur's actual configured storage path with this test's throwaway temp
folder. This test monkeypatches .save() to a no-op first -- see _patch_app_settings()
below -- so only the in-memory storage_path changes, never the file on disk.

Usage (Windows, real display, real tkinter -- no Xvfb/PYTHONPATH tricks needed there):
    python unitTests\\test_search_worker.py

Usage (this sandbox, headless, using the extracted tkinter under /tmp/tkextract):
    PYTHONPATH="/tmp/tkextract/usr/lib/python3.10:/tmp/tkextract/usr/lib/python3.10/lib-dynload:$PYTHONPATH" \\
    LD_LIBRARY_PATH="/tmp/tkextract/usr/lib:$LD_LIBRARY_PATH" \\
    xvfb-run -a python3 unitTests/test_search_worker.py
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
    """Neuters persistence so this test can point the app at a temp folder without
    ever touching the real primeatlas/locales/app_settings.json -- see module
    docstring."""
    app_settings.save = lambda: None


def _patch_messageboxes():
    """A real messagebox.showinfo/showerror under Xvfb uses its own nested
    wait_window() event loop that never returns control to the caller until a human
    dismisses it -- there is no human here, so it would hang this test forever the
    moment a search result triggers one (e.g. a confirmed-composite popup). Recorded
    calls are returned so assertions can check what WOULD have been shown."""
    shown = []
    tkinter.messagebox.showinfo = lambda *a, **k: shown.append(("info", a, k))
    tkinter.messagebox.showerror = lambda *a, **k: shown.append(("error", a, k))
    tkinter.messagebox.showwarning = lambda *a, **k: shown.append(("warning", a, k))
    tkinter.messagebox.askyesno = lambda *a, **k: False  # never auto-confirm a generation offer
    return shown


def _pump(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def main():
    import prime_sieve_v1

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_search_worker_test_")
    try:
        source_dir = os.path.join(tmp_portal, "10p3", "source_primes")
        os.makedirs(source_dir, exist_ok=True)
        primes = [p for p in range(100, 200)
                  if p > 1 and all(p % d for d in range(2, int(p ** 0.5) + 1))]
        prime_sieve_v1.write_prime_window(
            os.path.join(source_dir, "PRIME_WINDOW_0000000100.bin"), primes)

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
        app.reload_primes_tree()
        _pump(app, 3.0)

        # --- "prime" search: found -------------------------------------------------
        app._totals_search.start_search_job("prime", 3, 101)
        check(app._totals_search.search_busy, "search job marked busy immediately after dispatch")
        check(str(app.primes_tab_widget.search_button["state"]) == "disabled",
              f"search button disabled while a 'prime' search is in flight "
              f"(got state={app.primes_tab_widget.search_button['state']!r})")
        _pump(app, 3.0)
        check(not app._totals_search.search_busy, "search job no longer busy after PersistentWorker result")
        check(str(app.primes_tab_widget.search_button["state"]) == "normal",
              f"search button re-enabled after 'prime' search completes "
              f"(got state={app.primes_tab_widget.search_button['state']!r})")
        check("101" in app.status.get(), f"status mentions the found prime (got: {app.status.get()!r})")

        # --- "prime" search: not found but window covers it (confirmed composite) --
        # 150 is even/composite, and the seeded window covers [100,200), so this must
        # resolve to "confirmed composite" -- a showinfo popup (recorded, not shown --
        # see _patch_messageboxes) -- WITHOUT ever hanging waiting for a dialog.
        shown.clear()
        app._totals_search.start_search_job("prime", 3, 150)
        _pump(app, 3.0)
        check(not app._totals_search.search_busy, "search job settles after a 'not found' prime result too")
        check(any("150" in str(call) for call in shown),
              f"a composite/not-found popup mentioning 150 was recorded (got: {shown})")

        # --- "const" search: exercises the mid-job report_progress() path too ------
        # (find_constellation_participation reports progress via the SAME
        # report_progress mechanism _totals_job uses -- see _search_job's docstring).
        # No real hit files were seeded, so an empty participation list is the
        # correct, non-crashing outcome -- this is checking the PLUMBING survives a
        # "const" job end to end, not asserting any specific constellation content.
        app._totals_search.start_search_job("const", 3, 101)
        check(app._totals_search.search_busy, "const search job marked busy immediately after dispatch")
        _pump(app, 3.0)
        check(not app._totals_search.search_busy, "const search job settles without hanging or crashing")

        # --- Deterministic regression test for the status-bar race (task #404) -----
        # The scenarios above pass reliably once the coordinator's fix is in place,
        # but their actual timing depends on how fast the real background totals
        # scan happens to settle relative to the search -- on a fast/lightly-loaded
        # machine the totals job can finish BEFORE the search even starts, and on a
        # slow one (real disk I/O + antivirus scanning of a fresh temp folder) it can
        # finish well AFTER, neither of which reliably exercises the actual race
        # window every run (confirmed in practice, 2026-08-26: this exact scenario
        # intermittently failed/passed across otherwise-identical runs). This block
        # forces the totals scan to take ~1.5 REAL seconds (monkeypatching
        # update_pietro_totals_cache, the slow part of TotalsSearchCoordinator.
        # _totals_job) so it is GUARANTEED to still be in flight when the search
        # below starts and finishes -- deterministically reproducing the exact
        # interleaving the fix targets, independent of real disk/OS timing.
        import primeatlas.totals_search_coordinator as tsc_module
        _real_update_totals = tsc_module.update_pietro_totals_cache

        def _slow_update_totals(*a, **k):
            time.sleep(1.5)
            return _real_update_totals(*a, **k)

        tsc_module.update_pietro_totals_cache = _slow_update_totals
        try:
            app.reload_primes_tree()  # triggers compute_all_pietro_totals() -> a
                                       # (now artificially slow) totals job
            _pump(app, 0.6)  # let the (fast) scan itself settle and the slow totals
                              # job actually get submitted/picked up -- NOT a bare
                              # time.sleep(): the scan's own completion callback is
                              # delivered via app.after(), which only runs while the
                              # Tk event loop is being pumped
            app._totals_search.start_search_job("prime", 3, 103)
            _pump(app, 1.5)  # the search itself is fast (tiny fixture); this is
                              # ample, and the slow totals job is still running
            check(not app._totals_search.search_busy,
                  "race-test: search settles quickly despite a slow totals batch "
                  "still in flight")
            check("103" in app.status.get(),
                  f"race-test: search result is shown while the slow totals batch "
                  f"is still running (got: {app.status.get()!r})")
            _pump(app, 2.0)  # let the slow totals job (and its own "grand total"
                              # status message) finally land
            check("103" in app.status.get(),
                  f"race-test: status STAYS on the search result even after the "
                  f"slow totals batch finally completes afterward "
                  f"(got: {app.status.get()!r})")
        finally:
            tsc_module.update_pietro_totals_cache = _real_update_totals

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
