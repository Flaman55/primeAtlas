"""
research_squares_tab.py -- ResearchSquaresTab, the tkinter widgets for the
Research tab's Przedzialy kwadratowe (square intervals) sub-tab: Legendre/
Oppermann/Brocard presets plus a custom a(n)/b(n) formula pair, checked over a
[n_from, n_to] range via primeatlas/squares_window.py's pure
check_interval_range().

Faza 1 (Artur, 2026-09-13): always sieves fresh in-process, no on-disk-magazyn
bridge yet (mirrors research_goldbach.py's read_is_prime_from_storage -- see
squares_window.py's own MAX_SIEVE_BOUND docstring for exactly why that is
deferred rather than needed from day one: comfortably enough range for
interactive exploration without it). No CSV export yet either -- both are
natural follow-ups, added the same incremental way Goldbach's own tab grew
sub-feature by sub-feature over several phases.

squares_window.py is a self-contained pure-math module, not shared with
goldbach_window.py despite the near-identical sieve_is_prime -- same
reasoning as rings_tab.py's and generation_tab.py's own independently-
duplicated _build_scrollable_container: each conjecture/feature module in
this project stays free-standing rather than importing across conjecture
boundaries, so a change to one can never accidentally ripple into an
unrelated one.

Custom-formula evaluation (_eval_formula below) is a RESTRICTED eval (no
builtins, only a bound `n`) -- same "personal desktop tool, not a network-
facing service, but no reason to allow arbitrary code execution just to
parse a typed formula" reasoning as generation.py's own _eval_quick_number,
which this module does not reuse directly since that helper has no `n`
variable to substitute.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from . import background
from .base_tab import BaseTab
from .squares_window import check_interval_range, PRESETS

SQUARES_ROW_CAP = 200
"""Rows per page in the results Treeview -- same "verdict/counterexamples
always computed over the FULL range, only the display paginates" contract as
squares_window.check_interval_range's own row_cap/row_offset."""

_PRESET_IDS = ("legendre", "oppermann", "brocard", "custom")


