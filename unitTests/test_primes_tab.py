"""
test_primes_tab.py -- functional regression test for PrimesTab (primeatlas/
primes_tab.py + primeatlas/core/storage.py), extracted from prime_atlas_v2.py as part of
the tab-by-tab backend/UI split. This was the second tab extracted after Benchmark,
and the first one where the search
machinery had to stay app-level (see primes_tab.py's own module docstring) -- so this
test exercises BOTH the tab's self-contained floor/preview UI AND the injected-callable
seam into prime_atlas_v2.py's shared search worker.

Builds the real PortalBrowserApp() end to end against a real on-disk portal folder
seeded with real PGS1 prime windows, then exercises app.primes_tab_widget (the real
PrimesTab instance) directly:
  1. reload_primes_tree()/populate_floors() actually scanned the seeded floors and
     built one tree row per floor.
  2. Floor pagination: a floor with more source files than FLOOR_PAGE_SIZE gets a real
     second (and third) page -- expand the node the same way <<TreeviewOpen>> would,
     then drive Next/Prev/goto exactly like the on-screen buttons do. FLOOR_PAGE_SIZE
     and PAGE_SIZE are both monkeypatched down to small values BEFORE the app is built
     so this doesn't require seeding hundreds of real files (see the PORTAL_FOLDER
     redirection precedent in test_benchmark_tab.py's own module docstring for why this
     must happen before construction).
  3. Selecting a file row loads its header into the detail pane and enables "Load
     preview"; loading actually decodes the file and paginates the prime list.
  4. The search box (search_entry + search_button, not just _start_search_job() as
     test_search_worker.py already exercises at the worker level) round-trips through
     PrimesTab's injected start_search_job callable into the real app-level search
     worker and back into on_prime_search_result(), landing the found prime in the
     preview pane.
  5. Tree columns: "generated" is last and shown only while an open floor lists files;
     column widths fit their content; the tree pane is pinned to the content width
     (resizes, hidden-tab layout, sash drags snap back), with a horizontal
     scrollbar only while the window is too narrow for it.

Usage (Windows, real display):
    python unitTests\\test_primes_tab.py

Usage (this sandbox, headless):
    PYTHONPATH="/tmp/tkextract/usr/lib/python3.10:/tmp/tkextract/usr/lib/python3.10/lib-dynload:$PYTHONPATH" \\
    LD_LIBRARY_PATH="/tmp/tkextract/usr/lib:$LD_LIBRARY_PATH" \\
    xvfb-run -a python3 unitTests/test_primes_tab.py
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
    tkinter.messagebox.askyesno = lambda *a, **k: False
    return shown


def _pump(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.update()
        time.sleep(0.02)


def _primes_upto(n):
    return [p for p in range(2, n) if all(p % d for d in range(2, int(p ** 0.5) + 1))]


def _test_cumulative_floor_totals():
    """Direct unit test of primeatlas.primes.primes_tab._cumulative_floor_totals -- a plain
    function with no tkinter dependency (mirrors the existing convention of testing
    such extracted pure functions directly, e.g. benchmark_tab.py's
    _nearest_hover_point/_hover_label_position) -- so this runs even without Xvfb/a
    real display.

    The count is INCLUSIVE ("how many primes in total through this floor"), following
    the app's own floor/file structure rather than Wikipedia's pi(10**N): excluding a
    floor's own count would put it off by one from its own cumulative row next to the
    "Primes" column -- see that function's own docstring."""
    from primeatlas.primes.primes_tab import _cumulative_floor_totals

    # Fully known, contiguous floors 0..3 -- each floor's OWN count folded in, so the
    # numbers land one row "later" than Wikipedia's pi(10**N) would (that's the point):
    # floor 0 (own=4) reads 4, floor 1 (own=21) reads 4+21=25, floor 2 (own=143) reads
    # 25+143=168, matching pi(10)=4, pi(100)=25, pi(1000)=168 respectively.
    known = {0: (4, 1, 100), 1: (21, 1, 100), 2: (143, 1, 100), 3: (1061, 1, 100)}
    result = _cumulative_floor_totals([0, 1, 2, 3], known)
    check(result == {0: 4, 1: 25, 2: 168, 3: 1229},
          f"contiguous fully-known floors give an inclusive running total, own count "
          f"included (got {result})")

    # A GAP IN THE FLOOR SEQUENCE ITSELF (0 and 3 exist on disk, 1/2 were never
    # generated at all) -- floor 3's cumulative can't be trusted (missing floors 1/2's
    # contribution entirely), so it must come back None, not a falsely-small number.
    result = _cumulative_floor_totals([0, 3], {0: (4, 1, 100), 3: (1061, 1, 100)})
    check(result == {0: 4, 3: None},
          f"a gap in the floor SEQUENCE (1/2 missing) poisons floor 3's cumulative "
          f"(got {result})")

    # A gap in KNOWN TOTALS (floor 1 exists on disk but its total hasn't been
    # (re-)computed yet) poisons its OWN cumulative too now (inclusive means floor 1's
    # cumulative needs floor 1's own count, unlike the earlier exclusive version).
    result = _cumulative_floor_totals([0, 1, 2], {0: (4, 1, 100), 2: (143, 1, 100)})
    check(result == {0: 4, 1: None, 2: None},
          f"an unknown TOTAL (floor 1's count not yet known) poisons floor 1's own "
          f"cumulative and every floor above it (got {result})")

    # Once poisoned, stays poisoned for every higher floor, even ones individually known.
    result = _cumulative_floor_totals(
        [0, 1, 2, 3], {0: (4, 1, 100), 2: (143, 1, 100), 3: (1061, 1, 100)})
    check(result == {0: 4, 1: None, 2: None, 3: None},
          f"a gap stays poisoned for every floor above it, even a later known one "
          f"(got {result})")

    check(_cumulative_floor_totals([], {}) == {},
          "an empty floor list returns an empty dict, no crash")


