"""
research_goldbach_tab.py -- ResearchGoldbachTab, the tkinter widgets for the Research
tab's Goldbach sub-tab: structural-window check ("Sprawdz okno"), the on-disk-magazyn-
sourced "Wizualizacja" diagram (both-base [4, Pmax+GOLDBACH_BOTH_BASE_PMIN] window,
per Lean's additiveSelfContained_of_hasGoldbachRep), and the exhaustive "Rozloz liczbe"
decomposition detail window.

Extracted from prime_atlas_v1.py during the refactor branch's Faza 3 (tab-by-tab
backend/UI split, 2026-08-23). Fully self-contained, same precedent as
ConstellationsRecordsTab (confirmed exclusive to this one sub-tab): owns its own
background.PersistentWorker (self._goldbach_worker) end to end -- see
primeatlas/constellations_records_tab.py's own docstring for the general reasoning.

The ONE piece that genuinely can't move here: launching a "generate the missing range"
run in response to a Wizualizacja/decompose job hitting MissingStorageRangeError needs
prime_atlas_v1.py's own quick-gen planning/launch machinery (self._loop_runner,
_quick_gen_plan_literal_range, _launch_direct_window_range) and its
_pending_goldbach_retry_op slot (read back by _on_loop_finished once that generation
run completes) -- all app-level state shared with the Generation tab, not this tab's
own. That one call stays at the app level, injected here as a single
`offer_generate_missing_range(op, payload)` callable; retry_viz()/retry_decompose()
are the two small public methods _on_loop_finished calls back into once generation
finishes, so it never has to reach into this tab's private pagination/current-n state
directly.
"""
import csv
import datetime
import webbrowser

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from . import background
from .base_tab import BaseTab
from .goldbach_window import (
    check_window as goldbach_check_window,
    all_decompositions as goldbach_all_decompositions,
    both_base_window_rows as goldbach_both_base_window_rows,
    BOTH_BASE_PMAX_CEILING as GOLDBACH_BOTH_BASE_PMAX_CEILING,
    BOTH_BASE_PMIN as GOLDBACH_BOTH_BASE_PMIN,
    largest_prime_le as goldbach_largest_prime_le,
    sieve_is_prime as goldbach_sieve_is_prime,
)
from .research_goldbach import read_is_prime_from_storage, MissingStorageRangeError

GOLDBACH_VIZ_ROWS_PER_COL = 14  # per-n decomposition cards drawn in ONE column of the
                                  # Wizualizacja diagram before wrapping to a new
                                  # column -- see _goldbach_show_window_visualization's
                                  # multi-column layout, which fills the window's width
                                  # instead of piling every row into one narrow strip
                                  # with empty space beside it.
GOLDBACH_VIZ_MAX_COLS = 3  # cap on how many columns the card grid wraps into, so a
                             # huge window doesn't stretch the diagram absurdly wide.
GOLDBACH_CASCADE_ROW_CAP = GOLDBACH_VIZ_ROWS_PER_COL * GOLDBACH_VIZ_MAX_COLS
    # PAGE SIZE for the per-n decomposition rows, one backend goldbach_window_rows()
    # call per page (see row_offset there) -- the coverage verdict and counterexample
    # list are always computed over the FULL window regardless of which page is
    # requested. Prev/Next buttons in the Wizualizacja window (see
    # _on_goldbach_viz_row_prev/_next) step through pages of this size, per Artur's
    # request for the same kind of navigation used elsewhere for large lists (Primes
    # tab preview, benchmark log, etc. -- see _update_nav_controls).
GOLDBACH_VIZ_CHIP_ROWS_PER_PAGE = 6  # old-base prime chips: how many CHIP ROWS (not
    # individual chips -- chip_cols varies with Pmax's digit count) are shown per page
    # before Prev/Next must be used. Purely a client-side page (old_base_primes is
    # already fully computed by the backend), unlike row pagination above which needs
    # a fresh backend call per page.
GOLDBACH_DECOMPOSE_ROW_CAP = 300  # defensive cap on how many (p, q) pairs the "Rozloz
    # liczbe" detail window displays (see goldbach_all_decompositions + _goldbach_show_
    # decomposition_detail) -- the old_base_sufficient verdict and total count are
    # always computed over the FULL scan regardless of this cap, only the displayed
    # rows are truncated.

GOLDBACH_LEAN_REPO_URL = (
    "https://github.com/Flaman55/RelMathApps/tree/main/number_theory/"
    "structural_Goldbach/lean/StructuralGoldbach"
)  # points at the Lean 4 formalization backing this tab (additiveSelfContained_of_
    # hasGoldbachRep, windowCovered, the whole reduction chain) -- Artur, 2026-08-17:
    # wired in once this repo path was confirmed current (SelfContainment.lean synced
    # over and pushed, see project memory/commit history for that sync).


