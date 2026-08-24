"""
primes_tab.py -- PrimesTab, the tkinter widgets for the "Prime numbers" tab: a
lazily-paginated floor tree (one node per 10p{N} folder, expanding to a page of that
floor's PRIME_WINDOW_*.bin files) plus a file-preview pane (paginated decoded prime
list) and a search box that jumps straight to a specific number.

Extracted from prime_atlas_v1.py during the refactor branch's Faza 3 (tab-by-tab
backend/UI split, 2026-08-23) -- the second tab extracted after Benchmark (see that
tab's own commit history), and the first one to need REAL cross-tab shared services
instead of just one small nav-controls helper: floor/window listing and the totals-cache
logic live in primeatlas/storage.py (imported from here, no circularity since that
module has no tkinter dependency), but the SEARCH machinery is a genuinely shared,
app-level subsystem -- ONE PersistentWorker + ONE status/progress bar used by BOTH this
tab's search box and the Constellations tab's own (still living directly in
prime_atlas_v1.py), and the "generate the missing window, then retry" dialog it can
trigger reaches into the Generation tab's own launch methods and its run-finished
callback. None of that belongs to "the Prime numbers tab" specifically, so it stays in
prime_atlas_v1.py and is handed to this class as plain callables at construction time --
see __init__'s own docstring for exactly which ones and why, same reasoning
primeatlas/benchmark_tab.py's own docstring gives for its update_nav_controls parameter.

The per-floor "total prime count" background worker (a SECOND PersistentWorker, reading
every source window's header for a floor -- can take ~78s on a heavily-populated one)
also stays in prime_atlas_v1.py, for the same "shares the search worker's status/
progress bar" reason. This tab owns only the DISPLAY side of that worker's results (the
tree rows, the floor nav's page-total label) via populate_floors()/update_floor_row(),
called by prime_atlas_v1.py's own worker-result handlers (_on_primes_tree_scan_done/
_on_pietro_total_ready) instead of those handlers reaching into this tab's tree/state
attributes directly.

This is one of only a few files in primeatlas/ that import tkinter -- see
settings_tab.py's own docstring for the general "pure logic elsewhere" convention this
package otherwise follows.
"""
import os

import tkinter as tk
from tkinter import ttk, messagebox

import prime_sieve_v1

from .base_tab import BaseTab
from .storage import (
    digit_count_floor, format_big_int, format_bytes, format_duration,
    list_pietra, list_source_filenames, read_source_file_headers,
)
from .widgets import FlowRow


