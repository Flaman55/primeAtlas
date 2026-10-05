"""
tree_tab.py -- TreeTab(VizTabBase), the Visualization > Tree sub-tab. Launches the shared
GPU renderer (primeatlas/visualization/shared/renderer.py) in its own window and process
with --viz-mode tree --source none: the prime tree computes every value itself, so
it needs no storage folder and no loaded primes. With an empty storage, Start still
offers to generate a range first (as the Rings sub-tab does); Cancel starts the tree
without it. Launching, the console, the HUD panel
and live pause/resume come from VizTabBase; this tab builds its form and the argv.
"""
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox

from ...generation.generation import LocalLoggedRunner, _eval_quick_number, find_highest_populated_floor
from ...generation.generation_console import GenerationConsole
from ..shared.viz_tab_base import VizTabBase
from .highlight_layers import LAYERS
from .tree_layout import AXIS_AUTO, AXIS_KINDS

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
RENDERER_SCRIPT = os.path.join(os.path.dirname(_THIS_DIR), "shared", "renderer.py")


def build_tree_argv(n, python_executable=None, depth=None, branches=None, height=None, n_step=None,
                    tempo_ms=None, max_nodes=None, max_points=None, max_labels=None, multiples=None,
                    axis=None, colors="", highlight=(),
                    max_stripes=None, node_size=None, point_size=None, hud_font_size=None,
                    label_font_size=None, pipe_stdin_commands=False):
    """Argv launching renderer.py (as a plain script path, see its module docstring)
    in tree mode at window start `n`. Every None/empty optional value is omitted, so
    renderer.py's own defaults apply; values are forwarded as given (renderer.py
    validates them)."""
    exe = python_executable or sys.executable
    argv = [exe, RENDERER_SCRIPT, "--source", "none", "--upto", str(n), "--viz-mode", "tree"]
    for flag, value in (("--tree-depth", depth), ("--tree-branches", branches), ("--tree-height", height),
                        ("--n-step", n_step), ("--tempo-ms", tempo_ms), ("--tree-max-nodes", max_nodes),
                        ("--tree-max-points", max_points), ("--tree-multiples", multiples), ("--tree-axis", axis),
                        ("--tree-max-labels", max_labels), ("--tree-max-stripes", max_stripes),
                        ("--tree-node-size", node_size), ("--point-size", point_size),
                        ("--hud-font-size", hud_font_size), ("--tree-label-font-size", label_font_size)):
        if value is not None:
            argv += [flag, str(value)]
    if colors:
        argv += ["--tree-colors", colors]
    highlight = list(highlight)
    if highlight:
        argv += ["--tree-highlight", ",".join(highlight)]
    if pipe_stdin_commands:
        argv += ["--pipe-stdin-commands"]
    return argv


# (attribute, locale key, saved-params key, first-run default) for every plain numeric
# entry, in form order; parsed with _eval_quick_number (ints) or float().
_INT_FIELDS = (
    ("depth_entry", "depth_label", "depth", "8"),
    ("branches_entry", "branches_label", "drawn_branches", "3"),
    ("n_step_entry", "n_step_label", "n_step", "1"),
    ("tempo_ms_entry", "tempo_label", "tempo_ms", "120"),
    ("max_nodes_entry", "max_nodes_label", "max_nodes", "2000"),
    ("multiples_entry", "multiples_label", "multiples", "4"),
    ("max_points_entry", "max_points_label", "max_points", "500000"),
    ("max_labels_entry", "max_labels_label", "max_labels", "3000"),
    ("max_stripes_entry", "max_stripes_label", "max_stripes", "4"),
    ("hud_font_size_entry", "hud_font_size_label", "hud_font_size", "35"),
    ("label_font_size_entry", "label_font_size_label", "label_font_size", "35"),
)
_FLOAT_FIELDS = (
    ("height_entry", "height_label", "height", "1.5"),
    ("node_size_entry", "node_size_label", "node_size", "15"),
    ("point_size_entry", "point_size_label", "point_size", "15"),
)


