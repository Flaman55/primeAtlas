"""
rings_tab.py -- RingsTab(VizTabBase), the Visualization > Rings sub-tab. Launches the
GPU renderer (primeatlas/visualization/shared/renderer.py) as a separate native Windows subprocess
against the app's own currently-configured archive, given a target N.

WHY A SUBPROCESS, NOT EMBEDDED IN THIS WINDOW: GL's own event loop does not compose
with Tkinter's mainloop() -- see primeatlas/visualization/shared/__init__.py's own docstring for
the full reasoning.

WHY LocalLoggedRunner AND NOT WslLoggedRunner: renderer.py is a plain native Windows
Python script (moderngl+glfw, no WSL involved anywhere) -- LocalLoggedRunner
(primeatlas/generation/generation.py) already exists for exactly this "ordinary local subprocess,
live stdout capture on a background thread" shape (its only prior caller is the sympy
installer in settings_tab.py). GenerationConsole (the collapsible live-output pane
widget) is reused as-is for the actual UI, since it has no WSL-specific assumption
baked in at all.

renderer.py's own print() calls (loading progress, the per-N-change rebuild line, see
that module's own docstring) already write to stdout -- LocalLoggedRunner's queue-based
capture surfaces those as real, user-visible progress text in this tab's console pane,
not just the GL window's own title bar (which nothing outside that window can see).

get_portal_folder is a deferred callable (same dependency-injection pattern as every
other extracted tab -- see research_goldbach_tab.py's own docstring), read fresh at
launch time rather than captured once, so a Settings-tab storage-path change takes
effect on the NEXT launch without this tab needing its own change-notification wiring.
"""
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox

from ...generation.generation import LocalLoggedRunner, _eval_quick_number
from ...generation.generation_console import GenerationConsole
from ...core import storage
from ..shared.audio import INSTRUMENTS
from ..shared.viz_tab_base import VizTabBase

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
RENDERER_SCRIPT = os.path.join(os.path.dirname(_THIS_DIR), "shared", "renderer.py")


