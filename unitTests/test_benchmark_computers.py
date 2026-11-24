"""
test_benchmark_computers.py -- the computer a benchmark run ran on, in the Benchmark tab's
table, its filter and its exports (benchmark/computer_names.py, benchmark/computer_table.py,
benchmark/computer_cell.py, benchmark/computer_window.py), from benchmark_machines.json
(core/machines_file.py).

A. The cell: the short CPU name and the first 6 characters of machine_id
   ("Ryzen 9 5900X (3f9a0c)"); the id alone for a row whose machine_id has no entry or
   whose entry has no CPU name; blank for a row without machine_id (absent, empty, blank).
   The CPU name loses the maker, (R)/(TM), "CPU", "Processor", "N-Core", the clock after
   "@" and "with ... Graphics"; a name made only of those words stays as it is.
   annotate() gives every row the entry valid at its run time: the newest one recorded by
   then, the first for a run older than every entry, none for an unknown id; the row's
   log values stay as they are. The table column "machine" shows the cell (raw and
   shown); a blank cell shows the dash.
B. The filter dimension Computer: value "Ryzen 9 5900X · 64.0 GiB DDR4-3600 (3f9a0c)"
   (parts not known are left out; the id alone without an entry; blank without
   machine_id), header in English and Polish; one PC with two entries of different RAM
   gives two values; apply() keeps the chosen computer's runs; the PDF folds "·".
C. The computer table: the computers of the given rows in order of first appearance, each
   once, none for a row without machine_id; per computer a table with a column per entry
   (headed by its "since") and a row per field (labels in English and Polish), a value
   not known shown as the dash; no table for an id without an entry. The computers CSV:
   one line per entry (computer cell, machine_id, since, edited_at, the fields raw), one
   line with the id alone for a computer without an entry.
D. HTML page and snippet: the cell is a link to its computer's section; the section
   "Computers" at the end holds a table per computer of the kept runs (none of a run the
   filter drops), each with the anchor the link names; a computer without an entry says
   so; a run without machine_id has no link; the label is HTML-escaped.
E. CSV: export() writes the runs file and next to it <name>_computers.csv, returns both
   paths; the runs file holds the cell in the machine column.
F. PDF (benchmark/computer_pdf.py for the section): pdf_writer turns a page's Link and
   Anchor items into link annotations and named
   destinations (a link whose destination is on no page is left out, the content stream
   holds operators only); the report has one link per run with a machine_id (its machine
   cell) and a Computers section with a destination per computer; a run without machine_id
   has no link; a computer that does not fit the rest of a page starts the next one; without
   machines the report still renders.
G. The tab (real display): the cell shows the label from the storage's file; the hand
   cursor over the machine cell of a run with machine_id only; a click on it opens the
   Computer window with the entry's history; another computer's cell shows that one in
   the window; a click on a blank machine cell, another column or the floor row opens
   nothing; an id without an entry opens the window saying there is no data; a broken
   file leaves the cells with the id and opens no window with data.
H. The time model still filters by machine_id (annotate() does not change it).

Usage:
    python unitTests/test_benchmark_computers.py
"""
import csv
import json
import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "constellation"))

from primeatlas.benchmark import benchmark, chart_filter, report_export, table_cells  # noqa: E402
from primeatlas.benchmark import table_columns as tc  # noqa: E402
from primeatlas.core.i18n import Translator  # noqa: E402

failures = []
DASH = table_cells.MISSING
GIB = 1024 ** 3
PC = "3f9a0c1d2e4b"
OTHER = "77aa88bb99cc"
UNKNOWN = "deadbeef0001"


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _auto(**changes):
    auto = {"cpu_name": "AMD Ryzen 9 5900X 12-Core Processor", "cpu_maker": "AuthenticAMD",
            "cpu_family": "Family 25 Model 33 Stepping 2", "cores": 12, "threads": 24,
            "base_mhz": 3701, "l2_kb": 6144, "l3_kb": 65536, "ram_bytes": 64 * GIB,
            "ram_type": "DDR4", "ram_mts": 3600, "ram_modules": 4}
    auto.update(changes)
    return {k: v for k, v in auto.items() if v is not None}


