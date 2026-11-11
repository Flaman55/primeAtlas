"""
test_benchmark_table_columns.py -- the Benchmark run table's columns (table_columns.py) in the
tab's tree, the CSV export and the HTML/PDF report tables.

A. The column set: the engine first, then the two speeds, then the run speed without the
   verification P -> D and the run speed the verification costs; no column twice; the tree's columns
   are the report tables' columns in order; the export adds the floor and the run in front;
   no duplicate log column (write_files, run_purpose, kind, engine_version, instance_of_n,
   write_threads, target_idx_*, avg_primes_per_window, primes_per_second, bytes_written,
   base_gen_seconds, sieve_count_basis, proof_seconds) is a column of its own; every column has a header in
   English and Polish, and so does every run status.
B. Values: a pipeline row (session time and speed win over the instance's), a native count
   (no loop columns: the run speed is numbers / total time; it writes no window, so the
   windows are its range and s/window is time / range), a run stopped part-way (the windows
   it wrote, of its range), a store
   verification (no sieve time: no sieve speed), a stopped run, an old row with nothing but
   the floor (every value missing, status completed, purpose storage), a zero or a NaN time
   (no speed), a build commit kept in the engine name, two instances in the threads, an
   old hybrid row with its exact count; raw for the CSV, shown for the tables (grouped
   thousands, 10^n numbers, translated purpose and status, a dash when missing); the sieve
   speed equals the sieve chart's value and the run speed the whole-run chart's.
   A pt1 run with the verification after it (proof_seconds, part of its times): the run speed
   with it, the speed without it (the chart's P line), the speed it costs (without less
   with, in n/s), the verification
   time in the verify column (also over a logged 0.000 D/P compare time), from the session
   times when the loop stamped them; a run without one (blank, 0, unreadable, longer than
   the run) has neither the speed without it nor a drop.
C. The floor summary row: seconds per window of the column itself (the session value).
D. Exports: the CSV has EXPORT_COLUMNS as its header and raw values, only the kept runs; the
   HTML page has one table per group, each led by floor/run/engine, headers translated; the
   PDF renders with the new tables.
E. The tab (real display): the tree's columns are TREE_COLUMNS with translated headings; a
   run's #0 label is its timestamp alone; a cell shows the shown value.

Usage:
    python unitTests/test_benchmark_table_columns.py
"""
import csv
import json
import math
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "constellation"))

from primeatlas.benchmark import benchmark, report_export, table_cells  # noqa: E402
from primeatlas.benchmark import table_columns as tc  # noqa: E402
from primeatlas.core.i18n import Translator  # noqa: E402

failures = []
DASH = table_cells.MISSING
DROPPED = ("write_files", "run_purpose", "kind", "engine_version", "instance_of_n",
           "write_threads", "target_idx_start", "target_idx_end", "avg_primes_per_window",
           "primes_per_second", "bytes_written", "base_gen_seconds", "sieve_count_basis",
           "total_seconds", "loop_session_seconds", "loop_numbers_per_second",
           "loop_seconds_per_window", "base_exponent", "run_timestamp_utc", "proof_seconds")


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


PIPELINE = {"run_timestamp_utc": "2026-11-10 10:00:00 UTC", "base_exponent": "28",
            "target_idx_start": "0", "target_idx_end": "999", "windows_written": "1000",
            "total_seconds": "100.0", "seconds_per_window": "0.100000",
            "loop_session_seconds": "101.5", "loop_numbers_per_second": "98522167.49",
            "loop_seconds_per_window": "0.101500", "total_primes": "155000000",
            "l_final": "316227767", "sieving_primes_count": "17000000",
            "max_child_rss_mb": "3604.8", "instance_of_n": "2/2", "write_files": "1",
            "base_gen_seconds": "0.010", "sieve_seconds": "80.0", "write_seconds": "20.0",
            "bytes_written": "500000000", "engine": "v7", "numbers_processed": "10000000000",
            "run_status": "completed", "engine_version": "v7.2", "threads": "24",
            "write_threads": "4", "sieve_wall_seconds": "81.0", "run_purpose": "storage"}
