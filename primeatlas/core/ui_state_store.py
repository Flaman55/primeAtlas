"""
ui_state_store.py -- UiStateStore, the flat {key: value} JSON file behind ui_state.remember().
Imports no tkinter: app_dynamic opens the store before any window exists, and the store
uses only the after() of the window it is attached to.
"""
import json
import os

UI_STATE_FILENAME = "ui_state.json"

# Delay between the first change of a burst and the file write. Arbitrary: long enough
# that typing a number writes once, short enough that a crash loses at most this much.
SAVE_DELAY_MS = 500

_MISSING = object()


class UiStateStore:
    """The flat {key: value} map behind remember(). path=None keeps the values in memory
    only (tests, tabs built without the app)."""

    def __init__(self, path):
        self.path = path
        self._data = _load(path)
        self._root = None
        self._pending = None
        self.dirty = False

    def attach(self, root):
        """Debounces writes with root.after(); without a root every change writes at once."""
        self._root = root

    def get(self, key, default=None):
        return self._data.get(key, default)

    def has(self, key):
        return key in self._data

    def set(self, key, value):
        old = self._data.get(key, _MISSING)
        if old is not _MISSING and type(old) is type(value) and old == value:
            return
        self._data[key] = value
        if self.path is None:
            return
        self.dirty = True
        if self._root is None:
            self.flush()
        elif self._pending is None:
            try:
                self._pending = self._root.after(SAVE_DELAY_MS, self._on_timer)
            except Exception:  # noqa: BLE001 -- TclError: root already destroyed
                self.flush()

    def _on_timer(self):
        self._pending = None
        self.flush()

    def flush(self):
        """Writes a pending change now (app close, tests)."""
        if self._pending is not None and self._root is not None:
            try:
                self._root.after_cancel(self._pending)
            except Exception:  # noqa: BLE001 -- TclError: root already destroyed
                pass
        self._pending = None
        if self.dirty and self.path is not None:
            self._write()
            self.dirty = False

    def _write(self):
        tmp_path = f"{self.path}.tmp{os.getpid()}"
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=1, ensure_ascii=False, sort_keys=True)
            os.replace(tmp_path, self.path)
        except OSError:
            pass  # best-effort: the next change or flush tries again



def _load(path):
    if path is None or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
