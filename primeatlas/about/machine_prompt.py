"""
machine_prompt.py -- MachinePrompt, the app's one owner of this computer's entry in the
storage's benchmark_machines.json (core.machines_file) on the GUI side:

- open_details(): records the entry from core.hardware_dynamic.DETAILS when the file has
  none, then opens MachineDetailsWindow (one at a time: a second call raises the open one).
  No entry and no details read yet: a message, no window;
- after_rows(rows): after the Benchmark tab loads its rows, asks once per entry (Yes/No)
  to fill in the values Windows cannot read, when a row of this computer is there and the
  entry was not asked yet; both answers mark it asked, Yes opens the window;
- current_entry(): the entry for the About tab's lines, None without one; listeners
  (add_listener()) run each time the window closes, so the About tab shows saved values.

A broken file is never changed: a copy of it is kept and an error names it, once per
session for after_rows() (it runs after every Benchmark reload), each time for an open the
person asked for.
"""
import os
from tkinter import messagebox

from ..core import hardware_dynamic, machines_file, windows_hardware
from .machine_details_window import MachineDetailsWindow


class MachinePrompt:
    def __init__(self, parent, T, get_storage):
        self._parent = parent
        self.T = T
        self._get_storage = get_storage
        self.window = None
        self._broken_reported = False
        self._listeners = []

    def add_listener(self, listener):
        """listener() runs after the window closes (saved or not)."""
        self._listeners.append(listener)

    def _report_broken(self, storage):
        try:
            copy = os.path.basename(machines_file.preserve_corrupt(storage))
        except OSError:
            copy = "-"
        messagebox.showerror(self.T("machine.title"),
                             self.T("machine.broken", name=machines_file.FILE_NAME, copy=copy),
                             parent=self._parent)

    def current_entry(self):
        try:
            machines = machines_file.load(self._get_storage())
        except (machines_file.MachinesFileCorrupt, OSError):
            return None
        return machines_file.current(machines, windows_hardware.this_machine_id())

    def open_details(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            self.window.focus_set()
            return self.window
        storage = self._get_storage()
        machine_id = windows_hardware.this_machine_id()
        try:
            machines_file.record(storage, machine_id, hardware_dynamic.DETAILS)
            entry = machines_file.current(machines_file.load(storage), machine_id)
        except machines_file.MachinesFileCorrupt:
            self._report_broken(storage)
            return None
        if entry is None:
            messagebox.showinfo(self.T("machine.title"), self.T("machine.no_details"),
                                parent=self._parent)
            return None
        self.window = MachineDetailsWindow(self._parent, self.T, storage, machine_id, entry,
                                           on_closed=self._closed)
        return self.window

    def _closed(self):
        self.window = None
        for listener in list(self._listeners):
            listener()

    def after_rows(self, rows):
        machine_id = windows_hardware.this_machine_id()
        if not machine_id or not any(row.get("machine_id") == machine_id for row in rows):
            return
        storage = self._get_storage()
        try:
            entry = machines_file.current(machines_file.load(storage), machine_id)
        except machines_file.MachinesFileCorrupt:
            if not self._broken_reported:
                self._broken_reported = True
                self._report_broken(storage)
            return
        if not machines_file.needs_asking(entry):
            return
        cpu = (entry.get("auto") or {}).get("cpu_name") or self.T("about.system_unknown")
        fill_now = messagebox.askyesno(self.T("machine.title"), self.T("machine.ask", cpu=cpu),
                                       parent=self._parent)
        machines_file.mark_asked(storage, machine_id)
        if fill_now:
            self.open_details()
