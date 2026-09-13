"""
research_squares.py -- on-disk-magazyn storage bridge for the Research tab's
Przedzialy kwadratowe (square intervals) sub-tab (Faza 2, 2026-09-13).

Re-exports read_is_prime_from_storage/MissingStorageRangeError from
research_goldbach.py rather than duplicating them -- despite that module's
name, nothing about read_is_prime_from_storage's own logic is Goldbach-
specific (see its own docstring): it just turns on-disk floor storage into a
plain is_prime bytearray for ANY caller's pure-math functions to consume,
exactly the shape primeatlas/squares_window.py's
check_interval_range_from_source() needs too. Unlike squares_window.py's own
deliberate duplication of goldbach_window.py's sieve_is_prime (a ~15-line
primitive, cheap and safe to keep independent per-conjecture copies of),
this ~100-line storage reader carries real, previously-debugged correctness
subtleties (partial-file detection, floor-boundary math -- see its own
docstring's history of bugs found and fixed) that a second copy could only
ever drift out of sync with, never actually duplicate safely.
"""
from .research_goldbach import read_is_prime_from_storage, MissingStorageRangeError

__all__ = ["read_is_prime_from_storage", "MissingStorageRangeError"]
