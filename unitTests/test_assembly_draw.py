"""
test_assembly_draw.py -- spec tests for primeatlas/visualization/assembly/assembly_draw.py,
the world-space draw data of one frame of the assembly animation.

Spec (R = max_radius; floors stack upward, smaller world y = higher on screen):
  A. Floors: floor 0 is the base (period 1, one lane); floor f >= 1 is the level built by
     step f-1. A frame of step s draws floors 0..s, each at floor_y(f), one trunk line
     between neighbors; floor f's label names its prime, period and lanes
     ("p=5  period 30  8 lanes"). Floors >= 1 are pickable.
  B. Copy phase: q copy tips grow from floor s toward floor s+1; at frac 0 they sit on
     floor s's node, at frac 1 on floor_y(s+1), spread around the floor's x.
  C. Strike phase: copy j is revealed once frac >= (j+1)/q; struck_per_copy counts the
     revealed removed lanes (removed_per_copy at frac 1). Lanes are drawn as dots on each
     tip while lanes <= lane_dots. Tip labels read "8 -> 7" (lanes before -> after) once
     revealed.
  D. Grid (detail): q rows x period cells while q * period <= detail_cells. Struck values
     at strike frac 1 are q times the old lanes (7 * {1, 7, ..., 29} for q=7). Prime phase
     (0 < frac < 1) highlights every survivor in (1, square) -- all prime. Values are
     labelled from base = the largest multiple of the new period <= base_n.
  E. Collapse phase: at frac 1 every tip sits on floor s+1's node.
  F. detail_step shows that step's grid in its final (struck) state instead of the
     current step's; above detail_cells there is no grid.
  G. Array shapes: markers (k, MARKER_FLOATS) float32, segments (2k, 6) float32.
  H. Grid spacing: auto (cell_spacing None) fits the grid into the right half and
     shrinks the cells to 0.85 of the spacing when cell_size does not fit; a given
     spacing (pixels at the launch view = world units) is used as is, the grid starting
     at the same left edge, and the cells keep exactly cell_size.

Usage:
    python unitTests/test_assembly_draw.py
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

import numpy as np

failures = []
R = 450.0


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _is_prime(n):
    if n < 2:
        return False
    d = 2
    while d * d <= n:
        if n % d == 0:
            return False
        d += 1
    return True


def _frame(step, phase, frac, depth=6, base_n=0, detail_step=None, **style_kw):
    from primeatlas.visualization.assembly.assembly_draw import AssemblyStyle, build_assembly_draw_data
    from primeatlas.visualization.assembly.assembly_layout import build_steps
    steps = build_steps(depth)
    return build_assembly_draw_data(steps, step, phase, frac, R, AssemblyStyle(**style_kw),
                                    base_n=base_n, detail_step=detail_step)


def _close(a, b, eps=1e-6):
    return abs(a[0] - b[0]) < eps and abs(a[1] - b[1]) < eps


def section_a_floors():
    print("\n--- A: floors ---")
    d = _frame(0, 0, 0.0)
    check(len(d.floor_xy) == 1, f"the first frame draws only the base floor (got {len(d.floor_xy)})")
    check(not d.pickables, "the base floor is not pickable")
    d = _frame(3, 1, 0.5)
    check(len(d.floor_xy) == 4, f"step 3 draws floors 0..3 (got {len(d.floor_xy)})")
    ys = [y for _x, y in d.floor_xy]
    check(all(abs(y - d.floor_y(f)) < 1e-6 for f, y in enumerate(ys)) and ys == sorted(ys, reverse=True),
          "floors sit at floor_y(f), each higher than the one below")
    check([f for _x, _y, f in d.pickables] == [1, 2, 3], f"floors 1..3 are pickable (got {d.pickables})")
    texts = [label.text for label in d.labels]
    check(any("p=5" in t and "period 30" in t and "8 lanes" in t for t in texts),
          f"floor 3 is labelled with its prime, period and lanes (got {texts[:8]})")


def section_b_copy():
    print("\n--- B: copy phase ---")
    d = _frame(0, 0, 0.0)
    check(len(d.tips) == 2 and all(_close(t, d.floor_xy[0]) for t in d.tips),
          "copy frac 0: q=2 tips on the floor node")
    d = _frame(3, 0, 1.0)
    check(len(d.tips) == 7, f"q=7 tips (got {len(d.tips)})")
    check(all(abs(y - d.floor_y(4)) < 1e-6 for _x, y in d.tips), "copy frac 1: tips at the next floor's height")
    xs = [x for x, _y in d.tips]
    check(len(set(round(x, 6) for x in xs)) == 7 and abs(sum(xs) / 7 - d.floor_xy[3][0]) < 1e-6,
          "tips spread around the floor's x")


def section_c_strike():
    print("\n--- C: strike phase ---")
    check(_frame(3, 1, 0.0).struck_per_copy == [0] * 7, "strike frac 0: nothing removed yet")
    check(_frame(3, 1, 0.5).struck_per_copy == [1, 1, 1, 0, 0, 0, 0], "strike frac 0.5: copies 0..2 revealed")
    d = _frame(3, 1, 1.0)
    check(d.struck_per_copy == [1, 1, 1, 2, 1, 1, 1], f"strike frac 1 (got {d.struck_per_copy})")
    check(d.lane_dots_drawn, "8 lanes are drawn as dots")
    texts = [label.text for label in d.labels]
    check("8 -> 7" in texts and "8 -> 6" in texts, f"tip labels 8 -> 7 / 8 -> 6 (got {texts})")
    check(not _frame(3, 1, 1.0, lane_dots=4).lane_dots_drawn, "past lane_dots no dots")
    check(not _frame(5, 1, 1.0).lane_dots_drawn, "480 lanes are not dots by default")


def section_d_grid():
    print("\n--- D: grid ---")
    d = _frame(3, 1, 1.0)
    g = d.grid
    check(g is not None and (g.rows, g.cols, g.cells) == (7, 30, 210), f"7 x 30 grid (got {g and (g.rows, g.cols)})")
    check(g is not None and g.struck_values == [7 * r for r in (1, 7, 11, 13, 17, 19, 23, 29)],
          f"struck = 7 * old lanes (got {g and g.struck_values})")
    g = _frame(3, 1, 0.5).grid
    check(g is not None and g.struck_values == [7, 49, 77], f"strike frac 0.5: rows 0..2 (got {g and g.struck_values})")
    g = _frame(3, 2, 0.5).grid
    expected = [v for v in range(2, 121) if _is_prime(v) and v > 7]
    check(g is not None and g.highlighted_values == expected,
          f"prime phase: the survivors in (1, 121) -- the 26 primes 11..113 (got {g and g.highlighted_values})")
    check(_frame(3, 2, 0.0).grid.highlighted_values == [], "prime frac 0: no highlight")
    d = _frame(3, 0, 1.0, base_n=1000)
    check(d.grid.base == 840 and "840" in [label.text for label in d.labels],
          f"values labelled from base 840 (got {d.grid.base})")
    check(_frame(5, 1, 1.0).grid is None, "13 x 2310 > 2310 cells: no grid by default")
    g = _frame(5, 1, 1.0, detail_cells=30030).grid
    check(g is not None and g.cells == 30030, "a larger detail_cells shows it")
    check(_frame(3, 1, 1.0, detail_cells=0).grid is None, "detail_cells 0: no grid")


def section_e_collapse():
    print("\n--- E: collapse ---")
    d = _frame(3, 3, 1.0)
    target = (d.floor_xy[3][0], d.floor_y(4))
    check(all(_close(t, target) for t in d.tips), "collapse frac 1: tips on floor 4's node")
    d = _frame(3, 3, 0.5)
    check(not all(_close(t, target) for t in d.tips), "collapse frac 0.5: still on the way")


def section_f_detail_step():
    print("\n--- F: detail step ---")
    d = _frame(5, 0, 0.5, detail_step=3)
    check(d.grid is not None and d.grid.step_index == 3, "detail_step=3 shows step 3's grid")
    check(d.grid is not None and len(d.grid.struck_values) == 8, "in its final, struck state")
    check(_frame(5, 0, 0.5, detail_step=5).grid is None, "a detail step above detail_cells shows none")


def section_g_shapes():
    print("\n--- G: shapes ---")
    from primeatlas.visualization.tree.tree_draw import MARKER_FLOATS
    for args in ((0, 0, 0.0), (3, 1, 0.5), (3, 2, 0.5), (5, 3, 1.0)):
        d = _frame(*args)
        check(d.markers.dtype == np.float32 and d.markers.ndim == 2 and d.markers.shape[1] == MARKER_FLOATS
              and len(d.markers) > 0, f"{args}: markers (k, {MARKER_FLOATS}) float32")
        check(d.segments.dtype == np.float32 and d.segments.shape[1] == 6 and len(d.segments) % 2 == 0,
              f"{args}: segments (2k, 6) float32")
        inside = np.all(np.abs(d.markers[:, :2]) <= R * 1.001)
        check(bool(inside), f"{args}: markers inside the fitted square")


def section_h_spacing():
    print("\n--- H: grid spacing ---")
    auto = _frame(3, 1, 1.0).grid
    check(auto.spacing == min(0.9 * R / 30, 1.6 * R / 7), f"auto: the grid fits the panel (got {auto.spacing})")
    check(auto.cell_px <= 0.85 * auto.spacing + 1e-9 or auto.cell_px == 12.0, f"auto cell px (got {auto.cell_px})")
    big = _frame(3, 1, 1.0, cell_size=40.0).grid
    check(abs(big.cell_px - 0.85 * big.spacing) < 1e-9, f"auto: a too large cell shrinks to its spacing (got {big.cell_px})")
    d = _frame(3, 1, 1.0, cell_spacing=40.0, cell_size=20.0)
    g = d.grid
    check(g.spacing == 40.0 and g.cell_px == 20.0, f"given spacing 40, cell 20 (got {g.spacing}, {g.cell_px})")
    check(abs(g.x0 - auto.x0) < 1e-9, "the grid starts at the same left edge")
    g = _frame(3, 1, 1.0, cell_spacing=5.0, cell_size=12.0).grid
    check(g.cell_px == 12.0, f"a given spacing never shrinks the cells (got {g.cell_px})")


if __name__ == "__main__":
    for section in (section_a_floors, section_b_copy, section_c_strike, section_d_grid, section_e_collapse,
                    section_f_detail_step, section_g_shapes, section_h_spacing):
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
