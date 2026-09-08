"""
repair_benchmark_log_sharding_bug.py -- one-off repair for a real bug found 2026-08-27:
orchestrator_v3.py's print_benchmark_summary() (write_files=True branch) re-derived
windows_written/total_primes by checking a FLAT "source_dir/PRIME_WINDOW_....bin" path
with os.path.exists() -- task #405 sharded source_primes/ into shard_NNNNN subfolders,
and this ONE function (unlike every other reader) was missed in that sweep. Every real,
correctly-written generation run since the sharding merge logged windows_written=0 and
total_primes=0 to benchmark_log.csv (and floor_meta.json), even though the actual PGS2
files were written completely correctly to disk.

This does NOT touch any PRIME_WINDOW_*.bin file -- only benchmark_log.csv and, if present,
each affected floor's floor_meta.json, which are pure bookkeeping/history, never the
underlying prime data itself.

WHAT IT DOES
------------
For every benchmark_log.csv row where write_files=="1" and windows_written=="0" (the exact,
narrow signature of this bug -- a real write_files=True run legitimately requesting 0
windows never happens in practice), re-scans the ACTUAL sharded files on disk for that
row's own (base_exponent, target_idx_start, target_idx_end) range and recomputes the five
fields that were derived from the broken count:
    windows_written, total_primes, seconds_per_window, avg_primes_per_window,
    primes_per_second
total_seconds itself (and every other column -- l_final, sieving_primes_count,
max_child_rss_mb, base_gen_seconds, sieve_seconds, write_seconds, bytes_written, the
instance_of_n/loop_* columns) was computed OUTSIDE the buggy code path and is left
completely untouched -- only the five fields that depended on the broken disk scan are
corrected.

If a row's window files are no longer on disk for some other reason (deleted since), it is
left unrepaired and reported, never guessed at.

SAFETY
------
- DRY RUN BY DEFAULT. Nothing is written unless you pass --apply.
- Backs up benchmark_log.csv to benchmark_log.csv.bak_<timestamp> before writing, and each
  touched floor_meta.json to floor_meta.json.bak_<timestamp>, every time --apply runs.
- Rewrites files atomically (write to .tmp, os.replace over the original).
- Window_m is assumed to be 10,000,000 (the project's one fixed window width -- see
  window_sharding.py's own docstring on why this is always a safe assumption project-wide).

USAGE
-----
    python repair_benchmark_log_sharding_bug.py "H:\\Goldbach"              # dry run
    python repair_benchmark_log_sharding_bug.py "H:\\Goldbach" --apply      # actually fix
"""
import argparse
import csv
import json
import math
import os
import shutil
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CANDIDATE_PRIME_SIEVE_DIRS = [
    os.path.join(_SCRIPT_DIR, "prime_sieve"),
    _SCRIPT_DIR,
]
for _d in _CANDIDATE_PRIME_SIEVE_DIRS:
    if os.path.isfile(os.path.join(_d, "window_sharding.py")):
        sys.path.insert(0, _d)
        break
else:
    print("[!] Could not find window_sharding.py next to this script or in a "
          "prime_sieve/ subfolder. Copy this script into primeAtlas/prime_sieve/ "
          "(next to window_sharding.py) or primeAtlas/ itself, then re-run.")
    sys.exit(1)

import window_sharding  # noqa: E402
import prime_sieve_v1  # noqa: E402

WINDOW_M = 10_000_000

BENCHMARK_FIELDNAMES = [
    "run_timestamp_utc", "base_exponent", "target_idx_start", "target_idx_end",
    "windows_written", "total_seconds", "seconds_per_window", "total_primes",
    "avg_primes_per_window", "primes_per_second", "l_final", "sieving_primes_count",
    "max_child_rss_mb", "instance_of_n", "loop_session_seconds", "loop_numbers_per_second",
    "loop_seconds_per_window", "write_files", "base_gen_seconds", "sieve_seconds",
    "write_seconds", "bytes_written", "engine", "numbers_processed",
]


def format_offset(n):
    if n == 0:
        return "0"
    if n % 1_000_000 == 0:
        return f"{n // 1_000_000}M"
    if n % 1_000 == 0:
        return f"{n // 1_000}k"
    return str(n)


def _recount_from_disk(portal_folder, base_exponent, start_idx, end_idx):
    """Mirrors the FIXED print_benchmark_summary() write_files=True branch exactly --
    scans the real sharded files on disk and returns (windows_found, total_primes)."""
    source_dir = os.path.join(portal_folder, f"10p{base_exponent}", "source_primes")
    total_primes = 0
    windows_found = 0
    for target_idx in range(start_idx, end_idx):
        offset = target_idx * WINDOW_M
        tag = f"10p{base_exponent}_off_{format_offset(offset)}"
        window_index = window_sharding.shard_index_for_offset(offset, WINDOW_M)
        shard_folder = window_sharding.shard_dir(source_dir, window_index)
        path = os.path.join(shard_folder, f"PRIME_WINDOW_{tag}.bin")
        if not os.path.exists(path):
            continue
        header = prime_sieve_v1.read_prime_window_header(path)
        total_primes += header["count"]
        windows_found += 1
    return windows_found, total_primes


def _is_buggy_row(row):
    return row.get("write_files") == "1" and row.get("windows_written") == "0"


