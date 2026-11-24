"""Benchmark tab charts write large y tick values short (benchmark_tab._draw_growth_chart, the
same function the chart windows draw with): on a linear axis a tick from a million up is
number_format.compact() ("1.18 G"), a smaller one number_format.decimal(); every tick on its
own, so one axis may mix the two. A log axis keeps "3e9". The hover tooltip and the pin menu
(both read a point's hover entry) keep the exact value. The axis pads are measured from the
short texts (never below 50 px); the ticks stay where the scale puts them, zoomed or pinned.

Checks: tick texts on the left and the right axis, linear and log, a mixed axis, a zoomed and a
pinned axis; tick y positions; the pads; the hover entries; the 999 999 / 1 000 000 boundary;
an empty chart. Windows, real display:
    python unitTests/test_benchmark_tab_ticks.py
"""
import os
import sys
import tkinter as tk
from tkinter import font as tkfont

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [_REPO_ROOT, os.path.join(_REPO_ROOT, "prime_sieve")]

from primeatlas.benchmark import benchmark_tab, chart_series  # noqa: E402
from primeatlas.benchmark.chart_series import Series, point_label, y_scale  # noqa: E402
from primeatlas.core import number_format  # noqa: E402
from primeatlas.core.i18n import Translator  # noqa: E402

failures = []

WIDTH, HEIGHT = 900, 300
PAD_TOP, PAD_BOTTOM = 40, 40  # _draw_growth_chart's own plot strip


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


