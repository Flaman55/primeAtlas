"""
pi_count_notice_controls.py -- PiCountNoticeControls, the notice shown before a run that will
count pi(L) from zero on its floor (either pi checkbox of the pipeline form is on:
compute_sieving_primes_count, or the seeded count; pi_count_notice.py decides), with the
estimated time and [Enable] / [Leave disabled]. _on_run_loop and _on_run_orchestrator_direct
call it with the run's range just before they read the checkboxes. [Leave disabled] and
closing the window untick both boxes, so the run counts nothing; with counting off, or once
the floor has its cache, nothing shows.

A GenerationTab mixin: it uses the pipeline form's Variables (loop_section.py), the engine
selector and _get_portal_folder() of the tab.
"""
import tkinter as tk
from tkinter import ttk

from . import pi_count_notice
from .window_planning import find_continuation_target_idx


class PiCountNoticeControls:
    def _pi_counting_on(self):
        return bool(self._loop_count_sieving_var.get() or self._loop_use_pi_seed_var.get())

    def _pi_loop_form_range(self):
        """(floor, lo, hi, first_hi) of the run the pipeline form describes, None while a
        field is not a number or the floor's store is full. Its instances split each
        iteration's windows, so the first batch ends one instance slice past lo."""
        values = {}
        for key in ("base_exponent", "run_count", "n_instances", "window_count_per_run",
                    "window_m"):
            raw = self._loop_vars[key].get().strip()
            if not raw.isdigit():
                return None
            values[key] = int(raw)
        floor, window_m = values["base_exponent"], values["window_m"]
        per_run = values["window_count_per_run"]
        if not (window_m and per_run and values["run_count"] and values["n_instances"]):
            return None
        start = find_continuation_target_idx(self._get_portal_folder(), floor, window_m,
                                             engine=self._selected_engine())
        lo = 10 ** floor + start * window_m
        floor_end = 10 ** (floor + 1)
        if lo >= floor_end:
            return None
        hi = min(lo + values["run_count"] * per_run * window_m, floor_end)
        slice_windows = -(-per_run // values["n_instances"])
        return floor, lo, hi, min(lo + slice_windows * window_m, hi)

    def _pi_count_notice_for_loop_form(self):
        planned = self._pi_loop_form_range()
        if planned is not None:
            self._pi_count_notice(*planned)

    def _pi_count_notice(self, floor, lo, hi, first_hi):
        """Before a run over [lo, hi) of `floor`: the notice when it applies; [Leave
        disabled] unticks both pi checkboxes."""
        if not self._pi_counting_on():
            return
        est = pi_count_notice.estimate(self._get_portal_folder(), floor, lo, hi, first_hi,
                                       bool(self._loop_use_pi_seed_var.get()))
        if not pi_count_notice.notice_needed(True, est):
            return
        if not self._ask_pi_count(pi_count_notice.format_duration(est["seconds"])):
            self._loop_count_sieving_var.set(False)
            self._loop_use_pi_seed_var.set(False)

    def _ask_pi_count(self, time_text):
        """True for [Enable]; [Leave disabled] and closing the window give False."""
        T = self.T
        dialog = tk.Toplevel(self)
        dialog.title(T("gen.pi_notice_title"))
        dialog.transient(self.winfo_toplevel())
        answer = {"enable": False}
        ttk.Label(dialog, text=T("gen.pi_notice_title"), font=("TkDefaultFont", 10, "bold")).pack(
            anchor="w", padx=16, pady=(14, 4))
        ttk.Label(dialog, text=T("gen.pi_notice_body", time=time_text), wraplength=520,
                  justify="left").pack(anchor="w", padx=16)
        buttons = ttk.Frame(dialog)
        buttons.pack(pady=14)

        def choose(enable):
            answer["enable"] = enable
            dialog.destroy()

        ttk.Button(buttons, text=T("gen.pi_notice_enable"),
                   command=lambda: choose(True)).pack(side="left", padx=6)
        leave = ttk.Button(buttons, text=T("gen.pi_notice_leave_off"),
                           command=lambda: choose(False))
        leave.pack(side="left", padx=6)
        leave.focus_set()
        dialog.protocol("WM_DELETE_WINDOW", lambda: choose(False))
        dialog.grab_set()
        dialog.wait_window()
        return answer["enable"]
