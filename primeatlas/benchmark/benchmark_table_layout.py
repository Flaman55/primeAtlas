"""BenchmarkTab mixin: the run table's heading row and column widths.

The tree's own one-line headings give way to a WrappedHeading (core/wrapped_heading.py), whose
cells wrap a heading onto two lines. After every table build (reload, filter change) each
column is fitted (heading_wrap.fit_width()): as wide as its widest value among the runs the
filter keeps (the floor summaries in s/window, the box glyphs in the copy column) or as its
heading on two lines, whichever is wider, plus CELL_PAD. #0 fits the floor labels, the
summary labels and the run timestamps at their indent, after the open/close indicator. A width
dragged by hand holds until the next build.

Uses the tab's benchmark_tree, _benchmark_rows_by_floor, _theme_palette and T.
"""
from tkinter import font as tkfont

from ..core import heading_wrap
from ..core.wrapped_heading import WrappedHeading
from . import table_columns, table_copy

CELL_PAD = 16   # a cell's padding on both sides, with room to spare


def _style_pixels(widget, style, option, default):
    """A ttk style option's distances (e.g. "1.5p 1.5p 3p 1.5p") in pixels; `default` when the
    theme sets none. Read as text (tk.eval): the lookup's own result is the theme's shared Tcl
    object, and reading it as a list would turn it into one for every later lookup."""
    parts = widget.tk.eval(f"ttk::style lookup {style} -{option}").split()
    return [widget.winfo_fpixels(part) for part in (parts or default.split())]


def floor_summaries(rows, t):
    """The s/window summary text of each floor of `rows`, as the floor's stats row shows it."""
    by_floor = {}
    for row in rows:
        by_floor.setdefault(row.get("base_exponent"), []).append(row)
    out = []
    for floor_rows in by_floor.values():
        text = table_columns.summary_text(table_columns.stats(floor_rows), t)
        if text:
            out.append(text)
    return out


class BenchmarkTableLayout:

    def _build_table_heading(self, parent, scroll_set):
        """The heading row above the tree, packed at the top of `parent`; returns the tree's
        xscrollcommand (`scroll_set` plus the heading's redraw)."""
        self.benchmark_heading = WrappedHeading(parent, self.benchmark_tree, self._theme_palette)
        self.benchmark_heading.pack(side="top", fill="x")
        return self.benchmark_heading.follow(scroll_set)

    def _fit_table_columns(self):
        tree, T = self.benchmark_tree, self.T
        cell = tkfont.nametofont("TkDefaultFont", root=tree).measure
        heading = tkfont.nametofont("TkHeadingFont", root=tree).measure
        rows = [row for floor_rows in self._benchmark_rows_by_floor.values()
                for row in floor_rows]

        def fit(column, title, texts):
            tree.column(column, width=heading_wrap.fit_width(
                title, texts, cell, CELL_PAD, heading_measure=heading))

        for column in table_columns.TREE_COLUMNS:
            texts = [table_columns.shown(row, column, T) for row in rows]
            if column == "seconds_per_window":
                texts += floor_summaries(rows, T)
            fit(column, T(table_columns.header_key(column)), texts)
        fit(table_copy.CHECK_COLUMN, f"{table_copy.MARKED} {T('bench.copy_column')}",
            [table_copy.UNMARKED, table_copy.MARKED, table_copy.PARTIAL])
        fit("#0", T("bench.col_floor"), [])
        tree.column("#0", width=max(int(tree.column("#0", "width")),
                                    self._tree_label_width(cell) + CELL_PAD))

    def _tree_label_width(self, measure):
        """The widest #0 label at its indent, after the open/close indicator."""
        tree, T = self.benchmark_tree, self.T
        indent = sum(_style_pixels(tree, "Treeview", "indent", "20"))
        margins = _style_pixels(tree, "Treeview.Item", "indicatormargins", "2 2 4 2")
        indicator = (sum(_style_pixels(tree, "Treeview.Item", "indicatorsize", "12"))
                     + sum(margins[::2]))   # left and right of left, top, right, bottom
        widest = 0
        for floor, rows in self._benchmark_rows_by_floor.items():
            stats = table_columns.stats(rows)
            labels = [T("bench.stat_row_label", count=stats["count"]) if stats
                      else T("bench.stat_no_data")]
            labels += [row.get("run_timestamp_utc", "") for row in rows]
            floor_label = T("bench.floor_measurements", base_exponent=floor, count=len(rows))
            widest = max([widest, measure(floor_label)]
                         + [indent + measure(label) for label in labels])
        return int(round(indicator + widest))
