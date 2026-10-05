"""
session.py -- RenderSession: the mutable interactive state for
primeatlas/visualization/shared/renderer.py's `_run_visualization` that is common to
every viz-mode -- N, playback, scrub, camera, the HUD snapshot, buffer extension, the
bidirectional sliding range window and the background seek -- as ONE object with
methods instead of separate closures each capturing its own dict. Everything
mode-specific lives in the active mode object (`self.mode`, see shared/mode.py and
mode_registry.py), which the session delegates rebuilds, HUD colors and
mode-specific navigation to. Unit-tested without GL; the GLFW/moderngl main loop
itself cannot run headless.

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
genuinely GL-bound (ctx.buffer(), ctx.texture(), vbo.write()) are done by
_run_visualization with this class's return values, same convention as
draw_primitives.py/hud_text.py/playback.py. This is what makes every method here
unit-testable in a headless sandbox with no GPU/display.

Self-contained sys.path bootstrap (mirrors renderer.py's own -- see that
file's module docstring for the full "why plain-script-path" explanation):
needed so the primeatlas.* imports below work whether this module is
imported after renderer.py has already run its own bootstrap, or on its
own (e.g. directly from a test).
"""

import json
import os
import sys
import threading
import time

import numpy as np

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_PRIME_SIEVE_DIR = os.path.join(_REPO_ROOT, "prime_sieve")
if _PRIME_SIEVE_DIR not in sys.path:
    sys.path.insert(0, _PRIME_SIEVE_DIR)

from primeatlas.visualization.shared.draw_primitives import zoom_to_point, fit_zoom_for_viewport
from primeatlas.visualization.shared.playback import (
    clamp_tempo_ms,
    arrow_scrub_delta,
    can_start_playback,
    clamp_scrub_n,
    should_extend_buffer,
    next_buffer_ceiling,
    tick_next_n,
)
from primeatlas.visualization.shared.hud_text import compose_hud_canvas_lines, rasterize_hud_text
from primeatlas.visualization.shared.sources import load_archive, load_archive_before
from primeatlas.visualization.mode_registry import MODES

# Internal-only search stride for a background seek (see
# start_background_seek/_effective_chunk_size): the SEARCH crawls in chunks of the app's
# --max-load-count default (renderer.py) while RENDERING stays at the configured,
# possibly much smaller, chunk_size. Not a user-facing knob: it only affects how many
# chunks a seek's internal crawl loads, never what is rendered.
_SEEK_STRIDE_CHUNK_SIZE = 2_000_000


