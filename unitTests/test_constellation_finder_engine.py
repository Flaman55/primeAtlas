"""
test_constellation_finder_engine.py -- integration tests for constellation_finder_v1.py's
process_floor()/check_floor_boundary()/checkpoint machinery, using REAL temporary storage
and REAL PGS2 window files (via prime_sieve_v1.write_prime_window) -- no mocking of the
constellation engine itself, no tkinter/display dependency at all (this module has none).

Companion to test_constellation_matching.py, which covers match_patterns_vectorized() in
isolation; this file covers everything AROUND it: which windows get streamed, in what
order, how a pattern spanning a window boundary (or a FLOOR boundary) gets caught, how
CHECKPOINT.txt resume works, and the dedup safety net that keeps a re-scanned window from
crashing.

Targets three specific, documented historical fixes (see each section's own comment):

  1. Within-floor peek-ahead (present from v1): a pattern whose tail spills past one
     window's own values into the NEXT window (same floor) is only found because
     process_floor() peeks a bounded number of values from the head of the next window.

  2. FLOOR-boundary crossing (added 2026-08-18, at Artur's explicit request -- "jeśli choć
     jeden element jest z piętra niżej a reszta wyżej, to wciąż powinna być widoczna jak
     aktualne piętro"): a pattern whose base sits near the very TOP of one floor with its
     tail spilling into the NEXT FLOOR's numbers was never checked at all before
     check_floor_boundary() was added -- the within-floor peek only ever looks at the next
     window inside the SAME floor, and a floor's own last window has no such next window.

  3. Re-scan safety (added 2026-08-19, at Artur's request): re-appending the same hit
     values a second time (e.g. because CHECKPOINT.txt was reset, or a floor's
     constellations/ folder was physically copied in from another storage that had
     independently scanned some of the same windows) used to crash on
     append_prime_window()'s own strict-increase assertion the instant a re-scanned window
     turned up a real hit; _append_hits_deduped() is supposed to make this safe.

Uses tiny hand-picked integers as "primes" (write_prime_window doesn't verify primality,
only that its input is sorted ascending ints -- see that function's own docstring) so
expected hits can be worked out by hand and verified exactly.

Every check() states the specific expected vs. actual value.

Usage (Windows, real Python -- pure Python + numpy, no Tk/display dependency at all):
    python unitTests\\test_constellation_finder_engine.py

Usage (this sandbox, headless -- no display needed for this file either):
    python3 unitTests/test_constellation_finder_engine.py
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
    import constellation_finder_v1 as cf

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_constellation_engine_test_")
    try:
        cf.PORTAL_FOLDER = tmp_portal  # redirect the module's own global, same convention
                                        # as the Tk-based tests monkeypatching PORTAL_FOLDER

        def _write_window(floor, name, primes):
            # source_primes/ is sharded into shard_NNNNN subfolders (see
            # window_sharding.py, task #405) -- constellation_finder_v1.list_source_
            # windows() now walks those via list_sharded_files() rather than a flat
            # os.listdir(), so fixtures must be placed the same way real writers do.
            # Any valid shard placement works for a test this small; shard_00000
            # (window_index=0) is simplest and matches how a real low floor writes.
            source_dir = os.path.join(tmp_portal, f"10p{floor}", "source_primes")
            shard_dir = window_sharding.shard_dir(source_dir, 0)
            os.makedirs(shard_dir, exist_ok=True)
            path = os.path.join(shard_dir, name)
            prime_sieve_v1.write_prime_window(path, sorted(primes))
            return path

        def _read_hits(floor, k, variant_id):
            path = cf.hit_file_path(floor, k, variant_id)
            if not os.path.exists(path):
                return []
            return prime_sieve_v1.read_prime_window(path)

        # =====================================================================
        # BUG-TARGET #1 -- within-floor peek-ahead: floor 20 gets two windows; the
        # only k=2 (twin, offsets [0,2]) hit straddles the window boundary (200 is the
        # last value of window A, 202 is the FIRST value of window B).
        # =====================================================================
        _write_window(20, "PRIME_WINDOW_A.bin", [100, 200])
        _write_window(20, "PRIME_WINDOW_B.bin", [202, 300])
        cf.process_floor(20)
        hits_k2_f20 = _read_hits(20, 2, 1)
        check(hits_k2_f20 == [200],
              f"a k=2 pattern straddling two windows WITHIN the same floor (200 in "
              f"window A, its +2 partner 202 in window B) is found via the peek-ahead "
              f"mechanism (got hits={hits_k2_f20!r}, expected [200])")

        # =====================================================================
        # CHECKPOINT resume: re-running process_floor(20) with no new windows must not
        # re-append the same hit again (checkpoint should skip both already-processed
        # windows entirely).
        # =====================================================================
        cf.process_floor(20)
        hits_k2_f20_again = _read_hits(20, 2, 1)
        check(hits_k2_f20_again == [200],
              f"re-running process_floor() with no new windows must leave the hit file "
              f"unchanged (checkpoint skips already-processed windows) "
              f"(got hits={hits_k2_f20_again!r}, expected [200] still, not [200, 200])")
        checkpoint_after = cf.read_checkpoint(20)
        check(checkpoint_after == "PRIME_WINDOW_B.bin",
              f"CHECKPOINT.txt records the LAST window actually processed "
              f"(got {checkpoint_after!r}, expected 'PRIME_WINDOW_B.bin')")

        # Genuinely NEW windows added afterward must still be picked up on the next run
        # (checkpoint resume, not "floor already fully done forever"). NOTE: this is
        # deliberately NOT testing "does a later-arriving window retroactively find a hit
        # for an EARLIER, already-checkpointed window's candidate" -- process_floor()
        # never re-reads a checkpointed window once it's been passed, by design (the
        # peek-ahead only ever looks at whatever next window exists AT THE TIME a window
        # is processed), so 400 and its +2 partner 402 are placed in TWO NEW windows
        # (C, D) added and processed together in the SAME run, exactly the case
        # checkpoint-resume is meant to support.
        _write_window(20, "PRIME_WINDOW_C.bin", [400, 500])
        _write_window(20, "PRIME_WINDOW_D.bin", [502])  # 500+2=502 -> hit at 500
        cf.process_floor(20)
        hits_k2_f20_third = _read_hits(20, 2, 1)
        check(hits_k2_f20_third == [200, 500],
              f"adding two new windows (C, D) after floor 20 was already checkpointed "
              f"at B must still be picked up on the next run, with C/D's own "
              f"peek-ahead hit (500) appended after the earlier one (200) without "
              f"disturbing it (got hits={hits_k2_f20_third!r}, expected [200, 500])")

        # =====================================================================
        # BUG-TARGET #2 -- the floor-boundary-crossing fix (2026-08-18). Floor 3
        # ([1000, 10000)) gets one window whose last value (9998) is close enough to the
        # floor boundary (10000) that a k=2 pattern's tail (9998+2=10000) could only be
        # found by looking into floor 4's own first window -- something ONLY
        # check_floor_boundary() does; process_floor()'s own per-window peek only ever
        # looks within the SAME floor (floor 3 here has just one window, so there is no
        # "next window" for the ordinary peek to use at all).
        # =====================================================================
        _write_window(3, "PRIME_WINDOW_LOW.bin", [9990, 9998])
        cf.process_floor(3)  # floor 4 has no data yet -> boundary stays UNRESOLVED
        check(cf.is_boundary_checked(3) is False,
              "floor 3's boundary must stay UNRESOLVED (no marker written) while floor "
              "4 has no source data yet to check against -- must not silently give up "
              "and mark it done")
        check(_read_hits(3, 2, 1) == [],
              "before floor 4 has any data, no boundary-spanning hit can have been "
              "found yet")

        _write_window(4, "PRIME_WINDOW_NEXT.bin", [10000, 10050])
        cf.process_floor(3)  # now floor 4 has data -> boundary check can resolve
        check(cf.is_boundary_checked(3) is True,
              "once floor 4 has source data, re-running process_floor(3) must resolve "
              "and mark the boundary as checked")
        hits_k2_f3 = _read_hits(3, 2, 1)
        check(hits_k2_f3 == [9998],
              f"THE historical bug this exists to fix: a k=2 pattern based at 9998 "
              f"(floor 3's own last value) whose +2 partner (10000) lives in FLOOR 4 "
              f"must be recorded under FLOOR 3 (the lower floor, i.e. the base's own "
              f"floor) -- Artur's own words: 'jeśli choć jeden element jest z piętra "
              f"niżej a reszta wyżej, to wciąż powinna być widoczna jak aktualne "
              f"piętro' (got hits={hits_k2_f3!r}, expected [9998])")
        check(_read_hits(4, 2, 1) == [],
              "the boundary-spanning hit must be recorded ONLY under floor 3 (its "
              "base's own floor), never duplicated under floor 4 as well")

        # Idempotency: calling process_floor(3) again must not re-append/duplicate the
        # already-resolved boundary hit.
        cf.process_floor(3)
        check(_read_hits(3, 2, 1) == [9998],
              f"re-running process_floor(3) after its boundary is already resolved must "
              f"not touch the hit file again (marker file short-circuits the whole "
              f"boundary check -- got {_read_hits(3, 2, 1)!r}, expected [9998] still)")

        # =====================================================================
        # Floor whose last window is NOT close enough to its own boundary: must resolve
        # immediately (no cross-floor read needed at all, no dependency on the next
        # floor existing), since no catalog offset (max 84) could possibly reach past
        # the boundary from here.
        # =====================================================================
        _write_window(5, "PRIME_WINDOW_FAR.bin", [100000, 100010])  # floor 5 = [1e5,1e6)
        cf.process_floor(5)  # floor 6 has NO data at all -- must not matter here
        check(cf.is_boundary_checked(5) is True,
              "a floor whose last window's highest value is far short of its own "
              "numeric boundary (no catalog offset could possibly reach past it) must "
              "resolve its boundary check immediately, without needing the next "
              "floor's data at all")
        check(_read_hits(5, 2, 1) == [],
              "no boundary-spanning hit is possible here, so none should be recorded")

        # =====================================================================
        # BUG-TARGET #3 -- re-scan safety (2026-08-19): resetting floor 20's checkpoint
        # to force a full re-scan of already-processed windows (simulating a regressed/
        # copied-in checkpoint) must NOT crash on append_prime_window()'s strict-
        # increase assertion, and must NOT double the recorded hit count.
        # =====================================================================
        cf.write_checkpoint(20, "__nonexistent_forces_full_rescan__")
        try:
            cf.process_floor(20)
            rescan_crashed = False
        except Exception as e:
            rescan_crashed = True
            rescan_exception = e
        check(rescan_crashed is False,
              f"re-scanning already-processed windows (forced via a checkpoint pointing "
              f"at a nonexistent filename, exactly the 'ignoring checkpoint, processing "
              f"from the start' fallback path) must NOT crash "
              f"({'raised ' + repr(rescan_exception) if rescan_crashed else 'no exception raised'})")
        hits_after_rescan = _read_hits(20, 2, 1)
        check(hits_after_rescan == [200, 500],
              f"re-scanning must be idempotent -- the SAME hits already on disk must "
              f"not be duplicated by _append_hits_deduped()'s own dedup filter "
              f"(got {hits_after_rescan!r}, expected [200, 500] still, not "
              f"[200, 200, 500, 500])")

        if failures:
            print(f"\n{len(failures)} FAILURE(S)")
            return 1
        print("\nALL CHECKS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp_portal, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