def main():
    _test_cumulative_floor_totals()

    import prime_sieve_v1
    import window_sharding

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_primes_tab_test_")
    try:
        # source_primes/ is sharded into shard_NNNNN subfolders (see window_sharding.py) --
        # every fixture window below is placed under shard_00000, which is
        # valid regardless of how many windows share it (SHARD_SIZE=5000 is just a cap).
        #
        # Floor 10p0: a single small window, seeded specifically so PAGE_SIZE=5 (see
        # below) splits its 10 primes into exactly 2 preview pages.
        floor0_dir = os.path.join(tmp_portal, "10p0", "source_primes")
        floor0_shard_dir = window_sharding.shard_dir(floor0_dir, 0)
        os.makedirs(floor0_shard_dir, exist_ok=True)
        floor0_primes = _primes_upto(30)  # 2,3,5,7,...,29 -> 10 primes
        check(len(floor0_primes) == 10, f"fixture sanity: 10 primes below 30 (got {len(floor0_primes)})")
        prime_sieve_v1.write_prime_window(
            os.path.join(floor0_shard_dir, "PRIME_WINDOW_0000000000.bin"), floor0_primes)

        # Floor 10p3: 7 separate window files -- with FLOOR_PAGE_SIZE monkeypatched to 3
        # below, this spans exactly 3 floor-nav pages (3+3+1).
        floor3_dir = os.path.join(tmp_portal, "10p3", "source_primes")
        floor3_shard_dir = window_sharding.shard_dir(floor3_dir, 0)
        os.makedirs(floor3_shard_dir, exist_ok=True)
        for i in range(7):
            start = 1000 + i * 100
            primes = [p for p in range(start, start + 100)
                      if p > 1 and all(p % d for d in range(2, int(p ** 0.5) + 1))]
            prime_sieve_v1.write_prime_window(
                os.path.join(floor3_shard_dir, f"PRIME_WINDOW_{start:010d}.bin"), primes)

        shown = _patch_messageboxes()

        sys.argv = ["prime_atlas_v2.py"]
        import prime_atlas_v2

        # Small page sizes so the fixture above (10 primes / 7 files) actually exercises
        # multi-page pagination without needing hundreds of real files on disk. Both
        # constants are read by PrimesTab.__init__ as plain values at _build_primes_tab()
        # call time (see that method's own docstring), so this MUST happen before the
        # app is constructed -- same reasoning as the PORTAL_FOLDER redirection below.
        prime_atlas_v2.PAGE_SIZE = 5
        prime_atlas_v2.FLOOR_PAGE_SIZE = 3

        _patch_app_settings(prime_atlas_v2.APP_SETTINGS)
        prime_atlas_v2.APP_SETTINGS.set_storage_path(tmp_portal)
        prime_atlas_v2.PORTAL_FOLDER = tmp_portal

        app_cls = prime_atlas_v2._build_gui()
        app = app_cls()
        _pump(app, 5.0)

        widget = app.primes_tab_widget

        # --- startup scan populated both floors -------------------------------------
        top_nodes = widget.tree.get_children("")
        check(len(top_nodes) == 2, f"tree has exactly 2 top-level floor nodes (got {len(top_nodes)})")
        node_by_text = {widget.tree.item(n, "text"): n for n in top_nodes}
        check("10p0" in node_by_text and "10p3" in node_by_text,
              f"both seeded floors show up by name (got {sorted(node_by_text)})")
        node0 = node_by_text["10p0"]
        node3 = node_by_text["10p3"]

        # --- cumulative running-total column ------------------------------------------
        # Startup no longer auto-triggers a real per-floor rescan
        # (compute_all_floor_totals()) -- see storage.py's own module docstring for the persisted-totals
        # feature: a fresh portal folder's .portal_totals_cache.json doesn't exist yet,
        # so floor_total_known is genuinely empty right after startup, and the
        # cumulative column is correctly blank for BOTH floors at this point (nothing
        # to assert here beyond that; asserted implicitly by the totals verify below
        # actually changing things). Explicitly invoking the manual verify-totals
        # button (widget._verify_all_totals, the manual safety-net verify that replaced
        # the old automatic behavior) is what makes floor 0's real total known.
        widget._verify_all_totals()
        _pump(app, 5.0)

        # Floor 0's cumulative is INCLUSIVE of its own count -- with nothing below it,
        # that's just its own 10 primes, once the manual verify above has actually
        # finished computing it (the second 5s pump waits for that). Floor 3's
        # cumulative can NEVER be shown here: floors 1 and 2 were never seeded/
        # generated at all (a real gap in the floor SEQUENCE, not just an unknown
        # total -- see _cumulative_floor_totals's own docstring), so it must stay
        # blank rather than silently showing floor0's count alone as if that were the
        # true running total through floor 3.
        check(widget.tree.set(node0, "cumulative") == "10",
              f"floor 10p0's cumulative column shows its own inclusive running total "
              f"(got {widget.tree.set(node0, 'cumulative')!r})")
        check(widget.tree.set(node3, "cumulative") == "",
              f"floor 10p3's cumulative column stays blank -- floors 1/2 are missing "
              f"entirely, not just unknown (got {widget.tree.set(node3, 'cumulative')!r})")

        # --- floor pagination: expand 10p3 (7 files / FLOOR_PAGE_SIZE=3 -> 3 pages) --
        widget.tree.focus(node3)
        widget._populate_floor_node(node3)
        widget._set_active_floor_node(node3)
        state = widget._floor_state[node3]
        check(state["total_pages"] == 3,
              f"7 files at FLOOR_PAGE_SIZE=3 gives exactly 3 pages (got {state['total_pages']})")
        check(state["page"] == 0, f"floor starts on page 0 (got {state['page']})")
        check(str(widget.floor_prev_btn["state"]) == "disabled", "Prev disabled on page 1/3")
        check(str(widget.floor_next_btn["state"]) == "normal", "Next enabled on page 1/3")
        check(len(widget.tree.get_children(node3)) == 3,
              f"page 0 shows exactly 3 file rows (got {len(widget.tree.get_children(node3))})")

        widget._next_floor_page()
        check(state["page"] == 1, f"_next_floor_page() advanced to page 1 (got {state['page']})")
        widget._next_floor_page()
        check(state["page"] == 2, f"_next_floor_page() advanced to page 2 (got {state['page']})")
        check(str(widget.floor_next_btn["state"]) == "disabled", "Next disabled on the last page")
        check(len(widget.tree.get_children(node3)) == 1,
              f"last page (remainder) shows exactly 1 file row (got {len(widget.tree.get_children(node3))})")

        widget.floor_goto_entry.delete(0, "end")
        widget.floor_goto_entry.insert(0, "1")
        widget._goto_floor_page()
        check(state["page"] == 0, f"_goto_floor_page('1') landed back on page index 0 (got {state['page']})")

        # Collapsing drops the cached page state.
        widget.tree.focus(node3)
        widget._on_tree_close(None)
        check(node3 not in widget._floor_state, "closing the floor node drops its cached page state")

        # --- selecting a file row + loading the preview -----------------------------
        widget.tree.item(node0, open=True)
        widget._populate_floor_node(node0)
        file_item = widget.tree.get_children(node0)[0]
        widget.tree.selection_set(file_item)
        widget.tree.focus(file_item)
        widget._on_tree_select(None)
        check(widget._preview_primes == floor0_primes,
              f"selecting a non-empty file row auto-loads its preview, no separate "
              f"'Load preview' click needed (got {widget._preview_primes})")
        check(widget._preview_total_pages == 2,
              f"10 primes at PAGE_SIZE=5 gives exactly 2 preview pages (got {widget._preview_total_pages})")
        check(str(widget.next_page_btn["state"]) == "normal", "preview Next enabled on page 1/2")
        widget._next_preview_page()
        check(widget._preview_page == 1, f"_next_preview_page() advanced to page 1 (got {widget._preview_page})")
        check(str(widget.next_page_btn["state"]) == "disabled", "preview Next disabled on the last page")

        # --- search box round-trips through the shared app-level search worker -----
        widget.search_entry.delete(0, "end")
        widget.search_entry.insert(0, str(floor0_primes[3]))
        widget.search_button.invoke()
        check(app._totals_search.search_busy, "clicking Search dispatches a job (search_busy set)")
        _pump(app, 3.0)
        check(not app._totals_search.search_busy, "search job settles after the worker result")
        check(str(floor0_primes[3]) in app.status.get(),
              f"status mentions the found prime (got: {app.status.get()!r})")
        check(widget._preview_primes == floor0_primes,
              "on_prime_search_result() loaded the right file's primes into the preview")

        # --- invalid input is rejected without touching the worker ------------------
        shown.clear()
        widget.search_entry.delete(0, "end")
        widget.search_entry.insert(0, "not-a-number")
        widget.search_button.invoke()
        check(not app._totals_search.search_busy, "an invalid search query never reaches the worker")
        check(any(kind == "error" for kind, _a, _k in shown),
              f"an invalid search query shows an error dialog instead (got: {shown})")

        _test_tree_columns(app, widget, node0, node3)

        app.destroy()
    finally:
        shutil.rmtree(tmp_portal, ignore_errors=True)


