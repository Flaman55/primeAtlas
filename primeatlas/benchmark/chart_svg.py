"""SVG drawing of one Benchmark chart: chart_pdf.chart_ops() through an SVG backend.

chart_ops() lays a chart out in PDF's bottom-left-origin point space and hands every shape to
its backend; SvgBackend turns them into SVG elements of an image `height` points tall, flipping
y (SVG's origin is the top-left corner). Text stays Unicode (no PDF base-font folding), and
the PDF font names map to generic CSS families, so the SVG needs no embedded font.
"""
from xml.sax.saxutils import escape

from .chart_pdf import chart_ops

_FONTS = {"Helvetica": ("sans-serif", "normal"), "Helvetica-Bold": ("sans-serif", "bold"),
          "Courier": ("monospace", "normal")}


def _color(rgb):
    return "#{:02x}{:02x}{:02x}".format(*(round(c * 255) for c in rgb))


class SvgBackend:
    """chart_ops()'s drawing calls as SVG elements of an image `height` points tall."""

    def __init__(self, height):
        self.height = height

    def _y(self, y):
        return self.height - y

    def rect(self, x, y, w, h, fill_rgb=None, stroke_rgb=None, width=1.0):
        fill = _color(fill_rgb) if fill_rgb is not None else "none"
        stroke = (f' stroke="{_color(stroke_rgb)}" stroke-width="{width:.2f}"'
                  if stroke_rgb is not None else "")
        return (f'<rect x="{x:.2f}" y="{self._y(y + h):.2f}" width="{w:.2f}" height="{h:.2f}" '
                f'fill="{fill}"{stroke}/>')

    def line(self, x1, y1, x2, y2, width=1.0, rgb=(0, 0, 0)):
        return (f'<line x1="{x1:.2f}" y1="{self._y(y1):.2f}" x2="{x2:.2f}" '
                f'y2="{self._y(y2):.2f}" stroke="{_color(rgb)}" stroke-width="{width:.2f}"/>')

    def dot(self, cx, cy, r, rgb=(0, 0, 0)):
        return f'<circle cx="{cx:.2f}" cy="{self._y(cy):.2f}" r="{r:.2f}" fill="{_color(rgb)}"/>'

    def text(self, x, y, size, font_key, text, rgb=(0, 0, 0)):
        family, weight = _FONTS.get(font_key, ("sans-serif", "normal"))
        return (f'<text x="{x:.2f}" y="{self._y(y):.2f}" font-family="{family}" '
                f'font-weight="{weight}" font-size="{size}" fill="{_color(rgb)}">'
                f'{escape(text)}</text>')

    @staticmethod
    def dashed(element):
        return element.replace("/>", ' stroke-dasharray="3 2"/>', 1)

    @staticmethod
    def fold(text):
        return text


def chart_svg(width, height, **chart_kwargs):
    """A standalone <svg> element (width x height points, white background) of one chart;
    chart_kwargs are chart_ops()'s series/label/format/scale/pin arguments."""
    backend = SvgBackend(height)
    body = chart_ops(0, 0, width, height, backend=backend, **chart_kwargs)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}">'
            f'<rect width="{width}" height="{height}" fill="#ffffff"/>'
            + "".join(body) + "</svg>")
