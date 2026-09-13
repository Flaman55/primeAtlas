"""
test_research_squares_tab.py -- tests for primeatlas/research_squares_tab.py's
ResearchSquaresTab (Badania -> Przedzialy kwadratowe), the UI wired around
primeatlas/squares_window.py's pure check_interval_range()/check_interval_
range_from_source() (see that module's own test file, test_squares_window.py,
for the pure-logic checks -- this file only exercises the tkinter wiring:
preset switching, the required_count auto-fill, the custom a(n)/b(n) fields,
pagination buttons, error dialogs, the storage data-source toggle (Faza 2),
and CSV export (Faza 2)).

Builds the REAL app (same "no mocked LocalLoggedRunner-style stand-in needed
here -- there's no subprocess involved at all, just a background.
PersistentWorker thread in the same process" as e.g. test_gen_progress_bar_
engine_gating.py) rather than constructing ResearchSquaresTab in isolation,
so the exact same dependency-injection wiring prime_atlas_v1.py itself uses
is what gets tested. The storage-mode tests seed a real floor-0 window file
(primes 2,3,5,7 under 10p0/source_primes/) in a throwaway temp portal folder
-- same minimal-seed recipe as test_goldbach_worker.py's own module docstring
explains in detail (PGS1 window, sharded source_primes/ layout).

Usage (Windows, real display):
    python unitTests\\test_research_squares_tab.py
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
    tab test file's own _patch_app_settings (e.g. test_rings_tab.py)."""
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

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_squares_tab_test_")
    try:
        _run(tmp_portal, prime_sieve_v1, window_sharding)
    finally:
        shutil.rmtree(tmp_portal, ignore_errors=True)


