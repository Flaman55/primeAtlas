"""
test_fibers_mode.py -- spec tests for primeatlas/visualization/sphere/fibers_mode.py
(FibersMode, the sphere's fibers mode) inside the shared RenderSession. No GL; a fake
storage stands in for the prime archive.

Spec:
  A. Registration: "sphere_fibers" is a registered viz-mode; it plays, steps and rotates as
     the rings mode does (same N sub-steps, storage list, drag); its orbits are the pencil
     orbits (fiber_geometry.pencil_frames); one marker per orbit taking part plus the node.
  B. Resonance: the drawn fibers are the --sphere-visible-fibers pairs p < q (both orbits
     taking part) with the highest score 0.72 * strength + 0.28/(1 + ln pq) (+1 touching
     the focused orbit), strongest first -- the same as a full sort of every pair; 0
     visible fibers draws none.
  C. Pair cap: only the pairs among the first M orbits (M(M-1)/2 <= --sphere-pair-cap) are
     evaluated, plus the pairs of the focused orbit with every orbit taking part.
  D. Lineage: one fiber per orbit p_k taking part (k >= 1), from its parent p_{k-1}; its
     strength is that of the pair (p_{k-1}, p_k); it is drawn in the ancestor, taken and
     free colors; --sphere-visible-fibers does not limit it.
  E. Phase ("Pokaz faze"): a click on an orbit point focuses that orbit (the front one when
     points overlap); a click outside the sphere clears the focus; a click on the sphere
     but on no point changes nothing (not handled). A focused orbit is drawn in the focus
     color with its phase arc, a tick per residue (every ceil(p/60)-th) and its phase point;
     the HUD names N mod p and the phase in degrees. When N drops below the focused prime
     (or on R) the focus is cleared.
  F. View: reproject() after a drag keeps the same fibers (and the HUD).
  G. Big N (past 2**63): fibers and strengths are computed exactly and stay finite.
  H. HUD: names the fiber kind and the drawn count (resonance: of how many pairs; lineage:
     the chain), the strongest resonance pair, and for a focused orbit in lineage its three
     shares.
  J. Hidden rings (--sphere-hide-rings): the fibers are drawn as before, no orbit curve
     except the focused orbit's (with its phase overlay); every point stays.
  I. CLI: --sphere-fibers (resonance|lineage), --sphere-visible-fibers (32),
     --sphere-pair-cap (2,000,000), --sphere-fiber-samples (30) with these defaults; they
     coexist with the rings mode's arguments on one parser; bad values are rejected.

Usage:
    python unitTests/test_fibers_mode.py
"""
import argparse
import bisect
import math
import os
import sys
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


def _sieve(limit):
    flags = bytearray([1]) * (limit + 1)
    flags[0:2] = b"\x00\x00"
    for i in range(2, int(limit ** 0.5) + 1):
        if flags[i]:
            flags[i * i::i] = bytearray(len(flags[i * i::i]))
    return [i for i in range(limit + 1) if flags[i]]


STORED = _sieve(5000)
RINGS = STORED[:25]


class FakeStorage:
    def __init__(self, primes):
        self.primes = list(primes)

    def forward(self, after_n, count):
        i = bisect.bisect_right(self.primes, after_n)
        return self.primes[i:i + count]

    def backward(self, before_n, count):
        i = bisect.bisect_left(self.primes, before_n)
        return self.primes[max(0, i - count):i]


def _make_session(n=100, storage="fake", **overrides):
    from primeatlas.visualization.shared.session import RenderSession
    config = dict(sphere_rings=25, sphere_frames=4, sphere_chunk=200, sphere_spin=0.4, sphere_segments=24,
                  sphere_fibers="resonance", sphere_visible_fibers=12, sphere_pair_cap=10 ** 6,
                  sphere_fiber_samples=16)
    if storage == "fake":
        config["sphere_storage"] = FakeStorage(STORED)
    config.update(overrides)
    return RenderSession(
        primes=np.empty(0, dtype=np.int64), n=n, ceiling=-1, range_mode=False, range_primes=None,
        range_step=1, max_radius=450.0, tempo_ms=60, buffer_margin=1000, can_extend_buffer=False,
        portal_folder=None, viz_mode="sphere_fibers", **config,
    )


