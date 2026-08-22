"""
full_backup.py -- the SECOND backup mode (alongside manifest.py/backup_store.py's
metadata-only one): a real, per-floor copy of the actual data (source_primes windows +
constellation hit files), gzip-compressed, kept at a location OUTSIDE the live storage
path. Restoring from this copies bytes back; it never needs to re-sieve or re-scan for
constellations the way the metadata-only mode's restore does.

Design (settled with Artur 2026-08-18/19, see [[primeatlas_full_data_backup_design]] for
the full discussion -- this docstring only summarizes the DECIDED shape):

  - Per-FLOOR, not whole-storage: the person picks which floors get a full-data backup
    (typically the deep, expensive-to-regenerate ones -- see suggest_full_backup_floors()
    below), not an all-or-nothing dump of the whole magazyn.

  - One PERSISTENT entry per floor at the destination, never a growing pile of
    timestamped snapshots. "Backing up" a floor again after it's grown just copies
    whatever's NEW since last time (via plan_floor_backup_update(), which reuses
    manifest.py's own PietroSnapshot/ConstellationSnapshot scanning -- the same
    file-existence comparison that already drives the metadata-only restore's diff).
    copy_floor_increment() ONLY EVER ADDS files at the destination, never removes one,
    even if something vanished from the live side (e.g. via FloorWiper) -- a full backup
    existing to protect against exactly that kind of mistake must not itself follow the
    mistake. See [[primeatlas_storage_merge_federation]] for the parallel reasoning
    behind CHECKPOINT.txt's own regression-safety fix.

  - The one administrative exception to "never overwrite" is CHECKPOINT.txt/
    BOUNDARY_CHECKED.txt (constellation-scan progress markers) -- these are scalar
    "how far did we get" pointers, not append-only data, so re-syncing them to whatever
    the live side currently says is correct and matches how they already behave during
    normal operation (write_checkpoint() itself always overwrites). floor_meta.json's
    OWN rows are still merged additively via manifest.py's existing
    merge_rows_into_floor_meta(), never overwritten wholesale.

  - Destination MUST be outside the live storage_path (validate_destination_path() below)
    -- a backup living inside the very thing it protects isn't a backup.

  - Per-file gzip compression (stdlib, no new dependency), NOT one big archive -- makes
    "add what's new" a plain filesystem operation (no archive rewrite), keeps a single
    missing window restorable without touching anything else, and gzip's own trailer CRC
    gives integrity verification on restore for free (a truncated/corrupted .gz raises
    on decompression -- see restore_floor_from_full_backup()'s own docstring).

Like every other module in this package, this is pure logic -- no tkinter import, no
dependency on prime_atlas_v1.py (which imports FROM this package, not the other way
around) -- exercised directly by standalone tests, wired into the GUI by settings_tab.py.
"""
import os
import csv
import gzip
import shutil
import datetime

from .manifest import PietroSnapshot, ConstellationSnapshot, _save_json_atomic, _load_json_best_effort
from . import floor_meta

FULL_BACKUP_META_FILENAME = "full_backup_meta.json"
GZ_SUFFIX = ".gz"


# ------------------------------------------------------------------------------------------
# Destination validation
# ------------------------------------------------------------------------------------------

def validate_destination_path(storage_path, destination_root):
    """Returns None if `destination_root` is a legitimate, independent location for a
    full-data backup of `storage_path`; otherwise one of the short reason codes below,
    for the caller (settings_tab.py) to turn into a translated error message. A HARD
    condition, not just a warning -- see this module's own docstring and
    [[primeatlas_full_data_backup_design]]: a backup living inside (or wrapping) the very
    thing it protects isn't a backup.

    Reason codes:
      "empty"              -- destination_root wasn't given at all.
      "same_as_storage"     -- resolves to the exact same directory as storage_path.
      "inside_storage"      -- destination_root is a subdirectory of storage_path (so a
                                whole-storage-path disaster, e.g. the drive it's on
                                failing, takes the backup down with it too).
      "storage_inside_destination" -- the reverse: storage_path is (or would become) a
                                subdirectory of destination_root, which risks the backup
                                job itself writing into ITS OWN storage path.

    Comparison is done on realpath()+normcase() so this is robust to relative paths,
    trailing slashes, symlinks, and Windows case-insensitivity/8.3 short names -- a naive
    string prefix check on the raw paths as typed would miss all of those."""
    if not destination_root or not str(destination_root).strip():
        return "empty"
    storage_real = os.path.normcase(os.path.realpath(storage_path))
    dest_real = os.path.normcase(os.path.realpath(destination_root))
    if storage_real == dest_real:
        return "same_as_storage"
    sep = os.sep
    if (dest_real + sep).startswith(storage_real + sep):
        return "inside_storage"
    if (storage_real + sep).startswith(dest_real + sep):
        return "storage_inside_destination"
    return None


