"""
test_pi_seed.py -- unit tests for the "seed pi(L_final) from a known Wikipedia value" feature
(Artur's idea, 2026-08-27): instead of count_sieving_primes_cached()'s cold/shrink paths always
recounting pi(L_final) from 0 via primesieve, optionally seed from the largest known pi(10^n)
at or below L_final (KNOWN_PI_10N, prime_sieve_v4_1.py) and only count the remaining sliver via
count_sieving_primes_range(). See that file's own module comment above KNOWN_PI_10N for the
full motivation and source citation (Wikipedia's Prime-counting function page).

Covers:
  1. _seed_from_known_pi() -- pure function, no ctypes/.so dependency, so it's testable in any
     environment (this sandbox has no libprimesieve.so installed -- confirmed the real
     count_sieving_primes()/count_sieving_primes_range() calls raise OSError here).
  2. count_sieving_primes_cached() wiring -- use_known_pi_seed=True actually takes the
     "seeded" path on a cold floor (no cache yet) and a "shrink" floor (smaller limit than
     cached), while use_known_pi_seed=False (the default) is completely unaffected (byte-for-
     byte the old "cold"/"shrink" behavior). count_sieving_primes/count_sieving_primes_range
     are monkeypatched at module level for this since the real ones need libprimesieve.
  3. The cache file records seeded_from (power_of_ten/value/source) only when a seed was
     actually used -- Artur's own transparency requirement for this feature.
  4. build_wsl_logged_command() (generation.py) -- use_known_pi_seed=True adds
     PRIMEATLAS_USE_KNOWN_PI_SEED=1 to the env prefix; False (default) leaves it out entirely,
     unchanged from before this feature existed.

Usage:
    python3 unitTests/test_pi_seed.py
"""
import json
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def test_seed_from_known_pi():
    import prime_sieve_v4_1 as psv

    # Below the smallest known power of ten (10^1 = 10) -- no seed applies at all.
    check(psv._seed_from_known_pi(9) is None,
          "_seed_from_known_pi(9) is None (below 10**1, nothing to seed from)")

    # Exactly on a known power of ten -- seeds from itself.
    seed = psv._seed_from_known_pi(10 ** 5)
    check(seed == (10 ** 5, psv.KNOWN_PI_10N[5], psv.KNOWN_PI_SOURCE_URL),
          f"_seed_from_known_pi(10**5) seeds from 10**5 itself exactly (got {seed!r})")

    # Between two known powers of ten -- seeds from the LARGER (closer) one, not the smaller.
    limit = 3 * 10 ** 15  # between 10**15 and 10**16
    seed = psv._seed_from_known_pi(limit)
    check(seed == (10 ** 15, psv.KNOWN_PI_10N[15], psv.KNOWN_PI_SOURCE_URL),
          f"_seed_from_known_pi(3e15) seeds from the largest 10**n <= limit, i.e. 10**15, "
          f"not a smaller one (got {seed!r})")

    # Above the largest known power of ten (10**29) -- still seeds from the largest known
    # entry rather than returning None (a floor this deep is unlikely but should degrade
    # gracefully, seeding from the best available anchor instead of refusing to help at all).
    huge = 10 ** 40
    seed = psv._seed_from_known_pi(huge)
    check(seed == (10 ** 29, psv.KNOWN_PI_10N[29], psv.KNOWN_PI_SOURCE_URL),
          f"_seed_from_known_pi(10**40) falls back to the largest known entry, 10**29 "
          f"(got seed[0]={seed[0]!r} if not None)")

    check(len(psv.KNOWN_PI_10N) == 29 and set(psv.KNOWN_PI_10N) == set(range(1, 30)),
          f"KNOWN_PI_10N has exactly one entry per n=1..29 (got {sorted(psv.KNOWN_PI_10N)})")
    # Spot-check a couple of values against the Wikipedia table transcribed into the module
    # comment, to catch a gross transcription error (not a substitute for re-checking the
    # full table by eye, but catches e.g. an accidentally-dropped digit).
    check(psv.KNOWN_PI_10N[1] == 4, f"pi(10^1) == 4 (got {psv.KNOWN_PI_10N[1]})")
    check(psv.KNOWN_PI_10N[10] == 455052511,
          f"pi(10^10) == 455,052,511 (got {psv.KNOWN_PI_10N[10]})")
    check(psv.KNOWN_PI_10N[29] == 1520698109714272166094258063,
          f"pi(10^29) == 1,520,698,109,714,272,166,094,258,063 (got {psv.KNOWN_PI_10N[29]})")


