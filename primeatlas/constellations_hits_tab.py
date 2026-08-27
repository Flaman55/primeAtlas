"""
constellations_hits_tab.py -- ConstellationsHitsTab, the tkinter widgets for the
Constellations tab's "Magazyn" (storage) sub-tab: a floor tree grouped by k-tuple
pattern (constellations/k{k}/variant{id}/HITS_*.bin), a paginated hit-value preview
pane, and the "const" search box that jumps straight to every pattern a searched
number participates in.

Extracted from prime_atlas_v1.py during the refactor branch's Faza 3 (tab-by-tab
backend/UI split, 2026-08-23), the third tab extracted after Benchmark and Prime
numbers -- see primeatlas/primes_tab.py's own module docstring for the general
dependency-injection shape this follows (avoids importing prime_atlas_v1.py directly,
which would be circular).

Like the Prime numbers tab, the SEARCH machinery itself (the shared PersistentWorker,
one status/progress bar used by both this tab and the Prime numbers tab's own search
box, and the "generate the missing fragment, then retry" dialog that can launch a run
via the Generation tab) is a genuinely shared, app-level subsystem and stays in
prime_atlas_v1.py -- this tab receives start_search_job/is_search_busy/
offer_generate_missing_prime_window as injected callables, same shape as
primeatlas/primes_tab.py's own constructor.

ONE further wrinkle this tab has that Primes didn't: a "const" search's completion
handler needs to coordinate with the SIBLING Kalkulator konstelacji tab (does this
result belong to a search the calculator itself kicked off, and if so, auto-jump to
that exact pattern once the result comes back) -- see on_const_search_result()'s own
docstring for exactly how that coupling is kept to a thin, app-level orchestration
method (_on_const_search_result, still in prime_atlas_v1.py) instead of leaking one
tab's internals into the other.

This is one of a few files in primeatlas/ that import tkinter -- see
primes_tab.py's own docstring for the general "pure logic elsewhere" convention this
package otherwise follows.
"""
import bisect

import tkinter as tk
from tkinter import ttk, messagebox

import prime_sieve_v1

from .base_tab import BaseTab
from .storage import digit_count_floor, list_pietra
from .constellations import group_constellation_hits_by_k, list_constellation_hits
from .widgets import FlowRow


