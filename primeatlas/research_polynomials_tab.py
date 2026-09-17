"""
research_polynomials_tab.py -- ResearchPolynomialsTab, the tkinter widgets
for the Research tab's Wielomiany pierwszorodne (prime-generating
polynomials) sub-tab: Landau (n^2+1) / Euler (n^2+n+41) presets plus a
custom f(n) formula, checked over a [n_from, n_to] range via
primeatlas/polynomials_window.py's pure check_polynomial_range()/
check_polynomial_range_from_source().

Same shape as ResearchSquaresTab (primeatlas/research_squares_tab.py, see
that module's own docstring for the full Faza-1/Faza-2 history this mirrors
from day one): a data-source toggle ("Świeże sito" / "Dane z archive",
storage mode via primeatlas/research_polynomials.py's
read_is_prime_from_storage), pagination, and CSV export of the currently-
displayed page.

Unlike ResearchSquaresTab, there is no required_count field and no two-
formula (a(n)/b(n)) custom pair -- one polynomial f(n) per row, one
is_prime? verdict per row, and the summary is an open-ended prime_count/
density measurement rather than a covered/counterexamples verdict (see
polynomials_window.py's own module docstring for why: Landau's and Euler's
conjectures are about an infinite tail, which no finite range check can
ever confirm or refute).

Custom-formula evaluation (_eval_formula below) is a RESTRICTED eval (no
builtins, only a bound `n`) -- same reasoning, and literally the same
implementation, as research_squares_tab.py's own _eval_formula; kept as an
independent copy here rather than imported, per this project's own
duplicate-small-primitives-across-conjecture-modules convention (see
research_squares_tab.py's own docstring).
"""
import csv
import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from . import background
from .base_tab import BaseTab
from .polynomials_window import (
    check_polynomial_range, check_polynomial_range_from_source, MAX_SIEVE_BOUND,
)
from .research_polynomials import read_is_prime_from_storage, MissingStorageRangeError

POLYNOMIALS_ROW_CAP = 200
"""Rows per page in the results Treeview -- same "verdict/counts always
computed over the FULL range, only the display paginates" contract as
squares_window.check_interval_range's own row_cap/row_offset."""

_PRESET_IDS = ("landau", "euler", "custom")


def _eval_formula(formula, n):
    """Evaluates a user-typed f(n) formula string with `n` bound to the
    given integer -- restricted eval (no builtins), same reasoning as
    research_squares_tab._eval_formula/generation._eval_quick_number. Raises
    ValueError (not whatever raw exception type eval() itself produced) on
    anything that doesn't evaluate to a plain int, so callers can show one
    consistent error dialog regardless of what specifically went wrong."""
    formula = (formula or "").strip()
    if not formula:
        raise ValueError("empty formula")
    try:
        value = eval(formula, {"__builtins__": {}}, {"n": n})
        return int(value)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(str(e))


