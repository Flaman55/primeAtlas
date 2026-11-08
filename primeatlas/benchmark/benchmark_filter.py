"""BenchmarkFilter mixin of BenchmarkTab: the Filter window and the runs the charts compare.

The window lists every dimension (run purpose, engine build, sieve threads, write threads,
range width) with an All checkbox and one checkbox per value the log holds, all clickable at
once. A dimension is at All until a value is clicked: that value alone is then kept, further
clicks add or remove values, and removing the last one or clicking All goes back to All
(chart_filter.toggle_value()/select_all()). Every change applies at once: the charts, the
mixed-width note, the PDF export and the tab's table use chart_filter.apply() of the log,
and the summary next to the Filter button (and the PDF subtitle) names the selection. Below
the dimensions, "Sieve measure" picks the time the sieve chart measures (sieve_measure.py):
a change redraws it and clears its y-axis pins, whose units may differ; the summary and the
PDF name a measure other than the default. Kept for the session, like the chart toggles.
"""
import tkinter as tk
from tkinter import ttk

from ..core.info_tip import InfoTip
from . import chart_filter, sieve_measure

VALUES_PER_ROW = 6


class BenchmarkFilter:
    def _init_filter(self):
        self._filter_selection = {}
        self._sieve_measure = sieve_measure.DEFAULT
        self._filter_window = None
        self.filter_summary_var = tk.StringVar(value=self._filter_summary())

    def _filtered_rows(self):
        return chart_filter.apply(self._benchmark_rows, self._filter_selection)

    def _filter_summary(self):
        note = sieve_measure.note(self._sieve_measure, self.T)
        return chart_filter.summary(self._filter_selection, self.T) + ("  |  " + note if note else "")

    def _filter_note(self):
        parts = [chart_filter.summary(self._filter_selection, self.T)] if self._filter_selection else []
        note = sieve_measure.note(self._sieve_measure, self.T)
        return "  |  ".join(parts + ([note] if note else []))

    def _set_filter(self, selection, measure=None):
        self._filter_selection = selection
        if measure is not None and measure != self._sieve_measure:
            self._sieve_measure = measure
            self._y_pins["sieve"] = {}
        self.filter_summary_var.set(self._filter_summary())
        self._redraw_charts()
        self._rebuild_benchmark_tree()

    def _open_filter_window(self):
        if self._filter_window is not None and self._filter_window.winfo_exists():
            self._filter_window.lift()
        else:
            self._filter_window = FilterWindow(self)
        return self._filter_window


class FilterWindow(tk.Toplevel):
    def __init__(self, tab):
        super().__init__(tab)
        self.tab, T = tab, tab.T
        self.title(T("bench.filter_title"))
        self.transient(tab.winfo_toplevel())
        self.all_vars, self.all_buttons = {}, {}
        self.value_vars, self.value_buttons = {}, {}
        body = ttk.Frame(self, padding=8)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=T("bench.filter_hint"), style="Hint.TLabel",
                  wraplength=560, justify="left").pack(anchor="w", pady=(0, 6))
        for dim in chart_filter.DIMENSIONS:
            ttk.Label(body, text=T(chart_filter.DIMENSION_KEYS[dim])).pack(anchor="w", pady=(4, 0))
            frame = ttk.Frame(body)
            frame.pack(anchor="w", padx=(20, 0))
            self.all_vars[dim] = tk.BooleanVar()
            self.all_buttons[dim] = ttk.Checkbutton(
                frame, text=T("bench.filter_all"), variable=self.all_vars[dim],
                command=lambda d=dim: self._set(
                    chart_filter.select_all(self.tab._filter_selection, d)))
            self.all_buttons[dim].grid(row=0, column=0, sticky="w", padx=(0, 10))
            self.value_vars[dim], self.value_buttons[dim] = {}, {}
            for i, value in enumerate(chart_filter.dimension_values(tab._benchmark_rows, dim), 1):
                var = tk.BooleanVar()
                button = ttk.Checkbutton(
                    frame, text=chart_filter.value_label(dim, value, T), variable=var,
                    command=lambda d=dim, v=value: self._set(
                        chart_filter.toggle_value(self.tab._filter_selection, d, v)))
                button.grid(row=i // VALUES_PER_ROW, column=i % VALUES_PER_ROW, sticky="w",
                            padx=(0, 10))
                self.value_vars[dim][value], self.value_buttons[dim][value] = var, button
        measure_row = ttk.Frame(body)
        measure_row.pack(anchor="w", pady=(10, 0))
        ttk.Label(measure_row, text=T("bench.measure_title")).pack(side="left")
        self.measure_info = InfoTip(measure_row, lambda: T(sieve_measure.TIP_KEY))
        self.measure_info.label.pack(side="left", padx=(4, 0))
        self.measure_var = tk.StringVar(value=tab._sieve_measure)
        measures = ttk.Frame(body)
        measures.pack(anchor="w", padx=(20, 0))
        for measure in sieve_measure.MEASURES:
            ttk.Radiobutton(measures, text=T(sieve_measure.LABEL_KEYS[measure]), value=measure,
                            variable=self.measure_var, command=self.apply).pack(
                side="left", padx=(0, 10))
        buttons = ttk.Frame(body)
        buttons.pack(anchor="e", pady=(8, 0))
        ttk.Button(buttons, text=T("bench.filter_clear"), command=self._clear).pack(side="left")
        ttk.Button(buttons, text=T("bench.filter_close"), command=self.destroy).pack(
            side="left", padx=(6, 0))
        self._show(tab._filter_selection)

    def _show(self, selection):
        """Every checkbox shows `selection`: All for a dimension it leaves out, else the
        values it holds."""
        for dim in chart_filter.DIMENSIONS:
            self.all_vars[dim].set(dim not in selection)
            for value, var in self.value_vars[dim].items():
                var.set(dim in selection and value in selection[dim])

    def _set(self, selection):
        self._show(selection)
        self.tab._set_filter(selection, self.measure_var.get())

    def _clear(self):
        self._set({})

    def apply(self):
        self.tab._set_filter(self.tab._filter_selection, self.measure_var.get())
