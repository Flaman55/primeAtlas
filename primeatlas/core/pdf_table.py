"""
pdf_table.py -- the paginated data table of the app's PDF reports (Benchmark log,
Constellation records), drawn with pdf_writer.py's operators.

Every cell is printed in full: a column is as wide as its longest value, and a header
wraps onto extra lines at its "_" separators instead of being cut. When the columns
together are wider than the page, the table is split into column bands; every band
starts with the key columns (e.g. the run timestamp and floor), so a row of one band is
found again in the next. The bands of one row chunk are printed on consecutive pages.

Text is set in the fixed-width Courier / Courier-Bold, so widths are exact
(CHAR_WIDTH x font size per character). Pure logic, no tkinter.
"""
from .pdf_writer import _pdf_ascii_fold, _pdf_line_op, _pdf_rect_op, _pdf_text_op

CHAR_WIDTH = 0.6   # Courier's advance width per character, in units of the font size
CELL_PAD = 2       # points left free on each side of a cell's text
HEADER_RGB = (0.90, 0.90, 0.90)
STRIPE_RGB = (0.96, 0.96, 0.96)   # every second row, to follow a row across the page
RULE_RGB = (0.75, 0.75, 0.75)     # vertical rules between columns


def cell_text(value):
    """The printed form of a cell: str(value), "" for None, diacritics folded."""
    return "" if value is None else _pdf_ascii_fold(str(value))


def wrap_header(name, max_chars):
    """`name` broken into lines of at most max_chars characters, breaking after "_"
    separators (the separator stays at the line end); a single part longer than
    max_chars stays whole on its own line."""
    parts = [p + "_" for p in name.split("_")]
    parts[-1] = parts[-1][:-1]
    lines = [""]
    for part in parts:
        if lines[-1] and len(lines[-1]) + len(part) > max_chars:
            lines.append("")
        lines[-1] += part
    return lines


def column_chars(name, rows):
    """A column's width in characters: its longest value, or its header's longest "_"
    part when that is longer, so a header never needs to break inside a word."""
    longest_value = max((len(cell_text(r.get(name))) for r in rows), default=0)
    longest_part = max(len(p) + 1 for p in name.split("_"))
    return max(1, longest_value, longest_part)


class TableLayout:
    """Column bands of one table. bands: [[column name, ...], ...], each one the key columns
    (in key_columns order) followed by its own columns in fieldnames order; widths: {name: points};
    headers: {name: [header line, ...]}; header_h: the header row height of the tallest
    band header, shared by every band so every band of a row chunk ends at the same y."""

    def __init__(self, fieldnames, rows, content_width, font_size, key_columns=()):
        self.font_size = font_size
        self.row_h = round(font_size * 1.85)
        self.line_h = font_size + 1.5
        char_w = CHAR_WIDTH * font_size
        chars = {n: column_chars(n, rows) for n in fieldnames}
        self.widths = {n: c * char_w + 2 * CELL_PAD for n, c in chars.items()}
        self.headers = {n: wrap_header(n, chars[n]) for n in fieldnames}
        self.bands = self._split(list(fieldnames), content_width,
                                 [k for k in key_columns if k in self.widths])
        lines = max((len(self.headers[n]) for n in fieldnames), default=1)
        self.header_h = lines * self.line_h + 4

    def _split(self, fieldnames, content_width, keys):
        if sum(self.widths[n] for n in fieldnames) <= content_width:
            return [keys + [n for n in fieldnames if n not in keys]]
        key_width = sum(self.widths[k] for k in keys)
        bands, band = [], []
        for name in fieldnames:
            if name in keys:
                continue
            if band and key_width + sum(self.widths[n] for n in band) + self.widths[name] \
                    > content_width:
                bands.append(band)
                band = []
            band.append(name)
        if band or not bands:
            bands.append(band)
        return [keys + b for b in bands]

    def header_ops(self, band, left, y_top):
        """Ops of one band's header row; returns (ops, y below it)."""
        width = sum(self.widths[n] for n in band)
        ops = [_pdf_rect_op(left, y_top - self.header_h, width, self.header_h,
                            fill_rgb=HEADER_RGB)]
        x = left
        for name in band:
            for i, line in enumerate(self.headers[name]):
                ops.append(_pdf_text_op(x + CELL_PAD, y_top - 2 - (i + 1) * self.line_h + 1.5,
                                        self.font_size, "Courier-Bold", line))
            x += self.widths[name]
        return ops, y_top - self.header_h

    def row_ops(self, band, left, y_top, rows):
        """Ops of `rows` under one band's header, starting at y_top: striped rows, the
        column rules, then the cell text."""
        width = sum(self.widths[n] for n in band)
        ops = [_pdf_rect_op(left, y_top - (i + 1) * self.row_h, width, self.row_h,
                            fill_rgb=STRIPE_RGB) for i in range(1, len(rows), 2)]
        x = left
        for name in band[:-1]:
            x += self.widths[name]
            ops.append(_pdf_line_op(x, y_top, x, y_top - len(rows) * self.row_h, width=0.3,
                                    rgb=RULE_RGB))
        y = y_top
        for row in rows:
            x = left
            for name in band:
                ops.append(_pdf_text_op(x + CELL_PAD, y - self.row_h + 3, self.font_size,
                                        "Courier", cell_text(row.get(name))))
                x += self.widths[name]
            y -= self.row_h
        return ops

    def rows_fitting(self, y_top, y_bottom):
        """How many rows fit between y_top (above the header) and y_bottom."""
        return max(0, int((y_top - self.header_h - y_bottom) // self.row_h))


def table_pages(layout, rows, first_ops, first_top, content_top, content_bottom, left,
                continued_title):
    """Pages (lists of ops) of the whole table. first_ops: the first page's content above
    the table (title, charts), the table starting at y first_top below it -- or, when the
    table has several bands, on the next page, so every band of a row chunk gets the same
    rows. continued_title(page_number, band_number, band_count) -> the title text of a
    page the table continues on (folded to ASCII here)."""
    n_bands = len(layout.bands)
    pages = []
    if n_bands == 1:
        fit = layout.rows_fitting(first_top, content_bottom)
        ops, y = layout.header_ops(layout.bands[0], left, first_top)
        pages.append(first_ops + ops + layout.row_ops(layout.bands[0], left, y, rows[:fit]))
        rows = rows[fit:]
    else:
        pages.append(list(first_ops))
    table_top = content_top - 22
    fit = max(1, layout.rows_fitting(table_top, content_bottom))
    while rows:
        chunk, rows = rows[:fit], rows[fit:]
        for b, band in enumerate(layout.bands):
            page = [_pdf_text_op(left, content_top - 12, 10, "Helvetica-Bold",
                                 _pdf_ascii_fold(continued_title(len(pages) + 1, b + 1,
                                                                 n_bands)))]
            ops, y = layout.header_ops(band, left, table_top)
            pages.append(page + ops + layout.row_ops(band, left, y, chunk))
    return pages
