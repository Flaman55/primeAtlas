"""
test_sphere_mode.py -- spec tests for primeatlas/visualization/sphere/sphere_mode.py
(SphereMode, the sphere's rings mode) inside the shared RenderSession. No GL; a fake
storage stands in for the prime archive.

Spec:
  A. Registration: "sphere" is a registered viz-mode; RenderSession(viz_mode="sphere")
     builds without loaded primes; the ring buffers stay empty; it draws through
     marker_data/segment_data/world_labels; no center marker, no prime ceiling, count label
     "rings".
  B. Rings: the first K primes (--sphere-rings); a ring takes part once p <= N; the HUD
     count is the number of rings taking part.
  C. Playback: a tick moves the points one sub-step (--sphere-frames sub-steps per N) and
     forces a rebuild; after `frames` ticks N is one higher and the sub-step back at 0; every
     tick turns the view by spin/frames degrees (--sphere-spin per N). With a storage, a tick
     that would move N past the storage's last prime stops playback; without one it never
     stops.
  D. Stepping: Right/Left move N by 1, Ctrl+Right/Ctrl+Left jump to the next/previous
     stored prime, always to sub-step 0; N never drops below 1; at the storage's ends a
     prime jump stays; without a storage Ctrl+Left/Right stay. Up/Down move N by the step
     and reset the sub-step.
  E. Drag: in the sphere a left drag rotates the view (yaw by dx, pitch by dy, pitch held
     within +-89 degrees) instead of panning the camera, and marks the view dirty;
     reproject() rebuilds the draw data for the new view without touching the HUD. In the
     other modes a drag still pans.
  F. Highlights at a whole N (sub-step 0): the factors are the ring primes dividing N, the
     birth is N being a stored prime (a ring itself when N <= p_K); mid-step there are none.
  G. HUD lines: a prime N says so; a composite N lists its ring factors; a composite N
     without one says no ring divides it; outside the storage (or without one) primality
     is unknown; the rings line names 2 .. p_K; mid-step shows N -> N+1; with a storage the
     previous and next stored primes are named.
  H. Draw data: one marker per ring taking part plus the node; the ring curves are capped
     by --sphere-max-curves (smallest primes first) but the highlighted rings are always
     drawn, in the factor/birth colors; everything lies within the view radius; the node
     label lists the factors (or the prime).
  I. CLI: the sphere's arguments exist with their defaults; prepare_launch maps them (the
     portal folder gives the archive storage); validate_arguments rejects bad values.
  J. Home returns to the launch N at sub-step 0; R gives N = 1, sub-step 0, the start view.
  K. Playback step (--sphere-step): "n" (default) plays N by 1; "p" plays from stored prime
     to stored prime -- the sub-steps glide the points over the whole gap (the phase of ring
     p runs from N to the next prime), the HUD shows N -> next prime, the view turns spin
     degrees per step; at the storage's last prime playback stops; without a storage "p"
     plays by 1.

Usage:
    python unitTests/test_sphere_mode.py
"""
import argparse
import bisect
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


def _sieve(limit):
    flags = bytearray([1]) * (limit + 1)
    flags[0:2] = b"\x00\x00"
    for i in range(2, int(limit ** 0.5) + 1):
        if flags[i]:
            flags[i * i::i] = bytearray(len(flags[i * i::i]))
    return [i for i in range(limit + 1) if flags[i]]


STORED = _sieve(5000)


class FakeStorage:
    def __init__(self, primes):
        self.primes = list(primes)

    def forward(self, after_n, count):
        i = bisect.bisect_right(self.primes, after_n)
        return self.primes[i:i + count]

    def backward(self, before_n, count):
        i = bisect.bisect_left(self.primes, before_n)
        return self.primes[max(0, i - count):i]


def _make_session(n=100, viz_mode="sphere", storage="fake", **overrides):
    from primeatlas.visualization.shared.session import RenderSession
    config = dict(sphere_rings=25, sphere_frames=4, sphere_chunk=200, sphere_spin=0.4, sphere_segments=24)
    if storage == "fake":
        config["sphere_storage"] = FakeStorage(STORED)
    config.update(overrides)
    return RenderSession(
        primes=np.empty(0, dtype=np.int64), n=n, ceiling=-1, range_mode=False, range_primes=None,
        range_step=1, max_radius=450.0, tempo_ms=60, buffer_margin=1000, can_extend_buffer=False,
        portal_folder=None, viz_mode=viz_mode, **config,
    )


