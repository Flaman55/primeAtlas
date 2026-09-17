"""
test_research_polynomials_tab.py -- tests for
primeatlas/research/research_polynomials_tab.py's ResearchPolynomialsTab (Badania ->
Wielomiany pierwszorodne), the UI wired around
primeatlas/research/polynomials_window.py's pure check_polynomial_range()/check_
polynomial_range_from_source() (see that module's own test file,
test_polynomials_window.py, for the pure-logic checks -- this file only
exercises the tkinter wiring: preset switching, the custom f(n) field,
pagination buttons, error dialogs, the storage data-source toggle, and CSV
export).

Same "build the REAL app" approach as test_research_squares_tab.py -- see
that file's own docstring for why (no mocked stand-in needed, just a
background.PersistentWorker thread in the same process). The storage-mode
tests seed a real floor-0 window file, same minimal-seed recipe.

Usage (Windows, real display):
    python unitTests\\test_research_polynomials_tab.py
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

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_polynomials_tab_test_")
    try:
        _run(tmp_portal, prime_sieve_v1, window_sharding)
    finally:
        shutil.rmtree(tmp_portal, ignore_errors=True)


def _run(tmp_portal, prime_sieve_v1, window_sharding):
    # Floor 0 ([1,10)) seeded with its real primes -- covers Landau n=1,2
    # (f(1)=2, f(2)=5, both inside floor 0). n=3 (f(3)=10) stays inside floor
    # 0 too, so a range reaching floor 1 needs a larger n -- Euler n=7
    # (f(7)=97) deliberately reaches into floor 1, which is NOT seeded, to
    # exercise the "missing floor" error path.
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
    tab = app.research_polynomials_tab_widget

    settings_tab = app.settings_tab
    _patch_app_settings(settings_tab.app_settings)
    settings_tab.app_settings.set_storage_path(tmp_portal)
    settings_tab.wsl["set_portal_folder"](tmp_portal)
    app.update()

    # --- default preset is Landau, n_from defaults to 0 -------------------------------
    check(tab._current_preset_id() == "landau",
          f"the default preset is Landau (got {tab._current_preset_id()!r})")
    check(tab.poly_n_from_entry.get() == "0",
          f"the default n_from field starts at 0 (got {tab.poly_n_from_entry.get()!r})")
    check(not tab.poly_custom_frame.winfo_manager(),
          "the custom f(n) field is not packed at all under the default preset")

    # --- run Landau over a small range ------------------------------------------------
    _set_entry(tab.poly_n_from_entry, "1")
    _set_entry(tab.poly_n_to_entry, "5")
    shown.clear()
    tab._on_poly_run()
    _pump(app, 2.0)
    check(shown == [], f"no error dialog for a valid Landau run (got {shown!r})")
    rows = tab.poly_results_tree.get_children()
    check(len(rows) == 5, f"Landau n=1..5 produces exactly 5 result rows (got {len(rows)})")
    values0 = tab.poly_results_tree.item(rows[0])["values"]
    check(str(values0[0]) == "1" and str(values0[1]) == "2",
          f"first row is n=1, f(n)=2 (got {values0!r})")
    check(tab._poly_last_result["prime_count"] == 3,
          f"Landau n=1..5 has 3 primes among its values (2,5,17) "
          f"(got {tab._poly_last_result['prime_count']!r})")
    check(str(tab.poly_prev_button["state"]) == "disabled",
          "Prev is disabled on the very first page")
    check(str(tab.poly_next_button["state"]) == "disabled",
          "Next is disabled when the whole range fit on one page (5 < row cap)")

    # --- switching to Euler shows the famous n=0..39 all-prime run --------------------
    tab.poly_preset_combo.current(1)  # euler
    tab._on_poly_preset_changed()
    check(not tab.poly_custom_frame.winfo_manager(),
          "Euler preset does not show the custom f(n) field either")

    _set_entry(tab.poly_n_from_entry, "0")
    _set_entry(tab.poly_n_to_entry, "39")
    shown.clear()
    tab._on_poly_run()
    _pump(app, 2.0)
    check(shown == [], f"no error dialog for a valid Euler run (got {shown!r})")
    check(tab._poly_last_result["prime_count"] == 40,
          f"Euler's polynomial is prime for all 40 values n=0..39 "
          f"(got {tab._poly_last_result['prime_count']!r})")

    # --- switching to Custom reveals the f(n) field -----------------------------------
    tab.poly_preset_combo.current(2)  # custom
    tab._on_poly_preset_changed()
    check(bool(tab.poly_custom_frame.winfo_manager()),
          "the Custom preset packs the f(n) field (winfo_manager reports 'pack')")

    _set_entry(tab.poly_n_from_entry, "1")
    _set_entry(tab.poly_n_to_entry, "10")
    _set_entry(tab.poly_custom_formula_entry, "2*n+1")
    shown.clear()
    tab._on_poly_run()
    _pump(app, 2.0)
    check(shown == [], f"no error dialog for a valid custom-formula run (got {shown!r})")
    expected_count = sum(1 for n in range(1, 11) if (2 * n + 1) in (3, 5, 7, 11, 13, 17, 19, 23))
    check(tab._poly_last_result["prime_count"] == expected_count,
          f"custom f(n)=2n+1 counted correctly "
          f"(got {tab._poly_last_result['prime_count']!r}, expected {expected_count!r})")

    # --- an invalid custom formula shows an error dialog, no crash --------------------
    _set_entry(tab.poly_custom_formula_entry, "not a formula (((")
    shown.clear()
    tab._on_poly_run()
    _pump(app, 1.0)
    check(len(shown) == 1 and shown[0][0] == "error",
          f"an invalid custom f(n) formula shows an error dialog instead of raising "
          f"(got {shown!r})")

    # --- n_to < n_from is rejected before ever touching the worker --------------------
    tab.poly_preset_combo.current(0)  # landau
    tab._on_poly_preset_changed()
    _set_entry(tab.poly_n_from_entry, "10")
    _set_entry(tab.poly_n_to_entry, "1")
    shown.clear()
    tab._on_poly_run()
    _pump(app, 1.0)
    check(len(shown) == 1 and shown[0][0] == "error",
          f"n_to < n_from shows an error dialog (got {shown!r})")

    # --- an oversized range is refused with a clear error, not a hang/crash -----------
    _set_entry(tab.poly_n_from_entry, "1")
    _set_entry(tab.poly_n_to_entry, "1000000")
    shown.clear()
    tab._on_poly_run()
    _pump(app, 3.0)
    check(len(shown) == 1 and shown[0][0] == "error",
          f"an oversized range (needs a huge sieve) shows an error dialog "
          f"(got {shown!r})")

    # --- pagination: Prev/Next actually move between pages ----------------------------
    _set_entry(tab.poly_n_from_entry, "1")
    _set_entry(tab.poly_n_to_entry, "500")
    shown.clear()
    tab._on_poly_run()
    _pump(app, 3.0)
    check(shown == [], f"no error dialog for the pagination test's range (got {shown!r})")
    page0_first_n = tab.poly_results_tree.item(
        tab.poly_results_tree.get_children()[0])["values"][0]
    check(str(tab.poly_next_button["state"]) == "normal",
          "Next is enabled when more rows exist past the first page (500 rows > row cap)")
    tab._on_poly_next()
    _pump(app, 2.0)
    page1_first_n = tab.poly_results_tree.item(
        tab.poly_results_tree.get_children()[0])["values"][0]
    check(int(page1_first_n) > int(page0_first_n),
          f"clicking Next actually advances to a page with larger n's "
          f"(page0 first n={page0_first_n!r}, page1 first n={page1_first_n!r})")
    check(str(tab.poly_prev_button["state"]) == "normal",
          "Prev is enabled once on a page past the first")
    tab._on_poly_prev()
    _pump(app, 2.0)
    back_first_n = tab.poly_results_tree.item(
        tab.poly_results_tree.get_children()[0])["values"][0]
    check(str(back_first_n) == str(page0_first_n),
          f"clicking Prev returns to the original first page "
          f"(got {back_first_n!r}, expected {page0_first_n!r})")

    # --- storage mode: reads real data from the seeded floor 0 -----------------------
    tab.poly_preset_combo.current(0)  # landau
    tab._on_poly_preset_changed()
    tab.poly_source_var.set("storage")
    _set_entry(tab.poly_n_from_entry, "1")
    _set_entry(tab.poly_n_to_entry, "2")
    shown.clear()
    tab._on_poly_run()
    _pump(app, 2.0)
    check(shown == [], f"no error dialog for a storage-mode run within the seeded floor "
          f"(got {shown!r})")
    check(tab._poly_last_result is not None and tab._poly_last_result.get("source") == "storage",
          "the result records that it came from storage mode")
    check(len(tab.poly_results_tree.get_children()) == 2,
          f"Landau n=1..2 via storage mode produces 2 rows "
          f"(got {len(tab.poly_results_tree.get_children())})")
    check(tab._poly_last_result["prime_count"] == 2,
          "storage-mode result for n=1..2 finds both f(1)=2 and f(2)=5 prime "
          "(floor 0's real primes: 2,3,5,7)")

    # --- storage mode: a range reaching an ungenerated floor shows a clear error ------
    tab.poly_preset_combo.current(1)  # euler
    tab._on_poly_preset_changed()
    _set_entry(tab.poly_n_from_entry, "0")
    _set_entry(tab.poly_n_to_entry, "7")  # n=7 -> f(7)=97, reaches into floor 1
    shown.clear()
    tab._on_poly_run()
    _pump(app, 2.0)
    check(len(shown) == 1 and shown[0][0] == "error",
          f"a storage-mode range reaching an ungenerated floor shows an error dialog "
          f"(got {shown!r})")
    expected_message = tab.T("research_polynomials.error_storage_missing", floor=1, upto=f"{97:,}")
    got_message = shown[0][1][1] if shown and len(shown[0][1]) > 1 else None
    check(got_message == expected_message,
          f"the missing-floor error names the specific short floor (floor 1, needed up to 97) "
          f"(got {got_message!r}, expected {expected_message!r})")

    # --- CSV export: only enabled once a result with rows exists, writes the page ------
    tab.poly_preset_combo.current(0)  # landau
    tab._on_poly_preset_changed()
    tab.poly_source_var.set("sieve")
    _set_entry(tab.poly_n_from_entry, "1")
    _set_entry(tab.poly_n_to_entry, "5")
    shown.clear()
    tab._on_poly_run()
    _pump(app, 2.0)
    check(str(tab.poly_export_button["state"]) == "normal",
          "Export CSV is enabled once a result with rows is displayed")

    import tkinter.filedialog
    csv_path = os.path.join(tmp_portal, "polynomials_export_test.csv")
    tkinter.filedialog.asksaveasfilename = lambda **k: csv_path
    tab._on_poly_export_csv()
    check(os.path.isfile(csv_path), f"CSV export actually wrote a file at {csv_path!r}")
    with open(csv_path, newline="", encoding="utf-8") as f:
        exported_rows = list(csv.reader(f))
    check(exported_rows[0] == ["n", "value", "is_prime"],
          f"CSV header matches the Treeview's own columns (got {exported_rows[0]!r})")
    check(len(exported_rows) - 1 == 5,
          f"CSV body has exactly one row per displayed n (n=1..5) "
          f"(got {len(exported_rows) - 1})")
    check(exported_rows[1] == ["1", "2", "1"],
          f"first exported data row matches n=1's own displayed values "
          f"(got {exported_rows[1]!r})")

    app.destroy()


if __name__ == "__main__":
    main()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
