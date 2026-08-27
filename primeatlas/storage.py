"""
storage.py -- the core prime-window storage layer: listing which floors (10p{N}
folders) and PRIME_WINDOW_*.bin source files exist on disk, reading their headers, the
per-floor "total prime count" cache that makes repeat visits cheap, and the plain
formatting helpers (byte counts, durations, shortened big integers) used to display all
of it. Also find_prime_in_floor(), the binary-search lookup the "Prime numbers" tab's
search box and the shared cross-tab search worker both use.

Also the persisted GLOBAL total (GLOBAL_TOTAL_KEY / get_global_total() /
recompute_global_total()) and the incremental bump_pietro_total()/remove_pietro_total()
pair, added 2026-08-27 after Artur pointed out that update_pietro_totals_cache() being
the ONLY way any total ever gets refreshed meant a full directory-listing + os.stat()-
every-file pass ran for EVERY floor on every startup/reload, even when nothing had
changed since the last visit -- see those functions' own docstrings. The three real
write paths that actually change a floor's contents (generation finishing a run,
storage_integrate.py merging in an external floor, delete_manager.py deleting one) now
call bump_pietro_total()/remove_pietro_total() directly with a known delta instead of
relying on the next full rescan to notice; the full rescan itself is untouched and still
exists as a manual "Zweryfikuj sumy" verify action (primes_tab.py) for the rare case
these totals ever drift (a crash mid-write, or files touched outside the app).

Extracted from prime_atlas_v1.py during the refactor branch's Faza 3 (tab-by-tab
backend/UI split, 2026-08-23) -- unlike the Benchmark tab's extraction, these functions
were never specific to one tab in the first place: list_pietra()/list_source_filenames()/
format_bytes()/format_duration()/digit_count_floor() etc. are called from the "Prime
numbers" tab (primeatlas/primes_tab.py), the Constellations tab, the Generation tab's
quick-gen panel, and the Goldbach research tab, all still living directly in
prime_atlas_v1.py. Moving this whole layer out on its own -- rather than only the parts
the Primes tab itself needs -- avoids re-deriving which pieces are "primes-tab-only" vs.
shared (see primes_tab.py's own docstring for how that question came up during this same
pass) and gives every future tab extraction one obvious place to import this layer back
from, exactly like primeatlas/benchmark.py's read_benchmark_log() is already imported
back into prime_atlas_v1.py for its own totals-column use.

Pure logic (no tkinter dependency) -- exercisable/unit-tested without a display, same
convention as every other module in this package except settings_tab.py/benchmark_tab.py/
primes_tab.py/widgets.py (see this package's __init__.py's own docstring).
"""
import bisect
import json
import math
import os
import re

import prime_sieve_v1
import window_sharding

LOW_FLOOR_CUTOFF = 7  # duplicated from prime_sieve_v3.py/v4.py's own LOW_FLOOR_CUTOFF (see
                      # that constant's docstring for the full rationale: floors 0..6 are
                      # each narrower than window_m's minimum, 10,000,000, so they always
                      # get exactly ONE window file rather than window_m-sized chunks). This
                      # Windows-native module deliberately never imports prime_sieve_v3/v4
                      # (they ctypes-load a Linux .so -- see find_continuation_target_idx's
                      # own docstring, still in prime_atlas_v1.py, for why), so the value is
                      # kept in sync by hand here. Used by update_pietro_totals_cache() to
                      # decide when its own mtime-based staleness check can't be trusted
                      # (see that function's LOW-FLOOR EXCEPTION docstring paragraph). Also
                      # re-imported back into prime_atlas_v1.py for its OWN
                      # _floor_window_count()'s use (a Generation-tab quick-gen helper).


def list_pietra(portal_folder):
    """Returns sorted base_exponent ints for every 10p{N} folder found directly under
    portal_folder (regardless of whether it has source_primes/ or constellations/
    populated yet)."""
    if not os.path.isdir(portal_folder):
        return []
    result = []
    for name in os.listdir(portal_folder):
        if name.startswith("10p") and name[3:].isdigit():
            if os.path.isdir(os.path.join(portal_folder, name)):
                result.append(int(name[3:]))
    return sorted(result)


def _is_prime_window_name(name):
    return name.startswith("PRIME_WINDOW_") and name.endswith(".bin")


