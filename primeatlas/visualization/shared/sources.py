"""
sources.py -- ring-array data sources for primeatlas/visualization/shared/renderer.py:
load_synthetic, load_sieve, load_archive.

Kept independent of moderngl/glfw and of renderer.py's own GL-context state
-- see renderer.py's own module docstring, data-source point 1, for why
these three loaders are deliberately interchangeable and decoupled from the
rendering path: --source picks which one runs, and all three return a plain
ascending prime/ring array (to_prime_array's own uint64-or-object dtype
choice) that the rest of the renderer treats identically regardless of
where it came from.

Self-contained sys.path bootstrap (mirrors renderer.py's own, see that
file's module docstring for the full "why plain-script-path" explanation):
needed so `import prime_sieve_v1` / `from primeatlas.core import storage` inside
load_archive work whether this module is imported after renderer.py has
already run its own bootstrap, or on its own (e.g. directly from a test).
"""

import os
import sys

import numpy as np

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_PRIME_SIEVE_DIR = os.path.join(_REPO_ROOT, "prime_sieve")
if _PRIME_SIEVE_DIR not in sys.path:
    sys.path.insert(0, _PRIME_SIEVE_DIR)

from primeatlas.visualization.rings.ring_geometry import to_prime_array


def load_synthetic(count, seed=0):
    """A strictly increasing int64 array of exactly `count` values -- NOT
    real primes (no primality claim at all), for the purest rendering-only
    stress test. Gaps drawn from a small positive range so values stay
    'prime-density-ish' in magnitude without needing to actually sieve
    anything -- see module docstring point 1."""
    rng = np.random.default_rng(seed)
    gaps = rng.integers(1, 40, size=count, dtype=np.int64)
    return np.cumsum(gaps) + 2


def load_sieve(upto):
    """Real sieve of Eratosthenes up to `upto` (moderate scale only -- this
    is O(upto) memory as a bytearray, fine into the hundreds of millions, not
    intended for anything near archive scale; use --source archive for that).
    """
    if upto < 2:
        return np.empty(0, dtype=np.int64)
    is_composite = bytearray(upto + 1)
    primes = []
    for p in range(2, upto + 1):
        if not is_composite[p]:
            primes.append(p)
            if p * p <= upto:
                is_composite[p * p:upto + 1:p] = b"\x01" * len(range(p * p, upto + 1, p))
    return np.array(primes, dtype=np.int64)


