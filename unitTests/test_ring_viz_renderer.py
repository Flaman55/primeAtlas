"""
test_ring_viz_renderer.py -- the ring renderer's playback and HUD text: tempo and scrub
clamping, buffer extension, playback ticks and auto orbit (playback.py,
ring_playback.py), the resonance log update, HUD text composition, colors and
rasterizing (hud_text.py), and primeatlas/visualization/shared/renderer.py running as
a plain script with the tree-drawing source. Storage reads are in
test_ring_viz_sources.py, drawing math in test_ring_viz_draw.py.

Deliberately does NOT import moderngl/glfw (renderer.py only imports those inside
run(), which this test never calls).

Usage: python unitTests\\test_ring_viz_renderer.py
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


def _test_clamp_tempo_ms():
    from primeatlas.visualization.shared.playback import (
        clamp_tempo_ms, _TEMPO_MS_DEFAULT, _TEMPO_MS_MIN, _TEMPO_MS_MAX,
    )

    check(clamp_tempo_ms(120) == 120, "a value already inside [30,2000] passes through unchanged")
    check(clamp_tempo_ms(5) == _TEMPO_MS_MIN, f"a too-low value clamps up to the min ({_TEMPO_MS_MIN})")
    check(clamp_tempo_ms(9999) == _TEMPO_MS_MAX, f"a too-high value clamps down to the max ({_TEMPO_MS_MAX})")
    check(clamp_tempo_ms(30) == 30, "the min boundary itself is accepted as-is")
    check(clamp_tempo_ms(2000) == 2000, "the max boundary itself is accepted as-is")
    check(clamp_tempo_ms(None) == _TEMPO_MS_DEFAULT, f"a missing value falls back to the JS's own default ({_TEMPO_MS_DEFAULT})")


def _test_arrow_scrub_delta():
    """arrow_scrub_delta() is the pure delta computation behind the
    LEFT/RIGHT scrub keys (step by 1, or by 10 with Ctrl held) -- the
    pause/resume state machine around it (scrub_state's held-count
    bookkeeping in run()) is plain closure state, not extracted, same as
    on_mouse_button's own state["dragging"]."""
    from primeatlas.visualization.shared.playback import arrow_scrub_delta

    check(arrow_scrub_delta(is_right=True, ctrl_held=False) == 1,
          "RIGHT without Ctrl steps by +1")
    check(arrow_scrub_delta(is_right=False, ctrl_held=False) == -1,
          "LEFT without Ctrl steps by -1")
    check(arrow_scrub_delta(is_right=True, ctrl_held=True) == 10,
          "RIGHT with Ctrl held steps by +10")
    check(arrow_scrub_delta(is_right=False, ctrl_held=True) == -10,
          "LEFT with Ctrl held steps by -10")


def _test_clamp_scrub_n():
    """clamp_scrub_n() is the guard that stops the LEFT/RIGHT scrub keys'
    OS key-repeat from running N so far past the loaded ceiling that
    can_start_playback() could never resume afterward (without this guard,
    scrubbing past the ceiling left playback permanently stuck with no way
    to resume short of a full reset)."""
    from primeatlas.visualization.shared.playback import clamp_scrub_n, can_start_playback

    check(clamp_scrub_n(50, range_mode=False, ceiling=100) == 50,
          "a value already well within bounds passes through unchanged")
    check(clamp_scrub_n(-5, range_mode=False, ceiling=100) == 0,
          "never goes negative, same floor as Up/Down/PageUp/PageDown")
    check(clamp_scrub_n(9999, range_mode=False, ceiling=100) == 100,
          "sequential mode: a huge overshoot (many rapid key-repeat deltas) clamps to the ceiling exactly")
    check(clamp_scrub_n(100, range_mode=False, ceiling=100) == 100,
          "landing exactly on the ceiling is left as-is (the same terminal state real forward playback reaches on its own)")
    check(clamp_scrub_n(9999, range_mode=True, ceiling=100) == 9999,
          "range mode has no ceiling at all -- an equally large value is NOT clamped")

    # The actual bug this fixes, end to end: an unclamped overshoot would
    # leave N somewhere can_start_playback() refuses to resume from; the
    # clamped value must always stay resumable's own upper bound (n <
    # ceiling) OR sit exactly at the expected "nothing left" edge -- never
    # further out where even a full reset-free recovery would be unclear.
    clamped = clamp_scrub_n(50_000, range_mode=False, ceiling=100)
    check(clamped == 100,
          f"clamped result never exceeds the ceiling, regardless of how large the raw overshoot was (got {clamped})")


