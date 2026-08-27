"""
migrate_shard_source_primes.py -- one-off external migration for task #405's storage
sharding change.

WHY THIS EXISTS
----------------
Task #405 sharded source_primes/ into shard_NNNNN subfolders (see prime_sieve/
window_sharding.py) to fix constellation_finder_v1.py dying silently mid-scan on
floors with 100k+ flat window files (WSL/NTFS interop degrades badly past that
point). Every reader in primeAtlas (storage.py, constellation_finder_v1.py,
manifest.py, delete_manager.py, full_backup.py, storage_integrate.py,
restore_job.py) now ONLY looks inside shard_NNNNN subfolders -- a floor that was
generated before this change (flat PRIME_WINDOW_*.bin directly under
source_primes/) is now INVISIBLE to the app: 0 files, 0 totals, empty tree.

This script is the migration the task's own design deliberately deferred ("no
backward-compatibility needed for already-generated unsharded floors -- a
separate external migration script will handle those"). It moves each existing
flat window file into its correct shard_NNNNN subfolder, using the exact same
bucketing rule the app's own readers/writers use (window_sharding.py), so no
code path needs to change -- the app just needs the files to actually be where
it now looks.

SAFETY
------
- DRY RUN BY DEFAULT. Nothing is moved unless you pass --apply. Run once
  without --apply first and read the report.
- Never overwrites: if the computed destination already has a file with that
  name, the source is left in place and reported as a conflict for you to look
  at by hand.
- Never touches anything under constellations/ (hit files are explicitly out of
  scope for sharding -- see window_sharding.py's own docstring -- they are
  cumulative single files per (k, variant), never one-per-window).
- Never deletes anything -- files are MOVED (rename), not copied+deleted, and
  only within the same source_primes/ tree (parent dir -> its own shard_NNNNN
  child), so there is no window where a file exists in two places or in none.
- Idempotent: running it again after a successful --apply finds nothing left to
  move (every file that needed moving is already inside a shard_NNNNN folder).

HOW OFFSET IS DETERMINED
-------------------------
Real engine-written filenames are always "PRIME_WINDOW_10p{N}_off_{OFFSET}.bin"
(see prime_sieve_v1.py's format_offset/target_tag) -- the offset is parsed
straight from the filename, no file needs to be opened. For the rare foreign/
corrupt filename that doesn't match, this script falls back to opening the file
and computing offset = header.base_prime - 10**base_exponent; if even that
fails, the file is bucketed into shard_00000 (the same safe default
shard_dir_for_restored_offset() uses elsewhere in the codebase for an unknown
offset) and reported as a WARNING so you can look at it by hand -- it is never
skipped or lost.

USAGE
-----
    python migrate_shard_source_primes.py "H:\\Goldbach"              # dry run, report only
    python migrate_shard_source_primes.py "H:\\Goldbach" --apply      # actually move files

Run this against the live storage_path from primeatlas/locales/app_settings.json
(NOT a backup destination -- full_backup.py's backup-destination side is a
separate, deliberately out-of-scope known limitation, see full_backup.py's own
module comments).
"""
import argparse
import os
import re
import shutil
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Allow running this script from anywhere by pointing it at the repo's
# prime_sieve/ folder explicitly, in addition to trying the "next to this
# script" convenience case.
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

_OFFSET_FROM_NAME_RE = re.compile(r"_off_(\d+)(M|k)?\.bin$")
_FLOOR_DIR_RE = re.compile(r"^10p(\d+)$")
_PRIME_WINDOW_RE = re.compile(r"^PRIME_WINDOW_.*\.bin$")


def _offset_from_filename(name):
    m = _OFFSET_FROM_NAME_RE.search(name)
    if not m:
        return None
    n = int(m.group(1))
    suffix = m.group(2)
    if suffix == "M":
        n *= 1_000_000
    elif suffix == "k":
        n *= 1_000
    return n


def _offset_from_header_fallback(path, base_exponent):
    """Only reached for a filename that doesn't match the standard _off_ pattern
    at all (foreign/hand-renamed file) -- opens the file to read its header and
    derives an approximate offset from base_prime. Returns None if even this
    fails (caller then buckets into shard_00000 as a last resort)."""
    try:
        import prime_sieve_v1
        header = prime_sieve_v1.read_prime_window_header(path)
        base_prime = header.get("base_prime")
        if base_prime is None:
            return None
        offset = base_prime - (10 ** base_exponent)
        return offset if offset >= 0 else 0
    except Exception:
        return None


