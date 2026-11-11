"""Engine selector and knob fields of the Generation tab's pipeline form.

One readonly Combobox picks the sieve engine (engine_options.ENGINES), with the engine's code
version next to it (engine_options.ENGINE_VERSIONS) and an InfoTip. Below it, the knobs of
the selected engine only (engine_options.engine_knob_keys()), two per row in the form's
label/entry column pairs, each entry followed by an InfoTip saying how the knob affects the
run (a checkbox for engine_options.CHECKBOX_KNOBS, with a link-styled hint label after it
that another section fills and binds: knob_hint_vars, knob_hint_labels; set_knob_lock()
greys it out with the reason in a tooltip on hover, knob_lock_tips); switching the engine hides the old engine's fields (they keep their values and are
disabled) and shows the new ones. For v5 and v6 a second Combobox picks the knob profile
(engine_presets.py), one per engine: picking old, new or mid fills that engine's profile
fields (auto shows the set for the run width last given to set_windows(), new while none
is known); typing in one of those fields switches the profile to custom. Parsing, defaults, profile values and
the launch env live in engine_options.py and engine_presets.py; this module only owns the
widgets.
"""
import tkinter as tk
from tkinter import ttk

from ..core.info_tip import InfoTip
from . import engine_options, engine_presets
from .generation_settings import remember_generation_field

_KNOB_LABEL_KEYS = {key: f"gen.field_{key}" for key in engine_options.KNOB_KEYS}


