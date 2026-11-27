"""
irreducibility_primality_view.py -- Research -> Irreducibility -> Primality: whether A (the
same field and layout as in Comparison) is prime, decided by isPrimeRes (T6) from its
residues alone: divisors m = 2, 3, ... are compared with A and m^2 with A on residues, and
A mod m is read from the mixed-radix digits. At most `fuel` divisors are tried.

The run advances in time slices (irreducibility_primality.PrimalityRun) so the window stays
responsive; Stop ends it without an answer. The result shows the verdict, the step count,
the first and last steps and a check against integer primality (Miller-Rabin, outside the
residue arithmetic). Fit for primality sets a layout with W > (isqrt(A) + 1)^2, under which
the square test stops the run at isqrt(A) + 1. Test N numbers runs
irreducibility_selftest.primality_test.
"""
import random
import time
import tkinter as tk
from tkinter import ttk

from ..core.number_text import plain_number
from ..core.base_tab import BaseTab
from ..core.widgets import HeightGrip, StripedTreeview
from ..primality.primality import miller_rabin_test
from . import irreducibility_layout as layout
from . import irreducibility_residues as res
from .irreducibility_cases_window import show_cases
from .irreducibility_numbers import blocks_text, layout_info
from .irreducibility_primality import PrimalityRun, fit_target, square_test_holds
from .irreducibility_selftest import primality_test
from .irreducibility_widgets import entry, refusing, wrapped_label

DEFAULT_FUEL = 10 ** 6
"""Divisors tried before a run gives up; arbitrary."""

MAX_FUEL = 10 ** 9
"""Largest accepted fuel; arbitrary."""

SLICE_SECONDS = 0.05
"""Computing time per slice before the window handles its events; arbitrary."""

SLICE_STEPS = 200
"""Steps between clock reads inside a slice; arbitrary."""

PRIMALITY_TEST_COUNT = 1000

_CMP = {-1: "<", 0: "=", 1: ">", None: ""}


