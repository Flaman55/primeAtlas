"""
irreducibility_draw.py -- Canvas drawing for Research -> Irreducibility: a wrapped grid of
chips (modulus over radix, interval atoms), dials (one residue on its block modulus) and the
two sech combs C_a and C_b of the comb reading.

Every function clears the canvas (or the tag it draws) and reads the canvas width from the
widget, or from its configured width while it is not yet mapped. Chip and dial grids set the
canvas height to their content.
"""
import math

from .irreducibility_comb import last_peak, sech_comb

GOLD = "#c8961e"
GOLD_BG = "#fdf5e3"
COLOR_A = "#1f77b4"
COLOR_B = "#2ca02c"
COLOR_QUOT = "#888888"

_CHIP_W, _CHIP_H, _GAP = 58, 38, 4
_DIAL_W, _DIAL_H, _DIAL_R = 84, 104, 34
MAX_DIALS = 40
"""Dials drawn per number; the rest is summarised in one line."""


def canvas_width(canvas):
    w = canvas.winfo_width()
    return w if w >= 50 else int(canvas.cget("width"))


def draw_chips(canvas, chips, palette, tag="chip"):
    """chips: (top, bottom, marked) tuples. Draws them wrapped at the canvas width; marked
    chips get the gold frame and the extra tag 'gold'. Returns the height used."""
    canvas.delete("all")
    per_row = max(1, (canvas_width(canvas) + _GAP) // (_CHIP_W + _GAP))
    fg, line = palette["console_fg"], palette["border"]
    for i, (top, bottom, marked) in enumerate(chips):
        x = (i % per_row) * (_CHIP_W + _GAP) + 2
        y = (i // per_row) * (_CHIP_H + _GAP) + 2
        tags = (tag, "gold") if marked else (tag,)
        canvas.create_rectangle(x, y, x + _CHIP_W, y + _CHIP_H, tags=tags,
                                outline=GOLD if marked else line,
                                fill=GOLD_BG if marked else "")
        canvas.create_text(x + _CHIP_W / 2, y + 11, text=str(top), tags="label",
                           fill="#1d1d1f" if marked else fg)
        canvas.create_text(x + _CHIP_W / 2, y + 27, text=str(bottom), tags="label",
                           fill=GOLD if marked else fg, font=("TkDefaultFont", 9, "bold"))
    rows = -(-len(chips) // per_row) if chips else 0
    height = max(rows * (_CHIP_H + _GAP) + 4, 8)
    canvas.configure(height=height)
    return height


def draw_dials(canvas, dials, palette, more_text=""):
    """dials: (modulus, residue, color, label) tuples. One dial each: circle, ticks when the
    modulus is at most 120, a hand at the residue, 'residue/modulus' inside and the label
    under it. more_text is written after the last dial."""
    canvas.delete("all")
    per_row = max(1, canvas_width(canvas) // _DIAL_W)
    fg, line = palette["console_fg"], palette["border"]
    for i, (m, s, color, label) in enumerate(dials):
        ox = (i % per_row) * _DIAL_W
        oy = (i // per_row) * _DIAL_H
        cx, cy, R = ox + 42, oy + 42, _DIAL_R
        canvas.create_oval(cx - R, cy - R, cx + R, cy + R, outline=line, tags="dial")
        if m <= 120:
            for k in range(m):
                a = 2 * math.pi * k / m - math.pi / 2
                canvas.create_line(cx + (R - 4) * math.cos(a), cy + (R - 4) * math.sin(a),
                                   cx + R * math.cos(a), cy + R * math.sin(a), fill=line)
        a = 2 * math.pi * s / m - math.pi / 2
        canvas.create_line(cx, cy, cx + (R - 2) * math.cos(a), cy + (R - 2) * math.sin(a),
                           fill=color, width=2)
        canvas.create_oval(cx + R * math.cos(a) - 4, cy + R * math.sin(a) - 4,
                           cx + R * math.cos(a) + 4, cy + R * math.sin(a) + 4,
                           fill=color, outline=color)
        canvas.create_text(cx, cy + 4, text=f"{s}/{m}", fill=fg, font=("TkDefaultFont", 8))
        canvas.create_text(cx, oy + 94, text=label, fill=fg, font=("TkDefaultFont", 8))
    n = len(dials) + (1 if more_text else 0)
    if more_text:
        i = len(dials)
        canvas.create_text((i % per_row) * _DIAL_W + 4, (i // per_row) * _DIAL_H + 42,
                           text=more_text, anchor="w", fill=fg)
    rows = -(-n // per_row) if n else 0
    canvas.configure(height=max(rows * _DIAL_H, 8))


def draw_combs(canvas, a, b, s, palette):
    """C_a over the steps 0..a+2 on top, C_b below, both sampled finely and scaled to their
    maximum; the window from the last peak of C_b up to a shaded (tag 'window'), a dashed
    line at a (tag 'a_mark'), tick marks with a label every 5 steps."""
    canvas.delete("all")
    w = canvas_width(canvas)
    h = int(canvas.cget("height"))
    fg, line = palette["console_fg"], palette["border"]
    x0, span = 40, w - 52
    top_t = a + 2

    def x_of(t):
        return x0 + span * t / top_t

    def curve(d, base, tag, color):
        steps = max(400, top_t * 20)
        vals = [sech_comb(s, d, top_t * i / steps) for i in range(steps + 1)]
        mx = max(vals) or 1.0
        pts = []
        for i, v in enumerate(vals):
            pts += [x_of(top_t * i / steps), base - (h * 0.36) * v / mx]
        canvas.create_line(*pts, fill=color, width=1.5, tags=tag)

    last = last_peak(s, b, a)
    mid, bottom = h * 0.42, h * 0.86
    canvas.create_rectangle(x_of(last), mid + 6, x_of(a), bottom, fill=GOLD_BG, outline="",
                            tags="window")
    curve(a, mid, "comb_a", COLOR_A)
    curve(b, bottom, "comb_b", COLOR_B)
    canvas.create_line(x_of(a), 4, x_of(a), bottom + 2, fill=GOLD, dash=(4, 3), tags="a_mark")
    canvas.create_text(4, mid - h * 0.18, text=f"C_{a}", anchor="w", fill=fg)
    canvas.create_text(4, bottom - h * 0.18, text=f"C_{b}", anchor="w", fill=fg)
    for t in range(top_t + 1):
        canvas.create_line(x_of(t), bottom + 4, x_of(t), bottom + 8, fill=line)
        if t % 5 == 0:
            canvas.create_text(x_of(t), bottom + 10, text=str(t), anchor="n", fill=fg,
                               font=("TkDefaultFont", 8))
    return last
