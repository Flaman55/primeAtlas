"""
constellation_section.py -- ConstellationSection, Section B of the Generation tab: the
constellation_finder_v2_2.py search form and console, batched launches
(CONSTELLATION_BATCH_SIZE windows per WSL process), graceful Stop through a sentinel file,
checkpoint-verified auto-retry, and the finish handler.

A GenerationTab mixin: it uses the widgets, Variables and runner state that GenerationTab
and its other mixins set up, so it is never instantiated on its own.
"""
import os
import queue
import re
import time

import tkinter as tk
from tkinter import ttk, messagebox

from ..core.progress_bar_owner import release_progress_bar
from .generation_console import GenerationConsole
from .engine_argv import build_constellation_finder_argv, read_constellation_checkpoint
from .generation_settings import save_generation_settings
from .wsl_command import generation_log_paths, build_wsl_logged_command

# The constellation finder's WSL process can die mid-run WITHOUT writing an exit code on
# a large floor (hundreds of thousands of source windows), most likely the
# WSL/Windows filesystem-interop scaling issue window_sharding.py documents for directory
# listing. See _maybe_auto_retry_constellation() for the checkpoint-verified relaunching
# this constant bounds.
MAX_CONSTELLATION_AUTO_RETRIES = 200
CONSTELLATION_AUTO_RETRY_DELAY_MS = 2000

# Proactive counterpart to the reactive retry above -- rather than only reacting AFTER
# a crash, every specific-floor run is capped to this many windows per WSL invocation
# from the start (see
# build_constellation_finder_argv()'s own max_windows parameter and
# constellation_finder_v2_2.process_floor()'s own docstring), with
# _maybe_continue_constellation_batch() chaining a fresh WSL process for the next slice
# automatically on a clean exit. Matches window_sharding.SHARD_SIZE (the existing
# per-directory chunking granularity already established for this same floor-25 scaling
# problem) rather than inventing an unrelated magnitude.
CONSTELLATION_BATCH_SIZE = 5000
_GEN_CONST_BATCH_REMAINING_RE = re.compile(
    r"\[CONSTELLATIONS v2\] BATCH DONE -- (\d+) window")

# Graceful stop: a plain terminate()+pkill (WslLoggedRunner.stop()) can kill the
# constellation finder mid-write of a hit file -- append_prime_window()
# (prime_sieve_v1.py) writes a file's header (new count) BEFORE its payload, so an
# ill-timed kill can corrupt that file. _on_stop_constellation() below writes this
# sentinel file instead; the finder's process_floor() checks for it once per window
# (STOP_REQUEST_FILENAME/_stop_requested()) and exits cleanly BETWEEN windows, like an
# ordinary --max-windows batch boundary. CONSTELLATION_STOP_GRACE_MS bounds how long the
# GUI waits for that clean exit before falling back to a hard kill, for a process stuck
# somewhere that never reaches the loop-top check (e.g. WSL/DrvFs degradation).
# Filename must match the finder's STOP_REQUEST_FILENAME exactly -- a separate literal
# here (not imported) since this module only launches that script as a WSL subprocess
# (same reasoning as read_constellation_checkpoint()'s separate CHECKPOINT.txt parsing
# in engine_argv.py).
CONSTELLATION_STOP_REQUEST_FILENAME = "STOP_REQUEST.txt"
CONSTELLATION_STOP_GRACE_MS = 10_000

# Elapsed-time/ETA display. Rate is measured
# on the GUI's own wall clock (elapsed real time / floor-wide windows actually done)
# rather than parsed from constellation_finder_v2_2.py's own per-window "(X.XXs)" timing
# -- a single window's own duration swings wildly (tiny vs. huge windows, occasional
# WSL/DrvFs slowdowns), while a wall-clock rate averaged over many windows smooths that
# out AND naturally folds in the real cost of chaining a fresh WSL process for every
# --max-windows batch, which a single window's own self-reported time never would.
# CONSTELLATION_ETA_MIN_WINDOWS windows must have been processed in THIS session before
# an ETA is shown at all -- too few samples right after a (re)start would otherwise
# swing wildly (e.g. "ETA: 2h" after one lucky-fast window, "ETA: 20min" after the
# next).
CONSTELLATION_ETA_MIN_WINDOWS = 3


