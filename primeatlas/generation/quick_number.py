"""
quick_number.py -- _eval_quick_number(), the parser behind every numeric entry field in the
app (Quick generation panel, primesieve calculator, Primality tests, visualization tabs).
"""
from ..core.number_text import OK, read_number


def _eval_quick_number(raw):
    """The whole number in a field's text, in any notation core.number_text reads (grouping
    from any country, powers, scientific, pasted forms), or None when the text is blank,
    invalid or ambiguous. Callers treat None as "no value given" rather than raising, e.g.
    to decide whether the Floor field should be auto-computed or left for manual entry (see
    _on_quick_floor_start_changed); the field itself shows why (core.number_field)."""
    reading = read_number(raw)
    return reading.value if reading.state == OK else None
