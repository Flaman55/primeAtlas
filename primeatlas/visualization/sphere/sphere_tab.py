"""
sphere_tab.py -- SphereTab(VizTabBase), the Visualization > Sphere sub-tab. It launches
the shared GPU renderer (primeatlas/visualization/shared/renderer.py) in its own window
and process with --source none --viz-mode sphere: the first K primes as rings on a sphere
through one common node (see sphere_mode.py). The storage folder goes along as
--portal-folder; the renderer reads it as a list of primes around N (primality of N, the
jumps to the previous/next prime).

The visualization-mode selector lists the sphere's modes (rings). With an empty storage,
Start offers to generate a range first (as the Rings sub-tab does); Cancel starts the
sphere without a storage (primality unknown, Left/Right plain steps). Launching, the
console, the HUD panel and live pause/resume come from VizTabBase; this tab builds its
form and the argv.
"""
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox

from ...generation.generation import LocalLoggedRunner, _eval_quick_number, find_highest_populated_floor
from ...generation.generation_console import GenerationConsole
from ..shared.viz_tab_base import VizTabBase

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
RENDERER_SCRIPT = os.path.join(os.path.dirname(_THIS_DIR), "shared", "renderer.py")

MODE_RINGS = "rings"
MODES = (MODE_RINGS,)


def build_sphere_argv(n, python_executable=None, portal_folder=None, rings=None, frames=None, tempo_ms=None,
                      spin=None, n_step=None, chunk=None, segments=None, max_curves=None, point_size=None,
                      node_size=None, hud_font_size=None, label_font_size=None, pipe_stdin_commands=False):
    """Argv launching renderer.py (as a plain script path) in sphere mode at N = `n`.
    Every None optional value is omitted, so renderer.py's own defaults apply; values are
    forwarded as given (renderer.py validates them)."""
    exe = python_executable or sys.executable
    argv = [exe, RENDERER_SCRIPT, "--source", "none", "--upto", str(n), "--viz-mode", "sphere"]
    if portal_folder:
        argv += ["--portal-folder", str(portal_folder)]
    for flag, value in (("--sphere-rings", rings), ("--sphere-frames", frames), ("--tempo-ms", tempo_ms),
                        ("--sphere-spin", spin), ("--n-step", n_step), ("--sphere-chunk", chunk),
                        ("--sphere-segments", segments), ("--sphere-max-curves", max_curves),
                        ("--sphere-point-size", point_size), ("--sphere-node-size", node_size),
                        ("--hud-font-size", hud_font_size), ("--sphere-label-font-size", label_font_size)):
        if value is not None:
            argv += [flag, str(value)]
    if pipe_stdin_commands:
        argv += ["--pipe-stdin-commands"]
    return argv


# Entries: (attribute, label key, saved-params key, first-run default, kind), in form
# order; kind "int" is parsed with _eval_quick_number, "float" with float().
_FIELDS = (
    ("rings_entry", "rings_label", "rings", "200", "int"),
    ("frames_entry", "frames_label", "frames", "8", "int"),
    ("tempo_ms_entry", "tempo_label", "tempo_ms", "60", "int"),
    ("spin_entry", "spin_label", "spin", "0.4", "float"),
    ("n_step_entry", "n_step_label", "n_step", "1", "int"),
)
_PERFORMANCE_FIELDS = (
    ("chunk_entry", "chunk_label", "chunk", "100000", "int"),
    ("segments_entry", "segments_label", "segments", "96", "int"),
    ("max_curves_entry", "max_curves_label", "max_curves", "1000", "int"),
)
_APPEARANCE_FIELDS = (
    ("point_size_entry", "point_size_label", "point_size", "9", "float"),
    ("node_size_entry", "node_size_label", "node_size", "22", "float"),
    ("hud_font_size_entry", "hud_font_size_label", "hud_font_size", "35", "int"),
    ("label_font_size_entry", "label_font_size_label", "label_font_size", "35", "int"),
)
_ALL_FIELDS = _FIELDS + _PERFORMANCE_FIELDS + _APPEARANCE_FIELDS


def _parse(text, kind):
    if not text:
        return None
    if kind == "int":
        parsed = _eval_quick_number(text)
        return parsed if isinstance(parsed, int) else None
    try:
        return float(text)
    except ValueError:
        return None


