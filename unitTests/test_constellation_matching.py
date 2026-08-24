"""
test_constellation_matching.py -- characterization tests for match_patterns_vectorized(),
the vectorized numpy core that decides whether a k-tuple pattern from PATTERN_CATALOG is
actually present at a given candidate value. This is the single function every hit
constellation_finder_v1.py ever records ultimately comes from -- a wrong bitmask here
(wrong offset, OR instead of AND across a pattern's offsets, an off-by-one in the
np.searchsorted/clip trick used to emulate "is this value present in the set") would
silently corrupt or drop hits across every floor and every pattern at once, so this file
pins its exact behavior down directly, independent of any file I/O, checkpointing, or
floor-boundary logic (those are covered separately in
test_constellation_finder_engine.py).

Deliberately uses tiny, hand-picked integers (not real primes) as candidates -- the
function only ever checks arithmetic offset relationships between values already handed
to it; it has no opinion on primality, so a synthetic "candidate=100, local_set={100,102}"
is exactly as valid a test of the k=2 (twin) pattern as two real primes 10 apart would be,
and far easier to reason about by hand.

Every check() states the specific expected vs. actual value, per Artur's explicit request
for this suite ("wyłapały i wyświetliły co faktycznie powoduje błąd" -- catch it AND show
what actually caused it).

Usage (Windows, real Python -- pure function + numpy, no Tk/display dependency at all):
    python unitTests\\test_constellation_matching.py

Usage (this sandbox headless -- no display needed for THIS file, but kept consistent with
the rest of the suite):
    python3 unitTests/test_constellation_matching.py
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.join(_REPO_ROOT, "constellation"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def main():
    from constellation_finder_v1 import match_patterns_vectorized

    K2 = {"k": 2, "id": 1, "offsets": [0, 2]}
    K3 = {"k": 3, "id": 1, "offsets": [0, 2, 6]}

    # === basic single hit ===========================================================
    results = match_patterns_vectorized([11], {11, 13}, [K2])
    check(results.get((2, 1)) == [[11, 13]],
          f"a genuine k=2 hit (11, 13 both present) is found with full absolute values "
          f"(got {results!r}, expected {{(2, 1): [[11, 13]]}})")

    # === missing partner -> no hit, not a false positive ============================
    results = match_patterns_vectorized([11], {11}, [K2])
    check(results == {},
          f"candidate 11 with NO 13 in local_set must NOT be reported as a k=2 hit "
          f"(got {results!r}, expected {{}})")

    # === multi-offset pattern: ALL offsets must be present (AND, not OR) ============
    # k=3 needs candidate, candidate+2, AND candidate+6. Only offset 2 satisfied here
    # (missing +6) -- a bug that turned the offset-AND into an OR would wrongly report
    # this as a hit.
    results = match_patterns_vectorized([5], {5, 7}, [K3])
    check(results == {},
          f"a k=3 candidate satisfying only ONE of its two non-zero offsets (missing "
          f"+6) must NOT be reported as a hit -- offsets are ANDed, not ORed "
          f"(got {results!r}, expected {{}})")
    results = match_patterns_vectorized([5], {5, 7, 11}, [K3])
    check(results.get((3, 1)) == [[5, 7, 11]],
          f"a k=3 candidate satisfying BOTH non-zero offsets (+2 and +6) is reported "
          f"with all three absolute values (got {results!r}, "
          f"expected {{(3, 1): [[5, 7, 11]]}})")

    # === two independent patterns checked in the same call =========================
    # candidate 5 satisfies k=2 (5,7) AND k=3 (5,7,11) simultaneously -- both must be
    # reported, neither should suppress the other (shared offset masks, per the
    # function's own docstring, must not leak between patterns).
    results = match_patterns_vectorized([5], {5, 7, 11}, [K2, K3])
    check(results.get((2, 1)) == [[5, 7]] and results.get((3, 1)) == [[5, 7, 11]],
          f"a candidate matching two DIFFERENT catalog patterns at once must report BOTH "
          f"independently, sharing precomputed offset masks correctly rather than one "
          f"clobbering the other (got {results!r})")

    # === multiple candidates in one call: each is checked independently ============
    # 5 is a real k=2 hit; 100 is not (101 absent). Only 5 should be reported.
    results = match_patterns_vectorized([5, 100], {5, 7, 100}, [K2])
    check(results.get((2, 1)) == [[5, 7]],
          f"with two candidates, only the one that actually satisfies the pattern is "
          f"reported -- the other must not leak a false hit through shared numpy "
          f"vectorized arrays (got {results!r}, expected {{(2, 1): [[5, 7]]}})")

    # === large candidate values (near numpy int64 range used for floor >= 19) ======
    # match_patterns_vectorized deliberately computes on LOCAL offsets relative to
    # min(candidates), not absolute values, specifically so this stays correct even at
    # magnitudes numpy int64 can hold but where absolute arithmetic would need to be
    # watched carefully. Exercise a candidate near floor 19's own magnitude directly.
    big = 10 ** 19 + 7
    results = match_patterns_vectorized([big], {big, big + 2}, [K2])
    check(results.get((2, 1)) == [[big, big + 2]],
          f"a k=2 hit at a floor-19-scale magnitude ({big}) is still found correctly "
          f"via the LOCAL-offset computation (got {results!r})")

    # === empty inputs are a safe no-op, not an exception ============================
    check(match_patterns_vectorized([], {1, 2, 3}, [K2]) == {},
          "empty candidates list returns {} without raising")
    check(match_patterns_vectorized([5], set(), [K2]) == {},
          "empty local_set returns {} without raising")

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
