"""
rings_argv.py -- build_renderer_argv, the argv launching the shared GPU renderer
(primeatlas/visualization/shared/renderer.py) against the app's archive. The
Visualization > Rings sub-tab (rings/rings_tab.py) builds it from its form on Start.
"""
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
RENDERER_SCRIPT = os.path.join(os.path.dirname(_THIS_DIR), "shared", "renderer.py")


def build_renderer_argv(portal_folder, upto, python_executable=None,
                         windows=(), general_law_theta=0.5, general_law_mode="sliding",
                         point_size=None, track_primes=(), auto_orbit=False, load_range=None,
                         hit_point_size=None, hud_font_size=None, audio=False,
                         sound_low='sine', sound_prime='triangle', sound_lcm='choir',
                         pipe_stdin_commands=False, max_load_count=None, tempo_ms=None,
                         viz_mode="rings", pattern_seed_k=None, pattern_seed_start=None,
                         pattern_offsets=None, pattern_step_mode="manual", pattern_stop_on_match=False,
                         line_axis_curved=False, slide_load_range=False, slide_chunk_size=None):
    """Builds the argv for launching renderer.py against a real archive.

    Uses `python_executable` (defaults to sys.executable -- THIS SAME Python
    interpreter PrimeAtlas itself is currently running under) rather than a
    bare "python" resolved from PATH, so the launch can never accidentally
    pick a different, possibly moderngl/glfw-less Python install if more
    than one exists on the machine.

    Deliberately launches RENDERER_SCRIPT as a PLAIN SCRIPT PATH argument
    (`[exe, RENDERER_SCRIPT, ...]`), never `-m primeatlas.visualization.shared.renderer`
    -- see renderer.py's own module docstring for exactly why that matters
    (its internal sys.path fix for the prime_sieve/ sibling directory runs
    too late to help a `-m`/dotted-import invocation, which imports the
    primeatlas package first).

    `windows` -- an iterable of window family ids
    (any of "bertrand"/"legendre"/"generalLaw") to highlight, chosen once at
    launch time via this tab's checkboxes (there is no live in-GL-window
    toggle -- see renderer.py's own "no live in-window toggle yet" note).
    `general_law_theta`/`general_law_mode` are only appended when
    "generalLaw" is among `windows` -- passing them unconditionally would be
    harmless (renderer.py ignores them when that family isn't enabled) but
    a shorter argv is easier to read in the console pane's own `$ ...` echo
    line. `general_law_mode` -- "sliding" (default)/"stepped", plus two RIGID
    modes "bertrand"/"legendre", where `general_law_theta` is ignored entirely
    (forced to 1.0/0.5 by renderer.py itself -- see its --general-law-mode
    argparse) and the window reproduces that family's own EXACTLY, rather than
    approximating it via theta.

    `point_size` -- None (default) omits --point-size entirely, so
    renderer.py's own argparse default (3.0) applies; a real value is
    forwarded as-is. renderer.py's [diag] startup print shows whether the
    requested value reaches the renderer or is clamped by the
    GL_POINT_SIZE_RANGE hardware/driver limit.

    `track_primes` -- an iterable of prime
    values (any order/dupes as typed by the user, see ring_tracked.py's
    own filter_active_tracked docstring for why order is preserved) chosen
    once at launch time via the "Track P" field, forwarded as-is to
    renderer.py's --track-primes. `auto_orbit` mirrors the JS's auto-orbit
    checkbox; same launch-time-only convention as `windows` above -- no
    live in-GL-window toggle for either.

    `load_range` -- None (default, sequential mode) or a (from, to) pair
    forwarded as-is to
    renderer.py's --load-range. As with track_primes, the string values are
    NOT int()-cast here -- an empty or malformed field just omits
    --load-range entirely rather than raising inside the GUI thread;
    renderer_cli.parse_args does the real format validation (same
    parser.error() convention as --track-primes/--windows).

    `hit_point_size`
    -- None (default) omits --hit-point-size entirely, so renderer.py's own
    default (fall back to --point-size) applies; a real value gives rings on
    the vertical reference line (divisors of N) an independent on-screen
    size from every other ring. `hud_font_size` -- None (default) omits
    --hud-font-size entirely, so renderer.py's own argparse default (16px)
    applies; a real value scales the on-canvas HUD text. Same
    omit-if-None convention as `point_size` above.

    `max_load_count` -- None (default) omits --max-load-count entirely, so
    renderer.py's own argparse default applies; a real value overrides the
    safety cap on how many primes an archive `load_range` load may
    materialize (see load_archive's own `max_load_count` doc-comment for why
    this is a plain configurable number, not a hardcoded constant). Only
    meaningful together with `load_range`, but forwarded unconditionally
    like every other optional flag here -- renderer.py itself ignores it
    outside that mode.

    `tempo_ms` -- None
    (default) omits --tempo-ms entirely, so renderer.py's own argparse
    default (120, via clamp_tempo_ms) applies; a real value sets the
    playback tick's real-time pacing at launch (it can also be changed live
    with the ]/[ keys inside the GL window).
    Same omit-if-None convention as `point_size` above.

    `viz_mode` -- "rings" (default, omits --viz-mode entirely so
    renderer.py's own argparse default applies) or "line" (a fixed
    horizontal row of real primes from `load_range`, see renderer.py's own
    --viz-mode doc-comment). `pattern_seed_k`/`pattern_seed_start` -- both
    None (default) omits --pattern-seed-k/--pattern-seed-start entirely;
    given together, they derive the "line" mode's optional sliding k-tuple
    pattern (see line_geometry.pattern_offsets_from_seed). Not int()-cast
    here for the same reason track_primes isn't above -- renderer.py's own
    argparse does the real validation. `pattern_offsets` -- a catalog
    pattern's offsets, sent as --pattern-offsets 0,2,6,8 instead of a seed;
    None (default) omits it.

    `pattern_step_mode` -- "manual" (default, omits --pattern-step-mode
    entirely) always takes a single wheel step per navigation key,
    showing every candidate whether it's a real match or not; "auto"
    always seeks instead, per `pattern_stop_on_match`. `pattern_stop_
    on_match` -- False (default) omits --pattern-stop-on-match entirely,
    seeking the next NON-match wheel candidate (in "auto" mode only);
    True seeks the next real MATCH! instead -- see RenderSession.
    _pattern_uses_seek's own doc-comment for the exact combined rule.

    `line_axis_curved` -- False (default) omits --line-axis-curved
    entirely (straight-line axis); True bends line mode's axis into a
    circle instead -- purely visual, see LineMode.line_axis_curved.

    `slide_load_range` -- False (default, omits --slide-load-range
    entirely) keeps a fixed-slice `load_range` (the first `max_load_count`
    primes); True turns on the bidirectional sliding window so the WHOLE
    load_range span becomes reachable a chunk at a time. Off by default
    (enabled explicitly), since the extra disk I/O on each chunk swap may not
    suit every machine. `slide_chunk_size` -- None (default) omits
    --slide-chunk-size entirely, so renderer.py's argparse falls back to
    `max_load_count`'s value (one "how much is loaded at once" number for the
    first chunk and every slid-in chunk); a real value overrides that with a
    different chunk size."""
    exe = python_executable or sys.executable
    argv = [exe, RENDERER_SCRIPT, "--source", "archive",
            "--portal-folder", portal_folder, "--upto", str(upto)]
    windows = list(windows)
    if windows:
        argv += ["--windows", ",".join(windows)]
        if "generalLaw" in windows:
            argv += ["--general-law-theta", str(general_law_theta),
                     "--general-law-mode", general_law_mode]
    if point_size is not None:
        argv += ["--point-size", str(point_size)]
    if hit_point_size is not None:
        argv += ["--hit-point-size", str(hit_point_size)]
    if hud_font_size is not None:
        argv += ["--hud-font-size", str(hud_font_size)]
    # Deliberately str(p) here, NOT int(p) -- track_primes may come straight
    # from the Track P text field's raw (unvalidated) split, and forcing an
    # int() cast here would raise ValueError inside the GUI thread itself on
    # a typo. renderer.py's own --track-primes parsing (the parser.error()
    # path, same convention as --windows) is where a bad entry surfaces, as a
    # normal subprocess-launch error visible in the console pane -- not a
    # crash of this tab.
    track_primes = list(track_primes)
    if track_primes:
        argv += ["--track-primes", ",".join(str(p) for p in track_primes)]
    if auto_orbit:
        argv += ["--auto-orbit"]
    if load_range is not None:
        load_from, load_to = load_range
        argv += ["--load-range", f"{load_from},{load_to}"]
    if max_load_count is not None:
        argv += ["--max-load-count", str(max_load_count)]
    if tempo_ms is not None:
        argv += ["--tempo-ms", str(tempo_ms)]
    if viz_mode != "rings":
        argv += ["--viz-mode", str(viz_mode)]
    if pattern_seed_k is not None:
        argv += ["--pattern-seed-k", str(pattern_seed_k)]
    if pattern_seed_start is not None:
        argv += ["--pattern-seed-start", str(pattern_seed_start)]
    if pattern_offsets is not None:
        argv += ["--pattern-offsets", ",".join(str(o) for o in pattern_offsets)]
    if pattern_step_mode != "manual":
        argv += ["--pattern-step-mode", str(pattern_step_mode)]
    if pattern_stop_on_match:
        argv += ["--pattern-stop-on-match"]
    if line_axis_curved:
        argv += ["--line-axis-curved"]
    if slide_load_range:
        argv += ["--slide-load-range"]
    if slide_chunk_size is not None:
        argv += ["--slide-chunk-size", str(slide_chunk_size)]
    if audio:
        argv += ['--audio', '--sound-low', sound_low, '--sound-prime', sound_prime,
                 '--sound-lcm', sound_lcm]
    # Opt-in ONLY when the caller is actually
    # going to act on the RING_VIZ_PAUSED/RESUMED lines this makes
    # renderer.py print (see that flag's own doc-comment there) --
    # RingsTab._on_open is the one real caller and always passes True;
    # False (default) keeps the argv a plain terminal invocation of
    # renderer.py's CLI, with no pause/resume behavior.
    if pipe_stdin_commands:
        argv += ["--pipe-stdin-commands"]
    return argv
