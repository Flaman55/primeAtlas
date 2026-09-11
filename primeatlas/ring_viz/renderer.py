"""
renderer.py -- feasibility-proven GPU renderer for the Structural Sieve
"drum" (rings + hit teeth, see primeatlas/ring_geometry.py). Standalone
runnable module (see this package's own __init__.py docstring for why it
stays a separate process rather than being imported into the main Tkinter
app): launched as a subprocess by primeatlas/rings_tab.py from Faza 3
onward (see PLAN.md at the repo root for the phased rollout this file is
part of).

Why this exists (Artur, 2026-09-04): Structural Sieve is a browser/Canvas 2D
visualization (see js/render/DrumRenderer.js in the RelationalMathematics
repo) whose practical ring-count ceiling is bounded by what one JS thread can
redraw at interactive frame rates, plus what a browser tab can hold in memory
-- see StructuralSieveApp.js's own "hardware-calibrated auto-track-range"
feature, added specifically because that ceiling is real. PrimeAtlas already
has (a) a magazyn of pre-generated primes far beyond what any in-browser
sieve would attempt, and (b) real GPU hardware, already exercised for actual
sieve marking (see this project's cudasieve/marking_*_poc history).

**Feasibility already confirmed on real hardware** (see PLAN.md's own
"Feasibility already confirmed" section for the full story): 20,000,000
rings loaded in 0.27s, N-change rebuild ~1.3s, pan/zoom held 50+ fps even
with a fast scroll wheel at the full 20M-ring view. This module IS that
proven prototype, landed into the package rather than rewritten -- the only
changes from the standalone prototype version are import paths (now
`primeatlas.ring_geometry` instead of a bare `ring_geometry`) and
`load_magazyn`'s repo-root autodetection (now derived from this file's own
location instead of a `--primeatlas-root` CLI flag, since the file lives
inside the repo it needs to reach into).

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
         --upto. HARDENED (Faza 2, see PLAN.md and load_magazyn's own
         docstring): real floor enumeration via storage.list_pietra(), reads
         batched (not one unbounded pass), optional progress_callback -- the
         real per-load wall-clock ceiling at extreme N is still unmeasured
         against a real magazyn (no such data or GPU in the sandbox that
         wrote this), see load_magazyn's own docstring for what to expect.
         [ADDED, Artur 2026-09-11] The loaded buffer also TRAVELS with N
         during playback/scrubbing (extend_buffer_if_needed, called once
         per frame from run()): once N closes to within one launch-time
         margin's worth of the loaded ceiling, another chunk is fetched
         automatically, so the sequential-mode "ceiling wall" only actually
         stops anything once the magazyn itself has no more data past that
         point -- not merely because the ORIGINAL --upto load happened to
         stop somewhere short of it.

  2. Whether the resulting picture is mathematically interesting at huge N --
     a separate, later question once the rendering-feasibility question this
     module answers is settled.

Architecture (the part that was actually tested):

  - `primes` (ascending int64 numpy array) is loaded/generated ONCE at
    startup.
  - ring_geometry.ring_positions() recomputes x/y/phase/is_hit ONLY when N
    changes (Up/Down/PageUp/PageDown -- see #advance_n), never every frame:
    test_ring_geometry.py's own benchmark (run in the sandbox that built the
    original prototype, no GPU needed for that half) measured roughly 20M
    rings/second on plain CPU numpy for this recompute -- fine for "user
    pressed a key", far too slow to redo unconditionally at 60fps at tens of
    millions of rings.
  - Panning and zooming the CAMERA never touch that array: they only change a
    2D affine transform (offset + scale) applied inside the vertex shader via
    a uniform, so camera movement stays GPU-cheap regardless of ring count.
    This split -- CPU recomputes geometry on N-change, GPU alone handles
    camera every frame -- is the actual hypothesis that got confirmed on
    real hardware.
  - One `GL_POINTS` draw call per frame (point size set in the vertex shader,
    a soft circular alpha mask in the fragment shader) -- avoids the
    triangle-fan vertex multiplication a "real" circle mesh per ring would
    cost.
  - FPS and ring count are both written to the window title every frame.

Usage -- run as a PLAIN SCRIPT PATH, not `python -m primeatlas.ring_viz.renderer`:
    pip install moderngl glfw numpy
    pip install Pillow   # optional -- enables the on-canvas HUD text overlay
                          # (Faza 11B, see PLAN.md); everything else in this
                          # module works fine without it, see _PIL_AVAILABLE.
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
    (see that file) already has to do for the very same reason. If Faza 3's
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
                      (Artur, 2026-09-11: "szybkie przywrócenie do podglądu
                      pełnej wizualizacji")
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
                      and leaves it stopped (Artur, 2026-09-11)
    Space             start/stop playback -- auto-advances N by exactly 1 per
                      tick (independent of --n-step), same as the HTML's own
                      Start/Stop button (Faza 10, see PLAN.md)
    ] / [             faster / slower playback (+ / - also work as
                      aliases, in case ]/[ don't reach this window on a
                      given keyboard layout) -- multiplies the tempo
                      (ms/tick) by 0.8 / 1.25 each press (not a fixed ms
                      step: a flat +/-10ms was imperceptible at low tempos
                      and negligible at high ones -- see Artur's 2026-09-06
                      "nie widzę różnicy" report), clamped to [30, 2000],
                      printed to the console each press so the change is
                      confirmable even when it's visually subtle
    R                 reset -- stops playback, N=1, clears Track P, re-enables
                      auto-orbit, and drops back to sequential mode even if
                      --load-range was active (mirrors the HTML's own Reset
                      button, which always calls resetSequential())
    Esc               quit

HUD (Faza 11B, see PLAN.md): current N, ring count, playback status, factors
of N, tracked/LCM block, and any active window's range (Bertrand/Legendre/
General Law) are drawn directly in this window's top-left corner -- ports
DrumRenderer's own #drawHud text overlay, previously only reachable via the
console pane or rings_tab.py's side panel (see hud_lines_for_n's own
doc-comment for that history). Needs Pillow; degrades to "no on-canvas text"
(everything else unaffected) if it isn't installed -- see _PIL_AVAILABLE.
Size it with --hud-font-size (pixels, default 35) if the default is too
small on your screen/resolution -- see rasterize_hud_text's own docstring
(Artur, 2026-09-07: original 16px default was unreadable at his resolution;
2026-09-09: default bumped to 35).

--hit-point-size (Faza 11C, see PLAN.md): independent point size for rings
ON the vertical reference line (real divisors of N), separate from
--point-size for every other ring -- defaults to 40.0 (Artur, 2026-09-09),
or falls back to --point-size's own value if you pass an explicit empty
override some other way.
"""

import argparse
import json
import os
import queue
import sys
import threading
import time

import numpy as np

# Allow `python primeatlas/ring_viz/renderer.py` (not just `python -m
# primeatlas.ring_viz.renderer`) to work by ensuring the repo root is on
# sys.path before the primeatlas.* imports below -- the subprocess launcher
# in rings_tab.py (Faza 3) is free to pick either invocation style.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# primeatlas/__init__.py transitively imports .manifest, which does a bare
# `import window_sharding` (see storage.py's own module docstring for why
# prime_sieve_v1.py/window_sharding.py live outside this package as separate
# top-level modules) -- so `prime_sieve` must be on sys.path before ANY
# `primeatlas.*` import below, not just inside load_magazyn() where the
# actual prime_sieve_v1 usage lives (this bit Faza 0's own verification: a
# bare `from primeatlas.ring_geometry import ...` fails without this, even
# though ring_geometry.py itself has no such dependency).
_PRIME_SIEVE_DIR = os.path.join(_REPO_ROOT, "prime_sieve")
if _PRIME_SIEVE_DIR not in sys.path:
    sys.path.insert(0, _PRIME_SIEVE_DIR)

from primeatlas.ring_geometry import (
    ring_positions,
    compute_highlight_colors,
    compute_tracked_colors,
    tracked_ring_mask,
    legendre_level_at,
    general_law_window_bounds,
    tracked_resonance_state,
    format_big,
    resonance_log_lines,
    format_log_panel_text,
    window_anchor_primes,
    window_label_colors,
)

# [ADDED Faza 11B, see PLAN.md] On-canvas GL HUD text -- Pillow is used only
# to RASTERIZE plain text into an RGBA bitmap (PIL.ImageFont.load_default(),
# no external .ttf needed) once per HUD-content change, which is then
# uploaded as an ordinary moderngl texture and drawn as a single
# screen-space textured quad (see rasterize_hud_text / run()'s own
# `refresh_hud_texture` closure further down). Guarded so a machine without
# Pillow installed still runs every other feature of this module unchanged
# -- only the on-canvas HUD silently stays off (one console line explains
# why), same "optional dependency, never a hard crash" convention this
# project already uses for sympy (see primality.py's own module docstring).
try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


# ---------------------------------------------------------------------------
# Data sources -- see module docstring point 1 for why these are kept
# interchangeable and independent of the rendering path below.
# ---------------------------------------------------------------------------

def load_synthetic(count, seed=0):
    """A strictly increasing int64 array of exactly `count` values -- NOT
    real primes (no primality claim at all), for the purest rendering-only
    stress test. Gaps drawn from a small positive range so values stay
    'prime-density-ish' in magnitude without needing to actually sieve
    anything -- see module docstring point 1."""
    rng = np.random.default_rng(seed)
    gaps = rng.integers(1, 40, size=count, dtype=np.int64)
    return np.cumsum(gaps) + 2


def load_sieve(upto):
    """Real sieve of Eratosthenes up to `upto` (moderate scale only -- this
    is O(upto) memory as a bytearray, fine into the hundreds of millions, not
    intended for anything near magazyn scale; use --source magazyn for that).
    """
    if upto < 2:
        return np.empty(0, dtype=np.int64)
    is_composite = bytearray(upto + 1)
    primes = []
    for p in range(2, upto + 1):
        if not is_composite[p]:
            primes.append(p)
            if p * p <= upto:
                is_composite[p * p:upto + 1:p] = b"\x01" * len(range(p * p, upto + 1, p))
    return np.array(primes, dtype=np.int64)


def load_magazyn(portal_folder, upto, progress_callback=None, batch_files=64, from_n=0):
    """Reads real primes in (from_n, upto] from an existing PrimeAtlas
    portal folder, via primeatlas.storage's own file-listing helpers and
    prime_sieve_v1.read_prime_window for the actual decode.

    [ADDED `from_n`, Artur 2026-09-11: "bufor bedzie podrozowal wraz z n z
    wyprzedzeniem"] Defaults to 0, i.e. every real prime is >0 so this
    reproduces the exact old `arr[arr <= upto]` behavior unchanged when the
    caller doesn't pass it. A non-zero `from_n` lets a caller that already
    holds every prime up to some point (extend_buffer_if_needed in
    _run_visualization, below) fetch only the NEW primes past that point
    instead of re-reading and re-returning the whole [0, upto] range again
    -- two cheap wins over a naive "just call load_magazyn(new_upto) again"
    approach: (1) whole floors entirely below `from_n` are skipped without
    even listing their files (see the floor_hi_exclusive check below), and
    (2) within the one floor spanning `from_n`, files are still opened (no
    per-file range metadata to skip them by name alone) but their
    already-covered primes are trimmed out before being added to the
    result, so nothing already known gets duplicated into the array.

    HARDENED (Faza 2, see PLAN.md) vs the Faza-0 landing of the original
    feasibility prototype's loader, in three ways:

    1. Enumerates REAL floors on disk via storage.list_pietra() instead of
       blindly incrementing floor with only a fixed sanity cap (`floor > 30`)
       as a guard. A gap in the portal (e.g. floor 5 populated, floor 6 not
       yet) no longer costs an empty list_source_filenames() call for every
       skipped floor, and a portal whose highest real floor is well below
       `upto`'s own floor stops there immediately instead of still counting
       up toward the old hardcoded 30 regardless.
    2. Reads window files in BOUNDED BATCHES (`batch_files` at a time,
       default 64) rather than accumulating one unbounded Python list across
       an entire floor (or several floors) before ever concatenating -- see
       this project's own `c_skaner_odczyt_porcjami` history (04_C_skaner
       once failed the whole sieve, without warning, from a single ~1GB
       fread instead of reading in ~160MB portions) for the class of failure
       an unbounded single pass caused elsewhere in this codebase. Each
       batch is concatenated and appended to the running result list right
       away, so peak EXTRA memory during the load is bounded by one batch's
       worth of arrays, not the whole load -- the final full-array
       concatenate at the end is unavoidable (the renderer needs one
       contiguous sorted array to hand to ring_geometry), but the batching
       here at least keeps the INTERMEDIATE working set bounded.
    3. Accepts an optional `progress_callback(base_exponent, files_read_in_floor,
       primes_loaded_so_far)`, invoked after every batch, so a caller
       (primeatlas/rings_tab.py, Faza 3) can drive a real progress bar
       instead of a frozen GUI during what can be a multi-second load at
       real magazyn scale. Deliberately NOT trying to make the load itself
       faster (see this module's own docstring, data-source point 1, for why
       generation/read throughput is explicitly out of scope for this
       feature to optimize) -- only making the existing cost observable and
       boundable instead of an opaque hang.

    REAL CEILING (documented per PLAN.md's Faza 2 ask): NOT benchmarked here
    -- this sandbox has no real magazyn data or GPU to measure against. The
    rendering ceiling already confirmed on Artur's real hardware is
    20,000,000 rings at 50+ fps (see PLAN.md's "Feasibility already
    confirmed" section); this loader's own cost is dominated by per-file
    open() latency on the FUSE-mounted storage drive (~5ms/file -- the same
    figure storage.update_pietro_totals_cache()'s own docstring measured on
    this exact drive), not the PGS decode work itself. That means the real
    bottleneck to watch for at very high N is FILE COUNT, not prime count: a
    floor with many thousands of small window files costs far more
    wall-clock load time than one with a few large ones holding the same
    total prime count. Artur should measure the real number on his own
    hardware once Faza 3's tab exists to launch this against a real
    magazyn -- this docstring intentionally does not claim a number this
    sandbox cannot verify.

    `prime_sieve` (this repo's sibling top-level directory to `primeatlas/`)
    is added to sys.path here because primeatlas.storage itself does a bare
    `import prime_sieve_v1` / `import window_sharding` (see storage.py's own
    module docstring for why those two live as separate top-level modules
    rather than inside this package)."""
    prime_sieve_dir = os.path.join(_REPO_ROOT, "prime_sieve")
    if prime_sieve_dir not in sys.path:
        sys.path.insert(0, prime_sieve_dir)
    from primeatlas import storage
    import prime_sieve_v1

    chunks = []
    total_loaded = 0

    # [ADDED, see `from_n` doc above] Materialized (not a lazy generator)
    # so a floor's NEXT exponent is available while looking at the current
    # one -- gives a cheap, exact "is this whole floor already below from_n"
    # check without opening a single file, for every floor except the one
    # that actually straddles from_n (at most one wasted full floor-listing
    # in the worst case, none in the common case of extending near the top).
    floor_exponents = list(storage.list_pietra(portal_folder))
    for floor_index, base_exponent in enumerate(floor_exponents):
        floor_lo = 10 ** base_exponent if base_exponent > 0 else 0
        if floor_lo > upto:
            break
        if floor_index + 1 < len(floor_exponents):
            floor_hi_exclusive = 10 ** floor_exponents[floor_index + 1]
            if floor_hi_exclusive <= from_n:
                continue

        entries = storage.list_source_filenames(portal_folder, base_exponent)
        if not entries:
            continue

        files_read_in_floor = 0
        floor_done = False
        for batch_start in range(0, len(entries), batch_files):
            batch = entries[batch_start:batch_start + batch_files]
            batch_chunks = []
            for name, path in batch:
                window_primes = prime_sieve_v1.read_prime_window(path)
                arr = np.asarray(window_primes, dtype=np.int64)
                files_read_in_floor += 1
                if arr.size and arr[0] > upto:
                    floor_done = True
                    break
                trimmed = arr[(arr > from_n) & (arr <= upto)]
                if trimmed.size:
                    batch_chunks.append(trimmed)
                    total_loaded += int(trimmed.size)
                if arr.size and arr[-1] >= upto:
                    floor_done = True
                    break

            if batch_chunks:
                chunks.append(batch_chunks[0] if len(batch_chunks) == 1 else np.concatenate(batch_chunks))
            if progress_callback is not None:
                progress_callback(base_exponent, files_read_in_floor, total_loaded)
            if floor_done:
                break

    if not chunks:
        return np.empty(0, dtype=np.int64)
    result = np.concatenate(chunks)
    result.sort()
    return result


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