def _repair_row(row, portal_folder):
    """Returns (changed: bool, new_row, note). Never raises -- any problem is reported in
    `note` and the row is left untouched."""
    try:
        base_exponent = int(row["base_exponent"])
        start_idx = int(row["target_idx_start"])
        end_idx = int(row["target_idx_end"]) + 1  # CSV stores the inclusive last idx
        total_seconds = float(row["total_seconds"])
    except (KeyError, TypeError, ValueError) as e:
        return False, row, f"could not parse row fields ({e})"

    windows_found, total_primes = _recount_from_disk(portal_folder, base_exponent,
                                                       start_idx, end_idx)
    if windows_found == 0:
        return False, row, (f"still finds 0 files on disk for target_idx "
                             f"{start_idx}..{end_idx - 1} -- files may have been moved/"
                             f"deleted since this run; leaving row untouched")

    seconds_per_window = total_seconds / windows_found
    avg_primes_per_window = total_primes / windows_found
    primes_per_second = total_primes / total_seconds if total_seconds > 0 else float("nan")

    new_row = dict(row)
    new_row["windows_written"] = str(windows_found)
    new_row["total_primes"] = str(total_primes)
    new_row["seconds_per_window"] = f"{seconds_per_window:.4f}"
    new_row["avg_primes_per_window"] = f"{avg_primes_per_window:.1f}"
    new_row["primes_per_second"] = f"{primes_per_second:.2f}"
    note = (f"10^{base_exponent} idx {start_idx}..{end_idx - 1}: "
            f"windows_written 0->{windows_found}, total_primes 0->{total_primes:,}")
    return True, new_row, note


def repair_benchmark_log(portal_folder, apply_changes):
    log_path = os.path.join(portal_folder, "benchmark_log.csv")
    if not os.path.exists(log_path):
        print(f"[!] No benchmark_log.csv found at {log_path} -- nothing to do.")
        return []

    with open(log_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    repaired_keys = []
    new_rows = []
    for row in rows:
        if _is_buggy_row(row):
            changed, new_row, note = _repair_row(row, portal_folder)
            if changed:
                print(f"    [+] {note}")
                repaired_keys.append((row.get("base_exponent"), row.get("target_idx_start"),
                                       row.get("target_idx_end")))
                new_rows.append(new_row)
                continue
            else:
                print(f"    [?] row skipped: {note}")
        new_rows.append(row)

    if not repaired_keys:
        print("    (no buggy rows found in benchmark_log.csv)")
        return []

    if apply_changes:
        backup_path = f"{log_path}.bak_{int(time.time())}"
        shutil.copy2(log_path, backup_path)
        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in new_rows:
                writer.writerow(row)
        os.replace(tmp_path, log_path)
        print(f"    benchmark_log.csv repaired ({len(repaired_keys)} row(s)). "
              f"Backup: {backup_path}")
    else:
        print(f"    Would repair {len(repaired_keys)} row(s) in benchmark_log.csv "
              f"(dry run -- nothing written).")

    return repaired_keys


def repair_floor_meta(portal_folder, repaired_keys, apply_changes):
    """Mirrors the same fix into each affected floor's floor_meta.json (see
    orchestrator_v3.py's _append_floor_meta_row -- same row data duplicated there so a
    floor's history travels with its own directory)."""
    by_floor = {}
    for base_exponent, start_idx, end_idx in repaired_keys:
        by_floor.setdefault(base_exponent, []).append((start_idx, end_idx))

    for base_exponent, ranges in by_floor.items():
        path = os.path.join(portal_folder, f"10p{base_exponent}", "floor_meta.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        rows = data.get("benchmark_rows", [])
        touched = 0
        for row in rows:
            key = (row.get("target_idx_start"), row.get("target_idx_end"))
            if key in ranges and _is_buggy_row(row):
                changed, new_row, note = _repair_row(row, portal_folder)
                if changed:
                    row.update(new_row)
                    touched += 1
        if touched:
            print(f"    [+] 10p{base_exponent}/floor_meta.json: {touched} row(s) to repair")
            if apply_changes:
                backup_path = f"{path}.bak_{int(time.time())}"
                shutil.copy2(path, backup_path)
                tmp_path = path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, path)
                print(f"        repaired. Backup: {backup_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("portal_folder", help="Storage root, e.g. H:\\Goldbach")
    parser.add_argument("--apply", action="store_true",
                         help="Actually rewrite benchmark_log.csv/floor_meta.json. "
                              "Without this flag, only reports what WOULD change.")
    args = parser.parse_args()

    if not os.path.isdir(args.portal_folder):
        print(f"[!] Not a directory: {args.portal_folder}")
        sys.exit(1)

    mode = "APPLY (files will actually be rewritten)" if args.apply else "DRY RUN (nothing will be written)"
    print(f"Mode: {mode}")
    print(f"Portal folder: {args.portal_folder}\n")

    print("=== benchmark_log.csv ===")
    repaired_keys = repair_benchmark_log(args.portal_folder, args.apply)

    if repaired_keys:
        print("\n=== floor_meta.json (per affected floor) ===")
        repair_floor_meta(args.portal_folder, repaired_keys, args.apply)

    if not args.apply and repaired_keys:
        print("\nThis was a DRY RUN. Re-run with --apply to actually repair the files.")


if __name__ == "__main__":
    main()