def _test_should_extend_buffer():
    """should_extend_buffer is the trigger condition for
    extend_buffer_if_needed's own real (disk-hitting) extension call --
    covers the lookahead-margin threshold itself, the range_mode/source
    bypasses, and the strict-inequality boundary that stops a runaway
    re-extend-every-frame loop right after a successful extension (see
    that function's own doc-comment for why `>` and not `>=`)."""
    from primeatlas.visualization.shared.playback import should_extend_buffer

    check(should_extend_buffer(n=50, ceiling=1000, margin=100, range_mode=False, can_extend_source=True) is False,
          "far from the ceiling (n well below ceiling-margin): no extension needed yet")
    check(should_extend_buffer(n=901, ceiling=1000, margin=100, range_mode=False, can_extend_source=True) is True,
          "n has closed to within margin of the ceiling: extend now")
    check(should_extend_buffer(n=900, ceiling=1000, margin=100, range_mode=False, can_extend_source=True) is False,
          "n exactly AT ceiling-margin does not yet trigger (strict > only) -- "
          "this is the boundary that prevents re-triggering the very frame "
          "after a fresh extension lands exactly here")
    check(should_extend_buffer(n=999, ceiling=1000, margin=100, range_mode=True, can_extend_source=True) is False,
          "range mode never extends -- it has no ceiling concept at all")
    check(should_extend_buffer(n=999, ceiling=1000, margin=100, range_mode=False, can_extend_source=False) is False,
          "a data source that can't be extended (synthetic/sieve) never extends, no matter how close n is")
    check(should_extend_buffer(n=999, ceiling=1000, margin=0, range_mode=False, can_extend_source=True) is False,
          "a zero margin never triggers (nothing to look ahead by)")


def _test_next_buffer_ceiling():
    """Each extension advances the ceiling by exactly one more margin's
    worth, reusing the SAME margin figure every time (not a
    growing/shrinking one) -- see extend_buffer_if_needed's own call site
    for where that reused figure (buffer_margin) actually comes from. This
    is what lets the buffer keep traveling ahead of n indefinitely, as long
    as the underlying source (archive) can still supply data, instead of
    ever hitting a hard wall."""
    from primeatlas.visualization.shared.playback import next_buffer_ceiling

    check(next_buffer_ceiling(1000, 100) == 1100, "advances by exactly one margin's worth")
    check(next_buffer_ceiling(next_buffer_ceiling(1000, 100), 100) == 1200,
          "repeated extensions keep advancing by the SAME margin each time, not a growing one")


def _test_can_start_playback():
    from primeatlas.visualization.shared.playback import can_start_playback

    check(can_start_playback(n=50, range_mode=False, ceiling=100) is True,
          "sequential mode below the ceiling can start")
    check(can_start_playback(n=100, range_mode=False, ceiling=100) is False,
          "sequential mode already AT the ceiling refuses to start (ports #toggleRunning's own guard)")
    check(can_start_playback(n=150, range_mode=False, ceiling=100) is False,
          "sequential mode past the ceiling (shouldn't normally happen, but) also refuses")
    check(can_start_playback(n=0, range_mode=True, ceiling=100) is True,
          "range mode has no ceiling concept -- always allowed to start")
    check(can_start_playback(n=100, range_mode=True, ceiling=100) is True,
          "range mode still allowed to start even at a value equal to some unrelated ceiling")


