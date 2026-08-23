"""
constellations_records_tab.py -- ConstellationsRecordsTab, the tkinter widgets for the
Constellations tab's "Tabela rekordow" sub-tab: a pzktupel.de-style exp x variant
records table, but scanning THIS PROJECT'S OWN storage
(constellations/k{k}/variant{id}/HITS_....bin) instead of that website -- pick k, click
Skanuj, see the smallest offset found so far for each floor x variant combination (see
primeatlas/constellations.py's build_constellation_records_table() for the exact
semantics, including what the record-floor asterisk does and doesn't claim).

Extracted from prime_atlas_v1.py during the refactor branch's Faza 3 (tab-by-tab
backend/UI split, 2026-08-23). Unlike its two sibling sub-tabs (Magazyn/Kalkulator),
this one is fully self-contained -- its own background.PersistentWorker
(self._worker), never shared with anything else in the app (the search worker/totals
worker stay app-level specifically BECAUSE they're shared across tabs; this one never
was), so the whole worker lives here rather than being injected. Only `totals_progress`
(the shared status/progress bar widget, also used by the search and totals workers) is
injected, since that ONE widget is genuinely shared app-wide -- reusing it here avoids
adding a second progress bar just for this tab's scan/export jobs.

Double-clicking a cell drills down into the FULL list of hits behind it (all 2019
numbers for a "+23,080,007,797 (2019x)" cell, not just the smallest) in the paginated
detail panel below the tree. Export to PDF/CSV pulls the SAME full-detail data as the
cell drill-down (one row per individual hit, via build_constellation_records_detail_
rows()) rather than the compact on-screen summary, always covering the SAME floor
range as the currently displayed table (self._last_floor_bounds, captured at scan
time) -- not the live contents of the od/do fields, in case they've been edited since
the last Skanuj click.

This is one of a few files in primeatlas/ that import tkinter -- see
primes_tab.py's own docstring for the general "pure logic elsewhere" convention this
package otherwise follows.
"""
import csv
import datetime
import os

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import pattern_catalog_v1
import prime_sieve_v1

from . import background
from .constellations import (
    build_constellation_records_table, build_constellation_records_detail_rows,
    hit_file_path, render_constellation_records_pdf,
)
from .widgets import FlowRow


