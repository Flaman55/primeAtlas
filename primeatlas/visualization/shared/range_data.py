"""
range_data.py -- launch-time data selection shared by every visualization: the
Load Range slice of a loaded prime array and the N a view opens at for a given
--source.

Self-contained sys.path bootstrap (mirrors renderer.py's own -- see that
file's module docstring for the full "why plain-script-path" explanation):
needed so the primeatlas.* imports below work whether this module is imported
after renderer.py has already run its own bootstrap, or on its own (e.g.
directly from a test).
"""

import os
import sys

import numpy as np

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_PRIME_SIEVE_DIR = os.path.join(_REPO_ROOT, "prime_sieve")
if _PRIME_SIEVE_DIR not in sys.path:
    sys.path.insert(0, _PRIME_SIEVE_DIR)

from primeatlas.visualization.shared.bigint import to_prime_array


# ---------------------------------------------------------------------------
# Load Range: switch to a FIXED ring set (a slice of already-loaded primes
# in [from, to]), independent of N, mirroring
# SieveModel's "range"/slice mode (see that class's own module doc-comment:
# sequential mode's ring set is primesUpTo(n) and grows with n; range mode's
# ring set is a fixed array chosen once and never re-filtered by n again --
# only each ring's phase/hit status still depends on n via ring_positions,
# which doesn't care how its `primes` argument was derived).
# ---------------------------------------------------------------------------

def load_prime_range_slice(primes, from_n, to_n):
    """The ascending sub-array of `primes` (this renderer's own already-
    loaded array -- there is no separate always-larger data source here the
    way the JS's PrimeDataSource is, so `primes` itself plays that role)
    whose values fall in [from_n, to_n] inclusive. Ports
    SieveModel.loadPrimeRange's slicing half only -- the mode-switching side
    effects (n reset to 0, auto-populating Track P, printing an info line)
    are run()'s own job, kept out of this pure function the same way this
    module keeps every other GL-adjacent decision out of its pure helpers.

    Raises ValueError (Python's RangeError-equivalent) for the same two
    cases SieveModel.loadPrimeRange throws for: an inverted range (`from_n
    > to_n`), or a `to_n` beyond what is actually loaded (`to_n >
    primes[-1]`, or `primes` is empty) -- ports the "exceeds the loaded
    ceiling" check using THIS renderer's own loaded array as the ceiling."""
    if from_n > to_n:
        raise ValueError(f"load_prime_range_slice: invalid range [{from_n}, {to_n}] (from > to)")
    primes_arr = to_prime_array(primes)
    ceiling = int(primes_arr[-1]) if len(primes_arr) else -1
    if to_n > ceiling:
        raise ValueError(f"load_prime_range_slice: {to_n} exceeds the loaded ceiling ({ceiling})")
    lo = int(np.searchsorted(primes_arr, from_n, side="left"))
    hi = int(np.searchsorted(primes_arr, to_n, side="right"))
    return primes_arr[lo:hi]


def initial_n_for_source(source, upto, primes):
    """Picks the N the ring view should OPEN on, given how the ring array was
    sourced.

    For --source sieve/archive, the user has a real target N in mind
    (rings_tab.py's N field, passed through verbatim as --upto) -- the view
    must open exactly there, not on whatever the last loaded prime happens
    to be. ring_positions() computes is_hit as n % prime == 0 (real divisors
    of N), so N is not required to be prime itself; snapping to primes[-1]
    would silently show the wrong number (e.g. typing 1000 would open on
    N=997, the largest prime <=1000, with "Factors of N: 997" -- itself,
    since 997 is prime -- instead of 1000's real factors 2 and 5).

    --source synthetic has no user-specified target N at all (only --count,
    an arbitrary ring COUNT -- see load_synthetic's own docstring), so there
    is no "the value the user asked for" to open on; it keeps using the last
    generated value instead."""
    if source == "synthetic":
        return int(primes[-1]) if len(primes) else 0
    return upto
