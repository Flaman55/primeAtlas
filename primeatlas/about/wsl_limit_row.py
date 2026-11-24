"""
wsl_limit_row.py -- WslLimitRow, the About tab's row that changes the WSL limits: a whole-GB
RAM field (WSL's default, half the Windows RAM, up to the whole RAM) with the proposed limit
(wslconfig_edit.proposed_limit_gib), a processor field (1 up to the Windows threads) with
the thread count, and one Save button for both.

show(info) fills it from a system_info.SystemInfo: the RAM field gets the .wslconfig memory=
in whole GB when set, else the proposal; the processor field gets processors= when set, else
every Windows thread (what WSL takes with no processors=). save():
  1. refuses when either field has no usable value, before reading the file;
  2. compares both with the file: a field equal to the file's value (memory= in any unit;
     no processors= counts as every thread) is left out of the change; when neither
     changes, nothing at all happens;
  3. a changed RAM limit above the proposal (wslconfig_edit.is_risky) first gets a warning,
     No by default: Windows short of RAM can freeze or switch off;
  4. asks once with the file's path, the changed lines and the backup it leaves, then writes
     both in one change (wslconfig_edit.apply_change);
  5. the new limits apply when WSL starts again: while a Generation job runs (running_jobs())
     WSL is not restarted and a note says so; otherwise it asks to restart WSL now (it stops
     every WSL program, Atlas's or not) and runs wslconfig_edit.shutdown_wsl() in the
     background.
on_saved() (the tab reading the hardware again) follows the write.
Save is disabled (and save() does nothing) until the Windows RAM and threads are known and
while the WSL restart runs.

The dialogs and the shutdown are attributes (ask, warn, info, error, shutdown) a test replaces.
"""
import tkinter as tk
from tkinter import messagebox, ttk

from primeatlas.about import system_info, wslconfig_edit
from primeatlas.core import number_field
from primeatlas.core.background import run_in_background
from primeatlas.core.wrap_label import WrapLabel

GIB = wslconfig_edit.GIB


