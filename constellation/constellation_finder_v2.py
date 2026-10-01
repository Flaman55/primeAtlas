import sys
import os
import time
import datetime
import numpy as np

try:
    import resource  # POSIX-only -- this script always runs for real inside WSL, but
                      # is also imported directly on Windows by
                      # unitTests/test_constellation_finder_engine.py, so the import
                      # itself must not blow up there.
except ImportError:
    resource = None

# ==========================================================================================
# constellation_finder_v2.py
#
# Scans PGS2 prime windows for k-tuple patterns ("prime constellations") defined in
# pattern_catalog_v1.py, and appends newly found matches to per-pattern hit files.
#
# Source windows are read via prime_sieve_v1.read_prime_window / read_prime_window_head
# from CONSTELLATION_PORTAL/10p{N}/source_primes/, ordered by each file's base_prime
# (from its header) rather than by an offset parsed out of the filename.
#
# Every catalog pattern (k=2 and up) is matched by the same vectorized streaming
# pipeline: each window is scanned once, together with a peek into the head of the next
# window (up to MAX_SPAN past its base_prime) so that patterns spanning a window
# boundary are still found. Because a hit's full k-tuple is always recoverable from its
# starting value plus the pattern's fixed offsets, matches only need to be stored as
# sorted starting values.
#
# Hit storage: each (k, variant) pair gets its own cumulative file,
# CONSTELLATION_PORTAL/10p{N}/constellations/k{K}/variant{ID}/HITS_10p{N}_k{K}_v{ID}.bin,
# in the same PGS2 format as source_primes windows (see prime_sieve_v1.py). New hits are
# added via prime_sieve_v1.append_prime_window() (in-place header patch + tail append,
# not a full rewrite), which keeps the cost of accumulating hits over many runs linear
# rather than quadratic in the hit file's size -- important for patterns like k=2/3/4,
# which accumulate hits fastest.
#
# Progress is tracked per floor in CONSTELLATION_PORTAL/10p{N}/constellations/
# CHECKPOINT.txt, covering every k, as a set of already-processed window RANGES (see
# "gap-aware checkpoint" below), not just a single last-processed-filename pointer.
#
# Per-(k,variant) hit counts are available cheaply via
# read_prime_window_header(hit_path)['count'] (no full decode), which is enough to build
# an aggregate view -- e.g. for an HTML portal generator operating on
# pattern_catalog_v1.py's record_digits field -- without needing a separate report format
# maintained here.
#
# CLI: running with no floor argument auto-detects and processes every floor under the
# portal that has at least one source window (list_floors_with_data()); an explicit
# argument restricts the run to just that one floor.
#
# Peek-ahead threshold: the next window's header base_prime + MAX_SPAN (via
# read_prime_window_head), not a reconstructed nominal boundary. The two differ by at most
# the gap from a window's nominal start to its first prime, well within MAX_SPAN's margin
# (84 at the widest catalog entry, k=21).
#
# Floor boundary: a floor's last window has no successor within the floor. Every catalog
# offset is non-negative, so a boundary-straddling constellation's base lies on the lower
# floor; check_floor_boundary() handles it once per floor, recorded in a separate
# BOUNDARY_CHECKED.txt marker (CHECKPOINT.txt is not involved). If the next floor has no
# data yet, the check is skipped with an informational print.
#
# Re-scanning is safe: a window can be scanned again (a constellations/ folder copied in
# from another storage, a checkpoint naming a window that no longer exists, a crash before
# the done state was written). Every write goes through _append_hits_deduped(), which
# stores only values not already present, so a re-scan is idempotent.
#
# Checkpoint format: CHECKPOINT.txt stores DONE RANGES ("done_range=<first>|<last>", one
# per contiguous run of processed windows in base_prime order) via read_done_ranges()/
# write_done_ranges(), so an overlapping or partial checkpoint only costs re-scanning the
# missing windows. A `last_processed_file=` line (the highest done window) is written
# alongside for generation.py's read_constellation_checkpoint() and v1's
# read_checkpoint(). A v1-only CHECKPOINT.txt (no done_range= lines) is read as one range
# from the floor's first window through last_processed_file. The authoritative done set
# is DONE_WINDOWS.txt (see DONE_LOG_FILENAME); the ranges seed it on first use.
# ==========================================================================================

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Self-contained alongside the rest of the app: prime_sieve_v1 lives in the sibling
# folder ../prime_sieve/.
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "..", "prime_sieve"))
import prime_sieve_v1  # noqa: E402
import window_sharding  # noqa: E402
import hit_paging  # noqa: E402

from pattern_catalog_v1 import PATTERN_CATALOG  # noqa: E402

# CONSTELLATION_PORTAL_DIR: optional override for the portal's root folder, used by the
# GUI's Settings tab to point at a custom storage location. Falls back to a
# CONSTELLATION_PORTAL folder next to the application root (one level up from this
# file) when unset, matching AppSettings.default_storage_path.
PORTAL_FOLDER = os.environ.get("CONSTELLATION_PORTAL_DIR") or os.path.abspath(
    os.path.join(_SCRIPT_DIR, "..", "CONSTELLATION_PORTAL"))
CHECKPOINT_FILENAME = "CHECKPOINT.txt"
WINDOW_INDEX_FILENAME = "WINDOW_INDEX.tsv"
LAST_VALUES_FILENAME = "LAST_VALUES.tsv"
# Portal-ROOT (not per-floor) marker, checked once per window in process_floor()'s own
# loop below -- see that function's docstring for why a graceful, window-boundary-only
# stop matters here (append_prime_window()'s header-then-payload write order means a
# kill mid-window could corrupt a hit file, not just lose progress). One marker for the
# whole portal is enough since the GUI never runs more than one constellation_finder_
# v1.py instance at a time (same assumption WslLoggedRunner's own kill_pattern already
# relies on). Written by generation_tab.py's own _on_stop_constellation(), never by
# this script -- this side only ever reads it.
STOP_REQUEST_FILENAME = "STOP_REQUEST.txt"

# Crash-diagnosis instrumentation for process_floor()'s per-window loop (heartbeat line
# every HEARTBEAT_EVERY windows, plus fsync'd step-by-step detail for the first
# DETAILED_DIAG_WINDOWS windows of every batch), to locate which sub-step
# (read/peek/match/checkpoint) a silently dying WSL process was in. Off by default; set
# True while diagnosing a crash. Checked per branch (not around an already-built print()),
# so disabling it also skips the string-building/timing work.
CONSTELLATION_DIAG_ENABLED = False


def _proc_diag():
    """Cheap process-level diagnostics -- peak RSS memory and open file-descriptor
    count -- printed at key points in process_floor(). A WSL process dying from resource
    exhaustion (memory, file descriptors, the 9P filesystem driver) exits with no Python
    traceback; these numbers show which resource was growing.

    RSS via `resource.getrusage` (POSIX-only; `resource` is None on Windows, which only
    matters for unit tests importing this module) and open-FD count via `/proc/self/fd`
    (Linux-only, present inside WSL). Both are cheap enough to read once per window."""
    if resource is None:
        return "rss=n/a open_fds=n/a (non-POSIX)"
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    try:
        open_fds = len(os.listdir("/proc/self/fd"))
    except OSError:
        open_fds = -1
    return f"rss={rss_mb:.1f}MB open_fds={open_fds}"


