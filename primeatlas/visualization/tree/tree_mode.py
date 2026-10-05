"""
tree_mode.py -- TreeMode, the prime tree viz-mode (see shared/mode.py): consecutive primes
starting at the largest prime <= N, every copy of p branching into copies of the next
prime and feeding p's column of multiples, on the real n axis or the multiples axis.
The arithmetic is tree_layout.py, the world-space draw data tree_draw.py, the HUD
tree_hud.py; this class holds the view state and the navigation.

The session's N picks the start: any N is rounded down to a prime on rebuild. The tree
computes everything itself, so it runs with --source none and has no prime ceiling.

Navigation: Space plays the start forward one prime per tick, Left/Right step one
prime (Ctrl: ten), Up/Down/PageUp/PageDown move N by --n-step (x100). Clicking a copy
makes its prime the start; Backspace returns to the previous start, Home to the launch N;
R resets N to 1 (start 2).
"""

import time

import numpy as np

from primeatlas.visualization.shared.mode import VizMode
from primeatlas.visualization.tree.highlight_layers import LAYERS, make_layers
from primeatlas.visualization.tree.tree_colors import parse_color_map
from primeatlas.visualization.tree.tree_draw import MAX_STRIPES, TreeStyle, build_tree_draw_data
from primeatlas.visualization.tree.tree_hud import tree_hud_lines
from primeatlas.visualization.tree.tree_layout import AXIS_KINDS, build_tree, next_prime, prev_prime

_DEFAULTS = {
    "tree_depth": 4,
    "tree_branches": 3,
    "tree_height": 1.5,
    "tree_max_nodes": 2000,
    "tree_max_points": 500_000,
    "tree_multiples": 4,
    "tree_axis": "auto",
    "tree_max_labels": 3000,
    "tree_max_stripes": 4,
    "tree_node_size": 11.0,
    "tree_point_size": 7.0,
    "tree_label_font_size": 16,
}

# A click within this many pixels of a node's center picks it.
_PICK_RADIUS_PX = 12.0
_CTRL_SCRUB_PRIMES = 10