class RenderSession:
    """Owns every piece of mode-independent state _run_visualization's interactive
    part (camera, playback, HUD snapshot, buffer extension, sliding window,
    background seek) reads or writes, plus the pure state-transition logic, and the
    active viz-mode object (`self.mode`). See this module's docstring for the scope
    boundary and why nothing here touches GL directly.

    Construct with everything _run_visualization has resolved after its
    --load-range handling: a concrete `primes` array, the initial `n`/`ceiling`, the
    range-mode fields, the modes' own launch-time config (tracked primes/auto-orbit/
    window families for rings; the pattern settings for line), and the launch-time
    buffer-extension parameters."""

    def __init__(self, *, primes, n, ceiling, range_mode, range_primes, range_step,
                 max_radius, tempo_ms, buffer_margin, can_extend_buffer, portal_folder,
                 track_primes=(), auto_orbit=False, enabled_ids=frozenset(), theta=0.5,
                 law_mode="sliding", viz_mode="rings", pattern_offsets=None,
                 pattern_step_mode="manual", pattern_stop_on_match=False,
                 line_axis_curved=False, range_load_from=None, range_load_to=None,
                 chunk_size=None, sliding_enabled=False, **extra_mode_config):
        # Prime data / sequencing.
        self.primes = primes
        self.n = n
        self.ceiling = ceiling
        self.range_mode = range_mode
        # `range_primes` is a thin property (see below, right after __init__)
        # backed by `chunk_current` -- the triple-buffer sliding window's
        # middle/visible chunk (see chunk_back/chunk_current/chunk_forward
        # below). A property rather than a second attribute kept in sync, so
        # every read site (the modes' window bounds and rebuilds) always sees
        # the current chunk after a slide.
        self.chunk_current = range_primes
        self.range_step = range_step
        # View extent the camera fits to (recenter) and the rings mode lays out in.
        self.max_radius = max_radius

        # Playback.
        self.tempo_ms = clamp_tempo_ms(tempo_ms)
        self.playback_running = False

        # Camera.
        self.cam_pan = [0.0, 0.0]
        self.cam_zoom = 1.0
        self.cam_dragging = False
        self.cam_last_mouse = (0.0, 0.0)

        # Persistent HUD snapshot (written by the active mode's rebuild()).
        self.hud_n = n
        self.hud_count = 0
        self.hud_rebuild_ms = 0.0
        self.hud_lines = []

        # N-change bookkeeping the main loop reads every frame (the current N
        # itself is `self.n` above).
        self.n_advancing = False
        self.n_force_rebuild = False

        # LEFT/RIGHT scrub bookkeeping.
        self.scrub_held = 0
        self.scrub_was_running = False

        # Buffer-extension launch-time parameters + exhaustion flag.
        self.buffer_margin = buffer_margin
        self.can_extend_buffer = can_extend_buffer
        self.portal_folder = portal_folder
        self.extend_exhausted = False

        # Bidirectional sliding window over a --load-range: lets range mode
        # traverse the FULL logical [range_load_from, range_load_to) span a chunk at
        # a time instead of only the first `max_load_count` primes. `chunk_size` is
        # the caller's own field (configurable, never derived from `max_load_count`
        # or hardcoded here).
        #
        # sliding_enabled requires portal_folder (disk I/O to load a neighbor
        # chunk), a chunk_size AND a range_load_to -- without any of them (e.g. a
        # caller/test omitting these kwargs) this is False and the session keeps a
        # fixed slice, rather than raising.
        self.range_load_from = range_load_from
        self.range_load_to = range_load_to
        self.chunk_size = chunk_size
        self.sliding_enabled = bool(
            sliding_enabled and self.range_mode and portal_folder
            and chunk_size and range_load_to is not None
        )
        # None = "not attempted yet" (still needs a lazy load); an empty
        # array = "attempted, confirmed nothing there" (the TRUE edge of
        # range_load_from/range_load_to was reached, not just this
        # chunk's own edge) -- see _ensure_back_chunk/_ensure_forward_chunk's
        # own doc-comments for why this three-way state matters.
        self.chunk_back = None
        self.chunk_forward = None
        # Background-thread handles for an in-flight neighbor-chunk load (see
        # _ensure_forward_chunk/_ensure_back_chunk): None means no load is running.
        self._forward_load_thread = None
        self._back_load_thread = None
        # Dedup flags for the "already at the range's hard edge" message (see
        # _slide_forward/_slide_backward): a refused move past range_load_from/
        # range_load_to is reported once; reset as soon as either direction moves, so
        # returning to an edge reports again.
        self._forward_edge_reported = False
        self._back_edge_reported = False
        # Background-thread seek: with a small chunk_size and a sparse target (line
        # mode's next MATCH!), the next landing spot can be many chunk crossings
        # away, each a blocking disk load once the crawl outruns the one-chunk-deep
        # prefetch; running it on the GLFW main thread would freeze the window. See
        # start_background_seek (single in-flight seek, no cancellation, _seek_epoch
        # guards a late finisher against a reset() that already moved the session
        # on). None = idle.
        self._seek_thread = None
        self._seek_epoch = 0
        # Search-stride override for the CURRENT background seek (see
        # _effective_chunk_size/_recenter_render_chunks) -- None outside an active
        # seek, meaning every neighbor load uses the user's chunk_size.
        self._seek_stride = None
        self._seek_used_stride = False

        # The active viz-mode (see mode_registry.py and shared/mode.py). Each mode
        # reads its own keys from this launch-time config; it is kept so reset()
        # can construct the mode it returns to.
        self._mode_config = {
            "track_primes": track_primes, "auto_orbit": auto_orbit, "enabled_ids": enabled_ids,
            "theta": theta, "law_mode": law_mode,
            "pattern_offsets": pattern_offsets, "pattern_step_mode": pattern_step_mode,
            "pattern_stop_on_match": pattern_stop_on_match, "line_axis_curved": line_axis_curved,
            **extra_mode_config,
        }
        self.mode = MODES[viz_mode](self, self._mode_config)

        if self.sliding_enabled:
            # Construction itself blocks on both neighbors (there is
            # nothing on screen yet to hide this behind -- same cost as
            # a plain initial load), via the SAME wait helpers a
            # later swap uses when it genuinely races ahead of its own
            # background prefetch (see _wait_for_back_chunk/
            # _wait_for_forward_chunk).
            self._wait_for_back_chunk()
            self._wait_for_forward_chunk()
            self.mode.on_chunks_changed()

    @property
    def viz_mode(self):
        """Name of the active viz-mode (see mode_registry.MODES)."""
        return self.mode.name

    # ------------------------------------------------------------------
    # Bidirectional sliding window -- triple-buffer (chunk_back/
    # chunk_current/chunk_forward) over a --load-range, see __init__.
    # ------------------------------------------------------------------

    @property
    def range_primes(self):
        """Compatibility alias for `chunk_current` -- see __init__'s own
        doc-comment on `self.chunk_current` for why this is a live property
        rather than a second plain attribute."""
        return self.chunk_current

    @range_primes.setter
    def range_primes(self, value):
        self.chunk_current = value

    def _effective_chunk_size(self):
        """The chunk size to use for the NEXT neighbor load -- normally
        the user's own configured `chunk_size` (the render budget), but
        temporarily overridden to `_SEEK_STRIDE_CHUNK_SIZE` while a
        background seek (`start_background_seek`) is actively
        crawling. A small chunk_size (e.g. 500) means a
        sparse pattern's seek needs proportionally more real chunk
        crossings to reach its next match; searching with a much bigger
        stride instead cuts that crossing count down, at the cost of
        chunk_current temporarily holding far more than the user's own
        render budget WHILE the search is still running (never rendered
        mid-search -- see LineMode.rebuild's own "Searching..." HUD line,
        which is all that's shown then). `_recenter_render_chunks` reloads
        back down to the real `chunk_size` around the match once one is
        actually found, so what finally gets RENDERED still respects it.

        Records the override into `_seek_used_stride` the moment it's
        actually read (not just requested) -- `start_background_seek`'s own
        worker only pays for the recenter reload when this was genuinely
        used at least once, since a fast match found entirely within the
        already-loaded chunk_current never calls this at all."""
        if self._seek_stride is not None:
            self._seek_used_stride = True
            return self._seek_stride
        return self.chunk_size

    def _recenter_render_chunks(self, target_n):
        """Reloads chunk_back/chunk_current/chunk_forward at the user's
        own real `chunk_size` around `target_n`, undoing whatever bigger
        `_SEEK_STRIDE_CHUNK_SIZE` chunks the search that just found it
        grew to along the way (see _effective_chunk_size's own
        doc-comment) -- called ONLY when `_seek_used_stride` is True, right
        before a background seek commits a found match. `target_n` becomes
        chunk_current's own first element, same convention an ordinary
        _slide_forward/_slide_backward landing already establishes (see
        the sliding-window tests' own "chunk_current[0] == target"
        assertions) -- not centered, just consistent with what a real
        user's own next slide would have produced anyway, so nothing
        downstream needs to treat a stride-search landing any differently
        from an ordinary one.

        Runs synchronously (unlike _ensure_forward_chunk/_ensure_back_chunk's
        own background threads) -- this already executes ON a background
        seek thread, not the GLFW main thread, so blocking it further here
        costs nothing the search's own crawl wasn't already paying."""
        self.chunk_current = load_archive(
            self.portal_folder, self.range_load_to, from_n=target_n - 1, max_load_count=self.chunk_size,
        )
        lower_bound = self.range_load_from if self.range_load_from is not None else 0
        self.chunk_back = load_archive_before(
            self.portal_folder, target_n, self.chunk_size, not_below=lower_bound,
        )
        current_top = int(self.chunk_current[-1]) if len(self.chunk_current) else target_n
        if current_top >= self.range_load_to:
            self.chunk_forward = np.empty(0, dtype=np.uint64)
        else:
            self.chunk_forward = load_archive(
                self.portal_folder, self.range_load_to, from_n=current_top, max_load_count=self.chunk_size,
            )
        self.mode.on_chunks_changed()

    def _ensure_forward_chunk(self):
        """Kicks off loading `chunk_forward` IN THE BACKGROUND (a daemon
        thread) if it hasn't been attempted yet and no load is already in
        flight -- does NOT block. The renderer's GLFW main loop is single-threaded,
        so a synchronous load here would block the window (no frame draw, no input)
        for the whole disk read (multi-second at archive-scale `--slide-chunk-size`),
        while the swap itself, using an already-loaded `chunk_forward`, is instant.
        The background load has the whole time the user spends traversing the chunk
        just swapped in to finish. See _wait_for_forward_chunk for the case where a
        swap outruns the prefetch (a fast multi-chunk seek, or construction).

        Sets `chunk_forward` to a real empty array (not left as None) once
        `range_load_to` is confirmed reached -- that check is cheap
        (no I/O), so it stays synchronous -- so callers can tell "no more
        data ahead" apart from "still loading" (`_forward_load_thread is
        not None`) and "haven't even started yet" (both None) -- see
        __init__'s own doc-comment on the three-way chunk state."""
        if not self.sliding_enabled or self.chunk_forward is not None or self._forward_load_thread is not None:
            return
        if self.chunk_current is None or len(self.chunk_current) == 0:
            return
        current_top = int(self.chunk_current[-1])
        if current_top >= self.range_load_to:
            self.chunk_forward = np.empty(0, dtype=np.uint64)
            return
        load_count = self._effective_chunk_size()

        def _worker():
            result = load_archive(
                self.portal_folder, self.range_load_to, from_n=current_top,
                max_load_count=load_count,
            )
            self.chunk_forward = result
            self._forward_load_thread = None

        self._forward_load_thread = threading.Thread(target=_worker, daemon=True)
        self._forward_load_thread.start()

    def _ensure_back_chunk(self):
        """Background-thread counterpart to _ensure_forward_chunk above, via
        the new load_archive_before() -- see that method's own doc-comment
        for the full "why background, not synchronous" rationale, which
        applies identically here."""
        if not self.sliding_enabled or self.chunk_back is not None or self._back_load_thread is not None:
            return
        if self.chunk_current is None or len(self.chunk_current) == 0:
            return
        current_bottom = int(self.chunk_current[0])
        lower_bound = self.range_load_from if self.range_load_from is not None else 0
        if current_bottom <= lower_bound:
            self.chunk_back = np.empty(0, dtype=np.uint64)
            return
        load_count = self._effective_chunk_size()

        def _worker():
            result = load_archive_before(
                self.portal_folder, current_bottom, load_count, not_below=lower_bound,
            )
            self.chunk_back = result
            self._back_load_thread = None

        self._back_load_thread = threading.Thread(target=_worker, daemon=True)
        self._back_load_thread.start()

    def _wait_for_forward_chunk(self):
        """Ensures `chunk_forward` is actually READY (not just "a load was
        kicked off") before returning -- starts the background load if one
        hasn't even begun yet, then blocks on it if one is still running.
        This is the ONLY place that can still stall the main thread, and
        only for whatever's left of the load's own duration at the moment
        it's called -- zero wait in the common case where the background
        thread already finished during the time the user spent traversing
        the chunk that's about to be swapped out.

        Prints a line whenever it actually had to wait (a long traversal that
        outruns the one-chunk-deep prefetch, e.g. a multi-chunk seek or Ctrl-scrub
        back toward range_load_from, waits on EVERY swap and would otherwise look
        like a hang) -- silent in the already-prefetched case."""
        self._ensure_forward_chunk()
        thread = self._forward_load_thread
        if thread is not None:
            t0 = time.perf_counter()
            thread.join()
            print(f"Sliding window: waited {time.perf_counter() - t0:.2f}s for the next chunk "
                  f"forward (moving faster than the background prefetch can keep up)")

    def _wait_for_back_chunk(self):
        """Mirror of _wait_for_forward_chunk above."""
        self._ensure_back_chunk()
        thread = self._back_load_thread
        if thread is not None:
            t0 = time.perf_counter()
            thread.join()
            print(f"Sliding window: waited {time.perf_counter() - t0:.2f}s for the next chunk "
                  f"back (moving faster than the background prefetch can keep up)")

    def _slide_forward(self):
        """Crosses `chunk_current`'s own upper edge: the visible chunk
        becomes `chunk_back`, the (normally already-preloaded, see
        _wait_for_forward_chunk above) `chunk_forward` becomes the new
        visible `chunk_current`, and a fresh `chunk_forward` load is kicked
        off in the background right after (swap, not reload). Returns
        False (no-op) when there's genuinely nothing further ahead
        (`range_load_to` already reached) or sliding isn't enabled -- the
        caller's own edge-reached handling (next_wheel_n's `n`-unchanged
        convention) is unaffected either way.

        Prints an explicit message the first time it refuses to move
        because `range_load_to` is reached -- deduped via
        `_forward_edge_reported` so holding a key at the edge doesn't print
        once per frame; reset as soon as EITHER direction moves, so leaving and
        later returning to an edge reports again. Also sets `n_force_rebuild`
        the first time this fires: N staying unchanged at an edge means the main
        loop's `session.n != last_n` rebuild gate (renderer.py) never fires, and
        the mode's rebuild is the only place that refreshes `hud_lines` (line mode's edge_lines),
        so without it the HUD would not show the edge message."""
        if not self.sliding_enabled:
            return False
        self._wait_for_forward_chunk()
        if self.chunk_forward is None or len(self.chunk_forward) == 0:
            if not self._forward_edge_reported:
                print(f"Sliding window: already at the range's own TO edge "
                      f"({self.range_load_to:,}) -- cannot go further forward without "
                      f"exceeding --load-range")
                self._forward_edge_reported = True
                self.n_force_rebuild = True
            return False
        self.chunk_back = self.chunk_current
        self.chunk_current = self.chunk_forward
        self.chunk_forward = None
        self._ensure_forward_chunk()
        self.mode.on_chunks_changed()
        self._forward_edge_reported = False
        self._back_edge_reported = False
        return True

    def _slide_backward(self):
        """Mirror image of _slide_forward -- crosses `chunk_current`'s own
        lower edge. See that method's own doc-comment for the edge-message
        dedup rationale (identical here, just for `range_load_from`)."""
        if not self.sliding_enabled:
            return False
        self._wait_for_back_chunk()
        if self.chunk_back is None or len(self.chunk_back) == 0:
            if not self._back_edge_reported:
                print(f"Sliding window: already at the range's own FROM edge "
                      f"({self.range_load_from:,}) -- cannot go further backward without "
                      f"exceeding --load-range")
                self._back_edge_reported = True
                self.n_force_rebuild = True
            return False
        self.chunk_forward = self.chunk_current
        self.chunk_current = self.chunk_back
        self.chunk_back = None
        self._ensure_back_chunk()
        self.mode.on_chunks_changed()
        self._forward_edge_reported = False
        self._back_edge_reported = False
        return True

    def start_background_seek(self, search, is_tick, not_found_message):
        """Runs `search()` -- a callable returning (final_n, found) -- on a
        background thread instead of blocking the GLFW main thread, then commits
        `final_n` when found. Used by modes whose seek can cross many sliding-window
        chunks (each a disk load), i.e. line mode's pattern seek.

        No-ops if a seek is already in flight (`self._seek_thread is not None`):
        navigation input while one runs is ignored rather than starting a second
        one, since chunk_back/chunk_current/chunk_forward and their background-load
        threads assume a SINGLE owner (no locking), and two seeks racing through
        _slide_forward/_slide_backward could corrupt that state. Consequently,
        reversing direction mid-search does nothing until the search resolves;
        `search` must always terminate, and true cancellation would need a
        cooperative abort check inside it.

        `is_tick` selects a playback tick's extra not-found behavior (stop playback +
        print `not_found_message`; the tick returns immediately, so the main loop
        cannot react to a return value) versus a navigation key's silent
        no-op-on-miss.

        `self._seek_epoch` is captured at kickoff and re-checked right
        before the worker commits anything: reset() bumps this counter, so
        a seek that finishes AFTER a reset() happened silently discards
        its now-stale result instead of clobbering the fresh session state
        reset() already moved on to."""
        if self._seek_thread is not None:
            return
        epoch = self._seek_epoch
        self.n_force_rebuild = True  # shows the mode's "Searching..." HUD line this frame

        def _worker():
            # try/except/finally around the WHOLE body: an exception anywhere in
            # the search's crawl (a disk load, load_archive/load_archive_before,
            # _slide_forward/_slide_backward, ...) must still free `_seek_thread`,
            # otherwise the "a seek is already running" guard above would make
            # every later navigation a silent no-op in both directions. The
            # traceback print makes such a failure diagnosable.
            self._seek_stride = max(self.chunk_size, _SEEK_STRIDE_CHUNK_SIZE)
            self._seek_used_stride = False
            try:
                new_n, found = search()
                if self._seek_epoch == epoch:
                    if found:
                        if self._seek_used_stride:
                            # The search grew chunk_current/back/forward
                            # past the user's own chunk_size along the way
                            # (see _effective_chunk_size's own doc-comment)
                            # -- shrink back down to it now that a real
                            # match is actually being committed, so what
                            # gets RENDERED still respects that budget.
                            self._recenter_render_chunks(new_n)
                        self.n = new_n
                        self.n_advancing = True
                    elif is_tick:
                        self.playback_running = False
                        print(not_found_message)
                    self.n_force_rebuild = True
            except Exception:
                import traceback
                print("Pattern search failed with an unexpected error (navigation is still usable -- "
                      "see the traceback below):")
                traceback.print_exc()
            finally:
                self._seek_stride = None
                self._seek_thread = None

        self._seek_thread = threading.Thread(target=_worker, daemon=True)
        self._seek_thread.start()

    # ------------------------------------------------------------------
    # Camera -- the caller reads `viewport`/`cursor` from glfw itself (see
    # zoom_to_point's docstring for the effective-pan/state-pan conversion).
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
        last known position while `cam_dragging` is True."""
        lx, ly = self.cam_last_mouse
        if self.cam_dragging:
            self.cam_pan[0] += x - lx
            self.cam_pan[1] += y - ly
        self.cam_last_mouse = (x, y)

    def screen_to_world(self, x, y, viewport):
        """Inverse of the shaders' camera transform screen = world * zoom + pan (with
        the viewport-center offset on top of `cam_pan`)."""
        width, height = viewport
        return ((x - self.cam_pan[0] - width / 2) / self.cam_zoom,
                (y - self.cam_pan[1] - height / 2) / self.cam_zoom)

    def click(self, x, y, viewport):
        """A left click without a drag at screen position (x, y): forwarded to the
        active mode in world coordinates; a handled click forces a rebuild."""
        wx, wy = self.screen_to_world(x, y, viewport)
        if self.mode.click(wx, wy, 1.0 / self.cam_zoom):
            self.n_force_rebuild = True
            return True
        return False

    def key(self, name):
        """A key the renderer forwards by name (see VizMode.key); a handled key forces
        a rebuild."""
        if self.mode.key(name):
            self.n_force_rebuild = True
            return True
        return False

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
    # Playback / tempo -- Space, ] / [ / - keys, and the main loop's
    # playback tick.
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
        if self._may_start_playback():
            self.playback_running = True
            return None
        return "Playback: N is already at the loaded ceiling -- nothing left to advance to"

    def _may_start_playback(self):
        """can_start_playback, unless the active mode has no prime ceiling."""
        return not self.mode.uses_prime_ceiling or can_start_playback(self.n, self.range_mode, self.ceiling)

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

    def tick(self):
        """One playback tick, called once the main loop's own tempo_ms
        elapsed-time gate fires. The active mode may handle it itself (line
        mode's wheel jump, see LineMode.tick); otherwise ports tick_next_n,
        followed by the mode's clamp. Returns True if playback just stopped
        (N reached the ceiling, or the mode reported a stop), False if
        `self.n` advanced (and `self.n_advancing` was set for the caller's own
        N-change/rebuild branch to see)."""
        handled = self.mode.tick()
        if handled is not None:
            return handled
        new_n, should_stop = tick_next_n(self.n, self.range_mode, self.ceiling, self.range_step)
        if not should_stop:
            clamped = self.mode.clamp_n(new_n)
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
    # N navigation -- Up/Down/PageUp/PageDown, Left/Right (scrub), R (reset).
    # ------------------------------------------------------------------

    def bump_n(self, delta):
        """Ports the Up/Down/PageUp/PageDown branch: `self.n + delta`,
        floored at 0, UNCLAMPED at the ceiling (deliberately -- see
        clamp_scrub_n's own doc-comment for why only the scrub keys are
        capped, not these), then the mode's clamp. The active mode may handle
        the step itself instead (see LineMode.bump_n)."""
        if self.mode.bump_n(delta):
            return
        self.n = max(0, self.n + delta)
        self.n = self.mode.clamp_n(self.n)

    def scrub_advance(self, is_right, ctrl_held, is_first_press):
        """Ports the LEFT/RIGHT PRESS/REPEAT branch: on the FIRST press of
        a hold-sequence (`is_first_press=True`), pauses playback if it was
        running and remembers to resume it later.

        The active mode may handle the step itself (see LineMode.scrub).
        Otherwise, moves `self.n` by arrow_scrub_delta's step, clamped to the
        ceiling in sequential mode (clamp_scrub_n) so a long hold can never run
        N so far past it that nothing can resume playback afterward, then the
        mode's clamp."""
        if is_first_press:
            if self.scrub_held == 0 and self.playback_running:
                self.scrub_was_running = True
                self.playback_running = False
            self.scrub_held += 1
        if self.mode.scrub(is_right, ctrl_held):
            return
        delta = arrow_scrub_delta(is_right, ctrl_held)
        self.n = clamp_scrub_n(self.n + delta, self.range_mode, self.ceiling)
        self.n = self.mode.clamp_n(self.n)

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
            if self._may_start_playback():
                self.playback_running = True
                return None, True
            return "Playback: N is already at the loaded ceiling -- nothing left to advance to", True
        return None, False

    def reset(self):
        """Ports the KEY_R branch exactly: stop playback, N=1, and fall back to
        sequential mode even if --load-range was active at launch (mirrors the
        HTML's own resetSequential()). The view switches to the active mode's
        `reset_mode` (the rings and line modes return to a fresh rings mode; a mode
        with reset_mode None stays itself), whose own reset_state() then runs (rings:
        drops Track P and re-enables auto-orbit).

        Bumps `_seek_epoch` so a background seek (see start_background_seek's
        own doc-comment) still in flight from BEFORE this reset() call
        discards its result instead of clobbering self.n/playback_running with
        a stale answer to a question this reset already moved past -- the seek
        thread itself isn't cancelled, it just becomes a no-op once it
        finishes."""
        self.playback_running = False
        self.range_mode = False
        self.n = 1
        self.n_force_rebuild = True
        self._seek_epoch += 1
        target = self.mode.reset_mode or self.mode.name
        if self.mode.name != target:
            self.mode = MODES[target](self, self._mode_config)
        self.mode.reset_state()

    # ------------------------------------------------------------------
    # Buffer extension.
    # ------------------------------------------------------------------

    def extend_buffer_if_needed(self):
        """Extends the loaded prime buffer once N nears its ceiling (rationale on
        should_extend_buffer/next_buffer_ceiling in playback.py).
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
    # Rebuild -- delegated to the active mode; everything except the GL buffer
    # uploads (ctx.buffer() x2), which the caller does with the return value.
    # ------------------------------------------------------------------

    def rebuild(self, n_value, prev_ring_count=None, advancing=False, audio=None):
        """Recomputes the active mode's N-dependent state for `n_value` (see
        VizMode.rebuild). Returns (data_normal, data_hit, count, count_hit)."""
        return self.mode.rebuild(n_value, prev_ring_count=prev_ring_count, advancing=advancing, audio=audio)

    # ------------------------------------------------------------------
    # HUD refresh -- the HUD_STATE line plus the pure part of the HUD texture
    # (everything before ctx.texture()/hud_quad_vbo.write()), computed together
    # since every caller needs both.
    # ------------------------------------------------------------------

    def refresh_hud(self, hud_font_size):
        """Returns (json_line, rgba_or_None, width, height): `json_line` is
        the "HUD_STATE:..." line (the caller prints it); `rgba`/`width`/`height` are
        the HUD texture's pure computation (None/0/0 if Pillow isn't installed or
        there's nothing to draw) -- the caller uploads it to a GL texture and
        rewrites its quad buffer."""
        payload = {
            "n": self.hud_n,
            "count": self.hud_count,
            "rebuild_ms": self.hud_rebuild_ms,
            "lines": self.hud_lines,
            "running": self.playback_running,
            "tempo_ms": self.tempo_ms,
        }
        json_line = "HUD_STATE:" + json.dumps(payload)
        if not self.mode.draws_hud:
            return json_line, None, 0, 0

        canvas_lines = compose_hud_canvas_lines(
            self.hud_n, self.hud_count, self.hud_lines, self.playback_running, self.tempo_ms,
            count_label=self.mode.count_label,
        )
        line_colors = self.mode.hud_line_colors(canvas_lines)
        rgba = rasterize_hud_text(canvas_lines, font_size=hud_font_size, line_colors=line_colors)
        if rgba is None:
            return json_line, None, 0, 0
        height, width = rgba.shape[0], rgba.shape[1]
        return json_line, rgba, width, height
