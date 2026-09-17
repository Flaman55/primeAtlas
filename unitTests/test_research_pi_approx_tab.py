"""
test_research_pi_approx_tab.py -- tests for
primeatlas/research/research_pi_approx_tab.py's ResearchPiApproxTab (Badania ->
Przyblizenia pi(x)), the UI wired around primeatlas/research/pi_approx_window.py's
pure check_pi_approx_range()/check_pi_approx_range_from_source() (see that
module's own test file, test_pi_approx_window.py, for the pure-logic
checks -- this file only exercises the tkinter wiring: running a range,
pagination buttons, error dialogs, the storage data-source toggle, and CSV
export).

Same "build the REAL app" approach as test_research_squares_tab.py -- see
that file's own docstring for why. The storage-mode tests seed a real
floor-0 window file, same minimal-seed recipe.

Usage (Windows, real display):
    python unitTests\\test_research_pi_approx_tab.py
"""
import csv
import os
import shutil
import sys
import tempfile
import time
import tkinter as tk

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
    """Neuters persistence so this test never touches the real
    primeatlas/locales/app_settings.json -- same convention as every other
    tab test file's own _patch_app_settings (e.g. test_research_squares_tab.py)."""
    app_settings.save = lambda: None


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
    import window_sharding

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_pi_approx_tab_test_")
    try:
        _run(tmp_portal, prime_sieve_v1, window_sharding)
    finally:
        shutil.rmtree(tmp_portal, ignore_errors=True)


