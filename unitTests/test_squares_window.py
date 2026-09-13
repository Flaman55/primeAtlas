"""
test_squares_window.py -- tests for primeatlas/squares_window.py, the pure-Python
interval-contains-enough-primes engine for the Badania -> Przedzialy kwadratowe
sub-tab (Legendre/Oppermann/Brocard presets + custom formula). No tkinter, no
display needed -- run directly:

    python unitTests\\test_squares_window.py
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
# primeatlas/__init__.py imports manifest.py, which imports window_sharding --
# needed even just to import primeatlas.squares_window (same fix as every
# other test file in this folder, see e.g. test_ring_geometry.py's own copy).
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _test_sieve_is_prime():
    from primeatlas.squares_window import sieve_is_prime

    is_prime = sieve_is_prime(20)
    primes = [i for i in range(21) if is_prime[i]]
    check(primes == [2, 3, 5, 7, 11, 13, 17, 19],
          f"sieve_is_prime(20) lists exactly the primes <= 20 (got {primes!r})")
    check(len(sieve_is_prime(1)) == 2, "sieve_is_prime(1) returns a length-2 array, no crash")
    check(len(sieve_is_prime(0)) == 1, "sieve_is_prime(0) returns a length-1 array, no crash")


def _test_first_n_primes():
    from primeatlas.squares_window import first_n_primes

    check(first_n_primes(1) == [2], "first_n_primes(1) == [2]")
    check(first_n_primes(5) == [2, 3, 5, 7, 11],
          f"first_n_primes(5) matches the first five primes (got {first_n_primes(5)!r})")
    check(first_n_primes(10) == [2, 3, 5, 7, 11, 13, 17, 19, 23, 29],
          f"first_n_primes(10) matches the textbook first-ten-primes list "
          f"(got {first_n_primes(10)!r})")
    # A count comfortably past _nth_prime_upper_bound's small-n hardcoded table,
    # forcing the real Rosser-bound-then-verify path -- p_100 = 541 (well known).
    p100 = first_n_primes(100)
    check(len(p100) == 100 and p100[-1] == 541,
          f"first_n_primes(100)'s last entry is the 100th prime, 541 (got {p100[-1]!r})")


def _test_preset_bounds():
    from primeatlas.squares_window import preset_bounds

    check(preset_bounds("legendre", 3) == [(9, 16)],
          f"Legendre bounds for n=3 are [3^2, 4^2] = [9, 16] (got {preset_bounds('legendre', 3)!r})")
    check(preset_bounds("oppermann", 3) == [(9, 12), (12, 16)],
          f"Oppermann bounds for n=3 split [9,16] at n^2+n=12 into two halves "
          f"(got {preset_bounds('oppermann', 3)!r})")
    # Brocard n=1 -> (p_1, p_2) = (2, 3) -> [4, 9].
    check(preset_bounds("brocard", 1) == [(4, 9)],
          f"Brocard bounds for n=1 are [p_1^2, p_2^2] = [4, 9] (got {preset_bounds('brocard', 1)!r})")
    # Brocard n=2 -> (p_2, p_3) = (3, 5) -> [9, 25] -- the traditional starting
    # case of the conjecture (excludes p=2).
    check(preset_bounds("brocard", 2) == [(9, 25)],
          f"Brocard bounds for n=2 are [p_2^2, p_3^2] = [9, 25] "
          f"(got {preset_bounds('brocard', 2)!r})")

    try:
        preset_bounds("not-a-preset", 1)
        check(False, "preset_bounds raises ValueError on an unknown preset")
    except ValueError:
        check(True, "preset_bounds raises ValueError on an unknown preset")


def _test_check_interval_range_legendre():
    from primeatlas.squares_window import check_interval_range

    result = check_interval_range("legendre", 1, 5)
    check(result["covered"], "Legendre holds (no counterexamples) for n=1..5 "
          f"(got counterexamples={result['counterexamples']!r})")
    check(result["required_count"] == 1,
          f"Legendre's default required_count is 1 (got {result['required_count']!r})")
    check(len(result["rows"]) == 5, f"5 rows returned for n=1..5 with no row_cap (got {len(result['rows'])})")
    row3 = next(r for r in result["rows"] if r["n"] == 3)
    check(row3["intervals"] == [{"a": 9, "b": 16, "count": 2, "primes": [11, 13], "covered": True}],
          f"n=3 row: interval [9,16] contains primes 11 and 13 (got {row3['intervals']!r})")


def _test_check_interval_range_oppermann_two_subintervals():
    from primeatlas.squares_window import check_interval_range

    result = check_interval_range("oppermann", 3, 3)
    row = result["rows"][0]
    check(len(row["intervals"]) == 2,
          f"Oppermann n=3 has exactly two independently-checked subintervals "
          f"(got {len(row['intervals'])})")
    check(row["intervals"][0]["a"] == 9 and row["intervals"][0]["b"] == 12,
          "Oppermann's first half is [n^2, n^2+n]")
    check(row["intervals"][1]["a"] == 12 and row["intervals"][1]["b"] == 16,
          "Oppermann's second half is [n^2+n, (n+1)^2]")


def _test_check_interval_range_brocard_required_count_four():
    from primeatlas.squares_window import check_interval_range

    result = check_interval_range("brocard", 2, 2)
    check(result["required_count"] == 4,
          f"Brocard's default required_count is 4, not 1 (got {result['required_count']!r})")
    row = result["rows"][0]
    interval = row["intervals"][0]
    check(interval["a"] == 9 and interval["b"] == 25,
          f"Brocard n=2 checks [9, 25] (got a={interval['a']!r}, b={interval['b']!r})")
    check(interval["primes"] == [11, 13, 17, 19, 23],
          f"[9,25] contains exactly five primes: 11,13,17,19,23 (got {interval['primes']!r})")
    check(interval["count"] == 5 and interval["covered"],
          f"5 primes >= required_count 4, so this row is covered (got count={interval['count']!r}, "
          f"covered={interval['covered']!r})")


def _test_check_interval_range_counterexample_detection():
    from primeatlas.squares_window import check_interval_range

    # A required_count deliberately higher than any of these small intervals can
    # satisfy, so every row is a manufactured counterexample -- exercises the
    # "covered=False" / non-empty counterexamples path end to end.
    result = check_interval_range("legendre", 1, 3, required_count=100)
    check(not result["covered"], "an impossible required_count makes the whole range uncovered")
    check(result["counterexamples"] == [1, 2, 3],
          f"every n in range is listed as a counterexample (got {result['counterexamples']!r})")
    check(all(not row["covered"] for row in result["rows"]),
          "every individual row is also marked not covered")


def _test_check_interval_range_custom_bounds_fn():
    from primeatlas.squares_window import check_interval_range

    # Custom: a(n)=10n, b(n)=10n+1 -- a razor-thin two-integer window, only
    # "covered" when 10n or 10n+1 happens to be prime.
    def bounds_fn(n):
        return [(10 * n, 10 * n + 1)]

    result = check_interval_range("custom", 1, 5, required_count=1, bounds_fn=bounds_fn)
    # n=1 -> [10,11]: 11 is prime -> covered. n=2 -> [20,21]: neither prime -> not covered.
    row1 = next(r for r in result["rows"] if r["n"] == 1)
    row2 = next(r for r in result["rows"] if r["n"] == 2)
    check(row1["covered"], "custom bounds_fn: [10,11] contains the prime 11 -> covered")
    check(not row2["covered"], "custom bounds_fn: [20,21] contains no prime -> not covered")
    check(2 in result["counterexamples"],
          f"n=2 shows up as a counterexample (got {result['counterexamples']!r})")

    try:
        check_interval_range("custom", 1, 5)
        check(False, "preset='custom' without bounds_fn raises ValueError")
    except ValueError:
        check(True, "preset='custom' without bounds_fn raises ValueError")

    try:
        check_interval_range("custom", 1, 5, bounds_fn=bounds_fn)
        check(False, "preset='custom' without an explicit required_count raises ValueError")
    except ValueError:
        check(True, "preset='custom' without an explicit required_count raises ValueError")


def _test_check_interval_range_pagination():
    from primeatlas.squares_window import check_interval_range

    result = check_interval_range("legendre", 1, 10, row_cap=3, row_offset=2)
    check(len(result["rows"]) == 3, f"row_cap=3 returns exactly 3 rows (got {len(result['rows'])})")
    check([r["n"] for r in result["rows"]] == [3, 4, 5],
          f"row_offset=2 starts the page at the 3rd n (n=3), i.e. skips n=1,2 "
          f"(got {[r['n'] for r in result['rows']]!r})")
    check(result["segment_size"] == 10, f"segment_size is the FULL range size regardless of paging (got {result['segment_size']!r})")
    check(result["rows_truncated"], "more rows exist after this page -> rows_truncated is True")

    last_page = check_interval_range("legendre", 1, 10, row_cap=3, row_offset=9)
    check(len(last_page["rows"]) == 1, "the final page returns only the one remaining row")
    check(not last_page["rows_truncated"], "the final page's rows_truncated is False")

    # Rows OUTSIDE the returned page must not have materialized a full prime
    # list (see the module's own memory-conscious "primes: None" contract).
    full = check_interval_range("legendre", 1, 10, row_cap=3, row_offset=0)
    check(full["rows"][0]["intervals"][0]["primes"] is not None,
          "a row INSIDE the returned page has its full primes list materialized")


def _test_check_interval_range_validation():
    from primeatlas.squares_window import check_interval_range

    try:
        check_interval_range("legendre", 5, 1)
        check(False, "n_to < n_from raises ValueError")
    except ValueError:
        check(True, "n_to < n_from raises ValueError")

    try:
        check_interval_range("legendre", 0, 5)
        check(False, "n_from < 1 raises ValueError")
    except ValueError:
        check(True, "n_from < 1 raises ValueError")

    try:
        check_interval_range("not-a-preset", 1, 5)
        check(False, "an unknown preset raises ValueError")
    except ValueError:
        check(True, "an unknown preset raises ValueError")

    try:
        check_interval_range("legendre", 1, 5, required_count=0)
        check(False, "required_count < 1 raises ValueError")
    except ValueError:
        check(True, "required_count < 1 raises ValueError")

    try:
        check_interval_range("legendre", 1, 5, bounds_fn=lambda n: [(n, n)])
        check(False, "bounds_fn is refused for a non-custom preset")
    except ValueError:
        check(True, "bounds_fn is refused for a non-custom preset")


def _test_check_interval_range_max_sieve_bound_ceiling():
    import primeatlas.squares_window as squares_window

    # Rather than actually sieving hundreds of millions of ints just to prove
    # the refusal path (slow, memory-heavy for a unit test), temporarily lower
    # the ceiling to something check_interval_range's own Legendre bounds
    # trivially exceed, then restore it -- exercises the exact same code path
    # a real oversized request would hit.
    original_ceiling = squares_window.MAX_SIEVE_BOUND
    squares_window.MAX_SIEVE_BOUND = 50
    try:
        squares_window.check_interval_range("legendre", 1, 10)
        check(False, "exceeding MAX_SIEVE_BOUND raises ValueError instead of attempting a huge sieve")
    except ValueError:
        check(True, "exceeding MAX_SIEVE_BOUND raises ValueError instead of attempting a huge sieve")
    finally:
        squares_window.MAX_SIEVE_BOUND = original_ceiling


def main():
    _test_sieve_is_prime()
    _test_first_n_primes()
    _test_preset_bounds()
    _test_check_interval_range_legendre()
    _test_check_interval_range_oppermann_two_subintervals()
    _test_check_interval_range_brocard_required_count_four()
    _test_check_interval_range_counterexample_detection()
    _test_check_interval_range_custom_bounds_fn()
    _test_check_interval_range_pagination()
    _test_check_interval_range_validation()
    _test_check_interval_range_max_sieve_bound_ceiling()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
