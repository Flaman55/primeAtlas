"""Atlas Hybrid limits and exact parameter selection, without native libraries."""
from array import array
from bisect import bisect_right
from functools import lru_cache
from math import isqrt, log
from threading import Lock

MAX_TARGET = 10 ** 11  # inclusive user-facing limit
MAX_FILTER = 1_000_000
DEFAULT_MAIN = 100
_lock = Lock()


@lru_cache(maxsize=1)
def _primes():
    # Enough for every MAIN <= sqrt(MAX_TARGET) plus a full filter and successor.
    # One compact, reusable table; built only in the GUI's background worker.
    n = MAX_FILTER + isqrt(MAX_TARGET) + 2
    bound = int(n * (log(n) + log(log(n)))) + 100
    flags = bytearray(b'\x01') * (bound + 1)
    flags[:2] = b'\x00\x00'
    for p in range(2, isqrt(bound) + 1):
        if flags[p]:
            start = p * p
            flags[start::p] = b'\x00' * ((bound - start) // p + 1)
    return array('I', (i for i, flag in enumerate(flags) if flag))


def _table():
    with _lock:
        return _primes()


def check_target(end):
    if end - 1 > MAX_TARGET:
        raise ValueError(f"Koniec okna {end - 1:,} przekracza limit Hybrydy {MAX_TARGET:,}. Użyj primesieve.")


def _limit(primes, index, count):
    return primes[index + 1] * primes[index + count + 1] - 1


def _first_main(primes, count, target, lo=0):
    hi = bisect_right(primes, isqrt(MAX_TARGET) + 1)
    while lo < hi:
        mid = (lo + hi) // 2
        if _limit(primes, mid, count) >= target:
            hi = mid
        else:
            lo = mid + 1
    return lo


def parameters(main, count, end=None):
    """Preview, or minimize MAIN first and then the sufficient filter count.

    MAIN is capped at the first prime sufficient for the global limit with
    the selected filter. A larger MAIN cannot extend the permitted range.
    """
    if not isinstance(main, int) or main < 2:
        raise ValueError("MAIN musi być liczbą całkowitą co najmniej 2.")
    if not isinstance(count, int) or not 1 <= count <= MAX_FILTER:
        raise ValueError(f"Filtr musi zawierać od 1 do {MAX_FILTER:,} liczb pierwszych.")
    if end is not None:
        if end < 2:
            raise ValueError("Zakres musi być dodatni.")
        check_target(end)
    primes = _table()
    cap_index = _first_main(primes, count, MAX_TARGET)
    main = min(main, primes[cap_index])
    index = bisect_right(primes, main) - 1
    if end is not None:
        count = MAX_FILTER
        index = _first_main(primes, count, end - 1)
        main = primes[index]
        lo, hi = 1, MAX_FILTER
        while lo < hi:
            mid = (lo + hi) // 2
            if _limit(primes, index, mid) >= end - 1:
                hi = mid
            else:
                lo = mid + 1
        count = lo
    cap_index = _first_main(primes, count, MAX_TARGET)
    main = min(main, primes[cap_index])
    index = bisect_right(primes, main) - 1
    proof = _limit(primes, index, count)
    return dict(main=main, count=count, main_prime=primes[index],
                main_max=primes[cap_index], proof_limit=proof,
                limit=min(MAX_TARGET, proof))
