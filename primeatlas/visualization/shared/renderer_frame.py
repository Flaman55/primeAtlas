"""
renderer_frame.py -- the draw calls of one renderer.py frame: ring points, the
active mode's segments, markers, outlines, boundary line, center marker, flash
overlays, world labels and the HUD quad, in back-to-front order. Takes the GL
resources and buffers renderer.py's main loop owns; swapping buffers stays there.
"""

import moderngl

from primeatlas.visualization.shared.draw_primitives import (
    marker_device_scale, build_center_marker_vertex_data, build_flash_quad_vertex_data,
)


def draw_frame(gl, session, mode_draw, point_size, size, vao_normal, vao_hit,
               ring_count, ring_count_hit):
    """Clears the framebuffer of `size` (width, height) and draws every layer for
    the current session state. `mode_draw` holds the active mode's uploaded
    marker/segment/label buffers (renderer.py's _upload_mode_draw_data);
    `point_size` is --point-size, used for the rings off the reference line."""
    width, height = size
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
    # TWO draw calls, one per split buffer from renderer.py's rebuild_buffer
    # (see that function's own hit/normal split comment), each with its own
    # u_point_size uniform value -- this is what actually makes
    # --hit-point-size independent of --point-size on screen. Normal
    # rings drawn first, hit rings drawn last so they stay visually on
    # top of anything they'd otherwise overlap.
    # The mode's own world-space segments, under every point.
    if mode_draw["segment_vao"] is not None:
        gl.prog_segment["u_pan"].value = (pan_x, pan_y)
        gl.prog_segment["u_zoom"].value = session.cam_zoom
        gl.prog_segment["u_viewport"].value = (width, height)
        mode_draw["segment_vao"].render(moderngl.LINES, vertices=mode_draw["segment_count"])

    gl.prog["u_point_size"].value = point_size
    vao_normal.render(moderngl.POINTS, vertices=ring_count - ring_count_hit)
    gl.prog["u_point_size"].value = gl.hit_point_size
    vao_hit.render(moderngl.POINTS, vertices=ring_count_hit)

    # The mode's own striped markers (each carries its own pixel size).
    if mode_draw["marker_vao"] is not None:
        gl.prog_marker["u_pan"].value = (pan_x, pan_y)
        gl.prog_marker["u_zoom"].value = session.cam_zoom
        gl.prog_marker["u_viewport"].value = (width, height)
        mode_draw["marker_vao"].render(moderngl.POINTS, vertices=mode_draw["marker_count"])

    # Tracked-ring outline circles -- one LINE_LOOP draw call per
    # tracked-and-active ring over the shared unit-circle buffer,
    # scaled/positioned/colored per ring via per-draw-call uniforms
    # (see unit_circle_vertices' own doc-comment for why a shared
    # buffer rather than one per ring). Tracked-ring counts are always
    # small (user-typed or capped, see tracked_resonance_state), so a
    # few extra draw calls per frame here is negligible next to the
    # single GL_POINTS call above carrying the real ring count.
    outline_draws = session.mode.outline_draws()
    if outline_draws:
        gl.prog_outline["u_pan"].value = (pan_x, pan_y)
        gl.prog_outline["u_zoom"].value = session.cam_zoom
        gl.prog_outline["u_viewport"].value = (width, height)
        for radius, color in outline_draws:
            gl.prog_outline["u_radius"].value = radius
            gl.prog_outline["u_color"].value = color
            gl.unit_circle_vao.render(moderngl.LINE_LOOP)

    # The mode's radial boundary marker (line mode's curved axis) -- a single red
    # LINE from the circle's own center out to its "12 o'clock" edge,
    # over the SAME prog_outline program/uniforms as the tracked-ring
    # outlines just above (see line_draw.axis_boundary_marker_vertices' own
    # doc-comment for why this needs marking at all: the loaded
    # window's own start and end coincide on screen once bent into a
    # circle, but are NOT actually the same value the way a real
    # periodic wraparound would be). session.mode.axis_boundary_radius() is
    # exactly the radius build_line_vertex_data itself used for this
    # frame's own layout -- world_width/2 for a plain circle, or the
    # spiral's own bigger outer-lap radius once a real wheel promotes
    # it to a spiral (see that function's own `boundary_radius`
    # doc-comment) -- so this single line always reaches all the way
    # out to the LAST lap actually drawn, crossing every lap's own
    # phase-zero point along the way (value_to_spiral_xy's own
    # doc-comment explains why one straight radial line does that for
    # every lap at once, with no separate per-lap marker needed).
    boundary_radius = session.mode.axis_boundary_radius()
    if boundary_radius:
        gl.prog_outline["u_pan"].value = (pan_x, pan_y)
        gl.prog_outline["u_zoom"].value = session.cam_zoom
        gl.prog_outline["u_viewport"].value = (width, height)
        gl.prog_outline["u_radius"].value = boundary_radius
        gl.prog_outline["u_color"].value = (1.0, 0.0, 0.0, 1.0)
        gl.axis_boundary_vao.render(moderngl.LINES)

    # Center marker -- fixed decorative triangle + glow line at the
    # ring field's own screen-space origin (pan_x, pan_y; see
    # build_center_marker_vertex_data's own doc-comment for why this is
    # the same point as u_pan above, not further scaled by zoom).
    gl.prog_screen["u_viewport"].value = (width, height)
    if session.mode.draws_center_marker:
        s = marker_device_scale(width, height)
        triangle_data, line_data = build_center_marker_vertex_data(pan_x, pan_y, s)
        gl.marker_triangle_vbo.write(triangle_data.tobytes())
        gl.marker_line_vbo.write(line_data.tobytes())
        gl.marker_triangle_vao.render(moderngl.TRIANGLES)
        gl.marker_line_vao.render(moderngl.LINES)

    # Flash overlays -- full-screen washes that decay over subsequent
    # frames after a trigger (see the active mode's rebuild for the trigger
    # conditions). session.mode.flash_overlays() lists only the overlays
    # not yet fully decayed (none, the overwhelming majority of frames),
    # so this skips the draw call entirely rather than drawing an alpha-0
    # quad every frame -- each decay only advances AFTER its draw.
    for flash_color, decay in session.mode.flash_overlays():
        quad = build_flash_quad_vertex_data(width, height, flash_color)
        gl.flash_quad_vbo.write(quad.tobytes())
        gl.flash_quad_vao.render(moderngl.TRIANGLE_FAN)
        decay()

    # World-anchored labels: screen quads recomputed from the camera every frame
    # (pan/zoom never re-rasterizes text), drawn under the HUD.
    if mode_draw["labels"] is not None and gl.label_tex_holder["tex"] is not None:
        quads = mode_draw["labels"].quads((pan_x, pan_y), session.cam_zoom, (width, height))
        if len(quads):
            mode_draw["label_vbo"].write(quads.tobytes())
            gl.label_tex_holder["tex"].use(location=0)
            gl.prog_text["u_tex"].value = 0
            gl.prog_text["u_viewport"].value = (width, height)
            mode_draw["label_vao"].render(moderngl.TRIANGLES, vertices=len(quads))

    # On-canvas HUD text quad -- drawn LAST (after
    # rings/outlines/marker/flash, right before the swap) so it always
    # sits on top, same as DrumRenderer's own #drawHud being the final
    # call in its own #renderFrame. hud_tex_holder is only ever
    # non-None when Pillow is installed AND the current HUD text is
    # non-empty (see renderer.py's _apply_hud_refresh early-outs).
    if gl.hud_tex_holder["tex"] is not None:
        gl.hud_tex_holder["tex"].use(location=0)
        gl.prog_text["u_tex"].value = 0
        gl.prog_text["u_viewport"].value = (width, height)
        gl.hud_quad_vao.render(moderngl.TRIANGLES)
