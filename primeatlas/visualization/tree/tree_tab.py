"""
tree_tab.py -- TreeTab(VizTabBase), the Visualization > Tree sub-tab. It has two
visualization modes, both launching the shared GPU renderer
(primeatlas/visualization/shared/renderer.py) in its own window and process with
--source none (everything is computed, no storage needed):
  - tree: --viz-mode tree, the prime tree (build_tree_argv);
  - assembly: --viz-mode assembly, the wheel assembled level by level
    (assembly/assembly_argv.py's build_assembly_argv).
The common options (n, value-label cap, HUD and label font, node size, colors) are one set
of widgets for both modes; the mode-specific options are shown for the selected mode
only. Console and status texts come from the launched mode's locale namespace ("tree" or
"assembly").

With an empty storage, Start still offers to generate a range first (as the Rings
sub-tab does); Cancel starts the selected mode without numbers (--tree-bare /
--assembly-bare). Launching, the console, the HUD panel and live pause/resume come from
VizTabBase; this tab builds its form and the argv.
"""
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox

from ...generation.generation import LocalLoggedRunner, _eval_quick_number, find_highest_populated_floor
from ...generation.generation_console import GenerationConsole
from ..assembly.assembly_argv import build_assembly_argv
from ..shared.viz_tab_base import VizTabBase
from .highlight_layers import LAYERS
from .tree_layout import AXIS_AUTO, AXIS_KINDS, copy_budget
from .tree_mode import TREE_MAX_DEPTH

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
RENDERER_SCRIPT = os.path.join(os.path.dirname(_THIS_DIR), "shared", "renderer.py")

MODE_TREE = "tree"
MODE_ASSEMBLY = "assembly"
MODES = (MODE_TREE, MODE_ASSEMBLY)
# Foreground of the levels note when the copy cap cuts levels.
_CUT_NOTE_COLOR = "#d08000"


def build_tree_argv(n, python_executable=None, depth=None, branches=None, height=None, n_step=None,
                    tempo_ms=None, max_nodes=None, max_points=None, max_labels=None, multiples=None,
                    axis=None, colors="", highlight=(),
                    max_stripes=None, node_size=None, point_size=None, hud_font_size=None,
                    label_font_size=None, bare=False, pipe_stdin_commands=False):
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
    if bare:
        argv += ["--tree-bare"]
    if pipe_stdin_commands:
        argv += ["--pipe-stdin-commands"]
    return argv


# Entries: (attribute, label key, saved-params key, first-run default, kind), in form
# order; kind "int" is parsed with _eval_quick_number, "spin" too (a 1..TREE_MAX_DEPTH
# spinbox), "float" with float(), "text" is forwarded as typed. Common and tree labels are tree.* keys, assembly labels assembly.*.
_COMMON_FIELDS = (
    ("max_labels_entry", "max_labels_label", "max_labels", "3000", "int"),
    ("hud_font_size_entry", "hud_font_size_label", "hud_font_size", "35", "int"),
    ("label_font_size_entry", "label_font_size_label", "label_font_size", "35", "int"),
    ("node_size_entry", "node_size_label", "node_size", "15", "float"),
)
_TREE_FIELDS = (
    ("depth_entry", "depth_label", "depth", "8", "spin"),
    ("branches_entry", "branches_label", "drawn_branches", "3", "int"),
    ("n_step_entry", "n_step_label", "n_step", "1", "int"),
    ("tempo_ms_entry", "tempo_label", "tempo_ms", "120", "int"),
    ("max_nodes_entry", "max_nodes_label", "max_nodes", "100000", "int"),
    ("multiples_entry", "multiples_label", "multiples", "4", "int"),
    ("max_points_entry", "max_points_label", "max_points", "500000", "int"),
    ("height_entry", "height_label", "height", "1.5", "float"),
)
_TREE_APPEARANCE_FIELDS = (
    ("max_stripes_entry", "max_stripes_label", "max_stripes", "4", "int"),
    ("point_size_entry", "point_size_label", "point_size", "15", "float"),
)
_ASSEMBLY_FIELDS = (
    ("assembly_depth_entry", "depth_label", "assembly_depth", "6", "int"),
    ("frames_entry", "frames_label", "frames", "12", "int"),
    ("assembly_tempo_ms_entry", "tempo_label", "assembly_tempo_ms", "60", "int"),
    ("lane_dots_entry", "lane_dots_label", "lane_dots", "48", "int"),
    ("detail_cells_entry", "detail_cells_label", "detail_cells", "2310", "int"),
    ("max_lanes_entry", "max_lanes_label", "max_lanes", "200000", "int"),
    ("cell_size_entry", "cell_size_label", "cell_size", "12", "float"),
    ("cell_spacing_entry", "cell_spacing_label", "cell_spacing", "auto", "text"),
)


