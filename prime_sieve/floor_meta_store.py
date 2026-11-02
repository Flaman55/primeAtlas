"""
floor_meta_store.py -- reading and appending a floor's 10p{N}/floor_meta.json.

floor_meta.json holds a copy of every benchmark_log.csv row a floor has produced, so the
floor's generation history travels with its own directory when the directory is copied
into another storage (primeatlas/settings/floor_meta.py imports the rows back into that
storage's benchmark_log.csv). The engines (orchestrator_v3.py, prime_sieve_primesieve.py,
prime_sieve_cudasieve.py, hybrid_sieve.py) append each row they log; the GUI's
floor_meta.py builds its merge/import logic on the functions here. This module depends
only on the standard library, so the engines stay runnable standalone under WSL with only
prime_sieve/ on sys.path.
"""
import json
import os

FLOOR_META_FILENAME = "floor_meta.json"

# What makes one benchmark row unique: a floor+range+run combination does not repeat at
# second resolution, so these fields dedup without a stronger hash.
ROW_KEY_FIELDS = ("run_timestamp_utc", "base_exponent", "target_idx_start", "target_idx_end")


def row_key(row):
    return tuple(str(row.get(f, "")) for f in ROW_KEY_FIELDS)


def floor_meta_path(storage_path, base_exponent):
    return os.path.join(storage_path, f"10p{base_exponent}", FLOOR_META_FILENAME)


def _read_file(path):
    """The parsed object of an existing floor_meta.json. Raises OSError/ValueError on an
    unreadable file and ValueError on one that is not a floor_meta object."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("benchmark_rows", []), list):
        raise ValueError(f"{path} is not a floor_meta object")
    return data


def load_floor_meta(storage_path, base_exponent):
    """Returns {"base_exponent": N, "benchmark_rows": [...]}, or None when the floor has no
    readable floor_meta.json. Never raises: a missing or corrupt file means no known
    history."""
    path = floor_meta_path(storage_path, base_exponent)
    if not os.path.exists(path):
        return None
    try:
        data = _read_file(path)
    except (OSError, ValueError):
        return None
    return {"base_exponent": data.get("base_exponent", base_exponent),
            "benchmark_rows": list(data.get("benchmark_rows", []))}


def save_floor_meta(storage_path, base_exponent, benchmark_rows):
    """Writes the floor's rows atomically (temp file + os.replace()). Returns False on an
    OSError, leaving any previous file intact."""
    path = floor_meta_path(storage_path, base_exponent)
    tmp_path = f"{path}.tmp{os.getpid()}"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"base_exponent": base_exponent, "benchmark_rows": benchmark_rows},
                      f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
        return True
    except OSError:
        return False
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def append_benchmark_row_to_floor_meta(storage_path, base_exponent, row):
    """Appends `row` (the dict just written to benchmark_log.csv) to the floor's
    floor_meta.json. Returns True when the row was added, False otherwise.

    Idempotent: a row whose row_key() is already present is skipped. An existing file that
    cannot be read is left untouched, since rewriting it would drop the history it holds.
    Never raises: callers run this after benchmark_log.csv is written, and a failure here
    must not turn a logged run into a failed one."""
    path = floor_meta_path(storage_path, base_exponent)
    try:
        rows = list(_read_file(path).get("benchmark_rows", [])) if os.path.exists(path) else []
        if row_key(row) in {row_key(r) for r in rows}:
            return False
        rows.append(dict(row))
        return save_floor_meta(storage_path, base_exponent, rows)
    except Exception:
        return False
