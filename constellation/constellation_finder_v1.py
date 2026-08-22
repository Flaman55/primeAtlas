import sys
import os
import time
import datetime
import numpy as np

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
# ==========================================================================================

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Self-contained alongside the rest of the app: prime_sieve_v1 lives in the sibling
# folder ../prime_sieve/.
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "..", "prime_sieve"))
import prime_sieve_v1  # noqa: E402

from pattern_catalog_v1 import PATTERN_CATALOG  # noqa: E402

# CONSTELLATION_PORTAL_DIR: optional override for the portal's root folder, used by the
# GUI's Settings tab to point at a custom storage location. Falls back to a
# CONSTELLATION_PORTAL folder next to the application root (one level up from this
# file) when unset, matching AppSettings.default_storage_path.
PORTAL_FOLDER = os.environ.get("CONSTELLATION_PORTAL_DIR") or os.path.abspath(
    os.path.join(_SCRIPT_DIR, "..", "CONSTELLATION_PORTAL"))
CHECKPOINT_FILENAME = "CHECKPOINT.txt"


def list_source_windows(base_exponent):
    """Returns [(filename, path, base_prime), ...] for every PRIME_WINDOW_*.bin under
    10p{base_exponent}/source_primes/, ordered ascending by base_prime (from each file's
    header -- robust regardless of filename shorthand)."""
    source_dir = os.path.join(PORTAL_FOLDER, f"10p{base_exponent}", "source_primes")
    if not os.path.isdir(source_dir):
        return []
    entries = []
    for name in sorted(os.listdir(source_dir)):
        if not (name.startswith("PRIME_WINDOW_") and name.endswith(".bin")):
            continue
        path = os.path.join(source_dir, name)
        header = prime_sieve_v1.read_prime_window_header(path)
        entries.append((name, path, header["base_prime"]))
    entries.sort(key=lambda e: (e[2] is None, e[2] if e[2] is not None else 0, e[0]))
    return entries


def list_pietra_with_data():
    """Returns sorted base_exponent ints for every 10p{N} folder under PORTAL_FOLDER that
    actually has at least one PGS2 source window. Floor folders can exist as empty
    source_primes/constellations placeholders ahead of the scanner actually reaching
    them, so folder presence alone doesn't mean there's anything to process."""
    if not os.path.isdir(PORTAL_FOLDER):
        return []
    result = []
    for name in os.listdir(PORTAL_FOLDER):
        if name.startswith("10p") and name[3:].isdigit():
            base_exponent = int(name[3:])
            if list_source_windows(base_exponent):
                result.append(base_exponent)
    return sorted(result)


def _checkpoint_path(base_exponent):
    folder = os.path.join(PORTAL_FOLDER, f"10p{base_exponent}", "constellations")
    return os.path.join(folder, CHECKPOINT_FILENAME)


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
    path = _checkpoint_path(base_exponent)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"last_processed_file={filename}\n")
        f.write(f"updated_at={datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")


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
    path = _boundary_marker_path(base_exponent)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"{note}\n")
        f.write(f"checked_at={datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")


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


