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
# floor_meta (merge_floor_meta_into_benchmark_log) used to be imported here for the
# totals worker's own job -- moved to primeatlas/totals_search_coordinator.py during
# the refactor-phase2 branch's "God object" reduction (2026-08-26, see that module's
# own docstring), alongside the rest of the totals/search PersistentWorker mechanism.
# background.run_in_background()/read_benchmark_log used to be imported here for
# _primes_tree_scan/_constellations_tree_scan -- moved out with those two methods
# themselves to primeatlas/primes_tree_coordinator.py/constellations_tree_coordinator.py
# during the refactor-phase3 branch's continuation of the same "God object" reduction
# (2026-08-27, see either module's own docstring); nothing in this file needs either
# import directly anymore.
# pdf_writer/benchmark: extracted during the refactor branch's Faza 3 (tab-by-tab
# backend/UI split, 2026-08-23) -- see those modules' own docstrings. Now that
# render_constellation_records_pdf has ALSO moved out (to primeatlas/constellations.py,
# alongside the rest of the Constellations tab's backend), nothing in this file calls
# the pdf_writer helpers directly anymore -- everything the (now separate) Benchmark and
# Constellations tabs need lives in primeatlas/benchmark_tab.py and
# primeatlas/constellations_records_tab.py respectively, imported lazily/locally from
# inside their own build methods (see _build_gui()'s own lazy-tkinter-import convention).
# constellations: extracted during the refactor branch's Faza 3 (2026-08-23), alongside
# the Constellations tab's own UI split (primeatlas/constellations_hits_tab.py,
# constellations_calc_tab.py, constellations_records_tab.py) -- see that module's own
# docstring. find_constellation_participation moved out with the search worker itself
# (primeatlas/totals_search_coordinator.py, refactor-phase2's "God object" reduction,
# 2026-08-26); floor_has_constellation_hits moved out with _constellations_tree_scan
# itself (refactor-phase3, 2026-08-27, see constellations_tree_coordinator.py's own
# docstring). list_constellation_hits is the one name still called directly here, by
# _on_const_search_result below.
from primeatlas.constellations import list_constellation_hits  # noqa: E402
# storage: extracted during the refactor branch's Faza 3 (2026-08-23), alongside the
# "Prime numbers" tab's UI split (primeatlas/primes_tab.py) -- see that module's own
# docstring. update_pietro_totals_cache/save_totals_cache/format_duration/format_bytes/
# find_prime_in_floor moved out with the totals/search worker mechanism
# (primeatlas/totals_search_coordinator.py, refactor-phase2's "God object" reduction,
# 2026-08-26). list_pietra/list_source_filenames/load_totals_cache/
# aggregate_write_seconds_by_pietro moved out with _primes_tree_scan/
# _constellations_tree_scan themselves (refactor-phase3, 2026-08-27, see
# primes_tree_coordinator.py/constellations_tree_coordinator.py's own docstrings).
# LOW_FLOOR_CUTOFF stays -- _build_settings_tab's wsl_helpers dict below still needs
# it directly. list_source_files/read_source_file_headers/format_big_int/
# digit_count_floor/_offset_from_filename/FlowRow are no longer called directly
# here -- their last remaining call sites moved out with the Generation tab
# (primeatlas/generation.py/generation_tab.py, Faza 3, 2026-08-23) -- every extracted
# tab module that needs them imports its own copy directly from primeatlas.storage/
# primeatlas.widgets now.
from primeatlas.storage import LOW_FLOOR_CUTOFF  # noqa: E402
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
    build_cudasieve_status_argv, build_cudasieve_fetch_license_argv,
    build_cudasieve_build_argv, run_cudasieve_wsl_blocking,
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

