"""
benchmark_line_colors.py -- BenchmarkLineColors, the right-click menu of a Benchmark legend
entry: the color of that line's engine in the app's theme (every line of the engine, every
chart, line_colors.py), its default back, or every default back. A reference line has no menu
entry here (benchmark_tab._bind_pin_menu() opens the pin menu for it).

A BenchmarkTab mixin: it uses _post_menu() and _redraw_charts() of the tab.
"""
from tkinter import colorchooser

from primeatlas.core import ui_state_dynamic
from . import line_colors


class BenchmarkLineColors:
    def _color_menu_entries(self, series):
        """[(label, command, enabled)] for the legend entry of `series`."""
        T = self.T
        overridden = line_colors.overridden(ui_state_dynamic.STORE)
        return [(T("bench.color_choose", line=series.name),
                 lambda: self._choose_line_color(series), True),
                (T("bench.color_reset"), lambda: self._reset_line_color(series.engine),
                 series.engine in overridden),
                (T("bench.color_reset_all"), self._reset_line_colors, bool(overridden))]

    def _on_color_menu(self, series, x_root, y_root):
        self._post_menu(self._color_menu_entries(series), x_root, y_root)

    def _choose_line_color(self, series):
        _rgb, color = colorchooser.askcolor(
            color=line_colors.engine_color(series.engine, ui_state_dynamic.STORE),
            title=self.T("bench.color_dialog_title", line=series.name), parent=self)
        if color and line_colors.set_color(ui_state_dynamic.STORE, series.engine, color):
            self._redraw_charts()

    def _reset_line_color(self, engine):
        line_colors.reset_color(ui_state_dynamic.STORE, engine)
        self._redraw_charts()

    def _reset_line_colors(self):
        line_colors.reset_all(ui_state_dynamic.STORE)
        self._redraw_charts()
