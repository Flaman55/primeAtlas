"""
test_ring_resonance.py -- resonance events of the ring visualization
(ring_resonance.py): events in a range against a brute-force reference, the vectorized
scan matching it, the scan staying fast at large N, and the log lines / log panel text.

Usage: python unitTests\\test_ring_resonance.py
"""
import time
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))
# primeatlas/__init__.py itself imports .manifest, which does a bare
# `import window_sharding` (see storage.py's own module docstring for why
# prime_sieve_v1.py/window_sharding.py live outside this package) -- so the
# prime_sieve dir must be on sys.path before `from primeatlas import ...`
# below, exactly like unitTests/test_storage.py's own setup.

import numpy as np

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _brute_resonance_at(primes_arr, n):
    """Independent, unvectorized reimplementation of the SAME formula
    resonance_events_in_range is supposed to compute in bulk (mirrors
    SieveModel.js's getStepState per-n resonance test directly, not the bulk
    marking-pass algorithm) -- used ONLY as a cross-check in the test below,
    deliberately NOT sharing any code with the module under test. If this and
    resonance_events_in_range disagree, at least one
    of the two independent derivations has a bug worth finding, rather than
    trusting either one blind."""
    factors = []
    primorial = 1
    max_resonance = 0
    still_growing = True
    for p in primes_arr:
        p = int(p)
        if p > n:
            break
        if n % p == 0:
            factors.append(p)
        if still_growing:
            primorial *= p
            if primorial > n:
                still_growing = False
            else:
                max_resonance += 1
    active = max_resonance > 0 and len(factors) >= max_resonance
    return active, factors


def _test_resonance_events_in_range():
    from primeatlas.visualization.rings.ring.ring_resonance import resonance_events_in_range

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47], dtype=np.int64)
    from_n, to_n = 0, 60

    events = resonance_events_in_range(primes, from_n, to_n)
    event_by_n = {e["n"]: e["factors"] for e in events}

    brute_ns = []
    mismatches = []
    for n in range(from_n, to_n + 1):
        active, factors = _brute_resonance_at(primes, n)
        if active:
            brute_ns.append(n)
            if n not in event_by_n:
                mismatches.append(f"n={n}: brute says active, resonance_events_in_range missed it")
            elif sorted(event_by_n[n]) != sorted(factors):
                mismatches.append(f"n={n}: factor mismatch, brute={sorted(factors)} vs ported={sorted(event_by_n[n])}")
    for n in event_by_n:
        if n not in brute_ns:
            mismatches.append(f"n={n}: resonance_events_in_range flagged it, brute says not active")

    check(not mismatches,
          "resonance_events_in_range matches an independent per-n brute-force reimplementation over n in [0,60]"
          + ("" if not mismatches else f" -- {mismatches[:3]}"))
    check(len(brute_ns) > 0,
          "sanity: this prime list + range actually contains at least one resonance event (a vacuous pass would be a weak test)")

    check(resonance_events_in_range(primes, 10, 5) == [],
          "resonance_events_in_range returns [] when to_n < from_n")
    # n=0 with to_n=0: the smallest active prime (2) already exceeds to_n, so
    # no threshold is ever reached (max_resonance stays 0 for every n in
    # range) -- the honest "not enough range to have a resonance yet" case,
    # not a crash or an off-by-one.
    check(resonance_events_in_range(primes, 0, 0) == [],
          "resonance_events_in_range(primes, 0, 0) correctly finds no event (to_n=0 is below the smallest active prime)")

    # A floor-25-scale range-mode tick has active primes ~10**25 and (for a
    # long while) to_n only ~10**21 -- the smallest active prime already
    # exceeds to_n, so no resonance is possible ANYWHERE in the span; this
    # must return [] WITHOUT ever attempting the old
    # `np.zeros(to_n - from_n + 1, ...)` allocation, which raised
    # "ValueError: Maximum allowed dimension exceeded" at this magnitude.
    huge_primes = np.array([12345678901234567890000023, 12345678901234567890000127], dtype=object)
    huge_to_n = 1234567890123456789009  # ~10**21, four orders of magnitude below the primes above
    check(resonance_events_in_range(huge_primes, 1, huge_to_n) == [],
          "resonance_events_in_range at real storage-floor-25 scale (huge primes, a merely-large "
          "to_n well below them) returns [] instead of crashing on the old dense array allocation")

    # A second, independent guard for any combination that reaches a huge
    # span even with small-enough primes to pass the check above: a hard
    # cap on the span itself, past which the marking-pass algorithm could
    # never finish regardless of memory.
    from primeatlas.visualization.rings.ring.ring_resonance import _RESONANCE_SCAN_MAX_SIZE
    small_primes = np.array([2, 3, 5], dtype=np.int64)
    huge_span_to_n = _RESONANCE_SCAN_MAX_SIZE + 1_000_000
    check(resonance_events_in_range(small_primes, 0, huge_span_to_n) == [],
          f"resonance_events_in_range returns [] for a span past _RESONANCE_SCAN_MAX_SIZE "
          f"({_RESONANCE_SCAN_MAX_SIZE:,}), even with small, otherwise-relevant primes, instead "
          f"of attempting an infeasible allocation")


