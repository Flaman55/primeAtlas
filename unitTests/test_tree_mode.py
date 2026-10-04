"""
test_tree_mode.py -- spec tests for primeatlas/visualization/tree/tree_mode.py (TreeMode)
running inside the shared RenderSession, plus the shared-session behavior the tree needs.
No GL.

Spec:
  A. Registration: "tree" is a registered viz-mode; RenderSession(viz_mode="tree")
     builds from the tree's own config keys without any loaded primes.
  B. Rebuild: the ring point buffers are empty (count 0) -- the tree draws through
     marker_data/segment_data/world_labels; the HUD reports the drawn node count and a
     density line per level.
  C. Navigation has no prime ceiling: Space starts playback with no primes loaded, a
     tick advances N by 1, Left/Right scrub by 1 (Ctrl: 10) and never below 0, Up/Down
     bump by the given delta.
  D. Zoom: clicking a free node (world coordinates) makes its lane the view root and
     forces a rebuild; clicking empty space or the current root does nothing;
     "backspace" goes to the parent lane, "home" to the top root.
  E. Reset (R) stays in the tree window: N = 1, mode still "tree", root back at the
     top. The rings/line windows still reset to "rings".
  F. CLI: the tree's arguments exist with sane defaults, prepare_launch turns them
     into config keys, validate_arguments rejects out-of-range values.
  G. Session camera: screen_to_world inverts the shader transform.

Usage:
    python unitTests/test_tree_mode.py
"""
import argparse
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

import numpy as np

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _tree_config(**overrides):
    config = dict(tree_depth=4, tree_branches=3, tree_periods=2.0, tree_max_nodes=20000,
                  tree_max_points=500000, tree_colors={}, tree_highlight=[], tree_max_stripes=4,
                  tree_node_size=11.0, tree_point_size=7.0)
    config.update(overrides)
    return config


def _make_session(n=1, viz_mode="tree", **tree_overrides):
    from primeatlas.visualization.shared.session import RenderSession
    return RenderSession(
        primes=np.empty(0, dtype=np.int64), n=n, ceiling=-1, range_mode=False, range_primes=None,
        range_step=1, max_radius=450.0, tempo_ms=120, buffer_margin=1000, can_extend_buffer=False,
        portal_folder=None, viz_mode=viz_mode, **_tree_config(**tree_overrides),
    )


def section_a_registration():
    print("\n--- A: registration ---")
    from primeatlas.visualization.mode_registry import MODES
    check("tree" in MODES and MODES["tree"].name == "tree", f"'tree' is registered (got {sorted(MODES)})")
    s = _make_session()
    check(s.viz_mode == "tree", "RenderSession(viz_mode='tree') runs the tree mode")


def section_b_rebuild():
    print("\n--- B: rebuild ---")
    from primeatlas.visualization.tree.tree_draw import MARKER_FLOATS
    s = _make_session(n=1)
    data_normal, data_hit, count, count_hit = s.rebuild(1)
    check(count == 0 and count_hit == 0 and len(data_normal) == 0 and len(data_hit) == 0,
          "the ring point buffers are empty for the tree")
    markers = s.mode.marker_data()
    segments = s.mode.segment_data()
    check(markers is not None and markers.shape[1] == MARKER_FLOATS and len(markers) > 0, "marker data is produced")
    check(segments is not None and segments.shape[1] == 6 and len(segments) % 2 == 0, "segment data is produced")
    check(len(s.mode.world_labels()) > 0, "world labels are produced")
    check(s.hud_count == 1 + 1 + 2 + 6 + 18, f"HUD count = drawn free nodes (got {s.hud_count})")
    lines = "\n".join(s.hud_lines)
    for p in (2, 3, 5, 7):
        check(f"p={p}" in lines, f"the HUD has a density line for p={p}")
    check("22.857" in lines, f"the p=7 line shows prod(1-1/p) = 48/210 = 22.857% (HUD:\n{lines})")
    check(s.mode.draws_center_marker is False, "the tree draws no ring center marker")


def section_c_navigation():
    print("\n--- C: navigation without a prime ceiling ---")
    s = _make_session(n=5)
    check(s.toggle_space() is None and s.playback_running, "Space starts playback with no primes loaded")
    check(s.tick() is False and s.n == 6 and s.n_advancing, "a tick advances N by 1")
    s.playback_running = False
    s.scrub_advance(True, False, True)
    check(s.n == 7, f"Right scrubs +1 (got {s.n})")
    s.scrub_advance(True, True, False)
    check(s.n == 17, f"Ctrl+Right scrubs +10 (got {s.n})")
    msg, _ = s.scrub_release()
    check(msg is None, "releasing the scrub key prints no ceiling message")
    s.scrub_advance(False, True, True)
    s.scrub_advance(False, True, False)
    check(s.n == 0, f"Left never goes below 0 (got {s.n})")
    s.scrub_release()
    s.bump_n(1000)
    check(s.n == 1000, f"Up bumps by the delta (got {s.n})")
    s.bump_n(-5000)
    check(s.n == 0, f"Down floors at 0 (got {s.n})")
    s.playback_running = True
    s.scrub_advance(True, False, True)
    msg, refresh = s.scrub_release()
    check(s.playback_running and msg is None and refresh, "a scrub during playback resumes it on release")


