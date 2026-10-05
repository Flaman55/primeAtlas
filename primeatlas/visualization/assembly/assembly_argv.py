"""
assembly_argv.py -- build_assembly_argv, the argv launching the shared GPU renderer
(primeatlas/visualization/shared/renderer.py) in assembly mode with --source none. The
Visualization > Tree sub-tab (tree/tree_tab.py) launches it in its assembly mode.
"""
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
RENDERER_SCRIPT = os.path.join(os.path.dirname(_THIS_DIR), "shared", "renderer.py")


def build_assembly_argv(n, python_executable=None, depth=None, frames=None, tempo_ms=None, lane_dots=None,
                        detail_cells=None, max_labels=None, max_lanes=None, node_size=None, cell_size=None,
                        hud_font_size=None, label_font_size=None, colors="", cell_spacing="", bare=False,
                        pipe_stdin_commands=False):
    """Argv launching renderer.py (as a plain script path) in assembly mode with the grid
    values labelled from `n`. Every None/empty optional value is omitted, so renderer.py's
    own defaults apply; values are forwarded as given (renderer.py validates them)."""
    exe = python_executable or sys.executable
    argv = [exe, RENDERER_SCRIPT, "--source", "none", "--upto", str(n), "--viz-mode", "assembly"]
    for flag, value in (("--assembly-depth", depth), ("--assembly-frames", frames), ("--tempo-ms", tempo_ms),
                        ("--assembly-lane-dots", lane_dots), ("--assembly-detail-cells", detail_cells),
                        ("--assembly-max-labels", max_labels), ("--assembly-max-lanes", max_lanes),
                        ("--assembly-node-size", node_size), ("--assembly-cell-size", cell_size),
                        ("--hud-font-size", hud_font_size), ("--assembly-label-font-size", label_font_size)):
        if value is not None:
            argv += [flag, str(value)]
    if colors:
        argv += ["--assembly-colors", colors]
    if cell_spacing:
        argv += ["--assembly-cell-spacing", cell_spacing]
    if bare:
        argv += ["--assembly-bare"]
    if pipe_stdin_commands:
        argv += ["--pipe-stdin-commands"]
    return argv
