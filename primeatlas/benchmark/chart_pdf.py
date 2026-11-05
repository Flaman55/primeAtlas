"""PDF content-stream ops for one Benchmark chart: floor on x, Series on one or two y-axes.

The PDF counterpart of benchmark_tab._draw_growth_chart(): same series, scales and point
layout, in PDF's bottom-left-origin point space (tkinter's anchors and y-down canvas have
no PDF equivalent, so the two renderers stay separate and share chart_series.py instead).
A point's value label carries the series tag ("1,234 [v5]"); engine "unknown" gets no
tag, since every legacy point would repeat it. Labels never overlap: each line's last
point is labelled first, stacked away from the point when lines end close together, then
the other points in order, above the point or else below it; such a label with neither
place free is left out (the report's tables hold every value). A label is kept inside
the chart's box, between the x axis and the legend. Left-axis points are circles on a
thick line, right-axis points squares on a thin line, as on the canvas. A pinned axis
(chart_series.pin_bound()) cuts its lines at the plot edge and leaves out the points and
labels beyond it, and its title says so.

chart_ops() draws through a backend: PDF_BACKEND (the default) gives PDF content-stream
ops, chart_svg.SvgBackend SVG elements of the same layout, so the report's PDF, SVG and
HTML charts are one drawing.
"""
from ..core.i18n import Translator, DEFAULT_LANGUAGE
from ..core.pdf_writer import _pdf_ascii_fold, _pdf_dot_op, _pdf_line_op, _pdf_rect_op, _pdf_text_op
from .chart_series import clip_polyline, in_view, legend_series, point_label, series_xs, y_scale


class _PdfBackend:
    """chart_ops()'s drawing calls as PDF content-stream ops; text is ASCII-folded for the
    PDF base fonts."""
    rect = staticmethod(_pdf_rect_op)
    line = staticmethod(_pdf_line_op)
    dot = staticmethod(_pdf_dot_op)
    text = staticmethod(_pdf_text_op)
    fold = staticmethod(_pdf_ascii_fold)

    @staticmethod
    def dashed(op):
        return "[3 2] 0 d " + op + " [] 0 d"


PDF_BACKEND = _PdfBackend()

_AXIS_GRAY = (0.4, 0.4, 0.4)
_GUIDE_GRAY = (0.88, 0.88, 0.88)
_LABEL_SIZE = 7
_LABEL_CHAR_W = 0.6 * _LABEL_SIZE   # Courier advance width
_LAST_LABEL_STEPS = 5               # stacked places tried above and below a line's last point


def _overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def place_labels(candidates):
    """[(x, y, text, rgb)] of the labels that fit without overlapping. candidates:
    [(priority, [(x, y), ...] positions to try in order, text, rgb)], lower priority placed
    first; a label is boxed from its baseline y - 1 to y + size."""
    placed, boxes = [], []
    for _priority, positions, text, rgb in sorted(candidates, key=lambda c: c[0]):
        for x, y in positions:
            box = (x, y - 1, x + len(text) * _LABEL_CHAR_W, y + _LABEL_SIZE)
            if not any(_overlaps(box, b) for b in boxes):
                boxes.append(box)
                placed.append((x, y, text, rgb))
                break
    return placed


def _rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))


