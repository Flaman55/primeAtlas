"""
hud_text.py -- on-canvas HUD text shared by every visualization: the canvas
header+status wrapper (compose_hud_canvas_lines), Pillow text rasterization
(rasterize_hud_text) and the textured-quad geometry for that bitmap
(hud_quad_vertex_data).

Pillow is an optional dependency of THIS module only (see _PIL_AVAILABLE below) --
gl_setup.py imports `_PIL_AVAILABLE` from here to decide whether to allocate the
on-canvas HUD texture program/buffers at all, but never imports
Image/ImageDraw/ImageFont directly, since nothing outside rasterize_hud_text
touches them.
"""

import numpy as np


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
    window-range lines get their own family color). None (the default) draws
    every line in _HUD_TEXT_RGB; a line
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