VERTEX_SHADER = """
#version 330

in vec2 in_pos;
in vec3 in_color;

uniform vec2 u_pan;     // screen-space pan offset, pixels
uniform float u_zoom;   // camera zoom (separate from ring_geometry's own
                         // max_radius -- this is the CAMERA transform the
                         // module docstring's architecture note describes,
                         // applied every frame with NO CPU recompute)
uniform vec2 u_viewport; // (width, height) in pixels, for aspect + NDC
uniform float u_point_size;

out vec3 v_color;

void main() {
    vec2 screen = in_pos * u_zoom + u_pan;
    vec2 ndc = (screen / u_viewport) * 2.0 - 1.0;
    ndc.y = -ndc.y;
    gl_Position = vec4(ndc, 0.0, 1.0);
    gl_PointSize = u_point_size;
    v_color = in_color;
}
"""

FRAGMENT_SHADER = """
#version 330

in vec3 v_color;
out vec4 f_color;

void main() {
    // Soft circular point sprite: gl_PointCoord is [0,1]^2 across the point
    // quad; discard outside the inscribed circle, soft-edge the last bit so
    // millions of points don't look like a jagged square field.
    vec2 d = gl_PointCoord - vec2(0.5);
    float r = length(d) * 2.0;
    if (r > 1.0) discard;
    float alpha = smoothstep(1.0, 0.85, r);
    f_color = vec4(v_color, alpha);
}
"""


# [ADDED Faza 8, see PLAN.md] Tracked-ring outline circles use the SAME
# world-space transform as VERTEX_SHADER above (world*zoom+pan -> NDC), so a
# tracked ring's outline circle scales/pans with the camera exactly like its
# own point does -- but drawn as a GL_LINE_LOOP over a shared unit-circle
# buffer (see unit_circle_vertices) scaled by a per-draw-call `u_radius`
# uniform, with a flat (non-point-sprite) fragment shader since there is no
# gl_PointCoord for a line primitive.
OUTLINE_VERTEX_SHADER = """
#version 330

in vec2 in_pos;   // unit-circle point (cos, sin)

uniform float u_radius;
uniform vec2 u_pan;
uniform float u_zoom;
uniform vec2 u_viewport;
uniform vec4 u_color;

out vec4 v_color;

void main() {
    vec2 world = in_pos * u_radius;
    vec2 screen = world * u_zoom + u_pan;
    vec2 ndc = (screen / u_viewport) * 2.0 - 1.0;
    ndc.y = -ndc.y;
    gl_Position = vec4(ndc, 0.0, 1.0);
    v_color = u_color;
}
"""

OUTLINE_FRAGMENT_SHADER = """
#version 330

in vec4 v_color;
out vec4 f_color;

void main() {
    f_color = v_color;
}
"""

# [ADDED Faza 8] Screen-space shader for the center marker (triangle + line)
# and the full-screen flash-overlay quad -- both are drawn in absolute PIXEL
# space (no u_zoom, no u_pan multiply in the shader itself), matching
# DrumRenderer's own Canvas 2D calls for these two elements, which draw at
# literal screen coordinates (`cx, cy` already include pan but are never
# multiplied by the interactive zoomValue -- see
# center_marker_triangle_offsets' own doc-comment). Pan/anchor/color are all
# baked into the vertex data HOST-SIDE instead of passed as uniforms: these
# shapes are at most a handful of vertices (triangle=3, line=2, quad=4), so
# rewriting their tiny buffers every frame (needed anyway for the line,
# whose endpoint depends on the current pan+viewport) costs nothing
# regardless of ring count, and a single shared vertex format (2f pos, 4f
# rgba color) keeps run()'s draw calls for all three shapes identical.
SCREEN_VERTEX_SHADER = """
#version 330

in vec2 in_pos;    // absolute pixel-space position
in vec4 in_color;

uniform vec2 u_viewport;

out vec4 v_color;

void main() {
    vec2 ndc = (in_pos / u_viewport) * 2.0 - 1.0;
    ndc.y = -ndc.y;
    gl_Position = vec4(ndc, 0.0, 1.0);
    v_color = in_color;
}
"""

SCREEN_FRAGMENT_SHADER = """
#version 330

in vec4 v_color;
out vec4 f_color;

void main() {
    f_color = v_color;
}
"""

# [ADDED Faza 11B, see PLAN.md] On-canvas HUD text quad -- same absolute-
# pixel-space / y-down convention as SCREEN_VERTEX_SHADER above (so both
# share run()'s own u_viewport-from-framebuffer-size wiring), but samples a
# texture (the Pillow-rasterized HUD bitmap, see rasterize_hud_text) instead
# of taking a flat vertex color -- text needs per-pixel coverage from the
# glyph bitmap, which a flat color can't express.
TEXT_VERTEX_SHADER = """
#version 330

in vec2 in_pos;    // absolute pixel-space position
in vec2 in_uv;

uniform vec2 u_viewport;

out vec2 v_uv;

void main() {
    vec2 ndc = (in_pos / u_viewport) * 2.0 - 1.0;
    ndc.y = -ndc.y;
    gl_Position = vec4(ndc, 0.0, 1.0);
    v_uv = in_uv;
}
"""

TEXT_FRAGMENT_SHADER = """
#version 330

in vec2 v_uv;
out vec4 f_color;

uniform sampler2D u_tex;

void main() {
    f_color = texture(u_tex, v_uv);
}
"""


# [ADDED Faza 4, see PLAN.md] Colors as plain 0..255 RGB triples so they can
# be combined with WINDOW_FAMILY_COLORS (ring_geometry.py's own scale)
# before normalizing to 0..1 once at the very end -- ports DrumRenderer's
# #drawRingTeeth base-color chain (see that method's own doc-comment):
# cyan by default, gold/orange when the ring's tooth sits at phase==0 (a
# "hit"), split at prime>=11 same as the JS version's own threshold.
_CYAN_RGB = (0.0, 188.0, 212.0)      # "#00bcd4"
_GOLD_RGB = (255.0, 215.0, 0.0)      # "#ffd700" -- hit, prime >= 11
_ORANGE_RGB = (255.0, 87.0, 34.0)    # "#ff5722" -- hit, prime < 11


def build_vertex_data(primes, n, max_radius, enabled_ids=(), theta=0.5, mode="stepped"):
    """ring_geometry.ring_positions() -> flat (x,y,r,g,b) float32 array ready
    for a moderngl buffer.

    [Faza 0] Originally just cyan/gold based on hit status.
    [Faza 4, see PLAN.md] Now also layers in window-highlight colors via
    ring_geometry.compute_highlight_colors (already-tested Bertrand pink /
    Legendre green / General Law violet additive blend, ported in Faza 1) --
    ports DrumRenderer's own priority chain: base cyan, then hit recolors to
    gold/orange, then `ring.highlightColor` (if any family matches) OVERRIDES
    whatever came before, hit or not -- see #drawRingTeeth's own doc-comment
    ("This file no longer knows Bertrand's pink or Legendre's green as
    literals... it just paints whatever color... the app already computed").
    `enabled_ids` empty (the Faza-0/3 default, no window UI wired yet at
    launch time) reproduces the exact old cyan/gold-only behavior since
    compute_highlight_colors returns matched=all-False for an empty family
    set.

    Deliberately does NOT port the tracked-ring white-outline recoloring
    (needs a "Track P" UI field + its own anchor-based color pass, see the
    project's ring-visualization task list for that follow-up) -- this pass
    is the window-highlight half of "visual parity" only."""
    pos = ring_positions(primes, n, max_radius)
    count = len(pos["x"])
    hit = pos["is_hit"]

    rgb = np.empty((count, 3), dtype=np.float64)
    rgb[:] = _CYAN_RGB
    primes_arr = np.asarray(primes, dtype=np.int64)
    hit_gold = hit & (primes_arr >= 11)
    hit_orange = hit & (primes_arr < 11)
    rgb[hit_gold] = _GOLD_RGB
    rgb[hit_orange] = _ORANGE_RGB

    if enabled_ids:
        highlight_colors, matched = compute_highlight_colors(primes_arr, n, enabled_ids, theta, mode)
        rgb[matched] = highlight_colors[matched]

    data = np.empty((count, 5), dtype=np.float32)
    data[:, 0] = pos["x"]
    data[:, 1] = pos["y"]
    data[:, 2:5] = rgb / 255.0
    return data, count, pos


def split_hit_normal_vertex_data(data, hit_mask):
    """Splits `data` (build_vertex_data's own (count, 5) array) into two
    row subsets by `hit_mask` (pos["is_hit"], same row order/length as
    `data`) -- rings ON the vertical reference line (real divisors of N)
    vs everything else.

    [ADDED Faza 11C, see PLAN.md] Why this exists: Artur, 2026-09-07, wants
    hit rings sized independently of the rest (--hit-point-size vs
    --point-size). u_point_size is a single shared shader uniform (see
    VERTEX_SHADER) -- there is no per-vertex point-size attribute in this
    pipeline -- so getting two different on-screen sizes means two separate
    draw calls over two separate vertex buffers, each with its own
    u_point_size value set immediately before its own render() call (see
    run()'s own main loop). This function is the CPU-side half of that
    split (kept pure/GL-free so it's unit-testable without a display); the
    GL-side half (two ctx.buffer()/vertex_array() pairs, two render calls)
    lives entirely in run() since it needs a real moderngl context.

    Returns (data_normal, data_hit, count_hit) -- `data_normal`/`data_hit`
    are plain row-subset views (numpy fancy-indexing copies, not views, but
    that distinction doesn't matter to the caller, which immediately calls
    .tobytes() on each), `count_hit` is `data_hit`'s own row count (the
    caller already has `data`'s total row count separately, so there's no
    matching `count_normal` -- `total - count_hit` is cheaper than a second
    redundant field). An empty `data`/`hit_mask` (0 active rings) returns
    two empty arrays and count_hit=0, never raises."""
    if len(hit_mask) == 0:
        return data, data[:0], 0
    count_hit = int(np.count_nonzero(hit_mask))
    return data[~hit_mask], data[hit_mask], count_hit


# ---------------------------------------------------------------------------
# Faza 9 (see PLAN.md) -- Load Range: switch to a FIXED ring set (a slice of
# already-loaded primes in [from, to]), independent of N, mirroring
# SieveModel's "range"/slice mode (see that class's own module doc-comment:
# sequential mode's ring set is primesUpTo(n) and grows with n; range mode's
# ring set is a fixed array chosen once and never re-filtered by n again --
# only each ring's phase/hit status still depends on n via ring_positions,
# which doesn't care how its `primes` argument was derived).
# ---------------------------------------------------------------------------

def load_prime_range_slice(primes, from_n, to_n):
    """The ascending sub-array of `primes` (this renderer's own already-
    loaded array -- there is no separate always-larger data source here the
    way the JS's PrimeDataSource is, so `primes` itself plays that role)
    whose values fall in [from_n, to_n] inclusive. Ports
    SieveModel.loadPrimeRange's slicing half only -- the mode-switching side
    effects (n reset to 0, auto-populating Track P, printing an info line)
    are run()'s own job, kept out of this pure function the same way this
    module keeps every other GL-adjacent decision out of its pure helpers.

    Raises ValueError (Python's RangeError-equivalent) for the same two
    cases SieveModel.loadPrimeRange throws for: an inverted range (`from_n
    > to_n`), or a `to_n` beyond what is actually loaded (`to_n >
    primes[-1]`, or `primes` is empty) -- ports the "exceeds the loaded
    ceiling" check using THIS renderer's own loaded array as the ceiling."""
    if from_n > to_n:
        raise ValueError(f"load_prime_range_slice: invalid range [{from_n}, {to_n}] (from > to)")
    primes_arr = np.asarray(primes, dtype=np.int64)
    ceiling = int(primes_arr[-1]) if len(primes_arr) else -1
    if to_n > ceiling:
        raise ValueError(f"load_prime_range_slice: {to_n} exceeds the loaded ceiling ({ceiling})")
    lo = int(np.searchsorted(primes_arr, from_n, side="left"))
    hi = int(np.searchsorted(primes_arr, to_n, side="right"))
    return primes_arr[lo:hi]


# ---------------------------------------------------------------------------
# Faza 10 (see PLAN.md) -- playback controls (Space to start/stop, ]/[ for
# tempo, R to reset) and auto-orbit's actual cycling behavior, which needed
# a real "N advances on its own over time" loop to have anything to animate
# -- Faza 6 only landed the FOUNDATION (the --auto-orbit flag and its effect
# of suppressing the tracked/LCM HUD block), never the cycling itself, since
# this module had no notion of "time passing" until now. Ports
# StructuralSieveApp's #toggleRunning / #stop / #tick / #setTempo /
# #advanceAutoOrbit / (the resetSequential()-calling half of) #reset.
# ---------------------------------------------------------------------------

_TEMPO_MS_MIN = 30
_TEMPO_MS_MAX = 2000
_TEMPO_MS_DEFAULT = 120


def clamp_tempo_ms(value):
    """Ports #setTempo's own clamp exactly: [30, 2000] ms/tick, falling back
    to the JS's own default (120) for a missing/non-finite value -- see
    that method's own `Math.min(2000, Math.max(30, ...))` line."""
    if value is None:
        value = _TEMPO_MS_DEFAULT
    return min(_TEMPO_MS_MAX, max(_TEMPO_MS_MIN, int(value)))


_ARROW_SCRUB_STEP = 1
_ARROW_SCRUB_STEP_CTRL = 10


def arrow_scrub_delta(is_right, ctrl_held):
    """[ADDED, Artur 2026-09-11: "sterowanie w przod i w tyl ... strzalka
    lewo prawo ... o n+1 z wcisnietym ctrl o n+10"] The N delta for one
    LEFT/RIGHT scrub step: +/-1 normally, +/-10 with Ctrl held. A separate,
    literal step size from --n-step (which only governs Up/Down/PageUp/
    PageDown) -- Artur asked for these specific magnitudes regardless of
    how --n-step happens to be configured for a given run."""
    magnitude = _ARROW_SCRUB_STEP_CTRL if ctrl_held else _ARROW_SCRUB_STEP
    return magnitude if is_right else -magnitude


def can_start_playback(n, range_mode, ceiling):
    """Ports #toggleRunning's own pre-start guard: sequential mode refuses to
    START playback once N has already reached the loaded ceiling (the caller
    should show the JS's own "ss-info-ceiling-reached" message in that case
    instead of silently doing nothing) -- range mode has no ceiling at all
    and can always start (mirrors `this.#model.mode === "sequential" &&
    this.#n >= ceiling` being the ONLY case that blocks a start)."""
    return range_mode or n < ceiling


def clamp_scrub_n(n, range_mode, ceiling):
    """[ADDED, fixing a real break Artur hit, 2026-09-11: "na uruchomionym
    przewijalem do przodu do tylu z ctrl bez i sie zatrzymalo bez resetu nie
    ma mozliwosci wznowienia"] Bounds for the LEFT/RIGHT scrub keys
    specifically: never negative, and in SEQUENTIAL mode never past the
    loaded ceiling.

    Why this exists: unlike a single Up/Down/PageUp/PageDown press, OS key
    repeat can fire a LEFT/RIGHT scrub's PRESS/REPEAT handler many times per
    second while a key is held down -- especially with Ctrl held (10 per
    step instead of 1) -- so a couple of seconds of holding RIGHT can push N
    far past the ceiling before the key is ever released. Once N is past
    the ceiling, can_start_playback() permanently refuses to (re)start
    sequential playback -- exactly the "stuck, no way to resume without R"
    Artur hit, since the scrub's own auto-resume-on-release (and even a
    manual Space press afterward) both go through that same guard. Clamping
    the scrub itself to the ceiling caps it at the same "end of loaded data"
    edge real forward playback ticking already stops at on its own
    (tick_next_n) instead of letting it run arbitrarily far past that edge.

    Deliberately scoped to the scrub keys ONLY -- Up/Down/PageUp/PageDown's
    own pre-existing, unclamped past-ceiling behavior (in place since Faza
    10, never reported as broken) is left untouched here.

    Range mode has no ceiling at all (mirrors tick_next_n/can_start_playback's
    own range_mode bypass)."""
    n = max(0, n)
    if not range_mode:
        n = min(n, ceiling)
    return n


