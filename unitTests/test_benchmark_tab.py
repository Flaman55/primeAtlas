"""
test_benchmark_tab.py -- functional regression test for BenchmarkTab (primeatlas/
benchmark_tab.py + primeatlas/benchmark.py), extracted from prime_atlas_v1.py during
the refactor branch's Faza 3 (tab-by-tab backend/UI split, 2026-08-23; task #382-385).
The Benchmark tab was the smallest of the five tabs still living directly in
prime_atlas_v1.py, so it was the first one migrated to the SettingsTab-style
BenchmarkTab(ttk.Frame) + primeatlas/benchmark.py pure-logic split.

This test builds the real PortalBrowserApp() end to end (not a mock) against a real
on-disk portal folder seeded with a hand-written benchmark_log.csv, then exercises the
resulting app.benchmark_tab_widget (the real BenchmarkTab instance) directly:
  1. reload_benchmark_log() actually reads the seeded CSV and populates the growth-chart
     points, the sieve/write phase-chart points, and the floor tree.
  2. Pagination: a floor with 250 rows (> BENCHMARK_PAGE_SIZE=200) gets a real second
     page -- expand/populate the node the same way <<TreeviewOpen>> would, then drive
     Next/Prev/goto exactly like the on-screen buttons do.
  3. PDF export: bypasses the real filedialog.asksaveasfilename() dialog (like every
     other export test in this folder -- see test_const_records_worker.py's own module
     docstring) by monkeypatching it to return a fixed path, then checks the file is
     actually written and a confirmation is shown.
  4. The "no data yet" and forced-exception paths surface the right dialogs instead of
     silently doing nothing / crashing.
  5. Dark-theme fix (#407, 2026-08-26): the "pietro"/"stat" Treeview row tags pull their
     background AND foreground from primeatlas.theme.palette_for(), and both chart
     canvases' own background do too -- not hardcoded light colors regardless of theme.
  6. Chart readability fix (#408, 2026-08-26): _draw_growth_chart's dynamic pad_left
     stops wide numbers ("71,556,448") from clipping off the canvas edge -- exercised
     directly against _draw_growth_chart with a synthetic canvas, not through the CSV
     fixture above (which doesn't need such large numbers to be realistic). The
     always-on per-point labels were also replaced by a single hover tooltip; its
     "which point is the cursor over" decision lives in the plain, tkinter-free
     _nearest_hover_point() function (extracted specifically so this is testable
     without a real OS-level mouse event, which behaved inconsistently across
     platforms -- see that check's own comment below for the full story).

See test_loading_screen.py's own module docstring for why PORTAL_FOLDER must be
redirected BEFORE constructing the app (the constructor's own startup call --
self.benchmark_tab_widget.reload_benchmark_log() -- reads the module global at
construction time, same as the tree scans), and test_search_worker.py's for why
AppSettings.save() must be neutered first.

Usage (Windows, real display):
    python unitTests\\test_benchmark_tab.py

Usage (this sandbox, headless):
    PYTHONPATH="/tmp/tkextract/usr/lib/python3.10:/tmp/tkextract/usr/lib/python3.10/lib-dynload:$PYTHONPATH" \\
    LD_LIBRARY_PATH="/tmp/tkextract/usr/lib:$LD_LIBRARY_PATH" \\
    xvfb-run -a python3 unitTests/test_benchmark_tab.py
"""
import csv
import os
import shutil
import sys
import tempfile
import time
import tkinter as tk
import tkinter.messagebox
from tkinter import filedialog

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)

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


# Same canonical column set as primeatlas/floor_meta.py's CANONICAL_BENCHMARK_FIELDNAMES
# -- a realistic superset across every generator engine this project has had, so the
# seeded CSV exercises every aggregate_benchmark_*()/benchmark_row_stats() column at
# once instead of a stripped-down fixture that would miss a column-name typo.
_FIELDNAMES = [
    "run_timestamp_utc", "base_exponent", "target_idx_start", "target_idx_end",
    "windows_written", "total_seconds", "seconds_per_window", "total_primes",
    "avg_primes_per_window", "primes_per_second",
    "l_final", "sieving_primes_count", "max_child_rss_mb",
    "base_gen_seconds", "sieve_seconds", "write_seconds", "bytes_written",
    "instance_of_n", "loop_session_seconds", "loop_numbers_per_second",
    "loop_seconds_per_window", "write_files",
]


