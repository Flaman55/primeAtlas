"""
irreducibility_compare_view.py -- Research -> Irreducibility -> Comparison: two numbers A and
B, each in its own block layout (blocks D and quotient blocks K), compared from their residues
only (irreducibility_residues.compare_blocks). The numbers are turned into residues on input
(irreducibility_layout.block_rep_of) and the verdict is checked against the integers.

Each side shows its layout's ranges and, after a comparison, one dial per block modulus. The
result lists the common moduli from the most significant, with the radix and both digits; the
first differing digit decides. Random neighbours picks A below the smaller capacity and B = A
or A + 1; Test 1000 pairs runs irreducibility_selftest.compare_test.
"""
import random
import tkinter as tk
from tkinter import ttk

from ..core.base_tab import BaseTab
from ..core.widgets import StripedTreeview
from . import irreducibility_layout as layout
from . import irreducibility_residues as res
from .irreducibility_draw import COLOR_A, COLOR_B, COLOR_QUOT, GOLD_BG, MAX_DIALS, draw_dials
from .irreducibility_cases_window import show_cases
from .irreducibility_numbers import layout_info
from .irreducibility_selftest import compare_test
from .irreducibility_widgets import entry, wrapped_label

MASS_TEST_PAIRS = 1000

_SIDE_COLORS = {"A": COLOR_A, "B": COLOR_B}


class _Side:
    """The widgets of one number: its entry, layout entries, Fit button, info and dials."""

    def __init__(self, view, parent, side):
        T, nums = view.T, view.numbers
        box = ttk.LabelFrame(parent, text=T("research_irreducibility.number_title", side=side))
        self.frame = box
        row = ttk.Frame(box)
        row.pack(fill="x", padx=6, pady=(4, 2))
        self.number_entry = entry(row, "", "", width=34, textvariable=nums.number_var(side),
                                  on_return=view.run_compare)
        self.layout_entries = {}
        for prefix, title in (("d", "blocks_row"), ("k", "quot_row")):
            r = ttk.Frame(box)
            r.pack(fill="x", padx=6, pady=1)
            ttk.Label(r, text=T(f"research_irreducibility.{title}")).pack(side="left",
                                                                         padx=(0, 6))
            for suffix, lab in (("s", "start_label"), ("z", "size_label"), ("c", "count_label")):
                key = prefix + suffix
                self.layout_entries[key] = entry(
                    r, T(f"research_irreducibility.{lab}"), "", width=5,
                    textvariable=nums.layout_var(side, key), on_return=view.run_compare)
        r = ttk.Frame(box)
        r.pack(fill="x", padx=6, pady=(2, 2))
        self.fit_button = ttk.Button(r, text=T("research_irreducibility.fit"),
                                     command=lambda: view.fit(side))
        self.fit_button.pack(side="left")
        self.info_var = tk.StringVar()
        wrapped_label(box, textvariable=self.info_var, style="Hint.TLabel", padx=6, pady=(2, 2))
        self.dials = tk.Canvas(box, width=420, height=8, background=view.palette["console_bg"],
                               highlightthickness=0)
        self.dials.pack(fill="x", padx=6, pady=(0, 6))


