"""
computer_names.py -- how the Benchmark tab, its filter and its exports name the computer a
run ran on, from the run's machine_id and its entry of benchmark_machines.json
(core/machines_file.py).

annotate() gives every row of the log, under ENTRY_KEY (not a log column), the entry valid at
its run time (machines_file.entry_for()), None without one. From it:
- cell_label(): the table cell, the short CPU name and the id's first ID_CHARS characters
  ("Ryzen 9 5900X (3f9a0c)"); the id alone without an entry or a CPU name; "" without
  machine_id;
- filter_label(): the Filter window's value, the cell with the RAM ("Ryzen 9 5900X ·
  64.0 GiB DDR4-3600 (3f9a0c)"), so a RAM change on one computer is a value of its own;
  parts not known are left out.
short_cpu_name() drops what Windows adds to the model (maker, (R)/(TM), "CPU", "Processor",
"N-Core", the clock after "@", "with ... Graphics"). No tkinter here.
"""
import re

from ..core import machines_file, number_format

ENTRY_KEY = "_computer_entry"
ID_CHARS = 6
GIB = 1024 ** 3
SEPARATOR = " · "

_CUT = re.compile(r"\s+(?:@|with\s|w/\s).*$", re.IGNORECASE)
_DROPPED = re.compile(r"\((?:R|TM)\)|[®™]|\b(?:AMD|Intel|CPU|Processor|\d+-Core)\b",
                      re.IGNORECASE)


def short_cpu_name(name):
    """The CPU model without what Windows adds to it; a name made only of those words stays
    as it is; "" for none."""
    text = " ".join(str(name or "").split())
    short = " ".join(_DROPPED.sub(" ", _CUT.sub("", text)).split())
    return short or text


def id_tag(machine_id):
    return str(machine_id or "").strip()[:ID_CHARS]


def annotate(rows, machines):
    """Sets ENTRY_KEY of every row to the entry its run ran with, None without one."""
    for row in rows:
        row[ENTRY_KEY] = machines_file.entry_for(
            machines, str(row.get("machine_id") or "").strip(), row.get("run_timestamp_utc"))


def _named(name, tag):
    return f"{name} ({tag})" if name else tag


def entry_label(machine_id, entry):
    """The cell of a run of `machine_id` with `entry` (None for none)."""
    auto = (entry or {}).get("auto") or {}
    return _named(short_cpu_name(auto.get("cpu_name")), id_tag(machine_id))


def cell_label(row):
    return entry_label(row.get("machine_id"), row.get(ENTRY_KEY))


def filter_label(row):
    tag = id_tag(row.get("machine_id"))
    auto = (row.get(ENTRY_KEY) or {}).get("auto") or {}
    ram = []
    if auto.get("ram_bytes"):
        ram.append(f"{number_format.decimal(auto['ram_bytes'] / GIB, 1)} GiB")
    kind = "-".join(str(auto[k]) for k in ("ram_type", "ram_mts") if auto.get(k))
    if kind:
        ram.append(kind)
    parts = [p for p in (short_cpu_name(auto.get("cpu_name")), " ".join(ram)) if p]
    return _named(SEPARATOR.join(parts), tag) if tag else ""