class ConstellationsHitsTab(BaseTab):
    def __init__(self, parent, get_portal_folder, status_var, translator,
                 update_nav_controls, render_page, page_size,
                 reload_constellations_tree, start_search_job, is_search_busy,
                 offer_generate_missing_prime_window):
        """
        get_portal_folder/status_var/translator/update_nav_controls/render_page/
        page_size: same dependency-injection pattern as PrimesTab's own constructor
        (see that class's docstring) -- page_size in particular is prime_atlas_v1.py's
        shared PAGE_SIZE constant, also used by the Prime numbers tab's own preview.

        reload_constellations_tree: prime_atlas_v1.py's own reload_constellations_tree()
        -- the Refresh button's actual handler, staying at the app level for the same
        "shared with the startup loading screen's own bookkeeping" reason
        PrimesTab's reload_primes_tree parameter does.

        start_search_job(kind, base_exponent, number)/is_search_busy(): the shared
        search PersistentWorker's dispatch function and busy-flag getter -- see
        primeatlas/primes_tab.py's own docstring for the full rationale (shared with
        the Prime numbers tab's own search box, one status/progress bar for both).

        offer_generate_missing_prime_window(base_exponent, number): prime_atlas_v1.py's
        own _offer_generate_missing_prime_window(), pre-bound to kind="const" by the
        caller -- stays at the app level for the same reason as PrimesTab's own
        parameter of the same name (can launch a Generation-tab run).
        """
        super().__init__(parent, translator)
        self._get_portal_folder = get_portal_folder
        self.status = status_var
        self._update_nav_controls = update_nav_controls
        self._render_page = render_page
        self._page_size = page_size
        self._reload_constellations_tree = reload_constellations_tree
        self._start_search_job = start_search_job
        self._is_search_busy = is_search_busy
        self._offer_generate_missing_prime_window = offer_generate_missing_prime_window

        # (base_exponent, k, id) -> set(decoded starting values), reused across
        # searches within this session so each hit file is only decoded once. Public
        # (no leading underscore) -- prime_atlas_v1.py's own _search_job runs on the
        # shared search worker's background thread and mutates this dict in place via
        # find_constellation_participation() (see that function's own docstring for
        # why the cache lives here rather than as module state); _is_search_busy()
        # blocking a second concurrent search from the GUI side means only one job is
        # ever in flight, so this never races against itself.
        self.hit_set_cache = {}

        self._build_widgets()

    def _build_widgets(self):
        T = self.T

        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=4)
        ttk.Button(top, text=T("common.refresh"),
                   command=self._reload_constellations_tree).pack(side="left")

        ttk.Label(top, text=T("common.search_label")).pack(side="left")
        self.hits_search_entry = ttk.Entry(top, width=26)
        self.hits_search_entry.pack(side="left", padx=(4, 4))
        self.hits_search_entry.bind("<Return>", lambda _e: self.search_constellation())
        self.hits_search_button = ttk.Button(
            top, text=T("common.search_button"), command=self.search_constellation)
        self.hits_search_button.pack(side="left")

        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=6, pady=4)

        tree_frame = ttk.Frame(paned)
        paned.add(tree_frame, weight=1)

        self.hits_tree = ttk.Treeview(tree_frame, columns=("count", "generated"), show="tree headings")
        self.hits_tree.heading("#0", text=T("const.col_pietro"))
        self.hits_tree.heading("count", text=T("const.col_count"))
        self.hits_tree.heading("generated", text=T("const.col_generated"))
        self.hits_tree.column("#0", width=280)
        self.hits_tree.column("count", width=90, anchor="e")
        self.hits_tree.column("generated", width=170)
        hvsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.hits_tree.yview)
        self.hits_tree.configure(yscrollcommand=hvsb.set)
        self.hits_tree.pack(side="left", fill="both", expand=True)
        hvsb.pack(side="right", fill="y")

        self.hits_tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self.hits_tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        detail_frame = ttk.Frame(paned)
        paned.add(detail_frame, weight=2)

        self.hits_detail_text = tk.StringVar(value=T("const.detail_hint"))
        ttk.Label(detail_frame, textvariable=self.hits_detail_text, justify="left",
                  anchor="nw", wraplength=560).pack(fill="x", padx=6, pady=6)

        # Populated only after a search (empty during normal tree browsing): one row
        # per pattern the searched number participates in. Double-click (or Enter)
        # jumps straight to that exact hit's row in the preview below, mirroring how
        # the Prime numbers tab's search lands directly on the found number.
        self.search_results_list = tk.Listbox(detail_frame, height=5, font=("Consolas", 9))
        self.search_results_list.pack(fill="x", padx=6, pady=(0, 6))
        self.search_results_list.bind("<Double-Button-1>", self._on_search_result_activate)
        self.search_results_list.bind("<Return>", self._on_search_result_activate)
        self._search_results_data = []  # parallel to search_results_list rows

        # FlowRow, same reasoning as the Prime numbers tab's own preview-nav row -- see
        # that class's own docstring.
        btn_row = FlowRow(detail_frame)
        btn_row.frame.pack(anchor="w", padx=6, fill="x")
        self.hits_load_preview_btn = ttk.Button(
            btn_row.frame, text=T("common.load_preview"), command=self.load_preview,
            state="disabled")
        btn_row.add(self.hits_load_preview_btn)
        self.hits_prev_page_btn = ttk.Button(
            btn_row.frame, text=T("common.prev_page"), command=self._prev_hits_page, state="disabled")
        btn_row.add(self.hits_prev_page_btn, padx_left=10)
        self.hits_page_label = tk.StringVar(value="")
        btn_row.add(ttk.Label(btn_row.frame, textvariable=self.hits_page_label,
                               width=16, anchor="center"))
        self.hits_next_page_btn = ttk.Button(
            btn_row.frame, text=T("common.next_page"), command=self._next_hits_page, state="disabled")
        btn_row.add(self.hits_next_page_btn)
        btn_row.add(ttk.Label(btn_row.frame, text=T("common.page_prefix")), padx_left=10)
        self.hits_goto_entry = ttk.Entry(btn_row.frame, width=6)
        btn_row.add(self.hits_goto_entry, padx_left=4)
        self.hits_goto_entry.bind("<Return>", lambda _e: self._goto_hits_page())
        btn_row.add(ttk.Button(btn_row.frame, text=T("common.goto"),
                                command=self._goto_hits_page), padx_left=4)

        hits_preview_frame = ttk.Frame(detail_frame)
        hits_preview_frame.pack(fill="both", expand=True, padx=6, pady=6)
        self.hits_preview_list = tk.Listbox(hits_preview_frame, font=("Consolas", 9))
        hits_preview_vsb = ttk.Scrollbar(hits_preview_frame, orient="vertical",
                                          command=self.hits_preview_list.yview)
        self.hits_preview_list.configure(yscrollcommand=hits_preview_vsb.set)
        self.hits_preview_list.pack(side="left", fill="both", expand=True)
        hits_preview_vsb.pack(side="right", fill="y")

        # Each row here is ONE number (the pattern's position/offset context is shown
        # alongside it, not merged into a single copy-unfriendly comma-joined tuple
        # string) -- same Ctrl+C / right-click "Copy" convenience as the primes tab.
        self.hits_preview_list.bind("<Control-c>", lambda _e: self._copy_selected_hits_value())
        self.hits_preview_list.bind("<Button-3>", self._show_hits_context_menu)
        self._hits_context_menu = tk.Menu(self, tearoff=0)
        self._hits_context_menu.add_command(label=T("common.copy"), command=self._copy_selected_hits_value)

        self._hit_path_by_item = {}
        self._selected_hit_path = None
        self._selected_hit_pattern = None  # dict from pattern_catalog_v1, needed to
                                            # know each position's offset within a tuple
        self._hit_values = None    # raw decoded starting values for the selected
                                    # pattern's hit file, sorted ascending
        self._hit_rows = None      # flattened (value, hit_base, position, offset) --
                                    # one entry PER TUPLE POSITION, not per hit, so each
                                    # preview row is a single number like the primes tab
        self._hit_page = 0
        self._hit_total_pages = 1

    # --- Called by prime_atlas_v1.py's own reload_constellations_tree() machinery,
    # which stays at the app level (see this class's own docstring) -----------------------

    def populate_floors(self, pietra):
        """Rebuilds the floor tree from scratch -- called by
        ConstellationsTreeCoordinator._on_scan_done
        (primeatlas/constellations_tree_coordinator.py, moved out of prime_atlas_v1.py
        itself during the refactor-phase3 branch, 2026-08-27) once
        reload_constellations_tree()'s background disk scan
        (ConstellationsTreeCoordinator._scan) returns. Also drops the hit-set cache --
        data on disk may have changed since the last refresh, same reasoning as the
        original inline version."""
        T = self.T
        self.hits_tree.delete(*self.hits_tree.get_children())
        for base_exponent in pietra:
            node = self.hits_tree.insert("", "end", text=f"10p{base_exponent}",
                                          values=("", ""), open=False, tags=("pietro",))
            self.hits_tree.insert(node, "end", text=T("common.loading"))
        self.hit_set_cache = {}

    def search_constellation(self):
        """The Search button's handler -- ALSO called directly by the Kalkulator
        konstelacji tab (via its own injected trigger_hits_search callable) once it has
        filled in hits_search_entry itself (see set_search_query()) -- so this always
        reads the query from the entry rather than taking a parameter, matching exactly
        what a real button click does regardless of which caller triggered it."""
        T = self.T
        raw = self.hits_search_entry.get().strip()
        if not raw.isdigit():
            messagebox.showerror(T("common.dialog_search_title"), T("common.error_invalid_number"))
            return
        number = int(raw)
        base_exponent = digit_count_floor(number)
        if self._is_search_busy():
            messagebox.showinfo(T("common.dialog_search_title"), T("common.search_already_running"))
            return
        if base_exponent not in list_pietra(self._get_portal_folder()):
            # No floor 10p{base_exponent} at all yet -- see the Prime numbers tab's
            # own search_prime()'s identical branch for the full reasoning; offering
            # "const" here (not "prime") means the prime window gets generated first,
            # and the re-search that follows runs the FULL const search, which can
            # itself go on to offer generating constellation hits too if that's also
            # still missing.
            outcome = self._offer_generate_missing_prime_window(base_exponent, number)
            if outcome != "launched":
                self.show_missing_result(base_exponent, number, outcome)
            return

        self.search_results_list.delete(0, "end")
        self._search_results_data = []
        self._start_search_job("const", base_exponent, number)

    def set_search_query(self, number):
        """Fills the search entry with `number` without triggering a search -- used by
        the Kalkulator konstelacji tab right before it calls search_constellation()
        itself, so the resulting search reads exactly the number the calculator
        computed."""
        self.hits_search_entry.delete(0, "end")
        self.hits_search_entry.insert(0, str(number))

    def show_missing_result(self, base_exponent, number, outcome):
        """Shared by search_constellation()'s no-floor branch and prime_atlas_v1.py's
        own _on_const_search_result() (when its prime_result-is-None branch doesn't
        launch a generation run) -- both reach here only when a "generate missing
        fragment" offer was declined or resolved as composite, so there's a result to
        show right now rather than waiting on a re-search."""
        T = self.T
        if outcome == "composite":
            self.hits_detail_text.set(
                T("const.confirmed_composite_detail", number=number, base_exponent=base_exponent))
        else:
            self.hits_detail_text.set(
                T("const.not_found_detail", number=number, base_exponent=base_exponent))
        self._reset_preview_state()
        self.hits_load_preview_btn.configure(state="disabled")

    def show_search_participation(self, base_exponent, number, prime_result, participation):
        """Called by prime_atlas_v1.py's own _on_const_search_result() once a "const"
        search job has come back with a real prime_result (found) -- builds the detail
        text + one search_results_list row per pattern `number` participates in,
        exactly as search_constellation() used to do synchronously right after calling
        find_prime_in_floor()/find_constellation_participation() directly."""
        T = self.T
        lines = [T("const.number_line", number=number),
                 T("const.found_in", name=prime_result['name'], base_exponent=base_exponent), ""]
        if not participation:
            lines.append(T("const.no_participation"))
        else:
            lines.append(T("const.participation_intro", count=len(participation)))
            for rec in sorted(participation, key=lambda r: (r["pattern"]["k"], r["pattern"]["id"])):
                pattern = rec["pattern"]
                pos_1based = rec["position"] + 1
                total_positions = len(pattern["offsets"])
                if rec["offset"] == 0:
                    lines.append(T("const.participation_base_detail",
                                    k=pattern['k'], variant=pattern['id'],
                                    pos=pos_1based, total=total_positions))
                    row_text = T("const.row_base", k=pattern['k'], variant=pattern['id'],
                                 pos=pos_1based, total=total_positions)
                else:
                    lines.append(T("const.participation_offset_detail",
                                    k=pattern['k'], variant=pattern['id'],
                                    pos=pos_1based, total=total_positions,
                                    offset=rec['offset'], base=rec['base']))
                    row_text = T("const.row_offset", k=pattern['k'], variant=pattern['id'],
                                 pos=pos_1based, total=total_positions,
                                 offset=rec['offset'], base=rec['base'])
                self.search_results_list.insert("end", row_text)
                self._search_results_data.append({
                    "base_exponent": base_exponent, "pattern": pattern, "position": rec["position"],
                    "hit_base": rec["base"],
                })
        self.hits_detail_text.set("\n".join(lines))
        self._reset_preview_state()
        self._selected_hit_path = None
        self._selected_hit_pattern = None
        self.hits_load_preview_btn.configure(state="disabled")
        self.status.set(T("const.status_search", number=number, count=len(participation)))

    def jump_to_search_match(self, base_exponent, pattern, match):
        """Called by prime_atlas_v1.py's own _on_const_search_result() when a "const"
        search that the calculator tab itself kicked off comes back with a hit for the
        EXACT pattern it was asking about -- `match` is one of `participation`'s own
        dicts (has "position"/"base" keys), same shape _on_search_result_activate()
        below already navigates from."""
        self._jump_to(base_exponent, pattern, match["base"], match["position"])

    # --- Floor tree ------------------------------------------------------------------------

    def _on_tree_open(self, _event):
        node = self.hits_tree.focus()
        self._populate_pietro_node(node)

    def _populate_pietro_node(self, node):
        children = self.hits_tree.get_children(node)
        if len(children) != 1:
            return
        T = self.T
        if self.hits_tree.item(children[0], "text") != T("common.loading"):
            return
        self.hits_tree.delete(children[0])

        base_exponent = int(self.hits_tree.item(node, "text")[3:])  # "10p{N}"
        entries = list_constellation_hits(self._get_portal_folder(), base_exponent)
        if not entries:
            self.hits_tree.insert(node, "end", text=T("const.no_hits"))
            return

        # Nested by k, each with its own subtotal -- otherwise every
        # variant is a flat sibling row ("k=7 v=1", "k=7 v=2", ...) with no way to see
        # how many k-tuples exist IN TOTAL for a given k without adding the variant
        # counts up by hand. group_constellation_hits_by_k() re-groups what
        # list_constellation_hits() already fetched -- no extra I/O, the pattern catalog
        # is small enough that every existing hit file's header is already read above.
        # The floor row itself is also updated here to the grand total across every k
        # (sum of every k-group's own subtotal) -- for the SAME reason: previously blank.
        grand_total = 0
        for k, k_total, variants in group_constellation_hits_by_k(entries):
            grand_total += k_total
            k_node = self.hits_tree.insert(
                node, "end", text=T("const.k_total", k=k, total=f"{k_total:,}"),
                values=("", ""), tags=("k_group",), open=True)
            for pattern, path, header in variants:
                label_text = f"v={pattern['id']}"
                if header is None:
                    count_str, gen_str = "?", T("primes.unreadable_header")
                else:
                    count_str = f"{header['count']:,}"
                    gen_str = header["generated_at_iso"]
                child = self.hits_tree.insert(
                    k_node, "end", text=label_text,
                    values=(count_str, gen_str), tags=("pattern",))
                self._hit_path_by_item[child] = (pattern, path, header)
        self.hits_tree.item(node, values=(f"{grand_total:,}", ""))

    def _on_tree_select(self, _event):
        selection = self.hits_tree.selection()
        if not selection:
            return
        item = selection[0]
        T = self.T
        self._reset_preview_state()
        if item not in self._hit_path_by_item:
            self.hits_load_preview_btn.configure(state="disabled")
            return
        pattern, path, header = self._hit_path_by_item[item]
        self._selected_hit_path = path
        self._selected_hit_pattern = pattern
        if header is None:
            self.hits_detail_text.set(T("primes.header_error", path=path))
            self.hits_load_preview_btn.configure(state="disabled")
            return
        offsets_str = ", ".join(f"+{d}" for d in pattern["offsets"])
        if pattern["record_digits"] is not None:
            record_line = T("const.record_known", digits=pattern['record_digits'],
                             discoverer=pattern['discoverer'], date=pattern['date'])
        else:
            record_line = T("const.record_untracked")
        self.hits_detail_text.set(
            f"{path}\n\n" +
            T("const.header_detail", k=pattern['k'], variant=pattern['id'],
              offsets=offsets_str, count=f"{header['count']:,}",
              generated=header['generated_at_iso']) +
            f"\n{record_line}"
        )
        self.hits_load_preview_btn.configure(state="normal" if header["count"] > 0 else "disabled")

    def _reset_preview_state(self):
        self.hits_preview_list.delete(0, "end")
        self._hit_values = None
        self._hit_rows = None
        self._hit_page = 0
        self._hit_total_pages = 1
        self.hits_page_label.set("")
        self.hits_prev_page_btn.configure(state="disabled")
        self.hits_next_page_btn.configure(state="disabled")
        self.hits_load_preview_btn.configure(state="normal" if self._selected_hit_path else "disabled")

    def _hit_row_formatter(self, row):
        """Each row is (value, hit_base, position, offset) -- ONE tuple element, not
        the whole tuple (that used to be a single comma-joined string per row, which
        meant selecting/copying a row always grabbed every number in the tuple at
        once). `value` is what a copy action grabs; the rest is just context."""
        T = self.T
        value, hit_base, position, offset = row
        total = len(self._selected_hit_pattern["offsets"])
        if offset == 0:
            return T("const.hit_row_base", value=value, position=position + 1, total=total)
        return T("const.hit_row_offset", value=value, position=position + 1, total=total,
                 offset=offset, hit_base=hit_base)

    def load_preview(self):
        if not self._selected_hit_path:
            return
        T = self.T
        if self._hit_values is None:
            try:
                self._hit_values = prime_sieve_v1.read_prime_window(self._selected_hit_path)
            except Exception as exc:
                messagebox.showerror(T("primes.load_preview_failed_title"), str(exc))
                self._hit_values = None
                return
            offsets = self._selected_hit_pattern["offsets"]
            self._hit_rows = [(hit_base + offset, hit_base, position, offset)
                               for hit_base in self._hit_values
                               for position, offset in enumerate(offsets)]
        self._show_hits_page(0)
        self.hits_load_preview_btn.configure(state="disabled")

    def _show_hits_page(self, page):
        if not self._hit_rows:
            return
        self._hit_page, self._hit_total_pages = self._render_page(
            self.hits_preview_list, self._hit_rows, page, self._page_size, self._hit_row_formatter)
        self._update_nav_controls(self.hits_page_label, self._hit_page,
                                   self._hit_total_pages, self.hits_prev_page_btn, self.hits_next_page_btn)

    def _prev_hits_page(self):
        self._show_hits_page(self._hit_page - 1)

    def _next_hits_page(self):
        self._show_hits_page(self._hit_page + 1)

    def _goto_hits_page(self):
        raw = self.hits_goto_entry.get().strip()
        if not raw.isdigit():
            return
        self._show_hits_page(int(raw) - 1)

    def _show_hits_context_menu(self, event):
        index = self.hits_preview_list.nearest(event.y)
        if index >= 0:
            self.hits_preview_list.selection_clear(0, "end")
            self.hits_preview_list.selection_set(index)
        self._hits_context_menu.tk_popup(event.x_root, event.y_root)

    def _copy_selected_hits_value(self):
        sel = self.hits_preview_list.curselection()
        if not sel or not self._hit_rows:
            return
        global_index = self._hit_page * self._page_size + sel[0]
        if global_index >= len(self._hit_rows):
            return
        self._copy_to_clipboard(str(self._hit_rows[global_index][0]))

    def select_pattern_in_tree(self, base_exponent, pattern):
        """Same approach as the Prime numbers tab's own select_primes_file_in_tree():
        expand the pietro node, select the matching k/variant node, and flush the
        queued <<TreeviewSelect>> event with update() so _on_tree_select runs to
        completion (resetting/populating self._selected_hit_* etc.) before the caller
        proceeds to load+jump the preview."""
        pietro_item = None
        for item in self.hits_tree.get_children(""):
            if self.hits_tree.item(item, "text") == f"10p{base_exponent}":
                pietro_item = item
                break
        if pietro_item is None:
            return
        self.hits_tree.item(pietro_item, open=True)
        self._populate_pietro_node(pietro_item)
        # Patterns are nested one level deeper, under a "k={k} (razem: N)" group node
        # (per-k subtotals -- see _populate_pietro_node) -- find that k-group first,
        # then the v=id leaf underneath it.
        k_prefix = f"k={pattern['k']}  "
        k_node = None
        for child in self.hits_tree.get_children(pietro_item):
            if self.hits_tree.item(child, "text").startswith(k_prefix):
                k_node = child
                break
        if k_node is None:
            return
        self.hits_tree.item(k_node, open=True)
        target_item = None
        label = f"v={pattern['id']}"
        for child in self.hits_tree.get_children(k_node):
            if self.hits_tree.item(child, "text") == label:
                target_item = child
                break
        if target_item is None:
            return
        self.hits_tree.see(target_item)
        self.hits_tree.selection_set(target_item)
        self.hits_tree.focus(target_item)
        self.update()

    def jump_preview_to_row(self, hit_base, position):
        """Locates the flattened row for (hit_base, position) via bisect over the
        sorted starting values (same technique as find_prime_in_floor), then jumps
        the preview to the page/row containing it and selects just that one row --
        i.e. just that one number, not the whole tuple it belongs to."""
        if not self._hit_values or not self._hit_rows or self._selected_hit_pattern is None:
            return
        hit_index = bisect.bisect_left(self._hit_values, hit_base)
        if hit_index >= len(self._hit_values) or self._hit_values[hit_index] != hit_base:
            return
        total_positions = len(self._selected_hit_pattern["offsets"])
        target_index = hit_index * total_positions + position
        if target_index >= len(self._hit_rows):
            return
        page = target_index // self._page_size
        self._show_hits_page(page)
        self.hits_load_preview_btn.configure(state="disabled")
        local = target_index - self._hit_page * self._page_size
        self.hits_preview_list.selection_clear(0, "end")
        self.hits_preview_list.selection_set(local)
        self.hits_preview_list.see(local)

    def _jump_to(self, base_exponent, pattern, hit_base, position):
        self.select_pattern_in_tree(base_exponent, pattern)
        self.load_preview()
        self.jump_preview_to_row(hit_base, position)

    def _on_search_result_activate(self, _event):
        sel = self.search_results_list.curselection()
        if not sel or sel[0] >= len(self._search_results_data):
            return
        data = self._search_results_data[sel[0]]
        self._jump_to(data["base_exponent"], data["pattern"], data["hit_base"], data["position"])
