"""
research_gaps_tab.py -- ResearchGapsTab, the tkinter widgets for the
Research tab's Luki (prime gaps) sub-tab: raw consecutive-prime gaps plus a
selectable Andrica/Firoozbakht/Cramer overlay, checked over a
[n_from, n_to] range of prime POSITIONS via primeatlas/research/gaps_window.py's
pure check_gap_range()/check_gap_range_from_source().

Same shape as ResearchSquaresTab/ResearchPolynomialsTab (see either's own
docstring for the full data-source-toggle/CSV-export history this mirrors
from day one): a data-source toggle ("Świeże sito" / "Dane z archive",
storage mode via primeatlas/research/research_gaps.py's read_is_prime_from_storage),
pagination, and CSV export of the currently-displayed page.

Unlike ResearchSquaresTab/ResearchPolynomialsTab, there is no user-typed
formula at all -- the overlay is one of a fixed set (none/andrica/
firoozbakht/cramer, see gaps_window.py's own module docstring), selected via
a plain combobox, so this tab needs no restricted-eval helper of its own.
"""
import csv
import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from ..core import background
from ..core.base_tab import BaseTab
from .gaps_window import check_gap_range, check_gap_range_from_source, MAX_SIEVE_BOUND
from .research_gaps import read_is_prime_from_storage, MissingStorageRangeError

GAPS_ROW_CAP = 200
"""Rows per page in the results Treeview -- same "verdict/stats always
computed over the FULL range, only the display paginates" contract as
squares_window.check_interval_range's own row_cap/row_offset."""

_OVERLAY_IDS = ("none", "andrica", "firoozbakht", "cramer")