def list_source_files(portal_folder, base_exponent):
    """Returns a list of (filename, full_path, header_dict) for every PRIME_WINDOW_*.bin
    under 10p{base_exponent}/source_primes/ (sharded into shard_NNNNN subfolders -- see
    window_sharding.py, task #405 -- so this walks those via list_sharded_files() rather
    than a flat os.listdir()), sorted into ascending window order (by the base prime in
    each file's header -- robust to filename shorthand like "10M" vs "0", unlike trying
    to re-parse format_offset()'s abbreviation back into a number). Files that fail to
    parse (corrupt/truncated) are still listed, with header=None, rather than silently
    dropped -- a browsing tool should surface problems, not hide them."""
    source_dir = os.path.join(portal_folder, f"10p{base_exponent}", "source_primes")
    entries = []
    for name, path in window_sharding.list_sharded_files(source_dir, predicate=_is_prime_window_name):
        try:
            header = prime_sieve_v1.read_prime_window_header(path)
        except Exception:
            header = None
        entries.append((name, path, header))

    def sort_key(entry):
        _, _, header = entry
        if header is None or header.get("base_prime") is None:
            return (1, 0, entry[0])
        return (0, header["base_prime"], entry[0])

    entries.sort(key=sort_key)
    return entries


_OFFSET_FROM_NAME_RE = re.compile(r"_off_(\d+)(M|k)?\.bin$")


def _offset_from_filename(name):
    """Cheap, I/O-free sort key: reconstructs the numeric offset directly from the
    filename's "_off_{N}[M|k]" suffix instead of opening the file to read its header.
    Safe for THIS project specifically because window_m (orchestrator_v1.WINDOW_M) is
    always a multiple of 1_000_000 -- format_offset() therefore always emits either the
    literal "0" or an exact "{N}M" form for every file this scanner actually writes, never
    the fractional/rounded "k" fallback it has for arbitrary (non-window-aligned) inputs.
    Returns None if a filename doesn't match (corrupt/foreign file) -- callers should sort
    those to the end rather than guessing at a position."""
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


def list_source_filenames(portal_folder, base_exponent):
    """Cheap listing of every PRIME_WINDOW_*.bin under 10p{base_exponent}/source_primes/
    (sharded into shard_NNNNN subfolders -- see window_sharding.py, task #405): a cheap
    listdir per shard subfolder + a regex per name, NO file opens. Sorted ascending by
    the offset parsed from the filename (see _offset_from_filename) -- a floor can hold
    thousands of windows (10p15 alone is past 2,600+ and still growing, 10p25 past
    500,000 -- see window_sharding.py's own docstring on why this can no longer be a
    single flat directory at all), and list_source_files()'s per-file header read is
    exactly what made expanding a heavily-populated floor node freeze the GUI. Returns
    [(name, path), ...]; headers are read separately, only for whichever page is
    actually being displayed (see read_source_file_headers())."""
    source_dir = os.path.join(portal_folder, f"10p{base_exponent}", "source_primes")
    entries = [(_offset_from_filename(name), name, path)
               for name, path in window_sharding.list_sharded_files(source_dir, predicate=_is_prime_window_name)]
    entries.sort(key=lambda e: (e[0] is None, e[0], e[1]))
    return [(name, path) for _offset, name, path in entries]


def read_source_file_headers(entries):
    """Reads headers for a (small, page-sized) list of (name, path) tuples -- the actual
    disk I/O, deliberately kept separate from list_source_filenames() so it only ever runs
    on however many files are visible on ONE page, never the whole floor. Returns
    [(name, path, header_or_None), ...] in the same order given."""
    result = []
    for name, path in entries:
        try:
            header = prime_sieve_v1.read_prime_window_header(path)
        except Exception:
            header = None
        result.append((name, path, header))
    return result


TOTALS_CACHE_FILENAME = ".portal_totals_cache.json"


def _totals_cache_path(portal_folder):
    return os.path.join(portal_folder, TOTALS_CACHE_FILENAME)