def _test_tick_next_n():
    from primeatlas.visualization.shared.playback import tick_next_n

    new_n, stop = tick_next_n(n=50, range_mode=False, ceiling=100)
    check((new_n, stop) == (51, False), f"sequential mode below ceiling advances by exactly 1 (got {(new_n, stop)!r})")

    new_n, stop = tick_next_n(n=100, range_mode=False, ceiling=100)
    check((new_n, stop) == (100, True), f"sequential mode AT the ceiling stops instead of advancing (got {(new_n, stop)!r})")

    new_n, stop = tick_next_n(n=150, range_mode=False, ceiling=100)
    check((new_n, stop) == (150, True), f"sequential mode past the ceiling also stops (got {(new_n, stop)!r})")

    new_n, stop = tick_next_n(n=999, range_mode=True, ceiling=100)
    check((new_n, stop) == (1000, False), f"range mode ignores the ceiling entirely and always advances (got {(new_n, stop)!r})")

    # range_step -- omitted (default 1) reproduces the exact old behavior;
    # a real value is range mode's own per-tick step, but NEVER affects
    # sequential mode regardless. Needed for playback at real
    # archive-floor-scale ranges (~10**25), where stepping by 1 makes
    # playback appear frozen.
    new_n, stop = tick_next_n(n=999, range_mode=True, ceiling=100, range_step=1)
    check((new_n, stop) == (1000, False),
          f"range_step=1 (explicit) reproduces the default/omitted behavior exactly (got {(new_n, stop)!r})")
    new_n, stop = tick_next_n(n=0, range_mode=True, ceiling=100, range_step=1234)
    check((new_n, stop) == (1234, False),
          f"range mode advances by range_step when given, not a fixed +1 (got {(new_n, stop)!r})")
    new_n, stop = tick_next_n(n=50, range_mode=False, ceiling=100, range_step=1234)
    check((new_n, stop) == (51, False),
          f"sequential mode ignores range_step entirely, still advances by exactly 1 (got {(new_n, stop)!r})")
    new_n, stop = tick_next_n(n=100, range_mode=False, ceiling=100, range_step=1234)
    check((new_n, stop) == (100, True),
          f"sequential mode at the ceiling still stops regardless of range_step (got {(new_n, stop)!r})")


def _test_advance_auto_orbit():
    from primeatlas.visualization.rings.ring.ring_playback import advance_auto_orbit

    active = np.array([2, 3, 5, 7, 11], dtype=np.int64)

    # A single active prime is a no-op (mirrors the JS's own early-return guard).
    idx, cnt, chosen = advance_auto_orbit(np.array([2], dtype=np.int64), index=0, counter=0)
    check((idx, cnt, chosen) == (0, 0, None), f"len<=1 is a no-op (got {(idx, cnt, chosen)!r})")

    # gap(2->3) == 1, so the very first tick already crosses it.
    idx, cnt, chosen = advance_auto_orbit(active, index=0, counter=0)
    check((idx, cnt, chosen) == (1, 0, 3),
          f"gap of 1 (3-2) advances on the very first tick, landing on index 1/prime 3 (got {(idx, cnt, chosen)!r})")

    # gap(3->5) == 2: one tick short of crossing (counter goes 0->1, no advance yet).
    idx, cnt, chosen = advance_auto_orbit(active, index=1, counter=0)
    check((idx, cnt, chosen) == (1, 1, None),
          f"gap of 2 (5-3) does not advance after only 1 tick (got {(idx, cnt, chosen)!r})")
    # ...and the second tick crosses it.
    idx, cnt, chosen = advance_auto_orbit(active, index=1, counter=1)
    check((idx, cnt, chosen) == (2, 0, 5),
          f"gap of 2 (5-3) advances on the 2nd tick, landing on index 2/prime 5 (got {(idx, cnt, chosen)!r})")

    # Wrapping past the last index uses the fixed gap of 10 (ports the JS's
    # own `nextIndex === 0 ? 10 : ...` line).
    idx, cnt, chosen = advance_auto_orbit(active, index=4, counter=8)
    check((idx, cnt, chosen) == (4, 9, None),
          f"wrap-around gap of 10 does not advance after only 9 ticks (got {(idx, cnt, chosen)!r})")
    idx, cnt, chosen = advance_auto_orbit(active, index=4, counter=9)
    check((idx, cnt, chosen) == (0, 0, 2),
          f"wrap-around gap of 10 advances on the 10th tick, landing back on index 0/prime 2 (got {(idx, cnt, chosen)!r})")