def section_d_zoom():
    print("\n--- D: zoom into a subtree ---")
    s = _make_session(n=1)
    s.rebuild(1)
    mode = s.mode
    view = mode.view
    target = view.nodes_at_level(2)[0]
    x, y = mode.draw.node_xy(target)
    s.n_force_rebuild = False
    world_per_px = 1.0
    check(mode.click(x + 0.5, y, world_per_px) is True, "clicking next to a free node is handled")
    check(mode.root == (target.residue, target.modulus, target.depth),
          f"the clicked lane becomes the root (got {mode.root})")
    s.rebuild(1)
    check(all(n.value % target.modulus == target.residue for n in mode.view.nodes),
          "every node of the zoomed view is inside the clicked lane")
    check(mode.view.level_primes[0] == 5, f"the zoomed view starts at the next prime, 5 (got {mode.view.level_primes})")
    rx, ry = mode.draw.node_xy(mode.view.root)
    # On the real n axis a child can sit a fraction of a pixel from its parent (values
    # 1 and 7 in a 60,060-high window); a click there opens the deeper node, so the
    # root alone is hit only at a tolerance below that gap.
    check(mode.click(rx, ry, 0.001) is False, "clicking the current root alone does nothing")
    check(mode.click(10_000.0, 10_000.0, world_per_px) is False, "clicking empty space does nothing")
    check(mode.key("backspace") is True and mode.root == (1, 2, 1), f"backspace goes to the parent lane (got {mode.root})")
    check(mode.key("home") is True and mode.root == (0, 1, 0), "home returns to the top root")
    check(mode.key("backspace") is False, "backspace at the top root does nothing")
    check(mode.key("q") is False, "an unrelated key is not handled")

    s2 = _make_session(n=1)
    s2.rebuild(1)
    node = s2.mode.view.nodes_at_level(1)[0]
    nx, ny = s2.mode.draw.node_xy(node)
    wx, wy = s2.screen_to_world(*_world_to_screen(s2, nx, ny, (800, 600)), (800, 600))
    s2.n_force_rebuild = False
    s2.click(*_world_to_screen(s2, nx, ny, (800, 600)), (800, 600))
    check(s2.mode.root[1] == node.modulus and s2.n_force_rebuild,
          "RenderSession.click converts screen to world and forces a rebuild when the mode zooms")
    s2.n_force_rebuild = False
    check(s2.key("home") and s2.n_force_rebuild, "RenderSession.key forwards to the mode and forces a rebuild")


def _world_to_screen(session, wx, wy, viewport):
    w, h = viewport
    return (wx * session.cam_zoom + session.cam_pan[0] + w / 2,
            wy * session.cam_zoom + session.cam_pan[1] + h / 2)


def section_e_reset():
    print("\n--- E: reset stays in the tree ---")
    s = _make_session(n=77)
    s.rebuild(77)
    s.mode.root = (1, 6, 2)
    s.reset()
    check(s.viz_mode == "tree" and s.n == 1 and s.mode.root == (0, 1, 0),
          f"R keeps the tree mode, N=1, root at the top (mode {s.viz_mode}, n {s.n}, root {s.mode.root})")
    from primeatlas.visualization.mode_registry import MODES
    check(MODES["line"].reset_mode == "rings" and MODES["rings"].reset_mode == "rings",
          "the line and rings windows still reset to the rings mode")


def section_f_cli():
    print("\n--- F: CLI ---")
    from primeatlas.visualization.tree.tree_mode import TreeMode
    from types import SimpleNamespace
    parser = argparse.ArgumentParser()
    TreeMode.add_arguments(parser)
    args = parser.parse_args([])
    check(args.tree_depth >= 1 and args.tree_branches >= 1 and args.tree_periods >= 1,
          "default depth/branches/periods are valid")
    TreeMode.validate_arguments(parser, args)
    config = TreeMode.prepare_launch(args, SimpleNamespace(primes=None, n=1, range_mode=False, range_primes=None))
    for key in ("tree_depth", "tree_branches", "tree_periods", "tree_max_nodes", "tree_max_points",
                "tree_colors", "tree_highlight", "tree_max_stripes", "tree_node_size"):
        check(key in config, f"prepare_launch provides {key}")
    args = parser.parse_args(["--tree-colors", "2=#ff0000", "--tree-highlight", "primes"])
    config = TreeMode.prepare_launch(args, SimpleNamespace(primes=None, n=1, range_mode=False, range_primes=None))
    check(config["tree_colors"] == {2: (1.0, 0.0, 0.0)} and config["tree_highlight"] == ["primes"],
          "colors and highlight layers are parsed")

    class _Exit(Exception):
        pass

    class _Parser(argparse.ArgumentParser):
        def error(self, message):
            raise _Exit(message)

    strict = _Parser()
    TreeMode.add_arguments(strict)
    for bad in (["--tree-depth", "0"], ["--tree-branches", "0"], ["--tree-periods", "0.5"],
                ["--tree-max-nodes", "0"], ["--tree-max-points", "0"], ["--tree-max-stripes", "7"],
                ["--tree-colors", "4=#ff0000"], ["--tree-highlight", "nope"]):
        try:
            TreeMode.validate_arguments(strict, strict.parse_args(bad))
            check(False, f"{bad} is rejected")
        except _Exit:
            check(True, f"{bad} is rejected")


def section_g_camera():
    print("\n--- G: screen_to_world ---")
    s = _make_session()
    s.cam_zoom = 2.5
    s.cam_pan = [30.0, -12.0]
    sx, sy = _world_to_screen(s, 17.0, -40.0, (800, 600))
    wx, wy = s.screen_to_world(sx, sy, (800, 600))
    check(abs(wx - 17.0) < 1e-9 and abs(wy + 40.0) < 1e-9, f"screen_to_world inverts the transform (got {wx}, {wy})")


if __name__ == "__main__":
    for section in (section_a_registration, section_b_rebuild, section_c_navigation, section_d_zoom,
                    section_e_reset, section_f_cli, section_g_camera):
        try:
            section()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(False, f"{section.__name__} raised {type(e).__name__}: {e}")
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
