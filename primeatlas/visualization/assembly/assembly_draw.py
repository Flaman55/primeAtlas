"""
assembly_draw.py -- world-space draw data for one frame of the assembly animation
(assembly_layout.py): striped point markers, line segments and world-anchored labels in
the marker/segment format of tree/tree_draw.py. Pure numpy, no GL.

Layout (world space, the camera fits [-max_radius, max_radius] on both axes; smaller
world y is higher on screen):
  - Left half: the floors. Floor 0 is the base (period 1, one lane); floor f >= 1 is the
    level built by step f-1, labelled with its prime, period and lanes. Assembled floors
    are one trunk: every finished level is a single branch, however many lanes it holds.
  - The current step s fans out of floor s into q copy tips one floor up. Copy phase: the
    branches grow. Strike phase: copy by copy, the lanes whose copy is a multiple of q
    turn q's color (drawn as dots on each tip while the lanes fit lane_dots; the tip
    label reads "lanes before -> after"). Collapse phase: the tips draw together into
    the next floor's node.
  - Right half: the grid of the step (while q * period <= detail_cells): q rows, one copy
    of the period each, so a lane is a column. Rows appear during the copy phase; struck
    cells (in q's color) row by row during the strike phase; in the prime phase every
    survivor in (1, next_prime^2) pulses -- all of them are prime; during the collapse
    the rows slide into one row of the new period. Cells caught by an earlier prime are
    hollow, in that prime's color. Values are labelled from the largest multiple of the
    new period <= base_n.
"""

import math

import numpy as np

from primeatlas.visualization.assembly.assembly_layout import PHASE_COLLAPSE, PHASE_COPY, PHASE_PRIME, PHASE_STRIKE
from primeatlas.visualization.shared.world_labels import ANCHOR_ABOVE, ANCHOR_RIGHT_OF, WorldLabel
from primeatlas.visualization.tree.tree_colors import EDGE_RGB, NEUTRAL_NODE_RGB, prime_color
from primeatlas.visualization.tree.tree_draw import MARKER_FLOATS, _segment_pairs, _solid_rows, value_text
from primeatlas.visualization.tree.tree_hud import count_text

# Floors: their x as a share of max_radius, and the fan's total width.
_FLOOR_X_SHARE = -0.5
_FAN_WIDTH_SHARE = 0.9
# Lane dots: a square block filling this share of the spacing between two copy tips.
_DOT_ROW_SHARE = 0.8
# Grid cells and lane dots shrink to this share of their spacing at the launch view
# (one world unit is one pixel there), but not below the minimum size in pixels.
_SPACING_FILL = 0.85
_MIN_MARKER_PX = 3.0
# Tip labels sit this share of the floor gap above the tip.
_TIP_LABEL_SHARE = 0.12
# Grid panel: x range and height as shares of max_radius.
_GRID_X0_SHARE = 0.08
_GRID_X1_SHARE = 0.98
_GRID_HEIGHT_SHARE = 1.6
_GRID_HEADER_SHARE = 0.05
# Prime-phase highlight ring: size factor at its peak, and the next prime's extra pulse.
_HIGHLIGHT_RING = 1.8
_NEXT_PRIME_PULSE = 1.0
_TRUNK_ALPHA = 0.8
_BRANCH_ALPHA = 0.7
_DIM_RGB = (0.45, 0.45, 0.5)
_HIGHLIGHT_RGB = (1.0, 1.0, 1.0)
# Cell labels show once the cell spacing covers their width this many times over, so
# they never run into the neighboring rows.
_CELL_LABEL_ROOM = 0.45


class AssemblyStyle:
    """Sizes (pixels), caps and colors of the animation. `colors`: {prime: rgb}
    overrides. `lane_dots`: lanes drawn as dots per copy at most; `detail_cells`: grid
    cells drawn at most (0 = no grid); `max_labels`: cell labels at most."""

    def __init__(self, node_size=15.0, cell_size=12.0, colors=None, lane_dots=48, detail_cells=2310,
                 max_labels=3000):
        self.node_size = float(node_size)
        self.cell_size = float(cell_size)
        self.colors = dict(colors or {})
        self.lane_dots = int(lane_dots)
        self.detail_cells = int(detail_cells)
        self.max_labels = int(max_labels)

    def color(self, p, index):
        return prime_color(p, self.colors, index=index)


