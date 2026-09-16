"""
renderer.py -- GPU renderer for the Structural Sieve "drum" (rings + hit
teeth, see primeatlas/ring_geometry.py). Standalone runnable module (see
this package's own __init__.py docstring for why it stays a separate
process rather than being imported into the main Tkinter app): launched as
a subprocess by primeatlas/rings_tab.py.

Structural Sieve's browser/Canvas 2D visualization (see
js/render/DrumRenderer.js in the RelationalMathematics repo) has a
practical ring-count ceiling bounded by what one JS thread can redraw at
interactive frame rates, plus what a browser tab can hold in memory -- see
StructuralSieveApp.js's own "hardware-calibrated auto-track-range" feature,
added specifically because that ceiling is real. PrimeAtlas already has
(a) a magazyn of pre-generated primes far beyond what any in-browser sieve
would attempt, and (b) real GPU hardware, already exercised for actual
sieve marking (see this project's cudasieve/marking_*_poc history).

Confirmed on real hardware: 20,000,000 rings loaded in 0.27s, N-change
rebuild ~1.3s, pan/zoom held 50+ fps even with a fast scroll wheel at the
full 20M-ring view. This module is a ported prototype rather than a
rewrite -- the only differences from the standalone prototype version are
import paths (`primeatlas.ring_geometry` instead of a bare
`ring_geometry`) and `load_magazyn`'s repo-root autodetection (derived
from this file's own location instead of a `--primeatlas-root` CLI flag,
since the file lives inside the repo it needs to reach into).

Deliberately decoupled from two things this module is NOT responsible for:

  1. Prime GENERATION throughput -- already solved/benchmarked elsewhere in
     this project (04_C_skaner, primesieve integration, etc.). `--source`
     picks where the ring array comes from:
       - synthetic: directly specify a ring COUNT with an arbitrary strictly
         increasing int64 array (no real primality needed at all) -- the
         purest form of the rendering stress test, decoupled entirely from
         how expensive real primes would be to produce at that count.
       - sieve: a real (small-to-moderate scale) sieve of Eratosthenes up to
         --upto, for a real-looking demo.
       - magazyn: reads real floors from an existing PrimeAtlas portal folder
         via primeatlas/storage.py + prime_sieve_v1.read_prime_window, up to
         --upto: real floor enumeration via storage.list_pietra(), reads
         batched (not one unbounded pass), with an optional progress_callback
         -- the real per-load wall-clock ceiling at extreme N is still
         unmeasured against a real magazyn, see load_magazyn's own docstring
         for what to expect. The loaded buffer also TRAVELS with N during
         playback/scrubbing (extend_buffer_if_needed, called once per frame
         from run()): once N closes to within one launch-time margin's worth
         of the loaded ceiling, another chunk is fetched automatically, so
         the sequential-mode "ceiling wall" only actually stops anything
         once the magazyn itself has no more data past that point -- not
         merely because the ORIGINAL --upto load happened to stop somewhere
         short of it.

  2. Whether the resulting picture is mathematically interesting at huge N --
     a separate, later question once the rendering-feasibility question this
     module answers is settled.

Architecture (the part that was actually tested):

  - `primes` (ascending int64 numpy array) is loaded/generated ONCE at
    startup.
  - ring_geometry.ring_positions() recomputes x/y/phase/is_hit ONLY when N
    changes (Up/Down/PageUp/PageDown -- see #advance_n), never every frame:
    test_ring_geometry.py's own benchmark measured roughly 20M rings/second
    on plain CPU numpy for this recompute -- fine for "user pressed a key",
    far too slow to redo unconditionally at 60fps at tens of millions of
    rings.
  - Panning and zooming the CAMERA never touch that array: they only change a
    2D affine transform (offset + scale) applied inside the vertex shader via
    a uniform, so camera movement stays GPU-cheap regardless of ring count.
    This split -- CPU recomputes geometry on N-change, GPU alone handles
    camera every frame -- is what keeps pan/zoom frame rate independent of
    ring count.
  - One `GL_POINTS` draw call per frame (point size set in the vertex shader,
    a soft circular alpha mask in the fragment shader) -- avoids the
    triangle-fan vertex multiplication a "real" circle mesh per ring would
    cost.
  - FPS and ring count are both written to the window title every frame.

Usage -- run as a PLAIN SCRIPT PATH, not `python -m primeatlas.ring_viz.renderer`:
    pip install moderngl glfw numpy
    pip install Pillow   # optional -- enables the on-canvas HUD text overlay;
                          # everything else in this module works fine without
                          # it, see _PIL_AVAILABLE.
    python primeatlas/ring_viz/renderer.py --source synthetic --count 20000000
    python primeatlas/ring_viz/renderer.py --source sieve --upto 5000000
    python primeatlas/ring_viz/renderer.py --source magazyn \
        --portal-folder "D:\\...\\PORTAL" --upto 50000000000

    Why plain-script-path and not `-m`: `python -m primeatlas.ring_viz.renderer`
    makes Python import the `primeatlas` package FIRST (running
    `primeatlas/__init__.py`, which transitively imports `.manifest`, which
    does a bare `import window_sharding`) before this file's own body -- and
    therefore before the sys.path fix a few lines below ever runs. Run as a
    plain script path instead and that fix executes top-to-bottom before the
    `from primeatlas.ring_geometry import ...` line below is reached, exactly
    like prime_atlas_v1.py's own top-level `sys.path.insert(0, ".../prime_sieve")`
    (see that file) already has to do for the very same reason. If a
    subprocess launcher (rings_tab.py) wants `-m` invocation instead, it must
    set `PYTHONPATH` to include the repo root's `prime_sieve` directory itself
    before spawning the subprocess.

Controls:
    drag              pan
    scroll            zoom to cursor
    middle-click      recenter/fit -- resets pan to dead center and zoom to
                      fit_zoom_for_viewport() (fills the window's full
                      height, or width if the window is narrower than tall),
                      undoing any amount of prior scroll/drag in one action
    F11               toggle fullscreen -- ALSO re-fits zoom/pan the same
                      way as middle-click above whenever the toggle actually
                      changes the viewport size (both fullscreen->windowed
                      and windowed->fullscreen), since the old zoom was only
                      ever correct for the window size it was set at
    Up / Down         change N by +/- --n-step (recomputes ring buffer)
    PageUp / PageDown change N by +/- 100 * --n-step (coarse jump)
    Left / Right      scrub N by -/+1 (-/+10 with Ctrl held) -- if playback
                      is RUNNING, pressing either arrow pauses it for the
                      duration of the key press and resumes it automatically
                      the moment every held scrub key is released; if
                      playback is already STOPPED, scrubbing just moves N
                      and leaves it stopped
    Space             start/stop playback -- auto-advances N by exactly 1 per
                      tick (independent of --n-step), same as the HTML's own
                      Start/Stop button
    ] / [             faster / slower playback (+ / - also work as
                      aliases, in case ]/[ don't reach this window on a
                      given keyboard layout) -- multiplies the tempo
                      (ms/tick) by 0.8 / 1.25 each press (not a fixed ms
                      step: a flat +/-10ms was imperceptible at low tempos
                      and negligible at high ones), clamped to [30, 2000],
                      printed to the console each press so the change is
                      confirmable even when it's visually subtle
    R                 reset -- stops playback, N=1, clears Track P, re-enables
                      auto-orbit, and drops back to sequential mode even if
                      --load-range was active (mirrors the HTML's own Reset
                      button, which always calls resetSequential())
    Esc               quit

HUD: current N, ring count, playback status, factors of N, tracked/LCM
block, and any active window's range (Bertrand/Legendre/General Law) are
drawn directly in this window's top-left corner -- ports DrumRenderer's own
#drawHud text overlay, previously only reachable via the console pane or
rings_tab.py's side panel (see hud_lines_for_n's own doc-comment for that
history). Needs Pillow; degrades to "no on-canvas text" (everything else
unaffected) if it isn't installed -- see _PIL_AVAILABLE. Size it with
--hud-font-size (pixels, default 35) if the default is too small on your
screen/resolution -- see rasterize_hud_text's own docstring.

--hit-point-size: independent point size for rings ON the vertical
reference line (real divisors of N), separate from --point-size for every
other ring -- defaults to 40.0, or falls back to --point-size's own value
if you pass an explicit empty override some other way.
"""

