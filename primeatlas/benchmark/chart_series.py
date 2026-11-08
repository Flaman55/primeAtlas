"""Series and y-scales of the Benchmark charts, shared by the canvas and the PDF renderer.

A chart draws a list of Series per y-axis. Engine series come from benchmark_log.csv, one
line per engine, with P runs (pt1 above MR_DET_BOUND, "pt1 P") on a line of their own
(last row per floor and line wins), one distinct hue per line on both
axes; the renderers tell the axes apart by marker and line weight (primary: circles, thick
line; secondary: squares, thin line). Reference series (reference_points.py) are drawn
dashed with hollow markers on the primary axis. Hues are far apart in RGB and readable on
the light and dark theme backgrounds. YScale maps values to a 0..1 fraction of the plot
height, linear from zero or log10 fitted to the data; a pinned bound (pin_bound(), one
(min, max) pair per axis) replaces the fitted one exactly, like matplotlib's set_ylim, and
clip_polyline() cuts the lines at the plot edge (also the left and right edges of a zoomed
chart, YScale.zoomed() its visible part, chart_view.py). A line is one series on one axis; each one
can be hidden on its own (line_key(), a set of hidden keys per chart).
No tkinter here: benchmark_tab.py and benchmark.py both render from these objects.
"""
import copy
import math
from collections import namedtuple

# name: legend text; tag: short text after a point's value ("v5"), "" for none;
# engine: the color and draw-order key of the line ("v6", "pt1 P"), "" = name;
# notes: {x: text} shown after a point's tag ("10^11", the range it was measured on).
Series = namedtuple("Series", "name tag points color dashed engine notes",
                    defaults=("", None))

# Drawing order: later engines on top.
ENGINE_DRAW_ORDER = ("unknown", "primesieve", "primesieve_print", "primesieve_count", "hybrid",
                     "v4.1", "v5", "v6", "v7", "pt1", "pt1 D+P", "pt1 P")

ENGINE_COLORS = {"unknown": "#8c8c8c", "primesieve": "#b5e61d", "primesieve_print": "#00c8c8",
                 "primesieve_count": "#802080",
                 "hybrid": "#009e73", "v4.1": "#e69f00", "v5": "#2f7fe0", "v6": "#7f00ff", "v7": "#ff00ff",
                 "pt1": "#e0a0e0", "pt1 D+P": "#608000", "pt1 P": "#00e000"}
OTHER_ENGINE_COLOR = "#ff8080"

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


