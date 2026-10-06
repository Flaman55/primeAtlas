"""
sphere_mode.py -- SphereMode, the sphere's rings viz-mode (see shared/mode.py): the first
K primes as circles on a sphere through one common node; the point of ring p has phase
2*pi*N/p, so the rings dividing N meet at the node. Geometry is sphere_geometry.py, one
frame's draw data sphere_draw.py, the HUD sphere_hud.py; this class holds N's sub-step, the
view and the navigation.

Playback (--sphere-step) walks N by 1 ("n") or from stored prime to stored prime ("p");
each step plays --sphere-frames sub-steps in which the points glide to their next position
(over the whole gap in "p"). Primality of N and the jumps to the previous/next prime come
from the storage, read as a list around N (prime_window.py); without a storage the
primality stays unknown, "p" plays by 1 and the prime jumps stay put. The rings themselves
are sieved (they are the first K primes at any scale).

Navigation: Space plays, Right/Left step N by 1, Ctrl+Right/Ctrl+Left jump to the
next/previous stored prime, Up/Down step N, Home returns to the launch N, R resets to N = 1
and the start view. A left drag rotates the sphere (the camera itself is not panned), the
wheel zooms.
"""

import bisect
import math
import time

import numpy as np

from primeatlas.visualization.shared.mode import VizMode
from primeatlas.visualization.sphere.prime_window import ArchiveStorage, PrimeWindow
from primeatlas.visualization.sphere.sphere_draw import CurveCache, SphereStyle, build_sphere_draw_data
from primeatlas.visualization.sphere.sphere_geometry import (
    ease, residues, ring_angles, ring_frames, ring_phases, view_matrix,
)
from primeatlas.visualization.sphere.sphere_hud import sphere_hud_lines

_DEFAULTS = {
    "sphere_rings": 200,
    "sphere_frames": 8,
    "sphere_chunk": 100_000,
    "sphere_segments": 96,
    "sphere_max_curves": 1000,
    "sphere_spin": 0.4,
    "sphere_point_size": 9.0,
    "sphere_node_size": 22.0,
    "sphere_label_font_size": 35,
    "sphere_step": "n",
    "sphere_hide_rings": False,
}

STEP_N = "n"
STEP_P = "p"
STEP_KINDS = (STEP_N, STEP_P)

SPHERE_MAX_RINGS = 1_000_000
_MIN_SEGMENTS = 8
# Start view (degrees) and the rotation per dragged pixel.
_START_YAW = 38.0
_START_PITCH = 23.0
_DRAG_DEG_PER_PX = 0.35
_MAX_PITCH = 89.0
# Share of the fitted view radius the sphere fills.
_SPHERE_SHARE = 0.92


def first_primes_sieved(count):
    """The first `count` primes, by a sieve bounded with Rosser's estimate."""
    if count < 6:
        return [2, 3, 5, 7, 11][:count]
    limit = int(count * (math.log(count) + math.log(math.log(count)))) + 10
    flags = np.ones(limit + 1, dtype=bool)
    flags[:2] = False
    for i in range(2, int(limit ** 0.5) + 1):
        if flags[i]:
            flags[i * i::i] = False
    return [int(v) for v in np.flatnonzero(flags)[:count]]