def _entry(since, auto=None, manual=None):
    blank = {"architecture": None, "year": None, "turbo_mhz": None, "cl": None, "xmp": None}
    blank.update(manual or {})
    return {"since": since, "edited_at": since, "asked": True,
            "auto": _auto() if auto is None else auto, "manual": blank}


MACHINES = {
    PC: [_entry("2026-11-01 00:00:00 UTC",
                manual={"architecture": "Zen 3", "year": 2020, "turbo_mhz": 4800, "cl": 16,
                        "xmp": True}),
         _entry("2026-11-15 00:00:00 UTC", auto=_auto(ram_bytes=128 * GIB, ram_mts=3200),
                manual={"architecture": "Zen 3", "year": 2020, "turbo_mhz": 4800})],
    OTHER: [_entry("2026-11-02 00:00:00 UTC",
                   auto=_auto(cpu_name="Intel(R) Core(TM) i7-9700K CPU @ 3.60GHz",
                              ram_bytes=None, ram_type=None, ram_mts=None))],
}


def _row(stamp, machine_id=None, floor="28", engine="v7"):
    row = {"run_timestamp_utc": stamp, "base_exponent": floor, "engine": engine,
           "engine_version": "v7.2", "numbers_processed": "10000000000",
           "total_seconds": "100.0", "sieve_seconds": "80.0", "windows_written": "1000",
           "target_idx_start": "0", "target_idx_end": "999", "threads": "24",
           "write_threads": "4", "run_status": "completed", "run_purpose": "storage"}
    if machine_id is not None:
        row["machine_id"] = machine_id
    return row


def _rows():
    return [_row("2026-11-10 10:00:00 UTC", PC), _row("2026-11-20 10:00:00 UTC", PC),
            _row("2026-11-10 11:00:00 UTC", OTHER, floor="29"),
            _row("2026-11-10 12:00:00 UTC", UNKNOWN), _row("2026-11-10 13:00:00 UTC"),
            _row("2026-10-01 00:00:00 UTC", PC)]


def part_a():
    from primeatlas.benchmark import computer_names as cn
    names = {
        "AMD Ryzen 9 5900X 12-Core Processor": "Ryzen 9 5900X",
        "Intel(R) Core(TM) i7-9700K CPU @ 3.60GHz": "Core i7-9700K",
        "13th Gen Intel(R) Core(TM) i9-13900K": "13th Gen Core i9-13900K",
        "AMD Ryzen 7 5800H with Radeon Graphics": "Ryzen 7 5800H",
        "Intel(R) Core(TM) Ultra 7 155H": "Core Ultra 7 155H",
        "  AMD   Ryzen 5 3600  6-Core Processor  ": "Ryzen 5 3600",
        "Intel Processor": "Intel Processor",
        "": "", None: "",
    }
    for name, short in names.items():
        check(cn.short_cpu_name(name) == short,
              f"short CPU name {name!r} -> {cn.short_cpu_name(name)!r} (want {short!r})")
    rows = _rows()
    before = [dict(r) for r in rows]
    cn.annotate(rows, MACHINES)
    check(all({k: v for k, v in r.items() if k != cn.ENTRY_KEY} == b
              for r, b in zip(rows, before)), "annotate() keeps the log values")
    check(rows[0][cn.ENTRY_KEY] is MACHINES[PC][0], "run between entries: the older entry")
    check(rows[1][cn.ENTRY_KEY] is MACHINES[PC][1], "run after the second entry: the newer one")
    check(rows[5][cn.ENTRY_KEY] is MACHINES[PC][0], "run older than every entry: the first")
    check(rows[3][cn.ENTRY_KEY] is None and rows[4][cn.ENTRY_KEY] is None,
          "unknown id and no machine_id: no entry")
    check(cn.cell_label(rows[0]) == "Ryzen 9 5900X (3f9a0c)", f"cell {cn.cell_label(rows[0])!r}")
    check(cn.cell_label(rows[2]) == "Core i7-9700K (77aa88)", f"cell {cn.cell_label(rows[2])!r}")
    check(cn.cell_label(rows[3]) == "deadbe", f"no entry: id alone ({cn.cell_label(rows[3])!r})")
    check(cn.cell_label(rows[4]) == "", "no machine_id: blank cell")
    for blank in ("", "   "):
        check(cn.cell_label(_row("2026-11-10 10:00:00 UTC", blank)) == "",
              f"machine_id {blank!r}: blank cell")
    unannotated = _row("2026-11-10 10:00:00 UTC", PC)
    check(cn.cell_label(unannotated) == "3f9a0c", "a row annotate() never saw: id alone")
    nameless = [_row("2026-11-10 10:00:00 UTC", PC)]
    cn.annotate(nameless, {PC: [_entry("2026-11-01 00:00:00 UTC", auto=_auto(cpu_name=None))]})
    check(cn.cell_label(nameless[0]) == "3f9a0c", "entry without a CPU name: id alone")
    cn.annotate(nameless, {})
    check(cn.cell_label(nameless[0]) == "3f9a0c", "annotate() again with no file: id alone")
    t = Translator("en").t
    check(tc.raw(rows[0], "machine") == "Ryzen 9 5900X (3f9a0c)"
          and tc.shown(rows[0], "machine", t) == "Ryzen 9 5900X (3f9a0c)",
          "the table column shows the cell (raw and shown)")
    check(tc.raw(rows[4], "machine") == "" and tc.shown(rows[4], "machine", t) == DASH,
          "no machine_id: raw blank, shown dash")
    return rows


