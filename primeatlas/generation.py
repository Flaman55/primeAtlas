"""
generation.py -- pure-logic (no tkinter) backend for the Generation tab: window/floor
arithmetic, generation-settings persistence, WSL argv builders for every engine this app
launches (orchestrator_loop_v2.py, prime_sieve_primesieve.py, hybrid_sieve.py,
orchestrator_v3.py direct, constellation_finder_v1.py, ktuple_sieve_v1.py), the file-tailing WSL/local subprocess
runners (WslLoggedRunner/LocalLoggedRunner), and the WSL RAM/CPU-probing helpers used by
the Quick-gen panel's "Auto" suggestions.

Extracted from prime_atlas_v1.py during the refactor branch's Faza 3 (tab-by-tab
backend/UI split, 2026-08-23), alongside the tab's own UI split (see generation_tab.py's
own docstring). This is the single largest of the five tab extractions -- the Generation
tab launches every generation/search engine in the app and is the one most already
covered by dedicated regression tests (see unitTests/test_generation_window_arithmetic.py
and unitTests/test_generation_launch_planning.py, written in this same Faza 3 pass
specifically to catch the three documented historical bugs living in this arithmetic:
floor-25 MemoryError, floor-7-130M-numbers boundary bug, 1001-windows-for-1000 off-by-one).

build_primesieve_query_argv()/run_primesieve_query_wsl() deliberately did NOT move here
even though they sit in the same original file region -- they belong to the UNRELATED
"primesieve" calculator sub-tab (Liczby pierwsze -> primesieve), not this tab; see
prime_atlas_v1.py's own copy of those two functions.

build_wsl_logged_command() below takes an explicit `portal_folder` argument instead of
reading a bare PORTAL_FOLDER module global the way its original in-file version did (see
prime_atlas_v1.py's own APP_SETTINGS/PORTAL_FOLDER comment for why every function there
reads that name at CALL time) -- this module has no such mutable global of its own
(PORTAL_FOLDER only ever changes via _set_portal_folder's `global PORTAL_FOLDER` rebind,
which is prime_atlas_v1.py's own module namespace, not this one), so the only way to keep
every WSL launch honoring a live storage-path change is to have the caller (GenerationTab,
which already receives get_portal_folder() by injection like every other extracted tab)
pass the CURRENT value in explicitly at each call site.
"""
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time

from .storage import LOW_FLOOR_CUTOFF, list_pietra, list_source_filenames, _offset_from_filename

_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# One level up from THIS file's own directory (primeatlas/) -- prime_atlas_v1.py's
# original _SCRIPT_DIR pointed at the repo root (where it itself lives, alongside the
# prime_sieve/ and constellation/ directories the script-path constants below resolve
# into); this module lives one directory deeper, in primeatlas/, so it needs the extra
# dirname() hop to land on the same repo root.


QUICK_GEN_MAX_WINDOW_WIDTH = 10_000_000  # window width the (future) range ->
                          # window_count_per_run translation logic must not exceed. Not
                          # used yet -- interface-only step, logic follows in a later
                          # change; kept here as the single source of truth for that
                          # upcoming calculation.
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
                          # Exploration's per-iteration width used to be a fixed
                          # 10,000,000,000 (QUICK_GEN_EXPLORE_ITERATION_WIDTH, since
                          # removed) -- it now has its own Width spinbox, same [1, 1000]
                          # x QUICK_GEN_MAX_WINDOW_WIDTH meaning as Floor only's, so the
                          # per-iteration memory footprint scales with what the machine
                          # actually has rather than being pinned to one fixed size.

# LOW_FLOOR_CUTOFF/list_pietra/list_source_files/_OFFSET_FROM_NAME_RE/_offset_from_filename/
# list_source_filenames moved to primeatlas/storage.py during the refactor branch's Faza 3
# (tab-by-tab backend/UI split, 2026-08-23), alongside the "Prime numbers" tab's own UI split
# (primeatlas/primes_tab.py) -- see that module's own docstring for why this whole layer
# moved together rather than only the pieces the Primes tab itself needs. All five names are
# imported back at this file's top, unchanged, for every other tab that also calls them.

# BENCHMARK_TREE_HIDDEN_COLUMNS/BENCHMARK_PAGE_SIZE/_order_benchmark_tree_columns moved to
# primeatlas/benchmark.py during the refactor branch's Faza 3 (tab-by-tab backend/UI split,
# 2026-08-23), alongside the rest of the Benchmark tab's pure logic -- see that module's own
# docstring. Only read_benchmark_log() is still imported back here (below), for
# reload_primes_tree()'s own use (the "Prime numbers" tab's generation-time column).


# ------------------------------------------------------------------------------------------
# Pure logic (no tkinter dependency) -- kept separate from the GUI classes below so it can
# be unit-tested on its own, without a display.
# ------------------------------------------------------------------------------------------

# _safe_prime_gap_margin/MissingStorageRangeError/read_is_prime_from_storage moved to
# primeatlas/research_goldbach.py during the refactor branch's Faza 3 (tab-by-tab
# backend/UI split, 2026-08-23), alongside the Goldbach sub-tab's own UI split (see
# primeatlas/research_goldbach_tab.py's own docstring) -- neither is used by anything
# else in this file.


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
    already uses for primes_tab.py's _cumulative_pietro_totals()/benchmark_tab.py's
    _hover_label_position()."""
    bumps = []
    for row in rows[before_count:]:
        if row.get("write_files") != "1":
            continue
        try:
            base_exponent = int(row["base_exponent"])
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
    filenames(...)), nothing more. Added 2026-08-18 at Artur's request after a real-world
    screenshot showed a nonsensical "windows in storage" figure
    (234,567,890,123,458,790) in the Exploration-mode Quick-gen summary: that number was
    find_continuation_target_idx()'s CONTINUATION POINT (highest existing target_idx +
    1), which only equals the real file count on a floor with zero gaps -- once direct-
    start writes made genuine interior gaps possible (see find_first_gap_target_idx()'s
    own docstring), the two numbers can diverge arbitrarily, and the continuation point
    alone is meaningless as a "how much do I actually have" figure for a person to read.
    This function is for DISPLAY ONLY -- every launch/continuation decision must keep
    using find_continuation_target_idx() (or find_first_gap_target_idx() for the gap-
    fill strategy), since those need the highest-existing-POSITION semantics, not a
    plain count, to know where generation can safely resume. Proportional to the real
    file count via list_source_filenames()'s own os.listdir() (cheap even at thousands
    of files per floor), never to the numeric magnitude of the floor itself."""
    return len(list_source_filenames(portal_folder, base_exponent))


def find_continuation_target_idx(portal_folder, base_exponent, window_m):
    """Pure-Python, WSL/ctypes-free reimplementation of orchestrator_v2_debug.
    find_auto_start()'s logic, built on list_source_filenames() (already parses each
    PRIME_WINDOW_*.bin's offset straight from its filename, no file opens). Returns the
    target_idx the REAL orchestrator will actually continue from the next time it runs
    against this floor (0 if nothing exists yet) -- used by the Quick generation
    panel to preview/validate a requested range against what generation can truthfully
    do, WITHOUT importing orchestrator_v2_debug itself: that module's import
    chain ctypes-loads a Linux .so a few hops down (prime_sieve_v2_debug ->
    prime_sieve_engine), which this native-Windows tkinter app must never require just to
    check what's already on disk (same reasoning DEFAULT_GENERATION_SETTINGS's own
    docstring gives for duplicating orchestrator_loop_v2's defaults instead of importing
    them)."""
    highest = -1
    for name, _path in list_source_filenames(portal_folder, base_exponent):
        offset = _offset_from_filename(name)
        if offset is None:
            continue
        target_idx = offset // window_m
        if target_idx > highest:
            highest = target_idx
    return highest + 1