def _window_index_path(base_exponent):
    folder = os.path.join(PORTAL_FOLDER, f"10p{base_exponent}", "constellations")
    return os.path.join(folder, WINDOW_INDEX_FILENAME)


def _read_window_index(base_exponent):
    """Returns {filename: base_prime_or_None} from the cached per-floor window index (see
    list_source_windows()'s docstring), or {} if no index exists yet."""
    path = _window_index_path(base_exponent)
    if not os.path.exists(path):
        return {}
    index = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            name, _, base_prime_str = line.partition("\t")
            index[name] = int(base_prime_str) if base_prime_str else None
    return index


def _write_window_index(base_exponent, index):
    path = _window_index_path(base_exponent)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        for name, base_prime in index.items():
            f.write(f"{name}\t{'' if base_prime is None else base_prime}\n")
    os.replace(tmp_path, path)


def list_source_windows(base_exponent):
    """Returns [(filename, path, base_prime), ...] for every PRIME_WINDOW_*.bin under
    10p{base_exponent}/source_primes/, ordered ascending by base_prime (from each file's
    header -- robust regardless of filename shorthand).

    SHARDING: source_primes/ is sharded into shard_NNNNN subfolders (see
    window_sharding.py): WSL's filesystem interop with the Windows-side mount degrades
    badly (the process dies silently, no Python traceback) once a directory holds
    roughly 100k entries. window_sharding.list_sharded_files() walks each shard
    subfolder (at most SHARD_SIZE entries each) instead of listing source_dir directly.

    WINDOW_INDEX.tsv cache: sorting needs every window's base_prime, which otherwise
    means opening every source window's header on every call -- hundreds of thousands
    of file opens on a large floor before any matching starts. Source windows are
    written once and never rewritten (unlike hit files), so a filename's base_prime is
    cached indefinitely: a call only reads the headers of files new since the index was
    last written and drops entries whose file is gone, making the per-call cost
    O(files added since last run)."""
    t0 = time.time()
    source_dir = os.path.join(PORTAL_FOLDER, f"10p{base_exponent}", "source_primes")
    sharded_files = window_sharding.list_sharded_files(
        source_dir,
        predicate=lambda name: name.startswith("PRIME_WINDOW_") and name.endswith(".bin"))
    if not sharded_files:
        return []
    paths_by_name = dict(sharded_files)
    names_on_disk = sorted(paths_by_name.keys())
    if CONSTELLATION_DIAG_ENABLED:
        print(f"[CONSTELLATIONS v2] DIAG: shard walk found {len(names_on_disk):,} window(s) "
              f"for 10^{base_exponent} in {time.time()-t0:.2f}s | {_proc_diag()}")

    names_on_disk_set = set(names_on_disk)
    index = {name: base_prime for name, base_prime in _read_window_index(base_exponent).items()
              if name in names_on_disk_set}
    new_names = [name for name in names_on_disk if name not in index]
    if new_names:
        t1 = time.time()
        for name in new_names:
            header = prime_sieve_v1.read_prime_window_header(paths_by_name[name])
            index[name] = header["base_prime"]
        _write_window_index(base_exponent, index)
        if CONSTELLATION_DIAG_ENABLED:
            print(f"[CONSTELLATIONS v2] DIAG: read {len(new_names):,} fresh header(s) "
                  f"({len(names_on_disk) - len(new_names):,} served from WINDOW_INDEX.tsv "
                  f"cache) in {time.time()-t1:.2f}s | {_proc_diag()}")

    entries = [(name, paths_by_name[name], index[name]) for name in names_on_disk]
    entries.sort(key=lambda e: (e[2] is None, e[2] if e[2] is not None else 0, e[0]))
    if CONSTELLATION_DIAG_ENABLED:
        print(f"[CONSTELLATIONS v2] DIAG: list_source_windows(10^{base_exponent}) done in "
              f"{time.time()-t0:.2f}s total | {_proc_diag()}")
    return entries


def list_floors_with_data():
    """Returns sorted base_exponent ints for every 10p{N} folder under PORTAL_FOLDER that
    actually has at least one PGS2 source window. Floor folders can exist as empty
    source_primes/constellations placeholders ahead of the scanner actually reaching
    them, so folder presence alone doesn't mean there's anything to process.

    A cheap directory-listing existence check, NOT a call into list_source_windows():
    on a floor not indexed yet that would read every window header, a cost
    process_floor() already pays once.

    source_primes/ directly contains only shard_NNNNN subfolders (see
    window_sharding.py), so "has_window" is checked one level down, inside the first
    existing shard subfolder (any floor with data has a non-empty shard_00000) -- a
    bounded listdir, not a full window_sharding.list_sharded_files() walk."""
    if not os.path.isdir(PORTAL_FOLDER):
        return []
    result = []
    for name in os.listdir(PORTAL_FOLDER):
        if name.startswith("10p") and name[3:].isdigit():
            base_exponent = int(name[3:])
            source_dir = os.path.join(PORTAL_FOLDER, name, "source_primes")
            if not os.path.isdir(source_dir):
                continue
            has_window = False
            for _shard_name, shard_path in window_sharding.iter_shard_dirs(source_dir):
                if any(fn.startswith("PRIME_WINDOW_") and fn.endswith(".bin")
                       for fn in os.listdir(shard_path)):
                    has_window = True
                    break
            if has_window:
                result.append(base_exponent)
    return sorted(result)


def _checkpoint_path(base_exponent):
    folder = os.path.join(PORTAL_FOLDER, f"10p{base_exponent}", "constellations")
    return os.path.join(folder, CHECKPOINT_FILENAME)


#: Every window name this floor's scan has finished, one per line, append-only. Tracked
#: by name rather than by done_range= lines: "first|last" resolves against the CURRENT
#: window list, so a window generated later between two scanned ones would count as done
#: without being searched. With the log, the search covers exactly the windows in storage
#: that are not in it, wherever they lie (the same name-based diff backup/restore uses).
#: CHECKPOINT.txt keeps its ranges (GUI progress, backups, and the fallback for a floor
#: whose log does not exist yet).
DONE_LOG_FILENAME = "DONE_WINDOWS.txt"


def _done_log_path(base_exponent):
    return os.path.join(PORTAL_FOLDER, f"10p{base_exponent}", "constellations", DONE_LOG_FILENAME)


