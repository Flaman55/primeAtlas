"""
hud.py -- on-canvas/console HUD text composition and rasterization for
primeatlas/rings/ring_viz/renderer.py: the plain-text HUD line builder
(hud_lines_for_n), the canvas header+status wrapper (compose_hud_canvas_
lines), per-line window-family coloring (hud_line_colors), Pillow text
rasterization (rasterize_hud_text), the textured-quad geometry for that
bitmap (hud_quad_vertex_data), and the live-audio-tick bridge
(emit_audio_tick). Part of the renderer.py split -- see renderer.py's own
module docstring for the overall module breakdown.

Pillow is an optional dependency of THIS module only (see _PIL_AVAILABLE
below) -- renderer.py's own GL setup imports `_PIL_AVAILABLE` from here to
decide whether to allocate the on-canvas HUD texture program/buffers at
all, but never imports Image/ImageDraw/ImageFont directly, since nothing
outside rasterize_hud_text touches them.

Self-contained sys.path bootstrap (mirrors renderer.py's own -- see that
file's module docstring for the full "why plain-script-path" explanation):
needed so `from primeatlas.rings.ring_geometry import ...` below works whether
this module is imported after renderer.py has already run its own
bootstrap, or on its own (e.g. directly from a test).
"""

import os
import sys

import numpy as np

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # ring_viz/ now lives one directory deeper, under primeatlas/rings/
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_PRIME_SIEVE_DIR = os.path.join(_REPO_ROOT, "prime_sieve")
if _PRIME_SIEVE_DIR not in sys.path:
    sys.path.insert(0, _PRIME_SIEVE_DIR)

from primeatlas.rings.ring_geometry import (
    format_big,
    legendre_level_at,
    general_law_window_bounds,
    nested_shell_colors,
    WINDOW_FAMILY_COLORS,
)

# On-canvas GL HUD text -- Pillow is used only
# to RASTERIZE plain text into an RGBA bitmap (PIL.ImageFont.load_default(),
# no external .ttf needed) once per HUD-content change, which is then
# uploaded as an ordinary moderngl texture and drawn as a single
# screen-space textured quad (see rasterize_hud_text / renderer.py's own
# `refresh_hud_texture` closure). Guarded so a machine without Pillow
# installed still runs every other feature of this module unchanged -- only
# the on-canvas HUD silently stays off (one console line explains why),
# same "optional dependency, never a hard crash" convention this project
# already uses for sympy (see primality.py's own module docstring).
try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False