def find_first_gap_target_idx(portal_folder, base_exponent, window_m):
    """Returns the target_idx of the FIRST missing window on this floor (0 if nothing
    exists yet) -- where a 'fill gaps first' continuation strategy should start next, as
    opposed to find_continuation_target_idx()'s own 'extend past the highest existing
    file' strategy (added 2026-08-18, at Artur's request, once direct-start generation --
    see _launch_direct_window_range() -- made genuine gaps possible for the first time;
    before that, every floor was always contiguous from index 0, so the two strategies
    always agreed). Returns the exact same value as find_continuation_target_idx() when
    the floor genuinely has no gaps (still the common case) -- only differs once one
    exists. list_source_filenames() is already sorted ascending by offset, so this is a
    single linear pass comparing each file's target_idx against the NEXT expected one,
    stopping the instant they disagree -- safe even for a floor whose highest target_idx
    is astronomically large (e.g. one created by a direct-start write deep into an
    otherwise-empty floor), since this never iterates the numeric RANGE, only the actual
    file COUNT."""
    expected = 0
    for name, _path in list_source_filenames(portal_folder, base_exponent):
        offset = _offset_from_filename(name)
        if offset is None:
            continue
        target_idx = offset // window_m
        if target_idx != expected:
            return expected
        expected += 1
    return expected


def _trim_existing_from_target_idx_range(portal_folder, base_exponent, target_idx_start,
                                          window_count, window_m):
    """Shrinks [target_idx_start, target_idx_start + window_count) to skip whatever
    ALREADY exists at its own front and back edges -- write_prime_window() (every engine
    in prime_sieve/) always overwrites unconditionally, with no existence check of its
    own, so without this a request that happens to overlap already-generated windows
    would harmlessly but needlessly re-sieve and rewrite them (added 2026-08-18, at
    Artur's request). Only trims contiguous existing runs at the two EDGES of the
    request, not scattered gaps in its interior -- detecting/skipping an interior gap
    would need one launch per gap instead of one per request; an interior already-existing
    window still gets safely, harmlessly rewritten with identical content, same as before
    this function existed.

    Returns (trimmed_start, trimmed_count) -- trimmed_count is 0 (trimmed_start
    meaningless) if the ENTIRE requested range turns out to already exist."""
    existing = set()
    for name, _path in list_source_filenames(portal_folder, base_exponent):
        offset = _offset_from_filename(name)
        if offset is not None:
            existing.add(offset // window_m)
    start = target_idx_start
    end = target_idx_start + window_count  # exclusive
    while start < end and start in existing:
        start += 1
    while end > start and (end - 1) in existing:
        end -= 1
    return start, max(0, end - start)


def find_highest_populated_floor(portal_folder):
    """Highest base_exponent among every 10p{N} folder that actually has at least one
    PRIME_WINDOW_*.bin file on disk -- an empty/leftover 10p{N} directory with no
    source_primes files doesn't count. Returns None if nothing has been generated
    anywhere yet.

    Used by Exploration mode's own blank-Floor auto-continue (see
    _build_quick_mode_explore's docstring): the same way find_continuation_target_idx()
    above finds where ONE SPECIFIC floor's own data ends, this finds WHICH floor the
    whole database's deepest generated data currently sits on, so repeatedly clicking
    Generate with Floor left blank keeps extending whatever is actually the deepest data
    right now, without the person having to track and retype that floor number by hand
    (or getting stuck re-requesting an already-satisfied range on some floor number they
    typed once and never updated).

    list_pietra() returns folders sorted ascending; checked in reverse so this returns as
    soon as the first (highest) populated one is found, rather than scanning every floor
    unconditionally."""
    for base_exponent in reversed(list_pietra(portal_folder)):
        if list_source_filenames(portal_folder, base_exponent):
            return base_exponent
    return None


# read_source_file_headers/TOTALS_CACHE_FILENAME/_totals_cache_path/load_totals_cache/
# save_totals_cache/update_pietro_totals_cache moved to primeatlas/storage.py during the
# refactor branch's Faza 3 (2026-08-23) -- see that module's own docstring. All six names
# (except the private _totals_cache_path) are imported back at this file's top.


# hit_file_path/floor_has_constellation_hits/list_constellation_hits/
# group_constellation_hits_by_k/build_constellation_records_table/
# build_constellation_records_detail_rows/render_constellation_records_pdf/
# find_constellation_participation moved to primeatlas/constellations.py during the
# refactor branch's Faza 3 (2026-08-23), alongside the Constellations tab's own UI split
# (primeatlas/constellations_hits_tab.py, primeatlas/constellations_calc_tab.py,
# primeatlas/constellations_records_tab.py) -- see each module's own docstring.
# find_constellation_participation/floor_has_constellation_hits/list_constellation_hits
# are imported back at this file's top (still used by the shared search worker's
# _search_job, by _constellations_tree_scan, and by _on_const_search_result, all still
# here); the rest are only used by the (now separate) Constellations sub-tabs.

# _eval_quick_number/_round_range_to_window/_floor_window_count are general-
# purpose helpers (used by the Quick generation panel, primesieve calculator, Testy
# pierwszosci, and the Kalkulator konstelacji tab) that happened to sit textually
# between render_constellation_records_pdf and find_constellation_participation
# before the move above -- restored here unchanged, they were never Constellations-
# specific.

def _eval_quick_number(raw):
    """Best-effort parse of a Python-expression-style number (e.g. "10**5") -- shared by
    every numeric field in this app (Quick generation panel, primesieve calculator,
    Testy pierwszosci, Kalkulator konstelacji, ...). Returns an int, or None if
    `raw` is blank/unparseable; callers
    treat None as "no value given" rather than raising, e.g. to decide whether the
    Floor field should be auto-computed or left for manual entry (see
    _on_quick_floor_start_changed). Restricted eval (no builtins) -- this is a personal
    desktop tool, not a network-facing service, but there's no reason to allow arbitrary
    code execution just to parse a number typed into a text field.

    Strips every whitespace character (regular, non-breaking \\xa0, narrow no-break
    \\u202f -- all match Python's Unicode-aware \\s -- covers a number pasted straight out
    of a web page or spreadsheet) and every comma before evaluating, so a
    thousands-grouped number copied from elsewhere parses as a single int regardless of
    which grouping convention the source used: "23 081 664 151" (space every 3 digits)
    and "23,081,664,151" (comma) both become 23081664151. Safe for this field's actual
    purpose (one integer, or a simple arithmetic expression like "10**5+3") -- Python's
    own expression syntax never needs either character, and a comma left in place would
    otherwise build a tuple (rejected by the int() call below) instead of the single
    number this field is for."""
    raw = (raw or "").strip()
    if not raw:
        return None
    cleaned = re.sub(r"[\s,]", "", raw)
    if not cleaned:
        return None
    try:
        return int(eval(cleaned, {"__builtins__": {}}, {}))
    except Exception:
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

    Exists to stop exactly the bug this was written for: nothing previously checked
    whether a floor-only/range request's window_count_per_run would push target_idx past
    a floor's own boundary, so continuing to generate on floor 7 past its 9th window
    silently wrote floor 8 (and beyond)'s numbers into 10p7's folder, labeled as floor 7.
    See _quick_gen_plan_literal_range and _on_quick_generate_clicked's blank-starting-
    point Floor branch for where this gets applied -- Exploration mode deliberately does
    NOT use this (see that branch's own comment)."""
    if base_power < LOW_FLOOR_CUTOFF:
        return None
    return (9 * 10 ** base_power) // window




# ------------------------------------------------------------------------------------------
# Generation launcher -- settings persistence + WSL command building for running
# orchestrator_loop_v2.py and constellation_finder_v1.py from inside the GUI's
# "Generation" tab instead of a manual WSL terminal. Kept in this pure-logic section (no
# tkinter dependency) so the command-building/settings-merge/subprocess-streaming logic can
# be exercised without a display, same reasoning as everything else above.
# ------------------------------------------------------------------------------------------

GENERATION_SETTINGS_FILENAME = ".portal_generation_settings.json"

# Mirrors orchestrator_loop_v2.py's own module-level defaults (WINDOW_COUNT_PER_RUN=1000,
# WORKERS=24, BATCHES_PER_WORKER=2). Duplicated here (not imported) rather than importing
# orchestrator_loop_v2 directly, because that module requires WSL/ctypes to actually RUN
# (prime_sieve_v3.py, three hops down its import chain, ctypes-loads a Linux .so) -- this
# native-Windows tkinter app must never gain that dependency just to read a constant. If
# those scripts' defaults ever change, update both places.
DEFAULT_GENERATION_SETTINGS = {
    "loop": {
        "base_exponent": "20",
        "run_count": "1",
        "n_instances": "2",
        "write_files": True,
        "compute_sieving_primes_count": False,
        "use_known_pi_seed": False,
        "window_count_per_run": "1000",
        "workers": "24",
        "batches_per_worker": "2",
        "window_m": "10000000",  # mirrors orchestrator_loop_helpers.py's own
                                  # WINDOW_M -- see build_loop_argv()'s docstring for the
                                  # cross-floor-consistency caveat before changing this.
    },
    "constellation": {
        "base_exponent": "",  # blank = auto (every floor with source data -- see
                               # constellation_finder_v1.list_pietra_with_data())
    },
    "ktuple": {
        "base_exponent": "",
        "k": "",
        "variant_id": "",
        "n_locations": "1000",
        "window_m": "10000000",
        "strategy": "concentrated",  # see ktuple_sieve_v1.py's own module docstring for
                                      # what each strategy means
        "step": "",  # blank = auto-computed per strategy (required for manual_step)
        "fragment_width": "",  # blank = auto-sized from Hardy-Littlewood density
        "fragment_start": "0",  # only used the first time (no checkpoint yet) or after
                                 # a reset -- every run after that continues from the
                                 # checkpoint regardless of this field
        "manual_offsets": "",  # space/comma-separated ints, strategy=manual_list only
        "deep_prime_limit": "2000",
        "mr_rounds": "40",
        "reset_checkpoint": False,
        "pass_counter": "0",  # strategy=digit_sweep only -- starting pass (0, 1, 2, ...)
                               # used only when no checkpoint exists yet or after a
                               # reset -- see ktuple_sieve_v1.py's digit_sweep_locations()
                               # docstring (PATH VARIETY section)
    },
}


_KTUPLE_STRATEGY_KEYS = ["even", "concentrated", "manual_list", "manual_step", "digit_sweep"]


def _generation_settings_path(portal_folder):
    return os.path.join(portal_folder, GENERATION_SETTINGS_FILENAME)


def load_generation_settings(portal_folder):
    """Returns the persisted Generation-tab form values, merged over
    DEFAULT_GENERATION_SETTINGS so a settings file saved before some field existed (schema
    grew since) or a missing/corrupt file still yields a complete dict with every key
    present -- same defensive shape as load_totals_cache(). Never raises."""
    merged = {section: dict(values) for section, values in DEFAULT_GENERATION_SETTINGS.items()}
    path = _generation_settings_path(portal_folder)
    if not os.path.exists(path):
        return merged
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return merged
    if not isinstance(data, dict):
        return merged
    for section, values in merged.items():
        loaded = data.get(section)
        if isinstance(loaded, dict):
            values.update(loaded)
    return merged


def save_generation_settings(portal_folder, settings):
    """Atomic write (temp file + os.replace()), same pattern as save_totals_cache()."""
    path = _generation_settings_path(portal_folder)
    tmp_path = f"{path}.tmp{os.getpid()}"
    try:
        os.makedirs(portal_folder, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except OSError:
        pass  # best-effort -- a failed settings save just means the next launch reuses
              # whatever was last persisted (or the defaults, if nothing ever saved)


_WINDOWS_DRIVE_PATH_RE = re.compile(r'^([A-Za-z]):[\\/](.*)$')


def windows_path_to_wsl(path):
    """Translates a native Windows absolute path (e.g. "D:\\storage\\...") to its WSL
    mount-point equivalent ("/mnt/d/storage/...") -- the same mapping orchestrator_v3.py's/
    prime_sieve_v3.py's own __main__ blocks hardcode for BASE_STORAGE_10PN. A path with no
    drive-letter prefix is returned with backslashes flipped to forward slashes, unchanged
    otherwise (so already-WSL-style input passes through as-is)."""
    m = _WINDOWS_DRIVE_PATH_RE.match(path)
    if not m:
        return path.replace("\\", "/")
    drive = m.group(1).lower()
    rest = m.group(2).replace("\\", "/")
    return f"/mnt/{drive}/{rest}"


ORCHESTRATOR_LOOP_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "orchestrator_loop_v2.py"))
ORCHESTRATOR_DIRECT_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "orchestrator_v3.py"))
CONSTELLATION_FINDER_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "constellation", "constellation_finder_v1.py"))
KTUPLE_SIEVE_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "constellation", "ktuple_sieve_v1.py"))


