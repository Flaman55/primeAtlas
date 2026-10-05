"""
tree_draw.py -- world-space draw data for one prime tree (tree_layout.py): striped point
markers, line segments and world-anchored labels. Pure numpy, no GL; the renderer
uploads the arrays (see TreeMode.marker_data/segment_data/world_labels).

Layout (world space, the camera fits [-max_radius, max_radius] on both axes):
  - Vertical: the tree's axis -- the real n axis, or the multiples axis (its values at
    equal steps, the gap between neighbors labelled "+gap") -- with a small pad on both
    ends; larger values are higher on screen (smaller world y, screen y grows downward).
  - Horizontal has no numeric meaning: the drawn leaves take consecutive slots, an inner
    copy sits over the mean of its children; one column per level prime sits right of
    the tree, the axis left of it.
  - Every copy of p is a node at its prime's height with an edge to each drawn child
    and a merge line, in p's color, to p's column at 2p; hidden branches are one dashed
    stub labelled "+N". The column holds a marker at every drawn multiple k*p (k >= 2):
    hollow when a smaller prime divides k, striped with one color per distinct level
    prime dividing it, ascending (exponents ignored). A value on several columns gets a
    horizontal link across them.

Marker row layout (MARKER_FLOATS float32 columns): x, y, size_px, hollow (0/1),
stripe_count, then MAX_STRIPES rgb triples. Highlight-layer rings come first in the
array, so they are drawn under the points they mark.
"""

import numpy as np

from primeatlas.visualization.shared.world_labels import WorldLabel, ANCHOR_LEFT_OF, ANCHOR_RIGHT_OF
from primeatlas.visualization.tree.tree_colors import prime_color, EDGE_RGB, AXIS_RGB, OVERFLOW_STRIPE_RGB
from primeatlas.visualization.tree.tree_layout import (
    AXIS_REAL, column_values, divisor_flags, hollow_flags,
)
from primeatlas.visualization.tree.highlight_layers import POINT_NODE, POINT_COLUMN

MAX_STRIPES = 6
MARKER_FLOATS = 5 + 3 * MAX_STRIPES

_HIGHLIGHT_SIZE_FACTOR = 1.9
_EDGE_ALPHA = 0.7
_MERGE_ALPHA = 0.35
_STUB_ALPHA = 0.55
_COLUMN_LINE_ALPHA = 0.5
_LINK_ALPHA = 0.3
_AXIS_TICK_TARGET = 8
# Window pad above the top and below the bottom, as a share of the axis length.
_WINDOW_PAD = 0.04
# Column spacing in slots: at least one slot, else this share of the tree width.
_COLUMN_GAP_SHARE = 0.12
# Hidden-branch stub: it points at the next position of its copy's fan (one child
# spacing right of the last drawn child) and covers this share of the way. A copy
# without drawn children points half a slot right and one level gap up (or this share
# of max_radius on a one-level tree).
_STUB_LENGTH = 0.55
_STUB_DY_SHARE = 0.08
_STUB_DASHES = 3
# A column label shows once its vertical spacing (world units, times this factor)
# covers the label's pixel width at the current zoom.
_LABEL_SPACING_FACTOR = 5.0
# From this many digits on, labels show values as offsets from the start prime (the
# full start is in the HUD), so neighboring labels stay distinguishable.
_OFFSET_LABEL_DIGITS = 13


def value_text(value, start):
    """Label text for `value` in a tree starting at `start`."""
    if len(str(start)) < _OFFSET_LABEL_DIGITS:
        return f"{value:,}"
    return f"s+{value - start:,}"


class TreeStyle:
    """Sizes (pixels) and colors for one tree view. `colors`: {prime: rgb} overrides of
    the default palette. `max_stripes`: stripes drawn before the last one turns white to
    mean "more divisors". `max_labels`: column-marker labels are left out past it."""

    def __init__(self, node_size=11.0, point_size=7.0, max_stripes=4, colors=None, max_labels=3000):
        self.node_size = float(node_size)
        self.point_size = float(point_size)
        self.max_stripes = max(1, min(MAX_STRIPES, int(max_stripes)))
        self.colors = dict(colors or {})
        self.max_labels = int(max_labels)

    def color(self, p, index):
        return prime_color(p, self.colors, index=index)


