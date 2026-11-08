"""
quick_gen_pseudosquares.py -- QuickGenPseudosquares, Quick-gen's Pseudosquares mode: the
Pseudosquares Prime Sieve program (Kim Walisch, BSD 2-Clause License) run natively, count
or print, from Floor / From / Width / Threads (pseudosquares_plan.py), launched as
pseudosquares_native.py on the shared Generation runner and console.

The mode is always native: there is no Atlas-format wrapper and a run writes nothing into the
storage (print's text is the program's own format), so every run is a benchmark and the
Benchmark checkbox shows checked and locked (QuickGenPanel._sync_benchmark_lock). Threads
applies to count only: the program prints on one thread.

A GenerationTab mixin: it uses the widgets, Variables and runner state that GenerationTab
and its other mixins set up, so it is never instantiated on its own.
"""
import queue
import tkinter as tk
from tkinter import messagebox, ttk

import pseudosquares_const

from ..core.info_tip import InfoTip
from .engine_argv import build_pseudosquares_native_argv
from .pseudosquares_plan import parse_threads, plan
from .quick_gen_panel import _floor_spinbox
from .quick_number import _eval_quick_number
from .window_planning import QUICK_GEN_MAX_WINDOW_WIDTH
from .wsl_command import build_wsl_logged_command, generation_log_paths

PSEUDOSQUARES_MODES = ("count", "print")


