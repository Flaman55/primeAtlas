"""
theme.py -- THEMES: the color palette for each of the app's two visual themes
(light/dark). Pure data, no tkinter import here -- same "no tkinter" invariant as the
rest of this package (see __init__.py's docstring; settings_tab.py stays the only
tkinter-importing module in primeatlas/), so this is testable without a display the
same way every other module here is. prime_atlas_v1.py's PortalBrowserApp._apply_theme()
is the one place that actually turns a palette from here into ttk.Style() calls and Tk
option-database entries -- applying a theme needs a live Tk root/ttk.Style instance,
which this "pure logic" package deliberately never touches, so the data (here) and the
application logic (there) are deliberately split across the tkinter boundary.

Two themes only, "light" (default) and "dark", picked from Settings > Ogolne (see
settings_tab.py's _build_general_tab) -- same restart-required UX as the language
switch (i18n.py), for the same reason: re-styling every already-built widget live
would be a much larger, riskier change than re-applying colors once at the next
startup.
"""

DEFAULT_THEME = "light"

THEMES = {
    "light": {
        "bg": "#f0f0f0",
        "fg": "#000000",
        "field_bg": "#ffffff",
        "field_fg": "#000000",
        "select_bg": "#0078d7",
        "select_fg": "#ffffff",
        "disabled_fg": "#888888",
        "border": "#a0a0a0",
        "console_bg": "#ffffff",
        "console_fg": "#000000",
        "tree_bg": "#ffffff",
        "tree_alt_bg": "#f5f5f5",
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
        "disabled_fg": "#8a8a8a",
        "border": "#555555",
        "console_bg": "#1e1e1e",
        "console_fg": "#d4d4d4",
        "tree_bg": "#313335",
        "tree_alt_bg": "#3a3d3f",
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
