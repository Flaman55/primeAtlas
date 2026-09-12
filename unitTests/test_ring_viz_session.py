"""
test_ring_viz_session.py -- unit tests for primeatlas/ring_viz/session.py's
RenderSession (Faza 3 of the ring_viz/renderer.py split -- see that
module's own docstring for the full refactor plan and scope boundary).

Deliberately does NOT import moderngl/glfw -- RenderSession has no GL
dependency at all (that's the whole point of Faza 3: design and test this
class in isolation before Faza 4 wires it into the real GLFW/moderngl main
loop) -- so this test runs fine in a headless sandbox with no GPU/display,
same as every other pure-logic test in this package.

Usage (Windows, real Python):
    python unitTests\\test_ring_viz_session.py

Usage (this sandbox, headless):
    python3 unitTests/test_ring_viz_session.py
"""
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


_SMALL_PRIMES = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29], dtype=np.uint64)


def _make_session(**overrides):
    """A RenderSession with sane, small defaults -- every test overrides
    only the fields it actually cares about, matching this file's own
    convention of keeping each test's intent visible at the call site."""
    from primeatlas.ring_viz.session import RenderSession

    kwargs = dict(
        primes=_SMALL_PRIMES,
        n=10,
        ceiling=100,
        range_mode=False,
        range_primes=None,
        range_step=1,
        track_primes=[],
        auto_orbit=True,
        enabled_ids=set(),
        theta=0.5,
        law_mode="stepped",
        max_radius=500.0,
        tempo_ms=120,
        buffer_margin=1000,
        can_extend_buffer=False,
        portal_folder=None,
    )
    kwargs.update(overrides)
    return RenderSession(**kwargs)


def _test_construction_defaults():
    s = _make_session()
    check(s.n == 10 and s.ceiling == 100, "n/ceiling set verbatim from constructor args")
    check(s.tempo_ms == 120, "tempo_ms passed through clamp_tempo_ms unchanged when already in range")
    check(s.playback_running is False, "playback starts stopped")
    check(s.cam_pan == [0.0, 0.0] and s.cam_zoom == 1.0 and s.cam_dragging is False,
          "camera starts centered, unzoomed, not dragging")
    check(s.orbit_index == 0 and s.orbit_counter == 0 and s.orbit_current_prime is None,
          "auto-orbit starts at index 0 with no chosen prime")
    check(s.flash_prime == 0.0 and s.flash_resonance == 0.0, "flash accumulators start at 0")
    check(s.scrub_held == 0 and s.scrub_was_running is False, "scrub bookkeeping starts idle")
    check(s.extend_exhausted is False, "buffer extension starts not-exhausted")
    check(s.hud_n == 10 and s.hud_count == 0 and s.hud_lines == [], "HUD snapshot seeded from launch n, empty otherwise")


def _test_tempo_clamped_at_construction():
    s = _make_session(tempo_ms=5)
    check(s.tempo_ms == 30, f"a too-low launch tempo_ms is clamped to the min (got {s.tempo_ms})")
    s2 = _make_session(tempo_ms=9999)
    check(s2.tempo_ms == 2000, f"a too-high launch tempo_ms is clamped to the max (got {s2.tempo_ms})")


def _test_on_scroll_zoom_to_cursor():
    s = _make_session()
    s.cam_pan[0], s.cam_pan[1] = 100.0, 50.0
    viewport = (800, 600)
    cursor = (400.0, 300.0)  # exactly the viewport center in this call's own math
    old_zoom = s.cam_zoom
    s.on_scroll(dy=1.0, cursor=cursor, viewport=viewport)
    check(s.cam_zoom > old_zoom, f"positive dy zooms in (old={old_zoom}, new={s.cam_zoom})")
    s.on_scroll(dy=-1.0, cursor=cursor, viewport=viewport)
    check(abs(s.cam_zoom - old_zoom) < 1e-9, f"zooming in then out by the same factor returns to the original zoom (got {s.cam_zoom})")


def _test_drag_pans_camera():
    s = _make_session()
    s.on_cursor_pos(100.0, 100.0)  # establishes last_mouse, not dragging yet -- no pan
    check(s.cam_pan == [0.0, 0.0], "cursor move while not dragging does not pan")
    s.set_dragging(True)
    s.on_cursor_pos(130.0, 90.0)
    check(s.cam_pan == [30.0, -10.0], f"dragging pans by the exact cursor delta (got {s.cam_pan})")
    s.set_dragging(False)
    s.on_cursor_pos(500.0, 500.0)
    check(s.cam_pan == [30.0, -10.0], "cursor move after drag ends does not pan further")


