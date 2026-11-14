"""
quick_gen_runs.py -- QuickGenRuns, the launchers behind the Quick generation panel:
Generate/Stop, one apply-and-run pair per engine (pipeline loop, primesieve, Hybrid,
cudasieve, direct orchestrator window range), gap filling, and the multi-step storage fill
(start_storage_fill).

A GenerationTab mixin: it uses the widgets, Variables and runner state that GenerationTab
and its other mixins set up, so it is never instantiated on its own.
"""
import queue

from tkinter import messagebox

from ..core.storage import digit_count_floor, LOW_FLOOR_CUTOFF
from . import engine_options
from .engine_argv import (build_primesieve_argv, build_primesieve_native_argv, build_hybrid_argv, build_hybrid_narrow_argv,
                          build_cudasieve_argv, build_orchestrator_direct_argv)
from .quick_number import _eval_quick_number
from .window_planning import (QUICK_GEN_MAX_WINDOW_WIDTH, count_existing_windows,
                              find_continuation_target_idx, find_first_gap_target_idx,
                              _trim_existing_from_target_idx_range, hybrid_window_for_number,
                              hybrid_window_for_floor_index, _floor_window_count,
                              PRIMESIEVE_MAX_STOP)
from .wsl_command import generation_log_paths, build_wsl_logged_command


