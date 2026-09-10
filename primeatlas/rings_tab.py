"""
rings_tab.py -- RingsTab(BaseTab), the "Ring visualization" tab (Faza 3, see PLAN.md
at the repo root for the full phased rollout this belongs to). Launches the Faza 0-2
GPU renderer (primeatlas/ring_viz/renderer.py) as a separate native Windows subprocess
against the app's own currently-configured magazyn, given a target N.

WHY A SUBPROCESS, NOT EMBEDDED IN THIS WINDOW: GL's own event loop does not compose
with Tkinter's mainloop() -- see primeatlas/ring_viz/__init__.py's own docstring for
the full reasoning; already settled in PLAN.md's "Window embedding" design decision
before any of this tab's own code was written.

WHY LocalLoggedRunner AND NOT WslLoggedRunner: renderer.py is a plain native Windows
Python script (moderngl+glfw, no WSL involved anywhere) -- LocalLoggedRunner
(primeatlas/generation.py) already exists for exactly this "ordinary local subprocess,
live stdout capture on a background thread" shape (its only prior caller is the sympy
installer in settings_tab.py). PLAN.md's own point 5 said to reuse "the existing
WSL/GenerationConsole subprocess-management pattern" -- LocalLoggedRunner turned out to
be the closer fit once it was clear this specific launch is native, not WSL; GenerationConsole
(the collapsible live-output pane widget) is still reused as-is for the actual UI, since it
has no WSL-specific assumption baked in at all.

renderer.py's own print() calls (loading progress, the per-N-change rebuild line, see
that module's own docstring) already write to stdout -- LocalLoggedRunner's queue-based
capture surfaces those as real, user-visible progress text in this tab's console pane,
not just the GL window's own title bar (which nothing outside that window can see).

get_portal_folder is a deferred callable (same dependency-injection pattern as every
other extracted tab -- see research_goldbach_tab.py's own docstring), read fresh at
launch time rather than captured once, so a Settings-tab storage-path change takes
effect on the NEXT launch without this tab needing its own change-notification wiring.
"""
import json
import os
import queue
import sys
import tkinter as tk
from tkinter import ttk, messagebox

from .base_tab import BaseTab
from .generation import LocalLoggedRunner, _eval_quick_number
from .generation_console import GenerationConsole
from . import storage
from .ring_viz.audio import INSTRUMENTS

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
RENDERER_SCRIPT = os.path.join(_THIS_DIR, "ring_viz", "renderer.py")

# [ADDED Faza 11, see PLAN.md] Must match renderer.py's own emit_hud_state()
# print prefix exactly -- kept as one shared constant name (even though it's
# only ever referenced in THIS file, renderer.py runs as a separate
# subprocess and can't import a shared constant from here) so a future
# rename doesn't silently desync the two string literals.
_HUD_STATE_PREFIX = "HUD_STATE:"

# [ADDED 2026-09-10, Faza 13] Must match renderer.py's own two plain
# print("RING_VIZ_PAUSED"/"RING_VIZ_RESUMED") lines exactly -- these are NOT
# JSON payloads like _HUD_STATE_PREFIX, just bare sentinel lines, since
# there's no data to carry, only a state transition to react to.
_RING_VIZ_PAUSED_LINE = "RING_VIZ_PAUSED"
_RING_VIZ_RESUMED_LINE = "RING_VIZ_RESUMED"