def _brute_events(primes, from_n, to_n):
    out = []
    for n in range(from_n, to_n + 1):
        active, factors = _brute_resonance_at(primes, n)
        if active:
            out.append({"n": n, "factors": factors})
    return out


def _small_primes_upto(limit):
    sieve = np.ones(limit + 1, dtype=bool)
    sieve[:2] = False
    for i in range(2, int(limit ** 0.5) + 1):
        if sieve[i]:
            sieve[i * i::i] = False
    return np.nonzero(sieve)[0].astype(np.int64)


def _test_resonance_scan_vectorized_matches_brute():
    """The scan behind the ring-viz scrub-jump freeze (known bug #1: 4.4 s at
    N=20M, blocking the GLFW loop so Esc/close could not be processed) must stay
    exactly equal to the per-n brute force across every shape of input the
    renderer can pass: an offset from_n, from_n=0 (every p divides 0), active
    sets not starting at 2 (sliding window), object-dtype arrays, primes above
    to_n, and a scan split across several internal chunks."""
    from primeatlas.visualization.rings.ring import ring_resonance as rg

    primes = _small_primes_upto(3000)
    cases = [
        ("full [1,3000]", primes, 1, 3000),
        ("from_n=0", primes, 0, 400),
        ("offset from_n", primes, 1237, 2999),
        ("single n", primes, 2310, 2310),
        ("window not starting at 2", primes[primes >= 11], 1, 3000),
        ("primes above to_n", primes, 1, 500),
        ("object dtype", np.array([int(x) for x in primes[:200]], dtype=object), 1, 1500),
    ]
    for label, arr, lo, hi in cases:
        got = rg.resonance_events_in_range(arr, lo, hi)
        want = _brute_events(arr, lo, hi)
        check(got == want, f"resonance scan == brute force ({label}, {len(want)} events)"
              + ("" if got == want else f" -- first diff near {[e['n'] for e in got][:5]} vs {[e['n'] for e in want][:5]}"))

    saved = rg._RESONANCE_SCAN_CHUNK
    rg._RESONANCE_SCAN_CHUNK = 97
    try:
        got = rg.resonance_events_in_range(primes, 1, 3000)
    finally:
        rg._RESONANCE_SCAN_CHUNK = saved
    check(got == _brute_events(primes, 1, 3000),
          "resonance scan split into many small chunks still equals brute force")