def _parse(text, kind):
    if not text:
        return None
    if kind in ("int", "spin"):
        parsed = _eval_quick_number(text)
        return parsed if isinstance(parsed, int) else None
    if kind == "float":
        try:
            return float(text)
        except ValueError:
            return None
    return text


class TreeTab(VizTabBase):
    LOCALE_PREFIX = "tree"

    def __init__(self, parent, get_portal_folder, status_var, translator, totals_progress,
                 app_settings=None, offer_generate_storage=None):
        super().__init__(parent, get_portal_folder, status_var, translator, totals_progress,
                         app_settings)
        self._offer_generate_storage = offer_generate_storage
        # The locale namespace of the launched (or launching) mode; see _tk.
        self._active_prefix = MODE_TREE
        self._launched_mode = MODE_TREE
        self._build_ui()

    def _tk(self, key, **kwargs):
        """Translation in the active mode's namespace ("tree" or "assembly")."""
        return self.T(f"{self._active_prefix}.{key}", **kwargs)

    def _ak(self, key, **kwargs):
        return self.T(f"assembly.{key}", **kwargs)

    def _add_entries(self, parent, fields, saved, label):
        for attr, label_key, saved_key, default, kind in fields:
            row = ttk.Frame(parent)
            row.pack(fill="x", padx=8, pady=(0, 4))
            ttk.Label(row, text=label(label_key)).pack(side="left")
            if kind == "spin":
                entry = ttk.Spinbox(row, from_=1, to=TREE_MAX_DEPTH, increment=1, width=10)
            else:
                entry = ttk.Entry(row, width=12)
            entry.insert(0, saved.get(saved_key, default))
            entry.pack(side="left", padx=(6, 0))
            setattr(self, attr, entry)

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

        mode_row = ttk.Frame(container)
        mode_row.pack(fill="x", pady=(0, 8))
        ttk.Label(mode_row, text=self._tk("mode_label")).pack(side="left")
        self._mode_choices = [(mode, self._tk(f"mode_{mode}")) for mode in MODES]
        saved_mode = saved.get("viz_mode", MODE_TREE)
        self.mode_combo = ttk.Combobox(mode_row, state="readonly", width=28,
                                       values=[label for _mode, label in self._mode_choices])
        self.mode_combo.current(MODES.index(saved_mode if saved_mode in MODES else MODE_TREE))
        self.mode_combo.pack(side="left", padx=(6, 0))
        self.mode_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_mode())

        self.intro_label = ttk.Label(container, wraplength=760, justify="left")
        self.intro_label.pack(anchor="w", pady=(0, 10))

        common_frame = ttk.LabelFrame(container, text=self._tk("section_common"))
        common_frame.pack(fill="x", pady=(0, 8))
        n_row = ttk.Frame(common_frame)
        n_row.pack(fill="x", padx=8, pady=(6, 4))
        self.n_label = ttk.Label(n_row)
        self.n_label.pack(side="left")
        self.n_entry = ttk.Entry(n_row, width=28)
        self.n_entry.insert(0, saved.get("n", "2"))
        self.n_entry.pack(side="left", padx=(6, 0))
        self._add_entries(common_frame, _COMMON_FIELDS, saved, self._tk)
        colors_row = ttk.Frame(common_frame)
        colors_row.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(colors_row, text=self._tk("colors_label")).pack(side="left")
        self.colors_entry = ttk.Entry(colors_row, width=40)
        self.colors_entry.insert(0, saved.get("colors", ""))
        self.colors_entry.pack(side="left", padx=(6, 0))

        self._options_holder = ttk.Frame(container)
        self._options_holder.pack(fill="x")

        # Tree-only options.
        self.tree_options = ttk.Frame(self._options_holder)
        tree_frame = ttk.LabelFrame(self.tree_options, text=self._tk("section_tree"))
        tree_frame.pack(fill="x", pady=(0, 8))
        axis_row = ttk.Frame(tree_frame)
        axis_row.pack(fill="x", padx=8, pady=(6, 4))
        ttk.Label(axis_row, text=self._tk("axis_label")).pack(side="left")
        self._axis_choices = [(kind, self._tk(f"axis_{kind}")) for kind in AXIS_KINDS]
        saved_axis = saved.get("axis", AXIS_AUTO)
        self.axis_combo = ttk.Combobox(axis_row, state="readonly", width=28,
                                       values=[label for _kind, label in self._axis_choices])
        self.axis_combo.current([kind for kind, _label in self._axis_choices].index(
            saved_axis if saved_axis in AXIS_KINDS else AXIS_AUTO))
        self.axis_combo.pack(side="left", padx=(6, 0))
        self._add_entries(tree_frame, _TREE_FIELDS, saved, self._tk)
        self.depth_info_var = tk.StringVar()
        self.depth_info_label = ttk.Label(tree_frame, textvariable=self.depth_info_var, wraplength=700,
                                          justify="left")
        self.depth_info_label.pack(anchor="w", padx=8, pady=(0, 6))
        self.depth_entry.configure(command=self._refresh_depth_info)
        for entry in (self.n_entry, self.depth_entry, self.branches_entry, self.max_nodes_entry):
            entry.bind("<KeyRelease>", lambda _e: self._refresh_depth_info(), add="+")
        appearance_frame = ttk.LabelFrame(self.tree_options, text=self._tk("section_appearance"))
        appearance_frame.pack(fill="x", pady=(0, 8))
        self._add_entries(appearance_frame, _TREE_APPEARANCE_FIELDS, saved, self._tk)
        highlight_frame = ttk.LabelFrame(self.tree_options, text=self._tk("section_highlight"))
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

        # Assembly-only options.
        self.assembly_options = ttk.Frame(self._options_holder)
        assembly_frame = ttk.LabelFrame(self.assembly_options, text=self._ak("section_animation"))
        assembly_frame.pack(fill="x", pady=(0, 8))
        self._add_entries(assembly_frame, _ASSEMBLY_FIELDS, saved, self._ak)

        self.hint_label = ttk.Label(container, wraplength=760, justify="left", foreground="#888888")
        self.hint_label.pack(anchor="w", pady=(0, 8))

        hud_frame = ttk.LabelFrame(container, text=self._tk("hud_panel_title"))
        hud_frame.pack(fill="x", pady=(0, 10))
        self.hud_var = tk.StringVar(value=self._tk("hud_panel_placeholder"))
        ttk.Label(hud_frame, textvariable=self.hud_var, justify="left", anchor="w",
                  font=("TkFixedFont",)).pack(fill="x", padx=8, pady=6)

        self.console = GenerationConsole(container, self.T, height=14, window_title=self._tk("console_title"))
        self._register_scroll_exclude(self.console.text.frame)

        self._launch_param_entries = [self.n_entry, self.colors_entry] + [
            getattr(self, attr) for attr, *_ in
            _COMMON_FIELDS + _TREE_FIELDS + _TREE_APPEARANCE_FIELDS + _ASSEMBLY_FIELDS]
        self._apply_mode()
        self._refresh_depth_info()

    def _refresh_depth_info(self):
        """The note under the tree options: the copies the levels need and, when the copy
        cap cuts them, how many levels will be drawn (empty for invalid input)."""
        values = []
        for entry in (self.n_entry, self.depth_entry, self.branches_entry, self.max_nodes_entry):
            text = entry.get().strip()
            value = _eval_quick_number(text) if text else None
            values.append(value if isinstance(value, int) else None)
        n, depth, branches, cap = values
        if None in values or n < 0 or not 1 <= depth <= TREE_MAX_DEPTH or branches < 1 or cap < 1:
            self.depth_info_var.set("")
            return
        needed, drawn = copy_budget(n, depth, branches, cap)
        if drawn < depth:
            self.depth_info_var.set(self._tk("depth_info_cut", needed=f"{needed:,}", cap=f"{cap:,}",
                                             drawn=drawn, depth=depth))
            self.depth_info_label.configure(foreground=_CUT_NOTE_COLOR)
        else:
            self.depth_info_var.set(self._tk("depth_info_full", needed=f"{needed:,}", depth=depth))
            self.depth_info_label.configure(foreground="")

    # -- mode -------------------------------------------------------------------

    def current_mode(self):
        return self._mode_choices[max(0, self.mode_combo.current())][0]

    def set_mode(self, mode):
        self.mode_combo.current(MODES.index(mode))
        self._apply_mode()

    def _apply_mode(self):
        """Shows the selected mode's own options, intro, n label and controls hint."""
        mode = self.current_mode()
        shown, hidden = ((self.tree_options, self.assembly_options) if mode == MODE_TREE
                         else (self.assembly_options, self.tree_options))
        hidden.pack_forget()
        shown.pack(fill="x")
        self.intro_label.configure(text=self.T(f"{mode}.intro"))
        self.n_label.configure(text=self.T(f"{mode}.field_n"))
        self.hint_label.configure(text=self.T(f"{mode}.controls_hint"))

    # -- VizTabBase hooks -------------------------------------------------------

    def _set_launch_params_readonly(self, readonly):
        state = "disabled" if readonly else "normal"
        for widget in self._launch_param_entries + self._highlight_checks:
            widget.configure(state=state)
        combo_state = "disabled" if readonly else "readonly"
        self.axis_combo.configure(state=combo_state)
        self.mode_combo.configure(state=combo_state)

    def _restore_last_n(self, n):
        """Tree mode: the HUD N is the start prime and goes back into the n field. The
        assembly's HUD N is its period, so the field keeps the label base entered."""
        if self._launched_mode != MODE_TREE:
            return
        self.n_entry.delete(0, "end")
        self.n_entry.insert(0, str(n))

    def _on_open(self, skip_storage_check=False, bare=False):
        if self._resume_if_paused():
            return
        mode = self.current_mode()
        self._active_prefix = mode
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

        raw = dict((self._app_settings.tree_viz_params if self._app_settings else None) or {})
        raw.update({"n": raw_n, "viz_mode": mode})
        values = {}
        for attr, _label, saved_key, _default, kind in (
                _COMMON_FIELDS + _TREE_FIELDS + _TREE_APPEARANCE_FIELDS + _ASSEMBLY_FIELDS):
            text = getattr(self, attr).get().strip()
            raw[saved_key] = text
            values[saved_key] = _parse(text, kind)
        colors = self.colors_entry.get().strip()
        raw["colors"] = colors
        axis = self._axis_choices[max(0, self.axis_combo.current())][0]
        raw["axis"] = axis
        highlight = [name for name, var in self.highlight_vars.items() if var.get()]
        for name, var in self.highlight_vars.items():
            raw[f"highlight_{name}"] = var.get()

        if mode == MODE_TREE:
            argv = build_tree_argv(n, depth=values["depth"], branches=values["drawn_branches"],
                                   height=values["height"], n_step=values["n_step"], tempo_ms=values["tempo_ms"],
                                   max_nodes=values["max_nodes"], max_points=values["max_points"],
                                   max_labels=values["max_labels"], multiples=values["multiples"], axis=axis,
                                   colors=colors, highlight=highlight, max_stripes=values["max_stripes"],
                                   node_size=values["node_size"], point_size=values["point_size"],
                                   hud_font_size=values["hud_font_size"],
                                   label_font_size=values["label_font_size"], bare=bare,
                                   pipe_stdin_commands=True)
        else:
            argv = build_assembly_argv(n, depth=values["assembly_depth"], frames=values["frames"],
                                       tempo_ms=values["assembly_tempo_ms"], lane_dots=values["lane_dots"],
                                       detail_cells=values["detail_cells"], max_labels=values["max_labels"],
                                       max_lanes=values["max_lanes"], node_size=values["node_size"],
                                       cell_size=values["cell_size"], hud_font_size=values["hud_font_size"],
                                       label_font_size=values["label_font_size"], colors=colors,
                                       cell_spacing=values["cell_spacing"] or "", bare=bare,
                                       pipe_stdin_commands=True)
        if self._app_settings is not None:
            self._app_settings.set_tree_viz_params(raw)
        self._launched_mode = mode
        self._launch_renderer(argv, n, LocalLoggedRunner)
