"""
floor_meta.py -- per-floor sidecar metadata (10p{N}/floor_meta.json), pure-logic and
tkinter-free (same philosophy as manifest.py: exercised directly by standalone tests,
wired into the GUI/backup layers by prime_atlas_v1.py / manifest.py / backup_store.py).

Why this exists: benchmark_log.csv lives at the STORAGE ROOT, not inside any one floor's
own 10p{N}/ folder -- so a floor's generation history has no independent existence of its
own. Physically copying a 10p{N} directory out of one storage (magazyn) into another (the
common case: building a fresh storage but bringing some already-generated floors along)
leaves that floor's timing/benchmark rows behind in the OLD root's CSV -- from the new
storage's point of view the floor's data exists but its history is gone. floor_meta.json
fixes that by making a floor's generation history travel WITH its own directory: a full
copy of every benchmark_log.csv row this floor has ever produced, appended incrementally
as each row is logged (see the two live generator engines' own write hooks --
orchestrator_v3.py's print_benchmark_summary() and prime_sieve_primesieve.py's
write_benchmark_row() -- which duplicate a small inline version of the append logic here,
same "no cross-folder import between prime_sieve/ and primeatlas/" convention already used
throughout this project, since those engines run standalone, possibly under WSL), and
re-imported into the local benchmark_log.csv the first time this app notices the floor
(see merge_floor_meta_into_benchmark_log(), called from prime_atlas_v1.py's totals-cache
background worker on every floor visit). manifest.py folds floor_meta.json's rows into
backups too, alongside the totals/sieving caches -- see that module's own docstring.
"""
import os
import csv
import json

FLOOR_META_FILENAME = "floor_meta.json"

# Canonical column order used only when this module has to grow a benchmark_log.csv from
# scratch (e.g. importing a moved floor into an otherwise-empty destination storage) -- a
# superset across every generator engine this project has had (see
# prime_sieve_primesieve.py's own BENCHMARK_FIELDNAMES and orchestrator_v3.py's, which
# differ from each other). Deliberately NOT imported from either of those -- this module
# has no dependency on the versioned generator scripts (see this file's own docstring).
# Any row key not in this list still gets written; it's appended to the header, sorted,
# the first time it's seen.
CANONICAL_BENCHMARK_FIELDNAMES = [
    "run_timestamp_utc", "base_exponent", "target_idx_start", "target_idx_end",
    "windows_written", "total_seconds", "seconds_per_window", "total_primes",
    "avg_primes_per_window", "primes_per_second",
    "l_final", "sieving_primes_count", "max_child_rss_mb",
    "base_gen_seconds", "sieve_seconds", "write_seconds", "bytes_written",
    "instance_of_n", "loop_session_seconds", "loop_numbers_per_second",
    "loop_seconds_per_window", "write_files",
]

# What makes one benchmark row unique -- a floor+timerange+run combination should never
# repeat at second resolution, so this is enough to dedup without needing a stronger hash.
_ROW_KEY_FIELDS = ("run_timestamp_utc", "base_exponent", "target_idx_start", "target_idx_end")


def floor_meta_path(storage_path, base_exponent):
    return os.path.join(storage_path, f"10p{base_exponent}", FLOOR_META_FILENAME)


def load_floor_meta(storage_path, base_exponent):
    """Returns {"base_exponent": N, "benchmark_rows": [...]}, or None if this floor has no
    metadata file at all (a floor generated before this feature existed, or one with no
    completed runs yet). Never raises -- a missing/corrupt file just means no history is
    known, same best-effort philosophy as the totals cache (load_totals_cache)."""
    path = floor_meta_path(storage_path, base_exponent)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return {
            "base_exponent": data.get("base_exponent", base_exponent),
            "benchmark_rows": list(data.get("benchmark_rows", [])),
        }
    except (OSError, ValueError):
        return None