def _test_update_resonance_log():
    from primeatlas.visualization.rings.ring.ring_playback import update_resonance_log
    from primeatlas.visualization.rings.ring.ring_resonance import resonance_log_lines

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47], dtype=np.int64)

    # First call ever (last_n is None) is always a jump: full backfill from
    # from_n=1 (sequential mode).
    state = {"lines": [], "last_n": None, "last_range_mode": None}
    active = primes[primes <= 30]
    update_resonance_log(state, active, n_value=30, range_mode=False, advancing=False)
    expected = resonance_log_lines(active, 1, 30)
    check(state["lines"] == expected,
          f"first-ever call backfills the full [1, n] range (sequential mode) (got {state['lines']!r})")
    check(state["last_n"] == 30 and state["last_range_mode"] is False,
          "state's last_n/last_range_mode are updated after the call")

    # A manual jump (advancing=False) forces a fresh full backfill, even if
    # last_n was already set -- e.g. jumping backwards or skipping ahead.
    state = {"lines": ["stale", "data"], "last_n": 10, "last_range_mode": False}
    active = primes[primes <= 30]
    update_resonance_log(state, active, n_value=30, range_mode=False, advancing=False)
    check(state["lines"] == resonance_log_lines(active, 1, 30),
          "a manual jump (advancing=False) REPLACES stale lines with a fresh full backfill, "
          "not an append")

    # A forward tick (advancing=True) does NOT rescan -- it only checks
    # whether the new n_value itself is a resonance step, appending at most
    # one line, never touching earlier entries.
    state = {"lines": ["previous entry"], "last_n": 29, "last_range_mode": False}
    active = primes[primes <= 30]
    update_resonance_log(state, active, n_value=30, range_mode=False, advancing=True)
    tick_addition = resonance_log_lines(active, 30, 30)
    check(state["lines"] == ["previous entry"] + tick_addition,
          f"a forward tick only appends n_value's own resonance line(s) (if any) after existing entries "
          f"(got {state['lines']!r}, expected append of {tick_addition!r})")

    # A tick that produces NO new resonance event leaves the log untouched.
    # (n=8 is confirmed NOT a resonance step for this prime list -- the
    # earlier full-backfill assertion's own printed event list, over
    # [1, 30], never includes 8.)
    state = {"lines": ["kept as-is"], "last_n": 7, "last_range_mode": False}
    active = primes[primes <= 8]
    update_resonance_log(state, active, n_value=8, range_mode=False, advancing=True)
    check(state["lines"] == ["kept as-is"],
          f"a tick landing on a non-resonance n leaves state['lines'] unchanged (got {state['lines']!r})")

    # A tick is never double-appended if called twice with the same n_value
    # (defensive dedupe, mirrors #logResonance's own last-entry check).
    state = {"lines": [], "last_n": 29, "last_range_mode": False}
    active = primes[primes <= 30]
    update_resonance_log(state, active, n_value=30, range_mode=False, advancing=True)
    before = list(state["lines"])
    state["last_n"] = 29  # simulate calling again for the "same" tick
    update_resonance_log(state, active, n_value=30, range_mode=False, advancing=True)
    check(state["lines"] == before,
          "calling update_resonance_log twice for the same n_value tick does not duplicate the entry")

    # A multi-step forward tick (range mode with range_step > 1) must scan
    # the WHOLE skipped span since the last call, not just the new n_value
    # alone -- otherwise a resonance event strictly BETWEEN two (now
    # farther-apart) ticks would silently never get logged at all. Directly
    # tied to tick_next_n's own range_step support (see that function's own
    # doc-comment).
    state = {"lines": [], "last_n": 0, "last_range_mode": True}
    range_step_active = np.array([2, 3, 5, 7], dtype=np.int64)
    update_resonance_log(state, range_step_active, n_value=42, range_mode=True, advancing=True)
    expected_multi_step = resonance_log_lines(range_step_active, 1, 42)
    check(bool(expected_multi_step), "sanity: this span actually contains at least one resonance event")
    check(state["lines"] == expected_multi_step,
          f"a multi-step forward tick (range_step > 1) scans the WHOLE span since the last call "
          f"(from last_n+1, not just n_value) (got {state['lines']!r}, expected {expected_multi_step!r})")

    # A mode switch (sequential -> range) forces a jump even with advancing=True.
    state = {"lines": ["sequential data"], "last_n": 30, "last_range_mode": False}
    range_active = np.array([101, 103, 107], dtype=np.int64)
    update_resonance_log(state, range_active, n_value=2, range_mode=True, advancing=True)
    check(state["lines"] == resonance_log_lines(range_active, 0, 2),
          f"a mode switch forces a full backfill (from_n=0 for range mode) even with advancing=True "
          f"(got {state['lines']!r})")
    check(state["last_range_mode"] is True, "last_range_mode reflects the new mode after the switch")