def part_b(rows):
    check("computer" in chart_filter.DIMENSIONS, "Computer is a filter dimension")
    for lang in ("en", "pl"):
        key = chart_filter.DIMENSION_KEYS.get("computer", "")
        check(key and Translator(lang).t(key) != key, f"[{lang}] Computer dimension header")
    values = [chart_filter.row_value(r, "computer") for r in rows]
    check(values[0] == "Ryzen 9 5900X · 64.0 GiB DDR4-3600 (3f9a0c)",
          f"filter value {values[0]!r}")
    check(values[1] == "Ryzen 9 5900X · 128.0 GiB DDR4-3200 (3f9a0c)",
          f"new RAM entry, own value ({values[1]!r})")
    check(values[2] == "Core i7-9700K (77aa88)", f"RAM not known: left out ({values[2]!r})")
    check(values[3] == "deadbe" and values[4] == "", "no entry: id; no machine_id: blank")
    check(len(chart_filter.dimension_values(rows, "computer")) == 5,
          "one PC with two entries gives two values")
    kept = chart_filter.apply(rows, {"computer": {values[2]}})
    check(kept == [rows[2]], "apply() keeps the chosen computer's runs")
    t = Translator("en").t
    check(chart_filter.value_label("computer", "", t) == t("bench.filter_blank"),
          "blank computer shown as the blank label")
    from primeatlas.core.pdf_writer import _pdf_ascii_fold
    check(_pdf_ascii_fold(values[0]).isascii(), "the PDF folds the filter value to ASCII")


def part_c(rows):
    from primeatlas.benchmark import computer_table as ct
    check(ct.computers_in(rows) == [PC, OTHER, UNKNOWN], f"computers {ct.computers_in(rows)}")
    check(ct.computers_in([_row("x")]) == [], "no machine_id: no computer")
    for lang in ("en", "pl"):
        t = Translator(lang).t
        headers, body = ct.table(MACHINES[PC], t)
        check(headers[1:] == ["2026-11-01 00:00:00 UTC", "2026-11-15 00:00:00 UTC"],
              f"[{lang}] a column per entry headed by since ({headers})")
        labels = [line[0] for line in body]
        check(len(labels) == len(ct.FIELDS) and all(not lab.startswith("computer.")
                                                    for lab in labels + [headers[0]]),
              f"[{lang}] a translated row per field")
        cells = {line[0]: line[1:] for line in body}
        cpu = cells[t("computer.field_cpu_name")]
        check(cpu == ["AMD Ryzen 9 5900X 12-Core Processor"] * 2, f"[{lang}] full CPU name")
        check(cells[t("computer.field_cl")] == ["16", DASH], f"[{lang}] CL typed / not typed")
        check(cells[t("computer.field_xmp")] == [t("machine.xmp_on"), DASH], f"[{lang}] XMP")
        check(DASH not in cells[t("computer.field_ram_bytes")], f"[{lang}] RAM size known")
    check(ct.table([], Translator("en").t) is None and ct.table(None, Translator("en").t) is None,
          "no entry: no table")
    check(ct.anchor(PC) == "pc-" + PC, "anchor names the machine_id")
    text = ct.computers_csv([PC, UNKNOWN], MACHINES)
    lines = list(csv.reader(text.splitlines()))
    check(lines[0][:4] == ["computer", "machine_id", "since", "edited_at"]
          and len(lines[0]) == 4 + len(ct.FIELDS), f"computers CSV header {lines[0][:5]}")
    check(len(lines) == 4, f"one line per entry, one for an id without entry ({len(lines)})")
    check(lines[1][1] == PC and lines[1][2] == "2026-11-01 00:00:00 UTC"
          and lines[1][0] == "Ryzen 9 5900X (3f9a0c)", "entry line: cell, id, since")
    check(lines[3][:2] == ["deadbe", UNKNOWN] and not any(lines[3][2:]),
          "id without an entry: the id alone")
    header = lines[0]
    check(lines[1][header.index("ram_bytes")] == str(64 * GIB)
          and lines[1][header.index("xmp")] == "True" and lines[2][header.index("cl")] == "",
          "fields raw, a value not typed empty")


