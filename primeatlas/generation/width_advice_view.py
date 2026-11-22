"""WidthAdviceView: the width proposal's line under the engine proposal of each Quick-gen panel
copy, with its Use button (on_use(advice) writes the proposed width, and in Explore the
iteration count, into the fields). The text comes from width_advice_text.width_text().
"""
import tkinter as tk
from tkinter import ttk
from ..core.wrap_label import WrapLabel


class WidthAdviceView(ttk.Frame):
    def __init__(self, parent, T, on_use):
        super().__init__(parent)
        self._on_use = on_use
        self._advice = None
        self.text_var = tk.StringVar()
        ttk.Label(self, text=T("width_advice.label")).pack(side="left", anchor="n")
        WrapLabel(self, textvariable=self.text_var).pack(side="left", padx=(6, 0))
        self.use_button = ttk.Button(self, text=T("advisor.use_button"), width=6,
                                     command=self._use)
        self.use_button.pack(side="left", padx=(8, 0), anchor="n")

    def show(self, text, advice):
        self._advice = advice
        self.text_var.set(text)

    def _use(self):
        if self._advice is not None:
            self._on_use(self._advice)
