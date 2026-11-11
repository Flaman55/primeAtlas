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
PDF name a measure other than the default. Below it, "X axis" (floor or width) and a point
choice per chart (benchmark_points.py); the summary names them when not the defaults. Kept
across restarts (benchmark_view_state.py).

The choices sit on a ScrollablePage (a scrollbar once they do not fit the window's height);
Clear and Close sit under it, outside the scrolled part, so they stay in the window at any
height. The window opens at its content's size within the screen (fit_size()) and cannot be
made narrower than its content.
"""
import tkinter as tk
from tkinter import ttk

from ..core.info_tip import InfoTip
from ..core.widgets import ScrollablePage
from . import chart_filter, chart_points, sieve_measure
from .benchmark_points import CHARTS

VALUES_PER_ROW = 6
# Room left around the window for the title bar and the taskbar, in pixels.
SCREEN_MARGIN_X = 40
SCREEN_MARGIN_Y = 120
# Lowest window height (pixels) the person can drag it to: buttons plus a few lines.
MIN_HEIGHT = 220


def fit_size(content_w, content_h, screen_w, screen_h):
    """(width, height) of the window for content of that size: the content's size, capped
    to the screen less its margins (never below 1)."""
    return (max(1, min(content_w, screen_w - SCREEN_MARGIN_X)),
            max(1, min(content_h, screen_h - SCREEN_MARGIN_Y)))


class BenchmarkFilter:
    def _init_filter(self):
        self._filter_selection = {}
        self._sieve_measure = sieve_measure.DEFAULT
        self._filter_window = None
        self.filter_summary_var = tk.StringVar(value=self._filter_summary())

    def _filtered_rows(self):
        return chart_filter.apply(self._benchmark_rows, self._filter_selection)

    def _filter_summary(self):
        notes = [n for n in (sieve_measure.note(self._sieve_measure, self.T), self._points_note())
                 if n]
        return "  |  ".join([chart_filter.summary(self._filter_selection, self.T)] + notes)

    def _filter_note(self):
        parts = [chart_filter.summary(self._filter_selection, self.T)] if self._filter_selection else []
        notes = [n for n in (sieve_measure.note(self._sieve_measure, self.T), self._points_note())
                 if n]
        return "  |  ".join(parts + notes)

    def _set_points_from_window(self, x_mode, choices):
        self._set_points(x_mode, choices)
        self.filter_summary_var.set(self._filter_summary())

    def _set_filter(self, selection, measure=None):
        self._filter_selection = selection
        if measure is not None and measure != self._sieve_measure:
            self._sieve_measure = measure
            self._y_pins["sieve"] = {}
        self._save_view()
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
        buttons = ttk.Frame(self, padding=(8, 0, 8, 8))
        buttons.pack(side="bottom", fill="x")
        self.page = ScrollablePage(self, pad_text=T("common.scroll_pad"))
        body = ttk.Frame(self.page.body, padding=8)
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
        self._build_points(body)
        self.close_button = ttk.Button(buttons, text=T("bench.filter_close"),
                                       command=self.destroy)
        self.close_button.pack(side="right", padx=(6, 0), pady=(8, 0))
        self.clear_button = ttk.Button(buttons, text=T("bench.filter_clear"),
                                       command=self._clear)
        self.clear_button.pack(side="right", pady=(8, 0))
        self._show(tab._filter_selection)
        self._fit_to_screen(body, buttons)

    def _fit_to_screen(self, body, buttons):
        self.update_idletasks()
        bar = self.page.scrollbar.winfo_reqwidth() + self.page.pad.frame.winfo_reqwidth()
        content_w = body.winfo_reqwidth() + bar
        content_h = body.winfo_reqheight() + buttons.winfo_reqheight()
        width, height = fit_size(content_w, content_h, self.winfo_screenwidth(),
                                 self.winfo_screenheight())
        self.minsize(width, min(height, MIN_HEIGHT))
        x = max(0, min(self.winfo_rootx(), self.winfo_screenwidth() - width - SCREEN_MARGIN_X))
        self.geometry(f"{width}x{height}+{x}+{SCREEN_MARGIN_Y // 4}")

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

    def _build_points(self, body):
        """The x axis (floor or width) and one point choice per chart, each with its tip."""
        tab = self.tab
        T = tab.T
        row = ttk.Frame(body)
        row.pack(anchor="w", pady=(10, 0))
        ttk.Label(row, text=T("bench.x_axis_title")).pack(side="left")
        self.x_axis_info = InfoTip(row, lambda: T("bench.x_axis_tip"))
        self.x_axis_info.label.pack(side="left", padx=(4, 0))
        self.x_mode_var = tk.StringVar(value=tab._x_mode)
        modes = ttk.Frame(body)
        modes.pack(anchor="w", padx=(20, 0))
        for mode in chart_points.X_MODES:
            ttk.Radiobutton(modes, text=T("bench.x_axis_" + mode), value=mode,
                            variable=self.x_mode_var, command=self.apply_points).pack(
                side="left", padx=(0, 10))
        row = ttk.Frame(body)
        row.pack(anchor="w", pady=(10, 0))
        ttk.Label(row, text=T("bench.point_title")).pack(side="left")
        self.point_info = InfoTip(row, lambda: T("bench.point_tip"))
        self.point_info.label.pack(side="left", padx=(4, 0))
        grid = ttk.Frame(body)
        grid.pack(anchor="w", padx=(20, 0))
        self.choice_vars = {}
        for r, chart in enumerate(CHARTS):
            ttk.Label(grid, text=T("bench.chart_name_" + chart)).grid(row=r, column=0, sticky="w",
                                                                    padx=(0, 10))
            self.choice_vars[chart] = tk.StringVar(value=tab._point_choice[chart])
            for c, choice in enumerate(chart_points.CHOICES, 1):
                self.last_choice = ttk.Radiobutton(
                    grid, text=T(chart_points.CHOICE_LABEL_KEYS[choice]), value=choice,
                    variable=self.choice_vars[chart], command=self.apply_points)
                self.last_choice.grid(row=r, column=c, sticky="w", padx=(0, 10))

    def apply_points(self):
        self.tab._set_points_from_window(
            self.x_mode_var.get(), {chart: var.get() for chart, var in self.choice_vars.items()})