def should_extend_buffer(n, ceiling, margin, range_mode, can_extend_source):
    """[ADDED, Artur 2026-09-11: "wystarczy ze bufor bedzie podrozowal wraz
    z n z wyprzedzeniem nawet tym jaki jest teraz ustawiony na
    uruchomieniu, dzieki temu nie da sie dojsc do sciany o ile magazyn
    zapewnia dane"] Whether N has come close enough to the loaded ceiling
    (within `margin`) that the buffer should be extended further NOW,
    before N actually reaches it -- the whole point of a lookahead margin
    is to finish the (possibly slow, disk-bound) extension load before N's
    own advance ever catches up to a ceiling that would otherwise stop it.

    `range_mode` and a data source that has nothing more to fetch anyway
    (`can_extend_source=False` -- see extend_buffer_if_needed's own
    doc-comment for why only --source magazyn qualifies) both return False
    unconditionally, same as can_start_playback/tick_next_n's own
    range_mode bypass: there is no "ceiling" concept worth extending in
    either case.

    Uses a STRICT `n > ceiling - margin` (not `>=`): the caller
    (extend_buffer_if_needed) sets `ceiling` to exactly `ceiling + margin`
    on a successful extension, so at the moment that happens N still sits
    at (at most) the OLD ceiling -- `n > new_ceiling - margin` reduces to
    `n > old_ceiling`, which is False right after extending (N cannot
    exceed old_ceiling in sequential mode -- tick_next_n/clamp_scrub_n both
    already guarantee that). A non-strict `>=` would immediately re-trigger
    another extension the very next frame purely from floating/landing
    exactly on that boundary, before N has advanced by so much as 1."""
    if range_mode or not can_extend_source or margin <= 0:
        return False
    return n > ceiling - margin


def next_buffer_ceiling(current_ceiling, margin):
    """The new ceiling to request after a successful buffer extension --
    simply one more `margin`'s worth of headroom past the current ceiling,
    so the buffer keeps carrying the SAME lookahead margin it started with
    at launch as N keeps moving forward (Artur's own words: "nawet tym
    jaki jest teraz ustawiony na uruchomieniu" -- even the one already set
    at launch is fine, no need for a fancier/growing margin)."""
    return current_ceiling + margin


def tick_next_n(n, range_mode, ceiling):
    """One playback tick's worth of N-advance -- ports #tick's own body
    exactly: sequential mode STOPS (does not advance, `should_stop=True`)
    once N has reached the ceiling; range mode has no ceiling and always
    advances by exactly 1 (NOT by --n-step, which only applies to the
    manual Up/Down/PageUp/PageDown keys -- #tick's own `this.#n += 1` is a
    single hard-coded step regardless of any user-facing "step size"
    concept). Returns (new_n, should_stop)."""
    if not range_mode and n >= ceiling:
        return n, True
    return n + 1, False


def update_resonance_log(state, active, n_value, range_mode, advancing):
    """[ADDED PLAN.md Faza 11] Ports StructuralSieveApp.js's own
    #backfillResonanceLog / #logResonance split, mutating `state` in place
    (`state["lines"]`, `state["last_n"]`, `state["last_range_mode"]` --
    caller owns and persists this dict across calls, same convention as
    `flash_state`/`orbit_state` elsewhere in this module).

    A full O(from_n..n_value) recompute via ring_geometry.resonance_log_lines
    only runs on a JUMP: the first call ever (`state["last_n"] is None`), a
    sequential<->range mode switch, or any call that isn't a simple forward
    playback tick -- exactly StructuralSieveApp.js's own #renderFrame
    jump-detection condition (`this.#n !== this.#lastRenderedN ||
    this.#model.mode !== this.#lastRenderedMode`, OR'd with "not a +1
    forward tick"). A full backfill is cheap even here because
    resonance_log_lines' own resonance_events_in_range is a whole-range
    vectorized numpy pass, not a python loop -- same cost argument as this
    module's other jump-time full recomputes (build_vertex_data itself).

    A simple FORWARD tick (`advancing=True`) instead only checks whether
    n_value itself is a new resonance step: tick_next_n always advances by
    exactly +1 (see that function's own doc-comment), so the only NEW n to
    consider is n_value -- one O(1)-ish call into resonance_log_lines with
    from_n=to_n=n_value (cost bound by the active-prime count, not by
    n_value), not a full [from_n, n_value] rescan on every single tick.
    This is exactly the performance concern StructuralSieveApp.js's own
    #logResonance doc-comment calls out ("O(1) per tick ... this full-range
    recompute only runs for actual jumps") -- skipping it would make
    playback at a large N rescan the WHOLE history every tick.

    Returns nothing; mutates `state` in place (mirrors the JS's own
    #resonanceLog being a private instance field mutated by both methods,
    not returned/reassigned by the caller)."""
    is_jump = (
        state["last_n"] is None
        or state["last_range_mode"] != range_mode
        or not advancing
    )
    if is_jump:
        resonance_from_n = 0 if range_mode else 1
        state["lines"] = resonance_log_lines(active, resonance_from_n, n_value)
    else:
        new_lines = resonance_log_lines(active, n_value, n_value)
        for new_line in new_lines:
            if not state["lines"] or state["lines"][-1] != new_line:
                state["lines"].append(new_line)
    state["last_n"] = n_value
    state["last_range_mode"] = range_mode


def advance_auto_orbit(active_primes, index, counter):
    """One tick's worth of #advanceAutoOrbit -- ports that method's body
    exactly: cycles a "which ring is tracked" index forward through
    `active_primes`, holding each one for a number of ticks proportional to
    the gap to the next active prime (wrapping to a fixed gap of 10 once it
    cycles past the last one back to index 0 -- ports the JS's own
    `nextIndex === 0 ? 10 : ...` line verbatim).

    Returns (new_index, new_counter, chosen_prime_or_None) -- `chosen_prime`
    is only non-None on the tick where the orbit actually ADVANCES to a new
    ring (mirrors the JS only reassigning `this.#trackedPrimes` inside the
    `if (counter >= gap)` branch); the caller is responsible for remembering
    the LAST chosen prime across ticks where this returns None (see run()'s
    own `orbit_state["current_prime"]`, which persists across calls the same
    way the JS's own `this.#trackedPrimes` instance field does).

    `len(active_primes) <= 1` is a no-op (mirrors the JS's own early-return
    guard: nothing to orbit through) -- returns the index/counter unchanged
    and None."""
    n = len(active_primes)
    if n <= 1:
        return index, counter, None
    next_index = (index + 1) % n
    gap = 10 if next_index == 0 else int(active_primes[next_index]) - int(active_primes[index])
    counter += 1
    if counter >= gap:
        return next_index, 0, int(active_primes[next_index])
    return index, counter, None


# ---------------------------------------------------------------------------
# Faza 8 (see PLAN.md) -- tracked-ring outline circles, birth/resonance flash
# overlays, center marker. Ports DrumRenderer.draw's `if (ring.tracked) {...}`
# outline-stroke branch, #drawCenterMarker, and the #drawFlashOverlay/
# triggerBirthFlash/triggerResonanceFlash trio.
#
# All of the ANCHOR/COLOR math these draw calls need (compute_tracked_colors)
# already existed in ring_geometry.py from Faza 1 -- this phase's only new
# pure-math surface is the small amount below that is
# specific to the GL layer itself (unit-circle geometry, screen-space marker
# offsets, flash decay/alpha), everything kept as plain functions so it can
# be unit-tested without a GPU (see run()'s own GL wiring further down for
# the untestable-without-a-display half of this phase).
# ---------------------------------------------------------------------------

def unit_circle_vertices(segments=64):
    """(segments, 2) float32 array of (cos, sin) pairs around the unit
    circle, ascending angle from 0 -- the shared base geometry for every
    tracked-ring outline. Each tracked ring's actual on-screen circle is
    this SAME buffer scaled by a per-draw-call `u_radius` uniform (see
    OUTLINE_VERTEX_SHADER / run()'s tracked-outline draw loop) rather than
    rebuilding a new vertex buffer per ring: moderngl has no built-in arc
    primitive the way Canvas 2D's `ctx.arc(cx, cy, radius, 0, 2*PI)` does
    (DrumRenderer's own tracked-ring stroke), so this is the GL equivalent
    -- a GL_LINE_LOOP over `segments` points -- computed once and reused."""
    angles = np.linspace(0.0, 2.0 * np.pi, num=segments, endpoint=False, dtype=np.float64)
    return np.stack([np.cos(angles), np.sin(angles)], axis=1).astype(np.float32)


_TRACKED_OUTLINE_GRAY = (180.0 / 255.0, 180.0 / 255.0, 180.0 / 255.0)
_TRACKED_OUTLINE_ALPHA = 0.5


def tracked_outline_color(matched, tracked_color_rgb):
    """Per-ring outline stroke (r, g, b, a) in 0..1.

    [CHANGED 2026-09-10, see Artur's report: with only ONE window family
    enabled, the HUD's own window-range label already shows that family's
    full solid color (window_label_colors always returns one, regardless
    of how many families are on -- see that function's own doc-comment),
    but the matching tracked-ring outline still drew flat gray. Artur's own
    words: "trzymajmy sie jednej zasady, ze skoro okno w hud ma kolor to
    pierscien niech go tez ma tak samo" (one consistent rule: whenever a
    window has a color in the HUD, its ring should carry that same color).
    Originally this ported DrumRenderer's `ring.tracked` branch literally --
    `(state.activeWindowCount > 1 && ring.trackedColor) ? ... : gray` --
    which the ORIGINAL site actually does gate on more than one active
    family; this is now a deliberate, explicit DEVIATION from that 1:1 port,
    per Artur's above instruction, not a bug fix in the porting sense.

    `tracked_color_rgb` is a plain 0..255 (r, g, b) triple, already summed by
    ring_geometry.compute_tracked_colors for this ring -- this function only
    decides WHETHER to use it (via the `matched` flag from that same call):
    a real "no family matched" zero vector and a genuinely matched color are
    otherwise indistinguishable by value alone, so `matched` (not a
    non-zero check) is what compute_tracked_colors already returns for
    exactly this reason. `matched` is already False whenever NO window
    family is enabled at all (build_tracked_outline_draws sets it to an
    all-False array in that case), so a plain auto-orbit/manual-tracking
    ring with no window context still falls through to gray here, same as
    before -- only the ">1 windows" requirement is gone."""
    if matched:
        r, g, b = tracked_color_rgb
        return (r / 255.0, g / 255.0, b / 255.0, _TRACKED_OUTLINE_ALPHA)
    return (_TRACKED_OUTLINE_GRAY[0], _TRACKED_OUTLINE_GRAY[1], _TRACKED_OUTLINE_GRAY[2], _TRACKED_OUTLINE_ALPHA)


def resolve_effective_track_primes(window_anchors, enabled_ids, auto_orbit, orbit_current_prime, track_primes):
    """[ADDED 2026-09-10] Pure precedence rule for which primes get an
    outline ring THIS frame -- ports the combined effect of #renderFrame's
    `if (anyWindowOn) { this.#trackedPrimes = anchors; }` block together with
    the pre-existing `this.#trackedPrimes = [autoOrbit's current pick]` /
    launch-time --track-primes fallback this module already had (Faza 10).

    Precedence, matching the JS exactly: any window family on (`enabled_ids`
    truthy) wins outright -- `window_anchors` (see
    ring_geometry.window_anchor_primes) is used even if it happens to be an
    empty list (no anchor resolved yet), exactly like the JS's own
    unconditional overwrite. Only when NO window family is on does auto-orbit
    or a plain --track-primes list apply, same as before this fix -- see
    rebuild_buffer's own call site for why auto-orbit's cycling itself is
    ALSO gated on `not enabled_ids` now (a family being on must fully stop
    auto-orbit from advancing in the background, not just from being shown,
    mirroring the JS's `if (!anyWindowOn) { this.#advanceAutoOrbit(...) }`)."""
    if enabled_ids:
        return window_anchors
    if auto_orbit:
        return [orbit_current_prime] if orbit_current_prime is not None else []
    return track_primes


def build_tracked_outline_draws(primes_active, n, enabled_ids, theta, mode, track_primes, radii):
    """Everything the GL layer needs to draw one outline circle per tracked-
    AND-active ring, computed ONCE per N-change inside rebuild_buffer (same
    convention as build_vertex_data -- see module docstring's architecture
    note: geometry/color recompute on N-change only, camera/GPU work every
    frame).

    `radii` -- ring_geometry.ring_positions()["radius"] for this same
    `primes_active` array (same indexing), i.e. the caller's already-computed
    `pos["radius"]`; not recomputed here to avoid doing ring_positions' own
    trig twice per N-change.

    Returns a list of (radius, (r, g, b, a)) tuples, one per tracked-and-
    active ring, in `primes_active`'s own ascending order (matching how
    `radii` is indexed) -- NOT `track_primes`'s user-typed order, unlike
    filter_active_tracked's LCM-facing list."""
    primes_arr = np.asarray(primes_active, dtype=np.int64)
    mask = tracked_ring_mask(primes_arr, track_primes)
    if not mask.any():
        return []
    if enabled_ids:
        colors, matched = compute_tracked_colors(primes_arr, n, enabled_ids, theta, mode)
    else:
        colors = np.zeros((len(primes_arr), 3), dtype=np.float64)
        matched = np.zeros(len(primes_arr), dtype=bool)
    draws = []
    for i in np.nonzero(mask)[0]:
        draws.append((float(radii[i]), tracked_outline_color(bool(matched[i]), tuple(colors[i]))))
    return draws


def center_marker_triangle_offsets(s):
    """(3, 2) float32 array of (dx, dy) triangle-vertex offsets from the
    view's screen-space center point (cx, cy) -- ports DrumRenderer's
    #drawCenterMarker filled triangle exactly: tip pointing toward the ring
    field (0,0 offset, i.e. AT the center point itself) with two back
    corners 35*s pixels toward the top of the screen and 12*s pixels to
    each side.

    `s` is DrumRenderer's own resolution-only device scale (`min(w,h) /
    REFERENCE_MIN_DIM`) -- NOT the interactive camera zoom (state.zoomValue
    / this module's u_zoom) -- see run()'s caller for where `s` comes from
    on the Python side; the marker's size tracks window resolution, not how
    far the user has zoomed the ring field."""
    return np.array([[0.0, 0.0], [-12.0 * s, -35.0 * s], [12.0 * s, -35.0 * s]], dtype=np.float32)


def decay_flash(value, factor):
    """One frame's worth of exponential decay for a flash-overlay alpha
    accumulator. Ports DrumRenderer's own
        this.#flashResonance *= 0.65; if (this.#flashResonance < 0.01) this.#flashResonance = 0;
    (and the analogous 0.85-factor line for #flashPrime) as a single pure
    function, so run()'s render loop calls one thing instead of duplicating
    the epsilon-snap-to-zero rule inline at both call sites."""
    value = value * factor
    return 0.0 if value < 0.01 else value


_FLASH_RESONANCE_RGB = (255.0, 140.0, 0.0)  # "rgba(255,140,0,{a})" -- orange, resonance
_FLASH_PRIME_RGB = (60.0, 60.0, 60.0)       # "rgba(60,60,60,{a})" -- dark gray, prime birth
_FLASH_MAX_ALPHA = 0.25