class PrimesTab(BaseTab):
    def __init__(self, parent, get_portal_folder, status_var, translator,
                 update_nav_controls, render_page, page_size, floor_page_size,
                 reload_primes_tree, start_search_job, is_search_busy,
                 offer_generate_missing_prime_window, submit_totals_job):
        """
        get_portal_folder/status_var/translator/update_nav_controls: same dependency-
        injection pattern as BenchmarkTab's own constructor (see that class's
        docstring) -- avoids importing prime_atlas_v1.py directly, which would be
        circular (that file imports PrimesTab from this module).

        reload_primes_tree: prime_atlas_v1.py's own reload_primes_tree() -- the
        Refresh button's actual handler. Stays at the app level (unlike every OTHER
        tab's own Refresh button) because it dispatches a BACKGROUND disk scan shared
        with the startup loading screen's own bookkeeping (_loading_startup_pending,
        see that method's own docstring) -- this tab only receives the finished
        result, via populate_floors(), once that scan completes.

        render_page: prime_atlas_v1.py's own _render_page() helper, shared with the
        Constellations tab's own preview pane -- injected rather than duplicated, same
        reasoning as update_nav_controls.

        page_size/floor_page_size: prime_atlas_v1.py's PAGE_SIZE/FLOOR_PAGE_SIZE module
        constants, passed as plain values instead of imported -- PAGE_SIZE in
        particular is shared with the Constellations tab's own preview pane, so it
        stays a prime_atlas_v1.py-owned constant rather than moving here just for this
        one tab.

        start_search_job(kind, base_exponent, number)/is_search_busy(): the shared
        search PersistentWorker's dispatch function and busy-flag getter (see
        prime_atlas_v1.py's own _start_search_job()/_search_busy) -- shared with the
        Constellations tab's search box (both tabs' Search buttons disable together
        while EITHER kind of search is in flight, and both share one status/progress
        bar), so the worker itself stays in prime_atlas_v1.py rather than being
        duplicated or awkwardly split between two tab modules.

        offer_generate_missing_prime_window(base_exponent, number): prime_atlas_v1.py's
        own _offer_generate_missing_prime_window(), pre-bound to kind="prime" by the
        caller -- stays at the app level because it can launch a generation run via the
        Generation tab's own methods (_apply_primesieve_params_and_run/
        _apply_orchestrator_direct_params_and_run) and queues a post-generation retry
        consumed by THAT tab's own run-finished handler (_on_loop_finished) -- none of
        which this tab has any business owning.

        submit_totals_job(base_exponent): prime_atlas_v1.py's per-floor totals
        PersistentWorker's submit() method -- expanding a floor re-checks its total
        (cheap no-op if nothing changed, see update_pietro_totals_cache()'s own
        docstring), the same worker the Refresh button's "compute all" batch uses.
        """
        super().__init__(parent, translator)
        self._get_portal_folder = get_portal_folder
        self.status = status_var
        self._update_nav_controls = update_nav_controls
        self._render_page = render_page
        self._page_size = page_size
        self._floor_page_size = floor_page_size
        self._reload_primes_tree = reload_primes_tree
        self._start_search_job = start_search_job
        self._is_search_busy = is_search_busy
        self._offer_generate_missing_prime_window = offer_generate_missing_prime_window
        self._submit_totals_job = submit_totals_job

        self._pietro_total_known = {}   # base_exponent -> (total, file_count,
                                         # total_bytes), seeded by populate_floors(),
                                         # kept current by update_floor_row()
        self._pietro_gen_seconds = {}   # base_exponent -> total real generation
                                         # seconds, seeded by populate_floors() (see
                                         # that method's own docstring)

        self._build_widgets()

    def _build_widgets(self):
        T = self.T

        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=4)
        ttk.Button(top, text=T("common.refresh"), command=self._reload_primes_tree).pack(side="left")

        ttk.Label(top, text=T("common.search_label")).pack(side="left")
        self.search_entry = ttk.Entry(top, width=26)
        self.search_entry.pack(side="left", padx=(4, 4))
        self.search_entry.bind("<Return>", lambda _e: self._search_prime())
        self.search_button = ttk.Button(
            top, text=T("common.search_button"), command=self._search_prime)
        self.search_button.pack(side="left")

        # No separate "compute all totals" button --
        # Refresh already re-runs the totals scan for every floor (see
        # prime_atlas_v1.py's reload_primes_tree()), so a second button doing the same
        # thing was redundant. Re-running costs almost nothing when nothing changed:
        # update_pietro_totals_cache() only re-reads files NOT already in its cache (a
        # cheap os.listdir() + in-memory set diff per floor either way -- see that
        # function's docstring), so hitting Refresh after generating new windows only
        # pays for the new files, not a full floor-by-floor rescan.
        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=6, pady=4)

        tree_frame = ttk.Frame(paned)
        paned.add(tree_frame, weight=1)

        # Floor pagination -- ABOVE the tree, same Prev/label/Next/goto layout
        # as the file-preview pane on the right (see btn_row below). A floor can hold
        # thousands of source windows -- listing+rendering them all on one expand is
        # what used to freeze the GUI. Expanding a floor now only lists filenames
        # (cheap) and loads ONE page's worth of headers; these controls act on whichever
        # floor was most recently opened/clicked (self._active_floor_node) -- multiple
        # floors can stay expanded at once, each remembering its own page independently.
        floor_nav = ttk.Frame(tree_frame)
        floor_nav.pack(fill="x", pady=(0, 4))
        self.floor_prev_btn = ttk.Button(
            floor_nav, text=T("common.prev_page"), command=self._prev_floor_page, state="disabled")
        self.floor_prev_btn.pack(side="left")
        self.floor_page_label = tk.StringVar(value="")
        ttk.Label(floor_nav, textvariable=self.floor_page_label, width=16, anchor="center").pack(side="left")
        self.floor_next_btn = ttk.Button(
            floor_nav, text=T("common.next_page"), command=self._next_floor_page, state="disabled")
        self.floor_next_btn.pack(side="left")
        ttk.Label(floor_nav, text=T("common.page_prefix")).pack(side="left", padx=(10, 0))
        self.floor_goto_entry = ttk.Entry(floor_nav, width=6)
        self.floor_goto_entry.pack(side="left", padx=(4, 0))
        self.floor_goto_entry.bind("<Return>", lambda _e: self._goto_floor_page())
        ttk.Button(floor_nav, text=T("common.goto"), command=self._goto_floor_page).pack(side="left", padx=(4, 0))

        # Page subtotal (instant -- sums the headers this page already had to read to
        # display the file list, no extra I/O) alongside the floor's OVERALL total,
        # which is NOT instant for a heavily-populated floor and gets filled in
        # asynchronously once the background totals worker finishes (see
        # update_floor_row()) -- shows "computing..." until then.
        self.floor_subtotal_label = tk.StringVar(value="")
        ttk.Label(floor_nav, textvariable=self.floor_subtotal_label, anchor="w").pack(
            side="left", padx=(14, 0))

        # 4 value columns: count/files/generated/timer, split apart
        # because "generated" used to double as BOTH a per-file UTC timestamp (file rows)
        # AND a file count (floor summary rows) -- confusing on a collapsed floor, which
        # only ever shows the summary row. "files" now always means file count, "generated"
        # always means a UTC timestamp (blank on floor rows -- no single date is
        # meaningful for a whole floor), "timer" is new: total REAL generation time for
        # that floor (write_files=True runs only, see aggregate_write_seconds_by_pietro()).
        self.tree = ttk.Treeview(
            tree_frame, columns=("count", "files", "size", "generated", "timer"),
            show="tree headings")
        self.tree.heading("#0", text=T("primes.col_pietro"))
        self.tree.heading("count", text=T("primes.col_count"))
        self.tree.heading("files", text=T("primes.col_files"))
        self.tree.heading("size", text=T("primes.col_size"))
        self.tree.heading("generated", text=T("primes.col_generated"))
        self.tree.heading("timer", text=T("primes.col_timer"))
        self.tree.column("#0", width=260)
        self.tree.column("count", width=90, anchor="e")
        self.tree.column("files", width=90, anchor="e")
        self.tree.column("size", width=90, anchor="e")
        self.tree.column("generated", width=170)
        self.tree.column("timer", width=110, anchor="e")
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self.tree.bind("<<TreeviewClose>>", self._on_tree_close)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        self._pietro_state = {}         # tree item id -> {base_exponent, filenames,
                                         # page, total_pages}, or None if checked and
                                         # found empty. Populated lazily on
                                         # <<TreeviewOpen>>, dropped entirely (freeing
                                         # the filename list + tree rows) on
                                         # <<TreeviewClose>> -- see _on_tree_close.
        self._active_floor_node = None  # which floor's page the floor nav buttons
                                         # above currently operate on
        self._pietro_node_by_exp = {}   # base_exponent -> tree item id, so a totals
                                         # result arriving from the background worker
                                         # (keyed by base_exponent, not tree item id --
                                         # see update_floor_row()) knows which row to
                                         # update, even after a Refresh rebuilt the tree

        detail_frame = ttk.Frame(paned)
        paned.add(detail_frame, weight=2)

        self.detail_text = tk.StringVar(value=T("primes.detail_hint"))
        ttk.Label(detail_frame, textvariable=self.detail_text, justify="left",
                  anchor="nw", wraplength=560).pack(fill="x", padx=6, pady=6)

        # FlowRow (not a plain pack(side="left") row) so these controls wrap onto a
        # second line instead of running off the window's right edge on a narrow
        # width/pane -- see that class's own docstring.
        btn_row = FlowRow(detail_frame)
        btn_row.frame.pack(anchor="w", padx=6, fill="x")
        self.load_preview_btn = ttk.Button(
            btn_row.frame, text=T("common.load_preview"), command=self._load_preview, state="disabled")
        btn_row.add(self.load_preview_btn)
        self.prev_page_btn = ttk.Button(
            btn_row.frame, text=T("common.prev_page"), command=self._prev_preview_page, state="disabled")
        btn_row.add(self.prev_page_btn, padx_left=10)
        self.preview_page_label = tk.StringVar(value="")
        btn_row.add(ttk.Label(btn_row.frame, textvariable=self.preview_page_label,
                               width=16, anchor="center"))
        self.next_page_btn = ttk.Button(
            btn_row.frame, text=T("common.next_page"), command=self._next_preview_page, state="disabled")
        btn_row.add(self.next_page_btn)
        btn_row.add(ttk.Label(btn_row.frame, text=T("common.page_prefix")), padx_left=10)
        self.preview_goto_entry = ttk.Entry(btn_row.frame, width=6)
        btn_row.add(self.preview_goto_entry, padx_left=4)
        self.preview_goto_entry.bind("<Return>", lambda _e: self._goto_preview_page())
        btn_row.add(ttk.Button(btn_row.frame, text=T("common.goto"),
                                command=self._goto_preview_page), padx_left=4)

        preview_frame = ttk.Frame(detail_frame)
        preview_frame.pack(fill="both", expand=True, padx=6, pady=6)
        self.preview_list = tk.Listbox(preview_frame, font=("Consolas", 9))
        preview_vsb = ttk.Scrollbar(preview_frame, orient="vertical", command=self.preview_list.yview)
        self.preview_list.configure(yscrollcommand=preview_vsb.set)
        self.preview_list.pack(side="left", fill="both", expand=True)
        preview_vsb.pack(side="right", fill="y")

        # Each row here IS a single prime (unlike the Constellations tab's rows, which
        # show a whole reconstructed tuple) -- Ctrl+C and right-click "Copy" both
        # copy the selected row's actual value to the clipboard. A plain tk.Listbox
        # has no built-in copy behaviour at all, so without this there was no way to
        # get a value out of the list except retyping it by hand.
        self.preview_list.bind("<Control-c>", lambda _e: self._copy_selected_preview_value())
        self.preview_list.bind("<Button-3>", self._show_preview_context_menu)
        self._preview_context_menu = tk.Menu(self, tearoff=0)
        self._preview_context_menu.add_command(label=T("common.copy"), command=self._copy_selected_preview_value)

        self._selected_path = None
        self._preview_primes = None    # full decoded list for the selected file, cached
                                        # after "Load preview" so page navigation doesn't
                                        # re-decode the file from scratch each click
        self._preview_page = 0
        self._preview_total_pages = 1
        self._path_by_item = {}

    # --- Called by prime_atlas_v1.py's own reload_primes_tree()/totals-worker machinery,
    # which stays at the app level (see this class's own docstring) -----------------------

    def populate_floors(self, pietra, pietro_total_known, pietro_gen_seconds):
        """Rebuilds the floor tree from scratch -- called by prime_atlas_v1.py's own
        _on_primes_tree_scan_done() once reload_primes_tree()'s background disk scan
        (_primes_tree_scan) returns. pietro_total_known/pietro_gen_seconds are fresh
        dicts straight from that scan (see _primes_tree_scan()'s own docstring) --
        stored here (replacing whatever this tab held before), not merged, since the
        scan itself already re-read both sources of truth (the on-disk totals cache and
        benchmark_log.csv) from scratch."""
        T = self.T
        self._pietro_total_known = pietro_total_known
        self._pietro_gen_seconds = pietro_gen_seconds
        self.tree.delete(*self.tree.get_children())
        self._pietro_state = {}
        self._active_floor_node = None
        self._path_by_item = {}
        self._pietro_node_by_exp = {}
        self._refresh_floor_nav_controls()
        for base_exponent in pietra:
            # If a previous scan (this session or a past one, via the on-disk cache)
            # already knows this floor's total, show it immediately -- otherwise leave
            # the count column blank until the background worker fills it in (see
            # update_floor_row()). Either way the row is shown right away; only the
            # count itself may lag, and even then only until the (re-)scan reaches it.
            known = self._pietro_total_known.get(base_exponent)
            gen_seconds = self._pietro_gen_seconds.get(base_exponent)
            timer_str = format_duration(gen_seconds) if gen_seconds is not None else ""
            values = ((f"{known[0]:,}", f"{known[1]:,}", format_bytes(known[2]), "", timer_str)
                      if known else ("", "", "", "", timer_str))
            node = self.tree.insert("", "end", text=f"10p{base_exponent}",
                                     values=values, open=False, tags=("pietro",))
            self.tree.insert(node, "end", text=T("common.loading"))
            self._pietro_node_by_exp[base_exponent] = node

    def get_pietro_node_keys(self):
        """Every floor currently listed in the tree -- used by prime_atlas_v1.py's own
        _compute_all_pietro_totals() to know which base_exponents to submit to the
        totals worker for a "recompute everything" batch."""
        return list(self._pietro_node_by_exp.keys())

    def get_gen_seconds(self, base_exponent):
        """Read access to this tab's own _pietro_gen_seconds, for prime_atlas_v1.py's
        own _on_pietro_total_ready() grand-total duration sum (see that method's own
        docstring) -- this tab is the sole owner of that dict (populated once per
        reload_primes_tree() scan, see populate_floors()), so the app reads it here
        rather than keeping a second copy."""
        return self._pietro_gen_seconds.get(base_exponent)

    def update_floor_row(self, base_exponent, total, file_count, total_bytes):
        """Called by prime_atlas_v1.py's own _on_pietro_total_ready() once the app-level
        totals worker finishes (re-)computing one floor's total -- updates this tab's
        own copy of _pietro_total_known plus the corresponding tree row, and refreshes
        the floor-nav page-total label if that floor happens to be the currently active
        one."""
        self._pietro_total_known[base_exponent] = (total, file_count, total_bytes)
        node = self._pietro_node_by_exp.get(base_exponent)
        gen_seconds = self._pietro_gen_seconds.get(base_exponent)
        timer_str = format_duration(gen_seconds) if gen_seconds is not None else ""
        if node is not None and self.tree.exists(node):
            self.tree.item(node, values=(
                f"{total:,}", f"{file_count:,}", format_bytes(total_bytes), "", timer_str))
        if self._active_floor_node == node:
            self._refresh_floor_nav_controls()

    def on_prime_search_result(self, base_exponent, number, result):
        """Called by prime_atlas_v1.py's own _on_search_worker_result() once a "prime"
        search job (dispatched via the injected start_search_job) comes back -- same UI
        update _search_prime() used to do synchronously right after calling
        find_prime_in_floor() directly, now driven by the shared search worker instead."""
        T = self.T
        if result is None:
            outcome = self._offer_generate_missing_prime_window(base_exponent, number)
            if outcome == "launched":
                return
            if outcome == "composite":
                messagebox.showinfo(
                    T("common.dialog_search_title"),
                    T("primes.confirmed_composite", number=number, base_exponent=base_exponent))
                return
            messagebox.showinfo(
                T("common.dialog_search_title"),
                T("primes.not_found", number=number, base_exponent=base_exponent))
            return
        self._select_primes_file_in_tree(base_exponent, result["name"])
        self._preview_primes = result["primes"]
        self._jump_preview_to_index(result["index"])
        total = len(result["primes"])
        self.status.set(
            T("common.found_in_file", number=number, name=result['name'],
              base_exponent=base_exponent, position=f"{result['index'] + 1:,}", total=f"{total:,}"))

    # --- Floor tree ------------------------------------------------------------------------

    def _on_tree_open(self, _event):
        node = self.tree.focus()
        self._populate_pietro_node(node)
        self._set_active_floor_node(node)
        base_exponent = int(self.tree.item(node, "text")[3:])  # "10p{N}"
        self._submit_totals_job(base_exponent)  # always re-check -- cheap no-op if
                                                 # nothing changed since last time
                                                 # (see update_pietro_totals_cache)

    def _on_tree_close(self, _event):
        """Collapsing a floor drops its whole page/filename-list state and clears its
        rows back to a single "(loading...)" placeholder -- re-expanding later re-lists
        from disk instead of holding onto a floor's data indefinitely just because it
        was opened once. Other, still-open floors are untouched."""
        node = self.tree.focus()
        if node not in self._pietro_state:
            return
        del self._pietro_state[node]
        self._clear_floor_children(node)
        self.tree.insert(node, "end", text=self.T("common.loading"))
        if self._active_floor_node == node:
            self._active_floor_node = None
            self._refresh_floor_nav_controls()

    def _clear_floor_children(self, node):
        """Removes every current child row of `node` from the tree AND from
        self._path_by_item -- without this second part, repeated page turns/collapses
        would leak orphaned item-id -> (path, header) entries for rows that no longer
        exist in the tree."""
        for child in self.tree.get_children(node):
            self._path_by_item.pop(child, None)
        self.tree.delete(*self.tree.get_children(node))

    def _populate_pietro_node(self, node):
        if node in self._pietro_state:
            return  # already listed in this session -- nothing to redo
        T = self.T
        children = self.tree.get_children(node)
        if len(children) == 1 and self.tree.item(children[0], "text") == T("common.loading"):
            self.tree.delete(children[0])

        base_exponent = int(self.tree.item(node, "text")[3:])  # "10p{N}"
        filenames = list_source_filenames(self._get_portal_folder(), base_exponent)  # cheap:
                                                                                       # no
                                                                                       # header
                                                                                       # I/O
        if not filenames:
            self.tree.insert(node, "end", text=T("primes.no_source_files"))
            self._pietro_state[node] = None
            return

        total_pages = max(1, (len(filenames) + self._floor_page_size - 1) // self._floor_page_size)
        self._pietro_state[node] = {
            "base_exponent": base_exponent,
            "filenames": filenames,
            "page": 0,
            "total_pages": total_pages,
        }
        self._show_floor_page(node, 0)

    def _show_floor_page(self, node, page):
        """Renders page `page` (0-indexed) of a floor's file list: reads headers for
        ONLY that page's files (bounded I/O, unlike the old read-every-header-on-expand
        approach) and rebuilds the node's tree rows from scratch."""
        state = self._pietro_state.get(node)
        if not state:
            return
        total_pages = state["total_pages"]
        page = max(0, min(page, total_pages - 1))
        state["page"] = page
        start = page * self._floor_page_size
        end = min(start + self._floor_page_size, len(state["filenames"]))
        page_entries = read_source_file_headers(state["filenames"][start:end])

        self._clear_floor_children(node)
        page_total = 0
        for name, path, header in page_entries:
            try:
                size_str = format_bytes(os.path.getsize(path))
            except OSError:
                size_str = "?"
            if header is None:
                count_str, gen_str = "?", self.T("primes.unreadable_header")
            else:
                count_str = f"{header['count']:,}"
                gen_str = header["generated_at_iso"]
                page_total += header["count"]
            child = self.tree.insert(node, "end", text=name,
                                      values=(count_str, "", size_str, gen_str, ""),
                                      tags=("file",))
            self._path_by_item[child] = (path, header)
        state["page_total"] = page_total

        if self._active_floor_node == node:
            self._refresh_floor_nav_controls()

    def _set_active_floor_node(self, node):
        self._active_floor_node = node
        self._refresh_floor_nav_controls()

    def _refresh_floor_nav_controls(self):
        node = self._active_floor_node
        state = self._pietro_state.get(node) if node is not None else None
        if not state:
            self.floor_page_label.set("")
            self.floor_subtotal_label.set("")
            self.floor_prev_btn.configure(state="disabled")
            self.floor_next_btn.configure(state="disabled")
            return
        self._update_nav_controls(self.floor_page_label, state["page"], state["total_pages"],
                                   self.floor_prev_btn, self.floor_next_btn)
        page_total = state.get("page_total", 0)
        known = self._pietro_total_known.get(state["base_exponent"])
        overall = f"{known[0]:,}" if known else self.T("common.computing")
        self.floor_subtotal_label.set(
            self.T("primes.page_total", page_total=f"{page_total:,}", overall=overall))

    def _prev_floor_page(self):
        node = self._active_floor_node
        if node is not None and self._pietro_state.get(node):
            self._show_floor_page(node, self._pietro_state[node]["page"] - 1)

    def _next_floor_page(self):
        node = self._active_floor_node
        if node is not None and self._pietro_state.get(node):
            self._show_floor_page(node, self._pietro_state[node]["page"] + 1)

    def _goto_floor_page(self):
        raw = self.floor_goto_entry.get().strip()
        if not raw.isdigit():
            return
        node = self._active_floor_node
        if node is not None and self._pietro_state.get(node):
            self._show_floor_page(node, int(raw) - 1)

    def _on_tree_select(self, _event):
        selection = self.tree.selection()
        if not selection:
            return
        item = selection[0]
        if "pietro" in self.tree.item(item, "tags"):
            # Clicking a floor header (whether just opened or already expanded) makes
            # it the target of the floor-pagination controls above the tree, without
            # touching the file-preview state on the right.
            self._set_active_floor_node(item)
            return
        self._reset_preview_state()
        if item not in self._path_by_item:
            self.load_preview_btn.configure(state="disabled")
            return
        path, header = self._path_by_item[item]
        self._selected_path = path
        T = self.T
        if header is None:
            self.detail_text.set(T("primes.header_error", path=path))
            self.load_preview_btn.configure(state="disabled")
            return
        self.detail_text.set(
            f"{path}\n\n" +
            T("primes.header_detail",
              base_prime=format_big_int(header['base_prime']),
              count=f"{header['count']:,}",
              generated=header['generated_at_iso'])
        )
        self.load_preview_btn.configure(state="normal" if header["count"] > 0 else "disabled")

    # --- Preview pane ------------------------------------------------------------------------

    def _reset_preview_state(self):
        self.preview_list.delete(0, "end")
        self._preview_primes = None
        self._preview_page = 0
        self._preview_total_pages = 1
        self.preview_page_label.set("")
        self.prev_page_btn.configure(state="disabled")
        self.next_page_btn.configure(state="disabled")
        self.load_preview_btn.configure(state="normal" if self._selected_path else "disabled")

    def _load_preview(self):
        """Decodes the selected file ONCE (cached in self._preview_primes) and shows
        page 1."""
        if not self._selected_path:
            return
        if self._preview_primes is None:
            try:
                self._preview_primes = prime_sieve_v1.read_prime_window(self._selected_path)
            except Exception as exc:
                messagebox.showerror(self.T("primes.load_preview_failed_title"), str(exc))
                self._preview_primes = None
                return
        self._show_preview_page(0)
        self.load_preview_btn.configure(state="disabled")

    def _show_preview_page(self, page):
        if not self._preview_primes:
            return
        self._preview_page, self._preview_total_pages = self._render_page(
            self.preview_list, self._preview_primes, page, self._page_size, str)
        self._update_nav_controls(self.preview_page_label, self._preview_page,
                                   self._preview_total_pages, self.prev_page_btn, self.next_page_btn)

    def _prev_preview_page(self):
        self._show_preview_page(self._preview_page - 1)

    def _next_preview_page(self):
        self._show_preview_page(self._preview_page + 1)

    def _goto_preview_page(self):
        raw = self.preview_goto_entry.get().strip()
        if not raw.isdigit():
            return
        self._show_preview_page(int(raw) - 1)

    # --- Search --------------------------------------------------------------------------

    def _search_prime(self):
        T = self.T
        raw = self.search_entry.get().strip()
        if not raw.isdigit():
            messagebox.showerror(T("common.dialog_search_title"), T("common.error_invalid_number"))
            return
        number = int(raw)
        base_exponent = digit_count_floor(number)
        if self._is_search_busy():
            messagebox.showinfo(T("common.dialog_search_title"), T("common.search_already_running"))
            return
        if base_exponent not in list_pietra(self._get_portal_folder()):
            # No floor 10p{base_exponent} at all yet -- the SAME "this number's storage
            # fragment doesn't exist" situation on_prime_search_result() handles for an
            # existing-but-incomplete floor, just at the whole-floor scale (existing_count
            # is naturally 0 for a floor with zero windows -- see
            # find_continuation_target_idx()'s own docstring, still in prime_atlas_v1.py).
            # Route it through the exact same offer instead of a dead-end "no floor"
            # message: there's nothing this dialog told the user that generating the
            # fragment doesn't already cover.
            outcome = self._offer_generate_missing_prime_window(base_exponent, number)
            if outcome == "launched":
                return
            if outcome == "composite":
                messagebox.showinfo(
                    T("common.dialog_search_title"),
                    T("primes.confirmed_composite", number=number, base_exponent=base_exponent))
                return
            messagebox.showinfo(
                T("common.dialog_search_title"),
                T("primes.not_found", number=number, base_exponent=base_exponent))
            return
        self._start_search_job("prime", base_exponent, number)

    def _select_primes_file_in_tree(self, base_exponent, filename):
        pietro_item = None
        for item in self.tree.get_children(""):
            if self.tree.item(item, "text") == f"10p{base_exponent}":
                pietro_item = item
                break
        if pietro_item is None:
            return
        self.tree.item(pietro_item, open=True)
        self._populate_pietro_node(pietro_item)
        self._set_active_floor_node(pietro_item)
        state = self._pietro_state.get(pietro_item)
        if state:
            # Jump to whichever page actually contains this filename -- search can
            # land anywhere across a floor with thousands of paginated files, not
            # just whatever page happened to be showing (usually page 1).
            for idx, (name, _path) in enumerate(state["filenames"]):
                if name == filename:
                    self._show_floor_page(pietro_item, idx // self._floor_page_size)
                    break
        target_item = None
        for child in self.tree.get_children(pietro_item):
            if self.tree.item(child, "text") == filename:
                target_item = child
                break
        if target_item is None:
            return
        # selection_set() queues an async <<TreeviewSelect>> virtual event rather than
        # dispatching it immediately -- Tk resolves the bound handler at DISPATCH time,
        # not at generation time, so even unbind()-ing around this call doesn't help
        # (the event still fires, against whatever's bound once event processing
        # resumes). If the caller sets up search-specific preview state (jump to a
        # specific index) right after this returns, that queued event would fire
        # later and silently wipe it out via _on_tree_select's _reset_preview_state().
        # Flushing the event queue with update() here forces it to fire and run its
        # course NOW, before this function returns -- so any later state changes are
        # safe.
        self.tree.see(target_item)
        self.tree.selection_set(target_item)
        self.tree.focus(target_item)
        self.update()

    def _jump_preview_to_index(self, index):
        if not self._preview_primes:
            return
        page = index // self._page_size
        self._show_preview_page(page)
        self.load_preview_btn.configure(state="disabled")
        local = index - self._preview_page * self._page_size
        self.preview_list.selection_clear(0, "end")
        self.preview_list.selection_set(local)
        self.preview_list.see(local)

    def _show_preview_context_menu(self, event):
        # Right-clicking an unselected row should select IT (not whatever was
        # selected before), matching how most list/tree widgets behave elsewhere.
        index = self.preview_list.nearest(event.y)
        if index >= 0:
            self.preview_list.selection_clear(0, "end")
            self.preview_list.selection_set(index)
        self._preview_context_menu.tk_popup(event.x_root, event.y_root)

    def _copy_selected_preview_value(self):
        sel = self.preview_list.curselection()
        if not sel or not self._preview_primes:
            return
        global_index = self._preview_page * self._page_size + sel[0]
        if global_index >= len(self._preview_primes):
            return
        self._copy_to_clipboard(str(self._preview_primes[global_index]))
