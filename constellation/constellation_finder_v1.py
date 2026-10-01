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
# constellation_finder_v1.py
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
# Progress is tracked with a single checkpoint per floor
# (CONSTELLATION_PORTAL/10p{N}/constellations/CHECKPOINT.txt, storing the last fully-
# processed PGS2 filename), covering every k.
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
# Peek-ahead threshold: uses the NEXT file's header base_prime + MAX_SPAN as the peek
# threshold (via read_prime_window_head), rather than reconstructing each window's
# nominal boundary independently of its content. The two differ by at most the gap from
# a window's nominal start to its first actual prime -- a handful of units, well within
# MAX_SPAN's margin (84 at the widest catalog entry, k=21) -- so this is safe and simpler.
#
# FLOOR-BOUNDARY crossings: the peek-ahead above only ever looks at the next window WITHIN
# THE SAME FLOOR -- the floor's own LAST window has no such next window to peek into, so a
# pattern whose base sits near the very top of one floor with its tail spilling into the
# next floor's numbers would otherwise never be checked. Every catalog pattern's offsets
# are non-negative, so a boundary-straddling constellation's base is always on the LOWER of
# the two floors -- see check_floor_boundary()'s own docstring for how this is closed,
# without touching the per-window CHECKPOINT.txt above at all: a separate, tiny
# BOUNDARY_CHECKED.txt marker per floor, and a clear informational print when the check
# can't be completed yet because the next floor has no data.
#
# Re-scanning is safe: a window can be scanned again (a constellations/ folder copied in
# from another storage, a checkpoint naming a window that no longer exists). Every write
# goes through _append_hits_deduped(), which drops already-stored values instead of
# tripping append_prime_window()'s strict-increase check, so a re-scan is idempotent.
# ==========================================================================================

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Self-contained alongside the rest of the app: prime_sieve_v1 lives in the sibling
# folder ../prime_sieve/.
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "..", "prime_sieve"))
import prime_sieve_v1  # noqa: E402
import window_sharding  # noqa: E402

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