def _run(tmp_portal, prime_sieve_v1, window_sharding):
    # Floor 0 ([1,10)) seeded with its real primes -- covers every Legendre n
    # this test's storage-mode checks use (n=1 -> [1,4], n=2 -> [4,9], both
    # inside floor 0; n=3 -> [9,16] deliberately reaches into floor 1, which
    # is NOT seeded, to exercise the "missing floor" error path).
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
    tab = app.research_squares_tab_widget

    settings_tab = app.settings_tab
    _patch_app_settings(settings_tab.app_settings)
    settings_tab.app_settings.set_storage_path(tmp_portal)
    settings_tab.wsl["set_portal_folder"](tmp_portal)
    app.update()

    # --- default preset is Legendre, required_count defaults to 1 -------------------
    check(tab._current_preset_id() == "legendre",
          f"the default preset is Legendre (got {tab._current_preset_id()!r})")
    check(tab.squares_required_count_entry.get() == "1",
          f"the default required_count field starts at 1 (got {tab.squares_required_count_entry.get()!r})")
    check(not tab.squares_custom_frame.winfo_manager(),
          "the custom a(n)/b(n) fields are not packed at all under the default preset")

    # --- run Legendre over a small range, expect it fully covered --------------------
    _set_entry(tab.squares_n_from_entry, "1")
    _set_entry(tab.squares_n_to_entry, "50")
    shown.clear()
    tab._on_squares_run()
    _pump(app, 2.0)
    check(shown == [], f"no error dialog for a valid Legendre run (got {shown!r})")
    rows = tab.squares_results_tree.get_children()
    check(len(rows) == 50, f"Legendre n=1..50 produces exactly 50 result rows (got {len(rows)})")
    values0 = tab.squares_results_tree.item(rows[0])["values"]
    check(str(values0[0]) == "1" and str(values0[1]) == "1" and str(values0[2]) == "4",
          f"first row is n=1, a=1, b=4 (got {values0!r})")
    check(tab._squares_last_result["covered"],
          "Legendre holds for n=1..50 -- no counterexamples")
    check(str(tab.squares_prev_button["state"]) == "disabled",
          "Prev is disabled on the very first page")
    check(str(tab.squares_next_button["state"]) == "disabled",
          "Next is disabled when the whole range fit on one page (50 < row cap)")

    # --- switching to Brocard reveals no custom fields, but DOES change the ----------
    # required_count default from 1 to 4 (the actual conjectured threshold, not
    # merely ">=1" -- see squares_window.py's own module docstring).
    tab.squares_preset_combo.current(2)  # brocard
    tab._on_squares_preset_changed()
    check(tab.squares_required_count_entry.get() == "4",
          f"switching to the Brocard preset resets required_count to its own "
          f"default, 4 (got {tab.squares_required_count_entry.get()!r})")
    check(not tab.squares_custom_frame.winfo_manager(),
          "Brocard preset does not show the custom a(n)/b(n) fields either")

    _set_entry(tab.squares_n_from_entry, "2")
    _set_entry(tab.squares_n_to_entry, "10")
    shown.clear()
    tab._on_squares_run()
    _pump(app, 2.0)
    check(shown == [], f"no error dialog for a valid Brocard run (got {shown!r})")
    check(len(tab.squares_results_tree.get_children()) == 9,
          f"Brocard n=2..10 produces exactly 9 rows "
          f"(got {len(tab.squares_results_tree.get_children())})")

    # --- switching to Custom reveals the a(n)/b(n) fields -----------------------------
    tab.squares_preset_combo.current(3)  # custom
    tab._on_squares_preset_changed()
    check(bool(tab.squares_custom_frame.winfo_manager()),
          "the Custom preset packs the a(n)/b(n) fields (winfo_manager reports 'pack')")

    _set_entry(tab.squares_n_from_entry, "1")
    _set_entry(tab.squares_n_to_entry, "5")
    _set_entry(tab.squares_custom_a_entry, "10*n")
    _set_entry(tab.squares_custom_b_entry, "10*n+1")
    shown.clear()
    tab._on_squares_run()
    _pump(app, 2.0)
    check(shown == [], f"no error dialog for a valid custom-formula run (got {shown!r})")
    check(not tab._squares_last_result["covered"],
          "custom [10n,10n+1] is NOT covered for every n in 1..5 (n=2,5 miss)")
    check(tab._squares_last_result["counterexamples"] == [2, 5],
          f"counterexamples are exactly n=2 and n=5 "
          f"(got {tab._squares_last_result['counterexamples']!r})")

    # --- an invalid custom formula shows an error dialog, no crash --------------------
    _set_entry(tab.squares_custom_a_entry, "not a formula (((")
    shown.clear()
    tab._on_squares_run()
    _pump(app, 1.0)
    check(len(shown) == 1 and shown[0][0] == "error",
          f"an invalid custom a(n) formula shows an error dialog instead of raising "
          f"(got {shown!r})")

    # --- n_to < n_from is rejected before ever touching the worker --------------------
    tab.squares_preset_combo.current(0)  # legendre
    tab._on_squares_preset_changed()
    _set_entry(tab.squares_n_from_entry, "10")
    _set_entry(tab.squares_n_to_entry, "1")
    shown.clear()
    tab._on_squares_run()
    _pump(app, 1.0)
    check(len(shown) == 1 and shown[0][0] == "error",
          f"n_to < n_from shows an error dialog (got {shown!r})")

    # --- an oversized range is refused with a clear error, not a hang/crash -----------
    _set_entry(tab.squares_n_from_entry, "1")
    _set_entry(tab.squares_n_to_entry, "1000000")
    shown.clear()
    tab._on_squares_run()
    _pump(app, 3.0)
    check(len(shown) == 1 and shown[0][0] == "error",
          f"an oversized range (needs a huge sieve) shows an error dialog "
          f"(got {shown!r})")

    # --- pagination: Prev/Next actually move between pages ----------------------------
    _set_entry(tab.squares_n_from_entry, "1")
    _set_entry(tab.squares_n_to_entry, "500")
    shown.clear()
    tab._on_squares_run()
    _pump(app, 3.0)
    check(shown == [], f"no error dialog for the pagination test's range (got {shown!r})")
    page0_first_n = tab.squares_results_tree.item(
        tab.squares_results_tree.get_children()[0])["values"][0]
    check(str(tab.squares_next_button["state"]) == "normal",
          "Next is enabled when more rows exist past the first page (500 rows > row cap)")
    tab._on_squares_next()
    _pump(app, 2.0)
    page1_first_n = tab.squares_results_tree.item(
        tab.squares_results_tree.get_children()[0])["values"][0]
    check(int(page1_first_n) > int(page0_first_n),
          f"clicking Next actually advances to a page with larger n's "
          f"(page0 first n={page0_first_n!r}, page1 first n={page1_first_n!r})")
    check(str(tab.squares_prev_button["state"]) == "normal",
          "Prev is enabled once on a page past the first")
    tab._on_squares_prev()
    _pump(app, 2.0)
    back_first_n = tab.squares_results_tree.item(
        tab.squares_results_tree.get_children()[0])["values"][0]
    check(str(back_first_n) == str(page0_first_n),
          f"clicking Prev returns to the original first page "
          f"(got {back_first_n!r}, expected {page0_first_n!r})")

    # --- storage mode: reads real data from the seeded floor 0 -----------------------
    tab.squares_preset_combo.current(0)  # legendre
    tab._on_squares_preset_changed()
    tab.squares_source_var.set("storage")
    _set_entry(tab.squares_n_from_entry, "1")
    _set_entry(tab.squares_n_to_entry, "2")
    shown.clear()
    tab._on_squares_run()
    _pump(app, 2.0)
    check(shown == [], f"no error dialog for a storage-mode run within the seeded floor "
          f"(got {shown!r})")
    check(tab._squares_last_result is not None and tab._squares_last_result.get("source") == "storage",
          "the result records that it came from storage mode")
    check(len(tab.squares_results_tree.get_children()) == 2,
          f"Legendre n=1..2 via storage mode produces 2 rows "
          f"(got {len(tab.squares_results_tree.get_children())})")
    check(tab._squares_last_result["covered"],
          "storage-mode result for n=1..2 is covered (floor 0's real primes: 2,3,5,7)")

    # --- storage mode: a range reaching an ungenerated floor shows a clear error ------
    _set_entry(tab.squares_n_from_entry, "1")
    _set_entry(tab.squares_n_to_entry, "3")  # n=3 needs b=16, which reaches into floor 1
    shown.clear()
    tab._on_squares_run()
    _pump(app, 2.0)
    check(len(shown) == 1 and shown[0][0] == "error",
          f"a storage-mode range reaching an ungenerated floor shows an error dialog "
          f"(got {shown!r})")
    expected_message = tab.T("research_squares.error_storage_missing", floor=1, upto=f"{16:,}")
    got_message = shown[0][1][1] if shown and len(shown[0][1]) > 1 else None
    check(got_message == expected_message,
          f"the missing-floor error names the specific short floor (floor 1, needed up to 16) "
          f"(got {got_message!r}, expected {expected_message!r})")

    # --- CSV export: only enabled once a result with rows exists, writes the page ------
    tab.squares_source_var.set("sieve")
    _set_entry(tab.squares_n_from_entry, "1")
    _set_entry(tab.squares_n_to_entry, "10")
    shown.clear()
    tab._on_squares_run()
    _pump(app, 2.0)
    check(str(tab.squares_export_button["state"]) == "normal",
          "Export CSV is enabled once a result with rows is displayed")

    import tkinter.filedialog
    csv_path = os.path.join(tmp_portal, "squares_export_test.csv")
    tkinter.filedialog.asksaveasfilename = lambda **k: csv_path
    tab._on_squares_export_csv()
    check(os.path.isfile(csv_path), f"CSV export actually wrote a file at {csv_path!r}")
    with open(csv_path, newline="", encoding="utf-8") as f:
        exported_rows = list(csv.reader(f))
    check(exported_rows[0] == ["n", "a", "b", "count", "covered"],
          f"CSV header matches the Treeview's own columns (got {exported_rows[0]!r})")
    check(len(exported_rows) - 1 == 10,
          f"CSV body has exactly one row per displayed n (n=1..10) "
          f"(got {len(exported_rows) - 1})")
    check(exported_rows[1] == ["1", "1", "4", "2", "1"],
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
