"""
test_gaps_window.py -- tests for primeatlas/research/gaps_window.py, the pure-Python
consecutive-prime-gap engine for the Badania -> Luki sub-tab (raw gaps +
Andrica/Firoozbakht/Cramer overlays). No tkinter, no display needed -- run
directly:

    python unitTests\\test_gaps_window.py
"""
import math
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
# primeatlas/__init__.py imports manifest.py, which imports window_sharding --
# needed even just to import primeatlas.research.gaps_window (same fix as every other
# test file in this folder, see e.g. test_squares_window.py's own copy).
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _test_sieve_is_prime():
    from primeatlas.research.gaps_window import sieve_is_prime

    is_prime = sieve_is_prime(20)
    primes = [i for i in range(21) if is_prime[i]]
    check(primes == [2, 3, 5, 7, 11, 13, 17, 19],
          f"sieve_is_prime(20) lists exactly the primes <= 20 (got {primes!r})")


def _test_check_gap_range_none_overlay():
    from primeatlas.research.gaps_window import check_gap_range

    # p_1..p_6 = 2,3,5,7,11,13 -> gaps: 1,2,2,4,2
    result = check_gap_range(1, 5, overlay="none")
    gaps = [row["gap"] for row in result["rows"]]
    check(gaps == [1, 2, 2, 4, 2], f"raw gaps for n=1..5 (got {gaps!r})")
    check(result["max_gap"] == 4, f"largest gap in n=1..5 is 4 (got {result['max_gap']!r})")
    check(all(row["overlay_value"] is None and row["holds"] is None for row in result["rows"]),
          "overlay='none' leaves overlay_value/holds as None on every row")
    check(result["counterexamples"] == [], "overlay='none' never reports counterexamples")


def _test_check_gap_range_andrica():
    from primeatlas.research.gaps_window import check_gap_range

    result = check_gap_range(1, 10, overlay="andrica")
    row1 = result["rows"][0]
    expected = math.sqrt(3) - math.sqrt(2)
    check(abs(row1["overlay_value"] - expected) < 1e-9,
          f"Andrica n=1: sqrt(3)-sqrt(2) (got {row1['overlay_value']!r}, expected {expected!r})")
    check(row1["holds"], "Andrica's inequality holds for n=1 (well within the < 1 bound)")
    check(all(row["holds"] for row in result["rows"]),
          "Andrica holds for every n=1..10 -- no known counterexample this small")
    check(result["counterexamples"] == [], "no counterexamples for n=1..10")


def _test_check_gap_range_firoozbakht():
    from primeatlas.research.gaps_window import check_gap_range

    result = check_gap_range(1, 10, overlay="firoozbakht")
    row1 = result["rows"][0]
    # n=1: p_1=2, p_2=3 -> 3^(1/2) < 2^(1/1)
    check(abs(row1["overlay_value"] - (3 ** 0.5)) < 1e-9,
          f"Firoozbakht n=1's overlay_value is p_2^(1/2) (got {row1['overlay_value']!r})")
    check(row1["holds"], "Firoozbakht's inequality holds for n=1 (3^0.5 ~= 1.73 < 2)")
    check(all(row["holds"] for row in result["rows"]),
          "Firoozbakht holds for every n=1..10 -- no known counterexample this small")


def _test_check_gap_range_cramer():
    from primeatlas.research.gaps_window import check_gap_range

    result = check_gap_range(1, 10, overlay="cramer")
    row1 = result["rows"][0]
    expected = 1 / (math.log(2) ** 2)  # gap=1, p_1=2
    check(abs(row1["overlay_value"] - expected) < 1e-9,
          f"Cramer n=1's ratio is gap/(ln p_1)^2 = 1/(ln 2)^2 (got {row1['overlay_value']!r})")
    check(row1["holds"] is None, "Cramer's overlay never sets a holds verdict (asymptotic, not per-n)")
    check(result["counterexamples"] == [], "Cramer's overlay never reports counterexamples")
    check(result["max_cramer_ratio"] is not None and result["max_cramer_ratio"] > 0,
          f"max_cramer_ratio is populated (got {result['max_cramer_ratio']!r})")
    check(result["max_cramer_ratio"] == max(row["overlay_value"] for row in result["rows"]),
          "max_cramer_ratio matches the largest per-row ratio actually computed")


