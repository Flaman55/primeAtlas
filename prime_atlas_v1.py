import sys
import os

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
# prime_sieve_v1/pattern_catalog_v1 are not imported into THIS file's own namespace
# anymore -- every direct user of either moved into extracted primeatlas/*.py tab
# modules during the refactor branch's Faza 3 (2026-08-23). The sys.path.insert() calls
# below still matter: every primeatlas/*.py module that imports prime_sieve_v1/
# pattern_catalog_v1 itself relies on THIS app process having already added these two
# directories, since none of those modules re-add them.
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "prime_sieve"))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "constellation"))
from primeatlas import (  # noqa: E402
    AppSettings, Translator, prune_empty_pietro_dirs,
    try_import_sympy as primality_try_import_sympy,
)
# run_all_tests/factorize (as primality_run_all_tests/primality_factorize) used to be
# imported here for the primality-testing sub-tab's own worker job -- moved to
# primeatlas/primality_tab.py during the refactor branch's Faza 4 (2026-08-24), which
# imports them directly from primeatlas.primality itself. primality_try_import_sympy
# stays -- it's still called directly by _build_settings_tab's wsl_helpers dict
# (dependency installer), unrelated to the primality-testing sub-tab itself.
# goldbach_check_window/goldbach_cascade_step/goldbach_window_rows/
# goldbach_all_decompositions/goldbach_both_base_window_rows/
# GOLDBACH_BOTH_BASE_PMAX_CEILING/GOLDBACH_BOTH_BASE_PMIN/goldbach_largest_prime_le/
# goldbach_sieve_is_prime used to be imported here -- moved to primeatlas/
# research_goldbach_tab.py during the refactor branch's Faza 3 (tab-by-tab backend/UI
# split, 2026-08-23), which now imports them directly from primeatlas.goldbach_window
# itself (see that module's own docstring) -- nothing in this file calls them anymore.
from primeatlas import floor_meta  # noqa: E402
from primeatlas import background  # noqa: E402
# pdf_writer/benchmark: extracted during the refactor branch's Faza 3 (tab-by-tab
# backend/UI split, 2026-08-23) -- see those modules' own docstrings. Now that
# render_constellation_records_pdf has ALSO moved out (to primeatlas/constellations.py,
# alongside the rest of the Constellations tab's backend), nothing in this file calls
# the pdf_writer helpers directly anymore -- everything the (now separate) Benchmark and
# Constellations tabs need lives in primeatlas/benchmark_tab.py and
# primeatlas/constellations_records_tab.py respectively, imported lazily/locally from
# inside their own build methods (see _build_gui()'s own lazy-tkinter-import convention).
from primeatlas.benchmark import read_benchmark_log  # noqa: E402
# constellations: extracted during the refactor branch's Faza 3 (2026-08-23), alongside
# the Constellations tab's own UI split (primeatlas/constellations_hits_tab.py,
# constellations_calc_tab.py, constellations_records_tab.py) -- see that module's own
# docstring. Only the three names the shared search worker/_constellations_tree_scan/
# _on_const_search_result still call directly are imported here; everything else those
# sub-tabs need is imported locally inside _build_constellations_section().
from primeatlas.constellations import (  # noqa: E402
    find_constellation_participation, floor_has_constellation_hits, list_constellation_hits,
)
# storage: extracted during the refactor branch's Faza 3 (2026-08-23), alongside the
# "Prime numbers" tab's UI split (primeatlas/primes_tab.py) -- see that module's own
# docstring. list_pietra/list_source_filenames/load_totals_cache/save_totals_cache/
# update_pietro_totals_cache/format_duration/format_bytes/
# aggregate_write_seconds_by_pietro/find_prime_in_floor/LOW_FLOOR_CUTOFF were never
# specific to that one tab in the first place (see primeatlas/storage.py's own docstring
# for why the whole layer moved together rather than only the pieces primes_tab.py
# itself needs) -- app-level code below (totals worker, search worker, settings
# wsl_helpers) still calls these directly. list_source_files/read_source_file_headers/
# format_big_int/digit_count_floor/_offset_from_filename/FlowRow are no longer called
# directly here -- their last remaining call sites moved out with the Generation tab
# (primeatlas/generation.py/generation_tab.py, Faza 3, 2026-08-23) -- every extracted
# tab module that needs them imports its own copy directly from primeatlas.storage/
# primeatlas.widgets now.
from primeatlas.storage import (  # noqa: E402
    LOW_FLOOR_CUTOFF, list_pietra, list_source_filenames,
    load_totals_cache, save_totals_cache,
    update_pietro_totals_cache, format_duration, format_bytes,
    aggregate_write_seconds_by_pietro, find_prime_in_floor,
)
# generation: extracted during the refactor branch's Faza 3 (tab-by-tab backend/UI
# split, 2026-08-23), alongside the Generation tab's own UI split
# (primeatlas/generation_tab.py) -- see that module's own docstring. Only the names
# _offer_generate_missing_prime_window/_offer_generate_missing_constellation/
# ConstellationsCalcTab/ConstellationsRecordsTab construction (_eval_quick_number) and
# _build_settings_tab's wsl_helpers dict still call directly are imported here;
# everything else the Generation tab itself needs is imported locally inside
# primeatlas/generation_tab.py.
from primeatlas.generation import (  # noqa: E402
    QUICK_GEN_MAX_WINDOW_WIDTH, PRIMESIEVE_MAX_STOP, _eval_quick_number,
    build_loop_argv, build_constellation_finder_argv, build_wsl_logged_command,
    build_primesieve_argv, generation_log_paths, WslLoggedRunner, LocalLoggedRunner,
    build_pip_install_argv, estimate_wsl_available_ram_bytes, recommended_max_windows,
    find_continuation_target_idx,
)
# PRIMESIEVE_QUERY_SCRIPT/windows_path_to_wsl/build_primesieve_query_argv/
# run_primesieve_query_wsl used to be imported/defined here for the "primesieve"
# calculator sub-tab -- moved FULLY into primeatlas/primesieve_calc_tab.py during the
# refactor branch's Faza 4 (2026-08-24), alongside that sub-tab's own UI split, since
# nothing else in this file calls any of the four.

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

# GOLDBACH_VIZ_ROWS_PER_COL/GOLDBACH_VIZ_MAX_COLS/GOLDBACH_CASCADE_ROW_CAP/
# GOLDBACH_VIZ_CHIP_ROWS_PER_PAGE/GOLDBACH_DECOMPOSE_ROW_CAP/GOLDBACH_LEAN_REPO_URL moved
# to primeatlas/research_goldbach_tab.py during the refactor branch's Faza 3 (tab-by-tab
# backend/UI split, 2026-08-23), alongside the rest of the Goldbach sub-tab's own UI
# split -- see that module's own docstring.



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


# _FlowRow moved to primeatlas/widgets.py (renamed FlowRow) during the refactor branch's
# Faza 3 (2026-08-23), alongside the "Prime numbers" tab's own UI split -- see that
# module's own docstring. Imported back at this file's top as `FlowRow as _FlowRow`, so
# every existing call site below (still used directly by the Constellations tab's own
# preview panes) is unchanged.


