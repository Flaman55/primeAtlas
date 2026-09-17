"""
research_pi_approx_tab.py -- ResearchPiApproxTab, the tkinter widgets for
the Research tab's Przyblizenia pi(x) (pi(x) approximations) sub-tab:
compares the real prime-counting function pi(x) against li(x) and Riemann's
R(x) at a set of checkpoints x = x_from, x_from+step, ..., x_to, via
primeatlas/pi_approx_window.py's pure check_pi_approx_range()/check_pi_
approx_range_from_source().

Same shape as ResearchSquaresTab/ResearchPolynomialsTab/ResearchGapsTab
(see any of their own docstrings for the full data-source-toggle/CSV-
export history this mirrors from day one): a data-source toggle ("Świeże
sito" / "Dane z archive", storage mode via
primeatlas/research_pi_approx.py's read_is_prime_from_storage), pagination,
and CSV export of the currently-displayed page.

Unlike every other Research sub-tab, there is no conjecture verdict at all
here (not even Gaps' per-overlay covered/counterexamples for two of its
three overlays) -- this is purely a measurement/accuracy comparison, so the
summary reports the largest li(x)/R(x) error seen in the range instead of
any pass/fail statement (see pi_approx_window.py's own module docstring).

A THIRD data-source mode, "primecount", calls Kim Walisch's libprimecount -- a
companion library to primesieve, already used elsewhere in this project
(see prime_sieve/prime_sieve_primesieve.py) -- via ctypes, through the exact
same wsl.exe-subprocess SHAPE primesieve_calc_tab.py's calculator sub-tab
established (build_primesieve_query_argv/run_primesieve_query_wsl there;
build_primecount_query_argv/run_primecount_wsl_blocking here, both living in
primeatlas/generation.py alongside their CUDASieve counterparts -- see that
module's own docstrings). Unlike the sieve/storage modes, this one needs no
is_prime array at all -- primecount computes pi(x) directly via a
combinatorial algorithm (see prime_sieve/prime_count_primecount.py's own
module docstring), so it reaches x far past MAX_SIEVE_BOUND (verified live:
pi(10**15) in ~0.1s on a 24-core WSL box). Wired into pi_approx_window.
check_pi_approx_range_with_pi_func(), the third entry point that skips the
is_prime array entirely.

Batched ONE wsl.exe round trip per PAGE (primecount_query.py's "pi_batch"
op, all of that page's checkpoints in one call) rather than one round trip
per row -- a real cost when each round trip is a separate process launch.

libprimecount is a WSL apt package (primecount, libprimecount8,
libprimecount-dev, libprimecount-dev-common) NOT part of env_setup.py's
REQUIRED_APT_PACKAGES -- research-module-specific optional C libraries get an
on-demand install mechanism instead of a blanket first-run install everyone
pays for. The INSTALL mechanism belongs in Settings -> Aktualizacje (see settings_tab.py's
own primecount section) alongside every other optional-component installer
in this app, not duplicated here -- this tab only ever OFFERS to install
(a small Zainstaluj/Anuluj dialog, triggered the moment a "primecount"-mode
query actually fails because the library isn't there yet, see
_offer_install_primecount below), reusing that exact same generation.py
install function rather than a second copy of it."""
import csv
import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from . import background
from .base_tab import BaseTab
from .generation import (
    build_primecount_query_argv, run_primecount_wsl_blocking,
    run_primecount_install_wsl_blocking,
)
from .pi_approx_window import (
    check_pi_approx_range, check_pi_approx_range_from_source,
    check_pi_approx_range_with_pi_func, MAX_SIEVE_BOUND,
)
from .research_pi_approx import read_is_prime_from_storage, MissingStorageRangeError

PI_APPROX_ROW_CAP = 200
"""Rows per page in the results Treeview -- same "stats always computed
over the FULL range, only the display paginates" contract as
squares_window.check_interval_range's own row_cap/row_offset."""


class _PrimecountNotInstalled(Exception):
    """Raised internally (never crosses out of _pi_job) when a "primecount"-mode
    query fails specifically because libprimecount itself isn't loadable
    (run_primecount_wsl_blocking's own {"kind": "not_installed"} contract) --
    caught separately from every other ValueError so _on_pi_worker_result can
    offer the install prompt instead of a generic error dialog."""