class TreeTab(VizTabBase):
    LOCALE_PREFIX = "tree"

    def __init__(self, parent, get_portal_folder, status_var, translator, totals_progress,
                 app_settings=None, offer_generate_storage=None):
        super().__init__(parent, get_portal_folder, status_var, translator, totals_progress,
                         app_settings)
        self._offer_generate_storage = offer_generate_storage
        self._build_ui()

    def _build_ui(self):
        saved = (self._app_settings.tree_viz_params if self._app_settings else None) or {}
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

        tree_frame = ttk.LabelFrame(container, text=self._tk("section_tree"))
        tree_frame.pack(fill="x", pady=(0, 8))
        n_row = ttk.Frame(tree_frame)
        n_row.pack(fill="x", padx=8, pady=(6, 4))
        ttk.Label(n_row, text=self._tk("field_n")).pack(side="left")
        self.n_entry = ttk.Entry(n_row, width=28)
        self.n_entry.insert(0, saved.get("n", "2"))
        self.n_entry.pack(side="left", padx=(6, 0))

        axis_row = ttk.Frame(tree_frame)
        axis_row.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Label(axis_row, text=self._tk("axis_label")).pack(side="left")
        self._axis_choices = [(kind, self._tk(f"axis_{kind}")) for kind in AXIS_KINDS]
        saved_axis = saved.get("axis", AXIS_AUTO)
        self.axis_combo = ttk.Combobox(axis_row, state="readonly", width=28,
                                       values=[label for _kind, label in self._axis_choices])
        self.axis_combo.current([kind for kind, _label in self._axis_choices].index(
            saved_axis if saved_axis in AXIS_KINDS else AXIS_AUTO))
        self.axis_combo.pack(side="left", padx=(6, 0))

        appearance_frame = ttk.LabelFrame(container, text=self._tk("section_appearance"))
        appearance_frame.pack(fill="x", pady=(0, 8))
        tree_keys = {"depth", "drawn_branches", "height", "n_step", "tempo_ms", "max_nodes", "multiples",
                     "max_points", "max_labels"}
        for attr, label_key, saved_key, default in _INT_FIELDS + _FLOAT_FIELDS:
            parent = tree_frame if saved_key in tree_keys else appearance_frame
            row = ttk.Frame(parent)
            row.pack(fill="x", padx=8, pady=(0, 4))
            ttk.Label(row, text=self._tk(label_key)).pack(side="left")
            entry = ttk.Entry(row, width=12)
            entry.insert(0, saved.get(saved_key, default))
            entry.pack(side="left", padx=(6, 0))
            setattr(self, attr, entry)

        colors_row = ttk.Frame(appearance_frame)
        colors_row.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(colors_row, text=self._tk("colors_label")).pack(side="left")
        self.colors_entry = ttk.Entry(colors_row, width=40)
        self.colors_entry.insert(0, saved.get("colors", ""))
        self.colors_entry.pack(side="left", padx=(6, 0))

        highlight_frame = ttk.LabelFrame(container, text=self._tk("section_highlight"))
        highlight_frame.pack(fill="x", pady=(0, 8))
        highlight_row = ttk.Frame(highlight_frame)
        highlight_row.pack(fill="x", padx=8, pady=6)
        self.highlight_vars = {}
        self._highlight_checks = []
        for name in LAYERS:
            var = tk.BooleanVar(value=saved.get(f"highlight_{name}", False))
            check = ttk.Checkbutton(highlight_row, text=self._tk(f"highlight_{name}"), variable=var)
            check.pack(side="left", padx=(0, 12))
            self.highlight_vars[name] = var
            self._highlight_checks.append(check)

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
        for widget in self._launch_param_entries + self._highlight_checks:
            widget.configure(state=state)
        self.axis_combo.configure(state="disabled" if readonly else "readonly")

    def _restore_last_n(self, n):
        self.n_entry.delete(0, "end")
        self.n_entry.insert(0, str(n))

    def _on_open(self, skip_storage_check=False):
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
                                     on_cancel=lambda: self._on_open(skip_storage_check=True))
            return

        values = {}
        raw = {"n": raw_n}
        for attr, _label, saved_key, _default in _INT_FIELDS:
            text = getattr(self, attr).get().strip()
            raw[saved_key] = text
            parsed = _eval_quick_number(text) if text else None
            values[saved_key] = parsed if isinstance(parsed, int) else None
        for attr, _label, saved_key, _default in _FLOAT_FIELDS:
            text = getattr(self, attr).get().strip()
            raw[saved_key] = text
            try:
                values[saved_key] = float(text) if text else None
            except ValueError:
                values[saved_key] = None
        colors = self.colors_entry.get().strip()
        raw["colors"] = colors
        axis = self._axis_choices[max(0, self.axis_combo.current())][0]
        raw["axis"] = axis
        highlight = [name for name, var in self.highlight_vars.items() if var.get()]
        for name, var in self.highlight_vars.items():
            raw[f"highlight_{name}"] = var.get()

        argv = build_tree_argv(n, depth=values["depth"], branches=values["drawn_branches"],
                               height=values["height"], n_step=values["n_step"], tempo_ms=values["tempo_ms"],
                               max_nodes=values["max_nodes"], max_points=values["max_points"],
                               max_labels=values["max_labels"], multiples=values["multiples"], axis=axis,
                               colors=colors, highlight=highlight, max_stripes=values["max_stripes"],
                               node_size=values["node_size"], point_size=values["point_size"],
                               hud_font_size=values["hud_font_size"],
                               label_font_size=values["label_font_size"], pipe_stdin_commands=True)
        if self._app_settings is not None:
            self._app_settings.set_tree_viz_params(raw)
        self._launch_renderer(argv, n, LocalLoggedRunner)