NATIVE = {"run_timestamp_utc": "2026-11-10 19:51:07 UTC", "base_exponent": "33",
          "target_idx_start": "0", "target_idx_end": "99", "windows_written": "0",
          "total_seconds": "46.867", "total_primes": "13155690", "max_child_rss_mb": "3604.8",
          "write_files": "0", "sieve_seconds": "46.867", "engine": "pseudosquares_count",
          "numbers_processed": "1000000000", "run_status": "completed",
          "engine_version": "1.2 (fccb96e)", "threads": "24", "run_purpose": "benchmark"}
VERIFY = {"run_timestamp_utc": "2026-11-10 19:21:44 UTC", "base_exponent": "31",
          "target_idx_start": "0", "target_idx_end": "79", "windows_written": "80",
          "total_seconds": "50.537", "seconds_per_window": "0.631710",
          "total_primes": "11206598", "write_files": "1", "engine": "pt1_verify",
          "numbers_processed": "800000000", "run_status": "stopped",
          "verify_seconds": "47.029", "engine_version": "pt1.1", "threads": "24",
          "run_purpose": "storage"}
OLD = {"run_timestamp_utc": "2026-09-01 08:00:00 UTC", "base_exponent": "20"}
PROVEN = {"run_timestamp_utc": "2026-11-11 10:00:00 UTC", "base_exponent": "29",
          "target_idx_start": "0", "target_idx_end": "999", "windows_written": "1000",
          "total_seconds": "100.000", "seconds_per_window": "0.100000", "write_files": "1",
          "sieve_seconds": "50.000", "engine": "pt1", "numbers_processed": "10000000000",
          "run_status": "completed", "verify_seconds": "0.000", "engine_version": "pt1.1",
          "threads": "24", "run_purpose": "storage", "proof_seconds": "20.000"}
HYBRID = {"run_timestamp_utc": "2026-09-02 08:00:00 UTC", "base_exponent": "5",
          "instance_of_n": "hybrid", "target_idx_start": "0", "target_idx_end": "0",
          "windows_written": "1", "total_seconds": "0.5", "sieve_seconds": "0.25"}


