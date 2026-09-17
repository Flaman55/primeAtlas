"""
research_pi_approx.py -- on-disk-archive storage bridge for the Research
tab's Przyblizenia pi(x) (pi(x) approximations) sub-tab.

Re-exports read_is_prime_from_storage/MissingStorageRangeError from
research_goldbach.py rather than duplicating them -- same reasoning as
research_squares.py's/research_polynomials.py's/research_gaps.py's own
re-exports (see any of their own docstrings): read_is_prime_from_storage's
logic isn't Goldbach-specific, it just turns on-disk floor storage into a
plain is_prime bytearray for any caller's pure-math functions to consume,
exactly the shape primeatlas/pi_approx_window.py's check_pi_approx_range_
from_source() needs too.
"""
from .research_goldbach import read_is_prime_from_storage, MissingStorageRangeError

__all__ = ["read_is_prime_from_storage", "MissingStorageRangeError"]
