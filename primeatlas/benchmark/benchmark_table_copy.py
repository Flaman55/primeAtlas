"""BenchmarkTab mixin: copying runs of the run table to the clipboard (table_copy.py).

The tree's first column holds a box per floor and run. A click on a run's box marks or unmarks
it; a click on a floor's box marks all its runs the filter keeps, collapsed or open (unmarks
them when all are marked); the click neither selects nor scrolls the row; Space toggles the
focused row's box. A click on the column's heading marks every run the filter keeps (unmarks
them all when all are marked); the heading shows the same box for the whole table. Ctrl+C copies the marked runs of every floor as a Markdown table,
Ctrl+Shift+C as tab-separated values, then unmarks them. With nothing marked the selection is
copied: a selected floor, or its stats row, stands for every run the filter keeps on it, and a
run is copied once however it is selected; an empty selection leaves the clipboard as it was.
A table rebuild (reload, filter change) unmarks everything. The row above the table names both
keys, with an InfoTip on how the copy is made and formatted.

Uses the tab's benchmark_tree, _tree_item_rows, _tree_floor_nodes, _benchmark_rows_by_floor,
_copy_to_clipboard() and T.
"""
from tkinter import ttk

from ..core.info_tip import InfoTip
from . import table_copy

CHECK_WIDTH = 50


class BenchmarkTableCopy:

    def _build_table_copy_hint(self, row):
        """The keys' one-line hint and its InfoTip, at the right end of `row`."""
        T = self.T
        self.copy_info = InfoTip(row, lambda: T("bench.copy_tip"))
        self.copy_info.label.pack(side="right", padx=(4, 0))
        self.copy_hint_label = ttk.Label(row, text=T("bench.copy_hint"))
        self.copy_hint_label.pack(side="right")

    def _bind_table_copy(self):
        self._copy_marks = set()
        tree = self.benchmark_tree
        # Caps Lock gives Control-C without Shift: still Markdown.
        for sequence, fmt in (("<Control-c>", table_copy.MARKDOWN),
                              ("<Control-C>", table_copy.MARKDOWN),
                              ("<Control-Shift-c>", table_copy.TSV),
                              ("<Control-Shift-C>", table_copy.TSV)):
            tree.bind(sequence, lambda _e, f=fmt: self._copy_table_selection(f) or "break")
        tree.bind("<Button-1>", self._on_copy_box_click, add="+")
        tree.bind("<space>", lambda _e: self._toggle_copy_mark(tree.focus()) or "break")

    def _set_copy_columns(self, columns):
        """The tree's `columns` with the box column shown first. It is the last of the
        columns, so the rows' values (the table's columns) leave it empty until marked."""
        tree = self.benchmark_tree
        tree["columns"] = tuple(columns) + (table_copy.CHECK_COLUMN,)
        tree["displaycolumns"] = (table_copy.CHECK_COLUMN,) + tuple(columns)
        tree.heading(table_copy.CHECK_COLUMN, text=self.T("bench.copy_column"),
                     command=self._toggle_all_copy_marks)
        tree.column(table_copy.CHECK_COLUMN, width=CHECK_WIDTH, anchor="center", stretch=False)

    def _clear_copy_marks(self):
        self._copy_marks = set()
        self._show_copy_marks()

    def _all_table_runs(self):
        return [row for rows in self._benchmark_rows_by_floor.values() for row in rows]

    def _toggle_all_copy_marks(self):
        self._copy_marks = table_copy.toggle_floor(self._all_table_runs(), self._copy_marks)
        self._show_copy_marks()

    def _show_copy_marks(self):
        """The heading's box, every floor's box and the boxes of the runs on its open page."""
        tree, rows_by_floor = self.benchmark_tree, self._benchmark_rows_by_floor
        label = self.T("bench.copy_column")
        box = table_copy.floor_mark(self._all_table_runs(), self._copy_marks)
        tree.heading(table_copy.CHECK_COLUMN, text=f"{box} {label}" if box else label)
        for node, floor in self._tree_floor_nodes.items():
            tree.set(node, table_copy.CHECK_COLUMN,
                     table_copy.floor_mark(rows_by_floor.get(floor, []), self._copy_marks))
        for item, row in self._tree_item_rows.items():
            tree.set(item, table_copy.CHECK_COLUMN,
                     table_copy.MARKED if id(row) in self._copy_marks else table_copy.UNMARKED)

    def _on_copy_box_click(self, event):
        tree = self.benchmark_tree
        if (tree.identify_region(event.x, event.y) != "cell"
                or tree.identify_column(event.x) != "#1"):
            return None
        return "break" if self._toggle_copy_mark(tree.identify_row(event.y)) else None

    def _toggle_copy_mark(self, item):
        """Toggles the box of `item`, a run or a floor; False for any other row."""
        if item in self._tree_item_rows:
            self._copy_marks ^= {id(self._tree_item_rows[item])}
        elif item in self._tree_floor_nodes:
            rows = self._benchmark_rows_by_floor.get(self._tree_floor_nodes[item], [])
            self._copy_marks = table_copy.toggle_floor(rows, self._copy_marks)
        else:
            return False
        self._show_copy_marks()
        return True

    def _copy_table_selection(self, fmt):
        rows = table_copy.marked_in_order(self._benchmark_rows_by_floor, self._copy_marks)
        if not rows:
            rows = self._selected_runs()
        self._copy_to_clipboard(table_copy.table_text(rows, fmt, self.T))
        if self._copy_marks:
            self._clear_copy_marks()

    def _selected_runs(self):
        tree = self.benchmark_tree
        floors, runs = set(), []
        for item in tree.selection():
            if item in self._tree_item_rows:
                runs.append(self._tree_item_rows[item])
                continue
            node = item if item in self._tree_floor_nodes else tree.parent(item)
            if node in self._tree_floor_nodes:
                floors.add(self._tree_floor_nodes[node])
        return table_copy.runs_in_order(self._benchmark_rows_by_floor, floors, runs)
