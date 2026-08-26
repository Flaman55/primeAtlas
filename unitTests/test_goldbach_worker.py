"""
test_goldbach_worker.py -- functional regression test for the Goldbach
structural-window worker (Badania -> Goldbach sub-tab), migrated onto
primeatlas/background.py's PersistentWorker during the refactor branch's Faza 1
(background-job consolidation, 2026-08-23), then extracted wholesale into
primeatlas/research_goldbach_tab.py's ResearchGoldbachTab during Faza 3 (tab-by-tab
backend/UI split, 2026-08-23) -- all app.goldbach_*/app._goldbach_* references below
now go through app.research_goldbach_tab_widget instead (see that module's own
docstring for why the tab is fully self-contained, own worker included).

Drives the REAL UI entrypoints (_on_goldbach_run, _on_goldbach_visualize,
_on_goldbach_viz_decompose) -- exactly what clicking the tab's buttons does --
rather than hand-building job dicts, so this also exercises _goldbach_parse_n(),
the Wizualizacja Toplevel lazy-creation path, and the decompose Toplevel's own
dependency on a prior successful "viz" result, not just the worker plumbing in
isolation.

All three ops are kept inside floor 0's natural range ([1, 10)) so a single tiny
seeded PGS1 window (primes 2,3,5,7 at offset 0 under 10p0/source_primes/) covers
every storage read this test needs -- "window" doesn't touch storage at all
(fresh in-process sieve), "viz" needs up to n+GOLDBACH_BOTH_BASE_PMIN (2), and
"decompose" needs up to n itself.

See test_search_worker.py's own module docstring for why AppSettings.save() must
be neutered before touching storage_path in a test like this.

Usage (Windows, real display):
    python unitTests\\test_goldbach_worker.py

Usage (this sandbox, headless):
    PYTHONPATH="/tmp/tkextract/usr/lib/python3.10:/tmp/tkextract/usr/lib/python3.10/lib-dynload:$PYTHONPATH" \\
    LD_LIBRARY_PATH="/tmp/tkextract/usr/lib:$LD_LIBRARY_PATH" \\
    xvfb-run -a python3 unitTests/test_goldbach_worker.py
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
    tkinter.messagebox.showwarning = lambda *a, **k: shown.append(("warning", a, k))
    tkinter.messagebox.askyesno = lambda *a, **k: False
    return shown


def _pump(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def _set_entry(entry, value):
    entry.delete(0, "end")
    entry.insert(0, value)


def main():
    import prime_sieve_v1

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_goldbach_worker_test_")
    try:
        # Filename must match "..._off_{offset}[M|k].bin" -- read_is_prime_from_storage's
        # own file lookup (_offset_from_filename) parses the offset straight from the
        # name (see prime_sieve_v1.main_batch_scanner's own PRIME_WINDOW_10p{N}_off_{...}
        # naming), unlike the simple "PRIME_WINDOW_{start}.bin" name the search-worker
        # test uses (that feature reads window headers directly instead).
        # source_primes/ is sharded into shard_NNNNN subfolders (see window_sharding.py,
        # task #405) -- offset 0 always lands in shard_00000.
        import window_sharding
        source_dir = os.path.join(tmp_portal, "10p0", "source_primes")
        shard_dir = window_sharding.shard_dir(source_dir, 0)
        os.makedirs(shard_dir, exist_ok=True)
        prime_sieve_v1.write_prime_window(
            os.path.join(shard_dir, "PRIME_WINDOW_10p0_off_0.bin"), [2, 3, 5, 7])

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

        goldbach = app.research_goldbach_tab_widget

        # --- "window" op: fresh in-process sieve, no storage read at all ------------
        _set_entry(goldbach.goldbach_n_entry, "10")
        goldbach._on_goldbach_run()
        check(goldbach._goldbach_busy, "'window' job marked busy immediately after dispatch")
        _pump(app, 3.0)
        check(not goldbach._goldbach_busy, "'window' job settles after a PersistentWorker result")
        check(goldbach._goldbach_last_result is not None,
              "'window' job populated _goldbach_last_result")
        check(goldbach._goldbach_last_result["n"] == 10,
              f"'window' result carries the requested n (got {goldbach._goldbach_last_result!r})")

        # --- "viz" op: reads storage (floor 0), exercises report_progress ----------
        _set_entry(goldbach.goldbach_n_entry, "6")
        goldbach._on_goldbach_visualize()
        check(goldbach._goldbach_busy, "'viz' job marked busy immediately after dispatch")
        _pump(app, 3.0)
        check(not goldbach._goldbach_busy, "'viz' job settles without hanging or crashing")
        check(goldbach._goldbach_viz_last_result is not None,
              "'viz' job populated _goldbach_viz_last_result")
        check(goldbach._goldbach_viz_win is not None and goldbach._goldbach_viz_win.winfo_exists(),
              "Wizualizacja Toplevel was created and is still open")

        # --- "decompose" op: depends on the "viz" result just above for its pmax ---
        _set_entry(goldbach.goldbach_viz_decompose_entry, "6")
        goldbach._on_goldbach_viz_decompose()
        check(goldbach._goldbach_busy, "'decompose' job marked busy immediately after dispatch")
        _pump(app, 3.0)
        check(not goldbach._goldbach_busy, "'decompose' job settles without hanging or crashing")
        check(goldbach._goldbach_decompose_last_result is not None,
              "'decompose' job populated _goldbach_decompose_last_result")
        check(goldbach._goldbach_decompose_last_result["n"] == 6,
              f"'decompose' result carries the requested n "
              f"(got {goldbach._goldbach_decompose_last_result!r})")

        # --- error path: force _goldbach_job's own try/except to fire --------------
        # Mirrors test_primality_worker.py's forced-exception case: monkeypatching a
        # module-level function so it raises exercises the exact path _goldbach_job's
        # docstring documents (catches its own exception, returns (op, False, str(e))
        # instead of relying on PersistentWorker's last-resort net). Patched on
        # primeatlas.research_goldbach_tab (where _goldbach_job now lives and imports
        # goldbach_sieve_is_prime from), not prime_atlas_v1 -- see this file's own
        # module docstring for the Faza 3 extraction that moved it there.
        import primeatlas.research_goldbach_tab as research_goldbach_tab_module
        original_sieve_is_prime = research_goldbach_tab_module.goldbach_sieve_is_prime

        def fake_raise(n):
            raise RuntimeError("fake failure for this test")

        research_goldbach_tab_module.goldbach_sieve_is_prime = fake_raise
        shown.clear()
        _set_entry(goldbach.goldbach_n_entry, "10")
        goldbach._on_goldbach_run()
        _pump(app, 3.0)
        research_goldbach_tab_module.goldbach_sieve_is_prime = original_sieve_is_prime
        check(not goldbach._goldbach_busy, "'window' job settles even after an internal exception")
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
