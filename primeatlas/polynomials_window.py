"""
polynomials_window.py -- pure Python (no tkinter, no external dependencies)
prime-among-polynomial-values checks for the Badania -> Wielomiany
pierwszorodne (prime-generating polynomials) sub-tab.

Two classical cases share the same question shape ("is f(n) prime, for every
n in a range?"), differing only in the polynomial itself:

  - Landau:  f(n) = n^2 + 1       -- Landau's 4th problem: are there
             infinitely many primes of this form? Still an open conjecture.
  - Euler:   f(n) = n^2 + n + 41  -- famous for being prime for every
             n = 0..39 (41 consecutive prime values), though NOT for all n
             (f(40) = 1681 = 41^2, the first counterexample).

Plus a caller-supplied CUSTOM f(n) formula for exploring other polynomials --
this module never evaluates user-typed text itself (no eval() anywhere here);
the tab layer turns a typed formula into a plain Python callable first (same
"restricted eval lives at the UI layer" split as squares_window.py's own
_eval_formula in research_squares_tab.py, and generation.py's
_eval_quick_number).

Unlike squares_window.py's "does [a(n),b(n)] contain ENOUGH primes" covering
question (a finite range has a genuine pass/fail verdict with
counterexamples), Landau's and Euler's conjectures are about an INFINITE
tail ("infinitely many primes of this form") -- no finite range check can
ever confirm or refute that, so this module's result shape reports a plain
prime_count/density measurement over the checked range instead of a
covered/counterexamples verdict.

Mirrors squares_window.py's own two-entry-point split: a fresh-sieve
default (check_polynomial_range) and a source-injectable one
(check_polynomial_range_from_source), so a caller can plug in an on-disk-
magazyn-backed is_prime reader instead of always sieving fresh -- same
reasoning, duplicated sieve_is_prime rather than importing across
conjecture-module boundaries (see research_squares_tab.py's own docstring
for why each conjecture module in this project stays self-contained).
"""

MAX_SIEVE_BOUND = 200_000_000
"""Refuses (ValueError) any check whose largest f(n) value would need a
fresh in-memory sieve bigger than this (~200MB bytearray) -- same safety
ceiling and same reasoning as squares_window.py's own constant."""


def sieve_is_prime(limit):
    """Classic sieve of Eratosthenes. Returns a bytearray `is_prime` of length
    limit + 1, is_prime[i] truthy iff i is prime (0 and 1 are not). Same
    algorithm as squares_window.py's own copy (see this module's own
    docstring for why it's duplicated rather than imported)."""
    if limit < 2:
        return bytearray(max(limit + 1, 0))
    is_prime = bytearray([1]) * (limit + 1)
    is_prime[0] = 0
    is_prime[1] = 0
    p = 2
    while p * p <= limit:
        if is_prime[p]:
            span = len(range(p * p, limit + 1, p))
            is_prime[p * p:: p] = bytearray(span)
        p += 1
    return is_prime


PRESETS = ("landau", "euler")
"""Single source of truth the tab's preset combobox is built from. "custom"
is deliberately NOT listed here -- it has no fixed formula, the caller
always supplies poly_fn explicitly for it (see _resolve_get_value below)."""


def preset_value(preset, n):
    """f(n) for one of the two hardcoded presets -- plain arithmetic, not a
    typed formula (only "custom" ever goes through a caller-supplied
    callable, see module docstring)."""
    if preset == "landau":
        return n * n + 1
    if preset == "euler":
        return n * n + n + 41
    raise ValueError(f"unknown preset: {preset!r}")


def _resolve_get_value(preset, poly_fn):
    """Shared setup for both check_polynomial_range() and
    check_polynomial_range_from_source() below: resolves the per-n f(n)
    callable -- same "one implementation, used by both entry points" split
    as squares_window._resolve_get_bounds_and_required_count."""
    if preset == "custom":
        if poly_fn is None:
            raise ValueError("preset 'custom' requires poly_fn")
        return poly_fn
    if poly_fn is not None:
        raise ValueError("poly_fn is only accepted for preset 'custom'")
    if preset in PRESETS:
        return lambda n: preset_value(preset, n)
    raise ValueError(f"unknown preset: {preset!r}")


def _values_for_range(get_value, n_from, n_to):
    """f(n) for every n in the range, plus the largest value reached -- the
    caller needs that max BEFORE it can decide how to obtain an is_prime
    array long enough (fresh sieve vs. reading it from somewhere else).
    Raises ValueError on any negative value -- a negative f(n) has no
    meaningful "is it prime?" answer, and an is_prime array can't be
    indexed by it either."""
    values = [get_value(n) for n in range(n_from, n_to + 1)]
    for n, value in zip(range(n_from, n_to + 1), values):
        if value < 0:
            raise ValueError(
                f"f({n}) = {value} is negative -- cannot check primality")
    max_value = max(values) if values else 0
    return values, max_value


