"""
assembly_layout.py -- the arithmetic of the assembly animation. Level k of the wheel has
period M = p_1 * ... * p_k and L = prod(p_i - 1) lanes (the residues mod M no level prime
divides). The next level is built without computing anything: q = p_{k+1} copies of the
period side by side (values r + j*M, j = 0..q-1), minus the one residue class 0 mod q.
Because M is invertible mod q, every lane loses exactly one of its q copies, so the
lanes become L * (q - 1) and the period M * q.

The next prime is read off the new level as its smallest survivor > 1, and every
survivor below its square is prime.

Timeline: each step plays the phases PHASES, `frames` ticks each.
"""

import numpy as np

from primeatlas.visualization.tree.tree_layout import next_prime as _next_prime_after

PHASE_COPY = 0
PHASE_STRIKE = 1
PHASE_PRIME = 2
PHASE_COLLAPSE = 3
PHASES = ("copy", "strike", "prime", "collapse")


def first_primes(count):
    """The first `count` primes."""
    primes = []
    p = 1
    while len(primes) < count:
        p = _next_prime_after(p)
        primes.append(p)
    return primes


def next_lanes(lanes, period, q):
    """The lanes of period*q from the lanes of `period`: the q copies r + j*period of
    every lane, without the multiples of q (sorted int64)."""
    copies = (lanes[None, :] + np.arange(q, dtype=np.int64)[:, None] * period).ravel()
    return copies[copies % q != 0]


def survivor_residues(primes):
    """Sorted int64 residues r in [0, M), M = prod(primes), that no prime divides
    ([0] for no primes: one lane holding every integer), built copy by copy."""
    lanes = np.zeros(1, dtype=np.int64)
    period = 1
    for p in primes:
        lanes = next_lanes(lanes, period, p)
        period *= p
    return lanes


class AssemblyStep:
    """One step k -> k+1: `q` copies of the period `period_before` (lanes `lanes_before`)
    give the period `period_after` with `lanes_after` lanes. `removed_per_copy[j]`: the
    old lanes whose copy j (values r + j*period_before) is a multiple of q, or None when
    the lanes were not enumerated. `next_prime`: smallest survivor > 1 of the new level;
    `square` = next_prime**2."""

    def __init__(self, index, q, primes_before, period_before, lanes_before, removed_per_copy, next_prime):
        self.index = index
        self.q = q
        self.primes_before = tuple(primes_before)
        self.period_before = period_before
        self.period_after = period_before * q
        self.lanes_before = lanes_before
        self.lanes_after = lanes_before * (q - 1)
        self.removed_per_copy = removed_per_copy
        self.next_prime = next_prime
        self.square = next_prime * next_prime

    def lanes(self):
        """The old period's lanes (survivor residues), enumerated on demand."""
        return survivor_residues(self.primes_before)


def _removed_per_copy(lanes, period, q):
    copy_of_lane = (-(lanes % q) * pow(period % q, -1, q)) % q
    return tuple(int(c) for c in np.bincount(copy_of_lane, minlength=q))


def _smallest_survivor_above_one(lanes_after, period_after):
    candidates = np.where(lanes_after > 1, lanes_after, lanes_after + period_after)
    return int(candidates.min())


def build_steps(depth, max_lanes=200_000):
    """The first `depth` steps, starting from period 1 with one lane. The old lanes are
    enumerated (removed_per_copy, next_prime read off the new survivors) while there are
    at most `max_lanes` of them; past that the counts are exact products and next_prime
    is the next prime after q."""
    primes = first_primes(depth)
    steps = []
    period, lanes = 1, 1
    residues = np.zeros(1, dtype=np.int64)
    for index, q in enumerate(primes):
        removed = None
        if residues is not None and lanes <= max_lanes and period * q < 2 ** 62:
            removed = _removed_per_copy(residues, period, q)
            residues = next_lanes(residues, period, q)
            next_p = _smallest_survivor_above_one(residues, period * q)
        else:
            residues = None
            next_p = _next_prime_after(q)
        steps.append(AssemblyStep(index, q, primes[:index], period, lanes, removed, next_p))
        period *= q
        lanes *= q - 1
    return steps


class Timeline:
    """Animation position t in [0, total]: step_count steps of len(PHASES) phases,
    `frames` ticks each."""

    def __init__(self, step_count, frames):
        self.step_count = int(step_count)
        self.frames = max(1, int(frames))
        self.step_ticks = len(PHASES) * self.frames
        self.total = self.step_count * self.step_ticks

    def clamp(self, t):
        return max(0, min(self.total, int(t)))

    def step_start(self, step):
        return self.clamp(step * self.step_ticks)

    def locate(self, t):
        """(step, phase index, frac in [0, 1]) at position t."""
        t = self.clamp(t)
        if t >= self.total:
            return self.step_count - 1, len(PHASES) - 1, 1.0
        phase_global, offset = divmod(t, self.frames)
        step, phase = divmod(phase_global, len(PHASES))
        return step, phase, offset / self.frames

    def next_boundary(self, t, per_step=False):
        unit = self.step_ticks if per_step else self.frames
        return self.clamp((self.clamp(t) // unit + 1) * unit)

    def prev_boundary(self, t, per_step=False):
        unit = self.step_ticks if per_step else self.frames
        t = self.clamp(t)
        return self.clamp(((t - 1) // unit) * unit) if t > 0 else 0
