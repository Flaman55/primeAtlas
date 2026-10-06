"""
fiber_draw.py -- world-space draw data added by the sphere's fibers mode on top of the
orbits (sphere_draw.py): the fiber strands as line segments and the focused orbit's phase
overlay (the orbit, the arc from the node to its point, a tick per residue, the point).
Pure numpy, no GL. Depth is dimmed as in sphere_draw.py.
"""

import math

import numpy as np

from primeatlas.visualization.sphere.sphere_draw import (
    BACKGROUND_RGB, FACTOR_RGB, _polyline_rows, _subset, depth_keep,
)
from primeatlas.visualization.sphere.sphere_geometry import project, ring_points
from primeatlas.visualization.tree.tree_draw import MARKER_FLOATS, _solid_rows

LINK_RGB = (0.65, 0.55, 0.98)
HOT_RGB = FACTOR_RGB
FOCUS_RGB = (0.96, 0.38, 0.86)
TICK_RGB = (0.99, 0.66, 0.94)
ANCESTOR_RGB = (0.48, 0.55, 0.68)
TAKEN_RGB = (0.98, 0.45, 0.30)
FREE_RGB = (0.62, 0.92, 0.35)

# Strength above which a resonance fiber is drawn in the hot color.
_HOT_STRENGTH = 0.995
_RESONANCE_ALPHA = (0.06, 0.72)
_LINEAGE_ALPHA = (0.22, 0.70)
_FOCUSED_LINEAGE_BOOST = 0.3
_FOCUS_ORBIT_ALPHA = 0.9
_ARC_ALPHA = 0.95
_TICK_KEEP = 0.48
_TICK_SIZE_SHARE = 0.45
_PHASE_POINT_SHARE = 1.7
# Residue ticks on the focused orbit at most (every ceil(p/60)-th residue).
_MAX_TICKS = 60
_ARC_SAMPLES = 100


def resonance_style(strengths, focused):
    """(rgb (k, 3), alpha (k,)) of the resonance fibers."""
    strengths = np.asarray(strengths, dtype=np.float64)
    rgb = np.where((strengths > _HOT_STRENGTH)[:, None], np.asarray(HOT_RGB), np.asarray(LINK_RGB))
    rgb = np.where(np.asarray(focused, dtype=bool)[:, None], np.asarray(FOCUS_RGB), rgb)
    return rgb, _RESONANCE_ALPHA[0] + _RESONANCE_ALPHA[1] * strengths


def lineage_style(kinds, strengths, focused):
    """(rgb (k, pieces, 3), alpha (k,)) of the lineage fibers from their piece kinds."""
    palette = np.asarray([ANCESTOR_RGB, TAKEN_RGB, FREE_RGB])
    alpha = _LINEAGE_ALPHA[0] + _LINEAGE_ALPHA[1] * np.asarray(strengths, dtype=np.float64)
    alpha = np.minimum(1.0, alpha + _FOCUSED_LINEAGE_BOOST * np.asarray(focused, dtype=np.float64))
    return palette[kinds], alpha


def strand_rows(points, valid, rgb, alpha, matrix, radius):
    """GL_LINES rows of the valid strands: points (k, S, 3), rgb (k, 3) or (k, S-1, 3) per
    piece, alpha (k,), scaled by depth per piece."""
    keep_rows = np.flatnonzero(valid)
    if not len(keep_rows):
        return np.zeros((0, 6), dtype=np.float32)
    points = points[keep_rows]
    rgb = np.asarray(rgb)[keep_rows]
    alpha = np.asarray(alpha)[keep_rows]
    k, m, _ = points.shape
    sx, sy, toward = project(points.reshape(-1, 3), matrix, radius)
    sx, sy, toward = sx.reshape(k, m), sy.reshape(k, m), toward.reshape(k, m)
    rows = np.zeros((k, m - 1, 2, 6), dtype=np.float32)
    rows[:, :, 0, 0], rows[:, :, 0, 1] = sx[:, :-1], sy[:, :-1]
    rows[:, :, 1, 0], rows[:, :, 1, 1] = sx[:, 1:], sy[:, 1:]
    rows[:, :, :, 2:5] = (rgb[:, None, :] if rgb.ndim == 2 else rgb)[:, :, None, :]
    keep = depth_keep(0.5 * (toward[:, :-1] + toward[:, 1:]))
    rows[:, :, :, 5] = (alpha[:, None] * keep)[:, :, None]
    return rows.reshape(-1, 6)


def _dimmed(rgb, toward, keep=1.0):
    bg = np.asarray(BACKGROUND_RGB)
    return bg + (np.asarray(rgb) - bg) * keep * depth_keep(toward)[:, None]


def tick_step(p):
    return max(1, math.ceil(p / _MAX_TICKS))


def phase_overlay(frames, curve_cache, index, p, phase, matrix, radius, point_size):
    """(segments, markers) of the focused orbit `index` (prime p) at `phase` radians."""
    one = _subset(frames, np.array([index]))
    seg = [_polyline_rows(curve_cache.curves([index]), matrix, radius, FOCUS_RGB, _FOCUS_ORBIT_ALPHA)]
    fraction = (phase / (2.0 * math.pi)) % 1.0
    if fraction > 1e-9:
        arc = np.linspace(0.0, 2.0 * math.pi * fraction, max(3, int(fraction * _ARC_SAMPLES)))
        pts = ring_points(_subset(frames, np.zeros(len(arc), dtype=np.int64) + index), arc)
        seg.append(_polyline_rows(pts[None, :, :], matrix, radius, FOCUS_RGB, _ARC_ALPHA, closed=False))
    residues = np.arange(0, p, tick_step(p))
    ticks = ring_points(_subset(frames, np.zeros(len(residues), dtype=np.int64) + index),
                        2.0 * math.pi * residues / p)
    tx, ty, tt = project(ticks, matrix, radius)
    tick_rows = _solid_rows(tx, ty, point_size * _TICK_SIZE_SHARE, _dimmed(TICK_RGB, tt, _TICK_KEEP))
    point = ring_points(one, np.array([phase]))
    px, py, pt = project(point, matrix, radius)
    point_rows = _solid_rows(px, py, point_size * _PHASE_POINT_SHARE, _dimmed(FOCUS_RGB, pt))
    markers = np.concatenate([tick_rows, point_rows]).astype(np.float32).reshape(-1, MARKER_FLOATS)
    return np.concatenate(seg).astype(np.float32), markers
