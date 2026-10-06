"""
fiber_geometry.py -- the pure math of the sphere's fibers mode: the pencil orbits, the
pair table, the resonance strength of a pair, the strands drawn between two orbit points
and the lineage shares. Pure numpy, no GL.

Pencil orbits: orbit i lies in the plane with normal (0, sin a, cos a), a = 38 + 104 *
frac(i * 0.618...) degrees, moved along its normal to pass through the node (0, 0, 1);
every orbit touches the x axis there, so the orbits form a pencil of circles through the
node. Phases are those of sphere_geometry.ring_phases.

Resonance: the pair p < q is strong when N is near a multiple of pq -- strength =
exp(-(d/0.115)^2 / 2), d the distance of (N mod pq + frac)/pq to the nearest integer;
score = 0.72 * strength + 0.28/(1 + ln pq) (+1 for a pair of the focused orbit). N mod pq
comes from N mod p and N mod q (CRT), so it is exact for any N.

Lineage: the fiber of p_k runs from its parent p_{k-1}. Along it the shares of the number
line after sieving by every ring prime up to p: the ancestors' multiples 1 - prod_{q<p}(1 -
1/q), p's own new multiples prod_{q<p}(1 - 1/q)/p, and what stays free prod_{q<=p}(1 - 1/q).
"""

import numpy as np

from primeatlas.visualization.sphere.sphere_geometry import RingFrames

_GOLDEN_FRACTION = 0.618033988749895
_TILT_MIN_DEG = 38.0
_TILT_SPAN_DEG = 104.0
STRENGTH_WIDTH = 0.115
_STRENGTH_WEIGHT = 0.72
_BASE_WEIGHT = 0.28
WOBBLE = 0.045
_MIN_STRAND_ANGLE = 1e-5
_PARALLEL_EPS = 1e-8
# resonance_top pruning: pairs within this distance of a multiple of pq, the share of
# pairs above the bonus cut (1/_PRUNE_SHARE), pruning only past this many pairs per fiber.
_PRUNE_NEAR = 0.02
_PRUNE_SHARE = 200
_PRUNE_FACTOR = 64


def pencil_angles(count):
    """The tilt (radians) of every orbit index."""
    frac = (np.arange(count) * _GOLDEN_FRACTION) % 1.0
    return np.radians(_TILT_MIN_DEG + _TILT_SPAN_DEG * frac)


def pencil_frames(angles):
    """The circle of every tilt; see the module docstring."""
    a = np.asarray(angles, dtype=np.float64)
    s, c = np.sin(a), np.cos(a)
    zero = np.zeros_like(a)
    normal = np.stack([zero, s, c], axis=1)
    center = c[:, None] * normal
    radial = np.stack([zero, -c, s], axis=1)
    tangent = np.tile(np.array([1.0, 0.0, 0.0]), (len(a), 1))
    return RingFrames(normal, center, s.copy(), radial, tangent)


def pair_cap_orbits(cap):
    """The largest m with m(m-1)/2 <= cap (at least 1)."""
    cap = max(0, int(cap))
    m = int((1 + (1 + 8 * cap) ** 0.5) / 2)
    while m * (m - 1) // 2 > cap:
        m -= 1
    while (m + 1) * m // 2 <= cap:
        m += 1
    return max(1, m)


