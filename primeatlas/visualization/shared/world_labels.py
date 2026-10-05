"""
world_labels.py -- text labels anchored to world positions and drawn at a fixed pixel
size, for any viz-mode (VizMode.world_labels). Every label is rasterized once per
rebuild into one RGBA atlas (Pillow, like hud_text.py); each frame only the screen quads
are recomputed from the camera, so pan/zoom never re-rasterizes text.

Level of detail: a label may carry `room`, the horizontal world space it may use. It is
drawn only once room * zoom covers its pixel width, so dense labels appear as the view
zooms in instead of piling up at the fitted view.

Pure numpy/Pillow, no GL: the renderer uploads the atlas as a texture and the quads to
a buffer drawn with the HUD's text program (pixel-space positions + uv).
"""

from dataclasses import dataclass

import numpy as np

from primeatlas.visualization.shared.hud_text import _PIL_AVAILABLE

if _PIL_AVAILABLE:
    from PIL import Image, ImageDraw, ImageFont

ANCHOR_RIGHT_OF = "right_of"
ANCHOR_LEFT_OF = "left_of"
ANCHOR_ABOVE = "above"
_ANCHOR_CODES = {ANCHOR_RIGHT_OF: 0, ANCHOR_LEFT_OF: 1, ANCHOR_ABOVE: 2}

_ATLAS_MAX_WIDTH = 2048
_ATLAS_MAX_HEIGHT = 8192
_ATLAS_PADDING = 1


@dataclass
class WorldLabel:
    """`text` drawn in `rgb` (0..1 floats) next to world point (x, y). `anchor`: the
    text sits right of the point, left of it, or centered above it. `room`: world width
    the label may use (None = always drawn)."""
    x: float
    y: float
    text: str
    rgb: tuple
    room: float = None
    anchor: str = ANCHOR_RIGHT_OF


def label_visible(width_px, room, zoom):
    """True when a `width_px`-wide label fits its `room` at this zoom."""
    return room is None or room * zoom >= width_px


def _load_font(font_size):
    try:
        return ImageFont.load_default(size=font_size)
    except TypeError:
        return ImageFont.load_default()


def build_label_atlas(labels, font_size, max_width=_ATLAS_MAX_WIDTH, max_height=_ATLAS_MAX_HEIGHT):
    """Rasterizes every label into one RGBA atlas. Returns (rgba_or_None, sizes,
    rects): sizes[i] = (w, h) pixels, rects[i] = (u0, v0, u1, v1) in the atlas (v down,
    like the HUD texture). Identical (text, color) pairs share one image. A label that
    no longer fits under max_height gets size (0, 0) and is never drawn. Returns
    (None, [], []) without labels or without Pillow."""
    if not labels or not _PIL_AVAILABLE:
        return None, [], []
    font = _load_font(font_size)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    keys = []
    boxes = {}
    for label in labels:
        key = (label.text, tuple(round(c, 4) for c in label.rgb))
        keys.append(key)
        if key not in boxes:
            boxes[key] = probe.textbbox((0, 0), label.text, font=font)

    placements = {}
    x = y = row_height = 0
    used_width = 0
    for key, box in boxes.items():
        w = max(1, box[2] - box[0])
        h = max(1, box[3] - box[1])
        if x + w > max_width:
            x = 0
            y += row_height + _ATLAS_PADDING
            row_height = 0
        if y + h > max_height:
            placements[key] = None
            continue
        placements[key] = (x, y, w, h)
        x += w + _ATLAS_PADDING
        row_height = max(row_height, h)
        used_width = max(used_width, x)
    atlas_w = max(1, used_width)
    atlas_h = max(1, y + row_height)

    img = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for key, place in placements.items():
        if place is None:
            continue
        px, py, _, _ = place
        box = boxes[key]
        rgb = tuple(int(round(c * 255)) for c in key[1])
        draw.text((px - box[0], py - box[1]), key[0], font=font, fill=rgb + (255,))

    sizes, rects = [], []
    for key in keys:
        place = placements[key]
        if place is None:
            sizes.append((0, 0))
            rects.append((0.0, 0.0, 0.0, 0.0))
            continue
        px, py, w, h = place
        sizes.append((w, h))
        rects.append((px / atlas_w, py / atlas_h, (px + w) / atlas_w, (py + h) / atlas_h))
    return np.asarray(img, dtype=np.uint8), sizes, rects


class LabelLayout:
    """The per-rebuild label arrays, so each frame's quads are one vectorized pass."""

    def __init__(self, labels, sizes, rects):
        count = len(labels)
        self.wx = np.array([l.x for l in labels], dtype=np.float64)
        self.wy = np.array([l.y for l in labels], dtype=np.float64)
        self.room = np.array([np.inf if l.room is None else l.room for l in labels], dtype=np.float64)
        self.anchor = np.array([_ANCHOR_CODES[l.anchor] for l in labels], dtype=np.int8)
        self.w = np.array([s[0] for s in sizes], dtype=np.float64).reshape(count)
        self.h = np.array([s[1] for s in sizes], dtype=np.float64).reshape(count)
        self.uv = np.array(rects, dtype=np.float32).reshape(count, 4)

    def __len__(self):
        return len(self.wx)

    def quads(self, pan, zoom, viewport, offset_px=6.0):
        """(6 * visible, 4) float32 pixel-space (x, y, u, v) vertices: two triangles per
        label that fits its room and touches the viewport."""
        if not len(self):
            return np.zeros((0, 4), dtype=np.float32)
        sx = self.wx * zoom + pan[0]
        sy = self.wy * zoom + pan[1]
        x0 = np.where(self.anchor == 0, sx + offset_px,
                      np.where(self.anchor == 1, sx - offset_px - self.w, sx - self.w / 2))
        y0 = np.where(self.anchor == 2, sy - offset_px - self.h, sy - self.h / 2)
        x1 = x0 + self.w
        y1 = y0 + self.h
        width, height = viewport
        visible = ((self.w > 0) & (self.room * zoom >= self.w)
                   & (x1 >= 0) & (x0 <= width) & (y1 >= 0) & (y0 <= height))
        if not visible.any():
            return np.zeros((0, 4), dtype=np.float32)
        x0, y0, x1, y1 = x0[visible], y0[visible], x1[visible], y1[visible]
        u0, v0, u1, v1 = (self.uv[visible, i] for i in range(4))
        corners = [(x0, y0, u0, v0), (x1, y0, u1, v0), (x1, y1, u1, v1),
                   (x0, y0, u0, v0), (x1, y1, u1, v1), (x0, y1, u0, v1)]
        out = np.empty((len(x0), 6, 4), dtype=np.float32)
        for i, (cx, cy, cu, cv) in enumerate(corners):
            out[:, i, 0] = cx
            out[:, i, 1] = cy
            out[:, i, 2] = cu
            out[:, i, 3] = cv
        return out.reshape(-1, 4)


def label_screen_quads(labels, sizes, rects, pan, zoom, viewport, offset_px=6.0):
    """One-shot form of LabelLayout(labels, sizes, rects).quads(...)."""
    return LabelLayout(labels, sizes, rects).quads(pan, zoom, viewport, offset_px)
