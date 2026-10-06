"""
test_fiber_geometry.py -- spec tests for primeatlas/visualization/sphere/fiber_geometry.py,
the pure math of the sphere's fibers mode. No GL.

Spec:
  A. Pencil orbits: orbit i is tilted by 38 + 104 * frac(i * 0.618033988749895) degrees;
     every orbit is a circle on the unit sphere through the node (0, 0, 1) at phase 0, all
     with the same tangent (1, 0, 0) there (a pencil of circles touching at the node).
  B. Pair table: the pairs i < j of the first M orbits, M the largest m with
     m(m-1)/2 <= the pair cap; ordered j-major, so the pairs of the first a orbits are the
     first a(a-1)/2 rows; period = p_i * p_j.
  C. Pair residues: N mod p*q from the ring residues (CRT), exact for any N (also past
     2**63).
  D. Strength and score: strength = exp(-(d/0.115)^2 / 2), d = the distance of
     (N mod pq + frac)/pq to the nearest integer (1 at a multiple of pq, symmetric, frac may
     exceed 1); score = 0.72 * strength + 0.28/(1 + ln pq) + 1 for a focused pair; the top
     selection equals a full sort by score (descending). resonance_top (the pruned
     selection used per frame) returns exactly the full evaluation's top pairs and
     strengths, also when its pruning has to fall back, with or without a focus bonus.
  E. Strands: a strand runs from a to b (exact ends) on the unit sphere, a slerp with a
     sine wobble (amplitude 0.045, zero at both ends); coinciding ends give an invalid
     strand; nearly antipodal ends give finite points; a per-fiber t grid is accepted.
  F. Lineage shares: for p with the ring primes q < p before it, ancestors = 1 - prod(1 -
     1/q), taken by p = prod(1 - 1/q)/p, free = prod_{q <= p}(1 - 1/q); 3 -> 1/2|1/6|1/3,
     5 -> 2/3|1/15|4/15, the three sum to 1. The t grid of a lineage fiber contains both
     breakpoints, so every share gets its own pieces, whose t-lengths equal the shares.

Usage:
    python unitTests/test_fiber_geometry.py
"""
import math
import os
import sys
from fractions import Fraction
from itertools import combinations

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


def section_a_pencil():
    print("\n--- A: pencil orbits ---")
    from primeatlas.visualization.sphere.fiber_geometry import pencil_angles, pencil_frames
    from primeatlas.visualization.sphere.sphere_geometry import NODE, ring_points
    angles = pencil_angles(len(PRIMES))
    expected = [math.radians(38.0 + 104.0 * ((i * 0.618033988749895) % 1.0)) for i in range(len(PRIMES))]
    check(np.allclose(angles, expected), "tilt = 38 + 104 * frac(i * golden) degrees")
    frames = pencil_frames(angles)
    check(np.allclose(ring_points(frames, np.zeros(len(PRIMES))), NODE, atol=1e-9), "phase 0 is the node")
    eps = 1e-6
    tangent = (ring_points(frames, np.full(len(PRIMES), eps)) - NODE) / eps
    tangent /= np.linalg.norm(tangent, axis=1, keepdims=True)
    check(np.allclose(np.abs(tangent @ np.array([1.0, 0, 0])), 1.0, atol=1e-5), "common tangent (1,0,0) at the node")
    pts = ring_points(frames, np.random.default_rng(3).uniform(0, 2 * np.pi, len(PRIMES)))
    check(np.allclose(np.linalg.norm(pts, axis=1), 1.0), "points on the unit sphere")


