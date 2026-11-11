"""
benchmark_tab.py -- BenchmarkTab, the tkinter widgets for the Benchmark tab: a small
dependency-free growth chart (numbers/s vs. floor depth, one point per floor -- latest
logged run wins) plus a phase-breakdown chart (sieve-numbers/s + write-MB/s), above a
paginated, lazily-expandable tree view of the full benchmark_log.csv (written by
orchestrator_v3.py's print_benchmark_summary()); a "Save PDF" button renders the same
chart(s) + full table into a standalone PDF report.

Split out of PortalBrowserApp's tab-by-tab backend/UI separation: this module owns
only the widgets and the tkinter-specific on-screen chart drawing (_draw_growth_chart
below). All the pure-logic reduction/PDF-rendering work lives in
primeatlas/benchmark/benchmark.py.

This module imports tkinter; the pure logic it shows lives in benchmark.py, the
"pure logic elsewhere" convention the package follows.

BenchmarkTab does not know how PORTAL_FOLDER is stored or how the app's shared status
bar/translator are constructed -- it receives everything it needs at construction time
(get_portal_folder, status_var, translator, update_nav_controls) instead of importing
primeatlas/app/ directly, which would be circular (that file imports BenchmarkTab
from this module). update_nav_controls in particular is PortalBrowserApp's own small
shared pagination-label/button helper, used identically by every OTHER tab's own
pagination (Prime numbers, Constellations, Goldbach, ...) -- it stays put there rather
than being duplicated or promoted to its own module just for this one extraction, and
is passed in exactly like SettingsTab's wsl_helpers callables are.
"""
import re

import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

from ..core.base_tab import BaseTab
from ..core.ui_state import remember
from ..core.widgets import StripedTreeview
from .benchmark import (
    BENCHMARK_PAGE_SIZE, aggregate_benchmark_fair_spw,
    aggregate_benchmark_growth, aggregate_benchmark_sieve_nps,
    aggregate_benchmark_write_mbps, benchmark_series, mixed_width_floors,
    group_benchmark_rows_by_floor, read_benchmark_log,
)
from ..core.i18n import Translator, DEFAULT_LANGUAGE
from .chart_series import (
    axis_pins, clear_pins, clip_polyline, in_view, legend_entries, line_key,
    pin_bound, plain_series, point_label, series_xs, toggle_lines, visible_series, y_scale,
)
from . import chart_points, chart_view
from .benchmark_chart_windows import BenchmarkChartWindows
from .benchmark_export import BenchmarkExport
from .benchmark_filter import BenchmarkFilter
from .benchmark_line_colors import BenchmarkLineColors
from .benchmark_points import BenchmarkPoints
from .benchmark_view_state import BenchmarkViewState
from .benchmark_ram_chart import BenchmarkRamChart
from .chart_hover import _bind_chart_hover, _nearest_point
from .chart_zoom_controls import BenchmarkChartZoom
from . import sieve_measure, table_columns
from .reference_points import reference_series


