"""
computer_window.py -- ComputerWindow, the window a click on a Benchmark run's computer cell
opens (computer_cell.py): the computer's title (computer_table.heading()) and its table
(computer_table.table()), a column per entry of its history in benchmark_machines.json and a
row per field; for an id without an entry, a message saying the file has no data of it.
Read-only: the typed values are edited from About > This computer.
"""
import tkinter as tk
from tkinter import ttk

from ..core.widgets import StripedTreeview
from . import computer_table

FIELD_WIDTH = 160
ENTRY_WIDTH = 220
WRAP = 520


class ComputerWindow(tk.Toplevel):
    def __init__(self, parent, T, machine_id, history, label):
        super().__init__(parent)
        self.machine_id = machine_id
        self.title(T("computer.window_title", name=label))
        self.transient(parent.winfo_toplevel())
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=computer_table.heading(machine_id, history, T),
                  wraplength=WRAP, justify="left").pack(anchor="w", pady=(0, 8))
        shown = computer_table.table(history, T)
        self.headers = None
        self.message = ""
        self.tree = None
        if shown is None:
            self.message = T("computer.no_data")
            ttk.Label(body, text=self.message, wraplength=WRAP,
                      justify="left").pack(anchor="w")
        else:
            self.headers, rows = shown
            columns = [f"c{i}" for i in range(len(self.headers))]
            self.tree = StripedTreeview(body, columns=columns, show="headings",
                                        height=len(rows))
            for i, (column, text) in enumerate(zip(columns, self.headers)):
                self.tree.heading(column, text=text)
                self.tree.column(column, width=FIELD_WIDTH if i == 0 else ENTRY_WIDTH,
                                 anchor="w", stretch=False)
            for row in rows:
                self.tree.insert("", "end", values=row)
            self.tree.pack(fill="both", expand=True)
        ttk.Button(body, text=T("bench.filter_close"),
                   command=self.destroy).pack(anchor="e", pady=(10, 0))
