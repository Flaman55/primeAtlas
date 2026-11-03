"""
renderer.py -- GPU renderer host shared by every viz-mode (see
primeatlas/visualization/mode_registry.py): the GLFW window, the main loop, camera,
playback/navigation keys and the HUD texture. Everything mode-specific -- geometry,
HUD lines, overlay draws, mode-specific navigation, its own CLI arguments -- lives in
the active mode (RenderSession.mode, see shared/mode.py). Standalone runnable module
(see this package's own __init__.py docstring for why it stays a separate process
rather than being imported into the main Tkinter app): launched as a subprocess by a
visualization sub-tab (primeatlas/visualization/rings/rings_tab.py).

The rings mode renders the Structural Sieve "drum" (rings + hit teeth, see
primeatlas/visualization/rings/ring/ring_geometry.py). Structural Sieve's browser/Canvas 2D visualization (js/render/DrumRenderer.js in the
RelationalMathematics repo) has a practical ring-count ceiling bounded by what one JS
thread can redraw at interactive frame rates and what a browser tab can hold in memory
(see StructuralSieveApp.js's hardware-calibrated auto-track-range). PrimeAtlas has (a) an
archive of pre-generated primes far beyond an in-browser sieve and (b) a GPU. Measured:
20,000,000 rings load in 0.27s, N-change rebuild ~1.3s, pan/zoom 50+ fps at the full
20M-ring view. load_archive derives the repo root from this file's own location.

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
       - archive: reads real floors from an existing PrimeAtlas portal folder
         via primeatlas/core/storage.py + prime_sieve_v1.read_prime_window, up to
         --upto: real floor enumeration via storage.list_floors(), reads
         batched (not one unbounded pass), with an optional progress_callback
         -- the real per-load wall-clock ceiling at extreme N is still
         unmeasured against a real archive, see load_archive's own docstring
         for what to expect. The loaded buffer also TRAVELS with N during
         playback/scrubbing (extend_buffer_if_needed, called once per frame
         from run()): once N closes to within one launch-time margin's worth
         of the loaded ceiling, another chunk is fetched automatically, so
         the sequential-mode "ceiling wall" only actually stops anything
         once the archive itself has no more data past that point -- not
         merely because the ORIGINAL --upto load happened to stop somewhere
         short of it.

  2. Whether the resulting picture is mathematically interesting at huge N --
     a separate, later question once the rendering-feasibility question this
     module answers is settled.

Architecture:

  - `primes` (ascending int64 numpy array) is loaded/generated ONCE at
    startup.
  - The active mode's rebuild (for rings: ring_geometry.ring_positions())
    recomputes x/y/phase/is_hit ONLY when N
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

Module layout: renderer_cli.py parses and validates the command line,
renderer_launch.py loads the primes and builds the RenderSession,
renderer_frame.py issues one frame's draw calls; this file keeps the sys.path
bootstrap, the GLFW window, its input callbacks and the main loop.

Usage -- run as a PLAIN SCRIPT PATH, not `python -m primeatlas.visualization.shared.renderer`:
    pip install moderngl glfw numpy
    pip install Pillow   # optional -- enables the on-canvas HUD text overlay;
                          # everything else in this module works fine without
                          # it, see _PIL_AVAILABLE.
    python primeatlas/visualization/shared/renderer.py --source synthetic --count 20000000
    python primeatlas/visualization/shared/renderer.py --source sieve --upto 5000000
    python primeatlas/visualization/shared/renderer.py --source archive \
        --portal-folder "D:\\...\\PORTAL" --upto 50000000000

    Why plain-script-path and not `-m`: `python -m primeatlas.visualization.shared.renderer`
    makes Python import the `primeatlas` package FIRST (running
    `primeatlas/__init__.py`, which transitively imports `.manifest`, which
    does a bare `import window_sharding`) before this file's own body -- and
    therefore before the sys.path fix a few lines below ever runs. Run as a
    plain script path instead and that fix executes top-to-bottom before the
    `from primeatlas.visualization.shared.bigint import ...` line below is reached, exactly
    like prime_atlas_v2.py's own top-level `sys.path.insert(0, ".../prime_sieve")`
    (see that file) already has to do for the very same reason. If a
    subprocess launcher (rings_tab.py) wants `-m` invocation instead, it must
    set `PYTHONPATH` to include the repo root's `prime_sieve` directory itself
    before spawning the subprocess.

Controls:
    drag              pan (a mode may use the drag itself, see VizMode.drag --
                      the sphere rotates)
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
    R                 reset -- stops playback, N=1, returns to the rings mode,
                      clears Track P, re-enables auto-orbit, and drops back to
                      sequential mode even if --load-range was active (mirrors
                      the HTML's own Reset button, which always calls
                      resetSequential())
    Esc               quit

HUD: current N, item count, playback status, and the active mode's own lines are
drawn directly in this window's top-left corner (ports DrumRenderer's #drawHud text
overlay; the same lines also go to the console pane). Rings: factors of N, the
tracked/LCM block and any active window's range (Bertrand/Legendre/General Law), see
ring_hud.hud_lines_for_n; line: the pattern status line, see line_hud.pattern_hud_line.
Needs Pillow; without it there is no on-canvas text (everything else unaffected),
see _PIL_AVAILABLE. Size it with --hud-font-size (pixels, default 35) -- see
rasterize_hud_text's own docstring.

--hit-point-size: independent point size for rings ON the vertical
reference line (real divisors of N), separate from --point-size for every
other ring -- defaults to 40.0, or falls back to --point-size's own value
if you pass an explicit empty override some other way.
"""