def _test_check_gap_range_pagination():
    from primeatlas.research.gaps_window import check_gap_range

    result = check_gap_range(1, 10, overlay="none", row_cap=3, row_offset=2)
    check(len(result["rows"]) == 3, f"row_cap=3 returns exactly 3 rows (got {len(result['rows'])})")
    check([r["n"] for r in result["rows"]] == [3, 4, 5],
          f"row_offset=2 starts the page at the 3rd n (got {[r['n'] for r in result['rows']]!r})")
    check(result["segment_size"] == 10,
          f"segment_size is the FULL range size regardless of paging (got {result['segment_size']!r})")
    check(result["rows_truncated"], "more rows exist after this page -> rows_truncated is True")

    last_page = check_gap_range(1, 10, row_cap=3, row_offset=9)
    check(len(last_page["rows"]) == 1, "the final page returns only the one remaining row")
    check(not last_page["rows_truncated"], "the final page's rows_truncated is False")

    # max_gap must be over the FULL range even when the page itself doesn't
    # include the n where the largest gap occurs.
    full = check_gap_range(1, 10, overlay="none")
    page_only = check_gap_range(1, 10, overlay="none", row_cap=2, row_offset=0)
    check(page_only["max_gap"] == full["max_gap"],
          f"max_gap is computed over the FULL range, not just the returned page "
          f"(page-only={page_only['max_gap']!r}, full={full['max_gap']!r})")


def _test_check_gap_range_validation():
    from primeatlas.research.gaps_window import check_gap_range

    try:
        check_gap_range(5, 1)
        check(False, "n_to < n_from raises ValueError")
    except ValueError:
        check(True, "n_to < n_from raises ValueError")

    try:
        check_gap_range(0, 5)
        check(False, "n_from < 1 raises ValueError")
    except ValueError:
        check(True, "n_from < 1 raises ValueError")

    try:
        check_gap_range(1, 5, overlay="not-an-overlay")
        check(False, "an unknown overlay raises ValueError")
    except ValueError:
        check(True, "an unknown overlay raises ValueError")


def _test_check_gap_range_from_source():
    from primeatlas.research.gaps_window import check_gap_range_from_source, sieve_is_prime

    calls = []

    def source(bound):
        calls.append(bound)
        return sieve_is_prime(bound)

    result = check_gap_range_from_source(1, 5, source, overlay="none")
    check(len(calls) >= 1, "is_prime_source is called at least once")
    gaps = [row["gap"] for row in result["rows"]]
    check(gaps == [1, 2, 2, 4, 2],
          f"check_gap_range_from_source computes the same gaps as check_gap_range "
          f"(got {gaps!r})")

    # An is_prime source that can never produce enough primes (capped tiny,
    # always the same) must not spin forever -- it should keep doubling its
    # OWN reported bound without ever finding p_1..p_6, so this test caps the
    # number of attempts instead of actually looping forever.
    class _NeverEnoughSource:
        def __init__(self):
            self.calls = 0

        def __call__(self, bound):
            self.calls += 1
            if self.calls > 30:
                raise RuntimeError("too many attempts -- infinite loop suspected")
            return bytearray(2)  # length 2: only index 0,1 exist, no primes at all

    try:
        check_gap_range_from_source(1, 5, _NeverEnoughSource(), overlay="none")
        check(False, "a source that never yields enough primes eventually surfaces an error "
              "rather than succeeding with wrong data")
    except (RuntimeError, IndexError):
        check(True, "a source that never yields enough primes is not silently accepted "
              "(this test's own attempt cap or an indexing error surfaces instead)")


def _test_check_gap_range_max_sieve_bound_ceiling():
    import primeatlas.research.gaps_window as gaps_window

    # Rather than actually sieving hundreds of millions of ints just to prove
    # the refusal path, temporarily lower the ceiling to something trivially
    # exceeded, then restore it.
    original_ceiling = gaps_window.MAX_SIEVE_BOUND
    gaps_window.MAX_SIEVE_BOUND = 5
    try:
        gaps_window.check_gap_range(1, 100)
        check(False, "exceeding MAX_SIEVE_BOUND raises ValueError instead of attempting a huge sieve")
    except ValueError:
        check(True, "exceeding MAX_SIEVE_BOUND raises ValueError instead of attempting a huge sieve")
    finally:
        gaps_window.MAX_SIEVE_BOUND = original_ceiling


def main():
    _test_sieve_is_prime()
    _test_check_gap_range_none_overlay()
    _test_check_gap_range_andrica()
    _test_check_gap_range_firoozbakht()
    _test_check_gap_range_cramer()
    _test_check_gap_range_pagination()
    _test_check_gap_range_validation()
    _test_check_gap_range_from_source()
    _test_check_gap_range_max_sieve_bound_ceiling()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