def section_a_registration():
    print("\n--- A: registration ---")
    from primeatlas.visualization.mode_registry import MODES
    check("sphere" in MODES, "sphere is a registered viz-mode")
    s = _make_session()
    normal, hit, count, count_hit = s.rebuild(s.n)
    check(count == 0 and count_hit == 0 and len(normal) == 0, "ring buffers stay empty")
    check(s.mode.marker_data() is not None and len(s.mode.marker_data()) > 0, "draws markers")
    check(s.mode.segment_data() is not None and len(s.mode.segment_data()) > 0, "draws segments")
    check(not s.mode.draws_center_marker and not s.mode.uses_prime_ceiling, "no center marker, no ceiling")
    check(s.mode.count_label == "rings", "count label rings")
    check(s.toggle_space() is None and s.playback_running, "Space starts without loaded primes")


def section_b_rings():
    print("\n--- B: rings ---")
    s = _make_session(n=10)
    check(list(s.mode.rings) == STORED[:25], "the first K primes")
    s.rebuild(10)
    check(s.hud_count == 4, f"rings 2,3,5,7 take part at N=10 (got {s.hud_count})")
    s.rebuild(1000)
    check(s.hud_count == 25, f"all 25 at N=1000 (got {s.hud_count})")


def section_c_playback():
    print("\n--- C: playback ---")
    s = _make_session(n=100)
    s.rebuild(s.n)
    yaw0 = s.mode.yaw
    s.n_force_rebuild = False
    stopped = s.tick()
    check(not stopped and s.n == 100 and s.mode.sub == 1 and s.n_force_rebuild, "a tick is one sub-step")
    check(abs(s.mode.yaw - yaw0 - 0.1) < 1e-9, f"spin/frames per tick (got {s.mode.yaw - yaw0})")
    for _ in range(3):
        s.tick()
    check(s.n == 101 and s.mode.sub == 0, f"after frames ticks N+1, sub 0 (got {s.n}, {s.mode.sub})")
    end = _make_session(n=STORED[-1])
    end.playback_running = True
    results = [end.tick() for _ in range(4)]
    check(results[-1] is True and not end.playback_running and end.n == STORED[-1],
          f"stops before passing the storage's last prime (got {results}, n={end.n})")
    free = _make_session(n=10 ** 6, storage=None)
    free.playback_running = True
    results = [free.tick() for _ in range(8)]
    check(all(r is False for r in results) and free.n == 10 ** 6 + 2,
          f"without storage it never stops (got {results}, n={free.n})")


def section_d_stepping():
    print("\n--- D: stepping ---")
    s = _make_session(n=100)
    s.mode.sub = 2
    s.scrub_advance(True, False, True)
    check(s.n == 101 and s.mode.sub == 0, f"Right: +1 at sub 0 (got {s.n})")
    s.scrub_advance(True, False, True)
    check(s.n == 102, f"Right: +1 again, not the next prime (got {s.n})")
    s.scrub_advance(True, True, True)
    check(s.n == 103, f"Ctrl+Right: next prime (got {s.n})")
    s.scrub_advance(True, True, True)
    check(s.n == 107, f"Ctrl+Right: next prime again (got {s.n})")
    s.mode.sub = 1
    s.scrub_advance(False, True, True)
    check(s.n == 103 and s.mode.sub == 0, f"Ctrl+Left: previous prime (got {s.n})")
    s.scrub_advance(False, False, True)
    check(s.n == 102, f"Left: -1 (got {s.n})")
    s.n = STORED[-1]
    s.scrub_advance(True, True, True)
    check(s.n == STORED[-1], "Ctrl+Right at the storage end stays")
    s.n = 2
    s.scrub_advance(False, True, True)
    check(s.n == 2, "Ctrl+Left at the first prime stays")
    s.n = 1
    s.scrub_advance(False, False, True)
    check(s.n == 1, "Left never below 1")
    free = _make_session(n=50, storage=None)
    free.scrub_advance(True, False, True)
    check(free.n == 51, f"without storage Right is +1 (got {free.n})")
    free.scrub_advance(True, True, True)
    check(free.n == 51, f"without storage Ctrl+Right stays (got {free.n})")
    s = _make_session(n=5)
    s.mode.sub = 3
    s.bump_n(7)
    check(s.n == 12 and s.mode.sub == 0, f"Up: +step, sub reset (got {s.n}, {s.mode.sub})")
    s.bump_n(-100)
    check(s.n == 1, f"never below 1 (got {s.n})")