class WslLimitRow(ttk.Frame):
    def __init__(self, parent, T, running_jobs=lambda: [], path=None, on_saved=None):
        super().__init__(parent)
        self.T = T
        self._running_jobs = running_jobs
        self._path = path
        self._on_saved = on_saved or (lambda: None)
        self._ram = None
        self._threads = None
        self._min_gib = None
        self._max_gib = None
        self._restarting = False
        self.ask = messagebox.askyesno
        self.warn = _warn
        self.info = messagebox.showinfo
        self.error = messagebox.showerror
        self.shutdown = wslconfig_edit.shutdown_wsl
        self.columnconfigure(3, weight=1)
        self.value_var = tk.StringVar(self)
        self.entry, self.field, self.proposal_label = self._field_row(
            0, "about.wsl_limit_label", self.value_var, "about.wsl_limit_unit",
            "field_tip.wsl_ram_limit", lambda: self._min_gib, lambda: self._max_gib)
        self.cpu_var = tk.StringVar(self)
        self.cpu_entry, self.cpu_field, self.cpu_hint_label = self._field_row(
            1, "about.wsl_cpu_label", self.cpu_var, "about.wsl_cpu_unit",
            "field_tip.wsl_cpu_limit", wslconfig_edit.MIN_PROCESSORS,
            lambda: wslconfig_edit.max_processors(self._threads))
        self.save_button = ttk.Button(self, text=T("about.wsl_limit_save"), command=self.save)
        self.save_button.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self._update_button()

    def _field_row(self, row, label, variable, unit, tip, minimum, maximum):
        """A label, a whole-number field, its unit and a hint on grid row `row`."""
        ttk.Label(self, text=self.T(label)).grid(row=row, column=0, sticky="w")
        entry = ttk.Entry(self, textvariable=variable, width=6)
        entry.grid(row=row, column=1, sticky="w", padx=(6, 2))
        field = number_field.attach(entry, self.T, tip, minimum=minimum, maximum=maximum)
        ttk.Label(self, text=self.T(unit)).grid(row=row, column=2, sticky="w")
        hint = WrapLabel(self, text="", style="Hint.TLabel")
        hint.grid(row=row, column=3, sticky="w", padx=(8, 0))
        return entry, field, hint

    def _can_save(self):
        return bool(self._ram) and bool(self._threads) and not self._restarting

    def _update_button(self):
        self.save_button.state(["!disabled"] if self._can_save() else ["disabled"])

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
        self._threads = info.windows.threads or None
        self.cpu_hint_label.configure(
            text=self.T("about.wsl_cpu_hint", threads=self._threads) if self._threads else "")
        processors = info.wslconfig.processors
        shown = processors if processors is not None else self._threads
        self.cpu_var.set("" if shown is None else str(shown))
        self.field.refresh(at_once=True)
        self.cpu_field.refresh(at_once=True)
        self._update_button()

    def _values(self, title):
        """(RAM GB, processors) from the fields, or None after an error naming the field."""
        T = self.T
        if number_field.refuse_problem([self.value_var, self.cpu_var], T, title):
            return None
        for field, entry, empty in ((self.field, self.entry, "about.wsl_limit_empty"),
                                    (self.cpu_field, self.cpu_entry, "about.wsl_cpu_empty")):
            if not isinstance(field.reading.value, int):
                self.error(title, T(empty))
                entry.focus_set()
                return None
        return self.field.reading.value, self.cpu_field.reading.value

    def save(self):
        if not self._can_save():
            return
        T = self.T
        title = T("about.wsl_limit_title")
        values = self._values(title)
        if values is None:
            return
        gib, cpus = values
        try:
            current = wslconfig_edit.plan_change(self.path(), {})
        except (OSError, UnicodeDecodeError) as exc:
            self.error(title, T("about.wsl_limit_read_failed", path=self.path(), error=exc))
            return
        config = system_info.parse_wslconfig(current.old_text)
        keys = {}
        if config.memory_bytes != gib * GIB:
            keys["memory"] = f"{gib}GB"
        if (config.processors if config.processors is not None else self._threads) != cpus:
            keys["processors"] = str(cpus)
        if not keys:
            return
        if "memory" in keys and wslconfig_edit.is_risky(gib, self._ram):
            ram_gib = round(self._ram / GIB)
            reserve = ram_gib - wslconfig_edit.proposed_limit_gib(self._ram)
            if not self.warn(title, T("about.wsl_limit_risky", gib=gib,
                                      left=max(0, ram_gib - gib), reserve=reserve)):
                self.entry.focus_set()
                return
        change = current.with_values(keys)
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
        self._offer_restart(title)

    def _offer_restart(self, title):
        T = self.T
        jobs = self._running_jobs()
        if jobs:
            names = ", ".join(T(f"close.job_name_{key}") for key, _runner in jobs)
            self.info(title, T("about.wsl_limit_run_active", jobs=names))
        elif self.ask(title, T("about.wsl_limit_restart_question")):
            def done(ok, error):
                self._restarting = False
                self._update_button()
                if error is not None or not ok:
                    self.error(title, T("about.wsl_limit_restart_failed"))
                self._on_saved()
            shutdown = self.shutdown
            self._restarting = True
            self._update_button()
            run_in_background(self, lambda _report: shutdown(), on_done=done)
            return
        else:
            self.info(title, T("about.wsl_limit_next_start"))
        self._on_saved()


def _warn(title, text):
    return messagebox.askyesno(title, text, icon=messagebox.WARNING, default=messagebox.NO)


def _proposal_text(T, gib):
    return T("about.wsl_limit_proposal", gib=gib, share=round(100 * wslconfig_edit.RESERVE_SHARE),
             minimum=wslconfig_edit.RESERVE_MIN_GIB)