# ------------------------------------------------------------------------------------------
# Destination-side scanning (mirrors manifest.py's live-storage scanning, but strips the
# .gz suffix each file is actually stored under)
# ------------------------------------------------------------------------------------------

def _floor_dest_dir(destination_root, base_exponent):
    return os.path.join(destination_root, f"10p{base_exponent}")

def _dest_source_dir(destination_root, base_exponent):
    return os.path.join(_floor_dest_dir(destination_root, base_exponent), "source_primes")

def _dest_const_dir(destination_root, base_exponent):
    return os.path.join(_floor_dest_dir(destination_root, base_exponent), "constellations")

def _meta_path(destination_root, base_exponent):
    return os.path.join(_floor_dest_dir(destination_root, base_exponent), FULL_BACKUP_META_FILENAME)


def list_destination_source_filenames(destination_root, base_exponent):
    """Real (non-.gz-suffixed) source-window filenames already present at the backup
    destination for this floor -- the destination-side half of the same comparison
    PietroSnapshot.missing_from() does on the live-storage side."""
    source_dir = _dest_source_dir(destination_root, base_exponent)
    if not os.path.isdir(source_dir):
        return []
    return sorted(
        name[:-len(GZ_SUFFIX)] for name in os.listdir(source_dir)
        if name.startswith("PRIME_WINDOW_") and name.endswith(".bin" + GZ_SUFFIX))


def list_destination_hit_filenames(destination_root, base_exponent):
    """Real (non-.gz-suffixed) "k{K}/variant{V}/HITS_....bin" relative paths already
    present at the backup destination for this floor -- destination-side half of
    ConstellationSnapshot.missing_from()."""
    const_dir = _dest_const_dir(destination_root, base_exponent)
    hit_files = []
    if not os.path.isdir(const_dir):
        return hit_files
    for k_name in os.listdir(const_dir):
        k_path = os.path.join(const_dir, k_name)
        if not (k_name.startswith("k") and k_name[1:].isdigit()) or not os.path.isdir(k_path):
            continue
        for variant_name in os.listdir(k_path):
            variant_path = os.path.join(k_path, variant_name)
            if not (variant_name.startswith("variant") and variant_name[7:].isdigit()) \
                    or not os.path.isdir(variant_path):
                continue
            for fname in os.listdir(variant_path):
                if fname.startswith("HITS_") and fname.endswith(".bin" + GZ_SUFFIX):
                    hit_files.append(f"{k_name}/{variant_name}/{fname[:-len(GZ_SUFFIX)]}")
    return sorted(hit_files)


def load_full_backup_meta(destination_root, base_exponent):
    """Returns the small per-floor sidecar {"base_exponent", "updated_at", ...} at the
    destination, or None if this floor has never been backed up here at all -- same
    best-effort, never-raises philosophy as load_totals_cache()/load_floor_meta()."""
    return _load_json_best_effort(_meta_path(destination_root, base_exponent))


def list_full_backup_floors(destination_root):
    """Every base_exponent that has a full-data backup entry at destination_root
    (identified by the presence of full_backup_meta.json, not just a 10p{N} folder --
    an empty/interrupted first-ever backup attempt that never reached the point of
    writing its own meta file shouldn't show up as a real entry). Returns
    [(base_exponent, meta_dict), ...] sorted ascending."""
    if not os.path.isdir(destination_root):
        return []
    result = []
    for name in os.listdir(destination_root):
        if not (name.startswith("10p") and name[3:].isdigit()):
            continue
        base_exponent = int(name[3:])
        meta = load_full_backup_meta(destination_root, base_exponent)
        if meta is not None:
            result.append((base_exponent, meta))
    result.sort(key=lambda t: t[0])
    return result


