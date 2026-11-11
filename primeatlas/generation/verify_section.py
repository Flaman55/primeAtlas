"""
verify_section.py -- VerifySection, Section D of the Generation tab: proves pt1's P windows
of one floor's store, so they become D/P, by one of two methods: the pt1.1 proof
(prime_sieve/pt1_verify_store.py) or the v7.3 sieve (prime_sieve/v73_verify_store.py, engine
v7.2's sieve in passes of 10^Pass numbers).

The store-side counterpart of the pt1 engine's "verify P -> D" checkbox: with the checkbox
off, pt1 writes P windows at its full speed and this section proves them later, like the
k-tuple search reads the windows the generation wrote. The proof uses the pt1 knobs B and
chunk size of the pipeline form (engine_options.launch_env()); the sieve runs on v7.2's
default knobs. The method and the pass also serve the pipeline form's pt1 checkbox
"verify P -> D after the run" (run_verify.py): _pt1_verify_choice() goes into that launch's
env and the checkbox's hint names them; a click on that hint scrolls the tab to this section.
Next to the method, a rough time of both methods for the chosen windows
(verify_estimate.py, from benchmark_log.csv) helps choosing. Stop writes the generation stop
request, which the scripts check between slabs or passes (each finished one is kept), with
a hard kill after VERIFY_STOP_GRACE_MS for one that takes longer; a killed slab or pass only
loses its own proofs.

A GenerationTab mixin: it uses the widgets, Variables and runner state that GenerationTab
and its other mixins set up, so it is never instantiated on its own.
"""
import queue

import tkinter as tk
from tkinter import ttk, messagebox

import run_verify
from primeatlas.core import ui_state_dynamic
from ..core.info_tip import InfoTip
from ..benchmark.benchmark import read_benchmark_log
from . import engine_options, run_guard, verify_estimate, verify_plan
from .engine_argv import build_pt1_verify_argv, build_v73_verify_argv
from .generation_console import GenerationConsole
from .generation_settings import remember_generation_field, save_generation_settings
from .quick_gen_panel import _floor_spinbox
from .wsl_command import build_wsl_logged_command, generation_log_paths
from .wsl_resources import estimate_wsl_available_cpu_count

VERIFY_SCRIPT_PATTERNS = run_verify.SCRIPTS
# A slab of the default size takes about a minute of proofs on floor 29 (arbitrary margin).
VERIFY_STOP_GRACE_MS = 180_000
VERIFY_COUNT_DELAY_MS = 300
# The Windows field is not stored: it is recounted from the store (verify_plan.py).
_STORED_FIELDS = ("base_exponent", "width_exp", "threads", "method", "pass_exp")