def _prepared(rows):
    """Rows as read_benchmark_log() hands them over (engine, kind filled in)."""
    tmp = tempfile.mkdtemp(prefix="primeatlas_table_columns_")
    try:
        fields = list(dict.fromkeys(k for row in rows for k in row))
        with open(os.path.join(tmp, "benchmark_log.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return benchmark.read_benchmark_log(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def part_a():
    check(tc.TREE_COLUMNS[:5] == ("engine", "sieve_nps", "run_nps", "run_nps_unverified",
                                  "verify_drop"),
          f"engine, sieve and run speed, the speed without the verification and its drop "
          f"lead the table ({tc.TREE_COLUMNS[:5]})")
    check(len(set(tc.TREE_COLUMNS)) == len(tc.TREE_COLUMNS), "no column twice in the tree")
    check(tc.TREE_COLUMNS == tuple(c for _t, cols in tc.GROUPS for c in cols),
          "the tree's columns are the report groups' columns in order")
    check(tc.EXPORT_COLUMNS == ("floor", "run") + tc.TREE_COLUMNS,
          "the export puts floor and run in front of the tree's columns")
    check(len(tc.EXPORT_COLUMNS) <= 23, f"at most 23 export columns ({len(tc.EXPORT_COLUMNS)})")
    for column in DROPPED:
        check(column not in tc.EXPORT_COLUMNS, f"{column} is not a column of its own")
    for title, columns in tc.report_tables():
        check(columns[:3] == tc.KEY_COLUMNS and len(set(columns)) == len(columns),
              f"{title}: led by floor/run/engine, no column twice")
    for lang in ("en", "pl"):
        with open(os.path.join(_REPO_ROOT, "primeatlas", "core", "locales",
                               f"strings_{lang}.json"), encoding="utf-8") as f:
            strings = json.load(f)
        missing = [c for c in tc.EXPORT_COLUMNS if not strings.get(tc.header_key(c))]
        missing += [k for k in ("bench.run_status_completed", "bench.run_status_stopped")
                    if not strings.get(k)]
        check(not missing, f"{lang}: every header and run status has a string ({missing})")


def part_b():
    _f, (pipe, native, verify, old, hybrid) = _prepared([PIPELINE, NATIVE, VERIFY, OLD, HYBRID])
    T = Translator("pl")
    t = T.t

    check(tc.raw(pipe, "engine") == "v7.2", f"pipeline engine v7.2 ({tc.raw(pipe, 'engine')})")
    check(tc.raw(pipe, "sieve_nps") == "125000000", "sieve speed = numbers / sieve_seconds")
    check(tc.raw(pipe, "run_nps") == "98522167", "run speed = the session's loop speed")
    check(tc.raw(pipe, "seconds") == "101.5", "time = the session's time")
    check(tc.raw(pipe, "seconds_per_window") == "0.101500", "s/window = the session's")
    check(tc.raw(pipe, "numbers") == "10000000000", "numbers raw")
    check(tc.raw(pipe, "windows") == "1000 (0-999)", f"windows ({tc.raw(pipe, 'windows')})")
    check(tc.raw(pipe, "purpose") == "storage" and tc.raw(pipe, "status") == "completed",
          "purpose and status raw")
    check(tc.raw(pipe, "threads") == "2x24 thr, write 4",
          f"threads name instances and write threads ({tc.raw(pipe, 'threads')})")
    check(tc.raw(pipe, "write_mbps") == "25.0", "write MB/s = bytes / write_seconds")
    check(tc.raw(pipe, "ram_mb") == "3604.8" and tc.raw(pipe, "pi_l") == "17000000"
          and tc.raw(pipe, "floor") == "28" and tc.raw(pipe, "run").startswith("2026-11-10"),
          "copied columns keep the log's text")
    check(tc.shown(pipe, "sieve_nps", t) == "125,000,000", "shown speed grouped by thousands")
    check(tc.shown(pipe, "numbers", t) == "10^10", "shown numbers as 10^n")
    check(tc.shown(pipe, "purpose", t) == t("bench.purpose_storage"), "purpose translated")
    check(tc.shown(pipe, "status", t) == t("bench.run_status_completed"), "status translated")
    check(float(tc.raw(pipe, "sieve_nps")) == round(benchmark.line_value("sieve")(pipe)),
          "sieve speed is the sieve chart's value")
    check(float(tc.raw(pipe, "run_nps")) == round(benchmark.line_value("growth")(pipe)),
          "run speed is the whole-run chart's value")

    check(tc.raw(native, "engine") == "PSS count 1.2 (fccb96e)",
          f"native engine keeps the build commit ({tc.raw(native, 'engine')})")
    check(tc.raw(native, "run_nps") == str(round(1e9 / 46.867)),
          "native: run speed = numbers / total_seconds without loop columns")
    check(tc.raw(native, "seconds") == "46.867" and tc.raw(native, "windows") == "100 (0-99)",
          f"native: time from total_seconds, windows = its range ({tc.raw(native, 'windows')})")
    check(tc.raw(native, "purpose") == "benchmark" and tc.raw(native, "threads") == "24 thr",
          "native: benchmark purpose, no write threads")
    check(tc.raw(native, "seconds_per_window") == "0.468670",
          f"native: s/window = time / windows ({tc.raw(native, 'seconds_per_window')})")
    no_range = {k: v for k, v in native.items() if not k.startswith("target_idx")}
    check(tc.raw(no_range, "windows") == "" and tc.raw(no_range, "seconds_per_window") == "",
          "no range and nothing written: no windows, no s/window")
    partial = dict(pipe, windows_written="480")
    check(tc.raw(partial, "windows") == "480 (0-999)"
          and tc.raw(partial, "seconds_per_window") == "0.101500",
          "stopped part-way: the windows it wrote, the logged s/window")
    zero_time = dict(native, total_seconds="0")
    check(tc.raw(zero_time, "seconds_per_window") == "", "zero time: no s/window")

    check(tc.raw(verify, "sieve_nps") == "" and tc.shown(verify, "sieve_nps", t) == DASH,
          "store verification: no sieve time, no sieve speed")
    check(tc.raw(verify, "status") == "stopped"
          and tc.shown(verify, "status", t) == t("bench.run_status_stopped"), "stopped run")
    check(tc.raw(verify, "verify_seconds") == "47.029", "verify time")

    for column in tc.TREE_COLUMNS:
        if column in ("engine", "purpose", "status"):
            continue
        check(tc.raw(old, column) == "" and tc.shown(old, column, t) == DASH,
              f"old row: {column} missing")
    check(tc.raw(old, "status") == "completed" and tc.raw(old, "purpose") == "storage"
          and tc.raw(old, "engine") == "unknown", "old row: completed, storage, unknown engine")

    check(tc.raw(hybrid, "numbers") == "900000" and tc.raw(hybrid, "sieve_nps") == "3600000",
          "old hybrid floor: exact count gives numbers and speed")

    for bad in ("0", "nan", "-1", "x"):
        row = dict(native, sieve_seconds=bad, total_seconds=bad)
        check(tc.raw(row, "sieve_nps") == "" and tc.raw(row, "run_nps") == "",
              f"time {bad!r}: no speed")
    row = dict(pipe, loop_numbers_per_second="nan")
    check(tc.raw(row, "run_nps") == str(round(1e10 / 100.0)),
          "a NaN loop speed falls back to numbers / total_seconds")
    row = dict(pipe, write_seconds="0")
    check(tc.raw(row, "write_mbps") == "", "zero write time: no MB/s")
    proven_case(t)
    return pipe, native, verify


def proven_case(t):
    from primeatlas.benchmark import proof_rows
    _f, (proven,) = _prepared([PROVEN])
    check(tc.raw(proven, "run_nps") == "100000000", "proven: run speed with the verification")
    check(tc.raw(proven, "run_nps_unverified") == "125000000",
          f"proven: speed without it ({tc.raw(proven, 'run_nps_unverified')})")
    check(tc.raw(proven, "verify_drop") == "25000000"
          and tc.shown(proven, "verify_drop", t) == "25,000,000",
          f"proven: the speed it costs, without less with ({tc.raw(proven, 'verify_drop')})")
    check(tc.raw(proven, "verify_seconds") == "20.000",
          f"proven: the verify column shows the verification ({tc.raw(proven, 'verify_seconds')})")
    check(tc.raw(proven, "sieve_nps") == "200000000", "proven: the sieve speed is the sieve's")
    loop = dict(proven, loop_session_seconds="110.000", loop_numbers_per_second="90909090.91")
    check(float(tc.raw(loop, "run_nps_unverified"))
          == round(benchmark.line_value("growth")(proof_rows.split(loop)[0])),
          "proven: the speed without it is the whole-run chart's P line")
    check(tc.raw(loop, "run_nps") == "90909091"
          and tc.raw(loop, "run_nps_unverified") == "111111111"
          and tc.raw(loop, "verify_drop") == "20202020",
          f"proven in the loop: session times ({tc.raw(loop, 'run_nps_unverified')}, "
          f"{tc.raw(loop, 'verify_drop')})")
    for bad in ("", "0", "x", "150"):
        row = dict(proven, proof_seconds=bad)
        check(tc.raw(row, "run_nps_unverified") == "" and tc.raw(row, "verify_drop") == ""
              and tc.shown(row, "verify_drop", t) == DASH,
              f"proof_seconds {bad!r}: no speed without it, no drop")
    check(tc.raw(dict(proven, proof_seconds=""), "verify_seconds") == "0.000",
          "no proof: the verify column keeps the logged D/P compare time")


def part_c(pipe, native, verify):
    stats = tc.stats([pipe, native, verify])
    check(stats is not None and stats["count"] == 3
          and math.isclose(stats["min"], 0.1015) and math.isclose(stats["max"], 0.63171),
          f"floor summary over the column's own values ({stats})")
    check(tc.stats([dict(OLD)]) is None, "no value: no summary")


def part_d():
    fields, rows = _prepared([PIPELINE, NATIVE, VERIFY])
    text = report_export.render("csv", fields, rows, Translator("en"))
    back = list(csv.reader(text.splitlines()))
    check(tuple(back[0]) == tc.EXPORT_COLUMNS, "CSV header = EXPORT_COLUMNS")
    check(len(back) == 4 and back[1][tc.EXPORT_COLUMNS.index("sieve_nps")] == "125000000"
          and back[2][tc.EXPORT_COLUMNS.index("seconds_per_window")] == "0.468670"
          and back[3][tc.EXPORT_COLUMNS.index("sieve_nps")] == "",
          "CSV holds raw values, missing ones empty")
    kept = report_export.render("csv", fields, rows, Translator("en"),
                                selection={"engine": {"v7.2"}})
    check(len(kept.strip().splitlines()) == 2, "CSV holds only the kept runs")

    T = Translator("pl")
    page = report_export.render("html", fields, rows, T)
    check(page.count("<table>") == len(tc.GROUPS), "HTML: one table per group")
    for column in tc.EXPORT_COLUMNS:
        check(f"<th>{T.t(tc.header_key(column))}</th>" in page
              or f"<th>{T.t(tc.header_key(column)).replace('&', '&amp;')}</th>" in page,
              f"HTML: translated header of {column}")
    check("<th>loop_numbers_per_second</th>" not in page, "HTML: no raw log column header")

    tmp = tempfile.mkdtemp(prefix="primeatlas_table_columns_pdf_")
    try:
        path = os.path.join(tmp, "r.pdf")
        benchmark.render_benchmark_pdf(path, [], fields, rows, translator=T)
        check(os.path.getsize(path) > 0, "PDF renders with the new tables")
        data = open(path, "rb").read()
        check(b"loop_numbers_per_second" not in data, "PDF: no raw log column header")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def part_e():
    import tkinter.messagebox
    tkinter.messagebox.showinfo = lambda *a, **k: None
    from app_sandbox import isolate_app
    tmp = tempfile.mkdtemp(prefix="primeatlas_table_columns_tab_")
    try:
        fields = list(PIPELINE)
        with open(os.path.join(tmp, "benchmark_log.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerow(PIPELINE)
        prime_atlas_v2, _portal = isolate_app(tmp)
        app = prime_atlas_v2._build_gui()()
        app.update()
        try:
            tab = app.benchmark_tab_widget
            tab.reload_benchmark_log()
            tree = tab.benchmark_tree
            check(tuple(tree["columns"]) == tc.TREE_COLUMNS, "tree columns = TREE_COLUMNS")
            check(tree.heading("sieve_nps", "text") == tab.T(tc.header_key("sieve_nps")),
                  "tree heading translated")
            node = tree.get_children("")[0]
            tab._populate_benchmark_floor_node(node)
            stat_item, run_item = tree.get_children(node)[:2]
            check(tree.item(run_item, "text") == PIPELINE["run_timestamp_utc"],
                  f"#0 is the timestamp alone ({tree.item(run_item, 'text')!r})")
            values = tree.item(run_item, "values")
            check(str(values[tc.TREE_COLUMNS.index("sieve_nps")]) == "125,000,000"
                  and str(values[tc.TREE_COLUMNS.index("engine")]) == "v7.2",
                  f"run cells show the shown values ({values[:3]})")
            stat = tree.item(stat_item, "values")
            check("0.1015" in str(stat[tc.TREE_COLUMNS.index("seconds_per_window")]),
                  "summary row sits in the s/window column with the session value")
        finally:
            app.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    part_a()
    rows = part_b()
    part_c(*rows)
    part_d()
    part_e()
    if failures:
        print(f"\n{len(failures)} FAILED")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