class ResearchGapsTab(BaseTab):
    def __init__(self, parent, translator, totals_progress, eval_quick_number,
                 get_portal_folder, status_var):
        """Same dependency-injection pattern as ResearchSquaresTab/
        ResearchPolynomialsTab -- see either's own docstring for what each
        parameter is for. eval_quick_number is used for the plain integer
        n_from/n_to fields (n_from >= 1 -- p_1 = 2 is the first prime
        position, there is no position 0)."""
        super().__init__(parent, translator)
        self.totals_progress = totals_progress
        self._eval_quick_number = eval_quick_number
        self._get_portal_folder = get_portal_folder
        self.status = status_var

        self._gaps_busy = False
        self._gaps_worker = background.PersistentWorker(
            self, self._gaps_job, on_result=self._on_gaps_worker_result)
        self._gaps_last_result = None
        self._gaps_page = 0

        self._build_widgets()

    def _build_widgets(self):
        T = self.T
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=(10, 4))
        ttk.Label(top, text=T("research_gaps.overlay_label")).pack(side="left")
        self.gaps_overlay_combo = ttk.Combobox(
            top, state="readonly", width=36,
            values=[T(f"research_gaps.overlay_{oid}") for oid in _OVERLAY_IDS])
        self.gaps_overlay_combo.current(0)
        self.gaps_overlay_combo.pack(side="left", padx=(6, 0))

        range_row = ttk.Frame(self)
        range_row.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(range_row, text=T("research_gaps.n_from_label")).pack(side="left")
        self.gaps_n_from_entry = ttk.Entry(range_row, width=12)
        self.gaps_n_from_entry.insert(0, "1")
        self.gaps_n_from_entry.pack(side="left", padx=(6, 16))
        ttk.Label(range_row, text=T("research_gaps.n_to_label")).pack(side="left")
        self.gaps_n_to_entry = ttk.Entry(range_row, width=12)
        self.gaps_n_to_entry.insert(0, "100")
        self.gaps_n_to_entry.pack(side="left", padx=(6, 0))

        source_row = ttk.Frame(self)
        source_row.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(source_row, text=T("research_gaps.source_label")).pack(side="left")
        self.gaps_source_var = tk.StringVar(value="sieve")
        ttk.Radiobutton(
            source_row, text=T("research_gaps.source_sieve"),
            variable=self.gaps_source_var, value="sieve").pack(side="left", padx=(6, 0))
        ttk.Radiobutton(
            source_row, text=T("research_gaps.source_storage"),
            variable=self.gaps_source_var, value="storage").pack(side="left", padx=(10, 0))

        button_row = ttk.Frame(self)
        button_row.pack(fill="x", padx=6, pady=(0, 8))
        self.gaps_run_button = ttk.Button(
            button_row, text=T("research_gaps.run_button"), command=self._on_gaps_run)
        self.gaps_run_button.pack(side="left")
        self.gaps_prev_button = ttk.Button(
            button_row, text=T("research_gaps.prev_button"),
            command=self._on_gaps_prev, state="disabled")
        self.gaps_prev_button.pack(side="left", padx=(16, 0))
        self.gaps_next_button = ttk.Button(
            button_row, text=T("research_gaps.next_button"),
            command=self._on_gaps_next, state="disabled")
        self.gaps_next_button.pack(side="left", padx=(6, 0))
        self.gaps_export_button = ttk.Button(
            button_row, text=T("research_gaps.export_csv_button"),
            command=self._on_gaps_export_csv, state="disabled")
        self.gaps_export_button.pack(side="left", padx=(16, 0))

        ttk.Label(self, text=T("research_gaps.hint"),
                  wraplength=760, justify="left", foreground="#555").pack(
            anchor="w", padx=6, pady=(0, 8))

        self.gaps_summary_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.gaps_summary_var,
                  wraplength=760, justify="left").pack(anchor="w", padx=6, pady=(0, 8))

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        columns = ("n", "p_n", "p_n1", "gap", "overlay_value", "holds")
        self.gaps_results_tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", height=16)
        self.gaps_results_tree.heading("n", text=T("research_gaps.col_n"))
        self.gaps_results_tree.heading("p_n", text=T("research_gaps.col_p_n"))
        self.gaps_results_tree.heading("p_n1", text=T("research_gaps.col_p_n1"))
        self.gaps_results_tree.heading("gap", text=T("research_gaps.col_gap"))
        self.gaps_results_tree.heading("overlay_value", text=T("research_gaps.col_overlay_value"))
        self.gaps_results_tree.heading("holds", text=T("research_gaps.col_holds"))
        self.gaps_results_tree.column("n", width=80, anchor="e")
        self.gaps_results_tree.column("p_n", width=120, anchor="e")
        self.gaps_results_tree.column("p_n1", width=120, anchor="e")
        self.gaps_results_tree.column("gap", width=80, anchor="e")
        self.gaps_results_tree.column("overlay_value", width=140, anchor="e")
        self.gaps_results_tree.column("holds", width=90, anchor="center")
        svsb = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self.gaps_results_tree.yview)
        self.gaps_results_tree.configure(yscrollcommand=svsb.set)
        self.gaps_results_tree.pack(side="left", fill="both", expand=True)
        svsb.pack(side="right", fill="y")

    def _current_overlay_id(self):
        return _OVERLAY_IDS[self.gaps_overlay_combo.current()]

    def _parse_positive_int(self, entry, field_name_key):
        T = self.T
        value = self._eval_quick_number(entry.get())
        if value is None or value < 1:
            raise ValueError(T("research_gaps.error_field_positive_int",
                                field=T(field_name_key)))
        return value

    def _on_gaps_run(self):
        T = self.T
        if self._gaps_busy:
            return
        overlay = self._current_overlay_id()
        try:
            n_from = self._parse_positive_int(self.gaps_n_from_entry, "research_gaps.n_from_label")
            n_to = self._parse_positive_int(self.gaps_n_to_entry, "research_gaps.n_to_label")
            if n_to < n_from:
                raise ValueError(T("research_gaps.error_range_order"))
        except ValueError as e:
            messagebox.showerror(T("research_gaps.error_dialog_title"), str(e))
            return

        self._gaps_set_busy(True)
        self._gaps_worker.submit({
            "overlay": overlay, "n_from": n_from, "n_to": n_to,
            "source": self.gaps_source_var.get(), "page": 0,
        })

    def _on_gaps_prev(self):
        if self._gaps_page > 0:
            self._gaps_requeue_page(self._gaps_page - 1)

    def _on_gaps_next(self):
        self._gaps_requeue_page(self._gaps_page + 1)

    def _gaps_requeue_page(self, page):
        last = self._gaps_last_result
        if last is None or self._gaps_busy:
            return
        self._gaps_set_busy(True)
        self._gaps_worker.submit({
            "overlay": last["overlay"], "n_from": last["n_from"], "n_to": last["n_to"],
            "source": last.get("source", "sieve"), "page": page,
        })

    def _gaps_set_busy(self, busy):
        self._gaps_busy = busy
        self.gaps_run_button.configure(state="disabled" if busy else "normal")
        if busy:
            self.gaps_prev_button.configure(state="disabled")
            self.gaps_next_button.configure(state="disabled")
            self.gaps_export_button.configure(state="disabled")
            self._start_busy_progress()
        else:
            self._stop_busy_progress()

    def _gaps_job(self, job, _report_progress):
        """Runs on PersistentWorker's own daemon thread -- see
        ResearchSquaresTab._squares_job's own docstring for the single-
        owner-thread contract this relies on and why job["source"] picking
        between "sieve"/"storage" applies the SAME MAX_SIEVE_BOUND ceiling
        either way."""
        overlay = job["overlay"]
        try:
            if job["source"] == "storage":
                portal_folder = self._get_portal_folder()

                def source(bound, _folder=portal_folder):
                    if bound > MAX_SIEVE_BOUND:
                        raise ValueError(
                            f"the requested range needs data up to {bound:,}, above "
                            f"this tool's {MAX_SIEVE_BOUND:,} ceiling -- reduce n_to")
                    return read_is_prime_from_storage(_folder, bound)

                result = check_gap_range_from_source(
                    job["n_from"], job["n_to"], source, overlay=overlay,
                    row_cap=GAPS_ROW_CAP, row_offset=job["page"] * GAPS_ROW_CAP)
            else:
                result = check_gap_range(
                    job["n_from"], job["n_to"], overlay=overlay,
                    row_cap=GAPS_ROW_CAP, row_offset=job["page"] * GAPS_ROW_CAP)
            result["source"] = job["source"]
            result["page"] = job["page"]
            return True, result
        except MissingStorageRangeError as e:
            T = self.T
            return False, T("research_gaps.error_storage_missing",
                             floor=e.floor, upto=f"{e.needed_upto:,}")
        except ValueError as e:
            return False, str(e)

    def _on_gaps_worker_result(self, payload, error):
        T = self.T
        self._gaps_set_busy(False)
        if error is not None:
            messagebox.showerror(T("research_gaps.error_dialog_title"), str(error))
            self._gaps_refresh_nav_buttons()
            return
        ok, data = payload
        if not ok:
            messagebox.showerror(T("research_gaps.error_dialog_title"), str(data))
            self._gaps_refresh_nav_buttons()
            return
        self._gaps_show_result(data)

    def _gaps_refresh_nav_buttons(self):
        last = self._gaps_last_result
        self.gaps_prev_button.configure(
            state="normal" if last and self._gaps_page > 0 else "disabled")
        self.gaps_next_button.configure(
            state="normal" if last and last.get("rows_truncated") else "disabled")
        self.gaps_export_button.configure(
            state="normal" if last and last.get("rows") else "disabled")

    def _on_gaps_export_csv(self):
        """Exports the CURRENTLY DISPLAYED page's rows only -- same scope as
        ResearchSquaresTab._on_squares_export_csv (see its own docstring for
        why)."""
        result = self._gaps_last_result
        if not result or not result.get("rows"):
            return
        T = self.T
        default_name = (
            f"gaps_{result['overlay']}_n{result['n_from']}-{result['n_to']}_"
            f"page{result['page']}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        path = filedialog.asksaveasfilename(
            title=T("research_gaps.export_csv_button"),
            initialdir=self._get_portal_folder(),
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), (T("common.all_files"), "*.*")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["n", "p_n", "p_n1", "gap", "overlay_value", "holds"])
            for row in result["rows"]:
                overlay_value = "" if row["overlay_value"] is None else row["overlay_value"]
                holds = "" if row["holds"] is None else ("1" if row["holds"] else "0")
                writer.writerow([row["n"], row["p_n"], row["p_n1"], row["gap"],
                                  overlay_value, holds])
        self.status.set(T("research_gaps.status_exported", path=path))

    def _gaps_show_result(self, result):
        T = self.T
        self._gaps_last_result = result
        self._gaps_page = result["page"]
        overlay = result["overlay"]

        for item in self.gaps_results_tree.get_children():
            self.gaps_results_tree.delete(item)
        for row in result["rows"]:
            if row["overlay_value"] is None:
                overlay_value_text = "-"
            else:
                overlay_value_text = f"{row['overlay_value']:.6f}"
            if row["holds"] is None:
                holds_text = "-"
            else:
                holds_text = (T("research_gaps.holds_yes") if row["holds"]
                               else T("research_gaps.holds_no"))
            self.gaps_results_tree.insert("", "end", values=(
                row["n"], row["p_n"], row["p_n1"], row["gap"],
                overlay_value_text, holds_text))

        parts = [T(
            "research_gaps.summary_gap_stats",
            n_from=f"{result['n_from']:,}", n_to=f"{result['n_to']:,}",
            segment_size=f"{result['segment_size']:,}", max_gap=result["max_gap"])]
        if overlay in ("andrica", "firoozbakht"):
            overlay_name = T(f"research_gaps.overlay_{overlay}")
            if not result["counterexamples"]:
                parts.append(T(
                    "research_gaps.summary_covered", overlay_name=overlay_name,
                    n_from=f"{result['n_from']:,}", n_to=f"{result['n_to']:,}"))
            else:
                shown = result["counterexamples"][:20]
                more = len(result["counterexamples"]) - len(shown)
                counterexamples_text = ", ".join(str(n) for n in shown)
                if more > 0:
                    counterexamples_text += T("research_gaps.summary_more_suffix", more=more)
                parts.append(T(
                    "research_gaps.summary_not_covered",
                    count=len(result["counterexamples"]), counterexamples=counterexamples_text))
        elif overlay == "cramer":
            parts.append(T("research_gaps.summary_cramer",
                            max_ratio=f"{result['max_cramer_ratio']:.4f}"))
        self.gaps_summary_var.set(" ".join(parts))

        self._gaps_refresh_nav_buttons()
