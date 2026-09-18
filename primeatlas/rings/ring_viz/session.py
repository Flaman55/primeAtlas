"""
session.py -- RenderSession: the mutable interactive-playback state for
primeatlas/rings/ring_viz/renderer.py's `_run_visualization`, consolidated into
ONE object with methods instead of a dozen separate closures each
capturing its own local dict (`state`, `playback`, `orbit_state`,
`flash_state`, `n_holder`, `resonance_log_state`, `hud_state`,
`scrub_state`, `extend_state`, `cyclic_anchor_state`, plus bare
`track_primes`/`auto_orbit`/`range_mode`/`range_primes`/`range_step`/
`primes`/`ceiling` locals mutated via `nonlocal`). [Faza 3 of the
renderer.py split -- see that file's own module docstring for the overall
refactor plan this continues.]

DELIBERATELY NOT WIRED INTO _run_visualization YET (Faza 4's job): this
class is designed and unit-tested here, in isolation, first -- so a
mistake in its design is caught by these tests before the one part of
renderer.py with zero pre-existing unit test coverage (the GLFW/moderngl
main loop, untestable in a headless sandbox) ever comes to depend on it.
_run_visualization keeps its own current closures/dicts unchanged for now;
Faza 4 is the actual rewire, done key-by-key/closure-by-closure with a
real run against a real archive after each step, per PLAN.md.

Scope boundary: RenderSession owns everything from the point
_run_visualization has ALREADY resolved --source/--load-range into a
concrete `primes` array, an initial `n`, a `ceiling`, and the range-mode
fields -- the launch-time "which loader, what N to open on" sequence
above that point stays a plain linear script in _run_visualization, since
it runs once, top to bottom, with no shared mutable state to untangle.
Everything AFTER that point -- the interactive camera, playback, HUD, and
buffer-extension state that a dozen GLFW callbacks and the main loop all
read and write -- is what actually needed a single owner.

GL boundary: nothing here imports moderngl or glfw, and no method takes a
GL context/window. Every method takes and returns plain data (numpy
arrays, tuples, dicts, strings) -- the four or five lines that are
genuinely GL-bound in the ported originals (ctx.buffer(), ctx.texture(),
vbo.write()) are left for _run_visualization's own Faza-4 call sites to
do with this class's return values, same convention as geometry_draw.py/
hud.py/playback.py. This is what makes every method here unit-testable in
a headless sandbox with no GPU/display, same as those three modules.

Self-contained sys.path bootstrap (mirrors renderer.py's own -- see that
file's module docstring for the full "why plain-script-path" explanation):
needed so the primeatlas.* imports below work whether this module is
imported after renderer.py has already run its own bootstrap, or on its
own (e.g. directly from a test).
"""

import json
import os
import sys
import time

import numpy as np

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # ring_viz/ now lives one directory deeper, under primeatlas/rings/
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_PRIME_SIEVE_DIR = os.path.join(_REPO_ROOT, "prime_sieve")
if _PRIME_SIEVE_DIR not in sys.path:
    sys.path.insert(0, _PRIME_SIEVE_DIR)

from primeatlas.rings.ring_geometry import (
    tracked_resonance_state,
    window_anchor_primes,
    cyclic_window_anchor_at,
    format_log_panel_text,
    window_label_colors,
    pattern_wheel_residues,
    next_wheel_n,
    pattern_positions_and_match,
    DEFAULT_WHEEL_PRIMES,
)
from primeatlas.rings.ring_viz.geometry_draw import (
    build_vertex_data,
    build_line_vertex_data,
    split_hit_normal_vertex_data,
    resolve_effective_track_primes,
    build_tracked_outline_draws,
    decay_flash,
    flash_overlay_rgba,
    _FLASH_RESONANCE_RGB,
    _FLASH_PRIME_RGB,
    _FLASH_PATTERN_RGB,
    resonance_is_active,
    zoom_to_point,
    fit_zoom_for_viewport,
)
from primeatlas.rings.ring_viz.playback import (
    clamp_tempo_ms,
    arrow_scrub_delta,
    can_start_playback,
    clamp_scrub_n,
    should_extend_buffer,
    next_buffer_ceiling,
    tick_next_n,
    update_resonance_log,
    advance_auto_orbit,
)
from primeatlas.rings.ring_viz.hud import (
    hud_lines_for_n,
    compose_hud_canvas_lines,
    hud_line_colors,
    rasterize_hud_text,
    emit_audio_tick,
    pattern_hud_line,
)
from primeatlas.rings.ring_viz.sources import load_archive