def _test_compose_hud_canvas_lines():
    from primeatlas.visualization.shared.hud_text import compose_hud_canvas_lines

    lines = compose_hud_canvas_lines(n=1234567, count=42, lines=["Factors of N: 7, 11"],
                                      running=False, tempo_ms=120)
    check(lines[0] == "N = 1,234,567    rings = 42    [Stopped]",
          f"header line formats N/count with thousands separators and 'Stopped' status (got {lines[0]!r})")
    check(lines[1:] == ["Factors of N: 7, 11"],
          f"hud_lines_for_n's own lines pass through verbatim, in order (got {lines[1:]!r})")

    lines = compose_hud_canvas_lines(n=5, count=0, lines=[], running=True, tempo_ms=250)
    check(lines == ["N = 5    rings = 0    [Running (250ms/tick)]"],
          f"running status includes the tempo, empty extra-lines list is fine (got {lines!r})")


def _test_hud_line_colors():
    """hud_line_colors matches lines by their own fixed leading text
    (see _HUD_WINDOW_LINE_PREFIXES), independent of what comes before them
    -- Factors-of-N and Tracked-block lines, and the header line
    compose_hud_canvas_lines prepends, all fall through to the flat
    default _HUD_TEXT_RGB."""
    from primeatlas.visualization.rings.ring.ring_hud import hud_line_colors
    from primeatlas.visualization.shared.hud_text import _HUD_TEXT_RGB
    from primeatlas.visualization.rings.ring.ring_windows import window_label_colors

    window_colors = window_label_colors({"bertrand", "legendre"}, 141)
    lines = [
        "N = 141    rings = 34    [Stopped]",
        "Factors of N: 3, 47",
        "Bertrand window: (70, 141]",
        "Legendre window: k=11  (121, 141]",
    ]
    colors = hud_line_colors(lines, window_colors)
    check(len(colors) == len(lines), "one color per input line, same length")
    check(colors[0] == _HUD_TEXT_RGB, f"the header line gets the flat default color (got {colors[0]!r})")
    check(colors[1] == _HUD_TEXT_RGB, f"a Factors-of-N line gets the flat default color (got {colors[1]!r})")
    check(colors[2] == window_colors["bertrand"],
          f"the Bertrand window line gets Bertrand's own color from window_colors (got {colors[2]!r})")
    check(colors[3] == window_colors["legendre"],
          f"the Legendre window line gets Legendre's own color from window_colors (got {colors[3]!r})")

    # General Law's line has extra parenthesized text before the colon
    # (theta=..., k=... in stepped mode) -- the prefix match must still
    # fire on just "General Law window", not the full literal string.
    gl_colors = window_label_colors({"generalLaw"}, 141, theta=0.5, mode="stepped")
    gl_line = "General Law window (theta=0.5, k=11): (121, 141]"
    check(hud_line_colors([gl_line], gl_colors) == [gl_colors["generalLaw"]],
          "General Law's line matches by its fixed leading text even with extra "
          "parenthesized theta/k detail before the colon")

    # A family present in window_colors but with no matching line at all
    # (e.g. caller passed a stale/mismatched dict) must not crash or leak
    # into an unrelated line -- every line either matches its own family's
    # prefix or falls back to default, nothing else.
    check(hud_line_colors(["Tracked (active): 2, 3"], window_colors) == [_HUD_TEXT_RGB],
          "a Tracked-block line never accidentally matches a window prefix")

    check(hud_line_colors([], window_colors) == [], "empty lines list -> empty colors list")

    # shell_colors param -- at
    # n=141, theta=0.4 (three distinct lo values), the two nested-shell
    # legend lines each get their own averaged color, and a line that
    # DOESN'T match any known family or shell still falls through to the
    # flat default.
    from primeatlas.visualization.rings.ring.ring_windows import nested_shell_colors
    shell_colors = nested_shell_colors({"bertrand", "legendre", "generalLaw"}, 141, theta=0.4, mode="stepped")
    shell_lines = ["Bertrand + Legendre:", "Bertrand + Legendre + General Law:", "Unrelated line"]
    shell_line_colors = hud_line_colors(shell_lines, {}, shell_colors)
    check(shell_line_colors[0] == shell_colors[frozenset(("bertrand", "legendre"))],
          f"'Bertrand + Legendre:' line gets that shell's own averaged color (got {shell_line_colors[0]!r})")
    check(shell_line_colors[1] == shell_colors[frozenset(("bertrand", "legendre", "generalLaw"))],
          f"'Bertrand + Legendre + General Law:' line gets that shell's own averaged color "
          f"(got {shell_line_colors[1]!r})")
    check(shell_line_colors[2] == _HUD_TEXT_RGB,
          f"a line matching no known family or shell falls through to the flat default "
          f"(got {shell_line_colors[2]!r})")

    # shell_colors omitted entirely (None, the default) -> shell lines simply
    # don't match anything, same as an empty dict -- never a crash.
    check(hud_line_colors(["Bertrand + Legendre:"], {}) == [_HUD_TEXT_RGB],
          "omitting shell_colors entirely leaves shell lines at the flat default, no crash")


