"""
test_pi_count_notice.py -- primeatlas/generation/pi_count_notice.py: when counting pi(L)
(the compute_sieving_primes_count / use_known_pi_seed diagnostic) has to start from zero on
the floor, and about how long that takes.

A. l_final(hi) is the engines' isqrt(hi) + 1 (floor 18: 10^9 -> 1000000001, 10^10 ->
   1000000005, 10^11 -> 1000000050); primes_between() follows pi(x): li-based counts within
   0.2 % of pi(10^9) and pi(10^12), a 10^6 gap near 10^12 ~ 10^6 / ln(10^12).
B. read_cache: per floor folder of the storage; no file, a broken file or one without both
   keys -> None; another storage or another floor sees its own.
C. counts_from_zero: no cache, or a run whose first batch lies below the cached L -> the
   engine counts pi(L) from zero; a cache at or below the run's first L -> it does not.
D. estimate: the primes counted (from 0, or from the largest known 10^n with the seed) at
   SECONDS_PER_PRIME.
E. notice_needed: counting off -> never; on -> exactly when the engine counts from zero,
   whatever the floor (a low floor too); a cache covering the run or below it -> none.
F. format_duration: seconds, minutes, hours.

Usage:
    python unitTests/test_pi_count_notice.py
"""
import json
import math
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

from primeatlas.generation import pi_count_notice as pcn  # noqa: E402

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _cache(portal, floor, l_final, count):
    folder = os.path.join(portal, f"10p{floor}")
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, pcn.CACHE_FILENAME), "w", encoding="utf-8") as f:
        json.dump({"l_final": l_final, "count": count}, f)


def part_a():
    check(pcn.l_final(10 ** 18 + 10 ** 9) == 1000000001, "floor 18, 10^9: L 1000000001")
    check(pcn.l_final(10 ** 18 + 10 ** 10) == 1000000005, "floor 18, 10^10: L 1000000005")
    check(pcn.l_final(10 ** 18 + 10 ** 11) == 1000000050, "floor 18, 10^11: L 1000000050")
    got = pcn.primes_between(0, 10 ** 9)
    check(abs(got - 50847534) / 50847534 < 0.002, f"pi(10^9) within 0.2 % ({got:.0f})")
    got = pcn.primes_between(0, 10 ** 12)
    check(abs(got - 37607912018) / 37607912018 < 0.002, f"pi(10^12) within 0.2 % ({got:.0f})")
    got = pcn.primes_between(10 ** 12, 10 ** 12 + 10 ** 6)
    want = 10 ** 6 / math.log(10 ** 12)
    check(abs(got - want) / want < 0.01, f"10^6 gap near 10^12 ~ 10^6/ln ({got:.0f})")
    check(pcn.primes_between(5000, 5000) == 0 and pcn.primes_between(9000, 5000) == 0,
          "an empty or reversed span holds no primes")


def part_b(tmp):
    portal = os.path.join(tmp, "b")
    check(pcn.read_cache(portal, 20) is None, "no storage folder: None")
    _cache(portal, 20, 10 ** 10 + 1, 455052512)
    check(pcn.read_cache(portal, 20) == (10 ** 10 + 1, 455052512), "the floor's own cache")
    check(pcn.read_cache(portal, 21) is None, "another floor: None")
    check(pcn.read_cache(os.path.join(tmp, "other"), 20) is None, "another storage: None")
    with open(os.path.join(portal, "10p20", pcn.CACHE_FILENAME), "w", encoding="utf-8") as f:
        f.write("{broken")
    check(pcn.read_cache(portal, 20) is None, "a broken file: None")
    with open(os.path.join(portal, "10p20", pcn.CACHE_FILENAME), "w", encoding="utf-8") as f:
        json.dump({"l_final": 5}, f)
    check(pcn.read_cache(portal, 20) is None, "a file without count: None")


def part_c():
    L = 10 ** 13
    check(pcn.counts_from_zero(None, L), "no cache: the engine counts from zero")
    check(not pcn.counts_from_zero((L, 1), L), "cache at the run's first L: no")
    check(not pcn.counts_from_zero((L, 1), L + 10 ** 9), "run above the cache: no")
    check(pcn.counts_from_zero((L + 1, 1), L),
          "first batch below the cache: the engine counts from zero again")


def part_d(tmp):
    portal = os.path.join(tmp, "d")
    os.makedirs(portal)
    lo27 = 10 ** 27
    est = pcn.estimate(portal, 27, lo27, lo27 + 10 ** 9, lo27 + 10 ** 7, False)
    want = 1.0523e12 * pcn.SECONDS_PER_PRIME
    check(est["from_zero"] and abs(est["seconds"] - want) / want < 0.01,
          f"floor 27, no cache: pi(L) primes at SECONDS_PER_PRIME ({est['seconds']:.0f} s)")
    seeded = pcn.estimate(portal, 27, lo27, lo27 + 10 ** 9, lo27 + 10 ** 7, True)
    check(seeded["from_zero"] and seeded["seconds"] < est["seconds"] * 0.8,
          f"the seed shortens the count ({seeded['seconds']:.0f} s)")


def part_e(tmp):
    portal = os.path.join(tmp, "e")
    os.makedirs(portal)
    lo27 = 10 ** 27

    def notice(on, floor, lo, width=10 ** 9):
        lo = lo if lo else 10 ** floor
        return pcn.notice_needed(on, pcn.estimate(portal, floor, lo, lo + width,
                                                  lo + 10 ** 7, False))

    check(not notice(False, 27, lo27), "counting off: no notice")
    check(notice(True, 27, lo27), "counting on, no cache: notice")
    check(notice(True, 12, None), "counting on, no cache on a low floor: notice too")
    _cache(portal, 27, pcn.l_final(lo27 + 10 ** 9), 1)
    check(not notice(True, 27, lo27), "cache covering the run: no notice")
    check(not notice(True, 27, lo27 + 10 ** 26),
          "run far above the cache: no notice (the floor's pi is known)")
    _cache(portal, 27, pcn.l_final(lo27 + 10 ** 26), 1)
    check(notice(True, 27, lo27), "run below the cache: counts from zero, notice")
    check(not notice(False, 27, lo27), "counting off below the cache: no notice")


def part_f():
    check(pcn.format_duration(42.4) == "~42 s", "seconds")
    check(pcn.format_duration(0.2) == "~1 s", "under a second: ~1 s")
    check(pcn.format_duration(522) == "~9 min", "minutes")
    check(pcn.format_duration(2135.7) == "~36 min", "minutes, rounded")
    check(pcn.format_duration(8280) == "~2.3 h", "hours")


def main():
    tmp = tempfile.mkdtemp(prefix="primeatlas_pi_notice_test_")
    try:
        part_a()
        part_b(tmp)
        part_c()
        part_d(tmp)
        part_e(tmp)
        part_f()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if failures:
        print(f"\n{len(failures)} FAILED")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
