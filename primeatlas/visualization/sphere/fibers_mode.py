"""
fibers_mode.py -- FibersMode, the sphere's fibers viz-mode: the first K primes as a pencil
of orbits through the common node (fiber_geometry.pencil_frames), the point of orbit p at
phase 2*pi*N/p, and fibers drawn between orbit points. It plays, steps, reads the storage
and rotates exactly as the rings mode (SphereMode); this class adds the fibers and the
focused orbit's phase.

Fibers (--sphere-fibers):
  resonance -- the --sphere-visible-fibers pairs p < q with the highest score (strength
               near multiples of pq, see fiber_geometry.py), evaluated over every pair of
               the first M orbits (M(M-1)/2 <= --sphere-pair-cap) plus every pair of the
               focused orbit;
  lineage   -- the chain 2 -> 3 -> 5 -> ...: the fiber of p_k from its parent p_{k-1},
               present once p_k <= N, brightening near multiples of p_{k-1} * p_k, drawn
               in three parts: the ancestors' share, p's own multiples, the free rest
               (at most --sphere-max-curves fibers, smallest primes first, plus the
               focused orbit's).

Phase: a click on an orbit point focuses its orbit (its phase arc from the node, a tick
per residue, N mod p in the HUD); a click outside the sphere clears the focus, as does N
dropping below the focused prime or R.
"""

import bisect
import math

import numpy as np

from primeatlas.visualization.sphere.fiber_draw import (
    lineage_style, phase_overlay, resonance_style, strand_rows,
)
from primeatlas.visualization.sphere.fiber_geometry import (
    PairTable, bonus_cut, crt_residues, lineage_grid, lineage_piece_kinds, lineage_shares, modinv, pair_base,
    pair_residues, pair_strength, pencil_angles, pencil_frames, resonance_top, strand_points, strand_turns,
)
from primeatlas.visualization.sphere.sphere_draw import _subset
from primeatlas.visualization.sphere.sphere_geometry import project, residues, ring_points, view_matrix
from primeatlas.visualization.sphere.sphere_mode import SphereMode

FIBERS_RESONANCE = "resonance"
FIBERS_LINEAGE = "lineage"
FIBER_KINDS = (FIBERS_RESONANCE, FIBERS_LINEAGE)

_DEFAULTS = {
    "sphere_fibers": FIBERS_RESONANCE,
    "sphere_visible_fibers": 32,
    "sphere_pair_cap": 2_000_000,
    "sphere_fiber_samples": 30,
}
_MIN_SAMPLES = 2
# Click tolerance in pixels around a point marker's radius, and outside the sphere.
_PICK_SLOP_PX = 4.0
_OUTSIDE_SLOP_PX = 3.0


