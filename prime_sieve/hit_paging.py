"""
hit_paging.py -- splits a constellation pattern's cumulative hit file
(constellations/k{K}/variant{ID}/HITS_....bin, written via
prime_sieve_v1.append_prime_window()) into fixed-size, closed "page" files once it
grows past PAGE_SIZE entries, plus a small metadata file per (floor, k, variant) that
lets a reader learn total_count/first_value/last_value in O(1) without opening any page
at all, same idea prime_sieve_v1.read_prime_window_header() already applies to a single
PGS2 file's own header.

PGS2 is gap-encoded, so reading "entry N" means sequentially decoding all N-1 entries
before it -- there is no random access into the middle of a hit file. A dense pattern's
single cumulative file (k=2 on floor 25: ~1.5 billion entries, ~2.9GB) makes any operation
needing more than the header (the records tab's cell drill-down, PDF/CSV export) either
materialize the whole pattern as one Python list (OOM risk) or block the GUI thread for the
whole decode. Pages bound every such read to one page.

A separate module from window_sharding.py: that one splits source_primes/ into many small
files per directory, while a hit file is a single cumulative file that grows without bound.

Dual-mode by design, not a forced migration: a pattern's hit file is "paged" if and
only if a PAGES_META.json file exists in its variant{ID}/ folder (is_paged() below) --
every reader and writer in this codebase checks that FIRST and falls back to the
original single-cumulative-file behavior (prime_sieve_v1.append_prime_window()/
read_prime_window()/read_prime_window_header() directly on hit_file_path()'s path)
when it's absent. This means migrate_hit_file_to_pages() only needs to run for
patterns that actually reach problematic scale (in practice: k=2 on the densest,
highest floors) -- most patterns (anything with a handful to a few thousand hits)
never need it and use the single-file path.

Page files live in the SAME variant{ID}/ folder as the (pre-migration) cumulative
file, named f"HITS_10p{N}_k{K}_v{V}_page{P:05d}.bin" -- each one is an ordinary PGS2
file in its own right (written via prime_sieve_v1.write_prime_window()/
append_prime_window() exactly like the cumulative file was), so every existing
PGS2-reading primitive (read_prime_window, read_prime_window_header, ...) works on a
single page completely unchanged; only the bookkeeping of WHICH page is new here.
"""
import bisect
import json
import math
import os
import re

import prime_sieve_v1

PAGE_SIZE = 1_000_000

META_FILENAME = "PAGES_META.json"


def variant_dir(portal_folder, base_exponent, k, variant_id):
    """Same folder convention constellation_finder_v2.py's hit_file_path() and
    primeatlas/constellations.py's hit_file_path() already use for a pattern's
    variant{ID}/ folder -- kept as one shared helper (like window_sharding.py's own
    reasoning for being one module: writer and reader must agree on this path, a
    mismatched copy in just one caller would silently look in the wrong place)."""
    return os.path.join(
        portal_folder, f"10p{base_exponent}", "constellations", f"k{k}", f"variant{variant_id}")


def meta_path(a_variant_dir):
    return os.path.join(a_variant_dir, META_FILENAME)


def page_path(a_variant_dir, base_exponent, k, variant_id, page_index):
    return os.path.join(
        a_variant_dir, f"HITS_10p{base_exponent}_k{k}_v{variant_id}_page{page_index:05d}.bin")


def is_paged(a_variant_dir):
    """Cheap existence check -- the ONE thing every reader/writer in this codebase
    should call first to decide whether a pattern's hits live in pages or in the
    original single cumulative file (see this module's own docstring)."""
    return os.path.exists(meta_path(a_variant_dir))


