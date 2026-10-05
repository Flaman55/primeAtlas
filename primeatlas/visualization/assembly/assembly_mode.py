"""
assembly_mode.py -- AssemblyMode, the assembly animation viz-mode (see shared/mode.py):
level k+1 of the wheel built from level k by copying -- q copies of the period, minus the
multiples of q. The arithmetic is assembly_layout.py, one frame's draw data
assembly_draw.py, the HUD assembly_hud.py; this class holds the animation position and
the navigation.

The animation is a position t on a Timeline (each step plays copy, strike, prime and
collapse, --assembly-frames ticks each); the session's N only sets the base the grid
values are labelled from; the HUD N is the period shown. Everything is computed, so it runs with --source none and has
no prime ceiling.

Navigation: Space plays (one frame per tick, stops at the end), Right/Left jump to the
next/previous phase (Ctrl: step), Home restarts. Clicking an assembled floor shows its
step's grid; Backspace returns to the current step's. R resets to the start.

--assembly-bare draws the animation without any number (no labels, no on-canvas HUD).
"""

import time

import numpy as np

from primeatlas.visualization.assembly.assembly_draw import AssemblyStyle, build_assembly_draw_data
from primeatlas.visualization.assembly.assembly_hud import assembly_hud_lines
from primeatlas.visualization.assembly.assembly_layout import PHASE_PRIME, Timeline, build_steps
from primeatlas.visualization.shared.mode import VizMode
from primeatlas.visualization.tree.tree_colors import parse_color_map

_DEFAULTS = {
    "assembly_depth": 6,
    "assembly_frames": 12,
    "assembly_lane_dots": 48,
    "assembly_detail_cells": 2310,
    "assembly_max_labels": 3000,
    "assembly_max_lanes": 200_000,
    "assembly_node_size": 15.0,
    "assembly_cell_size": 12.0,
    "assembly_label_font_size": 35,
    "assembly_cell_spacing": "auto",
}

# A click within this many pixels of a floor's node picks it.
_PICK_RADIUS_PX = 14.0