def load_archive(portal_folder, upto, progress_callback=None, batch_files=64, from_n=0,
                  max_load_count=None):
    """Reads real primes in (from_n, upto] from an existing PrimeAtlas
    portal folder, via primeatlas.core.storage's own file-listing helpers and
    prime_sieve_v1.read_prime_window for the actual decode.

    Optional hard cap on how many primes this call ever materializes.
    Enforced as an early stop (mirrors the existing `floor_done` break just
    below) rather than a post-hoc `result[:max_load_count]` slice, so a huge
    `(from_n, upto]` span -- the whole point of `from_n` jumping straight to
    a high floor -- never reads a single file more than needed once the cap
    is hit. Truncation is always from the TOP (the highest values get cut),
    a natural consequence of floors/files being walked in ascending order
    already. `None` (default) means unbounded. No fixed cap is hardcoded: no safe
    figure has been benchmarked on archive hardware, so the caller (rings_tab.py)
    exposes it as a configurable field.

    `from_n` defaults to 0 (every prime is >0, so the whole (0, upto] range). A
    non-zero `from_n` lets a caller that already
    holds every prime up to some point (extend_buffer_if_needed in
    _run_visualization, renderer.py) fetch only the NEW primes past that
    point instead of re-reading and re-returning the whole [0, upto] range
    again -- two cheap wins over a naive "just call load_archive(new_upto)
    again" approach: (1) whole floors entirely below `from_n` are skipped
    without even listing their files (see the floor_hi_exclusive check
    below), and (2) within the one floor spanning `from_n`, files are still
    opened (no per-file range metadata to skip them by name alone) but
    their already-covered primes are trimmed out before being added to the
    result, so nothing already known gets duplicated into the array.

    This loader is hardened against portal-scale failure modes in three
    ways:

    1. Enumerates the floors actually on disk via storage.list_floors(), so a gap
       in the portal (e.g. floor 5 populated, floor 6 not) costs nothing and the
       walk stops at the portal's highest floor.
    2. Reads window files in BOUNDED BATCHES (`batch_files` at a time,
       default 64) rather than one unbounded Python list across a floor: each
       batch is concatenated and appended to the running result right away, so
       peak EXTRA memory during the load is one batch's arrays. The final
       concatenate is unavoidable (the renderer needs one contiguous sorted array).
    3. Accepts an optional `progress_callback(base_exponent, files_read_in_floor,
       primes_loaded_so_far)`, invoked after every batch, so a caller
       (primeatlas/visualization/rings/rings_tab.py) can drive a real progress bar
       instead of a frozen GUI during what can be a multi-second load at
       real archive scale. Deliberately NOT trying to make the load itself
       faster (see this module's own docstring, data-source point 1, for why
       generation/read throughput is explicitly out of scope for this
       feature to optimize) -- only making the existing cost observable and
       boundable instead of an opaque hang.

    This loader's own cost is dominated by per-file open() latency on the
    FUSE-mounted storage drive (~5ms/file -- the same figure
    storage.update_floor_totals_cache()'s own docstring measured on this
    exact drive), not the PGS decode work itself. That means the real
    bottleneck to watch for at very high N is FILE COUNT, not prime count: a
    floor with many thousands of small window files costs far more
    wall-clock load time than one with a few large ones holding the same
    total prime count. (The renderer itself handles ~20,000,000 rings at 50+ fps;
    that measures rendering, not this loader's I/O.)

    `prime_sieve` (this repo's sibling top-level directory to `primeatlas/`)
    is added to sys.path here because primeatlas.core.storage itself does a bare
    `import prime_sieve_v1` / `import window_sharding` (see storage.py's own
    module docstring for why those two live as separate top-level modules
    rather than inside this package)."""
    prime_sieve_dir = os.path.join(_REPO_ROOT, "prime_sieve")
    if prime_sieve_dir not in sys.path:
        sys.path.insert(0, prime_sieve_dir)
    from primeatlas.core import storage
    import prime_sieve_v1

    chunks = []
    total_loaded = 0

    # Materialized (not a lazy generator) so a floor's NEXT exponent is
    # available while looking at the current one -- gives a cheap, exact
    # "is this whole floor already below from_n" check without opening a
    # single file, for every floor except the one that actually straddles
    # from_n (at most one wasted full floor-listing in the worst case, none
    # in the common case of extending near the top).
    floor_exponents = list(storage.list_floors(portal_folder))
    for floor_index, base_exponent in enumerate(floor_exponents):
        floor_lo = 10 ** base_exponent if base_exponent > 0 else 0
        if floor_lo > upto:
            break
        if floor_index + 1 < len(floor_exponents):
            floor_hi_exclusive = 10 ** floor_exponents[floor_index + 1]
            if floor_hi_exclusive <= from_n:
                continue

        entries = storage.list_source_filenames(portal_folder, base_exponent)
        if not entries:
            continue

        files_read_in_floor = 0
        floor_done = False
        for batch_start in range(0, len(entries), batch_files):
            batch = entries[batch_start:batch_start + batch_files]
            batch_chunks = []
            for name, path in batch:
                window_primes = prime_sieve_v1.read_prime_window(path)
                # A hardcoded `dtype=np.int64` here overflows on a real
                # floor 25/27 window (~10**25-10**27 magnitude, see
                # to_prime_array's own doc-comment) -- window files below
                # the uint64 ceiling (the overwhelming majority of a
                # archive) still get the exact same fast native array as
                # before; only a window whose values actually exceed it
                # pays the `object`-dtype cost, and only for that one
                # window's own `chunks` entry --
                # np.concatenate below promotes the WHOLE result to `object`
                # automatically if and only if at least one chunk needed it
                # (see numpy's own dtype-promotion rules), so a from_n/upto
                # query confined to low floors never pays anything extra.
                arr = to_prime_array(window_primes)
                files_read_in_floor += 1
                if arr.size and arr[0] > upto:
                    floor_done = True
                    break
                trimmed = arr[(arr > from_n) & (arr <= upto)]
                if max_load_count is not None and trimmed.size:
                    remaining = max_load_count - total_loaded
                    if remaining <= 0:
                        trimmed = trimmed[:0]
                    elif trimmed.size > remaining:
                        trimmed = trimmed[:remaining]
                if trimmed.size:
                    batch_chunks.append(trimmed)
                    total_loaded += int(trimmed.size)
                if arr.size and arr[-1] >= upto:
                    floor_done = True
                    break
                if max_load_count is not None and total_loaded >= max_load_count:
                    floor_done = True
                    break

            if batch_chunks:
                chunks.append(batch_chunks[0] if len(batch_chunks) == 1 else np.concatenate(batch_chunks))
            if progress_callback is not None:
                progress_callback(base_exponent, files_read_in_floor, total_loaded)
            if floor_done:
                break
        if max_load_count is not None and total_loaded >= max_load_count:
            break

    if not chunks:
        return np.empty(0, dtype=np.uint64)
    result = np.concatenate(chunks)
    result.sort()
    return result