def _html(rows, selection=None, machines=MACHINES, kind="html"):
    return report_export.render(kind, list(rows[0]), rows, translator=Translator("en"),
                                selection=selection, machines=machines)


def part_d(rows):
    from primeatlas.benchmark import computer_names as cn, computer_table as ct
    t = Translator("en").t
    page = _html(rows)
    check(f'<a href="#pa-{ct.anchor(PC)}">Ryzen 9 5900X (3f9a0c)</a>' in page,
          "HTML: the cell links to its computer")
    check(f'id="pa-{ct.anchor(PC)}"' in page and f'id="pa-{ct.anchor(OTHER)}"' in page
          and f'id="pa-{ct.anchor(UNKNOWN)}"' in page, "HTML: a section anchor per computer")
    section = f"<summary><h2>{t('computer.section_title')}</h2></summary>"
    check(section in page and page.index(section) > page.index("</table>"),
          "HTML: the Computers section after the run tables")
    check(t("computer.no_data") in page, "HTML: a computer without entry says so")
    links = page.count('href="#pa-pc-')
    check(links == 5, f"HTML: a link per run with machine_id, in the machine column ({links})")
    kept = _html(rows, selection={"floor": {"29"}})
    check(f'id="pa-{ct.anchor(OTHER)}"' in kept and f'id="pa-{ct.anchor(PC)}"' not in kept,
          "HTML: only the computers of the kept runs")
    snippet = _html(rows, kind="snippet")
    check(f'id="pa-{ct.anchor(PC)}"' in snippet, "snippet: the section too")
    tricky = [_row("2026-11-10 10:00:00 UTC", PC)]
    machines = {PC: [_entry("2026-11-01 00:00:00 UTC", auto=_auto(cpu_name="A<b>&C"))]}
    cn.annotate(tricky, machines)
    page = _html(tricky, machines=machines)
    check("A&lt;b&gt;&amp;C (3f9a0c)</a>" in page and "A<b>&C (3f9a0c)</a>" not in page,
          "HTML: label escaped in the cell")
    check(t("computer.section_title") in _html(rows, machines=None),
          "HTML without machines still renders the section")


