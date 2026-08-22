import sys
import os
import csv
import bisect
import math
import re
import datetime
import json
import threading
import queue
import subprocess
import shlex
import time
import webbrowser

# ==========================================================================================
# PrimeAtlas -- a tkinter desktop application for browsing, generating, and managing the
# prime number and constellation data produced by the sieve/orchestrator pipeline in this
# repository. It ties together mass generation and mapping of prime numbers and their
# constellations across exponents ("floors"), plus search, backup/restore, and benchmark
# tooling built around that data.
#
# On-disk data lives under a folder/environment-variable named CONSTELLATION_PORTAL /
# CONSTELLATION_PORTAL_DIR, read directly by the sieve/orchestrator/constellation scripts
# this app launches (prime_sieve_v1.py/v3.py, orchestrator_v3.py, orchestrator_loop_v2.py,
# constellation_finder_v1.py); that naming is independent of the application's display name.
#
# Purpose: browse what the scanner/orchestrator/constellation finder have actually
# produced without opening a terminal. Five tabs:
#   1) "Prime numbers" -- floor by floor, PGS2 source-window file by file (count,
#      generation time, on-demand paginated prime preview; plus a search box to jump
#      straight to a specific prime number).
#   2) "Constellations" -- floor by floor, k-tuple pattern by pattern, showing hit count,
#      the pattern's offsets/record info from pattern_catalog_v1.py, and an on-demand
#      paginated preview that reconstructs each hit's FULL tuple (starting value + fixed
#      offsets); plus a search box that reports whether a given number participates in any
#      recorded constellation and at which position of its structure.
#   3) "Generation" -- launches orchestrator_loop_v2.py (the generation pipeline) and
#      constellation_finder_v1.py (k-tuple search) directly from this GUI, via WSL, instead
#      of a manual WSL terminal + hand-typed CLI args. Two independent forms (one per
#      script), each exposing every CLI parameter those scripts have -- including
#      workers/batches_per_worker/window_count_per_run -- with live streamed output and a
#      best-effort Stop button. Form values persist to .portal_generation_settings.json
#      (loaded at startup, saved whenever a run is launched).
#   4) "Benchmark" -- a small dependency-free growth chart (seconds/10M vs. floor depth,
#      one point per floor -- latest logged run wins) above a full table view of
#      benchmark_log.csv (written by orchestrator_v1.py's print_benchmark_summary()); a
#      "Save PDF" button renders that same chart + the full table into a standalone PDF
#      report (see the hand-rolled PDF writer below render_benchmark_pdf()).
#   5) "Settings" -- storage path configuration plus backup/restore/delete of the whole
#      prime/constellation database, built object-oriented in its own package
#      (./primeatlas/) rather than as more inline functions on this already-large file.
#      primeatlas/ holds five small, independently unit-tested (no tkinter dependency),
#      single-purpose classes:
#        - AppSettings                          (app_settings.py)  -- configurable storage
#                                                  path, persisted OUTSIDE the portal folder
#                                                  itself (see that module's docstring for
#                                                  why)
#        - BackupManifest/PietroSnapshot/
#          ConstellationSnapshot                 (manifest.py)  -- a lightweight JSON
#                                                  SNAPSHOT of what floors/constellations/
#                                                  benchmark log exist -- NOT a copy of the
#                                                  actual (many-GB) prime data
#        - BackupStore                           (backup_store.py)  -- saves/lists/loads
#                                                  those manifests under <storage>/_backups/
#        - RestoreJob                            (restore_job.py)  -- checkpointed,
#                                                  pausable/resumable/cancellable plan for
#                                                  regenerating whatever a backup's manifest
#                                                  says is missing from the CURRENT disk
#        - PortalWiper                           (delete_manager.py)  -- the "delete
#                                                  everything" button's actual logic
#      settings_tab.py (same package) is the only module that imports tkinter, wiring the
#      classes above into the actual Settings tab widgets. This file (prime_atlas_v1.py)
#      owns the other four tabs' UI code directly.
#
# The chosen storage path also has to reach the scripts this app launches as separate WSL
# processes (prime_sieve_v3.py, orchestrator_v3.py, orchestrator_loop_v2.py,
# constellation_finder_v1.py). All four check a CONSTELLATION_PORTAL_DIR environment
# variable first (see each file's own __main__/module-level comment) --
# build_wsl_logged_command() below prepends it to every WSL command this app launches, so
# choosing a custom path in Settings transparently affects the Generation tab's
# pipeline runs too, with no separate wiring needed.
#
# Built with tkinter (Python's standard-library GUI toolkit) specifically so it runs with
# zero extra installs on a normal Windows Python -- no pip packages required. Run directly
# (not through WSL -- this needs a display, and reading PGS2 files is pure Python, no
# ctypes/.so/primesieve dependency at all):
#   python prime_atlas_v1.py
#
# Depends on prime_sieve_v1.py (./prime_sieve/) for the PGS2 format readers and
# pattern_catalog_v1.py (./constellation/) for pattern offsets/record metadata --
# imported via sys.path, same approach orchestrator_v1.py/constellation_finder_v1.py use.
# Never touches prime_sieve_engine_v1.so (only prime_sieve_v1's lazy sieving path does).
# ==========================================================================================

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "prime_sieve"))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "constellation"))
import prime_sieve_v1  # noqa: E402
import pattern_catalog_v1  # noqa: E402
from primeatlas import (  # noqa: E402
    AppSettings, Translator, DEFAULT_LANGUAGE, prune_empty_pietro_dirs,
    run_all_tests as primality_run_all_tests, factorize as primality_factorize,
    try_import_sympy as primality_try_import_sympy,
    goldbach_check_window, goldbach_cascade_step,
    goldbach_window_rows, goldbach_all_decompositions,
    goldbach_both_base_window_rows, GOLDBACH_BOTH_BASE_PMAX_CEILING,
    GOLDBACH_BOTH_BASE_PMIN,
    goldbach_largest_prime_le, goldbach_sieve_is_prime,
)
from primeatlas import floor_meta  # noqa: E402

# AppSettings persists the chosen storage path OUTSIDE the portal folder itself (see
# app_settings.py's docstring for the chicken-and-egg reason). Loaded once here, at module
# level, BEFORE the App class is defined/instantiated -- every function in this file reads
# the bare name PORTAL_FOLDER at CALL time (not at function-definition time), so
# overwriting the global here is enough to redirect the whole app, with no changes needed
# to any of the call sites that pass PORTAL_FOLDER around explicitly.
APP_SETTINGS = AppSettings(_SCRIPT_DIR)
PORTAL_FOLDER = APP_SETTINGS.storage_path

# Every user-visible string in the GUI classes below goes through T("some.key", **kwargs)
# instead of a hardcoded literal -- see primeatlas/i18n.py's docstring for the full
# rationale (a language switch requires a RESTART, not a live re-render, since this app's
# widgets are built once at startup). Built from AppSettings.language the same way
# PORTAL_FOLDER is built from AppSettings.storage_path -- loaded once here, at module
# level, before the App class exists.
TRANSLATOR = Translator(APP_SETTINGS.language)
T = TRANSLATOR.t
PAGE_SIZE = 500  # entries per page in the preview lists -- windows/hit files can hold
                  # 100k+ entries; decoding is cached per selection, only rendering is paged.
FLOOR_PAGE_SIZE = 200  # PRIME_WINDOW_*.bin files shown per page when a floor node is
                        # expanded in the "Prime numbers" tree -- separate from PAGE_SIZE
                        # above (that one pages through prime NUMBERS inside one file; this
                        # one pages through FILES inside one floor). A floor can hold
                        # thousands of windows (10p15 alone passed 2,600+ and is still
                        # growing) -- reading every file's header AND inserting every file
                        # as a tree row on a single expand is what used to freeze the GUI.

GOLDBACH_VIZ_ROWS_PER_COL = 14  # per-n decomposition cards drawn in ONE column of the
                                  # Goldbach tab's Wizualizacja diagram before wrapping
                                  # to a new column -- see _goldbach_show_window_
                                  # visualization's multi-column layout, which fills
                                  # the window's width instead of piling every row into
                                  # one narrow strip with empty space beside it.
GOLDBACH_VIZ_MAX_COLS = 3  # cap on how many columns the card grid wraps into, so a
                             # huge window doesn't stretch the diagram absurdly wide.
GOLDBACH_CASCADE_ROW_CAP = GOLDBACH_VIZ_ROWS_PER_COL * GOLDBACH_VIZ_MAX_COLS
    # PAGE SIZE for the per-n decomposition rows, one backend goldbach_window_rows()
    # call per page (see row_offset there) -- the coverage verdict and counterexample
    # list are always computed over the FULL window regardless of which page is
    # requested. Prev/Next buttons in the Wizualizacja window (see
    # _on_goldbach_viz_row_prev/_next) step through pages of this size, per Artur's
    # request for the same kind of navigation used elsewhere for large lists (Primes
    # tab preview, benchmark log, etc. -- see _update_nav_controls).
GOLDBACH_VIZ_CHIP_ROWS_PER_PAGE = 6  # old-base prime chips: how many CHIP ROWS (not
    # individual chips -- chip_cols varies with Pmax's digit count) are shown per page
    # before Prev/Next must be used. Purely a client-side page (old_base_primes is
    # already fully computed by the backend), unlike row pagination above which needs
    # a fresh backend call per page.
GOLDBACH_DECOMPOSE_ROW_CAP = 300  # defensive cap on how many (p, q) pairs the "Rozloz
    # liczbe" detail window displays (see goldbach_all_decompositions + _goldbach_show_
    # decomposition_detail) -- the old_base_sufficient verdict and total count are
    # always computed over the FULL scan regardless of this cap, only the displayed
    # rows are truncated.

GOLDBACH_LEAN_REPO_URL = (
    "https://github.com/Flaman55/RelMathApps/tree/main/number_theory/"
    "structural_Goldbach/lean/StructuralGoldbach"
)  # points at the Lean 4 formalization backing this tab (additiveSelfContained_of_
    # hasGoldbachRep, windowCovered, the whole reduction chain) -- Artur, 2026-08-17:
    # wired in once this repo path was confirmed current (SelfContainment.lean synced
    # over and pushed, see project memory/commit history for that sync).

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

LOW_FLOOR_CUTOFF = 7  # duplicated from prime_sieve_v3.py/v4.py's own LOW_FLOOR_CUTOFF (see
                      # that constant's docstring for the full rationale: floors 0..6 are
                      # each narrower than window_m's minimum, 10,000,000, so they always
                      # get exactly ONE window file rather than window_m-sized chunks). This
                      # Windows-native module deliberately never imports prime_sieve_v3/v4
                      # (they ctypes-load a Linux .so -- see find_continuation_target_idx's
                      # docstring for why), so the value is kept in sync by hand here. Used
                      # by update_pietro_totals_cache() to decide when its own mtime-based
                      # staleness check can't be trusted (see that function's LOW-FLOOR
                      # EXCEPTION docstring paragraph).

BENCHMARK_TREE_HIDDEN_COLUMNS = {"base_exponent", "run_timestamp_utc"}  # columns dropped
                                # from the Benchmark tab's tree (not from the CSV, PDF
                                # export, or growth chart -- those still use every column).
                                # base_exponent is redundant once rows are grouped under a
                                # "10p{N}" floor node (every row repeats the same value).
                                # run_timestamp_utc is dropped as a COLUMN but not lost --
                                # it moves into the #0 "Floor / run" tree label for
                                # individual rows instead (that column sits empty for data
                                # -- see _order_benchmark_tree_columns() below for the one
                                # column whose DISPLAY position also gets adjusted
                                # rows otherwise, see _show_benchmark_page), freeing a whole
                                # column's width for the other fields that don't fit on
                                # screen at once.

def _order_benchmark_tree_columns(fieldnames):
    """Reorders the Benchmark tab's visible tree columns so loop_seconds_per_window sits
    immediately after seconds_per_window, instead of trailing at the end where it
    physically lives in benchmark_log.csv. Only the DISPLAY order changes here -- the
    CSV's own column order (and BENCHMARK_FIELDNAMES in orchestrator_v1.py etc.) is
    untouched, still append-only per the established schema-migration pattern. A no-op if
    either column is missing (older schema / already filtered out), so this is safe to
    call unconditionally."""
    fieldnames = list(fieldnames)
    if "loop_seconds_per_window" not in fieldnames or "seconds_per_window" not in fieldnames:
        return fieldnames
    fieldnames.remove("loop_seconds_per_window")
    insert_at = fieldnames.index("seconds_per_window") + 1
    fieldnames.insert(insert_at, "loop_seconds_per_window")
    return fieldnames


BENCHMARK_PAGE_SIZE = 200  # benchmark_log.csv rows shown per page when a floor node is
                            # expanded in the Benchmark tab's tree -- same reasoning as
                            # FLOOR_PAGE_SIZE above. benchmark_log.csv now gets a row per
                            # orchestrator run (including count-only/no-write benchmarking
                            # runs, which are cheap to run repeatedly), so it grows much
                            # faster than one row per floor -- inserting every row as a flat
                            # Treeview row on load is what would freeze this tab the same way
                            # the old un-paginated primes tree used to.


# ------------------------------------------------------------------------------------------
# Pure logic (no tkinter dependency) -- kept separate from the GUI classes below so it can
# be unit-tested on its own, without a display.
# ------------------------------------------------------------------------------------------

def list_pietra(portal_folder):
    """Returns sorted base_exponent ints for every 10p{N} folder found directly under
    portal_folder (regardless of whether it has source_primes/ or constellations/
    populated yet)."""
    if not os.path.isdir(portal_folder):
        return []
    result = []
    for name in os.listdir(portal_folder):
        if name.startswith("10p") and name[3:].isdigit():
            if os.path.isdir(os.path.join(portal_folder, name)):
                result.append(int(name[3:]))
    return sorted(result)


def list_source_files(portal_folder, base_exponent):
    """Returns a list of (filename, full_path, header_dict) for every PRIME_WINDOW_*.bin
    under 10p{base_exponent}/source_primes/, sorted into ascending window order (by the
    base prime in each file's header -- robust to filename shorthand like "10M" vs "0",
    unlike trying to re-parse format_offset()'s abbreviation back into a number). Files
    that fail to parse (corrupt/truncated) are still listed, with header=None, rather than
    silently dropped -- a browsing tool should surface problems, not hide them."""
    source_dir = os.path.join(portal_folder, f"10p{base_exponent}", "source_primes")
    if not os.path.isdir(source_dir):
        return []
    entries = []
    for name in sorted(os.listdir(source_dir)):
        if not (name.startswith("PRIME_WINDOW_") and name.endswith(".bin")):
            continue
        path = os.path.join(source_dir, name)
        try:
            header = prime_sieve_v1.read_prime_window_header(path)
        except Exception:
            header = None
        entries.append((name, path, header))

    def sort_key(entry):
        _, _, header = entry
        if header is None or header.get("base_prime") is None:
            return (1, 0, entry[0])
        return (0, header["base_prime"], entry[0])

    entries.sort(key=sort_key)
    return entries


_OFFSET_FROM_NAME_RE = re.compile(r"_off_(\d+)(M|k)?\.bin$")


def _offset_from_filename(name):
    """Cheap, I/O-free sort key: reconstructs the numeric offset directly from the
    filename's "_off_{N}[M|k]" suffix instead of opening the file to read its header.
    Safe for THIS project specifically because window_m (orchestrator_v1.WINDOW_M) is
    always a multiple of 1_000_000 -- format_offset() therefore always emits either the
    literal "0" or an exact "{N}M" form for every file this scanner actually writes, never
    the fractional/rounded "k" fallback it has for arbitrary (non-window-aligned) inputs.
    Returns None if a filename doesn't match (corrupt/foreign file) -- callers should sort
    those to the end rather than guessing at a position."""
    m = _OFFSET_FROM_NAME_RE.search(name)
    if not m:
        return None
    n = int(m.group(1))
    suffix = m.group(2)
    if suffix == "M":
        n *= 1_000_000
    elif suffix == "k":
        n *= 1_000
    return n


def list_source_filenames(portal_folder, base_exponent):
    """Cheap listing of every PRIME_WINDOW_*.bin under 10p{base_exponent}/source_primes/:
    just os.listdir() + a regex per name, NO file opens. Sorted ascending by the offset
    parsed from the filename (see _offset_from_filename) -- a floor can hold thousands of
    windows (10p15 alone is past 2,600+ and still growing), and list_source_files()'s
    per-file header read is exactly what made expanding a heavily-populated floor node
    freeze the GUI. Returns [(name, path), ...]; headers are read separately, only for
    whichever page is actually being displayed (see read_source_file_headers())."""
    source_dir = os.path.join(portal_folder, f"10p{base_exponent}", "source_primes")
    if not os.path.isdir(source_dir):
        return []
    entries = []
    for name in os.listdir(source_dir):
        if not (name.startswith("PRIME_WINDOW_") and name.endswith(".bin")):
            continue
        entries.append((_offset_from_filename(name), name))
    entries.sort(key=lambda e: (e[0] is None, e[0], e[1]))
    return [(name, os.path.join(source_dir, name)) for _offset, name in entries]


def _safe_prime_gap_margin(x):
    """Generous upper bound on the largest prime gap below x, used only to decide
    whether a storage window's sweep plausibly reached x -- real maximal gaps are much
    smaller (see e.g. Tomas Oliveira e Silva's maximal-gap tables: 34 below 10**5, 148
    below 10**7, 282 below 10**9); these constants are deliberately generous, not tight,
    since erring "too strict" only costs an extra generate-more-data prompt, while erring
    "too loose" would silently trust incomplete data (exactly the bug this function
    exists to prevent -- see read_is_prime_from_storage's own docstring)."""
    for threshold, margin in (
        (100, 10), (1_000, 20), (10_000, 40), (100_000, 80),
        (1_000_000, 150), (10_000_000, 250), (2 ** 63, 400),
    ):
        if x < threshold:
            return margin
    return 400


class MissingStorageRangeError(Exception):
    """Raised by read_is_prime_from_storage when floor `floor` does not (yet) hold
    verified data up to `needed_upto`. Carries both fields as attributes so the caller
    can build a message naming the SPECIFIC floor that's short, rather than a generic
    "storage is missing" message pointing at floor 0 regardless of which floor is
    actually the problem (see read_is_prime_from_storage's own docstring for the bug
    this replaced)."""

    def __init__(self, floor, needed_upto):
        self.floor = floor
        self.needed_upto = needed_upto
        super().__init__(f"floor {floor} missing data up to {needed_upto}")


def read_is_prime_from_storage(portal_folder, limit):
    """Builds an is_prime bytearray covering [0, limit] purely from already-generated
    floor storage (10p{N}/source_primes/PRIME_WINDOW_*.bin, PGS2 format -- see
    prime_sieve_v1.py's own format header) instead of running a fresh sieve. Used by
    the Goldbach tab's Wizualizacja feature (see _on_goldbach_visualize), per Artur's
    explicit instruction that this computation should read from the magazyn rather than
    recompute -- the per-n witness search itself still runs the exact same algorithm as
    goldbach_window.py's window_rows(), only the SOURCE of is_prime changes.

    Floors are NOT one continuous span starting at floor 0 -- each floor N covers only
    its own natural range [10**N, 10**(N+1)) (width 9*10**N), the same boundary
    enforced elsewhere in this file by _floor_window_count()/the range-clamping logic
    around "floor_boundary = 10 ** (floor_lo + 1)", and by
    prime_sieve_v4_1._low_floor_segments(). floor 0 = [1,10) (4 primes: 2,3,5,7),
    floor 1 = [10,100) (21 primes), floor 2 = [100,1000) (143 primes), and so on --
    this matches the real counts Artur's own storage reports. An EARLIER version of
    this function wrongly treated floor 0 alone as extending indefinitely in
    QUICK_GEN_MAX_WINDOW_WIDTH-wide chunks (i.e. as if floor 0 covered [1,10_000_001)),
    so e.g. limit=200 was checked entirely against floor 0's single tiny file and
    failed even though floors 0-2 were each genuinely complete -- Artur caught this
    ("piętro zero nigdy nie będzie miało 100... wartość 100 jest na piętrze 2"). This
    version instead walks floor 0, 1, 2, ... up to whichever floor's base exceeds
    limit, reading each floor's OWN files (possibly split into
    QUICK_GEN_MAX_WINDOW_WIDTH-wide window files only when a floor's natural width
    exceeds that, per prime_sieve_v1.main_batch_scanner()) and stitching their primes
    into one array.

    A window FILE existing on disk at the right offset does not by itself prove it
    actually covers the range needed -- a partial/test/interrupted-generation file can
    sit at offset 0 with only a handful of primes in it (this happened: Artur's
    storage_path at the time had exactly such a file, and an earlier version of this
    function trusted its mere existence, silently building an is_prime array that read
    as "mostly composite" above the file's real content and rendered a Wizualizacja
    diagram full of "?" instead of an honest error). So for every window needed, this
    also checks that the MAXIMUM prime actually found in that file reaches within
    _safe_prime_gap_margin() of the range it's relied on for -- short of that, the
    window is treated as not-yet-generated, same as if the file were simply missing.

    Returns an is_prime bytearray of length limit+1 if every floor needed to cover
    [0, limit] is present AND actually reaches far enough within itself; raises
    MissingStorageRangeError(floor, needed_upto) naming the SPECIFIC short floor
    otherwise -- never partially or silently truncates (a silent gap would make a
    "covered" verdict meaningless)."""
    window_m = QUICK_GEN_MAX_WINDOW_WIDTH
    if limit < 2:
        return bytearray(limit + 1)

    is_prime = bytearray(limit + 1)
    floor = 0
    while 10 ** floor <= limit:
        base = 10 ** floor
        floor_boundary = 10 ** (floor + 1)  # exclusive natural ceiling of this floor
        needed_here_top = min(limit, floor_boundary - 1)
        highest_needed_idx = (needed_here_top - base) // window_m

        files_by_idx = {}
        for name, path in list_source_filenames(portal_folder, floor):
            offset = _offset_from_filename(name)
            if offset is None:
                continue
            files_by_idx[offset // window_m] = path

        for idx in range(highest_needed_idx + 1):
            if idx not in files_by_idx:
                raise MissingStorageRangeError(floor, needed_here_top)

        for idx in range(highest_needed_idx + 1):
            window_end = base + (idx + 1) * window_m  # exclusive nominal upper bound
            needed_here = min(needed_here_top, window_end - 1)
            window_max_prime = 0
            for p in prime_sieve_v1.read_prime_window(files_by_idx[idx]):
                if p > window_max_prime:
                    window_max_prime = p
                if p <= limit:
                    is_prime[p] = 1
            margin = _safe_prime_gap_margin(max(needed_here, 2))
            if window_max_prime < needed_here - margin:
                raise MissingStorageRangeError(floor, needed_here_top)

        floor += 1
    return is_prime


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


def read_source_file_headers(entries):
    """Reads headers for a (small, page-sized) list of (name, path) tuples -- the actual
    disk I/O, deliberately kept separate from list_source_filenames() so it only ever runs
    on however many files are visible on ONE page, never the whole floor. Returns
    [(name, path, header_or_None), ...] in the same order given."""
    result = []
    for name, path in entries:
        try:
            header = prime_sieve_v1.read_prime_window_header(path)
        except Exception:
            header = None
        result.append((name, path, header))
    return result


TOTALS_CACHE_FILENAME = ".portal_totals_cache.json"


def _totals_cache_path(portal_folder):
    return os.path.join(portal_folder, TOTALS_CACHE_FILENAME)


def load_totals_cache(portal_folder):
    """Returns the persisted {"10p{N}": {"files": {filename: count, ...}, "total": T,
    "file_count": C}, ...} cache, or {} if it doesn't exist yet or is corrupt (never raises --
    a missing/bad cache just means the next update rebuilds it, same as no cache at all)."""
    path = _totals_cache_path(portal_folder)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_totals_cache(portal_folder, cache):
    """Atomic write (temp file + os.replace()), same pattern as orchestrator_v1.py's
    _ensure_benchmark_log_schema() -- this file can get large (one entry per source window,
    e.g. 15000+ for a heavily-populated floor), so a half-written file from an interrupted
    save must never be what a later load sees."""
    path = _totals_cache_path(portal_folder)
    tmp_path = f"{path}.tmp{os.getpid()}"
    try:
        os.makedirs(portal_folder, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        os.replace(tmp_path, path)
    except OSError:
        pass  # best-effort -- a failed cache save just means the next visit re-scans


def update_pietro_totals_cache(portal_folder, base_exponent, cache):
    """Computes (and caches) the TOTAL prime count across every source window file for one
    floor -- the file list on its own only shows each file's OWN count, never a sum, so
    this fills in the floor row's total. Reading every file's header for a
    heavily-populated floor is NOT cheap on this project's actual storage (~78s for one
    floor's 15,101 files, ~5ms/file -- per-file open() latency on the underlying mount,
    not the tiny header read itself) -- exactly why list_source_filenames()/
    read_source_file_headers() were already split apart for the paginated file list (see
    those functions' docstrings). This
    function makes repeat visits cheap: `cache` maps floor -> {filename: count} from the
    LAST computation, and only filenames not already in that map get their header re-read --
    files removed from disk since the last run are dropped from the map (no stale counts
    lingering forever). A floor visited for the first time still pays the full one-time
    scan cost -- callers should run this off the GUI thread (see PortalApp's background
    totals worker) so that cost is never a frozen window.

    Returns (total, file_count, newly_read_count, total_bytes) -- newly_read_count lets a
    caller report "read 42 new files" instead of re-summarizing the whole floor every
    time, useful for a status message on the (usual, fast) incremental case. total_bytes
    is the floor's on-disk footprint (sum of every source window file's size) -- tracked
    alongside count/mtime per file so it's free to report without any extra I/O beyond
    what this function was already doing (the same os.stat() call used for the mtime
    staleness check below also returns st_size).

    STALENESS NOTE: each cached entry also stores the file's mtime at the time its header
    was read, and a file gets RE-read (not just skipped because its name is already cached)
    if the current on-disk mtime no longer matches. This matters because filenames here are
    fully deterministic from floor+offset (see prime_sieve_*.py's write_prime_window path),
    NOT content-addressed -- a low floor (see LOW_FLOOR_CUTOFF in prime_sieve_v3.py/v4.py)
    always writes to the exact same single filename every time it's regenerated, so an
    in-place rewrite (e.g. redoing a floor after a bugfix, or after storage was reset and
    regenerated) previously kept serving the FIRST-ever cached count forever -- the cache
    only ever checked "have I seen this name before", never "has this name's content
    changed". Entries from before this check existed are plain ints (old schema) rather than
    {"count", "mtime"} dicts; any non-dict entry is treated as unconditionally stale so it
    gets re-read (and migrated to the new shape) the first time this runs against an old
    cache file, rather than silently trusting a count with no known mtime.

    LOW-FLOOR EXCEPTION: mtime alone turned out to be unreliable in practice for floors
    below LOW_FLOOR_CUTOFF -- this project's storage drive is FUSE/WSL-mounted (see the
    known git-on-that-drive unlink/rename quirk elsewhere in this codebase's history), and
    the Windows-side os.path.getmtime() this function relies on can keep reporting a stale
    cached stat for a file just rewritten from the WSL side, for longer than this app's
    Refresh-then-recompute cycle. A low floor never has more than ONE file (its whole width
    is always < window_m -- see LOW_FLOOR_CUTOFF's own rationale), so the caching this
    mtime check exists for barely matters there anyway: unconditionally re-reading a low
    floor's single file every call costs one extra ~5ms open, not the "78s across 15,101
    files" cost this whole cache exists to avoid for a heavily-populated NORMAL floor."""
    key = f"10p{base_exponent}"
    entry = cache.setdefault(key, {"files": {}})
    cached_files = entry.setdefault("files", {})

    filenames = list_source_filenames(portal_folder, base_exponent)
    current_names = {name for name, _path in filenames}

    for stale_name in list(cached_files.keys()):
        if stale_name not in current_names:
            del cached_files[stale_name]

    always_refresh = base_exponent < LOW_FLOOR_CUTOFF
    to_read = []
    stats = {}
    for name, path in filenames:
        try:
            st = os.stat(path)
            stats[name] = (st.st_mtime, st.st_size)
        except OSError:
            stats[name] = (None, 0)
        cached = cached_files.get(name)
        mtime, _size = stats[name]
        if always_refresh or not isinstance(cached, dict) or cached.get("mtime") != mtime:
            to_read.append((name, path))

    if to_read:
        for name, path, header in read_source_file_headers(to_read):
            mtime, size = stats[name]
            cached_files[name] = {
                "count": header["count"] if header is not None else 0,
                "mtime": mtime,
                "size": size,
            }

    # Backfill "size" for entries that were already up to date (mtime matched, so skipped
    # above) but predate this field being tracked -- keeps total_bytes accurate without
    # forcing a full header re-read just to learn a file's size, since the size was
    # already sitting in `stats` from the os.stat() call above regardless.
    for name, _path in filenames:
        entry_file = cached_files.get(name)
        if isinstance(entry_file, dict) and "size" not in entry_file:
            entry_file["size"] = stats[name][1]

    total = sum(v["count"] for v in cached_files.values())
    total_bytes = sum(v.get("size", 0) for v in cached_files.values())
    entry["total"] = total
    entry["file_count"] = len(cached_files)
    entry["total_bytes"] = total_bytes
    return total, len(cached_files), len(to_read), total_bytes


def hit_file_path(portal_folder, base_exponent, k, variant_id):
    """Same layout as constellation_finder_v1.hit_file_path() -- not imported from there
    directly (a browsing tool depending on the heavy analysis script felt backwards); this
    is deliberately kept in sync with that function instead."""
    return os.path.join(
        portal_folder, f"10p{base_exponent}", "constellations", f"k{k}", f"variant{variant_id}",
        f"HITS_10p{base_exponent}_k{k}_v{variant_id}.bin")


def floor_has_constellation_hits(portal_folder, base_exponent):
    """Cheap existence check -- does floor `base_exponent` have AT LEAST ONE constellation
    hit file on disk, without reading the pattern catalog or any file header (unlike
    list_constellation_hits() below, which is only called once a floor's tree node is
    actually expanded). Used by reload_constellations_tree() to decide which floors to
    list AT ALL -- a floor can have plenty of prime data but zero constellation hits (the
    finder hasn't been run against it yet, or ran and found nothing), and listing it
    anyway with an empty "no hits" placeholder just clutters the tree with entries there is
    nothing to actually browse. Short-circuits on the first hit file found rather than
    counting every one, same reasoning find_highest_populated_floor() above short-circuits
    on the first (highest) populated floor."""
    const_dir = os.path.join(portal_folder, f"10p{base_exponent}", "constellations")
    if not os.path.isdir(const_dir):
        return False
    for k_name in os.listdir(const_dir):
        k_path = os.path.join(const_dir, k_name)
        if not os.path.isdir(k_path):
            continue
        for variant_name in os.listdir(k_path):
            variant_path = os.path.join(k_path, variant_name)
            if not os.path.isdir(variant_path):
                continue
            for fname in os.listdir(variant_path):
                if fname.startswith("HITS_") and fname.endswith(".bin"):
                    return True
    return False


def list_constellation_hits(portal_folder, base_exponent):
    """Returns [(pattern_dict, path, header_or_None), ...] for every catalog pattern that
    has an existing hit file for this floor (i.e. constellation_finder_v1 has found at
    least one match), sorted by (k, id)."""
    entries = []
    for pattern in sorted(pattern_catalog_v1.PATTERN_CATALOG, key=lambda w: (w["k"], w["id"])):
        path = hit_file_path(portal_folder, base_exponent, pattern["k"], pattern["id"])
        if not os.path.exists(path):
            continue
        try:
            header = prime_sieve_v1.read_prime_window_header(path)
        except Exception:
            header = None
        entries.append((pattern, path, header))
    return entries


def group_constellation_hits_by_k(entries):
    """Groups list_constellation_hits()'s flat (pattern, path, header) list into
    [(k, k_total, [(pattern, path, header), ...]), ...] sorted ascending by k -- fills in
    the "how many k-tuples do I have in total for this k" figure that the tree's per-variant
    hit counts alone don't show (e.g. k=7 v=1: 136, k=7 v=2: 131, but never their sum).
    Cheap by construction -- the pattern catalog itself is
    small (currently 48 entries across all k), so list_constellation_hits() already reads
    every existing hit file's header for a floor in one shot; this just re-groups that
    already-fetched data, no extra I/O. Rows with header=None (corrupt/unreadable hit file)
    count as 0 toward k_total rather than breaking the sum."""
    groups = {}
    for pattern, path, header in entries:
        k = pattern["k"]
        groups.setdefault(k, []).append((pattern, path, header))
    result = []
    for k in sorted(groups):
        variants = groups[k]
        k_total = sum(header["count"] for _pattern, _path, header in variants if header is not None)
        result.append((k, k_total, variants))
    return result


def build_constellation_records_table(portal_folder, k, floor_min=None, floor_max=None):
    """Scans the user's OWN storage (constellations/k{k}/variant{id}/HITS_....bin -- NOT
    pzktupel.de) for every floor that has at least one hit file for pattern `k`, building
    a pzktupel.de-style exp x variant table: for each floor and each of k's catalog
    variants, the SMALLEST offset above that floor's own 10**base_exponent found among
    this project's own hits so far (hit files store sorted ascending starting values --
    see constellation_finder_v1.py's own module header -- so the smallest is simply the
    first stored value, no need to read/compare the whole file by hand).

    `floor_min`/`floor_max` (both optional, inclusive): scope the scan to a specific
    piętro/floor range instead of every floor in storage. Added because a project with
    many populated floors makes the unscoped table both slow to build and noisy to read
    (mostly "-" cells for floors the user isn't currently interested in) -- passing
    bounds lets the caller match the curated exp range pzktupel.de's own reference
    tables show (e.g. only exp 10..19) instead of dumping the whole storage. None means
    unbounded on that side, matching the pre-existing (pre-filter) behaviour when both
    are omitted.

    `is_record_floor` flags a cell whose floor happens to equal the pzktupel.de catalog's
    own record_digits - 1 (a D-digit record lives in floor D-1, since floor N holds
    [10**N, 10**(N+1))) -- this is a same-floor COINCIDENCE flag, not a verified match:
    the catalog only stores the record holder's digit count, not its exact offset, so
    there's no way to confirm this project's own find is the SAME number as the cited
    record without that offset. Still useful context (a hit on that exact floor is
    exactly where pzktupel.de's own record-holder would live), so it's surfaced as
    `pattern_meta[vid]` (discoverer/date/record_digits) for the caller to display
    alongside the flag rather than making a claim this function can't back up.

    Returns (variant_ids, variant_meta, rows):
      variant_ids: this k's catalog ids in order (column order for a table/tree/export)
      variant_meta: {id: pattern_dict} (offsets/record_digits/discoverer/date)
      rows: [{"base_exponent": int, "cells": {id: cell_or_None}}, ...] sorted ascending
            by base_exponent, one row per floor (within [floor_min, floor_max] when
            given) that has AT LEAST ONE hit for this k (floors with zero hits for k,
            even if they have hits for some OTHER k, are skipped -- nothing to show).
            cell_or_None is None when this floor has no hit file for that particular
            variant, else {"offset": int, "count": int, "is_record_floor": bool}.

    Pure function (no tkinter), reusing list_pietra()/floor_has_constellation_hits()/
    hit_file_path() exactly as reload_constellations_tree() already does, so this is
    consistent with (and no more expensive than) the existing storage browser -- the one
    added cost is prime_sieve_v1.read_prime_window() per (floor, variant) that actually
    has a hit file, to get that file's first (smallest) stored value."""
    variants = pattern_catalog_v1.patterns_for_k(k)
    variant_ids = [w["id"] for w in variants]
    variant_meta = {w["id"]: w for w in variants}
    rows = []
    for base_exponent in list_pietra(portal_folder):
        if floor_min is not None and base_exponent < floor_min:
            continue
        if floor_max is not None and base_exponent > floor_max:
            continue
        if not floor_has_constellation_hits(portal_folder, base_exponent):
            continue
        cells = {}
        any_hit = False
        for vid in variant_ids:
            path = hit_file_path(portal_folder, base_exponent, k, vid)
            cell = None
            if os.path.exists(path):
                try:
                    values = prime_sieve_v1.read_prime_window(path)
                except Exception:
                    values = []
                if values:
                    smallest = values[0]
                    offset = smallest - 10 ** base_exponent
                    record_digits = variant_meta[vid]["record_digits"]
                    is_record_floor = (record_digits is not None
                                        and base_exponent == record_digits - 1)
                    cell = {"offset": offset, "count": len(values),
                            "is_record_floor": is_record_floor}
                    any_hit = True
            cells[vid] = cell
        if any_hit:
            rows.append({"base_exponent": base_exponent, "cells": cells})
    return variant_ids, variant_meta, rows


def build_constellation_records_detail_rows(portal_folder, k, floor_min=None, floor_max=None):
    """Full-detail companion to build_constellation_records_table(): instead of just the
    smallest offset per (floor, variant) cell, returns ONE row per individual hit --
    every tuple-start value found in every hit file for `k` within the given floor
    range, not only the record-setting smallest one. Same floor_min/floor_max
    semantics (inclusive, None = unbounded) as build_constellation_records_table().

    Added for the PDF/CSV export buttons specifically (user request: the exported
    file should contain every hit this project has found for the currently displayed
    floor range, not just the compact one-cell-per-floor summary) -- the on-screen
    tree keeps showing the compact view (see build_constellation_records_table()'s own
    docstring for why that's the right shape for browsing), and
    _on_const_records_cell_activate() gives the same full list on-demand for a single
    cell inside the GUI itself without needing an export.

    Returns (variant_ids, variant_meta, rows):
      rows: [{"base_exponent": int, "variant_id": int, "offset": int, "number": int,
              "position_in_file": int, "count_in_file": int, "is_record_floor": bool},
             ...] sorted by (base_exponent, variant_id, offset) ascending -- offset
      ascending is automatic since hit files store values sorted ascending (see
      constellation_finder_v1.py's own module header) and offset = number - floor's
      10**base_exponent preserves that ordering.

    Can read a LOT of data for a long-running project (every hit, not just one per
    cell) -- callers should keep this off the GUI thread, same as
    build_constellation_records_table()."""
    variants = pattern_catalog_v1.patterns_for_k(k)
    variant_ids = [w["id"] for w in variants]
    variant_meta = {w["id"]: w for w in variants}
    rows = []
    for base_exponent in list_pietra(portal_folder):
        if floor_min is not None and base_exponent < floor_min:
            continue
        if floor_max is not None and base_exponent > floor_max:
            continue
        if not floor_has_constellation_hits(portal_folder, base_exponent):
            continue
        base = 10 ** base_exponent
        for vid in variant_ids:
            path = hit_file_path(portal_folder, base_exponent, k, vid)
            if not os.path.exists(path):
                continue
            try:
                values = prime_sieve_v1.read_prime_window(path)
            except Exception:
                values = []
            record_digits = variant_meta[vid]["record_digits"]
            is_record_floor = (record_digits is not None
                                and base_exponent == record_digits - 1)
            for position, value in enumerate(values):
                rows.append({
                    "base_exponent": base_exponent, "variant_id": vid,
                    "offset": value - base, "number": value,
                    "position_in_file": position, "count_in_file": len(values),
                    "is_record_floor": is_record_floor,
                })
    return variant_ids, variant_meta, rows


def render_constellation_records_pdf(path, k, fieldnames, rows, translator=None):
    """Writes a standalone PDF report of one k's records table (see
    build_constellation_records_table()) to `path` -- same low-level PDF-writing
    machinery (_write_pdf/_pdf_text_op/_pdf_rect_op, cell-truncation table layout) as
    render_benchmark_pdf(), just without a chart (this table has no time-series data to
    plot) and with a dynamic column count (1 + however many catalog variants k has,
    instead of a fixed benchmark_log.csv column set). `fieldnames`/`rows` are plain
    dicts, same shape render_benchmark_pdf() takes, built by the GUI layer
    (_export_const_records_pdf) from the last computed records table -- pure function
    (no tkinter), exercisable directly without a display.

    translator (optional): a primeatlas.i18n.Translator instance, for the title/subtitle/
    continuation-page chrome -- defaults to DEFAULT_LANGUAGE if not given, same as
    render_benchmark_pdf()."""
    t = (translator or Translator(DEFAULT_LANGUAGE)).t
    page_w, page_h = 841.89, 595.28  # A4 landscape, points -- same as render_benchmark_pdf
    margin = 30
    content_left = margin
    content_width = page_w - 2 * margin
    content_top = page_h - margin
    content_bottom = margin

    font_size = 8
    row_h = 14
    header_h = 16
    n_cols = max(1, len(fieldnames))
    col_w = content_width / n_cols
    max_chars = max(3, int(col_w / (0.6 * font_size)))

    def cell_text(value):
        s = "" if value is None else str(value)
        if len(s) > max_chars:
            s = s[:max(0, max_chars - 3)] + "..."
        return s

    def draw_table_header(ops, y_top):
        ops.append(_pdf_rect_op(content_left, y_top - header_h, content_width, header_h,
                                 fill_rgb=(0.90, 0.90, 0.90)))
        for i, name in enumerate(fieldnames):
            ops.append(_pdf_text_op(content_left + i * col_w + 2, y_top - header_h + 4,
                                     font_size, "Helvetica-Bold", cell_text(name)))
        return y_top - header_h

    def draw_table_rows(ops, y_top, row_slice):
        y = y_top
        for row in row_slice:
            for i, name in enumerate(fieldnames):
                ops.append(_pdf_text_op(content_left + i * col_w + 2, y - row_h + 4,
                                         font_size, "Courier", cell_text(row.get(name, ""))))
            y -= row_h
        return y

    pages = []
    ops = []
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ops.append(_pdf_text_op(content_left, content_top - 14, 14, "Helvetica-Bold",
                             _pdf_ascii_fold(t("const_records.pdf_title", k=k))))
    ops.append(_pdf_text_op(content_left, content_top - 30, 9, "Helvetica",
                             _pdf_ascii_fold(t("const_records.pdf_subtitle", now=now_str,
                                               rows=len(rows)))))
    table_top = content_top - 46
    y_after_header = draw_table_header(ops, table_top)
    available = y_after_header - content_bottom
    rows_fit = max(0, int(available // row_h))
    draw_table_rows(ops, y_after_header, rows[:rows_fit])
    pages.append(ops)

    remaining = rows[rows_fit:]
    page_num = 2
    while remaining:
        ops = []
        ops.append(_pdf_text_op(content_left, content_top - 12, 10, "Helvetica-Bold",
                                 _pdf_ascii_fold(t("const_records.pdf_continued", page=page_num))))
        table_top = content_top - 22
        y_after_header = draw_table_header(ops, table_top)
        available = y_after_header - content_bottom
        rows_fit = max(1, int(available // row_h))
        chunk = remaining[:rows_fit]
        draw_table_rows(ops, y_after_header, chunk)
        pages.append(ops)
        remaining = remaining[len(chunk):]
        page_num += 1

    _write_pdf(path, pages, page_size=(page_w, page_h))


def format_big_int(n, head=12, tail=6):
    """Shortens a huge integer for display: keeps the first `head` and last `tail` digits,
    elides the middle with "...". This is just for compact display in a tree/list widget;
    full-precision values are always used for any actual computation."""
    if n is None:
        return "-"
    s = str(n)
    if len(s) <= head + tail + 3:
        return s
    return f"{s[:head]}...{s[-tail:]} ({len(s)} digits)"


_DECIMAL_COMMA_RE = re.compile(r'^-?\d+,\d+$')


def _normalize_decimal_commas(row):
    """Fixes numeric fields that got re-written with a comma decimal separator (e.g.
    "236228657,66" instead of "236228657.66") -- happens if benchmark_log.csv is ever opened
    and re-saved in a spreadsheet app under a locale that uses comma-as-decimal (e.g.
    deleting rows in Excel under a Polish locale re-exports every numeric field this way,
    silently breaking the growth chart -- aggregate_benchmark_growth()/
    aggregate_benchmark_fair_spw()/benchmark_row_stats() all call float() on these columns,
    which raises ValueError on a comma decimal and gets caught+skipped, so the chart just
    quietly lost almost every point). Only touches values matching digits-comma-digits
    exactly (e.g. "1/1" in instance_of_n, or a plain int like "1000", are left alone) --
    same regex used for the one-off CSV repair that fixed the existing file. Mutates and
    returns `row` in place."""
    for k, v in row.items():
        if v and _DECIMAL_COMMA_RE.match(v):
            row[k] = v.replace(",", ".")
    return row


def read_benchmark_log(portal_folder):
    """Returns (fieldnames, rows) from CONSTELLATION_PORTAL/benchmark_log.csv, or
    ([], []) if the file doesn't exist yet (no benchmarked runs so far). Numeric fields are
    normalized to a period decimal separator on read (see _normalize_decimal_commas()) --
    tolerates the file having been re-saved with comma decimals by a spreadsheet app,
    regardless of whether the on-disk file itself has been repaired."""
    log_path = os.path.join(portal_folder, "benchmark_log.csv")
    if not os.path.exists(log_path):
        return [], []
    with open(log_path, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = [_normalize_decimal_commas(row) for row in reader]
    return fieldnames, rows


def aggregate_benchmark_growth(rows):
    """Reduces benchmark_log.csv rows to one (base_exponent, loop_numbers_per_second) point per
    floor, for the "cost growth by depth" chart. loop_numbers_per_second is the real
    session-level throughput (total numbers swept across all concurrent instances / real
    wall-clock time of the orchestrator_loop run -- see _tag_single_benchmark_row() /
    _tag_benchmark_rows_by_range() in orchestrator_loop_v1.py/v2.py), used directly as the
    y-value -- higher is better, unlike the old seconds_per_window metric which got WORSE
    (higher) as more concurrent instances were added even though wall-clock throughput
    actually improved. When a floor has multiple logged runs (re-benchmarked after a
    scanner change, or just run again), the LAST row for that floor wins: rows are appended
    in chronological order, so this reflects the most recent measurement instead of blending
    old and new tool versions together into one misleading average. Rows predating this
    column (blank loop_numbers_per_second) or with unparseable values are skipped rather than
    raising -- older floor depths simply won't have a point until re-benchmarked through
    orchestrator_loop. Returns a list of (base_exponent, loop_numbers_per_second) sorted
    ascending by base_exponent."""
    latest = {}
    for row in rows:
        try:
            base_exponent = int(row.get("base_exponent", ""))
            numbers_per_second = float(row.get("loop_numbers_per_second", ""))
        except (TypeError, ValueError):
            continue
        if math.isnan(numbers_per_second):
            continue
        latest[base_exponent] = numbers_per_second
    return sorted(latest.items())


def aggregate_benchmark_fair_spw(rows):
    """Same reduction as aggregate_benchmark_growth() (last row per floor wins, missing/
    unparseable values skipped), but for loop_seconds_per_window instead of
    loop_numbers_per_second -- a second growth-chart line restoring a seconds/window-shaped
    view alongside n/s, but computed FAIRLY (loop_total_seconds / total_windows across the
    whole concurrent group) instead of the old
    per-instance seconds_per_window, which punished splitting into more instances. Independent
    reduction from aggregate_benchmark_growth() -- a floor could in principle have one column
    populated and not the other (shouldn't happen for rows written after this feature, both
    get stamped together, but kept independent for the same robustness reason the two columns
    are independent in the CSV). Returns (base_exponent, loop_seconds_per_window) pairs sorted
    ascending by base_exponent."""
    latest = {}
    for row in rows:
        try:
            base_exponent = int(row.get("base_exponent", ""))
            seconds_per_window_fair = float(row.get("loop_seconds_per_window", ""))
        except (TypeError, ValueError):
            continue
        if math.isnan(seconds_per_window_fair):
            continue
        latest[base_exponent] = seconds_per_window_fair
    return sorted(latest.items())


def aggregate_benchmark_sieve_nps(rows):
    """Reduces benchmark_log.csv rows to one (base_exponent, sieve_numbers_per_second) point
    per floor -- the pure sieve-phase throughput (numbers swept / sieve_seconds), isolated
    from base-gen and disk-write time. Only populated for rows logged by prime_sieve_v4_1.py
    (SCANNER_VERSION="v4.1" -- see orchestrator_v3.py's BENCHMARK_FIELDNAMES comment); rows
    from v3/v4 leave sieve_seconds blank and are skipped, same as any unparseable value.
    windows_written * QUICK_GEN_MAX_WINDOW_WIDTH approximates the numbers actually swept --
    window_m itself isn't a logged CSV column (every run in practice uses the same fixed
    window width), so this reuses the same fixed-window-width assumption
    _floor_window_count() already makes elsewhere in this file rather than introducing a new
    one. Same last-row-per-floor-wins / skip-unparseable-or-non-positive reduction as
    aggregate_benchmark_growth(). Returns (base_exponent, sieve_numbers_per_second) pairs
    sorted ascending by base_exponent."""
    latest = {}
    for row in rows:
        try:
            base_exponent = int(row.get("base_exponent", ""))
            windows_written = int(row.get("windows_written", ""))
            sieve_seconds = float(row.get("sieve_seconds", ""))
        except (TypeError, ValueError):
            continue
        if sieve_seconds <= 0 or math.isnan(sieve_seconds):
            continue
        latest[base_exponent] = windows_written * QUICK_GEN_MAX_WINDOW_WIDTH / sieve_seconds
    return sorted(latest.items())


def aggregate_benchmark_write_mbps(rows):
    """Same reduction as aggregate_benchmark_sieve_nps() (last row per floor wins, only
    prime_sieve_v4_1.py rows have this data, missing/unparseable/non-positive values
    skipped), but for the disk-write phase: bytes_written / write_seconds, in MB/s -- the
    same figure orchestrator_v3.py's print_benchmark_summary() already prints inline next
    to 'write {write_seconds}s', just aggregated per floor here for the chart/PDF. Returns
    (base_exponent, write_mb_per_second) pairs sorted ascending by base_exponent."""
    latest = {}
    for row in rows:
        try:
            base_exponent = int(row.get("base_exponent", ""))
            bytes_written = float(row.get("bytes_written", ""))
            write_seconds = float(row.get("write_seconds", ""))
        except (TypeError, ValueError):
            continue
        if write_seconds <= 0 or math.isnan(write_seconds) or math.isnan(bytes_written):
            continue
        latest[base_exponent] = bytes_written / write_seconds / 1e6
    return sorted(latest.items())


def format_duration(seconds):
    """H h M m S s, dropping leading zero units. Duplicated (not imported) from
    orchestrator_v3.py's own format_duration() -- this GUI module deliberately doesn't
    import the WSL-only orchestrator scripts directly (see the Generation tab's own note
    on why orchestrator_loop_v2 is launched as a subprocess instead), so small pure-Python
    helpers like this one get a local copy rather than a cross-module dependency."""
    if seconds is None:
        return "?"
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def format_bytes(n):
    """Plain binary-unit (B/KiB/MiB/GiB/TiB) byte count formatter, one decimal place
    (none for bytes), unit picked by magnitude -- same spirit as format_duration above
    (small, local, no need to pull in a dependency for something this short). None/
    negative input -> "?", matching format_duration's own None handling."""
    if n is None or n < 0:
        return "?"
    n = float(n)
    if n < 1024:
        return f"{n:.0f} B"
    for unit in ("KiB", "MiB", "GiB"):
        n /= 1024
        if n < 1024:
            return f"{n:.1f} {unit}"
    return f"{n / 1024:.1f} TiB"


def aggregate_write_seconds_by_pietro(rows):
    """Sums total_seconds per floor across every benchmark_log.csv row that ACTUALLY wrote
    files (write_files=="1"), skipping write_files=False count-only benchmark rows entirely
    -- otherwise a floor that was also re-benchmarked in count-only mode (same
    base_exponent/range, much faster since it skips disk I/O) would have its "how long did
    this floor really take to generate" figure polluted by runs that produced no files at
    all -- counting numbers without writing files needs to stay distinct from counting with
    writes. Rows predating the write_files
    column (blank -- see orchestrator_v3.py's BENCHMARK_FIELDNAMES comment) are skipped too,
    same as an unparseable row -- no way to know after the fact which mode they ran in.
    Returns {base_exponent: total_seconds}."""
    totals = {}
    for row in rows:
        if row.get("write_files") != "1":
            continue
        try:
            base_exponent = int(row.get("base_exponent", ""))
            seconds = float(row.get("total_seconds", ""))
        except (TypeError, ValueError):
            continue
        if math.isnan(seconds):
            continue
        totals[base_exponent] = totals.get(base_exponent, 0.0) + seconds
    return totals


def group_benchmark_rows_by_pietro(rows):
    """Splits benchmark_log.csv rows into {base_exponent: [rows...]}, preserving each
    floor's rows in their original (chronological, CSV-append) order. Rows with a missing
    or unparseable base_exponent are skipped -- same defensive approach as
    aggregate_benchmark_growth(). Used by the Benchmark tab to build one lazily-expandable
    tree node per floor (mirroring the "Prime numbers" tab's floor tree) instead of
    dumping every row into one flat, ever-growing table."""
    grouped = {}
    for row in rows:
        try:
            base_exponent = int(row.get("base_exponent", ""))
        except (TypeError, ValueError):
            continue
        grouped.setdefault(base_exponent, []).append(row)
    return grouped


def benchmark_row_stats(rows):
    """Reduces a floor's benchmark rows to {count, avg, min, max} of seconds_per_window --
    the "how fast is this floor, at a glance" summary shown at the top of an expanded
    floor node in the Benchmark tab, so the user doesn't have to page through potentially
    dozens of runs (including quick count-only benchmarking runs) to see the spread. Rows
    with a missing/unparseable/NaN seconds_per_window are skipped. Returns None if no row
    had a usable value (e.g. an empty or all-unparseable floor)."""
    values = []
    for row in rows:
        try:
            v = float(row.get("seconds_per_window", ""))
        except (TypeError, ValueError):
            continue
        if math.isnan(v):
            continue
        values.append(v)
    if not values:
        return None
    return {
        "count": len(values),
        "avg": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
    }


# ------------------------------------------------------------------------------------------
# Minimal, dependency-free PDF writer -- just enough (text, lines, filled shapes, multiple
# pages) to render the Benchmark tab's growth chart + full data table into a standalone
# report. Written by hand instead of pulling in reportlab/matplotlib, to keep this app's
# documented zero-extra-installs promise (see module header: "no pip packages required").
# Only the three standard core-14 PDF fonts are used (Helvetica, Helvetica-Bold, Courier),
# so no font embedding is needed. WinAnsiEncoding (the default PDF text encoding for these
# fonts) doesn't cover Polish diacritics -- static labels drawn via these helpers stick to
# plain ASCII; the benchmark data itself (CSV field names/values) already is. Kept in the
# "pure logic" section (no tkinter dependency) so render_benchmark_pdf() can be exercised
# without a display, same reasoning as the rest of this section.
# ------------------------------------------------------------------------------------------

def _pdf_escape(s):
    return str(s).replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


_PDF_ASCII_FOLD_MAP = str.maketrans({
    "ą": "a", "Ą": "A", "ć": "c", "Ć": "C", "ę": "e", "Ę": "E",
    "ł": "l", "Ł": "L", "ń": "n", "Ń": "N", "ó": "o", "Ó": "O",
    "ś": "s", "Ś": "S", "ź": "z", "Ź": "Z", "ż": "z", "Ż": "Z",
})


def _pdf_ascii_fold(text):
    """Strips Polish diacritics down to plain ASCII -- WinAnsiEncoding (the PDF default
    for the core-14 fonts this writer uses, see the module comment above) doesn't cover
    them at all, so a raw accented string would render as garbage/missing glyphs, not
    just "wrong language". Locale strings themselves (strings_pl.json) stay properly
    accented -- they're shared with the on-screen Tkinter UI, which renders UTF-8 fine
    -- this folding only ever happens right here, at the point text is actually drawn
    into a PDF page, for EITHER language. The report's chrome (title/subtitle/
    continuation header, axis labels) is fully translator-driven and tracks the app's
    selected language -- see render_benchmark_pdf()'s/_pdf_chart_ops()'s title/axis
    text, so no fixed-language string leaks through untranslated."""
    return text.translate(_PDF_ASCII_FOLD_MAP)


def _pdf_text_op(x, y, size, font_key, text, rgb=(0, 0, 0)):
    r, g, b = rgb
    return (f"{r:.3f} {g:.3f} {b:.3f} rg BT /{font_key} {size} Tf "
            f"1 0 0 1 {x:.2f} {y:.2f} Tm ({_pdf_escape(text)}) Tj ET")


def _pdf_line_op(x1, y1, x2, y2, width=1.0, rgb=(0, 0, 0)):
    r, g, b = rgb
    return (f"{r:.3f} {g:.3f} {b:.3f} RG {width:.2f} w "
            f"{x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")


def _pdf_rect_op(x, y, w, h, fill_rgb=None, stroke_rgb=None, width=1.0):
    ops = []
    modes = []
    if fill_rgb is not None:
        r, g, b = fill_rgb
        ops.append(f"{r:.3f} {g:.3f} {b:.3f} rg")
        modes.append("f")
    if stroke_rgb is not None:
        r, g, b = stroke_rgb
        ops.append(f"{r:.3f} {g:.3f} {b:.3f} RG {width:.2f} w")
        modes.append("S")
    mode = "B" if len(modes) == 2 else (modes[0] if modes else "n")
    ops.append(f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re {mode}")
    return " ".join(ops)


def _pdf_dot_op(cx, cy, r, rgb=(0, 0, 0)):
    """Approximates a filled circle with a small octagon -- simpler than a real bezier-curve
    circle in raw PDF content ops, and plenty smooth at chart-marker size (r ~ 2.5pt)."""
    pts = [(cx + r * math.cos(2 * math.pi * i / 8), cy + r * math.sin(2 * math.pi * i / 8))
           for i in range(8)]
    rr, gg, bb = rgb
    parts = [f"{rr:.3f} {gg:.3f} {bb:.3f} rg", f"{pts[0][0]:.2f} {pts[0][1]:.2f} m"]
    for x, y in pts[1:]:
        parts.append(f"{x:.2f} {y:.2f} l")
    parts.append("h f")
    return " ".join(parts)


def _write_pdf(path, pages, page_size=(841.89, 595.28)):
    """Writes a minimal multi-page PDF (PDF 1.4) from `pages` -- a list of lists of raw
    content-stream operator strings (see the _pdf_*_op helpers above), one list per page,
    already positioned in PDF's bottom-left-origin point space. No compression, no font
    embedding -- just objects + an xref table, which is all a plain few-hundred-row report
    needs and keeps the writer itself small enough to read/review in one sitting. Default
    page size is A4 landscape (points, 1pt = 1/72in) -- the benchmark table has enough
    columns that portrait would force an unreadably small font."""
    width, height = page_size
    objects = {}
    next_id = [1]

    def alloc(body):
        oid = next_id[0]
        next_id[0] += 1
        objects[oid] = body
        return oid

    font_ids = {}
    for name in ("Helvetica", "Helvetica-Bold", "Courier"):
        font_ids[name] = alloc(
            f"<< /Type /Font /Subtype /Type1 /BaseFont /{name} >>".encode("ascii"))

    pages_id = alloc(None)  # backfilled below, once every page object id is known
    page_ids = []
    for ops in pages:
        content = "\n".join(ops).encode("ascii", errors="replace")
        content_id = alloc(
            f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"\nendstream")
        font_res = " ".join(f"/{name} {oid} 0 R" for name, oid in font_ids.items())
        page_id = alloc(
            (f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {width:.2f} {height:.2f}] "
             f"/Resources << /Font << {font_res} >> >> /Contents {content_id} 0 R >>"
             ).encode("ascii"))
        page_ids.append(page_id)

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[pages_id] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")
    catalog_id = alloc(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii"))

    buf = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for oid in sorted(objects):
        offsets[oid] = len(buf)
        buf += f"{oid} 0 obj\n".encode("ascii")
        buf += objects[oid]
        buf += b"\nendobj\n"
    xref_offset = len(buf)
    total = len(objects) + 1
    buf += f"xref\n0 {total}\n".encode("ascii")
    buf += b"0000000000 65535 f \n"
    for oid in range(1, total):
        buf += f"{offsets[oid]:010d} 00000 n \n".encode("ascii")
    buf += (f"trailer\n<< /Size {total} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF").encode("ascii")

    with open(path, "wb") as f:
        f.write(buf)


def _pdf_chart_ops(points, x0, y0, w, h, points2=None, translator=None,
                    label_key1="bench.axis_nps", label_key2="bench.axis_spw",
                    fmt1="{:,.0f}", fmt2="{:,.3f}"):
    """Returns PDF content-stream ops drawing a (pietro, primary-series) growth chart as
    _draw_growth_chart() (same axis/tick/point layout logic), inside the box
    [x0, x0+w] x [y0, y0+h] in PDF's bottom-left-origin point space -- kept as a SEPARATE
    function rather than sharing code with the canvas version, since tkinter's Canvas anchors
    ("e", "sw", ...) and y-down coordinate system have no PDF equivalent.

    points2 (optional): a SECOND series sharing the x-axis (pietro) -- by default the 'fair'
    loop_seconds_per_window figure shown alongside n/s, but label_key2/fmt2 (see below) let
    a caller reuse this for a different pair, e.g. sieve-numbers/s + write-MB/s. Drawn as a
    red line with its OWN right-hand y-axis and its own independent scale (values are a
    different order of magnitude from the primary series, so sharing one axis would flatten
    one of the two lines into a straight line at the bottom). The x-tick set is the UNION of
    both series' base_exponent values, so a pietro present in only one series still gets an
    x-tick.

    label_key1/label_key2: i18n keys for the primary/secondary axis titles (see
    _draw_growth_chart()'s matching parameters for the full rationale) -- default to the
    original n/s + s/window pair so existing callers are unaffected.

    fmt1/fmt2: str.format() templates used for every value label drawn next to a point and
    every y-axis tick on that series' axis -- default to the original ",.0f"/",.3f"
    precision (huge integer n/s counts vs. tiny decimal s/window figures); a caller with a
    different value shape (e.g. MB/s) passes its own template instead of getting a
    precision that doesn't fit its numbers.

    translator (optional): a primeatlas.i18n.Translator instance -- axis labels reuse the
    SAME on-screen chart's i18n keys (bench.axis_pietro/no_data_chart plus whichever
    label_key1/label_key2 resolve to, see _draw_growth_chart()) instead of separate
    hardcoded PDF text, then ASCII-fold the result (see _pdf_ascii_fold()), so every axis
    label tracks the app's actual language selection instead of a fixed one. Defaults to
    DEFAULT_LANGUAGE if not given (e.g. direct/test calls)."""
    t = (translator or Translator(DEFAULT_LANGUAGE)).t
    points = points or []
    points2 = points2 or []
    ops = [_pdf_rect_op(x0, y0, w, h, stroke_rgb=(0.8, 0.8, 0.8), width=0.5)]
    if not points and not points2:
        ops.append(_pdf_text_op(x0 + w / 2 - 60, y0 + h / 2, 10, "Helvetica",
                                 _pdf_ascii_fold(t("bench.no_data_chart"))))
        return ops

    has_secondary = bool(points2)
    pad_left = 55
    pad_right = 55 if has_secondary else 15
    pad_top, pad_bottom = 20, 30
    plot_x0 = x0 + pad_left
    plot_y0 = y0 + pad_bottom
    plot_w = max(1, w - pad_left - pad_right)
    plot_h = max(1, h - pad_top - pad_bottom)

    all_xs = sorted({p[0] for p in points} | {p[0] for p in points2})
    x_min, x_max = min(all_xs), max(all_xs)
    if x_min == x_max:
        x_min -= 1
        x_max += 1

    def y_bounds(pts):
        ys = [p[1] for p in pts]
        ylo, yhi = min(ys), max(ys)
        if ylo == yhi:
            pad = max(1.0, abs(ylo) * 0.1)
            ylo -= pad
            yhi += pad
        return min(ylo, 0), yhi

    if points:
        y_min, y_max = y_bounds(points)
    if has_secondary:
        y2_min, y2_max = y_bounds(points2)

    # Horizontal inset so the leftmost/rightmost points don't sit flush against the y-axis /
    # right edge -- their value labels (drawn centered above each point) would otherwise
    # collide with the y-axis tick labels at the same height. Numbers/second values are wide
    # (12-14 digit strings), so this collision is far more visible than it was with the old
    # short 1-2 digit s/10M values.
    inset_x = max(15.0, plot_w * 0.05)

    def sx(x):
        return plot_x0 + inset_x + (x - x_min) / (x_max - x_min) * (plot_w - 2 * inset_x)

    def sy(y):
        return plot_y0 + (y - y_min) / (y_max - y_min) * plot_h

    def sy2(y):
        return plot_y0 + (y - y2_min) / (y2_max - y2_min) * plot_h

    axis_gray = (0.4, 0.4, 0.4)
    red = (0.75, 0.2, 0.2)
    ops.append(_pdf_line_op(plot_x0, plot_y0, plot_x0, plot_y0 + plot_h, rgb=axis_gray))
    ops.append(_pdf_line_op(plot_x0, plot_y0, plot_x0 + plot_w, plot_y0, rgb=axis_gray))
    if has_secondary:
        ops.append(_pdf_line_op(plot_x0 + plot_w, plot_y0, plot_x0 + plot_w, plot_y0 + plot_h,
                                 rgb=red))

    if points:
        for i in range(6):
            y_val = y_min + (y_max - y_min) * i / 5
            y_px = sy(y_val)
            ops.append(_pdf_line_op(plot_x0 - 3, y_px, plot_x0, y_px, rgb=axis_gray))
            ops.append(_pdf_text_op(plot_x0 - 50, y_px - 3, 7, "Courier", fmt1.format(y_val)))

    if has_secondary:
        for i in range(6):
            y_val = y2_min + (y2_max - y2_min) * i / 5
            y_px = sy2(y_val)
            ops.append(_pdf_line_op(plot_x0 + plot_w, y_px, plot_x0 + plot_w + 3, y_px, rgb=red))
            ops.append(_pdf_text_op(plot_x0 + plot_w + 5, y_px - 3, 7, "Courier",
                                     fmt2.format(y_val)))

    for x_val in all_xs:
        x_px = sx(x_val)
        ops.append(_pdf_line_op(x_px, plot_y0, x_px, plot_y0 - 3, rgb=axis_gray))
        ops.append(_pdf_text_op(x_px - 8, plot_y0 - 14, 7, "Courier", str(x_val)))

    ops.append(_pdf_text_op(plot_x0 + plot_w / 2 - 30, y0 + 4, 8, "Helvetica-Bold",
                             _pdf_ascii_fold(t("bench.axis_pietro"))))
    if points:
        ops.append(_pdf_text_op(x0 + 2, y0 + h - 10, 8, "Helvetica-Bold",
                                 _pdf_ascii_fold(t(label_key1))))
    if has_secondary:
        ops.append(_pdf_text_op(x0 + w - 62, y0 + h - 10, 8, "Helvetica-Bold",
                                 _pdf_ascii_fold(t(label_key2)), rgb=red))

    if points:
        if len(points) > 1:
            coords = [(sx(xv), sy(yv)) for xv, yv in points]
            for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
                ops.append(_pdf_line_op(x1, y1, x2, y2, width=1.5, rgb=(0.29, 0.56, 0.85)))
        for x_val, y_val in points:
            cx, cy = sx(x_val), sy(y_val)
            ops.append(_pdf_dot_op(cx, cy, 2.5, rgb=(0.11, 0.37, 0.66)))
            ops.append(_pdf_text_op(cx - 10, cy + 8, 7, "Courier", fmt1.format(y_val)))

    if has_secondary:
        if len(points2) > 1:
            coords2 = [(sx(xv), sy2(yv)) for xv, yv in points2]
            for (x1, y1), (x2, y2) in zip(coords2, coords2[1:]):
                ops.append(_pdf_line_op(x1, y1, x2, y2, width=1.5, rgb=red))
        for x_val, y_val in points2:
            cx, cy = sx(x_val), sy2(y_val)
            ops.append(_pdf_dot_op(cx, cy, 2.5, rgb=red))
            ops.append(_pdf_text_op(cx - 12, cy - 14, 7, "Courier", fmt2.format(y_val), rgb=red))

    return ops


def render_benchmark_pdf(path, points, fieldnames, rows, points2=None, translator=None,
                          sieve_points=None, write_points=None):
    """Writes a standalone PDF report -- the same growth chart(s) shown in the Benchmark tab
    plus the FULL benchmark_log.csv table (every row, every column) -- to `path`. The table
    continues onto as many additional (landscape A4) pages as needed, repeating the column
    header row on each one, since a project running for months can accumulate far more rows
    than fit on one page. Pure function (no tkinter) so it can be exercised/tested without a
    display -- the GUI layer (_export_benchmark_pdf) just gathers the same
    points/fieldnames/rows this app already holds for the on-screen chart/table and hands
    them here unchanged.

    points2 (optional): second (base_exponent, loop_seconds_per_window) series, drawn as a
    second red line on its own right-hand y-axis -- see _pdf_chart_ops().

    sieve_points/write_points (optional): the sieve-numbers/s and write-MB/s series from
    aggregate_benchmark_sieve_nps()/aggregate_benchmark_write_mbps() -- only populated for
    floors re-benchmarked with prime_sieve_v4_1.py, so most projects will have this empty
    for a while yet. A SECOND chart, same layout as the primary one, is only drawn (taking
    space away from the table below it) when at least one of the two is non-empty --
    otherwise page 1 looks exactly as it did before this pair of series existed, rather
    than reserving blank chart space no data will ever fill.

    translator (optional): a primeatlas.i18n.Translator instance, threaded into
    _pdf_chart_ops() and used for the title/subtitle/continuation-page header below --
    defaults to DEFAULT_LANGUAGE if not given. The title/subtitle/continuation text and
    axis labels are all translator-driven so the report is consistently in one language,
    matching whatever the app's language setting actually is, rather than mixing
    languages across different pieces of chrome. Table column headers (`fieldnames`) are
    deliberately left alone -- they're the raw benchmark_log.csv
    column names, same untranslated technical identifiers already shown as-is in the
    on-screen Benchmark tab's own Treeview (see self.benchmark_tree.heading(col,
    text=col)), not app-owned UI vocabulary."""
    t = (translator or Translator(DEFAULT_LANGUAGE)).t
    page_w, page_h = 841.89, 595.28  # A4 landscape, points
    margin = 30
    content_left = margin
    content_width = page_w - 2 * margin
    content_top = page_h - margin
    content_bottom = margin

    font_size = 6.5
    row_h = 12
    header_h = 14
    n_cols = max(1, len(fieldnames))
    col_w = content_width / n_cols
    max_chars = max(3, int(col_w / (0.6 * font_size)))  # ~0.6*size = Courier's fixed
                                                          # advance width per character

    def cell_text(value):
        s = "" if value is None else str(value)
        if len(s) > max_chars:
            s = s[:max(0, max_chars - 3)] + "..."
        return s

    def draw_table_header(ops, y_top):
        ops.append(_pdf_rect_op(content_left, y_top - header_h, content_width, header_h,
                                 fill_rgb=(0.90, 0.90, 0.90)))
        for i, name in enumerate(fieldnames):
            ops.append(_pdf_text_op(content_left + i * col_w + 2, y_top - header_h + 3,
                                     font_size, "Helvetica-Bold", cell_text(name)))
        return y_top - header_h

    def draw_table_rows(ops, y_top, row_slice):
        y = y_top
        for row in row_slice:
            for i, name in enumerate(fieldnames):
                ops.append(_pdf_text_op(content_left + i * col_w + 2, y - row_h + 3,
                                         font_size, "Courier", cell_text(row.get(name, ""))))
            y -= row_h
        return y

    pages = []

    # --- page 1: title + chart + as many table rows as fit below it ---
    ops = []
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ops.append(_pdf_text_op(content_left, content_top - 14, 14, "Helvetica-Bold",
                             _pdf_ascii_fold(t("bench.pdf_title"))))
    ops.append(_pdf_text_op(content_left, content_top - 30, 9, "Helvetica",
                             _pdf_ascii_fold(t("bench.pdf_subtitle", now=now_str,
                                               runs=len(rows), depths=len(points)))))
    has_speed_chart = bool(sieve_points) or bool(write_points)
    chart_h = 140 if has_speed_chart else 180
    chart_top = content_top - 40
    chart_y0 = chart_top - chart_h
    ops.extend(_pdf_chart_ops(points, content_left, chart_y0, content_width, chart_h,
                               points2=points2, translator=translator))

    if has_speed_chart:
        chart2_h = 140
        chart2_top = chart_y0 - 16
        chart2_y0 = chart2_top - chart2_h
        ops.extend(_pdf_chart_ops(
            sieve_points, content_left, chart2_y0, content_width, chart2_h,
            points2=write_points, translator=translator,
            label_key1="bench.axis_sieve_nps", label_key2="bench.axis_write_mbps",
            fmt1="{:,.0f}", fmt2="{:,.1f}"))
        table_top = chart2_y0 - 12
    else:
        table_top = chart_y0 - 12
    y_after_header = draw_table_header(ops, table_top)
    available = y_after_header - content_bottom
    rows_fit = max(0, int(available // row_h))
    draw_table_rows(ops, y_after_header, rows[:rows_fit])
    pages.append(ops)

    # --- continuation pages: just the table, repeating the header row ---
    remaining = rows[rows_fit:]
    page_num = 2
    while remaining:
        ops = []
        ops.append(_pdf_text_op(content_left, content_top - 12, 10, "Helvetica-Bold",
                                 _pdf_ascii_fold(t("bench.pdf_continued", page=page_num))))
        table_top = content_top - 22
        y_after_header = draw_table_header(ops, table_top)
        available = y_after_header - content_bottom
        rows_fit = max(1, int(available // row_h))  # at least 1, so a single
                                                       # oversized/edge-case row can't loop
                                                       # forever without making progress
        chunk = remaining[:rows_fit]
        draw_table_rows(ops, y_after_header, chunk)
        pages.append(ops)
        remaining = remaining[len(chunk):]
        page_num += 1

    _write_pdf(path, pages, page_size=(page_w, page_h))


def digit_count_floor(number):
    """A window at floor N holds numbers in [10^N, ...), which all have N+1 digits (in
    the overwhelming common case -- windows practically never straddle a power-of-10
    boundary). So the digit count of `number` directly tells us which floor to look in
    first, without having to scan every floor folder."""
    return len(str(number)) - 1


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


def _read_base_prime(path):
    """Just the one field find_prime_in_floor's binary search actually needs -- still a
    full header read (there's no cheaper way to get a real base_prime without opening the
    file), but callers control exactly how many of these happen, unlike the old
    list_source_files()-based approach which read every window's header unconditionally."""
    try:
        header = prime_sieve_v1.read_prime_window_header(path)
    except Exception:
        return None
    return header.get("base_prime") if header else None


def find_prime_in_floor(portal_folder, base_exponent, number):
    """Searches PGS2 source windows under 10p{base_exponent} for `number`.

    Windows are non-overlapping and written in strictly increasing target_idx order, so
    their base_primes are guaranteed ascending too -- each window's base_prime falls
    somewhere inside that window's own [start, start+window_m) range, and those ranges
    never overlap between windows. That means a binary search for the rightmost window
    with base_prime <= number identifies the ONE window whose numeric range could contain
    `number` (plus its immediate neighbor, as a constant-cost safety net against an
    off-by-one boundary edge case) -- and, critically, the search only needs to read a
    header for the O(log N) windows it actually PROBES, not every window in the floor.

    This replaced an earlier version that called list_source_files() (reads every
    window's header up front) before bisecting in memory -- fine at hundreds of windows,
    but 10p15 alone has passed 14,000: reading every header on every search made the
    feature unusably slow/freeze-prone at that scale (~14,000 file opens vs. ~14 for a
    14,000-window binary search). Listing filenames is still cheap (list_source_filenames,
    no I/O) -- only actual header reads are now bounded.

    A handful of unreadable headers along the search path (corrupt/truncated files --
    should be rare) are tolerated by trying the next index once rather than aborting the
    whole search; if that neighbor is ALSO unreadable, the search conservatively narrows
    away from that pivot instead of guessing.

    Returns a dict {name, path, primes, index} on success (index = position of `number`
    within that file's decoded, sorted prime list), or None if not found.
    """
    windows = list_source_filenames(portal_folder, base_exponent)  # cheap: no file I/O
    if not windows:
        return None
    n = len(windows)

    def _check(idx):
        name, path = windows[idx]
        try:
            primes = prime_sieve_v1.read_prime_window(path)
        except Exception:
            return None
        pos = bisect.bisect_left(primes, number)
        if pos < len(primes) and primes[pos] == number:
            return {"name": name, "path": path, "primes": primes, "index": pos}
        return None

    lo, hi = 0, n - 1
    best = -1  # rightmost index seen so far with base_prime <= number
    while lo <= hi:
        mid = (lo + hi) // 2
        bp = _read_base_prime(windows[mid][1])
        if bp is None and mid + 1 <= hi:
            mid += 1
            bp = _read_base_prime(windows[mid][1])
        if bp is None:
            hi = mid - 1
            continue
        if bp <= number:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1

    candidate_indices = []
    if best >= 0:
        candidate_indices.append(best)
    if best + 1 < n:
        candidate_indices.append(best + 1)

    for idx in candidate_indices:
        result = _check(idx)
        if result is not None:
            return result
    return None


def find_constellation_participation(portal_folder, base_exponent, number, hit_set_cache=None,
                                      progress_callback=None):
    """For every catalog pattern with an existing hit file at this floor, checks whether
    `number` participates in any recorded hit -- either as the BASE (offset +0) or as any
    other fixed-offset member (base = number - offset). A number can legitimately show up
    in more than one pattern at once (e.g. any k=4 hit's base is also, by construction, a
    k=3 and k=2 hit's base -- sub-tuples of a longer pattern), so this returns every match,
    not just the first.

    `hit_set_cache`, if given, is a dict keyed by (base_exponent, k, id) -> set of decoded
    starting values; reused across repeated searches in the same session so each hit file
    is only decoded once rather than on every search.

    `progress_callback(done, total)`, if given, is called once per pattern AFTER it's been
    processed (whether that meant a fresh, potentially slow prime_sieve_v1.read_prime_window()
    decode or a cache hit) -- a floor's FIRST-ever constellation search can decode dozens
    of full hit files synchronously (nothing cached yet), which is the actual slow part of
    this feature (find_prime_in_floor's own binary search is fast in comparison -- see
    that function's docstring). The GUI thread never
    calls this directly anymore; prime_atlas_v1's _search_worker_loop does, off the main
    thread, and turns each progress_callback invocation into a queued message that drives
    the shared status/progress bar (see _poll_search_results).

    Returns a list of dicts: {pattern, offset, position, base} (position is 0-indexed --
    0 means "this IS the base of the tuple").
    """
    if hit_set_cache is None:
        hit_set_cache = {}
    entries = list_constellation_hits(portal_folder, base_exponent)
    total = len(entries)
    results = []
    for done, (pattern, path, header) in enumerate(entries, start=1):
        if header is None or header.get("count", 0) == 0:
            if progress_callback is not None:
                progress_callback(done, total)
            continue
        key = (base_exponent, pattern["k"], pattern["id"])
        if key not in hit_set_cache:
            try:
                hit_set_cache[key] = set(prime_sieve_v1.read_prime_window(path))
            except Exception:
                hit_set_cache[key] = set()
        starts = hit_set_cache[key]
        for position, offset in enumerate(pattern["offsets"]):
            base = number - offset
            if base in starts:
                results.append({"pattern": pattern, "offset": offset, "position": position, "base": base})
        if progress_callback is not None:
            progress_callback(done, total)
    return results


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


def build_primesieve_query_argv(op, *args, script_path=None):
    """Returns the LINUX-side argv for primesieve_query.py -- the one-shot calculator CLI
    behind the 'primesieve' sub-tab (Liczby pierwsze -> primesieve). `op` is one of
    "count"/"nth"/"next"/"prev" and `args` are that operation's positional arguments, all
    passed through as plain strings (see that script's own module header for each
    operation's exact argument count) -- this function does no validation of its own,
    the query script itself rejects a malformed call and reports it as
    {"ok": false, "error": ...} rather than crashing (see run_primesieve_query_wsl())."""
    script = script_path if script_path is not None else PRIMESIEVE_QUERY_SCRIPT
    script_wsl = windows_path_to_wsl(script)
    return ["python3", "-u", script_wsl, op] + [str(a) for a in args]


def run_primesieve_query_wsl(argv, timeout=120):
    """Runs a primesieve_query.py invocation (see build_primesieve_query_argv()) as a
    BLOCKING wsl.exe subprocess call -- deliberately NOT the WslLoggedRunner/file-tailing
    machinery every other WSL launch in this app uses (see that class's own docstring for
    why long-running jobs need it): a single count/nth/next/prev query answers in well
    under a second for any reasonable input and doesn't need a live progress console, so
    the simpler synchronous-capture-output shape already used by
    estimate_wsl_available_ram_bytes() above fits better here. Callers (the primesieve
    calculator tab's own worker thread, see _primesieve_calc_worker_loop) are still
    responsible for not calling this on the GUI thread directly, since even a "well under
    a second" WSL round-trip is enough to freeze Tk's event loop noticeably.

    `timeout` bounds the whole wsl.exe call, not just the query itself -- count_primes and
    nth_prime are genuine sieve operations (see prime_sieve_primesieve.py's own docstrings
    on those two), so an extreme range/n CAN legitimately take a while; 120s is generous
    for anything a person would plausibly type into this calculator by hand, not a hard
    guarantee.

    Returns (True, result) on success (result is the int primesieve_query.py reported), or
    (False, error_message) on ANY failure -- a non-zero/JSON-shaped {"ok": false, ...}
    response from the script itself, a WSL/process-launch failure, a timeout, or
    unparseable stdout (e.g. WSL not installed at all, so 'wsl.exe' itself never ran) --
    every failure path funnels through this same two-tuple shape so the GUI side has
    exactly one place that decides how to display an error, not one per failure kind."""
    inner = " ".join(shlex.quote(str(t)) for t in argv)
    cmd = ["wsl.exe", "-e", "bash", "-c", inner]
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired:
        return False, T("primesieve_calc.error_timeout", timeout=timeout)
    except OSError as e:
        return False, T("primesieve_calc.error_wsl_launch", error=e)
    stdout = (result.stdout or "").strip()
    last_line = stdout.splitlines()[-1] if stdout else ""
    try:
        payload = json.loads(last_line)
    except (ValueError, IndexError):
        detail = stdout or (result.stderr or "").strip() or T("primesieve_calc.error_no_output")
        return False, T("primesieve_calc.error_bad_output", detail=detail[:500])
    if payload.get("ok"):
        return True, payload.get("result")
    return False, payload.get("error", T("primesieve_calc.error_unknown"))


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


def build_wsl_logged_command(argv, windows_log_path, windows_exit_path):
    """Wraps a Linux-side argv (e.g. ["python3", "/mnt/d/.../script.py", "20", ...]) in a
    `wsl.exe -e bash -c "..."` invocation that redirects combined stdout+stderr into
    windows_log_path (translated to its WSL mount path) and writes the process's exit
    code into windows_exit_path afterward -- see WslLoggedRunner's docstring for why
    file-based redirection replaced an earlier subprocess.PIPE-against-wsl.exe's-own-
    stdout approach. Every token is individually shell-quoted (shlex.quote) so the space
    in "Prime numbers storage" (and anything else) survives bash -c's re-parsing --
    the exec-mode `wsl.exe -e <argv>` form used elsewhere in this app deliberately avoids
    a shell entirely for that reason, but the `>`/`;` here are shell syntax and need one."""
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
    portal_wsl = windows_path_to_wsl(PORTAL_FOLDER)
    env_prefix = f"CONSTELLATION_PORTAL_DIR={shlex.quote(portal_wsl)} "
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

    def __init__(self, cmd, output_queue):
        self.cmd = cmd
        self.output_queue = output_queue
        self.proc = None
        self._thread = None

    def start(self):
        self.output_queue.put(f"$ {' '.join(self.cmd)}\n")
        try:
            self.proc = subprocess.Popen(
                self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, **_popen_kwargs_no_window())
        except OSError as e:
            self.output_queue.put(f"[!] Could not start process: {e}\n")
            self.output_queue.put(("__exit__", None))
            return
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

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


# ------------------------------------------------------------------------------------------
# GUI (tkinter). Four tabs: "Prime numbers", "Constellations", "Generation", "Benchmark".
# ------------------------------------------------------------------------------------------

def _render_page(listbox, values, page, page_size, formatter):
    """Replaces `listbox`'s contents with page `page` (0-indexed) of `values`, rendering
    each entry with `formatter(value) -> str`. Page-based navigation (as opposed to the
    earlier cumulative "load more" approach): each call fully replaces what's shown, so
    there's no growing/duplicate-trailer state to track -- Prev/Next/jump-to-page just
    call this again with a different page index. Returns (clamped_page, total_pages)."""
    total = len(values)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    listbox.delete(0, "end")
    start = page * page_size
    end = min(start + page_size, total)
    for v in values[start:end]:
        listbox.insert("end", formatter(v))
    return page, total_pages


def _update_nav_controls(page_label_var, page, total_pages, prev_btn, next_btn):
    """Shared by both preview panes: updates the "Page X / Y" label and enables/disables
    the Prev/Next buttons at the boundaries."""
    page_label_var.set(T("common.page_label", page=page + 1, total=total_pages))
    prev_btn.configure(state="normal" if page > 0 else "disabled")
    next_btn.configure(state="normal" if page < total_pages - 1 else "disabled")


class _FlowRow:
    """A button-row container that wraps its children onto additional lines instead of
    running them off the edge of the window. The Prime numbers and Constellations tabs'
    preview-navigation rows (Load preview / Prev / page label / Next / page-goto entry)
    used a plain ttk.Frame with every child .pack(side="left")'d onto ONE line -- on a
    narrow window (or a narrow detail pane after the split-view divider is dragged), the
    rightmost controls simply ran past the frame's right edge and became invisible/
    unreachable, with no way to get to them short of resizing the whole window. Reported
    via screenshot: page-nav buttons in the Constellations tab cut off outside the app
    window's right edge.

    Children are added via .add(widget, padx_left=...) instead of widget.pack(...); this
    class lays them out itself using place() (which, unlike pack/grid, doesn't force a
    single line or a fixed grid) and re-flows on every <Configure> of its own frame --
    same 'safe to call again on resize' pattern already used by _draw_growth_chart's
    canvas binding. .frame is what the caller packs/grids into its own parent, exactly
    like a plain ttk.Frame would be."""

    ROW_GAP = 4

    def __init__(self, parent):
        # Local import, not a module-level `from tkinter import ttk` -- this file
        # deliberately defers importing tkinter until _build_gui() actually runs (see the
        # module's own lazy-import convention, also documented in settings_tab.py's
        # header), so `ttk` is never a module-global name here. Every OTHER module-level
        # helper in this file that touches tkinter widgets (_update_nav_controls,
        # _draw_growth_chart, ...) sidesteps this by only ever calling methods on
        # already-constructed widgets passed in as arguments; this class is the first one
        # that needs to construct a widget itself, hence the local import.
        from tkinter import ttk
        self.frame = ttk.Frame(parent)
        self._items = []  # [(widget, padx_left)], in add() order
        self.frame.bind("<Configure>", self._reflow)

    def add(self, widget, padx_left=0):
        self._items.append((widget, padx_left))
        return widget

    def _reflow(self, event):
        width = event.width
        if width <= 1 or not self._items:
            return
        x = 0
        y = 0
        row_height = 0
        for widget, padx_left in self._items:
            widget.update_idletasks()
            w = widget.winfo_reqwidth()
            h = widget.winfo_reqheight()
            if x > 0 and x + padx_left + w > width:
                x = 0
                y += row_height + self.ROW_GAP
                row_height = 0
            widget.place(x=x + padx_left, y=y, width=w, height=h)
            x += padx_left + w
            row_height = max(row_height, h)
        self.frame.configure(height=y + row_height)


def _draw_growth_chart(canvas, points, width, height, points2=None,
                        label_key1="bench.axis_nps", label_key2="bench.axis_spw",
                        fmt1="{:,.0f}", fmt2="{:,.3f}"):
    """Draws (base_exponent, primary-series) points onto `canvas` as a simple axes +
    connected-scatter chart -- x = floor depth, y = the primary series (by default numbers
    swept per second, real session-level wall-clock throughput, higher is better). Plain
    tk.Canvas drawing, no charting library: this app is deliberately zero-extra-installs
    (see module header), and a handful of axis lines + dots doesn't need one. Clears the
    canvas first, so this is safe to call again on refresh/resize (bound to <Configure>).

    points2 (optional): a SECOND series sharing the x-axis -- by default the 'fair'
    loop_seconds_per_window figure shown alongside n/s, but label_key2/fmt2 (see below) let
    a caller reuse this for a different pair, e.g. sieve-numbers/s + write-MB/s. Drawn as a
    red line on its own right-hand y-axis with an independent scale (see
    _pdf_chart_ops()'s docstring for why it needs its own axis rather than sharing the
    primary one).

    label_key1/label_key2/fmt1/fmt2: same meaning and defaults as _pdf_chart_ops()'s matching
    parameters -- i18n keys for the two axis titles, and str.format() templates for tick/
    point value labels -- so the PDF export and this on-screen chart stay visually
    consistent for any series pair, not just the original n/s + s/window one."""
    canvas.delete("all")
    if width <= 1 or height <= 1:
        return  # not yet realized/sized
    points = points or []
    points2 = points2 or []
    if not points and not points2:
        canvas.create_text(width / 2, height / 2, text=T("bench.no_data_chart"),
                            fill="#888888")
        return

    has_secondary = bool(points2)
    pad_left = 70
    pad_right = 70 if has_secondary else 24
    pad_top, pad_bottom = 40, 40
    # pad_top has room ABOVE the topmost y-tick (which sits right at pad_top) for the axis
    # title below -- it used to sit almost on top of that tick's label (both landed within
    # a few px of each other near the top-left corner) and visually merged into one
    # unreadable blob.
    plot_w = max(1, width - pad_left - pad_right)
    plot_h = max(1, height - pad_top - pad_bottom)

    all_xs = sorted({p[0] for p in points} | {p[0] for p in points2})
    x_min, x_max = min(all_xs), max(all_xs)
    if x_min == x_max:
        x_min -= 1
        x_max += 1

    def y_bounds(pts):
        ys = [p[1] for p in pts]
        ylo, yhi = min(ys), max(ys)
        if ylo == yhi:
            pad = max(1.0, abs(ylo) * 0.1)
            ylo -= pad
            yhi += pad
        return min(ylo, 0), yhi  # anchor at (or below) zero -- growth should read honest

    if points:
        y_min, y_max = y_bounds(points)
    if has_secondary:
        y2_min, y2_max = y_bounds(points2)

    # Same horizontal inset as _pdf_chart_ops() -- see that function's comment for why.
    inset_x = max(15.0, plot_w * 0.05)

    def sx(x):
        return pad_left + inset_x + (x - x_min) / (x_max - x_min) * (plot_w - 2 * inset_x)

    def sy(y):
        return pad_top + plot_h - (y - y_min) / (y_max - y_min) * plot_h

    def sy2(y):
        return pad_top + plot_h - (y - y2_min) / (y2_max - y2_min) * plot_h

    canvas.create_line(pad_left, pad_top, pad_left, pad_top + plot_h, fill="#666666")
    canvas.create_line(pad_left, pad_top + plot_h, pad_left + plot_w, pad_top + plot_h,
                        fill="#666666")
    if has_secondary:
        canvas.create_line(pad_left + plot_w, pad_top, pad_left + plot_w, pad_top + plot_h,
                            fill="#c0504d")

    if points:
        for i in range(6):
            y_val = y_min + (y_max - y_min) * i / 5
            y_px = sy(y_val)
            canvas.create_line(pad_left - 4, y_px, pad_left, y_px, fill="#666666")
            canvas.create_text(pad_left - 8, y_px, text=fmt1.format(y_val), anchor="e",
                                font=("Consolas", 8))

    if has_secondary:
        for i in range(6):
            y_val = y2_min + (y2_max - y2_min) * i / 5
            y_px = sy2(y_val)
            canvas.create_line(pad_left + plot_w, y_px, pad_left + plot_w + 4, y_px,
                                fill="#c0504d")
            canvas.create_text(pad_left + plot_w + 8, y_px, text=fmt2.format(y_val), anchor="w",
                                font=("Consolas", 8), fill="#c0504d")

    for x_val in all_xs:
        x_px = sx(x_val)
        canvas.create_line(x_px, pad_top + plot_h, x_px, pad_top + plot_h + 4, fill="#666666")
        canvas.create_text(x_px, pad_top + plot_h + 8, text=str(x_val), anchor="n",
                            font=("Consolas", 8))

    canvas.create_text(pad_left + plot_w / 2, height - 8, text=T("bench.axis_pietro"),
                        font=("Consolas", 8, "bold"))
    # Sits in the padding strip ABOVE the plot area (not overlapping any tick label, which
    # all live at y >= pad_top) -- anchored "sw" so its BOTTOM edge, not its top, is what's
    # positioned, keeping a consistent small gap above the topmost tick regardless of font
    # metrics.
    if points:
        canvas.create_text(4, pad_top - 10, text=T(label_key1), anchor="sw",
                            font=("Consolas", 8, "bold"))
    if has_secondary:
        canvas.create_text(width - 4, pad_top - 10, text=T(label_key2), anchor="se",
                            font=("Consolas", 8, "bold"), fill="#c0504d")

    if points:
        if len(points) > 1:
            coords = []
            for x_val, y_val in points:
                coords.extend([sx(x_val), sy(y_val)])
            canvas.create_line(*coords, fill="#4a90d9", width=2)

        r = 4
        for x_val, y_val in points:
            cx, cy = sx(x_val), sy(y_val)
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#1c5fa8", outline="")
            canvas.create_text(cx, cy - r - 8, text=fmt1.format(y_val), font=("Consolas", 8))

    if has_secondary:
        if len(points2) > 1:
            coords2 = []
            for x_val, y_val in points2:
                coords2.extend([sx(x_val), sy2(y_val)])
            canvas.create_line(*coords2, fill="#c0504d", width=2)

        r = 4
        for x_val, y_val in points2:
            cx, cy = sx(x_val), sy2(y_val)
            canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#c0504d", outline="")
            canvas.create_text(cx, cy + r + 8, text=fmt2.format(y_val), font=("Consolas", 8),
                                fill="#c0504d")


def _build_gui():
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    # The Settings tab's widgets live in their own package (primeatlas/) as a
    # proper class (SettingsTab), not more nested functions on PortalBrowserApp -- see
    # this file's module docstring and settings_tab.py's own docstring for the full
    # rationale. Imported here (inside _build_gui(), not at module top level) for the
    # same reason tkinter itself is: it keeps this module's top-level prefix (everything
    # above _build_gui) importable/testable without tkinter installed.
    from primeatlas.settings_tab import SettingsTab
    from primeatlas.generation_console import GenerationConsole

    class PortalBrowserApp(tk.Tk):
        def __init__(self):
            super().__init__()
            self._apply_theme(APP_SETTINGS.theme)
            self.title(T("app.title"))
            self.geometry("1050x680")

            # status_frame is created and packed BEFORE the notebook, not after. tkinter's
            # pack() geometry manager carves up the toplevel's cavity in the ORDER widgets
            # are packed, not by `side` -- a widget packed with fill=both, expand=True (the
            # notebook) claims however much of the cavity is available AT THE TIME it's
            # packed, so if it goes first, anything packed afterward (status_frame -- the
            # bottom status bar showing the grand total prime count/generation time plus
            # the totals-scan progress bar) only gets whatever sliver is left once total
            # tab content exceeds the window's height. This is a classic Tk pitfall:
            # dock-to-edge widgets like a status bar must be packed before the
            # fill=both,expand=True central widget, not after -- it only becomes visible
            # once a tab's content grows tall enough to exceed the default 1050x680 window
            # size. Packing status_frame FIRST guarantees its own natural height is always
            # reserved; the notebook (still fill=both, expand=True) then fills whatever
            # remains, exactly as intended.
            status_frame = ttk.Frame(self)
            status_frame.pack(fill="x", side="bottom")
            self.status = tk.StringVar(value=T("app.status_portal_initial", folder=PORTAL_FOLDER))
            ttk.Label(status_frame, textvariable=self.status, anchor="w").pack(fill="x", side="top")
            # Visible progress bar for the floor-totals background scan -- the status TEXT
            # alone, updating only once per finished floor, makes it look like nothing is
            # happening for the first ~78s on a big floor; a bar that fills in as floors
            # complete, plus a "start" message the instant a floor's scan actually begins
            # (not just when it finishes), makes the in-progress state visibly obvious.
            # Always packed (not shown/hidden dynamically)
            # so its position never jumps around -- sits at 0/0 (empty) until the first batch
            # starts, see _compute_all_pietro_totals()/_on_pietro_total_start().
            self.totals_progress = ttk.Progressbar(status_frame, orient="horizontal",
                                                     mode="determinate", maximum=1, value=0)
            self.totals_progress.pack(fill="x", side="top")

            notebook = ttk.Notebook(self)
            notebook.pack(fill="both", expand=True)
            # Saved so other tabs can programmatically switch to "Prime numbers" (see
            # _on_const_calc_search_selected(), Faza 3's constellation calculator) --
            # every prior use of this notebook was purely declarative (add tabs, never
            # navigate between them from code), so nothing kept a reference until now.
            self.main_notebook = notebook

            self.primes_tab = ttk.Frame(notebook)
            self.constellations_tab = ttk.Frame(notebook)
            self.research_tab = ttk.Frame(notebook)
            self.generation_tab = ttk.Frame(notebook)
            self.benchmark_tab = ttk.Frame(notebook)
            self.settings_tab_container = ttk.Frame(notebook)
            notebook.add(self.primes_tab, text=T("tabs.primes"))
            notebook.add(self.constellations_tab, text=T("tabs.constellations"))
            notebook.add(self.research_tab, text=T("tabs.research"))
            notebook.add(self.generation_tab, text=T("tabs.generation"))
            notebook.add(self.benchmark_tab, text=T("tabs.benchmark"))
            notebook.add(self.settings_tab_container, text=T("tabs.settings"))

            self._build_primes_section()
            self._build_constellations_section()
            self._build_research_section()
            self._build_generation_tab()
            self._build_benchmark_tab()
            self._build_settings_tab(SettingsTab)

            # Floor-total background worker: reading every source window's
            # header to sum a whole floor's prime count is NOT cheap on this project's real
            # storage (measured ~78s for one 15,101-file floor, ~5ms/file -- per-file open()
            # latency on the underlying mount, not the tiny header itself) -- doing that on
            # the GUI thread is exactly the kind of freeze the paginated file list was built
            # to avoid (see _populate_pietro_node's docstring). ONE daemon worker thread owns
            # self._totals_cache exclusively (loads it once here, then only the worker thread
            # ever reads/writes/saves it -- see update_pietro_totals_cache()); the main thread
            # never touches that dict directly, only sends floor numbers in via
            # _totals_work_queue and receives (base_exponent, total, file_count, new_read,
            # error) tuples back via _totals_result_queue, polled every 150ms (see
            # _poll_totals_results). self._pietro_total_known is a SEPARATE, main-thread-only
            # dict (seeded from the same on-disk cache at startup, updated only from received
            # results) -- two independent copies instead of sharing one dict across threads,
            # so neither thread ever needs a lock.
            self._pietro_total_known = {}
            self._totals_cache = {}
            self._reload_totals_caches()
            self._totals_work_queue = queue.Queue()
            self._totals_result_queue = queue.Queue()
            self._computing_all_totals = False
            self._totals_batch_size = 0   # fixed at the START of a "compute all" batch --
                                           # NOT re-read from _pietro_node_by_exp on every
                                           # result, so the progress bar's denominator can't
                                           # shift mid-batch (e.g. after a Refresh)
            self._grand_total_sum = 0
            self._grand_total_bytes = 0  # on-disk footprint total, mirrors _grand_total_sum
                                          # but for bytes instead of prime count -- see
                                          # update_pietro_totals_cache()'s total_bytes and
                                          # format_bytes()
            self._grand_total_seen = set()
            # base_exponent -> total real generation seconds (write_files=True runs only),
            # from benchmark_log.csv -- read fresh on every reload_primes_tree() (cheap, one
            # small CSV shared by all floors, not a per-floor disk scan like the totals
            # worker above). self._grand_total_seconds mirrors _grand_total_sum's role for
            # the "GRAND TOTAL" status line, giving it a time total alongside the
            # prime-count total.
            self._pietro_gen_seconds = {}
            self._grand_total_seconds = 0.0
            threading.Thread(target=self._totals_worker_loop, daemon=True).start()
            self.after(150, self._poll_totals_results)

            # Search worker: number/constellation search needs to run off the GUI thread,
            # or it freezes the whole application while searching. find_prime_in_floor()'s
            # binary search is normally fast (O(log N) file opens -- see its own
            # docstring), but find_constellation_participation() can decode dozens of
            # full hit files on a floor's first-ever search (nothing cached yet), which
            # is exactly the kind of disk-bound work _totals_worker_loop already exists
            # to keep off the GUI thread -- same one-daemon-thread-owns-the-slow-stuff
            # shape, reusing the SAME status/progress bar the totals worker uses (one
            # shared status bar for both features, not a second one). See
            # _search_worker_loop/_poll_search_results/_start_search_job below.
            self._search_busy = False
            self._search_work_queue = queue.Queue()
            self._search_result_queue = queue.Queue()
            threading.Thread(target=self._search_worker_loop, daemon=True).start()
            self.after(150, self._poll_search_results)

            # primesieve calculator worker (Liczby pierwsze -> primesieve sub-tab): same
            # one-daemon-thread-owns-the-blocking-call shape as the search worker just
            # above (run_primesieve_query_wsl() is a synchronous wsl.exe subprocess call --
            # see that function's own docstring -- so it must not run on the GUI thread),
            # kept as its OWN queue pair rather than reusing _search_work_queue/
            # _search_result_queue since the two jobs have unrelated result shapes (a
            # found-or-not prime/participation result vs. a single computed integer) --
            # sharing one queue would mean every consumer had to branch on job type just
            # to ignore the other kind.
            self._primesieve_calc_busy = False
            self._primesieve_calc_work_queue = queue.Queue()
            self._primesieve_calc_result_queue = queue.Queue()
            threading.Thread(target=self._primesieve_calc_worker_loop, daemon=True).start()
            self.after(150, self._poll_primesieve_calc_results)

            # Primality-testing worker (Liczby pierwsze -> Testy pierwszosci sub-tab):
            # own queue pair for the same reason as the primesieve-calculator block just
            # above (unrelated result shapes: a list of per-method test rows vs. a
            # factorization dict) -- but note this worker never touches WSL at all, see
            # _primality_worker_loop's own docstring.
            self._primality_busy = False
            self._primality_work_queue = queue.Queue()
            self._primality_result_queue = queue.Queue()
            threading.Thread(target=self._primality_worker_loop, daemon=True).start()
            self.after(150, self._poll_primality_results)

            # Goldbach structural-window worker (Badania -> Goldbach sub-tab): own queue
            # pair for the same reason as every other worker block here -- unrelated
            # result shape (a full per-n row list + counterexample list), pure Python
            # like the primality worker, no WSL round trip (see goldbach_window.py's own
            # header comment).
            self._goldbach_busy = False
            self._goldbach_work_queue = queue.Queue()
            self._goldbach_result_queue = queue.Queue()
            # Wizualizacja Toplevel is created lazily (see _goldbach_ensure_viz_window)
            # and reused across clicks -- None here means "not open yet".
            self._goldbach_viz_win = None
            # Pagination state for the two independently-browsable sections of the
            # diagram (see _goldbach_queue_viz / _on_goldbach_viz_chip_prev etc.):
            # row_page drives a fresh backend goldbach_window_rows() call per page,
            # chip_page is a pure client-side slice of the last result's
            # old_base_primes (already fully computed, no backend cost to page
            # through). current_n/last_result let the Prev/Next handlers act without
            # the caller having to thread n and the previous result through again.
            self._goldbach_viz_row_page = 0
            self._goldbach_viz_chip_page = 0
            self._goldbach_viz_current_n = None
            self._goldbach_viz_last_result = None
            # "Rozloz liczbe" detail Toplevel (all_decompositions of one specific n
            # against the currently-open window's Pmax) -- same lazy-create-and-reuse
            # pattern as _goldbach_viz_win, see _goldbach_ensure_decompose_window.
            self._goldbach_decompose_win = None
            # Pagination state for the decompose detail list -- same backend-call-per-
            # page shape as the sums row nav above (a large n can have tens of
            # thousands of pairs, see Artur's own n~=9999992 screenshot: 53364 pairs
            # for one single n). current_n/current_pmax let Prev/Next/goto re-issue a
            # job for the SAME target without the caller re-supplying them each time;
            # last_result caches just enough (count) to clamp a goto target locally.
            self._goldbach_decompose_page = 0
            self._goldbach_decompose_current_n = None
            self._goldbach_decompose_current_pmax = None
            self._goldbach_decompose_last_result = None
            threading.Thread(target=self._goldbach_worker_loop, daemon=True).start()
            self.after(150, self._poll_goldbach_results)

            # Constellation-records-table scan worker (Constellations -> Tabela rekordow
            # sub-tab, Faza 4): own queue pair for the same reason as every other worker
            # above (unrelated result shape -- a whole records table, not a single value).
            self._const_records_busy = False
            self._const_records_work_queue = queue.Queue()
            self._const_records_result_queue = queue.Queue()
            threading.Thread(target=self._const_records_worker_loop, daemon=True).start()
            self.after(150, self._poll_const_records_results)

            # "Generate missing fragment, then re-search" state -- set by
            # _offer_generate_missing_prime_window()/_offer_generate_missing_constellation()
            # right before launching a generation run in response to a search miss, and
            # consumed (cleared + the original search re-run) by _on_loop_finished() /
            # _on_constellation_finished() respectively once that SPECIFIC run's exit
            # sentinel arrives. Two separate slots because a missing prime window and
            # missing constellation hits are fixed by two DIFFERENT runners/queues (see
            # those methods' own docstrings) -- a "const" search miss can end up setting
            # the prime-window slot first (if the window itself was missing) and the
            # constellation slot on a LATER re-search (if the window existed but hits for
            # the floor never did) -- never both at once, since each offer only fires
            # after the previous generation's re-search has already come back.
            self._pending_search_after_prime_gen = None
            self._pending_search_after_const_gen = None

            # Same idea, one more slot: a Wizualizacja/decompose job that hit
            # MissingStorageRangeError and whose "generate this range?" offer (see
            # _goldbach_offer_generate_missing_range) was accepted. Records WHICH
            # op to retry ("viz" or "decompose", None = nothing pending) -- the two
            # ops read their target n from different places (self._goldbach_viz_
            # current_n vs self._goldbach_decompose_current_n/current_pmax), so
            # _on_loop_finished needs to know which one just failed to re-queue the
            # right job instead of always re-running "viz" regardless of which op
            # actually reported the gap.
            self._pending_goldbach_retry_op = None

            # Whole-pipeline step count for the shared bottom progress bar -- see
            # _update_shared_progress_from_generation_chunk()'s own docstring. None between
            # runs / before the first batch-progress line of a run has arrived (so the real
            # step count isn't known yet); set to n_batches+1 once it is, and cleared again
            # once a run's own "done" line snaps the bar to full.
            self._gen_step_total = None
            # Multi-iteration Exploration-mode loop state, same lazy None-between-runs
            # lifecycle as _gen_step_total above -- see _update_shared_progress_from_
            # generation_chunk()'s own docstring for why these exist (without them, the
            # bar only ever reflects ONE iteration's own progress, not the whole
            # Iterations x Width request). Both None whenever the currently-running engine
            # isn't orchestrator_loop_v2.py (primesieve/orchestrator-direct/constellation-
            # finder launches never set these, so the single-run progress logic below
            # applies to them unchanged).
            self._gen_loop_run_count = None
            self._gen_loop_iteration = None

            self.reload_primes_tree()  # this ALSO kicks off the floor-totals scan for every
                                        # floor -- see reload_primes_tree()'s docstring
            self.reload_constellations_tree()
            self.reload_benchmark_log()

        # --- Floor-total background worker ------------------------------------------

        def _reload_totals_caches(self):
            """(Re-)loads _pietro_total_known and _totals_cache from PORTAL_FOLDER's own
            .portal_totals_cache.json -- factored out of __init__ so reload_primes_tree()
            can call this too, on every refresh, not just once at app startup. Otherwise,
            after changing storage path in Settings and clicking Refresh, totals would
            still reflect the PREVIOUS location.

            Root cause of that: both dicts used to be built ONCE in __init__ against
            whatever PORTAL_FOLDER was active when the app launched, then never reloaded --
            a later storage-path change rebinds the PORTAL_FOLDER global (see
            _set_portal_folder) but left these two dicts holding the OLD location's data
            in memory. update_pietro_totals_cache()'s incremental-cache logic keys
            _totals_cache PURELY BY FILENAME within each "10p{N}" entry, with no
            portal_folder scoping at all -- so if a NEWLY selected location happens to
            have its own floor with the same number (and prime_sieve_v1.py assigns
            filenames deterministically from floor+offset, so a same-number floor in
            two different locations very plausibly has same-NAMED files), the stale
            entry made it treat that location's real file as "already read" and served
            the OLD location's cached count without ever opening the new file. A
            genuinely EMPTY new location was already unaffected by this specific bug
            (list_pietra() itself is a stateless disk scan, so no rows get inserted for
            floors that don't exist there) -- but ANY overlap in floor numbers between
            two locations could silently show wrong totals without this reload."""
            self._pietro_total_known = {}
            for _key, _entry in load_totals_cache(PORTAL_FOLDER).items():
                if _key.startswith("10p") and _key[3:].isdigit():
                    self._pietro_total_known[int(_key[3:])] = (
                        _entry.get("total", 0), _entry.get("file_count", 0),
                        _entry.get("total_bytes", 0))
            self._totals_cache = load_totals_cache(PORTAL_FOLDER)  # worker-owned copy

        def _totals_worker_loop(self):
            """Runs forever on its own daemon thread, pulling base_exponent requests off
            _totals_work_queue and pushing results back via _totals_result_queue -- see the
            big comment in __init__ for the single-owner-per-thread rationale. Emits a
            ("start", base_exponent) message the INSTANT a request is picked up, before the
            (possibly ~1 minute, for a heavily-populated floor) scan itself runs -- without
            this, the status/progress bar would sit unchanged for that whole stretch,
            making an in-progress scan look like it's not working. A
            daemon thread needs no explicit shutdown -- it dies with the process."""
            while True:
                base_exponent = self._totals_work_queue.get()
                self._totals_result_queue.put(("start", base_exponent))
                try:
                    total, file_count, new_read, total_bytes = update_pietro_totals_cache(
                        PORTAL_FOLDER, base_exponent, self._totals_cache)
                    if new_read:
                        save_totals_cache(PORTAL_FOLDER, self._totals_cache)
                    # A floor physically copied in from another storage (magazyn) brings
                    # its own floor_meta.json along -- see floor_meta.py's module
                    # docstring. This imports any rows from it that aren't already in the
                    # LOCAL benchmark_log.csv, so the Benchmark tab shows that floor's
                    # real generation history instead of nothing, exactly as if it had
                    # been generated here. No-ops (cheap) on the ordinary case where
                    # there's nothing new to import, so it's safe to call on every floor
                    # visit rather than trying to detect "is this floor newly-copied-in"
                    # some other way.
                    floor_meta.merge_floor_meta_into_benchmark_log(PORTAL_FOLDER, base_exponent)
                    self._totals_result_queue.put(
                        ("done", base_exponent, total, file_count, new_read, None, total_bytes))
                except Exception as e:  # noqa: BLE001 -- must never kill this thread
                    self._totals_result_queue.put(
                        ("done", base_exponent, None, None, None, str(e), None))

        def _poll_totals_results(self):
            """Main-thread side of the worker: drains whatever "start"/"done" messages have
            arrived since the last poll and updates the tree/status/progress bar, then
            reschedules itself -- runs for the whole lifetime of the window (see __init__)."""
            try:
                while True:
                    msg = self._totals_result_queue.get_nowait()
                    if msg[0] == "start":
                        self._on_pietro_total_start(msg[1])
                    else:
                        _kind, base_exponent, total, file_count, new_read, error, total_bytes = msg
                        if error is not None:
                            self.status.set(T("primes.status_error_sum", base_exponent=base_exponent, error=error))
                        else:
                            self._pietro_total_known[base_exponent] = (total, file_count, total_bytes)
                            self._on_pietro_total_ready(
                                base_exponent, total, file_count, new_read, total_bytes)
            except queue.Empty:
                pass
            self.after(150, self._poll_totals_results)

        def _on_pietro_total_start(self, base_exponent):
            """Fires the moment the worker PICKS UP a request -- see _totals_worker_loop's
            docstring for why this exists separately from the completion handler below."""
            if self._computing_all_totals:
                done = len(self._grand_total_seen)
                self.status.set(
                    T("primes.status_computing_progress", base_exponent=base_exponent,
                      done=done, total=self._totals_batch_size,
                      sum=f"{self._grand_total_sum:,}"))
            else:
                self.status.set(T("primes.status_computing", base_exponent=base_exponent))

        def _on_pietro_total_ready(self, base_exponent, total, file_count, new_read, total_bytes):
            node = self._pietro_node_by_exp.get(base_exponent)
            gen_seconds = self._pietro_gen_seconds.get(base_exponent)
            timer_str = format_duration(gen_seconds) if gen_seconds is not None else ""
            if node is not None and self.tree.exists(node):
                self.tree.item(node, values=(
                    f"{total:,}", f"{file_count:,}", format_bytes(total_bytes), "", timer_str))
            if self._active_floor_node == node:
                self._refresh_floor_nav_controls()

            if self._computing_all_totals:
                if base_exponent not in self._grand_total_seen:
                    self._grand_total_seen.add(base_exponent)
                    self._grand_total_sum += total
                    self._grand_total_seconds += gen_seconds or 0.0
                    self._grand_total_bytes += total_bytes or 0
                done = len(self._grand_total_seen)
                expected = self._totals_batch_size
                self.totals_progress.configure(value=done)
                if done >= expected:
                    self._computing_all_totals = False
                    # Reset back to the same empty (0/1) state _totals_progress starts in
                    # (see __init__) -- left at full/expected otherwise, a completed scan
                    # would leave the bar sitting permanently full, which reads as "still
                    # busy" even though nothing is running.
                    self.totals_progress.configure(maximum=1, value=0)
                    self.status.set(
                        T("primes.status_grand_total", count=expected,
                          sum=f"{self._grand_total_sum:,}",
                          duration=format_duration(self._grand_total_seconds),
                          size=format_bytes(self._grand_total_bytes)))
                else:
                    self.status.set(
                        T("primes.status_partial_totals", done=done, total=expected,
                          sum=f"{self._grand_total_sum:,}",
                          size=format_bytes(self._grand_total_bytes)))
            else:
                extra = T("primes.status_extra_new_files", count=new_read) if new_read else ""
                self.status.set(
                    T("primes.status_pietro_total", base_exponent=base_exponent,
                      total=f"{total:,}", files=f"{file_count:,}",
                      size=format_bytes(total_bytes), extra=extra))

        def _compute_all_pietro_totals(self):
            pietra = list(self._pietro_node_by_exp.keys())
            if not pietra:
                self.status.set(T("primes.status_none_to_compute"))
                return
            self._computing_all_totals = True
            self._totals_batch_size = len(pietra)
            self._grand_total_sum = 0
            self._grand_total_seconds = 0.0
            self._grand_total_bytes = 0
            self._grand_total_seen = set()
            self.totals_progress.configure(maximum=len(pietra), value=0)
            self.status.set(T("primes.status_batch_start", count=len(pietra)))
            for base_exponent in pietra:
                self._totals_work_queue.put(base_exponent)

        def _apply_theme(self, theme_name):
            """Applies primeatlas.theme's color palette to every widget class this app
            actually uses -- called once, in __init__, BEFORE any child widget is
            created, so everything built afterward picks up the new colors through
            normal ttk style inheritance / Tk option-database lookup instead of
            needing a live re-walk of the whole widget tree once it already exists.
            Same restart-required UX as `language` (see i18n.py's docstring) --
            Settings > Ogolne's theme picker (settings_tab.py) only writes the choice
            to AppSettings, it does not attempt to re-theme the already-built app.

            Two coloring mechanisms, because this app mixes ttk and raw tk widgets:
              - ttk widgets (the large majority -- Frame/Label/Button/Entry/Combobox/
                Checkbutton/Radiobutton/Labelframe/Notebook/Treeview/Scrollbar/
                Panedwindow/Progressbar/Spinbox -- grep-verified against every
                ttk.* call in this file plus settings_tab.py/generation_console.py)
                only obey ttk.Style(), never the Tk option database -- every style
                name actually used anywhere in this app is configured below.
              - the handful of raw tk widgets (tk.Text inside GenerationConsole/
                ScrolledText, tk.Listbox backing every readonly ttk.Combobox's own
                dropdown, tk.Canvas for the Wizualizacja/constellation diagrams) obey
                the Tk option DATABASE instead -- root.option_add() below, which only
                takes effect for widgets that don't pass an explicit bg/fg at
                construction time. The two benchmark-chart Canvases (see
                _build_benchmark_tab) DO pass an explicit background="white" already
                and are deliberately left untouched here: their plotted line colors
                were chosen assuming a white plot area, and darkening just the
                background without re-picking every plotted series' color would make
                them harder to read, not easier -- consistent with "add
                functionality, don't replace it", this leaves that pre-existing
                choice alone rather than overriding it.

            'clam' is forced as the base ttk theme regardless of the platform
            default (Windows normally defaults to 'vista'/'winnative', which
            silently IGNORES most background/foreground style.configure() calls for
            common widgets -- a well-known tkinter limitation) -- without this, a
            dark palette would visually do nothing on Windows, which is where this
            app actually runs."""
            from primeatlas.theme import palette_for
            p = palette_for(theme_name)

            style = ttk.Style(self)
            style.theme_use("clam")

            style.configure(".", background=p["bg"], foreground=p["fg"],
                             fieldbackground=p["field_bg"])
            style.map(".", foreground=[("disabled", p["disabled_fg"])])

            for cls in ("TFrame", "TLabelframe", "TLabelframe.Label", "TLabel",
                        "TCheckbutton", "TRadiobutton", "TPanedwindow"):
                style.configure(cls, background=p["bg"], foreground=p["fg"])
            style.map("TCheckbutton", background=[("active", p["bg"])])
            style.map("TRadiobutton", background=[("active", p["bg"])])

            style.configure("TButton", background=p["field_bg"], foreground=p["fg"])
            style.map("TButton",
                      background=[("active", p["select_bg"]), ("disabled", p["bg"])],
                      foreground=[("disabled", p["disabled_fg"])])

            style.configure("TEntry", fieldbackground=p["field_bg"], foreground=p["field_fg"],
                             insertcolor=p["field_fg"])
            style.map("TEntry", fieldbackground=[("disabled", p["bg"])])
            style.configure("TSpinbox", fieldbackground=p["field_bg"], foreground=p["field_fg"],
                             background=p["field_bg"], arrowcolor=p["fg"])

            style.configure("TCombobox", fieldbackground=p["field_bg"], foreground=p["field_fg"],
                             background=p["field_bg"], arrowcolor=p["fg"])
            style.map("TCombobox",
                      fieldbackground=[("readonly", p["field_bg"]), ("disabled", p["bg"])],
                      foreground=[("readonly", p["field_fg"])])
            # ttk.Combobox's dropdown is internally a raw tk.Listbox, NOT a ttk
            # widget -- it obeys the option database, not ttk.Style().
            self.option_add("*TCombobox*Listbox.background", p["field_bg"])
            self.option_add("*TCombobox*Listbox.foreground", p["field_fg"])
            self.option_add("*TCombobox*Listbox.selectBackground", p["select_bg"])
            self.option_add("*TCombobox*Listbox.selectForeground", p["select_fg"])

            style.configure("TNotebook", background=p["bg"], borderwidth=0)
            style.configure("TNotebook.Tab", background=p["tab_bg"], foreground=p["fg"])
            style.map("TNotebook.Tab",
                      background=[("selected", p["tab_selected_bg"])],
                      foreground=[("selected", p["fg"])])

            style.configure("Treeview", background=p["tree_bg"], fieldbackground=p["tree_bg"],
                             foreground=p["fg"])
            style.map("Treeview",
                      background=[("selected", p["select_bg"])],
                      foreground=[("selected", p["select_fg"])])
            style.configure("Treeview.Heading", background=p["tab_bg"], foreground=p["fg"])
            style.map("Treeview.Heading", background=[("active", p["select_bg"])])

            style.configure("TScrollbar", background=p["tab_bg"], troughcolor=p["bg"],
                             arrowcolor=p["fg"], bordercolor=p["bg"])
            style.configure("TProgressbar", background=p["select_bg"], troughcolor=p["field_bg"])
            style.configure("TSeparator", background=p["border"])

            self.configure(background=p["bg"])
            self.option_add("*Background", p["bg"])
            self.option_add("*Foreground", p["fg"])
            self.option_add("*Text.Background", p["console_bg"])
            self.option_add("*Text.Foreground", p["console_fg"])
            self.option_add("*Text.insertBackground", p["console_fg"])
            self.option_add("*Listbox.Background", p["field_bg"])
            self.option_add("*Listbox.Foreground", p["field_fg"])
            self.option_add("*Canvas.Background", p["bg"])
            self.option_add("*Entry.Background", p["field_bg"])
            self.option_add("*Entry.Foreground", p["field_fg"])

        # --- Tab 1: Prime numbers (source primes) ---------------------------------

        def _build_primes_section(self):
            """The top-level 'Prime numbers' notebook tab is itself a small ttk.Notebook
            now, not a single flat frame -- 'Magazyn' (Storage) holds exactly what this
            whole tab used to be (the floor/file browser + search, built by
            _build_primes_tab() below, completely unchanged apart from its parent frame
            now being self.primes_storage_tab instead of self.primes_tab directly),
            alongside two new sibling tabs that later phases fill in:
            self.primes_primesieve_tab (a standalone libprimesieve calculator -- count/
            nth/next/prev prime, no on-disk storage involved) and
            self.primes_primality_tab (probabilistic primality testing + factorization
            for a single entered number). See _build_constellations_section() for the
            SAME nested-notebook pattern applied to the Constellations tab -- deliberately
            identical structure between the two so the app has one consistent way of
            giving a top-level section its own sub-tabs, not two diverging ones."""
            sub = ttk.Notebook(self.primes_tab)
            sub.pack(fill="both", expand=True)
            # Saved for the same reason as self.main_notebook above -- the constellation
            # calculator's Search button (Faza 3) needs to switch to this sub-notebook's
            # own Magazyn tab, not just the top-level Prime numbers tab.
            self.primes_sub_notebook = sub
            self.primes_storage_tab = ttk.Frame(sub)
            self.primes_primesieve_tab = ttk.Frame(sub)
            self.primes_primality_tab = ttk.Frame(sub)
            sub.add(self.primes_storage_tab, text=T("tabs.primes_storage"))
            sub.add(self.primes_primesieve_tab, text=T("tabs.primes_primesieve"))
            sub.add(self.primes_primality_tab, text=T("tabs.primes_primality"))
            self._build_primes_tab()
            self._build_primesieve_tab()
            self._build_primality_tab()

        def _build_primesieve_tab(self):
            """Standalone libprimesieve calculator -- count primes in a range, nth prime,
            next/prev prime -- entirely independent of anything already in storage (no
            floor, no PORTAL_FOLDER, nothing written to disk). See
            build_primesieve_query_argv()/run_primesieve_query_wsl() for the WSL round
            trip this launches, and primesieve_query.py (prime_sieve/ folder) for the
            one-shot CLI script actually doing the libprimesieve call.

            Operation-dependent input fields use the SAME grid()/grid_remove() swap
            technique the Quick-gen panel's mode switch already established (NOT tkraise
            -- that approach had a frame-overlap bug fixed earlier in this project's
            history), so only one field layout is ever visible/interactive at a time."""
            container = ttk.Frame(self.primes_primesieve_tab)
            container.pack(fill="x", padx=12, pady=12)

            op_row = ttk.Frame(container)
            op_row.pack(fill="x", pady=(0, 10))
            ttk.Label(op_row, text=T("primesieve_calc.field_operation")).pack(side="left")
            # (internal op code, translated display label) pairs -- the combobox itself
            # only ever shows/stores the translated label (ttk.Combobox has no separate
            # value/label concept like a listbox with associated data), so
            # _on_primesieve_calc_operation_changed() maps back to the code via this same
            # list's index (combobox.current()) rather than reverse-parsing display text.
            self._primesieve_calc_ops = [
                ("count", T("primesieve_calc.op_count")),
                ("nth", T("primesieve_calc.op_nth")),
                ("next", T("primesieve_calc.op_next")),
                ("prev", T("primesieve_calc.op_prev")),
            ]
            self.primesieve_calc_op_combo = ttk.Combobox(
                op_row, state="readonly", width=32,
                values=[label for _code, label in self._primesieve_calc_ops])
            self.primesieve_calc_op_combo.current(0)
            self.primesieve_calc_op_combo.pack(side="left", padx=(6, 0))
            self.primesieve_calc_op_combo.bind(
                "<<ComboboxSelected>>", self._on_primesieve_calc_operation_changed)

            fields_area = ttk.Frame(container)
            fields_area.pack(fill="x", pady=(0, 10))

            self._primesieve_calc_count_frame = ttk.Frame(fields_area)
            ttk.Label(self._primesieve_calc_count_frame,
                      text=T("primesieve_calc.field_lo")).grid(row=0, column=0, sticky="e")
            self.primesieve_calc_lo_entry = ttk.Entry(self._primesieve_calc_count_frame, width=22)
            self.primesieve_calc_lo_entry.grid(row=0, column=1, padx=(6, 16))
            ttk.Label(self._primesieve_calc_count_frame,
                      text=T("primesieve_calc.field_hi")).grid(row=0, column=2, sticky="e")
            self.primesieve_calc_hi_entry = ttk.Entry(self._primesieve_calc_count_frame, width=22)
            self.primesieve_calc_hi_entry.grid(row=0, column=3, padx=(6, 0))

            self._primesieve_calc_nth_frame = ttk.Frame(fields_area)
            ttk.Label(self._primesieve_calc_nth_frame,
                      text=T("primesieve_calc.field_n")).grid(row=0, column=0, sticky="e")
            self.primesieve_calc_n_entry = ttk.Entry(self._primesieve_calc_nth_frame, width=22)
            self.primesieve_calc_n_entry.grid(row=0, column=1, padx=(6, 16))
            ttk.Label(self._primesieve_calc_nth_frame,
                      text=T("primesieve_calc.field_start")).grid(row=0, column=2, sticky="e")
            self.primesieve_calc_start_entry = ttk.Entry(self._primesieve_calc_nth_frame, width=22)
            self.primesieve_calc_start_entry.grid(row=0, column=3, padx=(6, 0))

            self._primesieve_calc_x_frame = ttk.Frame(fields_area)
            ttk.Label(self._primesieve_calc_x_frame,
                      text=T("primesieve_calc.field_x")).grid(row=0, column=0, sticky="e")
            self.primesieve_calc_x_entry = ttk.Entry(self._primesieve_calc_x_frame, width=22)
            self.primesieve_calc_x_entry.grid(row=0, column=1, padx=(6, 0))

            # All three placed in the SAME grid cell -- grid_remove() on the two not
            # currently active, grid() on the one that is (see
            # _on_primesieve_calc_operation_changed()). count starts visible, matching
            # the combobox's own default selection (index 0) above.
            self._primesieve_calc_count_frame.grid(row=0, column=0, sticky="w")
            self._primesieve_calc_nth_frame.grid(row=0, column=0, sticky="w")
            self._primesieve_calc_x_frame.grid(row=0, column=0, sticky="w")
            self._primesieve_calc_nth_frame.grid_remove()
            self._primesieve_calc_x_frame.grid_remove()

            button_row = ttk.Frame(container)
            button_row.pack(fill="x", pady=(0, 10))
            self.primesieve_calc_button = ttk.Button(
                button_row, text=T("primesieve_calc.compute_button"),
                command=self._on_primesieve_calc_compute)
            self.primesieve_calc_button.pack(side="left")

            result_row = ttk.Frame(container)
            result_row.pack(fill="x")
            self.primesieve_calc_result_var = tk.StringVar(value="")
            ttk.Label(result_row, textvariable=self.primesieve_calc_result_var,
                      font=("Consolas", 11, "bold"), wraplength=700, justify="left").pack(
                side="left", anchor="w")
            self.primesieve_calc_copy_button = ttk.Button(
                result_row, text=T("primesieve_calc.copy_button"),
                command=self._on_primesieve_calc_copy_result, state="disabled")
            self.primesieve_calc_copy_button.pack(side="left", padx=(10, 0))
            self._primesieve_calc_last_result = None  # raw int, for the Copy button --
                                                        # None whenever the result label
                                                        # isn't currently showing a
                                                        # successful numeric result

        def _on_primesieve_calc_operation_changed(self, _event=None):
            code = self._primesieve_calc_ops[self.primesieve_calc_op_combo.current()][0]
            self._primesieve_calc_count_frame.grid_remove()
            self._primesieve_calc_nth_frame.grid_remove()
            self._primesieve_calc_x_frame.grid_remove()
            if code == "count":
                self._primesieve_calc_count_frame.grid()
            elif code == "nth":
                self._primesieve_calc_nth_frame.grid()
            else:  # next / prev share the same single-field layout
                self._primesieve_calc_x_frame.grid()

        def _on_primesieve_calc_compute(self):
            """Validates the active operation's fields CLIENT-SIDE first (same rules
            primesieve_query.py itself enforces -- n>0, x>2 for prev, hi>lo for count --
            see that script's own docstring) so an obviously-bad input gets an immediate
            messagebox instead of paying for a WSL round trip just to have it rejected
            there anyway. A value primesieve_query.py could STILL reject for some other
            reason (e.g. asking libprimesieve for something past its own uint64 ceiling)
            is left to come back as a normal error result -- this is a fast local sanity
            check, not a full re-implementation of the backend's own validation."""
            if self._primesieve_calc_busy:
                return
            code = self._primesieve_calc_ops[self.primesieve_calc_op_combo.current()][0]
            try:
                if code == "count":
                    lo = _eval_quick_number(self.primesieve_calc_lo_entry.get())
                    hi = _eval_quick_number(self.primesieve_calc_hi_entry.get())
                    if lo is None or hi is None:
                        raise ValueError(T("primesieve_calc.error_count_fields_int"))
                    if hi <= lo:
                        raise ValueError(T("primesieve_calc.error_hi_le_lo"))
                    args = (lo, hi)
                elif code == "nth":
                    n = _eval_quick_number(self.primesieve_calc_n_entry.get())
                    if n is None or n <= 0:
                        raise ValueError(T("primesieve_calc.error_n_positive"))
                    start_raw = self.primesieve_calc_start_entry.get().strip()
                    if start_raw:
                        start = _eval_quick_number(start_raw)
                        if start is None or start < 0:
                            raise ValueError(T("primesieve_calc.error_start_nonneg"))
                    else:
                        start = 0
                    args = (n, start)
                else:  # next / prev
                    x = _eval_quick_number(self.primesieve_calc_x_entry.get())
                    if x is None:
                        raise ValueError(T("primesieve_calc.error_field_int", field=T("primesieve_calc.field_x")))
                    if code == "prev" and x <= 2:
                        raise ValueError(T("primesieve_calc.error_prev_too_small"))
                    args = (x,)
            except ValueError as e:
                messagebox.showerror(T("primesieve_calc.error_dialog_title"), str(e))
                return

            self._primesieve_calc_busy = True
            self.primesieve_calc_button.configure(state="disabled")
            self.primesieve_calc_copy_button.configure(state="disabled")
            self._primesieve_calc_last_result = None
            self.totals_progress.stop()
            self.totals_progress.configure(mode="indeterminate")
            self.totals_progress.start(80)
            self.status.set(T("primesieve_calc.status_computing"))
            self._primesieve_calc_work_queue.put({"code": code, "args": args})

        def _primesieve_calc_worker_loop(self):
            """Own daemon thread -- same single-owner reasoning as _search_worker_loop
            (see that method's own docstring); _primesieve_calc_busy blocking new
            requests from the GUI side means only one query is ever in flight."""
            while True:
                job = self._primesieve_calc_work_queue.get()
                code, args = job["code"], job["args"]
                argv = build_primesieve_query_argv(code, *args)
                ok, payload = run_primesieve_query_wsl(argv)
                self._primesieve_calc_result_queue.put((code, args, ok, payload))

        def _poll_primesieve_calc_results(self):
            """Main-thread side of the calculator worker -- same 150ms polling cadence as
            _poll_search_results/_poll_totals_results, runs for the whole lifetime of the
            window."""
            try:
                while True:
                    code, args, ok, payload = self._primesieve_calc_result_queue.get_nowait()
                    self._primesieve_calc_busy = False
                    self.primesieve_calc_button.configure(state="normal")
                    self.totals_progress.stop()
                    self.totals_progress.configure(mode="determinate", maximum=1, value=0)
                    if not ok:
                        self.status.set(T("primesieve_calc.status_error"))
                        messagebox.showerror(T("primesieve_calc.error_dialog_title"), payload)
                        continue
                    self.status.set(T("primesieve_calc.status_done"))
                    self._primesieve_calc_last_result = payload
                    self.primesieve_calc_copy_button.configure(state="normal")
                    if code == "count":
                        lo, hi = args
                        text = T("primesieve_calc.result_count", lo=f"{lo:,}", hi=f"{hi:,}",
                                  count=f"{payload:,}")
                    elif code == "nth":
                        n, start = args
                        text = T("primesieve_calc.result_nth", n=f"{n:,}", start=f"{start:,}",
                                  value=f"{payload:,}")
                    elif code == "next":
                        (x,) = args
                        text = T("primesieve_calc.result_next", x=f"{x:,}", value=f"{payload:,}")
                    else:
                        (x,) = args
                        text = T("primesieve_calc.result_prev", x=f"{x:,}", value=f"{payload:,}")
                    self.primesieve_calc_result_var.set(text)
            except queue.Empty:
                pass
            self.after(150, self._poll_primesieve_calc_results)

        def _on_primesieve_calc_copy_result(self):
            if self._primesieve_calc_last_result is None:
                return
            self.clipboard_clear()
            self.clipboard_append(str(self._primesieve_calc_last_result))

        def _build_primality_tab(self):
            """Testy pierwszosci sub-tab -- enter a number, run Miller-Rabin/Fermat/
            Solovay-Strassen against it (primeatlas/primality.py, pure Python, no WSL
            round trip needed -- see that module's own header comment on why), or
            factorize it (trial division + Pollard's rho by default, sympy.factorint()
            instead when installed). Both operations run on their own worker thread
            (own queue.Queue pair + 150ms poller, same pattern as
            _primesieve_calc_worker_loop/_poll_primesieve_calc_results) purely to keep a
            slow big-number computation off the GUI thread -- unlike the primesieve
            calculator this never leaves the process, there's no WSL subprocess
            involved."""
            top = ttk.Frame(self.primes_primality_tab)
            top.pack(fill="x", padx=6, pady=(10, 4))
            ttk.Label(top, text=T("primality.field_number")).pack(side="left")
            self.primality_number_entry = ttk.Entry(top, width=32)
            self.primality_number_entry.pack(side="left", padx=(6, 16))

            self.primality_use_sympy_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(
                top, text=T("primality.use_sympy_checkbox"),
                variable=self.primality_use_sympy_var).pack(side="left")

            button_row = ttk.Frame(self.primes_primality_tab)
            button_row.pack(fill="x", padx=6, pady=(0, 8))
            self.primality_check_button = ttk.Button(
                button_row, text=T("primality.check_button"),
                command=self._on_primality_check_compute)
            self.primality_check_button.pack(side="left")
            self.primality_factorize_button = ttk.Button(
                button_row, text=T("primality.factorize_button"),
                command=self._on_primality_factorize_compute)
            self.primality_factorize_button.pack(side="left", padx=(8, 0))

            ttk.Label(self.primes_primality_tab, text=T("primality.hint"),
                      wraplength=640, justify="left", foreground="#555").pack(
                anchor="w", padx=6, pady=(0, 8))

            tree_frame = ttk.Frame(self.primes_primality_tab)
            tree_frame.pack(fill="both", expand=False, padx=6, pady=(0, 8))
            columns = ("method", "verdict", "certainty", "seconds")
            self.primality_results_tree = ttk.Treeview(
                tree_frame, columns=columns, show="headings", height=3)
            self.primality_results_tree.heading("method", text=T("primality.col_method"))
            self.primality_results_tree.heading("verdict", text=T("primality.col_verdict"))
            self.primality_results_tree.heading("certainty", text=T("primality.col_certainty"))
            self.primality_results_tree.heading("seconds", text=T("primality.col_seconds"))
            self.primality_results_tree.column("method", width=140, anchor="w")
            self.primality_results_tree.column("verdict", width=110, anchor="center")
            self.primality_results_tree.column("certainty", width=220, anchor="w")
            self.primality_results_tree.column("seconds", width=100, anchor="e")
            self.primality_results_tree.pack(fill="x")

            factor_frame = ttk.Frame(self.primes_primality_tab)
            factor_frame.pack(fill="x", padx=6, pady=(0, 4))
            self.primality_factor_result_var = tk.StringVar(value="")
            ttk.Label(factor_frame, textvariable=self.primality_factor_result_var,
                      wraplength=760, justify="left").pack(anchor="w")

            # Separate readonly Entry holding JUST the factor list (no "n = " prefix, no
            # "(metoda: ..., czas: ...)" suffix) -- a plain Label's text can't be selected
            # or copied at all in tkinter, so the summary line above was previously
            # impossible to copy from. An Entry supports normal mouse selection (drag for
            # a range, double-click for one factor) and Ctrl+C even in readonly state --
            # readonly only blocks typing/editing, not selection -- plus a one-click Copy
            # button for grabbing the whole list at once.
            factors_row = ttk.Frame(self.primes_primality_tab)
            factors_row.pack(fill="x", padx=6, pady=(0, 8))
            ttk.Label(factors_row, text=T("primality.factors_field_label")).pack(side="left")
            self.primality_factors_only_var = tk.StringVar(value="")
            self.primality_factors_entry = ttk.Entry(
                factors_row, textvariable=self.primality_factors_only_var, state="readonly")
            self.primality_factors_entry.pack(side="left", fill="x", expand=True, padx=(6, 6))
            self.primality_factors_copy_button = ttk.Button(
                factors_row, text=T("primality.copy_factors_button"),
                command=self._on_primality_copy_factors, state="disabled")
            self.primality_factors_copy_button.pack(side="left")

        def _primality_parse_number(self):
            """Shared client-side validation for both buttons -- parses the number field
            (via _eval_quick_number, so expressions like 10**5+3 work here too, same as
            the primesieve calculator's fields), requiring an integer >= 2 (both
            primality.run_all_tests and primality.factorize document this same floor --
            see that module's own docstrings). Raises ValueError with a translated
            message on failure; returns the parsed int on success."""
            n = _eval_quick_number(self.primality_number_entry.get())
            if n is None or n < 2:
                raise ValueError(T("primality.error_number_invalid"))
            return n

        def _on_primality_check_compute(self):
            if self._primality_busy:
                return
            try:
                n = self._primality_parse_number()
            except ValueError as e:
                messagebox.showerror(T("primality.error_dialog_title"), str(e))
                return
            self._primality_set_busy(True)
            self._primality_work_queue.put({"op": "check", "n": n})

        def _on_primality_factorize_compute(self):
            if self._primality_busy:
                return
            try:
                n = self._primality_parse_number()
            except ValueError as e:
                messagebox.showerror(T("primality.error_dialog_title"), str(e))
                return
            self._primality_set_busy(True)
            self._primality_work_queue.put(
                {"op": "factorize", "n": n, "use_sympy": self.primality_use_sympy_var.get()})

        def _primality_set_busy(self, busy):
            self._primality_busy = busy
            state = "disabled" if busy else "normal"
            self.primality_check_button.configure(state=state)
            self.primality_factorize_button.configure(state=state)
            if busy:
                self.totals_progress.stop()
                self.totals_progress.configure(mode="indeterminate")
                self.totals_progress.start(80)
                self.status.set(T("primality.status_computing"))
            else:
                self.totals_progress.stop()
                self.totals_progress.configure(mode="determinate", maximum=1, value=0)

        def _primality_worker_loop(self):
            """Own daemon thread -- single-owner reasoning identical to
            _primesieve_calc_worker_loop's own docstring (self._primality_busy blocks
            new requests from the GUI side, so only one job is ever in flight). No WSL
            subprocess here at all -- primeatlas.primality is ordinary in-process pure
            Python, run directly on this thread."""
            while True:
                job = self._primality_work_queue.get()
                op = job["op"]
                try:
                    if op == "check":
                        rows = primality_run_all_tests(job["n"])
                        self._primality_result_queue.put((op, job["n"], True, rows))
                    else:
                        result = primality_factorize(job["n"], use_sympy=job["use_sympy"])
                        self._primality_result_queue.put((op, job["n"], True, result))
                except Exception as e:  # noqa: BLE001 -- surface any unexpected failure
                                         # to the GUI as an error dialog instead of
                                         # silently killing this worker thread
                    self._primality_result_queue.put((op, job["n"], False, str(e)))

        def _poll_primality_results(self):
            """Main-thread side -- same 150ms polling cadence as
            _poll_primesieve_calc_results/_poll_search_results, runs for the whole
            lifetime of the window."""
            try:
                while True:
                    op, n, ok, payload = self._primality_result_queue.get_nowait()
                    self._primality_set_busy(False)
                    if not ok:
                        self.status.set(T("primality.status_error"))
                        messagebox.showerror(T("primality.error_dialog_title"), payload)
                        continue
                    self.status.set(T("primality.status_done"))
                    if op == "check":
                        self._primality_show_check_results(payload)
                    else:
                        self._primality_show_factorize_result(n, payload)
            except queue.Empty:
                pass
            self.after(150, self._poll_primality_results)

        def _primality_show_check_results(self, rows):
            self.primality_results_tree.delete(*self.primality_results_tree.get_children())
            for row in rows:
                verdict = (T("primality.verdict_prime") if row["is_prime"]
                            else T("primality.verdict_composite"))
                self.primality_results_tree.insert(
                    "", "end",
                    values=(row["method"], verdict, row["certainty"], f"{row['seconds']:.4f}"))

        def _primality_show_factorize_result(self, n, result):
            pairs = result["pairs"]
            factor_str = " x ".join(
                f"{p}^{e}" if e > 1 else str(p) for p, e in pairs) or str(n)
            method = (T("primality.method_sympy") if result["method"] == "sympy"
                      else T("primality.method_pure_python"))
            text = T("primality.factor_result", n=f"{n:,}", factors=factor_str,
                      method=method, seconds=f"{result['seconds']:.4f}")
            if not result["complete"]:
                text += " " + T("primality.factor_result_incomplete_note")
            self.primality_factor_result_var.set(text)
            self.primality_factors_only_var.set(factor_str)
            self.primality_factors_copy_button.configure(state="normal")

        def _on_primality_copy_factors(self):
            text = self.primality_factors_only_var.get()
            if not text:
                return
            self.clipboard_clear()
            self.clipboard_append(text)

        def _build_primes_tab(self):
            top = ttk.Frame(self.primes_storage_tab)
            top.pack(fill="x", padx=6, pady=4)
            ttk.Button(top, text=T("common.refresh"), command=self.reload_primes_tree).pack(side="left")

            ttk.Label(top, text=T("common.search_label")).pack(side="left")
            self.search_entry = ttk.Entry(top, width=26)
            self.search_entry.pack(side="left", padx=(4, 4))
            self.search_entry.bind("<Return>", lambda _e: self._search_prime())
            self.search_button = ttk.Button(
                top, text=T("common.search_button"), command=self._search_prime)
            self.search_button.pack(side="left")

            # No separate "compute all totals" button --
            # Refresh already re-runs the totals scan for every floor (see
            # reload_primes_tree()), so a second button doing the same thing was redundant.
            # Re-running costs almost nothing when nothing changed: update_pietro_totals_
            # cache() only re-reads files NOT already in its cache (a cheap os.listdir() +
            # in-memory set diff per floor either way -- see that function's docstring), so
            # hitting Refresh after generating new windows only pays for the new files, not
            # a full floor-by-floor rescan.
            paned = ttk.Panedwindow(self.primes_storage_tab, orient="horizontal")
            paned.pack(fill="both", expand=True, padx=6, pady=4)

            tree_frame = ttk.Frame(paned)
            paned.add(tree_frame, weight=1)

            # Floor pagination -- ABOVE the tree, same Prev/label/Next/goto layout
            # as the file-preview pane on the right (see btn_row below). A floor can hold
            # thousands of source windows -- listing+rendering them all on one expand is
            # what used to freeze the GUI. Expanding a floor now only lists filenames
            # (cheap) and loads ONE page's worth of headers; these controls act on whichever
            # floor was most recently opened/clicked (self._active_floor_node) -- multiple
            # floors can stay expanded at once, each remembering its own page independently.
            floor_nav = ttk.Frame(tree_frame)
            floor_nav.pack(fill="x", pady=(0, 4))
            self.floor_prev_btn = ttk.Button(
                floor_nav, text=T("common.prev_page"), command=self._prev_floor_page, state="disabled")
            self.floor_prev_btn.pack(side="left")
            self.floor_page_label = tk.StringVar(value="")
            ttk.Label(floor_nav, textvariable=self.floor_page_label, width=16, anchor="center").pack(side="left")
            self.floor_next_btn = ttk.Button(
                floor_nav, text=T("common.next_page"), command=self._next_floor_page, state="disabled")
            self.floor_next_btn.pack(side="left")
            ttk.Label(floor_nav, text=T("common.page_prefix")).pack(side="left", padx=(10, 0))
            self.floor_goto_entry = ttk.Entry(floor_nav, width=6)
            self.floor_goto_entry.pack(side="left", padx=(4, 0))
            self.floor_goto_entry.bind("<Return>", lambda _e: self._goto_floor_page())
            ttk.Button(floor_nav, text=T("common.goto"), command=self._goto_floor_page).pack(side="left", padx=(4, 0))

            # Page subtotal (instant -- sums the headers this page already had to read to
            # display the file list, no extra I/O) alongside the floor's OVERALL total,
            # which is NOT instant for a heavily-populated floor and gets filled in
            # asynchronously once the background totals worker finishes (see
            # _on_pietro_total_ready) -- shows "computing..." until then.
            self.floor_subtotal_label = tk.StringVar(value="")
            ttk.Label(floor_nav, textvariable=self.floor_subtotal_label, anchor="w").pack(
                side="left", padx=(14, 0))

            # 4 value columns: count/files/generated/timer, split apart
            # because "generated" used to double as BOTH a per-file UTC timestamp (file rows)
            # AND a file count (floor summary rows) -- confusing on a collapsed floor, which
            # only ever shows the summary row. "files" now always means file count, "generated"
            # always means a UTC timestamp (blank on floor rows -- no single date is
            # meaningful for a whole floor), "timer" is new: total REAL generation time for
            # that floor (write_files=True runs only, see aggregate_write_seconds_by_pietro()).
            self.tree = ttk.Treeview(
                tree_frame, columns=("count", "files", "size", "generated", "timer"),
                show="tree headings")
            self.tree.heading("#0", text=T("primes.col_pietro"))
            self.tree.heading("count", text=T("primes.col_count"))
            self.tree.heading("files", text=T("primes.col_files"))
            self.tree.heading("size", text=T("primes.col_size"))
            self.tree.heading("generated", text=T("primes.col_generated"))
            self.tree.heading("timer", text=T("primes.col_timer"))
            self.tree.column("#0", width=260)
            self.tree.column("count", width=90, anchor="e")
            self.tree.column("files", width=90, anchor="e")
            self.tree.column("size", width=90, anchor="e")
            self.tree.column("generated", width=170)
            self.tree.column("timer", width=110, anchor="e")
            vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
            self.tree.configure(yscrollcommand=vsb.set)
            self.tree.pack(side="left", fill="both", expand=True)
            vsb.pack(side="right", fill="y")

            self.tree.bind("<<TreeviewOpen>>", self._on_tree_open)
            self.tree.bind("<<TreeviewClose>>", self._on_tree_close)
            self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

            self._pietro_state = {}         # tree item id -> {base_exponent, filenames,
                                             # page, total_pages}, or None if checked and
                                             # found empty. Populated lazily on
                                             # <<TreeviewOpen>>, dropped entirely (freeing
                                             # the filename list + tree rows) on
                                             # <<TreeviewClose>> -- see _on_tree_close.
            self._active_floor_node = None  # which floor's page the floor nav buttons
                                             # above currently operate on
            self._pietro_node_by_exp = {}   # base_exponent -> tree item id, so a totals
                                             # result arriving from the background worker
                                             # (keyed by base_exponent, not tree item id --
                                             # see _totals_worker_loop) knows which row to
                                             # update, even after a Refresh rebuilt the tree

            detail_frame = ttk.Frame(paned)
            paned.add(detail_frame, weight=2)

            self.detail_text = tk.StringVar(value=T("primes.detail_hint"))
            ttk.Label(detail_frame, textvariable=self.detail_text, justify="left",
                      anchor="nw", wraplength=560).pack(fill="x", padx=6, pady=6)

            # _FlowRow (not a plain pack(side="left") row) so these controls wrap onto a
            # second line instead of running off the window's right edge on a narrow
            # width/pane -- see that class's own docstring.
            btn_row = _FlowRow(detail_frame)
            btn_row.frame.pack(anchor="w", padx=6, fill="x")
            self.load_preview_btn = ttk.Button(
                btn_row.frame, text=T("common.load_preview"), command=self._load_preview, state="disabled")
            btn_row.add(self.load_preview_btn)
            self.prev_page_btn = ttk.Button(
                btn_row.frame, text=T("common.prev_page"), command=self._prev_preview_page, state="disabled")
            btn_row.add(self.prev_page_btn, padx_left=10)
            self.preview_page_label = tk.StringVar(value="")
            btn_row.add(ttk.Label(btn_row.frame, textvariable=self.preview_page_label,
                                   width=16, anchor="center"))
            self.next_page_btn = ttk.Button(
                btn_row.frame, text=T("common.next_page"), command=self._next_preview_page, state="disabled")
            btn_row.add(self.next_page_btn)
            btn_row.add(ttk.Label(btn_row.frame, text=T("common.page_prefix")), padx_left=10)
            self.preview_goto_entry = ttk.Entry(btn_row.frame, width=6)
            btn_row.add(self.preview_goto_entry, padx_left=4)
            self.preview_goto_entry.bind("<Return>", lambda _e: self._goto_preview_page())
            btn_row.add(ttk.Button(btn_row.frame, text=T("common.goto"),
                                    command=self._goto_preview_page), padx_left=4)

            preview_frame = ttk.Frame(detail_frame)
            preview_frame.pack(fill="both", expand=True, padx=6, pady=6)
            self.preview_list = tk.Listbox(preview_frame, font=("Consolas", 9))
            preview_vsb = ttk.Scrollbar(preview_frame, orient="vertical", command=self.preview_list.yview)
            self.preview_list.configure(yscrollcommand=preview_vsb.set)
            self.preview_list.pack(side="left", fill="both", expand=True)
            preview_vsb.pack(side="right", fill="y")

            # Each row here IS a single prime (unlike the Constellations tab's rows, which
            # show a whole reconstructed tuple) -- Ctrl+C and right-click "Copy" both
            # copy the selected row's actual value to the clipboard. A plain tk.Listbox
            # has no built-in copy behaviour at all, so without this there was no way to
            # get a value out of the list except retyping it by hand.
            self.preview_list.bind("<Control-c>", lambda _e: self._copy_selected_preview_value())
            self.preview_list.bind("<Button-3>", self._show_preview_context_menu)
            self._preview_context_menu = tk.Menu(self, tearoff=0)
            self._preview_context_menu.add_command(label=T("common.copy"), command=self._copy_selected_preview_value)

            self._selected_path = None
            self._preview_primes = None    # full decoded list for the selected file, cached
                                            # after "Load preview" so page navigation doesn't
                                            # re-decode the file from scratch each click
            self._preview_page = 0
            self._preview_total_pages = 1

        def reload_primes_tree(self):
            """Rebuilds the floor list from disk (picks up newly created/removed 10pN
            folders) AND re-runs the totals scan for every floor -- so
            pressing Refresh after generating new windows is enough to see updated totals,
            no separate button needed. This is NOT a full re-read of everything: each
            floor's total is cached (see update_pietro_totals_cache()'s docstring) keyed by
            filename, so a floor with no new files costs one cheap os.listdir() + an
            in-memory set diff, and a floor WITH new files only pays for reading THOSE
            files' headers, not the whole floor again.

            Also reloads _pietro_total_known/_totals_cache fresh from the CURRENT
            PORTAL_FOLDER every time -- without this, both would be loaded once at app
            startup and never touched again, so Refresh after a storage-path change in
            Settings could show totals left over from the PREVIOUS location for any
            floor whose number happened to exist in both (see _reload_totals_caches()'s
            docstring for the full root-cause writeup).

            Runs prune_empty_pietro_dirs() first, every time -- this used to be a one-off
            call restore made at the end of its own job, but an empty leftover 10p{N}
            folder (or a now-empty source_primes/ or constellations/ subdir inside an
            otherwise-still-populated one) can just as easily result from a manual delete
            or even a generation run that only ever removed files (never actually true in
            practice, but the guarantee is cheaper to make unconditional than to reason
            about per-caller). Reload is the one place EVERY mutating action (restore,
            generation-finished, constellation-finished, delete) already funnels through
            before the user sees the tree again, so pruning here covers all of them from
            a single spot instead of each caller remembering to do it itself.

            Floors that exist on disk but have NO actual PRIME_WINDOW_*.bin files are
            filtered OUT of the list entirely -- most commonly a 10p{N} folder that
            prune_empty_pietro_dirs() just above chose to KEEP rather than remove because
            it still holds a sieving_primes_count_cache.json (see
            prime_sieve_v4.py's count_sieving_primes_cached()): that cache is worth
            keeping on disk for whenever the user next generates on that floor, but with
            no prime data behind it, it has nothing to show under Liczby pierwsze."""
            prune_empty_pietro_dirs(PORTAL_FOLDER)
            self._reload_totals_caches()
            self.tree.delete(*self.tree.get_children())
            self._pietro_state = {}
            self._active_floor_node = None
            self._path_by_item = {}
            self._pietro_node_by_exp = {}
            self._refresh_floor_nav_controls()
            # Cheap (one small CSV, not a per-floor disk scan) -- re-read fresh on every
            # Refresh so a just-finished write_files=True run shows up in the Timer column
            # immediately, same responsiveness as the totals worker below.
            self._pietro_gen_seconds = aggregate_write_seconds_by_pietro(
                read_benchmark_log(PORTAL_FOLDER)[1])
            pietra = [be for be in list_pietra(PORTAL_FOLDER)
                      if list_source_filenames(PORTAL_FOLDER, be)]
            for base_exponent in pietra:
                # If a previous scan (this session or a past one, via the on-disk cache)
                # already knows this floor's total, show it immediately -- otherwise leave
                # the count column blank until the background worker fills it in (see
                # _compute_all_pietro_totals() below / _on_pietro_total_ready). Either way
                # the row is shown right away; only the count itself may lag, and even then
                # only until the (re-)scan below reaches it.
                known = self._pietro_total_known.get(base_exponent)
                gen_seconds = self._pietro_gen_seconds.get(base_exponent)
                timer_str = format_duration(gen_seconds) if gen_seconds is not None else ""
                values = ((f"{known[0]:,}", f"{known[1]:,}", format_bytes(known[2]), "", timer_str)
                          if known else ("", "", "", "", timer_str))
                node = self.tree.insert("", "end", text=f"10p{base_exponent}",
                                         values=values, open=False, tags=("pietro",))
                self.tree.insert(node, "end", text=T("common.loading"))
                self._pietro_node_by_exp[base_exponent] = node
            self.status.set(T("app.status_portal_with_count", folder=PORTAL_FOLDER, count=len(pietra)))
            self._compute_all_pietro_totals()

        def _on_tree_open(self, _event):
            node = self.tree.focus()
            self._populate_pietro_node(node)
            self._set_active_floor_node(node)
            base_exponent = int(self.tree.item(node, "text")[3:])  # "10p{N}"
            self._totals_work_queue.put(base_exponent)  # always re-check -- cheap no-op if
                                                          # nothing changed since last time
                                                          # (see update_pietro_totals_cache)

        def _on_tree_close(self, _event):
            """Collapsing a floor drops its whole page/filename-list state and clears its
            rows back to a single "(loading...)" placeholder -- re-expanding later re-lists
            from disk instead of holding onto a floor's data indefinitely just because it
            was opened once. Other, still-open floors are untouched."""
            node = self.tree.focus()
            if node not in self._pietro_state:
                return
            del self._pietro_state[node]
            self._clear_floor_children(node)
            self.tree.insert(node, "end", text=T("common.loading"))
            if self._active_floor_node == node:
                self._active_floor_node = None
                self._refresh_floor_nav_controls()

        def _clear_floor_children(self, node):
            """Removes every current child row of `node` from the tree AND from
            self._path_by_item -- without this second part, repeated page turns/collapses
            would leak orphaned item-id -> (path, header) entries for rows that no longer
            exist in the tree."""
            path_map = getattr(self, "_path_by_item", {})
            for child in self.tree.get_children(node):
                path_map.pop(child, None)
            self.tree.delete(*self.tree.get_children(node))

        def _populate_pietro_node(self, node):
            if node in self._pietro_state:
                return  # already listed in this session -- nothing to redo
            children = self.tree.get_children(node)
            if len(children) == 1 and self.tree.item(children[0], "text") == T("common.loading"):
                self.tree.delete(children[0])

            base_exponent = int(self.tree.item(node, "text")[3:])  # "10p{N}"
            filenames = list_source_filenames(PORTAL_FOLDER, base_exponent)  # cheap: no
                                                                              # header I/O
            if not filenames:
                self.tree.insert(node, "end", text=T("primes.no_source_files"))
                self._pietro_state[node] = None
                return

            total_pages = max(1, (len(filenames) + FLOOR_PAGE_SIZE - 1) // FLOOR_PAGE_SIZE)
            self._pietro_state[node] = {
                "base_exponent": base_exponent,
                "filenames": filenames,
                "page": 0,
                "total_pages": total_pages,
            }
            self._show_floor_page(node, 0)

        def _show_floor_page(self, node, page):
            """Renders page `page` (0-indexed) of a floor's file list: reads headers for
            ONLY that page's files (bounded I/O, unlike the old read-every-header-on-expand
            approach) and rebuilds the node's tree rows from scratch."""
            state = self._pietro_state.get(node)
            if not state:
                return
            total_pages = state["total_pages"]
            page = max(0, min(page, total_pages - 1))
            state["page"] = page
            start = page * FLOOR_PAGE_SIZE
            end = min(start + FLOOR_PAGE_SIZE, len(state["filenames"]))
            page_entries = read_source_file_headers(state["filenames"][start:end])

            self._clear_floor_children(node)
            self._path_by_item = getattr(self, "_path_by_item", {})
            page_total = 0
            for name, path, header in page_entries:
                try:
                    size_str = format_bytes(os.path.getsize(path))
                except OSError:
                    size_str = "?"
                if header is None:
                    count_str, gen_str = "?", T("primes.unreadable_header")
                else:
                    count_str = f"{header['count']:,}"
                    gen_str = header["generated_at_iso"]
                    page_total += header["count"]
                child = self.tree.insert(node, "end", text=name,
                                          values=(count_str, "", size_str, gen_str, ""),
                                          tags=("file",))
                self._path_by_item[child] = (path, header)
            state["page_total"] = page_total

            if self._active_floor_node == node:
                self._refresh_floor_nav_controls()

        def _set_active_floor_node(self, node):
            self._active_floor_node = node
            self._refresh_floor_nav_controls()

        def _refresh_floor_nav_controls(self):
            node = self._active_floor_node
            state = self._pietro_state.get(node) if node is not None else None
            if not state:
                self.floor_page_label.set("")
                self.floor_subtotal_label.set("")
                self.floor_prev_btn.configure(state="disabled")
                self.floor_next_btn.configure(state="disabled")
                return
            _update_nav_controls(self.floor_page_label, state["page"], state["total_pages"],
                                  self.floor_prev_btn, self.floor_next_btn)
            page_total = state.get("page_total", 0)
            known = self._pietro_total_known.get(state["base_exponent"])
            overall = f"{known[0]:,}" if known else T("common.computing")
            self.floor_subtotal_label.set(
                T("primes.page_total", page_total=f"{page_total:,}", overall=overall))

        def _prev_floor_page(self):
            node = self._active_floor_node
            if node is not None and self._pietro_state.get(node):
                self._show_floor_page(node, self._pietro_state[node]["page"] - 1)

        def _next_floor_page(self):
            node = self._active_floor_node
            if node is not None and self._pietro_state.get(node):
                self._show_floor_page(node, self._pietro_state[node]["page"] + 1)

        def _goto_floor_page(self):
            raw = self.floor_goto_entry.get().strip()
            if not raw.isdigit():
                return
            node = self._active_floor_node
            if node is not None and self._pietro_state.get(node):
                self._show_floor_page(node, int(raw) - 1)

        def _on_tree_select(self, _event):
            selection = self.tree.selection()
            if not selection:
                return
            item = selection[0]
            if "pietro" in self.tree.item(item, "tags"):
                # Clicking a floor header (whether just opened or already expanded) makes
                # it the target of the floor-pagination controls above the tree, without
                # touching the file-preview state on the right.
                self._set_active_floor_node(item)
                return
            path_map = getattr(self, "_path_by_item", {})
            self._reset_preview_state()
            if item not in path_map:
                self.load_preview_btn.configure(state="disabled")
                return
            path, header = path_map[item]
            self._selected_path = path
            if header is None:
                self.detail_text.set(T("primes.header_error", path=path))
                self.load_preview_btn.configure(state="disabled")
                return
            self.detail_text.set(
                f"{path}\n\n" +
                T("primes.header_detail",
                  base_prime=format_big_int(header['base_prime']),
                  count=f"{header['count']:,}",
                  generated=header['generated_at_iso'])
            )
            self.load_preview_btn.configure(state="normal" if header["count"] > 0 else "disabled")

        def _reset_preview_state(self):
            self.preview_list.delete(0, "end")
            self._preview_primes = None
            self._preview_page = 0
            self._preview_total_pages = 1
            self.preview_page_label.set("")
            self.prev_page_btn.configure(state="disabled")
            self.next_page_btn.configure(state="disabled")
            self.load_preview_btn.configure(state="normal" if self._selected_path else "disabled")

        def _load_preview(self):
            """Decodes the selected file ONCE (cached in self._preview_primes) and shows
            page 1."""
            if not self._selected_path:
                return
            if self._preview_primes is None:
                try:
                    self._preview_primes = prime_sieve_v1.read_prime_window(self._selected_path)
                except Exception as exc:
                    messagebox.showerror(T("primes.load_preview_failed_title"), str(exc))
                    self._preview_primes = None
                    return
            self._show_preview_page(0)
            self.load_preview_btn.configure(state="disabled")

        def _show_preview_page(self, page):
            if not self._preview_primes:
                return
            self._preview_page, self._preview_total_pages = _render_page(
                self.preview_list, self._preview_primes, page, PAGE_SIZE, str)
            _update_nav_controls(self.preview_page_label, self._preview_page,
                                  self._preview_total_pages, self.prev_page_btn, self.next_page_btn)

        def _prev_preview_page(self):
            self._show_preview_page(self._preview_page - 1)

        def _next_preview_page(self):
            self._show_preview_page(self._preview_page + 1)

        def _goto_preview_page(self):
            raw = self.preview_goto_entry.get().strip()
            if not raw.isdigit():
                return
            self._show_preview_page(int(raw) - 1)

        def _search_prime(self):
            raw = self.search_entry.get().strip()
            if not raw.isdigit():
                messagebox.showerror(T("common.dialog_search_title"), T("common.error_invalid_number"))
                return
            number = int(raw)
            base_exponent = digit_count_floor(number)
            if self._search_busy:
                messagebox.showinfo(T("common.dialog_search_title"), T("common.search_already_running"))
                return
            if base_exponent not in list_pietra(PORTAL_FOLDER):
                # No floor 10p{base_exponent} at all yet -- the SAME "this number's storage
                # fragment doesn't exist" situation _on_prime_search_result() handles for an
                # existing-but-incomplete floor, just at the whole-floor scale (existing_count
                # is naturally 0 for a floor with zero windows -- see
                # find_continuation_target_idx()'s own docstring). Route it through the exact
                # same offer instead of a dead-end "no floor" message: there's nothing this
                # dialog told the user that generating the fragment doesn't already cover.
                outcome = self._offer_generate_missing_prime_window("prime", base_exponent, number)
                if outcome == "launched":
                    return
                if outcome == "composite":
                    messagebox.showinfo(
                        T("common.dialog_search_title"),
                        T("primes.confirmed_composite", number=number, base_exponent=base_exponent))
                    return
                messagebox.showinfo(
                    T("common.dialog_search_title"),
                    T("primes.not_found", number=number, base_exponent=base_exponent))
                return
            self._start_search_job("prime", base_exponent, number)

        def _on_prime_search_result(self, base_exponent, number, result):
            """Main-thread completion handler for a "prime" search job -- same UI update
            _search_prime() used to do synchronously right after calling
            find_prime_in_floor(), now driven by _poll_search_results() once the worker
            thread hands the (plain-data, no tkinter involved) result back."""
            if result is None:
                outcome = self._offer_generate_missing_prime_window("prime", base_exponent, number)
                if outcome == "launched":
                    return
                if outcome == "composite":
                    messagebox.showinfo(
                        T("common.dialog_search_title"),
                        T("primes.confirmed_composite", number=number, base_exponent=base_exponent))
                    return
                messagebox.showinfo(
                    T("common.dialog_search_title"),
                    T("primes.not_found", number=number, base_exponent=base_exponent))
                return
            self._select_primes_file_in_tree(base_exponent, result["name"])
            self._preview_primes = result["primes"]
            self._jump_preview_to_index(result["index"])
            total = len(result["primes"])
            self.status.set(
                T("common.found_in_file", number=number, name=result['name'],
                  base_exponent=base_exponent, position=f"{result['index'] + 1:,}", total=f"{total:,}"))

        # --- Search worker -- shared by both "Prime numbers" and
        # "Constellations" search boxes, see the __init__ comment above _search_worker_loop's
        # startup for the full rationale. ------------------------------------------------

        def _start_search_job(self, kind, base_exponent, number):
            """Hands the actual (potentially slow) file-scanning work off to
            _search_worker_loop's daemon thread. Only fast/instant validation (isdigit,
            digit_count_floor, list_pietra's no-I/O floor-existence check) happens on the
            GUI thread, in the caller, before this is ever reached. Disables BOTH search
            buttons while a job is in flight -- the two features share one worker thread
            and one status/progress bar, so only one search runs at a time system-wide,
            same reasoning _on_quick_generate_clicked already applies to
            self._loop_runner."""
            self._search_busy = True
            self.search_button.configure(state="disabled")
            self.hits_search_button.configure(state="disabled")
            self.totals_progress.stop()
            self.totals_progress.configure(mode="indeterminate")
            self.totals_progress.start(80)
            if kind == "prime":
                self.status.set(T("primes.status_searching", number=number, base_exponent=base_exponent))
            else:
                self.status.set(T("const.status_searching", number=number, base_exponent=base_exponent))
            self._search_work_queue.put(
                {"kind": kind, "base_exponent": base_exponent, "number": number})

        def _search_worker_loop(self):
            """Own daemon thread -- same single-owner-per-thread reasoning as
            _totals_worker_loop (see that method's docstring). While a "const" job is in
            flight, this thread is ALSO the sole owner of self._hit_set_cache (the GUI
            thread never mutates it directly anymore, only reads the finished
            participation list handed back via the result queue) -- _search_busy blocking
            new searches from the GUI side means only one job is ever in flight, so this
            never races against itself."""
            while True:
                job = self._search_work_queue.get()
                kind = job["kind"]
                base_exponent = job["base_exponent"]
                number = job["number"]
                try:
                    if kind == "prime":
                        result = find_prime_in_floor(PORTAL_FOLDER, base_exponent, number)
                        self._search_result_queue.put(("prime_done", base_exponent, number, result))
                    else:
                        prime_result = find_prime_in_floor(PORTAL_FOLDER, base_exponent, number)
                        if prime_result is None:
                            self._search_result_queue.put(
                                ("const_done", base_exponent, number, None, []))
                            continue

                        def _progress(done, total, _q=self._search_result_queue):
                            _q.put(("const_progress", done, total))

                        participation = find_constellation_participation(
                            PORTAL_FOLDER, base_exponent, number, self._hit_set_cache,
                            progress_callback=_progress)
                        self._search_result_queue.put(
                            ("const_done", base_exponent, number, prime_result, participation))
                except Exception as e:  # noqa: BLE001 -- must never kill this thread
                    self._search_result_queue.put((f"{kind}_error", base_exponent, number, str(e)))

        def _poll_search_results(self):
            """Main-thread side of the search worker -- same 150ms self.after() polling
            cadence as _poll_totals_results, runs for the whole lifetime of the window."""
            try:
                while True:
                    msg = self._search_result_queue.get_nowait()
                    kind = msg[0]
                    if kind == "const_progress":
                        _kind, done, total = msg
                        self.totals_progress.stop()
                        self.totals_progress.configure(
                            mode="determinate", maximum=max(1, total), value=done)
                        self.status.set(T("const.status_search_progress", done=done, total=total))
                    elif kind == "prime_done":
                        _kind, base_exponent, number, result = msg
                        self._finish_search_job()
                        self._on_prime_search_result(base_exponent, number, result)
                    elif kind == "const_done":
                        _kind, base_exponent, number, prime_result, participation = msg
                        self._finish_search_job()
                        self._on_const_search_result(base_exponent, number, prime_result, participation)
                    else:  # "prime_error" / "const_error"
                        _kind, _base_exponent, _number, error = msg
                        self._finish_search_job()
                        messagebox.showerror(T("common.dialog_search_title"), error)
            except queue.Empty:
                pass
            self.after(150, self._poll_search_results)

        def _finish_search_job(self):
            self._search_busy = False
            self.search_button.configure(state="normal")
            self.hits_search_button.configure(state="normal")
            self.totals_progress.stop()
            # Same "reset back to the empty 0/1 state" reasoning as
            # _on_pietro_total_ready's grand-total completion branch -- a bar left sitting
            # full/mid-way reads as "still busy" even though nothing is running.
            self.totals_progress.configure(mode="determinate", maximum=1, value=0)

        def _offer_generate_missing_prime_window(self, kind, base_exponent, number):
            """Called from _on_prime_search_result()/_on_const_search_result() the moment
            find_prime_in_floor() comes back empty -- which, on its own, is ambiguous:
            either `number` really is composite, OR the window that would COVER it was
            simply never generated (the floor folder exists -- that's checked earlier, in
            _search_prime()/_search_constellation() -- but this specific fragment inside
            it doesn't). _quick_gen_plan_literal_range(number, number + 1) is the exact
            same "is this literal point already on disk" check Range/Floor mode already
            use (see that method's own docstring) -- reused here unchanged rather than
            re-deriving the on-disk-coverage logic a second time.

            Returns one of three strings, so the caller can pick the right final message
            instead of a single generic "not found" for every case:
              "launched"  -- a generation run was actually started; the caller should show
                              NOTHING yet -- _on_loop_finished() re-runs the search once the
                              run completes and THAT result decides the final message.
              "composite" -- plan says "already": the window covering `number` DOES exist
                              on disk, find_prime_in_floor() already searched it and came up
                              empty, so this isn't a data gap at all -- `number` is
                              CONFIRMED composite. The caller should say so plainly instead
                              of the generic "not found in storage" wording, which exists
                              specifically for the ambiguous case this ISN'T.
              "skipped"   -- still ambiguous: either a generation run is already in flight
                              (an error dialog was already shown here, via the same
                              T("quick.error_already_running") message the Quick-gen panel
                              itself uses for the identical situation) or the user declined
                              the confirmation prompt. The caller should fall back to the
                              generic "not found in storage" wording -- true either way,
                              since the fragment genuinely isn't on disk.

            LAUNCH ENGINE: deliberately _apply_primesieve_params_and_run(), NOT
            _apply_loop_params_and_run() (v4's own batch engine) -- window_count_per_run
            from _quick_gen_plan_literal_range() is measured relative to
            find_continuation_target_idx()'s CONTINUATION point (existing_count), which is
            exactly right for Range/Floor mode (a person deliberately filling a range they
            want whole), but wrong here: a number searched deep into an otherwise-empty
            floor would silently turn into a request to backfill EVERY window from index 0
            up to it first, because orchestrator_loop_v2.py/v4's engine has no notion of
            "start at an arbitrary target_idx" -- it only ever continues from wherever a
            floor's storage currently ends (see build_loop_argv()'s own CLI, which has no
            target_idx_start position at all). One real run hit exactly this: floor 11,
            nothing on disk yet, searched a number landing at target_idx ~30000 -> a
            30,001-window batch instead of the single window actually needed.
            build_primesieve_argv()'s script (prime_sieve_primesieve.py) takes
            target_idx_start explicitly and has no continuation requirement -- it writes
            just the ONE window asked for, gaps before it and all, which is exactly what a
            single-number check needs (see that function's own docstring).

            CEILING FALLBACK: primesieve mode can't reach every floor -- libprimesieve's
            own uint64 domain tops out at PRIMESIEVE_MAX_STOP (2**64-1 =~ 1.8e19), while a
            search can land on any floor at all (a floor-30 constellation search real-world
            hit this: 10^30 is about eleven orders of magnitude past that ceiling, so
            primesieve mode silently truncated the run to nothing rather than writing the
            window). Once `plan['rounded_start']` is past that ceiling, primesieve mode
            cannot write ANY part of the requested window, so this falls back to
            orchestrator_v3.py run directly (see build_orchestrator_direct_argv()'s own
            docstring for why that engine -- not its loop wrapper -- is the one capable of
            an arbitrary single-window write at any magnitude)."""
            plan = self._quick_gen_plan_literal_range(number, number + 1)
            if plan.get("error"):
                return "skipped"
            if plan.get("already"):
                return "composite"
            if self._loop_runner is not None and self._loop_runner.is_running():
                messagebox.showinfo(T("quick.dialog_title"), T("quick.error_already_running"))
                return "skipped"
            if not messagebox.askyesno(
                    T("common.dialog_search_title"),
                    T("search.offer_generate_prime_window", number=f"{number:,}",
                      base_exponent=base_exponent,
                      rounded_start=f"{plan['rounded_start']:,}",
                      rounded_end=f"{plan['rounded_end']:,}")):
                return "skipped"
            self._pending_search_after_prime_gen = {
                "kind": kind, "base_exponent": base_exponent, "number": number}
            self.status.set(T("search.status_generating_prime_window", number=f"{number:,}"))
            target_idx = (plan["rounded_start"] - 10 ** plan["floor"]) // QUICK_GEN_MAX_WINDOW_WIDTH
            if plan["rounded_start"] > PRIMESIEVE_MAX_STOP:
                self._apply_orchestrator_direct_params_and_run(plan["floor"], target_idx, 1)
            else:
                self._apply_primesieve_params_and_run(plan["floor"], target_idx, 1)
            return "launched"

        def _offer_generate_missing_constellation(self, base_exponent, number):
            """Two callers: _on_const_search_result(), when `number` IS a confirmed prime
            (its window exists and find_prime_in_floor() found it) but
            find_constellation_participation() came back with zero matches -- ambiguous
            on its own: either this number genuinely isn't the base/offset-member of any
            tracked pattern at this floor, OR constellation_finder_v1.py has simply never
            been run for floor 10p{base_exponent} at all, so there's nothing recorded to
            match against either way. That caller checks list_constellation_hits()
            returning an empty list (no hit FILES at all for this floor, for any pattern
            in the catalog) first, to distinguish the second case from genuine
            non-participation, before calling this.

            The second caller, _on_const_calc_search_selected() (Kalkulator konstelacji),
            checks something more specific instead: whether the ONE pattern it's asking
            about has a hit file yet, regardless of whether other patterns already do --
            list_constellation_hits()'s "nothing at all" check would stay silent in
            that case even though this exact pattern was never confirmed either way
            (see that method's own docstring for why the coarser check isn't enough
            there). Either way, once this actually launches, process_floor() itself is
            what decides whether there's genuinely new work to do (it only re-scans
            windows past its own per-floor checkpoint -- a floor already fully
            checkpointed under the current catalog just reports "nothing new" and
            reconfirms the same non-participation result, harmless either way).
            search.offer_generate_constellation's own wording is deliberately scenario-
            agnostic ("no hits recorded", not "never ran") so it reads correctly from
            both callers.

            Same True/False launched-or-not contract this file uses elsewhere for a single
            generation offer (simpler than _offer_generate_missing_prime_window()'s 3-way
            "launched"/"composite"/"skipped" string, since there's no equivalent of
            "composite" here -- an empty hit-file list is ALWAYS ambiguous, never a
            confirmed answer, so there's nothing finer to distinguish), but
            drives constellation_finder_v1.py's own runner/queue (self._const_runner) via
            _on_run_constellation()'s exact launch path instead of the prime-window one --
            see _on_constellation_finished() for the completion/re-search side."""
            if self._const_runner is not None and self._const_runner.is_running():
                messagebox.showinfo(T("quick.dialog_title"), T("quick.error_already_running"))
                return False
            if not messagebox.askyesno(
                    T("common.dialog_search_title"),
                    T("search.offer_generate_constellation", number=f"{number:,}",
                      base_exponent=base_exponent)):
                return False
            self._pending_search_after_const_gen = {
                "kind": "const", "base_exponent": base_exponent, "number": number}
            self.status.set(T("search.status_generating_constellation", base_exponent=base_exponent))
            self._const_base_exponent_var.set(str(base_exponent))
            self._on_run_constellation()
            return True

        def _select_primes_file_in_tree(self, base_exponent, filename):
            pietro_item = None
            for item in self.tree.get_children(""):
                if self.tree.item(item, "text") == f"10p{base_exponent}":
                    pietro_item = item
                    break
            if pietro_item is None:
                return
            self.tree.item(pietro_item, open=True)
            self._populate_pietro_node(pietro_item)
            self._set_active_floor_node(pietro_item)
            state = self._pietro_state.get(pietro_item)
            if state:
                # Jump to whichever page actually contains this filename -- search can
                # land anywhere across a floor with thousands of paginated files, not
                # just whatever page happened to be showing (usually page 1).
                for idx, (name, _path) in enumerate(state["filenames"]):
                    if name == filename:
                        self._show_floor_page(pietro_item, idx // FLOOR_PAGE_SIZE)
                        break
            target_item = None
            for child in self.tree.get_children(pietro_item):
                if self.tree.item(child, "text") == filename:
                    target_item = child
                    break
            if target_item is None:
                return
            # selection_set() queues an async <<TreeviewSelect>> virtual event rather than
            # dispatching it immediately -- Tk resolves the bound handler at DISPATCH time,
            # not at generation time, so even unbind()-ing around this call doesn't help
            # (the event still fires, against whatever's bound once event processing
            # resumes). If the caller sets up search-specific preview state (jump to a
            # specific index) right after this returns, that queued event would fire
            # later and silently wipe it out via _on_tree_select's _reset_preview_state().
            # Flushing the event queue with update() here forces it to fire and run its
            # course NOW, before this function returns -- so any later state changes are
            # safe.
            self.tree.see(target_item)
            self.tree.selection_set(target_item)
            self.tree.focus(target_item)
            self.update()

        def _jump_preview_to_index(self, index):
            if not self._preview_primes:
                return
            page = index // PAGE_SIZE
            self._show_preview_page(page)
            self.load_preview_btn.configure(state="disabled")
            local = index - self._preview_page * PAGE_SIZE
            self.preview_list.selection_clear(0, "end")
            self.preview_list.selection_set(local)
            self.preview_list.see(local)

        def _show_preview_context_menu(self, event):
            # Right-clicking an unselected row should select IT (not whatever was
            # selected before), matching how most list/tree widgets behave elsewhere.
            index = self.preview_list.nearest(event.y)
            if index >= 0:
                self.preview_list.selection_clear(0, "end")
                self.preview_list.selection_set(index)
            self._preview_context_menu.tk_popup(event.x_root, event.y_root)

        def _copy_selected_preview_value(self):
            sel = self.preview_list.curselection()
            if not sel or not self._preview_primes:
                return
            global_index = self._preview_page * PAGE_SIZE + sel[0]
            if global_index >= len(self._preview_primes):
                return
            self.clipboard_clear()
            self.clipboard_append(str(self._preview_primes[global_index]))

        # --- Tab 2: Constellations (constellation hits) ---------------------------------

        def _build_constellations_section(self):
            """Same nested-notebook pattern as _build_primes_section() (see that method's
            own docstring for the full rationale) -- 'Magazyn' (Storage) holds exactly
            what this whole tab used to be (the hit-file browser + search, built by
            _build_constellations_tab() below, unchanged apart from its parent frame now
            being self.constellations_storage_tab), alongside two new sibling tabs later
            phases fill in: self.constellations_calculator_tab ('Kalkulator konstelacji'
            -- pick a k-tuple pattern from pattern_catalog_v1.py + an exp/Offset pair,
            Atlas computes the full k numbers and offers to search for them) and
            self.constellations_records_tab (a pzktupel.de-style exp x variant table
            built from the user's OWN storage, exportable to PDF+CSV)."""
            sub = ttk.Notebook(self.constellations_tab)
            sub.pack(fill="both", expand=True)
            # Saved for the same reason as self.primes_sub_notebook -- the constellation
            # calculator's Search button needs to switch to THIS sub-notebook's own
            # Magazyn tab (not just the top-level Constellations tab).
            self.constellations_sub_notebook = sub
            self.constellations_storage_tab = ttk.Frame(sub)
            self.constellations_calculator_tab = ttk.Frame(sub)
            self.constellations_records_tab = ttk.Frame(sub)
            sub.add(self.constellations_storage_tab, text=T("tabs.constellations_storage"))
            sub.add(self.constellations_calculator_tab, text=T("tabs.constellations_calculator"))
            sub.add(self.constellations_records_tab, text=T("tabs.constellations_records"))
            self._build_constellations_tab()
            self._build_constellations_calculator_tab()
            self._build_constellations_records_tab()

        def _build_constellations_calculator_tab(self):
            """Kalkulator konstelacji -- pick a k-tuple pattern from pattern_catalog_v1.py
            (k dropdown -> variant dropdown, showing that variant's offsets plus its
            pzktupel.de record info when tracked), enter exp/Offset, and Atlas computes
            N = 10**exp + Offset plus every N + offset_i for the pattern -- shown in a
            results table (not yet checked for primality; this is pure arithmetic, no
            file I/O, so it's instant even for a large exp).

            The Search button does NOT re-implement search itself -- it reuses the
            EXISTING "Constellations -> Magazyn" search box (self.hits_search_entry /
            self._search_constellation(), see _on_const_calc_search_selected()) against
            whichever row is currently selected, since that search already covers BOTH
            things the calculator needs to verify: is this number prime at all (offering
            to generate the missing prime window if not -- see
            _offer_generate_missing_prime_window()) AND does it actually participate in
            a tracked constellation pattern (offering to run constellation_finder_v1.py
            if the floor has genuinely never been scanned -- see
            _offer_generate_missing_constellation()). Searching all k numbers
            automatically in one click was considered (matching the literal "one button
            searches every number" framing this feature was requested with) but
            rejected: that search path already has its own async worker-thread +
            generate-offer-dialog state machine, and chaining K of those end-to-end
            would mean either blocking synchronously (defeating the point of the worker
            thread) or bolting a second layer of completion-callback state onto an
            already-intricate flow. One-row-at-a-time keeps every existing code path
            untouched and lets the user see each result (or generate-offer dialog)
            before deciding whether to search the next number.

            _on_const_calc_search_selected() ALSO does one thing beyond a plain
            self._search_constellation() call: since the calculator already knows
            EXACTLY which catalog pattern (k, variant id) this number was computed for
            (unlike the generic search box, which has no target pattern in mind), it (1)
            proactively checks whether THAT SPECIFIC pattern already has a hit file for
            this floor -- list_constellation_hits() empty-floor check the generic search
            box relies on (see _on_const_search_result()) stays silent whenever the
            floor already has hits for some OTHER pattern, which is exactly the gap a
            calculator search into an already-partially-scanned floor would otherwise
            fall into -- and offers to generate if not; and (2), once the search
            actually completes, auto-navigates the Magazyn tree straight to that
            specific (k, variant) node and jumps the preview to this exact number (see
            _select_hits_pattern_in_tree()/_jump_hits_preview_to_row(), the same helpers
            double-clicking a search result row already uses) instead of leaving the
            user to find it themselves among however many patterns the participation
            list turned up."""
            container = ttk.Frame(self.constellations_calculator_tab)
            container.pack(fill="both", expand=True, padx=12, pady=12)

            pattern_row = ttk.Frame(container)
            pattern_row.pack(fill="x", pady=(0, 8))
            ttk.Label(pattern_row, text=T("const_calc.field_k")).pack(side="left")
            self._const_calc_k_values = pattern_catalog_v1.all_k()
            self.const_calc_k_combo = ttk.Combobox(
                pattern_row, state="readonly", width=6,
                values=[str(k) for k in self._const_calc_k_values])
            self.const_calc_k_combo.pack(side="left", padx=(6, 16))
            self.const_calc_k_combo.bind("<<ComboboxSelected>>", self._on_const_calc_k_changed)

            ttk.Label(pattern_row, text=T("const_calc.field_variant")).pack(side="left")
            self._const_calc_variants = []
            self.const_calc_variant_combo = ttk.Combobox(pattern_row, state="readonly", width=10)
            self.const_calc_variant_combo.pack(side="left", padx=(6, 0))
            self.const_calc_variant_combo.bind(
                "<<ComboboxSelected>>", self._on_const_calc_variant_changed)

            self.const_calc_pattern_info_var = tk.StringVar(value="")
            ttk.Label(container, textvariable=self.const_calc_pattern_info_var,
                      wraplength=760, justify="left", foreground="#555").pack(
                anchor="w", pady=(0, 8))

            input_row = ttk.Frame(container)
            input_row.pack(fill="x", pady=(0, 8))
            ttk.Label(input_row, text=T("const_calc.field_exp")).pack(side="left")
            self.const_calc_exp_entry = ttk.Entry(input_row, width=10)
            self.const_calc_exp_entry.pack(side="left", padx=(6, 16))
            ttk.Label(input_row, text=T("const_calc.field_offset")).pack(side="left")
            self.const_calc_offset_entry = ttk.Entry(input_row, width=24)
            self.const_calc_offset_entry.pack(side="left", padx=(6, 16))
            self.const_calc_compute_button = ttk.Button(
                input_row, text=T("const_calc.compute_button"),
                command=self._on_const_calc_compute)
            self.const_calc_compute_button.pack(side="left")

            tree_frame = ttk.Frame(container)
            tree_frame.pack(fill="both", expand=True, pady=(0, 8))
            self.const_calc_results_tree = ttk.Treeview(
                tree_frame, columns=("offset", "number"), show="headings",
                height=10, selectmode="browse")
            self.const_calc_results_tree.heading("offset", text=T("const_calc.col_offset"))
            self.const_calc_results_tree.heading("number", text=T("const_calc.col_number"))
            self.const_calc_results_tree.column("offset", width=90, anchor="e")
            self.const_calc_results_tree.column("number", width=440, anchor="w")
            self.const_calc_results_tree.pack(side="left", fill="both", expand=True)
            cvsb = ttk.Scrollbar(
                tree_frame, orient="vertical", command=self.const_calc_results_tree.yview)
            self.const_calc_results_tree.configure(yscrollcommand=cvsb.set)
            cvsb.pack(side="left", fill="y")

            self.const_calc_search_button = ttk.Button(
                container, text=T("const_calc.search_button"),
                command=self._on_const_calc_search_selected, state="disabled")
            self.const_calc_search_button.pack(anchor="w")

            self._const_calc_numbers = []  # [(offset, number), ...], same order as the tree
            self._const_calc_active_pattern = None  # the exact pattern dict last used by
                                                      # _on_const_calc_compute() -- read by
                                                      # _on_const_calc_search_selected() so a
                                                      # variant-combo change AFTER computing
                                                      # doesn't retroactively change what a
                                                      # search believes it's looking for
            self._const_calc_pending = None  # {"base_exponent", "number", "pattern"} while
                                              # a calculator-initiated search is in flight --
                                              # consumed by _on_const_search_result() to
                                              # auto-navigate to the right variant once done
            if self._const_calc_k_values:
                self.const_calc_k_combo.current(0)
                self._on_const_calc_k_changed()

        def _on_const_calc_k_changed(self, _event=None):
            k_str = self.const_calc_k_combo.get()
            if not k_str:
                return
            self._const_calc_variants = pattern_catalog_v1.patterns_for_k(int(k_str))
            self.const_calc_variant_combo.configure(
                values=[T("const_calc.variant_label", id=w["id"])
                        for w in self._const_calc_variants])
            if self._const_calc_variants:
                self.const_calc_variant_combo.current(0)
            else:
                self.const_calc_variant_combo.set("")
            self._on_const_calc_variant_changed()

        def _on_const_calc_variant_changed(self, _event=None):
            idx = self.const_calc_variant_combo.current()
            if idx < 0 or idx >= len(self._const_calc_variants):
                self.const_calc_pattern_info_var.set("")
                return
            w = self._const_calc_variants[idx]
            offsets_str = ", ".join(str(o) for o in w["offsets"])
            if w["record_digits"] is not None:
                self.const_calc_pattern_info_var.set(T(
                    "const_calc.pattern_info", offsets=offsets_str,
                    record_digits=w["record_digits"], discoverer=w["discoverer"],
                    date=w["date"]))
            else:
                self.const_calc_pattern_info_var.set(
                    T("const_calc.pattern_info_untracked", offsets=offsets_str))

        def _on_const_calc_compute(self):
            idx = self.const_calc_variant_combo.current()
            if idx < 0 or idx >= len(self._const_calc_variants):
                messagebox.showerror(
                    T("const_calc.error_dialog_title"), T("const_calc.error_no_pattern"))
                return
            pattern = self._const_calc_variants[idx]
            offsets = pattern["offsets"]
            exp = _eval_quick_number(self.const_calc_exp_entry.get())
            if exp is None or exp < 0:
                messagebox.showerror(
                    T("const_calc.error_dialog_title"), T("const_calc.error_exp_invalid"))
                return
            offset_raw = self.const_calc_offset_entry.get().strip()
            base_offset = _eval_quick_number(offset_raw) if offset_raw else 0
            if base_offset is None or base_offset < 0:
                messagebox.showerror(
                    T("const_calc.error_dialog_title"), T("const_calc.error_offset_invalid"))
                return
            n0 = 10 ** exp + base_offset
            self._const_calc_active_pattern = pattern
            self._const_calc_numbers = [(d, n0 + d) for d in offsets]
            self.const_calc_results_tree.delete(*self.const_calc_results_tree.get_children())
            for d, n in self._const_calc_numbers:
                self.const_calc_results_tree.insert("", "end", values=(f"+{d}", f"{n:,}"))
            self.const_calc_search_button.configure(
                state="normal" if self._const_calc_numbers else "disabled")

        def _on_const_calc_search_selected(self):
            sel = self.const_calc_results_tree.selection()
            if not sel:
                messagebox.showinfo(
                    T("const_calc.error_dialog_title"), T("const_calc.error_select_row_first"))
                return
            idx = self.const_calc_results_tree.index(sel[0])
            if (idx < 0 or idx >= len(self._const_calc_numbers)
                    or self._const_calc_active_pattern is None):
                return
            _offset, number = self._const_calc_numbers[idx]
            pattern = self._const_calc_active_pattern
            base_exponent = digit_count_floor(number)

            # Switch to Constellations -> Magazyn up front, before any dialog fires, so
            # generate-offer confirmations and the eventual result both land where the
            # user is already looking rather than behind the still-visible calculator tab.
            self.main_notebook.select(self.constellations_tab)
            self.constellations_sub_notebook.select(self.constellations_storage_tab)
            self.hits_search_entry.delete(0, "end")
            self.hits_search_entry.insert(0, str(number))

            self._const_calc_pending = {
                "base_exponent": base_exponent, "number": number, "pattern": pattern}

            if base_exponent in list_pietra(PORTAL_FOLDER):
                # Floor exists -- but has constellation_finder_v1.py ever recorded hits
                # for THIS SPECIFIC pattern here? _on_const_search_result()'s own
                # "offer to generate" check only fires when list_constellation_hits()
                # is empty -- i.e. NOTHING has ever been scanned for this floor -- which
                # silently stays quiet whenever the floor already has hits for some
                # OTHER pattern (e.g. the user already ran the finder here for twin
                # primes). That's the right level of caution for the generic search box
                # (it has no specific pattern in mind, so "maybe check everything" isn't
                # a well-defined offer), but the calculator DOES know exactly which
                # pattern it's asking about, so it can check precisely instead of
                # guessing -- closing the gap reported after searching a calculator
                # number into a floor that had unrelated constellation hits already.
                has_this_pattern = any(
                    p["id"] == pattern["id"]
                    for p, _path, _hdr in list_constellation_hits(PORTAL_FOLDER, base_exponent)
                    if p["k"] == pattern["k"])
                if not has_this_pattern and self._offer_generate_missing_constellation(
                        base_exponent, number):
                    return  # generation launched -- _on_constellation_finished() re-runs
                            # the const search once it's done, landing back in
                            # _on_const_search_result() with self._const_calc_pending
                            # still set, same as every other path below
            self._search_constellation()

        def _build_constellations_records_tab(self):
            """pzktupel.de-style exp x variant records table, but scanning THIS PROJECT'S
            OWN storage (constellations/k{k}/variant{id}/HITS_....bin) instead of that
            website -- pick k, click Skanuj, see the smallest offset found so far for
            each floor x variant combination (build_constellation_records_table() does
            the actual scan -- see that function's own docstring for the exact
            semantics, including what the record-floor asterisk does and doesn't claim).

            Double-clicking a cell drills down into the FULL list of hits behind it (all
            2019 numbers for a "+23,080,007,797 (2019x)" cell, not just the smallest) in
            the paginated detail panel below the tree -- see
            _on_const_records_cell_activate(). Same idea as the Constellations tab's own
            expand-to-preview flow, just inline in this tab instead of a separate
            navigation step, per user request.

            Export to PDF (render_constellation_records_pdf(), same low-level PDF writer
            as the Benchmark tab's export) or CSV (plain csv.DictWriter) now pulls the
            SAME full-detail data as the cell drill-down (one row per individual hit,
            via build_constellation_records_detail_rows()) rather than the compact
            on-screen summary -- also per user request ("pełna tabela z wszystkimi
            elementami"): the summary's smallest-offset-per-cell shape is right for
            browsing, but not for an exported reference file meant to hold everything
            found so far. Export always covers the SAME floor range as the currently
            displayed table (self._const_records_last_floor_bounds, captured at scan
            time) -- not the live contents of the od/do fields, in case they've been
            edited since the last Skanuj click.

            Optional "Piętro od/do" fields scope the on-screen scan to a floor range
            (see build_constellation_records_table()'s own docstring) -- added because
            an unbounded scan over a storage with many populated floors produces a
            table that's mostly noise (a wall of "-" cells for floors the user isn't
            looking at right now), not because the scan itself is too slow to run
            unbounded.

            Scans AND exports run on the SAME worker thread (queue pair here matches
            every other worker in this file -- see e.g. _primesieve_calc_worker_loop's
            own docstring for the shared rationale), distinguished by a job["mode"]
            field ("scan" / "export_pdf" / "export_csv") -- reading every hit file in
            full for an export is more expensive than the summary scan's "just the
            first value" read, so keeping it off the GUI thread matters even more here."""
            container = ttk.Frame(self.constellations_records_tab)
            container.pack(fill="both", expand=True, padx=12, pady=12)

            top_row = ttk.Frame(container)
            top_row.pack(fill="x", pady=(0, 8))
            ttk.Label(top_row, text=T("const_records.field_k")).pack(side="left")
            self.const_records_k_combo = ttk.Combobox(
                top_row, state="readonly", width=6,
                values=[str(k) for k in pattern_catalog_v1.all_k()])
            self.const_records_k_combo.pack(side="left", padx=(6, 16))
            ttk.Label(top_row, text=T("const_records.field_floor_from")).pack(side="left")
            self.const_records_floor_from_entry = ttk.Entry(top_row, width=8)
            self.const_records_floor_from_entry.pack(side="left", padx=(6, 12))
            ttk.Label(top_row, text=T("const_records.field_floor_to")).pack(side="left")
            self.const_records_floor_to_entry = ttk.Entry(top_row, width=8)
            self.const_records_floor_to_entry.pack(side="left", padx=(6, 16))
            self.const_records_scan_button = ttk.Button(
                top_row, text=T("const_records.scan_button"),
                command=self._on_const_records_scan_clicked)
            self.const_records_scan_button.pack(side="left")
            self.const_records_export_pdf_button = ttk.Button(
                top_row, text=T("const_records.export_pdf_button"),
                command=self._export_const_records_pdf, state="disabled")
            self.const_records_export_pdf_button.pack(side="left", padx=(16, 0))
            self.const_records_export_csv_button = ttk.Button(
                top_row, text=T("const_records.export_csv_button"),
                command=self._export_const_records_csv, state="disabled")
            self.const_records_export_csv_button.pack(side="left", padx=(6, 0))

            ttk.Label(container, text=T("const_records.hint"), wraplength=760,
                      justify="left", foreground="#555").pack(anchor="w", pady=(0, 8))

            # Vertical split: table on top, full-hit-list drill-down for whatever cell
            # was last double-clicked on the bottom -- same "tree above, detail panel
            # below" shape as the Constellations tab's own paned view, just stacked
            # instead of side-by-side since this table's rows are wide but few, while
            # its drill-down list is narrow but potentially long.
            #
            # Plain tk.PanedWindow here, not ttk.Panedwindow (used everywhere else in
            # this file) -- ttk's sash is a near-invisible 1-2px line on most themes,
            # which read as "no divider at all, can't resize" (user report). tk's
            # PanedWindow exposes sashwidth/sashrelief directly, giving an actually
            # visible grab bar. stretch="never" on the tree pane + a dynamic tree
            # height (see _rebuild_const_records_tree's row_count param) means the top
            # pane's natural size already tracks how many floors are in the table
            # instead of always claiming a fixed block of mostly-empty space; the
            # detail pane (stretch="always") absorbs any extra space on window resize.
            # The sash stays fully manually draggable either way.
            paned = tk.PanedWindow(container, orient="vertical", sashwidth=6,
                                    sashrelief="raised", sashpad=1, bg="#c8c8c8")
            paned.pack(fill="both", expand=True)

            self.const_records_tree_frame = ttk.Frame(paned)
            paned.add(self.const_records_tree_frame, minsize=60, stretch="never")
            self.const_records_tree = None  # built fresh per scan -- see
                                             # _rebuild_const_records_tree(), column
                                             # count depends on how many variants k has
            self.const_records_tree_vsb = None  # its scrollbars, tracked separately so
            self.const_records_tree_hsb = None  # they can be destroyed alongside the
                                                 # tree on rebuild (see that method's
                                                 # own note)
            self._const_records_last = None  # (k, variant_ids, variant_meta, rows) from
                                              # the most recently finished scan -- read by
                                              # the cell drill-down and both export
                                              # buttons (for k; rows/variant_ids are the
                                              # compact summary, NOT what gets exported)
            self._const_records_last_floor_bounds = (None, None)  # (floor_min, floor_max)
                                              # used by that same scan -- exports reuse
                                              # this exact scope rather than re-reading
                                              # the od/do fields, which may have changed
                                              # since Skanuj was last clicked
            self._rebuild_const_records_tree([])

            detail_frame = ttk.Frame(paned)
            paned.add(detail_frame, minsize=100, stretch="always")
            self.const_records_detail_label_var = tk.StringVar(
                value=T("const_records.detail_hint"))
            ttk.Label(detail_frame, textvariable=self.const_records_detail_label_var,
                      anchor="w").pack(fill="x", padx=4, pady=(2, 4))

            # _FlowRow, same reasoning as every other preview-nav row in this file --
            # see that class's own docstring.
            detail_nav = _FlowRow(detail_frame)
            detail_nav.frame.pack(anchor="w", padx=4, fill="x")
            self.const_records_detail_prev_btn = ttk.Button(
                detail_nav.frame, text=T("common.prev_page"),
                command=self._prev_const_records_detail_page, state="disabled")
            detail_nav.add(self.const_records_detail_prev_btn)
            self.const_records_detail_page_label = tk.StringVar(value="")
            detail_nav.add(ttk.Label(detail_nav.frame,
                                      textvariable=self.const_records_detail_page_label,
                                      width=16, anchor="center"))
            self.const_records_detail_next_btn = ttk.Button(
                detail_nav.frame, text=T("common.next_page"),
                command=self._next_const_records_detail_page, state="disabled")
            detail_nav.add(self.const_records_detail_next_btn)
            detail_nav.add(ttk.Label(detail_nav.frame, text=T("common.page_prefix")),
                            padx_left=10)
            self.const_records_detail_goto_entry = ttk.Entry(detail_nav.frame, width=6)
            detail_nav.add(self.const_records_detail_goto_entry, padx_left=4)
            self.const_records_detail_goto_entry.bind(
                "<Return>", lambda _e: self._goto_const_records_detail_page())
            detail_nav.add(ttk.Button(detail_nav.frame, text=T("common.goto"),
                                       command=self._goto_const_records_detail_page),
                            padx_left=4)

            detail_list_frame = ttk.Frame(detail_frame)
            detail_list_frame.pack(fill="both", expand=True, padx=4, pady=(0, 4))
            self.const_records_detail_list = tk.Listbox(detail_list_frame, font=("Consolas", 9))
            detail_vsb = ttk.Scrollbar(detail_list_frame, orient="vertical",
                                        command=self.const_records_detail_list.yview)
            self.const_records_detail_list.configure(yscrollcommand=detail_vsb.set)
            self.const_records_detail_list.pack(side="left", fill="both", expand=True)
            detail_vsb.pack(side="right", fill="y")

            # Same Ctrl+C / right-click "Copy" convenience as the Constellations tab's
            # own hits preview list. Double-click jumps to that exact hit in the
            # Constellations tab's own Magazyn view -- see
            # _on_const_records_detail_activate()'s own docstring.
            self.const_records_detail_list.bind(
                "<Control-c>", lambda _e: self._copy_selected_const_records_detail_value())
            self.const_records_detail_list.bind(
                "<Button-3>", self._show_const_records_detail_context_menu)
            self.const_records_detail_list.bind(
                "<Double-Button-1>", self._on_const_records_detail_activate)
            self._const_records_detail_context_menu = tk.Menu(self, tearoff=0)
            self._const_records_detail_context_menu.add_command(
                label=T("common.copy"), command=self._copy_selected_const_records_detail_value)

            self._const_records_detail_rows = []  # [(number, offset), ...] for whichever
                                                    # cell was last double-clicked
            self._const_records_detail_context = None  # {"base_exponent":, "pattern":}
                                                         # for that same cell -- needed
                                                         # by the jump-to-Magazyn handler
            self._const_records_detail_page = 0
            self._const_records_detail_total_pages = 1

            if pattern_catalog_v1.all_k():
                self.const_records_k_combo.current(0)

        def _rebuild_const_records_tree(self, variant_ids, row_count=0):
            """(Re)builds self.const_records_tree with one column per variant id, plus
            the fixed leading 'exp' column -- a plain ttk.Treeview can't have its column
            SET changed after construction, and different k values have different
            variant counts (k=8 has 3, k=13 has 6), so the tree is destroyed and
            recreated on every scan rather than trying to reuse one fixed-shape widget.

            Both scrollbars are destroyed and recreated right alongside it (tracked in
            self.const_records_tree_vsb/_hsb, not just throwaway locals) -- previously
            the vertical one was a local variable never torn down, so every Skanuj click
            left the old one behind, orphaned in the frame, stacking up one more
            scrollbar per scan.

            Every column is stretch=False (fixed width) with an added horizontal
            scrollbar -- same fix as the Benchmark tab's tree (see its own comment for
            the rationale): without this, Tk auto-stretches columns to fill the frame,
            which for a single-variant k pushes that one column's header far from its
            data (the empty gap the user reported), and for a many-variant k instead
            squeezes everything down with no way to see the columns pushed off the
            right edge -- neither is fixable by resizing the window, since Tk was
            filling/squeezing to the CURRENT width either way. Fixed width + horizontal
            scroll makes the table's real width consistent regardless of variant count,
            and lets the user actually scroll to whatever doesn't fit.

            `row_count` (the number of floor-rows about to be inserted, known upfront by
            the caller even though insertion happens after this returns) sizes the
            Treeview's own `height` to match -- capped at 14 so a huge scan doesn't
            balloon the visible area, floored at 3 so an empty/fresh table isn't
            reduced to a sliver. Combined with the tree pane's stretch="never" in the
            paned window (see _build_constellations_records_tab's own note), this makes
            the top pane's size track the actual amount of data instead of always
            claiming a fixed block of space regardless of how few rows there are --
            user report: 2 rows of data sitting in a mostly-empty ~460px pane.

            The <Double-Button-1> binding for cell drill-down is (re)attached here too,
            not just once at tab-build time -- since this whole widget gets destroyed
            and recreated on every scan, a binding made only in
            _build_constellations_records_tab() would silently stop firing after the
            very first Skanuj click, once the original bound widget is gone."""
            if self.const_records_tree is not None:
                self.const_records_tree.destroy()
            if self.const_records_tree_vsb is not None:
                self.const_records_tree_vsb.destroy()
            if self.const_records_tree_hsb is not None:
                self.const_records_tree_hsb.destroy()
            columns = ("exp",) + tuple(f"v{vid}" for vid in variant_ids)
            height = max(3, min(row_count, 14)) if row_count else 3
            tree = ttk.Treeview(
                self.const_records_tree_frame, columns=columns, show="headings", height=height)
            tree.heading("exp", text=T("const_records.col_exp"))
            tree.column("exp", width=70, anchor="e", stretch=False)
            for vid in variant_ids:
                tree.heading(f"v{vid}", text=T("const_calc.variant_label", id=vid))
                tree.column(f"v{vid}", width=190, anchor="w", stretch=False)
            vsb = ttk.Scrollbar(self.const_records_tree_frame, orient="vertical",
                                 command=tree.yview)
            hsb = ttk.Scrollbar(self.const_records_tree_frame, orient="horizontal",
                                 command=tree.xview)
            tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
            vsb.pack(side="right", fill="y")
            hsb.pack(side="bottom", fill="x")
            tree.pack(side="left", fill="both", expand=True)
            tree.bind("<Double-Button-1>", self._on_const_records_cell_activate)
            self.const_records_tree = tree
            self.const_records_tree_vsb = vsb
            self.const_records_tree_hsb = hsb

        def _on_const_records_scan_clicked(self):
            if self._const_records_busy:
                return
            k_str = self.const_records_k_combo.get()
            if not k_str:
                messagebox.showerror(
                    T("const_records.error_dialog_title"), T("const_calc.error_no_pattern"))
                return
            k = int(k_str)
            floor_min = _eval_quick_number(self.const_records_floor_from_entry.get())
            floor_max = _eval_quick_number(self.const_records_floor_to_entry.get())
            if floor_min is not None and floor_max is not None and floor_min > floor_max:
                messagebox.showerror(
                    T("const_records.error_dialog_title"), T("const_records.error_invalid_range"))
                return
            self._const_records_start_job(
                {"mode": "scan", "k": k, "floor_min": floor_min, "floor_max": floor_max},
                T("const_records.status_scanning", k=k))

        def _const_records_start_job(self, job, status_text):
            """Shared dispatch for every job this tab's worker can run (scan/export_pdf/
            export_csv) -- all three are mutually exclusive (one at a time, same busy
            flag/progress bar/button-disabling), so this is the one place that logic
            lives instead of being copy-pasted into each of the three click handlers."""
            self._const_records_busy = True
            self.const_records_scan_button.configure(state="disabled")
            self.const_records_export_pdf_button.configure(state="disabled")
            self.const_records_export_csv_button.configure(state="disabled")
            self.totals_progress.stop()
            self.totals_progress.configure(mode="indeterminate")
            self.totals_progress.start(80)
            self.status.set(status_text)
            self._const_records_work_queue.put(job)

        def _const_records_worker_loop(self):
            while True:
                job = self._const_records_work_queue.get()
                mode = job.get("mode", "scan")
                k = job["k"]
                floor_min = job.get("floor_min")
                floor_max = job.get("floor_max")
                try:
                    if mode == "scan":
                        variant_ids, variant_meta, rows = build_constellation_records_table(
                            PORTAL_FOLDER, k, floor_min=floor_min, floor_max=floor_max)
                        self._const_records_result_queue.put(
                            (mode, k, True, (variant_ids, variant_meta, rows, floor_min, floor_max)))
                    else:  # export_pdf / export_csv
                        _variant_ids, _variant_meta, detail_rows = (
                            build_constellation_records_detail_rows(
                                PORTAL_FOLDER, k, floor_min=floor_min, floor_max=floor_max))
                        path = job["path"]
                        if mode == "export_pdf":
                            self._render_const_records_detail_pdf(path, k, detail_rows)
                        else:
                            self._write_const_records_detail_csv(path, detail_rows)
                        self._const_records_result_queue.put((mode, k, True, path))
                except Exception as e:  # noqa: BLE001 -- must never kill this thread
                    self._const_records_result_queue.put((mode, k, False, str(e)))

        def _render_const_records_detail_pdf(self, path, k, detail_rows):
            """Runs on the worker thread (called from _const_records_worker_loop) --
            builds the PDF fieldnames/rows from build_constellation_records_detail_rows()'
            flat per-hit dicts and hands them to render_constellation_records_pdf(),
            same low-level writer the old summary export used. One row per individual
            hit (see that function's own docstring for why), so a floor with 2019 hits
            produces 2019 PDF rows/however many continuation pages that takes -- exactly
            what was asked for ("pełna tabela z wszystkimi elementami"), not a
            regression from the old compact one-row-per-floor shape."""
            fieldnames = ["exp", "id", "offset", "number"]
            pdf_rows = [{
                "exp": f"10p{r['base_exponent']}",
                "id": r["variant_id"],
                "offset": f"+{r['offset']:,}" + (" *" if r["is_record_floor"] else ""),
                "number": r["number"],
            } for r in detail_rows]
            render_constellation_records_pdf(path, k, fieldnames, pdf_rows, translator=TRANSLATOR)

        def _write_const_records_detail_csv(self, path, detail_rows):
            """Runs on the worker thread (called from _const_records_worker_loop) --
            plain csv.DictWriter, one row per individual hit (see
            build_constellation_records_detail_rows()'s own docstring)."""
            fieldnames = ["exp", "variant_id", "offset", "number",
                          "position_in_file", "count_in_file", "is_record_floor"]
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for r in detail_rows:
                    writer.writerow({
                        "exp": f"10p{r['base_exponent']}",
                        "variant_id": r["variant_id"],
                        "offset": r["offset"],
                        "number": r["number"],
                        "position_in_file": r["position_in_file"],
                        "count_in_file": r["count_in_file"],
                        "is_record_floor": r["is_record_floor"],
                    })

        def _poll_const_records_results(self):
            try:
                while True:
                    mode, k, ok, payload = self._const_records_result_queue.get_nowait()
                    self._const_records_busy = False
                    self.const_records_scan_button.configure(state="normal")
                    self.totals_progress.stop()
                    self.totals_progress.configure(mode="determinate", maximum=1, value=0)
                    if mode == "scan":
                        if not ok:
                            # Scan failed -- self._const_records_last (if any) still
                            # holds the last SUCCESSFUL scan's data untouched, so restore
                            # the export buttons to match it instead of leaving them
                            # disabled from _const_records_start_job() (which disables
                            # all three buttons up front, since a scan and an export
                            # can't usefully run at the same time).
                            has_rows = bool(self._const_records_last and self._const_records_last[3])
                            self.const_records_export_pdf_button.configure(
                                state="normal" if has_rows else "disabled")
                            self.const_records_export_csv_button.configure(
                                state="normal" if has_rows else "disabled")
                            self.status.set(T("const_records.status_error"))
                            messagebox.showerror(T("const_records.error_dialog_title"), payload)
                            continue
                        variant_ids, variant_meta, rows, floor_min, floor_max = payload
                        self._show_const_records_results(
                            k, variant_ids, variant_meta, rows, floor_min, floor_max)
                    else:  # export_pdf / export_csv
                        has_rows = bool(self._const_records_last and self._const_records_last[3])
                        self.const_records_export_pdf_button.configure(
                            state="normal" if has_rows else "disabled")
                        self.const_records_export_csv_button.configure(
                            state="normal" if has_rows else "disabled")
                        button_label = T("const_records.export_pdf_button" if mode == "export_pdf"
                                          else "const_records.export_csv_button")
                        if not ok:
                            self.status.set(T("const_records.status_error"))
                            messagebox.showerror(T("const_records.error_dialog_title"), payload)
                            continue
                        path = payload
                        self.status.set(T("bench.status_saved", path=path))
                        messagebox.showinfo(button_label, T("bench.saved_dialog", path=path))
            except queue.Empty:
                pass
            self.after(150, self._poll_const_records_results)

        def _show_const_records_results(self, k, variant_ids, variant_meta, rows, floor_min, floor_max):
            self._const_records_last = (k, variant_ids, variant_meta, rows)
            self._const_records_last_floor_bounds = (floor_min, floor_max)
            self._rebuild_const_records_tree(variant_ids, row_count=len(rows))
            for row in rows:
                values = [f"10p{row['base_exponent']}"]
                for vid in variant_ids:
                    cell = row["cells"].get(vid)
                    if cell is None:
                        values.append("-")
                    else:
                        text = f"+{cell['offset']:,} ({cell['count']}x)"
                        if cell["is_record_floor"]:
                            text += " *"
                        values.append(text)
                # iid = the floor number itself (unique -- one row per floor), so a cell
                # double-click can recover which floor was clicked directly from
                # identify_row() without a separate item->floor lookup table.
                self.const_records_tree.insert(
                    "", "end", iid=str(row["base_exponent"]), values=tuple(values))
            has_rows = bool(rows)
            self.const_records_export_pdf_button.configure(state="normal" if has_rows else "disabled")
            self.const_records_export_csv_button.configure(state="normal" if has_rows else "disabled")
            self.status.set(T(
                "const_records.status_done" if has_rows else "const_records.status_no_hits",
                k=k, count=len(rows)))
            # The tree was just torn down and rebuilt -- any iid the detail panel was
            # showing no longer exists, so reset it rather than leaving a stale list on
            # screen that no longer corresponds to anything selectable.
            self._const_records_detail_rows = []
            self._const_records_detail_context = None
            self.const_records_detail_label_var.set(T("const_records.detail_hint"))
            self._show_const_records_detail_page(0)

        def _on_const_records_cell_activate(self, event):
            """Double-click drill-down: identifies which (floor, variant) cell was
            clicked and loads the FULL list of hits behind it (not just the smallest
            offset the tree cell shows) into the paginated detail panel below --
            addresses the user's "nie mogę rozwinąć by je zobaczyć tak jak w zakładce
            konstelacje" report (this table's cells only ever showed a one-line
            summary, with no way to see the rest without leaving the tab).

            Stashes (base_exponent, pattern) in self._const_records_detail_context --
            not just the raw values -- so a later double-click on one of the resulting
            rows (_on_const_records_detail_activate) knows which floor/pattern that
            row belongs to without having to re-derive it from the label text."""
            tree = self.const_records_tree
            if tree.identify_region(event.x, event.y) != "cell":
                return
            row_id = tree.identify_row(event.y)
            col_id = tree.identify_column(event.x)  # "#1" = exp, "#2".. = variants
            if not row_id or not col_id or self._const_records_last is None:
                return
            try:
                base_exponent = int(row_id)
                col_index = int(col_id[1:]) - 1  # 0-based into the columns tuple
            except (ValueError, IndexError):
                return
            k, variant_ids, variant_meta, _rows = self._const_records_last
            vi = col_index - 1  # columns[0] is "exp" -- skip it, no cell data there
            if vi < 0 or vi >= len(variant_ids):
                return
            vid = variant_ids[vi]
            pattern = variant_meta[vid]
            path = hit_file_path(PORTAL_FOLDER, base_exponent, k, vid)
            if not os.path.exists(path):
                self._const_records_detail_rows = []
                self._const_records_detail_context = None
                self.const_records_detail_label_var.set(
                    T("const_records.detail_empty", exp=base_exponent, id=vid))
                self._show_const_records_detail_page(0)
                return
            try:
                values = prime_sieve_v1.read_prime_window(path)
            except Exception as exc:
                messagebox.showerror(T("const_records.error_dialog_title"), str(exc))
                return
            base = 10 ** base_exponent
            self._const_records_detail_rows = [(v, v - base) for v in values]
            self._const_records_detail_context = {"base_exponent": base_exponent, "pattern": pattern}
            self.const_records_detail_label_var.set(
                T("const_records.detail_title", exp=base_exponent, id=vid, count=len(values)))
            self._show_const_records_detail_page(0)

        def _on_const_records_detail_activate(self, event):
            """Double-click a hit in the drill-down list: jumps to the Constellations
            tab's Magazyn sub-tab, expands/selects the exact floor+variant node there,
            and scrolls its own hits preview straight to this number -- the same
            navigation the Kalkulator konstelacji's 'Szukaj zaznaczoną liczbę' button
            already does (_select_hits_pattern_in_tree / _load_hits_preview /
            _jump_hits_preview_to_row), just triggered from here instead. Per user
            request: 'dwukrotne kliknięcie na daną wartość z okna dolnego przenosi do
            [...] magazyn [...] tak jak w szukajce'.

            Each row here is a hit file's raw stored value, i.e. a tuple's BASE element
            (position 0 in _hit_row_formatter's own numbering -- see
            _on_const_records_cell_activate's read of prime_sieve_v1.read_prime_window,
            which returns exactly those base values), so the jump always targets
            position 0, never needing to look up which tuple position this row is."""
            sel = self.const_records_detail_list.curselection()
            if not sel or not self._const_records_detail_rows or self._const_records_detail_context is None:
                return
            global_index = self._const_records_detail_page * PAGE_SIZE + sel[0]
            if global_index >= len(self._const_records_detail_rows):
                return
            hit_base, _offset = self._const_records_detail_rows[global_index]
            ctx = self._const_records_detail_context
            base_exponent = ctx["base_exponent"]
            pattern = ctx["pattern"]

            self.main_notebook.select(self.constellations_tab)
            self.constellations_sub_notebook.select(self.constellations_storage_tab)
            self._select_hits_pattern_in_tree(base_exponent, pattern)
            self._load_hits_preview()
            self._jump_hits_preview_to_row(hit_base, 0)

        def _const_records_detail_row_formatter(self, row):
            number, offset = row
            return T("const_records.detail_row", number=f"{number:,}", offset=f"{offset:,}")

        def _show_const_records_detail_page(self, page):
            if not self._const_records_detail_rows:
                self.const_records_detail_list.delete(0, "end")
                self.const_records_detail_page_label.set("")
                self.const_records_detail_prev_btn.configure(state="disabled")
                self.const_records_detail_next_btn.configure(state="disabled")
                return
            self._const_records_detail_page, self._const_records_detail_total_pages = _render_page(
                self.const_records_detail_list, self._const_records_detail_rows, page, PAGE_SIZE,
                self._const_records_detail_row_formatter)
            _update_nav_controls(
                self.const_records_detail_page_label, self._const_records_detail_page,
                self._const_records_detail_total_pages,
                self.const_records_detail_prev_btn, self.const_records_detail_next_btn)

        def _prev_const_records_detail_page(self):
            self._show_const_records_detail_page(self._const_records_detail_page - 1)

        def _next_const_records_detail_page(self):
            self._show_const_records_detail_page(self._const_records_detail_page + 1)

        def _goto_const_records_detail_page(self):
            raw = self.const_records_detail_goto_entry.get().strip()
            if not raw.isdigit():
                return
            self._show_const_records_detail_page(int(raw) - 1)

        def _show_const_records_detail_context_menu(self, event):
            index = self.const_records_detail_list.nearest(event.y)
            if index >= 0:
                self.const_records_detail_list.selection_clear(0, "end")
                self.const_records_detail_list.selection_set(index)
            self._const_records_detail_context_menu.tk_popup(event.x_root, event.y_root)

        def _copy_selected_const_records_detail_value(self):
            sel = self.const_records_detail_list.curselection()
            if not sel or not self._const_records_detail_rows:
                return
            global_index = self._const_records_detail_page * PAGE_SIZE + sel[0]
            if global_index >= len(self._const_records_detail_rows):
                return
            self.clipboard_clear()
            self.clipboard_append(str(self._const_records_detail_rows[global_index][0]))

        def _export_const_records_pdf(self):
            if not self._const_records_last or self._const_records_busy:
                return
            k = self._const_records_last[0]
            default_name = (f"constellation_records_k{k}_"
                             f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
            path = filedialog.asksaveasfilename(
                title=T("const_records.export_pdf_button"),
                initialdir=PORTAL_FOLDER,
                initialfile=default_name,
                defaultextension=".pdf",
                filetypes=[("PDF", "*.pdf"), (T("common.all_files"), "*.*")])
            if not path:
                return
            floor_min, floor_max = self._const_records_last_floor_bounds
            self._const_records_start_job(
                {"mode": "export_pdf", "k": k, "floor_min": floor_min, "floor_max": floor_max,
                 "path": path},
                T("const_records.status_exporting", k=k))

        def _export_const_records_csv(self):
            if not self._const_records_last or self._const_records_busy:
                return
            k = self._const_records_last[0]
            default_name = (f"constellation_records_k{k}_"
                             f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
            path = filedialog.asksaveasfilename(
                title=T("const_records.export_csv_button"),
                initialdir=PORTAL_FOLDER,
                initialfile=default_name,
                defaultextension=".csv",
                filetypes=[("CSV", "*.csv"), (T("common.all_files"), "*.*")])
            if not path:
                return
            floor_min, floor_max = self._const_records_last_floor_bounds
            self._const_records_start_job(
                {"mode": "export_csv", "k": k, "floor_min": floor_min, "floor_max": floor_max,
                 "path": path},
                T("const_records.status_exporting", k=k))

        def _build_constellations_tab(self):
            top = ttk.Frame(self.constellations_storage_tab)
            top.pack(fill="x", padx=6, pady=4)
            ttk.Button(top, text=T("common.refresh"), command=self.reload_constellations_tree).pack(side="left")

            ttk.Label(top, text=T("common.search_label")).pack(side="left")
            self.hits_search_entry = ttk.Entry(top, width=26)
            self.hits_search_entry.pack(side="left", padx=(4, 4))
            self.hits_search_entry.bind("<Return>", lambda _e: self._search_constellation())
            self.hits_search_button = ttk.Button(
                top, text=T("common.search_button"), command=self._search_constellation)
            self.hits_search_button.pack(side="left")

            paned = ttk.Panedwindow(self.constellations_storage_tab, orient="horizontal")
            paned.pack(fill="both", expand=True, padx=6, pady=4)

            tree_frame = ttk.Frame(paned)
            paned.add(tree_frame, weight=1)

            self.hits_tree = ttk.Treeview(tree_frame, columns=("count", "generated"), show="tree headings")
            self.hits_tree.heading("#0", text=T("const.col_pietro"))
            self.hits_tree.heading("count", text=T("const.col_count"))
            self.hits_tree.heading("generated", text=T("const.col_generated"))
            self.hits_tree.column("#0", width=280)
            self.hits_tree.column("count", width=90, anchor="e")
            self.hits_tree.column("generated", width=170)
            hvsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.hits_tree.yview)
            self.hits_tree.configure(yscrollcommand=hvsb.set)
            self.hits_tree.pack(side="left", fill="both", expand=True)
            hvsb.pack(side="right", fill="y")

            self.hits_tree.bind("<<TreeviewOpen>>", self._on_hits_tree_open)
            self.hits_tree.bind("<<TreeviewSelect>>", self._on_hits_tree_select)

            detail_frame = ttk.Frame(paned)
            paned.add(detail_frame, weight=2)

            self.hits_detail_text = tk.StringVar(value=T("const.detail_hint"))
            ttk.Label(detail_frame, textvariable=self.hits_detail_text, justify="left",
                      anchor="nw", wraplength=560).pack(fill="x", padx=6, pady=6)

            # Populated only after a search (empty during normal tree browsing): one row
            # per pattern the searched number participates in. Double-click (or Enter)
            # jumps straight to that exact hit's row in the preview below, mirroring how
            # the Prime numbers tab's search lands directly on the found number.
            self.search_results_list = tk.Listbox(detail_frame, height=5, font=("Consolas", 9))
            self.search_results_list.pack(fill="x", padx=6, pady=(0, 6))
            self.search_results_list.bind("<Double-Button-1>", self._on_search_result_activate)
            self.search_results_list.bind("<Return>", self._on_search_result_activate)
            self._search_results_data = []  # parallel to search_results_list rows

            # _FlowRow, same reasoning as the Prime numbers tab's own preview-nav row --
            # see that class's docstring.
            btn_row = _FlowRow(detail_frame)
            btn_row.frame.pack(anchor="w", padx=6, fill="x")
            self.hits_load_preview_btn = ttk.Button(
                btn_row.frame, text=T("common.load_preview"), command=self._load_hits_preview,
                state="disabled")
            btn_row.add(self.hits_load_preview_btn)
            self.hits_prev_page_btn = ttk.Button(
                btn_row.frame, text=T("common.prev_page"), command=self._prev_hits_page, state="disabled")
            btn_row.add(self.hits_prev_page_btn, padx_left=10)
            self.hits_page_label = tk.StringVar(value="")
            btn_row.add(ttk.Label(btn_row.frame, textvariable=self.hits_page_label,
                                   width=16, anchor="center"))
            self.hits_next_page_btn = ttk.Button(
                btn_row.frame, text=T("common.next_page"), command=self._next_hits_page, state="disabled")
            btn_row.add(self.hits_next_page_btn)
            btn_row.add(ttk.Label(btn_row.frame, text=T("common.page_prefix")), padx_left=10)
            self.hits_goto_entry = ttk.Entry(btn_row.frame, width=6)
            btn_row.add(self.hits_goto_entry, padx_left=4)
            self.hits_goto_entry.bind("<Return>", lambda _e: self._goto_hits_page())
            btn_row.add(ttk.Button(btn_row.frame, text=T("common.goto"),
                                    command=self._goto_hits_page), padx_left=4)

            hits_preview_frame = ttk.Frame(detail_frame)
            hits_preview_frame.pack(fill="both", expand=True, padx=6, pady=6)
            self.hits_preview_list = tk.Listbox(hits_preview_frame, font=("Consolas", 9))
            hits_preview_vsb = ttk.Scrollbar(hits_preview_frame, orient="vertical",
                                              command=self.hits_preview_list.yview)
            self.hits_preview_list.configure(yscrollcommand=hits_preview_vsb.set)
            self.hits_preview_list.pack(side="left", fill="both", expand=True)
            hits_preview_vsb.pack(side="right", fill="y")

            # Each row here is ONE number (the pattern's position/offset context is shown
            # alongside it, not merged into a single copy-unfriendly comma-joined tuple
            # string) -- same Ctrl+C / right-click "Copy" convenience as the primes tab.
            self.hits_preview_list.bind("<Control-c>", lambda _e: self._copy_selected_hits_value())
            self.hits_preview_list.bind("<Button-3>", self._show_hits_context_menu)
            self._hits_context_menu = tk.Menu(self, tearoff=0)
            self._hits_context_menu.add_command(label=T("common.copy"), command=self._copy_selected_hits_value)

            self._selected_hit_path = None
            self._selected_hit_pattern = None  # dict from pattern_catalog_v1, needed to
                                                # know each position's offset within a tuple
            self._hit_values = None    # raw decoded starting values for the selected
                                        # pattern's hit file, sorted ascending
            self._hit_rows = None      # flattened (value, hit_base, position, offset) --
                                        # one entry PER TUPLE POSITION, not per hit, so each
                                        # preview row is a single number like the primes tab
            self._hit_page = 0
            self._hit_total_pages = 1
            self._hit_set_cache = {}  # (base_exponent, k, id) -> set(starting values),
                                       # reused across searches within this session

        def reload_constellations_tree(self):
            # Same reasoning as reload_primes_tree()'s own call to this -- this tab's own
            # Refresh button can be clicked without reload_primes_tree() ever running in
            # the same gesture (e.g. right after constellation-finding finishes -- see
            # _on_constellation_finished()), so the sweep is repeated here too rather than
            # relying on the OTHER tree's refresh to have already covered it. Cheap and
            # idempotent (see prune_empty_pietro_dirs()'s own docstring) -- calling it
            # twice when both trees do refresh together costs one extra os.listdir() pass.
            prune_empty_pietro_dirs(PORTAL_FOLDER)
            self.hits_tree.delete(*self.hits_tree.get_children())
            # Only floors that actually HAVE at least one detected constellation hit --
            # list_pietra() alone would include every floor with prime data, regardless of
            # whether the constellation finder has ever been run against it (or ran and
            # found nothing), cluttering this tree with entries that only ever expand into
            # an empty "no hits" placeholder. See floor_has_constellation_hits()'s own
            # docstring.
            pietra = [be for be in list_pietra(PORTAL_FOLDER)
                      if floor_has_constellation_hits(PORTAL_FOLDER, be)]
            for base_exponent in pietra:
                node = self.hits_tree.insert("", "end", text=f"10p{base_exponent}",
                                              values=("", ""), open=False, tags=("pietro",))
                self.hits_tree.insert(node, "end", text=T("common.loading"))
            self._hit_set_cache = {}  # data on disk may have changed since last refresh

        def _on_hits_tree_open(self, _event):
            node = self.hits_tree.focus()
            self._populate_hits_pietro_node(node)

        def _populate_hits_pietro_node(self, node):
            children = self.hits_tree.get_children(node)
            if len(children) != 1:
                return
            if self.hits_tree.item(children[0], "text") != T("common.loading"):
                return
            self.hits_tree.delete(children[0])

            base_exponent = int(self.hits_tree.item(node, "text")[3:])  # "10p{N}"
            entries = list_constellation_hits(PORTAL_FOLDER, base_exponent)
            if not entries:
                self.hits_tree.insert(node, "end", text=T("const.no_hits"))
                return

            # Nested by k, each with its own subtotal -- otherwise every
            # variant is a flat sibling row ("k=7 v=1", "k=7 v=2", ...) with no way to see
            # how many k-tuples exist IN TOTAL for a given k without adding the variant
            # counts up by hand. group_constellation_hits_by_k() re-groups what
            # list_constellation_hits() already fetched -- no extra I/O, the pattern catalog
            # is small enough that every existing hit file's header is already read above.
            # The floor row itself is also updated here to the grand total across every k
            # (sum of every k-group's own subtotal) -- for the SAME reason: previously blank.
            grand_total = 0
            self._hit_path_by_item = getattr(self, "_hit_path_by_item", {})
            for k, k_total, variants in group_constellation_hits_by_k(entries):
                grand_total += k_total
                k_node = self.hits_tree.insert(
                    node, "end", text=T("const.k_total", k=k, total=f"{k_total:,}"),
                    values=("", ""), tags=("k_group",), open=True)
                for pattern, path, header in variants:
                    label_text = f"v={pattern['id']}"
                    if header is None:
                        count_str, gen_str = "?", T("primes.unreadable_header")
                    else:
                        count_str = f"{header['count']:,}"
                        gen_str = header["generated_at_iso"]
                    child = self.hits_tree.insert(
                        k_node, "end", text=label_text,
                        values=(count_str, gen_str), tags=("pattern",))
                    self._hit_path_by_item[child] = (pattern, path, header)
            self.hits_tree.item(node, values=(f"{grand_total:,}", ""))

        def _on_hits_tree_select(self, _event):
            selection = self.hits_tree.selection()
            if not selection:
                return
            item = selection[0]
            path_map = getattr(self, "_hit_path_by_item", {})
            self._reset_hits_preview_state()
            if item not in path_map:
                self.hits_load_preview_btn.configure(state="disabled")
                return
            pattern, path, header = path_map[item]
            self._selected_hit_path = path
            self._selected_hit_pattern = pattern
            if header is None:
                self.hits_detail_text.set(T("primes.header_error", path=path))
                self.hits_load_preview_btn.configure(state="disabled")
                return
            offsets_str = ", ".join(f"+{d}" for d in pattern["offsets"])
            if pattern["record_digits"] is not None:
                record_line = T("const.record_known", digits=pattern['record_digits'],
                                 discoverer=pattern['discoverer'], date=pattern['date'])
            else:
                record_line = T("const.record_untracked")
            self.hits_detail_text.set(
                f"{path}\n\n" +
                T("const.header_detail", k=pattern['k'], variant=pattern['id'],
                  offsets=offsets_str, count=f"{header['count']:,}",
                  generated=header['generated_at_iso']) +
                f"\n{record_line}"
            )
            self.hits_load_preview_btn.configure(state="normal" if header["count"] > 0 else "disabled")

        def _reset_hits_preview_state(self):
            self.hits_preview_list.delete(0, "end")
            self._hit_values = None
            self._hit_rows = None
            self._hit_page = 0
            self._hit_total_pages = 1
            self.hits_page_label.set("")
            self.hits_prev_page_btn.configure(state="disabled")
            self.hits_next_page_btn.configure(state="disabled")
            self.hits_load_preview_btn.configure(state="normal" if self._selected_hit_path else "disabled")

        def _hit_row_formatter(self, row):
            """Each row is (value, hit_base, position, offset) -- ONE tuple element, not
            the whole tuple (that used to be a single comma-joined string per row, which
            meant selecting/copying a row always grabbed every number in the tuple at
            once). `value` is what a copy action grabs; the rest is just context."""
            value, hit_base, position, offset = row
            total = len(self._selected_hit_pattern["offsets"])
            if offset == 0:
                return T("const.hit_row_base", value=value, position=position + 1, total=total)
            return T("const.hit_row_offset", value=value, position=position + 1, total=total,
                     offset=offset, hit_base=hit_base)

        def _load_hits_preview(self):
            if not self._selected_hit_path:
                return
            if self._hit_values is None:
                try:
                    self._hit_values = prime_sieve_v1.read_prime_window(self._selected_hit_path)
                except Exception as exc:
                    messagebox.showerror(T("primes.load_preview_failed_title"), str(exc))
                    self._hit_values = None
                    return
                offsets = self._selected_hit_pattern["offsets"]
                self._hit_rows = [(hit_base + offset, hit_base, position, offset)
                                   for hit_base in self._hit_values
                                   for position, offset in enumerate(offsets)]
            self._show_hits_page(0)
            self.hits_load_preview_btn.configure(state="disabled")

        def _show_hits_page(self, page):
            if not self._hit_rows:
                return
            self._hit_page, self._hit_total_pages = _render_page(
                self.hits_preview_list, self._hit_rows, page, PAGE_SIZE, self._hit_row_formatter)
            _update_nav_controls(self.hits_page_label, self._hit_page,
                                  self._hit_total_pages, self.hits_prev_page_btn, self.hits_next_page_btn)

        def _prev_hits_page(self):
            self._show_hits_page(self._hit_page - 1)

        def _next_hits_page(self):
            self._show_hits_page(self._hit_page + 1)

        def _goto_hits_page(self):
            raw = self.hits_goto_entry.get().strip()
            if not raw.isdigit():
                return
            self._show_hits_page(int(raw) - 1)

        def _show_hits_context_menu(self, event):
            index = self.hits_preview_list.nearest(event.y)
            if index >= 0:
                self.hits_preview_list.selection_clear(0, "end")
                self.hits_preview_list.selection_set(index)
            self._hits_context_menu.tk_popup(event.x_root, event.y_root)

        def _copy_selected_hits_value(self):
            sel = self.hits_preview_list.curselection()
            if not sel or not self._hit_rows:
                return
            global_index = self._hit_page * PAGE_SIZE + sel[0]
            if global_index >= len(self._hit_rows):
                return
            self.clipboard_clear()
            self.clipboard_append(str(self._hit_rows[global_index][0]))

        def _select_hits_pattern_in_tree(self, base_exponent, pattern):
            """Same approach as primes tab's _select_primes_file_in_tree(): expand the
            pietro node, select the matching k/variant node, and flush the queued
            <<TreeviewSelect>> event with update() so _on_hits_tree_select runs to
            completion (resetting/populating self._selected_hit_* etc.) before the caller
            proceeds to load+jump the preview."""
            pietro_item = None
            for item in self.hits_tree.get_children(""):
                if self.hits_tree.item(item, "text") == f"10p{base_exponent}":
                    pietro_item = item
                    break
            if pietro_item is None:
                return
            self.hits_tree.item(pietro_item, open=True)
            self._populate_hits_pietro_node(pietro_item)
            # Patterns are nested one level deeper, under a "k={k} (razem: N)" group node
            # (per-k subtotals -- see _populate_hits_pietro_node) --
            # find that k-group first, then the v=id leaf underneath it.
            k_prefix = f"k={pattern['k']}  "
            k_node = None
            for child in self.hits_tree.get_children(pietro_item):
                if self.hits_tree.item(child, "text").startswith(k_prefix):
                    k_node = child
                    break
            if k_node is None:
                return
            self.hits_tree.item(k_node, open=True)
            target_item = None
            label = f"v={pattern['id']}"
            for child in self.hits_tree.get_children(k_node):
                if self.hits_tree.item(child, "text") == label:
                    target_item = child
                    break
            if target_item is None:
                return
            self.hits_tree.see(target_item)
            self.hits_tree.selection_set(target_item)
            self.hits_tree.focus(target_item)
            self.update()

        def _jump_hits_preview_to_row(self, hit_base, position):
            """Locates the flattened row for (hit_base, position) via bisect over the
            sorted starting values (same technique as find_prime_in_floor), then jumps
            the preview to the page/row containing it and selects just that one row --
            i.e. just that one number, not the whole tuple it belongs to."""
            if not self._hit_values or not self._hit_rows or self._selected_hit_pattern is None:
                return
            hit_index = bisect.bisect_left(self._hit_values, hit_base)
            if hit_index >= len(self._hit_values) or self._hit_values[hit_index] != hit_base:
                return
            total_positions = len(self._selected_hit_pattern["offsets"])
            target_index = hit_index * total_positions + position
            if target_index >= len(self._hit_rows):
                return
            page = target_index // PAGE_SIZE
            self._show_hits_page(page)
            self.hits_load_preview_btn.configure(state="disabled")
            local = target_index - self._hit_page * PAGE_SIZE
            self.hits_preview_list.selection_clear(0, "end")
            self.hits_preview_list.selection_set(local)
            self.hits_preview_list.see(local)

        def _on_search_result_activate(self, _event):
            sel = self.search_results_list.curselection()
            if not sel or sel[0] >= len(self._search_results_data):
                return
            data = self._search_results_data[sel[0]]
            self._select_hits_pattern_in_tree(data["base_exponent"], data["pattern"])
            self._load_hits_preview()
            self._jump_hits_preview_to_row(data["hit_base"], data["position"])

        def _search_constellation(self):
            raw = self.hits_search_entry.get().strip()
            if not raw.isdigit():
                messagebox.showerror(T("common.dialog_search_title"), T("common.error_invalid_number"))
                return
            number = int(raw)
            base_exponent = digit_count_floor(number)
            if self._search_busy:
                messagebox.showinfo(T("common.dialog_search_title"), T("common.search_already_running"))
                return
            if base_exponent not in list_pietra(PORTAL_FOLDER):
                # No floor 10p{base_exponent} at all yet -- see _search_prime()'s identical
                # branch for the full reasoning; offering "const" here (not "prime") means
                # the prime window gets generated first, and the re-search that follows
                # (_on_loop_finished()) runs the FULL const search, which can itself go on
                # to offer generating constellation hits too if THAT'S also still missing.
                outcome = self._offer_generate_missing_prime_window("const", base_exponent, number)
                if outcome != "launched":
                    self._show_const_prime_missing_result(base_exponent, number, outcome)
                return

            self.search_results_list.delete(0, "end")
            self._search_results_data = []
            self._start_search_job("const", base_exponent, number)

        def _show_const_prime_missing_result(self, base_exponent, number, outcome):
            """Shared by _search_constellation()'s no-floor branch and
            _on_const_search_result()'s prime_result-is-None branch -- both reach here only
            when _offer_generate_missing_prime_window() did NOT launch a generation run
            ("composite" or "skipped", see that method's own docstring), so there's a
            Constellations-tab result to show right now rather than waiting on a re-search."""
            if outcome == "composite":
                self.hits_detail_text.set(
                    T("const.confirmed_composite_detail", number=number, base_exponent=base_exponent))
            else:
                self.hits_detail_text.set(
                    T("const.not_found_detail", number=number, base_exponent=base_exponent))
            self._reset_hits_preview_state()
            self.hits_load_preview_btn.configure(state="disabled")

        def _on_const_search_result(self, base_exponent, number, prime_result, participation):
            """Main-thread completion handler for a "const" search job -- same UI update
            _search_constellation() used to do synchronously right after calling
            find_prime_in_floor()/find_constellation_participation(), now driven by
            _poll_search_results() once the worker thread hands the (plain-data) results
            back.

            calc_pending/calc_match: when this completion is for a search the
            constellation calculator itself kicked off (self._const_calc_pending set by
            _on_const_calc_search_selected()), and this call is the one that actually
            reaches a final answer (not a "launched a generation run, wait for the
            re-search" detour), the matching pattern's node gets auto-selected in the
            Magazyn tree and the preview jumped straight to this number -- see the tail
            of this method. calc_pending is only ever CLEARED on a genuinely final
            outcome (declined/composite/no-participation/found) so it survives across
            however many generate-then-re-search hops a single calculator search needs;
            comparing against `calc_pending` (the LOCAL copy captured at entry) rather
            than re-reading self._const_calc_pending after clearing it keeps the
            match/pattern lookup valid even after the instance attribute is gone."""
            calc_pending = self._const_calc_pending
            calc_match = (calc_pending is not None
                          and calc_pending["base_exponent"] == base_exponent
                          and calc_pending["number"] == number)

            if prime_result is None:
                outcome = self._offer_generate_missing_prime_window("const", base_exponent, number)
                if outcome != "launched":
                    if calc_match:
                        self._const_calc_pending = None
                    self._show_const_prime_missing_result(base_exponent, number, outcome)
                return

            lines = [T("const.number_line", number=number),
                     T("const.found_in", name=prime_result['name'], base_exponent=base_exponent), ""]
            if not participation:
                # Empty result is genuinely ambiguous -- see
                # _offer_generate_missing_constellation()'s own docstring: no hit FILES at
                # all for this floor means constellation_finder_v1.py simply never ran
                # here, not that this specific number was checked and excluded.
                if (not list_constellation_hits(PORTAL_FOLDER, base_exponent)
                        and self._offer_generate_missing_constellation(base_exponent, number)):
                    return
                if calc_match:
                    self._const_calc_pending = None
                lines.append(T("const.no_participation"))
            else:
                if calc_match:
                    self._const_calc_pending = None
                lines.append(T("const.participation_intro", count=len(participation)))
                for rec in sorted(participation, key=lambda r: (r["pattern"]["k"], r["pattern"]["id"])):
                    pattern = rec["pattern"]
                    pos_1based = rec["position"] + 1
                    total_positions = len(pattern["offsets"])
                    if rec["offset"] == 0:
                        lines.append(T("const.participation_base_detail",
                                        k=pattern['k'], variant=pattern['id'],
                                        pos=pos_1based, total=total_positions))
                        row_text = T("const.row_base", k=pattern['k'], variant=pattern['id'],
                                     pos=pos_1based, total=total_positions)
                    else:
                        lines.append(T("const.participation_offset_detail",
                                        k=pattern['k'], variant=pattern['id'],
                                        pos=pos_1based, total=total_positions,
                                        offset=rec['offset'], base=rec['base']))
                        row_text = T("const.row_offset", k=pattern['k'], variant=pattern['id'],
                                     pos=pos_1based, total=total_positions,
                                     offset=rec['offset'], base=rec['base'])
                    self.search_results_list.insert("end", row_text)
                    self._search_results_data.append({
                        "base_exponent": base_exponent, "pattern": pattern, "position": rec["position"],
                        "hit_base": rec["base"],
                    })
            self.hits_detail_text.set("\n".join(lines))
            self._reset_hits_preview_state()
            self._selected_hit_path = None
            self._selected_hit_pattern = None
            self.hits_load_preview_btn.configure(state="disabled")
            self.status.set(T("const.status_search", number=number, count=len(participation)))

            if calc_match and participation:
                # Jump straight to the SPECIFIC (k, variant) node the calculator computed
                # this number for -- same helpers _on_search_result_activate() uses for a
                # double-clicked result row, just triggered automatically instead of
                # requiring that extra click. If the number happens to ALSO participate in
                # some other pattern (shown in the results list either way), this still
                # lands on the one the user actually asked about.
                match = next(
                    (rec for rec in participation
                     if rec["pattern"]["k"] == calc_pending["pattern"]["k"]
                     and rec["pattern"]["id"] == calc_pending["pattern"]["id"]), None)
                if match is not None:
                    self._select_hits_pattern_in_tree(base_exponent, calc_pending["pattern"])
                    self._load_hits_preview()
                    self._jump_hits_preview_to_row(match["base"], match["position"])

        # --- Research tab: skeleton only (Faza 0) --------------------------------------

        def _build_research_section(self):
            """Same nested-notebook pattern as _build_primes_section() /
            _build_constellations_section() (see either's own docstring for the full
            rationale) -- a new top-level 'Research' tab, positioned between
            Constellations and Generation.

            Sub-tabs are grouped by SHARED QUESTION SHAPE, not by conjecture name (Artur's
            own restructuring, 2026-08-17), so one engine/analysis serves several classical
            conjectures via parameter presets instead of duplicating near-identical code:
              - Square intervals: 'does [a(n), b(n)] contain >=1 prime?' -- Legendre
                ([n^2, (n+1)^2]), Oppermann ([n^2, n^2+n] and [n^2+n, (n+1)^2]), and Brocard
                ([p_n^2, p_(n+1)^2], prime-indexed) are the same question with a different
                boundary formula -- three presets plus a custom formula, ONE tab.
              - Prime-generating polynomials: 'are there infinitely many primes among
                f(n)'s values?' -- Landau's n^2+1 is one instance of this, alongside Euler's
                n^2+n+41 and a custom polynomial (Bunyakovsky conjecture in general).
              - Goldbach: additive representation (strong: n=p+q even; weak: n=p+q+r odd,
                proven) -- genuinely a different question shape, stays its own tab.
              - Gaps: consecutive-prime growth family -- raw gaps PLUS the inequalities that
                are really just different statistics on the same p_n/p_(n+1) sequence
                (Andrica: sqrt(p_(n+1))-sqrt(p_n)<1; Firoozbakht: p_(n+1)^(1/(n+1)) <
                p_n^(1/n); Cramer: gap vs (log p)^2 as a theoretical ceiling) -- selectable
                overlays on ONE tab, not separate tabs.
              - pi(x) approximations: accuracy of li(x)/R(x) against the real count -- a
                measurement-quality question, not a yes/no conjecture check, stays its own
                tab.
            Hardy-Littlewood / twin-prime / Polignac density questions are NOT a sub-tab
            here -- they're the same computation the EXISTING Constellations tab already
            does (pattern hit-counting), so that family becomes a future density-comparison
            VIEW added to Constellations (actual hits vs Hardy-Littlewood asymptotic
            prediction) instead of a duplicate engine here. See this project's own task
            list for that follow-up.

            SKELETON ONLY, deliberately -- per Artur's own instruction (2026-08-17), this
            phase adds the tab structure with NO computational logic behind any of the
            five sub-tabs; each is a placeholder label for now. Logic gets filled in
            incrementally, one sub-tab at a time, in later phases -- see each
            _build_research_*_tab() method below for where that content will go."""
            sub = ttk.Notebook(self.research_tab)
            sub.pack(fill="both", expand=True)
            self.research_sub_notebook = sub
            self.research_squares_tab = ttk.Frame(sub)
            self.research_polynomials_tab = ttk.Frame(sub)
            self.research_goldbach_tab = ttk.Frame(sub)
            self.research_gaps_tab = ttk.Frame(sub)
            self.research_pi_approx_tab = ttk.Frame(sub)
            sub.add(self.research_squares_tab, text=T("tabs.research_squares"))
            sub.add(self.research_polynomials_tab, text=T("tabs.research_polynomials"))
            sub.add(self.research_goldbach_tab, text=T("tabs.research_goldbach"))
            sub.add(self.research_gaps_tab, text=T("tabs.research_gaps"))
            sub.add(self.research_pi_approx_tab, text=T("tabs.research_pi_approx"))
            self._build_research_squares_tab()
            self._build_research_polynomials_tab()
            self._build_research_goldbach_tab()
            self._build_research_gaps_tab()
            self._build_research_pi_approx_tab()

        def _build_research_squares_tab(self):
            """Square-interval explorer (Legendre/Oppermann/Brocard presets + custom
            boundary formula) -- PLACEHOLDER, no logic yet (Faza 0)."""
            ttk.Label(self.research_squares_tab, text=T("research_squares.placeholder"),
                      wraplength=700, justify="left").pack(anchor="nw", padx=12, pady=12)

        def _build_research_polynomials_tab(self):
            """Prime-generating polynomial explorer (Landau n^2+1, Euler n^2+n+41, custom)
            -- PLACEHOLDER, no logic yet (Faza 0)."""
            ttk.Label(self.research_polynomials_tab, text=T("research_polynomials.placeholder"),
                      wraplength=700, justify="left").pack(anchor="nw", padx=12, pady=12)

        def _build_research_goldbach_tab(self):
            """Goldbach structural-window check. The field is labeled "n" (an arbitrary
            integer) -- Pmax is DERIVED as the largest prime <= n (goldbach_window.
            largest_prime_le), matching the paper's own convention that Pmax must itself
            be a genuine prime, without requiring the person to type a prime by hand.
            "Sprawdz okno" checks windowCovered(Pmax) -- every even n in [4, 2*Pmax]
            must be a sum of two primes -- exactly as formalized in Structural.lean /
            "A Structural Sieve for Goldbach's Conjecture" (see primeatlas/
            goldbach_window.py's own header for the full term-by-term correspondence,
            numerically verified there against the paper's own worked examples). The
            checkbox switches between "touch_once" (stop at the first witness per n --
            windowCovered/hasGoldbachRep, the paper's ACTIVE line of proof, coincides
            with buildableFromBase(Pmax, n) on this window) and "all_combinations" (full
            repCount(n) per n -- the paper's counting framing, kept there only for
            comparison since it inherits the parity problem). "Wizualizacja" draws the
            SAME [4, 2*Pmax] window (never a separate cascade step -- see
            goldbach_window.window_rows' own docstring), sourced from the on-disk
            magazyn. Both run on the shared worker thread (own queue.Queue pair + 150ms
            poller, same pattern as _primality_worker_loop/_poll_primality_results)."""
            top = ttk.Frame(self.research_goldbach_tab)
            top.pack(fill="x", padx=6, pady=(10, 4))
            ttk.Label(top, text=T("research_goldbach.field_n")).pack(side="left")
            self.goldbach_n_entry = ttk.Entry(top, width=20)
            self.goldbach_n_entry.pack(side="left", padx=(6, 16))
            self.goldbach_n_entry.insert(0, "1000")

            self.goldbach_touch_once_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(
                top, text=T("research_goldbach.touch_once_checkbox"),
                variable=self.goldbach_touch_once_var).pack(side="left")

            button_row = ttk.Frame(self.research_goldbach_tab)
            button_row.pack(fill="x", padx=6, pady=(0, 8))
            self.goldbach_run_button = ttk.Button(
                button_row, text=T("research_goldbach.run_button"),
                command=self._on_goldbach_run)
            self.goldbach_run_button.pack(side="left")
            self.goldbach_export_button = ttk.Button(
                button_row, text=T("research_goldbach.export_csv_button"),
                command=self._on_goldbach_export_csv, state="disabled")
            self.goldbach_export_button.pack(side="left", padx=(8, 0))
            self.goldbach_visualize_button = ttk.Button(
                button_row, text=T("research_goldbach.visualize_button"),
                command=self._on_goldbach_visualize)
            self.goldbach_visualize_button.pack(side="left", padx=(8, 0))

            ttk.Label(self.research_goldbach_tab, text=T("research_goldbach.viz_hint"),
                      wraplength=760, justify="left", foreground="#555").pack(
                anchor="w", padx=6, pady=(0, 4))

            ttk.Label(self.research_goldbach_tab, text=T("research_goldbach.hint"),
                      wraplength=760, justify="left", foreground="#555").pack(
                anchor="w", padx=6, pady=(0, 8))

            lean_link = ttk.Label(
                self.research_goldbach_tab, text=T("research_goldbach.lean_repo_link"),
                foreground="#1d4ed8", cursor="hand2")
            lean_link.pack(anchor="w", padx=6, pady=(0, 8))
            lean_link.bind("<Button-1>", self._on_goldbach_open_lean_repo)

            self.goldbach_summary_var = tk.StringVar(value="")
            ttk.Label(self.research_goldbach_tab, textvariable=self.goldbach_summary_var,
                      wraplength=760, justify="left").pack(anchor="w", padx=6, pady=(0, 8))

            tree_frame = ttk.Frame(self.research_goldbach_tab)
            tree_frame.pack(fill="both", expand=True, padx=6, pady=(0, 8))
            columns = ("n", "p", "q", "rep_count")
            self.goldbach_results_tree = ttk.Treeview(
                tree_frame, columns=columns, show="headings", height=16)
            self.goldbach_results_tree.heading("n", text=T("research_goldbach.col_n"))
            self.goldbach_results_tree.heading("p", text=T("research_goldbach.col_p"))
            self.goldbach_results_tree.heading("q", text=T("research_goldbach.col_q"))
            self.goldbach_results_tree.heading(
                "rep_count", text=T("research_goldbach.col_rep_count"))
            self.goldbach_results_tree.column("n", width=110, anchor="e")
            self.goldbach_results_tree.column("p", width=110, anchor="e")
            self.goldbach_results_tree.column("q", width=110, anchor="e")
            self.goldbach_results_tree.column("rep_count", width=110, anchor="e")
            gvsb = ttk.Scrollbar(
                tree_frame, orient="vertical", command=self.goldbach_results_tree.yview)
            self.goldbach_results_tree.configure(yscrollcommand=gvsb.set)
            self.goldbach_results_tree.pack(side="left", fill="both", expand=True)
            gvsb.pack(side="right", fill="y")
            self.goldbach_results_tree.bind(
                "<Double-1>", self._on_goldbach_row_double_click)

            self._goldbach_last_result = None

        def _on_goldbach_open_lean_repo(self, _event=None):
            """Opens GOLDBACH_LEAN_REPO_URL in the system's default browser -- the only
            external link in this tab, so a plain webbrowser.open() (no confirmation
            dialog) is fine; it's a read-only navigation, not an action with side
            effects on the user's own accounts or data."""
            webbrowser.open(GOLDBACH_LEAN_REPO_URL)

        def _goldbach_parse_n_from(self, entry):
            """Parses an "n" field via _eval_quick_number (so expressions like 10**4
            work here too, same as the primesieve calculator's and Testy pierwszosci's
            fields), requiring an integer >= 2 (so a largest-prime-<=n exists to derive
            Pmax from -- see goldbach_window.largest_prime_le's own docstring). Takes
            the Entry widget explicitly so both the main tab's field and the
            Wizualizacja window's OWN field (see _goldbach_ensure_viz_window) share one
            validation path."""
            n = _eval_quick_number(entry.get())
            if n is None or n < 2:
                raise ValueError(T("research_goldbach.error_n_invalid"))
            return n

        def _goldbach_parse_n(self):
            return self._goldbach_parse_n_from(self.goldbach_n_entry)

        def _on_goldbach_run(self):
            if self._goldbach_busy:
                return
            try:
                n = self._goldbach_parse_n()
            except ValueError as e:
                messagebox.showerror(T("research_goldbach.error_dialog_title"), str(e))
                return
            mode = "touch_once" if self.goldbach_touch_once_var.get() else "all_combinations"
            self._goldbach_set_busy(True)
            self._goldbach_work_queue.put({"op": "window", "n": n, "mode": mode})

        def _on_goldbach_visualize(self):
            """"Wizualizacja" button -- derives Pmax = largest prime <= n (starting from
            the SAME n as the "Sprawdz okno" field) and draws the window Lean's
            additiveSelfContained_of_hasGoldbachRep proves unconditionally
            (goldbach_window.both_base_window_rows -- see that module's own
            docstring), sourcing is_prime from the on-disk magazyn
            (read_is_prime_from_storage) rather than a fresh sieve. Opens (or reuses,
            if already open) a Toplevel with its OWN od/do range + check button, so
            different n values can be explored there directly without bouncing back to
            this tab each time (see _goldbach_ensure_viz_window). "od" is left at
            whatever the Toplevel's own field already holds (its own default is 4,
            set once at window creation) -- only "do" is overwritten from this tab's
            n, matching how it always worked before the od/do merge (see
            _goldbach_queue_viz's own docstring for why od/do are no longer
            optional)."""
            try:
                n = self._goldbach_parse_n()
            except ValueError as e:
                messagebox.showerror(T("research_goldbach.error_dialog_title"), str(e))
                return
            win = self._goldbach_ensure_viz_window()
            self.goldbach_viz_n_entry.delete(0, "end")
            self.goldbach_viz_n_entry.insert(0, str(n))
            win.deiconify()
            win.lift()
            self._goldbach_queue_viz(n)

        def _on_goldbach_viz_refresh(self):
            """The Wizualizacja Toplevel's OWN "Sprawdz okno" button -- reads "do"
            from ITS OWN field (self.goldbach_viz_n_entry, still validated via
            _goldbach_parse_n_from -- "do" plays exactly the role the old standalone
            "n" field used to), not the main tab's, so the window is self-sufficient
            once open. "od" is read/validated inside _goldbach_queue_viz itself
            (shared with the row Prev/Next/goto handlers, which also need it re-
            checked on every call -- see that method's own docstring)."""
            if self._goldbach_viz_win is None or not self._goldbach_viz_win.winfo_exists():
                return
            try:
                n = self._goldbach_parse_n_from(self.goldbach_viz_n_entry)
            except ValueError as e:
                messagebox.showerror(T("research_goldbach.error_dialog_title"), str(e))
                return
            self._goldbach_queue_viz(n)

        def _goldbach_queue_viz(self, n, reset_page=True):
            """Queues a "viz" worker job for the range [od, n] -- "n" here is the
            SAME value the "do" field holds, i.e. it plays two roles at once: it's
            what Pmax is derived from (largest prime <= n, exactly like the old
            standalone "n" field), AND it's the scan's own upper bound. reset_page=
            True (the default, used by a fresh "Sprawdz okno" click from either the
            main tab or the Wizualizacja window's own button) starts back at
            row/chip page 0, since a different n means a different window and a
            different old base entirely. reset_page=False (used by the row
            Prev/Next handlers below) keeps whatever self._goldbach_viz_row_page was
            already set to by the caller.

            "od" is read fresh from goldbach_viz_range_from_entry every call (not
            cached, via getattr since that Entry only exists once the Wizualizacja
            Toplevel has actually been built) -- Artur, 2026-08-17: an earlier
            version treated od/do as an "optional" pair (blank = full window), which
            looked like two independent ranges once a standalone "n" field ALSO sat
            above it ("ja chyba nie umiem uzywac zakresowosci"). Now there is only
            one range: od defaults to 4 (not blank) and is validated here on every
            call (>=4, and <= n-2 so at least one even number is actually in
            range) -- an invalid od blocks the job with a clear error instead of
            silently clamping into something the person didn't ask for."""
            if self._goldbach_busy:
                return
            from_entry = getattr(self, "goldbach_viz_range_from_entry", None)
            od_raw = from_entry.get().strip() if from_entry is not None else ""
            n_min = _eval_quick_number(od_raw) if od_raw else 4
            if n_min is None or n_min < 4:
                messagebox.showerror(
                    T("research_goldbach.error_dialog_title"),
                    T("research_goldbach.error_viz_range_from_invalid"))
                return
            if n_min > n - 2:
                messagebox.showerror(
                    T("research_goldbach.error_dialog_title"),
                    T("research_goldbach.error_viz_range_from_too_high", do=f"{n:,}"))
                return
            if reset_page:
                self._goldbach_viz_row_page = 0
                self._goldbach_viz_chip_page = 0
            self._goldbach_viz_current_n = n
            self._goldbach_set_busy(True)
            self._goldbach_work_queue.put({
                "op": "viz", "n": n, "row_page": self._goldbach_viz_row_page,
                "n_min": n_min, "n_max": n,
            })

        def _on_goldbach_viz_row_prev(self):
            """Sums-grid "Poprzednia" -- steps back one PAGE of decomposition rows
            (GOLDBACH_CASCADE_ROW_CAP per page). Needs a fresh worker call (see
            _goldbach_queue_viz's own docstring) since only one page's rows are ever
            held in memory at a time."""
            if self._goldbach_busy or self._goldbach_viz_current_n is None:
                return
            if self._goldbach_viz_row_page > 0:
                self._goldbach_viz_row_page -= 1
                self._goldbach_queue_viz(self._goldbach_viz_current_n, reset_page=False)

        def _on_goldbach_viz_row_next(self):
            """Sums-grid "Nastepna" -- see _on_goldbach_viz_row_prev. The Next button is
            disabled once goldbach_window_rows() reports rows_truncated=False for the
            current page (see _goldbach_show_window_visualization), so this doesn't
            need its own upper-bound check."""
            if self._goldbach_busy or self._goldbach_viz_current_n is None:
                return
            self._goldbach_viz_row_page += 1
            self._goldbach_queue_viz(self._goldbach_viz_current_n, reset_page=False)

        def _on_goldbach_viz_row_goto(self):
            """Sums-grid "Idz" -- jumps directly to a typed page number instead of
            stepping one page at a time, same as the app's other large-list nav rows
            (see e.g. _goto_floor_page/_goto_benchmark_page). Clamped against the last
            known segment_size (if a result has already been drawn) so a wildly
            out-of-range page number doesn't just come back empty -- an unclamped page
            still WOULD come back correctly empty (row_offset simply exceeds
            segment_size), this just avoids the round-trip and the confusing "page 500
            / 12" label that would otherwise result."""
            if self._goldbach_busy or self._goldbach_viz_current_n is None:
                return
            raw = self.goldbach_viz_row_goto_entry.get().strip()
            if not raw.isdigit():
                return
            target = int(raw) - 1
            if self._goldbach_viz_last_result is not None:
                total_row_pages = max(
                    1, -(-self._goldbach_viz_last_result["segment_size"]
                         // GOLDBACH_CASCADE_ROW_CAP))
                target = max(0, min(target, total_row_pages - 1))
            else:
                target = max(0, target)
            self._goldbach_viz_row_page = target
            self._goldbach_queue_viz(self._goldbach_viz_current_n, reset_page=False)

        def _on_goldbach_viz_chip_prev(self):
            """STARA BAZA "Poprzednia" -- purely client-side: old_base_primes is
            already fully present in the last worker result, so paging through it is
            just a redraw with a different slice, no worker round-trip needed."""
            if self._goldbach_viz_chip_page > 0:
                self._goldbach_viz_chip_page -= 1
                if self._goldbach_viz_last_result is not None:
                    self._goldbach_show_window_visualization(self._goldbach_viz_last_result)

        def _on_goldbach_viz_chip_next(self):
            """STARA BAZA "Nastepna" -- see _on_goldbach_viz_chip_prev. Clamped against
            the true page count inside _goldbach_show_window_visualization, so an extra
            click past the end is harmless (the Next button is also disabled there)."""
            self._goldbach_viz_chip_page += 1
            if self._goldbach_viz_last_result is not None:
                self._goldbach_show_window_visualization(self._goldbach_viz_last_result)

        def _on_goldbach_viz_chip_goto(self):
            """STARA BAZA "Idz" -- pure client-side like chip prev/next, so this just
            sets the page and redraws; _goldbach_show_window_visualization clamps it
            against the true page count itself (same as it already does for chip
            prev/next going past either end)."""
            raw = self.goldbach_viz_chip_goto_entry.get().strip()
            if not raw.isdigit():
                return
            self._goldbach_viz_chip_page = max(0, int(raw) - 1)
            if self._goldbach_viz_last_result is not None:
                self._goldbach_show_window_visualization(self._goldbach_viz_last_result)

        def _on_goldbach_viz_decompose(self):
            """"Pokaz wszystkie rozklady" -- reads a target n from the Wizualizacja
            window's own decompose field and exhaustively scans EVERY prime pair
            summing to it (goldbach_all_decompositions), flagged against the Pmax of
            the window currently displayed above (self._goldbach_viz_last_result).
            Needs a window to already be checked (for its Pmax) -- unlike the main n
            field, this one is not restricted to n's inside [4, 2*Pmax], since the
            question ("does n need a prime outside Pmax's base") makes sense for any
            even n Artur wants to probe, not just ones already in the current window."""
            if self._goldbach_busy:
                return
            if self._goldbach_viz_last_result is None:
                messagebox.showerror(
                    T("research_goldbach.error_dialog_title"),
                    T("research_goldbach.error_decompose_no_window"))
                return
            try:
                target_n = self._goldbach_parse_n_from(self.goldbach_viz_decompose_entry)
            except ValueError as e:
                messagebox.showerror(T("research_goldbach.error_dialog_title"), str(e))
                return
            if target_n < 4 or target_n % 2 != 0:
                messagebox.showerror(
                    T("research_goldbach.error_dialog_title"),
                    T("research_goldbach.error_decompose_must_be_even"))
                return
            self._goldbach_decompose_current_n = target_n
            self._goldbach_decompose_current_pmax = self._goldbach_viz_last_result["pmax"]
            self._goldbach_decompose_page = 0
            self._goldbach_queue_decompose_page()

        def _goldbach_queue_decompose_page(self):
            """Issues a "decompose" worker job for self._goldbach_decompose_page of
            self._goldbach_decompose_current_n against self._goldbach_decompose_
            current_pmax -- shared by the initial "Pokaz wszystkie rozklady" click and
            the detail window's own Prev/Next/goto handlers, so they all re-request the
            SAME target n/pmax and only the page differs."""
            self._goldbach_set_busy(True)
            self._goldbach_work_queue.put({
                "op": "decompose", "n": self._goldbach_decompose_current_n,
                "pmax": self._goldbach_decompose_current_pmax,
                "page": self._goldbach_decompose_page,
            })

        def _on_goldbach_decompose_prev(self):
            if self._goldbach_busy or self._goldbach_decompose_current_n is None:
                return
            if self._goldbach_decompose_page > 0:
                self._goldbach_decompose_page -= 1
                self._goldbach_queue_decompose_page()

        def _on_goldbach_decompose_next(self):
            """Next button is disabled once the last drawn result's own "truncated" is
            False (see _goldbach_show_decomposition_detail), so no upper-bound check
            needed here -- same convention as the sums-grid row nav."""
            if self._goldbach_busy or self._goldbach_decompose_current_n is None:
                return
            self._goldbach_decompose_page += 1
            self._goldbach_queue_decompose_page()

        def _on_goldbach_decompose_goto(self):
            if self._goldbach_busy or self._goldbach_decompose_current_n is None:
                return
            raw = self.goldbach_decompose_goto_entry.get().strip()
            if not raw.isdigit():
                return
            target = int(raw) - 1
            if self._goldbach_decompose_last_result is not None:
                total_pages = max(1, -(
                    -self._goldbach_decompose_last_result["count"]
                    // GOLDBACH_DECOMPOSE_ROW_CAP))
                target = max(0, min(target, total_pages - 1))
            else:
                target = max(0, target)
            self._goldbach_decompose_page = target
            self._goldbach_queue_decompose_page()

        def _goldbach_ensure_decompose_window(self):
            """Lazy-create-and-reuse Toplevel for the decomposition detail list, same
            pattern as _goldbach_ensure_viz_window (one persistent window redrawn in
            place, not a new Toplevel piling up per click)."""
            if (self._goldbach_decompose_win is not None
                    and self._goldbach_decompose_win.winfo_exists()):
                return self._goldbach_decompose_win

            win = tk.Toplevel(self)

            def _on_close():
                win.destroy()
                self._goldbach_decompose_win = None

            win.protocol("WM_DELETE_WINDOW", _on_close)

            self.goldbach_decompose_verdict_var = tk.StringVar(value="")
            ttk.Label(win, textvariable=self.goldbach_decompose_verdict_var,
                      wraplength=520, justify="left", font=("TkDefaultFont", 10, "bold"),
                      padding=(10, 10, 10, 4)).pack(anchor="w")

            self.goldbach_decompose_count_var = tk.StringVar(value="")
            ttk.Label(win, textvariable=self.goldbach_decompose_count_var,
                      padding=(10, 0, 10, 2)).pack(anchor="w")

            # Prev/label/Next/goto -- same layout as the Wizualizacja's own row_nav,
            # needed here for the same reason: a large n can have tens of thousands of
            # pairs (Artur's own n~=9999992 screenshot: 53364), and the old silent
            # "(showing first 300 of 53364)" note with no way to see the rest was
            # exactly the gap Artur flagged.
            decompose_nav = ttk.Frame(win, padding=(10, 0, 10, 4))
            decompose_nav.pack(fill="x")
            self.goldbach_decompose_prev_btn = ttk.Button(
                decompose_nav, text=T("common.prev_page"),
                command=self._on_goldbach_decompose_prev, state="disabled")
            self.goldbach_decompose_prev_btn.pack(side="left")
            self.goldbach_decompose_page_label = tk.StringVar(value="")
            ttk.Label(decompose_nav, textvariable=self.goldbach_decompose_page_label,
                      width=14, anchor="center").pack(side="left", padx=(4, 4))
            self.goldbach_decompose_next_btn = ttk.Button(
                decompose_nav, text=T("common.next_page"),
                command=self._on_goldbach_decompose_next, state="disabled")
            self.goldbach_decompose_next_btn.pack(side="left")
            self.goldbach_decompose_goto_entry = ttk.Entry(decompose_nav, width=6)
            self.goldbach_decompose_goto_entry.pack(side="left", padx=(12, 0))
            self.goldbach_decompose_goto_entry.bind(
                "<Return>", lambda _e: self._on_goldbach_decompose_goto())
            ttk.Button(decompose_nav, text=T("common.goto"),
                       command=self._on_goldbach_decompose_goto).pack(
                side="left", padx=(4, 0))

            tree_frame = ttk.Frame(win, padding=(10, 0, 10, 4))
            tree_frame.pack(fill="both", expand=True)
            columns = ("p", "q", "old_base")
            tree = ttk.Treeview(
                tree_frame, columns=columns, show="headings", height=16)
            tree.heading("p", text=T("research_goldbach.decompose_col_p"))
            tree.heading("q", text=T("research_goldbach.decompose_col_q"))
            tree.heading("old_base", text=T("research_goldbach.decompose_col_base"))
            tree.column("p", width=100, anchor="e")
            tree.column("q", width=100, anchor="e")
            tree.column("old_base", width=140, anchor="center")
            tree.tag_configure("new", foreground="#a06a00")
            scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=scroll.set)
            tree.pack(side="left", fill="both", expand=True)
            scroll.pack(side="left", fill="y")
            self.goldbach_decompose_tree = tree

            self._goldbach_decompose_win = win
            return win

        def _goldbach_show_decomposition_detail(self, result):
            """Renders one goldbach_all_decompositions() result into the detail
            Toplevel: every (p, q) pair for the requested n ON THIS PAGE, plus a
            headline verdict on buildableFromBase(Pmax, n) [Constructive.lean] --
            computed over the whole scan regardless of which page is showing. Per
            Artur's correction ("popraw tak by było zgodne z leanem"): Lean's own
            buildableFromBase only ever bounds p, never q (see goldbach_window.py's
            module docstring) -- so the per-row "Skad q" column is PURELY
            INFORMATIONAL (which prime was already known before this window vs first
            appears inside it), never a pass/fail signal. The verdict is about p_in_base
            across the whole list, not about any individual q. Page nav (Prev/Next/
            goto) mirrors the sums-grid row nav in the main diagram."""
            win = self._goldbach_ensure_decompose_window()
            win.title(T("research_goldbach.decompose_window_title", n=result["n"]))
            win.deiconify()
            win.lift()

            self._goldbach_decompose_last_result = result

            pmax = result["pmax"]
            if result["buildable_from_base"]:
                self.goldbach_decompose_verdict_var.set(
                    T("research_goldbach.decompose_verdict_yes",
                      pmax=pmax, count=result["count"]))
            else:
                self.goldbach_decompose_verdict_var.set(
                    T("research_goldbach.decompose_verdict_no",
                      pmax=pmax, count=result["count"]))
            self.goldbach_decompose_count_var.set(
                T("research_goldbach.decompose_count", count=result["count"]))

            tree = self.goldbach_decompose_tree
            tree.delete(*tree.get_children())
            old_label = T("research_goldbach.decompose_q_old")
            new_label = T("research_goldbach.decompose_q_new")
            for pair in result["decompositions"]:
                q_old = pair["q_in_base"]
                tree.insert(
                    "", "end", values=(pair["p"], pair["q"],
                                        old_label if q_old else new_label),
                    tags=() if q_old else ("new",))

            page = result.get("page", 0)
            total_pages = max(1, -(-result["count"] // GOLDBACH_DECOMPOSE_ROW_CAP))
            _update_nav_controls(
                self.goldbach_decompose_page_label, page, total_pages,
                self.goldbach_decompose_prev_btn, self.goldbach_decompose_next_btn)

        def _goldbach_ensure_viz_window(self):
            """Creates the Wizualizacja Toplevel the first time it's needed, or returns
            the existing one if it's still open -- so repeated clicks (from this tab's
            button, or from the window's own check button) redraw ONE persistent
            window instead of piling up a new Toplevel per click. Layout: a top row
            with its own od/do range fields + check button + status label, then a
            Canvas below that _goldbach_show_window_visualization redraws in place
            (clear + redraw, resizing the canvas to fit) rather than rebuilding from
            scratch."""
            if self._goldbach_viz_win is not None and self._goldbach_viz_win.winfo_exists():
                return self._goldbach_viz_win

            win = tk.Toplevel(self)
            win.title(T("research_goldbach.viz_window_title_generic"))

            def _on_close():
                win.destroy()
                self._goldbach_viz_win = None

            win.protocol("WM_DELETE_WINDOW", _on_close)

            # Single od/do row -- Artur, 2026-08-17: an earlier version had a
            # standalone "n" field here PLUS a separate "optional" od/do range
            # below it, which looked like two independent ways to pick a range
            # ("ja chyba nie umiem uzywac zakresowosci") when "do" was always
            # effectively n's own role anyway (Pmax is derived from whatever's
            # typed as the upper bound, exactly like the old n field did) --
            # merged into one row so there's only one range to reason about, not
            # two overlapping ones. "do" plays n's old role unchanged (still
            # goldbach_viz_n_entry / _goldbach_parse_n_from, still what
            # determines Pmax); "od" defaults to 4 (not blank) and is validated
            # against "do" in _goldbach_queue_viz (>=4, and <= do-2 so at least
            # one even n exists in the range) so the button always operates on a
            # concrete, well-formed range -- no more separate "leave it blank for
            # the full window" mode to explain.
            top = ttk.Frame(win)
            top.pack(fill="x", padx=10, pady=(10, 4))
            ttk.Label(top, text=T("research_goldbach.viz_range_label")).pack(side="left")
            self.goldbach_viz_range_from_entry = ttk.Entry(top, width=16)
            self.goldbach_viz_range_from_entry.pack(side="left", padx=(6, 12))
            self.goldbach_viz_range_from_entry.insert(0, "4")
            self.goldbach_viz_range_from_entry.bind(
                "<Return>", lambda _e: self._on_goldbach_viz_refresh())
            ttk.Label(top, text=T("research_goldbach.viz_range_to_label")).pack(side="left")
            self.goldbach_viz_n_entry = ttk.Entry(top, width=16)
            self.goldbach_viz_n_entry.pack(side="left", padx=(6, 12))
            self.goldbach_viz_n_entry.insert(0, self.goldbach_n_entry.get() or "1000")
            self.goldbach_viz_n_entry.bind(
                "<Return>", lambda _e: self._on_goldbach_viz_refresh())
            self.goldbach_viz_check_button = ttk.Button(
                top, text=T("research_goldbach.run_button"),
                command=self._on_goldbach_viz_refresh)
            self.goldbach_viz_check_button.pack(side="left")
            ttk.Label(win, text=T("research_goldbach.viz_range_hint"),
                      wraplength=780, justify="left", foreground="#777").pack(
                anchor="w", padx=10, pady=(0, 6))

            self.goldbach_viz_status_var = tk.StringVar(value="")
            ttk.Label(win, textvariable=self.goldbach_viz_status_var,
                      wraplength=780, justify="left", foreground="#555").pack(
                anchor="w", padx=10, pady=(0, 6))

            # Own Progressbar, separate from the shared self.totals_progress in the
            # MAIN window -- Artur, 2026-08-17: "progress br trzeba dodać też do
            # samego okna wizualizacji bo w nim często jestem w trybie
            # pełnoekranowym" -- the shared bottom bar is invisible while this
            # Toplevel is maximized/fullscreen over it. Mirrored in lockstep with
            # totals_progress by _goldbach_viz_progress_set (see its own
            # docstring), called from every place that already updates
            # totals_progress (_goldbach_set_busy, the "progress" queue tick in
            # _poll_goldbach_results) so the two never drift out of sync.
            self.goldbach_viz_progress = ttk.Progressbar(
                win, mode="determinate", maximum=1, value=0)
            self.goldbach_viz_progress.pack(fill="x", padx=10, pady=(0, 6))

            # "Rozloz liczbe" -- Artur's request after noticing that the smallest-
            # witness search (_smallest_witness / window_rows) can land on a pair
            # whose q > Pmax even when an old-base-only pair (both p, q <= Pmax) exists
            # elsewhere in the full combination list -- e.g. n=1012 against Pmax=997:
            # the smallest witness is 3+1009 (1009 is "new"), but 29+983 also works and
            # stays entirely inside the old base. This exhaustively scans ALL pairs for
            # one specific n (see goldbach_all_decompositions) against the Pmax of the
            # window currently shown above, instead of only the single smallest one.
            decompose_row = ttk.Frame(win)
            decompose_row.pack(fill="x", padx=10, pady=(0, 6))
            ttk.Label(decompose_row, text=T("research_goldbach.viz_decompose_label")).pack(
                side="left")
            self.goldbach_viz_decompose_entry = ttk.Entry(decompose_row, width=16)
            self.goldbach_viz_decompose_entry.pack(side="left", padx=(6, 12))
            self.goldbach_viz_decompose_entry.bind(
                "<Return>", lambda _e: self._on_goldbach_viz_decompose())
            self.goldbach_viz_decompose_button = ttk.Button(
                decompose_row, text=T("research_goldbach.viz_decompose_button"),
                command=self._on_goldbach_viz_decompose)
            self.goldbach_viz_decompose_button.pack(side="left")

            # Two INDEPENDENT navigation rows, per Artur's request for the same kind
            # of Prev/Next paging used elsewhere for large lists (Primes tab preview,
            # benchmark log -- see _update_nav_controls). STARA BAZA pages through
            # old_base_primes client-side; the sums grid pages through the window's
            # decomposition rows via a fresh backend call each time (see
            # _goldbach_queue_viz's docstring for why they differ).
            chip_nav = ttk.Frame(win)
            chip_nav.pack(fill="x", padx=10, pady=(0, 2))
            ttk.Label(chip_nav, text=T("research_goldbach.viz_nav_chips_label")).pack(
                side="left")
            self.goldbach_viz_chip_prev_btn = ttk.Button(
                chip_nav, text=T("common.prev_page"),
                command=self._on_goldbach_viz_chip_prev, state="disabled")
            self.goldbach_viz_chip_prev_btn.pack(side="left", padx=(6, 4))
            self.goldbach_viz_chip_page_label = tk.StringVar(value="")
            ttk.Label(chip_nav, textvariable=self.goldbach_viz_chip_page_label,
                      width=14, anchor="center").pack(side="left")
            self.goldbach_viz_chip_next_btn = ttk.Button(
                chip_nav, text=T("common.next_page"),
                command=self._on_goldbach_viz_chip_next, state="disabled")
            self.goldbach_viz_chip_next_btn.pack(side="left", padx=(4, 0))
            self.goldbach_viz_chip_goto_entry = ttk.Entry(chip_nav, width=6)
            self.goldbach_viz_chip_goto_entry.pack(side="left", padx=(12, 0))
            self.goldbach_viz_chip_goto_entry.bind(
                "<Return>", lambda _e: self._on_goldbach_viz_chip_goto())
            ttk.Button(chip_nav, text=T("common.goto"),
                       command=self._on_goldbach_viz_chip_goto).pack(side="left", padx=(4, 0))

            row_nav = ttk.Frame(win)
            row_nav.pack(fill="x", padx=10, pady=(0, 6))
            ttk.Label(row_nav, text=T("research_goldbach.viz_nav_rows_label")).pack(
                side="left")
            self.goldbach_viz_row_prev_btn = ttk.Button(
                row_nav, text=T("common.prev_page"),
                command=self._on_goldbach_viz_row_prev, state="disabled")
            self.goldbach_viz_row_prev_btn.pack(side="left", padx=(6, 4))
            self.goldbach_viz_row_page_label = tk.StringVar(value="")
            ttk.Label(row_nav, textvariable=self.goldbach_viz_row_page_label,
                      width=14, anchor="center").pack(side="left")
            self.goldbach_viz_row_next_btn = ttk.Button(
                row_nav, text=T("common.next_page"),
                command=self._on_goldbach_viz_row_next, state="disabled")
            self.goldbach_viz_row_next_btn.pack(side="left", padx=(4, 0))
            self.goldbach_viz_row_goto_entry = ttk.Entry(row_nav, width=6)
            self.goldbach_viz_row_goto_entry.pack(side="left", padx=(12, 0))
            self.goldbach_viz_row_goto_entry.bind(
                "<Return>", lambda _e: self._on_goldbach_viz_row_goto())
            ttk.Button(row_nav, text=T("common.goto"),
                       command=self._on_goldbach_viz_row_goto).pack(side="left", padx=(4, 0))

            # NOT fill="both"/expand=True here: an earlier version packed the canvas to
            # fill the whole Toplevel, which meant the Canvas widget stretched to
            # whatever size the window happened to be (its actual drawn content still
            # only covering its own configured width/height), leaving a big blank area
            # to the right and pinning everything to the top-left -- exactly the bug
            # Artur reported ("mamy tyle wolnej przestrzeni a wszystko z lewej
            # strony"). Packing it at its natural size instead means the Toplevel
            # itself auto-sizes to the canvas's actual content on every redraw (see
            # the win.geometry("") reset in _goldbach_show_window_visualization).
            canvas_frame = ttk.Frame(win)
            canvas_frame.pack(padx=10, pady=(0, 10))
            self.goldbach_viz_canvas = tk.Canvas(
                canvas_frame, width=820, height=120, background="white",
                highlightthickness=0)
            self.goldbach_viz_canvas.pack()

            self._goldbach_viz_win = win
            return win

        def _goldbach_widget_configure(self, attr_name, **kwargs):
            """configure() an optional, possibly-stale widget attribute without
            blowing up -- `hasattr(self, attr_name)` alone isn't enough here: closing
            the Wizualizacja or decompose Toplevel (see their own _on_close handlers)
            destroys every Tk widget inside it, but does NOT clear out the Python
            attribute still pointing at that now-dead widget (only the *_win attribute
            itself gets reset to None). Configuring a destroyed widget raises
            tk.TclError -- caught and ignored here, since "the window this button
            lived in is gone" is a perfectly normal thing to happen mid-flight (a
            worker job queued before the window was closed, whose result now arrives
            after). Without this guard, that TclError propagates out of whichever
            caller stopped it from reaching the code that resets self._goldbach_busy
            back to False, permanently disabling every Goldbach button on the tab --
            exactly the bug Artur reported (open+close "Pokaz wszystkie rozklady",
            button stays greyed out, sums-grid "Nastepna" too)."""
            widget = getattr(self, attr_name, None)
            if widget is None:
                return
            try:
                widget.configure(**kwargs)
            except tk.TclError:
                pass

        def _goldbach_set_busy(self, busy):
            self._goldbach_busy = busy
            state = "disabled" if busy else "normal"
            self.goldbach_run_button.configure(state=state)
            self._goldbach_widget_configure("goldbach_viz_check_button", state=state)
            self._goldbach_widget_configure("goldbach_viz_decompose_button", state=state)
            # Only force-DISABLE the row nav buttons here -- their correct enabled
            # state at the bounds (first/last page) is recalculated by
            # _update_nav_controls once a fresh result is drawn, so re-enabling them
            # unconditionally here would briefly un-disable Prev on page 0. Chip nav
            # buttons aren't gated by busy at all -- paging them is pure client-side
            # redraw, no worker round-trip (see _on_goldbach_viz_chip_prev/_next).
            if busy:
                self._goldbach_widget_configure("goldbach_viz_row_prev_btn", state="disabled")
                self._goldbach_widget_configure("goldbach_viz_row_next_btn", state="disabled")
                self._goldbach_widget_configure("goldbach_decompose_prev_btn", state="disabled")
                self._goldbach_widget_configure("goldbach_decompose_next_btn", state="disabled")
            if busy:
                self.totals_progress.stop()
                self.totals_progress.configure(mode="indeterminate")
                self.totals_progress.start(80)
                self._goldbach_viz_progress_set(indeterminate=True)
                self.status.set(T("research_goldbach.status_computing"))
            else:
                self.totals_progress.stop()
                self.totals_progress.configure(mode="determinate", maximum=1, value=0)
                self._goldbach_viz_progress_set(value=0)

        def _goldbach_refresh_nav_buttons(self):
            """Restores BOTH the Wizualizacja sums-grid Prev/Next and the decompose
            window's own Prev/Next from their last-drawn results. Needed because
            _goldbach_set_busy(True) force-disables ALL FOUR of these buttons for
            ANY Goldbach job (window/viz/decompose share one busy flag and one
            worker thread), but each pair's correct re-enabled state is normally
            only recalculated by its OWN show_* function's _update_nav_controls
            call -- _goldbach_show_decomposition_detail never touches the
            sums-grid buttons, and _goldbach_show_window_visualization never
            touches the decompose buttons. Since only ONE show_* function runs per
            completed job, the OTHER pair was left stuck disabled from the
            busy=True phase forever -- exactly what Artur reported: clicking
            "Pokaz wszystkie rozklady" (a decompose job) leaves the Wizualizacja's
            own "Sumy w oknie" Nastepna button greyed out even though that
            viz result's true last-known page state hasn't changed at all.
            Called unconditionally after every busy=False transition, regardless
            of which op just completed -- each block below is a harmless no-op
            (re-deriving the same state _update_nav_controls would already have
            set) when its own op is the one that just finished."""
            if self._goldbach_viz_last_result is not None:
                result = self._goldbach_viz_last_result
                row_page = result.get("row_page", 0)
                total_row_pages = max(
                    1, -(-result["segment_size"] // GOLDBACH_CASCADE_ROW_CAP))
                try:
                    _update_nav_controls(
                        self.goldbach_viz_row_page_label, row_page, total_row_pages,
                        self.goldbach_viz_row_prev_btn, self.goldbach_viz_row_next_btn)
                except (tk.TclError, AttributeError):
                    pass
            if self._goldbach_decompose_last_result is not None:
                result = self._goldbach_decompose_last_result
                page = result.get("page", 0)
                total_pages = max(
                    1, -(-result["count"] // GOLDBACH_DECOMPOSE_ROW_CAP))
                try:
                    _update_nav_controls(
                        self.goldbach_decompose_page_label, page, total_pages,
                        self.goldbach_decompose_prev_btn, self.goldbach_decompose_next_btn)
                except (tk.TclError, AttributeError):
                    pass

        def _goldbach_worker_loop(self):
            """Own daemon thread -- single-owner reasoning identical to
            _primality_worker_loop's own docstring (self._goldbach_busy blocks new
            requests from the GUI side, so only one job is ever in flight). Three job
            shapes distinguished by "op":

            "window" -- resolves Pmax = largest prime <= n from a FRESH in-process
            sieve up to n, then runs goldbach_window.check_window(Pmax, mode) (which
            sieves again, up to 2*Pmax -- a small amount of duplicate work, traded for
            reusing check_window()'s existing, already-verified contract unchanged).

            "viz" -- resolves Pmax the same way, but from is_prime sourced from the
            on-disk magazyn (read_is_prime_from_storage, up to 2*n -- a safe upper
            bound since Pmax <= n means 2*Pmax <= 2*n), per Artur's explicit
            instruction that Wizualizacja should read from storage rather than
            recompute. Then runs goldbach_window.window_rows(is_prime, Pmax, ...) over
            that SAME array -- both the Pmax resolution and the window check share one
            storage read. job["row_page"] (default 0) selects which PAGE of
            decomposition rows to compute (see GOLDBACH_CASCADE_ROW_CAP and the
            row_offset param it's paired with) -- re-reads storage and re-derives Pmax
            every page turn rather than caching, same cost profile as re-running the
            whole check, which is acceptable since it's already async off the GUI
            thread.

            "decompose" -- job carries an explicit "pmax" (the ALREADY-displayed
            window's Pmax, not re-derived from n, since the target n here is a
            separate probe, not necessarily inside that window). Reads storage up to
            n itself (only need is_prime long enough to index n), then runs
            goldbach_window.all_decompositions(is_prime, n, pmax, cap=...) -- the
            exhaustive "sliding window" scan Artur asked for, answering whether n
            truly needs a prime beyond pmax's old base or whether the smallest-witness
            search (used by "viz") just happened to land on one.

            None of the three ops needs a WSL subprocess."""
            while True:
                job = self._goldbach_work_queue.get()
                op = job["op"]
                n = job["n"]
                try:
                    if op == "window":
                        is_prime_n = goldbach_sieve_is_prime(n)
                        pmax = goldbach_largest_prime_le(is_prime_n, n)
                        if pmax is None:
                            self._goldbach_result_queue.put((
                                op, False, T("research_goldbach.error_no_prime_le_n", n=n)))
                            continue
                        result = goldbach_check_window(pmax, job["mode"])
                        result["n"] = n
                        self._goldbach_result_queue.put((op, True, result))
                    elif op == "decompose":
                        try:
                            is_prime = read_is_prime_from_storage(PORTAL_FOLDER, n)
                        except MissingStorageRangeError as e:
                            self._goldbach_result_queue.put((
                                op, False,
                                {"kind": "storage_missing", "floor": e.floor,
                                 "needed_upto": e.needed_upto,
                                 "message": T("research_goldbach.error_storage_missing",
                                              floor=e.floor, upto=f"{e.needed_upto:,}")}))
                            continue
                        page = job.get("page", 0)
                        result = goldbach_all_decompositions(
                            is_prime, n, job["pmax"], cap=GOLDBACH_DECOMPOSE_ROW_CAP,
                            offset=page * GOLDBACH_DECOMPOSE_ROW_CAP)
                        result["page"] = page
                        self._goldbach_result_queue.put((op, True, result))
                    else:
                        # Wizualizacja's only window: [4, Pmax+GOLDBACH_BOTH_BASE_PMIN],
                        # both p and q required <= Pmax -- exactly what Lean's
                        # additiveSelfContained_of_hasGoldbachRep proves unconditionally
                        # (see goldbach_window.BOTH_BASE_PMIN's own docstring). Only
                        # ever needs storage read up to n+Pmin, not 2*n. Checked BEFORE
                        # the storage read (not after, unlike a plain ValueError from
                        # both_base_window_rows itself) so an oversized n gets a
                        # translated, dedicated error instead of a raw exception string.
                        limit = n + GOLDBACH_BOTH_BASE_PMIN
                        try:
                            is_prime = read_is_prime_from_storage(PORTAL_FOLDER, limit)
                        except MissingStorageRangeError as e:
                            self._goldbach_result_queue.put((
                                op, False,
                                {"kind": "storage_missing", "floor": e.floor,
                                 "needed_upto": e.needed_upto,
                                 "message": T("research_goldbach.error_storage_missing",
                                              floor=e.floor, upto=f"{e.needed_upto:,}")}))
                            continue
                        pmax = goldbach_largest_prime_le(is_prime, n)
                        if pmax is None:
                            self._goldbach_result_queue.put((
                                op, False, T("research_goldbach.error_no_prime_le_n", n=n)))
                            continue
                        if pmax > GOLDBACH_BOTH_BASE_PMAX_CEILING:
                            self._goldbach_result_queue.put((
                                op, False,
                                T("research_goldbach.error_both_base_pmax_too_large",
                                  pmax=f"{pmax:,}",
                                  ceiling=f"{GOLDBACH_BOTH_BASE_PMAX_CEILING:,}")))
                            continue
                        row_page = job.get("row_page", 0)
                        # Progress ticks go through the SAME result queue, tagged
                        # "progress" so _poll_goldbach_results can special-case them
                        # (update the bar, then re-loop for the next queue message)
                        # instead of treating them as a finished job -- see that
                        # method's own handling of op=="progress".
                        result = goldbach_both_base_window_rows(
                            is_prime, pmax, row_cap=GOLDBACH_CASCADE_ROW_CAP,
                            row_offset=row_page * GOLDBACH_CASCADE_ROW_CAP,
                            n_min=job.get("n_min"), n_max=job.get("n_max"),
                            progress_cb=lambda f: self._goldbach_result_queue.put(
                                ("progress", True, f)))
                        result["n"] = n
                        result["row_page"] = row_page
                        self._goldbach_result_queue.put((op, True, result))
                except Exception as e:  # noqa: BLE001 -- surface any unexpected failure
                                         # to the GUI as an error dialog instead of
                                         # silently killing this worker thread
                    self._goldbach_result_queue.put((op, False, str(e)))

        def _poll_goldbach_results(self):
            """Main-thread side -- same 150ms polling cadence as
            _poll_primality_results, runs for the whole lifetime of the window. The
            per-message body is wrapped in its own try/except (Exception, not just
            queue.Empty) so that ONE bad message -- e.g. a result arriving for a
            Toplevel (Wizualizacja or decompose) the user already closed -- can never
            skip the self.after(...) reschedule at the bottom and silently kill
            polling for the rest of the session (see _goldbach_widget_configure's own
            docstring for the specific bug this was covering for)."""
            try:
                while True:
                    op, ok, payload = self._goldbach_result_queue.get_nowait()
                    if op == "progress":
                        # Not a finished job -- one tick of both_base_window_rows'
                        # own progress_cb (see the worker loop's viz branch). Switch
                        # the SHARED bottom bar (self.totals_progress -- same one the
                        # floor-totals scan/Generation tab use) out of the
                        # indeterminate spin _goldbach_set_busy(True) started it in
                        # and into a real fraction; stop() first since an
                        # indeterminate animation still running underneath a
                        # determinate value looks broken (bar visibly jumps once the
                        # animation's next tick fires). Busy state/nav buttons are
                        # untouched -- the job is still running.
                        self.totals_progress.stop()
                        self.totals_progress.configure(
                            mode="determinate", maximum=1, value=payload)
                        self._goldbach_viz_progress_set(value=payload)
                        continue
                    try:
                        self._goldbach_set_busy(False)
                        self._goldbach_refresh_nav_buttons()
                        if not ok:
                            self.status.set(T("research_goldbach.status_error"))
                            if isinstance(payload, dict) and payload.get("kind") == "storage_missing":
                                # Not a generic failure -- read_is_prime_from_storage
                                # found a specific gap (floor/needed_upto). Offer to
                                # fill it instead of just naming it, same "offer to
                                # generate the missing piece" UX search already uses
                                # for prime/constellation lookups (see
                                # _offer_generate_missing_prime_window's docstring).
                                self._goldbach_offer_generate_missing_range(op, payload)
                            else:
                                messagebox.showerror(
                                    T("research_goldbach.error_dialog_title"), payload)
                            continue
                        self.status.set(T("research_goldbach.status_done"))
                        if op == "window":
                            self._goldbach_show_result(payload)
                        elif op == "decompose":
                            self._goldbach_show_decomposition_detail(payload)
                        else:
                            self._goldbach_show_window_visualization(payload)
                    except Exception:  # noqa: BLE001 -- see docstring: never let one
                                        # bad message skip the reschedule below
                        pass
            except queue.Empty:
                pass
            self.after(150, self._poll_goldbach_results)

        def _goldbach_offer_generate_missing_range(self, op, payload):
            """Offers to generate the primes storage a Wizualizacja/decompose job
            just found missing (MissingStorageRangeError, translated into this dict
            by the worker loop's own except MissingStorageRangeError blocks --
            see _goldbach_worker_loop's docstring). Mirrors
            _offer_generate_missing_prime_window()'s askyesno pattern, but launches
            through _quick_gen_plan_literal_range()/_launch_direct_window_range() --
            the SAME path Quick-gen's own Range mode button uses -- instead of always
            forcing the primesieve engine directly the way that helper does: a Goldbach
            gap can span many windows (the whole floor up to needed_upto), not just the one
            window a single prime search needs, so the continuation-based
            orchestrator engine (fills from wherever the floor's storage already
            ends, up to the requested count) is the right fit here, not
            primesieve's "write exactly this one window" contract.

            Records `op` ("viz" or "decompose") into self._pending_goldbach_
            retry_op once a run is actually launched, so _on_loop_finished knows
            WHICH job to re-queue once generation completes -- the two ops read
            their target n from different places (see that method's own
            docstring), so blindly always retrying "viz" would silently drop a
            decompose request that hit this same offer. read_is_prime_from_storage
            only ever reports the FIRST short floor it hits while walking
            0,1,2,... in order, so a range spanning multiple short floors may
            still come back short again after one generation run -- re-queuing
            just repeats this same offer for the next gap rather than trying to
            solve every gap in one shot."""
            floor = payload["floor"]
            needed_upto = payload["needed_upto"]
            if self._loop_runner is not None and self._loop_runner.is_running():
                messagebox.showinfo(T("quick.dialog_title"), T("quick.error_already_running"))
                return
            plan = self._quick_gen_plan_literal_range(10 ** floor, needed_upto + 1)
            if plan.get("error"):
                messagebox.showerror(*plan["error"])
                return
            if plan.get("already"):
                # Shouldn't normally happen (read_is_prime_from_storage's own check
                # just said this floor was short), but if a race/edge case lands
                # here anyway, fall back to the plain error rather than launching a
                # no-op run.
                messagebox.showerror(T("research_goldbach.error_dialog_title"), payload["message"])
                return
            if not messagebox.askyesno(
                    T("common.dialog_search_title"),
                    T("research_goldbach.offer_generate_missing_range",
                      floor=floor, rounded_start=f"{plan['rounded_start']:,}",
                      rounded_end=f"{plan['rounded_end']:,}")):
                return
            self._pending_goldbach_retry_op = op
            self.status.set(T("research_goldbach.status_generating_range", floor=floor))
            self._launch_direct_window_range(
                plan["floor"], plan["target_idx_start"], plan["window_count_per_run"])

        def _goldbach_viz_progress_set(self, indeterminate=False, value=None):
            """Mirrors totals_progress's own state onto the Wizualizacja Toplevel's
            OWN Progressbar (see _goldbach_ensure_viz_window) -- Artur, 2026-08-17:
            the shared bottom bar lives in the MAIN window and is invisible while
            the Toplevel is maximized/fullscreen, which is how this tab is used
            most of the time. Guarded with the same try/except tk.TclError pattern
            _goldbach_widget_configure uses, since the Toplevel may already be
            closed when a queued job's result/progress tick arrives."""
            widget = getattr(self, "goldbach_viz_progress", None)
            if widget is None:
                return
            try:
                widget.stop()
                if indeterminate:
                    widget.configure(mode="indeterminate")
                    widget.start(80)
                else:
                    widget.configure(mode="determinate", maximum=1, value=value or 0)
            except tk.TclError:
                pass

        def _goldbach_show_result(self, result):
            self._goldbach_last_result = result
            self.goldbach_results_tree.delete(*self.goldbach_results_tree.get_children())
            rows = result["rows"]
            truncated = len(rows) > PAGE_SIZE
            for row in rows[:PAGE_SIZE]:
                p = row["p"] if row["p"] is not None else T("research_goldbach.no_witness")
                q = row["q"] if row["q"] is not None else ""
                rc = row["rep_count"] if row["rep_count"] is not None else "-"
                self.goldbach_results_tree.insert("", "end", values=(row["n"], p, q, rc))
            if result["covered"]:
                summary = T(
                    "research_goldbach.summary_covered", n=result["n"], pmax=result["pmax"],
                    n_checked=result["n_checked"],
                    window_max=result["window_max"], elapsed=f"{result['elapsed']:.3f}")
            else:
                summary = T(
                    "research_goldbach.summary_void", n=result["n"], pmax=result["pmax"],
                    counterexamples=", ".join(str(x) for x in result["counterexamples"]),
                    window_max=result["window_max"], elapsed=f"{result['elapsed']:.3f}")
            if truncated:
                summary += " " + T(
                    "research_goldbach.summary_truncated", shown=PAGE_SIZE, total=len(rows))
            self.goldbach_summary_var.set(summary)
            self.goldbach_export_button.configure(state="normal")

        def _on_goldbach_row_double_click(self, event):
            """Drill-down for "all_combinations" mode -- shows the FULL deduplicated
            witness-pair list for the double-clicked n (the results table only shows
            the smallest pair + count, same drill-down spirit as the Constellations ->
            Tabela rekordow tab's hit-list dialog). No-op in "touch_once" mode (pairs
            is None there by design -- see goldbach_window.py's own docstring)."""
            sel = self.goldbach_results_tree.selection()
            if not sel or not self._goldbach_last_result:
                return
            n = self.goldbach_results_tree.item(sel[0])["values"][0]
            row = next(
                (r for r in self._goldbach_last_result["rows"] if r["n"] == n), None)
            if row is None or row["pairs"] is None:
                return
            pairs_text = "\n".join(f"{p} + {q} = {n}" for p, q in row["pairs"])
            messagebox.showinfo(
                T("research_goldbach.pairs_dialog_title", n=n),
                pairs_text or T("research_goldbach.no_witness"))

        def _on_goldbach_export_csv(self):
            if not self._goldbach_last_result:
                return
            result = self._goldbach_last_result
            default_name = (
                f"goldbach_window_n{result['n']}_pmax{result['pmax']}_{result['mode']}_"
                f"{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
            path = filedialog.asksaveasfilename(
                title=T("research_goldbach.export_csv_button"),
                initialdir=PORTAL_FOLDER,
                initialfile=default_name,
                defaultextension=".csv",
                filetypes=[("CSV", "*.csv"), (T("common.all_files"), "*.*")])
            if not path:
                return
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["n", "p", "q", "rep_count", "pairs"])
                for row in result["rows"]:
                    pairs_str = (
                        "; ".join(f"{p}+{q}" for p, q in row["pairs"])
                        if row["pairs"] else "")
                    writer.writerow([
                        row["n"],
                        row["p"] if row["p"] is not None else "",
                        row["q"] if row["q"] is not None else "",
                        row["rep_count"] if row["rep_count"] is not None else "",
                        pairs_str])
            self.status.set(T("research_goldbach.status_exported", path=path))

        def _goldbach_show_window_visualization(self, result):
            """Redraws the "old base vs window" diagram into the PERSISTENT Wizualizacja
            Toplevel/Canvas (see _goldbach_ensure_viz_window) -- built from a REAL
            window_rows() result sourced from the magazyn
            (read_is_prime_from_storage), covering EXACTLY the window [4, 2*Pmax] that
            "Sprawdz okno" also checks (never a separate cascade step -- see
            goldbach_window.window_rows' own docstring and Artur's own instruction:
            "wizualizacja zawsze siedzi w oknie 4-2Pmax"). The window itself, its n
            field and its check button are created once and reused; this method only
            clears and repopulates the canvas so repeated checks (from this tab's
            button, or the window's own button) update ONE window in place instead of
            piling up a new Toplevel per click. Plain tk.Canvas, same
            zero-extra-installs approach as the Benchmark tab's own hand-rolled chart
            (no matplotlib)."""
            win = self._goldbach_ensure_viz_window()
            win.title(T("research_goldbach.viz_window_title",
                        n=result["n"], pmax=result["pmax"]))
            # The coverage verdict (all covered / which n's aren't) is ALSO drawn at
            # the very bottom of the canvas below (viz_summary_covered/void), but
            # that can end up scrolled or clipped off screen for a tall diagram --
            # Artur asked for the message to appear "somewhere" it's guaranteed
            # visible, so it's repeated here in the status label at the TOP of the
            # window, which never depends on the canvas's own size.
            coverage_text = (
                T("research_goldbach.viz_summary_covered",
                  segment_size=result["segment_size"])
                if result["covered"] else
                T("research_goldbach.viz_summary_void",
                  counterexamples=", ".join(str(x) for x in result["counterexamples"])))
            # Only shown when the "od/do" fields actually narrowed the scan below
            # the full [4, window_max] -- otherwise range_min/range_max just equal
            # the window's own bounds and the note would be redundant noise on
            # every single check. Without this, a restricted-range "covered"
            # verdict could easily be misread as a claim about the WHOLE window.
            range_note = (
                "  " + T("research_goldbach.viz_range_note",
                         range_min=result["range_min"], range_max=result["range_max"])
                if result["range_min"] != 4 or result["range_max"] != result["window_max"]
                else "")
            self.goldbach_viz_status_var.set(
                T("research_goldbach.viz_status_shown", n=result["n"], pmax=result["pmax"])
                + range_note + "  " + coverage_text)
            if self.goldbach_viz_n_entry.get().strip() != str(result["n"]):
                self.goldbach_viz_n_entry.delete(0, "end")
                self.goldbach_viz_n_entry.insert(0, str(result["n"]))

            # Cache the full result so the chip Prev/Next handlers (pure client-side,
            # see _on_goldbach_viz_chip_prev/_next's own docstrings) can call back into
            # this same method without needing a fresh worker round-trip.
            self._goldbach_viz_last_result = result

            canvas = self.goldbach_viz_canvas
            canvas.delete("all")

            chips = result["old_base_primes"]
            rows = result["rows"]

            # Box widths scale to the actual digit count of the values THIS diagram is
            # drawing (window_max/pmax), instead of a fixed pixel width -- a fixed
            # width sized for 2-digit examples would silently clip or overflow once n
            # (and therefore p/q) grows into 5+ digits.
            def _digit_box_w(min_w, digits):
                return max(min_w, 11 * digits + 22)

            n_digits = len(str(result["window_max"]))
            p_digits = len(str(result["pmax"]))
            q_digits = len(str(result["window_max"]))  # q can approach window_max
            n_box_w = _digit_box_w(46, n_digits)
            p_box_w = _digit_box_w(44, p_digits)
            q_box_w = _digit_box_w(44, q_digits)
            chip_w = _digit_box_w(34, p_digits)
            chip_gap = 6

            # chip_cols (and therefore the "STARA BAZA" box width) is derived from
            # chip_w, not hardcoded -- a fixed 6-column grid at a fixed 230px box width
            # was sized for 1-2 digit primes; once Pmax grew multi-digit (chip_w scaled
            # up above), 6 columns no longer fit inside 230px and the overflow chips
            # were drawn PAST the box's right edge, straight on top of the row grid
            # beside it (Artur caught this: the "11 13" / "31 37" / "59 61" / "83 89"
            # fragments overlapping the n=6/8/10/12 rows in his n=997 screenshot were
            # literally chips 5 and 6 of each chip row spilling out). box_w is now
            # computed to fit chip_cols columns EXACTLY, so there is no overflow at any
            # digit count -- chip_cols itself narrows for big primes instead.
            chip_cols_target_w = 210  # desired inner width for the chip grid
            chip_cols = max(3, chip_cols_target_w // (chip_w + chip_gap))
            box_w = 24 + chip_cols * chip_w + (chip_cols - 1) * chip_gap

            # STARA BAZA pagination (client-side, see _on_goldbach_viz_chip_prev/_next):
            # old_base_primes can hold hundreds of thousands of entries for a large
            # Pmax, so only ONE page's worth is ever sliced for drawing -- per Artur's
            # request for the same kind of Prev/Next browsing used elsewhere in the app
            # for large lists, instead of a static "+N more" note with no way to see
            # the rest.
            chip_page_size = chip_cols * GOLDBACH_VIZ_CHIP_ROWS_PER_PAGE
            total_chip_pages = max(1, -(-len(chips) // chip_page_size)) if chips else 1
            self._goldbach_viz_chip_page = max(
                0, min(self._goldbach_viz_chip_page, total_chip_pages - 1))
            chip_start = self._goldbach_viz_chip_page * chip_page_size
            chip_shown = chips[chip_start:chip_start + chip_page_size]
            chip_rows = max(1, -(-len(chip_shown) // chip_cols))
            _update_nav_controls(
                self.goldbach_viz_chip_page_label, self._goldbach_viz_chip_page,
                total_chip_pages, self.goldbach_viz_chip_prev_btn,
                self.goldbach_viz_chip_next_btn)

            # Rows fan out into up to GOLDBACH_VIZ_MAX_COLS columns instead of one long
            # strip -- a single column left the diagram pinned to the top-left with a
            # large blank area beside it once the window was sized to fit its content
            # rather than stretched to fill the Toplevel (see _goldbach_ensure_viz_
            # window's own note on why the canvas is no longer packed with fill/expand).
            rows_per_col = GOLDBACH_VIZ_ROWS_PER_COL
            header_h = 106
            footer_h = 60

            # Cap rows_per_col to what actually fits ON SCREEN VERTICALLY, mirroring
            # the column-width cap just below -- Artur reported that adding the mode
            # toggle row (_goldbach_ensure_viz_window) pushed a full 3x14-row page
            # (both_base mode, n=1000) tall enough that the canvas -- and with it the
            # "wszystko pokryte" / counterexamples summary drawn at its very bottom --
            # ran off the bottom of the screen with no scrollbar to reach it. Unlike
            # the width cap (which drops whole COLUMNS), this shrinks how many ROWS
            # each column holds, so a screen too short for 14 rows still shows AS MANY
            # full rows as fit rather than none. available_h subtracts a flat margin
            # for the Toplevel's own packed controls above the canvas (n/status/mode/
            # decompose/chip-nav/row-nav rows) plus OS window chrome/taskbar, none of
            # which is part of the canvas itself but all of which still has to fit
            # alongside it on screen.
            screen_h = win.winfo_screenheight()
            available_h = max(260, screen_h - 380)
            max_rows_h = available_h - header_h - footer_h
            max_rows_per_col = max(1, (max_rows_h - 26 - 18) // 36)
            if rows_per_col > max_rows_per_col:
                rows_per_col = max_rows_per_col

            cols_wanted = min(GOLDBACH_VIZ_MAX_COLS, max(1, -(-len(rows) // rows_per_col))) \
                if rows else 1

            EQ_W, PLUS_W, GAP, COL_GAP = 16, 16, 8, 28
            card_w = n_box_w + GAP + EQ_W + GAP + p_box_w + GAP + PLUS_W + GAP + q_box_w
            right_x = 16 + box_w + 20

            # Cap the diagram to what actually fits ON SCREEN (not just what fits in
            # the CANVAS) -- Artur reported a wide n (e.g. n=10_000_000, 8-digit
            # values) producing a Toplevel wider than his screen, with the rightmost
            # column of "n = p + q" cards simply run off the edge (no scrollbar, no
            # way to reach it). Per his instruction ("jeśli nie zmieści się w oknie
            # kolumna sum to niech się nie wyświetla") a column that would push the
            # window past screen width is dropped entirely rather than drawn
            # off-screen -- the truncation note below then reports the real shown/total
            # count so it's clear more rows exist (use n or Eksportuj CSV to see them).
            screen_w = win.winfo_screenwidth()
            available_w = max(700, screen_w - 150)  # leave room for window chrome/taskbar
            fit_cols = max(1, (available_w - right_x - 16 + COL_GAP) // (card_w + COL_GAP))
            cols = max(1, min(cols_wanted, fit_cols))
            rows_drawn = min(len(rows), cols * rows_per_col)
            grid_w = cols * card_w + (cols - 1) * COL_GAP

            canvas_w = max(
                16 + box_w + 20 + grid_w + 16,
                16 + box_w + 16 + 300,  # never narrower than a comfortable minimum
            )
            chips_h = 48 + chip_rows * 36
            rows_truncated = result["rows_truncated"] or rows_drawn < len(rows)
            # Height reserved for the tallest column actually drawn -- with the fixed
            # (non-rebalanced) rows_per_col assignment below, every column except
            # possibly the last is exactly rows_per_col tall, so min(rows_per_col,
            # rows_drawn) is always correct: it's rows_per_col once there's enough to
            # fill a full column, or just rows_drawn for a single partial column (e.g.
            # a small window with only a handful of rows total -- reserving a full
            # page's height for those would leave a large empty gap below them, the
            # same "wasted space" complaint this diagram had before).
            rows_per_col_used = max(1, min(rows_per_col, rows_drawn))
            rows_h = 26 + rows_per_col_used * 36 + (18 if rows_truncated else 0)
            canvas_h = header_h + max(chips_h, rows_h) + footer_h
            canvas.configure(width=canvas_w, height=canvas_h)

            canvas.create_text(
                16, 18, anchor="nw", font=("TkDefaultFont", 13, "bold"),
                text=T("research_goldbach.viz_header",
                       n=result["n"], pmax=result["pmax"], window_max=result["window_max"]))
            canvas.create_text(
                16, 44, anchor="nw", font=("TkDefaultFont", 9), fill="#64748b",
                width=canvas_w - 32,
                text=T("research_goldbach.viz_subheader"))
            canvas.create_text(
                16, 82, anchor="nw", font=("TkDefaultFont", 8), fill="#166534",
                text=T("research_goldbach.viz_legend_new_q"))

            top_y = header_h

            canvas.create_rectangle(16, top_y, 16 + box_w, top_y + chips_h,
                                     outline="#2563eb", width=1.5, fill="#eff6ff")
            canvas.create_text(16 + box_w / 2, top_y + 16, font=("TkDefaultFont", 10, "bold"),
                                fill="#1d4ed8", text=T("research_goldbach.viz_old_base_title"))
            canvas.create_text(
                16 + box_w / 2, top_y + 32, font=("TkDefaultFont", 8), fill="#3b82f6",
                text=T("research_goldbach.viz_old_base_subtitle", pmax=result["pmax"]))
            chip_h_px = 30
            start_x = 16 + 12
            start_y = top_y + 46
            for i, p in enumerate(chip_shown):
                col, row = i % chip_cols, i // chip_cols
                x0 = start_x + col * (chip_w + chip_gap)
                y0 = start_y + row * (chip_h_px + chip_gap)
                canvas.create_rectangle(x0, y0, x0 + chip_w, y0 + chip_h_px,
                                         outline="#93c5fd", width=1.5, fill="white")
                canvas.create_text(x0 + chip_w / 2, y0 + chip_h_px / 2,
                                    font=("TkDefaultFont", 10, "bold"), fill="#1d4ed8",
                                    text=str(p))

            row_y = top_y
            canvas.create_text(
                right_x, row_y, anchor="nw", font=("TkDefaultFont", 10, "bold"),
                width=canvas_w - right_x - 16,
                text=T("research_goldbach.viz_segment_title",
                       range_min=result["range_min"], range_max=result["range_max"]))
            grid_top_y = row_y + 26
            for i, row in enumerate(rows[:rows_drawn]):
                col_idx = i // rows_per_col
                within_idx = i % rows_per_col
                cx = right_x + col_idx * (card_w + COL_GAP)
                cy = grid_top_y + within_idx * 36
                n = row["n"]
                p = row["p"] if row["p"] is not None else "?"
                q = row["q"] if row["q"] is not None else "?"
                x = cx
                canvas.create_rectangle(x, cy, x + n_box_w, cy + 26,
                                         fill="#0f172a", outline="")
                canvas.create_text(x + n_box_w / 2, cy + 13, fill="white",
                                    font=("TkDefaultFont", 10, "bold"), text=str(n))
                x += n_box_w + GAP
                canvas.create_text(x + EQ_W / 2, cy + 13, fill="#94a3b8", text="=")
                x += EQ_W + GAP
                canvas.create_rectangle(x, cy, x + p_box_w, cy + 26,
                                         outline="#2563eb", width=1.5, fill="#dbeafe")
                canvas.create_text(x + p_box_w / 2, cy + 13, fill="#1d4ed8",
                                    font=("TkDefaultFont", 10, "bold"), text=str(p))
                x += p_box_w + GAP
                canvas.create_text(x + PLUS_W / 2, cy + 13, fill="#94a3b8", text="+")
                x += PLUS_W + GAP
                # q is drawn in the SAME blue as p -- both_base_window_rows only ever
                # records a witness with q <= Pmax too (matching Lean's
                # additiveSelfContained_of_hasGoldbachRep), so q is exactly as much
                # "in the base" as p is here, not just informational. (An amber/
                # warning-orange coloring for q > Pmax briefly existed when this
                # diagram tracked buildableFromBase, which only bounds p -- removed
                # per Artur, 2026-08-17: "skoro wszystkie są budowalne z bazy to
                # takie wyświetlajmy", and now moot besides, since q > Pmax is never
                # a witness this mode returns at all.)
                q_fill, q_outline = "#dbeafe", "#2563eb"
                canvas.create_rectangle(x, cy, x + q_box_w, cy + 26,
                                         outline=q_outline, width=1.5, fill=q_fill)
                canvas.create_text(x + q_box_w / 2, cy + 13, fill=q_outline,
                                    font=("TkDefaultFont", 10, "bold"), text=str(q))
            grid_bottom_y = grid_top_y + rows_per_col_used * 36
            if rows_truncated:
                canvas.create_text(
                    right_x, grid_bottom_y + 2, anchor="nw", font=("TkDefaultFont", 8),
                    fill="#64748b",
                    text=T("research_goldbach.viz_rows_truncated",
                           shown=rows_drawn, total=result["segment_size"]))

            # total_row_pages is derived from segment_size/ROW_CAP -- deliberately NOT
            # from rows_drawn (the on-screen, possibly-narrower-than-a-page count from
            # the column-dropping above). A screen-width-dropped column means more of
            # THIS SAME page would show if the window were wider, not that turning the
            # page would reveal it -- so Next must only look available when there's
            # genuinely another page of window beyond this one.
            row_page = result.get("row_page", 0)
            total_row_pages = max(
                1, -(-result["segment_size"] // GOLDBACH_CASCADE_ROW_CAP))
            _update_nav_controls(
                self.goldbach_viz_row_page_label, row_page, total_row_pages,
                self.goldbach_viz_row_prev_btn, self.goldbach_viz_row_next_btn)

            footer_y = top_y + max(chips_h, rows_h) + 16
            if result["covered"]:
                footer_text = T("research_goldbach.viz_summary_covered",
                                 segment_size=result["segment_size"])
                footer_color = "#166534"
            else:
                footer_text = T(
                    "research_goldbach.viz_summary_void",
                    counterexamples=", ".join(str(x) for x in result["counterexamples"]))
                footer_color = "#991b1b"
            canvas.create_text(16, footer_y, anchor="nw", font=("TkDefaultFont", 10, "bold"),
                                fill=footer_color, width=canvas_w - 32, text=footer_text)

            # Reset any size the user (or a previous, differently-sized diagram) left
            # the Toplevel at, so it re-fits itself to THIS canvas's actual content
            # instead of staying stretched -- see _goldbach_ensure_viz_window's note.
            win.geometry("")

        def _build_research_gaps_tab(self):
            """Prime gap explorer (raw gaps + Andrica/Firoozbakht/Cramer overlays) --
            PLACEHOLDER, no logic yet (Faza 0)."""
            ttk.Label(self.research_gaps_tab, text=T("research_gaps.placeholder"),
                      wraplength=700, justify="left").pack(anchor="nw", padx=12, pady=12)

        def _build_research_pi_approx_tab(self):
            """pi(x) approximation accuracy explorer (li(x), R(x)) -- PLACEHOLDER, no logic
            yet (Faza 0)."""
            ttk.Label(self.research_pi_approx_tab, text=T("research_pi_approx.placeholder"),
                      wraplength=700, justify="left").pack(anchor="nw", padx=12, pady=12)

        # --- Tab 3: Generation (launch orchestrator_loop_v2 / constellation_finder) --

        def _build_scrollable_container(self, parent):
            """Wraps `parent` in a vertically-scrollable canvas+frame and returns the
            inner ttk.Frame -- pack the tab's REAL content into that returned frame
            instead of into `parent` directly; everything else (canvas, scrollbar,
            width sync, mousewheel binding) is handled here. Added 2026-08-19 because
            the Generation tab's three sections (A: pipeline, B: constellation search,
            C: k-tuple search -- each with its own Advanced-fields block and its own
            GenerationConsole terminal) together need more vertical space than the
            1050x680 main window has, and a plain pack()/Panedwindow layout has no way
            to reach whatever falls below the visible area -- Section C being added
            last effectively pushed A/B's terminals and advanced fields (write_files,
            compute_sieving_primes_count, etc.) out of reach even though nothing was
            actually removed. This is a pure ADDITIVE wrapper (same rule as
            digit_sweep/pass_counter above: extend, don't replace) -- it changes
            nothing about what's inside, only how it's reached once it doesn't fit.

            Standard canvas-scrollregion idiom: an inner frame is placed on a canvas
            via create_window; the inner frame's own <Configure> (fires whenever its
            packed children change its natural size) updates the canvas' scrollregion
            to match, and the canvas' own <Configure> (fires on window resize) keeps
            the inner frame exactly as WIDE as the visible canvas so fill="x" widgets
            inside it still span the full width like they did before this wrapper
            existed, instead of collapsing to their minimum content width. Mousewheel
            scrolling is bound only while the pointer is actually over this canvas
            (bound on <Enter>, unbound on <Leave>) so it doesn't steal wheel events
            from Treeviews or other scrollable widgets on other tabs. <MouseWheel>
            covers Windows/Mac; <Button-4>/<Button-5> cover X11 (Linux) which reports
            the wheel as button clicks instead of a delta."""
            outer = ttk.Frame(parent)
            outer.pack(fill="both", expand=True)

            canvas = tk.Canvas(outer, highlightthickness=0)
            vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=vsb.set)
            canvas.pack(side="left", fill="both", expand=True)
            vsb.pack(side="right", fill="y")

            inner = ttk.Frame(canvas)
            inner_window = canvas.create_window((0, 0), window=inner, anchor="nw")

            def _on_inner_configure(_event):
                canvas.configure(scrollregion=canvas.bbox("all"))
            inner.bind("<Configure>", _on_inner_configure)

            def _on_canvas_configure(event):
                canvas.itemconfigure(inner_window, width=event.width)
            canvas.bind("<Configure>", _on_canvas_configure)

            def _on_mousewheel(event):
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

            def _bind_mousewheel(_event):
                canvas.bind_all("<MouseWheel>", _on_mousewheel)
                canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
                canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))

            def _unbind_mousewheel(_event):
                canvas.unbind_all("<MouseWheel>")
                canvas.unbind_all("<Button-4>")
                canvas.unbind_all("<Button-5>")

            canvas.bind("<Enter>", _bind_mousewheel)
            canvas.bind("<Leave>", _unbind_mousewheel)

            return inner

        def _build_generation_tab(self):
            """Two independent sections ("Separate calls and parameterization"):
            orchestrator_loop_v2.py's full generation pipeline on
            top, constellation_finder_v1.py's k-tuple search below -- each with its own
            form (every CLI parameter those scripts expose, including the ones that used
            to require editing source files -- see orchestrator_v3.py's/orchestrator_
            loop_v2.py's workers/batches_per_worker/window_count_per_run CLI-exposure
            changes), its own Run/Stop pair, and its own live output pane. Form
            values are loaded from .portal_generation_settings.json once here and
            persisted again every time Run is pressed (see _on_run_loop/
            _on_run_constellation) -- so the next app start reopens with
            whatever was last used, no re-typing needed."""
            self._generation_settings = load_generation_settings(PORTAL_FOLDER)

            # Scrollable wrapper (see _build_scrollable_container's own docstring) --
            # everything below packs into `generation_body`, not into
            # self.generation_tab directly, so the tab as a whole gains a vertical
            # scrollbar/mousewheel once Sections A+B+C together exceed the window's
            # visible height, instead of silently cutting off whatever doesn't fit.
            generation_body = self._build_scrollable_container(self.generation_tab)

            self._init_quick_generation_state()
            quick_outer = ttk.Labelframe(generation_body, text=T("quick.section_title"))
            quick_outer.pack(fill="x", padx=6, pady=(6, 0))
            self._build_quick_generation_panel(quick_outer)

            paned = ttk.Panedwindow(generation_body, orient="vertical")
            paned.pack(fill="both", expand=True, padx=6, pady=6)

            # --- Section A: orchestrator_loop_v2.py (generation pipeline) ------------
            loop_outer = ttk.Labelframe(
                paned, text=T("gen.section_loop"))
            paned.add(loop_outer, weight=1)

            # These are advanced settings, so base_exponent/run_count/
            # n_instances/window_count_per_run/workers/batches_per_worker/window_m (plus
            # the two checkboxes) collapse behind a toggle button, collapsed by default.
            #
            # loop_btn_row (Run/Stop/status) is hidden along with them: the raw
            # Run button only makes sense once you can actually SEE what it'll run
            # with, so loop_btn_row now lives INSIDE the same collapsible block as the
            # fields, not next to it -- one toggle hides/shows both together. The normal
            # way to run is now the Quick-gen "Generate" button above
            # (_on_quick_generate_or_stop_clicked), which doubles as Stop while a run is
            # in flight (see _on_run_loop/_on_loop_finished).
            loop_advanced_row = ttk.Frame(loop_outer)
            loop_advanced_row.pack(fill="x", padx=8, pady=(6, 0))
            self._loop_advanced_visible = False
            self.loop_advanced_toggle_btn = ttk.Button(
                loop_advanced_row, text=T("gen.advanced_show"),
                command=self._on_toggle_loop_advanced)
            self.loop_advanced_toggle_btn.pack(side="left")

            loop_advanced_content = ttk.Frame(loop_outer)
            self._loop_advanced_content = loop_advanced_content
            # NOT packed here -- starts collapsed, see _on_toggle_loop_advanced(). Packed
            # (when shown) with before=self.loop_console.toggle_row so it always lands
            # right below the toggle button, above the console's own toggle row.

            loop_form = ttk.Frame(loop_advanced_content)
            loop_form.pack(fill="x")

            self._loop_vars = {}
            loop_settings = self._generation_settings["loop"]

            def add_loop_field(row, col, key, label, width=10):
                ttk.Label(loop_form, text=label).grid(
                    row=row, column=col * 2, sticky="w", padx=(0, 4), pady=2)
                var = tk.StringVar(value=str(loop_settings.get(key, "")))
                ttk.Entry(loop_form, textvariable=var, width=width).grid(
                    row=row, column=col * 2 + 1, sticky="w", padx=(0, 20), pady=2)
                self._loop_vars[key] = var

            add_loop_field(0, 0, "base_exponent", T("gen.field_base_exponent"))
            add_loop_field(0, 1, "run_count", T("gen.field_run_count"))
            add_loop_field(1, 0, "n_instances", T("gen.field_n_instances"))
            add_loop_field(1, 1, "window_count_per_run", T("gen.field_window_count"))
            add_loop_field(2, 0, "workers", T("gen.field_workers"))
            # Auto button for "workers", same idea as Quick generation's own RAM-based
            # Auto button for window count (_on_quick_auto_width_clicked) -- probes
            # WSL's available CPU count and fills the field with it (see
            # _on_workers_auto_clicked's own docstring). Occupies the grid slot
            # batches_per_worker used to sit in (raw column 2); batches_per_worker
            # itself moves one field-slot to the right (col=2 -> raw columns 4/5) to
            # make room, rather than crowding a fourth thing onto this row.
            ttk.Button(loop_form, text=T("quick.auto_button"), width=6,
                       command=self._on_workers_auto_clicked).grid(
                row=2, column=2, sticky="w", padx=(0, 8), pady=2)
            add_loop_field(2, 2, "batches_per_worker", T("gen.field_batches"))
            # window_m: was hardcoded to 10,000,000 in three separate scanner/orchestrator
            # files -- now a real CLI-overridable parameter, threaded all the way down to
            # prime_sieve_v3.py (see build_loop_argv()'s docstring for the full chain and
            # the "only safe to change for a floor with no existing data" caveat).
            add_loop_field(3, 0, "window_m", T("gen.field_window_m"), width=14)

            self._loop_write_files_var = tk.BooleanVar(
                value=bool(loop_settings.get("write_files", True)))
            ttk.Checkbutton(loop_form, text=T("gen.check_write_files"),
                             variable=self._loop_write_files_var).grid(
                row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
            self._loop_count_sieving_var = tk.BooleanVar(
                value=bool(loop_settings.get("compute_sieving_primes_count", False)))
            ttk.Checkbutton(
                loop_form, text=T("gen.check_count_sieving"),
                variable=self._loop_count_sieving_var).grid(
                row=4, column=2, columnspan=2, sticky="w", pady=(6, 0))

            loop_btn_row = ttk.Frame(loop_advanced_content)
            loop_btn_row.pack(fill="x", pady=(6, 0))
            self.loop_run_btn = ttk.Button(loop_btn_row, text=T("common.run"), command=self._on_run_loop)
            self.loop_run_btn.pack(side="left")
            self.loop_stop_btn = ttk.Button(
                loop_btn_row, text=T("common.stop"), command=self._on_stop_loop, state="disabled")
            self.loop_stop_btn.pack(side="left", padx=(6, 0))
            self.loop_status_label = tk.StringVar(value=T("common.ready"))
            ttk.Label(loop_btn_row, textvariable=self.loop_status_label).pack(
                side="left", padx=(12, 0))

            # Each terminal pane (loop and constellation) has its own collapse toggle,
            # collapsed whenever its script isn't running: own toggle, collapsed on every
            # app start (no persisted state), auto-expanded by _show_loop_terminal() the
            # moment a run actually starts (_on_run_loop), and deliberately left alone
            # (never auto-collapsed) once it finishes -- see _on_loop_finished. Toggle/
            # clear/open-in-new-window live together in GenerationConsole (primeatlas/
            # generation_console.py), reused identically by this section and the
            # constellation-finder section below. The detached window additionally gets
            # its own copy of the Quick-gen panel (see _build_detached_quick_panel), bound
            # to the SAME shared StringVars as the embedded one, so both always show the
            # same values and a run started from either place behaves identically.
            self.loop_console = GenerationConsole(
                loop_outer, TRANSLATOR, height=10,
                extra_controls_builder=self._build_detached_quick_panel)
            self.loop_output = self.loop_console.text

            self._loop_runner = None
            self._loop_output_queue = queue.Queue()

            # --- Section B: constellation_finder_v1.py (k-tuple search) --------------
            const_outer = ttk.Labelframe(
                paned, text=T("gen.section_const"))
            paned.add(const_outer, weight=1)

            const_form = ttk.Frame(const_outer)
            const_form.pack(fill="x", padx=8, pady=6)
            const_settings = self._generation_settings["constellation"]
            ttk.Label(const_form, text=T("gen.const_field_base_exponent")).pack(
                side="left")
            self._const_base_exponent_var = tk.StringVar(
                value=str(const_settings.get("base_exponent", "")))
            ttk.Entry(const_form, textvariable=self._const_base_exponent_var, width=10).pack(
                side="left", padx=(6, 0))

            const_btn_row = ttk.Frame(const_outer)
            const_btn_row.pack(fill="x", padx=8, pady=(0, 4))
            self.const_run_btn = ttk.Button(
                const_btn_row, text=T("common.run"), command=self._on_run_constellation)
            self.const_run_btn.pack(side="left")
            self.const_stop_btn = ttk.Button(
                const_btn_row, text=T("common.stop"), command=self._on_stop_constellation,
                state="disabled")
            self.const_stop_btn.pack(side="left", padx=(6, 0))
            self.const_status_label = tk.StringVar(value=T("common.ready"))
            ttk.Label(const_btn_row, textvariable=self.const_status_label).pack(
                side="left", padx=(12, 0))

            # Collapsible terminal, same as the pipeline section's loop_console above --
            # see GenerationConsole's docstring for the full rationale. No extra_controls_
            # builder here -- the constellation-finder section has no Quick-gen-style panel
            # to duplicate, only its own raw Run/Stop pair above.
            self.const_console = GenerationConsole(const_outer, TRANSLATOR, height=10)
            self.const_output = self.const_console.text

            self._const_runner = None
            self._const_output_queue = queue.Queue()

            # --- Section C: ktuple_sieve_v1.py (targeted k-tuple candidate sieve) -----
            # Complementary to Section B: that one pattern-matches against windows
            # already fully sieved by prime_sieve; this one hunts a single, sparse
            # pattern (e.g. k=15) directly, via a residue wheel + trial division +
            # Miller-Rabin, across scattered window locations -- see ktuple_sieve_v1.py's
            # own module docstring for why that's a fundamentally different (and, for a
            # sparse-enough pattern, far cheaper) approach than fully sieving a wide
            # enough span for Section B to find the same thing.
            ktuple_outer = ttk.Labelframe(paned, text=T("gen.section_ktuple"))
            paned.add(ktuple_outer, weight=1)

            ktuple_settings = self._generation_settings["ktuple"]

            ktuple_pattern_row = ttk.Frame(ktuple_outer)
            ktuple_pattern_row.pack(fill="x", padx=8, pady=(6, 0))
            ttk.Label(ktuple_pattern_row, text=T("gen.ktuple_field_k")).pack(side="left")
            self._ktuple_k_values = pattern_catalog_v1.all_k()
            self.ktuple_k_combo = ttk.Combobox(
                ktuple_pattern_row, state="readonly", width=6,
                values=[str(k) for k in self._ktuple_k_values])
            self.ktuple_k_combo.pack(side="left", padx=(6, 16))
            self.ktuple_k_combo.bind("<<ComboboxSelected>>", self._on_ktuple_k_changed)

            ttk.Label(ktuple_pattern_row, text=T("gen.ktuple_field_variant")).pack(side="left")
            self._ktuple_variants = []
            self.ktuple_variant_combo = ttk.Combobox(ktuple_pattern_row, state="readonly", width=10)
            self.ktuple_variant_combo.pack(side="left", padx=(6, 0))
            self.ktuple_variant_combo.bind(
                "<<ComboboxSelected>>", self._on_ktuple_variant_changed)

            self.ktuple_pattern_info_var = tk.StringVar(value="")
            ttk.Label(ktuple_outer, textvariable=self.ktuple_pattern_info_var,
                      wraplength=760, justify="left", foreground="#555").pack(
                anchor="w", padx=8, pady=(0, 4))

            ktuple_form = ttk.Frame(ktuple_outer)
            ktuple_form.pack(fill="x", padx=8, pady=(0, 4))

            self._ktuple_vars = {}

            def add_ktuple_field(row, col, key, label, width=10):
                ttk.Label(ktuple_form, text=label).grid(
                    row=row, column=col * 2, sticky="w", padx=(0, 4), pady=2)
                var = tk.StringVar(value=str(ktuple_settings.get(key, "")))
                ttk.Entry(ktuple_form, textvariable=var, width=width).grid(
                    row=row, column=col * 2 + 1, sticky="w", padx=(0, 20), pady=2)
                self._ktuple_vars[key] = var

            add_ktuple_field(0, 0, "base_exponent", T("gen.ktuple_field_base_exponent"))
            add_ktuple_field(0, 1, "n_locations", T("gen.ktuple_field_n_locations"))
            # Auto button: recommended_digit_sweep_n_locations()'s own suggestion --
            # see _on_ktuple_n_locations_auto_clicked()'s docstring for why this
            # exists (a shared n_locations field left digit_sweep's per-branch depth
            # much thinner than Artur had pictured). Occupies the free grid slot right
            # after n_locations's own entry (columns 2/3), same "Auto button right
            # next to the field it fills" placement as the loop pipeline's own
            # workers Auto button above.
            ttk.Button(ktuple_form, text=T("quick.auto_button"), width=6,
                       command=self._on_ktuple_n_locations_auto_clicked).grid(
                row=0, column=4, sticky="w", padx=(0, 8), pady=2)
            add_ktuple_field(1, 0, "window_m", T("gen.ktuple_field_window_m"), width=14)

            ttk.Label(ktuple_form, text=T("gen.ktuple_field_strategy")).grid(
                row=1, column=2, sticky="w", padx=(0, 4), pady=2)
            self.ktuple_strategy_combo = ttk.Combobox(
                ktuple_form, state="readonly", width=16,
                values=[T("gen.ktuple_strategy_even"), T("gen.ktuple_strategy_concentrated"),
                        T("gen.ktuple_strategy_manual_list"), T("gen.ktuple_strategy_manual_step"),
                        T("gen.ktuple_strategy_digit_sweep")])
            self.ktuple_strategy_combo.grid(row=1, column=3, sticky="w", padx=(0, 20), pady=2)
            _saved_strategy = ktuple_settings.get("strategy", "concentrated")
            self.ktuple_strategy_combo.current(
                _KTUPLE_STRATEGY_KEYS.index(_saved_strategy)
                if _saved_strategy in _KTUPLE_STRATEGY_KEYS else 1)

            # "step": optional override for even/concentrated (both auto-compute their
            # own step otherwise -- see ktuple_sieve_v1.step_for_even()/
            # step_for_concentrated()), REQUIRED for manual_step. Visible in the
            # primary form (not tucked behind Advanced) since it's central to how
            # every non-manual_list strategy now behaves -- see the checkpoint/step
            # design added 2026-08-19 at Artur's request, after his first real run
            # showed every Run re-scanning the same locations with nothing persisted
            # in between.
            add_ktuple_field(2, 0, "step", T("gen.ktuple_field_step"), width=14)

            ktuple_advanced_row = ttk.Frame(ktuple_outer)
            ktuple_advanced_row.pack(fill="x", padx=8)
            self._ktuple_advanced_visible = False
            self.ktuple_advanced_toggle_btn = ttk.Button(
                ktuple_advanced_row, text=T("gen.advanced_show"),
                command=self._on_toggle_ktuple_advanced)
            self.ktuple_advanced_toggle_btn.pack(side="left")

            ktuple_advanced_content = ttk.Frame(ktuple_outer)
            self._ktuple_advanced_content = ktuple_advanced_content
            # NOT packed here -- starts collapsed, see _on_toggle_ktuple_advanced().

            ktuple_advanced_form = ttk.Frame(ktuple_advanced_content)
            ktuple_advanced_form.pack(fill="x")

            def add_ktuple_advanced_field(row, col, key, label, width=10):
                ttk.Label(ktuple_advanced_form, text=label).grid(
                    row=row, column=col * 2, sticky="w", padx=(0, 4), pady=2)
                var = tk.StringVar(value=str(ktuple_settings.get(key, "")))
                ttk.Entry(ktuple_advanced_form, textvariable=var, width=width).grid(
                    row=row, column=col * 2 + 1, sticky="w", padx=(0, 20), pady=2)
                self._ktuple_vars[key] = var

            add_ktuple_advanced_field(
                0, 0, "fragment_width", T("gen.ktuple_field_fragment_width"), width=18)
            add_ktuple_advanced_field(
                0, 1, "fragment_start", T("gen.ktuple_field_fragment_start"), width=18)
            add_ktuple_advanced_field(1, 0, "deep_prime_limit", T("gen.ktuple_field_deep_prime_limit"))
            add_ktuple_advanced_field(1, 1, "mr_rounds", T("gen.ktuple_field_mr_rounds"))
            # pass_counter: strategy=digit_sweep only -- the starting pass number (only
            # used the first time, before any checkpoint exists -- default 0 matches
            # Artur's own worked example verbatim). Each pass sweeps the whole floor
            # once more with every drilled position committing to a DIFFERENT digit
            # than the pass before (a different rate per position, so the explored path
            # looks scrambled/varied rather than a single repeated digit -- see
            # ktuple_sieve_v1.py's digit_sweep_locations() PATH VARIETY note). Kept in
            # Advanced alongside the other rarely-touched fields since the default
            # already matches his intent.
            add_ktuple_advanced_field(2, 0, "pass_counter", T("gen.ktuple_field_pass_counter"))
            ttk.Label(ktuple_advanced_form, text=T("gen.ktuple_field_manual_offsets")).grid(
                row=3, column=0, sticky="w", padx=(0, 4), pady=2)
            _manual_offsets_var = tk.StringVar(value=str(ktuple_settings.get("manual_offsets", "")))
            ttk.Entry(ktuple_advanced_form, textvariable=_manual_offsets_var, width=50).grid(
                row=3, column=1, columnspan=3, sticky="w", padx=(0, 20), pady=2)
            self._ktuple_vars["manual_offsets"] = _manual_offsets_var

            ktuple_btn_row = ttk.Frame(ktuple_outer)
            ktuple_btn_row.pack(fill="x", padx=8, pady=(4, 4))
            self.ktuple_run_btn = ttk.Button(
                ktuple_btn_row, text=T("common.run"),
                command=lambda: self._launch_ktuple(auto=False))
            self.ktuple_run_btn.pack(side="left")
            # "Auto": same launch path as Run, only auto=True differs -- keeps looping
            # batch after batch (checkpointing after each, see ktuple_sieve_v1.
            # run_ktuple_job()'s own docstring) inside the SAME WSL process until a
            # confirmed hit, Stop, or the floor is exhausted, rather than requiring a
            # fresh Run click per batch.
            self.ktuple_auto_btn = ttk.Button(
                ktuple_btn_row, text=T("gen.ktuple_auto_button"),
                command=lambda: self._launch_ktuple(auto=True))
            self.ktuple_auto_btn.pack(side="left", padx=(6, 0))
            self.ktuple_stop_btn = ttk.Button(
                ktuple_btn_row, text=T("common.stop"), command=self._on_stop_ktuple,
                state="disabled")
            self.ktuple_stop_btn.pack(side="left", padx=(6, 0))
            self.ktuple_status_label = tk.StringVar(value=T("common.ready"))
            ttk.Label(ktuple_btn_row, textvariable=self.ktuple_status_label).pack(
                side="left", padx=(12, 0))

            # Reset-checkpoint: a plain checkbox rather than its own button/action --
            # checked, it adds --reset-checkpoint to whichever of Run/Auto is clicked
            # next (see _launch_ktuple), so resetting never needs its own separate WSL
            # round trip just to delete one small text file. Left checked afterward
            # (not auto-unchecked) -- deliberately, so a person who wants to restart a
            # SEQUENCE of runs from scratch doesn't have to re-check it before every
            # click.
            self._ktuple_reset_checkpoint_var = tk.BooleanVar(
                value=bool(ktuple_settings.get("reset_checkpoint", False)))
            ttk.Checkbutton(
                ktuple_outer, text=T("gen.ktuple_check_reset_checkpoint"),
                variable=self._ktuple_reset_checkpoint_var).pack(anchor="w", padx=8, pady=(0, 4))

            self.ktuple_console = GenerationConsole(ktuple_outer, TRANSLATOR, height=10)
            self.ktuple_output = self.ktuple_console.text

            self._ktuple_runner = None
            self._ktuple_output_queue = queue.Queue()

            if self._ktuple_k_values:
                _saved_k = ktuple_settings.get("k", "")
                try:
                    _saved_k_int = int(_saved_k) if _saved_k else None
                except ValueError:
                    _saved_k_int = None
                self.ktuple_k_combo.current(
                    self._ktuple_k_values.index(_saved_k_int)
                    if _saved_k_int in self._ktuple_k_values else 0)
                self._on_ktuple_k_changed(restore_variant_id=ktuple_settings.get("variant_id"))

            self.after(150, self._poll_loop_output)
            self.after(150, self._poll_constellation_output)
            self.after(150, self._poll_ktuple_output)

        def _on_toggle_loop_advanced(self):
            """Shows/hides loop_advanced_content -- the fields AND the raw Run/
            Stop/status row together (see _build_generation_tab()'s comment on
            Section A) -- packed with before=self.loop_console.toggle_row so it always
            lands back in the same slot (between the toggle button and the console's own
            toggle row) regardless of how many times it's been forgotten/re-shown."""
            if self._loop_advanced_visible:
                self._loop_advanced_content.pack_forget()
                self._loop_advanced_visible = False
                self.loop_advanced_toggle_btn.configure(text=T("gen.advanced_show"))
            else:
                self._loop_advanced_content.pack(
                    fill="x", padx=8, pady=(0, 4), before=self.loop_console.toggle_row)
                self._loop_advanced_visible = True
                self.loop_advanced_toggle_btn.configure(text=T("gen.advanced_hide"))

        def _show_loop_terminal(self):
            """Force-expands the pipeline console if it's currently collapsed -- called
            from _on_run_loop() the moment a run actually starts. No-op if already visible
            (e.g. the user had opened it manually)."""
            self.loop_console.show()

        def _show_const_terminal(self):
            self.const_console.show()

        def _new_run_separator(self):
            """Appended (not clear()'d -- see _on_run_loop/_on_run_constellation) at the
            start of every run, so several runs' output can stay stacked in the console
            for comparison instead of being wiped on every click. The Clear button (see
            GenerationConsole) is the only thing that actually empties the console now."""
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            return "\n" + "=" * 70 + f"\n{T('gen.new_run_marker', time=ts)}\n" + "=" * 70 + "\n"

        # --- Quick generation panel (higher-level, sits above the raw pipeline form) ---

        def _init_quick_generation_state(self):
            """Creates every Quick-gen StringVar/BooleanVar exactly once, shared by every
            panel instance _build_quick_generation_panel() builds (the embedded one plus
            any detached copy, see that method's note below) -- sharing the same Variable
            objects, rather than one set per instance, is what keeps two simultaneously-
            visible panels showing identical values without any manual syncing: typing in
            either copy's Entry widget updates both immediately."""
            self.quick_mode_var = tk.StringVar(value="floor")
            self.quick_floor_var = tk.StringVar(value="")
            self.quick_floor_width_var = tk.StringVar(value="1")
            self.quick_floor_start_var = tk.StringVar(value="")
            self.quick_floor_start_var.trace_add("write", self._on_quick_floor_start_changed)
            # Shared by TWO modes' own continuation paths: Floor mode's own BLANK-
            # starting-point path (a typed starting point already means "start exactly
            # there", see _quick_gen_plan_literal_range's own docstring, unaffected by
            # this toggle either way) and Exploration mode's own Floor field (blank OR
            # typed -- both of Exploration's own starting points can land on a floor
            # with a gap, see _try_fill_quick_gen_gap()'s own docstring, added there
            # 2026-08-18 at Artur's request to match Floor mode exactly). Default False
            # (continue past the highest existing file, today's historical behavior,
            # unchanged) rather than True, so enabling gap-filling is an explicit,
            # conscious choice rather than a surprising default for a person who has
            # never left a gap and doesn't need to think about this at all. Not
            # persisted across restarts, same as every other Quick-gen field (Width,
            # punkt startowy) -- see _apply_loop_params_and_run's own docstring for why
            # only the low-level orchestrator form persists.
            self.quick_floor_fill_gaps_var = tk.BooleanVar(value=False)
            self.quick_from_var = tk.StringVar(value="")
            self.quick_to_var = tk.StringVar(value="")
            self.quick_explore_floor_var = tk.StringVar(value="")
            self.quick_iterations_var = tk.StringVar(value="1")
            self.quick_explore_width_var = tk.StringVar(value="1")
            # primesieve mode: deliberately its OWN Floor/From/Width variables rather than
            # reusing quick_from_var/quick_to_var (an earlier version of this mode did) --
            # see _build_quick_mode_primesieve's docstring for why: this mode's own Auto
            # button now has a completely different meaning (fills From with this floor's
            # storage continuation point, not a RAM-based width suggestion), and Width
            # replaces the old literal To field entirely, so sharing Range mode's variables
            # would mean a value typed in one mode's fields could silently mispopulate the
            # other's on a mode switch.
            self.quick_primesieve_floor_var = tk.StringVar(value="")
            self.quick_primesieve_from_var = tk.StringVar(value="")
            self.quick_primesieve_width_var = tk.StringVar(value="1")
            self.quick_hint_var = tk.StringVar(value="")
            self.quick_status_var = tk.StringVar(value="")
            self._quick_panels = []

        def _build_quick_generation_panel(self, parent):
            """Higher-level "just tell me the floor / range" panel above the raw
            orchestrator_loop_v2.py parameter form -- those low-level
            fields (window_count_per_run, workers, batches_per_worker...) are too
            low-level for the app/user. This
            panel lets the person say WHAT they want -- a floor, or a numeric range in
            Python-expression-friendly notation (e.g. 10**5) -- in one of three ways, and a
            LATER step will translate that into the low-level fields below automatically:
            window width capped at QUICK_GEN_MAX_WINDOW_WIDTH (10,000,000), window count
            derived from the target range so the total comes out right, "exploration" mode
            appending N further 10-billion-wide chunks to a floor's existing data.

            An earlier "range -- width" mode (floor + a single width
            field) was dropped -- with no explicit start, it behaved identically to
            "floor only" (both just continue/create that floor), so it was a redundant
            duplicate rather than a genuinely different way of specifying the target.

            Callable more than once -- the detached generation window (see
            _build_detached_quick_panel) gets its own full copy of this panel, built by
            calling this same method again with a different parent. Every widget it
            creates is bound to the shared StringVars from _init_quick_generation_state()
            (called once, before the first call to this method), so typing in either copy
            updates both immediately; the one thing NOT shared is the widgets themselves,
            which is why mode-switching (_on_quick_mode_changed), the Floor field's
            readonly toggle (_on_quick_floor_start_changed), and the Generate/Stop label
            flip (_on_run_loop/_on_loop_finished) all loop over self._quick_panels instead
            of touching one fixed widget reference."""
            ttk.Label(parent, text=T("quick.intro"), foreground="#555555",
                      wraplength=900, justify="left").pack(
                anchor="w", padx=8, pady=(6, 4))

            mode_row = ttk.Frame(parent)
            mode_row.pack(fill="x", padx=8, pady=(0, 2))
            quick_modes = [
                ("floor", T("quick.mode_floor")),
                ("range", T("quick.mode_range")),
                ("explore", T("quick.mode_explore")),
                ("primesieve", T("quick.mode_primesieve")),
            ]
            for value, label in quick_modes:
                ttk.Radiobutton(mode_row, text=label, value=value, variable=self.quick_mode_var,
                                 command=self._on_quick_mode_changed).pack(side="left", padx=(0, 16))

            # All three mode sub-frames share the same grid cell (row 0, col 0) and are
            # switched with .tkraise() -- keeps whichever fields aren't relevant to the
            # current mode out of the way instead of disabling-in-place, and avoids
            # reflowing the rest of the panel's layout when the mode changes.
            fields_container = ttk.Frame(parent)
            fields_container.pack(fill="x", padx=8, pady=(2, 4))
            mode_frames = {}
            floor_entry = self._build_quick_mode_floor(fields_container, mode_frames)
            self._build_quick_mode_range(fields_container, mode_frames)
            self._build_quick_mode_explore(fields_container, mode_frames)
            self._build_quick_mode_primesieve(fields_container, mode_frames)

            ttk.Label(parent, textvariable=self.quick_hint_var, foreground="#555555",
                      wraplength=900, justify="left").pack(anchor="w", padx=8, pady=(0, 4))

            btn_row = ttk.Frame(parent)
            btn_row.pack(fill="x", padx=8, pady=(0, 8))
            # Generate is the primary Start/Stop control (the raw
            # Run/Stop pair moved inside the collapsible advanced block, see
            # _build_generation_tab()'s Section A) -- see
            # _on_quick_generate_or_stop_clicked/_on_run_loop/_on_loop_finished for the
            # three places that flip its label between quick.generate_button and
            # common.stop (looping over self._quick_panels so every copy flips together).
            generate_btn = ttk.Button(
                btn_row, text=T("quick.generate_button"),
                command=self._on_quick_generate_or_stop_clicked)
            generate_btn.pack(side="left")
            ttk.Label(btn_row, textvariable=self.quick_status_var).pack(side="left", padx=(12, 0))

            panel = {"mode_frames": mode_frames, "floor_entry": floor_entry,
                     "generate_btn": generate_btn}
            self._quick_panels.append(panel)
            self._sync_quick_panel(panel)  # show the right sub-frame + state for this copy
            return panel

        def _build_quick_mode_floor(self, container, mode_frames):
            """The on-disk window format stays EXACTLY as it is -- always round the
            requested amount UP to a whole number of QUICK_GEN_MAX_WINDOW_WIDTH
            (10,000,000) windows, since rounding up costs almost no extra time and keeps
            file management predictable. So Width here is a MULTIPLIER of that window
            size, not a raw integer -- entering 1 means one 10-million window, 1000 means
            1000 of them (10 billion, the max, an explicit input cap). A ttk.Spinbox (not a
            plain Entry) makes that bounded-multiplier nature visible at a glance and a
            validatecommand blocks keystrokes that would push it out of [1, 1000].

            Starting point is optional and drives which of its TWO roles the Floor field
            plays: blank start -> Floor is a normal, manually-typed field, and generation
            continues from that floor's last existing file; a start value -> Floor
            becomes a READ-ONLY, auto-computed display of digit_count_floor(start) (also
            solves "it's not easy to count how many zeros are in a big number" -- counting
            zeros in a huge number by eye is exactly what this now does for you). See
            _on_quick_floor_start_changed, wired via a trace on quick_floor_start_var
            (added once, in _init_quick_generation_state).

            Returns the Floor Entry widget so the caller can track it per-panel-instance
            (see _on_quick_floor_start_changed).

            Second row: a "fill gaps first" checkbox, relevant ONLY to the blank-starting-
            point path (a typed starting point already means "start exactly there" --
            see _quick_gen_plan_literal_range's own docstring, unaffected by this toggle)
            -- see quick_floor_fill_gaps_var's own comment in _init_quick_generation_state
            for why this defaults off. Deliberately not disabled/greyed out when a
            starting point IS typed -- it's simply ignored by that path, no need for the
            extra state-tracking a live enable/disable would cost."""
            # Outer wraps BOTH rows (field row + gap-toggle row) so mode_frames tracks
            # a single widget for the whole "floor" mode UI -- _sync_quick_panel only
            # grid()/grid_remove()s whatever is registered in mode_frames, so if the
            # toggle row were a sibling of outer in container (its own row=1) instead of
            # nested inside outer, it would never be hidden when switching to another
            # Quick-gen mode. Nesting it here is what keeps the two rows shown/hidden
            # together.
            outer = ttk.Frame(container)
            outer.grid(row=0, column=0, sticky="w")
            frame = ttk.Frame(outer)
            frame.grid(row=0, column=0, sticky="w")
            ttk.Label(frame, text=T("quick.field_floor")).pack(side="left")
            floor_entry = ttk.Entry(frame, textvariable=self.quick_floor_var, width=10)
            floor_entry.pack(side="left", padx=(6, 20))
            ttk.Label(frame, text=T("quick.field_width")).pack(side="left")
            width_vcmd = (self.register(self._validate_quick_width_spinbox), "%P")
            ttk.Spinbox(frame, from_=1, to=1000, textvariable=self.quick_floor_width_var,
                        width=6, validate="key", validatecommand=width_vcmd).pack(
                side="left", padx=(6, 4))
            ttk.Button(frame, text=T("quick.auto_button"),
                       command=lambda: self._on_quick_auto_width_clicked(
                           self.quick_floor_width_var)).pack(side="left", padx=(0, 20))
            ttk.Label(frame, text=T("quick.field_start")).pack(side="left")
            ttk.Entry(frame, textvariable=self.quick_floor_start_var, width=20).pack(
                side="left", padx=(6, 0))
            gap_row = ttk.Frame(outer)
            gap_row.grid(row=1, column=0, sticky="w", pady=(4, 0))
            ttk.Checkbutton(gap_row, text=T("quick.field_fill_gaps_first"),
                             variable=self.quick_floor_fill_gaps_var).pack(side="left")
            mode_frames["floor"] = outer
            return floor_entry

        def _validate_quick_width_spinbox(self, proposed):
            """validatecommand for the Width spinbox -- allows an empty field WHILE
            editing (so the user can select-all-and-retype), otherwise only digit strings
            in [1, 1000] -- UI-level input restriction only; this is not where the actual
            1 unit = 10,000,000 translation happens (that's the logic step, not yet
            written)."""
            if proposed == "":
                return True
            return proposed.isdigit() and 1 <= int(proposed) <= 1000

        def _validate_primesieve_width_spinbox(self, proposed):
            """validatecommand for primesieve mode's OWN Width spinbox -- same shape as
            _validate_quick_width_spinbox, but bounded to PRIMESIEVE_MAX_WIDTH_MULT instead
            of 1000 (see that constant's own docstring for why this mode's Width field has
            no RAM-driven reason to stay small)."""
            if proposed == "":
                return True
            return proposed.isdigit() and 1 <= int(proposed) <= PRIMESIEVE_MAX_WIDTH_MULT

        def _on_quick_floor_start_changed(self, *_args):
            """Gives the Floor field its two roles (see _build_quick_mode_floor's
            docstring): a parseable starting point value makes it a read-only,
            auto-computed "which floor is this number in" display; clearing/blanking it
            (or typing something unparseable) hands control back to the person, since an
            empty starting point means "continue this floor" and the app has no other way
            to know WHICH floor that is."""
            value = _eval_quick_number(self.quick_floor_start_var.get())
            new_floor_value = "" if value is None else str(digit_count_floor(value))
            new_state = "normal" if value is None else "readonly"
            self.quick_floor_var.set(new_floor_value)
            for panel in self._quick_panels:
                panel["floor_entry"].configure(state=new_state)

        def _build_quick_mode_range(self, container, mode_frames):
            frame = ttk.Frame(container)
            frame.grid(row=0, column=0, sticky="w")
            ttk.Label(frame, text=T("quick.field_from")).pack(side="left")
            ttk.Entry(frame, textvariable=self.quick_from_var, width=20).pack(
                side="left", padx=(6, 20))
            ttk.Label(frame, text=T("quick.field_to")).pack(side="left")
            ttk.Entry(frame, textvariable=self.quick_to_var, width=20).pack(
                side="left", padx=(6, 20))
            # Range mode has no window-COUNT field to fill in (From/To are literal
            # numbers, not a window multiplier) -- Auto here reports the recommendation
            # via a dialog instead (width_var=None, see _on_quick_auto_width_clicked),
            # for the person to factor into their own From/To choice.
            ttk.Button(frame, text=T("quick.auto_button"),
                       command=lambda: self._on_quick_auto_width_clicked(None)).pack(
                side="left")
            mode_frames["range"] = frame

        def _build_quick_mode_explore(self, container, mode_frames):
            """Exploration maps directly onto orchestrator_loop_v2's own
            run_count/WINDOW_COUNT_PER_RUN loop -- this mode ONLY continues on an EXISTING
            floor, never creates a new one. Floor can be left blank: the dispatch handler
            (_on_quick_generate_clicked) then auto-detects the highest 10p{N} folder that
            actually has data (find_highest_populated_floor()) and continues THAT, re-
            detected fresh on every click rather than sticky in the entry field -- so
            repeatedly pressing Generate with nothing typed keeps extending whatever is
            genuinely the deepest generated data right now. Typing a floor explicitly still
            works, to explore a specific one instead -- including a LOW floor (0-6), which
            legitimately reports "already in storage" once its own small, fixed domain is
            fully covered (see the low-floor guard in _on_quick_generate_clicked) rather
            than being treated as some kind of "auto" sentinel value; 0 is a real floor,
              not a placeholder for blank.

            The Floor field's own "Auto" button (_on_explore_auto_floor_clicked, separate
            from the Width field's own Auto button further right in this same row) fills
            it with that SAME auto-detected highest-populated-floor value explicitly --
            leaving the field blank and clicking Generate directly already does the
            identical thing, but typing/deleting text to reach an empty field is a much
            less discoverable way to trigger it than a labeled button, especially compared
            to every other Quick-gen mode's own Auto button doing something visibly similar
            for their own fields.

            One iteration covers Width x QUICK_GEN_MAX_WINDOW_WIDTH numbers -- same Width
            spinbox/meaning as "Floor only"'s (reuses _validate_quick_width_spinbox,
            [1, 1000]), so the per-iteration memory footprint is exactly as
            user-controllable here as it is there, instead of being pinned to a fixed
            1000-window (10 billion) iteration size regardless of how much RAM the machine
            running the WSL sieve actually has.

            Second row: the SAME "fill gaps first" checkbox/variable Floor mode's own
            blank-starting-point path uses (quick_floor_fill_gaps_var -- added here
            2026-08-18, at Artur's request, to match Floor mode's behavior exactly: "tak
            jak tylko piętro"). Relevant to BOTH of this mode's own starting points --
            blank Floor (auto-detects the highest populated floor) and a typed Floor --
            since either one can land on a floor that has a gap (see
            _try_fill_quick_gen_gap()'s own docstring for why a floor Exploration hasn't
            personally visited yet can still have one, e.g. from a search or Goldbach
            direct-range write)."""
            outer = ttk.Frame(container)
            outer.grid(row=0, column=0, sticky="w")
            frame = ttk.Frame(outer)
            frame.grid(row=0, column=0, sticky="w")
            ttk.Label(frame, text=T("quick.field_floor")).pack(side="left")
            ttk.Entry(frame, textvariable=self.quick_explore_floor_var, width=10).pack(
                side="left", padx=(6, 4))
            ttk.Button(frame, text=T("quick.explore_auto_floor_button"),
                       command=self._on_explore_auto_floor_clicked).pack(
                side="left", padx=(0, 20))
            ttk.Label(frame, text=T("quick.field_iterations")).pack(side="left")
            iterations_vcmd = (self.register(self._validate_quick_iterations_spinbox), "%P")
            ttk.Spinbox(frame, from_=1, to=100, textvariable=self.quick_iterations_var,
                        width=6, validate="key", validatecommand=iterations_vcmd).pack(
                side="left", padx=(6, 20))
            ttk.Label(frame, text=T("quick.field_width")).pack(side="left")
            width_vcmd = (self.register(self._validate_quick_width_spinbox), "%P")
            ttk.Spinbox(frame, from_=1, to=1000, textvariable=self.quick_explore_width_var,
                        width=6, validate="key", validatecommand=width_vcmd).pack(
                side="left", padx=(6, 4))
            ttk.Button(frame, text=T("quick.auto_button"),
                       command=lambda: self._on_quick_auto_width_clicked(
                           self.quick_explore_width_var)).pack(side="left")
            gap_row = ttk.Frame(outer)
            gap_row.grid(row=1, column=0, sticky="w", pady=(4, 0))
            ttk.Checkbutton(gap_row, text=T("quick.field_fill_gaps_first"),
                             variable=self.quick_floor_fill_gaps_var).pack(side="left")
            mode_frames["explore"] = outer

        def _build_quick_mode_primesieve(self, container, mode_frames):
            """Floor + From + Width -- NOT the From/To pair the first version of this mode
            used. From is a literal absolute starting point (like Floor mode's own
            "Starting point" field), and Width is a multiplier of QUICK_GEN_MAX_WINDOW_WIDTH
            (same [1, 1000] spinbox convention as Floor/Exploration mode's Width) that
            replaces having to type a second huge literal number for the end of the range --
            picking a floor deep in the uint64 range and navigating to an arbitrary point
              within it is exactly what this mode is FOR, and typing two 19+ digit numbers by
            hand for every request was real friction that Floor/To-based Range mode doesn't
            have (a floor's own start already anchors one end there).

            Floor is INDEPENDENT of From -- not derived from it the way Floor mode's own
            Floor field is derived from its Starting point (see _on_quick_floor_start_changed)
            -- because this mode's Auto button needs a floor to look up BEFORE a From value
            necessarily exists yet: click Auto with just a Floor typed in, and it fills From
            with wherever that floor's storage currently ends (see
            _on_primesieve_auto_from_clicked), which is the actual point of this layout --
            orienting yourself on a floor that can hold hundreds of billions of windows
            without having to compute a resume point by hand. Generation itself derives its
            real target floor from From alone (via _quick_gen_plan_literal_range ->
            digit_count_floor), same as Floor mode's own starting-point flow -- the Floor
            field here is a lookup convenience for Auto, not fed back into the request.

            The attribution label is ALWAYS visible while this mode is selected, not just
            mentioned in a hint or code comment -- this mode calls directly into a
            third-party library (libprimesieve, by Kim Walisch) with no engine of ours in
            between, and that should be visible to whoever clicks Generate, not just to
            whoever reads the source."""
            frame = ttk.Frame(container)
            frame.grid(row=0, column=0, sticky="w")
            row1 = ttk.Frame(frame)
            row1.pack(anchor="w")
            ttk.Label(row1, text=T("quick.field_floor")).pack(side="left")
            ttk.Entry(row1, textvariable=self.quick_primesieve_floor_var, width=10).pack(
                side="left", padx=(6, 20))
            ttk.Label(row1, text=T("quick.field_from")).pack(side="left")
            ttk.Entry(row1, textvariable=self.quick_primesieve_from_var, width=24).pack(
                side="left", padx=(6, 4))
            ttk.Button(row1, text=T("quick.auto_button"),
                       command=self._on_primesieve_auto_from_clicked).pack(
                side="left", padx=(0, 20))
            ttk.Label(row1, text=T("quick.field_width")).pack(side="left")
            width_vcmd = (self.register(self._validate_primesieve_width_spinbox), "%P")
            ttk.Spinbox(row1, from_=1, to=PRIMESIEVE_MAX_WIDTH_MULT,
                        textvariable=self.quick_primesieve_width_var,
                        width=14, validate="key", validatecommand=width_vcmd).pack(
                side="left", padx=(6, 0))
            ttk.Label(frame, text=T("quick.attribution_primesieve"), foreground="#777777",
                      font=("TkDefaultFont", 8), wraplength=860, justify="left").pack(
                anchor="w", pady=(4, 0))
            mode_frames["primesieve"] = frame

        def _on_primesieve_auto_from_clicked(self):
            """primesieve mode's OWN Auto button -- unlike every other mode's Auto (RAM-
            based window-count suggestion, see _on_quick_auto_width_clicked), this one fills
            the From field with wherever the given Floor's storage currently ends (0 if
            nothing is there yet), computed the exact same way find_continuation_target_idx
            already does for every other mode's own continuation logic. This is the whole
            point of splitting Floor out from From (see _build_quick_mode_primesieve's
            docstring): a floor this deep can hold hundreds of billions of windows, so
              "where does my data actually stop on floor N" is not something to work out by
            hand."""
            raw_floor = self.quick_primesieve_floor_var.get().strip()
            floor_value = _eval_quick_number(raw_floor)
            if not raw_floor or floor_value is None or floor_value < 0:
                messagebox.showerror(T("quick.dialog_title"), T("quick.error_floor_required"))
                return
            existing_count = find_continuation_target_idx(
                PORTAL_FOLDER, floor_value, QUICK_GEN_MAX_WINDOW_WIDTH)
            if floor_value < LOW_FLOOR_CUTOFF:
                # A low floor is AT MOST one combined window wide, ever (see
                # LOW_FLOOR_CUTOFF) -- existing_count>=1 means it (and every other floor
                # 0-6) is already fully generated, not "add one more window" the way the
                # formula below would wrongly compute (10**floor + 10M lands in the NEXT
                # floor's own territory, not a meaningful continuation point here).
                continuation_point = 10 ** floor_value
                self.quick_primesieve_from_var.set(str(continuation_point))
                if existing_count >= 1:
                    messagebox.showinfo(T("quick.dialog_title"), T(
                        "quick.primesieve_auto_from_low_floor_done", floor=floor_value))
                else:
                    messagebox.showinfo(T("quick.dialog_title"), T(
                        "quick.primesieve_auto_from_low_floor_result", floor=floor_value))
                return
            continuation_point = 10 ** floor_value + existing_count * QUICK_GEN_MAX_WINDOW_WIDTH
            self.quick_primesieve_from_var.set(str(continuation_point))
            # existing_count above is a CONTINUATION POSITION (see
            # find_continuation_target_idx()'s own docstring), not necessarily the real
            # file count once a floor has interior gaps -- the message shows the real
            # count instead (see count_existing_windows()'s own docstring for why).
            real_window_count = count_existing_windows(PORTAL_FOLDER, floor_value)
            messagebox.showinfo(T("quick.dialog_title"), T(
                "quick.primesieve_auto_from_result", floor=floor_value,
                existing_count=real_window_count, continuation_point=f"{continuation_point:,}"))

        def _on_explore_auto_floor_clicked(self):
            """Exploration mode's OWN Floor-Auto button -- fills quick_explore_floor_var
            with find_highest_populated_floor()'s result, the SAME value leaving Floor
            blank and clicking Generate directly already resolves to (see
            _on_quick_generate_clicked's "explore" branch). This button exists purely for
            discoverability: an empty text field as the trigger for "auto-continue the
            deepest floor" turned out to be easy to miss in practice (a person testing this
            mode typed an explicit "0" rather than clearing the field, which is a
            perfectly legitimate floor to request -- see this mode's own docstring for why
            that's NOT the same thing as leaving it blank) -- a labeled button matches
            every other Quick-gen mode's own Auto convention instead of relying on an
            invisible one.

            Unlike _on_quick_auto_width_clicked (shared, RAM-based, targets a Width field)
            and _on_primesieve_auto_from_clicked (fills a From field given an ALREADY-KNOWN
            Floor), this button determines the Floor itself from scratch by scanning the
            whole database -- there is no floor to read from the UI first."""
            highest = find_highest_populated_floor(PORTAL_FOLDER)
            if highest is None:
                messagebox.showinfo(
                    T("quick.dialog_title"), T("quick.explore_auto_floor_empty"))
                return
            self.quick_explore_floor_var.set(str(highest))

        def _validate_quick_iterations_spinbox(self, proposed):
            """validatecommand for the Number of iterations spinbox -- same shape as
            _validate_quick_width_spinbox, bounded to [1, 100] (100 x 10 bln = 1 trillion
            upper bound)."""
            if proposed == "":
                return True
            return proposed.isdigit() and 1 <= int(proposed) <= 100

        def _on_quick_auto_width_clicked(self, width_var):
            """Auto button handler, shared by every mode's button (see
            _build_quick_mode_floor/_build_quick_mode_explore/_build_quick_mode_range).
            Queries available RAM INSIDE WSL (estimate_wsl_available_ram_bytes -- the
            sieve itself runs there, not in this native Windows process) and turns it
            into a recommended window count (recommended_max_windows -- see that
            function's docstring for exactly what it is and isn't accounting for).

            width_var is the Width spinbox's StringVar to fill in directly (Floor/
            Exploration modes); pass None for Range mode, which has no window-count
            field to fill -- there the recommendation is only reported via the dialog,
            for the person to factor into their own From/To choice."""
            available = estimate_wsl_available_ram_bytes()
            if available is None:
                messagebox.showerror(T("quick.dialog_title"), T("quick.error_ram_probe_failed"))
                return
            recommended = recommended_max_windows(available)
            numbers_total = recommended * QUICK_GEN_MAX_WINDOW_WIDTH
            if width_var is not None:
                width_var.set(str(recommended))
            messagebox.showinfo(T("quick.dialog_title"), T(
                "quick.auto_ram_result", available_gb=f"{available / 1e9:.1f}",
                recommended=f"{recommended:,}", numbers_total=f"{numbers_total:,}"))

        def _on_workers_auto_clicked(self):
            """Auto button handler for the "workers" field in the loop pipeline's
            advanced form (see _build_generation_tab's own comment above the button)
            -- the CPU-count counterpart to _on_quick_auto_width_clicked's RAM-based
            window-count suggestion above. Queries the CPU count INSIDE WSL
            (estimate_wsl_available_cpu_count -- the sieve's worker processes run
            there, not in this native Windows process) and fills the "workers" field
            with the recommendation (recommended_worker_count -- simply the detected
            count itself, since requesting more workers than available CPUs adds
            scheduling overhead without adding real parallelism).

            This only ever SUGGESTS a value into the field -- like every other field
            in this advanced form, "workers" stays a plain, freely-editable Entry
            afterward (the person can still type anything from 1 up to, or beyond,
            the detected count; nothing here enforces a hard ceiling on typing, same
            as window_count_per_run's own field right above it)."""
            available = estimate_wsl_available_cpu_count()
            if available is None:
                messagebox.showerror(T("quick.dialog_title"), T("gen.error_cpu_probe_failed"))
                return
            recommended = recommended_worker_count(available)
            self._loop_vars["workers"].set(str(recommended))
            messagebox.showinfo(T("quick.dialog_title"), T(
                "gen.auto_cpu_result", available=available, recommended=recommended))

        def _sync_quick_panel(self, panel):
            """tkraise() only reorders stacking within the shared grid cell -- it does
            NOT clip a sibling frame's own size. Since the "floor" sub-frame
            (Floor+Width+Starting point) is wider than "range" (From+To), raising
            "range" on top would still leave "floor"'s trailing Starting point label/
            entry visible past range's right edge. grid_remove()/grid() actually pulls
            the inactive frames out of the layout instead of just moving them behind.

            Operates on a single panel's mode_frames -- called for every entry in
            self._quick_panels so the embedded panel and any open detached copy switch
            mode together (they share quick_mode_var, but each has its OWN frame
            widgets, so each needs this applied individually)."""
            mode = self.quick_mode_var.get()
            for name, frame in panel["mode_frames"].items():
                if name == mode:
                    frame.grid(row=0, column=0, sticky="w")
                else:
                    frame.grid_remove()

        def _on_quick_mode_changed(self):
            for panel in self._quick_panels:
                self._sync_quick_panel(panel)
            hints = {
                "floor": T("quick.hint_floor"),
                "range": T("quick.hint_range"),
                "explore": T("quick.hint_explore"),
                "primesieve": T("quick.hint_primesieve"),
            }
            self.quick_hint_var.set(hints.get(self.quick_mode_var.get(), ""))

        def _build_detached_quick_panel(self, parent):
            """extra_controls_builder callback for self.loop_console (see
            GenerationConsole.open_detached) -- builds a second, independent copy of the
            Quick-gen panel inside the detached console window, so a run can be started
            from there without switching back to the main window. Wrapped in its own
            Labelframe to visually separate it from the mirrored console output below.

            Returns a cleanup closure that GenerationConsole invokes when the detached
            window closes, removing this copy from self._quick_panels so later
            mode/state-sync loops don't touch destroyed widgets."""
            outer = ttk.Labelframe(parent, text=T("quick.section_title"))
            outer.pack(fill="x", padx=8, pady=(8, 0))
            panel = self._build_quick_generation_panel(outer)

            def _cleanup():
                if panel in self._quick_panels:
                    self._quick_panels.remove(panel)

            return _cleanup

        def _on_quick_generate_or_stop_clicked(self):
            """Dual-function dispatch for the Quick-gen 'Generate' button: while a
            pipeline run is in flight, this button IS the stop control
            (its label already reads Stop -- see _on_run_loop); otherwise it's the
            normal generate path. Checked the same way _on_quick_generate_clicked already
            guards against double-launch (self._loop_runner.is_running())."""
            if self._loop_runner is not None and self._loop_runner.is_running():
                self._on_stop_loop()
            else:
                self._on_quick_generate_clicked()

        def _apply_loop_params_and_run(self, base_exponent, run_count, window_count_per_run):
            """Writes the computed low-level parameters into the EXISTING orchestrator_
            loop_v2 form fields (self._loop_vars) and fires the same launch path the
            low-level "Run" button uses (_on_run_loop) -- reuses its validation,
            settings-persistence, WslLoggedRunner wiring and live-output panel verbatim
            instead of duplicating any of it (the log pane right below this panel is
            where the real output shows up). n_instances/write_files/
            compute_sieving_primes_count/workers/batches_per_worker/window_m are left
            exactly as they already are in the low-level form -- the app translates the
            quick-gen inputs into width/window-count in the form below, but quick-gen
            only ever decides base_exponent/run_count/window_count_per_run, nothing
            else."""
            self._loop_vars["base_exponent"].set(str(base_exponent))
            self._loop_vars["run_count"].set(str(run_count))
            self._loop_vars["window_count_per_run"].set(str(window_count_per_run))
            self._on_run_loop()

        def _apply_primesieve_params_and_run(self, base_exponent, target_idx_start,
                                              window_count_per_run):
            """Quick-gen 'primesieve' mode's counterpart to _apply_loop_params_and_run() --
            this engine has no low-level form of its own (see prime_sieve_primesieve.py's
            simpler CLI, module header), so there are no self._loop_vars-equivalent fields
            to round-trip through first; the three values already fully determine the WSL
            command (see build_primesieve_argv/_on_run_primesieve). write_files is still
            read from the SAME checkbox the low-level orchestrator form uses
            (self._loop_write_files_var) -- one general "write files vs. count-only
            diagnostic" concept shared across every engine this app can launch, not
            something specific to orchestrator_loop_v2.py."""
            self._on_run_primesieve(base_exponent, target_idx_start, window_count_per_run)

        def _on_run_primesieve(self, base_exponent, target_idx_start, window_count_per_run):
            """Launch path for prime_sieve_primesieve.py -- deliberately reuses the SAME
            self._loop_runner/self._loop_output_queue/self.loop_console/self.loop_run_btn/
            self.loop_stop_btn/self.loop_status_label/_poll_loop_output/_on_loop_finished
            plumbing _on_run_loop() uses, rather than a separate runner+console+queue
            triple: only one Generation run can be in flight at a time regardless of which
            engine it uses (_on_quick_generate_or_stop_clicked already guards on
            self._loop_runner.is_running() for exactly this reason), and the live-output
            console/Stop control/tree-refresh-on-finish behavior are all engine-agnostic --
            duplicating that machinery for one more script would only add a second place
            every future change to it has to be made twice."""
            if self._loop_runner is not None and self._loop_runner.is_running():
                return
            write_files = self._loop_write_files_var.get()
            argv = build_primesieve_argv(
                base_exponent, target_idx_start, window_count_per_run,
                QUICK_GEN_MAX_WINDOW_WIDTH, write_files)
            log_path, exit_path, _run_id = generation_log_paths(PORTAL_FOLDER, "primesieve")
            cmd = build_wsl_logged_command(argv, log_path, exit_path)

            self.loop_console.append(self._new_run_separator())
            self._loop_output_queue = queue.Queue()
            self._loop_runner = WslLoggedRunner(
                cmd, log_path, exit_path, self._loop_output_queue,
                kill_pattern="prime_sieve_primesieve.py")
            self._loop_runner.start()
            self.loop_run_btn.configure(state="disabled")
            self.loop_stop_btn.configure(state="normal")
            self.loop_status_label.set(T("common.running"))
            for panel in self._quick_panels:
                panel["generate_btn"].configure(text=T("common.stop"))
            self._show_loop_terminal()

        def _apply_orchestrator_direct_params_and_run(self, base_exponent, target_idx_start,
                                                        window_count_per_run):
            """Fallback counterpart to _apply_primesieve_params_and_run() for
            _offer_generate_missing_prime_window(), used only when the requested window
            falls beyond libprimesieve's own uint64 ceiling (PRIMESIEVE_MAX_STOP) -- see
            build_orchestrator_direct_argv()'s own docstring for why orchestrator_v3.py
            itself (not its loop wrapper) is the right engine there. Reads
            write_files/compute_sieving_primes_count from the same low-level form fields
            primesieve mode and the main 'Uruchom' button already use
            (self._loop_write_files_var/self._loop_count_sieving_var), and
            workers/batches_per_worker from self._loop_vars with a safe fallback of 1 each
            if that form hasn't been touched/validated yet -- unlike _on_run_loop()'s own
            validation, this call site must never block a search-triggered generation on
            an unrelated low-level field being blank or malformed."""
            self._on_run_orchestrator_direct(base_exponent, target_idx_start, window_count_per_run)

        def _on_run_orchestrator_direct(self, base_exponent, target_idx_start, window_count_per_run):
            """Launch path for orchestrator_v3.py run DIRECTLY (see
            build_orchestrator_direct_argv()) -- reuses the exact same
            self._loop_runner/self._loop_output_queue/self.loop_console/... plumbing
            _on_run_loop()/_on_run_primesieve() both already use, for the same
            one-runner-at-a-time reasoning _on_run_primesieve()'s own docstring gives."""
            if self._loop_runner is not None and self._loop_runner.is_running():
                return
            write_files = self._loop_write_files_var.get()
            compute_sieving = self._loop_count_sieving_var.get()

            def _positive_int_or(key, default):
                raw = self._loop_vars[key].get().strip()
                return int(raw) if raw.isdigit() and int(raw) > 0 else default

            workers = _positive_int_or("workers", 1)
            batches_per_worker = _positive_int_or("batches_per_worker", 1)
            argv = build_orchestrator_direct_argv(
                base_exponent, target_idx_start, window_count_per_run,
                QUICK_GEN_MAX_WINDOW_WIDTH, write_files, compute_sieving,
                workers, batches_per_worker)
            log_path, exit_path, _run_id = generation_log_paths(PORTAL_FOLDER, "orchdirect")
            cmd = build_wsl_logged_command(argv, log_path, exit_path)

            self.loop_console.append(self._new_run_separator())
            self._loop_output_queue = queue.Queue()
            self._loop_runner = WslLoggedRunner(
                cmd, log_path, exit_path, self._loop_output_queue,
                kill_pattern="orchestrator_v3.py")
            self._loop_runner.start()
            self.loop_run_btn.configure(state="disabled")
            self.loop_stop_btn.configure(state="normal")
            self.loop_status_label.set(T("common.running"))
            for panel in self._quick_panels:
                panel["generate_btn"].configure(text=T("common.stop"))
            self._show_loop_terminal()

        def _try_fill_quick_gen_gap(self, floor_value, existing_count, width_mult):
            """Shared "fill gaps first" check for Floor mode's blank-starting-point path
            AND Exploration mode (see quick_floor_fill_gaps_var's own comment in
            _init_quick_generation_state -- the SAME toggle/variable drives both; added to
            Exploration 2026-08-18, at Artur's request, to match Floor mode's own
            behavior exactly ("tak jak tylko piętro")). Only changes anything when
            floor_value genuinely HAS a gap: find_first_gap_target_idx() returns the exact
            same value as existing_count (find_continuation_target_idx()) otherwise, so
            the "no gap" case returns False and callers fall straight through to their own
            normal continue-from-highest logic, unchanged. Returns True (and has ALREADY
            launched something + set quick_status_var) if a gap was found and filled;
            False otherwise -- callers should `return` immediately on True, exactly like
            any other terminal branch in _on_quick_generate_clicked.

            Deliberately launches at most width_mult windows into the gap -- ONE
            iteration's worth, never more, even from Exploration mode's own multi-
            iteration call site (which has no equivalent single-shot cap otherwise).
            Exploration's normal (non-gap) launches go through orchestrator_loop_v2.py
            specifically so each subprocess's own batch gets a bounded window_count_per_run
            -- orchestrator_v3.py's own batch_size is simply set equal to whatever
            window_count it receives (see that file's main(), batch_size = window_count),
            with NO internal chunking of its own. Collapsing gap-filling into one direct
            _launch_direct_window_range() call sized at iterations*width_mult instead of
            just width_mult would silently hand a single subprocess a batch far larger
            than Exploration's own Iterations field was ever meant to allow through in one
            step, reintroducing exactly the per-batch RAM risk multi-iteration launches
            exist to avoid (see [[feedback_ram_budget_round_down]]-style reasoning: prefer
            under-filling a wide gap over one oversized launch). A gap wider than
            width_mult is filled incrementally instead -- click by click, or automatically
            over repeated blank-Floor auto-detect passes -- using the same
            quick.note_gap_partial the caller already surfaces for this."""
            if not self.quick_floor_fill_gaps_var.get():
                return False
            gap_target_idx = find_first_gap_target_idx(
                PORTAL_FOLDER, floor_value, QUICK_GEN_MAX_WINDOW_WIDTH)
            if gap_target_idx >= existing_count:
                return False
            floor_window_count = _floor_window_count(floor_value)
            gap_remaining = floor_window_count - gap_target_idx
            capped_width = min(width_mult, gap_remaining)
            reaches_existing = gap_target_idx + capped_width >= existing_count
            gap_start = 10 ** floor_value + gap_target_idx * QUICK_GEN_MAX_WINDOW_WIDTH
            self.quick_status_var.set(T(
                "quick.summary_floor_fill_gap", floor=floor_value,
                width_mult=capped_width,
                width_total=f"{capped_width * QUICK_GEN_MAX_WINDOW_WIDTH:,}",
                gap_start=f"{gap_start:,}",
                existing_count=count_existing_windows(PORTAL_FOLDER, floor_value),
                added_count=capped_width)
                + (T("quick.note_gap_partial") if not reaches_existing else ""))
            # _launch_direct_window_range() (not _apply_loop_params_and_run()) since this
            # is a literal target_idx -- it also trims any edge overlap with what's
            # already on disk, though none is expected here since gap_target_idx is by
            # definition the first MISSING window.
            self._launch_direct_window_range(floor_value, gap_target_idx, capped_width)
            return True

        def _launch_direct_window_range(self, floor, target_idx_start, window_count):
            """Shared dispatch for every caller that already knows its own literal
            [target_idx_start, target_idx_start + window_count) target (Range mode, Floor
            mode with a starting point, Goldbach's 'generate missing range' offer -- see
            _quick_gen_plan_literal_range()'s own docstring for how that target_idx_start
            is computed) -- writes starting EXACTLY there, never backfilling anything
            before it, unlike orchestrator_loop_v2.py's own continuation-only wrapper
            (build_loop_argv()), which has no notion of an arbitrary start position at
            all. Picks whichever engine can actually reach that magnitude: primesieve
            mode if the whole requested range still fits under libprimesieve's own uint64
            ceiling (PRIMESIEVE_MAX_STOP), else orchestrator_v3.py launched directly (see
            build_orchestrator_direct_argv()'s own docstring) -- the exact same
            ceiling-aware choice _offer_generate_missing_prime_window() already makes for
            the search flow's own missing-fragment offer.

            Trims against what's ALREADY on disk first (see
            _trim_existing_from_target_idx_range()'s own docstring) -- every engine this
            app can launch overwrites unconditionally with no existence check of its own,
            so this is the one place that avoids redundantly re-sieving/rewriting windows
            the caller's own request happens to overlap."""
            trimmed_start, trimmed_count = _trim_existing_from_target_idx_range(
                PORTAL_FOLDER, floor, target_idx_start, window_count, QUICK_GEN_MAX_WINDOW_WIDTH)
            if trimmed_count <= 0:
                self.quick_status_var.set(T("quick.status_range_fully_covered"))
                return
            range_end_abs = 10 ** floor + (trimmed_start + trimmed_count) * QUICK_GEN_MAX_WINDOW_WIDTH
            if range_end_abs - 1 > PRIMESIEVE_MAX_STOP:
                self._apply_orchestrator_direct_params_and_run(floor, trimmed_start, trimmed_count)
            else:
                self._apply_primesieve_params_and_run(floor, trimmed_start, trimmed_count)

        def _quick_gen_plan_literal_range(self, start, end, max_window_count=None):
            """Shared by Range mode and Floor mode WITH a starting point set (see
            _on_quick_generate_clicked): given a literal [start, end) target, rounds it
            out to whole QUICK_GEN_MAX_WINDOW_WIDTH windows, CLAMPS it to the starting
            floor's own boundary if it would otherwise cross into the next floor (see the
            "truncated" note below), rejects it if it can't be grid-aligned even after
            rounding/clamping (only affects very low floors), and checks it against
            find_continuation_target_idx -- i.e. against what's ACTUALLY on disk --
            instead of just handing window_count_per_run to orchestrator_loop_v2's own
            continuation-only engine and hoping it lines up with what was asked for. That
            mismatch used to be a real bug for Floor mode: a starting point picked WHICH
            floor to generate (via digit_count_floor) but was otherwise silently ignored
            -- generation always just continued from wherever that floor's storage
            already ended, even if the requested range was already fully covered. This
            makes both modes report "already in storage" instead of launching a
            redundant run in that case, and generate only the missing gap otherwise --
            never anything outside/before what was asked for, consistent with this
            project's established "always round up, never trim" philosophy (see
            _round_range_to_window) -- EXCEPT at the far end, where "never trim" would
            mean silently spilling numbers from the NEXT floor into this one's folder
            (see the floor-7-with-130M-numbers bug this was written to fix). The floor
            boundary is the one edge this function always trims TO rather than rounds
            past.

            CLAMPING NOTE: a requested end past the starting floor's own boundary
            (10**(floor_lo+1)) gets silently pulled back to that boundary -- e.g. asking
            for floor 7 with a width that would reach into floor 8's numbers instead
            stops at floor 7's last window, and whatever was asked for beyond that is
            simply dropped, never generated under this call. This mirrors exactly what a
            low floor's own single-window cap already does (see LOW_FLOOR_CUTOFF) --
            every floor, low or high, now has a firm upper edge this function will not
            cross. Deliberately GUI-side, not backend: main_batch_scanner itself has no
            opinion on where a floor ends for base_power >= LOW_FLOOR_CUTOFF (it just
            writes whatever combined range it's given under the requested folder), so the
            caller choosing window_count_per_run is what has to stay inside the lines.
            Exploration mode is NOT routed through this function and is NOT capped this
            way on purpose -- marching across floor boundaries and picking up wherever
            the next floor needs filling is that mode's whole point, not a bug to guard
            against (see _on_quick_generate_clicked's explore branch).

            Returns a dict:
              {"error": (title, message)}                          -- invalid request,
                                                                        show it and stop
              {"already": True, "rounded_start", "rounded_end",
               "existing_count", "truncated"}                       -- fully covered
                                                                        already
              {"floor", "existing_count", "window_count_per_run",
               "rounded_start", "rounded_end", "truncated"}          -- what to launch
            "truncated" is True whenever the requested end got clamped back to the
            floor's own boundary -- callers should mention that in their status message
            so a shortened run isn't mistaken for the full request having been honored.

            LAUNCH START (added 2026-08-18, at Artur's request): "target_idx_start" in
            the launch-case dict is max(the request's OWN literal target_idx, existing_
            count) -- never less than the literal request (so a starting point picked
            deep into an otherwise-empty floor no longer silently balloons into
            backfilling everything from index 0 up to it, which used to both misrepresent
            what was asked for AND crash prime_sieve_v4_1.py outright for a big enough gap
            -- MemoryError building a target_idx Python list hundreds of quadrillions of
            entries long, a real run on floor 25 hit exactly this), and never less than
            existing_count either (so the ordinary case -- filling from at/near the front
            of an already-partially-generated floor -- is untouched: this reduces to
            exactly today's existing_count-based start when the request doesn't reach
            past it). window_count_per_run is sized to this SAME start, so it only ever
            covers what's actually still missing from [target_idx_start, target_idx_end)
            -- never more. Callers should launch via a target_idx_start-CAPABLE engine
            (see _launch_direct_window_range()), not orchestrator_loop_v2.py's own
            continuation-only wrapper, which has no way to honor a start past wherever
            storage currently ends.

            max_window_count (added 2026-08-18, at Artur's request, after a real floor-25
            run logged "target_idx X..X+1000 (1001 windows)" for a Width=1000 request):
            _round_range_to_window() rounds the START down AND the END up to the nearest
            window boundary -- deliberate for Range mode's own from/to contract ("never
            fall short of what was literally asked for", see that function's docstring),
            but wrong for a caller like Floor mode's Starting-point path, where Width is
            an explicit WINDOW-COUNT BUDGET, not a literal end number: whenever the typed
            starting point isn't itself a multiple of QUICK_GEN_MAX_WINDOW_WIDTH (the
            common case for a search-driven starting point), rounding BOTH ends outward
            silently adds exactly one extra window beyond the requested count -- a
            correctness bug on its own (the launched run no longer matches what the
            summary message told the person it would do), and specifically the wrong
            direction for a RAM-budgeted launch, where the safer failure mode is covering
            slightly less than asked (at most one window's width short at the tail) rather
            than more. Callers that pass a window-count budget here (Floor mode's
            Starting-point path; NOT Range mode, which has no count concept, only the
            literal from/to numbers themselves) should pass their own width_mult as
            max_window_count -- this clamps target_idx_end (and, consequently,
            window_count_per_run) to never exceed literal_target_idx_start +
            max_window_count, on top of whatever the floor-boundary clamp above already
            did (whichever constraint is tighter wins; if the floor boundary already cut
            target_idx_end down at or below the budget, this is a no-op). Sets
            "width_capped" in the returned dict so callers can surface a distinct note --
            deliberately NOT folded into "truncated" (that flag/note is specifically about
            the floor-boundary reason and would misdescribe this one)."""
            rounded_start, rounded_end = _round_range_to_window(start, end)
            floor_lo = digit_count_floor(rounded_start)
            floor_boundary = 10 ** (floor_lo + 1)
            truncated = rounded_end > floor_boundary
            if truncated:
                rounded_end = floor_boundary
            base = 10 ** floor_lo
            if ((rounded_start - base) % QUICK_GEN_MAX_WINDOW_WIDTH
                    or (rounded_end - base) % QUICK_GEN_MAX_WINDOW_WIDTH):
                return {"error": (T("quick.dialog_title"), T("quick.error_range_misaligned"))}
            literal_target_idx_start = (rounded_start - base) // QUICK_GEN_MAX_WINDOW_WIDTH
            target_idx_end = (rounded_end - base) // QUICK_GEN_MAX_WINDOW_WIDTH
            width_capped = False
            if max_window_count is not None:
                budget_target_idx_end = literal_target_idx_start + max_window_count
                if budget_target_idx_end < target_idx_end:
                    target_idx_end = budget_target_idx_end
                    rounded_end = base + target_idx_end * QUICK_GEN_MAX_WINDOW_WIDTH
                    width_capped = True
            existing_count = find_continuation_target_idx(
                PORTAL_FOLDER, floor_lo, QUICK_GEN_MAX_WINDOW_WIDTH)
            # existing_count above is a CONTINUATION POSITION, not necessarily the real
            # file count on a floor with interior gaps -- real_existing_count is for
            # DISPLAY only (see count_existing_windows()'s own docstring); every caller's
            # own arithmetic must keep using existing_count/target_idx_start.
            real_existing_count = count_existing_windows(PORTAL_FOLDER, floor_lo)
            if target_idx_end <= existing_count:
                return {"already": True, "rounded_start": rounded_start,
                        "rounded_end": rounded_end, "existing_count": existing_count,
                        "real_existing_count": real_existing_count,
                        "truncated": truncated, "width_capped": width_capped}
            launch_target_idx_start = max(literal_target_idx_start, existing_count)
            return {"floor": floor_lo, "existing_count": existing_count,
                     "real_existing_count": real_existing_count,
                     "target_idx_start": launch_target_idx_start,
                     "window_count_per_run": target_idx_end - launch_target_idx_start,
                     "rounded_start": rounded_start, "rounded_end": rounded_end,
                     "truncated": truncated, "width_capped": width_capped}

        def _on_quick_generate_clicked(self):
            """Real launch path: computes base_exponent/run_count/
            window_count_per_run for whichever mode is selected and hands them to
            _apply_loop_params_and_run().

            Floor only: blank starting point is pure "add N more windows to this
            floor" (orchestrator_loop_v2's own continuation-only behavior -- always
            either right after the highest existing window, or target_idx=0 if nothing
            exists yet). A starting point given, though, now means a literal target --
            handled by _quick_gen_plan_literal_range exactly like Range mode, so it can
            report "already in storage" instead of silently generating past what was
            actually asked for.

            Range -- from/to and Exploration (via its own Width field, same meaning as
            Floor only's) both go through _quick_gen_plan_literal_range /
            find_continuation_target_idx too -- see that method's docstring."""
            if self._loop_runner is not None and self._loop_runner.is_running():
                messagebox.showerror(T("quick.dialog_title"), T("quick.error_already_running"))
                return
            mode = self.quick_mode_var.get()
            if mode == "floor":
                raw_floor = self.quick_floor_var.get().strip()
                floor_value = _eval_quick_number(raw_floor)
                if floor_value is None or floor_value < 0:
                    messagebox.showerror(T("quick.dialog_title"), T("quick.error_floor_required"))
                    return
                width_mult = _eval_quick_number(self.quick_floor_width_var.get()) or 1
                width_total = width_mult * QUICK_GEN_MAX_WINDOW_WIDTH
                raw_start = self.quick_floor_start_var.get().strip()
                start_value = _eval_quick_number(raw_start)
                if start_value is not None:
                    # max_window_count=width_mult -- Width here is an explicit window-COUNT
                    # budget (unlike Range mode's raw from/to, which has no count concept
                    # and is left uncapped, see _quick_gen_plan_literal_range's own
                    # docstring) -- without this, a starting point that isn't itself a
                    # multiple of QUICK_GEN_MAX_WINDOW_WIDTH (the common case for a
                    # search-driven starting point) silently launches ONE MORE window than
                    # Width says, exactly the "1001 windows for a Width=1000 request" bug a
                    # real floor-25 run hit.
                    plan = self._quick_gen_plan_literal_range(
                        start_value, start_value + width_total, max_window_count=width_mult)
                    if plan.get("error"):
                        messagebox.showerror(*plan["error"])
                        return
                    if plan.get("already"):
                        self.quick_status_var.set(T(
                            "quick.status_already_in_storage",
                            rounded_start=f"{plan['rounded_start']:,}",
                            rounded_end=f"{plan['rounded_end']:,}",
                            existing_count=plan["real_existing_count"]))
                        return
                    self.quick_status_var.set(T(
                        "quick.summary_range", start=f"{start_value:,}",
                        end=f"{start_value + width_total:,}",
                        rounded_start=f"{plan['rounded_start']:,}",
                        rounded_end=f"{plan['rounded_end']:,}", floor=plan["floor"],
                        existing_count=plan["real_existing_count"],
                        added_count=plan["window_count_per_run"])
                        + (T("quick.note_truncated_floor_boundary",
                              boundary=f"{plan['rounded_end']:,}")
                           if plan.get("truncated") else "")
                        + (T("quick.note_width_capped_alignment")
                           if plan.get("width_capped") else ""))
                    self._launch_direct_window_range(
                        plan["floor"], plan["target_idx_start"], plan["window_count_per_run"])
                    return
                existing_count = find_continuation_target_idx(
                    PORTAL_FOLDER, floor_value, QUICK_GEN_MAX_WINDOW_WIDTH)
                if floor_value < LOW_FLOOR_CUTOFF:
                    # A floor below the cutoff (see LOW_FLOOR_CUTOFF's own docstring) is
                    # ALWAYS exactly one window wide at most, never continuable past
                    # target_idx=0 -- treating it like a normal floor here used to let a
                    # blank-starting-point click keep appending another
                    # QUICK_GEN_MAX_WINDOW_WIDTH-sized window (e.g. "..._off_10M.bin")
                    # onto a floor whose real numeric domain is only a few thousand/million
                    # numbers wide, silently mislabeling a chunk of a HIGHER floor's numbers
                    # as belonging to this one. existing_count >= 1 means the single
                    # low-floor window is already there (written by main_batch_scanner's
                    # low-floor branch, possibly while cascading up from a lower floor's own
                    # request -- see that function's docstring) -- nothing left to do.
                    if existing_count >= 1:
                        rounded_start = 10 ** floor_value
                        rounded_end = rounded_start + QUICK_GEN_MAX_WINDOW_WIDTH
                        self.quick_status_var.set(T(
                            "quick.status_already_in_storage",
                            rounded_start=f"{rounded_start:,}", rounded_end=f"{rounded_end:,}",
                            existing_count=existing_count))
                        return
                    self.quick_status_var.set(T(
                        "quick.summary_floor", floor=floor_value, width_mult=1,
                        width_total=f"{QUICK_GEN_MAX_WINDOW_WIDTH:,}",
                        start=T("quick.start_continue_last"),
                        existing_count=0, added_count=1))
                    self._apply_loop_params_and_run(floor_value, 1, 1)
                    return
                # Floor >= LOW_FLOOR_CUTOFF: cap window_count_per_run so target_idx never
                # crosses into the NEXT floor's own numeric range -- see
                # _floor_window_count's docstring for the bug this closes (floor 7 ending
                # up with 130-million-range numbers filed under its folder because nothing
                # here checked where floor 7 actually ends).
                floor_window_count = _floor_window_count(floor_value)
                if self._try_fill_quick_gen_gap(floor_value, existing_count, width_mult):
                    return
                remaining = floor_window_count - existing_count
                if remaining <= 0:
                    self.quick_status_var.set(T(
                        "quick.status_floor_full", floor=floor_value,
                        existing_count=count_existing_windows(PORTAL_FOLDER, floor_value),
                        floor_window_count=floor_window_count))
                    return
                capped_width = min(width_mult, remaining)
                self.quick_status_var.set(T(
                    "quick.summary_floor", floor=floor_value, width_mult=capped_width,
                    width_total=f"{capped_width * QUICK_GEN_MAX_WINDOW_WIDTH:,}",
                    start=T("quick.start_continue_last"),
                    existing_count=count_existing_windows(PORTAL_FOLDER, floor_value),
                    added_count=capped_width)
                    + (T("quick.note_truncated_floor_boundary",
                          boundary=f"{10 ** (floor_value + 1):,}")
                       if capped_width < width_mult else ""))
                self._apply_loop_params_and_run(floor_value, 1, capped_width)
            elif mode == "range":
                raw_from = self.quick_from_var.get().strip()
                raw_to = self.quick_to_var.get().strip()
                start = _eval_quick_number(raw_from)
                end = _eval_quick_number(raw_to)
                if not raw_from or not raw_to or start is None or end is None:
                    messagebox.showerror(T("quick.dialog_title"), T("quick.error_range_required"))
                    return
                if start < 0:
                    messagebox.showerror(T("quick.dialog_title"), T("quick.error_range_negative"))
                    return
                if start >= end:
                    messagebox.showerror(T("quick.dialog_title"), T("quick.error_range_order"))
                    return
                plan = self._quick_gen_plan_literal_range(start, end)
                if plan.get("error"):
                    messagebox.showerror(*plan["error"])
                    return
                if plan.get("already"):
                    self.quick_status_var.set(T(
                        "quick.status_already_in_storage",
                        rounded_start=f"{plan['rounded_start']:,}",
                        rounded_end=f"{plan['rounded_end']:,}",
                        existing_count=plan["real_existing_count"]))
                    return
                self.quick_status_var.set(T(
                    "quick.summary_range", start=f"{start:,}", end=f"{end:,}",
                    rounded_start=f"{plan['rounded_start']:,}",
                    rounded_end=f"{plan['rounded_end']:,}", floor=plan["floor"],
                    existing_count=plan["real_existing_count"],
                    added_count=plan["window_count_per_run"])
                    + (T("quick.note_truncated_floor_boundary",
                          boundary=f"{plan['rounded_end']:,}")
                       if plan.get("truncated") else ""))
                self._launch_direct_window_range(
                    plan["floor"], plan["target_idx_start"], plan["window_count_per_run"])
            elif mode == "explore":
                raw_floor = self.quick_explore_floor_var.get().strip()
                if raw_floor:
                    floor_value = _eval_quick_number(raw_floor)
                    if floor_value is None or floor_value < 0:
                        messagebox.showerror(
                            T("quick.dialog_title"), T("quick.error_explore_floor_required"))
                        return
                else:
                    # Blank Floor = continue from wherever the deepest generated data in
                    # the WHOLE database currently sits (the highest 10p{N} folder with any
                    # files), re-detected fresh on every click rather than sticky in the
                    # entry field -- so repeatedly pressing Generate with nothing typed
                    # always keeps extending whatever floor is genuinely deepest right now,
                    # even if something else (another Quick-gen run, a restore) advanced
                    # the database in the meantime. See find_highest_populated_floor()'s own
                    # docstring. Falls through to the same "type one yourself" error as
                    # before when literally nothing has been generated anywhere yet -- there
                    # is no floor to continue from in that case.
                    floor_value = find_highest_populated_floor(PORTAL_FOLDER)
                    if floor_value is None:
                        messagebox.showerror(
                            T("quick.dialog_title"), T("quick.error_explore_floor_required"))
                        return
                iterations = _eval_quick_number(self.quick_iterations_var.get()) or 1
                width_mult = _eval_quick_number(self.quick_explore_width_var.get()) or 1
                window_count_per_run = width_mult
                existing_count = find_continuation_target_idx(
                    PORTAL_FOLDER, floor_value, QUICK_GEN_MAX_WINDOW_WIDTH)
                if floor_value < LOW_FLOOR_CUTOFF:
                    # Same low-floor guard as blank-starting-point Floor mode above (see
                    # that branch's comment for the full rationale) -- Exploration is meant
                    # for deep/high floors, but nothing stops someone from picking a low one
                    # here too, and it would hit the exact same "keeps appending
                    # QUICK_GEN_MAX_WINDOW_WIDTH-sized chunks past a floor's real, much
                    # smaller domain" bug otherwise.
                    if existing_count >= 1:
                        # Floors 0-6 are ALREADY fully done -- the one-shot low-floor batch
                        # already ran, whether just now (this click) or in the past --
                        # there is nothing left to explore down here, EVER (LOW_FLOOR_CUTOFF
                        # is a fixed, permanently-capped range, not a moving target). Roll
                        # forward to floor 7 -- the first floor Exploration's real
                        # target_idx-based, uncapped continuation actually applies to -- and
                        # fall through to the SAME launch logic below using the request's
                        # own iterations/width there, instead of just reporting "already in
                        # storage" and stopping dead. Reported via screenshot: Floor=6
                        # (already complete, picked by the Auto button) kept reporting
                        # nothing to do instead of continuing into floor 7+. The Floor field
                        # itself is updated to show "7" too, so what's displayed matches
                        # what actually ran, and a follow-up click (blank or typed) starts
                        # from the right place.
                        floor_value = LOW_FLOOR_CUTOFF
                        self.quick_explore_floor_var.set(str(floor_value))
                        existing_count = find_continuation_target_idx(
                            PORTAL_FOLDER, floor_value, QUICK_GEN_MAX_WINDOW_WIDTH)
                    else:
                        self.quick_status_var.set(T(
                            "quick.summary_explore", floor=floor_value, iterations=1,
                            width_mult=1, iterations_total=f"{QUICK_GEN_MAX_WINDOW_WIDTH:,}",
                            existing_count=0, added_count=1))
                        self._apply_loop_params_and_run(floor_value, 1, 1)
                        return
                # Floor >= LOW_FLOOR_CUTOFF (arrived here directly, or just rolled forward
                # from a completed low-floor batch above): roll forward through however
                # many CONSECUTIVE floors are already full -- the low-floor block above
                # only ever resolves the 0-6 -> 7 jump once, so without this loop, typing
                # (or Auto-detecting) any floor >= 7 that happens to already be complete
                # hit the exact bug reported: Exploration fell straight through to
                # _apply_loop_params_and_run below with no completion check at all (unlike
                # Floor mode's remaining<=0 guard a few branches up), so it kept writing
                # more windows into an ALREADY-COMPLETE floor's folder -- silently filing
                # data that numerically belongs to the NEXT floor under this one's name.
                # Bounded at 1000 advances purely as a runaway-loop guard; floor capacity
                # grows fast enough (see _floor_window_count) that a real run should never
                # get remotely close to that.
                # "Fill gaps first" check BEFORE the roll-forward loop below -- checked
                # again inside the loop too, for every floor it advances THROUGH: a floor
                # Exploration has never personally visited can still have a gap (e.g. a
                # search or Goldbach "generate missing range" offer wrote directly into
                # it), and the roll-forward loop's own "remaining<=0" fullness check
                # only looks at the highest existing file, not interior gaps -- so
                # without this, such a floor would be silently skipped past as "already
                # full" instead of having its gap filled first. See
                # _try_fill_quick_gen_gap()'s own docstring.
                if self._try_fill_quick_gen_gap(floor_value, existing_count, width_mult):
                    return
                floor_window_count = _floor_window_count(floor_value)
                remaining = floor_window_count - existing_count
                advances = 0
                while remaining <= 0 and advances < 1000:
                    floor_value += 1
                    self.quick_explore_floor_var.set(str(floor_value))
                    existing_count = find_continuation_target_idx(
                        PORTAL_FOLDER, floor_value, QUICK_GEN_MAX_WINDOW_WIDTH)
                    if self._try_fill_quick_gen_gap(floor_value, existing_count, width_mult):
                        return
                    floor_window_count = _floor_window_count(floor_value)
                    remaining = floor_window_count - existing_count
                    advances += 1
                if remaining <= 0:
                    self.quick_status_var.set(T(
                        "quick.status_floor_full", floor=floor_value,
                        existing_count=count_existing_windows(PORTAL_FOLDER, floor_value),
                        floor_window_count=floor_window_count))
                    return
                # Same reasoning as Floor mode's capped_width just above: base_exponent is
                # FIXED for an entire orchestrator run (see _apply_loop_params_and_run's own
                # docstring), so a single launch can never itself cross from this floor into
                # the next one -- cap the requested iterations*window_count_per_run down to
                # whatever this floor actually has left, rather than letting it overshoot.
                requested_total = iterations * window_count_per_run
                truncated = requested_total > remaining
                if truncated:
                    if window_count_per_run <= remaining:
                        iterations = max(1, remaining // window_count_per_run)
                    else:
                        window_count_per_run = remaining
                        iterations = 1
                iteration_width = window_count_per_run * QUICK_GEN_MAX_WINDOW_WIDTH
                iterations_total = iterations * iteration_width
                self.quick_status_var.set(T(
                    "quick.summary_explore", floor=floor_value, iterations=iterations,
                    width_mult=window_count_per_run, iterations_total=f"{iterations_total:,}",
                    existing_count=count_existing_windows(PORTAL_FOLDER, floor_value),
                    added_count=iterations * window_count_per_run)
                    + (T("quick.note_truncated_floor_boundary",
                          boundary=f"{10 ** (floor_value + 1):,}")
                       if truncated else ""))
                self._apply_loop_params_and_run(floor_value, iterations, window_count_per_run)
            else:
                # mode == "primesieve": From + Width (NOT From/To -- see
                # _build_quick_mode_primesieve's docstring for why) determine the literal
                # [start, end) target the exact same way Floor mode's own "Starting point"
                # flow does (start_value, start_value + width_total) -- fed into the SAME
                # _quick_gen_plan_literal_range() Range mode uses, PLUS a check against
                # libprimesieve's own uint64 ceiling (PRIMESIEVE_MAX_STOP) -- see that
                # constant's docstring and prime_sieve_primesieve.py's
                # generate_floor_windows() for where the actual clamp happens (backend-side,
                # reading the live library value, not this duplicated GUI-side one). Launches
                # via _apply_primesieve_params_and_run (prime_sieve_primesieve.py) instead of
                # _apply_loop_params_and_run (orchestrator_loop_v2.py).
                raw_from = self.quick_primesieve_from_var.get().strip()
                start = _eval_quick_number(raw_from)
                width_mult = _eval_quick_number(self.quick_primesieve_width_var.get()) or 1
                if not raw_from or start is None:
                    # Blank From with a Floor typed in is NOT an error -- it means the same
                    # thing blank Floor mode's own Starting point does: continue
                    # automatically from wherever this floor's storage currently ends (0,
                    # i.e. the floor's own start, if nothing is there yet). Clicking Auto
                    # first is a convenience to SEE that number before committing, not a
                    # required step -- Generate alone should already do the right thing on
                    # an empty floor, the same way every other mode's blank-continuation
                    # flow does.
                    raw_floor = self.quick_primesieve_floor_var.get().strip()
                    floor_value = _eval_quick_number(raw_floor)
                    if not raw_floor or floor_value is None or floor_value < 0:
                        messagebox.showerror(
                            T("quick.dialog_title"), T("quick.error_primesieve_from_required"))
                        return
                    start = 10 ** floor_value
                    if floor_value >= LOW_FLOOR_CUTOFF:
                        existing_count = find_continuation_target_idx(
                            PORTAL_FOLDER, floor_value, QUICK_GEN_MAX_WINDOW_WIDTH)
                        start = 10 ** floor_value + existing_count * QUICK_GEN_MAX_WINDOW_WIDTH
                    self.quick_primesieve_from_var.set(str(start))
                if start < 0:
                    messagebox.showerror(T("quick.dialog_title"), T("quick.error_range_negative"))
                    return

                # A low floor (see LOW_FLOOR_CUTOFF) is at most ONE combined window wide,
                # ever -- Width is meaningless for it (mirrors Floor mode's own blank-
                # starting-point low-floor branch, which ignores its Width field the same
                # way). Whatever floor `start` actually falls in decides this, not the
                # separate Floor field (which is only a lookup convenience for Auto) --
                # same reasoning Floor mode's own starting-point flow already uses
                # (digit_count_floor(start), not a separately-typed field).
                floor_lo = digit_count_floor(start)
                if floor_lo < LOW_FLOOR_CUTOFF:
                    existing_count = find_continuation_target_idx(
                        PORTAL_FOLDER, floor_lo, QUICK_GEN_MAX_WINDOW_WIDTH)
                    if existing_count >= 1:
                        rounded_start = 10 ** floor_lo
                        rounded_end = rounded_start + QUICK_GEN_MAX_WINDOW_WIDTH
                        self.quick_status_var.set(T(
                            "quick.status_already_in_storage",
                            rounded_start=f"{rounded_start:,}", rounded_end=f"{rounded_end:,}",
                            existing_count=existing_count))
                        return
                    self.quick_status_var.set(T(
                        "quick.summary_floor", floor=floor_lo, width_mult=1,
                        width_total=f"{QUICK_GEN_MAX_WINDOW_WIDTH:,}",
                        start=T("quick.start_continue_last"),
                        existing_count=0, added_count=1))
                    self._apply_primesieve_params_and_run(floor_lo, 0, 1)
                    return

                end = start + width_mult * QUICK_GEN_MAX_WINDOW_WIDTH
                if start > PRIMESIEVE_MAX_STOP:
                    messagebox.showerror(T("quick.dialog_title"), T(
                        "quick.error_primesieve_beyond_ceiling",
                        max_stop=f"{PRIMESIEVE_MAX_STOP:,}"))
                    return
                plan = self._quick_gen_plan_literal_range(start, end)
                if plan.get("error"):
                    messagebox.showerror(*plan["error"])
                    return
                if plan.get("already"):
                    self.quick_status_var.set(T(
                        "quick.status_already_in_storage",
                        rounded_start=f"{plan['rounded_start']:,}",
                        rounded_end=f"{plan['rounded_end']:,}",
                        existing_count=plan["real_existing_count"]))
                    return
                ceiling_truncated = (plan["rounded_end"] - 1) > PRIMESIEVE_MAX_STOP
                self.quick_status_var.set(T(
                    "quick.summary_range", start=f"{start:,}", end=f"{end:,}",
                    rounded_start=f"{plan['rounded_start']:,}",
                    rounded_end=f"{plan['rounded_end']:,}", floor=plan["floor"],
                    existing_count=plan["real_existing_count"],
                    added_count=plan["window_count_per_run"])
                    + (T("quick.note_truncated_floor_boundary",
                          boundary=f"{plan['rounded_end']:,}")
                       if plan.get("truncated") else "")
                    + (T("quick.note_primesieve_ceiling",
                          max_stop=f"{PRIMESIEVE_MAX_STOP:,}")
                       if ceiling_truncated else ""))
                self._apply_primesieve_params_and_run(
                    plan["floor"], plan["target_idx_start"], plan["window_count_per_run"])

        def _collect_loop_settings_from_form(self):
            """Reads + validates every orchestrator_loop_v2 form field. Returns a dict of
            parsed values on success, or None (after a messagebox explaining which field
            is wrong) if anything fails validation -- mirrors the existing "Szukaj"
            fields' isdigit()-based validation pattern elsewhere in this file."""
            # base_exponent (the floor) is the ONE field here allowed to be 0 -- floor 0
            # is [10^0, 10^1) = [1, 10), a legitimate floor (holds 2, 3, 5, 7 among
            # others), not a placeholder/unset value. Every other field genuinely needs
            # to be strictly positive (0 windows/workers/batches/runs/instances doesn't
            # mean anything) -- this used to lump base_exponent in with those and reject
            # it right alongside them, silently making floor 0 impossible to generate.
            zero_allowed_fields = {"base_exponent"}
            int_fields = ("base_exponent", "run_count", "n_instances", "window_count_per_run",
                          "workers", "batches_per_worker", "window_m")
            parsed = {}
            for key in int_fields:
                raw = self._loop_vars[key].get().strip()
                minimum = 0 if key in zero_allowed_fields else 1
                if not raw.isdigit() or int(raw) < minimum:
                    messagebox.showerror(
                        T("gen.dialog_title"), T("gen.error_field_int", field=key))
                    return None
                parsed[key] = int(raw)
            parsed["write_files"] = self._loop_write_files_var.get()
            parsed["compute_sieving_primes_count"] = self._loop_count_sieving_var.get()
            return parsed

        def _on_run_loop(self):
            if self._loop_runner is not None and self._loop_runner.is_running():
                return
            parsed = self._collect_loop_settings_from_form()
            if parsed is None:
                return

            self._generation_settings["loop"] = {
                "base_exponent": str(parsed["base_exponent"]),
                "run_count": str(parsed["run_count"]),
                "n_instances": str(parsed["n_instances"]),
                "write_files": parsed["write_files"],
                "compute_sieving_primes_count": parsed["compute_sieving_primes_count"],
                "window_count_per_run": str(parsed["window_count_per_run"]),
                "workers": str(parsed["workers"]),
                "batches_per_worker": str(parsed["batches_per_worker"]),
                "window_m": str(parsed["window_m"]),
            }
            save_generation_settings(PORTAL_FOLDER, self._generation_settings)

            argv = build_loop_argv(
                parsed["base_exponent"], parsed["run_count"], parsed["n_instances"],
                parsed["write_files"], parsed["compute_sieving_primes_count"],
                parsed["window_count_per_run"], parsed["workers"], parsed["batches_per_worker"],
                parsed["window_m"])
            log_path, exit_path, _run_id = generation_log_paths(PORTAL_FOLDER, "loop")
            cmd = build_wsl_logged_command(argv, log_path, exit_path)

            self.loop_console.append(self._new_run_separator())
            self._loop_output_queue = queue.Queue()
            self._loop_runner = WslLoggedRunner(
                cmd, log_path, exit_path, self._loop_output_queue,
                kill_pattern="orchestrator_loop_v2.py")
            self._loop_runner.start()
            self.loop_run_btn.configure(state="disabled")
            self.loop_stop_btn.configure(state="normal")
            self.loop_status_label.set(T("common.running"))
            # Generate doubles as Stop while this runs (see
            # _on_quick_generate_or_stop_clicked), and the terminal auto-expands the
            # moment a run actually starts -- reset back to normal in
            # _on_loop_finished() once it exits. Looped over every currently-open
            # Quick-gen panel instance (embedded + detached copy, if any).
            for panel in self._quick_panels:
                panel["generate_btn"].configure(text=T("common.stop"))
            self._show_loop_terminal()

        def _on_stop_loop(self):
            if self._loop_runner is not None:
                self._loop_runner.stop()
                self.loop_status_label.set(T("common.stopping"))

        def _on_loop_finished(self):
            """_drain_output_queue's on_exit callback for the loop queue -- resets every
            open Quick-gen panel's 'Generate' button back from its temporary 'Stop'
            label now that nothing is running. Deliberately does NOT touch the console's
            collapse state -- it stays expanded so the final log is still visible after
            the run finishes.

            Also re-runs reload_primes_tree() -- the SAME rebuild the manual Refresh
            button on the Prime numbers tab triggers -- so newly written/regenerated
            windows show up there without the person having to notice the run finished
            and go click Refresh themselves. Previously nothing here touched that tree at
            all, so a completed generation (including a low-floor completion/regeneration
            -- see LOW_FLOOR_CUTOFF) stayed invisible until a manual refresh; this closes
            that gap the same way _set_portal_folder already does after a storage-path
            change."""
            for panel in self._quick_panels:
                panel["generate_btn"].configure(text=T("quick.generate_button"))
            self.reload_primes_tree()

            # A search-triggered "generate the missing window" run (see
            # _offer_generate_missing_prime_window()) just finished -- re-run the SAME
            # search now that the fragment should be on disk. Runs regardless of the
            # exit code: a failed/stopped run just means the re-search comes back empty
            # again, same as any other genuinely-not-found case, rather than needing a
            # separate error path here.
            if self._pending_search_after_prime_gen is not None:
                pending = self._pending_search_after_prime_gen
                self._pending_search_after_prime_gen = None
                self._start_search_job(pending["kind"], pending["base_exponent"], pending["number"])

            # Mirrors the block above, for a Wizualizacja/decompose "generate the
            # missing range" offer instead of a prime/constellation search miss
            # (see _goldbach_offer_generate_missing_range) -- re-queues whichever
            # of the two ops actually reported the gap, now that generation should
            # have filled it. "viz" re-reads n/row-page/od-do fresh from the still-
            # open Toplevel's own entries (_goldbach_queue_viz); "decompose" reuses
            # self._goldbach_decompose_current_n/current_pmax/page, already set by
            # the original _on_goldbach_viz_decompose click and left untouched by
            # the failed attempt (see _goldbach_queue_decompose_page's docstring).
            # Runs regardless of exit code, same reasoning as the prime-window
            # block: a failed/stopped run just means the retry reports the same
            # gap again.
            if self._pending_goldbach_retry_op is not None:
                retry_op = self._pending_goldbach_retry_op
                self._pending_goldbach_retry_op = None
                if retry_op == "viz" and self._goldbach_viz_current_n is not None:
                    self._goldbach_queue_viz(self._goldbach_viz_current_n, reset_page=False)
                elif retry_op == "decompose" and self._goldbach_decompose_current_n is not None:
                    self._goldbach_queue_decompose_page()

        def _poll_loop_output(self):
            self._drain_output_queue(self._loop_output_queue, self.loop_console,
                                      self.loop_run_btn, self.loop_stop_btn, self.loop_status_label,
                                      on_exit=self._on_loop_finished)
            self.after(150, self._poll_loop_output)

        def _on_run_constellation(self):
            if self._const_runner is not None and self._const_runner.is_running():
                return
            base_exponent = self._const_base_exponent_var.get().strip()
            if base_exponent and not base_exponent.isdigit():
                messagebox.showerror(
                    T("gen.dialog_title"), T("gen.error_base_exponent_int"))
                return

            self._generation_settings["constellation"] = {"base_exponent": base_exponent}
            save_generation_settings(PORTAL_FOLDER, self._generation_settings)

            argv = build_constellation_finder_argv(base_exponent if base_exponent else None)
            log_path, exit_path, _run_id = generation_log_paths(PORTAL_FOLDER, "constellation")
            cmd = build_wsl_logged_command(argv, log_path, exit_path)

            self.const_console.append(self._new_run_separator())
            self._const_output_queue = queue.Queue()
            self._const_runner = WslLoggedRunner(
                cmd, log_path, exit_path, self._const_output_queue,
                kill_pattern="constellation_finder_v1.py")
            self._const_runner.start()
            self.const_run_btn.configure(state="disabled")
            self.const_stop_btn.configure(state="normal")
            self.const_status_label.set(T("common.running"))
            self._show_const_terminal()

        def _on_stop_constellation(self):
            if self._const_runner is not None:
                self._const_runner.stop()
                self.const_status_label.set(T("common.stopping"))

        def _on_constellation_finished(self):
            """_drain_output_queue's on_exit callback for the constellation queue --
            mirrors _on_loop_finished's reload_primes_tree() call, but for the
            Constellations tab: re-runs reload_constellations_tree() so newly found hits
            show up there the moment a run finishes, without a manual Refresh click.
            constellation_finder_v1.py has no dual-purpose button label to reset (unlike
            the Quick-gen 'Generate'/'Stop' one _on_loop_finished handles), so this is
            otherwise a much shorter version of that method."""
            self.reload_constellations_tree()

            # Mirrors _on_loop_finished()'s pending-search re-run, for a search-triggered
            # "run constellation_finder for this floor" instead (see
            # _offer_generate_missing_constellation()) -- see that method's own docstring
            # for why this is a SEPARATE slot from the prime-window one.
            if self._pending_search_after_const_gen is not None:
                pending = self._pending_search_after_const_gen
                self._pending_search_after_const_gen = None
                self._start_search_job(pending["kind"], pending["base_exponent"], pending["number"])

        def _poll_constellation_output(self):
            self._drain_output_queue(self._const_output_queue, self.const_console,
                                      self.const_run_btn, self.const_stop_btn,
                                      self.const_status_label,
                                      on_exit=self._on_constellation_finished)
            self.after(150, self._poll_constellation_output)

        def _on_ktuple_k_changed(self, _event=None, restore_variant_id=None):
            """Repopulates the variant combo for whichever k is now selected -- same
            two-combo cascade as the Kalkulator konstelacji tab's own
            _on_const_calc_k_changed(). `restore_variant_id`, given only on initial
            build (see _build_generation_tab()'s own call), re-selects a persisted
            variant instead of always defaulting to index 0, so the form reopens showing
            whatever pattern was last used here."""
            k_str = self.ktuple_k_combo.get()
            if not k_str:
                return
            self._ktuple_variants = pattern_catalog_v1.patterns_for_k(int(k_str))
            self.ktuple_variant_combo.configure(
                values=[T("const_calc.variant_label", id=w["id"])
                        for w in self._ktuple_variants])
            if self._ktuple_variants:
                idx = 0
                if restore_variant_id not in (None, ""):
                    for i, w in enumerate(self._ktuple_variants):
                        if str(w["id"]) == str(restore_variant_id):
                            idx = i
                            break
                self.ktuple_variant_combo.current(idx)
            else:
                self.ktuple_variant_combo.set("")
            self._on_ktuple_variant_changed()

        def _on_ktuple_variant_changed(self, _event=None):
            idx = self.ktuple_variant_combo.current()
            if idx < 0 or idx >= len(self._ktuple_variants):
                self.ktuple_pattern_info_var.set("")
                return
            w = self._ktuple_variants[idx]
            offsets_str = ", ".join(str(o) for o in w["offsets"])
            if w["record_digits"] is not None:
                self.ktuple_pattern_info_var.set(T(
                    "const_calc.pattern_info", offsets=offsets_str,
                    record_digits=w["record_digits"], discoverer=w["discoverer"],
                    date=w["date"]))
            else:
                self.ktuple_pattern_info_var.set(
                    T("const_calc.pattern_info_untracked", offsets=offsets_str))

        def _on_ktuple_n_locations_auto_clicked(self):
            """Auto button for the shared "n_locations" field -- primarily meant for
            strategy=digit_sweep (see recommended_digit_sweep_n_locations()'s own
            docstring for why it exists: the field is shared across all five
            strategies, so a single static default couldn't fit digit_sweep's
            per-branch-depth needs without either being far too small for it or far
            too large for the other four). Reads base_exponent/window_m straight from
            their own fields (both already on screen, no WSL round-trip needed --
            unlike _on_workers_auto_clicked's CPU probe, this is pure arithmetic), and
            fills n_locations with the recommendation. Like every other Auto button in
            this app, only ever SUGGESTS a value -- the field stays freely editable
            afterward."""
            base_exponent_str = self._ktuple_vars["base_exponent"].get().strip()
            window_m_str = self._ktuple_vars["window_m"].get().strip()
            if not base_exponent_str.isdigit() or not window_m_str.isdigit():
                messagebox.showerror(T("gen.dialog_title"), T("gen.error_base_exponent_int"))
                return
            base_exponent = int(base_exponent_str)
            window_m = int(window_m_str)
            recommended = recommended_digit_sweep_n_locations(base_exponent, window_m)
            self._ktuple_vars["n_locations"].set(str(recommended))
            numbers_total = recommended * window_m
            messagebox.showinfo(T("quick.dialog_title"), T(
                "gen.ktuple_auto_n_locations_result",
                recommended=f"{recommended:,}", numbers_total=f"{numbers_total:,}"))

        def _on_toggle_ktuple_advanced(self):
            """Same show/hide-together idiom as _on_toggle_loop_advanced() -- see that
            method's own docstring."""
            if self._ktuple_advanced_visible:
                self._ktuple_advanced_content.pack_forget()
                self._ktuple_advanced_visible = False
                self.ktuple_advanced_toggle_btn.configure(text=T("gen.advanced_show"))
            else:
                self._ktuple_advanced_content.pack(
                    fill="x", padx=8, pady=(0, 4), before=self.ktuple_console.toggle_row)
                self._ktuple_advanced_visible = True
                self.ktuple_advanced_toggle_btn.configure(text=T("gen.advanced_hide"))

        def _show_ktuple_terminal(self):
            self.ktuple_console.show()

        def _launch_ktuple(self, auto):
            """Shared by both the Run button (auto=False -- one batch, checkpointed,
            per click) and the Auto button (auto=True -- ktuple_sieve_v1.py itself
            keeps looping batch after batch inside this one WSL process until a
            confirmed hit, Stop, or the floor is exhausted -- see
            ktuple_sieve_v1.run_ktuple_job()'s own docstring). Everything below the
            auto-specific argv flag is identical between the two."""
            if self._ktuple_runner is not None and self._ktuple_runner.is_running():
                return
            base_exponent = self._ktuple_vars["base_exponent"].get().strip()
            if not base_exponent.isdigit():
                messagebox.showerror(T("gen.dialog_title"), T("gen.error_base_exponent_int"))
                return

            k_idx = self.ktuple_k_combo.current()
            variant_idx = self.ktuple_variant_combo.current()
            if k_idx < 0 or variant_idx < 0 or variant_idx >= len(self._ktuple_variants):
                messagebox.showerror(T("gen.dialog_title"), T("gen.ktuple_error_no_pattern"))
                return
            pattern = self._ktuple_variants[variant_idx]

            n_locations = self._ktuple_vars["n_locations"].get().strip()
            window_m = self._ktuple_vars["window_m"].get().strip()
            step = self._ktuple_vars["step"].get().strip()
            fragment_width = self._ktuple_vars["fragment_width"].get().strip()
            fragment_start = self._ktuple_vars["fragment_start"].get().strip() or "0"
            deep_prime_limit = self._ktuple_vars["deep_prime_limit"].get().strip() or "2000"
            mr_rounds = self._ktuple_vars["mr_rounds"].get().strip() or "40"
            manual_offsets_str = self._ktuple_vars["manual_offsets"].get().strip()
            pass_counter = self._ktuple_vars["pass_counter"].get().strip() or "0"

            numeric_ok = (
                n_locations.isdigit() and window_m.isdigit() and fragment_start.isdigit()
                and deep_prime_limit.isdigit() and mr_rounds.isdigit() and pass_counter.isdigit()
                and (not fragment_width or fragment_width.isdigit())
                and (not step or step.isdigit()))
            if not numeric_ok:
                messagebox.showerror(T("gen.dialog_title"), T("gen.ktuple_error_numeric_fields"))
                return

            strategy_idx = self.ktuple_strategy_combo.current()
            strategy = (_KTUPLE_STRATEGY_KEYS[strategy_idx]
                        if 0 <= strategy_idx < len(_KTUPLE_STRATEGY_KEYS) else "concentrated")

            manual_offsets = None
            if strategy == "manual_list":
                try:
                    manual_offsets = [int(tok) for tok in manual_offsets_str.replace(",", " ").split()]
                except ValueError:
                    manual_offsets = []
                if not manual_offsets:
                    messagebox.showerror(T("gen.dialog_title"), T("gen.ktuple_error_manual_offsets"))
                    return
            elif strategy == "manual_step" and not step:
                messagebox.showerror(T("gen.dialog_title"), T("gen.ktuple_error_manual_step_needs_step"))
                return

            reset_checkpoint = self._ktuple_reset_checkpoint_var.get()

            self._generation_settings["ktuple"] = {
                "base_exponent": base_exponent, "k": str(pattern["k"]),
                "variant_id": str(pattern["id"]), "n_locations": n_locations,
                "window_m": window_m, "strategy": strategy, "step": step,
                "fragment_width": fragment_width, "fragment_start": fragment_start,
                "manual_offsets": manual_offsets_str, "deep_prime_limit": deep_prime_limit,
                "mr_rounds": mr_rounds, "reset_checkpoint": reset_checkpoint,
                "pass_counter": pass_counter,
            }
            save_generation_settings(PORTAL_FOLDER, self._generation_settings)

            argv = build_ktuple_sieve_argv(
                base_exponent, pattern["k"], pattern["id"],
                n_locations=int(n_locations), window_m=int(window_m), strategy=strategy,
                step=int(step) if step else None,
                fragment_width=int(fragment_width) if fragment_width else None,
                fragment_start=int(fragment_start) if strategy != "manual_list" else None,
                manual_offsets=manual_offsets, deep_prime_limit=int(deep_prime_limit),
                mr_rounds=int(mr_rounds), auto=auto, reset_checkpoint=reset_checkpoint,
                pass_counter=int(pass_counter) if strategy == "digit_sweep" else None)
            log_path, exit_path, _run_id = generation_log_paths(PORTAL_FOLDER, "ktuple")
            cmd = build_wsl_logged_command(argv, log_path, exit_path)

            self.ktuple_console.append(self._new_run_separator())
            self._ktuple_output_queue = queue.Queue()
            self._ktuple_runner = WslLoggedRunner(
                cmd, log_path, exit_path, self._ktuple_output_queue,
                kill_pattern="ktuple_sieve_v1.py")
            self._ktuple_runner.start()
            self.ktuple_run_btn.configure(state="disabled")
            self.ktuple_auto_btn.configure(state="disabled")
            self.ktuple_stop_btn.configure(state="normal")
            self.ktuple_status_label.set(T("common.running"))
            self._show_ktuple_terminal()

        def _on_stop_ktuple(self):
            if self._ktuple_runner is not None:
                self._ktuple_runner.stop()
                self.ktuple_status_label.set(T("common.stopping"))

        def _on_ktuple_finished(self):
            """Mirrors _on_constellation_finished() -- confirmed hits land in the same
            per-(k,variant) hit files Section B writes to, so the Constellations tab
            needs the same post-run refresh. Also re-enables ktuple_auto_btn --
            _drain_output_queue() only knows about the plain run_btn/stop_btn pair
            shared with every other section, not this section's own extra Auto
            button, so that one is reset here instead."""
            self.reload_constellations_tree()
            self.ktuple_auto_btn.configure(state="normal")

        def _poll_ktuple_output(self):
            self._drain_output_queue(self._ktuple_output_queue, self.ktuple_console,
                                      self.ktuple_run_btn, self.ktuple_stop_btn,
                                      self.ktuple_status_label,
                                      on_exit=self._on_ktuple_finished)
            self.after(150, self._poll_ktuple_output)

        def _drain_output_queue(self, q, console, run_btn, stop_btn, status_var, on_exit=None):
            """Shared by both Generation sections: drains whatever output
            a WslLoggedRunner has pushed onto `q` since the last poll into
            `console` (a GenerationConsole -- autoscrolling to the bottom is handled by
            its own append()), and on that runner's
            ("__exit__", returncode) sentinel, re-enables Run / disables Stop and
            reports the exit code. Same 150ms self.after() polling cadence as the floor-
            totals worker (_poll_totals_results) -- this method itself does NOT
            reschedule; each caller (_poll_loop_output / _poll_constellation_output) owns
            its own self.after() chain so the two sections' polling stays independent.

            An optional on_exit() callback fires right after the exit-sentinel
            handling above -- currently only _poll_loop_output uses it (to reset the
            Quick-gen 'Generate' button's temporary 'Stop' label, see
            _on_loop_finished); _poll_constellation_output has no equivalent dual-purpose
            button so it leaves this at its default of None.

            Every plain-text chunk is ALSO fed to _update_shared_progress_from_generation_
            chunk() -- see that method's own docstring -- so the shared bottom bar reflects
            live generation/constellation-search progress, on top of the raw text staying
            visible in `console` exactly as before."""
            try:
                while True:
                    item = q.get_nowait()
                    if isinstance(item, tuple) and item and item[0] == "__exit__":
                        returncode = item[1]
                        run_btn.configure(state="normal")
                        stop_btn.configure(state="disabled")
                        if returncode is None:
                            status_var.set(T("common.error_starting_process"))
                        elif returncode == 0:
                            status_var.set(T("common.finished_ok"))
                        else:
                            status_var.set(T("common.finished_code", code=returncode))
                        if on_exit is not None:
                            on_exit()
                        continue
                    console.append(item)
                    self._update_shared_progress_from_generation_chunk(item)
            except queue.Empty:
                pass

        def _update_shared_progress_from_generation_chunk(self, chunk):
            """Reflects a generation run's live console output onto the shared bottom status
            bar -- the SAME self.status/self.totals_progress the floor-totals scan and the
            Primes/Constellations search box already use -- covering the WHOLE pipeline as
            one sequence of steps, not just the batch-sieve phase. Scans `chunk` (a raw text
            blob straight from WslLoggedRunner's log-tailing -- may hold zero, one, or
            several lines, and may occasionally split one line across two chunks; a missed
            match here just means the bar catches up on the next chunk a moment later,
            harmless for a live display) for whichever of the five line shapes documented on
            _GEN_PREP_DONE_RE/_GEN_SIEVE_PROGRESS_RE/_GEN_SIEVE_DONE_RE/_GEN_CONST_PROGRESS_RE/
            _GEN_CONST_DONE_RE's own module-level comment is present, checked in the order a
            real run actually prints them (prep -> batches -> done; the constellation path has
            no separate prep step of its own, just per-file progress -> done).

            Sieve-pipeline step model (self._gen_step_total, reset to None between runs):
            step 0 is the pi(L_final) prep phase (which can itself run into minutes at
            extreme depth -- see prime_sieve_v4_1.py's own SKIPPED-mode comment -- and used
            to leave the bar sitting completely empty for all of it), steps 1..n_batches are
            each individual sieve batch. The real n_batches isn't known until the FIRST
            batch-progress line arrives, so between the prep line and that first batch line
            the bar shows a provisional 1-of-2 (half full) rather than 0-of-unknown -- it
            gets corrected to the real proportion the moment the first batch line defines the
            actual total, which in practice is only a few seconds later. The run-finished
            line ("[*] TOTAL PRIMES FOUND...") snaps the bar to fully complete regardless of
            exactly how many steps were tracked, then clears _gen_step_total so the NEXT
            run starts from the same 'unknown total yet' state rather than inheriting this
            run's batch count.

            No explicit arbitration against search/totals for ownership of the shared bar:
            each of the three writes self.status on its own independent schedule, so
            whichever last had something to say is simply what's showing. In practice
            generation dominates while it's actually running, since these lines repeat every
            couple of seconds -- far more often than search's one-shot "searching..."
            message or the totals scan's own periodic updates -- without needing a priority
            flag to enforce that.

            Multi-iteration Exploration-mode loop (self._gen_loop_run_count/_gen_loop_
            iteration, both None outside a loop run): orchestrator_loop_v2.py launches
            run_count separate orchestrator_v3.py subprocesses back to back, one per
            iteration, and each one prints its OWN independent prep/batch-progress/done
            lines as if it were a lone single-window-range run. Without loop-awareness the
            bar would snap to "done" after iteration 1 of N (see _LOOP_SESSION_START_RE's
            own module-level comment). While _gen_loop_run_count is set, the per-iteration
            step count from the sieve-pipeline model above is treated as one slice of a
            wider run_count-slice bar: overall maximum = run_count * that iteration's own
            step_total, overall value = completed-iterations-worth of steps + the current
            iteration's own progress into its slice. Only _LOOP_SESSION_DONE_RE -- the
            line orchestrator_loop_v2.py itself prints once ALL iterations are over --
            snaps the bar to full and clears _gen_loop_run_count/_gen_loop_iteration back
            to None; the per-iteration "[*] TOTAL PRIMES FOUND..." line just marks that
            iteration's slice as complete and keeps waiting."""
            if _LOOP_SESSION_DONE_RE.search(chunk):
                total = self._gen_step_total or 1
                self.totals_progress.stop()
                self.totals_progress.configure(mode="determinate", maximum=total, value=total)
                self.status.set(T("gen.status_progress_done"))
                self._gen_step_total = None
                self._gen_loop_run_count = None
                self._gen_loop_iteration = None
                return

            loop_start_match = _LOOP_SESSION_START_RE.search(chunk)
            if loop_start_match:
                self._gen_loop_run_count = int(loop_start_match.group(1))
                self._gen_loop_iteration = 1

            iter_start_matches = _LOOP_ITERATION_START_RE.findall(chunk)
            if iter_start_matches:
                iteration_str, _run_count_str = iter_start_matches[-1]
                self._gen_loop_iteration = int(iteration_str)
                self._gen_step_total = None  # fresh subprocess -- real total not known
                                              # until its own first batch-progress line

            if _GEN_SIEVE_DONE_RE.search(chunk) or _GEN_CONST_DONE_RE.search(chunk):
                if self._gen_loop_run_count is not None:
                    # One iteration of a multi-iteration run just finished -- NOT the whole
                    # session. Only _LOOP_SESSION_DONE_RE (checked above) snaps the bar to
                    # full/clears loop state; here just mark this iteration's own slice as
                    # complete and keep the loop state alive for the next iteration.
                    run_count = self._gen_loop_run_count
                    iteration = self._gen_loop_iteration or 1
                    step_total = self._gen_step_total or 1
                    self.totals_progress.stop()
                    self.totals_progress.configure(
                        mode="determinate", maximum=run_count * step_total,
                        value=min(iteration, run_count) * step_total)
                    self.status.set(T("gen.status_progress_loop_iteration_done",
                                       iteration=iteration, run_count=run_count))
                    return
                total = self._gen_step_total or 1
                self.totals_progress.stop()
                self.totals_progress.configure(mode="determinate", maximum=total, value=total)
                self.status.set(T("gen.status_progress_done"))
                self._gen_step_total = None
                return

            sieve_matches = _GEN_SIEVE_PROGRESS_RE.findall(chunk)
            if sieve_matches:
                percent_str, done_str, total_str = sieve_matches[-1]
                done, n_batches = int(done_str), int(total_str)
                self._gen_step_total = n_batches + 1  # +1 for the prep step already done
                self.totals_progress.stop()
                if self._gen_loop_run_count is not None:
                    run_count = self._gen_loop_run_count
                    iteration = self._gen_loop_iteration or 1
                    self.totals_progress.configure(
                        mode="determinate", maximum=run_count * self._gen_step_total,
                        value=(iteration - 1) * self._gen_step_total + (done + 1))
                    self.status.set(T("gen.status_progress_loop_sieve", iteration=iteration,
                                       run_count=run_count, percent=percent_str,
                                       done=done, total=n_batches))
                else:
                    self.totals_progress.configure(mode="determinate",
                                                    maximum=self._gen_step_total, value=done + 1)
                    self.status.set(T("gen.status_progress_sieve", percent=percent_str,
                                       done=done, total=n_batches))
                return

            const_matches = _GEN_CONST_PROGRESS_RE.findall(chunk)
            if const_matches:
                done_str, total_str = const_matches[-1]
                done, total = int(done_str), int(total_str)
                self._gen_step_total = total
                self.totals_progress.stop()
                self.totals_progress.configure(mode="determinate", maximum=max(1, total), value=done)
                self.status.set(T("gen.status_progress_const", done=done, total=total))
                return

            if _GEN_PREP_DONE_RE.search(chunk):
                self._gen_step_total = None  # real total not known until the first
                                              # batch-progress line -- see docstring above
                self.totals_progress.stop()
                if self._gen_loop_run_count is not None:
                    run_count = self._gen_loop_run_count
                    iteration = self._gen_loop_iteration or 1
                    self.totals_progress.configure(
                        mode="determinate", maximum=run_count * 2, value=(iteration - 1) * 2 + 1)
                    self.status.set(T("gen.status_progress_loop_prep", iteration=iteration,
                                       run_count=run_count))
                else:
                    self.totals_progress.configure(mode="determinate", maximum=2, value=1)
                    self.status.set(T("gen.status_progress_prep"))

        # --- Tab 5: Settings -----------------------------------------------------

        def _set_portal_folder(self, new_path):
            """The one place that rebinds the module-level PORTAL_FOLDER global -- passed
            into SettingsTab as wsl_helpers["set_portal_folder"] so a storage-path change
            in the Settings tab takes effect immediately for every other tab/function in
            this file, all of which read the bare name PORTAL_FOLDER at call time (see the
            APP_SETTINGS/PORTAL_FOLDER comment near this file's top). `global` here binds
            to this MODULE's namespace regardless of this method's own nesting depth
            inside _build_gui()/PortalBrowserApp.

            Rebinding the global alone isn't enough: without an explicit reload, a
            genuinely empty new location would still show the previous location's floors
            with real file counts, since nothing else re-scans the Prime numbers /
            Constellations trees after a path change. So this re-triggers both trees'
            reload itself, right here, the moment the path actually changes (guarded by
            `changed` so re-saving the SAME path -- e.g. clicking Save again -- doesn't
            pay for two pointless re-scans). Both reload_*_tree() methods are safe to call
            here: by the time a user can reach the Settings tab's Save/Reset buttons,
            every other tab has long since finished its own initial build."""
            global PORTAL_FOLDER
            changed = (new_path != PORTAL_FOLDER)
            PORTAL_FOLDER = new_path
            self.status.set(T("app.status_portal_initial", folder=PORTAL_FOLDER))
            if changed:
                self.reload_primes_tree()
                self.reload_constellations_tree()

        def _build_settings_tab(self, settings_tab_cls):
            """Wires SettingsTab (primeatlas/settings_tab.py) into the 5th notebook tab.
            SettingsTab doesn't know how to launch WSL subprocesses itself -- it reuses
            THIS file's existing Generation-tab machinery (build_loop_argv,
            build_constellation_finder_argv, build_wsl_logged_command, WslLoggedRunner,
            generation_log_paths) via this small callable bundle, rather than
            reimplementing a second copy inside primeatlas/ or creating a circular import
            back into this module. get_loop_defaults() reads self._generation_settings,
            which _build_generation_tab() (called just before this method) already
            populated from .portal_generation_settings.json."""
            wsl_helpers = {
                "get_portal_folder": lambda: PORTAL_FOLDER,
                "set_portal_folder": self._set_portal_folder,
                "get_loop_defaults": lambda: self._generation_settings.get("loop", {}),
                "build_loop_argv": build_loop_argv,
                "build_constellation_finder_argv": build_constellation_finder_argv,
                "build_wsl_logged_command": build_wsl_logged_command,
                "WslLoggedRunner": WslLoggedRunner,
                "generation_log_paths": generation_log_paths,
                # Added for the restore driver's own RAM-based "auto width" and low-floor
                # (0-6) cascade-aware batching -- see restore_job.py / settings_tab.py's
                # _drive_windows_phase() docstring. Passed through rather than imported
                # directly in settings_tab.py, same reasoning as every other entry here
                # (see this method's own docstring).
                "low_floor_cutoff": LOW_FLOOR_CUTOFF,
                "estimate_wsl_available_ram_bytes": estimate_wsl_available_ram_bytes,
                "recommended_max_windows": recommended_max_windows,
                # Added so the restore driver can prefer primesieve mode (much faster,
                # no RAM-buffer cost) for any floor whose numeric range fits under
                # libprimesieve's own uint64 ceiling, falling back to the orchestrator
                # pipeline only for floors that don't -- see _drive_windows_phase().
                "primesieve_max_stop": PRIMESIEVE_MAX_STOP,
                "build_primesieve_argv": build_primesieve_argv,
                "find_continuation_target_idx": find_continuation_target_idx,
                # Added so SettingsTab can refresh the Prime numbers / Constellations trees
                # itself after two operations that change disk contents outside those tabs'
                # own controls: deleting the entire database, and a restore job finishing.
                # Both trees previously only refreshed via _set_portal_folder (path change)
                # or _on_loop_finished/_on_constellation_finished (Generation tab runs) --
                # neither delete-all nor restore-complete touched them at all, so newly
                # emptied/regenerated floors stayed invisible until a manual Refresh click.
                "reload_primes_tree": self.reload_primes_tree,
                "reload_constellations_tree": self.reload_constellations_tree,
                # Faza 2b -- optional-library installer (currently just sympy, see
                # primeatlas/primality.py). LocalLoggedRunner/build_pip_install_argv are
                # plain local (non-WSL) subprocess helpers -- see their own docstrings
                # for why they don't need WslLoggedRunner's file-tailing machinery.
                "try_import_sympy": primality_try_import_sympy,
                "build_pip_install_argv": build_pip_install_argv,
                "LocalLoggedRunner": LocalLoggedRunner,
            }
            self.settings_tab = settings_tab_cls(
                self.settings_tab_container, APP_SETTINGS, wsl_helpers, TRANSLATOR)
            self.settings_tab.pack(fill="both", expand=True)

        # --- Tab 4: Benchmark ---------------------------------------------------------

        def _build_benchmark_tab(self):
            top = ttk.Frame(self.benchmark_tab)
            top.pack(fill="x", padx=6, pady=4)
            ttk.Button(top, text=T("common.refresh"), command=self.reload_benchmark_log).pack(side="left")
            ttk.Button(top, text=T("bench.save_pdf"), command=self._export_benchmark_pdf).pack(
                side="left", padx=(6, 0))
            ttk.Label(top, text=T("bench.chart_hint")).pack(side="left")

            chart_frame = ttk.Frame(self.benchmark_tab)
            chart_frame.pack(fill="x", padx=6, pady=(0, 4))
            self.benchmark_chart = tk.Canvas(chart_frame, height=220, background="white",
                                              highlightthickness=1, highlightbackground="#cccccc")
            self.benchmark_chart.pack(fill="x")
            self.benchmark_chart.bind("<Configure>", lambda _e: self._redraw_benchmark_chart())

            # Second chart: sieve-numbers/s + write-MB/s -- the phase-breakdown counterpart
            # to the growth chart above, populated only from prime_sieve_v4_1.py rows (see
            # aggregate_benchmark_sieve_nps()/aggregate_benchmark_write_mbps()). Always
            # visible, same as the first chart -- _draw_growth_chart() already shows its own
            # "no data yet" placeholder when both series are empty, so a project that hasn't
            # re-benchmarked with v4.1 yet just sees that placeholder rather than the tab
            # silently hiding/showing a whole section.
            chart_frame2 = ttk.Frame(self.benchmark_tab)
            chart_frame2.pack(fill="x", padx=6, pady=(0, 4))
            ttk.Label(chart_frame2, text=T("bench.chart2_hint")).pack(anchor="w")
            self.benchmark_chart2 = tk.Canvas(chart_frame2, height=180, background="white",
                                               highlightthickness=1, highlightbackground="#cccccc")
            self.benchmark_chart2.pack(fill="x")
            self.benchmark_chart2.bind("<Configure>", lambda _e: self._redraw_benchmark_chart2())

            tree_frame = ttk.Frame(self.benchmark_tab)
            tree_frame.pack(fill="both", expand=True, padx=6, pady=4)

            # Floor pagination -- ABOVE the tree, same Prev/label/Next/goto layout as the
            # "Prime numbers" tab's floor nav (see that tab's _build_primes_tab for the
            # full rationale). benchmark_log.csv now gets a row per orchestrator run
            # (including cheap, repeatable count-only benchmarking runs -- see the
            # write_files toggle), so a floor can accumulate dozens-to-hundreds of rows;
            # expanding a floor only lists/groups rows already in memory (cheap -- the
            # whole CSV is small text) but only INSERTS one page's worth of Treeview rows at
            # a time, which is the part that used to freeze the old flat, ever-growing table.
            benchmark_nav = ttk.Frame(tree_frame)
            benchmark_nav.pack(fill="x", pady=(0, 4))
            self.benchmark_prev_btn = ttk.Button(
                benchmark_nav, text=T("common.prev_page"), command=self._prev_benchmark_page,
                state="disabled")
            self.benchmark_prev_btn.pack(side="left")
            self.benchmark_page_label = tk.StringVar(value="")
            ttk.Label(benchmark_nav, textvariable=self.benchmark_page_label, width=16,
                      anchor="center").pack(side="left")
            self.benchmark_next_btn = ttk.Button(
                benchmark_nav, text=T("common.next_page"), command=self._next_benchmark_page,
                state="disabled")
            self.benchmark_next_btn.pack(side="left")
            ttk.Label(benchmark_nav, text=T("common.page_prefix")).pack(side="left", padx=(10, 0))
            self.benchmark_goto_entry = ttk.Entry(benchmark_nav, width=6)
            self.benchmark_goto_entry.pack(side="left", padx=(4, 0))
            self.benchmark_goto_entry.bind("<Return>", lambda _e: self._goto_benchmark_page())
            ttk.Button(benchmark_nav, text=T("common.goto"), command=self._goto_benchmark_page).pack(
                side="left", padx=(4, 0))

            self.benchmark_tree = ttk.Treeview(tree_frame, show="tree headings")
            self.benchmark_tree.heading("#0", text=T("bench.col_pietro"))
            self.benchmark_tree.column("#0", width=170, stretch=False)
            # Horizontal scrollbar -- with 11 data columns + #0, the row is wider than the
            # tab, and without this the only way to see the columns off the right edge was
            # shrinking every column's width by hand. stretch=False on every column (set
            # below, in reload_benchmark_log()) keeps each column at its given width instead
            # of Tk auto-stretching the last one to fill the widget, which is what makes the
            # row properly wider than the view and the scrollbar actually needed/usable.
            vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.benchmark_tree.yview)
            hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.benchmark_tree.xview)
            self.benchmark_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
            vsb.pack(side="right", fill="y")
            hsb.pack(side="bottom", fill="x")
            self.benchmark_tree.pack(side="left", fill="both", expand=True)

            self.benchmark_tree.tag_configure("pietro", background="#eef3fb")
            self.benchmark_tree.tag_configure("stat", background="#fff6d8")

            self.benchmark_tree.bind("<<TreeviewOpen>>", self._on_benchmark_tree_open)
            self.benchmark_tree.bind("<<TreeviewClose>>", self._on_benchmark_tree_close)
            self.benchmark_tree.bind("<<TreeviewSelect>>", self._on_benchmark_tree_select)

            self._benchmark_growth_points = []
            self._benchmark_fair_spw_points = []  # loop_seconds_per_window, second chart line
            self._benchmark_sieve_nps_points = []   # sieve-phase numbers/s, second CHART's
                                                     # primary line (prime_sieve_v4_1.py rows
                                                     # only -- see aggregate_benchmark_sieve_nps)
            self._benchmark_write_mbps_points = []  # write-phase MB/s, second chart's
                                                     # secondary line (same v4.1-only caveat)
            self._benchmark_fieldnames = []  # kept in sync by reload_benchmark_log() --
            self._benchmark_tree_fieldnames = []  # same, minus BENCHMARK_TREE_HIDDEN_COLUMNS
                                              # -- what the tree itself actually displays
            self._benchmark_rows = []        # _export_benchmark_pdf reads these (the FULL,
                                              # ungrouped data) instead of re-parsing the CSV,
                                              # so the PDF always exports everything, even
                                              # rows not currently paged into view.
            self._benchmark_rows_by_pietro = {}   # base_exponent -> [rows...], built by
                                                   # reload_benchmark_log() via
                                                   # group_benchmark_rows_by_pietro()
            self._benchmark_pietro_state = {}     # tree item id -> {base_exponent, rows,
                                                   # stats, page, total_pages} -- lazily
                                                   # populated on <<TreeviewOpen>>, dropped on
                                                   # <<TreeviewClose>>, same lifecycle as the
                                                   # primes tab's _pietro_state.
            self._active_benchmark_node = None    # which floor's page the nav buttons above
                                                   # currently operate on

        def _redraw_benchmark_chart(self):
            # Before the window has actually been mapped/laid out by the OS window manager
            # (e.g. the very first draw, triggered from reload_benchmark_log() during
            # __init__), winfo_width()/height() can still report the Tk default of 1x1 --
            # <Configure> will fire and redraw properly once real geometry is assigned, but
            # falling back to a reasonable size here means the chart doesn't sit blank in
            # the meantime.
            width = self.benchmark_chart.winfo_width()
            height = self.benchmark_chart.winfo_height()
            if width <= 1:
                width = 900
            if height <= 1:
                height = 220
            _draw_growth_chart(self.benchmark_chart, self._benchmark_growth_points, width, height,
                                points2=self._benchmark_fair_spw_points)

        def _redraw_benchmark_chart2(self):
            """Same fallback-size handling as _redraw_benchmark_chart() (see that method's own
            comment) -- draws the sieve-numbers/s + write-MB/s phase-breakdown chart onto its
            own canvas, right below the growth chart."""
            width = self.benchmark_chart2.winfo_width()
            height = self.benchmark_chart2.winfo_height()
            if width <= 1:
                width = 900
            if height <= 1:
                height = 180
            _draw_growth_chart(self.benchmark_chart2, self._benchmark_sieve_nps_points, width,
                                height, points2=self._benchmark_write_mbps_points,
                                label_key1="bench.axis_sieve_nps",
                                label_key2="bench.axis_write_mbps",
                                fmt1="{:,.0f}", fmt2="{:,.1f}")

        def reload_benchmark_log(self):
            fieldnames, rows = read_benchmark_log(PORTAL_FOLDER)
            self._benchmark_fieldnames = fieldnames  # FULL list -- PDF export/growth chart
                                                       # still use every column, unaffected
                                                       # by what the tree itself displays
            self._benchmark_rows = rows
            self._benchmark_rows_by_pietro = group_benchmark_rows_by_pietro(rows)
            self._benchmark_tree_fieldnames = _order_benchmark_tree_columns(
                [c for c in fieldnames if c not in BENCHMARK_TREE_HIDDEN_COLUMNS])

            self._benchmark_growth_points = aggregate_benchmark_growth(rows)
            self._benchmark_fair_spw_points = aggregate_benchmark_fair_spw(rows)
            self._redraw_benchmark_chart()

            self._benchmark_sieve_nps_points = aggregate_benchmark_sieve_nps(rows)
            self._benchmark_write_mbps_points = aggregate_benchmark_write_mbps(rows)
            self._redraw_benchmark_chart2()

            self.benchmark_tree.delete(*self.benchmark_tree.get_children())
            self._benchmark_pietro_state = {}
            self._active_benchmark_node = None
            self._refresh_benchmark_nav_controls()

            tree_fieldnames = self._benchmark_tree_fieldnames
            self.benchmark_tree["columns"] = tree_fieldnames
            for col in tree_fieldnames:
                self.benchmark_tree.heading(col, text=col)
                self.benchmark_tree.column(col, width=120, anchor="center", stretch=False)

            if not fieldnames or not self._benchmark_rows_by_pietro:
                self.benchmark_tree.insert("", "end", text=T("bench.no_data_row"))
                return

            for base_exponent in sorted(self._benchmark_rows_by_pietro):
                count = len(self._benchmark_rows_by_pietro[base_exponent])
                node = self.benchmark_tree.insert(
                    "", "end", text=T("bench.pietro_measurements", base_exponent=base_exponent, count=count),
                    values=["" for _ in tree_fieldnames], open=False, tags=("pietro",))
                self.benchmark_tree.insert(node, "end", text=T("common.loading"))

        def _on_benchmark_tree_open(self, _event):
            node = self.benchmark_tree.focus()
            self._populate_benchmark_pietro_node(node)
            self._set_active_benchmark_node(node)

        def _on_benchmark_tree_close(self, _event):
            """Same lifecycle as the primes tab's _on_tree_close(): collapsing a floor drops
            its row/page state and resets to a single "(loading...)" placeholder, so a floor
            that's never re-expanded doesn't hold onto its (already in-memory, but still
            worth not duplicating into tree-item state) rows indefinitely."""
            node = self.benchmark_tree.focus()
            if node not in self._benchmark_pietro_state:
                return
            del self._benchmark_pietro_state[node]
            self.benchmark_tree.delete(*self.benchmark_tree.get_children(node))
            self.benchmark_tree.insert(node, "end", text=T("common.loading"))
            if self._active_benchmark_node == node:
                self._active_benchmark_node = None
                self._refresh_benchmark_nav_controls()

        def _on_benchmark_tree_select(self, _event):
            """Clicking a floor header (whether just opened or already expanded) makes it
            the target of the pagination controls above the tree -- same behavior as the
            primes tab's floor nav."""
            selection = self.benchmark_tree.selection()
            if not selection:
                return
            item = selection[0]
            if "pietro" in self.benchmark_tree.item(item, "tags"):
                self._set_active_benchmark_node(item)

        def _populate_benchmark_pietro_node(self, node):
            if node in self._benchmark_pietro_state:
                return  # already prepared this session -- nothing to redo
            children = self.benchmark_tree.get_children(node)
            if len(children) == 1 and self.benchmark_tree.item(children[0], "text") == T("common.loading"):
                self.benchmark_tree.delete(children[0])

            text = self.benchmark_tree.item(node, "text")  # "10p{N} (M measurement(s))"
            base_exponent = int(text[3:].split(" ", 1)[0])
            rows = self._benchmark_rows_by_pietro.get(base_exponent, [])
            stats = benchmark_row_stats(rows)
            total_pages = max(1, (len(rows) + BENCHMARK_PAGE_SIZE - 1) // BENCHMARK_PAGE_SIZE)
            self._benchmark_pietro_state[node] = {
                "base_exponent": base_exponent,
                "rows": rows,
                "stats": stats,
                "page": 0,
                "total_pages": total_pages,
            }
            self._show_benchmark_page(node, 0)

        def _show_benchmark_page(self, node, page):
            """Renders page `page` (0-indexed) of a floor's benchmark rows, PLUS a
            standalone stats row at the top (min/avg/max seconds_per_window across ALL of
            that floor's rows, not just the current page -- re-inserted on every page turn,
            which costs nothing since it's a single row) -- see benchmark_row_stats()."""
            state = self._benchmark_pietro_state.get(node)
            if not state:
                return
            total_pages = state["total_pages"]
            page = max(0, min(page, total_pages - 1))
            state["page"] = page

            self.benchmark_tree.delete(*self.benchmark_tree.get_children(node))
            fieldnames = self._benchmark_tree_fieldnames  # display columns only -- see
                                                            # BENCHMARK_TREE_HIDDEN_COLUMNS

            stats = state["stats"]
            stat_values = ["" for _ in fieldnames]
            if stats and "seconds_per_window" in fieldnames:
                idx = fieldnames.index("seconds_per_window")
                stat_values[idx] = T("bench.stat_summary", avg=f"{stats['avg']:.4f}",
                                      min=f"{stats['min']:.4f}", max=f"{stats['max']:.4f}")
                stat_text = T("bench.stat_row_label", count=stats['count'])
            else:
                stat_text = T("bench.stat_no_data")
            self.benchmark_tree.insert(node, "end", text=stat_text, values=stat_values,
                                        tags=("stat",))

            rows = state["rows"]
            start = page * BENCHMARK_PAGE_SIZE
            end = min(start + BENCHMARK_PAGE_SIZE, len(rows))
            for row in rows[start:end]:
                # #0 shows the run's timestamp for individual rows -- run_timestamp_utc is
                # excluded from the columns list (BENCHMARK_TREE_HIDDEN_COLUMNS) precisely
                # so it can live here instead, in the column that would otherwise sit empty
                # for every data row (target_idx_start/target_idx_end are already their own
                # columns, so #0 had nothing else useful to show).
                label = row.get("run_timestamp_utc", "")
                values = [row.get(c, "") for c in fieldnames]
                self.benchmark_tree.insert(node, "end", text=label, values=values, tags=("row",))

            if self._active_benchmark_node == node:
                self._refresh_benchmark_nav_controls()

        def _set_active_benchmark_node(self, node):
            self._active_benchmark_node = node
            self._refresh_benchmark_nav_controls()

        def _refresh_benchmark_nav_controls(self):
            node = self._active_benchmark_node
            state = self._benchmark_pietro_state.get(node) if node is not None else None
            if not state:
                self.benchmark_page_label.set("")
                self.benchmark_prev_btn.configure(state="disabled")
                self.benchmark_next_btn.configure(state="disabled")
                return
            _update_nav_controls(self.benchmark_page_label, state["page"], state["total_pages"],
                                  self.benchmark_prev_btn, self.benchmark_next_btn)

        def _prev_benchmark_page(self):
            node = self._active_benchmark_node
            if node is not None and self._benchmark_pietro_state.get(node):
                self._show_benchmark_page(node, self._benchmark_pietro_state[node]["page"] - 1)

        def _next_benchmark_page(self):
            node = self._active_benchmark_node
            if node is not None and self._benchmark_pietro_state.get(node):
                self._show_benchmark_page(node, self._benchmark_pietro_state[node]["page"] + 1)

        def _goto_benchmark_page(self):
            raw = self.benchmark_goto_entry.get().strip()
            if not raw.isdigit():
                return
            node = self._active_benchmark_node
            if node is not None and self._benchmark_pietro_state.get(node):
                self._show_benchmark_page(node, int(raw) - 1)

        def _export_benchmark_pdf(self):
            if not self._benchmark_fieldnames or not self._benchmark_rows:
                messagebox.showinfo(
                    T("bench.save_pdf"),
                    T("bench.no_data_dialog"))
                return
            default_name = f"benchmark_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            path = filedialog.asksaveasfilename(
                title=T("bench.save_dialog_title"),
                initialdir=PORTAL_FOLDER,
                initialfile=default_name,
                defaultextension=".pdf",
                filetypes=[("PDF", "*.pdf"), (T("common.all_files"), "*.*")])
            if not path:
                return
            try:
                render_benchmark_pdf(path, self._benchmark_growth_points,
                                      self._benchmark_fieldnames, self._benchmark_rows,
                                      points2=self._benchmark_fair_spw_points,
                                      translator=TRANSLATOR,
                                      sieve_points=self._benchmark_sieve_nps_points,
                                      write_points=self._benchmark_write_mbps_points)
            except Exception as exc:
                messagebox.showerror(T("bench.save_pdf"), T("bench.save_error", error=exc))
                return
            self.status.set(T("bench.status_saved", path=path))
            messagebox.showinfo(T("bench.save_pdf"), T("bench.saved_dialog", path=path))

    return PortalBrowserApp


def main():
    app_cls = _build_gui()
    app = app_cls()
    app.mainloop()


if __name__ == "__main__":
    main()
