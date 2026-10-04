"""
tree_draw.py -- world-space draw data for one built sieve-lane tree view (tree_layout.py):
striped point markers, line segments and world-anchored labels. Pure numpy, no GL; the
renderer uploads the arrays (see TreeMode.marker_data/segment_data/world_labels).

Layout (world space, the camera fits [-max_radius, max_radius] on both axes):
  - Vertical: the real n axis. Value a (window start) sits at y = +max_radius (bottom
    of the screen, whose y grows downward) and a + h at y = -max_radius.
  - Horizontal has no numeric meaning: drawn terminal nodes take consecutive slots,
    an inner node sits over the mean of its children; one column per view prime and
    the n axis sit to the left of slot 0.
  - Every multiple of p in the root lane inside the window is a marker on p's column
    (so 6 is on both the 2 and the 3 column, at the same height). It is hollow when a
    smaller view prime divides it (caught earlier by the sieve), and striped with one
    color per distinct view prime dividing it, ascending (exponents ignored).
  - Each drawn free node gets an edge to each shown free child and one edge, in p's
    color, to its occupied child: that child's first value on p's column.
  - Each drawn terminal lane continues as a vertical line with a marker at every value
    up to the window top.

Marker row layout (MARKER_FLOATS float32 columns): x, y, size_px, hollow (0/1),
stripe_count, then MAX_STRIPES rgb triples. Highlight-layer rings come first in the
array, so they are drawn under the points they mark.
"""

import numpy as np

from primeatlas.visualization.shared.world_labels import (
    WorldLabel, ANCHOR_ABOVE, ANCHOR_LEFT_OF, ANCHOR_RIGHT_OF,
)
from primeatlas.visualization.tree.tree_colors import (
    prime_color, NEUTRAL_NODE_RGB, TERMINAL_LANE_RGB, EDGE_RGB, AXIS_RGB, OVERFLOW_STRIPE_RGB,
)
from primeatlas.visualization.tree.tree_layout import (
    column_lane, lane_values_in_window, prime_divisor_flags,
)
from primeatlas.visualization.tree.highlight_layers import POINT_NODE, POINT_LANE, POINT_COLUMN

MAX_STRIPES = 6
MARKER_FLOATS = 5 + 3 * MAX_STRIPES

_ROOT_SIZE_FACTOR = 1.4
_LANE_POINT_FACTOR = 0.8
_HIGHLIGHT_SIZE_FACTOR = 1.9
_EDGE_ALPHA = 0.75
_OCCUPIED_EDGE_ALPHA = 0.45
_COLUMN_LINE_ALPHA = 0.35
_LANE_LINE_ALPHA = 0.35
_AXIS_TICK_TARGET = 8
# From this many digits on, labels show values as offsets from the window start a (the
# full a is in the HUD), so neighboring labels stay distinguishable.
_OFFSET_LABEL_DIGITS = 13


def value_text(value, a):
    """Label text for `value` in a window starting at `a`."""
    if len(str(a)) < _OFFSET_LABEL_DIGITS:
        return f"{value:,}"
    return f"a+{value - a:,}"


class TreeStyle:
    """Sizes (pixels) and colors for one tree view. `colors`: {prime: rgb} overrides
    of the default per-prime palette. `max_stripes`: stripes drawn before the last one
    turns white to mean "more divisors"."""

    def __init__(self, node_size=11.0, point_size=7.0, max_stripes=4, colors=None):
        self.node_size = float(node_size)
        self.point_size = float(point_size)
        self.max_stripes = max(1, min(MAX_STRIPES, int(max_stripes)))
        self.colors = dict(colors or {})

    def color(self, p):
        return prime_color(p, self.colors)


class TreeDrawData:
    """The draw data of one view plus the world mapping used to build it."""

    def __init__(self, view, h, max_radius, slot_world, x_left):
        self.view = view
        self.h = h
        self.max_radius = max_radius
        self.slot_world = slot_world
        self._x_left = x_left
        self.markers = np.zeros((0, MARKER_FLOATS), dtype=np.float32)
        self.segments = np.zeros((0, 6), dtype=np.float32)
        self.labels = []
        self.pickables = []
        self.column_x = {}
        self.layer_counts = {}
        self._point_groups = []

    def x_of_slot(self, slot_units):
        return -self.max_radius + (slot_units - self._x_left) * self.slot_world

    def y_of(self, value):
        return self.max_radius - 2.0 * self.max_radius * ((value - self.view.a) / self.h)

    def node_xy(self, node):
        return self.x_of_slot(node.slot), self.y_of(node.value)

    @property
    def point_values(self):
        """One value per point marker (highlight rings excluded), in marker order."""
        values = []
        for kind, payload in self._point_groups:
            if kind == POINT_COLUMN:
                _, first, step, count = payload
                values.extend(first + t * step for t in range(count))
            else:
                values.extend(payload)
        return values


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