class GridInfo:
    """What the grid of one step shows: `rows` copies of `cols` cells, values labelled
    from `base`; the struck and highlighted values (sorted, without base)."""

    def __init__(self, step_index, rows, cols, base):
        self.step_index = step_index
        self.rows = rows
        self.cols = cols
        self.cells = rows * cols
        self.base = base
        self.struck_values = []
        self.highlighted_values = []


class AssemblyDrawData:
    """One frame's arrays plus the world mapping. `floor_xy`: drawn floors' nodes;
    `pickables`: [(x, y, floor)] for floors >= 1; `tips`: the current copies' positions;
    `struck_per_copy`: removed lanes revealed per copy (None when not enumerated)."""

    def __init__(self, steps, max_radius):
        self.max_radius = float(max_radius)
        self.floor_gap = 2.0 * self.max_radius / (len(steps) + 1)
        self.floor_x = _FLOOR_X_SHARE * self.max_radius
        self.markers = np.zeros((0, MARKER_FLOATS), dtype=np.float32)
        self.segments = np.zeros((0, 6), dtype=np.float32)
        self.labels = []
        self.floor_xy = []
        self.pickables = []
        self.tips = []
        self.struck_per_copy = None
        self.lane_dots_drawn = False
        self.grid = None

    def floor_y(self, floor):
        return self.max_radius - (floor + 0.5) * self.floor_gap


def block_rows_of(lanes_count):
    cols = int(math.ceil(math.sqrt(max(1, lanes_count))))
    return int(math.ceil(max(1, lanes_count) / cols))


def floor_text(steps, floor):
    if floor == 0:
        return "period 1  1 lane"
    st = steps[floor - 1]
    lanes = st.lanes_after
    return f"p={st.q:,}  period {count_text(st.period_after)}  {count_text(lanes)} lane{'s' if lanes != 1 else ''}"


def _marker_px(spacing_world, max_px):
    return max(_MIN_MARKER_PX, min(float(max_px), _SPACING_FILL * spacing_world))


def _revealed(phase, frac, j, q):
    if phase == PHASE_STRIKE:
        return frac >= (j + 1) / q
    return phase > PHASE_STRIKE