def build_renderer_argv(portal_folder, upto, python_executable=None,
                         windows=(), general_law_theta=0.5, general_law_mode="sliding",
                         point_size=None, track_primes=(), auto_orbit=False, load_range=None,
                         hit_point_size=None, hud_font_size=None, audio=False,
                         sound_low='sine', sound_prime='triangle', sound_lcm='choir',
                         pipe_stdin_commands=False, max_load_count=None, tempo_ms=None,
                         viz_mode="rings", pattern_seed_k=None, pattern_seed_start=None,
                         pattern_step_mode="manual", pattern_stop_on_match=False,
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
    values (any order/dupes as typed by the user, see ring_geometry.py's
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
    renderer.py's own main() does the real format validation (same
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
    pattern (see ring_geometry.pattern_offsets_from_seed). Not int()-cast
    here for the same reason track_primes isn't above -- renderer.py's own
    argparse does the real validation.

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
    # a typo. renderer.py's own --track-primes parsing (main()'s parser.error()
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


class RingsTab(VizTabBase):
    LOCALE_PREFIX = "rings"

    def __init__(self, parent, get_portal_folder, status_var, translator, totals_progress,
                 app_settings=None):
        super().__init__(parent, get_portal_folder, status_var, translator, totals_progress,
                         app_settings)
        self._build_ui()

    def _build_ui(self):
        # Every literal fallback below (e.g. "2", "15", "0.5") is the tab's
        # first-run default, shown on a fresh install (no saved_params yet).
        # Once at least one run has launched,
        # saved_params overrides them, so every field after the first-ever run reopens
        # exactly where the previous one left off (see ring_viz_params's own
        # doc-comment in app_settings.py).
        saved_params = (self._app_settings.ring_viz_params if self._app_settings else None) or {}

        # scroll_body replaces `self` as container's parent (see
        # _build_scrollable_container's own docstring) -- container itself
        # keeps its exact original padx/pady pack() call, so nothing below this
        # line needed to change at all.
        scroll_body, self._register_scroll_exclude = self._build_scrollable_container(self)
        container = ttk.Frame(scroll_body)
        container.pack(fill="both", expand=True, padx=12, pady=12)

        intro = ttk.Label(container, text=self.T("rings.intro"), wraplength=760, justify="left")
        intro.pack(anchor="w", pady=(0, 10))

        # Fields are grouped into labeled sections (Position/mode, Appearance,
        # Audio, Windows & tracking) purely for layout; every widget is addressed
        # by attribute name (by _on_open, _set_launch_params_readonly, persistence
        # and tests), never by parent frame or pack position.

        # --- Position & mode ---------------------------------------------
        position_frame = ttk.LabelFrame(container, text=self.T("rings.section_position"))
        position_frame.pack(fill="x", pady=(0, 8))

        # Explicit mode switch, replacing the old implicit "load_range
        # activates whenever BOTH From/To happen to be non-empty" rule --
        # that rule could silently activate range mode from a stale leftover
        # value left in one of the fields by a previous test.
        # _on_mode_changed greys out whichever of N / Load Range this mode
        # doesn't use, so a leftover value in the inactive field is visibly
        # inert instead of a trap.
        mode_row = ttk.Frame(position_frame)
        mode_row.pack(fill="x", padx=8, pady=(6, 6))
        ttk.Label(mode_row, text=self.T("rings.mode_label")).pack(side="left")
        self.mode_var = tk.StringVar(value=saved_params.get("mode", "sequential"))
        self._mode_sequential_radio = ttk.Radiobutton(
            mode_row, text=self.T("rings.mode_sequential"), value="sequential",
            variable=self.mode_var, command=self._on_mode_changed)
        self._mode_sequential_radio.pack(side="left", padx=(6, 0))
        self._mode_range_radio = ttk.Radiobutton(
            mode_row, text=self.T("rings.mode_range"), value="range",
            variable=self.mode_var, command=self._on_mode_changed)
        self._mode_range_radio.pack(side="left", padx=(10, 0))

        field_row = ttk.Frame(position_frame)
        field_row.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(field_row, text=self.T("rings.field_n")).pack(side="left")
        self.n_entry = ttk.Entry(field_row, width=28)
        # N is pre-filled at startup instead
        # of left empty, so the field/hint are non-empty on first render.
        self.n_entry.insert(0, saved_params.get("n", "2"))
        self.n_entry.pack(side="left", padx=(6, 10))
        self.n_hint_var = tk.StringVar(value="")
        ttk.Label(field_row, textvariable=self.n_hint_var, foreground="#888888").pack(side="left")
        self.n_entry.bind("<KeyRelease>", self._on_n_changed)
        self._on_n_changed()

        # Load Range -- From/To fields, launch-time
        # only (same convention as every other field on this tab: read once by
        # _on_open, no live subprocess IPC). Which mode
        # is active is decided by mode_var above, not by whether these
        # happen to be filled in -- see renderer.py's own --load-range
        # handling in run() for the full behavior, ported from the HTML's
        # #loadPrimeRange/"Load Range" button.
        range_row = ttk.Frame(position_frame)
        range_row.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(range_row, text=self.T("rings.load_range_label")).pack(side="left")
        self.load_range_from_entry = ttk.Entry(range_row, width=16)
        self.load_range_from_entry.insert(0, saved_params.get("load_range_from", ""))
        self.load_range_from_entry.pack(side="left", padx=(6, 6))
        ttk.Label(range_row, text=self.T("rings.load_range_to_label")).pack(side="left")
        self.load_range_to_entry = ttk.Entry(range_row, width=16)
        self.load_range_to_entry.insert(0, saved_params.get("load_range_to", ""))
        self.load_range_to_entry.pack(side="left", padx=(6, 0))

        # Safety cap for a Load Range
        # load, so an arbitrary From/To spanning a huge value gap (the whole
        # point of being able to open at a high floor without loading every
        # floor below it first -- see load_archive's own `from_n`/
        # `max_load_count` doc-comments) can't stall the launch. No safe
        # number has been benchmarked on real archive hardware yet, so this
        # is a plain editable field (persisted like every other field here)
        # rather than a hardcoded constant -- left empty falls back to
        # renderer.py's own argparse default.
        max_load_row = ttk.Frame(position_frame)
        max_load_row.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(max_load_row, text=self.T("rings.max_load_count_label")).pack(side="left")
        self.max_load_count_entry = ttk.Entry(max_load_row, width=16)
        self.max_load_count_entry.insert(0, saved_params.get("max_load_count", ""))
        self.max_load_count_entry.pack(side="left", padx=(6, 0))

        # Bidirectional sliding window over Load Range -- OFF by default (enabled
        # explicitly), so a plain Load Range is a fixed slice unless this is
        # checked. No separate chunk-size field (fewer parameters keep the tab
        # intuitive): each slid-in chunk reuses Max load count's value
        # (build_renderer_argv is never given a slide_chunk_size here, so
        # renderer.py's inherit-from-max-load-count fallback applies).
        # renderer.py's --slide-chunk-size CLI flag remains for direct invocation.
        slide_row = ttk.Frame(position_frame)
        slide_row.pack(fill="x", padx=8, pady=(0, 6))
        self.slide_load_range_var = tk.BooleanVar(value=saved_params.get("slide_load_range", False))
        self._slide_load_range_check = ttk.Checkbutton(
            slide_row, text=self.T("rings.slide_load_range_label"), variable=self.slide_load_range_var)
        self._slide_load_range_check.pack(side="left")

        # Exposes renderer.py's --tempo-ms at launch time (also adjustable live
        # with the ]/[ keys inside the GL window -- see clamp_tempo_ms's
        # [30,2000] range there).
        # Applies to BOTH modes (it is the playback tick's own real-time
        # pacing, independent of tick_next_n's range_step -- see that
        # function's own doc-comment for how those two are
        # different knobs: tempo is "how often", range_step is "how far
        # each time"). Empty/invalid falls back to renderer.py's own
        # argparse default (120ms), same omit-if-blank convention as every
        # other numeric field here.
        tempo_row = ttk.Frame(position_frame)
        tempo_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(tempo_row, text=self.T("rings.tempo_label")).pack(side="left")
        self.tempo_ms_entry = ttk.Entry(tempo_row, width=8)
        self.tempo_ms_entry.insert(0, saved_params.get("tempo_ms", "120"))
        self.tempo_ms_entry.pack(side="left", padx=(6, 0))

        # "line" viz-mode: an experimental second drawing mode -- a fixed
        # horizontal row of real primes (from Load Range above, which this
        # requires) instead of the default ring-per-modulus display, with an
        # optional k-tuple pattern slid along it by N (see renderer.py's own
        # --viz-mode/--pattern-seed-* flags and ring_geometry.py's "line
        # viz-mode" section for the full design). k/p0 derive the pattern's
        # offsets from k real consecutive primes >= p0 -- see
        # pattern_offsets_from_seed's own doc-comment for why that's always
        # an admissible pattern.
        line_mode_row = ttk.Frame(position_frame)
        line_mode_row.pack(fill="x", padx=8, pady=(0, 8))
        self.line_mode_var = tk.BooleanVar(value=saved_params.get("line_mode", False))
        self._line_mode_check = ttk.Checkbutton(line_mode_row, text=self.T("rings.line_mode_label"),
                                                  variable=self.line_mode_var)
        self._line_mode_check.pack(side="left")
        ttk.Label(line_mode_row, text=self.T("rings.pattern_k_label")).pack(side="left", padx=(16, 0))
        self.pattern_k_entry = ttk.Entry(line_mode_row, width=6)
        self.pattern_k_entry.insert(0, saved_params.get("pattern_k", ""))
        self.pattern_k_entry.pack(side="left", padx=(6, 16))
        ttk.Label(line_mode_row, text=self.T("rings.pattern_p0_label")).pack(side="left")
        self.pattern_p0_entry = ttk.Entry(line_mode_row, width=16)
        self.pattern_p0_entry.insert(0, saved_params.get("pattern_p0", ""))
        self.pattern_p0_entry.pack(side="left", padx=(6, 0))

        # Manual/Auto step-mode radio + "MATCH!" checkbox: Manual (default) always
        # takes a single wheel
        # step per LEFT/RIGHT/Up/Down/Space, showing every candidate
        # whether it's a real match or not; Auto always seeks instead
        # (LineMode._pattern_seek) -- for the next real MATCH! when
        # checked, or specifically the next NON-match when unchecked. See
        # renderer.py's own --pattern-step-mode/--pattern-stop-on-match
        # doc-comments.
        pattern_step_row = ttk.Frame(position_frame)
        pattern_step_row.pack(fill="x", padx=8, pady=(0, 8))
        self.pattern_step_mode_var = tk.StringVar(value=saved_params.get("pattern_step_mode", "manual"))
        self._pattern_manual_radio = ttk.Radiobutton(
            pattern_step_row, text=self.T("rings.pattern_step_manual_label"),
            variable=self.pattern_step_mode_var, value="manual")
        self._pattern_manual_radio.pack(side="left")
        self._pattern_auto_radio = ttk.Radiobutton(
            pattern_step_row, text=self.T("rings.pattern_step_auto_label"),
            variable=self.pattern_step_mode_var, value="auto")
        self._pattern_auto_radio.pack(side="left", padx=(6, 16))
        self.pattern_stop_on_match_var = tk.BooleanVar(value=saved_params.get("pattern_stop_on_match", False))
        self._pattern_stop_on_match_check = ttk.Checkbutton(
            pattern_step_row, text=self.T("rings.pattern_stop_on_match_label"),
            variable=self.pattern_stop_on_match_var)
        self._pattern_stop_on_match_check.pack(side="left")

        # Curved axis: purely visual --
        # bends line mode's straight dot-row into a circle instead, with a
        # red boundary line marking where the loaded window's own start
        # and end coincide on screen (they are NOT the same value, unlike
        # a real periodic wraparound -- see line_draw.
        # axis_boundary_marker_vertices' own doc-comment). Does not touch
        # navigation/matching/wheel logic at all -- see RenderSession.
        # line_axis_curved.
        self.line_axis_curved_var = tk.BooleanVar(value=saved_params.get("line_axis_curved", False))
        self._line_axis_curved_check = ttk.Checkbutton(
            pattern_step_row, text=self.T("rings.line_axis_curved_label"),
            variable=self.line_axis_curved_var)
        self._line_axis_curved_check.pack(side="left", padx=(16, 0))

        # --- Windows & tracking -------------------------------------------
        # These are working parameters (what the visualization
        # computes/highlights), not visual/appearance settings, so they
        # belong right after Position & mode, ahead of Appearance/Audio.
        windows_frame = ttk.LabelFrame(container, text=self.T("rings.section_windows"))
        windows_frame.pack(fill="x", pady=(0, 8))

        # Window-highlight-family checkboxes --
        # chosen once here, at launch time, and passed as --windows to
        # renderer.py (see build_renderer_argv's own doc-comment for why
        # this is launch-time-only rather than a live in-GL-window toggle).
        windows_row = ttk.Frame(windows_frame)
        windows_row.pack(fill="x", padx=8, pady=(6, 6))
        ttk.Label(windows_row, text=self.T("rings.windows_label")).pack(side="left")
        self.bertrand_var = tk.BooleanVar(value=saved_params.get("bertrand", False))
        self._bertrand_check = ttk.Checkbutton(windows_row, text=self.T("rings.window_bertrand"),
                                                 variable=self.bertrand_var)
        self._bertrand_check.pack(side="left", padx=(6, 0))
        self.legendre_var = tk.BooleanVar(value=saved_params.get("legendre", False))
        self._legendre_check = ttk.Checkbutton(windows_row, text=self.T("rings.window_legendre"),
                                                 variable=self.legendre_var)
        self._legendre_check.pack(side="left", padx=(6, 0))
        self.general_law_var = tk.BooleanVar(value=saved_params.get("general_law", False))
        self._general_law_check = ttk.Checkbutton(windows_row, text=self.T("rings.window_general_law"),
                                                     variable=self.general_law_var)
        self._general_law_check.pack(side="left", padx=(6, 0))

        general_law_row = ttk.Frame(windows_frame)
        general_law_row.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(general_law_row, text=self.T("rings.general_law_theta_label")).pack(side="left")
        self.general_law_theta_entry = ttk.Entry(general_law_row, width=6)
        self.general_law_theta_entry.insert(0, saved_params.get("general_law_theta", "0.5"))
        self.general_law_theta_entry.pack(side="left", padx=(6, 16))
        ttk.Label(general_law_row, text=self.T("rings.general_law_mode_label")).pack(side="left")
        # 'bertrand'/'legendre' are RIGID choices: they lock theta to a fixed
        # display value (see _on_general_law_mode_changed below) and reproduce those
        # families' windows EXACTLY, rather than approximating them via theta.
        self.general_law_mode_combo = ttk.Combobox(general_law_row, width=10, state="readonly",
                                                     values=["stepped", "sliding", "bertrand", "legendre"])
        # Default "sliding" -- matches renderer.py's --general-law-mode argparse
        # default (see that flag's doc-comment for why).
        self.general_law_mode_combo.set(saved_params.get("general_law_mode", "sliding"))
        self.general_law_mode_combo.bind("<<ComboboxSelected>>", self._on_general_law_mode_changed)
        self.general_law_mode_combo.pack(side="left", padx=(6, 0))

        # Track P field -- comma-separated prime
        # values, forwarded as-is to renderer.py's --track-primes (see
        # build_renderer_argv's own doc-comment). Launch-time-only, same
        # convention as the windows checkboxes above: no live in-GL-window
        # text field yet. "Auto orbit" mirrors the JS's auto-cycle mode
        # (mutually exclusive in effect with a real Track P list -- see
        # renderer.py's own rebuild_buffer(), which skips the tracked-filter
        # entirely when auto-orbit is on); left as an independent checkbox
        # here rather than disabling the Track P field.
        track_row = ttk.Frame(windows_frame)
        track_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(track_row, text=self.T("rings.track_primes_label")).pack(side="left")
        self.track_primes_entry = ttk.Entry(track_row, width=20)
        self.track_primes_entry.insert(0, saved_params.get("track_primes", ""))
        self.track_primes_entry.pack(side="left", padx=(6, 16))
        self.auto_orbit_var = tk.BooleanVar(value=saved_params.get("auto_orbit", False))
        self._auto_orbit_check = ttk.Checkbutton(track_row, text=self.T("rings.auto_orbit_label"),
                                                   variable=self.auto_orbit_var)
        self._auto_orbit_check.pack(side="left")

        # --- Appearance ----------------------------------------------------
        appearance_frame = ttk.LabelFrame(container, text=self.T("rings.section_appearance"))
        appearance_frame.pack(fill="x", pady=(0, 8))

        # Exposed here (instead of only reachable by hand-editing
        # renderer.py's argparse default) so a real value change is
        # verifiable from the GUI alone -- see build_renderer_argv's own
        # doc-comment for the full context.
        point_size_row = ttk.Frame(appearance_frame)
        point_size_row.pack(fill="x", padx=8, pady=(6, 6))
        ttk.Label(point_size_row, text=self.T("rings.point_size_label")).pack(side="left")
        self.point_size_entry = ttk.Entry(point_size_row, width=8)
        self.point_size_entry.insert(0, saved_params.get("point_size", "15"))
        self.point_size_entry.pack(side="left", padx=(6, 0))

        # See build_renderer_argv's own doc-comment: hit-rings (on the
        # vertical reference line) need an independent size from every other
        # ring, distinct from the HUD font size. Pre-filled with default
        # values so these are visibly wired in at launch rather than hidden
        # behind a blank field the user has to know to fill in. Clearing the
        # field still omits the CLI flag entirely (renderer.py's own
        # argparse defaults apply then too).
        hit_point_size_row = ttk.Frame(appearance_frame)
        hit_point_size_row.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(hit_point_size_row, text=self.T("rings.hit_point_size_label")).pack(side="left")
        self.hit_point_size_entry = ttk.Entry(hit_point_size_row, width=8)
        self.hit_point_size_entry.insert(0, saved_params.get("hit_point_size", "20"))
        self.hit_point_size_entry.pack(side="left", padx=(6, 0))

        hud_font_size_row = ttk.Frame(appearance_frame)
        hud_font_size_row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(hud_font_size_row, text=self.T("rings.hud_font_size_label")).pack(side="left")
        self.hud_font_size_entry = ttk.Entry(hud_font_size_row, width=8)
        self.hud_font_size_entry.insert(0, saved_params.get("hud_font_size", "35"))
        self.hud_font_size_entry.pack(side="left", padx=(6, 0))

        # --- Audio -----------------------------------------------------------
        audio_frame = ttk.LabelFrame(container, text=self.T("rings.section_audio"))
        audio_frame.pack(fill="x", pady=(0, 8))
        audio_row = ttk.Frame(audio_frame)
        audio_row.pack(fill='x', padx=8, pady=(6, 4))
        self.audio_enabled = tk.BooleanVar(value=saved_params.get("audio_enabled", False))
        self._audio_enable_check = ttk.Checkbutton(audio_row, text=self.T('rings.audio_enable'),
                                                     variable=self.audio_enabled)
        self._audio_enable_check.pack(side='left')
        self.audio_choices = {}
        for channel, default in (('low', 'sine'), ('prime', 'triangle'), ('lcm', 'choir')):
            ttk.Label(audio_row, text=self.T('rings.sound_' + channel)).pack(side='left', padx=(8, 3))
            choice = ttk.Combobox(audio_row, state='readonly', width=11,
                                 values=[self.T('rings.instrument_' + name) for name in INSTRUMENTS])
            saved_instrument = saved_params.get('sound_' + channel, default)
            choice.current(INSTRUMENTS.index(saved_instrument) if saved_instrument in INSTRUMENTS
                            else INSTRUMENTS.index(default))
            choice.pack(side='left')
            self.audio_choices[channel] = choice
        ttk.Label(audio_frame, text=self.T('rings.audio_hint')).pack(anchor='w', padx=8, pady=(0, 6))

        # Applies the mode switch's enabled/disabled
        # wiring once, right after every field above has been created --
        # must run after load_range_from/to and max_load_count entries above
        # exist, and after n_entry, since it addresses all of them by
        # attribute.
        self._on_mode_changed()
        # Same, for General Law's own theta lock -- must run after
        # general_law_theta_entry/general_law_mode_combo above exist, so a
        # saved_params value of "bertrand"/"legendre" starts the entry
        # correctly locked instead of only locking on the NEXT manual change.
        self._on_general_law_mode_changed()

        # open_button/stop_button act as Start/Resume and Reset -- see _on_reset
        # and __init__ for the resume half (the N field is updated to the last
        # live N whenever the GL window closes on its own, so Start reopens right
        # there; Reset discards that live-resume value without touching what is
        # typed in any field).
        # Packed `before=intro`, i.e. at the very top of the tab: launching is the
        # tab's primary action, and must not sit below the option sections. Still
        # created here, after every field it reads.
        button_row = ttk.Frame(container)
        button_row.pack(fill="x", pady=(0, 10), before=intro)
        self.open_button = ttk.Button(button_row, text=self.T("rings.open_button"),
                                       command=self._on_open)
        self.open_button.pack(side="left")
        self.stop_button = ttk.Button(button_row, text=self.T("rings.stop_button"),
                                       command=self._on_reset, state="disabled")
        self.stop_button.pack(side="left", padx=(6, 0))

        # Always-current HUD status panel --
        # separate from self.console below on purpose. renderer.py's own
        # human-readable HUD lines (N, factors of N, tracked/LCM state,
        # etc.) already reach that console pane too -- but during playback
        # they reprint every single tick and scroll past far too fast to
        # ever read, so there was no always-visible snapshot of the current
        # state. This label's content gets REPLACED wholesale on every
        # "HUD_STATE:" line (see renderer.py's own emit_hud_state()), never
        # appended.
        hud_frame = ttk.LabelFrame(container, text=self.T("rings.hud_panel_title"))
        hud_frame.pack(fill="x", pady=(0, 10))
        self.hud_var = tk.StringVar(value=self.T("rings.hud_panel_placeholder"))
        ttk.Label(hud_frame, textvariable=self.hud_var, justify="left", anchor="w",
                  font=("TkFixedFont",)).pack(fill="x", padx=8, pady=6)

        self.console = GenerationConsole(container, self.T, height=14,
                                          window_title=self.T("rings.console_title"))
        # See _build_scrollable_container's own docstring -- this tells the tab's
        # outer scroll wrapper to leave mousewheel/button events that land
        # inside the console's own ScrolledText (and its scrollbar) alone.
        self._register_scroll_exclude(self.console.text.frame)

        # Every field below is read ONCE, at
        # _on_open's launch-time argv build -- see build_renderer_argv's own
        # doc-comment. While the process is paused-and-resumable
        # (self._paused, see _set_launch_params_readonly's own doc-comment),
        # editing any of them would silently do nothing until the NEXT fresh
        # launch, which would otherwise look like it should matter but
        # wouldn't. Split into two groups because ttk widgets don't share
        # one disabled-state spelling: entries/checkbuttons use
        # "normal"/"disabled", comboboxes use "readonly" (their own normal
        # state here, since they're never free-text) vs "disabled".
        self._launch_param_entries = [
            self.n_entry, self.point_size_entry, self.hit_point_size_entry,
            self.hud_font_size_entry, self.general_law_theta_entry,
            self.track_primes_entry, self.load_range_from_entry, self.load_range_to_entry,
            self.max_load_count_entry, self.tempo_ms_entry,
            self.pattern_k_entry, self.pattern_p0_entry,
        ]
        self._launch_param_checkbuttons = [
            self._audio_enable_check, self._bertrand_check, self._legendre_check,
            self._general_law_check, self._auto_orbit_check,
            self._mode_sequential_radio, self._mode_range_radio, self._line_mode_check,
            self._pattern_manual_radio, self._pattern_auto_radio, self._pattern_stop_on_match_check,
            self._line_axis_curved_check, self._slide_load_range_check,
        ]
        self._launch_param_dropdowns = [
            self.general_law_mode_combo,
            self.audio_choices['low'], self.audio_choices['prime'], self.audio_choices['lcm'],
        ]

    def _set_launch_params_readonly(self, readonly):
        """Toggles every launch-time-only field
        (N, point sizes, window-highlight checkboxes, Track P, Load Range,
        audio instrument pickers, ...) between editable and read-only.
        Called with readonly=True the moment the process reports itself
        paused (RING_VIZ_PAUSED, see _poll_queue below) -- while paused, the
        Start/Resume button sends RESUME instead of relaunching, so these
        fields would no longer feed anything even though they still LOOK
        live and editable. Called with readonly=False on RING_VIZ_RESUMED,
        on Reset, and on any real process exit, so the fields are always
        editable again the instant a fresh launch (not a resume) is what
        the next Start/Resume click will actually do."""
        entry_state = "disabled" if readonly else "normal"
        for entry in self._launch_param_entries:
            entry.configure(state=entry_state)
        for check in self._launch_param_checkbuttons:
            check.configure(state=entry_state)
        dropdown_state = "disabled" if readonly else "readonly"
        for dropdown in self._launch_param_dropdowns:
            dropdown.configure(state=dropdown_state)
        if not readonly:
            # The blanket loop above just re-enabled N
            # AND Load Range/max-load-count together -- re-apply the mode
            # switch's own restriction on top, so unlocking (Reset, a clean
            # exit, RING_VIZ_RESUMED) leaves only whichever pair the
            # CURRENTLY selected mode actually uses editable, same as right
            # after _build_ui runs.
            self._on_mode_changed()
            # Same for General Law's own theta lock -- the blanket loop above
            # just re-enabled general_law_theta_entry unconditionally too.
            self._on_general_law_mode_changed()

    def _on_mode_changed(self, _event=None):
        """Greys out whichever of N / Load Range's fields the CURRENT mode
        doesn't use, instead of leaving a stale, easy-to-miss leftover value
        in the inactive one able to silently change behavior (see
        _on_open's own load_range gating below, keyed off mode_var rather
        than "both fields happen to be non-empty" -- the old rule that could
        let a 26-digit leftover From value silently activate range mode).
        max_load_count is only ever meaningful together with Load Range, so
        it follows the same enabled state. Same for the sliding-window
        checkbox."""
        is_range = self.mode_var.get() == "range"
        self.n_entry.configure(state="disabled" if is_range else "normal")
        range_state = "normal" if is_range else "disabled"
        self.load_range_from_entry.configure(state=range_state)
        self.load_range_to_entry.configure(state=range_state)
        self.max_load_count_entry.configure(state=range_state)
        self._slide_load_range_check.configure(state=range_state)

    def _on_general_law_mode_changed(self, _event=None):
        """'bertrand'/
        'legendre' are RIGID modes -- theta is not a live parameter there
        (general_law_window_bounds ignores it entirely for these two, see
        that function's own doc-comment), so the theta entry is locked to a
        fixed display value instead of left showing whatever was last typed
        for stepped/sliding, which would look editable/live but silently do
        nothing. Re-enabled, keeping its current value as-is, on switching
        back to stepped/sliding -- same "remembers its last-used value"
        convention as every other launch-time field here. Called on the
        combobox's own <<ComboboxSelected>> event, and once more from
        _set_launch_params_readonly's unlock branch (mirrors _on_mode_
        changed's own re-apply-after-unlock convention) so Reset/RESUME
        can't leave a stale unlocked/locked state behind."""
        mode = self.general_law_mode_combo.get()
        if mode == "bertrand":
            self.general_law_theta_entry.configure(state="normal")
            self.general_law_theta_entry.delete(0, "end")
            self.general_law_theta_entry.insert(0, "1")
            self.general_law_theta_entry.configure(state="disabled")
        elif mode == "legendre":
            self.general_law_theta_entry.configure(state="normal")
            self.general_law_theta_entry.delete(0, "end")
            self.general_law_theta_entry.insert(0, "0.5")
            self.general_law_theta_entry.configure(state="disabled")
        else:
            self.general_law_theta_entry.configure(state="normal")

    def _on_n_changed(self, _event=None):
        """Live floor hint next to the N field -- purely informational (which
        10p{N} floor this N would fall in, via the SAME digit_count_floor()
        the Primes tab's own search box uses), never
        blocks typing on an invalid/incomplete value."""
        raw = self.n_entry.get().strip()
        if not raw:
            self.n_hint_var.set("")
            return
        n = _eval_quick_number(raw)
        if n is None or n < 0:
            self.n_hint_var.set(self.T("rings.hint_invalid"))
            return
        floor = storage.digit_count_floor(n) if n > 0 else 0
        self.n_hint_var.set(self.T("rings.hint_floor", floor=floor))

    def _restore_last_n(self, n):
        """VizTabBase hook: puts the last N the renderer reported back into the N field
        (see VizTabBase._poll_queue's exit branch)."""
        self.n_entry.delete(0, "end")
        self.n_entry.insert(0, str(n))
        self._on_n_changed()

    def _on_open(self):
        if self._resume_if_paused():
            return
        raw = self.n_entry.get().strip()
        n = _eval_quick_number(raw) if raw else None
        if n is None or n < 2:
            messagebox.showerror(self.T("rings.error_dialog_title"), self.T("rings.error_n_invalid"))
            return
        portal_folder = self._get_portal_folder()
        if not portal_folder or not os.path.isdir(portal_folder):
            messagebox.showerror(self.T("rings.error_dialog_title"), self.T("rings.error_no_portal"))
            return

        windows = []
        if self.bertrand_var.get():
            windows.append("bertrand")
        if self.legendre_var.get():
            windows.append("legendre")
        if self.general_law_var.get():
            windows.append("generalLaw")
        # Deliberately NOT _eval_quick_number here -- that helper is
        # int-only (see its own docstring), and theta is a fraction (e.g.
        # 0.5) -- a plain float() with a safe fallback to the same 0.5
        # default renderer.py's own --general-law-theta argparse default
        # uses is simpler and correct for this one field.
        try:
            theta = float(self.general_law_theta_entry.get().strip())
        except ValueError:
            theta = 0.5
        mode = self.general_law_mode_combo.get() or "sliding"

        # Same reasoning as theta above: point size is a float, and an
        # empty/invalid field should just omit --point-size entirely so
        # renderer.py's own argparse default (3.0) applies, rather than
        # silently forcing some fallback value here too.
        point_size_raw = self.point_size_entry.get().strip()
        try:
            point_size = float(point_size_raw) if point_size_raw else None
        except ValueError:
            point_size = None

        # Same empty-or-invalid-omits-the-flag convention
        # as point_size above.
        hit_point_size_raw = self.hit_point_size_entry.get().strip()
        try:
            hit_point_size = float(hit_point_size_raw) if hit_point_size_raw else None
        except ValueError:
            hit_point_size = None

        hud_font_size_raw = self.hud_font_size_entry.get().strip()
        try:
            hud_font_size = int(hud_font_size_raw) if hud_font_size_raw else None
        except ValueError:
            hud_font_size = None

        # Track P -- comma-separated prime values,
        # forwarded as-is (renderer.py's own --track-primes does the
        # digit/validity check, mirroring --windows's own error-reporting
        # convention -- see that module's main() for the parser.error()).
        track_primes_raw = self.track_primes_entry.get().strip()
        track_primes = [p.strip() for p in track_primes_raw.split(",") if p.strip()] if track_primes_raw else []
        auto_orbit = self.auto_orbit_var.get()

        # Which mode is active is decided EXPLICITLY by
        # mode_var (the radiobuttons next to N), not by whether From/To
        # happen to both be filled in -- that old implicit rule could let a
        # stale leftover From value silently activate range mode. Range mode
        # with missing/invalid From or To now fails loudly (an error dialog,
        # same convention as the N-invalid case above) instead of silently
        # falling back to sequential.
        #
        # Parsing itself goes through the SAME _eval_quick_number
        # the N field above already uses (plain digits, "10**5"-style
        # expressions, and -- via that function's own parse_big_int fast
        # path -- "a*10^b"/scientific notation too), instead of a bare
        # `.isdigit()` check that rejected anything but plain decimal
        # digits. A real archive floor's own magnitude (floor 25 alone is
        # 26 digits) is exactly why this matters here.
        range_mode_selected = self.mode_var.get() == "range"
        range_from_raw = self.load_range_from_entry.get().strip()
        range_to_raw = self.load_range_to_entry.get().strip()
        load_range = None
        if range_mode_selected:
            range_from = _eval_quick_number(range_from_raw) if range_from_raw else None
            range_to = _eval_quick_number(range_to_raw) if range_to_raw else None
            if range_from is None or range_to is None or range_from < 0 or range_to < 0:
                messagebox.showerror(self.T("rings.error_dialog_title"), self.T("rings.error_range_invalid"))
                return
            load_range = (range_from, range_to)

        # Same empty-or-invalid-omits-the-flag
        # convention as point_size/hit_point_size/hud_font_size above --
        # renderer.py's own argparse default (2,000,000) applies when this
        # is left blank or unparseable. Same _eval_quick_number convention
        # as load_range above. Only meaningful in range mode, but parsed
        # unconditionally like every other optional field here -- harmless
        # (never forwarded) when mode is sequential.
        max_load_count_raw = self.max_load_count_entry.get().strip()
        max_load_count = _eval_quick_number(max_load_count_raw) if max_load_count_raw else None
        if max_load_count is not None and max_load_count < 0:
            max_load_count = None

        # Sliding window -- default OFF (see the checkbox above). No chunk-size
        # field: every slid-in chunk reuses max_load_count's value (passed to
        # build_renderer_argv below). Gated on range_mode_selected, like load_range
        # just above: _on_mode_changed() only greys out the checkbox WIDGET and
        # never clears slide_load_range_var, so a value left checked from an
        # earlier range-mode session (or a persisted settings file) must not be
        # forwarded in sequential mode -- renderer.py's argparse rejects
        # --slide-load-range without --load-range.
        slide_load_range = self.slide_load_range_var.get() if range_mode_selected else False

        # Same empty-or-invalid-omits-the-flag
        # convention as every other numeric field here -- renderer.py's own
        # argparse/clamp_tempo_ms default (120ms, clamped to [30,2000])
        # applies when this is left blank or unparseable.
        tempo_ms_raw = self.tempo_ms_entry.get().strip()
        tempo_ms = _eval_quick_number(tempo_ms_raw) if tempo_ms_raw else None

        # Line mode requires a valid Load Range (it draws THAT fixed set of
        # real primes as its dot row -- see renderer.py's own --viz-mode
        # line validation, mirrored here so the error surfaces in this
        # dialog instead of the subprocess's own parser.error() exit).
        # The pattern (k/p0) itself is optional within line mode -- see
        # build_line_vertex_data's own empty-offsets case -- but if either
        # field was filled in, both must parse and satisfy the same k>=2/
        # p0>2 rule renderer.py's own argparse enforces, so a half-typed
        # pattern fails loudly here rather than as a confusing subprocess
        # launch error.
        line_mode = self.line_mode_var.get()
        pattern_k_raw = self.pattern_k_entry.get().strip()
        pattern_p0_raw = self.pattern_p0_entry.get().strip()
        pattern_k = None
        pattern_p0 = None
        if line_mode:
            if load_range is None:
                messagebox.showerror(self.T("rings.error_dialog_title"),
                                      self.T("rings.error_line_mode_needs_range"))
                return
            pattern_k = _eval_quick_number(pattern_k_raw) if pattern_k_raw else None
            pattern_p0 = _eval_quick_number(pattern_p0_raw) if pattern_p0_raw else None
            if (pattern_k_raw or pattern_p0_raw) and (
                pattern_k is None or pattern_p0 is None or pattern_k < 2 or pattern_p0 <= 2
            ):
                messagebox.showerror(self.T("rings.error_dialog_title"), self.T("rings.error_pattern_invalid"))
                return

        argv = build_renderer_argv(portal_folder, n, windows=windows,
                                    general_law_theta=theta, general_law_mode=mode,
                                    point_size=point_size,
                                    track_primes=track_primes, auto_orbit=auto_orbit,
                                    load_range=load_range,
                                    hit_point_size=hit_point_size,
                                    hud_font_size=hud_font_size,
                                    audio=self.audio_enabled.get(),
                                    sound_low=INSTRUMENTS[self.audio_choices['low'].current()],
                                    sound_prime=INSTRUMENTS[self.audio_choices['prime'].current()],
                                    sound_lcm=INSTRUMENTS[self.audio_choices['lcm'].current()],
                                    pipe_stdin_commands=True,
                                    max_load_count=max_load_count,
                                    tempo_ms=tempo_ms,
                                    viz_mode="line" if line_mode else "rings",
                                    pattern_seed_k=pattern_k,
                                    pattern_seed_start=pattern_p0,
                                    pattern_step_mode=self.pattern_step_mode_var.get(),
                                    pattern_stop_on_match=self.pattern_stop_on_match_var.get(),
                                    line_axis_curved=self.line_axis_curved_var.get(),
                                    slide_load_range=slide_load_range)
        # Persist every launch-time field as-typed, so the NEXT
        # launch (this session's Reset+Start, or a whole new app restart) reopens
        # with these same values instead of the tab's hardcoded first-run defaults
        # -- see ring_viz_params's own doc-comment in app_settings.py. Raw strings/
        # bools straight from the widgets, not the parsed n/point_size/etc. above,
        # so a value that failed to parse (and therefore fell back to a CLI-flag-
        # omitting None here) still round-trips as the text the user actually typed.
        if self._app_settings is not None:
            self._app_settings.set_ring_viz_params({
                "n": raw,
                "point_size": point_size_raw,
                "hit_point_size": hit_point_size_raw,
                "hud_font_size": hud_font_size_raw,
                "audio_enabled": self.audio_enabled.get(),
                "sound_low": INSTRUMENTS[self.audio_choices['low'].current()],
                "sound_prime": INSTRUMENTS[self.audio_choices['prime'].current()],
                "sound_lcm": INSTRUMENTS[self.audio_choices['lcm'].current()],
                "bertrand": self.bertrand_var.get(),
                "legendre": self.legendre_var.get(),
                "general_law": self.general_law_var.get(),
                "general_law_theta": self.general_law_theta_entry.get().strip(),
                "general_law_mode": mode,
                "track_primes": track_primes_raw,
                "auto_orbit": auto_orbit,
                "mode": self.mode_var.get(),
                "tempo_ms": tempo_ms_raw,
                "load_range_from": range_from_raw,
                "load_range_to": range_to_raw,
                "max_load_count": max_load_count_raw,
                "slide_load_range": slide_load_range,
                "line_mode": line_mode,
                "pattern_k": pattern_k_raw,
                "pattern_p0": pattern_p0_raw,
                "pattern_step_mode": self.pattern_step_mode_var.get(),
                "pattern_stop_on_match": self.pattern_stop_on_match_var.get(),
                "line_axis_curved": self.line_axis_curved_var.get(),
            })
        self._launch_renderer(argv, n, LocalLoggedRunner)
