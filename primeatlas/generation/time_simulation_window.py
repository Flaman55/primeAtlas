"""Time simulation window of the Generation tab: how the run width and the floor set the prep
cost, the speed and the total time (time_model.py, calibrated from benchmark_log.csv).

Two sliders: the floor and the run width in windows of 10^7 (the Quick-gen Width field, log
scale up to the engine's per-run cap), plus the engine selector. The window writes and
reads the very StringVars of the Generation form it was opened from, so a slider move fills
the form and a form edit moves the slider; the vars belong to the form, the window only
traces them and removes its traces when it closes. The log is read once when the window
opens; it is never written.
"""
import math
import tkinter as tk
from tkinter import ttk

from . import engine_options, time_model
from .run_output import format_duration_short

FLOOR_MIN = time_model.LOW_FLOOR_CUTOFF
FLOOR_MAX = 35
_DAY = 86400.0
_YEAR = 365.25 * _DAY


def format_long_duration(seconds, T):
    """Short duration up to a day, then days, then years (scientific past 10^6 years)."""
    if seconds is None:
        return "?"
    if seconds < 1e-3:
        return f"{seconds * 1e6:.1f} µs"
    if seconds < 1:
        return f"{seconds * 1e3:.1f} ms"
    if seconds < _DAY:
        return format_duration_short(seconds)
    if seconds < _YEAR:
        return T("timesim.unit_days", value=f"{seconds / _DAY:.1f}")
    years = seconds / _YEAR
    return T("timesim.unit_years", value=f"{years:.3g}" if years < 1e6 else f"{years:.2e}")


_RATE_UNITS = ((1e9, "Gn/s"), (1e6, "Mn/s"), (1e3, "kn/s"))


def format_rate(numbers_per_second):
    """Numbers per second with the unit scaled to the value: n/s, kn/s, Mn/s or Gn/s."""
    if numbers_per_second is None:
        return "?"
    for scale, unit in _RATE_UNITS:
        if numbers_per_second >= scale:
            return f"{numbers_per_second / scale:,.1f} {unit}"
    return f"{numbers_per_second:.1f} n/s"


def _int_or_none(text):
    text = str(text).strip()
    return int(text) if text.isdigit() else None


