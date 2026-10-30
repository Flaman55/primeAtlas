"""Sieving-prime count pi(L_final) of a v5 run: a diagnostic statistic only (the sieve never
reads it), counted by libprimesieve through the v5 engine, with a per-floor cache and an
optional seed from known pi(10^n) values so repeat and first calls stay cheap."""
import os

from engine_v5_lib import load_lib


def count_sieving_primes(limit):
    """pi(limit): how many sieving primes p in [2, limit] (limit = L_final) were used to
    sieve the combined window, counted by libprimesieve via the C engine."""
    lib = load_lib()
    return int(lib.count_sieving_primes(limit))


def count_sieving_primes_range(start, stop):
    """pi(stop) - pi(start) -- primes in (start, stop]. Thin wrapper over the engine's
    additive count_sieving_primes_range(), used by count_sieving_primes_cached() below to
    count only the NEW territory between a cached L and a larger one, instead of recounting
    from 0 every time."""
    lib = load_lib()
    return int(lib.count_sieving_primes_range(start, stop))


SIEVING_PRIMES_COUNT_CACHE_FILENAME = "sieving_primes_count_cache.json"

# KNOWN_PI_10N -- exact pi(10^n) values for n=1..29, taken from the "x, pi(x)" table on
# Wikipedia's Prime-counting function page (see KNOWN_PI_SOURCE_URL). That page in turn
# cites the primary sources for each value (Meissel/Lehmer-method computations by Buethe/
# Franke/Jost/Kleinjung and Platt up to 10^24-25, Staple for 10^26, and Baugh/Walisch for
# 10^27-29 -- see the Wikipedia article's own footnotes for full citations).
#
# count_sieving_primes_cached() below already avoids recounting a floor's ENTIRE
# [0, L_final] range on every call once a cache exists for that floor (see that function's
# own docstring) -- but the very FIRST call on a floor still pays the full
# count_sieving_primes(0, L_final) cost from scratch: at floor-scale L_final (order 10^13+)
# that alone can take minutes. Since L_final = isqrt(combined_hi) is itself only ~half as
# many digits as the floor it belongs to, a floor most people would ever reach (order 10^58
# or below) has an L_final at or below 10^29 -- squarely inside this table's range. Seeding
# the cold-start count from the largest known pi(10^n) <= L_final and counting only the
# remaining sliver via count_sieving_primes_range() turns that first-ever call into the
# same cheap "incremental" shape every SUBSEQUENT call on that floor already gets, instead
# of a full from-zero recount.
#
# This table is used ONLY when use_known_pi_seed=True is explicitly passed through (default
# False everywhere -- see prime_sieve_v5.py's COMPUTE_SIEVING_PRIMES_COUNT comment for the sibling "off by
# default" reasoning). Even if a transcription error ever crept into a single entry here, the
# worst case is a wrong number in one benchmark_log.csv diagnostic column -- sieving_primes_
# count is never read by the sieve/marking logic itself (see the module docstring), so this table carries zero correctness risk for the actual generated primes.
KNOWN_PI_SOURCE_URL = "https://en.wikipedia.org/wiki/Prime-counting_function"

KNOWN_PI_10N = {
    1: 4,
    2: 25,
    3: 168,
    4: 1229,
    5: 9592,
    6: 78498,
    7: 664579,
    8: 5761455,
    9: 50847534,
    10: 455052511,
    11: 4118054813,
    12: 37607912018,
    13: 346065536839,
    14: 3204941750802,
    15: 29844570422669,
    16: 279238341033925,
    17: 2623557157654233,
    18: 24739954287740860,
    19: 234057667276344607,
    20: 2220819602560918840,
    21: 21127269486018731928,
    22: 201467286689315906290,
    23: 1925320391606803968923,
    24: 18435599767349200867866,
    25: 176846309399143769411680,
    26: 1699246750872437141327603,
    27: 16352460426841680446427399,
    28: 157589269275973410412739598,
    29: 1520698109714272166094258063,
}


def _seed_from_known_pi(limit):
    """Returns (seed_l, seed_count, source_url) for the LARGEST 10**n <= limit that
    KNOWN_PI_10N has an entry for, or None if limit < 10 (no known power of ten fits) or
    limit is small enough that seeding wouldn't save anything anyway. Pure function, no
    ctypes/primesieve dependency -- deliberately kept that way so it's unit-testable without
    the compiled engine .so being present (see this repo's unitTests/ for that test)."""
    best_n = None
    for n in KNOWN_PI_10N:
        if 10 ** n <= limit and (best_n is None or n > best_n):
            best_n = n
    if best_n is None:
        return None
    return 10 ** best_n, KNOWN_PI_10N[best_n], KNOWN_PI_SOURCE_URL


