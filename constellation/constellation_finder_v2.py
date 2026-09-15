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
# CHECKPOINT.txt, covering every k -- as of v2, a set of already-processed window
# RANGES (see this file's own "v2 -- gap-aware checkpoint" header section below), not
# just a single last-processed-filename pointer.
#
# Per-(k,variant) hit counts are available cheaply via
# read_prime_window_header(hit_path)['count'] (no full decode), which is enough to build
# an aggregate view -- e.g. for an HTML portal generator operating on
# pattern_catalog_v1.py's record_digits field -- without needing a separate report format
# maintained here.
#
# CLI: running with no floor argument auto-detects and processes every floor under the
# portal that has at least one source window (list_pietra_with_data()); an explicit
# argument restricts the run to just that one floor.
#
# Peek-ahead threshold: uses the NEXT file's header base_prime + MAX_SPAN as the peek
# threshold (via read_prime_window_head), rather than reconstructing each window's
# nominal boundary independently of its content. The two differ by at most the gap from
# a window's nominal start to its first actual prime -- a handful of units, well within
# MAX_SPAN's margin (84 at the widest catalog entry, k=21) -- so this is safe and simpler.
#
# FLOOR-BOUNDARY crossings (added 2026-08-18, at Artur's request): the peek-ahead above
# only ever looks at the next window WITHIN THE SAME FLOOR -- the floor's own LAST window
# has no such next window to peek into, so a pattern whose base sits near the very top of
# one floor with its tail spilling into the next floor's numbers was never checked at all.
# Every catalog pattern's offsets are non-negative, so a boundary-straddling
# constellation's base is always on the LOWER of the two floors -- see
# check_floor_boundary()'s own docstring for how this is closed, without touching the
# per-window CHECKPOINT.txt above at all: a separate, tiny BOUNDARY_CHECKED.txt marker per
# floor, and a clear informational print when the check can't be completed yet because the
# next floor has no data.
#
# CHECKPOINT.txt regression safety (added 2026-08-19, at Artur's request): CHECKPOINT.txt
# and BOUNDARY_CHECKED.txt are both plain files with no merge logic of their own -- if a
# floor's constellations/ folder is physically copied in from another storage (magazyn)
# that had independently scanned some of the same windows, or CHECKPOINT.txt simply names
# a window no longer present among the current ones (the existing "ignoring checkpoint,
# processing from the start" fallback below), some already-processed windows get
# RE-scanned. Re-scanning is normally harmless on its own, but re-appending the SAME hit
# values a second time used to crash (append_prime_window()'s own strict-increase
# assertion) the instant a re-scanned window turned up a real hit. See
# _append_hits_deduped()'s own docstring and [[primeatlas_storage_merge_federation]] for
# the full story -- every append_hits() call in this file now goes through that wrapper,
# which silently drops already-known values instead of crashing, making re-scanning an
# already-covered window safe and effectively idempotent.
#
# v2 -- gap-aware checkpoint (added 2026-09-15, at Artur's request after a real field
# report: an unpredictable PC restart left two constellation_finder processes running
# for the same floor, and CHECKPOINT.txt -- v1's single "last_processed_file=" pointer,
# overwritten by whichever process wrote most recently -- ended up pointing at a window
# far BEHIND where the floor's own magazyn already had hits recorded from the other
# process. v1's own resume logic (process_floor()'s "everything after last_done" slice)
# has no way to represent "done, except for this earlier gap" -- it can only resume from
# ONE position, so after a regression like this it burns hours re-scanning a huge
# already-covered range instead of just closing the actual gap. Re-scanning itself was
# already safe (the dedup wrapper above), just wasteful.
#
# Fix: CHECKPOINT.txt now stores a set of DONE RANGES ("done_range=<first>|<last>" lines,
# one per contiguous run of already-processed windows in base_prime order) instead of a
# single pointer, via read_done_ranges()/write_done_ranges() below. process_floor() diffs
# the floor's current window list against the union of those ranges to build to_process,
# so a regressed/overlapping checkpoint only ever costs re-scanning the genuinely-missing
# windows, never the whole tail again. A `last_processed_file=` line is still written
# alongside the ranges (the highest-index window covered by any range) purely for
# backward compatibility with generation.py's own read_constellation_checkpoint() (GUI-
# side auto-retry "did we make progress" comparison) and v1's own read_checkpoint() --
# neither needs to know about ranges, both just want "how far has this floor gotten".
# An old, v1-only CHECKPOINT.txt (no done_range= lines at all) is read as a single range
# from the floor's very first window through last_processed_file -- exactly what v1
# itself would have assumed -- so upgrading a floor already in progress from v1 to v2
# loses no recorded progress.
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
    count -- printed at key checkpoints throughout process_floor() (added 2026-09-13,
    at Artur's explicit request after floor 25 kept killing the whole WSL process
    silently, no Python traceback, and Artur himself had already ruled out file
    corruption by hand-checking the source_primes/ files: this really does look like a
    pure scale/volume problem specific to this one floor -- by far the largest
    source_primes/ folder in any of his storages -- not a poisoned file).

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

    SHARDING (added 2026-08-27, task #405): source_primes/ is sharded into shard_NNNNN
    subfolders (see window_sharding.py) -- this is the exact function whose flat
    os.listdir() previously implicated a real crash: floor 25's 542,001-file flat
    directory made WSL's own process die silently mid-scan (no Python traceback) at
    200000/542001 windows in, root-caused to WSL/Windows filesystem interop degrading at
    100k+ entries in one directory. window_sharding.list_sharded_files() walks each
    shard subfolder (never more than SHARD_SIZE entries each) instead of listing
    source_dir directly.

    WINDOW_INDEX.tsv cache (added 2026-08-23, at Artur's request -- floor 25's 542k-file
    source_primes/ was making every run of this function, and therefore every run of
    process_floor()/list_pietra_with_data(), open and read the header of ALL 542k files
    just to learn their base_prime for sorting -- paid IN FULL on every single invocation
    regardless of how much of the floor CHECKPOINT.txt already covers, and paid TWICE per
    script run (once here, once more from list_pietra_with_data()'s old call into this
    same function just to test for non-emptiness). That's several hundred thousand
    individual file opens before a single window even gets matched against a pattern --
    easily long enough to look like a hang on a floor this size, even though the actual
    per-window streaming loop in process_floor() was always incremental and checkpointed.
    Source windows are written once by the generator and never rewritten in place (unlike
    hit files, which grow via append_prime_window()), so a filename's base_prime is safe
    to cache indefinitely once read: a repeat run only needs to read the header of
    filenames that are NEW since the last time this floor's index was written, dropping
    entries whose file no longer exists. This turns the per-run header-read cost from
    O(all files on the floor) into O(files added since last run) -- for a floor that's
    already fully scanned, that's typically zero."""
    t0 = time.time()
    source_dir = os.path.join(PORTAL_FOLDER, f"10p{base_exponent}", "source_primes")
    sharded_files = window_sharding.list_sharded_files(
        source_dir,
        predicate=lambda name: name.startswith("PRIME_WINDOW_") and name.endswith(".bin"))
    if not sharded_files:
        return []
    paths_by_name = dict(sharded_files)
    names_on_disk = sorted(paths_by_name.keys())
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
        print(f"[CONSTELLATIONS v2] DIAG: read {len(new_names):,} fresh header(s) "
              f"({len(names_on_disk) - len(new_names):,} served from WINDOW_INDEX.tsv "
              f"cache) in {time.time()-t1:.2f}s | {_proc_diag()}")

    entries = [(name, paths_by_name[name], index[name]) for name in names_on_disk]
    entries.sort(key=lambda e: (e[2] is None, e[2] if e[2] is not None else 0, e[0]))
    print(f"[CONSTELLATIONS v2] DIAG: list_source_windows(10^{base_exponent}) done in "
          f"{time.time()-t0:.2f}s total | {_proc_diag()}")
    return entries


def list_pietra_with_data():
    """Returns sorted base_exponent ints for every 10p{N} folder under PORTAL_FOLDER that
    actually has at least one PGS2 source window. Floor folders can exist as empty
    source_primes/constellations placeholders ahead of the scanner actually reaching
    them, so folder presence alone doesn't mean there's anything to process.

    Deliberately a cheap directory-listing existence check, NOT a call into
    list_source_windows() -- see that function's docstring on WINDOW_INDEX.tsv: this used
    to call list_source_windows() just to test non-emptiness, which for an
    already-fully-indexed floor is free, but for a floor never indexed yet (e.g. the very
    first run after a large floor like 10p25 first gets data) meant paying the full
    header-read-every-file cost a SECOND time on top of the one process_floor() itself
    needs -- effectively doubling floor 25's worst-case startup cost for no benefit.

    SHARDING (task #405): source_primes/ now only ever directly contains shard_NNNNN
    subfolders (see window_sharding.py) -- a bare os.listdir(source_dir) would only ever
    see those subfolder names, never an actual PRIME_WINDOW_*.bin file, so "has_window"
    is checked one level down, inside the FIRST existing shard subfolder only (any floor
    with data has a non-empty shard_00000) -- still a cheap, bounded listdir, not a full
    window_sharding.list_sharded_files() walk across every shard."""
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
    """Turns this floor's persisted done_ranges into an actual set of done window names,
    validated against `names` (the CURRENT base_prime-sorted window name list -- see
    list_source_windows()). A range whose boundary name is no longer among `names` is
    dropped with a warning, same fallback spirit as v1's own "ignoring checkpoint,
    processing from the start" -- a stale boundary name means that range can no longer be
    resolved to a position, so it's safer to let those windows be re-scanned (harmless,
    see _append_hits_deduped()) than to silently trust a boundary that no longer lines up
    with reality."""
    if not names:
        return set()
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
    """Atomic tmp-then-replace + fsync (same pattern as v1's own write_checkpoint(), for
    the same power-loss reason -- see that docstring), persisting the FULL set of
    already-processed windows as merged (first_name|last_name) ranges over `names` (the
    current base_prime-sorted window list) rather than a single pointer.

    `done_indices` -- every index into `names` that is done as of this write (i.e. the
    caller's own accumulated set, not just what changed since the last write) -- kept
    simple rather than a delta/patch scheme since a floor's own done-range list stays
    tiny in practice (processing is normally strictly in order, so it collapses to ONE
    range; the whole point of this format is staying correct, not necessarily minimal,
    on the rare occasion it doesn't).

    Still writes `last_processed_file=` (the name at the highest done index) alongside
    the ranges -- see read_checkpoint()'s own docstring for who still relies on that
    line."""
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
    """Returns {(k, variant_id): (last_value, count)} from this floor's own persistent
    last-value cache -- see _resolve_last_value()'s own docstring for the THE ACTUAL
    CRASH this exists to fix (confirmed via a real crash log, 2026-09-13): a fresh
    process_floor() call's in-memory last_value_cache starts EMPTY every single run, so
    the FIRST window in a run that has a hit for a given (k, variant_id) pattern used
    to trigger a FULL decode of that pattern's WHOLE accumulated hit file (via
    prime_sieve_v1.read_prime_window()) just to learn its own last stored value.
    Floor 25's k=2 (twin primes) hit file, after 342,001 already-processed windows of
    a very dense floor, is large enough that this one decode alone was enough to crash
    the whole WSL process -- exactly matching the observed symptom (zero checkpoint
    progress, died right after the "pattern matching done" DIAG line, before the
    per-window summary print).

    Returns {} if no cache file exists yet (matches _read_window_index()'s own
    "nothing cached yet" contract)."""
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

    Tries the ON-DISK persistent cache (disk_cache, see _read_last_values_disk_cache()'s
    own docstring for the crash this whole mechanism exists to avoid) FIRST, validated
    via a CHEAP header-only read (read_prime_window_header(), ~264 bytes regardless of
    the file's real size) against the file's ACTUAL current `count`: if they match, the
    cached last_value is trustworthy and the expensive decode below is skipped entirely.
    Only ever falls back to decoding when the disk cache has no entry for this pattern
    yet (including THE VERY FIRST TIME this cache is ever populated for a given floor --
    a real crash log, 2026-09-14, showed this exact bootstrap decode itself killing the
    WSL process on floor 25's k=2 hit file after 342,001 windows, BEFORE the cache ever
    got a chance to be written -- the disk cache alone cannot help the first time, only
    every relaunch AFTER a successful one), the hit file doesn't exist, or the counts
    DISAGREE (meaning the file was modified by something other than this same cache
    since it was last written -- e.g. a storage merge physically copying in a
    constellations/ folder from another magazyn, per [[primeatlas_storage_merge_
    federation]] -- so the cached value can no longer be trusted and must be
    rediscovered the safe way). This count-based validation is what makes the cache
    safe to trust blindly on the fast path while never risking silently corrupting a
    hit file's gap-encoding on a stale read (see append_prime_window()'s own docstring
    on why an incorrect known_last_value would corrupt the file, not just misbehave).

    Uses prime_sieve_v1.read_prime_window_last_value() for the fallback, NOT plain
    read_prime_window() -- see that function's own docstring: decoding a
    several-hundred-thousand-window floor's dense pattern into a full Python list of
    millions of big integers can itself cost several times the file's raw byte size in
    RAM, which is exactly what crashed the real WSL process here. The lean version
    walks the same gap stream (same O(count) time -- there's no way around that for a
    sequentially gap-encoded format) but keeps only the running last value, never a
    growing list."""
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
    # THE expensive path this whole cache exists to make rare -- see this function's
    # own docstring for the real crash it used to cause on floor 25's k=2 hit file. Kept
    # visible (not silent) whenever it actually triggers, with size + timing, printed
    # (and fsynced) BEFORE the decode itself -- precisely so a crash DURING this decode
    # still leaves a clear "this is where it died, and this file's size is why" trail,
    # instead of the silence a real crash log showed here before this print existed.
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

    Why this exists (added 2026-08-18, at Artur's request, closing the gap noted in
    [[primeatlas_storage_merge_federation]]): CHECKPOINT.txt is a single plain file with
    no merge logic of its own -- if a floor's constellations/ folder gets physically
    copied in from another storage (magazyn) that had independently scanned some of the
    SAME windows, or if CHECKPOINT.txt simply names a window no longer present among the
    CURRENT windows (process_floor()'s own existing fallback: "ignoring checkpoint,
    processing from the start"), some already-processed windows get RE-scanned. Those
    windows produce the exact same hit values as before (matching is deterministic), and
    without this filter, re-appending them would hit append_prime_window()'s own
    ValueError the instant a re-scanned window turns up a real hit -- a hard crash, not a
    silent problem, but still one that stops constellation scanning for that floor dead
    until someone notices and manually intervenes.

    This makes re-scanning an already-covered window SAFE and effectively idempotent
    instead: already-known values are silently dropped (logged by the caller, not here,
    since only the caller knows whether this is worth mentioning at the per-window
    volume process_floor()'s own loop runs at), genuinely NEW values (there can be none
    for an exact re-scan, but this stays correct even if some future change makes that
    possible) still get appended normally. Deliberately implemented here, not as a
    change to append_prime_window() itself -- that function's own strict assertion stays
    intact as a genuine invariant check for any other, non-reprocessing caller; this
    wrapper is specific to the one scenario constellation_finder_v1.py's own checkpoint
    can legitimately regress in.

    `last_value_cache`, if given, is a dict {(k, variant_id): (last_value, count)}
    CALLERS own and mutate across a whole run (see process_floor()'s own
    last_value_cache) -- same performance rationale as append_hits()'s own
    known_last_value parameter (avoids re-decoding the whole hit file on every single
    call WITHIN one run).

    `disk_cache`, if given, is the SAME shaped dict but PERSISTED across separate runs
    (see _read_last_values_disk_cache()'s own docstring for the real crash this exists
    to fix: floor 25's k=2 hit file, after 342,001 windows of a dense floor, was large
    enough that decoding it from scratch on every FRESH process -- which last_value_
    cache alone can never avoid, since it starts empty every run -- crashed the whole
    WSL process). Used via _resolve_last_value() only when this (k, variant_id) isn't
    already in last_value_cache (i.e. at most once per pattern per run).

    Falls back to a full decode from disk (today's ORIGINAL, correct-but-expensive
    behavior) when neither cache has a valid entry -- see _resolve_last_value()'s own
    docstring for exactly when that happens.

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

    Computes on LOCAL offsets relative to min(candidates) -- not absolute values -- since
    numpy int64 cannot hold floor >= 19 magnitudes (see file header on why this matters
    at all only for floor >= 19; still correct and cheap either way at shallower depths).
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
    element) actually belongs to (added 2026-08-18, at Artur's explicit request: "jeśli
    choć jeden element jest z piętra niżej a reszta wyżej, to wciąż powinna być widoczna
    jak aktualne piętro").

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
    fully close off this floor's own constellation search (Artur's own answer to how this
    case should be handled, in preference to a heavier automatic-retry mechanism).
    Automatically re-checked (and closed) the next time constellation_finder runs on this
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
        # A one-off call, not part of process_floor()'s own hot per-window loop -- still
        # threads `disk_cache` through when the caller has one (process_floor() always
        # does), so this stays consistent with the persistent cache and doesn't force
        # an unnecessary full decode next run. Deduped (not a plain append_hits() call)
        # for the same reason as process_floor()'s own loop -- see
        # _append_hits_deduped()'s own docstring.
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
    floor, in order, matching every catalog pattern (k>=2) and appending new hits. Also
    checks (once, then never again -- see check_floor_boundary()'s own docstring) whether
    a pattern spans this floor's own upper boundary into 10p{base_exponent+1}.

    `max_windows` (added 2026-09-13, at Artur's explicit request after floor 25's WSL
    process kept dying mid-run at 545,000 source windows -- see WslLoggedRunner's own
    docstring on the exact failure shape, "Proces wsl.exe zakonczyl sie bez zapisania
    kodu wyjscia", and generation_tab.py's own _maybe_auto_retry_constellation()/
    _maybe_continue_constellation_batch() for the Windows-side half of this fix):
    caps how many windows a SINGLE call processes before returning, regardless of how
    many are actually pending. None (the historical default) processes everything in
    one call, same as before this parameter existed.

    Why this exists at all: a floor this size makes a single process_floor() call hold
    open hundreds of thousands of file handles (two per window: its own content plus a
    peek into the next one) and accumulate whatever OS-level state that costs over a
    single process's lifetime -- window_sharding.py's own docstring already documents
    WSL/Windows filesystem interop (crossing the 9P-based /mnt/ mount) degrading badly
    under sustained directory-listing load at 100k+ entries; the working hypothesis
    here is the same class of degradation, just triggered by sustained FILE-OPEN volume
    within one process instead. Capping the batch size bounds that per-process cost
    the same way window_sharding.SHARD_SIZE already bounds per-directory listing cost,
    letting the CALLER (generation_tab.py) relaunch a fresh, short-lived WSL process
    for each batch instead of one process trying to carry the whole floor. Returns the
    number of windows still remaining after this call (0 once the floor's own windows,
    as of when this call started, are all processed) -- the CLI's own __main__ block
    below turns this into the "BATCH DONE -- N window(s) still remain" marker line
    generation_tab.py's own _scan_const_chunk_for_batch_marker() parses to decide
    whether to chain another batch.

    Graceful stop (added 2026-09-14, Artur's own proposal after asking whether a manual
    Stop click resumes cleanly): checked once per window, at the very TOP of the loop
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

    names = [name for name, _, _ in windows]
    index_of = {name: i for i, name in enumerate(names)}
    done_names = resolve_done_names(base_exponent, names)
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
    # Machine-parseable counterpart to the human-readable line above, added 2026-09-14
    # so generation_tab.py's own _update_shared_progress_from_generation_chunk() can show
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

    print(f"[CONSTELLATIONS v2] DIAG: entering per-window loop, elapsed={time.time()-run_start:.2f}s "
          f"| {_proc_diag()}")

    # How often to print a heartbeat DIAG line and how often to print the lighter
    # per-window reading/summary lines below. Chosen small enough that a crash between
    # two heartbeats still narrows the death down to a tight window count, large
    # enough not to meaningfully slow down a 5000-window batch.
    HEARTBEAT_EVERY = 100
    # The first few windows of EVERY batch get much finer-grained diagnostics (one
    # print + explicit fsync after EACH sub-step: read, peek, match, checkpoint) --
    # added 2026-09-13 after a real crash log showed the process dying between the
    # "reading window 1" line and its own per-window SUMMARY line, with nothing in
    # between to say which of those sub-steps (the read itself, the next-window peek,
    # pattern matching, or the checkpoint write) it actually died inside. Not applied
    # to every window in the batch -- fsync-ing after every sub-step of all 5000
    # windows would add real overhead -- but the observed crash has been on window 1
    # of a batch both times so far, so the first few windows are exactly where this
    # detail earns its cost; _diag_step() below is the shared helper both this
    # detailed path and the lighter one call into.
    DETAILED_DIAG_WINDOWS = 5

    def _diag_step(label, detailed):
        line = f"[CONSTELLATIONS v2] DIAG: {label} | {_proc_diag()}"
        if detailed:
            _diag_fsync_print(line)  # see HEARTBEAT_EVERY's own comment above, and
                                      # _diag_fsync_print()'s own docstring, on why
                                      # fsync matters here
        else:
            print(line)

    for i, (name, path, _base_prime) in enumerate(to_process):
        # Checked at the very TOP of the loop, before any work on window i starts -- see
        # STOP_REQUEST_FILENAME's own module-level comment on why this matters at a
        # window BOUNDARY specifically: append_prime_window() writes a hit file's header
        # (new count) before its payload bytes, so killing the process mid-window (mid-
        # append) can corrupt that file, not just lose a bit of progress. Stopping only
        # ever between windows -- never mid-window -- means a graceful stop is exactly as
        # safe as a normal --max-windows batch boundary, which this codebase already
        # relies on constantly. `remaining_after` (fixed before this loop started, at the
        # --max-windows cap) gets the rest of THIS batch added back in, so the post-loop
        # code below reports the correct "still pending" count for the floor, same as an
        # ordinary clipped batch would (and correctly skips the boundary check, which
        # only makes sense once the floor is genuinely caught up).
        if _stop_requested():
            remaining_after += len(to_process) - i
            print(f"\n[CONSTELLATIONS v2] STOP REQUESTED -- stopping cleanly after {i} "
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
        print(f"[CONSTELLATIONS v2] reading {i+1}/{len(to_process)}: {name}...")
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
            # Deduped, not a plain append_hits() call -- v2's done_range checkpoint (see
            # this file's own header comment) means resolve_done_names() should already
            # keep an already-covered window OUT of to_process in the normal case, but a
            # range whose boundary name resolve_done_names() couldn't find (stale
            # boundary -- see that function's own docstring) falls back to letting those
            # windows be re-scanned rather than silently trusting a mismatch. Re-scanning
            # produces the exact same hit values as before (matching is deterministic),
            # and without this dedup wrapper, re-appending them would crash on
            # append_prime_window()'s own strict-increase assertion the instant a
            # re-scanned window turns up a real hit. Kept as a safety net, same as v1.
            appended, skipped = _append_hits_deduped(
                base_exponent, k, vid, starts, last_value_cache, disk_cache=disk_last_values)
            total_hits_this_run[key] = total_hits_this_run.get(key, 0) + appended
            new_hits_count += appended
            skipped_hits_count += skipped

        done_indices.add(index_of[name])
        write_done_ranges(base_exponent, names, done_indices)

        extra = f" skipped_duplicates={skipped_hits_count}" if skipped_hits_count else ""
        print(f"[CONSTELLATIONS v2] {i+1}/{len(to_process)}: {name} -- "
              f"primes={len(candidates):,} peeked_head={len(head)} "
              f"new_hits={new_hits_count}{extra} ({time.time()-t0:.2f}s)")

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

    # Manual argv parsing (not argparse) -- kept in the same style as the rest of this
    # script's CLI, which has always been a single optional positional floor arg. --max-
    # windows (see process_floor()'s own docstring) is the one flag added on top of
    # that, so a tiny hand-rolled scan is simpler than pulling in argparse for one flag.
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
        floors = list_pietra_with_data()
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
