"""
loop_section.py -- LoopSection, Section A of the Generation tab: the
orchestrator_loop_v2.py pipeline form (collapsed behind Advanced, with the sieve engine
fields), its console, and the Run/finish/poll handlers that update the floor totals and
the other tabs once a run ends.

A GenerationTab mixin: it uses the widgets, Variables and runner state that GenerationTab
and its other mixins set up, so it is never instantiated on its own.
"""
import queue

import tkinter as tk
from tkinter import ttk, messagebox

from ..core.progress_bar_owner import release_progress_bar
from ..core.storage import bump_floor_total, load_totals_cache, save_totals_cache
from ..benchmark.benchmark import read_benchmark_log
from .generation_console import GenerationConsole
from . import engine_options
from .engine_fields import EngineFields
from .engine_argv import build_loop_argv
from primeatlas.core import ui_state_dynamic
from .generation_settings import remember_generation_field, save_generation_settings
from .window_planning import compute_totals_bumps_from_new_rows
from .wsl_command import generation_log_paths, build_wsl_logged_command


class LoopSection:
    def _build_loop_section(self, sections):
        """Section A: the pipeline form, its Run/Stop row and its console."""
        # --- Section A: orchestrator_loop_v2.py (generation pipeline) ------------
        loop_outer = ttk.Labelframe(
            sections, text=self.T("gen.section_loop"))
        loop_outer.pack(fill="x")

        # These are advanced settings, so base_exponent/run_count/
        # n_instances/window_count_per_run/workers/batches_per_worker/window_m (plus
        # the two checkboxes) collapse behind a toggle button, collapsed by default.
        #
        # loop_btn_row (Run/Stop/status) is hidden along with them: the raw
        # Run button only makes sense once you can actually SEE what it'll run
        # with, so loop_btn_row now lives INSIDE the same collapsible block as the
        # fields, not next to it -- one toggle hides/shows both together. The normal
        # way to run is now the Quick-gen "Generate" button above
        # (_on_quick_generate_or_stop_clicked), which doubles as Stop while a run is
        # in flight (see _on_run_loop/_on_loop_finished).
        loop_advanced_row = ttk.Frame(loop_outer)
        loop_advanced_row.pack(fill="x", padx=8, pady=(6, 0))
        self._loop_advanced_visible = False
        self.loop_advanced_toggle_btn = ttk.Button(
            loop_advanced_row, text=self.T("gen.advanced_show"),
            command=self._on_toggle_loop_advanced)
        self.loop_advanced_toggle_btn.pack(side="left")

        loop_advanced_content = ttk.Frame(loop_outer)
        self._loop_advanced_content = loop_advanced_content
        # NOT packed here -- starts collapsed, see _on_toggle_loop_advanced(). Packed
        # (when shown) with before=self.loop_console.toggle_row so it always lands
        # right below the toggle button, above the console's own toggle row.

        loop_form = ttk.Frame(loop_advanced_content)
        loop_form.pack(fill="x")

        self._loop_vars = {}
        loop_settings = self._generation_settings["loop"]

        def add_loop_field(row, col, key, label, width=10):
            ttk.Label(loop_form, text=label).grid(
                row=row, column=col * 2, sticky="w", padx=(0, 4), pady=2)
            var = tk.StringVar(value=str(loop_settings.get(key, "")))
            ttk.Entry(loop_form, textvariable=var, width=width).grid(
                row=row, column=col * 2 + 1, sticky="w", padx=(0, 20), pady=2)
            self._loop_vars[key] = var
            remember_generation_field("loop", key, var)

        add_loop_field(0, 0, "base_exponent", self.T("gen.field_base_exponent"))
        add_loop_field(0, 1, "run_count", self.T("gen.field_run_count"))
        add_loop_field(1, 0, "n_instances", self.T("gen.field_n_instances"))
        add_loop_field(1, 1, "window_count_per_run", self.T("gen.field_window_count"))
        add_loop_field(2, 0, "workers", self.T("gen.field_workers"))
        # Auto button for "workers", same idea as Quick generation's own RAM-based
        # Auto button for window count (_on_quick_auto_width_clicked) -- probes
        # WSL's available CPU count and fills the field with it (see
        # _on_workers_auto_clicked's own docstring). Occupies raw column 2;
        # batches_per_worker sits one field-slot to the right (col=2 -> raw columns 4/5).
        ttk.Button(loop_form, text=self.T("quick.auto_button"), width=6,
                   command=self._on_workers_auto_clicked).grid(
            row=2, column=2, sticky="w", padx=(0, 8), pady=2)
        add_loop_field(2, 2, "batches_per_worker", self.T("gen.field_batches"))
        # window_m: was hardcoded to 10,000,000 in three separate scanner/orchestrator
        # files -- now a real CLI-overridable parameter, threaded all the way down to
        # prime_sieve_v3.py (see build_loop_argv()'s docstring for the full chain and
        # the "only safe to change for a floor with no existing data" caveat).
        add_loop_field(3, 0, "window_m", self.T("gen.field_window_m"), width=14)

        self._loop_write_files_var = tk.BooleanVar(
            value=bool(loop_settings.get("write_files", True)))
        self._loop_write_files_cb = ttk.Checkbutton(
            loop_form, text=self.T("gen.check_write_files"), variable=self._loop_write_files_var)
        self._loop_write_files_cb.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        if hasattr(self, "_sync_primesieve_native_controls"):
            self._sync_primesieve_native_controls()
        # These two checkboxes are mutually exclusive ALTERNATIVES for computing
        # pi(L_final), not an independent base+modifier pair (picking
        # one must uncheck the other; both off means "don't compute pi(L_final) at all").
        # Effective compute_sieving_primes_count sent to the scripts is the OR of the two
        # (see _collect_loop_settings_from_form()/_on_run_orchestrator_direct()) --
        # "count sieving primes" means "full recount, no seed", "use Wikipedia seed" means
        # "count, but seeded" -- see count_sieving_primes_cached()'s own docstring
        # (prime_sieve_v4_1.py) and build_wsl_logged_command()'s docstring (wsl_command.py)
        # for the full mechanism.
        use_pi_seed_initial = bool(loop_settings.get("use_known_pi_seed", False))
        self._loop_count_sieving_var = tk.BooleanVar(
            value=bool(loop_settings.get("compute_sieving_primes_count", False))
            and not use_pi_seed_initial)
        ttk.Checkbutton(
            loop_form, text=self.T("gen.check_count_sieving"),
            variable=self._loop_count_sieving_var).grid(
            row=4, column=2, columnspan=2, sticky="w", pady=(6, 0))
        self._loop_use_pi_seed_var = tk.BooleanVar(value=use_pi_seed_initial)
        ttk.Checkbutton(
            loop_form, text=self.T("gen.check_use_pi_seed"),
            variable=self._loop_use_pi_seed_var).grid(
            row=5, column=0, columnspan=4, sticky="w", pady=(0, 0))

        def _on_count_sieving_toggle(*_args):
            if self._loop_count_sieving_var.get() and self._loop_use_pi_seed_var.get():
                self._loop_use_pi_seed_var.set(False)

        def _on_use_pi_seed_toggle(*_args):
            if self._loop_use_pi_seed_var.get() and self._loop_count_sieving_var.get():
                self._loop_count_sieving_var.set(False)

        # trace_add fires on every write, but each handler only ever acts when BOTH vars
        # are True at once (impossible to sustain past this callback), so there's no
        # infinite ping-pong -- setting the other var to False triggers its own trace,
        # which sees its own condition (get() and other.get()) already false and no-ops.
        self._loop_count_sieving_var.trace_add("write", _on_count_sieving_toggle)
        self._loop_use_pi_seed_var.trace_add("write", _on_use_pi_seed_toggle)
        remember_generation_field("loop", "write_files", self._loop_write_files_var)
        remember_generation_field(
            "loop", "compute_sieving_primes_count", self._loop_count_sieving_var)
        remember_generation_field("loop", "use_known_pi_seed", self._loop_use_pi_seed_var)

        # Sieve engine and its knobs (rows 6-10); the Quick-gen Width cap follows the engine.
        self._engine_fields = EngineFields(loop_form, self.T, loop_settings, row=6)
        self._engine_fields.on_engine_change(self._sync_quick_width_caps)
        self._sync_quick_width_caps()
        # Auto profile fields show the set of the run width edited last: Windows / iteration,
        # or the Quick-gen Floor / Exploration Width it is copied from at launch.
        for width_var in (self._loop_vars["window_count_per_run"],
                          self.quick_floor_width_var, self.quick_explore_width_var):
            width_var.trace_add(
                "write", lambda *_, var=width_var: self._engine_fields.set_windows(var.get()))
        self._engine_fields.set_windows(self._loop_vars["window_count_per_run"].get())

        loop_btn_row = ttk.Frame(loop_advanced_content)
        loop_btn_row.pack(fill="x", pady=(6, 0))
        self.loop_run_btn = ttk.Button(loop_btn_row, text=self.T("common.run"), command=self._on_run_loop)
        self.loop_run_btn.pack(side="left")
        self.loop_stop_btn = ttk.Button(
            loop_btn_row, text=self.T("common.stop"), command=self._on_stop_loop, state="disabled")
        self.loop_stop_btn.pack(side="left", padx=(6, 0))
        self.loop_status_label = tk.StringVar(value=self.T("common.ready"))
        ttk.Label(loop_btn_row, textvariable=self.loop_status_label).pack(
            side="left", padx=(12, 0))

        # Each terminal pane (loop and constellation) has its own collapse toggle,
        # collapsed whenever its script isn't running: own toggle, collapsed on every
        # app start (no persisted state), auto-expanded by _show_loop_terminal() the
        # moment a run actually starts (_on_run_loop), and deliberately left alone
        # (never auto-collapsed) once it finishes -- see _on_loop_finished. Toggle/
        # clear/open-in-new-window live together in GenerationConsole (primeatlas/
        # generation_console.py), reused identically by this section and the
        # constellation-finder section below. The detached window additionally gets
        # its own copy of the Quick-gen panel (see _build_detached_quick_panel), bound
        # to the SAME shared StringVars as the embedded one, so both always show the
        # same values and a run started from either place behaves identically.
        self.loop_console = GenerationConsole(
            loop_outer, self.T, height=20,
            extra_controls_builder=self._build_detached_quick_panel)
        self.loop_output = self.loop_console.text
        # See _build_scrollable_container's own docstring: scrolling this console's
        # own ScrolledText must not ALSO scroll the whole generation_body underneath it.
        self._register_scroll_exclude(self.loop_console.text.frame)

        self._loop_runner = None
        self._init_run_guard(self._new_wsl_runner)
        self._loop_output_queue = queue.Queue()
        self._benchmark_rows_before_run = None  # row count of benchmark_log.csv as of
        # the moment the currently-running (or just-launched) self._loop_runner started
        # -- set by _on_run_loop()/_on_run_primesieve()/_on_run_orchestrator_direct()
        # right before starting the subprocess, consumed by _on_loop_finished()'s
        # _bump_totals_from_finished_run() to know which rows in the CSV are new since
        # then. See storage.py's module docstring: benchmark_log.csv already logs each
        # run's total_primes/windows_written/bytes_written/write_files, so the persisted
        # totals cache is updated from those rows instead of a full per-floor rescan.

    def _on_toggle_loop_advanced(self):
        """Shows/hides loop_advanced_content -- the fields AND the raw Run/
        Stop/status row together (see _build_loop_section()'s comment on
        Section A) -- packed with before=self.loop_console.toggle_row so it always
        lands back in the same slot (between the toggle button and the console's own
        toggle row) regardless of how many times it's been forgotten/re-shown."""
        if self._loop_advanced_visible:
            self._loop_advanced_content.pack_forget()
            self._loop_advanced_visible = False
            self.loop_advanced_toggle_btn.configure(text=self.T("gen.advanced_show"))
        else:
            self._loop_advanced_content.pack(
                fill="x", padx=8, pady=(0, 4), before=self.loop_console.toggle_row)
            self._loop_advanced_visible = True
            self.loop_advanced_toggle_btn.configure(text=self.T("gen.advanced_hide"))

    def _show_loop_terminal(self):
        """Force-expands the pipeline console if it's currently collapsed -- called
        from _on_run_loop() the moment a run actually starts. No-op if already visible
        (e.g. the user had opened it manually)."""
        self.loop_console.show()

    def _collect_loop_settings_from_form(self):
        """Reads + validates every orchestrator_loop_v2 form field. Returns a dict of
        parsed values on success, or None (after a messagebox explaining which field
        is wrong) if anything fails validation -- mirrors the existing "Search"
        fields' isdigit()-based validation pattern elsewhere in this file."""
        # base_exponent (the floor) is the ONE field here allowed to be 0 -- floor 0
        # is [10^0, 10^1) = [1, 10), a legitimate floor (holds 2, 3, 5, 7 among
        # others), not a placeholder/unset value. Every other field genuinely needs
        # to be strictly positive (0 windows/workers/batches/runs/instances doesn't
        # mean anything).
        zero_allowed_fields = {"base_exponent"}
        int_fields = ("base_exponent", "run_count", "n_instances", "window_count_per_run",
                      "workers", "batches_per_worker", "window_m")
        parsed = {}
        for key in int_fields:
            raw = self._loop_vars[key].get().strip()
            minimum = 0 if key in zero_allowed_fields else 1
            if not raw.isdigit() or int(raw) < minimum:
                messagebox.showerror(
                    self.T("gen.dialog_title"), self.T("gen.error_field_int", field=key))
                return None
            parsed[key] = int(raw)
        parsed["write_files"] = self._loop_write_files_var.get()
        parsed["use_known_pi_seed"] = self._loop_use_pi_seed_var.get()
        # Effective flag sent to the scripts: either checkbox being on means "compute
        # pi(L_final)" -- see the mutual-exclusion comment above the two Checkbuttons in
        # _build_loop_section for why these are alternatives, not independent toggles.
        parsed["compute_sieving_primes_count"] = (
            self._loop_count_sieving_var.get() or parsed["use_known_pi_seed"])
        choice, bad_key = self._engine_fields.choice(parsed["window_count_per_run"])
        if choice is None:
            messagebox.showerror(
                self.T("gen.dialog_title"), self.T("gen.error_field_int", field=bad_key))
            return None
        parsed["engine_choice"] = choice
        return parsed

    def _on_run_loop(self):
        if (self._loop_runner is not None and self._loop_runner.is_running()
                or self._other_engine_is_running("loop")):
            messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_already_running"))
            return
        # The old batched engine (orchestrator_v3.py via orchestrator_loop_v2.py)
        # DOES print granular "[+] Progress: ..." lines -- re-enable and reset the
        # shared bar in case a previous run left it off (primesieve/cudasieve mode,
        # see _set_gen_progress_bar()'s own docstring) or left it full (a previous
        # run's own 100%-done state).
        self._reset_gen_progress_bar_for_new_run()
        parsed = self._collect_loop_settings_from_form()
        if parsed is None:
            return

        try:
            self._generation_settings["loop"] = {
                "base_exponent": str(parsed["base_exponent"]),
                "run_count": str(parsed["run_count"]),
                "n_instances": str(parsed["n_instances"]),
                "write_files": parsed["write_files"],
                "compute_sieving_primes_count": parsed["compute_sieving_primes_count"],
                "use_known_pi_seed": parsed["use_known_pi_seed"],
                "window_count_per_run": str(parsed["window_count_per_run"]),
                "workers": str(parsed["workers"]),
                "batches_per_worker": str(parsed["batches_per_worker"]),
                "window_m": str(parsed["window_m"]),
                **self._engine_fields.settings(),
            }
            save_generation_settings(ui_state_dynamic.STORE, self._generation_settings)

            argv = build_loop_argv(
                parsed["base_exponent"], parsed["run_count"], parsed["n_instances"],
                parsed["write_files"], parsed["compute_sieving_primes_count"],
                parsed["window_count_per_run"], parsed["workers"], parsed["batches_per_worker"],
                parsed["window_m"])
            log_path, exit_path, _run_id = generation_log_paths(self._get_portal_folder(), "loop")
            cmd = build_wsl_logged_command(
                argv, log_path, exit_path, self._get_portal_folder(),
                use_known_pi_seed=parsed["use_known_pi_seed"],
                extra_env=engine_options.launch_env(parsed["engine_choice"]))

            self.loop_console.append(self._new_run_separator())
            self._loop_output_queue = queue.Queue()
            self._start_loop_runner(cmd, log_path, exit_path, "orchestrator_loop_v2.py",
                                    parsed["base_exponent"],
                                    engine=parsed["engine_choice"].engine, window_m=parsed["window_m"])
        except Exception as e:  # noqa: BLE001 -- without this, a launch failure is
            # swallowed by Tk's default callback exception handling (printed to a
            # console the user usually can't see; the GUI looks unchanged). Surface it.
            self._loop_runner = None
            messagebox.showerror(self.T("gen.dialog_title"), self.T(
                "gen.error_launch_failed", error=str(e)))
            return
        self.loop_run_btn.configure(state="disabled")
        self.loop_stop_btn.configure(state="normal")
        self._lock_other_run_buttons("loop")
        self.loop_status_label.set(self.T("common.running"))
        # Generate doubles as Stop while this runs (see
        # _on_quick_generate_or_stop_clicked), and the terminal auto-expands the
        # moment a run actually starts -- reset back to normal in
        # _on_loop_finished() once it exits. Looped over every currently-open
        # Quick-gen panel instance (embedded + detached copy, if any).
        for panel in self._quick_panels:
            panel["generate_btn"].configure(text=self.T("common.stop"))
        self._show_loop_terminal()

    def _bump_totals_from_finished_run(self):
        """Reads benchmark_log.csv fresh and folds every NEW row written since
        self._benchmark_rows_before_run's snapshot (see that attribute's own comment in
        __init__) directly into the persisted totals cache via storage.bump_floor_total(),
        instead of relying on the next full per-floor rescan to notice the new windows --
        see storage.py's own module docstring for the feature this is one of three write-
        path hooks for (generation here; storage_integrate.py's merge and
        delete_manager.py's floor delete are the other two). The actual row-filtering/
        parsing decision is generation.compute_totals_bumps_from_new_rows() -- see that
        function's own docstring for why it's split out.

        Called BEFORE reload_primes_tree() in _on_loop_finished() -- reload's own
        PrimesTreeCoordinator._scan() reads the totals cache fresh from disk every time
        (see that module's own docstring), so by the time the tree repopulates it already
        reflects whatever this method just bumped, with no extra rescan needed for that to
        be true."""
        portal_folder = self._get_portal_folder()
        before = self._benchmark_rows_before_run
        self._benchmark_rows_before_run = None
        if before is None:
            return
        _fieldnames, rows = read_benchmark_log(portal_folder)
        bumps = compute_totals_bumps_from_new_rows(rows, before)
        if not bumps:
            return
        cache = load_totals_cache(portal_folder)
        for base_exponent, delta_count, delta_files, delta_bytes in bumps:
            bump_floor_total(cache, base_exponent, delta_count, delta_files, delta_bytes)
        save_totals_cache(portal_folder, cache)

    def _on_loop_finished(self, _returncode=None):
        """_drain_output_queue's on_exit callback for the loop queue -- resets every
        open Quick-gen panel's 'Generate' button back from its temporary 'Stop'
        label now that nothing is running. Deliberately does NOT touch the console's
        collapse state -- it stays expanded so the final log is still visible after
        the run finishes.

        Also re-runs reload_primes_tree() -- the SAME rebuild the manual Refresh
        button on the Prime numbers tab triggers -- so newly written/regenerated
        windows show up there without the person having to notice the run finished
        and click Refresh (low-floor completions/regenerations included -- see
        LOW_FLOOR_CUTOFF), the same way _set_portal_folder does after a storage-path
        change."""
        for panel in self._quick_panels:
            panel["generate_btn"].configure(text=self.T("quick.generate_button"))
        self._settle_finished_loop_run()
        # Loop/hybrid/orchestrator's own subprocess encompasses its whole
        # multi-iteration run internally -- unlike constellation's batch chaining,
        # _on_loop_finished ALWAYS means this session is genuinely over, so it's
        # always safe to re-enable the other two engines here -- see
        # _lock_other_run_buttons()'s own docstring.
        self._unlock_other_run_buttons()
        self._bump_totals_from_finished_run()
        # Releases this run's claim on the shared totals_progress bar (see
        # progress_bar_owner.py) BEFORE reload_primes_tree() below -- that call
        # chains into TotalsSearchCoordinator.show_cached_grand_total(), whose own
        # reset-to-empty write needs the bar free to actually take effect instead of
        # silently no-op'ing against a run that (as far as ownership is concerned)
        # hasn't relinquished it yet.
        release_progress_bar(self.totals_progress, self)
        self.reload_primes_tree()
        self._reload_time_simulation_log()
        self.reload_benchmark_log()

        # A search-triggered "generate the missing window" run (see
        # _offer_generate_missing_prime_window()) just finished -- re-run the SAME
        # search now that the fragment should be on disk. Runs regardless of the
        # exit code: a failed/stopped run just means the re-search comes back empty
        # again, same as any other genuinely-not-found case, rather than needing a
        # separate error path here.
        if self._pending_search_after_prime_gen is not None:
            pending = self._pending_search_after_prime_gen
            self._pending_search_after_prime_gen = None
            self._start_search_job(pending["kind"], pending["base_exponent"], pending["number"])

        # Mirrors the block above, for a Visualize/decompose "generate the
        # missing range" offer instead of a prime/constellation search miss
        # (see _goldbach_offer_generate_missing_range) -- re-queues whichever
        # of the two ops actually reported the gap, now that generation should
        # have filled it. "viz" re-reads n/row-page/od-do fresh from the still-
        # open Toplevel's own entries (_goldbach_queue_viz); "decompose" reuses
        # self._goldbach_decompose_current_n/current_pmax/page, already set by
        # the original _on_goldbach_viz_decompose click and left untouched by
        # the failed attempt (see _goldbach_queue_decompose_page's docstring).
        # Runs regardless of exit code, same reasoning as the prime-window
        # block: a failed/stopped run just means the retry reports the same
        # gap again.
        if self._pending_goldbach_retry_op is not None:
            retry_op = self._pending_goldbach_retry_op
            self._pending_goldbach_retry_op = None
            if retry_op == "viz":
                self.research_goldbach_tab_widget.retry_viz()
            elif retry_op == "decompose":
                self.research_goldbach_tab_widget.retry_decompose()

        self._on_storage_fill_run_finished(_returncode)

    def _poll_loop_output(self):
        self._drain_output_queue(self._loop_output_queue, self.loop_console,
                                  self.loop_run_btn, self.loop_stop_btn, self.loop_status_label,
                                  on_exit=self._on_loop_finished)
        self.after(150, self._poll_loop_output)