def hud_lines_for_n(primes_active, n, pos, enabled_ids, theta, mode, tracked_state=None):
    """Ports the non-tracked-primes subset of DrumRenderer's #drawHud /
    StructuralSieveApp's #renderFrame draw-state construction (see those
    methods' own doc-comments in js/render/DrumRenderer.js and
    js/app/StructuralSieveApp.js in the RelationalMathematics repo) as
    PLAIN TEXT LINES printed to stdout, rather than drawn as an in-GL-window
    overlay.

    Why stdout and not a GL text overlay: this project has no OpenGL
    text-rendering pipeline (glyph atlas / freetype / textured-quad-per-glyph
    shader) -- building one from scratch here would be a real new subsystem,
    and one this sandbox (no GPU/display) could not visually verify at all
    before landing it. rings_tab.py's GenerationConsole pane is already
    proven working on real hardware, since LocalLoggedRunner pipes this
    module's stdout straight into it -- reusing that live text surface for
    HUD info is lower-risk than shipping unverified GL text rendering.

    `tracked_state` -- the already-computed result of
    ring_geometry.tracked_resonance_state(...)
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
    # n=0 is range/fixed mode's own placeholder starting value (see run()'s
    # own "n = 0 mirrors the JS's own this.#n = 0" comment) -- but
    # phase = n mod prime is trivially 0 for EVERY prime when n=0, so
    # pos["is_hit"] was True for ALL of them, and the line below joined
    # every single active ring's value into one string. That was survivable
    # when this feature only ever saw a handful of active primes; a real
    # arbitrary-range load can auto-track/activate thousands of ~26-digit
    # values at once, turning this into a single tens-of-thousands-of-
    # characters line that stalls (or silently fails) HUD text
    # rasterization -- never a MEANINGFUL "factors of N" list either, since
    # N=0 has no real factorization. Skipped outright for n==0; any n>=1
    # still gets its real (and normally small) divisor list exactly as
    # before.
    if n != 0:
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
        # [ADDED 2026-09-26] Two RIGID modes -- theta is a locked display
        # value there (see renderer.py's own --general-law-mode argparse),
        # not a live parameter, so it's left out of the text entirely and the
        # mode's real name stands in for it instead. 'legendre' shows k (a
        # real, meaningful level here, unlike 'bertrand'); neither has a tent
        # factor to report (that's 'stepped'-only).
        if mode == "stepped":
            lines.append(f"General Law window (theta={theta}, k={k}): ({lo_floor:,}, {hi:,}]")
        elif mode == "bertrand":
            lines.append(f"General Law window (Bertrand): ({lo_floor:,}, {hi:,}]")
        elif mode == "legendre":
            lines.append(f"General Law window (Legendre, k={k}): ({lo_floor:,}, {hi:,}]")
        else:
            lines.append(f"General Law window (theta={theta}): ({lo_floor:,}, {hi:,}]")

    # [ADDED 2026-09-26, REDESIGNED same day -- see ring_geometry.
    # nested_shell_colors' own doc-comment] A small color LEGEND -- one line
    # per distinct NESTING SHELL among currently-enabled families (not every
    # pairwise combination), in that shell's own averaged color, so a viewer
    # can look up what a blended ring's color actually means. No numeric
    # window bounds here -- a shell has no single window of its own to
    # report, just a color to name.
    family_order = list(WINDOW_FAMILY_COLORS.keys())
    for shell_ids, _color in nested_shell_colors(enabled_ids, n, theta, mode).items():
        ordered = sorted(shell_ids, key=family_order.index)
        lines.append(_shell_line_prefix(ordered))

    return lines


def pattern_hud_line(n, offsets, all_match, wheel_modulus=None, wheel_residue_count=None,
                      step_mode="manual", stop_on_match=False, view_mode=None, line_axis_curved=False):
    """The single HUD text line for "line" viz-mode's k-tuple pattern
    status: the anchor N, its offsets, whether every member currently
    lands on a real prime, (when a wheel is active, see
    ring_geometry.pattern_wheel_residues) the candidate density the wheel
    skip is scanning at -- `wheel_residue_count=0` prints the "can never
    repeat" case rather than a silent 0/M -- and the current Manual/Auto +
    MATCH! regime (see RenderSession._pattern_uses_seek's own doc-comment
    for the exact rule this describes: "manual" shows every wheel
    candidate in turn; "auto" always seeks, for a MATCH! when checked or
    for a non-match when unchecked). Returned as a plain string so the
    caller (RenderSession.rebuild_line) can drop it straight into
    `self.hud_lines` -- compose_hud_canvas_lines below already just
    appends whatever strings that list holds.

    `view_mode` -- ring_geometry.line_view_bounds' own "full"/"local" flag
    (build_line_vertex_data's return value, forwarded verbatim by
    RenderSession.rebuild_line) -- printed only when "local", so Artur can
    tell at a glance the renderer switched to the anchor-centered
    viewport (float32-precision fallback for a real archive-scale window,
    see line_view_bounds' own doc-comment) instead of showing the whole
    loaded range at once; None or "full" adds nothing, matching this
    line's own pre-existing text for every case before this fallback
    existed.

    `line_axis_curved` -- RenderSession.line_axis_curved's own value
    (2026-09-18/19 follow-up): when True, reports which curved layout is
    actually active this frame -- "[axis: spiral]" once a real wheel
    (`wheel_modulus > 1`) promotes it from a single circle to a spiral
    (see build_line_vertex_data's own `wheel_modulus` doc-comment), or
    "[axis: ring]" for the plain single-circle case (no pattern, or a
    pattern whose wheel excludes nothing). False (default, unchanged)
    adds nothing, matching every straight-axis HUD line before this
    feature existed."""
    suffix = "  MATCH!" if all_match else ""
    wheel_text = ""
    if wheel_modulus is not None and wheel_modulus > 1:
        if wheel_residue_count:
            wheel_text = f"  wheel={wheel_modulus} ({wheel_residue_count}/{wheel_modulus} candidates/period)"
        else:
            wheel_text = f"  wheel={wheel_modulus} (0/{wheel_modulus} -- this pattern can never repeat)"
    if step_mode == "auto":
        mode_text = "  [auto: seek MATCH!]" if stop_on_match else "  [auto: seek non-match]"
    else:
        mode_text = "  [manual]"
    view_text = "  [view: local]" if view_mode == "local" else ""
    if line_axis_curved:
        axis_text = "  [axis: spiral]" if (wheel_modulus is not None and wheel_modulus > 1) else "  [axis: ring]"
    else:
        axis_text = ""
    return f"Pattern: n={n:,} offsets={list(offsets)}{suffix}{wheel_text}{mode_text}{view_text}{axis_text}"


# ---------------------------------------------------------------------------
# On-canvas GL HUD text. Ports the actual DrumRenderer.#drawHud text overlay
# itself (the part hud_lines_for_n above deliberately did NOT port -- see
# that function's own doc-comment, written back when this sandbox had no way
# to visually verify GL text rendering at all). The console pane and
# rings_tab.py's side panel both show this same text, but neither is the GL
# window itself, which is where the HUD overlay actually needs to be drawn.
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

#: The fixed leading text hud_lines_for_n uses for each window family's own
#: range line -- see hud_line_colors' own doc-comment for why matching is
#: done by text prefix rather than by line position.
_HUD_WINDOW_LINE_PREFIXES = {
    "bertrand": "Bertrand window:",
    "legendre": "Legendre window:",
    "generalLaw": "General Law window",
}

#: [ADDED 2026-09-26] Human-readable display name per family id, used only
#: to build the dynamic nested-shell color-legend lines below -- separate
#: from _HUD_WINDOW_LINE_PREFIXES's own "<Name> window:" text since a shell
#: has no single window of its own to report bounds for, just a color to
#: name.
_FAMILY_DISPLAY_NAMES = {
    "bertrand": "Bertrand",
    "legendre": "Legendre",
    "generalLaw": "General Law",
}


def _shell_line_prefix(family_ids):
    """The fixed leading text for a nested-shell color-legend HUD line, e.g.
    "Bertrand + Legendre:" or "Bertrand + Legendre + General Law:" -- called
    from BOTH hud_lines_for_n (which builds the line) and hud_line_colors
    (which matches it back to a color) so the two can never drift apart,
    same "single shared helper" reasoning _HUD_WINDOW_LINE_PREFIXES's own
    docstring gives for the single-family case. `family_ids` is expected
    pre-sorted into registry order by the caller (see
    ring_geometry.nested_shell_colors' own doc-comment) and to have at least
    2 entries (a 1-family "shell" is just that family's own existing line,
    never built here)."""
    return " + ".join(_FAMILY_DISPLAY_NAMES[fid] for fid in family_ids) + ":"


def hud_line_colors(lines, window_colors, shell_colors=None):
    """Parallel per-line RGB color list, same length as `lines`
    (hud_lines_for_n's own text output, or compose_hud_canvas_lines' header+
    lines combination -- either works, since neither the header nor any
    Factors-of-N/Tracked-block line matches a window prefix and therefore
    all fall through to the flat default).

    Every line defaults to _HUD_TEXT_RGB EXCEPT a window-range line
    (identified by its own fixed leading text, see
    _HUD_WINDOW_LINE_PREFIXES), which gets that family's own plain,
    unconditional color from `window_colors` (ring_geometry.
    window_label_colors' output -- see that function's own doc-comment for
    why it's back to a plain per-family lookup, no blending, as of
    2026-09-26 -- blending moved to the nested-shell legend lines below).

    Matches by TEXT PREFIX rather than by position/index so this stays
    correct even if hud_lines_for_n's own Factors-of-N/Tracked-block line
    count changes later -- the window-range lines are always identifiable
    by their own fixed leading text regardless of what precedes them.

    `shell_colors` -- [ADDED 2026-09-26] optional dict from ring_geometry.
    nested_shell_colors (frozenset(family ids) -> (r,g,b)), matched the same
    prefix-text way via _shell_line_prefix -- colors the new nested-shell
    color-legend lines hud_lines_for_n now appends. None (the default)
    simply means no shell lines will match, i.e. they'd fall through to the
    flat default color -- callers that DO enable those lines should always
    pass the matching dict, same convention `window_colors` already has (an
    empty/wrong dict there just means those lines fall back to
    _HUD_TEXT_RGB too, never an error)."""
    shell_colors = shell_colors or {}
    family_order = list(WINDOW_FAMILY_COLORS.keys())
    colors = []
    for line in lines:
        color = _HUD_TEXT_RGB
        matched = False
        for family_id, prefix in _HUD_WINDOW_LINE_PREFIXES.items():
            if line.startswith(prefix):
                color = window_colors.get(family_id, _HUD_TEXT_RGB)
                matched = True
                break
        if not matched:
            for shell_ids, scolor in shell_colors.items():
                ordered = sorted(shell_ids, key=family_order.index)
                if line.startswith(_shell_line_prefix(ordered)):
                    color = scolor
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
    logic, no risk of a missing-file crash).

    `font_size` -- pixel size of the glyphs, forwarded to
    load_default(size=...) (Pillow >= 10.1's own scalable bitmap default
    font). A fixed 16px default is unreadably small on high-DPI displays,
    so it's exposed as --hud-font-size, a launch-time choice rather than a
    hand-edited constant. Margin and line-spacing are DERIVED from
    font_size (roughly half and a quarter of it) rather than fixed pixel
    constants, so the whole HUD block stays proportional at any size
    instead of the padding looking tiny next to huge text or huge next to
    tiny text.

    Returns None for an empty `lines` list (nothing to draw -- caller should
    leave any existing HUD texture as-is or skip drawing entirely) or if
    Pillow is not installed (`_PIL_AVAILABLE` is the caller's own guard;
    this function still defends itself in case it's ever called directly).

    `line_colors` -- optional list of (r, g, b) tuples,
    one per entry in `lines`, drawn instead of the flat _HUD_TEXT_RGB for
    that line (see hud_line_colors, which builds this list from
    ring_geometry.window_label_colors so the Bertrand/Legendre/General Law
    window-range lines get their own family color, or a shared averaged
    color when two enabled families' windows genuinely overlap). None (the
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