def build_assembly_draw_data(steps, step_index, phase, frac, max_radius, style, base_n=0, detail_step=None):
    """Markers, segments, labels and pickable floors of step `step_index` at `phase`
    (an index into PHASES) and `frac` in [0, 1]."""
    data = AssemblyDrawData(steps, max_radius)
    st = steps[step_index]
    q, period, lanes_count = st.q, st.period_before, st.lanes_before
    fx = data.floor_x
    marker_blocks, segment_blocks = [], []

    # Assembled floors and the trunk between them.
    top_floor = step_index + (1 if phase == PHASE_COLLAPSE and frac >= 1.0 else 0)
    floors = [(fx, data.floor_y(f)) for f in range(top_floor + 1)]
    data.floor_xy = floors[:step_index + 1]
    floor_rgbs = [NEUTRAL_NODE_RGB] + [tuple(style.color(steps[f - 1].q, f - 1)) for f in range(1, top_floor + 1)]
    marker_blocks.append(_solid_rows([x for x, _ in floors], [y for _, y in floors], style.node_size,
                                     np.array(floor_rgbs, dtype=np.float32)))
    segment_blocks.append(_segment_pairs(list(zip(floors, floors[1:])), EDGE_RGB, _TRUNK_ALPHA))
    for f, (x, y) in enumerate(floors):
        data.labels.append(WorldLabel(x, y, floor_text(steps, f), floor_rgbs[f], anchor=ANCHOR_RIGHT_OF))
        if 1 <= f <= step_index:
            data.pickables.append((x, y, f))

    # The fan of q copies.
    q_rgb = tuple(style.color(q, step_index))
    node = floors[step_index]
    spacing = _FAN_WIDTH_SHARE * data.max_radius / q
    tip_y = data.floor_y(step_index + 1)
    target = (fx, tip_y)
    tips = []
    for j in range(q):
        full = (fx + (j - (q - 1) / 2.0) * spacing, tip_y)
        if phase == PHASE_COPY:
            pos = (node[0] + frac * (full[0] - node[0]), node[1] + frac * (full[1] - node[1]))
        elif phase == PHASE_COLLAPSE:
            pos = (full[0] + frac * (target[0] - full[0]), full[1] + frac * (target[1] - full[1]))
        else:
            pos = full
        tips.append(pos)
    data.tips = tips
    segment_blocks.append(_segment_pairs([(node, t) for t in tips], q_rgb, _BRANCH_ALPHA))

    removed = st.removed_per_copy
    revealed = [_revealed(phase, frac, j, q) for j in range(q)]
    if removed is not None:
        data.struck_per_copy = [removed[j] if revealed[j] else 0 for j in range(q)]
    shrink = (1.0 - frac) if phase == PHASE_COLLAPSE else 1.0
    if removed is not None and lanes_count <= style.lane_dots:
        data.lane_dots_drawn = True
        lanes = st.lanes()
        block_cols = int(math.ceil(math.sqrt(lanes_count)))
        dot_step = _DOT_ROW_SHARE * spacing / block_cols
        dot_px = _marker_px(dot_step, style.cell_size)
        index = np.arange(lanes_count)
        col, row = index % block_cols, index // block_cols
        dx = (col - (block_cols - 1) / 2.0) * dot_step * shrink
        dy = -row * dot_step * shrink
        for j, (tx, ty) in enumerate(tips):
            struck = ((lanes + j * period) % q == 0) & revealed[j]
            rgbs = np.where(struck[:, None], np.array(q_rgb), np.array(NEUTRAL_NODE_RGB)).astype(np.float32)
            hollow = 1.0 if phase == PHASE_COLLAPSE else 0.0
            alive = ~struck
            marker_blocks.append(_solid_rows(tx + dx[alive], ty + dy[alive], dot_px, rgbs[alive]))
            if struck.any():
                marker_blocks.append(_solid_rows(tx + dx[struck], ty + dy[struck], dot_px, rgbs[struck],
                                                 hollow=hollow))
    else:
        marker_blocks.append(_solid_rows([t[0] for t in tips], [t[1] for t in tips], style.node_size, q_rgb))
    if phase in (PHASE_STRIKE, PHASE_PRIME):
        for j, (tx, ty) in enumerate(tips):
            if removed is None:
                text = f"{count_text(lanes_count)} lanes"
            elif revealed[j]:
                text = f"{count_text(lanes_count)} -> {count_text(lanes_count - removed[j])}"
            else:
                text = count_text(lanes_count)
            block_top = (block_rows_of(lanes_count) - 1) * _DOT_ROW_SHARE * spacing / max(
                1, int(math.ceil(math.sqrt(lanes_count)))) if data.lane_dots_drawn else 0.0
            data.labels.append(WorldLabel(tx, ty - block_top - _TIP_LABEL_SHARE * data.floor_gap, text,
                                          q_rgb if revealed[j] else NEUTRAL_NODE_RGB, room=spacing,
                                          anchor=ANCHOR_ABOVE))

    # The grid of the step (or of the clicked floor's step, in its final state).
    if detail_step is not None:
        grid_step, grid_phase, grid_frac = detail_step, PHASE_STRIKE, 1.0
    else:
        grid_step, grid_phase, grid_frac = step_index, phase, frac
    gst = steps[grid_step]
    if 0 < gst.q * gst.period_before <= style.detail_cells:
        _add_grid(data, steps, gst, grid_phase, grid_frac, style, base_n, marker_blocks, segment_blocks)

    blocks = [b for b in marker_blocks if len(b)]
    if blocks:
        data.markers = np.concatenate(blocks)
    blocks = [b for b in segment_blocks if len(b)]
    if blocks:
        data.segments = np.concatenate(blocks)
    return data


