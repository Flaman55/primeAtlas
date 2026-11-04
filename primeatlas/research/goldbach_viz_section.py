"""
goldbach_viz_section.py -- GoldbachVizSection, the Goldbach sub-tab's Visualize Toplevel:
its od/do range fields and check button, the queued "viz" job for one page of rows, the
OLD BASE chip pagination (client-side) and sums-grid row pagination (one worker call per
page), and the Canvas diagram of the both-base window [4, Pmax+GOLDBACH_BOTH_BASE_PMIN].

A ResearchGoldbachTab mixin: it uses the widgets, worker and state that ResearchGoldbachTab
and its other mixins set up, so it is never instantiated on its own.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from ..core.ui_state import remember
from .goldbach_paging import (
    GOLDBACH_CASCADE_ROW_CAP, GOLDBACH_VIZ_MAX_COLS, GOLDBACH_VIZ_ROWS_PER_COL)


GOLDBACH_VIZ_CHIP_ROWS_PER_PAGE = 6  # old-base prime chips: how many CHIP ROWS (not
    # individual chips -- chip_cols varies with Pmax's digit count) are shown per page
    # before Prev/Next must be used. Purely a client-side page (old_base_primes is
    # already fully computed by the backend), unlike row pagination above which needs
    # a fresh backend call per page.


class GoldbachVizSection:
    def _on_goldbach_viz_refresh(self):
        """The Visualize Toplevel's OWN "Check window" button -- reads "do"
        from ITS OWN field (self.goldbach_viz_n_entry, still validated via
        _goldbach_parse_n_from -- "do" is the n that Pmax is derived from), not the
        main tab's, so the window is self-sufficient
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
        what Pmax is derived from (largest prime <= n, as in the main tab's n
        field), AND it's the scan's own upper bound. reset_page=
        True (the default, used by a fresh "Check window" click from either the
        main tab or the Visualize window's own button) starts back at
        row/chip page 0, since a different n means a different window and a
        different old base entirely. reset_page=False (used by the row
        Prev/Next handlers below) keeps whatever self._goldbach_viz_row_page was
        already set to by the caller.

        "od" is read fresh from goldbach_viz_range_from_entry every call (not
        cached, via getattr since that Entry only exists once the Visualize
        Toplevel has actually been built). od/do form a single validated range
        rather than two independent optional ranges (a standalone "n" field plus
        a separate blank-defaults range is ambiguous about which one governs the
        scan): od defaults to 4 (not blank) and is validated here on every
        call (>=4, and <= n-2 so at least one even number is actually in
        range) -- an invalid od blocks the job with a clear error instead of
        silently clamping into something the person didn't ask for."""
        T = self.T
        if self._goldbach_busy:
            return
        from_entry = getattr(self, "goldbach_viz_range_from_entry", None)
        from_raw = from_entry.get().strip() if from_entry is not None else ""
        n_min = self._eval_quick_number(from_raw) if from_raw else 4
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
        """Sums-grid "Previous" -- steps back one PAGE of decomposition rows
        (GOLDBACH_CASCADE_ROW_CAP per page). Needs a fresh worker call (see
        _goldbach_queue_viz's own docstring) since only one page's rows are ever
        held in memory at a time."""
        if self._goldbach_busy or self._goldbach_viz_current_n is None:
            return
        if self._goldbach_viz_row_page > 0:
            self._goldbach_viz_row_page -= 1
            self._goldbach_queue_viz(self._goldbach_viz_current_n, reset_page=False)

    def _on_goldbach_viz_row_next(self):
        """Sums-grid "Next" -- see _on_goldbach_viz_row_prev. The Next button is
        disabled once goldbach_window_rows() reports rows_truncated=False for the
        current page (see _goldbach_show_window_visualization), so this doesn't
        need its own upper-bound check."""
        if self._goldbach_busy or self._goldbach_viz_current_n is None:
            return
        self._goldbach_viz_row_page += 1
        self._goldbach_queue_viz(self._goldbach_viz_current_n, reset_page=False)

    def _on_goldbach_viz_row_goto(self):
        """Sums-grid "Go" -- jumps directly to a typed page number instead of
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
        """OLD BASE "Previous" -- purely client-side: old_base_primes is
        already fully present in the last worker result, so paging through it is
        just a redraw with a different slice, no worker round-trip needed."""
        if self._goldbach_viz_chip_page > 0:
            self._goldbach_viz_chip_page -= 1
            if self._goldbach_viz_last_result is not None:
                self._goldbach_show_window_visualization(self._goldbach_viz_last_result)

    def _on_goldbach_viz_chip_next(self):
        """OLD BASE "Next" -- see _on_goldbach_viz_chip_prev. Clamped against
        the true page count inside _goldbach_show_window_visualization, so an extra
        click past the end is harmless (the Next button is also disabled there)."""
        self._goldbach_viz_chip_page += 1
        if self._goldbach_viz_last_result is not None:
            self._goldbach_show_window_visualization(self._goldbach_viz_last_result)

    def _on_goldbach_viz_chip_goto(self):
        """OLD BASE "Go" -- pure client-side like chip prev/next, so this just
        sets the page and redraws; _goldbach_show_window_visualization clamps it
        against the true page count itself (same as it already does for chip
        prev/next going past either end)."""
        raw = self.goldbach_viz_chip_goto_entry.get().strip()
        if not raw.isdigit():
            return
        self._goldbach_viz_chip_page = max(0, int(raw) - 1)
        if self._goldbach_viz_last_result is not None:
            self._goldbach_show_window_visualization(self._goldbach_viz_last_result)

    def _goldbach_ensure_viz_window(self):
        """Creates the Visualize Toplevel the first time it's needed, or returns
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

        # Single od/do row: one range to reason about. "do" determines Pmax
        # (goldbach_viz_n_entry / _goldbach_parse_n_from, derived from whatever's
        # typed as the upper bound); "od" defaults to 4 (not blank) and is validated
        # against "do" in _goldbach_queue_viz (>=4, and <= do-2 so at least one even
        # n exists in the range), so the button always operates on a concrete,
        # well-formed range.
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
        remember("research.goldbach_viz.range_from", self.goldbach_viz_range_from_entry)
        remember("research.goldbach_viz.n", self.goldbach_viz_n_entry)
        self.goldbach_viz_check_button = ttk.Button(
            top, text=T("research_goldbach.run_button"),
            command=self._on_goldbach_viz_refresh)
        self.goldbach_viz_check_button.pack(side="left")
        ttk.Label(win, text=T("research_goldbach.viz_range_hint"),
                  wraplength=780, justify="left", style="Hint.TLabel").pack(
            anchor="w", padx=10, pady=(0, 6))

        self.goldbach_viz_status_var = tk.StringVar(value="")
        ttk.Label(win, textvariable=self.goldbach_viz_status_var,
                  wraplength=780, justify="left", style="Hint.TLabel").pack(
            anchor="w", padx=10, pady=(0, 6))

        # Own Progressbar, separate from the shared self.totals_progress in the
        # MAIN window: the shared bottom bar is invisible while this
        # Toplevel is maximized/fullscreen over it. Mirrored in lockstep with
        # totals_progress by _goldbach_viz_progress_set (see its own
        # docstring), called from every place that already updates
        # totals_progress (_goldbach_set_busy, _on_goldbach_worker_progress) so
        # the two never drift out of sync.
        self.goldbach_viz_progress = ttk.Progressbar(
            win, mode="determinate", maximum=1, value=0)
        self.goldbach_viz_progress.pack(fill="x", padx=10, pady=(0, 6))

        # "Decompose number" -- the smallest-witness search (_smallest_witness /
        # window_rows) can land on a pair
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
        remember("research.goldbach_viz.decompose", self.goldbach_viz_decompose_entry)
        self.goldbach_viz_decompose_button = ttk.Button(
            decompose_row, text=T("research_goldbach.viz_decompose_button"),
            command=self._on_goldbach_viz_decompose)
        self.goldbach_viz_decompose_button.pack(side="left")

        # Two INDEPENDENT navigation rows, matching the Prev/Next paging pattern
        # used elsewhere for large lists (Primes tab preview,
        # benchmark log -- see _update_nav_controls). OLD BASE pages through
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

        # NOT fill="both"/expand=True here: filling the whole Toplevel would stretch
        # the Canvas widget to the window's size (its drawn content still covering only
        # its own configured width/height), leaving a big blank area to the right and
        # pinning everything to the top-left. Packed at its natural size, the Toplevel
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

    def _goldbach_show_window_visualization(self, result):
        """Redraws the "old base vs window" diagram into the PERSISTENT Visualize
        Toplevel/Canvas (see _goldbach_ensure_viz_window) -- built from a REAL
        window_rows() result sourced from the archive
        (read_is_prime_from_storage), covering EXACTLY the window [4, 2*Pmax] that
        "Check window" also checks (never a separate cascade step -- see
        goldbach_window.window_rows' own docstring). The window itself, its n
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
        # that can end up scrolled or clipped off screen for a tall diagram, so
        # it's repeated here in the status label at the TOP of the
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

        # chip_cols (and therefore the "OLD BASE" box width) is derived from
        # chip_w, not hardcoded: chip_w grows with Pmax's digit count, so a fixed
        # column count in a fixed-width box would draw the overflow chips past the
        # box's right edge, on top of the row grid beside it. box_w fits chip_cols
        # columns EXACTLY, and chip_cols narrows for big primes instead.
        chip_cols_target_w = 210  # desired inner width for the chip grid
        chip_cols = max(3, chip_cols_target_w // (chip_w + chip_gap))
        box_w = 24 + chip_cols * chip_w + (chip_cols - 1) * chip_gap

        # OLD BASE pagination (client-side, see _on_goldbach_viz_chip_prev/_next):
        # old_base_primes can hold hundreds of thousands of entries for a large
        # Pmax, so only ONE page's worth is ever sliced for drawing, matching the
        # Prev/Next browsing pattern used elsewhere in the app
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
        # strip: the window is sized to fit its content (see _goldbach_ensure_viz_
        # window's note on why the canvas is not packed with fill/expand), so a
        # single column would leave a narrow diagram with a large blank area beside it.
        rows_per_col = GOLDBACH_VIZ_ROWS_PER_COL
        header_h = 106
        footer_h = 60

        # Cap rows_per_col to what actually fits ON SCREEN VERTICALLY, mirroring
        # the column-width cap just below: the controls packed above the canvas
        # (_goldbach_ensure_viz_window) can make a full 3x14-row page (n=1000) tall
        # enough that the canvas -- and with it the
        # "segment covered" / counterexamples summary drawn at its very bottom --
        # runs off the bottom of the screen with no scrollbar to reach it. Unlike
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
        # the CANVAS): a wide n (e.g. n=10_000_000, 8-digit
        # values) can produce a Toplevel wider than the screen, with the rightmost
        # column of "n = p + q" cards simply running off the edge (no scrollbar, no
        # way to reach it). A column that would push the
        # window past screen width is dropped entirely rather than drawn
        # off-screen -- the truncation note below then reports the real shown/total
        # count so it's clear more rows exist (use n or  to see them).
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
        # page's height for those would leave a large empty gap below them).
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
            # "in the base" as p is here, not just informational: q > Pmax is
            # never a witness this window returns.
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