class RecordingCanvas(tk.Canvas):
    """A canvas that keeps every create_text call's (x, y, kwargs)."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.texts = []

    def delete(self, *tags):
        if "all" in tags:
            self.texts = []
        return super().delete(*tags)

    def create_text(self, x, y, **kw):
        self.texts.append((x, y, kw))
        return super().create_text(x, y, **kw)


def draw(canvas, series1=None, series2=None, **kw):
    """Draws and returns (left ticks, right ticks, hover points); a tick is (x, y, text)."""
    captured = []
    real = benchmark_tab._bind_chart_hover
    benchmark_tab._bind_chart_hover = lambda c, points, *a, **k: captured.append(points)
    try:
        benchmark_tab._draw_growth_chart(canvas, None, WIDTH, HEIGHT, translator=Translator("en"),
                                         series1=series1, series2=series2, **kw)
    finally:
        benchmark_tab._bind_chart_hover = real
    in_plot = [(x, y, k) for x, y, k in canvas.texts
               if PAD_TOP - 0.5 <= y <= HEIGHT - PAD_BOTTOM + 0.5]
    left = [(x, y, k["text"]) for x, y, k in in_plot if k.get("anchor") == "e"]
    right = [(x, y, k["text"]) for x, y, k in in_plot
             if k.get("anchor") == "w" and x > WIDTH / 2]
    return left, right, (captured[0] if captured else [])


def expected(scale, places):
    if scale.log:
        return [scale.tick_label(v, places) for v in scale.ticks()]
    return [(number_format.compact if v >= 1e6 else number_format.decimal)(v, places)
            for v in scale.ticks()]


def texts(ticks):
    return [text for _x, y, text in sorted(ticks, key=lambda t: -t[1])]


def main():
    root = tk.Tk()
    canvas = RecordingCanvas(root, width=WIDTH, height=HEIGHT)
    canvas.pack()
    root.update()
    tick_font = tkfont.Font(family="Consolas", size=8)
    plot_h = HEIGHT - PAD_TOP - PAD_BOTTOM

    big = Series("v5", tag="v5", points=[(19, 1_180_000_000), (20, 3_500_000_000), (21, 71_556_448)],
                 color="#1c5fa8", dashed=False)
    small = Series("v5", tag="v5", points=[(19, 1.25), (20, 2_400_000.5), (21, 900_000.125)],
                   color="#1c5fa8", dashed=False)

    # 1, 3: left axis, linear, every tick on its own (0 stays "0").
    left, right, hover = draw(canvas, [big], [small], places1=0, places2=3)
    scale1 = y_scale([big])
    scale2 = y_scale([small])
    check(texts(left) == expected(scale1, 0),
          f"left linear ticks are short from a million up: {texts(left)}")
    check(any(" G" in s or " G" in s for s in texts(left)),
          f"a 3.5e9 axis has a G tick: {texts(left)}")
    # 1, 2, 3: right axis, mixed: below a million decimal(), from it compact().
    check(texts(right) == expected(scale2, 3),
          f"right linear ticks: short from a million, exact below: {texts(right)}")
    ticks2 = scale2.ticks()
    check(any(0 < v < 1e6 for v in ticks2) and any(v >= 1e6 for v in ticks2),
          f"the right axis really mixes both sides of a million: {ticks2}")

    # 8: tick y positions follow the scale.
    ys = sorted((y for _x, y, _t in left), reverse=True)
    want = [PAD_TOP + plot_h - scale1.frac(v) * plot_h for v in scale1.ticks()]
    check(len(ys) == len(want) and all(abs(a - b) < 0.01 for a, b in zip(ys, want)),
          f"left ticks sit where the scale puts them: {ys} vs {want}")

    # 7: pads measured from the short texts, never below 50 px.
    pad_left = left[0][0] + 8
    widest = max(tick_font.measure(s) for s in texts(left))
    check(pad_left == max(50, widest + 24), f"left pad from the short texts: {pad_left}")
    long_widest = max(tick_font.measure(number_format.decimal(v, 0)) for v in scale1.ticks())
    check(pad_left < long_widest + 24, f"the left pad is narrower than the exact texts need "
                                       f"({pad_left} < {long_widest + 24})")
    pad_right = WIDTH - (right[0][0] - 8)
    widest2 = max(tick_font.measure(s) for s in texts(right))
    check(pad_right == max(50, widest2 + 28), f"right pad from the short texts: {pad_right}")

    # 5, 6: the hover entry (tooltip and pin menu) keeps the exact value.
    check(len(hover) == 6, f"every point has a hover entry: {len(hover)}")
    for entry in hover:
        s = big if entry[7] == "primary" else small
        places = 0 if entry[7] == "primary" else 3
        check(entry[4] == point_label(places, entry[3], s, show_unknown=True, x=entry[2]),
              f"hover/pin text is exact: {entry[4]!r}")
    check(any(number_format.decimal(71_556_448, 0) in e[4] for e in hover),
          "the 71 556 448 point's text has all its digits")

    # 4: log axis unchanged.
    left, right, _ = draw(canvas, [big], [small], places1=0, places2=3, log_y=True)
    check(texts(left) == expected(y_scale([big], True), 0)
          and all("e" in s for s in texts(left)), f"log ticks stay 'NeM': {texts(left)}")
    check(texts(right) == expected(y_scale([small], True), 3), f"right log ticks: {texts(right)}")

    # 8: zoomed and pinned axes put short texts on the same ticks.
    pins = (None, 2_000_000_000)
    left, _right, _ = draw(canvas, [big], None, places1=0, pins1=pins, y_view=(0.25, 0.75))
    zoomed = y_scale([big], False, pins).zoomed((0.25, 0.75))
    check(texts(left) == expected(zoomed, 0), f"zoomed, pinned ticks: {texts(left)}")
    ys = sorted((y for _x, y, _t in left), reverse=True)
    want = [PAD_TOP + plot_h - zoomed.frac(v) * plot_h for v in zoomed.ticks()]
    check(all(abs(a - b) < 0.01 for a, b in zip(ys, want)), "zoomed ticks keep their places")

    # 2: below a million the axis is exact, as before.
    tiny = Series("v5", tag="v5", points=[(19, 12.5), (20, 640_000.0)], color="#1c5fa8", dashed=False)
    left, _right, _ = draw(canvas, [tiny], None, places1=1)
    check(texts(left) == [number_format.decimal(v, 1) for v in y_scale([tiny]).ticks()],
          f"an axis under a million keeps exact ticks: {texts(left)}")

    # 1, 2: the boundary.
    scale = chart_series.YScale([1.0])
    check(scale.tick_label(999_999, 0, short=True) == number_format.decimal(999_999, 0),
          "999 999 stays exact")
    check(scale.tick_label(1_000_000, 0, short=True) == number_format.compact(1_000_000, 0)
          and "M" in scale.tick_label(1_000_000, 0, short=True), "1 000 000 is short")

    # 9: an empty chart still says so.
    canvas.texts = []
    benchmark_tab._draw_growth_chart(canvas, [], WIDTH, HEIGHT, translator=Translator("en"))
    check([k["text"] for _x, _y, k in canvas.texts] == [Translator("en").t("bench.no_data_chart")],
          "an empty chart shows only 'no data'")

    root.destroy()
    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
