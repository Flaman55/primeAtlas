"""Colors of the Benchmark chart lines: one hue per engine key (chart_series.Series.engine:
"v6", "pt1 P", "pseudosquares_count") in two palettes, one per theme, with the user's own
choice on top.

PALETTES["dark"] is drawn on the dark theme's chart background, PALETTES["light"] on white:
the light theme's chart and every export (PDF, SVG, HTML: EXPORT_THEME). An engine keeps its
hue in both; the light colors are darker, so each palette reaches 3:1 contrast on its own
background and keeps its colors far apart in RGB. The theme is the app's
(theme_dynamic.THEME, read at call time) unless a caller names one. The user's colors are one
{engine key: "#rrggbb"} map per theme in the remembered-fields store
(ui_state_dynamic.STORE), so a color chosen in the legend holds for every line of that
engine, every chart and, in the light theme, every export. Entries that are not "#rrggbb"
colors are ignored. No tkinter here.
"""
import re

from primeatlas.core import theme_dynamic, ui_state_dynamic
from primeatlas.core.theme import DEFAULT_THEME

PALETTES = {
    "dark": {"unknown": "#8c8c8c", "primesieve": "#b5e61d", "primesieve_print": "#00c8c8",
             "primesieve_count": "#a87838", "pseudosquares_print": "#50c050",
             "pseudosquares_count": "#80b8f8", "hybrid": "#009e73", "v4.1": "#e69f00",
             "v5": "#2f7fe0", "v6": "#a060ff", "v7": "#ff00ff", "pt1": "#e0a0e0",
             "pt1-pss": "#ff50d8", "pt1 D+P": "#608000", "pt1 P": "#00e000",
             "pt1 D proof": "#60f0b0"},
    "light": {"unknown": "#707070", "primesieve": "#789c00", "primesieve_print": "#5898bc",
              "primesieve_count": "#d07c60", "pseudosquares_print": "#38a440",
              "pseudosquares_count": "#1e90ff", "hybrid": "#006050", "v4.1": "#d47c00",
              "v5": "#1f3fb0", "v6": "#7a30d0", "v7": "#fc00fc", "pt1": "#c070c0",
              "pt1-pss": "#a00070", "pt1 D+P": "#445010", "pt1 P": "#008c00",
              "pt1 D proof": "#08a498"},
}
# The color of an engine without its own entry.
OTHER_COLORS = {"dark": "#ff8080", "light": "#780000"}

# Exports draw on a white background.
EXPORT_THEME = "light"

# The default theme's palette, for callers that name no theme.
ENGINE_COLORS = PALETTES[DEFAULT_THEME]
OTHER_ENGINE_COLOR = OTHER_COLORS[DEFAULT_THEME]

STORE_KEY = "benchmark.line_colors"

_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")


def is_color(value):
    return isinstance(value, str) and _HEX_COLOR.fullmatch(value) is not None


def _theme(theme):
    """`theme`, else the app's; an unknown name falls back to the default theme."""
    theme = theme_dynamic.THEME if theme is None else theme
    return theme if theme in PALETTES else DEFAULT_THEME


def _store(store):
    return ui_state_dynamic.STORE if store is None else store


def store_key(theme=None):
    return f"{STORE_KEY}.{_theme(theme)}"


def _overrides(store, theme):
    """The stored {engine key: color} of the theme with every invalid entry left out."""
    stored = _store(store).get(store_key(theme))
    if not isinstance(stored, dict):
        return {}
    return {engine: color.lower() for engine, color in stored.items() if is_color(color)}


def default_color(engine, theme=None):
    theme = _theme(theme)
    return PALETTES[theme].get(engine, OTHER_COLORS[theme])


def engine_color(engine, store=None, theme=None):
    """The user's color of `engine` in the theme, else its default there."""
    return _overrides(store, theme).get(engine) or default_color(engine, theme)


def overridden(store=None, theme=None):
    """The engine keys with a color of the user's in the theme."""
    return set(_overrides(store, theme))


def set_color(store, engine, color, theme=None):
    """Stores `color` for `engine` in the theme; False (nothing stored) when it is not
    "#rrggbb"."""
    if not is_color(color):
        return False
    colors = _overrides(store, theme)
    colors[engine] = color.lower()
    _store(store).set(store_key(theme), colors)
    return True


def reset_color(store, engine, theme=None):
    """`engine` back to its default color in the theme."""
    colors = _overrides(store, theme)
    colors.pop(engine, None)
    _store(store).set(store_key(theme), colors)


def reset_all(store, theme=None):
    _store(store).set(store_key(theme), {})
