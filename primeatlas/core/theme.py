"""
theme.py -- THEMES: the color palette for each of the app's two visual themes
(light/dark). Pure data, no tkinter import here -- same "no tkinter" invariant as the
rest of this package (see __init__.py's docstring; settings_tab.py stays the only
tkinter-importing module in primeatlas/), so this is testable without a display the
same way every other module here is. prime_atlas_v2.py's PortalBrowserApp._apply_theme()
is the one place that actually turns a palette from here into ttk.Style() calls and Tk
option-database entries -- applying a theme needs a live Tk root/ttk.Style instance,
which this "pure logic" package deliberately never touches, so the data (here) and the
application logic (there) are deliberately split across the tkinter boundary.

Two themes only, "light" and "dark" (default), picked from Settings > General (see
settings_tab.py's _build_general_tab) -- same restart-required UX as the language
switch (i18n.py), for the same reason: re-styling every already-built widget live
would be a much larger, riskier change than re-applying colors once at the next
startup.

tree_group_bg/tree_stat_bg: per-row highlight colors for a Treeview's own
tag_configure() calls (NOT covered by ttk.Style() -- a tag's background overrides the
base "Treeview" style per-row, see _apply_theme()'s own docstring for the ttk-vs-tk
split, this is a THIRD case: a ttk widget's per-item override that also bypasses
Style()). The Benchmark tab's floor-grouping/stats-row highlights
(primeatlas/benchmark/benchmark_tab.py's "floor"/"stat" tags) use these, each paired with
this theme's own `fg` for the tag's foreground -- a fixed light background would leave
light Treeview text unreadable in dark mode. Dark theme's values are dark-tinted
equivalents (blue-ish/amber-ish), so the grouping/highlight effect stays visible in both
themes. tree_alt_bg is the stripe color of every second row (widgets.StripedTreeview).

hint_fg: explanatory/secondary label text (the Hint.TLabel style). hint_fg and
disabled_fg keep at least a 4.5:1 contrast against bg (WCAG AA) in both themes.

adjusted_palette() applies the user's per-theme brightness shifts (Settings > General >
User interface): `background` moves every BACKGROUND_KEYS color and `text` every
TEXT_KEYS color toward white (+) or black (-) by that percentage. Selection and accent
colors stay fixed so the selection highlight keeps its meaning.
"""

DEFAULT_THEME = "dark"

# Brightness shift in percent toward white (+) or black (-); 0 = the palette as defined.
BRIGHTNESS_DEFAULT = 0
BRIGHTNESS_MIN = -50
BRIGHTNESS_MAX = 50
# Text size in percent of the system default (scales every point-sized font).
FONT_SCALE_DEFAULT = 100
FONT_SCALE_MIN = 80
FONT_SCALE_MAX = 200

BACKGROUND_KEYS = ("bg", "field_bg", "border", "console_bg", "tree_bg", "tree_alt_bg",
                   "tree_group_bg", "tree_stat_bg", "tab_bg", "tab_selected_bg")
TEXT_KEYS = ("fg", "field_fg", "disabled_fg", "hint_fg", "console_fg")

THEMES = {
    "light": {
        "bg": "#f0f0f0",
        "fg": "#000000",
        "field_bg": "#ffffff",
        "field_fg": "#000000",
        "select_bg": "#0078d7",
        "select_fg": "#ffffff",
        "disabled_fg": "#6b6b6b",
        "hint_fg": "#555555",
        "border": "#a0a0a0",
        "console_bg": "#ffffff",
        "console_fg": "#000000",
        "tree_bg": "#ffffff",
        "tree_alt_bg": "#f5f5f5",
        "tree_group_bg": "#eef3fb",
        "tree_stat_bg": "#fff6d8",
        "tab_bg": "#e1e1e1",
        "tab_selected_bg": "#ffffff",
    },
    "dark": {
        "bg": "#2b2b2b",
        "fg": "#e0e0e0",
        "field_bg": "#3c3f41",
        "field_fg": "#e0e0e0",
        "select_bg": "#3a6ea5",
        "select_fg": "#ffffff",
        "disabled_fg": "#949494",
        "hint_fg": "#b0b0b0",
        "border": "#555555",
        "console_bg": "#1e1e1e",
        "console_fg": "#d4d4d4",
        "tree_bg": "#313335",
        "tree_alt_bg": "#3a3d3f",
        "tree_group_bg": "#2f3b4a",
        "tree_stat_bg": "#4a4020",
        "tab_bg": "#3c3f41",
        "tab_selected_bg": "#2b2b2b",
    },
}


def palette_for(theme_name):
    """Returns THEMES[theme_name], falling back to the light palette for any unknown
    value (a stale/corrupted app_settings.json entry, or a theme name from a future
    version of this app running against an older settings file) -- same
    fail-to-default philosophy as AppSettings.language's DEFAULT_LANGUAGE fallback."""
    return THEMES.get(theme_name, THEMES[DEFAULT_THEME])


def _clamp_int(value, lo, hi, default):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, number))


def clamp_brightness(value):
    """int(value) clamped to [BRIGHTNESS_MIN, BRIGHTNESS_MAX]; BRIGHTNESS_DEFAULT if
    value is not an integer."""
    return _clamp_int(value, BRIGHTNESS_MIN, BRIGHTNESS_MAX, BRIGHTNESS_DEFAULT)


def clamp_font_scale(value):
    """int(value) clamped to [FONT_SCALE_MIN, FONT_SCALE_MAX]; FONT_SCALE_DEFAULT if
    value is not an integer."""
    return _clamp_int(value, FONT_SCALE_MIN, FONT_SCALE_MAX, FONT_SCALE_DEFAULT)


def shift_color(color, percent):
    """"#rrggbb" blended `percent`% toward white (percent > 0) or black (percent < 0)."""
    channels = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    target = 255 if percent > 0 else 0
    weight = min(abs(percent), 100) / 100
    return "#" + "".join(f"{round(c + (target - c) * weight):02x}" for c in channels)


def adjusted_palette(theme_name, background=BRIGHTNESS_DEFAULT, text=BRIGHTNESS_DEFAULT):
    """A copy of palette_for(theme_name) with BACKGROUND_KEYS shifted by `background`
    and TEXT_KEYS by `text` (both clamped, see shift_color())."""
    palette = dict(palette_for(theme_name))
    background = clamp_brightness(background)
    text = clamp_brightness(text)
    for key in BACKGROUND_KEYS:
        palette[key] = shift_color(palette[key], background)
    for key in TEXT_KEYS:
        palette[key] = shift_color(palette[key], text)
    return palette
