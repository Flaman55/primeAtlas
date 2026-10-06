"""
sphere_draw.py -- world-space draw data for one frame of the sphere's rings mode
(sphere_geometry.py): ring curves and a faint latitude/longitude grid as line segments,
one point marker per ring plus the node, and the node label. Pure numpy, no GL.

Depth: the sphere is drawn orthographically without a depth buffer, so the far half is
dimmed -- segment alpha and marker color fade toward the background behind the sphere's
silhouette -- and markers are sorted back to front.

Curves: at most `max_curves` ring curves, the smallest primes first; the highlighted rings
(factors of N, the birth ring) are always drawn, in their own colors.
"""

from dataclasses import dataclass, field

import numpy as np

from primeatlas.visualization.shared.world_labels import WorldLabel
from primeatlas.visualization.sphere.sphere_geometry import NODE, project, ring_curves, ring_points
from primeatlas.visualization.tree.tree_draw import MARKER_FLOATS, _solid_rows

ORBIT_RGB = (0.22, 0.74, 0.97)
FACTOR_RGB = (0.98, 0.80, 0.08)
BIRTH_RGB = (0.29, 0.87, 0.50)
GRID_RGB = (0.45, 0.52, 0.62)
LABEL_RGB = (0.99, 0.88, 0.28)
BACKGROUND_RGB = (0.05, 0.05, 0.07)

_GRID_ALPHA = 0.14
_HIGHLIGHT_ALPHA = 0.9
# Brightness kept by what lies behind the sphere, and the toward-viewer band over which
# it fades in.
_BACK_KEEP = 0.28
_DEPTH_BAND = 0.2
_GRID_MERIDIANS = 12
_GRID_PARALLELS = (-60, -30, 0, 30, 60)
_GRID_SAMPLES = 72
# Factors listed in the node label at most.
_LABEL_FACTORS = 12


@dataclass
class SphereStyle:
    point_size: float = 9.0
    node_size: float = 22.0
    segments: int = 96
    max_curves: int = 1000


@dataclass
class SphereDrawData:
    markers: np.ndarray = field(default_factory=lambda: np.zeros((0, MARKER_FLOATS), dtype=np.float32))
    segments: np.ndarray = field(default_factory=lambda: np.zeros((0, 6), dtype=np.float32))
    labels: list = field(default_factory=list)
    curve_primes: list = field(default_factory=list)


def ring_alpha(active):
    """Alpha of the plain ring curves: fainter as more rings overlap."""
    return float(max(0.035, min(0.36, 0.95 / np.sqrt(max(1, active)))))


def depth_keep(toward):
    """Brightness factor in [_BACK_KEEP, 1] from the toward-viewer coordinate."""
    t = np.clip((np.asarray(toward) + _DEPTH_BAND) / (2 * _DEPTH_BAND), 0.0, 1.0)
    return _BACK_KEEP + (1.0 - _BACK_KEEP) * t


def _polyline_rows(points, matrix, radius, rgb, alpha, closed=True):
    """GL_LINES rows for (c, m, 3) polylines, alpha scaled by depth per segment."""
    c, m, _ = points.shape
    sx, sy, toward = project(points.reshape(-1, 3), matrix, radius)
    sx, sy, toward = sx.reshape(c, m), sy.reshape(c, m), toward.reshape(c, m)
    if closed:
        nxt = np.roll(np.arange(m), -1)
        a_idx, b_idx = np.arange(m), nxt
    else:
        a_idx, b_idx = np.arange(m - 1), np.arange(1, m)
    k = len(a_idx)
    rows = np.zeros((c, k, 2, 6), dtype=np.float32)
    rows[:, :, 0, 0], rows[:, :, 0, 1] = sx[:, a_idx], sy[:, a_idx]
    rows[:, :, 1, 0], rows[:, :, 1, 1] = sx[:, b_idx], sy[:, b_idx]
    rows[:, :, :, 2:5] = rgb
    keep = depth_keep(0.5 * (toward[:, a_idx] + toward[:, b_idx]))
    rows[:, :, :, 5] = (alpha * keep)[:, :, None]
    return rows.reshape(-1, 6)


def _grid_polylines():
    lon = np.linspace(0.0, 2 * np.pi, _GRID_SAMPLES, endpoint=False)
    lines = []
    for k in range(_GRID_MERIDIANS):
        a = np.pi * k / _GRID_MERIDIANS
        lines.append(np.stack([np.cos(lon) * np.cos(a), np.cos(lon) * np.sin(a), np.sin(lon)], axis=1))
    for lat_deg in _GRID_PARALLELS:
        lat = np.radians(lat_deg)
        lines.append(np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon),
                               np.full_like(lon, np.sin(lat))], axis=1))
    return np.stack(lines)


