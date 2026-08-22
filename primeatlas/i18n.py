"""
i18n.py -- Translator: loads one of two static locale files (locales/strings_pl.json,
locales/strings_en.json) and provides T(key, **kwargs) lookups for every piece of
user-visible text in this app's GUI (prime_atlas_v1.py + settings_tab.py).

Deliberately RESTART-required, not a live hot-swap: this app's 5 tabs are built once, at
startup, by _build_gui() (prime_atlas_v1.py) -- rewriting every already-built widget's
displayed text in place, for every widget in every tab, would be a much larger and
riskier change to a large file with no way to visually verify tkinter widget layout.
The language choice persists to AppSettings and takes effect on next launch; the
Settings tab shows a message saying so when the choice is changed.

Pure Python, zero tkinter dependency -- exercised directly by unit tests.
"""
import os
import json

LOCALES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
DEFAULT_LANGUAGE = "pl"
SUPPORTED_LANGUAGES = ("pl", "en")
LANGUAGE_NAMES = {"pl": "Polski", "en": "English"}

# The chosen language lives in its own small file here rather than in the general
# app_settings.json (whose other job, storage_path, is unrelated to language) -- it
# belongs alongside the locale JSON files it actually governs.
LANGUAGE_SETTINGS_PATH = os.path.join(LOCALES_DIR, "language_settings.json")


def _locale_path(language):
    return os.path.join(LOCALES_DIR, f"strings_{language}.json")


def load_saved_language():
    """Reads the persisted language choice from locales/language_settings.json.
    Returns None if unset, unreadable, or set to something SUPPORTED_LANGUAGES doesn't
    recognize -- callers fall back to DEFAULT_LANGUAGE themselves (same pattern as
    AppSettings.storage_path's default-on-missing behavior)."""
    try:
        with open(LANGUAGE_SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        lang = data.get("language") if isinstance(data, dict) else None
        return lang if lang in SUPPORTED_LANGUAGES else None
    except (OSError, ValueError):
        return None


def save_language(language):
    """Atomic write (temp file + os.replace()), same pattern as AppSettings.save().
    Best-effort: a failed save just means the next launch falls back to the default
    language, not a crash. No-ops silently on an unrecognized language code."""
    if language not in SUPPORTED_LANGUAGES:
        return
    os.makedirs(LOCALES_DIR, exist_ok=True)
    tmp_path = f"{LANGUAGE_SETTINGS_PATH}.tmp{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"language": language}, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, LANGUAGE_SETTINGS_PATH)
    except OSError:
        pass


class Translator:
    """Loads locales/strings_<language>.json once at construction. t(key, **kwargs) (also
    callable directly as translator(key, **kwargs)) returns the translated string with any
    {placeholder} kwargs substituted (str.format semantics).

    Fallback chain, so a missing/partial translation degrades gracefully instead of
    crashing or silently showing nothing: requested language -> Polish (the locale every
    key is guaranteed to exist in, since it's the app's original/default language) -> the
    bare key itself (visibly obvious as e.g. "primes.refresh_button" in the UI, rather
    than blank, if a key is missing from BOTH files -- a bug to fix, not to hide)."""

    def __init__(self, language=None):
        self.language = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
        self._strings = self._load(self.language)
        self._fallback_strings = (self._strings if self.language == DEFAULT_LANGUAGE
                                   else self._load(DEFAULT_LANGUAGE))

    @staticmethod
    def _load(language):
        path = _locale_path(language)
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def t(self, key, **kwargs):
        template = self._strings.get(key)
        if template is None:
            template = self._fallback_strings.get(key, key)
        if kwargs:
            try:
                return template.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return template
        return template

    def __call__(self, key, **kwargs):
        return self.t(key, **kwargs)

    @staticmethod
    def available_languages():
        """[(code, display_name)] for every locale file that actually exists on disk,
        in SUPPORTED_LANGUAGES order -- used to populate the Settings tab's language
        picker without hardcoding the list twice."""
        out = []
        for code in SUPPORTED_LANGUAGES:
            if os.path.exists(_locale_path(code)):
                out.append((code, LANGUAGE_NAMES.get(code, code)))
        return out
