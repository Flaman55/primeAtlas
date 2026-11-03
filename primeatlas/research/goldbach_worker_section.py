"""
goldbach_worker_section.py -- GoldbachWorkerSection, the Goldbach sub-tab's background
job: _goldbach_job runs the "window", "viz" and "decompose" ops on the tab's
background.PersistentWorker thread, and the main-thread callbacks route each result or
progress tick to the matching view (main results table, Visualize, decompose detail).

A ResearchGoldbachTab mixin: it uses the widgets, worker and state that ResearchGoldbachTab
and its other mixins set up, so it is never instantiated on its own.
"""

import tkinter as tk
from tkinter import messagebox

from ..core.progress_bar_owner import claim_progress_bar
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
from .goldbach_paging import GOLDBACH_CASCADE_ROW_CAP, GOLDBACH_DECOMPOSE_ROW_CAP


class GoldbachWorkerSection:
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
        on-disk archive (read_is_prime_from_storage, up to 2*n -- a safe upper
        bound since Pmax <= n means 2*Pmax <= 2*n); Visualize reads from
        storage rather than recomputing a fresh sieve. Then runs
        goldbach_window.window_rows(is_prime, Pmax, ...) over
        that SAME array -- both the Pmax resolution and the window check share one
        storage read. job["row_page"] (default 0) selects which PAGE of
        decomposition rows to compute (see GOLDBACH_CASCADE_ROW_CAP and the
        row_offset param it's paired with) -- re-reads storage and re-derives Pmax
        every page turn rather than caching, same cost profile as re-running the
        whole check, which is acceptable since it's already async off the GUI
        thread. Mid-job progress ticks from both_base_window_rows' own
        progress_cb are relayed via report_progress -- PersistentWorker's own
        channel, kept separate from the (op, ok, payload) result tuple so
        progress updates never have to be told apart from a finished job.

        "decompose" -- job carries an explicit "pmax" (the ALREADY-displayed
        window's Pmax, not re-derived from n, since the target n here is a
        separate probe, not necessarily inside that window). Reads storage up to
        n itself (only need is_prime long enough to index n), then runs
        goldbach_window.all_decompositions(is_prime, n, pmax, cap=...) -- the
        exhaustive "sliding window" scan answering whether n
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
                # Visualize's only window: [4, Pmax+GOLDBACH_BOTH_BASE_PMIN],
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
        running. Claims the shared bar first (see progress_bar_owner.py) -- a no-op
        if _goldbach_set_busy(True)'s own _start_busy_progress() call never actually
        got it (some other owner had it throughout)."""
        if claim_progress_bar(self.totals_progress, self):
            self.totals_progress.stop()
            self.totals_progress.configure(mode="determinate", maximum=1, value=payload)
        self._goldbach_viz_progress_set(value=payload)

    def _on_goldbach_worker_result(self, payload, error):
        """Main-thread callback for _goldbach_job, delivered via PersistentWorker.
        Wrapped in its own try/except
        (Exception, not just letting it propagate) so that ONE bad message -- e.g.
        a result arriving for a Toplevel (Visualize or decompose) the user
        already closed -- can never raise up through PersistentWorker's own
        _poll() and skip ITS self.widget.after() reschedule, which would silently
        kill polling for the rest of the session (background.PersistentWorker._poll
        does not wrap on_result itself -- see _goldbach_widget_configure's own
        docstring for the same failure mode on a closed Toplevel's widgets).
        `error` is only non-None for a genuine PersistentWorker-framework bug
        (_goldbach_job already catches its own exceptions -- see its docstring)."""
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
                if (isinstance(result_payload, dict)
                        and result_payload.get("kind") == "storage_missing"):
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
        """Mirrors totals_progress's own state onto the Visualize Toplevel's
        OWN Progressbar (see _goldbach_ensure_viz_window):
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
