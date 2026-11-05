"""The Benchmark charts' zoomed floor range: zoom around a floor, pan, and the series inside the
range. Pure functions, no tkinter.

A view is (lo, hi) in floors, or None for every floor of the data. The three charts share one
view (one floor axis), so zooming one chart lines all of them up. Zooming keeps the floor under
the pointer where it is on screen; a view never gets narrower than MIN_WIDTH floors, never
leaves the data's span, and a view as wide as the span is None again.
"""
from .chart_series import Series

MIN_WIDTH = 1.0
WHEEL_STEP = 0.8   # range factor per wheel notch toward the pointer (arbitrary)


def data_span(*series_lists):
    """(first, last) floor of every point of the series lists, or None without points."""
    xs = [x for series in series_lists for s in series for x, _y in s.points]
    return (min(xs), max(xs)) if xs else None


def _clamp(lo, hi, span):
    width = hi - lo
    if lo < span[0]:
        lo, hi = span[0], span[0] + width
    if hi > span[1]:
        lo, hi = span[1] - width, span[1]
    return lo, hi


def zoom(view, span, anchor, factor):
    """The view after scaling its width by `factor` (< 1 zooms in) around floor `anchor`."""
    if span is None or span[1] <= span[0]:
        return None
    lo, hi = view if view is not None else span
    width = min(span[1] - span[0], max(MIN_WIDTH, (hi - lo) * factor))
    if width >= span[1] - span[0]:
        return None
    frac = (anchor - lo) / (hi - lo) if hi > lo else 0.5
    frac = min(1.0, max(0.0, frac))
    new_lo = anchor - frac * width
    return _clamp(new_lo, new_lo + width, span)


def pan(view, span, delta):
    """The view shifted by `delta` floors, kept inside the span; None stays None."""
    if view is None or span is None:
        return view
    return _clamp(view[0] + delta, view[1] + delta, span)


def in_view(series, view):
    """`series` with only the points whose floor lies in the view (all of them for None)."""
    if view is None:
        return list(series)
    lo, hi = view
    return [Series(s.name, s.tag, [(x, y) for x, y in s.points if lo <= x <= hi], s.color,
                   s.dashed) for s in series]


def floor_at(geometry, px):
    """The floor under canvas x `px`; geometry = (x of the first floor, pixels from the first
    to the last floor, first floor, last floor) as the chart drew them."""
    x0, width, x_min, x_max = geometry
    if width <= 0:
        return x_min
    return x_min + (px - x0) / width * (x_max - x_min)


def floors_per_pixel(geometry):
    x0, width, x_min, x_max = geometry
    return (x_max - x_min) / width if width > 0 else 0.0
