"""BenchmarkFilter mixin of BenchmarkTab: the Filter window and the runs the charts compare.

The window has one checkbox per dimension (engine build, sieve threads, write threads, range
width); checking one shows that dimension's values from the log, each with its own checkbox,
all selected at first. Every change applies at once: the charts, the mixed-width note and the
PDF export use chart_filter.apply() of the log, and the summary next to the Filter button (and
the PDF subtitle) names the selection. Below the dimensions, "Sieve measure" picks the time
the sieve chart measures (sieve_measure.py): a change redraws it and clears its y-axis pins,
whose units may differ; the summary and the PDF name a measure other than the default. The
tab's table keeps the whole log. Kept for the session, like the chart toggles.
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
        selection = tab._filter_selection
        self.enabled, self.values, self._value_frames = {}, {}, {}
        body = ttk.Frame(self, padding=8)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=T("bench.filter_hint"), style="Hint.TLabel",
                  wraplength=560, justify="left").pack(anchor="w", pady=(0, 6))
        for dim in chart_filter.DIMENSIONS:
            self.enabled[dim] = tk.BooleanVar(value=dim in selection)
            ttk.Checkbutton(body, text=T(chart_filter.DIMENSION_KEYS[dim]),
                            variable=self.enabled[dim],
                            command=self._on_dimension).pack(anchor="w", pady=(4, 0))
            frame = ttk.Frame(body)
            frame.pack(anchor="w", padx=(20, 0))
            self._value_frames[dim] = frame
            self.values[dim] = {}
            for i, value in enumerate(chart_filter.dimension_values(tab._benchmark_rows, dim)):
                var = tk.BooleanVar(value=dim not in selection or value in selection[dim])
                self.values[dim][value] = var
                ttk.Checkbutton(frame, text=value or T("bench.filter_blank"), variable=var,
                                command=self.apply).grid(
                    row=i // VALUES_PER_ROW, column=i % VALUES_PER_ROW, sticky="w", padx=(0, 10))
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
        self._sync_states()

    def _sync_states(self):
        for dim, frame in self._value_frames.items():
            state = "normal" if self.enabled[dim].get() else "disabled"
            for child in frame.winfo_children():
                child.configure(state=state)

    def _on_dimension(self):
        self._sync_states()
        self.apply()

    def _clear(self):
        for var in self.enabled.values():
            var.set(False)
        for values in self.values.values():
            for var in values.values():
                var.set(True)
        self._on_dimension()

    def apply(self):
        self.tab._set_filter({dim: {v for v, var in self.values[dim].items() if var.get()}
                              for dim in chart_filter.DIMENSIONS if self.enabled[dim].get()},
                             self.measure_var.get())
