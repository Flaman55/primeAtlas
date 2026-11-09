"""BenchmarkRamChart mixin of BenchmarkTab: the RAM chart, the lowest of the three.

Each run's peak RAM (max_child_rss_mb, the largest process's peak) in MB on the left axis and
that per written window on the right one, so runs of different widths compare. It has its own
canvas so its megabytes do not share an axis with a speed, and the same legend toggles, log
scale, pinned axes and mixed-width note as the speed charts (chart key "ram"). Native
primesieve runs write no Atlas windows, so they have a point on MB per run only.
"""
import tkinter as tk
from tkinter import ttk

DEFAULT_SIZE = (900, 180)


class BenchmarkRamChart:
    def _build_ram_chart(self, parent):
        """The chart's canvas and mixed-width note in `parent`, under its hint."""
        p = self._theme_palette
        self.benchmark_chart3 = tk.Canvas(parent, height=DEFAULT_SIZE[1],
                                          background=p["console_bg"], highlightthickness=1,
                                          highlightbackground=p["border"])
        self.benchmark_chart3.pack(fill="x")
        self.benchmark_chart3.bind("<Configure>", lambda _e: self._redraw_benchmark_chart3())
        self._bind_chart_zoom(self.benchmark_chart3, "ram")
        self._mixed_widths_labels["ram"] = (
            ttk.Label(parent, style="Status.TLabel", textvariable=self.mixed_widths_vars["ram"]),
            self.benchmark_chart3)

    def _redraw_benchmark_chart3(self):
        self._show_mixed_widths("ram", ("ram", "ram_per_window"))
        self._draw_chart("ram", self.benchmark_chart3, [], DEFAULT_SIZE,
                         label_key1="bench.axis_ram_mb", label_key2="bench.axis_ram_mb_window",
                         fmt1="{:,.0f}", fmt2="{:,.2f}",
                         series1=self._chart_series("ram"),
                         series2=self._chart_series("ram_per_window"),
                         marks=self._chart_marks("ram", "ram_per_window"))
