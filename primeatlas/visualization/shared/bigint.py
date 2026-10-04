"""
bigint.py -- exact integer helpers shared by every visualization: the cheapest exact
numpy dtype for a prime array (to_prime_array), flexible big-integer parsing
(parse_big_int) and big-integer display formatting (format_big). No rendering, no I/O.
"""

import math
import re

import numpy as np


UINT64_MAX = (1 << 64) - 1


def to_prime_array(values):
    """Converts an ascending sequence of nonnegative prime values into the
    cheapest numpy dtype that holds every value EXACTLY. Storage floors 25/27
    (~10**25-10**27) overflow `dtype=np.int64`, so the dtype choice is centralized
    here instead of each prime-handling function deciding it:

      - `uint64` (native, vectorized; ~1.8e19 ceiling vs int64's ~9.2e18, since
        primes never need the sign bit) when the largest value fits.
      - plain-Python-int `object` dtype otherwise -- exact at any magnitude
        (a real floor 25/27 prime included), just slower per-element (numpy
        dispatches object-dtype ufuncs through Python's own int arithmetic
        instead of native SIMD) since there is no fixed-width integer type
        that could hold a 25+-digit value at all.

    Decided ONCE here from the last element (callers always pass an ascending
    sequence). Already-canonical input (an ndarray of dtype uint64 or object) is
    returned as-is, without a copy, so this is cheap to call at the top of every
    prime-handling function, repeatedly on the same array.

    An array of any other dtype (e.g. int64, or a plain Python list) is re-cast per
    element (`int(x)`) only when its dtype can't cheaply prove every element fits
    uint64."""
    if isinstance(values, np.ndarray) and values.dtype in (np.uint64, object):
        return values
    n = len(values)
    if n == 0:
        return np.empty(0, dtype=np.uint64)
    last = values[-1]
    last = int(last) if not isinstance(last, np.integer) else int(last)
    if 0 <= last <= UINT64_MAX:
        return np.asarray(values, dtype=np.uint64)
    return np.asarray([int(v) for v in values], dtype=object)


_PARSE_INT_RE = re.compile(r'^[+-]?\d+$')

# Mantissa is OPTIONAL (defaults to 1) so a bare "10**25"/"10^25" (shorthand
# for "floor 25 starts here") parses the same as "1*10**25".
_PARSE_POW_RE = re.compile(r'^(?:([+-]?\d+)\s*\*\s*)?10\s*(?:\*\*|\^)\s*([+-]?\d+)$')

_PARSE_SCI_RE = re.compile(r'^([+-]?\d+)(?:\.(\d+))?\s*[eE]\s*([+-]?\d+)$')


def parse_big_int(text):
    """Parses a Python int from `text`, accepting whichever of these forms
    is most convenient to type for a value at a real storage floor's
    magnitude (floor 25 alone needs 26 digits, impractical to type as a
    plain digit string):

      - plain digits, optionally with `_` group separators (Python's own
        integer-literal convention, e.g. "1_000_000") -- reproduces bare
        `int()` behavior for anything that already parses that way.
      - `a*10**b` or `a*10^b` (mathematical/programming exponent forms) --
        e.g. "6*10**20", "6 * 10 ^ 20".
      - scientific notation `aEb` / `a.fEb` -- e.g. "6e20", "1.5E25".

    Always computed with exact Python integer arithmetic (`int(...) *
    10**exponent`, decimal-point cases shift digits instead of dividing) --
    NEVER via `float(text)`, which would silently round a value like this at
    the 15-17th significant digit, exactly where a floor-25+ value's own
    precision matters. Raises ValueError (naming the rejected text, same
    contract as `int()` itself) for anything else, so existing "invalid
    field" handling around a bare `int()`/`.isdigit()` call needs no change
    beyond swapping in this function."""
    s = text.strip().replace('_', '')
    if not s:
        raise ValueError(f"parse_big_int: empty value {text!r}")
    if _PARSE_INT_RE.match(s):
        return int(s)
    m = _PARSE_POW_RE.match(s)
    if m:
        mantissa = int(m.group(1)) if m.group(1) is not None else 1
        exponent = int(m.group(2))
        if exponent < 0:
            raise ValueError(f"parse_big_int: negative exponent in {text!r}")
        return mantissa * (10 ** exponent)
    m = _PARSE_SCI_RE.match(s)
    if m:
        int_part, frac_part, exponent = m.group(1), m.group(2) or '', int(m.group(3))
        exponent -= len(frac_part)
        if exponent < 0:
            raise ValueError(f"parse_big_int: {text!r} is not a whole number")
        return int(int_part + frac_part) * (10 ** exponent)
    raise ValueError(
        f"parse_big_int: not a recognized integer (plain digits, a*10**b, a*10^b, "
        f"or aEb expected): {text!r}"
    )


def _int_digit_count(value):
    """Exact decimal digit count of a non-negative int, WITHOUT ever
    calling str() on it -- see format_big's own doc-comment for why that
    matters. `value.bit_length() * log10(2)` gives a cheap starting
    estimate (off by at most one, right at a power-of-ten boundary); the
    two correction loops below fix that up using only integer power/
    comparison, neither of which numpy or Python impose any digit-count
    limit on (unlike str(int), see PEP-recommended
    sys.set_int_max_str_digits() background)."""
    if value == 0:
        return 1
    estimate = int(value.bit_length() * math.log10(2)) + 1
    while 10 ** estimate <= value:
        estimate += 1
    while estimate > 1 and 10 ** (estimate - 1) > value:
        estimate -= 1
    return estimate


def format_big(value, digit_threshold=15):
    """Port of StructuralSieveApp.js's #formatBig: below digit_threshold
    digits (JS default 15, ~Number.MAX_SAFE_INTEGER's own digit count),
    the plain digit string; past it, "mantissa×10^exponent (N digits)"
    since LCM/Phase/To-resonance can genuinely reach hundreds or thousands
    of digits once dozens of pairwise-coprime primes are multiplied
    together, and printing all of them would be noise, not information.
    English-only wording (unlike the JS's #t()-localized string) since
    this is a console/HUD diagnostic string on the Python side, not
    user-facing app chrome with its own PL/EN locale files.

    The LCM of ~500 auto-tracked real storage-floor-scale primes (~25
    digits each) can reach roughly 12,500 digits, which would crash with
    "ValueError: Exceeds the limit (4300 digits) for integer string
    conversion" if formatted naively -- Python 3.11+'s int-to-str safety
    limit (see sys.set_int_max_str_digits(), CVE-2020-10735) bites BEFORE
    any truncation logic gets a chance to run if `str(value)` is called
    unconditionally just to measure its length. Avoided by never
    converting the FULL value to a string: _int_digit_count() gets the
    exact digit count via integer arithmetic alone, and only the leading
    handful of digits (a small int, however huge `value` itself is) is
    ever passed to str() for the truncated mantissa. Below digit_threshold,
    `value` itself is already known to be small (<=15 digits by default,
    i.e. nowhere near the 4300-digit limit), so str() on the full value
    there is exactly as safe as it always was."""
    value = int(value)
    negative = value < 0
    magnitude = -value if negative else value
    digit_count = _int_digit_count(magnitude)
    if digit_count <= digit_threshold:
        return ("-" if negative else "") + str(magnitude)
    leading_digit_count = 5
    shift = digit_count - leading_digit_count
    leading = magnitude // (10 ** shift) if shift > 0 else magnitude
    s = str(leading)
    mantissa = f"{s[0]}.{s[1:5]}"
    exponent = digit_count - 1
    return ("-" if negative else "") + f"{mantissa}×10^{exponent} ({digit_count} digits)"