class TimeSimulationWindow(tk.Toplevel):
    """Toplevel bound to the form's vars: floor_var and width_var (windows per run),
    engine_var; width_cap() gives the engine's per-run cap, write_files() whether runs write
    files, pt1_b() the pt1 B knob (0 = automatic)."""

    def __init__(self, master, T, log_path, floor_var, width_var, engine_var, width_cap,
                 write_files, pt1_b):
        super().__init__(master)
        self.T = T
        self.title(T("timesim.title"))
        self.floor_var = floor_var
        self.width_var = width_var
        self.engine_var = engine_var
        self._width_cap = width_cap
        self._write_files = write_files
        self._pt1_b = pt1_b
        self._samples = time_model.read_samples(log_path)
        self._calibrations = {}
        self._syncing = False
        self.result_vars = {key: tk.StringVar(value="") for key in (
            "floor", "width", "primes", "prep", "sieve", "write", "run", "window", "speed",
            "speed_net", "measured", "floor_total", "model")}
        self._build()
        self._traces = [(var, var.trace_add("write", lambda *_: self._on_form_changed()))
                        for var in (floor_var, width_var, engine_var)]
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._on_form_changed()

    def _build(self):
        T = self.T
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=T("timesim.intro"), style="Hint.TLabel", wraplength=560,
                  justify="left").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        ttk.Label(body, text=T("gen.field_engine")).grid(row=1, column=0, sticky="w")
        self.engine_combo = ttk.Combobox(body, textvariable=self.engine_var,
                                         values=engine_options.ENGINES, state="readonly", width=8)
        self.engine_combo.grid(row=1, column=1, sticky="w", pady=2)

        ttk.Label(body, text=T("timesim.floor_slider")).grid(row=2, column=0, sticky="w")
        self.floor_scale = ttk.Scale(body, from_=FLOOR_MIN, to=FLOOR_MAX, orient="horizontal",
                                     length=360, command=self._on_floor_slider)
        self.floor_scale.grid(row=2, column=1, sticky="we", pady=4)
        ttk.Label(body, textvariable=self.result_vars["floor"], width=26).grid(
            row=2, column=2, sticky="w", padx=(8, 0))

        ttk.Label(body, text=T("timesim.width_slider")).grid(row=3, column=0, sticky="w")
        self.width_scale = ttk.Scale(body, from_=0.0, to=1.0, orient="horizontal", length=360,
                                     command=self._on_width_slider)
        self.width_scale.grid(row=3, column=1, sticky="we", pady=4)
        ttk.Label(body, textvariable=self.result_vars["width"], width=26).grid(
            row=3, column=2, sticky="w", padx=(8, 0))

        results = ttk.LabelFrame(body, text=T("timesim.results_frame"), padding=8)
        results.grid(row=4, column=0, columnspan=3, sticky="we", pady=(8, 0))
        for row, key in enumerate(("primes", "prep", "sieve", "write", "run", "window", "speed",
                                   "speed_net", "measured", "floor_total")):
            ttk.Label(results, text=T(f"timesim.label_{key}")).grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=1)
            ttk.Label(results, textvariable=self.result_vars[key]).grid(
                row=row, column=1, sticky="w", pady=1)
        ttk.Label(body, textvariable=self.result_vars["model"], style="Hint.TLabel",
                  wraplength=560, justify="left").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))
        body.columnconfigure(1, weight=1)

    def close(self):
        for var, trace_id in self._traces:
            try:
                var.trace_remove("write", trace_id)
            except tk.TclError:
                pass
        self._traces = []
        self.destroy()

    def _engine(self):
        return engine_options.normalize_engine(self.engine_var.get())

    def _calibration(self, engine):
        if engine not in self._calibrations:
            self._calibrations[engine] = time_model.calibrate(
                self._samples, engine, self._pt1_b() if engine == engine_options.ENGINE_PT1 else 0)
        return self._calibrations[engine]

    def floor(self):
        value = _int_or_none(self.floor_var.get())
        return min(FLOOR_MAX, max(FLOOR_MIN, value)) if value is not None else FLOOR_MIN

    def windows(self):
        value = _int_or_none(self.width_var.get())
        return min(self._width_cap(), max(1, value)) if value else 1

    def _width_position(self, windows):
        cap = self._width_cap()
        return math.log(windows) / math.log(cap) if cap > 1 else 0.0

    def _on_floor_slider(self, value):
        if self._syncing:
            return
        floor = int(round(float(value)))
        if _int_or_none(self.floor_var.get()) != floor:
            self.floor_var.set(str(floor))

    def _on_width_slider(self, value):
        if self._syncing:
            return
        cap = self._width_cap()
        windows = max(1, min(cap, int(round(cap ** float(value)))))
        if _int_or_none(self.width_var.get()) != windows:
            self.width_var.set(str(windows))

    def _on_form_changed(self):
        self._syncing = True
        try:
            self.floor_scale.set(self.floor())
            self.width_scale.set(self._width_position(self.windows()))
        finally:
            self._syncing = False
        self.refresh()

    def _measured_text(self, engine, floor, pt1_b):
        T = self.T
        runs = time_model.measured_runs(self._samples, engine, floor, pt1_b)
        if not runs.count:
            return T("timesim.measured_none")
        speed = runs.windows * time_model.WINDOW_WIDTH / runs.seconds if runs.seconds else None
        return T("timesim.measured_value", count=runs.count, windows=f"{runs.windows:,}",
                 time=format_long_duration(runs.seconds, T), speed=format_rate(speed),
                 model=format_long_duration(runs.model_seconds, T))

    def refresh(self):
        T = self.T
        engine, floor, windows = self._engine(), self.floor(), self.windows()
        write_files = self._write_files()
        pt1_b = self._pt1_b() if engine == engine_options.ENGINE_PT1 else 0
        cal = self._calibration(engine)
        est = time_model.estimate(cal, engine, floor, windows, write_files, pt1_b)
        below = time_model.estimate(None, engine, floor - 1, windows, write_files, pt1_b)
        v = self.result_vars
        v["floor"].set(T("timesim.floor_value", floor=floor))
        v["width"].set(T("timesim.width_value", windows=f"{windows:,}", span=f"{est.span:.3g}"))
        kind = T("timesim.exact") if est.primes_exact else T("timesim.approx")
        ratio = est.primes / below.primes if below.primes else 0.0
        v["primes"].set(T("timesim.primes_value", primes=f"{est.primes:,}", kind=kind,
                          limit=f"{est.limit:.3g}", ratio=f"{ratio:.2f}"))
        v["prep"].set(format_long_duration(est.prep_seconds, T))
        v["sieve"].set(format_long_duration(est.sieve_seconds, T))
        if not write_files:
            v["write"].set(T("timesim.write_off"))
        elif cal is not None and not est.write_known:
            v["write"].set(T("timesim.write_unknown"))
        else:
            v["write"].set(format_long_duration(est.write_seconds, T))
        v["run"].set(format_long_duration(est.run_seconds, T))
        v["window"].set(format_long_duration(est.window_seconds, T))
        v["speed"].set(format_rate(est.numbers_per_second))
        v["speed_net"].set(format_rate(est.span / est.sieve_seconds if est.sieve_seconds else None))
        total = time_model.floor_seconds(cal, engine, floor, windows, write_files, pt1_b)
        runs = -(-time_model.floor_windows(floor) // windows)
        v["floor_total"].set(T("timesim.floor_total_value", time=format_long_duration(total, T),
                               runs=f"{runs:,}", numbers=f"{9 * 10 ** floor:.0e}"))
        v["measured"].set(self._measured_text(engine, floor, pt1_b))
        if cal is None:
            v["model"].set(T("timesim.model_none", engine=engine))
        else:
            text = T("timesim.model_info", engine=engine, rows=cal.rows, floor_lo=cal.floors[0],
                     floor_hi=cal.floors[1], error=f"{cal.max_error * 100:.0f}")
            if est.extrapolated:
                text += "\n" + T("timesim.model_extrapolated")
            v["model"].set(text)