def _reference_top(n, active_primes, count, focus=None):
    """The prototype's selection at a whole N."""
    scored = []
    for p, q in combinations(active_primes, 2):
        pq = p * q
        ph = (n % pq) / pq
        s = math.exp(-0.5 * (min(ph, 1 - ph) / 0.115) ** 2)
        scored.append((0.72 * s + 0.28 / (1 + math.log(pq)) + (1.0 if focus in (p, q) else 0.0), p, q))
    scored.sort(key=lambda x: -x[0])
    return [(p, q) for _s, p, q in scored[:count]]


def _screen_points(mode, n):
    from primeatlas.visualization.sphere.sphere_geometry import project, ring_phases, ring_points, view_matrix
    from primeatlas.visualization.sphere.sphere_draw import _subset
    active = bisect.bisect_right(mode.rings, n)
    pts = ring_points(_subset(mode.ring_frames, np.arange(active)), ring_phases(n, 0.0, mode.rings[:active]))
    return project(pts, view_matrix(mode.yaw, mode.pitch), mode.radius)


def _isolated_front_orbit(mode, n, min_px=25.0):
    sx, sy, toward = _screen_points(mode, n)
    for k in np.argsort(-toward):
        d = np.hypot(sx - sx[k], sy - sy[k])
        d[k] = np.inf
        if d.min() > min_px and toward[k] > 0:
            return int(k), float(sx[k]), float(sy[k])
    return None


def _has_rgb(segments, rgb):
    return bool(np.any(np.all(np.abs(segments[:, 2:5] - np.asarray(rgb)) < 1e-3, axis=1)))


def section_a_registration():
    print("\n--- A: registration ---")
    from primeatlas.visualization.mode_registry import MODES
    from primeatlas.visualization.sphere.fiber_geometry import pencil_angles, pencil_frames
    check("sphere_fibers" in MODES, "sphere_fibers is a registered viz-mode")
    s = _make_session(n=100)
    s.rebuild(100)
    check(np.allclose(s.mode.ring_frames.normal, pencil_frames(pencil_angles(25)).normal), "pencil orbits")
    check(len(s.mode.marker_data()) == 25 + 1, f"a marker per orbit plus the node (got {len(s.mode.marker_data())})")
    check(s.toggle_space() is None and s.playback_running, "Space plays")
    for _ in range(4):
        s.tick()
    check(s.n == 101, f"4 ticks = one N (got {s.n})")
    s.scrub_advance(True, True, True)
    check(s.n == 103, f"Ctrl+Right jumps to the next stored prime (got {s.n})")
    s.on_cursor_pos(0, 0)
    s.set_dragging(True)
    s.on_cursor_pos(30, 10)
    check(s.cam_pan == [0.0, 0.0] and s.view_dirty, "a drag rotates")


def section_b_resonance():
    print("\n--- B: resonance ---")
    s = _make_session(n=100, sphere_visible_fibers=12)
    s.rebuild(100)
    want = _reference_top(100, RINGS, 12)
    check(s.mode.fiber_pairs == want, f"top 12 = the prototype's selection (got {s.mode.fiber_pairs[:4]}...)")
    check(len(s.mode.fiber_strengths) == 12 and all(0 <= v <= 1 for v in s.mode.fiber_strengths), "strengths")
    s.rebuild(15)
    check(all(p <= 15 and q <= 15 for p, q in s.mode.fiber_pairs) and len(s.mode.fiber_pairs) == 12,
          f"only orbits taking part (got {s.mode.fiber_pairs})")
    check(s.mode.fiber_pairs[0] == (3, 5), f"N = 15: 3-5 strongest (got {s.mode.fiber_pairs[0]})")
    s.rebuild(2)
    check(s.mode.fiber_pairs == [], "N = 2: one orbit, no pairs")
    zero = _make_session(n=100, sphere_visible_fibers=0)
    zero.rebuild(100)
    check(zero.mode.fiber_pairs == [], "0 visible fibers: none")


