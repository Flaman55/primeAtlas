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

  2. FLOOR-boundary crossing: a pattern whose base sits near the very TOP of one floor
     with its tail spilling into the NEXT FLOOR's numbers was never checked at all before
     check_floor_boundary() was added -- the within-floor peek only ever looks at the next
     window inside the SAME floor, and a floor's own last window has no such next window.
     A hit whose base value belongs to the lower floor must be recorded under that lower
     floor even when its tail value falls in the floor above.

  3. Re-scan safety: re-appending the same hit values a second time (e.g. because
     CHECKPOINT.txt was reset, or a floor's
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
        # BUG-TARGET #2 -- the floor-boundary-crossing fix. Floor 3
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
              f"floor), not silently dropped or misfiled under the higher floor "
              f"(got hits={hits_k2_f3!r}, expected [9998])")
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
        # BUG-TARGET #3 -- re-scan safety: resetting floor 20's checkpoint
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

        # =====================================================================
        # max_windows batching (floor-25-scale fix): a floor with 4
        # windows, processed 2-at-a-time, must resume correctly across calls and only
        # run the boundary check once truly caught up -- see process_floor()'s own
        # docstring on why this exists (WSL dying mid-run on a floor with hundreds of
        # thousands of windows).
        # =====================================================================
        _write_window(30, "PRIME_WINDOW_P.bin", [10, 20])
        _write_window(30, "PRIME_WINDOW_Q.bin", [30, 40])
        _write_window(30, "PRIME_WINDOW_R.bin", [50, 60])
        _write_window(30, "PRIME_WINDOW_S.bin", [70, 80])

        remaining_1 = cf.process_floor(30, max_windows=2)
        check(remaining_1 == 2,
              f"batch 1/2 (max_windows=2 of 4 total) reports 2 window(s) still "
              f"remaining (got {remaining_1!r})")
        check(cf.read_checkpoint(30) == "PRIME_WINDOW_Q.bin",
              f"batch 1 stops exactly at the 2nd window, not further "
              f"(got checkpoint={cf.read_checkpoint(30)!r})")
        check(cf.is_boundary_checked(30) is False,
              "the floor's own upper-boundary check must NOT run yet -- this batch "
              "didn't reach the floor's real last window")

        remaining_2 = cf.process_floor(30, max_windows=2)
        check(remaining_2 == 0,
              f"batch 2/2 finishes the remaining 2 windows, reporting 0 remaining "
              f"(got {remaining_2!r})")
        check(cf.read_checkpoint(30) == "PRIME_WINDOW_S.bin",
              f"batch 2 reaches the floor's real last window "
              f"(got checkpoint={cf.read_checkpoint(30)!r})")
        check(cf.is_boundary_checked(30) is True,
              "the boundary check DOES run once a batch actually reaches the floor's "
              "real last window, same as an unbounded (max_windows=None) run would")

        # A THIRD call (floor fully caught up, batched or not) must be a clean no-op,
        # matching the unbounded (max_windows=None) "Nothing new" behavior.
        remaining_3 = cf.process_floor(30, max_windows=2)
        check(remaining_3 == 0,
              f"a floor already fully caught up reports 0 remaining regardless of "
              f"max_windows (got {remaining_3!r})")

        # =====================================================================
        # Graceful stop: STOP_REQUEST.txt, checked once per window at the very
        # TOP of the loop, must break BETWEEN windows -- never mid-window -- and report
        # the correct "still remaining" count, same shape as an ordinary --max-windows
        # clip. Floor 50 gets 4 windows; the marker is dropped in right before the run,
        # so it must stop after window 1 with 3 remaining, leaving windows 2-4 untouched.
        # =====================================================================
        _write_window(50, "PRIME_WINDOW_M.bin", [10, 20])
        _write_window(50, "PRIME_WINDOW_N.bin", [30, 40])
        _write_window(50, "PRIME_WINDOW_O.bin", [50, 60])
        _write_window(50, "PRIME_WINDOW_P.bin", [70, 80])
        stop_path = os.path.join(tmp_portal, cf.STOP_REQUEST_FILENAME)

        original_stop_requested = cf._stop_requested
        calls_before_drop = [0]

        def _drop_stop_request_after_first_window(*a, **k):
            calls_before_drop[0] += 1
            if calls_before_drop[0] == 2:  # 1st call: loop-top check before window 1
                                            # (must see nothing yet); 2nd call: loop-top
                                            # check before window 2 -- drop it exactly
                                            # here so window 1 is fully committed first.
                with open(stop_path, "w", encoding="utf-8") as f:
                    f.write("test\n")
            return original_stop_requested()

        cf._stop_requested = _drop_stop_request_after_first_window
        try:
            remaining_stop = cf.process_floor(50)
        finally:
            cf._stop_requested = original_stop_requested
        check(remaining_stop == 3,
              f"stopping after window 1 of 4 reports 3 window(s) still remaining "
              f"(got {remaining_stop!r})")
        check(cf.read_checkpoint(50) == "PRIME_WINDOW_M.bin",
              f"checkpoint reflects ONLY the one window fully processed before the stop "
              f"was honored (got checkpoint={cf.read_checkpoint(50)!r})")
        check(cf.is_boundary_checked(50) is False,
              "the floor's own upper-boundary check must NOT run -- the floor is not "
              "actually caught up, a stop mid-floor is not the same as finishing it")
        os.remove(stop_path)

        # Resuming afterward (marker gone, exactly what generation_tab.py's own
        # _on_constellation_finished() guarantees -- see that method's own docstring)
        # must pick up right where the stop left off, same as any other checkpoint
        # resume already tested above.
        remaining_after_resume = cf.process_floor(50)
        check(remaining_after_resume == 0,
              f"resuming after the stop-request marker is removed finishes the "
              f"remaining 3 windows in one call (got {remaining_after_resume!r})")
        check(cf.read_checkpoint(50) == "PRIME_WINDOW_P.bin",
              f"checkpoint now reflects the floor's real last window "
              f"(got checkpoint={cf.read_checkpoint(50)!r})")
        check(cf.is_boundary_checked(50) is True,
              "the boundary check runs once the floor is genuinely caught up, same as "
              "any unbounded run reaching the floor's last window")

        # =====================================================================
        # read_prime_window_last_value() itself -- must agree exactly with plain
        # read_prime_window() on both a real, already-populated hit file (floor 20's
        # k=2 file, [200, 500] from earlier in this test) and an empty/nonexistent one.
        # =====================================================================
        real_hits = _read_hits(20, 2, 1)
        lean_last, lean_count = prime_sieve_v1.read_prime_window_last_value(cf.hit_file_path(20, 2, 1))
        check((lean_last, lean_count) == (real_hits[-1], len(real_hits)),
              f"read_prime_window_last_value() agrees with a full read_prime_window() "
              f"decode on a real file (got {(lean_last, lean_count)!r}, expected "
              f"{(real_hits[-1], len(real_hits))!r})")
        # =====================================================================
        # LAST_VALUES.tsv disk cache -- THE regression test for
        # the actual floor-25 crash root cause: a fresh process_floor() call's
        # in-memory last_value_cache starts EMPTY every run, so without a PERSISTENT
        # disk cache, the first hit for any pattern in a fresh run used to force a
        # decode of that pattern's WHOLE accumulated hit file just to learn its own
        # last value -- confirmed via a real crash log to be exactly what killed the
        # WSL process on floor 25's k=2 hit file after 342,001 already-processed
        # windows. Proves a SECOND, separate process_floor() call (simulating a fresh
        # WSL process/relaunch) skips that decode entirely, by counting real calls to
        # prime_sieve_v1.read_prime_window_last_value() (the lean, list-free reader
        # _resolve_last_value() actually calls -- see that function's own docstring on
        # why plain read_prime_window() was itself part of the crash, independent of
        # the caching question) against the HIT FILE path specifically (source window
        # reads are unaffected and still happen normally, so a blanket call count would
        # be the wrong signal).
        # =====================================================================
        original_read_last_value = prime_sieve_v1.read_prime_window_last_value
        hit_file_reads = []

        def _counting_read(path):
            if "HITS_" in path:
                hit_file_reads.append(path)
            return original_read_last_value(path)

        prime_sieve_v1.read_prime_window_last_value = _counting_read
        try:
            _write_window(40, "PRIME_WINDOW_X.bin", [1000, 1002])  # twin hit at 1000
            cf.process_floor(40)
            check(len(hit_file_reads) == 0,
                  f"a BRAND NEW hit file (never existed before) needs no decode at all "
                  f"to learn its 'last value' (got {len(hit_file_reads)} hit-file "
                  f"read(s): {hit_file_reads!r})")

            hit_file_reads.clear()
            _write_window(40, "PRIME_WINDOW_Y.bin", [2000, 2002])  # twin hit at 2000
            cf.process_floor(40)  # a SEPARATE call -- simulates a fresh WSL process
                                   # with an empty in-memory last_value_cache, same as
                                   # a real relaunch (auto-retry or batch-continuation)
                                   # would have
            check(len(hit_file_reads) == 0,
                  f"a SECOND, separate process_floor() call must find its pattern's "
                  f"last value via the ON-DISK cache, WITHOUT a full decode of the "
                  f"(potentially huge) accumulated hit file "
                  f"(got {len(hit_file_reads)} hit-file read(s): {hit_file_reads!r})")

            hits_k2_f40 = _read_hits(40, 2, 1)
            check(hits_k2_f40 == [1000, 2000],
                  f"both hits are correctly recorded across the two separate runs, "
                  f"proving the cache didn't just skip the decode but also stayed "
                  f"CORRECT (got {hits_k2_f40!r})")

            # Staleness safety: if the hit file changes WITHOUT the disk cache being
            # told (simulating an external modification, e.g. a storage merge per
            # [[primeatlas_storage_merge_federation]]), the cache must be distrusted
            # and the safe, slow full-decode fallback must still fire -- never silently
            # trust a stale cached last_value (which could corrupt the file's own
            # gap-encoding -- see append_prime_window()'s own docstring).
            hpath = cf.hit_file_path(40, 2, 1)
            prime_sieve_v1.append_prime_window(hpath, [2500])  # bypasses the cache entirely
            hit_file_reads.clear()
            _write_window(40, "PRIME_WINDOW_Z.bin", [3000, 3002])  # twin hit at 3000
            cf.process_floor(40)
            check(len(hit_file_reads) == 1,
                  f"an externally-modified hit file (count no longer matches the disk "
                  f"cache) correctly falls back to exactly one full decode, not zero "
                  f"(got {len(hit_file_reads)} hit-file read(s))")
            hits_k2_f40_final = _read_hits(40, 2, 1)
            check(hits_k2_f40_final == [1000, 2000, 2500, 3000],
                  f"the fallback decode still produces the CORRECT result -- no "
                  f"corruption, no lost/duplicated values "
                  f"(got {hits_k2_f40_final!r})")
        finally:
            prime_sieve_v1.read_prime_window_last_value = original_read_last_value

        if failures:
            print(f"\n{len(failures)} FAILURE(S)")
            return 1
        print("\nALL CHECKS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp_portal, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
