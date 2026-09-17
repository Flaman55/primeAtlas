"""
squares_window.py -- pure Python (no tkinter, no external dependencies) interval-
contains-enough-primes checks for the Badania -> Przedzialy kwadratowe sub-tab.

Three classical conjectures share the same question shape ("does [a(n), b(n)]
contain at least `required_count` primes?"), differing only in the boundary
formula and the count actually required:

  - Legendre:  [n^2, (n+1)^2],                     required_count = 1
  - Oppermann: [n^2, n^2+n] AND [n^2+n, (n+1)^2],  required_count = 1 (EACH half,
               independently -- this is what makes Oppermann's conjecture
               strictly stronger than Legendre's, not just a rephrasing of it)
  - Brocard:   [p_k^2, p_(k+1)^2] (squares of consecutive primes),
               required_count = 4 -- the actual conjecture ("at least four
               primes between the squares of consecutive primes greater than
               2"), not merely ">=1" (an earlier prime_atlas_v1.py comment
               describing the whole Research-tab layout simplified all three
               conjectures down to the same ">=1" question for the purpose of
               explaining why they share one tab -- this module keeps that
               simplification confined to the OTHER two, where it's actually
               true, and gives Brocard its own real threshold).

Plus a caller-supplied CUSTOM (a(n), b(n)) pair for exploring other formulas --
this module never evaluates user-typed text itself (no eval() anywhere here);
the tab layer is responsible for turning a typed formula into a plain Python
callable first (same "restricted eval lives at the UI layer" split as
generation.py's _eval_quick_number, which also never reaches into this module).

Mirrors goldbach_window.py's own shape (sieve_is_prime + a *_window_rows()-style
range function returning a {"covered", "counterexamples", "rows", ...} dict)
rather than importing from it directly -- see research_squares_tab.py's own
docstring for why each conjecture module in this project stays a self-contained
copy instead of sharing code across conjecture boundaries.
"""
import math

MAX_SIEVE_BOUND = 200_000_000
"""Refuses (ValueError) any check whose largest interval boundary would need a
fresh in-memory sieve bigger than this (~200MB bytearray) -- a safety ceiling
for this Faza-1 version, which always sieves fresh rather than reading from
the on-disk archive (see this module's own docstring: that bridge, mirroring
research_goldbach.py's read_is_prime_from_storage, is planned as a later,
separate addition once real exploration needs push past what a fresh sieve
can hold). Legendre/Oppermann reach this only around n ~= 14,000; Brocard
around the ~1,600th prime -- both comfortably enough range for interactive
GUI exploration in the meantime."""


def sieve_is_prime(limit):
    """Classic sieve of Eratosthenes. Returns a bytearray `is_prime` of length
    limit + 1, is_prime[i] truthy iff i is prime (0 and 1 are not). Same
    algorithm as goldbach_window.py's own copy (see this module's own
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


def primes_upto(limit):
    """Sorted list of every prime <= limit."""
    is_prime = sieve_is_prime(limit)
    return [i for i in range(2, limit + 1) if is_prime[i]]


def _nth_prime_upper_bound(n):
    """Generous upper bound on the n-th prime (1-indexed, p_1=2) -- sizes the
    FIRST sieve attempt in first_n_primes() below; never trusted blindly (that
    function keeps doubling until the sieve actually contains enough primes),
    so this only needs to be a good guess, not a proven bound. Rosser's
    theorem (p_n < n*(ln n + ln ln n) for n >= 6) covers everything past the
    smallest handful of primes, which are hardcoded instead since ln ln n is
    undefined for n < 3."""
    if n < 1:
        raise ValueError("n must be >= 1")
    if n <= 5:
        return [2, 3, 5, 7, 11][n - 1]
    return int(n * (math.log(n) + math.log(math.log(n)))) + 10


def first_n_primes(count):
    """First `count` primes, 1-indexed (result[0] == p_1 == 2). Doubles the
    sieve bound and retries until it actually contains enough primes, rather
    than trusting _nth_prime_upper_bound()'s estimate outright."""
    if count < 1:
        raise ValueError("count must be >= 1")
    bound = _nth_prime_upper_bound(count)
    primes = primes_upto(bound)
    while len(primes) < count:
        bound *= 2
        primes = primes_upto(bound)
    return primes[:count]


PRESETS = {
    "legendre": {"required_count": 1},
    "oppermann": {"required_count": 1},
    "brocard": {"required_count": 4},
}
"""Single source of truth the tab's preset combobox is built from -- each
preset's own default `required_count` (see module docstring for why Brocard's
is 4, not 1). "custom" is deliberately NOT listed here -- it has no fixed
formula for check_interval_range's bounds_fn to derive on its own, the caller
always supplies both required_count and bounds_fn explicitly for it."""


