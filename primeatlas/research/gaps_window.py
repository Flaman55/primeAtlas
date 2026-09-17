"""
gaps_window.py -- pure Python (no tkinter, no external dependencies)
consecutive-prime-gap checks for the Badania -> Luki (prime gaps) sub-tab.

Raw gaps g_n = p_(n+1) - p_n, plus three classical inequalities that are
really just different statistics on the SAME p_n/p_(n+1) sequence,
selectable as an OVERLAY on this one tab rather than three separate tabs
(see prime_atlas_v1.py's own _build_research_section docstring for why):

  - Andrica:     sqrt(p_(n+1)) - sqrt(p_n) < 1 -- conjectured true for every
                 n, still open; largest known values occur at small n
                 (n=1: sqrt(3)-sqrt(2) ~= 0.318).
  - Firoozbakht: p_(n+1)^(1/(n+1)) < p_n^(1/n) -- conjectured true for every
                 n, still open, and the STRONGEST of the three (proven to
                 imply both Andrica's conjecture and a strong form of
                 Cramer's, if it holds).
  - Cramer:      g_n / (log p_n)^2 -- Cramer's conjecture is actually about
                 limsup of this ratio equaling 1 as n -> infinity, an
                 ASYMPTOTIC statement about the whole infinite tail, NOT a
                 per-n strict inequality (unlike the other two). So this
                 overlay reports the ratio as a plain measurement (no
                 "holds" boolean, no counterexamples list -- see
                 _build_result's own docstring) rather than a pass/fail
                 verdict; the tab surfaces the largest ratio seen in the
                 checked range instead.

n indexes prime POSITION (1-indexed, p_1=2), same convention as
squares_window.py's Brocard preset -- n_from/n_to select a range of
consecutive-prime PAIRS (p_n, p_(n+1)), not a range of plain integers.

Mirrors squares_window.py's own shape (sieve_is_prime, duplicated rather
than imported -- see research_squares_tab.py's own docstring for why each
conjecture module in this project stays a self-contained copy) and its
two-entry-point split (check_gap_range / check_gap_range_from_source) for
the same fresh-sieve-vs-archive-bridge reason. Unlike squares_window.py's
first_n_primes (which always sieves fresh, no ceiling of its own until the
caller's outer check), the "find enough primes" logic here
(_first_n_primes_from_source) applies its source's own ceiling on EVERY
retry attempt, so a caller-supplied MAX_SIEVE_BOUND-guarded source refuses
early rather than after already sieving something huge.
"""
import math

MAX_SIEVE_BOUND = 200_000_000
"""Refuses (ValueError) any check whose largest prime searched for would
need a fresh in-memory sieve bigger than this (~200MB bytearray) -- same
safety ceiling and same reasoning as squares_window.py's own constant."""

_OVERLAYS = ("none", "andrica", "firoozbakht", "cramer")


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


def _nth_prime_upper_bound(n):
    """Generous upper bound on the n-th prime (1-indexed, p_1=2) -- sizes the
    FIRST attempt in _first_n_primes_from_source below; never trusted
    blindly (that function keeps doubling until the source actually
    contains enough primes), so this only needs to be a good guess, not a
    proven bound. Same as squares_window.py's own copy -- Rosser's theorem
    (p_n < n*(ln n + ln ln n) for n >= 6) covers everything past the
    smallest handful of primes, which are hardcoded instead since ln ln n is
    undefined for n < 3."""
    if n < 1:
        raise ValueError("n must be >= 1")
    if n <= 5:
        return [2, 3, 5, 7, 11][n - 1]
    return int(n * (math.log(n) + math.log(math.log(n)))) + 10


def _first_n_primes_from_source(is_prime_source, count):
    """First `count` primes (1-indexed, result[0] == p_1 == 2), found by
    scanning an is_prime array obtained from `is_prime_source(bound)` --
    doubles `bound` and re-calls the source until the array actually
    contains `count` primes, rather than trusting _nth_prime_upper_bound's
    estimate outright (same retry idea as squares_window.first_n_primes,
    generalized to an injectable source instead of always sieving fresh).
    is_prime_source's own ceiling check (see MAX_SIEVE_BOUND / the fresh-
    sieve _source closures below) runs on EVERY attempt here, including the
    first, so an oversized request is refused before ever finding a single
    prime, not just after the fact."""
    bound = _nth_prime_upper_bound(count)
    while True:
        is_prime = is_prime_source(bound)
        primes = []
        for i, flag in enumerate(is_prime):
            if flag:
                primes.append(i)
                if len(primes) == count:
                    return primes
        bound *= 2


