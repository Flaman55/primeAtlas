"""The Benchmark charts drawn on a tk.Canvas: axes, ticks, lines, points, the legend along the
top edge and the right-click pin and color menus' bindings. BenchmarkTab (benchmark_tab.py) and
the chart windows (benchmark_chart_windows.py) draw through _draw_growth_chart(); the hover
tooltip is chart_hover.py, the PDF counterpart chart_pdf.py.
"""
import re

from tkinter import font as tkfont

from ..core.i18n import Translator, DEFAULT_LANGUAGE
from .chart_series import (
    clip_polyline, in_view, legend_entries, line_key, marker_state, plain_series, point_label,
    run_key, series_xs, visible_series, y_scale,
)
from . import chart_points, chart_view
from .chart_hover import _bind_chart_hover, _nearest_point

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
    square: right axis) and the name. With on_toggle, a marker click flips that run's line
    on its axis and a name click the whole run: on_toggle([key]). A marker is filled while
    the run keeps its line on that axis and hollow when it does not; it is dim while the
    line is not drawn (its axis or its run hidden). A hidden run's name is dim.
    canvas.legend_series maps each item's tag to its Series for the right-click
    (_bind_pin_menu)."""
    font = ("Consolas", 8, "bold")
    r, y = 4, 10
    for s, axes in entries:
        for axis in axes:
            on, drawn = marker_state(hidden, axis, s.name)
            tag = _legend_tag(axis, s.name)
            canvas.legend_series[tag] = s
            # The background box widens the click target beyond the 8 px marker.
            canvas.create_rectangle(x, y - 8, x + 14, y + 8, fill=bg_color, outline="",
                                    tags=("legend", tag))
            color = s.color if drawn else dim_color
            fill = color if on and not s.dashed else bg_color
            shape = canvas.create_rectangle if axis == "secondary" else canvas.create_oval
            shape(x + 7 - r, y - r, x + 7 + r, y + r, outline=color, fill=fill,
                  width=0 if on and not s.dashed else 2, tags=("legend", tag))
            if on_toggle:
                canvas.tag_bind(tag, "<Button-1>",
                                lambda _e, k=line_key(axis, s.name): on_toggle([k]))
            x += 14
        tag = _legend_tag("name", s.name)
        canvas.legend_series[tag] = s
        text_id = canvas.create_text(x + 3, y, text=s.name, anchor="w", font=font,
                                     fill=dim_color if run_key(s.name) in (hidden or ())
                                     else s.color, tags=("legend", tag))
        if on_toggle:
            canvas.tag_bind(tag, "<Button-1>", lambda _e, k=run_key(s.name): on_toggle([k]))
        bbox = canvas.bbox(text_id)
        x = (bbox[2] if bbox else x + 60) + 16
    if on_toggle:
        canvas.tag_bind("legend", "<Enter>", lambda _e: canvas.configure(cursor="hand2"))
        canvas.tag_bind("legend", "<Leave>", lambda _e: canvas.configure(cursor=""))


def _draw_growth_chart(canvas, points, width, height, points2=None, translator=None,
                        label_key1="bench.axis_nps", label_key2="bench.axis_spw",
                        places1=0, places2=3,
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
    each along the top edge (_draw_legend); a point's exact value and series tag show in a
    hover tooltip, while a linear axis' ticks from a million up are short ("1.18 G").

    hidden: set of chart_series.line_key() left out of the plot and its scales; their
    legend markers stay, so on_toggle (the legend's click callback) can bring them back.

    pins1/pins2: the axes' pinned (min, max) (chart_series.axis_pins()): a pinned bound is
    the axis edge exactly, lines are cut there and the points beyond it are not drawn; the
    axis title says "pinned". on_pin_menu(target, x_root, y_root): right-click callback,
    target = (axis, value, value text) of the point under the pointer or None.
    on_color_menu(series, x_root, y_root): right-click on an engine's legend entry instead.

    label_key1/label_key2/places1/places2: same meaning as chart_pdf.chart_ops()'s parameters, so
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

    # Tick texts are short from a million up (number_format.compact()); pad_left/pad_right
    # are measured from them with the real font, so no tick is clipped.
    tick_font = tkfont.Font(family="Consolas", size=8)

    def _max_tick_label_width(scale, places):
        return max((tick_font.measure(scale.tick_label(v, places, short=True))
                    for v in scale.ticks()), default=0)

    pad_left = max(50, _max_tick_label_width(scale1, places1) + 24) if scale1 else 24
    pad_right = max(50, _max_tick_label_width(scale2, places2) + 28) if scale2 else 24

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
            canvas.create_text(pad_left - 8, y_px, text=scale1.tick_label(y_val, places1, short=True),
                                anchor="e", font=("Consolas", 8), fill=fg_color)
    if scale2:
        for y_val in scale2.ticks():
            y_px = sy(scale2, y_val)
            canvas.create_line(pad_left + plot_w, y_px, pad_left + plot_w + 4, y_px,
                                fill=grid_color)
            canvas.create_text(pad_left + plot_w + 8, y_px, text=scale2.tick_label(y_val, places2, short=True),
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

    def draw(series, scale, places, label_key, secondary=False):
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
                                     point_label(places, y_val, s, show_unknown=True, x=x_val),
                                     s.color, label_key,
                                     "secondary" if secondary else "primary"))

    if scale1:
        draw(series1, scale1, places1, label_key1)
    if scale2:
        draw(series2, scale2, places2, label_key2, secondary=True)

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
        target = (point[7], point[3], point[4]) if point else None
        on_pin_menu(target, event.x_root, event.y_root)

    canvas.bind("<Button-3>", _on_right_click)