def section_b_pairs():
    print("\n--- B: pair table ---")
    from primeatlas.visualization.sphere.fiber_geometry import PairTable, pair_cap_orbits
    check(pair_cap_orbits(0) == 1 and pair_cap_orbits(1) == 2 and pair_cap_orbits(2) == 2
          and pair_cap_orbits(3) == 3 and pair_cap_orbits(2_000_000) == 2000, "M from the pair cap")
    table = PairTable(PRIMES, cap=45)
    check(table.orbits == 10 and len(table.i) == 45, f"cap 45 -> 10 orbits, 45 pairs (got {table.orbits})")
    rows = list(zip(table.i.tolist(), table.j.tolist()))
    check(rows == [(i, j) for j in range(10) for i in range(j)], "j-major order")
    check(all(table.count(a) == min(a, 10) * (min(a, 10) - 1) // 2 for a in range(0, 25)),
          "count(a) = pairs among the first a orbits (capped)")
    check(table.period.tolist() == [PRIMES[i] * PRIMES[j] for i, j in rows], "period = p*q")
    big = PairTable(PRIMES, cap=10 ** 9)
    check(big.orbits == len(PRIMES), "a large cap takes every orbit")


def section_c_residues():
    print("\n--- C: pair residues ---")
    from primeatlas.visualization.sphere.fiber_geometry import PairTable, pair_residues
    from primeatlas.visualization.sphere.sphere_geometry import residues
    table = PairTable(PRIMES, cap=10 ** 6)
    for n in (0, 1, 210, 999_983, 2 ** 63 + 5, 10 ** 30 + 12345):
        got = pair_residues(table, residues(n, PRIMES), table.count(len(PRIMES)))
        want = [n % (PRIMES[i] * PRIMES[j]) for i, j in zip(table.i.tolist(), table.j.tolist())]
        check(got.tolist() == want, f"N mod pq exact at N = {n}")


def section_d_strength():
    print("\n--- D: strength and score ---")
    from primeatlas.visualization.sphere.fiber_geometry import pair_scores, pair_strength, top_pairs
    period = np.array([15, 15, 15, 15, 15], dtype=np.int64)
    res = np.array([0, 0, 3, 12, 7], dtype=np.int64)
    s = pair_strength(res, 0.0, period)
    check(abs(s[0] - 1.0) < 1e-12, "1 at a multiple of pq")
    check(abs(s[2] - s[3]) < 1e-12, "symmetric around a multiple")
    check(abs(s[2] - math.exp(-0.5 * (0.2 / 0.115) ** 2)) < 1e-12, "Gauss of width 0.115")
    check(abs(pair_strength(np.array([14]), 16.0, np.array([15]))[0] - 1.0) < 1e-12,
          "frac past 1 wraps (14 + 16 = 30 = 2 * 15)")
    focused = np.array([False, False, True, False, False])
    sc = pair_scores(s, period, focused)
    check(np.allclose(sc, 0.72 * s + 0.28 / (1 + np.log(15.0)) + focused), "score formula")
    rng = np.random.default_rng(5)
    scores = rng.uniform(0, 2, 400)
    for count in (0, 1, 7, 400, 900):
        got = top_pairs(scores, count).tolist()
        check(got == np.argsort(-scores, kind="stable")[:count].tolist(), f"top {count} = full sort")
    # The script's selection on its own pairs, for one N.
    primes = PRIMES[:15]
    pairs = list(combinations(range(15), 2))
    n = 187.4
    per = np.array([primes[i] * primes[j] for i, j in pairs], dtype=np.float64)
    ph = np.remainder(n, per) / per
    ref = 0.72 * np.exp(-0.5 * (np.minimum(ph, 1 - ph) / 0.115) ** 2) + 0.28 / (1 + np.log(per))
    res = np.array([187 % int(p) for p in per], dtype=np.int64)
    mine = pair_scores(pair_strength(res, 0.4, per.astype(np.int64)), per.astype(np.int64), np.zeros(len(per), bool))
    check(np.allclose(mine, ref), "scores match the prototype's formula")
    from primeatlas.visualization.sphere.fiber_geometry import bonus_cut, pair_base, resonance_top
    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89,
                       97, 101, 103, 107, 109, 113, 127, 131, 137, 139, 149, 151, 157, 163, 167, 173], dtype=np.int64)
    rng = np.random.default_rng(11)
    pi = rng.choice(primes, 60000)
    pj = rng.choice(primes, 60000) + 1000
    period = pi * pj
    res = rng.integers(0, period)
    for focus_share, count, frac in ((0.0, 32, 0.3), (0.001, 32, 1.7), (0.0, 900, 0.0), (0.0, 5, 0.99)):
        bonus = pair_base(period) + (rng.random(len(period)) < focus_share)
        full_s = pair_strength(res, frac, period)
        want = top_pairs(0.72 * full_s + bonus, count)
        got, strength = resonance_top(res / period, 1.0 / period, bonus, bonus_cut(bonus, count), frac, count)
        check(got.tolist() == want.tolist() and np.allclose(strength, full_s[want]),
              f"resonance_top = full evaluation (focus share {focus_share}, top {count})")
    near = np.zeros(60000)
    got, _ = resonance_top(near, 1.0 / period, pair_base(period), bonus_cut(pair_base(period), 32), 0.0, 32)
    check(got.tolist() == top_pairs(0.72 + pair_base(period), 32).tolist(), "every pair at a multiple (fallback)")


