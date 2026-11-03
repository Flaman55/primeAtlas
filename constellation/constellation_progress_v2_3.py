"""
constellation_progress_v2_3.py -- what a floor's scan has already covered: the done log
(DONE_WINDOWS.txt), the gap-aware CHECKPOINT.txt ranges, the BOUNDARY_CHECKED.txt marker
and the GUI's portal-root stop request. Every write is atomic (tmp-then-replace) or an
fsynced append.
"""
import datetime
import os

import constellation_const_v2_3 as _const


def _checkpoint_path(portal, base_exponent):
    folder = os.path.join(portal, f"10p{base_exponent}", "constellations")
    return os.path.join(folder, _const.CHECKPOINT_FILENAME)


def _done_log_path(portal, base_exponent):
    return os.path.join(portal, f"10p{base_exponent}", "constellations", _const.DONE_LOG_FILENAME)


def read_done_log(portal, base_exponent):
    """The set of window names in this floor's done log, or None if it has no log yet."""
    path = _done_log_path(portal, base_exponent)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def seed_done_log(portal, base_exponent, names):
    """Creates the done log from `names` (atomic tmp-then-replace + fsync) -- used once
    per floor, from the legacy done_range= resolution."""
    path = _done_log_path(portal, base_exponent)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        for name in sorted(names):
            f.write(name + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def append_done_log(portal, base_exponent, names):
    """Appends newly finished window names (fsynced). A torn last line from a crash
    mid-append is just an unknown name -- that window gets scanned again, which is safe."""
    if not names:
        return
    path = _done_log_path(portal, base_exponent)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for name in names:
            f.write(name + "\n")
        f.flush()
        os.fsync(f.fileno())


def _stop_requested(portal):
    """True once the GUI has asked this run to stop (see _const.STOP_REQUEST_FILENAME). A plain
    existence check, not consumed here: generation_tab.py's _on_constellation_finished()
    removes the marker, since it runs exactly once per launch whether this script saw the
    marker or was killed first."""
    return os.path.exists(os.path.join(portal, _const.STOP_REQUEST_FILENAME))


def read_checkpoint(portal, base_exponent):
    """Returns the filename of the furthest-along PGS2 window recorded for this floor
    (the highest-index window covered by any done_range -- see write_done_ranges()'s own
    docstring for why this is still written even though process_floor() itself now
    resumes from read_done_ranges(), not this value), or None if there's no checkpoint
    yet. Kept for engine_argv.py's own read_constellation_checkpoint() (GUI-side "did we
    make progress" comparison) and for v1-style callers/tests that only care about "how
    far has this floor gotten", not the full gap-aware picture."""
    path = _checkpoint_path(portal, base_exponent)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("last_processed_file="):
                return line.split("=", 1)[1].strip()
    return None


def read_done_ranges(portal, base_exponent):
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
    path = _checkpoint_path(portal, base_exponent)
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


def resolve_done_names(portal, base_exponent, names):
    """Turns this floor's persisted done_ranges into a set of done window names,
    validated against `names` (the current base_prime-sorted window list, see
    list_source_windows()). A range whose boundary name is not in `names` cannot be
    resolved to a position and is dropped with a warning; its windows get re-scanned,
    which is safe (see _append_hits_deduped())."""
    if not names:
        return set()
    logged = read_done_log(portal, base_exponent)
    if logged is not None:
        return logged.intersection(names)
    index_of = {name: i for i, name in enumerate(names)}
    done = set()
    for first, last in read_done_ranges(portal, base_exponent):
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


def write_done_ranges(portal, base_exponent, names, done_indices):
    """Atomic tmp-then-replace + fsync (as v1's write_checkpoint()), persisting the full
    set of processed windows as merged (first_name|last_name) ranges over `names` (the
    current base_prime-sorted window list).

    `done_indices` -- every index into `names` that is done as of this write (the full
    set, not a delta); the range list stays short since processing is normally in order.

    Also writes `last_processed_file=` (the name at the highest done index) -- see
    read_checkpoint() for its readers."""
    path = _checkpoint_path(portal, base_exponent)
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



def _boundary_marker_path(portal, base_exponent):
    folder = os.path.join(portal, f"10p{base_exponent}", "constellations")
    return os.path.join(folder, _const.BOUNDARY_MARKER_FILENAME)


def is_boundary_checked(portal, base_exponent):
    """True once this floor's upper boundary (against 10p{base_exponent+1}) has been
    resolved -- see check_floor_boundary(). A separate marker from CHECKPOINT.txt: it
    tracks the one cross-floor check, not which windows were streamed."""
    return os.path.exists(_boundary_marker_path(portal, base_exponent))


def write_boundary_checked(portal, base_exponent, note):
    """Atomic tmp-then-replace + fsync, as write_checkpoint(): a plain open(path, "w")
    truncates first, so a crash mid-write could leave a garbage marker that
    is_boundary_checked() still accepts (os.path.exists() is true for a 0-byte file)."""
    path = _boundary_marker_path(portal, base_exponent)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(f"{note}\n")
        f.write(f"checked_at={datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
