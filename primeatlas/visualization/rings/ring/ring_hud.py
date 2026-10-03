"""
ring_hud.py -- rings-mode HUD text: the per-N HUD line builder (hud_lines_for_n),
per-line window-family coloring (hud_line_colors), and the live-audio-tick bridge
(emit_audio_tick).

Self-contained sys.path bootstrap (mirrors renderer.py's own -- see that
file's module docstring for the full "why plain-script-path" explanation):
needed so the primeatlas.* imports below work whether this module is imported
after renderer.py has already run its own bootstrap, or on its own (e.g.
directly from a test).
"""

import os
import sys

import numpy as np

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_PRIME_SIEVE_DIR = os.path.join(_REPO_ROOT, "prime_sieve")
if _PRIME_SIEVE_DIR not in sys.path:
    sys.path.insert(0, _PRIME_SIEVE_DIR)

from primeatlas.visualization.shared.bigint import format_big
from primeatlas.visualization.rings.ring.ring_geometry import (
    legendre_level_at, general_law_window_bounds, nested_shell_colors, WINDOW_FAMILY_COLORS,
)

from primeatlas.visualization.shared.hud_text import _HUD_TEXT_RGB


def hud_lines_for_n(primes_active, n, pos, enabled_ids, theta, mode, tracked_state=None):
    """Ports the non-tracked-primes subset of DrumRenderer's #drawHud /
    StructuralSieveApp's #renderFrame draw-state construction (js/render/
    DrumRenderer.js and js/app/StructuralSieveApp.js in the RelationalMathematics
    repo) as PLAIN TEXT LINES -- printed to the console pane and rasterized for the
    GL window's HUD overlay (rasterize_hud_text), so no GL text pipeline (glyph
    atlas, per-glyph quads) is needed.

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
    # n=0 is range/fixed mode's placeholder starting value. phase = n mod prime is 0
    # for EVERY prime at n=0, so every active ring would be listed -- after an
    # arbitrary-range load, thousands of ~26-digit values in one line too long to
    # rasterize -- while N=0 has no meaningful factorization. Skipped for n==0.
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
        # Two RIGID modes -- theta is a locked display
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

    # A small color LEGEND (see ring_geometry.nested_shell_colors) -- one line
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

#: The fixed leading text hud_lines_for_n uses for each window family's own
#: range line -- see hud_line_colors' own doc-comment for why matching is
#: done by text prefix rather than by line position.
_HUD_WINDOW_LINE_PREFIXES = {
    "bertrand": "Bertrand window:",
    "legendre": "Legendre window:",
    "generalLaw": "General Law window",
}

#: Human-readable display name per family id, used only
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
    window_label_colors' output, a plain per-family lookup with no blending --
    blending is shown by the nested-shell legend lines below).

    Matches by TEXT PREFIX rather than by position/index so this stays
    correct even if hud_lines_for_n's own Factors-of-N/Tracked-block line
    count changes later -- the window-range lines are always identifiable
    by their own fixed leading text regardless of what precedes them.

    `shell_colors` -- optional dict from ring_geometry.
    nested_shell_colors (frozenset(family ids) -> (r,g,b)), matched the same
    prefix-text way via _shell_line_prefix -- colors the nested-shell
    color-legend lines hud_lines_for_n appends. None (the default)
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
