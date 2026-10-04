"""
line_mode.py -- LineMode, the "line" viz-mode: a fixed row of real primes from
--load-range with an optional k-tuple pattern slid along it by N. Owns the pattern
state, the wheel of residues a pattern anchor can take, wheel-aware navigation and
the pattern seek (run on the session's background-seek thread when the sliding
window is on). See shared/mode.py for the hook contract.

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

from primeatlas.visualization.shared.mode import VizMode, LaunchAborted
from primeatlas.visualization.shared.bigint import parse_big_int
from primeatlas.visualization.shared.draw_primitives import (
    split_hit_normal_vertex_data, decay_flash, flash_overlay_rgba,
)
from primeatlas.visualization.rings.line.line_geometry import (
    pattern_wheel_residues, next_wheel_n, pattern_positions_and_match, DEFAULT_WHEEL_PRIMES,
    pattern_offsets_from_seed, next_prime_at_or_above, resolve_pattern_anchor,
)
from primeatlas.visualization.rings.line.line_draw import build_line_vertex_data, _FLASH_PATTERN_RGB
from primeatlas.visualization.rings.line.line_hud import pattern_hud_line


class LineMode(VizMode):
    """Line-mode state: the k-tuple pattern (offsets, wheel, match state, the cached
    set of loaded primes it is matched against), the Manual/Auto step regime, the
    curved-axis layout choice and the pattern-match flash."""

    name = "line"

    def __init__(self, session, config):
        super().__init__(session, config)
        s = session
        pattern_offsets = config.get("pattern_offsets")
        self.pattern_offsets = list(pattern_offsets) if pattern_offsets else None
        self.pattern_match = False
        self.pattern_view_mode = None
        # Purely cosmetic, launch-time-only choice: draw the axis as a straight line
        # (default) or bent into a circle -- see line_draw.
        # build_line_vertex_data's own `curved` doc-comment for why this
        # never touches matching/navigation/wheel logic, only which (x,y)
        # a position renders at.
        self.line_axis_curved = bool(config.get("line_axis_curved", False))
        # The curved-axis boundary marker's own radius for THIS frame --
        # world_width/2 for a plain circle, or spiral_outer_radius's
        # bigger value once a real wheel promotes the layout to a spiral
        # (see build_line_vertex_data's own `boundary_radius` return) --
        # None whenever line_axis_curved is False (nothing to draw).
        # renderer.py's main loop reads this (axis_boundary_radius()) instead of
        # hardcoding a fixed radius, so the marker always reaches exactly
        # as far out as the outermost lap actually drawn this frame.
        self.pattern_axis_boundary_radius = None
        self.flash_pattern = 0.0
        # Wheel-skip: which n (mod some small-prime-derived period) can
        # EVER match, computed once up front from the pattern's own
        # offsets -- see pattern_wheel_residues' own doc-comment. Only
        # meaningful (modulus > 1) once a pattern is actually set;
        # scrub/tick fall back to the session's plain +1/+step
        # behavior whenever it isn't (modulus is None or 1).
        if self.pattern_offsets:
            self.pattern_wheel_modulus, self.pattern_wheel_residues = pattern_wheel_residues(self.pattern_offsets)
            # Cached ONCE (range_primes is fixed for the life of line mode --
            # there is no buffer-extension concept there, see
            # should_extend_buffer's own range_mode bypass) so both the
            # founding-coincidence patch just below and _pattern_seek's own
            # repeated match checks don't rebuild this from a numpy array
            # on every single candidate.
            self._pattern_primes_set = set(int(v) for v in s.range_primes) if len(s.range_primes) else set()
            # Any real occurrence of this pattern whose OWN anchor value
            # coincides with one of the wheel's own small primes is a
            # "founding coincidence" (pattern_wheel_residues' own
            # doc-comment) -- pure residue arithmetic excludes it
            # (n mod p == 0 looks like "forced composite", even though n
            # itself is prime, not composite), making it UNREACHABLE by
            # scrubbing/seeking otherwise -- both the launch anchor itself (seed 3
            # for a {0,2} pattern) and a match inside the range (n=11 for a k=5
            # pattern, which --pattern-stop-on-match's search would never consider
            # a candidate). Patch
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
                for candidate in (s.n, *DEFAULT_WHEEL_PRIMES):
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

        # Manual/Auto radio + "MATCH!" checkbox (see _pattern_uses_seek for the
        # combined semantics): "manual" always takes a single wheel step, showing
        # every candidate whether it's a match or not; "auto" always SEEKS -- for a
        # MATCH! when checked, or for a non-match when unchecked.
        self.pattern_step_mode = config.get("pattern_step_mode", "manual")
        self.pattern_stop_on_match = config.get("pattern_stop_on_match", False)

    # ------------------------------------------------------------------
    # Launch-time CLI arguments (see VizMode.add_arguments).
    # ------------------------------------------------------------------

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument("--pattern-seed-k", type=int, default=None,
                             help="line mode only: take this many real consecutive primes >= "
                                  "--pattern-seed-start as the sliding k-tuple pattern's offsets")
        parser.add_argument("--pattern-seed-start", type=parse_big_int, default=None,
                             help="line mode only: starting prime (must be > 2) for --pattern-seed-k")
        # Manual/Auto step-mode radio + "MATCH!" checkbox: "manual" (default) always
        # takes a single wheel step per
        # LEFT/RIGHT/Up/Down/Space, showing every wheel candidate in turn
        # whether it's a real match or not; "auto" always SEEKS instead --
        # for the next real MATCH! when the checkbox is given, or specifically
        # for the next NON-match wheel candidate when it isn't. See
        # LineMode._pattern_uses_seek's own doc-comment for the exact rule.
        parser.add_argument("--pattern-step-mode", choices=["manual", "auto"], default="manual",
                             help="line mode pattern only: 'manual' (default) always takes a single wheel "
                                  "step per navigation key; 'auto' always seeks instead (see "
                                  "--pattern-stop-on-match for which kind)")
        parser.add_argument("--pattern-stop-on-match", action="store_true",
                             help="line mode pattern only, and only with --pattern-step-mode auto: seek "
                                  "the next real MATCH! when given, or specifically the next NON-match "
                                  "wheel candidate when not given")
        # Purely cosmetic: bend the axis into a
        # circle instead of a straight line -- see line_draw.
        # build_line_vertex_data's own `curved` doc-comment. Does not change
        # navigation, matching, or the wheel/seek logic at all, only where a
        # position renders on screen -- see LineMode.line_axis_curved.
        parser.add_argument("--line-axis-curved", action="store_true",
                             help="line mode only: draw the axis bent into a circle instead of a "
                                  "straight line (purely visual -- the loaded window's own start/end "
                                  "coincide on screen, marked with a red boundary line, since they are "
                                  "NOT actually the same value the way a real periodic wraparound would be)")

    @classmethod
    def validate_arguments(cls, parser, args):
        if args.viz_mode == cls.name and not args.load_range:
            parser.error("--viz-mode line requires --load-range")
        if (args.pattern_seed_k is None) != (args.pattern_seed_start is None):
            parser.error("--pattern-seed-k and --pattern-seed-start must be given together")
        if args.pattern_seed_k is not None:
            if args.viz_mode != cls.name:
                parser.error("--pattern-seed-k/--pattern-seed-start require --viz-mode line")
            if args.pattern_seed_k < 2:
                parser.error(f"--pattern-seed-k must be >= 2, got {args.pattern_seed_k}")
            if args.pattern_seed_start <= 2:
                parser.error(f"--pattern-seed-start must be > 2, got {args.pattern_seed_start}")

    @classmethod
    def prepare_launch(cls, args, launch):
        # --viz-mode line draws range_primes directly (see rebuild) and has
        # no fallback "primes[primes <= n]" path the way ring mode does -- a
        # --load-range that failed to actually populate range_primes (the
        # "Load Range failed" message, or a --max-load-count of 0)
        # would otherwise crash deep inside build_line_vertex_data instead of
        # surfacing the real cause. validate_arguments can only
        # check that --load-range was GIVEN, not that it actually loaded
        # (load_prime_range_slice needs the real `primes` array to know that),
        # so this is the earliest point that can catch it.
        if args.viz_mode == cls.name and not launch.range_mode:
            raise LaunchAborted(
                "--viz-mode line requires --load-range to load successfully -- see the "
                "'Load Range failed' message above. Exiting without opening a window.")

        # k-tuple pattern-slide seed -- derived from real
        # consecutive primes >= --pattern-seed-start, see
        # pattern_offsets_from_seed's own doc-comment for why this always yields
        # an admissible pattern. validate_arguments already
        # guarantees --pattern-seed-k/--pattern-seed-start only appear together
        # and only with --viz-mode line + --load-range, so no further gating is
        # needed here.
        #
        # --pattern-seed-start only picks the pattern's SHAPE (which of the
        # catalog's v1..v4-style offset variants) -- a small seed like 7 or 11
        # works exactly the same way whether --load-range is [1, 1000] or a
        # real archive-scale [10**22, 10**23]. The pattern's OWN anchor
        # (`n`) is a completely separate concern: if the seed's own resolved
        # occurrence actually falls inside the loaded window, start there (an
        # immediate, guaranteed real MATCH! -- see pattern_offsets_from_seed's
        # own doc-comment for why). Otherwise (the archive-scale case: the
        # window is nowhere near the small seed used only to pick the shape)
        # DON'T just clamp to the window's raw lower edge -- that's an
        # arbitrary value with no guarantee of even being wheel-compatible.
        # Compute the phase (pattern_wheel_residues, same math LineMode's own
        # constructor uses) and jump straight to the first genuinely
        # wheel-compatible candidate at or past the window's lower edge, so
        # scrubbing from there on is correctly phase-aligned from frame one.
        pattern_offsets = None
        if args.pattern_seed_k is not None:
            pattern_offsets = pattern_offsets_from_seed(args.pattern_seed_k, args.pattern_seed_start)
            seed_prime = next_prime_at_or_above(args.pattern_seed_start)
            print(f"Pattern seed: k={args.pattern_seed_k} start={args.pattern_seed_start:,} -> "
                  f"offsets={pattern_offsets} (first realized at n={seed_prime:,})")
            if launch.range_mode and len(launch.range_primes):
                lo = int(launch.range_primes[0])
                hi = int(launch.range_primes[-1]) - pattern_offsets[-1]
                launch.n = resolve_pattern_anchor(seed_prime, pattern_offsets, lo, hi)
                if launch.n != seed_prime:
                    print(f"Pattern seed's own occurrence (n={seed_prime:,}) is outside the loaded "
                          f"window -- starting instead at the first phase-compatible candidate: n={launch.n:,}")

        return {"pattern_offsets": pattern_offsets, "pattern_step_mode": args.pattern_step_mode,
                "pattern_stop_on_match": args.pattern_stop_on_match,
                "line_axis_curved": args.line_axis_curved}

    # ------------------------------------------------------------------
    # Sliding-window hook.
    # ------------------------------------------------------------------

    def on_chunks_changed(self):
        """Rebuilds `_pattern_primes_set` as the UNION of every currently-
        loaded chunk (back + current + forward), not `chunk_current` alone
        -- a k-tuple's own offsets can straddle a chunk seam, and all three
        chunks are already resident in memory so this costs nothing extra.
        `_pattern_window_bounds()` (where the cursor itself is allowed to
        sit) deliberately stays scoped to `chunk_current` only -- these are
        genuinely two different ranges (pattern-match correctness at chunk
        seams vs. cursor placement). No-op when no pattern is set."""
        if self.pattern_offsets is None:
            return
        s = self.session
        self._pattern_primes_set = set(int(v) for v in s.chunk_current) if len(s.chunk_current) else set()
        if s.chunk_back is not None and len(s.chunk_back):
            self._pattern_primes_set.update(int(v) for v in s.chunk_back)
        if s.chunk_forward is not None and len(s.chunk_forward):
            self._pattern_primes_set.update(int(v) for v in s.chunk_forward)

    # ------------------------------------------------------------------
    # Pattern window, wheel steps and seek.
    # ------------------------------------------------------------------

    def _pattern_window_bounds(self):
        """(lo, hi) the current pattern's anchor must stay
        inside -- lo is the loaded range's own lower edge, hi is reduced
        by the pattern's diameter so its last member never scrubs past
        the loaded window's upper edge (see clamp_pattern_anchor's own
        doc-comment). None when no pattern is set."""
        range_primes = self.session.range_primes
        if self.pattern_offsets and len(range_primes):
            return int(range_primes[0]), int(range_primes[-1]) - self.pattern_offsets[-1]
        return None

    def clamp_n(self, n):
        """A no-op when no pattern is set. Used only where a plain step (bump_n, or
        scrub/tick's own fallback when the wheel offers no filtering -- see
        _pattern_wheel_step below) needs the window clamp on its own; the wheel jump
        already respects this same window."""
        bounds = self._pattern_window_bounds()
        if bounds is None:
            return n
        lo, hi = bounds
        return max(lo, min(n, hi))

    def _pattern_wheel_step(self, n, is_right):
        """One wheel-aware jump (see line_geometry.next_wheel_n) toward
        the next position that can EVER match this pattern, skipping
        every n forced composite by small-prime divisibility alone.

        When sliding is enabled (see RenderSession's own doc-comment on
        `sliding_enabled`) and `next_wheel_n` reports nothing further
        within `chunk_current`'s own edge, this SLIDES the triple-buffer
        window one (or, for a pathologically sparse chunk, more than one --
        see the `while True` below) chunk further in `is_right`'s
        direction and keeps searching. After a slide, the search resumes from just
        past the new chunk's own edge (`lo - 1`/`hi + 1`) -- next_wheel_n's
        own residue arithmetic is ABSOLUTE (see its own doc-comment), so
        this correctly finds the first real wheel-compatible candidate in
        the new window regardless of how far the slide moved.

        Returns `n` UNCHANGED -- the ORIGINAL `n` passed in, not some
        intermediate post-slide position -- when there is no further such
        position anywhere: sliding is off, every slide attempt failed
        (the TRUE `range_load_from`/`range_load_to` edge was reached), or
        (self.pattern_wheel_residues == []) the pattern's own wheel proves
        it can never repeat at all. This preserves the "n unchanged == stuck"
        contract _pattern_seek/tick/bump_n/scrub rely on.

        Clears both edge-reported flags (and their HUD line, see rebuild's
        edge_lines) on ANY move, not just a chunk-crossing one: a step away from an
        edge that stays inside the loaded chunk_current is still a move away from it,
        and the edge message must not stay on screen."""
        s = self.session
        bounds = self._pattern_window_bounds()
        if bounds is None:
            return n
        lo, hi = bounds
        current = n
        while True:
            nxt = next_wheel_n(current, is_right, self.pattern_wheel_modulus, self.pattern_wheel_residues, lo, hi)
            if nxt != current:
                if s._forward_edge_reported or s._back_edge_reported:
                    s._forward_edge_reported = False
                    s._back_edge_reported = False
                    s.n_force_rebuild = True
                return nxt
            if not s.sliding_enabled:
                return n
            slid = s._slide_forward() if is_right else s._slide_backward()
            if not slid:
                return n
            bounds = self._pattern_window_bounds()
            if bounds is None:
                return n
            lo, hi = bounds
            current = (lo - 1) if is_right else (hi + 1)

    def _has_pattern_wheel(self):
        """Whether scrub/tick/bump_n should use the wheel-jump path at
        all -- False falls back to the session's plain +1/+step behavior,
        which is the correct thing to do both with no pattern set
        and in the rare case the wheel found nothing to filter at all
        (modulus == 1 -- see pattern_wheel_residues' own doc-comment)."""
        return bool(
            self.pattern_offsets
            and self.pattern_wheel_modulus is not None and self.pattern_wheel_modulus > 1
        )

    def _pattern_uses_seek(self):
        """Whether an advance action should keep taking wheel steps (see
        _pattern_seek) instead of a single wheel step. The Manual/Auto radio
        (`pattern_step_mode`) is the master switch: "manual" ALWAYS takes a single
        step, showing every wheel candidate in turn whether it's a match or not;
        only "auto" seeks. Used identically by scrub, bump_n, and tick, so
        arrows/Up-Down/Space all agree on which regime is active."""
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
        mode that does. Returns (final_n, found) -- `found` is False only
        when the search reaches the genuine window edge (or the wheel
        proved this pattern can never repeat at all) without ever landing
        on the desired kind, same "stuck" signal _pattern_wheel_step's own
        n-unchanged convention gives its callers.

        No step cap: at archive scale (a k=5+ pattern, a sparse loaded range) the
        next MATCH! can be any number of wheel steps away, and stopping early would
        land on an arbitrary non-match candidate. The loop still terminates: the
        cursor is bounded by the loaded window (`_pattern_window_bounds`), and
        next_wheel_n returns `n` unchanged once there is nowhere further in
        `is_right`'s direction, which `_pattern_wheel_step` propagates as
        `nxt == current` below -- at most one iteration per wheel-compatible position
        in the window."""
        current = n
        want_match = self.pattern_stop_on_match
        while True:
            nxt = self._pattern_wheel_step(current, is_right)
            if nxt == current:
                return current, False
            current = nxt
            is_match = pattern_positions_and_match(current, self.pattern_offsets, self._pattern_primes_set)[2]
            if is_match == want_match:
                return current, True

    def _start_pattern_seek(self, is_right, is_tick):
        """Runs _pattern_seek(session.n, is_right) on the session's background-seek
        thread (RenderSession.start_background_seek) instead of blocking the GLFW
        main thread: with sliding enabled, _pattern_seek has no step cap and a small
        `chunk_size` against a sparse pattern can need many chunk crossings, each a
        disk load, to reach the next MATCH!. Only called from tick()/bump_n()/scrub()
        when the session's `sliding_enabled` is on -- without sliding,
        _pattern_wheel_step cannot loop (`if not s.sliding_enabled: return n` fires
        on the first failed candidate), so non-sliding call sites call _pattern_seek
        synchronously.

        `is_tick` selects tick()'s extra not-found behavior (stop playback + print;
        tick() returns immediately, so the main loop cannot react to a return value)
        versus bump_n/scrub's silent no-op-on-miss. Both commit only when found."""
        start_n = self.session.n
        self.session.start_background_seek(
            lambda: self._pattern_seek(start_n, is_right), is_tick,
            "Playback stopped: pattern search reached the loaded range's own edge",
        )

    # ------------------------------------------------------------------
    # Navigation hooks.
    # ------------------------------------------------------------------

    def tick(self):
        """With a meaningful pattern wheel, advances straight to the next
        wheel-compatible n (see _pattern_wheel_step) instead of ticking by
        1/range_step -- this is the whole point of the wheel: skip every n the
        small-prime divisibility check alone already rules out. Returns None (the
        session's plain tick runs) when there is no wheel; otherwise True if
        playback just stopped (the pattern's last member reached the loaded window's
        edge, or the wheel found no further compatible position), False if N
        advanced."""
        if not self._has_pattern_wheel():
            return None
        s = self.session
        if self._pattern_uses_seek():
            if s.sliding_enabled:
                # With sliding enabled, a seek that needs to cross
                # chunks runs in the BACKGROUND (see
                # _start_pattern_seek's own doc-comment) -- this kicks
                # it off (or no-ops if one is already running) and
                # returns False immediately; playback keeps "running"
                # while the search is in flight, and the worker itself
                # flips playback_running False once it resolves
                # without a further match.
                self._start_pattern_seek(True, is_tick=True)
                return False
            new_n, found = self._pattern_seek(s.n, True)
            # found=False here means the loaded-window edge was reached
            # without landing on the desired kind (_pattern_seek has no early
            # give-up), so stay HERE, at the last position that satisfied
            # pattern_stop_on_match, not at `new_n` (the last, non-desired wheel
            # candidate passed on the way to the edge).
            if not found:
                new_n = s.n
        else:
            new_n = self._pattern_wheel_step(s.n, True)
        if new_n == s.n:
            s.playback_running = False
            return True
        s.n = new_n
        s.n_advancing = True
        return False

    def bump_n(self, delta):
        """With a meaningful pattern wheel, `delta`'s raw magnitude (n_step, 1000 by
        default) is meaningless once most integers can never match at all -- landing
        on an arbitrary +1000 offset looks like the wheel jump is "shifted" when it's
        really just a different, wheel-UNAWARE code path. Up/Down/PageUp/PageDown
        jump ONE wheel step instead, in `delta`'s own sign direction, so every
        navigation key in this mode only ever lands on a position the pattern could
        actually match. Returns False (the session's plain step runs) when there is
        no wheel."""
        if not self._has_pattern_wheel():
            return False
        s = self.session
        if self._pattern_uses_seek():
            if s.sliding_enabled:
                # See tick()'s own doc-comment on why a sliding seek
                # runs in the background -- same reasoning, same
                # no-op-if-already-running/found-gated commit here.
                self._start_pattern_seek(delta >= 0, is_tick=False)
                return True
            # Only commit the seek's own landing spot when it actually found
            # the desired kind -- see tick()'s own comment on `found` for why
            # (the genuine window edge, now the ONLY way this is False,
            # should leave n on the last position that WAS the desired kind).
            new_n, found = self._pattern_seek(s.n, delta >= 0)
            if found:
                s.n = new_n
        else:
            s.n = self._pattern_wheel_step(s.n, delta >= 0)
        return True

    def scrub(self, is_right, ctrl_held):
        """With a meaningful pattern wheel, every press/repeat jumps straight to the
        next wheel-compatible n in that direction (Ctrl repeats the jump 10 times
        instead of 1, mirroring arrow_scrub_delta's own x10 -- see
        _pattern_wheel_step), stopping early without error if the window edge (or an
        empty wheel -- the pattern can never repeat) is reached partway through.
        Returns False (the session's plain scrub runs) when there is no wheel."""
        if not self._has_pattern_wheel():
            return False
        s = self.session
        if self._pattern_uses_seek():
            if s.sliding_enabled:
                # See tick()'s own doc-comment on why a sliding seek
                # runs in the background.
                self._start_pattern_seek(is_right, is_tick=False)
                return True
            # Same "only commit on an actual found match" guard as bump_n's
            # own -- see tick()'s comment for why.
            new_n, found = self._pattern_seek(s.n, is_right)
            if found:
                s.n = new_n
            return True
        for _ in range(10 if ctrl_held else 1):
            new_n = self._pattern_wheel_step(s.n, is_right)
            if new_n == s.n:
                break
            s.n = new_n
        return True

    # ------------------------------------------------------------------
    # Frame data.
    # ------------------------------------------------------------------

    def pattern_flash_color(self):
        """Current pattern-full-match flash overlay (r, g, b, a) in 0..1,
        or None if fully decayed. flash_pattern only ever gets set to 1.0 from
        rebuild()."""
        if self.flash_pattern <= 0.0:
            return None
        return flash_overlay_rgba(self.flash_pattern, _FLASH_PATTERN_RGB)

    def decay_pattern_flash(self):
        self.flash_pattern = decay_flash(self.flash_pattern, 0.65)

    def flash_overlays(self):
        color = self.pattern_flash_color()
        return [(color, self.decay_pattern_flash)] if color is not None else []

    def axis_boundary_radius(self):
        if self.line_axis_curved and self.pattern_axis_boundary_radius:
            return self.pattern_axis_boundary_radius
        return None

    def rebuild(self, n_value, prev_ring_count=None, advancing=False, audio=None):
        """The fixed dot-row for the session's `range_primes` plus the sliding
        pattern's own positions/match state, via build_line_vertex_data. Line mode
        has no rings, no "factors of N", no resonance log; its only per-frame state
        is the pattern match. `prev_ring_count`/`audio` are accepted for the shared
        rebuild signature and unused.

        Returns (data_normal, data_hit, count, count_hit), the same shape
        RingMode.rebuild returns, so the caller's own two ctx.buffer() uploads and
        the main render loop's draw calls stay identical between modes."""
        s = self.session
        t0 = time.perf_counter()
        data, count, hit_mask, all_match, view_mode, boundary_radius = build_line_vertex_data(
            s.range_primes, n_value, self.pattern_offsets or (), primes_set=self._pattern_primes_set,
            curved=self.line_axis_curved, wheel_modulus=self.pattern_wheel_modulus,
        )
        self.pattern_axis_boundary_radius = boundary_radius
        t1 = time.perf_counter()
        print(f"N={n_value:,}  line dots={count:,}  view={view_mode}  rebuild={1000 * (t1 - t0):.1f}ms")

        self.pattern_match = all_match
        self.pattern_view_mode = view_mode
        if all_match:
            self.flash_pattern = 1.0

        data_normal, data_hit, count_hit = split_hit_normal_vertex_data(data, hit_mask)

        s.hud_n = n_value
        s.hud_count = count
        s.hud_rebuild_ms = round(1000 * (t1 - t0), 1)
        # Sliding-window "hard edge reached" indicator in the GL window itself
        # (the console line alone is not visible while watching the window; see
        # RenderSession._slide_forward/_slide_backward), driven by the SAME dedup
        # flags those methods set/clear, so it appears and disappears with the
        # console message.
        edge_lines = []
        if s._seek_thread is not None:
            # Background pattern seek in flight (see _start_pattern_seek's
            # own doc-comment) -- N itself hasn't moved yet, so without
            # this the GUI would look identical to before the key was
            # pressed for however long the search takes; this line is the
            # window's own confirmation "yes, it's working."
            edge_lines.append("Searching for the next pattern match...")
        if s._forward_edge_reported:
            edge_lines.append(f"At range TO edge ({s.range_load_to:,}) -- cannot go further forward")
        if s._back_edge_reported:
            edge_lines.append(f"At range FROM edge ({s.range_load_from:,}) -- cannot go further backward")
        s.hud_lines = (
            [pattern_hud_line(
                n_value, self.pattern_offsets, all_match,
                wheel_modulus=self.pattern_wheel_modulus,
                wheel_residue_count=len(self.pattern_wheel_residues) if self.pattern_wheel_residues else 0,
                step_mode=self.pattern_step_mode, stop_on_match=self.pattern_stop_on_match,
                view_mode=view_mode, line_axis_curved=self.line_axis_curved,
            )] + edge_lines
            if self.pattern_offsets else []
        )
        for line in s.hud_lines:
            print(line)

        return data_normal, data_hit, count, count_hit
