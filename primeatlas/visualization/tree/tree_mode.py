"""
tree_mode.py -- TreeMode, the sieve-lane tree viz-mode (see shared/mode.py): the sieve's
free lanes as a tree on the real n axis, with one column per prime holding all of its
multiples. The arithmetic is tree_layout.py, the world-space draw data tree_draw.py,
the HUD tree_hud.py; this class holds the view state and the navigation.

The session's N is the window start a. Moving N only changes values: the drawn shape is
fixed by the primes and K. The tree computes everything itself, so it runs with
--source none and has no prime ceiling.

Navigation: Space plays N forward by 1 per tick, Left/Right step 1 (Ctrl: 10),
Up/Down/PageUp/PageDown step --n-step (x100). Clicking a free node opens its lane as
the view root (the next primes become the levels); Backspace goes to the parent lane,
Home to the top root; R resets N to 1 and the root to the top.
"""

import time

import numpy as np

from primeatlas.visualization.shared.mode import VizMode
from primeatlas.visualization.tree.highlight_layers import LAYERS, make_layers
from primeatlas.visualization.tree.tree_colors import parse_color_map
from primeatlas.visualization.tree.tree_draw import MAX_STRIPES, TreeStyle, build_tree_draw_data
from primeatlas.visualization.tree.tree_hud import tree_hud_lines
from primeatlas.visualization.tree.tree_layout import (
    build_view_tree, effective_window, first_primes, levels_within_cap, parent_lane,
)

TOP_ROOT = (0, 1, 0)

_DEFAULTS = {
    "tree_depth": 4,
    "tree_branches": 5,
    "tree_periods": 2.0,
    "tree_max_nodes": 20_000,
    "tree_max_points": 500_000,
    "tree_max_stripes": 4,
    "tree_node_size": 11.0,
    "tree_point_size": 7.0,
    "tree_label_font_size": 16,
}

# A click within this many pixels of a node's center picks it.
_PICK_RADIUS_PX = 12.0