class TreeDrawData:
    """The draw data of one tree plus the world mapping used to build it.
    `hidden_stubs`: [(p, start, end)] (and `hidden_stub_nodes`, the same with the
    copy instead of p); `shared_links`: [(value, x0, x1)];
    `pickables`: [(x, y, prime)]."""

    def __init__(self, tree, max_radius, slot_world, x_left):
        self.tree = tree
        self.max_radius = max_radius
        self.slot_world = slot_world
        self._x_left = x_left
        length = tree.axis.length
        self._pad = max(0.5, _WINDOW_PAD * length)
        self._span = float(length) + 2.0 * self._pad
        self.markers = np.zeros((0, MARKER_FLOATS), dtype=np.float32)
        self.segments = np.zeros((0, 6), dtype=np.float32)
        self.labels = []
        self.pickables = []
        self.column_x = {}
        self.hidden_stubs = []
        self.hidden_stub_nodes = []
        self.shared_links = []
        self.layer_counts = {}
        self.point_values = []

    def x_of_slot(self, slot):
        return -self.max_radius + (slot - self._x_left) * self.slot_world

    def y_of_position(self, position):
        return self.max_radius - 2.0 * self.max_radius * (position + self._pad) / self._span

    def y_of(self, value):
        return self.y_of_position(float(self.tree.axis.position(value)))

    def node_xy(self, node):
        return self.x_of_slot(node.slot), self.y_of(node.p)

    @property
    def world_per_position(self):
        return 2.0 * self.max_radius / self._span


def _marker_rows(xs, ys, size, hollow, counts, colors):
    """Marker rows from per-point arrays; `colors` is (n, MAX_STRIPES, 3)."""
    n = len(xs)
    rows = np.zeros((n, MARKER_FLOATS), dtype=np.float32)
    rows[:, 0] = xs
    rows[:, 1] = ys
    rows[:, 2] = size
    rows[:, 3] = hollow
    rows[:, 4] = counts
    rows[:, 5:] = colors.reshape(n, 3 * MAX_STRIPES)
    return rows


def _solid_rows(xs, ys, size, rgbs, hollow=0.0):
    """Single-stripe rows; `rgbs` is one rgb or one rgb per point."""
    n = len(xs)
    colors = np.zeros((n, MAX_STRIPES, 3), dtype=np.float32)
    colors[:, 0] = rgbs
    return _marker_rows(np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64),
                        size, hollow, np.ones(n), colors)


def _segment_pairs(pairs, rgb, alpha):
    """GL_LINES rows for [((x0, y0), (x1, y1)), ...] in one color."""
    rows = np.zeros((2 * len(pairs), 6), dtype=np.float32)
    if pairs:
        ends = np.asarray(pairs, dtype=np.float64).reshape(-1, 2)
        rows[:, :2] = ends
    rows[:, 2:5] = rgb
    rows[:, 5] = alpha
    return rows