class ConstellationSection:
    def _build_constellation_section(self, sections):
        """Section B: the constellation search form, its Run/Stop row and its console."""
        # --- Section B: constellation_finder_v2_2.py (k-tuple search) --------------
        const_outer = ttk.Labelframe(
            sections, text=self.T("gen.section_const"))
        const_outer.pack(fill="x", pady=(6, 0))

        const_form = ttk.Frame(const_outer)
        const_form.pack(fill="x", padx=8, pady=6)
        const_settings = self._generation_settings["constellation"]
        ttk.Label(const_form, text=self.T("gen.const_field_base_exponent")).pack(
            side="left")
        self._const_base_exponent_var = tk.StringVar(
            value=str(const_settings.get("base_exponent", "")))
        ttk.Entry(const_form, textvariable=self._const_base_exponent_var, width=10).pack(
            side="left", padx=(6, 0))

        const_btn_row = ttk.Frame(const_outer)
        const_btn_row.pack(fill="x", padx=8, pady=(0, 4))
        self.const_run_btn = ttk.Button(
            const_btn_row, text=self.T("common.run"), command=self._on_run_constellation)
        self.const_run_btn.pack(side="left")
        self.const_stop_btn = ttk.Button(
            const_btn_row, text=self.T("common.stop"), command=self._on_stop_constellation,
            state="disabled")
        self.const_stop_btn.pack(side="left", padx=(6, 0))
        self.const_status_label = tk.StringVar(value=self.T("common.ready"))
        ttk.Label(const_btn_row, textvariable=self.const_status_label).pack(
            side="left", padx=(12, 0))

        # Collapsible terminal, same as the pipeline section's loop_console above --
        # see GenerationConsole's docstring for the full rationale. No extra_controls_
        # builder here -- the constellation-finder section has no Quick-gen-style panel
        # to duplicate, only its own raw Run/Stop pair above.
        self.const_console = GenerationConsole(
            const_outer, self.T, height=20)
        self.const_output = self.const_console.text
        self._register_scroll_exclude(self.const_console.text.frame)

        self._const_runner = None
        self._const_output_queue = queue.Queue()
        # Auto-retry state for _maybe_auto_retry_constellation() -- see that method's
        # own docstring. _const_auto_retry_base_exponent mirrors whatever was in
        # _const_base_exponent_var at the moment Run was clicked ("" means "every
        # floor with data", which auto-retry deliberately never engages for).
        self._const_auto_retry_count = 0
        self._const_auto_retry_base_exponent = None
        self._const_last_checkpoint_seen = None
        # Set by _scan_const_chunk_for_batch_marker() as the current run's output
        # streams in, consumed (and reset to None) by
        # _maybe_continue_constellation_batch() once the run's exit sentinel arrives.
        self._const_batch_remaining = None
        # Floor-wide progress state, set by _update_shared_progress_from_generation_
        # chunk() the moment a run's own "FLOOR PROGRESS" line arrives -- see
        # _GEN_CONST_FLOOR_PROGRESS_RE's own comment in run_output.py. None until then
        # (and reset to None at the start of every fresh launch, in
        # _start_constellation_runner()) so a stale value from a PREVIOUS run's floor
        # can never be mistaken for the current one's.
        self._const_floor_total_windows = None
        self._const_floor_already_done = None
        # How many windows this floor already had checkpointed as done BEFORE the
        # current Run click's own first batch -- i.e. the baseline the bar/status text
        # subtract from _const_floor_total_windows/_const_floor_already_done so the bar
        # tracks THIS RUN's own start-to-finish progress instead of the floor's whole
        # checkpoint history (a floor resumed from an earlier session can already be
        # 99%+ done, which would put the bar at "full" from the start -- see
        # _on_run_constellation()'s own reset and the FLOOR PROGRESS handling in
        # _update_shared_progress_from_generation_chunk() for where this gets
        # (re-)anchored). None until the first FLOOR PROGRESS line of a run arrives.
        self._const_run_start_already_done = None
        # Elapsed-time/ETA state -- see CONSTELLATION_ETA_MIN_WINDOWS's own module-level
        # comment. _const_session_start_time is set ONLY by _on_run_constellation() (a
        # fresh Run click) -- NOT by _start_constellation_runner(), so it keeps counting
        # across auto-retries and chained batch continuations for the SAME floor scan
        # (exactly what "how long has this floor scan been running" should mean). The
        # _const_eta_baseline_* trio anchors the RATE measurement instead -- reset
        # whenever the floor total actually changes (see _update_shared_progress_from_
        # generation_chunk()'s own handling of the FLOOR PROGRESS line), which covers
        # both "session just started" (total goes from unknown to known) and "the
        # 'every floor with data' mode just moved on to a different floor" (total
        # changes between two already-known values) with the same one check.
        self._const_session_start_time = None
        self._const_eta_baseline_time = None
        self._const_eta_baseline_done = None
        self._const_eta_baseline_total = None
        # Grace-period handle for the graceful-Stop mechanism -- see
        # _on_stop_constellation()'s own docstring. Cancelled (via after_cancel) if the
        # run's own exit sentinel arrives before the grace period elapses, so a stale
        # timer from a run that already finished cleanly never fires a pointless
        # (and harmless, but confusing to watch in the console) hard-stop fallback.
        self._const_stop_grace_after_id = None

    def _show_const_terminal(self):
        self.const_console.show()

    def _on_run_constellation(self):
        if self._const_runner is not None and self._const_runner.is_running():
            return
        # See _other_engine_is_running()'s own docstring -- loop/hybrid/orchestrator
        # and the ktuple sieve both share this tab's mutable progress-parsing state
        # with the constellation search, so running one of them alongside this is
        # unsafe. A normal click can't reach here while another engine is running
        # (see _lock_other_run_buttons()) -- this is the non-button-click backstop.
        if self._other_engine_is_running("const"):
            return
        base_exponent = self._const_base_exponent_var.get().strip()
        if base_exponent and not base_exponent.isdigit():
            messagebox.showerror(
                self.T("gen.dialog_title"), self.T("gen.error_base_exponent_int"))
            return

        self._generation_settings["constellation"] = {"base_exponent": base_exponent}
        save_generation_settings(self._get_portal_folder(), self._generation_settings)

        # constellation_finder_v2_2.py DOES print granular per-file progress lines --
        # see _reset_gen_progress_bar_for_new_run()'s own docstring: without this, a
        # previous run's leftover bar state (e.g. a prime-generation run that just
        # finished at 100%) stays on screen until the first FLOOR PROGRESS line
        # arrives, which is not immediate.
        self._reset_gen_progress_bar_for_new_run()
        self._const_auto_retry_count = 0
        self._const_auto_retry_base_exponent = base_exponent
        # A fresh Run click is the one true "session start" -- see _const_session_
        # start_time's own __init__ comment for why this lives HERE and not in
        # _start_constellation_runner() (which auto-retry/batch-continuation also call,
        # and must NOT reset the elapsed clock for those).
        self._const_session_start_time = time.time()
        self._const_eta_baseline_time = None
        self._const_eta_baseline_done = None
        self._const_eta_baseline_total = None
        # A fresh Run click also re-anchors the run-relative bar baseline (see its own
        # __init__ comment) -- NOT done in _start_constellation_runner(), same reasoning
        # as _const_session_start_time above: that method also runs for auto-retries and
        # chained-batch continuations, which must keep accumulating against THIS run's
        # original baseline, not reset it.
        self._const_run_start_already_done = None
        self._start_constellation_runner(base_exponent)

    def _start_constellation_runner(self, base_exponent):
        """Builds and launches the actual constellation_finder_v2_2.py WSL command --
        shared by _on_run_constellation() (the Run button), _maybe_auto_retry_
        constellation() (an automatic relaunch after a crash) and _maybe_continue_
        constellation_batch() (chaining the next batch after a clean one), so every
        one of those is byte-for-byte the same command a manual re-click would
        produce.

        Every SPECIFIC-floor run (base_exponent non-empty) is capped to
        CONSTELLATION_BATCH_SIZE windows via build_constellation_finder_argv()'s own
        max_windows -- see that function's and constellation_finder_v2_2.process_floor()'s
        own docstrings for why. The "process every floor with data" mode (base_exponent
        blank) stays uncapped -- there's no single floor/checkpoint for the batch-
        continuation logic to track progress against there.

        Snapshots this floor's CHECKPOINT.txt (self._const_last_checkpoint_seen)
        immediately before launching, every time -- not just once at the very first
        Run click -- so _maybe_auto_retry_constellation()'s "did THIS run make
        progress" check always compares against the checkpoint as it stood right
        before THIS SPECIFIC run started, whether that run is the original click, an
        auto-retry, or a chained batch continuation. Also clears
        self._const_batch_remaining so a stale marker from a PREVIOUS run's own output
        can never be mistaken for this run's -- same reasoning extends to the floor-
        wide progress state (self._const_floor_total_windows/_const_floor_already_done,
        see their own __init__ comment) and to a defensive removal of the graceful-Stop
        sentinel file (CONSTELLATION_STOP_REQUEST_FILENAME): _on_constellation_finished()
        already removes it on every exit, but a leftover from some earlier, ungraceful
        termination (e.g. the app itself was closed mid-stop) should never be able to
        make a brand-new, never-stopped run exit after its very first window."""
        self._const_last_checkpoint_seen = (
            read_constellation_checkpoint(self._get_portal_folder(), int(base_exponent))
            if base_exponent else None)
        self._const_batch_remaining = None
        self._const_floor_total_windows = None
        self._const_floor_already_done = None
        try:
            os.remove(os.path.join(self._get_portal_folder(), CONSTELLATION_STOP_REQUEST_FILENAME))
        except OSError:
            pass

        argv = build_constellation_finder_argv(
            base_exponent if base_exponent else None,
            max_windows=CONSTELLATION_BATCH_SIZE if base_exponent else None)
        log_path, exit_path, _run_id = generation_log_paths(self._get_portal_folder(), "constellation")
        cmd = build_wsl_logged_command(argv, log_path, exit_path, self._get_portal_folder())

        self.const_console.append(self._new_run_separator())
        self._const_output_queue = queue.Queue()
        self._const_runner = self._new_wsl_runner(
            cmd, log_path, exit_path, self._const_output_queue,
            kill_pattern="constellation_finder_v2_2.py")
        self._const_runner.start()
        self.const_run_btn.configure(state="disabled")
        self.const_stop_btn.configure(state="normal")
        self._lock_other_run_buttons("const")
        self.const_status_label.set(self.T("common.running"))
        self._show_const_terminal()

    def _on_stop_constellation(self):
        """Stop click: requests a GRACEFUL stop first -- writes CONSTELLATION_STOP_
        REQUEST_FILENAME, which the finder's process_floor() checks once per window
        (see that mechanism's module-level comment above) -- rather than killing the
        WSL process immediately. A raw terminate()+pkill can land mid-window and
        corrupt a hit file: append_prime_window() (prime_sieve_v1.py) writes a file's
        header (new count) BEFORE its payload, so an ill-timed kill leaves the header
        claiming entries that were never written. Schedules _force_stop_
        constellation_if_still_running() as a bounded backstop after CONSTELLATION_
        STOP_GRACE_MS, for a process stuck somewhere that never reaches the loop-top
        check (e.g. WSL/DrvFs degradation) -- same "graceful first, bounded hard-kill
        fallback" shape as _maybe_auto_retry_constellation()'s retry cap.

        An explicit Stop is a deliberate user action, not a crash -- a run the user
        asked to stop is never auto-relaunched."""
        if self._const_runner is not None:
            self._const_auto_retry_base_exponent = None
            try:
                with open(os.path.join(self._get_portal_folder(),
                                        CONSTELLATION_STOP_REQUEST_FILENAME),
                          "w", encoding="utf-8") as f:
                    f.write("stop requested from GenerationTab's own Stop button\n")
            except OSError:
                pass  # best-effort -- the grace-period fallback below still reaches
                      # the same hard-kill Stop this method always used before this
            self.const_status_label.set(self.T("gen.const_stopping_graceful"))
            if self._const_stop_grace_after_id is not None:
                self.after_cancel(self._const_stop_grace_after_id)
            self._const_stop_grace_after_id = self.after(
                CONSTELLATION_STOP_GRACE_MS, self._force_stop_constellation_if_still_running)

    def _force_stop_constellation_if_still_running(self):
        """Grace-period fallback for _on_stop_constellation() above -- fires
        CONSTELLATION_STOP_GRACE_MS after a Stop click. If the run already exited
        cleanly in response to the sentinel file (the common case), _on_constellation_
        finished() already cancelled this very callback, so in practice this body only
        ever runs for a process that's genuinely stuck. Falls back to a hard
        terminate()+pkill in that case."""
        self._const_stop_grace_after_id = None
        if self._const_runner is not None and self._const_runner.is_running():
            self._const_runner.stop()
            self.const_status_label.set(self.T("common.stopping"))

    def _maybe_auto_retry_constellation(self, returncode):
        """Auto-relaunches the constellation finder when its WSL process dies WITHOUT
        writing an exit code (returncode is None): on a large floor (hundreds of
        thousands of source windows) the WSL wrapper process can end silently mid-run
        (no Python traceback, no exit code -- see WslLoggedRunner), most likely the
        WSL/Windows filesystem-interop scaling issue window_sharding.py documents for
        directory listing, here under sustained file-open volume against the /mnt/
        mount -- outside this app's control.

        The finder records its progress in CHECKPOINT.txt as it goes, so relaunching
        the identical command resumes where the last one died at essentially zero
        cost, and the floor keeps being processed until done without the user
        re-clicking Run.

        Guards against relaunching forever on a genuinely PERMANENT failure (not a
        transient scale hiccup) two ways: a hard retry cap
        (MAX_CONSTELLATION_AUTO_RETRIES) as a backstop against pathological flapping,
        and -- the real safety net -- comparing each floor's own CHECKPOINT.txt before
        vs. after a relaunch attempt: if a relaunch made no forward progress at all
        (e.g. the very first window after the checkpoint is itself poisoned somehow),
        further identical relaunches would just spin uselessly, so this stops
        immediately and surfaces the failure instead of retrying blindly.

        Only engages for a run against a SPECIFIC floor (base_exponent field non-empty
        when Run was clicked) -- the "process every floor with data" mode has no single
        CHECKPOINT.txt this can watch for progress, and multi-floor runs are rare/
        manual enough that falling back to the existing manual-restart behavior there
        is fine. Also never engages after an explicit Stop (_on_stop_constellation
        clears _const_auto_retry_base_exponent first).

        Returns True if a retry was just scheduled (caller should treat this run as
        still in-flight -- pending-search state etc. left untouched until the RETRY's
        own eventual _on_constellation_finished lands), False otherwise (this run is
        genuinely done, or gave up retrying -- business as usual)."""
        if returncode is not None:
            self._const_auto_retry_count = 0
            return False
        base_exponent = self._const_auto_retry_base_exponent
        if not base_exponent:
            return False
        checkpoint_now = read_constellation_checkpoint(self._get_portal_folder(), int(base_exponent))
        if checkpoint_now == self._const_last_checkpoint_seen:
            self.const_console.append(
                f"[!] {self.T('gen.const_auto_retry_no_progress')}\n")
            self._const_auto_retry_base_exponent = None
            return False
        if self._const_auto_retry_count >= MAX_CONSTELLATION_AUTO_RETRIES:
            self.const_console.append(
                f"[!] {self.T('gen.const_auto_retry_giving_up', count=MAX_CONSTELLATION_AUTO_RETRIES)}\n")
            self._const_auto_retry_base_exponent = None
            return False
        self._const_auto_retry_count += 1
        self.const_console.append(
            f"[*] {self.T('gen.const_auto_retry_relaunching', attempt=self._const_auto_retry_count, max=MAX_CONSTELLATION_AUTO_RETRIES)}\n")
        self.after(CONSTELLATION_AUTO_RETRY_DELAY_MS,
                   lambda: self._start_constellation_runner(base_exponent))
        return True

    def _scan_const_chunk_for_batch_marker(self, chunk):
        """chunk_hook passed to _drain_output_queue() for the constellation queue only
        -- records the "N window(s) still remain" count from constellation_finder_v2_2.
        py's own process_floor() when a --max-windows-capped batch didn't reach the
        end of the floor's own windows (see that function's and build_constellation_
        finder_argv()'s own docstrings). _maybe_continue_constellation_batch() reads
        this once the run's exit sentinel arrives, to decide whether to chain another
        batch. Deliberately NOT re-derived by re-listing source_primes/ from the
        Windows side -- that would repeat the exact expensive walk this whole feature
        exists to avoid paying twice; the script already knows the answer and prints
        it, this just reads it off the wire."""
        match = _GEN_CONST_BATCH_REMAINING_RE.search(chunk)
        if match:
            self._const_batch_remaining = int(match.group(1))

    def _maybe_continue_constellation_batch(self, returncode):
        """Chains the NEXT batch when a run finished CLEANLY (returncode == 0) but was
        itself only a bounded --max-windows slice of the floor with more still to do --
        see _start_constellation_runner()'s own docstring on why every specific-floor
        run is capped at CONSTELLATION_BATCH_SIZE windows in the first place. This is
        the proactive half of the floor-25 fix (feeding
        WSL small pieces instead of the whole floor at once); _maybe_auto_retry_
        constellation() above remains the reactive half for a batch that itself
        crashes mid-way.

        Only engages for a specific-floor run (mirrors _maybe_auto_retry_
        constellation()'s own restriction -- no single floor/checkpoint to chain for
        the 'every floor with data' mode) and only after _maybe_auto_retry_
        constellation() has already declined to act (a crash takes the retry path
        instead, never this one).

        Returns True if a continuation was just launched (caller should treat this run
        as still in-flight, same contract as _maybe_auto_retry_constellation()),
        False otherwise (nothing left to chain -- the floor is caught up, or this
        wasn't a specific-floor run)."""
        remaining = self._const_batch_remaining
        self._const_batch_remaining = None
        if returncode != 0 or not remaining:
            return False
        base_exponent = self._const_auto_retry_base_exponent
        if not base_exponent:
            return False
        self.const_console.append(
            f"[*] {self.T('gen.const_batch_continuing', remaining=remaining)}\n")
        self._start_constellation_runner(base_exponent)
        return True

    def _on_constellation_finished(self, returncode):
        """_drain_output_queue's on_exit callback for the constellation queue --
        mirrors _on_loop_finished's reload_primes_tree() call, but for the
        Constellations tab: re-runs reload_constellations_tree() so newly found hits
        show up there the moment a run finishes, without a manual Refresh click.
        constellation_finder_v2_2.py has no dual-purpose button label to reset (unlike
        the Quick-gen 'Generate'/'Stop' one _on_loop_finished handles), so this is
        otherwise a much shorter version of that method.

        Also owns cleanup for the graceful-Stop mechanism (see _on_stop_constellation()'s
        own docstring), on EVERY exit path -- clean batch/floor completion, a crash, an
        explicit graceful stop, or the hard-kill fallback -- not just the Stop-triggered
        one: cancels a still-pending grace-period timer (self._const_stop_grace_after_id)
        so it can never fire against a LATER, unrelated run started before the old
        timer's delay elapsed, and removes the sentinel file itself so it can never
        block the very next launch (the same file is also removed proactively in
        _start_constellation_runner, as a second, independent safety net -- see that
        method's own docstring)."""
        if self._const_stop_grace_after_id is not None:
            self.after_cancel(self._const_stop_grace_after_id)
            self._const_stop_grace_after_id = None
        try:
            os.remove(os.path.join(self._get_portal_folder(), CONSTELLATION_STOP_REQUEST_FILENAME))
        except OSError:
            pass
        self.reload_constellations_tree()

        if self._maybe_auto_retry_constellation(returncode):
            return  # a fresh run was just scheduled -- pending-search state (below)
                     # stays untouched until THAT run's own exit sentinel lands

        if self._maybe_continue_constellation_batch(returncode):
            return  # same as above, for a chained batch continuation instead

        # Genuinely finished (no chained retry/batch scheduled) -- unlike the loop
        # path, nothing downstream of reload_constellations_tree() resets the shared
        # totals_progress bar (reload_primes_tree()'s own show_cached_grand_total()
        # does that for loop/hybrid/etc. runs; the constellations tree reload has no
        # equivalent), so this run resets it back to its own empty resting state
        # itself before releasing its claim -- see progress_bar_owner.py.
        self._set_gen_progress_bar(mode="determinate", maximum=1, value=0)
        release_progress_bar(self.totals_progress, self)
        # See _lock_other_run_buttons()'s own docstring -- this point (past both
        # early-return chaining checks above) is the only place this run is
        # genuinely, not just this-batch, over.
        self._unlock_other_run_buttons()

        # Mirrors _on_loop_finished()'s pending-search re-run, for a search-triggered
        # "run constellation_finder for this floor" instead (see
        # _offer_generate_missing_constellation()) -- see that method's own docstring
        # for why this is a SEPARATE slot from the prime-window one.
        if self._pending_search_after_const_gen is not None:
            pending = self._pending_search_after_const_gen
            self._pending_search_after_const_gen = None
            self._start_search_job(pending["kind"], pending["base_exponent"], pending["number"])

    def _poll_constellation_output(self):
        self._drain_output_queue(self._const_output_queue, self.const_console,
                                  self.const_run_btn, self.const_stop_btn,
                                  self.const_status_label,
                                  on_exit=self._on_constellation_finished,
                                  chunk_hook=self._scan_const_chunk_for_batch_marker)
        self.after(150, self._poll_constellation_output)
