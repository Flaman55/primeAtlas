"""
run_guard_controls.py -- GenerationTab mixin wiring the close guard (CLOSE_GUARD_PLAN.md):
one launch path for Generation runs (stop request cleared, active-run marker written),
the save-point stop (stop request + kill of the scanner only, so the orchestrator logs
what was written; a second Stop, or an engine without the orchestrator, hard stops, on a
pt1 run with the verification that may follow it, run_verify.py), the
interface close_guard.py drives (stop_job_for_close, job_settled, loop_run_info), the
clean-up when a run ends, and the start-up recovery of a run the previous session never
saw finish (run_guard.recover_unfinished_run, off the GUI thread).
"""
import queue
import threading
import time

import generation_stop
import run_verify

from ..benchmark.benchmark import read_benchmark_log
from . import run_guard


class RunGuardControls:
    def _init_run_guard(self, runner_factory):
        """runner_factory(cmd, log_path, exit_path, queue, kill_pattern=...) builds the
        WslLoggedRunner of a Generation run."""
        self._loop_runner_factory = runner_factory
        self.loop_run_info = None       # {"engine", "scanner_pattern", ...} of the current run
        self._loop_stop_requested = False

    def _start_loop_runner(self, cmd, log_path, exit_path, kill_pattern, base_exponent,
                           engine=None, first_target_idx=0, window_m=None):
        """Starts a Generation run on self._loop_output_queue. `engine` is the orchestrator
        engine (generation_stop.SCANNER_SCRIPTS) for a save-point stop; None for engines
        that only have the hard stop."""
        portal = self._get_portal_folder()
        run_guard.clear_stop_request(portal)
        self._loop_stop_requested = False
        # Taken BEFORE starting the subprocess -- see _benchmark_rows_before_run in __init__.
        self._benchmark_rows_before_run = len(read_benchmark_log(portal)[1])
        self.loop_run_info = {
            "base_exponent": base_exponent, "engine": engine,
            "kill_pattern": kill_pattern,
            "scanner_pattern": generation_stop.scanner_script(engine) if engine else None,
            "rows_before": self._benchmark_rows_before_run,
            "first_target_idx": first_target_idx or 0, "window_m": window_m,
            "log_path": log_path, "exit_path": exit_path, "started_at": time.time(),
        }
        self._loop_runner = self._loop_runner_factory(
            cmd, log_path, exit_path, self._loop_output_queue, kill_pattern=kill_pattern)
        self._loop_runner.start()
        run_guard.write_active_run(portal, self.loop_run_info)

    def _on_stop_loop(self):
        """Stop button: the save-point stop when the run has a scanner to kill and the
        stop request could be written; a second press, or any other run, hard stops."""
        if self._loop_runner is None:
            return
        pattern = (self.loop_run_info or {}).get("scanner_pattern")
        if (pattern and not self._loop_stop_requested
                and run_guard.write_stop_request(self._get_portal_folder())
                and run_guard.kill_wsl_processes(pattern)):
            self._loop_stop_requested = True
            self.loop_status_label.set(self.T("gen.loop_stopping_save_point"))
            return
        self._loop_runner.stop()
        if (self.loop_run_info or {}).get("engine") == "pt1":
            # The verification after a pt1 run is a child of the orchestrator.
            for script in run_verify.SCRIPTS.values():
                run_guard.kill_wsl_processes(script)
        self.loop_status_label.set(self.T("common.stopping"))

    def _settle_finished_loop_run(self):
        """_on_loop_finished's first step: the run reported back, so its marker and stop
        request go; a save-point stop shows its own status."""
        portal = self._get_portal_folder()
        run_guard.clear_stop_request(portal)
        run_guard.clear_active_run(portal)
        if self._loop_stop_requested:
            self.loop_status_label.set(self.T("gen.loop_stopped_save_point"))

    def stop_job_for_close(self, key):
        """close_guard.py's stop: the same stop as each section's Stop button, with
        every follow-up launch (search retry, storage fill, batch chaining) cancelled."""
        self._pending_search_after_prime_gen = None
        self._pending_goldbach_retry_op = None
        if key == "generation":
            self._on_stop_loop()
        elif key == "constellation":
            self._on_stop_constellation()
        elif key == "ktuple":
            self._on_stop_ktuple()
        elif key == "verify":
            self._on_stop_verify()

    def job_settled(self, key):
        """True once the job's runner has finished and its output (exit sentinel included)
        has been drained, i.e. its finish callback ran."""
        runner, q = {
            "generation": (self._loop_runner, self._loop_output_queue),
            "constellation": (self._const_runner, self._const_output_queue),
            "ktuple": (self._ktuple_runner, self._ktuple_output_queue),
            "verify": (self._verify_runner, self._verify_output_queue),
        }[key]
        return runner is None or (runner.is_finished() and q.empty())

    def recover_previous_run(self, on_done=None):
        """Settles the previous session's unfinished Generation run in a background thread
        and reports it in the Generation console; on_done() runs on the GUI thread after a
        recovery that changed the totals."""
        portal = self._get_portal_folder()
        results = queue.Queue()

        def worker():
            try:
                results.put(run_guard.recover_unfinished_run(
                    portal, run_guard.wsl_process_alive, run_guard.rescan_floor_totals))
            except Exception as exc:  # noqa: BLE001 -- reported in the console, never raised
                results.put({"status": "error", "error": str(exc)})

        def poll():
            if not self.winfo_exists():
                return
            try:
                result = results.get_nowait()
            except queue.Empty:
                self.after(200, poll)
                return
            self._report_recovery(result)
            if result["status"] == "recovered" and on_done is not None:
                on_done()

        threading.Thread(target=worker, daemon=True).start()
        self.after(200, poll)

    def _report_recovery(self, result):
        status = result["status"]
        info = result.get("info") or {}
        if status == "alive":
            text = self.T("gen.recovery_alive", pattern=info.get("kill_pattern", ""))
        elif status == "recovered" and result["rescanned"]:
            text = self.T("gen.recovery_rescanned", floor=info.get("base_exponent"),
                          deleted=len(result["deleted_windows"]))
        elif status == "recovered":
            text = self.T("gen.recovery_rows", rows=result["bumped_rows"])
        elif status == "error":
            text = self.T("gen.recovery_error", error=result.get("error", ""))
        else:
            return
        self.loop_console.append(text + "\n")
