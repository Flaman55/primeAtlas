"""The Benchmark charts' hover tooltip on the tab's canvas: which drawn point the pointer is
over, where its tooltip fits, and the <Motion>/<Leave> bindings. benchmark_tab.py draws the
points and hands their pixel positions here.
"""
from tkinter import font as tkfont

from . import chart_points


def _nearest_point(hover_points, x, y, max_distance=14.0):
    """The whole hover_points tuple closest to (x, y) within max_distance pixels, or None."""
    best = None
    best_d2 = max_distance ** 2
    for point in hover_points:
        d2 = (x - point[0]) ** 2 + (y - point[1]) ** 2
        if d2 <= best_d2:
            best_d2 = d2
            best = point
    return best


def _nearest_hover_point(hover_points, x, y, max_distance=14.0):
    """Picks which (if any) of hover_points the cursor at (x, y) is "over" -- the one
    decision _bind_chart_hover's <Motion> handler needs to make, pulled out as a
    plain function with no canvas/tkinter dependency so it's directly unit-testable.
    (Driving this through a real OS-level synthetic mouse event in a test behaves
    inconsistently across platforms/Tk versions -- e.g. Windows Python 3.13 delivers
    <Motion> coordinates that don't reliably land within max_distance of a dot even
    when targeted at its exact pixel center -- whereas this pure function is
    deterministic and needs no live display at all.)

    hover_points: see _bind_chart_hover's own docstring for the tuple shape.
    Returns (px, py, x_val, y_val, fmt, color) for the closest point within
    max_distance pixels, or None if every point is farther than that (or the list
    is empty)."""
    best = _nearest_point(hover_points, x, y, max_distance)
    return tuple(best[:6]) if best else None


SAME_SPOT_PX = 6.0   # points this close to the nearest one share its tooltip


def _hover_points_at(hover_points, x, y, max_distance=14.0):
    """The hover_points sharing the spot under (x, y): the nearest one within max_distance
    and every other within SAME_SPOT_PX of it (a right-axis square on another line's
    circle), left-axis points first; [] when none is near."""
    best = _nearest_point(hover_points, x, y, max_distance)
    if best is None:
        return []
    group = [p for p in hover_points
             if (p[0] - best[0]) ** 2 + (p[1] - best[1]) ** 2 <= SAME_SPOT_PX ** 2]
    return sorted(group, key=lambda p: p[7] == "secondary")


def _hover_label_position(px, py, text_w, text_h, canvas_width, canvas_height, pad=4):
    """Decides where _on_motion (below) should anchor its tooltip TEXT item so it stays
    inside [0, canvas_width] x [0, canvas_height], given the point being labeled
    (px, py), the label's own already-measured pixel size (text_w, text_h -- see
    tkfont.Font.measure()/metrics("linespace") at the call site), and the canvas's
    LOGICAL size (the same width/height _draw_growth_chart's caller already computed,
    not a live canvas.winfo_width()/height() query -- see _bind_chart_hover's own
    docstring for why that distinction matters).

    Returns (tx, ty, anchor) ready for canvas.create_text(). Default placement is to
    the upper-right of the point (anchor="w", text growing rightward); flips to the
    LEFT (anchor="e") if the label wouldn't fit on the right, and flips from above to
    below the point if it wouldn't fit above -- without this, the tooltip for a point
    near the chart's right edge (the highest floor plotted, exactly where a user is
    most likely to hover) gets pushed off the visible canvas and clipped.

    Pulled out as a plain function (mirroring _nearest_hover_point above) specifically
    so this decision is directly unit-testable without a real Tk canvas or event loop:
    driving it through a synthetic <Motion> event on a probe canvas is as unreliable
    as _nearest_hover_point's own docstring describes for
    real OS-level mouse events, and for the same underlying reason here too -- a probe
    canvas packed onto an already-fully-laid-out test window may never actually become
    mapped/viewable, and Tk does not reliably deliver pointer events to an unmapped
    widget regardless of how the event is generated."""
    if px + 12 + text_w + pad <= canvas_width:
        tx, anchor = px + 12, "w"
    elif px - 12 - text_w - pad >= 0:
        tx, anchor = px - 12, "e"
    else:
        # Neither side fully fits (a very narrow canvas) -- pick the right side; the
        # bbox-clamp safety net in _on_motion pulls it back on-screen either way.
        tx, anchor = px + 12, "w"

    if py - 12 - text_h - pad >= 0:
        ty = py - 12
    elif py + 12 + text_h + pad <= canvas_height:
        ty = py + 12
    else:
        ty = py - 12

    return tx, ty, anchor


