"""
test_ktuple_sieve_v2_provisional.py -- integration tests for ktuple_sieve_v2.py's
gap-safe hit routing, using REAL temporary storage and REAL PGS2 window files (via
prime_sieve_v1.write_prime_window), no mocking of either module.

Targets the field report this exists to fix: ktuple_sieve_v1.py
wrote every confirmed hit straight into the SAME cumulative hit file
constellation_finder_v1.py's own exhaustive scan uses, via the shared
_append_hits_deduped() -- which decides "already known" purely by comparing a new value
against the file's own LAST stored value. Since this module deliberately jumps around a
floor hunting for rare, deep hits far ahead of wherever the exhaustive scan currently is,
one of its own finds landing in the shared file poisons that file's dedup cursor against
every smaller, genuinely new hit the exhaustive scan finds afterwards -- confirmed on a
real floor-25 run, which reported new_hits=0/skipped_duplicates=~4000 on EVERY window for
over 90,000 windows straight.

Covers three layers:
  1. _exhaustive_frontier_value() -- the smallest value NOT yet covered by
     constellation_finder_v2's own gap-aware done-range checkpoint.
  2. _record_confirmed_hits()/_append_provisional_hits() -- the routing + dedup logic in
     isolation, with a synthetic frontier (no real sieve run needed).
  3. An end-to-end scan_locations() run against a REAL twin-prime pair, proving the
     routing decision is actually wired into the sieve's own hit-recording path, not
     just correct in isolation.

Usage (Windows, real Python -- pure Python, no Tk/display dependency):
    python unitTests\\test_ktuple_sieve_v2_provisional.py

Usage (this sandbox, headless):
    python3 unitTests/test_ktuple_sieve_v2_provisional.py
"""
import os
import shutil
import sys
import tempfile

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
    import prime_sieve_v1
    import window_sharding
    import constellation_finder_v2 as cf2
    import ktuple_sieve_v2 as ks2

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_ktuple_v2_provisional_test_")
    try:
        cf2.PORTAL_FOLDER = tmp_portal  # ks2's own _cf2 is the SAME module object (single
                                         # entry in sys.modules), so this is visible to it
                                         # too without any separate patching.

        def _write_source_window(floor, name, primes):
            source_dir = os.path.join(tmp_portal, f"10p{floor}", "source_primes")
            shard_dir = window_sharding.shard_dir(source_dir, 0)
            os.makedirs(shard_dir, exist_ok=True)
            path = os.path.join(shard_dir, name)
            prime_sieve_v1.write_prime_window(path, sorted(primes))
            return path

        def _read_hits(floor, k, variant_id):
            path = cf2.hit_file_path(floor, k, variant_id)
            if not os.path.exists(path):
                return []
            return prime_sieve_v1.read_prime_window(path)

        # =====================================================================
        # Layer 1: _exhaustive_frontier_value()
        # =====================================================================
        _write_source_window(80, "PRIME_WINDOW_A.bin", [1000, 1010])
        _write_source_window(80, "PRIME_WINDOW_B.bin", [2000, 2010])
        _write_source_window(80, "PRIME_WINDOW_C.bin", [3000, 3010])
        windows_80 = cf2.list_source_windows(80)
        names_80 = [w[0] for w in windows_80]

        check(ks2._exhaustive_frontier_value(80) == -1,
              "no checkpoint at all -> nothing is safe (frontier == -1)")

        cf2.write_done_ranges(80, names_80, {0})  # only A done
        check(ks2._exhaustive_frontier_value(80) == windows_80[1][2],
              f"only the first window (A) done -> frontier is B's own base_prime "
              f"(got {ks2._exhaustive_frontier_value(80)!r}, expected {windows_80[1][2]!r})")

        cf2.write_done_ranges(80, names_80, {0, 1, 2})  # all done
        check(ks2._exhaustive_frontier_value(80) == float("inf"),
              "the whole floor done -> frontier is +inf (everything is safe)")

        check(ks2._exhaustive_frontier_value(999) == -1,
              "a floor with no source windows at all -> frontier == -1 (nothing to be "
              "safe against, so nothing is treated as safe)")

        # =====================================================================
        # Layer 2: _record_confirmed_hits() / _append_provisional_hits() routing, in
        # isolation, with a hand-picked frontier (no real sieve run needed).
        # =====================================================================
        safe_count, ahead_count = ks2._record_confirmed_hits(81, 99, 1, [500, 1500], 1000)
        check((safe_count, ahead_count) == (1, 1),
              f"of [500, 1500] against frontier=1000, exactly one lands on each side "
              f"(got {(safe_count, ahead_count)!r})")
        check(_read_hits(81, 99, 1) == [500],
              f"the value BELOW the frontier (500) is appended to the normal shared "
              f"hit file (got {_read_hits(81, 99, 1)!r})")
        check(ks2.read_provisional_hits(81, 99, 1) == {1500},
              f"the value AT/BEYOND the frontier (1500) goes to the PROVISIONAL file "
              f"instead (got {ks2.read_provisional_hits(81, 99, 1)!r})")

        # Re-recording the SAME provisional value plus one new one: only the new one
        # should actually be written (dedup against what's already on disk).
        safe_count2, ahead_count2 = ks2._record_confirmed_hits(81, 99, 1, [1500, 1600], 1000)
        check(ahead_count2 == 1,
              f"re-submitting an already-known provisional value (1500) alongside a "
              f"genuinely new one (1600) only counts/writes the new one "
              f"(got ahead_count={ahead_count2!r})")
        check(ks2.read_provisional_hits(81, 99, 1) == {1500, 1600},
              f"both provisional values are on disk after the second call "
              f"(got {ks2.read_provisional_hits(81, 99, 1)!r})")
        check(_read_hits(81, 99, 1) == [500],
              "the shared hit file is untouched by the second call (nothing in "
              "[1500, 1600] was below the frontier)")

        # =====================================================================
        # Layer 3: end-to-end via scan_locations() against REAL twin primes inside
        # floor 2's own [100, 1000) range, window_m=100 covering [100, 200) -- proves
        # _exhaustive_frontier_value() is actually wired into the sieve's own
        # hit-recording path, not just correct in isolation.
        # =====================================================================
        twin_pattern = {"k": 2, "id": 1, "offsets": [0, 2], "discoverer": "test", "date": "test"}

        # Case A: floor 2's own exhaustive scan has NOT reached this range at all (no
        # checkpoint) -- the confirmed twin hit at 101 must land in PROVISIONAL, not
        # the shared file, since constellation_finder_v2 hasn't verified it yet.
        _write_source_window(2, "PRIME_WINDOW_LOW.bin", [101, 103])  # base_prime=101
        _write_source_window(2, "PRIME_WINDOW_HIGH.bin", [503, 509])  # base_prime=503
        result_a = ks2.scan_locations(2, twin_pattern, [100], window_m=100)
        # [100, 200) genuinely contains 7 twin-prime pairs, not just (101, 103) --
        # 101/107/137/149/179/191/197, each with a +2 partner also prime.
        expected_twins = {101, 107, 137, 149, 179, 191, 197}
        check(result_a["total_confirmed"] == len(expected_twins),
              f"the wheel+Miller-Rabin sieve itself finds every real twin base in "
              f"[100, 200) (got total_confirmed={result_a['total_confirmed']!r}, "
              f"expected {len(expected_twins)})")
        check(_read_hits(2, 2, 1) == [],
              f"with NO exhaustive coverage yet, none of them are written to the "
              f"shared file (got {_read_hits(2, 2, 1)!r})")
        check(ks2.read_provisional_hits(2, 2, 1) == expected_twins,
              f"...they all go to the PROVISIONAL file instead "
              f"(got {ks2.read_provisional_hits(2, 2, 1)!r})")

        # Case B: constellation_finder_v2's own exhaustive scan now covers the LOW
        # window (base_prime=101) -- the SAME location, re-scanned, must now land in
        # the shared file, exactly like ktuple_sieve_v1.py always behaved.
        windows_2 = cf2.list_source_windows(2)
        names_2 = [w[0] for w in windows_2]
        cf2.write_done_ranges(2, names_2, {0})  # LOW done, HIGH not
        result_b = ks2.scan_locations(2, twin_pattern, [100], window_m=100)
        check(_read_hits(2, 2, 1) == sorted(expected_twins),
              f"once the exhaustive scan covers this window, the SAME hits are "
              f"recorded in the shared file (got {_read_hits(2, 2, 1)!r})")

        if failures:
            print(f"\n{len(failures)} FAILURE(S)")
            return 1
        print("\nALL CHECKS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp_portal, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