import os
import queue
import sys
import time

# Allow `python primeatlas/visualization/shared/renderer.py` (not just `python -m
# primeatlas.visualization.shared.renderer`) to work by ensuring the repo root is on
# sys.path before the primeatlas.* imports below -- the subprocess launcher
# in rings_tab.py is free to pick either invocation style.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# primeatlas/__init__.py transitively imports .manifest, which does a bare
# `import window_sharding` (see storage.py's own module docstring for why
# prime_sieve_v1.py/window_sharding.py live outside this package as separate
# top-level modules) -- so `prime_sieve` must be on sys.path before ANY
# `primeatlas.*` import below, not just inside load_archive() where the
# actual prime_sieve_v1 usage lives: a bare `from primeatlas.visualization.shared.bigint
# import ...` fails without this, even though bigint.py itself has
# no such dependency.
_PRIME_SIEVE_DIR = os.path.join(_REPO_ROOT, "prime_sieve")
if _PRIME_SIEVE_DIR not in sys.path:
    sys.path.insert(0, _PRIME_SIEVE_DIR)

from primeatlas.visualization.shared.hud_text import hud_quad_vertex_data
from primeatlas.visualization.shared.world_labels import build_label_atlas, LabelLayout
from primeatlas.visualization.shared.stdin_commands import start_stdin_command_reader
from primeatlas.visualization.shared.gl_setup import setup_gl_resources
from primeatlas.visualization.shared.renderer_cli import parse_args
from primeatlas.visualization.shared.renderer_launch import build_session
from primeatlas.visualization.mode_registry import MODES

# Shaders (shaders.py), GL resources (gl_setup.py), pure geometry
# (draw_primitives.py, the modes' own *_draw.py), HUD text (hud_text.py and the
# modes' *_hud.py) and playback rules (playback.py) contain no GL calls outside
# gl_setup.py and renderer_frame.py; this file wires them into the GLFW
# callbacks and main loop.