def section_c_cap():
    print("\n--- C: pair cap ---")
    s = _make_session(n=100, sphere_pair_cap=10, sphere_visible_fibers=6)
    s.rebuild(100)
    first5 = set(RINGS[:5])
    check(s.mode.fiber_pairs == _reference_top(100, RINGS[:5], 6),
          f"cap 10: the pairs among the first 5 orbits (got {s.mode.fiber_pairs})")
    s.mode.focus = 31
    s.rebuild(100)
    check(len(s.mode.fiber_pairs) == 6 and all(31 in pair for pair in s.mode.fiber_pairs),
          f"the focused orbit's pairs are evaluated past the cap (got {s.mode.fiber_pairs})")
    check(s.mode.fiber_pairs == _reference_top(100, RINGS, 6, focus=31)[:6], "and ranked like the prototype")
    check(not first5 >= {q for _p, q in s.mode.fiber_pairs}, "beyond the first 5 orbits")


def section_d_lineage():
    print("\n--- D: lineage ---")
    from primeatlas.visualization.sphere.fiber_draw import ANCESTOR_RGB, FREE_RGB, TAKEN_RGB
    s = _make_session(n=100, sphere_fibers="lineage", sphere_visible_fibers=3)
    s.rebuild(100)
    check(s.mode.fiber_pairs == list(zip(RINGS[:-1], RINGS[1:])),
          f"a fiber from each parent, not limited by visible fibers (got {len(s.mode.fiber_pairs)})")
    s.rebuild(10)
    check(s.mode.fiber_pairs == [(2, 3), (3, 5), (5, 7)], f"N = 10: 2->3->5->7 (got {s.mode.fiber_pairs})")
    s.rebuild(1)
    check(s.mode.fiber_pairs == [], "N = 1: none")
    s.mode.sub = 0
    s.rebuild(15)
    strengths = dict(zip(s.mode.fiber_pairs, s.mode.fiber_strengths))
    check(abs(strengths[(3, 5)] - 1.0) < 1e-12, "N = 15: the 3->5 fiber at full strength")
    check(strengths[(5, 7)] < 0.5, "5->7 dim at 15")
    seg = s.mode.segment_data()
    check(_has_rgb(seg, ANCESTOR_RGB) and _has_rgb(seg, TAKEN_RGB) and _has_rgb(seg, FREE_RGB),
          "ancestor, taken and free colors drawn")


def section_e_phase():
    print("\n--- E: phase ---")
    from primeatlas.visualization.sphere.fiber_draw import FOCUS_RGB
    s = _make_session(n=100)
    s.rebuild(100)
    found = _isolated_front_orbit(s.mode, 100)
    check(found is not None, "an isolated front orbit point exists to click")
    k, x, y = found
    check(s.mode.click(x + 2.0, y - 1.0, 1.0) is True and s.mode.focus == RINGS[k],
          f"a click on the point focuses its orbit (got {s.mode.focus}, want {RINGS[k]})")
    s.rebuild(100)
    p = RINGS[k]
    step = math.ceil(p / 60)
    ticks = len(range(0, p, step))
    check(len(s.mode.marker_data()) == 25 + 1 + ticks + 1,
          f"ticks per residue plus the phase point (got {len(s.mode.marker_data())}, want {25 + 2 + ticks})")
    check(_has_rgb(s.mode.segment_data(), FOCUS_RGB), "the focused orbit and arc in the focus color")
    text = "\n".join(s.hud_lines)
    check(f"{100 % p} / {p}" in text and "°" in text, f"HUD: N mod p and the degrees (got {s.hud_lines})")
    r = s.mode.radius
    check(s.mode.click(0.0, 0.0, 1.0) in (False, None) or s.mode.focus == p,
          "a click on the sphere off any point keeps the focus")
    check(s.mode.focus == p, "focus kept")
    check(s.mode.click(r * 1.2, 0.0, 1.0) is True and s.mode.focus is None, "a click outside the sphere clears it")
    check(s.mode.click(r * 1.3, 0.0, 1.0) in (False, None), "outside again with no focus: nothing to do")
    s.mode.focus = 97
    s.rebuild(100)
    s.rebuild(90)
    check(s.mode.focus is None, "N below the focused prime clears the focus")
    s.mode.focus = 7
    s.reset()
    check(s.mode.focus is None and s.viz_mode == "sphere_fibers", "R clears the focus, stays in fibers")


