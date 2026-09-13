"""
test_research_gaps_tab.py -- tests for primeatlas/research_gaps_tab.py's
ResearchGapsTab (Badania -> Luki), the UI wired around
primeatlas/gaps_window.py's pure check_gap_range()/check_gap_range_from_
source() (see that module's own test file, test_gaps_window.py, for the
pure-logic checks -- this file only exercises the tkinter wiring: overlay
switching, pagination buttons, error dialogs, the storage data-source
toggle, and CSV export).

Same "build the REAL app" approach as test_research_squares_tab.py -- see
that file's own docstring for why. The storage-mode tests seed a real
floor-0 window file, same minimal-seed recipe.

Usage (Windows, real display):
    python unitTests\\test_research_gaps_tab.py
"""
import csv
import os
import shutil
import sys
import tempfile
import time

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

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_gaps_tab_test_")
    try:
        _run(tmp_portal, prime_sieve_v1, window_sharding)
    finally:
        shutil.rmtree(tmp_portal, ignore_errors=True)


def _run(tmp_portal, prime_sieve_v1, window_sharding):
    # Floor 0 ([1,10)) seeded with its real primes -- covers n=1..3 (p_1..p_4
    # = 2,3,5,7, all inside floor 0). n=4 needs p_5=11, which reaches into
    # floor 1, NOT seeded, to exercise the "missing floor" error path.
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
    tab = app.research_gaps_tab_widget

    settings_tab = app.settings_tab
    _patch_app_settings(settings_tab.app_settings)
    settings_tab.app_settings.set_storage_path(tmp_portal)
    settings_tab.wsl["set_portal_folder"](tmp_portal)
    app.update()

    # --- default overlay is "none", n_from defaults to 1 ------------------------------
    check(tab._current_overlay_id() == "none",
          f"the default overlay is 'none' (got {tab._current_overlay_id()!r})")
    check(tab.gaps_n_from_entry.get() == "1",
          f"the default n_from field starts at 1 (got {tab.gaps_n_from_entry.get()!r})")

    # --- run with no overlay over a small range ----------------------------------------
    _set_entry(tab.gaps_n_from_entry, "1")
    _set_entry(tab.gaps_n_to_entry, "5")
    shown.clear()
    tab._on_gaps_run()
    _pump(app, 2.0)
    check(shown == [], f"no error dialog for a valid run (got {shown!r})")
    rows = tab.gaps_results_tree.get_children()
    check(len(rows) == 5, f"n=1..5 produces exactly 5 result rows (got {len(rows)})")
    values0 = tab.gaps_results_tree.item(rows[0])["values"]
    check(str(values0[0]) == "1" and str(values0[1]) == "2" and str(values0[2]) == "3"
          and str(values0[3]) == "1",
          f"first row is n=1, p_1=2, p_2=3, gap=1 (got {values0!r})")
    check(str(values0[4]) == "-" and str(values0[5]) == "-",
          f"overlay='none' shows a dash for both overlay_value and holds (got {values0!r})")
    check(tab._gaps_last_result["max_gap"] == 4,
          f"the largest gap among n=1..5 is 4 (p_4=7 -> p_5=11) "
          f"(got {tab._gaps_last_result['max_gap']!r})")
    check(str(tab.gaps_prev_button["state"]) == "disabled",
          "Prev is disabled on the very first page")
    check(str(tab.gaps_next_button["state"]) == "disabled",
          "Next is disabled when the whole range fit on one page (5 < row cap)")

    # --- switching to Andrica shows holds=Yes for every row in a small range ----------
    tab.gaps_overlay_combo.current(1)  # andrica
    _set_entry(tab.gaps_n_from_entry, "1")
    _set_entry(tab.gaps_n_to_entry, "10")
    shown.clear()
    tab._on_gaps_run()
    _pump(app, 2.0)
    check(shown == [], f"no error dialog for a valid Andrica run (got {shown!r})")
    check(tab._gaps_last_result["counterexamples"] == [],
          "Andrica holds for every n=1..10 -- no counterexamples")
    rows = tab.gaps_results_tree.get_children()
    row0_values = tab.gaps_results_tree.item(rows[0])["values"]
    check(str(row0_values[5]) == tab.T("research_gaps.holds_yes"),
          f"Andrica's holds column shows the translated 'yes' text for a holding row "
          f"(got {row0_values[5]!r})")

    # --- switching to Cramer shows a ratio measurement, no holds verdict --------------
    tab.gaps_overlay_combo.current(3)  # cramer
    shown.clear()
    tab._on_gaps_run()
    _pump(app, 2.0)
    check(shown == [], f"no error dialog for a valid Cramer run (got {shown!r})")
    check(tab._gaps_last_result["max_cramer_ratio"] is not None,
          "Cramer's overlay populates max_cramer_ratio")
    rows = tab.gaps_results_tree.get_children()
    row0_values = tab.gaps_results_tree.item(rows[0])["values"]
    check(str(row0_values[5]) == "-",
          f"Cramer's holds column is always a dash (no per-n verdict) (got {row0_values[5]!r})")
    check(str(row0_values[4]) != "-",
          f"Cramer's overlay_value column shows an actual ratio (got {row0_values[4]!r})")

    # --- n_to < n_from is rejected before ever touching the worker --------------------
    tab.gaps_overlay_combo.current(0)  # none
    _set_entry(tab.gaps_n_from_entry, "10")
    _set_entry(tab.gaps_n_to_entry, "1")
    shown.clear()
    tab._on_gaps_run()
    _pump(app, 1.0)
    check(len(shown) == 1 and shown[0][0] == "error",
          f"n_to < n_from shows an error dialog (got {shown!r})")

    # --- an oversized range is refused with a clear error, not a hang/crash -----------
    _set_entry(tab.gaps_n_from_entry, "1")
    _set_entry(tab.gaps_n_to_entry, "50000000")
    shown.clear()
    tab._on_gaps_run()
    _pump(app, 3.0)
    check(len(shown) == 1 and shown[0][0] == "error",
          f"an oversized range (needs a huge sieve) shows an error dialog "
          f"(got {shown!r})")

    # --- pagination: Prev/Next actually move between pages ----------------------------
    _set_entry(tab.gaps_n_from_entry, "1")
    _set_entry(tab.gaps_n_to_entry, "500")
    shown.clear()
    tab._on_gaps_run()
    _pump(app, 3.0)
    check(shown == [], f"no error dialog for the pagination test's range (got {shown!r})")
    page0_first_n = tab.gaps_results_tree.item(
        tab.gaps_results_tree.get_children()[0])["values"][0]
    check(str(tab.gaps_next_button["state"]) == "normal",
          "Next is enabled when more rows exist past the first page (500 rows > row cap)")
    tab._on_gaps_next()
    _pump(app, 2.0)
    page1_first_n = tab.gaps_results_tree.item(
        tab.gaps_results_tree.get_children()[0])["values"][0]
    check(int(page1_first_n) > int(page0_first_n),
          f"clicking Next actually advances to a page with larger n's "
          f"(page0 first n={page0_first_n!r}, page1 first n={page1_first_n!r})")
    check(str(tab.gaps_prev_button["state"]) == "normal",
          "Prev is enabled once on a page past the first")
    tab._on_gaps_prev()
    _pump(app, 2.0)
    back_first_n = tab.gaps_results_tree.item(
        tab.gaps_results_tree.get_children()[0])["values"][0]
    check(str(back_first_n) == str(page0_first_n),
          f"clicking Prev returns to the original first page "
          f"(got {back_first_n!r}, expected {page0_first_n!r})")

    # --- storage mode: reads real data from the seeded floor 0 -----------------------
    tab.gaps_source_var.set("storage")
    _set_entry(tab.gaps_n_from_entry, "1")
    _set_entry(tab.gaps_n_to_entry, "3")
    shown.clear()
    tab._on_gaps_run()
    _pump(app, 2.0)
    check(shown == [], f"no error dialog for a storage-mode run within the seeded floor "
          f"(got {shown!r})")
    check(tab._gaps_last_result is not None and tab._gaps_last_result.get("source") == "storage",
          "the result records that it came from storage mode")
    check(len(tab.gaps_results_tree.get_children()) == 3,
          f"n=1..3 via storage mode produces 3 rows "
          f"(got {len(tab.gaps_results_tree.get_children())})")

    # --- storage mode: a range reaching an ungenerated floor shows a clear error ------
    _set_entry(tab.gaps_n_from_entry, "1")
    _set_entry(tab.gaps_n_to_entry, "4")  # n=4 needs p_5=11, reaches into floor 1
    shown.clear()
    tab._on_gaps_run()
    _pump(app, 2.0)
    check(len(shown) == 1 and shown[0][0] == "error",
          f"a storage-mode range reaching an ungenerated floor shows an error dialog "
          f"(got {shown!r})")

    # --- CSV export: only enabled once a result with rows exists, writes the page ------
    tab.gaps_source_var.set("sieve")
    _set_entry(tab.gaps_n_from_entry, "1")
    _set_entry(tab.gaps_n_to_entry, "5")
    shown.clear()
    tab._on_gaps_run()
    _pump(app, 2.0)
    check(str(tab.gaps_export_button["state"]) == "normal",
          "Export CSV is enabled once a result with rows is displayed")

    import tkinter.filedialog
    csv_path = os.path.join(tmp_portal, "gaps_export_test.csv")
    tkinter.filedialog.asksaveasfilename = lambda **k: csv_path
    tab._on_gaps_export_csv()
    check(os.path.isfile(csv_path), f"CSV export actually wrote a file at {csv_path!r}")
    with open(csv_path, newline="", encoding="utf-8") as f:
        exported_rows = list(csv.reader(f))
    check(exported_rows[0] == ["n", "p_n", "p_n1", "gap", "overlay_value", "holds"],
          f"CSV header matches the Treeview's own columns (got {exported_rows[0]!r})")
    check(len(exported_rows) - 1 == 5,
          f"CSV body has exactly one row per displayed n (n=1..5) "
          f"(got {len(exported_rows) - 1})")
    check(exported_rows[1] == ["1", "2", "3", "1", "", ""],
          f"first exported data row matches n=1's own values, overlay='none' so blank "
          f"overlay_value/holds (got {exported_rows[1]!r})")

    app.destroy()


if __name__ == "__main__":
    main()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