def modinv(a, m):
    """a^-1 mod m elementwise (int64 arrays, gcd(a, m) = 1)."""
    m = np.asarray(m, dtype=np.int64)
    old_r = np.asarray(a, dtype=np.int64) % m
    r = m.copy()
    old_s = np.ones_like(m)
    s = np.zeros_like(m)
    while np.any(r != 0):
        live = r != 0
        q = np.where(live, old_r // np.where(live, r, 1), 0)
        old_r, r = np.where(live, r, old_r), np.where(live, old_r - q * r, r)
        old_s, s = np.where(live, s, old_s), np.where(live, old_s - q * s, s)
    return old_s % m


def crt_residues(ri, rj, pi, pj, inv):
    """N mod pi*pj from ri = N mod pi, rj = N mod pj, inv = pi^-1 mod pj."""
    t = ((rj - ri) % pj) * inv % pj
    return ri + pi * t


class PairTable:
    """The pairs i < j of the first `orbits` ring primes (orbits(orbits-1)/2 <= cap),
    j-major: the pairs of the first a orbits are the first a(a-1)/2 rows."""

    def __init__(self, primes, cap):
        self.orbits = min(len(primes), pair_cap_orbits(cap))
        m = self.orbits
        p = np.asarray(primes[:m], dtype=np.int64)
        j = np.repeat(np.arange(m, dtype=np.int64), np.arange(m, dtype=np.int64))
        offsets = np.arange(m, dtype=np.int64) * (np.arange(m, dtype=np.int64) - 1) // 2
        self.i = np.arange(len(j), dtype=np.int64) - offsets[j]
        self.j = j
        self.p_i, self.p_j = p[self.i], p[j]
        self.period = self.p_i * self.p_j
        self.inv = modinv(self.p_i, self.p_j)
        self.base = pair_base(self.period)
        self.inv_period = 1.0 / self.period.astype(np.float64)

    def count(self, active):
        a = min(int(active), self.orbits)
        return a * (a - 1) // 2


def pair_residues(table, ring_res, count):
    """N mod p*q of the first `count` table pairs; `ring_res` = N mod p per ring prime."""
    i, j = table.i[:count], table.j[:count]
    return crt_residues(ring_res[i], ring_res[j], table.p_i[:count], table.p_j[:count], table.inv[:count])


def pair_strength(res, frac, period):
    """exp(-(d/0.115)^2 / 2), d = distance of (res + frac)/period to the nearest integer."""
    period = np.asarray(period, dtype=np.float64)
    x = np.remainder(np.asarray(res, dtype=np.float64) + frac, period) / period
    d = np.minimum(x, 1.0 - x)
    return gauss(d)


def pair_base(period):
    """0.28/(1 + ln period)."""
    return _BASE_WEIGHT / (1.0 + np.log(np.asarray(period, dtype=np.float64)))


def pair_scores(strength, period, focused):
    """0.72 * strength + 0.28/(1 + ln period) + 1 per focused pair."""
    return _STRENGTH_WEIGHT * np.asarray(strength) + pair_base(period) + np.asarray(focused, dtype=np.float64)


def top_pairs(scores, count):
    """Indices of the `count` highest scores, highest first (ties by index)."""
    scores = np.asarray(scores)
    count = max(0, min(int(count), len(scores)))
    if count == 0:
        return np.zeros(0, dtype=np.int64)
    if count < len(scores):
        picked = np.argpartition(-scores, count - 1)[:count]
    else:
        picked = np.arange(len(scores))
    return picked[np.lexsort((picked, -scores[picked]))]


def gauss(d):
    """exp(-(d/0.115)^2 / 2)."""
    return np.exp(-0.5 * (np.asarray(d) / STRENGTH_WIDTH) ** 2)


def bonus_cut(bonus, count):
    """(cut, above): a bonus value with a small share of the pairs above it and the mask of
    those pairs -- the pruning split of resonance_top, fixed per N."""
    n = len(bonus)
    k = min(n, max(4 * int(count), n // _PRUNE_SHARE))
    cut = float(np.partition(bonus, n - k)[n - k]) if k else float("inf")
    return cut, bonus > cut


def resonance_top(phase0, inv_period, bonus, split, frac, count):
    """The `count` best pairs by 0.72 * strength + bonus (bonus = base + focus), highest
    first, and their strengths; phase0 = (N mod pq)/pq, inv_period = 1/pq, `split` from
    bonus_cut. Exact: the strengths are evaluated only for the pairs near a multiple of
    pq or above the cut, and that result is accepted only when no other pair can reach
    it, else every pair is evaluated."""
    x = np.multiply(inv_period, frac)
    x += phase0
    x -= np.floor(x)
    d = np.minimum(x, np.subtract(1.0, x))
    if 0 < count and _PRUNE_FACTOR * count < len(d):
        cut, above = split
        near = d < _PRUNE_NEAR
        near |= above
        cand = np.flatnonzero(near)
        if len(cand) >= count:
            strength = gauss(d[cand])
            scores = _STRENGTH_WEIGHT * strength + bonus[cand]
            top = top_pairs(scores, count)
            if _STRENGTH_WEIGHT * gauss(_PRUNE_NEAR) + cut < scores[top[-1]]:
                return cand[top], strength[top]
    strength = gauss(d)
    top = top_pairs(_STRENGTH_WEIGHT * strength + bonus, count)
    return top, strength[top]


def strand_points(a, b, turns, phase, t, wobble=WOBBLE):
    """The strands from a[k] to b[k] (unit vectors, (k, 3)) sampled at t in [0, 1] -- (S,)
    shared or (k, S) per strand: the great-circle arc, wobbled sideways by
    wobble * sin(pi t) * sin(2 pi turns t + phase). Returns (points (k, S, 3), valid (k,)):
    a strand whose ends coincide is invalid."""
    a = np.asarray(a, dtype=np.float64).reshape(-1, 3)
    b = np.asarray(b, dtype=np.float64).reshape(-1, 3)
    k = len(a)
    t = np.asarray(t, dtype=np.float64)
    t = np.broadcast_to(t, (k, t.shape[-1])) if t.ndim == 1 else t
    dot = np.clip(np.einsum("ij,ij->i", a, b), -1.0, 1.0)
    theta = np.arccos(dot)
    valid = theta > _MIN_STRAND_ANGLE
    normal = np.cross(a, b)
    length = np.linalg.norm(normal, axis=1)
    flat = length < _PARALLEL_EPS
    if np.any(flat):
        helper = np.where((np.abs(a[:, 0]) < 0.8)[:, None], np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0]))
        alt = np.cross(a, helper)
        normal = np.where(flat[:, None], alt, normal)
        length = np.linalg.norm(normal, axis=1)
    normal = normal / length[:, None]
    toward = np.cross(normal, a)
    angle = theta[:, None] * t
    base = a[:, None, :] * np.cos(angle)[:, :, None] + toward[:, None, :] * np.sin(angle)[:, :, None]
    wave = (wobble * np.sin(np.pi * t)
            * np.sin(2.0 * np.pi * np.asarray(turns, dtype=np.float64)[:, None] * t
                     + np.asarray(phase, dtype=np.float64)[:, None]))
    points = base * np.cos(wave)[:, :, None] + normal[:, None, :] * np.sin(wave)[:, :, None]
    points /= np.linalg.norm(points, axis=2, keepdims=True)
    return points, valid


def strand_turns(p, q):
    """Wobble turns of the strand of p and q: 1 + (p + q) mod 3."""
    return 1 + (np.asarray(p, dtype=np.int64) + np.asarray(q, dtype=np.int64)) % 3


def lineage_shares(primes):
    """(ancestors, taken, free) per ring prime; see the module docstring."""
    p = np.asarray([float(v) for v in primes])
    keep = 1.0 - 1.0 / p
    prior = np.concatenate([[1.0], np.cumprod(keep)[:-1]]) if len(p) else p
    return 1.0 - prior, prior / p, prior * keep


def lineage_grid(ancestors, taken, samples):
    """Per fiber: `samples` equal steps over [0, 1] plus both share breakpoints, sorted."""
    ancestors = np.asarray(ancestors, dtype=np.float64)
    k = len(ancestors)
    grid = np.concatenate([np.tile(np.linspace(0.0, 1.0, samples), (k, 1)), ancestors[:, None],
                           (ancestors + np.asarray(taken))[:, None]], axis=1)
    return np.sort(grid, axis=1)


def lineage_piece_kinds(t, ancestors, taken):
    """Per piece between consecutive t: 0 = ancestors, 1 = taken by p, 2 = free."""
    mid = 0.5 * (t[:, :-1] + t[:, 1:])
    a = np.asarray(ancestors)[:, None]
    return np.where(mid < a, 0, np.where(mid < a + np.asarray(taken)[:, None], 1, 2))
