"""PDF content-stream ops for one Benchmark chart: floor on x, Series on one or two y-axes.

The PDF counterpart of benchmark_tab._draw_growth_chart(): same series, scales and point
layout, in PDF's bottom-left-origin point space (tkinter's anchors and y-down canvas have
no PDF equivalent, so the two renderers stay separate and share chart_series.py instead).
Every point carries its value label with the series tag ("1,234 [v5]"); engine "unknown"
gets no tag, since every legacy point would repeat it. Left-axis points are circles on a
thick line, right-axis points squares on a thin line, as on the canvas.
"""
from ..core.i18n import Translator, DEFAULT_LANGUAGE
from ..core.pdf_writer import _pdf_ascii_fold, _pdf_dot_op, _pdf_line_op, _pdf_rect_op, _pdf_text_op
from .chart_series import legend_series, point_label, series_xs, y_scale

_AXIS_GRAY = (0.4, 0.4, 0.4)
_GUIDE_GRAY = (0.88, 0.88, 0.88)


def _rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))


def _dashed(op):
    return "[3 2] 0 d " + op + " [] 0 d"


def chart_ops(x0, y0, w, h, series1=(), series2=(), translator=None,
              label_key1="bench.axis_nps", label_key2="bench.axis_spw",
              fmt1="{:,.0f}", fmt2="{:,.3f}", log_y=False):
    """Ops drawing the chart inside the box [x0, x0+w] x [y0, y0+h].

    series1/series2: [chart_series.Series] on the left (primary) and right (secondary)
    axis; the right axis exists only when series2 has points. Each axis has its own scale
    (chart_series.YScale, log10 when log_y), because the two series differ by orders of
    magnitude. The x ticks are the union of all floors. A legend of named series runs
    along the top edge.

    label_key1/label_key2: i18n keys of the axis titles; fmt1/fmt2: str.format() templates
    of the value labels and linear ticks. Text is ASCII-folded for the PDF base fonts."""
    t = (translator or Translator(DEFAULT_LANGUAGE)).t
    series1 = [s for s in series1 if s.points]
    series2 = [s for s in series2 if s.points]
    ops = [_pdf_rect_op(x0, y0, w, h, stroke_rgb=(0.8, 0.8, 0.8), width=0.5)]
    if not series1 and not series2:
        ops.append(_pdf_text_op(x0 + w / 2 - 60, y0 + h / 2, 10, "Helvetica",
                                 _pdf_ascii_fold(t("bench.no_data_chart"))))
        return ops

    has_secondary = bool(series2)
    pad_left = 55
    pad_right = 55 if has_secondary else 15
    pad_top, pad_bottom = 30, 30
    plot_x0 = x0 + pad_left
    plot_y0 = y0 + pad_bottom
    plot_w = max(1, w - pad_left - pad_right)
    plot_h = max(1, h - pad_top - pad_bottom)

    all_xs = series_xs(series1, series2)
    x_min, x_max = min(all_xs), max(all_xs)
    if x_min == x_max:
        x_min -= 1
        x_max += 1
    scale1 = y_scale(series1, log_y) if series1 else None
    scale2 = y_scale(series2, log_y) if has_secondary else None

    # Horizontal inset keeps the edge points' value labels off the y-axis tick labels.
    inset_x = max(15.0, plot_w * 0.05)

    def sx(x):
        return plot_x0 + inset_x + (x - x_min) / (x_max - x_min) * (plot_w - 2 * inset_x)

    def sy(scale, y):
        return plot_y0 + scale.frac(y) * plot_h

    if scale1:
        for y_val in scale1.ticks():
            ops.append(_pdf_line_op(plot_x0, sy(scale1, y_val), plot_x0 + plot_w,
                                     sy(scale1, y_val), width=0.4, rgb=_GUIDE_GRAY))
    ops.append(_pdf_line_op(plot_x0, plot_y0, plot_x0, plot_y0 + plot_h, rgb=_AXIS_GRAY))
    ops.append(_pdf_line_op(plot_x0, plot_y0, plot_x0 + plot_w, plot_y0, rgb=_AXIS_GRAY))
    if has_secondary:
        ops.append(_pdf_line_op(plot_x0 + plot_w, plot_y0, plot_x0 + plot_w, plot_y0 + plot_h,
                                 rgb=_AXIS_GRAY))

    if scale1:
        for y_val in scale1.ticks():
            y_px = sy(scale1, y_val)
            ops.append(_pdf_line_op(plot_x0 - 3, y_px, plot_x0, y_px, rgb=_AXIS_GRAY))
            ops.append(_pdf_text_op(plot_x0 - 50, y_px - 3, 7, "Courier",
                                     scale1.tick_label(y_val, fmt1)))
    if scale2:
        for y_val in scale2.ticks():
            y_px = sy(scale2, y_val)
            ops.append(_pdf_line_op(plot_x0 + plot_w, y_px, plot_x0 + plot_w + 3, y_px,
                                     rgb=_AXIS_GRAY))
            ops.append(_pdf_text_op(plot_x0 + plot_w + 5, y_px - 3, 7, "Courier",
                                     scale2.tick_label(y_val, fmt2)))

    for x_val in all_xs:
        x_px = sx(x_val)
        ops.append(_pdf_line_op(x_px, plot_y0, x_px, plot_y0 - 3, rgb=_AXIS_GRAY))
        ops.append(_pdf_text_op(x_px - 8, plot_y0 - 14, 7, "Courier", str(x_val)))

    ops.append(_pdf_text_op(plot_x0 + plot_w / 2 - 30, y0 + 4, 8, "Helvetica-Bold",
                             _pdf_ascii_fold(t("bench.axis_floor"))))
    if series1:
        ops.append(_pdf_dot_op(x0 + 4, y0 + h - 7.5, 2.2, rgb=_AXIS_GRAY))
        ops.append(_pdf_text_op(x0 + 9, y0 + h - 10, 8, "Helvetica-Bold",
                                 _pdf_ascii_fold(t(label_key1))))
    if has_secondary:
        ops.append(_pdf_rect_op(x0 + w - 6, y0 + h - 9.5, 4, 4, fill_rgb=_AXIS_GRAY))
        ops.append(_pdf_text_op(x0 + w - 68, y0 + h - 10, 8, "Helvetica-Bold",
                                 _pdf_ascii_fold(t(label_key2))))

    legend_x = x0 + 90
    for s in legend_series(series1, series2):
        rgb = _rgb(s.color)
        line = _pdf_line_op(legend_x - 5, y0 + h - 8, legend_x + 5, y0 + h - 8, width=1.5,
                            rgb=rgb)
        ops.append(_dashed(line) if s.dashed else line)
        ops.append(_pdf_dot_op(legend_x, y0 + h - 8, 2.5, rgb=rgb))
        if s.dashed:
            ops.append(_pdf_dot_op(legend_x, y0 + h - 8, 1.3, rgb=(1, 1, 1)))
        text = _pdf_ascii_fold(s.name)
        ops.append(_pdf_text_op(legend_x + 8, y0 + h - 10.5, 6.5, "Helvetica-Bold", text,
                                 rgb=rgb))
        legend_x += 22 + 6.5 * 0.55 * len(text)

    def draw(series, scale, fmt, label_dy, secondary=False):
        for s in series:
            pts = [(x, y) for x, y in s.points if scale.usable(y)]
            rgb = _rgb(s.color)
            coords = [(sx(x), sy(scale, y)) for x, y in pts]
            for (xa, ya), (xb, yb) in zip(coords, coords[1:]):
                op = _pdf_line_op(xa, ya, xb, yb, width=0.7 if secondary else 1.8, rgb=rgb)
                ops.append(_dashed(op) if s.dashed else op)
            for (x_val, y_val), (cx, cy) in zip(pts, coords):
                if secondary:
                    ops.append(_pdf_rect_op(cx - 2.3, cy - 2.3, 4.6, 4.6, fill_rgb=rgb))
                else:
                    ops.append(_pdf_dot_op(cx, cy, 2.5, rgb=rgb))
                if s.dashed:
                    ops.append(_pdf_dot_op(cx, cy, 1.3, rgb=(1, 1, 1)))
                ops.append(_pdf_text_op(cx - 10, cy + label_dy, 7, "Courier",
                                         _pdf_ascii_fold(point_label(fmt, y_val, s)), rgb=rgb))

    if scale1:
        draw(series1, scale1, fmt1, 8)
    if scale2:
        draw(series2, scale2, fmt2, -14, secondary=True)
    return ops

