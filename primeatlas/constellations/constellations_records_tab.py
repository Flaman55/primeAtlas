"""
constellations_records_tab.py -- ConstellationsRecordsTab, the tkinter widgets for the
Constellations tab's "Tabela rekordow" sub-tab: a pzktupel.de-style exp x variant
records table, but scanning THIS PROJECT'S OWN storage
(constellations/k{k}/variant{id}/HITS_....bin) instead of that website -- pick k, click
Skanuj, see the smallest offset found so far for each floor x variant combination (see
primeatlas/constellations/constellations.py's build_constellation_records_table() for the exact
semantics, including what the record-floor asterisk does and doesn't claim).

Unlike its two sibling sub-tabs (Magazyn/Kalkulator), this one is fully
self-contained -- its own background.PersistentWorker
(self._worker), never shared with anything else in the app (the search worker/totals
worker stay app-level specifically BECAUSE they're shared across tabs; this one never
was), so the whole worker lives here rather than being injected. Only `totals_progress`
(the shared status/progress bar widget, also used by the search and totals workers) is
injected, since that ONE widget is genuinely shared app-wide -- reusing it here avoids
adding a second progress bar just for this tab's scan/export jobs.

Double-clicking a cell drills down into the FULL list of hits behind it (all 2019
numbers for a "+23,080,007,797 (2019x)" cell, not just the smallest) in the paginated
detail panel below the tree. Export to PDF/CSV covers the same full-detail data as the
cell drill-down (one row per individual hit) rather than the compact on-screen summary,
always covering the SAME floor range as the currently displayed table
(self._last_floor_bounds, captured at scan time) -- not the live contents of the od/do
fields, in case they've been edited since the last Skanuj click. CSV streams rows one
at a time (iter_constellation_records_detail_rows()) so a range including a pattern the
scale of floor 25's k=2 (~2.16 billion hits) doesn't try to hold every row in memory at
once; PDF still needs the whole row list up front for pagination, so it refuses (with a
clear error) a range whose row count would exceed PDF_EXPORT_ROW_LIMIT instead -- see
that constant's own comment.

This is one of a few files in primeatlas/ that import tkinter -- see
primes_tab.py's own docstring for the general "pure logic elsewhere" convention this
package otherwise follows.
"""
import datetime
import os

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import pattern_catalog_v1

from ..core import background
from ..core.base_tab import BaseTab
import hit_paging

from .constellations import (
    build_constellation_records_table, build_constellation_records_detail_rows,
    iter_constellation_records_detail_rows, count_constellation_records_detail_rows,
    write_constellation_detail_rows_csv,
    render_constellation_records_pdf,
    read_hit_pattern_header, read_hit_pattern_page, hit_pattern_page_count,
    hit_pattern_actual_page_size, hit_pattern_is_paged,
)

# A PDF, unlike streamed CSV, needs every row laid out on paginated pages up front (see
# render_constellation_records_pdf()) -- so its row count can't be unbounded the way
# CSV export now is (see _job()'s own comment). 1,000,000 rows (one hit_paging page's
# worth) is still far too many for an actual PDF: render_constellation_records_pdf()'s
# own row_h=14/A4-landscape layout fits ~37 rows per page, so even ONE full hit_paging
# page (the smallest a page-range
# export can ask for once a pattern's own pages are 1,000,000 each) would render a
# ~27,000-page PDF -- not just slow, but useless once opened. 50,000 rows (~1,350
# pages) is still a big PDF but at least one that finishes rendering and opens in a
# reasonable viewer; a caller who wants more should use CSV export instead (streamed,
# no row-count limit -- see _job()'s own comment).
PDF_EXPORT_ROW_LIMIT = 50_000
from ..core.widgets import FlowRow, add_page_nav_group


