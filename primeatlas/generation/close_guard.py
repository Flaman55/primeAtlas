"""
close_guard.py -- closing the main window while a Generation-tab job runs
(CLOSE_GUARD_PLAN.md sections 1 and 3).

request_close() is the main window's WM_DELETE_WINDOW handler. With no job it closes at
once. Otherwise a Yes/No dialog (default No) lists each running job with its stage
(run_guard.job_stage); on Yes every job gets the Generation tab's save-point stop
(stop_job_for_close) and a StoppingWindow shows the live stages until each job has
settled (its runner finished and its output drained, so totals are bumped), saves each
stopped job's console to .generation_logs/closed_<job>_<UTC>.log and closes the app.
"Close now" hard stops what is left; the next start repairs it (run_guard.py).

The Generation tab is used through this interface only: _loop_runner / _const_runner /
_ktuple_runner, loop_console / const_console / ktuple_console (get_text()),
loop_run_info (dict with "engine"), stop_job_for_close(key), job_settled(key),
_get_portal_folder().
"""
import os
import tkinter as tk
from datetime import datetime, timezone
from tkinter import messagebox, ttk

from .wsl_command import GENERATION_LOGS_DIRNAME
from .run_guard import job_stage

# (job key, runner attribute, console attribute) of the jobs the guard watches.
_JOBS = (
    ("generation", "_loop_runner", "loop_console"),
    ("constellation", "_const_runner", "const_console"),
    ("ktuple", "_ktuple_runner", "ktuple_console"),
)
_STAGE_KEYS = ("idle", "sieving", "counting", "checking", "verifying", "starting_batch",
               "searching", "line")

STRING_KEYS = (
    ("close.dialog_title", "close.question", "close.kept_note", "close.v5_sieve_note",
     "close.stopping_title", "close.stopping_intro", "close.stopping_job", "close.close_now")
    + tuple(f"close.job_{key}" for key, _r, _c in _JOBS)
    + tuple(f"close.job_name_{key}" for key, _r, _c in _JOBS)
    + tuple(f"close.stage_{key}" for key in _STAGE_KEYS)
)

POLL_MS = 200
# Engines that write a batch's windows only after sieving all of it (close.v5_sieve_note).
SIEVE_THEN_WRITE_ENGINES = ("v5", "v6")

_active = None  # the open StoppingWindow, if any


def active_stopping_window():
    return _active


def running_jobs(gen_tab):
    """[(key, runner)] of the jobs whose runner is running."""
    jobs = []
    for key, runner_attr, _console_attr in _JOBS:
        runner = getattr(gen_tab, runner_attr)
        if runner is not None and runner.is_running():
            jobs.append((key, runner))
    return jobs


def _stage(runner):
    return job_stage(runner.tail_lines)


def _stage_text(stage, T):
    key, detail = stage
    return T(f"close.stage_{key}", detail=detail or "")


def close_message(gen_tab, jobs, T):
    lines = []
    for key, runner in jobs:
        stage = _stage(runner)
        lines.append(T(f"close.job_{key}", stage=_stage_text(stage, T)))
        if (key == "generation" and stage[0] == "sieving"
                and (gen_tab.loop_run_info or {}).get("engine") in SIEVE_THEN_WRITE_ENGINES):
            lines.append(T("close.v5_sieve_note"))
    return "\n".join(lines) + "\n\n" + T("close.kept_note") + "\n\n" + T("close.question")


def request_close(root, gen_tab, T, close_app=None, ask=None, poll_ms=POLL_MS):
    """Returns "closed", "kept" (answer No) or "stopping" (a StoppingWindow is open,
    including a repeated request while it is)."""
    global _active
    close_app = close_app or root.destroy
    if _active is not None:
        return "stopping"
    jobs = running_jobs(gen_tab)
    if not jobs:
        close_app()
        return "closed"
    title, message = T("close.dialog_title"), close_message(gen_tab, jobs, T)
    if ask is None:
        answer = messagebox.askyesno(title, message, icon="warning", default="no", parent=root)
    else:
        answer = ask(title, message)
    if not answer:
        return "kept"
    for key, _runner in jobs:
        gen_tab.stop_job_for_close(key)
    _active = StoppingWindow(root, gen_tab, [key for key, _r in jobs], T, close_app, poll_ms)
    return "stopping"


def _save_console_logs(gen_tab, keys):
    logs_dir = os.path.join(gen_tab._get_portal_folder(), GENERATION_LOGS_DIRNAME)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    consoles = {key: console_attr for key, _r, console_attr in _JOBS}
    for key in keys:
        try:
            os.makedirs(logs_dir, exist_ok=True)
            with open(os.path.join(logs_dir, f"closed_{key}_{stamp}.log"), "w",
                      encoding="utf-8", newline="") as f:
                f.write(getattr(gen_tab, consoles[key]).get_text())
        except OSError:
            pass  # best-effort: the storage folder may be gone; closing must still work


class StoppingWindow:
    """Modal-less progress window shown while the stopped jobs settle."""

    def __init__(self, root, gen_tab, keys, T, close_app, poll_ms):
        self.gen_tab, self.keys, self.T = gen_tab, keys, T
        self._close_app, self._poll_ms = close_app, poll_ms
        self._runner_attrs = {key: runner_attr for key, runner_attr, _c in _JOBS}
        self.win = tk.Toplevel(root)
        self.win.title(T("close.stopping_title"))
        self.win.transient(root)
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)  # only Close now leaves early
        body = ttk.Frame(self.win, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=T("close.stopping_intro"), wraplength=420,
                  justify="left").pack(anchor="w")
        self._status = tk.StringVar()
        ttk.Label(body, textvariable=self._status, justify="left",
                  wraplength=420).pack(anchor="w", pady=(8, 8))
        ttk.Button(body, text=T("close.close_now"), command=self.close_now).pack(anchor="e")
        self._after_id = None
        self._refresh()
        self._after_id = self.win.after(self._poll_ms, self._poll)

    def _runner(self, key):
        return getattr(self.gen_tab, self._runner_attrs[key])

    def status_text(self):
        return self._status.get()

    def _refresh(self):
        lines = []
        for key in self.keys:
            runner = self._runner(key)
            stage = _stage(runner) if runner is not None else ("idle", None)
            lines.append(self.T("close.stopping_job", job=self.T(f"close.job_name_{key}"),
                                stage=_stage_text(stage, self.T)))
        self._status.set("\n".join(lines))

    def _poll(self):
        self._after_id = None
        self._refresh()
        if all(self.gen_tab.job_settled(key) for key in self.keys):
            self._finish()
            return
        self._after_id = self.win.after(self._poll_ms, self._poll)

    def close_now(self):
        """Hard stop of every job still running, then close."""
        for key in self.keys:
            runner = self._runner(key)
            if runner is not None and runner.is_running():
                runner.stop()
        self._finish()

    def _finish(self):
        global _active
        if self._after_id is not None:
            self.win.after_cancel(self._after_id)
            self._after_id = None
        _save_console_logs(self.gen_tab, self.keys)
        self.win.destroy()
        _active = None
        self._close_app()