def _test_resonance_scan_large_n_is_fast():
    """Known bug #1's own measurement: N=5M took 1.09 s, 20M 4.38 s -- all inside the
    single-threaded GLFW loop. A 10M full backfill must now finish well under a second
    (generous bound, the vectorized scan takes ~0.25 s here)."""
    from primeatlas.visualization.rings.ring.ring_resonance import resonance_events_in_range
    primes = _small_primes_upto(10_000_000)
    t0 = time.perf_counter()
    events = resonance_events_in_range(primes, 1, 10_000_000)
    elapsed = time.perf_counter() - t0
    check(len(events) > 0 and elapsed < 1.0,
          f"resonance scan over [1, 10M] with {len(primes):,} active primes takes {elapsed:.2f}s (< 1.0s)")


def _test_resonance_log_lines():
    from primeatlas.visualization.rings.ring.ring_resonance import (
        resonance_events_in_range, resonance_log_lines)

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47], dtype=np.int64)
    from_n, to_n = 0, 60

    lines = resonance_log_lines(primes, from_n, to_n)
    events = resonance_events_in_range(primes, from_n, to_n)
    expected = [f"{e['n']} = {' × '.join(str(f) for f in e['factors'])}" for e in events]
    check(lines == expected,
          "resonance_log_lines formats every resonance_events_in_range event as 'N = f1 × f2 × ...', "
          "same order, same content, no independent formatting drift")
    check(len(lines) > 0,
          "sanity: this range actually produces at least one resonance log line")
    check(all(" × " in line or " = " in line for line in lines),
          "every resonance_log_lines entry contains the 'N = ...' separator")

    check(resonance_log_lines(primes, 10, 5) == [],
          "resonance_log_lines returns [] for an empty (to_n < from_n) range, same as resonance_events_in_range")


def _test_format_log_panel_text():
    from primeatlas.visualization.rings.ring.ring_resonance import (
        LOG_PANEL_TRUNCATE_THRESHOLD, format_log_panel_text)

    count, text = format_log_panel_text([])
    check(count == 0 and text == "-",
          "format_log_panel_text([]) -> (0, '-') for an empty list")

    small = [2, 3, 5, 7, 11]
    count, text = format_log_panel_text(small)
    check(count == 5 and text == "2, 3, 5, 7, 11",
          f"format_log_panel_text of a short list is fully joined by ', ' with no truncation (got {text!r})")

    check(LOG_PANEL_TRUNCATE_THRESHOLD == 50,
          "LOG_PANEL_TRUNCATE_THRESHOLD mirrors StructuralSieveApp.js's own threshold (50)")

    exact = list(range(LOG_PANEL_TRUNCATE_THRESHOLD))
    count, text = format_log_panel_text(exact)
    check(count == LOG_PANEL_TRUNCATE_THRESHOLD and "more" not in text,
          "a list with EXACTLY threshold items is shown in full, not truncated (JS: only ABOVE threshold collapses)")

    over = list(range(LOG_PANEL_TRUNCATE_THRESHOLD + 7))
    count, text = format_log_panel_text(over)
    check(count == LOG_PANEL_TRUNCATE_THRESHOLD + 7,
          "format_log_panel_text reports the TRUE total count even when the text itself is truncated")
    check(text.endswith("(+7 more)"),
          f"a list 7 over threshold is truncated with a trailing '(+7 more)' marker (got {text!r})")
    check(text.startswith("0, 1, 2"),
          "the truncated text still starts with the list's own first items, in order")
    check(len(text.split(" (+")[0].split(", ")) == LOG_PANEL_TRUNCATE_THRESHOLD,
          "the truncated text shows exactly `threshold` items before the '(+K more)' marker")

    # Custom threshold, so the test doesn't only ever exercise the default 50.
    count, text = format_log_panel_text([1, 2, 3, 4, 5], threshold=3)
    check(text == "1, 2, 3 (+2 more)",
          f"a custom threshold=3 truncates at 3 items (got {text!r})")


def main():
    _test_resonance_events_in_range()
    _test_resonance_scan_vectorized_matches_brute()
    _test_resonance_scan_large_n_is_fast()
    _test_resonance_log_lines()
    _test_format_log_panel_text()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
