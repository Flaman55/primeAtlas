"""
window_sharding.py -- restores the ~5000-files-per-subfolder sharding scheme the
original orchestrator (v1, pre-PrimeAtlas) used for window storage, dropped when
PrimeAtlas's current flat-per-floor layout (every PRIME_WINDOW_*.bin directly under
10p{N}/source_primes/) was introduced.

Why this exists (task #405): a single flat source_primes/ folder degrades badly at
scale -- floor 25 alone reached 542,001 files in one directory. Artur's field-observed
crash: constellation_finder_v1.py's WSL process died silently mid-scan on floor 25
(200000/542001 windows in, "Proces wsl.exe zakonczyl sie bez zapisania kodu wyjscia" --
no Python traceback, the WSL process itself died), with generation (writing files) at
that same scale confirmed fine -- only large-scale directory listing/lookup was
affected. Root cause hypothesis (Artur, confirmed as the fix direction): WSL/Windows
filesystem interop (9P protocol crossing the H:\\ mount) degrades badly on directory
listing/lookup at 100k+ entries in one folder, plausibly timing out or exhausting a
resource in a way that kills the WSL process without a clean Python exception.

Deliberately ONE small, shared, pure-Python module (plain int arithmetic + os.path
only -- no ctypes/mmap/multiprocessing) rather than duplicated per file, unlike this
codebase's usual convention for small helpers (e.g. storage.py's own format_duration()
docstring on why THAT one is a local copy per module). The difference: format_duration
is self-contained pure formatting with no cross-file contract. The shard boundary here
is a hard CONTRACT between every writer (prime_sieve_v1.py/v3.py/v4.py/v4_1.py/
prime_sieve_primesieve.py) and every reader (primeatlas/storage.py,
constellation/constellation_finder_v1.py, primeatlas/delete_manager.py,
primeatlas/full_backup.py, primeatlas/manifest.py, primeatlas/restore_job.py,
primeatlas/storage_integrate.py, primeatlas/settings_tab.py) -- a mismatched copy in
just one of those files would silently misplace or "lose" files. Lives in prime_sieve/
specifically so both sides can import it identically: every WSL engine script in this
same folder can bare `import window_sharding` (same directory), and every Windows-side
primeatlas/*.py module can do the same via prime_atlas_v1.py's existing
sys.path.insert(0, ".../prime_sieve") (the same mechanism already used there for
prime_sieve_v1 itself), and constellation_finder_v1.py already does its own
sys.path.insert(0, "../prime_sieve") to reach prime_sieve_v1, so this rides along for
free.

Backward compatibility with pre-existing UNSHARDED floors is explicitly NOT handled
here -- Artur confirmed (2026-08-24) that migrating already-generated floors to this
layout is a separate, fully external script, outside primeAtlas entirely. Every reader
in this codebase can therefore assume ALL floors are sharded going forward; there is no
dual-layout-support code path.

Scope: ONLY source_primes/ windows (the ones that reach hundreds of thousands of files
per floor at scale). Constellation HIT files
(10p{N}/constellations/k{K}/variant{ID}/HITS_....bin) are NOT windowed one-per-file --
each (k, variant) pair accumulates into a single cumulative file via
prime_sieve_v1.append_prime_window() -- so they never hit this problem and are
untouched by this module.
"""
import os

SHARD_SIZE = 5000


def shard_name(window_index):
    """window_index -- 0-based position of a window within a floor, in generation
    order (== offset // window_m for the fixed-width, evenly-spaced windows every
    engine here produces -- see shard_index_for_offset() below). Returns the subfolder
    name, e.g. "shard_00000" for window indices 0-4999, "shard_00001" for 5000-9999,
    and so on -- matching the old pre-PrimeAtlas orchestrator's own naming scheme."""
    if window_index < 0:
        raise ValueError(f"window_index must be >= 0, got {window_index}")
    return f"shard_{window_index // SHARD_SIZE:05d}"


def shard_index_for_offset(offset, window_m):
    """Every engine in this codebase writes fixed-width, evenly-spaced windows (see
    each write call site's own "offset = distance - BASE" / target_idx*window_m math)
    -- offset // window_m is therefore exactly that window's 0-based generation-order
    index, without needing to thread a separate counter through every call site.
    Floors below LOW_FLOOR_CUTOFF always write their single window at offset=0,
    correctly landing in shard index 0 regardless of window_m."""
    return offset // window_m


def shard_dir(parent_dir, window_index):
    """parent_dir is a floor's source_primes/ folder -- returns the shard SUBfolder
    path for window_index (not yet created; callers os.makedirs(..., exist_ok=True)
    when actually about to write into it)."""
    return os.path.join(parent_dir, shard_name(window_index))


def iter_shard_dirs(parent_dir):
    """Yields (shard_name, shard_path) for every existing shard_NNNNN subfolder
    directly under parent_dir, in ascending shard order -- the one, cheap
    os.listdir(parent_dir) a reader needs (parent_dir itself never holds more than a
    few thousand shard subfolders even at floor 25's scale: 542,001 windows / 5000 ==
    ~109 shard folders) before listing each shard's own (<=SHARD_SIZE) files."""
    if not os.path.isdir(parent_dir):
        return
    for name in sorted(os.listdir(parent_dir)):
        if name.startswith("shard_"):
            path = os.path.join(parent_dir, name)
            if os.path.isdir(path):
                yield name, path


def list_sharded_files(parent_dir, predicate=None):
    """Returns [(filename, full_path), ...] for every file in every shard_NNNNN
    subfolder under parent_dir (see iter_shard_dirs() above), in shard order then name
    order within each shard. `predicate(filename) -> bool` optionally filters which
    filenames are included (default: every filename). This is the ONE listing
    primitive every reader of a sharded source_primes/ folder in this codebase should
    use -- never a bare os.listdir(parent_dir) directly, which would only ever see
    shard_NNNNN subfolder names, not the actual window files inside them."""
    results = []
    for _shard_name, shard_path in iter_shard_dirs(parent_dir):
        for name in sorted(os.listdir(shard_path)):
            if predicate is None or predicate(name):
                results.append((name, os.path.join(shard_path, name)))
    return results


def shard_dir_for_restored_offset(parent_dir, offset, assumed_window_m=10_000_000):
    """For placing a window file INTO a sharded folder when its original window_m isn't
    known at the call site (e.g. cross-storage merges in storage_integrate.py, or
    restoring from a full_backup.py archive) -- buckets by `assumed_window_m` (default:
    10,000,000, the smallest window_m used anywhere in this codebase -- see
    storage.py's own LOW_FLOOR_CUTOFF docstring), which still guarantees at most
    SHARD_SIZE files per shard regardless of the file's real original window_m (never
    smaller than this default, project-wide). `offset` is the value recovered from the
    filename itself (see storage.py's _offset_from_filename) -- None (unparseable
    filename) falls back to shard index 0 rather than raising."""
    window_index = 0 if offset is None else shard_index_for_offset(offset, assumed_window_m)
    return shard_dir(parent_dir, window_index)


def count_sharded_files(parent_dir, predicate=None):
    """Same enumeration as list_sharded_files(), but returns just the count -- callers
    that only need "how many" (e.g. a floor-delete confirmation dialog) skip building
    the full (name, path) list."""
    total = 0
    for _shard_name, shard_path in iter_shard_dirs(parent_dir):
        for name in os.listdir(shard_path):
            if predicate is None or predicate(name):
                total += 1
    return total