def build_renderer_argv(portal_folder, upto, python_executable=None,
                         windows=(), general_law_theta=0.5, general_law_mode="stepped",
                         point_size=None, track_primes=(), auto_orbit=False, load_range=None,
                         hit_point_size=None, hud_font_size=None, audio=False,
                         sound_low='sine', sound_prime='triangle', sound_lcm='choir',
                         pipe_stdin_commands=False):
    """Builds the argv for launching renderer.py against a real magazyn.

    Uses `python_executable` (defaults to sys.executable -- THIS SAME Python
    interpreter PrimeAtlas itself is currently running under) rather than a
    bare "python" resolved from PATH, so the launch can never accidentally
    pick a different, possibly moderngl/glfw-less Python install if more
    than one exists on the machine.

    Deliberately launches RENDERER_SCRIPT as a PLAIN SCRIPT PATH argument
    (`[exe, RENDERER_SCRIPT, ...]`), never `-m primeatlas.ring_viz.renderer`
    -- see renderer.py's own module docstring for exactly why that matters
    (its internal sys.path fix for the prime_sieve/ sibling directory runs
    too late to help a `-m`/dotted-import invocation, which imports the
    primeatlas package first).

    [ADDED Faza 4, see PLAN.md] `windows` -- an iterable of window family ids
    (any of "bertrand"/"legendre"/"generalLaw") to highlight, chosen once at
    launch time via this tab's checkboxes (there is no live in-GL-window
    toggle -- see renderer.py's own "no live in-window toggle yet" note).
    `general_law_theta`/`general_law_mode` are only appended when
    "generalLaw" is among `windows` -- passing them unconditionally would be
    harmless (renderer.py ignores them when that family isn't enabled) but
    a shorter argv is easier to read in the console pane's own `$ ...` echo
    line.

    [ADDED as part of Faza 4's point-size investigation, 2026-09-04]
    `point_size` -- None (default) omits --point-size entirely, so
    renderer.py's own argparse default (3.0) applies; a real value is
    forwarded as-is. Exposed here (rather than only via renderer.py's own
    CLI, which needs hand-editing its argparse default to test) specifically
    so a real value change is verifiable from the GUI alone -- see
    renderer.py's own [diag] startup print for the other half of that
    investigation (confirming the requested value actually reaches the
    renderer, vs. a possible GL_POINT_SIZE_RANGE hardware/driver clamp).

    [ADDED Faza 6, see PLAN.md] `track_primes` -- an iterable of prime
    values (any order/dupes as typed by the user, see ring_geometry.py's
    own filter_active_tracked docstring for why order is preserved) chosen
    once at launch time via the new "Track P" field, forwarded as-is to
    renderer.py's --track-primes. `auto_orbit` mirrors the JS's auto-orbit
    checkbox; same launch-time-only convention as `windows` above -- no
    live in-GL-window toggle for either.

    [ADDED Faza 9, see PLAN.md] `load_range` -- None (default, sequential
    mode, unchanged behavior) or a (from, to) pair forwarded as-is to
    renderer.py's --load-range. As with track_primes, the string values are
    NOT int()-cast here -- an empty or malformed field just omits
    --load-range entirely rather than raising inside the GUI thread;
    renderer.py's own main() does the real format validation (same
    parser.error() convention as --track-primes/--windows).

    [ADDED Faza 11C, 2026-09-06 -- Artur's real-screen report: "hud jest
    tak mikroskopijny ... że nie jestem wstanie go przeczytać"] `hit_point_size`
    -- None (default) omits --hit-point-size entirely, so renderer.py's own
    default (fall back to --point-size) applies; a real value gives rings on
    the vertical reference line (divisors of N) an independent on-screen
    size from every other ring. `hud_font_size` -- None (default) omits
    --hud-font-size entirely, so renderer.py's own argparse default (16px)
    applies; a real value scales the on-canvas HUD text. Same
    omit-if-None convention as `point_size` above."""
    exe = python_executable or sys.executable
    argv = [exe, RENDERER_SCRIPT, "--source", "magazyn",
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
    if audio:
        argv += ['--audio', '--sound-low', sound_low, '--sound-prime', sound_prime,
                 '--sound-lcm', sound_lcm]
    # [ADDED Faza 13, see PLAN.md] Opt-in ONLY when the caller is actually
    # going to act on the RING_VIZ_PAUSED/RESUMED lines this makes
    # renderer.py print (see that flag's own doc-comment there) --
    # RingsTab._on_open is the one real caller and always passes True;
    # False (default) keeps every existing pure-function test above byte-
    # for-byte unchanged, and keeps a plain terminal invocation of this
    # function's own CLI output copy-pasteable with no surprise behavior.
    if pipe_stdin_commands:
        argv += ["--pipe-stdin-commands"]
    return argv


class RingsTab(BaseTab):
    def __init__(self, parent, get_portal_folder, status_var, translator, totals_progress):
        super().__init__(parent, translator)
        self._get_portal_folder = get_portal_folder
        self.status = status_var
        self.totals_progress = totals_progress
        self._runner = None
        self._queue = None
        # [ADDED 2026-09-10] Last N seen in a HUD_STATE line from the most
        # recently running process (see _apply_hud_state/_poll_queue below).
        # Powers the "Uruchom / Wznów" (Start/Resume) button: when the GL
        # window closes on its own (Esc, window-close control, or a crash)
        # rather than via an explicit Reset click, the N field is updated to
        # this value so the next launch reopens right where playback left
        # off, instead of wherever the field happened to still say. Cleared
        # by _on_reset, which is the one path that deliberately discards it.
        self._last_hud_n = None
        # [ADDED 2026-09-10, Faza 13] True while the running renderer.py
        # process is alive but hidden/idling, waiting for a RESUME command
        # (see _poll_queue's RING_VIZ_PAUSED/RESUMED handling below and
        # renderer.py's own start_stdin_command_reader doc-comment for the
        # full protocol). Distinct from "not running at all" -- open_button
        # is re-enabled in BOTH cases, but only this one sends "RESUME"
        # over stdin instead of launching a brand new subprocess.
        self._paused = False
        self._build_ui()

    def _build_ui(self):
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=12, pady=12)

        intro = ttk.Label(container, text=self.T("rings.intro"), wraplength=760, justify="left")
        intro.pack(anchor="w", pady=(0, 10))

        field_row = ttk.Frame(container)
        field_row.pack(fill="x", pady=(0, 6))
        ttk.Label(field_row, text=self.T("rings.field_n")).pack(side="left")
        self.n_entry = ttk.Entry(field_row, width=28)
        # [CHANGED 2026-09-10] Artur asked for N pre-filled at startup instead
        # of an empty field, so the field/hint are non-empty on first render.
        self.n_entry.insert(0, "2")
        self.n_entry.pack(side="left", padx=(6, 10))
        self.n_hint_var = tk.StringVar(value="")
        ttk.Label(field_row, textvariable=self.n_hint_var, foreground="#888888").pack(side="left")
        self.n_entry.bind("<KeyRelease>", self._on_n_changed)
        self._on_n_changed()

        # [ADDED as part of Faza 4's point-size investigation, 2026-09-04]
        # Exposed here (instead of only reachable by hand-editing
        # renderer.py's argparse default) so a real value change is
        # verifiable from the GUI alone -- see build_renderer_argv's own
        # doc-comment for the full context.
        point_size_row = ttk.Frame(container)
        point_size_row.pack(fill="x", pady=(0, 6))
        ttk.Label(point_size_row, text=self.T("rings.point_size_label")).pack(side="left")
        self.point_size_entry = ttk.Entry(point_size_row, width=8)
        # [CHANGED 2026-09-10] Artur's own chosen default, raised from 3.0 to 15.
        self.point_size_entry.insert(0, "15")
        self.point_size_entry.pack(side="left", padx=(6, 0))

        # [ADDED Faza 11C, see build_renderer_argv's own doc-comment --
        # Artur's real-screen report that the HUD was unreadably small and
        # that hit-rings (on the vertical reference line) needed an
        # independent size from every other ring.] Pre-filled with Artur's
        # own chosen defaults (2026-09-09: hit-ring size 40, HUD font 35) --
        # same convention as point_size_entry's own "3.0" pre-fill above --
        # so these values are visibly wired in at launch rather than hidden
        # behind a blank field the user has to know to fill in. Clearing the
        # field still omits the CLI flag entirely (renderer.py's own
        # argparse defaults, ALSO 40/35 as of this phase, apply then too).
        hit_point_size_row = ttk.Frame(container)
        hit_point_size_row.pack(fill="x", pady=(0, 6))
        ttk.Label(hit_point_size_row, text=self.T("rings.hit_point_size_label")).pack(side="left")
        self.hit_point_size_entry = ttk.Entry(hit_point_size_row, width=8)
        # [CHANGED 2026-09-10] Artur's own chosen default, lowered from 40 to 20.
        self.hit_point_size_entry.insert(0, "20")
        self.hit_point_size_entry.pack(side="left", padx=(6, 0))

        hud_font_size_row = ttk.Frame(container)
        hud_font_size_row.pack(fill="x", pady=(0, 6))
        ttk.Label(hud_font_size_row, text=self.T("rings.hud_font_size_label")).pack(side="left")
        self.hud_font_size_entry = ttk.Entry(hud_font_size_row, width=8)
        self.hud_font_size_entry.insert(0, "35")
        self.hud_font_size_entry.pack(side="left", padx=(6, 0))
        audio_row = ttk.Frame(container)
        audio_row.pack(fill='x', pady=(0, 6))
        self.audio_enabled = tk.BooleanVar(value=False)
        self._audio_enable_check = ttk.Checkbutton(audio_row, text=self.T('rings.audio_enable'),
                                                     variable=self.audio_enabled)
        self._audio_enable_check.pack(side='left')
        self.audio_choices = {}
        for channel, default in (('low', 'sine'), ('prime', 'triangle'), ('lcm', 'choir')):
            ttk.Label(audio_row, text=self.T('rings.sound_' + channel)).pack(side='left', padx=(8, 3))
            choice = ttk.Combobox(audio_row, state='readonly', width=11,
                                 values=[self.T('rings.instrument_' + name) for name in INSTRUMENTS])
            choice.current(INSTRUMENTS.index(default))
            choice.pack(side='left')
            self.audio_choices[channel] = choice
        ttk.Label(container, text=self.T('rings.audio_hint')).pack(anchor='w', pady=(0, 6))

        # [ADDED Faza 4, see PLAN.md] Window-highlight-family checkboxes --
        # chosen once here, at launch time, and passed as --windows to
        # renderer.py (see build_renderer_argv's own doc-comment for why
        # this is launch-time-only rather than a live in-GL-window toggle).
        windows_row = ttk.Frame(container)
        windows_row.pack(fill="x", pady=(0, 6))
        ttk.Label(windows_row, text=self.T("rings.windows_label")).pack(side="left")
        self.bertrand_var = tk.BooleanVar(value=False)
        self._bertrand_check = ttk.Checkbutton(windows_row, text=self.T("rings.window_bertrand"),
                                                 variable=self.bertrand_var)
        self._bertrand_check.pack(side="left", padx=(6, 0))
        self.legendre_var = tk.BooleanVar(value=False)
        self._legendre_check = ttk.Checkbutton(windows_row, text=self.T("rings.window_legendre"),
                                                 variable=self.legendre_var)
        self._legendre_check.pack(side="left", padx=(6, 0))
        self.general_law_var = tk.BooleanVar(value=False)
        self._general_law_check = ttk.Checkbutton(windows_row, text=self.T("rings.window_general_law"),
                                                     variable=self.general_law_var)
        self._general_law_check.pack(side="left", padx=(6, 0))

        general_law_row = ttk.Frame(container)
        general_law_row.pack(fill="x", pady=(0, 10))
        ttk.Label(general_law_row, text=self.T("rings.general_law_theta_label")).pack(side="left")
        self.general_law_theta_entry = ttk.Entry(general_law_row, width=6)
        self.general_law_theta_entry.insert(0, "0.5")
        self.general_law_theta_entry.pack(side="left", padx=(6, 16))
        ttk.Label(general_law_row, text=self.T("rings.general_law_mode_label")).pack(side="left")
        self.general_law_mode_combo = ttk.Combobox(general_law_row, width=10, state="readonly",
                                                     values=["stepped", "sliding"])
        self.general_law_mode_combo.set("stepped")
        self.general_law_mode_combo.pack(side="left", padx=(6, 0))

        # [ADDED Faza 6, see PLAN.md] Track P field -- comma-separated prime
        # values, forwarded as-is to renderer.py's --track-primes (see
        # build_renderer_argv's own doc-comment). Launch-time-only, same
        # convention as the windows checkboxes above: no live in-GL-window
        # text field yet. "Auto orbit" mirrors the JS's auto-cycle mode
        # (mutually exclusive in effect with a real Track P list -- see
        # renderer.py's own rebuild_buffer(), which skips the tracked-filter
        # entirely when auto-orbit is on); left as an independent checkbox
        # here rather than disabling the Track P field, since Faza 10 is
        # what actually wires auto-orbit's visible behavior.
        track_row = ttk.Frame(container)
        track_row.pack(fill="x", pady=(0, 6))
        ttk.Label(track_row, text=self.T("rings.track_primes_label")).pack(side="left")
        self.track_primes_entry = ttk.Entry(track_row, width=20)
        self.track_primes_entry.pack(side="left", padx=(6, 16))
        self.auto_orbit_var = tk.BooleanVar(value=False)
        self._auto_orbit_check = ttk.Checkbutton(track_row, text=self.T("rings.auto_orbit_label"),
                                                   variable=self.auto_orbit_var)
        self._auto_orbit_check.pack(side="left")

        # [ADDED Faza 9, see PLAN.md] Load Range -- From/To fields, launch-time
        # only (same convention as every other field on this tab: read once by
        # _on_open, no live subprocess IPC). Leaving BOTH empty keeps today's
        # sequential-mode behavior unchanged; filling in both switches to a
        # fixed range mode that auto-tracks every prime in it (see
        # renderer.py's own --load-range handling in run() for the full
        # behavior, ported from the HTML's #loadPrimeRange/"Load Range"
        # button).
        range_row = ttk.Frame(container)
        range_row.pack(fill="x", pady=(0, 10))
        ttk.Label(range_row, text=self.T("rings.load_range_label")).pack(side="left")
        self.load_range_from_entry = ttk.Entry(range_row, width=16)
        self.load_range_from_entry.pack(side="left", padx=(6, 6))
        ttk.Label(range_row, text=self.T("rings.load_range_to_label")).pack(side="left")
        self.load_range_to_entry = ttk.Entry(range_row, width=16)
        self.load_range_to_entry.pack(side="left", padx=(6, 0))

        # [RELABELED 2026-09-10] These two buttons keep their original
        # attribute names (open_button/stop_button -- unchanged, so
        # test_rings_tab.py's state checks keep working) and _on_open's own
        # launch logic is untouched, but their labels/semantics now read as
        # Start/Resume and Reset -- see _on_reset's and __init__'s own
        # doc-comments for how the resume half works (short version: the N
        # field gets silently updated to the last live N whenever the GL
        # window closes on its own, so clicking this button again reopens
        # right there; Reset is the one path that discards that and puts
        # the field back to the tab's own startup default instead).
        button_row = ttk.Frame(container)
        button_row.pack(fill="x", pady=(0, 10))
        self.open_button = ttk.Button(button_row, text=self.T("rings.open_button"),
                                       command=self._on_open)
        self.open_button.pack(side="left")
        self.stop_button = ttk.Button(button_row, text=self.T("rings.stop_button"),
                                       command=self._on_reset, state="disabled")
        self.stop_button.pack(side="left", padx=(6, 0))

        # [ADDED Faza 11, see PLAN.md] Always-current HUD status panel --
        # separate from self.console below on purpose. renderer.py's own
        # human-readable HUD lines (N, factors of N, tracked/LCM state,
        # etc.) already reached that console pane since Faza 4/7 -- but
        # during Faza 10 playback they reprint every single tick and
        # scroll past far too fast to ever read (Artur, 2026-09-06, right
        # after confirming Faza 10 works: "brak panelu HUD w ogóle" -- the
        # text existed, there was just no ALWAYS-VISIBLE snapshot of it).
        # This label's content gets REPLACED wholesale on every
        # "HUD_STATE:" line (see renderer.py's own emit_hud_state()), never
        # appended -- see _on_console_line's own doc-comment for how those
        # lines are told apart from ordinary console output.
        hud_frame = ttk.LabelFrame(container, text=self.T("rings.hud_panel_title"))
        hud_frame.pack(fill="x", pady=(0, 10))
        self.hud_var = tk.StringVar(value=self.T("rings.hud_panel_placeholder"))
        ttk.Label(hud_frame, textvariable=self.hud_var, justify="left", anchor="w",
                  font=("TkFixedFont",)).pack(fill="x", padx=8, pady=6)

        self.console = GenerationConsole(container, self.T, height=14,
                                          window_title=self.T("rings.console_title"))

        # [ADDED 2026-09-10, Faza 13] Every field below is read ONCE, at
        # _on_open's launch-time argv build -- see build_renderer_argv's own
        # doc-comment. While the process is paused-and-resumable
        # (self._paused, see _set_launch_params_readonly's own doc-comment),
        # editing any of them would silently do nothing until the NEXT fresh
        # launch, which is exactly the kind of "changing this looks like it
        # should matter" trap Artur flagged. Split into two groups because
        # ttk widgets don't share one disabled-state spelling: entries/
        # checkbuttons use "normal"/"disabled", comboboxes use "readonly"
        # (their own normal state here, since they're never free-text) vs
        # "disabled".
        self._launch_param_entries = [
            self.n_entry, self.point_size_entry, self.hit_point_size_entry,
            self.hud_font_size_entry, self.general_law_theta_entry,
            self.track_primes_entry, self.load_range_from_entry, self.load_range_to_entry,
        ]
        self._launch_param_checkbuttons = [
            self._audio_enable_check, self._bertrand_check, self._legendre_check,
            self._general_law_check, self._auto_orbit_check,
        ]
        self._launch_param_dropdowns = [
            self.general_law_mode_combo,
            self.audio_choices['low'], self.audio_choices['prime'], self.audio_choices['lcm'],
        ]

    def _set_launch_params_readonly(self, readonly):
        """[ADDED 2026-09-10, Faza 13] Toggles every launch-time-only field
        (N, point sizes, window-highlight checkboxes, Track P, Load Range,
        audio instrument pickers, ...) between editable and read-only.
        Called with readonly=True the moment the process reports itself
        paused (RING_VIZ_PAUSED, see _poll_queue below) -- while paused, the
        Start/Resume button sends RESUME instead of relaunching, so these
        fields would no longer feed anything even though they still LOOK
        live and editable (Artur, 2026-09-10: "sugeruje że zmiana ich coś
        zmieni, a to jest używane tylko przy uruchomieniu"). Called with
        readonly=False on RING_VIZ_RESUMED, on Reset, and on any real
        process exit, so the fields are always editable again the instant a
        fresh launch (not a resume) is what the next Start/Resume click
        will actually do."""
        entry_state = "disabled" if readonly else "normal"
        for entry in self._launch_param_entries:
            entry.configure(state=entry_state)
        for check in self._launch_param_checkbuttons:
            check.configure(state=entry_state)
        dropdown_state = "disabled" if readonly else "readonly"
        for dropdown in self._launch_param_dropdowns:
            dropdown.configure(state=dropdown_state)

    def _on_n_changed(self, _event=None):
        """Live floor hint next to the N field -- purely informational (which
        10p{N} floor this N would fall in, via the SAME digit_count_floor()
        the Primes tab's own search box uses -- see PLAN.md point 4), never
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

    def _on_open(self):
        # [ADDED 2026-09-10, Faza 13] Live resume path: the process never
        # actually exited, it's just idling with its window hidden (see
        # renderer.py's own PAUSE/RESUME protocol) -- send it a command
        # instead of launching a brand new one, so N, playback state,
        # tempo, LCM cache, and (the whole point) audio all continue
        # exactly as they were, with zero discontinuity. is_running() is
        # still True here (the OS process never died), which is exactly
        # why self._paused is tracked as its own flag rather than reusing
        # that check.
        if self._runner is not None and self._paused:
            self._runner.send_line("RESUME")
            return
        if self._runner is not None and self._runner.is_running():
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
        mode = self.general_law_mode_combo.get() or "stepped"

        # Same reasoning as theta above: point size is a float, and an
        # empty/invalid field should just omit --point-size entirely so
        # renderer.py's own argparse default (3.0) applies, rather than
        # silently forcing some fallback value here too.
        point_size_raw = self.point_size_entry.get().strip()
        try:
            point_size = float(point_size_raw) if point_size_raw else None
        except ValueError:
            point_size = None

        # [ADDED Faza 11C] Same empty-or-invalid-omits-the-flag convention
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

        # [ADDED Faza 6, see PLAN.md] Track P -- comma-separated prime values,
        # forwarded as-is (renderer.py's own --track-primes does the
        # digit/validity check, mirroring --windows's own error-reporting
        # convention -- see that module's main() for the parser.error()).
        track_primes_raw = self.track_primes_entry.get().strip()
        track_primes = [p.strip() for p in track_primes_raw.split(",") if p.strip()] if track_primes_raw else []
        auto_orbit = self.auto_orbit_var.get()

        # [ADDED Faza 9, see PLAN.md] Load Range -- both fields must be
        # non-empty AND parse as plain integers to activate range mode;
        # anything else (both blank, one blank, garbage text) silently
        # falls back to sequential mode rather than raising inside the GUI
        # thread -- renderer.py's own --load-range parsing/validation
        # (main()'s parser.error, run()'s load_prime_range_slice) is where
        # a well-formed-but-nonsensical range (e.g. FROM > TO, or TO beyond
        # what's loaded) surfaces, as a normal subprocess error visible in
        # the console pane, same convention as track_primes above.
        range_from_raw = self.load_range_from_entry.get().strip()
        range_to_raw = self.load_range_to_entry.get().strip()
        load_range = None
        if range_from_raw and range_to_raw and range_from_raw.isdigit() and range_to_raw.isdigit():
            load_range = (int(range_from_raw), int(range_to_raw))

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
                                    pipe_stdin_commands=True)
        q = queue.Queue()
        # [ADDED 2026-09-10, Faza 13] pipe_stdin=True so send_line("RESUME")
        # further down (and in _on_open's own live-resume branch above) has
        # an actual pipe to write to -- see LocalLoggedRunner's own
        # doc-comment for why this is opt-in rather than the default.
        runner = LocalLoggedRunner(argv, q, pipe_stdin=True)
        self._runner = runner
        self._queue = q
        self._paused = False
        self.open_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.console.show()
        self.console.append(self.T("rings.console_launching", n=f"{n:,}") + "\n")
        self.status.set(self.T("rings.status_launching"))
        # [ADDED Faza 11] Reset the HUD panel back to its placeholder text
        # on every new launch -- otherwise a stale snapshot from a PREVIOUS
        # run (different N entirely) would sit there until the new
        # process's first rebuild happens to emit its own HUD_STATE line.
        self.hud_var.set(self.T("rings.hud_panel_placeholder"))
        runner.start()
        self._poll_queue()

    def _on_reset(self):
        """[RENAMED from _on_stop, 2026-09-10] Closes the GL window's own
        process, same as before -- but ALSO discards the resume state
        (_last_hud_n) and puts the N field back to its own startup default,
        which is what distinguishes an explicit Reset click from just
        closing the GL window yourself (Esc / the window's own close
        control): a plain close is handled by _poll_queue's own __exit__
        branch below, which treats it as an implicit pause and preserves
        the last-seen N for the Start/Resume button; THIS path means the
        user asked to throw that away and start clean next time."""
        if self._runner is not None:
            self._runner.stop()
        self._last_hud_n = None
        # [ADDED 2026-09-10, Faza 13] terminate() kills the OS process
        # outright regardless of whether it's currently idling in the
        # hidden-window pause loop or actively rendering -- no special-
        # casing needed there -- but the Tkinter-side _paused flag is only
        # ever cleared by a RING_VIZ_RESUMED line, which will never arrive
        # for a process we just killed, so it must be reset explicitly here.
        self._paused = False
        # Don't wait for the async __exit__ queue item to re-enable these --
        # Reset is a deliberate "I'm done with this run" click, so the
        # fields should read as editable again immediately, not lag a poll
        # cycle behind terminate()'s own OS-level kill.
        self._set_launch_params_readonly(False)
        self.n_entry.delete(0, "end")
        self.n_entry.insert(0, "2")
        self._on_n_changed()

    def _poll_queue(self):
        if self._queue is None:
            return
        try:
            while True:
                item = self._queue.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__exit__":
                    code = item[1]
                    # [ADDED 2026-09-10, Faza 13] The process is actually
                    # gone now (proc.wait() returned), whether it was paused
                    # or not -- clear the flag so a later _on_open never
                    # mistakes a brand-new launch for a resume.
                    self._paused = False
                    self.open_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    # A real exit always means the fields are editable again
                    # -- covers both "exited while paused" (readonly was
                    # True) and the ordinary running-then-exits case (already
                    # editable, this is just a harmless no-op then).
                    self._set_launch_params_readonly(False)
                    if code == 0:
                        self.console.append(self.T("rings.console_closed_ok") + "\n")
                        self.status.set(self.T("rings.status_closed"))
                    else:
                        self.console.append(self.T("rings.console_closed_error", code=code) + "\n")
                        self.status.set(self.T("rings.status_error"))
                    # [ADDED 2026-09-10] Implicit-pause resume: this branch
                    # fires whether the process ended by itself (Esc / the
                    # GL window's own close control / a crash) or via the
                    # Reset button (_on_reset) -- but _on_reset already
                    # cleared _last_hud_n to None BEFORE calling
                    # runner.stop(), so it always reads None here and this
                    # is a no-op on that path. Any other exit means the user
                    # didn't explicitly ask to discard progress, so drop the
                    # last N seen in a HUD_STATE line into the N field --
                    # the Start/Resume button's next click reopens right
                    # there instead of at whatever the field last said.
                    if self._last_hud_n is not None:
                        self.n_entry.delete(0, "end")
                        self.n_entry.insert(0, str(self._last_hud_n))
                        self._on_n_changed()
                    self._runner = None
                    self._queue = None
                    return
                # [ADDED Faza 11, see PLAN.md] renderer.py's own
                # emit_hud_state() prints exactly one such line per HUD
                # refresh (see that function's own doc-comment) --
                # LocalLoggedRunner's _read_loop puts one whole stdout
                # line per queue item (confirmed against its own
                # `for line in self.proc.stdout` body), so a plain
                # startswith check is reliable here, no partial-line
                # reassembly needed. Routed to the HUD panel INSTEAD OF
                # the scrolling console -- a raw JSON blob in the log
                # would just be noise next to the human-readable HUD
                # lines that already print alongside it.
                # [ADDED 2026-09-10, Faza 13] The process is idling with its
                # window hidden, not exiting -- so this does NOT go through
                # the __exit__ branch above (the OS process is still alive,
                # LocalLoggedRunner's _read_loop only puts __exit__ once
                # proc.wait() actually returns). open_button is re-enabled so
                # Start/Resume becomes clickable again, but stop_button stays
                # enabled too since Reset must still be able to kill a paused
                # process (LocalLoggedRunner.stop()'s terminate() call works
                # regardless of what the subprocess's Python code is doing).
                if item.strip() == _RING_VIZ_PAUSED_LINE:
                    self._paused = True
                    self.open_button.configure(state="normal")
                    self.status.set(self.T("rings.status_paused"))
                    self.console.append(self.T("rings.console_paused") + "\n")
                    self._set_launch_params_readonly(True)
                    continue
                if item.strip() == _RING_VIZ_RESUMED_LINE:
                    self._paused = False
                    self.open_button.configure(state="disabled")
                    self.status.set(self.T("rings.status_running"))
                    self.console.append(self.T("rings.console_resumed") + "\n")
                    self._set_launch_params_readonly(False)
                    continue
                if item.startswith(_HUD_STATE_PREFIX):
                    self._apply_hud_state(item[len(_HUD_STATE_PREFIX):])
                    continue
                self.console.append(item)
        except queue.Empty:
            pass
        self.after(150, self._poll_queue)

    def _apply_hud_state(self, raw_json):
        """Parses one renderer.py emit_hud_state() JSON payload and
        replaces (never appends to) self.hud_var's content. Malformed/
        truncated JSON is silently skipped rather than raised -- a stray
        parse hiccup on one tick's line must never crash the GUI thread;
        the next tick's line (a few dozen ms later during playback) simply
        supersedes it."""
        try:
            data = json.loads(raw_json)
        except (ValueError, TypeError):
            return
        n = data.get("n", 0)
        # [ADDED 2026-09-10] Track the current N for the Start/Resume button
        # -- see __init__'s own doc-comment on _last_hud_n and _poll_queue's
        # __exit__ branch, which is what actually reads this back into the
        # N field once the process ends.
        self._last_hud_n = n
        count = data.get("count", 0)
        rebuild_ms = data.get("rebuild_ms", 0.0)
        running = data.get("running", False)
        tempo_ms = data.get("tempo_ms", 0)
        lines = data.get("lines", [])
        status = (self.T("rings.hud_status_running", tempo=tempo_ms) if running
                  else self.T("rings.hud_status_stopped"))
        header = self.T("rings.hud_header", n=f"{n:,}", count=f"{count:,}",
                         rebuild_ms=f"{rebuild_ms:.1f}", status=status)
        body = "\n".join(str(line) for line in lines)
        self.hud_var.set(header + ("\n" + body if body else ""))
