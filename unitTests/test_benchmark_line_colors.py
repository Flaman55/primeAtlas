"""Benchmark line colors: readable defaults and the user's own color per engine
(primeatlas/benchmark/line_colors.py, the legend's right-click menu in benchmark_tab.py).

Defaults: two palettes, dark and light, with the same engines; each color reaches 3:1
contrast on its theme's chart background (white for light), keeps its hue across the two
and stays far from the other colors of its palette, the reference colors included. The tab
draws in the app's theme, every export in the light palette (white background); an unknown
theme falls back to the default. Overrides: stored per theme and engine key in the
remembered-fields store, used by every Series of that engine (all lines of the engine,
every chart, the width-axis shades, the exports of the light theme);
invalid values in the store or from the caller are ignored; a reset brings the default
back; the store survives a reload from its file. Tab: a right-click on a legend entry opens
the color menu of that engine (not the pin menu); choosing a color redraws the charts in it;
the resets are enabled only while there is something to reset; a right-click off the legend
still opens the pin menu; a reference line has no color menu. Windows, real display:
    python unitTests/test_benchmark_line_colors.py
"""
import colorsys
import csv
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "prime_sieve"), str(ROOT / "constellation")]

from primeatlas.benchmark import (benchmark, chart_points, chart_series,  # noqa: E402
                                  line_colors, reference_points)
from primeatlas.core import theme_dynamic, ui_state_dynamic  # noqa: E402
from primeatlas.core.i18n import Translator  # noqa: E402
from primeatlas.core.theme import palette_for  # noqa: E402
from primeatlas.core.ui_state_store import UiStateStore  # noqa: E402