def _proc_diag():
    """Cheap process-level diagnostics -- peak RSS memory and open file-descriptor
    count -- printed at key checkpoints throughout process_floor(). A very large
    source_primes/ folder can make the whole WSL process die silently (no Python
    traceback) purely from scale/volume, with no file corruption involved.

    Without this, a crash log shows nothing but the LAST line printed before the WSL
    wrapper process itself died -- a complete black box as to whether memory was
    climbing, file descriptors were leaking, or neither (pointing instead at something
    outside this process's own visibility, e.g. the WSL VM or its 9P filesystem driver
    hitting a wall on its own). Real numbers up to the moment of death narrow that down
    enormously the next time this happens.

    RSS via `resource.getrusage` (POSIX-only, see the top-of-file import guard --
    resource is None on Windows, only relevant to unitTests/test_constellation_finder_
    engine.py importing this module directly for its own pure-logic tests, never to a
    real run) and open-FD count via `/proc/self/fd` (Linux-only, always present inside
    WSL) are both essentially free to read -- no measurable overhead even called once
    per window."""
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
    print(f"[CONSTELLATIONS v1] DIAG: shard walk found {len(names_on_disk):,} window(s) "
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
        print(f"[CONSTELLATIONS v1] DIAG: read {len(new_names):,} fresh header(s) "
              f"({len(names_on_disk) - len(new_names):,} served from WINDOW_INDEX.tsv "
              f"cache) in {time.time()-t1:.2f}s | {_proc_diag()}")

    entries = [(name, paths_by_name[name], index[name]) for name in names_on_disk]
    entries.sort(key=lambda e: (e[2] is None, e[2] if e[2] is not None else 0, e[0]))
    print(f"[CONSTELLATIONS v1] DIAG: list_source_windows(10^{base_exponent}) done in "
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


def _stop_requested():
    """True once the GUI has asked this run to stop -- see STOP_REQUEST_FILENAME's own
    module-level comment. Deliberately a plain existence check, not consumed/deleted
    here: generation_tab.py's own _on_constellation_finished() owns cleanup (removing it
    once it has confirmed, via the exit sentinel, that the process actually stopped),
    since that's the one side guaranteed to run exactly once per launch regardless of
    whether this script noticed the marker itself or was hard-killed before it got the
    chance -- see that method's own docstring."""
    return os.path.exists(os.path.join(PORTAL_FOLDER, STOP_REQUEST_FILENAME))


def read_checkpoint(base_exponent):
    """Returns the filename of the last fully-processed PGS2 window for this floor, or
    None if there's no checkpoint yet."""
    path = _checkpoint_path(base_exponent)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("last_processed_file="):
                return line.split("=", 1)[1].strip()
    return None


def write_checkpoint(base_exponent, filename):
    """Atomic tmp-then-replace + fsync: opening CHECKPOINT.txt directly with "w" would
    TRUNCATE it before writing a single byte of the new content. Power loss (or a hard
    kill) landing between that truncation and the write completing would leave a 0-byte
    or partial file on disk; read_checkpoint() would then find no
    "last_processed_file=" line and silently return None, which process_floor() treats
    as "no checkpoint yet" -- reprocessing the WHOLE floor from window 0, discarding a
    potentially very long run's worth of progress on a large floor. Writing to a sibling
    .tmp file, fsync-ing ITS contents to disk, and only then os.replace()-ing it over the
    real path guarantees the on-disk file is always either the complete OLD checkpoint or
    the complete NEW one -- never a truncated in-between state -- even across a literal
    power cut, not just an orderly process kill. Same atomic pattern already used by
    _write_window_index() and _write_last_values_disk_cache() below; this is the one call
    site that most needed it, since losing THIS file is what makes process_floor() throw
    away an entire floor's worth of already-done work."""
    path = _checkpoint_path(base_exponent)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(f"last_processed_file={filename}\n")
        f.write(f"updated_at={datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


BOUNDARY_MARKER_FILENAME = "BOUNDARY_CHECKED.txt"


def _boundary_marker_path(base_exponent):
    folder = os.path.join(PORTAL_FOLDER, f"10p{base_exponent}", "constellations")
    return os.path.join(folder, BOUNDARY_MARKER_FILENAME)


def is_boundary_checked(base_exponent):
    """True once this floor's own upper boundary (against 10p{base_exponent+1}) has been
    fully resolved -- see check_floor_boundary()'s own docstring for what "resolved"
    covers. Deliberately a SEPARATE marker from CHECKPOINT.txt (read_checkpoint() above),
    not a field folded into it -- the two track genuinely different things (which WINDOWS
    have been streamed vs. whether the one cross-floor edge case has been closed off) and
    keeping them apart means neither file's own read/write logic has to change to
    accommodate the other."""
    return os.path.exists(_boundary_marker_path(base_exponent))


def write_boundary_checked(base_exponent, note):
    """Same atomic tmp-then-replace + fsync pattern as write_checkpoint() above, and for
    the same reason: a direct open(path, "w") truncates BOUNDARY_CHECKED.txt before
    writing its replacement, so a crash/power-loss mid-write can leave a marker file
    that is_boundary_checked() still finds (os.path.exists() is true for a 0-byte file
    too) but whose content is garbage -- silently corrupting the "already resolved"
    signal instead of just losing it outright."""
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
    """print() + explicit flush/fsync -- see HEARTBEAT_EVERY's own comment in
    process_floor() for why the fsync matters: a write() that already returned inside
    the WSL VM can still be sitting in a dirty page not yet physically synced across
    the 9P mount to the real Windows-side log file when the VM dies abruptly. Used for
    every diagnostic print in this file that sits right before or during a genuinely
    expensive operation (a full hit-file decode being the prime example, see
    _resolve_last_value() below) -- exactly the moments a crash log otherwise goes
    silent right when the detail matters most."""
    print(msg)
    try:
        sys.stdout.flush()
        os.fsync(sys.stdout.fileno())
    except OSError:
        pass  # best-effort -- must never crash the run over a diagnostic nicety


def _resolve_last_value(base_exponent, k, variant_id, disk_cache):
    """Returns (known_last_value, count) for this pattern's cumulative hit file --
    (None, 0) if it doesn't exist yet.

    Tries the on-disk cache (disk_cache, see _read_last_values_disk_cache()) FIRST,
    validated by a header-only read (read_prime_window_header(), ~264 bytes) against the
    file's current `count`: a match means the cached last_value is valid and the decode
    below is skipped. Falls back to decoding when the cache has no entry for this
    pattern yet, the hit file doesn't exist, or the counts DISAGREE (the file was
    modified outside this cache, e.g. a constellations/ folder copied in from another
    storage). An incorrect known_last_value would corrupt the gap-encoding (see
    append_prime_window()), so a stale entry is never trusted.

    The fallback uses prime_sieve_v1.read_prime_window_last_value(), not
    read_prime_window(): same O(count) walk of the gap stream, but keeping only the
    running last value instead of a list of millions of big integers."""
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
            f"[CONSTELLATIONS v1] DIAG: k={k} variant={variant_id} disk cache count "
            f"({cached_count:,}) does not match the hit file's real count "
            f"({real_count if real_count is not None else 'unreadable'}) -- falling "
            f"back to a full decode (file changed since the cache was last written).")
    # THE expensive path this whole cache exists to make rare -- see this function's
    # own docstring for the crash risk it carries on a large, dense hit file. Kept
    # visible (not silent) whenever it actually triggers, with size + timing, printed
    # (and fsynced) BEFORE the decode itself -- precisely so a crash DURING this decode
    # still leaves a clear "this is where it died, and this file's size is why" trail.
    if os.path.exists(hpath):
        size_bytes = os.path.getsize(hpath)
        _diag_fsync_print(
            f"[CONSTELLATIONS v1] DIAG: k={k} variant={variant_id} resolving last "
            f"value for {hpath} ({size_bytes:,} bytes, no cached entry or cache stale) "
            f"-- starting lean decode... | {_proc_diag()}")
        t_decode0 = time.time()
        last_value, count = prime_sieve_v1.read_prime_window_last_value(hpath)
        _diag_fsync_print(
            f"[CONSTELLATIONS v1] DIAG: k={k} variant={variant_id} lean decode done -- "
            f"{count:,} value(s), last={last_value}, in {time.time()-t_decode0:.2f}s "
            f"| {_proc_diag()}")
        return last_value, count
    return None, 0


def hit_file_path(base_exponent, k, variant_id):
    return os.path.join(
        PORTAL_FOLDER, f"10p{base_exponent}", "constellations", f"k{k}", f"variant{variant_id}",
        f"HITS_10p{base_exponent}_k{k}_v{variant_id}.bin")


def append_hits(base_exponent, k, variant_id, new_sorted_starts, known_last_value=None):
    """Appends newly-found match starting values (already sorted, all greater than
    anything previously stored for this floor since windows are processed in increasing
    order) to this pattern's cumulative hit file -- creating the k{K}/variant{ID}/ folder
    on first use, same auto-create-what's-missing approach as the scanner uses for
    source_primes/.

    `known_last_value` is threaded straight through to append_prime_window() -- see its
    docstring. Callers making many appends to the same (k, variant) across one
    process_floor() run (the common case: k=2..5 hit files pick up new entries on almost
    every window) should track it themselves and pass it, instead of letting
    append_prime_window() re-decode the whole accumulated hit file on every single call."""
    path = hit_file_path(base_exponent, k, variant_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    prime_sieve_v1.append_prime_window(path, new_sorted_starts, known_last_value=known_last_value)


def _append_hits_deduped(base_exponent, k, variant_id, new_sorted_starts, last_value_cache=None,
                          disk_cache=None):
    """Wraps append_hits() with a pre-filter against whatever this pattern's hit file's
    CURRENT last stored value actually is, dropping any of `new_sorted_starts` that are
    <= that value instead of handing them to append_prime_window() (which raises
    ValueError on exactly that condition -- see its own docstring: "must be strictly
    greater than the file's current last value").

    This makes re-scanning an already-covered window SAFE and idempotent (a
    constellations/ folder copied in from another storage, a checkpoint naming a
    missing window): matching is deterministic, so a re-scan produces the same values,
    which are skipped instead of tripping append_prime_window()'s ValueError. That check
    stays in append_prime_window() as an invariant for other callers.

    `last_value_cache`, if given, is a dict {(k, variant_id): (last_value, count)} the
    caller owns across a run (see process_floor()), so the hit file is not decoded on
    every call.

    `disk_cache`, if given, is the same dict persisted across runs (see
    _read_last_values_disk_cache()); consulted via _resolve_last_value() only when the
    pattern is not in last_value_cache (at most once per pattern per run). Without a
    valid entry in either, the last value comes from a full decode.

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
    else:
        to_append = [v for v in new_sorted_starts if v > known_last_value]
    skipped = len(new_sorted_starts) - len(to_append)

    if to_append:
        append_hits(base_exponent, k, variant_id, to_append, known_last_value=known_last_value)
        new_last_value = to_append[-1]
        new_count = old_count + len(to_append)
        if last_value_cache is not None:
            last_value_cache[key] = (new_last_value, new_count)
        if disk_cache is not None:
            disk_cache[key] = (new_last_value, new_count)
    else:
        if last_value_cache is not None:
            last_value_cache[key] = (known_last_value, old_count)
        if disk_cache is not None:
            disk_cache[key] = (known_last_value, old_count)

    return len(to_append), skipped


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
    as process_floor()'s own hits -- exactly matching how a person would expect a
    constellation to show up under whichever floor its base (its smallest, defining
    element) actually belongs to: a constellation with even one element on a lower floor
    and the rest on the next floor up is still shown as belonging to the lower floor.

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
    fully close off this floor's own constellation search, in preference to a heavier
    automatic-retry mechanism. Automatically re-checked (and closed) the next time
    constellation_finder runs on this
    floor, once that next-floor data exists -- no separate action needed beyond
    generating it."""
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
        print(f"[CONSTELLATIONS v1] NOTE: 10^{base_exponent}'s last window ({last_name}) "
              f"reaches within MAX_SPAN={max_span} of the floor boundary "
              f"({floor_boundary}) -- 10^{base_exponent + 1} has no source data yet, so a "
              f"pattern spanning the boundary can't be checked. Generate at least the "
              f"first window of 10^{base_exponent + 1} to close this off (re-checked "
              f"automatically on every future run of this floor until then).")
        return
    next_name, next_path, next_base = next_windows[0]
    if next_base is None:
        print(f"[CONSTELLATIONS v1] NOTE: 10^{base_exponent + 1}'s first window "
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
        print(f"[CONSTELLATIONS v1] Boundary check: {skipped_count} hit(s) already present "
              f"(skipped as duplicates, not appended again).")
    write_boundary_checked(
        base_exponent,
        f"checked against 10^{base_exponent + 1}'s first window ({next_name}) -- "
        f"{new_hits_count} boundary-spanning hit(s) found")
    print(f"[CONSTELLATIONS v1] Boundary check 10^{base_exponent} -> 10^{base_exponent + 1}: "
          f"{new_hits_count} new hit(s) spanning the floor boundary.")


def process_floor(base_exponent, max_windows=None):
    """Main entry point: streams through every not-yet-processed PGS2 window for this
    floor, in order, matching every catalog pattern (k>=2) and appending new hits. Also
    checks (once, then never again -- see check_floor_boundary()'s own docstring) whether
    a pattern spans this floor's own upper boundary into 10p{base_exponent+1}.

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

    Graceful stop: checked once per window, at the very TOP of the loop
    below, via STOP_REQUEST_FILENAME's own module-level comment -- a request never
    interrupts a window already in progress, only ever stops BETWEEN windows, for the
    same reason a --max-windows batch boundary is safe but a raw kill isn't: append_
    prime_window() writes a hit file's header (new count) before its own payload bytes,
    so a mid-window kill can leave a hit file's header claiming entries that were never
    actually written. Treated exactly like an ordinary clipped batch afterward (adds the
    unprocessed tail back into remaining_after, skips the boundary check) -- see the
    check's own inline comment for the exact mechanics."""
    run_start = time.time()
    windows = list_source_windows(base_exponent)
    if not windows:
        print(f"[!] No source_primes windows found for 10^{base_exponent} "
              f"(expected under {PORTAL_FOLDER}/10p{base_exponent}/source_primes/).")
        return 0

    active_patterns = list(PATTERN_CATALOG)
    max_span = max(w["offsets"][-1] for w in active_patterns)

    # See _read_last_values_disk_cache()'s own docstring for the crash this avoids --
    # loaded ONCE here (a handful of lines, one per catalog pattern, regardless of
    # floor size) and threaded through every _append_hits_deduped()/check_floor_
    # boundary() call below, written back once before every return point.
    disk_last_values = _read_last_values_disk_cache(base_exponent)

    last_done = read_checkpoint(base_exponent)
    names = [name for name, _, _ in windows]
    if last_done is not None and last_done in names:
        start_idx = names.index(last_done) + 1
        to_process_all = windows[start_idx:]
    else:
        if last_done is not None:
            print(f"[!] Checkpointed file {last_done!r} not found among current windows "
                  f"-- ignoring checkpoint, processing from the start.")
        to_process_all = windows

    if max_windows is not None and len(to_process_all) > max_windows:
        to_process = to_process_all[:max_windows]
        remaining_after = len(to_process_all) - max_windows
    else:
        to_process = to_process_all
        remaining_after = 0

    batch_note = f" (batch-limited to {max_windows}, {remaining_after} remain after this run)" if remaining_after else ""
    print(f"\n[CONSTELLATIONS v1] 10^{base_exponent}: {len(to_process)}/{len(windows)} "
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
    print(f"[CONSTELLATIONS v1] FLOOR PROGRESS: batch_size={len(to_process)} "
          f"total_windows={len(windows)} "
          f"already_done_before_batch={len(windows) - len(to_process_all)}")

    if not to_process:
        print("[CONSTELLATIONS v1] Nothing new -- checkpoint is up to date.")
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
    # (k, variant_id) -> last stored value in that pattern's cumulative hit file, tracked
    # IN MEMORY across this whole run so _append_hits_deduped() never has to re-decode
    # the already-accumulated hit file just to find where to resume gap-encoding from.
    # Without this, every append re-read the WHOLE growing file (see
    # append_prime_window()'s docstring in prime_sieve_v1.py) -- for common patterns like
    # k=2..5, which pick up new hits on nearly every window, that makes the total append
    # cost quadratic in the hit file's size over a floor's lifetime. Bootstrapped lazily
    # (at most once per pattern per run, from disk) the first time a pattern actually gets
    # a hit in this run. Also what makes duplicate-detection cheap across the whole run
    # (see _append_hits_deduped()'s own docstring) -- not just a performance cache.
    last_value_cache = {}

    print(f"[CONSTELLATIONS v1] DIAG: entering per-window loop, elapsed={time.time()-run_start:.2f}s "
          f"| {_proc_diag()}")

    # How often to print a heartbeat DIAG line and how often to print the lighter
    # per-window reading/summary lines below. Chosen small enough that a crash between
    # two heartbeats still narrows the death down to a tight window count, large
    # enough not to meaningfully slow down a 5000-window batch.
    HEARTBEAT_EVERY = 100
    # The first few windows of EVERY batch get much finer-grained diagnostics (one
    # print + explicit fsync after EACH sub-step: read, peek, match, checkpoint), so that
    # a crash between the "reading window i" line and its own per-window SUMMARY line
    # still narrows down which of those sub-steps (the read itself, the next-window peek,
    # pattern matching, or the checkpoint write) it actually died inside. Not applied to
    # every window in the batch -- fsync-ing after every sub-step of a large batch would
    # add real overhead -- but crashes tend to surface early in a batch, so the first few
    # windows are where this detail earns its cost; _diag_step() below is the shared
    # helper both this detailed path and the lighter one call into.
    DETAILED_DIAG_WINDOWS = 5

    def _diag_step(label, detailed):
        line = f"[CONSTELLATIONS v1] DIAG: {label} | {_proc_diag()}"
        if detailed:
            _diag_fsync_print(line)  # see HEARTBEAT_EVERY's own comment above, and
                                      # _diag_fsync_print()'s own docstring, on why
                                      # fsync matters here
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
            print(f"\n[CONSTELLATIONS v1] STOP REQUESTED -- stopping cleanly after {i} "
                  f"window(s) this run, {remaining_after} window(s) still pending for "
                  f"10^{base_exponent}.")
            break
        t0 = time.time()
        detailed = i < DETAILED_DIAG_WINDOWS
        # Printed BEFORE the read itself (not just in the per-window summary line
        # after it finishes) so that if the WSL process dies mid-read -- see this
        # function's own docstring on max_windows -- the log names the EXACT window
        # that was in flight when it happened, instead of dying with zero clue which
        # of the batch's files was involved.
        print(f"[CONSTELLATIONS v1] reading {i+1}/{len(to_process)}: {name}...")
        if detailed:
            try:
                size_bytes = os.path.getsize(path)
                header = prime_sieve_v1.read_prime_window_header(path)
                _diag_step(f"window {i+1} -- file size={size_bytes:,} bytes, "
                           f"header count={header['count']:,}", detailed=True)
            except OSError as e:
                _diag_step(f"window {i+1} -- could not stat/read header: {e}", detailed=True)
        elif i % HEARTBEAT_EVERY == 0:
            _diag_step(f"heartbeat at window {i+1}/{len(to_process)}, "
                       f"elapsed={time.time()-run_start:.2f}s", detailed=True)

        candidates = prime_sieve_v1.read_prime_window(path)
        if detailed:
            _diag_step(f"window {i+1} -- read_prime_window() returned "
                       f"{len(candidates):,} primes ({time.time()-t0:.2f}s so far)",
                       detailed=True)

        head = []
        if i + 1 < len(to_process):
            next_name, next_path, next_base = to_process[i + 1]
            if next_base is not None:
                head = prime_sieve_v1.read_prime_window_head(next_path, next_base + max_span)
        if detailed:
            _diag_step(f"window {i+1} -- peeked {len(head):,} value(s) from the next "
                       f"window ({time.time()-t0:.2f}s so far)", detailed=True)

        local_set = set(candidates)
        local_set.update(head)

        results = match_patterns_vectorized(candidates, local_set, active_patterns)
        if detailed:
            _diag_step(f"window {i+1} -- pattern matching done, "
                       f"{sum(len(v) for v in results.values())} raw match(es) across "
                       f"{len(results)} pattern(s) ({time.time()-t0:.2f}s so far)",
                       detailed=True)
        new_hits_count = 0
        skipped_hits_count = 0
        for (k, vid), matches in results.items():
            starts = sorted(m[0] for m in matches)
            key = (k, vid)
            # Deduped, not a plain append_hits() call -- CHECKPOINT.txt has no merge
            # logic of its own (see _append_hits_deduped()'s own docstring): if this
            # window is being RE-scanned (checkpoint regressed, e.g. a floor's
            # constellations/ folder was physically copied in from another storage that
            # had independently scanned some of the same windows, or the checkpoint's
            # named file just isn't among the current windows -- see the "ignoring
            # checkpoint, processing from the start" fallback above), the same values
            # would already be stored, and a plain append_hits() call would crash on
            # append_prime_window()'s own strict-increase assertion the instant that
            # happens. This makes re-scanning an already-covered window safe instead.
            appended, skipped = _append_hits_deduped(
                base_exponent, k, vid, starts, last_value_cache, disk_cache=disk_last_values)
            total_hits_this_run[key] = total_hits_this_run.get(key, 0) + appended
            new_hits_count += appended
            skipped_hits_count += skipped

        write_checkpoint(base_exponent, name)

        extra = f" skipped_duplicates={skipped_hits_count}" if skipped_hits_count else ""
        print(f"[CONSTELLATIONS v1] {i+1}/{len(to_process)}: {name} -- "
              f"primes={len(candidates):,} peeked_head={len(head)} "
              f"new_hits={new_hits_count}{extra} ({time.time()-t0:.2f}s)")

    if remaining_after:
        # This batch was clipped -- the floor is NOT fully caught up yet, so the
        # boundary check (which only makes sense once every one of the floor's own
        # windows, as of when this call started, has actually been streamed) is
        # skipped for now; the next batch's own process_floor() call runs it once
        # to_process finally reaches the tail of `windows`.
        print(f"\n[CONSTELLATIONS v1] BATCH DONE -- {remaining_after} window(s) still "
              f"remain for 10^{base_exponent}.")
    else:
        check_floor_boundary(base_exponent, windows, active_patterns, max_span, disk_cache=disk_last_values)

    _write_last_values_disk_cache(base_exponent, disk_last_values)

    print(f"\n[CONSTELLATIONS v1] Done. New hits this run, by pattern:")
    if not total_hits_this_run:
        print("    (none)")
    for (k, vid), count in sorted(total_hits_this_run.items()):
        print(f"    k={k:2} variant={vid}: +{count}")
    print(f"[CONSTELLATIONS v1] DIAG: run finished, elapsed={time.time()-run_start:.2f}s "
          f"| {_proc_diag()}")

    return remaining_after


if __name__ == "__main__":
    print("=" * 70)
    print("[*] CONSTELLATION FINDER -- v1 (PGS2 streaming + unified k=2..21 + "
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
            print(f"\n[CONSTELLATIONS v1] STOP REQUESTED -- skipping remaining floor(s) "
                  f"in this 'every floor with data' run.")
            break
        process_floor(base_exponent, max_windows=max_windows)