# ------------------------------------------------------------------------------------------
# Planning: what's new since the last time this floor was backed up here
# ------------------------------------------------------------------------------------------

def plan_floor_backup_update(storage_path, destination_root, base_exponent):
    """Compares the LIVE floor (storage_path) against what's already at the backup
    destination, returning {"missing_windows": [filenames...], "missing_hits": [relative
    paths...]} -- files that exist live but not yet at the destination, i.e. exactly what
    copy_floor_increment() needs to copy. Reuses manifest.py's own PietroSnapshot/
    ConstellationSnapshot for the live side (the SAME scan already driving the
    metadata-only backup/restore's diff), so there's no second, independently-maintained
    notion of "what does this floor's data look like" to keep in sync.

    Empty missing_windows/missing_hits (this floor is already fully backed up here) is a
    perfectly normal result, not an error -- the caller should treat that as "nothing to
    copy" rather than a failure."""
    live_pietro = PietroSnapshot.scan(storage_path, base_exponent)
    live_const = ConstellationSnapshot.scan(storage_path, base_exponent)
    dest_windows = set(list_destination_source_filenames(destination_root, base_exponent))
    dest_hits = set(list_destination_hit_filenames(destination_root, base_exponent))
    missing_windows = sorted(set(live_pietro.filenames) - dest_windows)
    missing_hits = sorted(set(live_const.hit_files) - dest_hits)
    return {"missing_windows": missing_windows, "missing_hits": missing_hits}


# ------------------------------------------------------------------------------------------
# Copy (backup) / restore -- streaming, gzip-compressed, atomic per file
# ------------------------------------------------------------------------------------------

