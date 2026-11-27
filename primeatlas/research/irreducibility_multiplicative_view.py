"""
irreducibility_multiplicative_view.py -- Research -> Irreducibility -> Multiplicative counting
(T9): one cycle of g modulo q counted multiplicatively (start at 1, multiply by g per step)
next to the additive counter modulo q - 1, the order of g, whether both counters are equal at
the same pairs of steps, the step reaching N mod q and its parity (N a square modulo q), and
the sech comb of modulus q - 1 with the returns to 1 (irreducibility_multiplicative.py).

g is a number or Auto (irreducibility_multiplicative.auto_generator). The square reading is
given only when g has order q - 1, which happens only for a prime q. The check compares it
with Euler's criterion and q's primality on integers (Miller-Rabin), outside the counting.
Everything computes synchronously, on opening and on the button; one cycle is at most MAX_Q
steps.
"""
import random
import tkinter as tk
from tkinter import ttk

from ..core.number_text import plain_number
from ..core.base_tab import BaseTab
from ..core.widgets import HeightGrip, StripedTreeview
from ..primality.primality import miller_rabin_test
from . import irreducibility_multiplicative as mult
from .irreducibility_cases_window import show_cases
from .irreducibility_draw import draw_returns
from .irreducibility_numbers import parse_number
from .irreducibility_selftest import multiplicative_test
from .irreducibility_widgets import entry, refusing, wrapped_label

COMB_SCALE = 8.0
"""Scale of the drawn comb; arbitrary, at least irreducibility_comb.PROVED_SCALE."""

MUL_TEST_COUNT = 1000

AUTO = "auto"

_PEAKS_SHOWN = 8
"""Steps listed in the comb line before an ellipsis; arbitrary."""


def _steps_text(steps):
    head = ", ".join(map(str, steps[:_PEAKS_SHOWN]))
    return head + (", …" if len(steps) > _PEAKS_SHOWN else "")


