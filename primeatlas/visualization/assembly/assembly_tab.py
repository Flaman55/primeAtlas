"""
assembly_tab.py -- AssemblyTab(VizTabBase), the Visualization > Assembly sub-tab. Launches
the shared GPU renderer (primeatlas/visualization/shared/renderer.py) in its own window
and process with --viz-mode assembly --source none: the animation computes everything
itself. With an empty storage, Start still offers to generate a range first (as the
Rings and Tree sub-tabs do); Cancel starts the animation without numbers
(--assembly-bare). Launching, the console, the HUD panel and live pause/resume come from
VizTabBase; this tab builds its form and the argv.
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


def build_assembly_argv(n, python_executable=None, depth=None, frames=None, tempo_ms=None, lane_dots=None,
                        detail_cells=None, max_labels=None, max_lanes=None, node_size=None, cell_size=None,
                        hud_font_size=None, label_font_size=None, colors="", bare=False,
                        pipe_stdin_commands=False):
    """Argv launching renderer.py (as a plain script path) in assembly mode with the grid
    values labelled from `n`. Every None/empty optional value is omitted, so renderer.py's
    own defaults apply; values are forwarded as given (renderer.py validates them)."""
    exe = python_executable or sys.executable
    argv = [exe, RENDERER_SCRIPT, "--source", "none", "--upto", str(n), "--viz-mode", "assembly"]
    for flag, value in (("--assembly-depth", depth), ("--assembly-frames", frames), ("--tempo-ms", tempo_ms),
                        ("--assembly-lane-dots", lane_dots), ("--assembly-detail-cells", detail_cells),
                        ("--assembly-max-labels", max_labels), ("--assembly-max-lanes", max_lanes),
                        ("--assembly-node-size", node_size), ("--assembly-cell-size", cell_size),
                        ("--hud-font-size", hud_font_size), ("--assembly-label-font-size", label_font_size)):
        if value is not None:
            argv += [flag, str(value)]
    if colors:
        argv += ["--assembly-colors", colors]
    if bare:
        argv += ["--assembly-bare"]
    if pipe_stdin_commands:
        argv += ["--pipe-stdin-commands"]
    return argv


# (attribute, locale key, saved-params key, first-run default, section) for every plain
# numeric entry, in form order; parsed with _eval_quick_number (ints) or float().
_INT_FIELDS = (
    ("depth_entry", "depth_label", "depth", "6", "animation"),
    ("frames_entry", "frames_label", "frames", "12", "animation"),
    ("tempo_ms_entry", "tempo_label", "tempo_ms", "60", "animation"),
    ("lane_dots_entry", "lane_dots_label", "lane_dots", "48", "animation"),
    ("detail_cells_entry", "detail_cells_label", "detail_cells", "2310", "animation"),
    ("max_labels_entry", "max_labels_label", "max_labels", "3000", "animation"),
    ("max_lanes_entry", "max_lanes_label", "max_lanes", "200000", "animation"),
    ("hud_font_size_entry", "hud_font_size_label", "hud_font_size", "35", "appearance"),
    ("label_font_size_entry", "label_font_size_label", "label_font_size", "35", "appearance"),
)
_FLOAT_FIELDS = (
    ("node_size_entry", "node_size_label", "node_size", "15", "appearance"),
    ("cell_size_entry", "cell_size_label", "cell_size", "12", "appearance"),
)


class AssemblyTab(VizTabBase):
    LOCALE_PREFIX = "assembly"

    def __init__(self, parent, get_portal_folder, status_var, translator, totals_progress,
                 app_settings=None, offer_generate_storage=None):
        super().__init__(parent, get_portal_folder, status_var, translator, totals_progress,
                         app_settings)
        self._offer_generate_storage = offer_generate_storage
        self._build_ui()

    def _build_ui(self):
        saved = (self._app_settings.assembly_viz_params if self._app_settings else None) or {}
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

        ttk.Label(container, text=self._tk("intro"), wraplength=760, justify="left").pack(anchor="w", pady=(0, 10))

        sections = {
            "animation": ttk.LabelFrame(container, text=self._tk("section_animation")),
            "appearance": ttk.LabelFrame(container, text=self._tk("section_appearance")),
        }
        for frame in sections.values():
            frame.pack(fill="x", pady=(0, 8))
        n_row = ttk.Frame(sections["animation"])
        n_row.pack(fill="x", padx=8, pady=(6, 4))
        ttk.Label(n_row, text=self._tk("field_n")).pack(side="left")
        self.n_entry = ttk.Entry(n_row, width=28)
        self.n_entry.insert(0, saved.get("n", "0"))
        self.n_entry.pack(side="left", padx=(6, 0))

        for attr, label_key, saved_key, default, section in _INT_FIELDS + _FLOAT_FIELDS:
            row = ttk.Frame(sections[section])
            row.pack(fill="x", padx=8, pady=(0, 4))
            ttk.Label(row, text=self._tk(label_key)).pack(side="left")
            entry = ttk.Entry(row, width=12)
            entry.insert(0, saved.get(saved_key, default))
            entry.pack(side="left", padx=(6, 0))
            setattr(self, attr, entry)

        colors_row = ttk.Frame(sections["appearance"])
        colors_row.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(colors_row, text=self._tk("colors_label")).pack(side="left")
        self.colors_entry = ttk.Entry(colors_row, width=40)
        self.colors_entry.insert(0, saved.get("colors", ""))
        self.colors_entry.pack(side="left", padx=(6, 0))

        ttk.Label(container, text=self._tk("controls_hint"), wraplength=760, justify="left",
                  foreground="#888888").pack(anchor="w", pady=(0, 8))

        hud_frame = ttk.LabelFrame(container, text=self._tk("hud_panel_title"))
        hud_frame.pack(fill="x", pady=(0, 10))
        self.hud_var = tk.StringVar(value=self._tk("hud_panel_placeholder"))
        ttk.Label(hud_frame, textvariable=self.hud_var, justify="left", anchor="w",
                  font=("TkFixedFont",)).pack(fill="x", padx=8, pady=6)

        self.console = GenerationConsole(container, self.T, height=14, window_title=self._tk("console_title"))
        self._register_scroll_exclude(self.console.text.frame)

        self._launch_param_entries = [self.n_entry, self.colors_entry] + [
            getattr(self, attr) for attr, *_ in _INT_FIELDS + _FLOAT_FIELDS]

    def _set_launch_params_readonly(self, readonly):
        state = "disabled" if readonly else "normal"
        for widget in self._launch_param_entries:
            widget.configure(state=state)

    def _restore_last_n(self, n):
        """The HUD N is the animation's period, not a launch value: the N field (the
        label base) keeps what was entered."""

    def _on_open(self, skip_storage_check=False, bare=False):
        if self._resume_if_paused():
            return
        raw_n = self.n_entry.get().strip()
        n = _eval_quick_number(raw_n) if raw_n else None
        if n is None or n < 0:
            messagebox.showerror(self._tk("error_dialog_title"), self._tk("error_n_invalid"))
            return
        if (not skip_storage_check and self._offer_generate_storage is not None
                and find_highest_populated_floor(self._get_portal_folder()) is None):
            self._offer_storage_fill("", raw_n, self._on_open,
                                     on_cancel=lambda: self._on_open(skip_storage_check=True, bare=True))
            return

        values = {}
        raw = {"n": raw_n}
        for attr, _label, saved_key, _default, _section in _INT_FIELDS:
            text = getattr(self, attr).get().strip()
            raw[saved_key] = text
            parsed = _eval_quick_number(text) if text else None
            values[saved_key] = parsed if isinstance(parsed, int) else None
        for attr, _label, saved_key, _default, _section in _FLOAT_FIELDS:
            text = getattr(self, attr).get().strip()
            raw[saved_key] = text
            try:
                values[saved_key] = float(text) if text else None
            except ValueError:
                values[saved_key] = None
        colors = self.colors_entry.get().strip()
        raw["colors"] = colors

        argv = build_assembly_argv(n, depth=values["depth"], frames=values["frames"], tempo_ms=values["tempo_ms"],
                                   lane_dots=values["lane_dots"], detail_cells=values["detail_cells"],
                                   max_labels=values["max_labels"], max_lanes=values["max_lanes"],
                                   node_size=values["node_size"], cell_size=values["cell_size"],
                                   hud_font_size=values["hud_font_size"],
                                   label_font_size=values["label_font_size"], colors=colors, bare=bare,
                                   pipe_stdin_commands=True)
        if self._app_settings is not None:
            self._app_settings.set_assembly_viz_params(raw)
        self._launch_renderer(argv, n, LocalLoggedRunner)
