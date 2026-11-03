"""
quick_number.py -- _eval_quick_number(), the parser behind every numeric entry field in the
app (Quick generation panel, primesieve calculator, Primality tests, visualization tabs).
"""
import re

from ..visualization.shared.bigint import parse_big_int


def _eval_quick_number(raw):
    """Best-effort parse of a Python-expression-style number (e.g. "10**5") -- shared by
    every numeric field in this app (Quick generation panel, primesieve calculator,
    Primality tests, Constellation calculator, ...). Returns an int, or None if
    `raw` is blank/unparseable; callers
    treat None as "no value given" rather than raising, e.g. to decide whether the
    Floor field should be auto-computed or left for manual entry (see
    _on_quick_floor_start_changed). Restricted eval (no builtins) -- this is a personal
    desktop tool, not a network-facing service, but there's no reason to allow arbitrary
    code execution just to parse a number typed into a text field.

    Strips every whitespace character (regular, non-breaking \\xa0, narrow no-break
    \\u202f -- all match Python's Unicode-aware \\s -- covers a number pasted straight out
    of a web page or spreadsheet) and every comma before evaluating, so a
    thousands-grouped number copied from elsewhere parses as a single int regardless of
    which grouping convention the source used: "23 081 664 151" (space every 3 digits)
    and "23,081,664,151" (comma) both become 23081664151. Safe for this field's actual
    purpose (one integer, or a simple arithmetic expression like "10**5+3") -- Python's
    own expression syntax never needs either character, and a comma left in place would
    otherwise build a tuple (rejected by the int() call below) instead of the single
    number this field is for."""
    raw = (raw or "").strip()
    if not raw:
        return None
    cleaned = re.sub(r"[\s,]", "", raw)
    if not cleaned:
        return None
    # Tried FIRST, ahead of the general eval() below: parse_big_int recognizes
    # a plain integer, "a*10**b"/"a*10^b", or scientific notation ("aEb")
    # using EXACT integer arithmetic only -- never float() -- so a storage-
    # floor-scale value (floor 25 alone is 26 digits) round-trips exactly no
    # matter how large the exponent. The eval() fallback stays exactly as it
    # was for every other input this function has always accepted (general
    # arithmetic expressions like "10**5+3", which parse_big_int intentionally
    # does not attempt), so nothing already relying on it changes behavior.
    try:
        return parse_big_int(cleaned)
    except ValueError:
        pass
    try:
        return int(eval(cleaned, {"__builtins__": {}}, {}))
    except Exception:
        return None