class QuickGenRuns:
    def _on_quick_generate_or_stop_clicked(self):
        """Dual-function dispatch for the Quick-gen 'Generate' button: while a
        pipeline run is in flight, this button IS the stop control
        (its label already reads Stop -- see _on_run_loop); otherwise it's the
        normal generate path. Checked the same way _on_quick_generate_clicked already
        guards against double-launch (self._loop_runner.is_running())."""
        if self._loop_runner is not None and self._loop_runner.is_running():
            self._on_stop_loop()
        else:
            self._on_quick_generate_clicked()

    def _apply_loop_params_and_run(self, base_exponent, run_count, window_count_per_run):
        """Writes the computed low-level parameters into the EXISTING orchestrator_
        loop_v2 form fields (self._loop_vars) and fires the same launch path the
        low-level "Run" button uses (_on_run_loop) -- reuses its validation,
        settings-persistence, WslLoggedRunner wiring and live-output panel verbatim
        instead of duplicating any of it (the log pane right below this panel is
        where the real output shows up). n_instances/write_files/
        compute_sieving_primes_count/workers/batches_per_worker/window_m are left
        exactly as they already are in the low-level form -- the app translates the
        quick-gen inputs into width/window-count in the form below, but quick-gen
        only ever decides base_exponent/run_count/window_count_per_run, nothing
        else."""
        self._loop_vars["base_exponent"].set(str(base_exponent))
        self._loop_vars["run_count"].set(str(run_count))
        self._loop_vars["window_count_per_run"].set(str(window_count_per_run))
        self._on_run_loop()

    def _apply_primesieve_params_and_run(self, base_exponent, target_idx_start,
                                          window_count_per_run):
        """Quick-gen 'primesieve' mode's counterpart to _apply_loop_params_and_run() --
        this engine has no low-level form of its own (see prime_sieve_primesieve.py's
        simpler CLI, module header), so there are no self._loop_vars-equivalent fields
        to round-trip through first; the three values already fully determine the WSL
        command (see build_primesieve_argv/_on_run_primesieve). write_files is still
        read from the SAME checkbox the low-level orchestrator form uses
        (self._loop_write_files_var) -- one general "write files vs. count-only
        diagnostic" concept shared across every engine this app can launch, not
        something specific to orchestrator_loop_v2.py."""
        self._on_run_primesieve(base_exponent, target_idx_start, window_count_per_run)

    def _on_run_primesieve(self, base_exponent, target_idx_start, window_count_per_run):
        """Launch path for prime_sieve_primesieve.py -- deliberately reuses the SAME
        self._loop_runner/self._loop_output_queue/self.loop_console/self.loop_run_btn/
        self.loop_stop_btn/self.loop_status_label/_poll_loop_output/_on_loop_finished
        plumbing _on_run_loop() uses, rather than a separate runner+console+queue
        triple: only one Generation run can be in flight at a time regardless of which
        engine it uses (_on_quick_generate_or_stop_clicked already guards on
        self._loop_runner.is_running() for exactly this reason), and the live-output
        console/Stop control/tree-refresh-on-finish behavior are all engine-agnostic --
        duplicating that machinery for one more script would only add a second place
        every future change to it has to be made twice."""
        if (self._loop_runner is not None and self._loop_runner.is_running()
                or self._other_engine_is_running("loop")):
            messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_already_running"))
            return
        # primesieve mode's own stdout never prints granular progress (a single
        # blocking libprimesieve call, no per-batch lines) -- see
        # _set_gen_progress_bar()'s own docstring for why the shared bar is left
        # inactive for this engine rather than faked.
        self._gen_progress_bar_active = False
        write_files = self._loop_write_files_var.get()
        native = self.quick_primesieve_native_var.get()
        try:
            if native:
                # The primesieve program itself (print or count), always a benchmark
                # run; write_files does not apply.
                argv = build_primesieve_native_argv(
                    base_exponent, target_idx_start, window_count_per_run,
                    QUICK_GEN_MAX_WINDOW_WIDTH, self.quick_primesieve_native_mode_var.get())
                script = "primesieve_native.py"
            else:
                argv = build_primesieve_argv(
                    base_exponent, target_idx_start, window_count_per_run,
                    QUICK_GEN_MAX_WINDOW_WIDTH, write_files)
                script = "prime_sieve_primesieve.py"
            log_path, exit_path, _run_id = generation_log_paths(self._get_portal_folder(), "primesieve")
            cmd = build_wsl_logged_command(argv, log_path, exit_path, self._get_portal_folder())

            self.loop_console.append(self._new_run_separator())
            self._loop_output_queue = queue.Queue()
            self._start_loop_runner(cmd, log_path, exit_path, script,
                                    base_exponent, first_target_idx=target_idx_start,
                                    window_m=QUICK_GEN_MAX_WINDOW_WIDTH)
        except Exception as e:  # noqa: BLE001 -- see _on_run_loop's own comment on
            # why this is caught and surfaced instead of silently swallowed.
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

    def _on_run_hybrid(self, base_exponent, iterations, width_windows, filter_prime_count):
        """Launch the separate reference hybrid runner through the normal Generation UI.

        It shares the one-run-at-a-time console, Stop control and completion refresh
        with every other engine.  It never routes through v4: the child process first
        verifies that storage really supplies a continuous MAIN prefix.
        """
        if (self._loop_runner is not None and self._loop_runner.is_running()
                or self._other_engine_is_running("loop")):
            messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_already_running"))
            return
        self._reset_gen_progress_bar_for_new_run()
        self._gen_loop_run_count = iterations
        self._gen_loop_iteration = None
        self._gen_step_total = None
        write_files = self._loop_write_files_var.get()
        try:
            argv = build_hybrid_argv(base_exponent, iterations, width_windows, filter_prime_count, write_files)
            log_path, exit_path, _run_id = generation_log_paths(self._get_portal_folder(), "hybrid")
            cmd = build_wsl_logged_command(argv, log_path, exit_path, self._get_portal_folder())
            self.loop_console.append(self._new_run_separator())
            self._loop_output_queue = queue.Queue()
            self._start_loop_runner(cmd, log_path, exit_path, "hybrid_sieve.py",
                                    base_exponent)
        except Exception as e:  # noqa: BLE001 -- launch errors belong in the GUI.
            self._loop_runner = None
            self._gen_loop_run_count = None
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

    def _hybrid_selected_range(self):
        target_kind = self.quick_hybrid_target_var.get()
        value = _eval_quick_number(self.quick_hybrid_value_var.get())
        floor = _eval_quick_number(self.quick_hybrid_target_floor_var.get())
        if target_kind != "n" and (floor is None or floor < 0):
            raise ValueError(self.T("quick.hybrid_error_negative_floor"))
        if target_kind == "n":
            start, end = hybrid_window_for_number(value)
        elif target_kind == self.T("quick.hybrid_target_continue_floor"):
            # Low floors each own exactly one whole-floor PGS2 window.
            # Continuing past it means the first window of the next floor,
            # never a fictitious index 1 inside the completed floor.
            target_idx = find_continuation_target_idx(
                self._get_portal_folder(), floor, QUICK_GEN_MAX_WINDOW_WIDTH, engine=self._selected_engine())
            while floor < LOW_FLOOR_CUTOFF and target_idx >= 1:
                floor += 1
                target_idx = find_continuation_target_idx(
                    self._get_portal_folder(), floor, QUICK_GEN_MAX_WINDOW_WIDTH, engine=self._selected_engine())
            start, end = hybrid_window_for_floor_index(floor, target_idx)
        elif target_kind == self.T("quick.hybrid_target_fill_gap"):
            start, end = hybrid_window_for_floor_index(
                floor, find_first_gap_target_idx(self._get_portal_folder(), floor,
                                                 QUICK_GEN_MAX_WINDOW_WIDTH, engine=self._selected_engine()))
        else:
            start, end = hybrid_window_for_floor_index(floor, value)
        return start, end

    def _on_run_hybrid_narrow(self, start, end, main_cap, filter_prime_count):
        """Launch the explicit one-window Hybrid experiment through the usual console."""
        if (self._loop_runner is not None and self._loop_runner.is_running()
                or self._other_engine_is_running("loop")):
            messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_already_running"))
            return
        self._reset_gen_progress_bar_for_new_run()
        self._gen_loop_run_count = 1
        self._gen_loop_iteration = None
        self._gen_step_total = None
        try:
            argv = build_hybrid_narrow_argv(start, end, main_cap, filter_prime_count,
                                            self._loop_write_files_var.get())
            log_path, exit_path, _run_id = generation_log_paths(self._get_portal_folder(), "hybrid")
            cmd = build_wsl_logged_command(argv, log_path, exit_path, self._get_portal_folder())
            self.loop_console.append(self._new_run_separator())
            self._loop_output_queue = queue.Queue()
            self._start_loop_runner(cmd, log_path, exit_path, "hybrid_sieve.py",
                                    digit_count_floor(start))
        except Exception as e:  # noqa: BLE001
            self._loop_runner = None
            messagebox.showerror(self.T("gen.dialog_title"), self.T("gen.error_launch_failed", error=str(e)))
            return
        self.loop_run_btn.configure(state="disabled")
        self.loop_stop_btn.configure(state="normal")
        self._lock_other_run_buttons("loop")
        self.loop_status_label.set(self.T("common.running"))
        for panel in self._quick_panels:
            panel["generate_btn"].configure(text=self.T("common.stop"))
        self._show_loop_terminal()

    def _apply_cudasieve_params_and_run(self, base_exponent, target_idx_start,
                                         window_count_per_run):
        """Quick-gen 'cudasieve' mode's counterpart to _apply_primesieve_params_and_run()
        -- identical reasoning; this engine also has no low-level form of its own (see
        prime_sieve_cudasieve.py's module header), just launching
        prime_sieve_cudasieve.py (`_on_run_cudasieve`) instead of
        prime_sieve_primesieve.py."""
        self._on_run_cudasieve(base_exponent, target_idx_start, window_count_per_run)

    def _on_run_cudasieve(self, base_exponent, target_idx_start, window_count_per_run):
        """Launch path for prime_sieve_cudasieve.py -- reuses the SAME
        self._loop_runner/self._loop_output_queue/self.loop_console/self.loop_run_btn/
        self.loop_stop_btn/self.loop_status_label/_poll_loop_output/_on_loop_finished
        plumbing _on_run_primesieve() uses -- see that method's own docstring for why
        (only one Generation run can be in flight at a time regardless of engine)."""
        if (self._loop_runner is not None and self._loop_runner.is_running()
                or self._other_engine_is_running("loop")):
            messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_already_running"))
            return
        # cudasieve mode's own stdout has no per-batch progress lines Atlas parses
        # yet either (the CUDASieve CLI itself does print per-prime progress to its
        # terminal, but this project doesn't read that back -- deferred, see
        # _set_gen_progress_bar()'s own docstring), so the shared bar stays inactive
        # here too, same reasoning as primesieve mode just above.
        self._gen_progress_bar_active = False
        write_files = self._loop_write_files_var.get()
        try:
            argv = build_cudasieve_argv(
                base_exponent, target_idx_start, window_count_per_run,
                QUICK_GEN_MAX_WINDOW_WIDTH, write_files)
            log_path, exit_path, _run_id = generation_log_paths(self._get_portal_folder(), "cudasieve")
            cmd = build_wsl_logged_command(argv, log_path, exit_path, self._get_portal_folder())

            self.loop_console.append(self._new_run_separator())
            self._loop_output_queue = queue.Queue()
            self._start_loop_runner(cmd, log_path, exit_path, "prime_sieve_cudasieve.py",
                                    base_exponent, first_target_idx=target_idx_start,
                                    window_m=QUICK_GEN_MAX_WINDOW_WIDTH)
        except Exception as e:  # noqa: BLE001 -- see _on_run_loop's own comment on
            # why this is caught and surfaced instead of silently swallowed.
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

    def _apply_orchestrator_direct_params_and_run(self, base_exponent, target_idx_start,
                                                    window_count_per_run):
        """Fallback counterpart to _apply_primesieve_params_and_run() for
        _offer_generate_missing_prime_window(), used only when the requested window
        falls beyond libprimesieve's own uint64 ceiling (PRIMESIEVE_MAX_STOP) -- see
        build_orchestrator_direct_argv()'s own docstring for why orchestrator_v3.py
        itself (not its loop wrapper) is the right engine there. Reads
        write_files/compute_sieving_primes_count from the same low-level form fields
        primesieve mode and the main 'Run' button already use
        (self._loop_write_files_var/self._loop_count_sieving_var), and
        workers/batches_per_worker from self._loop_vars with a safe fallback of 1 each
        if that form hasn't been touched/validated yet -- unlike _on_run_loop()'s own
        validation, this call site must never block a search-triggered generation on
        an unrelated low-level field being blank or malformed."""
        self._on_run_orchestrator_direct(base_exponent, target_idx_start, window_count_per_run)

    def _on_run_orchestrator_direct(self, base_exponent, target_idx_start, window_count_per_run):
        """Launch path for orchestrator_v3.py run DIRECTLY (see
        build_orchestrator_direct_argv()) -- reuses the exact same
        self._loop_runner/self._loop_output_queue/self.loop_console/... plumbing
        _on_run_loop()/_on_run_primesieve() both already use, for the same
        one-runner-at-a-time reasoning _on_run_primesieve()'s own docstring gives."""
        if (self._loop_runner is not None and self._loop_runner.is_running()
                or self._other_engine_is_running("loop")):
            messagebox.showerror(self.T("quick.dialog_title"), self.T("quick.error_already_running"))
            return
        # orchestrator_v3.py run directly still calls prime_sieve_v3/v4/v4_1's own
        # generate_floor_windows(), same granular "[+] Progress: ..." lines as the
        # loop path -- re-enable and reset the shared bar, same reasoning as
        # _on_run_loop()'s own comment.
        self._reset_gen_progress_bar_for_new_run()
        lo = 10 ** base_exponent + target_idx_start * QUICK_GEN_MAX_WINDOW_WIDTH
        hi = lo + window_count_per_run * QUICK_GEN_MAX_WINDOW_WIDTH
        self._pi_count_notice(base_exponent, lo, hi, hi)
        write_files = self._loop_write_files_var.get()
        use_pi_seed = self._loop_use_pi_seed_var.get()
        # Effective flag: either checkbox on means "compute pi(L_final)" -- see the
        # mutual-exclusion comment above the two Checkbuttons in _build_loop_section.
        compute_sieving = self._loop_count_sieving_var.get() or use_pi_seed

        def _positive_int_or(key, default):
            raw = self._loop_vars[key].get().strip()
            return int(raw) if raw.isdigit() and int(raw) > 0 else default

        workers = _positive_int_or("workers", 1)
        batches_per_worker = _positive_int_or("batches_per_worker", 1)
        choice, bad_key = self._engine_fields.choice(window_count_per_run)
        if choice is None:
            messagebox.showerror(
                self.T("gen.dialog_title"), self.T("gen.error_field_int", field=bad_key))
            return
        if not self.confirm_ram_budget(choice, window_count_per_run, QUICK_GEN_MAX_WINDOW_WIDTH):
            return
        try:
            argv = build_orchestrator_direct_argv(
                base_exponent, target_idx_start, window_count_per_run,
                QUICK_GEN_MAX_WINDOW_WIDTH, write_files, compute_sieving,
                workers, batches_per_worker)
            log_path, exit_path, _run_id = generation_log_paths(self._get_portal_folder(), "orchdirect")
            cmd = build_wsl_logged_command(
                argv, log_path, exit_path, self._get_portal_folder(),
                use_known_pi_seed=use_pi_seed,
                extra_env=engine_options.launch_env(choice, verify=self._pt1_verify_choice()))

            self.loop_console.append(self._new_run_separator())
            self._loop_output_queue = queue.Queue()
            self._start_loop_runner(cmd, log_path, exit_path, "orchestrator_v3.py",
                                    base_exponent, engine=choice.engine,
                                    first_target_idx=target_idx_start, window_m=QUICK_GEN_MAX_WINDOW_WIDTH)
        except Exception as e:  # noqa: BLE001 -- see _on_run_loop's own comment on
            # why this is caught and surfaced instead of silently swallowed.
            self._loop_runner = None
            messagebox.showerror(self.T("gen.dialog_title"), self.T(
                "gen.error_launch_failed", error=str(e)))
            return
        self._start_run_eta(self.run_time_iterations(
            choice.engine, base_exponent, window_count_per_run, write_files, [lo]))
        self.loop_run_btn.configure(state="disabled")
        self.loop_stop_btn.configure(state="normal")
        self._lock_other_run_buttons("loop")
        self.loop_status_label.set(self.T("common.running"))
        for panel in self._quick_panels:
            panel["generate_btn"].configure(text=self.T("common.stop"))
        self._show_loop_terminal()

    def _try_fill_quick_gen_gap(self, floor_value, existing_count, width_mult):
        """Shared "fill gaps first" check for Floor mode's blank-starting-point path
        AND Exploration mode (see quick_floor_fill_gaps_var's own comment in
        _init_quick_generation_state -- the SAME toggle/variable drives both, matching
        Floor mode's own behavior exactly). Only changes anything when
        floor_value genuinely HAS a gap: find_first_gap_target_idx() returns the exact
        same value as existing_count (find_continuation_target_idx()) otherwise, so
        the "no gap" case returns False and callers fall straight through to their own
        normal continue-from-highest logic, unchanged. Returns True (and has ALREADY
        launched something + set quick_status_var) if a gap was found and filled;
        False otherwise -- callers should `return` immediately on True, exactly like
        any other terminal branch in _on_quick_generate_clicked.

        Deliberately launches at most width_mult windows into the gap -- ONE
        iteration's worth, never more, even from Exploration mode's own multi-
        iteration call site (which has no equivalent single-shot cap otherwise).
        Exploration's normal (non-gap) launches go through orchestrator_loop_v2.py
        specifically so each subprocess's own batch gets a bounded window_count_per_run
        -- orchestrator_v3.py's own batch_size is simply set equal to whatever
        window_count it receives (see that file's main(), batch_size = window_count),
        with NO internal chunking of its own. Collapsing gap-filling into one direct
        _launch_direct_window_range() call sized at iterations*width_mult instead of
        just width_mult would silently hand a single subprocess a batch far larger
        than Exploration's own Iterations field was ever meant to allow through in one
        step, reintroducing exactly the per-batch RAM risk multi-iteration launches
        exist to avoid (under-filling a wide gap is preferred over one oversized
        launch). A gap wider than
        width_mult is filled incrementally instead -- click by click, or automatically
        over repeated blank-Floor auto-detect passes -- using the same
        quick.note_gap_partial the caller already surfaces for this."""
        if not self.quick_floor_fill_gaps_var.get():
            return False
        gap_target_idx = find_first_gap_target_idx(
            self._get_portal_folder(), floor_value, QUICK_GEN_MAX_WINDOW_WIDTH, engine=self._selected_engine())
        if gap_target_idx >= existing_count:
            return False
        floor_window_count = _floor_window_count(floor_value)
        gap_remaining = floor_window_count - gap_target_idx
        capped_width = min(width_mult, gap_remaining)
        reaches_existing = gap_target_idx + capped_width >= existing_count
        gap_start = 10 ** floor_value + gap_target_idx * QUICK_GEN_MAX_WINDOW_WIDTH
        self.quick_status_var.set(self.T(
            "quick.summary_floor_fill_gap", floor=floor_value,
            width_mult=capped_width,
            width_total=f"{capped_width * QUICK_GEN_MAX_WINDOW_WIDTH:,}",
            gap_start=f"{gap_start:,}",
            existing_count=count_existing_windows(self._get_portal_folder(), floor_value),
            added_count=capped_width)
            + (self.T("quick.note_gap_partial") if not reaches_existing else ""))
        # _launch_direct_window_range() (not _apply_loop_params_and_run()) since this
        # is a literal target_idx -- it also trims any edge overlap with what's
        # already on disk, though none is expected here since gap_target_idx is by
        # definition the first MISSING window.
        self._launch_direct_window_range(floor_value, gap_target_idx, capped_width)
        return True

    def _launch_direct_window_range(self, floor, target_idx_start, window_count):
        """Shared dispatch for every caller that already knows its own literal
        [target_idx_start, target_idx_start + window_count) target (Range mode, Floor
        mode with a starting point, Goldbach's 'generate missing range' offer -- see
        _quick_gen_plan_literal_range()'s own docstring for how that target_idx_start
        is computed) -- writes starting EXACTLY there, never backfilling anything
        before it, unlike orchestrator_loop_v2.py's own continuation-only wrapper
        (build_loop_argv()), which has no notion of an arbitrary start position at
        all. Picks whichever engine can actually reach that magnitude: primesieve
        mode if the whole requested range still fits under libprimesieve's own uint64
        ceiling (PRIMESIEVE_MAX_STOP), else orchestrator_v3.py launched directly (see
        build_orchestrator_direct_argv()'s own docstring) -- the exact same
        ceiling-aware choice _offer_generate_missing_prime_window() already makes for
        the search flow's own missing-fragment offer.

        Trims against what's ALREADY on disk first (see
        _trim_existing_from_target_idx_range()'s own docstring) -- every engine this
        app can launch overwrites unconditionally with no existence check of its own,
        so this is the one place that avoids redundantly re-sieving/rewriting windows
        the caller's own request happens to overlap.

        Returns "covered" (nothing left to generate), "launched" (a run started) or
        "failed" (the engine refused or failed to start; it has already said why)."""
        trimmed_start, trimmed_count = _trim_existing_from_target_idx_range(
            self._get_portal_folder(), floor, target_idx_start, window_count, QUICK_GEN_MAX_WINDOW_WIDTH, engine=self._selected_engine())
        if trimmed_count <= 0:
            self.quick_status_var.set(self.T("quick.status_range_fully_covered"))
            return "covered"
        runner_before = self._loop_runner
        range_end_abs = 10 ** floor + (trimmed_start + trimmed_count) * QUICK_GEN_MAX_WINDOW_WIDTH
        if range_end_abs - 1 > PRIMESIEVE_MAX_STOP:
            self._apply_orchestrator_direct_params_and_run(floor, trimmed_start, trimmed_count)
        else:
            self._apply_primesieve_params_and_run(floor, trimmed_start, trimmed_count)
        if self._loop_runner is not None and self._loop_runner is not runner_before:
            return "launched"
        return "failed"

    def start_storage_fill(self, launches, on_finished):
        """Runs plan_storage_fill's launches one after another through
        _launch_direct_window_range (one Generation run at a time, as everywhere in
        this tab): each finished run starts the next step (_on_storage_fill_run_
        finished), a step already on disk is skipped at once. on_finished(True) after
        the last step; on_finished(False) as soon as a launch fails or a run exits
        non-zero (an error or Stop), with the rest of the plan dropped. Returns False,
        launching nothing, while another run is in flight."""
        if (self._loop_runner is not None and self._loop_runner.is_running()
                or self._other_engine_is_running("loop")):
            return False
        self._pending_storage_fill = {"launches": list(launches), "on_finished": on_finished}
        self._advance_storage_fill()
        return True

    def _advance_storage_fill(self):
        pending = self._pending_storage_fill
        while pending["launches"]:
            floor, target_idx_start, window_count = pending["launches"].pop(0)
            result = self._launch_direct_window_range(floor, target_idx_start, window_count)
            if result == "launched":
                return
            if result == "failed":
                self._finish_storage_fill(False)
                return
        self._finish_storage_fill(True)

    def _finish_storage_fill(self, success):
        on_finished = self._pending_storage_fill["on_finished"]
        self._pending_storage_fill = None
        on_finished(success)

    def _on_storage_fill_run_finished(self, returncode):
        """_on_loop_finished's hook: the next storage-fill step, or the end of it."""
        if self._pending_storage_fill is None:
            return
        if returncode not in (None, 0) or self._loop_stop_requested:
            self._finish_storage_fill(False)
            return
        self._advance_storage_fill()