_GRID = _grid_polylines()


class CurveCache:
    """The sampled curves of the first `max_curves` rings, computed once; other rings'
    curves are sampled on demand."""

    def __init__(self, frames, style):
        self.frames = frames
        self.segments = style.segments
        count = min(style.max_curves, len(frames.radius))
        self.prefix = ring_curves(_subset(frames, np.arange(count)), self.segments) if count else None

    def curves(self, indices):
        indices = np.asarray(indices, dtype=np.int64)
        if self.prefix is not None and len(indices) and indices.max() < len(self.prefix):
            return self.prefix[indices]
        return ring_curves(_subset(self.frames, indices), self.segments)


def _subset(frames, indices):
    from primeatlas.visualization.sphere.sphere_geometry import RingFrames
    return RingFrames(frames.normal[indices], frames.center[indices], frames.radius[indices],
                      frames.radial[indices], frames.tangent[indices])


def node_label_text(n, factors, birth):
    """The node label: the ring factors of N, or N itself when it is a new prime."""
    if birth:
        return f"{n:,} prime"
    if not factors:
        return ""
    shown = " · ".join(f"{p:,}" for p in factors[:_LABEL_FACTORS])
    extra = len(factors) - _LABEL_FACTORS
    return shown + (f" +{extra}" if extra > 0 else "")


def build_sphere_draw_data(rings, frames, curve_cache, active, phases, factors, birth, n, matrix, radius, style):
    """One frame: `rings` ascending, the first `active` of them taking part, `phases` their
    phases; `factors` (ring primes dividing N) and `birth` (N a new prime) are highlighted."""
    data = SphereDrawData()
    factor_set = set(factors)
    birth_ring = n if birth and active and n <= rings[active - 1] else None

    seg_blocks = [_polyline_rows(_GRID, matrix, radius, GRID_RGB, _GRID_ALPHA)]
    plain = list(range(min(active, style.max_curves)))
    index_of = {p: i for i, p in enumerate(rings[:active])} if (factor_set or birth_ring) else {}
    highlighted = sorted({index_of[p] for p in factor_set if p in index_of}
                         | ({index_of[birth_ring]} if birth_ring in index_of else set()))
    plain_only = [i for i in plain if i not in set(highlighted)]
    if plain_only:
        seg_blocks.append(_polyline_rows(curve_cache.curves(plain_only), matrix, radius, ORBIT_RGB,
                                         ring_alpha(active)))
    for i in highlighted:
        rgb = BIRTH_RGB if rings[i] == birth_ring else FACTOR_RGB
        seg_blocks.append(_polyline_rows(curve_cache.curves([i]), matrix, radius, rgb, _HIGHLIGHT_ALPHA))
    data.segments = np.concatenate(seg_blocks).astype(np.float32)
    data.curve_primes = sorted(rings[i] for i in set(plain_only) | set(highlighted))

    if active:
        pts = ring_points(_subset(frames, np.arange(active)), phases[:active])
        sx, sy, toward = project(pts, matrix, radius)
        base = np.tile(np.asarray(ORBIT_RGB), (active, 1))
        for i in highlighted:
            base[i] = BIRTH_RGB if rings[i] == birth_ring else FACTOR_RGB
        keep = depth_keep(toward)[:, None]
        rgbs = np.asarray(BACKGROUND_RGB) + (base - np.asarray(BACKGROUND_RGB)) * keep
        order = np.argsort(toward, kind="stable")
        ring_rows = _solid_rows(sx[order], sy[order], style.point_size, rgbs[order])
    else:
        ring_rows = np.zeros((0, MARKER_FLOATS), dtype=np.float32)
    nx, ny, nt = project(NODE[None, :], matrix, radius)
    node_rgb = BIRTH_RGB if birth and birth_ring is None else FACTOR_RGB
    node_rgb = np.asarray(BACKGROUND_RGB) + (np.asarray(node_rgb) - np.asarray(BACKGROUND_RGB)) * depth_keep(nt[0])
    node_rows = _solid_rows(nx, ny, style.node_size, node_rgb)
    data.markers = np.concatenate([ring_rows, node_rows]).astype(np.float32)

    text = node_label_text(n, factors, birth)
    if text:
        data.labels = [WorldLabel(float(nx[0]) + 0.5 * style.node_size, float(ny[0]), text,
                                  BIRTH_RGB if birth else LABEL_RGB)]
    return data