def _mix(color_a, color_b):
    """The hex color half way between two "#rrggbb" colors."""
    a = [int(color_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(color_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join("%02x" % ((x + y) // 2) for x, y in zip(a, b))


def _legend_tag(kind, name):
    """Canvas tag of a legend item; tag searches parse spaces and parentheses, so the
    series name is reduced to word characters and dots."""
    return "legend:%s:%s" % (kind, re.sub(r"[^\w.]", "_", name))


def _draw_legend(canvas, entries, hidden, on_toggle, x, bg_color, dim_color):
    """One entry per series along the top edge: a marker per line (circle: left axis,
    square: right axis) and the name. With on_toggle, a marker click toggles its line and a
    name click all lines of the series: on_toggle([line_key, ...]). A hidden line's marker
    is a hollow dim outline; a name whose lines are all hidden is dim. canvas.legend_series
    maps each item's tag to its Series for the right-click (_bind_pin_menu)."""
    font = ("Consolas", 8, "bold")
    r, y = 4, 10
    for s, axes in entries:
        keys = [line_key(axis, s.name) for axis in axes]
        for axis, key in zip(axes, keys):
            off = key in hidden
            tag = _legend_tag(axis, s.name)
            canvas.legend_series[tag] = s
            # The background box widens the click target beyond the 8 px marker.
            canvas.create_rectangle(x, y - 8, x + 14, y + 8, fill=bg_color, outline="",
                                    tags=("legend", tag))
            color = dim_color if off else s.color
            fill = bg_color if off or s.dashed else s.color
            shape = canvas.create_rectangle if axis == "secondary" else canvas.create_oval
            shape(x + 7 - r, y - r, x + 7 + r, y + r, outline=color, fill=fill,
                  width=2 if off or s.dashed else 0, tags=("legend", tag))
            if on_toggle:
                canvas.tag_bind(tag, "<Button-1>", lambda _e, k=key: on_toggle([k]))
            x += 14
        tag = _legend_tag("name", s.name)
        canvas.legend_series[tag] = s
        text_id = canvas.create_text(x + 3, y, text=s.name, anchor="w", font=font,
                                     fill=dim_color if all(k in hidden for k in keys)
                                     else s.color, tags=("legend", tag))
        if on_toggle:
            canvas.tag_bind(tag, "<Button-1>", lambda _e, k=keys: on_toggle(k))
        bbox = canvas.bbox(text_id)
        x = (bbox[2] if bbox else x + 60) + 16
    if on_toggle:
        canvas.tag_bind("legend", "<Enter>", lambda _e: canvas.configure(cursor="hand2"))
        canvas.tag_bind("legend", "<Leave>", lambda _e: canvas.configure(cursor=""))


def _draw_growth_chart(canvas, points, width, height, points2=None, translator=None,
                        label_key1="bench.axis_nps", label_key2="bench.axis_spw",
                        fmt1="{:,.0f}", fmt2="{:,.3f}",
                        bg_color="#ffffff", fg_color="#000000", grid_color="#666666",
                        series1=None, series2=None, log_y=False, hidden=None,
                        on_toggle=None, pins1=None, pins2=None, on_pin_menu=None,
                        on_color_menu=None, x_view=None, y_view=None, x_mode=chart_points.X_FLOOR, marks=None):
    """Draws a floor-depth chart onto `canvas`: x = floor (or the run's width, x_mode), y = one
    or two axes of chart_series.Series (one line per engine, plus dashed reference lines). Plain
    tk.Canvas drawing, no charting library: the app is zero-extra-installs. Clears the
    canvas first, so it is safe to call again on refresh/resize (<Configure>).

    series1/series2: [Series] on the left and right axis; when omitted, points/points2
    (bare (floor, value) lists) are drawn as one unnamed series each. The right axis exists
    only when it has points; each axis has its own scale (chart_series.YScale, log10 when
    log_y), since the two series differ by orders of magnitude. An engine keeps its color on
    both axes: left-axis points are circles on a thick line, right-axis points squares on a
    thin line, and the axis titles carry the same marker. Named series get one legend entry
    each along the top edge (_draw_legend); a point's value and series tag show in a hover
    tooltip.

    hidden: set of chart_series.line_key() left out of the plot and its scales; their
    legend markers stay, so on_toggle (the legend's click callback) can bring them back.

    pins1/pins2: the axes' pinned (min, max) (chart_series.axis_pins()): a pinned bound is
    the axis edge exactly, lines are cut there and the points beyond it are not drawn; the
    axis title says "pinned". on_pin_menu(target, x_root, y_root): right-click callback,
    target = (axis, value, value text) of the point under the pointer or None.
    on_color_menu(series, x_root, y_root): right-click on an engine's legend entry instead.

    label_key1/label_key2/fmt1/fmt2: same meaning as chart_pdf.chart_ops()'s parameters, so
    the PDF and this chart stay consistent. translator: a primeatlas.core.i18n.Translator,
    DEFAULT_LANGUAGE when omitted. bg_color/fg_color/grid_color: the theme's colors.

    x_view/y_view: the zoomed part of the chart (chart_view.py): (lo, hi) in floors, and
    (lo, hi) as fractions of the full y scales (pins included); None for the whole axis. The
    axes show that part, the lines are cut at the plot edges, the points outside it are not
    drawn. canvas.chart_geometry keeps (x of the first floor, its pixel width, first floor,
    last floor, y of the plot top, plot height, y_view, the data's (lowest, highest) fraction
    of the full y scales, the chart's own (first, last) floor unzoomed) for the zoom and pan
    bindings, None while nothing is plotted. x_mode: chart_points.X_FLOOR or X_WIDTH, which
    names the x ticks and the axis title. marks: {(axis, line name, x, value)} of the points
    from the run selected in the table, ringed in the foreground color (tag "selected_mark")."""
    t = (translator or Translator(DEFAULT_LANGUAGE)).t
    canvas.configure(background=bg_color)
    canvas.delete("all")
    canvas.chart_geometry = None
    canvas.legend_series = {}
    if width <= 1 or height <= 1:
        return  # not yet realized/sized
    series1 = [s for s in (series1 if series1 is not None else plain_series(points or []))
               if s.points]
    series2 = [s for s in (series2 if series2 is not None
                           else plain_series(points2 or [], "secondary")) if s.points]
    if not series1 and not series2:
        canvas.create_text(width / 2, height / 2, text=t("bench.no_data_chart"),
                            fill="#888888")
        _bind_chart_hover(canvas, [], t, fg_color, bg_color, width, height)
        _bind_pin_menu(canvas, [], on_pin_menu, on_color_menu)
        return
    hidden = hidden or set()
    # A fixed legend origin keeps every toggle under the pointer while the axes refit.
    _draw_legend(canvas, legend_entries(series1, series2), hidden, on_toggle, 50, bg_color,
                 _mix(bg_color, grid_color))
    series1 = visible_series(series1, hidden, "primary")
    series2 = visible_series(series2, hidden, "secondary")
    if not series1 and not series2:
        canvas.create_text(width / 2, height / 2, text=t("bench.all_lines_hidden"),
                            fill="#888888")
        _bind_chart_hover(canvas, [], t, fg_color, bg_color, width, height)
        _bind_pin_menu(canvas, [], on_pin_menu, on_color_menu)
        return

    has_secondary = bool(series2)
    # pad_top holds the legend and, below it, the axis titles above the topmost tick.
    pad_top, pad_bottom = 40, 40

    all_xs = series_xs(series1, series2)
    x_min, x_max = x_view if x_view is not None else (min(all_xs), max(all_xs))
    if x_min == x_max:
        x_min -= 1
        x_max += 1
    full1 = y_scale(series1, log_y, pins1) if series1 else None
    full2 = y_scale(series2, log_y, pins2) if has_secondary else None
    scale1 = full1.zoomed(y_view) if full1 else None
    scale2 = full2.zoomed(y_view) if full2 else None

    # pad_left/pad_right are measured from the actual tick label strings with the real
    # font: throughput reaches 10-13 digit n/s figures, which a fixed pad would clip.
    tick_font = tkfont.Font(family="Consolas", size=8)

    def _max_tick_label_width(scale, fmt):
        return max((tick_font.measure(scale.tick_label(v, fmt)) for v in scale.ticks()),
                   default=0)

    pad_left = max(50, _max_tick_label_width(scale1, fmt1) + 24) if scale1 else 24
    pad_right = max(50, _max_tick_label_width(scale2, fmt2) + 28) if scale2 else 24

    plot_w = max(1, width - pad_left - pad_right)
    plot_h = max(1, height - pad_top - pad_bottom)

    # Same horizontal inset as chart_pdf.chart_ops(): edge points stay off the y-axes.
    inset_x = max(15.0, plot_w * 0.05)

    def sx(x):
        return pad_left + inset_x + (x - x_min) / (x_max - x_min) * (plot_w - 2 * inset_x)

    canvas.chart_geometry = (pad_left + inset_x, plot_w - 2 * inset_x, x_min, x_max,
                             pad_top, plot_h, y_view,
                             chart_view.data_fracs((full1, series1), (full2, series2)),
                             (min(all_xs), max(all_xs)))
    # A zoomed axis ticks the whole floors across the plot, insets included.
    margin = inset_x / max(1.0, plot_w - 2 * inset_x) * (x_max - x_min)
    x_ticks = all_xs if x_view is None else chart_view.tick_floors(x_min, x_max, margin)

    def on_plot(x_px):
        return pad_left <= x_px <= pad_left + plot_w

    def sy(scale, y):
        return pad_top + plot_h - scale.frac(y) * plot_h

    # Horizontal guides at the left-axis ticks, half way between background and axis color.
    guide_color = _mix(bg_color, grid_color)
    if scale1:
        for y_val in scale1.ticks():
            canvas.create_line(pad_left, sy(scale1, y_val), pad_left + plot_w, sy(scale1, y_val),
                                fill=guide_color)
    canvas.create_line(pad_left, pad_top, pad_left, pad_top + plot_h, fill=grid_color)
    canvas.create_line(pad_left, pad_top + plot_h, pad_left + plot_w, pad_top + plot_h,
                        fill=grid_color)
    if has_secondary:
        canvas.create_line(pad_left + plot_w, pad_top, pad_left + plot_w, pad_top + plot_h,
                            fill=grid_color)

    if scale1:
        for y_val in scale1.ticks():
            y_px = sy(scale1, y_val)
            canvas.create_line(pad_left - 4, y_px, pad_left, y_px, fill=grid_color)
            canvas.create_text(pad_left - 8, y_px, text=scale1.tick_label(y_val, fmt1),
                                anchor="e", font=("Consolas", 8), fill=fg_color)
    if scale2:
        for y_val in scale2.ticks():
            y_px = sy(scale2, y_val)
            canvas.create_line(pad_left + plot_w, y_px, pad_left + plot_w + 4, y_px,
                                fill=grid_color)
            canvas.create_text(pad_left + plot_w + 8, y_px, text=scale2.tick_label(y_val, fmt2),
                                anchor="w", font=("Consolas", 8), fill=fg_color)

    for x_val in x_ticks:
        x_px = sx(x_val)
        canvas.create_line(x_px, pad_top + plot_h, x_px, pad_top + plot_h + 4, fill=grid_color)
        canvas.create_text(x_px, pad_top + plot_h + 8, text=chart_points.x_label(x_val, x_mode),
                            anchor="n", font=("Consolas", 8), fill=fg_color)

    canvas.create_text(pad_left + plot_w / 2, height - 8,
                        text=t(chart_points.AXIS_TITLE_KEYS[x_mode]),
                        font=("Consolas", 8, "bold"), fill=fg_color)
    def pinned(pins):
        return (" [" + t("bench.axis_pinned") + "]"
                if any(v is not None for v in pins or ()) else "")

    # Axis titles sit in the strip above the plot area, anchored by their bottom edge so
    # the gap above the topmost tick does not depend on font metrics.
    if series1:
        canvas.create_text(4, pad_top - 10, text="\u25cf " + t(label_key1) + pinned(pins1),
                            anchor="sw", font=("Consolas", 8, "bold"), fill=fg_color)
    if has_secondary:
        canvas.create_text(width - 4, pad_top - 10,
                            text=t(label_key2) + pinned(pins2) + " \u25a0", anchor="se",
                            font=("Consolas", 8, "bold"), fill=fg_color)

    # Values show in one hover tooltip (_bind_chart_hover): permanent per-point labels
    # overlap into an unreadable smear on dense series.
    hover_points = []

    marks = marks or set()

    def draw(series, scale, fmt, label_key, secondary=False):
        r = 4
        axis = "secondary" if secondary else "primary"
        for s in series:
            pts = [(x, y) for x, y in s.points if scale.usable(y)]
            for run in clip_polyline([(sx(x), scale.frac(y)) for x, y in pts],
                                     pad_left, pad_left + plot_w):
                if len(run) > 1:
                    coords = [(x, pad_top + plot_h - f * plot_h) for x, f in run]
                    canvas.create_line(*[c for xy in coords for c in xy], fill=s.color,
                                        width=1 if secondary else 3,
                                        dash=(5, 3) if s.dashed else None)
            pts = [(x, y) for x, y in pts if in_view(scale.frac(y)) and on_plot(sx(x))]
            coords = [(sx(x), sy(scale, y)) for x, y in pts]
            for (x_val, y_val), (cx, cy) in zip(pts, coords):
                if secondary:
                    canvas.create_rectangle(cx - r, cy - r, cx + r, cy + r, outline=s.color,
                                             width=0, fill=s.color)
                else:
                    canvas.create_oval(cx - r, cy - r, cx + r, cy + r, outline=s.color,
                                        width=2 if s.dashed else 0,
                                        fill=bg_color if s.dashed else s.color)
                if (axis, s.name, x_val, y_val) in marks:
                    canvas.create_oval(cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4,
                                       outline=fg_color, width=2, tags="selected_mark")
                hover_points.append((cx, cy, x_val, y_val,
                                     point_label(fmt, y_val, s, show_unknown=True, x=x_val)
                                     .replace("{", "{{").replace("}", "}}"),
                                     s.color, label_key,
                                     "secondary" if secondary else "primary"))

    if scale1:
        draw(series1, scale1, fmt1, label_key1)
    if scale2:
        draw(series2, scale2, fmt2, label_key2, secondary=True)

    _bind_chart_hover(canvas, hover_points, t, fg_color, bg_color, width, height, x_mode)
    _bind_pin_menu(canvas, hover_points, on_pin_menu, on_color_menu)


def _legend_series_at(canvas, x, y):
    """The Series of the legend item at (x, y), None off the legend."""
    for item in reversed(canvas.find_overlapping(x, y, x, y)):
        for tag in canvas.gettags(item):
            if tag in getattr(canvas, "legend_series", {}):
                return canvas.legend_series[tag]
    return None


def _bind_pin_menu(canvas, hover_points, on_pin_menu, on_color_menu=None):
    """Right-click on the canvas: on_color_menu(series, x_root, y_root) on an engine's
    legend entry, else on_pin_menu((axis, value, value text) of the point under the pointer,
    or None off every point, x_root, y_root). Rebound on every redraw, like
    _bind_chart_hover."""
    if on_pin_menu is None:
        return

    def _on_right_click(event):
        series = _legend_series_at(canvas, event.x, event.y)
        if on_color_menu is not None and series is not None and not series.dashed:
            on_color_menu(series, event.x_root, event.y_root)
            return
        point = _nearest_point(hover_points, event.x, event.y)
        target = (point[7], point[3], point[4].format(point[3])) if point else None
        on_pin_menu(target, event.x_root, event.y_root)

    canvas.bind("<Button-3>", _on_right_click)


class BenchmarkTab(BenchmarkExport, BenchmarkFilter, BenchmarkLineColors, BenchmarkPoints,
                   BenchmarkRamChart, BenchmarkChartZoom, BenchmarkChartWindows,
                   BenchmarkViewState, BaseTab):
    def __init__(self, parent, get_portal_folder, status_var, translator, update_nav_controls,
                 theme_palette):
        """
        theme_palette: the CURRENT theme's color dict (primeatlas.core.theme.palette_for()'s
        return value, e.g. {"fg": ..., "tree_group_bg": ..., "tree_stat_bg": ..., ...}),
        passed in explicitly rather than read from a bare global -- same dependency-
        injection reasoning as every other constructor parameter here. Needed because
        this tab's own tree "floor"/"stat" row-highlight tags (see _build_widgets'
        own tag_configure calls) are a per-item ttk.Treeview override that
        PortalBrowserApp._apply_theme()'s ttk.Style() calls can never reach -- see
        primeatlas/core/theme.py's own docstring on tree_group_bg/tree_stat_bg for the bug
        this fixes (light-hardcoded row highlights were unreadable in dark mode)."""
        super().__init__(parent, translator)
        self._get_portal_folder = get_portal_folder
        self.status = status_var
        self._update_nav_controls = update_nav_controls
        self._theme_palette = theme_palette
        self._init_points()
        self._init_filter()
        self._init_chart_windows()
        self._init_chart_zoom()

        self._build_widgets()
        self._load_view()

    def _build_widgets(self):
        T = self.T

        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=4)
        # "Points of different widths on floor N" under each chart, set by its redraw.
        self.mixed_widths_vars = {"run": tk.StringVar(), "sieve": tk.StringVar(),
                                  "ram": tk.StringVar()}
        # Chart view toggles; every export follows them, the lines hidden from each chart's
        # legend ({chart: set of line_key()}, kept across restarts: benchmark_view_state.py)
        # and the pinned y-axis bounds ({chart: {axis: (min, max)}}, set from the
        # right-click menu, kept for the session).
        self._hidden_lines = {"run": set(), "sieve": set(), "ram": set()}
        self._y_pins = {"run": {}, "sieve": {}, "ram": {}}
        self.log_scale_var = tk.BooleanVar(value=False)
        self.references_var = tk.BooleanVar(value=False)
        remember("benchmark.log_scale", self.log_scale_var)
        remember("benchmark.show_references", self.references_var)
        # The toggles are packed first: when the row is too narrow, pack cuts the filter
        # summary packed after them, not the toggles.
        ttk.Checkbutton(top, text=T("bench.log_scale"), variable=self.log_scale_var,
                        command=self._redraw_charts).pack(side="right")
        ttk.Checkbutton(top, text=T("bench.show_references"), variable=self.references_var,
                        command=self._redraw_charts).pack(side="right", padx=(0, 8))
        ttk.Button(top, text=T("common.refresh"), command=self.reload_benchmark_log).pack(side="left")
        self._build_export_controls(top)
        ttk.Button(top, text=T("bench.filter_button"), command=self._open_filter_window).pack(
            side="left", padx=(6, 0))
        ttk.Label(top, textvariable=self.filter_summary_var, style="Status.TLabel").pack(
            side="left", padx=(6, 12))

        # The charts stand one under another, full width: the sieve, the whole run (sieve
        # + write), RAM. Canvas colors come from the CURRENT theme (console_bg/border, the
        # keys the app's other canvas-like widgets use) so the dark theme does not keep a
        # light chart; _draw_growth_chart's bg_color/fg_color/grid_color (passed by
        # _draw_chart below) keep ticks and axis titles readable on it. Each chart is
        # always shown: _draw_growth_chart() draws a "no data yet" placeholder when its
        # series are empty. A mixed-width note is packed under its chart only while it
        # has text, so an empty one takes no height.
        p = self._theme_palette
        self._mixed_widths_labels = {}
        chart_frame2 = self._chart_frame("sieve")
        self.benchmark_chart2 = tk.Canvas(chart_frame2, height=220, background=p["console_bg"],
                                           highlightthickness=1, highlightbackground=p["border"])
        self.benchmark_chart2.pack(fill="x")
        self.benchmark_chart2.bind("<Configure>", lambda _e: self._redraw_benchmark_chart2())
        self._bind_chart_zoom(self.benchmark_chart2, "sieve")
        self._mixed_widths_labels["sieve"] = (
            ttk.Label(chart_frame2, style="Status.TLabel",
                      textvariable=self.mixed_widths_vars["sieve"]), self.benchmark_chart2)

        chart_frame = self._chart_frame("run")
        self.benchmark_chart = tk.Canvas(chart_frame, height=180, background=p["console_bg"],
                                          highlightthickness=1, highlightbackground=p["border"])
        self.benchmark_chart.pack(fill="x")
        self.benchmark_chart.bind("<Configure>", lambda _e: self._redraw_benchmark_chart())
        self._bind_chart_zoom(self.benchmark_chart, "run")
        self._mixed_widths_labels["run"] = (
            ttk.Label(chart_frame, style="Status.TLabel",
                      textvariable=self.mixed_widths_vars["run"]), self.benchmark_chart)

        self._build_ram_chart(self._chart_frame("ram"))

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=6, pady=4)

        # Floor pagination -- ABOVE the tree, same Prev/label/Next/goto layout as the
        # "Prime numbers" tab's floor nav (see that tab's own _build_primes_tab for the
        # full rationale). benchmark_log.csv gets a row per orchestrator run
        # (including cheap, repeatable count-only benchmarking runs -- see the
        # write_files toggle), so a floor can accumulate dozens-to-hundreds of rows;
        # expanding a floor only lists/groups rows already in memory (cheap -- the
        # whole CSV is small text) and INSERTS one page's worth of Treeview rows at a
        # time (inserting all of them is what would freeze the GUI).
        benchmark_nav = ttk.Frame(tree_frame)
        benchmark_nav.pack(fill="x", pady=(0, 4))
        self.benchmark_prev_btn = ttk.Button(
            benchmark_nav, text=T("common.prev_page"), command=self._prev_benchmark_page,
            state="disabled")
        self.benchmark_prev_btn.pack(side="left")
        self.benchmark_page_label = tk.StringVar(value="")
        ttk.Label(benchmark_nav, textvariable=self.benchmark_page_label, width=16,
                  anchor="center").pack(side="left")
        self.benchmark_next_btn = ttk.Button(
            benchmark_nav, text=T("common.next_page"), command=self._next_benchmark_page,
            state="disabled")
        self.benchmark_next_btn.pack(side="left")
        ttk.Label(benchmark_nav, text=T("common.page_prefix")).pack(side="left", padx=(10, 0))
        self.benchmark_goto_entry = ttk.Entry(benchmark_nav, width=6)
        self.benchmark_goto_entry.pack(side="left", padx=(4, 0))
        self.benchmark_goto_entry.bind("<Return>", lambda _e: self._goto_benchmark_page())
        ttk.Button(benchmark_nav, text=T("common.goto"), command=self._goto_benchmark_page).pack(
            side="left", padx=(4, 0))

        # height is the tree's height when the page has to scroll, as it does under the three
        # stacked charts at the default 1050x680; while the page fits, pack(expand=True)
        # gives it the rest of the window.
        self.benchmark_tree = StripedTreeview(tree_frame, show="tree headings", height=10)
        self.benchmark_tree.heading("#0", text=T("bench.col_floor"))
        self.benchmark_tree.column("#0", width=170, stretch=False)
        # Horizontal scrollbar -- with 11 data columns + #0, the row is wider than the
        # tab, and without this the only way to see the columns off the right edge was
        # shrinking every column's width by hand. stretch=False on every column (set
        # below, in reload_benchmark_log()) keeps each column at its given width instead
        # of Tk auto-stretching the last one to fill the widget, which is what makes the
        # row properly wider than the view and the scrollbar actually needed/usable.
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.benchmark_tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.benchmark_tree.xview)
        self.benchmark_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self.benchmark_tree.pack(side="left", fill="both", expand=True)

        # Explicit foreground alongside each background -- a tag's own colors
        # override the base "Treeview" ttk.Style() colors per-row (see this
        # constructor's own docstring), so without pairing them here, dark mode
        # would keep the (light) style-level foreground on top of these
        # theme-appropriate backgrounds and still be unreadable.
        p = self._theme_palette
        self.benchmark_tree.tag_configure("floor", background=p["tree_group_bg"], foreground=p["fg"])
        self.benchmark_tree.tag_configure("stat", background=p["tree_stat_bg"], foreground=p["fg"])

        self.benchmark_tree.bind("<<TreeviewOpen>>", self._on_benchmark_tree_open)
        self.benchmark_tree.bind("<<TreeviewClose>>", self._on_benchmark_tree_close)
        self.benchmark_tree.bind("<<TreeviewSelect>>", self._on_benchmark_tree_select)
        self._bind_tree_points()

        self._benchmark_growth_points = []
        self._benchmark_fair_spw_points = []  # loop_seconds_per_window, second chart line
        self._benchmark_sieve_nps_points = []   # sieve-phase numbers/s, second CHART's
                                                 # primary line (v4.1 and v5 engine rows
                                                 # only -- see aggregate_benchmark_sieve_nps)
        self._benchmark_write_mbps_points = []  # write-phase MB/s, second chart's
                                                 # secondary line (same v4.1/v5-only caveat)
        self._benchmark_fieldnames = []  # kept in sync by reload_benchmark_log() --
        self._benchmark_rows = []        # _export_benchmark_pdf reads these (the FULL,
                                          # ungrouped data) instead of re-parsing the CSV,
                                          # so the PDF always exports everything, even
                                          # rows not currently paged into view.
        self._benchmark_rows_by_floor = {}   # base_exponent -> [rows...], built by
                                               # reload_benchmark_log() via
                                               # group_benchmark_rows_by_floor()
        self._benchmark_floor_state = {}     # tree item id -> {base_exponent, rows,
                                               # stats, page, total_pages} -- lazily
                                               # populated on <<TreeviewOpen>>, dropped on
                                               # <<TreeviewClose>>, same lifecycle as the
                                               # primes tab's _floor_state.
        self._active_benchmark_node = None    # which floor's page the nav buttons above
                                               # currently operate on

    def _redraw_benchmark_chart(self):
        # Before the window has actually been mapped/laid out by the OS window manager
        # (e.g. the very first draw, triggered from reload_benchmark_log() during
        # __init__), winfo_width()/height() can still report the Tk default of 1x1 --
        # <Configure> will fire and redraw properly once real geometry is assigned, but
        # falling back to a reasonable size here means the chart doesn't sit blank in
        # the meantime.
        self._show_mixed_widths("run", ("growth", "write"))
        self._draw_chart("run", self.benchmark_chart, self._benchmark_growth_points, (900, 180),
                         points2=self._benchmark_write_mbps_points,
                         label_key1="bench.axis_total_nps",
                         label_key2="bench.axis_write_mbps", fmt2="{:,.1f}",
                         series1=self._chart_series("growth"),
                         series2=self._chart_series("write"),
                         marks=self._chart_marks("growth", "write"))

    def _draw_chart(self, chart, canvas, points, default_size, **kwargs):
        """_draw_growth_chart() on `canvas` and on the chart's open window
        (benchmark_chart_windows.py) with the view state of `chart` ("run", "sieve", "ram"):
        log scale, hidden lines, pinned axes, the zoomed floor range, theme colors;
        `default_size` (width, height) stands in while a canvas is not laid out yet."""
        p = self._theme_palette
        for target in [canvas] + self._chart_window_canvases(chart):
            width, height = target.winfo_width(), target.winfo_height()
            width = default_size[0] if width <= 1 else width
            height = default_size[1] if height <= 1 else height
            _draw_growth_chart(target, points, width, height, translator=self.T,
                               log_y=self.log_scale_var.get(), hidden=self._hidden_lines[chart],
                               on_toggle=lambda keys: self._toggle_lines(chart, keys),
                               pins1=axis_pins(self._y_pins[chart], "primary"),
                               pins2=axis_pins(self._y_pins[chart], "secondary"),
                               on_pin_menu=lambda *a: self._on_pin_menu(chart, *a),
                               on_color_menu=self._on_color_menu,
                               bg_color=p["console_bg"], fg_color=p["console_fg"],
                               grid_color=p["border"], x_view=self._x_view,
                               y_view=self._y_views[chart], x_mode=self._x_mode, **kwargs)

    def _chart_series(self, metric, references=False):
        """One Series per engine for a chart metric; with references=True, the reference
        lines too while the "Reference points" toggle is on. PARI/GP writes nothing, so the
        references go on the sieve chart."""
        series = benchmark_series(self._filtered_rows(), metric, self._metric_view(metric))
        if references and self.references_var.get():
            series += reference_series(self.T)
        return series

    def _toggle_lines(self, chart, keys):
        """Legend click on the "run", "sieve" or "ram" chart: hides or shows those lines."""
        self._hidden_lines[chart] = toggle_lines(self._hidden_lines[chart], keys)
        self._save_view()
        self._redraw_chart(chart)

    def _redraw_chart(self, chart):
        if chart == "run":
            self._redraw_benchmark_chart()
        elif chart == "ram":
            self._redraw_benchmark_chart3()
        else:
            self._redraw_benchmark_chart2()

    def _redraw_charts(self):
        self._redraw_benchmark_chart()
        self._redraw_benchmark_chart2()
        self._redraw_benchmark_chart3()

    def _show_mixed_widths(self, chart, metrics):
        floors = sorted({f for m in metrics
                         for f in mixed_width_floors(self._filtered_rows(), m,
                                                     self._metric_view(m))
                         if chart_view.contains(self._x_view, f)})
        notes = [self.T("bench.mixed_widths", floors=", ".join(map(str, floors)))] if floors else []
        notes += [note for note in (self._unplaced_note(metrics),) if note]
        self.mixed_widths_vars[chart].set("  |  ".join(notes))
        label, canvas = self._mixed_widths_labels[chart]
        if notes:
            label.pack(anchor="w", after=canvas)
        else:
            label.pack_forget()

    def _set_pins(self, chart, pins):
        self._y_pins[chart] = pins
        self._redraw_chart(chart)

    def _pin_menu_entries(self, chart, target):
        """[(label, command, enabled) or None for a separator] of the right-click menu: the
        chart's point choices (_point_menu_entries()), the axis toggles
        (_axis_menu_entries()), a point's pins, the three resets;
        target: see _draw_growth_chart's on_pin_menu. A point offers its value as its axis'
        max or min; a reset is enabled while its axis has a pin."""
        T, pins = self.T, self._y_pins[chart]
        entries = (self._point_menu_entries(chart) + [None]
                   + self._axis_menu_entries(chart) + [None])
        if target:
            axis, value, text = target
            for which in ("max", "min"):
                entries.append((T("bench.pin_" + which, value=text),
                                lambda w=which, a=axis: self._set_pins(
                                    chart, pin_bound(self._y_pins[chart], a, w, value)),
                                True))
            entries.append(None)
        for axis in ("primary", "secondary"):
            entries.append((T("bench.pin_reset_" + axis),
                            lambda a=axis: self._set_pins(
                                chart, clear_pins(self._y_pins[chart], a)),
                            axis in pins))
        entries.append((T("bench.pin_reset_chart"), lambda: self._set_pins(chart, {}),
                        bool(pins)))
        return entries

    def _on_pin_menu(self, chart, target, x_root, y_root):
        self._post_menu(self._pin_menu_entries(chart, target), x_root, y_root)

    def _post_menu(self, entries, x_root, y_root):
        menu = tk.Menu(self, tearoff=False)
        for entry in entries:
            if entry is None:
                menu.add_separator()
                continue
            label, command, enabled = entry
            menu.add_command(label=label, command=command,
                             state="normal" if enabled else "disabled")
        try:
            menu.tk_popup(x_root, y_root)
        finally:
            menu.grab_release()

    def _redraw_benchmark_chart2(self):
        """Same fallback-size handling as _redraw_benchmark_chart() (see that method's own
        comment) -- draws the sieve chart of the Filter window's sieve measure
        (sieve_measure.chart(): n/s and s/window, with reference points, or the startup
        overhead) onto its own canvas, the top one, above the whole-run chart."""
        spec = sieve_measure.chart(self._sieve_measure)
        self._show_mixed_widths("sieve", (spec.metric1, spec.metric2))
        self._draw_chart("sieve", self.benchmark_chart2, self._benchmark_sieve_nps_points,
                         (900, 220), label_key1=spec.label_key1, label_key2=spec.label_key2,
                         fmt1=spec.fmt1, fmt2=spec.fmt2,
                         series1=self._chart_series(spec.metric1, spec.references),
                         series2=self._chart_series(spec.metric2),
                         marks=self._chart_marks(spec.metric1, spec.metric2))

    def reload_benchmark_log(self):
        fieldnames, rows = read_benchmark_log(self._get_portal_folder())
        self._benchmark_fieldnames = fieldnames  # FULL list -- PDF export/growth chart
                                                   # still use every column, unaffected
                                                   # by what the tree itself displays
        self._benchmark_rows = rows
        self._prune_filter()

        self._benchmark_growth_points = aggregate_benchmark_growth(rows)
        self._benchmark_fair_spw_points = aggregate_benchmark_fair_spw(rows)
        self._redraw_benchmark_chart()

        self._benchmark_sieve_nps_points = aggregate_benchmark_sieve_nps(rows)
        self._benchmark_write_mbps_points = aggregate_benchmark_write_mbps(rows)
        self._redraw_benchmark_chart2()
        self._redraw_benchmark_chart3()

        self.benchmark_tree.delete(*self.benchmark_tree.get_children())
        self.benchmark_tree["columns"] = table_columns.TREE_COLUMNS
        for col in table_columns.TREE_COLUMNS:
            self.benchmark_tree.heading(col, text=self.T(table_columns.header_key(col)))
            self.benchmark_tree.column(
                col, width=table_columns.WIDTHS.get(col, table_columns.DEFAULT_WIDTH),
                anchor="center", stretch=False)
        self._rebuild_benchmark_tree()

    def _rebuild_benchmark_tree(self):
        """Lists the runs the Filter window keeps (_filtered_rows()), grouped per floor; a
        floor with no kept run is left out. Called on reload and on every filter change, which
        keeps the columns and their widths."""
        T = self.T
        fieldnames = self._benchmark_fieldnames
        self._benchmark_rows_by_floor = group_benchmark_rows_by_floor(self._filtered_rows())
        self.benchmark_tree.delete(*self.benchmark_tree.get_children())
        self._tree_item_rows = {}
        self._benchmark_floor_state = {}
        self._active_benchmark_node = None
        self._refresh_benchmark_nav_controls()

        tree_fieldnames = table_columns.TREE_COLUMNS
        if not fieldnames or not self._benchmark_rows:
            self.benchmark_tree.insert("", "end", text=T("bench.no_data_row"))
            return
        if not self._benchmark_rows_by_floor:
            self.benchmark_tree.insert("", "end", text=T("bench.filter_no_rows"))
            return

        for base_exponent in sorted(self._benchmark_rows_by_floor):
            count = len(self._benchmark_rows_by_floor[base_exponent])
            node = self.benchmark_tree.insert(
                "", "end", text=T("bench.floor_measurements", base_exponent=base_exponent, count=count),
                values=["" for _ in tree_fieldnames], open=False, tags=("floor",))
            self.benchmark_tree.insert(node, "end", text=T("common.loading"))

    def _on_benchmark_tree_open(self, _event):
        node = self.benchmark_tree.focus()
        self._populate_benchmark_floor_node(node)
        self._set_active_benchmark_node(node)

    def _on_benchmark_tree_close(self, _event):
        """Same lifecycle as the primes tab's _on_tree_close(): collapsing a floor drops
        its row/page state and resets to a single "(loading...)" placeholder, so a floor
        that's never re-expanded doesn't hold onto its (already in-memory, but still
        worth not duplicating into tree-item state) rows indefinitely."""
        node = self.benchmark_tree.focus()
        if node not in self._benchmark_floor_state:
            return
        del self._benchmark_floor_state[node]
        self.benchmark_tree.delete(*self.benchmark_tree.get_children(node))
        self.benchmark_tree.insert(node, "end", text=self.T("common.loading"))
        if self._active_benchmark_node == node:
            self._active_benchmark_node = None
            self._refresh_benchmark_nav_controls()

    def _on_benchmark_tree_select(self, _event):
        """Clicking a floor header (whether just opened or already expanded) makes it
        the target of the pagination controls above the tree -- same behavior as the
        primes tab's floor nav. The selected row scrolls to the top, under the headings,
        once the click or key that selected it has been handled."""
        selection = self.benchmark_tree.selection()
        if not selection:
            return
        item = selection[0]
        self.benchmark_tree.after_idle(self.benchmark_tree.scroll_to_top, item)
        if "floor" in self.benchmark_tree.item(item, "tags"):
            self._set_active_benchmark_node(item)
        else:
            self._on_tree_row_selected(item)

    def _populate_benchmark_floor_node(self, node):
        if node in self._benchmark_floor_state:
            return  # already prepared this session -- nothing to redo
        children = self.benchmark_tree.get_children(node)
        if len(children) == 1 and self.benchmark_tree.item(children[0], "text") == self.T("common.loading"):
            self.benchmark_tree.delete(children[0])

        text = self.benchmark_tree.item(node, "text")  # "10p{N} (M measurement(s))"
        base_exponent = int(text[3:].split(" ", 1)[0])
        rows = self._benchmark_rows_by_floor.get(base_exponent, [])
        stats = table_columns.stats(rows)
        total_pages = max(1, (len(rows) + BENCHMARK_PAGE_SIZE - 1) // BENCHMARK_PAGE_SIZE)
        self._benchmark_floor_state[node] = {
            "base_exponent": base_exponent,
            "rows": rows,
            "stats": stats,
            "page": 0,
            "total_pages": total_pages,
        }
        self._show_benchmark_page(node, 0)

    def _show_benchmark_page(self, node, page):
        """Renders page `page` (0-indexed) of a floor's benchmark rows, PLUS a
        standalone stats row at the top (min/avg/max seconds_per_window across ALL of
        that floor's rows, not just the current page -- re-inserted on every page turn,
        which costs nothing since it's a single row) -- see table_columns.stats()."""
        T = self.T
        state = self._benchmark_floor_state.get(node)
        if not state:
            return
        total_pages = state["total_pages"]
        page = max(0, min(page, total_pages - 1))
        state["page"] = page

        for item in self.benchmark_tree.get_children(node):
            self._tree_item_rows.pop(item, None)
        self.benchmark_tree.delete(*self.benchmark_tree.get_children(node))
        fieldnames = table_columns.TREE_COLUMNS

        stats = state["stats"]
        stat_values = ["" for _ in fieldnames]
        if stats and "seconds_per_window" in fieldnames:
            idx = fieldnames.index("seconds_per_window")
            stat_values[idx] = T("bench.stat_summary", avg=f"{stats['avg']:.4f}",
                                  min=f"{stats['min']:.4f}", max=f"{stats['max']:.4f}")
            stat_text = T("bench.stat_row_label", count=stats['count'])
        else:
            stat_text = T("bench.stat_no_data")
        self.benchmark_tree.insert(node, "end", text=stat_text, values=stat_values,
                                    tags=("stat",))

        rows = state["rows"]
        start = page * BENCHMARK_PAGE_SIZE
        end = min(start + BENCHMARK_PAGE_SIZE, len(rows))
        for row in rows[start:end]:
            # #0 names the run by its timestamp; the engine has its own column.
            label = row.get("run_timestamp_utc", "")
            values = [table_columns.shown(row, c, T) for c in fieldnames]
            item = self.benchmark_tree.insert(node, "end", text=label, values=values,
                                              tags=("row",))
            self._remember_tree_row(item, row)

        if self._active_benchmark_node == node:
            self._refresh_benchmark_nav_controls()

    def _set_active_benchmark_node(self, node):
        self._active_benchmark_node = node
        self._refresh_benchmark_nav_controls()

    def _refresh_benchmark_nav_controls(self):
        node = self._active_benchmark_node
        state = self._benchmark_floor_state.get(node) if node is not None else None
        if not state:
            self.benchmark_page_label.set("")
            self.benchmark_prev_btn.configure(state="disabled")
            self.benchmark_next_btn.configure(state="disabled")
            return
        self._update_nav_controls(self.benchmark_page_label, state["page"], state["total_pages"],
                                   self.benchmark_prev_btn, self.benchmark_next_btn)

    def _prev_benchmark_page(self):
        node = self._active_benchmark_node
        if node is not None and self._benchmark_floor_state.get(node):
            self._show_benchmark_page(node, self._benchmark_floor_state[node]["page"] - 1)

    def _next_benchmark_page(self):
        node = self._active_benchmark_node
        if node is not None and self._benchmark_floor_state.get(node):
            self._show_benchmark_page(node, self._benchmark_floor_state[node]["page"] + 1)

    def _goto_benchmark_page(self):
        raw = self.benchmark_goto_entry.get().strip()
        if not raw.isdigit():
            return
        node = self._active_benchmark_node
        if node is not None and self._benchmark_floor_state.get(node):
            self._show_benchmark_page(node, int(raw) - 1)
