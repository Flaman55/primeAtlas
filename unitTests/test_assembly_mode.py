"""
test_assembly_mode.py -- spec tests for primeatlas/visualization/assembly/assembly_mode.py
(AssemblyMode, the assembly animation) inside the shared RenderSession. No GL.

Spec:
  A. Registration: "assembly" is a registered viz-mode; RenderSession(viz_mode="assembly")
     builds without loaded primes; the ring buffers stay empty (count 0); it draws through
     marker_data/segment_data/world_labels.
  B. Playback: Space starts with no primes loaded (no prime ceiling); each tick moves the
     animation one frame and forces a rebuild; at the end a tick stops playback.
  C. Stepping: Right jumps to the next phase boundary, Ctrl+Right to the next step, Left
     and Ctrl+Left back; never outside [0, total]. Up/Down only move N (the label base),
     not the animation.
  D. Click on an assembled floor shows its step's grid (detail_step) and forces a rebuild;
     clicking empty space does nothing; Backspace drops the detail (nothing when none);
     Home restarts the animation.
  E. Reset (R) stays in the assembly window: position 0, detail cleared, N = 1.
  F. HUD: lines name the step, q and phase, the period and lanes before -> after, the
     removed class, the next prime with its square; the HUD count is the lanes shown and
     the HUD N the period shown (it grows with the animation; the session's N, the label
     base, stays as it is).
  G. CLI: the assembly's arguments exist with defaults (depth 6, frames 12, lane dots 48,
     detail cells 2310, label font 35); prepare_launch maps them; validate_arguments
     rejects out-of-range values.
  H. Bare (--assembly-bare): no world labels, no on-canvas HUD; off by default.

Usage:
    python unitTests/test_assembly_mode.py
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


def _make_session(n=1, **overrides):
    from primeatlas.visualization.shared.session import RenderSession
    config = dict(assembly_depth=4, assembly_frames=2)
    config.update(overrides)
    return RenderSession(
        primes=np.empty(0, dtype=np.int64), n=n, ceiling=-1, range_mode=False, range_primes=None,
        range_step=1, max_radius=450.0, tempo_ms=60, buffer_margin=1000, can_extend_buffer=False,
        portal_folder=None, viz_mode="assembly", **config,
    )


def section_a_registration():
    print("\n--- A: registration ---")
    from primeatlas.visualization.mode_registry import MODES
    check("assembly" in MODES, "assembly is a registered viz-mode")
    s = _make_session()
    check(s.viz_mode == "assembly", "the session runs the assembly mode")
    data_normal, data_hit, count, count_hit = s.rebuild(s.n)
    check(count == 0 and count_hit == 0 and len(data_normal) == 0, "ring buffers stay empty")
    check(s.mode.marker_data() is not None and len(s.mode.marker_data()) > 0, "markers drawn")
    check(s.mode.segment_data() is not None, "segments drawn")
    check(len(s.mode.world_labels()) > 0, "labels drawn")
    check(s.mode.timeline.total == 4 * 4 * 2, f"timeline: 4 steps x 4 phases x 2 frames (got {s.mode.timeline.total})")


def section_b_playback():
    print("\n--- B: playback ---")
    s = _make_session()
    s.rebuild(s.n)
    check(s.toggle_space() is None and s.playback_running, "Space starts without primes")
    s.n_force_rebuild = False
    stopped = s.tick()
    check(stopped is False and s.mode.position == 1 and s.n_force_rebuild, "a tick advances one frame and rebuilds")
    s.mode.position = s.mode.timeline.total
    check(s.tick() is True and not s.playback_running, "a tick at the end stops playback")
    check(s.mode.position == s.mode.timeline.total, "the position stays at the end")


def section_c_stepping():
    print("\n--- C: stepping ---")
    s = _make_session()
    s.rebuild(s.n)
    s.n_force_rebuild = False
    s.scrub_advance(True, False, True)
    s.scrub_release()
    check(s.mode.position == 2 and s.n_force_rebuild, f"Right: next phase boundary (got {s.mode.position})")
    s.scrub_advance(True, True, True)
    s.scrub_release()
    check(s.mode.position == 8, f"Ctrl+Right: next step (got {s.mode.position})")
    s.scrub_advance(False, False, True)
    s.scrub_release()
    check(s.mode.position == 6, f"Left: previous phase boundary (got {s.mode.position})")
    s.scrub_advance(False, True, True)
    s.scrub_release()
    check(s.mode.position == 0, f"Ctrl+Left: previous step (got {s.mode.position})")
    s.scrub_advance(False, False, True)
    s.scrub_release()
    check(s.mode.position == 0, "never below 0")
    s.mode.position = s.mode.timeline.total
    s.scrub_advance(True, True, True)
    s.scrub_release()
    check(s.mode.position == s.mode.timeline.total, "never past the end")
    s.mode.position = 5
    s.bump_n(1000)
    check(s.mode.position == 5 and s.n == 1001, "Up/Down move N, not the animation")


def section_d_click_keys():
    print("\n--- D: click, Backspace, Home ---")
    s = _make_session()
    s.mode.position = s.mode.timeline.step_start(3)
    s.rebuild(s.n)
    x, y, floor = s.mode.draw.pickables[-1]
    s.n_force_rebuild = False
    check(s.mode.click(x, y, 1.0), "clicking floor 3 is handled")
    check(s.mode.detail_step == floor - 1 == 2, f"its step's grid is shown (got {s.mode.detail_step})")
    check(not s.mode.click(10_000.0, 10_000.0, 1.0), "clicking empty space does nothing")
    check(s.key("backspace") and s.mode.detail_step is None, "Backspace drops the detail")
    check(not s.key("backspace"), "Backspace without a detail does nothing")
    check(s.key("home") and s.mode.position == 0, "Home restarts the animation")


def section_e_reset():
    print("\n--- E: reset ---")
    s = _make_session(n=500)
    s.mode.position = 9
    s.mode.detail_step = 1
    s.reset()
    check(s.viz_mode == "assembly" and s.mode.position == 0 and s.mode.detail_step is None and s.n == 1,
          f"R: still assembly, position 0, no detail, N 1 (got {s.viz_mode}, {s.mode.position})")


def section_f_hud():
    print("\n--- F: HUD ---")
    s = _make_session()
    s.mode.position = s.mode.timeline.step_start(3) + 2  # step 3 strike (2 frames per phase)
    s.rebuild(s.n)
    text = "\n".join(s.hud_lines)
    for needle in ("q = 7", "strike", "30 -> 210", "8 -> 48", "multiples of 7", "11", "121"):
        check(needle in text, f"HUD mentions {needle!r}")
    check(s.hud_count == 8, f"strike: the HUD count is the old lanes (got {s.hud_count})")
    check(s.hud_n == 30 and s.n == 1, f"strike: the HUD N is the old period (got {s.hud_n}, N {s.n})")
    s.mode.position = s.mode.timeline.step_start(3) + 4  # prime phase
    s.rebuild(s.n)
    check(s.hud_count == 48, f"from the prime phase on: the new lanes (got {s.hud_count})")
    check(s.hud_n == 210, f"from the prime phase on: the new period (got {s.hud_n})")
    s.mode.position = 0
    s.rebuild(s.n)
    check(s.hud_n == 1, f"the first frame: period 1 (got {s.hud_n})")
    from primeatlas.visualization.shared.hud_text import compose_hud_canvas_lines
    header = compose_hud_canvas_lines(30, 8, [], False, 60, count_label="lanes", n_label=s.mode.n_label)[0]
    check(header.startswith("period = 30") and "lanes = 8" in header,
          f"the on-canvas header names the period (got {header!r})")
    check(compose_hud_canvas_lines(5, 2, [], False, 60)[0].startswith("N = 5"), "other modes keep N =")


def section_g_cli():
    print("\n--- G: CLI ---")
    from primeatlas.visualization.assembly.assembly_mode import AssemblyMode
    parser = argparse.ArgumentParser()
    AssemblyMode.add_arguments(parser)
    args = parser.parse_args([])
    defaults = {"assembly_depth": 6, "assembly_frames": 12, "assembly_lane_dots": 48,
                "assembly_detail_cells": 2310, "assembly_label_font_size": 35, "assembly_bare": False,
                "assembly_cell_spacing": "auto"}
    for key, value in defaults.items():
        check(getattr(args, key) == value, f"default {key} = {value} (got {getattr(args, key)})")
    config = AssemblyMode.prepare_launch(args, None)
    check(config["assembly_depth"] == 6 and config["assembly_frames"] == 12, "prepare_launch maps the arguments")
    check(config["assembly_cell_spacing"] is None, "auto spacing -> None")
    parser = argparse.ArgumentParser()
    AssemblyMode.add_arguments(parser)
    config = AssemblyMode.prepare_launch(parser.parse_args(["--assembly-cell-spacing", "40"]), None)
    check(config["assembly_cell_spacing"] == 40.0, f"--assembly-cell-spacing 40 -> 40.0 (got {config['assembly_cell_spacing']})")
    s = _make_session(assembly_cell_spacing=40.0)
    s.mode.position = s.mode.timeline.step_start(3)
    s.rebuild(s.n)
    check(s.mode.draw.grid.spacing == 40.0, "the session passes the spacing to the grid")

    class _Exit(Exception):
        pass

    def _error(message):
        raise _Exit(message)

    for bad in (["--assembly-depth", "0"], ["--assembly-frames", "0"], ["--assembly-lane-dots", "-1"],
                ["--assembly-detail-cells", "-1"], ["--assembly-max-labels", "-1"],
                ["--assembly-max-lanes", "0"], ["--assembly-colors", "4=#ff0000"],
                ["--assembly-cell-spacing", "0"], ["--assembly-cell-spacing", "wide"]):
        parser = argparse.ArgumentParser()
        AssemblyMode.add_arguments(parser)
        parser.error = _error
        try:
            AssemblyMode.validate_arguments(parser, parser.parse_args(bad))
            check(False, f"{bad} is rejected")
        except _Exit:
            check(True, f"{bad} is rejected")


def section_h_bare():
    print("\n--- H: bare ---")
    s = _make_session()
    s.rebuild(s.n)
    check(s.mode.draws_hud and s.mode.world_labels(), "labels and HUD by default")
    s = _make_session(assembly_bare=True)
    s.rebuild(s.n)
    check(not s.mode.world_labels() and not s.mode.draws_hud, "bare: no labels, no on-canvas HUD")
    check(len(s.mode.marker_data()) > 0, "bare: markers still drawn")


if __name__ == "__main__":
    for section in (section_a_registration, section_b_playback, section_c_stepping, section_d_click_keys,
                    section_e_reset, section_f_hud, section_g_cli, section_h_bare):
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