# _draw_growth_chart moved to primeatlas/benchmark_tab.py during the refactor branch's
# Faza 3 (2026-08-23), alongside the rest of the Benchmark tab's widgets -- see that
# module's own docstring. Adapted there to accept an explicit translator= parameter
# instead of reading this file's module-level T() global (unavailable from primeatlas/,
# see that module's own comment on why).


def _build_gui():
    import tkinter as tk
    from tkinter import ttk, messagebox
    # The Settings tab's widgets live in their own package (primeatlas/) as a
    # proper class (SettingsTab), not more nested functions on PortalBrowserApp -- see
    # this file's module docstring and settings_tab.py's own docstring for the full
    # rationale. Imported here (inside _build_gui(), not at module top level) for the
    # same reason tkinter itself is: it keeps this module's top-level prefix (everything
    # above _build_gui) importable/testable without tkinter installed. GenerationConsole
    # is no longer imported here -- its only user (the Generation tab) now imports it
    # directly inside primeatlas/generation_tab.py.
    from primeatlas.settings_tab import SettingsTab

    class PortalBrowserApp(tk.Tk):
        def __init__(self):
            super().__init__()
            self._apply_theme(APP_SETTINGS.theme)
            self.title(T("app.title"))
            self.geometry("1050x680")

            # status_frame/notebook are BUILT here but deliberately left UNPACKED until
            # _finish_loading_screen() reveals them -- see the loading_frame block just
            # below for why (Faza 2 of the refactor branch, 2026-08-23: previously the
            # notebook was packed immediately and the six _build_*_section/_build_*_tab
            # calls plus the three post-build reload_*_tree()/reload_benchmark_log() calls
            # all ran synchronously against an already-visible (but empty/half-built)
            # window, which is what made every one of those steps look like a freeze
            # rather than a load). ttk widgets can be constructed and have children added
            # while unpacked -- only the geometry manager step (.pack itself) is deferred.
            #
            # status_frame is packed BEFORE the notebook, not after, once both are
            # revealed. tkinter's pack() geometry manager carves up the toplevel's cavity
            # in the ORDER widgets are packed, not by `side` -- a widget packed with
            # fill=both, expand=True (the notebook) claims however much of the cavity is
            # available AT THE TIME it's packed, so if it goes first, anything packed
            # afterward (status_frame -- the bottom status bar showing the grand total
            # prime count/generation time plus the totals-scan progress bar) only gets
            # whatever sliver is left once tab content exceeds the window's height. This
            # is a classic Tk pitfall: dock-to-edge widgets like a status bar must be
            # packed before the fill=both,expand=True central widget, not after -- it
            # only becomes visible once a tab's content grows tall enough to exceed the
            # default 1050x680 window size. Packing status_frame FIRST guarantees its own
            # natural height is always reserved; the notebook (still fill=both,
            # expand=True) then fills whatever remains, exactly as intended.
            status_frame = ttk.Frame(self)
            self._status_frame = status_frame  # stashed so _finish_loading_screen can pack it
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

            # Loading screen (Faza 2, 2026-08-23) -- ported from the cudasieve branch's own
            # startup loading bar (commit a4df0fd) and extended to also cover the async
            # tree scans below, not just the six tab-build calls. Packed and painted
            # (self.update()) BEFORE any tab is built, so the window shows something
            # immediately instead of sitting blank while ttk.Notebook/Treeview widgets for
            # six tabs are constructed.
            loading_frame = ttk.Frame(self)
            loading_frame.pack(fill="both", expand=True)
            loading_center = ttk.Frame(loading_frame)
            loading_center.place(relx=0.5, rely=0.5, anchor="center")
            ttk.Label(loading_center, text=T("app.title"),
                      font=("TkDefaultFont", 16, "bold")).pack(pady=(0, 12))
            self._loading_caption = tk.StringVar(value=T("app.loading_starting"))
            ttk.Label(loading_center, textvariable=self._loading_caption).pack(pady=(0, 8))
            self._loading_bar = ttk.Progressbar(loading_center, orient="horizontal",
                                                 mode="indeterminate", length=280)
            self._loading_bar.pack()
            self._loading_bar.start(12)
            self._loading_frame = loading_frame
            self.update()

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

            loading_steps = (
                (T("tabs.primes"), self._build_primes_section),
                (T("tabs.constellations"), self._build_constellations_section),
                (T("tabs.research"), self._build_research_section),
                (T("tabs.generation"), self._build_generation_tab),
                (T("tabs.benchmark"), self._build_benchmark_tab),
                (T("tabs.settings"), lambda: self._build_settings_tab(SettingsTab)),
            )
            for step_name, step_fn in loading_steps:
                self._loading_caption.set(T("app.status_loading_step", step=step_name))
                self.update()
                step_fn()

            # Floor-total background worker: reading every source window's
            # header to sum a whole floor's prime count is NOT cheap on this project's real
            # storage (measured ~78s for one 15,101-file floor, ~5ms/file -- per-file open()
            # latency on the underlying mount, not the tiny header itself) -- doing that on
            # the GUI thread is exactly the kind of freeze the paginated file list was built
            # to avoid (see PrimesTab._populate_pietro_node's docstring). ONE daemon worker
            # thread owns self._totals_cache exclusively (loads it once here, then only the
            # worker thread ever reads/writes/saves it -- see update_pietro_totals_cache());
            # the main thread never touches that dict directly, only submits floor numbers
            # via self._totals_worker.submit() and receives results back via
            # _on_totals_worker_result, a primeatlas/background.py PersistentWorker instance
            # (see _totals_job's own docstring for the request/result shape). The DISPLAY-
            # side counterpart of this cache (self._pietro_total_known) now lives entirely
            # inside primeatlas/primes_tab.py's PrimesTab -- see that class's own
            # populate_floors()/update_floor_row() docstrings.
            self._totals_cache = {}
            self._reload_totals_caches()
            self._computing_all_totals = False
            self._totals_batch_size = 0   # fixed at the START of a "compute all" batch --
                                           # NOT re-read from PrimesTab's own floor-node map
                                           # on every result, so the progress bar's
                                           # denominator can't shift mid-batch (e.g. after a
                                           # Refresh)
            self._grand_total_sum = 0
            self._grand_total_bytes = 0  # on-disk footprint total, mirrors _grand_total_sum
                                          # but for bytes instead of prime count -- see
                                          # update_pietro_totals_cache()'s total_bytes and
                                          # format_bytes()
            self._grand_total_seen = set()
            self._grand_total_seconds = 0.0  # mirrors _grand_total_sum's role for the
                                              # "GRAND TOTAL" status line, giving it a time
                                              # total alongside the prime-count total --
                                              # the underlying per-floor generation-seconds
                                              # dict this sums (base_exponent -> seconds)
                                              # now lives inside PrimesTab, seeded fresh on
                                              # every reload_primes_tree() scan (see that
                                              # class's own populate_floors()).
            # Faza 1 background-job migration (2026-08-23, second half -- see
            # primeatlas/background.py's PersistentWorker docstring for the full audit):
            # this used to be its own hand-rolled threading.Thread + two queue.Queue()s +
            # self.after(150, self._poll_totals_results) block, identical in shape to five
            # other workers in this file. _totals_job is the one part that's genuinely
            # specific to this feature; PersistentWorker owns the thread/queues/polling.
            self._totals_worker = background.PersistentWorker(
                self, self._totals_job, on_result=self._on_totals_worker_result,
                on_progress=self._on_pietro_total_start)

            # Search worker: number/constellation search needs to run off the GUI thread,
            # or it freezes the whole application while searching. find_prime_in_floor()'s
            # binary search is normally fast (O(log N) file opens -- see its own
            # docstring), but find_constellation_participation() can decode dozens of
            # full hit files on a floor's first-ever search (nothing cached yet), which
            # is exactly the kind of disk-bound work the totals worker above already
            # exists to keep off the GUI thread -- same PersistentWorker shape, reusing
            # the SAME status/progress bar the totals worker uses (one shared status bar
            # for both features, not a second one). See
            # _search_job/_on_search_worker_result/_start_search_job below.
            self._search_busy = False
            self._search_worker = background.PersistentWorker(
                self, self._search_job, on_result=self._on_search_worker_result,
                on_progress=self._on_search_worker_progress)

            # primesieve calculator worker (Liczby pierwsze -> primesieve sub-tab) and
            # primality-testing worker (Liczby pierwsze -> Testy pierwszosci sub-tab)
            # used to live here as two more hand-attached PersistentWorker instances --
            # moved FULLY into their own PrimesieveCalcTab/PrimalityTab classes during
            # the refactor branch's Faza 4 (2026-08-24, the phase that shrinks the app
            # shell further after every tab was already split out during Faza 3), since
            # each worker is confirmed exclusive to its own one sub-tab (unlike the
            # shared search/totals workers above, which stay here) -- see
            # primeatlas/primesieve_calc_tab.py and primeatlas/primality_tab.py's own
            # docstrings.

            # Goldbach structural-window worker (Badania -> Goldbach sub-tab), its
            # Wizualizacja/decompose Toplevel state, and all their pagination fields used
            # to live here -- moved FULLY into ResearchGoldbachTab during the refactor
            # branch's Faza 3 (2026-08-23), since it's confirmed exclusive to that one
            # sub-tab (unlike the shared search/totals workers below, which stay here) --
            # see primeatlas/research_goldbach_tab.py's own docstring.

            # Constellation-records-table scan worker (Constellations -> Tabela rekordow
            # sub-tab) used to live here as its own PersistentWorker -- moved FULLY into
            # ConstellationsRecordsTab itself during the refactor branch's Faza 3
            # (2026-08-23), since it's confirmed exclusive to that one sub-tab (unlike the
            # shared search/totals workers below, which stay here) -- see
            # primeatlas/constellations_records_tab.py's own docstring.

            # "Generate missing fragment, then re-search" state (_pending_search_after_
            # prime_gen/_pending_search_after_const_gen/_pending_goldbach_retry_op) and
            # the shared-progress-bar step counters (_gen_step_total/_gen_loop_run_count/
            # _gen_loop_iteration) used to live here -- moved into GenerationTab's own
            # __init__ during the refactor branch's Faza 3 (2026-08-23), since they're
            # exclusively read/written by Generation-tab methods now (see
            # primeatlas/generation_tab.py's own docstring). App-level code that sets the
            # first three from OUTSIDE the tab (_offer_generate_missing_prime_window/
            # _offer_generate_missing_constellation/_goldbach_offer_generate_missing_range,
            # all below) reaches in via self.generation_tab_widget.X instead.

            # reload_benchmark_log() stays synchronous here -- it's one small CSV read,
            # not a per-floor disk scan (see reload_primes_tree()'s own docstring for the
            # cost distinction) -- so it's cheap enough to keep on the GUI thread even
            # during the loading screen.
            self.benchmark_tab_widget.reload_benchmark_log()
            # reload_primes_tree()/reload_constellations_tree() are BOTH asynchronous as
            # of Faza 2 (see their own docstrings) -- each dispatches its disk scan onto
            # background.run_in_background() and returns immediately. _loading_startup_
            # pending tracks which of the two startup scans are still outstanding;
            # _on_primes_tree_scan_done/_on_hits_tree_scan_done each discard their own
            # name from this set and call _finish_loading_screen() once it's empty, which
            # is what actually reveals status_frame/notebook. Every LATER call to either
            # reload function (Refresh button, storage-path change, etc.) finds this
            # attribute already None (see _finish_loading_screen) and skips the check.
            self._loading_startup_pending = {"primes", "constellations"}
            self._loading_caption.set(T("app.status_loading_data"))
            self.update()
            self.reload_primes_tree()  # this ALSO kicks off the floor-totals scan for every
                                        # floor -- see reload_primes_tree()'s docstring
            self.reload_constellations_tree()

        def _finish_loading_screen(self):
            """Reveals the real UI (status_frame + notebook) and tears down the loading
            overlay -- called once from _on_primes_tree_scan_done/_on_hits_tree_scan_done,
            whichever of the two startup scans finishes LAST (see _loading_startup_pending's
            own comment in __init__). Safe to call at most once per app lifetime: both
            callers null out _loading_startup_pending before calling this, and every other
            reload_*_tree() call site checks that attribute is still a non-empty set before
            ever touching this method."""
            self._loading_bar.stop()
            self._loading_frame.destroy()
            self._status_frame.pack(fill="x", side="bottom")
            self.main_notebook.pack(fill="both", expand=True)

        # --- Floor-total background worker ------------------------------------------

        def _reload_totals_caches(self):
            """(Re-)loads _totals_cache (the totals worker's OWN incremental-cache copy,
            see update_pietro_totals_cache()) from PORTAL_FOLDER's own
            .portal_totals_cache.json -- factored out of __init__ so reload_primes_tree()
            can call this too, on every refresh, not just once at app startup. Otherwise,
            after changing storage path in Settings and clicking Refresh, this worker-
            owned cache would still reflect the PREVIOUS location.

            Root cause of the bug this originally fixed: this dict used to be built ONCE
            in __init__ against whatever PORTAL_FOLDER was active when the app launched,
            then never reloaded -- a later storage-path change rebinds the PORTAL_FOLDER
            global (see _set_portal_folder) but left it holding the OLD location's data
            in memory. update_pietro_totals_cache()'s incremental-cache logic keys this
            cache PURELY BY FILENAME within each "10p{N}" entry, with no portal_folder
            scoping at all -- so if a NEWLY selected location happens to have its own
            floor with the same number (and prime_sieve_v1.py assigns filenames
            deterministically from floor+offset, so a same-number floor in two different
            locations very plausibly has same-NAMED files), the stale entry made it treat
            that location's real file as "already read" and served the OLD location's
            cached count without ever opening the new file.

            The DISPLAY-side counterpart of this same on-disk cache (what the "Prime
            numbers" tree actually shows) now lives entirely in primeatlas/primes_tab.py's
            PrimesTab -- reload_primes_tree()'s own async scan re-reads it fresh from disk
            every time (see _primes_tree_scan()) and hands the result to
            PrimesTab.populate_floors(), so there's no equivalent stale-copy risk there to
            fix by hand."""
            self._totals_cache = load_totals_cache(PORTAL_FOLDER)  # worker-owned copy

        def _totals_job(self, base_exponent, report_progress):
            """Runs on PersistentWorker's own daemon thread, one base_exponent at a time --
            see that class's docstring for why this shape replaced a hand-rolled
            threading.Thread + two queue.Queue()s. report_progress(base_exponent) fires the
            INSTANT this request is picked up, before the (possibly ~1 minute, for a
            heavily-populated floor) scan itself runs -- without this, the status/progress
            bar would sit unchanged for that whole stretch, making an in-progress scan look
            like it's not working. Catches its own exceptions (rather than letting
            PersistentWorker's generic error path handle it) so the failure can still be
            attributed to the RIGHT base_exponent -- see PersistentWorker's own docstring
            for why that matters."""
            report_progress(base_exponent)
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
                return base_exponent, total, file_count, new_read, None, total_bytes
            except Exception as e:  # noqa: BLE001 -- must never kill the worker thread
                return base_exponent, None, None, None, str(e), None

        def _on_totals_worker_result(self, payload, error):
            """Main-thread callback for _totals_job -- error is only ever non-None for a
            genuine PersistentWorker/framework-level failure (report_progress itself
            raising, say), since _totals_job catches everything else internally and folds
            it into payload's own error slot instead (see that method's docstring)."""
            if error is not None:
                self.status.set(str(error))
                return
            base_exponent, total, file_count, new_read, job_error, total_bytes = payload
            if job_error is not None:
                self.status.set(T("primes.status_error_sum", base_exponent=base_exponent, error=job_error))
            else:
                self._on_pietro_total_ready(base_exponent, total, file_count, new_read, total_bytes)

        def _on_pietro_total_start(self, base_exponent):
            """Fires the moment the worker PICKS UP a request -- see _totals_job's
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
            """Main-thread completion handler for the totals worker's result -- the
            actual tree-row update, plus the floor-nav page-total label refresh if this
            floor happens to be the active one, is delegated to PrimesTab.update_floor_row
            (see that method's own docstring); this app-level method keeps only the
            grand-total batch bookkeeping and status/progress-bar text, which don't
            belong to any one tab (the status bar and totals_progress widget are shared
            with the search worker too, see __init__'s own comment on that)."""
            self.primes_tab_widget.update_floor_row(base_exponent, total, file_count, total_bytes)
            gen_seconds = self.primes_tab_widget.get_gen_seconds(base_exponent)

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
            pietra = self.primes_tab_widget.get_pietro_node_keys()
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
                self._totals_worker.submit(base_exponent)

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
            """The top-level 'Prime numbers' notebook tab is itself a small ttk.Notebook,
            not a single flat frame -- 'Magazyn' (Storage) holds exactly what this whole
            tab used to be (the floor/file browser + search, built by _build_primes_tab()
            below, unchanged apart from its parent frame now being
            self.primes_storage_tab instead of self.primes_tab directly), alongside two
            sibling tabs: self.primes_primesieve_tab (a standalone libprimesieve
            calculator -- count/nth/next/prev prime, no on-disk storage involved) and
            self.primes_primality_tab (probabilistic primality testing + factorization
            for a single entered number). See _build_constellations_section() for the
            SAME nested-notebook pattern applied to the Constellations tab -- deliberately
            identical structure between the two so the app has one consistent way of
            giving a top-level section its own sub-tabs, not two diverging ones.

            All three sub-tabs are now thin wrappers around their own primeatlas/*.py
            classes (PrimesTab / PrimesieveCalcTab / PrimalityTab) -- the last two were
            extracted during the refactor branch's Faza 4 (2026-08-24), the phase after
            Faza 3 that shrinks the app shell further; see those two modules' own
            docstrings for why status_var/translator/totals_progress are the only three
            things injected into each."""
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

            from primeatlas.primesieve_calc_tab import PrimesieveCalcTab
            self.primesieve_calc_tab_widget = PrimesieveCalcTab(
                self.primes_primesieve_tab, status_var=self.status, translator=TRANSLATOR,
                totals_progress=self.totals_progress)
            self.primesieve_calc_tab_widget.pack(fill="both", expand=True)

            from primeatlas.primality_tab import PrimalityTab
            self.primality_tab_widget = PrimalityTab(
                self.primes_primality_tab, status_var=self.status, translator=TRANSLATOR,
                totals_progress=self.totals_progress)
            self.primality_tab_widget.pack(fill="both", expand=True)

        def _build_primes_tab(self):
            """Thin wrapper -- all of the Primes tab's actual widgets/logic live in
            primeatlas/primes_tab.py's PrimesTab class (Faza 3 of the refactor branch,
            tab-by-tab backend/UI split, 2026-08-23; see that module's own docstring).
            Local import, not module-level, for the same lazy-tkinter-import reason
            SettingsTab/BenchmarkTab are imported inside _build_gui() rather than at this
            file's top."""
            from primeatlas.primes_tab import PrimesTab
            self.primes_tab_widget = PrimesTab(
                self.primes_storage_tab, get_portal_folder=lambda: PORTAL_FOLDER,
                status_var=self.status, translator=TRANSLATOR,
                update_nav_controls=_update_nav_controls, render_page=_render_page,
                page_size=PAGE_SIZE, floor_page_size=FLOOR_PAGE_SIZE,
                reload_primes_tree=self.reload_primes_tree,
                start_search_job=self._start_search_job,
                is_search_busy=lambda: self._search_busy,
                offer_generate_missing_prime_window=lambda be, num:
                    self._offer_generate_missing_prime_window("prime", be, num),
                submit_totals_job=lambda be: self._totals_worker.submit(be))
            self.primes_tab_widget.pack(fill="both", expand=True)

        def _primes_tree_scan(self, portal_folder, _report_progress):
            """Runs OFF the GUI thread (see reload_primes_tree()/background.
            run_in_background()) -- every line here is pure disk I/O with no widget
            access, split out of what used to be the first half of reload_primes_tree()
            itself (Faza 2 of the refactor branch, 2026-08-23). Returns a plain dict;
            _on_primes_tree_scan_done does all the actual tree/widget mutation back on
            the main thread. portal_folder is passed in explicitly (captured by the
            caller at dispatch time) rather than read from the PORTAL_FOLDER global in
            here, so a storage-path change that happens WHILE this scan is running can
            never make it silently scan the wrong (newly-current) location.

            See reload_primes_tree()'s OLD docstring (still true, just relocated) for why
            prune_empty_pietro_dirs() runs unconditionally on every reload, why floors
            with no PRIME_WINDOW_*.bin files are filtered out, and why the totals caches
            are reloaded fresh from disk every time rather than only once at startup."""
            prune_empty_pietro_dirs(portal_folder)
            pietro_total_known = {}
            for _key, _entry in load_totals_cache(portal_folder).items():
                if _key.startswith("10p") and _key[3:].isdigit():
                    pietro_total_known[int(_key[3:])] = (
                        _entry.get("total", 0), _entry.get("file_count", 0),
                        _entry.get("total_bytes", 0))
            totals_cache = load_totals_cache(portal_folder)  # worker-owned copy
            pietro_gen_seconds = aggregate_write_seconds_by_pietro(
                read_benchmark_log(portal_folder)[1])
            pietra = [be for be in list_pietra(portal_folder)
                      if list_source_filenames(portal_folder, be)]
            return {
                "pietro_total_known": pietro_total_known,
                "totals_cache": totals_cache,
                "pietro_gen_seconds": pietro_gen_seconds,
                "pietra": pietra,
            }

        def reload_primes_tree(self):
            """Rebuilds the floor list from disk (picks up newly created/removed 10pN
            folders) AND re-runs the totals scan for every floor -- so
            pressing Refresh after generating new windows is enough to see updated totals,
            no separate button needed. This is NOT a full re-read of everything: each
            floor's total is cached (see update_pietro_totals_cache()'s docstring) keyed by
            filename, so a floor with no new files costs one cheap os.listdir() + an
            in-memory set diff, and a floor WITH new files only pays for reading THOSE
            files' headers, not the whole floor again.

            Faza 2 (2026-08-23): the actual disk scan (_primes_tree_scan) now runs on
            background.run_in_background() instead of the GUI thread -- this method just
            dispatches it and returns immediately; _on_primes_tree_scan_done does the
            real tree-population work once the scan comes back. A busy/pending pair of
            flags coalesces re-entrant calls (e.g. the user mashing Refresh, or a
            generation-finished callback firing while a Refresh is still in flight) into
            at most one extra rerun after the in-flight scan settles, rather than
            spawning a second overlapping scan thread. PORTAL_FOLDER is captured HERE,
            at dispatch time, and compared again in _on_primes_tree_scan_done -- if a
            storage-path change rebound the global while this scan was still running, the
            result is discarded and a fresh scan against the NEW folder is queued instead
            (see that method's own docstring)."""
            if getattr(self, "_primes_tree_reload_busy", False):
                self._primes_tree_reload_pending = True
                return
            self._primes_tree_reload_busy = True
            portal_folder = PORTAL_FOLDER
            background.run_in_background(
                self, lambda report_progress: self._primes_tree_scan(portal_folder, report_progress),
                on_done=lambda result, error: self._on_primes_tree_scan_done(
                    portal_folder, result, error))

        def _on_primes_tree_scan_done(self, portal_folder, result, error):
            """Main-thread callback for _primes_tree_scan -- see reload_primes_tree()'s
            own docstring for the busy/pending/staleness handling this implements."""
            self._primes_tree_reload_busy = False
            stale = portal_folder != PORTAL_FOLDER
            if getattr(self, "_primes_tree_reload_pending", False) or stale:
                self._primes_tree_reload_pending = False
                self.reload_primes_tree()
                return
            if error is not None:
                self.status.set(T("primes.status_reload_error", error=str(error)))
                return
            self._totals_cache = result["totals_cache"]
            pietra = result["pietra"]
            # The actual tree rebuild (rows, per-floor known totals/gen-seconds display
            # state) is owned by PrimesTab now -- see populate_floors()'s own docstring.
            # This app-level method keeps only the totals_cache (worker-owned copy,
            # unrelated to what any one tab renders), the status text, kicking off the
            # background totals scan, and the loading-screen bookkeeping.
            self.primes_tab_widget.populate_floors(
                pietra, result["pietro_total_known"], result["pietro_gen_seconds"])
            self.status.set(T("app.status_portal_with_count", folder=portal_folder, count=len(pietra)))
            self._compute_all_pietro_totals()

            pending = getattr(self, "_loading_startup_pending", None)
            if pending:
                pending.discard("primes")
                if not pending:
                    self._finish_loading_screen()
        # --- Search worker -- shared by both "Prime numbers" and
        # "Constellations" search boxes, see the __init__ comment above self._search_worker's
        # construction for the full rationale. ------------------------------------------------

        def _start_search_job(self, kind, base_exponent, number):
            """Hands the actual (potentially slow) file-scanning work off to
            self._search_worker's daemon thread (a PersistentWorker). Only fast/instant validation (isdigit,
            digit_count_floor, list_pietra's no-I/O floor-existence check) happens on the
            GUI thread, in the caller, before this is ever reached. Disables BOTH search
            buttons while a job is in flight -- the two features share one worker thread
            and one status/progress bar, so only one search runs at a time system-wide,
            same reasoning _on_quick_generate_clicked already applies to
            self._loop_runner."""
            self._search_busy = True
            self.primes_tab_widget.search_button.configure(state="disabled")
            self.constellations_hits_tab_widget.hits_search_button.configure(state="disabled")
            self.totals_progress.stop()
            self.totals_progress.configure(mode="indeterminate")
            self.totals_progress.start(80)
            if kind == "prime":
                self.status.set(T("primes.status_searching", number=number, base_exponent=base_exponent))
            else:
                self.status.set(T("const.status_searching", number=number, base_exponent=base_exponent))
            self._search_worker.submit(
                {"kind": kind, "base_exponent": base_exponent, "number": number})

        def _search_job(self, job, report_progress):
            """Runs on PersistentWorker's own daemon thread. While a "const" job is in
            flight, this thread is ALSO the sole owner of
            self.constellations_hits_tab_widget.hit_set_cache (the GUI thread never
            mutates it directly anymore, only reads the finished participation list
            handed back via the result) -- _search_busy blocking new searches from the
            GUI side means only one job is ever in flight, so this never races against
            itself. Catches its own exceptions (see PersistentWorker's docstring for
            why) so the error can still be tagged with the right kind."""
            kind = job["kind"]
            base_exponent = job["base_exponent"]
            number = job["number"]
            try:
                if kind == "prime":
                    result = find_prime_in_floor(PORTAL_FOLDER, base_exponent, number)
                    return ("prime_done", base_exponent, number, result)
                else:
                    prime_result = find_prime_in_floor(PORTAL_FOLDER, base_exponent, number)
                    if prime_result is None:
                        return ("const_done", base_exponent, number, None, [])

                    def _progress(done, total):
                        report_progress(("const_progress", done, total))

                    participation = find_constellation_participation(
                        PORTAL_FOLDER, base_exponent, number,
                        self.constellations_hits_tab_widget.hit_set_cache,
                        progress_callback=_progress)
                    return ("const_done", base_exponent, number, prime_result, participation)
            except Exception as e:  # noqa: BLE001 -- must never kill the worker thread
                return (f"{kind}_error", base_exponent, number, str(e))

        def _on_search_worker_progress(self, payload):
            """Main-thread callback for _search_job's mid-job progress reports (the only
            kind it ever sends is "const_progress", during find_constellation_participation)."""
            kind = payload[0]
            if kind == "const_progress":
                _kind, done, total = payload
                self.totals_progress.stop()
                self.totals_progress.configure(
                    mode="determinate", maximum=max(1, total), value=done)
                self.status.set(T("const.status_search_progress", done=done, total=total))

        def _on_search_worker_result(self, payload, error):
            """Main-thread callback for _search_job's return value -- error is only ever
            non-None for a genuine PersistentWorker/framework-level failure, since
            _search_job catches everything else internally (see that method's docstring)."""
            if error is not None:
                self._finish_search_job()
                messagebox.showerror(T("common.dialog_search_title"), str(error))
                return
            kind = payload[0]
            if kind == "prime_done":
                _kind, base_exponent, number, result = payload
                self._finish_search_job()
                self.primes_tab_widget.on_prime_search_result(base_exponent, number, result)
            elif kind == "const_done":
                _kind, base_exponent, number, prime_result, participation = payload
                self._finish_search_job()
                self._on_const_search_result(base_exponent, number, prime_result, participation)
            else:  # "prime_error" / "const_error"
                _kind, _base_exponent, _number, job_error = payload
                self._finish_search_job()
                messagebox.showerror(T("common.dialog_search_title"), job_error)

        def _finish_search_job(self):
            self._search_busy = False
            self.primes_tab_widget.search_button.configure(state="normal")
            self.constellations_hits_tab_widget.hits_search_button.configure(state="normal")
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
            gen = self.generation_tab_widget
            plan = gen._quick_gen_plan_literal_range(number, number + 1)
            if plan.get("error"):
                return "skipped"
            if plan.get("already"):
                return "composite"
            if gen._loop_runner is not None and gen._loop_runner.is_running():
                messagebox.showinfo(T("quick.dialog_title"), T("quick.error_already_running"))
                return "skipped"
            if not messagebox.askyesno(
                    T("common.dialog_search_title"),
                    T("search.offer_generate_prime_window", number=f"{number:,}",
                      base_exponent=base_exponent,
                      rounded_start=f"{plan['rounded_start']:,}",
                      rounded_end=f"{plan['rounded_end']:,}")):
                return "skipped"
            gen._pending_search_after_prime_gen = {
                "kind": kind, "base_exponent": base_exponent, "number": number}
            self.status.set(T("search.status_generating_prime_window", number=f"{number:,}"))
            target_idx = (plan["rounded_start"] - 10 ** plan["floor"]) // QUICK_GEN_MAX_WINDOW_WIDTH
            if plan["rounded_start"] > PRIMESIEVE_MAX_STOP:
                gen._apply_orchestrator_direct_params_and_run(plan["floor"], target_idx, 1)
            else:
                gen._apply_primesieve_params_and_run(plan["floor"], target_idx, 1)
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

            The second caller, ConstellationsCalcTab.search_selected() (Kalkulator
            konstelacji), checks something more specific instead: whether the ONE pattern it's asking
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
            gen = self.generation_tab_widget
            if gen._const_runner is not None and gen._const_runner.is_running():
                messagebox.showinfo(T("quick.dialog_title"), T("quick.error_already_running"))
                return False
            if not messagebox.askyesno(
                    T("common.dialog_search_title"),
                    T("search.offer_generate_constellation", number=f"{number:,}",
                      base_exponent=base_exponent)):
                return False
            gen._pending_search_after_const_gen = {
                "kind": "const", "base_exponent": base_exponent, "number": number}
            self.status.set(T("search.status_generating_constellation", base_exponent=base_exponent))
            gen._const_base_exponent_var.set(str(base_exponent))
            gen._on_run_constellation()
            return True

        # --- Tab 2: Constellations (constellation hits) ---------------------------------

        def _build_constellations_section(self):
            """Thin wrapper -- all three of the Constellations tab's actual widgets/logic
            live in primeatlas/constellations_hits_tab.py (ConstellationsHitsTab, the
            "Magazyn" sub-tab), primeatlas/constellations_calc_tab.py
            (ConstellationsCalcTab, "Kalkulator konstelacji"), and
            primeatlas/constellations_records_tab.py (ConstellationsRecordsTab, "Tabela
            rekordow") -- Faza 3 of the refactor branch, tab-by-tab backend/UI split,
            2026-08-23; see each module's own docstring. Local imports, not module-level,
            for the same lazy-tkinter-import reason SettingsTab/BenchmarkTab/PrimesTab are
            imported inside their own _build_*_tab() methods rather than at this file's
            top.

            Construction order below doesn't matter for any of the deferred-lambda
            callables passed in -- none of them are resolved until actually CALLED, so
            it's safe for the calculator/records tabs to reference
            self.constellations_hits_tab_widget even though it's constructed first, and
            safe for anything to reference either sibling regardless of build order (see
            primeatlas/primes_tab.py's own docstring for the general construction-order
            hazard this avoids)."""
            from primeatlas.constellations_hits_tab import ConstellationsHitsTab
            from primeatlas.constellations_calc_tab import ConstellationsCalcTab
            from primeatlas.constellations_records_tab import ConstellationsRecordsTab

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

            self.constellations_hits_tab_widget = ConstellationsHitsTab(
                self.constellations_storage_tab,
                get_portal_folder=lambda: PORTAL_FOLDER, status_var=self.status,
                translator=TRANSLATOR, update_nav_controls=_update_nav_controls,
                render_page=_render_page, page_size=PAGE_SIZE,
                reload_constellations_tree=self.reload_constellations_tree,
                start_search_job=self._start_search_job,
                is_search_busy=lambda: self._search_busy,
                offer_generate_missing_prime_window=lambda be, num:
                    self._offer_generate_missing_prime_window("const", be, num))
            self.constellations_hits_tab_widget.pack(fill="both", expand=True)

            self.constellations_calc_tab_widget = ConstellationsCalcTab(
                self.constellations_calculator_tab, translator=TRANSLATOR,
                eval_quick_number=_eval_quick_number, get_portal_folder=lambda: PORTAL_FOLDER,
                select_hits_view=self._select_constellations_hits_view,
                set_hits_search_query=lambda number:
                    self.constellations_hits_tab_widget.set_search_query(number),
                trigger_hits_search=lambda:
                    self.constellations_hits_tab_widget.search_constellation(),
                offer_generate_missing_constellation=self._offer_generate_missing_constellation)
            self.constellations_calc_tab_widget.pack(fill="both", expand=True)

            self.constellations_records_tab_widget = ConstellationsRecordsTab(
                self.constellations_records_tab, get_portal_folder=lambda: PORTAL_FOLDER,
                status_var=self.status, translator=TRANSLATOR,
                update_nav_controls=_update_nav_controls, render_page=_render_page,
                page_size=PAGE_SIZE, eval_quick_number=_eval_quick_number,
                totals_progress=self.totals_progress)
            self.constellations_records_tab_widget.bind_jump_to_hits(
                self._jump_records_detail_to_hits)
            self.constellations_records_tab_widget.pack(fill="both", expand=True)

        def _select_constellations_hits_view(self):
            """Switches the main notebook to the Constellations tab AND its own
            sub-notebook to the Magazyn tab -- injected into ConstellationsCalcTab as
            select_hits_view (see that class's own docstring) and used directly by
            _jump_records_detail_to_hits below; app-level because it touches
            self.main_notebook/self.constellations_sub_notebook, neither of which any one
            sub-tab has (or should have) direct knowledge of."""
            self.main_notebook.select(self.constellations_tab)
            self.constellations_sub_notebook.select(self.constellations_storage_tab)

        def _jump_records_detail_to_hits(self, base_exponent, pattern, hit_base, position):
            """Registered with ConstellationsRecordsTab.bind_jump_to_hits() -- double-
            clicking a hit in the Tabela rekordow drill-down list jumps to the Magazyn
            tab's own tree/preview, landing on this exact number. Thin app-level glue
            between two sibling tabs, same shape as _on_const_search_result below."""
            self._select_constellations_hits_view()
            self.constellations_hits_tab_widget.select_pattern_in_tree(base_exponent, pattern)
            self.constellations_hits_tab_widget.load_preview()
            self.constellations_hits_tab_widget.jump_preview_to_row(hit_base, position)

        def _constellations_tree_scan(self, portal_folder, _report_progress):
            """Runs OFF the GUI thread -- see _primes_tree_scan's own docstring for the
            general shape/rationale (Faza 2 of the refactor branch, 2026-08-23). Same
            idempotent prune_empty_pietro_dirs() double-call as before (see
            reload_constellations_tree()'s OLD docstring, relocated below) -- now two
            INDEPENDENT background threads may call it back-to-back rather than the same
            GUI-thread call twice in a row, but the function's own try/except around each
            individual os.rmdir() (see its docstring) already makes that race harmless:
            worst case, one of the two calls finds a given empty subdir already gone and
            silently skips it.

            Only floors that actually HAVE at least one detected constellation hit --
            list_pietra() alone would include every floor with prime data, regardless of
            whether the constellation finder has ever been run against it (or ran and
            found nothing), cluttering this tree with entries that only ever expand into
            an empty "no hits" placeholder. See floor_has_constellation_hits()'s own
            docstring."""
            prune_empty_pietro_dirs(portal_folder)
            pietra = [be for be in list_pietra(portal_folder)
                      if floor_has_constellation_hits(portal_folder, be)]
            return {"pietra": pietra}

        def reload_constellations_tree(self):
            """Rebuilds the constellation-hits floor list from disk. This tab's own
            Refresh button can be clicked without reload_primes_tree() ever running in
            the same gesture (e.g. right after constellation-finding finishes -- see
            _on_constellation_finished()), so its own prune/scan is dispatched
            independently rather than relying on the OTHER tree's refresh to have
            already covered it.

            Faza 2 (2026-08-23): same async split as reload_primes_tree() -- the actual
            disk scan (_constellations_tree_scan) runs on background.run_in_background(),
            this method only dispatches it, and _on_hits_tree_scan_done does the real
            tree-population work once it comes back. Its own busy/pending flags and
            PORTAL_FOLDER capture-and-compare mirror reload_primes_tree()'s exactly --
            see that method's docstring for the full reasoning."""
            if getattr(self, "_hits_tree_reload_busy", False):
                self._hits_tree_reload_pending = True
                return
            self._hits_tree_reload_busy = True
            portal_folder = PORTAL_FOLDER
            background.run_in_background(
                self, lambda report_progress: self._constellations_tree_scan(portal_folder, report_progress),
                on_done=lambda result, error: self._on_hits_tree_scan_done(
                    portal_folder, result, error))

        def _on_hits_tree_scan_done(self, portal_folder, result, error):
            """Main-thread callback for _constellations_tree_scan -- see
            reload_constellations_tree()'s own docstring for the busy/pending/staleness
            handling this implements (identical shape to _on_primes_tree_scan_done)."""
            self._hits_tree_reload_busy = False
            stale = portal_folder != PORTAL_FOLDER
            if getattr(self, "_hits_tree_reload_pending", False) or stale:
                self._hits_tree_reload_pending = False
                self.reload_constellations_tree()
                return
            if error is not None:
                self.status.set(T("const.status_reload_error", error=str(error)))
                return
            self.constellations_hits_tab_widget.populate_floors(result["pietra"])

            pending = getattr(self, "_loading_startup_pending", None)
            if pending:
                pending.discard("constellations")
                if not pending:
                    self._finish_loading_screen()

        def _on_const_search_result(self, base_exponent, number, prime_result, participation):
            """Thin app-level orchestrator for a "const" search job's completion --
            unlike Primes tab's fully self-contained on_prime_search_result, this stays
            at the app level because it coordinates a genuine three-way handoff: the
            search worker's raw result, the Magazyn (hits) tab's display (see
            ConstellationsHitsTab.show_missing_result/show_search_participation/
            jump_to_search_match), and the Kalkulator konstelacji tab's pending-search
            state (calc.get_pending()/clear_pending()) -- neither sibling tab should own
            that coupling alone.

            calc_pending/calc_match: when this completion is for a search the
            constellation calculator itself kicked off, and this call is the one that
            actually reaches a final answer (not a "launched a generation run, wait for
            the re-search" detour), the matching pattern's node gets auto-selected in
            the Magazyn tree and the preview jumped straight to this number -- see the
            tail of this method. calc_pending is only ever CLEARED on a genuinely final
            outcome (declined/composite/no-participation/found) so it survives across
            however many generate-then-re-search hops a single calculator search needs;
            comparing against the LOCAL `calc_pending` copy captured at entry (rather
            than re-reading calc.get_pending() after clearing it) keeps the
            match/pattern lookup valid even after the pending state is gone."""
            hits = self.constellations_hits_tab_widget
            calc = self.constellations_calc_tab_widget
            calc_pending = calc.get_pending()
            calc_match = (calc_pending is not None
                          and calc_pending["base_exponent"] == base_exponent
                          and calc_pending["number"] == number)

            if prime_result is None:
                outcome = self._offer_generate_missing_prime_window("const", base_exponent, number)
                if outcome != "launched":
                    if calc_match:
                        calc.clear_pending()
                    hits.show_missing_result(base_exponent, number, outcome)
                return

            if not participation:
                # Empty result is genuinely ambiguous -- see
                # _offer_generate_missing_constellation()'s own docstring: no hit FILES at
                # all for this floor means constellation_finder_v1.py simply never ran
                # here, not that this specific number was checked and excluded.
                if (not list_constellation_hits(PORTAL_FOLDER, base_exponent)
                        and self._offer_generate_missing_constellation(base_exponent, number)):
                    return
                if calc_match:
                    calc.clear_pending()
            else:
                if calc_match:
                    calc.clear_pending()

            hits.show_search_participation(base_exponent, number, prime_result, participation)

            if calc_match and participation:
                # Jump straight to the SPECIFIC (k, variant) node the calculator computed
                # this number for -- same helper ConstellationsHitsTab's own
                # _on_search_result_activate() uses for a double-clicked result row, just
                # triggered automatically instead of requiring that extra click. If the
                # number happens to ALSO participate in some other pattern (shown in the
                # results list either way), this still lands on the one the user actually
                # asked about.
                match = next(
                    (rec for rec in participation
                     if rec["pattern"]["k"] == calc_pending["pattern"]["k"]
                     and rec["pattern"]["id"] == calc_pending["pattern"]["id"]), None)
                if match is not None:
                    hits.jump_to_search_match(base_exponent, calc_pending["pattern"], match)

        # --- Research tab: skeleton only (Faza 0) --------------------------------------

        # --- Research tab: nested notebook, ResearchGoldbachTab + 4 trivial ------------
        # placeholder sub-tabs (squares/polynomials/gaps/pi_approx -- Faza 0, no logic
        # yet) -------------------------------------------------------------------------

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
                proven) -- genuinely a different question shape, stays its own tab; the ONLY
                one of the five with real logic behind it so far (ResearchGoldbachTab, see
                primeatlas/research_goldbach_tab.py).
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

            The four non-Goldbach sub-tabs remain SKELETON ONLY, per Artur's own
            instruction (2026-08-17) -- each is a placeholder label; logic gets filled in
            incrementally, one sub-tab at a time, in later phases -- see each
            _build_research_*_tab() method below for where that content will go.

            ResearchGoldbachTab is constructed via dependency injection (same pattern as
            every other extracted tab -- see primeatlas/primes_tab.py's own docstring),
            local import for the same lazy-tkinter-import reason SettingsTab/BenchmarkTab/
            PrimesTab are imported inside their own _build_*_tab() methods rather than at
            this file's top. offer_generate_missing_range is the ONE callback that stays
            app-level -- see _goldbach_offer_generate_missing_range's own docstring and
            primeatlas/research_goldbach_tab.py's module docstring for why."""
            from primeatlas.research_goldbach_tab import ResearchGoldbachTab

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

            self.research_goldbach_tab_widget = ResearchGoldbachTab(
                self.research_goldbach_tab, get_portal_folder=lambda: PORTAL_FOLDER,
                status_var=self.status, translator=TRANSLATOR,
                update_nav_controls=_update_nav_controls,
                eval_quick_number=_eval_quick_number, page_size=PAGE_SIZE,
                totals_progress=self.totals_progress,
                offer_generate_missing_range=self._goldbach_offer_generate_missing_range)
            self.research_goldbach_tab_widget.pack(fill="both", expand=True)

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

        def _goldbach_offer_generate_missing_range(self, op, payload):
            """Offers to generate the primes storage a Wizualizacja/decompose job
            just found missing (MissingStorageRangeError, translated into this dict
            by the worker loop's own except MissingStorageRangeError blocks --
            see ResearchGoldbachTab._goldbach_job's docstring). Mirrors
            _offer_generate_missing_prime_window()'s askyesno pattern, but launches
            through _quick_gen_plan_literal_range()/_launch_direct_window_range() --
            the SAME path Quick-gen's own Range mode button uses -- instead of always
            forcing the primesieve engine directly the way that helper does: a Goldbach
            gap can span many windows (the whole floor up to needed_upto), not just the one
            window a single prime search needs, so the continuation-based
            orchestrator engine (fills from wherever the floor's storage already
            ends, up to the requested count) is the right fit here, not
            primesieve's "write exactly this one window" contract.

            This is the ONE piece of the Goldbach sub-tab's own logic that stays at the
            app level rather than moving into primeatlas/research_goldbach_tab.py's
            ResearchGoldbachTab (extracted during the refactor branch's Faza 3,
            2026-08-23) -- launching a generation run needs this app's own quick-gen
            planning/launch machinery (self._loop_runner, _quick_gen_plan_literal_range,
            _launch_direct_window_range), all shared app-level state also used by the
            Generation tab, not anything the Goldbach tab owns itself. Injected into
            ResearchGoldbachTab as the single `offer_generate_missing_range(op, payload)`
            callable (see that class's own docstring).

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
            gen = self.generation_tab_widget
            floor = payload["floor"]
            needed_upto = payload["needed_upto"]
            if gen._loop_runner is not None and gen._loop_runner.is_running():
                messagebox.showinfo(T("quick.dialog_title"), T("quick.error_already_running"))
                return
            plan = gen._quick_gen_plan_literal_range(10 ** floor, needed_upto + 1)
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
            gen._pending_goldbach_retry_op = op
            self.status.set(T("research_goldbach.status_generating_range", floor=floor))
            gen._launch_direct_window_range(
                plan["floor"], plan["target_idx_start"], plan["window_count_per_run"])

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

        def _build_generation_tab(self):
            """Thin wrapper -- the whole tab (Quick-gen panel, Section A/B/C forms,
            launch/poll/finish handlers) lives in primeatlas/generation_tab.py's
            GenerationTab now, extracted during the refactor branch's Faza 3
            (tab-by-tab backend/UI split, 2026-08-23) -- see that module's own
            docstring for the full design, including why research_goldbach_tab_widget
            is injected directly (Research tab is built before this one, see this
            file's own __init__ tab-build order) and which three pieces of cross-tab
            state (_pending_search_after_prime_gen/_pending_search_after_const_gen/
            _pending_goldbach_retry_op, plus the quick-gen launch methods) app-level
            code below reaches into via self.generation_tab_widget.X instead."""
            from primeatlas.generation_tab import GenerationTab

            self.generation_tab_widget = GenerationTab(
                self.generation_tab, get_portal_folder=lambda: PORTAL_FOLDER,
                status_var=self.status, translator=TRANSLATOR,
                totals_progress=self.totals_progress,
                reload_primes_tree=self.reload_primes_tree,
                reload_constellations_tree=self.reload_constellations_tree,
                research_goldbach_tab_widget=self.research_goldbach_tab_widget)
            self.generation_tab_widget.pack(fill="both", expand=True)

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
            back into this module. get_loop_defaults() reads
            self.generation_tab_widget._generation_settings, populated by GenerationTab's
            own construction (primeatlas/generation_tab.py, called just before this
            method) from .portal_generation_settings.json.

            build_wsl_logged_command here is wrapped in a lambda supplying the current
            PORTAL_FOLDER explicitly -- primeatlas/generation.py's own copy of this
            function takes portal_folder as an explicit argument instead of reading a
            bare module global (see that module's own docstring for why), but
            settings_tab.py still calls this entry with the original 3-arg shape
            (argv, log_path, exit_path), so the 4th argument is supplied here rather
            than changing settings_tab.py itself."""
            wsl_helpers = {
                "get_portal_folder": lambda: PORTAL_FOLDER,
                "set_portal_folder": self._set_portal_folder,
                "get_loop_defaults":
                    lambda: self.generation_tab_widget._generation_settings.get("loop", {}),
                "build_loop_argv": build_loop_argv,
                "build_constellation_finder_argv": build_constellation_finder_argv,
                "build_wsl_logged_command":
                    lambda argv, log_path, exit_path:
                        build_wsl_logged_command(argv, log_path, exit_path, PORTAL_FOLDER),
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
            """Thin wrapper -- all of the Benchmark tab's actual widgets/logic live in
            primeatlas/benchmark_tab.py's BenchmarkTab class (Faza 3 of the refactor
            branch, tab-by-tab backend/UI split, 2026-08-23; see that module's own
            docstring). Local import, not module-level, for the same lazy-tkinter-import
            reason SettingsTab/GenerationConsole are imported inside _build_gui() rather
            than at this file's top.

            update_nav_controls is passed in explicitly rather than BenchmarkTab
            importing it back from this file -- that would be circular (this file
            imports BenchmarkTab from primeatlas.benchmark_tab) -- see BenchmarkTab's
            own docstring for why this ONE shared helper stays here instead of moving
            into primeatlas/ alongside everything else this tab needed."""
            from primeatlas.benchmark_tab import BenchmarkTab
            self.benchmark_tab_widget = BenchmarkTab(
                self.benchmark_tab, get_portal_folder=lambda: PORTAL_FOLDER,
                status_var=self.status, translator=TRANSLATOR,
                update_nav_controls=_update_nav_controls)
            self.benchmark_tab_widget.pack(fill="both", expand=True)

    return PortalBrowserApp


def main():
    app_cls = _build_gui()
    app = app_cls()
    app.mainloop()


if __name__ == "__main__":
    main()
