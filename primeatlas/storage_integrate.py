"""
storage_integrate.py -- the systemic fix for the scenario Artur hit manually (see
[[primeatlas_storage_merge_federation]]): someone downloads PrimeAtlas from GitHub, gets
a copy of someone else's magazyn (or one from another machine), and wants to fold it
into their own -- growing the local storage the way GIMPS folds in partial results from
many contributors.

Doing this with a generic file-copy tool forces the person to resolve a conflict dialog
for files that were never meant to be merged that way: `.portal_totals_cache.json` and
`.portal_generation_settings.json` at the storage ROOT (pure local-install convenience,
overwriting either way is harmless but pointless) and, more dangerously,
`benchmark_log.csv` at the root (overwriting it wholesale silently discards whichever
side's rows aren't picked -- there's no way to "merge" two CSVs file-for-file). This
module never touches any of those three files directly -- it only copies/merges the
FLOOR folders (10p{N}/source_primes, 10p{N}/constellations, 10p{N}/floor_meta.json),
which is the part that's actually safe to merge (see this module's own functions'
docstrings, and the CHECKPOINT.txt regression-safety fix in
constellation_finder_v1.py's _append_hits_deduped()). benchmark_log.csv then reconciles
itself automatically and additively the normal way -- via floor_meta.json travelling
with each floor and prime_atlas_v1.py's totals-worker importing it on the next visit to
that floor (floor_meta.merge_floor_meta_into_benchmark_log(), already wired) -- this
module gives that mechanism an immediate push per floor too (see integrate_floor()),
rather than waiting for a later visit.

Shape deliberately mirrors full_backup.py (plan_*() for a dry-run, then a per-floor
copy function with progress_cb/should_stop for a live progress bar) -- but this is a
LIVE-to-LIVE merge (both `destination_path` and `external_path` are real, uncompressed
PrimeAtlas storages), not a compressed backup, so files are copied as-is (no gzip).

Pure logic, no tkinter -- exercised directly by standalone tests, wired into the GUI by
settings_tab.py.
"""
import os
import shutil

from .manifest import PietroSnapshot, ConstellationSnapshot
from .delete_manager import FloorWiper
from . import floor_meta


def list_external_floors(external_path):
    """Every base_exponent with a 10p{N} folder present at `external_path`, sorted
    ascending -- reuses FloorWiper.list_floors() (already storage_path-agnostic; it
    only ever looks at whatever path it's constructed with, so pointing it at an
    external location works exactly the same as pointing it at the live storage)."""
    return FloorWiper(external_path).list_floors()


def _floor_source_dir(storage_path, base_exponent):
    return os.path.join(storage_path, f"10p{base_exponent}", "source_primes")


def _floor_const_dir(storage_path, base_exponent):
    return os.path.join(storage_path, f"10p{base_exponent}", "constellations")