def load_totals_cache(portal_folder):
    """Returns the persisted {"10p{N}": {"files": {filename: count, ...}, "total": T,
    "file_count": C}, ...} cache, or {} if it doesn't exist yet or is corrupt (never raises --
    a missing/bad cache just means the next update rebuilds it, same as no cache at all)."""
    path = _totals_cache_path(portal_folder)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_totals_cache(portal_folder, cache):
    """Atomic write (temp file + os.replace()), same pattern as orchestrator_v1.py's
    _ensure_benchmark_log_schema() -- this file can get large (one entry per source window,
    e.g. 15000+ for a heavily-populated floor), so a half-written file from an interrupted
    save must never be what a later load sees."""
    path = _totals_cache_path(portal_folder)
    tmp_path = f"{path}.tmp{os.getpid()}"
    try:
        os.makedirs(portal_folder, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        os.replace(tmp_path, path)
    except OSError:
        pass  # best-effort -- a failed cache save just means the next visit re-scans


def update_pietro_totals_cache(portal_folder, base_exponent, cache):
    """Computes (and caches) the TOTAL prime count across every source window file for one
    floor -- the file list on its own only shows each file's OWN count, never a sum, so
    this fills in the floor row's total. Reading every file's header for a
    heavily-populated floor is NOT cheap on this project's actual storage (~78s for one
    floor's 15,101 files, ~5ms/file -- per-file open() latency on the underlying mount,
    not the tiny header read itself) -- exactly why list_source_filenames()/
    read_source_file_headers() were already split apart for the paginated file list (see
    those functions' docstrings). This
    function makes repeat visits cheap: `cache` maps floor -> {filename: count} from the
    LAST computation, and only filenames not already in that map get their header re-read --
    files removed from disk since the last run are dropped from the map (no stale counts
    lingering forever). A floor visited for the first time still pays the full one-time
    scan cost -- callers should run this off the GUI thread (see PortalApp's background
    totals worker) so that cost is never a frozen window.

    Returns (total, file_count, newly_read_count, total_bytes) -- newly_read_count lets a
    caller report "read 42 new files" instead of re-summarizing the whole floor every
    time, useful for a status message on the (usual, fast) incremental case. total_bytes
    is the floor's on-disk footprint (sum of every source window file's size) -- tracked
    alongside count/mtime per file so it's free to report without any extra I/O beyond
    what this function was already doing (the same os.stat() call used for the mtime
    staleness check below also returns st_size).

    STALENESS NOTE: each cached entry also stores the file's mtime at the time its header
    was read, and a file gets RE-read (not just skipped because its name is already cached)
    if the current on-disk mtime no longer matches. This matters because filenames here are
    fully deterministic from floor+offset (see prime_sieve_*.py's write_prime_window path),
    NOT content-addressed -- a low floor (see LOW_FLOOR_CUTOFF in prime_sieve_v3.py/v4.py)
    always writes to the exact same single filename every time it's regenerated, so an
    in-place rewrite (e.g. redoing a floor after a bugfix, or after storage was reset and
    regenerated) previously kept serving the FIRST-ever cached count forever -- the cache
    only ever checked "have I seen this name before", never "has this name's content
    changed". Entries from before this check existed are plain ints (old schema) rather than
    {"count", "mtime"} dicts; any non-dict entry is treated as unconditionally stale so it
    gets re-read (and migrated to the new shape) the first time this runs against an old
    cache file, rather than silently trusting a count with no known mtime.

    LOW-FLOOR EXCEPTION: mtime alone turned out to be unreliable in practice for floors
    below LOW_FLOOR_CUTOFF -- this project's storage drive is FUSE/WSL-mounted (see the
    known git-on-that-drive unlink/rename quirk elsewhere in this codebase's history), and
    the Windows-side os.path.getmtime() this function relies on can keep reporting a stale
    cached stat for a file just rewritten from the WSL side, for longer than this app's
    Refresh-then-recompute cycle. A low floor never has more than ONE file (its whole width
    is always < window_m -- see LOW_FLOOR_CUTOFF's own rationale), so the caching this
    mtime check exists for barely matters there anyway: unconditionally re-reading a low
    floor's single file every call costs one extra ~5ms open, not the "78s across 15,101
    files" cost this whole cache exists to avoid for a heavily-populated NORMAL floor."""
    key = f"10p{base_exponent}"
    entry = cache.setdefault(key, {"files": {}})
    cached_files = entry.setdefault("files", {})

    filenames = list_source_filenames(portal_folder, base_exponent)
    current_names = {name for name, _path in filenames}

    for stale_name in list(cached_files.keys()):
        if stale_name not in current_names:
            del cached_files[stale_name]

    always_refresh = base_exponent < LOW_FLOOR_CUTOFF
    to_read = []
    stats = {}
    for name, path in filenames:
        try:
            st = os.stat(path)
            stats[name] = (st.st_mtime, st.st_size)
        except OSError:
            stats[name] = (None, 0)
        cached = cached_files.get(name)
        mtime, _size = stats[name]
        if always_refresh or not isinstance(cached, dict) or cached.get("mtime") != mtime:
            to_read.append((name, path))

    if to_read:
        for name, path, header in read_source_file_headers(to_read):
            mtime, size = stats[name]
            cached_files[name] = {
                "count": header["count"] if header is not None else 0,
                "mtime": mtime,
                "size": size,
            }

    # Backfill "size" for entries that were already up to date (mtime matched, so skipped
    # above) but predate this field being tracked -- keeps total_bytes accurate without
    # forcing a full header re-read just to learn a file's size, since the size was
    # already sitting in `stats` from the os.stat() call above regardless.
    for name, _path in filenames:
        entry_file = cached_files.get(name)
        if isinstance(entry_file, dict) and "size" not in entry_file:
            entry_file["size"] = stats[name][1]

    total = sum(v["count"] for v in cached_files.values())
    total_bytes = sum(v.get("size", 0) for v in cached_files.values())
    entry["total"] = total
    entry["file_count"] = len(cached_files)
    entry["total_bytes"] = total_bytes
    return total, len(cached_files), len(to_read), total_bytes


GLOBAL_TOTAL_KEY = "_global"  # deliberately not "10p"-prefixed, so it can never collide
                              # with a real floor key (see list_pietra()'s "10p{N}" naming)


def _global_entry(cache):
    """Returns (creating if absent) the {"sum", "file_count", "bytes"} summary dict that
    tracks the persisted GLOBAL prime total across every floor -- see bump_pietro_total()/
    remove_pietro_total()/recompute_global_total() for who keeps it in sync and
    get_global_total() for who reads it back."""
    return cache.setdefault(GLOBAL_TOTAL_KEY, {"sum": 0, "file_count": 0, "bytes": 0})


def get_global_total(cache):
    """Returns (sum, file_count, bytes) from the persisted global summary, or None if it
    has never been computed yet (a cache from before this feature existed, or a brand-new
    portal folder) -- callers should treat None as "fall back to a real recompute", same
    as load_totals_cache()'s own "missing means rebuild" contract."""
    entry = cache.get(GLOBAL_TOTAL_KEY)
    if not isinstance(entry, dict):
        return None
    return entry.get("sum", 0), entry.get("file_count", 0), entry.get("bytes", 0)


def recompute_global_total(cache):
    """Rebuilds the persisted global summary FROM SCRATCH by summing every floor's own
    already-cached entry["total"]/["file_count"]/["total_bytes"] -- pure in-memory, no
    disk I/O of its own (the expensive part was whatever already populated those per-floor
    fields, e.g. a full update_pietro_totals_cache() pass over every floor). This is the
    one place that re-derives the global sum independently of the incremental bump/remove
    bookkeeping below, so it's what the manual "Zweryfikuj sumy" verify action (and a
    first-ever run against an old cache with no "_global" key yet) uses to self-heal any
    drift between the two. Floors with no "total" yet (never scanned, e.g. right after
    bump_pietro_total() created a bare entry with no prior real scan) contribute 0 rather
    than raising. Mutates `cache` in place and returns the new (sum, file_count, bytes)
    tuple for convenience."""
    total_sum = 0
    total_files = 0
    total_bytes = 0
    for key, entry in cache.items():
        if key == GLOBAL_TOTAL_KEY or not isinstance(entry, dict):
            continue
        total_sum += entry.get("total", 0) or 0
        total_files += entry.get("file_count", 0) or 0
        total_bytes += entry.get("total_bytes", 0) or 0
    cache[GLOBAL_TOTAL_KEY] = {"sum": total_sum, "file_count": total_files, "bytes": total_bytes}
    return total_sum, total_files, total_bytes


def bump_pietro_total(cache, base_exponent, delta_count, delta_file_count, delta_bytes):
    """Adjusts one floor's cached total (and the persisted global summary alongside it) by
    a DELTA, without touching the per-file "files" map at all and without any disk I/O of
    its own -- the incremental counterpart to update_pietro_totals_cache()'s full rescan,
    added so the three write paths Artur named (generation, storage merge, floor delete --
    see this module's own docstring for the feature this belongs to) can keep the
    persisted total accurate without ever re-reading a window file's header or re-listing
    a floor's directory.

    Deliberately does NOT add anything to entry["files"] (the per-filename mtime/count map
    update_pietro_totals_cache() uses for its own staleness check): the caller here only
    knows an aggregate delta (e.g. benchmark_log.csv's total_primes/windows_written/
    bytes_written for one generation run, or another storage's own already-cached floor
    total during a merge), not each individual new filename/header. This is an accepted
    trade-off, not an oversight -- entry["files"] simply stays exactly as accurate as it
    was before the bump (it under-represents on-disk reality until the next real scan),
    while entry["total"]/["file_count"]/["total_bytes"] (what every display actually reads)
    stay correct immediately. The next full rescan (manual "Zweryfikuj sumy", or the first
    time a floor is opened after this cache predates that feature) re-derives "files" from
    the real directory listing regardless, the same as it always has, so this never leaves
    a permanent inconsistency -- only a temporary one between bumps and the next verify.

    A floor with no prior entry at all (e.g. its very first-ever generation run, before
    anyone has opened this floor in the Primes tab even once) gets a bare
    {"total": 0, "file_count": 0, "total_bytes": 0, "files": {}} entry created here first,
    same shape update_pietro_totals_cache() would have created, so a later real rescan
    finds the shape it expects."""
    key = f"10p{base_exponent}"
    entry = cache.setdefault(key, {"files": {}})
    entry["total"] = entry.get("total", 0) + delta_count
    entry["file_count"] = entry.get("file_count", 0) + delta_file_count
    entry["total_bytes"] = entry.get("total_bytes", 0) + delta_bytes

    global_entry = _global_entry(cache)
    global_entry["sum"] += delta_count
    global_entry["file_count"] += delta_file_count
    global_entry["bytes"] += delta_bytes


def remove_pietro_total(cache, base_exponent):
    """The floor-deletion counterpart to bump_pietro_total(): drops base_exponent's entry
    from `cache` entirely (a deleted floor has no on-disk files left to stay stale about)
    and subtracts whatever total it last held from the persisted global summary. Returns
    the removed entry's (total, file_count, total_bytes) for a caller that wants to log/
    display what was subtracted, or None if this floor had no cache entry at all (nothing
    to subtract -- e.g. a floor that was deleted before it was ever opened/generated into
    in a way that reached this cache)."""
    key = f"10p{base_exponent}"
    entry = cache.pop(key, None)
    if not isinstance(entry, dict):
        return None
    total = entry.get("total", 0) or 0
    file_count = entry.get("file_count", 0) or 0
    total_bytes = entry.get("total_bytes", 0) or 0

    global_entry = _global_entry(cache)
    global_entry["sum"] -= total
    global_entry["file_count"] -= file_count
    global_entry["bytes"] -= total_bytes
    return total, file_count, total_bytes


def format_big_int(n, head=12, tail=6):
    """Shortens a huge integer for display: keeps the first `head` and last `tail` digits,
    elides the middle with "...". This is just for compact display in a tree/list widget;
    full-precision values are always used for any actual computation."""
    if n is None:
        return "-"
    s = str(n)
    if len(s) <= head + tail + 3:
        return s
    return f"{s[:head]}...{s[-tail:]} ({len(s)} digits)"


def format_duration(seconds):
    """H h M m S s, dropping leading zero units. Duplicated (not imported) from
    orchestrator_v3.py's own format_duration() -- this GUI module deliberately doesn't
    import the WSL-only orchestrator scripts directly (see the Generation tab's own note,
    still in prime_atlas_v1.py, on why orchestrator_loop_v2 is launched as a subprocess
    instead), so small pure-Python helpers like this one get a local copy rather than a
    cross-module dependency."""
    if seconds is None:
        return "?"
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def format_bytes(n):
    """Plain binary-unit (B/KiB/MiB/GiB/TiB) byte count formatter, one decimal place
    (none for bytes), unit picked by magnitude -- same spirit as format_duration above
    (small, local, no need to pull in a dependency for something this short). None/
    negative input -> "?", matching format_duration's own None handling."""
    if n is None or n < 0:
        return "?"
    n = float(n)
    if n < 1024:
        return f"{n:.0f} B"
    for unit in ("KiB", "MiB", "GiB"):
        n /= 1024
        if n < 1024:
            return f"{n:.1f} {unit}"
    return f"{n / 1024:.1f} TiB"


def aggregate_write_seconds_by_pietro(rows):
    """Sums total_seconds per floor across every benchmark_log.csv row that ACTUALLY wrote
    files (write_files=="1"), skipping write_files=False count-only benchmark rows entirely
    -- otherwise a floor that was also re-benchmarked in count-only mode (same
    base_exponent/range, much faster since it skips disk I/O) would have its "how long did
    this floor really take to generate" figure polluted by runs that produced no files at
    all -- counting numbers without writing files needs to stay distinct from counting with
    writes. Rows predating the write_files
    column (blank -- see orchestrator_v3.py's BENCHMARK_FIELDNAMES comment) are skipped too,
    same as an unparseable row -- no way to know after the fact which mode they ran in.
    Returns {base_exponent: total_seconds}."""
    totals = {}
    for row in rows:
        if row.get("write_files") != "1":
            continue
        try:
            base_exponent = int(row.get("base_exponent", ""))
            seconds = float(row.get("total_seconds", ""))
        except (TypeError, ValueError):
            continue
        if math.isnan(seconds):
            continue
        totals[base_exponent] = totals.get(base_exponent, 0.0) + seconds
    return totals


def digit_count_floor(number):
    """A window at floor N holds numbers in [10^N, ...), which all have N+1 digits (in
    the overwhelming common case -- windows practically never straddle a power-of-10
    boundary). So the digit count of `number` directly tells us which floor to look in
    first, without having to scan every floor folder."""
    return len(str(number)) - 1


def _read_base_prime(path):
    """Just the one field find_prime_in_floor's binary search actually needs -- still a
    full header read (there's no cheaper way to get a real base_prime without opening the
    file), but callers control exactly how many of these happen, unlike the old
    list_source_files()-based approach which read every window's header unconditionally."""
    try:
        header = prime_sieve_v1.read_prime_window_header(path)
    except Exception:
        return None
    return header.get("base_prime") if header else None


def find_prime_in_floor(portal_folder, base_exponent, number):
    """Searches PGS2 source windows under 10p{base_exponent} for `number`.

    Windows are non-overlapping and written in strictly increasing target_idx order, so
    their base_primes are guaranteed ascending too -- each window's base_prime falls
    somewhere inside that window's own [start, start+window_m) range, and those ranges
    never overlap between windows. That means a binary search for the rightmost window
    with base_prime <= number identifies the ONE window whose numeric range could contain
    `number` (plus its immediate neighbor, as a constant-cost safety net against an
    off-by-one boundary edge case) -- and, critically, the search only needs to read a
    header for the O(log N) windows it actually PROBES, not every window in the floor.

    This replaced an earlier version that called list_source_files() (reads every
    window's header up front) before bisecting in memory -- fine at hundreds of windows,
    but 10p15 alone has passed 14,000: reading every header on every search made the
    feature unusably slow/freeze-prone at that scale (~14,000 file opens vs. ~14 for a
    14,000-window binary search). Listing filenames is still cheap (list_source_filenames,
    no I/O) -- only actual header reads are now bounded.

    A handful of unreadable headers along the search path (corrupt/truncated files --
    should be rare) are tolerated by trying the next index once rather than aborting the
    whole search; if that neighbor is ALSO unreadable, the search conservatively narrows
    away from that pivot instead of guessing.

    Returns a dict {name, path, primes, index} on success (index = position of `number`
    within that file's decoded, sorted prime list), or None if not found.
    """
    windows = list_source_filenames(portal_folder, base_exponent)  # cheap: no file I/O
    if not windows:
        return None
    n = len(windows)

    def _check(idx):
        name, path = windows[idx]
        try:
            primes = prime_sieve_v1.read_prime_window(path)
        except Exception:
            return None
        pos = bisect.bisect_left(primes, number)
        if pos < len(primes) and primes[pos] == number:
            return {"name": name, "path": path, "primes": primes, "index": pos}
        return None

    lo, hi = 0, n - 1
    best = -1  # rightmost index seen so far with base_prime <= number
    while lo <= hi:
        mid = (lo + hi) // 2
        bp = _read_base_prime(windows[mid][1])
        if bp is None and mid + 1 <= hi:
            mid += 1
            bp = _read_base_prime(windows[mid][1])
        if bp is None:
            hi = mid - 1
            continue
        if bp <= number:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1

    candidate_indices = []
    if best >= 0:
        candidate_indices.append(best)
    if best + 1 < n:
        candidate_indices.append(best + 1)

    for idx in candidate_indices:
        result = _check(idx)
        if result is not None:
            return result
    return None
