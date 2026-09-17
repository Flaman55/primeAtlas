"""
test_polynomials_window.py -- tests for primeatlas/research/polynomials_window.py, the
pure-Python prime-among-polynomial-values engine for the Badania -> Wielomiany
pierwszorodne sub-tab (Landau/Euler presets + custom formula). No tkinter, no
display needed -- run directly:

    python unitTests\\test_polynomials_window.py
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
# primeatlas/__init__.py imports manifest.py, which imports window_sharding --
# needed even just to import primeatlas.research.polynomials_window (same fix as every
# other test file in this folder, see e.g. test_squares_window.py's own copy).
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _test_sieve_is_prime():
    from primeatlas.research.polynomials_window import sieve_is_prime

    is_prime = sieve_is_prime(20)
    primes = [i for i in range(21) if is_prime[i]]
    check(primes == [2, 3, 5, 7, 11, 13, 17, 19],
          f"sieve_is_prime(20) lists exactly the primes <= 20 (got {primes!r})")
    check(len(sieve_is_prime(1)) == 2, "sieve_is_prime(1) returns a length-2 array, no crash")
    check(len(sieve_is_prime(0)) == 1, "sieve_is_prime(0) returns a length-1 array, no crash")


def _test_preset_value():
    from primeatlas.research.polynomials_window import preset_value

    check(preset_value("landau", 0) == 1, "Landau f(0) = 0^2+1 = 1")
    check(preset_value("landau", 3) == 10, "Landau f(3) = 3^2+1 = 10")
    check(preset_value("euler", 0) == 41, "Euler f(0) = 0^2+0+41 = 41")
    check(preset_value("euler", 1) == 43, "Euler f(1) = 1^2+1+41 = 43")
    check(preset_value("euler", 40) == 1681, "Euler f(40) = 40^2+40+41 = 1681 (= 41^2, the first non-prime)")

    try:
        preset_value("not-a-preset", 1)
        check(False, "preset_value raises ValueError on an unknown preset")
    except ValueError:
        check(True, "preset_value raises ValueError on an unknown preset")


def _test_check_polynomial_range_euler_famous_run():
    from primeatlas.research.polynomials_window import check_polynomial_range

    # Euler's own famous property: f(n) = n^2+n+41 is prime for every n = 0..39.
    result = check_polynomial_range("euler", 0, 39)
    check(result["prime_count"] == 40,
          f"Euler's polynomial is prime for all 40 values n=0..39 "
          f"(got prime_count={result['prime_count']!r})")
    check(all(row["is_prime"] for row in result["rows"]),
          "every individual row n=0..39 is marked is_prime")

    # n=40 is the first counterexample: f(40) = 1681 = 41^2, not prime.
    result40 = check_polynomial_range("euler", 40, 40)
    row = result40["rows"][0]
    check(row["value"] == 1681, f"Euler f(40) = 1681 (got {row['value']!r})")
    check(not row["is_prime"], "Euler f(40) = 1681 = 41^2 is NOT prime")


def _test_check_polynomial_range_landau():
    from primeatlas.research.polynomials_window import check_polynomial_range

    result = check_polynomial_range("landau", 1, 5)
    values = {row["n"]: row["value"] for row in result["rows"]}
    check(values == {1: 2, 2: 5, 3: 10, 4: 17, 5: 26},
          f"Landau f(n)=n^2+1 for n=1..5 (got {values!r})")
    is_prime = {row["n"]: row["is_prime"] for row in result["rows"]}
    check(is_prime == {1: True, 2: True, 3: False, 4: True, 5: False},
          f"2,5,17 are prime; 10,26 are not (got {is_prime!r})")


def _test_check_polynomial_range_custom_poly_fn():
    from primeatlas.research.polynomials_window import check_polynomial_range

    # A trivial custom polynomial: f(n) = 2n+1 (odd numbers).
    result = check_polynomial_range("custom", 1, 10, poly_fn=lambda n: 2 * n + 1)
    check(result["prime_count"] == sum(
        1 for n in range(1, 11) if (2 * n + 1) in (3, 5, 7, 11, 13, 17, 19, 23)),
        f"custom poly_fn 2n+1 counted correctly (got prime_count={result['prime_count']!r})")

    try:
        check_polynomial_range("custom", 1, 5)
        check(False, "preset='custom' without poly_fn raises ValueError")
    except ValueError:
        check(True, "preset='custom' without poly_fn raises ValueError")

    try:
        check_polynomial_range("landau", 1, 5, poly_fn=lambda n: n)
        check(False, "poly_fn is refused for a non-custom preset")
    except ValueError:
        check(True, "poly_fn is refused for a non-custom preset")


def _test_check_polynomial_range_negative_value_rejected():
    from primeatlas.research.polynomials_window import check_polynomial_range

    try:
        check_polynomial_range("custom", 1, 5, poly_fn=lambda n: 3 - n)
        check(False, "a negative f(n) raises ValueError instead of crashing on indexing")
    except ValueError:
        check(True, "a negative f(n) raises ValueError instead of crashing on indexing")


def _test_check_polynomial_range_pagination():
    from primeatlas.research.polynomials_window import check_polynomial_range

    result = check_polynomial_range("landau", 1, 10, row_cap=3, row_offset=2)
    check(len(result["rows"]) == 3, f"row_cap=3 returns exactly 3 rows (got {len(result['rows'])})")
    check([r["n"] for r in result["rows"]] == [3, 4, 5],
          f"row_offset=2 starts the page at the 3rd n (n=3), i.e. skips n=1,2 "
          f"(got {[r['n'] for r in result['rows']]!r})")
    check(result["segment_size"] == 10,
          f"segment_size is the FULL range size regardless of paging (got {result['segment_size']!r})")
    check(result["rows_truncated"], "more rows exist after this page -> rows_truncated is True")
    check(result["prime_count"] == sum(
        1 for n in range(1, 11) if n * n + 1 in (2, 5, 17, 37, 101)),
        f"prime_count is over the FULL range, not just the returned page "
        f"(got {result['prime_count']!r})")

    last_page = check_polynomial_range("landau", 1, 10, row_cap=3, row_offset=9)
    check(len(last_page["rows"]) == 1, "the final page returns only the one remaining row")
    check(not last_page["rows_truncated"], "the final page's rows_truncated is False")


def _test_check_polynomial_range_validation():
    from primeatlas.research.polynomials_window import check_polynomial_range

    try:
        check_polynomial_range("landau", 5, 1)
        check(False, "n_to < n_from raises ValueError")
    except ValueError:
        check(True, "n_to < n_from raises ValueError")

    check(check_polynomial_range("euler", 0, 0)["rows"][0]["n"] == 0,
          "n_from=0 is accepted (Euler's own famous run starts there)")

    try:
        check_polynomial_range("landau", -1, 5)
        check(False, "n_from < 0 raises ValueError")
    except ValueError:
        check(True, "n_from < 0 raises ValueError")

    try:
        check_polynomial_range("not-a-preset", 1, 5)
        check(False, "an unknown preset raises ValueError")
    except ValueError:
        check(True, "an unknown preset raises ValueError")


def _test_check_polynomial_range_from_source():
    from primeatlas.research.polynomials_window import check_polynomial_range_from_source, sieve_is_prime

    calls = []

    def source(max_value):
        calls.append(max_value)
        return sieve_is_prime(max_value)

    result = check_polynomial_range_from_source("landau", 1, 5, source)
    check(calls == [26], f"is_prime_source is called exactly once, with the range's own "
          f"max_value (Landau n=5 -> f(5)=26) (got {calls!r})")
    check(result["prime_count"] == 3,
          f"Landau n=1..5 has 3 primes among its values via check_polynomial_range_from_source too "
          f"(got {result['prime_count']!r})")

    # An is_prime source that returns an array too short for the range's own
    # max_value must be refused, not silently truncated.
    try:
        check_polynomial_range_from_source("landau", 1, 5, lambda max_value: sieve_is_prime(10))
        check(False, "an is_prime array too short for max_value raises ValueError")
    except ValueError:
        check(True, "an is_prime array too short for max_value raises ValueError")

    # No MAX_SIEVE_BOUND ceiling here -- that check lives in check_polynomial_range's
    # OWN _source closure, not in the shared _from_source entry point. Uses a
    # lightweight fake "array" instead of an actual multi-hundred-MB bytearray.
    class _FakeHugeIsPrime:
        def __init__(self, length):
            self._length = length

        def __len__(self):
            return self._length

        def __getitem__(self, _i):
            return 0

    huge_calls = []

    def huge_source(max_value):
        huge_calls.append(max_value)
        return _FakeHugeIsPrime(max_value + 1)

    result = check_polynomial_range_from_source("landau", 100000, 100000, huge_source)
    check(huge_calls == [100000 * 100000 + 1],
          f"check_polynomial_range_from_source never applies check_polynomial_range's own "
          f"fresh-sieve ceiling, even for a max_value far past MAX_SIEVE_BOUND "
          f"(got {huge_calls!r})")
    check(not result["rows"][0]["is_prime"],
          "the fake source reports every index as not-prime")


def _test_check_polynomial_range_max_sieve_bound_ceiling():
    import primeatlas.research.polynomials_window as polynomials_window

    # Rather than actually sieving hundreds of millions of ints just to prove
    # the refusal path, temporarily lower the ceiling to something Euler's own
    # bounds trivially exceed, then restore it.
    original_ceiling = polynomials_window.MAX_SIEVE_BOUND
    polynomials_window.MAX_SIEVE_BOUND = 50
    try:
        polynomials_window.check_polynomial_range("euler", 0, 39)
        check(False, "exceeding MAX_SIEVE_BOUND raises ValueError instead of attempting a huge sieve")
    except ValueError:
        check(True, "exceeding MAX_SIEVE_BOUND raises ValueError instead of attempting a huge sieve")
    finally:
        polynomials_window.MAX_SIEVE_BOUND = original_ceiling


def main():
    _test_sieve_is_prime()
    _test_preset_value()
    _test_check_polynomial_range_euler_famous_run()
    _test_check_polynomial_range_landau()
    _test_check_polynomial_range_custom_poly_fn()
    _test_check_polynomial_range_negative_value_rejected()
    _test_check_polynomial_range_pagination()
    _test_check_polynomial_range_validation()
    _test_check_polynomial_range_from_source()
    _test_check_polynomial_range_max_sieve_bound_ceiling()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