class VerifySection:
    def _build_verify_section(self, sections):
        """Section D: floor, window width exponent, the window count (recounted from the
        store) and threads; the method, the v7.3 pass width and the estimate; Run/Stop,
        console."""
        outer = ttk.Labelframe(sections, text=self.T("gen.section_verify"))
        outer.pack(fill="x", pady=(6, 0))
        self._verify_frame = outer
        self._engine_fields.knob_hint_labels["pt1_verify"].bind(
            "<Button-1>", lambda _e: self._scroll_page.scroll_to(outer))
        hint_row = ttk.Frame(outer)
        hint_row.pack(fill="x", padx=8, pady=(6, 0))
        ttk.Label(hint_row, text=self.T("gen.verify_hint"), wraplength=760, justify="left",
                  style="Hint.TLabel").pack(side="left")
        InfoTip(hint_row, lambda: self.T("gen.info_verify")).label.pack(side="left", padx=(4, 0))

        settings = self._generation_settings["verify"]
        form = ttk.Frame(outer)
        form.pack(fill="x", padx=8, pady=(4, 4))
        self._verify_vars = {key: tk.StringVar(value=str(settings.get(key, "")))
                             for key in _STORED_FIELDS}
        if self._verify_vars["method"].get() not in verify_plan.METHODS:
            self._verify_vars["method"].set(verify_plan.METHOD_PROOF)
        if not self._verify_vars["pass_exp"].get():
            self._verify_vars["pass_exp"].set(str(verify_plan.DEFAULT_PASS_EXP))
        self._verify_vars["max_windows"] = tk.StringVar(value="0")
        for key in _STORED_FIELDS:
            remember_generation_field("verify", key, self._verify_vars[key])

        def label(key):
            ttk.Label(form, text=self.T(f"gen.verify_field_{key}")).pack(side="left")

        label("base_exponent")
        _floor_spinbox(form, self._verify_vars["base_exponent"], 6).pack(
            side="left", padx=(6, 20))
        label("width_exp")
        ttk.Spinbox(form, from_=verify_plan.WIDTH_EXP_MIN, to=verify_plan.WIDTH_EXP_MAX,
                    increment=1, textvariable=self._verify_vars["width_exp"], width=4).pack(
            side="left", padx=(6, 20))
        label("max_windows")
        self._verify_windows_box = ttk.Spinbox(
            form, from_=1, to=1, increment=1, textvariable=self._verify_vars["max_windows"],
            width=8)
        self._verify_windows_box.pack(side="left", padx=(6, 4))
        self._verify_total_text = tk.StringVar()
        ttk.Label(form, textvariable=self._verify_total_text, style="Hint.TLabel").pack(
            side="left", padx=(0, 20))
        label("threads")
        ttk.Spinbox(form, values=verify_plan.THREAD_CHOICES,
                    textvariable=self._verify_vars["threads"], width=6).pack(
            side="left", padx=(6, 0))
        method_row = ttk.Frame(outer)
        method_row.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Label(method_row, text=self.T("gen.verify_field_method")).pack(side="left")
        self._verify_method_names = {method: self.T(f"gen.verify_method_{method}")
                                     for method in verify_plan.METHODS}
        self._verify_method_text = tk.StringVar(
            value=self._verify_method_names[self._verify_vars["method"].get()])
        method_box = ttk.Combobox(method_row, textvariable=self._verify_method_text,
                                  values=list(self._verify_method_names.values()),
                                  state="readonly", width=14)
        method_box.pack(side="left", padx=(6, 20))
        method_box.bind("<<ComboboxSelected>>", lambda _e: self._on_verify_method_chosen())
        ttk.Label(method_row, text=self.T("gen.verify_field_pass_exp")).pack(side="left")
        self._verify_pass_box = ttk.Spinbox(
            method_row, from_=verify_plan.WIDTH_EXP_MIN, to=verify_plan.WIDTH_EXP_MAX,
            increment=1, textvariable=self._verify_vars["pass_exp"], width=4)
        self._verify_pass_box.pack(side="left", padx=(6, 20))
        self._verify_estimate_text = tk.StringVar()
        ttk.Label(method_row, textvariable=self._verify_estimate_text,
                  style="Hint.TLabel").pack(side="left")
        self._on_verify_method_chosen()

        self._verify_total = 0
        self._verify_count_after_id = None
        for key in ("base_exponent", "width_exp"):
            self._verify_vars[key].trace_add("write", lambda *_: self._schedule_verify_count())
        for key in ("max_windows", "pass_exp"):
            self._verify_vars[key].trace_add("write",
                                             lambda *_: self._schedule_verify_count(False))
        self._verify_vars["pass_exp"].trace_add("write",
                                                lambda *_: self._refresh_pt1_verify_hint())
        self._loop_write_files_var.trace_add("write", lambda *_: self._sync_pt1_verify_lock())
        self._sync_pt1_verify_lock()
        self._refresh_verify_count()

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", padx=8, pady=(4, 4))
        self.verify_run_btn = ttk.Button(buttons, text=self.T("common.run"),
                                         command=self._on_run_verify)
        self.verify_run_btn.pack(side="left")
        self.verify_stop_btn = ttk.Button(buttons, text=self.T("common.stop"),
                                          command=self._on_stop_verify, state="disabled")
        self.verify_stop_btn.pack(side="left", padx=(6, 0))
        self.verify_status_label = tk.StringVar(value=self.T("common.ready"))
        ttk.Label(buttons, textvariable=self.verify_status_label).pack(side="left", padx=(12, 0))

        self.verify_console = GenerationConsole(outer, self.T, height=12)
        self._register_scroll_exclude(self.verify_console.text.frame)
        self._verify_runner = None
        self._verify_output_queue = queue.Queue()
        self._verify_stop_after_id = None

    def _schedule_verify_count(self, recount=True):
        """Recounts the floor's P windows (recount) or only the estimate once typing or
        wheeling pauses: both list the floor's P store."""
        if self._verify_count_after_id is not None:
            self.after_cancel(self._verify_count_after_id)
        self._verify_count_after_id = self.after(
            VERIFY_COUNT_DELAY_MS,
            self._refresh_verify_count if recount else self._refresh_verify_estimate)

    def _on_verify_method_chosen(self):
        """Stores the chosen method; the pass width only counts for the v7.3 sieve."""
        chosen = self._verify_method_text.get()
        method = next((m for m, name in self._verify_method_names.items() if name == chosen),
                      verify_plan.METHOD_PROOF)
        self._verify_vars["method"].set(method)
        self._verify_pass_box.configure(
            state="normal" if method == verify_plan.METHOD_SIEVE else "disabled")
        self._refresh_pt1_verify_hint()

    def _pt1_verify_choice(self):
        """(method, pass_numbers) of this section for the verification after a pt1 run."""
        return (self._verify_vars["method"].get(),
                10 ** verify_plan.pass_exp(self._verify_vars["pass_exp"].get()))

    def _refresh_pt1_verify_hint(self):
        """Names this section's method (and the sieve's pass) next to the pt1 checkbox."""
        if self._verify_vars["method"].get() == verify_plan.METHOD_SIEVE:
            text = self.T("gen.pt1_verify_hint_sieve",
                          pass_exp=verify_plan.pass_exp(self._verify_vars["pass_exp"].get()))
        else:
            text = self.T("gen.pt1_verify_hint_proof")
        self._engine_fields.knob_hint_vars["pt1_verify"].set(text)

    def _sync_pt1_verify_lock(self):
        """A Benchmark run (write_files off) writes no P window to verify: the pt1 checkbox
        is greyed out then, the reason in its tooltip."""
        self._engine_fields.set_knob_lock(
            "pt1_verify",
            None if self._loop_write_files_var.get() else self.T("gen.pt1_verify_benchmark_lock"))

    def _refresh_verify_estimate(self):
        """Sets and returns the estimate of both methods for the chosen windows."""
        self._verify_count_after_id = None
        floor = verify_plan.parse_int(self._verify_vars["base_exponent"].get(), 0)
        width_exp = verify_plan.parse_int(self._verify_vars["width_exp"].get(),
                                          verify_plan.WIDTH_EXP_MIN)
        pass_exp = verify_plan.parse_int(self._verify_vars["pass_exp"].get(),
                                         verify_plan.WIDTH_EXP_MIN)
        max_windows = verify_plan.max_windows_arg(self._verify_vars["max_windows"].get(),
                                                  self._verify_total) or 0
        portal = self._get_portal_folder()
        passes = verify_plan.store_passes(portal, floor, width_exp, max_windows, pass_exp)
        _fields, rows = read_benchmark_log(portal) if portal else ([], [])
        text = self.T("gen.verify_estimate",
                      proof=verify_estimate.duration_text(
                          verify_estimate.proof_seconds(rows, sum(passes))),
                      sieve=verify_estimate.duration_text(
                          verify_estimate.sieve_seconds(rows, floor, passes)),
                      passes=len(passes))
        self._verify_estimate_text.set(text)
        return text

    def _refresh_verify_count(self):
        """Sets the Windows field to every P window of the floor at the chosen width (a
        smaller value proves only the first ones) and returns that total."""
        self._verify_count_after_id = None
        floor = verify_plan.parse_int(self._verify_vars["base_exponent"].get(), 0)
        width_exp = verify_plan.parse_int(self._verify_vars["width_exp"].get(),
                                          verify_plan.WIDTH_EXP_MIN)
        self._verify_total = verify_plan.window_count(self._get_portal_folder(), floor,
                                                      width_exp)
        self._verify_windows_box.configure(to=max(self._verify_total, 1))
        self._verify_vars["max_windows"].set(str(self._verify_total))
        self._verify_total_text.set(self.T("gen.verify_windows_total",
                                           total=f"{self._verify_total:,}"))
        self._refresh_verify_estimate()
        return self._verify_total

    def _verify_error(self, key):
        messagebox.showerror(self.T("gen.dialog_title"),
                             self.T(f"gen.verify_error_{key}"))
        return None

    def _verify_values(self):
        """{base_exponent, window_m, max_windows, threads} for the script, or None after an
        error dialog."""
        floor = verify_plan.parse_int(self._verify_vars["base_exponent"].get(), 0)
        if floor is None:
            return self._verify_error("base_exponent")
        width_exp = verify_plan.parse_int(self._verify_vars["width_exp"].get(),
                                          verify_plan.WIDTH_EXP_MIN)
        if width_exp is None or width_exp > verify_plan.WIDTH_EXP_MAX:
            return self._verify_error("width_exp")
        typed = self._verify_vars["max_windows"].get()
        total = verify_plan.window_count(self._get_portal_folder(), floor, width_exp)
        if total == 0:
            self._refresh_verify_count()
            return self._verify_error("no_windows")
        max_windows = verify_plan.max_windows_arg(typed, total)
        if max_windows is None:
            return self._verify_error("max_windows")
        threads_text = self._verify_vars["threads"].get()
        cpu_count = (estimate_wsl_available_cpu_count()
                     if threads_text.strip().lower() == verify_plan.THREADS_MAX.lower()
                     else None)
        threads = verify_plan.resolve_threads(threads_text,
                                              self._loop_vars["workers"].get(), cpu_count)
        if threads is None:
            return self._verify_error("threads")
        values = {"base_exponent": floor, "window_m": 10 ** width_exp,
                  "max_windows": max_windows, "threads": threads,
                  "method": self._verify_vars["method"].get()}
        if values["method"] != verify_plan.METHOD_SIEVE:
            return values
        pass_exp = verify_plan.parse_int(self._verify_vars["pass_exp"].get(), width_exp)
        if pass_exp is None or pass_exp > verify_plan.WIDTH_EXP_MAX:
            return self._verify_error("pass_exp")
        return dict(values, pass_numbers=10 ** pass_exp)

    def _on_run_verify(self):
        if self._verify_runner is not None and self._verify_runner.is_running():
            return
        if self._other_engine_is_running("verify"):
            return
        values = self._verify_values()
        if values is None:
            return
        self._generation_settings["verify"] = {
            key: self._verify_vars[key].get().strip() for key in _STORED_FIELDS}
        save_generation_settings(ui_state_dynamic.STORE, self._generation_settings)
        portal = self._get_portal_folder()
        run_guard.clear_stop_request(portal)
        method = values["method"]
        if method == verify_plan.METHOD_SIEVE:
            env = []
            argv = build_v73_verify_argv(values["base_exponent"], values["threads"],
                                         values["window_m"], values["max_windows"],
                                         values["pass_numbers"])
        else:
            knobs = engine_options.resolve(self._generation_settings["loop"]).knobs
            env = [(engine_options.PT1_B_ENV, str(knobs["pt1_b"])),
                   (engine_options.PT1_CHUNK_KB_ENV, str(knobs["pt1_chunk_kb"]))]
            argv = build_pt1_verify_argv(values["base_exponent"], values["threads"],
                                         values["window_m"], values["max_windows"])
        log_path, exit_path, _run_id = generation_log_paths(portal, "verify")
        cmd = build_wsl_logged_command(argv, log_path, exit_path, portal, extra_env=env)
        self.verify_console.append(self._new_run_separator())
        self._verify_output_queue = queue.Queue()
        self._verify_runner = self._new_wsl_runner(cmd, log_path, exit_path,
                                                   self._verify_output_queue,
                                                   kill_pattern=VERIFY_SCRIPT_PATTERNS[method])
        self._verify_runner.start()
        self.verify_run_btn.configure(state="disabled")
        self.verify_stop_btn.configure(state="normal")
        self._lock_other_run_buttons("verify")
        self.verify_status_label.set(self.T("common.running"))
        self.verify_console.show()

    def _on_stop_verify(self):
        """Writes the stop request (the script ends after its current slab or pass), then
        kills the run if it is still alive after VERIFY_STOP_GRACE_MS."""
        if self._verify_runner is None or not self._verify_runner.is_running():
            return
        run_guard.write_stop_request(self._get_portal_folder())
        self.verify_status_label.set(self.T("gen.verify_stopping"))
        if self._verify_stop_after_id is None:
            self._verify_stop_after_id = self.after(VERIFY_STOP_GRACE_MS,
                                                    self._force_stop_verify)

    def _force_stop_verify(self):
        self._verify_stop_after_id = None
        if self._verify_runner is not None and self._verify_runner.is_running():
            self._verify_runner.stop()
            self.verify_status_label.set(self.T("common.stopping"))

    def _on_verify_finished(self, _returncode=None):
        if self._verify_stop_after_id is not None:
            self.after_cancel(self._verify_stop_after_id)
            self._verify_stop_after_id = None
        run_guard.clear_stop_request(self._get_portal_folder())
        self._refresh_verify_count()
        self.reload_primes_tree()
        self.reload_benchmark_log()
        self._unlock_other_run_buttons()

    def _poll_verify_output(self):
        self._drain_output_queue(self._verify_output_queue, self.verify_console,
                                 self.verify_run_btn, self.verify_stop_btn,
                                 self.verify_status_label, on_exit=self._on_verify_finished)
        self.after(150, self._poll_verify_output)
