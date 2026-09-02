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

    @property
    def cudasieve_status(self):
        """Last known result of the Settings > Aktualizacje CUDASieve status probe
        (see settings_tab.py's _on_check_cudasieve_status()) -- {"ok": bool,
        "payload": dict-or-error-string}, or None if never checked on this install.

        Deliberately NOT re-probed automatically at app startup (Artur, 2026-08-23,
        ported from the original `cudasieve` branch): an earlier version called the WSL
        status check directly from the Settings tab's __init__, which (a) paid a WSL
        round-trip on every single launch for a GPU-only, opt-in engine most sessions
        never touch, and (b) raced the app's own mainloop() startup (RuntimeError: main
        thread is not in main loop, confirmed live) since cmd_status() answers fast
        enough to finish before mainloop() even starts. Caching here fixes the slowdown
        at its root instead of just the crash: this value is shown as-is on every
        startup; a fresh WSL probe only happens when the user explicitly clicks
        Sprawdz status / Pobierz z GitHub / Zainstaluj."""
        return self._data.get("cudasieve_status") or None

    def set_cudasieve_status(self, ok, payload):
        """Persists the (ok, payload) pair settings_tab.py's cudasieve probe callers
        already produce, so it survives an app restart -- see cudasieve_status's own
        docstring for why this replaces querying WSL on every launch. Called after every
        real probe (manual status check, post-download, post-build), never
        speculatively."""
        self._data["cudasieve_status"] = {"ok": bool(ok), "payload": payload}
        self.save()

    @property
    def setup_completed(self):
        """Whether the first-run environment wizard (env_setup_wizard.py, task #513) has
        already confirmed WSL + Ubuntu + required packages are present on THIS install.
        Checked once at startup (prime_atlas_v1.py's main(), before PortalBrowserApp is
        even constructed -- see that module's own comment) to decide whether to show the
        wizard at all; False (the default for any install that predates this flag, or a
        genuinely fresh one) means the wizard runs. Deliberately NOT re-verified against
        a live WSL probe on every launch, same "cache the last real result, don't pay a
        round-trip every startup" reasoning as cudasieve_status above -- Settings >
        Aktualizacje's 'Zweryfikuj srodowisko' button (settings_tab.py) re-runs the real
        check on demand if something changes later (e.g. Ubuntu gets uninstalled)."""
        return bool(self._data.get("setup_completed", False))

    def set_setup_completed(self, value):
        self._data["setup_completed"] = bool(value)
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