def engine_series(lines, engines=None, notes=None):
    """[Series] for engine_lines() output, in ENGINE_DRAW_ORDER, in the engine's color.
    engines: {line name: engine key} when the names are not the engine keys themselves;
    notes: {line name: {x: text}} for the points' notes."""
    engines = engines or {}
    notes = notes or {}

    def key(name):
        return engines.get(name, name)
    return [Series(name, "" if name == "unknown" else name, points,
                   ENGINE_COLORS.get(key(name), OTHER_ENGINE_COLOR), False, key(name),
                   notes.get(name))
            for name, points in sorted(lines.items(),
                                       key=lambda kv: (_engine_rank(key(kv[0])), kv[0]))
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
    return sorted(out, key=lambda s: (s.dashed, (0, "") if s.dashed
                                      else (_engine_rank(s.engine or s.name), s.name)))


def legend_entries(series1, series2):
    """[(Series, axes)] in legend_series() order; axes: the axes the series has a line on,
    ("primary",), ("secondary",) or both, so the legend offers one toggle per line."""
    names = {"primary": {s.name for s in series1}, "secondary": {s.name for s in series2}}
    return [(s, tuple(axis for axis in ("primary", "secondary") if s.name in names[axis]))
            for s in legend_series(series1, series2)]


def line_key(axis, name):
    """The key of one line in a chart's set of hidden lines."""
    return (axis, name)


def visible_series(series, hidden, axis):
    """series without the lines in `hidden` (a set of line_key(); None for none)."""
    return [s for s in series if not hidden or line_key(axis, s.name) not in hidden]


def toggle_lines(hidden, keys):
    """A new hidden set: all `keys` shown when all of them are hidden, else all hidden."""
    keys = set(keys)
    return set(hidden) - keys if keys <= set(hidden) else set(hidden) | keys


def series_xs(*series_lists):
    return sorted({x for series in series_lists for s in series for x, _ in s.points})


def point_label(fmt, value, series, show_unknown=False, x=None):
    """Value text with the series tag and the point's note: "1,234 [v5] @ 10^11"."""
    tag = series.tag or ("unknown" if show_unknown and not series.dashed else "")
    note = (series.notes or {}).get(x, "")
    return fmt.format(value) + (" [" + tag + "]" if tag else "") + (" @ " + note if note else "")


class YScale:
    """Linear scale anchored at zero, or log10 over the positive values' own range plus a
    small margin, so the lines use the plot height instead of sitting inside whole empty
    decades. Values a log scale cannot show (<= 0) are reported by usable().

    lo/hi: pinned bounds in value units; each one is the axis edge exactly and the other
    edge is fitted to the data as above. A log scale ignores a pin <= 0. An edge fitted
    against a pin keeps the axis from collapsing (LOG_MIN_SPAN, or the linear pad)."""

    LOG_MARGIN = 0.06  # fraction of the log span added above and below the data
    LOG_MIN_SPAN = 0.2  # decades

    def __init__(self, values, log=False, lo=None, hi=None):
        self.log = log
        if log:
            positive = [v for v in values if v > 0] or [1.0]
            pin_lo = math.log10(lo) if lo is not None and lo > 0 else None
            pin_hi = math.log10(hi) if hi is not None and hi > 0 else None
            lo, hi = math.log10(min(positive)), math.log10(max(positive))
            if hi - lo < self.LOG_MIN_SPAN:
                mid = (lo + hi) / 2
                lo, hi = mid - self.LOG_MIN_SPAN / 2, mid + self.LOG_MIN_SPAN / 2
            margin = (hi - lo) * self.LOG_MARGIN
            lo, hi = lo - margin, hi + margin
            self.lo, self.hi = self._fit(lo, hi, pin_lo, pin_hi, self.LOG_MIN_SPAN)
        else:
            values = list(values) or [0.0]
            pin_lo, pin_hi = lo, hi
            lo, hi = min(values), max(values)
            if lo == hi:
                pad = max(1.0, abs(lo) * 0.1)
                lo -= pad
                hi += pad
            lo = min(lo, 0)
            span = pin_lo if pin_lo is not None else pin_hi
            pad = max(1.0, abs(span) * 0.1) if span is not None else 0
            self.lo, self.hi = self._fit(lo, hi, pin_lo, pin_hi, pad)

    @staticmethod
    def _fit(lo, hi, pin_lo, pin_hi, pad):
        """(lo, hi) with the pins in place; an unpinned edge stays at least `pad` away from
        a pinned one."""
        if pin_lo is not None and pin_hi is not None and pin_lo < pin_hi:
            return pin_lo, pin_hi
        if pin_hi is not None:
            return min(lo, pin_hi - pad), pin_hi
        if pin_lo is not None:
            return pin_lo, max(hi, pin_lo + pad)
        return lo, hi

    def zoomed(self, view):
        """This scale narrowed to `view` = (lo, hi), fractions of its full range
        (chart_view.py); the scale itself for None."""
        if view is None:
            return self
        out = copy.copy(self)
        span = self.hi - self.lo
        out.lo, out.hi = self.lo + view[0] * span, self.lo + view[1] * span
        return out

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


def y_scale(series, log=False, pins=None):
    """YScale of the series' values; pins: the axis' (min, max) from axis_pins()."""
    lo, hi = pins or (None, None)
    return YScale([y for s in series for _, y in s.points], log, lo, hi)


def axis_pins(pins, axis):
    """(min, max) pinned on `axis` ("primary" | "secondary"), None for an unpinned edge;
    pins: {axis: (min, max)} of one chart."""
    return (pins or {}).get(axis, (None, None))


def pin_bound(pins, axis, which, value):
    """A new pins dict with `value` as the axis' "min" or "max". A min at or above the
    pinned max, or a max at or below the pinned min, replaces that other pin."""
    lo, hi = axis_pins(pins, axis)
    if which == "max":
        lo, hi = (lo if lo is not None and lo < value else None), value
    else:
        lo, hi = value, (hi if hi is not None and hi > value else None)
    return dict(pins or {}, **{axis: (lo, hi)})


def clear_pins(pins, axis=None):
    """A new pins dict without the pins of `axis`, or without any for axis=None."""
    return {} if axis is None else {k: v for k, v in (pins or {}).items() if k != axis}


VIEW_EPSILON = 1e-9  # a pinned point's own fraction is 0 or 1 up to rounding


def in_view(frac):
    """True for a fraction of the plot height inside the plot, edges included."""
    return -VIEW_EPSILON <= frac <= 1 + VIEW_EPSILON


def _clip(points, k, lo, hi, inside):
    """Runs of a polyline inside lo <= coordinate k <= hi (inside() tests a point's own
    coordinate): a segment leaving the band ends on the edge it crosses."""
    runs, run = [], []

    def cross(a, b, edge):
        t = (edge - a[k]) / (b[k] - a[k])
        other = a[1 - k] + (b[1 - k] - a[1 - k]) * t
        return (float(edge), other) if k == 0 else (other, float(edge))

    for i, p in enumerate(points):
        if i:
            a = points[i - 1]
            edges = sorted({e for e in (lo, hi) if min(a[k], p[k]) < e < max(a[k], p[k])},
                           reverse=a[k] > p[k])
            for edge in edges:
                q = cross(a, p, edge)
                if run:
                    run.append(q)
                    runs.append(run)
                    run = []
                else:
                    run = [q]
        if inside(p[k]):
            run.append(p)
        elif run:
            runs.append(run)
            run = []
    if run:
        runs.append(run)
    return runs


def clip_polyline(points, x_lo=None, x_hi=None):
    """Runs of a polyline [(x, frac), ...] inside 0 <= frac <= 1 and, when given, inside
    x_lo <= x <= x_hi: a segment leaving the plot ends on the edge it crosses and the line
    resumes where it comes back in."""
    runs = _clip(points, 1, 0, 1, in_view)
    if x_lo is None:
        return runs
    return [cut for run in runs
            for cut in _clip(run, 0, x_lo, x_hi, lambda x: x_lo <= x <= x_hi)]