def load_archive_before(portal_folder, before_n, count, not_below=None):
    """Backward-walking counterpart to load_archive(): the `count` largest
    real primes strictly LESS than `before_n` (ascending order), or fewer if
    the portal's own data runs out first. The sliding window's chunk_back loader
    (forward sliding uses load_archive(from_n=...)).

    `before_n` is EXCLUSIVE, mirroring load_archive's own `from_n`
    exclusivity (`arr > from_n`) -- so a chunk_back ending here and a
    chunk_current starting at the same `before_n` boundary never duplicate
    or gap a value at the seam.

    `not_below` -- None (default) walks back toward the start of the portal's
    data. The sliding window passes its `range_load_from`
    (RenderSession._ensure_back_chunk), making FROM a hard boundary: the function
    never returns a value `<= not_below` and stops at the floor containing it.
    Without it, a --load-range starting high (e.g. floor 24) with floors 0-23 also
    populated would walk earlier floors on every backward slide, one disk load
    after another. Same treatment of FROM as the first chunk's initial load
    (renderer.py's `from_n=preload_from`).

    Gap-encoded PGS2 windows have no random access (same limitation
    hit_paging.py's own docstring and load_archive's own module docstring
    already document elsewhere), so getting the LAST `count` values below a
    boundary still means fully decoding whole window files -- but only the
    ones actually needed, walked from the boundary backward, using the same
    cheap "list filenames (no I/O), binary-search headers (small I/O),
    decode only what's needed" pattern storage.find_prime_in_floor and the paged
    constellation search use:

    1. storage.list_floors() to find which floor `before_n` falls in (or
       the nearest floor below it, if `before_n` lands exactly on a floor's
       own lower bound -- that floor itself can then contribute nothing).
    2. Within that one floor, storage.list_source_filenames() (cheap, no
       I/O) + a binary search over prime_sieve_v1.read_prime_window_header's
       base_prime (cheap header peek, not a full decode) to find the
       rightmost window whose base_prime is still < before_n -- every
       window after it has base_prime >= before_n, hence EVERY value in it
       is >= before_n too (windows are non-overlapping and base_prime is
       each window's own minimum), so those can be skipped without opening
       them at all.
    3. Full-decode (prime_sieve_v1.read_prime_window) windows one at a time,
       walking backward, masking each to `< before_n` (a no-op for every
       window except the one straddling the boundary), until `count` values
       are collected or the floor's own first window is exhausted.
    4. If `count` still isn't reached, cross into the PREVIOUS floor
       (storage.list_floors() again) and continue -- exact mirror of how
       load_archive crosses floors forward.

    Deliberately no `batch_files`-style batched intermediate accumulation
    like load_archive's own (that exists there because a single forward
    call can span an effectively unbounded number of files across a huge
    upto-from_n span) -- a backward call is inherently bounded by `count`
    itself (the loop stops the moment enough values are collected), so the
    number of files ever opened here is already bounded the same way
    load_archive's own final partial-window read is: by need, one file at a
    time, no wasted over-read past what `count` actually requires."""
    if count <= 0 or before_n <= 0:
        return np.empty(0, dtype=np.uint64)
    prime_sieve_dir = os.path.join(_REPO_ROOT, "prime_sieve")
    if prime_sieve_dir not in sys.path:
        sys.path.insert(0, prime_sieve_dir)
    from primeatlas.core import storage
    import prime_sieve_v1

    def _safe_base_prime(path):
        try:
            return prime_sieve_v1.read_prime_window_header(path)["base_prime"]
        except Exception:
            return None

    floor_exponents = list(storage.list_floors(portal_folder))
    floor_index = -1
    for i, base_exponent in enumerate(floor_exponents):
        floor_lo = 10 ** base_exponent if base_exponent > 0 else 0
        if floor_lo < before_n:
            floor_index = i
        else:
            break
    if floor_index == -1:
        return np.empty(0, dtype=np.uint64)

    collected = []
    total = 0
    idx = floor_index
    while idx >= 0 and total < count:
        base_exponent = floor_exponents[idx]
        # `not_below`'s own hard-boundary check: once THIS floor's own
        # lower edge is already at or below it, there is nothing left
        # worth looking at past this floor -- see this function's own
        # doc-comment for why walking further was the actual bug.
        floor_lo = 10 ** base_exponent if base_exponent > 0 else 0
        floor_is_last = not_below is not None and floor_lo <= not_below

        entries = storage.list_source_filenames(portal_folder, base_exponent)
        if entries:
            if idx == floor_index:
                lo, hi = 0, len(entries) - 1
                best = -1
                while lo <= hi:
                    mid = (lo + hi) // 2
                    bp = _safe_base_prime(entries[mid][1])
                    if bp is None and mid + 1 <= hi:
                        mid += 1
                        bp = _safe_base_prime(entries[mid][1])
                    if bp is None:
                        hi = mid - 1
                        continue
                    if bp < before_n:
                        best = mid
                        lo = mid + 1
                    else:
                        hi = mid - 1
                start_file_index = best
            else:
                start_file_index = len(entries) - 1

            file_index = start_file_index
            while file_index >= 0 and total < count:
                _, path = entries[file_index]
                arr = to_prime_array(prime_sieve_v1.read_prime_window(path))
                if not_below is not None:
                    trimmed = arr[(arr < before_n) & (arr > not_below)]
                else:
                    trimmed = arr[arr < before_n]
                if trimmed.size:
                    collected.append(trimmed)
                    total += int(trimmed.size)
                file_index -= 1

        if floor_is_last:
            break
        idx -= 1

    if not collected:
        return np.empty(0, dtype=np.uint64)
    result = np.concatenate(list(reversed(collected)))
    result.sort()
    if result.size > count:
        result = result[-count:]
    return result