class TreeMode(VizMode):
    name = "tree"
    window_title = "PrimeAtlas -- Prime tree"
    count_label = "copies"
    draws_center_marker = False
    uses_prime_ceiling = False

    def __init__(self, session, config):
        super().__init__(session, config)
        get = lambda key: config.get(key, _DEFAULTS.get(key))  # noqa: E731
        self.depth = int(get("tree_depth"))
        self.branches = int(get("tree_branches"))
        self.height = float(get("tree_height"))
        self.max_nodes = int(get("tree_max_nodes"))
        self.max_points = int(get("tree_max_points"))
        self.multiples = int(get("tree_multiples"))
        self.axis = get("tree_axis")
        self.max_stripes = int(get("tree_max_stripes"))
        self.label_font_size = int(get("tree_label_font_size"))
        self.style = TreeStyle(node_size=get("tree_node_size"), point_size=get("tree_point_size"),
                               max_stripes=self.max_stripes, colors=config.get("tree_colors") or {},
                               max_labels=get("tree_max_labels"))
        self.layers = make_layers(config.get("tree_highlight") or [])
        self.tree = None
        self.draw = None
        self._history = []
        self._launch_n = session.n

    # -- launch -----------------------------------------------------------------

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument("--tree-depth", type=int, default=_DEFAULTS["tree_depth"],
                            help="tree mode: how many consecutive primes (levels) the tree holds")
        parser.add_argument("--tree-branches", type=int, default=_DEFAULTS["tree_branches"],
                            help="tree mode: child copies drawn per copy of p; the rest of its p-1 "
                                 "branches are shown as '+N'")
        parser.add_argument("--tree-height", type=float, default=_DEFAULTS["tree_height"],
                            help="tree mode, real axis: window height as a multiple of the levels' "
                                 "span (start to the next prime after the last level, >= 1)")
        parser.add_argument("--tree-max-nodes", type=int, default=_DEFAULTS["tree_max_nodes"],
                            help="tree mode: drawn-copy cap; levels past it are left out")
        parser.add_argument("--tree-multiples", type=int, default=_DEFAULTS["tree_multiples"],
                            help="tree mode, multiples axis: multiples p..kp shown per level (>= 2)")
        parser.add_argument("--tree-axis", choices=AXIS_KINDS, default=_DEFAULTS["tree_axis"],
                            help="tree mode: vertical axis -- real n, the multiples of the level "
                                 "primes, or auto (real while the multiples fit one window)")
        parser.add_argument("--tree-max-points", type=int, default=_DEFAULTS["tree_max_points"],
                            help="tree mode: cap on column markers; the window shrinks to fit it")
        parser.add_argument("--tree-max-labels", type=int, default=_DEFAULTS["tree_max_labels"],
                            help="tree mode: cap on column-marker value labels")
        parser.add_argument("--tree-max-stripes", type=int, default=_DEFAULTS["tree_max_stripes"],
                            help=f"tree mode: color stripes per marker (1..{MAX_STRIPES}); past it "
                                 "the last stripe turns white")
        parser.add_argument("--tree-node-size", type=float, default=_DEFAULTS["tree_node_size"],
                            help="tree mode: node marker size in pixels (column markers use --point-size)")
        parser.add_argument("--tree-label-font-size", type=int, default=_DEFAULTS["tree_label_font_size"],
                            help="tree mode: pixel size of the labels next to nodes and columns")
        parser.add_argument("--tree-colors", type=str, default="",
                            help="tree mode: per-prime color overrides, e.g. '2=#ff0000,3=#00aaff'")
        parser.add_argument("--tree-highlight", type=str, default="",
                            help=f"tree mode: comma-separated highlight layers ({', '.join(sorted(LAYERS))})")

    @classmethod
    def validate_arguments(cls, parser, args):
        if args.tree_depth < 1:
            parser.error(f"--tree-depth must be >= 1, got {args.tree_depth}")
        if args.tree_branches < 1:
            parser.error(f"--tree-branches must be >= 1, got {args.tree_branches}")
        if args.tree_height < 1:
            parser.error(f"--tree-height must be >= 1, got {args.tree_height}")
        if args.tree_max_nodes < 1:
            parser.error(f"--tree-max-nodes must be >= 1, got {args.tree_max_nodes}")
        if args.tree_multiples < 2:
            parser.error(f"--tree-multiples must be >= 2, got {args.tree_multiples}")
        if args.tree_max_points < 1:
            parser.error(f"--tree-max-points must be >= 1, got {args.tree_max_points}")
        if args.tree_max_labels < 0:
            parser.error(f"--tree-max-labels must be >= 0, got {args.tree_max_labels}")
        if not 1 <= args.tree_max_stripes <= MAX_STRIPES:
            parser.error(f"--tree-max-stripes must be in 1..{MAX_STRIPES}, got {args.tree_max_stripes}")
        try:
            parse_color_map(args.tree_colors)
        except ValueError as e:
            parser.error(f"--tree-colors: {e}")
        try:
            make_layers(_split_names(args.tree_highlight))
        except ValueError as e:
            parser.error(f"--tree-highlight: {e}")

    @classmethod
    def prepare_launch(cls, args, launch):
        return {
            "tree_depth": args.tree_depth,
            "tree_branches": args.tree_branches,
            "tree_height": args.tree_height,
            "tree_max_nodes": args.tree_max_nodes,
            "tree_max_points": args.tree_max_points,
            "tree_multiples": args.tree_multiples,
            "tree_axis": args.tree_axis,
            "tree_max_labels": args.tree_max_labels,
            "tree_max_stripes": args.tree_max_stripes,
            "tree_node_size": args.tree_node_size,
            "tree_point_size": getattr(args, "point_size", _DEFAULTS["tree_point_size"]),
            "tree_label_font_size": args.tree_label_font_size,
            "tree_colors": parse_color_map(args.tree_colors),
            "tree_highlight": _split_names(args.tree_highlight),
        }

    # -- frame data -------------------------------------------------------------

    def rebuild(self, n_value, prev_ring_count=None, advancing=False, audio=None):
        """Builds the tree starting at the largest prime <= n_value and its draw data.
        The ring point buffers stay empty: the tree draws through marker_data/
        segment_data/world_labels."""
        s = self.session
        t0 = time.perf_counter()
        tree = build_tree(n_value, self.depth, branches=self.branches, max_nodes=self.max_nodes,
                          height=self.height, max_points=self.max_points, multiples=self.multiples,
                          axis=self.axis)
        self.tree = tree
        self.draw = build_tree_draw_data(tree, s.max_radius, self.style, layers=self.layers)
        t1 = time.perf_counter()

        layer_lines = [layer.hud_line(self.draw.layer_counts.get(layer.name, 0)) for layer in self.layers]
        s.hud_n = tree.start
        s.hud_count = len(tree.nodes)
        s.hud_rebuild_ms = round(1000 * (t1 - t0), 1)
        s.hud_lines = tree_hud_lines(tree, n_value, layer_lines)
        print(f"N={n_value:,}  start={tree.start:,}  copies={len(tree.nodes):,}  markers={len(self.draw.markers):,}  "
              f"rebuild={1000 * (t1 - t0):.1f}ms")
        empty = np.zeros((0, 5), dtype=np.float32)
        return empty, empty, 0, 0

    def marker_data(self):
        return None if self.draw is None else self.draw.markers

    def segment_data(self):
        return None if self.draw is None else self.draw.segments

    def world_labels(self):
        return [] if self.draw is None else self.draw.labels

    # -- navigation -------------------------------------------------------------

    def tick(self):
        s = self.session
        s.n = next_prime(prev_prime(s.n))
        s.n_advancing = True
        return False

    def scrub(self, is_right, ctrl_held):
        s = self.session
        p = prev_prime(s.n)
        for _ in range(_CTRL_SCRUB_PRIMES if ctrl_held else 1):
            p = next_prime(p) if is_right else prev_prime(p - 1)
        s.n = p
        return True

    def click(self, world_x, world_y, world_per_pixel):
        """Makes the prime of the nearest copy within the pick radius the start; copies of
        the current start are not candidates."""
        if self.draw is None:
            return False
        radius = _PICK_RADIUS_PX * world_per_pixel
        best = None
        for x, y, p in self.draw.pickables:
            if p == self.tree.start:
                continue
            d2 = (x - world_x) ** 2 + (y - world_y) ** 2
            if d2 <= radius * radius and (best is None or d2 < best[0]):
                best = (d2, p)
        if best is None:
            return False
        self._history.append(self.session.n)
        self.session.n = best[1]
        return True

    def key(self, name):
        s = self.session
        if name == "home":
            if s.n == self._launch_n:
                return False
            self._history.clear()
            s.n = self._launch_n
            return True
        if name == "backspace":
            if not self._history:
                return False
            s.n = self._history.pop()
            return True
        return False

    def reset_state(self):
        self._history.clear()
        self._launch_n = self.session.n


def _split_names(text):
    return [part.strip() for part in (text or "").split(",") if part.strip()]