# How long after __init__ finishes to fire the app self-update auto-check (task #524) --
# see PortalBrowserApp.__init__'s own comment at the call site. Long enough that it never
# competes with the loading screen or the two startup tree scans for attention/bandwidth,
# short enough that it still fires well within the first minute of a normal session.
_APP_UPDATE_STARTUP_CHECK_DELAY_MS = 5000

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
    from tkinter import ttk
    # The Settings tab's widgets live in their own package (primeatlas/) as a
    # proper class (SettingsTab), not more nested functions on PortalBrowserApp -- see
    # this file's module docstring and settings_tab.py's own docstring for the full
    # rationale. Imported here (inside _build_gui(), not at module top level) for the
    # same reason tkinter itself is: it keeps this module's top-level prefix (everything
    # above _build_gui) importable/testable without tkinter installed. GenerationConsole
    # is no longer imported here -- its only user (the Generation tab) now imports it
    # directly inside primeatlas/generation_tab.py.
    from primeatlas.settings_tab import SettingsTab
    from primeatlas.totals_search_coordinator import TotalsSearchCoordinator
    from primeatlas.primes_tree_coordinator import PrimesTreeCoordinator
    from primeatlas.constellations_tree_coordinator import ConstellationsTreeCoordinator
    from primeatlas.generation_offer_coordinator import GenerationOfferCoordinator

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
            # starts, see TotalsSearchCoordinator.compute_all_pietro_totals()/
            # _on_pietro_total_start() (primeatlas/totals_search_coordinator.py).
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
            self.rings_tab = ttk.Frame(notebook)
            self.benchmark_tab = ttk.Frame(notebook)
            self.settings_tab_container = ttk.Frame(notebook)
            notebook.add(self.primes_tab, text=T("tabs.primes"))
            notebook.add(self.constellations_tab, text=T("tabs.constellations"))
            notebook.add(self.research_tab, text=T("tabs.research"))
            notebook.add(self.generation_tab, text=T("tabs.generation"))
            notebook.add(self.rings_tab, text=T("tabs.rings"))
            notebook.add(self.benchmark_tab, text=T("tabs.benchmark"))
            notebook.add(self.settings_tab_container, text=T("tabs.settings"))

            loading_steps = (
                (T("tabs.primes"), self._build_primes_section),
                (T("tabs.constellations"), self._build_constellations_section),
                (T("tabs.research"), self._build_research_section),
                (T("tabs.generation"), self._build_generation_tab),
                (T("tabs.rings"), self._build_rings_tab),
                (T("tabs.benchmark"), self._build_benchmark_tab),
                (T("tabs.settings"), lambda: self._build_settings_tab(SettingsTab)),
            )
            for step_name, step_fn in loading_steps:
                self._loading_caption.set(T("app.status_loading_step", step=step_name))
                self.update()
                step_fn()

            # Floor-totals + prime/constellation search: TWO PersistentWorkers that
            # used to live directly on this class (hand-rolled thread/queue pairs
            # before Faza 1, then inline PersistentWorker instances) -- moved into
            # their own primeatlas/totals_search_coordinator.py during the
            # refactor-phase2 branch's "God object" reduction (2026-08-26, see that
            # module's own docstring for the full rationale and README.md's "Known
            # gaps" for why this was the chosen next step). Constructed here, AFTER
            # every tab widget above already exists, because it reaches directly into
            # primes_tab_widget/constellations_hits_tab_widget (same construction-
            # order requirement the original inline code already had). on_const_
            # search_result stays a method on THIS class (self._on_const_search_result
            # below) rather than moving into the coordinator -- it's genuine three-tab
            # coordination (Constellations-hits AND Constellations-calc), not part of
            # the two-worker mechanism itself.
            self._totals_search = TotalsSearchCoordinator(
                self, get_portal_folder=lambda: PORTAL_FOLDER, status_var=self.status,
                totals_progress=self.totals_progress, translator=TRANSLATOR,
                primes_tab_widget=self.primes_tab_widget,
                constellations_hits_tab_widget=self.constellations_hits_tab_widget,
                on_const_search_result=self._on_const_search_result)

            # Primes-tree/Constellations-tree background scan+reload: two more
            # methods that used to live directly on this class (_primes_tree_scan/
            # reload_primes_tree/_on_primes_tree_scan_done and their constellations
            # counterparts) -- moved into their own primeatlas/primes_tree_coordinator.py
            # and primeatlas/constellations_tree_coordinator.py during the
            # refactor-phase3 branch's continuation of the same "God object" reduction
            # TotalsSearchCoordinator started above (see either module's own docstring).
            # Constructed here for the same construction-order reason as
            # TotalsSearchCoordinator: _on_scan_done reaches directly into
            # primes_tab_widget/constellations_hits_tab_widget, both of which already
            # exist by this point. reload_primes_tree()/reload_constellations_tree()
            # below stay as one-line delegating METHODS on this class (not instance
            # attributes reassigned here) so every existing caller that already holds
            # a self.reload_primes_tree/self.reload_constellations_tree reference
            # (PrimesTab, ConstellationsHitsTab, GenerationTab, _set_portal_folder,
            # the startup kickoff further down) keeps working unchanged, late-bound at
            # call time exactly like the original inline versions were.
            self._primes_tree_coord = PrimesTreeCoordinator(
                self, get_portal_folder=lambda: PORTAL_FOLDER, status_var=self.status,
                translator=TRANSLATOR, primes_tab_widget=self.primes_tab_widget,
                totals_search=self._totals_search,
                prune_empty_pietro_dirs=prune_empty_pietro_dirs,
                on_startup_scan_done=self._on_tree_startup_scan_done)
            self._constellations_tree_coord = ConstellationsTreeCoordinator(
                self, get_portal_folder=lambda: PORTAL_FOLDER, status_var=self.status,
                translator=TRANSLATOR,
                constellations_hits_tab_widget=self.constellations_hits_tab_widget,
                prune_empty_pietro_dirs=prune_empty_pietro_dirs,
                on_startup_scan_done=self._on_tree_startup_scan_done)

            # The three "offer to generate this missing fragment" bridge methods
            # (_offer_generate_missing_prime_window/_offer_generate_missing_constellation/
            # _goldbach_offer_generate_missing_range) used to live directly on this class
            # -- moved into their own primeatlas/generation_offer_coordinator.py during
            # this same refactor-phase3 branch (2026-08-27, see that module's own
            # docstring). Uses a LAZY get_generation_tab_widget callable (unlike the two
            # tree coordinators' direct tab-widget references above) since
            # generation_tab_widget doesn't exist yet at this point in __init__ (the
            # Generation tab is built AFTER this point in loading_steps) -- every one of
            # these three methods is only ever called well after full construction
            # anyway, so this can safely be built here alongside the other coordinators.
            self._generation_offer_coord = GenerationOfferCoordinator(
                get_generation_tab_widget=lambda: self.generation_tab_widget,
                status_var=self.status, translator=TRANSLATOR,
                quick_gen_max_window_width=QUICK_GEN_MAX_WINDOW_WIDTH,
                primesieve_max_stop=PRIMESIEVE_MAX_STOP)

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

            # App self-update auto-check (task #524) -- deferred several seconds past
            # startup (not run inline here) so a `git fetch` against GitHub -- a real
            # network round-trip that can be slow or simply hang on a bad connection --
            # never delays the loading screen or the two tree scans just kicked off
            # above. Reuses SettingsTab's own _check_for_app_update() (built for the
            # manual 'Sprawdz teraz' button) rather than duplicating its network-thread/
            # dialog/download logic here -- single code path, so the Settings tab's
            # status label reflects this automatic check too, not just manual ones.
            # Only actually runs if AppSettings.auto_update_check is on (default True;
            # see that property's own docstring) -- settings_tab is already fully built
            # by this point (it's the last of the loading_steps above).
            if APP_SETTINGS.auto_update_check:
                self.after(_APP_UPDATE_STARTUP_CHECK_DELAY_MS,
                           self.settings_tab._check_for_app_update)

        def _finish_loading_screen(self):
            """Reveals the real UI (status_frame + notebook) and tears down the loading
            overlay -- called once from _on_tree_startup_scan_done, once whichever of the
            two startup scans finishes LAST (see _loading_startup_pending's own comment in
            __init__). Safe to call at most once per app lifetime: _on_tree_startup_scan_done
            nulls out _loading_startup_pending before calling this, and every other
            reload_*_tree() call site checks that attribute is still a non-empty set before
            ever touching this method."""
            self._loading_bar.stop()
            self._loading_frame.destroy()
            self._status_frame.pack(fill="x", side="bottom")
            self.main_notebook.pack(fill="both", expand=True)

        def _on_tree_startup_scan_done(self, name):
            """Shared completion seam for BOTH PrimesTreeCoordinator and
            ConstellationsTreeCoordinator's own on_startup_scan_done callback (see either
            module's own docstring) -- genuinely shared state (one _loading_startup_pending
            set, one _finish_loading_screen call) that neither coordinator should own or
            reach into on the other's behalf, so it stays here rather than moving into
            either extracted class. `name` is "primes" or "constellations"."""
            pending = getattr(self, "_loading_startup_pending", None)
            if pending:
                pending.discard(name)
                if not pending:
                    self._finish_loading_screen()

        # Floor-total background worker, prime/constellation search worker: moved to
        # primeatlas/totals_search_coordinator.py's TotalsSearchCoordinator during the
        # refactor-phase2 branch's "God object" reduction (2026-08-26) -- see that
        # module's own docstring and this file's __init__ (self._totals_search) for
        # where the two PersistentWorkers this used to own directly now live.

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
                start_search_job=lambda *a: self._totals_search.start_search_job(*a),
                is_search_busy=lambda: self._totals_search.search_busy,
                offer_generate_missing_prime_window=lambda be, num:
                    self._offer_generate_missing_prime_window("prime", be, num),
                submit_totals_job=lambda be: self._totals_search.submit_totals_job(be),
                verify_all_totals=lambda: self._totals_search.compute_all_pietro_totals())
            self.primes_tab_widget.pack(fill="both", expand=True)

        def reload_primes_tree(self):
            """Rebuilds the floor list from disk (picks up newly created/removed 10pN
            folders) AND re-runs the totals scan for every floor -- so pressing Refresh
            after generating new windows is enough to see updated totals, no separate
            button needed.

            One-line delegate to primeatlas/primes_tree_coordinator.py's
            PrimesTreeCoordinator (moved out during the refactor-phase3 branch's
            continuation of TotalsSearchCoordinator's own "God object" reduction,
            2026-08-27 -- see that module's own docstring for the full scan/reload/
            caching/coalescing/staleness design). Kept as a plain class METHOD (not an
            instance attribute reassigned in __init__) so every existing caller that
            already holds a self.reload_primes_tree reference (PrimesTab, GenerationTab,
            _set_portal_folder, the startup kickoff in __init__) keeps working unchanged,
            late-bound at call time -- self._primes_tree_coord only needs to exist by the
            time this is actually CALLED, not by the time some other constructor captures
            this method as a callable."""
            self._primes_tree_coord.reload()
        # --- Search worker -- moved to primeatlas/totals_search_coordinator.py's
        # TotalsSearchCoordinator alongside the totals worker (see this file's own
        # __init__ / that module's docstring for the refactor-phase2 "God object"
        # reduction, 2026-08-26). self._on_const_search_result below is the one
        # deliberate seam left here -- see TotalsSearchCoordinator's own docstring on
        # its on_const_search_result constructor parameter for why that specific
        # completion handler stays app-level. ------------------------------------

        def _offer_generate_missing_prime_window(self, kind, base_exponent, number):
            """One-line delegate to primeatlas/generation_offer_coordinator.py's
            GenerationOfferCoordinator (moved out during the refactor-phase3 branch,
            2026-08-27 -- see that module's own docstring for the full "offer to
            generate this missing fragment, then re-check" design and the 3-way
            "launched"/"composite"/"skipped" return contract). Kept as a plain class
            METHOD (not an instance attribute) for the same late-binding reason
            reload_primes_tree()/reload_constellations_tree() are -- see
            primeatlas/primes_tree_coordinator.py's own docstring."""
            return self._generation_offer_coord.offer_generate_missing_prime_window(
                kind, base_exponent, number)

        def _offer_generate_missing_constellation(self, base_exponent, number):
            """One-line delegate to GenerationOfferCoordinator -- see
            _offer_generate_missing_prime_window()'s own docstring just above and
            primeatlas/generation_offer_coordinator.py's module docstring."""
            return self._generation_offer_coord.offer_generate_missing_constellation(
                base_exponent, number)

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
                start_search_job=lambda *a: self._totals_search.start_search_job(*a),
                is_search_busy=lambda: self._totals_search.search_busy,
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

        def reload_constellations_tree(self):
            """Rebuilds the constellation-hits floor list from disk. This tab's own
            Refresh button can be clicked without reload_primes_tree() ever running in
            the same gesture (e.g. right after constellation-finding finishes), so its
            own prune/scan is dispatched independently rather than relying on the OTHER
            tree's refresh to have already covered it.

            One-line delegate to primeatlas/constellations_tree_coordinator.py's
            ConstellationsTreeCoordinator (moved out during the refactor-phase3 branch's
            continuation of TotalsSearchCoordinator's own "God object" reduction,
            2026-08-27 -- see that module's own docstring, and
            primeatlas/primes_tree_coordinator.py's own docstring for why this stays a
            plain class METHOD rather than an instance attribute)."""
            self._constellations_tree_coord.reload()

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
            """One-line delegate to GenerationOfferCoordinator -- see
            _offer_generate_missing_prime_window()'s own docstring and
            primeatlas/generation_offer_coordinator.py's module docstring. Still the
            ONE piece of the Goldbach sub-tab's own logic injected from outside
            primeatlas/research_goldbach_tab.py's ResearchGoldbachTab (extracted during
            the refactor branch's Faza 3, 2026-08-23) -- ResearchGoldbachTab receives
            this exact bound method as its own `offer_generate_missing_range(op,
            payload)` callable (see that class's own docstring) and has no idea (nor
            needs to) that the actual logic now lives in a coordinator class rather
            than directly on PortalBrowserApp."""
            return self._generation_offer_coord.offer_generate_missing_range(op, payload)

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

        # --- Tab 5: Ring visualization ---------------------------------------------

        def _build_rings_tab(self):
            """Thin wrapper -- the whole tab lives in primeatlas/rings_tab.py's
            RingsTab (Faza 3, see PLAN.md at the repo root for the phased rollout),
            same construction pattern as _build_generation_tab above. get_portal_folder
            is a deferred lambda (not the resolved PORTAL_FOLDER value) so a later
            Settings-tab storage-path change is picked up on the NEXT launch without
            this tab needing its own change-notification wiring, same reasoning as
            every other tab's own get_portal_folder injection."""
            from primeatlas.rings_tab import RingsTab

            self.rings_tab_widget = RingsTab(
                self.rings_tab, get_portal_folder=lambda: PORTAL_FOLDER,
                status_var=self.status, translator=TRANSLATOR,
                totals_progress=self.totals_progress, app_settings=APP_SETTINGS)
            self.rings_tab_widget.pack(fill="both", expand=True)

        # --- Tab 6: Settings -----------------------------------------------------

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
                # CUDASieve (optional GPU engine) installer, ported from the `cudasieve`
                # branch onto cudasieve-v2 -- see primeatlas/generation.py's own
                # run_cudasieve_wsl_blocking() docstring for why it's NOT the plain
                # subprocess.run(timeout=...) shape run_primesieve_query_wsl() uses.
                # Wrapped in a lambda supplying the current PORTAL_FOLDER, same as
                # build_wsl_logged_command above, since generation.py's own copy takes
                # portal_folder as an explicit argument rather than reading a bare
                # module global.
                "build_cudasieve_status_argv": build_cudasieve_status_argv,
                "build_cudasieve_fetch_license_argv": build_cudasieve_fetch_license_argv,
                "build_cudasieve_build_argv": build_cudasieve_build_argv,
                "run_cudasieve_wsl_blocking":
                    lambda argv, timeout=120:
                        run_cudasieve_wsl_blocking(argv, PORTAL_FOLDER, timeout),
                # Added so the theme/language auto-restart feature (settings_tab.py's
                # _has_running_job()) can tell whether a Generation-tab pipeline/
                # constellation-finder/k-tuple run is currently in flight before
                # replacing the whole process via os.execv -- SettingsTab has no direct
                # reference to GenerationTab itself (same reasoning as every other entry
                # in this dict), so this is threaded through the same way. Each runner is
                # None until its first launch, hence the None-check before .is_running().
                "is_any_job_running": lambda: any(
                    r is not None and r.is_running() for r in (
                        self.generation_tab_widget._loop_runner,
                        self.generation_tab_widget._const_runner,
                        self.generation_tab_widget._ktuple_runner)),
                # repo_dir for the app-update checker (primeatlas/app_update.py) -- the
                # git checkout root this running process is executing out of, same value
                # AppSettings(_SCRIPT_DIR) above was constructed with.
                "repo_dir": _SCRIPT_DIR,
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
            from primeatlas.theme import palette_for
            self.benchmark_tab_widget = BenchmarkTab(
                self.benchmark_tab, get_portal_folder=lambda: PORTAL_FOLDER,
                status_var=self.status, translator=TRANSLATOR,
                update_nav_controls=_update_nav_controls,
                theme_palette=palette_for(APP_SETTINGS.theme))
            self.benchmark_tab_widget.pack(fill="both", expand=True)

    return PortalBrowserApp


def main():
    # First-run environment check/install wizard (task #513) -- runs BEFORE _build_gui()
    # is even called, let alone PortalBrowserApp constructed. Deliberately not folded into
    # the loading_frame steps below: enabling the WSL Windows features can require a full
    # REBOOT before anything else in this app can usefully run (WSL itself, hence every
    # generation/constellation script this app launches, would not work yet) -- see
    # primeatlas/env_setup.py's own module docstring for the full reasoning. Gated on
    # AppSettings.setup_completed (primeatlas/app_settings.py), so an already-set-up
    # install skips straight past this with only a near-instant background check, not a
    # visible dialog.
    from primeatlas.env_setup_wizard import maybe_run_first_run_wizard
    if not maybe_run_first_run_wizard(APP_SETTINGS, TRANSLATOR):
        return

    app_cls = _build_gui()
    app = app_cls()
    app.mainloop()


if __name__ == "__main__":
    main()