def _solid_rows(xs, ys, size, rgb, hollow=0.0):
    n = len(xs)
    colors = np.zeros((n, MAX_STRIPES, 3), dtype=np.float32)
    colors[:, 0] = rgb
    return _marker_rows(np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64),
                        size, hollow, np.ones(n), colors)


def _segment_pairs(pairs, rgb, alpha):
    """GL_LINES rows for [((x0, y0), (x1, y1)), ...] in one color."""
    rows = np.zeros((2 * len(pairs), 6), dtype=np.float32)
    for i, ((x0, y0), (x1, y1)) in enumerate(pairs):
        rows[2 * i, :2] = (x0, y0)
        rows[2 * i + 1, :2] = (x1, y1)
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


def build_tree_draw_data(view, h, max_radius, style, layers=()):
    """Markers, segments, labels and pickable nodes for `view` over the window
    [view.a, view.a + h)."""
    level_primes = view.level_primes
    depth = len(level_primes)
    col_gap = max(1.5, view.slot_count * 0.06)
    x_left = -(depth + 1) * col_gap
    span = max(1.0, (view.slot_count - 1) - x_left)
    slot_world = 2.0 * max_radius / span
    data = TreeDrawData(view, h, max_radius, slot_world, x_left)
    a = view.a
    top = a + h
    y_top = data.y_of(top)
    y_bottom = data.y_of(a)
    for j, p in enumerate(level_primes):
        data.column_x[p] = data.x_of_slot(-(depth - j) * col_gap)
    axis_x = data.x_of_slot(x_left)

    point_rows = []
    segment_blocks = []
    highlight_points = {layer.name: [] for layer in layers}

    # Free nodes.
    nodes = view.nodes
    node_xy = [data.node_xy(n) for n in nodes]
    sizes = np.full(len(nodes), style.node_size)
    sizes[0] = style.node_size * _ROOT_SIZE_FACTOR
    point_rows.append(_solid_rows([xy[0] for xy in node_xy], [xy[1] for xy in node_xy], sizes, NEUTRAL_NODE_RGB))
    data.pickables.extend((x, y, node) for node, (x, y) in zip(nodes, node_xy))
    data._point_groups.append((POINT_NODE, [n.value for n in nodes]))
    for layer in layers:
        for node, (x, y) in zip(nodes, node_xy):
            if layer.picks(node.value, POINT_NODE, None):
                highlight_points[layer.name].append((x, y, style.node_size))

    # Edges: free children and occupied children.
    free_edges = []
    occupied_edges = {p: [] for p in level_primes}
    index = {id(n): i for i, n in enumerate(nodes)}
    for node, xy in zip(nodes, node_xy):
        for child in node.children:
            free_edges.append((xy, node_xy[index[id(child)]]))
        if node.occupied is not None:
            occ = node.occupied
            occupied_edges[occ.prime].append((xy, (data.column_x[occ.prime], data.y_of(occ.value))))
    segment_blocks.append(_segment_pairs(free_edges, EDGE_RGB, _EDGE_ALPHA))
    for p, pairs in occupied_edges.items():
        segment_blocks.append(_segment_pairs(pairs, style.color(p), _OCCUPIED_EDGE_ALPHA))

    # Terminal lanes: a vertical line and a marker at every later value in the window.
    leaf_modulus = view.leaf_modulus
    lane_size = style.point_size * _LANE_POINT_FACTOR
    lane_lines = []
    lane_values = []
    lane_xs, lane_ys = [], []
    for node, (x, y) in zip(nodes, node_xy):
        if node.level != depth:
            continue
        if node.value < top:
            lane_lines.append(((x, y), (x, y_top)))
        value = node.value + leaf_modulus
        while value < top:
            lane_values.append(value)
            lane_xs.append(x)
            lane_ys.append(data.y_of(value))
            value += leaf_modulus
    segment_blocks.append(_segment_pairs(lane_lines, TERMINAL_LANE_RGB, _LANE_LINE_ALPHA))
    if lane_values:
        point_rows.append(_solid_rows(lane_xs, lane_ys, lane_size, TERMINAL_LANE_RGB))
    data._point_groups.append((POINT_LANE, lane_values))
    for layer in layers:
        for value, x, y in zip(lane_values, lane_xs, lane_ys):
            if layer.picks(value, POINT_LANE, None):
                highlight_points[layer.name].append((x, y, lane_size))

    # Prime columns: every multiple of p in the root lane inside the window.
    column_lines = []
    for j, p in enumerate(level_primes):
        x = data.column_x[p]
        residue, modulus = column_lane(view.root.residue, view.root.modulus, p)
        first, count = lane_values_in_window(a, h, residue, modulus)
        column_lines.append((p, ((x, y_bottom), (x, y_top))))
        data.labels.append(WorldLabel(x, y_top, f"p={p}", style.color(p), room=col_gap * slot_world,
                                      anchor=ANCHOR_ABOVE))
        data._point_groups.append((POINT_COLUMN, (p, first, modulus, count)))
        if count == 0:
            continue
        t = np.arange(count, dtype=np.float64)
        ys = max_radius - 2.0 * max_radius * ((first - a) / h + t * (modulus / h))
        flags = prime_divisor_flags(first, modulus, count, level_primes)
        hollow = flags[:, :j].any(axis=1).astype(np.float32) if j else np.zeros(count, dtype=np.float32)
        before = np.cumsum(flags, axis=1) - flags
        counts = flags.sum(axis=1)
        colors = np.zeros((count, MAX_STRIPES, 3), dtype=np.float32)
        for k, q in enumerate(level_primes):
            sel = flags[:, k] & (before[:, k] < style.max_stripes)
            if sel.any():
                colors[sel, before[sel, k]] = style.color(q)
        overflow = counts > style.max_stripes
        colors[overflow, style.max_stripes - 1] = OVERFLOW_STRIPE_RGB
        counts = np.minimum(counts, style.max_stripes)
        point_rows.append(_marker_rows(np.full(count, x), ys, style.point_size, hollow, counts, colors))
        for layer in layers:
            for i in layer.picks_column(p, first, modulus, count):
                highlight_points[layer.name].append((x, float(ys[i]), style.point_size))
    for p, pair in column_lines:
        segment_blocks.append(_segment_pairs([pair], style.color(p), _COLUMN_LINE_ALPHA))

    # n axis with ticks.
    axis_pairs = [((axis_x, y_bottom), (axis_x, y_top))]
    tick_len = 0.3 * col_gap * slot_world
    step = _nice_step(h, _AXIS_TICK_TARGET)
    tick = a + (-a) % step
    ticks = [a] + [v for v in range(tick, top + 1, step) if v != a][:4 * _AXIS_TICK_TARGET]
    for v in ticks:
        y = data.y_of(v)
        axis_pairs.append(((axis_x, y), (axis_x + tick_len, y)))
        data.labels.append(WorldLabel(axis_x, y, value_text(v, a), AXIS_RGB, anchor=ANCHOR_LEFT_OF))
    segment_blocks.append(_segment_pairs(axis_pairs, AXIS_RGB, 0.8))

    # Node labels: value, plus the hidden branches and their exact leaf count.
    for node, (x, y) in zip(nodes, node_xy):
        if node is view.root:
            text = f"{node.residue:,} mod {node.modulus:,}: {value_text(node.value, a)}"
            room = None
        else:
            text = value_text(node.value, a)
            room = node.leaf_span * slot_world
        if node.hidden_count:
            text += f"  +{node.hidden_count} ({node.hidden_leaves:,} leaves)"
        data.labels.append(WorldLabel(x, y, text, NEUTRAL_NODE_RGB, room=room, anchor=ANCHOR_RIGHT_OF))

    highlight_rows = []
    for layer in layers:
        picked = highlight_points[layer.name]
        data.layer_counts[layer.name] = len(picked)
        if picked:
            xs, ys, sizes = zip(*picked)
            highlight_rows.append(_solid_rows(xs, ys, np.array(sizes) * _HIGHLIGHT_SIZE_FACTOR,
                                              layer.rgb, hollow=1.0))
    blocks = highlight_rows + point_rows
    data.markers = np.concatenate(blocks) if blocks else data.markers
    blocks = [b for b in segment_blocks if len(b)]
    data.segments = np.concatenate(blocks) if blocks else data.segments
    return data