def _file_size_or_zero(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def plan_integration(destination_path, external_path):
    """Dry-run: for every floor present at `external_path`, compares it against
    `destination_path` (via the same PietroSnapshot/ConstellationSnapshot scanning
    full_backup.py's own planning uses) and reports what integrate_floor() would add.
    Floors already fully present at the destination are OMITTED from the result --
    "nothing to do" is not an error, just not worth showing.

    Returns a list of per-floor dicts, newest floors last:
      {"base_exponent": int, "is_new_floor": bool,
       "missing_windows": [...], "missing_hits": [...], "missing_bytes": int}
    `is_new_floor` means the destination has no 10p{N} folder for this floor at all yet
    (a brand-new floor being adopted), as opposed to an existing floor merely gaining
    some additional files. `missing_bytes` sums the ON-DISK size of the missing files at
    the EXTERNAL side (what will actually need to be copied), for a human-readable
    size estimate in the preview -- best-effort (a file that vanishes between the scan
    and the size check just contributes 0, not a crash, since this is only a preview).

    Never touches benchmark_log.csv / .portal_totals_cache.json /
    .portal_generation_settings.json at either root -- see this module's own docstring
    for why those three are deliberately out of scope here."""
    destination_floors = set(FloorWiper(destination_path).list_floors())
    result = []
    for base_exponent in list_external_floors(external_path):
        live_dest = PietroSnapshot.scan(destination_path, base_exponent)
        live_ext = PietroSnapshot.scan(external_path, base_exponent)
        const_dest = ConstellationSnapshot.scan(destination_path, base_exponent)
        const_ext = ConstellationSnapshot.scan(external_path, base_exponent)

        missing_windows = sorted(set(live_ext.filenames) - set(live_dest.filenames))
        missing_hits = sorted(set(const_ext.hit_files) - set(const_dest.hit_files))
        if not missing_windows and not missing_hits:
            continue

        ext_source_dir = _floor_source_dir(external_path, base_exponent)
        ext_const_dir = _floor_const_dir(external_path, base_exponent)
        missing_bytes = sum(
            _file_size_or_zero(os.path.join(ext_source_dir, name)) for name in missing_windows
        ) + sum(
            _file_size_or_zero(os.path.join(ext_const_dir, rel)) for rel in missing_hits
        )

        result.append({
            "base_exponent": base_exponent,
            "is_new_floor": base_exponent not in destination_floors,
            "missing_windows": missing_windows,
            "missing_hits": missing_hits,
            "missing_bytes": missing_bytes,
        })
    result.sort(key=lambda entry: entry["base_exponent"])
    return result


class IntegrationCancelled(Exception):
    """Same cooperative-cancellation shape as full_backup.py's BackupCancelled --
    raised internally when `should_stop` returns True between files, caught by the
    caller. Whatever was already copied stays copied (only ever adds, safely
    resumable by re-running plan_integration()+integrate_floor())."""


def _stream_copy_plain(src_path, dst_path):
    """Plain (uncompressed) atomic streaming copy -- same temp-file+os.replace()
    pattern as every other file write in this project, but no gzip: both sides here
    are live, already-uncompressed PrimeAtlas storages, so there's nothing to
    compress/decompress, just bytes to move. shutil.copyfileobj() (inside
    shutil.copyfile) never holds a whole file in memory."""
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    tmp_path = f"{dst_path}.tmp{os.getpid()}"
    try:
        shutil.copyfile(src_path, tmp_path)
        os.replace(tmp_path, dst_path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


def integrate_floor(destination_path, external_path, base_exponent,
                     progress_cb=None, should_stop=None):
    """Copies every file this floor has at `external_path` but not yet at
    `destination_path` (per the same diff plan_integration() reports), in "windows
    before hits" order. Only ever ADDS files at the destination -- mirrors
    full_backup.py's copy_floor_increment() in every respect except there's no
    compression (both sides are live storages, not a backup archive).

    `progress_cb(phase, name, index, total)` / `should_stop()` -- identical shape to
    full_backup.py's copy_floor_increment(), so settings_tab.py can drive both with the
    same worker/queue/poll pattern.

    CHECKPOINT.txt/BOUNDARY_CHECKED.txt: only copied from the external side if the
    destination doesn't already have its OWN copy for this floor -- same "never
    regress a live floor's own scan progress" policy as
    full_backup.restore_floor_from_full_backup(), applied here because destination is
    the "live" side from this app's point of view. If the destination DOES already
    have a checkpoint, it's left completely untouched (even if the external side's is
    further along) -- the worst consequence of that conservative choice is some
    windows getting reprocessed by a later constellation-finder run, which is exactly
    the case _append_hits_deduped() (see constellation_finder_v1.py) already made
    safe -- see [[primeatlas_storage_merge_federation]].

    floor_meta.json rows are merged in additively (both directions are never touched:
    this only ever imports external's rows INTO destination's file, never the
    reverse), so this floor's generation history from the external magazyn becomes
    available locally too -- and, the next time prime_atlas_v1.py's totals worker
    visits this floor, those rows flow into the LOCAL benchmark_log.csv automatically
    (merge_floor_meta_into_benchmark_log(), already wired -- see this module's own
    docstring for why this file never touches benchmark_log.csv directly itself).

    Returns {"copied_windows": n, "copied_hits": n, "cancelled": bool}."""
    live_dest = PietroSnapshot.scan(destination_path, base_exponent)
    live_ext = PietroSnapshot.scan(external_path, base_exponent)
    const_dest = ConstellationSnapshot.scan(destination_path, base_exponent)
    const_ext = ConstellationSnapshot.scan(external_path, base_exponent)

    missing_windows = sorted(set(live_ext.filenames) - set(live_dest.filenames))
    missing_hits = sorted(set(const_ext.hit_files) - set(const_dest.hit_files))
    total = len(missing_windows) + len(missing_hits)
    copied_windows = 0
    copied_hits = 0
    cancelled = False

    dest_source_dir = _floor_source_dir(destination_path, base_exponent)
    ext_source_dir = _floor_source_dir(external_path, base_exponent)
    dest_const_dir = _floor_const_dir(destination_path, base_exponent)
    ext_const_dir = _floor_const_dir(external_path, base_exponent)

    try:
        for i, name in enumerate(missing_windows):
            if should_stop is not None and should_stop():
                cancelled = True
                raise IntegrationCancelled()
            if progress_cb is not None:
                progress_cb("window", name, i, total)
            _stream_copy_plain(os.path.join(ext_source_dir, name),
                                os.path.join(dest_source_dir, name))
            copied_windows += 1

        for j, rel_path in enumerate(missing_hits):
            if should_stop is not None and should_stop():
                cancelled = True
                raise IntegrationCancelled()
            if progress_cb is not None:
                progress_cb("hit", rel_path, len(missing_windows) + j, total)
            _stream_copy_plain(os.path.join(ext_const_dir, rel_path),
                                os.path.join(dest_const_dir, rel_path))
            copied_hits += 1
    except IntegrationCancelled:
        pass

    if const_dest.checkpoint_text is None and const_ext.checkpoint_text is not None:
        os.makedirs(dest_const_dir, exist_ok=True)
        checkpoint_dst = os.path.join(dest_const_dir, "CHECKPOINT.txt")
        tmp_path = f"{checkpoint_dst}.tmp{os.getpid()}"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(const_ext.checkpoint_text)
        os.replace(tmp_path, checkpoint_dst)

    dest_boundary_path = os.path.join(dest_const_dir, "BOUNDARY_CHECKED.txt")
    ext_boundary_path = os.path.join(ext_const_dir, "BOUNDARY_CHECKED.txt")
    if not os.path.exists(dest_boundary_path) and os.path.exists(ext_boundary_path):
        os.makedirs(dest_const_dir, exist_ok=True)
        tmp_path = f"{dest_boundary_path}.tmp{os.getpid()}"
        shutil.copyfile(ext_boundary_path, tmp_path)
        os.replace(tmp_path, dest_boundary_path)

    ext_meta = floor_meta.load_floor_meta(external_path, base_exponent)
    if ext_meta and ext_meta["benchmark_rows"]:
        floor_meta.merge_rows_into_floor_meta(
            destination_path, base_exponent, ext_meta["benchmark_rows"])

    return {"copied_windows": copied_windows, "copied_hits": copied_hits, "cancelled": cancelled}