import argparse
import os
import queue
import sys
import time

# Allow `python primeatlas/ring_viz/renderer.py` (not just `python -m
# primeatlas.ring_viz.renderer`) to work by ensuring the repo root is on
# sys.path before the primeatlas.* imports below -- the subprocess launcher
# in rings_tab.py is free to pick either invocation style.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# primeatlas/__init__.py transitively imports .manifest, which does a bare
# `import window_sharding` (see storage.py's own module docstring for why
# prime_sieve_v1.py/window_sharding.py live outside this package as separate
# top-level modules) -- so `prime_sieve` must be on sys.path before ANY
# `primeatlas.*` import below, not just inside load_magazyn() where the
# actual prime_sieve_v1 usage lives: a bare `from primeatlas.ring_geometry
# import ...` fails without this, even though ring_geometry.py itself has
# no such dependency.
_PRIME_SIEVE_DIR = os.path.join(_REPO_ROOT, "prime_sieve")
if _PRIME_SIEVE_DIR not in sys.path:
    sys.path.insert(0, _PRIME_SIEVE_DIR)

# ring_geometry's other functions (ring_positions, compute_highlight_
# colors, compute_tracked_colors, tracked_ring_mask, legendre_level_at,
# general_law_window_bounds, tracked_resonance_state, format_big,
# resonance_log_lines, format_log_panel_text, window_anchor_primes,
# cyclic_window_anchor_at, window_label_colors, to_prime_array) are used
# through geometry_draw.py/hud.py/session.py instead of directly here --
# only parse_big_int (--upto/--load-range/main()'s own CLI parsing) is
# still used directly in this file.
from primeatlas.ring_geometry import parse_big_int

# The guarded Pillow import (and rasterize_hud_text, the only function that
# actually touches Image/ImageDraw/ImageFont) lives in hud.py, since Pillow
# is entirely a HUD-text-rendering concern. _PIL_AVAILABLE itself is not
# referenced directly here either -- gl_setup.py's own setup_gl_resources()
# owns the "allocate the on-canvas HUD texture program/buffers, or don't"
# decision.


# ---------------------------------------------------------------------------
# Data sources -- see module docstring point 1 for why these are kept
# interchangeable and independent of the rendering path below.
# ---------------------------------------------------------------------------

# load_synthetic/load_sieve/load_magazyn live in sources.py; they have no
# GL-context dependency (unlike everything below this point in the file).
# Re-imported under their original names so every call site in
# _run_visualization/main() below is unchanged.
from primeatlas.ring_viz.sources import load_synthetic, load_sieve, load_magazyn


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

# The GLSL source strings live in shaders.py, as pure data with no
# GL-context dependency. Every ctx.program(...) call that uses them lives in
# gl_setup.py's own setup_gl_resources() -- nothing in this file references
# the raw shader strings directly.


# build_vertex_data through initial_n_for_source live in geometry_draw.py;
# none of them touch GL state. Most of this module's own call sites for
# these (build_vertex_data, resolve_effective_track_primes,
# build_tracked_outline_draws, decay_flash, flash_overlay_rgba,
# resonance_is_active, zoom_to_point, fit_zoom_for_viewport,
# split_hit_normal_vertex_data, tracked_outline_color, center_marker_
# triangle_offsets, the _FLASH_*_RGB constants) live in session.rebuild/
# session.on_scroll/session.recenter/session.resonance_flash_color/etc;
# unit_circle_vertices lives in gl_setup.py's own setup_gl_resources() --
# only the handful still called directly from _run_visualization/main() are
# re-imported here; unitTests/test_ring_viz_renderer.py imports the rest
# directly from geometry_draw.py.
from primeatlas.ring_viz.geometry_draw import (
    load_prime_range_slice,
    marker_device_scale,
    build_center_marker_vertex_data,
    build_flash_quad_vertex_data,
    _FIT_MARGIN,
    initial_n_for_source,
)


# ---------------------------------------------------------------------------
# Playback controls (Space to start/stop, ]/[ for tempo, R to reset) and
# auto-orbit's cycling behavior. Ports StructuralSieveApp's #toggleRunning /
# #stop / #tick / #setTempo / #advanceAutoOrbit / (the resetSequential()-
# calling half of) #reset.
# ---------------------------------------------------------------------------

# All of the pure playback-timing functions (clamp_tempo_ms,
# arrow_scrub_delta, can_start_playback, clamp_scrub_n, should_extend_
# buffer, next_buffer_ceiling, tick_next_n, update_resonance_log,
# advance_auto_orbit, and the _TEMPO_MS_MIN/MAX and _ARROW_SCRUB_STEP*
# constants) live in playback.py and RenderSession's own methods; none of
# them touch GL state. Only _TEMPO_MS_DEFAULT (main()'s --tempo-ms argparse
# default) and _RANGE_STEP_ORBIT_TICKS (this file's own launch-time
# range_step computation, run before RenderSession is constructed) are
# still referenced directly here.
from primeatlas.ring_viz.playback import (
    _TEMPO_MS_DEFAULT,
    _RANGE_STEP_ORBIT_TICKS,
)


