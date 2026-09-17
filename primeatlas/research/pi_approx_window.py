"""
pi_approx_window.py -- pure Python (no tkinter, no external dependencies)
pi(x)-approximation-accuracy checks for the Badania -> Przyblizenia pi(x)
sub-tab.

Compares the REAL count of primes <= x (computed via a fresh sieve or read
from the on-disk archive) against two classical analytic approximations, at
a set of checkpoints x = x_from, x_from+step, ..., x_to:

  - li(x): the logarithmic integral, li(x) = Ei(ln x) for x > 1 (the
    standard definition matching the usual Prime Number Theorem statement
    pi(x) ~ li(x)). Implemented via the exponential integral Ei(z), from
    its own convergent power series (see _ei's own docstring) -- no scipy/
    mpmath dependency; this project keeps its own pure-Python
    implementation rather than pulling in a heavy optional library for one
    function (unlike primality.py's sympy-is-optional pattern, this module
    doesn't lean on an external library at all, not even optionally).
  - R(x): Riemann's R function, a substantially better approximation than
    li(x) for the same x -- this is a well-known, NOT-a-conjecture fact
    (unlike Squares/Polynomials/Gaps, this whole tab is a measurement-
    quality question, not a yes/no conjecture check -- see
    prime_atlas_v1.py's own _build_research_section docstring). Computed
    via the convergent Gram series R(x) = 1 + sum_{k=1}^inf (ln x)^k /
    (k * k! * zeta(k+1)), using a cheap Euler-Maclaurin-corrected zeta(s)
    for integer s >= 2 (see _zeta's own docstring) -- good to several
    correct digits, plenty for this tab's educational accuracy comparison,
    not a research-grade zeta implementation.

Unlike squares_window.py's covering check or gaps_window.py's per-n
inequality, there is no conjecture verdict here at all -- x, pi(x), li(x),
R(x), and their errors are reported as plain numbers for every checkpoint,
same measurement-only shape as polynomials_window.py's prime_count/density
(see that module's own docstring for the same reasoning).

Mirrors squares_window.py's own two-entry-point split (check_pi_approx_
range / check_pi_approx_range_from_source) for the same fresh-sieve-vs-
archive-bridge reason, and its own duplicated sieve_is_prime (see
research_squares_tab.py's own docstring for why each conjecture/feature
module in this project stays a self-contained copy). A THIRD entry point,
check_pi_approx_range_with_pi_func(), skips the is_prime array entirely --
it exists for primecount (Kim Walisch's combinatorial prime-counting
library, see prime_sieve/prime_count_primecount.py), which computes pi(x)
directly without ever sieving, reaching x far past MAX_SIEVE_BOUND.
"""
import math

MAX_SIEVE_BOUND = 200_000_000
"""Refuses (ValueError) any check whose largest checkpoint would need a
fresh in-memory sieve bigger than this (~200MB bytearray) -- same safety
ceiling and same reasoning as squares_window.py's own constant."""

_EULER_GAMMA = 0.5772156649015328606065120900824024310421593359399235988057672348849


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


def _ei(z):
    """Exponential integral Ei(z) for z > 0, via its convergent power
    series (Abramowitz & Stegun 5.1.11): Ei(z) = gamma + ln(z) +
    sum_{k=1}^inf z^k/(k*k!). Sums until a term's relative contribution is
    negligible, capped at a generous iteration count -- safe in ordinary
    double precision for every z this tab ever needs (z = ln(x), x bounded
    by MAX_SIEVE_BOUND, so z never exceeds ~19). li() below only ever calls
    this for x > 1, so z > 0 always -- Ei's singularity at z=0 (and its
    different branch for z<0) never comes up here."""
    if z <= 0:
        raise ValueError("Ei(z) is only implemented here for z > 0")
    total = _EULER_GAMMA + math.log(z)
    term = 1.0
    for k in range(1, 500):
        term *= z / k
        contribution = term / k
        total += contribution
        if k > 5 and abs(contribution) < 1e-16 * abs(total):
            break
    return total


def li(x):
    """Logarithmic integral li(x) = Ei(ln x), for x > 1 -- see module
    docstring for why this (not the "offset" Li(x) = li(x) - li(2) variant
    some textbooks use) is the right definition for comparing against
    pi(x) under the Prime Number Theorem's usual statement."""
    if x <= 1:
        raise ValueError("li(x) is only implemented here for x > 1")
    return _ei(math.log(x))


_ZETA_CACHE = {}