def section_f_view():
    print("\n--- F: view ---")
    s = _make_session(n=100)
    s.rebuild(100)
    pairs, hud = list(s.mode.fiber_pairs), s.hud_lines
    before = s.mode.segment_data().copy()
    s.on_cursor_pos(0, 0)
    s.set_dragging(True)
    s.on_cursor_pos(60, 20)
    s.mode.reproject()
    check(s.mode.fiber_pairs == pairs and s.hud_lines is hud, "same fibers and HUD after reproject")
    check(not np.array_equal(before, s.mode.segment_data()), "the fibers are reprojected")


def section_g_big():
    print("\n--- G: big N ---")
    n = 10 ** 30 + 12345
    s = _make_session(n=n, storage=None)
    s.rebuild(n)
    want = _reference_top(n, RINGS, 12)
    check(s.mode.fiber_pairs == want, "exact selection past 2**63")
    check(np.all(np.isfinite(s.mode.segment_data())), "finite draw data")
    lin = _make_session(n=n, storage=None, sphere_fibers="lineage")
    lin.rebuild(n)
    check(len(lin.mode.fiber_pairs) == 24, "lineage past 2**63")


def section_h_hud():
    print("\n--- H: HUD ---")
    s = _make_session(n=100)
    s.rebuild(100)
    text = "\n".join(s.hud_lines).lower()
    check("resonance" in text and "12" in text and "300" in text,
          f"resonance: drawn of 300 pairs (got {s.hud_lines})")
    p, q = s.mode.fiber_pairs[0]
    check(f"{p} · {q}" in "\n".join(s.hud_lines), "the strongest pair is named")
    lin = _make_session(n=100, sphere_fibers="lineage")
    lin.mode.focus = 5
    lin.rebuild(100)
    text = "\n".join(lin.hud_lines)
    check("lineage" in text.lower() and "24" in text, f"lineage and its fiber count (got {lin.hud_lines})")
    check("3 -> 5" in text and "0.6667" in text and "0.0667" in text and "0.2667" in text,
          f"the focused orbit's shares (got {lin.hud_lines})")


def section_i_cli():
    print("\n--- I: CLI ---")
    from primeatlas.visualization.sphere.fibers_mode import FibersMode
    from primeatlas.visualization.sphere.sphere_mode import SphereMode
    parser = argparse.ArgumentParser()
    parser.add_argument("--portal-folder", default=None)
    SphereMode.add_arguments(parser)
    FibersMode.add_arguments(parser)
    args = parser.parse_args([])
    expected = dict(sphere_fibers="resonance", sphere_visible_fibers=32, sphere_pair_cap=2_000_000,
                    sphere_fiber_samples=30)
    got = {k: getattr(args, k) for k in expected}
    check(got == expected, f"defaults (got {got})")
    FibersMode.validate_arguments(parser, args)
    config = FibersMode.prepare_launch(args, None)
    check(all(config[k] == v for k, v in expected.items()), "prepare_launch maps them")

    class _Strict(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError(message)

    strict = _Strict()
    FibersMode.add_arguments(strict)
    for bad in (["--sphere-fibers", "web"], ["--sphere-visible-fibers", "-1"], ["--sphere-pair-cap", "-1"],
                ["--sphere-fiber-samples", "1"]):
        try:
            FibersMode.validate_arguments(strict, strict.parse_args(bad))
            check(False, f"{bad} rejected")
        except ValueError:
            check(True, f"{bad} rejected")


def section_j_hidden_rings():
    print("\n--- J: hidden rings ---")
    from primeatlas.visualization.sphere.fiber_draw import FOCUS_RGB
    from primeatlas.visualization.sphere.sphere_draw import ORBIT_RGB
    shown = _make_session(n=100)
    shown.rebuild(100)
    s = _make_session(n=100, sphere_hide_rings=True)
    s.rebuild(100)
    seg = s.mode.segment_data()
    check(s.mode.fiber_pairs == shown.mode.fiber_pairs and not _has_rgb(seg, ORBIT_RGB),
          "the same fibers, no orbit curve")
    check(len(s.mode.marker_data()) == 25 + 1, "every point and the node stay")
    s.mode.focus = 41
    s.rebuild(100)
    check(_has_rgb(s.mode.segment_data(), FOCUS_RGB), "the focused orbit is still drawn")


def main():
    for section in (section_a_registration, section_j_hidden_rings, section_b_resonance, section_c_cap, section_d_lineage,
                    section_e_phase, section_f_view, section_g_big, section_h_hud, section_i_cli):
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
