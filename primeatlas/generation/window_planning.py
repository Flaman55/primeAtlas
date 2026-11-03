"""
window_planning.py -- window and floor arithmetic for the Generation tab: which windows of a
floor already exist in an engine's store (continuation point, first gap, edge trimming),
rounding and splitting a requested range into whole windows and per-floor launches, the
one-window Hybrid targets, totals-cache bumps from new benchmark rows, and the engine
range limits (primesieve/CUDASieve uint64 ceiling) the planning respects.

Pure logic, no tkinter: covered by unitTests/test_generation_window_arithmetic.py,
unitTests/test_generation_launch_planning.py and unitTests/test_storage_fill.py.
"""
import storage_kinds

from ..core.storage import LOW_FLOOR_CUTOFF, list_floors, list_source_filenames
from . import engine_options


QUICK_GEN_MAX_WINDOW_WIDTH = 10_000_000  # window width Quick-gen's range ->
                          # window_count_per_run translation must not exceed.
                          #
                          # NOTE: this constant ASSUMES window_m=10,000,000, matching the
                          # editable "window_m" field on the low-level form (see
                          # add_loop_field(3, 0, "window_m", ...) and build_loop_argv()).
                          # Quick-gen does NOT read the value from that form field -- if
                          # window_m is ever changed there, the Range/Floor/Exploration
                          # math below will silently stop matching what
                          # orchestrator_loop_v2.py actually scans. Safe as long as
                          # window_m stays at its default value (as in
                          # DEFAULT_GENERATION_SETTINGS) -- not fixed here, only noted as
                          # a known limitation.
                          #
                          # Exploration's per-iteration width is its own Width spinbox
                          # ([1, 1000]) x QUICK_GEN_MAX_WINDOW_WIDTH, same meaning as
                          # Floor only's, so the per-iteration memory footprint follows
                          # what the machine has.


