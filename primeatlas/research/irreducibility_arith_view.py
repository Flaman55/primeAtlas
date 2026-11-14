"""
irreducibility_arith_view.py -- Research -> Irreducibility -> Arithmetic: operations on the
residues of A and B (the same numbers and layouts as the Comparison sub-tab), computed by
irreducibility_ops.py: A ⊕ B, A ⊖ B, A ⊗ B on the union of their moduli, A ⊘ b, the address
of A with respect to T, A^e, appending powers of p, and the random self-test of every kind.
Each result ends with a check against the integer result (outside the residue arithmetic).
"""
import math
import random
import tkinter as tk
from tkinter import ttk

from ..core.base_tab import BaseTab
from . import irreducibility_layout as layout
from . import irreducibility_ops as ops
from . import irreducibility_residues as res
from .irreducibility_cases_window import show_cases
from .irreducibility_numbers import blocks_text, layout_info
from .irreducibility_selftest import ops_test
from .irreducibility_widgets import OutputText, entry, wrapped_label

SHOWN_RESIDUES = 10
"""Residues listed per result; the rest is counted."""

MAX_EXPONENT = 10000
"""Largest accepted e of A^(e); arbitrary, bounds the integer check."""

MAX_CHAPTERS = 12

OPS_TEST_COUNT = 450


class _Bad(Exception):
    """An input error; its message is shown in the output."""


