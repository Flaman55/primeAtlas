"""
research_goldbach_tab.py -- ResearchGoldbachTab, the Research tab's Goldbach sub-tab:
the structural-window check ("Check window") with its results table and CSV export,
composed with one mixin per window or job area:

  - goldbach_viz_section.py        Visualize Toplevel: both-base window diagram, sourced
                                   from the on-disk archive (Lean's
                                   additiveSelfContained_of_hasGoldbachRep)
  - goldbach_decompose_section.py  "Show all decompositions" detail Toplevel
  - goldbach_worker_section.py     the background job and its result/progress callbacks

The tab owns its background.PersistentWorker (self._goldbach_worker) end to end, same as
ConstellationsRecordsTab (see primeatlas/constellations/constellations_records_tab.py's
docstring for the general reasoning).

Launching a "generate the missing range" run when a Visualize/decompose job hits
MissingStorageRangeError needs the app-level quick-gen planning/launch machinery and the
pending-retry slot shared with the Generation tab, so that one call is injected as
`offer_generate_missing_range(op, payload)`. retry_viz()/retry_decompose() are the two
public methods the Generation tab's _on_loop_finished calls once that run completes, so
it never reaches into this tab's pagination/current-n state directly.
"""
import csv
import datetime
import webbrowser

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from ..core import background
from ..core.base_tab import BaseTab
from ..core.ui_state import remember
from ..core.widgets import StripedTreeview
from .goldbach_paging import GOLDBACH_CASCADE_ROW_CAP, GOLDBACH_DECOMPOSE_ROW_CAP
from .goldbach_viz_section import GoldbachVizSection
from .goldbach_decompose_section import GoldbachDecomposeSection
from .goldbach_worker_section import GoldbachWorkerSection

GOLDBACH_LEAN_REPO_URL = (
    "https://github.com/Flaman55/RelMathApps/tree/main/number_theory/"
    "structural_Goldbach/lean/StructuralGoldbach"
)  # points at the Lean 4 formalization backing this tab (additiveSelfContained_of_
    # hasGoldbachRep, windowCovered, the whole reduction chain).


