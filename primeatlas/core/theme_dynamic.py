"""
theme_dynamic.py -- the theme the app runs in ("light" or "dark"), read as
theme_dynamic.THEME at call time by modules outside primeatlas/app/ that pick colors per
theme (primeatlas/benchmark/line_colors.py). It starts at theme.DEFAULT_THEME, so a tab
built without the app draws in the default theme; app_dynamic sets it from AppSettings at
startup (a theme change needs a restart, see theme.py).
"""
from .theme import DEFAULT_THEME

THEME = DEFAULT_THEME