class EngineFields:
    """Grids the selector at `row` and the selected engine's knobs on the rows below it, two
    per row, in the same label/entry column pairs the pipeline form uses (columns 0-3)."""

    def __init__(self, form, T, loop_settings, row):
        self._row = row
        self.engine_var = tk.StringVar(
            value=engine_options.normalize_engine(loop_settings.get("engine")))
        ttk.Label(form, text=T("gen.field_engine")).grid(
            row=row, column=0, sticky="w", padx=(0, 4), pady=(6, 2))
        selector = ttk.Frame(form)
        selector.grid(row=row, column=1, columnspan=3, sticky="w", pady=(6, 2))
        ttk.Combobox(selector, textvariable=self.engine_var, values=engine_options.ENGINES,
                     state="readonly", width=8).pack(side="left")
        remember_generation_field("loop", "engine", self.engine_var)
        self.version_var = tk.StringVar()
        ttk.Label(selector, textvariable=self.version_var).pack(side="left", padx=(6, 0))
        self.engine_info = InfoTip(selector, lambda: T("gen.info_engine"))
        self.engine_info.label.pack(side="left", padx=(4, 0))

        self._T = T
        self.preset_vars = {
            engine: tk.StringVar(value=engine_presets.normalize_preset(
                loop_settings.get(engine_presets.preset_key(engine))))
            for engine in engine_presets.PRESET_ENGINES}
        for engine, var in self.preset_vars.items():
            remember_generation_field("loop", engine_presets.preset_key(engine), var)
        self._preset_frame = ttk.Frame(selector)
        ttk.Label(self._preset_frame, text=T("gen.field_preset")).pack(side="left", padx=(16, 4))
        self._preset_labels = {name: T(f"gen.preset_{name}") for name in engine_presets.PRESETS}
        self.preset_display = tk.StringVar()
        self.preset_box = ttk.Combobox(
            self._preset_frame, textvariable=self.preset_display, state="readonly", width=12,
            values=[self._preset_labels[name] for name in engine_presets.PRESETS])
        self.preset_box.pack(side="left")
        self.preset_box.bind("<<ComboboxSelected>>", lambda _e: self._on_preset_picked())
        self.preset_info = InfoTip(self._preset_frame, lambda: T("gen.info_preset"))
        self.preset_info.label.pack(side="left", padx=(4, 0))
        self._filling = False
        self._windows = None

        self.knob_vars = {}
        self.knob_entries = {}
        self.knob_infos = {}
        self.knob_hint_vars = {}
        self.knob_hint_labels = {}
        self.knob_lock_tips = {}
        self._knob_locks = {}
        self._knob_widgets = {}
        for key in engine_options.KNOB_KEYS:
            label = ttk.Label(form, text=T(_KNOB_LABEL_KEYS[key]))
            cell = ttk.Frame(form)
            default = engine_options.DEFAULT_KNOBS[key]
            var = tk.StringVar(value=str(loop_settings.get(key, default)))
            if key in engine_options.CHECKBOX_KNOBS:
                entry = ttk.Checkbutton(cell, variable=var, onvalue="1", offvalue="0")
            else:
                entry = ttk.Entry(cell, textvariable=var, width=10)
            entry.pack(side="left")
            info = InfoTip(cell, lambda key=key: T(f"gen.info_{key}"))
            info.label.pack(side="left", padx=(4, 0))
            if key in engine_options.CHECKBOX_KNOBS:
                self.knob_hint_vars[key] = tk.StringVar()
                self.knob_hint_labels[key] = ttk.Label(
                    cell, textvariable=self.knob_hint_vars[key], style="Link.TLabel",
                    cursor="hand2")
                self.knob_hint_labels[key].pack(side="left", padx=(6, 0))
                self.knob_lock_tips[key] = InfoTip(
                    cell, lambda key=key: self._knob_locks.get(key) or "", anchor=entry)
            self.knob_vars[key] = var
            remember_generation_field("loop", key, var)
            self.knob_entries[key] = entry
            self.knob_infos[key] = info
            self._knob_widgets[key] = (label, cell)
        self._listeners = []
        for engine in engine_presets.PRESET_ENGINES:
            self._fill_preset(engine)
            for key in engine_presets.profile_knob_keys(engine):
                self.knob_vars[key].trace_add(
                    "write", lambda *_, engine=engine: self._on_profile_knob_typed(engine))
        self.engine_var.trace_add("write", lambda *_: self._on_engine_changed())
        self._sync_knob_state()

    def engine(self):
        return engine_options.normalize_engine(self.engine_var.get())

    def on_engine_change(self, callback):
        self._listeners.append(callback)

    def choice(self, windows=None):
        """(EngineChoice, None), or (None, key) naming the first invalid knob field of the
        selected engine; another engine's knobs never block a run. The engine's profile
        sets its profile knobs, auto by `windows` per run (None = not known yet)."""
        engine = self.engine()
        own = engine_options.engine_knob_keys(engine)
        raw = {key: var.get() for key, var in self.knob_vars.items()}
        for key in own:
            _knobs, bad = engine_options.parse_knobs({key: raw[key]})
            if bad is not None:
                return None, bad
        return engine_options.resolve(self.settings(), windows), None

    def choice_for_windows(self, windows):
        """The EngineChoice a run of `windows` windows launches with, None while a knob field
        of the selected engine is invalid."""
        return self.choice(windows)[0]

    def settings(self):
        """Values to persist in the Generation settings' "loop" section."""
        values = {key: var.get().strip() for key, var in self.knob_vars.items()}
        values["engine"] = self.engine()
        for engine, var in self.preset_vars.items():
            values[engine_presets.preset_key(engine)] = var.get()
        return values

    def preset(self, engine=None):
        """The knob profile of `engine` (default: the selected one), None without profiles."""
        var = self.preset_vars.get(engine or self.engine())
        return var.get() if var is not None else None

    def set_preset(self, name, engine=None):
        """Selects profile `name` for `engine` (default: the selected one) and fills its
        profile fields."""
        engine = engine or self.engine()
        self.preset_vars[engine].set(engine_presets.normalize_preset(name))
        self._fill_preset(engine)
        self._sync_preset_box()

    def set_bucket_mb(self, bucket_mb, engine=None):
        """Fills the bucket field of `engine` (default: the selected one), if it has one."""
        key = engine_options.bucket_knob(engine or self.engine())
        if key is not None:
            self.knob_vars[key].set(str(bucket_mb))

    def set_windows(self, windows):
        """Sets the run width (windows per run) Auto sizes the profile fields for and refills
        every engine on Auto; a blank or non-positive value changes nothing."""
        text = str(windows).strip()
        if not text.isdigit() or int(text) <= 0:
            return
        self._windows = int(text)
        for engine, var in self.preset_vars.items():
            if var.get() == engine_presets.PRESET_AUTO:
                self._fill_preset(engine)

    def _fill_preset(self, engine):
        values = engine_presets.preset_knobs(engine, self.preset_vars[engine].get(),
                                             self._windows)
        if values is None:
            return
        self._filling = True
        try:
            for key, value in values.items():
                self.knob_vars[key].set(str(value))
        finally:
            self._filling = False

    def _on_profile_knob_typed(self, engine):
        if not self._filling and self.preset_vars[engine].get() != engine_presets.PRESET_CUSTOM:
            self.preset_vars[engine].set(engine_presets.PRESET_CUSTOM)
            self._sync_preset_box()

    def _on_preset_picked(self):
        by_label = {label: name for name, label in self._preset_labels.items()}
        name = by_label.get(self.preset_display.get())
        if name is not None and self.engine() in self.preset_vars:
            self.set_preset(name)

    def _sync_preset_box(self):
        var = self.preset_vars.get(self.engine())
        if var is None:
            self._preset_frame.pack_forget()
            return
        self._preset_frame.pack(side="left")
        self.preset_display.set(self._preset_labels[var.get()])

    def set_knob_lock(self, key, reason):
        """Greys `key`'s field out while `reason` (a text, shown on hover) is set; None
        enables it again. The field keeps its value either way."""
        self._knob_locks[key] = reason
        self._sync_knob_state()

    def _sync_knob_state(self):
        engine = self.engine()
        own = engine_options.engine_knob_keys(engine)
        self.version_var.set(engine_options.ENGINE_VERSIONS[engine])
        self._sync_preset_box()
        for key, (label, cell) in self._knob_widgets.items():
            label.grid_remove()
            cell.grid_remove()
            enabled = key in own and not self._knob_locks.get(key)
            self.knob_entries[key].configure(state="normal" if enabled else "disabled")
        for i, key in enumerate(own):
            r, c = self._row + 1 + i // 2, (i % 2) * 2
            label, cell = self._knob_widgets[key]
            label.grid(row=r, column=c, sticky="w", padx=(0, 4), pady=2)
            cell.grid(row=r, column=c + 1, sticky="w", padx=(0, 20), pady=2)

    def _on_engine_changed(self):
        self._sync_knob_state()
        for callback in self._listeners:
            callback()