def _test_recenter():
    s = _make_session(max_radius=400.0)
    s.cam_pan[0], s.cam_pan[1] = 123.0, 45.0
    s.cam_zoom = 7.0
    s.recenter((1600, 1000))
    check(s.cam_pan == [0.0, 0.0], "recenter zeroes the pan")
    check(s.cam_zoom > 0, f"recenter sets a real positive fit-to-viewport zoom (got {s.cam_zoom})")


def _test_toggle_space_sequential_ceiling_guard():
    s = _make_session(n=99, ceiling=100, range_mode=False)
    msg = s.toggle_space()
    check(msg is None and s.playback_running is True, "starts playback below the ceiling")
    msg2 = s.toggle_space()
    check(msg2 is None and s.playback_running is False, "a second press always stops playback")

    s_at_ceiling = _make_session(n=100, ceiling=100, range_mode=False)
    msg3 = s_at_ceiling.toggle_space()
    check(msg3 is not None and s_at_ceiling.playback_running is False,
          f"refuses to start exactly at the ceiling in sequential mode (got msg={msg3!r})")


def _test_toggle_space_range_mode_always_allowed():
    s = _make_session(n=10**30, ceiling=5, range_mode=True)
    msg = s.toggle_space()
    check(msg is None and s.playback_running is True, "range mode can always start regardless of any ceiling value")


def _test_tempo_faster_slower():
    s = _make_session(tempo_ms=120)
    msg = s.tempo_faster()
    check(s.tempo_ms == 96 and "faster" in msg, f"tempo_faster multiplies by 0.8 (got {s.tempo_ms}, msg={msg!r})")
    s2 = _make_session(tempo_ms=120)
    msg2 = s2.tempo_slower()
    check(s2.tempo_ms == 150 and "slower" in msg2, f"tempo_slower divides by 0.8 (got {s2.tempo_ms}, msg={msg2!r})")


def _test_tick_sequential_stops_at_ceiling():
    s = _make_session(n=99, ceiling=100, range_mode=False, range_step=1)
    s.playback_running = True
    stopped = s.tick()
    check(stopped is False and s.n == 100 and s.n_advancing is True, f"advances by 1 below the ceiling (got n={s.n})")
    stopped2 = s.tick()
    check(stopped2 is True and s.playback_running is False, "stops exactly at the ceiling, playback flips off")


def _test_tick_range_mode_uses_range_step():
    s = _make_session(n=1000, ceiling=5, range_mode=True, range_step=250)
    stopped = s.tick()
    check(stopped is False and s.n == 1250, f"range mode advances by range_step, ignoring ceiling (got n={s.n})")


def _test_bump_n():
    s = _make_session(n=10)
    s.bump_n(5)
    check(s.n == 15, f"positive bump adds delta (got {s.n})")
    s.bump_n(-100)
    check(s.n == 0, f"bump_n floors at 0, never negative (got {s.n})")
    s2 = _make_session(n=99, ceiling=100)
    s2.bump_n(1000)
    check(s2.n == 1099, "bump_n is deliberately UNCLAMPED at the ceiling (unlike the scrub keys)")


def _test_scrub_pauses_and_resumes_playback():
    s = _make_session(n=50, ceiling=100, range_mode=False)
    s.playback_running = True
    s.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    check(s.playback_running is False and s.scrub_was_running is True,
          "first scrub press while running pauses playback and remembers to resume")
    check(s.n == 51, f"scrub still advances n on the pausing press itself (got {s.n})")
    s.scrub_advance(is_right=True, ctrl_held=True, is_first_press=False)
    check(s.n == 61, f"a repeat (not first press) does not re-trigger the pause bookkeeping, still advances (+10 ctrl) (got {s.n})")
    msg, needs_refresh = s.scrub_release()
    check(msg is None and needs_refresh is True and s.playback_running is True,
          "release (last held key up) resumes playback since it was running before the scrub")


def _test_scrub_while_stopped_never_autostarts():
    s = _make_session(n=50, ceiling=100, range_mode=False)
    s.playback_running = False
    s.scrub_advance(is_right=False, ctrl_held=False, is_first_press=True)
    check(s.playback_running is False and s.scrub_was_running is False,
          "scrubbing while already stopped never marks was_running")
    msg, needs_refresh = s.scrub_release()
    check(msg is None and needs_refresh is False and s.playback_running is False,
          "release after a stopped-state scrub does nothing (no message, no refresh, still stopped)")


def _test_scrub_release_refuses_at_ceiling():
    s = _make_session(n=100, ceiling=100, range_mode=False)
    s.playback_running = True
    s.scrub_held = 0
    s.scrub_was_running = False
    s.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)
    check(s.n == 100, f"clamp_scrub_n caps the scrub at the ceiling (got {s.n})")
    msg, needs_refresh = s.scrub_release()
    check(msg is not None and needs_refresh is True and s.playback_running is False,
          f"release right at the ceiling refuses to resume, with an explanatory message (got msg={msg!r})")


