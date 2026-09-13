"""
test_pi_approx_window.py -- tests for primeatlas/pi_approx_window.py, the
pure-Python pi(x)-approximation-accuracy engine for the Badania ->
Przyblizenia pi(x) sub-tab (li(x), Riemann's R(x), against the real count).
No tkinter, no display needed -- run directly:

    python unitTests\\test_pi_approx_window.py

Deliberately avoids asserting against memorized reference constants for
li(x)/R(x) (error-prone to recall precisely) -- instead cross-checks each
function against an INDEPENDENT method computed right here in the test
(a finite-difference derivative for li(x), a real sieve-based pi(x) count
plus the well-known qualitative fact that R(x) approximates pi(x) better
than li(x) does) so a wrong implementation would actually be caught.
"""
import math
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
# primeatlas/__init__.py imports manifest.py, which imports window_sharding --
# needed even just to import primeatlas.pi_approx_window (same fix as every
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
    from primeatlas.pi_approx_window import sieve_is_prime

    is_prime = sieve_is_prime(20)
    primes = [i for i in range(21) if is_prime[i]]
    check(primes == [2, 3, 5, 7, 11, 13, 17, 19],
          f"sieve_is_prime(20) lists exactly the primes <= 20 (got {primes!r})")


def _test_zeta_known_closed_forms():
    from primeatlas.pi_approx_window import _zeta

    check(abs(_zeta(2) - (math.pi ** 2 / 6)) < 1e-6,
          f"zeta(2) matches the closed form pi^2/6 (got {_zeta(2)!r}, "
          f"expected {math.pi ** 2 / 6!r})")
    check(abs(_zeta(4) - (math.pi ** 4 / 90)) < 1e-6,
          f"zeta(4) matches the closed form pi^4/90 (got {_zeta(4)!r}, "
          f"expected {math.pi ** 4 / 90!r})")
    check(_zeta(10) > 1.0 and _zeta(10) < 1.001,
          f"zeta(10) is just barely above 1 (large s -> zeta(s) -> 1) "
          f"(got {_zeta(10)!r})")


def _test_li_monotonic_and_derivative():
    from primeatlas.pi_approx_window import li

    check(li(10) < li(100) < li(1000) < li(10000),
          "li(x) is strictly increasing across a wide range of x")

    # li'(x) = 1/ln(x) by the Fundamental Theorem of Calculus (li is defined
    # as an integral of 1/ln(t)) -- verify the IMPLEMENTATION's own output
    # matches this via a central finite difference, independent of any
    # memorized reference value for li(x) itself.
    x = 1000.0
    h = 1.0
    numeric_derivative = (li(x + h) - li(x - h)) / (2 * h)
    expected_derivative = 1.0 / math.log(x)
    check(abs(numeric_derivative - expected_derivative) < 1e-4,
          f"li(x)'s finite-difference derivative at x=1000 matches 1/ln(x) "
          f"(got {numeric_derivative!r}, expected {expected_derivative!r})")

    try:
        li(1)
        check(False, "li(x) raises ValueError for x <= 1")
    except ValueError:
        check(True, "li(x) raises ValueError for x <= 1")


def _test_riemann_r_monotonic_and_close_to_li():
    from primeatlas.pi_approx_window import li, riemann_r

    check(riemann_r(10) < riemann_r(100) < riemann_r(1000) < riemann_r(10000),
          "R(x) is strictly increasing across a wide range of x")
    # R(x) and li(x) should be in the same ballpark (same order of magnitude,
    # both approximating pi(x)) -- not identical, but nowhere near as far
    # apart as, say, li(x) vs x itself.
    for x in (1000, 100000, 10000000):
        check(0.5 < riemann_r(x) / li(x) < 1.5,
              f"R({x}) and li({x}) are within the same rough ballpark of each "
              f"other (got R/li={riemann_r(x) / li(x)!r})")

    try:
        riemann_r(1)
        check(False, "riemann_r(x) raises ValueError for x <= 1")
    except ValueError:
        check(True, "riemann_r(x) raises ValueError for x <= 1")


