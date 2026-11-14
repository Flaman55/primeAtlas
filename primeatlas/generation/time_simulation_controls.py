"""TimeSimulationControls -- GenerationTab mixin: the Quick-gen "Time simulation" button and
the one TimeSimulationWindow it opens.

The window is bound to the Floor and Width fields of the selected Quick-gen mode (Explore
has its own pair; every other mode uses the Floor-only pair) and to the pipeline form's
engine selector, so what the sliders set is what Generate runs. Switching the Quick-gen
mode reopens an open window on the new mode's pair. benchmark_log.csv is read from the
storage folder each time the window opens and, while it is open, when a run ends. The RAM
free in WSL is read when the tab is built, when the window opens and when a run ends, on a
background thread (a wsl.exe call can take up to its timeout), and handed to the engine
proposal and Generate's RAM check (engine_advice_controls.py), and to an open window, when the
thread ends. The window shows the same proposal as Quick-gen: it asks the tab for it
(engine_advice_display) at the sliders' floor and width.
"""
import os
import threading
from tkinter import ttk

from . import engine_options
from .time_simulation_window import TimeSimulationWindow
from .wsl_resources import estimate_wsl_available_ram_bytes

RAM_READ_CHECK_MS = 100

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
            pt1_b=self._time_simulation_pt1_b,
            engine_choice=self._engine_fields.choice_for_windows,
            budget_vars=self._time_simulation_budget_vars(),
            advice=self.engine_advice_display, use_engine=self._use_advised_engine,
            advice_vars=(self._advice_offset_var,))
        self._reload_engine_advice_log()
        self._read_free_ram()
        return self._time_simulation_window

    def _time_simulation_budget_vars(self):
        """Form vars the RAM cap depends on: the RAM budget, the bucket memory, the profiles."""
        fields = self._engine_fields
        keys = [engine_options.RAM_BUDGET_KNOB] + [
            engine_options.bucket_knob(engine) for engine in engine_options.BUCKETED_ENGINES]
        return [fields.knob_vars[key] for key in keys] + list(fields.preset_vars.values())

    def _read_free_ram(self):
        """Reads the free WSL RAM on a thread; the engine proposal, and the window open when
        the read began, get it when the thread ends."""
        win = self._time_simulation_window
        result = {}
        thread = threading.Thread(
            target=lambda: result.update(value=estimate_wsl_available_ram_bytes()), daemon=True)
        thread.start()

        def deliver():
            if thread.is_alive():
                self.after(RAM_READ_CHECK_MS, deliver)
            else:
                self._set_engine_advice_ram(result.get("value"))
                if win is self._time_simulation_window and self._time_simulation_is_open():
                    win.set_available_ram(result.get("value"))

        self.after(RAM_READ_CHECK_MS, deliver)

    def _reload_time_simulation_log(self):
        """Called when a run ends: an open window rereads the log with the run's new row, and
        the free RAM is read again."""
        if self._time_simulation_is_open():
            self._time_simulation_window.reload_log()
        self._read_free_ram()

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
