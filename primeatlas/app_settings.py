"""
app_settings.py -- AppSettings, persisting the user-configurable storage path.

The settings file (primeatlas/locales/app_settings.json) lives outside the portal
folder it points at, on purpose -- a "chicken-and-egg" constraint: a setting that
TELLS you where the portal folder is can't itself live inside that same folder (you'd
need to already know the path to find the file that tells you the path). This is
distinct from per-portal generation-form state, which is expected to live inside the
portal folder itself since it's tied to that specific portal, not to locating it.

storage_path lives in primeatlas/locales/, alongside language_settings.json, so every
small per-install runtime setting lives in ONE place instead of split between the app's
own root and a subfolder. An earlier on-disk location next to the app itself
(.portal_app_settings.json) is still read once, for migration, by
_migrate_legacy_root_file() below, but is never written to again.

Pure Python, zero tkinter/UI dependency -- exercised directly by unit tests, wired into the
GUI by settings_tab.py.
"""
import os
import json

from .i18n import DEFAULT_LANGUAGE, LOCALES_DIR, load_saved_language, save_language
from .theme import DEFAULT_THEME

SETTINGS_FILENAME = "app_settings.json"
LEGACY_SETTINGS_FILENAME = ".portal_app_settings.json"  # earlier location, next to the
                                                          # script -- read once for
                                                          # migration, never written again


class AppSettings:
    """One JSON file (primeatlas/locales/app_settings.json), holding storage_path
    alongside the language choice. Kept as a class (not a bare dict/function pair) so
    it's a natural single object to pass around the Settings tab and to the
    subprocess-launching code that needs to know the CURRENT storage path to set
    CONSTELLATION_PORTAL_DIR for orchestrator_loop_v2.py/constellation_finder_v1.py."""

    def __init__(self, script_dir):
        self.script_dir = script_dir
        self._legacy_path = os.path.join(script_dir, LEGACY_SETTINGS_FILENAME)
        self._path = os.path.join(LOCALES_DIR, SETTINGS_FILENAME)
        self._data = {}
        self.load()

    @property
    def default_storage_path(self):
        """Default storage location: a CONSTELLATION_PORTAL folder directly alongside
        this application's own files. Self-contained regardless of where the
        application directory is placed on disk -- no assumption about an enclosing
        directory structure."""
        return os.path.abspath(
            os.path.join(self.script_dir, "CONSTELLATION_PORTAL"))

    @property
    def storage_path(self):
        custom = self._data.get("storage_path")
        return custom if custom else self.default_storage_path

    @property
    def is_custom(self):
        return bool(self._data.get("storage_path"))

    def set_storage_path(self, path):
        """path=None or "" resets to the default (a CONSTELLATION_PORTAL folder next to
        this script)."""
        self._data["storage_path"] = path or None
        self.save()

    @property
    def full_backup_destination(self):
        """Last-used destination folder for the full-data (compressed) backup feature
        (primeatlas/full_backup.py) -- remembered purely as a UI convenience (so the
        Settings tab's folder picker doesn't reset to nothing every restart), NOT
        trusted as-is: settings_tab.py still re-runs validate_destination_path() against
        the CURRENT storage_path before every backup/restore/list action, since the
        storage path itself may have changed since this was last saved. Returns None if
        never set."""
        return self._data.get("full_backup_destination") or None

    def set_full_backup_destination(self, path):
        self._data["full_backup_destination"] = path or None
        self.save()

    @property
    def language(self):
        """Read once at startup (see prime_atlas_v1.py's TRANSLATOR construction) to
        build the Translator that every T(...) call in this app's GUI uses. Falls back
        to DEFAULT_LANGUAGE ("pl") if unset.

        Persisted in primeatlas/locales/language_settings.json, next to the locale
        JSON files it actually governs (see i18n.py's load_saved_language()/
        save_language()), separate from storage_path. This property/setter pair is
        kept so callers (settings_tab.py) don't need to know where the value is
        actually stored."""
        return load_saved_language() or DEFAULT_LANGUAGE

    def set_language(self, language):
        save_language(language)

    @property
    def theme(self):
        """Visual theme ("light" or "dark") -- see primeatlas/theme.py for the two
        color palettes. Read once at startup (PortalBrowserApp._apply_theme(), same
        restart-required pattern as `language` above -- Settings > Ogolne's theme
        picker only writes the choice here, it does not attempt to re-theme the
        already-built app). Stored directly in THIS file's own JSON
        (_data["theme"]), unlike `language` above -- theme has nothing to do with
        i18n.py's translation machinery, so it doesn't need that indirection.
        Defaults to DEFAULT_THEME ("light") if unset or unrecognized."""
        return self._data.get("theme") or DEFAULT_THEME

    def set_theme(self, theme_name):
        self._data["theme"] = theme_name or DEFAULT_THEME
        self.save()

    def load(self):
        if not os.path.exists(self._path):
            self._data = {}
        else:
            try:
                with open(self._path, encoding="utf-8") as f:
                    data = json.load(f)
                self._data = data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self._data = {}
        self._migrate_legacy_root_file()

    def _migrate_legacy_root_file(self):
        """One-time migration for installations where storage_path (and, at one point,
        language too) lived in .portal_app_settings.json next to the script, before both
        settings moved into primeatlas/locales/. Carries forward whichever of those two
        values the new locations don't already have, so moving the file doesn't silently
        reset a previously-configured custom storage path or language choice back to
        defaults. The legacy file itself is left in place untouched (best-effort,
        non-destructive -- same policy as every other migration in this app) -- just
        never read again after this, and never written to."""
        if not os.path.exists(self._legacy_path):
            return
        try:
            with open(self._legacy_path, encoding="utf-8") as f:
                legacy_data = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(legacy_data, dict):
            return

        changed = False
        if not self._data.get("storage_path"):
            legacy_storage_path = legacy_data.get("storage_path")
            if legacy_storage_path:
                self._data["storage_path"] = legacy_storage_path
                changed = True

        legacy_language = legacy_data.get("language")
        if legacy_language and load_saved_language() is None:
            save_language(legacy_language)

        if changed:
            self.save()

    def save(self):
        """Atomic write (temp file + os.replace()). Best-effort: a failed save just
        means the next launch falls back to the default path, not a crash."""
        tmp_path = f"{self._path}.tmp{os.getpid()}"
        try:
            os.makedirs(LOCALES_DIR, exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self._path)
        except OSError:
            pass