def read_meta(a_variant_dir):
    """Returns the metadata dict, or None if this pattern isn't paged (is_paged() is
    just os.path.exists(meta_path(...)); this additionally parses it -- most callers
    that need the fields want this directly rather than checking existence first)."""
    path = meta_path(a_variant_dir)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_meta(a_variant_dir, meta):
    """Atomic tmp-then-replace + fsync, same crash-safety pattern
    constellation_finder_v2.py's _write_last_values_disk_cache()/write_checkpoint()
    already use for small, frequently-rewritten metadata files -- a direct
    open(path, "w") would truncate PAGES_META.json before writing its replacement, and
    a crash/power-loss mid-write would leave a metadata file every reader trusts
    blindly (there is nothing to cross-check it against, unlike the LAST_VALUES.tsv
    disk cache's count-vs-header validation) silently corrupted instead of just
    missing."""
    os.makedirs(a_variant_dir, exist_ok=True)
    path = meta_path(a_variant_dir)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(meta, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def page_count(meta):
    """Legacy metadata (no "pages" list): derived from total_count and page_size, every
    page full except the last. Metadata that has been through insert_hits_paged() lists
    its pages explicitly (see that function), since pages then differ in size."""
    if "pages" in meta:
        return len(meta["pages"])
    if meta["total_count"] == 0:
        return 0
    return math.ceil(meta["total_count"] / meta["page_size"])


def page_start(meta, page_index):
    """Global position (0-based) of page `page_index`'s first entry within the whole
    pattern -- page_index * page_size for legacy uniform pages, the sum of the earlier
    pages' counts once they differ in size."""
    if "pages" in meta:
        return sum(entry["count"] for entry in meta["pages"][:page_index])
    return page_index * meta["page_size"]


def _page_id(meta, page_index):
    """File id (the number in "..._page{id:05d}.bin") of the page at position
    `page_index`. Legacy pages are numbered by position; listed pages carry their own id,
    because a page rewritten by insert_hits_paged() is written under a FRESH id (see
    there) and so no longer matches its position."""
    if meta is not None and "pages" in meta:
        return meta["pages"][page_index]["id"]
    return page_index


def page_file(a_variant_dir, meta, page_index):
    """Path of the page at position `page_index`."""
    return page_path(a_variant_dir, meta["base_exponent"], meta["k"], meta["variant_id"],
                     _page_id(meta, page_index))


def read_page(a_variant_dir, base_exponent, k, variant_id, page_index):
    """Decodes ONLY page `page_index` -- cost is bounded by page_size regardless of how
    large the pattern's total_count is, which is the entire point of paging (see this
    module's own docstring)."""
    path = page_path(a_variant_dir, base_exponent, k, variant_id,
                     _page_id(read_meta(a_variant_dir), page_index))
    return prime_sieve_v1.read_prime_window(path)


def read_page_header(a_variant_dir, base_exponent, k, variant_id, page_index):
    path = page_path(a_variant_dir, base_exponent, k, variant_id,
                     _page_id(read_meta(a_variant_dir), page_index))
    return prime_sieve_v1.read_prime_window_header(path)


def append_hits_paged(a_variant_dir, base_exponent, k, variant_id, new_sorted_values, meta=None):
    """Paged sibling of constellation_finder_v2.py's append_hits(): appends to the
    CURRENTLY OPEN (last) page, starting a fresh page once the current one reaches
    meta["page_size"] entries. `meta`, if given, is the SAME dict a caller making many
    appends across one run should keep reusing (mutated in place and returned) --
    identical performance rationale to append_hits()'s own known_last_value/
    last_value_cache: reading+parsing the small PAGES_META.json on every single append
    is cheap in isolation (O(1) regardless of total_count) but still needless disk I/O
    at the volume a dense pattern's per-window appends run at.

    Creates a fresh, empty meta (page_size=PAGE_SIZE) if none exists yet and none was
    passed in -- callers that want to START paging a previously-unpaged pattern should
    go through migrate_hit_file_to_pages() instead, not this function directly, so the
    pre-existing single cumulative file's own values are never silently orphaned.

    Strict-increase (new values > current last_value) is enforced per PAGE by
    prime_sieve_v1.append_prime_window() exactly as it already is for the unpaged path
    -- this function does no deduping of its own, same division of responsibility as
    append_hits(): constellation_finder_v2.py's _append_hits_deduped() wrapper is
    where that filtering happens, upstream of both the paged and unpaged write paths.

    Returns the updated meta dict (already written to disk)."""
    if not new_sorted_values:
        return meta if meta is not None else read_meta(a_variant_dir)
    if meta is None:
        meta = read_meta(a_variant_dir)
    if meta is None:
        meta = {
            "base_exponent": base_exponent, "k": k, "variant_id": variant_id,
            "page_size": PAGE_SIZE, "total_count": 0,
            "first_value": None, "last_value": None,
        }
    os.makedirs(a_variant_dir, exist_ok=True)
    if "pages" in meta:
        _append_listed(a_variant_dir, meta, list(new_sorted_values))
        write_meta(a_variant_dir, meta)
        return meta
    page_size = meta["page_size"]
    remaining = list(new_sorted_values)
    running_last = meta["last_value"]
    while remaining:
        current_index = meta["total_count"] // page_size
        slots_left = page_size - (meta["total_count"] - current_index * page_size)
        chunk = remaining[:slots_left]
        remaining = remaining[slots_left:]
        ppath = page_path(a_variant_dir, base_exponent, k, variant_id, current_index)
        if os.path.exists(ppath):
            prime_sieve_v1.append_prime_window(ppath, chunk, known_last_value=running_last)
        else:
            prime_sieve_v1.write_prime_window(ppath, chunk)
        if meta["first_value"] is None:
            meta["first_value"] = chunk[0]
        meta["total_count"] += len(chunk)
        meta["last_value"] = chunk[-1]
        running_last = chunk[-1]
    write_meta(a_variant_dir, meta)
    return meta


_PAGE_ID_RE = re.compile(r"_page(\d+)\.bin$")


def _next_page_id(a_variant_dir, meta):
    """A page id used neither by the metadata nor by any file on disk -- the disk check
    matters after a crash between writing new page files and writing the metadata that
    would have referenced them (insert_hits_paged()'s write order), which leaves such
    files behind unreferenced. It also makes a page file written a moment ago reserve
    its id for the next piece of the same split."""
    used = {entry["id"] for entry in meta["pages"]}
    if os.path.isdir(a_variant_dir):
        for name in os.listdir(a_variant_dir):
            m = _PAGE_ID_RE.search(name)
            if m:
                used.add(int(m.group(1)))
    return max(used, default=-1) + 1


def _append_listed(a_variant_dir, meta, values):
    """append_hits_paged() for listed metadata: fills the last page up to page_size,
    then opens pages under fresh ids. Mutates `meta` (the caller writes it)."""
    page_size = meta["page_size"]
    b, k, v = meta["base_exponent"], meta["k"], meta["variant_id"]
    while values:
        last = meta["pages"][-1] if meta["pages"] else None
        if last is not None and last["count"] < page_size:
            room = page_size - last["count"]
            chunk, values = values[:room], values[room:]
            prime_sieve_v1.append_prime_window(page_path(a_variant_dir, b, k, v, last["id"]), chunk,
                                               known_last_value=meta["last_value"])
            last["count"] += len(chunk)
        else:
            chunk, values = values[:page_size], values[page_size:]
            new_id = _next_page_id(a_variant_dir, meta)
            prime_sieve_v1.write_prime_window(page_path(a_variant_dir, b, k, v, new_id), chunk)
            meta["pages"].append({"id": new_id, "count": len(chunk), "first": chunk[0]})
        if meta["first_value"] is None:
            meta["first_value"] = chunk[0]
        meta["total_count"] += len(chunk)
        meta["last_value"] = chunk[-1]


def _ensure_page_list(a_variant_dir, meta):
    """Upgrades legacy metadata (uniform page_size, pages numbered by position) to an
    explicit [{"id", "count", "first"}, ...] list -- one header read per page, once per
    pattern. Mutates `meta` (the caller writes it)."""
    if "pages" in meta:
        return
    n = page_count(meta)
    page_size = meta["page_size"]
    pages = []
    for i in range(n):
        header = prime_sieve_v1.read_prime_window_header(
            page_path(a_variant_dir, meta["base_exponent"], meta["k"], meta["variant_id"], i))
        count = page_size if i < n - 1 else meta["total_count"] - page_size * (n - 1)
        pages.append({"id": i, "count": count, "first": header["base_prime"]})
    meta["pages"] = pages


def insert_hits_paged(a_variant_dir, base_exponent, k, variant_id, new_sorted_values, meta=None):
    """Stores `new_sorted_values` as the sorted union with what this paged pattern
    already holds, wherever they fall -- below the first stored value, between stored
    values, or past the last. Returns (meta, added, duplicates).

    A floor's windows can be generated and scanned in any order (below, between or above
    already-scanned ones), and append_hits_paged() can only extend the end.

    Values past the last stored one take the cheap append path. The rest are grouped by
    the page whose range they fall into (the rightmost page whose first value <= the
    value; page 0 for anything below the whole pattern), and only those pages are
    rewritten -- decode, merge, re-encode one page (~1M values, well under a second),
    never the whole pattern (k=2 on floor 25: ~2,000 pages). A merged page above
    2 * page_size is split into page_size pieces, so pages stay bounded for every reader
    (records tab drill-down, hits tab, exports).

    Crash safety: rewritten pages are written under FRESH ids, the metadata (atomic
    replace) is switched over to them, and only then are the replaced files deleted. A
    crash before the metadata write leaves the old, still-consistent pattern plus some
    unreferenced files; after it, at worst some stale files nothing references."""
    if meta is None:
        meta = read_meta(a_variant_dir)
    values = sorted(set(new_sorted_values))
    if not values:
        return meta, 0, 0
    if meta is None or meta["total_count"] == 0:
        meta = append_hits_paged(a_variant_dir, base_exponent, k, variant_id, values, meta=meta)
        return meta, len(values), 0

    cut = bisect.bisect_right(values, meta["last_value"])
    inside, tail = values[:cut], values[cut:]
    added = 0
    duplicates = 0
    if inside:
        _ensure_page_list(a_variant_dir, meta)
        page_size = meta["page_size"]
        firsts = [entry["first"] for entry in meta["pages"]]
        groups = {}
        for value in inside:
            groups.setdefault(max(0, bisect.bisect_right(firsts, value) - 1), []).append(value)
        obsolete = []
        # Highest page first: splitting a page inserts list entries after it, which
        # must not shift the positions of pages still waiting to be processed.
        for index in sorted(groups, reverse=True):
            group = groups[index]
            entry = meta["pages"][index]
            old_path = page_path(a_variant_dir, base_exponent, k, variant_id, entry["id"])
            old_values = prime_sieve_v1.read_prime_window(old_path)
            merged = sorted(set(old_values).union(group))
            new_here = len(merged) - len(old_values)
            added += new_here
            duplicates += len(group) - new_here
            if new_here == 0:
                continue
            pieces = ([merged[i:i + page_size] for i in range(0, len(merged), page_size)]
                      if len(merged) > 2 * page_size else [merged])
            replacement = []
            for piece in pieces:
                new_id = _next_page_id(a_variant_dir, meta)
                prime_sieve_v1.write_prime_window(
                    page_path(a_variant_dir, base_exponent, k, variant_id, new_id), piece)
                replacement.append({"id": new_id, "count": len(piece), "first": piece[0]})
            meta["pages"][index:index + 1] = replacement
            obsolete.append(old_path)
        if added:
            meta["total_count"] += added
            meta["first_value"] = min(meta["first_value"], inside[0])
            write_meta(a_variant_dir, meta)
            for path in obsolete:
                try:
                    os.remove(path)
                except OSError:
                    pass
    if tail:
        meta = append_hits_paged(a_variant_dir, base_exponent, k, variant_id, tail, meta=meta)
        added += len(tail)
    return meta, added, duplicates


def migrate_hit_file_to_pages(source_path, a_variant_dir, base_exponent, k, variant_id,
                               page_size=None, dry_run=False):
    """One-time conversion of an existing single cumulative hit file into paged form --
    analogous to prime_sieve_v1's own migrate_shard_source_primes.py for
    source_primes/, but for constellation hits. Refuses to run if this pattern is
    already paged (is_paged(a_variant_dir)), to avoid double-migrating.

    Streams the source file via prime_sieve_v1.iter_prime_window_chunks() -- NEVER
    prime_sieve_v1.read_prime_window() -- specifically because materializing a
    ~1.5-billion-entry pattern (floor 25's k=2) as one Python list is the same class of
    OOM risk this whole module exists to eliminate; see iter_prime_window_chunks()'s
    own docstring. Peak added memory is O(page_size) ints, not O(total count).

    `dry_run=True` reads only the header (O(1)) and reports how many pages WOULD be
    created without writing anything -- use this first against a real large file
    before committing to the real run.

    On success, renames the original single file to f"{source_path}.pre_page_
    migration.bak" (not deleted) so migration is trivially reversible (rename back +
    delete the page files + delete PAGES_META.json) and so its old ".bin" name no
    longer collides with the "does floor_has_constellation_hits() see a hit file here"
    existence check -- callers should keep a real filesystem backup of the whole
    portal folder before running this against irreplaceable production data regardless
    (a rename on the SAME filesystem is not a substitute for an actual backup if the
    disk itself fails mid-migration).

    `page_size` defaults to the module's current PAGE_SIZE, resolved INSIDE the
    function body (not as a bare default-argument value) so a caller that never
    passes it explicitly still picks up any runtime change to hit_paging.PAGE_SIZE --
    a default-argument value is bound once, at function-DEFINITION time (module
    import), so `page_size=PAGE_SIZE` directly in the signature would silently keep
    using whatever PAGE_SIZE was at import time even after a test (or a future
    config feature) changes the module attribute later.

    Returns a dict: {"total_count": int, "page_count": int, "dry_run": bool}."""
    if page_size is None:
        page_size = PAGE_SIZE
    if is_paged(a_variant_dir):
        raise ValueError(f"{a_variant_dir}: already paged (refusing to double-migrate)")
    header = prime_sieve_v1.read_prime_window_header(source_path)
    total_count = header["count"]
    planned_pages = math.ceil(total_count / page_size) if total_count else 0
    if dry_run:
        return {"total_count": total_count, "page_count": planned_pages, "dry_run": True}

    meta = {
        "base_exponent": base_exponent, "k": k, "variant_id": variant_id,
        "page_size": page_size, "total_count": 0,
        "first_value": None, "last_value": None,
    }
    for chunk in prime_sieve_v1.iter_prime_window_chunks(source_path, page_size):
        page_index = meta["total_count"] // page_size
        ppath = page_path(a_variant_dir, base_exponent, k, variant_id, page_index)
        prime_sieve_v1.write_prime_window(ppath, chunk)
        if meta["first_value"] is None:
            meta["first_value"] = chunk[0]
        meta["total_count"] += len(chunk)
        meta["last_value"] = chunk[-1]
    write_meta(a_variant_dir, meta)

    backup_path = source_path + ".pre_page_migration.bak"
    os.replace(source_path, backup_path)

    return {"total_count": meta["total_count"], "page_count": page_count(meta), "dry_run": False}