def _luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    channels = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _row(floor, engine, version, numbers=10 ** 9, nps="1e8"):
    return dict(base_exponent=str(floor), engine=engine, engine_version=version, threads="24",
                write_threads="8", instance_of_n="1/1", numbers_processed=str(numbers),
                windows_written=str(numbers // 10 ** 7), sieve_seconds="2",
                loop_numbers_per_second=nps, write_seconds="1", bytes_written="1000000")


ROWS = [_row(20, "v6", "v6.0"), _row(21, "v6", "v6.0"), _row(20, "v5", "v5.1"),
        dict(_row(20, "v6", "v6.0"), threads="1")]


def _rgb(color):
    return [int(color[i:i + 2], 16) for i in (1, 3, 5)]


def _hue(color):
    return colorsys.rgb_to_hls(*[c / 255 for c in _rgb(color)])[0] * 360


def _palette(theme):
    return dict(line_colors.PALETTES[theme], other=line_colors.OTHER_COLORS[theme])


# Chart background per palette: the dark theme's canvas, white for light (the light theme's
# canvas and every export).
BACKGROUNDS = {"dark": palette_for("dark")["console_bg"], "light": "#ffffff"}


class _StoreCase(unittest.TestCase):
    def setUp(self):
        self._store = ui_state_dynamic.STORE
        self._theme = theme_dynamic.THEME
        ui_state_dynamic.STORE = UiStateStore(None)

    def tearDown(self):
        ui_state_dynamic.STORE = self._store
        theme_dynamic.THEME = self._theme


class DefaultTests(_StoreCase):
    def test_both_palettes_name_the_same_engines(self):
        self.assertEqual(set(line_colors.PALETTES), {"dark", "light"})
        self.assertEqual(set(line_colors.PALETTES["dark"]), set(line_colors.PALETTES["light"]))
        self.assertEqual(set(line_colors.OTHER_COLORS), set(line_colors.PALETTES))
        self.assertEqual(palette_for("light")["console_bg"], BACKGROUNDS["light"],
                         "the light theme's canvas is white like the exports")

    def test_each_palette_is_readable_on_its_background(self):
        for theme, bg in BACKGROUNDS.items():
            for engine, color in _palette(theme).items():
                self.assertGreaterEqual(_contrast(color, bg), 3.0,
                                        f"{theme}: {engine} {color} on {bg}")

    def test_an_engine_keeps_its_hue(self):
        dark, light = _palette("dark"), _palette("light")
        for engine in dark:
            grey = max(_rgb(dark[engine])) - min(_rgb(dark[engine])) < 20
            self.assertEqual(max(_rgb(light[engine])) - min(_rgb(light[engine])) < 20, grey,
                             engine)
            if not grey:
                diff = abs(_hue(dark[engine]) - _hue(light[engine])) % 360
                self.assertLessEqual(min(diff, 360 - diff), 25,
                                     f"{engine} {dark[engine]} / {light[engine]}")

    def test_colors_of_a_palette_are_far_apart(self):
        refs = {r.tag: r.color for r in reference_points.REFERENCES}
        for theme in BACKGROUNDS:
            colors = dict(_palette(theme), **refs)
            names = sorted(colors)
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    distance = sum((p - q) ** 2 for p, q in
                                   zip(_rgb(colors[a]), _rgb(colors[b]))) ** 0.5
                    self.assertGreaterEqual(distance, 85,
                                            f"{theme}: {a} {colors[a]} vs {b} {colors[b]}")

    def test_the_theme_picks_the_palette(self):
        theme_dynamic.THEME = "light"
        self.assertEqual(line_colors.engine_color("v6"), line_colors.PALETTES["light"]["v6"])
        self.assertEqual(line_colors.engine_color("cuda"), line_colors.OTHER_COLORS["light"])
        self.assertEqual(line_colors.engine_color("v6", theme="dark"),
                         line_colors.PALETTES["dark"]["v6"], "a named theme wins")
        theme_dynamic.THEME = "sepia"
        self.assertEqual(line_colors.engine_color("v6"), line_colors.PALETTES["dark"]["v6"],
                         "an unknown theme: the default")
        theme_dynamic.THEME = "dark"
        self.assertEqual(line_colors.engine_color("v6"), line_colors.PALETTES["dark"]["v6"])

    def test_no_override_means_the_defaults(self):
        store = UiStateStore(None)
        for engine, color in chart_series.ENGINE_COLORS.items():
            self.assertEqual(line_colors.engine_color(engine, store), color)
        self.assertEqual(line_colors.engine_color("cuda", store), chart_series.OTHER_ENGINE_COLOR)


class OverrideTests(_StoreCase):
    def test_set_reset_and_reset_all(self):
        store = ui_state_dynamic.STORE
        self.assertTrue(line_colors.set_color(store, "v6", "#ABCDEF"))
        self.assertEqual(line_colors.engine_color("v6", store), "#abcdef", "kept lower case")
        self.assertTrue(line_colors.set_color(store, "cuda", "#102030"),
                        "an engine without a default color can have one")
        self.assertEqual(line_colors.engine_color("cuda", store), "#102030")
        self.assertEqual(line_colors.engine_color("v5", store), chart_series.ENGINE_COLORS["v5"])
        self.assertEqual(line_colors.overridden(store), {"v6", "cuda"})
        line_colors.reset_color(store, "v6")
        self.assertEqual(line_colors.engine_color("v6", store), chart_series.ENGINE_COLORS["v6"])
        line_colors.reset_color(store, "v6")  # twice: nothing to reset, no error
        line_colors.reset_all(store)
        self.assertEqual(line_colors.overridden(store), set())
        self.assertEqual(line_colors.engine_color("cuda", store), chart_series.OTHER_ENGINE_COLOR)

    def test_invalid_colors_are_refused_and_ignored(self):
        store = ui_state_dynamic.STORE
        for bad in ("red", "#12345", "#1234567", "#gggggg", "", None, 5, "123456"):
            self.assertFalse(line_colors.set_color(store, "v6", bad), repr(bad))
        self.assertEqual(line_colors.overridden(store), set())
        store.set(line_colors.store_key(), {"v6": "#zzzzzz", "v5": 7, "v7": "#00ff00"})
        self.assertEqual(line_colors.engine_color("v6", store), chart_series.ENGINE_COLORS["v6"])
        self.assertEqual(line_colors.engine_color("v5", store), chart_series.ENGINE_COLORS["v5"])
        self.assertEqual(line_colors.engine_color("v7", store), "#00ff00")
        store.set(line_colors.store_key(), ["not", "a", "dict"])
        self.assertEqual(line_colors.engine_color("v7", store), chart_series.ENGINE_COLORS["v7"])
        self.assertTrue(line_colors.set_color(store, "v7", "#010203"), "a broken entry is replaced")

    def test_every_line_of_the_engine_and_every_chart_follow(self):
        line_colors.set_color(ui_state_dynamic.STORE, "v6", "#123456")
        for metric in ("growth", "sieve", "write"):
            series = benchmark.benchmark_series(ROWS, metric)
            v6 = [s for s in series if s.engine == "v6"]
            self.assertEqual(len(v6), 2, "24 thr and 1 thr lines")
            self.assertTrue(all(s.color == "#123456" for s in v6), metric)
            self.assertTrue(all(s.color == chart_series.ENGINE_COLORS["v5"]
                                for s in series if s.engine == "v5"))

    def test_width_axis_shades_start_from_the_override(self):
        line_colors.set_color(ui_state_dynamic.STORE, "v6", "#808080")
        view = chart_points.PointView(chart_points.X_WIDTH, chart_points.LAST)
        colors = {s.name: s.color for s in benchmark.benchmark_series(ROWS[:2], "sieve", view)}
        self.assertEqual(sorted(colors.values()),
                         sorted(["#808080", chart_points.shade("#808080", 1)]))

    def test_references_keep_their_colors(self):
        line_colors.set_color(ui_state_dynamic.STORE, "v6", "#123456")
        refs = reference_points.reference_series(Translator("en").t)
        self.assertEqual([r.color for r in refs], [r.color for r in reference_points.REFERENCES])

    def test_overrides_are_per_theme(self):
        store = ui_state_dynamic.STORE
        line_colors.set_color(store, "v6", "#123456", theme="dark")
        self.assertEqual(line_colors.engine_color("v6", store, "light"),
                         line_colors.PALETTES["light"]["v6"])
        line_colors.set_color(store, "v6", "#654321", theme="light")
        self.assertEqual(line_colors.engine_color("v6", store, "dark"), "#123456")
        line_colors.reset_all(store, theme="light")
        self.assertEqual(line_colors.overridden(store, "dark"), {"v6"})
        self.assertEqual(line_colors.overridden(store, "light"), set())
        theme_dynamic.THEME = "light"
        line_colors.set_color(store, "v5", "#0a0b0c")
        self.assertEqual(line_colors.overridden(store, "light"), {"v5"},
                         "no theme named: the app's")

    def test_exports_draw_the_light_palette(self):
        theme_dynamic.THEME = "dark"
        line_colors.set_color(ui_state_dynamic.STORE, "v5", "#0a0b0c", theme="light")
        spec = benchmark.report_chart_pages(ROWS)[0][1][0]
        series = benchmark.report_chart_series(ROWS, spec)
        self.assertTrue(series)
        for s in series:
            self.assertEqual(s.color, {"v6": line_colors.PALETTES["light"]["v6"],
                                       "v5": "#0a0b0c"}[s.engine], s.name)
        tab_colors = {s.engine: s.color for s in benchmark.benchmark_series(ROWS, spec[2])}
        self.assertEqual(tab_colors["v6"], line_colors.PALETTES["dark"]["v6"],
                         "the tab draws in the app's theme")

    def test_survives_a_reload_of_the_store_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "ui_state.json")
            first = UiStateStore(path)
            line_colors.set_color(first, "pt1 P", "#a0b0c0")
            first.flush()
            self.assertEqual(line_colors.engine_color("pt1 P", UiStateStore(path)), "#a0b0c0")
            line_colors.reset_color(first, "pt1 P")
            first.flush()
            self.assertEqual(line_colors.overridden(UiStateStore(path)), set())


