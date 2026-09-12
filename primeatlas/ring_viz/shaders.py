"""
shaders.py -- GLSL source strings for primeatlas/ring_viz/renderer.py's
moderngl programs. [ADDED Faza 1 of the renderer.py split, see that file's
own module docstring for the overall refactor plan.] Pure data (plain
triple-quoted strings), no logic and no dependency on moderngl/glfw
themselves -- importable in a headless sandbox with no GPU, same as every
other non-GL-context-bound piece of this package.
"""

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

# [DEDUPED Faza 0 refactor] OUTLINE_FRAGMENT_SHADER and SCREEN_FRAGMENT_SHADER
# used to be two separately-defined but byte-for-byte identical GLSL strings
# (a flat, unlit vertex-color pass-through) -- one shared constant, aliased
# under both of this module's existing names so neither call site needs to
# change.
FLAT_COLOR_FRAGMENT_SHADER = """
#version 330

in vec4 v_color;
out vec4 f_color;

void main() {
    f_color = v_color;
}
"""

OUTLINE_FRAGMENT_SHADER = FLAT_COLOR_FRAGMENT_SHADER

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

SCREEN_FRAGMENT_SHADER = FLAT_COLOR_FRAGMENT_SHADER

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
