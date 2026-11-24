"""
number_format.py -- the one formatter for numbers shown to a person: whole() groups the
digits of an integer, decimal() writes a number with fixed places, signed() adds the sign.
The notation follows the interface language (pl: 1 234 567,89, en: 1,234,567.89) unless
Settings > General picks another one; number_format_dynamic.STYLE holds the notation the app runs in, set once at
startup by apply_saved() (a change needs a restart, like the language).

Text for machines (logs, CSV and other files, command lines) keeps Python's own
formatting; core.number_text reads every notation here back.
"""
import operator

from . import number_format_dynamic

FOLLOW_LANGUAGE = "follow_language"
SPACE_COMMA = "space_comma"
COMMA_DOT = "comma_dot"
DOT_COMMA = "dot_comma"
APOSTROPHE_DOT = "apostrophe_dot"
PLAIN_DOT = "plain_dot"

# notation -> (digit group separator, decimal mark); the no-break space keeps a number on
# one line when a label wraps
STYLES = {
    SPACE_COMMA: (" ", ","),
    COMMA_DOT: (",", "."),
    DOT_COMMA: (".", ","),
    APOSTROPHE_DOT: ("'", "."),
    PLAIN_DOT: ("", "."),
}
CHOICES = (FOLLOW_LANGUAGE,) + tuple(STYLES)
LANGUAGE_STYLES = {"pl": SPACE_COMMA, "en": COMMA_DOT}
DEFAULT_STYLE = COMMA_DOT

_SAMPLE = 1234567.89


def resolve(choice, language):
    """The notation a saved `choice` stands for under `language`."""
    if choice in STYLES:
        return choice
    return LANGUAGE_STYLES.get(language, DEFAULT_STYLE)


def _localise(text, style):
    group, mark = STYLES.get(style or number_format_dynamic.STYLE, STYLES[DEFAULT_STYLE])
    return "".join(group if c == "," else mark if c == "." else c for c in text)


def whole(n, style=None):
    """An integer (also a numpy integer) with grouped digits; a float raises TypeError."""
    return _localise(f"{operator.index(n):,}", style)


def decimal(x, places, style=None):
    """`x` rounded to `places` decimal places, its integer part grouped."""
    return _localise(f"{x:,.{places}f}", style)


_PREFIXES = ("M", "G", "T", "P", "E", "Z", "Y")
COMPACT_FROM = 1e6
COMPACT_DIGITS = 3


def compact(x, places, style=None):
    """A chart's short form of `x`: from a million up COMPACT_DIGITS significant digits and an
    SI prefix after a no-break space (1,18 G, 236 M; past Y whole Y units), below it decimal()
    with `places`."""
    if abs(x) < COMPACT_FROM:
        return decimal(x, places, style)
    for power, prefix in enumerate(_PREFIXES):
        scaled = abs(x) / 10.0 ** (6 + 3 * power)
        digits = max(0, COMPACT_DIGITS - len(str(int(scaled))))
        # Rounding up to the next power of ten (9.996 -> 10.00) costs one decimal place.
        if len(str(int(float(f"{scaled:.{digits}f}")))) > len(str(int(scaled))):
            digits = max(0, digits - 1)
        if float(f"{scaled:.{digits}f}") < 1000 or prefix == _PREFIXES[-1]:
            sign = "-" if x < 0 else ""
            return sign + decimal(scaled, digits, style) + " " + prefix
    raise AssertionError("unreachable")


def signed(x, places, style=None):
    """decimal() with an explicit sign, like Python's "+" format flag: +1 234,5, -0,25."""
    text = decimal(x, places, style)
    return text if text.startswith("-") else "+" + text


def sample(style):
    """The example a Settings entry shows for `style`: 1 234 567,89."""
    return decimal(_SAMPLE, 2, style)


def apply_saved(app_settings):
    """Sets number_format_dynamic.STYLE from the saved choice and language; returns it."""
    number_format_dynamic.STYLE = resolve(app_settings.number_format, app_settings.language)
    return number_format_dynamic.STYLE
