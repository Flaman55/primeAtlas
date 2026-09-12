"""
sources.py -- ring-array data sources for primeatlas/ring_viz/renderer.py:
load_synthetic, load_sieve, load_magazyn. [ADDED Faza 1 of the renderer.py
split, see that file's own module docstring for the overall refactor plan.]

Kept independent of moderngl/glfw and of renderer.py's own GL-context state
-- see renderer.py's own module docstring, data-source point 1, for why
these three loaders are deliberately interchangeable and decoupled from the
rendering path: --source picks which one runs, and all three return a plain
ascending prime/ring array (to_prime_array's own uint64-or-object dtype
choice) that the rest of the renderer treats identically regardless of
where it came from.

Self-contained sys.path bootstrap (mirrors renderer.py's own, see that
file's module docstring for the full "why plain-script-path" explanation):
needed so `import prime_sieve_v1` / `from primeatlas import storage` inside
load_magazyn work whether this module is imported after renderer.py has
already run its own bootstrap, or on its own (e.g. directly from a test).
"""

import os
import sys

import numpy as np

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_PRIME_SIEVE_DIR = os.path.join(_REPO_ROOT, "prime_sieve")
if _PRIME_SIEVE_DIR not in sys.path:
    sys.path.insert(0, _PRIME_SIEVE_DIR)

from primeatlas.ring_geometry import to_prime_array


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
    intended for anything near magazyn scale; use --source magazyn for that).
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


