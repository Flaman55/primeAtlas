"""
sphere_geometry.py -- the pure math of the sphere's rings mode: one circle on the unit
sphere per ring prime, all through the common node (0, 0, 1). Pure numpy, no GL.

Ring p lies in the plane with normal Ry(a) Rx(a) (0, 1, 0), a = 2*pi*p/p_max (the largest
ring closes the full turn), moved along its normal so that it passes through the node. The
point of ring p at N + frac has phase 2*pi*((N mod p) + frac)/p measured from the node, so
it is at the node exactly when p | N.

The view is a rotation (yaw about the vertical z axis, then pitch about the screen x
axis) followed by an orthographic projection: screen x = radius * x', world y =
-radius * z' (screen y grows downward), toward the viewer = -y'.
"""

from dataclasses import dataclass

import numpy as np

NODE = np.array([0.0, 0.0, 1.0])

# Share of every N step during which the points rest before moving on.
_EASE_HOLD = 0.26


@dataclass
class RingFrames:
    """Per ring (arrays of length K): the plane's unit normal, the circle's center and
    radius, and the in-plane unit vectors from the center to the node (radial) and
    perpendicular to it (tangent)."""
    normal: np.ndarray
    center: np.ndarray
    radius: np.ndarray
    radial: np.ndarray
    tangent: np.ndarray


def ring_angles(primes):
    """2*pi*p/p_max per ring prime."""
    values = np.array([float(p) for p in primes])
    return 2.0 * np.pi * values / values.max()


def ring_frames(angles):
    """The circle of every ring angle; see the module docstring."""
    a = np.asarray(angles, dtype=np.float64)
    s, c = np.sin(a), np.cos(a)
    normal = np.stack([s * s, c, s * c], axis=1)
    distance = normal @ NODE
    center = distance[:, None] * normal
    radius = np.sqrt(np.maximum(0.0, 1.0 - distance * distance))
    radial = NODE[None, :] - center
    radial /= np.linalg.norm(radial, axis=1, keepdims=True)
    tangent = np.cross(normal, radial)
    tangent /= np.linalg.norm(tangent, axis=1, keepdims=True)
    return RingFrames(normal, center, radius, radial, tangent)


def ring_points(frames, phases):
    """The point of every ring at its phase (radians from the node), (K, 3)."""
    ph = np.asarray(phases, dtype=np.float64)
    return (frames.center + frames.radius[:, None]
            * (frames.radial * np.cos(ph)[:, None] + frames.tangent * np.sin(ph)[:, None]))


def ring_curves(frames, segments):
    """Every ring sampled at `segments` equal phases starting at the node, (K, segments, 3)."""
    ph = 2.0 * np.pi * np.arange(segments) / segments
    cos, sin = np.cos(ph), np.sin(ph)
    return (frames.center[:, None, :] + frames.radius[:, None, None]
            * (frames.radial[:, None, :] * cos[None, :, None] + frames.tangent[:, None, :] * sin[None, :, None]))


def residues(n, primes):
    """N mod p per ring prime, exact for any integer N."""
    n = int(n)
    if 0 <= n < 2 ** 63:
        return np.int64(n) % np.asarray(primes, dtype=np.int64)
    return np.array([n % int(p) for p in primes], dtype=np.int64)


def ring_phases(n, frac, primes):
    """2*pi*((N mod p) + frac)/p per ring prime."""
    p = np.asarray(primes, dtype=np.float64)
    return 2.0 * np.pi * (residues(n, primes).astype(np.float64) + frac) / p


def ease(frac):
    """Position within one N step: at rest for the first _EASE_HOLD of it, then a
    smoothstep to 1."""
    if frac <= _EASE_HOLD:
        return 0.0
    t = min(1.0, (frac - _EASE_HOLD) / (1.0 - _EASE_HOLD))
    return t * t * (3.0 - 2.0 * t)


def view_matrix(yaw_deg, pitch_deg):
    """Rx(pitch) @ Rz(yaw)."""
    y, p = np.radians(yaw_deg), np.radians(pitch_deg)
    cy, sy, cp, sp = np.cos(y), np.sin(y), np.cos(p), np.sin(p)
    rz = np.array([[cy, -sy, 0.0], [sy, cy, 0.0], [0.0, 0.0, 1.0]])
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cp, -sp], [0.0, sp, cp]])
    return rx @ rz


def project(points, matrix, radius):
    """(screen-world x, world y, toward-viewer) of (k, 3) points; see the module docstring."""
    rotated = np.asarray(points, dtype=np.float64).reshape(-1, 3) @ matrix.T
    return radius * rotated[:, 0], -radius * rotated[:, 2], -rotated[:, 1]
