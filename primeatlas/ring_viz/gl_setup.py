"""
gl_setup.py -- window/context/shader-program/VAO/VBO creation for
primeatlas/ring_viz/renderer.py's `_run_visualization`. [ADDED Faza 5 of
the renderer.py split, see renderer.py's own module docstring for the
overall refactor plan this continues.]

This is the one piece of the split that genuinely CANNOT be made GL-free
(unlike geometry_draw.py/hud.py/playback.py/session.py) -- creating a
window, an OpenGL context, and every shader program/VAO/VBO the renderer
needs is unavoidably GL-bound, one-time, sequential setup work. Pulling it
out of _run_visualization does not make it any more unit-testable (it
still needs a real display/GPU, exactly as before), but it DOES separate
"what GL objects exist and how they're wired together at startup" from
"what happens every frame" -- the two were tangled together in
_run_visualization before this split.

setup_gl_resources(args) returns a single GLResources instance bundling
every created object under one name, rather than the ~16 loose local
variables _run_visualization used to juggle for this (window, ctx, prog,
hit_point_size, prog_outline, unit_circle_vao, prog_screen,
marker_triangle_vbo/vao, marker_line_vbo/vao, flash_quad_vbo/vao,
prog_text, hud_quad_vbo/vao, hud_tex_holder).
"""

from primeatlas.ring_viz.shaders import (
    VERTEX_SHADER,
    FRAGMENT_SHADER,
    OUTLINE_VERTEX_SHADER,
    OUTLINE_FRAGMENT_SHADER,
    SCREEN_VERTEX_SHADER,
    SCREEN_FRAGMENT_SHADER,
    TEXT_VERTEX_SHADER,
    TEXT_FRAGMENT_SHADER,
)
from primeatlas.ring_viz.geometry_draw import unit_circle_vertices
from primeatlas.ring_viz.hud import _PIL_AVAILABLE


class GLResources:
    """Plain bag of every GL object _run_visualization's main loop and
    callbacks need, created once at startup by setup_gl_resources(). No
    behavior of its own beyond make_ring_vao() (see that method's own
    doc-comment for why it lives here rather than as a bare module
    function)."""

    def __init__(self, window, ctx, prog, hit_point_size, prog_outline,
                 unit_circle_vao, prog_screen, marker_triangle_vbo,
                 marker_triangle_vao, marker_line_vbo, marker_line_vao,
                 flash_quad_vbo, flash_quad_vao, prog_text, hud_quad_vbo,
                 hud_quad_vao):
        self.window = window
        self.ctx = ctx
        self.prog = prog
        self.hit_point_size = hit_point_size
        self.prog_outline = prog_outline
        self.unit_circle_vao = unit_circle_vao
        self.prog_screen = prog_screen
        self.marker_triangle_vbo = marker_triangle_vbo
        self.marker_triangle_vao = marker_triangle_vao
        self.marker_line_vbo = marker_line_vbo
        self.marker_line_vao = marker_line_vao
        self.flash_quad_vbo = flash_quad_vbo
        self.flash_quad_vao = flash_quad_vao
        self.prog_text = prog_text
        self.hud_quad_vbo = hud_quad_vbo
        self.hud_quad_vao = hud_quad_vao
        # [ADDED Faza 11B, see PLAN.md] Holds the current on-canvas HUD
        # texture (None until the first refresh, and whenever Pillow isn't
        # installed or there's nothing to draw) -- a plain dict (not a bare
        # attribute) purely by inherited convention from the pre-Faza-5
        # `hud_tex_holder = {"tex": None}` local, which existed as a dict
        # in the first place only so closures could mutate it without a
        # `nonlocal` declaration; keeping the same shape here avoids
        # touching every call site an extra time for no behavioral gain.
        self.hud_tex_holder = {"tex": None}

    def make_ring_vao(self, vbo):
        """(Re)creates the normal/hit VAO pair (see split_hit_normal_
        vertex_data's own doc-comment, in geometry_draw.py, for why there
        are two) from a fresh VBO -- called once at startup and again on
        every N-change rebuild in the main loop. The single place that
        vertex-format string ("2f 3f", "in_pos", "in_color") is written."""
        return self.ctx.vertex_array(self.prog, [(vbo, "2f 3f", "in_pos", "in_color")])


def setup_gl_resources(args):
    """Creates the GLFW window, the moderngl context, and every shader
    program/VAO/VBO _run_visualization's main loop and callbacks need.
    Ports that function's own startup block exactly (see git history for
    the pre-Faza-5 version, if the original per-line comments are ever
    needed again) -- ordering and every GL call are unchanged, only the
    ~16 result variables are now attributes on one returned GLResources
    instead of that many loose locals."""
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
    # moderngl textures are fixed-size -- see RenderSession.refresh_hud /
    # _run_visualization's own _apply_hud_refresh for the GL upload.
    # Only set up at all if Pillow is actually importable; otherwise the
    # HUD quad is simply never drawn (main loop's own `if hud_tex_holder`
    # guard), same graceful-degradation convention as everywhere else this
    # module treats an optional library as optional.
    prog_text = ctx.program(vertex_shader=TEXT_VERTEX_SHADER, fragment_shader=TEXT_FRAGMENT_SHADER) if _PIL_AVAILABLE else None
    hud_quad_vbo = ctx.buffer(reserve=6 * 4 * 4) if _PIL_AVAILABLE else None
    hud_quad_vao = ctx.vertex_array(prog_text, [(hud_quad_vbo, "2f 2f", "in_pos", "in_uv")]) if _PIL_AVAILABLE else None
    if not _PIL_AVAILABLE:
        print("[hud] Pillow not installed -- on-canvas HUD text disabled "
              "(run `pip install --user Pillow` to enable it). Everything "
              "else in this window is unaffected.")

    return GLResources(
        window=window, ctx=ctx, prog=prog, hit_point_size=hit_point_size,
        prog_outline=prog_outline, unit_circle_vao=unit_circle_vao,
        prog_screen=prog_screen, marker_triangle_vbo=marker_triangle_vbo,
        marker_triangle_vao=marker_triangle_vao, marker_line_vbo=marker_line_vbo,
        marker_line_vao=marker_line_vao, flash_quad_vbo=flash_quad_vbo,
        flash_quad_vao=flash_quad_vao, prog_text=prog_text,
        hud_quad_vbo=hud_quad_vbo, hud_quad_vao=hud_quad_vao,
    )