class FibersMode(SphereMode):
    name = "sphere_fibers"
    window_title = "PrimeAtlas -- Sphere fibers"
    count_label = "rings"

    def __init__(self, session, config):
        get = lambda key: config.get(key, _DEFAULTS[key])  # noqa: E731
        self.kind = str(get("sphere_fibers"))
        self.visible = int(get("sphere_visible_fibers"))
        self.samples = int(get("sphere_fiber_samples"))
        self.pair_cap = int(get("sphere_pair_cap"))
        super().__init__(session, config)
        self.focus = None
        self._positions = np.zeros((0, 3))
        self.fiber_pairs = []
        self.fiber_strengths = []
        self.evaluated_pairs = 0
        self._fibers = None
        self._pair_cache = None
        primes = np.asarray(self.rings, dtype=np.int64)
        if self.kind == FIBERS_RESONANCE:
            self.table = PairTable(self.rings, self.pair_cap)
        else:
            self.table = None
            self.shares = lineage_shares(self.rings)
            self._chain_inv = modinv(primes[:-1], primes[1:]) if len(primes) > 1 else np.zeros(0, np.int64)
        self._primes = primes

    # -- launch -----------------------------------------------------------------

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument("--sphere-fibers", type=str, default=_DEFAULTS["sphere_fibers"],
                            help="sphere fibers mode: resonance (the strongest pairs p, q near multiples of "
                                 "pq) or lineage (the chain 2 -> 3 -> 5 -> ..., each prime from its parent)")
        parser.add_argument("--sphere-visible-fibers", type=int, default=_DEFAULTS["sphere_visible_fibers"],
                            help="sphere fibers mode: resonance fibers drawn (the strongest)")
        parser.add_argument("--sphere-pair-cap", type=int, default=_DEFAULTS["sphere_pair_cap"],
                            help="sphere fibers mode: pairs evaluated at most (those of the first M orbits, "
                                 "plus the focused orbit's)")
        parser.add_argument("--sphere-fiber-samples", type=int, default=_DEFAULTS["sphere_fiber_samples"],
                            help="sphere fibers mode: points per fiber strand")

    @classmethod
    def validate_arguments(cls, parser, args):
        if args.sphere_fibers not in FIBER_KINDS:
            parser.error(f"--sphere-fibers must be one of {', '.join(FIBER_KINDS)}, got {args.sphere_fibers!r}")
        for flag, value in (("--sphere-visible-fibers", args.sphere_visible_fibers),
                            ("--sphere-pair-cap", args.sphere_pair_cap)):
            if value < 0:
                parser.error(f"{flag} must be >= 0, got {value}")
        if args.sphere_fiber_samples < _MIN_SAMPLES:
            parser.error(f"--sphere-fiber-samples must be >= {_MIN_SAMPLES}, got {args.sphere_fiber_samples}")

    @classmethod
    def prepare_launch(cls, args, launch):
        return {key: getattr(args, key) for key in _DEFAULTS}

    # -- frame data -------------------------------------------------------------

    def _orbit_frames(self):
        return pencil_frames(pencil_angles(len(self.rings)))

    def _focus_index(self, active):
        if self.focus is None:
            return None
        k = bisect.bisect_left(self.rings, self.focus)
        return k if k < active and self.rings[k] == self.focus else None

    def _prepare_frame(self, n, frac, active, phases):
        if self.focus is not None and self._focus_index(active) is None:
            self.focus = None
        self._positions = ring_points(_subset(self.ring_frames, np.arange(active)), phases[:active])
        focus = self._focus_index(active)
        if self.kind == FIBERS_RESONANCE:
            self._resonance(n, frac, active, focus)
        else:
            self._lineage(n, frac, active, focus)

    def _pairs_at(self, n, active, focus):
        """Every evaluated pair at a whole N, cached: (i, j, N mod pq, (N mod pq)/pq, 1/pq,
        base + focus bonus, the bonus cut)."""
        key = (n, active, focus, self.visible)
        if self._pair_cache is not None and self._pair_cache[0] == key:
            return self._pair_cache[1]
        ring_res = residues(n, self.rings[:active])
        count = self.table.count(active)
        i, j = self.table.i[:count], self.table.j[:count]
        res = pair_residues(self.table, ring_res, count)
        inv_period, base = self.table.inv_period[:count], self.table.base[:count]
        if focus is not None and active > self.table.orbits:
            others = np.arange(active, dtype=np.int64)
            others = others[(others != focus) & (np.maximum(others, focus) >= self.table.orbits)]
            fi = np.minimum(others, focus)
            fj = np.maximum(others, focus)
            pi, pj = self._primes[fi], self._primes[fj]
            fres = crt_residues(ring_res[fi], ring_res[fj], pi, pj, modinv(pi, pj))
            fperiod = pi * pj
            i, j, res = np.concatenate([i, fi]), np.concatenate([j, fj]), np.concatenate([res, fres])
            inv_period = np.concatenate([inv_period, 1.0 / fperiod.astype(np.float64)])
            base = np.concatenate([base, pair_base(fperiod)])
        bonus = base + ((i == focus) | (j == focus)) if focus is not None else base
        value = (i, j, res, res * inv_period, inv_period, bonus, bonus_cut(bonus, self.visible))
        self._pair_cache = (key, value)
        return value

    def _resonance(self, n, frac, active, focus):
        self.fiber_pairs, self.fiber_strengths, self._fibers = [], [], None
        self.evaluated_pairs = 0
        if active < 2:
            return
        i, j, res, phase0, inv_period, bonus, cut = self._pairs_at(n, active, focus)
        self.evaluated_pairs = len(i)
        if self.visible <= 0 or not len(i):
            return
        picked, strength = resonance_top(phase0, inv_period, bonus, cut, frac, self.visible)
        i, j, res = i[picked], j[picked], res[picked]
        p, q = self._primes[i], self._primes[j]
        period = p * q
        focused = (i == focus) | (j == focus) if focus is not None else np.zeros(len(i), dtype=bool)
        phase = 2.0 * np.pi * np.remainder(res.astype(np.float64) + frac, period) / period
        points, valid = strand_points(self._positions[i], self._positions[j], strand_turns(p, q), phase,
                                      np.linspace(0.0, 1.0, self.samples))
        rgb, alpha = resonance_style(strength, focused)
        self._fibers = (points, valid, rgb, alpha)
        self.fiber_pairs = list(zip(p.tolist(), q.tolist()))
        self.fiber_strengths = strength.tolist()

    def _lineage(self, n, frac, active, focus):
        self.fiber_pairs, self.fiber_strengths, self._fibers = [], [], None
        if active < 2:
            return
        child = np.arange(1, min(active, self.style.max_curves + 1), dtype=np.int64)
        if focus is not None:
            extra = [k for k in (focus, focus + 1) if 1 <= k < active and k > child[-1:].max(initial=0)]
            child = np.concatenate([child, np.asarray(extra, dtype=np.int64)])
        if not len(child):
            return
        parent = child - 1
        ring_res = residues(n, self.rings[:active])
        p, q = self._primes[parent], self._primes[child]
        res = crt_residues(ring_res[parent], ring_res[child], p, q, self._chain_inv[parent])
        period = p * q
        strength = pair_strength(res, frac, period)
        ancestors, taken = self.shares[0][child], self.shares[1][child]
        t = lineage_grid(ancestors, taken, self.samples)
        phase = 2.0 * np.pi * np.remainder(res.astype(np.float64) + frac, period) / period
        points, valid = strand_points(self._positions[parent], self._positions[child], strand_turns(p, q), phase, t)
        focused = (parent == focus) | (child == focus) if focus is not None else np.zeros(len(child), dtype=bool)
        rgb, alpha = lineage_style(lineage_piece_kinds(t, ancestors, taken), strength, focused)
        self._fibers = (points, valid, rgb, alpha)
        self.fiber_pairs = list(zip(p.tolist(), q.tolist()))
        self.fiber_strengths = strength.tolist()

    def _draw_frame(self):
        super()._draw_frame()
        active, phases, _factors, _birth, _n = self._frame
        matrix = view_matrix(self.yaw, self.pitch)
        segments, markers = [self.draw.segments], [self.draw.markers]
        if self._fibers is not None:
            segments.append(strand_rows(*self._fibers, matrix, self.radius))
        focus = self._focus_index(active)
        if focus is not None:
            seg, mk = phase_overlay(self.ring_frames, self.curve_cache, focus, self.rings[focus], float(phases[focus]),
                                    matrix, self.radius, self.style.point_size)
            segments.append(seg)
            markers.append(mk)
        self.draw.segments = np.concatenate(segments).astype(np.float32)
        self.draw.markers = np.concatenate(markers).astype(np.float32)

    def _extra_hud_lines(self, n, frac, active):
        lines = []
        if self.kind == FIBERS_RESONANCE:
            text = f"Fibers: resonance, the {len(self.fiber_pairs):,} strongest of {self.evaluated_pairs:,} pairs"
            if active > self.table.orbits:
                text += f" (those of the first {self.table.orbits:,} orbits + the focused orbit's)"
            lines.append(text)
            if self.fiber_pairs:
                p, q = self.fiber_pairs[0]
                lines.append(f"Strongest: {p:,} · {q:,} = {p * q:,}, strength {self.fiber_strengths[0]:.2f}")
        else:
            total = max(0, active - 1)
            if total:
                chain = " -> ".join(f"{p:,}" for p in self.rings[:min(active, 3)])
                chain += f" -> ... -> {self.rings[active - 1]:,}" if active > 3 else ""
                text = f"Fibers: lineage {chain} ({total:,} fibers"
                text += f", drawn {len(self.fiber_pairs):,})" if len(self.fiber_pairs) != total else ")"
            else:
                text = "Fibers: lineage (none yet: the chain starts at 2 -> 3)"
            lines.append(text)
        focus = self._focus_index(active)
        if focus is None:
            lines.append("Phase: click an orbit point to follow it (a click outside the sphere clears it)")
            return lines
        p = self.rings[focus]
        r = int(residues(n, [p])[0])
        degrees = 360.0 * (((r + frac) / p) % 1.0)
        lines.append(f"Phase of {p:,}: N mod p = {r:,} / {p:,}, {degrees:.1f}°")
        if self.kind == FIBERS_LINEAGE:
            a, b, c = (float(share[focus]) for share in self.shares)
            if focus == 0:
                lines.append(f"{p:,} starts the chain: taken by {p:,} {b:.4f} | free {c:.4f}")
            else:
                lines.append(f"Fiber {self.rings[focus - 1]:,} -> {p:,}: ancestors {a:.4f} | "
                             f"taken by {p:,} {b:.4f} | free {c:.4f}")
        return lines

    # -- navigation -------------------------------------------------------------

    def click(self, world_x, world_y, world_per_pixel):
        """Focuses the orbit whose point is under the click (the front one), clears the
        focus outside the sphere; anything else is not handled."""
        if self._frame is None:
            return False
        matrix = view_matrix(self.yaw, self.pitch)
        if len(self._positions):
            sx, sy, toward = project(self._positions, matrix, self.radius)
            tolerance = (0.5 * self.style.point_size + _PICK_SLOP_PX) * world_per_pixel
            hit = np.flatnonzero(np.hypot(sx - world_x, sy - world_y) <= tolerance)
            if len(hit):
                self.focus = self.rings[int(hit[np.argmax(toward[hit])])]
                return True
        if math.hypot(world_x, world_y) > self.radius + _OUTSIDE_SLOP_PX * world_per_pixel and self.focus is not None:
            self.focus = None
            return True
        return False

    def reset_state(self):
        super().reset_state()
        self.focus = None