def section_k_playback_step():
    print("\n--- K: playback step ---")
    from primeatlas.visualization.sphere.sphere_geometry import ring_phases
    s = _make_session(n=89, sphere_step="p", sphere_frames=4)
    s.playback_running = True
    yaw0 = s.mode.yaw
    s.tick()
    check(s.n == 89 and s.mode.sub == 1 and s.mode.target == 97, f"p: gliding toward 97 (got {s.n}, {s.mode.target})")
    s.rebuild(s.n)
    check("89 -> 97" in "\n".join(s.hud_lines), f"HUD N -> next prime (got {s.hud_lines})")
    s.tick()
    s.tick()
    s.rebuild(s.n)
    from primeatlas.visualization.sphere.sphere_geometry import ease
    expected = ring_phases(89, ease(3 / 4) * 8, s.mode.rings[:24])
    check(np.allclose(s.mode._frame[1], expected), "the phase runs over the whole gap")
    s.tick()
    check(s.n == 97 and s.mode.sub == 0, f"after frames ticks N is the next prime (got {s.n})")
    check(abs(s.mode.yaw - yaw0 - 0.4) < 1e-9, f"spin per step (got {s.mode.yaw - yaw0})")
    end = _make_session(n=STORED[-1], sphere_step="p")
    end.playback_running = True
    check(end.tick() is True and not end.playback_running and end.n == STORED[-1],
          "p: stops at the storage's last prime")
    free = _make_session(n=10, storage=None, sphere_step="p", sphere_frames=2)
    free.playback_running = True
    free.tick()
    free.tick()
    check(free.n == 11, f"p without storage plays by 1 (got {free.n})")
    n_mode = _make_session(n=89, sphere_frames=2)
    n_mode.tick()
    n_mode.tick()
    check(n_mode.n == 90, f"n (default) plays by 1 (got {n_mode.n})")


def section_e_drag():
    print("\n--- E: drag ---")
    s = _make_session()
    s.rebuild(s.n)
    yaw, pitch = s.mode.yaw, s.mode.pitch
    hud = s.hud_lines
    s.on_cursor_pos(100, 100)
    s.set_dragging(True)
    s.on_cursor_pos(140, 90)
    check(s.cam_pan == [0.0, 0.0], f"no pan in the sphere (got {s.cam_pan})")
    check(s.mode.yaw != yaw and s.mode.pitch != pitch, "yaw and pitch follow the drag")
    check(s.view_dirty, "the view is marked dirty")
    before = s.mode.segment_data().copy()
    s.mode.reproject()
    check(not np.array_equal(before, s.mode.segment_data()), "reproject rebuilds the draw data")
    check(s.hud_lines is hud, "reproject leaves the HUD as it is")
    s.on_cursor_pos(140, 90 + 100000)
    check(abs(s.mode.pitch) <= 89.0, f"pitch held within +-89 (got {s.mode.pitch})")
    tree = _make_session(viz_mode="tree", storage=None, tree_depth=3)
    tree.on_cursor_pos(0, 0)
    tree.set_dragging(True)
    tree.on_cursor_pos(30, 20)
    check(tree.cam_pan == [30.0, 20.0], f"other modes still pan (got {tree.cam_pan})")


def section_f_highlights():
    print("\n--- F: highlights ---")
    s = _make_session(n=84)
    s.rebuild(84)
    check(s.mode.factors == [2, 3, 7] and not s.mode.birth, f"84: factors 2, 3, 7 (got {s.mode.factors})")
    s.rebuild(89)
    check(s.mode.factors == [89] and s.mode.birth, "89 <= p_K=97: its own ring at the node, a birth")
    s.rebuild(101)
    check(s.mode.factors == [] and s.mode.birth, "101: prime past the rings, birth without a ring")
    s.mode.sub = 2
    s.rebuild(84)
    check(s.mode.factors == [] and not s.mode.birth, "mid-step: no highlights")


def section_g_hud():
    print("\n--- G: HUD ---")
    s = _make_session(n=84)
    s.rebuild(84)
    text = "\n".join(s.hud_lines)
    check("2 · 3 · 7" in text, f"lists the ring factors (got {s.hud_lines})")
    check("2 .. 97" in text, "the rings line names 2 .. p_K")
    check("83" in text and "89" in text, "previous and next stored primes")
    s.rebuild(101)
    check("prime" in "\n".join(s.hud_lines).lower(), "a prime N says so")
    few = _make_session(n=10, sphere_rings=10)
    few.rebuild(31 * 37)
    check("no ring divides" in "\n".join(few.hud_lines).lower(), f"no ring factor is said (got {few.hud_lines})")
    s.rebuild(10007 * 10009)
    check("unknown" in "\n".join(s.hud_lines).lower(), "outside the storage: unknown")
    free = _make_session(n=10, storage=None)
    free.rebuild(13)
    check("unknown" in "\n".join(free.hud_lines).lower(), "without storage: unknown")
    s.mode.sub = 1
    s.rebuild(84)
    check("84 -> 85" in "\n".join(s.hud_lines), f"mid-step N -> N+1 (got {s.hud_lines})")