class ResearchPiApproxTab(BaseTab):
    def __init__(self, parent, translator, totals_progress, eval_quick_number,
                 get_portal_folder, status_var):
        """Same dependency-injection pattern as ResearchSquaresTab/
        ResearchPolynomialsTab/ResearchGapsTab -- see any of their own
        docstrings for what each parameter is for. eval_quick_number parses
        the plain integer x_from/x_to/step fields (x_from >= 2 -- li(x)/
        R(x) are only implemented for x > 1, see pi_approx_window.py's own
        docstring)."""
        super().__init__(parent, translator)
        self.totals_progress = totals_progress
        self._eval_quick_number = eval_quick_number
        self._get_portal_folder = get_portal_folder
        self.status = status_var

        self._pi_busy = False
        self._pi_worker = background.PersistentWorker(
            self, self._pi_job, on_result=self._on_pi_worker_result)
        self._pi_last_result = None
        self._pi_page = 0
        # Set just before submitting an "install_primecount" job triggered from
        # _offer_install_primecount()'s dialog -- the exact "run" job dict that
        # failed because primecount wasn't installed, so a successful install can
        # automatically retry it without a second manual click (see
        # _on_pi_worker_result's own "install_primecount" branch).
        self._pi_pending_retry_job = None

        self._build_widgets()

    def _build_widgets(self):
        T = self.T
        range_row = ttk.Frame(self)
        range_row.pack(fill="x", padx=6, pady=(10, 4))
        ttk.Label(range_row, text=T("research_pi_approx.x_from_label")).pack(side="left")
        self.pi_x_from_entry = ttk.Entry(range_row, width=14)
        self.pi_x_from_entry.insert(0, "100")
        self.pi_x_from_entry.pack(side="left", padx=(6, 16))
        ttk.Label(range_row, text=T("research_pi_approx.x_to_label")).pack(side="left")
        self.pi_x_to_entry = ttk.Entry(range_row, width=14)
        self.pi_x_to_entry.insert(0, "100000")
        self.pi_x_to_entry.pack(side="left", padx=(6, 16))
        ttk.Label(range_row, text=T("research_pi_approx.step_label")).pack(side="left")
        self.pi_step_entry = ttk.Entry(range_row, width=14)
        self.pi_step_entry.insert(0, "10000")
        self.pi_step_entry.pack(side="left", padx=(6, 0))

        source_row = ttk.Frame(self)
        source_row.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(source_row, text=T("research_pi_approx.source_label")).pack(side="left")
        self.pi_source_var = tk.StringVar(value="sieve")
        ttk.Radiobutton(
            source_row, text=T("research_pi_approx.source_sieve"),
            variable=self.pi_source_var, value="sieve").pack(side="left", padx=(6, 0))
        ttk.Radiobutton(
            source_row, text=T("research_pi_approx.source_storage"),
            variable=self.pi_source_var, value="storage").pack(side="left", padx=(10, 0))
        ttk.Radiobutton(
            source_row, text=T("research_pi_approx.source_primecount"),
            variable=self.pi_source_var, value="primecount").pack(side="left", padx=(10, 0))

        button_row = ttk.Frame(self)
        button_row.pack(fill="x", padx=6, pady=(0, 8))
        self.pi_run_button = ttk.Button(
            button_row, text=T("research_pi_approx.run_button"), command=self._on_pi_run)
        self.pi_run_button.pack(side="left")
        self.pi_prev_button = ttk.Button(
            button_row, text=T("research_pi_approx.prev_button"),
            command=self._on_pi_prev, state="disabled")
        self.pi_prev_button.pack(side="left", padx=(16, 0))
        self.pi_next_button = ttk.Button(
            button_row, text=T("research_pi_approx.next_button"),
            command=self._on_pi_next, state="disabled")
        self.pi_next_button.pack(side="left", padx=(6, 0))
        self.pi_export_button = ttk.Button(
            button_row, text=T("research_pi_approx.export_csv_button"),
            command=self._on_pi_export_csv, state="disabled")
        self.pi_export_button.pack(side="left", padx=(16, 0))

        ttk.Label(self, text=T("research_pi_approx.hint"),
                  wraplength=760, justify="left", foreground="#555").pack(
            anchor="w", padx=6, pady=(0, 8))

        self.pi_summary_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.pi_summary_var,
                  wraplength=760, justify="left").pack(anchor="w", padx=6, pady=(0, 8))

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        columns = ("x", "pi_x", "li_x", "r_x", "li_error", "r_error")
        self.pi_results_tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", height=16)
        self.pi_results_tree.heading("x", text=T("research_pi_approx.col_x"))
        self.pi_results_tree.heading("pi_x", text=T("research_pi_approx.col_pi_x"))
        self.pi_results_tree.heading("li_x", text=T("research_pi_approx.col_li_x"))
        self.pi_results_tree.heading("r_x", text=T("research_pi_approx.col_r_x"))
        self.pi_results_tree.heading("li_error", text=T("research_pi_approx.col_li_error"))
        self.pi_results_tree.heading("r_error", text=T("research_pi_approx.col_r_error"))
        self.pi_results_tree.column("x", width=110, anchor="e")
        self.pi_results_tree.column("pi_x", width=110, anchor="e")
        self.pi_results_tree.column("li_x", width=110, anchor="e")
        self.pi_results_tree.column("r_x", width=110, anchor="e")
        self.pi_results_tree.column("li_error", width=90, anchor="e")
        self.pi_results_tree.column("r_error", width=90, anchor="e")
        svsb = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self.pi_results_tree.yview)
        self.pi_results_tree.configure(yscrollcommand=svsb.set)
        self.pi_results_tree.pack(side="left", fill="both", expand=True)
        svsb.pack(side="right", fill="y")

    def _parse_positive_int(self, entry, field_name_key, min_value=1):
        T = self.T
        value = self._eval_quick_number(entry.get())
        if value is None or value < min_value:
            raise ValueError(T("research_pi_approx.error_field_int",
                                field=T(field_name_key), min_value=min_value))
        return value

    def _on_pi_run(self):
        T = self.T
        if self._pi_busy:
            return
        try:
            x_from = self._parse_positive_int(self.pi_x_from_entry, "research_pi_approx.x_from_label", 2)
            x_to = self._parse_positive_int(self.pi_x_to_entry, "research_pi_approx.x_to_label", 2)
            if x_to < x_from:
                raise ValueError(T("research_pi_approx.error_range_order"))
            step = self._parse_positive_int(self.pi_step_entry, "research_pi_approx.step_label", 1)
        except ValueError as e:
            messagebox.showerror(T("research_pi_approx.error_dialog_title"), str(e))
            return

        self._pi_set_busy(True)
        self._pi_worker.submit({
            "x_from": x_from, "x_to": x_to, "step": step,
            "source": self.pi_source_var.get(), "page": 0,
        })

    def _on_pi_prev(self):
        if self._pi_page > 0:
            self._pi_requeue_page(self._pi_page - 1)

    def _on_pi_next(self):
        self._pi_requeue_page(self._pi_page + 1)

    def _pi_requeue_page(self, page):
        last = self._pi_last_result
        if last is None or self._pi_busy:
            return
        self._pi_set_busy(True)
        self._pi_worker.submit({
            "x_from": last["x_from"], "x_to": last["x_to"], "step": last["step"],
            "source": last.get("source", "sieve"), "page": page,
        })

    def _pi_set_busy(self, busy):
        self._pi_busy = busy
        self.pi_run_button.configure(state="disabled" if busy else "normal")
        if busy:
            self.pi_prev_button.configure(state="disabled")
            self.pi_next_button.configure(state="disabled")
            self.pi_export_button.configure(state="disabled")
            self._start_busy_progress()
        else:
            self._stop_busy_progress()

    def _pi_job(self, job, _report_progress):
        """Runs on PersistentWorker's own daemon thread -- see
        ResearchSquaresTab._squares_job's own docstring for the single-
        owner-thread contract this relies on and why job["source"] picking
        between "sieve"/"storage"/"primecount" applies the SAME
        MAX_SIEVE_BOUND ceiling to the first two either way ("primecount"
        has none of its own, see pi_approx_window.check_pi_approx_range_
        with_pi_func's own docstring). Returns a (kind, ok, data) 3-tuple:
        "run" for an ordinary checkpoint sweep (data is the same result
        dict every source has always returned, or an error string on
        failure), "primecount_not_installed" specifically when a
        "primecount"-mode query failed because the library isn't there yet
        (data is a ready-to-resubmit job dict, the exact one that just
        failed -- see _on_pi_worker_result's own handling), and
        "install_primecount" for the retry-triggered install itself (data
        is None on success, an error string otherwise)."""
        if job.get("kind") == "install_primecount":
            portal_folder = self._get_portal_folder()
            ok, err = run_primecount_install_wsl_blocking(portal_folder)
            return "install_primecount", ok, err

        try:
            if job["source"] == "storage":
                portal_folder = self._get_portal_folder()

                def source(limit, _folder=portal_folder):
                    if limit > MAX_SIEVE_BOUND:
                        raise ValueError(
                            f"the requested range needs data up to {limit:,}, above "
                            f"this tool's {MAX_SIEVE_BOUND:,} ceiling -- reduce x_to")
                    return read_is_prime_from_storage(_folder, limit)

                result = check_pi_approx_range_from_source(
                    job["x_from"], job["x_to"], job["step"], source,
                    row_cap=PI_APPROX_ROW_CAP, row_offset=job["page"] * PI_APPROX_ROW_CAP)
            elif job["source"] == "primecount":
                portal_folder = self._get_portal_folder()

                def pi_func(checkpoints, _folder=portal_folder):
                    argv = build_primecount_query_argv("pi_batch", *checkpoints)
                    ok, payload = run_primecount_wsl_blocking(argv, _folder, timeout=600)
                    if not ok:
                        if isinstance(payload, dict) and payload.get("kind") == "not_installed":
                            raise _PrimecountNotInstalled(payload.get("message", ""))
                        message = (payload.get("message") if isinstance(payload, dict)
                                   else str(payload))
                        raise ValueError(message)
                    return payload

                result = check_pi_approx_range_with_pi_func(
                    job["x_from"], job["x_to"], job["step"], pi_func,
                    row_cap=PI_APPROX_ROW_CAP, row_offset=job["page"] * PI_APPROX_ROW_CAP)
            else:
                result = check_pi_approx_range(
                    job["x_from"], job["x_to"], job["step"],
                    row_cap=PI_APPROX_ROW_CAP, row_offset=job["page"] * PI_APPROX_ROW_CAP)
            result["source"] = job["source"]
            result["page"] = job["page"]
            return "run", True, result
        except _PrimecountNotInstalled:
            return "primecount_not_installed", False, {
                "x_from": job["x_from"], "x_to": job["x_to"], "step": job["step"],
                "source": "primecount", "page": job["page"]}
        except MissingStorageRangeError as e:
            T = self.T
            return "run", False, T("research_pi_approx.error_storage_missing",
                                    floor=e.floor, upto=f"{e.needed_upto:,}")
        except ValueError as e:
            return "run", False, str(e)

    def _on_pi_worker_result(self, payload, error):
        T = self.T
        self._pi_set_busy(False)
        if error is not None:
            messagebox.showerror(T("research_pi_approx.error_dialog_title"), str(error))
            self._pi_refresh_nav_buttons()
            return
        kind, ok, data = payload
        if kind == "primecount_not_installed":
            self._pi_refresh_nav_buttons()
            self._offer_install_primecount(data)
            return
        if kind == "install_primecount":
            if ok:
                self.status.set(T("research_pi_approx.status_primecount_installed"))
                pending = self._pi_pending_retry_job
                self._pi_pending_retry_job = None
                if pending is not None:
                    self._pi_set_busy(True)
                    self._pi_worker.submit(pending)
                    return
            else:
                messagebox.showerror(T("research_pi_approx.error_dialog_title"),
                                      T("research_pi_approx.error_install_failed", detail=str(data)))
            self._pi_refresh_nav_buttons()
            return
        if not ok:
            messagebox.showerror(T("research_pi_approx.error_dialog_title"), str(data))
            self._pi_refresh_nav_buttons()
            return
        self._pi_show_result(data)

    def _offer_install_primecount(self, pending_job):
        """Shown the moment a "primecount"-mode query fails specifically because
        libprimecount isn't installed yet -- a small Zainstaluj/Anuluj dialog
        instead of a generic error message. A plain tkinter messagebox.askyesno can't carry custom
        button labels (Tk supplies its own stock Yes/No text), so this is a
        small dedicated Toplevel, same "own modal dialog for a two-choice
        prompt" idea as settings_tab.py's CUDASieve license-consent dialog,
        just without any license text to show. The Install button's own
        handler is a separate, PLAIN instance method (_start_primecount_
        install() below), not a closure kept only inside this dialog -- same
        split as that CUDASieve dialog's on_accept() calling settings_tab.
        py's own _start_cudasieve_build(), so a test can drive the "user
        accepted" path directly without needing to find/click a real Tk
        button buried inside a Toplevel it just created."""
        T = self.T
        dialog = tk.Toplevel(self)
        dialog.title(T("research_pi_approx.install_prompt_title"))
        dialog.transient(self.winfo_toplevel())
        dialog.resizable(False, False)
        dialog.grab_set()
        ttk.Label(dialog, text=T("research_pi_approx.install_prompt_message"),
                  wraplength=420, justify="left").pack(anchor="w", padx=16, pady=(16, 12))
        btn_row = ttk.Frame(dialog)
        btn_row.pack(fill="x", padx=16, pady=(0, 16))

        def on_install():
            dialog.destroy()
            self._start_primecount_install(pending_job)

        def on_cancel():
            dialog.destroy()

        ttk.Button(btn_row, text=T("research_pi_approx.install_prompt_install_button"),
                   command=on_install).pack(side="right", padx=(6, 0))
        ttk.Button(btn_row, text=T("research_pi_approx.install_prompt_cancel_button"),
                   command=on_cancel).pack(side="right")

    def _start_primecount_install(self, pending_job):
        """Actually starts the install job -- reuses the SAME generation.py install
        function Settings -> Aktualizacje's own primecount section calls (see that
        module's own docstring), remembering `pending_job` (the exact "run" job that
        just failed) so a successful install can automatically retry it, see
        _on_pi_worker_result's own "install_primecount" branch."""
        self._pi_pending_retry_job = pending_job
        self._pi_set_busy(True)
        self.status.set(self.T("research_pi_approx.status_installing_primecount"))
        self._pi_worker.submit({"kind": "install_primecount"})

    def _pi_refresh_nav_buttons(self):
        last = self._pi_last_result
        self.pi_prev_button.configure(
            state="normal" if last and self._pi_page > 0 else "disabled")
        self.pi_next_button.configure(
            state="normal" if last and last.get("rows_truncated") else "disabled")
        self.pi_export_button.configure(
            state="normal" if last and last.get("rows") else "disabled")

    def _on_pi_export_csv(self):
        """Exports the CURRENTLY DISPLAYED page's rows only -- same scope as
        ResearchSquaresTab._on_squares_export_csv (see its own docstring for
        why)."""
        result = self._pi_last_result
        if not result or not result.get("rows"):
            return
        T = self.T
        default_name = (
            f"pi_approx_x{result['x_from']}-{result['x_to']}_step{result['step']}_"
            f"page{result['page']}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        path = filedialog.asksaveasfilename(
            title=T("research_pi_approx.export_csv_button"),
            initialdir=self._get_portal_folder(),
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), (T("common.all_files"), "*.*")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["x", "pi_x", "li_x", "r_x", "li_error", "r_error"])
            for row in result["rows"]:
                writer.writerow([row["x"], row["pi_x"], f"{row['li_x']:.4f}",
                                  f"{row['r_x']:.4f}", f"{row['li_error']:.4f}",
                                  f"{row['r_error']:.4f}"])
        self.status.set(T("research_pi_approx.status_exported", path=path))

    def _pi_show_result(self, result):
        T = self.T
        self._pi_last_result = result
        self._pi_page = result["page"]

        for item in self.pi_results_tree.get_children():
            self.pi_results_tree.delete(item)
        for row in result["rows"]:
            self.pi_results_tree.insert("", "end", values=(
                f"{row['x']:,}", f"{row['pi_x']:,}",
                f"{row['li_x']:.2f}", f"{row['r_x']:.2f}",
                f"{row['li_error']:+.2f}", f"{row['r_error']:+.2f}"))

        self.pi_summary_var.set(T(
            "research_pi_approx.summary",
            x_from=f"{result['x_from']:,}", x_to=f"{result['x_to']:,}",
            segment_size=f"{result['segment_size']:,}",
            max_li_error=f"{result['max_li_error']:+.2f}",
            max_r_error=f"{result['max_r_error']:+.2f}"))

        self._pi_refresh_nav_buttons()
