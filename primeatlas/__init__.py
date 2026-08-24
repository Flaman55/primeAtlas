"""
primeatlas -- the backend + GUI-tab package behind prime_atlas_v1.py, which is now a
thin composition root (see README.md's "Architecture" section for the full module map
and the tab-class/dependency-injection conventions used throughout this package).

This top-level __init__.py itself only re-exports the pure-logic pieces originally
built for the Settings tab (storage path config, backup/restore as lightweight
manifests rather than raw data copies, full-database delete, PL/EN language switching,
light/dark theme palettes -- theme.py is pure data only, the actual
ttk.Style()/option_add() application lives in prime_atlas_v1.py's
PortalBrowserApp._apply_theme(), which needs a live Tk root this module deliberately
never touches) plus primality testing and the Goldbach structural-window backend.
Every name re-exported here is independently unit-testable without a display. The
package as a whole is much larger now -- one GUI tab class plus, for the bigger tabs,
one pure-logic module per feature (generation.py/generation_tab.py,
benchmark.py/benchmark_tab.py, constellations.py/constellations_*_tab.py,
research_goldbach.py/research_goldbach_tab.py) -- see each module's own docstring for
details, and README.md for the overall picture.
"""
from .app_settings import AppSettings
from .theme import THEMES, DEFAULT_THEME, palette_for
from .manifest import PietroSnapshot, ConstellationSnapshot, BackupManifest
from .backup_store import BackupStore
from .restore_job import (
    RestoreJob, RestoreStep, restore_checkpoint_path, prune_empty_pietro_dirs,
)
from .delete_manager import PortalWiper
from .i18n import Translator, SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE, LANGUAGE_NAMES
from .primality import run_all_tests, factorize, try_import_sympy
from .goldbach_window import (
    check_window as goldbach_check_window,
    cascade_step as goldbach_cascade_step,
    next_anchor as goldbach_next_anchor,
    window_rows as goldbach_window_rows,
    all_decompositions as goldbach_all_decompositions,
    both_base_window_rows as goldbach_both_base_window_rows,
    BOTH_BASE_PMAX_CEILING as GOLDBACH_BOTH_BASE_PMAX_CEILING,
    BOTH_BASE_PMIN as GOLDBACH_BOTH_BASE_PMIN,
    largest_prime_le as goldbach_largest_prime_le,
    sieve_is_prime as goldbach_sieve_is_prime,
)

__all__ = [
    "AppSettings",
    "THEMES", "DEFAULT_THEME", "palette_for",
    "PietroSnapshot", "ConstellationSnapshot", "BackupManifest",
    "BackupStore",
    "RestoreJob", "RestoreStep", "restore_checkpoint_path", "prune_empty_pietro_dirs",
    "PortalWiper",
    "Translator", "SUPPORTED_LANGUAGES", "DEFAULT_LANGUAGE", "LANGUAGE_NAMES",
    "run_all_tests", "factorize", "try_import_sympy",
    "goldbach_check_window", "goldbach_cascade_step", "goldbach_next_anchor",
    "goldbach_window_rows", "goldbach_all_decompositions",
    "goldbach_both_base_window_rows", "GOLDBACH_BOTH_BASE_PMAX_CEILING",
    "GOLDBACH_BOTH_BASE_PMIN",
    "goldbach_largest_prime_le", "goldbach_sieve_is_prime",
]
