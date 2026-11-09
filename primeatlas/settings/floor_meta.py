"""
floor_meta.py -- per-floor sidecar metadata (10p{N}/floor_meta.json), pure-logic and
tkinter-free (same philosophy as manifest.py: exercised directly by standalone tests,
wired into the GUI/backup layers by primeatlas/app/ / manifest.py / backup_store.py).

Why this exists: benchmark_log.csv lives at the STORAGE ROOT, not inside any one floor's
own 10p{N}/ folder -- so a floor's generation history has no independent existence of its
own. Physically copying a 10p{N} directory out of one storage (archive) into another (the
common case: building a fresh storage but bringing some already-generated floors along)
leaves that floor's timing/benchmark rows behind in the OLD root's CSV -- from the new
storage's point of view the floor's data exists but its history is gone. floor_meta.json
fixes that by making a floor's generation history travel WITH its own directory: a full
copy of every benchmark_log.csv row this floor has ever produced, appended by each engine
as it logs the row (prime_sieve/floor_meta_store.py, which also holds the file's reading,
writing and row key, imported here), and re-imported into the local benchmark_log.csv
the first time this app notices the floor (see merge_floor_meta_into_benchmark_log(), called from PortalBrowserApp's totals-cache
background worker on every floor visit). manifest.py folds floor_meta.json's rows into
backups too, alongside the totals/sieving caches -- see that module's own docstring.
Benchmark-purpose rows never enter floor_meta.json; merge_rows_into_benchmark_log() and
benchmark_purpose_rows() let integration, restore and the full-data backup carry them
from one log to another.
"""
import os
import csv

from benchmark_log_schema import BENCHMARK_FIELDNAMES, RUN_PURPOSE_BENCHMARK, row_purpose
from floor_meta_store import (  # noqa: F401
    FLOOR_META_FILENAME, append_benchmark_row_to_floor_meta, floor_meta_path,
    load_floor_meta, row_key as _row_key, save_floor_meta)


def merge_rows_into_floor_meta(storage_path, base_exponent, rows):
    """Unions `rows` into this floor's existing floor_meta.json (if any), by the same key
    used everywhere else in this module -- never drops a row that's only present locally,
    only adds ones that are missing there. Used by manifest.py's backup-restore path
    (BackupManifest.restore_floor_metadata()), so restoring an OLDER backup on top of a
    floor that has since logged newer runs doesn't erase that newer local history.

    Returns the number of rows actually added."""
    if not rows:
        return 0
    meta = load_floor_meta(storage_path, base_exponent)
    existing = list(meta["benchmark_rows"]) if meta else []
    existing_keys = {_row_key(r) for r in existing}
    added = 0
    for row in rows:
        key = _row_key(row)
        if key not in existing_keys:
            existing.append(dict(row))
            existing_keys.add(key)
            added += 1
    if added:
        save_floor_meta(storage_path, base_exponent, existing)
    return added


def _read_csv_rows(log_path):
    if not os.path.exists(log_path):
        return [], []
    with open(log_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def _write_csv_rows(log_path, fieldnames, rows):
    tmp_path = f"{log_path}.tmp{os.getpid()}"
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    os.replace(tmp_path, log_path)


def read_benchmark_log_rows(storage_path):
    """The rows of the storage's benchmark_log.csv as dicts, [] without a log."""
    return _read_csv_rows(os.path.join(storage_path, "benchmark_log.csv"))[1]


def benchmark_purpose_rows(rows, base_exponent=None):
    """The rows whose row_purpose() is a benchmark, of one floor when base_exponent is given."""
    return [r for r in rows if row_purpose(r) == RUN_PURPOSE_BENCHMARK
            and (base_exponent is None or str(r.get("base_exponent", "")) == str(base_exponent))]


def merge_rows_into_benchmark_log(storage_path, rows):
    """Appends to the storage's benchmark_log.csv every row of `rows` whose key (see
    _row_key) the log lacks, the first of equal keys only; existing rows stay as they are.

    Returns the number of rows actually added (0 also when the log cannot be written)."""
    if not rows:
        return 0
    log_path = os.path.join(storage_path, "benchmark_log.csv")
    fieldnames, existing_rows = _read_csv_rows(log_path)
    existing_keys = {_row_key(r) for r in existing_rows}
    to_import = []
    for row in rows:
        key = _row_key(row)
        if key not in existing_keys:
            existing_keys.add(key)
            to_import.append(row)
    if not to_import:
        return 0
    if not fieldnames:
        # A log grown from scratch (e.g. a moved floor imported into an empty storage) gets
        # the engines' own header, so a later engine run appends without a migration.
        fieldnames = list(BENCHMARK_FIELDNAMES)
    # Grow the header (never shrink/reorder existing columns) if an imported row has a key
    # this log hasn't seen before -- additive, unlike ensure_benchmark_log_schema()
    # in benchmark_log_schema.py (which migrates to one fixed target schema); this module
    # doesn't own a fixed schema, so it only ever adds columns, never rewrites their
    # meaning.
    extra_fields = []
    for row in to_import:
        for key in row.keys():
            if key not in fieldnames and key not in extra_fields:
                extra_fields.append(key)
    if extra_fields:
        fieldnames = fieldnames + sorted(extra_fields)
    try:
        os.makedirs(storage_path, exist_ok=True)
        _write_csv_rows(log_path, fieldnames, existing_rows + to_import)
    except OSError:
        return 0
    return len(to_import)


def merge_floor_meta_into_benchmark_log(storage_path, base_exponent):
    """Imports this floor's floor_meta.json rows into the storage root's
    benchmark_log.csv (merge_rows_into_benchmark_log()). This
    is what makes a floor physically copied in from another storage (bringing its own
    floor_meta.json along) show up in THIS storage's Benchmark tab exactly as if it had
    been generated here. Called unconditionally from PortalBrowserApp's totals-cache
    background worker on every floor visit -- a no-op (returns 0) on the ordinary case
    where there's nothing new to import, so it's cheap to call every time rather than
    trying to separately detect "is this floor newly-copied-in".

    Returns the number of rows actually imported (0 if none, including when this floor has
    no floor_meta.json at all)."""
    meta = load_floor_meta(storage_path, base_exponent)
    if not meta or not meta["benchmark_rows"]:
        return 0
    return merge_rows_into_benchmark_log(storage_path, meta["benchmark_rows"])
