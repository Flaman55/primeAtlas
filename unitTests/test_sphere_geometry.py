"""
test_sphere_geometry.py -- spec tests for primeatlas/visualization/sphere/sphere_geometry.py,
the pure math of the sphere's rings mode. No GL.

Spec:
  A. Angles: ring p is turned by 2*pi*p/p_max (p_max = the largest ring), so the largest
     ring closes the full turn (its plane is the angle-0 plane) and 2 lies next to it.
  B. Frames: every ring is a circle on the unit sphere through the common node (0, 0, 1);
     its point at phase 0 (and every multiple of 2*pi) is the node; every point has norm 1;
     the radius never collapses (>= sqrt(3)/2).
  C. Phases: exact for any N -- the phase of ring p at N + frac is 2*pi*((N mod p) + frac)/p,
     N mod p computed exactly also past 2**63; the point is at the node exactly when p | N
     (frac 0).
  D. Easing: ease(0) = 0, it holds at 0 for the first 26% of the step, then rises
     monotonically (smoothstep) toward 1.
  E. View and projection: view_matrix is a rotation (orthonormal, det 1); with yaw = pitch
     = 0, x maps to screen right, the node to screen top (world y = -radius, screen y grows
     downward), (0, -1, 0) faces the viewer; a positive pitch turns the node toward the
     viewer; projected points stay within the radius.
  F. Curves: ring_curves samples every ring at `segments` equal phases; all samples lie on
     the ring (unit norm, the first one the node).

Usage:
    python unitTests/test_sphere_geometry.py
"""
import math
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


PRIMES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97]


def section_a_angles():
    print("\n--- A: angles ---")
    from primeatlas.visualization.sphere.sphere_geometry import ring_angles, ring_frames
    angles = ring_angles(PRIMES)
    check(np.allclose(angles, 2 * np.pi * np.array(PRIMES) / 97), "angle = 2*pi*p/p_max")
    frames = ring_frames(angles)
    zero = ring_frames(np.array([0.0]))
    check(np.allclose(frames.normal[-1], zero.normal[0], atol=1e-9), "the largest ring closes the turn (angle-0 plane)")
    dots = frames.normal @ frames.normal[-1]
    check(dots[0] > dots[1:-1].max(), "2 lies next to the largest ring (closest plane of all others)")


def section_b_frames():
    print("\n--- B: frames ---")
    from primeatlas.visualization.sphere.sphere_geometry import NODE, ring_angles, ring_frames, ring_points
    frames = ring_frames(ring_angles(PRIMES))
    for phase in (0.0, 2 * np.pi, 6 * np.pi):
        pts = ring_points(frames, np.full(len(PRIMES), phase))
        check(np.allclose(pts, NODE, atol=1e-9), f"phase {phase:.2f}: every ring at the node")
    rng = np.random.default_rng(1)
    phases = rng.uniform(0, 2 * np.pi, len(PRIMES))
    pts = ring_points(frames, phases)
    check(np.allclose(np.linalg.norm(pts, axis=1), 1.0), "every point on the unit sphere")
    planar = np.einsum("ij,ij->i", pts - frames.center, frames.normal)
    check(np.allclose(planar, 0.0, atol=1e-9), "every point in its ring's plane")
    many = ring_frames(np.linspace(0, 2 * np.pi, 2001))
    check(many.radius.min() >= math.sqrt(3) / 2 - 1e-12, f"radius >= sqrt(3)/2 (min {many.radius.min():.4f})")


def section_c_phases():
    print("\n--- C: phases ---")
    from primeatlas.visualization.sphere.sphere_geometry import (
        NODE, ring_angles, ring_frames, ring_points, ring_phases, residues)
    big = 10 ** 30 + 12345
    check(list(residues(big, PRIMES)) == [big % p for p in PRIMES], "N mod p exact past 2**63")
    check(list(residues(2 ** 64 + 1, [3, 5])) == [(2 ** 64 + 1) % 3, (2 ** 64 + 1) % 5], "2**64 + 1")
    ph = ring_phases(17, 0.5, [5, 7])
    check(np.allclose(ph, [2 * np.pi * 2.5 / 5, 2 * np.pi * 3.5 / 7]), f"phase = 2*pi*((N mod p)+frac)/p (got {ph})")
    frames = ring_frames(ring_angles(PRIMES))
    n = 2 * 3 * 7 * 97
    pts = ring_points(frames, ring_phases(n, 0.0, PRIMES))
    at_node = [p for p, pt in zip(PRIMES, pts) if np.allclose(pt, NODE, atol=1e-9)]
    check(at_node == [2, 3, 7, 97], f"at the node exactly the rings dividing N (got {at_node})")


def section_d_ease():
    print("\n--- D: easing ---")
    from primeatlas.visualization.sphere.sphere_geometry import ease
    check(ease(0.0) == 0.0 and ease(0.25) == 0.0, "holds at 0 for the first 26%")
    xs = np.linspace(0, 0.999, 400)
    ys = [ease(x) for x in xs]
    check(all(b >= a for a, b in zip(ys, ys[1:])), "monotonic")
    check(ease(0.999) > 0.99 and ease(0.999) <= 1.0, f"close to 1 at the end (got {ease(0.999)})")


def section_e_view():
    print("\n--- E: view and projection ---")
    from primeatlas.visualization.sphere.sphere_geometry import NODE, view_matrix, project
    m = view_matrix(37.0, -21.0)
    check(np.allclose(m @ m.T, np.eye(3)) and abs(np.linalg.det(m) - 1) < 1e-9, "a rotation")
    r = 400.0
    sx, sy, toward = project(np.array([[1.0, 0, 0], NODE, [0, -1.0, 0]]), view_matrix(0, 0), r)
    check(np.allclose([sx[0], sy[0]], [r, 0]), f"x -> screen right (got {sx[0]}, {sy[0]})")
    check(np.allclose([sx[1], sy[1]], [0, -r]), f"node -> screen top (got {sx[1]}, {sy[1]})")
    check(toward[2] > 0.99 and abs(toward[0]) < 1e-9, "(0,-1,0) faces the viewer")
    _, _, t_node = project(np.array([NODE]), view_matrix(0, 30), r)
    check(t_node[0] > 0.4, f"positive pitch turns the node toward the viewer (got {t_node[0]:.3f})")
    pts = np.random.default_rng(2).normal(size=(500, 3))
    pts /= np.linalg.norm(pts, axis=1, keepdims=True)
    sx, sy, _ = project(pts, view_matrix(123, 45), r)
    check(np.all(np.hypot(sx, sy) <= r + 1e-9), "projected points stay within the radius")


def section_f_curves():
    print("\n--- F: curves ---")
    from primeatlas.visualization.sphere.sphere_geometry import NODE, ring_angles, ring_frames, ring_curves
    frames = ring_frames(ring_angles(PRIMES))
    curves = ring_curves(frames, 48)
    check(curves.shape == (len(PRIMES), 48, 3), f"shape (rings, segments, 3) (got {curves.shape})")
    check(np.allclose(np.linalg.norm(curves, axis=2), 1.0), "samples on the unit sphere")
    check(np.allclose(curves[:, 0], NODE, atol=1e-9), "first sample is the node")


def main():
    for section in (section_a_angles, section_b_frames, section_c_phases, section_d_ease, section_e_view,
                    section_f_curves):
        try:
            section()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            check(False, f"{section.__name__} raised {e!r}")
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