def _nice_step(span, target):
    """A 1/2/5 x 10^k step giving about `target` ticks over `span`."""
    raw = max(1, span // target)
    magnitude = 1
    while magnitude * 10 <= raw:
        magnitude *= 10
    for factor in (1, 2, 5, 10):
        if factor * magnitude >= raw:
            return factor * magnitude
    return 10 * magnitude


def _dashed(start, end, dashes):
    (x0, y0), (x1, y1) = start, end
    pairs = []
    for i in range(dashes):
        t0, t1 = (2 * i) / (2 * dashes - 1), (2 * i + 1) / (2 * dashes - 1)
        pairs.append(((x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0), (x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1)))
    return pairs


def build_tree_draw_data(tree, max_radius, style, layers=()):
    """Markers, segments, labels and pickable nodes for `tree` over its axis."""
    axis = tree.axis
    level_primes = tree.primes
    start = tree.start
    slots = max(1, tree.slot_count)
    col_gap = max(1.0, _COLUMN_GAP_SHARE * slots)
    axis_slot = -col_gap
    x_left = axis_slot - 1.2 * col_gap
    x_right = (slots - 1) + col_gap * (len(level_primes) + 1)
    slot_world = 2.0 * max_radius / (x_right - x_left)
    data = TreeDrawData(tree, max_radius, slot_world, x_left)
    for j, p in enumerate(level_primes):
        data.column_x[p] = data.x_of_slot((slots - 1) + col_gap * (j + 1))
    rgbs = [tuple(style.color(p, j)) for j, p in enumerate(level_primes)]
    y_bottom, y_top = data.y_of_position(0.0), data.y_of_position(float(axis.length))

    point_rows = []
    segment_blocks = []
    highlight_points = {layer.name: [] for layer in layers}

    # Copies, their edges, merge lines and hidden stubs.
    nodes = tree.nodes
    node_xy = [data.node_xy(n) for n in nodes]
    index = {id(n): i for i, n in enumerate(nodes)}
    point_rows.append(_solid_rows([xy[0] for xy in node_xy], [xy[1] for xy in node_xy], style.node_size,
                                  np.array([rgbs[n.level] for n in nodes], dtype=np.float32)))
    data.point_values.extend(n.p for n in nodes)
    edges = []
    merges = {p: [] for p in level_primes}
    stubs = []
    level_gap = {}
    for node, (x, y) in zip(nodes, node_xy):
        if node.parent is not None and node.level not in level_gap:
            level_gap[node.level] = y - node_xy[index[id(node.parent)]][1]
    for node, (x, y) in zip(nodes, node_xy):
        data.pickables.append((x, y, node.p))
        data.labels.append(WorldLabel(x, y, value_text(node.p, start), rgbs[node.level],
                                      room=node.leaf_span * slot_world, anchor=ANCHOR_RIGHT_OF))
        for child in node.children:
            edges.append(((x, y), node_xy[index[id(child)]]))
        merges[node.p].append(((x, y), (data.column_x[node.p], data.y_of(2 * node.p))))
        if node.hidden:
            if node.children:
                child_xy = [node_xy[index[id(c)]] for c in node.children]
                spacing = child_xy[1][0] - child_xy[0][0] if len(child_xy) > 1 else slot_world
                target = (child_xy[-1][0] + spacing, child_xy[-1][1])
            else:
                target = (x + 0.5 * slot_world, y + level_gap.get(node.level, -_STUB_DY_SHARE * max_radius))
            end = (x + _STUB_LENGTH * (target[0] - x), y + _STUB_LENGTH * (target[1] - y))
            data.hidden_stubs.append((node.p, (x, y), end))
            data.hidden_stub_nodes.append((node, (x, y), end))
            stubs.extend(_dashed((x, y), end, _STUB_DASHES))
            data.labels.append(WorldLabel(end[0], end[1], f"+{node.hidden:,}", EDGE_RGB,
                                          room=node.leaf_span * slot_world, anchor=ANCHOR_RIGHT_OF))
        for layer in layers:
            if layer.picks(node.p, POINT_NODE, None):
                highlight_points[layer.name].append((x, y, style.node_size))
    segment_blocks.append(_segment_pairs(edges, EDGE_RGB, _EDGE_ALPHA))
    segment_blocks.append(_segment_pairs(stubs, EDGE_RGB, _STUB_ALPHA))
    for j, p in enumerate(level_primes):
        segment_blocks.append(_segment_pairs(merges[p], rgbs[j], _MERGE_ALPHA))

    # Columns of multiples.
    links = []
    label_budget = style.max_labels
    for j, p in enumerate(level_primes):
        x = data.column_x[p]
        ks = column_values(tree, p)
        count = len(ks)
        if count == 0:
            continue
        if axis.kind == AXIS_REAL:
            positions = (ks - 1).astype(np.float64) * float(p) + float(p - axis.bottom)
            values = None
        else:
            values = [int(k) * p for k in ks]
            positions = np.array([axis.position(v) for v in values], dtype=np.float64)
        ys = data.y_of_position(positions)
        segment_blocks.append(_segment_pairs([((x, float(ys[0])), (x, float(ys[-1])))], rgbs[j], _COLUMN_LINE_ALPHA))
        hollow = hollow_flags(p, ks).astype(np.float32)
        flags = divisor_flags(j, ks, level_primes)
        before = np.cumsum(flags, axis=1) - flags
        counts = flags.sum(axis=1)
        colors = np.zeros((count, MAX_STRIPES, 3), dtype=np.float32)
        for q_index, q in enumerate(level_primes):
            sel = flags[:, q_index] & (before[:, q_index] < style.max_stripes)
            if sel.any():
                colors[sel, before[sel, q_index]] = rgbs[q_index]
        colors[counts > style.max_stripes, style.max_stripes - 1] = OVERFLOW_STRIPE_RGB
        point_rows.append(_marker_rows(np.full(count, x), ys, style.point_size, hollow,
                                       np.minimum(counts, style.max_stripes), colors))
        if values is None:
            values = [int(k) * p for k in ks]
        data.point_values.extend(values)
        for layer in layers:
            for t in layer.picks_column(p, 2 * p, p, count):
                highlight_points[layer.name].append((x, float(ys[t]), style.point_size))

        for t in np.nonzero((counts >= 2) & (flags.argmax(axis=1) == j))[0]:
            last = len(level_primes) - 1 - int(np.argmax(flags[t, ::-1]))
            x1 = data.column_x[level_primes[last]]
            data.shared_links.append((values[t], x, x1))
            links.append(((x, float(ys[t])), (x1, float(ys[t]))))

        if count <= label_budget:
            label_budget -= count
            spacing = p if axis.kind == AXIS_REAL else 1
            room = min(0.9 * col_gap * slot_world, _LABEL_SPACING_FACTOR * spacing * data.world_per_position)
            for t in range(count):
                data.labels.append(WorldLabel(x, float(ys[t]), value_text(values[t], start), rgbs[j],
                                              room=room, anchor=ANCHOR_RIGHT_OF))
    segment_blocks.append(_segment_pairs(links, EDGE_RGB, _LINK_ALPHA))

    # The vertical axis: real ticks, or every multiples-axis value with the gaps between.
    axis_x = data.x_of_slot(axis_slot)
    axis_pairs = [((axis_x, y_bottom), (axis_x, y_top))]
    tick_len = 0.15 * col_gap * slot_world
    if axis.kind == AXIS_REAL:
        step = _nice_step(axis.length, _AXIS_TICK_TARGET)
        first = axis.bottom + (-axis.bottom) % step
        ticks = [axis.bottom] + [v for v in range(first, axis.top + 1, step) if v != axis.bottom]
        ticks = ticks[:4 * _AXIS_TICK_TARGET]
    else:
        ticks = list(axis.values)
    for v in ticks:
        y = data.y_of(v)
        axis_pairs.append(((axis_x, y), (axis_x + tick_len, y)))
        data.labels.append(WorldLabel(axis_x, y, value_text(v, start), AXIS_RGB, anchor=ANCHOR_LEFT_OF))
    if axis.kind != AXIS_REAL:
        for lo, hi in zip(axis.values, axis.values[1:]):
            y = (data.y_of(lo) + data.y_of(hi)) / 2.0
            data.labels.append(WorldLabel(axis_x, y, f"+{hi - lo:,}", EDGE_RGB, anchor=ANCHOR_RIGHT_OF))
    segment_blocks.append(_segment_pairs(axis_pairs, AXIS_RGB, 0.8))

    highlight_rows = []
    for layer in layers:
        picked = highlight_points[layer.name]
        data.layer_counts[layer.name] = len(picked)
        if picked:
            hx, hy, sizes = zip(*picked)
            highlight_rows.append(_solid_rows(hx, hy, np.array(sizes) * _HIGHLIGHT_SIZE_FACTOR,
                                              layer.rgb, hollow=1.0))
    blocks = highlight_rows + point_rows
    data.markers = np.concatenate(blocks) if blocks else data.markers
    blocks = [b for b in segment_blocks if len(b)]
    data.segments = np.concatenate(blocks) if blocks else data.segments
    return data