class RenderSession:
    """Owns every piece of state _run_visualization's interactive part
    (camera, playback, HUD, buffer-extension, tracked/auto-orbit) reads or
    writes, plus the pure state-transition logic that used to live in that
    function's own closures. See this module's own docstring for the exact
    scope boundary and why nothing here touches GL directly.

    Construct with everything _run_visualization has already resolved by
    the point its own `state = {...}` dict used to begin (see that
    function's own body, right after the --load-range handling block):
    a concrete `primes` array, the initial `n`/`ceiling`, the range-mode
    fields, tracked-primes/auto-orbit, the enabled window families, and
    the launch-time buffer-extension parameters. Every field below has a
    direct 1:1 counterpart in the pre-Faza-3 closures -- see each field's
    own comment for which one."""

    def __init__(self, *, primes, n, ceiling, range_mode, range_primes, range_step,
                 track_primes, auto_orbit, enabled_ids, theta, law_mode, max_radius,
                 tempo_ms, buffer_margin, can_extend_buffer, portal_folder,
                 viz_mode="rings", pattern_offsets=None,
                 pattern_step_mode="manual", pattern_stop_on_match=False):
        # Ring data / sequencing (was: bare `primes`/`ceiling`/`range_mode`/
        # `range_primes`/`range_step` locals in _run_visualization, some
        # mutated via `nonlocal`).
        self.primes = primes
        self.n = n
        self.ceiling = ceiling
        self.range_mode = range_mode
        self.range_primes = range_primes
        self.range_step = range_step

        # Window/tracking launch-time config (was: bare `enabled_ids`/
        # `theta`/`law_mode`/`track_primes`/`auto_orbit` locals).
        self.track_primes = track_primes
        self.auto_orbit = auto_orbit
        self.enabled_ids = enabled_ids
        self.theta = theta
        self.law_mode = law_mode
        self.max_radius = max_radius

        # Playback (was: `tempo_ms` local + `playback = {"running": False}`).
        self.tempo_ms = clamp_tempo_ms(tempo_ms)
        self.playback_running = False

        # Auto-orbit cycling (was: `orbit_state` dict).
        self.orbit_index = 0
        self.orbit_counter = 0
        self.orbit_current_prime = None

        # Cyclic window-anchor freeze/jump state (was: `cyclic_anchor_state`
        # dict, one entry per family -- see cyclic_window_anchor_at's own
        # doc-comment).
        self.cyclic_anchor_state = {}

        # Camera (was: `state` dict -- "pan"/"zoom"/"dragging"/"last_mouse").
        self.cam_pan = [0.0, 0.0]
        self.cam_zoom = 1.0
        self.cam_dragging = False
        self.cam_last_mouse = (0.0, 0.0)

        # Birth/resonance flash decay accumulators + tracked-outline draw
        # list (was: `flash_state` dict + `outline_draws_holder` dict).
        self.flash_prime = 0.0
        self.flash_resonance = 0.0
        self.outline_draws = []

        # "line" viz-mode: k-tuple pattern-slide state (see
        # ring_geometry.py's own "line viz-mode" section and
        # rebuild_line/pattern_flash_color below). `viz_mode` stays
        # "rings" and `pattern_offsets` stays None for every existing
        # caller that never passes these two kwargs, so ring mode's own
        # behavior is completely unchanged.
        self.viz_mode = viz_mode
        self.pattern_offsets = list(pattern_offsets) if pattern_offsets else None
        self.pattern_match = False
        self.pattern_view_mode = None
        self.flash_pattern = 0.0
        # Wheel-skip: which n (mod some small-prime-derived period) can
        # EVER match, computed once up front from the pattern's own
        # offsets -- see pattern_wheel_residues' own doc-comment. Only
        # meaningful (modulus > 1) once a pattern is actually set;
        # scrub_advance/tick fall back to their old plain +1/+step
        # behavior whenever it isn't (modulus is None or 1).
        if self.pattern_offsets:
            self.pattern_wheel_modulus, self.pattern_wheel_residues = pattern_wheel_residues(self.pattern_offsets)
            # Cached ONCE (range_primes is fixed for the life of line mode --
            # there is no buffer-extension concept there, see
            # should_extend_buffer's own range_mode bypass) so both the
            # founding-coincidence patch just below and _pattern_seek's own
            # repeated match checks don't rebuild this from a numpy array
            # on every single candidate.
            self._pattern_primes_set = set(int(v) for v in self.range_primes) if len(self.range_primes) else set()
            # Any real occurrence of this pattern whose OWN anchor value
            # coincides with one of the wheel's own small primes is a
            # "founding coincidence" (pattern_wheel_residues' own
            # doc-comment) -- pure residue arithmetic excludes it
            # (n mod p == 0 looks like "forced composite", even though n
            # itself is prime, not composite), making it UNREACHABLE by
            # scrubbing/seeking otherwise. Two real reports, both
            # 2026-09-18: the launch anchor itself (seed 3 for a {0,2}
            # pattern -- "I can't get back to the value I started from"),
            # and a genuine match buried mid-range (n=11 for a k=5
            # pattern -- silently skipped by --pattern-stop-on-match's own
            # search, which never even considered it a candidate). Patch
            # BOTH kinds back into the residue set -- the launch anchor
            # itself AND any of DEFAULT_WHEEL_PRIMES -- but ONLY once each
            # is VERIFIED as a real match against `_pattern_primes_set`,
            # never trusted unconditionally: renderer.py's own seed-vs-
            # window placement (see its "Pattern seed's own occurrence is
            # outside the loaded window" branch) can hand this class a
            # launch anchor that's just the phase-correct first candidate
            # in an archive-scale window nowhere near the small seed, NOT
            # a guaranteed real occurrence -- forcing an unverified
            # residue in would pollute the wheel with a mostly-composite
            # class for the WHOLE window, not just at the anchor. Doesn't
            # touch the "can never repeat at all" signal (residues == [])
            # -- an entirely dead pattern still correctly has nowhere else
            # to go either way.
            if self.pattern_wheel_modulus > 1 and self.pattern_wheel_residues:
                extra_residues = set()
                for candidate in (self.n, *DEFAULT_WHEEL_PRIMES):
                    if candidate in self._pattern_primes_set and pattern_positions_and_match(
                        candidate, self.pattern_offsets, self._pattern_primes_set
                    )[2]:
                        extra_residues.add(candidate % self.pattern_wheel_modulus)
                missing = extra_residues - set(self.pattern_wheel_residues)
                if missing:
                    self.pattern_wheel_residues = sorted(self.pattern_wheel_residues + list(missing))
        else:
            self.pattern_wheel_modulus, self.pattern_wheel_residues = None, None
            self._pattern_primes_set = None

        # Manual/Auto radio + "MATCH!" checkbox (see _pattern_uses_seek's
        # own doc-comment for the exact combined semantics Artur
        # specified, 2026-09-18): "manual" always takes a single wheel
        # step, showing every candidate whether it's a real match or not
        # ("w trybie manual ... idę kolejno niezaleznie na jaki
        # wyladuje"); "auto" always SEEKS -- for a MATCH! when checked,
        # or specifically for a non-match when unchecked ("po wszystkich
        # poprawnych ma być match! a odznaczone po niepoprawnych").
        self.pattern_step_mode = pattern_step_mode
        self.pattern_stop_on_match = pattern_stop_on_match

        # Resonance log (was: `resonance_log_state` dict).
        self.resonance_log_state = {"lines": [], "last_n": None, "last_range_mode": None}

        # Persistent HUD snapshot (was: `hud_state` dict).
        self.hud_n = n
        self.hud_count = 0
        self.hud_rebuild_ms = 0.0
        self.hud_lines = []

        # N-change bookkeeping the main loop reads every frame (was:
        # `n_holder` dict's own "advancing"/"force_rebuild" fields -- its
        # "n" field is this class's own `self.n` above).
        self.n_advancing = False
        self.n_force_rebuild = False

        # LEFT/RIGHT scrub bookkeeping (was: `scrub_state` dict).
        self.scrub_held = 0
        self.scrub_was_running = False

        # Buffer-extension launch-time parameters + exhaustion flag (was:
        # `buffer_margin`/`can_extend_buffer` locals + `extend_state` dict).
        self.buffer_margin = buffer_margin
        self.can_extend_buffer = can_extend_buffer
        self.portal_folder = portal_folder
        self.extend_exhausted = False

    # ------------------------------------------------------------------
    # Camera -- was on_scroll/on_mouse_button/on_cursor_pos's own closure
    # bodies, with `window`/glfw replaced by an explicit `viewport`/`cursor`
    # the caller reads from glfw itself (see zoom_to_point's own docstring
    # for the effective-pan/state-pan conversion this still does).
    # ------------------------------------------------------------------

    def on_scroll(self, dy, cursor, viewport):
        """One scroll-wheel tick: zoom in (dy>0) or out, anchored on
        `cursor` (screen-space, same convention as zoom_to_point)."""
        factor = 1.1 if dy > 0 else (1 / 1.1)
        width, height = viewport
        old_pan = (self.cam_pan[0] + width / 2, self.cam_pan[1] + height / 2)
        new_zoom, new_pan = zoom_to_point(self.cam_zoom, old_pan, cursor, viewport, factor)
        self.cam_zoom = new_zoom
        self.cam_pan[0] = new_pan[0] - width / 2
        self.cam_pan[1] = new_pan[1] - height / 2

    def set_dragging(self, dragging):
        """Left mouse button down/up -- ports on_mouse_button's own
        `state["dragging"] = action == glfw.PRESS` line."""
        self.cam_dragging = bool(dragging)

    def on_cursor_pos(self, x, y):
        """Mouse moved to (x, y) -- pans the camera by the delta from the
        last known position while `cam_dragging` is True, same as
        on_cursor_pos's own closure body."""
        lx, ly = self.cam_last_mouse
        if self.cam_dragging:
            self.cam_pan[0] += x - lx
            self.cam_pan[1] += y - ly
        self.cam_last_mouse = (x, y)

    def recenter(self, viewport):
        """Snap the camera back to "the whole ring field, centered, filling
        the window" -- ports the middle-click branch of on_mouse_button AND
        the F11 re-fit branch of on_key (both did the exact same three
        assignments; unified here since they were always identical)."""
        width, height = viewport
        self.cam_zoom = fit_zoom_for_viewport(self.max_radius, width, height)
        self.cam_pan[0] = 0.0
        self.cam_pan[1] = 0.0

    # ------------------------------------------------------------------
    # Playback / tempo -- was on_key's own KEY_SPACE/KEY_RIGHT_BRACKET/
    # KEY_LEFT_BRACKET/KEY_MINUS branches, and the main loop's own
    # playback-tick block.
    # ------------------------------------------------------------------

    def toggle_space(self):
        """Ports the KEY_SPACE branch of on_key exactly: STOP always
        succeeds; START is refused (message returned, not printed, so the
        caller decides where it goes) once sequential mode has already
        reached the loaded ceiling. Returns a message string to print, or
        None if nothing needs saying."""
        if self.playback_running:
            self.playback_running = False
            return None
        if can_start_playback(self.n, self.range_mode, self.ceiling):
            self.playback_running = True
            return None
        return "Playback: N is already at the loaded ceiling -- nothing left to advance to"

    def tempo_faster(self):
        """Ports the KEY_RIGHT_BRACKET/KEY_EQUAL branch: multiplies tempo_ms
        by 0.8 (clamped). Returns the confirmation line to print."""
        self.tempo_ms = clamp_tempo_ms(round(self.tempo_ms * 0.8))
        return f"Tempo: {self.tempo_ms}ms/tick (faster)"

    def tempo_slower(self):
        """Ports the KEY_LEFT_BRACKET/KEY_MINUS branch: divides tempo_ms by
        0.8 (clamped). Returns the confirmation line to print."""
        self.tempo_ms = clamp_tempo_ms(round(self.tempo_ms / 0.8))
        return f"Tempo: {self.tempo_ms}ms/tick (slower)"

    def _pattern_window_bounds(self):
        """(lo, hi) the current line-mode pattern's anchor must stay
        inside -- lo is the loaded range's own lower edge, hi is reduced
        by the pattern's diameter so its last member never scrubs past
        the loaded window's upper edge (see clamp_pattern_anchor's own
        doc-comment). None when no pattern is active (ring mode, or line
        mode with no pattern set)."""
        if self.viz_mode == "line" and self.pattern_offsets and len(self.range_primes):
            return int(self.range_primes[0]), int(self.range_primes[-1]) - self.pattern_offsets[-1]
        return None

    def _clamp_pattern_n(self, n):
        """A no-op for every mode/state other than an active line-mode
        pattern, so this is safe to call unconditionally from every
        N-changing method below without altering their existing, tested
        behavior. Used only where a plain step (bump_n, or scrub/tick's
        own fallback when the wheel offers no filtering -- see
        _pattern_wheel_step below) needs the window clamp on its own;
        scrub_advance/tick's main path uses the wheel jump instead, which
        already respects this same window."""
        bounds = self._pattern_window_bounds()
        if bounds is None:
            return n
        lo, hi = bounds
        return max(lo, min(n, hi))

    def _pattern_wheel_step(self, n, is_right):
        """One wheel-aware jump (see ring_geometry.next_wheel_n) toward
        the next position that can EVER match this pattern, skipping
        every n forced composite by small-prime divisibility alone.
        Returns `n` unchanged when there is no further such position --
        the window edge, or (self.pattern_wheel_residues == []) the
        pattern's own wheel proving it can never repeat at all."""
        bounds = self._pattern_window_bounds()
        if bounds is None:
            return n
        lo, hi = bounds
        return next_wheel_n(n, is_right, self.pattern_wheel_modulus, self.pattern_wheel_residues, lo, hi)

    def _has_pattern_wheel(self):
        """Whether scrub_advance/tick should use the wheel-jump path at
        all -- False falls back to their old plain +1/+step behavior,
        which is the correct thing to do both outside line mode/pattern
        and in the rare case the wheel found nothing to filter at all
        (modulus == 1 -- see pattern_wheel_residues' own doc-comment)."""
        return (
            self.viz_mode == "line" and self.pattern_offsets
            and self.pattern_wheel_modulus is not None and self.pattern_wheel_modulus > 1
        )

    #: Safety bound for _pattern_seek's own search loop -- with
    #: next_wheel_n's bisect lookup (O(log residues)) this is generous
    #: overkill against any realistic loaded window, not a real limit;
    #: it only guards a single frame from stalling forever on a pattern
    #: whose desired kind (match, or non-match) never recurs in the
    #: loaded range.
    _PATTERN_SEEK_MAX_STEPS = 50_000

    def _pattern_uses_seek(self):
        """Whether an advance action should keep taking wheel steps (see
        _pattern_seek) instead of a single wheel step -- exactly Artur's
        own 2026-09-18 spec: the Manual/Auto radio (`pattern_step_mode`)
        is the master switch -- "manual" ALWAYS takes a single step,
        showing every wheel candidate in turn regardless of whether it's
        a match or not ("idę kolejno niezaleznie na jaki wyladuje"); only
        "auto" ever seeks. Used identically by scrub_advance, bump_n, and
        tick, so arrows/Up-Down/Space all agree on which regime is
        active."""
        return self.pattern_step_mode == "auto"

    def _pattern_seek(self, n, is_right):
        """Repeats _pattern_wheel_step in one direction until landing on a
        wheel candidate of the kind `self.pattern_stop_on_match` asks
        for -- a genuine MATCH! when the checkbox is checked, or a
        non-match (a real wheel candidate that ISN'T a real occurrence)
        when it's unchecked (both checked via the cached
        `_pattern_primes_set`) -- or there's nowhere further to go
        (window edge, or the wheel proved this pattern can never repeat
        at all). "Auto" mode always seeks one of these two kinds; it
        never takes a bare, unfiltered wheel step -- see
        _pattern_uses_seek's own doc-comment for why "manual" is the only
        mode that does. Returns (final_n, found) -- `found` is False when
        the search gave up at the edge without ever landing on the
        desired kind, same "stuck" signal _pattern_wheel_step's own
        n-unchanged convention gives its callers."""
        current = n
        want_match = self.pattern_stop_on_match
        for _ in range(self._PATTERN_SEEK_MAX_STEPS):
            nxt = self._pattern_wheel_step(current, is_right)
            if nxt == current:
                return current, False
            current = nxt
            is_match = pattern_positions_and_match(current, self.pattern_offsets, self._pattern_primes_set)[2]
            if is_match == want_match:
                return current, True
        return current, False

    def tick(self):
        """One playback tick, called once the main loop's own tempo_ms
        elapsed-time gate fires. In line mode with a meaningful pattern
        wheel, advances straight to the next wheel-compatible n (see
        _pattern_wheel_step) instead of ticking by 1/range_step -- this is
        the whole point of the wheel: skip every n the small-prime
        divisibility check alone already rules out. Otherwise ports
        tick_next_n's call site exactly, same as before. Returns True if
        playback just stopped (N reached the ceiling, the pattern's last
        member reached the loaded window's edge, or the wheel found no
        further compatible position), False if `self.n` advanced (and
        `self.n_advancing` was set for the caller's own N-change/rebuild
        branch to see)."""
        if self._has_pattern_wheel():
            if self._pattern_uses_seek():
                new_n, _found = self._pattern_seek(self.n, True)
            else:
                new_n = self._pattern_wheel_step(self.n, True)
            if new_n == self.n:
                self.playback_running = False
                return True
            self.n = new_n
            self.n_advancing = True
            return False
        new_n, should_stop = tick_next_n(self.n, self.range_mode, self.ceiling, self.range_step)
        if not should_stop:
            clamped = self._clamp_pattern_n(new_n)
            if clamped == self.n:
                should_stop = True
            else:
                new_n = clamped
        if should_stop:
            self.playback_running = False
            return True
        self.n = new_n
        self.n_advancing = True
        return False

    # ------------------------------------------------------------------
    # N navigation -- was on_key's own KEY_UP/DOWN/PAGE_UP/PAGE_DOWN and
    # KEY_LEFT/KEY_RIGHT (scrub) branches, and KEY_R (reset).
    # ------------------------------------------------------------------

    def bump_n(self, delta):
        """Ports the Up/Down/PageUp/PageDown branch: `self.n + delta`,
        floored at 0, UNCLAMPED at the ceiling (deliberately -- see
        clamp_scrub_n's own doc-comment for why only the scrub keys are
        capped, not these).

        In line mode with a meaningful pattern wheel, `delta`'s raw
        magnitude (n_step, 1000 by default) is meaningless once most
        integers can never match at all -- landing on an arbitrary +1000
        offset looks like the wheel jump is "shifted" when it's really
        just a different, wheel-UNAWARE code path. Up/Down/PageUp/
        PageDown jump ONE wheel step instead, in `delta`'s own sign
        direction, so every navigation key in this mode -- not just
        scrub/playback -- only ever lands on a position the pattern could
        actually match (same reasoning as scrub_advance's own wheel
        branch)."""
        if self._has_pattern_wheel():
            if self._pattern_uses_seek():
                self.n, _found = self._pattern_seek(self.n, delta >= 0)
            else:
                self.n = self._pattern_wheel_step(self.n, delta >= 0)
            return
        self.n = max(0, self.n + delta)
        self.n = self._clamp_pattern_n(self.n)

    def scrub_advance(self, is_right, ctrl_held, is_first_press):
        """Ports the LEFT/RIGHT PRESS/REPEAT branch: on the FIRST press of
        a hold-sequence (`is_first_press=True`), pauses playback if it was
        running and remembers to resume it later.

        In line mode with a meaningful pattern wheel, every press/repeat
        jumps straight to the next wheel-compatible n in that direction
        (Ctrl repeats the jump 10 times instead of 1, mirroring
        arrow_scrub_delta's own x10 -- see _pattern_wheel_step), stopping
        early without error if the window edge (or an empty wheel -- the
        pattern can never repeat) is reached partway through. Otherwise,
        moves `self.n` by arrow_scrub_delta's step, clamped to the ceiling
        in sequential mode (clamp_scrub_n) so a long hold can never run N
        so far past it that nothing can resume playback afterward -- same
        as before the wheel existed."""
        if is_first_press:
            if self.scrub_held == 0 and self.playback_running:
                self.scrub_was_running = True
                self.playback_running = False
            self.scrub_held += 1
        if self._has_pattern_wheel():
            if self._pattern_uses_seek():
                self.n, _found = self._pattern_seek(self.n, is_right)
                return
            for _ in range(10 if ctrl_held else 1):
                new_n = self._pattern_wheel_step(self.n, is_right)
                if new_n == self.n:
                    break
                self.n = new_n
            return
        delta = arrow_scrub_delta(is_right, ctrl_held)
        self.n = clamp_scrub_n(self.n + delta, self.range_mode, self.ceiling)
        self.n = self._clamp_pattern_n(self.n)

    def scrub_release(self):
        """Ports the LEFT/RIGHT RELEASE branch: once every held scrub key
        is up again, resumes playback IF it was running before the scrub
        started -- gated through the same can_start_playback guard Space
        uses, so scrubbing to exactly the ceiling correctly refuses to
        resume instead of claiming to run. Returns (message_or_None,
        needs_hud_refresh) -- `needs_hud_refresh` is True exactly when
        playback's running-state actually changed here (mirrors the
        original's unconditional _refresh_hud() call inside that same
        `if` branch -- N itself doesn't change on a release, so the
        caller's own N-change-triggered refresh never fires for this)."""
        self.scrub_held = max(0, self.scrub_held - 1)
        if self.scrub_held == 0 and self.scrub_was_running:
            self.scrub_was_running = False
            if can_start_playback(self.n, self.range_mode, self.ceiling):
                self.playback_running = True
                return None, True
            return "Playback: N is already at the loaded ceiling -- nothing left to advance to", True
        return None, False

    def reset(self):
        """Ports the KEY_R branch exactly: stop playback, N=1, drop Track
        P, re-enable auto-orbit, and fall back to sequential mode even if
        --load-range was active at launch (mirrors the HTML's own
        resetSequential())."""
        self.playback_running = False
        self.track_primes.clear()
        self.auto_orbit = True
        self.range_mode = False
        self.orbit_index = 0
        self.orbit_counter = 0
        self.orbit_current_prime = None
        self.n = 1
        self.n_force_rebuild = True
        self.viz_mode = "rings"
        self.pattern_offsets = None
        self.pattern_match = False
        self.pattern_view_mode = None
        self.pattern_wheel_modulus = None
        self.pattern_wheel_residues = None
        self._pattern_primes_set = None
        self.pattern_step_mode = "manual"
        self.pattern_stop_on_match = False

    # ------------------------------------------------------------------
    # Buffer extension -- was extend_buffer_if_needed's own closure body.
    # ------------------------------------------------------------------

    def extend_buffer_if_needed(self):
        """Ports extend_buffer_if_needed exactly (see that function's own
        pre-Faza-3 doc-comment, preserved on should_extend_buffer/
        next_buffer_ceiling in playback.py, for the full rationale).
        Returns a message string to print, or None if no extension was
        needed/attempted this call."""
        if not self.can_extend_buffer or self.extend_exhausted:
            return None
        if not should_extend_buffer(self.n, self.ceiling, self.buffer_margin, self.range_mode, self.can_extend_buffer):
            return None
        new_ceiling = next_buffer_ceiling(self.ceiling, self.buffer_margin)
        new_primes = load_archive(self.portal_folder, new_ceiling, from_n=self.ceiling)
        if len(new_primes) == 0:
            self.extend_exhausted = True
            return (f"Buffer extend: no more data past {self.ceiling:,} in the archive -- "
                    f"the loaded ceiling is now the real end of stored data")
        self.primes = np.concatenate([self.primes, new_primes])
        self.ceiling = new_ceiling
        return f"Buffer extend: loaded {len(new_primes):,} more primes ahead of N, ceiling now {self.ceiling:,}"

    # ------------------------------------------------------------------
    # Flash overlays -- was the main loop's own two near-identical
    # `if flash_state[...] > 0.0:` blocks, split into "what color right
    # now" (pure) and "advance the decay" (mutates), so the caller can
    # draw between the two the same way the original drew between
    # computing `quad` and reassigning `flash_state[...]`.
    # ------------------------------------------------------------------

    def resonance_flash_color(self):
        """Current resonance-flash overlay (r, g, b, a) in 0..1, or None if
        fully decayed (nothing to draw this frame)."""
        if self.flash_resonance <= 0.0:
            return None
        return flash_overlay_rgba(self.flash_resonance, _FLASH_RESONANCE_RGB)

    def decay_resonance_flash(self):
        self.flash_resonance = decay_flash(self.flash_resonance, 0.65)

    def prime_flash_color(self):
        """Current prime-birth-flash overlay (r, g, b, a) in 0..1, or None
        if fully decayed (nothing to draw this frame)."""
        if self.flash_prime <= 0.0:
            return None
        return flash_overlay_rgba(self.flash_prime, _FLASH_PRIME_RGB)

    def decay_prime_flash(self):
        self.flash_prime = decay_flash(self.flash_prime, 0.85)

    def pattern_flash_color(self):
        """Current pattern-full-match flash overlay (r, g, b, a) in 0..1,
        or None if fully decayed. "line" viz-mode only -- flash_pattern
        only ever gets set to 1.0 from rebuild_line."""
        if self.flash_pattern <= 0.0:
            return None
        return flash_overlay_rgba(self.flash_pattern, _FLASH_PATTERN_RGB)

    def decay_pattern_flash(self):
        self.flash_pattern = decay_flash(self.flash_pattern, 0.65)

    # ------------------------------------------------------------------
    # Rebuild -- was rebuild_buffer's own closure body, minus its final
    # four GL-bound lines (ctx.buffer() x2), which the Faza-4 caller does
    # with this method's own return value.
    # ------------------------------------------------------------------

    def rebuild(self, n_value, prev_ring_count=None, advancing=False, audio=None):
        """Recomputes every piece of N-change-triggered state (ring
        geometry/colors, tracked/LCM HUD block, resonance log, tracked-
        outline draws, flash triggers) for `n_value` -- ports rebuild_
        buffer's own body verbatim except its final GL buffer uploads.
        Prints the same console lines rebuild_buffer always did (rebuild
        timing, factors-of-N/tracked HUD lines, resonance log, surviving
        primes) -- these are diagnostic/console-pane output, not test
        assertions, so keeping them here (rather than returning yet more
        strings) matches this module's "pure logic, incidental printing"
        convention elsewhere (playback.py, hud.py).

        `audio` -- forwarded to emit_audio_tick verbatim (that function's
        own `audio is None` guard already makes this a no-op when no audio
        engine is running, matching the original call site's behavior
        with no separate guard needed here).

        Returns (data_normal, data_hit, count, count_hit) -- split_hit_
        normal_vertex_data's own output, ready for the caller's two
        ctx.buffer() calls (see that function's own doc-comment)."""
        t0 = time.perf_counter()
        active = self.range_primes if self.range_mode else self.primes[self.primes <= n_value]

        if self.auto_orbit and not self.enabled_ids and advancing:
            new_index, new_counter, chosen = advance_auto_orbit(
                active, self.orbit_index, self.orbit_counter
            )
            self.orbit_index = new_index
            self.orbit_counter = new_counter
            if chosen is not None:
                self.orbit_current_prime = chosen

        cyclic_anchor_overrides = {
            family_id: cyclic_window_anchor_at(
                self.cyclic_anchor_state, family_id, active, n_value, self.theta, self.law_mode
            )
            for family_id in ("legendre", "generalLaw")
            if family_id in self.enabled_ids
        }
        window_anchors = window_anchor_primes(
            active, n_value, self.enabled_ids, self.theta, self.law_mode, cyclic_anchor_overrides
        )
        effective_track_primes = resolve_effective_track_primes(
            window_anchors, self.enabled_ids, self.auto_orbit, self.orbit_current_prime, self.track_primes
        )

        tracked_state = tracked_resonance_state(self.track_primes, active, n_value, auto_orbit=self.auto_orbit)
        resonance_track_primes = (
            tracked_state["tracked"]
            if tracked_state and not tracked_state.get("too_large") and tracked_state.get("to_resonance") == 0
            else ()
        )

        data, count, pos = build_vertex_data(
            active, n_value, self.max_radius, self.enabled_ids, self.theta, self.law_mode, effective_track_primes,
            resonance_track_primes
        )
        t1 = time.perf_counter()
        print(f"N={n_value:,}  rings={count:,}  rebuild={1000 * (t1 - t0):.1f}ms")

        emit_audio_tick(audio, active, pos['is_hit'], tracked_state, advancing)
        current_hud_lines = hud_lines_for_n(active, n_value, pos, self.enabled_ids, self.theta, self.law_mode, tracked_state)
        for line in current_hud_lines:
            print(line)

        update_resonance_log(self.resonance_log_state, active, n_value, self.range_mode, advancing)
        resonance_count, resonance_text = format_log_panel_text(self.resonance_log_state["lines"])
        print(f"Resonance log ({resonance_count}): {resonance_text}")
        primes_count, primes_text = format_log_panel_text(list(active))
        print(f"Surviving primes ({primes_count}): {primes_text}")

        self.outline_draws = build_tracked_outline_draws(
            active, n_value, self.enabled_ids, self.theta, self.law_mode, effective_track_primes, pos["radius"],
            cyclic_anchor_overrides
        )

        if prev_ring_count is not None and count > prev_ring_count:
            self.flash_prime = 1.0
        if resonance_is_active(pos):
            self.flash_resonance = 1.0

        data_normal, data_hit, count_hit = split_hit_normal_vertex_data(data, pos["is_hit"])

        self.hud_n = n_value
        self.hud_count = count
        self.hud_rebuild_ms = round(1000 * (t1 - t0), 1)
        self.hud_lines = current_hud_lines

        return data_normal, data_hit, count, count_hit

    def rebuild_line(self, n_value, advancing=False):
        """"line" viz-mode counterpart of rebuild(): the fixed dot-row for
        `self.range_primes` plus the sliding pattern's own positions/match
        state, via build_line_vertex_data. Deliberately independent of
        rebuild()'s ring/resonance/window/HUD-factors machinery above --
        line mode has none of that (no rings, no "factors of N", no
        resonance log); its only per-frame state is the pattern match.

        Returns (data_normal, data_hit, count, count_hit), the same shape
        rebuild() returns, so the caller's own two ctx.buffer() uploads and
        the main render loop's draw calls stay identical between modes."""
        t0 = time.perf_counter()
        data, count, hit_mask, all_match, view_mode = build_line_vertex_data(
            self.range_primes, n_value, self.pattern_offsets or (), primes_set=self._pattern_primes_set
        )
        t1 = time.perf_counter()
        print(f"N={n_value:,}  line dots={count:,}  view={view_mode}  rebuild={1000 * (t1 - t0):.1f}ms")

        self.pattern_match = all_match
        self.pattern_view_mode = view_mode
        if all_match:
            self.flash_pattern = 1.0

        data_normal, data_hit, count_hit = split_hit_normal_vertex_data(data, hit_mask)

        self.hud_n = n_value
        self.hud_count = count
        self.hud_rebuild_ms = round(1000 * (t1 - t0), 1)
        self.hud_lines = (
            [pattern_hud_line(
                n_value, self.pattern_offsets, all_match,
                wheel_modulus=self.pattern_wheel_modulus,
                wheel_residue_count=len(self.pattern_wheel_residues) if self.pattern_wheel_residues else 0,
                step_mode=self.pattern_step_mode, stop_on_match=self.pattern_stop_on_match,
                view_mode=view_mode,
            )]
            if self.pattern_offsets else []
        )
        for line in self.hud_lines:
            print(line)

        return data_normal, data_hit, count, count_hit

    # ------------------------------------------------------------------
    # HUD refresh -- was emit_hud_state (pure) + refresh_hud_texture's own
    # pure prefix (everything before ctx.texture()/hud_quad_vbo.write()),
    # unified since every pre-Faza-3 call site always called both together
    # (see _refresh_hud's own Faza-0 doc-comment).
    # ------------------------------------------------------------------

    def refresh_hud(self, hud_font_size):
        """Returns (json_line, rgba_or_None, width, height): `json_line` is
        the exact "HUD_STATE:..." line emit_hud_state used to print
        directly (caller prints it); `rgba`/`width`/`height` are refresh_
        hud_texture's own pure computation (None/0/0 if Pillow isn't
        installed or there's nothing to draw) -- the caller uploads this
        to a GL texture and rewrites its quad buffer, same as refresh_hud_
        texture's own final three lines did."""
        payload = {
            "n": self.hud_n,
            "count": self.hud_count,
            "rebuild_ms": self.hud_rebuild_ms,
            "lines": self.hud_lines,
            "running": self.playback_running,
            "tempo_ms": self.tempo_ms,
        }
        json_line = "HUD_STATE:" + json.dumps(payload)

        canvas_lines = compose_hud_canvas_lines(
            self.hud_n, self.hud_count, self.hud_lines, self.playback_running, self.tempo_ms
        )
        window_colors = window_label_colors(self.enabled_ids, self.hud_n, self.theta, self.law_mode)
        line_colors = hud_line_colors(canvas_lines, window_colors)
        rgba = rasterize_hud_text(canvas_lines, font_size=hud_font_size, line_colors=line_colors)
        if rgba is None:
            return json_line, None, 0, 0
        height, width = rgba.shape[0], rgba.shape[1]
        return json_line, rgba, width, height
