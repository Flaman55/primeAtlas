"""
primality_tab.py -- probabilistic primality testing + factorization sub-tab (Liczby
pierwsze -> Testy pierwszosci), extracted from prime_atlas_v1.py during the refactor
branch's Faza 4 (2026-08-24), the same phase that extracted the primesieve calculator
sub-tab alongside it (primeatlas/primesieve_calc_tab.py) -- these two were the last
remaining un-extracted sub-tabs left inline in the app shell after every OTHER tab was
already split out during Faza 3.

Backend logic (primeatlas.primality: run_all_tests/factorize/try_import_sympy) was
ALREADY its own module before this extraction -- this file only ever held the UI +
worker-thread glue, the same split every other tab already has. No WSL round trip here
at all (see _primality_job's own docstring below) -- everything runs in-process, on
this tab's own PersistentWorker thread.

Constructor-injected (status_var/translator/totals_progress) exactly like
PrimesieveCalcTab right next to it -- see that module's own docstring for why these
three, and not more, are injected (the shared status bar/progress bar and the app's
Translator instance).
"""
import tkinter as tk
from tkinter import ttk, messagebox

from .background import PersistentWorker
from .generation import _eval_quick_number
from .primality import run_all_tests as primality_run_all_tests, factorize as primality_factorize


class PrimalityTab(ttk.Frame):
    def __init__(self, parent, status_var, translator, totals_progress):
        super().__init__(parent)
        self.status = status_var
        self.T = translator
        self.totals_progress = totals_progress
        self._primality_busy = False
        self._primality_worker = PersistentWorker(
            self, self._primality_job, on_result=self._on_primality_worker_result)
        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=(10, 4))
        ttk.Label(top, text=self.T("primality.field_number")).pack(side="left")
        self.primality_number_entry = ttk.Entry(top, width=32)
        self.primality_number_entry.pack(side="left", padx=(6, 16))

        self.primality_use_sympy_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            top, text=self.T("primality.use_sympy_checkbox"),
            variable=self.primality_use_sympy_var).pack(side="left")

        button_row = ttk.Frame(self)
        button_row.pack(fill="x", padx=6, pady=(0, 8))
        self.primality_check_button = ttk.Button(
            button_row, text=self.T("primality.check_button"),
            command=self._on_primality_check_compute)
        self.primality_check_button.pack(side="left")
        self.primality_factorize_button = ttk.Button(
            button_row, text=self.T("primality.factorize_button"),
            command=self._on_primality_factorize_compute)
        self.primality_factorize_button.pack(side="left", padx=(8, 0))

        ttk.Label(self, text=self.T("primality.hint"),
                  wraplength=640, justify="left", foreground="#555").pack(
            anchor="w", padx=6, pady=(0, 8))

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=False, padx=6, pady=(0, 8))
        columns = ("method", "verdict", "certainty", "seconds")
        self.primality_results_tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", height=3)
        self.primality_results_tree.heading("method", text=self.T("primality.col_method"))
        self.primality_results_tree.heading("verdict", text=self.T("primality.col_verdict"))
        self.primality_results_tree.heading("certainty", text=self.T("primality.col_certainty"))
        self.primality_results_tree.heading("seconds", text=self.T("primality.col_seconds"))
        self.primality_results_tree.column("method", width=140, anchor="w")
        self.primality_results_tree.column("verdict", width=110, anchor="center")
        self.primality_results_tree.column("certainty", width=220, anchor="w")
        self.primality_results_tree.column("seconds", width=100, anchor="e")
        self.primality_results_tree.pack(fill="x")

        factor_frame = ttk.Frame(self)
        factor_frame.pack(fill="x", padx=6, pady=(0, 4))
        self.primality_factor_result_var = tk.StringVar(value="")
        ttk.Label(factor_frame, textvariable=self.primality_factor_result_var,
                  wraplength=760, justify="left").pack(anchor="w")

        # Separate readonly Entry holding JUST the factor list (no "n = " prefix, no
        # "(metoda: ..., czas: ...)" suffix) -- a plain Label's text can't be selected or
        # copied at all in tkinter, so the summary line above was previously impossible
        # to copy from. An Entry supports normal mouse selection (drag for a range,
        # double-click for one factor) and Ctrl+C even in readonly state -- readonly only
        # blocks typing/editing, not selection -- plus a one-click Copy button for
        # grabbing the whole list at once.
        factors_row = ttk.Frame(self)
        factors_row.pack(fill="x", padx=6, pady=(0, 8))
        ttk.Label(factors_row, text=self.T("primality.factors_field_label")).pack(side="left")
        self.primality_factors_only_var = tk.StringVar(value="")
        self.primality_factors_entry = ttk.Entry(
            factors_row, textvariable=self.primality_factors_only_var, state="readonly")
        self.primality_factors_entry.pack(side="left", fill="x", expand=True, padx=(6, 6))
        self.primality_factors_copy_button = ttk.Button(
            factors_row, text=self.T("primality.copy_factors_button"),
            command=self._on_primality_copy_factors, state="disabled")
        self.primality_factors_copy_button.pack(side="left")

    def _primality_parse_number(self):
        """Shared client-side validation for both buttons -- parses the number field
        (via _eval_quick_number, so expressions like 10**5+3 work here too, same as the
        primesieve calculator's fields), requiring an integer >= 2 (both
        primality.run_all_tests and primality.factorize document this same floor -- see
        that module's own docstrings). Raises ValueError with a translated message on
        failure; returns the parsed int on success."""
        n = _eval_quick_number(self.primality_number_entry.get())
        if n is None or n < 2:
            raise ValueError(self.T("primality.error_number_invalid"))
        return n

    def _on_primality_check_compute(self):
        if self._primality_busy:
            return
        try:
            n = self._primality_parse_number()
        except ValueError as e:
            messagebox.showerror(self.T("primality.error_dialog_title"), str(e))
            return
        self._primality_set_busy(True)
        self._primality_worker.submit({"op": "check", "n": n})

    def _on_primality_factorize_compute(self):
        if self._primality_busy:
            return
        try:
            n = self._primality_parse_number()
        except ValueError as e:
            messagebox.showerror(self.T("primality.error_dialog_title"), str(e))
            return
        self._primality_set_busy(True)
        self._primality_worker.submit(
            {"op": "factorize", "n": n, "use_sympy": self.primality_use_sympy_var.get()})

    def _primality_set_busy(self, busy):
        self._primality_busy = busy
        state = "disabled" if busy else "normal"
        self.primality_check_button.configure(state=state)
        self.primality_factorize_button.configure(state=state)
        if busy:
            self.totals_progress.stop()
            self.totals_progress.configure(mode="indeterminate")
            self.totals_progress.start(80)
            self.status.set(self.T("primality.status_computing"))
        else:
            self.totals_progress.stop()
            self.totals_progress.configure(mode="determinate", maximum=1, value=0)

    def _primality_job(self, job, report_progress):
        """Runs on PersistentWorker's own daemon thread -- single-owner reasoning
        identical to PrimesieveCalcTab._primesieve_calc_job's own docstring
        (self._primality_busy blocks new requests from the GUI side, so only one job is
        ever in flight). No WSL subprocess here at all -- primeatlas.primality is
        ordinary in-process pure Python, run directly on this thread. Catches its own
        exceptions (per PersistentWorker's fn contract -- see background.py's docstring)
        so a failure surfaces with the right op/n context via a normal error-dialog
        result, instead of falling through to PersistentWorker's own last-resort net
        which has no way to know which request failed."""
        op = job["op"]
        try:
            if op == "check":
                rows = primality_run_all_tests(job["n"])
                return op, job["n"], True, rows
            result = primality_factorize(job["n"], use_sympy=job["use_sympy"])
            return op, job["n"], True, result
        except Exception as e:  # noqa: BLE001 -- surface any unexpected failure to the
                                 # GUI as an error dialog instead of silently killing
                                 # this worker thread
            return op, job["n"], False, str(e)

    def _on_primality_worker_result(self, payload, error):
        """Main-thread callback for _primality_job -- `error` is only non-None for a
        genuine PersistentWorker-framework bug (_primality_job already catches its own
        exceptions -- see its docstring)."""
        self._primality_set_busy(False)
        if error is not None:
            self.status.set(self.T("primality.status_error"))
            messagebox.showerror(self.T("primality.error_dialog_title"), str(error))
            return
        op, n, ok, result_payload = payload
        if not ok:
            self.status.set(self.T("primality.status_error"))
            messagebox.showerror(self.T("primality.error_dialog_title"), result_payload)
            return
        self.status.set(self.T("primality.status_done"))
        if op == "check":
            self._primality_show_check_results(result_payload)
        else:
            self._primality_show_factorize_result(n, result_payload)

    def _primality_show_check_results(self, rows):
        self.primality_results_tree.delete(*self.primality_results_tree.get_children())
        for row in rows:
            verdict = (self.T("primality.verdict_prime") if row["is_prime"]
                       else self.T("primality.verdict_composite"))
            self.primality_results_tree.insert(
                "", "end",
                values=(row["method"], verdict, row["certainty"], f"{row['seconds']:.4f}"))

    def _primality_show_factorize_result(self, n, result):
        pairs = result["pairs"]
        factor_str = " x ".join(
            f"{p}^{e}" if e > 1 else str(p) for p, e in pairs) or str(n)
        method = (self.T("primality.method_sympy") if result["method"] == "sympy"
                  else self.T("primality.method_pure_python"))
        text = self.T("primality.factor_result", n=f"{n:,}", factors=factor_str,
                       method=method, seconds=f"{result['seconds']:.4f}")
        if not result["complete"]:
            text += " " + self.T("primality.factor_result_incomplete_note")
        self.primality_factor_result_var.set(text)
        self.primality_factors_only_var.set(factor_str)
        self.primality_factors_copy_button.configure(state="normal")

    def _on_primality_copy_factors(self):
        text = self.primality_factors_only_var.get()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