class CompareView(BaseTab):
    def __init__(self, parent, translator, palette, numbers):
        super().__init__(parent, translator)
        T = self.T
        self.palette = palette
        self.cases_window = None
        self.numbers = numbers
        self.oracle_ok = None
        self._dials = {"A": [], "B": []}
        wrapped_label(self, text=T("research_irreducibility.compare_desc"), style="Hint.TLabel",
                      padx=6, pady=(8, 4))
        cards = ttk.Frame(self)
        cards.pack(fill="x", padx=6)
        cards.columnconfigure(0, weight=1, uniform="side")
        cards.columnconfigure(1, weight=1, uniform="side")
        self.sides = {}
        for col, side in enumerate(("A", "B")):
            s = _Side(self, cards, side)
            s.frame.grid(row=0, column=col, sticky="nsew", padx=(0, 6) if col == 0 else (6, 0))
            s.dials.bind("<Configure>", lambda _e, sd=side: self._redraw_dials(sd))
            self.sides[side] = s

        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=(8, 4))
        ttk.Button(row, text=T("research_irreducibility.compare"),
                   command=self.run_compare).pack(side="left")
        self.random_button = ttk.Button(row, text=T("research_irreducibility.random_pair"),
                                        command=self.random_pair)
        self.random_button.pack(side="left", padx=(8, 0))
        self.test_button = ttk.Button(
            row, text=T("research_irreducibility.test_pairs", count=MASS_TEST_PAIRS),
            command=self.mass_test)
        self.test_button.pack(side="left", padx=(8, 0))

        self.message_var = tk.StringVar()
        wrapped_label(self, textvariable=self.message_var, padx=6)
        self.verdict_var = tk.StringVar()
        ttk.Label(self, textvariable=self.verdict_var,
                  font=("TkDefaultFont", 16, "bold")).pack(anchor="w", padx=6)
        self.oracle_var = tk.StringVar()
        self.oracle_label = tk.Label(self, textvariable=self.oracle_var, anchor="w",
                                     background=palette["bg"])
        self.oracle_label.pack(anchor="w", padx=6)
        self.note_var = tk.StringVar()
        wrapped_label(self, textvariable=self.note_var, style="Hint.TLabel", padx=6, pady=(2, 4))

        frame = ttk.Frame(self)
        frame.pack(fill="x", padx=6, pady=(0, 8))
        cols = ("modulus", "radix", "digit_a", "digit_b")
        self.digits_tree = StripedTreeview(frame, columns=cols, show="headings", height=12)
        for c in cols:
            self.digits_tree.heading(c, text=T(f"research_irreducibility.col_{c}"))
            self.digits_tree.column(c, width=120, anchor="e")
        self.digits_tree.tag_configure("decides", background=GOLD_BG, foreground="#1d1d1f")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.digits_tree.yview)
        self.digits_tree.configure(yscrollcommand=scroll.set)
        self.digits_tree.pack(side="left", fill="x", expand=True)
        scroll.pack(side="left", fill="y")

        numbers.on_change(self.refresh_info)
        for side in ("A", "B"):
            self.refresh_info(side)
        self.run_compare()

    def refresh_info(self, side):
        try:
            D, K = self.numbers.layout(side)
        except ValueError:
            self.sides[side].info_var.set(self.T("research_irreducibility.layout_invalid"))
            return
        try:
            n = self.numbers.number(side)
        except ValueError:
            n = None
        self.sides[side].info_var.set(layout_info(self.T, D, K, n))

    def fit(self, side):
        try:
            self.numbers.fit(side)
        except ValueError:
            self.message_var.set(self.T("research_irreducibility.number_invalid"))
            return
        self.message_var.set("")

    def _clear(self, message):
        self.message_var.set(message)
        self.verdict_var.set("")
        self.oracle_var.set("")
        self.note_var.set("")
        self.oracle_ok = None
        self.digits_tree.delete(*self.digits_tree.get_children())
        self._dials = {"A": [], "B": []}
        for side in ("A", "B"):
            self._redraw_dials(side)

    def _read(self):
        """(values, layouts, smaller capacity) or a translated error message."""
        T = self.T
        try:
            layouts = {s: self.numbers.layout(s) for s in ("A", "B")}
        except ValueError:
            return T("research_irreducibility.layout_invalid")
        try:
            values = {s: self.numbers.number(s) for s in ("A", "B")}
        except ValueError:
            return T("research_irreducibility.number_invalid")
        cap = min(layout.capacity(*layouts[s]) for s in ("A", "B"))
        if any(v >= cap for v in values.values()):
            return T("research_irreducibility.compare_too_large", cap=layout.fmt_big(cap))
        return values, layouts, cap

    def run_compare(self):
        T = self.T
        got = self._read()
        if isinstance(got, str):
            self._clear(got)
            return
        values, layouts, _cap = got
        reps = {s: layout.block_rep_of(values[s], *layouts[s]) for s in ("A", "B")}
        v = res.compare_blocks(reps["A"], reps["B"])
        self.message_var.set("")
        self.verdict_var.set({-1: "A < B", 0: "A = B", 1: "A > B"}[v["verdict"]])
        truth = (values["A"] > values["B"]) - (values["A"] < values["B"])
        self._set_oracle(truth == v["verdict"])
        self.note_var.set(T("research_irreducibility.compare_note"))
        tree = self.digits_tree
        tree.delete(*tree.get_children())
        for i in range(len(v["moduli"]) - 1, -1, -1):
            tree.insert("", "end", values=(v["moduli"][i], v["radices"][i], v["digits_x"][i],
                                           v["digits_y"][i]),
                        tags=("decides",) if i == v["at"] else ())
        for side in ("A", "B"):
            rep = reps[side]
            dm, dr = res.block_moduli(rep["blocks"], rep["residues"])
            km, kr = res.block_moduli(rep["quot_blocks"], rep["quot_residues"])
            self._dials[side] = (
                [(m, s, _SIDE_COLORS[side], f"D{i + 1}") for i, (m, s) in enumerate(zip(dm, dr))]
                + [(m, s, COLOR_QUOT, f"K{i + 1}") for i, (m, s) in enumerate(zip(km, kr))])
            self._redraw_dials(side)

    def _set_oracle(self, ok):
        T = self.T
        self.oracle_ok = ok
        self.oracle_var.set(T("research_irreducibility.oracle_agrees" if ok
                              else "research_irreducibility.oracle_disagrees"))
        self.oracle_label.configure(foreground="#2ca02c" if ok else "#c0392b")

    def _redraw_dials(self, side):
        dials = self._dials[side]
        more = ""
        if len(dials) > MAX_DIALS:
            more = self.T("research_irreducibility.more_dials", count=len(dials) - MAX_DIALS)
        draw_dials(self.sides[side].dials, dials[:MAX_DIALS], self.palette, more)

    def random_pair(self):
        got = self._read_caps()
        if got is None:
            return
        x = random.randrange(max(got - 1, 1))
        self.numbers.number_var("A").set(str(x))
        self.numbers.number_var("B").set(str(x + random.choice((0, 1))))
        self.run_compare()

    def _read_caps(self):
        try:
            return min(layout.capacity(*self.numbers.layout(s)) for s in ("A", "B"))
        except ValueError:
            self._clear(self.T("research_irreducibility.layout_invalid"))
            return None

    def mass_test(self):
        out = compare_test(MASS_TEST_PAIRS, random.Random())
        self._clear("")
        self.verdict_var.set(self.T("research_irreducibility.compare_test_result",
                                    count=out["count"], wrong=out["wrong"]))
        self._set_oracle(out["wrong"] == 0)
        self.oracle_var.set(self.T("research_irreducibility.compare_test_note"))
        T = self.T
        columns = [("no", T("research_irreducibility.cases_col_no"), 50, False),
                   ("a", T("research_irreducibility.cases_col_a"), 300, True),
                   ("b", T("research_irreducibility.cases_col_b"), 300, True),
                   ("residues", T("research_irreducibility.cases_col_residues"), 170, False),
                   ("integers", T("research_irreducibility.cases_col_integers"), 120, False),
                   ("ok", T("research_irreducibility.cases_col_ok"), 60, False)]
        rows = [((i + 1, c["a"], c["b"], c["residues"], c["integers"]), c["ok"], c["detail"])
                for i, c in enumerate(out["cases"])]
        show_cases(self, self.palette, T("research_irreducibility.cases_title_compare"),
                   T("research_irreducibility.compare_test_result", count=out["count"],
                     wrong=out["wrong"]),
                   out["wrong"] == 0, columns, rows,
                   T("research_irreducibility.cases_detail_compare"))
