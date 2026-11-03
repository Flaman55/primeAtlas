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
# constellation_finder_v2_3.py); that naming is independent of the application's display name.
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
#      constellation_finder_v2_3.py (k-tuple search) directly from this GUI, via WSL, instead
#      of a manual WSL terminal + hand-typed CLI args. Two independent forms (one per
#      script), each exposing every CLI parameter those scripts have -- including
#      workers/batches_per_worker/window_count_per_run -- with live streamed output and a
#      best-effort Stop button. Form values persist to .portal_generation_settings.json
#      (loaded at startup, saved whenever a run is launched).
#   4) "Benchmark" -- a small dependency-free growth chart (seconds/10M vs. floor depth,
#      one point per floor -- latest logged run wins) above a full table view of
#      benchmark_log.csv (written by orchestrator_v3.py's print_benchmark_summary()); a
#      "Save PDF" button renders that same chart + the full table into a standalone PDF
#      report (see the hand-rolled PDF writer below render_benchmark_pdf()).
#   5) "Settings" -- storage path configuration plus backup/restore/delete of the whole
#      prime/constellation database, built object-oriented in its own package
#      (./primeatlas/settings/).
#      primeatlas/ holds five small, independently unit-tested (no tkinter dependency),
#      single-purpose classes:
#        - AppSettings                          (app_settings.py)  -- configurable storage
#                                                  path, persisted OUTSIDE the portal folder
#                                                  itself (see that module's docstring for
#                                                  why)
#        - BackupManifest/FloorSnapshot/
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
#      settings_tab.py (same package) and its *_section.py mixins wire the classes above
#      into the actual Settings tab widgets.
#
# The chosen storage path also has to reach the scripts this app launches as separate WSL
# processes (prime_sieve_v3.py, orchestrator_v3.py, orchestrator_loop_v2.py,
# constellation_finder_v2_3.py). All four check a CONSTELLATION_PORTAL_DIR environment
# variable first (see each file's own __main__/module-level comment) --
# build_wsl_logged_command() (primeatlas/generation/wsl_command.py) prepends it to every
# WSL command this app launches, so
# choosing a custom path in Settings transparently affects the Generation tab's
# pipeline runs too, with no separate wiring needed.
#
# Built with tkinter (Python's standard-library GUI toolkit) specifically so it runs with
# zero extra installs on a normal Windows Python -- no pip packages required. Run directly
# (not through WSL -- this needs a display, and reading PGS2 files is pure Python, no
# ctypes/.so/primesieve dependency at all):
#   python prime_atlas_v2.py
#
# Depends on prime_sieve_v1.py (./prime_sieve/) for the PGS2 format readers and
# pattern_catalog_v1.py (./constellation/) for pattern offsets/record metadata --
# imported via sys.path, same approach orchestrator_v3.py/constellation_finder_v2.py use.
# Never touches prime_sieve_engine_v1.so (only prime_sieve_v1's lazy sieving path does).
#
# This file is the entry point only: it sets up sys.path, checks dependencies and starts
# PortalBrowserApp. The application lives in primeatlas/app/:
#   app_const.py             -- shared fixed values (preview page sizes, update-check delay)
#   app_dynamic.py           -- shared startup values (AppSettings, PORTAL_FOLDER, translator)
#   app_window.py            -- PortalBrowserApp: loading screen, notebook, coordinators
#   app_theme.py             -- font scale and ttk/Tk color palette
#   paging.py                -- page rendering shared by the preview lists
#   primes_section.py        -- 'Prime numbers' tab
#   constellations_section.py -- 'Constellations' tab and its cross-sub-tab jumps
#   research_section.py      -- 'Research' tab
#   visualization_section.py -- 'Visualization' tab
#   single_tabs_section.py   -- 'Generation', 'Benchmark', 'About' tabs
#   settings_wiring.py       -- 'Settings' tab and the storage-path setter
# ==========================================================================================

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# prime_sieve_v1/pattern_catalog_v1 are not imported into THIS file's own namespace --
# every direct user of either lives in primeatlas/ modules. The
# sys.path.insert() calls below still matter: every primeatlas/*.py module that
# imports prime_sieve_v1/pattern_catalog_v1 itself relies on THIS app process having
# already added these two directories, since none of those modules re-add them.
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "prime_sieve"))
sys.path.insert(0, os.path.join(_SCRIPT_DIR, "constellation"))
# primeatlas/__init__.py itself imports numpy, so a fresh machine without it would die on the
# import below with a bare ImportError -- check requirements.txt first and offer a pip install
# (see startup_dependency_check.py). Only when run as the app, never when imported by tests.
if __name__ == "__main__":
    import startup_dependency_check  # noqa: E402
    if not startup_dependency_check.ensure_dependencies():
        sys.exit(1)
# Shared startup values (AppSettings, PORTAL_FOLDER, translator), see app_dynamic.py.
from primeatlas.app import app_dynamic as _dyn  # noqa: E402


def _build_gui():
    """Returns the PortalBrowserApp class. tkinter is imported only here (through
    app_window.py), so importing this module needs no display."""
    from primeatlas.app.app_window import PortalBrowserApp
    return PortalBrowserApp


def main():
    # Before the first window: without it the taskbar shows pythonw.exe's Python icon
    # instead of ours (see primeatlas/core/app_icon.py).
    from primeatlas.core.app_icon import set_app_user_model_id
    set_app_user_model_id()

    # First-run environment check/install wizard -- runs BEFORE _build_gui()
    # is even called, let alone PortalBrowserApp constructed. Deliberately not folded into
    # the loading_frame steps below: enabling the WSL Windows features can require a full
    # REBOOT before anything else in this app can usefully run (WSL itself, hence every
    # generation/constellation script this app launches, would not work yet) -- see
    # primeatlas/settings/env_setup.py's own module docstring for the full reasoning. Gated on
    # AppSettings.setup_completed (primeatlas/core/app_settings.py), so an already-set-up
    # install skips straight past this with only a near-instant background check, not a
    # visible dialog.
    from primeatlas.settings.env_setup_wizard import maybe_run_first_run_wizard
    if not maybe_run_first_run_wizard(_dyn.APP_SETTINGS, _dyn.TRANSLATOR):
        return

    app_cls = _build_gui()
    app = app_cls()
    app.mainloop()


if __name__ == "__main__":
    main()
