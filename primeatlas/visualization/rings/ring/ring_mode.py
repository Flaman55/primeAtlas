"""
ring_mode.py -- RingMode, the "rings" viz-mode: one ring per active small prime
(phase = n % p), window-family highlights (Bertrand/Legendre/General Law), tracked
primes with their LCM/resonance HUD block, auto-orbit, the resonance log and the
prime-birth/resonance flash overlays. See shared/mode.py for the hook contract.

Self-contained sys.path bootstrap (mirrors renderer.py's own -- see that
file's module docstring for the full "why plain-script-path" explanation):
needed so the primeatlas.* imports below work whether this module is imported
after renderer.py has already run its own bootstrap, or on its own (e.g.
directly from a test).
"""

import os
import sys
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_PRIME_SIEVE_DIR = os.path.join(_REPO_ROOT, "prime_sieve")
if _PRIME_SIEVE_DIR not in sys.path:
    sys.path.insert(0, _PRIME_SIEVE_DIR)

from primeatlas.visualization.shared.mode import VizMode
from primeatlas.visualization.shared.draw_primitives import (
    split_hit_normal_vertex_data, decay_flash, flash_overlay_rgba,
)
from primeatlas.visualization.rings.ring.ring_geometry import (
    tracked_resonance_state, window_anchor_primes, cyclic_window_anchor_at,
    format_log_panel_text, window_label_colors, nested_shell_colors,
)
from primeatlas.visualization.rings.ring.ring_draw import (
    build_vertex_data, resolve_effective_track_primes, build_tracked_outline_draws,
    _FLASH_RESONANCE_RGB, _FLASH_PRIME_RGB, resonance_is_active,
)
from primeatlas.visualization.rings.ring.ring_hud import hud_lines_for_n, hud_line_colors, emit_audio_tick
from primeatlas.visualization.rings.ring.ring_playback import update_resonance_log, advance_auto_orbit


