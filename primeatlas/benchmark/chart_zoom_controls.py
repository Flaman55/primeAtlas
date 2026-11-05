"""BenchmarkChartZoom -- mouse zoom and pan of the Benchmark charts along the floor axis, the
gestures of the visualizations: the wheel zooms around the floor under the pointer, a left drag
pans, a middle click or a double click shows every floor again. The three charts share one view
(chart_view.py); the drawing reads it as x_view, and every export follows it.

The bindings sit on each chart canvas and return "break", so a wheel turn over a chart never
reaches the page's own wheel scrolling (bound app-wide while the pointer is over the page). A
press that moves less than DRAG_SLOP_PX is a click, left to the legend and the pin menu.

A BenchmarkTab mixin: it uses the tab's canvases, rows and redraw methods.
"""
from . import chart_view

DRAG_SLOP_PX = 4
_SPAN_METRICS = ("growth", "write", "sieve", "sieve_spw", "ram", "ram_per_window")


class BenchmarkChartZoom:
    _x_view = None
    _drag = None

    def _bind_chart_zoom(self, canvas):
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            canvas.bind(sequence, lambda e, c=canvas: self._on_chart_wheel(c, e))
        canvas.bind("<ButtonPress-1>", lambda e, c=canvas: self._on_chart_press(c, e), add="+")
        canvas.bind("<B1-Motion>", lambda e: self._on_chart_drag(e))
        canvas.bind("<ButtonRelease-1>", lambda _e: self._end_chart_drag(), add="+")
        canvas.bind("<Button-2>", lambda _e: self._reset_chart_view())
        canvas.bind("<Double-Button-1>", lambda _e: self._reset_chart_view())

    def _x_span(self):
        return chart_view.data_span(*(self._chart_series(m) for m in _SPAN_METRICS))

    def _set_chart_view(self, view):
        if view != self._x_view:
            self._x_view = view
            self._redraw_charts()

    def _on_chart_wheel(self, canvas, event):
        geometry = getattr(canvas, "chart_geometry", None)
        if geometry:
            zoom_in = event.num == 4 or getattr(event, "delta", 0) > 0
            factor = chart_view.WHEEL_STEP if zoom_in else 1 / chart_view.WHEEL_STEP
            self._set_chart_view(chart_view.zoom(
                self._x_view, self._x_span(), chart_view.floor_at(geometry, event.x), factor))
        return "break"

    def _on_chart_press(self, canvas, event):
        geometry = getattr(canvas, "chart_geometry", None)
        self._drag = (event.x, self._x_view, geometry) if geometry else None

    def _on_chart_drag(self, event):
        if self._drag is None:
            return
        start_x, start_view, geometry = self._drag
        dx = event.x - start_x
        if start_view is None or abs(dx) < DRAG_SLOP_PX:
            return
        self._set_chart_view(chart_view.pan(start_view, self._x_span(),
                                            -dx * chart_view.floors_per_pixel(geometry)))

    def _end_chart_drag(self):
        self._drag = None

    def _reset_chart_view(self):
        self._drag = None
        self._set_chart_view(None)
        return "break"