def test_count_sieving_primes_cached_seeding(tmp_portal):
    import prime_sieve_v4_1 as psv

    # Monkeypatch the two ctypes-backed functions -- this sandbox has no libprimesieve.so, and
    # regardless, this test cares about the CACHING/SEEDING LOGIC, not primesieve's own
    # counting correctness (that's the underlying C library's job, not this feature's).
    original_full = psv.count_sieving_primes
    original_range = psv.count_sieving_primes_range
    range_calls = []

    def fake_full_count(limit):
        # A trivially "correct-shaped" stand-in: pretend pi(limit) == limit // 10 (not a real
        # prime count, just a deterministic function of limit so seeded vs. non-seeded totals
        # can be compared against each other, which is all this test needs).
        return limit // 10

    def fake_range_count(start, stop):
        range_calls.append((start, stop))
        return fake_full_count(stop) - fake_full_count(start)

    psv.count_sieving_primes = fake_full_count
    psv.count_sieving_primes_range = fake_range_count
    try:
        base_power = 30
        cache_path = os.path.join(tmp_portal, f"10p{base_power}",
                                   psv.SIEVING_PRIMES_COUNT_CACHE_FILENAME)

        # --- cold floor, use_known_pi_seed=False: unchanged "cold" behavior -----------------
        limit_a = 3 * 10 ** 15
        count, mode = psv.count_sieving_primes_cached(tmp_portal, base_power, limit_a,
                                                        use_known_pi_seed=False)
        check(mode == "cold", f"use_known_pi_seed=False on an empty cache takes the 'cold' "
                               f"path (got mode={mode!r})")
        check(count == fake_full_count(limit_a),
              f"cold path counts the FULL range from 0 (got count={count}, "
              f"expected {fake_full_count(limit_a)})")
        with open(cache_path, encoding="utf-8") as f:
            cache_after_cold = json.load(f)
        check("seeded_from" not in cache_after_cold,
              f"cache written by the unseeded cold path has no seeded_from key "
              f"(got keys={list(cache_after_cold.keys())})")

        # Reset to an empty floor for the next case (delete the cache file this just wrote).
        os.remove(cache_path)
        range_calls.clear()

        # --- cold floor, use_known_pi_seed=True: takes the 'seeded' path --------------------
        count, mode = psv.count_sieving_primes_cached(tmp_portal, base_power, limit_a,
                                                        use_known_pi_seed=True)
        check(mode == "seeded", f"use_known_pi_seed=True on an empty cache takes the "
                                 f"'seeded' path (got mode={mode!r})")
        # Expected = the REAL known seed value (KNOWN_PI_10N[15], not derived from
        # fake_full_count -- it's a genuine Wikipedia figure) plus the fake sliver-range count
        # from the seed point to limit_a. This is the exact formula count_sieving_primes_cached
        # itself uses -- NOT fake_full_count(limit_a), which would only match if the fake
        # stand-in happened to agree with the real pi(10**15) at the seed point (it doesn't,
        # by design -- fake_full_count is a synthetic placeholder, KNOWN_PI_10N is real data).
        # NOTE: compute the expected sliver directly from fake_full_count, NOT by calling
        # fake_range_count() here -- that function is the same one monkeypatched in as
        # count_sieving_primes_range and logs to range_calls as a side effect, so calling it
        # again here would double-count entries in that list.
        expected_seeded = psv.KNOWN_PI_10N[15] + (fake_full_count(limit_a) - fake_full_count(10 ** 15))
        check(count == expected_seeded,
              f"seeded count == known seed value + counted sliver (got count={count}, "
              f"expected {expected_seeded})")
        check(range_calls == [(10 ** 15, limit_a)],
              f"seeded path only ever counts the SLIVER from the seed point to limit, via "
              f"count_sieving_primes_range -- not the full [0, limit] range "
              f"(got range_calls={range_calls})")
        with open(cache_path, encoding="utf-8") as f:
            cache_after_seed = json.load(f)
        check(cache_after_seed.get("seeded_from") == {
                  "power_of_ten": 15, "value": psv.KNOWN_PI_10N[15],
                  "source": psv.KNOWN_PI_SOURCE_URL},
              f"cache written by the seeded path records power_of_ten/value/source for "
              f"transparency (got {cache_after_seed.get('seeded_from')!r})")

        # --- shrink case (limit < cached l_final), use_known_pi_seed=True: also seeds -------
        range_calls.clear()
        smaller_limit = 10 ** 15 + 5  # still > 10**15 seed point, but < limit_a (cached l_final)
        count, mode = psv.count_sieving_primes_cached(tmp_portal, base_power, smaller_limit,
                                                        use_known_pi_seed=True)
        check(mode == "seeded",
              f"a smaller limit than the cached l_final ('shrink' case) ALSO takes the "
              f"seeded path when use_known_pi_seed=True, instead of a full recount from 0 "
              f"(got mode={mode!r})")
        expected_shrink = psv.KNOWN_PI_10N[15] + (fake_full_count(smaller_limit) - fake_full_count(10 ** 15))
        check(count == expected_shrink,
              f"seeded shrink-case count == known seed value + counted sliver "
              f"(got count={count}, expected {expected_shrink})")

        # --- cache_hit / incremental paths are completely untouched by this feature ---------
        count, mode = psv.count_sieving_primes_cached(tmp_portal, base_power, smaller_limit,
                                                        use_known_pi_seed=True)
        check(mode == "cache_hit",
              f"asking for the exact same limit again is a cache_hit regardless of "
              f"use_known_pi_seed (got mode={mode!r})")
        bigger_limit = smaller_limit + 1000
        range_calls.clear()
        count, mode = psv.count_sieving_primes_cached(tmp_portal, base_power, bigger_limit,
                                                        use_known_pi_seed=True)
        check(mode == "incremental",
              f"a larger limit than the cached one is 'incremental' regardless of "
              f"use_known_pi_seed -- seeding only applies to cold/shrink (got mode={mode!r})")
        check(range_calls == [(smaller_limit, bigger_limit)],
              f"incremental path counts only from the PREVIOUS cached l_final, not from the "
              f"original Wikipedia seed point (got {range_calls})")
    finally:
        psv.count_sieving_primes = original_full
        psv.count_sieving_primes_range = original_range