class PrimalityView(BaseTab):
    def __init__(self, parent, translator, palette, numbers):
        super().__init__(parent, translator)
        T = self.T
        self.numbers = numbers
        self.palette = palette
        self.cases_window = None
        self.last_check = None
        self._run = None
        self._run_n = None
        self._after = None
        wrapped_label(self, text=T("research_irreducibility.primality_desc"),
                      style="Hint.TLabel", padx=6, pady=(8, 4))
        box = ttk.LabelFrame(self, text=T("research_irreducibility.arith_number_title",
                                          side="A"))
        box.pack(fill="x", padx=6)
        row = ttk.Frame(box)
        row.pack(fill="x", padx=6, pady=(4, 2))
        start = refusing(self, lambda: [self.number_entry, self.fuel_entry], self.start)
        self.number_entry = entry(T, "field_tip.irreducibility_number",
                                  row, "", "", width=34, textvariable=numbers.number_var("A"),
                                  on_return=start, minimum=0)
        self.fit_button = ttk.Button(row, text=T("research_irreducibility.primality_fit"),
                                     command=refusing(self, lambda: [self.number_entry],
                                                      self.fit))
        self.fit_button.pack(side="left")
        self.info_var = tk.StringVar()
        wrapped_label(box, textvariable=self.info_var, style="Hint.TLabel", padx=6, pady=(2, 2))
        self.square_note_var = tk.StringVar()
        wrapped_label(box, textvariable=self.square_note_var, style="Hint.TLabel", padx=6,
                      pady=(0, 6))

        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=(8, 4))
        self.fuel_entry = entry(T, "field_tip.irreducibility_primality_fuel",
                                row, T("research_irreducibility.primality_fuel"),
                                str(DEFAULT_FUEL), "research.irreducibility.primality_fuel",
                                width=12, on_return=start, minimum=1)
        self.run_button = ttk.Button(row, text=T("research_irreducibility.primality_run"),
                                     command=start)
        self.run_button.pack(side="left")
        self.stop_button = ttk.Button(row, text=T("research_irreducibility.primality_stop"),
                                      command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=(8, 0))
        self.test_button = ttk.Button(
            row, text=T("research_irreducibility.primality_test_button",
                        count=PRIMALITY_TEST_COUNT), command=self.self_test)
        self.test_button.pack(side="left", padx=(8, 0))

        self.message_var = tk.StringVar()
        wrapped_label(self, textvariable=self.message_var, padx=6)
        self.progress_var = tk.StringVar()
        ttk.Label(self, textvariable=self.progress_var, style="Hint.TLabel").pack(anchor="w",
                                                                                padx=6)
        self.verdict_var = tk.StringVar()
        ttk.Label(self, textvariable=self.verdict_var,
                  font=("TkDefaultFont", 16, "bold")).pack(anchor="w", padx=6)
        self.result_var = tk.StringVar()
        wrapped_label(self, textvariable=self.result_var, padx=6)
        self.oracle_var = tk.StringVar()
        self.oracle_label = tk.Label(self, textvariable=self.oracle_var, anchor="w",
                                     background=palette["bg"])
        self.oracle_label.pack(anchor="w", padx=6, pady=(0, 4))

        frame = ttk.Frame(self)
        frame.pack(fill="x", padx=6)
        cols = ("step", "m", "vs_m", "vs_square", "remainder")
        self.steps_tree = StripedTreeview(frame, columns=cols, show="headings", height=12)
        for c in cols:
            self.steps_tree.heading(c, text=T(f"research_irreducibility.primality_col_{c}"))
            self.steps_tree.column(c, width=120, anchor="e")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.steps_tree.yview)
        self.steps_tree.configure(yscrollcommand=scroll.set)
        self.steps_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        HeightGrip(self, self.steps_tree, after=frame, padx=6, pady=(2, 8),
                   place="irreducibility.primality")

        numbers.on_change(lambda side: side == "A" and self.refresh_info())
        self.refresh_info()

    # --- state read by the tests and the buttons -----------------------------------------

    @property
    def answer(self):
        return self._run.answer if self._run else None

    @property
    def reason(self):
        return self._run.reason if self._run else None

    @property
    def steps(self):
        return self._run.steps if self._run else 0

    def is_running(self):
        return self._after is not None

    def button_state(self):
        return "running" if self.is_running() else "idle"

    # --- inputs --------------------------------------------------------------------------

    def refresh_info(self):
        T = self.T
        self.square_note_var.set("")
        try:
            D, K = self.numbers.layout("A")
        except ValueError:
            self.info_var.set(T("research_irreducibility.layout_invalid"))
            return
        try:
            n = self.numbers.number("A")
        except ValueError:
            n = None
        self.info_var.set(blocks_text(D, K, T) + "\n" + layout_info(T, D, K, n))
        w = layout.capacity(D, K)
        if n is not None and n < w and not square_test_holds(n, w):
            self.square_note_var.set(T("research_irreducibility.primality_square_note"))

    def fit(self):
        try:
            n = self.numbers.number("A")
        except ValueError:
            self._clear(self.T("research_irreducibility.number_invalid"))
            return
        self.numbers.fit("A", fit_target(n))
        self.message_var.set("")

    def _read(self):
        """(n, moduli, residues, fuel) or a translated error message."""
        T = self.T
        try:
            D, K = self.numbers.layout("A")
        except ValueError:
            return T("research_irreducibility.layout_invalid")
        try:
            n = self.numbers.number("A")
        except ValueError:
            return T("research_irreducibility.number_invalid")
        try:
            fuel = int(plain_number(self.fuel_entry.get()))
        except ValueError:
            fuel = 0
        if not 1 <= fuel <= MAX_FUEL:
            return T("research_irreducibility.primality_fuel_invalid",
                     max=layout.fmt_big(MAX_FUEL))
        w = layout.capacity(D, K)
        if w <= 2:
            return T("research_irreducibility.primality_w_too_small")
        if n >= w:
            return T("research_irreducibility.arith_does_not_fit", side="A")
        moduli, residues = res.flatten(layout.block_rep_of(n, D, K))
        return n, moduli, residues, fuel

    # --- the run -------------------------------------------------------------------------

    def _cancel(self):
        if self._after is not None:
            self.after_cancel(self._after)
            self._after = None
        self.stop_button.configure(state="disabled")

    def _clear(self, message):
        self._cancel()
        self._run = None
        self.last_check = None
        self.message_var.set(message)
        for var in (self.progress_var, self.verdict_var, self.result_var, self.oracle_var):
            var.set("")
        self.steps_tree.delete(*self.steps_tree.get_children())

    def start(self):
        got = self._read()
        if isinstance(got, str):
            self._clear(got)
            return
        n, moduli, residues, fuel = got
        self._clear("")
        self._run = PrimalityRun(moduli, residues, fuel)
        self._run_n = n
        self.stop_button.configure(state="normal")
        self._after = self.after(1, self._tick)

    def _tick(self):
        run = self._run
        start = time.perf_counter()
        while not run.advance(SLICE_STEPS) and time.perf_counter() - start < SLICE_SECONDS:
            pass
        self.progress_var.set(self.T("research_irreducibility.primality_progress",
                                     m=run.current_m(), steps=run.steps, fuel=run.fuel))
        if run.done:
            self._after = None
            self._finish()
        else:
            self._after = self.after(1, self._tick)

    def stop(self):
        if self._run is not None and self.is_running():
            self._run.stop()
            self._cancel()
            self._finish()

    def destroy(self):
        self._cancel()
        super().destroy()

    def _finish(self):
        T = self.T
        run, n = self._run, self._run_n
        self.stop_button.configure(state="disabled")
        m = run.current_m()
        self.verdict_var.set(T(f"research_irreducibility.primality_verdict_{run.reason}",
                               n=n, m=m, fuel=run.fuel))
        self.result_var.set(T("research_irreducibility.primality_steps", steps=run.steps))
        is_prime, certainty = miller_rabin_test(n)
        key = "primality_check_prime" if is_prime else "primality_check_composite"
        method = T("research_irreducibility.primality_method_"
                   + ("probable" if certainty.startswith("probabilistic") else "proven"))
        text = T(f"research_irreducibility.{key}", method=method)
        if run.answer is None:
            self.last_check = None
            self.oracle_var.set(text)
            self.oracle_label.configure(foreground=self.palette["hint_fg"])
        else:
            self.last_check = run.answer == is_prime
            self.oracle_var.set(text + " — " + T(
                "research_irreducibility.check_ok_text" if self.last_check
                else "research_irreducibility.check_bad_text"))
            self.oracle_label.configure(foreground="#2ca02c" if self.last_check else "#c0392b")
        tree = self.steps_tree
        tree.delete(*tree.get_children())
        rows = list(run.first)
        tail = [r for r in run.last if r[0] > len(run.first)]
        if tail and tail[0][0] > len(run.first) + 1:
            rows.append(("…", "", "", "", ""))
        for r in rows + tail:
            if r[0] == "…":
                tree.insert("", "end", values=r)
                continue
            idx, mm, vs_m, vs_sq, rem = r
            tree.insert("", "end", values=(idx, mm, _CMP[vs_m], _CMP[vs_sq],
                                           "" if rem is None else rem))

    # --- self-test -----------------------------------------------------------------------

    def self_test(self):
        T = self.T
        out = primality_test(PRIMALITY_TEST_COUNT, random.Random())
        self._clear("")
        self.last_check = out["wrong"] == 0
        summary = T("research_irreducibility.primality_test_result", count=out["count"],
                    wrong=out["wrong"])
        self.verdict_var.set(summary)
        self.oracle_var.set(T("research_irreducibility.primality_test_note"))
        self.oracle_label.configure(foreground="#2ca02c" if self.last_check else "#c0392b")
        columns = [("no", T("research_irreducibility.cases_col_no"), 50, False),
                   ("task", T("research_irreducibility.cases_col_task"), 260, True),
                   ("residues", T("research_irreducibility.cases_col_residues"), 260, True),
                   ("integers", T("research_irreducibility.cases_col_integers"), 260, True),
                   ("ok", T("research_irreducibility.cases_col_ok"), 60, False)]
        rows = [((i + 1, c["task"], c["residues"], c["integers"]), c["ok"], c["detail"])
                for i, c in enumerate(out["cases"])]
        show_cases(self, self.palette, T("research_irreducibility.cases_title_primality"),
                   summary, self.last_check, columns, rows,
                   T("research_irreducibility.cases_detail_primality"))
