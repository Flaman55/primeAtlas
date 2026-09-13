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
sito" / "Dane z magazynu", storage mode via
primeatlas/research_pi_approx.py's read_is_prime_from_storage), pagination,
and CSV export of the currently-displayed page.

Unlike every other Research sub-tab, there is no conjecture verdict at all
here (not even Gaps' per-overlay covered/counterexamples for two of its
three overlays) -- this is purely a measurement/accuracy comparison, so the
summary reports the largest li(x)/R(x) error seen in the range instead of
any pass/fail statement (see pi_approx_window.py's own module docstring)."""
import csv
import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from . import background
from .base_tab import BaseTab
from .pi_approx_window import check_pi_approx_range, check_pi_approx_range_from_source, MAX_SIEVE_BOUND
from .research_pi_approx import read_is_prime_from_storage, MissingStorageRangeError

PI_APPROX_ROW_CAP = 200
"""Rows per page in the results Treeview -- same "stats always computed
over the FULL range, only the display paginates" contract as
squares_window.check_interval_range's own row_cap/row_offset."""


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
        between "sieve"/"storage" applies the SAME MAX_SIEVE_BOUND ceiling
        either way."""
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
            else:
                result = check_pi_approx_range(
                    job["x_from"], job["x_to"], job["step"],
                    row_cap=PI_APPROX_ROW_CAP, row_offset=job["page"] * PI_APPROX_ROW_CAP)
            result["source"] = job["source"]
            result["page"] = job["page"]
            return True, result
        except MissingStorageRangeError as e:
            T = self.T
            return False, T("research_pi_approx.error_storage_missing",
                             floor=e.floor, upto=f"{e.needed_upto:,}")
        except ValueError as e:
            return False, str(e)

    def _on_pi_worker_result(self, payload, error):
        T = self.T
        self._pi_set_busy(False)
        if error is not None:
            messagebox.showerror(T("research_pi_approx.error_dialog_title"), str(error))
            self._pi_refresh_nav_buttons()
            return
        ok, data = payload
        if not ok:
            messagebox.showerror(T("research_pi_approx.error_dialog_title"), str(data))
            self._pi_refresh_nav_buttons()
            return
        self._pi_show_result(data)

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