def chart_ops(x0, y0, w, h, series1=(), series2=(), translator=None,
              label_key1="bench.axis_nps", label_key2="bench.axis_spw",
              fmt1="{:,.0f}", fmt2="{:,.3f}", log_y=False, pins1=None, pins2=None,
              backend=PDF_BACKEND):
    """Ops drawing the chart inside the box [x0, x0+w] x [y0, y0+h].

    series1/series2: [chart_series.Series] on the left (primary) and right (secondary)
    axis; the right axis exists only when series2 has points. Each axis has its own scale
    (chart_series.YScale, log10 when log_y), because the two series differ by orders of
    magnitude. The x ticks are the union of all floors. A legend of named series runs
    along the top edge.

    label_key1/label_key2: i18n keys of the axis titles; fmt1/fmt2: str.format() templates
    of the value labels and linear ticks. pins1/pins2: the axes' pinned (min, max), see
    chart_series.axis_pins(). backend: PDF_BACKEND or a chart_svg.SvgBackend."""
    b = backend
    t = (translator or Translator(DEFAULT_LANGUAGE)).t
    series1 = [s for s in series1 if s.points]
    series2 = [s for s in series2 if s.points]
    ops = [b.rect(x0, y0, w, h, stroke_rgb=(0.8, 0.8, 0.8), width=0.5)]
    if not series1 and not series2:
        ops.append(b.text(x0 + w / 2 - 60, y0 + h / 2, 10, "Helvetica",
                                 b.fold(t("bench.no_data_chart"))))
        return ops

    has_secondary = bool(series2)
    scale1 = y_scale(series1, log_y, pins1) if series1 else None
    scale2 = y_scale(series2, log_y, pins2) if has_secondary else None
    # The left margin fits the longest tick label (7 pt Courier) left of the axis.
    tick_chars = max((len(scale1.tick_label(v, fmt1)) for v in scale1.ticks()),
                     default=0) if scale1 else 0
    pad_left = max(55, tick_chars * 0.6 * 7 + 10)
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
    pinned = " [" + t("bench.axis_pinned") + "]"
    title1 = t(label_key1) + (pinned if any(v is not None for v in pins1 or ()) else "")
    title2 = t(label_key2) + (pinned if any(v is not None for v in pins2 or ()) else "")

    # Horizontal inset keeps the edge points' value labels off the y-axis tick labels.
    inset_x = max(15.0, plot_w * 0.05)

    def sx(x):
        return plot_x0 + inset_x + (x - x_min) / (x_max - x_min) * (plot_w - 2 * inset_x)

    def sy(scale, y):
        return plot_y0 + scale.frac(y) * plot_h

    def sf(frac):
        return plot_y0 + frac * plot_h

    if scale1:
        for y_val in scale1.ticks():
            ops.append(b.line(plot_x0, sy(scale1, y_val), plot_x0 + plot_w,
                                     sy(scale1, y_val), width=0.4, rgb=_GUIDE_GRAY))
    ops.append(b.line(plot_x0, plot_y0, plot_x0, plot_y0 + plot_h, rgb=_AXIS_GRAY))
    ops.append(b.line(plot_x0, plot_y0, plot_x0 + plot_w, plot_y0, rgb=_AXIS_GRAY))
    if has_secondary:
        ops.append(b.line(plot_x0 + plot_w, plot_y0, plot_x0 + plot_w, plot_y0 + plot_h,
                                 rgb=_AXIS_GRAY))

    if scale1:
        for y_val in scale1.ticks():
            y_px = sy(scale1, y_val)
            ops.append(b.line(plot_x0 - 3, y_px, plot_x0, y_px, rgb=_AXIS_GRAY))
            text = scale1.tick_label(y_val, fmt1)
            ops.append(b.text(plot_x0 - 5 - len(text) * 0.6 * 7, y_px - 3, 7, "Courier",
                                     text))
    if scale2:
        for y_val in scale2.ticks():
            y_px = sy(scale2, y_val)
            ops.append(b.line(plot_x0 + plot_w, y_px, plot_x0 + plot_w + 3, y_px,
                                     rgb=_AXIS_GRAY))
            ops.append(b.text(plot_x0 + plot_w + 5, y_px - 3, 7, "Courier",
                                     scale2.tick_label(y_val, fmt2)))

    for x_val in all_xs:
        x_px = sx(x_val)
        ops.append(b.line(x_px, plot_y0, x_px, plot_y0 - 3, rgb=_AXIS_GRAY))
        ops.append(b.text(x_px - 8, plot_y0 - 14, 7, "Courier", str(x_val)))

    ops.append(b.text(plot_x0 + plot_w / 2 - 30, y0 + 4, 8, "Helvetica-Bold",
                             b.fold(t("bench.axis_floor"))))
    if series1:
        ops.append(b.dot(x0 + 4, y0 + h - 7.5, 2.2, rgb=_AXIS_GRAY))
        ops.append(b.text(x0 + 9, y0 + h - 10, 8, "Helvetica-Bold",
                                 b.fold(title1)))
    if has_secondary:
        ops.append(b.rect(x0 + w - 6, y0 + h - 9.5, 4, 4, fill_rgb=_AXIS_GRAY))
        # Helvetica-Bold at 8 pt averages ~4.4 pt per character; the title ends at the marker.
        ops.append(b.text(x0 + w - 68 - 4.4 * (len(title2) - len(t(label_key2))),
                                 y0 + h - 10, 8, "Helvetica-Bold", b.fold(title2)))

    legend_x = x0 + 90
    for s in legend_series(series1, series2):
        rgb = _rgb(s.color)
        line = b.line(legend_x - 5, y0 + h - 8, legend_x + 5, y0 + h - 8, width=1.5,
                            rgb=rgb)
        ops.append(b.dashed(line) if s.dashed else line)
        ops.append(b.dot(legend_x, y0 + h - 8, 2.5, rgb=rgb))
        if s.dashed:
            ops.append(b.dot(legend_x, y0 + h - 8, 1.3, rgb=(1, 1, 1)))
        text = b.fold(s.name)
        ops.append(b.text(legend_x + 8, y0 + h - 10.5, 6.5, "Helvetica-Bold", text,
                                 rgb=rgb))
        legend_x += 22 + 6.5 * 0.55 * len(text)

    candidates = []
    # Labels stay between the x axis and the legend row, off the floor tick labels.
    label_y_min, label_y_max = plot_y0 + 2, y0 + h - 22

    def draw(series, scale, fmt, label_dy, secondary=False):
        for s in series:
            pts = [(x, y) for x, y in s.points if scale.usable(y)]
            rgb = _rgb(s.color)
            for run in clip_polyline([(sx(x), scale.frac(y)) for x, y in pts]):
                for (xa, fa), (xb, fb) in zip(run, run[1:]):
                    op = b.line(xa, sf(fa), xb, sf(fb), width=0.7 if secondary else 1.8,
                                      rgb=rgb)
                    ops.append(b.dashed(op) if s.dashed else op)
            pts = [(x, y) for x, y in pts if in_view(scale.frac(y))]
            coords = [(sx(x), sy(scale, y)) for x, y in pts]
            for i, ((x_val, y_val), (cx, cy)) in enumerate(zip(pts, coords)):
                if secondary:
                    ops.append(b.rect(cx - 2.3, cy - 2.3, 4.6, 4.6, fill_rgb=rgb))
                else:
                    ops.append(b.dot(cx, cy, 2.5, rgb=rgb))
                if s.dashed:
                    ops.append(b.dot(cx, cy, 1.3, rgb=(1, 1, 1)))
                last = i == len(pts) - 1
                above, below = cy + label_dy, cy - 22 - label_dy
                steps = range(_LAST_LABEL_STEPS if last else 1)
                text = b.fold(point_label(fmt, y_val, s))
                lx = max(x0 + 2, min(cx - 10, x0 + w - 2 - len(text) * _LABEL_CHAR_W))
                positions = [(lx, y) for k in steps
                             for y in (above + k * (_LABEL_SIZE + 2),
                                       below - k * (_LABEL_SIZE + 2))
                             if label_y_min <= y <= label_y_max]
                candidates.append(((0 if last else 1, cx), positions, text, rgb))

    if scale1:
        draw(series1, scale1, fmt1, 8)
    if scale2:
        draw(series2, scale2, fmt2, -14, secondary=True)
    for x, y, text, rgb in place_labels(candidates):
        ops.append(b.text(x, y, _LABEL_SIZE, "Courier", text, rgb=rgb))
    return ops

