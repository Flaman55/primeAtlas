"""
density_chart.py -- Canvas chart of the Density sub-tab: hits / Hardy-Littlewood prediction
per floor for one pattern, with a reference line at 1 and a Poisson error bar of
+-1/sqrt(expected) around each point.

The y axis runs from 0 to the highest bar end, at least 2 and at most Y_CAP; a bar or point
above Y_CAP is drawn at the top edge with an arrow. Floors sit on a linear x axis, so floors
without a row leave a gap.
"""
COLOR_POINT = "#1f77b4"
COLOR_REF = "#c8961e"

Y_CAP = 5.0
"""Top of the y axis at most; arbitrary, keeps one floor with a tiny prediction from
flattening the rest."""

_PAD_LEFT, _PAD_RIGHT, _PAD_TOP, _PAD_BOTTOM = 48, 16, 24, 28
_INSET = 28  # keeps the first and last floor's point and label off the plot edges
_R = 4


def canvas_size(canvas):
    w, h = canvas.winfo_width(), canvas.winfo_height()
    if w < 50:
        w = int(canvas.cget("width"))
    if h < 50:
        h = int(canvas.cget("height"))
    return w, h


def draw_ratio_chart(canvas, points, palette, title, empty_text):
    """points: (floor, ratio, error) tuples, error = 1/sqrt(expected). Clears the canvas and
    draws the title, the axes, the line at 1 (tag 'ref'), the bars ('bar') and the points
    ('point'); with no points only the title and empty_text ('empty')."""
    canvas.delete("all")
    fg, line = palette["console_fg"], palette["border"]
    w, h = canvas_size(canvas)
    canvas.create_text(_PAD_LEFT, 4, text=title, anchor="nw", fill=fg, tags="title")
    if not points:
        canvas.create_text(w / 2, h / 2, text=empty_text, fill=palette["hint_fg"], tags="empty")
        return
    top = min(Y_CAP, max([2.0] + [r + e for _f, r, e in points]))
    floors = [f for f, _r, _e in points]
    lo, hi = min(floors), max(floors)
    plot_w = w - _PAD_LEFT - _PAD_RIGHT
    plot_h = h - _PAD_TOP - _PAD_BOTTOM

    def sx(floor):
        if hi == lo:
            return _PAD_LEFT + plot_w / 2
        return _PAD_LEFT + _INSET + (floor - lo) * (plot_w - 2 * _INSET) / (hi - lo)

    def sy(value):
        return _PAD_TOP + plot_h * (1 - min(value, top) / top)

    canvas.create_line(_PAD_LEFT, _PAD_TOP, _PAD_LEFT, _PAD_TOP + plot_h, fill=line, tags="axis")
    canvas.create_line(_PAD_LEFT, _PAD_TOP + plot_h, _PAD_LEFT + plot_w, _PAD_TOP + plot_h,
                       fill=line, tags="axis")
    for value in (0.0, 1.0, top):
        canvas.create_text(_PAD_LEFT - 6, sy(value), text=f"{value:.3g}", anchor="e", fill=fg,
                           tags="axis")
    canvas.create_line(_PAD_LEFT, sy(1.0), _PAD_LEFT + plot_w, sy(1.0), fill=COLOR_REF,
                       dash=(4, 3), tags="ref")
    for floor in sorted(set(floors)):
        canvas.create_text(sx(floor), _PAD_TOP + plot_h + 6, text=f"10^{floor}", anchor="n",
                           fill=fg, tags="axis")
    for floor, ratio, err in points:
        x = sx(floor)
        clipped = ratio + err > top
        canvas.create_line(x, sy(max(ratio - err, 0.0)), x, sy(ratio + err), fill=COLOR_POINT,
                           arrow="last" if clipped else "none", tags="bar")
        y = sy(ratio)
        canvas.create_oval(x - _R, y - _R, x + _R, y + _R, outline=COLOR_POINT,
                           fill="" if ratio > top else COLOR_POINT, tags="point")