def load_magazyn(portal_folder, upto, progress_callback=None, batch_files=64, from_n=0,
                  max_load_count=None):
    """Reads real primes in (from_n, upto] from an existing PrimeAtlas
    portal folder, via primeatlas.storage's own file-listing helpers and
    prime_sieve_v1.read_prime_window for the actual decode.

    [ADDED `max_load_count`, Artur 2026-09-12: "przyjac wartosc startowa i
    ilosc pierscieni jakie wchodza do zakresu ... od-do i drugi parametr
    dowolny zakres pierscieni ... jesli ... wiecej niz jakis prog ... zakres
    od gory jest ciety do ilosci limitu"] Optional hard cap on how many
    primes this call ever materializes. Enforced as an early stop (mirrors
    the existing `floor_done` break just below) rather than a post-hoc
    `result[:max_load_count]` slice, so a huge `(from_n, upto]` span --
    the whole point of `from_n` jumping straight to a high floor -- never
    reads a single file more than needed once the cap is hit. Truncation is
    always from the TOP (the highest values get cut, exactly as Artur
    asked), a natural consequence of floors/files being walked in ascending
    order already. `None` (default) reproduces the old unbounded behavior
    exactly. No fixed number is hardcoded here on purpose -- see this
    function's own REAL CEILING note below: nobody has benchmarked a safe
    figure on real magazyn hardware yet, so the caller (rings_tab.py) makes
    this a plain configurable field instead of a guessed constant.

    [ADDED `from_n`, Artur 2026-09-11: "bufor bedzie podrozowal wraz z n z
    wyprzedzeniem"] Defaults to 0, i.e. every real prime is >0 so this
    reproduces the exact old `arr[arr <= upto]` behavior unchanged when the
    caller doesn't pass it. A non-zero `from_n` lets a caller that already
    holds every prime up to some point (extend_buffer_if_needed in
    _run_visualization, renderer.py) fetch only the NEW primes past that
    point instead of re-reading and re-returning the whole [0, upto] range
    again -- two cheap wins over a naive "just call load_magazyn(new_upto)
    again" approach: (1) whole floors entirely below `from_n` are skipped
    without even listing their files (see the floor_hi_exclusive check
    below), and (2) within the one floor spanning `from_n`, files are still
    opened (no per-file range metadata to skip them by name alone) but
    their already-covered primes are trimmed out before being added to the
    result, so nothing already known gets duplicated into the array.

    HARDENED (Faza 2, see PLAN.md) vs the Faza-0 landing of the original
    feasibility prototype's loader, in three ways:

    1. Enumerates REAL floors on disk via storage.list_pietra() instead of
       blindly incrementing floor with only a fixed sanity cap (`floor > 30`)
       as a guard. A gap in the portal (e.g. floor 5 populated, floor 6 not
       yet) no longer costs an empty list_source_filenames() call for every
       skipped floor, and a portal whose highest real floor is well below
       `upto`'s own floor stops there immediately instead of still counting
       up toward the old hardcoded 30 regardless.
    2. Reads window files in BOUNDED BATCHES (`batch_files` at a time,
       default 64) rather than accumulating one unbounded Python list across
       an entire floor (or several floors) before ever concatenating -- see
       this project's own `c_skaner_odczyt_porcjami` history (04_C_skaner
       once failed the whole sieve, without warning, from a single ~1GB
       fread instead of reading in ~160MB portions) for the class of failure
       an unbounded single pass caused elsewhere in this codebase. Each
       batch is concatenated and appended to the running result list right
       away, so peak EXTRA memory during the load is bounded by one batch's
       worth of arrays, not the whole load -- the final full-array
       concatenate at the end is unavoidable (the renderer needs one
       contiguous sorted array to hand to ring_geometry), but the batching
       here at least keeps the INTERMEDIATE working set bounded.
    3. Accepts an optional `progress_callback(base_exponent, files_read_in_floor,
       primes_loaded_so_far)`, invoked after every batch, so a caller
       (primeatlas/rings_tab.py, Faza 3) can drive a real progress bar
       instead of a frozen GUI during what can be a multi-second load at
       real magazyn scale. Deliberately NOT trying to make the load itself
       faster (see this module's own docstring, data-source point 1, for why
       generation/read throughput is explicitly out of scope for this
       feature to optimize) -- only making the existing cost observable and
       boundable instead of an opaque hang.

    REAL CEILING (documented per PLAN.md's Faza 2 ask): NOT benchmarked here
    -- this sandbox has no real magazyn data or GPU to measure against. The
    rendering ceiling already confirmed on Artur's real hardware is
    20,000,000 rings at 50+ fps (see PLAN.md's "Feasibility already
    confirmed" section); this loader's own cost is dominated by per-file
    open() latency on the FUSE-mounted storage drive (~5ms/file -- the same
    figure storage.update_pietro_totals_cache()'s own docstring measured on
    this exact drive), not the PGS decode work itself. That means the real
    bottleneck to watch for at very high N is FILE COUNT, not prime count: a
    floor with many thousands of small window files costs far more
    wall-clock load time than one with a few large ones holding the same
    total prime count. Artur should measure the real number on his own
    hardware once Faza 3's tab exists to launch this against a real
    magazyn -- this docstring intentionally does not claim a number this
    sandbox cannot verify.

    `prime_sieve` (this repo's sibling top-level directory to `primeatlas/`)
    is added to sys.path here because primeatlas.storage itself does a bare
    `import prime_sieve_v1` / `import window_sharding` (see storage.py's own
    module docstring for why those two live as separate top-level modules
    rather than inside this package)."""
    prime_sieve_dir = os.path.join(_REPO_ROOT, "prime_sieve")
    if prime_sieve_dir not in sys.path:
        sys.path.insert(0, prime_sieve_dir)
    from primeatlas import storage
    import prime_sieve_v1

    chunks = []
    total_loaded = 0

    # [ADDED, see `from_n` doc above] Materialized (not a lazy generator)
    # so a floor's NEXT exponent is available while looking at the current
    # one -- gives a cheap, exact "is this whole floor already below from_n"
    # check without opening a single file, for every floor except the one
    # that actually straddles from_n (at most one wasted full floor-listing
    # in the worst case, none in the common case of extending near the top).
    floor_exponents = list(storage.list_pietra(portal_folder))
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
                # [FIXED 2026-09-12, Artur's report: OverflowError loading a
                # real piętro 25/27 window (~10**25-10**27 magnitude, see
                # to_prime_array's own doc-comment)] was the old hardcoded
                # `dtype=np.int64` here -- window files below the uint64
                # ceiling (the overwhelming majority of a magazyn) still get
                # the exact same fast native array as before; only a window
                # whose values actually exceed it pays the `object`-dtype
                # cost, and only for that one window's own `chunks` entry --
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