def save_floor_meta(storage_path, base_exponent, benchmark_rows):
    """Atomic write (temp file + os.replace()), same pattern as every other persisted file
    in this project (totals cache, backup manifests, benchmark_log.csv rewrites)."""
    floor_dir = os.path.join(storage_path, f"10p{base_exponent}")
    path = floor_meta_path(storage_path, base_exponent)
    tmp_path = f"{path}.tmp{os.getpid()}"
    try:
        os.makedirs(floor_dir, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"base_exponent": base_exponent, "benchmark_rows": benchmark_rows},
                      f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
        return True
    except OSError:
        return False  # best-effort -- a failed save just means this run's row only lives
                       # in benchmark_log.csv, same as before this feature existed


def _row_key(row):
    return tuple(str(row.get(f, "")) for f in _ROW_KEY_FIELDS)


def append_benchmark_row_to_floor_meta(storage_path, base_exponent, row):
    """GUI-side / test-side equivalent of the small inline helper duplicated into the two
    live generator engines (see this module's docstring) -- kept here too so restore_job.py
    style code and standalone tests can append without needing a running generation
    subprocess. `row` should be the exact same dict already written to benchmark_log.csv
    for this run, so floor_meta.json stays byte-for-byte consistent with the CSV, no
    separate reconstruction needed.

    Idempotent: a row whose (run_timestamp_utc, base_exponent, target_idx_start,
    target_idx_end) key already exists is skipped, so calling this twice for the same run
    (e.g. a retried write) is harmless."""
    meta = load_floor_meta(storage_path, base_exponent)
    rows = list(meta["benchmark_rows"]) if meta else []
    existing_keys = {_row_key(r) for r in rows}
    if _row_key(row) in existing_keys:
        return False
    rows.append(dict(row))
    return save_floor_meta(storage_path, base_exponent, rows)


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


def merge_floor_meta_into_benchmark_log(storage_path, base_exponent):
    """Imports this floor's floor_meta.json rows into the storage root's
    benchmark_log.csv, skipping any row whose key (see _row_key) is already present. This
    is what makes a floor physically copied in from another storage (bringing its own
    floor_meta.json along) show up in THIS storage's Benchmark tab exactly as if it had
    been generated here. Called unconditionally from prime_atlas_v1.py's totals-cache
    background worker on every floor visit -- a no-op (returns 0) on the ordinary case
    where there's nothing new to import, so it's cheap to call every time rather than
    trying to separately detect "is this floor newly-copied-in".

    Returns the number of rows actually imported (0 if none, including when this floor has
    no floor_meta.json at all)."""
    meta = load_floor_meta(storage_path, base_exponent)
    if not meta or not meta["benchmark_rows"]:
        return 0
    log_path = os.path.join(storage_path, "benchmark_log.csv")
    fieldnames, existing_rows = _read_csv_rows(log_path)
    existing_keys = {_row_key(r) for r in existing_rows}
    to_import = [r for r in meta["benchmark_rows"] if _row_key(r) not in existing_keys]
    if not to_import:
        return 0
    if not fieldnames:
        fieldnames = list(CANONICAL_BENCHMARK_FIELDNAMES)
    # Grow the header (never shrink/reorder existing columns) if an imported row has a key
    # this log hasn't seen before -- additive, unlike _ensure_benchmark_log_schema()
    # elsewhere in this project (which migrates to one fixed target schema); this module
    # doesn't own a fixed schema, so it only ever adds columns, never rewrites their
    # meaning.
    extra_fields = []
    for row in to_import:
        for key in row.keys():
            if key not in fieldnames and key not in extra_fields:
                extra_fields.append(key)
    if extra_fields:
        fieldnames = fieldnames + sorted(extra_fields)
    all_rows = existing_rows + to_import
    try:
        os.makedirs(storage_path, exist_ok=True)
        _write_csv_rows(log_path, fieldnames, all_rows)
    except OSError:
        return 0
    return len(to_import)