# hud_lines_for_n through emit_audio_tick live in hud.py; none of them touch
# GL state (Pillow rasterization included -- see that module's own
# docstring for why the guarded PIL import lives there too). Their call
# sites live in RenderSession.rebuild/RenderSession.refresh_hud -- only
# _HUD_FONT_SIZE_DEFAULT (main()'s --hud-font-size argparse default) and
# hud_quad_vertex_data (still called directly by _apply_hud_refresh's own
# GL upload) are still referenced here; unitTests/test_ring_viz_renderer.py
# imports the rest directly from hud.py.
from primeatlas.ring_viz.hud import (
    _HUD_FONT_SIZE_DEFAULT,
    hud_quad_vertex_data,
)


# start_stdin_command_reader lives in stdin_commands.py; re-imported under
# its original name so run()'s own --pipe-stdin-commands call site is
# unchanged.
from primeatlas.ring_viz.stdin_commands import start_stdin_command_reader

# RenderSession consolidates _run_visualization's own dozen
# closure-captured state dicts (camera, playback, orbit, flash, HUD, scrub,
# buffer-extension, tracked/range fields) into one object with methods,
# unit-tested in isolation in session.py.
from primeatlas.ring_viz.session import RenderSession

# Window/context/shader-program/VAO/VBO creation lives in one GLResources
# instance built by setup_gl_resources(), instead of a ~16-local-variable
# block inline in _run_visualization.
from primeatlas.ring_viz.gl_setup import setup_gl_resources


def run(args):
    from primeatlas.ring_viz.audio import Instruments, LiveAudio
    audio = None
    try:
        if getattr(args, 'audio', False):
            audio = LiveAudio(Instruments(args.sound_low, args.sound_prime, args.sound_lcm))
            if not audio.start():
                print(f'AUDIO: unavailable: {audio.error}. Install sounddevice in this Python '
                      'or check the output device; visualization continues without sound.', flush=True)
                audio.close()
                audio = None
            else:
                print('AUDIO: enabled (8 voices maximum; sound on advancing ticks)', flush=True)
        return _run_visualization(args, audio)
    finally:
        if audio is not None:
            audio.close()