def read_done_log(base_exponent):
    """The set of window names in this floor's done log, or None if it has no log yet."""
    path = _done_log_path(base_exponent)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def seed_done_log(base_exponent, names):
    """Creates the done log from `names` (atomic tmp-then-replace + fsync) -- used once
    per floor, from the legacy done_range= resolution."""
    path = _done_log_path(base_exponent)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        for name in sorted(names):
            f.write(name + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def append_done_log(base_exponent, names):
    """Appends newly finished window names (fsynced). A torn last line from a crash
    mid-append is just an unknown name -- that window gets scanned again, which is safe."""
    if not names:
        return
    path = _done_log_path(base_exponent)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for name in names:
            f.write(name + "\n")
        f.flush()
        os.fsync(f.fileno())


def _stop_requested():
    """True once the GUI has asked this run to stop (see STOP_REQUEST_FILENAME). A plain
    existence check, not consumed here: generation_tab.py's _on_constellation_finished()
    removes the marker, since it runs exactly once per launch whether this script saw the
    marker or was killed first."""
    return os.path.exists(os.path.join(PORTAL_FOLDER, STOP_REQUEST_FILENAME))


def read_checkpoint(base_exponent):
    """Returns the filename of the furthest-along PGS2 window recorded for this floor
    (the highest-index window covered by any done_range -- see write_done_ranges()'s own
    docstring for why this is still written even though process_floor() itself now
    resumes from read_done_ranges(), not this value), or None if there's no checkpoint
    yet. Kept for generation.py's own read_constellation_checkpoint() (GUI-side "did we
    make progress" comparison) and for v1-style callers/tests that only care about "how
    far has this floor gotten", not the full gap-aware picture."""
    path = _checkpoint_path(base_exponent)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("last_processed_file="):
                return line.split("=", 1)[1].strip()
    return None


def read_done_ranges(base_exponent):
    """Returns [(first_name, last_name), ...] -- the floor's own set of already-processed
    window ranges, in the order they were written (not necessarily sorted by position;
    resolve_done_names() below sorts/merges against the CURRENT window list). Empty list
    if there's no checkpoint yet.

    v1-checkpoint migration: a CHECKPOINT.txt with a "last_processed_file=" line but no
    "done_range=" lines at all (i.e. written by v1, or by v2 before this floor's very
    first done_range existed) is read as ONE range from the start of the floor through
    that filename -- exactly what v1's own "everything up to and including last_done"
    assumption already meant, so a floor already in progress under v1 loses nothing by
    switching to v2 mid-scan."""
    path = _checkpoint_path(base_exponent)
    if not os.path.exists(path):
        return []
    ranges = []
    legacy_last = None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("done_range="):
                first, _, last = line.split("=", 1)[1].partition("|")
                ranges.append((first, last))
            elif line.startswith("last_processed_file="):
                legacy_last = line.split("=", 1)[1].strip()
    if not ranges and legacy_last is not None:
        # None as the range's own start is a sentinel resolve_done_names() expands to
        # "the current window list's own first entry" -- deliberately not resolved here,
        # since this function has no access to the current window list.
        ranges.append((None, legacy_last))
    return ranges


def resolve_done_names(base_exponent, names):
    """Turns this floor's persisted done_ranges into a set of done window names,
    validated against `names` (the current base_prime-sorted window list, see
    list_source_windows()). A range whose boundary name is not in `names` cannot be
    resolved to a position and is dropped with a warning; its windows get re-scanned,
    which is safe (see _append_hits_deduped())."""
    if not names:
        return set()
    logged = read_done_log(base_exponent)
    if logged is not None:
        return logged.intersection(names)
    index_of = {name: i for i, name in enumerate(names)}
    done = set()
    for first, last in read_done_ranges(base_exponent):
        resolved_first = names[0] if first is None else first
        if resolved_first not in index_of or last not in index_of:
            print(f"[!] Checkpointed range {(first, last)!r} not resolvable among current "
                  f"windows for 10^{base_exponent} -- ignoring just this range.")
            continue
        start_i, end_i = index_of[resolved_first], index_of[last]
        if start_i > end_i:
            start_i, end_i = end_i, start_i
        done.update(names[start_i:end_i + 1])
    return done


def _merge_ranges_by_index(ranges_by_index):
    """Sorts (first_idx, last_idx) pairs and merges any that touch or overlap
    (last_idx + 1 >= next first_idx) into one -- keeps the persisted range list from
    growing without bound across a long floor scan, where the common case (windows
    processed strictly in order) should always collapse back down to a single range."""
    merged = []
    for start, end in sorted(ranges_by_index):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def write_done_ranges(base_exponent, names, done_indices):
    """Atomic tmp-then-replace + fsync (as v1's write_checkpoint()), persisting the full
    set of processed windows as merged (first_name|last_name) ranges over `names` (the
    current base_prime-sorted window list).

    `done_indices` -- every index into `names` that is done as of this write (the full
    set, not a delta); the range list stays short since processing is normally in order.

    Also writes `last_processed_file=` (the name at the highest done index) -- see
    read_checkpoint() for its readers."""
    path = _checkpoint_path(base_exponent)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sorted_indices = sorted(done_indices)
    ranges = []
    run_start = None
    prev = None
    for idx in sorted_indices:
        if run_start is None:
            run_start = idx
        elif idx != prev + 1:
            ranges.append((run_start, prev))
            run_start = idx
        prev = idx
    if run_start is not None:
        ranges.append((run_start, prev))
    ranges = _merge_ranges_by_index(ranges)

    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        if sorted_indices:
            f.write(f"last_processed_file={names[sorted_indices[-1]]}\n")
        f.write(f"updated_at={datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        for start, end in ranges:
            f.write(f"done_range={names[start]}|{names[end]}\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


BOUNDARY_MARKER_FILENAME = "BOUNDARY_CHECKED.txt"


def _boundary_marker_path(base_exponent):
    folder = os.path.join(PORTAL_FOLDER, f"10p{base_exponent}", "constellations")
    return os.path.join(folder, BOUNDARY_MARKER_FILENAME)


def is_boundary_checked(base_exponent):
    """True once this floor's upper boundary (against 10p{base_exponent+1}) has been
    resolved -- see check_floor_boundary(). A separate marker from CHECKPOINT.txt: it
    tracks the one cross-floor check, not which windows were streamed."""
    return os.path.exists(_boundary_marker_path(base_exponent))


def write_boundary_checked(base_exponent, note):
    """Atomic tmp-then-replace + fsync, as write_checkpoint(): a plain open(path, "w")
    truncates first, so a crash mid-write could leave a garbage marker that
    is_boundary_checked() still accepts (os.path.exists() is true for a 0-byte file)."""
    path = _boundary_marker_path(base_exponent)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(f"{note}\n")
        f.write(f"checked_at={datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _last_values_path(base_exponent):
    folder = os.path.join(PORTAL_FOLDER, f"10p{base_exponent}", "constellations")
    return os.path.join(folder, LAST_VALUES_FILENAME)


def _read_last_values_disk_cache(base_exponent):
    """Returns {(k, variant_id): (last_value, count)} from this floor's persistent
    last-value cache. process_floor()'s in-memory last_value_cache starts empty every
    run; without this, the first hit for a pattern in a run would decode the pattern's
    whole hit file to learn its last value, which for a dense pattern (k=2 on a large
    floor) can exhaust memory.

    Returns {} if no cache file exists yet (same contract as _read_window_index())."""
    path = _last_values_path(base_exponent)
    if not os.path.exists(path):
        return {}
    cache = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 4:
                continue  # a malformed line must never crash the run -- just skip it,
                          # same effect as this pattern having no cached entry at all
            k_str, vid_str, last_value_str, count_str = parts
            try:
                cache[(int(k_str), int(vid_str))] = (int(last_value_str), int(count_str))
            except ValueError:
                continue
    return cache


def _write_last_values_disk_cache(base_exponent, cache):
    """Writes the WHOLE cache at once, same atomic tmp-then-replace pattern as
    _write_window_index() -- called ONCE per process_floor() run (not once per append),
    since the cache holds at most one entry per CATALOG PATTERN (at most a few dozen,
    see PATTERN_CATALOG -- NOT one per window, unlike WINDOW_INDEX.tsv), so batching
    the write costs nothing and avoids dozens of tiny file writes scattered across a
    run for no benefit."""
    path = _last_values_path(base_exponent)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        for (k, vid), (last_value, count) in cache.items():
            f.write(f"{k}\t{vid}\t{last_value}\t{count}\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _diag_fsync_print(msg):
    """print() + explicit flush/fsync. Inside WSL a returned write() can still sit in a
    dirty page not yet synced across the 9P mount to the Windows-side log file when the
    VM dies. Used for diagnostics printed right before or during an expensive operation
    (e.g. a full hit-file decode in _resolve_last_value()), so the log shows where a run
    died."""
    print(msg)
    try:
        sys.stdout.flush()
        os.fsync(sys.stdout.fileno())
    except OSError:
        pass  # best-effort -- must never crash the run over a diagnostic nicety


def _resolve_last_value(base_exponent, k, variant_id, disk_cache):
    """Returns (known_last_value, count) for this pattern's cumulative hit file --
    (None, 0) if it doesn't exist yet.

    Order of lookup:
    1. Paged pattern (hit_paging.is_paged()): PAGES_META.json, kept in sync on every
       append (hit_paging.append_hits_paged()), O(1). Checked first because a migrated
       pattern's single file no longer grows, so its LAST_VALUES.tsv entry would go stale
       (and the header cross-check below reads hpath, which migration renames away).
    2. The on-disk cache (disk_cache, see _read_last_values_disk_cache()), validated by
       a header-only read (read_prime_window_header(), ~264 bytes) against the file's
       current `count`. A match means the cached last_value is valid.
    3. Otherwise -- no entry yet, no file, or a count mismatch (the file was modified
       outside this cache, e.g. a constellations/ folder copied in from another
       storage) -- a full decode. An incorrect known_last_value would corrupt the
       gap-encoding (see append_prime_window()), so a stale entry is never trusted.

    The fallback uses prime_sieve_v1.read_prime_window_last_value(), not
    read_prime_window(): same O(count) walk of the gap stream, but keeping only the
    running last value instead of a list of millions of big integers."""
    vdir = hit_paging.variant_dir(PORTAL_FOLDER, base_exponent, k, variant_id)
    if hit_paging.is_paged(vdir):
        meta = hit_paging.read_meta(vdir)
        return meta["last_value"], meta["total_count"]
    hpath = hit_file_path(base_exponent, k, variant_id)
    key = (k, variant_id)
    if disk_cache is not None and key in disk_cache and os.path.exists(hpath):
        cached_last_value, cached_count = disk_cache[key]
        try:
            real_count = prime_sieve_v1.read_prime_window_header(hpath)["count"]
        except (OSError, ValueError):
            real_count = None
        if real_count == cached_count:
            return cached_last_value, cached_count
        _diag_fsync_print(
            f"[CONSTELLATIONS v2] DIAG: k={k} variant={variant_id} disk cache count "
            f"({cached_count:,}) does not match the hit file's real count "
            f"({real_count if real_count is not None else 'unreadable'}) -- falling "
            f"back to a full decode (file changed since the cache was last written).")
    # The expensive path. Printed (and fsynced) with size and timing BEFORE the decode,
    # so a crash during it still leaves the file and its size in the log.
    if os.path.exists(hpath):
        size_bytes = os.path.getsize(hpath)
        _diag_fsync_print(
            f"[CONSTELLATIONS v2] DIAG: k={k} variant={variant_id} resolving last "
            f"value for {hpath} ({size_bytes:,} bytes, no cached entry or cache stale) "
            f"-- starting lean decode... | {_proc_diag()}")
        t_decode0 = time.time()
        last_value, count = prime_sieve_v1.read_prime_window_last_value(hpath)
        _diag_fsync_print(
            f"[CONSTELLATIONS v2] DIAG: k={k} variant={variant_id} lean decode done -- "
            f"{count:,} value(s), last={last_value}, in {time.time()-t_decode0:.2f}s "
            f"| {_proc_diag()}")
        return last_value, count
    return None, 0


def hit_file_path(base_exponent, k, variant_id):
    return os.path.join(
        PORTAL_FOLDER, f"10p{base_exponent}", "constellations", f"k{k}", f"variant{variant_id}",
        f"HITS_10p{base_exponent}_k{k}_v{variant_id}.bin")


def append_hits(base_exponent, k, variant_id, new_sorted_starts, known_last_value=None):
    """Appends match starting values (sorted, all greater than the pattern's last stored
    value) to this pattern's cumulative hit file, creating the k{K}/variant{ID}/ folder
    on first use.

    Paging-aware: PGS2's gap-encoding has no random access, so a dense pattern is split
    into pages (see hit_paging.py). For a paged pattern (hit_paging.is_paged()) the
    values go to the open page; an unpaged pattern uses the single-file path,
    `known_last_value` included.

    `known_last_value` is passed through to append_prime_window() (unpaged path only).
    Callers appending to the same (k, variant) many times in one run should track and
    pass it, so append_prime_window() doesn't decode the whole hit file on every call.

    AUTO-MIGRATES an unpaged pattern to pages when this append would push its count past
    hit_paging.PAGE_SIZE, so a pattern is migrated once at a small, predictable size
    (~PAGE_SIZE entries, seconds; streamed, see migrate_hit_file_to_pages()) instead of
    growing into a single file too large to browse. The count check is a header-only
    read (read_prime_window_header(), O(1))."""
    vdir = hit_paging.variant_dir(PORTAL_FOLDER, base_exponent, k, variant_id)
    if hit_paging.is_paged(vdir):
        hit_paging.append_hits_paged(vdir, base_exponent, k, variant_id, new_sorted_starts)
        return
    path = hit_file_path(base_exponent, k, variant_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        try:
            current_count = prime_sieve_v1.read_prime_window_header(path)["count"]
        except (OSError, ValueError):
            current_count = 0
        if current_count + len(new_sorted_starts) > hit_paging.PAGE_SIZE:
            _diag_fsync_print(
                f"[CONSTELLATIONS v2] DIAG: k={k} variant={variant_id} crossing "
                f"hit_paging.PAGE_SIZE ({current_count:,} + {len(new_sorted_starts):,} "
                f"> {hit_paging.PAGE_SIZE:,}) -- auto-migrating to pages before this "
                f"append... | {_proc_diag()}")
            t_migrate0 = time.time()
            hit_paging.migrate_hit_file_to_pages(path, vdir, base_exponent, k, variant_id)
            _diag_fsync_print(
                f"[CONSTELLATIONS v2] DIAG: k={k} variant={variant_id} auto-migration "
                f"done in {time.time()-t_migrate0:.2f}s | {_proc_diag()}")
            hit_paging.append_hits_paged(vdir, base_exponent, k, variant_id, new_sorted_starts)
            return
    prime_sieve_v1.append_prime_window(path, new_sorted_starts, known_last_value=known_last_value)


def _append_hits_deduped(base_exponent, k, variant_id, new_sorted_starts, last_value_cache=None,
                          disk_cache=None, defer_into=None):
    """Wraps append_hits(): values above this pattern's current last stored value are
    appended (append_prime_window() requires strictly greater ones); values at or below
    it go through _insert_hits_sorted(), which merges the new ones into the sorted
    storage and reports the rest as duplicates.

    This makes re-scanning a window safe and idempotent (a constellations/ folder copied
    in from another storage, a checkpoint naming a missing window, a crash before the
    done state was written): already-stored values are skipped instead of tripping
    append_prime_window()'s strict-increase check. That check stays in
    append_prime_window() as an invariant for other callers.

    `last_value_cache`, if given, is a dict {(k, variant_id): (last_value, count)} the
    caller owns across a run (see process_floor()), so the hit file is not decoded on
    every call.

    `disk_cache`, if given, is the same dict persisted across runs (see
    _read_last_values_disk_cache()); consulted via _resolve_last_value() only when the
    pattern is not in last_value_cache (at most once per pattern per run). Without a
    valid entry in either, the last value comes from a full decode.

    `defer_into`, if given, is a dict {(k, variant_id): [values]} that collects the
    values at or below the last stored one instead of merging them right away --
    process_floor() merges them in one go per batch (_flush_deferred_hits()), since a
    merge rewrites a whole page and a run of windows below the stored range would
    otherwise rewrite the same page once per window. Deferred values are counted in
    neither returned number.

    Returns (appended_count, skipped_count)."""
    if not new_sorted_starts:
        return 0, 0
    key = (k, variant_id)
    if last_value_cache is not None and key in last_value_cache:
        known_last_value, old_count = last_value_cache[key]
    else:
        known_last_value, old_count = _resolve_last_value(base_exponent, k, variant_id, disk_cache)

    if known_last_value is None:
        to_append = new_sorted_starts
        not_after_last = []
    else:
        to_append = [v for v in new_sorted_starts if v > known_last_value]
        not_after_last = [v for v in new_sorted_starts if v <= known_last_value]

    # A value <= the last stored one is a duplicate only if it is actually stored:
    # windows are not necessarily scanned in increasing order (a window generated below
    # or between already-scanned ones), so these are merged into the sorted storage,
    # which also separates real duplicates.
    if not_after_last and defer_into is not None:
        defer_into.setdefault(key, []).extend(not_after_last)
        inserted, skipped = 0, 0
    elif not_after_last:
        inserted, skipped = _insert_hits_sorted(base_exponent, k, variant_id, not_after_last)
    else:
        inserted, skipped = 0, 0
    new_last_value = known_last_value
    new_count = old_count + inserted
    if to_append:
        append_hits(base_exponent, k, variant_id, to_append, known_last_value=known_last_value)
        new_last_value = to_append[-1]
        new_count += len(to_append)
    if last_value_cache is not None:
        last_value_cache[key] = (new_last_value, new_count)
    if disk_cache is not None:
        disk_cache[key] = (new_last_value, new_count)

    return len(to_append) + inserted, skipped


def _flush_deferred_hits(base_exponent, deferred, last_value_cache, disk_cache):
    """Merges every pattern's deferred values (see _append_hits_deduped()'s defer_into)
    into its hit storage and empties `deferred`. Keeps both caches' counts in step (the
    last stored value cannot change: every deferred value was <= it). Returns
    ({(k, variant_id): added}, duplicates)."""
    added_by_key = {}
    duplicates = 0
    for key in sorted(deferred):
        values = sorted(set(deferred[key]))
        if not values:
            continue
        k, variant_id = key
        added, dup = _insert_hits_sorted(base_exponent, k, variant_id, values)
        added_by_key[key] = added
        duplicates += dup + (len(deferred[key]) - len(values))
        for cache in (last_value_cache, disk_cache):
            if cache is not None and key in cache:
                last_value, count = cache[key]
                cache[key] = (last_value, count + added)
    deferred.clear()
    return added_by_key, duplicates


def _insert_hits_sorted(base_exponent, k, variant_id, values):
    """Merges `values` (all <= the pattern's last stored value) into its hit storage as a
    sorted union. Returns (added, duplicates).

    Paged pattern: hit_paging.insert_hits_paged() rewrites only the pages the values fall
    into. Unpaged pattern: small by construction (auto-migration keeps it under
    hit_paging.PAGE_SIZE), so the whole file is decoded, merged and rewritten via a temp
    file + atomic replace; a merge that grows it past PAGE_SIZE migrates it to pages,
    same as append_hits() does for an append."""
    vdir = hit_paging.variant_dir(PORTAL_FOLDER, base_exponent, k, variant_id)
    if hit_paging.is_paged(vdir):
        _, added, duplicates = hit_paging.insert_hits_paged(vdir, base_exponent, k, variant_id, values)
        return added, duplicates
    path = hit_file_path(base_exponent, k, variant_id)
    old_values = prime_sieve_v1.read_prime_window(path)
    merged = sorted(set(old_values).union(values))
    added = len(merged) - len(old_values)
    if added == 0:
        return 0, len(values)
    tmp_path = path + ".merge.tmp"
    prime_sieve_v1.write_prime_window(tmp_path, merged)
    os.replace(tmp_path, path)
    if len(merged) > hit_paging.PAGE_SIZE:
        hit_paging.migrate_hit_file_to_pages(path, vdir, base_exponent, k, variant_id)
    return added, len(values) - added


def match_patterns_vectorized(candidates, local_set, active_patterns):
    """Computes a presence MASK (numpy, vectorized) once per UNIQUE offset used by ANY
    tracked pattern, instead of once per (pattern, candidate, offset) triple. Matching a
    specific pattern is then a bitwise AND of its offsets' precomputed masks.

    candidates      -- Python-int list, from the CURRENT window only (each candidate is
                        used as a pattern's "base" exactly once, in its own window).
    local_set       -- Python-int set: candidates + the peeked head of the next window
                        (possible targets for p+d).
    active_patterns -- catalog entries to check (includes k=2, see file header).

    Returns {(k, id): [[p, p+d2, ..., p+dk], ...]} -- full (absolute) values.

    Computes on LOCAL offsets relative to min(candidates), not absolute values: numpy
    int64 cannot hold magnitudes from floor 19 up.
    """
    if not candidates or not local_set:
        return {}

    base = min(candidates)
    candidates_local = np.fromiter((p - base for p in candidates), dtype=np.int64, count=len(candidates))
    local_sorted = np.fromiter(sorted(v - base for v in local_set), dtype=np.int64, count=len(local_set))

    unique_offsets = sorted(set(d for w in active_patterns for d in w["offsets"]))
    masks = {}
    for d in unique_offsets:
        shifted = candidates_local + d
        idx = np.searchsorted(local_sorted, shifted)
        idx_safe = np.clip(idx, 0, len(local_sorted) - 1)
        masks[d] = local_sorted[idx_safe] == shifted

    results = {}
    for pattern in active_patterns:
        offsets = pattern["offsets"]
        mask = masks[offsets[0]].copy()
        for d in offsets[1:]:
            mask &= masks[d]
        if not mask.any():
            continue
        key = (pattern["k"], pattern["id"])
        for i in np.nonzero(mask)[0]:
            p = candidates[int(i)]  # full-precision value from the original list
            results.setdefault(key, []).append([p + d for d in offsets])
    return results


def check_floor_boundary(base_exponent, windows, active_patterns, max_span, disk_cache=None):
    """Checks whether a k-tuple pattern's base could sit near the very TOP of this
    floor's own numeric range with its tail spilling into 10p{base_exponent+1} -- the one
    case process_floor()'s own per-window streaming loop can never catch on its own,
    since its own peek-ahead only ever looks at the next window WITHIN THE SAME FLOOR (see
    that function's docstring), and the floor's own last window has no such next window.
    Every catalog pattern's offsets are non-negative (base p is always the SMALLEST
    element: p, p+d2, ..., p+dk), so a boundary-straddling constellation's base is ALWAYS
    on the LOWER of the two floors involved -- meaning this only ever needs to look
    FORWARD, from this floor's own last window into the next floor's own first window,
    never backward. Any hit found here is recorded under THIS floor (base_exponent), same
    as process_floor()'s own hits -- matching how a constellation is expected to show up
    under whichever floor its base (its smallest, defining element) actually belongs to.

    Idempotent via a small per-floor marker file (is_boundary_checked() /
    write_boundary_checked(), BOUNDARY_CHECKED.txt) instead of re-running this on every
    single process_floor() call forever: once resolved, this returns immediately without
    touching disk again. "Resolved" means either (a) a real peek against
    10p{base_exponent+1}'s own first window already ran and any hits it found were
    recorded, or (b) the floor's own last window doesn't reach close enough to the
    boundary for ANY catalog offset to possibly cross it, so there was never anything to
    check in the first place.

    While UNRESOLVED -- the last window DOES reach close enough, but
    10p{base_exponent+1} has no source data on disk yet -- prints an informational note
    EVERY run instead of silently doing nothing, so a person scanning a leading-edge
    floor finds out they need to generate at least the first window of the next floor to
    fully close off this floor's own constellation search. Automatically re-checked (and
    closed) the next time constellation_finder runs on this floor, once that next-floor
    data exists -- no separate action needed beyond generating it."""
    if is_boundary_checked(base_exponent):
        return
    if not windows:
        return
    last_name, last_path, _last_base = windows[-1]
    last_candidates = prime_sieve_v1.read_prime_window(last_path)
    if not last_candidates:
        write_boundary_checked(base_exponent, "empty last window -- nothing to check")
        return
    floor_boundary = 10 ** (base_exponent + 1)
    max_candidate = last_candidates[-1]
    if max_candidate + max_span < floor_boundary:
        # Comfortably short of the boundary -- no catalog offset (at most max_span) could
        # ever reach past it from here, so no cross-floor pattern is even POSSIBLE from
        # this floor's own last window. Nothing to check, ever, for this floor -- close it
        # out immediately rather than leaving it to be silently re-evaluated (and
        # re-confirmed pointless) on every future run.
        write_boundary_checked(
            base_exponent,
            f"last window's highest prime ({max_candidate}) is more than MAX_SPAN "
            f"({max_span}) below the floor boundary ({floor_boundary}) -- no cross-floor "
            f"pattern is possible")
        return
    next_windows = list_source_windows(base_exponent + 1)
    if not next_windows:
        print(f"[CONSTELLATIONS v2] NOTE: 10^{base_exponent}'s last window ({last_name}) "
              f"reaches within MAX_SPAN={max_span} of the floor boundary "
              f"({floor_boundary}) -- 10^{base_exponent + 1} has no source data yet, so a "
              f"pattern spanning the boundary can't be checked. Generate at least the "
              f"first window of 10^{base_exponent + 1} to close this off (re-checked "
              f"automatically on every future run of this floor until then).")
        return
    next_name, next_path, next_base = next_windows[0]
    if next_base is None:
        print(f"[CONSTELLATIONS v2] NOTE: 10^{base_exponent + 1}'s first window "
              f"({next_name}) has no usable header (base_prime missing) -- boundary check "
              f"against 10^{base_exponent} skipped until this is resolved.")
        return
    head = prime_sieve_v1.read_prime_window_head(next_path, next_base + max_span)
    local_set = set(last_candidates)
    local_set.update(head)
    results = match_patterns_vectorized(last_candidates, local_set, active_patterns)
    new_hits_count = 0
    skipped_count = 0
    for (k, vid), matches in results.items():
        starts = sorted(m[0] for m in matches)
        # Passes disk_cache through so the persistent cache stays consistent, and goes
        # through _append_hits_deduped() for the same reason as process_floor()'s loop.
        appended, skipped = _append_hits_deduped(base_exponent, k, vid, starts, disk_cache=disk_cache)
        new_hits_count += appended
        skipped_count += skipped
    if skipped_count:
        print(f"[CONSTELLATIONS v2] Boundary check: {skipped_count} hit(s) already present "
              f"(skipped as duplicates, not appended again).")
    write_boundary_checked(
        base_exponent,
        f"checked against 10^{base_exponent + 1}'s first window ({next_name}) -- "
        f"{new_hits_count} boundary-spanning hit(s) found")
    print(f"[CONSTELLATIONS v2] Boundary check 10^{base_exponent} -> 10^{base_exponent + 1}: "
          f"{new_hits_count} new hit(s) spanning the floor boundary.")


def process_floor(base_exponent, max_windows=None):
    """Main entry point: streams through every not-yet-processed PGS2 window for this
    floor, matching every catalog pattern (k>=2) and storing new hits. Also checks once
    (see check_floor_boundary()) whether a pattern spans this floor's upper boundary into
    10p{base_exponent+1}.

    `max_windows` caps how many windows one call processes; None processes all of them.
    A whole floor in one process holds open hundreds of thousands of file handles (two
    per window: content plus a peek into the next) and WSL's 9P /mnt/ interop degrades
    under that kind of sustained load (see window_sharding.py for the directory-listing
    equivalent), with wsl.exe exiting without a captured exit code (see
    WslLoggedRunner). The cap lets the caller (generation_tab.py's
    _maybe_auto_retry_constellation()/_maybe_continue_constellation_batch()) run each
    batch in a fresh, short-lived WSL process. Returns the number of windows still
    remaining (0 once every window present when the call started is processed); the CLI
    prints it as the "BATCH DONE -- N window(s) still remain" line that
    generation_tab.py's _scan_const_chunk_for_batch_marker() parses.

    Graceful stop (STOP_REQUEST_FILENAME): checked at the top of each window, so a stop
    only happens BETWEEN windows -- append_prime_window() writes a hit file's header
    (new count) before its payload, so a mid-window kill can leave a header claiming
    entries that were never written. A stop is handled like a clipped batch (unprocessed
    tail added to remaining_after, boundary check skipped)."""
    run_start = time.time()
    windows = list_source_windows(base_exponent)
    if not windows:
        print(f"[!] No source_primes windows found for 10^{base_exponent} "
              f"(expected under {PORTAL_FOLDER}/10p{base_exponent}/source_primes/).")
        return 0

    active_patterns = list(PATTERN_CATALOG)
    max_span = max(w["offsets"][-1] for w in active_patterns)

    # Loaded once (one line per catalog pattern), threaded through every
    # _append_hits_deduped()/check_floor_boundary() call below and written back before
    # every return. See _read_last_values_disk_cache().
    disk_last_values = _read_last_values_disk_cache(base_exponent)

    names = [name for name, _, _ in windows]
    index_of = {name: i for i, name in enumerate(names)}
    done_names = resolve_done_names(base_exponent, names)
    if read_done_log(base_exponent) is None:
        # First run with the done log on this floor: seed it from the legacy ranges.
        seed_done_log(base_exponent, done_names)
    # done_indices seeds write_done_ranges()'s own running set below -- it has to start
    # from whatever's ALREADY resolved (not empty), or a run that adds only a handful of
    # new windows to a floor with a huge pre-existing done set would write those back as
    # if they were the ONLY thing ever done, discarding everything else on the very next
    # checkpoint write.
    done_indices = {i for i, name in enumerate(names) if name in done_names}
    to_process_all = [w for w in windows if w[0] not in done_names]

    if max_windows is not None and len(to_process_all) > max_windows:
        to_process = to_process_all[:max_windows]
        remaining_after = len(to_process_all) - max_windows
    else:
        to_process = to_process_all
        remaining_after = 0

    batch_note = f" (batch-limited to {max_windows}, {remaining_after} remain after this run)" if remaining_after else ""
    print(f"\n[CONSTELLATIONS v2] 10^{base_exponent}: {len(to_process)}/{len(windows)} "
          f"windows to process{batch_note} | patterns active: {len(active_patterns)} (k>=2) | "
          f"MAX_SPAN={max_span}")
    # Machine-parseable counterpart to the human-readable line above, so
    # generation_tab.py's own _update_shared_progress_from_generation_chunk() can show
    # progress against the WHOLE floor instead of just this one --max-windows-capped
    # batch (each chained batch's own per-window "i/len(to_process)" line -- see the loop
    # below -- only ever counts up to THIS batch's size, resetting to 1 every time a new
    # batch is chained). already_done_before_batch = len(windows) - len(to_process_all)
    # (everything the floor's own checkpoint already covered before this call started);
    # combined with this batch's own per-window "i/N" line, the GUI can derive
    # already_done_before_batch + i as a running total out of total_windows.
    print(f"[CONSTELLATIONS v2] FLOOR PROGRESS: batch_size={len(to_process)} "
          f"total_windows={len(windows)} "
          f"already_done_before_batch={len(windows) - len(to_process_all)}")

    if not to_process:
        print("[CONSTELLATIONS v2] Nothing new -- checkpoint is up to date.")
        # Still check the floor's own upper boundary even though there's no NEW window to
        # stream -- a floor fully checkpointed in a PAST run (hence to_process is empty
        # NOW) may only just have gotten its boundary resolvable THIS run, e.g. because
        # 10p{base_exponent + 1} was generated since the last time this floor was
        # processed. Skipping this here would mean a floor that's otherwise "done" never
        # gets its boundary checked at all once its own windows stop changing.
        check_floor_boundary(base_exponent, windows, active_patterns, max_span, disk_cache=disk_last_values)
        _write_last_values_disk_cache(base_exponent, disk_last_values)
        return 0

    total_hits_this_run = {}
    # (k, variant_id) -> (last stored value, count), kept IN MEMORY for the whole run so
    # _append_hits_deduped() never re-decodes a hit file to find where gap-encoding
    # resumes; without it, total append cost is quadratic in the hit file's size for
    # patterns like k=2..5 that get hits on nearly every window. Filled lazily, at most
    # once per pattern per run.
    last_value_cache = {}
    # Hits at or below a pattern's last stored value (a window below or between already
    # scanned ones) wait here and are merged once per batch -- see _append_hits_deduped()'s
    # defer_into. Their windows wait in pending_done: a window only joins the persisted
    # done set once its hits are stored, so a crash before the merge just means those
    # windows get scanned again (re-scanning is safe), never lost hits.
    deferred_hits = {}
    pending_done = []

    def _commit_pending():
        if not pending_done and not deferred_hits:
            return
        added_by_key, duplicates = _flush_deferred_hits(
            base_exponent, deferred_hits, last_value_cache, disk_last_values)
        for key, added in added_by_key.items():
            total_hits_this_run[key] = total_hits_this_run.get(key, 0) + added
        if added_by_key:
            print(f"[CONSTELLATIONS v2] merged {sum(added_by_key.values())} hit(s) from "
                  f"window(s) below already-stored values into storage"
                  + (f", {duplicates} duplicate(s) skipped" if duplicates else ""))
        append_done_log(base_exponent, [names[i] for i in pending_done])
        done_indices.update(pending_done)
        pending_done.clear()
        write_done_ranges(base_exponent, names, done_indices)

    if CONSTELLATION_DIAG_ENABLED:
        print(f"[CONSTELLATIONS v2] DIAG: entering per-window loop, elapsed={time.time()-run_start:.2f}s "
              f"| {_proc_diag()}")

    # How often to print a heartbeat DIAG line and the lighter per-window lines below:
    # small enough to narrow a crash down to a few windows, large enough not to slow a
    # 5000-window batch.
    HEARTBEAT_EVERY = 100
    # The first few windows of every batch get a print + fsync after EACH sub-step (read,
    # peek, match, checkpoint), so a crash inside a window shows which sub-step it was.
    # Limited to the first windows of a batch (where crashes have occurred) to keep the
    # fsync overhead off the rest.
    DETAILED_DIAG_WINDOWS = 5

    def _diag_step(label, detailed):
        line = f"[CONSTELLATIONS v2] DIAG: {label} | {_proc_diag()}"
        if detailed:
            _diag_fsync_print(line)  # fsync: see _diag_fsync_print()
        else:
            print(line)

    for i, (name, path, _base_prime) in enumerate(to_process):
        # Checked at the TOP of the loop, before any work on window i: append_prime_window()
        # writes a hit file's header (new count) before its payload, so killing the process
        # mid-window can corrupt that file. Stopping only between windows makes a graceful
        # stop as safe as a --max-windows batch boundary. The rest of THIS batch is added
        # back into `remaining_after` so the post-loop code reports the correct pending
        # count and skips the boundary check, as for an ordinary clipped batch.
        if _stop_requested():
            remaining_after += len(to_process) - i
            print(f"\n[CONSTELLATIONS v2] STOP REQUESTED -- stopping cleanly after {i} "
                  f"window(s) this run, {remaining_after} window(s) still pending for "
                  f"10^{base_exponent}.")
            break
        t0 = time.time()
        detailed = CONSTELLATION_DIAG_ENABLED and i < DETAILED_DIAG_WINDOWS
        # Printed BEFORE the read, so if the WSL process dies mid-read the log names the
        # window in flight.
        print(f"[CONSTELLATIONS v2] reading {i+1}/{len(to_process)}: {name}...")
        if detailed:
            try:
                size_bytes = os.path.getsize(path)
                header = prime_sieve_v1.read_prime_window_header(path)
                _diag_step(f"window {i+1} -- file size={size_bytes:,} bytes, "
                           f"header count={header['count']:,}", detailed=True)
            except OSError as e:
                _diag_step(f"window {i+1} -- could not stat/read header: {e}", detailed=True)
        elif CONSTELLATION_DIAG_ENABLED and i % HEARTBEAT_EVERY == 0:
            _diag_step(f"heartbeat at window {i+1}/{len(to_process)}, "
                       f"elapsed={time.time()-run_start:.2f}s", detailed=True)

        candidates = prime_sieve_v1.read_prime_window(path)
        if detailed:
            _diag_step(f"window {i+1} -- read_prime_window() returned "
                       f"{len(candidates):,} primes ({time.time()-t0:.2f}s so far)",
                       detailed=True)

        # Neighbours come from the floor's FULL window list, not from this batch: a window
        # generated between already-scanned ones has done neighbours on both sides, and
        # constellations running into them must still be found.
        position = index_of[name]
        head = []
        if position + 1 < len(windows):
            next_name, next_path, next_base = windows[position + 1]
            if next_base is not None and candidates and next_base <= candidates[-1] + max_span:
                # Only values a constellation based in THIS window can reach. The
                # successor may lie arbitrarily far above (e.g. windows generated at the
                # start of a floor whose scanned range begins much higher); values beyond
                # reach are useless and overflow match_patterns_vectorized()'s int64
                # local offsets.
                head = [v for v in prime_sieve_v1.read_prime_window_head(next_path, next_base + max_span)
                        if v <= candidates[-1] + max_span]
        # Look back once per contiguous run: the predecessor was scanned on its own
        # (earlier run or batch), possibly before this window existed, so a
        # constellation starting in its last max_span numbers and ending in this window
        # was never looked for. Already-stored ones come back as duplicates.
        back_tail = []
        if position > 0 and (i == 0 or to_process[i - 1][0] != windows[position - 1][0]) and candidates:
            back_values = prime_sieve_v1.read_prime_window(windows[position - 1][1])
            back_tail = [v for v in back_values if v >= candidates[0] - max_span]
        if detailed:
            _diag_step(f"window {i+1} -- peeked {len(head):,} value(s) from the next "
                       f"window ({time.time()-t0:.2f}s so far)", detailed=True)

        local_set = set(candidates)
        local_set.update(head)

        results = match_patterns_vectorized(candidates, local_set, active_patterns)
        if back_tail:
            back_results = match_patterns_vectorized(
                back_tail, local_set.union(back_tail), active_patterns)
            for key, matches in back_results.items():
                results.setdefault(key, []).extend(matches)
        if detailed:
            _diag_step(f"window {i+1} -- pattern matching done, "
                       f"{sum(len(v) for v in results.values())} raw match(es) across "
                       f"{len(results)} pattern(s) ({time.time()-t0:.2f}s so far)",
                       detailed=True)
        new_hits_count = 0
        skipped_hits_count = 0
        deferred_before = sum(len(v) for v in deferred_hits.values())
        for (k, vid), matches in results.items():
            starts = sorted(m[0] for m in matches)
            key = (k, vid)
            # Deduped, not a plain append_hits(): a window can be re-scanned (stale
            # done_range boundary, see resolve_done_names()), and re-appending its hits
            # would trip append_prime_window()'s strict-increase check.
            appended, skipped = _append_hits_deduped(
                base_exponent, k, vid, starts, last_value_cache, disk_cache=disk_last_values,
                defer_into=deferred_hits)
            total_hits_this_run[key] = total_hits_this_run.get(key, 0) + appended
            new_hits_count += appended
            skipped_hits_count += skipped
        deferred_now = sum(len(v) for v in deferred_hits.values()) - deferred_before

        pending_done.append(index_of[name])
        # Merge early once any pattern has a page's worth waiting (bounds memory on a
        # long unbatched run); otherwise once, at the end of the batch.
        if (not deferred_hits
                or any(len(v) >= hit_paging.PAGE_SIZE for v in deferred_hits.values())):
            _commit_pending()

        extra = f" skipped_duplicates={skipped_hits_count}" if skipped_hits_count else ""
        if deferred_now:
            extra += f" queued_below_stored={deferred_now}"
        print(f"[CONSTELLATIONS v2] {i+1}/{len(to_process)}: {name} -- "
              f"primes={len(candidates):,} peeked_head={len(head)} "
              f"new_hits={new_hits_count}{extra} ({time.time()-t0:.2f}s)")

    _commit_pending()

    if remaining_after:
        # This batch was clipped -- the floor is NOT fully caught up yet, so the
        # boundary check (which only makes sense once every one of the floor's own
        # windows, as of when this call started, has actually been streamed) is
        # skipped for now; the next batch's own process_floor() call runs it once
        # to_process finally reaches the tail of `windows`.
        print(f"\n[CONSTELLATIONS v2] BATCH DONE -- {remaining_after} window(s) still "
              f"remain for 10^{base_exponent}.")
    else:
        check_floor_boundary(base_exponent, windows, active_patterns, max_span, disk_cache=disk_last_values)

    _write_last_values_disk_cache(base_exponent, disk_last_values)

    print(f"\n[CONSTELLATIONS v2] Done. New hits this run, by pattern:")
    if not total_hits_this_run:
        print("    (none)")
    for (k, vid), count in sorted(total_hits_this_run.items()):
        print(f"    k={k:2} variant={vid}: +{count}")
    if CONSTELLATION_DIAG_ENABLED:
        print(f"[CONSTELLATIONS v2] DIAG: run finished, elapsed={time.time()-run_start:.2f}s "
              f"| {_proc_diag()}")

    return remaining_after


if __name__ == "__main__":
    print("=" * 70)
    print("[*] CONSTELLATION FINDER -- v2 (PGS2 streaming + unified k=2..21 + "
          "in-place-append hit files)")
    print("=" * 70)

    print(f"[*] Portal: {PORTAL_FOLDER}")
    print("Start time:", datetime.datetime.now().strftime("%H:%M:%S"))

    # Manual argv parsing (not argparse): one optional positional floor arg plus
    # --max-windows (see process_floor()).
    _args = sys.argv[1:]
    max_windows = None
    _positional = []
    _i = 0
    while _i < len(_args):
        if _args[_i] == "--max-windows":
            max_windows = int(_args[_i + 1])
            _i += 2
        else:
            _positional.append(_args[_i])
            _i += 1

    if _positional:
        floors = [int(_positional[0])]
    else:
        # No floor given -- auto-detect every one that actually has source_primes data.
        # process_floor() is already a cheap no-op for a floor whose checkpoint is fully
        # caught up, so scanning all of them each run is safe, not just at the moment a
        # new floor's data first appears.
        floors = list_floors_with_data()
        if not floors:
            print("[!] No floor folders with source_primes data found under the portal -- nothing to do.")
        else:
            print(f"[*] No floor given on the command line -- auto-detected {len(floors)} "
                  f"with data: {', '.join('10^' + str(n) for n in floors)}")

    for base_exponent in floors:
        if _stop_requested():
            print(f"\n[CONSTELLATIONS v2] STOP REQUESTED -- skipping remaining floor(s) "
                  f"in this 'every floor with data' run.")
            break
        process_floor(base_exponent, max_windows=max_windows)
