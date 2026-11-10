"""Which logged runs become the points of a Benchmark chart, and where they sit on its x axis.

A chart reduces the kept runs (chart_filter.py) to points: the runs that land on the same
line and x form a group, and the group's point is chosen by the chart's point choice --
the last run in log order, the lowest or the highest value of the chart's metric, or the run
selected in the tab's table (SELECTED: the selected run's own group shows that run, every
other group its last run). Ties on MIN/MAX go to the later run. ALL keeps every run of a group
as a point of its own, in log order, so repeated runs stand one above the other and show the
spread of the measurements.

The x axis has two modes (PointView.x_mode). X_FLOOR: x is the floor and a line is one engine
build on one thread setup (line_names.line_name()). X_WIDTH: x is log10 of the numbers the
run sieved (numbers_processed) and a line is that build on one floor ("v7.1, 24 thr @ f28"),
so the same engine's speed over width compares floor by floor; a run without a known width
has no x and is left out (unplaced() counts those). x_label() names an x value: the floor,
or the width ("2x10^11"). Lines of the same engine on different floors share the engine's
hue in shades (shade()): dashes stay reserved for the reference series. A pt1 run with a
verification is drawn as two runs, the sieve alone and the sieve with the proof
(proof_rows.py); both count as the logged run for SELECTED.
No tkinter here.
"""
import math
from collections import namedtuple

from . import line_names, proof_rows

X_FLOOR, X_WIDTH = "floor", "width"
X_MODES = (X_FLOOR, X_WIDTH)
AXIS_TITLE_KEYS = {X_FLOOR: "bench.axis_floor", X_WIDTH: "bench.axis_width"}

LAST, MIN, MAX, SELECTED, ALL = "last", "min", "max", "selected", "all"
CHOICES = (LAST, MIN, MAX, SELECTED, ALL)
CHOICE_LABEL_KEYS = {LAST: "bench.point_last", MIN: "bench.point_min",
                     MAX: "bench.point_max", SELECTED: "bench.point_selected",
                     ALL: "bench.point_all"}

# x_mode: X_FLOOR or X_WIDTH; choice: one of CHOICES; selected: the run (a row dict of the
# log, compared by identity) selected in the tab's table, None for none.
PointView = namedtuple("PointView", "x_mode choice selected", defaults=(X_FLOOR, LAST, None))
DEFAULT = PointView()

# Shade steps of one hue: mixed toward black, then white, in turns (arbitrary).
_SHADE_STEP = 0.3
_SHADE_MAX = 0.75


def check(view):
    if view.x_mode not in X_MODES:
        raise ValueError(f"unknown x mode {view.x_mode!r}")
    if view.choice not in CHOICES:
        raise ValueError(f"unknown point choice {view.choice!r}")
    return view


def floor_of(row):
    try:
        return int(row.get("base_exponent", ""))
    except (TypeError, ValueError):
        return None


def numbers_of(row):
    """The run's width (numbers_processed), None when unknown or not positive."""
    try:
        numbers = int(row.get("numbers_processed") or "")
    except (TypeError, ValueError):
        return None
    return numbers if numbers > 0 else None


def row_x(row, x_mode):
    """The run's x: its floor, or log10 of its width; None when unknown."""
    if x_mode == X_FLOOR:
        return floor_of(row)
    numbers = numbers_of(row)
    return math.log10(numbers) if numbers is not None else None


def floor_suffix(floor):
    return f" @ f{floor}"


def line_name(row, x_mode):
    """The run's line: line_names.line_name(), plus its floor in X_WIDTH."""
    name = line_names.line_name(row)
    return name + floor_suffix(floor_of(row)) if x_mode == X_WIDTH else name


def pick(candidates, choice, selected=None):
    """The (row, value) of a group: candidates are its (row, value) pairs in log order."""
    if choice == SELECTED:
        for row, value in candidates:
            if proof_rows.source(row) is selected:
                return row, value
        return candidates[-1]
    if choice == MIN:
        best = min(value for _row, value in candidates)
    elif choice == MAX:
        best = max(value for _row, value in candidates)
    else:
        return candidates[-1]
    return [c for c in candidates if c[1] == best][-1]


def chart_points(rows, row_value, view=DEFAULT):
    """{line: [(x, value, row)] ascending in x}: one point per group of `rows` whose
    row_value(row) is not None, every run of the group for ALL (module docstring)."""
    check(view)
    groups = {}
    for row in proof_rows.chart_rows(rows):
        if floor_of(row) is None:
            continue
        value = row_value(row)
        if value is None:
            continue
        x = row_x(row, view.x_mode)
        if x is None:
            continue
        groups.setdefault(line_name(row, view.x_mode), {}).setdefault(x, []).append((row, value))
    lines = {}
    for name, by_x in groups.items():
        points = []
        for x in sorted(by_x):
            chosen = by_x[x] if view.choice == ALL else [pick(by_x[x], view.choice,
                                                              view.selected)]
            points += [(x, value, row) for row, value in chosen]
        lines[name] = points
    return lines


def unplaced(rows, row_value, view=DEFAULT):
    """How many runs with a value have no x on this axis (a width-less run in X_WIDTH)."""
    return sum(1 for row in proof_rows.chart_rows(rows)
               if floor_of(row) is not None and row_value(row) is not None
               and row_x(row, view.x_mode) is None)


def x_label(x, x_mode):
    """The text of an x value: "28", or the width "10^11", "2x10^11"."""
    if x_mode == X_FLOOR:
        return str(int(round(x)))
    return line_names.width_label(round(10 ** x))


def shade(color, index):
    """`color` ("#rrggbb") for the index-th floor of a line family: 0 itself, then mixed
    toward black and white in turns, a step further every two floors."""
    if index <= 0:
        return color
    amount = min(_SHADE_MAX, _SHADE_STEP * ((index + 1) // 2))
    target = 0 if index % 2 else 255
    channels = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join("%02x" % round(c + (target - c) * amount) for c in channels)
