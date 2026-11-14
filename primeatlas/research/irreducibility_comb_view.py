"""
irreducibility_comb_view.py -- Research -> Irreducibility -> Comb reading: where modulus a
stands on modulus b, read from two sech combs (irreducibility_comb.py). Both combs start from
a common zero; when C_a first returns to a peak (step a), the steps back to the last peak of
C_b are a mod b (Lean: combResid_eq, from scale 3).

a and b are 2..MAX_STEP. A scale below PROVED_SCALE is raised to it with a note: below it
neighbouring pulses can merge and the reading fails.
"""
import math
import tkinter as tk
from tkinter import ttk

from ..core.base_tab import BaseTab
from .irreducibility_comb import PROVED_SCALE
from .irreducibility_draw import draw_combs
from .irreducibility_widgets import entry, wrapped_label

MAX_STEP = 200
"""Largest a and b; arbitrary, keeps the plot readable."""


class CombView(BaseTab):
    def __init__(self, parent, translator, palette):
        super().__init__(parent, translator)
        T = self.T
        self._palette = palette
        self._input = None
        wrapped_label(self, text=T("research_irreducibility.comb_desc"), style="Hint.TLabel",
                      padx=6, pady=(8, 4))
        row = ttk.Frame(self)
        row.pack(fill="x", padx=6, pady=(0, 4))
        self.a_entry = entry(row, "a", "17", "research.irreducibility.comb_a", width=6,
                             on_return=self.draw)
        self.b_entry = entry(row, "b", "5", "research.irreducibility.comb_b", width=6,
                             on_return=self.draw)
        self.scale_entry = entry(row, T("research_irreducibility.scale_label"), "8",
                                 "research.irreducibility.comb_scale", width=6,
                                 on_return=self.draw)
        ttk.Button(row, text=T("research_irreducibility.draw"), command=self.draw).pack(
            side="left")
        self.message_var = tk.StringVar()
        wrapped_label(self, textvariable=self.message_var, padx=6)
        self.result_var = tk.StringVar()
        wrapped_label(self, textvariable=self.result_var, padx=6, pady=(0, 4))
        wrapped_label(self, text=T("research_irreducibility.comb_scale_note"),
                      style="Hint.TLabel", padx=6, pady=(0, 4))
        self.canvas = tk.Canvas(self, width=900, height=240, background=palette["console_bg"],
                                highlightthickness=1, highlightbackground=palette["border"])
        self.canvas.pack(fill="x", padx=6, pady=(0, 8))
        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        self.draw()

    def _read(self):
        a = int(self.a_entry.get().strip())
        b = int(self.b_entry.get().strip())
        s = float(self.scale_entry.get().strip())
        if not (2 <= a <= MAX_STEP and 2 <= b <= MAX_STEP and math.isfinite(s)):
            raise ValueError("range")
        return a, b, s

    def draw(self):
        T = self.T
        try:
            a, b, s = self._read()
        except ValueError:
            self._input = None
            self.canvas.delete("all")
            self.result_var.set("")
            self.message_var.set(T("research_irreducibility.comb_invalid", max=MAX_STEP))
            return
        note = ""
        if s < PROVED_SCALE:
            s = PROVED_SCALE
            self.scale_entry.delete(0, "end")
            self.scale_entry.insert(0, f"{s:g}")
            note = T("research_irreducibility.comb_scale_raised")
        self.message_var.set(note)
        self._input = (a, b, s)
        last = self._redraw()
        self.result_var.set(T("research_irreducibility.comb_result", a=a, b=b, last=last,
                              steps=a - last))

    def _redraw(self):
        if self._input is None:
            return None
        a, b, s = self._input
        return draw_combs(self.canvas, a, b, s, self._palette)