class TreeMode(VizMode):
    name = "tree"
    window_title = "PrimeAtlas -- Sieve-lane tree"
    count_label = "nodes"
    draws_center_marker = False
    uses_prime_ceiling = False

    def __init__(self, session, config):
        super().__init__(session, config)
        get = lambda key: config.get(key, _DEFAULTS.get(key))  # noqa: E731
        self.depth = int(get("tree_depth"))
        self.branches = int(get("tree_branches"))
        self.periods = float(get("tree_periods"))
        self.max_nodes = int(get("tree_max_nodes"))
        self.max_points = int(get("tree_max_points"))
        self.max_stripes = int(get("tree_max_stripes"))
        self.label_font_size = int(get("tree_label_font_size"))
        self.style = TreeStyle(node_size=get("tree_node_size"), point_size=get("tree_point_size"),
                               max_stripes=self.max_stripes, colors=config.get("tree_colors") or {})
        self.layers = make_layers(config.get("tree_highlight") or [])
        self.root = TOP_ROOT
        self._all_primes = first_primes(self.depth + 1)
        self.view = None
        self.draw = None

    # -- launch -----------------------------------------------------------------

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument("--tree-depth", type=int, default=_DEFAULTS["tree_depth"],
                            help="tree mode: how many primes (levels) the view spans below its root")
        parser.add_argument("--tree-branches", type=int, default=_DEFAULTS["tree_branches"],
                            help="tree mode: free branches drawn per node (the lowest on the n axis); "
                                 "the rest are shown as '+N' with their exact leaf count")
        parser.add_argument("--tree-periods", type=float, default=_DEFAULTS["tree_periods"],
                            help="tree mode: window height in periods of the deepest lanes (>= 1)")
        parser.add_argument("--tree-max-nodes", type=int, default=_DEFAULTS["tree_max_nodes"],
                            help="tree mode: drawn-node cap; levels past it are not drawn")
        parser.add_argument("--tree-max-points", type=int, default=_DEFAULTS["tree_max_points"],
                            help="tree mode: cap on line markers; the window shrinks to fit it")
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
        if args.tree_periods < 1:
            parser.error(f"--tree-periods must be >= 1, got {args.tree_periods}")
        if args.tree_max_nodes < 1:
            parser.error(f"--tree-max-nodes must be >= 1, got {args.tree_max_nodes}")
        if args.tree_max_points < 1:
            parser.error(f"--tree-max-points must be >= 1, got {args.tree_max_points}")
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
            "tree_periods": args.tree_periods,
            "tree_max_nodes": args.tree_max_nodes,
            "tree_max_points": args.tree_max_points,
            "tree_max_stripes": args.tree_max_stripes,
            "tree_node_size": args.tree_node_size,
            "tree_point_size": getattr(args, "point_size", _DEFAULTS["tree_point_size"]),
            "tree_label_font_size": args.tree_label_font_size,
            "tree_colors": parse_color_map(args.tree_colors),
            "tree_highlight": _split_names(args.tree_highlight),
        }

    # -- frame data -------------------------------------------------------------

    def _primes_through(self, count):
        if len(self._all_primes) < count:
            self._all_primes = first_primes(count)
        return self._all_primes

    def rebuild(self, n_value, prev_ring_count=None, advancing=False, audio=None):
        """Builds the view for window start a = n_value and its draw data. The ring
        point buffers stay empty: the tree draws through marker_data/segment_data/
        world_labels."""
        s = self.session
        t0 = time.perf_counter()
        residue, modulus, depth = self.root
        all_primes = self._primes_through(depth + self.depth)
        wanted = all_primes[depth:depth + self.depth]
        levels = levels_within_cap(wanted, self.branches, self.max_nodes)
        level_primes = wanted[:levels]
        view = build_view_tree(n_value, residue, modulus, depth, level_primes, self.branches)
        leaf_count = len(view.nodes_at_level(levels))
        h_requested = max(1, int(self.periods * view.leaf_modulus))
        h = effective_window(h_requested, modulus, level_primes, leaf_count, self.max_points)
        self.view = view
        self.draw = build_tree_draw_data(view, h, s.max_radius, self.style, layers=self.layers)
        t1 = time.perf_counter()

        layer_lines = [layer.hud_line(self.draw.layer_counts.get(layer.name, 0)) for layer in self.layers]
        s.hud_n = n_value
        s.hud_count = len(view.nodes)
        s.hud_rebuild_ms = round(1000 * (t1 - t0), 1)
        s.hud_lines = tree_hud_lines(view, h, h_requested, all_primes, levels < len(wanted), self.branches,
                                     layer_lines)
        print(f"N={n_value:,}  tree nodes={len(view.nodes):,}  markers={len(self.draw.markers):,}  "
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
        s.n += 1
        s.n_advancing = True
        return False

    def scrub(self, is_right, ctrl_held):
        s = self.session
        step = 10 if ctrl_held else 1
        s.n = max(0, s.n + (step if is_right else -step))
        return True

    def click(self, world_x, world_y, world_per_pixel):
        """Opens the nearest free node within the pick radius as the view root. The
        current root is not a candidate, and on a tie the deeper node wins: a node's
        lowest child often has the node's own value, and with a single shown child it
        also has the same slot, so both sit on the same point."""
        if self.draw is None:
            return False
        radius = _PICK_RADIUS_PX * world_per_pixel
        best = None
        for x, y, node in self.draw.pickables:
            if node is self.view.root:
                continue
            d2 = (x - world_x) ** 2 + (y - world_y) ** 2
            if d2 <= radius * radius and (best is None or (d2, -node.level) < best[0]):
                best = ((d2, -node.level), node)
        if best is None:
            return False
        node = best[1]
        self.root = (node.residue, node.modulus, node.depth)
        return True

    def key(self, name):
        if name == "home":
            if self.root == TOP_ROOT:
                return False
            self.root = TOP_ROOT
            return True
        if name == "backspace":
            residue, modulus, depth = self.root
            parent = parent_lane(residue, modulus, depth, self._primes_through(depth))
            if parent is None:
                return False
            self.root = parent
            return True
        return False

    def reset_state(self):
        self.root = TOP_ROOT


def _split_names(text):
    return [part.strip() for part in (text or "").split(",") if part.strip()]
