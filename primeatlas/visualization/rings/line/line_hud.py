"""
line_hud.py -- line-mode HUD text: the pattern/wheel/axis status line
(pattern_hud_line).
"""

def pattern_hud_line(n, offsets, all_match, wheel_modulus=None, wheel_residue_count=None,
                      step_mode="manual", stop_on_match=False, view_mode=None, line_axis_curved=False):
    """The single HUD text line for "line" viz-mode's k-tuple pattern
    status: the anchor N, its offsets, whether every member currently
    lands on a real prime, (when a wheel is active, see
    ring_geometry.pattern_wheel_residues) the candidate density the wheel
    skip is scanning at -- `wheel_residue_count=0` prints the "can never
    repeat" case rather than a silent 0/M -- and the current Manual/Auto +
    MATCH! regime (see LineMode._pattern_uses_seek's own doc-comment
    for the exact rule this describes: "manual" shows every wheel
    candidate in turn; "auto" always seeks, for a MATCH! when checked or
    for a non-match when unchecked). Returned as a plain string so the
    caller (LineMode.rebuild) can drop it straight into
    `self.hud_lines` -- compose_hud_canvas_lines below already just
    appends whatever strings that list holds.

    `view_mode` -- ring_geometry.line_view_bounds' own "full"/"local" flag
    (build_line_vertex_data's return value, forwarded verbatim by
    LineMode.rebuild) -- printed only when "local", showing that the
    renderer switched to the anchor-centered viewport (float32-precision fallback
    for an archive-scale window, see line_view_bounds) instead of the whole loaded
    range; None or "full" adds nothing.

    `line_axis_curved` -- LineMode.line_axis_curved: when True, reports which
    curved layout is active this frame -- "[axis: spiral]" once a real wheel
    (`wheel_modulus > 1`) promotes it from a single circle to a spiral
    (see build_line_vertex_data's own `wheel_modulus` doc-comment), or
    "[axis: ring]" for the plain single-circle case (no pattern, or a
    pattern whose wheel excludes nothing). False (default) adds nothing."""
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