class ResearchPolynomialsTab(BaseTab):
    def __init__(self, parent, translator, totals_progress, eval_quick_number,
                 get_portal_folder, status_var):
        """Same dependency-injection pattern as ResearchSquaresTab -- see
        that class's own docstring for what each parameter is for.
        eval_quick_number is used for the plain integer n_from/n_to fields
        (which may legitimately be 0 -- Euler's own famous run starts
        there), NOT for the custom f(n) formula, which needs an `n`
        variable substituted per-row instead (see _eval_formula above)."""
        super().__init__(parent, translator)
        self.totals_progress = totals_progress
        self._eval_quick_number = eval_quick_number
        self._get_portal_folder = get_portal_folder
        self.status = status_var

        self._poly_busy = False
        self._poly_worker = background.PersistentWorker(
            self, self._poly_job, on_result=self._on_poly_worker_result)
        self._poly_last_result = None
        self._poly_page = 0

        self._build_widgets()

    def _build_widgets(self):
        T = self.T
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=(10, 4))
        ttk.Label(top, text=T("research_polynomials.preset_label")).pack(side="left")
        self.poly_preset_combo = ttk.Combobox(
            top, state="readonly", width=18,
            values=[T(f"research_polynomials.preset_{pid}") for pid in _PRESET_IDS])
        self.poly_preset_combo.current(0)
        self.poly_preset_combo.pack(side="left", padx=(6, 16))
        self.poly_preset_combo.bind("<<ComboboxSelected>>", self._on_poly_preset_changed)

        range_row = ttk.Frame(self)
        range_row.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(range_row, text=T("research_polynomials.n_from_label")).pack(side="left")
        self.poly_n_from_entry = ttk.Entry(range_row, width=12)
        self.poly_n_from_entry.insert(0, "0")
        self.poly_n_from_entry.pack(side="left", padx=(6, 16))
        ttk.Label(range_row, text=T("research_polynomials.n_to_label")).pack(side="left")
        self.poly_n_to_entry = ttk.Entry(range_row, width=12)
        self.poly_n_to_entry.insert(0, "100")
        self.poly_n_to_entry.pack(side="left", padx=(6, 0))
        self._poly_range_row = range_row

        # Only shown/relevant when preset == "custom" -- see
        # _set_custom_field_visible/_on_poly_preset_changed. Anchored via
        # pack(after=range_row), same reasoning as ResearchSquaresTab's own
        # squares_custom_frame (a bare pack() would append it after whatever
        # else is currently packed instead of back into its own slot).
        self.poly_custom_frame = ttk.Frame(self)
        ttk.Label(self.poly_custom_frame, text=T("research_polynomials.custom_formula_label")).pack(side="left")
        self.poly_custom_formula_entry = ttk.Entry(self.poly_custom_frame, width=24)
        self.poly_custom_formula_entry.insert(0, "n**2 - n + 41")
        self.poly_custom_formula_entry.pack(side="left", padx=(6, 0))
        self._set_custom_field_visible(False)

        source_row = ttk.Frame(self)
        source_row.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(source_row, text=T("research_polynomials.source_label")).pack(side="left")
        self.poly_source_var = tk.StringVar(value="sieve")
        ttk.Radiobutton(
            source_row, text=T("research_polynomials.source_sieve"),
            variable=self.poly_source_var, value="sieve").pack(side="left", padx=(6, 0))
        ttk.Radiobutton(
            source_row, text=T("research_polynomials.source_storage"),
            variable=self.poly_source_var, value="storage").pack(side="left", padx=(10, 0))

        button_row = ttk.Frame(self)
        button_row.pack(fill="x", padx=6, pady=(0, 8))
        self.poly_run_button = ttk.Button(
            button_row, text=T("research_polynomials.run_button"), command=self._on_poly_run)
        self.poly_run_button.pack(side="left")
        self.poly_prev_button = ttk.Button(
            button_row, text=T("research_polynomials.prev_button"),
            command=self._on_poly_prev, state="disabled")
        self.poly_prev_button.pack(side="left", padx=(16, 0))
        self.poly_next_button = ttk.Button(
            button_row, text=T("research_polynomials.next_button"),
            command=self._on_poly_next, state="disabled")
        self.poly_next_button.pack(side="left", padx=(6, 0))
        self.poly_export_button = ttk.Button(
            button_row, text=T("research_polynomials.export_csv_button"),
            command=self._on_poly_export_csv, state="disabled")
        self.poly_export_button.pack(side="left", padx=(16, 0))

        ttk.Label(self, text=T("research_polynomials.hint"),
                  wraplength=760, justify="left", foreground="#555").pack(
            anchor="w", padx=6, pady=(0, 8))

        self.poly_summary_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.poly_summary_var,
                  wraplength=760, justify="left").pack(anchor="w", padx=6, pady=(0, 8))

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        columns = ("n", "value", "is_prime")
        self.poly_results_tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", height=16)
        self.poly_results_tree.heading("n", text=T("research_polynomials.col_n"))
        self.poly_results_tree.heading("value", text=T("research_polynomials.col_value"))
        self.poly_results_tree.heading("is_prime", text=T("research_polynomials.col_is_prime"))
        self.poly_results_tree.column("n", width=90, anchor="e")
        self.poly_results_tree.column("value", width=160, anchor="e")
        self.poly_results_tree.column("is_prime", width=110, anchor="center")
        svsb = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self.poly_results_tree.yview)
        self.poly_results_tree.configure(yscrollcommand=svsb.set)
        self.poly_results_tree.pack(side="left", fill="both", expand=True)
        svsb.pack(side="right", fill="y")

    def _set_custom_field_visible(self, visible):
        if visible:
            self.poly_custom_frame.pack(fill="x", padx=6, pady=(0, 4),
                                         after=self._poly_range_row)
        else:
            self.poly_custom_frame.pack_forget()

    def _current_preset_id(self):
        return _PRESET_IDS[self.poly_preset_combo.current()]

    def _on_poly_preset_changed(self, _event=None):
        preset = self._current_preset_id()
        self._set_custom_field_visible(preset == "custom")

    def _parse_int(self, entry, field_name_key, min_value):
        T = self.T
        value = self._eval_quick_number(entry.get())
        if value is None or value < min_value:
            raise ValueError(T("research_polynomials.error_field_int",
                                field=T(field_name_key), min_value=min_value))
        return value

    def _on_poly_run(self):
        T = self.T
        if self._poly_busy:
            return
        preset = self._current_preset_id()
        try:
            n_from = self._parse_int(self.poly_n_from_entry, "research_polynomials.n_from_label", 0)
            n_to = self._parse_int(self.poly_n_to_entry, "research_polynomials.n_to_label", 0)
            if n_to < n_from:
                raise ValueError(T("research_polynomials.error_range_order"))
            custom_formula = None
            if preset == "custom":
                custom_formula = self.poly_custom_formula_entry.get()
                # Validate against n_from right away, so a typo shows an error
                # immediately instead of only once the worker thread hits it.
                _eval_formula(custom_formula, n_from)
        except ValueError as e:
            messagebox.showerror(T("research_polynomials.error_dialog_title"), str(e))
            return

        self._poly_set_busy(True)
        self._poly_worker.submit({
            "preset": preset, "n_from": n_from, "n_to": n_to,
            "custom_formula": custom_formula,
            "source": self.poly_source_var.get(), "page": 0,
        })

    def _on_poly_prev(self):
        if self._poly_page > 0:
            self._poly_requeue_page(self._poly_page - 1)

    def _on_poly_next(self):
        self._poly_requeue_page(self._poly_page + 1)

    def _poly_requeue_page(self, page):
        last = self._poly_last_result
        if last is None or self._poly_busy:
            return
        self._poly_set_busy(True)
        self._poly_worker.submit({
            "preset": last["preset"], "n_from": last["n_from"], "n_to": last["n_to"],
            "custom_formula": last.get("custom_formula"),
            "source": last.get("source", "sieve"), "page": page,
        })

    def _poly_set_busy(self, busy):
        self._poly_busy = busy
        self.poly_run_button.configure(state="disabled" if busy else "normal")
        if busy:
            self.poly_prev_button.configure(state="disabled")
            self.poly_next_button.configure(state="disabled")
            self.poly_export_button.configure(state="disabled")
            self._start_busy_progress()
        else:
            self._stop_busy_progress()

    def _poly_job(self, job, _report_progress):
        """Runs on PersistentWorker's own daemon thread -- see
        ResearchSquaresTab._squares_job's own docstring for the single-
        owner-thread contract this relies on and why job["source"] picking
        between "sieve"/"storage" applies the SAME MAX_SIEVE_BOUND ceiling
        either way (it bounds the size of the in-memory is_prime ARRAY,
        identical regardless of how it got filled)."""
        preset = job["preset"]
        if preset == "custom":
            custom_formula = job["custom_formula"]

            def poly_fn(n, _f=custom_formula):
                return _eval_formula(_f, n)
        else:
            poly_fn = None
        try:
            if job["source"] == "storage":
                portal_folder = self._get_portal_folder()

                def source(max_value, _folder=portal_folder):
                    if max_value > MAX_SIEVE_BOUND:
                        raise ValueError(
                            f"the requested range needs data up to {max_value:,}, above "
                            f"this tool's {MAX_SIEVE_BOUND:,} ceiling -- reduce n_to")
                    return read_is_prime_from_storage(_folder, max_value)

                result = check_polynomial_range_from_source(
                    preset, job["n_from"], job["n_to"], source, poly_fn=poly_fn,
                    row_cap=POLYNOMIALS_ROW_CAP, row_offset=job["page"] * POLYNOMIALS_ROW_CAP)
            else:
                result = check_polynomial_range(
                    preset, job["n_from"], job["n_to"], poly_fn=poly_fn,
                    row_cap=POLYNOMIALS_ROW_CAP, row_offset=job["page"] * POLYNOMIALS_ROW_CAP)
            result["custom_formula"] = job.get("custom_formula")
            result["source"] = job["source"]
            result["page"] = job["page"]
            return True, result
        except MissingStorageRangeError as e:
            T = self.T
            return False, T("research_polynomials.error_storage_missing",
                             floor=e.floor, upto=f"{e.needed_upto:,}")
        except ValueError as e:
            return False, str(e)

    def _on_poly_worker_result(self, payload, error):
        T = self.T
        self._poly_set_busy(False)
        if error is not None:
            messagebox.showerror(T("research_polynomials.error_dialog_title"), str(error))
            self._poly_refresh_nav_buttons()
            return
        ok, data = payload
        if not ok:
            messagebox.showerror(T("research_polynomials.error_dialog_title"), str(data))
            self._poly_refresh_nav_buttons()
            return
        self._poly_show_result(data)

    def _poly_refresh_nav_buttons(self):
        last = self._poly_last_result
        self.poly_prev_button.configure(
            state="normal" if last and self._poly_page > 0 else "disabled")
        self.poly_next_button.configure(
            state="normal" if last and last.get("rows_truncated") else "disabled")
        self.poly_export_button.configure(
            state="normal" if last and last.get("rows") else "disabled")

    def _on_poly_export_csv(self):
        """Exports the CURRENTLY DISPLAYED page's rows only -- same scope as
        ResearchSquaresTab._on_squares_export_csv (see its own docstring for
        why: re-running the full range just for export could silently
        export against a range that no longer matches what's on screen)."""
        result = self._poly_last_result
        if not result or not result.get("rows"):
            return
        T = self.T
        default_name = (
            f"polynomials_{result['preset']}_n{result['n_from']}-{result['n_to']}_"
            f"page{result['page']}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        path = filedialog.asksaveasfilename(
            title=T("research_polynomials.export_csv_button"),
            initialdir=self._get_portal_folder(),
            initialfile=default_name,
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), (T("common.all_files"), "*.*")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["n", "value", "is_prime"])
            for row in result["rows"]:
                writer.writerow([row["n"], row["value"], "1" if row["is_prime"] else "0"])
        self.status.set(T("research_polynomials.status_exported", path=path))

    def _poly_show_result(self, result):
        T = self.T
        self._poly_last_result = result
        self._poly_page = result["page"]

        for item in self.poly_results_tree.get_children():
            self.poly_results_tree.delete(item)
        for row in result["rows"]:
            self.poly_results_tree.insert("", "end", values=(
                row["n"], row["value"],
                T("research_polynomials.is_prime_yes") if row["is_prime"]
                else T("research_polynomials.is_prime_no"),
            ))

        segment_size = result["segment_size"]
        prime_count = result["prime_count"]
        percent = (100.0 * prime_count / segment_size) if segment_size else 0.0
        self.poly_summary_var.set(T(
            "research_polynomials.summary",
            n_from=f"{result['n_from']:,}", n_to=f"{result['n_to']:,}",
            segment_size=f"{segment_size:,}", prime_count=f"{prime_count:,}",
            percent=f"{percent:.1f}"))

        self._poly_refresh_nav_buttons()