class ConstellationsRecordsTab(ttk.Frame):
    def __init__(self, parent, get_portal_folder, status_var, translator,
                 update_nav_controls, render_page, page_size, eval_quick_number,
                 totals_progress):
        """
        get_portal_folder/status_var/translator/update_nav_controls/render_page/
        page_size: same dependency-injection pattern as every other extracted tab --
        see primeatlas/primes_tab.py's own docstring.

        eval_quick_number: prime_atlas_v1.py's own _eval_quick_number() -- same
        parameter as ConstellationsCalcTab's own, used here for the optional "Pietro
        od/do" floor-range fields.

        totals_progress: the app's shared status/progress bar ttk.Progressbar widget
        (constructed once, well before any tab, in __init__ -- safe to pass directly
        rather than via a deferred lambda) -- see this module's own docstring for why
        it's the one thing here that ISN'T fully self-contained.
        """
        super().__init__(parent)
        self._get_portal_folder = get_portal_folder
        self.status = status_var
        self.T = translator
        self._update_nav_controls = update_nav_controls
        self._render_page = render_page
        self._page_size = page_size
        self._eval_quick_number = eval_quick_number
        self.totals_progress = totals_progress

        self._busy = False
        self._worker = background.PersistentWorker(
            self, self._job, on_result=self._on_worker_result)

        self._build_widgets()

    def _build_widgets(self):
        T = self.T
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=12, pady=12)

        top_row = ttk.Frame(container)
        top_row.pack(fill="x", pady=(0, 8))
        ttk.Label(top_row, text=T("const_records.field_k")).pack(side="left")
        self.k_combo = ttk.Combobox(
            top_row, state="readonly", width=6,
            values=[str(k) for k in pattern_catalog_v1.all_k()])
        self.k_combo.pack(side="left", padx=(6, 16))
        ttk.Label(top_row, text=T("const_records.field_floor_from")).pack(side="left")
        self.floor_from_entry = ttk.Entry(top_row, width=8)
        self.floor_from_entry.pack(side="left", padx=(6, 12))
        ttk.Label(top_row, text=T("const_records.field_floor_to")).pack(side="left")
        self.floor_to_entry = ttk.Entry(top_row, width=8)
        self.floor_to_entry.pack(side="left", padx=(6, 16))
        self.scan_button = ttk.Button(
            top_row, text=T("const_records.scan_button"), command=self._on_scan_clicked)
        self.scan_button.pack(side="left")
        self.export_pdf_button = ttk.Button(
            top_row, text=T("const_records.export_pdf_button"),
            command=self._export_pdf, state="disabled")
        self.export_pdf_button.pack(side="left", padx=(16, 0))
        self.export_csv_button = ttk.Button(
            top_row, text=T("const_records.export_csv_button"),
            command=self._export_csv, state="disabled")
        self.export_csv_button.pack(side="left", padx=(6, 0))

        ttk.Label(container, text=T("const_records.hint"), wraplength=760,
                  justify="left", foreground="#555").pack(anchor="w", pady=(0, 8))

        # Vertical split: table on top, full-hit-list drill-down for whatever cell was
        # last double-clicked on the bottom. Plain tk.PanedWindow, not ttk.Panedwindow
        # -- ttk's sash is a near-invisible 1-2px line on most themes, which read as
        # "no divider at all, can't resize" (user report); tk's PanedWindow exposes
        # sashwidth/sashrelief directly, giving an actually visible grab bar.
        # stretch="never" on the tree pane + a dynamic tree height (see
        # _rebuild_tree's row_count param) means the top pane's natural size already
        # tracks how many floors are in the table.
        paned = tk.PanedWindow(container, orient="vertical", sashwidth=6,
                                sashrelief="raised", sashpad=1, bg="#c8c8c8")
        paned.pack(fill="both", expand=True)

        self.tree_frame = ttk.Frame(paned)
        paned.add(self.tree_frame, minsize=60, stretch="never")
        self.tree = None  # built fresh per scan -- see _rebuild_tree(), column count
                           # depends on how many variants k has
        self.tree_vsb = None  # its scrollbars, tracked separately so they can be
        self.tree_hsb = None  # destroyed alongside the tree on rebuild
        self._last = None  # (k, variant_ids, variant_meta, rows) from the most
                            # recently finished scan
        self._last_floor_bounds = (None, None)  # (floor_min, floor_max) used by that
                                                  # same scan -- exports reuse this
                                                  # exact scope rather than re-reading
                                                  # the od/do fields
        self._rebuild_tree([])

        detail_frame = ttk.Frame(paned)
        paned.add(detail_frame, minsize=100, stretch="always")
        self.detail_label_var = tk.StringVar(value=T("const_records.detail_hint"))
        ttk.Label(detail_frame, textvariable=self.detail_label_var,
                  anchor="w").pack(fill="x", padx=4, pady=(2, 4))

        detail_nav = FlowRow(detail_frame)
        detail_nav.frame.pack(anchor="w", padx=4, fill="x")
        self.detail_prev_btn = ttk.Button(
            detail_nav.frame, text=T("common.prev_page"),
            command=self._prev_detail_page, state="disabled")
        detail_nav.add(self.detail_prev_btn)
        self.detail_page_label = tk.StringVar(value="")
        detail_nav.add(ttk.Label(detail_nav.frame, textvariable=self.detail_page_label,
                                  width=16, anchor="center"))
        self.detail_next_btn = ttk.Button(
            detail_nav.frame, text=T("common.next_page"),
            command=self._next_detail_page, state="disabled")
        detail_nav.add(self.detail_next_btn)
        detail_nav.add(ttk.Label(detail_nav.frame, text=T("common.page_prefix")), padx_left=10)
        self.detail_goto_entry = ttk.Entry(detail_nav.frame, width=6)
        detail_nav.add(self.detail_goto_entry, padx_left=4)
        self.detail_goto_entry.bind("<Return>", lambda _e: self._goto_detail_page())
        detail_nav.add(ttk.Button(detail_nav.frame, text=T("common.goto"),
                                   command=self._goto_detail_page), padx_left=4)

        detail_list_frame = ttk.Frame(detail_frame)
        detail_list_frame.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self.detail_list = tk.Listbox(detail_list_frame, font=("Consolas", 9))
        detail_vsb = ttk.Scrollbar(detail_list_frame, orient="vertical",
                                    command=self.detail_list.yview)
        self.detail_list.configure(yscrollcommand=detail_vsb.set)
        self.detail_list.pack(side="left", fill="both", expand=True)
        detail_vsb.pack(side="right", fill="y")

        self.detail_list.bind("<Control-c>", lambda _e: self._copy_selected_detail_value())
        self.detail_list.bind("<Button-3>", self._show_detail_context_menu)
        self.detail_list.bind("<Double-Button-1>", self._on_detail_activate)
        self._detail_context_menu = tk.Menu(self, tearoff=0)
        self._detail_context_menu.add_command(
            label=T("common.copy"), command=self._copy_selected_detail_value)

        self._detail_rows = []  # [(number, offset), ...] for whichever cell was last
                                 # double-clicked
        self._detail_context = None  # {"base_exponent":, "pattern":} for that same
                                      # cell -- needed by the jump-to-Magazyn handler
        self._detail_page = 0
        self._detail_total_pages = 1

        if pattern_catalog_v1.all_k():
            self.k_combo.current(0)

    def _rebuild_tree(self, variant_ids, row_count=0):
        """(Re)builds self.tree with one column per variant id, plus the fixed
        leading 'exp' column -- a plain ttk.Treeview can't have its column SET
        changed after construction, and different k values have different variant
        counts, so the tree is destroyed and recreated on every scan rather than
        trying to reuse one fixed-shape widget. Both scrollbars are destroyed and
        recreated right alongside it. Every column is stretch=False (fixed width)
        with an added horizontal scrollbar, same fix as the Benchmark tab's tree.
        `row_count` sizes the Treeview's own `height` to match (capped at 14, floored
        at 3)."""
        if self.tree is not None:
            self.tree.destroy()
        if self.tree_vsb is not None:
            self.tree_vsb.destroy()
        if self.tree_hsb is not None:
            self.tree_hsb.destroy()
        T = self.T
        columns = ("exp",) + tuple(f"v{vid}" for vid in variant_ids)
        height = max(3, min(row_count, 14)) if row_count else 3
        tree = ttk.Treeview(
            self.tree_frame, columns=columns, show="headings", height=height)
        tree.heading("exp", text=T("const_records.col_exp"))
        tree.column("exp", width=70, anchor="e", stretch=False)
        for vid in variant_ids:
            tree.heading(f"v{vid}", text=T("const_calc.variant_label", id=vid))
            tree.column(f"v{vid}", width=190, anchor="w", stretch=False)
        vsb = ttk.Scrollbar(self.tree_frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(self.tree_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        tree.pack(side="left", fill="both", expand=True)
        tree.bind("<Double-Button-1>", self._on_cell_activate)
        self.tree = tree
        self.tree_vsb = vsb
        self.tree_hsb = hsb

    def _on_scan_clicked(self):
        if self._busy:
            return
        T = self.T
        k_str = self.k_combo.get()
        if not k_str:
            messagebox.showerror(T("const_records.error_dialog_title"), T("const_calc.error_no_pattern"))
            return
        k = int(k_str)
        floor_min = self._eval_quick_number(self.floor_from_entry.get())
        floor_max = self._eval_quick_number(self.floor_to_entry.get())
        if floor_min is not None and floor_max is not None and floor_min > floor_max:
            messagebox.showerror(T("const_records.error_dialog_title"), T("const_records.error_invalid_range"))
            return
        self._start_job(
            {"mode": "scan", "k": k, "floor_min": floor_min, "floor_max": floor_max},
            T("const_records.status_scanning", k=k))

    def _start_job(self, job, status_text):
        """Shared dispatch for every job this tab's worker can run (scan/export_pdf/
        export_csv) -- all three are mutually exclusive (one at a time, same busy
        flag/progress bar/button-disabling), so this is the one place that logic
        lives instead of being copy-pasted into each of the three click handlers."""
        self._busy = True
        self.scan_button.configure(state="disabled")
        self.export_pdf_button.configure(state="disabled")
        self.export_csv_button.configure(state="disabled")
        self.totals_progress.stop()
        self.totals_progress.configure(mode="indeterminate")
        self.totals_progress.start(80)
        self.status.set(status_text)
        self._worker.submit(job)

    def _job(self, job, report_progress):
        """Runs on PersistentWorker's own daemon thread. Three job shapes
        distinguished by "mode": "scan" (build_constellation_records_table -> the main
        tree), "export_pdf"/"export_csv" (build_constellation_records_detail_rows ->
        a flat per-hit row list, then handed to the matching renderer below). Catches
        its own exceptions so a failure surfaces with the right mode/k context,
        instead of falling through to PersistentWorker's own last-resort net which has
        no way to know which request failed."""
        mode = job.get("mode", "scan")
        k = job["k"]
        floor_min = job.get("floor_min")
        floor_max = job.get("floor_max")
        portal_folder = self._get_portal_folder()
        try:
            if mode == "scan":
                variant_ids, variant_meta, rows = build_constellation_records_table(
                    portal_folder, k, floor_min=floor_min, floor_max=floor_max)
                return mode, k, True, (variant_ids, variant_meta, rows, floor_min, floor_max)
            else:  # export_pdf / export_csv
                _variant_ids, _variant_meta, detail_rows = build_constellation_records_detail_rows(
                    portal_folder, k, floor_min=floor_min, floor_max=floor_max)
                path = job["path"]
                if mode == "export_pdf":
                    self._render_detail_pdf(path, k, detail_rows)
                else:
                    self._write_detail_csv(path, detail_rows)
                return mode, k, True, path
        except Exception as e:  # noqa: BLE001 -- must never kill this thread
            return mode, k, False, str(e)

    def _render_detail_pdf(self, path, k, detail_rows):
        """Runs on the worker thread (called from _job) -- builds the PDF fieldnames/
        rows from build_constellation_records_detail_rows()' flat per-hit dicts and
        hands them to render_constellation_records_pdf(), same low-level writer the
        old summary export used. One row per individual hit, so a floor with 2019
        hits produces 2019 PDF rows/however many continuation pages that takes."""
        fieldnames = ["exp", "id", "offset", "number"]
        pdf_rows = [{
            "exp": f"10p{r['base_exponent']}",
            "id": r["variant_id"],
            "offset": f"+{r['offset']:,}" + (" *" if r["is_record_floor"] else ""),
            "number": r["number"],
        } for r in detail_rows]
        render_constellation_records_pdf(path, k, fieldnames, pdf_rows, translator=self.T)

    def _write_detail_csv(self, path, detail_rows):
        """Runs on the worker thread (called from _job) -- plain csv.DictWriter, one
        row per individual hit."""
        fieldnames = ["exp", "variant_id", "offset", "number",
                      "position_in_file", "count_in_file", "is_record_floor"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in detail_rows:
                writer.writerow({
                    "exp": f"10p{r['base_exponent']}",
                    "variant_id": r["variant_id"],
                    "offset": r["offset"],
                    "number": r["number"],
                    "position_in_file": r["position_in_file"],
                    "count_in_file": r["count_in_file"],
                    "is_record_floor": r["is_record_floor"],
                })

    def _on_worker_result(self, payload, error):
        """Main-thread callback for _job -- `error` is only non-None for a genuine
        PersistentWorker-framework bug (_job already catches its own exceptions)."""
        T = self.T
        self._busy = False
        self.scan_button.configure(state="normal")
        self.totals_progress.stop()
        self.totals_progress.configure(mode="determinate", maximum=1, value=0)
        if error is not None:
            has_rows = bool(self._last and self._last[3])
            self.export_pdf_button.configure(state="normal" if has_rows else "disabled")
            self.export_csv_button.configure(state="normal" if has_rows else "disabled")
            self.status.set(T("const_records.status_error"))
            messagebox.showerror(T("const_records.error_dialog_title"), str(error))
            return
        mode, k, ok, result_payload = payload
        if mode == "scan":
            if not ok:
                # Scan failed -- self._last (if any) still holds the last SUCCESSFUL
                # scan's data untouched, so restore the export buttons to match it
                # instead of leaving them disabled from _start_job() (which disables
                # all three buttons up front, since a scan and an export can't
                # usefully run at the same time).
                has_rows = bool(self._last and self._last[3])
                self.export_pdf_button.configure(state="normal" if has_rows else "disabled")
                self.export_csv_button.configure(state="normal" if has_rows else "disabled")
                self.status.set(T("const_records.status_error"))
                messagebox.showerror(T("const_records.error_dialog_title"), result_payload)
                return
            variant_ids, variant_meta, rows, floor_min, floor_max = result_payload
            self._show_results(k, variant_ids, variant_meta, rows, floor_min, floor_max)
        else:  # export_pdf / export_csv
            has_rows = bool(self._last and self._last[3])
            self.export_pdf_button.configure(state="normal" if has_rows else "disabled")
            self.export_csv_button.configure(state="normal" if has_rows else "disabled")
            button_label = T("const_records.export_pdf_button" if mode == "export_pdf"
                              else "const_records.export_csv_button")
            if not ok:
                self.status.set(T("const_records.status_error"))
                messagebox.showerror(T("const_records.error_dialog_title"), result_payload)
                return
            path = result_payload
            self.status.set(T("bench.status_saved", path=path))
            messagebox.showinfo(button_label, T("bench.saved_dialog", path=path))

    def _show_results(self, k, variant_ids, variant_meta, rows, floor_min, floor_max):
        T = self.T
        self._last = (k, variant_ids, variant_meta, rows)
        self._last_floor_bounds = (floor_min, floor_max)
        self._rebuild_tree(variant_ids, row_count=len(rows))
        for row in rows:
            values = [f"10p{row['base_exponent']}"]
            for vid in variant_ids:
                cell = row["cells"].get(vid)
                if cell is None:
                    values.append("-")
                else:
                    text = f"+{cell['offset']:,} ({cell['count']}x)"
                    if cell["is_record_floor"]:
                        text += " *"
                    values.append(text)
                # iid = the floor number itself (unique -- one row per floor), so a
                # cell double-click can recover which floor was clicked directly from
                # identify_row() without a separate item->floor lookup table.
            self.tree.insert("", "end", iid=str(row["base_exponent"]), values=tuple(values))
        has_rows = bool(rows)
        self.export_pdf_button.configure(state="normal" if has_rows else "disabled")
        self.export_csv_button.configure(state="normal" if has_rows else "disabled")
        self.status.set(T(
            "const_records.status_done" if has_rows else "const_records.status_no_hits",
            k=k, count=len(rows)))
        # The tree was just torn down and rebuilt -- any iid the detail panel was
        # showing no longer exists, so reset it rather than leaving a stale list on
        # screen that no longer corresponds to anything selectable.
        self._detail_rows = []
        self._detail_context = None
        self.detail_label_var.set(T("const_records.detail_hint"))
        self._show_detail_page(0)

    def _on_cell_activate(self, event):
        """Double-click drill-down: identifies which (floor, variant) cell was clicked
        and loads the FULL list of hits behind it (not just the smallest offset the
        tree cell shows) into the paginated detail panel below.

        Stashes (base_exponent, pattern) in self._detail_context -- not just the raw
        values -- so a later double-click on one of the resulting rows
        (_on_detail_activate) knows which floor/pattern that row belongs to without
        having to re-derive it from the label text."""
        T = self.T
        tree = self.tree
        if tree.identify_region(event.x, event.y) != "cell":
            return
        row_id = tree.identify_row(event.y)
        col_id = tree.identify_column(event.x)  # "#1" = exp, "#2".. = variants
        if not row_id or not col_id or self._last is None:
            return
        try:
            base_exponent = int(row_id)
            col_index = int(col_id[1:]) - 1  # 0-based into the columns tuple
        except (ValueError, IndexError):
            return
        k, variant_ids, variant_meta, _rows = self._last
        vi = col_index - 1  # columns[0] is "exp" -- skip it, no cell data there
        if vi < 0 or vi >= len(variant_ids):
            return
        vid = variant_ids[vi]
        pattern = variant_meta[vid]
        path = hit_file_path(self._get_portal_folder(), base_exponent, k, vid)
        if not os.path.exists(path):
            self._detail_rows = []
            self._detail_context = None
            self.detail_label_var.set(T("const_records.detail_empty", exp=base_exponent, id=vid))
            self._show_detail_page(0)
            return
        try:
            values = prime_sieve_v1.read_prime_window(path)
        except Exception as exc:
            messagebox.showerror(T("const_records.error_dialog_title"), str(exc))
            return
        base = 10 ** base_exponent
        self._detail_rows = [(v, v - base) for v in values]
        self._detail_context = {"base_exponent": base_exponent, "pattern": pattern}
        self.detail_label_var.set(
            T("const_records.detail_title", exp=base_exponent, id=vid, count=len(values)))
        self._show_detail_page(0)

    def bind_jump_to_hits(self, jump_to_hits):
        """Registers the callable used by _on_detail_activate() to jump into the
        Magazyn tab -- injected via a setter rather than the constructor because
        prime_atlas_v1.py's own _build_constellations_section() constructs this tab
        (and its sibling ConstellationsHitsTab) in a fixed order, and this callable
        needs to reach the Magazyn tab's own widget/sub-notebook-selection logic (all
        app-level, see that method's own comment) -- exactly the same deferred-wiring
        need PrimesTab's constructor covers with a lambda instead, kept as an explicit
        setter here since it is the ONLY app-level callback this otherwise fully
        self-contained tab needs."""
        self._jump_to_hits = jump_to_hits

    def _on_detail_activate(self, event):
        """Double-click a hit in the drill-down list: jumps to the Constellations
        tab's Magazyn sub-tab, expands/selects the exact floor+variant node there, and
        scrolls its own hits preview straight to this number -- the same navigation
        the Kalkulator konstelacji's 'Szukaj zaznaczoną liczbę' button already does,
        just triggered from here instead.

        Each row here is a hit file's raw stored value, i.e. a tuple's BASE element
        (position 0 -- see _on_cell_activate's read of prime_sieve_v1.read_prime_window,
        which returns exactly those base values), so the jump always targets position
        0, never needing to look up which tuple position this row is."""
        sel = self.detail_list.curselection()
        if not sel or not self._detail_rows or self._detail_context is None:
            return
        global_index = self._detail_page * self._page_size + sel[0]
        if global_index >= len(self._detail_rows):
            return
        hit_base, _offset = self._detail_rows[global_index]
        ctx = self._detail_context
        jump_to_hits = getattr(self, "_jump_to_hits", None)
        if jump_to_hits is not None:
            jump_to_hits(ctx["base_exponent"], ctx["pattern"], hit_base, 0)

    def _detail_row_formatter(self, row):
        number, offset = row
        return self.T("const_records.detail_row", number=f"{number:,}", offset=f"{offset:,}")

    def _show_detail_page(self, page):
        if not self._detail_rows:
            self.detail_list.delete(0, "end")
            self.detail_page_label.set("")
            self.detail_prev_btn.configure(state="disabled")
            self.detail_next_btn.configure(state="disabled")
            return
        self._detail_page, self._detail_total_pages = self._render_page(
            self.detail_list, self._detail_rows, page, self._page_size, self._detail_row_formatter)
        self._update_nav_controls(
            self.detail_page_label, self._detail_page, self._detail_total_pages,
            self.detail_prev_btn, self.detail_next_btn)

    def _prev_detail_page(self):
        self._show_detail_page(self._detail_page - 1)

    def _next_detail_page(self):
        self._show_detail_page(self._detail_page + 1)

    def _goto_detail_page(self):
        raw = self.detail_goto_entry.get().strip()
        if not raw.isdigit():
            return
        self._show_detail_page(int(raw) - 1)

    def _show_detail_context_menu(self, event):
        index = self.detail_list.nearest(event.y)
        if index >= 0:
            self.detail_list.selection_clear(0, "end")
            self.detail_list.selection_set(index)
        self._detail_context_menu.tk_popup(event.x_root, event.y_root)

    def _copy_selected_detail_value(self):
        sel = self.detail_list.curselection()
        if not sel or not self._detail_rows:
            return
        global_index = self._detail_page * self._page_size + sel[0]
        if global_index >= len(self._detail_rows):
            return
        self.clipboard_clear()
        self.clipboard_append(str(self._detail_rows[global_index][0]))

    def _export_pdf(self):
        if not self._last or self._busy:
            return
        T = self.T
        k = self._last[0]
        default_name = (f"constellation_records_k{k}_"
                         f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
        path = filedialog.asksaveasfilename(
            title=T("const_records.export_pdf_button"),
            initialdir=self._get_portal_folder(),
            initialfile=default_name,
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf"), (T("common.all_files"), "*.*")])
        if not path:
            return
        floor_min, floor_max = self._last_floor_bounds
        self._start_job(
            {"mode": "export_pdf", "k": k, "floor_min": floor_min, "floor_max": floor_max,
             "path": path},
            T("const_records.status_exporting", k=k))

    def _export_csv(self):
        if not self._last or self._busy:
            return
        T = self.T
        k = self._last[0]
        default_name = (f"constellation_records_k{k}_"
                         f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        path = filedialog.asksaveasfilename(
            title=T("const_records.export_csv_button"),
            initialdir=self._get_portal_folder(),
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), (T("common.all_files"), "*.*")])
        if not path:
            return
        floor_min, floor_max = self._last_floor_bounds
        self._start_job(
            {"mode": "export_csv", "k": k, "floor_min": floor_min, "floor_max": floor_max,
             "path": path},
            T("const_records.status_exporting", k=k))