def recommended_digit_sweep_n_locations(base_exponent, window_m, target_windows_per_branch=40):
    """Mirrors ktuple_sieve_v1.digit_sweep_positions()'s own p_min search (duplicated,
    not imported -- that module runs standalone inside WSL, this native-Windows GUI
    process must not depend on it, same "duplicated rather than imported" pattern
    already used elsewhere in this file, e.g. LOW_FLOOR_CUTOFF/QUICK_GEN_MAX_WINDOW_WIDTH
    right below).

    Added 2026-08-19 after Artur pointed out that the shared 1000-window default left
    each individual digit branch only ~4-5 windows deep (40M numbers) when he'd
    pictured each branch getting close to the ~40-window (400M number) depth his own
    "1000 windows / 25 positions = 40 per position" mental model implied per BRANCH,
    not per POSITION split across its ~10 branches. Rather than silently reinterpret
    what n_locations means, this just recommends an n_locations big enough that BOTH
    readings coincide: every position still gets swept in the SAME batch (matching
    his explicit goal of the whole floor's magnitude range examined at once), and
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


PRIMESIEVE_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "prime_sieve_primesieve.py"))
HYBRID_SIEVE_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "hybrid_sieve.py"))
PRIMESIEVE_QUERY_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "primesieve_query.py"))

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

# Width (multiplier of QUICK_GEN_MAX_WINDOW_WIDTH) spinbox bound for primesieve mode --
# deliberately NOT the [1, 1000] cap every other mode's Width field uses (that cap exists
# because those engines pay a real RAM cost of window_count * window_width / 8 bytes for a
# combined shared buffer -- see README's "Window count, throughput, and RAM"). primesieve
# mode has no such buffer (see prime_sieve_primesieve.py's module header); its only real
# limit is libprimesieve's own uint64 ceiling, so the Width field is allowed to reach far
# enough to cover the WHOLE library range from floor 0's own start -- one extra window of
# headroom rounds this comfortably past PRIMESIEVE_MAX_STOP // QUICK_GEN_MAX_WINDOW_WIDTH.
PRIMESIEVE_MAX_WIDTH_MULT = PRIMESIEVE_MAX_STOP // QUICK_GEN_MAX_WINDOW_WIDTH + 1


# ------------------------------------------------------------------------------------------
# CUDASieve (optional GPU engine) -- argv builders + blocking WSL status/install calls.
# Ported from the `cudasieve` branch's prime_atlas_v2.py (forked 2026-08-22, before this
# refactor's tab-by-tab extraction existed) onto this module, task #459/cudasieve-v2 branch.
# See prime_sieve/prime_sieve_cudasieve.py's own module header for what --status/
# --fetch-license/--build each do and why the install consent-gate is split across two of
# them; this is only the "how do I invoke it from Windows via wsl.exe" layer, same division
# of responsibility every other build_*_argv() in this module already follows.
# ------------------------------------------------------------------------------------------

CUDASIEVE_SCRIPT = os.path.abspath(
    os.path.join(_SCRIPT_DIR, "prime_sieve", "prime_sieve_cudasieve.py"))


def build_cudasieve_status_argv():
    """`python3 prime_sieve_cudasieve.py --status` -- see that function's own docstring
    for the JSON shape returned."""
    return ["python3", windows_path_to_wsl(CUDASIEVE_SCRIPT), "--status"]


def build_cudasieve_fetch_license_argv():
    """`python3 prime_sieve_cudasieve.py --fetch-license` -- clones/updates CUDASieve and
    returns its OWN current License file text as JSON; see cmd_fetch_license()'s own
    docstring for why this (not a copy embedded in this project) is what the consent
    dialog shows."""
    return ["python3", windows_path_to_wsl(CUDASIEVE_SCRIPT), "--fetch-license"]


def build_cudasieve_build_argv():
    """`python3 -u prime_sieve_cudasieve.py --build` -- runs `make` in the already-cloned
    install dir (see cmd_build()'s own docstring); -u (unbuffered) for the same reason
    build_constellation_finder_argv() uses it -- this is a long-running job whose progress
    lines should reach WslLoggedRunner's log file as they're printed, not only at exit."""
    return ["python3", "-u", windows_path_to_wsl(CUDASIEVE_SCRIPT), "--build"]


def run_cudasieve_wsl_blocking(argv, portal_folder, timeout=120):
    """Blocking wsl.exe call for --status/--fetch-license (both answer in a few seconds at
    most under normal conditions -- --fetch-license's git clone/fetch is the slow part,
    hence the longer default timeout than a quick status ping). Returns (True, payload)/
    (False, error_message), same two-tuple contract as run_primesieve_query_wsl()
    (primesieve_calc_tab.py) and every other WSL-launching call in this app.

    `portal_folder` is an explicit parameter, not a bare module global -- see this
    module's own docstring for why every WSL-launching function here takes it that way
    (settings_tab.py's wsl_helpers wraps this in a lambda supplying the CURRENT storage
    path, same as it already does for build_wsl_logged_command).

    Deliberately does NOT use the simple subprocess.run(cmd, timeout=timeout) pattern
    run_primesieve_query_wsl() uses (primesieve_calc_tab.py) -- ported forward from a real,
    confirmed-live bug hit on the `cudasieve` branch (2026-08-23):

    1) subprocess.run() against wsl.exe's own stdout pipe hung indefinitely from within
       this windowed/console-less Tk process, even though a bare `wsl.exe -e bash -c
       "echo hi"` from a plain terminal returned instantly -- the same console-allocation/
       pipe-hang failure mode build_wsl_logged_command()'s own docstring documents.
    2) Switching to build_wsl_logged_command()'s file-redirection (real stdout/stderr never
       touch a pipe wsl.exe itself owns) while still calling subprocess.run(...,
       timeout=timeout) STILL hung, even after a full app restart + `wsl --shutdown`. Root
       cause: on Windows, when Popen.communicate(timeout=timeout) raises TimeoutExpired,
       CPython's subprocess.run() calls process.kill() and then calls
       process.communicate() a SECOND time with NO timeout at all, as a "collect the real
       output" fallback (see subprocess.py's own source). If wsl.exe's own process doesn't
       actually die from kill() (WSL's process-lifecycle model doesn't guarantee a killed
       Windows-side wrapper takes the underlying Linux process down with it -- see
       WslLoggedRunner's own docstring), that second, untimed call can hang forever,
       silently defeating `timeout=` entirely regardless of its value.

    WslLoggedRunner itself never hits this: it uses Popen() (non-blocking) plus its own
    manual proc.poll() loop, and never calls wait()/communicate() with (or without) a
    timeout anywhere. This function now copies that exact pattern instead of leaning on
    subprocess.run's timeout machinery at all. (run_primesieve_query_wsl() has not hit
    this in practice since a single count/nth/next/prev query answers in well under a
    second, but the same latent hang risk applies there too -- flagged separately, not
    fixed here, since that function belongs to an unrelated tab.)"""
    log_path, exit_path, _run_id = generation_log_paths(portal_folder, "cudasieve_query")
    cmd = build_wsl_logged_command(argv, log_path, exit_path, portal_folder)
    try:
        proc = subprocess.Popen(cmd, **_popen_kwargs_no_window())
    except OSError as e:
        return False, f"Could not launch WSL: {e}"
    deadline = time.time() + timeout
    while proc.poll() is None:
        if time.time() > deadline:
            try:
                proc.kill()
            except OSError:
                pass
            for p in (log_path, exit_path):
                try:
                    os.remove(p)
                except OSError:
                    pass
            # Deliberately does NOT wait()/communicate() after kill() -- see history item
            # 2 above; this is exactly the untimed call that could hang forever. The
            # underlying wsl.exe process may still be running in the background after this
            # returns -- WSL's process model does not guarantee kill() reaches the Linux
            # side, only that this app stops waiting on it.
            return False, f"Timed out after {timeout}s."
        time.sleep(0.2)
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            stdout = f.read().strip()
    except OSError as e:
        return False, f"Could not read WSL output log: {e}"
    finally:
        for p in (log_path, exit_path):
            try:
                os.remove(p)
            except OSError:
                pass
    last_line = stdout.splitlines()[-1] if stdout else ""
    try:
        payload = json.loads(last_line)
    except (ValueError, IndexError):
        detail = stdout or "(no output)"
        return False, detail[:2000]
    if payload.get("ok"):
        return True, payload
    return False, payload.get("error", "unknown error")


def build_loop_argv(base_exponent, run_count, n_instances, write_files,
                     compute_sieving_primes_count, window_count_per_run,
                     workers, batches_per_worker, window_m, script_path=None):
    """Returns the LINUX-side argv (["python3", "-u", script, args...]) for running
    orchestrator_loop_v2.py -- NOT yet wrapped in a wsl.exe invocation (see
    build_wsl_logged_command() for that). Argument order matches that script's __main__
    CLI EXACTLY (see its module-header "Usage (WSL)" comment): <base_exponent> <run_count>
    <n_instances> <write_files 0/1> <compute_sieving_primes_count 0/1>
    <window_count_per_run> <workers> <batches_per_worker> <window_m> -- ALL 9 positions are
    always passed explicitly, never conditionally omitted, so a value the GUI form shows can
    never silently fall back to that script's own hardcoded default instead (same
    discipline build_instance_cmd() in orchestrator_loop_v2.py itself follows -- see that
    function's docstring).

    window_m: how many numbers each "window" (target_idx step) covers -- a real
    CLI-overridable parameter, same as workers/batches_per_worker, rather than the
    10,000,000 hardcoded in prime_sieve_v3.py/orchestrator_v3.py/
    orchestrator_loop_helpers.py. NOTE (surfaced in the GUI field's own label/tooltip too,
    not just here): changing this for a floor that ALREADY has PRIME_WINDOW_*.bin files
    written with a DIFFERENT window_m breaks auto-resume (the next run would compute a
    wrong/misaligned starting target_idx) -- only safe to change for a floor with no
    existing data yet.

    The `-u` flag forces Python's stdout/stderr to be
    UNBUFFERED instead of the fully-buffered mode it defaults to whenever stdout isn't a
    terminal (exactly the case here -- see build_wsl_logged_command()'s `> logfile`
    redirect). Without it, print() output sits in an in-process buffer and isn't actually
    written to the log file until that buffer fills (several KB) or the process exits --
    for a script whose print volume is low relative to its runtime (constellation_finder_
    v1.py's per-window progress lines, especially early in a long first-time run against a
    heavily-populated floor), that can mean WslLoggedRunner's live tail shows NOTHING for
    a very long time even though the process is working correctly and already writing real
    results to disk incrementally -- indistinguishable from a genuine hang from the GUI's
    point of view."""
    script = script_path if script_path is not None else ORCHESTRATOR_LOOP_SCRIPT
    script_wsl = windows_path_to_wsl(script)
    return [
        "python3", "-u", script_wsl,
        str(base_exponent), str(run_count), str(n_instances),
        "1" if write_files else "0",
        "1" if compute_sieving_primes_count else "0",
        str(window_count_per_run), str(workers), str(batches_per_worker), str(window_m),
    ]


def build_primesieve_argv(base_exponent, target_idx_start, window_count_per_run, window_m,
                           write_files, script_path=None):
    """Returns the LINUX-side argv for prime_sieve_primesieve.py -- the 'primesieve mode'
    engine (see that file's module header for what makes it different from every other
    engine this app can launch: it calls libprimesieve's own primesieve_generate_primes()
    directly, no batching/orchestrator of ours involved at all). Argument order matches
    that script's __main__ CLI exactly: <base_exponent> <target_idx_start>
    <target_idx_count> <window_m> <write_files 0/1> -- deliberately simpler than
    build_loop_argv()'s 9 positions, since workers/batches_per_worker/
    compute_sieving_primes_count have no meaning for this engine.

    Unlike orchestrator_loop_v2.py (which auto-detects its own resume point via
    find_auto_start()), this script takes target_idx_start explicitly -- the GUI already
    computes it via find_continuation_target_idx() while planning the request (see
    _quick_gen_plan_literal_range()), so there's no reason for this simpler script to
    duplicate that disk-scanning logic itself."""
    script = script_path if script_path is not None else PRIMESIEVE_SCRIPT
    script_wsl = windows_path_to_wsl(script)
    return [
        "python3", "-u", script_wsl,
        str(base_exponent), str(target_idx_start), str(window_count_per_run), str(window_m),
        "1" if write_files else "0",
    ]


def build_hybrid_argv(base_exponent, iterations, width_windows, filter_prime_count, write_files,
                      script_path=None):
    """Return the WSL argv for the future ``hybrid_sieve.py`` extension runner.

    This deliberately has a compact, hybrid-specific contract rather than borrowing
    ``build_loop_argv()``'s window-count semantics.  A hybrid stage's reach is
    determined by the visible ``filter_prime_count`` (``k_adv``), not by a fixed
    numeric-width multiplier: the runner derives its exact extension bound only after
    it has built that filter-prime prefix.  The base floor selects the existing,
    continuous magazyn that supplies MAIN; ``iterations`` requests successive hybrid
    extensions of that base.

    CLI order is fixed now, before the runner exists, so the GUI and runner can be
    tested independently in later phases:
    ``<base_exponent> <iterations> <width_windows> <filter_prime_count> <write_files 0/1>``.
    """
    script = script_path if script_path is not None else HYBRID_SIEVE_SCRIPT
    return [
        "python3", "-u", windows_path_to_wsl(script),
        str(base_exponent), str(iterations), str(width_windows), str(filter_prime_count),
        "1" if write_files else "0",
    ]


def build_hybrid_narrow_argv(start, end, main_cap, filter_prime_count, write_files,
                             script_path=None):
    """Build the one-standard-window experimental Hybrid invocation."""
    script = script_path if script_path is not None else HYBRID_SIEVE_SCRIPT
    return [
        "python3", "-u", windows_path_to_wsl(script), "narrow",
        str(start), str(end), str(main_cap), str(filter_prime_count),
        "1" if write_files else "0",
    ]


# Duplicated from prime_sieve_cudasieve.py's own MIN_PRINTABLE_TOP -- CUDASieve's own CLI
# documents that its -p/--print flag "will be ignored below 2**40", so this mode can never
# usefully list individual primes below that value. Checked here too (not just backend-side)
# so a doomed request is rejected before paying a WSL round-trip, exactly like
# PRIMESIEVE_MAX_STOP's own pre-flight check above.
CUDASIEVE_MIN_PRINTABLE_TOP = 2 ** 40

# CUDASieve's own --help text documents examples up to 2**64 (e.g. "-b 2**64-2**35-2**30 -t
# 2**64-2**35"), confirmed on real hardware (RTX 5070, 2026-08-23, `cudasieve` branch) --
# same uint64_t domain as libprimesieve's own PRIMESIEVE_MAX_STOP, so the same
# ceiling/truncation-note logic applies.
CUDASIEVE_MAX_STOP = 2 ** 64 - 1
CUDASIEVE_MAX_WIDTH_MULT = CUDASIEVE_MAX_STOP // QUICK_GEN_MAX_WINDOW_WIDTH + 1


def build_cudasieve_argv(base_exponent, target_idx_start, window_count_per_run, window_m,
                          write_files, script_path=None):
    """Returns the LINUX-side argv for prime_sieve_cudasieve.py -- the GPU 'cudasieve mode'
    engine. Argument order matches that script's __main__ CLI exactly, and is deliberately
    identical in shape to build_primesieve_argv()'s: <base_exponent> <target_idx_start>
    <target_idx_count> <window_m> <write_files 0/1> -- both engines skip the batching/
    orchestrator machinery entirely, so neither has a workers/batches_per_worker/
    compute_sieving_primes_count concept to pass through."""
    script = script_path if script_path is not None else CUDASIEVE_SCRIPT
    script_wsl = windows_path_to_wsl(script)
    return [
        "python3", "-u", script_wsl,
        str(base_exponent), str(target_idx_start), str(window_count_per_run), str(window_m),
        "1" if write_files else "0",
    ]


def build_orchestrator_direct_argv(base_exponent, target_idx_start, window_count_per_run,
                                    window_m, write_files, compute_sieving_primes_count,
                                    workers, batches_per_worker, script_path=None):
    """Returns the LINUX-side argv for launching orchestrator_v3.py DIRECTLY -- bypassing
    orchestrator_loop_v2.py's own wrapper CLI (build_loop_argv()), which only ever
    auto-continues from wherever a floor's storage currently ends (see that function's own
    docstring) and has no way to target an arbitrary target_idx.

    This is the fallback engine for _offer_generate_missing_prime_window() when the
    requested window falls beyond libprimesieve's own uint64 ceiling (PRIMESIEVE_MAX_STOP)
    -- primesieve mode (build_primesieve_argv(), this app's usual single-arbitrary-window
    engine for that call site) simply cannot reach floors that high (e.g. 10^30 is roughly
    eleven orders of magnitude past 2**64-1). orchestrator_v3.py has no such ceiling and,
    unlike its own loop wrapper, DOES accept an explicit start_window on its own __main__
    CLI (see that script's argument parsing) -- so calling it directly, with start_auto
    forced off, gets the exact same 'write just the one window asked for, gaps before it
    and all' behavior primesieve mode provides at the low end, just through the slower
    engine at any magnitude. Argument order matches orchestrator_v3.py's own CLI exactly:
    <base_exponent> <window_count> <start_auto 0/1> <start_window> <write_files 0/1>
    <compute_sieving_primes_count 0/1> <workers> <batches_per_worker> <window_m>."""
    script = script_path if script_path is not None else ORCHESTRATOR_DIRECT_SCRIPT
    script_wsl = windows_path_to_wsl(script)
    return [
        "python3", "-u", script_wsl,
        str(base_exponent), str(window_count_per_run),
        "0", str(target_idx_start),
        "1" if write_files else "0",
        "1" if compute_sieving_primes_count else "0",
        str(workers), str(batches_per_worker), str(window_m),
    ]



def build_constellation_finder_argv(base_exponent=None, script_path=None):
    """Returns the LINUX-side argv for constellation_finder_v1.py, whose CLI is
    `[<base_exponent>]` -- a single OPTIONAL positional arg, omitted entirely (not passed
    as an empty string) when base_exponent is None/blank, matching that script's own
    auto-detect-every-populated-floor behavior (list_pietra_with_data()) when it's
    called with no argument at all. Not yet wrapped in a wsl.exe invocation -- see
    build_wsl_logged_command(). Uses `-u` (unbuffered stdout) for the same reason
    build_loop_argv() does -- see that function's docstring; this script's low per-window
    print volume made it the one where the default full-buffering was actually reported
    as a problem."""
    script = script_path if script_path is not None else CONSTELLATION_FINDER_SCRIPT
    script_wsl = windows_path_to_wsl(script)
    argv = ["python3", "-u", script_wsl]
    if base_exponent not in (None, ""):
        argv.append(str(base_exponent))
    return argv


def build_ktuple_sieve_argv(base_exponent, k, variant_id, n_locations=1000, window_m=10_000_000,
                             strategy="concentrated", step=None, fragment_width=None,
                             fragment_start=None, manual_offsets=None, deep_prime_limit=2000,
                             mr_rounds=40, auto=False, reset_checkpoint=False, pass_counter=None,
                             script_path=None):
    """Returns the LINUX-side argv for ktuple_sieve_v1.py -- see that script's own
    argparse block for the exact CLI shape (three required positionals: base_exponent,
    k, variant_id; the rest are optional flags with the same defaults this function
    uses). `-u` for the same unbuffered-stdout reason build_constellation_finder_argv()
    uses -- this script's per-location print volume is lower still (each location does
    real work: wheel-stride + trial-division + Miller-Rabin, not just a window read), so
    buffering would hide live progress even more than that script's own case did.

    Unlike build_constellation_finder_argv(), base_exponent/k/variant_id are all
    REQUIRED here (ktuple_sieve_v1.py has no auto-detect-every-floor mode -- a k-tuple
    hunt is always FOR one specific pattern, at a caller-chosen floor, never implicit).

    `strategy` -- one of "even", "concentrated", "manual_list", "manual_step",
    "digit_sweep" (see ktuple_sieve_v1.py's own module docstring for what each means;
    all but manual_list share a checkpoint-driven continuation mechanism, manual_list
    is a one-shot with no checkpoint). `step`/`fragment_start` are left OUT of argv
    entirely when None -- ktuple_sieve_v1.py's own CLI defaults (auto-computed step per
    strategy, fragment_start=0) then apply, same "don't pass what wasn't explicitly
    set" shape as `fragment_width`/`manual_offsets`/`pass_counter` already had.
    `pass_counter` only matters for strategy=digit_sweep (default 0 on the script side
    when omitted, and only used the first time -- once a checkpoint exists the script's
    own next_offset field takes over and this starting value is ignored). `auto`/
    `reset_checkpoint` are plain boolean flags (only appended when True -- argparse's
    own store_true default is already False)."""
    script = script_path if script_path is not None else KTUPLE_SIEVE_SCRIPT
    script_wsl = windows_path_to_wsl(script)
    argv = ["python3", "-u", script_wsl, str(base_exponent), str(k), str(variant_id),
            "--n-locations", str(n_locations), "--window-m", str(window_m),
            "--strategy", strategy,
            "--deep-prime-limit", str(deep_prime_limit), "--mr-rounds", str(mr_rounds)]
    if step is not None:
        argv += ["--step", str(step)]
    if fragment_width is not None:
        argv += ["--fragment-width", str(fragment_width)]
    if fragment_start is not None:
        argv += ["--fragment-start", str(fragment_start)]
    if manual_offsets:
        argv += ["--manual-offsets"] + [str(o) for o in manual_offsets]
    if pass_counter is not None:
        argv += ["--pass-counter", str(pass_counter)]
    if auto:
        argv.append("--auto")
    if reset_checkpoint:
        argv.append("--reset-checkpoint")
    return argv


GENERATION_LOGS_DIRNAME = ".generation_logs"


def generation_log_paths(portal_folder, prefix):
    """Allocates a fresh (windows_log_path, windows_exit_path, run_id) triple under
    CONSTELLATION_PORTAL/.generation_logs/ for one subprocess run. Both paths sit on the
    same Windows drive WSL already sees under its own /mnt/ mount point -- the Linux-side redirect (see
    build_wsl_logged_command()) and this app's own file-tailing (see WslLoggedRunner) are
    reading/writing the exact same physical file, so no WSL<->Windows translation is ever
    needed on the READ side, only when building the bash command itself."""
    logs_dir = os.path.join(portal_folder, GENERATION_LOGS_DIRNAME)
    os.makedirs(logs_dir, exist_ok=True)
    run_id = f"{prefix}_{int(time.time() * 1000)}_{os.getpid()}"
    return (os.path.join(logs_dir, f"{run_id}.log"),
            os.path.join(logs_dir, f"{run_id}.exit"),
            run_id)


def build_wsl_logged_command(argv, windows_log_path, windows_exit_path, portal_folder,
                              use_known_pi_seed=False):
    """Wraps a Linux-side argv (e.g. ["python3", "/mnt/d/.../script.py", "20", ...]) in a
    `wsl.exe -e bash -c "..."` invocation that redirects combined stdout+stderr into
    windows_log_path (translated to its WSL mount path) and writes the process's exit
    code into windows_exit_path afterward -- see WslLoggedRunner's docstring for why
    file-based redirection replaced an earlier subprocess.PIPE-against-wsl.exe's-own-
    stdout approach. Every token is individually shell-quoted (shlex.quote) so the space
    in "Prime numbers storage" (and anything else) survives bash -c's re-parsing --
    the exec-mode `wsl.exe -e <argv>` form used elsewhere in this app deliberately avoids
    a shell entirely for that reason, but the `>`/`;` here are shell syntax and need one. `portal_folder` is the CURRENT storage
    path, passed explicitly by the caller (see this module's own docstring for why -- this
    function no longer reads a bare PORTAL_FOLDER global).

    use_known_pi_seed (default False, Artur's idea, 2026-08-27): sets
    PRIMEATLAS_USE_KNOWN_PI_SEED=1 alongside CONSTELLATION_PORTAL_DIR below, using the exact
    same env-prefix mechanism -- see prime_sieve_v4_1.py's own __main__ block (where it's
    read) and count_sieving_primes_cached()'s docstring for what it does. Every call site
    launches a DIFFERENT script (orchestrator_loop_v2.py, orchestrator_v3.py directly,
    prime_sieve_primesieve.py, ktuple_sieve_v1.py, constellation_finder_v1.py) and only the
    first two ever read this var -- the others simply ignore an env var they don't check, so
    it's harmless to leave at its False default for every call site that doesn't pass it
    explicitly (only the Generation tab's classic-engine Pipeline/Loop launches do)."""
    log_wsl = windows_path_to_wsl(windows_log_path)
    exit_wsl = windows_path_to_wsl(windows_exit_path)
    inner = " ".join(shlex.quote(str(t)) for t in argv)
    # CONSTELLATION_PORTAL_DIR, set via prime_atlas_v1.py's Settings tab: a plain
    # os.environ[...] set in THIS (Windows) process does NOT automatically cross into
    # wsl.exe's Linux environment (that needs WSLENV, which this app doesn't otherwise use)
    # -- so the override is prepended directly to the bash -c command line instead, the one
    # mechanism guaranteed to work regardless of WSLENV configuration. This makes every WSL
    # launch through this function (i.e. every Generation-tab run) automatically honor
    # whatever storage path is currently configured, with no per-call-site changes needed.
    portal_wsl = windows_path_to_wsl(portal_folder)
    env_prefix = f"CONSTELLATION_PORTAL_DIR={shlex.quote(portal_wsl)} "
    if use_known_pi_seed:
        env_prefix += "PRIMEATLAS_USE_KNOWN_PI_SEED=1 "
    bash_cmd = (f"{env_prefix}{inner} > {shlex.quote(log_wsl)} 2>&1; "
                f"echo $? > {shlex.quote(exit_wsl)}")
    return ["wsl.exe", "-e", "bash", "-c", bash_cmd]


def _popen_kwargs_no_window():
    kwargs = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def estimate_wsl_available_ram_bytes(timeout=10):
    """Best-effort read of MemAvailable from /proc/meminfo INSIDE WSL -- deliberately not
    the native Windows process's own memory, since the actual sieve run happens as a WSL
    subprocess (see build_wsl_logged_command above) and WSL2's memory cap is configured
    independently of the host (.wslconfig, defaults to roughly half the host's RAM) --
    querying Windows-side RAM would silently overstate what the run this estimate is FOR
    can actually use. Returns None on any failure (WSL not installed/reachable, parse
    failure, timeout) -- callers must treat that as "couldn't determine, don't guess",
    never fall back to a made-up number."""
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            ["wsl.exe", "-e", "bash", "-c", "cat /proc/meminfo"],
            capture_output=True, text=True, timeout=timeout, **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        if line.startswith("MemAvailable:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1]) * 1024  # /proc/meminfo reports kB
    return None


def recommended_max_windows(available_ram_bytes, window_m=QUICK_GEN_MAX_WINDOW_WIDTH,
                             safety_fraction=0.5):
    """Conservative "how many windows should fit in one run" recommendation. Only the ONE
    memory cost that's known EXACTLY regardless of floor depth is used as the basis: the
    shared output buffer the engine allocates up front is windows * (window_m // 8) bytes
    (see prime_sieve_v3.py/v4.py's own "Shared output buffer" print line -- this mirrors
    that same arithmetic). Per-worker overhead is NOT modeled here -- it DOES grow with
    floor depth (each worker walks sieving primes up to L_final = isqrt(combined_hi),
    which grows with the floor), and there isn't enough calibration data yet to model it
    honestly. safety_fraction (default 0.5 -- only half of available RAM counted) stands
    in for that unmodeled cost; treat the result as a starting point to try on a small
    run first, not a guarantee -- the benchmark log's own peak-RAM column is the real
    feedback loop for tightening this over time. Returns None if available_ram_bytes is
    None/non-positive; otherwise an int clamped to the same [1, 1000] range every width
    spinbox in this panel already enforces."""
    if not available_ram_bytes or available_ram_bytes <= 0:
        return None
    bytes_per_window = window_m // 8
    windows = int((available_ram_bytes * safety_fraction) // bytes_per_window)
    return max(1, min(1000, windows))


def estimate_wsl_available_cpu_count(timeout=10):
    """Best-effort read of the CPU count INSIDE WSL (via `nproc`) -- same reasoning as
    estimate_wsl_available_ram_bytes() above: the sieve itself runs as a WSL subprocess
    (see build_wsl_logged_command above), and WSL2 can be configured (`.wslconfig`'s own
    `processors` setting) with fewer virtual CPUs than the host actually has, so reading
    Windows-side CPU count (e.g. `os.cpu_count()` in this native process) would silently
    overstate what a run launched INTO WSL can actually use in parallel. Returns None on
    any failure (WSL not installed/reachable, parse failure, timeout) -- callers must
    treat that as "couldn't determine, don't guess", never fall back to a made-up
    number, same as the RAM probe."""
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            ["wsl.exe", "-e", "bash", "-c", "nproc"],
            capture_output=True, text=True, timeout=timeout, **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    if not output.isdigit():
        return None
    count = int(output)
    return count if count > 0 else None


def recommended_worker_count(available_cpu_count):
    """The "workers" CLI parameter (orchestrator_loop_v2.py/orchestrator_v3.py) spawns
    that many OS-level parallel processes, each pinned to sieving its own batch of the
    combined range -- unlike window count (which trades RAM for throughput with no
    natural ceiling other than memory), there is no benefit to requesting more workers
    than there are CPUs to actually run them concurrently; anything beyond that just
    adds process-scheduling overhead without adding real parallelism. The
    recommendation is therefore simply the detected CPU count itself, clamped to a
    sane [1, 256] display range (defensive only -- guards against a corrupt/absurd
    `nproc` read, not a real architectural limit). Returns None if
    available_cpu_count is None/non-positive, same "couldn't determine" contract as
    recommended_max_windows()."""
    if not available_cpu_count or available_cpu_count <= 0:
        return None
    return max(1, min(256, int(available_cpu_count)))


# Parsed out of a generation run's live console output by _drain_output_queue() to drive the
# SHARED bottom status/progress bar (self.status/self.totals_progress -- the same one the
# floor-totals scan and the Primes/Constellations search box already use) while a run is in
# flight, in addition to the raw text already visible in the console/terminal panel itself.
# Every one of these lines is already printed by the engines on their own -- nothing new was
# added to either script, this only reads what was already there. Together they cover the
# WHOLE pipeline, not just the batch-sieve phase -- see
# _update_shared_progress_from_generation_chunk()'s own docstring for how the individual
# lines below map onto one combined step count, so the bar isn't left sitting empty for
# however long the pi(L_final) prep phase happens to take (which can itself run into
# minutes at extreme depth) before the first batch-progress line ever arrives.
#   prime_sieve_v4.py/prime_sieve_v4_1.py (main_batch_scanner, pi(L_final) prep step --
#   EITHER the "used" (computed) or "count ... SKIPPED" wording, depending on the
#   compute_sieving_primes_count flag, both start the same way):
#     "[*] Active sieving primes used (pi(L_final)): 346,065,536,839 (computed in 0.009s -- ...)"
#     "[*] Active sieving primes count (pi(L_final)): SKIPPED (...)"
#   prime_sieve_v4.py/prime_sieve_v4_1.py (main_batch_scanner's own progress print):
#     "[+] Progress: 42.31% (156/369 batches) | time: 12.34s (...) | ETA ~16s"
#   prime_sieve_v4.py/prime_sieve_v4_1.py (main_batch_scanner, run-finished line -- printed
#   for BOTH the low-floor and normal-window code paths, only the tail differs):
#     "[*] TOTAL PRIMES FOUND this run: 167,026,529 across 1000 windows"
#   constellation_finder_v1.py (process_floor's own per-file print):
#     "[CONSTELLATIONS v1] 12/48: PRIME_WINDOW_10p11_off_50M.bin -- ..."
#   constellation_finder_v1.py (process_floor, run-finished line):
#     "[CONSTELLATIONS v1] Done. New hits this run, by pattern:"
#   orchestrator_loop_v2.py (multi-iteration Exploration-mode launches ONLY -- see
#   _LOOP_SESSION_START_RE/_LOOP_ITERATION_START_RE/_LOOP_SESSION_DONE_RE's own comment
#   below for why these three matter: without them, _GEN_SIEVE_DONE_RE above fires once
#   PER ITERATION -- each iteration is its own separate orchestrator_v3.py subprocess --
#   snapping the bar to "done" after iteration 1 of N, and _GEN_SIEVE_PROGRESS_RE's own
#   batch count resets every iteration too, so the bar only ever showed progress through
#   THAT one iteration's own windows, never the whole multi-iteration request):
#     "[LOOP] orchestrator_loop_v2 v2 (parallel instances): 10 iteration(s), 1 instance(s)
#     /iteration, 1000 windows/iteration, ..."
#     "[LOOP] iteration 3/10: launching 1 instance(s) concurrently -- target_idx ..."
#     "[LOOP] All iterations complete in 123.4s total." / "[LOOP] Stopped early in ...s total."
_GEN_PREP_DONE_RE = re.compile(r"\[\*\] Active sieving primes (?:used|count) \(pi\(L_final\)\)")
_GEN_SIEVE_PROGRESS_RE = re.compile(r"\[\+\] Progress: ([\d.]+)% \((\d+)/(\d+) batches\)")
_GEN_SIEVE_DONE_RE = re.compile(r"\[\*\] TOTAL PRIMES FOUND this run:")
_GEN_CONST_PROGRESS_RE = re.compile(r"\[CONSTELLATIONS v1\] (\d+)/(\d+): ")
_GEN_CONST_DONE_RE = re.compile(r"\[CONSTELLATIONS v1\] Done\. New hits this run")
_GEN_HYBRID_STAGE_RE = re.compile(r"\[HYBRID\] stage (\d+)/(\d+):")
_GEN_HYBRID_DONE_RE = re.compile(r"\[HYBRID\] done:")
_LOOP_SESSION_START_RE = re.compile(
    r"\[LOOP\] orchestrator_loop_v2 \S+ \(parallel instances\): (\d+) iteration\(s\)")
_LOOP_ITERATION_START_RE = re.compile(r"\[LOOP\] iteration (\d+)/(\d+): launching")
_LOOP_SESSION_DONE_RE = re.compile(
    r"\[LOOP\] (?:All iterations complete|Stopped early) in [\d.]+s total\.")


class WslLoggedRunner:
    """Runs a WSL command with output redirected to files on disk (build_wsl_logged_
    command()) instead of relying on subprocess.PIPE against wsl.exe's own stdout.

    A pipe-based approach doesn't work reliably here: launching wsl.exe from a
    console-less parent process (this is a windowed tkinter app, not a console app) can
    make Windows/WSL's own console-allocation machinery open a SEPARATE, real terminal
    window that receives the script's actual output, while the pipe this app reads from
    gets nothing and never sees EOF -- so the app never learns the run finished. A
    terminal window shows the script running, but neither the user nor the app itself
    can tell from its own UI whether or when the run finished. Redirecting entirely on
    the Linux side sidesteps that: the log/exit-code
    files are ordinary files on the same Windows drive both Windows and WSL already share,
    tailed directly with plain Python file I/O on a background daemon thread -- no pipe,
    no console, no WSL console-interop quirks anywhere in the actual data path, whatever
    window WSL itself chooses to pop up (or not) along the way.

    `output_queue` receives plain text chunks, then a final ("__exit__", returncode)
    sentinel tuple once the run is done (returncode
    is None if the run never started, or if the wrapper process ended without ever
    writing the exit-code file -- see the grace-period handling in _tail_loop()) -- so
    the GUI polling code (_drain_output_queue) needed no changes to support this class.

    stop() remains best-effort for the reason above (WSL's process-lifecycle model
    doesn't guarantee terminate()ing the Windows-side wrapper kills the Linux process
    underneath) -- this additionally fires a one-shot `wsl.exe -e pkill -f kill_pattern`
    as a second, independent attempt at reaching the actual Linux process tree. Matching
    by substring against the running command line is safe here specifically because the
    GUI only ever allows one instance of a given script to run at a time (see the
    is_running() checks in _on_run_loop/_on_run_constellation) -- kill_pattern is that
    script's own filename, which should not collide with anything else.

    No tkinter dependency -- exercised directly (substituting a plain `bash -c` command
    for the `wsl.exe -e bash -c` form, since this class only cares about the log/exit
    FILES, not what actually wrote them) without a display or a real WSL install."""

    POLL_INTERVAL = 0.2
    EXIT_MARKER_GRACE_SECONDS = 2.0

    def __init__(self, cmd, log_path, exit_path, output_queue, kill_pattern=None):
        self.cmd = cmd
        self.log_path = log_path
        self.exit_path = exit_path
        self.output_queue = output_queue
        self.kill_pattern = kill_pattern
        self.proc = None
        self._thread = None

    def start(self):
        self.output_queue.put(f"$ {' '.join(self.cmd)}\n")
        try:
            self.proc = subprocess.Popen(self.cmd, **_popen_kwargs_no_window())
        except OSError as e:
            self.output_queue.put(f"[!] Nie udalo sie uruchomic procesu: {e}\n")
            self.output_queue.put(("__exit__", None))
            return
        self._thread = threading.Thread(target=self._tail_loop, daemon=True)
        self._thread.start()

    def _tail_loop(self):
        offset = 0
        grace_deadline = None
        try:
            while True:
                offset = self._drain_new_log_bytes(offset)
                if os.path.exists(self.exit_path):
                    time.sleep(0.1)  # let a just-flushed final write land before the
                                      # last drain, so the tail-end of the script's
                                      # output isn't cut off by a race with echo $? >
                    offset = self._drain_new_log_bytes(offset)
                    returncode = self._read_exit_code()
                    self._cleanup_files()
                    self.output_queue.put(("__exit__", returncode))
                    return
                if self.proc.poll() is not None:
                    # Wrapper process ended but never wrote the exit marker (e.g. wsl.exe
                    # itself failed before reaching the redirect) -- give the filesystem
                    # a brief grace period before giving up, rather than reporting a
                    # false failure on every ordinary run (write latency on the underlying
                    # mount is real).
                    if grace_deadline is None:
                        grace_deadline = time.time() + self.EXIT_MARKER_GRACE_SECONDS
                    elif time.time() > grace_deadline:
                        offset = self._drain_new_log_bytes(offset)
                        self.output_queue.put(
                            "[!] Proces wsl.exe zakonczyl sie bez zapisania kodu wyjscia.\n")
                        self._cleanup_files()
                        self.output_queue.put(("__exit__", None))
                        return
                time.sleep(self.POLL_INTERVAL)
        except Exception as e:  # noqa: BLE001 -- must never kill this thread silently
            self.output_queue.put(f"[!] Blad odczytu logu: {e}\n")
            self.output_queue.put(("__exit__", None))

    def _drain_new_log_bytes(self, offset):
        if not os.path.exists(self.log_path):
            return offset
        try:
            with open(self.log_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(offset)
                chunk = f.read()
                new_offset = f.tell()
        except OSError:
            return offset
        if chunk:
            self.output_queue.put(chunk)
        return new_offset

    def _read_exit_code(self):
        try:
            with open(self.exit_path, encoding="utf-8") as f:
                raw = f.read().strip()
            return int(raw)
        except (OSError, ValueError):
            return None

    def _cleanup_files(self):
        """Best-effort delete of the log/exit files once fully drained and reported --
        keeps .generation_logs/ from growing unbounded across months of runs. The GUI
        already shows the full output live in its own pane, so nothing is lost."""
        for path in (self.log_path, self.exit_path):
            try:
                os.remove(path)
            except OSError:
                pass

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass
        if self.kill_pattern:
            try:
                subprocess.Popen(["wsl.exe", "-e", "pkill", "-f", self.kill_pattern],
                                  **_popen_kwargs_no_window())
            except OSError:
                pass


def build_pip_install_argv(package, upgrade=False):
    """[sys.executable, -m, pip, install, --user, package] -- installs into the SAME
    Python environment this GUI process itself runs under (sys.executable, not a bare
    "python"/"python3" on PATH, which could resolve to a different interpreter),
    --user so no admin/venv-write permission is required. Used by the Settings tab's
    optional-library installer (Faza 2b) -- currently only sympy (see
    primeatlas/primality.py's try_import_sympy()), kept general in case a future
    optional dependency needs the same treatment."""
    argv = [sys.executable, "-m", "pip", "install", "--user"]
    if upgrade:
        argv.append("--upgrade")
    argv.append(package)
    return argv


class LocalLoggedRunner:
    """Runs an ordinary LOCAL subprocess (no WSL involved) with its stdout/stderr piped
    directly back to this process, unlike WslLoggedRunner's file-tailing approach. That
    file-tailing dance exists ONLY to work around wsl.exe's own console-allocation
    quirks when launched from a windowed (console-less) parent -- see WslLoggedRunner's
    own docstring. A plain native subprocess (e.g. `sys.executable -m pip install`) has
    none of that: it's a normal child of this same Windows process tree, so a regular
    subprocess.PIPE + line-by-line read on a background thread is both simpler and
    perfectly reliable here.

    Same output contract as WslLoggedRunner (plain text chunks on `output_queue`, then a
    final ("__exit__", returncode) sentinel) so callers that already know how to drain
    that queue (see settings_tab.py's _poll_restore_queue) don't need a second shape to
    handle -- this class is used for exactly one thing so far (the sympy installer, see
    settings_tab.py's _on_install_sympy), but kept generically named/shaped in case a
    future feature needs another local (non-WSL) subprocess with live output.

    No tkinter dependency -- exercised directly against a trivial local command (e.g.
    [sys.executable, "-c", "print('hi')"]) without any WSL install required."""

    def __init__(self, cmd, output_queue, pipe_stdin=False):
        self.cmd = cmd
        self.output_queue = output_queue
        self.proc = None
        self._thread = None
        # [ADDED 2026-09-10, Faza 13] Opt-in only -- every existing caller
        # (e.g. settings_tab.py's sympy installer) keeps stdin inherited/
        # default exactly as before. RingsTab is the first caller that
        # needs a way to send commands INTO the running subprocess (see
        # send_line() below) -- ring_viz/renderer.py's own PAUSE/RESUME
        # protocol reads them off stdin when launched with
        # --pipe-stdin-commands (see build_renderer_argv/rings_tab.py).
        self._pipe_stdin = pipe_stdin

    def start(self):
        self.output_queue.put(f"$ {' '.join(self.cmd)}\n")
        # _popen_kwargs_no_window() already sets stdout=DEVNULL/stderr=DEVNULL (the
        # right default for WslLoggedRunner/env_setup.py's fire-and-forget callers,
        # which don't want piped output at all) -- this class DOES need piped output,
        # so those two keys must be overridden in the dict rather than also passed as
        # separate keyword args to Popen(), which raised "got multiple values for
        # keyword argument 'stdout'" the first time this path was actually exercised
        # for real (RingsTab's launch, 2026-09-04 -- every earlier caller of this
        # class, e.g. settings_tab.py's sympy installer, apparently never hit this
        # live before).
        kwargs = _popen_kwargs_no_window()
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.STDOUT
        if self._pipe_stdin:
            kwargs["stdin"] = subprocess.PIPE
        try:
            self.proc = subprocess.Popen(self.cmd, text=True, bufsize=1, **kwargs)
        except OSError as e:
            self.output_queue.put(f"[!] Could not start process: {e}\n")
            self.output_queue.put(("__exit__", None))
            return
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def send_line(self, text):
        """[ADDED 2026-09-10, Faza 13] Write one line to the subprocess's
        stdin (only meaningful when started with pipe_stdin=True -- a no-op,
        not an error, otherwise, since a caller checking is_running() first
        has no easy way to know in advance whether stdin was piped). Used by
        RingsTab to send "RESUME" while the renderer is idling in its own
        paused/hidden state -- see that class's own PAUSE/RESUME doc-comment.
        Swallows a broken pipe (process already gone) same as stop() does,
        since the caller's next _poll_queue tick will see the __exit__
        sentinel regardless and react to that instead."""
        if self.proc is None or self.proc.stdin is None:
            return
        try:
            self.proc.stdin.write(text.rstrip("\n") + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def _read_loop(self):
        try:
            for line in self.proc.stdout:
                self.output_queue.put(line)
            self.proc.stdout.close()
            returncode = self.proc.wait()
            self.output_queue.put(("__exit__", returncode))
        except Exception as e:  # noqa: BLE001 -- must never kill this thread silently
            self.output_queue.put(f"[!] Error reading process output: {e}\n")
            self.output_queue.put(("__exit__", None))

    def is_running(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass
