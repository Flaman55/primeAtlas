"""
test_benchmark_rows_safety.py -- benchmark-mode rows survive integration, restore and full backup.

A benchmark row (row_purpose() "benchmark": a measuring run or a native program) lives only in
the storage's benchmark_log.csv, never in a floor's floor_meta.json, since a measuring run leaves
the storage as it was. Every path that moves or rewinds the log keeps those rows:

A. floor_meta.merge_rows_into_benchmark_log(storage, rows) adds the rows whose row_key() the log
   lacks (log order kept, new rows appended, the header grown, never shrunk), creates a missing
   log with the engines' header, skips duplicates inside `rows`, returns the count added;
   floor_meta.read_benchmark_log_rows() reads a log, [] without one.
B. storage_integrate.integrate_floor() also imports the external storage's benchmark rows of
   THAT floor into the destination's log: not other floors' rows, not the external storage
   rows (those travel through floor_meta.json), nothing twice on a repeated integration, the
   external log untouched, no failure without an external log.
C. BackupStore.restore_csv() puts the backup's log back and keeps the current benchmark rows the
   backup lacks (after the backup's rows); current storage rows the backup lacks go, as before
   (they belong to files the restore rolls back); returns the count kept.
D. full_backup.copy_floor_increment() keeps the floor's benchmark rows in the backup
   (BENCHMARK_ROWS_FILENAME in the floor's backup folder), adding new ones on a later backup
   and never dropping one the live log lost; the live floor_meta.json gains no benchmark row;
   restore_floor_from_full_backup() merges them into the live log; a corrupt rows file is
   ignored (no exception, nothing imported).

Usage:
    python unitTests/test_benchmark_rows_safety.py
"""
import csv
import json
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from benchmark_log_schema import BENCHMARK_FIELDNAMES  # noqa: E402
from primeatlas.settings import floor_meta, full_backup, storage_integrate  # noqa: E402
from primeatlas.settings.backup_store import BackupStore  # noqa: E402
from primeatlas.settings.manifest import BackupManifest  # noqa: E402

failures = []
_dirs = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _tmp(prefix):
    path = tempfile.mkdtemp(prefix=f"bench_rows_{prefix}_")
    _dirs.append(path)
    return path


def _row(stamp, floor, purpose, engine="v7.1", start="0", end="9"):
    row = {f: "" for f in BENCHMARK_FIELDNAMES}
    row.update(run_timestamp_utc=stamp, base_exponent=str(floor), target_idx_start=start,
               target_idx_end=end, engine=engine, run_purpose=purpose, total_seconds="1.5",
               write_files="0" if purpose == "benchmark" else "1")
    return row


def _write_log(storage, rows, fieldnames=None):
    os.makedirs(storage, exist_ok=True)
    with open(os.path.join(storage, "benchmark_log.csv"), "w", newline="",
              encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames or BENCHMARK_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in writer.fieldnames})


def _stamps(storage):
    return [r["run_timestamp_utc"] for r in floor_meta.read_benchmark_log_rows(storage)]


def _log_text(storage):
    with open(os.path.join(storage, "benchmark_log.csv"), encoding="utf-8") as f:
        return f.read()


def _make_floor(storage, floor):
    os.makedirs(os.path.join(storage, f"10p{floor}", "source_primes"), exist_ok=True)


def test_merge_rows():
    print("\n--- A. merge_rows_into_benchmark_log ---")
    storage = _tmp("merge")
    check(floor_meta.read_benchmark_log_rows(storage) == [], "no log: no rows")
    a, b, c = _row("t1", 20, "storage"), _row("t2", 20, "benchmark"), _row("t3", 21, "benchmark")
    added = floor_meta.merge_rows_into_benchmark_log(storage, [a, b, dict(b)])
    check(added == 2 and _stamps(storage) == ["t1", "t2"],
          f"a missing log is created, a duplicate inside the rows is skipped ({added}, {_stamps(storage)})")
    with open(os.path.join(storage, "benchmark_log.csv"), encoding="utf-8") as f:
        header = next(csv.reader(f))
    check(header == BENCHMARK_FIELDNAMES, "a new log gets the engines' header")
    changed_b = dict(b, total_seconds="99")
    added = floor_meta.merge_rows_into_benchmark_log(storage, [changed_b, c])
    rows = floor_meta.read_benchmark_log_rows(storage)
    check(added == 1 and _stamps(storage) == ["t1", "t2", "t3"],
          f"only the missing key is added, after the existing rows ({added}, {_stamps(storage)})")
    check(rows[1]["total_seconds"] == "1.5", "an existing row with the same key is kept as it was")
    check(floor_meta.merge_rows_into_benchmark_log(storage, [a, b, c]) == 0
          and _stamps(storage) == ["t1", "t2", "t3"], "merging the same rows again adds nothing")
    check(floor_meta.merge_rows_into_benchmark_log(storage, []) == 0, "no rows: 0")
    short = _tmp("merge_short")
    _write_log(short, [a], fieldnames=BENCHMARK_FIELDNAMES[:5])
    extra = dict(c, custom_column="x")
    floor_meta.merge_rows_into_benchmark_log(short, [extra])
    with open(os.path.join(short, "benchmark_log.csv"), encoding="utf-8") as f:
        header = next(csv.reader(f))
    check(header[:5] == BENCHMARK_FIELDNAMES[:5] and "custom_column" in header
          and "engine" in header, f"the header grows, existing columns first ({header[:7]})")
    check(floor_meta.read_benchmark_log_rows(short)[0]["run_timestamp_utc"] == "t1",
          "existing rows survive a grown header")


def test_integrate():
    print("\n--- B. integrate_floor ---")
    ext, dest = _tmp("ext"), _tmp("dest")
    _make_floor(ext, 20)
    ext_rows = [_row("e1", 20, "benchmark"), _row("e2", 20, "storage"),
                _row("e3", 21, "benchmark"), _row("e4", 20, "x", engine="primesieve_count")]
    _write_log(ext, ext_rows)
    ext_before = _log_text(ext)
    _write_log(dest, [_row("d1", 20, "benchmark")])
    storage_integrate.integrate_floor(dest, ext, 20)
    check(_stamps(dest) == ["d1", "e1", "e4"],
          f"the floor's benchmark rows (incl. a native row) come in, not other floors' or "
          f"storage rows ({_stamps(dest)})")
    storage_integrate.integrate_floor(dest, ext, 20)
    check(_stamps(dest) == ["d1", "e1", "e4"], "a repeated integration adds nothing")
    check(_log_text(ext) == ext_before, "the external log is untouched")
    no_log_ext = _tmp("ext_nolog")
    _make_floor(no_log_ext, 20)
    try:
        storage_integrate.integrate_floor(dest, no_log_ext, 20)
        check(_stamps(dest) == ["d1", "e1", "e4"], "an external storage without a log changes nothing")
    except Exception as exc:  # noqa: BLE001
        check(False, f"an external storage without a log raised {exc!r}")
    fresh = _tmp("dest_fresh")
    storage_integrate.integrate_floor(fresh, ext, 20)
    check(_stamps(fresh) == ["e1", "e4"], f"a destination without a log gets one ({_stamps(fresh)})")


def test_restore_csv():
    print("\n--- C. BackupStore.restore_csv ---")
    storage = _tmp("restore")
    _write_log(storage, [_row("s1", 20, "storage"), _row("b1", 20, "benchmark")])
    manifest = BackupManifest.build_from_disk(storage)
    _write_log(storage, [_row("s1", 20, "storage"), _row("b1", 20, "benchmark"),
                         _row("s2", 21, "storage"), _row("b2", 21, "benchmark"),
                         _row("n1", 28, "x", engine="pseudosquares_count")])
    kept = BackupStore(storage).restore_csv(manifest)
    check(_stamps(storage) == ["s1", "b1", "b2", "n1"],
          f"the backup's rows, then the newer benchmark rows; the newer storage row goes "
          f"({_stamps(storage)})")
    check(kept == 2, f"restore_csv() returns the benchmark rows kept ({kept})")
    kept = BackupStore(storage).restore_csv(manifest)
    check(kept == 2 and _stamps(storage) == ["s1", "b1", "b2", "n1"],
          "restoring again duplicates nothing")
    empty = _tmp("restore_empty")
    manifest_empty = BackupManifest.build_from_disk(empty)
    _write_log(empty, [_row("b9", 20, "benchmark")])
    BackupStore(empty).restore_csv(manifest_empty)
    check(_stamps(empty) == ["b9"], f"a backup taken without a log keeps the benchmark rows ({_stamps(empty)})")


def test_full_backup():
    print("\n--- D. full backup ---")
    storage, dest, target = _tmp("fb_live"), _tmp("fb_dest"), _tmp("fb_target")
    _make_floor(storage, 20)
    _write_log(storage, [_row("s1", 20, "storage"), _row("b1", 20, "benchmark"),
                         _row("b2", 21, "benchmark")])
    full_backup.copy_floor_increment(storage, dest, 20)
    path = os.path.join(dest, "10p20", full_backup.BENCHMARK_ROWS_FILENAME)
    check(os.path.isfile(path), "the backup keeps a benchmark rows file for the floor")
    rows = full_backup.load_backup_benchmark_rows(dest, 20)
    check([r["run_timestamp_utc"] for r in rows] == ["b1"],
          f"only that floor's benchmark rows ({[r['run_timestamp_utc'] for r in rows]})")
    meta = floor_meta.load_floor_meta(storage, 20)
    check(not meta or all(r.get("run_purpose") != "benchmark" for r in meta["benchmark_rows"]),
          "the live floor_meta.json gains no benchmark row")
    _write_log(storage, [_row("s1", 20, "storage"), _row("b3", 20, "benchmark")])
    full_backup.copy_floor_increment(storage, dest, 20)
    rows = full_backup.load_backup_benchmark_rows(dest, 20)
    check([r["run_timestamp_utc"] for r in rows] == ["b1", "b3"],
          "a later backup adds the new row and keeps the one the live log lost")
    _make_floor(target, 20)
    _write_log(target, [_row("t1", 20, "benchmark")])
    full_backup.restore_floor_from_full_backup(target, dest, 20)
    check(_stamps(target) == ["t1", "b1", "b3"], f"restore merges them into the live log ({_stamps(target)})")
    full_backup.restore_floor_from_full_backup(target, dest, 20)
    check(_stamps(target) == ["t1", "b1", "b3"], "a repeated restore adds nothing")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    other = _tmp("fb_other")
    _make_floor(other, 20)
    try:
        full_backup.restore_floor_from_full_backup(other, dest, 20)
        check(floor_meta.read_benchmark_log_rows(other) == [], "a corrupt rows file imports nothing")
    except Exception as exc:  # noqa: BLE001
        check(False, f"a corrupt rows file raised {exc!r}")
    check(full_backup.load_backup_benchmark_rows(dest, 20) == [], "a corrupt rows file reads as none")
    full_backup.copy_floor_increment(storage, dest, 20)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    check([r["run_timestamp_utc"] for r in data["benchmark_rows"]] == ["b3"],
          "a corrupt rows file is rewritten from the live log on the next backup")


def main():
    try:
        test_merge_rows()
        test_integrate()
        test_restore_csv()
        test_full_backup()
    finally:
        for path in _dirs:
            shutil.rmtree(path, ignore_errors=True)
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  FAIL: {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
