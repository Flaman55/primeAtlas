"""
pi_count_notice.py -- whether a run that counts pi(L) (the compute_sieving_primes_count /
use_known_pi_seed diagnostic of an engine run) has to count it from zero on its floor, and
about how long that takes. No tkinter here; pi_count_notice_controls.py asks the user.

An engine counts pi(L_final), L_final = isqrt(the batch's top) + 1, through the per-floor
cache sieving_prime_count_v5.count_sieving_primes_cached() keeps in the storage
(10p{N}/sieving_primes_count_cache.json: the largest L counted on the floor and its count;
prime_sieve_v4_1.py keeps the same file the same way). A floor without it, or a run whose
first batch lies below its L (the cache holds no prefix for a smaller L), counts from zero
(from the largest known pi(10^n) below L with the seed): that run's total time then holds
the whole count. Every other run adds only the primes above the cached L.
"""
import json
import math
import os

from sieving_prime_count_v5 import SIEVING_PRIMES_COUNT_CACHE_FILENAME, _seed_from_known_pi

CACHE_FILENAME = SIEVING_PRIMES_COUNT_CACHE_FILENAME

# Seconds per counted prime for the time the notice names. Arbitrary, inside the range
# measured with libprimesieve on one machine (0.25 ns at L = 10^11 to 0.67 ns at L = 10^14).
SECONDS_PER_PRIME = 0.5e-9

_SIMPSON_STEPS = 64


def l_final(hi):
    """The engines' L_final for a batch ending at `hi` (exclusive)."""
    return math.isqrt(hi) + 1


def _li_from_2(x):
    """li(x) - li(2) = integral of dt / ln t over [2, x]: Simpson's rule on e^u / u, u = ln t."""
    if x <= 2:
        return 0.0
    a, b = math.log(2), math.log(x)
    h = (b - a) / _SIMPSON_STEPS
    total = 0.0
    for i in range(_SIMPSON_STEPS + 1):
        u = a + i * h
        weight = 1 if i in (0, _SIMPSON_STEPS) else (4 if i % 2 else 2)
        total += weight * math.exp(u) / u
    return total * h / 3


def primes_between(start, stop):
    """About pi(stop) - pi(start); 0 for an empty or reversed span. A span narrow against its
    position uses (stop - start) / ln(midpoint), where a difference of two li values would
    lose its digits."""
    if stop <= start:
        return 0.0
    if stop - start < stop * 1e-6:
        return (stop - start) / math.log((start + stop) / 2)
    return _li_from_2(stop) - _li_from_2(start)


def read_cache(portal_folder, floor):
    """(l_final, count) of the floor's cache, None when there is none or it is unreadable."""
    path = os.path.join(portal_folder, f"10p{floor}", CACHE_FILENAME)
    try:
        with open(path, encoding="utf-8") as f:
            cached = json.load(f)
        return int(cached["l_final"]), int(cached["count"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def counts_from_zero(cache, l_first):
    """True when a run whose first batch reaches L = l_first counts pi(L) from zero."""
    return cache is None or l_first < cache[0]


def estimate(portal_folder, floor, lo, hi, first_hi, use_seed):
    """{from_zero, seconds} of counting pi(L) in a run over [lo, hi) whose first batch ends at
    first_hi: seconds is the count from zero (or from the seed) up to the run's last L."""
    l_first = l_final(max(min(first_hi, hi), lo + 1))
    seed = _seed_from_known_pi(l_first) if use_seed else None
    start = seed[0] if seed is not None else 0
    return {"from_zero": counts_from_zero(read_cache(portal_folder, floor), l_first),
            "seconds": primes_between(start, l_final(hi)) * SECONDS_PER_PRIME}


def notice_needed(counting_on, est):
    return bool(counting_on) and est["from_zero"]


def format_duration(seconds):
    if seconds < 90:
        return f"~{max(1, round(seconds))} s"
    if seconds < 3600:
        return f"~{round(seconds / 60)} min"
    return f"~{seconds / 3600:.1f} h"
