"""EngineAdviceView: the engine proposal's widgets, one per place that shows it (Time simulation
window, each Quick-gen panel copy).

A ttk.Frame with the proposal line and its Use button (on_use(engine) applies the proposed
engine; the button is disabled while that engine is already selected or there is no
proposal), the BPSW warning and the guest line; an empty warning or guest line is hidden.
The texts come from engine_advice_text.advice_text().
"""
import tkinter as tk
from tkinter import ttk


class EngineAdviceView(ttk.Frame):
    def __init__(self, parent, T, on_use, wraplength=560):
        super().__init__(parent)
        self._on_use = on_use
        self._engine = None
        self.proposal_var = tk.StringVar()
        self.warning_var = tk.StringVar()
        self.guest_var = tk.StringVar()
        top = ttk.Frame(self)
        top.pack(fill="x", anchor="w")
        ttk.Label(top, text=T("advisor.label")).pack(side="left", anchor="n")
        ttk.Label(top, textvariable=self.proposal_var, wraplength=wraplength,
                  justify="left").pack(side="left", padx=(6, 0))
        self.use_button = ttk.Button(top, text=T("advisor.use_button"), width=6,
                                     command=self._use)
        self.use_button.pack(side="left", padx=(8, 0), anchor="n")
        self.warning_label = ttk.Label(self, textvariable=self.warning_var,
                                       wraplength=wraplength, justify="left")
        self.guest_label = ttk.Label(self, textvariable=self.guest_var, style="Hint.TLabel",
                                     wraplength=wraplength, justify="left")

    def show(self, text, engine, selected_engine):
        """Fills the view from an AdviceText; `engine` is the proposed engine (None: no
        proposal), `selected_engine` the one the form holds."""
        self._engine = engine
        self.proposal_var.set(text.proposal)
        self.use_button.configure(
            state="normal" if engine is not None and engine != selected_engine else "disabled")
        # Repacked in order every time, so the warning always stays above the guest line.
        for var, label, value in ((self.warning_var, self.warning_label, text.warning),
                                  (self.guest_var, self.guest_label, text.guest)):
            var.set(value)
            label.pack_forget()
            if value:
                label.pack(fill="x", anchor="w", pady=(2, 0))

    def _use(self):
        if self._engine is not None:
            self._on_use(self._engine)
