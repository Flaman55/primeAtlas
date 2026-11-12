"""EngineAdviceControls -- GenerationTab mixin: the engine proposal (engine_advisor.py) of the
run the Quick-gen Floor and Width fields describe, shown under each Quick-gen panel copy (Floor
and Explore modes) and in the Time simulation window, and the pipeline form's BPSW offset
field it reads.

One source for both places: engine_advice() computes the Advice from benchmark_log.csv (read
when the tab is built, when the Time simulation window opens and when a run ends), the
selected engine's settings (pt1 B, write files, every engine's knobs for the RAM check) and
the RAM free in WSL as last read by the Time simulation window (unknown: no RAM limit). The
Use button selects the proposed engine in the pipeline form; nothing switches it otherwise.

A GenerationTab mixin: it uses the widgets and Variables GenerationTab and its other mixins
set up, so it is never instantiated on its own.
"""
import os
import tkinter as tk
from tkinter import ttk

from ..core.info_tip import InfoTip
from . import engine_advisor, engine_options, run_ram, time_model
from .engine_advice_text import advice_text
from .engine_advice_view import EngineAdviceView
from .generation_settings import remember_generation_field
from .time_simulation_window import format_long_duration
from .window_planning import QUICK_GEN_MAX_WINDOW_WIDTH

BENCHMARK_LOG_NAME = "benchmark_log.csv"
_ADVICE_MODES = ("floor", "explore")


def _positive_int(text):
    text = str(text).strip()
    return int(text) if text.isdigit() and int(text) > 0 else None


class EngineAdviceControls:
    _advice_samples = ()
    _advice_cals = None        # (pt1 B, engine_advisor.calibrations()) of _advice_samples
    _advice_free_ram = None
    _advice_offset_var = None

    def _build_advisor_offset_field(self, form, row):
        """The BPSW offset field (label, entry, info tip) on `row` of the pipeline form."""
        loop_settings = self._generation_settings["loop"]
        key = engine_options.ADVISOR_OFFSET_KEY
        self._advice_offset_var = tk.StringVar(value=str(loop_settings.get(
            key, f"{engine_options.DEFAULT_BPSW_OFFSET:g}")))
        ttk.Label(form, text=self.T("gen.field_advisor_bpsw_offset")).grid(
            row=row, column=0, sticky="w", padx=(0, 4), pady=2)
        cell = ttk.Frame(form)
        cell.grid(row=row, column=1, sticky="w", padx=(0, 20), pady=2)
        ttk.Entry(cell, textvariable=self._advice_offset_var, width=10).pack(side="left")
        InfoTip(cell, lambda: self.T("gen.info_advisor_bpsw_offset")).label.pack(
            side="left", padx=(4, 0))
        remember_generation_field("loop", key, self._advice_offset_var)

    def _build_engine_advice_view(self, parent):
        """A holder packed in `parent` with the proposal view of one Quick-gen panel copy; the
        view itself shows only in the Floor and Explore modes."""
        if not hasattr(self, "_quick_advice_views"):
            self._quick_advice_views = []
        holder = ttk.Frame(parent)
        holder.pack(fill="x", padx=8, pady=(0, 4))
        view = EngineAdviceView(holder, self.T, self._use_advised_engine, wraplength=900)
        self._quick_advice_views.append(view)
        return view

    def _start_engine_advice(self):
        """Called once the pipeline form exists: reads the log and follows every field the
        proposal depends on."""
        self._reload_engine_advice_log()
        fields = self._engine_fields
        watched = [self.quick_mode_var, self.quick_floor_var, self.quick_floor_width_var,
                   self.quick_explore_floor_var, self.quick_explore_width_var,
                   fields.engine_var, self._advice_offset_var, fields.knob_vars["pt1_b"],
                   self._loop_write_files_var]
        for var in watched:
            var.trace_add("write", lambda *_: self._refresh_engine_advice())

    def _reload_engine_advice_log(self):
        """Rereads benchmark_log.csv (a run has added its row, or the storage folder changed)."""
        path = os.path.join(self._get_portal_folder(), BENCHMARK_LOG_NAME)
        self._advice_samples = time_model.read_samples(path)
        self._advice_cals = None
        self._refresh_engine_advice()

    def _set_engine_advice_ram(self, available_ram_bytes):
        self._advice_free_ram = available_ram_bytes
        self._refresh_engine_advice()

    def _advice_offset(self):
        raw = self._advice_offset_var.get() if self._advice_offset_var is not None else ""
        offset = engine_advisor.parse_offset(raw)
        return engine_advisor.DEFAULT_BPSW_OFFSET if offset is None else offset

    def _advice_pt1_b(self):
        knobs, bad = engine_options.parse_knobs(
            {"pt1_b": self._engine_fields.knob_vars["pt1_b"].get()})
        return knobs["pt1_b"] if bad is None else 0

    def engine_advice(self, floor, windows):
        """engine_advisor.Advice of one run of `windows` windows from 10^floor."""
        pt1_b = self._advice_pt1_b()
        if self._advice_cals is None or self._advice_cals[0] != pt1_b:
            self._advice_cals = (pt1_b, engine_advisor.calibrations(self._advice_samples, pt1_b))
        fields = self._engine_fields

        def ram_fits(engine):
            return run_ram.fits_budget(fields.choice_for_engine(engine, windows), windows,
                                       QUICK_GEN_MAX_WINDOW_WIDTH, self._advice_free_ram)

        return engine_advisor.advise(
            self._advice_samples, floor, windows, bool(self._loop_write_files_var.get()),
            pt1_b, self._advice_offset(), ram_fits, cals=self._advice_cals[1])

    def engine_advice_display(self, floor, windows):
        """(AdviceText, proposed engine or None) for the views."""
        advice = self.engine_advice(floor, windows)
        text = advice_text(advice, self.T, lambda s: format_long_duration(s, self.T),
                           self._advice_offset())
        return text, advice.engine if advice is not None else None

    def _refresh_engine_advice(self):
        # A closed detached panel's view is gone: drop it.
        views = [v for v in getattr(self, "_quick_advice_views", []) if v.winfo_exists()]
        self._quick_advice_views = views
        if not views or not hasattr(self, "_engine_fields"):
            return
        mode = self.quick_mode_var.get()
        floor = width = None
        if mode in _ADVICE_MODES:
            floor_var, width_var = ((self.quick_explore_floor_var, self.quick_explore_width_var)
                                    if mode == "explore"
                                    else (self.quick_floor_var, self.quick_floor_width_var))
            floor, width = _positive_int(floor_var.get()), _positive_int(width_var.get())
        if floor is None or width is None or floor < time_model.LOW_FLOOR_CUTOFF:
            for view in views:
                view.pack_forget()
            return
        text, engine = self.engine_advice_display(floor, width)
        for view in views:
            view.show(text, engine, self._engine_fields.engine())
            view.pack(fill="x", anchor="w")

    def _use_advised_engine(self, engine):
        self._engine_fields.engine_var.set(engine)