class SphereTab(VizTabBase):
    LOCALE_PREFIX = "sphere"

    def __init__(self, parent, get_portal_folder, status_var, translator, totals_progress,
                 app_settings=None, offer_generate_storage=None):
        super().__init__(parent, get_portal_folder, status_var, translator, totals_progress,
                         app_settings)
        self._offer_generate_storage = offer_generate_storage
        self._build_ui()

    def _add_entries(self, parent, fields, saved):
        for attr, label_key, saved_key, default, _kind in fields:
            row = ttk.Frame(parent)
            row.pack(fill="x", padx=8, pady=(0, 4))
            ttk.Label(row, text=self._tk(label_key)).pack(side="left")
            entry = ttk.Entry(row, width=12)
            entry.insert(0, saved.get(saved_key, default))
            entry.pack(side="left", padx=(6, 0))
            setattr(self, attr, entry)

    def _build_ui(self):
        saved = (self._app_settings.sphere_viz_params if self._app_settings else None) or {}
        scroll_body, self._register_scroll_exclude = self._build_scrollable_container(self)
        container = ttk.Frame(scroll_body)
        container.pack(fill="both", expand=True, padx=12, pady=12)

        button_row = ttk.Frame(container)
        button_row.pack(fill="x", pady=(0, 10))
        self.open_button = ttk.Button(button_row, text=self._tk("open_button"), command=self._on_open)
        self.open_button.pack(side="left")
        self.stop_button = ttk.Button(button_row, text=self._tk("stop_button"), command=self._on_reset,
                                      state="disabled")
        self.stop_button.pack(side="left", padx=(6, 0))

        mode_row = ttk.Frame(container)
        mode_row.pack(fill="x", pady=(0, 8))
        ttk.Label(mode_row, text=self._tk("mode_label")).pack(side="left")
        self._mode_choices = [(mode, self._tk(f"mode_{mode}")) for mode in MODES]
        saved_mode = saved.get("viz_mode", MODE_RINGS)
        self.mode_combo = ttk.Combobox(mode_row, state="readonly", width=28,
                                       values=[label for _mode, label in self._mode_choices])
        self.mode_combo.current(MODES.index(saved_mode if saved_mode in MODES else MODE_RINGS))
        self.mode_combo.pack(side="left", padx=(6, 0))

        ttk.Label(container, text=self._tk("intro"), wraplength=760, justify="left").pack(anchor="w", pady=(0, 10))

        common_frame = ttk.LabelFrame(container, text=self._tk("section_common"))
        common_frame.pack(fill="x", pady=(0, 8))
        n_row = ttk.Frame(common_frame)
        n_row.pack(fill="x", padx=8, pady=(6, 4))
        ttk.Label(n_row, text=self._tk("field_n")).pack(side="left")
        self.n_entry = ttk.Entry(n_row, width=28)
        self.n_entry.insert(0, saved.get("n", "1"))
        self.n_entry.pack(side="left", padx=(6, 0))
        self._add_entries(common_frame, _FIELDS, saved)

        performance_frame = ttk.LabelFrame(container, text=self._tk("section_performance"))
        performance_frame.pack(fill="x", pady=(0, 8))
        self._add_entries(performance_frame, _PERFORMANCE_FIELDS, saved)

        appearance_frame = ttk.LabelFrame(container, text=self._tk("section_appearance"))
        appearance_frame.pack(fill="x", pady=(0, 8))
        self._add_entries(appearance_frame, _APPEARANCE_FIELDS, saved)

        ttk.Label(container, text=self._tk("controls_hint"), wraplength=760, justify="left",
                  foreground="#888888").pack(anchor="w", pady=(0, 8))

        hud_frame = ttk.LabelFrame(container, text=self._tk("hud_panel_title"))
        hud_frame.pack(fill="x", pady=(0, 10))
        self.hud_var = tk.StringVar(value=self._tk("hud_panel_placeholder"))
        ttk.Label(hud_frame, textvariable=self.hud_var, justify="left", anchor="w",
                  font=("TkFixedFont",)).pack(fill="x", padx=8, pady=6)

        self.console = GenerationConsole(container, self.T, height=14, window_title=self._tk("console_title"))
        self._register_scroll_exclude(self.console.text.frame)

        self._launch_param_entries = [self.n_entry] + [getattr(self, attr) for attr, *_ in _ALL_FIELDS]

    def current_mode(self):
        return self._mode_choices[max(0, self.mode_combo.current())][0]

    # -- VizTabBase hooks -------------------------------------------------------

    def _set_launch_params_readonly(self, readonly):
        state = "disabled" if readonly else "normal"
        for widget in self._launch_param_entries:
            widget.configure(state=state)
        self.mode_combo.configure(state="disabled" if readonly else "readonly")

    def _restore_last_n(self, n):
        self.n_entry.delete(0, "end")
        self.n_entry.insert(0, str(n))

    def _on_open(self, skip_storage_check=False, with_storage=True):
        if self._resume_if_paused():
            return
        raw_n = self.n_entry.get().strip()
        n = _eval_quick_number(raw_n) if raw_n else None
        if n is None or n < 1:
            messagebox.showerror(self._tk("error_dialog_title"), self._tk("error_n_invalid"))
            return
        portal = self._get_portal_folder()
        if (not skip_storage_check and self._offer_generate_storage is not None
                and find_highest_populated_floor(portal) is None):
            self._offer_storage_fill("", raw_n, self._on_open,
                                     on_cancel=lambda: self._on_open(skip_storage_check=True, with_storage=False))
            return

        raw = dict((self._app_settings.sphere_viz_params if self._app_settings else None) or {})
        raw.update({"n": raw_n, "viz_mode": self.current_mode()})
        values = {}
        for attr, _label, saved_key, _default, kind in _ALL_FIELDS:
            text = getattr(self, attr).get().strip()
            raw[saved_key] = text
            values[saved_key] = _parse(text, kind)
        argv = build_sphere_argv(n, portal_folder=portal if with_storage else None, pipe_stdin_commands=True,
                                 **values)
        if self._app_settings is not None:
            self._app_settings.set_sphere_viz_params(raw)
        self._launch_renderer(argv, n, LocalLoggedRunner)