def section_e_strands():
    print("\n--- E: strands ---")
    from primeatlas.visualization.sphere.fiber_geometry import strand_points
    rng = np.random.default_rng(7)
    a = rng.normal(size=(6, 3))
    b = rng.normal(size=(6, 3))
    a /= np.linalg.norm(a, axis=1, keepdims=True)
    b /= np.linalg.norm(b, axis=1, keepdims=True)
    b[4] = a[4]
    b[5] = -a[5] + 1e-9
    turns = np.array([1, 2, 3, 1, 2, 3])
    pts, valid = strand_points(a, b, turns, rng.uniform(0, 6, 6), np.linspace(0, 1, 30))
    check(pts.shape == (6, 30, 3), f"shape (k, samples, 3) (got {pts.shape})")
    check(valid.tolist() == [True, True, True, True, False, True], f"coinciding ends invalid (got {valid})")
    check(np.all(np.isfinite(pts)), "finite points (antipodal ends included)")
    check(np.allclose(pts[valid, 0], a[valid]) and np.allclose(pts[valid, -1], b[valid]), "exact ends")
    check(np.allclose(np.linalg.norm(pts[valid], axis=2), 1.0), "on the unit sphere")
    plain, _ = strand_points(a[:1], b[:1], np.array([1]), np.array([0.0]), np.linspace(0, 1, 30), wobble=0.0)
    dev = np.max(np.linalg.norm(pts[0] - plain[0], axis=1))
    check(0.0 < dev < 0.05, f"wobble at most ~0.045 (got {dev:.4f})")
    grid = np.tile(np.linspace(0, 1, 12), (6, 1))
    pts2, _ = strand_points(a, b, turns, np.zeros(6), grid)
    check(pts2.shape == (6, 12, 3), "per-fiber t grid")


def section_f_lineage():
    print("\n--- F: lineage shares ---")
    from primeatlas.visualization.sphere.fiber_geometry import lineage_grid, lineage_piece_kinds, lineage_shares
    anc, taken, free = lineage_shares(PRIMES)
    check(np.allclose([anc[0], taken[0], free[0]], [0, 0.5, 0.5]), "2: 0 | 1/2 | 1/2")
    check(np.allclose([anc[1], taken[1], free[1]], [1 / 2, 1 / 6, 1 / 3]), "3: 1/2 | 1/6 | 1/3")
    check(np.allclose([anc[2], taken[2], free[2]], [2 / 3, 1 / 15, 4 / 15]), "5: 2/3 | 1/15 | 4/15")
    check(np.allclose(anc + taken + free, 1.0), "the shares sum to 1")
    prod = Fraction(1)
    for k, p in enumerate(PRIMES):
        want = (1 - prod, prod / p, prod * (1 - Fraction(1, p)))
        prod *= 1 - Fraction(1, p)
        if not np.allclose([anc[k], taken[k], free[k]], [float(x) for x in want]):
            check(False, f"shares of {p}")
            break
    else:
        check(True, "shares exact for every ring prime")
    t = lineage_grid(anc, taken, 30)
    check(t.shape == (len(PRIMES), 32), f"grid = samples + 2 breakpoints (got {t.shape})")
    check(np.all(np.diff(t, axis=1) >= 0) and np.allclose(t[:, 0], 0) and np.allclose(t[:, -1], 1), "sorted 0..1")
    kinds = lineage_piece_kinds(t, anc, taken)
    lengths = np.diff(t, axis=1)
    for k in (1, 2, 6, 24):
        got = [lengths[k][kinds[k] == kind].sum() for kind in (0, 1, 2)]
        check(np.allclose(got, [anc[k], taken[k], free[k]]),
              f"{PRIMES[k]}: piece lengths per kind = shares (got {np.round(got, 5)})")
        check(all((kinds[k] == kind).any() for kind in (1, 2)), f"{PRIMES[k]}: taken and free have pieces")


def main():
    for section in (section_a_pencil, section_b_pairs, section_c_residues, section_d_strength, section_e_strands,
                    section_f_lineage):
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