def _row(base_exponent, idx, **overrides):
    row = {
        "run_timestamp_utc": f"2026-08-23T00:{idx:02d}:00Z",
        "base_exponent": base_exponent,
        "target_idx_start": idx * 10,
        "target_idx_end": idx * 10 + 10,
        "windows_written": 10,
        "total_seconds": 5.0,
        "seconds_per_window": 0.5,
        "total_primes": 100,
        "avg_primes_per_window": 10,
        "primes_per_second": 2000,
        "l_final": 1000,
        "sieving_primes_count": 50,
        "max_child_rss_mb": 128,
        "base_gen_seconds": 1.0,
        "sieve_seconds": 2.0,
        "write_seconds": 1.0,
        "bytes_written": 1_000_000,
        "instance_of_n": "1/1",
        "loop_session_seconds": 5.0,
        "loop_numbers_per_second": 1_000_000 + idx,
        "loop_seconds_per_window": 0.5,
        "write_files": True,
    }
    row.update(overrides)
    return row


def _write_benchmark_log(path, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main():
    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_benchmark_tab_test_")
    try:
        rows = []
        # Floor 10p0: 3 runs -- exercises "last row wins" in aggregate_benchmark_growth/
        # aggregate_benchmark_fair_spw/aggregate_benchmark_sieve_nps/
        # aggregate_benchmark_write_mbps, and benchmark_row_stats' avg/min/max.
        for i in range(3):
            rows.append(_row(0, i, seconds_per_window=0.4 + i * 0.1))
        # Floor 10p3: 250 runs -- exercises pagination (BENCHMARK_PAGE_SIZE=200, so this
        # floor spans exactly 2 pages).
        for i in range(250):
            rows.append(_row(3, i))
        benchmark_log_path = os.path.join(tmp_portal, "benchmark_log.csv")
        _write_benchmark_log(benchmark_log_path, rows)

        shown = _patch_messageboxes()

        sys.argv = ["prime_atlas_v1.py"]
        import prime_atlas_v1

        # Redirect PORTAL_FOLDER BEFORE constructing the app -- __init__'s own startup
        # call to self.benchmark_tab_widget.reload_benchmark_log() reads the module
        # global via the get_portal_folder=lambda: PORTAL_FOLDER closure captured at
        # _build_benchmark_tab() call time (see that method's own docstring), so
        # redirecting only AFTER construction would miss the very first load.
        _patch_app_settings(prime_atlas_v1.APP_SETTINGS)
        prime_atlas_v1.APP_SETTINGS.set_storage_path(tmp_portal)
        prime_atlas_v1.PORTAL_FOLDER = tmp_portal

        app_cls = prime_atlas_v1._build_gui()
        app = app_cls()
        _pump(app, 5.0)

        widget = app.benchmark_tab_widget

        # --- reload_benchmark_log() actually read the seeded CSV -------------------
        check(bool(widget._benchmark_rows), "startup reload populated _benchmark_rows "
              f"(got {len(widget._benchmark_rows)} rows)")
        check(len(widget._benchmark_rows) == len(rows),
              f"every seeded row made it in (expected {len(rows)}, got "
              f"{len(widget._benchmark_rows)})")
        check(0 in widget._benchmark_rows_by_pietro and 3 in widget._benchmark_rows_by_pietro,
              f"both seeded floors are grouped (got keys {sorted(widget._benchmark_rows_by_pietro)})")
        check(len(widget._benchmark_rows_by_pietro[3]) == 250,
              f"floor 10p3 kept all 250 rows (got {len(widget._benchmark_rows_by_pietro[3])})")

        growth = dict(widget._benchmark_growth_points)
        check(growth.get(0) == 1_000_000 + 2,
              f"growth chart uses the LAST row for floor 10p0, not an average or the "
              f"first row (got {growth.get(0)!r}, expected {1_000_000 + 2})")

        fair_spw = dict(widget._benchmark_fair_spw_points)
        check(0 in fair_spw, "secondary (fair s/window) series populated for floor 10p0")

        sieve_nps = dict(widget._benchmark_sieve_nps_points)
        write_mbps = dict(widget._benchmark_write_mbps_points)
        check(0 in sieve_nps and 0 in write_mbps,
              "sieve-nps/write-mbps phase series populated (v4.1-style rows in the fixture)")

        # --- explicit re-reload (Refresh button path) is also safe to call again ---
        widget.reload_benchmark_log()
        check(len(widget._benchmark_rows) == len(rows),
              "a second reload_benchmark_log() call re-reads cleanly, no duplication "
              f"(got {len(widget._benchmark_rows)} rows)")

        # --- floor tree actually has both floor nodes ------------------------------
        top_nodes = widget.benchmark_tree.get_children("")
        check(len(top_nodes) == 2,
              f"benchmark_tree has exactly 2 top-level floor nodes (got {len(top_nodes)})")
        node_for_floor3 = None
        for node in top_nodes:
            text = widget.benchmark_tree.item(node, "text")
            if text.startswith("10p3"):
                node_for_floor3 = node
        check(node_for_floor3 is not None, "a floor node whose label starts with '10p3' exists")

        # --- pagination: expand floor 10p3 (250 rows -> 2 pages of 200) -------------
        widget._populate_benchmark_pietro_node(node_for_floor3)
        widget._set_active_benchmark_node(node_for_floor3)
        state = widget._benchmark_pietro_state[node_for_floor3]
        check(state["total_pages"] == 2,
              f"250 rows at BENCHMARK_PAGE_SIZE=200 gives exactly 2 pages (got {state['total_pages']})")
        check(state["page"] == 0, f"floor starts on page 0 (got {state['page']})")
        check(str(widget.benchmark_prev_btn["state"]) == "disabled",
              "Prev is disabled on page 1/2")
        check(str(widget.benchmark_next_btn["state"]) == "normal",
              "Next is enabled on page 1/2 (a second page exists)")
        # Page 0 shows 1 stats row + 200 data rows.
        page0_children = widget.benchmark_tree.get_children(node_for_floor3)
        check(len(page0_children) == 201,
              f"page 0 shows the stats row plus 200 data rows (got {len(page0_children)})")

        widget._next_benchmark_page()
        check(state["page"] == 1, f"_next_benchmark_page() advanced to page 1 (got {state['page']})")
        check(str(widget.benchmark_next_btn["state"]) == "disabled",
              "Next is disabled on the last page")
        check(str(widget.benchmark_prev_btn["state"]) == "normal",
              "Prev is enabled once off page 1/2")
        page1_children = widget.benchmark_tree.get_children(node_for_floor3)
        check(len(page1_children) == 51,
              f"page 1 (the remainder) shows the stats row plus 50 data rows "
              f"(got {len(page1_children)})")

        widget._prev_benchmark_page()
        check(state["page"] == 0, f"_prev_benchmark_page() went back to page 0 (got {state['page']})")

        widget.benchmark_goto_entry.delete(0, "end")
        widget.benchmark_goto_entry.insert(0, "2")
        widget._goto_benchmark_page()
        check(state["page"] == 1, f"_goto_benchmark_page('2') landed on page index 1 (got {state['page']})")

        # Collapsing drops the cached page state, same lifecycle as the primes tab.
        # _on_benchmark_tree_close() reads the currently-focused item rather than taking
        # one as an argument (it's bound to the real <<TreeviewClose>> event), so focus()
        # is set explicitly first to drive it the same way a real collapse click would.
        widget.benchmark_tree.focus(node_for_floor3)
        widget._on_benchmark_tree_close(None)
        check(node_for_floor3 not in widget._benchmark_pietro_state,
              "closing the floor node drops its cached page state")

        # --- PDF export: bypass the real file dialog, like the other export tests --
        pdf_path = os.path.join(tmp_portal, "benchmark_report_test.pdf")
        original_dialog = filedialog.asksaveasfilename
        filedialog.asksaveasfilename = lambda **kwargs: pdf_path
        shown.clear()
        widget._export_benchmark_pdf()
        filedialog.asksaveasfilename = original_dialog
        check(os.path.exists(pdf_path), "_export_benchmark_pdf() actually wrote the PDF file")
        check(os.path.getsize(pdf_path) > 0, "the written PDF is non-empty")
        check(any(kind == "info" for kind, _a, _k in shown),
              f"a 'saved' confirmation was shown via messagebox.showinfo (got: {shown})")

        # --- PDF export: "no data" path never opens the file dialog at all ---------
        real_rows, real_fieldnames = widget._benchmark_rows, widget._benchmark_fieldnames
        widget._benchmark_rows, widget._benchmark_fieldnames = [], []
        shown.clear()

        def _dialog_should_not_be_called(**kwargs):
            raise AssertionError("filedialog.asksaveasfilename was called with no data present")

        filedialog.asksaveasfilename = _dialog_should_not_be_called
        widget._export_benchmark_pdf()
        filedialog.asksaveasfilename = original_dialog
        widget._benchmark_rows, widget._benchmark_fieldnames = real_rows, real_fieldnames
        check(any(kind == "info" for kind, _a, _k in shown),
              f"the 'no data yet' dialog was shown instead of opening a file dialog (got: {shown})")

        # --- PDF export: a raising renderer surfaces messagebox.showerror ----------
        import primeatlas.benchmark_tab as benchmark_tab_module
        original_render = benchmark_tab_module.render_benchmark_pdf

        def _fake_raise(*a, **k):
            raise RuntimeError("fake failure for this test")

        benchmark_tab_module.render_benchmark_pdf = _fake_raise
        filedialog.asksaveasfilename = lambda **kwargs: pdf_path
        shown.clear()
        widget._export_benchmark_pdf()
        filedialog.asksaveasfilename = original_dialog
        benchmark_tab_module.render_benchmark_pdf = original_render
        check(any(kind == "error" for kind, _a, _k in shown),
              f"a raising render_benchmark_pdf() surfaces messagebox.showerror "
              f"(got: {shown})")
        check(any("fake failure for this test" in str(call) for call in shown),
              f"the actual exception text reaches the error dialog (got: {shown})")

        # --- dark-theme fix: tree tag colors follow the palette, not hardcoded (#407) --
        # "pietro"/"stat" row tags used to be hardcoded to light colors with no matching
        # foreground override -- unreadable under the dark theme. See BenchmarkTab.
        # __init__'s own docstring and primeatlas/theme.py's tree_group_bg/tree_stat_bg
        # docstring for the bug this fixes.
        from primeatlas.theme import palette_for
        theme_palette = palette_for(prime_atlas_v1.APP_SETTINGS.theme)
        # str(...) -- tag_configure's single-option query form can hand back a Tcl
        # color/font object rather than a plain str depending on the Tcl/Tk version
        # (same reason every OTHER tk-value comparison in this file already goes
        # through str(), e.g. the button-state checks above), so compare string forms
        # rather than the raw query result.
        pietro_bg = str(widget.benchmark_tree.tag_configure("pietro", "background"))
        pietro_fg = str(widget.benchmark_tree.tag_configure("pietro", "foreground"))
        stat_bg = str(widget.benchmark_tree.tag_configure("stat", "background"))
        stat_fg = str(widget.benchmark_tree.tag_configure("stat", "foreground"))
        check(pietro_bg == theme_palette["tree_group_bg"],
              f"'pietro' row tag background comes from the theme palette, not a hardcoded "
              f"color (got {pietro_bg!r}, expected {theme_palette['tree_group_bg']!r})")
        check(pietro_fg == theme_palette["fg"],
              f"'pietro' row tag foreground comes from the theme palette "
              f"(got {pietro_fg!r}, expected {theme_palette['fg']!r})")
        check(stat_bg == theme_palette["tree_stat_bg"],
              f"'stat' row tag background comes from the theme palette "
              f"(got {stat_bg!r}, expected {theme_palette['tree_stat_bg']!r})")
        check(stat_fg == theme_palette["fg"],
              f"'stat' row tag foreground comes from the theme palette "
              f"(got {stat_fg!r}, expected {theme_palette['fg']!r})")

        # --- dark-theme fix: chart canvas background follows the palette too (#408) ----
        chart_bg = widget.benchmark_chart.cget("background")
        chart2_bg = widget.benchmark_chart2.cget("background")
        check(chart_bg == theme_palette["console_bg"],
              f"growth-chart canvas background comes from the theme palette "
              f"(got {chart_bg!r}, expected {theme_palette['console_bg']!r})")
        check(chart2_bg == theme_palette["console_bg"],
              f"phase-chart canvas background comes from the theme palette "
              f"(got {chart2_bg!r}, expected {theme_palette['console_bg']!r})")

        # --- chart readability fix: dynamic left padding stops big numbers clipping ----
        # (#408, 2026-08-26 screenshot) -- a 9-11 digit n/s figure like "71,556,448" used
        # to sit under a fixed 70px pad_left and get cut off against the canvas edge.
        # _draw_growth_chart now measures the actual tick label strings with the real
        # font and widens pad_left to fit -- reproduce that exact scenario directly
        # (no need to go through the whole app/CSV path) and check no tick-label text
        # item is left with a negative left edge (i.e. clipped off-canvas).
        from primeatlas.benchmark_tab import _draw_growth_chart
        probe_canvas = tk.Canvas(app, width=900, height=220)
        probe_canvas.pack()
        app.update()
        big_points = [(0, 71_556_448), (5, 14_405_937), (10, 999_999_999)]
        _draw_growth_chart(probe_canvas, big_points, 900, 220, translator=widget.T)
        min_left_edge = None
        for item_id in probe_canvas.find_all():
            if probe_canvas.type(item_id) == "text":
                bbox = probe_canvas.bbox(item_id)
                if bbox is not None:
                    min_left_edge = bbox[0] if min_left_edge is None else min(min_left_edge, bbox[0])
        check(min_left_edge is not None, "the probe chart actually drew some tick-label text")
        check(min_left_edge >= -1,
              f"no tick-label text is clipped off the left edge of the canvas "
              f"(leftmost text bbox edge was {min_left_edge}, expected >= -1)")

        # --- chart readability fix: hover tooltip replaces always-on point labels ------
        # (#408) -- per-point value labels used to be drawn permanently next to every dot
        # and overlapped into an unreadable smear on dense series; now nothing is shown
        # until the mouse is near a point, then exactly one tooltip (tagged "hover_tip")
        # appears. Reuses the probe_canvas/big_points draw from the padding check above,
        # so hover_points (closed over by _bind_chart_hover) matches what's on screen.
        check(len(probe_canvas.find_withtag("hover_tip")) == 0,
              "no hover tooltip is shown before the mouse moves near any point")
        # The "which point (if any) is the cursor over" decision is tested directly
        # via _nearest_hover_point -- a plain function with no canvas/tkinter
        # dependency (extracted from _bind_chart_hover's own <Motion> handler
        # specifically so this is possible) -- rather than through a real OS-level
        # synthetic mouse event. A synthetic <Motion>/<Leave> pair turned out to
        # behave inconsistently across platforms during testing (2026-08-26): on one
        # Windows/Tk combination, <Motion> didn't reliably land within the trigger
        # radius even when targeted at a dot's exact pixel center, and <Leave>
        # rejected the -warp option outright. _nearest_hover_point is deterministic
        # and needs no live display, so it tests the actual logic bug reports were
        # about (dense/overlapping labels) without inheriting that platform noise.
        from primeatlas.benchmark_tab import _nearest_hover_point
        dot_center = None
        for item_id in probe_canvas.find_all():
            if probe_canvas.type(item_id) == "oval":
                bbox = probe_canvas.bbox(item_id)
                if bbox is not None:
                    dot_center = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
                    break
        check(dot_center is not None, "the probe chart actually drew at least one point dot")
        hit = _nearest_hover_point([], dot_center[0], dot_center[1])
        check(hit is None, "an empty hover_points list never matches (no crash, no false hit)")
        far_away = _nearest_hover_point(
            [(dot_center[0], dot_center[1], 0, 0, "{}", "#000000", "k")],
            dot_center[0] + 1000, dot_center[1] + 1000)
        check(far_away is None,
              "a cursor position far from every point's dot matches nothing "
              "(the ~14px trigger radius is respected)")
        exact_hit = _nearest_hover_point(
            [(dot_center[0], dot_center[1], 42, 1234, "{}", "#1c5fa8", "k")],
            dot_center[0], dot_center[1])
        check(exact_hit is not None and exact_hit[2] == 42 and exact_hit[3] == 1234,
              f"a cursor position exactly on a dot matches that dot's own x_val/y_val "
              f"(got {exact_hit!r})")
        probe_canvas.destroy()

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