def test_build_wsl_logged_command_env_var():
    import primeatlas.generation as gen

    argv = ["python3", "orchestrator_v3.py", "20", "5"]
    with tempfile.TemporaryDirectory() as tmp:
        log_path = os.path.join(tmp, "run.log")
        exit_path = os.path.join(tmp, "run.exit")
        portal = os.path.join(tmp, "portal")

        cmd_off = gen.build_wsl_logged_command(argv, log_path, exit_path, portal)
        bash_cmd_off = cmd_off[-1]
        check("PRIMEATLAS_USE_KNOWN_PI_SEED" not in bash_cmd_off,
              "build_wsl_logged_command's default (use_known_pi_seed omitted) does not set "
              "PRIMEATLAS_USE_KNOWN_PI_SEED at all -- unchanged from before this feature")

        cmd_on = gen.build_wsl_logged_command(argv, log_path, exit_path, portal,
                                               use_known_pi_seed=True)
        bash_cmd_on = cmd_on[-1]
        check("PRIMEATLAS_USE_KNOWN_PI_SEED=1 " in bash_cmd_on,
              f"use_known_pi_seed=True adds PRIMEATLAS_USE_KNOWN_PI_SEED=1 to the env prefix "
              f"(got bash -c string: {bash_cmd_on!r})")
        check("CONSTELLATION_PORTAL_DIR=" in bash_cmd_on,
              "CONSTELLATION_PORTAL_DIR is still set alongside the new var, unaffected")

        cmd_explicit_off = gen.build_wsl_logged_command(argv, log_path, exit_path, portal,
                                                          use_known_pi_seed=False)
        check(cmd_explicit_off == cmd_off,
              "explicitly passing use_known_pi_seed=False produces byte-identical output to "
              "omitting it entirely")


def main():
    test_seed_from_known_pi()

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_pi_seed_test_")
    try:
        test_count_sieving_primes_cached_seeding(tmp_portal)
    finally:
        shutil.rmtree(tmp_portal, ignore_errors=True)

    test_build_wsl_logged_command_env_var()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
