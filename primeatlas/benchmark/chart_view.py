"""The Benchmark charts' zoom: which part of a chart is on screen, as when zooming a picture.
Pure functions, no tkinter.

Unzoomed, a chart shows all of itself: that is the furthest zoom out. Zooming in narrows the
visible part around the pointer on both axes, keeping the point under the pointer where it is
on screen; lines run on to the plot edge and are cut there, so a zoomed part between two floors
shows the line passing through it. Dragging moves the visible part over the chart.

The floor axis is shared: one x view, (lo, hi) in floors, lines the three charts up; its full
range is the floors of all charts' points. Each chart keeps its own y view, (lo, hi) as
fractions 0..1 of its full (unzoomed, pinned) y scale, applied to both of its axes
(chart_series.YScale.zoomed()). None is the full axis. Zoom goes in wheel notches: a level
counts them from the whole chart (0) up to MAX_LEVEL, and a view's width follows from its level
alone (zoom_step()), so zooming out retraces zooming in notch by notch. A view can be moved
past the data until the data's far edge reaches its opposite edge (the last floor at the view's
left edge, the first at its right edge), so any part can be centred and the data never leaves
the view.
"""
import math

WHEEL_STEP = 0.8   # range factor per wheel notch toward the pointer (arbitrary)
MAX_LEVEL = 18     # notches in from the whole chart: 0.8**18, about 1/56 of it (arbitrary)
MAX_X_TICKS = 24   # floor ticks on a zoomed axis; more floors show every k-th one
FULL_Y = (0.0, 1.0)


def data_span(*series_lists):
    """(first, last) floor of every point of the series lists, or None without points."""
    xs = [x for series in series_lists for s in series for x, _y in s.points]
    return (min(xs), max(xs)) if xs else None


def _clamp(lo, hi, full):
    """(lo, hi) moved back just enough to keep some of the full range in view: the full
    range's last value may reach the view's left edge and its first value the right edge."""
    width = hi - lo
    lo = min(max(lo, full[0] - width), full[1])
    return lo, lo + width


def zoom_step(view, level, base, anchor, steps, full):
    """(view, level) after `steps` wheel notches (+1 in, -1 out) around `anchor`. level counts
    the notches in from the whole chart (0: view None); the view's width is base's width times
    WHEEL_STEP ** level, base being the range the whole chart shows (the floors of the chart
    zoomed first; FULL_Y on a y axis). So a notch out undoes a notch in exactly, and as many
    notches out as in are the whole chart again. full: the range the view pans within
    (_clamp())."""
    level = min(MAX_LEVEL, max(0, level + steps))
    if level == 0 or base is None or base[1] <= base[0]:
        return None, 0
    lo, hi = view if view is not None else base
    width = (base[1] - base[0]) * WHEEL_STEP ** level
    frac = (anchor - lo) / (hi - lo) if hi > lo else 0.5
    frac = min(1.0, max(0.0, frac))
    new_lo = anchor - frac * width
    return _clamp(new_lo, new_lo + width, full), level


def pan(view, full, delta):
    """The view shifted by `delta`, at most until the full range's far edge reaches the
    view's opposite edge (_clamp()); None stays None."""
    if view is None or full is None:
        return view
    return _clamp(view[0] + delta, view[1] + delta, full)


def contains(view, floor):
    """True for a floor inside the view (every floor for None)."""
    return view is None or view[0] <= floor <= view[1]


def tick_floors(x_min, x_max, margin):
    """The whole floors between x_min - margin and x_max + margin, every k-th one when there
    are more than MAX_X_TICKS: the floor ticks of a zoomed axis."""
    floors = list(range(math.ceil(x_min - margin), math.floor(x_max + margin) + 1))
    step = max(1, math.ceil(len(floors) / MAX_X_TICKS))
    return floors[::step]


def data_fracs(*scaled_series):
    """(lowest, highest) fraction of the points on their full y scales, kept within 0..1
    (pins cut there); scaled_series: (YScale, [Series]) pairs, a None scale skipped. The y
    view pans within this range, as the x view within the floors: a linear scale starts at
    zero, so the part of it below the data is empty."""
    fracs = [min(1.0, max(0.0, scale.frac(y))) for scale, series in scaled_series if scale
             for s in series for _x, y in s.points if scale.usable(y)]
    return (min(fracs), max(fracs)) if fracs else FULL_Y


def floor_at(geometry, px):
    """The floor under canvas x `px`; geometry: a chart's chart_geometry (x of the first
    floor, pixels from the first to the last floor, first floor, last floor, ...)."""
    x0, width, x_min, x_max = geometry[:4]
    if width <= 0:
        return x_min
    return x_min + (px - x0) / width * (x_max - x_min)


def floors_per_pixel(geometry):
    x0, width, x_min, x_max = geometry[:4]
    return (x_max - x_min) / width if width > 0 else 0.0


def y_frac_at(geometry, py):
    """The fraction of the full y scale under canvas y `py`; geometry[4:] = (y of the plot's
    top edge, plot height, y view) as the chart drew them."""
    top, height, (lo, hi) = geometry[4], geometry[5], geometry[6] or FULL_Y
    if height <= 0:
        return lo
    return lo + (top + height - py) / height * (hi - lo)


def y_fracs_per_pixel(geometry):
    height, (lo, hi) = geometry[5], geometry[6] or FULL_Y
    return (hi - lo) / height if height > 0 else 0.0