def run(args):
    from primeatlas.visualization.shared.audio import Instruments, LiveAudio
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

    from primeatlas.visualization.shared.renderer_frame import draw_frame

    # Window/context/every shader program/VAO/VBO live on one GLResources
    # instance, `gl`, built by setup_gl_resources(). Every reference to
    # those objects below is `gl.xxx`.
    gl = setup_gl_resources(args, MODES[args.viz_mode].window_title)

    session = build_session(args)
    if session is None:
        return

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

    # The active mode's own world-space draw data (VizMode.marker_data/segment_data/
    # world_labels), rebuilt together with the ring buffers.
    mode_draw = {"marker_vao": None, "marker_count": 0, "segment_vao": None, "segment_count": 0,
                 "labels": None, "label_vbo": None, "label_vao": None}

    def _upload_mode_draw_data():
        markers = session.mode.marker_data()
        segments = session.mode.segment_data()
        for key in ("marker_vao", "segment_vao", "label_vao"):
            if mode_draw[key] is not None:
                mode_draw[key].release()
                mode_draw[key] = None
        if mode_draw["label_vbo"] is not None:
            mode_draw["label_vbo"].release()
            mode_draw["label_vbo"] = None
        mode_draw["marker_count"] = 0 if markers is None else len(markers)
        if mode_draw["marker_count"]:
            mode_draw["marker_vao"] = gl.make_marker_vao(gl.ctx.buffer(markers.astype("f4").tobytes()))
        mode_draw["segment_count"] = 0 if segments is None else len(segments)
        if mode_draw["segment_count"]:
            mode_draw["segment_vao"] = gl.make_segment_vao(gl.ctx.buffer(segments.astype("f4").tobytes()))
        if gl.label_tex_holder["tex"] is not None:
            gl.label_tex_holder["tex"].release()
            gl.label_tex_holder["tex"] = None
        mode_draw["labels"] = None
        labels = session.mode.world_labels()
        if labels and gl.prog_text is not None:
            rgba, sizes, rects = build_label_atlas(labels, session.mode.label_font_size)
            if rgba is not None:
                tex = gl.ctx.texture((rgba.shape[1], rgba.shape[0]), 4, rgba.tobytes())
                tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
                gl.label_tex_holder["tex"] = tex
                mode_draw["labels"] = LabelLayout(labels, sizes, rects)
                mode_draw["label_vbo"] = gl.ctx.buffer(reserve=max(1, len(labels)) * 6 * 4 * 4)
                mode_draw["label_vao"] = gl.ctx.vertex_array(
                    gl.prog_text, [(mode_draw["label_vbo"], "2f 2f", "in_pos", "in_uv")])

    def rebuild_buffer(n_value, prev_ring_count=None, advancing=False):
        """GL-side half of session.rebuild(): uploads its returned vertex
        data into two fresh VBOs (see split_hit_normal_vertex_data's own
        doc-comment, in draw_primitives.py, for why there are two) and
        refreshes the HUD. Everything N-dependent (geometry/colors, HUD lines,
        outline draws, flash triggers) is computed by the active mode's own
        rebuild, see session.rebuild."""
        data_normal, data_hit, count, count_hit = session.rebuild(
            n_value, prev_ring_count=prev_ring_count, advancing=advancing, audio=audio
        )
        normal_bytes = data_normal.tobytes()
        vbo_normal = gl.ctx.buffer(normal_bytes) if normal_bytes else gl.ctx.buffer(reserve=20)
        hit_bytes = data_hit.tobytes()
        vbo_hit = gl.ctx.buffer(hit_bytes) if hit_bytes else gl.ctx.buffer(reserve=20)
        _upload_mode_draw_data()
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

    # A left press/release pair that moved less than this many pixels is a click
    # (forwarded to the mode, see RenderSession.click), not a drag.
    click_slop_px = 4.0
    press_pos = {"xy": None}

    def on_mouse_button(_window, button, action, _mods):
        if button == glfw.MOUSE_BUTTON_LEFT:
            session.set_dragging(action == glfw.PRESS)
            x, y = glfw.get_cursor_pos(gl.window)
            if action == glfw.PRESS:
                press_pos["xy"] = (x, y)
            elif press_pos["xy"] is not None:
                px, py = press_pos["xy"]
                press_pos["xy"] = None
                if abs(x - px) <= click_slop_px and abs(y - py) <= click_slop_px:
                    # Cursor positions are in window coordinates; the camera works in
                    # framebuffer pixels (they differ on a scaled display).
                    fb_w, fb_h = glfw.get_framebuffer_size(gl.window)
                    win_w, win_h = glfw.get_window_size(gl.window)
                    sx = fb_w / win_w if win_w else 1.0
                    sy = fb_h / win_h if win_h else 1.0
                    session.click(x * sx, y * sy, (fb_w, fb_h))
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

    # LEFT/RIGHT scrub state lives on `session` (scrub_held/scrub_was_running) --
    # see session.scrub_advance/scrub_release for the held-count/was-running
    # bookkeeping.
    from primeatlas.visualization.shared.window_mode import FullscreenToggle
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
        mode_key = {glfw.KEY_BACKSPACE: "backspace", glfw.KEY_HOME: "home"}.get(key)
        if mode_key is not None:
            if action == glfw.PRESS:
                session.key(mode_key)
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
        # essentially never actually fires for an archive that still has
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
        # rarely-exercised fallback for an archive that has genuinely run
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
            session.view_dirty = False
        elif session.view_dirty:
            # The mode used a drag (e.g. the sphere's rotation): only its draw data
            # changes, the HUD and the ring buffers stay.
            session.view_dirty = False
            session.mode.reproject()
            _upload_mode_draw_data()

        width, height = glfw.get_framebuffer_size(gl.window)
        draw_frame(gl, session, mode_draw, args.point_size, (width, height),
                   vao_normal, vao_hit, ring_count, ring_count_hit)

        glfw.swap_buffers(gl.window)

        frame_count += 1
        now = time.perf_counter()
        if now - fps_t0 >= 0.5:
            fps = frame_count / (now - fps_t0)
            glfw.set_window_title(
                gl.window, f"{session.mode.window_title}  N={last_n:,}  "
                           f"{session.mode.count_label}={session.hud_count:,}  fps={fps:.1f}"
            )
            frame_count = 0
            fps_t0 = now

    glfw.terminate()


def main():
    run(parse_args(__doc__))


if __name__ == "__main__":
    main()
