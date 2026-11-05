"""BenchmarkChartZoom -- mouse zoom and pan of the Benchmark charts, as when zooming a picture:
the wheel zooms the part of the chart under the pointer on both axes (the floor axis of all
three charts, the y axes of that chart), a left drag moves the visible part, a middle click or
a double click shows the whole charts again. The views live in chart_view.py terms: one shared
x view (self._x_view, its notch level self._x_level and the range it zooms from, self._x_base:
the floors of the chart zoomed first) and one y view and level per chart (self._y_views,
self._y_levels); the drawing reads the views, and every export follows them.

The bindings sit on each chart canvas and return "break", so a wheel turn over a chart never
reaches the page's own wheel scrolling (bound app-wide while the pointer is over the page). A
press that moves less than DRAG_SLOP_PX is a click, left to the legend and the pin menu.

A BenchmarkTab mixin: it uses the tab's canvases (and the chart windows'), rows and redraw
methods.
"""
from . import chart_view, sieve_measure

DRAG_SLOP_PX = 4


class BenchmarkChartZoom:
    _x_view = None
    _x_level = 0
    _x_base = None
    _drag = None

    def _init_chart_zoom(self):
        self._y_views = {"run": None, "sieve": None, "ram": None}
        self._y_levels = {"run": 0, "sieve": 0, "ram": 0}

    def _bind_chart_zoom(self, canvas, chart):
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            canvas.bind(sequence, lambda e, c=canvas: self._on_chart_wheel(c, chart, e))
        canvas.bind("<ButtonPress-1>", lambda e, c=canvas: self._on_chart_press(c, chart, e),
                    add="+")
        canvas.bind("<B1-Motion>", lambda e: self._on_chart_drag(e))
        canvas.bind("<ButtonRelease-1>", lambda _e: self._end_chart_drag(), add="+")
        canvas.bind("<Button-2>", lambda _e: self._reset_chart_view())
        canvas.bind("<Double-Button-1>", lambda _e: self._reset_chart_view())

    def _x_span(self):
        """The floors of every chart's points: the whole run, the sieve in its measure with
        the references while they are on, RAM."""
        spec = sieve_measure.chart(self._sieve_measure)
        series = [self._chart_series(m) for m in ("growth", "write", spec.metric2, "ram",
                                                  "ram_per_window")]
        return chart_view.data_span(*series, self._chart_series(spec.metric1, spec.references))

    def _set_chart_view(self, x_view, chart=None, y_view=None):
        """Sets the shared x view and, with `chart`, that chart's y view; redraws on a change."""
        changed = x_view != self._x_view
        self._x_view = x_view
        if chart is not None and y_view != self._y_views[chart]:
            self._y_views[chart] = y_view
            changed = True
        if changed:
            self._redraw_charts()

    def _on_chart_wheel(self, canvas, chart, event):
        geometry = getattr(canvas, "chart_geometry", None)
        if geometry:
            steps = 1 if event.num == 4 or getattr(event, "delta", 0) > 0 else -1
            if self._x_level == 0:
                self._x_base = geometry[8]
            x_view, self._x_level = chart_view.zoom_step(
                self._x_view, self._x_level, self._x_base,
                chart_view.floor_at(geometry, event.x), steps, self._x_span())
            y_view, self._y_levels[chart] = chart_view.zoom_step(
                self._y_views[chart], self._y_levels[chart], chart_view.FULL_Y,
                chart_view.y_frac_at(geometry, event.y), steps, geometry[7])
            self._set_chart_view(x_view, chart, y_view)
        return "break"

    def _on_chart_press(self, canvas, chart, event):
        geometry = getattr(canvas, "chart_geometry", None)
        self._drag = ((event.x, event.y, self._x_view, self._y_views[chart], geometry, chart)
                      if geometry else None)

    def _on_chart_drag(self, event):
        if self._drag is None:
            return
        start_x, start_y, x_view, y_view, geometry, chart = self._drag
        dx, dy = event.x - start_x, event.y - start_y
        if (x_view is None and y_view is None) or max(abs(dx), abs(dy)) < DRAG_SLOP_PX:
            return
        self._set_chart_view(
            chart_view.pan(x_view, self._x_span(), -dx * chart_view.floors_per_pixel(geometry)),
            chart,
            chart_view.pan(y_view, geometry[7], dy * chart_view.y_fracs_per_pixel(geometry)))

    def _end_chart_drag(self):
        self._drag = None

    def _reset_chart_view(self):
        self._drag = None
        self._y_views = {chart: None for chart in self._y_views}
        self._y_levels = {chart: 0 for chart in self._y_levels}
        self._x_view, self._x_level, self._x_base = None, 0, None
        self._redraw_charts()
        return "break"
