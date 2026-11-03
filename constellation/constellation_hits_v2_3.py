"""
constellation_hits_v2_3.py -- the cumulative hit storage of every (k, variant): file
layout, the LAST_VALUES.tsv cache of each pattern's last stored value, appends with
auto-migration to pages, and the deduplicating append/merge that makes a re-scan safe.
"""
import os
import time

import constellation_const_v2_3 as _const
import prime_sieve_v1  # noqa: E402
import hit_paging  # noqa: E402
from constellation_diag_v2_3 import _proc_diag, _diag_fsync_print  # noqa: E402


def _last_values_path(portal, base_exponent):
    folder = os.path.join(portal, f"10p{base_exponent}", "constellations")
    return os.path.join(folder, _const.LAST_VALUES_FILENAME)


def _read_last_values_disk_cache(portal, base_exponent):
    """Returns {(k, variant_id): (last_value, count)} from this floor's persistent
    last-value cache. process_floor()'s in-memory last_value_cache starts empty every
    run; without this, the first hit for a pattern in a run would decode the pattern's
    whole hit file to learn its last value, which for a dense pattern (k=2 on a large
    floor) can exhaust memory.

    Returns {} if no cache file exists yet (same contract as _read_window_index())."""
    path = _last_values_path(portal, base_exponent)
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


def _write_last_values_disk_cache(portal, base_exponent, cache):
    """Writes the WHOLE cache at once, same atomic tmp-then-replace pattern as
    _write_window_index() -- called ONCE per process_floor() run (not once per append),
    since the cache holds at most one entry per CATALOG PATTERN (at most a few dozen,
    see PATTERN_CATALOG -- NOT one per window, unlike WINDOW_INDEX.tsv), so batching
    the write costs nothing and avoids dozens of tiny file writes scattered across a
    run for no benefit."""
    path = _last_values_path(portal, base_exponent)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        for (k, vid), (last_value, count) in cache.items():
            f.write(f"{k}\t{vid}\t{last_value}\t{count}\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _resolve_last_value(portal, base_exponent, k, variant_id, disk_cache):
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
    vdir = hit_paging.variant_dir(portal, base_exponent, k, variant_id)
    if hit_paging.is_paged(vdir):
        meta = hit_paging.read_meta(vdir)
        return meta["last_value"], meta["total_count"]
    hpath = hit_file_path(portal, base_exponent, k, variant_id)
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


def hit_file_path(portal, base_exponent, k, variant_id):
    return os.path.join(
        portal, f"10p{base_exponent}", "constellations", f"k{k}", f"variant{variant_id}",
        f"HITS_10p{base_exponent}_k{k}_v{variant_id}.bin")


def append_hits(portal, base_exponent, k, variant_id, new_sorted_starts, known_last_value=None):
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
    vdir = hit_paging.variant_dir(portal, base_exponent, k, variant_id)
    if hit_paging.is_paged(vdir):
        hit_paging.append_hits_paged(vdir, base_exponent, k, variant_id, new_sorted_starts)
        return
    path = hit_file_path(portal, base_exponent, k, variant_id)
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


def _append_hits_deduped(portal, base_exponent, k, variant_id, new_sorted_starts, last_value_cache=None,
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
        known_last_value, old_count = _resolve_last_value(portal, base_exponent, k, variant_id, disk_cache)

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
        inserted, skipped = _insert_hits_sorted(portal, base_exponent, k, variant_id, not_after_last)
    else:
        inserted, skipped = 0, 0
    new_last_value = known_last_value
    new_count = old_count + inserted
    if to_append:
        append_hits(portal, base_exponent, k, variant_id, to_append, known_last_value=known_last_value)
        new_last_value = to_append[-1]
        new_count += len(to_append)
    if last_value_cache is not None:
        last_value_cache[key] = (new_last_value, new_count)
    if disk_cache is not None:
        disk_cache[key] = (new_last_value, new_count)

    return len(to_append) + inserted, skipped


def _flush_deferred_hits(portal, base_exponent, deferred, last_value_cache, disk_cache):
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
        added, dup = _insert_hits_sorted(portal, base_exponent, k, variant_id, values)
        added_by_key[key] = added
        duplicates += dup + (len(deferred[key]) - len(values))
        for cache in (last_value_cache, disk_cache):
            if cache is not None and key in cache:
                last_value, count = cache[key]
                cache[key] = (last_value, count + added)
    deferred.clear()
    return added_by_key, duplicates


def _insert_hits_sorted(portal, base_exponent, k, variant_id, values):
    """Merges `values` (all <= the pattern's last stored value) into its hit storage as a
    sorted union. Returns (added, duplicates).

    Paged pattern: hit_paging.insert_hits_paged() rewrites only the pages the values fall
    into. Unpaged pattern: small by construction (auto-migration keeps it under
    hit_paging.PAGE_SIZE), so the whole file is decoded, merged and rewritten via a temp
    file + atomic replace; a merge that grows it past PAGE_SIZE migrates it to pages,
    same as append_hits() does for an append."""
    vdir = hit_paging.variant_dir(portal, base_exponent, k, variant_id)
    if hit_paging.is_paged(vdir):
        _, added, duplicates = hit_paging.insert_hits_paged(vdir, base_exponent, k, variant_id, values)
        return added, duplicates
    path = hit_file_path(portal, base_exponent, k, variant_id)
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