def _test_check_pi_approx_range_r_beats_li():
    from primeatlas.pi_approx_window import check_pi_approx_range

    # The well-known, NOT-a-conjecture fact this whole tab exists to show:
    # Riemann's R(x) is a substantially better approximation to the real
    # pi(x) than li(x) is, for ordinary computational ranges. Verify this
    # against REAL sieve-computed pi(x) rather than any memorized numbers.
    result = check_pi_approx_range(1000, 1000000, 999000)
    check(len(result["rows"]) == 2, f"x_from=1000, x_to=1000000, step=999000 "
          f"produces exactly 2 checkpoints (1000 and 1000000) "
          f"(got {len(result['rows'])})")
    for row in result["rows"]:
        check(abs(row["r_error"]) < abs(row["li_error"]),
              f"at x={row['x']}, R(x)'s error ({row['r_error']!r}) is smaller in "
              f"magnitude than li(x)'s error ({row['li_error']!r}) -- R(x) is the "
              f"known-better approximation")
        check(row["li_error"] > 0,
              f"li(x) overshoots the real pi(x) at x={row['x']} (li_error={row['li_error']!r}) "
              f"-- true for every x this small, well below Skewes' number")


def _test_check_pi_approx_range_checkpoints_and_endpoint():
    from primeatlas.pi_approx_window import check_pi_approx_range

    # step doesn't evenly divide (x_to - x_from) -- x_to must still show up
    # as its own checkpoint, not get silently rounded away.
    result = check_pi_approx_range(10, 100, 30)
    xs = [row["x"] for row in result["rows"]]
    check(xs == [10, 40, 70, 100],
          f"checkpoints are x_from, x_from+step, ..., always ending at x_to itself "
          f"(got {xs!r})")

    row_x10 = result["rows"][0]
    check(row_x10["pi_x"] == 4, f"pi(10) = 4 (primes 2,3,5,7) (got {row_x10['pi_x']!r})")
    row_x100 = result["rows"][-1]
    check(row_x100["pi_x"] == 25, f"pi(100) = 25 (got {row_x100['pi_x']!r})")


def _test_check_pi_approx_range_pagination():
    from primeatlas.pi_approx_window import check_pi_approx_range

    result = check_pi_approx_range(10, 1000, 10, row_cap=3, row_offset=2)
    check(len(result["rows"]) == 3, f"row_cap=3 returns exactly 3 rows (got {len(result['rows'])})")
    check(result["segment_size"] > 3,
          f"segment_size is the FULL checkpoint count regardless of paging "
          f"(got {result['segment_size']!r})")
    check(result["rows_truncated"], "more rows exist after this page -> rows_truncated is True")

    # max_li_error/max_r_error must be over the FULL range even when the
    # displayed page doesn't include the checkpoint with the largest error.
    full = check_pi_approx_range(10, 1000, 10)
    page_only = check_pi_approx_range(10, 1000, 10, row_cap=2, row_offset=0)
    check(page_only["max_li_error"] == full["max_li_error"],
          f"max_li_error is computed over the FULL range, not just the returned page "
          f"(page-only={page_only['max_li_error']!r}, full={full['max_li_error']!r})")


def _test_check_pi_approx_range_validation():
    from primeatlas.pi_approx_window import check_pi_approx_range

    try:
        check_pi_approx_range(100, 10, 1)
        check(False, "x_to < x_from raises ValueError")
    except ValueError:
        check(True, "x_to < x_from raises ValueError")

    try:
        check_pi_approx_range(1, 100, 1)
        check(False, "x_from < 2 raises ValueError")
    except ValueError:
        check(True, "x_from < 2 raises ValueError")

    try:
        check_pi_approx_range(10, 100, 0)
        check(False, "step < 1 raises ValueError")
    except ValueError:
        check(True, "step < 1 raises ValueError")