def _eval_formula(formula, n):
    """Evaluates a user-typed a(n)/b(n) formula string with `n` bound to the
    given integer -- restricted eval (no builtins), same reasoning as
    generation._eval_quick_number (see this module's own docstring). Raises
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


class ResearchSquaresTab(BaseTab):
    def __init__(self, parent, translator, totals_progress, eval_quick_number):
        """
        translator/totals_progress: same dependency-injection pattern as every
        other extracted tab -- see primeatlas/primes_tab.py's own docstring.
        eval_quick_number: prime_atlas_v1.py's shared numeric-field parser
        (generation._eval_quick_number), used for the plain integer n_from/
        n_to/required_count fields -- NOT for the custom a(n)/b(n) formulas,
        which need an `n` variable substituted per-row instead (see
        _eval_formula above)."""
        super().__init__(parent, translator)
        self.totals_progress = totals_progress
        self._eval_quick_number = eval_quick_number

        # Own PersistentWorker, pure Python, no WSL round trip -- same
        # single-shared-background-thread pattern every job dispatcher in
        # this app uses (see background.py's own docstring).
        self._squares_busy = False
        self._squares_worker = background.PersistentWorker(
            self, self._squares_job, on_result=self._on_squares_worker_result)
        self._squares_last_result = None
        self._squares_page = 0

        self._build_widgets()

    def _build_widgets(self):
        T = self.T
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=(10, 4))
        ttk.Label(top, text=T("research_squares.preset_label")).pack(side="left")
        self.squares_preset_combo = ttk.Combobox(
            top, state="readonly", width=16,
            values=[T(f"research_squares.preset_{pid}") for pid in _PRESET_IDS])
        self.squares_preset_combo.current(0)
        self.squares_preset_combo.pack(side="left", padx=(6, 16))
        self.squares_preset_combo.bind("<<ComboboxSelected>>", self._on_squares_preset_changed)

        ttk.Label(top, text=T("research_squares.required_count_label")).pack(side="left")
        self.squares_required_count_entry = ttk.Entry(top, width=6)
        self.squares_required_count_entry.insert(0, "1")
        self.squares_required_count_entry.pack(side="left", padx=(6, 0))

        range_row = ttk.Frame(self)
        range_row.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(range_row, text=T("research_squares.n_from_label")).pack(side="left")
        self.squares_n_from_entry = ttk.Entry(range_row, width=12)
        self.squares_n_from_entry.insert(0, "1")
        self.squares_n_from_entry.pack(side="left", padx=(6, 16))
        ttk.Label(range_row, text=T("research_squares.n_to_label")).pack(side="left")
        self.squares_n_to_entry = ttk.Entry(range_row, width=12)
        self.squares_n_to_entry.insert(0, "100")
        self.squares_n_to_entry.pack(side="left", padx=(6, 0))
        self._squares_range_row = range_row

        # Only shown/relevant when preset == "custom" -- see
        # _set_custom_fields_visible/_on_squares_preset_changed. Anchored via
        # pack(after=range_row) (not a plain pack()) so toggling it back on
        # after a pack_forget() lands it in its original slot -- a bare
        # pack() would instead append it after whatever else is currently
        # packed (button_row, the tree, ...), which is NOT where it belongs.
        self.squares_custom_frame = ttk.Frame(self)
        ttk.Label(self.squares_custom_frame, text=T("research_squares.custom_a_label")).pack(side="left")
        self.squares_custom_a_entry = ttk.Entry(self.squares_custom_frame, width=16)
        self.squares_custom_a_entry.insert(0, "n**2")
        self.squares_custom_a_entry.pack(side="left", padx=(6, 16))
        ttk.Label(self.squares_custom_frame, text=T("research_squares.custom_b_label")).pack(side="left")
        self.squares_custom_b_entry = ttk.Entry(self.squares_custom_frame, width=16)
        self.squares_custom_b_entry.insert(0, "(n+1)**2")
        self.squares_custom_b_entry.pack(side="left", padx=(6, 0))
        self._set_custom_fields_visible(False)

        button_row = ttk.Frame(self)
        button_row.pack(fill="x", padx=6, pady=(0, 8))
        self.squares_run_button = ttk.Button(
            button_row, text=T("research_squares.run_button"), command=self._on_squares_run)
        self.squares_run_button.pack(side="left")
        self.squares_prev_button = ttk.Button(
            button_row, text=T("research_squares.prev_button"),
            command=self._on_squares_prev, state="disabled")
        self.squares_prev_button.pack(side="left", padx=(16, 0))
        self.squares_next_button = ttk.Button(
            button_row, text=T("research_squares.next_button"),
            command=self._on_squares_next, state="disabled")
        self.squares_next_button.pack(side="left", padx=(6, 0))

        ttk.Label(self, text=T("research_squares.hint"),
                  wraplength=760, justify="left", foreground="#555").pack(
            anchor="w", padx=6, pady=(0, 8))

        self.squares_summary_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.squares_summary_var,
                  wraplength=760, justify="left").pack(anchor="w", padx=6, pady=(0, 8))

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        columns = ("n", "a", "b", "count", "covered")
        self.squares_results_tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", height=16)
        self.squares_results_tree.heading("n", text=T("research_squares.col_n"))
        self.squares_results_tree.heading("a", text=T("research_squares.col_a"))
        self.squares_results_tree.heading("b", text=T("research_squares.col_b"))
        self.squares_results_tree.heading("count", text=T("research_squares.col_count"))
        self.squares_results_tree.heading("covered", text=T("research_squares.col_covered"))
        self.squares_results_tree.column("n", width=90, anchor="e")
        self.squares_results_tree.column("a", width=140, anchor="e")
        self.squares_results_tree.column("b", width=140, anchor="e")
        self.squares_results_tree.column("count", width=90, anchor="e")
        self.squares_results_tree.column("covered", width=90, anchor="center")
        svsb = ttk.Scrollbar(
            tree_frame, orient="vertical", command=self.squares_results_tree.yview)
        self.squares_results_tree.configure(yscrollcommand=svsb.set)
        self.squares_results_tree.pack(side="left", fill="both", expand=True)
        svsb.pack(side="right", fill="y")

    def _set_custom_fields_visible(self, visible):
        if visible:
            self.squares_custom_frame.pack(fill="x", padx=6, pady=(0, 4),
                                            after=self._squares_range_row)
        else:
            self.squares_custom_frame.pack_forget()

    def _current_preset_id(self):
        return _PRESET_IDS[self.squares_preset_combo.current()]

    def _on_squares_preset_changed(self, _event=None):
        preset = self._current_preset_id()
        self._set_custom_fields_visible(preset == "custom")
        default_required = PRESETS.get(preset, {}).get("required_count", 1)
        self.squares_required_count_entry.delete(0, "end")
        self.squares_required_count_entry.insert(0, str(default_required))

    def _parse_positive_int(self, entry, field_name_key):
        T = self.T
        value = self._eval_quick_number(entry.get())
        if value is None or value < 1:
            raise ValueError(T("research_squares.error_field_positive_int",
                                field=T(field_name_key)))
        return value

    def _on_squares_run(self):
        T = self.T
        if self._squares_busy:
            return
        preset = self._current_preset_id()
        try:
            n_from = self._parse_positive_int(self.squares_n_from_entry, "research_squares.n_from_label")
            n_to = self._parse_positive_int(self.squares_n_to_entry, "research_squares.n_to_label")
            if n_to < n_from:
                raise ValueError(T("research_squares.error_range_order"))
            required_count = self._parse_positive_int(
                self.squares_required_count_entry, "research_squares.required_count_label")
            custom_a = custom_b = None
            if preset == "custom":
                custom_a = self.squares_custom_a_entry.get()
                custom_b = self.squares_custom_b_entry.get()
                # Validate against n_from right away, so a typo shows an error
                # immediately instead of only once the worker thread hits it.
                _eval_formula(custom_a, n_from)
                _eval_formula(custom_b, n_from)
        except ValueError as e:
            messagebox.showerror(T("research_squares.error_dialog_title"), str(e))
            return

        self._squares_set_busy(True)
        self._squares_worker.submit({
            "preset": preset, "n_from": n_from, "n_to": n_to,
            "required_count": required_count, "custom_a": custom_a, "custom_b": custom_b,
            "page": 0,
        })

    def _on_squares_prev(self):
        if self._squares_page > 0:
            self._squares_requeue_page(self._squares_page - 1)

    def _on_squares_next(self):
        self._squares_requeue_page(self._squares_page + 1)

    def _squares_requeue_page(self, page):
        last = self._squares_last_result
        if last is None or self._squares_busy:
            return
        self._squares_set_busy(True)
        self._squares_worker.submit({
            "preset": last["preset"], "n_from": last["n_from"], "n_to": last["n_to"],
            "required_count": last["required_count"],
            "custom_a": last.get("custom_a"), "custom_b": last.get("custom_b"),
            "page": page,
        })

    def _squares_set_busy(self, busy):
        self._squares_busy = busy
        self.squares_run_button.configure(state="disabled" if busy else "normal")
        if busy:
            self.squares_prev_button.configure(state="disabled")
            self.squares_next_button.configure(state="disabled")
            self._start_busy_progress()
        else:
            self._stop_busy_progress()

    def _squares_job(self, job, _report_progress):
        """Runs on PersistentWorker's own daemon thread -- see background.py's
        own docstring for the single-owner-thread contract this relies on
        (self._squares_busy blocks new requests from the GUI side, so only
        one job is ever in flight). Builds a bounds_fn closure for the
        "custom" preset right here rather than on the GUI thread -- ordinary
        Python closures cross a plain thread boundary within the same
        process with no marshalling needed (unlike this app's WSL-subprocess
        calls elsewhere, which genuinely do need serializable arguments)."""
        preset = job["preset"]
        if preset == "custom":
            custom_a, custom_b = job["custom_a"], job["custom_b"]

            def bounds_fn(n, _a=custom_a, _b=custom_b):
                return [(_eval_formula(_a, n), _eval_formula(_b, n))]
        else:
            bounds_fn = None
        try:
            result = check_interval_range(
                preset, job["n_from"], job["n_to"],
                required_count=job["required_count"], bounds_fn=bounds_fn,
                row_cap=SQUARES_ROW_CAP, row_offset=job["page"] * SQUARES_ROW_CAP)
            result["custom_a"] = job.get("custom_a")
            result["custom_b"] = job.get("custom_b")
            result["page"] = job["page"]
            return True, result
        except ValueError as e:
            return False, str(e)

    def _on_squares_worker_result(self, payload, error):
        T = self.T
        self._squares_set_busy(False)
        if error is not None:
            messagebox.showerror(T("research_squares.error_dialog_title"), str(error))
            self._squares_refresh_nav_buttons()
            return
        ok, data = payload
        if not ok:
            messagebox.showerror(T("research_squares.error_dialog_title"), str(data))
            self._squares_refresh_nav_buttons()
            return
        self._squares_show_result(data)

    def _squares_refresh_nav_buttons(self):
        last = self._squares_last_result
        self.squares_prev_button.configure(
            state="normal" if last and self._squares_page > 0 else "disabled")
        self.squares_next_button.configure(
            state="normal" if last and last.get("rows_truncated") else "disabled")

    def _squares_show_result(self, result):
        T = self.T
        self._squares_last_result = result
        self._squares_page = result["page"]

        for item in self.squares_results_tree.get_children():
            self.squares_results_tree.delete(item)
        for row in result["rows"]:
            for interval in row["intervals"]:
                self.squares_results_tree.insert("", "end", values=(
                    row["n"], interval["a"], interval["b"], interval["count"],
                    T("research_squares.covered_yes") if interval["covered"]
                    else T("research_squares.covered_no"),
                ))

        if result["covered"]:
            self.squares_summary_var.set(T(
                "research_squares.summary_covered",
                n_from=f"{result['n_from']:,}", n_to=f"{result['n_to']:,}"))
        else:
            shown = result["counterexamples"][:20]
            more = len(result["counterexamples"]) - len(shown)
            counterexamples_text = ", ".join(str(n) for n in shown)
            if more > 0:
                counterexamples_text += T("research_squares.summary_more_suffix", more=more)
            self.squares_summary_var.set(T(
                "research_squares.summary_not_covered",
                count=len(result["counterexamples"]), counterexamples=counterexamples_text))

        self._squares_refresh_nav_buttons()
