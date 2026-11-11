"""BenchmarkPoints mixin of BenchmarkTab: the x axis, each chart's point choice and the run
selected in the table (chart_points.py).

The Filter window sets the x axis (floor or width) for all three charts and a point choice per
chart (last, min, max, selected); a change of the x axis shows the whole charts, since the zoom
of one axis means nothing on the other. Selecting a run in the table makes it the selected run
of all three charts: a chart on SELECTED shows it in its own group. In the table up/down move
between runs (the Treeview's own keys) and left/right turn the floor's page, selecting the
page's first run, so the arrows walk the selected point through every run. Selecting a run
switches every chart to SELECTED (a chart on ALL keeps it: the run is among its points), so a
click shows at once, and remembers each chart's choice from before the first selection. A
right-click in the table clears the selection and puts every chart still on SELECTED back on
its remembered choice. A chart's right-click menu (_point_menu_entries()) and the Filter
window set any choice. The points from the selected run are ringed (_chart_marks()). The x
axis and the choices are kept across restarts (benchmark_view_state.py), the selected run is
not.
"""
from . import chart_points
from .benchmark import line_value, selected_marks

# The chart each metric is drawn on ("run", "sieve", "ram"); the sieve measures are the rest.
_METRIC_CHART = {"growth": "run", "write": "run", "ram": "ram", "ram_per_window": "ram"}
CHARTS = ("run", "sieve", "ram")


class BenchmarkPoints:
    def _init_points(self):
        self._x_mode = chart_points.X_FLOOR
        self._point_choice = {chart: chart_points.LAST for chart in CHARTS}
        self._selected_run = None
        self._choices_before_select = {}
        self._tree_item_rows = {}

    def _point_view(self, chart):
        return chart_points.PointView(self._x_mode, self._point_choice[chart],
                                      self._selected_run)

    def _point_views(self):
        """{chart: PointView}, what the exports draw (report_export, render_benchmark_pdf)."""
        return {chart: self._point_view(chart) for chart in CHARTS}

    def _metric_view(self, metric):
        return self._point_view(_METRIC_CHART.get(metric, "sieve"))

    def _chart_marks(self, metric1, metric2):
        """{(axis, line, x, value)} of the selected run's points on a chart's two axes."""
        rows = self._filtered_rows()
        return {(axis, *mark) for axis, metric in (("primary", metric1), ("secondary", metric2))
                for mark in selected_marks(rows, metric, self._metric_view(metric))}

    def _set_points(self, x_mode, choices):
        """New x axis and point choices; a changed x axis resets the zoom (whole charts)."""
        chart_points.check(chart_points.PointView(x_mode))
        for choice in choices.values():
            chart_points.check(chart_points.PointView(choice=choice))
        changed = x_mode != self._x_mode
        self._x_mode = x_mode
        self._point_choice = dict(self._point_choice, **choices)
        self._save_view()
        if changed:
            self._reset_chart_view()
        else:
            self._redraw_charts()

    def _points_note(self):
        """The x axis and the point choices when not the defaults, for the filter summary."""
        T = self.T
        parts = []
        if self._x_mode != chart_points.X_FLOOR:
            parts.append(T("bench.x_axis_title") + ": " + T("bench.x_axis_" + self._x_mode))
        chosen = [T("bench.chart_name_" + chart) + " "
                  + T(chart_points.CHOICE_LABEL_KEYS[self._point_choice[chart]])
                  for chart in CHARTS if self._point_choice[chart] != chart_points.LAST]
        if chosen:
            parts.append(T("bench.point_title") + ": " + ", ".join(chosen))
        return "  |  ".join(parts)

    def _unplaced_note(self, metrics):
        """"N run(s) without a known width ..." on the width axis, "" otherwise."""
        if self._x_mode != chart_points.X_WIDTH:
            return ""
        rows = self._filtered_rows()
        count = max((chart_points.unplaced(rows, line_value(m), self._metric_view(m))
                     for m in metrics), default=0)
        return self.T("bench.unplaced_runs", count=count) if count else ""

    # --- the table ------------------------------------------------------------------------

    def _remember_tree_row(self, item, row):
        self._tree_item_rows[item] = row

    def _select_run(self, row):
        """Makes `row` the selected run and switches the charts to SELECTED (ALL stays)."""
        if row is self._selected_run:
            return
        if self._selected_run is None:
            self._choices_before_select = dict(self._point_choice)
        self._selected_run = row
        self._point_choice = {chart: choice if choice == chart_points.ALL
                              else chart_points.SELECTED
                              for chart, choice in self._point_choice.items()}
        self._show_point_choices()
        self._redraw_charts()

    def _clear_selected_run(self, _event=None):
        """Right-click in the table: no run selected; a chart still on SELECTED goes back to
        its choice from before the selection."""
        tree = self.benchmark_tree
        if self._selected_run is None and not tree.selection():
            return
        tree.selection_set(())
        self._point_choice = {
            chart: self._choices_before_select.get(chart, choice)
            if choice == chart_points.SELECTED else choice
            for chart, choice in self._point_choice.items()}
        self._selected_run = None
        self._choices_before_select = {}
        self._show_point_choices()
        self._redraw_charts()

    def _show_point_choices(self):
        """The point choices in an open Filter window and in the filter summary."""
        window = getattr(self, "_filter_window", None)
        if window is not None and window.winfo_exists():
            for chart, var in window.choice_vars.items():
                var.set(self._point_choice[chart])
        self.filter_summary_var.set(self._filter_summary())

    def _point_menu_entries(self, chart):
        """[(label, command, enabled)] of `chart`'s point choices for its right-click menu:
        the current one ticked and disabled, SELECTED disabled while no run is selected."""
        entries = []
        for choice in chart_points.CHOICES:
            current = choice == self._point_choice[chart]
            label = self.T("bench.point_menu",
                           choice=self.T(chart_points.CHOICE_LABEL_KEYS[choice]))
            enabled = not current and (choice != chart_points.SELECTED
                                       or self._selected_run is not None)
            entries.append(("\u2713 " + label if current else label,
                            lambda c=choice: self._set_chart_choice(chart, c), enabled))
        return entries

    def _set_chart_choice(self, chart, choice):
        self._set_points(self._x_mode, {chart: choice})
        self._show_point_choices()

    def _on_tree_row_selected(self, item):
        row = self._tree_item_rows.get(item)
        if row is not None:
            self._select_run(row)

    def _turn_row_page(self, step):
        """Left/right on a run: the floor's previous/next page, its first run selected."""
        tree = self.benchmark_tree
        item = tree.focus()
        if item not in self._tree_item_rows:
            return None
        node = tree.parent(item)
        state = self._benchmark_floor_state.get(node)
        if not state:
            return "break"
        page = state["page"] + step
        if 0 <= page < state["total_pages"]:
            self._show_benchmark_page(node, page)
            first = next((i for i in tree.get_children(node) if i in self._tree_item_rows), None)
            if first is not None:
                tree.selection_set(first)
                tree.focus(first)
                tree.see(first)
        return "break"

    def _bind_tree_points(self):
        self.benchmark_tree.bind("<Left>", lambda _e: self._turn_row_page(-1))
        self.benchmark_tree.bind("<Right>", lambda _e: self._turn_row_page(1))
        self.benchmark_tree.bind("<Button-3>", self._clear_selected_run)