def _iter_with_progress(rows, report_progress, step=100_000):
    """Wraps a per-hit row generator to call report_progress(count) every `step` rows
    as they're consumed -- lets a long CSV export drive a real DETERMINATE progress
    bar (see ConstellationsRecordsTab._start_job()'s own docstring for why: an
    indeterminate spinner for a minutes-long export looks like flickering rather
    than genuine incremental progress). step=100,000
    balances UI responsiveness against report_progress()'s cost (each call
    round-trips through PersistentWorker's own queue + the main thread's poll loop,
    see background.py) -- reporting every single row would be needless overhead at
    the scale (up to ~2.16 billion rows) this is built for."""
    count = 0
    for r in rows:
        yield r
        count += 1
        if count % step == 0:
            report_progress(count)


class ConstellationsRecordsTab(BaseTab):
    def __init__(self, parent, get_portal_folder, status_var, translator,
                 update_nav_controls, render_page, page_size, eval_quick_number,
                 totals_progress):
        """
        get_portal_folder/status_var/translator/update_nav_controls/render_page/
        page_size: same dependency-injection pattern as every other extracted tab --
        see primeatlas/primes/primes_tab.py's own docstring.

        eval_quick_number: prime_atlas_v1.py's own _eval_quick_number() -- same
        parameter as ConstellationsCalcTab's own, used here for the optional "Pietro
        od/do" floor-range fields.

        totals_progress: the app's shared status/progress bar ttk.Progressbar widget
        (constructed once, well before any tab, in __init__ -- safe to pass directly
        rather than via a deferred lambda) -- see this module's own docstring for why
        it's the one thing here that ISN'T fully self-contained.
        """
        super().__init__(parent, translator)
        self._get_portal_folder = get_portal_folder
        self.status = status_var
        self._update_nav_controls = update_nav_controls
        self._render_page = render_page
        self._page_size = page_size
        self._eval_quick_number = eval_quick_number
        self.totals_progress = totals_progress

        self._busy = False
        self._worker = background.PersistentWorker(
            self, self._job, on_result=self._on_worker_result,
            on_progress=self._on_worker_progress)

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

        # Optional on-screen-page-range scoping for BOTH export buttons above -- left
        # blank, Eksportuj PDF/CSV export the whole currently-displayed floor range
        # exactly as before; filled in (requires a cell to have been drilled into
        # first, via double-click below or Magazyn's "Eksportuj" jump -- see
        # activate_pattern_for_export()), they scope the SAME two buttons to just the
        # chosen SCREEN pages of that one pattern instead -- SAME numbering as
        # detail_nav's own "Strona X/Y" label below (self._page_size rows each), NOT
        # a whole hit-file page (hit_paging.PAGE_SIZE, up to 1,000,000 entries) -- see
        # _build_export_rows_from_current_page()'s own docstring for the on-screen vs
        # hit-file-page distinction this depends on. Scoping lives on these same two
        # buttons rather than a separate range-scoped control, so PDF export gets the
        # same range-scoping option CSV does.
        ttk.Label(top_row, text=T("const_records.export_range_label")).pack(
            side="left", padx=(16, 0))
        self.detail_export_from_entry = ttk.Entry(top_row, width=6)
        self.detail_export_from_entry.pack(side="left", padx=(4, 0))
        ttk.Label(top_row, text=T("const_records.export_range_to")).pack(
            side="left", padx=(4, 0))
        self.detail_export_to_entry = ttk.Entry(top_row, width=6)
        self.detail_export_to_entry.pack(side="left", padx=(4, 0))

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
        self.detail_page_label = tk.StringVar(value="")
        self.detail_prev_btn, self.detail_next_btn, self.detail_goto_entry = add_page_nav_group(
            detail_nav, T, self.detail_page_label,
            self._prev_detail_page, self._next_detail_page, self._goto_detail_page)

        # Real hit-file page navigation (up to hit_paging.PAGE_SIZE=1,000,000 hits per
        # page) -- separate from detail_nav above, which only paginates WITHIN
        # whichever hit-file page is currently loaded into self._detail_rows
        # (self._page_size=500-ish rows at a time). Needed so a pattern too
        # large to ever load in full (floor 25's k=2, ~2.16 billion hits / 2160 pages)
        # can still be browsed page by page instead of being stuck on page 1 forever.
        # Page-scoped export itself lives in the top_row's "Eksportuj strony od/do"
        # fields, feeding the SAME _export_pdf()/_export_csv() buttons as a whole-range
        # export -- see top_row's own construction comment.
        detail_file_nav = FlowRow(detail_frame)
        detail_file_nav.frame.pack(anchor="w", padx=4, fill="x")
        self.detail_file_page_label = tk.StringVar(value="")
        self.detail_file_prev_btn, self.detail_file_next_btn, self.detail_file_goto_entry = add_page_nav_group(
            detail_file_nav, T, self.detail_file_page_label,
            self._prev_detail_file_page, self._next_detail_file_page, self._goto_detail_file_page,
            label_width=20,
            prev_key="const_records.file_page_prev", next_key="const_records.file_page_next")

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
        self._detail_file_page_index = 0  # which hit-file page (0-based) is currently
                                           # loaded into self._detail_rows
        self._detail_file_page_count = 1  # how many hit-file pages this pattern has

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

    def _refresh_export_buttons_state(self):
        """Eksportuj PDF/CSV are usable whenever EITHER a completed scan has rows
        (self._last, for a whole-floor-range export) OR a specific pattern is active
        (self._detail_context, for a page-range export -- see _export()'s own
        docstring) -- either alone is enough, since _export() itself decides which
        mode to use from the top_row "Eksportuj strony od/do" fields at click time,
        not from which of these two is currently populated. Centralized here (rather
        than repeating the OR at every call site) since it's re-evaluated after every
        job result AND every time the drilled-into pattern changes (_load_detail_file_
        page()/_set_detail_file_nav_disabled())."""
        has_rows = bool(self._last and self._last[3])
        has_page_context = self._detail_context is not None
        enabled = "normal" if (has_rows or has_page_context) else "disabled"
        self.export_pdf_button.configure(state=enabled)
        self.export_csv_button.configure(state=enabled)

    def _start_job(self, job, status_text, total_rows=None):
        """Shared dispatch for every job this tab's worker can run (scan/export_pdf/
        export_csv/export_page_range_csv) -- mutually exclusive (one at a time, same
        busy flag/progress bar/button-disabling), so this is the one place that logic
        lives instead of being copy-pasted into each click handler.

        `total_rows`, if given (export jobs only -- a cheap header-only count the
        caller computes BEFORE dispatch, see count_constellation_records_detail_rows()/
        hit_pattern_header-based sums in the export handlers below), switches
        self.totals_progress to a real DETERMINATE bar (0..total_rows) instead of the
        indeterminate spin _start_busy_progress() gives every other job -- the
        indeterminate bar's constant bounce/reset during a real, minutes-long export
        reads as flickering rather than genuine incremental progress. `_job()`'s own
        report_progress calls (row counts
        as export proceeds) drive the bar's value from there via _on_worker_progress().
        Falls back to the indeterminate spin when total_rows is None (the "scan" job,
        which has no cheap way to know its own eventual row count up front)."""
        self._busy = True
        self.scan_button.configure(state="disabled")
        self.export_pdf_button.configure(state="disabled")
        self.export_csv_button.configure(state="disabled")
        if total_rows is not None:
            self.totals_progress.stop()
            self.totals_progress.configure(mode="determinate", maximum=max(1, total_rows), value=0)
        else:
            self._start_busy_progress()
        self.status.set(status_text)
        self._worker.submit(job)

    def _on_worker_progress(self, payload):
        """PersistentWorker's on_progress callback -- payload is the row count so far
        (an int), pushed by _job()'s report_progress() during a streamed CSV/PDF-row
        export. A no-op if the bar isn't currently in determinate mode (e.g. a stray
        progress call arriving after _stop_busy_progress() already reset it, or during
        a "scan" job, which never calls report_progress in the first place)."""
        if str(self.totals_progress["mode"]) == "determinate":
            self.totals_progress["value"] = payload

    def _job(self, job, report_progress):
        """Runs on PersistentWorker's own daemon thread. Five job shapes distinguished
        by "mode": "scan" (build_constellation_records_table -> the main tree);
        "export_csv"/"export_pdf" (whole-floor-range export, reads from disk via
        job["floor_min"]/["floor_max"]); "export_page_range_csv"/"export_page_range_pdf"
        (scoped to the on-screen list-pages of whichever pattern/hit-file-page was
        loaded when the button was clicked -- job["rows"] is already a fully-built,
        plain list of row dicts, built on the MAIN thread from self._detail_rows
        BEFORE dispatch, see _export()'s own docstring for how a caller picks between
        the two shapes: the top_row "Eksportuj strony od/do" fields being filled or
        blank -- this mode needs no disk access here at all).

        CSV (either shape) streams -- a generator for the whole-range case
        (iter_constellation_records_detail_rows()), or the already-small job["rows"]
        list for the page-scoped case -- written to disk one row at a time via
        write_constellation_detail_rows_csv(), wrapped in _iter_with_progress() to
        drive a real determinate progress bar. The whole-range generator matters most
        here: materializing every row as one big list first (the pre-paging version
        of this job) would, for a pattern the scale of floor 25's k=2 (~2.16 billion
        hits), try to hold billions of dicts in memory at once.

        PDF (either shape) needs the whole laid-out row list up front for pagination,
        so it stays bounded by REFUSING an oversized request (PDF_EXPORT_ROW_LIMIT)
        instead of streaming.

        Catches its own exceptions so a failure surfaces with the right mode/k
        context, instead of falling through to PersistentWorker's own last-resort net
        which has no way to know which request failed."""
        mode = job.get("mode", "scan")
        k = job["k"]
        floor_min = job.get("floor_min")
        floor_max = job.get("floor_max")
        portal_folder = self._get_portal_folder()
        page_scoped = mode.startswith("export_page_range_")
        try:
            if mode == "scan":
                variant_ids, variant_meta, rows = build_constellation_records_table(
                    portal_folder, k, floor_min=floor_min, floor_max=floor_max)
                return mode, k, True, (variant_ids, variant_meta, rows, floor_min, floor_max)

            if mode in ("export_pdf", "export_page_range_pdf"):
                if page_scoped:
                    detail_rows = job["rows"]
                    total_rows = len(detail_rows)
                else:
                    total_rows = count_constellation_records_detail_rows(
                        portal_folder, k, floor_min=floor_min, floor_max=floor_max)
                if total_rows > PDF_EXPORT_ROW_LIMIT:
                    return mode, k, False, ("pdf_too_large", total_rows)
                if not page_scoped:
                    _variant_ids, _variant_meta, detail_rows = build_constellation_records_detail_rows(
                        portal_folder, k, floor_min=floor_min, floor_max=floor_max)
                path = job["path"]
                self._render_detail_pdf(path, k, detail_rows)
                return mode, k, True, path

            # export_csv / export_page_range_csv
            if page_scoped:
                detail_rows = job["rows"]
            else:
                detail_rows = iter_constellation_records_detail_rows(
                    portal_folder, k, floor_min=floor_min, floor_max=floor_max)
            path = job["path"]
            write_constellation_detail_rows_csv(
                path, _iter_with_progress(detail_rows, report_progress))
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

    def _on_worker_result(self, payload, error):
        """Main-thread callback for _job -- `error` is only non-None for a genuine
        PersistentWorker-framework bug (_job already catches its own exceptions)."""
        T = self.T
        self._busy = False
        self.scan_button.configure(state="normal")
        self._stop_busy_progress()
        if error is not None:
            self._refresh_export_buttons_state()
            self.status.set(T("const_records.status_error"))
            messagebox.showerror(T("const_records.error_dialog_title"), str(error))
            return
        mode, k, ok, result_payload = payload
        if mode == "scan":
            if not ok:
                # Scan failed -- self._last (if any) still holds the last SUCCESSFUL
                # scan's data untouched, so restore the export buttons to match it
                # instead of leaving them disabled from _start_job() (which disables
                # both up front, since a scan and an export can't usefully run at the
                # same time).
                self._refresh_export_buttons_state()
                self.status.set(T("const_records.status_error"))
                messagebox.showerror(T("const_records.error_dialog_title"), result_payload)
                return
            variant_ids, variant_meta, rows, floor_min, floor_max = result_payload
            self._show_results(k, variant_ids, variant_meta, rows, floor_min, floor_max)
        else:  # export_pdf / export_csv / export_page_range_pdf / export_page_range_csv
            self._refresh_export_buttons_state()
            button_label = T(
                "const_records.export_pdf_button" if "pdf" in mode
                else "const_records.export_csv_button")
            if not ok:
                self.status.set(T("const_records.status_error"))
                if isinstance(result_payload, tuple) and result_payload[0] == "pdf_too_large":
                    _reason, total_rows = result_payload
                    messagebox.showerror(
                        T("const_records.error_dialog_title"),
                        T("const_records.export_pdf_too_large",
                          count=f"{total_rows:,}", limit=f"{PDF_EXPORT_ROW_LIMIT:,}"))
                else:
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
        and loads the hits behind it (not just the smallest offset the tree cell shows)
        into the paginated detail panel below.

        Reads via read_hit_pattern_header()/read_hit_pattern_page() (paging-transparent
        -- see primeatlas/constellations/constellations.py's own module-level helpers and
        prime_sieve/hit_paging.py) instead of a bare prime_sieve_v1.read_prime_window()
        on hit_file_path(): a pattern this large (dense k=2 on a high floor -- see
        hit_paging.py's own docstring for the real crash this is about) may have been
        migrated to pages, in which case the original single file no longer exists at
        all, AND a full decode of even an unmigrated multi-hundred-million-entry file
        on THIS (the GUI) thread is exactly what used to freeze the whole app on
        double-click. Only the FIRST hit-file page (bounded to
        hit_paging.PAGE_SIZE entries, currently 1,000,000) is ever loaded here -- for
        the vast majority of patterns (never paged, far fewer hits than that) this is
        the exact same "whole file" as before; for a paged one, the label makes clear
        only a first slice is shown and points at CSV/PDF export (which streams every
        page instead of holding them all in memory -- see build_constellation_records_
        detail_rows()) for the rest.

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
        portal_folder = self._get_portal_folder()
        header = read_hit_pattern_header(portal_folder, base_exponent, k, vid)
        if header is None or header["count"] == 0:
            self._detail_rows = []
            self._detail_context = None
            self._set_detail_file_nav_disabled()
            self.detail_label_var.set(T("const_records.detail_empty", exp=base_exponent, id=vid))
            self._show_detail_page(0)
            return
        # A pattern this large that HASN'T been migrated to pages yet still has its
        # whole hit count in ONE file -- read_hit_pattern_page() page 0 would be a full,
        # unbounded prime_sieve_v1.read_prime_window() decode on THIS (the GUI) thread
        # (see hit_pattern_is_paged()'s own docstring for the real freeze this guard is
        # about: k=2 on floor 25, ~2.15 billion hits, hung the whole app on a plain
        # double-click). Refuse outright rather than attempt it -- there is no safe
        # bounded read until prime_sieve/hit_paging.py's migrate_hit_file_to_pages()
        # has actually run for this pattern.
        if (header["count"] > hit_paging.PAGE_SIZE
                and not hit_pattern_is_paged(portal_folder, base_exponent, k, vid)):
            self._detail_rows = []
            self._detail_context = None
            self._set_detail_file_nav_disabled()
            self.detail_label_var.set(T(
                "const_records.detail_too_large", exp=base_exponent, id=vid,
                count=f"{header['count']:,}"))
            self._show_detail_page(0)
            return
        self._detail_context = {"base_exponent": base_exponent, "pattern": pattern}
        self._detail_file_page_count = hit_pattern_page_count(portal_folder, base_exponent, k, vid)
        self._load_detail_file_page(base_exponent, k, vid, 0)

    def _set_detail_file_nav_disabled(self):
        """Resets the hit-file page navigator to its empty/disabled state -- shared by
        _on_cell_activate()'s empty/too-large early returns above, neither of which
        has a real pattern to page through. Callers already set self._detail_context
        to None before calling this; _refresh_export_buttons_state() re-evaluates the
        Eksportuj PDF/CSV buttons against that (they stay enabled if a PRIOR scan
        still has rows, disabled only if neither that nor a pattern is available)."""
        self._detail_file_page_index = 0
        self._detail_file_page_count = 1
        self.detail_file_page_label.set("")
        self.detail_file_prev_btn.configure(state="disabled")
        self.detail_file_next_btn.configure(state="disabled")
        self._refresh_export_buttons_state()

    def _load_detail_file_page(self, base_exponent, k, vid, page_index):
        """Loads hit-file page `page_index` (bounded to hit_paging.PAGE_SIZE entries,
        see read_hit_pattern_page()'s own docstring) into self._detail_rows, resets the
        small in-memory UI pager (self._page_size-row chunks) back to its own page 0,
        and refreshes the file-page nav label/buttons + the detail title. Shared by
        _on_cell_activate() (initial load, always page 0) and
        _prev_detail_file_page()/_next_detail_file_page() (paging through the real
        file) so both go through the exact same bounded read + label logic."""
        T = self.T
        portal_folder = self._get_portal_folder()
        try:
            values = read_hit_pattern_page(portal_folder, base_exponent, k, vid, page_index)
        except Exception as exc:
            messagebox.showerror(T("const_records.error_dialog_title"), str(exc))
            return
        base = 10 ** base_exponent
        self._detail_rows = [(v, v - base) for v in values]
        self._detail_file_page_index = page_index
        pattern = self._detail_context["pattern"] if self._detail_context else {"id": vid}
        self.detail_label_var.set(T(
            "const_records.detail_title_file_page", exp=base_exponent, id=pattern.get("id", vid),
            page=page_index + 1, page_total=self._detail_file_page_count,
            count=f"{len(values):,}"))
        self.detail_file_page_label.set(T(
            "const_records.file_page_label", page=page_index + 1, total=self._detail_file_page_count))
        self.detail_file_prev_btn.configure(state="normal" if page_index > 0 else "disabled")
        self.detail_file_next_btn.configure(
            state="normal" if page_index < self._detail_file_page_count - 1 else "disabled")
        self._refresh_export_buttons_state()
        self._show_detail_page(0)

    def _prev_detail_file_page(self):
        if self._detail_context is None or self._detail_file_page_index <= 0:
            return
        ctx = self._detail_context
        self._load_detail_file_page(
            ctx["base_exponent"], ctx["pattern"]["k"], ctx["pattern"]["id"],
            self._detail_file_page_index - 1)

    def _next_detail_file_page(self):
        if self._detail_context is None or self._detail_file_page_index >= self._detail_file_page_count - 1:
            return
        ctx = self._detail_context
        self._load_detail_file_page(
            ctx["base_exponent"], ctx["pattern"]["k"], ctx["pattern"]["id"],
            self._detail_file_page_index + 1)

    def _goto_detail_file_page(self):
        raw = self.detail_file_goto_entry.get().strip()
        if self._detail_context is None or not raw.isdigit():
            return
        ctx = self._detail_context
        page_index = max(0, min(int(raw) - 1, self._detail_file_page_count - 1))
        self._load_detail_file_page(
            ctx["base_exponent"], ctx["pattern"]["k"], ctx["pattern"]["id"], page_index)

    def activate_pattern_for_export(self, base_exponent, pattern, page_index):
        """Sets this tab up to browse/export ONE specific pattern's page range, without
        needing a prior Skanuj/tree click -- called by prime_atlas_v1.py's app-level
        jump wiring when Magazyn's own "Eksportuj" button (ConstellationsHitsTab, see
        its own docstring) hands off to here instead of duplicating a whole separate
        export mechanism there.

        Sets self._detail_context directly (everything _on_cell_activate() would
        normally derive from a clicked tree cell is already known here -- `pattern`
        is the full catalog dict, not just an id), loads `page_index` (the hit-file
        page) via _load_detail_file_page(), and pre-fills the top_row "Eksportuj
        strony od/do" fields to "1"/"1" -- _load_detail_file_page() always resets the
        on-screen list pager to its own page 0 on a fresh load (see its own
        docstring), so "1" (on-screen page 1) is always the right default here
        regardless of which hit-file page was loaded; the user can widen the range
        there before clicking Eksportuj PDF/CSV.

        Also pre-fills "Pietro od/do" to this exact floor -- these
        aren't read by the page-range export path itself, but matter the moment the
        user clears "Eksportuj strony od/do" to fall back to a whole-range export
        instead: left blank (the pre-jump default), that fallback would silently mean
        "every floor in the whole archive," not "just the floor I jumped from"."""
        self.k_combo.set(str(pattern["k"]))
        self.floor_from_entry.delete(0, "end")
        self.floor_from_entry.insert(0, str(base_exponent))
        self.floor_to_entry.delete(0, "end")
        self.floor_to_entry.insert(0, str(base_exponent))
        self._detail_context = {"base_exponent": base_exponent, "pattern": pattern}
        self._detail_file_page_count = hit_pattern_page_count(
            self._get_portal_folder(), base_exponent, pattern["k"], pattern["id"])
        self._load_detail_file_page(base_exponent, pattern["k"], pattern["id"], page_index)
        self.detail_export_from_entry.delete(0, "end")
        self.detail_export_from_entry.insert(0, "1")
        self.detail_export_to_entry.delete(0, "end")
        self.detail_export_to_entry.insert(0, "1")

    def _parse_export_page_range(self):
        """Reads the top_row "Eksportuj strony od/do" entries (see their own
        construction comment): both blank means "no scoping" (the export buttons fall
        back to their original whole-floor-range behavior) -- returns None. Both
        filled, 1-based in the UI -- SAME numbering as detail_nav's "Strona X/Y" label
        above the drill-down list, i.e. on-screen list-pages of whichever pattern/
        hit-file-page is currently loaded (see _build_export_rows_from_current_page()'s
        own docstring for why THAT granularity, not a whole hit-file page) -- returns
        (ui_from, ui_to) as 0-based ints. Raises ValueError (callers show
        const_records.export_range_invalid) for anything else: only one filled,
        non-numeric, or from > to."""
        from_text = self.detail_export_from_entry.get().strip()
        to_text = self.detail_export_to_entry.get().strip()
        if not from_text and not to_text:
            return None
        ui_from = int(from_text) - 1
        ui_to = int(to_text) - 1
        if ui_from > ui_to:
            raise ValueError("ui_from > ui_to")
        return ui_from, ui_to

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
        (position 0 -- see _on_cell_activate's read via read_hit_pattern_page(), which
        returns exactly those base values), so the jump always targets position 0,
        never needing to look up which tuple position this row is."""
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
        self._copy_to_clipboard(str(self._detail_rows[global_index][0]))

    def _export_pdf(self):
        self._export("pdf")

    def _export_csv(self):
        self._export("csv")

    def _build_export_rows_from_current_page(self, ui_from, ui_to):
        """Builds full CSV/PDF row dicts for ON-SCREEN list-pages [ui_from, ui_to]
        (0-based, the SAME numbering as detail_nav's "Strona X/Y" label above the
        list) of the CURRENTLY LOADED hit-file page (self._detail_rows) -- NOT a
        whole hit-file page (up to hit_paging.PAGE_SIZE, 1,000,000, entries), and NOT
        the whole pattern.

        Scoped to on-screen pages (self._page_size rows each) rather than the much
        coarser hit-file page unit, since the latter would make even a single-page
        request 1,000,000 rows -- far too coarse for a range meant to select
        individual screenfuls of rows.

        Clamped into [0, len(self._detail_rows)) -- an out-of-range ui_from yields an
        empty list rather than raising."""
        ctx = self._detail_context
        portal_folder = self._get_portal_folder()
        base_exponent, pattern = ctx["base_exponent"], ctx["pattern"]
        header = read_hit_pattern_header(portal_folder, base_exponent, pattern["k"], pattern["id"])
        total_count = header["count"] if header is not None else len(self._detail_rows)
        record_digits = pattern["record_digits"]
        is_record_floor = record_digits is not None and base_exponent == record_digits - 1
        page_size = hit_pattern_actual_page_size(
            portal_folder, base_exponent, pattern["k"], pattern["id"])
        file_page_offset = self._detail_file_page_index * page_size

        start = max(0, ui_from * self._page_size)
        end = min(len(self._detail_rows), (ui_to + 1) * self._page_size)
        rows = []
        for local_index in range(start, end):
            number, offset = self._detail_rows[local_index]
            rows.append({
                "base_exponent": base_exponent, "variant_id": pattern["id"],
                "offset": offset, "number": number,
                "position_in_file": file_page_offset + local_index,
                "count_in_file": total_count, "is_record_floor": is_record_floor,
            })
        return rows

    def _export(self, fmt):
        """Shared handler for both "Eksportuj PDF" and "Eksportuj CSV" -- each is
        either a WHOLE-floor-range export (self._last, the old behavior, when the
        top_row "Eksportuj strony od/do" fields are blank) or scoped to the on-screen
        list-pages [od, do] of whichever pattern/hit-file-page is currently loaded
        (self._detail_context/self._detail_rows, when those fields are filled -- see
        _build_export_rows_from_current_page()'s own docstring). One method covers
        both formats and both scopes rather than a separate range-scoped button, so
        PDF export gets the same range-scoping option CSV does."""
        if self._busy:
            return
        T = self.T
        try:
            page_range = self._parse_export_page_range()
        except ValueError:
            messagebox.showerror(T("const_records.error_dialog_title"),
                                  T("const_records.export_range_invalid"))
            return
        if page_range is not None and self._detail_context is None:
            messagebox.showerror(T("const_records.error_dialog_title"),
                                  T("const_records.export_range_needs_pattern"))
            return
        if page_range is None and not self._last:
            return
        portal_folder = self._get_portal_folder()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        button_key = "const_records.export_pdf_button" if fmt == "pdf" else "const_records.export_csv_button"

        if page_range is not None:
            ctx = self._detail_context
            k, vid, base_exponent = ctx["pattern"]["k"], ctx["pattern"]["id"], ctx["base_exponent"]
            ui_from, ui_to = page_range
            default_name = (f"constellation_k{k}_v{vid}_10p{base_exponent}_"
                             f"screenpages{ui_from + 1}-{ui_to + 1}_{timestamp}.{fmt}")
            rows = self._build_export_rows_from_current_page(ui_from, ui_to)
            total_rows = len(rows)
            job = {"mode": f"export_page_range_{fmt}", "k": k, "rows": rows}
            status_text = T("const_records.status_exporting_range", fmt=fmt.upper())
        else:
            k = self._last[0]
            floor_min, floor_max = self._last_floor_bounds
            default_name = f"constellation_records_k{k}_{timestamp}.{fmt}"
            total_rows = count_constellation_records_detail_rows(
                portal_folder, k, floor_min=floor_min, floor_max=floor_max)
            job = {"mode": f"export_{fmt}", "k": k, "floor_min": floor_min, "floor_max": floor_max}
            status_text = T("const_records.status_exporting", k=k)

        filetypes = ([("PDF", "*.pdf")] if fmt == "pdf" else [("CSV", "*.csv")]) + \
            [(T("common.all_files"), "*.*")]
        path = filedialog.asksaveasfilename(
            title=T(button_key), initialdir=portal_folder, initialfile=default_name,
            defaultextension=f".{fmt}", filetypes=filetypes)
        if not path:
            return
        job["path"] = path
        # PDF (whole-range OR on-screen-page-scoped) still needs the whole row list
        # laid out up front for pagination -- report_progress() during the write
        # itself (what total_rows otherwise drives, see _iter_with_progress()) isn't
        # wired for PDF, so the indeterminate spin (total_rows=None) stays correct
        # there; only CSV streams and can show a real determinate bar.
        self._start_job(job, status_text, total_rows=(total_rows if fmt == "csv" else None))