def migrate_floor(source_dir, base_exponent, apply_changes):
    """Moves every flat PRIME_WINDOW_*.bin directly under source_dir (i.e. NOT
    already inside a shard_NNNNN subfolder) into its correct shard_NNNNN
    subfolder. Returns (moved, conflicts, warnings, other_files) counts."""
    if not os.path.isdir(source_dir):
        return 0, 0, 0, 0

    moved = conflicts = warnings = other_files = 0
    with os.scandir(source_dir) as it:
        entries = list(it)

    for entry in entries:
        if entry.is_dir():
            # Existing shard_NNNNN folders (or anything else) -- never descend,
            # never touch. Only flat top-level FILES are migration candidates.
            continue
        name = entry.name
        if not _PRIME_WINDOW_RE.match(name):
            other_files += 1
            print(f"    [?] not a PRIME_WINDOW_*.bin file, leaving alone: {name}")
            continue

        offset = _offset_from_filename(name)
        if offset is None:
            offset = _offset_from_header_fallback(entry.path, base_exponent)
            if offset is None:
                warnings += 1
                print(f"    [!] WARNING: could not determine offset for {name} "
                      f"(no _off_ suffix, header read failed) -- bucketing into "
                      f"shard_00000 as a safe fallback. Look at this file by hand.")
                offset = 0
            else:
                print(f"    [i] {name}: offset recovered from file header "
                      f"(no _off_ suffix in filename) -> {offset}")

        dest_dir = window_sharding.shard_dir_for_restored_offset(source_dir, offset)
        dest_path = os.path.join(dest_dir, name)

        if os.path.exists(dest_path):
            conflicts += 1
            print(f"    [!] CONFLICT: {name} -- destination already has a file "
                  f"with this name ({dest_path}). Left source in place -- "
                  f"resolve by hand.")
            continue

        if apply_changes:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.move(entry.path, dest_path)
        moved += 1
        verb = "moved" if apply_changes else "would move"
        print(f"    [+] {verb}: {name} -> {os.path.basename(dest_dir)}/")

    return moved, conflicts, warnings, other_files


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("portal_folder", help="Storage root, e.g. H:\\Goldbach "
                         "(the storage_path from app_settings.json)")
    parser.add_argument("--apply", action="store_true",
                         help="Actually move files. Without this flag, only reports "
                              "what WOULD be moved (dry run).")
    args = parser.parse_args()

    portal_folder = args.portal_folder
    if not os.path.isdir(portal_folder):
        print(f"[!] Not a directory: {portal_folder}")
        sys.exit(1)

    mode = "APPLY (files will actually be moved)" if args.apply else "DRY RUN (nothing will be moved)"
    print(f"Mode: {mode}")
    print(f"Portal folder: {portal_folder}\n")

    total_moved = total_conflicts = total_warnings = total_other = 0
    floors_touched = 0

    for name in sorted(os.listdir(portal_folder)):
        m = _FLOOR_DIR_RE.match(name)
        if not m:
            continue
        base_exponent = int(m.group(1))
        source_dir = os.path.join(portal_folder, name, "source_primes")
        if not os.path.isdir(source_dir):
            continue

        print(f"=== 10p{base_exponent} ({source_dir}) ===")
        moved, conflicts, warnings, other = migrate_floor(source_dir, base_exponent, args.apply)
        if moved or conflicts or warnings or other:
            floors_touched += 1
        total_moved += moved
        total_conflicts += conflicts
        total_warnings += warnings
        total_other += other
        if not (moved or conflicts or warnings or other):
            print("    (nothing to do -- already sharded or empty)")
        print()

    print("=" * 60)
    verb = "Moved" if args.apply else "Would move"
    print(f"{verb}: {total_moved} file(s) across {floors_touched} floor(s)")
    if total_conflicts:
        print(f"Conflicts (left in place, needs manual look): {total_conflicts}")
    if total_warnings:
        print(f"Warnings (offset guessed, bucketed to shard_00000): {total_warnings}")
    if total_other:
        print(f"Non-window files skipped untouched: {total_other}")
    if not args.apply and total_moved:
        print("\nThis was a DRY RUN. Re-run with --apply to actually move the files.")


if __name__ == "__main__":
    main()
