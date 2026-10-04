"""
test_world_labels.py -- spec tests for primeatlas/visualization/shared/world_labels.py:
text labels anchored to world positions, drawn at a fixed pixel size.

Spec:
  A. Level of detail: a label with a `room` (world units of horizontal space) is shown
     only once room * zoom is at least its pixel width; room None always shows.
  B. Screen quads: each visible label becomes 6 vertices (x, y, u, v) in pixel space,
     placed by the camera transform screen = world * zoom + pan and the label's anchor;
     labels entirely outside the viewport are culled.
  C. Atlas: every label text is rasterized once into one RGBA atlas; each label's uv
     rectangle lies inside [0, 1] and matches its pixel size (needs Pillow; skipped
     without it).

Usage:
    python unitTests/test_world_labels.py
"""
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


def section_a_lod():
    print("\n--- A: level of detail ---")
    from primeatlas.visualization.shared.world_labels import label_visible
    check(label_visible(50, None, 0.1), "room None is always visible")
    check(not label_visible(50, 10.0, 4.0), "40px of room is too little for a 50px label")
    check(label_visible(50, 10.0, 6.0), "60px of room fits a 50px label")


def section_b_quads():
    print("\n--- B: screen quads ---")
    from primeatlas.visualization.shared.world_labels import WorldLabel, label_screen_quads
    labels = [
        WorldLabel(0.0, 0.0, "a", (1.0, 1.0, 1.0), anchor="right_of"),
        WorldLabel(10.0, 0.0, "b", (1.0, 1.0, 1.0), room=1.0),
        WorldLabel(100000.0, 0.0, "c", (1.0, 1.0, 1.0)),
    ]
    sizes = [(20, 10), (20, 10), (20, 10)]
    rects = [(0.0, 0.0, 0.5, 0.5), (0.5, 0.0, 1.0, 0.5), (0.0, 0.5, 0.5, 1.0)]
    quads = label_screen_quads(labels, sizes, rects, pan=(400.0, 300.0), zoom=2.0,
                               viewport=(800, 600), offset_px=6.0)
    check(quads.dtype == np.float32 and quads.shape == (6, 4),
          f"only label 'a' is visible: 'b' lacks room, 'c' is off-screen (got {quads.shape})")
    xs, ys = quads[:, 0], quads[:, 1]
    check(abs(xs.min() - 406.0) < 1e-4 and abs(xs.max() - 426.0) < 1e-4,
          f"a right_of label starts offset_px right of its anchor point (x {xs.min()}..{xs.max()})")
    check(abs(ys.min() - 295.0) < 1e-4 and abs(ys.max() - 305.0) < 1e-4,
          f"a right_of label is vertically centered on its anchor (y {ys.min()}..{ys.max()})")
    check(set(map(tuple, quads[:, 2:4].tolist())) == {(0.0, 0.0), (0.5, 0.0), (0.5, 0.5), (0.0, 0.5)},
          "the quad samples exactly the label's own atlas rectangle")
    above = label_screen_quads([WorldLabel(0.0, 0.0, "p", (1, 1, 1), anchor="above")], [(20, 10)],
                               [(0, 0, 1, 1)], pan=(400.0, 300.0), zoom=1.0, viewport=(800, 600), offset_px=6.0)
    check(abs(above[:, 0].min() - 390.0) < 1e-4 and abs(above[:, 1].max() - 294.0) < 1e-4,
          "an 'above' label is centered horizontally and sits offset_px above its point")
    left = label_screen_quads([WorldLabel(0.0, 0.0, "t", (1, 1, 1), anchor="left_of")], [(20, 10)],
                              [(0, 0, 1, 1)], pan=(400.0, 300.0), zoom=1.0, viewport=(800, 600), offset_px=6.0)
    check(abs(left[:, 0].max() - 394.0) < 1e-4, "a 'left_of' label ends offset_px left of its point")
    empty = label_screen_quads([], [], [], pan=(0, 0), zoom=1.0, viewport=(10, 10))
    check(empty.shape == (0, 4), "no labels give an empty (0, 4) array")


def section_c_atlas():
    print("\n--- C: atlas ---")
    from primeatlas.visualization.shared.hud_text import _PIL_AVAILABLE
    from primeatlas.visualization.shared.world_labels import WorldLabel, build_label_atlas
    if not _PIL_AVAILABLE:
        print("skip: Pillow not installed")
        return
    labels = [WorldLabel(0, 0, f"label {i}", (1.0, 0.5, 0.0)) for i in range(300)]
    rgba, sizes, rects = build_label_atlas(labels, font_size=16)
    check(rgba is not None and rgba.ndim == 3 and rgba.shape[2] == 4, "the atlas is an RGBA image")
    check(len(sizes) == len(rects) == 300, "one size and one uv rectangle per label")
    h, w = rgba.shape[0], rgba.shape[1]
    ok = all(0.0 <= u0 < u1 <= 1.0 and 0.0 <= v0 < v1 <= 1.0 and abs((u1 - u0) * w - sw) < 1.01
             and abs((v1 - v0) * h - sh) < 1.01
             for (u0, v0, u1, v1), (sw, sh) in zip(rects, sizes))
    check(ok, "every uv rectangle lies inside the atlas and matches the label's pixel size")
    none = build_label_atlas([], font_size=16)
    check(none[0] is None and none[1] == [] and none[2] == [], "no labels give no atlas")


if __name__ == "__main__":
    for section in (section_a_lod, section_b_quads, section_c_atlas):
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