def flash_overlay_rgba(flash_value, base_rgb, max_alpha=_FLASH_MAX_ALPHA):
    """(r, g, b, a) in 0..1 for a full-screen flash-overlay quad at the given
    accumulator value -- ports DrumRenderer's #drawFlashOverlay (a filled
    rect over the whole canvas, alpha = flash_value * max_alpha, wired
    through a `rgba(...,{a})` template string there) as a plain tuple for a
    GL uniform instead of a CSS color string. `flash_value <= 0` (the
    resting state most frames are in) yields alpha 0 -- callers can skip
    the draw call entirely in that case rather than drawing an invisible
    quad every frame, since flash_value is 0 the overwhelming majority of
    the time (only nonzero for a few frames after a trigger, per
    decay_flash's own decay rate)."""
    r, g, b = base_rgb
    return (r / 255.0, g / 255.0, b / 255.0, flash_value * max_alpha)


def resonance_is_active(pos):
    """Whether EVERY currently active ring's tooth sits at phase 0 -- ports
    SieveModel.getStepState's `resonance.active` condition (`maxResonance >
    0 && factors.length >= maxResonance`, which reduces to "every active
    prime divides n" once at least one ring exists -- see that method's own
    doc-comment for why the maxResonance>0 guard exists, to avoid a
    spurious resonance at n=0/no active primes). `pos` is
    ring_geometry.ring_positions()'s own return dict; an empty ring set
    (count==0) is never a resonance, matching the JS guard."""
    hit = pos["is_hit"]
    return bool(len(hit)) and bool(np.all(hit))


_MARKER_REFERENCE_MIN_DIM = 2160.0  # ports DrumRenderer's own REFERENCE_MIN_DIM constant


def marker_device_scale(width, height):
    """DrumRenderer's own `s = Math.min(w, h) / REFERENCE_MIN_DIM` -- the
    resolution-only proportion scale every absolute-pixel marker constant is
    multiplied by (see that module's own doc-comment: its reference layout
    was 3840x2160)."""
    return min(width, height) / _MARKER_REFERENCE_MIN_DIM


_MARKER_TRIANGLE_RGBA = (1.0, 0.067, 0.067, 1.0)      # DrumRenderer's opaque marker fill, "#ff1111"
_MARKER_LINE_RGBA = (1.0, 0.157, 0.157, 0.55)         # DrumRenderer's "rgba(255,40,40,0.55)" glow line


def build_center_marker_vertex_data(cx, cy, s):
    """(triangle_data, line_data) -- two small float32 (pos.xy, color.rgba)
    arrays ready for a moderngl buffer via SCREEN_VERTEX_SHADER, at the
    given screen-space anchor (cx, cy) -- the ring field's own world-origin
    screen position, i.e. the SAME value already computed each frame as
    run()'s `prog["u_pan"]` (see center_marker_triangle_offsets' own
    doc-comment for why zoom does not enter into this) -- and device scale
    `s` (see marker_device_scale).

    triangle_data: 3 vertices, ports #drawCenterMarker's filled arrow.
    line_data: 2 vertices, from the anchor itself up to screen y=0 -- ports
    `ctx.moveTo(cx, cy); ctx.lineTo(cx, 0)`. Recomputed fresh every frame
    (this function is cheap: 5 vertices total) since both cx/cy (camera pan)
    and the line's own length (cy's distance to the top of the window) can
    change every frame -- there is no fixed buffer to reuse the way the
    tracked-ring outline's shared unit circle is."""
    offsets = center_marker_triangle_offsets(s)
    triangle = np.empty((3, 6), dtype=np.float32)
    triangle[:, 0] = cx + offsets[:, 0]
    triangle[:, 1] = cy + offsets[:, 1]
    triangle[:, 2:6] = _MARKER_TRIANGLE_RGBA

    line = np.empty((2, 6), dtype=np.float32)
    line[0] = (cx, cy, *_MARKER_LINE_RGBA)
    line[1] = (cx, 0.0, *_MARKER_LINE_RGBA)
    return triangle, line


def build_flash_quad_vertex_data(width, height, rgba):
    """4-vertex float32 (pos.xy, color.rgba) array covering the full
    viewport (a TRIANGLE_FAN quad: corners in order (0,0),(w,0),(w,h),(0,h))
    at a single flat color -- ports DrumRenderer's #drawFlashOverlay
    (`ctx.fillRect(0, 0, w, h)` at that color). All four vertices share the
    same `rgba` (see flash_overlay_rgba for how that's derived from the
    current flash accumulator) since the overlay is a flat wash, not a
    gradient."""
    quad = np.empty((4, 6), dtype=np.float32)
    quad[:, 0] = (0.0, width, width, 0.0)
    quad[:, 1] = (0.0, 0.0, height, height)
    quad[:, 2:6] = rgba
    return quad


def zoom_to_point(old_zoom, old_pan, cursor, viewport, factor):
    """Computes the new (zoom, pan) that keeps the WORLD-space point
    currently under `cursor` fixed on screen after multiplying zoom by
    `factor` -- i.e. real "zoom to cursor" (or, called with the viewport's
    own center as `cursor`, "zoom to screen center").

    [FIXED, see Artur's 2026-09-04 bug report] The vertex shader computes
    screen = world*zoom + pan (see VERTEX_SHADER's u_pan/u_zoom uniforms),
    where `pan` here is the EFFECTIVE pan already including the viewport-
    center offset (i.e. exactly the u_pan value -- run()'s render loop adds
    state["pan"] + viewport/2 to get this; see this function's own callers).
    Naively multiplying zoom alone (the old on_scroll behavior) leaves world
    position (0,0) -- the ring field's own mathematical center -- pinned to
    whatever screen point `pan` currently is, regardless of where the cursor
    or the viewport center actually are. That made every zoom anchor on the
    ring field's center: zooming in on a panned-to tail raced back toward
    that center instead of staying under the cursor, and zooming out from
    there flew the view away from the ring field entirely.

    `old_pan`, returned `new_pan` -- (x, y) tuples, the EFFECTIVE pan (world
    origin's current screen position), NOT run()'s `state["pan"]` (which is
    that value minus viewport/2 -- see run()'s on_scroll for the conversion
    at both ends of a call to this function).
    `cursor`, `viewport` -- (x, y) tuples in the same screen-pixel space as
    `old_pan`.
    `factor` -- zoom multiplier (>1 to zoom in, <1 to zoom out).

    Returns (new_zoom, (new_pan_x, new_pan_y))."""
    new_zoom = old_zoom * factor
    cx, cy = cursor
    old_pan_x, old_pan_y = old_pan
    world_x = (cx - old_pan_x) / old_zoom
    world_y = (cy - old_pan_y) / old_zoom
    new_pan_x = cx - world_x * new_zoom
    new_pan_y = cy - world_y * new_zoom
    return new_zoom, (new_pan_x, new_pan_y)


# Fraction of the viewport's SMALLER dimension the ring field's own radius
# should fill -- 0.45 means the full ring-field DIAMETER (2*max_radius) ends
# up covering 90% of that dimension, leaving a modest 5%-per-side margin.
# This is the same 0.45 _run_visualization already used, inline, to size
# max_radius itself from the LAUNCH window (max_radius = min(args.width,
# args.height) * 0.45) -- pulling it out into a named constant shared with
# fit_zoom_for_viewport below guarantees the two stay in lockstep: calling
# fit_zoom_for_viewport(max_radius, launch_width, launch_height) returns
# exactly 1.0, so "the view as it already opens" and "the view after an
# explicit re-fit" are provably the same computation, not two independently
# hand-tuned constants that could drift apart.
_FIT_MARGIN = 0.45


def fit_zoom_for_viewport(max_radius, width, height, margin=_FIT_MARGIN):
    """Zoom multiplier that makes a ring field of world-space radius
    `max_radius` fill `margin` of the viewport's SMALLER dimension -- i.e.
    the full window HEIGHT, or the full WIDTH if the window is narrower than
    it is tall (Artur, 2026-09-11: "zajmowało pełną wysokość okna lub
    szerokość jeśli okno będzie węższe od wysokości"). Using min(width,
    height) as the constraint is exactly that rule: whichever dimension is
    the tighter one is the one the (roughly circular) ring field gets fit
    against, so it's never clipped on either axis.

    Used for two things that both need the same "make it fit again"
    computation: (1) re-fitting after an F11 fullscreen<->windowed
    transition changes the viewport size/aspect ratio out from under a zoom
    value that was only ever correct for the OLD size, and (2) the explicit
    recenter action (middle mouse button, see on_mouse_button below) that
    snaps a zoomed/panned-away view back to "the whole picture, centered" in
    one action.

    Degenerate inputs (a non-positive radius or viewport dimension -- should
    not happen in practice, but a GLFW framebuffer query returning 0 during
    a transient resize is exactly the kind of thing worth not crashing on)
    fall back to zoom=1.0 rather than dividing by zero or returning a
    negative/infinite zoom."""
    if max_radius <= 0 or width <= 0 or height <= 0:
        return 1.0
    return (min(width, height) * margin) / max_radius


def initial_n_for_source(source, upto, primes):
    """Picks the N the ring view should OPEN on, given how the ring array was
    sourced.

    [FIXED, see Artur's 2026-09-04 bug report] For --source sieve/magazyn,
    the user has a real target N in mind (rings_tab.py's N field, passed
    through verbatim as --upto) -- the view must open exactly there, not on
    whatever the last loaded prime happens to be. ring_positions() computes
    is_hit as n % prime == 0 (real divisors of N), so N is not required to be
    prime itself; snapping to primes[-1] silently showed the wrong number
    (e.g. typing 1000 opened on N=997, the largest prime <=1000, with
    "Factors of N: 997" -- itself, since 997 is prime -- instead of 1000's
    real factors 2 and 5).

    --source synthetic has no user-specified target N at all (only --count,
    an arbitrary ring COUNT -- see load_synthetic's own docstring), so there
    is no "the value the user asked for" to open on; it keeps using the last
    generated value instead, same as before this fix."""
    if source == "synthetic":
        return int(primes[-1]) if len(primes) else 0
    return upto


def hud_lines_for_n(primes_active, n, pos, enabled_ids, theta, mode, tracked_state=None):
    """Ports the non-tracked-primes subset of DrumRenderer's #drawHud /
    StructuralSieveApp's #renderFrame draw-state construction (see those
    methods' own doc-comments in js/render/DrumRenderer.js and
    js/app/StructuralSieveApp.js in the RelationalMathematics repo) as
    PLAIN TEXT LINES printed to stdout, rather than drawn as an in-GL-window
    overlay.

    Why stdout and not a GL text overlay (per PLAN.md's Faza 4 "decide
    which [surface]" note): this project has no OpenGL text-rendering
    pipeline (glyph atlas / freetype / textured-quad-per-glyph shader) --
    building one from scratch here would be a real new subsystem, and one
    this sandbox (no GPU/display) could not visually verify at all before
    landing it. rings_tab.py's GenerationConsole pane (Faza 3) is already
    proven working on real hardware, since LocalLoggedRunner pipes this
    module's stdout straight into it -- reusing that live text surface for
    HUD info is lower-risk than shipping unverified GL text rendering.

    [ADDED Faza 6, see PLAN.md; EXTENDED Faza 7B] `tracked_state` -- the
    already-computed result of ring_geometry.tracked_resonance_state(...)
    (computed once in run(), not per-call here -- mirrors the JS's own
    "no longer computed a second time here" note on #buildLcmLines, which
    takes the already-computed #trackedResonanceState result rather than
    recomputing it). None means "nothing to show" (auto-orbit on, no
    tracked primes, or none active yet -- see tracked_resonance_state's own
    doc-comment for the exact conditions); a `too_large` dict means the
    tracked-and-active count exceeded the exact-LCM budget; otherwise the
    full tracked/lcm/phase/to_resonance block is rendered, mirroring
    #buildLcmLines's four HUD lines exactly (tracked list, LCM, phase, and
    to-resonance), using format_big for the potentially-huge BigInt-sized
    values.

    Returns a list of plain-text lines (may be empty)."""
    lines = []
    factor_primes = primes_active[pos["is_hit"]] if len(primes_active) else primes_active
    if len(factor_primes):
        lines.append("Factors of N: " + ", ".join(str(int(p)) for p in factor_primes))

    if tracked_state is not None:
        if tracked_state.get("too_large"):
            lines.append(
                f"Tracked: too many active to compute an exact LCM "
                f"({len(tracked_state['tracked'])} > {tracked_state['limit']})"
            )
        else:
            lines.append("Tracked (active): " + ", ".join(str(p) for p in tracked_state["tracked"]))
            lines.append("LCM: " + format_big(tracked_state["lcm"]))
            lines.append(
                f"Phase: {format_big(tracked_state['phase'])} / {format_big(tracked_state['lcm'])}"
            )
            lines.append("To resonance: " + format_big(tracked_state["to_resonance"]))

    if "bertrand" in enabled_ids:
        lo = n // 2
        lines.append(f"Bertrand window: ({lo:,}, {n:,}]")

    if "legendre" in enabled_ids:
        k = legendre_level_at(n)
        lo = k * k
        lines.append(f"Legendre window: k={k}  ({lo:,}, {n:,}]")

    if "generalLaw" in enabled_ids:
        lo, hi, k, _factor = general_law_window_bounds(n, theta, mode)
        lo_floor = int(np.floor(lo))
        if mode == "stepped":
            lines.append(f"General Law window (theta={theta}, k={k}): ({lo_floor:,}, {hi:,}]")
        else:
            lines.append(f"General Law window (theta={theta}): ({lo_floor:,}, {hi:,}]")

    return lines


# ---------------------------------------------------------------------------
# Faza 11B (see PLAN.md) -- on-canvas GL HUD text. Ports the actual
# DrumRenderer.#drawHud text overlay itself (the part hud_lines_for_n above
# deliberately did NOT port -- see that function's own doc-comment, written
# back when this sandbox had no way to visually verify GL text rendering at
# all). Artur's 2026-09-06 follow-up report -- "nie widzę informacji hud w
# oknie wizualizacji" -- is exactly this gap: the console pane (and Faza
# 11's rings_tab.py side panel) both show this same text, but neither is
# the GL window itself, which is where the HTML tool actually draws it.
#
# compose_hud_canvas_lines is kept as a PLAIN pure function (no PIL, no GL)
# so it is fully unit-testable even in a sandbox without Pillow or a
# display -- it only decides WHAT text appears; rasterize_hud_text (needs
# Pillow) decides how it becomes pixels.
# ---------------------------------------------------------------------------

def compose_hud_canvas_lines(n, count, lines, running, tempo_ms):
    """The exact list of text lines the GL window's HUD overlay should show,
    in order: a header line (current N and how many rings are active, ports
    DrumRenderer's own N/count header), a playback-status line (mirrors the
    HTML's Start/Stop button label + tempo, so Space/]/[  presses are
    confirmable on-canvas the same way the console print already is), then
    `lines` (hud_lines_for_n's own output: factors of N, tracked/LCM block,
    window ranges) verbatim and in the same order.

    `count` is the number of ACTIVE rings at this N (same value
    rebuild_buffer already computes), not len(lines)."""
    status = f"Running ({tempo_ms}ms/tick)" if running else "Stopped"
    header = f"N = {n:,}    rings = {count:,}    [{status}]"
    return [header] + list(lines)


_HUD_FONT_SIZE_DEFAULT = 35
_HUD_TEXT_RGB = (235, 235, 235)

#: [ADDED 2026-09-10] The fixed leading text hud_lines_for_n uses for each
#: window family's own range line -- see hud_line_colors' own doc-comment
#: for why matching is done by text prefix rather than by line position.
_HUD_WINDOW_LINE_PREFIXES = {
    "bertrand": "Bertrand window:",
    "legendre": "Legendre window:",
    "generalLaw": "General Law window",
}


def hud_line_colors(lines, window_colors):
    """[ADDED 2026-09-10, see Artur's report on colorizing the HUD's window-
    range labels] Parallel per-line RGB color list, same length as `lines`
    (hud_lines_for_n's own text output, or compose_hud_canvas_lines' header+
    lines combination -- either works, since neither the header nor any
    Factors-of-N/Tracked-block line matches a window prefix and therefore
    all fall through to the flat default).

    Every line defaults to _HUD_TEXT_RGB EXCEPT a window-range line
    (identified by its own fixed leading text, see
    _HUD_WINDOW_LINE_PREFIXES), which gets that family's own color from
    `window_colors` (ring_geometry.window_label_colors' output -- solid per-
    family color, or the additive blend when two+ enabled families' windows
    coincide exactly at this N).

    Matches by TEXT PREFIX rather than by position/index so this stays
    correct even if hud_lines_for_n's own Factors-of-N/Tracked-block line
    count changes later -- the window-range lines are always identifiable
    by their own fixed leading text regardless of what precedes them."""
    colors = []
    for line in lines:
        color = _HUD_TEXT_RGB
        for family_id, prefix in _HUD_WINDOW_LINE_PREFIXES.items():
            if line.startswith(prefix):
                color = window_colors.get(family_id, _HUD_TEXT_RGB)
                break
        colors.append(color)
    return colors


