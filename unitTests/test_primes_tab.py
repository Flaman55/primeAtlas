"""
test_primes_tab.py -- functional regression test for PrimesTab (primeatlas/
primes_tab.py + primeatlas/storage.py), extracted from prime_atlas_v1.py during the
refactor branch's Faza 3 (tab-by-tab backend/UI split, 2026-08-23; task #387). This was
the second tab extracted after Benchmark, and the first one where the search
machinery had to stay app-level (see primes_tab.py's own module docstring) -- so this
test exercises BOTH the tab's self-contained floor/preview UI AND the injected-callable
seam into prime_atlas_v1.py's shared search worker.

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


def main():
    import prime_sieve_v1

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_primes_tab_test_")
    try:
        # Floor 10p0: a single small window, seeded specifically so PAGE_SIZE=5 (see
        # below) splits its 10 primes into exactly 2 preview pages.
        floor0_dir = os.path.join(tmp_portal, "10p0", "source_primes")
        os.makedirs(floor0_dir, exist_ok=True)
        floor0_primes = _primes_upto(30)  # 2,3,5,7,...,29 -> 10 primes
        check(len(floor0_primes) == 10, f"fixture sanity: 10 primes below 30 (got {len(floor0_primes)})")
        prime_sieve_v1.write_prime_window(
            os.path.join(floor0_dir, "PRIME_WINDOW_0000000000.bin"), floor0_primes)

        # Floor 10p3: 7 separate window files -- with FLOOR_PAGE_SIZE monkeypatched to 3
        # below, this spans exactly 3 floor-nav pages (3+3+1).
        floor3_dir = os.path.join(tmp_portal, "10p3", "source_primes")
        os.makedirs(floor3_dir, exist_ok=True)
        for i in range(7):
            start = 1000 + i * 100
            primes = [p for p in range(start, start + 100)
                      if p > 1 and all(p % d for d in range(2, int(p ** 0.5) + 1))]
            prime_sieve_v1.write_prime_window(
                os.path.join(floor3_dir, f"PRIME_WINDOW_{start:010d}.bin"), primes)

        shown = _patch_messageboxes()

        sys.argv = ["prime_atlas_v1.py"]
        import prime_atlas_v1

        # Small page sizes so the fixture above (10 primes / 7 files) actually exercises
        # multi-page pagination without needing hundreds of real files on disk. Both
        # constants are read by PrimesTab.__init__ as plain values at _build_primes_tab()
        # call time (see that method's own docstring), so this MUST happen before the
        # app is constructed -- same reasoning as the PORTAL_FOLDER redirection below.
        prime_atlas_v1.PAGE_SIZE = 5
        prime_atlas_v1.FLOOR_PAGE_SIZE = 3

        _patch_app_settings(prime_atlas_v1.APP_SETTINGS)
        prime_atlas_v1.APP_SETTINGS.set_storage_path(tmp_portal)
        prime_atlas_v1.PORTAL_FOLDER = tmp_portal

        app_cls = prime_atlas_v1._build_gui()
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

        # --- floor pagination: expand 10p3 (7 files / FLOOR_PAGE_SIZE=3 -> 3 pages) --
        widget.tree.focus(node3)
        widget._populate_pietro_node(node3)
        widget._set_active_floor_node(node3)
        state = widget._pietro_state[node3]
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
        check(node3 not in widget._pietro_state, "closing the floor node drops its cached page state")

        # --- selecting a file row + loading the preview -----------------------------
        widget.tree.item(node0, open=True)
        widget._populate_pietro_node(node0)
        file_item = widget.tree.get_children(node0)[0]
        widget.tree.selection_set(file_item)
        widget.tree.focus(file_item)
        widget._on_tree_select(None)
        check(str(widget.load_preview_btn["state"]) == "normal",
              "selecting a non-empty file row enables Load preview")

        widget._load_preview()
        check(widget._preview_primes == floor0_primes,
              f"_load_preview() decoded the exact seeded prime list (got {widget._preview_primes})")
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
        check(app._search_busy, "clicking Search dispatches a job (search_busy set)")
        _pump(app, 3.0)
        check(not app._search_busy, "search job settles after the worker result")
        check(str(floor0_primes[3]) in app.status.get(),
              f"status mentions the found prime (got: {app.status.get()!r})")
        check(widget._preview_primes == floor0_primes,
              "on_prime_search_result() loaded the right file's primes into the preview")

        # --- invalid input is rejected without touching the worker ------------------
        shown.clear()
        widget.search_entry.delete(0, "end")
        widget.search_entry.insert(0, "not-a-number")
        widget.search_button.invoke()
        check(not app._search_busy, "an invalid search query never reaches the worker")
        check(any(kind == "error" for kind, _a, _k in shown),
              f"an invalid search query shows an error dialog instead (got: {shown})")

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
