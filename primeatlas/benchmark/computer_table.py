"""
computer_table.py -- a computer's entries of benchmark_machines.json (core/machines_file.py)
as the Computer window and the report sections show them, and as the computers CSV writes
them.

- computers_in(rows): the machine_ids of the rows, in order of first appearance, each once;
- table(history, T): (headers, rows) of one computer, a column per entry headed by its
  `since` and a row per field of FIELDS (the details Windows gave, then the typed ones), a
  value not known shown as table_cells.MISSING; None for a computer without an entry;
- heading(): the title of a computer's table, its cell (computer_names.py) and its full id;
- anchor(): the link target of a computer in the HTML page and the PDF;
- computers_csv(): one line per entry (the cell, machine_id, since, edited_at, the fields as
  stored), one line with the id alone for a computer without an entry.
No tkinter here.
"""
import csv
import io
import re

from ..about.system_info_text import cache_text, gib_text
from ..core import number_format
from . import computer_names, table_cells

# (part of the entry, field) in table order.
FIELDS = (("auto", "cpu_name"), ("auto", "cpu_maker"), ("auto", "cpu_family"),
          ("manual", "architecture"), ("manual", "year"), ("auto", "cores"),
          ("auto", "threads"), ("auto", "base_mhz"), ("manual", "turbo_mhz"),
          ("auto", "l2_kb"), ("auto", "l3_kb"), ("auto", "ram_bytes"),
          ("auto", "ram_modules"), ("auto", "ram_type"), ("auto", "ram_mts"),
          ("manual", "cl"), ("manual", "xmp"))
CSV_KEYS = ("computer", "machine_id", "since", "edited_at")


def computers_in(rows):
    seen = {}
    for row in rows:
        machine_id = str(row.get("machine_id") or "").strip()
        if machine_id:
            seen.setdefault(machine_id, None)
    return list(seen)


def anchor(machine_id):
    return "pc-" + re.sub(r"[^A-Za-z0-9_-]", "_", str(machine_id))


def _value(entry, part, field):
    value = (entry.get(part) or {}).get(field)
    return None if value is None or value == "" else value


def _shown(field, value, T):
    if value is None:
        return table_cells.MISSING
    if field in ("base_mhz", "turbo_mhz"):
        return f"{number_format.whole(value)} MHz"
    if field in ("l2_kb", "l3_kb"):
        return cache_text(value, T)
    if field == "ram_bytes":
        return gib_text(value, T)
    if field == "ram_mts":
        return f"{number_format.whole(value)} MT/s"
    if field == "xmp":
        return T("machine.xmp_on") if value else T("machine.xmp_off")
    return str(value)


def table(history, T):
    if not history:
        return None
    headers = [T("computer.field")] + [entry["since"] for entry in history]
    rows = [[T(f"computer.field_{field}")]
            + [_shown(field, _value(entry, part, field), T) for entry in history]
            for part, field in FIELDS]
    return headers, rows


def heading(machine_id, history, T):
    newest = history[-1] if history else None
    return T("computer.heading", name=computer_names.entry_label(machine_id, newest),
             id=machine_id)


def computers_csv(machine_ids, machines):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_KEYS + tuple(field for _part, field in FIELDS))
    for machine_id in machine_ids:
        history = machines.get(machine_id) or []
        if not history:
            writer.writerow([computer_names.id_tag(machine_id), machine_id]
                            + [""] * (len(CSV_KEYS) - 2 + len(FIELDS)))
        for entry in history:
            values = [_value(entry, part, field) for part, field in FIELDS]
            writer.writerow([computer_names.entry_label(machine_id, entry), machine_id,
                             entry.get("since", ""), entry.get("edited_at", "")]
                            + ["" if v is None else str(v) for v in values])
    return out.getvalue()