class SphereMode(VizMode):
    name = "sphere"
    window_title = "PrimeAtlas -- Sphere"
    count_label = "rings"
    draws_center_marker = False
    uses_prime_ceiling = False

    def __init__(self, session, config):
        super().__init__(session, config)
        get = lambda key: config.get(key, _DEFAULTS[key])  # noqa: E731
        self.rings = first_primes_sieved(int(get("sphere_rings")))
        self.frames = int(get("sphere_frames"))
        self.spin = float(get("sphere_spin"))
        self.label_font_size = int(get("sphere_label_font_size"))
        self.style = SphereStyle(point_size=float(get("sphere_point_size")), node_size=float(get("sphere_node_size")),
                                 segments=int(get("sphere_segments")), max_curves=int(get("sphere_max_curves")),
                                 draw_rings=not bool(get("sphere_hide_rings")))
        self.ring_frames = self._orbit_frames()
        self.curve_cache = CurveCache(self.ring_frames, self.style)
        storage = config.get("sphere_storage")
        self.window = PrimeWindow(storage, int(get("sphere_chunk"))) if storage is not None else None
        self.step = str(get("sphere_step"))
        self.launch_n = int(session.n)
        self.sub = 0
        # The N the current glide ends at (set when a glide starts).
        self.target = None
        self.yaw = _START_YAW
        self.pitch = _START_PITCH
        self.factors = []
        self.birth = False
        self.draw = None
        self._frame = None

    # -- launch -----------------------------------------------------------------

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument("--sphere-rings", type=int, default=_DEFAULTS["sphere_rings"],
                            help=f"sphere mode: rings = the first K primes (1..{SPHERE_MAX_RINGS:,})")
        parser.add_argument("--sphere-frames", type=int, default=_DEFAULTS["sphere_frames"],
                            help="sphere mode: playback ticks per N (the points glide between N and N+1)")
        parser.add_argument("--sphere-chunk", type=int, default=_DEFAULTS["sphere_chunk"],
                            help="sphere mode: storage primes read per load, below and from N")
        parser.add_argument("--sphere-segments", type=int, default=_DEFAULTS["sphere_segments"],
                            help="sphere mode: line segments per ring curve")
        parser.add_argument("--sphere-max-curves", type=int, default=_DEFAULTS["sphere_max_curves"],
                            help="sphere mode: ring curves drawn at most (smallest primes first; the "
                                 "highlighted rings are always drawn)")
        parser.add_argument("--sphere-spin", type=float, default=_DEFAULTS["sphere_spin"],
                            help="sphere mode: view turn in degrees per N during playback (0 = none)")
        parser.add_argument("--sphere-point-size", type=float, default=_DEFAULTS["sphere_point_size"],
                            help="sphere mode: ring point size in pixels")
        parser.add_argument("--sphere-node-size", type=float, default=_DEFAULTS["sphere_node_size"],
                            help="sphere mode: node marker size in pixels")
        parser.add_argument("--sphere-label-font-size", type=int, default=_DEFAULTS["sphere_label_font_size"],
                            help="sphere mode: pixel size of the node label")
        parser.add_argument("--sphere-step", type=str, default=_DEFAULTS["sphere_step"],
                            help="sphere mode: playback walks N by 1 (n) or from stored prime to stored prime (p)")
        parser.add_argument("--sphere-hide-rings", action="store_true",
                            help="sphere modes: draw no ring/orbit curves (the points, the fibers and a focused "
                                 "orbit stay)")

    @classmethod
    def validate_arguments(cls, parser, args):
        if not 1 <= args.sphere_rings <= SPHERE_MAX_RINGS:
            parser.error(f"--sphere-rings must be in 1..{SPHERE_MAX_RINGS}, got {args.sphere_rings}")
        for flag, value in (("--sphere-frames", args.sphere_frames), ("--sphere-chunk", args.sphere_chunk),
                            ("--sphere-label-font-size", args.sphere_label_font_size)):
            if value < 1:
                parser.error(f"{flag} must be >= 1, got {value}")
        if args.sphere_segments < _MIN_SEGMENTS:
            parser.error(f"--sphere-segments must be >= {_MIN_SEGMENTS}, got {args.sphere_segments}")
        if args.sphere_step not in STEP_KINDS:
            parser.error(f"--sphere-step must be one of {', '.join(STEP_KINDS)}, got {args.sphere_step!r}")
        if args.sphere_max_curves < 0:
            parser.error(f"--sphere-max-curves must be >= 0, got {args.sphere_max_curves}")
        for flag, value in (("--sphere-point-size", args.sphere_point_size),
                            ("--sphere-node-size", args.sphere_node_size)):
            if not value > 0:
                parser.error(f"{flag} must be > 0, got {value}")

    @classmethod
    def prepare_launch(cls, args, launch):
        config = {key: getattr(args, key) for key in _DEFAULTS}
        portal = getattr(args, "portal_folder", None)
        config["sphere_storage"] = ArchiveStorage(portal) if portal else None
        return config

    # -- frame data -------------------------------------------------------------

    @property
    def radius(self):
        return self.session.max_radius * _SPHERE_SHARE

    def rebuild(self, n_value, prev_ring_count=None, advancing=False, audio=None):
        """Builds the frame at N + the eased sub-step. The ring point buffers stay empty:
        the sphere draws through marker_data/segment_data/world_labels."""
        s = self.session
        t0 = time.perf_counter()
        n = max(0, int(n_value))
        whole = self.sub == 0
        target = self.target if not whole and self.target is not None and self.target > n else n + 1
        frac = ease(self.sub / self.frames) * (target - n)
        active = bisect.bisect_right(self.rings, n)
        prime_state = self.window.is_prime(n) if self.window is not None else None
        if whole and active:
            hit = residues(n, self.rings[:active]) == 0
            self.factors = [p for p, h in zip(self.rings[:active], hit) if h]
        else:
            self.factors = []
        self.birth = whole and prime_state is True
        phases = ring_phases(n, frac, self.rings[:active]) if active else np.zeros(0)
        self._frame = (active, phases, list(self.factors), self.birth, n)
        self._prepare_frame(n, frac, active, phases)
        self._draw_frame()
        t1 = time.perf_counter()
        prev_p = next_p = None
        if self.window is not None:
            prev_p, next_p = self.window.prev_prime(n), self.window.next_prime(n)
        s.hud_n = n
        s.hud_count = active
        s.hud_rebuild_ms = round(1000 * (t1 - t0), 1)
        s.hud_lines = sphere_hud_lines(n, not whole, self.factors, prime_state if whole else None,
                                       self.rings, active, prev_p, next_p, self.window is not None,
                                       target=target) + self._extra_hud_lines(n, frac, active)
        empty = np.zeros((0, 5), dtype=np.float32)
        return empty, empty, 0, 0

    def _orbit_frames(self):
        return ring_frames(ring_angles(self.rings))

    def _prepare_frame(self, n, frac, active, phases):
        """Hook: the N-dependent state a subclass draws, computed once per rebuild."""

    def _extra_hud_lines(self, n, frac, active):
        """Hook: HUD lines appended after the rings mode's own."""
        return []

    def _draw_frame(self):
        active, phases, factors, birth, n = self._frame
        self.draw = build_sphere_draw_data(self.rings, self.ring_frames, self.curve_cache, active, phases, factors,
                                           birth, n, view_matrix(self.yaw, self.pitch), self.radius, self.style)

    def reproject(self):
        if self._frame is not None:
            self._draw_frame()

    def marker_data(self):
        return None if self.draw is None else self.draw.markers

    def segment_data(self):
        return None if self.draw is None else self.draw.segments

    def world_labels(self):
        return [] if self.draw is None else self.draw.labels

    # -- navigation -------------------------------------------------------------

    def clamp_n(self, n):
        return max(1, n)

    def _next_target(self, n):
        """Where a glide from N ends, or None when the storage has nothing past N."""
        if self.window is None:
            return n + 1
        if self.step == STEP_P:
            return self.window.next_prime(n)
        return None if self.window.is_prime(n + 1) is None else n + 1

    def tick(self):
        s = self.session
        if self.sub == 0:
            target = self._next_target(s.n)
            if target is None:
                s.playback_running = False
                return True
            self.target = target
        self.yaw += self.spin / self.frames
        if self.sub + 1 >= self.frames:
            self.sub = 0
            s.n = self.target
            self.target = None
            s.n_advancing = True
        else:
            self.sub += 1
        s.n_force_rebuild = True
        return False

    def bump_n(self, delta):
        self.sub = 0
        self.target = None
        return False

    def scrub(self, is_right, ctrl_held):
        """Right/Left: N +-1; Ctrl: the next/previous stored prime (stays without one)."""
        s = self.session
        self.sub = 0
        self.target = None
        s.n_force_rebuild = True
        if not ctrl_held:
            s.n = max(1, s.n + (1 if is_right else -1))
        elif self.window is not None:
            jump = self.window.next_prime(s.n) if is_right else self.window.prev_prime(s.n)
            if jump is not None:
                s.n = jump
        return True

    def drag(self, dx, dy):
        self.yaw += dx * _DRAG_DEG_PER_PX
        self.pitch = max(-_MAX_PITCH, min(_MAX_PITCH, self.pitch + dy * _DRAG_DEG_PER_PX))
        return True

    def key(self, name):
        if name == "home":
            self.session.n = self.launch_n
            self.sub = 0
            self.target = None
            return True
        return False

    def reset_state(self):
        self.sub = 0
        self.target = None
        self.yaw = _START_YAW
        self.pitch = _START_PITCH