class ResearchGoldbachTab(BaseTab):
    def __init__(self, parent, get_portal_folder, status_var, translator,
                 update_nav_controls, eval_quick_number, page_size,
                 totals_progress, offer_generate_missing_range):
        """
        get_portal_folder/status_var/translator/update_nav_controls/eval_quick_number/
        page_size/totals_progress: same dependency-injection pattern as every other
        extracted tab -- see primeatlas/primes_tab.py's own docstring, and
        constellations_records_tab.py's for why totals_progress (a shared widget) is
        passed directly rather than via a deferred lambda.

        offer_generate_missing_range: prime_atlas_v1.py's own
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
        # Wizualizacja Toplevel is created lazily (see _goldbach_ensure_viz_window)
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
        # "Rozloz liczbe" detail Toplevel (all_decompositions of one specific n
        # against the currently-open window's Pmax) -- same lazy-create-and-reuse
        # pattern as _goldbach_viz_win, see _goldbach_ensure_decompose_window.
        self._goldbach_decompose_win = None
        # Pagination state for the decompose detail list -- same backend-call-per-
        # page shape as the sums row nav above (a large n can have tens of
        # thousands of pairs, see Artur's own n~=9999992 screenshot: 53364 pairs
        # for one single n). current_n/current_pmax let Prev/Next/goto re-issue a
        # job for the SAME target without the caller re-supplying them each time;
        # last_result caches just enough (count) to clamp a goto target locally.
        self._goldbach_decompose_page = 0
        self._goldbach_decompose_current_n = None
        self._goldbach_decompose_current_pmax = None
        self._goldbach_decompose_last_result = None
        self._goldbach_last_result = None

        self._build_widgets()

    def retry_viz(self):
        """Called by prime_atlas_v1.py's _on_loop_finished once a "generate the
        missing range" run it launched for a "viz" job (see
        _goldbach_offer_generate_missing_range) completes -- re-reads n/row-page/
        od-do fresh from the still-open Wizualizacja Toplevel's own entries via
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
        "Sprawdz okno" checks windowCovered(Pmax) -- every even n in [4, 2*Pmax]
        must be a sum of two primes -- exactly as formalized in Structural.lean /
        "A Structural Sieve for Goldbach's Conjecture" (see primeatlas/
        goldbach_window.py's own header for the full term-by-term correspondence,
        numerically verified there against the paper's own worked examples). The
        checkbox switches between "touch_once" (stop at the first witness per n --
        windowCovered/hasGoldbachRep, the paper's ACTIVE line of proof, coincides
        with buildableFromBase(Pmax, n) on this window) and "all_combinations" (full
        repCount(n) per n -- the paper's counting framing, kept there only for
        comparison since it inherits the parity problem). "Wizualizacja" draws the
        SAME [4, 2*Pmax] window (never a separate cascade step -- see
        goldbach_window.window_rows' own docstring), sourced from the on-disk
        magazyn. Both run on the shared _goldbach_worker (background.PersistentWorker
        -- see _goldbach_job's own docstring), the same shared-worker-thread pattern
        every job dispatcher in this app uses since Faza 1's background-job
        consolidation."""
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
                  wraplength=760, justify="left", foreground="#555").pack(
            anchor="w", padx=6, pady=(0, 4))

        ttk.Label(self, text=T("research_goldbach.hint"),
                  wraplength=760, justify="left", foreground="#555").pack(
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
        self.goldbach_results_tree = ttk.Treeview(
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
        work here too, same as the primesieve calculator's and Testy pierwszosci's
        fields), requiring an integer >= 2 (so a largest-prime-<=n exists to derive
        Pmax from -- see goldbach_window.largest_prime_le's own docstring). Takes
        the Entry widget explicitly so both the main tab's field and the
        Wizualizacja window's OWN field (see _goldbach_ensure_viz_window) share one
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
        """"Wizualizacja" button -- derives Pmax = largest prime <= n (starting from
        the SAME n as the "Sprawdz okno" field) and draws the window Lean's
        additiveSelfContained_of_hasGoldbachRep proves unconditionally
        (goldbach_window.both_base_window_rows -- see that module's own
        docstring), sourcing is_prime from the on-disk magazyn
        (read_is_prime_from_storage) rather than a fresh sieve. Opens (or reuses,
        if already open) a Toplevel with its OWN od/do range + check button, so
        different n values can be explored there directly without bouncing back to
        this tab each time (see _goldbach_ensure_viz_window). "od" is left at
        whatever the Toplevel's own field already holds (its own default is 4,
        set once at window creation) -- only "do" is overwritten from this tab's
        n, matching how it always worked before the od/do merge (see
        _goldbach_queue_viz's own docstring for why od/do are no longer
        optional)."""
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

    def _on_goldbach_viz_refresh(self):
        """The Wizualizacja Toplevel's OWN "Sprawdz okno" button -- reads "do"
        from ITS OWN field (self.goldbach_viz_n_entry, still validated via
        _goldbach_parse_n_from -- "do" plays exactly the role the old standalone
        "n" field used to), not the main tab's, so the window is self-sufficient
        once open. "od" is read/validated inside _goldbach_queue_viz itself
        (shared with the row Prev/Next/goto handlers, which also need it re-
        checked on every call -- see that method's own docstring)."""
        if self._goldbach_viz_win is None or not self._goldbach_viz_win.winfo_exists():
            return
        try:
            n = self._goldbach_parse_n_from(self.goldbach_viz_n_entry)
        except ValueError as e:
            messagebox.showerror(self.T("research_goldbach.error_dialog_title"), str(e))
            return
        self._goldbach_queue_viz(n)

    def _goldbach_queue_viz(self, n, reset_page=True):
        """Queues a "viz" worker job for the range [od, n] -- "n" here is the
        SAME value the "do" field holds, i.e. it plays two roles at once: it's
        what Pmax is derived from (largest prime <= n, exactly like the old
        standalone "n" field), AND it's the scan's own upper bound. reset_page=
        True (the default, used by a fresh "Sprawdz okno" click from either the
        main tab or the Wizualizacja window's own button) starts back at
        row/chip page 0, since a different n means a different window and a
        different old base entirely. reset_page=False (used by the row
        Prev/Next handlers below) keeps whatever self._goldbach_viz_row_page was
        already set to by the caller.

        "od" is read fresh from goldbach_viz_range_from_entry every call (not
        cached, via getattr since that Entry only exists once the Wizualizacja
        Toplevel has actually been built) -- Artur, 2026-08-17: an earlier
        version treated od/do as an "optional" pair (blank = full window), which
        looked like two independent ranges once a standalone "n" field ALSO sat
        above it ("ja chyba nie umiem uzywac zakresowosci"). Now there is only
        one range: od defaults to 4 (not blank) and is validated here on every
        call (>=4, and <= n-2 so at least one even number is actually in
        range) -- an invalid od blocks the job with a clear error instead of
        silently clamping into something the person didn't ask for."""
        T = self.T
        if self._goldbach_busy:
            return
        from_entry = getattr(self, "goldbach_viz_range_from_entry", None)
        od_raw = from_entry.get().strip() if from_entry is not None else ""
        n_min = self._eval_quick_number(od_raw) if od_raw else 4
        if n_min is None or n_min < 4:
            messagebox.showerror(
                T("research_goldbach.error_dialog_title"),
                T("research_goldbach.error_viz_range_from_invalid"))
            return
        if n_min > n - 2:
            messagebox.showerror(
                T("research_goldbach.error_dialog_title"),
                T("research_goldbach.error_viz_range_from_too_high", do=f"{n:,}"))
            return
        if reset_page:
            self._goldbach_viz_row_page = 0
            self._goldbach_viz_chip_page = 0
        self._goldbach_viz_current_n = n
        self._goldbach_set_busy(True)
        self._goldbach_worker.submit({
            "op": "viz", "n": n, "row_page": self._goldbach_viz_row_page,
            "n_min": n_min, "n_max": n,
        })

    def _on_goldbach_viz_row_prev(self):
        """Sums-grid "Poprzednia" -- steps back one PAGE of decomposition rows
        (GOLDBACH_CASCADE_ROW_CAP per page). Needs a fresh worker call (see
        _goldbach_queue_viz's own docstring) since only one page's rows are ever
        held in memory at a time."""
        if self._goldbach_busy or self._goldbach_viz_current_n is None:
            return
        if self._goldbach_viz_row_page > 0:
            self._goldbach_viz_row_page -= 1
            self._goldbach_queue_viz(self._goldbach_viz_current_n, reset_page=False)

    def _on_goldbach_viz_row_next(self):
        """Sums-grid "Nastepna" -- see _on_goldbach_viz_row_prev. The Next button is
        disabled once goldbach_window_rows() reports rows_truncated=False for the
        current page (see _goldbach_show_window_visualization), so this doesn't
        need its own upper-bound check."""
        if self._goldbach_busy or self._goldbach_viz_current_n is None:
            return
        self._goldbach_viz_row_page += 1
        self._goldbach_queue_viz(self._goldbach_viz_current_n, reset_page=False)

    def _on_goldbach_viz_row_goto(self):
        """Sums-grid "Idz" -- jumps directly to a typed page number instead of
        stepping one page at a time, same as the app's other large-list nav rows
        (see e.g. _goto_floor_page/_goto_benchmark_page). Clamped against the last
        known segment_size (if a result has already been drawn) so a wildly
        out-of-range page number doesn't just come back empty -- an unclamped page
        still WOULD come back correctly empty (row_offset simply exceeds
        segment_size), this just avoids the round-trip and the confusing "page 500
        / 12" label that would otherwise result."""
        if self._goldbach_busy or self._goldbach_viz_current_n is None:
            return
        raw = self.goldbach_viz_row_goto_entry.get().strip()
        if not raw.isdigit():
            return
        target = int(raw) - 1
        if self._goldbach_viz_last_result is not None:
            total_row_pages = max(
                1, -(-self._goldbach_viz_last_result["segment_size"]
                     // GOLDBACH_CASCADE_ROW_CAP))
            target = max(0, min(target, total_row_pages - 1))
        else:
            target = max(0, target)
        self._goldbach_viz_row_page = target
        self._goldbach_queue_viz(self._goldbach_viz_current_n, reset_page=False)

    def _on_goldbach_viz_chip_prev(self):
        """STARA BAZA "Poprzednia" -- purely client-side: old_base_primes is
        already fully present in the last worker result, so paging through it is
        just a redraw with a different slice, no worker round-trip needed."""
        if self._goldbach_viz_chip_page > 0:
            self._goldbach_viz_chip_page -= 1
            if self._goldbach_viz_last_result is not None:
                self._goldbach_show_window_visualization(self._goldbach_viz_last_result)

    def _on_goldbach_viz_chip_next(self):
        """STARA BAZA "Nastepna" -- see _on_goldbach_viz_chip_prev. Clamped against
        the true page count inside _goldbach_show_window_visualization, so an extra
        click past the end is harmless (the Next button is also disabled there)."""
        self._goldbach_viz_chip_page += 1
        if self._goldbach_viz_last_result is not None:
            self._goldbach_show_window_visualization(self._goldbach_viz_last_result)

    def _on_goldbach_viz_chip_goto(self):
        """STARA BAZA "Idz" -- pure client-side like chip prev/next, so this just
        sets the page and redraws; _goldbach_show_window_visualization clamps it
        against the true page count itself (same as it already does for chip
        prev/next going past either end)."""
        raw = self.goldbach_viz_chip_goto_entry.get().strip()
        if not raw.isdigit():
            return
        self._goldbach_viz_chip_page = max(0, int(raw) - 1)
        if self._goldbach_viz_last_result is not None:
            self._goldbach_show_window_visualization(self._goldbach_viz_last_result)

    def _on_goldbach_viz_decompose(self):
        """"Pokaz wszystkie rozklady" -- reads a target n from the Wizualizacja
        window's own decompose field and exhaustively scans EVERY prime pair
        summing to it (goldbach_all_decompositions), flagged against the Pmax of
        the window currently displayed above (self._goldbach_viz_last_result).
        Needs a window to already be checked (for its Pmax) -- unlike the main n
        field, this one is not restricted to n's inside [4, 2*Pmax], since the
        question ("does n need a prime outside Pmax's base") makes sense for any
        even n Artur wants to probe, not just ones already in the current window."""
        T = self.T
        if self._goldbach_busy:
            return
        if self._goldbach_viz_last_result is None:
            messagebox.showerror(
                T("research_goldbach.error_dialog_title"),
                T("research_goldbach.error_decompose_no_window"))
            return
        try:
            target_n = self._goldbach_parse_n_from(self.goldbach_viz_decompose_entry)
        except ValueError as e:
            messagebox.showerror(T("research_goldbach.error_dialog_title"), str(e))
            return
        if target_n < 4 or target_n % 2 != 0:
            messagebox.showerror(
                T("research_goldbach.error_dialog_title"),
                T("research_goldbach.error_decompose_must_be_even"))
            return
        self._goldbach_decompose_current_n = target_n
        self._goldbach_decompose_current_pmax = self._goldbach_viz_last_result["pmax"]
        self._goldbach_decompose_page = 0
        self._goldbach_queue_decompose_page()

    def _goldbach_queue_decompose_page(self):
        """Issues a "decompose" worker job for self._goldbach_decompose_page of
        self._goldbach_decompose_current_n against self._goldbach_decompose_
        current_pmax -- shared by the initial "Pokaz wszystkie rozklady" click and
        the detail window's own Prev/Next/goto handlers, so they all re-request the
        SAME target n/pmax and only the page differs."""
        self._goldbach_set_busy(True)
        self._goldbach_worker.submit({
            "op": "decompose", "n": self._goldbach_decompose_current_n,
            "pmax": self._goldbach_decompose_current_pmax,
            "page": self._goldbach_decompose_page,
        })

    def _on_goldbach_decompose_prev(self):
        if self._goldbach_busy or self._goldbach_decompose_current_n is None:
            return
        if self._goldbach_decompose_page > 0:
            self._goldbach_decompose_page -= 1
            self._goldbach_queue_decompose_page()

    def _on_goldbach_decompose_next(self):
        """Next button is disabled once the last drawn result's own "truncated" is
        False (see _goldbach_show_decomposition_detail), so no upper-bound check
        needed here -- same convention as the sums-grid row nav."""
        if self._goldbach_busy or self._goldbach_decompose_current_n is None:
            return
        self._goldbach_decompose_page += 1
        self._goldbach_queue_decompose_page()

    def _on_goldbach_decompose_goto(self):
        if self._goldbach_busy or self._goldbach_decompose_current_n is None:
            return
        raw = self.goldbach_decompose_goto_entry.get().strip()
        if not raw.isdigit():
            return
        target = int(raw) - 1
        if self._goldbach_decompose_last_result is not None:
            total_pages = max(1, -(
                -self._goldbach_decompose_last_result["count"]
                // GOLDBACH_DECOMPOSE_ROW_CAP))
            target = max(0, min(target, total_pages - 1))
        else:
            target = max(0, target)
        self._goldbach_decompose_page = target
        self._goldbach_queue_decompose_page()

    def _goldbach_ensure_decompose_window(self):
        """Lazy-create-and-reuse Toplevel for the decomposition detail list, same
        pattern as _goldbach_ensure_viz_window (one persistent window redrawn in
        place, not a new Toplevel piling up per click)."""
        if (self._goldbach_decompose_win is not None
                and self._goldbach_decompose_win.winfo_exists()):
            return self._goldbach_decompose_win

        T = self.T
        win = tk.Toplevel(self)

        def _on_close():
            win.destroy()
            self._goldbach_decompose_win = None

        win.protocol("WM_DELETE_WINDOW", _on_close)

        self.goldbach_decompose_verdict_var = tk.StringVar(value="")
        ttk.Label(win, textvariable=self.goldbach_decompose_verdict_var,
                  wraplength=520, justify="left", font=("TkDefaultFont", 10, "bold"),
                  padding=(10, 10, 10, 4)).pack(anchor="w")

        self.goldbach_decompose_count_var = tk.StringVar(value="")
        ttk.Label(win, textvariable=self.goldbach_decompose_count_var,
                  padding=(10, 0, 10, 2)).pack(anchor="w")

        # Prev/label/Next/goto -- same layout as the Wizualizacja's own row_nav,
        # needed here for the same reason: a large n can have tens of thousands of
        # pairs (Artur's own n~=9999992 screenshot: 53364), and the old silent
        # "(showing first 300 of 53364)" note with no way to see the rest was
        # exactly the gap Artur flagged.
        decompose_nav = ttk.Frame(win, padding=(10, 0, 10, 4))
        decompose_nav.pack(fill="x")
        self.goldbach_decompose_prev_btn = ttk.Button(
            decompose_nav, text=T("common.prev_page"),
            command=self._on_goldbach_decompose_prev, state="disabled")
        self.goldbach_decompose_prev_btn.pack(side="left")
        self.goldbach_decompose_page_label = tk.StringVar(value="")
        ttk.Label(decompose_nav, textvariable=self.goldbach_decompose_page_label,
                  width=14, anchor="center").pack(side="left", padx=(4, 4))
        self.goldbach_decompose_next_btn = ttk.Button(
            decompose_nav, text=T("common.next_page"),
            command=self._on_goldbach_decompose_next, state="disabled")
        self.goldbach_decompose_next_btn.pack(side="left")
        self.goldbach_decompose_goto_entry = ttk.Entry(decompose_nav, width=6)
        self.goldbach_decompose_goto_entry.pack(side="left", padx=(12, 0))
        self.goldbach_decompose_goto_entry.bind(
            "<Return>", lambda _e: self._on_goldbach_decompose_goto())
        ttk.Button(decompose_nav, text=T("common.goto"),
                   command=self._on_goldbach_decompose_goto).pack(
            side="left", padx=(4, 0))

        tree_frame = ttk.Frame(win, padding=(10, 0, 10, 4))
        tree_frame.pack(fill="both", expand=True)
        columns = ("p", "q", "old_base")
        tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", height=16)
        tree.heading("p", text=T("research_goldbach.decompose_col_p"))
        tree.heading("q", text=T("research_goldbach.decompose_col_q"))
        tree.heading("old_base", text=T("research_goldbach.decompose_col_base"))
        tree.column("p", width=100, anchor="e")
        tree.column("q", width=100, anchor="e")
        tree.column("old_base", width=140, anchor="center")
        tree.tag_configure("new", foreground="#a06a00")
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        self.goldbach_decompose_tree = tree

        self._goldbach_decompose_win = win
        return win

    def _goldbach_show_decomposition_detail(self, result):
        """Renders one goldbach_all_decompositions() result into the detail
        Toplevel: every (p, q) pair for the requested n ON THIS PAGE, plus a
        headline verdict on buildableFromBase(Pmax, n) [Constructive.lean] --
        computed over the whole scan regardless of which page is showing. Per
        Artur's correction ("popraw tak by było zgodne z leanem"): Lean's own
        buildableFromBase only ever bounds p, never q (see goldbach_window.py's
        module docstring) -- so the per-row "Skad q" column is PURELY
        INFORMATIONAL (which prime was already known before this window vs first
        appears inside it), never a pass/fail signal. The verdict is about p_in_base
        across the whole list, not about any individual q. Page nav (Prev/Next/
        goto) mirrors the sums-grid row nav in the main diagram."""
        T = self.T
        win = self._goldbach_ensure_decompose_window()
        win.title(T("research_goldbach.decompose_window_title", n=result["n"]))
        win.deiconify()
        win.lift()

        self._goldbach_decompose_last_result = result

        pmax = result["pmax"]
        if result["buildable_from_base"]:
            self.goldbach_decompose_verdict_var.set(
                T("research_goldbach.decompose_verdict_yes",
                  pmax=pmax, count=result["count"]))
        else:
            self.goldbach_decompose_verdict_var.set(
                T("research_goldbach.decompose_verdict_no",
                  pmax=pmax, count=result["count"]))
        self.goldbach_decompose_count_var.set(
            T("research_goldbach.decompose_count", count=result["count"]))

        tree = self.goldbach_decompose_tree
        tree.delete(*tree.get_children())
        old_label = T("research_goldbach.decompose_q_old")
        new_label = T("research_goldbach.decompose_q_new")
        for pair in result["decompositions"]:
            q_old = pair["q_in_base"]
            tree.insert(
                "", "end", values=(pair["p"], pair["q"],
                                    old_label if q_old else new_label),
                tags=() if q_old else ("new",))

        page = result.get("page", 0)
        total_pages = max(1, -(-result["count"] // GOLDBACH_DECOMPOSE_ROW_CAP))
        self._update_nav_controls(
            self.goldbach_decompose_page_label, page, total_pages,
            self.goldbach_decompose_prev_btn, self.goldbach_decompose_next_btn)

    def _goldbach_ensure_viz_window(self):
        """Creates the Wizualizacja Toplevel the first time it's needed, or returns
        the existing one if it's still open -- so repeated clicks (from this tab's
        button, or from the window's own check button) redraw ONE persistent
        window instead of piling up a new Toplevel per click. Layout: a top row
        with its own od/do range fields + check button + status label, then a
        Canvas below that _goldbach_show_window_visualization redraws in place
        (clear + redraw, resizing the canvas to fit) rather than rebuilding from
        scratch."""
        if self._goldbach_viz_win is not None and self._goldbach_viz_win.winfo_exists():
            return self._goldbach_viz_win

        T = self.T
        win = tk.Toplevel(self)
        win.title(T("research_goldbach.viz_window_title_generic"))

        def _on_close():
            win.destroy()
            self._goldbach_viz_win = None

        win.protocol("WM_DELETE_WINDOW", _on_close)

        # Single od/do row -- Artur, 2026-08-17: an earlier version had a
        # standalone "n" field here PLUS a separate "optional" od/do range
        # below it, which looked like two independent ways to pick a range
        # ("ja chyba nie umiem uzywac zakresowosci") when "do" was always
        # effectively n's own role anyway (Pmax is derived from whatever's
        # typed as the upper bound, exactly like the old n field did) --
        # merged into one row so there's only one range to reason about, not
        # two overlapping ones. "do" plays n's old role unchanged (still
        # goldbach_viz_n_entry / _goldbach_parse_n_from, still what
        # determines Pmax); "od" defaults to 4 (not blank) and is validated
        # against "do" in _goldbach_queue_viz (>=4, and <= do-2 so at least
        # one even n exists in the range) so the button always operates on a
        # concrete, well-formed range -- no more separate "leave it blank for
        # the full window" mode to explain.
        top = ttk.Frame(win)
        top.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(top, text=T("research_goldbach.viz_range_label")).pack(side="left")
        self.goldbach_viz_range_from_entry = ttk.Entry(top, width=16)
        self.goldbach_viz_range_from_entry.pack(side="left", padx=(6, 12))
        self.goldbach_viz_range_from_entry.insert(0, "4")
        self.goldbach_viz_range_from_entry.bind(
            "<Return>", lambda _e: self._on_goldbach_viz_refresh())
        ttk.Label(top, text=T("research_goldbach.viz_range_to_label")).pack(side="left")
        self.goldbach_viz_n_entry = ttk.Entry(top, width=16)
        self.goldbach_viz_n_entry.pack(side="left", padx=(6, 12))
        self.goldbach_viz_n_entry.insert(0, self.goldbach_n_entry.get() or "1000")
        self.goldbach_viz_n_entry.bind(
            "<Return>", lambda _e: self._on_goldbach_viz_refresh())
        self.goldbach_viz_check_button = ttk.Button(
            top, text=T("research_goldbach.run_button"),
            command=self._on_goldbach_viz_refresh)
        self.goldbach_viz_check_button.pack(side="left")
        ttk.Label(win, text=T("research_goldbach.viz_range_hint"),
                  wraplength=780, justify="left", foreground="#777").pack(
            anchor="w", padx=10, pady=(0, 6))

        self.goldbach_viz_status_var = tk.StringVar(value="")
        ttk.Label(win, textvariable=self.goldbach_viz_status_var,
                  wraplength=780, justify="left", foreground="#555").pack(
            anchor="w", padx=10, pady=(0, 6))

        # Own Progressbar, separate from the shared self.totals_progress in the
        # MAIN window -- Artur, 2026-08-17: "progress br trzeba dodać też do
        # samego okna wizualizacji bo w nim często jestem w trybie
        # pełnoekranowym" -- the shared bottom bar is invisible while this
        # Toplevel is maximized/fullscreen over it. Mirrored in lockstep with
        # totals_progress by _goldbach_viz_progress_set (see its own
        # docstring), called from every place that already updates
        # totals_progress (_goldbach_set_busy, _on_goldbach_worker_progress) so
        # the two never drift out of sync.
        self.goldbach_viz_progress = ttk.Progressbar(
            win, mode="determinate", maximum=1, value=0)
        self.goldbach_viz_progress.pack(fill="x", padx=10, pady=(0, 6))

        # "Rozloz liczbe" -- Artur's request after noticing that the smallest-
        # witness search (_smallest_witness / window_rows) can land on a pair
        # whose q > Pmax even when an old-base-only pair (both p, q <= Pmax) exists
        # elsewhere in the full combination list -- e.g. n=1012 against Pmax=997:
        # the smallest witness is 3+1009 (1009 is "new"), but 29+983 also works and
        # stays entirely inside the old base. This exhaustively scans ALL pairs for
        # one specific n (see goldbach_all_decompositions) against the Pmax of the
        # window currently shown above, instead of only the single smallest one.
        decompose_row = ttk.Frame(win)
        decompose_row.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Label(decompose_row, text=T("research_goldbach.viz_decompose_label")).pack(
            side="left")
        self.goldbach_viz_decompose_entry = ttk.Entry(decompose_row, width=16)
        self.goldbach_viz_decompose_entry.pack(side="left", padx=(6, 12))
        self.goldbach_viz_decompose_entry.bind(
            "<Return>", lambda _e: self._on_goldbach_viz_decompose())
        self.goldbach_viz_decompose_button = ttk.Button(
            decompose_row, text=T("research_goldbach.viz_decompose_button"),
            command=self._on_goldbach_viz_decompose)
        self.goldbach_viz_decompose_button.pack(side="left")

        # Two INDEPENDENT navigation rows, per Artur's request for the same kind
        # of Prev/Next paging used elsewhere for large lists (Primes tab preview,
        # benchmark log -- see _update_nav_controls). STARA BAZA pages through
        # old_base_primes client-side; the sums grid pages through the window's
        # decomposition rows via a fresh backend call each time (see
        # _goldbach_queue_viz's docstring for why they differ).
        chip_nav = ttk.Frame(win)
        chip_nav.pack(fill="x", padx=10, pady=(0, 2))
        ttk.Label(chip_nav, text=T("research_goldbach.viz_nav_chips_label")).pack(
            side="left")
        self.goldbach_viz_chip_prev_btn = ttk.Button(
            chip_nav, text=T("common.prev_page"),
            command=self._on_goldbach_viz_chip_prev, state="disabled")
        self.goldbach_viz_chip_prev_btn.pack(side="left", padx=(6, 4))
        self.goldbach_viz_chip_page_label = tk.StringVar(value="")
        ttk.Label(chip_nav, textvariable=self.goldbach_viz_chip_page_label,
                  width=14, anchor="center").pack(side="left")
        self.goldbach_viz_chip_next_btn = ttk.Button(
            chip_nav, text=T("common.next_page"),
            command=self._on_goldbach_viz_chip_next, state="disabled")
        self.goldbach_viz_chip_next_btn.pack(side="left", padx=(4, 0))
        self.goldbach_viz_chip_goto_entry = ttk.Entry(chip_nav, width=6)
        self.goldbach_viz_chip_goto_entry.pack(side="left", padx=(12, 0))
        self.goldbach_viz_chip_goto_entry.bind(
            "<Return>", lambda _e: self._on_goldbach_viz_chip_goto())
        ttk.Button(chip_nav, text=T("common.goto"),
                   command=self._on_goldbach_viz_chip_goto).pack(side="left", padx=(4, 0))

        row_nav = ttk.Frame(win)
        row_nav.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Label(row_nav, text=T("research_goldbach.viz_nav_rows_label")).pack(
            side="left")
        self.goldbach_viz_row_prev_btn = ttk.Button(
            row_nav, text=T("common.prev_page"),
            command=self._on_goldbach_viz_row_prev, state="disabled")
        self.goldbach_viz_row_prev_btn.pack(side="left", padx=(6, 4))
        self.goldbach_viz_row_page_label = tk.StringVar(value="")
        ttk.Label(row_nav, textvariable=self.goldbach_viz_row_page_label,
                  width=14, anchor="center").pack(side="left")
        self.goldbach_viz_row_next_btn = ttk.Button(
            row_nav, text=T("common.next_page"),
            command=self._on_goldbach_viz_row_next, state="disabled")
        self.goldbach_viz_row_next_btn.pack(side="left", padx=(4, 0))
        self.goldbach_viz_row_goto_entry = ttk.Entry(row_nav, width=6)
        self.goldbach_viz_row_goto_entry.pack(side="left", padx=(12, 0))
        self.goldbach_viz_row_goto_entry.bind(
            "<Return>", lambda _e: self._on_goldbach_viz_row_goto())
        ttk.Button(row_nav, text=T("common.goto"),
                   command=self._on_goldbach_viz_row_goto).pack(side="left", padx=(4, 0))

        # NOT fill="both"/expand=True here: an earlier version packed the canvas to
        # fill the whole Toplevel, which meant the Canvas widget stretched to
        # whatever size the window happened to be (its actual drawn content still
        # only covering its own configured width/height), leaving a big blank area
        # to the right and pinning everything to the top-left -- exactly the bug
        # Artur reported ("mamy tyle wolnej przestrzeni a wszystko z lewej
        # strony"). Packing it at its natural size instead means the Toplevel
        # itself auto-sizes to the canvas's actual content on every redraw (see
        # the win.geometry("") reset in _goldbach_show_window_visualization).
        canvas_frame = ttk.Frame(win)
        canvas_frame.pack(padx=10, pady=(0, 10))
        self.goldbach_viz_canvas = tk.Canvas(
            canvas_frame, width=820, height=120, background="white",
            highlightthickness=0)
        self.goldbach_viz_canvas.pack()

        self._goldbach_viz_win = win
        return win

    def _goldbach_widget_configure(self, attr_name, **kwargs):
        """configure() an optional, possibly-stale widget attribute without
        blowing up -- `hasattr(self, attr_name)` alone isn't enough here: closing
        the Wizualizacja or decompose Toplevel (see their own _on_close handlers)
        destroys every Tk widget inside it, but does NOT clear out the Python
        attribute still pointing at that now-dead widget (only the *_win attribute
        itself gets reset to None). Configuring a destroyed widget raises
        tk.TclError -- caught and ignored here, since "the window this button
        lived in is gone" is a perfectly normal thing to happen mid-flight (a
        worker job queued before the window was closed, whose result now arrives
        after). Without this guard, that TclError propagates out of whichever
        caller stopped it from reaching the code that resets self._goldbach_busy
        back to False, permanently disabling every Goldbach button on the tab --
        exactly the bug Artur reported (open+close "Pokaz wszystkie rozklady",
        button stays greyed out, sums-grid "Nastepna" too)."""
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
        """Restores BOTH the Wizualizacja sums-grid Prev/Next and the decompose
        window's own Prev/Next from their last-drawn results. Needed because
        _goldbach_set_busy(True) force-disables ALL FOUR of these buttons for
        ANY Goldbach job (window/viz/decompose share one busy flag and one
        worker thread), but each pair's correct re-enabled state is normally
        only recalculated by its OWN show_* function's _update_nav_controls
        call -- _goldbach_show_decomposition_detail never touches the
        sums-grid buttons, and _goldbach_show_window_visualization never
        touches the decompose buttons. Since only ONE show_* function runs per
        completed job, the OTHER pair was left stuck disabled from the
        busy=True phase forever -- exactly what Artur reported: clicking
        "Pokaz wszystkie rozklady" (a decompose job) leaves the Wizualizacja's
        own "Sumy w oknie" Nastepna button greyed out even though that
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

    def _goldbach_job(self, job, report_progress):
        """Runs on PersistentWorker's own daemon thread -- single-owner reasoning
        identical to ConstellationsRecordsTab._job's own docstring (self._goldbach_busy
        blocks new requests from the GUI side, so only one job is ever in flight).
        Three job shapes distinguished by "op":

        "window" -- resolves Pmax = largest prime <= n from a FRESH in-process
        sieve up to n, then runs goldbach_window.check_window(Pmax, mode) (which
        sieves again, up to 2*Pmax -- a small amount of duplicate work, traded for
        reusing check_window()'s existing, already-verified contract unchanged).

        "viz" -- resolves Pmax the same way, but from is_prime sourced from the
        on-disk magazyn (read_is_prime_from_storage, up to 2*n -- a safe upper
        bound since Pmax <= n means 2*Pmax <= 2*n), per Artur's explicit
        instruction that Wizualizacja should read from storage rather than
        recompute. Then runs goldbach_window.window_rows(is_prime, Pmax, ...) over
        that SAME array -- both the Pmax resolution and the window check share one
        storage read. job["row_page"] (default 0) selects which PAGE of
        decomposition rows to compute (see GOLDBACH_CASCADE_ROW_CAP and the
        row_offset param it's paired with) -- re-reads storage and re-derives Pmax
        every page turn rather than caching, same cost profile as re-running the
        whole check, which is acceptable since it's already async off the GUI
        thread. Mid-job progress ticks from both_base_window_rows' own
        progress_cb are relayed via report_progress -- PersistentWorker's own
        channel, kept separate from the (op, ok, payload) result tuple so
        _on_goldbach_worker_progress never has to be told apart from a finished
        job the way the old single-queue "progress" tag required.

        "decompose" -- job carries an explicit "pmax" (the ALREADY-displayed
        window's Pmax, not re-derived from n, since the target n here is a
        separate probe, not necessarily inside that window). Reads storage up to
        n itself (only need is_prime long enough to index n), then runs
        goldbach_window.all_decompositions(is_prime, n, pmax, cap=...) -- the
        exhaustive "sliding window" scan Artur asked for, answering whether n
        truly needs a prime beyond pmax's old base or whether the smallest-witness
        search (used by "viz") just happened to land on one.

        None of the three ops needs a WSL subprocess. Catches its own exceptions
        (per PersistentWorker's fn contract -- see background.py's docstring) so a
        failure surfaces with the right op context, instead of falling through to
        PersistentWorker's own last-resort net which has no way to know which
        request failed."""
        T = self.T
        op = job["op"]
        n = job["n"]
        portal_folder = self._get_portal_folder()
        try:
            if op == "window":
                is_prime_n = goldbach_sieve_is_prime(n)
                pmax = goldbach_largest_prime_le(is_prime_n, n)
                if pmax is None:
                    return op, False, T("research_goldbach.error_no_prime_le_n", n=n)
                result = goldbach_check_window(pmax, job["mode"])
                result["n"] = n
                return op, True, result
            elif op == "decompose":
                try:
                    is_prime = read_is_prime_from_storage(portal_folder, n)
                except MissingStorageRangeError as e:
                    return op, False, {
                        "kind": "storage_missing", "floor": e.floor,
                        "needed_upto": e.needed_upto,
                        "message": T("research_goldbach.error_storage_missing",
                                     floor=e.floor, upto=f"{e.needed_upto:,}")}
                page = job.get("page", 0)
                result = goldbach_all_decompositions(
                    is_prime, n, job["pmax"], cap=GOLDBACH_DECOMPOSE_ROW_CAP,
                    offset=page * GOLDBACH_DECOMPOSE_ROW_CAP)
                result["page"] = page
                return op, True, result
            else:
                # Wizualizacja's only window: [4, Pmax+GOLDBACH_BOTH_BASE_PMIN],
                # both p and q required <= Pmax -- exactly what Lean's
                # additiveSelfContained_of_hasGoldbachRep proves unconditionally
                # (see goldbach_window.BOTH_BASE_PMIN's own docstring). Only
                # ever needs storage read up to n+Pmin, not 2*n. Checked BEFORE
                # the storage read (not after, unlike a plain ValueError from
                # both_base_window_rows itself) so an oversized n gets a
                # translated, dedicated error instead of a raw exception string.
                limit = n + GOLDBACH_BOTH_BASE_PMIN
                try:
                    is_prime = read_is_prime_from_storage(portal_folder, limit)
                except MissingStorageRangeError as e:
                    return op, False, {
                        "kind": "storage_missing", "floor": e.floor,
                        "needed_upto": e.needed_upto,
                        "message": T("research_goldbach.error_storage_missing",
                                     floor=e.floor, upto=f"{e.needed_upto:,}")}
                pmax = goldbach_largest_prime_le(is_prime, n)
                if pmax is None:
                    return op, False, T("research_goldbach.error_no_prime_le_n", n=n)
                if pmax > GOLDBACH_BOTH_BASE_PMAX_CEILING:
                    return op, False, T(
                        "research_goldbach.error_both_base_pmax_too_large",
                        pmax=f"{pmax:,}",
                        ceiling=f"{GOLDBACH_BOTH_BASE_PMAX_CEILING:,}")
                row_page = job.get("row_page", 0)
                result = goldbach_both_base_window_rows(
                    is_prime, pmax, row_cap=GOLDBACH_CASCADE_ROW_CAP,
                    row_offset=row_page * GOLDBACH_CASCADE_ROW_CAP,
                    n_min=job.get("n_min"), n_max=job.get("n_max"),
                    progress_cb=lambda f: report_progress(f))
                result["n"] = n
                result["row_page"] = row_page
                return op, True, result
        except Exception as e:  # noqa: BLE001 -- surface any unexpected failure
                                 # to the GUI as an error dialog instead of
                                 # silently killing this worker thread
            return op, False, str(e)

    def _on_goldbach_worker_progress(self, payload):
        """PersistentWorker's report_progress channel for the "viz" op's
        both_base_window_rows() call (see _goldbach_job's own docstring). Switches
        the SHARED bottom bar (self.totals_progress -- same one the floor-totals
        scan/Generation tab use) out of the indeterminate spin
        _goldbach_set_busy(True) started it in and into a real fraction; stop()
        first since an indeterminate animation still running underneath a
        determinate value looks broken (bar visibly jumps once the animation's
        next tick fires). Busy state/nav buttons are untouched -- the job is still
        running."""
        self.totals_progress.stop()
        self.totals_progress.configure(mode="determinate", maximum=1, value=payload)
        self._goldbach_viz_progress_set(value=payload)

    def _on_goldbach_worker_result(self, payload, error):
        """Main-thread callback for _goldbach_job -- same shape as the old
        _poll_goldbach_results, just delivered via PersistentWorker instead of a
        bespoke queue.Queue + self.after() pair. Wrapped in its own try/except
        (Exception, not just letting it propagate) so that ONE bad message -- e.g.
        a result arriving for a Toplevel (Wizualizacja or decompose) the user
        already closed -- can never raise up through PersistentWorker's own
        _poll() and skip ITS self.widget.after() reschedule, which would silently
        kill polling for the rest of the session (background.PersistentWorker._poll
        does not wrap on_result itself -- see _goldbach_widget_configure's own
        docstring for the specific bug this same reasoning was originally
        covering for). `error` is only non-None for a genuine PersistentWorker-
        framework bug (_goldbach_job already catches its own exceptions -- see its
        docstring)."""
        T = self.T
        try:
            self._goldbach_set_busy(False)
            self._goldbach_refresh_nav_buttons()
            if error is not None:
                self.status.set(T("research_goldbach.status_error"))
                messagebox.showerror(T("research_goldbach.error_dialog_title"), str(error))
                return
            op, ok, result_payload = payload
            if not ok:
                self.status.set(T("research_goldbach.status_error"))
                if isinstance(result_payload, dict) and result_payload.get("kind") == "storage_missing":
                    # Not a generic failure -- read_is_prime_from_storage
                    # found a specific gap (floor/needed_upto). Offer to
                    # fill it instead of just naming it, same "offer to
                    # generate the missing piece" UX search already uses
                    # for prime/constellation lookups (see
                    # _offer_generate_missing_prime_window's docstring).
                    self._offer_generate_missing_range(op, result_payload)
                else:
                    messagebox.showerror(
                        T("research_goldbach.error_dialog_title"), result_payload)
                return
            self.status.set(T("research_goldbach.status_done"))
            if op == "window":
                self._goldbach_show_result(result_payload)
            elif op == "decompose":
                self._goldbach_show_decomposition_detail(result_payload)
            else:
                self._goldbach_show_window_visualization(result_payload)
        except Exception:  # noqa: BLE001 -- see docstring: never let one bad
                            # message raise up through PersistentWorker's _poll
            pass

    def _goldbach_viz_progress_set(self, indeterminate=False, value=None):
        """Mirrors totals_progress's own state onto the Wizualizacja Toplevel's
        OWN Progressbar (see _goldbach_ensure_viz_window) -- Artur, 2026-08-17:
        the shared bottom bar lives in the MAIN window and is invisible while
        the Toplevel is maximized/fullscreen, which is how this tab is used
        most of the time. Guarded with the same try/except tk.TclError pattern
        _goldbach_widget_configure uses, since the Toplevel may already be
        closed when a queued job's result/progress tick arrives."""
        widget = getattr(self, "goldbach_viz_progress", None)
        if widget is None:
            return
        try:
            widget.stop()
            if indeterminate:
                widget.configure(mode="indeterminate")
                widget.start(80)
            else:
                widget.configure(mode="determinate", maximum=1, value=value or 0)
        except tk.TclError:
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
        Tabela rekordow tab's hit-list dialog). No-op in "touch_once" mode (pairs
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

    def _goldbach_show_window_visualization(self, result):
        """Redraws the "old base vs window" diagram into the PERSISTENT Wizualizacja
        Toplevel/Canvas (see _goldbach_ensure_viz_window) -- built from a REAL
        window_rows() result sourced from the magazyn
        (read_is_prime_from_storage), covering EXACTLY the window [4, 2*Pmax] that
        "Sprawdz okno" also checks (never a separate cascade step -- see
        goldbach_window.window_rows' own docstring and Artur's own instruction:
        "wizualizacja zawsze siedzi w oknie 4-2Pmax"). The window itself, its n
        field and its check button are created once and reused; this method only
        clears and repopulates the canvas so repeated checks (from this tab's
        button, or the window's own button) update ONE window in place instead of
        piling up a new Toplevel per click. Plain tk.Canvas, same
        zero-extra-installs approach as the Benchmark tab's own hand-rolled chart
        (no matplotlib)."""
        T = self.T
        win = self._goldbach_ensure_viz_window()
        win.title(T("research_goldbach.viz_window_title",
                    n=result["n"], pmax=result["pmax"]))
        # The coverage verdict (all covered / which n's aren't) is ALSO drawn at
        # the very bottom of the canvas below (viz_summary_covered/void), but
        # that can end up scrolled or clipped off screen for a tall diagram --
        # Artur asked for the message to appear "somewhere" it's guaranteed
        # visible, so it's repeated here in the status label at the TOP of the
        # window, which never depends on the canvas's own size.
        coverage_text = (
            T("research_goldbach.viz_summary_covered",
              segment_size=result["segment_size"])
            if result["covered"] else
            T("research_goldbach.viz_summary_void",
              counterexamples=", ".join(str(x) for x in result["counterexamples"])))
        # Only shown when the "od/do" fields actually narrowed the scan below
        # the full [4, window_max] -- otherwise range_min/range_max just equal
        # the window's own bounds and the note would be redundant noise on
        # every single check. Without this, a restricted-range "covered"
        # verdict could easily be misread as a claim about the WHOLE window.
        range_note = (
            "  " + T("research_goldbach.viz_range_note",
                     range_min=result["range_min"], range_max=result["range_max"])
            if result["range_min"] != 4 or result["range_max"] != result["window_max"]
            else "")
        self.goldbach_viz_status_var.set(
            T("research_goldbach.viz_status_shown", n=result["n"], pmax=result["pmax"])
            + range_note + "  " + coverage_text)
        if self.goldbach_viz_n_entry.get().strip() != str(result["n"]):
            self.goldbach_viz_n_entry.delete(0, "end")
            self.goldbach_viz_n_entry.insert(0, str(result["n"]))

        # Cache the full result so the chip Prev/Next handlers (pure client-side,
        # see _on_goldbach_viz_chip_prev/_next's own docstrings) can call back into
        # this same method without needing a fresh worker round-trip.
        self._goldbach_viz_last_result = result

        canvas = self.goldbach_viz_canvas
        canvas.delete("all")

        chips = result["old_base_primes"]
        rows = result["rows"]

        # Box widths scale to the actual digit count of the values THIS diagram is
        # drawing (window_max/pmax), instead of a fixed pixel width -- a fixed
        # width sized for 2-digit examples would silently clip or overflow once n
        # (and therefore p/q) grows into 5+ digits.
        def _digit_box_w(min_w, digits):
            return max(min_w, 11 * digits + 22)

        n_digits = len(str(result["window_max"]))
        p_digits = len(str(result["pmax"]))
        q_digits = len(str(result["window_max"]))  # q can approach window_max
        n_box_w = _digit_box_w(46, n_digits)
        p_box_w = _digit_box_w(44, p_digits)
        q_box_w = _digit_box_w(44, q_digits)
        chip_w = _digit_box_w(34, p_digits)
        chip_gap = 6

        # chip_cols (and therefore the "STARA BAZA" box width) is derived from
        # chip_w, not hardcoded -- a fixed 6-column grid at a fixed 230px box width
        # was sized for 1-2 digit primes; once Pmax grew multi-digit (chip_w scaled
        # up above), 6 columns no longer fit inside 230px and the overflow chips
        # were drawn PAST the box's right edge, straight on top of the row grid
        # beside it (Artur caught this: the "11 13" / "31 37" / "59 61" / "83 89"
        # fragments overlapping the n=6/8/10/12 rows in his n=997 screenshot were
        # literally chips 5 and 6 of each chip row spilling out). box_w is now
        # computed to fit chip_cols columns EXACTLY, so there is no overflow at any
        # digit count -- chip_cols itself narrows for big primes instead.
        chip_cols_target_w = 210  # desired inner width for the chip grid
        chip_cols = max(3, chip_cols_target_w // (chip_w + chip_gap))
        box_w = 24 + chip_cols * chip_w + (chip_cols - 1) * chip_gap

        # STARA BAZA pagination (client-side, see _on_goldbach_viz_chip_prev/_next):
        # old_base_primes can hold hundreds of thousands of entries for a large
        # Pmax, so only ONE page's worth is ever sliced for drawing -- per Artur's
        # request for the same kind of Prev/Next browsing used elsewhere in the app
        # for large lists, instead of a static "+N more" note with no way to see
        # the rest.
        chip_page_size = chip_cols * GOLDBACH_VIZ_CHIP_ROWS_PER_PAGE
        total_chip_pages = max(1, -(-len(chips) // chip_page_size)) if chips else 1
        self._goldbach_viz_chip_page = max(
            0, min(self._goldbach_viz_chip_page, total_chip_pages - 1))
        chip_start = self._goldbach_viz_chip_page * chip_page_size
        chip_shown = chips[chip_start:chip_start + chip_page_size]
        chip_rows = max(1, -(-len(chip_shown) // chip_cols))
        self._update_nav_controls(
            self.goldbach_viz_chip_page_label, self._goldbach_viz_chip_page,
            total_chip_pages, self.goldbach_viz_chip_prev_btn,
            self.goldbach_viz_chip_next_btn)

        # Rows fan out into up to GOLDBACH_VIZ_MAX_COLS columns instead of one long
        # strip -- a single column left the diagram pinned to the top-left with a
        # large blank area beside it once the window was sized to fit its content
        # rather than stretched to fill the Toplevel (see _goldbach_ensure_viz_
        # window's own note on why the canvas is no longer packed with fill/expand).
        rows_per_col = GOLDBACH_VIZ_ROWS_PER_COL
        header_h = 106
        footer_h = 60

        # Cap rows_per_col to what actually fits ON SCREEN VERTICALLY, mirroring
        # the column-width cap just below -- Artur reported that adding the mode
        # toggle row (_goldbach_ensure_viz_window) pushed a full 3x14-row page
        # (both_base mode, n=1000) tall enough that the canvas -- and with it the
        # "wszystko pokryte" / counterexamples summary drawn at its very bottom --
        # ran off the bottom of the screen with no scrollbar to reach it. Unlike
        # the width cap (which drops whole COLUMNS), this shrinks how many ROWS
        # each column holds, so a screen too short for 14 rows still shows AS MANY
        # full rows as fit rather than none. available_h subtracts a flat margin
        # for the Toplevel's own packed controls above the canvas (n/status/mode/
        # decompose/chip-nav/row-nav rows) plus OS window chrome/taskbar, none of
        # which is part of the canvas itself but all of which still has to fit
        # alongside it on screen.
        screen_h = win.winfo_screenheight()
        available_h = max(260, screen_h - 380)
        max_rows_h = available_h - header_h - footer_h
        max_rows_per_col = max(1, (max_rows_h - 26 - 18) // 36)
        if rows_per_col > max_rows_per_col:
            rows_per_col = max_rows_per_col

        cols_wanted = min(GOLDBACH_VIZ_MAX_COLS, max(1, -(-len(rows) // rows_per_col))) \
            if rows else 1

        EQ_W, PLUS_W, GAP, COL_GAP = 16, 16, 8, 28
        card_w = n_box_w + GAP + EQ_W + GAP + p_box_w + GAP + PLUS_W + GAP + q_box_w
        right_x = 16 + box_w + 20

        # Cap the diagram to what actually fits ON SCREEN (not just what fits in
        # the CANVAS) -- Artur reported a wide n (e.g. n=10_000_000, 8-digit
        # values) producing a Toplevel wider than his screen, with the rightmost
        # column of "n = p + q" cards simply run off the edge (no scrollbar, no
        # way to reach it). Per his instruction ("jeśli nie zmieści się w oknie
        # kolumna sum to niech się nie wyświetla") a column that would push the
        # window past screen width is dropped entirely rather than drawn
        # off-screen -- the truncation note below then reports the real shown/total
        # count so it's clear more rows exist (use n or Eksportuj CSV to see them).
        screen_w = win.winfo_screenwidth()
        available_w = max(700, screen_w - 150)  # leave room for window chrome/taskbar
        fit_cols = max(1, (available_w - right_x - 16 + COL_GAP) // (card_w + COL_GAP))
        cols = max(1, min(cols_wanted, fit_cols))
        rows_drawn = min(len(rows), cols * rows_per_col)
        grid_w = cols * card_w + (cols - 1) * COL_GAP

        canvas_w = max(
            16 + box_w + 20 + grid_w + 16,
            16 + box_w + 16 + 300,  # never narrower than a comfortable minimum
        )
        chips_h = 48 + chip_rows * 36
        rows_truncated = result["rows_truncated"] or rows_drawn < len(rows)
        # Height reserved for the tallest column actually drawn -- with the fixed
        # (non-rebalanced) rows_per_col assignment below, every column except
        # possibly the last is exactly rows_per_col tall, so min(rows_per_col,
        # rows_drawn) is always correct: it's rows_per_col once there's enough to
        # fill a full column, or just rows_drawn for a single partial column (e.g.
        # a small window with only a handful of rows total -- reserving a full
        # page's height for those would leave a large empty gap below them, the
        # same "wasted space" complaint this diagram had before).
        rows_per_col_used = max(1, min(rows_per_col, rows_drawn))
        rows_h = 26 + rows_per_col_used * 36 + (18 if rows_truncated else 0)
        canvas_h = header_h + max(chips_h, rows_h) + footer_h
        canvas.configure(width=canvas_w, height=canvas_h)

        canvas.create_text(
            16, 18, anchor="nw", font=("TkDefaultFont", 13, "bold"),
            text=T("research_goldbach.viz_header",
                   n=result["n"], pmax=result["pmax"], window_max=result["window_max"]))
        canvas.create_text(
            16, 44, anchor="nw", font=("TkDefaultFont", 9), fill="#64748b",
            width=canvas_w - 32,
            text=T("research_goldbach.viz_subheader"))
        canvas.create_text(
            16, 82, anchor="nw", font=("TkDefaultFont", 8), fill="#166534",
            text=T("research_goldbach.viz_legend_new_q"))

        top_y = header_h

        canvas.create_rectangle(16, top_y, 16 + box_w, top_y + chips_h,
                                 outline="#2563eb", width=1.5, fill="#eff6ff")
        canvas.create_text(16 + box_w / 2, top_y + 16, font=("TkDefaultFont", 10, "bold"),
                            fill="#1d4ed8", text=T("research_goldbach.viz_old_base_title"))
        canvas.create_text(
            16 + box_w / 2, top_y + 32, font=("TkDefaultFont", 8), fill="#3b82f6",
            text=T("research_goldbach.viz_old_base_subtitle", pmax=result["pmax"]))
        chip_h_px = 30
        start_x = 16 + 12
        start_y = top_y + 46
        for i, p in enumerate(chip_shown):
            col, row = i % chip_cols, i // chip_cols
            x0 = start_x + col * (chip_w + chip_gap)
            y0 = start_y + row * (chip_h_px + chip_gap)
            canvas.create_rectangle(x0, y0, x0 + chip_w, y0 + chip_h_px,
                                     outline="#93c5fd", width=1.5, fill="white")
            canvas.create_text(x0 + chip_w / 2, y0 + chip_h_px / 2,
                                font=("TkDefaultFont", 10, "bold"), fill="#1d4ed8",
                                text=str(p))

        row_y = top_y
        canvas.create_text(
            right_x, row_y, anchor="nw", font=("TkDefaultFont", 10, "bold"),
            width=canvas_w - right_x - 16,
            text=T("research_goldbach.viz_segment_title",
                   range_min=result["range_min"], range_max=result["range_max"]))
        grid_top_y = row_y + 26
        for i, row in enumerate(rows[:rows_drawn]):
            col_idx = i // rows_per_col
            within_idx = i % rows_per_col
            cx = right_x + col_idx * (card_w + COL_GAP)
            cy = grid_top_y + within_idx * 36
            n = row["n"]
            p = row["p"] if row["p"] is not None else "?"
            q = row["q"] if row["q"] is not None else "?"
            x = cx
            canvas.create_rectangle(x, cy, x + n_box_w, cy + 26,
                                     fill="#0f172a", outline="")
            canvas.create_text(x + n_box_w / 2, cy + 13, fill="white",
                                font=("TkDefaultFont", 10, "bold"), text=str(n))
            x += n_box_w + GAP
            canvas.create_text(x + EQ_W / 2, cy + 13, fill="#94a3b8", text="=")
            x += EQ_W + GAP
            canvas.create_rectangle(x, cy, x + p_box_w, cy + 26,
                                     outline="#2563eb", width=1.5, fill="#dbeafe")
            canvas.create_text(x + p_box_w / 2, cy + 13, fill="#1d4ed8",
                                font=("TkDefaultFont", 10, "bold"), text=str(p))
            x += p_box_w + GAP
            canvas.create_text(x + PLUS_W / 2, cy + 13, fill="#94a3b8", text="+")
            x += PLUS_W + GAP
            # q is drawn in the SAME blue as p -- both_base_window_rows only ever
            # records a witness with q <= Pmax too (matching Lean's
            # additiveSelfContained_of_hasGoldbachRep), so q is exactly as much
            # "in the base" as p is here, not just informational. (An amber/
            # warning-orange coloring for q > Pmax briefly existed when this
            # diagram tracked buildableFromBase, which only bounds p -- removed
            # per Artur, 2026-08-17: "skoro wszystkie są budowalne z bazy to
            # takie wyświetlajmy", and now moot besides, since q > Pmax is never
            # a witness this mode returns at all.)
            q_fill, q_outline = "#dbeafe", "#2563eb"
            canvas.create_rectangle(x, cy, x + q_box_w, cy + 26,
                                     outline=q_outline, width=1.5, fill=q_fill)
            canvas.create_text(x + q_box_w / 2, cy + 13, fill=q_outline,
                                font=("TkDefaultFont", 10, "bold"), text=str(q))
        grid_bottom_y = grid_top_y + rows_per_col_used * 36
        if rows_truncated:
            canvas.create_text(
                right_x, grid_bottom_y + 2, anchor="nw", font=("TkDefaultFont", 8),
                fill="#64748b",
                text=T("research_goldbach.viz_rows_truncated",
                       shown=rows_drawn, total=result["segment_size"]))

        # total_row_pages is derived from segment_size/ROW_CAP -- deliberately NOT
        # from rows_drawn (the on-screen, possibly-narrower-than-a-page count from
        # the column-dropping above). A screen-width-dropped column means more of
        # THIS SAME page would show if the window were wider, not that turning the
        # page would reveal it -- so Next must only look available when there's
        # genuinely another page of window beyond this one.
        row_page = result.get("row_page", 0)
        total_row_pages = max(
            1, -(-result["segment_size"] // GOLDBACH_CASCADE_ROW_CAP))
        self._update_nav_controls(
            self.goldbach_viz_row_page_label, row_page, total_row_pages,
            self.goldbach_viz_row_prev_btn, self.goldbach_viz_row_next_btn)

        footer_y = top_y + max(chips_h, rows_h) + 16
        if result["covered"]:
            footer_text = T("research_goldbach.viz_summary_covered",
                             segment_size=result["segment_size"])
            footer_color = "#166534"
        else:
            footer_text = T(
                "research_goldbach.viz_summary_void",
                counterexamples=", ".join(str(x) for x in result["counterexamples"]))
            footer_color = "#991b1b"
        canvas.create_text(16, footer_y, anchor="nw", font=("TkDefaultFont", 10, "bold"),
                            fill=footer_color, width=canvas_w - 32, text=footer_text)

        # Reset any size the user (or a previous, differently-sized diagram) left
        # the Toplevel at, so it re-fits itself to THIS canvas's actual content
        # instead of staying stretched -- see _goldbach_ensure_viz_window's note.
        win.geometry("")
