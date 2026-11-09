"""
restore_section.py -- RestoreSection, the metadata backup and restore part of the Backup
sub-tab: backup create/list/delete, the diff against disk, and the checkpointed,
pausable/resumable/cancellable restore job that regenerates missing windows and
constellation hits through the WSL engines.

Restore driving: orchestrator_loop_v2.py does not accept "regenerate exactly these
offsets" -- it appends the next N windows from wherever a floor's file count sits. The
engine assigns offsets deterministically in a fixed sequence per floor, so restarting
generation on a floor with fewer files than the backup recorded reproduces the SAME
missing filenames in the SAME order: "run enough iterations to cover the missing count,
then re-diff" is a correct restore strategy. Each step retries MAX_STAGE_RETRIES times
before it is marked done anyway with a logged warning (best-effort, like
delete_manager.py's PortalWiper.execute()).

A SettingsTab mixin: it uses the widgets, Variables and state that SettingsTab and its
other mixins set up, so it is never instantiated on its own.
"""
import os
import queue

from tkinter import messagebox

from ..generation import engine_options
from .manifest import FloorSnapshot, ConstellationSnapshot
from .backup_store import BackupStore
from .restore_job import (
    RestoreJob, restore_checkpoint_path, delete_extra_files,
    STATUS_RUNNING, STATUS_PAUSED,
)
from ..core import background


