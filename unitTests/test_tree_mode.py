"""
test_tree_mode.py -- spec tests for primeatlas/visualization/tree/tree_mode.py (TreeMode, the
prime tree) running inside the shared RenderSession, plus the shared-session
behavior the tree needs. No GL.

Spec:
  A. Registration: "tree" is a registered viz-mode; RenderSession(viz_mode="tree")
     builds from the tree's own config keys without any loaded primes.
  B. Rebuild: the tree starts at the largest prime <= N (N=1 -> 2, N=10 -> 7); the ring
     point buffers are empty (count 0) -- the tree draws through marker_data/
     segment_data/world_labels; the HUD N is the start prime, the HUD count the drawn
     copies (1+1+2+6 for 2,3,5,7), one HUD line per level with its hidden branches, and
     from 2 on the density prod(1-1/p) (48/210 = 22.857% at 7).
  C. Navigation has no prime ceiling: Space starts playback with no primes loaded; a
     tick moves the start to the next prime; Right/Left step one prime (Ctrl: ten),
     never below 2; Up/Down bump N by the given delta (the rebuild rounds it down to a
     prime).
  D. Clicking a copy of a prime other than the start makes that prime the start and
     forces a rebuild; clicking the start or empty space does nothing; Backspace
     returns to the previous start, Home to the launch N; both do nothing when there
     is nowhere to go.
  E. Reset (R) stays in the tree window: N = 1 (start 2), mode still "tree", the
     history cleared. The rings/line windows still reset to "rings".
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
    config = dict(tree_depth=4, tree_branches=3, tree_height=1.5, tree_max_nodes=2000,
                  tree_max_points=500000, tree_multiples=4, tree_axis="auto", tree_colors={},
                  tree_highlight=[], tree_max_stripes=4, tree_node_size=11.0, tree_point_size=7.0)
    config.update(overrides)
    return config


def _make_session(n=1, viz_mode="tree", **tree_overrides):
    from primeatlas.visualization.shared.session import RenderSession
    return RenderSession(
        primes=np.empty(0, dtype=np.int64), n=n, ceiling=-1, range_mode=False, range_primes=None,
        range_step=1, max_radius=450.0, tempo_ms=120, buffer_margin=1000, can_extend_buffer=False,
        portal_folder=None, viz_mode=viz_mode, **_tree_config(**tree_overrides),
    )


def _world_to_screen(session, wx, wy, viewport):
    w, h = viewport
    return (wx * session.cam_zoom + session.cam_pan[0] + w / 2,
            wy * session.cam_zoom + session.cam_pan[1] + h / 2)


def _node_xy(mode, p):
    node = next(n for n in mode.tree.nodes if n.p == p)
    return mode.draw.node_xy(node)


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
    check(s.mode.tree.start == 2 and s.hud_n == 2, f"N=1 starts the chain at 2 (got {s.mode.tree.start})")
    markers = s.mode.marker_data()
    segments = s.mode.segment_data()
    check(markers is not None and markers.shape[1] == MARKER_FLOATS and len(markers) > 0, "marker data is produced")
    check(segments is not None and segments.shape[1] == 6 and len(segments) % 2 == 0, "segment data is produced")
    check(len(s.mode.world_labels()) > 0, "world labels are produced")
    check(s.hud_count == 10, f"HUD count = drawn copies 1+1+2+6 (got {s.hud_count})")
    lines = "\n".join(s.hud_lines)
    for p in (2, 3, 5, 7):
        check(f"p={p}" in lines, f"the HUD has a line for p={p}")
    check("+1 hidden" in lines and "+6 hidden" in lines, f"the HUD counts hidden branches (HUD:\n{lines})")
    check("22.857" in lines, "the p=7 line shows prod(1-1/p) = 48/210 = 22.857%")
    check(s.mode.draws_center_marker is False, "the tree draws no ring center marker")
    s.rebuild(10)
    check(s.mode.tree.start == 7 and s.hud_n == 7, f"N=10 starts the chain at 7 (got {s.mode.tree.start})")


def section_c_navigation():
    print("\n--- C: navigation without a prime ceiling ---")
    s = _make_session(n=10)
    s.rebuild(10)
    check(s.toggle_space() is None and s.playback_running, "Space starts playback with no primes loaded")
    check(s.tick() is False and s.n == 11 and s.n_advancing, f"a tick moves to the next prime (got {s.n})")
    s.playback_running = False
    s.scrub_advance(True, False, True)
    check(s.n == 13, f"Right steps one prime (got {s.n})")
    s.scrub_advance(True, True, False)
    check(s.n == 53, f"Ctrl+Right steps ten primes, 13 -> 53 (got {s.n})")
    msg, _ = s.scrub_release()
    check(msg is None, "releasing the scrub key prints no ceiling message")
    s.scrub_advance(False, False, True)
    check(s.n == 47, f"Left steps one prime back (got {s.n})")
    s.scrub_advance(False, True, False)
    s.scrub_advance(False, True, False)
    check(s.n == 2, f"Left never goes below 2 (got {s.n})")
    s.scrub_release()
    s.bump_n(1000)
    check(s.n == 1002, f"Up bumps N by the delta (got {s.n})")
    s.rebuild(s.n)
    check(s.mode.tree.start == 997, f"the rebuild rounds the bumped N down to 997 (got {s.mode.tree.start})")
    s.playback_running = True
    s.scrub_advance(True, False, True)
    msg, refresh = s.scrub_release()
    check(s.playback_running and msg is None and refresh, "a scrub during playback resumes it on release")


def section_d_click():
    print("\n--- D: click a node ---")
    s = _make_session(n=2)
    s.rebuild(2)
    mode = s.mode
    x, y = _node_xy(mode, 5)
    check(mode.click(x + 0.5, y, 1.0) is True and s.n == 5, f"clicking node 5 makes it the start (n {s.n})")
    s.rebuild(s.n)
    x, y = _node_xy(mode, 5)
    check(mode.click(x, y, 1.0) is False, "clicking the start itself does nothing")
    check(mode.click(10_000.0, 10_000.0, 1.0) is False, "clicking empty space does nothing")
    tx, ty = _node_xy(mode, 11)
    check(mode.click(tx, ty, 1.0) is True and s.n == 11, "a copy on a higher level is clickable too")
    check(mode.key("backspace") is True and s.n == 5, f"backspace returns to the previous start (got {s.n})")
    check(mode.key("home") is True and s.n == 2, f"home returns to the launch N (got {s.n})")
    check(mode.key("home") is False, "home at the launch N does nothing")
    check(mode.key("backspace") is False, "backspace with no history does nothing")
    check(mode.key("q") is False, "an unrelated key is not handled")

    s2 = _make_session(n=2)
    s2.rebuild(2)
    nx, ny = _node_xy(s2.mode, 3)
    s2.n_force_rebuild = False
    s2.click(*_world_to_screen(s2, nx, ny, (800, 600)), (800, 600))
    check(s2.n == 3 and s2.n_force_rebuild,
          "RenderSession.click converts screen to world and forces a rebuild when the mode moves")
    s2.n_force_rebuild = False
    check(s2.key("home") and s2.n_force_rebuild and s2.n == 2, "RenderSession.key forwards to the mode")


def section_e_reset():
    print("\n--- E: reset stays in the tree ---")
    s = _make_session(n=77)
    s.rebuild(77)
    x, y = _node_xy(s.mode, 79)
    s.mode.click(x, y, 1.0)
    s.reset()
    s.rebuild(s.n)
    check(s.viz_mode == "tree" and s.n == 1 and s.mode.tree.start == 2,
          f"R keeps the tree mode, N=1, start 2 (mode {s.viz_mode}, n {s.n})")
    check(s.mode.key("backspace") is False, "R clears the history")
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
    check(args.tree_depth >= 1 and args.tree_branches == 3 and args.tree_height >= 1
          and args.tree_axis == "auto" and args.tree_multiples == 4,
          "defaults: valid depth, 3 drawn branches, height >= 1, auto axis, 4 multiples")
    TreeMode.validate_arguments(parser, args)
    launch = SimpleNamespace(primes=None, n=1, range_mode=False, range_primes=None)
    config = TreeMode.prepare_launch(args, launch)
    for key in ("tree_depth", "tree_branches", "tree_height", "tree_max_nodes", "tree_max_points",
                "tree_multiples", "tree_axis", "tree_colors", "tree_highlight", "tree_max_stripes",
                "tree_node_size"):
        check(key in config, f"prepare_launch provides {key}")
    args = parser.parse_args(["--tree-colors", "2=#ff0000", "--tree-highlight", "primes"])
    config = TreeMode.prepare_launch(args, launch)
    check(config["tree_colors"] == {2: (1.0, 0.0, 0.0)} and config["tree_highlight"] == ["primes"],
          "colors and highlight layers are parsed")

    class _Exit(Exception):
        pass

    class _Parser(argparse.ArgumentParser):
        def error(self, message):
            raise _Exit(message)

    strict = _Parser()
    TreeMode.add_arguments(strict)
    for bad in (["--tree-depth", "0"], ["--tree-branches", "0"], ["--tree-height", "0.5"],
                ["--tree-max-points", "0"], ["--tree-max-stripes", "7"], ["--tree-max-nodes", "0"],
                ["--tree-multiples", "1"],
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
    for section in (section_a_registration, section_b_rebuild, section_c_navigation, section_d_click,
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