def _build_result(is_prime, preset, n_from, n_to, max_value, values, row_cap, row_offset):
    """The actual per-n primality lookup, given an is_prime array already
    known to reach max_value -- shared tail end of both
    check_polynomial_range() and check_polynomial_range_from_source(), so a
    fresh sieve and a storage-sourced array are scored by IDENTICAL logic."""
    rows = []
    prime_count = 0
    for idx, n in enumerate(range(n_from, n_to + 1)):
        value = values[idx]
        is_p = bool(is_prime[value])
        if is_p:
            prime_count += 1
        include_row = idx >= row_offset and (row_cap is None or len(rows) < row_cap)
        if include_row:
            rows.append({"n": n, "value": value, "is_prime": is_p})

    segment_size = n_to - n_from + 1
    return {
        "preset": preset, "n_from": n_from, "n_to": n_to, "max_value": max_value,
        "prime_count": prime_count, "segment_size": segment_size,
        "row_offset": row_offset, "rows": rows,
        "rows_truncated": (row_cap is not None and row_offset + len(rows) < segment_size),
    }


def check_polynomial_range_from_source(preset, n_from, n_to, is_prime_source,
                                        poly_fn=None, row_cap=None, row_offset=0):
    """Same contract as check_polynomial_range() below, except the is_prime
    array is obtained by calling `is_prime_source(max_value)` -- a plain
    callable int -> is_prime bytearray/array-like, long enough to index up
    to max_value -- instead of always sieving fresh in memory. This is what
    lets a caller plug in primeatlas/research_polynomials.py's
    read_is_prime_from_storage(portal_folder, ...) (on-disk-magazyn bridge,
    mirroring squares_window.py's own check_interval_range_from_source) as
    an alternative to a fresh sieve.

    Raises ValueError if `is_prime_source(max_value)` returns an array too
    short to index up to max_value -- same "never silently truncate"
    contract as squares_window.py's own."""
    if n_from < 0 or n_to < n_from:
        raise ValueError("need 0 <= n_from <= n_to")
    get_value = _resolve_get_value(preset, poly_fn)
    values, max_value = _values_for_range(get_value, n_from, n_to)
    is_prime = is_prime_source(max_value)
    if len(is_prime) <= max_value:
        raise ValueError(
            f"is_prime array too short: need index up to {max_value:,}, got "
            f"length {len(is_prime):,}")
    return _build_result(is_prime, preset, n_from, n_to, max_value, values,
                          row_cap, row_offset)


def check_polynomial_range(preset, n_from, n_to, poly_fn=None, row_cap=None, row_offset=0):
    """Checks f(n)'s primality for every n in [n_from, n_to] (n_from may be
    0 -- Euler's own famous run starts there). Always sieves fresh, in
    memory -- see check_polynomial_range_from_source() above for the
    on-disk-magazyn-backed alternative.

    `preset` is one of PRESETS ("landau"/"euler"), or "custom" (in which case
    `poly_fn` -- a plain callable n -> int -- is required; the caller builds
    this from whatever formula the user typed, see this module's own
    docstring on why the eval itself never happens in here).

    Refuses (ValueError) whenever the largest f(n) value needed would
    require a fresh sieve above MAX_SIEVE_BOUND -- see that constant's own
    docstring.

    Returns {"preset":, "n_from":, "n_to":, "max_value":, "prime_count":,
    "segment_size":, "row_offset":, "rows": [...], "rows_truncated": bool}.
    Each row is {"n":, "value":, "is_prime": bool}. "rows" is only the
    row_cap/row_offset page; prime_count/segment_size are always computed
    over the FULL range regardless of paging (same contract as
    squares_window.check_interval_range's own covered/counterexamples)."""
    def _source(max_value):
        if max_value > MAX_SIEVE_BOUND:
            raise ValueError(
                f"the requested range needs a sieve up to {max_value:,}, above this "
                f"tool's {MAX_SIEVE_BOUND:,} ceiling for a fresh in-memory sieve -- "
                f"reduce n_to")
        return sieve_is_prime(max_value)

    return check_polynomial_range_from_source(
        preset, n_from, n_to, _source, poly_fn=poly_fn, row_cap=row_cap,
        row_offset=row_offset)
