"""
ui_state_dynamic.py -- the remembered-fields store (ui_state.UiStateStore) shared by every
tab, read as ui_state_dynamic.STORE at call time. It starts in memory only, so a tab built
without the app writes nothing; app_dynamic replaces it with the per-install file at
startup, and unitTests/app_sandbox.isolate_app() with an in-memory store again.
"""
from .ui_state_store import UiStateStore

STORE = UiStateStore(None)
