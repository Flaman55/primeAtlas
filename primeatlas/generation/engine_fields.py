"""Engine selector and knob fields of the Generation tab's pipeline form.

One readonly Combobox picks the sieve engine (engine_options.ENGINES); one Entry per knob
(engine_options.KNOB_KEYS: four for v5, B and the chunk size for pt1), enabled only while
the engine that reads it is selected. Parsing, defaults and the launch env live in
engine_options.py; this module only owns the widgets.
"""
import tkinter as tk
from tkinter import ttk

from . import engine_options

_KNOB_LABEL_KEYS = {
    "v5_segment_kb": "gen.field_v5_segment_kb",
    "v5_region_kb": "gen.field_v5_region_kb",
    "v5_bucket_mb": "gen.field_v5_bucket_mb",
    "v5_windows_at_25": "gen.field_v5_windows_at_25",
    "pt1_b": "gen.field_pt1_b",
    "pt1_chunk_kb": "gen.field_pt1_chunk_kb",
}


class EngineFields:
    """Grids the selector at `row` and the knobs on the rows below it, two per row, in the same
    label/entry column pairs the pipeline form uses (columns 0-3)."""

    def __init__(self, form, T, loop_settings, row):
        self.engine_var = tk.StringVar(
            value=engine_options.normalize_engine(loop_settings.get("engine")))
        ttk.Label(form, text=T("gen.field_engine")).grid(
            row=row, column=0, sticky="w", padx=(0, 4), pady=(6, 2))
        ttk.Combobox(form, textvariable=self.engine_var, values=engine_options.ENGINES,
                     state="readonly", width=8).grid(
            row=row, column=1, sticky="w", padx=(0, 20), pady=(6, 2))
        self.knob_vars = {}
        self.knob_entries = {}
        for i, key in enumerate(engine_options.KNOB_KEYS):
            r, c = row + 1 + i // 2, (i % 2) * 2
            ttk.Label(form, text=T(_KNOB_LABEL_KEYS[key])).grid(
                row=r, column=c, sticky="w", padx=(0, 4), pady=2)
            default = engine_options.DEFAULT_KNOBS[key]
            var = tk.StringVar(value=str(loop_settings.get(key, default)))
            entry = ttk.Entry(form, textvariable=var, width=10)
            entry.grid(row=r, column=c + 1, sticky="w", padx=(0, 20), pady=2)
            self.knob_vars[key] = var
            self.knob_entries[key] = entry
        self._listeners = []
        self.engine_var.trace_add("write", lambda *_: self._on_engine_changed())
        self._sync_knob_state()

    def engine(self):
        return engine_options.normalize_engine(self.engine_var.get())

    def on_engine_change(self, callback):
        self._listeners.append(callback)

    def choice(self):
        """(EngineChoice, None), or (None, key) naming the first invalid knob field of the
        selected engine; another engine's knobs never block a run."""
        engine = self.engine()
        own = engine_options.engine_knob_keys(engine)
        raw = {key: var.get() for key, var in self.knob_vars.items()}
        for key in own:
            _knobs, bad = engine_options.parse_knobs({key: raw[key]})
            if bad is not None:
                return None, bad
        return engine_options.resolve(self.settings()), None

    def settings(self):
        """Values to persist in the Generation settings' "loop" section."""
        values = {key: var.get().strip() for key, var in self.knob_vars.items()}
        values["engine"] = self.engine()
        return values

    def set_bucket_mb(self, bucket_mb):
        self.knob_vars["v5_bucket_mb"].set(str(bucket_mb))

    def _sync_knob_state(self):
        own = engine_options.engine_knob_keys(self.engine())
        for key, entry in self.knob_entries.items():
            entry.configure(state="normal" if key in own else "disabled")

    def _on_engine_changed(self):
        self._sync_knob_state()
        for callback in self._listeners:
            callback()
