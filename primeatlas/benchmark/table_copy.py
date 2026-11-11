"""The Benchmark run table's selection as clipboard text.

runs_in_order(): the runs of the selected floors and the selected single runs, each once, in
table order. table_text(): those runs in the export columns (table_columns.EXPORT_COLUMNS:
floor, run, engine, then the tree's), header first, in one of two formats:
  - MARKDOWN: a pipe table of the shown values (table_columns.shown()), each column padded to
    its widest cell so it also reads as plain text where a chat does not render Markdown;
  - TSV: tab-separated raw values (table_columns.raw(), as the CSV export writes them), so a
    spreadsheet reads the numbers.
A column no copied run has a value in is left out.
Marks: the runs ticked for copying, a set of id(row) over the rows of one table build.
floor_mark() is a floor's box, toggle_floor() its click (both also serve the whole table's
box in the column heading), marked_in_order() the marked runs in
table order. No tkinter here.
"""
from . import table_columns

MARKDOWN, TSV = "markdown", "tsv"
CHECK_COLUMN = "copy"   # the tree's box column; not a log or export column
UNMARKED, MARKED, PARTIAL = "☐", "☑", "▣"


def runs_in_order(rows_by_floor, floors, runs):
    """Rows of every floor in `floors` and the rows in `runs`, each once, floors ascending and
    runs in their floor's order (`rows_by_floor`: {floor: [row, ...]})."""
    picked = {id(row) for row in runs}
    return [row for floor in sorted(rows_by_floor) for row in rows_by_floor[floor]
            if floor in floors or id(row) in picked]


def floor_mark(rows, marks):
    """The box of a floor of `rows`: MARKED when all are in `marks`, PARTIAL when some,
    UNMARKED when none; "" for a floor without runs."""
    if not rows:
        return ""
    marked = sum(id(row) in marks for row in rows)
    if marked == len(rows):
        return MARKED
    return PARTIAL if marked else UNMARKED


def toggle_floor(rows, marks):
    """`marks` after a click on the floor's box: none of `rows` when all are marked, else all
    of them; marks of other floors kept."""
    ids = {id(row) for row in rows}
    return marks - ids if ids <= marks else marks | ids


def marked_in_order(rows_by_floor, marks):
    """The rows in `marks`, floors ascending and runs in their floor's order."""
    return [row for floor in sorted(rows_by_floor) for row in rows_by_floor[floor]
            if id(row) in marks]


def _escape(cell):
    return cell.replace("|", "\\|")


def table_text(rows, fmt, t):
    """`rows` as MARKDOWN or TSV text (see the module docstring); "" for no rows."""
    if not rows:
        return ""
    columns = [c for c in table_columns.EXPORT_COLUMNS
               if any(table_columns.raw(row, c) for row in rows)]
    header = [t(table_columns.header_key(c)) for c in columns]
    if fmt == TSV:
        body = [[table_columns.raw(row, c) for c in columns] for row in rows]
        return "\n".join("\t".join(line) for line in [header] + body)
    table = [[_escape(cell) for cell in line]
             for line in [header] + [[table_columns.shown(row, c, t) for c in columns]
                                     for row in rows]]
    widths = [max(len(line[i]) for line in table) for i in range(len(columns))]

    def line_text(cells):
        return "| " + " | ".join(cell.ljust(w) for cell, w in zip(cells, widths)) + " |"

    separator = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    return "\n".join([line_text(table[0]), separator] + [line_text(line) for line in table[1:]])