class RestoreSection:
    MAX_STAGE_RETRIES = 2

    # ---- backup -------------------------------------------------------------------------

    def _current_backup_store(self):
        # Rebuilt on every call (not cached) so it always reflects whatever storage path
        # is CURRENT -- the user can change the path without recreating this tab.
        return BackupStore(self.wsl["get_portal_folder"]())

    def _on_create_backup(self):
        store = self._current_backup_store()
        manifest = store.create()
        self.backup_status_var.set(self.T("settings.backup_created", name=manifest.name))
        self._refresh_backup_list()

    def _refresh_backup_list(self):
        """list_backups() is a cheap top-level os.listdir() of _backups/ per
        backup_store.py's own docstring, but this is backgrounded anyway for
        architectural consistency with the 'nothing clicked should freeze the window'
        goal -- this is called from many places, including tab construction itself, so
        its cost is paid on every app startup regardless of how fast it usually is, and
        a slow/remote-mounted storage path (e.g. network drive) can make even a
        top-level listdir slow."""
        store = self._current_backup_store()
        background.run_in_background(
            self, lambda report_progress: store.list_backups(),
            on_done=self._on_refresh_backup_list_done)

    def _on_refresh_backup_list_done(self, backups, error):
        if error is not None:
            messagebox.showerror(self.T("settings.dialog_title"), str(error))
            return
        self._backups = backups
        self.backup_listbox.delete(0, "end")
        for name, _path in self._backups:
            self.backup_listbox.insert("end", name)
        self._selected_backup_name = None
        self._diff_cache = None
        self.restore_start_btn.configure(state="disabled")

    def _on_backup_selected(self, _event):
        sel = self.backup_listbox.curselection()
        if not sel:
            return
        self._selected_backup_name = self.backup_listbox.get(sel[0])
        self._diff_cache = None
        self.restore_start_btn.configure(state="disabled")

    def _on_delete_backup(self):
        sel = self.backup_listbox.curselection()
        if not sel:
            messagebox.showinfo(self.T("settings.dialog_title"),
                                 self.T("settings.backup_delete_select_first"))
            return
        name = self.backup_listbox.get(sel[0])
        if not messagebox.askyesno(self.T("settings.dialog_title"),
                                    self.T("settings.backup_delete_confirm", name=name)):
            return
        store = self._current_backup_store()
        store.delete(name)
        self.backup_status_var.set(self.T("settings.backup_deleted", name=name))
        self._refresh_backup_list()

    # ---- restore: diff + start ----------------------------------------------------------

    def _on_check_diff(self):
        """Validates selection/state synchronously (cheap), loads the small manifest JSON
        synchronously (backup_store.py's load() is one file read, not a tree scan), then
        runs the actual manifest.diff_against_disk() comparison -- a full scan of every
        floor's CURRENT on-disk state, see that method's own docstring -- on a background
        thread via primeatlas/core/background.py's run_in_background(), instead of blocking
        the GUI thread for however long that scan takes.

        Calling diff_against_disk() directly, inline, on the GUI thread would freeze the
        window for the full scan on every click of the "Check differences" button."""
        if not self._selected_backup_name:
            messagebox.showinfo(self.T("settings.restore_title"),
                                 self.T("settings.restore_select_backup_first"))
            return
        if self._active_job is not None and self._active_job.status == STATUS_RUNNING:
            messagebox.showinfo(self.T("settings.restore_title"),
                                 self.T("settings.restore_already_running"))
            return
        if self._diff_check_running:
            return
        store = self._current_backup_store()
        manifest = store.load(self._selected_backup_name)
        portal_folder = self.wsl["get_portal_folder"]()
        self._diff_check_running = True
        self.restore_diff_btn.configure(state="disabled")
        background.run_in_background(
            self, lambda report_progress: manifest.diff_against_disk(portal_folder),
            on_done=self._on_check_diff_done)

    def _on_check_diff_done(self, diff, error):
        """Main-thread callback for _on_check_diff()'s background scan. A raised
        exception is surfaced to the user via messagebox (instead of propagating out of
        a Tk callback as console noise), and the Start-restore button stays disabled
        since there's no valid diff to act on."""
        self._diff_check_running = False
        self.restore_diff_btn.configure(state="normal")
        if error is not None:
            messagebox.showerror(self.T("settings.restore_title"), str(error))
            self._diff_cache = None
            self.restore_start_btn.configure(state="disabled")
            return
        self._diff_cache = diff
        if not diff:
            self._restore_log(
                self.T("settings.restore_no_diff", name=self._selected_backup_name))
            self.restore_start_btn.configure(state="disabled")
            return
        lines = [self.T("settings.restore_diff_header", name=self._selected_backup_name)]
        for base_exponent, d in sorted(diff.items()):
            lines.append(self.T(
                "settings.restore_diff_line", base_exponent=base_exponent,
                windows=len(d["missing_windows"]), hits=len(d["missing_hits"]),
                extra_windows=len(d.get("extra_windows", [])),
                extra_hits=len(d.get("extra_hits", []))))
        self._restore_log("".join(lines))
        self.restore_start_btn.configure(state="normal")

    def _on_start_restore(self):
        if not self._selected_backup_name or self._diff_cache is None:
            return
        # When storage has more entries than the backup (e.g. a new floor added after the
        # backup was made), restoring to that backup will delete the surplus -- that's
        # destructive, so there's a separate, explicit warning BEFORE the general restore
        # confirmation, with a chance to cancel right here.
        extra_floors = {
            be: d for be, d in self._diff_cache.items()
            if d.get("extra_windows") or d.get("extra_hits")
        }
        if extra_floors:
            extra_lines = "".join(
                self.T("settings.restore_extra_line", base_exponent=be,
                        windows=len(d.get("extra_windows", [])),
                        hits=len(d.get("extra_hits", [])))
                for be, d in sorted(extra_floors.items()))
            if not messagebox.askyesno(
                    self.T("settings.restore_title"),
                    self.T("settings.restore_confirm_delete_extra",
                           name=self._selected_backup_name, lines=extra_lines)):
                return
        if not messagebox.askyesno(
                self.T("settings.restore_title"),
                self.T("settings.restore_confirm", name=self._selected_backup_name)):
            return
        # Restore also swaps in the backup's benchmark_log.csv: its row history for
        # windows/floors that never made it into the backup (e.g. a floor added after
        # the backup was taken) has to go away along with their files (benchmark-mode rows,
        # which describe no files, are kept -- see BackupStore.restore_csv()), and rows for
        # anything regenerated below get freshly re-appended by that generation run
        # anyway (same WSL pipeline that writes benchmark_log.csv during ordinary
        # generation -- see orchestrator_loop_v2.py/prime_sieve_v3.py).
        # BackupStore.restore_csv() does the full swap-in of the backup's own CSV
        # snapshot; it's called here, once, at the START of a NEW job -- not from
        # _on_resume_incomplete(), which continues a job whose CSV was already restored
        # when it was first started.
        store = self._current_backup_store()
        manifest = store.load(self._selected_backup_name)
        kept = store.restore_csv(manifest)
        self._restore_log(self.T("settings.restore_csv_restored", name=self._selected_backup_name,
                                 kept=kept))
        # Cheap, non-destructive caches (floor_meta.json rows, totals-cache entries,
        # sieving-prime-count caches) -- see BackupManifest.restore_floor_metadata()'s own
        # docstring for why this is safe to run now, before any window regeneration below.
        store.restore_floor_metadata(manifest)
        self._restore_log(self.T("settings.restore_metadata_restored", name=self._selected_backup_name))
        portal_folder = self.wsl["get_portal_folder"]()
        checkpoint_path = restore_checkpoint_path(portal_folder, self._selected_backup_name)
        job = RestoreJob.from_diff(self._selected_backup_name, self._diff_cache, checkpoint_path)
        job.start()
        self._active_job = job
        self._step_retry_counts = {}
        self._restore_phase = None
        self._given_up_windows = set()
        self._given_up_hits = set()
        self._update_restore_progress()
        self._update_restore_buttons()
        self._drive_restore()

    def _on_resume_incomplete(self):
        sel = self.incomplete_listbox.curselection()
        if not sel or not self._incomplete_jobs:
            return
        job = self._incomplete_jobs[sel[0]]
        if job.status == STATUS_RUNNING:
            # App restarted (or crashed) while this job was running -- no subprocess is
            # actually alive anymore, so treat it as PAUSED until the user explicitly
            # clicks Resume, rather than silently resuming into a false "already running".
            job.status = STATUS_PAUSED
            job.save()
        self._active_job = job
        self._step_retry_counts = {}
        self._restore_phase = None
        self._given_up_windows = set()
        self._given_up_hits = set()
        self._restore_log(self.T("settings.restore_loaded_incomplete", name=job.backup_name))
        self._update_restore_progress()
        self._update_restore_buttons()

    def _on_delete_incomplete(self):
        sel = self.incomplete_listbox.curselection()
        if not sel or not self._incomplete_jobs:
            messagebox.showinfo(self.T("settings.dialog_title"),
                                 self.T("settings.restore_delete_select_first"))
            return
        job = self._incomplete_jobs[sel[0]]
        is_active_and_running = (
            job is self._active_job and self._active_job_runner_kind is not None)
        if is_active_and_running:
            messagebox.showinfo(self.T("settings.dialog_title"),
                                 self.T("settings.restore_delete_active_blocked"))
            return
        if not messagebox.askyesno(
                self.T("settings.dialog_title"),
                self.T("settings.restore_delete_confirm", name=job.backup_name)):
            return
        if job.checkpoint_path:
            try:
                os.remove(job.checkpoint_path)
            except OSError:
                pass
        if job is self._active_job:
            # Deleting the checkpoint the currently-loaded (but not in-flight) job is
            # backed by -- drop it from the tab's state too, otherwise Pause/Resume/Cancel
            # would keep operating on a job whose own save() calls now go nowhere (it
            # would silently no-op per RestoreJob.save()'s own docstring, but the buttons
            # staying "live" would be misleading).
            self._active_job = None
            self._update_restore_progress()
            self._update_restore_buttons()
        self._restore_log(self.T("settings.restore_deleted_incomplete", name=job.backup_name))
        self._scan_incomplete_restores()

    # ---- restore: pause/resume/cancel ----------------------------------------------------

    def _on_restore_pause(self):
        if self._active_job:
            self._active_job.pause()
            self._restore_log(self.T("settings.restore_paused_note"))
            self._update_restore_buttons()

    def _on_restore_resume(self):
        if self._active_job:
            self._active_job.resume()
            self._restore_log(self.T("settings.restore_resumed_note"))
            self._update_restore_buttons()
            self._drive_restore()

    def _on_restore_cancel(self):
        if self._active_job is None:
            return
        if not messagebox.askyesno(self.T("settings.restore_title"),
                                    self.T("settings.restore_confirm_cancel")):
            return
        if self._restore_runner is not None:
            self._restore_runner.stop()
        self._active_job.cancel()
        self._restore_log(self.T("settings.restore_cancelled_note"))
        self._update_restore_buttons()

    # ---- restore: driver (two phases -- ALL floors' windows, then ALL floors' hits) ------

    def _drive_restore(self):
        """Kicks off the next unit of restore work. No-op if there is no active job, the job
        isn't RUNNING (paused/cancelled/completed), or a subprocess is already in flight for
        it (that subprocess's own completion callback calls back into this method).

        Two strict phases, not one step (floor) fully finished before the next starts: EVERY
        floor's missing prime windows are restored first, in ascending floor order, before
        ANY floor's constellation hits are touched -- constellation_finder_v2_3.py reads the
        source_primes files that are already on disk (see that script), so running it against
        a floor whose own windows aren't fully back yet would either fail outright or (worse)
        record hits against an incomplete prime set and silently miss some. Only once no step
        anywhere still needs windows does the driver move on to hits, floor by floor, same as
        before. A step is only handed to _finish_step() (extras cleanup + marked done) once
        BOTH its windows and hits are satisfied -- see _on_step_stage_done()."""
        job = self._active_job
        if job is None or job.status != STATUS_RUNNING:
            return
        if self._active_job_runner_kind is not None:
            return
        windows_step = next(
            (s for s in job.pending_steps
             if s.needs_windows and s.base_exponent not in self._given_up_windows), None)
        if windows_step is not None:
            if self._restore_phase != "windows":
                self._restore_phase = "windows"
                self._restore_log(self.T("settings.restore_phase_windows_start"))
            self._restore_log(self.T(
                "settings.restore_step_start", base_exponent=windows_step.base_exponent,
                windows=len(windows_step.missing_windows), hits=len(windows_step.missing_hits)))
            self._drive_windows_phase(windows_step)
            return
        hits_step = next(
            (s for s in job.pending_steps
             if s.needs_hits and s.base_exponent not in self._given_up_hits), None)
        if hits_step is not None:
            if self._restore_phase != "hits":
                self._restore_phase = "hits"
                self._restore_log(self.T("settings.restore_phase_hits_start"))
            self._restore_log(self.T(
                "settings.restore_step_start", base_exponent=hits_step.base_exponent,
                windows=len(hits_step.missing_windows), hits=len(hits_step.missing_hits)))
            self._start_constellation_for_step(hits_step)
            return
        step = job.next_step()
        if step is None:
            self._on_restore_job_finished()
            return
        self._finish_step(step)

    def _finish_step(self, step):
        """Called once a step has nothing left that needs REGENERATING (no missing windows
        or hits, possibly after giving up per MAX_STAGE_RETRIES). If the step also has
        surplus files on disk that aren't in the backup, delete them now -- this is a pure
        local file op (delete_extra_files(), no WSL subprocess), so it runs synchronously
        right here rather than through the poll/subprocess machinery. The confirm/cancel
        warning already happened once, up front in _on_start_restore(), before the whole
        job was ever started."""
        job = self._active_job
        if step.has_extra:
            portal_folder = self.wsl["get_portal_folder"]()
            deleted, pruned, errors = delete_extra_files(
                portal_folder, step.base_exponent, step.extra_windows, step.extra_hits)
            self._restore_log(self.T(
                "settings.restore_extra_deleted", base_exponent=step.base_exponent,
                deleted=deleted))
            if pruned:
                self._restore_log(self.T(
                    "settings.restore_extra_pruned", base_exponent=step.base_exponent,
                    pruned=pruned))
            if errors:
                self._restore_log(self.T("settings.restore_extra_delete_errors"))
                for e in errors:
                    self._restore_log(f"  {e}\n")
            step.extra_windows = []
            step.extra_hits = []
        if not (step.needs_windows or step.needs_hits):
            self._restore_log(self.T("settings.restore_step_done", base_exponent=step.base_exponent))
        job.mark_step_done(step.base_exponent)
        self._update_restore_progress()
        if job.status != STATUS_RUNNING:
            # mark_step_done() flips the job itself to STATUS_COMPLETED the moment the
            # LAST pending step is marked done (see RestoreJob.mark_step_done()) -- before
            # _drive_restore() ever gets a chance to notice. _drive_restore()'s own very
            # first guard bails out on anything other than STATUS_RUNNING, so calling it
            # here would just no-op silently, leaving _active_job set and the Pause/Resume/
            # Cancel buttons frozen in their running state while the progress label
            # (sourced from job.status) already says "[completed]". Route
            # through the same finish path _drive_restore() itself uses for the
            # next_step()-is-None case instead.
            self._on_restore_job_finished()
            return
        self._drive_restore()

    def _drive_windows_phase(self, step):
        """Windows-phase launcher for one RestoreStep. Two questions decide how a floor
        gets restored -- whether it's a LOW floor (0-6), and whether its numeric range
        fits under libprimesieve's own uint64 ceiling -- answered independently of each
        other:

        Engine choice (primesieve vs. the orchestrator pipeline): a floor whose own upper
        boundary (10**(base_exponent+1) - 1) does not exceed primesieve_max_stop restores
        through prime_sieve_primesieve.py -- "primesieve mode", see that file's module
        header -- which calls libprimesieve's own bulk generate_primes() directly, with no
        batching/RAM-buffer cost of ours at all, dramatically faster than the orchestrator
        pipeline for anything within its reach. A floor that doesn't fit (its own top edge
        is past the ceiling) falls back to orchestrator_loop_v2.py.
        Floor 19 is the one floor that straddles the ceiling partway through -- treated
        here as "doesn't fit" for simplicity/safety (the orchestrator pipeline has no
        ceiling at all, so it's always correct, just slower); a future refinement could
        split that one floor's restore between both engines instead of picking one.

        Low floors (base_exponent < LOW_FLOOR_CUTOFF): ALWAYS well within primesieve's
        reach, so they take the primesieve path too -- a SINGLE target_idx_start=0,
        window_count=1 run against the LOWEST pending low floor completes EVERY floor from
        there up through floor 6 in one pass (prime_sieve_primesieve.py ports the exact
        same LOW_FLOOR_CUTOFF/_low_floor_segments() cascade prime_sieve_v3.py/v4.py have --
        see that file's own docstring for why). Launching once per PENDING low floor
        would regenerate that same shared block up to seven times over.
        _on_step_stage_done()'s low-floor branch re-scans every OTHER pending
        low-floor step once this run finishes and marks whatever the cascade already
        satisfied, instead of separately re-launching a run for each.

        Width, for whichever engine ends up used:
        - primesieve: the WHOLE missing-window count in one run (window_count_per_run =
          len(step.missing_windows), run_count = 1) -- primesieve mode has no per-window
          RAM-buffer cost the way the orchestrator's shared bit-packed buffer does (see
          README's "Window count, throughput, and RAM"), so there is no reason to chunk it.
        - orchestrator: the RAM-based recommendation (the same formula the Quick-gen
          panel's own Auto button uses -- estimate_wsl_available_ram_bytes() /
          engine_options.recommend() with the pipeline form's engine and v5 knobs, re-read
          fresh for EVERY floor, since available RAM can
          change between floors within one restore run) rather than whatever was last
          manually typed into the low-level Generation form. A floor whose own missing-
          window count fits within that RAM budget restores in ONE run; a floor that needs
          more than that iterates (run_count > 1) until it's full."""
        self._active_job_runner_kind = "loop"
        low_floor_cutoff = self.wsl["low_floor_cutoff"]
        primesieve_max_stop = self.wsl["primesieve_max_stop"]
        defaults = self.wsl["get_loop_defaults"]()
        window_m = int(defaults.get("window_m") or 10_000_000)
        engine_choice = engine_options.resolve(defaults)
        if engine_choice.engine == engine_options.ENGINE_PT1:
            # The manifest lists D windows only: a restore regenerates them with a sieve
            # engine, never pt1, which writes P from MR_DET_BOUND on.
            engine_choice = engine_options.EngineChoice(engine_options.DEFAULT_ENGINE,
                                                        engine_choice.knobs)
        bucket_mb = None
        portal_folder = self.wsl["get_portal_folder"]()

        is_low_floor = step.base_exponent < low_floor_cutoff
        floor_upper_bound = 10 ** (step.base_exponent + 1) - 1
        use_primesieve = floor_upper_bound <= primesieve_max_stop
        self._restore_low_floor_batch = is_low_floor

        if is_low_floor:
            target_idx_start, window_count_per_run, run_count = 0, 1, 1
            self._restore_log(self.T(
                "settings.restore_low_floor_batch_note", base_exponent=step.base_exponent))
        else:
            target_idx_start = self.wsl["find_continuation_target_idx"](
                portal_folder, step.base_exponent, window_m)
            if use_primesieve:
                window_count_per_run = max(1, len(step.missing_windows))
                run_count = 1
            else:
                # The pipeline form's engine and v5 knobs size the run; a RAM-reduced
                # bucket memory goes to the launch env below.
                available = self.wsl["estimate_wsl_available_ram_bytes"]()
                budget = engine_options.recommend(
                    available, engine_choice, step.base_exponent, window_m)
                if budget is not None:
                    bucket_mb = budget.bucket_mb
                window_count_per_run = (budget.windows if budget else None) or int(
                    defaults.get("window_count_per_run") or 20)
                run_count = max(1, -(-len(step.missing_windows) // max(1, window_count_per_run)))

        if use_primesieve:
            self._restore_log(self.T(
                "settings.restore_using_primesieve", base_exponent=step.base_exponent))
            argv = self.wsl["build_primesieve_argv"](
                step.base_exponent, target_idx_start, window_count_per_run, window_m, True)
            kill_pattern = "prime_sieve_primesieve.py"
        else:
            n_instances = int(defaults.get("n_instances") or 1)
            workers = int(defaults.get("workers") or 1)
            batches_per_worker = int(defaults.get("batches_per_worker") or 1)
            compute_sieving = bool(defaults.get("compute_sieving_primes_count", False))
            argv = self.wsl["build_loop_argv"](
                step.base_exponent, run_count, n_instances, True, compute_sieving,
                window_count_per_run, workers, batches_per_worker, window_m)
            kill_pattern = "orchestrator_loop_v2.py"

        log_path, exit_path, _run_id = self.wsl["generation_log_paths"](
            portal_folder, "restore_loop")
        # The knob profile's auto choice depends on the run width, known only now.
        engine_choice = engine_options.EngineChoice(engine_choice.engine, engine_options.resolve(
            dict(defaults, engine=engine_choice.engine), window_count_per_run).knobs)
        extra_env = () if use_primesieve else engine_options.launch_env(engine_choice, bucket_mb)
        cmd = self.wsl["build_wsl_logged_command"](argv, log_path, exit_path, extra_env=extra_env)
        q = queue.Queue()
        runner = self.wsl["WslLoggedRunner"](
            cmd, log_path, exit_path, q, kill_pattern=kill_pattern)
        self._restore_runner = runner
        self._restore_queue = q
        runner.start()
        self._poll_restore_queue(step, "loop")

    def _reconcile_low_floor_siblings(self, job, trigger_step, portal_folder):
        """After a low-floor batch run (see _drive_windows_phase), the cascade completes
        every floor from trigger_step.base_exponent up through floor 6 -- not just
        trigger_step's own floor. Re-scan every OTHER still-pending low-floor step and clear
        whatever the cascade already satisfied, so the driver doesn't redundantly launch a
        separate run for each one afterward."""
        low_floor_cutoff = self.wsl["low_floor_cutoff"]
        cleared = []
        for other in job.steps:
            if other is trigger_step or other.base_exponent >= low_floor_cutoff:
                continue
            if not other.needs_windows:
                continue
            snap = FloorSnapshot.scan(portal_folder, other.base_exponent)
            still_missing = sorted(set(other.missing_windows) - set(snap.filenames))
            if still_missing != other.missing_windows:
                other.missing_windows = still_missing
                if not other.needs_windows:
                    cleared.append(other.base_exponent)
        if cleared:
            self._restore_log(self.T(
                "settings.restore_low_floor_batch_cleared",
                trigger=trigger_step.base_exponent,
                floors=", ".join(f"10p{f}" for f in cleared)))

    def _start_constellation_for_step(self, step):
        self._active_job_runner_kind = "constellation"
        argv = self.wsl["build_constellation_finder_argv"](step.base_exponent)
        portal_folder = self.wsl["get_portal_folder"]()
        log_path, exit_path, _run_id = self.wsl["generation_log_paths"](
            portal_folder, "restore_const")
        cmd = self.wsl["build_wsl_logged_command"](argv, log_path, exit_path)
        q = queue.Queue()
        runner = self.wsl["WslLoggedRunner"](
            cmd, log_path, exit_path, q, kill_pattern="constellation_finder_v2_3.py")
        self._restore_runner = runner
        self._restore_queue = q
        runner.start()
        self._poll_restore_queue(step, "constellation")

    def _poll_restore_queue(self, step, kind):
        try:
            while True:
                item = self._restore_queue.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "__exit__":
                    self._restore_log(self.T("settings.restore_stage_done", kind=kind, code=item[1]))
                    self._on_step_stage_done(step, kind)
                    return
                self._restore_log(item)
        except queue.Empty:
            pass
        self.after(150, lambda: self._poll_restore_queue(step, kind))

    def _on_step_stage_done(self, step, kind):
        """Called once a single subprocess stage (one orchestrator_loop_v2.py run for
        "loop", one constellation_finder_v2_3.py run for "constellation") has finished for
        one step. Handles ONLY that stage's own retry-or-give-up decision -- it never
        decides what runs next itself. Control always goes back to _drive_restore() at
        the end (the one place that decides: this step's other aspect, another floor's
        same-phase work, or moving into the next phase) -- launching this step's hits
        directly here would break the windows-before-hits ordering (see that method's
        docstring)."""
        job = self._active_job
        self._active_job_runner_kind = None
        self._restore_runner = None
        if job is None:
            return
        portal_folder = self.wsl["get_portal_folder"]()
        if kind == "loop":
            current = FloorSnapshot.scan(portal_folder, step.base_exponent)
            step.missing_windows = sorted(set(step.missing_windows) - set(current.filenames))
            if self._restore_low_floor_batch:
                self._reconcile_low_floor_siblings(job, step, portal_folder)
        else:
            current_c = ConstellationSnapshot.scan(portal_folder, step.base_exponent)
            step.missing_hits = sorted(set(step.missing_hits) - set(current_c.hit_files))
        job.save()

        if job.status != STATUS_RUNNING:
            return  # paused/cancelled while the subprocess was running -- don't auto-continue

        retry_key = (step.base_exponent, kind)
        retries = self._step_retry_counts.get(retry_key, 0)
        still_needs = step.needs_windows if kind == "loop" else step.needs_hits
        if still_needs and retries < self.MAX_STAGE_RETRIES:
            self._step_retry_counts[retry_key] = retries + 1
            if kind == "loop":
                self._restore_log(self.T(
                    "settings.restore_retry_windows", base_exponent=step.base_exponent,
                    count=len(step.missing_windows)))
                self._drive_windows_phase(step)
            else:
                self._start_constellation_for_step(step)
            return
        if still_needs:
            self._restore_log(self.T(
                "settings.restore_gave_up", base_exponent=step.base_exponent,
                windows=len(step.missing_windows), hits=len(step.missing_hits)))
            (self._given_up_windows if kind == "loop" else self._given_up_hits).add(
                step.base_exponent)
        self._drive_restore()

    def _on_restore_job_finished(self):
        self._restore_log(self.T("settings.restore_job_finished", name=self._active_job.backup_name))
        self._active_job = None
        self._update_restore_progress()
        self._update_restore_buttons()
        self._scan_incomplete_restores()
        # reload_primes_tree()/reload_constellations_tree() below now run the leftover-
        # empty-directory sweep themselves (prune_empty_floor_dirs(), see that function's
        # docstring) on EVERY refresh, not just after a restore -- delete_extra_files() can
        # leave behind directories it never itself touched (e.g. a constellations/k{K}/
        # variant{V}/ leaf that had nothing to delete), and restore isn't the only caller
        # that can leave a floor's folder empty. Was a one-off call made right here; moved
        # so a manual Refresh, a finished generation run, or a delete-all all get the same
        # guarantee instead of only restore.
        # Same reasoning as _report_delete_result's own call to these two -- a restore run
        # regenerates/removes real files on disk (source_primes windows, constellation hit
        # files) that the Prime numbers / Constellations tabs had no way to notice on their
        # own, so without this they'd keep showing pre-restore counts until a manual
        # Refresh click.
        self.wsl["reload_primes_tree"]()
        self.wsl["reload_constellations_tree"]()

    def _scan_incomplete_restores(self):
        portal_folder = self.wsl["get_portal_folder"]()
        backups_dir = os.path.join(portal_folder, "_backups")
        found = []
        if os.path.isdir(backups_dir):
            for fname in sorted(os.listdir(backups_dir)):
                if not fname.endswith(".restore.json"):
                    continue
                path = os.path.join(backups_dir, fname)
                try:
                    job = RestoreJob.load(path)
                except (OSError, ValueError, KeyError):
                    continue
                if job is not None and job.pending_steps:
                    found.append(job)
        self._incomplete_jobs = found
        self.incomplete_listbox.delete(0, "end")
        for job in found:
            done, total = job.progress
            self.incomplete_listbox.insert(
                "end", f"{job.backup_name}  [{job.status}]  {done}/{total}")

    # ---- restore: progress/log widgets ---------------------------------------------------

    def _update_restore_buttons(self):
        job = self._active_job
        running_now = job is not None and job.status == STATUS_RUNNING
        paused = job is not None and job.status == STATUS_PAUSED
        self.restore_pause_btn.configure(state="normal" if running_now else "disabled")
        self.restore_resume_btn.configure(state="normal" if paused else "disabled")
        self.restore_cancel_btn.configure(
            state="normal" if (running_now or paused) else "disabled")

    def _update_restore_progress(self):
        job = self._active_job
        if job is None:
            self.restore_progress.configure(maximum=1, value=0)
            self.restore_progress_label.set("")
            return
        done, total = job.progress
        self.restore_progress.configure(maximum=max(1, total), value=done)
        self.restore_progress_label.set(self.T(
            "settings.restore_progress_label", name=job.backup_name, done=done, total=total,
            status=job.status))

    def _restore_log(self, text):
        self.restore_console.append(text)