def _test_hud_quad_vertex_data():
    from primeatlas.visualization.shared.hud_text import hud_quad_vertex_data

    verts = hud_quad_vertex_data(100.0, 50.0, x=10.0, y=20.0)
    check(verts.shape == (6, 4), f"two triangles = 6 vertices, each (pos_x, pos_y, uv_x, uv_y) (got shape {verts.shape})")
    xs, ys = verts[:, 0], verts[:, 1]
    check(xs.min() == 10.0 and xs.max() == 110.0, f"quad spans x in [10, 110] (anchor + width) (got [{xs.min()}, {xs.max()}])")
    check(ys.min() == 20.0 and ys.max() == 70.0, f"quad spans y in [20, 70] (anchor + height) (got [{ys.min()}, {ys.max()}])")
    # Top-left corner (min x, min y) must carry uv (0, 0) -- matches PIL's
    # own top-left-origin image layout, so the rasterized bitmap shows up
    # right-side-up with no manual flip anywhere in the pipeline.
    top_left_rows = verts[(xs == 10.0) & (ys == 20.0)]
    check(bool(np.all(top_left_rows[:, 2:4] == 0.0)), f"top-left corner has uv=(0,0) (got {top_left_rows[:, 2:4].tolist()})")
    bottom_right_rows = verts[(xs == 110.0) & (ys == 70.0)]
    check(bool(np.all(bottom_right_rows[:, 2:4] == 1.0)), f"bottom-right corner has uv=(1,1) (got {bottom_right_rows[:, 2:4].tolist()})")