def _stream_copy(src_path, dst_path, compress):
    """Shared streaming copy for both directions: compress=True gzips src_path's bytes
    into dst_path (backup direction), compress=False gunzips src_path's bytes into
    dst_path (restore direction). Always atomic (temp file + os.replace()). Chunked via
    shutil.copyfileobj() (64 KiB default buffer) -- never holds a whole file in memory."""
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    tmp_path = f"{dst_path}.tmp{os.getpid()}"
    try:
        if compress:
            with open(src_path, "rb") as src_f, gzip.open(tmp_path, "wb") as dst_f:
                shutil.copyfileobj(src_f, dst_f)
        else:
            # gzip.open()'s own read path validates the trailer CRC32 as it decompresses
            # -- a truncated or bit-flipped .gz raises BadGzipFile/zlib.error/EOFError
            # here rather than silently handing back corrupt bytes. That IS this
            # feature's integrity check (see this module's own docstring) -- no separate
            # checksum scheme needed.
            with gzip.open(src_path, "rb") as src_f, open(tmp_path, "wb") as dst_f:
                shutil.copyfileobj(src_f, dst_f)
        os.replace(tmp_path, dst_path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


class BackupCancelled(Exception):
    """Raised (internally, caught by the caller) when `should_stop` returns True between
    files -- cooperative cancellation at file granularity, never mid-file (a half-written
    .gz would fail its own CRC check on the next restore attempt anyway, but there is no
    reason to ever produce one)."""


def copy_floor_increment(storage_path, destination_root, base_exponent,
                          progress_cb=None, should_stop=None):
    """Copies every currently-missing file for this floor (per plan_floor_backup_update())
    from the live storage into a gzip-compressed mirror at destination_root, in the same
    "windows before hits" order restore_job.py's own docstring establishes elsewhere in
    this project. Only ever ADDS files at the destination -- never removes one, even if
    something vanished from the live side since the last backup (see this module's own
    docstring for why).

    `progress_cb(phase, name, index, total)`, if given, is called before each file copy
    (phase is "window" or "hit"), for a live progress bar. `should_stop()`, if given, is
    polled between files (never mid-file) -- returning True raises BackupCancelled, which
    the caller should catch; whatever was already copied stays copied (no rollback --
    consistent with "only ever adds", a cancelled run just means fewer files got added
    this time, safely resumable by running this again).

    After copying, CHECKPOINT.txt/BOUNDARY_CHECKED.txt (constellation-scan progress
    markers -- scalar pointers, not append-only data, see this module's own docstring)
    are re-synced to whatever the live side currently says, and floor_meta.json's rows
    are merged in additively (never overwritten) via manifest.py's existing
    merge_rows_into_floor_meta(). Finally writes/updates full_backup_meta.json (updated_at
    timestamp + file counts) -- but ONLY if anything was actually copied or the meta file
    doesn't exist yet, so re-running this on an already-fully-backed-up floor is a cheap,
    genuine no-op rather than needlessly bumping updated_at.

    Returns {"copied_windows": n, "copied_hits": n, "cancelled": bool}."""
    plan = plan_floor_backup_update(storage_path, destination_root, base_exponent)
    missing_windows = plan["missing_windows"]
    missing_hits = plan["missing_hits"]
    total = len(missing_windows) + len(missing_hits)
    copied_windows = 0
    copied_hits = 0
    cancelled = False

    source_dir = os.path.join(storage_path, f"10p{base_exponent}", "source_primes")
    dest_source_dir = _dest_source_dir(destination_root, base_exponent)
    const_dir = os.path.join(storage_path, f"10p{base_exponent}", "constellations")
    dest_const_dir = _dest_const_dir(destination_root, base_exponent)

    try:
        for i, name in enumerate(missing_windows):
            if should_stop is not None and should_stop():
                cancelled = True
                raise BackupCancelled()
            if progress_cb is not None:
                progress_cb("window", name, i, total)
            _stream_copy(os.path.join(source_dir, name),
                         os.path.join(dest_source_dir, name + GZ_SUFFIX), compress=True)
            copied_windows += 1

        for j, rel_path in enumerate(missing_hits):
            if should_stop is not None and should_stop():
                cancelled = True
                raise BackupCancelled()
            if progress_cb is not None:
                progress_cb("hit", rel_path, len(missing_windows) + j, total)
            _stream_copy(os.path.join(const_dir, rel_path),
                         os.path.join(dest_const_dir, rel_path + GZ_SUFFIX), compress=True)
            copied_hits += 1
    except BackupCancelled:
        pass

    # Administrative sidecars: always re-synced, not gated on "was anything new copied"
    # this run -- cheap either way, and keeps the destination's own progress markers
    # fresh even on a run that copied zero data files.
    live_const = ConstellationSnapshot.scan(storage_path, base_exponent)
    if live_const.checkpoint_text is not None:
        os.makedirs(dest_const_dir, exist_ok=True)
        checkpoint_dst = os.path.join(dest_const_dir, "CHECKPOINT.txt")
        tmp_path = f"{checkpoint_dst}.tmp{os.getpid()}"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(live_const.checkpoint_text)
        os.replace(tmp_path, checkpoint_dst)
    boundary_src = os.path.join(const_dir, "BOUNDARY_CHECKED.txt")
    if os.path.exists(boundary_src):
        os.makedirs(dest_const_dir, exist_ok=True)
        boundary_dst = os.path.join(dest_const_dir, "BOUNDARY_CHECKED.txt")
        tmp_path = f"{boundary_dst}.tmp{os.getpid()}"
        shutil.copyfile(boundary_src, tmp_path)
        os.replace(tmp_path, boundary_dst)

    live_meta = floor_meta.load_floor_meta(storage_path, base_exponent)
    if live_meta and live_meta["benchmark_rows"]:
        floor_meta.merge_rows_into_floor_meta(
            destination_root, base_exponent, live_meta["benchmark_rows"])

    existing_meta = load_full_backup_meta(destination_root, base_exponent)
    if copied_windows or copied_hits or existing_meta is None:
        real_window_count = len(list_destination_source_filenames(destination_root, base_exponent))
        real_hit_count = len(list_destination_hit_filenames(destination_root, base_exponent))
        new_meta = {
            "base_exponent": base_exponent,
            "updated_at": datetime.datetime.now(datetime.timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_window_count": real_window_count,
            "hit_file_count": real_hit_count,
        }
        _save_json_atomic(_meta_path(destination_root, base_exponent), new_meta)

    return {"copied_windows": copied_windows, "copied_hits": copied_hits, "cancelled": cancelled}


def plan_floor_restore(storage_path, destination_root, base_exponent):
    """Mirror of plan_floor_backup_update(), in the opposite direction: files present at
    the backup destination but missing from the live storage right now -- exactly what
    restore_floor_from_full_backup() needs to copy back. Returns the same
    {"missing_windows": [...], "missing_hits": [...]} shape (named from the LIVE side's
    point of view, same as the metadata-only restore's diff_against_disk())."""
    live_pietro = PietroSnapshot.scan(storage_path, base_exponent)
    live_const = ConstellationSnapshot.scan(storage_path, base_exponent)
    dest_windows = set(list_destination_source_filenames(destination_root, base_exponent))
    dest_hits = set(list_destination_hit_filenames(destination_root, base_exponent))
    missing_windows = sorted(dest_windows - set(live_pietro.filenames))
    missing_hits = sorted(dest_hits - set(live_const.hit_files))
    return {"missing_windows": missing_windows, "missing_hits": missing_hits}


def restore_floor_from_full_backup(storage_path, destination_root, base_exponent,
                                    progress_cb=None, should_stop=None):
    """Copies every file the backup destination has for this floor that the live storage
    is currently missing, decompressing as it goes (gzip's own trailer CRC32 catches a
    corrupted/truncated .gz on the way -- see _stream_copy()'s own docstring). Never
    overwrites a file that already exists locally -- if the live side already has a
    window/hit file under this name, it's left exactly as-is, matching the same
    conservative "only ever add, never overwrite real data" philosophy as the backup
    direction.

    CHECKPOINT.txt/BOUNDARY_CHECKED.txt (constellation-scan progress markers) are the
    one exception, but in the OPPOSITE direction from copy_floor_increment(): they're
    only written into the live storage if it doesn't already have its OWN copy -- this
    restore must never REGRESS a live floor's own, possibly more advanced, scan progress
    (same principle as _append_hits_deduped() in constellation_finder_v1.py, which makes
    it safe even if this guard were somehow bypassed -- see
    [[primeatlas_storage_merge_federation]]). floor_meta.json rows are merged additively,
    same as the backup direction.

    `progress_cb`/`should_stop` -- same shape as copy_floor_increment().

    Returns {"restored_windows": n, "restored_hits": n, "cancelled": bool}."""
    plan = plan_floor_restore(storage_path, destination_root, base_exponent)
    missing_windows = plan["missing_windows"]
    missing_hits = plan["missing_hits"]
    total = len(missing_windows) + len(missing_hits)
    restored_windows = 0
    restored_hits = 0
    cancelled = False

    source_dir = os.path.join(storage_path, f"10p{base_exponent}", "source_primes")
    dest_source_dir = _dest_source_dir(destination_root, base_exponent)
    const_dir = os.path.join(storage_path, f"10p{base_exponent}", "constellations")
    dest_const_dir = _dest_const_dir(destination_root, base_exponent)

    try:
        for i, name in enumerate(missing_windows):
            if should_stop is not None and should_stop():
                cancelled = True
                raise BackupCancelled()
            if progress_cb is not None:
                progress_cb("window", name, i, total)
            _stream_copy(os.path.join(dest_source_dir, name + GZ_SUFFIX),
                         os.path.join(source_dir, name), compress=False)
            restored_windows += 1

        for j, rel_path in enumerate(missing_hits):
            if should_stop is not None and should_stop():
                cancelled = True
                raise BackupCancelled()
            if progress_cb is not None:
                progress_cb("hit", rel_path, len(missing_windows) + j, total)
            _stream_copy(os.path.join(dest_const_dir, rel_path + GZ_SUFFIX),
                         os.path.join(const_dir, rel_path), compress=False)
            restored_hits += 1
    except BackupCancelled:
        pass

    live_checkpoint_path = os.path.join(const_dir, "CHECKPOINT.txt")
    backup_checkpoint_path = os.path.join(dest_const_dir, "CHECKPOINT.txt")
    if not os.path.exists(live_checkpoint_path) and os.path.exists(backup_checkpoint_path):
        os.makedirs(const_dir, exist_ok=True)
        tmp_path = f"{live_checkpoint_path}.tmp{os.getpid()}"
        shutil.copyfile(backup_checkpoint_path, tmp_path)
        os.replace(tmp_path, live_checkpoint_path)

    live_boundary_path = os.path.join(const_dir, "BOUNDARY_CHECKED.txt")
    backup_boundary_path = os.path.join(dest_const_dir, "BOUNDARY_CHECKED.txt")
    if not os.path.exists(live_boundary_path) and os.path.exists(backup_boundary_path):
        os.makedirs(const_dir, exist_ok=True)
        tmp_path = f"{live_boundary_path}.tmp{os.getpid()}"
        shutil.copyfile(backup_boundary_path, tmp_path)
        os.replace(tmp_path, live_boundary_path)

    backup_meta = floor_meta.load_floor_meta(destination_root, base_exponent)
    if backup_meta and backup_meta["benchmark_rows"]:
        floor_meta.merge_rows_into_floor_meta(
            storage_path, base_exponent, backup_meta["benchmark_rows"])

    return {"restored_windows": restored_windows, "restored_hits": restored_hits,
            "cancelled": cancelled}


def delete_full_backup_floor(destination_root, base_exponent):
    """Best-effort removal of one floor's ENTIRE full-data backup at destination_root --
    same best-effort philosophy as delete_manager.py's PortalWiper (a single locked file
    doesn't abort the whole thing). This is the one place a full-data backup's files DO
    get deleted -- an explicit, whole-floor, user-initiated removal, never an implicit
    side effect of updating or restoring a backup."""
    floor_dir = _floor_dest_dir(destination_root, base_exponent)
    if not os.path.isdir(floor_dir):
        return False
    shutil.rmtree(floor_dir, ignore_errors=True)
    return not os.path.isdir(floor_dir)


# ------------------------------------------------------------------------------------------
# Suggestion: which floors are expensive enough to be worth a full-data backup
# ------------------------------------------------------------------------------------------

def _read_benchmark_rows(storage_path):
    """Small, self-contained benchmark_log.csv reader -- deliberately NOT imported from
    prime_atlas_v1.py's own read_benchmark_log() (that module imports FROM this package,
    so the reverse import would be circular; same "duplicate the small helper" convention
    floor_meta.py's own docstring already establishes for the standalone generator
    engines). Returns [] if the file doesn't exist yet."""
    log_path = os.path.join(storage_path, "benchmark_log.csv")
    if not os.path.exists(log_path):
        return []
    with open(log_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def aggregate_generation_seconds_by_floor(rows):
    """Sums total_seconds per floor across every benchmark_log.csv row that actually
    wrote files (write_files=="1") -- same filter and rationale as prime_atlas_v1.py's
    own aggregate_write_seconds_by_pietro() (kept in sync by hand; see this module's own
    docstring for why it isn't imported directly). Returns {base_exponent: total_seconds}."""
    totals = {}
    for row in rows:
        if row.get("write_files") != "1":
            continue
        try:
            base_exponent = int(row.get("base_exponent", ""))
            seconds = float(row.get("total_seconds", ""))
        except (TypeError, ValueError):
            continue
        if seconds != seconds:  # NaN check without importing math for one use
            continue
        totals[base_exponent] = totals.get(base_exponent, 0.0) + seconds
    return totals


def suggest_full_backup_floors(storage_path, threshold_seconds=3600):
    """Floors whose MEASURED total generation time (summed across every real, file-
    writing benchmark_log.csv run for that floor) exceeds `threshold_seconds` -- Artur's
    own proposed default is one hour, per [[primeatlas_full_data_backup_design]]: "a
    floor costs more than an hour to regenerate" is worth trading disk space for restore
    speed, rather than guessing from the floor's bare number the way an earlier version
    of this design considered and rejected. Returns a sorted list of base_exponent ints
    -- the caller (settings_tab.py) uses this to pre-check/highlight those floors in the
    per-floor picker, not to force anything -- the person can still pick differently."""
    rows = _read_benchmark_rows(storage_path)
    totals = aggregate_generation_seconds_by_floor(rows)
    return sorted(be for be, seconds in totals.items() if seconds >= threshold_seconds)
