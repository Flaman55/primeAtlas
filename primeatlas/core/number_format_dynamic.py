"""
number_format_dynamic.py -- the number notation the app runs in (a number_format.STYLES
code), read as number_format_dynamic.STYLE at call time by number_format. It starts at the
English notation, so code run without the app formats as 1,234.5; app_dynamic and the
renderer process set it from AppSettings at startup (number_format.apply_saved()).
"""
STYLE = "comma_dot"