def _test_rasterize_hud_text():
    from primeatlas.visualization.shared.hud_text import rasterize_hud_text, _PIL_AVAILABLE

    check(rasterize_hud_text([]) is None, "empty line list rasterizes to None (nothing to draw)")

    if not _PIL_AVAILABLE:
        print("skip: Pillow not installed in this environment -- rasterize_hud_text's "
              "real-bitmap behavior is untested here (renderer.py itself degrades "
              "gracefully in this case, see its own _PIL_AVAILABLE guard)")
        return

    rgba = rasterize_hud_text(["N = 100", "Factors of N: 2, 5"])
    check(rgba is not None, "non-empty lines produce a real bitmap")
    check(rgba.ndim == 3 and rgba.shape[2] == 4, f"result is an (H, W, 4) RGBA array (got shape {rgba.shape})")
    check(rgba.dtype == np.uint8, f"result is uint8 (got {rgba.dtype})")
    check(rgba.shape[0] > 0 and rgba.shape[1] > 0, f"non-empty text produces a non-degenerate image (got shape {rgba.shape})")
    # Two lines of text must be taller than a single line of the same text,
    # otherwise the per-line layout loop isn't actually stacking anything.
    one_line = rasterize_hud_text(["N = 100"])
    check(rgba.shape[0] > one_line.shape[0],
          f"two lines are taller than one line ({rgba.shape[0]} vs {one_line.shape[0]})")
    # Some pixel must actually be opaque (alpha > 0) -- otherwise this drew
    # nothing (e.g. a font/color bug silently producing a blank image).
    check(bool((rgba[:, :, 3] > 0).any()), "at least one pixel has non-zero alpha (text was actually drawn)")

    # font_size must actually change the rasterized bitmap size -- this is
    # the whole point of the --hud-font-size CLI param, so a bug here would
    # silently make the new flag a no-op.
    small = rasterize_hud_text(["N = 100"], font_size=10)
    big = rasterize_hud_text(["N = 100"], font_size=40)
    check(big.shape[0] > small.shape[0] and big.shape[1] > small.shape[1],
          f"font_size=40 produces a taller AND wider bitmap than font_size=10 "
          f"(got small={small.shape}, big={big.shape})")

    # line_colors must actually change the rasterized pixel color, not just
    # be accepted and ignored -- render the SAME single line twice with two
    # very different colors and confirm the resulting opaque pixels differ.
    pink = rasterize_hud_text(["Bertrand window: (70, 141]"], line_colors=[(255, 51, 204)])
    green = rasterize_hud_text(["Bertrand window: (70, 141]"], line_colors=[(57, 255, 20)])
    check(pink.shape == green.shape, "line_colors changes pixel color only, not the bitmap's own size")
    pink_opaque = pink[pink[:, :, 3] > 0]
    green_opaque = green[green[:, :, 3] > 0]
    check(len(pink_opaque) > 0 and len(green_opaque) > 0, "sanity: both renders actually drew something")
    check(tuple(pink_opaque[0][:3]) == (255, 51, 204),
          f"an opaque text pixel carries the requested line_colors RGB exactly (got {tuple(pink_opaque[0][:3])!r})")
    check(tuple(green_opaque[0][:3]) == (57, 255, 20),
          f"a different line_colors value produces a different opaque pixel RGB (got {tuple(green_opaque[0][:3])!r})")

    # No line_colors given (None, the default) keeps the flat _HUD_TEXT_RGB
    # for every line.
    from primeatlas.visualization.shared.hud_text import _HUD_TEXT_RGB
    default_rgba = rasterize_hud_text(["N = 100"])
    default_opaque = default_rgba[default_rgba[:, :, 3] > 0]
    check(tuple(default_opaque[0][:3]) == _HUD_TEXT_RGB,
          f"omitting line_colors still renders the old flat _HUD_TEXT_RGB color (got {tuple(default_opaque[0][:3])!r})")