def _add_grid(data, steps, st, phase, frac, style, base_n, marker_blocks, segment_blocks):
    R = data.max_radius
    q, cols = st.q, st.period_before
    rows = q
    base = (int(base_n) // st.period_after) * st.period_after
    grid = GridInfo(st.index, rows, cols, base)
    data.grid = grid

    x0 = _GRID_X0_SHARE * R
    width = (_GRID_X1_SHARE - _GRID_X0_SHARE) * R
    cell = min(width / cols, _GRID_HEIGHT_SHARE * R / rows)
    y0 = -rows * cell / 2.0
    r = np.tile(np.arange(cols, dtype=np.int64), rows)
    j = np.repeat(np.arange(rows, dtype=np.int64), cols)
    v = r + j * cols
    xs = x0 + (r + 0.5) * cell
    ys = y0 + (j + 0.5) * cell
    if phase == PHASE_COLLAPSE:
        line_cell = width / (rows * cols)
        xs = xs + frac * (x0 + (v + 0.5) * line_cell - xs)
        ys = ys + frac * (0.0 - ys)
        cell_room = cell + frac * (line_cell - cell)
    else:
        cell_room = cell
    visible = np.ones(len(v), dtype=bool)
    if phase == PHASE_COPY:
        visible = (j == 0) | (frac * (rows - 1) >= j)

    # The smallest earlier prime dividing r (index into primes_before), -1 for a lane.
    first_divisor = np.full(cols, -1, dtype=np.int64)
    for index in range(len(st.primes_before) - 1, -1, -1):
        first_divisor[np.arange(cols) % st.primes_before[index] == 0] = index
    lane = first_divisor[r] < 0
    row_revealed = np.array([_revealed(phase, frac, row, q) for row in range(rows)])
    struck = lane & (v % q == 0) & row_revealed[j]
    q_rgb = np.array(style.color(q, st.index), dtype=np.float32)

    rgbs = np.tile(np.array(NEUTRAL_NODE_RGB, dtype=np.float32), (len(v), 1))
    dead = ~lane
    if dead.any():
        palette = np.array([style.color(p, i) for i, p in enumerate(st.primes_before)], dtype=np.float32)
        rgbs[dead] = palette[first_divisor[r[dead]]]
    rgbs[struck] = q_rgb
    solid = visible & lane & ~struck
    hollow_cells = visible & (dead | (struck & (phase == PHASE_COLLAPSE)))
    struck_solid = visible & struck & (phase != PHASE_COLLAPSE)
    cell_px = _marker_px(cell_room, style.cell_size)
    for mask, hollow in ((hollow_cells, 1.0), (solid, 0.0), (struck_solid, 0.0)):
        if mask.any():
            marker_blocks.append(_solid_rows(xs[mask], ys[mask], cell_px, rgbs[mask], hollow=hollow))
    grid.struck_values = [int(x) for x in np.sort(v[struck & visible])]

    if phase == PHASE_PRIME and 0.0 < frac < 1.0:
        pulse = math.sin(math.pi * frac)
        survivors = visible & lane & ~struck & (v > 1) & (v < st.square)
        grid.highlighted_values = [int(x) for x in np.sort(v[survivors])]
        if survivors.any():
            marker_blocks.insert(0, _solid_rows(xs[survivors], ys[survivors],
                                                cell_px * (1.0 + (_HIGHLIGHT_RING - 1.0) * pulse),
                                                _HIGHLIGHT_RGB, hollow=1.0))
        nxt = (v == st.next_prime) & visible
        if nxt.any():
            marker_blocks.insert(0, _solid_rows(xs[nxt], ys[nxt],
                                                cell_px * (_HIGHLIGHT_RING + _NEXT_PRIME_PULSE * pulse),
                                                _HIGHLIGHT_RGB, hollow=1.0))

    data.labels.append(WorldLabel(x0, y0 - _GRID_HEADER_SHARE * R, f"{q} copies x {cols:,}", tuple(q_rgb),
                                  anchor=ANCHOR_RIGHT_OF))
    if int(visible.sum()) <= style.max_labels:
        for index in np.nonzero(visible)[0]:
            rgb = tuple(rgbs[index]) if lane[index] else _DIM_RGB
            data.labels.append(WorldLabel(float(xs[index]), float(ys[index]) - 0.5 * cell_room,
                                          value_text(base + int(v[index]), base), rgb,
                                          room=_CELL_LABEL_ROOM * cell_room,
                                          anchor=ANCHOR_ABOVE))