def _test_check_pi_approx_range_from_source():
    from primeatlas.pi_approx_window import check_pi_approx_range_from_source, sieve_is_prime

    calls = []

    def source(limit):
        calls.append(limit)
        return sieve_is_prime(limit)

    result = check_pi_approx_range_from_source(10, 100, 30, source)
    check(calls == [100], f"is_prime_source is called exactly once, with x_to itself "
          f"(got {calls!r})")
    check([row["x"] for row in result["rows"]] == [10, 40, 70, 100],
          "check_pi_approx_range_from_source computes the same checkpoints as "
          "check_pi_approx_range")

    try:
        check_pi_approx_range_from_source(10, 100, 30, lambda limit: sieve_is_prime(50))
        check(False, "an is_prime array too short for x_to raises ValueError")
    except ValueError:
        check(True, "an is_prime array too short for x_to raises ValueError")


def _test_check_pi_approx_range_with_pi_func():
    from primeatlas.pi_approx_window import check_pi_approx_range_with_pi_func

    calls = []

    def pi_func(checkpoints):
        calls.append(list(checkpoints))
        # A fake "exact" pi(x) source -- real pi(10)=4, pi(40)=12, pi(70)=19,
        # pi(100)=25 (same known small values test_check_pi_approx_range_
        # checkpoints_and_endpoint already relies on), but this test only
        # cares that check_pi_approx_range_with_pi_func wires whatever
        # pi_func returns straight through, unchanged, into each row.
        return [1000 + x for x in checkpoints]

    result = check_pi_approx_range_with_pi_func(10, 100, 30, pi_func)
    check(calls == [[10, 40, 70, 100]],
          f"pi_func is called exactly once, with ALL checkpoints in one batch "
          f"(got {calls!r})")
    check([row["pi_x"] for row in result["rows"]] == [1010, 1040, 1070, 1100],
          f"each row's pi_x is exactly what pi_func returned for that checkpoint "
          f"(got {[row['pi_x'] for row in result['rows']]!r})")
    check("max_li_error" in result and "max_r_error" in result,
          "the result still carries li(x)/R(x) error stats, computed from pi_func's own count")

    # A pi_func that returns the wrong number of values (a batch call that
    # silently dropped or duplicated an entry) must be refused, not
    # zip()-truncated into a wrong-looking but silent result.
    try:
        check_pi_approx_range_with_pi_func(10, 100, 30, lambda checkpoints: [1, 2])
        check(False, "pi_func returning the wrong number of values raises ValueError")
    except ValueError:
        check(True, "pi_func returning the wrong number of values raises ValueError")

    # No MAX_SIEVE_BOUND ceiling on this path -- a huge x_to must reach
    # pi_func directly rather than being refused up front.
    huge_calls = []

    def huge_pi_func(checkpoints):
        huge_calls.append(list(checkpoints))
        return [0 for _ in checkpoints]

    check_pi_approx_range_with_pi_func(10 ** 12, 10 ** 12, 1, huge_pi_func)
    check(huge_calls == [[10 ** 12]],
          f"check_pi_approx_range_with_pi_func never applies check_pi_approx_range's own "
          f"fresh-sieve ceiling, even for x far past MAX_SIEVE_BOUND (got {huge_calls!r})")


def _test_check_pi_approx_range_max_sieve_bound_ceiling():
    import primeatlas.pi_approx_window as pi_approx_window

    original_ceiling = pi_approx_window.MAX_SIEVE_BOUND
    pi_approx_window.MAX_SIEVE_BOUND = 50
    try:
        pi_approx_window.check_pi_approx_range(10, 1000, 10)
        check(False, "exceeding MAX_SIEVE_BOUND raises ValueError instead of attempting a huge sieve")
    except ValueError:
        check(True, "exceeding MAX_SIEVE_BOUND raises ValueError instead of attempting a huge sieve")
    finally:
        pi_approx_window.MAX_SIEVE_BOUND = original_ceiling


def main():
    _test_sieve_is_prime()
    _test_zeta_known_closed_forms()
    _test_li_monotonic_and_derivative()
    _test_riemann_r_monotonic_and_close_to_li()
    _test_check_pi_approx_range_r_beats_li()
    _test_check_pi_approx_range_checkpoints_and_endpoint()
    _test_check_pi_approx_range_pagination()
    _test_check_pi_approx_range_validation()
    _test_check_pi_approx_range_from_source()
    _test_check_pi_approx_range_with_pi_func()
    _test_check_pi_approx_range_max_sieve_bound_ceiling()

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