def _displayed(widget):
    return tuple(widget.tree.cget("displaycolumns"))


def _cell_texts(widget, column):
    items, stack = [], list(widget.tree.get_children(""))
    while stack:
        item = stack.pop()
        items.append(item)
        stack.extend(widget.tree.get_children(item))
    if column == "#0":
        return [widget.tree.item(i, "text") for i in items]
    return [widget.tree.set(i, column) for i in items]


def _test_tree_columns(app, widget, node0, node3):
    """5. Column layout: "generated" is the last column and is shown only while at least
    one open floor lists file rows; every displayed column is exactly wide enough for its
    heading and cells (no stretching); the tree pane is pinned to that content width."""
    import tkinter.font as tkfont
    print("\n--- 5. tree columns ---")
    base = ("count", "cumulative", "files", "size", "timer")
    for node in (node0, node3):
        if node in widget._floor_state:
            widget.tree.focus(node)
            widget._on_tree_close(None)
    check(_displayed(widget) == base,
          f"no floor open -> 'generated' hidden, timer last (got {_displayed(widget)})")

    widget.tree.item(node3, open=True)
    widget._populate_floor_node(node3)
    check(_displayed(widget) == base + ("generated",),
          f"an open floor shows 'generated' as the LAST column (got {_displayed(widget)})")
    widget.tree.item(node0, open=True)
    widget._populate_floor_node(node0)
    widget.tree.focus(node3)
    widget._on_tree_close(None)
    check(_displayed(widget) == base + ("generated",),
          "closing one floor while another stays open keeps 'generated'")
    widget.tree.focus(node0)
    widget._on_tree_close(None)
    check(_displayed(widget) == base, "closing the last open floor hides 'generated' again")

    widget._select_primes_file_in_tree(3, "PRIME_WINDOW_0000001000.bin")
    check(_displayed(widget) == base + ("generated",),
          "a search opening a floor programmatically shows 'generated'")

    # Widths fit content: never narrower than the heading or any cell, never padded
    # beyond the fit, and no column stretches to fill the pane.
    body = tkfont.nametofont("TkDefaultFont")
    heading = tkfont.nametofont("TkHeadingFont")
    for column in _displayed(widget):
        width = int(widget.tree.column(column, "width"))
        need = max([heading.measure(widget.tree.heading(column, "text"))] +
                   [body.measure(t) for t in _cell_texts(widget, column)])
        check(need < width <= need + 40,
              f"column {column!r} fits its content ({width}px for {need}px of text)")
        check(not widget.tree.column(column, "stretch"), f"column {column!r} does not stretch")
    width0 = int(widget.tree.column("#0", "width"))
    need0 = max(body.measure(t) for t in _cell_texts(widget, "#0"))
    check(need0 < width0, f"tree column fits the longest file name ({width0}px > {need0}px)")

    widget.tree.focus(node3)
    widget._on_tree_close(None)
    check(int(widget.tree.column("#0", "width")) < width0,
          "closing the floor shrinks the tree column back to the floor labels")

    # Tree pane follows the content until the user drags the sash -- checked on the
    # pane's on-screen width, which sashpos() alone can misreport.
    tree_pane = widget._tree_paned.panes()[0]

    def pane_fits(label):
        need = widget._tree_content_width()
        actual = app.nametowidget(tree_pane).winfo_width()
        check(abs(actual - need) <= 12,
              f"{label}: tree pane is as wide as its content ({actual}px, content {need}px)")

    app.geometry("1600x700")
    _pump(app, 1.0)
    pane_fits("after a window resize")
    widget.tree.item(node3, open=True)
    widget._populate_floor_node(node3)
    _pump(app, 0.3)
    pane_fits("after opening a floor")
    app.geometry("1900x700")
    _pump(app, 1.0)
    pane_fits("after widening the window with a floor open")
    widget.tree.focus(node3)
    widget._on_tree_close(None)
    _pump(app, 0.3)
    pane_fits("after closing the floor")

    # The tab is laid out for the first time at a new size while it is hidden (startup
    # on another tab, then the window is maximized) -- shown again it must still fit.
    primes_page = app.main_notebook.select()
    other_page = next(t for t in app.main_notebook.tabs() if t != primes_page)
    app.main_notebook.select(other_page)
    _pump(app, 0.3)
    app.geometry("2400x800")
    _pump(app, 1.0)
    app.main_notebook.select(primes_page)
    _pump(app, 1.0)
    pane_fits("after the tab is shown at a size it was never laid out at")

    # The sash is pinned to the content: a drag in either direction snaps back.
    need_pane = widget._tree_content_width()
    widget._tree_paned.sashpos(0, need_pane + 200)
    widget._on_sash_released(None)
    _pump(app, 0.3)
    pane_fits("after dragging the sash wider than the content")
    widget._tree_paned.sashpos(0, need_pane - 100)
    widget._on_sash_released(None)
    _pump(app, 0.3)
    pane_fits("after dragging the sash narrower than the content")
    check(not widget._tree_hsb.winfo_ismapped(),
          "the horizontal scrollbar is hidden while the content fits")

    # A window too narrow for the content (the detail pane keeps its minimum width):
    # the tree pane gives way and a horizontal scrollbar reaches the cut-off columns.
    widget.tree.item(node3, open=True)
    widget._populate_floor_node(node3)
    app.geometry("800x700")
    _pump(app, 1.0)
    narrow = app.nametowidget(tree_pane).winfo_width()
    check(narrow < widget._tree_content_width(),
          f"fixture: an 800px window cannot fit the content ({narrow}px < "
          f"{widget._tree_content_width()}px)")
    check(widget._tree_hsb.winfo_ismapped(),
          "a too-narrow tree pane shows the horizontal scrollbar")
    app.geometry("2400x800")
    _pump(app, 1.0)
    pane_fits("after widening the window back")
    check(not widget._tree_hsb.winfo_ismapped(),
          "the horizontal scrollbar hides again once the content fits")

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
