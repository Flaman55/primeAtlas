"""
computer_pdf.py -- the "Computers" section at the end of the Benchmark PDF report: per computer
of the reported runs its title (computer_table.heading()) with a pdf_writer.Anchor named
computer_table.anchor(), the target of the runs' computer cells, then its table
(computer_table.table(), core/pdf_table.py), or a line saying the file has no data of it.
A computer whose block does not fit the rest of a page starts the next one. Pure logic, no
tkinter.
"""
from ..core.pdf_table import TableLayout
from ..core.pdf_writer import Anchor, _pdf_ascii_fold, _pdf_text_op
from . import computer_table

FONT_SIZE = 6.5
HEADING_H = 16
GAP = 12


def _block(machine_id, history, t, width):
    """(height, draw(left, top) -> ops) of one computer."""
    title = _pdf_ascii_fold(computer_table.heading(machine_id, history, t))
    shown = computer_table.table(history, t)
    if shown is None:
        message = _pdf_ascii_fold(t("computer.no_data"))
        layout, rows = None, []
        height = HEADING_H + 12
    else:
        headers = [_pdf_ascii_fold(h) for h in shown[0]]
        rows = [dict(zip(headers, line)) for line in shown[1]]
        layout = TableLayout(headers, rows, width, FONT_SIZE, headers[:1])
        band_h = layout.header_h + len(rows) * layout.row_h
        height = HEADING_H + len(layout.bands) * (band_h + 4)

    def draw(left, top):
        ops = [Anchor(computer_table.anchor(machine_id), top),
               _pdf_text_op(left, top - 11, 10, "Helvetica-Bold", title)]
        y = top - HEADING_H
        if layout is None:
            return ops + [_pdf_text_op(left, y - 9, 8, "Helvetica", message)]
        for band in layout.bands:
            header, y = layout.header_ops(band, left, y)
            ops += header + layout.row_ops(band, left, y, rows)
            y -= len(rows) * layout.row_h + 4
        return ops

    return height, draw


def computer_pages(machine_ids, machines, t, left, width, top, bottom):
    """Pages (lists of ops) of the section for `machine_ids`; [] without computers."""
    if not machine_ids:
        return []
    page = [_pdf_text_op(left, top - 12, 12, "Helvetica-Bold",
                         _pdf_ascii_fold(t("computer.section_title")))]
    pages = [page]
    y = top - 22
    for machine_id in machine_ids:
        height, draw = _block(machine_id, machines.get(machine_id) or [], t, width)
        if y - height < bottom and len(page) > 1:
            page = []
            pages.append(page)
            y = top
        page += draw(left, y)
        y -= height + GAP
    return pages
