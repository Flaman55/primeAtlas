"""
table_cells.py -- the shown form of a Benchmark log cell in the tab's table and the report
tables (HTML page, PDF).

A run leaves a column empty when its engine does not measure that value (e.g. primesieve's
count mode has no per-window time); such a cell shows MISSING, a dash, so an absent value
is told apart from a blank one at a glance. The CSV export keeps the log's empty values.
The PDF writer folds the dash to "-" (core/pdf_writer.py: WinAnsi core fonts).
"""
MISSING = "—"


def cell(row, column):
    """`row`'s value in `column` as shown in a table: the value as text, MISSING when the
    run has none (absent, None or blank)."""
    value = row.get(column)
    text = "" if value is None else str(value)
    return text if text.strip() else MISSING
