"""
verify_estimate.py -- the rough time of each store verification method for Section D, from
the rows of benchmark_log.csv. No tkinter here.

The pt1.1 proof runs at about the same numbers per second on every floor, so it is priced by
the last pt1_verify row with a time: numbers / (its numbers_processed / verify_seconds). The
v7.3 sieve is engine v7.2's sieve, whose time per pass is nearly fixed per floor and grows
slowly with the width, so each pass is priced by the sieve_seconds of that floor's v7.2 row
nearest to the pass in width (ratio of widths). Thread counts are not matched: the estimate
is a guide for choosing the method, not an ETA. No such row: None, shown as "?".
"""
import math

from benchmark_log_schema import ENGINE_PT1_VERIFY

V72_ENGINE = "v7"
V72_VERSION = "v7.2"


def _positive(row, key):
    try:
        value = float(row.get(key) or "")
    except ValueError:
        return None
    return value if value > 0 else None


def proof_seconds(rows, numbers):
    """Seconds the pt1.1 proof takes for `numbers` numbers, None without a timed row."""
    if numbers <= 0:
        return None
    for row in reversed(rows):
        if row.get("engine") != ENGINE_PT1_VERIFY:
            continue
        done, seconds = _positive(row, "numbers_processed"), _positive(row, "verify_seconds")
        if done and seconds:
            return numbers * seconds / done
    return None


def sieve_seconds(rows, base_exponent, pass_widths):
    """Seconds the v7.3 sieve takes for passes of `pass_widths` numbers on the floor, None
    without a v7.2 row of that floor or without a pass."""
    measured = []
    for row in rows:
        if (row.get("engine") == V72_ENGINE and row.get("engine_version") == V72_VERSION
                and str(row.get("base_exponent")) == str(base_exponent)):
            width, seconds = _positive(row, "numbers_processed"), _positive(row, "sieve_seconds")
            if width and seconds:
                measured.append((width, seconds))
    if not measured or not pass_widths:
        return None
    return sum(min(measured, key=lambda m: abs(math.log(m[0] / width)))[1]
               for width in pass_widths)


def duration_text(seconds):
    """"?", "42 s", "10 min", "1.1 h"."""
    if seconds is None:
        return "?"
    if seconds < 100:
        return f"{seconds:.0f} s"
    if seconds < 3600:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"