def _build_result(primes, n_from, n_to, overlay, row_cap, row_offset):
    """The actual per-n gap/overlay scan, given a `primes` list already
    known to contain at least p_1..p_(n_to+1) -- shared tail end of both
    check_gap_range() and check_gap_range_from_source(), so a fresh sieve
    and a storage-sourced prime list are scored by IDENTICAL logic.

    "counterexamples"/an per-row "holds" boolean only apply to Andrica and
    Firoozbakht (per-n strict inequalities); for "cramer" and "none",
    "holds" stays None on every row and counterexamples stays empty -- see
    module docstring for why Cramer's is an asymptotic statement, not a
    per-n verdict. max_gap and max_cramer_ratio are always computed over
    the FULL range regardless of row_cap/row_offset paging (same "verdict
    always full-range, only the display paginates" contract as
    squares_window.check_interval_range's own covered/counterexamples)."""
    rows = []
    counterexamples = []
    max_gap = None
    max_cramer_ratio = None
    for idx, n in enumerate(range(n_from, n_to + 1)):
        p_n = primes[n - 1]
        p_n1 = primes[n]
        gap = p_n1 - p_n
        if max_gap is None or gap > max_gap:
            max_gap = gap

        overlay_value = None
        holds = None
        if overlay == "andrica":
            overlay_value = math.sqrt(p_n1) - math.sqrt(p_n)
            holds = overlay_value < 1
        elif overlay == "firoozbakht":
            overlay_value = p_n1 ** (1.0 / (n + 1))
            holds = overlay_value < p_n ** (1.0 / n)
        elif overlay == "cramer":
            overlay_value = gap / (math.log(p_n) ** 2)
            if max_cramer_ratio is None or overlay_value > max_cramer_ratio:
                max_cramer_ratio = overlay_value

        if holds is False:
            counterexamples.append(n)
        include_row = idx >= row_offset and (row_cap is None or len(rows) < row_cap)
        if include_row:
            rows.append({"n": n, "p_n": p_n, "p_n1": p_n1, "gap": gap,
                         "overlay_value": overlay_value, "holds": holds})

    segment_size = n_to - n_from + 1
    return {
        "overlay": overlay, "n_from": n_from, "n_to": n_to,
        "segment_size": segment_size, "row_offset": row_offset, "rows": rows,
        "rows_truncated": (row_cap is not None and row_offset + len(rows) < segment_size),
        "counterexamples": counterexamples,
        "max_gap": max_gap, "max_cramer_ratio": max_cramer_ratio,
    }


def check_gap_range_from_source(n_from, n_to, is_prime_source, overlay="none",
                                 row_cap=None, row_offset=0):
    """Same contract as check_gap_range() below, except the prime list is
    obtained via `is_prime_source(bound)` -- a plain callable int -> is_prime
    bytearray/array-like -- instead of always sieving fresh in memory. This
    is what lets a caller plug in primeatlas/research/research_gaps.py's
    read_is_prime_from_storage(portal_folder, ...) (on-disk-archive bridge,
    mirroring squares_window.py's own check_interval_range_from_source) as
    an alternative to a fresh sieve.

    Raises ValueError if is_prime_source never returns an array with enough
    primes (see _first_n_primes_from_source's own docstring: a storage-
    backed source that hits MissingStorageRangeError propagates that
    instead, since retrying with a bigger bound against fixed on-disk floors
    can never succeed where a smaller one failed)."""
    if n_from < 1 or n_to < n_from:
        raise ValueError("need 1 <= n_from <= n_to")
    if overlay not in _OVERLAYS:
        raise ValueError(f"unknown overlay: {overlay!r}")
    primes = _first_n_primes_from_source(is_prime_source, n_to + 1)
    return _build_result(primes, n_from, n_to, overlay, row_cap, row_offset)


def check_gap_range(n_from, n_to, overlay="none", row_cap=None, row_offset=0):
    """Checks the gap g_n = p_(n+1)-p_n, plus an optional overlay
    (Andrica/Firoozbakht/Cramer), for every n in [n_from, n_to]
    (n_from >= 1, p_1 = 2). Always sieves fresh, in memory -- see
    check_gap_range_from_source() above for the on-disk-archive-backed
    alternative.

    Refuses (ValueError) whenever the largest prime search needed would
    require a fresh sieve above MAX_SIEVE_BOUND -- see that constant's own
    docstring.

    Returns {"overlay":, "n_from":, "n_to":, "segment_size":, "row_offset":,
    "rows": [...], "rows_truncated": bool, "counterexamples": [n, ...],
    "max_gap": int, "max_cramer_ratio": float or None}. Each row is
    {"n":, "p_n":, "p_n1":, "gap":, "overlay_value": float or None,
    "holds": bool or None}."""
    def _source(bound):
        if bound > MAX_SIEVE_BOUND:
            raise ValueError(
                f"the requested range needs a sieve up to {bound:,}, above this "
                f"tool's {MAX_SIEVE_BOUND:,} ceiling for a fresh in-memory sieve -- "
                f"reduce n_to")
        return sieve_is_prime(bound)

    return check_gap_range_from_source(
        n_from, n_to, _source, overlay=overlay, row_cap=row_cap, row_offset=row_offset)