def preset_bounds(preset, n):
    """Returns a list of (a, b) inclusive-bound subintervals for one n under
    `preset` ("legendre"/"oppermann"/"brocard") -- two entries for Oppermann
    (each half checked independently), one otherwise. A plain, non-optimized
    single-n lookup (Brocard's own branch here re-sieves via first_n_primes()
    on every call) -- fine for one-off use or tests; check_interval_range()
    below special-cases Brocard internally instead of calling this in a loop,
    so a multi-n range check never pays that cost more than once.

    Brocard's n indexes consecutive PRIME positions starting at n=1 ->
    (p_1, p_2) = (2, 3). The traditional statement of Brocard's conjecture
    starts from the first pair of ODD primes (3, 5), excluding p=2 -- that is
    a UI-level default (n_from=2), not enforced here; this function computes
    whatever n is actually given."""
    if n < 1:
        raise ValueError("n must be >= 1")
    if preset == "legendre":
        return [(n * n, (n + 1) * (n + 1))]
    if preset == "oppermann":
        mid = n * n + n
        return [(n * n, mid), (mid, (n + 1) * (n + 1))]
    if preset == "brocard":
        p1, p2 = first_n_primes(n + 1)[-2:]
        return [(p1 * p1, p2 * p2)]
    raise ValueError(f"unknown preset: {preset!r}")


def _resolve_get_bounds_and_required_count(preset, n_to, required_count, bounds_fn):
    """Shared setup for both check_interval_range() and
    check_interval_range_from_source() below: validates/builds the per-n
    `get_bounds` callable and resolves `required_count` to a concrete int.
    Factored out so BOTH entry points share exactly one implementation of
    "how to interpret preset/bounds_fn/required_count" -- a fresh sieve and
    a storage-sourced is_prime must never interpret these any differently.

    For Brocard specifically, the needed primes (p_1..p_(n_to+1)) are sieved
    ONCE here rather than via preset_bounds() per row (which would re-sieve
    from scratch for every single n in the range) -- the one genuine
    optimization either entry point gets beyond a plain per-n loop."""
    if preset == "custom":
        if bounds_fn is None:
            raise ValueError("preset 'custom' requires bounds_fn")
        if required_count is None:
            raise ValueError("preset 'custom' requires an explicit required_count")
        get_bounds = bounds_fn
    elif preset == "brocard":
        if bounds_fn is not None:
            raise ValueError("bounds_fn is only accepted for preset 'custom'")
        primes = first_n_primes(n_to + 1)

        def get_bounds(n, _primes=primes):
            p1, p2 = _primes[n - 1], _primes[n]
            return [(p1 * p1, p2 * p2)]
    elif preset in PRESETS:
        if bounds_fn is not None:
            raise ValueError("bounds_fn is only accepted for preset 'custom'")
        get_bounds = lambda n: preset_bounds(preset, n)
    else:
        raise ValueError(f"unknown preset: {preset!r}")

    if required_count is None:
        required_count = PRESETS[preset]["required_count"]
    if required_count < 1:
        raise ValueError("required_count must be >= 1")
    return get_bounds, required_count


def _bounds_for_range(get_bounds, n_from, n_to):
    """Every n's subintervals, computed once, plus the largest boundary any
    of them reaches -- the caller needs that max BEFORE it can decide how to
    obtain an is_prime array long enough (fresh sieve vs. reading it from
    somewhere else)."""
    per_n_bounds = [get_bounds(n) for n in range(n_from, n_to + 1)]
    max_bound = max(b for bounds in per_n_bounds for (_a, b) in bounds)
    return per_n_bounds, max_bound


def _build_result(is_prime, preset, required_count, n_from, n_to, max_bound,
                   per_n_bounds, row_cap, row_offset):
    """The actual per-n covered/counterexample scan, given an is_prime array
    already known to reach max_bound -- shared tail end of both
    check_interval_range() and check_interval_range_from_source(), so a
    fresh sieve and a storage-sourced array are scored by IDENTICAL logic."""
    rows = []
    counterexamples = []
    for idx, n in enumerate(range(n_from, n_to + 1)):
        include_row = idx >= row_offset and (row_cap is None or len(rows) < row_cap)
        intervals = []
        row_covered = True
        for (a, b) in per_n_bounds[idx]:
            if include_row:
                found = [p for p in range(a, b + 1) if is_prime[p]]
                count = len(found)
            else:
                found = None
                count = sum(1 for p in range(a, b + 1) if is_prime[p])
            covered = count >= required_count
            row_covered = row_covered and covered
            intervals.append({"a": a, "b": b, "count": count, "primes": found,
                               "covered": covered})
        if not row_covered:
            counterexamples.append(n)
        if include_row:
            rows.append({"n": n, "intervals": intervals, "covered": row_covered})

    segment_size = n_to - n_from + 1
    return {
        "preset": preset, "required_count": required_count,
        "n_from": n_from, "n_to": n_to, "max_bound": max_bound,
        "covered": not counterexamples, "counterexamples": counterexamples,
        "segment_size": segment_size, "row_offset": row_offset, "rows": rows,
        "rows_truncated": (row_cap is not None and row_offset + len(rows) < segment_size),
    }


