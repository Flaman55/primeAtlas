import datetime
import os
import sys
import time

# ==========================================================================================
# constellation_finder_v2_2.py
#
# Same engine as constellation_finder_v2.py, split across modules (unitTests/
# test_constellation_finder_v2_2.py checks that every function and constant matches).
# It is the version the GUI launches. Module layout:
#   constellation_const_v2_2.py    -- shared fixed values (state file names, diag switch)
#   constellation_dynamic_v2_2.py  -- shared import-time values (PORTAL_FOLDER, sys.path)
#   constellation_diag_v2_2.py     -- crash-diagnosis helpers
#   constellation_windows_v2_2.py  -- source window list and WINDOW_INDEX.tsv
#   constellation_progress_v2_2.py -- done log, checkpoint ranges, boundary marker, stop
#   constellation_hits_v2_2.py     -- hit storage, last-value cache, deduped appends
#   constellation_match_v2_2.py    -- vectorized pattern matching
#   constellation_finder_v2_2.py   -- floor boundary check, process_floor(), the CLI
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
# alongside for engine_argv.py's read_constellation_checkpoint() and v1's
# read_checkpoint(). A v1-only CHECKPOINT.txt (no done_range= lines) is read as one range
# from the floor's first window through last_processed_file. The authoritative done set
# is DONE_WINDOWS.txt (see DONE_LOG_FILENAME); the ranges seed it on first use.
# ==========================================================================================

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)  # sibling constellation_*_v2_2.py, pattern_catalog_v1.py
import constellation_dynamic_v2_2 as _dyn  # first: puts ../prime_sieve on sys.path  # noqa: E402
import constellation_const_v2_2 as _const  # noqa: E402
import prime_sieve_v1  # noqa: E402
import hit_paging  # noqa: E402

from pattern_catalog_v1 import PATTERN_CATALOG  # noqa: E402
from constellation_diag_v2_2 import _proc_diag, _diag_fsync_print  # noqa: E402
from constellation_windows_v2_2 import list_source_windows, list_floors_with_data  # noqa: E402
from constellation_progress_v2_2 import (  # noqa: E402
    read_done_log, seed_done_log, append_done_log, _stop_requested, resolve_done_names,
    write_done_ranges, is_boundary_checked, write_boundary_checked,
)
from constellation_hits_v2_2 import (  # noqa: E402
    _read_last_values_disk_cache, _write_last_values_disk_cache, _append_hits_deduped,
    _flush_deferred_hits,
)
from constellation_match_v2_2 import match_patterns_vectorized  # noqa: E402


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

    Graceful stop (_const.STOP_REQUEST_FILENAME): checked at the top of each window, so a stop
    only happens BETWEEN windows -- append_prime_window() writes a hit file's header
    (new count) before its payload, so a mid-window kill can leave a header claiming
    entries that were never written. A stop is handled like a clipped batch (unprocessed
    tail added to remaining_after, boundary check skipped)."""
    run_start = time.time()
    windows = list_source_windows(base_exponent)
    if not windows:
        print(f"[!] No source_primes windows found for 10^{base_exponent} "
              f"(expected under {_dyn.PORTAL_FOLDER}/10p{base_exponent}/source_primes/).")
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

    if _const.CONSTELLATION_DIAG_ENABLED:
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
        detailed = _const.CONSTELLATION_DIAG_ENABLED and i < DETAILED_DIAG_WINDOWS
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
        elif _const.CONSTELLATION_DIAG_ENABLED and i % HEARTBEAT_EVERY == 0:
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
    if _const.CONSTELLATION_DIAG_ENABLED:
        print(f"[CONSTELLATIONS v2] DIAG: run finished, elapsed={time.time()-run_start:.2f}s "
              f"| {_proc_diag()}")

    return remaining_after


if __name__ == "__main__":
    print("=" * 70)
    print("[*] CONSTELLATION FINDER -- v2.2 (PGS2 streaming + unified k=2..21 + "
          "in-place-append hit files)")
    print("=" * 70)

    print(f"[*] Portal: {_dyn.PORTAL_FOLDER}")
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