def _run(tmp_portal, prime_sieve_v1, window_sharding):
    # Floor 0 ([1,10)) seeded with its real primes -- covers checkpoints up
    # to x=9. x=10 itself needs floor 1 (NOT seeded), to exercise the
    # "missing floor" error path.
    source_dir = os.path.join(tmp_portal, "10p0", "source_primes")
    shard_dir = window_sharding.shard_dir(source_dir, 0)
    os.makedirs(shard_dir, exist_ok=True)
    prime_sieve_v1.write_prime_window(
        os.path.join(shard_dir, "PRIME_WINDOW_10p0_off_0.bin"), [2, 3, 5, 7])

    import tkinter.messagebox
    shown = []
    tkinter.messagebox.showerror = lambda *a, **k: shown.append(("error", a, k))

    sys.argv = ["prime_atlas_v1.py"]
    import prime_atlas_v1
    _patch_app_settings(prime_atlas_v1.APP_SETTINGS)
    app_cls = prime_atlas_v1._build_gui()
    app = app_cls()
    app.update()
    tab = app.research_pi_approx_tab_widget

    settings_tab = app.settings_tab
    _patch_app_settings(settings_tab.app_settings)
    settings_tab.app_settings.set_storage_path(tmp_portal)
    settings_tab.wsl["set_portal_folder"](tmp_portal)
    app.update()

    # --- defaults ------------------------------------------------------------------------
    check(tab.pi_x_from_entry.get() == "100",
          f"the default x_from field starts at 100 (got {tab.pi_x_from_entry.get()!r})")

    # --- run over a small range ------------------------------------------------------
    _set_entry(tab.pi_x_from_entry, "10")
    _set_entry(tab.pi_x_to_entry, "100")
    _set_entry(tab.pi_step_entry, "30")
    shown.clear()
    tab._on_pi_run()
    _pump(app, 2.0)
    check(shown == [], f"no error dialog for a valid run (got {shown!r})")
    rows = tab.pi_results_tree.get_children()
    check(len(rows) == 4, f"x=10,40,70,100 produces exactly 4 result rows (got {len(rows)})")
    values0 = tab.pi_results_tree.item(rows[0])["values"]
    check(str(values0[0]) == "10" and str(values0[1]) == "4",
          f"first row is x=10, pi(x)=4 (got {values0!r})")
    check(tab._pi_last_result["max_li_error"] is not None,
          "max_li_error is populated after a run")
    check(str(tab.pi_prev_button["state"]) == "disabled",
          "Prev is disabled on the very first page")
    check(str(tab.pi_next_button["state"]) == "disabled",
          "Next is disabled when the whole range fit on one page (4 < row cap)")

    # --- R(x) is a closer approximation than li(x), visible in the summary text ------
    summary_text = tab.pi_summary_var.get()
    check(bool(summary_text), "the summary line is populated after a run")

    # --- n_to < n_from is rejected before ever touching the worker --------------------
    _set_entry(tab.pi_x_from_entry, "100")
    _set_entry(tab.pi_x_to_entry, "10")
    shown.clear()
    tab._on_pi_run()
    _pump(app, 1.0)
    check(len(shown) == 1 and shown[0][0] == "error",
          f"x_to < x_from shows an error dialog (got {shown!r})")

    # --- x_from < 2 is rejected --------------------------------------------------------
    _set_entry(tab.pi_x_from_entry, "1")
    _set_entry(tab.pi_x_to_entry, "100")
    shown.clear()
    tab._on_pi_run()
    _pump(app, 1.0)
    check(len(shown) == 1 and shown[0][0] == "error",
          f"x_from < 2 shows an error dialog (got {shown!r})")

    # --- an oversized range is refused with a clear error, not a hang/crash -----------
    _set_entry(tab.pi_x_from_entry, "1000")
    _set_entry(tab.pi_x_to_entry, "1000000000")
    _set_entry(tab.pi_step_entry, "100000000")
    shown.clear()
    tab._on_pi_run()
    _pump(app, 3.0)
    check(len(shown) == 1 and shown[0][0] == "error",
          f"an oversized range (needs a huge sieve) shows an error dialog "
          f"(got {shown!r})")

    # --- pagination: Prev/Next actually move between pages ----------------------------
    _set_entry(tab.pi_x_from_entry, "10")
    _set_entry(tab.pi_x_to_entry, "10000")
    _set_entry(tab.pi_step_entry, "10")
    shown.clear()
    tab._on_pi_run()
    _pump(app, 3.0)
    check(shown == [], f"no error dialog for the pagination test's range (got {shown!r})")
    page0_first_x = tab.pi_results_tree.item(
        tab.pi_results_tree.get_children()[0])["values"][0]
    check(str(tab.pi_next_button["state"]) == "normal",
          "Next is enabled when more rows exist past the first page (1000 checkpoints > row cap)")
    tab._on_pi_next()
    _pump(app, 2.0)
    page1_first_x = tab.pi_results_tree.item(
        tab.pi_results_tree.get_children()[0])["values"][0]
    check(page1_first_x != page0_first_x,
          f"clicking Next actually advances to a page with different checkpoints "
          f"(page0 first x={page0_first_x!r}, page1 first x={page1_first_x!r})")
    check(str(tab.pi_prev_button["state"]) == "normal",
          "Prev is enabled once on a page past the first")
    tab._on_pi_prev()
    _pump(app, 2.0)
    back_first_x = tab.pi_results_tree.item(
        tab.pi_results_tree.get_children()[0])["values"][0]
    check(back_first_x == page0_first_x,
          f"clicking Prev returns to the original first page "
          f"(got {back_first_x!r}, expected {page0_first_x!r})")

    # --- storage mode: reads real data from the seeded floor 0 -----------------------
    tab.pi_source_var.set("storage")
    _set_entry(tab.pi_x_from_entry, "2")
    _set_entry(tab.pi_x_to_entry, "9")
    _set_entry(tab.pi_step_entry, "7")
    shown.clear()
    tab._on_pi_run()
    _pump(app, 2.0)
    check(shown == [], f"no error dialog for a storage-mode run within the seeded floor "
          f"(got {shown!r})")
    check(tab._pi_last_result is not None and tab._pi_last_result.get("source") == "storage",
          "the result records that it came from storage mode")

    # --- storage mode: a range reaching an ungenerated floor shows a clear error ------
    _set_entry(tab.pi_x_from_entry, "2")
    _set_entry(tab.pi_x_to_entry, "10")  # x=10 reaches into floor 1
    _set_entry(tab.pi_step_entry, "8")
    shown.clear()
    tab._on_pi_run()
    _pump(app, 2.0)
    check(len(shown) == 1 and shown[0][0] == "error",
          f"a storage-mode range reaching an ungenerated floor shows an error dialog "
          f"(got {shown!r})")

    # --- CSV export: only enabled once a result with rows exists, writes the page ------
    tab.pi_source_var.set("sieve")
    _set_entry(tab.pi_x_from_entry, "10")
    _set_entry(tab.pi_x_to_entry, "100")
    _set_entry(tab.pi_step_entry, "30")
    shown.clear()
    tab._on_pi_run()
    _pump(app, 2.0)
    check(str(tab.pi_export_button["state"]) == "normal",
          "Export CSV is enabled once a result with rows is displayed")

    import tkinter.filedialog
    csv_path = os.path.join(tmp_portal, "pi_approx_export_test.csv")
    tkinter.filedialog.asksaveasfilename = lambda **k: csv_path
    tab._on_pi_export_csv()
    check(os.path.isfile(csv_path), f"CSV export actually wrote a file at {csv_path!r}")
    with open(csv_path, newline="", encoding="utf-8") as f:
        exported_rows = list(csv.reader(f))
    check(exported_rows[0] == ["x", "pi_x", "li_x", "r_x", "li_error", "r_error"],
          f"CSV header matches the Treeview's own columns (got {exported_rows[0]!r})")
    check(len(exported_rows) - 1 == 4,
          f"CSV body has exactly one row per displayed checkpoint (x=10,40,70,100) "
          f"(got {len(exported_rows) - 1})")
    check(exported_rows[1][0] == "10" and exported_rows[1][1] == "4",
          f"first exported data row matches x=10's own pi(x)=4 (got {exported_rows[1]!r})")

    # --- primecount mode: monkeypatched WSL round trip (no real wsl.exe/libprimecount --
    # same "fake the module-level WSL call, exercise the worker plumbing" approach as
    # test_primesieve_calc_worker.py's own docstring explains) --------------------------
    import primeatlas.research.research_pi_approx_tab as rpat

    captured_argv = []

    def fake_query_ok(argv, portal_folder, timeout=120):
        captured_argv.append(argv)
        # Fake "exact" pi(x) answers, one per checkpoint, in argv's own order
        # (argv = ["python3", "-u", script, "pi_batch", <x1>, <x2>, ...]). Already
        # unwrapped from the query script's own {"ok":true,"result":...} envelope --
        # run_primecount_wsl_blocking's own contract, see its docstring.
        xs = [int(a) for a in argv[4:]]
        return True, [x // 2 for x in xs]

    rpat.run_primecount_wsl_blocking = fake_query_ok
    tab.pi_source_var.set("primecount")
    _set_entry(tab.pi_x_from_entry, "10")
    _set_entry(tab.pi_x_to_entry, "100")
    _set_entry(tab.pi_step_entry, "30")
    shown.clear()
    tab._on_pi_run()
    _pump(app, 2.0)
    check(shown == [], f"no error dialog for a valid primecount-mode run (got {shown!r})")
    check(captured_argv and captured_argv[-1][3] == "pi_batch",
          f"primecount mode calls the pi_batch op (got {captured_argv[-1] if captured_argv else None!r})")
    check(captured_argv and captured_argv[-1][4:] == ["10", "40", "70", "100"],
          f"pi_batch is called with ALL checkpoints in one round trip "
          f"(got {captured_argv[-1][4:] if captured_argv else None!r})")
    check(tab._pi_last_result is not None and tab._pi_last_result.get("source") == "primecount",
          "the result records that it came from primecount mode")
    rows = tab.pi_results_tree.get_children()
    check(str(tab.pi_results_tree.item(rows[0])["values"][1]) == "5",
          f"first row's pi(x) is the fake source's own answer (10//2=5) "
          f"(got {tab.pi_results_tree.item(rows[0])['values'][1]!r})")

    # --- primecount mode: a GENERIC WSL/library failure (kind=None) surfaces as a -----
    # plain error dialog, same as sieve/storage mode failures ---------------------------
    def fake_query_generic_fail(argv, portal_folder, timeout=120):
        return False, {"message": "some other failure (fake, for this test)", "kind": None}

    rpat.run_primecount_wsl_blocking = fake_query_generic_fail
    shown.clear()
    tab._on_pi_run()
    _pump(app, 2.0)
    check(len(shown) == 1 and shown[0][0] == "error",
          f"a generic primecount-mode failure shows a plain error dialog "
          f"(got {shown!r})")

    # --- primecount mode: a "not installed" failure is a DISTINCT _pi_job outcome -----
    # (kind="primecount_not_installed"), tested by calling _pi_job directly -- same
    # "test the underlying logic, not a real Tk dialog's button widget" convention
    # test_cudasieve_integration.py's own suite uses for ITS consent dialog -----------
    def fake_query_not_installed(argv, portal_folder, timeout=120):
        return False, {"message": "Could not load libprimecount (fake, for this test)",
                        "kind": "not_installed"}

    rpat.run_primecount_wsl_blocking = fake_query_not_installed
    pending_job = {"x_from": 10, "x_to": 100, "step": 30, "source": "primecount", "page": 0}
    kind, ok, data = tab._pi_job(pending_job, lambda *a: None)
    check(kind == "primecount_not_installed",
          f"_pi_job reports the specific 'not installed' kind instead of a generic "
          f"failure (got {kind!r})")
    check(not ok, "the 'not installed' result is still reported as a failure")
    check(data == pending_job,
          f"the failure carries the EXACT job dict needed to retry after installing "
          f"(got {data!r})")

    # --- the full round trip through _on_pi_worker_result: a "not installed" result --
    # must open the install-offer dialog (a Toplevel), NOT a generic error messagebox --
    shown.clear()
    tab._on_pi_worker_result(("primecount_not_installed", False, data), None)
    _pump(app, 0.3)
    check(shown == [], "a 'not installed' result does NOT show a generic error dialog")
    install_dialogs = [w for w in tab.winfo_children() if isinstance(w, tk.Toplevel)]
    check(len(install_dialogs) == 1,
          f"exactly one install-offer dialog (Toplevel) is shown "
          f"(got {len(install_dialogs)})")
    install_dialogs[0].destroy()

    # --- _start_primecount_install: called directly (same convention as _pi_job above,
    # and as test_cudasieve_integration.py's own direct _start_cudasieve_build() calls).
    # Both the install call itself AND the retried query are monkeypatched -- this
    # submits a REAL job to the REAL background worker (unlike the earlier steps that
    # called _pi_job/_on_pi_worker_result directly), so _pump() below drives it through
    # exactly as a live install click would, with no manual double-triggering.
    rpat.run_primecount_install_wsl_blocking = lambda portal_folder, timeout=300: (True, None)
    rpat.run_primecount_wsl_blocking = fake_query_ok
    captured_argv.clear()
    tab.status.set("")
    tab._start_primecount_install(data)
    check(tab._pi_pending_retry_job == data,
          f"_start_primecount_install remembers the exact job to retry after a "
          f"successful install (got {tab._pi_pending_retry_job!r})")
    check("primecount" in tab.status.get().lower(),
          f"starting the install updates the status bar (got {tab.status.get()!r})")

    # --- a successful install auto-retries the pending job, no second manual click ----
    _pump(app, 3.0)
    check(tab._pi_pending_retry_job is None,
          "the pending retry job is cleared once the install succeeds and the retry is submitted")
    check(captured_argv, "a successful install automatically re-ran the original query")
    check(tab._pi_last_result is not None and tab._pi_last_result.get("source") == "primecount",
          "the auto-retried run actually completed and produced a result")

    # --- a failed install shows an error dialog and does NOT consume the pending job --
    rpat.run_primecount_install_wsl_blocking = (
        lambda portal_folder, timeout=300: (False, "apt-get install failed (fake, for this test)"))
    shown.clear()
    tab._start_primecount_install(data)
    _pump(app, 2.0)
    check(len(shown) == 1 and shown[0][0] == "error",
          f"a failed install shows an error dialog (got {shown!r})")
    check(tab._pi_pending_retry_job == data,
          "a failed install does not clear the pending retry job (nothing was retried)")

    app.destroy()


if __name__ == "__main__":
    main()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