def section_h_draw():
    print("\n--- H: draw data ---")
    from primeatlas.visualization.sphere.sphere_draw import FACTOR_RGB, BIRTH_RGB
    s = _make_session(n=84, sphere_max_curves=5)
    s.rebuild(84)
    markers = s.mode.marker_data()
    check(len(markers) == 23 + 1, f"a marker per ring taking part (23 primes <= 84) plus the node (got {len(markers)})")
    seg = s.mode.segment_data()
    check(np.any(np.all(np.abs(seg[:, 2:5] - FACTOR_RGB) < 1e-3, axis=1)), "factor rings in the factor color")
    curves = s.mode.draw.curve_primes
    check(curves[:5] == [2, 3, 5, 7, 11] and 7 in curves and len(curves) <= 5 + 3,
          f"5 smallest curves plus the highlighted (got {curves})")
    r = s.max_radius
    xy = np.concatenate([markers[:, :2], seg[:, :2]])
    check(np.all(np.hypot(xy[:, 0], xy[:, 1]) <= r * 1.001), "everything within the view radius")
    labels = s.mode.world_labels()
    check(any("2 · 3 · 7" in lab.text for lab in labels), f"node label lists the factors (got {[l.text for l in labels]})")
    s = _make_session(n=89, sphere_max_curves=0)
    s.rebuild(89)
    check(s.mode.draw.curve_primes == [89], f"cap 0: only the birth ring (got {s.mode.draw.curve_primes})")
    check(np.any(np.all(np.abs(s.mode.segment_data()[:, 2:5] - BIRTH_RGB) < 1e-3, axis=1)),
          "the birth ring in the birth color")


def section_i_cli():
    print("\n--- I: CLI ---")
    from primeatlas.visualization.sphere.sphere_mode import SphereMode
    from primeatlas.visualization.sphere.prime_window import ArchiveStorage
    parser = argparse.ArgumentParser()
    parser.add_argument("--portal-folder", default=None)
    SphereMode.add_arguments(parser)
    args = parser.parse_args([])
    expected = dict(sphere_rings=200, sphere_frames=8, sphere_chunk=100000, sphere_segments=96,
                    sphere_max_curves=1000, sphere_spin=0.4, sphere_point_size=9.0, sphere_node_size=22.0,
                    sphere_label_font_size=35, sphere_step="n")
    got = {k: getattr(args, k) for k in expected}
    check(got == expected, f"defaults (got {got})")
    SphereMode.validate_arguments(parser, args)
    config = SphereMode.prepare_launch(args, None)
    check(all(config[k] == v for k, v in expected.items()), "prepare_launch maps them")
    check(config.get("sphere_storage") is None, "no portal: no storage")
    args = parser.parse_args(["--portal-folder", "X:/portal"])
    config = SphereMode.prepare_launch(args, None)
    check(isinstance(config["sphere_storage"], ArchiveStorage) and config["sphere_storage"].portal_folder == "X:/portal",
          "portal folder: archive storage")

    class _Strict(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError(message)

    strict = _Strict()
    SphereMode.add_arguments(strict)
    for bad in (["--sphere-rings", "0"], ["--sphere-rings", "1000001"], ["--sphere-frames", "0"],
                ["--sphere-chunk", "0"], ["--sphere-segments", "7"], ["--sphere-max-curves", "-1"],
                ["--sphere-point-size", "0"], ["--sphere-node-size", "-2"], ["--sphere-step", "q"]):
        try:
            SphereMode.validate_arguments(strict, strict.parse_args(bad))
            check(False, f"{bad} rejected")
        except ValueError:
            check(True, f"{bad} rejected")


def section_j_home_reset():
    print("\n--- J: home and reset ---")
    s = _make_session(n=300)
    s.scrub_advance(True, True, True)
    s.mode.sub = 2
    s.on_cursor_pos(0, 0)
    s.set_dragging(True)
    s.on_cursor_pos(50, 50)
    s.set_dragging(False)
    s.key("home")
    check(s.n == 300 and s.mode.sub == 0, f"Home: launch N, sub 0 (got {s.n})")
    s.reset()
    check(s.n == 1 and s.mode.sub == 0 and s.viz_mode == "sphere", "R: N = 1, sub 0, stays in the sphere")
    fresh = _make_session(n=300)
    check((s.mode.yaw, s.mode.pitch) == (fresh.mode.yaw, fresh.mode.pitch), "R: the start view")


def main():
    for section in (section_a_registration, section_b_rings, section_c_playback, section_d_stepping,
                    section_e_drag, section_f_highlights, section_g_hud, section_h_draw, section_i_cli,
                    section_j_home_reset, section_k_playback_step):
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
