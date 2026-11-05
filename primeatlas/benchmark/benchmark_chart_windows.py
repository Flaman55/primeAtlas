"""BenchmarkChartWindows mixin of BenchmarkTab: any of the three charts in a window of its own.

The "Open in new window" button above a chart opens a resizable Toplevel with a second canvas
of that chart; another click raises the open window instead of a second copy (the app's
detach pattern, as GenerationConsole's). The window draws the same chart state as the tab:
_draw_chart() draws on the tab's canvas and on the open window's, so the zoomed floor range,
the legend toggles, the pinned axes, the filter, the sieve measure and the toggles change both,
and zooming in the window zooms the tab's three charts too (one shared floor view). The
window keeps the chart's hint, the zoom gestures and its mixed-width note. Closing it only
drops its canvas.
"""
import tkinter as tk
from tkinter import ttk

WINDOW_GEOMETRY = "1100x600"
HINT_WRAP_PX = 860
CHART_HINTS = {"run": "bench.chart_hint", "sieve": "bench.chart2_hint", "ram": "bench.chart3_hint"}


class BenchmarkChartWindows:
    def _init_chart_windows(self):
        self._chart_windows = {}   # chart key -> (Toplevel, canvas)

    def _chart_frame(self, chart):
        """A full-width frame under the previous chart: the hint of `chart` ("run", "sieve",
        "ram") and the button opening it in a window."""
        frame = ttk.Frame(self)
        frame.pack(fill="x", padx=6, pady=(0, 4))
        header = ttk.Frame(frame)
        header.pack(fill="x")
        ttk.Button(header, text=self.T("bench.chart_open_window"),
                   command=lambda: self._open_chart_window(chart)).pack(side="right")
        ttk.Label(header, text=self._chart_hint(chart), wraplength=HINT_WRAP_PX,
                  justify="left").pack(side="left", anchor="w")
        return frame

    def _chart_hint(self, chart):
        return self.T(CHART_HINTS[chart]) + "; " + self.T("bench.zoom_hint")

    def _chart_window_canvases(self, chart):
        entry = self._chart_windows.get(chart)
        if entry is None:
            return []
        win, canvas = entry
        return [canvas] if win.winfo_exists() else []

    def _open_chart_window(self, chart):
        entry = self._chart_windows.get(chart)
        if entry is not None and entry[0].winfo_exists():
            entry[0].lift()
            return entry[0]
        T, p = self.T, self._theme_palette
        win = tk.Toplevel(self)
        win.title(T("bench.chart_window_title", chart=T(f"bench.chart_name_{chart}")))
        win.geometry(WINDOW_GEOMETRY)
        body = ttk.Frame(win)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=self._chart_hint(chart), wraplength=1060,
                  justify="left").pack(anchor="w", padx=8, pady=(8, 4))
        ttk.Label(body, style="Status.TLabel",
                  textvariable=self.mixed_widths_vars[chart]).pack(side="bottom", anchor="w",
                                                                    padx=8, pady=(0, 8))
        canvas = tk.Canvas(body, background=p["console_bg"], highlightthickness=1,
                           highlightbackground=p["border"])
        canvas.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        canvas.bind("<Configure>", lambda _e: self._redraw_chart(chart))
        self._bind_chart_zoom(canvas, chart)
        self._chart_windows[chart] = (win, canvas)

        def _on_close():
            self._chart_windows.pop(chart, None)
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", _on_close)
        self._redraw_chart(chart)
        return win