def _append_hits_deduped(base_exponent, k, variant_id, new_sorted_starts, last_value_cache=None):
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

    `last_value_cache`, if given, is a dict CALLERS own and mutate across a whole run
    (see process_floor()'s own last_value_cache) -- same performance rationale as
    append_hits()'s own known_last_value parameter (avoids re-decoding the whole hit
    file on every single call). Falls back to reading the file's real last value from
    disk when no cache is given or this (k, variant_id) hasn't been seen yet this run.

    Returns (appended_count, skipped_count)."""
    if not new_sorted_starts:
        return 0, 0
    key = (k, variant_id)
    if last_value_cache is not None and key in last_value_cache:
        known_last_value = last_value_cache[key]
    else:
        hpath = hit_file_path(base_exponent, k, variant_id)
        existing = prime_sieve_v1.read_prime_window(hpath) if os.path.exists(hpath) else []
        known_last_value = existing[-1] if existing else None

    if known_last_value is None:
        to_append = new_sorted_starts
    else:
        to_append = [v for v in new_sorted_starts if v > known_last_value]
    skipped = len(new_sorted_starts) - len(to_append)

    if to_append:
        append_hits(base_exponent, k, variant_id, to_append, known_last_value=known_last_value)
        if last_value_cache is not None:
            last_value_cache[key] = to_append[-1]
    elif last_value_cache is not None:
        last_value_cache[key] = known_last_value

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


def check_floor_boundary(base_exponent, windows, active_patterns, max_span):
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
        # A one-off call, not part of process_floor()'s own hot per-window loop -- letting
        # _append_hits_deduped() re-discover the hit file's real last value from disk
        # here is fine; the O(current hit-file size) cost that incurs only matters when
        # it's paid on nearly every window of a run, which this isn't. Deduped (not a
        # plain append_hits() call) for the same reason as process_floor()'s own loop --
        # see _append_hits_deduped()'s own docstring.
        appended, skipped = _append_hits_deduped(base_exponent, k, vid, starts)
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


def process_floor(base_exponent):
    """Main entry point: streams through every not-yet-processed PGS2 window for this
    floor, in order, matching every catalog pattern (k>=2) and appending new hits. Also
    checks (once, then never again -- see check_floor_boundary()'s own docstring) whether
    a pattern spans this floor's own upper boundary into 10p{base_exponent+1}."""
    windows = list_source_windows(base_exponent)
    if not windows:
        print(f"[!] No source_primes windows found for 10^{base_exponent} "
              f"(expected under {PORTAL_FOLDER}/10p{base_exponent}/source_primes/).")
        return

    active_patterns = list(PATTERN_CATALOG)
    max_span = max(w["offsets"][-1] for w in active_patterns)

    last_done = read_checkpoint(base_exponent)
    names = [name for name, _, _ in windows]
    if last_done is not None and last_done in names:
        start_idx = names.index(last_done) + 1
        to_process = windows[start_idx:]
    else:
        if last_done is not None:
            print(f"[!] Checkpointed file {last_done!r} not found among current windows "
                  f"-- ignoring checkpoint, processing from the start.")
        to_process = windows

    print(f"\n[CONSTELLATIONS v1] 10^{base_exponent}: {len(to_process)}/{len(windows)} "
          f"windows to process | patterns active: {len(active_patterns)} (k>=2) | "
          f"MAX_SPAN={max_span}")

    if not to_process:
        print("[CONSTELLATIONS v1] Nothing new -- checkpoint is up to date.")
        # Still check the floor's own upper boundary even though there's no NEW window to
        # stream -- a floor fully checkpointed in a PAST run (hence to_process is empty
        # NOW) may only just have gotten its boundary resolvable THIS run, e.g. because
        # 10p{base_exponent + 1} was generated since the last time this floor was
        # processed. Skipping this here would mean a floor that's otherwise "done" never
        # gets its boundary checked at all once its own windows stop changing.
        check_floor_boundary(base_exponent, windows, active_patterns, max_span)
        return

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

    for i, (name, path, _base_prime) in enumerate(to_process):
        t0 = time.time()
        candidates = prime_sieve_v1.read_prime_window(path)

        head = []
        if i + 1 < len(to_process):
            next_name, next_path, next_base = to_process[i + 1]
            if next_base is not None:
                head = prime_sieve_v1.read_prime_window_head(next_path, next_base + max_span)

        local_set = set(candidates)
        local_set.update(head)

        results = match_patterns_vectorized(candidates, local_set, active_patterns)
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
            appended, skipped = _append_hits_deduped(base_exponent, k, vid, starts, last_value_cache)
            total_hits_this_run[key] = total_hits_this_run.get(key, 0) + appended
            new_hits_count += appended
            skipped_hits_count += skipped

        write_checkpoint(base_exponent, name)

        extra = f" skipped_duplicates={skipped_hits_count}" if skipped_hits_count else ""
        print(f"[CONSTELLATIONS v1] {i+1}/{len(to_process)}: {name} -- "
              f"primes={len(candidates):,} peeked_head={len(head)} "
              f"new_hits={new_hits_count}{extra} ({time.time()-t0:.2f}s)")

    check_floor_boundary(base_exponent, windows, active_patterns, max_span)

    print(f"\n[CONSTELLATIONS v1] Done. New hits this run, by pattern:")
    if not total_hits_this_run:
        print("    (none)")
    for (k, vid), count in sorted(total_hits_this_run.items()):
        print(f"    k={k:2} variant={vid}: +{count}")


if __name__ == "__main__":
    print("=" * 70)
    print("[*] CONSTELLATION FINDER -- v1 (PGS2 streaming + unified k=2..21 + "
          "in-place-append hit files)")
    print("=" * 70)

    print(f"[*] Portal: {PORTAL_FOLDER}")
    print("Start time:", datetime.datetime.now().strftime("%H:%M:%S"))

    if len(sys.argv) > 1:
        floors = [int(sys.argv[1])]
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
        process_floor(base_exponent)