def _zeta(s, terms=300):
    """Riemann zeta function for real s > 1, via direct summation of the
    first `terms` terms plus an Euler-Maclaurin midpoint tail correction
    (sum_{n=terms+1}^infty n^-s ~= (terms+0.5)^(1-s)/(s-1)) -- accurate to
    several correct digits for every s this module calls it with (s =
    k+1 >= 2 in riemann_r's Gram series below), which is all R(x) needs for
    a useful educational accuracy comparison; NOT a research-grade zeta
    implementation. Cached per s -- riemann_r() calls this once per k for
    every row, and the same small set of integer k's repeats across every
    row/every call in a single process (module-level cache, deliberately
    never cleared -- zeta(s) for a fixed integer s never changes)."""
    cached = _ZETA_CACHE.get(s)
    if cached is not None:
        return cached
    total = 0.0
    for n in range(1, terms + 1):
        total += 1.0 / (n ** s)
    total += (terms + 0.5) ** (1 - s) / (s - 1)
    _ZETA_CACHE[s] = total
    return total


def riemann_r(x, max_terms=200):
    """Riemann's R function via the convergent Gram series R(x) = 1 +
    sum_{k=1}^inf (ln x)^k / (k*k!*zeta(k+1)) -- see module docstring. Sums
    until a term's relative contribution is negligible, capped at
    `max_terms`. The k-th term t_k = (ln x)^k/(k*k!) is built iteratively
    via t_k = t_(k-1) * ln(x) * (k-1)/k^2 (from the ratio t_k/t_(k-1)),
    avoiding any explicit factorial (which would overflow for k in the low
    hundreds long before the terms themselves become negligible)."""
    if x <= 1:
        raise ValueError("riemann_r(x) is only implemented here for x > 1")
    ln_x = math.log(x)
    total = 1.0
    t = 0.0
    for k in range(1, max_terms + 1):
        t = ln_x if k == 1 else t * ln_x * (k - 1) / (k * k)
        contribution = t / _zeta(k + 1)
        total += contribution
        if k > 5 and abs(contribution) < 1e-16 * abs(total):
            break
    return total


def _build_checkpoints(x_from, x_to, step):
    """x_from, x_from+step, ..., always ending with x_to itself even when
    step doesn't evenly divide (x_to - x_from) -- the endpoint the user
    actually typed should always appear as its own row, not get silently
    rounded away."""
    checkpoints = list(range(x_from, x_to + 1, step))
    if checkpoints[-1] != x_to:
        checkpoints.append(x_to)
    return checkpoints


def _pi_at_checkpoints(is_prime, checkpoints):
    """pi(x) (count of primes <= x) for every x in the sorted `checkpoints`
    list, via ONE pass over is_prime split into non-overlapping slices
    (each byte counted exactly once across the whole call) -- deliberately
    NOT one sum(is_prime[0:x+1]) per checkpoint independently, which would
    re-scan the low end of the array once per checkpoint and cost O(len(
    checkpoints) * x_to) instead of O(x_to) total."""
    results = []
    running_total = 0
    prev_end = 0
    for x in checkpoints:
        running_total += sum(is_prime[prev_end:x + 1])
        results.append(running_total)
        prev_end = x + 1
    return results


def _build_result(checkpoints, pi_values, x_from, x_to, step, row_cap, row_offset):
    """The actual per-checkpoint li(x)/R(x)/error computation, given
    already-known pi(x) values -- shared tail end of both
    check_pi_approx_range() and check_pi_approx_range_from_source(), so a
    fresh sieve and a storage-sourced count are scored by IDENTICAL logic.
    max_li_error/max_r_error (largest ABSOLUTE error seen) are always
    computed over the FULL range regardless of row_cap/row_offset paging --
    same "verdict always full-range, only the display paginates" contract
    as squares_window.check_interval_range's own covered/counterexamples."""
    rows = []
    max_li_error = None
    max_r_error = None
    for idx, (x, pi_x) in enumerate(zip(checkpoints, pi_values)):
        li_x = li(x)
        r_x = riemann_r(x)
        li_error = li_x - pi_x
        r_error = r_x - pi_x
        if max_li_error is None or abs(li_error) > abs(max_li_error):
            max_li_error = li_error
        if max_r_error is None or abs(r_error) > abs(max_r_error):
            max_r_error = r_error
        include_row = idx >= row_offset and (row_cap is None or len(rows) < row_cap)
        if include_row:
            rows.append({"x": x, "pi_x": pi_x, "li_x": li_x, "r_x": r_x,
                         "li_error": li_error, "r_error": r_error})

    segment_size = len(checkpoints)
    return {
        "x_from": x_from, "x_to": x_to, "step": step,
        "segment_size": segment_size, "row_offset": row_offset, "rows": rows,
        "rows_truncated": (row_cap is not None and row_offset + len(rows) < segment_size),
        "max_li_error": max_li_error, "max_r_error": max_r_error,
    }