class MultiplicativeView(BaseTab):
    def __init__(self, parent, translator, palette):
        super().__init__(parent, translator)
        T = self.T
        self.palette = palette
        self.cases_window = None
        self.result = None
        self.g_used = None
        self.auto_used = False
        self.last_check = None
        self._comb = None
        wrapped_label(self, text=T("research_irreducibility.mul_desc"), style="Hint.TLabel",
                      padx=6, pady=(8, 4))
        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=(0, 4))
        run = refusing(self, lambda: [self.q_entry, self.g_entry, self.n_entry], self.run)
        self.q_entry = entry(T, "field_tip.irreducibility_mul_q",
                             row, "q", "23", "research.irreducibility.mul_q", width=8,
                             on_return=run, minimum=2)
        self.g_entry = entry(T, "field_tip.irreducibility_mul_g",
                             row, "g", AUTO, "research.irreducibility.mul_g", width=6,
                             on_return=run, words=(AUTO,), minimum=1)
        self.n_entry = entry(T, "field_tip.irreducibility_mul_n",
                             row, "N", "10", "research.irreducibility.mul_n", width=24,
                             on_return=run, minimum=0)
        self.run_button = ttk.Button(row, text=T("research_irreducibility.mul_run"),
                                     command=run)
        self.run_button.pack(side="left")
        self.test_button = ttk.Button(
            row, text=T("research_irreducibility.mul_test_button", count=MUL_TEST_COUNT),
            command=self.self_test)
        self.test_button.pack(side="left", padx=(8, 0))

        self.message_var = tk.StringVar()
        wrapped_label(self, textvariable=self.message_var, padx=6)
        self.generator_var = tk.StringVar()
        wrapped_label(self, textvariable=self.generator_var, padx=6)
        self.pairs_var = tk.StringVar()
        wrapped_label(self, textvariable=self.pairs_var, padx=6)
        self.step_var = tk.StringVar()
        wrapped_label(self, textvariable=self.step_var, padx=6)
        self.verdict_var = tk.StringVar()
        ttk.Label(self, textvariable=self.verdict_var,
                  font=("TkDefaultFont", 16, "bold")).pack(anchor="w", padx=6)
        self.oracle_var = tk.StringVar()
        self.oracle_label = tk.Label(self, textvariable=self.oracle_var, anchor="w",
                                     justify="left", background=palette["bg"])
        self.oracle_label.pack(anchor="w", padx=6, pady=(0, 4))

        body = ttk.Frame(self)
        body.pack(fill="x", padx=6, pady=(0, 8))
        # The table and its grip in their own column, so the chart beside it never
        # stretches the table.
        table_column = ttk.Frame(body)
        table_column.pack(side="left", anchor="n")
        table_row = ttk.Frame(table_column)
        table_row.pack(fill="x")
        cols = ("t", "value", "count", "mark")
        self.table = StripedTreeview(table_row, columns=cols, show="headings", height=10)
        for c, width in zip(cols, (70, 90, 100, 110)):
            self.table.heading(c, text=T(f"research_irreducibility.mul_col_{c}"))
            self.table.column(c, width=width, anchor="e", stretch=False)
        scroll = ttk.Scrollbar(table_row, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="y")
        scroll.pack(side="left", fill="y")
        HeightGrip(table_column, self.table, after=table_row,
                   place="irreducibility.multiplicative")
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.comb_var = tk.StringVar()
        wrapped_label(right, textvariable=self.comb_var, style="Hint.TLabel")
        self.canvas = tk.Canvas(right, width=500, height=170, background=palette["console_bg"],
                                highlightthickness=1, highlightbackground=palette["border"])
        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        # Packed with the chart, below it (see the chart's own pack/pack_forget).
        self.canvas_grip = HeightGrip(right, self.canvas,
                                      place="irreducibility.multiplicative_chart")
        self.run()

    # --- inputs --------------------------------------------------------------------------

    def _read(self):
        """(q, g or None for Auto, N) or a translated error message."""
        T = self.T
        try:
            q = int(plain_number(self.q_entry.get()))
        except ValueError:
            q = 0
        if not 2 <= q <= mult.MAX_Q:
            return T("research_irreducibility.mul_q_invalid", max=mult.MAX_Q)
        text = plain_number(self.g_entry.get(), words=(AUTO,))
        g = None
        if text.lower() != AUTO:
            try:
                g = int(text)
            except ValueError:
                g = 0
            if not 1 <= g < q:
                return T("research_irreducibility.mul_g_invalid")
        try:
            n = parse_number(self.n_entry.get())
        except ValueError:
            return T("research_irreducibility.mul_n_invalid")
        return q, g, n

    def _clear(self, message):
        self.result = None
        self.g_used = None
        self.auto_used = False
        self.last_check = None
        self._comb = None
        self.message_var.set(message)
        for var in (self.generator_var, self.pairs_var, self.step_var, self.verdict_var,
                    self.oracle_var, self.comb_var):
            var.set("")
        self.table.delete(*self.table.get_children())
        self.canvas.delete("all")
        self.canvas.pack_forget()
        self.canvas_grip.pack_forget()

    # --- the cycle -----------------------------------------------------------------------

    def run(self):
        T = self.T
        got = self._read()
        if isinstance(got, str):
            self._clear(got)
            return
        q, g, n = got
        self._clear("")
        self.auto_used = g is None
        if g is None:
            g, order = mult.auto_generator(q)
            if order != q - 1:
                self.message_var.set(T("research_irreducibility.mul_auto_note",
                                       max=mult.AUTO_MAX_G, max_q=mult.MAX_Q))
        a = mult.analyze(q, g, n)
        self.result, self.g_used = a, g
        self._show_generator(q, g, a)
        self._show_pairs(a)
        self._show_step(g, a)
        self._show_verdict(q, g, n, a)
        self._show_check(q, n, a)
        self._fill_table(q, a)
        self._show_comb(q, g, a)

    def _show_generator(self, q, g, a):
        T = self.T
        auto = T("research_irreducibility.mul_auto_suffix") if self.auto_used else ""
        if a["order"] is None:
            self.generator_var.set(T("research_irreducibility.mul_order_none", g=g, auto=auto))
        elif a["primitive"]:
            self.generator_var.set(T("research_irreducibility.mul_order_full", g=g, auto=auto,
                                     order=a["order"]))
        else:
            self.generator_var.set(T("research_irreducibility.mul_order_short", g=g, auto=auto,
                                     order=a["order"], q1=q - 1))

    def _show_pairs(self, a):
        T = self.T
        if a["pairs_break"] is None:
            self.pairs_var.set(T("research_irreducibility.mul_pairs_equal"))
            return
        u, t = a["pairs_break"]
        self.pairs_var.set(T("research_irreducibility.mul_pairs_break", u=u, t=t,
                             vu=a["values"][u], vt=a["values"][t], cu=a["counts"][u],
                             ct=a["counts"][t]))

    def _show_step(self, g, a):
        T = self.T
        if a["step"] is None:
            self.step_var.set(T("research_irreducibility.mul_residue", r=a["r"]))
        else:
            self.step_var.set(T("research_irreducibility.mul_step", r=a["r"], t=a["step"],
                                g=g))

    def _show_verdict(self, q, g, n, a):
        T = self.T
        if q == 2:
            key, kw = "mul_verdict_q2", {}
        elif a["r"] == 0:
            key, kw = "mul_verdict_divides", {"q": q, "n": n}
        elif a["step"] is None:
            key, kw = "mul_verdict_not_reached", {"r": a["r"], "g": g}
        elif a["square"] is None:
            key, kw = "mul_verdict_withheld", {"g": g}
        else:
            key = "mul_verdict_square" if a["square"] else "mul_verdict_nonsquare"
            kw = {"n": n, "q": q, "t": a["step"]}
        self.verdict_var.set(T(f"research_irreducibility.{key}", **kw))

    def _show_check(self, q, n, a):
        """Integers: q's primality and, for an odd q not dividing N, Euler's criterion."""
        T = self.T
        is_prime, certainty = miller_rabin_test(q)
        method = T("research_irreducibility.primality_method_"
                   + ("probable" if certainty.startswith("probabilistic") else "proven"))
        key = "mul_check_prime" if is_prime else "mul_check_composite"
        text = T(f"research_irreducibility.{key}", method=method)
        euler = None
        if is_prime and q > 2 and a["r"] != 0:
            e = pow(n, (q - 1) // 2, q)
            euler = e == 1
            text += "; " + T("research_irreducibility.mul_check_euler", e=e,
                             verdict=T("research_irreducibility.mul_square" if euler
                                       else "research_irreducibility.mul_not_square"))
        if a["square"] is None or euler is None:
            self.last_check = None
            self.oracle_label.configure(foreground=self.palette["hint_fg"])
        else:
            self.last_check = a["square"] == euler
            text += " — " + T("research_irreducibility.check_ok_text" if self.last_check
                              else "research_irreducibility.check_bad_text")
            self.oracle_label.configure(foreground="#2ca02c" if self.last_check else "#c0392b")
        self.oracle_var.set(text)

    def _fill_table(self, q, a):
        T = self.T
        one = T("research_irreducibility.mul_mark_one")
        hit = T("research_irreducibility.mul_mark_r")
        for t in mult.table_steps(q, a["step"]):
            if t is None:
                self.table.insert("", "end", values=("…", "", "", ""))
                continue
            v = a["values"][t]
            mark = hit if t == a["step"] else (one if v == 1 else "")
            self.table.insert("", "end", values=(t, v, a["counts"][t], mark))

    def _show_comb(self, q, g, a):
        T = self.T
        if q > mult.COMB_MAX_Q:
            self.comb_var.set(T("research_irreducibility.mul_comb_too_large",
                                max=mult.COMB_MAX_Q))
            return
        peaks, returns = mult.comb_returns(COMB_SCALE, q, g)
        same = T("research_irreducibility.mul_comb_same" if peaks == returns
                 else "research_irreducibility.mul_comb_differ")
        self.comb_var.set(T("research_irreducibility.mul_comb_line", d=q - 1, s=f"{COMB_SCALE:g}",
                            peaks=_steps_text(peaks), returns=_steps_text(returns), same=same))
        self._comb = (q, returns, a["step"])
        self.canvas.pack(fill="x", pady=(4, 0))
        self.canvas_grip.pack(after=self.canvas)
        self._redraw()

    def _redraw(self):
        if self._comb is None:
            return
        q, returns, step = self._comb
        draw_returns(self.canvas, q - 1, max(2 * (q - 1), 2), COMB_SCALE, returns, step,
                     self.palette)

    # --- self-test -----------------------------------------------------------------------

    def self_test(self):
        T = self.T
        out = multiplicative_test(MUL_TEST_COUNT, random.Random())
        self._clear("")
        self.last_check = out["wrong"] == 0
        summary = T("research_irreducibility.mul_test_result", count=out["count"],
                    wrong=out["wrong"])
        self.verdict_var.set(summary)
        self.oracle_var.set(T("research_irreducibility.mul_test_note"))
        self.oracle_label.configure(foreground="#2ca02c" if self.last_check else "#c0392b")
        columns = [("no", T("research_irreducibility.cases_col_no"), 50, False),
                   ("task", T("research_irreducibility.cases_col_task"), 300, True),
                   ("residues", T("research_irreducibility.mul_cases_col_count"), 240, True),
                   ("integers", T("research_irreducibility.cases_col_integers"), 240, True),
                   ("ok", T("research_irreducibility.cases_col_ok"), 60, False)]
        rows = [((i + 1, c["task"], c["residues"], c["integers"]), c["ok"], c["detail"])
                for i, c in enumerate(out["cases"])]
        show_cases(self, self.palette, T("research_irreducibility.cases_title_mul"), summary,
                   self.last_check, columns, rows, T("research_irreducibility.cases_detail_mul"))