def _test_scrub_multi_key_hold_needs_both_released():
    s = _make_session(n=50, ceiling=100)
    s.playback_running = True
    s.scrub_advance(is_right=True, ctrl_held=False, is_first_press=True)   # RIGHT down
    s.scrub_advance(is_right=False, ctrl_held=False, is_first_press=True)  # LEFT down too
    check(s.scrub_held == 2, f"both held keys are counted together (got {s.scrub_held})")
    msg1, needs_refresh1 = s.scrub_release()  # one released
    check(needs_refresh1 is False and s.playback_running is False,
          "releasing only ONE of two held scrub keys does not resume playback yet")
    msg2, needs_refresh2 = s.scrub_release()  # the other released
    check(needs_refresh2 is True and s.playback_running is True,
          "releasing the LAST held scrub key resumes playback")


def _test_reset():
    s = _make_session(n=500, track_primes=[2, 3, 5], auto_orbit=False, range_mode=True)
    s.playback_running = True
    s.orbit_index, s.orbit_counter, s.orbit_current_prime = 3, 7, 29
    s.reset()
    check(s.playback_running is False, "reset stops playback")
    check(s.track_primes == [], "reset clears Track P")
    check(s.auto_orbit is True, "reset re-enables auto-orbit")
    check(s.range_mode is False, "reset drops back to sequential mode even if range mode was active")
    check((s.orbit_index, s.orbit_counter, s.orbit_current_prime) == (0, 0, None), "reset clears auto-orbit cycling state")
    check(s.n == 1, f"reset lands N on 1 (got {s.n})")
    check(s.n_force_rebuild is True, "reset forces a rebuild even if N was already 1")


def _test_extend_buffer_if_needed():
    import primeatlas.ring_viz.session as session_module

    original_loader = session_module.load_magazyn
    calls = []

    def fake_loader(portal_folder, new_ceiling, from_n=None):
        calls.append((portal_folder, new_ceiling, from_n))
        return np.array([31, 37, 41], dtype=np.uint64)

    session_module.load_magazyn = fake_loader
    try:
        s = _make_session(n=95, ceiling=100, buffer_margin=10, can_extend_buffer=True, portal_folder="FAKE")
        msg = s.extend_buffer_if_needed()
        check(msg is not None and "loaded 3 more primes" in msg, f"extends when within margin of the ceiling (got {msg!r})")
        check(s.ceiling == 110, f"ceiling advances by exactly one margin's worth (got {s.ceiling})")
        check(list(s.primes[-3:]) == [31, 37, 41], "new primes are appended to the loaded array")
        check(calls == [("FAKE", 100 + 10, 100)], f"loader called with (portal_folder, new_ceiling, from_n=old_ceiling) (got {calls!r})")

        s_far = _make_session(n=10, ceiling=100, buffer_margin=10, can_extend_buffer=True, portal_folder="FAKE")
        msg_far = s_far.extend_buffer_if_needed()
        check(msg_far is None, "does nothing when N is nowhere near the ceiling yet")

        s_disabled = _make_session(n=95, ceiling=100, buffer_margin=10, can_extend_buffer=False, portal_folder=None)
        msg_disabled = s_disabled.extend_buffer_if_needed()
        check(msg_disabled is None, "does nothing at all when the data source can't be extended (synthetic/sieve)")
    finally:
        session_module.load_magazyn = original_loader


def _test_extend_buffer_exhaustion_sticks():
    import primeatlas.ring_viz.session as session_module

    original_loader = session_module.load_magazyn
    call_count = [0]

    def empty_loader(portal_folder, new_ceiling, from_n=None):
        call_count[0] += 1
        return np.empty(0, dtype=np.uint64)

    session_module.load_magazyn = empty_loader
    try:
        s = _make_session(n=95, ceiling=100, buffer_margin=10, can_extend_buffer=True, portal_folder="FAKE")
        msg = s.extend_buffer_if_needed()
        check(s.extend_exhausted is True and msg is not None, "an empty extension result flips exhausted=True")
        s.extend_buffer_if_needed()
        s.extend_buffer_if_needed()
        check(call_count[0] == 1, f"once exhausted, no further load attempts are made (got {call_count[0]} calls)")
    finally:
        session_module.load_magazyn = original_loader


def _test_rebuild_basic():
    s = _make_session(n=10)
    data_normal, data_hit, count, count_hit = s.rebuild(10)
    check(count == 4, f"4 primes <= 10 are active (2,3,5,7) (got {count})")
    check(count_hit == 2, f"2 of them divide 10 (2 and 5) (got {count_hit})")
    check(data_normal.shape[0] + data_hit.shape[0] == count, "normal+hit rows add up to the total count")
    check(s.hud_n == 10 and s.hud_count == 4, f"HUD snapshot updated to match (got n={s.hud_n}, count={s.hud_count})")
    check(len(s.hud_lines) >= 1, "hud_lines is populated (at least the Factors-of-N line)")