class AssemblyMode(VizMode):
    name = "assembly"
    window_title = "PrimeAtlas -- Assembly"
    count_label = "lanes"
    n_label = "period"
    draws_center_marker = False
    uses_prime_ceiling = False

    def __init__(self, session, config):
        super().__init__(session, config)
        get = lambda key: config.get(key, _DEFAULTS[key])  # noqa: E731
        self.steps = build_steps(int(get("assembly_depth")), max_lanes=int(get("assembly_max_lanes")))
        self.timeline = Timeline(len(self.steps), int(get("assembly_frames")))
        self.label_font_size = int(get("assembly_label_font_size"))
        self.style = AssemblyStyle(node_size=get("assembly_node_size"), cell_size=get("assembly_cell_size"),
                                   colors=config.get("assembly_colors") or {},
                                   lane_dots=get("assembly_lane_dots"), detail_cells=get("assembly_detail_cells"),
                                   max_labels=get("assembly_max_labels"),
                                   cell_spacing=_spacing_value(get("assembly_cell_spacing")))
        self.bare = bool(config.get("assembly_bare", False))
        self.draws_hud = not self.bare
        self.position = 0
        self.detail_step = None
        self.draw = None

    # -- launch -----------------------------------------------------------------

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument("--assembly-depth", type=int, default=_DEFAULTS["assembly_depth"],
                            help="assembly mode: steps (primes 2, 3, 5, ...) the animation assembles")
        parser.add_argument("--assembly-frames", type=int, default=_DEFAULTS["assembly_frames"],
                            help="assembly mode: ticks per phase (copy, strike, prime, collapse)")
        parser.add_argument("--assembly-lane-dots", type=int, default=_DEFAULTS["assembly_lane_dots"],
                            help="assembly mode: lanes drawn as dots on each copy at most; past it only counts")
        parser.add_argument("--assembly-detail-cells", type=int, default=_DEFAULTS["assembly_detail_cells"],
                            help="assembly mode: grid cells (q x period) drawn at most; 0 = no grid")
        parser.add_argument("--assembly-max-labels", type=int, default=_DEFAULTS["assembly_max_labels"],
                            help="assembly mode: grid value labels at most")
        parser.add_argument("--assembly-max-lanes", type=int, default=_DEFAULTS["assembly_max_lanes"],
                            help="assembly mode: lanes enumerated at most (per-copy removals); past it only "
                                 "the counts")
        parser.add_argument("--assembly-node-size", type=float, default=_DEFAULTS["assembly_node_size"],
                            help="assembly mode: floor and copy marker size in pixels")
        parser.add_argument("--assembly-cell-size", type=float, default=_DEFAULTS["assembly_cell_size"],
                            help="assembly mode: grid cell and lane dot size in pixels")
        parser.add_argument("--assembly-cell-spacing", type=str, default=_DEFAULTS["assembly_cell_spacing"],
                            help="assembly mode: grid cell spacing in pixels at the launch view, or 'auto' "
                                 "to fit the grid and shrink cells to their spacing")
        parser.add_argument("--assembly-label-font-size", type=int, default=_DEFAULTS["assembly_label_font_size"],
                            help="assembly mode: pixel size of the labels")
        parser.add_argument("--assembly-colors", type=str, default="",
                            help="assembly mode: per-prime color overrides, e.g. '2=#ff0000,3=#00aaff'")
        parser.add_argument("--assembly-bare", action="store_true",
                            help="assembly mode: draw without labels and HUD")

    @classmethod
    def validate_arguments(cls, parser, args):
        if args.assembly_depth < 1:
            parser.error(f"--assembly-depth must be >= 1, got {args.assembly_depth}")
        if args.assembly_frames < 1:
            parser.error(f"--assembly-frames must be >= 1, got {args.assembly_frames}")
        for flag, value in (("--assembly-lane-dots", args.assembly_lane_dots),
                            ("--assembly-detail-cells", args.assembly_detail_cells),
                            ("--assembly-max-labels", args.assembly_max_labels)):
            if value < 0:
                parser.error(f"{flag} must be >= 0, got {value}")
        if args.assembly_max_lanes < 1:
            parser.error(f"--assembly-max-lanes must be >= 1, got {args.assembly_max_lanes}")
        try:
            _spacing_value(args.assembly_cell_spacing)
        except ValueError as e:
            parser.error(f"--assembly-cell-spacing: {e}")
        try:
            parse_color_map(args.assembly_colors)
        except ValueError as e:
            parser.error(f"--assembly-colors: {e}")

    @classmethod
    def prepare_launch(cls, args, launch):
        config = {key: getattr(args, key) for key in _DEFAULTS}
        config["assembly_colors"] = parse_color_map(args.assembly_colors)
        config["assembly_cell_spacing"] = _spacing_value(args.assembly_cell_spacing)
        config["assembly_bare"] = bool(args.assembly_bare)
        return config

    # -- frame data -------------------------------------------------------------

    def rebuild(self, n_value, prev_ring_count=None, advancing=False, audio=None):
        """Builds the frame at the current position. The ring point buffers stay empty:
        the animation draws through marker_data/segment_data/world_labels."""
        s = self.session
        t0 = time.perf_counter()
        step, phase, frac = self.timeline.locate(self.position)
        self.draw = build_assembly_draw_data(self.steps, step, phase, frac, s.max_radius, self.style,
                                             base_n=max(0, int(n_value)), detail_step=self.detail_step)
        t1 = time.perf_counter()
        st = self.steps[step]
        base = (max(0, int(n_value)) // st.period_after) * st.period_after
        done = phase >= PHASE_PRIME
        s.hud_n = st.period_after if done else st.period_before
        s.hud_count = st.lanes_after if done else st.lanes_before
        s.hud_rebuild_ms = round(1000 * (t1 - t0), 1)
        s.hud_lines = assembly_hud_lines(self.steps, step, phase, base, self.detail_step)
        empty = np.zeros((0, 5), dtype=np.float32)
        return empty, empty, 0, 0

    def marker_data(self):
        return None if self.draw is None else self.draw.markers

    def segment_data(self):
        return None if self.draw is None else self.draw.segments

    def world_labels(self):
        return [] if self.draw is None or self.bare else self.draw.labels

    # -- navigation -------------------------------------------------------------

    def _move_to(self, position):
        self.position = self.timeline.clamp(position)
        self.session.n_force_rebuild = True

    def tick(self):
        if self.position >= self.timeline.total:
            self.session.playback_running = False
            return True
        self._move_to(self.position + 1)
        return False

    def scrub(self, is_right, ctrl_held):
        if is_right:
            self._move_to(self.timeline.next_boundary(self.position, per_step=ctrl_held))
        else:
            self._move_to(self.timeline.prev_boundary(self.position, per_step=ctrl_held))
        return True

    def click(self, world_x, world_y, world_per_pixel):
        """Shows the grid of the step that built the nearest assembled floor within the
        pick radius."""
        if self.draw is None:
            return False
        radius = _PICK_RADIUS_PX * world_per_pixel
        best = None
        for x, y, floor in self.draw.pickables:
            d2 = (x - world_x) ** 2 + (y - world_y) ** 2
            if d2 <= radius * radius and (best is None or d2 < best[0]):
                best = (d2, floor)
        if best is None:
            return False
        self.detail_step = best[1] - 1
        return True

    def key(self, name):
        if name == "home":
            self.position = 0
            self.detail_step = None
            return True
        if name == "backspace":
            if self.detail_step is None:
                return False
            self.detail_step = None
            return True
        return False

    def reset_state(self):
        self.position = 0
        self.detail_step = None


def _spacing_value(value):
    """None for 'auto' (or None), else a spacing > 0 as float; ValueError otherwise."""
    if value is None or (isinstance(value, str) and value.strip().lower() in ("", "auto")):
        return None
    try:
        spacing = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{value!r} is neither 'auto' nor a number") from None
    if not spacing > 0:
        raise ValueError(f"must be > 0, got {value!r}")
    return spacing
