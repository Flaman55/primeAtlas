"""
research_gaps.py -- on-disk-magazyn storage bridge for the Research tab's
Luki (prime gaps) sub-tab.

Re-exports read_is_prime_from_storage/MissingStorageRangeError from
research_goldbach.py rather than duplicating them -- same reasoning as
research_squares.py's and research_polynomials.py's own re-exports (see
either's own docstring): read_is_prime_from_storage's logic isn't Goldbach-
specific, it just turns on-disk floor storage into a plain is_prime
bytearray for any caller's pure-math functions to consume, exactly the
shape primeatlas/gaps_window.py's check_gap_range_from_source() needs too.
"""
from .research_goldbach import read_is_prime_from_storage, MissingStorageRangeError

__all__ = ["read_is_prime_from_storage", "MissingStorageRangeError"]