class ResearchGoldbachTab(GoldbachVizSection, GoldbachDecomposeSection,
                          GoldbachWorkerSection, BaseTab):
    def __init__(self, parent, get_portal_folder, status_var, translator,
                 update_nav_controls, eval_quick_number, page_size,
                 totals_progress, offer_generate_missing_range):
        """
        get_portal_folder/status_var/translator/update_nav_controls/eval_quick_number/
        page_size/totals_progress: same dependency-injection pattern as every other
        extracted tab -- see primeatlas/primes/primes_tab.py's own docstring, and
        constellations_records_tab.py's for why totals_progress (a shared widget) is
        passed directly rather than via a deferred lambda.

        offer_generate_missing_range: PortalBrowserApp's own
        _goldbach_offer_generate_missing_range(op, payload) -- see this module's own
        docstring for why launching that specific generation run stays app-level.
        """
        super().__init__(parent, translator)
        self._get_portal_folder = get_portal_folder
        self.status = status_var
        self._update_nav_controls = update_nav_controls
        self._eval_quick_number = eval_quick_number
        self._page_size = page_size
        self.totals_progress = totals_progress
        self._offer_generate_missing_range = offer_generate_missing_range

        # Goldbach structural-window worker: own PersistentWorker, pure Python, no
        # WSL round trip (see goldbach_window.py's own header comment). Progress
        # ticks from the "viz" op's both_base_window_rows() call are relayed through
        # report_progress -- see _goldbach_job's own docstring.
        self._goldbach_busy = False
        self._goldbach_worker = background.PersistentWorker(
            self, self._goldbach_job, on_result=self._on_goldbach_worker_result,
            on_progress=self._on_goldbach_worker_progress)
        # Visualize Toplevel is created lazily (see _goldbach_ensure_viz_window)
        # and reused across clicks -- None here means "not open yet".
        self._goldbach_viz_win = None
        # Pagination state for the two independently-browsable sections of the
        # diagram (see _goldbach_queue_viz / _on_goldbach_viz_chip_prev etc.):
        # row_page drives a fresh backend goldbach_window_rows() call per page,
        # chip_page is a pure client-side slice of the last result's
        # old_base_primes (already fully computed, no backend cost to page
        # through). current_n/last_result let the Prev/Next handlers act without
        # the caller having to thread n and the previous result through again.
        self._goldbach_viz_row_page = 0
        self._goldbach_viz_chip_page = 0
        self._goldbach_viz_current_n = None
        self._goldbach_viz_last_result = None
        # "Decompose number" detail Toplevel (all_decompositions of one specific n
        # against the currently-open window's Pmax) -- same lazy-create-and-reuse
        # pattern as _goldbach_viz_win, see _goldbach_ensure_decompose_window.
        self._goldbach_decompose_win = None
        # Pagination state for the decompose detail list -- same backend-call-per-
        # page shape as the sums row nav above (a large n can have tens of
        # thousands of pairs, e.g. n~=9999992 yields 53364 pairs for one single
        # n). current_n/current_pmax let Prev/Next/goto re-issue a
        # job for the SAME target without the caller re-supplying them each time;
        # last_result caches just enough (count) to clamp a goto target locally.
        self._goldbach_decompose_page = 0
        self._goldbach_decompose_current_n = None
        self._goldbach_decompose_current_pmax = None
        self._goldbach_decompose_last_result = None
        self._goldbach_last_result = None

        self._build_widgets()

    def retry_viz(self):
        """Called by PortalBrowserApp's _on_loop_finished once a "generate the
        missing range" run it launched for a "viz" job (see
        _goldbach_offer_generate_missing_range) completes -- re-reads n/row-page/
        od-do fresh from the still-open Visualize Toplevel's own entries via
        _goldbach_queue_viz, same as the row Prev/Next handlers do."""
        if self._goldbach_viz_current_n is not None:
            self._goldbach_queue_viz(self._goldbach_viz_current_n, reset_page=False)

    def retry_decompose(self):
        """Mirrors retry_viz() for a "decompose" job -- reuses self._goldbach_
        decompose_current_n/current_pmax/page, already set by the original
        _on_goldbach_viz_decompose click and left untouched by the failed
        attempt (see _goldbach_queue_decompose_page's docstring)."""
        if self._goldbach_decompose_current_n is not None:
            self._goldbach_queue_decompose_page()

    def _build_widgets(self):
        """Goldbach structural-window check. The field is labeled "n" (an arbitrary
        integer) -- Pmax is DERIVED as the largest prime <= n (goldbach_window.
        largest_prime_le), matching the paper's own convention that Pmax must itself
        be a genuine prime, without requiring the person to type a prime by hand.
        "Check window" checks windowCovered(Pmax) -- every even n in [4, 2*Pmax]
        must be a sum of two primes -- exactly as formalized in Structural.lean /
        "A Structural Sieve for Goldbach's Conjecture" (see primeatlas/
        goldbach_window.py's own header for the full term-by-term correspondence,
        numerically verified there against the paper's own worked examples). The
        checkbox switches between "touch_once" (stop at the first witness per n --
        windowCovered/hasGoldbachRep, the paper's ACTIVE line of proof, coincides
        with buildableFromBase(Pmax, n) on this window) and "all_combinations" (full
        repCount(n) per n -- the paper's counting framing, kept there only for
        comparison since it inherits the parity problem). "Visualize" draws the
        SAME [4, 2*Pmax] window (never a separate cascade step -- see
        goldbach_window.window_rows' own docstring), sourced from the on-disk
        archive. Both run on the shared _goldbach_worker (background.PersistentWorker
        -- see _goldbach_job's own docstring), the same shared-worker-thread pattern
        every job dispatcher in this app uses."""
        T = self.T
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=(10, 4))
        ttk.Label(top, text=T("research_goldbach.field_n")).pack(side="left")
        self.goldbach_n_entry = ttk.Entry(top, width=20)
        self.goldbach_n_entry.pack(side="left", padx=(6, 16))
        self.goldbach_n_entry.insert(0, "1000")

        self.goldbach_touch_once_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            top, text=T("research_goldbach.touch_once_checkbox"),
            variable=self.goldbach_touch_once_var).pack(side="left")
        remember("research.goldbach.n", self.goldbach_n_entry)
        remember("research.goldbach.touch_once", self.goldbach_touch_once_var)

        button_row = ttk.Frame(self)
        button_row.pack(fill="x", padx=6, pady=(0, 8))
        self.goldbach_run_button = ttk.Button(
            button_row, text=T("research_goldbach.run_button"),
            command=self._on_goldbach_run)
        self.goldbach_run_button.pack(side="left")
        self.goldbach_export_button = ttk.Button(
            button_row, text=T("research_goldbach.export_csv_button"),
            command=self._on_goldbach_export_csv, state="disabled")
        self.goldbach_export_button.pack(side="left", padx=(8, 0))
        self.goldbach_visualize_button = ttk.Button(
            button_row, text=T("research_goldbach.visualize_button"),
            command=self._on_goldbach_visualize)
        self.goldbach_visualize_button.pack(side="left", padx=(8, 0))

        ttk.Label(self, text=T("research_goldbach.viz_hint"),
                  wraplength=760, justify="left", style="Hint.TLabel").pack(
            anchor="w", padx=6, pady=(0, 4))

        ttk.Label(self, text=T("research_goldbach.hint"),
                  wraplength=760, justify="left", style="Hint.TLabel").pack(
            anchor="w", padx=6, pady=(0, 8))

        lean_link = ttk.Label(
            self, text=T("research_goldbach.lean_repo_link"),
            foreground="#1d4ed8", cursor="hand2")
        lean_link.pack(anchor="w", padx=6, pady=(0, 8))
        lean_link.bind("<Button-1>", self._on_goldbach_open_lean_repo)

        self.goldbach_summary_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.goldbach_summary_var,
                  wraplength=760, justify="left").pack(anchor="w", padx=6, pady=(0, 8))

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        columns = ("n", "p", "q", "rep_count")
        self.goldbach_results_tree = StripedTreeview(
            tree_frame, columns=columns, show="headings", height=16)
        self.goldbach_results_tree.heading("n", text=T("research_goldbach.col_n"))
        self.goldbach_results_tree.heading("p", text=T("research_goldbach.col_p"))
        self.goldbach_results_tree.heading("q", text=T("research_goldbach.col_q"))
        self.goldbach_results_tree.heading(
            "rep_count", text=T("research_goldbach.col_rep_count"))
        self.goldbach_results_tree.column("n", width=110, anchor="e")
        self.goldbach_results_tree.column("p", width=110, anchor="e")
        self.goldbach_results_tree.column("q", width=110, anchor="e")
        self.goldbach_results_tree.column("rep_count", width=110, anchor="e")
        gvsb = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self.goldbach_results_tree.yview)
        self.goldbach_results_tree.configure(yscrollcommand=gvsb.set)
        self.goldbach_results_tree.pack(side="left", fill="both", expand=True)
        gvsb.pack(side="right", fill="y")
        self.goldbach_results_tree.bind(
            "<Double-1>", self._on_goldbach_row_double_click)

        self._goldbach_last_result = None

    def _on_goldbach_open_lean_repo(self, _event=None):
        """Opens GOLDBACH_LEAN_REPO_URL in the system's default browser -- the only
        external link in this tab, so a plain webbrowser.open() (no confirmation
        dialog) is fine; it's a read-only navigation, not an action with side
        effects on the user's own accounts or data."""
        webbrowser.open(GOLDBACH_LEAN_REPO_URL)

    def _goldbach_parse_n_from(self, entry):
        """Parses an "n" field via _eval_quick_number (so expressions like 10**4
        work here too, same as the primesieve calculator's and Primality tests's
        fields), requiring an integer >= 2 (so a largest-prime-<=n exists to derive
        Pmax from -- see goldbach_window.largest_prime_le's own docstring). Takes
        the Entry widget explicitly so both the main tab's field and the
        Visualize window's OWN field (see _goldbach_ensure_viz_window) share one
        validation path."""
        n = self._eval_quick_number(entry.get())
        if n is None or n < 2:
            raise ValueError(self.T("research_goldbach.error_n_invalid"))
        return n

    def _goldbach_parse_n(self):
        return self._goldbach_parse_n_from(self.goldbach_n_entry)

    def _on_goldbach_run(self):
        T = self.T
        if self._goldbach_busy:
            return
        try:
            n = self._goldbach_parse_n()
        except ValueError as e:
            messagebox.showerror(T("research_goldbach.error_dialog_title"), str(e))
            return
        mode = "touch_once" if self.goldbach_touch_once_var.get() else "all_combinations"
        self._goldbach_set_busy(True)
        self._goldbach_worker.submit({"op": "window", "n": n, "mode": mode})

    def _on_goldbach_visualize(self):
        """"Visualize" button -- derives Pmax = largest prime <= n (starting from
        the SAME n as the "Check window" field) and draws the window Lean's
        additiveSelfContained_of_hasGoldbachRep proves unconditionally
        (goldbach_window.both_base_window_rows -- see that module's own
        docstring), sourcing is_prime from the on-disk archive
        (read_is_prime_from_storage) rather than a fresh sieve. Opens (or reuses,
        if already open) a Toplevel with its OWN od/do range + check button, so
        different n values can be explored there directly without bouncing back to
        this tab each time (see _goldbach_ensure_viz_window). "od" is left at
        whatever the Toplevel's own field already holds (its own default is 4,
        set once at window creation) -- only "do" is overwritten from this tab's
        n (see _goldbach_queue_viz's own docstring for why od/do form one
        validated range)."""
        T = self.T
        try:
            n = self._goldbach_parse_n()
        except ValueError as e:
            messagebox.showerror(T("research_goldbach.error_dialog_title"), str(e))
            return
        win = self._goldbach_ensure_viz_window()
        self.goldbach_viz_n_entry.delete(0, "end")
        self.goldbach_viz_n_entry.insert(0, str(n))
        win.deiconify()
        win.lift()
        self._goldbach_queue_viz(n)

    def _goldbach_widget_configure(self, attr_name, **kwargs):
        """configure() an optional, possibly-stale widget attribute without
        blowing up -- `hasattr(self, attr_name)` alone isn't enough here: closing
        the Visualize or decompose Toplevel (see their own _on_close handlers)
        destroys every Tk widget inside it, but does NOT clear out the Python
        attribute still pointing at that now-dead widget (only the *_win attribute
        itself gets reset to None). Configuring a destroyed widget raises
        tk.TclError -- caught and ignored here, since "the window this button
        lived in is gone" is a perfectly normal thing to happen mid-flight (a
        worker job queued before the window was closed, whose result now arrives
        after). Without this guard, that TclError propagates out of whichever
        caller stopped it from reaching the code that resets self._goldbach_busy
        back to False, permanently disabling every Goldbach button on the tab
        (e.g. opening and closing "Show all decompositions" leaves that button
        greyed out, and the sums-grid "Next" too)."""
        widget = getattr(self, attr_name, None)
        if widget is None:
            return
        try:
            widget.configure(**kwargs)
        except tk.TclError:
            pass

    def _goldbach_set_busy(self, busy):
        self._goldbach_busy = busy
        state = "disabled" if busy else "normal"
        self.goldbach_run_button.configure(state=state)
        self._goldbach_widget_configure("goldbach_viz_check_button", state=state)
        self._goldbach_widget_configure("goldbach_viz_decompose_button", state=state)
        # Only force-DISABLE the row nav buttons here -- their correct enabled
        # state at the bounds (first/last page) is recalculated by
        # _update_nav_controls once a fresh result is drawn, so re-enabling them
        # unconditionally here would briefly un-disable Prev on page 0. Chip nav
        # buttons aren't gated by busy at all -- paging them is pure client-side
        # redraw, no worker round-trip (see _on_goldbach_viz_chip_prev/_next).
        if busy:
            self._goldbach_widget_configure("goldbach_viz_row_prev_btn", state="disabled")
            self._goldbach_widget_configure("goldbach_viz_row_next_btn", state="disabled")
            self._goldbach_widget_configure("goldbach_decompose_prev_btn", state="disabled")
            self._goldbach_widget_configure("goldbach_decompose_next_btn", state="disabled")
        if busy:
            self._start_busy_progress()
            self._goldbach_viz_progress_set(indeterminate=True)
            self.status.set(self.T("research_goldbach.status_computing"))
        else:
            self._stop_busy_progress()
            self._goldbach_viz_progress_set(value=0)

    def _goldbach_refresh_nav_buttons(self):
        """Restores BOTH the Visualize sums-grid Prev/Next and the decompose
        window's own Prev/Next from their last-drawn results. Needed because
        _goldbach_set_busy(True) force-disables ALL FOUR of these buttons for
        ANY Goldbach job (window/viz/decompose share one busy flag and one
        worker thread), but each pair's correct re-enabled state is normally
        only recalculated by its OWN show_* function's _update_nav_controls
        call -- _goldbach_show_decomposition_detail never touches the
        sums-grid buttons, and _goldbach_show_window_visualization never
        touches the decompose buttons. Since only ONE show_* function runs per
        completed job, the OTHER pair would otherwise stay disabled from the
        busy=True phase -- e.g. clicking
        "Show all decompositions" (a decompose job) leaves the Visualize's
        own "Window sums" Next button greyed out even though that
        viz result's true last-known page state hasn't changed at all.
        Called unconditionally after every busy=False transition, regardless
        of which op just completed -- each block below is a harmless no-op
        (re-deriving the same state _update_nav_controls would already have
        set) when its own op is the one that just finished."""
        if self._goldbach_viz_last_result is not None:
            result = self._goldbach_viz_last_result
            row_page = result.get("row_page", 0)
            total_row_pages = max(
                1, -(-result["segment_size"] // GOLDBACH_CASCADE_ROW_CAP))
            try:
                self._update_nav_controls(
                    self.goldbach_viz_row_page_label, row_page, total_row_pages,
                    self.goldbach_viz_row_prev_btn, self.goldbach_viz_row_next_btn)
            except (tk.TclError, AttributeError):
                pass
        if self._goldbach_decompose_last_result is not None:
            result = self._goldbach_decompose_last_result
            page = result.get("page", 0)
            total_pages = max(
                1, -(-result["count"] // GOLDBACH_DECOMPOSE_ROW_CAP))
            try:
                self._update_nav_controls(
                    self.goldbach_decompose_page_label, page, total_pages,
                    self.goldbach_decompose_prev_btn, self.goldbach_decompose_next_btn)
            except (tk.TclError, AttributeError):
                pass

    def _goldbach_show_result(self, result):
        T = self.T
        self._goldbach_last_result = result
        self.goldbach_results_tree.delete(*self.goldbach_results_tree.get_children())
        rows = result["rows"]
        truncated = len(rows) > self._page_size
        for row in rows[:self._page_size]:
            p = row["p"] if row["p"] is not None else T("research_goldbach.no_witness")
            q = row["q"] if row["q"] is not None else ""
            rc = row["rep_count"] if row["rep_count"] is not None else "-"
            self.goldbach_results_tree.insert("", "end", values=(row["n"], p, q, rc))
        if result["covered"]:
            summary = T(
                "research_goldbach.summary_covered", n=result["n"], pmax=result["pmax"],
                n_checked=result["n_checked"],
                window_max=result["window_max"], elapsed=f"{result['elapsed']:.3f}")
        else:
            summary = T(
                "research_goldbach.summary_void", n=result["n"], pmax=result["pmax"],
                counterexamples=", ".join(str(x) for x in result["counterexamples"]),
                window_max=result["window_max"], elapsed=f"{result['elapsed']:.3f}")
        if truncated:
            summary += " " + T(
                "research_goldbach.summary_truncated", shown=self._page_size, total=len(rows))
        self.goldbach_summary_var.set(summary)
        self.goldbach_export_button.configure(state="normal")

    def _on_goldbach_row_double_click(self, event):
        """Drill-down for "all_combinations" mode -- shows the FULL deduplicated
        witness-pair list for the double-clicked n (the results table only shows
        the smallest pair + count, same drill-down spirit as the Constellations ->
        Records table tab's hit-list dialog). No-op in "touch_once" mode (pairs
        is None there by design -- see goldbach_window.py's own docstring)."""
        T = self.T
        sel = self.goldbach_results_tree.selection()
        if not sel or not self._goldbach_last_result:
            return
        n = self.goldbach_results_tree.item(sel[0])["values"][0]
        row = next(
            (r for r in self._goldbach_last_result["rows"] if r["n"] == n), None)
        if row is None or row["pairs"] is None:
            return
        pairs_text = "\n".join(f"{p} + {q} = {n}" for p, q in row["pairs"])
        messagebox.showinfo(
            T("research_goldbach.pairs_dialog_title", n=n),
            pairs_text or T("research_goldbach.no_witness"))

    def _on_goldbach_export_csv(self):
        if not self._goldbach_last_result:
            return
        T = self.T
        result = self._goldbach_last_result
        default_name = (
            f"goldbach_window_n{result['n']}_pmax{result['pmax']}_{result['mode']}_"
            f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        path = filedialog.asksaveasfilename(
            title=T("research_goldbach.export_csv_button"),
            initialdir=self._get_portal_folder(),
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), (T("common.all_files"), "*.*")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["n", "p", "q", "rep_count", "pairs"])
            for row in result["rows"]:
                pairs_str = (
                    "; ".join(f"{p}+{q}" for p, q in row["pairs"])
                    if row["pairs"] else "")
                writer.writerow([
                    row["n"],
                    row["p"] if row["p"] is not None else "",
                    row["q"] if row["q"] is not None else "",
                    row["rep_count"] if row["rep_count"] is not None else "",
                    pairs_str])
        self.status.set(T("research_goldbach.status_exported", path=path))