def part_e(rows):
    tmp = tempfile.mkdtemp(prefix="primeatlas_computers_csv_")
    try:
        path = os.path.join(tmp, "report.csv")
        written = report_export.export("csv", path, list(rows[0]), rows,
                                       translator=Translator("en"), machines=MACHINES)
        second = os.path.join(tmp, "report_computers.csv")
        check(written == [path, second], f"export returns both paths ({written})")
        check(os.path.exists(second), "the computers CSV is written next to the runs CSV")
        with open(path, encoding="utf-8") as f:
            runs = list(csv.DictReader(f))
        check(runs[0]["machine"] == "Ryzen 9 5900X (3f9a0c)" and runs[4]["machine"] == "",
              "runs CSV: the cell in the machine column")
        with open(second, encoding="utf-8") as f:
            check(len(list(csv.reader(f))) == 1 + 2 + 1 + 1, "computers CSV: 4 lines + header")
        html = os.path.join(tmp, "report.html")
        check(report_export.export("html", html, list(rows[0]), rows,
                                   translator=Translator("en"), machines=MACHINES) == [html],
              "HTML export returns its one path")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def part_f(rows):
    from primeatlas.benchmark import computer_table as ct
    from primeatlas.core import pdf_writer
    tmp = tempfile.mkdtemp(prefix="primeatlas_computers_pdf_")
    try:
        path = os.path.join(tmp, "links.pdf")
        pdf_writer._write_pdf(path, [
            ["BT ET", pdf_writer.Link((10, 10, 50, 12), "pc-a"),
             pdf_writer.Link((10, 30, 50, 12), "pc-nowhere")],
            ["BT ET", pdf_writer.Anchor("pc-a", 500)]])
        data = open(path, "rb").read()
        check(data.count(b"/Subtype /Link") == 1, "a link per known destination only")
        check(b"/Dests" in data and b"/pc-a" in data and b"pc-nowhere" not in data,
              "named destination in the catalog")
        check(b"Link(" not in data and b"Anchor(" not in data, "content holds operators only")
        path = os.path.join(tmp, "r.pdf")
        benchmark.render_benchmark_pdf(path, [], list(rows[0]), rows,
                                       translator=Translator("en"), machines=MACHINES)
        data = open(path, "rb").read()
        check(data.count(b"/Subtype /Link") == 5,
              f"a link per run with machine_id ({data.count(b'/Subtype /Link')})")
        for machine in (PC, OTHER, UNKNOWN):
            check(f"/{ct.anchor(machine)}".encode() in data, f"destination for {machine}")
        check(Translator("en").t("computer.section_title").encode() in data,
              "PDF: the Computers section")
        from primeatlas.benchmark import computer_pdf
        t = Translator("en").t
        check(computer_pdf.computer_pages([], MACHINES, t, 30, 780, 565, 30) == [],
              "no computers: no section pages")
        many = {f"{i:012x}": MACHINES[PC] for i in range(8)}
        pages = computer_pdf.computer_pages(list(many) + [UNKNOWN], many, t, 30, 780, 565, 30)
        anchors = [item.name for page in pages for item in page
                   if isinstance(item, pdf_writer.Anchor)]
        check(len(pages) > 1 and anchors == [ct.anchor(m) for m in list(many) + [UNKNOWN]],
              f"a computer that does not fit starts a page, one anchor each ({len(pages)} pages)")
        check(all(isinstance(page[0], pdf_writer.Anchor) for page in pages[1:]),
              "a continued page starts with a computer, never half of one")
        check(any(t("computer.no_data").split("(")[0] in str(item) for item in pages[-1]),
              "a computer without an entry: the no-data line")
        path = os.path.join(tmp, "plain.pdf")
        benchmark.render_benchmark_pdf(path, [], list(rows[0]), rows,
                                       translator=Translator("en"))
        check(os.path.getsize(path) > 0, "PDF without machines still renders")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def part_g():
    import tkinter.messagebox
    tkinter.messagebox.showinfo = lambda *a, **k: None
    tkinter.messagebox.showerror = lambda *a, **k: None
    from app_sandbox import isolate_app
    from primeatlas.core import machines_file as mf
    tmp = tempfile.mkdtemp(prefix="primeatlas_computers_tab_")
    try:
        rows = [_row("2026-11-10 10:00:00 UTC", PC), _row("2026-11-10 11:00:00 UTC", OTHER),
                _row("2026-11-10 12:00:00 UTC", UNKNOWN), _row("2026-11-10 13:00:00 UTC", "")]
        with open(os.path.join(tmp, "benchmark_log.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        with open(mf.path(tmp), "w", encoding="utf-8") as f:
            json.dump({"format": 1, "machines": MACHINES}, f)
        prime_atlas_v2, _portal = isolate_app(tmp)
        app = prime_atlas_v2._build_gui()()
        app.update()
        try:
            tab = app.benchmark_tab_widget
            tab.reload_benchmark_log()
            tree = tab.benchmark_tree
            node = tree.get_children("")[0]
            tree.item(node, open=True)
            tab._populate_benchmark_floor_node(node)
            app.update()
            items = [i for i in tree.get_children(node) if "row" in tree.item(i, "tags")]
            by_label = {tree.item(i, "values")[tc.TREE_COLUMNS.index("machine")]: i
                        for i in items}
            check(set(by_label) == {"Ryzen 9 5900X (3f9a0c)", "Core i7-9700K (77aa88)",
                                    "deadbe", DASH}, f"cells from the file ({set(by_label)})")
            tree.see(items[-1])
            app.update()
            cell = tab.computer_cell

            def event(item, column):
                x, y, w, h = tree.bbox(item, column)
                return SimpleNamespace(x=x + w // 2, y=y + h // 2)

            cell.on_motion(event(by_label["Ryzen 9 5900X (3f9a0c)"], "machine"))
            check(str(tree["cursor"]) == "hand2", "hand cursor over a computer cell")
            cell.on_motion(event(by_label["Ryzen 9 5900X (3f9a0c)"], "engine"))
            check(str(tree["cursor"]) == "", "plain cursor over another column")
            cell.on_motion(event(by_label[DASH], "machine"))
            check(str(tree["cursor"]) == "", "plain cursor over a blank machine cell")
            cell.on_click(event(by_label[DASH], "machine"))
            cell.on_click(event(by_label["Ryzen 9 5900X (3f9a0c)"], "engine"))
            check(cell.window is None, "no window from a blank cell or another column")
            x, y, w, h = tree.bbox(node, "machine")
            cell.on_click(SimpleNamespace(x=x + w // 2, y=y + h // 2))
            check(cell.window is None, "no window from the floor row")
            cell.on_click(event(by_label["Ryzen 9 5900X (3f9a0c)"], "machine"))
            app.update()
            window = cell.window
            check(window is not None and window.winfo_exists(), "a click opens the window")
            check(window.machine_id == PC and list(window.headers[1:])
                  == ["2026-11-01 00:00:00 UTC", "2026-11-15 00:00:00 UTC"],
                  "the window shows the entry history")
            check("Ryzen 9 5900X (3f9a0c)" in window.title(), f"window title {window.title()!r}")
            cell.on_click(event(by_label["Core i7-9700K (77aa88)"], "machine"))
            app.update()
            check(cell.window.machine_id == OTHER and cell.window.winfo_exists()
                  and not window.winfo_exists(), "another computer: shown instead, one window")
            cell.on_click(event(by_label["deadbe"], "machine"))
            app.update()
            check(cell.window.machine_id == UNKNOWN and cell.window.headers is None
                  and tab.T("computer.no_data") in cell.window.message,
                  "id without an entry: the window says there is no data")
            cell.window.destroy()
            with open(mf.path(tmp), "w", encoding="utf-8") as f:
                f.write("{broken")
            tab.reload_benchmark_log()
            tab._populate_benchmark_floor_node(tree.get_children("")[0])
            app.update()
            items = [i for i in tree.get_children(tree.get_children("")[0])
                     if "row" in tree.item(i, "tags")]
            labels = {tree.item(i, "values")[tc.TREE_COLUMNS.index("machine")] for i in items}
            check(labels == {"3f9a0c", "77aa88", "deadbe", DASH},
                  f"broken file: the cells show the id ({labels})")
        finally:
            app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def part_h():
    from primeatlas.benchmark import computer_names as cn
    from primeatlas.generation import time_model
    import inspect
    rows = [_row("2026-11-10 10:00:00 UTC", PC), _row("2026-11-10 10:00:00 UTC", OTHER)]
    cn.annotate(rows, MACHINES)
    check(rows[0]["machine_id"] == PC and rows[1]["machine_id"] == OTHER,
          "annotate() leaves machine_id for the time model")
    check("machine_id" in inspect.getsource(time_model.read_samples),
          "the time model still filters by machine_id")


def main():
    rows = part_a()
    part_b(rows)
    part_c(rows)
    part_d(rows)
    part_e(rows)
    part_f(rows)
    part_g()
    part_h()
    if failures:
        print(f"\n{len(failures)} FAILED")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