class ArithView(BaseTab):
    def __init__(self, parent, translator, palette, numbers):
        super().__init__(parent, translator)
        T = self.T
        self.numbers = numbers
        self.palette = palette
        self.last_check = None
        self.cases_window = None
        wrapped_label(self, text=T("research_irreducibility.arith_desc"), style="Hint.TLabel",
                      padx=6, pady=(8, 4))
        cards = ttk.Frame(self)
        cards.pack(fill="x", padx=6)
        cards.columnconfigure(0, weight=1, uniform="side")
        cards.columnconfigure(1, weight=1, uniform="side")
        self.number_entries = {}
        self._layout_vars = {}
        for col, side in enumerate(("A", "B")):
            box = ttk.LabelFrame(cards, text=T("research_irreducibility.arith_number_title",
                                               side=side))
            box.grid(row=0, column=col, sticky="nsew", padx=(0, 6) if col == 0 else (6, 0))
            row = ttk.Frame(box)
            row.pack(fill="x", padx=6, pady=(4, 2))
            self.number_entries[side] = entry(row, "", "", width=34,
                                              textvariable=numbers.number_var(side))
            ttk.Button(row, text=T("research_irreducibility.fit"),
                       command=lambda s=side: self._fit(s)).pack(side="left")
            self._layout_vars[side] = tk.StringVar()
            wrapped_label(box, textvariable=self._layout_vars[side], style="Hint.TLabel",
                          padx=6, pady=(2, 6))

        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=(8, 2))
        self.add_button = ttk.Button(row, text="A ⊕ B", command=lambda: self.add(1))
        self.add_button.pack(side="left")
        self.sub_button = ttk.Button(row, text="A ⊖ B", command=lambda: self.add(-1))
        self.sub_button.pack(side="left", padx=(8, 0))
        self.mul_button = ttk.Button(row, text="A ⊗ B", command=self.mul)
        self.mul_button.pack(side="left", padx=(8, 0))
        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=2)
        self.b_entry = entry(row, "b", "7", "research.irreducibility.arith_b", width=8)
        self.div_button = ttk.Button(row, text="A ⊘ b", command=self.div)
        self.div_button.pack(side="left", padx=(0, 18))
        self.t_entry = entry(row, "T", "30", "research.irreducibility.arith_t", width=8)
        self.address_button = ttk.Button(row, text=T("research_irreducibility.address_button"),
                                         command=self.address)
        self.address_button.pack(side="left")
        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=2)
        self.e_entry = entry(row, "e", "3", "research.irreducibility.arith_e", width=8)
        self.pow_button = ttk.Button(row, text="A^(e)", command=self.power)
        self.pow_button.pack(side="left", padx=(0, 18))
        self.p_entry = entry(row, "p", "5", "research.irreducibility.arith_p", width=6)
        self.n_entry = entry(row, "n", "3", "research.irreducibility.arith_n", width=6)
        self.chapters_button = ttk.Button(row, text=T("research_irreducibility.chapters_button"),
                                          command=self.chapters)
        self.chapters_button.pack(side="left")
        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=(2, 6))
        self.test_button = ttk.Button(
            row, text=T("research_irreducibility.ops_test_button", count=OPS_TEST_COUNT),
            command=self.self_test)
        self.test_button.pack(side="left")
        self.out = OutputText(self, palette)
        self.out.pack(fill="both", expand=True, padx=6, pady=(0, 8))

        numbers.on_change(self._refresh_layout)
        for side in ("A", "B"):
            self._refresh_layout(side)

    # --- inputs -------------------------------------------------------------------------

    def _refresh_layout(self, side):
        try:
            D, K = self.numbers.layout(side)
        except ValueError:
            self._layout_vars[side].set(self.T("research_irreducibility.layout_invalid"))
            return
        try:
            n = self.numbers.number(side)
        except ValueError:
            n = None
        self._layout_vars[side].set(blocks_text(D, K, self.T) + "\n" + layout_info(self.T, D, K, n))

    def _fit(self, side):
        try:
            self.numbers.fit(side)
        except ValueError:
            self._error(self.T("research_irreducibility.number_invalid"))

    def _value(self, side):
        T = self.T
        try:
            D, K = self.numbers.layout(side)
        except ValueError:
            raise _Bad(T("research_irreducibility.layout_invalid"))
        try:
            n = self.numbers.number(side)
        except ValueError:
            raise _Bad(T("research_irreducibility.number_invalid"))
        if n >= layout.capacity(D, K):
            raise _Bad(T("research_irreducibility.arith_does_not_fit", side=side))
        return n, layout.block_rep_of(n, D, K)

    def _int(self, e, lo, hi, key):
        try:
            v = int(e.get().strip())
        except ValueError:
            v = None
        if v is None or not lo <= v <= hi:
            raise _Bad(self.T("research_irreducibility.param_out_of_range", name=key, lo=lo,
                              hi=hi))
        return v

    # --- output -------------------------------------------------------------------------

    def output_text(self):
        return self.out.text()

    def _error(self, message):
        self.last_check = None
        self.out.clear()
        self.out.write(message + "\n", "err")

    def _heading(self, text):
        self.last_check = None
        self.out.clear()
        self.out.write(text + "\n", "heading")

    def _residues(self, moduli, residues):
        pairs = [f"{s}/{m}" for m, s in zip(moduli, residues) if m > 1]
        text = "  ".join(pairs[:SHOWN_RESIDUES])
        if len(pairs) > SHOWN_RESIDUES:
            text += "  " + self.T("research_irreducibility.more_moduli",
                                  count=len(pairs) - SHOWN_RESIDUES)
        self.out.write(text + "\n")

    def _line(self, text):
        self.out.write(text + "\n")

    def _check(self, ok, value_text):
        T = self.T
        self.last_check = ok
        key = "check_ok_text" if ok else "check_bad_text"
        self.out.write(T("research_irreducibility.check_line", value=value_text) + " "
                       + T(f"research_irreducibility.{key}") + "\n", "ok" if ok else "err")

    # --- operations ---------------------------------------------------------------------

    def _run(self, body):
        try:
            body()
        except _Bad as e:
            self._error(str(e))

    def add(self, sign):
        def body():
            T, f = self.T, layout.fmt_big
            x, A = self._value("A")
            y, B = self._value("B")
            out = ops.op_add(A, B, sign)
            w = layout.lcm_all(out["moduli"])
            sym = "⊕" if sign > 0 else "⊖"
            self._heading(T("research_irreducibility.add_heading", sym=sym,
                            count=len(out["moduli"]), w=f(w)))
            self._residues(out["moduli"], out["residues"])
            kind = ("add" if sign > 0 else "sub") + ("_wrap" if out["wrap"] else "_plain")
            self._line(T(f"research_irreducibility.{kind}"))
            self._line(T("research_irreducibility.add_period", sym=sym, period=f(out["period"])))
            expected = (x + sign * y) % w
            self._check(ops.residues_match(out["moduli"], out["residues"], expected),
                        f(expected))
        self._run(body)

    def mul(self):
        def body():
            T, f = self.T, layout.fmt_big
            x, A = self._value("A")
            y, B = self._value("B")
            out = ops.op_mul(A, B)
            w = layout.lcm_all(out["moduli"])
            self._heading(T("research_irreducibility.mul_heading", w=f(w)))
            self._residues(out["moduli"], out["residues"])
            self._line(T("research_irreducibility.mul_fits" if x * y < w
                         else "research_irreducibility.mul_wraps"))
            self._line(T("research_irreducibility.mul_rhythm", mu=out["preperiod"],
                         period=f(out["period"])))
            self._check(ops.residues_match(out["moduli"], out["residues"], x * y % w),
                        f(x * y % w))
        self._run(body)

    def div(self):
        def body():
            T, f = self.T, layout.fmt_big
            x, A = self._value("A")
            b = self._int(self.b_entry, 1, 10 ** 9, "b")
            out = ops.op_div(A, b)
            w = layout.lcm_all(out["source_moduli"])
            self._heading(T("research_irreducibility.div_heading", b=b, w=f(w)))
            if out["kind"] == "exact":
                self._line(T("research_irreducibility.div_exact", b=b))
                self._residues(out["moduli"], out["residues"])
                self._check(ops.residues_match(out["moduli"], out["residues"], x // b),
                            f(x // b))
                return
            self._line(T("research_irreducibility.div_not_exact", b=b, rem=out["remainder"]))
            d = math.gcd(b, w)
            if out["kind"] == "none":
                self._line(T("research_irreducibility.div_none", b=b))
                self._check(x % d != 0, T("research_irreducibility.div_none_value", d=d))
                return
            self._line(T("research_irreducibility.div_classes", d=out["d"]) if out["d"] > 1
                       else T("research_irreducibility.div_unique"))
            self._residues(out["moduli"], out["residues"])
            wd = w // d
            sol = (x // d) * pow(b // d, -1, wd) % wd if wd > 1 else 0
            self._check(out["d"] == d and ops.residues_match(out["moduli"], out["residues"], sol),
                        f(sol))
        self._run(body)

    def address(self):
        def body():
            T, f = self.T, layout.fmt_big
            x, A = self._value("A")
            t = self._int(self.t_entry, 2, 10 ** 9, "T")
            out = ops.op_address(A, t)
            if out is None:
                w = layout.lcm_all(res.flatten(A)[0])
                raise _Bad(T("research_irreducibility.address_needs_divisor", t=t, w=f(w)))
            self._heading(T("research_irreducibility.address_heading", t=t))
            self._line(T("research_irreducibility.address_offset", i=out["i"], t=t))
            self._residues(out["moduli"], out["k"])
            i_exp = (x - 1) % t + 1 if x > 0 else t
            k_exp = (x - i_exp) // t + 1
            self._line(T("research_irreducibility.address_value", k=f(k_exp), i=i_exp))
            self._check(out["i"] == i_exp and ops.residues_match(out["moduli"], out["k"], k_exp),
                        f(k_exp))
        self._run(body)

    def power(self):
        def body():
            T, f = self.T, layout.fmt_big
            x, A = self._value("A")
            e = self._int(self.e_entry, 1, MAX_EXPONENT, "e")
            out = ops.op_pow(A, e)
            w = layout.lcm_all(out["moduli"])
            self._heading(T("research_irreducibility.pow_heading", e=e, w=f(w)))
            self._residues(out["moduli"], out["residues"])
            self._line(T("research_irreducibility.pow_rhythm", mu=out["preperiod"],
                         period=f(out["period"])))
            xe = x ** e
            self._line(T("research_irreducibility.pow_fits" if xe < w
                         else "research_irreducibility.pow_wraps", e=e, digits=len(str(xe)),
                         w_digits=layout.digit_count(w)))
            self._check(ops.residues_match(out["moduli"], out["residues"], xe % w), f(xe % w))
        self._run(body)

    def chapters(self):
        def body():
            T, f = self.T, layout.fmt_big
            _x, A = self._value("A")
            p = self._int(self.p_entry, 2, 10 ** 6, "p")
            n = self._int(self.n_entry, 1, MAX_CHAPTERS, "n")
            out = ops.chapters(A, p, n)
            v = out["v"]
            self._heading(T("research_irreducibility.chapters_heading", p=p))
            self._line(T("research_irreducibility.chapters_power", p=p, v=v))
            for row in out["rows"]:
                added = (T("research_irreducibility.chapters_base") if row["added"] is None
                         else T("research_irreducibility.chapters_added", p=p,
                                k=v + row["j"] - 1))
                self._line(T("research_irreducibility.chapters_row", j=row["j"], added=added,
                             w=f(row["w"]), digits=layout.digit_count(row["w"])))
            back = [f(r["w"]) for r in reversed(out["rows"])]
            self._line(T("research_irreducibility.chapters_fold", p=p, chain=" → ".join(back)))
            ok = all(r["w"] == out["rows"][0]["w"] * p ** (r["j"] - 1) for r in out["rows"])
            self._check(ok, T("research_irreducibility.chapters_value", p=p))
        self._run(body)

    def self_test(self):
        T = self.T
        out = ops_test(OPS_TEST_COUNT, random.Random())
        self._heading(T("research_irreducibility.ops_test_result", count=OPS_TEST_COUNT,
                        wrong=out["wrong"]))
        for s in out["kinds"]:
            self._line(T("research_irreducibility.ops_test_row",
                         name=T(f"research_irreducibility.op_{s['name']}"), tries=s["tries"],
                         wrong=s["wrong"]))
        self._line(T("research_irreducibility.ops_test_note"))
        self.last_check = out["wrong"] == 0
        self.out.write(T("research_irreducibility.check_ok_text" if self.last_check
                         else "research_irreducibility.check_bad_text") + "\n",
                       "ok" if self.last_check else "err")
        columns = [("no", T("research_irreducibility.cases_col_no"), 50, False),
                   ("kind", T("research_irreducibility.cases_col_kind"), 150, False),
                   ("task", T("research_irreducibility.cases_col_task"), 260, True),
                   ("residues", T("research_irreducibility.cases_col_residues"), 300, True),
                   ("integers", T("research_irreducibility.cases_col_integers"), 300, True),
                   ("ok", T("research_irreducibility.cases_col_ok"), 60, False)]
        rows = [((i + 1, T(f"research_irreducibility.op_{c['kind']}"), c["task"],
                  c["residues"], c["integers"]), c["ok"], c["detail"])
                for i, c in enumerate(out["cases"])]
        show_cases(self, self.palette, T("research_irreducibility.cases_title_ops"),
                   T("research_irreducibility.ops_test_result", count=OPS_TEST_COUNT,
                     wrong=out["wrong"]),
                   self.last_check, columns, rows, T("research_irreducibility.cases_detail_ops"))
