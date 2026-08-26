"""
test_constellations_tab.py -- functional regression test for the Constellations tab's
three sub-tabs (primeatlas/constellations_hits_tab.py's ConstellationsHitsTab,
constellations_calc_tab.py's ConstellationsCalcTab, constellations_records_tab.py's
ConstellationsRecordsTab, plus their shared pure-logic backend in
primeatlas/constellations.py), extracted from prime_atlas_v1.py during the refactor
branch's Faza 3 (tab-by-tab backend/UI split, 2026-08-23; task #388). Unlike the Primes
tab, this tab has TWO extra wrinkles this test specifically exercises:

  1. A genuine three-way coupling for a "const" search's completion (search worker +
     Magazyn/hits display + Kalkulator konstelacji's pending-search state) that stayed
     at the app level as _on_const_search_result -- see that method's own docstring.
     The calculator-triggered-search path below is the only way to exercise that
     coupling end to end.
  2. ConstellationsRecordsTab's cell/detail-row double-click drill-down, which needs
     real Treeview geometry (bbox) to simulate a click since identify_region/
     identify_row/identify_column read actual widget layout -- a small _FakeEvent with
     x/y from tree.bbox(...) stands in for a real button-1 double-click event, same
     idea test_const_records_worker.py already uses PersistentWorker.submit() directly
     to sidestep native file dialogs.

Builds the real PortalBrowserApp() end to end against a real on-disk portal folder,
seeded with ONE real prime window (containing an actual prime P) and ONE real
constellation hit file (pattern k=2/id=1, twin primes, offsets [0, 2]) recording P
itself as a hit base -- so a "const" search for P finds both a real prime_result AND
real participation without needing constellation_finder_v1.py to actually run.

Usage (Windows, real display):
    python unitTests\\test_constellations_tab.py

Usage (this sandbox, headless):
    PYTHONPATH="/tmp/tkextract/usr/lib/python3.10:/tmp/tkextract/usr/lib/python3.10/lib-dynload:$PYTHONPATH" \\
    LD_LIBRARY_PATH="/tmp/tkextract/usr/lib:$LD_LIBRARY_PATH" \\
    xvfb-run -a python3 unitTests/test_constellations_tab.py
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
    tkinter.messagebox.askyesno = lambda *a, **k: False
    return shown


def _pump(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def _primes_in(lo, hi):
    return [p for p in range(lo, hi) if p > 1 and all(p % d for d in range(2, int(p ** 0.5) + 1))]


class _FakeEvent:
    """Stand-in for a real tkinter click event -- just the x/y attributes
    identify_region/identify_row/identify_column actually read."""
    def __init__(self, x, y):
        self.x = x
        self.y = y


def main():
    import prime_sieve_v1
    import pattern_catalog_v1

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_constellations_tab_test_")
    try:
        # Floor 10p3: a real prime window containing P=1009, plus a real constellation
        # hit file for k=2/id=1 (twin primes, offsets [0, 2]) recording P as a hit BASE
        # (position 0, offset 0) -- so a "const" search for P finds both a genuine
        # prime_result and genuine participation without ever running
        # constellation_finder_v1.py.
        P = 1009
        primes_1000_1100 = _primes_in(1000, 1100)
        check(P in primes_1000_1100, f"fixture sanity: {P} is prime (got primes: {primes_1000_1100[:5]}...)")

        # source_primes/ is sharded into shard_NNNNN subfolders (see window_sharding.py,
        # task #405) -- placed under shard_00000, matching how a real low-index window
        # would land.
        import window_sharding
        floor3_dir = os.path.join(tmp_portal, "10p3", "source_primes")
        floor3_shard_dir = window_sharding.shard_dir(floor3_dir, 0)
        os.makedirs(floor3_shard_dir, exist_ok=True)
        prime_sieve_v1.write_prime_window(
            os.path.join(floor3_shard_dir, "PRIME_WINDOW_0000001000.bin"), primes_1000_1100)

        k = 2
        variant = pattern_catalog_v1.patterns_for_k(k)[0]
        vid = variant["id"]
        check(variant["offsets"] == [0, 2], f"fixture sanity: k=2 v={vid} is twin primes (got {variant['offsets']})")

        hit_dir = os.path.join(tmp_portal, "10p3", "constellations", f"k{k}", f"variant{vid}")
        os.makedirs(hit_dir, exist_ok=True)
        prime_sieve_v1.write_prime_window(
            os.path.join(hit_dir, f"HITS_10p3_k{k}_v{vid}.bin"), [P])

        shown = _patch_messageboxes()

        sys.argv = ["prime_atlas_v1.py"]
        import prime_atlas_v1

        prime_atlas_v1.PAGE_SIZE = 50
        _patch_app_settings(prime_atlas_v1.APP_SETTINGS)
        prime_atlas_v1.APP_SETTINGS.set_storage_path(tmp_portal)
        prime_atlas_v1.PORTAL_FOLDER = tmp_portal

        app_cls = prime_atlas_v1._build_gui()
        app = app_cls()
        _pump(app, 5.0)

        hits = app.constellations_hits_tab_widget
        calc = app.constellations_calc_tab_widget
        records = app.constellations_records_tab_widget

        # === 1. Magazyn (ConstellationsHitsTab): tree population + pattern preview ===
        top_nodes = hits.hits_tree.get_children("")
        check(len(top_nodes) == 1, f"hits tree has exactly 1 floor node (got {len(top_nodes)})")
        node3 = top_nodes[0]
        check(hits.hits_tree.item(node3, "text") == "10p3",
              f"the seeded floor shows up by name (got {hits.hits_tree.item(node3, 'text')!r})")

        hits.hits_tree.focus(node3)
        hits._populate_pietro_node(node3)
        k_nodes = hits.hits_tree.get_children(node3)
        check(len(k_nodes) == 1, f"floor node has exactly 1 k-group (got {len(k_nodes)})")
        variant_nodes = hits.hits_tree.get_children(k_nodes[0])
        check(len(variant_nodes) == 1, f"k=2 group has exactly 1 variant node (got {len(variant_nodes)})")
        pattern_item = variant_nodes[0]
        check(hits.hits_tree.item(pattern_item, "values")[0] == "1",
              f"the v={vid} node shows count=1 (got {hits.hits_tree.item(pattern_item, 'values')})")

        hits.hits_tree.selection_set(pattern_item)
        hits.hits_tree.focus(pattern_item)
        hits._on_tree_select(None)
        check(str(hits.hits_load_preview_btn["state"]) == "normal",
              "selecting the populated pattern node enables Load preview")

        hits.load_preview()
        check(hits._hit_values == [P], f"load_preview() decoded the exact seeded hit base (got {hits._hit_values})")

        # === 2. Search box: real "const" search round-trips through the shared worker ===
        hits.hits_search_entry.delete(0, "end")
        hits.hits_search_entry.insert(0, str(P))
        hits.search_constellation()
        check(app._totals_search.search_busy, "clicking Search dispatches a 'const' job (search_busy set)")
        _pump(app, 3.0)
        check(not app._totals_search.search_busy, "'const' search job settles after the worker result")
        check(str(P) in app.status.get(), f"status mentions the searched number (got: {app.status.get()!r})")
        check(len(hits._search_results_data) == 1,
              f"search found exactly 1 participation record (got {len(hits._search_results_data)})")
        check(hits._search_results_data[0]["base_exponent"] == 3 and hits._search_results_data[0]["hit_base"] == P,
              f"the participation record points at the right floor/base (got {hits._search_results_data[0]})")

        # Double-clicking the one search result row jumps the preview straight to it.
        hits.search_results_list.selection_clear(0, "end")
        hits.search_results_list.selection_set(0)
        hits._on_search_result_activate(None)
        check(hits._selected_hit_path is not None and hits._hit_values == [P],
              "double-clicking the search result jumped the Magazyn preview to the right pattern")

        # === 3. Kalkulator konstelacji: compute + search-selected triggers the SAME ===
        # === real search, and (being calculator-initiated) auto-jumps on completion ===
        calc.k_combo.set(str(k))
        calc._on_k_changed()
        calc.variant_combo.current(0)
        calc._on_variant_changed()
        calc.exp_entry.delete(0, "end")
        calc.exp_entry.insert(0, "3")
        calc.offset_entry.delete(0, "end")
        calc.offset_entry.insert(0, str(P - 1000))  # n0 = 10**3 + 9 = 1009 = P
        calc._on_compute()
        rows = calc._numbers
        check(rows == [(0, P), (2, P + 2)],
              f"compute() produced the exact expected (offset, number) pairs (got {rows})")

        # Select the offset-0 row (== P itself, the seeded hit) and search it.
        first_row_item = calc.results_tree.get_children("")[0]
        calc.results_tree.selection_set(first_row_item)
        calc.search_selected()
        check(app.main_notebook.select() == str(app.constellations_tab),
              "search_selected() switched the main notebook to the Constellations tab")
        check(hits.hits_search_entry.get() == str(P),
              f"search_selected() filled the Magazyn search box with {P} (got {hits.hits_search_entry.get()!r})")
        _pump(app, 3.0)
        check(calc.get_pending() is None,
              "calculator's pending-search state was cleared once the search resolved")
        check(hits._selected_hit_path is not None and hits._hit_values == [P],
              "calculator-initiated search auto-jumped the Magazyn preview to the exact pattern/number")

        # === 4. Tabela rekordow: scan + cell drill-down + jump back to Magazyn ========
        # bbox() below needs the tree to actually be mapped on screen (Tk doesn't
        # compute real cell geometry for a widget sitting on an unselected notebook
        # page), so switch to this sub-tab explicitly first.
        app.main_notebook.select(app.constellations_tab)
        app.constellations_sub_notebook.select(app.constellations_records_tab)
        app.update()

        records.k_combo.set(str(k))
        records.floor_from_entry.delete(0, "end")
        records.floor_to_entry.delete(0, "end")
        records._on_scan_clicked()
        check(records._busy, "records 'scan' job marked busy immediately after dispatch")
        _pump(app, 3.0)
        check(not records._busy, "records 'scan' job settles after a PersistentWorker result")
        check(records._last is not None and records._last[0] == k,
              f"records scan populated _last for the requested k (got {records._last[0] if records._last else None})")
        tree_rows = records.tree.get_children("")
        check(len(tree_rows) == 1, f"records tree has exactly 1 floor row (got {len(tree_rows)})")
        check(tree_rows[0] == "3", f"the row's iid is the floor's base_exponent (got {tree_rows[0]!r})")

        app.update()
        bbox = records.tree.bbox(tree_rows[0], f"v{vid}")
        check(bool(bbox), f"the v={vid} cell has real on-screen geometry (got bbox={bbox})")
        if bbox:
            x, y, w, h = bbox
            fake_event = _FakeEvent(x + w // 2, y + h // 2)
            records._on_cell_activate(fake_event)
            check(records._detail_rows == [(P, P - 1000)],
                  f"cell drill-down loaded the exact single hit (number, offset) (got {records._detail_rows})")
            check(records._detail_context is not None and records._detail_context["base_exponent"] == 3,
                  f"drill-down context recorded the right floor (got {records._detail_context})")

            # Double-clicking that one detail row jumps back to the Magazyn tab, landing
            # on the exact same number -- reset the hits tab's state first so this
            # genuinely proves the jump (not a leftover from step 1/3 above).
            hits._reset_preview_state()
            hits._selected_hit_path = None
            records.detail_list.selection_clear(0, "end")
            records.detail_list.selection_set(0)
            records._on_detail_activate(None)
            check(hits._selected_hit_path is not None and hits._hit_values == [P],
                  "Tabela rekordow's drill-down jump landed back on the exact hit in Magazyn")

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
