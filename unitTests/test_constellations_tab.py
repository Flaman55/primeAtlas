"""
test_constellations_tab.py -- functional regression test for the Constellations tab's
three sub-tabs (primeatlas/constellations/constellations_hits_tab.py's ConstellationsHitsTab,
constellations_calc_tab.py's ConstellationsCalcTab, constellations_records_tab.py's
ConstellationsRecordsTab, plus their shared pure-logic backend in
primeatlas/constellations/constellations.py), extracted from prime_atlas_v1.py during the refactor
branch's tab-by-tab backend/UI split. Unlike the Primes
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

        # === 0. Export od/do filled but no pattern active yet -> a clear error, not
        # a silently-wrong whole-range export or a crash. ===
        records.detail_export_from_entry.insert(0, "1")
        records.detail_export_to_entry.insert(0, "1")
        shown_before_guard = len(shown)
        records._export_csv()
        check(len(shown) == shown_before_guard + 1 and shown[-1][0] == "error",
              f"od/do filled with no active pattern shows an error, not a silent export (got {shown[-1:]})")
        check(not records._busy, "the guard refuses before ever dispatching a job")
        records.detail_export_from_entry.delete(0, "end")
        records.detail_export_to_entry.delete(0, "end")

        # === 1. Magazyn (ConstellationsHitsTab): tree population + pattern preview ===
        top_nodes = hits.hits_tree.get_children("")
        check(len(top_nodes) == 1, f"hits tree has exactly 1 floor node (got {len(top_nodes)})")
        node3 = top_nodes[0]
        check(hits.hits_tree.item(node3, "text") == "10p3",
              f"the seeded floor shows up by name (got {hits.hits_tree.item(node3, 'text')!r})")

        hits.hits_tree.focus(node3)
        hits._populate_floor_node(node3)
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
        check(hits._hit_values == [P],
              f"selecting the populated pattern node auto-loads its preview, no separate "
              f"'Load preview' click needed (got {hits._hit_values})")

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

        # === 4. Interactive preview/drill-down REFUSES a large, NOT-YET-PAGED pattern
        # instead of attempting a full decode on the GUI thread. Guards against the
        # GUI hanging when a huge, not-yet-migrated-to-pages hit file (e.g. billions
        # of hits) is opened via a plain double-click preview load.
        # hit_paging.PAGE_SIZE is monkeypatched down to keep this fast and
        # deterministic without needing a real oversized fixture file. ===
        import hit_paging
        original_page_size = hit_paging.PAGE_SIZE
        hit_paging.PAGE_SIZE = 3
        try:
            floor4_hit_dir = os.path.join(tmp_portal, "10p4", "constellations", f"k{k}", f"variant{vid}")
            os.makedirs(floor4_hit_dir, exist_ok=True)
            oversized_values = [4000 + 2 * i for i in range(1, 6)]  # 5 values > patched PAGE_SIZE=3
            prime_sieve_v1.write_prime_window(
                os.path.join(floor4_hit_dir, f"HITS_10p4_k{k}_v{vid}.bin"), oversized_values)

            # --- Magazyn (load_preview) ---
            hits._reset_preview_state()
            hits._selected_hit_path = os.path.join(floor4_hit_dir, f"HITS_10p4_k{k}_v{vid}.bin")
            hits._selected_hit_base_exponent = 4
            hits._selected_hit_pattern = variant
            hits._selected_hit_total_count = len(oversized_values)
            shown_before = len(shown)
            hits.load_preview()
            check(hits._hit_values is None,
                  "load_preview() refuses an oversized not-yet-paged pattern (no decode attempted)")
            check(len(shown) == shown_before + 1 and shown[-1][0] == "error",
                  f"load_preview() shows an error dialog instead of hanging (got {shown[-1:]})")

            # --- Tabela rekordow (_on_cell_activate) ---
            records.floor_from_entry.delete(0, "end")
            records.floor_to_entry.delete(0, "end")
            records._on_scan_clicked()
            _pump(app, 3.0)
            app.update()
            tree_rows2 = records.tree.get_children("")
            check("4" in tree_rows2, f"records tree now also includes floor 4 (got {tree_rows2})")
            records.tree.see("4")
            app.update()
            bbox4 = records.tree.bbox("4", f"v{vid}")
            check(bool(bbox4), f"floor 4's v={vid} cell has real on-screen geometry (got bbox={bbox4})")
            if bbox4:
                x, y, w, h = bbox4
                fake_event4 = _FakeEvent(x + w // 2, y + h // 2)
                records._on_cell_activate(fake_event4)
                check(records._detail_rows == [],
                      f"cell drill-down refuses an oversized not-yet-paged pattern (got {records._detail_rows})")
                check(records._detail_context is None,
                      "cell drill-down sets no detail context for a refused pattern")
        finally:
            hit_paging.PAGE_SIZE = original_page_size

        # === 5. Export: CSV streams rows (never materializes the whole pattern in
        # memory -- see iter_constellation_records_detail_rows()'s own docstring),
        # PDF refuses an oversized range instead of trying to lay it all out. Calls
        # records._job() directly (the same dict shape _export_pdf()/_export_csv()
        # build before handing off to the worker) to bypass the real save-file
        # dialog those two methods open. Floors 3+4 together have 6 total k=2 hits
        # (1 from floor 3's original fixture + 5 from floor 4's oversized-guard
        # fixture above) -- monkeypatching the PDF row limit down to 3 makes that
        # combined range exceed it without needing a real huge fixture. ===
        import primeatlas.constellations.constellations_records_tab as _records_tab_module
        original_pdf_limit = _records_tab_module.PDF_EXPORT_ROW_LIMIT

        csv_path = os.path.join(tmp_portal, "export_test.csv")
        csv_job = {"mode": "export_csv", "k": k, "path": csv_path}
        csv_result = records._job(csv_job, lambda *a: None)
        check(csv_result[:3] == ("export_csv", k, True),
              f"export_csv job succeeds (got {csv_result[:3]})")
        with open(csv_path, encoding="utf-8") as f:
            csv_lines = f.read().strip().splitlines()
        check(len(csv_lines) == 1 + 6,
              f"CSV has a header + all 6 combined k=2 hits from floors 3 and 4 (got {len(csv_lines)} lines)")

        _records_tab_module.PDF_EXPORT_ROW_LIMIT = 3
        try:
            pdf_path = os.path.join(tmp_portal, "export_test.pdf")
            pdf_job = {"mode": "export_pdf", "k": k, "path": pdf_path}
            pdf_result = records._job(pdf_job, lambda *a: None)
            check(pdf_result[:3] == ("export_pdf", k, False),
                  f"export_pdf job refuses a range over the (patched) row limit (got {pdf_result[:3]})")
            check(isinstance(pdf_result[3], tuple) and pdf_result[3][0] == "pdf_too_large"
                  and pdf_result[3][1] == 6,
                  f"export_pdf failure payload names the reason and real row count (got {pdf_result[3]})")
            check(not os.path.exists(pdf_path), "no PDF file was written when the export was refused")
        finally:
            _records_tab_module.PDF_EXPORT_ROW_LIMIT = original_pdf_limit

        # === 6. Real hit-file page navigation + ON-SCREEN-page-scoped export,
        # against an ACTUALLY migrated (paged) pattern -- floor 5's k=2/v=1,
        # hit_paging page_size=60, 130 values -> hit-file pages [60,60,10]. Each
        # hit-file page is bigger than the UI's own page_size (50, set via
        # prime_atlas_v1.PAGE_SIZE above) so it spans multiple on-screen pages --
        # needed to prove that "export pages from/to" scopes to ON-SCREEN pages,
        # not the much coarser hit-file page a single "page" used to mean. ===
        floor5_dir = os.path.join(tmp_portal, "10p5", "constellations", f"k{k}", f"variant{vid}")
        os.makedirs(floor5_dir, exist_ok=True)
        paged_values = [5000 + 2 * i for i in range(1, 131)]  # 130 values
        paged_source = os.path.join(floor5_dir, f"HITS_10p5_k{k}_v{vid}.bin")
        prime_sieve_v1.write_prime_window(paged_source, paged_values)
        hit_paging.migrate_hit_file_to_pages(paged_source, floor5_dir, 5, k, vid, page_size=60)

        records.floor_from_entry.delete(0, "end")
        records.floor_to_entry.delete(0, "end")
        records._on_scan_clicked()
        _pump(app, 3.0)
        app.update()
        tree_rows3 = records.tree.get_children("")
        check("5" in tree_rows3, f"records tree now also includes floor 5 (got {tree_rows3})")
        records.tree.see("5")
        app.update()
        bbox5 = records.tree.bbox("5", f"v{vid}")
        check(bool(bbox5), f"floor 5's v={vid} cell has real on-screen geometry (got bbox={bbox5})")
        if bbox5:
            x, y, w, h = bbox5
            records._on_cell_activate(_FakeEvent(x + w // 2, y + h // 2))
            check(records._detail_file_page_count == 3,
                  f"drill-down sees the real hit-file page count for a migrated pattern (got {records._detail_file_page_count})")
            check(records._detail_file_page_index == 0, "drill-down starts on hit-file page 0 (1 in the UI)")
            check([v for v, _off in records._detail_rows] == paged_values[0:60],
                  f"hit-file page 0's rows are exactly that page's 60 values (got {len(records._detail_rows)} rows)")
            check(str(records.detail_file_prev_btn["state"]) == "disabled",
                  "prev file-page button is disabled on the first hit-file page")
            check(str(records.detail_file_next_btn["state"]) == "normal",
                  "next file-page button is enabled when more hit-file pages exist")

            records._next_detail_file_page()
            check(records._detail_file_page_index == 1, "next file-page button advances to hit-file page 1")
            check([v for v, _off in records._detail_rows] == paged_values[60:120],
                  f"hit-file page 1's rows are exactly that page's 60 values (got {len(records._detail_rows)} rows)")

            records._prev_detail_file_page()
            check(records._detail_file_page_index == 0, "prev file-page button returns to hit-file page 0")

            # On-screen page export: request 1-based screen page 1 (0-based UI page 0)
            # of the CURRENTLY LOADED hit-file page -- should pull exactly the first
            # 50 (self._page_size) values, NOT the whole 60-row hit-file page.
            from tkinter import filedialog
            original_asksaveasfilename = filedialog.asksaveasfilename
            range_csv_path = os.path.join(tmp_portal, "range_export_test.csv")
            filedialog.asksaveasfilename = lambda **kwargs: range_csv_path
            try:
                records.detail_export_from_entry.delete(0, "end")
                records.detail_export_from_entry.insert(0, "1")
                records.detail_export_to_entry.delete(0, "end")
                records.detail_export_to_entry.insert(0, "1")
                records._export_csv()  # unified: od/do filled + a pattern active -> on-screen-page mode
                check(records._busy, "on-screen-page export dispatches a background job (busy set)")
                _pump(app, 3.0)
                check(not records._busy, "on-screen-page export job settles")
            finally:
                filedialog.asksaveasfilename = original_asksaveasfilename

            check(os.path.exists(range_csv_path), "on-screen-page export actually wrote a CSV file")
            with open(range_csv_path, encoding="utf-8") as f:
                range_lines = f.read().strip().splitlines()
            exported_rows = [line.split(",") for line in range_lines[1:]]
            exported_numbers = [int(r[3]) for r in exported_rows]
            check(exported_numbers == paged_values[0:50],
                  f"screen page [1,1] pulls exactly the first 50 values of hit-file page 0, "
                  f"NOT the whole 60-row hit-file page (got {len(exported_numbers)} rows)")
            exported_positions = [int(r[4]) for r in exported_rows]
            check(exported_positions == list(range(0, 50)),
                  f"position_in_file is correct for hit-file page 0 (got {exported_positions[:5]}...)")

            # Screen page 2 of the SAME hit-file page -> the remaining 10 rows, not
            # the next hit-file page's data.
            filedialog.asksaveasfilename = lambda **kwargs: range_csv_path
            try:
                records.detail_export_from_entry.delete(0, "end")
                records.detail_export_from_entry.insert(0, "2")
                records.detail_export_to_entry.delete(0, "end")
                records.detail_export_to_entry.insert(0, "2")
                records._export_csv()
                _pump(app, 3.0)
            finally:
                filedialog.asksaveasfilename = original_asksaveasfilename
            with open(range_csv_path, encoding="utf-8") as f:
                range_lines2 = f.read().strip().splitlines()
            exported_numbers2 = [int(line.split(",")[3]) for line in range_lines2[1:]]
            check(exported_numbers2 == paged_values[50:60],
                  f"screen page [2,2] pulls exactly the remaining 10 rows of hit-file page 0 "
                  f"(got {exported_numbers2})")

            # Same screen-page-1 range, but "Eksportuj PDF" instead -- exercises the
            # export_page_range_pdf mode (new, alongside export_page_range_csv above).
            records.detail_export_from_entry.delete(0, "end")
            records.detail_export_from_entry.insert(0, "1")
            records.detail_export_to_entry.delete(0, "end")
            records.detail_export_to_entry.insert(0, "1")
            range_pdf_path = os.path.join(tmp_portal, "range_export_test.pdf")
            filedialog.asksaveasfilename = lambda **kwargs: range_pdf_path
            try:
                records._export_pdf()
                check("PDF" in records.status.get() and "CSV" not in records.status.get(),
                      f"the status bar says PDF, not CSV, while an on-screen-page PDF export runs "
                      f"(got {records.status.get()!r})")
                _pump(app, 3.0)
            finally:
                filedialog.asksaveasfilename = original_asksaveasfilename
            check(os.path.exists(range_pdf_path), "on-screen-page export_pdf actually wrote a PDF file")
            check(os.path.getsize(range_pdf_path) > 0, "the on-screen-page PDF is non-empty")

        # === 7. Same real hit-file page navigation + jump-to-export, in the
        # Magazyn (ConstellationsHitsTab) tab -- reuses floor 5's already-migrated
        # k=2/v=1 pattern from section 6 above (3 hit-file pages [60,60,10]). ===
        hits._reload_constellations_tree()
        _pump(app, 3.0)
        app.update()
        floor_nodes = hits.hits_tree.get_children("")
        floor5_node = next(
            (n for n in floor_nodes if hits.hits_tree.item(n, "text") == "10p5"), None)
        check(floor5_node is not None, f"Magazyn tree now shows floor 5 (got {floor_nodes})")
        if floor5_node is not None:
            hits.hits_tree.focus(floor5_node)
            hits._populate_floor_node(floor5_node)
            k5_nodes = hits.hits_tree.get_children(floor5_node)
            v5_node = hits.hits_tree.get_children(k5_nodes[0])[0]
            hits.hits_tree.selection_set(v5_node)
            hits.hits_tree.focus(v5_node)
            hits._on_tree_select(None)

            hits.load_preview()
            check(hits._hit_file_page_count == 3,
                  f"Magazyn load_preview() sees the real hit-file page count (got {hits._hit_file_page_count})")
            check(hits._hit_values == paged_values[0:60],
                  f"Magazyn hit-file page 0's values match exactly (got {len(hits._hit_values)} values)")
            check(str(hits.hits_file_prev_btn["state"]) == "disabled",
                  "Magazyn prev file-page button is disabled on the first page")
            check(str(hits.hits_file_next_btn["state"]) == "normal",
                  "Magazyn next file-page button is enabled when more pages exist")

            hits._next_hit_file_page()
            check(hits._hit_file_page_index == 1, "Magazyn next file-page button advances to hit-file page 1")
            check(hits._hit_values == paged_values[60:120],
                  f"Magazyn hit-file page 1's values match exactly (got {len(hits._hit_values)} values)")

            hits._prev_hit_file_page()
            check(hits._hit_file_page_index == 0, "Magazyn prev file-page button returns to hit-file page 0")
            check(str(hits.hits_export_btn["state"]) == "normal",
                  "Magazyn's Eksportuj button is enabled once a page is loaded")

            # The Magazyn export button no longer exports locally (that duplicated
            # Tabela rekordow's own export) -- it jumps there instead, with THIS
            # pattern + the currently-loaded hit-file page pre-selected.
            hits._next_hit_file_page()  # move off page 0 first, so the jump target
            check(hits._hit_file_page_index == 1, "moved to hit-file page 1 before jumping")

            # Deliberately DIRTY every field the jump is supposed to set, to REAL bogus
            # values first -- a jump that silently no-ops (leaving the from/to and k
            # fields unset) would leave these wrong values sitting there instead of
            # failing loudly, so a test that never dirtied them first couldn't have
            # caught that.
            records.k_combo.set("99")
            records.detail_export_from_entry.delete(0, "end")
            records.detail_export_from_entry.insert(0, "777")
            records.detail_export_to_entry.delete(0, "end")
            records.detail_export_to_entry.insert(0, "888")
            records.floor_from_entry.delete(0, "end")
            records.floor_from_entry.insert(0, "111")
            records.floor_to_entry.delete(0, "end")
            records.floor_to_entry.insert(0, "222")

            hits._export_current_page()
            app.update()
            check(app.constellations_sub_notebook.index(app.constellations_sub_notebook.select())
                  == app.constellations_sub_notebook.index(app.constellations_records_tab),
                  "Magazyn's Eksportuj button switches to the Tabela rekordow sub-tab")
            check(records._detail_context is not None
                  and records._detail_context["base_exponent"] == 5
                  and records._detail_context["pattern"]["k"] == k
                  and records._detail_context["pattern"]["id"] == vid,
                  f"the jump activates the exact same pattern Magazyn was showing (got {records._detail_context})")
            check(records.k_combo.get() == str(k),
                  f"the jump overwrites k_combo's dirty bogus value with the real k "
                  f"(got {records.k_combo.get()!r}, expected {str(k)!r})")
            check(records.floor_from_entry.get() == "5" and records.floor_to_entry.get() == "5",
                  f"the jump overwrites Pietro od/do's dirty bogus values with the real floor "
                  f"(got {records.floor_from_entry.get()!r}/{records.floor_to_entry.get()!r})")
            check(records._detail_file_page_index == 1,
                  f"the jump preloads the SAME hit-file page Magazyn was showing (got {records._detail_file_page_index})")
            check(records.detail_export_from_entry.get() == "1" and records.detail_export_to_entry.get() == "1",
                  f"the jump pre-fills the on-screen od/do to screen page 1 (the on-screen pager "
                  f"always resets to page 0 on a fresh load, regardless of which hit-file page) "
                  f"(got {records.detail_export_from_entry.get()!r}/{records.detail_export_to_entry.get()!r})")
            check([v for v, _off in records._detail_rows] == paged_values[60:120],
                  f"the preloaded hit-file page's rows match exactly what Magazyn had shown "
                  f"(got {len(records._detail_rows)} rows)")

            # od/do already default to screen page 1 of THIS hit-file page after the
            # jump -- confirm the now-unified _export_csv() exports exactly that (the
            # first self._page_size=50 of hit-file page 1's own 60 rows), not the
            # whole hit-file page and not hit-file page 0's data.
            from tkinter import filedialog as _fd2
            original_asksaveasfilename2 = _fd2.asksaveasfilename
            hits_range_csv_path = os.path.join(tmp_portal, "hits_range_export_test.csv")
            _fd2.asksaveasfilename = lambda **kwargs: hits_range_csv_path
            try:
                records._export_csv()
                _pump(app, 3.0)
            finally:
                _fd2.asksaveasfilename = original_asksaveasfilename2

            check(os.path.exists(hits_range_csv_path),
                  "exporting after a Magazyn-jump actually wrote a CSV file")
            with open(hits_range_csv_path, encoding="utf-8") as f:
                hits_range_lines = f.read().strip().splitlines()
            hits_exported_numbers = [int(line.split(",")[3]) for line in hits_range_lines[1:]]
            check(hits_exported_numbers == paged_values[60:110],
                  f"the jump's default screen-page-1 export pulls exactly the first 50 of "
                  f"hit-file page 1's own 60 rows (got {len(hits_exported_numbers)} rows)")

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