def _bind_chart_hover(canvas, hover_points, t, fg_color, bg_color, width, height,
                      x_mode=chart_points.X_FLOOR):
    """Wires a single-tooltip hover interaction onto `canvas` instead of drawing every
    point's value permanently next to its dot -- with a couple dozen closely-spaced
    floors, the always-on labels used to stack on top of each other into an unreadable
    smear. Only the point nearest the cursor
    (within a small pixel radius) gets a label, drawn fresh on every mouse move and
    cleared on <Leave>, so one spot's values are legible at a time no matter how dense
    the series is. Points drawn on the same spot (a right-axis square on another line's
    circle, _hover_points_at()) share the tooltip, one line each in its color, ● for the
    left axis and ■ for the right one.

    hover_points: a flat list of (px, py, x_val, y_val, fmt, color, label_key, axis)
    tuples in CANVAS pixel space, built by the caller from whichever series (primary
    and/or secondary) it already computed pixel coordinates for -- this function itself
    has no notion of axes/scales, just "here are some labeled dots".

    width/height: the SAME logical canvas size _draw_growth_chart's caller already
    computed and used for every other pad_left/plot_w/etc. calculation -- used here to
    keep the tooltip text on-screen instead of querying canvas.winfo_width()/winfo_height(). Those reflect the widget's
    actual REALIZED on-screen geometry, which can be stale or 1x1 whenever the canvas
    hasn't been mapped/redrawn yet at the moment a test (or a very fast resize) fires a
    motion event -- the caller's own width/height are always trustworthy since they're
    exactly what was just used to place every point on the canvas in the first place.

    Rebinding on every redraw (this is called once per _draw_growth_chart invocation,
    i.e. every resize/data refresh) is intentional and cheap: tkinter's bind() replaces
    the previous callback for the same event sequence on the same widget rather than
    stacking a new one alongside it, so this never leaks handlers, and each new callback
    closes over the CURRENT hover_points/scale rather than a stale one.

    x_mode: the chart's x axis (chart_points.X_FLOOR or X_WIDTH), which names a point's x
    in the tooltip ("floor (10^N) 28", "numbers sieved (log) 2x10^11")."""

    def _clear_tip():
        canvas.delete("hover_tip")

    def _on_leave(_event):
        _clear_tip()

    hover_font = ("Consolas", 9, "bold")
    _hover_font_metrics = tkfont.Font(family="Consolas", size=9, weight="bold")

    def _on_motion(event):
        _clear_tip()
        group = _hover_points_at(hover_points, event.x, event.y)
        if not group:
            return
        px, py = group[0][0], group[0][1]
        lines = [(("\u25a0 " if p[7] == "secondary" else "\u25cf ")
                  + f"{t(chart_points.AXIS_TITLE_KEYS[x_mode])} "
                  + f"{chart_points.x_label(p[2], x_mode)}: {p[4].format(p[3])}", p[5])
                 for p in group]
        for p in group:
            canvas.create_oval(p[0] - 6, p[1] - 6, p[0] + 6, p[1] + 6, outline=p[5], width=2,
                                tags="hover_tip")

        # The text's size, measured with the font that draws it, places the tooltip
        # analytically (_hover_label_position) instead of draw-measure-redraw. width/height
        # are _bind_chart_hover's own parameters (see its docstring), not
        # canvas.winfo_width()/height(), which read back stale values before the canvas
        # is mapped.
        pad = 4
        line_h = _hover_font_metrics.metrics("linespace")
        text_w = max(_hover_font_metrics.measure(text) for text, _color in lines)
        text_h = line_h * len(lines)
        tx, ty, anchor_x = _hover_label_position(px, py, text_w, text_h, width, height, pad)
        # One text item per point in its line's color, stacked around ty.
        for i, (text, color) in enumerate(lines):
            canvas.create_text(tx, ty - text_h / 2 + line_h * (i + 0.5), text=text,
                                anchor=anchor_x, fill=color, font=hover_font,
                                tags=("hover_tip", "hover_text"))
        bbox = canvas.bbox("hover_text")
        if bbox:
            # Clamp the drawn bbox back onto the canvas as a final safety net --
            # covers any residual overflow the estimate above didn't quite catch
            # (font metrics vs. actual glyph rendering can differ by a pixel or two).
            dx = 0
            if bbox[0] - pad < 0:
                dx = -(bbox[0] - pad)
            elif bbox[2] + pad > width:
                dx = width - (bbox[2] + pad)
            dy = 0
            if bbox[1] - pad < 0:
                dy = -(bbox[1] - pad)
            elif bbox[3] + pad > height:
                dy = height - (bbox[3] + pad)
            if dx or dy:
                canvas.move("hover_text", dx, dy)
                bbox = canvas.bbox("hover_text")
            box_id = canvas.create_rectangle(
                bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad,
                fill=bg_color, outline=group[0][5], tags="hover_tip")
            canvas.tag_lower(box_id, "hover_text")
        canvas.dtag("hover_text", "hover_text")

    canvas.bind("<Motion>", _on_motion)
    canvas.bind("<Leave>", _on_leave)
