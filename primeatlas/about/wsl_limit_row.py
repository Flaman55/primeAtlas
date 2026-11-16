"""
wsl_limit_row.py -- WslLimitRow, the About tab's row that changes the WSL RAM limit: a whole-GB
number field (WSL's default, half the Windows RAM, up to the whole RAM), the proposed limit (wslconfig_edit.proposed_limit_gib) and
a Save button.

show(info) fills it from a system_info.SystemInfo: the field gets the .wslconfig memory= in
whole GB when set, else the proposal. save():
  1. refuses a field with no usable value;
     a limit above the proposal (wslconfig_edit.is_risky) first gets a warning, No by default:
     Windows short of RAM can freeze or switch off;
  2. when the value differs from the file, asks with the file's path, the changed lines and
     the backup it leaves, then writes (wslconfig_edit.apply_change);
  3. the new limit applies when WSL starts again: while a Generation job runs (running_jobs())
     WSL is not restarted and a note says so; otherwise it asks to restart WSL now (it stops
     every WSL program, Atlas's or not) and runs wslconfig_edit.shutdown_wsl() in the
     background.
A value equal to the file skips step 2, so Save also restarts WSL after a change made before.
on_saved() (the tab reading the hardware again) follows a write or a restart.

The dialogs and the shutdown are attributes (ask, warn, info, error, shutdown) a test replaces.
"""
import tkinter as tk
from tkinter import messagebox, ttk

from primeatlas.about import system_info, wslconfig_edit
from primeatlas.core import number_field
from primeatlas.core.background import run_in_background

GIB = wslconfig_edit.GIB


class WslLimitRow(ttk.Frame):
    def __init__(self, parent, T, running_jobs=lambda: [], path=None, on_saved=None):
        super().__init__(parent)
        self.T = T
        self._running_jobs = running_jobs
        self._path = path
        self._on_saved = on_saved or (lambda: None)
        self._ram = None
        self._min_gib = None
        self._max_gib = None
        self.ask = messagebox.askyesno
        self.warn = _warn
        self.info = messagebox.showinfo
        self.error = messagebox.showerror
        self.shutdown = wslconfig_edit.shutdown_wsl
        self.value_var = tk.StringVar(self)
        ttk.Label(self, text=T("about.wsl_limit_label")).pack(side="left")
        self.entry = ttk.Entry(self, textvariable=self.value_var, width=6)
        self.entry.pack(side="left", padx=(6, 2))
        self.field = number_field.attach(self.entry, T, minimum=lambda: self._min_gib,
                                         maximum=lambda: self._max_gib)
        ttk.Label(self, text=T("about.wsl_limit_unit")).pack(side="left")
        self.save_button = ttk.Button(self, text=T("about.wsl_limit_save"), command=self.save)
        self.save_button.pack(side="left", padx=(8, 8))
        self.proposal_label = ttk.Label(self, text="", style="Hint.TLabel")
        self.proposal_label.pack(side="left")

    def path(self):
        return self._path or system_info.wslconfig_path()

    def show(self, info):
        ram = info.windows.ram_total
        self._ram = ram
        self._min_gib = wslconfig_edit.min_limit_gib(ram)
        self._max_gib = wslconfig_edit.max_limit_gib(ram)
        proposal = wslconfig_edit.proposed_limit_gib(ram)
        self.proposal_label.configure(text=_proposal_text(self.T, proposal) if proposal else "")
        current = info.wslconfig.memory_bytes
        shown = round(current / GIB) if current else proposal
        self.value_var.set("" if shown is None else str(shown))
        self.field.refresh(at_once=True)

    def save(self):
        T = self.T
        title = T("about.wsl_limit_title")
        if number_field.refuse_problem([self.value_var], T, title):
            return
        gib = self.field.reading.value
        if not isinstance(gib, int):
            self.error(title, T("about.wsl_limit_empty"))
            return
        if wslconfig_edit.is_risky(gib, self._ram):
            ram_gib = round(self._ram / GIB)
            reserve = ram_gib - wslconfig_edit.proposed_limit_gib(self._ram)
            if not self.warn(title, T("about.wsl_limit_risky", gib=gib,
                                      left=max(0, ram_gib - gib), reserve=reserve)):
                self.entry.focus_set()
                return
        try:
            change = wslconfig_edit.plan_change(self.path(), gib)
        except (OSError, UnicodeDecodeError) as exc:
            self.error(title, T("about.wsl_limit_read_failed", path=self.path(), error=exc))
            return
        if change.changed:
            backup = (T("about.wsl_limit_backup_note") if change.existed
                      else T("about.wsl_limit_new_file_note"))
            question = T("about.wsl_limit_confirm", path=change.path,
                         diff="\n".join(change.diff_lines()), backup=backup)
            if not self.ask(title, question):
                return
            try:
                wslconfig_edit.apply_change(change)
            except wslconfig_edit.FileChangedError:
                self.error(title, T("about.wsl_limit_file_changed", path=change.path))
                return
            except OSError as exc:
                self.error(title, T("about.wsl_limit_write_failed", path=change.path, error=exc))
                return
        self._offer_restart(title, written=change.changed)

    def _offer_restart(self, title, written):
        T = self.T
        jobs = self._running_jobs()
        if jobs:
            names = ", ".join(T(f"close.job_name_{key}") for key, _runner in jobs)
            self.info(title, T("about.wsl_limit_run_active", jobs=names))
        elif self.ask(title, T("about.wsl_limit_restart_question")):
            def done(ok, error):
                if error is not None or not ok:
                    self.error(title, T("about.wsl_limit_restart_failed"))
                self._on_saved()
            shutdown = self.shutdown
            run_in_background(self, lambda _report: shutdown(), on_done=done)
            return
        else:
            self.info(title, T("about.wsl_limit_next_start"))
        if written:
            self._on_saved()


def _warn(title, text):
    return messagebox.askyesno(title, text, icon=messagebox.WARNING, default=messagebox.NO)


def _proposal_text(T, gib):
    return T("about.wsl_limit_proposal", gib=gib, share=round(100 * wslconfig_edit.RESERVE_SHARE),
             minimum=wslconfig_edit.RESERVE_MIN_GIB)