def count_sieving_primes_cached(portal_folder, base_power, limit, use_known_pi_seed=False):
    """pi(limit), reusing a per-floor cache instead of recomputing from 0 every call.

    Motivation: repeat calls to this diagnostic on the SAME floor almost always ask for a
    limit that is equal to, or only marginally larger than, the previous call's limit --
    L_final = isqrt(combined_hi) grows far slower than the floor's own windows do (going
    another 10 windows deeper at floor 20 nudges L_final by single digits out of ~10^10).
    Counting that tiny sliver via count_sieving_primes_range(cached_l, limit) is dramatically
    cheaper than recounting the whole [0, limit] range from scratch, which is exactly what the
    plain count_sieving_primes() path (and every version before this one) does on every call.

    Cache is a single small JSON file per floor: {"l_final": <largest L counted to>,
    "count": <pi(that L)>}. Three cases:
      - no cache yet for this floor              -> full count(0, limit), cache it
      - limit == cached l_final                   -> return the cached count, NO primesieve
                                                       call at all
      - limit >  cached l_final                   -> cached count + count_range(cached_l, limit),
                                                       cache the new (limit, count) pair
      - limit <  cached l_final (rare -- exploring
        a SMALLER limit than before on this floor) -> falls back to a full recount, since the
                                                       cache only ever stores a running total up
                                                       to its largest L, not a queryable prefix
                                                       count at arbitrary smaller points.

    use_known_pi_seed (default False): when the "no cache yet"/"smaller limit" cases above
    would otherwise fall back to a full count_sieving_primes(0, limit) recount, try
    _seed_from_known_pi(limit) first -- if it finds a known pi(10^n) at or below limit (see
    KNOWN_PI_10N above), seed from THAT instead of 0 and only actually count the sliver from
    there up to limit via count_sieving_primes_range(). Turns what would otherwise be the
    single most expensive call this function ever makes into the same cheap shape as every
    later "incremental" call. When a seed is used, the cache also records which one
    (seeded_from: {power_of_ten, value, source}) so the number's provenance stays visible to
    anyone inspecting the cache file directly.

    Returns (count, mode) where mode is one of "cold" / "cache_hit" / "incremental" / "shrink"
    / "seeded" -- purely informational, used by main_batch_scanner()'s timing print so a
    benchmark run can show which path was actually taken.
    """
    import json
    cache_dir = os.path.join(portal_folder, f"10p{base_power}")
    cache_path = os.path.join(cache_dir, SIEVING_PRIMES_COUNT_CACHE_FILENAME)

    cached = None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
    except (OSError, ValueError):
        cached = None

    seeded_from = None
    if cached is None or "l_final" not in cached or "count" not in cached:
        seed = _seed_from_known_pi(limit) if use_known_pi_seed else None
        if seed is not None:
            seed_l, seed_count, source = seed
            count = seed_count + count_sieving_primes_range(seed_l, limit)
            mode = "seeded"
            seeded_from = {"power_of_ten": len(str(seed_l)) - 1, "value": seed_count,
                            "source": source}
        else:
            count = count_sieving_primes(limit)
            mode = "cold"
    elif limit == cached["l_final"]:
        return cached["count"], "cache_hit"
    elif limit > cached["l_final"]:
        count = cached["count"] + count_sieving_primes_range(cached["l_final"], limit)
        mode = "incremental"
    else:
        seed = _seed_from_known_pi(limit) if use_known_pi_seed else None
        if seed is not None:
            seed_l, seed_count, source = seed
            count = seed_count + count_sieving_primes_range(seed_l, limit)
            mode = "seeded"
            seeded_from = {"power_of_ten": len(str(seed_l)) - 1, "value": seed_count,
                            "source": source}
        else:
            count = count_sieving_primes(limit)
            mode = "shrink"

    try:
        os.makedirs(cache_dir, exist_ok=True)
        cache_entry = {"l_final": limit, "count": count}
        if seeded_from is not None:
            cache_entry["seeded_from"] = seeded_from
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_entry, f)
    except OSError as e:
        print(f"[!] WARNING: could not write sieving-primes-count cache ({e})")

    return count, mode
