"""
computer_cell.py -- ComputerCell, the computer cell of the Benchmark run table as a link: the
hand cursor over the "machine" cell of a run with a machine_id, and a click on it opens
ComputerWindow with that computer's entries of the storage's benchmark_machines.json, read at
the click. One window at a time: a click on the same computer raises it, on another computer
shows that one instead. A blank cell, another column, the floor and summary rows do nothing.

load() reads the file for the tab (computer_names.annotate()); a missing, broken or unreadable
file reads as no entries (machine_prompt.py reports a broken one), so the cells show the ids.
"""
from ..core import machines_file
from . import computer_names
from .computer_window import ComputerWindow

COLUMN = "machine"
HAND = "hand2"


class ComputerCell:
    def __init__(self, tree, T, get_storage, row_of):
        """row_of(item) -> the log row the tree item shows, None for other items."""
        self.tree = tree
        self.T = T
        self._get_storage = get_storage
        self._row_of = row_of
        self.window = None
        tree.bind("<Motion>", self.on_motion, add="+")
        tree.bind("<Leave>", lambda _e: self._set_cursor(""), add="+")
        tree.bind("<Button-1>", self.on_click, add="+")

    def load(self):
        try:
            return machines_file.load(self._get_storage())
        except (machines_file.MachinesFileCorrupt, OSError):
            return {}

    def _column_at(self, x):
        number = self.tree.identify_column(x)
        shown = list(self.tree["displaycolumns"])
        if shown in (["#all"], []):
            shown = list(self.tree["columns"])
        index = int(number.lstrip("#") or 0) - 1
        return shown[index] if 0 <= index < len(shown) else None

    def _row_at(self, event):
        """The run under the event when it points at the computer cell of a run with a
        machine_id, else None."""
        if self._column_at(event.x) != COLUMN:
            return None
        row = self._row_of(self.tree.identify_row(event.y))
        if row is None or not str(row.get("machine_id") or "").strip():
            return None
        return row

    def _set_cursor(self, cursor):
        if str(self.tree["cursor"]) != cursor:
            self.tree.configure(cursor=cursor)

    def on_motion(self, event):
        self._set_cursor(HAND if self._row_at(event) is not None else "")

    def on_click(self, event):
        row = self._row_at(event)
        if row is None:
            return
        machine_id = str(row["machine_id"]).strip()
        if self.window is not None and self.window.winfo_exists():
            if self.window.machine_id == machine_id:
                self.window.lift()
                return
            self.window.destroy()
        self.window = ComputerWindow(self.tree, self.T, machine_id,
                                     self.load().get(machine_id) or [],
                                     computer_names.cell_label(row))
