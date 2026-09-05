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
    Up / Down         change N by +/- --n-step (recomputes ring buffer)
    PageUp / PageDown change N by +/- 100 * --n-step (coarse jump)
    Esc               quit
"""

import argparse
import os
import sys
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
    active_window_count,
    tracked_ring_mask,
    legendre_level_at,
    general_law_window_bounds,
    tracked_resonance_state,
    format_big,
)


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


def load_magazyn(portal_folder, upto, progress_callback=None, batch_files=64):
    """Reads real primes up to `upto` from an existing PrimeAtlas portal
    folder, via primeatlas.storage's own file-listing helpers and
    prime_sieve_v1.read_prime_window for the actual decode.

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

    for base_exponent in storage.list_pietra(portal_folder):
        floor_lo = 10 ** base_exponent if base_exponent > 0 else 0
        if floor_lo > upto:
            break

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
                trimmed = arr[arr <= upto]
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
# Faza 8 (see PLAN.md) -- tracked-ring outline circles, birth/resonance flash
# overlays, center marker. Ports DrumRenderer.draw's `if (ring.tracked) {...}`
# outline-stroke branch, #drawCenterMarker, and the #drawFlashOverlay/
# triggerBirthFlash/triggerResonanceFlash trio.
#
# All of the ANCHOR/COLOR math these draw calls need (compute_tracked_colors,
# active_window_count) already existed in ring_geometry.py from Faza 1 --
# this phase's only new pure-math surface is the small amount below that is
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


def tracked_outline_color(active_window_count_value, matched, tracked_color_rgb):
    """Per-ring outline stroke (r, g, b, a) in 0..1 -- ports DrumRenderer's
    `ring.tracked` branch exactly:

        ctx.strokeStyle = (state.activeWindowCount > 1 && ring.trackedColor)
          ? hexToRgba(ring.trackedColor, 0.5)
          : "rgba(180,180,180,0.5)"

    `tracked_color_rgb` is a plain 0..255 (r, g, b) triple, already summed by
    ring_geometry.compute_tracked_colors for this ring -- this function only
    decides WHETHER to use it (via the `matched` flag from that same call),
    mirroring the JS's `&& ring.trackedColor` truthiness check: a real
    "no family matched" zero vector and a genuinely matched color are
    otherwise indistinguishable by value alone, so `matched` (not a
    non-zero check) is what compute_tracked_colors already returns for
    exactly this reason -- see that function's own doc-comment."""
    if active_window_count_value > 1 and matched:
        r, g, b = tracked_color_rgb
        return (r / 255.0, g / 255.0, b / 255.0, _TRACKED_OUTLINE_ALPHA)
    return (_TRACKED_OUTLINE_GRAY[0], _TRACKED_OUTLINE_GRAY[1], _TRACKED_OUTLINE_GRAY[2], _TRACKED_OUTLINE_ALPHA)


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
    active_count = active_window_count(enabled_ids)
    draws = []
    for i in np.nonzero(mask)[0]:
        draws.append((float(radii[i]), tracked_outline_color(active_count, bool(matched[i]), tuple(colors[i]))))
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


def run(args):
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

    print(f"Loading primes via --source={args.source} ...")
    t0 = time.perf_counter()
    if args.source == "synthetic":
        primes = load_synthetic(args.count)
    elif args.source == "sieve":
        primes = load_sieve(args.upto)
    elif args.source == "magazyn":
        primes = load_magazyn(args.portal_folder, args.upto)
    else:
        raise ValueError(f"unknown --source {args.source!r}")
    t1 = time.perf_counter()
    print(f"Loaded {len(primes):,} values in {t1 - t0:.2f}s")

    n = initial_n_for_source(args.source, args.upto, primes)
    max_radius = min(args.width, args.height) * 0.45

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

    def rebuild_buffer(n_value, prev_ring_count=None):
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
        for line in hud_lines_for_n(active, n_value, pos, enabled_ids, theta, law_mode, tracked_state):
            print(line)

        # [ADDED Faza 8] Tracked-ring outline circles -- recomputed here
        # alongside the main buffer, same N-change-only cadence.
        outline_draws_holder["draws"] = build_tracked_outline_draws(
            active, n_value, enabled_ids, theta, law_mode, track_primes, pos["radius"]
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

        return ctx.buffer(data.tobytes()), count

    vbo, ring_count = rebuild_buffer(n)
    vao = ctx.vertex_array(prog, [(vbo, "2f 3f", "in_pos", "in_color")])

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

    def on_cursor_pos(_window, x, y):
        lx, ly = state["last_mouse"]
        if state["dragging"]:
            state["pan"][0] += x - lx
            state["pan"][1] += y - ly
        state["last_mouse"] = (x, y)

    n_holder = {"n": n}

    def on_key(_window, key, _scancode, action, _mods):
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

    glfw.set_scroll_callback(window, on_scroll)
    glfw.set_mouse_button_callback(window, on_mouse_button)
    glfw.set_cursor_pos_callback(window, on_cursor_pos)
    glfw.set_key_callback(window, on_key)

    last_n = n
    frame_count = 0
    fps_t0 = time.perf_counter()

    while not glfw.window_should_close(window):
        glfw.poll_events()

        if n_holder["n"] != last_n:
            last_n = n_holder["n"]
            vbo, new_ring_count = rebuild_buffer(last_n, prev_ring_count=ring_count)
            ring_count = new_ring_count
            vao = ctx.vertex_array(prog, [(vbo, "2f 3f", "in_pos", "in_color")])

        width, height = glfw.get_framebuffer_size(window)
        ctx.viewport = (0, 0, width, height)
        ctx.clear(0.05, 0.05, 0.07)

        pan_x = state["pan"][0] + width / 2
        pan_y = state["pan"][1] + height / 2
        prog["u_pan"].value = (pan_x, pan_y)
        prog["u_zoom"].value = state["zoom"]
        prog["u_viewport"].value = (width, height)

        vao.render(moderngl.POINTS)

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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=["synthetic", "sieve", "magazyn"], default="synthetic")
    parser.add_argument("--count", type=int, default=1_000_000, help="ring count for --source synthetic")
    parser.add_argument("--upto", type=int, default=1_000_000, help="upper bound for --source sieve/magazyn")
    parser.add_argument("--portal-folder", type=str, default=None, help="PrimeAtlas portal folder for --source magazyn")
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--point-size", type=float, default=3.0)
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