def rasterize_hud_text(lines, font_size=_HUD_FONT_SIZE_DEFAULT, line_colors=None):
    """Renders `lines` (top to bottom) into an RGBA numpy uint8 array sized
    exactly to fit them, white-ish text on a fully transparent background --
    ready to upload as a moderngl texture and draw as one screen-space quad
    (see run()'s own `refresh_hud_texture` closure). Uses
    PIL.ImageFont.load_default() deliberately: it ships INSIDE Pillow
    itself, so this needs no .ttf file anywhere on disk (no font-hunting
    logic, no risk of a missing-file crash on Artur's machine).

    [ADDED Faza 11C, see PLAN.md] `font_size` -- pixel size of the glyphs,
    forwarded to load_default(size=...) (Pillow >= 10.1's own scalable
    bitmap default font). Artur, 2026-09-07: the previous fixed 16px was
    unreadably small on his screen -- exposed as --hud-font-size so it's a
    launch-time choice rather than a hand-edited constant. Margin and
    line-spacing are DERIVED from font_size (roughly half and a quarter of
    it) rather than fixed pixel constants, so the whole HUD block stays
    proportional at any size instead of the padding looking tiny next to
    huge text or huge next to tiny text.

    Returns None for an empty `lines` list (nothing to draw -- caller should
    leave any existing HUD texture as-is or skip drawing entirely) or if
    Pillow is not installed (`_PIL_AVAILABLE` is the caller's own guard;
    this function still defends itself in case it's ever called directly).

    [ADDED 2026-09-10] `line_colors` -- optional list of (r, g, b) tuples,
    one per entry in `lines`, drawn instead of the flat _HUD_TEXT_RGB for
    that line (see hud_line_colors, which builds this list from
    ring_geometry.window_label_colors so the Bertrand/Legendre/General Law
    window-range lines get their own family color, or a shared blended
    color when two enabled families' windows coincide exactly). None (the
    default) keeps the old single-flat-color behavior unchanged; a line
    index beyond len(line_colors) also falls back to _HUD_TEXT_RGB, so a
    caller may pass a shorter list covering only the lines it cares about."""
    if not lines or not _PIL_AVAILABLE:
        return None
    margin = max(4, round(font_size * 0.5))
    line_spacing = max(2, round(font_size * 0.25))
    # Measuring text extents needs a real ImageDraw bound to SOME image --
    # PIL has no font-metrics call that doesn't go through one -- so this
    # throwaway 1x1 probe exists purely for its .textbbox() method.
    probe_img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    probe_draw = ImageDraw.Draw(probe_img)
    try:
        font = ImageFont.load_default(size=font_size)
    except TypeError:
        # Older Pillow (<10.1) load_default() takes no `size` kwarg at all --
        # falls back to its one fixed built-in size rather than crashing
        # (the --hud-font-size knob simply has no effect on that Pillow
        # version; everything else in this module is unaffected).
        font = ImageFont.load_default()

    line_boxes = [probe_draw.textbbox((0, 0), line, font=font) for line in lines]
    line_heights = [(box[3] - box[1]) for box in line_boxes]
    line_widths = [(box[2] - box[0]) for box in line_boxes]
    width = max(line_widths) + 2 * margin
    height = sum(line_heights) + line_spacing * (len(lines) - 1) + 2 * margin

    img = Image.new("RGBA", (int(width), int(height)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    y = margin
    for i, (line, box, h) in enumerate(zip(lines, line_boxes, line_heights)):
        color = line_colors[i] if line_colors is not None and i < len(line_colors) else _HUD_TEXT_RGB
        draw.text((margin - box[0], y - box[1]), line, font=font, fill=tuple(color) + (255,))
        y += h + line_spacing

    return np.asarray(img, dtype=np.uint8)


_HUD_ANCHOR_X = 12.0
_HUD_ANCHOR_Y = 12.0


def hud_quad_vertex_data(width, height, x=_HUD_ANCHOR_X, y=_HUD_ANCHOR_Y):
    """(6, 4) float32 array -- two triangles covering a `width` x `height`
    pixel-space quad anchored at (x, y) (top-left corner, ports this
    module's own SCREEN_VERTEX_SHADER pixel/y-down convention), each vertex
    (pos_x, pos_y, uv_x, uv_y). uv (0,0) is the texture's top-left texel
    (matches PIL's own top-left-origin image layout in rasterize_hud_text,
    so the quad shows the HUD bitmap right-side-up with no manual flip).

    Kept as a plain pure function (no GL calls) so the quad geometry itself
    is unit-testable without a display -- run()'s own `refresh_hud_texture`
    closure is the only caller that actually uploads this into a buffer."""
    x0, y0 = float(x), float(y)
    x1, y1 = x0 + float(width), y0 + float(height)
    return np.array([
        [x0, y0, 0.0, 0.0],
        [x1, y0, 1.0, 0.0],
        [x1, y1, 1.0, 1.0],
        [x0, y0, 0.0, 0.0],
        [x1, y1, 1.0, 1.0],
        [x0, y1, 0.0, 1.0],
    ], dtype=np.float32)


def emit_audio_tick(audio, active, hit_mask, tracked_state, advancing):
    """Reuse computed hit/HUD state; inspect only the audible index prefix."""
    if audio is None or not advancing:
        return
    # After the 15 reference pitches, frequency = 130 + index*40.
    limit = max(15, int(np.ceil((audio.mixer.sample_rate/2 - 130)/40)))
    indices = np.flatnonzero(hit_mask[:limit])
    audio.on_frame(((int(i), int(active[i])) for i in indices), advancing=True,
                   tracked_resonance=bool(tracked_state and not tracked_state.get('too_large')
                                          and tracked_state.get('to_resonance') == 0))


def start_stdin_command_reader():
    """[ADDED Faza 13, see PLAN.md] Background daemon thread that blocks on
    `sys.stdin.readline()` in a loop, pushing each stripped non-empty line
    into a thread-safe queue.Queue the main GLFW loop polls NON-blockingly
    (queue.get_nowait()) once per frame -- same producer/thread-consumer-
    queue shape as generation.py's own LocalLoggedRunner._read_loop, just
    the opposite direction (that one reads the subprocess's stdOUT into a
    queue for Tkinter to drain; this one reads OUR stdIN, fed by
    LocalLoggedRunner.send_line() on the Tkinter side, into a queue this
    same process's own main loop drains).

    When stdin hits EOF (the parent process died, or closed the pipe --
    e.g. Tkinter's own process exiting without an explicit Reset first),
    the special sentinel "__STDIN_CLOSED__" is pushed exactly once so the
    main loop can tell "no command right now" (empty queue) apart from
    "there will never be another command" (must not idle forever).

    Only ever started when --pipe-stdin-commands is passed (see that
    flag's own doc-comment) -- reading stdin at all when it's just an
    inherited console (the flag OFF) would block forever on a real
    terminal with nothing to read, hanging what should be a normal
    Ctrl-C-able CLI run."""
    q = queue.Queue()

    def _loop():
        try:
            for line in sys.stdin:
                cmd = line.strip()
                if cmd:
                    q.put(cmd)
        except Exception:  # noqa: BLE001 -- must never crash this thread silently
            pass
        q.put("__STDIN_CLOSED__")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return q


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

    if not glfw.init():
        raise RuntimeError("glfw.init() failed -- no display available on this machine?")

    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)

    window = glfw.create_window(args.width, args.height, "PrimeAtlas -- Ring visualization", None, None)
    if not window:
        glfw.terminate()
        raise RuntimeError("glfw.create_window() failed")
    glfw.make_context_current(window)
    glfw.swap_interval(0)  # uncapped, so the title FPS reflects real cost, not vsync

    ctx = moderngl.create_context()
    ctx.enable(moderngl.BLEND)
    ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
    # In an OpenGL 3.3 CORE PROFILE context, writing gl_PointSize from the
    # vertex shader has NO EFFECT at all unless GL_PROGRAM_POINT_SIZE is
    # explicitly enabled -- otherwise every point renders at a fixed,
    # driver-controlled size regardless of u_point_size's value. This was
    # missing from Faza 0's original landing (the fixed-function
    # glPointSize() path this project never used doesn't need it, which is
    # presumably why it went unnoticed until Artur tried changing
    # --point-size for real and saw zero visual change -- see the
    # "Rendered rings too small at high zoom" report/task #593, 2026-09-04).
    ctx.enable(moderngl.PROGRAM_POINT_SIZE)
    # Belt-and-suspenders alongside PROGRAM_POINT_SIZE above: per the GL
    # spec, once PROGRAM_POINT_SIZE is enabled, the fixed-function
    # glPointSize() value (ctx.point_size) is SUPPOSED to be ignored
    # entirely in favor of the shader's own gl_PointSize output -- but
    # setting it too costs nothing and removes one more variable if a
    # given driver doesn't honor that part of the spec cleanly.
    ctx.point_size = args.point_size

    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    prog["u_point_size"].value = args.point_size

    # [ADDED Faza 11C, see PLAN.md] Independent size for rings ON the
    # vertical reference line (pos["is_hit"] -- real divisors of N) --
    # falls back to args.point_size when --hit-point-size wasn't given, so
    # omitting it reproduces the old single-size behavior exactly. u_point_size
    # is a single shared uniform (see VERTEX_SHADER), so getting two sizes on
    # screen means two separate draw calls over two separate vertex buffers
    # (hit rings vs everything else), not a single draw with per-vertex
    # size -- see rebuild_buffer's own hit/normal split further down and the
    # two vao.render() calls in the main loop.
    hit_point_size = args.hit_point_size if args.hit_point_size is not None else args.point_size

    # [DIAGNOSTIC, added 2026-09-04] Artur reported that --point-size still
    # produces no visible change at all across a wide range (0.5 to 100)
    # even after the PROGRAM_POINT_SIZE fix above made points visible in
    # the first place. Two real possibilities this sandbox (no GPU/display)
    # cannot test directly: (a) the requested value genuinely isn't
    # reaching this point (argv/parsing issue), or (b) this specific
    # GPU/driver clamps the actual renderable point size to a narrow
    # hardware range regardless of what the shader requests (a real,
    # documented OpenGL behavior -- GL_POINT_SIZE_RANGE / the analogous key
    # in ctx.info). Printing both here, unconditionally, so the next real
    # run's console pane settles which one it is instead of guessing blind.
    print(f"[diag] requested point size (--point-size): {args.point_size}")
    try:
        point_size_info = {k: v for k, v in ctx.info.items() if "POINT" in k.upper()}
        print(f"[diag] GL point-size-related context info: {point_size_info}")
    except Exception as e:  # noqa: BLE001 -- diagnostic only, must never crash the run
        print(f"[diag] could not read ctx.info: {e}")

    # [ADDED Faza 8, see PLAN.md] Tracked-ring outline circles: one shared
    # unit-circle VBO/VAO reused for every tracked ring's draw call (see
    # unit_circle_vertices' own doc-comment for why a shared buffer + a
    # per-draw-call radius/color uniform pair, rather than one buffer per
    # ring).
    prog_outline = ctx.program(vertex_shader=OUTLINE_VERTEX_SHADER, fragment_shader=OUTLINE_FRAGMENT_SHADER)
    unit_circle_vbo = ctx.buffer(unit_circle_vertices().tobytes())
    unit_circle_vao = ctx.vertex_array(prog_outline, [(unit_circle_vbo, "2f", "in_pos")])

    # [ADDED Faza 8] Screen-space shapes: center marker (triangle + line) and
    # the birth/resonance flash-overlay quad, all sharing one program and
    # vertex format (see SCREEN_VERTEX_SHADER's own doc-comment). Each gets
    # its own small dynamic buffer, rewritten every frame from plain numpy
    # arrays (build_center_marker_vertex_data / build_flash_quad_vertex_data)
    # -- cheap regardless of ring count since these are always <= 4 vertices.
    prog_screen = ctx.program(vertex_shader=SCREEN_VERTEX_SHADER, fragment_shader=SCREEN_FRAGMENT_SHADER)
    marker_triangle_vbo = ctx.buffer(reserve=3 * 6 * 4)
    marker_triangle_vao = ctx.vertex_array(prog_screen, [(marker_triangle_vbo, "2f 4f", "in_pos", "in_color")])
    marker_line_vbo = ctx.buffer(reserve=2 * 6 * 4)
    marker_line_vao = ctx.vertex_array(prog_screen, [(marker_line_vbo, "2f 4f", "in_pos", "in_color")])
    flash_quad_vbo = ctx.buffer(reserve=4 * 6 * 4)
    flash_quad_vao = ctx.vertex_array(prog_screen, [(flash_quad_vbo, "2f 4f", "in_pos", "in_color")])

    # [ADDED Faza 11B, see PLAN.md] On-canvas HUD text -- a textured quad
    # (hud_quad_vertex_data, "2f 2f" pos+uv) sampling a Pillow-rasterized
    # bitmap (rasterize_hud_text). Ports DrumRenderer's own #drawHud text
    # overlay directly into this GL window, replacing "console pane only"
    # as the HUD's real home (see hud_lines_for_n's own doc-comment for why
    # that was this module's original, deliberately lower-risk choice, and
    # Artur's 2026-09-06 "nie widzę informacji hud w oknie wizualizacji"
    # report for why that turned out not to be enough). hud_tex is
    # recreated (not just rewritten) each time the text changes, since
    # moderngl textures are fixed-size -- see refresh_hud_texture below.
    # Only set up at all if Pillow is actually importable; otherwise the
    # HUD quad is simply never drawn (main loop's own `if hud_tex_holder`
    # guard), same graceful-degradation convention as everywhere else this
    # module treats an optional library as optional.
    prog_text = ctx.program(vertex_shader=TEXT_VERTEX_SHADER, fragment_shader=TEXT_FRAGMENT_SHADER) if _PIL_AVAILABLE else None
    hud_quad_vbo = ctx.buffer(reserve=6 * 4 * 4) if _PIL_AVAILABLE else None
    hud_quad_vao = ctx.vertex_array(prog_text, [(hud_quad_vbo, "2f 2f", "in_pos", "in_uv")]) if _PIL_AVAILABLE else None
    hud_tex_holder = {"tex": None}
    if not _PIL_AVAILABLE:
        print("[hud] Pillow not installed -- on-canvas HUD text disabled "
              "(run `pip install --user Pillow` to enable it). Everything "
              "else in this window is unaffected.")

    # [ADDED Faza 10, see PLAN.md] For --source sieve/magazyn, Faza 4 made
    # the view OPEN exactly at N=args.upto (see initial_n_for_source's own
    # docstring) -- but sequential playback needs somewhere to advance TO,
    # and loading only up to that exact N leaves zero headroom: N would
    # already equal the load ceiling on frame one, so Space would silently
    # refuse to start every single time (Artur hit this directly testing
    # Faza 10 itself, 2026-09-06 -- "spacja nie działa"). `load_upto` pads
    # the underlying LOAD by a modest +5% (at least 1000) past the
    # requested N so there is room to play forward and actually see
    # auto-orbit cycle; the DISPLAY still opens at the user's exact
    # args.upto below (n = initial_n_for_source(..., args.upto, ...), not
    # load_upto) -- only the loaded prime array itself is padded.
    load_upto = args.upto
    if args.source in ("sieve", "magazyn"):
        load_upto = args.upto + max(1000, args.upto // 20)

    print(f"Loading primes via --source={args.source} ...")
    t0 = time.perf_counter()
    if args.source == "synthetic":
        primes = load_synthetic(args.count)
    elif args.source == "sieve":
        primes = load_sieve(load_upto)
    elif args.source == "magazyn":
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

    # [ADDED Faza 4, see PLAN.md] Window-highlight families enabled at
    # launch time -- parsed once here (not per-frame): "" -> empty set,
    # reproducing Faza 0-3's plain cyan/gold-only behavior exactly (see
    # build_vertex_data's own doc-comment). No live in-window toggle yet
    # (would need on-screen UI this raw GL window doesn't have) -- set via
    # rings_tab.py's launch-time checkboxes instead, same as N itself.
    enabled_ids = {f.strip() for f in args.windows.split(",") if f.strip()} if args.windows else set()
    theta = args.general_law_theta
    law_mode = args.general_law_mode

    # [ADDED Faza 6, see PLAN.md] Track P foundation -- parsed once here (not
    # per-frame), same launch-time-only convention as --windows above (no
    # live in-window text field yet, see rings_tab.py's own Track P field
    # docstring for why). `--auto-orbit` is accepted and stored now so
    # Faza 10's playback loop has something to read once it exists; as of
    # Faza 7B its only visible effect on its own is suppressing the tracked/
    # LCM HUD block below (mirrors the JS's own #trackedResonanceState guard)
    # -- the actual auto-cycling behavior is still Faza 10's own scope.
    track_primes = [int(p.strip()) for p in args.track_primes.split(",") if p.strip()] if args.track_primes else []
    auto_orbit = args.auto_orbit

    # [ADDED Faza 10, see PLAN.md] Playback state -- ports #isRunning,
    # #tempoMs, #autoOrbitIndex/#autoOrbitCounter/#trackedPrimes (the
    # auto-orbit half). `ceiling` mirrors the JS's own PrimeDataSource
    # ceiling check inside #tick/#toggleRunning (sequential mode only --
    # range mode has no ceiling, same as tick_next_n/can_start_playback's
    # own `range_mode` bypass).
    #
    # [FIXED, see Artur's 2026-09-06 "spacja nie działa" report] This used
    # to be `int(primes[-1])` -- the largest ACTUAL prime found -- which is
    # the wrong quantity: the real boundary of trustworthy data is how far
    # loading went (load_upto), not where the last prime happened to land
    # (primes can be sparse near the boundary, e.g. load_upto=100 with
    # primes[-1]=97 would have refused 3 perfectly safe ticks). Using
    # load_upto also gives the load-time headroom padding above something
    # real to advance into instead of refusing on frame one.
    ceiling = load_upto if args.source in ("sieve", "magazyn") else (int(primes[-1]) if len(primes) else -1)

    # [ADDED, Artur 2026-09-11: "bufor bedzie podrozowal wraz z n z
    # wyprzedzeniem ... dzieki temu nie da sie dojsc do sciany o ile
    # magazyn zapewnia dane. ale zanim to tak comit i push" -- this is the
    # "to" he asked to do after task #618's scrub-fix commit landed] Reuses
    # the EXACT same margin figure as load_upto's own launch-time pad just
    # above (his own words: "nawet tym jaki jest teraz ustawiony na
    # uruchomieniu" -- even the one already set at launch is fine) instead
    # of inventing a second, different margin concept.
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
    # `exhausted` flips True the first time a real extension attempt comes
    # back with zero new primes -- see extend_buffer_if_needed's own
    # doc-comment for why that means "stop trying", not "keep retrying
    # every frame forever".
    extend_state = {"exhausted": False}

    tempo_ms = clamp_tempo_ms(args.tempo_ms)
    playback = {"running": False}
    orbit_state = {"index": 0, "counter": 0, "current_prime": None}

    # [ADDED Faza 9, see PLAN.md] Load Range -- ports #loadPrimeRange: switch
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
    if args.load_range:
        load_from, load_to = (int(p.strip()) for p in args.load_range.split(","))
        try:
            range_primes = load_prime_range_slice(primes, load_from, load_to)
            range_mode = True
            n = 0  # mirrors the JS's own `this.#n = 0` on a successful range load
            range_count = len(range_primes)
            # [ADDED Faza 9] Auto-populate Track P with EVERY ring in the
            # loaded range (Artur, ported from the JS's own 2026-09-03 note:
            # "loading a P-range should show all its rings tracked at once,
            # so the LCM/phase/to-resonance HUD reflects the whole set") --
            # but only up to Faza 7's own tracked_resonance_state cap
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
            else:
                print(f"Range [{load_from:,}, {load_to:,}] loaded: {range_count:,} primes")
        except ValueError as e:
            print(f"Load Range failed: {e}")

    state = {"pan": [0.0, 0.0], "zoom": 1.0, "dragging": False, "last_mouse": (0.0, 0.0)}

    # [ADDED Faza 8, see PLAN.md] flash-overlay decay accumulators (ports
    # DrumRenderer's #flashPrime/#flashResonance instance fields) and the
    # tracked-ring outline draw list -- all recomputed/updated on N-change
    # inside rebuild_buffer below, never per-frame (same convention as the
    # main ring buffer).
    flash_state = {"prime": 0.0, "resonance": 0.0}
    outline_draws_holder = {"draws": []}

    # [ADDED PLAN.md Faza 11 -- resonance log + surviving-primes panel; NOT
    # to be confused with this file's own pre-existing "Faza 11"/"Faza 11B"
    # labels a few lines below, which name the HUD_STATE snapshot / on-canvas
    # GL text work instead -- that numbering was assigned informally on
    # 2026-09-06 before PLAN.md's Faza 6+ phase list (written 2026-09-05) was
    # cross-checked, and PLAN.md's own Faza 11 is this resonance-log/
    # surviving-primes feature, landed here.]
    #
    # Persisted across rebuild_buffer calls (ports StructuralSieveApp.js's
    # own #resonanceLog array) -- see update_resonance_log's own doc-comment
    # for the full jump-vs-tick algorithm this dict feeds.
    resonance_log_state = {"lines": [], "last_n": None, "last_range_mode": None}

    # [ADDED Faza 11, see PLAN.md] Persistent HUD snapshot -- rebuild_buffer
    # keeps this updated (below) alongside its existing human-readable
    # console prints; emit_hud_state() serializes it (plus the always-live
    # playback/tempo fields) as ONE JSON line on stdout, prefixed so
    # rings_tab.py's own console-line callback can pick it out of the
    # stream. This is IN ADDITION TO the existing print(line) calls, not a
    # replacement -- those stay useful for a still frame or scrolling back
    # through history in the console pane.
    #
    # Why this exists at all (Artur, 2026-09-06, right after confirming
    # Faza 10 works): "brak panelu HUD w ogóle" -- the HUD text technically
    # already reached the console pane (Faza 4/7/11's own long-standing
    # console-pane convention), but during Faza 10 playback it reprints
    # every single tick and scrolls past far too fast to ever read; there
    # was no ALWAYS-CURRENT snapshot anywhere. rings_tab.py renders this
    # into a small always-visible panel instead of leaving it to scroll by.
    hud_state = {"n": n, "count": 0, "rebuild_ms": 0.0, "lines": []}

    def emit_hud_state():
        payload = {
            "n": hud_state["n"],
            "count": hud_state["count"],
            "rebuild_ms": hud_state["rebuild_ms"],
            "lines": hud_state["lines"],
            "running": playback["running"],
            "tempo_ms": tempo_ms,
        }
        print("HUD_STATE:" + json.dumps(payload))

    # [ADDED Faza 11B, see PLAN.md] Rebuilds the on-canvas HUD texture from
    # hud_state's current contents -- called from the same two places
    # emit_hud_state() already is (end of rebuild_buffer, and on_key after
    # a Space/]/[/R press), since those are exactly the moments the text
    # COULD have changed (N changed, or playback running/tempo changed).
    # A no-op if Pillow isn't installed (hud_quad_vao is None in that case).
    def refresh_hud_texture():
        if hud_quad_vao is None:
            return
        canvas_lines = compose_hud_canvas_lines(
            hud_state["n"], hud_state["count"], hud_state["lines"], playback["running"], tempo_ms
        )
        # [ADDED 2026-09-10, see Artur's report: HUD window-range labels
        # colored like their own ring color, merging to a shared blended
        # color when two enabled families' windows coincide exactly] --
        # window_label_colors only needs enabled_ids/n/theta/law_mode (all
        # already in scope in run()'s own closure), hud_line_colors then
        # maps that onto canvas_lines by each window line's own fixed text
        # prefix -- see both functions' own doc-comments.
        window_colors = window_label_colors(enabled_ids, hud_state["n"], theta, law_mode)
        line_colors = hud_line_colors(canvas_lines, window_colors)
        rgba = rasterize_hud_text(canvas_lines, font_size=args.hud_font_size, line_colors=line_colors)
        if hud_tex_holder["tex"] is not None:
            hud_tex_holder["tex"].release()
            hud_tex_holder["tex"] = None
        if rgba is None:
            return
        h, w = rgba.shape[0], rgba.shape[1]
        tex = ctx.texture((w, h), 4, rgba.tobytes())
        tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        hud_tex_holder["tex"] = tex
        hud_quad_vbo.write(hud_quad_vertex_data(w, h).tobytes())

    def rebuild_buffer(n_value, prev_ring_count=None, advancing=False):
        t0 = time.perf_counter()
        # [ADDED Faza 9, see PLAN.md] range_mode's ring set is FIXED
        # (range_primes, set once above) -- it does not grow/shrink with
        # n_value the way sequential mode's `primes[primes <= n_value]`
        # does; only each ring's phase/hit status still depends on n_value,
        # via ring_positions inside build_vertex_data below.
        active = range_primes if range_mode else primes[primes <= n_value]
        data, count, pos = build_vertex_data(active, n_value, max_radius, enabled_ids, theta, law_mode)
        t1 = time.perf_counter()
        print(f"N={n_value:,}  rings={count:,}  rebuild={1000 * (t1 - t0):.1f}ms")
        # [ADDED Faza 7B, see PLAN.md] tracked_resonance_state does its own
        # active-filtering internally (ring_geometry.filter_active_tracked,
        # same function Faza 6 introduced) -- no separate filter step needed
        # here anymore. auto_orbit=True short-circuits to None inside that
        # function too (mirrors the JS's own `if (this.#autoOrbit || ...)
        # return null` guard), so the explicit `if auto_orbit` branch Faza 6
        # had here is gone; there is nothing left for it to skip.
        tracked_state = tracked_resonance_state(track_primes, active, n_value, auto_orbit=auto_orbit)
        emit_audio_tick(audio, active, pos['is_hit'], tracked_state, advancing)
        current_hud_lines = hud_lines_for_n(active, n_value, pos, enabled_ids, theta, law_mode, tracked_state)
        for line in current_hud_lines:
            print(line)

        # [ADDED PLAN.md Faza 11 -- resonance log + surviving-primes panel]
        # See update_resonance_log's own doc-comment for the jump-vs-tick
        # distinction this relies on.
        update_resonance_log(resonance_log_state, active, n_value, range_mode, advancing)

        resonance_count, resonance_text = format_log_panel_text(resonance_log_state["lines"])
        print(f"Resonance log ({resonance_count}): {resonance_text}")
        primes_count, primes_text = format_log_panel_text(list(active))
        print(f"Surviving primes ({primes_count}): {primes_text}")

        # [ADDED Faza 10, see PLAN.md] Auto-orbit's actual cycling -- only
        # advances on a FORWARD playback tick (advancing=True), never on a
        # manual jump/goto, a range-mode reload, or a non-advancing redraw,
        # exactly mirroring #advanceAutoOrbit only ever being called from
        # inside #tick (see that method's own call site in
        # StructuralSieveApp.js). orbit_state["current_prime"] persists the
        # last-chosen ring across every OTHER rebuild_buffer call so a
        # manual N jump mid-playback still shows the last-orbited ring
        # rather than reverting to nothing.
        # [FIXED 2026-09-10, Artur's report: "pierscienie sa dla sledzonych i
        # dla auto orbit ale nie ma dla bertranda legendre i dla general
        # law"] Auto-orbit's cycling is now ALSO gated on `not enabled_ids`,
        # mirroring the JS's own `if (!anyWindowOn) { this.#advanceAutoOrbit
        # (...) }` -- a window family being on must fully stop auto-orbit
        # from advancing in the background, not just from being shown (see
        # resolve_effective_track_primes's own doc-comment for the full
        # precedence rule this pairs with).
        if auto_orbit and not enabled_ids and advancing:
            new_index, new_counter, chosen = advance_auto_orbit(
                active, orbit_state["index"], orbit_state["counter"]
            )
            orbit_state["index"] = new_index
            orbit_state["counter"] = new_counter
            if chosen is not None:
                orbit_state["current_prime"] = chosen
        # [FIXED 2026-09-10] window_anchor_primes (ring_geometry.py) supplies
        # each currently-on window family's own anchor -- see that function's
        # doc-comment for the exact gap this closes: Bertrand/Legendre/
        # General Law's highlight COLOR already worked (Faza 1), but their
        # own anchor ring never got the tracked-set membership that actually
        # draws the outline circle, because nothing before this fed window
        # anchors into effective_track_primes the way auto-orbit and
        # --track-primes already did.
        window_anchors = window_anchor_primes(active, n_value, enabled_ids, theta, law_mode)
        effective_track_primes = resolve_effective_track_primes(
            window_anchors, enabled_ids, auto_orbit, orbit_state["current_prime"], track_primes
        )

        # [ADDED Faza 8, extended 2026-09-10] Tracked-ring outline circles --
        # recomputed here alongside the main buffer, same N-change-only
        # cadence. Uses effective_track_primes (Faza 10, now also covering
        # window-family anchors -- see resolve_effective_track_primes's own
        # doc-comment for the full precedence) rather than track_primes
        # directly, so auto-orbit mode outlines whichever single ring it is
        # currently on, and window mode (Bertrand/Legendre/General Law)
        # outlines each on family's own anchor, instead of every launch-time
        # --track-primes entry (mirrors DrumRenderer's own outline loop
        # reading `this.#trackedPrimes`, which IS what both auto-orbit AND
        # the window-family anchor loop overwrite -- unlike
        # tracked_resonance_state below, which auto-orbit instead
        # short-circuits to None entirely, per that function's own
        # doc-comment).
        outline_draws_holder["draws"] = build_tracked_outline_draws(
            active, n_value, enabled_ids, theta, law_mode, effective_track_primes, pos["radius"]
        )

        # [ADDED Faza 8] Birth/resonance flash triggers -- approximates
        # DrumRenderer's own triggerBirthFlash()/triggerResonanceFlash()
        # call sites (StructuralSieveApp's per-tick `step.justBorn` /
        # `step.resonance.active`, see those call sites' own doc-comments in
        # StructuralSieveApp.js), adapted to this module's discrete N-jump
        # model (Up/Down/PageUp/PageDown key presses) rather than the JS's
        # per-tick playback loop, which doesn't exist here yet (Faza 10).
        # "Just born" here means "this jump increased the active ring
        # count" -- exact for a single-step (+n_step) jump, an
        # over-approximation for a coarse PageUp/PageDown jump that crosses
        # more than one prime (fires once for the whole jump rather than
        # once per prime crossed, same simplification a discrete-jump model
        # has to make regardless of flash granularity) -- and a jump that
        # DECREASES n (count goes down) never fires it, matching the JS's
        # own justBorn being a forward-only concept. Resonance uses
        # resonance_is_active(pos) directly (every active ring's tooth at
        # phase 0) rather than tracked_state's own to-resonance==0 condition
        # -- the JS keeps these as two deliberately separate signals (see
        # StructuralSieveApp.js's own comment on the LCM chime being a
        # "SEPARATE condition from step.resonance.active"); this port only
        # has the general one wired to the flash (the tracked-LCM chime has
        # no visual flash counterpart in DrumRenderer to begin with -- it is
        # HUD-text-and-audio-only there).
        if prev_ring_count is not None and count > prev_ring_count:
            flash_state["prime"] = 1.0
        if resonance_is_active(pos):
            flash_state["resonance"] = 1.0

        # [FIXED, see Artur's 2026-09-06 R/reset crash report]
        # moderngl.Context.buffer() refuses a truly zero-length buffer
        # ("the buffer cannot be empty") -- previously unreachable in
        # practice (N always opened well above 0 active rings), but Faza
        # 10's own R/reset lands N on 1 (0 active rings, since the
        # smallest prime is 2), and Up/Down/PageDown can reach N=0 the
        # same way. Falls back to a 1-vertex placeholder reservation
        # (never actually drawn -- the main loop's own vao.render calls are
        # told the REAL counts, `count_normal`/`count_hit`, explicitly)
        # rather than crashing the whole GL subprocess over an empty set.
        #
        # [ADDED Faza 11C, see PLAN.md] Split into TWO buffers here -- rings
        # ON the vertical reference line (pos["is_hit"], real divisors of N)
        # vs everything else -- so the main loop can draw each with its own
        # u_point_size uniform (Artur, 2026-09-07: wants hit rings sized
        # independently of the rest). See split_hit_normal_vertex_data's own
        # doc-comment for why this is a separate, unit-tested pure function
        # rather than inlined here.
        data_normal, data_hit, count_hit = split_hit_normal_vertex_data(data, pos["is_hit"])

        normal_bytes = data_normal.tobytes()
        vbo_normal = ctx.buffer(normal_bytes) if normal_bytes else ctx.buffer(reserve=20)
        hit_bytes = data_hit.tobytes()
        vbo_hit = ctx.buffer(hit_bytes) if hit_bytes else ctx.buffer(reserve=20)

        # [ADDED Faza 11, see PLAN.md] Refresh + emit the HUD snapshot every
        # time this function runs (every N-change, whether from a manual
        # jump or a playback tick) -- see hud_state's own doc-comment above
        # for why this exists alongside (not instead of) the plain
        # print(line) calls above.
        hud_state["n"] = n_value
        hud_state["count"] = count
        hud_state["rebuild_ms"] = round(1000 * (t1 - t0), 1)
        hud_state["lines"] = current_hud_lines
        emit_hud_state()
        refresh_hud_texture()

        return vbo_normal, vbo_hit, count, count_hit

    vbo_normal, vbo_hit, ring_count, ring_count_hit = rebuild_buffer(n)
    vao_normal = ctx.vertex_array(prog, [(vbo_normal, "2f 3f", "in_pos", "in_color")])
    vao_hit = ctx.vertex_array(prog, [(vbo_hit, "2f 3f", "in_pos", "in_color")])

    def on_scroll(_window, _dx, dy):
        # [FIXED, see Artur's 2026-09-04 bug report and zoom_to_point's own
        # docstring for the full before/after explanation] Previously this
        # only multiplied state["zoom"], leaving state["pan"] untouched --
        # which anchored every zoom on the ring field's own mathematical
        # center rather than the cursor. zoom_to_point() does the real
        # zoom-to-cursor math; this closure only converts between
        # state["pan"] (relative to viewport center) and the EFFECTIVE pan
        # that function needs (absolute screen position of world (0,0),
        # matching what the shader's u_pan uniform actually receives below).
        factor = 1.1 if dy > 0 else (1 / 1.1)
        width, height = glfw.get_framebuffer_size(window)
        old_pan = (state["pan"][0] + width / 2, state["pan"][1] + height / 2)
        new_zoom, new_pan = zoom_to_point(state["zoom"], old_pan, state["last_mouse"], (width, height), factor)
        state["zoom"] = new_zoom
        state["pan"][0] = new_pan[0] - width / 2
        state["pan"][1] = new_pan[1] - height / 2

    def on_mouse_button(_window, button, action, _mods):
        if button == glfw.MOUSE_BUTTON_LEFT:
            state["dragging"] = action == glfw.PRESS
        elif button == glfw.MOUSE_BUTTON_MIDDLE and action == glfw.PRESS:
            # [ADDED, Artur 2026-09-11] "myszką można było wyśrodkować...
            # szybkie przywrócenie do podglądu pełnej wizualizacji" -- a
            # one-click way to snap an off-center/zoomed-in view straight
            # back to "the whole ring field, centered, filling the window",
            # without having to manually scroll-zoom-out and drag back.
            # Middle-click was free (left drags, scroll zooms) and is the
            # conventional "reset camera" gesture in most viewers/3D tools.
            width, height = glfw.get_framebuffer_size(window)
            state["zoom"] = fit_zoom_for_viewport(max_radius, width, height)
            state["pan"][0] = 0.0
            state["pan"][1] = 0.0

    def on_cursor_pos(_window, x, y):
        lx, ly = state["last_mouse"]
        if state["dragging"]:
            state["pan"][0] += x - lx
            state["pan"][1] += y - ly
        state["last_mouse"] = (x, y)

    # [ADDED Faza 10] "advancing" and "force_rebuild" are read by the main
    # loop's own N-change branch below: "advancing" tells rebuild_buffer
    # this N-change came from a forward playback tick (so auto-orbit should
    # cycle), and "force_rebuild" forces a rebuild even when n hasn't
    # actually changed (needed for R/reset landing back on n=1 when n was
    # ALREADY 1 -- a plain `n != last_n` check would otherwise miss it).
    n_holder = {"n": n, "advancing": False, "force_rebuild": False}

    def extend_buffer_if_needed():
        """[ADDED, Artur 2026-09-11, see buffer_margin's own comment above
        for the full quote] Keeps the loaded `primes` array's lookahead
        margin AHEAD of N as playback/scrubbing advances, instead of the
        launch-time pad being a ONE-TIME margin that N eventually catches
        up to and permanently stops at -- clamp_scrub_n/tick_next_n/
        can_start_playback's own ceiling checks remain the correct SAFETY
        NET (a real, exhausted magazyn still needs a hard stop somewhere),
        they just become the rarely-exercised fallback instead of the
        thing that fires on every normal long playback run.

        Called once per frame from the main loop, before the playback-tick
        block -- should_extend_buffer is a cheap O(1) check the overwhelming
        majority of frames (N nowhere near the ceiling yet) and only does
        real work (a fresh load_magazyn call) on the rare frame where N has
        actually closed to within buffer_margin of it.

        Deliberately gives up permanently once one real extension attempt
        comes back with zero new primes (`extend_state["exhausted"]`)
        rather than re-attempting a full load_magazyn scan every single
        frame forever while N sits near an exhausted ceiling: that outcome
        means the magazyn genuinely has no more data past the current
        ceiling right now, so falling back to the pre-existing hard-stop
        behavior there is the CORRECT outcome -- Artur's own caveat "o ile
        magazyn zapewnia dane" (only as long as storage provides data), not
        a bug to keep working around."""
        nonlocal ceiling, primes
        if not can_extend_buffer or extend_state["exhausted"]:
            return
        if not should_extend_buffer(n_holder["n"], ceiling, buffer_margin, range_mode, can_extend_buffer):
            return
        new_ceiling = next_buffer_ceiling(ceiling, buffer_margin)
        new_primes = load_magazyn(args.portal_folder, new_ceiling, from_n=ceiling)
        if len(new_primes) == 0:
            extend_state["exhausted"] = True
            print(f"Buffer extend: no more data past {ceiling:,} in the magazyn -- "
                  f"the loaded ceiling is now the real end of stored data")
            return
        primes = np.concatenate([primes, new_primes])
        ceiling = new_ceiling
        print(f"Buffer extend: loaded {len(new_primes):,} more primes ahead of N, ceiling now {ceiling:,}")

    # [ADDED, Artur 2026-09-11] LEFT/RIGHT scrub state -- "held" counts
    # currently-pressed scrub keys (LEFT and RIGHT tracked together, not
    # separately, so pressing both at once and releasing them in either
    # order still only resumes once BOTH are up); "was_running" remembers
    # whether playback was actually running at the moment the first scrub
    # key of this hold-sequence went down, so a scrub performed while
    # already stopped never auto-starts playback on release (Artur:
    # "gdy używamy strzałek na zatrzymanym to przewija ale nie uruchamia
    # wizualizacji, wciąż jest statyczna").
    scrub_state = {"held": 0, "was_running": False}
    from primeatlas.ring_viz.window_mode import FullscreenToggle
    fullscreen = FullscreenToggle(glfw, window)
    print('F11: toggle fullscreen (auto-fits zoom to the new window size); '
          'middle-click: recenter/fit view; Esc: close visualization', flush=True)

    # [ADDED Faza 13, see PLAN.md] Live pause/resume -- opt-in (see
    # --pipe-stdin-commands's own doc-comment). command_queue is None when
    # the flag is off, which the main loop's pause branch below treats as
    # "no reader running" and skips entirely -- window-close behaves
    # exactly as every earlier Faza (immediate real exit).
    command_queue = start_stdin_command_reader() if args.pipe_stdin_commands else None

    def on_key(_window, key, _scancode, action, mods):
        # Declared at the very top of the function (not just before the
        # Space/R/tempo branch that reassigns range_mode further down) --
        # Python requires a nonlocal declaration to precede every use of
        # that name within the function, including reads in the LEFT/RIGHT
        # branch just below, which only READS range_mode/auto_orbit but
        # still lives in the same function body as the branch that assigns
        # them.
        nonlocal auto_orbit, range_mode, tempo_ms
        if key in (glfw.KEY_LEFT, glfw.KEY_RIGHT):
            # [ADDED, Artur 2026-09-11: "sterowanie w przod i w tyl ...
            # strzalka lewo prawo jesli klikamy na uruchomionym to robi
            # pauze i przechodzimy w tryb manualny o n+1 z wcisnietym ctrl
            # o n+10 ... gdy puscimy wizualizacja kontynuuje, gdy uzywamy
            # strzalek na zatrzymanym to przewija ale nie uruchamia
            # wizualizacji"] Handled BEFORE the PRESS/REPEAT-only filter
            # below (unlike every other key here) because this is the one
            # control that also needs the RELEASE event, to resume playback
            # once scrubbing stops. See scrub_state's own comment (above,
            # near n_holder) for the held-count/was-running bookkeeping.
            ctrl_held = bool(mods & glfw.MOD_CONTROL)
            delta = arrow_scrub_delta(key == glfw.KEY_RIGHT, ctrl_held)
            if action in (glfw.PRESS, glfw.REPEAT):
                if action == glfw.PRESS:
                    if scrub_state["held"] == 0 and playback["running"]:
                        scrub_state["was_running"] = True
                        playback["running"] = False
                    scrub_state["held"] += 1
                # [FIXED, see Artur's 2026-09-11 "zatrzymalo sie bez resetu
                # nie ma mozliwosci wznowienia" report] clamp_scrub_n caps
                # this at the loaded ceiling in sequential mode -- see its
                # own doc-comment for why an unclamped scrub (especially
                # with OS key-repeat and the Ctrl 10x step both piling up
                # deltas fast) could run N so far past the ceiling that
                # nothing -- not even a plain Space press -- could resume
                # playback afterward.
                n_holder["n"] = clamp_scrub_n(n_holder["n"] + delta, range_mode, ceiling)
                # n_holder["n"] changing is what actually refreshes the HUD
                # (see the main loop's own `n_holder["n"] != last_n` branch,
                # which calls rebuild_buffer -> emit_hud_state at its end) --
                # no explicit emit_hud_state()/refresh_hud_texture() call
                # needed here, same as the plain Up/Down/PageUp/PageDown
                # keys just below.
            elif action == glfw.RELEASE:
                scrub_state["held"] = max(0, scrub_state["held"] - 1)
                if scrub_state["held"] == 0 and scrub_state["was_running"]:
                    scrub_state["was_running"] = False
                    # [FIXED, same 2026-09-11 report] Gate the auto-resume
                    # through the exact same guard Space uses, instead of
                    # blindly setting running=True -- even with the
                    # PRESS/REPEAT-side clamp above, scrubbing can still
                    # legitimately land exactly ON the ceiling (the same
                    # "end of loaded data" edge real forward playback
                    # ticking stops at on its own), which is a real,
                    # expected "nothing left to advance to" state, not a
                    # bug -- resuming from there should refuse (with the
                    # same message Space already prints) rather than
                    # silently claim playback is running when it can't
                    # actually advance.
                    if can_start_playback(n_holder["n"], range_mode, ceiling):
                        playback["running"] = True
                    else:
                        print("Playback: N is already at the loaded ceiling -- nothing left to advance to")
                    # Unlike PRESS/REPEAT above, N does NOT change here, so
                    # the main loop's own N-change branch will never fire on
                    # its own this frame -- without this explicit pair, the
                    # HUD panel's [Stopped]->[Running] text would lag behind
                    # the actual resume by up to one whole tempo_ms tick
                    # (same reasoning as the Space/tempo-key case below).
                    emit_hud_state()
                    refresh_hud_texture()
            return

        if key == glfw.KEY_F11:
            # [ADDED, Artur 2026-09-11] "przejście w tryb pełnoekranowy jak i
            # okienkowy wizualizację ustawiało na wartości zoom tak by
            # zajmowało pełną wysokość okna lub szerokość" -- re-fit zoom
            # (and recenter pan) after EITHER direction of the fullscreen
            # transition, since a viewport-size/aspect-ratio change makes the
            # OLD zoom value wrong for the NEW window regardless of which way
            # F11 just went. Measuring the framebuffer size before AND after
            # the toggle (rather than assuming it always changes) means a
            # toggle that fails outright (no monitors found -- see
            # FullscreenToggle.toggle()'s own early-return paths) leaves the
            # current view untouched instead of unexpectedly resetting it.
            before = glfw.get_framebuffer_size(window)
            fullscreen.handle_key(key, action)
            if action == glfw.PRESS:
                after = glfw.get_framebuffer_size(window)
                if after != before:
                    state["zoom"] = fit_zoom_for_viewport(max_radius, after[0], after[1])
                    state["pan"][0] = 0.0
                    state["pan"][1] = 0.0
            return
        if action not in (glfw.PRESS, glfw.REPEAT):
            return
        if key == glfw.KEY_ESCAPE:
            glfw.set_window_should_close(window, True)
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
            n_holder["n"] = max(0, n_holder["n"] + delta)
            return

        # [ADDED Faza 10, see PLAN.md] Playback controls -- gated to PRESS
        # only (not REPEAT), unlike the arrow keys above: these are
        # toggle/step actions, not continuous ones, so holding Space down
        # must not rapid-fire start/stop the way holding Up rapid-fires N
        # jumps.
        if action != glfw.PRESS:
            return
        if key == glfw.KEY_SPACE:
            # Ports #toggleRunning exactly: STOP always succeeds; START is
            # refused (with a message, mirroring the JS's own
            # "ss-info-ceiling-reached") once sequential mode has already
            # reached the loaded ceiling -- see can_start_playback's own
            # doc-comment.
            if playback["running"]:
                playback["running"] = False
            elif can_start_playback(n_holder["n"], range_mode, ceiling):
                playback["running"] = True
            else:
                print("Playback: N is already at the loaded ceiling -- nothing left to advance to")
        elif key == glfw.KEY_R:
            # Ports #reset exactly (the resetSequential()-calling half --
            # see this function's own module docstring "Controls:" entry
            # for R): stop playback, N=1, drop Track P, re-enable
            # auto-orbit, and fall back to sequential mode even if
            # --load-range was active at launch.
            playback["running"] = False
            track_primes.clear()
            auto_orbit = True
            range_mode = False
            orbit_state["index"] = 0
            orbit_state["counter"] = 0
            orbit_state["current_prime"] = None
            n_holder["n"] = 1
            n_holder["force_rebuild"] = True
        elif key in (glfw.KEY_RIGHT_BRACKET, glfw.KEY_EQUAL):
            # [FIXED, see Artur's 2026-09-06 "nie widzę różnicy" report]
            # Was a flat tempo_ms += 10 -- a barely-there ~8% change at the
            # 120ms default, and a rounding error at the low end (30ms) or
            # invisible at the high end (2000ms). Multiplicative scaling
            # (20% per press) stays proportionally noticeable across the
            # whole [30,2000] range, and the print gives Artur a way to
            # CONFIRM the value actually changed independent of whether
            # the animation itself looks any different to the eye.
            # KEY_EQUAL (the unshifted '=' key, i.e. the '+' position) is
            # accepted as an alias for KEY_RIGHT_BRACKET in case '[' / ']'
            # don't reach this callback at all on a given keyboard layout
            # -- '+' faster / '-' slower is also the more universal
            # media-player convention regardless.
            tempo_ms = clamp_tempo_ms(round(tempo_ms * 0.8))
            print(f"Tempo: {tempo_ms}ms/tick (faster)")
        elif key in (glfw.KEY_LEFT_BRACKET, glfw.KEY_MINUS):
            tempo_ms = clamp_tempo_ms(round(tempo_ms / 0.8))
            print(f"Tempo: {tempo_ms}ms/tick (slower)")

        # [ADDED Faza 11, see PLAN.md] Space/tempo changes update
        # playback["running"]/tempo_ms without necessarily triggering a
        # rebuild_buffer call this same frame (R's own force_rebuild=True
        # is the one exception, but re-emitting here too is harmless) --
        # re-emit right away so the HUD panel's running/tempo fields don't
        # lag behind a key press by up to one whole tempo_ms tick. Same
        # reasoning for refresh_hud_texture() -- the on-canvas HUD's own
        # running/tempo line would otherwise lag one tick behind too.
        emit_hud_state()
        refresh_hud_texture()

    glfw.set_scroll_callback(window, on_scroll)
    glfw.set_mouse_button_callback(window, on_mouse_button)
    glfw.set_cursor_pos_callback(window, on_cursor_pos)
    glfw.set_key_callback(window, on_key)

    last_n = n
    frame_count = 0
    fps_t0 = time.perf_counter()
    last_tick_time = time.perf_counter()

    while not glfw.window_should_close(window):
        glfw.poll_events()

        # [ADDED Faza 13, see PLAN.md] Live pause/resume -- only reachable
        # with command_queue set (--pipe-stdin-commands, see its own
        # doc-comment). A window-close request (Esc, titlebar X, or an OS
        # close) is intercepted HERE instead of being allowed to fall
        # through to the loop's own exit condition: we cancel the close,
        # hide the window, print a PAUSED marker line rings_tab.py's
        # _poll_queue recognizes (mirrors the existing HUD_STATE: prefix
        # convention), and idle -- still pumping the OS message loop via
        # wait_events_timeout so Windows doesn't mark it "Not Responding",
        # but doing zero rendering/audio work -- until either a "RESUME"
        # line arrives (show the window again, print RESUMED, fall through
        # to the normal frame below with everything -- n_holder, playback,
        # audio state -- untouched since none of it was ever torn down) or
        # stdin hits EOF (the __STDIN_CLOSED__ sentinel -- the Tkinter side
        # is gone, e.g. an explicit Reset already called proc.terminate(),
        # or Tkinter itself exited -- in which case there is no one left
        # to send RESUME, so let the real exit happen by leaving
        # window_should_close(window) True and breaking out of this
        # sub-loop; the outer while's own condition then ends the process).
        if command_queue is not None and glfw.window_should_close(window):
            glfw.set_window_should_close(window, False)
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
                            glfw.set_window_should_close(window, True)
                            paused = False
                except queue.Empty:
                    pass
            if glfw.window_should_close(window):
                break
            fullscreen.show_after_pause()
            print("RING_VIZ_RESUMED", flush=True)
            continue

        # [ADDED, Artur 2026-09-11, see extend_buffer_if_needed's own
        # doc-comment near n_holder above] Checked BEFORE the playback-tick
        # block below, every frame: if N has closed to within buffer_margin
        # of the loaded ceiling, extend the buffer now so tick_next_n's own
        # ceiling check (right below) essentially never actually fires for
        # a magazyn that still has more data to give.
        extend_buffer_if_needed()

        # [ADDED Faza 10, see PLAN.md] Playback loop -- ports #tick's own
        # setTimeout(tempoMs)-based scheduling as a plain elapsed-time check
        # against wall-clock time (this loop already runs every frame
        # uncapped -- see glfw.swap_interval(0) above -- so there is no
        # separate timer callback to install, just a gate on how often the
        # N-advance actually fires). tick_next_n's own should_stop covers
        # sequential mode reaching its ceiling (mirrors #tick's own
        # ceiling check, which STOPS rather than advancing past it) -- now
        # the rarely-exercised fallback for a magazyn that has genuinely run
        # out of data (extend_state["exhausted"]), not the normal outcome of
        # a long sequential playback run.
        if playback["running"]:
            now_tick = time.perf_counter()
            if (now_tick - last_tick_time) * 1000.0 >= tempo_ms:
                last_tick_time = now_tick
                new_n, should_stop = tick_next_n(n_holder["n"], range_mode, ceiling)
                if should_stop:
                    playback["running"] = False
                    print("Playback stopped: N reached the loaded ceiling")
                    # [ADDED Faza 11] N itself doesn't change on this branch,
                    # so no rebuild_buffer call (and thus no emit_hud_state)
                    # happens this frame -- emit directly so the panel's
                    # "running" field flips to stopped immediately instead
                    # of looking stuck on the last real tick's snapshot.
                    emit_hud_state()
                    refresh_hud_texture()
                else:
                    n_holder["n"] = new_n
                    n_holder["advancing"] = True

        if n_holder["n"] != last_n or n_holder["force_rebuild"]:
            last_n = n_holder["n"]
            advancing = n_holder["advancing"]
            vbo_normal, vbo_hit, new_ring_count, new_ring_count_hit = rebuild_buffer(
                last_n, prev_ring_count=ring_count, advancing=advancing
            )
            ring_count = new_ring_count
            ring_count_hit = new_ring_count_hit
            vao_normal = ctx.vertex_array(prog, [(vbo_normal, "2f 3f", "in_pos", "in_color")])
            vao_hit = ctx.vertex_array(prog, [(vbo_hit, "2f 3f", "in_pos", "in_color")])
            n_holder["advancing"] = False
            n_holder["force_rebuild"] = False

        width, height = glfw.get_framebuffer_size(window)
        ctx.viewport = (0, 0, width, height)
        ctx.clear(0.05, 0.05, 0.07)

        pan_x = state["pan"][0] + width / 2
        pan_y = state["pan"][1] + height / 2
        prog["u_pan"].value = (pan_x, pan_y)
        prog["u_zoom"].value = state["zoom"]
        prog["u_viewport"].value = (width, height)

        # [FIXED, see Faza 10's own empty-buffer note above] vertices=
        # ring_count(_hit) explicitly, rather than letting moderngl infer
        # the count from the vbo's own byte size -- needed now that a
        # 0-ring buffer is padded to a 1-vertex placeholder reservation
        # instead of a true zero-length allocation (inferring from buffer
        # size would otherwise draw that bogus placeholder vertex at the
        # origin).
        #
        # [ADDED Faza 11C, see PLAN.md] TWO draw calls, one per split buffer
        # from rebuild_buffer (see that function's own hit/normal split
        # comment), each with its own u_point_size uniform value -- this is
        # what actually makes --hit-point-size independent of --point-size
        # on screen. Normal rings drawn first, hit rings drawn last so they
        # stay visually on top of anything they'd otherwise overlap.
        prog["u_point_size"].value = args.point_size
        vao_normal.render(moderngl.POINTS, vertices=ring_count - ring_count_hit)
        prog["u_point_size"].value = hit_point_size
        vao_hit.render(moderngl.POINTS, vertices=ring_count_hit)

        # [ADDED Faza 8, see PLAN.md] Tracked-ring outline circles -- one
        # LINE_LOOP draw call per tracked-and-active ring over the shared
        # unit-circle buffer, scaled/positioned/colored per ring via
        # per-draw-call uniforms (see unit_circle_vertices' own doc-comment
        # for why a shared buffer rather than one per ring). Tracked-ring
        # counts are always small (user-typed or Faza-7-capped), so a few
        # extra draw calls per frame here is negligible next to the single
        # GL_POINTS call above carrying the real ring count.
        if outline_draws_holder["draws"]:
            prog_outline["u_pan"].value = (pan_x, pan_y)
            prog_outline["u_zoom"].value = state["zoom"]
            prog_outline["u_viewport"].value = (width, height)
            for radius, color in outline_draws_holder["draws"]:
                prog_outline["u_radius"].value = radius
                prog_outline["u_color"].value = color
                unit_circle_vao.render(moderngl.LINE_LOOP)

        # [ADDED Faza 8] Center marker -- fixed decorative triangle + glow
        # line at the ring field's own screen-space origin (pan_x, pan_y;
        # see build_center_marker_vertex_data's own doc-comment for why this
        # is the same point as u_pan above, not further scaled by zoom).
        s = marker_device_scale(width, height)
        triangle_data, line_data = build_center_marker_vertex_data(pan_x, pan_y, s)
        marker_triangle_vbo.write(triangle_data.tobytes())
        marker_line_vbo.write(line_data.tobytes())
        prog_screen["u_viewport"].value = (width, height)
        marker_triangle_vao.render(moderngl.TRIANGLES)
        marker_line_vao.render(moderngl.LINES)

        # [ADDED Faza 8] Birth/resonance flash overlays -- full-screen washes
        # that decay over subsequent frames after a trigger (see
        # rebuild_buffer's own Faza-8 comment for the trigger conditions).
        # Skipped entirely once decayed to 0 (the overwhelming majority of
        # frames) rather than drawing an alpha-0 quad every frame.
        if flash_state["resonance"] > 0.0:
            quad = build_flash_quad_vertex_data(
                width, height, flash_overlay_rgba(flash_state["resonance"], _FLASH_RESONANCE_RGB)
            )
            flash_quad_vbo.write(quad.tobytes())
            flash_quad_vao.render(moderngl.TRIANGLE_FAN)
            flash_state["resonance"] = decay_flash(flash_state["resonance"], 0.65)
        if flash_state["prime"] > 0.0:
            quad = build_flash_quad_vertex_data(
                width, height, flash_overlay_rgba(flash_state["prime"], _FLASH_PRIME_RGB)
            )
            flash_quad_vbo.write(quad.tobytes())
            flash_quad_vao.render(moderngl.TRIANGLE_FAN)
            flash_state["prime"] = decay_flash(flash_state["prime"], 0.85)

        # [ADDED Faza 11B, see PLAN.md] On-canvas HUD text quad -- drawn
        # LAST (after rings/outlines/marker/flash, right before the swap)
        # so it always sits on top, same as DrumRenderer's own #drawHud
        # being the final call in its own #renderFrame. hud_tex_holder is
        # only ever non-None when Pillow is installed AND the current HUD
        # text is non-empty (see refresh_hud_texture's own early-outs).
        if hud_tex_holder["tex"] is not None:
            hud_tex_holder["tex"].use(location=0)
            prog_text["u_tex"].value = 0
            prog_text["u_viewport"].value = (width, height)
            hud_quad_vao.render(moderngl.TRIANGLES)

        glfw.swap_buffers(window)

        frame_count += 1
        now = time.perf_counter()
        if now - fps_t0 >= 0.5:
            fps = frame_count / (now - fps_t0)
            glfw.set_window_title(
                window, f"PrimeAtlas -- Ring visualization  N={last_n:,}  rings={ring_count:,}  fps={fps:.1f}"
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
    parser.add_argument("--upto", type=int, default=1_000_000, help="upper bound for --source sieve/magazyn")
    parser.add_argument("--portal-folder", type=str, default=None, help="PrimeAtlas portal folder for --source magazyn")
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--point-size", type=float, default=3.0)
    # [ADDED Faza 11C, see PLAN.md] Independent point size for rings ON the
    # vertical reference line (pos["is_hit"] -- real divisors of N) --
    # Artur, 2026-09-07: wants to make these bigger/smaller separately from
    # every other ring, e.g. to spot factors of N at a glance without the
    # rest of the field growing too. Artur, 2026-09-09: set the default to
    # 40 outright (was None/"same as --point-size") so the axis rings are
    # readably distinct even when this flag isn't passed explicitly --
    # rings_tab.py's own GUI field is pre-filled with "40" to match (see
    # that file's own comment) -- the None-fallback-to-point-size behavior
    # in run()'s hit_point_size computation still applies if a caller
    # explicitly passes an empty/omitted value some other way.
    parser.add_argument("--hit-point-size", type=float, default=40.0,
                         help="point size for rings on the vertical reference line "
                              "(divisors of N); defaults to 40.0")
    # [ADDED Faza 11C] Font size (pixels) for the on-canvas HUD text (Faza
    # 11B) -- Artur, 2026-09-07: the original default (16px) was unreadably
    # small on his screen/resolution. rasterize_hud_text derives
    # margin/line-spacing from this value too, so scaling it up keeps the
    # whole HUD block proportional instead of just the glyphs. Artur,
    # 2026-09-09: bumped the default itself to 35 (see
    # _HUD_FONT_SIZE_DEFAULT above) rather than just relying on the GUI's
    # pre-filled field, so direct CLI use without the GUI is readable too.
    parser.add_argument("--hud-font-size", type=int, default=_HUD_FONT_SIZE_DEFAULT,
                         help="pixel size of the on-canvas HUD text (Faza 11B), default 35")
    parser.add_argument("--n-step", type=int, default=1000)
    # [ADDED Faza 4, see PLAN.md] Window-highlight-color parity with the
    # browser version's Bertrand/Legendre/General Law toggles -- comma list
    # of family ids among the three ring_geometry.WINDOW_FAMILY_COLORS keys.
    parser.add_argument("--windows", type=str, default="",
                         help="comma-separated window families to highlight: bertrand,legendre,generalLaw")
    parser.add_argument("--general-law-theta", type=float, default=0.5)
    parser.add_argument("--general-law-mode", choices=["stepped", "sliding"], default="stepped")
    # [ADDED Faza 6, see PLAN.md] Track P foundation -- comma-separated prime
    # values (same convention as --windows), and --auto-orbit as the
    # JS's #autoOrbit mode (auto-cycle active primes when nothing is
    # explicitly tracked). See rings_tab.py's Track P field docstring for
    # the launch-time-only rationale.
    parser.add_argument("--track-primes", type=str, default="",
                         help="comma-separated prime values to track, e.g. 2,3,5")
    parser.add_argument("--auto-orbit", action="store_true",
                         help="auto-cycle through active primes instead of a fixed Track P list")
    # [ADDED Faza 9, see PLAN.md] Load Range -- comma-separated FROM,TO (two
    # non-negative integers, FROM <= TO checked here; the "does TO actually
    # fit under what got loaded" check needs the real loaded `primes` array,
    # so that half happens in run() via load_prime_range_slice instead).
    parser.add_argument("--load-range", type=str, default="",
                         help="comma-separated FROM,TO -- switch to a fixed range mode showing exactly the "
                              "primes in [FROM,TO], auto-tracking all of them if there aren't too many")
    # [ADDED Faza 10, see PLAN.md] Playback speed -- ports #tempoMs's own
    # default (120ms/tick) and clamp range ([30,2000], see
    # clamp_tempo_ms's own doc-comment); Space starts/stops playback at
    # this rate, ]/[ adjust it live by +/-10ms per press.
    parser.add_argument("--tempo-ms", type=int, default=_TEMPO_MS_DEFAULT,
                         help="playback speed in ms/tick, clamped to [30,2000] "
                              "(Space starts/stops playback, ]/[ adjust it live)")
    # [ADDED Faza 13, see PLAN.md] Opt-in live pause/resume protocol -- OFF
    # by default so running this file directly from a terminal (Artur's own
    # manual testing, or anyone else's) behaves exactly as before: closing
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

    # [ADDED Faza 6, see PLAN.md] Validate --track-primes up front (same
    # fail-fast convention as --windows above) instead of letting a
    # malformed entry raise an uncaught ValueError later inside run()'s
    # own int(p.strip()) parsing.
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

    # [ADDED Faza 9, see PLAN.md] Same fail-fast format validation as
    # --track-primes/--windows above: catch a malformed --load-range before
    # run() ever starts loading primes, rather than raising an uncaught
    # ValueError/unpack error later. The "exceeds what got loaded" case
    # cannot be checked here (no `primes` array yet) -- see run()'s own
    # call to load_prime_range_slice for that half.
    if args.load_range:
        parts = args.load_range.split(",")
        if len(parts) != 2 or not all(p.strip().isdigit() for p in parts):
            parser.error(f"--load-range must be exactly two comma-separated non-negative integers FROM,TO, "
                         f"got {args.load_range!r}")
        load_from, load_to = int(parts[0]), int(parts[1])
        if load_from > load_to:
            parser.error(f"--load-range FROM must be <= TO, got {args.load_range!r}")

    run(args)


if __name__ == "__main__":
    main()