class RingMode(VizMode):
    """Ring-mode state: window/tracking launch config, auto-orbit cycling, cyclic
    window-anchor state, flash decay accumulators, tracked-outline draw list and the
    resonance log. Reads N/primes/range state from the owning session."""

    name = "rings"
    reset_mode = "rings"

    def __init__(self, session, config):
        super().__init__(session, config)
        # Window/tracking launch-time config.
        self.track_primes = config["track_primes"]
        self.auto_orbit = config["auto_orbit"]
        self.enabled_ids = config["enabled_ids"]
        self.theta = config["theta"]
        self.law_mode = config["law_mode"]

        # Auto-orbit cycling.
        self.orbit_index = 0
        self.orbit_counter = 0
        self.orbit_current_prime = None

        # Cyclic window-anchor freeze/jump state, one entry per family -- see
        # cyclic_window_anchor_at.
        self.cyclic_anchor_state = {}

        # Birth/resonance flash decay accumulators + tracked-outline draw list.
        self.flash_prime = 0.0
        self.flash_resonance = 0.0
        self._outline_draws = []

        # Resonance log.
        self.resonance_log_state = {"lines": [], "last_n": None, "last_range_mode": None}

    # ------------------------------------------------------------------
    # Launch-time CLI arguments (see VizMode.add_arguments).
    # ------------------------------------------------------------------

    @classmethod
    def add_arguments(cls, parser):
        # Window-highlight-color parity with the browser version's
        # Bertrand/Legendre/General Law toggles -- comma list of family ids
        # among the three ring_geometry.WINDOW_FAMILY_COLORS keys.
        parser.add_argument("--windows", type=str, default="",
                             help="comma-separated window families to highlight: bertrand,legendre,generalLaw")
        parser.add_argument("--general-law-theta", type=float, default=0.5)
        # 'bertrand'/'legendre' are RIGID modes reproducing those families' windows
        # EXACTLY (theta ignored, forced to 1.0/0.5 in prepare_launch for any place
        # that might echo it) instead of approximating them via theta. Default
        # 'sliding': its n^theta formula matches literature prime-gap bounds
        # (Baker-Harman-Pintz theta=0.525, Runbo Li's 2023 refinement theta=0.52).
        parser.add_argument("--general-law-mode", choices=["stepped", "sliding", "bertrand", "legendre"], default="sliding")
        # Track P -- comma-separated prime values (same convention as
        # --windows), and --auto-orbit as the JS's #autoOrbit mode (auto-cycle
        # active primes when nothing is explicitly tracked). See rings_tab.py's
        # Track P field docstring for the launch-time-only rationale.
        parser.add_argument("--track-primes", type=str, default="",
                             help="comma-separated prime values to track, e.g. 2,3,5")
        parser.add_argument("--auto-orbit", action="store_true",
                             help="auto-cycle through active primes instead of a fixed Track P list")

    @classmethod
    def validate_arguments(cls, parser, args):
        valid_families = {"bertrand", "legendre", "generalLaw"}
        requested_families = {f.strip() for f in args.windows.split(",") if f.strip()}
        unknown = requested_families - valid_families
        if unknown:
            parser.error(f"--windows has unknown family id(s) {sorted(unknown)!r}, expected any of {sorted(valid_families)}")

        # Validate --track-primes up front (same fail-fast convention as
        # --windows above) instead of letting a malformed entry raise an
        # uncaught ValueError later inside prepare_launch's own int(p.strip()) parsing.
        if args.track_primes:
            bad = []
            for raw in args.track_primes.split(","):
                raw = raw.strip()
                if not raw:
                    continue
                if not raw.isdigit():
                    bad.append(raw)
            if bad:
                parser.error(f"--track-primes has non-integer value(s) {bad!r}, expected comma-separated primes e.g. 2,3,5")

    @classmethod
    def prepare_launch(cls, args, launch):
        # Window-highlight families enabled at launch time -- parsed once here
        # (not per-frame): "" -> empty set (see build_vertex_data's own
        # doc-comment). No live in-window toggle (would need on-screen UI this
        # raw GL window doesn't have) -- set via rings_tab.py's launch-time
        # checkboxes instead, same as N itself.
        enabled_ids = {f.strip() for f in args.windows.split(",") if f.strip()} if args.windows else set()
        theta = args.general_law_theta
        law_mode = args.general_law_mode
        # 'bertrand'/'legendre' are RIGID modes -- theta is ignored by every
        # general_law_* function for these two (see general_law_window_bounds), so it is
        # forced here to the value it represents, keeping any place that echoes `theta`
        # consistent instead of relying on every call site not to trust it.
        if law_mode == "bertrand":
            theta = 1.0
        elif law_mode == "legendre":
            theta = 0.5

        # Track P -- parsed once here (not per-frame), same launch-time-only
        # convention as --windows above (no live in-window text field, see
        # rings_tab.py's own Track P field docstring for why). `--auto-orbit` is
        # accepted and stored for the playback loop to read; on its own it
        # suppresses the tracked/LCM HUD block (mirrors the JS's own
        # #trackedResonanceState guard).
        track_primes = [int(p.strip()) for p in args.track_primes.split(",") if p.strip()] if args.track_primes else []
        auto_orbit = args.auto_orbit

        # A successful Load Range auto-populates Track P with EVERY ring in the
        # loaded range -- so the LCM/phase/to-resonance HUD reflects the whole
        # set -- but only up to tracked_resonance_state's own cap
        # (max_tracked_for_exact_lcm's default, 500), same reasoning as the JS's
        # #maxTrackedForExactLcm: past that the exact BigInt LCM of the whole set
        # would be too slow to multiply even once. Overwrites whatever
        # --track-primes was set at launch, exactly like the JS overwrites
        # this.#trackedPrimes unconditionally on a successful range load.
        if launch.range_mode and 0 < len(launch.range_primes) <= 500:
            track_primes = [int(p) for p in launch.range_primes]
            auto_orbit = False

        return {"track_primes": track_primes, "auto_orbit": auto_orbit, "enabled_ids": enabled_ids,
                "theta": theta, "law_mode": law_mode}

    def reset_state(self):
        """R: drop Track P, re-enable auto-orbit, restart the orbit (mirrors the
        HTML's own resetSequential())."""
        self.track_primes.clear()
        self.auto_orbit = True
        self.orbit_index = 0
        self.orbit_counter = 0
        self.orbit_current_prime = None

    # ------------------------------------------------------------------
    # Flash overlays -- split into "what color right now" (pure) and "advance the
    # decay" (mutates), so the caller can draw between the two.
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

    def flash_overlays(self):
        out = []
        resonance_color = self.resonance_flash_color()
        if resonance_color is not None:
            out.append((resonance_color, self.decay_resonance_flash))
        prime_color = self.prime_flash_color()
        if prime_color is not None:
            out.append((prime_color, self.decay_prime_flash))
        return out

    def outline_draws(self):
        return self._outline_draws

    def hud_line_colors(self, canvas_lines):
        hud_n = self.session.hud_n
        window_colors = window_label_colors(self.enabled_ids, hud_n, self.theta, self.law_mode)
        shell_colors = nested_shell_colors(self.enabled_ids, hud_n, self.theta, self.law_mode)
        return hud_line_colors(canvas_lines, window_colors, shell_colors)

    # ------------------------------------------------------------------
    # Rebuild -- everything except the GL buffer uploads (ctx.buffer() x2), which
    # the caller does with this method's return value.
    # ------------------------------------------------------------------

    def rebuild(self, n_value, prev_ring_count=None, advancing=False, audio=None):
        """Recomputes every piece of N-change-triggered state (ring
        geometry/colors, tracked/LCM HUD block, resonance log, tracked-
        outline draws, flash triggers) for `n_value` -- everything except the
        final GL buffer uploads. Prints the console lines (rebuild
        timing, factors-of-N/tracked HUD lines, resonance log, surviving
        primes) -- these are diagnostic/console-pane output, not test
        assertions, so keeping them here (rather than returning yet more
        strings) matches this package's "pure logic, incidental printing"
        convention elsewhere (playback.py, ring_hud.py).

        `audio` -- forwarded to emit_audio_tick verbatim (that function's
        own `audio is None` guard already makes this a no-op when no audio
        engine is running, so no separate guard is needed here).

        Returns (data_normal, data_hit, count, count_hit) -- split_hit_
        normal_vertex_data's own output, ready for the caller's two
        ctx.buffer() calls (see that function's own doc-comment)."""
        s = self.session
        t0 = time.perf_counter()
        active = s.range_primes if s.range_mode else s.primes[s.primes <= n_value]

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
            active, n_value, s.max_radius, self.enabled_ids, self.theta, self.law_mode, effective_track_primes,
            resonance_track_primes
        )
        t1 = time.perf_counter()
        print(f"N={n_value:,}  rings={count:,}  rebuild={1000 * (t1 - t0):.1f}ms")

        emit_audio_tick(audio, active, pos['is_hit'], tracked_state, advancing)
        current_hud_lines = hud_lines_for_n(active, n_value, pos, self.enabled_ids, self.theta, self.law_mode, tracked_state)
        for line in current_hud_lines:
            print(line)

        update_resonance_log(self.resonance_log_state, active, n_value, s.range_mode, advancing)
        resonance_count, resonance_text = format_log_panel_text(self.resonance_log_state["lines"])
        print(f"Resonance log ({resonance_count}): {resonance_text}")
        primes_count, primes_text = format_log_panel_text(list(active))
        print(f"Surviving primes ({primes_count}): {primes_text}")

        self._outline_draws = build_tracked_outline_draws(
            active, n_value, self.enabled_ids, self.theta, self.law_mode, effective_track_primes, pos["radius"],
            cyclic_anchor_overrides
        )

        if prev_ring_count is not None and count > prev_ring_count:
            self.flash_prime = 1.0
        if resonance_is_active(pos):
            self.flash_resonance = 1.0

        data_normal, data_hit, count_hit = split_hit_normal_vertex_data(data, pos["is_hit"])

        s.hud_n = n_value
        s.hud_count = count
        s.hud_rebuild_ms = round(1000 * (t1 - t0), 1)
        s.hud_lines = current_hud_lines

        return data_normal, data_hit, count, count_hit