def _test_renderer_runs_as_plain_script():
    """Spec: renderer.py is launched as a plain script path (see its module docstring), so
    its own directory is sys.path[0] in that process -- no module next to it may shadow a
    standard-library module, and every registered mode's arguments must parse. `--help`
    exercises the whole import chain and argparse setup without opening a window."""
    import subprocess
    script = os.path.join(_REPO_ROOT, "primeatlas", "visualization", "shared", "renderer.py")
    proc = subprocess.run([sys.executable, script, "--help"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)
    check(proc.returncode == 0,
          f"renderer.py --help exits 0 when run as a plain script (rc={proc.returncode}, "
          f"stderr tail={proc.stderr[-300:]!r})")
    for flag in ("--viz-mode", "--windows", "--track-primes", "--pattern-seed-k", "--line-axis-curved",
                 "--tree-depth", "--tree-branches", "--tree-highlight"):
        check(flag in proc.stdout, f"renderer.py --help lists {flag}")
    shared_dir = os.path.dirname(script)
    clashes = sorted(f for f in os.listdir(shared_dir)
                     if f.endswith(".py") and f[:-3] in sys.stdlib_module_names)
    check(not clashes, f"no module in visualization/shared/ shadows a stdlib module (got {clashes})")

def _test_source_none_and_tree_drawing_support():
    """Spec: --source none loads no primes (the tree computes everything itself) and opens
    at --upto; the HUD header names what the mode counts; the tree's marker and segment
    shaders exist."""
    import numpy as np
    from primeatlas.visualization.shared.range_data import initial_n_for_source
    from primeatlas.visualization.shared.sources import load_none
    from primeatlas.visualization.shared.hud_text import compose_hud_canvas_lines
    from primeatlas.visualization.shared import shaders
    empty = load_none()
    check(isinstance(empty, np.ndarray) and len(empty) == 0, "load_none returns an empty array")
    check(initial_n_for_source("none", 12345, empty) == 12345, "--source none opens at --upto")
    header = compose_hud_canvas_lines(5, 28, [], False, 120, count_label="nodes")[0]
    check("nodes = 28" in header, f"the HUD header uses the mode's count label (got {header!r})")
    header = compose_hud_canvas_lines(5, 28, [], False, 120)[0]
    check("rings = 28" in header, f"the default count label stays 'rings' (got {header!r})")
    check("gl_PointCoord" in shaders.MARKER_FRAGMENT_SHADER and "in_size" in shaders.MARKER_VERTEX_SHADER,
          "the striped-marker shader pair exists")
    check("in_color" in shaders.SEGMENT_VERTEX_SHADER, "the world-space segment shader exists")


def main():
    _test_clamp_tempo_ms()
    _test_arrow_scrub_delta()
    _test_clamp_scrub_n()
    _test_should_extend_buffer()
    _test_next_buffer_ceiling()
    _test_can_start_playback()
    _test_tick_next_n()
    _test_advance_auto_orbit()
    _test_update_resonance_log()
    _test_compose_hud_canvas_lines()
    _test_hud_line_colors()
    _test_hud_quad_vertex_data()
    _test_rasterize_hud_text()
    _test_renderer_runs_as_plain_script()
    _test_source_none_and_tree_drawing_support()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
