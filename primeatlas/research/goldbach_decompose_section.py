"""
goldbach_decompose_section.py -- GoldbachDecomposeSection, the "Show all decompositions"
detail Toplevel opened from the Visualize window: every prime pair (p, q) summing to one
even n, flagged against the displayed window's Pmax, one worker call per page of
GOLDBACH_DECOMPOSE_ROW_CAP pairs.

A ResearchGoldbachTab mixin: it uses the widgets, worker and state that ResearchGoldbachTab
and its other mixins set up, so it is never instantiated on its own.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from ..core.widgets import StripedTreeview

GOLDBACH_DECOMPOSE_ROW_CAP = 300  # defensive cap on how many (p, q) pairs the "Decompose
    # number" detail window displays (see goldbach_all_decompositions + _goldbach_show_
    # decomposition_detail) -- the old_base_sufficient verdict and total count are
    # always computed over the FULL scan regardless of this cap, only the displayed
    # rows are truncated.


class GoldbachDecomposeSection:
    def _on_goldbach_viz_decompose(self):
        """"Show all decompositions" -- reads a target n from the Visualize
        window's own decompose field and exhaustively scans EVERY prime pair
        summing to it (goldbach_all_decompositions), flagged against the Pmax of
        the window currently displayed above (self._goldbach_viz_last_result).
        Needs a window to already be checked (for its Pmax) -- unlike the main n
        field, this one is not restricted to n's inside [4, 2*Pmax], since the
        question ("does n need a prime outside Pmax's base") makes sense for any
        even n being probed, not just ones already in the current window."""
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
        current_pmax -- shared by the initial "Show all decompositions" click and
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

        # Prev/label/Next/goto -- same layout as the Visualize's own row_nav,
        # needed here for the same reason: a large n can have tens of thousands of
        # pairs (e.g. n~=9999992 yields 53364), so a static
        # "(showing first 300 of 53364)" truncation note with no way to see the
        # rest is insufficient.
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
        tree = StripedTreeview(
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
        computed over the whole scan regardless of which page is showing. Lean's
        own buildableFromBase only ever bounds p, never q (see goldbach_window.py's
        module docstring) -- so the per-row "Where q is from" column is PURELY
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