def compute_totals_bumps_from_new_rows(rows, before_count):
    """Pure logic behind GenerationTab._bump_totals_from_finished_run() (see that
    method's own docstring for the full feature rationale -- storage.py's persisted
    totals cache, updated incrementally instead of by a full per-floor rescan). `rows`
    is benchmark_log.csv's own row list (read_benchmark_log()'s second return value,
    each row a plain dict of strings -- csv.DictReader's own shape), `before_count` is
    how many rows existed right before the just-finished run started (see
    GenerationTab.__init__'s own comment on self._benchmark_rows_before_run).

    Returns a list of (base_exponent, delta_count, delta_file_count, delta_bytes)
    tuples, one per NEW row (rows[before_count:]) that both (a) has write_files == "1"
    -- a count-only benchmark run logs a real total_primes number too, but wrote
    nothing to disk, so it must never be folded into a total that's supposed to track
    real files -- and (b) parses cleanly as integers; a malformed/legacy row (missing
    a column that predates it, non-numeric field) is skipped rather than raising, same
    defensive stance load_totals_cache() takes toward a corrupt cache file. A
    genuinely-zero delta (delta_count == delta_file_count == delta_bytes == 0) is also
    dropped -- nothing changed, no reason to touch the cache over it.

    Pulled out as its own pure function (no cache/disk I/O of its own) purely so this
    row-filtering/parsing logic is unit-testable without constructing a real
    GenerationTab/tkinter widget or a real benchmark_log.csv on disk -- the same
    "extract the decision logic, keep the I/O at the edges" convention this package
    already uses for primes_tab.py's _cumulative_floor_totals()/benchmark_tab.py's
    _hover_label_position().

    The bumped totals are the D store's (storage_kinds.py). A pt1 row on a floor reaching
    MR_DET_BOUND (floor 24 and up) wrote P windows, or a mix on floor 24, so it is skipped:
    P totals come from the P store's rescan (update_floor_totals_cache(kind="P"))."""
    bumps = []
    for row in rows[before_count:]:
        if row.get("write_files") != "1":
            continue
        try:
            base_exponent = int(row["base_exponent"])
            if (row.get("engine") == storage_kinds.ENGINE_PT1
                    and 10 ** (base_exponent + 1) > storage_kinds.MR_DET_BOUND):
                continue
            delta_count = int(row["total_primes"])
            delta_file_count = int(row["windows_written"])
            delta_bytes = int(row.get("bytes_written") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if delta_count == 0 and delta_file_count == 0 and delta_bytes == 0:
            continue
        bumps.append((base_exponent, delta_count, delta_file_count, delta_bytes))
    return bumps


def count_existing_windows(portal_folder, base_exponent):
    """Real count of window FILES actually on disk for this floor -- len(list_source_
    filenames(...)), nothing more. Distinct from find_continuation_target_idx()'s
    CONTINUATION POINT (highest existing target_idx + 1), which only equals the real
    file count on a floor with zero gaps -- once direct-start writes made genuine
    interior gaps possible (see find_first_gap_target_idx()'s own docstring), the two
    numbers can diverge arbitrarily, and the continuation point alone is meaningless as
    a "how much do I actually have" figure for a person to read.
    This function is for DISPLAY ONLY -- every launch/continuation decision must keep
    using find_continuation_target_idx() (or find_first_gap_target_idx() for the gap-
    fill strategy), since those need the highest-existing-POSITION semantics, not a
    plain count, to know where generation can safely resume. Proportional to the real
    file count via list_source_filenames()'s own os.listdir() (cheap even at thousands
    of files per floor), never to the numeric magnitude of the floor itself."""
    return len(list_source_filenames(portal_folder, base_exponent))


def _engine_idxs(portal_folder, base_exponent, window_m, engine):
    return storage_kinds.engine_target_idxs(portal_folder, base_exponent, window_m,
                                            engine or engine_options.DEFAULT_ENGINE)


def find_continuation_target_idx(portal_folder, base_exponent, window_m, engine=None):
    """The target_idx orchestrator_v3.find_auto_start() continues this floor from with
    `engine` (default: the default engine): one past the highest window of the store that
    engine writes into (storage_kinds.engine_target_idxs()), 0 if there is none. Pure
    Python on filenames: this native-Windows app never imports the WSL engine modules."""
    idxs = _engine_idxs(portal_folder, base_exponent, window_m, engine)
    return max(idxs) + 1 if idxs else 0


def find_first_gap_target_idx(portal_folder, base_exponent, window_m, engine=None):
    """The target_idx of the FIRST window missing from `engine`'s store on this floor (0 if
    nothing exists yet) -- where a 'fill gaps first' continuation starts, as opposed to
    find_continuation_target_idx()'s 'extend past the highest existing window'. Equal to it
    when the floor has no gap. Walks the existing windows, never the numeric range, so a
    window written deep into an otherwise empty floor costs nothing."""
    idxs = _engine_idxs(portal_folder, base_exponent, window_m, engine)
    expected = 0
    while expected in idxs:
        expected += 1
    return expected


def _trim_existing_from_target_idx_range(portal_folder, base_exponent, target_idx_start,
                                          window_count, window_m, engine=None):
    """Shrinks [target_idx_start, target_idx_start + window_count) to skip the windows of
    `engine`'s store that ALREADY exist at its front and back edges: every engine
    overwrites unconditionally, so a request overlapping generated windows would re-sieve
    them for nothing. Interior existing windows are rewritten with identical content (one
    launch per request, not per gap).

    Returns (trimmed_start, trimmed_count) -- trimmed_count is 0 (trimmed_start
    meaningless) if the ENTIRE requested range turns out to already exist."""
    existing = _engine_idxs(portal_folder, base_exponent, window_m, engine)
    start = target_idx_start
    end = target_idx_start + window_count  # exclusive
    while start < end and start in existing:
        start += 1
    while end > start and (end - 1) in existing:
        end -= 1
    return start, max(0, end - start)


def find_highest_populated_floor(portal_folder, engine=None):
    """Highest base_exponent with at least one window in a store `engine` writes into (D
    for the sieve engines, D or P for pt1); an empty or leftover 10p{N} folder doesn't
    count. None if nothing has been generated anywhere yet.

    Used by Exploration mode's blank-Floor auto-continue (see _build_quick_mode_explore's
    docstring): repeatedly clicking Generate with Floor left blank keeps extending the
    deepest data. Floors are checked from the highest down, stopping at the first hit."""
    engine = engine or engine_options.DEFAULT_ENGINE
    kinds = storage_kinds.KINDS if engine == storage_kinds.ENGINE_PT1 else (storage_kinds.KIND_D,)
    for base_exponent in reversed(list_floors(portal_folder)):
        if any(storage_kinds.list_window_files(portal_folder, base_exponent, kind)
               for kind in kinds):
            return base_exponent
    return None


def _round_range_to_window(start, end, window=QUICK_GEN_MAX_WINDOW_WIDTH):
    """Range from/to quick-gen mode: the on-disk window format doesn't change here either,
    so a requested [start, end) span is always widened out to whole `window`-sized chunks
    -- start rounded DOWN to the nearest multiple, end rounded UP -- so generation never
    falls short of what was asked for. Example: 12,000,000..309,000,000 ->
    10,000,000..310,000,000 (window=10,000,000). Plain floor/ceil division; a start or
    end that's already an exact multiple is left unchanged."""
    rounded_start = (start // window) * window
    rounded_end = -(-end // window) * window  # ceiling division without importing math
    return rounded_start, rounded_end


def plan_hybrid_narrow_range(start, end, window=QUICK_GEN_MAX_WINDOW_WIDTH):
    """Classify a literal request for the one-window Hybrid experiment.

    Storage always receives complete standard windows.  Hybrid is deliberately
    limited to exactly one such window; a wider rounded request must use the
    normal Range/v4.1 pipeline instead of pretending to be a scalable engine.
    """
    if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
        raise ValueError("hybrid range must be a non-empty non-negative interval")
    rounded_start, rounded_end = _round_range_to_window(start, end, window)
    return {
        "rounded_start": rounded_start,
        "rounded_end": rounded_end,
        "use_hybrid": rounded_end - rounded_start == window,
    }


def hybrid_window_for_number(number, window=QUICK_GEN_MAX_WINDOW_WIDTH):
    """Canonical one-window Hybrid target containing a concrete integer ``n``."""
    if not isinstance(number, int) or number < 0:
        raise ValueError("n must be a non-negative integer")
    floor = len(str(number)) - 1
    if floor < LOW_FLOOR_CUTOFF:
        start = 10 ** floor
        return start, 10 ** (floor + 1)
    start = (number // window) * window
    return start, start + window


def hybrid_window_for_floor_index(floor, target_idx, window=QUICK_GEN_MAX_WINDOW_WIDTH):
    """Canonical absolute window selected by an Atlas floor/index coordinate."""
    if not isinstance(floor, int) or not isinstance(target_idx, int) or floor < 0 or target_idx < 0:
        raise ValueError("floor and target_idx must be non-negative integers")
    if floor < LOW_FLOOR_CUTOFF:
        if target_idx != 0:
            raise ValueError("low floors have exactly one whole-floor output window")
        return 10 ** floor, 10 ** (floor + 1)
    start = 10 ** floor + target_idx * window
    return start, start + window


def _floor_window_count(base_power, window=QUICK_GEN_MAX_WINDOW_WIDTH):
    """How many `window`-sized windows fit EXACTLY within floor base_power's own numeric
    domain [10**base_power, 10**(base_power+1)) -- i.e. target_idx 0..(this value - 1) are
    the only valid window positions for this floor; target_idx >= this value would spill
    into the NEXT floor's numbers. Returns None for base_power < LOW_FLOOR_CUTOFF -- a low
    floor is narrower than one window and handled by its own single-window completion path
    instead (see LOW_FLOOR_CUTOFF), so "how many windows fit" isn't the right question
    there. For base_power >= LOW_FLOOR_CUTOFF the floor's width (9 * 10**base_power) is
    ALWAYS an exact multiple of `window` (both sides are powers of 10 at or above 10**7),
    so this division never has a remainder to worry about -- e.g. floor 7 -> 9 windows
    (target_idx 0..8), floor 8 -> 90 windows, and so on.

    Caps a floor-only/range request's window_count_per_run so target_idx never passes
    the floor's own boundary; otherwise the next floor's numbers would be written into
    this floor's folder, labeled as this floor (e.g. floor 7 past its 9th window). See
    _quick_gen_plan_literal_range and _on_quick_generate_clicked's blank-starting-point
    Floor branch for where this is applied -- Exploration mode deliberately does NOT use
    this (see that branch's own comment)."""
    if base_power < LOW_FLOOR_CUTOFF:
        return None
    return (9 * 10 ** base_power) // window


def recommended_digit_sweep_n_locations(base_exponent, window_m, target_windows_per_branch=40):
    """Mirrors ktuple_locations_v2_2.digit_sweep_positions()'s own p_min search (duplicated,
    not imported -- that module runs standalone inside WSL, this native-Windows GUI
    process must not depend on it, same "duplicated rather than imported" pattern
    as PRIMESIEVE_MAX_STOP below).

    The shared 1000-window default leaves each individual digit branch only ~4-5
    windows deep (40M numbers) under a per-POSITION reading of n_locations ("1000
    windows / 25 positions = 40 per position"), versus the ~40-window (400M number)
    depth the same arithmetic gives under a per-BRANCH reading, split across its ~10
    branches. Rather than silently pick one interpretation, this recommends an
    n_locations big enough that BOTH readings coincide: every position still gets
    swept in the SAME batch (the whole floor's magnitude range examined at once), and
    every digit branch within it gets close to `target_windows_per_branch` windows.

    Returns the recommended n_locations (an int) -- a plain suggestion, like every
    other Auto button in this app; the field stays freely editable afterward."""
    p_min = 0
    while 10 ** p_min < window_m:
        p_min += 1
    positions = [p for p in ([base_exponent] + list(range(base_exponent - 1, p_min - 1, -1)))
                 if p >= 0]
    total = 0
    for p in positions:
        n_digit_values = 9 if p == base_exponent else 10
        total += n_digit_values * target_windows_per_branch
    return total


# The uint64_t ceiling libprimesieve itself enforces (primesieve_get_max_stop(), which
# always returns exactly 2**64 - 1) -- duplicated here, not imported, for the same reason
# LOW_FLOOR_CUTOFF and QUICK_GEN_MAX_WINDOW_WIDTH are duplicated rather than imported: this
# native-Windows GUI process must not depend on prime_sieve_primesieve.py's ctypes/WSL-only
# libprimesieve binding just to know a fixed, extremely stable numeric constant. Used only
# to decide whether to show a pre-flight truncation note before launching -- the actual
# clamp is entirely backend-side (prime_sieve_primesieve.py's own live
# primesieve_get_max_stop() call), so this staying correct is not safety-critical, only
# cosmetic (a stale value here would at worst show/skip the note a run late).
PRIMESIEVE_MAX_STOP = 2 ** 64 - 1


def plan_storage_fill(start, end, window=QUICK_GEN_MAX_WINDOW_WIDTH, primesieve_max_stop=PRIMESIEVE_MAX_STOP):
    """Plans filling the literal range [start, end) into storage, across as many floors
    as it touches, as (floor, target_idx_start, window_count) launches in ascending order
    for a target_idx-capable engine (GenerationTab._launch_direct_window_range).

    Everything below 10**LOW_FLOOR_CUTOFF is ONE launch, (0, 0, 1): every engine splits
    a low-floor window starting at 10**0 into the real floors 0..6 itself. From floor
    LOW_FLOOR_CUTOFF on, each floor touched gets [max(start, 10**f), min(end,
    10**(f+1))) rounded out to whole windows -- never past the floor's own upper edge,
    since 10**f is a multiple of `window` there. A floor straddling the primesieve
    ceiling is split at the last window lying wholly under it, so primesieve covers
    what it can and only the rest goes to the engine without that limit (the dispatch
    decides per launch). An empty or inverted request plans nothing."""
    start = max(start, 1)
    if end <= start:
        return []
    launches = []
    low_top = 10 ** LOW_FLOOR_CUTOFF
    if start < low_top:
        launches.append((0, 0, 1))
        start = low_top
    floor = len(str(start)) - 1
    while start < end and 10 ** floor < end:
        base = 10 ** floor
        lo = max(start, base)
        hi = min(end, 10 ** (floor + 1))
        idx_start = (lo - base) // window
        idx_end = -(-(hi - base) // window)
        split = (primesieve_max_stop + 1 - base) // window
        if idx_start < split < idx_end:
            launches.append((floor, idx_start, split - idx_start))
            launches.append((floor, split, idx_end - split))
        else:
            launches.append((floor, idx_start, idx_end - idx_start))
        floor += 1
    return launches

# Width (multiplier of QUICK_GEN_MAX_WINDOW_WIDTH) spinbox bound for primesieve mode --
# deliberately NOT the [1, 1000] cap every other mode's Width field uses (that cap exists
# because those engines pay a real RAM cost of window_count * window_width / 8 bytes for a
# combined shared buffer -- see README's "Window count, throughput, and RAM"). primesieve
# mode has no such buffer (see prime_sieve_primesieve.py's module header); its only real
# limit is libprimesieve's own uint64 ceiling, so the Width field is allowed to reach far
# enough to cover the WHOLE library range from floor 0's own start -- one extra window of
# headroom rounds this comfortably past PRIMESIEVE_MAX_STOP // QUICK_GEN_MAX_WINDOW_WIDTH.
PRIMESIEVE_MAX_WIDTH_MULT = PRIMESIEVE_MAX_STOP // QUICK_GEN_MAX_WINDOW_WIDTH + 1


# Duplicated from prime_sieve_cudasieve.py's own MIN_PRINTABLE_TOP -- CUDASieve's own CLI
# documents that its -p/--print flag "will be ignored below 2**40", so this mode can never
# usefully list individual primes below that value. Checked here too (not just backend-side)
# so a doomed request is rejected before paying a WSL round-trip, exactly like
# PRIMESIEVE_MAX_STOP's own pre-flight check above.
CUDASIEVE_MIN_PRINTABLE_TOP = 2 ** 40

# CUDASieve's own --help text documents examples up to 2**64 (e.g. "-b 2**64-2**35-2**30 -t
# 2**64-2**35") -- same uint64_t domain as libprimesieve's own PRIMESIEVE_MAX_STOP, so the
# same ceiling/truncation-note logic applies.
CUDASIEVE_MAX_STOP = 2 ** 64 - 1
CUDASIEVE_MAX_WIDTH_MULT = CUDASIEVE_MAX_STOP // QUICK_GEN_MAX_WINDOW_WIDTH + 1