def _run_visualization(args, audio=None):
    import glfw
    import moderngl

    # Window/context/every shader program/VAO/VBO live on one GLResources
    # instance, `gl`, built by setup_gl_resources(). Every reference to
    # those objects below is `gl.xxx`.
    gl = setup_gl_resources(args)

    # For --source sieve/magazyn, the view OPENS exactly at N=args.upto (see
    # initial_n_for_source's own docstring) -- but sequential playback needs
    # somewhere to advance TO, and loading only up to that exact N leaves
    # zero headroom: N would already equal the load ceiling on frame one, so
    # Space would silently refuse to start every time. `load_upto` pads
    # the underlying LOAD by a modest +5% (at least 1000) past the
    # requested N so there is room to play forward and actually see
    # auto-orbit cycle; the DISPLAY still opens at the user's exact
    # args.upto below (n = initial_n_for_source(..., args.upto, ...), not
    # load_upto) -- only the loaded prime array itself is padded.
    load_upto = args.upto
    if args.source in ("sieve", "magazyn"):
        load_upto = args.upto + max(1000, args.upto // 20)

    # For --source magazyn with an explicit --load-range, loading [0,
    # load_upto] in full before load_range's post-hoc slice runs is
    # infeasible once the requested range sits at a high floor, since every
    # floor below it
    # would be read first for nothing. Loading directly via `from_n=FROM`
    # instead reuses load_magazyn's own already-existing cheap floor-skip
    # (see that function's own `from_n` doc-comment) to jump straight to the
    # requested floor, capped by --max-load-count so an accidentally huge
    # span still can't stall the whole load (truncated from the top -- see
    # load_magazyn's own doc-comment on that point). `primes` IS the range
    # here already, so the load_range block further below (which still
    # handles synthetic/sieve the old, unbounded way) is told to skip its
    # own redundant re-slice via `magazyn_range_preload`.
    magazyn_range_preload = None
    if args.source == "magazyn" and args.load_range:
        magazyn_range_preload = tuple(parse_big_int(p) for p in args.load_range.split(","))

    print(f"Loading primes via --source={args.source} ...")
    t0 = time.perf_counter()
    if args.source == "synthetic":
        primes = load_synthetic(args.count)
    elif args.source == "sieve":
        primes = load_sieve(load_upto)
    elif args.source == "magazyn":
        if magazyn_range_preload is not None:
            preload_from, preload_to = magazyn_range_preload
            primes = load_magazyn(args.portal_folder, preload_to, from_n=preload_from,
                                   max_load_count=args.max_load_count)
        else:
            primes = load_magazyn(args.portal_folder, load_upto)
    else:
        raise ValueError(f"unknown --source {args.source!r}")
    t1 = time.perf_counter()
    print(f"Loaded {len(primes):,} values in {t1 - t0:.2f}s")

    n = initial_n_for_source(args.source, args.upto, primes)
    # See fit_zoom_for_viewport's own doc-comment for why this uses the
    # shared _FIT_MARGIN constant rather than a second, independent 0.45
    # literal -- it keeps "the view as it opens" and "the view after an
    # explicit re-fit (F11 / middle-click)" provably the same computation.
    max_radius = min(args.width, args.height) * _FIT_MARGIN

    # Window-highlight families enabled at launch time -- parsed once here
    # (not per-frame): "" -> empty set (see build_vertex_data's own
    # doc-comment). No live in-window toggle (would need on-screen UI this
    # raw GL window doesn't have) -- set via rings_tab.py's launch-time
    # checkboxes instead, same as N itself.
    enabled_ids = {f.strip() for f in args.windows.split(",") if f.strip()} if args.windows else set()
    theta = args.general_law_theta
    law_mode = args.general_law_mode

    # Track P -- parsed once here (not per-frame), same launch-time-only
    # convention as --windows above (no live in-window text field, see
    # rings_tab.py's own Track P field docstring for why). `--auto-orbit` is
    # accepted and stored for the playback loop to read; on its own it
    # suppresses the tracked/LCM HUD block below (mirrors the JS's own
    # #trackedResonanceState guard).
    track_primes = [int(p.strip()) for p in args.track_primes.split(",") if p.strip()] if args.track_primes else []
    auto_orbit = args.auto_orbit

    # Playback state -- ports #isRunning, #tempoMs,
    # #autoOrbitIndex/#autoOrbitCounter/#trackedPrimes (the auto-orbit
    # half). `ceiling` mirrors the JS's own PrimeDataSource ceiling check
    # inside #tick/#toggleRunning (sequential mode only -- range mode has no
    # ceiling, same as tick_next_n/can_start_playback's own `range_mode`
    # bypass).
    #
    # `ceiling` must be load_upto, not `int(primes[-1])` (the largest ACTUAL
    # prime found): the real boundary of trustworthy data is how far
    # loading went, not where the last prime happened to land (primes can
    # be sparse near the boundary, e.g. load_upto=100 with primes[-1]=97
    # would wrongly refuse 3 perfectly safe ticks). Using load_upto also
    # gives the load-time headroom padding above something real to advance
    # into instead of refusing on frame one.
    ceiling = load_upto if args.source in ("sieve", "magazyn") else (int(primes[-1]) if len(primes) else -1)

    # Reuses the same margin figure as load_upto's own launch-time pad just
    # above, instead of inventing a second, different margin concept.
    #
    # Scoped to --source magazyn only: synthetic/sieve are both bounded by
    # their own launch-time argument with nothing further to ever fetch
    # (see load_magazyn's own module-level docstring point 1) -- magazyn is
    # the one real, always-possibly-larger data source this module has (a
    # disk portal that can simply have more window files than were loaded
    # at launch). See extend_buffer_if_needed (below, near n_holder) for
    # the actual extension call.
    buffer_margin = max(1000, args.upto // 20)
    can_extend_buffer = args.source == "magazyn" and bool(args.portal_folder)
    # `extend_state["exhausted"]`, `tempo_ms`/`playback["running"]`,
    # `orbit_state`, and `cyclic_anchor_state` are RenderSession's own
    # fields (self.extend_exhausted, self.tempo_ms/playback_running,
    # self.orbit_*, self.cyclic_anchor_state), constructed further down
    # once `range_mode`/`range_primes`/`range_step`/`track_primes`/
    # `auto_orbit` below are all known -- see session.py's own
    # RenderSession docstring for the full field-by-field mapping.

    # Load Range -- ports #loadPrimeRange: switch
    # to a FIXED ring set (range_primes), independent of N from here on
    # (rebuild_buffer below uses it verbatim instead of `primes[primes <=
    # n_value]` whenever range_mode is True -- see load_prime_range_slice's
    # own doc-comment for why `primes` itself is the ceiling here, unlike
    # the JS's separate always-larger PrimeDataSource). Failures are
    # reported the same friendly way the JS's #loadPrimeRange does (a plain
    # printed line, this module's only "info" surface -- see
    # hud_lines_for_n's own doc-comment for why stdout and not a GL overlay)
    # rather than crashing the whole subprocess over a bad --load-range.
    range_mode = False
    range_primes = None
    # Range mode's per-tick N-advance, dynamically sized to the largest
    # currently-loaded prime once range_primes is known below; stays at
    # this default (1) for sequential mode and for a range that fails to
    # load at all -- see tick_next_n's own doc-comment for the full
    # rationale.
    range_step = 1
    if args.load_range:
        load_from, load_to = (parse_big_int(p) for p in args.load_range.split(","))
        try:
            if magazyn_range_preload is not None:
                # `primes` was already loaded directly as this exact (possibly
                # --max-load-count-truncated) range above -- re-slicing it
                # here would be redundant, and load_prime_range_slice's own
                # "does TO fit under what got loaded" check would wrongly
                # raise whenever truncation legitimately left primes[-1]
                # short of load_to.
                range_primes = primes
            else:
                range_primes = load_prime_range_slice(primes, load_from, load_to)
            range_mode = True
            n = 0  # mirrors the JS's own `this.#n = 0` on a successful range load
            range_count = len(range_primes)
            # Without this, playback would look frozen at a real
            # magazyn-floor-scale range, since a fixed step of 1 is
            # imperceptible against prime gaps of that size. See
            # tick_next_n's own doc-comment -- naturally settles back to `1`
            # at low floors (where a full orbit already fits inside
            # _RANGE_STEP_ORBIT_TICKS).
            if range_count:
                range_step = max(1, int(range_primes[-1]) // _RANGE_STEP_ORBIT_TICKS)
            # Auto-populate Track P with EVERY ring in the loaded range --
            # so the LCM/phase/to-resonance HUD reflects the whole set --
            # but only up to tracked_resonance_state's own cap
            # (max_tracked_for_exact_lcm's default, 500), same reasoning as
            # the JS's #maxTrackedForExactLcm: past that the exact BigInt
            # LCM of the whole set would be too slow to multiply even once.
            # Overwrites whatever --track-primes was set at launch, exactly
            # like the JS overwrites this.#trackedPrimes unconditionally on
            # a successful range load.
            if 0 < range_count <= 500:
                track_primes = [int(p) for p in range_primes]
                auto_orbit = False
                print(f"Range [{load_from:,}, {load_to:,}] loaded: {range_count:,} primes, all tracked")
            elif range_count and int(range_primes[-1]) < load_to:
                print(f"Range [{load_from:,}, {load_to:,}] capped at --max-load-count="
                      f"{args.max_load_count:,}: only [{load_from:,}, {int(range_primes[-1]):,}] "
                      f"loaded ({range_count:,} primes)")
            else:
                print(f"Range [{load_from:,}, {load_to:,}] loaded: {range_count:,} primes")
        except ValueError as e:
            print(f"Load Range failed: {e}")

    # Everything from here down operates on one RenderSession object instead
    # of a dozen separate closure-captured dicts (state/pan-zoom, playback,
    # orbit_state, cyclic_anchor_state, flash_state, outline_draws_holder,
    # resonance_log_state, hud_state, n_holder, scrub_state, extend_state)
    # plus bare track_primes/auto_orbit/range_mode/range_primes/range_step/
    # primes/ceiling locals mutated via `nonlocal`. `session.n` plays
    # n_holder["n"]'s old role; every GLFW callback and the main loop below
    # call session.* methods instead of mutating their own captured dict.
    # See session.py's own RenderSession docstring for the field-by-field
    # mapping to the old closures.
    session = RenderSession(
        primes=primes, n=n, ceiling=ceiling, range_mode=range_mode,
        range_primes=range_primes, range_step=range_step,
        track_primes=track_primes, auto_orbit=auto_orbit,
        enabled_ids=enabled_ids, theta=theta, law_mode=law_mode,
        max_radius=max_radius, tempo_ms=args.tempo_ms,
        buffer_margin=buffer_margin, can_extend_buffer=can_extend_buffer,
        portal_folder=args.portal_folder,
    )

    def _apply_hud_refresh():
        """Prints the HUD JSON snapshot and uploads a fresh on-canvas HUD
        texture, using session.refresh_hud()'s own pure computation for
        both (see that method's own doc-comment) -- only the actual GL
        upload (ctx.texture, hud_tex_holder release, hud_quad_vbo.write)
        stays here, since session.py has no GL dependency at all."""
        json_line, rgba, w, h = session.refresh_hud(args.hud_font_size)
        print(json_line)
        if gl.hud_quad_vao is None:
            return
        if gl.hud_tex_holder["tex"] is not None:
            gl.hud_tex_holder["tex"].release()
            gl.hud_tex_holder["tex"] = None
        if rgba is None:
            return
        tex = gl.ctx.texture((w, h), 4, rgba.tobytes())
        tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        gl.hud_tex_holder["tex"] = tex
        gl.hud_quad_vbo.write(hud_quad_vertex_data(w, h).tobytes())

    def rebuild_buffer(n_value, prev_ring_count=None, advancing=False):
        """GL-side half of session.rebuild(): uploads its returned vertex
        data into two fresh VBOs (see split_hit_normal_vertex_data's own
        doc-comment, in geometry_draw.py, for why there are two) and
        refreshes the HUD. Geometry/color recompute, the tracked/LCM HUD
        block, resonance log, tracked-outline draws, and flash triggers all
        live in session.rebuild itself."""
        data_normal, data_hit, count, count_hit = session.rebuild(
            n_value, prev_ring_count=prev_ring_count, advancing=advancing, audio=audio
        )
        normal_bytes = data_normal.tobytes()
        vbo_normal = gl.ctx.buffer(normal_bytes) if normal_bytes else gl.ctx.buffer(reserve=20)
        hit_bytes = data_hit.tobytes()
        vbo_hit = gl.ctx.buffer(hit_bytes) if hit_bytes else gl.ctx.buffer(reserve=20)
        _apply_hud_refresh()
        return vbo_normal, vbo_hit, count, count_hit

    vbo_normal, vbo_hit, ring_count, ring_count_hit = rebuild_buffer(session.n)
    vao_normal = gl.make_ring_vao(vbo_normal)
    vao_hit = gl.make_ring_vao(vbo_hit)

    def on_scroll(_window, _dx, dy):
        # session.cam_last_mouse already IS the cursor position this needs
        # (session.on_cursor_pos keeps it updated) -- this callback only
        # supplies the current viewport size, which session.py has no way
        # to read for itself (no GL/glfw dependency there by design). See
        # zoom_to_point's own docstring for the full before/after
        # explanation.
        width, height = glfw.get_framebuffer_size(gl.window)
        session.on_scroll(dy, session.cam_last_mouse, (width, height))

    def on_mouse_button(_window, button, action, _mods):
        if button == glfw.MOUSE_BUTTON_LEFT:
            session.set_dragging(action == glfw.PRESS)
        elif button == glfw.MOUSE_BUTTON_MIDDLE and action == glfw.PRESS:
            # See session.recenter's own doc-comment (shared with the F11
            # re-fit branch below, since both do the exact same thing).
            width, height = glfw.get_framebuffer_size(gl.window)
            session.recenter((width, height))

    def on_cursor_pos(_window, x, y):
        session.on_cursor_pos(x, y)

    def extend_buffer_if_needed():
        """Thin GL-free wrapper around session.extend_buffer_if_needed() --
        printing its returned message (if any) is the only thing left for
        this closure to do."""
        msg = session.extend_buffer_if_needed()
        if msg is not None:
            print(msg)

    # LEFT/RIGHT scrub state lives on `session` (scrub_held/
    # scrub_was_running) -- see session.scrub_advance/scrub_release's own
    # doc-comments for the held-count/was-running bookkeeping this used to
    # need a separate `scrub_state` dict for.
    from primeatlas.ring_viz.window_mode import FullscreenToggle
    fullscreen = FullscreenToggle(glfw, gl.window)
    print('F11: toggle fullscreen (auto-fits zoom to the new window size); '
          'middle-click: recenter/fit view; Esc: close visualization', flush=True)

    # Live pause/resume -- opt-in (see --pipe-stdin-commands's own
    # doc-comment). command_queue is None when the flag is off, which the
    # main loop's pause branch below treats as "no reader running" and
    # skips entirely -- window-close behaves as an immediate real exit.
    command_queue = start_stdin_command_reader() if args.pipe_stdin_commands else None

    def on_key(_window, key, _scancode, action, mods):
        if key in (glfw.KEY_LEFT, glfw.KEY_RIGHT):
            # Handled BEFORE the PRESS/REPEAT-only filter below (unlike
            # every other key here) because this is the one control that
            # also needs the RELEASE event, to resume playback once
            # scrubbing stops -- see session.scrub_advance/scrub_release's
            # own doc-comments for the full logic, unit-tested in
            # test_ring_viz_session.py.
            ctrl_held = bool(mods & glfw.MOD_CONTROL)
            if action in (glfw.PRESS, glfw.REPEAT):
                session.scrub_advance(key == glfw.KEY_RIGHT, ctrl_held, is_first_press=(action == glfw.PRESS))
            elif action == glfw.RELEASE:
                msg, needs_refresh = session.scrub_release()
                if msg is not None:
                    print(msg)
                if needs_refresh:
                    # Unlike PRESS/REPEAT above, N does NOT change here, so
                    # the main loop's own N-change branch will never fire on
                    # its own this frame -- without this explicit refresh,
                    # the HUD panel's [Stopped]->[Running] text would lag
                    # behind the actual resume by up to one whole tempo_ms
                    # tick (same reasoning as the Space/tempo-key case
                    # below).
                    _apply_hud_refresh()
            return

        if key == glfw.KEY_F11:
            # Re-fit zoom (and recenter pan) after EITHER direction of the
            # fullscreen transition via the SAME session.recenter() the
            # middle-click branch above uses, since a viewport-size/
            # aspect-ratio change makes the OLD zoom value wrong for the
            # NEW window regardless
            # of which way F11 just went. Measuring the framebuffer size
            # before AND after the toggle (rather than assuming it always
            # changes) means a toggle that fails outright (no monitors
            # found -- see FullscreenToggle.toggle()'s own early-return
            # paths) leaves the current view untouched instead of
            # unexpectedly resetting it.
            before = glfw.get_framebuffer_size(gl.window)
            fullscreen.handle_key(key, action)
            if action == glfw.PRESS:
                after = glfw.get_framebuffer_size(gl.window)
                if after != before:
                    session.recenter(after)
            return
        if action not in (glfw.PRESS, glfw.REPEAT):
            return
        if key == glfw.KEY_ESCAPE:
            glfw.set_window_should_close(gl.window, True)
            return
        step = args.n_step
        delta = 0
        if key == glfw.KEY_UP:
            delta = step
        elif key == glfw.KEY_DOWN:
            delta = -step
        elif key == glfw.KEY_PAGE_UP:
            delta = step * 100
        elif key == glfw.KEY_PAGE_DOWN:
            delta = -step * 100
        if delta:
            session.bump_n(delta)
            return

        # Playback controls -- gated to PRESS only (not REPEAT), unlike the
        # arrow keys above: these are toggle/step actions, not continuous
        # ones, so holding Space down must not rapid-fire start/stop the
        # way holding Up rapid-fires N jumps.
        if action != glfw.PRESS:
            return
        if key == glfw.KEY_SPACE:
            # Ports #toggleRunning exactly via session.toggle_space(): STOP
            # always succeeds; START is refused (with a message, mirroring
            # the JS's own "ss-info-ceiling-reached") once sequential mode
            # has already reached the loaded ceiling.
            msg = session.toggle_space()
            if msg is not None:
                print(msg)
        elif key == glfw.KEY_R:
            # Ports #reset exactly via session.reset() (the
            # resetSequential()-calling half -- see this function's own
            # module docstring "Controls:" entry for R).
            session.reset()
        elif key in (glfw.KEY_RIGHT_BRACKET, glfw.KEY_EQUAL):
            # KEY_EQUAL (the unshifted '=' key, i.e. the '+' position) is
            # accepted as an alias for KEY_RIGHT_BRACKET in case '[' / ']'
            # don't reach this callback at all on a given keyboard layout
            # -- '+' faster / '-' slower is also the more universal
            # media-player convention regardless.
            print(session.tempo_faster())
        elif key in (glfw.KEY_LEFT_BRACKET, glfw.KEY_MINUS):
            print(session.tempo_slower())

        # Space/tempo/R changes update session state without necessarily
        # triggering a rebuild_buffer call this same frame -- re-emit right
        # away so the HUD panel's running/tempo fields don't lag behind a
        # key press by up to one whole tempo_ms tick (R's own
        # force_rebuild=True is the one exception, but re-emitting here too
        # is harmless).
        _apply_hud_refresh()

    glfw.set_scroll_callback(gl.window, on_scroll)
    glfw.set_mouse_button_callback(gl.window, on_mouse_button)
    glfw.set_cursor_pos_callback(gl.window, on_cursor_pos)
    glfw.set_key_callback(gl.window, on_key)

    last_n = session.n
    frame_count = 0
    fps_t0 = time.perf_counter()
    last_tick_time = time.perf_counter()

    while not glfw.window_should_close(gl.window):
        glfw.poll_events()

        # Live pause/resume -- only reachable with command_queue set
        # (--pipe-stdin-commands, see its own doc-comment). A window-close
        # request (Esc, titlebar X, or an OS
        # close) is intercepted HERE instead of being allowed to fall
        # through to the loop's own exit condition: we cancel the close,
        # hide the window, print a PAUSED marker line rings_tab.py's
        # _poll_queue recognizes (mirrors the existing HUD_STATE: prefix
        # convention), and idle -- still pumping the OS message loop via
        # wait_events_timeout so Windows doesn't mark it "Not Responding",
        # but doing zero rendering/audio work -- until either a "RESUME"
        # line arrives (show the window again, print RESUMED, fall through
        # to the normal frame below with everything -- session, playback,
        # audio state -- untouched since none of it was ever torn down) or
        # stdin hits EOF (the __STDIN_CLOSED__ sentinel -- the Tkinter side
        # is gone, e.g. an explicit Reset already called proc.terminate(),
        # or Tkinter itself exited -- in which case there is no one left
        # to send RESUME, so let the real exit happen by leaving
        # window_should_close(window) True and breaking out of this
        # sub-loop; the outer while's own condition then ends the process).
        if command_queue is not None and glfw.window_should_close(gl.window):
            glfw.set_window_should_close(gl.window, False)
            if not fullscreen.hide_for_pause():
                print("Could not leave fullscreen; window remains visible", flush=True)
                continue
            print("RING_VIZ_PAUSED", flush=True)
            paused = True
            while paused:
                glfw.wait_events_timeout(0.2)
                try:
                    while True:
                        cmd = command_queue.get_nowait()
                        if cmd == "RESUME":
                            paused = False
                        elif cmd == "__STDIN_CLOSED__":
                            glfw.set_window_should_close(gl.window, True)
                            paused = False
                except queue.Empty:
                    pass
            if glfw.window_should_close(gl.window):
                break
            fullscreen.show_after_pause()
            print("RING_VIZ_RESUMED", flush=True)
            continue

        # Checked BEFORE the playback-tick block below, every frame: if N
        # has closed to within buffer_margin of the loaded ceiling, extend
        # the buffer now so tick_next_n's own ceiling check (right below)
        # essentially never actually fires for a magazyn that still has
        # more data to give.
        extend_buffer_if_needed()

        # Playback loop -- ports #tick's own setTimeout(tempoMs)-based
        # scheduling as a plain elapsed-time check against wall-clock time
        # (this loop already runs every frame uncapped -- see
        # glfw.swap_interval(0) above -- so there is no separate timer
        # callback to install, just a gate on how often the N-advance
        # actually fires). session.tick()'s own should_stop covers
        # sequential mode reaching its ceiling (mirrors #tick's own ceiling
        # check, which STOPS rather than advancing past it) -- now the
        # rarely-exercised fallback for a magazyn that has genuinely run
        # out of data (session.extend_exhausted), not the normal outcome of
        # a long sequential playback run.
        if session.playback_running:
            now_tick = time.perf_counter()
            if (now_tick - last_tick_time) * 1000.0 >= session.tempo_ms:
                last_tick_time = now_tick
                should_stop = session.tick()
                if should_stop:
                    print("Playback stopped: N reached the loaded ceiling")
                    # N itself doesn't change on this branch, so no
                    # rebuild_buffer call (and thus no HUD refresh) happens
                    # this frame -- emit directly so the panel's "running"
                    # field flips to stopped immediately instead of looking
                    # stuck on the last real tick's snapshot.
                    _apply_hud_refresh()

        if session.n != last_n or session.n_force_rebuild:
            last_n = session.n
            advancing = session.n_advancing
            vbo_normal, vbo_hit, new_ring_count, new_ring_count_hit = rebuild_buffer(
                last_n, prev_ring_count=ring_count, advancing=advancing
            )
            ring_count = new_ring_count
            ring_count_hit = new_ring_count_hit
            vao_normal = gl.make_ring_vao(vbo_normal)
            vao_hit = gl.make_ring_vao(vbo_hit)
            session.n_advancing = False
            session.n_force_rebuild = False

        width, height = glfw.get_framebuffer_size(gl.window)
        gl.ctx.viewport = (0, 0, width, height)
        gl.ctx.clear(0.05, 0.05, 0.07)

        pan_x = session.cam_pan[0] + width / 2
        pan_y = session.cam_pan[1] + height / 2
        gl.prog["u_pan"].value = (pan_x, pan_y)
        gl.prog["u_zoom"].value = session.cam_zoom
        gl.prog["u_viewport"].value = (width, height)

        # vertices=ring_count(_hit) explicitly, rather than letting
        # moderngl infer the count from the vbo's own byte size -- needed
        # because a 0-ring buffer is padded to a 1-vertex placeholder
        # reservation instead of a true zero-length allocation (inferring
        # from buffer size would otherwise draw that bogus placeholder
        # vertex at the origin).
        #
        # TWO draw calls, one per split buffer from rebuild_buffer (see
        # that function's own hit/normal split comment), each with its own
        # u_point_size uniform value -- this is what actually makes
        # --hit-point-size independent of --point-size on screen. Normal
        # rings drawn first, hit rings drawn last so they stay visually on
        # top of anything they'd otherwise overlap.
        gl.prog["u_point_size"].value = args.point_size
        vao_normal.render(moderngl.POINTS, vertices=ring_count - ring_count_hit)
        gl.prog["u_point_size"].value = gl.hit_point_size
        vao_hit.render(moderngl.POINTS, vertices=ring_count_hit)

        # Tracked-ring outline circles -- one LINE_LOOP draw call per
        # tracked-and-active ring over the shared unit-circle buffer,
        # scaled/positioned/colored per ring via per-draw-call uniforms
        # (see unit_circle_vertices' own doc-comment for why a shared
        # buffer rather than one per ring). Tracked-ring counts are always
        # small (user-typed or capped, see tracked_resonance_state), so a
        # few extra draw calls per frame here is negligible next to the
        # single GL_POINTS call above carrying the real ring count.
        if session.outline_draws:
            gl.prog_outline["u_pan"].value = (pan_x, pan_y)
            gl.prog_outline["u_zoom"].value = session.cam_zoom
            gl.prog_outline["u_viewport"].value = (width, height)
            for radius, color in session.outline_draws:
                gl.prog_outline["u_radius"].value = radius
                gl.prog_outline["u_color"].value = color
                gl.unit_circle_vao.render(moderngl.LINE_LOOP)

        # Center marker -- fixed decorative triangle + glow line at the
        # ring field's own screen-space origin (pan_x, pan_y; see
        # build_center_marker_vertex_data's own doc-comment for why this is
        # the same point as u_pan above, not further scaled by zoom).
        s = marker_device_scale(width, height)
        triangle_data, line_data = build_center_marker_vertex_data(pan_x, pan_y, s)
        gl.marker_triangle_vbo.write(triangle_data.tobytes())
        gl.marker_line_vbo.write(line_data.tobytes())
        gl.prog_screen["u_viewport"].value = (width, height)
        gl.marker_triangle_vao.render(moderngl.TRIANGLES)
        gl.marker_line_vao.render(moderngl.LINES)

        # Birth/resonance flash overlays -- full-screen washes that decay
        # over subsequent frames after a trigger (see session.rebuild's own
        # comment for the trigger conditions). session.resonance_flash_
        # color()/prime_flash_color() return None once fully decayed (the
        # overwhelming majority of frames), so this skips the draw call
        # entirely rather than drawing an alpha-0 quad every frame -- decay
        # only advances AFTER the draw.
        resonance_color = session.resonance_flash_color()
        if resonance_color is not None:
            quad = build_flash_quad_vertex_data(width, height, resonance_color)
            gl.flash_quad_vbo.write(quad.tobytes())
            gl.flash_quad_vao.render(moderngl.TRIANGLE_FAN)
            session.decay_resonance_flash()
        prime_color = session.prime_flash_color()
        if prime_color is not None:
            quad = build_flash_quad_vertex_data(width, height, prime_color)
            gl.flash_quad_vbo.write(quad.tobytes())
            gl.flash_quad_vao.render(moderngl.TRIANGLE_FAN)
            session.decay_prime_flash()

        # On-canvas HUD text quad -- drawn LAST (after
        # rings/outlines/marker/flash, right before the swap) so it always
        # sits on top, same as DrumRenderer's own #drawHud being the final
        # call in its own #renderFrame. hud_tex_holder is only ever
        # non-None when Pillow is installed AND the current HUD text is
        # non-empty (see _apply_hud_refresh's own early-outs).
        if gl.hud_tex_holder["tex"] is not None:
            gl.hud_tex_holder["tex"].use(location=0)
            gl.prog_text["u_tex"].value = 0
            gl.prog_text["u_viewport"].value = (width, height)
            gl.hud_quad_vao.render(moderngl.TRIANGLES)

        glfw.swap_buffers(gl.window)

        frame_count += 1
        now = time.perf_counter()
        if now - fps_t0 >= 0.5:
            fps = frame_count / (now - fps_t0)
            glfw.set_window_title(
                gl.window, f"PrimeAtlas -- Ring visualization  N={last_n:,}  rings={ring_count:,}  fps={fps:.1f}"
            )
            frame_count = 0
            fps_t0 = now

    glfw.terminate()


def main():
    from primeatlas.ring_viz.audio import INSTRUMENTS
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--audio', action='store_true', help='enable optional live sound (requires sounddevice)')
    parser.add_argument('--sound-low', choices=INSTRUMENTS, default='sine')
    parser.add_argument('--sound-prime', choices=INSTRUMENTS, default='triangle')
    parser.add_argument('--sound-lcm', choices=INSTRUMENTS, default='choir')
    parser.add_argument("--source", choices=["synthetic", "sieve", "magazyn"], default="synthetic")
    parser.add_argument("--count", type=int, default=1_000_000, help="ring count for --source synthetic")
    # Accepts parse_big_int's flexible forms (plain digits, a*10**b, a*10^b,
    # aEb) in addition to a bare int -- see that function's own doc-comment.
    # A real magazyn floor's own magnitude (floor 25 alone is 26 digits) is
    # exactly why this exists.
    parser.add_argument("--upto", type=parse_big_int, default=1_000_000,
                         help="upper bound for --source sieve/magazyn -- accepts plain digits, "
                              "a*10**b, a*10^b, or scientific notation (aEb)")
    parser.add_argument("--portal-folder", type=str, default=None, help="PrimeAtlas portal folder for --source magazyn")
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--point-size", type=float, default=3.0)
    # Independent point size for rings ON the vertical reference line
    # (pos["is_hit"] -- real divisors of N), separate from every other
    # ring, e.g. to spot factors of N at a glance without the rest of the
    # field growing too. Defaults to 40 (was None/"same as --point-size")
    # so the axis rings are readably distinct even when this flag isn't
    # passed explicitly -- rings_tab.py's own GUI field is pre-filled with
    # "40" to match (see that file's own comment) -- the
    # None-fallback-to-point-size behavior in run()'s hit_point_size
    # computation still applies if a caller explicitly passes an
    # empty/omitted value some other way.
    parser.add_argument("--hit-point-size", type=float, default=40.0,
                         help="point size for rings on the vertical reference line "
                              "(divisors of N); defaults to 40.0")
    # Font size (pixels) for the on-canvas HUD text. rasterize_hud_text
    # derives margin/line-spacing from this value too, so scaling it up
    # keeps the whole HUD block proportional instead of just the glyphs.
    parser.add_argument("--hud-font-size", type=int, default=_HUD_FONT_SIZE_DEFAULT,
                         help="pixel size of the on-canvas HUD text, default 35")
    parser.add_argument("--n-step", type=int, default=1000)
    # Window-highlight-color parity with the browser version's
    # Bertrand/Legendre/General Law toggles -- comma list of family ids
    # among the three ring_geometry.WINDOW_FAMILY_COLORS keys.
    parser.add_argument("--windows", type=str, default="",
                         help="comma-separated window families to highlight: bertrand,legendre,generalLaw")
    parser.add_argument("--general-law-theta", type=float, default=0.5)
    parser.add_argument("--general-law-mode", choices=["stepped", "sliding"], default="stepped")
    # Track P -- comma-separated prime values (same convention as
    # --windows), and --auto-orbit as the JS's #autoOrbit mode (auto-cycle
    # active primes when nothing is explicitly tracked). See rings_tab.py's
    # Track P field docstring for the launch-time-only rationale.
    parser.add_argument("--track-primes", type=str, default="",
                         help="comma-separated prime values to track, e.g. 2,3,5")
    parser.add_argument("--auto-orbit", action="store_true",
                         help="auto-cycle through active primes instead of a fixed Track P list")
    # Load Range -- comma-separated FROM,TO (two non-negative integers,
    # FROM <= TO checked here; the "does TO actually fit under what got
    # loaded" check needs the real loaded `primes` array, so that half
    # happens in run() via load_prime_range_slice instead).
    parser.add_argument("--load-range", type=str, default="",
                         help="comma-separated FROM,TO (each accepts plain digits, a*10**b, a*10^b, "
                              "or aEb -- see --upto) -- switch to a fixed range mode showing exactly "
                              "the primes in [FROM,TO], auto-tracking all of them if there aren't too many")
    # Viewing a high floor (e.g. 30) must not require loading every floor
    # below it first. For --source magazyn with --load-range, this caps how
    # many primes actually get materialized -- see load_magazyn's own
    # `max_load_count` doc-comment for why it's a plain configurable number
    # here, not a hardcoded guess.
    parser.add_argument("--max-load-count", type=parse_big_int, default=2_000_000,
                         help="safety cap on primes materialized for a magazyn --load-range load; "
                              "the range is truncated from the top if it holds more than this "
                              "(accepts plain digits, a*10**b, a*10^b, or aEb -- see --upto)")
    # Playback speed -- ports #tempoMs's own default (120ms/tick) and
    # clamp range ([30,2000], see clamp_tempo_ms's own doc-comment); Space
    # starts/stops playback at this rate, ]/[ adjust it live by +/-10ms per
    # press.
    parser.add_argument("--tempo-ms", type=int, default=_TEMPO_MS_DEFAULT,
                         help="playback speed in ms/tick, clamped to [30,2000] "
                              "(Space starts/stops playback, ]/[ adjust it live)")
    # Opt-in live pause/resume protocol -- OFF by default so running this
    # file directly from a terminal behaves exactly as before: closing
    # the window (Esc / titlebar X) really exits. Only rings_tab.py passes
    # this flag, since it's the only caller that pipes stdin (see
    # LocalLoggedRunner.send_line()) and can actually act on the PAUSED/
    # RESUMED lines this prints -- see start_stdin_command_reader's own
    # doc-comment for the full protocol.
    parser.add_argument("--pipe-stdin-commands", action="store_true",
                         help="read RESUME commands from stdin and, instead of "
                              "exiting on window-close, hide the window and idle "
                              "until one arrives (used by rings_tab.py for live "
                              "pause/resume; harmless but pointless when running "
                              "this file directly from a terminal)")
    args = parser.parse_args()

    if args.source == "magazyn" and not args.portal_folder:
        parser.error("--source magazyn requires --portal-folder")

    valid_families = {"bertrand", "legendre", "generalLaw"}
    requested_families = {f.strip() for f in args.windows.split(",") if f.strip()}
    unknown = requested_families - valid_families
    if unknown:
        parser.error(f"--windows has unknown family id(s) {sorted(unknown)!r}, expected any of {sorted(valid_families)}")

    # Validate --track-primes up front (same fail-fast convention as
    # --windows above) instead of letting a malformed entry raise an
    # uncaught ValueError later inside run()'s own int(p.strip()) parsing.
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

    # Same fail-fast format validation as --track-primes/--windows above:
    # catch a malformed --load-range before run() ever starts loading
    # primes, rather than raising an uncaught ValueError/unpack error
    # later. The "exceeds what got loaded" case cannot be checked here (no
    # `primes` array yet) -- see run()'s own call to load_prime_range_slice
    # for that half.
    if args.load_range:
        parts = args.load_range.split(",")
        if len(parts) != 2:
            parser.error(f"--load-range must be exactly two comma-separated FROM,TO values, "
                         f"got {args.load_range!r}")
        try:
            load_from, load_to = (parse_big_int(p) for p in parts)
        except ValueError as e:
            parser.error(f"--load-range: {e}")
        if load_from < 0 or load_to < 0:
            parser.error(f"--load-range FROM/TO must be non-negative, got {args.load_range!r}")
        if load_from > load_to:
            parser.error(f"--load-range FROM must be <= TO, got {args.load_range!r}")

    run(args)


if __name__ == "__main__":
    main()