def check_interval_range_from_source(preset, n_from, n_to, is_prime_source,
                                      required_count=None, bounds_fn=None,
                                      row_cap=None, row_offset=0):
    """Same contract as check_interval_range() below, except the is_prime
    array is obtained by calling `is_prime_source(max_bound)` -- a plain
    callable int -> is_prime bytearray/array-like, long enough to index up
    to max_bound -- instead of always sieving fresh in memory. This is what
    lets a caller plug in primeatlas/research/research_squares.py's
    read_is_prime_from_storage(portal_folder, ...) (mirroring
    research_goldbach.py's own storage read) as an alternative to a fresh sieve,
    sharing every other bit of
    logic (bounds resolution, the covered/counterexample scan) unchanged --
    see check_interval_range's own docstring for why a fresh sieve stays the
    default, separate entry point rather than folding MAX_SIEVE_BOUND's
    check into this one (that ceiling is specifically about the COST of
    sieving fresh; `is_prime_source` may have already paid a different cost,
    or none at all, to produce its array -- the ceiling decision belongs to
    the source, not to this shared scan).

    Raises ValueError if `is_prime_source(max_bound)` returns an array too
    short to index up to max_bound -- the same "never silently truncate"
    contract goldbach_window.py's own array-length checks use."""
    if n_from < 1 or n_to < n_from:
        raise ValueError("need 1 <= n_from <= n_to")
    get_bounds, required_count = _resolve_get_bounds_and_required_count(
        preset, n_to, required_count, bounds_fn)
    per_n_bounds, max_bound = _bounds_for_range(get_bounds, n_from, n_to)
    is_prime = is_prime_source(max_bound)
    if len(is_prime) <= max_bound:
        raise ValueError(
            f"is_prime array too short: need index up to {max_bound:,}, got "
            f"length {len(is_prime):,}")
    return _build_result(is_prime, preset, required_count, n_from, n_to,
                          max_bound, per_n_bounds, row_cap, row_offset)


def check_interval_range(preset, n_from, n_to, required_count=None,
                          bounds_fn=None, row_cap=None, row_offset=0):
    """Checks, for every n in [n_from, n_to], whether every subinterval
    `preset` defines for that n contains at least `required_count` primes --
    the range-level counterpart of goldbach_window.window_rows(), same
    "verdict/counterexamples always computed over the FULL range, only the
    displayed `rows` slice is paginated via row_cap/row_offset" contract.
    Always sieves fresh, in memory -- see check_interval_range_from_source()
    above for the on-disk-archive-backed alternative.

    `preset` is one of PRESETS's keys, or "custom" (in which case `bounds_fn`
    -- a plain callable n -> [(a, b), ...] -- is required; the caller builds
    this from whatever formula the user typed, see this module's own
    docstring on why the eval itself never happens in here). `required_count`
    defaults to the preset's own PRESETS[preset]["required_count"] when
    omitted; "custom" has no default and must be given explicitly.

    Refuses (ValueError) whenever the largest interval boundary needed would
    require a fresh sieve above MAX_SIEVE_BOUND -- see that constant's own
    docstring.

    Returns {"preset":, "required_count":, "n_from":, "n_to":, "max_bound":,
    "covered": bool, "counterexamples": [n, ...], "segment_size": int,
    "row_offset": int, "rows": [...], "rows_truncated": bool}. Each row is
    {"n":, "covered": bool, "intervals": [{"a":,"b":,"count":,"primes":
    [...] or None, "covered": bool}, ...]} -- "primes" is the full witness
    list only for rows that actually fall inside the returned page (row_cap/
    row_offset window); for every other row (still needed for the full-range
    verdict) only its prime COUNT is computed, never the full list, so a
    huge out-of-page interval doesn't cost more memory than a bool needs."""
    def _source(max_bound):
        if max_bound > MAX_SIEVE_BOUND:
            raise ValueError(
                f"the requested range needs a sieve up to {max_bound:,}, above this "
                f"tool's {MAX_SIEVE_BOUND:,} ceiling for a fresh in-memory sieve -- "
                f"reduce n_to")
        return sieve_is_prime(max_bound)

    return check_interval_range_from_source(
        preset, n_from, n_to, _source, required_count=required_count,
        bounds_fn=bounds_fn, row_cap=row_cap, row_offset=row_offset)