class QuickGenPseudosquares:
    def _init_pseudosquares_state(self):
        """The mode's Variables, shared by every panel copy like every other mode's."""
        self.quick_pseudosquares_floor_var = tk.StringVar(value="")
        self.quick_pseudosquares_from_var = tk.StringVar(value="")
        self.quick_pseudosquares_width_var = tk.StringVar(value="1")
        self.quick_pseudosquares_mode_var = tk.StringVar(value="count")
        self.quick_pseudosquares_threads_var = tk.StringVar(value="Auto")
        self._pseudosquares_threads_spinboxes = []  # one per panel copy
        self.quick_pseudosquares_mode_var.trace_add(
            "write", lambda *_: self._sync_pseudosquares_controls())

    def _build_quick_mode_pseudosquares(self, container, mode_frames):
        """Floor + From + Width like primesieve mode (From blank = the Floor's start), then
        count/print and Threads, and the always-visible attribution."""
        frame = ttk.Frame(container)
        frame.grid(row=0, column=0, sticky="w")
        row1 = ttk.Frame(frame)
        row1.pack(anchor="w")
        ttk.Label(row1, text=self.T("quick.field_floor")).pack(side="left")
        _floor_spinbox(row1, self.quick_pseudosquares_floor_var, 10,
                       to=pseudosquares_const.MAX_FLOOR).pack(side="left", padx=(6, 20))
        ttk.Label(row1, text=self.T("quick.field_from")).pack(side="left")
        ttk.Entry(row1, textvariable=self.quick_pseudosquares_from_var, width=36).pack(
            side="left", padx=(6, 20))
        ttk.Label(row1, text=self.T("quick.field_width")).pack(side="left")
        ttk.Entry(row1, textvariable=self.quick_pseudosquares_width_var, width=14).pack(
            side="left", padx=(6, 0))

        row2 = ttk.Frame(frame)
        row2.pack(anchor="w", pady=(4, 0))
        labels = {"count": self.T("quick.pseudosquares_mode_count"),
                  "print": self.T("quick.pseudosquares_mode_print")}
        shown = tk.StringVar(value=labels.get(self.quick_pseudosquares_mode_var.get(),
                                              labels["count"]))
        ttk.Combobox(row2, textvariable=shown, values=[labels[m] for m in PSEUDOSQUARES_MODES],
                     state="readonly", width=max(len(v) for v in labels.values()) + 2).pack(
            side="left")

        def on_shown(*_):
            self.quick_pseudosquares_mode_var.set(
                next(k for k, v in labels.items() if v == shown.get()))

        def on_mode(*_):  # another panel copy changed the mode
            label = labels[self.quick_pseudosquares_mode_var.get()]
            if shown.get() != label:
                shown.set(label)
        shown.trace_add("write", on_shown)
        self.quick_pseudosquares_mode_var.trace_add("write", on_mode)
        InfoTip(row2, lambda: self.T("quick.info_pseudosquares")).label.pack(
            side="left", padx=(4, 16))
        ttk.Label(row2, text=self.T("quick.field_threads")).pack(side="left")
        threads = ttk.Spinbox(row2, values=["Auto"] + [str(n) for n in range(1, 257)],
                              textvariable=self.quick_pseudosquares_threads_var, width=8)
        threads.pack(side="left", padx=(6, 0))
        self._pseudosquares_threads_spinboxes.append(threads)

        ttk.Label(frame, text=self.T("quick.attribution_pseudosquares"), style="Hint.TLabel",
                  font=("TkDefaultFont", 8), wraplength=860, justify="left").pack(
            anchor="w", pady=(4, 0))
        mode_frames["pseudosquares"] = frame
        self._sync_pseudosquares_controls()

    def _sync_pseudosquares_controls(self):
        """Threads only for count; the Benchmark lock follows the mode."""
        state = "normal" if self.quick_pseudosquares_mode_var.get() == "count" else "disabled"
        for spinbox in self._pseudosquares_threads_spinboxes:
            if spinbox.winfo_exists():
                spinbox.configure(state=state)
        self._sync_benchmark_lock()

    def _on_quick_generate_pseudosquares(self):
        """Plans the run from the fields (pseudosquares_plan.plan) and launches it, or shows
        why it cannot run."""
        raw_from = self.quick_pseudosquares_from_var.get().strip()
        start = _eval_quick_number(raw_from) if raw_from else None
        raw_floor = self.quick_pseudosquares_floor_var.get().strip()
        floor = _eval_quick_number(raw_floor) if raw_floor else None
        width = _eval_quick_number(self.quick_pseudosquares_width_var.get())
        mode = self.quick_pseudosquares_mode_var.get()
        threads = parse_threads(self.quick_pseudosquares_threads_var.get())
        if mode == "print":
            threads = 0
        if threads is None:
            messagebox.showerror(self.T("quick.dialog_title"),
                                 self.T("quick.error_pseudosquares_threads"))
            return
        if raw_from and start is None:
            start = 0  # not a number: refused as below 1
        result = plan(start, floor, width, QUICK_GEN_MAX_WINDOW_WIDTH)
        if "error" in result:
            messagebox.showerror(self.T("quick.dialog_title"), self.T(
                f"quick.error_pseudosquares_{result['error']}",
                max_stop=f"{pseudosquares_const.MAX_STOP:,}",
                max_floor=pseudosquares_const.MAX_FLOOR))
            return
        self.quick_status_var.set(self.T(
            "quick.summary_pseudosquares", mode=mode, floor=result["floor"],
            lo=f"{result['lo']:,}", hi=f"{result['hi']:,}", count=result["count"],
            threads=threads or "Auto")
            + (self.T("quick.note_pseudosquares_clamped") if result["clamped"] else ""))
        self._on_run_pseudosquares(result["floor"], result["target_idx_start"],
                                   result["count"], mode, threads)

    def _on_run_pseudosquares(self, base_exponent, target_idx_start, window_count, mode,
                              threads):
        """Launches pseudosquares_native.py on the shared Generation runner (one run at a
        time across engines, same console, Stop and finish handling as primesieve mode)."""
        if (self._loop_runner is not None and self._loop_runner.is_running()
                or self._other_engine_is_running("loop")):
            messagebox.showerror(self.T("quick.dialog_title"),
                                 self.T("quick.error_already_running"))
            return
        # One blocking program call with no per-window lines: no progress to show.
        self._gen_progress_bar_active = False
        try:
            argv = build_pseudosquares_native_argv(
                base_exponent, target_idx_start, window_count, QUICK_GEN_MAX_WINDOW_WIDTH,
                mode, threads)
            log_path, exit_path, _run_id = generation_log_paths(self._get_portal_folder(),
                                                                "pseudosquares")
            cmd = build_wsl_logged_command(argv, log_path, exit_path, self._get_portal_folder())
            self.loop_console.append(self._new_run_separator())
            self._loop_output_queue = queue.Queue()
            self._start_loop_runner(cmd, log_path, exit_path, "pseudosquares_native.py",
                                    base_exponent, first_target_idx=target_idx_start,
                                    window_m=QUICK_GEN_MAX_WINDOW_WIDTH)
        except Exception as e:  # noqa: BLE001 -- surfaced, like every other launcher
            self._loop_runner = None
            messagebox.showerror(self.T("gen.dialog_title"), self.T(
                "gen.error_launch_failed", error=str(e)))
            return
        self.loop_run_btn.configure(state="disabled")
        self.loop_stop_btn.configure(state="normal")
        self._lock_other_run_buttons("loop")
        self.loop_status_label.set(self.T("common.running"))
        for panel in self._quick_panels:
            panel["generate_btn"].configure(text=self.T("common.stop"))
        self._show_loop_terminal()