def _test_rebuild_prime_flash_on_ring_count_increase():
    s = _make_session(n=6)
    _, _, count6, _ = s.rebuild(6)
    check(s.flash_prime == 0.0, "no prev_ring_count given -> no birth flash on the very first rebuild")
    check(count6 == 3, f"sanity: primes <=6 are {{2,3,5}} (got {count6})")

    s2 = _make_session(n=10)
    _, _, count10, _ = s2.rebuild(10)
    _, _, count11, _ = s2.rebuild(11, prev_ring_count=count10)
    check(count11 > count10, f"sanity: crossing prime 11 increases the active count ({count10} -> {count11})")
    check(s2.flash_prime == 1.0, "ring count increasing triggers the prime-birth flash")

    s3 = _make_session(n=10)
    _, _, count10b, _ = s3.rebuild(10)
    _, _, count10c, _ = s3.rebuild(10, prev_ring_count=count10b)
    check(count10c == count10b and s3.flash_prime == 0.0,
          "re-rebuilding at the SAME N (no new prime crossed) does not trigger the birth flash")


def _test_rebuild_resonance_flash_when_all_hit():
    s = _make_session(primes=np.array([2, 3], dtype=np.uint64), n=6)
    s.rebuild(6)
    check(s.flash_resonance == 1.0, "N=6 is divisible by both active primes (2 and 3) -> resonance flash triggers")

    s2 = _make_session(primes=np.array([2, 3], dtype=np.uint64), n=7)
    s2.rebuild(7)
    check(s2.flash_resonance == 0.0, "N=7 divides neither active prime -> no resonance flash")


def _test_flash_color_and_decay():
    s = _make_session()
    check(s.resonance_flash_color() is None, "no color while flash_resonance is 0")
    check(s.prime_flash_color() is None, "no color while flash_prime is 0")
    s.flash_resonance = 1.0
    s.flash_prime = 1.0
    rc = s.resonance_flash_color()
    pc = s.prime_flash_color()
    check(rc is not None and len(rc) == 4, f"resonance flash color is an (r,g,b,a) tuple (got {rc!r})")
    check(pc is not None and len(pc) == 4, f"prime flash color is an (r,g,b,a) tuple (got {pc!r})")
    s.decay_resonance_flash()
    s.decay_prime_flash()
    check(0.0 < s.flash_resonance < 1.0, f"resonance flash decayed toward 0 but not yet there (got {s.flash_resonance})")
    check(0.0 < s.flash_prime < 1.0, f"prime flash decayed toward 0 but not yet there (got {s.flash_prime})")


def _test_refresh_hud_json_line():
    import json as _json
    s = _make_session(n=42)
    s.hud_count = 7
    s.hud_lines = ["Factors of N: 2, 3"]
    s.playback_running = True
    line, rgba, w, h = s.refresh_hud(hud_font_size=20)
    check(line.startswith("HUD_STATE:"), f"refresh_hud's json_line carries the same prefix emit_hud_state used (got {line[:20]!r})")
    payload = _json.loads(line[len("HUD_STATE:"):])
    check(payload["n"] == 42 and payload["count"] == 7 and payload["running"] is True,
          f"payload reflects the session's current hud/playback fields (got {payload!r})")
    check((rgba is None) == (w == 0 == h), "rgba is None exactly when width/height are both 0 (Pillow unavailable or nothing to draw)")


def main():
    _test_construction_defaults()
    _test_tempo_clamped_at_construction()
    _test_on_scroll_zoom_to_cursor()
    _test_drag_pans_camera()
    _test_recenter()
    _test_toggle_space_sequential_ceiling_guard()
    _test_toggle_space_range_mode_always_allowed()
    _test_tempo_faster_slower()
    _test_tick_sequential_stops_at_ceiling()
    _test_tick_range_mode_uses_range_step()
    _test_bump_n()
    _test_scrub_pauses_and_resumes_playback()
    _test_scrub_while_stopped_never_autostarts()
    _test_scrub_release_refuses_at_ceiling()
    _test_scrub_multi_key_hold_needs_both_released()
    _test_reset()
    _test_extend_buffer_if_needed()
    _test_extend_buffer_exhaustion_sticks()
    _test_rebuild_basic()
    _test_rebuild_prime_flash_on_ring_count_increase()
    _test_rebuild_resonance_flash_when_all_hit()
    _test_flash_color_and_decay()
    _test_refresh_hud_json_line()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
