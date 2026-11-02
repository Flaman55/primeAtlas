"""
run_progress.py -- GenerationRunProgress, what every Generation section shares while a run
is live: draining a runner's output queue into its console, the shared bottom progress bar
and status text parsed from the engines' output, the cross-engine Run button lock, and the
constellation elapsed/ETA suffix.

A GenerationTab mixin: it uses the widgets, Variables and runner state that GenerationTab
and its other mixins set up, so it is never instantiated on its own.
"""
import queue
import time

from tkinter import messagebox

from ..core.progress_bar_owner import claim_progress_bar
from .constellation_section import CONSTELLATION_BATCH_SIZE, CONSTELLATION_ETA_MIN_WINDOWS
from .generation import (
    format_duration_short, _LOOP_SESSION_DONE_RE, _LOOP_SESSION_START_RE,
    _LOOP_ITERATION_START_RE, _GEN_SIEVE_DONE_RE, _GEN_SIEVE_PROGRESS_RE,
    _GEN_CONST_PROGRESS_RE, _GEN_CONST_FLOOR_PROGRESS_RE, _GEN_PREP_DONE_RE,
    _GEN_HYBRID_STAGE_RE, _GEN_HYBRID_DONE_RE,
)


class GenerationRunProgress:
    def _drain_output_queue(self, q, console, run_btn, stop_btn, status_var, on_exit=None,
                             chunk_hook=None):
        """Shared by both Generation sections: drains whatever output
        a WslLoggedRunner has pushed onto `q` since the last poll into
        `console` (a GenerationConsole -- autoscrolling to the bottom is handled by
        its own append()), and on that runner's
        ("__exit__", returncode) sentinel, re-enables Run / disables Stop and
        reports the exit code. Same 150ms self.after() polling cadence as the floor-
        totals worker (_poll_totals_results) -- this method itself does NOT
        reschedule; each caller (_poll_loop_output / _poll_constellation_output) owns
        its own self.after() chain so the two sections' polling stays independent.

        An optional on_exit(returncode) callback fires right after the exit-sentinel
        handling above -- _poll_loop_output uses it to reset the Quick-gen 'Generate'
        button's temporary 'Stop' label (see _on_loop_finished, which ignores the
        returncode); _poll_constellation_output's own _on_constellation_finished DOES
        use the returncode, to decide whether to auto-relaunch a crashed run or chain
        the next batch (see _maybe_auto_retry_constellation()/_maybe_continue_
        constellation_batch()).

        An optional chunk_hook(chunk) fires for every plain-text chunk, right
        alongside _update_shared_progress_from_generation_chunk() below -- currently
        only _poll_constellation_output uses it (_scan_const_chunk_for_batch_marker(),
        to notice a "BATCH DONE -- N window(s) still remain" marker line as it streams
        in, ahead of on_exit needing that information once the run actually ends).
        Kept SEPARATE from _update_shared_progress_from_generation_chunk() rather than
        adding another regex branch to that already-dense, multi-engine-shared method
        -- this one is specific to a single section's own feature.

        Every plain-text chunk is ALSO fed to _update_shared_progress_from_generation_
        chunk() -- see that method's own docstring -- so the shared bottom bar reflects
        live generation/constellation-search progress, on top of the raw text staying
        visible in `console` exactly as before."""
        try:
            while True:
                item = q.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__exit__":
                    returncode = item[1]
                    run_btn.configure(state="normal")
                    stop_btn.configure(state="disabled")
                    if returncode is None:
                        status_var.set(self.T("common.error_starting_process"))
                    elif returncode == 0:
                        status_var.set(self.T("common.finished_ok"))
                    else:
                        status_var.set(self.T("common.finished_code", code=returncode))
                    if on_exit is not None:
                        on_exit(returncode)
                    continue
                console.append(item)
                self._update_shared_progress_from_generation_chunk(item)
                if chunk_hook is not None:
                    chunk_hook(item)
        except queue.Empty:
            pass

    def _set_gen_progress_bar(self, **configure_kwargs):
        """Applies a totals_progress.configure(**configure_kwargs) update, but ONLY
        when self._gen_progress_bar_active is True -- see that attribute's own
        __init__ comment. primesieve/cudasieve mode's own stdout never produces
        anything for _update_shared_progress_from_generation_chunk() to parse mid-run
        (both are a single blocking call with no per-batch reporting), so the only line of
        theirs that ever matches anything here is the final "[*] TOTAL PRIMES
        FOUND..." line (_GEN_SIEVE_DONE_RE) -- which, without this guard, would snap
        the bar straight from whatever it was already showing to "100% done", with
        nothing meaningful in between. Leave the
        bar alone entirely for those two engines rather than show a fake step count --
        the status TEXT (self.status.set(...), untouched by this helper) still updates
        normally either way, so the user isn't left with zero feedback, just no bar
        animation. Deferred, not fixed here: cudasieve's own CLI does print real
        per-prime progress to its terminal, Atlas just doesn't parse it yet."""
        if not self._gen_progress_bar_active:
            return
        # Claims the shared bar (see progress_bar_owner.py) -- a no-op if some OTHER
        # tab/coordinator currently owns it (e.g. a floor-totals scan or a Prime/
        # Constellations search), so this run's own progress just doesn't get painted
        # for that tick rather than stomping on whatever the user is actually
        # watching. The run's own state (self._gen_step_total etc.) keeps tracking
        # normally regardless -- this run's OWN next poll tick will reclaim the bar
        # the moment the other owner releases it.
        if not claim_progress_bar(self.totals_progress, self):
            return
        self.totals_progress.stop()
        self.totals_progress.configure(**configure_kwargs)

    def _other_engine_is_running(self, engine):
        """True if some engine OTHER than `engine` ('loop'/'const'/'ktuple') is
        currently mid-run. self._loop_runner (every Quick-gen/loop/hybrid/
        orchestrator-direct launch path), self._const_runner (Constellations
        search) and self._ktuple_runner (targeted k-tuple sieve) all funnel their
        live output through the SAME _update_shared_progress_from_generation_
        chunk(), which keeps its parsing state (self._gen_step_total, self._const_
        floor_total_windows, etc.) in plain instance attributes with no per-engine
        namespacing -- two of these running at once would silently corrupt each
        other's bar/status state. Used both as a belt-and-suspenders guard at each
        launch path's own entry point (see _lock_other_run_buttons()'s own
        docstring for why the button graying alone isn't sufficient) and to avoid
        needing it at all in the common case."""
        if engine != "loop" and self._loop_runner is not None and self._loop_runner.is_running():
            return True
        if engine != "const" and self._const_runner is not None and self._const_runner.is_running():
            return True
        if engine != "ktuple" and self._ktuple_runner is not None and self._ktuple_runner.is_running():
            return True
        return False

    def _lock_other_run_buttons(self, active_engine):
        """Disables the OTHER two engines' own Run buttons while `active_engine`
        ('loop'/'const'/'ktuple') is running -- see _other_engine_is_running()'s
        own docstring for why running two of these three at once is unsafe. Some
        non-button call paths (e.g. a search box's "generate missing window"
        auto-offer) invoke a launch method directly rather than through its own
        button, so _other_engine_is_running() is still checked at each launch
        path's own entry point too -- this graying is the visible half, not the
        only guard. Paired with _unlock_other_run_buttons(), called from each
        engine's own GENUINELY-finished handler (_on_loop_finished/_on_
        constellation_finished's own completion tail/_on_ktuple_finished) --
        never from a chained-batch/iteration continuation, which must keep the
        other two engines locked out for the whole session, not just one batch.

        The loop engine has TWO kinds of user-facing Run control -- the low-level
        Loop/Exploration section's own self.loop_run_btn, AND every open Quick-gen
        panel's own "Generate" button (self._quick_panels[i]["generate_btn"]),
        which all six loop-family launch paths (_on_run_loop/_on_run_primesieve/
        _on_run_hybrid/_on_run_hybrid_narrow/_on_run_cudasieve/_on_run_
        orchestrator_direct) share -- so locking OUT the loop engine (active_
        engine is 'const' or 'ktuple') must gray out both, not just the low-level
        one. While the loop engine is ITSELF the one running (active_engine ==
        'loop'), its own launch path already re-labels generate_btn to "Stop"
        (Generate doubles as Stop while it runs) and leaves it enabled -- this
        method must NOT touch it in that case, which is exactly what `!= 'loop'`
        already guards against below."""
        if active_engine != "loop":
            self.loop_run_btn.configure(state="disabled")
            for panel in self._quick_panels:
                panel["generate_btn"].configure(state="disabled")
        if active_engine != "const":
            self.const_run_btn.configure(state="disabled")
        if active_engine != "ktuple":
            self.ktuple_run_btn.configure(state="disabled")
            self.ktuple_auto_btn.configure(state="disabled")

    def _unlock_other_run_buttons(self):
        """Re-enables every engine's own Run button (see _lock_other_run_buttons()'s
        own docstring for why that includes every Quick-gen panel's "Generate"
        button, not just self.loop_run_btn). Safe to call unconditionally --
        _lock_other_run_buttons() only ever disabled the two engines that weren't
        the one launched, and this is only ever called once THAT one has
        genuinely finished (see its own callers), at which point none of the
        three can still be running."""
        self.loop_run_btn.configure(state="normal")
        for panel in self._quick_panels:
            panel["generate_btn"].configure(state="normal")
        self.const_run_btn.configure(state="normal")
        self.ktuple_run_btn.configure(state="normal")
        self.ktuple_auto_btn.configure(state="normal")

    def _reset_gen_progress_bar_for_new_run(self):
        """Called at the start of every Generation run-launch path that drives the
        shared totals_progress bar (loop/hybrid/hybrid-narrow/orchestrator-direct/
        constellation) -- (re-)activates it and resets it to an empty 0/1 determinate
        state. Without this, a value left over from whatever last used this SHARED bar
        (the totals scan, a Primes/Constellations search, or a previous run that
        finished at 100%) stays on screen until this run's own first real progress
        line arrives, which can be a visible delay for engines whose first progress
        report doesn't come immediately (e.g. constellation search's per-file lines)."""
        self._gen_progress_bar_active = True
        self._set_gen_progress_bar(mode="determinate", maximum=1, value=0)

    def _const_elapsed_eta_suffix(self, floor_total, floor_done):
        """Builds the " | running: Xh..., ETA: Y..." (or ETA-less) tail appended to the
        constellation search's own status text -- see CONSTELLATION_ETA_MIN_WINDOWS's
        comment in constellation_section.py and _const_session_start_time's comment in
        _build_constellation_section() for the two clocks this combines. Returns '' (no
        suffix at all) if the session clock hasn't started yet -- defensive only, since
        every caller only ever reaches
        this once a FLOOR PROGRESS line has already been seen, which itself only ever
        happens during an actual run."""
        if self._const_session_start_time is None:
            return ""
        elapsed_str = format_duration_short(time.time() - self._const_session_start_time)
        eta_str = None
        if self._const_eta_baseline_time is not None:
            done_since_baseline = floor_done - (self._const_eta_baseline_done or 0)
            rate_elapsed = time.time() - self._const_eta_baseline_time
            if done_since_baseline >= CONSTELLATION_ETA_MIN_WINDOWS and rate_elapsed > 0:
                rate = done_since_baseline / rate_elapsed  # windows/second
                if rate > 0:
                    eta_str = format_duration_short((floor_total - floor_done) / rate)
        if eta_str:
            return " " + self.T("gen.status_elapsed_eta", elapsed=elapsed_str, eta=eta_str)
        return " " + self.T("gen.status_elapsed_only", elapsed=elapsed_str)

    def _update_shared_progress_from_generation_chunk(self, chunk):
        """Reflects a generation run's live console output onto the shared bottom status
        bar -- the SAME self.status/self.totals_progress the floor-totals scan and the
        Primes/Constellations search box already use -- covering the WHOLE pipeline as
        one sequence of steps, not just the batch-sieve phase. Scans `chunk` (a raw text
        blob straight from WslLoggedRunner's log-tailing -- may hold zero, one, or
        several lines, and may occasionally split one line across two chunks; a missed
        match here just means the bar catches up on the next chunk a moment later,
        harmless for a live display) for whichever of the line shapes documented on
        _GEN_PREP_DONE_RE/_GEN_SIEVE_PROGRESS_RE/_GEN_SIEVE_DONE_RE/_GEN_CONST_
        FLOOR_PROGRESS_RE/_GEN_CONST_PROGRESS_RE's own module-level comment is
        present, checked in the order a real run actually prints them (prep ->
        batches -> done; the constellation path has no separate prep step of its
        own, just floor-wide totals -> per-file progress). _GEN_CONST_DONE_RE is
        deliberately NOT among these -- see the inline comment right before the
        _GEN_SIEVE_DONE_RE check below for why a constellation batch's own "Done"
        line must NOT be treated the same as the sieve pipeline's.

        Sieve-pipeline step model (self._gen_step_total, reset to None between runs):
        step 0 is the pi(L_final) prep phase (which can itself run into minutes at
        extreme depth -- see prime_sieve_v4_1.py's own SKIPPED-mode comment), steps
        1..n_batches are
        each individual sieve batch. The real n_batches isn't known until the FIRST
        batch-progress line arrives, so between the prep line and that first batch line
        the bar shows a provisional 1-of-2 (half full) rather than 0-of-unknown -- it
        gets corrected to the real proportion the moment the first batch line defines the
        actual total, which in practice is only a few seconds later. The run-finished
        line ("[*] TOTAL PRIMES FOUND...") snaps the bar to fully complete regardless of
        exactly how many steps were tracked, then clears _gen_step_total so the NEXT
        run starts from the same 'unknown total yet' state rather than inheriting this
        run's batch count.

        No explicit arbitration against search/totals for ownership of the shared bar:
        each of the three writes self.status on its own independent schedule, so
        whichever last had something to say is simply what's showing. In practice
        generation dominates while it's actually running, since these lines repeat every
        couple of seconds -- far more often than search's one-shot "searching..."
        message or the totals scan's own periodic updates -- without needing a priority
        flag to enforce that.

        Multi-iteration Exploration-mode loop (self._gen_loop_run_count/_gen_loop_
        iteration, both None outside a loop run): orchestrator_loop_v2.py launches
        run_count separate orchestrator_v3.py subprocesses back to back, one per
        iteration, and each one prints its OWN independent prep/batch-progress/done
        lines as if it were a lone single-window-range run. Without loop-awareness the
        bar would snap to "done" after iteration 1 of N (see _LOOP_SESSION_START_RE's
        own module-level comment). While _gen_loop_run_count is set, the per-iteration
        step count from the sieve-pipeline model above is treated as one slice of a
        wider run_count-slice bar: overall maximum = run_count * that iteration's own
        step_total, overall value = completed-iterations-worth of steps + the current
        iteration's own progress into its slice. Only _LOOP_SESSION_DONE_RE -- the
        line orchestrator_loop_v2.py itself prints once ALL iterations are over --
        snaps the bar to full and clears _gen_loop_run_count/_gen_loop_iteration back
        to None; the per-iteration "[*] TOTAL PRIMES FOUND..." line just marks that
        iteration's slice as complete and keeps waiting.

        Every totals_progress write below goes through _set_gen_progress_bar() (see
        that method's own docstring), not a direct .configure() call -- it silently
        no-ops for engines that don't actually report granular progress (primesieve/
        cudasieve mode, see self._gen_progress_bar_active's own __init__ comment)."""
        pending = getattr(self, '_hybrid_error_tail', '') + chunk
        lines = pending.split("\n")
        self._hybrid_error_tail = lines.pop()[-8192:]
        for line in lines:
            if '[HYBRID] ERROR:' in line:
                detail = line.split('[HYBRID] ERROR:', 1)[1].strip()
                self.quick_status_var.set(self.T("quick.hybrid_status_incomplete") + detail)
                messagebox.showerror(self.T("quick.hybrid_error_interrupted_title"),
                    detail + self.T("quick.hybrid_error_interrupted_hint"))
        hybrid_stage_matches = _GEN_HYBRID_STAGE_RE.findall(chunk)
        if hybrid_stage_matches:
            stage_str, total_str = hybrid_stage_matches[-1]
            stage, total = int(stage_str), int(total_str)
            self._gen_loop_run_count = total
            self._gen_loop_iteration = stage
            self._gen_step_total = 1
            self._set_gen_progress_bar(mode="determinate", maximum=max(1, total), value=stage - 1)
            self.status.set(self.T("quick.status_hybrid_stage", stage=stage, total=total))
            return

        if _GEN_HYBRID_DONE_RE.search(chunk):
            total = self._gen_loop_run_count or 1
            self._set_gen_progress_bar(mode="determinate", maximum=total, value=total)
            self.status.set(self.T("gen.status_progress_done"))
            self._gen_step_total = None
            self._gen_loop_run_count = None
            self._gen_loop_iteration = None
            return

        if _LOOP_SESSION_DONE_RE.search(chunk):
            total = self._gen_step_total or 1
            self._set_gen_progress_bar(mode="determinate", maximum=total, value=total)
            self.status.set(self.T("gen.status_progress_done"))
            self._gen_step_total = None
            self._gen_loop_run_count = None
            self._gen_loop_iteration = None
            return

        loop_start_match = _LOOP_SESSION_START_RE.search(chunk)
        if loop_start_match:
            self._gen_loop_run_count = int(loop_start_match.group(1))
            self._gen_loop_iteration = 1

        iter_start_matches = _LOOP_ITERATION_START_RE.findall(chunk)
        if iter_start_matches:
            iteration_str, _run_count_str = iter_start_matches[-1]
            self._gen_loop_iteration = int(iteration_str)
            self._gen_step_total = None  # fresh subprocess -- real total not known
                                          # until its own first batch-progress line

        # _GEN_CONST_DONE_RE deliberately does NOT join the check below:
        # constellation_finder_v2.py's process_floor() prints its "Done. New hits this
        # run" line at the end of EVERY batch (a fresh WSL subprocess per
        # --max-windows-capped batch, see build_constellation_finder_argv()), not once
        # the whole floor is finished. Treated like _GEN_SIEVE_DONE_RE, it would snap
        # the bar to 100% at every batch boundary and restart it near-empty with the
        # next batch. The floor-wide branch further below (_GEN_CONST_FLOOR_PROGRESS_RE
        # + _GEN_CONST_PROGRESS_RE) tracks progress across chained batches, and
        # _on_constellation_finished()'s tail resets the bar once the floor is complete
        # (no further batch scheduled). So a const-done match is simply ignored here,
        # letting this chunk's per-window line, if present, update the bar/status via
        # the floor-wide path below.
        if _GEN_SIEVE_DONE_RE.search(chunk):
            if self._gen_loop_run_count is not None:
                # One iteration of a multi-iteration run just finished -- NOT the whole
                # session. Only _LOOP_SESSION_DONE_RE (checked above) snaps the bar to
                # full/clears loop state; here just mark this iteration's own slice as
                # complete and keep the loop state alive for the next iteration.
                run_count = self._gen_loop_run_count
                iteration = self._gen_loop_iteration or 1
                step_total = self._gen_step_total or 1
                self._set_gen_progress_bar(
                    mode="determinate", maximum=run_count * step_total,
                    value=min(iteration, run_count) * step_total)
                self.status.set(self.T("gen.status_progress_loop_iteration_done",
                                   iteration=iteration, run_count=run_count))
                return
            total = self._gen_step_total or 1
            self._set_gen_progress_bar(mode="determinate", maximum=total, value=total)
            self.status.set(self.T("gen.status_progress_done"))
            self._gen_step_total = None
            return

        sieve_matches = _GEN_SIEVE_PROGRESS_RE.findall(chunk)
        if sieve_matches:
            percent_str, done_str, total_str = sieve_matches[-1]
            done, n_batches = int(done_str), int(total_str)
            self._gen_step_total = n_batches + 1  # +1 for the prep step already done
            if self._gen_loop_run_count is not None:
                run_count = self._gen_loop_run_count
                iteration = self._gen_loop_iteration or 1
                self._set_gen_progress_bar(
                    mode="determinate", maximum=run_count * self._gen_step_total,
                    value=(iteration - 1) * self._gen_step_total + (done + 1))
                self.status.set(self.T("gen.status_progress_loop_sieve", iteration=iteration,
                                   run_count=run_count, percent=percent_str,
                                   done=done, total=n_batches))
            else:
                self._set_gen_progress_bar(mode="determinate",
                                            maximum=self._gen_step_total, value=done + 1)
                self.status.set(self.T("gen.status_progress_sieve", percent=percent_str,
                                   done=done, total=n_batches))
            return

        floor_progress_match = _GEN_CONST_FLOOR_PROGRESS_RE.search(chunk)
        if floor_progress_match:
            # See _GEN_CONST_FLOOR_PROGRESS_RE's own comment in generation.py -- printed
            # once near the start of every process_floor() call, so this just records
            # the floor-wide totals; deliberately no `return` here, since the SAME chunk
            # may also carry this batch's own first per-window line (handled below),
            # which shouldn't have to wait for the next 150ms poll tick to be reflected.
            _batch_size_str, total_windows_str, already_done_str = floor_progress_match.groups()
            self._const_floor_total_windows = int(total_windows_str)
            self._const_floor_already_done = int(already_done_str)
            # ETA rate baseline -- reset whenever the floor total actually CHANGES from
            # whatever it was last anchored against (covers both "first FLOOR PROGRESS
            # line of this session" -- baseline_total is still None -- and "process
            # every floor with data" mode moving on to a genuinely different floor).
            # Deliberately NOT reset on every batch of the SAME floor: an unchanged
            # total means this is just the next chained batch, and the rate should keep
            # averaging over the whole floor scan so far, not restart at each batch
            # boundary -- see CONSTELLATION_ETA_MIN_WINDOWS's comment in constellation_section.py.
            if self._const_eta_baseline_total != self._const_floor_total_windows:
                self._const_eta_baseline_time = time.time()
                self._const_eta_baseline_done = self._const_floor_already_done
                self._const_eta_baseline_total = self._const_floor_total_windows
                # Same "total actually changed" trigger re-anchors the run-relative bar
                # baseline too -- covers "every floor with data" mode moving on to a
                # genuinely different floor mid-run, on top of _on_run_constellation()'s
                # own reset for an ordinary fresh Run click.
                self._const_run_start_already_done = self._const_floor_already_done

        const_matches = _GEN_CONST_PROGRESS_RE.findall(chunk)
        if const_matches:
            done_str, total_str = const_matches[-1]
            done, total = int(done_str), int(total_str)
            self._gen_step_total = total
            if self._const_floor_total_windows:
                # Floor-wide progress is known (this batch's own FLOOR PROGRESS line has
                # already been seen) -- show/animate against the WHOLE floor instead of
                # just this one --max-windows-capped batch, so the bar doesn't snap back
                # to near-zero every time _maybe_continue_constellation_batch() chains
                # the next one. See this attribute's own __init__ comment.
                floor_total = self._const_floor_total_windows
                already_done = self._const_floor_already_done or 0
                floor_done = min(floor_total, already_done + done)
                # Bar/status track THIS RUN's own start-to-finish progress, not the
                # floor's whole checkpoint history -- see _const_run_start_already_done's
                # own __init__ comment for why (a resumed floor can already be 99%+ done
                # from an earlier session).
                run_start_already_done = self._const_run_start_already_done or 0
                run_total = max(1, floor_total - run_start_already_done)
                run_done = max(0, min(run_total, floor_done - run_start_already_done))
                batch_count = -(-run_total // CONSTELLATION_BATCH_SIZE)  # ceil div
                batch_num = min(batch_count, run_done // CONSTELLATION_BATCH_SIZE + 1)
                self._set_gen_progress_bar(mode="determinate", maximum=run_total,
                                            value=run_done)
                if batch_count > 1:
                    status_text = self.T("gen.status_progress_const_batch",
                                     done=run_done, total=run_total,
                                     batch_num=batch_num, batch_count=batch_count)
                else:
                    status_text = self.T("gen.status_progress_const",
                                     done=run_done, total=run_total)
                # Remaining work is identical whether computed from floor-wide or
                # run-relative terms (both differ from the other only by the constant
                # run_start_already_done offset), and the ETA rate baseline is itself
                # anchored in floor-wide terms -- see its own reset above -- so this
                # deliberately keeps passing the floor-wide numbers here rather than
                # run_total/run_done.
                status_text += self._const_elapsed_eta_suffix(floor_total, floor_done)
                self.status.set(status_text)
            else:
                self._set_gen_progress_bar(mode="determinate", maximum=max(1, total), value=done)
                self.status.set(self.T("gen.status_progress_const", done=done, total=total))
            return

        if _GEN_PREP_DONE_RE.search(chunk):
            self._gen_step_total = None  # real total not known until the first
                                          # batch-progress line -- see docstring above
            if self._gen_loop_run_count is not None:
                run_count = self._gen_loop_run_count
                iteration = self._gen_loop_iteration or 1
                self._set_gen_progress_bar(
                    mode="determinate", maximum=run_count * 2, value=(iteration - 1) * 2 + 1)
                self.status.set(self.T("gen.status_progress_loop_prep", iteration=iteration,
                                   run_count=run_count))
            else:
                self._set_gen_progress_bar(mode="determinate", maximum=2, value=1)
                self.status.set(self.T("gen.status_progress_prep"))
