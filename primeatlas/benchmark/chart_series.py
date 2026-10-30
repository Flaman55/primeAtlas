"""Series and y-scales of the Benchmark charts, shared by the canvas and the PDF renderer.

A chart draws a list of Series per y-axis. Engine series come from benchmark_log.csv, one
line per engine (last row per floor and engine wins), one distinct hue per engine on both
axes; the renderers tell the axes apart by marker and line weight (primary: circles, thick
line; secondary: squares, thin line). Reference series (reference_points.py) are drawn
dashed with hollow markers on the primary axis. Hues are far apart in RGB and readable on
the light and dark theme backgrounds. YScale maps values to a 0..1 fraction of the plot
height, linear from zero or log10 fitted to the data.
No tkinter here: benchmark_tab.py and benchmark.py both render from these objects.
"""
import math
from collections import namedtuple

# name: legend text; tag: short text after a point's value ("v5"), "" for none.
Series = namedtuple("Series", "name tag points color dashed")

# Drawing order: later engines on top.
ENGINE_DRAW_ORDER = ("unknown", "hybrid", "v4.1", "v5")

ENGINE_COLORS = {"unknown": "#8c8c8c", "hybrid": "#009e73", "v4.1": "#e69f00", "v5": "#2f7fe0"}
OTHER_ENGINE_COLOR = "#b5e61d"

AXIS_COLOR = {"primary": "#2f7fe0", "secondary": "#e69f00"}


def engine_lines(rows, row_value, row_engine):
    """{engine: [(base_exponent, value), ...] ascending} with the last row per floor and
    engine whose row_value(row) is not None."""
    latest = {}
    for row in rows:
        try:
            floor = int(row.get("base_exponent", ""))
        except (TypeError, ValueError):
            continue
        value = row_value(row)
        if value is not None:
            latest.setdefault(row_engine(row), {})[floor] = value
    return {engine: sorted(points.items()) for engine, points in latest.items()}


def _engine_rank(engine):
    return (ENGINE_DRAW_ORDER.index(engine) if engine in ENGINE_DRAW_ORDER else 1.5, engine)


def engine_series(lines):
    """[Series] for engine_lines() output, in ENGINE_DRAW_ORDER, in the engine's color."""
    return [Series(engine, "" if engine == "unknown" else engine, points,
                   ENGINE_COLORS.get(engine, OTHER_ENGINE_COLOR), False)
            for engine, points in sorted(lines.items(), key=lambda kv: _engine_rank(kv[0]))
            if points]


def plain_series(points, axis="primary"):
    """One unnamed solid Series for a bare (floor, value) list; [] for no points."""
    return [Series("", "", list(points), AXIS_COLOR[axis], False)] if points else []


def legend_series(*series_lists):
    """Named series once each, an engine on both axes as one entry: engines in
    ENGINE_DRAW_ORDER, then the reference series in their own order."""
    seen, out = set(), []
    for s in (s for series in series_lists for s in series):
        if s.name and s.name not in seen:
            seen.add(s.name)
            out.append(s)
    return sorted(out, key=lambda s: (s.dashed, (0, "") if s.dashed else _engine_rank(s.name)))


def series_xs(*series_lists):
    return sorted({x for series in series_lists for s in series for x, _ in s.points})


def point_label(fmt, value, series, show_unknown=False):
    """Value text with the series tag: "1,234 [v5]"."""
    tag = series.tag or ("unknown" if show_unknown and not series.dashed else "")
    return fmt.format(value) + (" [" + tag + "]" if tag else "")


class YScale:
    """Linear scale anchored at zero, or log10 over the positive values' own range plus a
    small margin, so the lines use the plot height instead of sitting inside whole empty
    decades. Values a log scale cannot show (<= 0) are reported by usable()."""

    LOG_MARGIN = 0.06  # fraction of the log span added above and below the data

    def __init__(self, values, log=False):
        self.log = log
        if log:
            positive = [v for v in values if v > 0] or [1.0]
            lo, hi = math.log10(min(positive)), math.log10(max(positive))
            if hi - lo < 0.2:
                mid = (lo + hi) / 2
                lo, hi = mid - 0.1, mid + 0.1
            margin = (hi - lo) * self.LOG_MARGIN
            self.lo, self.hi = lo - margin, hi + margin
        else:
            values = list(values) or [0.0]
            lo, hi = min(values), max(values)
            if lo == hi:
                pad = max(1.0, abs(lo) * 0.1)
                lo -= pad
                hi += pad
            self.lo, self.hi = min(lo, 0), hi

    def usable(self, value):
        return value > 0 if self.log else True

    def frac(self, value):
        if self.log:
            return (math.log10(value) - self.lo) / (self.hi - self.lo)
        return (value - self.lo) / (self.hi - self.lo)

    def _log_ticks(self, mantissas, step=1):
        return [m * 10.0 ** k
                for k in range(math.floor(self.lo), math.ceil(self.hi) + 1, step)
                for m in mantissas
                if self.lo <= math.log10(m) + k <= self.hi]

    def ticks(self):
        """Tick values. Log: 1-2-5 per decade over at most 2.5 decades, then every decade
        (every second one past 8), down to 1..9 when no other set gives two ticks.
        Linear: six even steps."""
        if self.log:
            span = self.hi - self.lo
            if span > 8:
                return self._log_ticks((1,), 2)
            for mantissas in (((1,),) if span > 2.5 else ()) + ((1, 2, 5), tuple(range(1, 10))):
                ticks = self._log_ticks(mantissas)
                if len(ticks) >= 2:
                    return ticks
            return ticks
        return [self.lo + (self.hi - self.lo) * i / 5 for i in range(6)]

    def tick_label(self, value, fmt):
        if self.log:
            exponent = math.floor(math.log10(value) + 1e-9)
            return "%de%d" % (round(value / 10.0 ** exponent), exponent)
        return fmt.format(value)


def y_scale(series, log=False):
    return YScale([y for s in series for _, y in s.points], log)
