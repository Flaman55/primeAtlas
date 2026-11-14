"""
irreducibility_radices_view.py -- Research -> Irreducibility -> Radices: the radix each
modulus of a range lo..hi receives after the moduli before it (irreducibility_core.radices),
drawn as chips (modulus over radix, radix > 1 marked), and the atoms of the interval
(irreducibility_residues.interval_atoms) split into those below lo and those inside, each with
the pair a, a + k it is read from.

The range is clamped as entered: lo to 1..MAX_MODULUS, hi to lo..MAX_MODULUS and to at most
MAX_RANGE moduli; the clamped values are written back into the fields.
"""
import tkinter as tk
from tkinter import ttk

from ..core.base_tab import BaseTab
from . import irreducibility_core as core
from . import irreducibility_residues as res
from .irreducibility_draw import draw_chips
from .irreducibility_widgets import entry, wrapped_label

MAX_MODULUS = 50000
"""Largest accepted end of the range; arbitrary."""

MAX_RANGE = 1000
"""Most moduli drawn at once; arbitrary, keeps the chip grid readable."""


class RadicesView(BaseTab):
    def __init__(self, parent, translator, palette):
        super().__init__(parent, translator)
        T = self.T
        self._palette = palette
        self.chips = []
        self.atoms_below = []
        self.atoms_inside = []
        wrapped_label(self, text=T("research_irreducibility.radices_desc"), style="Hint.TLabel",
                      padx=6, pady=(8, 4))
        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=(0, 4))
        self.from_entry = entry(row, T("research_irreducibility.from_label"), "2",
                                "research.irreducibility.range_from", on_return=self.run)
        self.to_entry = entry(row, T("research_irreducibility.to_label"), "60",
                              "research.irreducibility.range_to", on_return=self.run)
        ttk.Button(row, text=T("research_irreducibility.build"), command=self.run).pack(
            side="left")
        self.summary_var = tk.StringVar()
        ttk.Label(row, textvariable=self.summary_var).pack(side="left", padx=(12, 0))
        self.message_var = tk.StringVar()
        wrapped_label(self, textvariable=self.message_var, padx=6)

        self.canvas = tk.Canvas(self, width=900, height=40, background=palette["console_bg"],
                                highlightthickness=0)
        self.canvas.pack(fill="x", padx=6, pady=(0, 6))

        ttk.Label(self, text=T("research_irreducibility.atoms_title"),
                  font=("TkDefaultFont", 10, "bold")).pack(anchor="w", padx=6, pady=(10, 2))
        wrapped_label(self, text=T("research_irreducibility.atoms_desc"), style="Hint.TLabel",
                      padx=6, pady=(0, 4))
        self.atoms_var = tk.StringVar()
        ttk.Label(self, textvariable=self.atoms_var).pack(anchor="w", padx=6)
        self.below_canvas = tk.Canvas(self, width=900, height=8,
                                      background=palette["console_bg"], highlightthickness=0)
        self.below_canvas.pack(fill="x", padx=6, pady=(2, 4))
        self.inside_var = tk.StringVar()
        wrapped_label(self, textvariable=self.inside_var, style="Hint.TLabel", padx=6)
        self.inside_canvas = tk.Canvas(self, width=900, height=8,
                                       background=palette["console_bg"], highlightthickness=0)
        self.inside_canvas.pack(fill="x", padx=6, pady=(2, 8))
        for c in (self.canvas, self.below_canvas, self.inside_canvas):
            c.bind("<Configure>", lambda _e: self._redraw())
        self.run()

    def _read_range(self):
        lo = int(self.from_entry.get().strip())
        hi = int(self.to_entry.get().strip())
        if lo < 1:
            raise ValueError("from")
        lo = min(lo, MAX_MODULUS)
        hi = min(MAX_MODULUS, max(lo, hi))
        cut = hi - lo + 1 > MAX_RANGE
        if cut:
            hi = lo + MAX_RANGE - 1
        return lo, hi, cut

    def run(self):
        T = self.T
        try:
            lo, hi, cut = self._read_range()
        except ValueError:
            self.chips, self.atoms_below, self.atoms_inside = [], [], []
            self.summary_var.set("")
            self.atoms_var.set("")
            self.inside_var.set("")
            self.message_var.set(T("research_irreducibility.range_invalid", max=MAX_MODULUS))
            self._redraw()
            return
        self.message_var.set("")
        for e, v in ((self.from_entry, lo), (self.to_entry, hi)):
            if e.get().strip() != str(v):
                e.delete(0, "end")
                e.insert(0, str(v))
        moduli = list(range(lo, hi + 1))
        self.chips = list(zip(moduli, core.radices(moduli)))
        marked = sum(r > 1 for _, r in self.chips)
        summary = T("research_irreducibility.range_summary", lo=lo, hi=hi, marked=marked,
                    count=len(moduli))
        if cut:
            summary += " " + T("research_irreducibility.limit_note", max=MAX_RANGE)
        self.summary_var.set(summary)

        rows = [(k, res.first_multiple_from(lo, k), res.first_multiple_from(lo, k) + k)
                for k in res.interval_atoms(lo, hi)]
        self.atoms_below = [r for r in rows if r[0] < lo]
        self.atoms_inside = [r for r in rows if r[0] >= lo]
        self.atoms_var.set(T("research_irreducibility.atoms_summary", lo=lo,
                             below=len(self.atoms_below), inside=len(self.atoms_inside))
                           + ("" if self.atoms_below else
                              " " + T("research_irreducibility.atoms_none_below")))
        self.inside_var.set(T("research_irreducibility.atoms_inside", lo=lo)
                            if self.atoms_inside else "")
        self._redraw()

    def _redraw(self):
        p = self._palette
        draw_chips(self.canvas, [(m, r, r > 1) for m, r in self.chips], p)
        draw_chips(self.below_canvas, [(k, f"{b}−{a}", True) for k, a, b in self.atoms_below],
                   p, tag="atom")
        draw_chips(self.inside_canvas, [(k, f"{b}−{a}", True) for k, a, b in self.atoms_inside],
                   p, tag="atom")
