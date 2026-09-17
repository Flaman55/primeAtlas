"""
research_polynomials.py -- on-disk-archive storage bridge for the Research
tab's Wielomiany pierwszorodne (prime-generating polynomials) sub-tab.

Re-exports read_is_prime_from_storage/MissingStorageRangeError from
research_goldbach.py rather than duplicating them -- same reasoning as
research_squares.py's own re-export (see that module's own docstring):
read_is_prime_from_storage's logic isn't Goldbach-specific, it just turns
on-disk floor storage into a plain is_prime bytearray for any caller's pure-
math functions to consume, exactly the shape
primeatlas/research/polynomials_window.py's check_polynomial_range_from_source()
needs too.
"""
from .research_goldbach import read_is_prime_from_storage, MissingStorageRangeError

__all__ = ["read_is_prime_from_storage", "MissingStorageRangeError"]
