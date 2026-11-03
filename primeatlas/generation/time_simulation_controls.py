"""TimeSimulationControls -- GenerationTab mixin: the Quick-gen "Time simulation" button and
the one TimeSimulationWindow it opens.

The window is bound to the Floor and Width fields of the selected Quick-gen mode (Explore
has its own pair; every other mode uses the Floor-only pair) and to the pipeline form's
engine selector, so what the sliders set is what Generate runs. Switching the Quick-gen
mode reopens an open window on the new mode's pair. benchmark_log.csv is read from the
storage folder each time the window opens.
"""
import os
from tkinter import ttk

from . import engine_options
from .time_simulation_window import TimeSimulationWindow

BENCHMARK_LOG_NAME = "benchmark_log.csv"


class TimeSimulationControls:
    _time_simulation_window = None

    def _build_time_simulation_button(self, parent):
        button = ttk.Button(parent, text=self.T("timesim.open_button"),
                            command=self._open_time_simulation)
        button.pack(side="left", padx=(8, 0))
        return button

    def _time_simulation_vars(self):
        """(floor_var, width_var) of the selected Quick-gen mode."""
        if self.quick_mode_var.get() == "explore":
            return self.quick_explore_floor_var, self.quick_explore_width_var
        return self.quick_floor_var, self.quick_floor_width_var

    def _time_simulation_is_open(self):
        win = self._time_simulation_window
        try:
            return win is not None and bool(win.winfo_exists())
        except Exception:  # noqa: BLE001 -- a destroyed Tcl widget raises TclError
            return False

    def _open_time_simulation(self):
        if self._time_simulation_is_open():
            self._time_simulation_window.lift()
            self._time_simulation_window.focus_set()
            return self._time_simulation_window
        floor_var, width_var = self._time_simulation_vars()
        self._time_simulation_window = TimeSimulationWindow(
            self, self.T, os.path.join(self._get_portal_folder(), BENCHMARK_LOG_NAME),
            floor_var, width_var, self._engine_fields.engine_var,
            width_cap=self._quick_width_cap,
            write_files=lambda: bool(self._loop_write_files_var.get()),
            pt1_b=self._time_simulation_pt1_b)
        return self._time_simulation_window

    def _time_simulation_pt1_b(self):
        knobs, bad = engine_options.parse_knobs(
            {"pt1_b": self._engine_fields.knob_vars["pt1_b"].get()})
        return knobs["pt1_b"] if bad is None else 0

    def _rebind_time_simulation(self):
        """Reopens an open window on the selected mode's Floor/Width pair."""
        if not self._time_simulation_is_open():
            return
        if (self._time_simulation_window.floor_var, self._time_simulation_window.width_var) \
                == self._time_simulation_vars():
            return
        self._time_simulation_window.close()
        self._time_simulation_window = None
        self._open_time_simulation()
