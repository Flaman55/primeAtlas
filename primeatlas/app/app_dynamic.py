"""
app_dynamic.py -- values computed once at startup and read by several primeatlas/app/
modules: the repository root, the persisted AppSettings, the current storage folder
(PORTAL_FOLDER) and the translator. It also opens the per-install remembered-fields file
into primeatlas/core/ui_state_dynamic.STORE, read by tabs outside primeatlas/app/. Read
as module attributes (_dyn.NAME) at call time:
PortalBrowserApp._set_portal_folder() rebinds _dyn.PORTAL_FOLDER, and every tab reads
it through a `lambda: _dyn.PORTAL_FOLDER` getter, so a storage-path change reaches all
of them without separate wiring.
"""
import os

from primeatlas.core.app_settings import AppSettings
from primeatlas.core import ui_state_dynamic
from primeatlas.core.i18n import LOCALES_DIR, Translator
from primeatlas.core.ui_state_store import UI_STATE_FILENAME, UiStateStore


# The checkout root prime_atlas_v2.py runs from (two levels above this file).
REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# AppSettings persists the chosen storage path OUTSIDE the portal folder itself (see
# app_settings.py's docstring for the chicken-and-egg reason).
APP_SETTINGS = AppSettings(REPO_DIR)
PORTAL_FOLDER = APP_SETTINGS.storage_path

# Every user-visible string in the GUI goes through T("some.key", **kwargs)
# instead of a hardcoded literal -- see primeatlas/core/i18n.py's docstring for the full
# rationale (a language switch requires a RESTART, not a live re-render, since this app's
# widgets are built once at startup). Built from AppSettings.language the same way
# PORTAL_FOLDER is built from AppSettings.storage_path.
TRANSLATOR = Translator(APP_SETTINGS.language)
T = TRANSLATOR.t

# Remembered form fields (primeatlas/core/ui_state.py), one file per install next to
# app_settings.json.
ui_state_dynamic.STORE = UiStateStore(os.path.join(LOCALES_DIR, UI_STATE_FILENAME))