class TabColorMenuTests(_StoreCase):
    def test_legend_right_click_colors_the_engine(self):
        import tkinter as tk
        from tkinter import colorchooser
        from primeatlas.benchmark import benchmark_tab

        t = Translator("en").t
        menus, asked = [], []
        original_ask = colorchooser.askcolor

        def fake_ask(color=None, **kw):
            asked.append(color)
            return ((1, 2, 3), "#010203")
        colorchooser.askcolor = fake_ask
        with tempfile.TemporaryDirectory() as portal:
            with open(os.path.join(portal, "benchmark_log.csv"), "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(ROWS[0]))
                writer.writeheader()
                writer.writerows(ROWS)
            root = tk.Tk()
            try:
                tab = benchmark_tab.BenchmarkTab(
                    root, lambda: portal, tk.StringVar(master=root), Translator("en"),
                    lambda *a, **k: None, palette_for("dark"))
                tab.pack()
                tab._post_menu = lambda entries, x, y: menus.append(entries)
                tab.reload_benchmark_log()
                root.update()
                tab._redraw_charts()
                chart = tab.benchmark_chart
                v6_name = "v6.0, 24 thr, write 8"

                def legend_text(canvas, name):
                    hits = [i for i in canvas.find_withtag("legend")
                            if canvas.type(i) == "text" and canvas.itemcget(i, "text") == name]
                    self.assertEqual(len(hits), 1, name)
                    return hits[0]

                def right_click(canvas, x, y):
                    menus.clear()
                    canvas.event_generate("<Motion>", x=x, y=y)
                    canvas.event_generate("<Button-3>", x=x, y=y)
                    root.update()
                    self.assertEqual(len(menus), 1, "one menu per right-click")
                    return {label: (command, enabled) for label, command, enabled in menus[0]}

                def click_legend(canvas, name):
                    x0, y0, x1, y1 = canvas.bbox(legend_text(canvas, name))
                    return right_click(canvas, (x0 + x1) // 2, (y0 + y1) // 2)

                entries = click_legend(chart, v6_name)
                choose = t("bench.color_choose", line=v6_name)
                self.assertEqual(set(entries), {choose, t("bench.color_reset"),
                                                t("bench.color_reset_all")},
                                 "the color menu, not the pin menu")
                self.assertTrue(entries[choose][1])
                self.assertFalse(entries[t("bench.color_reset")][1], "nothing to reset yet")
                self.assertFalse(entries[t("bench.color_reset_all")][1])

                entries[choose][0]()
                self.assertEqual(asked, [chart_series.ENGINE_COLORS["v6"]],
                                 "the dialog starts from the current color")
                for canvas in (chart, tab.benchmark_chart2):
                    self.assertEqual(canvas.itemcget(legend_text(canvas, v6_name), "fill"),
                                     "#010203", "every chart redrawn")
                self.assertEqual(chart.itemcget(legend_text(chart, "v6.0, 1 thr, write 8"),
                                                "fill"), "#010203", "every line of the engine")
                self.assertEqual(chart.itemcget(legend_text(chart, "v5.1, 24 thr, write 8"),
                                                "fill"), chart_series.ENGINE_COLORS["v5"])

                # The dialog cancelled: nothing changes.
                colorchooser.askcolor = lambda color=None, **kw: (None, None)
                click_legend(chart, v6_name)[choose][0]()
                self.assertEqual(line_colors.engine_color("v6", ui_state_dynamic.STORE),
                                 "#010203")

                entries = click_legend(chart, v6_name)
                self.assertTrue(entries[t("bench.color_reset")][1])
                entries[t("bench.color_reset")][0]()
                self.assertEqual(chart.itemcget(legend_text(chart, v6_name), "fill"),
                                 chart_series.ENGINE_COLORS["v6"])

                # Reset all from another engine's entry.
                colorchooser.askcolor = fake_ask
                v5_name = "v5.1, 24 thr, write 8"
                click_legend(chart, v5_name)[t("bench.color_choose", line=v5_name)][0]()
                entries = click_legend(chart, v6_name)
                self.assertFalse(entries[t("bench.color_reset")][1], "v6 has the default")
                self.assertTrue(entries[t("bench.color_reset_all")][1])
                entries[t("bench.color_reset_all")][0]()
                self.assertEqual(line_colors.overridden(ui_state_dynamic.STORE), set())

                # Off the legend: still the pin menu.
                entries = right_click(chart, 3, chart.winfo_height() - 3)
                self.assertIn(t("bench.pin_reset_chart"), entries)

                # A reference line: no color menu.
                tab.references_var.set(True)
                tab._redraw_charts()
                ref = reference_points.reference_series(t)[0].name
                entries = click_legend(tab.benchmark_chart2, ref)
                self.assertNotIn(t("bench.color_reset_all"), entries)
            finally:
                root.destroy()
                colorchooser.askcolor = original_ask

    def test_locales_have_the_color_keys(self):
        for lang in ("en", "pl"):
            t = Translator(lang).t
            for key in ("bench.color_choose", "bench.color_reset", "bench.color_reset_all",
                        "bench.color_dialog_title"):
                self.assertNotEqual(t(key, line="x"), key, f"{lang}: {key}")


if __name__ == "__main__":
    unittest.main()
