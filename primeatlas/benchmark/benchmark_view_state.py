"""BenchmarkViewState mixin of BenchmarkTab: the view kept across restarts and the one-click
axis toggles of a chart's right-click menu.

The filter, the sieve measure, the x axis, the point choices and the hidden lines are loaded
from the remembered-fields store when the tab is built and saved at every change of them
(view_store.py); a filter value the log no longer holds is dropped at reload. A chart's menu
offers "Hide/Show left-axis lines (circles)" and "... right-axis lines (squares)": the chart's
own memory of that axis, one key (chart_series.axis_key); hiding covers a line that appears on
the axis later too (a new run, a wider filter). The runs' own memories (legend name and
markers) stay as they are, so showing the axis brings back what each run had on it. Disabled
while the axis has no line.
"""
from primeatlas.core import ui_state_dynamic
from . import view_store
from .chart_series import axis_key, toggle_keys

AXES = ("primary", "secondary")


class BenchmarkViewState:
    def _load_view(self):
        view = view_store.load(ui_state_dynamic.STORE)
        self._filter_selection = view["selection"]
        self._sieve_measure = view["measure"]
        self._x_mode = view["x_mode"]
        self._point_choice = view["choices"]
        self._hidden_lines = view["hidden"]
        self.filter_summary_var.set(self._filter_summary())

    def _save_view(self):
        view_store.save(ui_state_dynamic.STORE, self._filter_selection, self._sieve_measure,
                        self._x_mode, self._point_choice, self._choices_before_select,
                        self._hidden_lines)

    def _prune_filter(self):
        self._filter_selection = view_store.prune(self._filter_selection, self._benchmark_rows)
        self.filter_summary_var.set(self._filter_summary())

    def _axis_line_keys(self, chart, axis):
        canvas = {"run": self.benchmark_chart, "sieve": self.benchmark_chart2,
                  "ram": self.benchmark_chart3}[chart]
        prefix = f"legend:{axis}:"
        return {(axis, series.name)
                for tag, series in getattr(canvas, "legend_series", {}).items()
                if tag.startswith(prefix)}

    def _axis_menu_entries(self, chart):
        """[(label, command, enabled)]: hide or show each axis of `chart`."""
        entries = []
        for axis in AXES:
            action = "show" if axis_key(axis) in self._hidden_lines[chart] else "hide"
            entries.append((self.T(f"bench.axis_lines_{action}_{axis}"),
                            lambda a=axis: self._toggle_axis(chart, a),
                            bool(self._axis_line_keys(chart, axis))))
        return entries

    def _toggle_axis(self, chart, axis):
        self._hidden_lines[chart] = toggle_keys(self._hidden_lines[chart], [axis_key(axis)])
        self._save_view()
        self._redraw_chart(chart)
