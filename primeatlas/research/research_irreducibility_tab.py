"""
research_irreducibility_tab.py -- ResearchIrreducibilityTab, the Research -> Irreducibility
sub-tab: the definitions of the Irreducibility repository (Lean 4, linked from the tab)
computed on the user's own input, in five sub-tabs:

  Radices      irreducibility_radices_view.RadicesView   radices of lo..hi, interval atoms
  Comparison   irreducibility_compare_view.CompareView   A and B in block layouts, compared
  Comb reading irreducibility_comb_view.CombView         a mod b read from two sech combs
  Ranges       irreducibility_ranges_view.RangesView     W of a layout, parameter sweep, fit
  Arithmetic   irreducibility_arith_view.ArithView       operations on the residues of A, B

The numbers A and B and their layouts (irreducibility_numbers.IrreducibilityNumbers) are
shared by Comparison, Ranges and Arithmetic. Every sub-tab computes synchronously, on opening
and on its buttons; errors are shown in the sub-tab, never as a dialog.
"""
import webbrowser

from tkinter import ttk

from ..core import theme_dynamic
from ..core.base_tab import BaseTab
from ..core.theme import palette_for
from .irreducibility_arith_view import ArithView
from .irreducibility_comb_view import CombView
from .irreducibility_compare_view import CompareView
from .irreducibility_numbers import IrreducibilityNumbers
from .irreducibility_radices_view import RadicesView
from .irreducibility_ranges_view import RangesView
from .irreducibility_widgets import wrapped_label

REPO_URL = "https://github.com/Flaman55/Irreducibility"
PAPER_URL = REPO_URL + "/blob/main/Latex/irreducibility.pdf"


class ResearchIrreducibilityTab(BaseTab):
    def __init__(self, parent, translator):
        super().__init__(parent, translator)
        T = self.T
        palette = palette_for(theme_dynamic.THEME)
        head = ttk.Frame(self)
        head.pack(fill="x", padx=6, pady=(10, 4))
        wrapped_label(head, text=T("research_irreducibility.intro"))
        buttons = ttk.Frame(head)
        buttons.pack(anchor="w", pady=(4, 0))
        self.repo_button = ttk.Button(buttons, text=T("research_irreducibility.open_repo"),
                                      command=lambda: webbrowser.open(REPO_URL))
        self.repo_button.pack(side="left")
        self.paper_button = ttk.Button(buttons, text=T("research_irreducibility.open_paper"),
                                       command=lambda: webbrowser.open(PAPER_URL))
        self.paper_button.pack(side="left", padx=(8, 0))

        self.numbers = IrreducibilityNumbers(self)
        sub = ttk.Notebook(self)
        sub.pack(fill="both", expand=True, padx=6, pady=(6, 6))
        self.sub_notebook = sub
        self.radices_view = RadicesView(sub, translator, palette)
        self.compare_view = CompareView(sub, translator, palette, self.numbers)
        self.comb_view = CombView(sub, translator, palette)
        self.ranges_view = RangesView(sub, translator, palette, self.numbers, self._show_compare)
        self.arith_view = ArithView(sub, translator, palette, self.numbers)
        for view, key in ((self.radices_view, "radices"), (self.compare_view, "compare"),
                          (self.comb_view, "comb"), (self.ranges_view, "ranges"),
                          (self.arith_view, "arith")):
            sub.add(view, text=T(f"research_irreducibility.tab_{key}"))

    def _show_compare(self):
        self.sub_notebook.select(self.compare_view)
        self.compare_view.run_compare()
