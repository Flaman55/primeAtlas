"""
verify_section.py -- VerifySection, Section D of the Generation tab: proves pt1's P windows
of one floor's store, so they become D/P, by one of two methods: the pt1.1 proof
(prime_sieve/pt1_verify_store.py) or the v7.3 sieve (prime_sieve/v73_verify_store.py, engine
v7.2's sieve, one pass per verification window).

It verifies the floor's first island of P files (verify_width.py): the Width field sets the
numbers of one verification window (whole files, one file up to the island; for the v7.3 sieve
up to its RAM cap too), the Split field how many windows the island splits into (the island's
size next to it); a change of either recounts the other. "Verify now" sets how many of those
windows a run proves (all of them by default). A width typed outside its range takes the
nearest end, one between rounds down to whole files (on leaving the field, a floor or method
change, Run), and it is shown short and exact (verify_width.width_text(): 1e8, 9e7, 2.5e8); its
arrows and the wheel step by one file. A typed split gives ceil(files / split) files per
window; its arrows step to the next split that changes the width. Auto picks the width by the
method. The free RAM is read by
Auto and by a v7.3 Run; the last reading also caps the passes of the verification after a pt1
run.

The store-side counterpart of the pt1 engine's "verify P -> D" checkbox: with the checkbox
off, pt1 writes P windows at its full speed and this section proves them later, like the
k-tuple search reads the windows the generation wrote. The proof uses the pt1 knobs B and
chunk size of the pipeline form (engine_options.launch_env()); the sieve runs on v7.2's
default knobs. The method and the v7.3 RAM cap also serve the pipeline form's pt1 checkbox
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
from ..core import cpu_dynamic, number_field, number_format
from ..core.threads_field import ThreadsField
from ..core.info_tip import InfoTip
from ..benchmark.benchmark import read_benchmark_log
from . import engine_options, run_guard, verify_estimate, verify_plan, verify_width
from .engine_argv import build_pt1_verify_argv, build_v73_verify_argv
from .generation_console import GenerationConsole
from .generation_settings import remember_generation_field, save_generation_settings
from .quick_gen_panel import _floor_spinbox
from .wsl_command import build_wsl_logged_command, generation_log_paths
from . import wsl_resources
from ..core.wrap_label import WrapLabel

VERIFY_SCRIPT_PATTERNS = run_verify.SCRIPTS
# A slab of the default size takes about a minute of proofs on floor 29 (arbitrary margin).
VERIFY_STOP_GRACE_MS = 180_000
VERIFY_COUNT_DELAY_MS = 300
# The Windows field is not stored: it is recounted from the store (verify_width.py).
_STORED_FIELDS = ("base_exponent", "width", "threads", "method")


def _bind_steps(box, step):
    """The arrows and the wheel of `box` call step(+1 / -1) instead of the Spinbox's own
    numeric step (the wheel spins between -from and -to directly, not via <<Increment>>)."""
    for event, direction in (("<<Increment>>", 1), ("<<Decrement>>", -1),
                             ("<Button-4>", 1), ("<Button-5>", -1)):
        box.bind(event, lambda _e, d=direction: step(d))
    box.bind("<MouseWheel>", lambda e: step(1 if e.delta > 0 else -1))


class VerifySection:
    def _build_verify_section(self, sections):
        """Section D: floor, window width with Auto, the window count (recounted from the
        store) and threads; the method and the estimate; Run/Stop, console."""
        outer = ttk.Labelframe(sections, text=self.T("gen.section_verify"))
        outer.pack(fill="x", pady=(6, 0))
        self._verify_frame = outer
        self._engine_fields.knob_hint_labels["pt1_verify"].bind(
            "<Button-1>", lambda _e: self._scroll_page.scroll_to(outer))
        hint_row = ttk.Frame(outer)
        hint_row.pack(fill="x", padx=8, pady=(6, 0))
        WrapLabel(hint_row, text=self.T("gen.verify_hint"), style="Hint.TLabel").pack(side="left")
        InfoTip(hint_row, lambda: self.T("gen.info_verify")).label.pack(side="left", padx=(4, 0))

        settings = self._generation_settings["verify"]
        self._verify_vars = {key: tk.StringVar(value=str(settings.get(key, "")))
                             for key in _STORED_FIELDS}
        if self._verify_vars["method"].get() not in verify_plan.METHODS:
            self._verify_vars["method"].set(verify_plan.METHOD_PROOF)
        self._verify_vars["max_windows"] = tk.StringVar(value="")
        for key in _STORED_FIELDS:
            remember_generation_field("verify", key, self._verify_vars[key])
        self._verify_island = None
        self._verify_total = 0
        self._verify_sieve_cap = verify_width.DEFAULT_SIEVE_CAP
        self._verify_count_after_id = None

        def label(parent, key):
            ttk.Label(parent, text=self.T(f"gen.verify_field_{key}")).pack(side="left")

        form = ttk.Frame(outer)
        form.pack(fill="x", padx=8, pady=(4, 4))
        label(form, "base_exponent")
        _floor_spinbox(form, self._verify_vars["base_exponent"], 6, self.T).pack(
            side="left", padx=(6, 20))
        label(form, "width")
        self._verify_width_box = ttk.Spinbox(form, textvariable=self._verify_vars["width"],
                                             width=16)
        number_field.attach(self._verify_width_box, self.T, "field_tip.verify_width", minimum=1)
        self._verify_width_box.pack(side="left", padx=(6, 4))
        _bind_steps(self._verify_width_box, self._step_verify_width)
        for event in ("<FocusOut>", "<Return>"):
            self._verify_width_box.bind(event, lambda _e: self._refresh_verify_count(), add="+")
        self._verify_auto_btn = ttk.Button(form, text=self.T("quick.auto_button"),
                                           command=self._on_verify_auto_width)
        self._verify_auto_btn.pack(side="left", padx=(0, 6))
        self._verify_width_text = tk.StringVar()
        ttk.Label(form, textvariable=self._verify_width_text, style="Hint.TLabel").pack(
            side="left")

        split_row = ttk.Frame(outer)
        split_row.pack(fill="x", padx=8, pady=(0, 4))
        label(split_row, "split")
        # Not stored: the width is, and the split follows from it.
        self._verify_split_var = tk.StringVar(value="")
        self._verify_split_box = ttk.Spinbox(split_row, textvariable=self._verify_split_var,
                                             width=8)
        number_field.attach(self._verify_split_box, self.T, "field_tip.verify_split", minimum=1)
        self._verify_split_box.pack(side="left", padx=(6, 4))
        _bind_steps(self._verify_split_box, self._step_verify_split)
        for event in ("<FocusOut>", "<Return>"):
            self._verify_split_box.bind(event, lambda _e: self._commit_verify_split(), add="+")
        self._verify_island_text = tk.StringVar()
        ttk.Label(split_row, textvariable=self._verify_island_text, style="Hint.TLabel").pack(
            side="left")

        count_row = ttk.Frame(outer)
        count_row.pack(fill="x", padx=8, pady=(0, 4))
        label(count_row, "max_windows")
        self._verify_windows_box = ttk.Spinbox(
            count_row, from_=1, to=1, increment=1,
            textvariable=self._verify_vars["max_windows"], width=8)
        number_field.attach(self._verify_windows_box, self.T, "field_tip.verify_max_windows",
                            minimum=1)
        self._verify_windows_box.pack(side="left", padx=(6, 4))
        self._verify_total_text = tk.StringVar()
        ttk.Label(count_row, textvariable=self._verify_total_text, style="Hint.TLabel").pack(
            side="left", padx=(0, 20))
        label(count_row, "threads")
        # Auto shows the workers it stands for and follows the pipeline form's field.
        threads = ThreadsField(
            count_row, self.T, self._verify_vars["threads"],
            words=(verify_plan.THREADS_AUTO, verify_plan.THREADS_MAX),
            over=verify_plan.THREADS_MAX, width=9, purpose="field_tip.verify_threads",
            resolve=lambda word: verify_plan.resolve_threads(
                word, self._loop_vars["workers"].get(), cpu_dynamic.WSL_CPUS))
        self._loop_vars["workers"].trace_add("write", lambda *_: threads.refresh())
        threads.pack(side="left", padx=(6, 0))

        method_row = ttk.Frame(outer)
        method_row.pack(fill="x", padx=8, pady=(0, 4))
        label(method_row, "method")
        self._verify_method_names = {method: self.T(f"gen.verify_method_{method}")
                                     for method in verify_plan.METHODS}
        self._verify_method_text = tk.StringVar(
            value=self._verify_method_names[self._verify_vars["method"].get()])
        method_box = ttk.Combobox(method_row, textvariable=self._verify_method_text,
                                  values=list(self._verify_method_names.values()),
                                  state="readonly", width=14)
        method_box.pack(side="left", padx=(6, 20))
        method_box.bind("<<ComboboxSelected>>", lambda _e: self._on_verify_method_chosen())
        self._verify_estimate_text = tk.StringVar()
        ttk.Label(method_row, textvariable=self._verify_estimate_text,
                  style="Hint.TLabel").pack(side="left")

        self._verify_vars["base_exponent"].trace_add("write",
                                                     lambda *_: self._schedule_verify_count())
        self._verify_vars["width"].trace_add("write",
                                             lambda *_: self._schedule_verify_count(False))
        self._verify_vars["max_windows"].trace_add(
            "write", lambda *_: self._schedule_verify_count(estimate_only=True))
        self._loop_write_files_var.trace_add("write", lambda *_: self._sync_pt1_verify_lock())

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

        self.verify_console = GenerationConsole(outer, self.T, place="generation.verify")
        self._register_scroll_exclude(self.verify_console.text.frame)
        self._verify_runner = None
        self._verify_output_queue = queue.Queue()
        self._verify_stop_after_id = None
        self._sync_pt1_verify_lock()
        self._on_verify_method_chosen()
        # P files can come or go outside this section (the primes tree, another store
        # folder): showing the main tab that holds it recounts the island.
        notebook = self.master
        while notebook is not None and not isinstance(notebook, ttk.Notebook):
            notebook = notebook.master
        if notebook is not None:
            notebook.bind("<<NotebookTabChanged>>",
                          lambda _e: self._recount_verify_if_shown(notebook), add="+")

    def _recount_verify_if_shown(self, notebook):
        page = notebook.select()
        if page and (str(self) + ".").startswith(str(page) + "."):
            self._refresh_verify_count()

    def _sync_verify_run_state(self):
        """Run is greyed out on a floor without P files and while a run holds the Run
        buttons (_lock_other_run_buttons())."""
        ready = self._verify_island is not None and self._run_lock_engine is None
        self.verify_run_btn.configure(state="normal" if ready else "disabled")

    def _schedule_verify_count(self, fit=True, estimate_only=False):
        """Recounts the island once typing or wheeling pauses: fitting the width into its
        range (a floor change) or not (typing in the Width field, which fits on leaving it),
        or only the estimate (the Windows field)."""
        if self._verify_count_after_id is not None:
            self.after_cancel(self._verify_count_after_id)
        if estimate_only:
            job = self._refresh_verify_estimate
        else:
            job = lambda: self._refresh_verify_count(fit)  # noqa: E731
        self._verify_count_after_id = self.after(VERIFY_COUNT_DELAY_MS, job)

    def _verify_method(self):
        return self._verify_vars["method"].get()

    def _on_verify_method_chosen(self):
        """Stores the chosen method and fits the width into its range."""
        chosen = self._verify_method_text.get()
        method = next((m for m, name in self._verify_method_names.items() if name == chosen),
                      verify_plan.METHOD_PROOF)
        self._verify_vars["method"].set(method)
        self._refresh_pt1_verify_hint()
        self._refresh_verify_count()

    def _probe_verify_ram(self):
        """Reads the free RAM into the v7.3 cap (DEFAULT_SIEVE_CAP when unreadable)."""
        self._verify_sieve_cap = verify_width.sieve_cap(
            wsl_resources.estimate_free_ram_bytes(), 1)
        self._refresh_pt1_verify_hint()
        return self._verify_sieve_cap

    def _fitted_verify_width(self, island=None):
        """The Width field's value fitted to the island's range, None for invalid text."""
        return verify_width.fit_width(self._verify_vars["width"].get(),
                                      island or self._verify_island, self._verify_method(),
                                      self._verify_sieve_cap)

    def _step_verify_width(self, direction):
        """An arrow: the next round width (verify_width.step_width()), within the range."""
        island = self._verify_island
        if island is not None:
            current = self._fitted_verify_width() or island.file_width
            self._verify_vars["width"].set(verify_width.width_text(verify_width.step_width(
                island, current, direction, self._verify_method(), self._verify_sieve_cap)))
        return "break"

    def _commit_verify_split(self):
        """A typed split (leaving the field, Enter): the width it stands for, then a recount
        shows the split whole files allow. Invalid text stays (red)."""
        island = self._verify_island
        if island is None:
            return
        width = verify_width.width_for_split(self._verify_split_var.get(), island,
                                             self._verify_method(), self._verify_sieve_cap)
        if width is None:
            return
        self._verify_vars["width"].set(verify_width.width_text(width))
        self._refresh_verify_count()

    def _step_verify_split(self, direction):
        """An arrow on the split: the next split that changes the width, within the range."""
        island = self._verify_island
        if island is not None:
            current = self._fitted_verify_width() or island.file_width
            self._verify_vars["width"].set(verify_width.width_text(verify_width.step_split(
                island, current, direction, self._verify_method(), self._verify_sieve_cap)))
        return "break"

    def _on_verify_auto_width(self):
        """Auto: the width by the method (verify_width.auto_width()); v7.3 reads the RAM."""
        if self._verify_island is None:
            return
        if self._verify_method() == verify_plan.METHOD_SIEVE:
            self._probe_verify_ram()
        self._verify_vars["width"].set(verify_width.width_text(verify_width.auto_width(
            self._verify_island, self._verify_method(), self._verify_sieve_cap)))
        self._refresh_verify_count()

    def _verify_after_pt1_run(self, run_info):
        """A pt1 run that wrote files (stopped ones too): this section takes its floor and runs
        Auto, so the P windows it left show at once, or none when all were proved. Other
        engines and a Benchmark run leave floor and width as they are."""
        info = run_info or {}
        if info.get("engine") != "pt1" or not info.get("write_files"):
            return
        self._verify_vars["base_exponent"].set(str(info["base_exponent"]))
        self._refresh_verify_count()
        self._on_verify_auto_width()

    def _pt1_verify_choice(self):
        """(method, pass_numbers) of this section for the verification after a pt1 run: the
        v7.3 passes take the RAM cap."""
        return self._verify_method(), self._verify_sieve_cap

    def _refresh_pt1_verify_hint(self):
        """Names this section's method (and the sieve's RAM cap) next to the pt1 checkbox."""
        if self._verify_method() == verify_plan.METHOD_SIEVE:
            text = self.T("gen.pt1_verify_hint_sieve",
                          pass_numbers=verify_width.width_text(self._verify_sieve_cap))
        else:
            text = self.T("gen.pt1_verify_hint_proof")
        self._engine_fields.knob_hint_vars["pt1_verify"].set(text)

    def _sync_pt1_verify_lock(self):
        """A Benchmark run (write_files off) writes no P window to verify: the pt1 checkbox
        is greyed out then, the reason in its tooltip."""
        self._engine_fields.set_knob_lock(
            "pt1_verify",
            None if self._loop_write_files_var.get() else self.T("gen.pt1_verify_benchmark_lock"))

    def _chosen_verify_windows(self, width):
        """The Windows field's count, at most every window; every window when it is invalid."""
        typed = verify_plan.parse_int(self._verify_vars["max_windows"].get(), 1)
        total = verify_width.window_total(self._verify_island, width)
        return min(typed, total) if typed is not None else total

    def _refresh_verify_estimate(self):
        """Sets and returns the estimate of both methods for the chosen windows: the proof
        over their numbers, the sieve over the same files in passes of at most its cap."""
        self._verify_count_after_id = None
        floor = verify_plan.parse_int(self._verify_vars["base_exponent"].get(), 0)
        island = self._verify_island
        width = self._fitted_verify_width() if island is not None else None
        sizes, passes = [], []
        if width is not None:
            sizes = verify_width.window_sizes(island, width, self._chosen_verify_windows(width))
            chosen = verify_width.Island(island.start, island.file_width,
                                         sum(sizes) // island.file_width)
            sieve_width = verify_width.fit_width(str(width), chosen, verify_plan.METHOD_SIEVE,
                                                 self._verify_sieve_cap)
            passes = verify_width.window_sizes(chosen, sieve_width, chosen.files)
        portal = self._get_portal_folder()
        _fields, rows = read_benchmark_log(portal) if portal else ([], [])
        text = self.T("gen.verify_estimate",
                      proof=verify_estimate.duration_text(
                          verify_estimate.proof_seconds(rows, sum(sizes))),
                      sieve=verify_estimate.duration_text(
                          verify_estimate.sieve_seconds(rows, floor, passes)),
                      passes=len(passes))
        self._verify_estimate_text.set(text)
        return text

    def _refresh_verify_count(self, fit=True):
        """Reads the floor's first island and sets the Windows field to every window of the
        chosen width (a smaller value proves only the first ones); returns that total. fit:
        the width is fitted into its range (blank: Auto's width). Without a P file there is
        nothing to pick: Windows empty and greyed out, "none" beside it, Width, Auto and Run
        greyed out."""
        if self._verify_count_after_id is not None:
            self.after_cancel(self._verify_count_after_id)
        self._verify_count_after_id = None
        floor = verify_plan.parse_int(self._verify_vars["base_exponent"].get(), 0)
        island = verify_width.store_island(self._get_portal_folder(), floor)
        self._verify_island = island
        state = "normal" if island is not None else "disabled"
        for widget in (self._verify_width_box, self._verify_auto_btn, self._verify_split_box,
                       self._verify_windows_box):
            widget.configure(state=state)
        width = None
        if island is not None:
            width_var = self._verify_vars["width"]
            if fit and not width_var.get().strip():
                width = verify_width.auto_width(island, self._verify_method(),
                                                self._verify_sieve_cap)
            else:
                width = self._fitted_verify_width()
            if fit and width is not None and width_var.get() != verify_width.width_text(width):
                width_var.set(verify_width.width_text(width))
        if island is None:
            self._verify_total = 0
            self._verify_vars["max_windows"].set("")
            self._verify_total_text.set(self.T("gen.verify_windows_none"))
            self._verify_width_text.set("")
            self._verify_split_var.set("")
            self._verify_island_text.set("")
        elif width is not None:
            self._verify_total = verify_width.window_total(island, width)
            self._verify_windows_box.configure(to=self._verify_total)
            self._verify_vars["max_windows"].set(str(self._verify_total))
            self._verify_split_var.set(str(self._verify_total))
            self._verify_total_text.set(self.T("gen.verify_windows_total",
                                               total=number_format.whole(self._verify_total)))
            low, high = verify_width.width_range(island, self._verify_method(),
                                                 self._verify_sieve_cap)
            self._verify_island_text.set(self.T(
                "gen.verify_island", numbers=verify_width.width_text(island.numbers),
                files=number_format.whole(island.files), low=verify_width.width_text(low),
                high=verify_width.width_text(high)))
            self._verify_width_text.set(self.T(
                "gen.verify_width_files", files=number_format.whole(width // island.file_width),
                file_width=verify_width.width_text(island.file_width)))
        # The field writes above schedule recounts of their own; this one already counts them.
        if self._verify_count_after_id is not None:
            self.after_cancel(self._verify_count_after_id)
        self._refresh_verify_estimate()
        self._sync_verify_run_state()
        return self._verify_total

    def _verify_error(self, key):
        messagebox.showerror(self.T("gen.dialog_title"),
                             self.T(f"gen.verify_error_{key}"))
        return None

    def _verify_values(self):
        """{base_exponent, window_m (the file width), max_windows (the files of the chosen
        windows), threads, method[, pass_numbers (the width)]} for the script, or None after
        an error dialog. P files gone since the last recount: None without a dialog, the
        recount greys Run out. A v7.3 run reads the free RAM first; the width is fitted (and
        shown so) before it is used."""
        floor = verify_plan.parse_int(self._verify_vars["base_exponent"].get(), 0)
        if floor is None:
            return self._verify_error("base_exponent")
        island = verify_width.store_island(self._get_portal_folder(), floor)
        if island is None:
            self._refresh_verify_count()
            return None
        method = self._verify_method()
        if method == verify_plan.METHOD_SIEVE:
            self._probe_verify_ram()
        width = self._fitted_verify_width(island)
        if width is None:
            return self._verify_error("width")
        if self._verify_vars["width"].get() != verify_width.width_text(width):
            self._verify_vars["width"].set(verify_width.width_text(width))
        windows = verify_plan.parse_int(self._verify_vars["max_windows"].get(), 1)
        if windows is None:
            return self._verify_error("max_windows")
        threads_text = self._verify_vars["threads"].get()
        workers_text = self._loop_vars["workers"].get()
        auto = threads_text.strip().lower() == verify_plan.THREADS_AUTO.lower()
        cpu_count = (wsl_resources.read_wsl_cpus()
                     if threads_text.strip().lower() == verify_plan.THREADS_MAX.lower()
                     or auto and wsl_resources.wants_cpu_count(workers_text) else None)
        threads = verify_plan.resolve_threads(threads_text, workers_text, cpu_count)
        if threads is None:
            return self._verify_error("threads")
        values = {"base_exponent": floor, "window_m": island.file_width,
                  "max_windows": verify_width.files_for(island, width, windows),
                  "threads": threads, "method": method}
        if method != verify_plan.METHOD_SIEVE:
            return values
        return dict(values, pass_numbers=width)

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
        self.reload_primes_tree()
        self.reload_benchmark_log()
        self._unlock_other_run_buttons()

    def _poll_verify_output(self):
        self._drain_output_queue(self._verify_output_queue, self.verify_console,
                                 self.verify_run_btn, self.verify_stop_btn,
                                 self.verify_status_label, on_exit=self._on_verify_finished)
        self.after(150, self._poll_verify_output)