def check_pi_approx_range_from_source(x_from, x_to, step, is_prime_source,
                                       row_cap=None, row_offset=0):
    """Same contract as check_pi_approx_range() below, except the is_prime
    array is obtained by calling `is_prime_source(x_to)` -- a plain
    callable int -> is_prime bytearray/array-like, long enough to index up
    to x_to -- instead of always sieving fresh in memory. This is what lets
    a caller plug in primeatlas/research/research_pi_approx.py's read_is_prime_
    from_storage(portal_folder, ...) (on-disk-archive bridge, mirroring
    squares_window.py's own check_interval_range_from_source) as an
    alternative to a fresh sieve.

    Raises ValueError if `is_prime_source(x_to)` returns an array too
    short to index up to x_to -- same "never silently truncate" contract
    as squares_window.py's own."""
    if x_from < 2 or x_to < x_from:
        raise ValueError("need 2 <= x_from <= x_to")
    if step < 1:
        raise ValueError("step must be >= 1")
    checkpoints = _build_checkpoints(x_from, x_to, step)
    is_prime = is_prime_source(x_to)
    if len(is_prime) <= x_to:
        raise ValueError(
            f"is_prime array too short: need index up to {x_to:,}, got "
            f"length {len(is_prime):,}")
    pi_values = _pi_at_checkpoints(is_prime, checkpoints)
    return _build_result(checkpoints, pi_values, x_from, x_to, step, row_cap, row_offset)


def check_pi_approx_range(x_from, x_to, step, row_cap=None, row_offset=0):
    """Checks li(x)/R(x) against the real pi(x) for every checkpoint
    x = x_from, x_from+step, ..., x_to (x_from >= 2). Always sieves fresh,
    in memory -- see check_pi_approx_range_from_source() above for the
    on-disk-archive-backed alternative.

    Refuses (ValueError) whenever x_to would require a fresh sieve above
    MAX_SIEVE_BOUND -- see that constant's own docstring.

    Returns {"x_from":, "x_to":, "step":, "segment_size":, "row_offset":,
    "rows": [...], "rows_truncated": bool, "max_li_error": float,
    "max_r_error": float}. Each row is {"x":, "pi_x":, "li_x":, "r_x":,
    "li_error":, "r_error":} -- errors are li_x/r_x MINUS pi_x (positive
    means the approximation overshoots the real count)."""
    def _source(limit):
        if limit > MAX_SIEVE_BOUND:
            raise ValueError(
                f"the requested range needs a sieve up to {limit:,}, above this "
                f"tool's {MAX_SIEVE_BOUND:,} ceiling for a fresh in-memory sieve -- "
                f"reduce x_to")
        return sieve_is_prime(limit)

    return check_pi_approx_range_from_source(
        x_from, x_to, step, _source, row_cap=row_cap, row_offset=row_offset)


def check_pi_approx_range_with_pi_func(x_from, x_to, step, pi_func, row_cap=None, row_offset=0):
    """Same contract as check_pi_approx_range() above, except pi(x) itself
    is obtained by calling `pi_func(checkpoints)` -- a plain callable
    list[int] -> list[int], returning the EXACT count of primes <= x for
    EVERY checkpoint in one call, same order -- instead of building/
    scanning an is_prime array at all. Batched (all checkpoints in one
    call) rather than one call per x deliberately: this is what lets a
    caller plug in primecount (Kim Walisch's combinatorial prime-counting
    library, see primeatlas/research/research_pi_approx_tab.py's own "primecount"
    data-source mode) via a single WSL round-trip per page instead of one
    per row -- a real cost when each round trip is a separate wsl.exe
    process launch.

    Deliberately has NO MAX_SIEVE_BOUND ceiling of its own -- that ceiling
    is specifically about the cost of building a full is_prime array up to
    x_to; primecount's own algorithm never builds one at all (see
    prime_sieve/prime_count_primecount.py's own module docstring for its
    very different, sub-x time/memory complexity), so it can legitimately
    answer for x FAR past what this module's own sieve-based paths could
    ever attempt. Whatever cost/timeout limits apply belong to `pi_func`
    itself (e.g. a WSL round-trip timeout), not to this shared entry point
    -- same "the ceiling decision belongs to the source" reasoning as
    squares_window.check_interval_range_from_source's own docstring."""
    if x_from < 2 or x_to < x_from:
        raise ValueError("need 2 <= x_from <= x_to")
    if step < 1:
        raise ValueError("step must be >= 1")
    checkpoints = _build_checkpoints(x_from, x_to, step)
    pi_values = pi_func(checkpoints)
    if len(pi_values) != len(checkpoints):
        raise ValueError(
            f"pi_func returned {len(pi_values)} values for {len(checkpoints)} checkpoints")
    return _build_result(checkpoints, pi_values, x_from, x_to, step, row_cap, row_offset)
