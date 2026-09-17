"""
test_constellation_finder_v2_checkpoint.py -- integration tests for
constellation_finder_v2.py's gap-aware CHECKPOINT.txt (done_range=) format, using REAL
temporary storage and REAL PGS2 window files (via prime_sieve_v1.write_prime_window), no
mocking of the constellation engine itself.

Companion to test_constellation_finder_engine.py (v1's own checkpoint/boundary/dedup
tests, still valid against v2 unchanged since only the checkpoint's own read/write
format and process_floor()'s window-selection logic changed) -- this file covers only
what v2 adds: resuming from a set of DONE RANGES instead of a single last-processed
pointer.

Targets the field report this exists to fix: an unpredictable PC restart left two
constellation_finder processes running for the same floor, and
CHECKPOINT.txt's single "last_processed_file=" pointer -- overwritten by whichever
process wrote most recently -- ended up naming a window far AHEAD of one that had
genuinely never been scanned, leaving a "hole" behind it. v1's own resume logic
("everything after last_done") has no way to represent that hole at all: if it trusted
the ahead-of-hole pointer, the hole would NEVER get scanned again; if it fell back to
"ignoring checkpoint, processing from the start" (the only other path v1 has), it would
burn hours re-scanning everything ALREADY covered just to close one small gap. v2's own
done_range set can represent "A,B and D,E done, C is not" directly, so it fills exactly
the hole and nothing else.

Usage (Windows, real Python -- pure Python + numpy, no Tk/display dependency at all):
    python unitTests\\test_constellation_finder_v2_checkpoint.py

Usage (this sandbox, headless -- no display needed for this file either):
    python3 unitTests/test_constellation_finder_v2_checkpoint.py
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

    tmp_portal = tempfile.mkdtemp(prefix="primeatlas_constellation_v2_checkpoint_test_")
    try:
        cf2.PORTAL_FOLDER = tmp_portal  # same convention as v1's own engine test

        def _write_window(floor, name, primes):
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
        # THE core scenario: a floor with a HOLE in its done set (windows A,B,D,E
        # already marked done, C is not) -- exactly the shape a regressed/overlapping
        # checkpoint from two independent writers can leave behind. Only window C
        # (the one with the actual k=2 hit, at 50) carries a pattern; A,B,D,E are
        # plain filler with no hits of their own, so there is nothing to fake by
        # marking them "done" without really having scanned them.
        # =====================================================================
        _write_window(60, "PRIME_WINDOW_A.bin", [10, 20])
        _write_window(60, "PRIME_WINDOW_B.bin", [30, 40])
        _write_window(60, "PRIME_WINDOW_C.bin", [50, 52])  # twin hit at 50
        _write_window(60, "PRIME_WINDOW_D.bin", [70, 80])
        _write_window(60, "PRIME_WINDOW_E.bin", [90, 100])

        windows = cf2.list_source_windows(60)
        names = [w[0] for w in windows]
        check(names == ["PRIME_WINDOW_A.bin", "PRIME_WINDOW_B.bin", "PRIME_WINDOW_C.bin",
                         "PRIME_WINDOW_D.bin", "PRIME_WINDOW_E.bin"],
              f"sanity: floor 60's 5 windows sort by base_prime in the expected A..E "
              f"order (got {names!r})")

        # Simulate the regressed/overlapping checkpoint directly: A, B, D, E (indices
        # 0, 1, 3, 4) done; C (index 2) is the hole.
        cf2.write_done_ranges(60, names, {0, 1, 3, 4})
        done_ranges_before = cf2.read_done_ranges(60)
        check(len(done_ranges_before) == 2,
              f"the simulated hole is persisted as TWO separate done_range entries "
              f"(A|B and D|E), not one contiguous range "
              f"(got {done_ranges_before!r})")

        original_read_prime_window = prime_sieve_v1.read_prime_window
        source_reads = []

        def _counting_read(path):
            if "source_primes" in path.replace("\\", "/"):
                source_reads.append(path)
            return original_read_prime_window(path)

        prime_sieve_v1.read_prime_window = _counting_read
        try:
            remaining = cf2.process_floor(60)
        finally:
            prime_sieve_v1.read_prime_window = original_read_prime_window

        check(remaining == 0,
              f"filling the one-window hole leaves nothing pending "
              f"(got remaining={remaining!r})")
        # E is legitimately read a second time here regardless of the checkpoint fix --
        # check_floor_boundary() always reads the floor's own LAST window once, the
        # first time a floor becomes fully caught up (see that function's own
        # docstring) -- that's unrelated to pattern-matching resume. The actual claim
        # under test is that A, B and D (already done, no boundary role) are NEVER
        # re-read, and C (the hole) is read exactly once.
        read_names = sorted(os.path.basename(p) for p in source_reads)
        check(read_names == ["PRIME_WINDOW_C.bin", "PRIME_WINDOW_E.bin"],
              f"process_floor() re-reads only the hole (C, for pattern matching) and E "
              f"(the floor's last window, for the one-time boundary check) -- never "
              f"re-reading A, B or D, which the done_range set already correctly marks "
              f"as covered (got {read_names!r})")
        check(_read_hits(60, 2, 1) == [50],
              f"the hole's own hit (twin at 50) is found once it's actually scanned "
              f"(got {_read_hits(60, 2, 1)!r})")

        done_ranges_after = cf2.read_done_ranges(60)
        check(len(done_ranges_after) == 1 and done_ranges_after[0] == (names[0], names[-1]),
              f"filling the hole merges the two ranges back into ONE contiguous "
              f"A..E range, same as a floor that was never interrupted at all "
              f"(got {done_ranges_after!r})")
        check(cf2.resolve_done_names(60, names) == set(names),
              "every one of the floor's 5 windows now resolves as done")

        # Re-running once more (fully caught up) must be a clean no-op, same as v1.
        remaining_again = cf2.process_floor(60)
        check(remaining_again == 0,
              f"re-running a fully-caught-up floor is a no-op (got {remaining_again!r})")
        check(_read_hits(60, 2, 1) == [50],
              "re-running does not duplicate the already-recorded hit")

        # =====================================================================
        # Migration: a plain v1-style CHECKPOINT.txt (only "last_processed_file=",
        # no done_range= lines at all) must be read as ONE range covering everything
        # from the floor's own first window through the named one -- v1's own
        # assumption exactly -- so a floor already in progress under v1 loses no
        # recorded progress when the GUI switches over to v2.
        # =====================================================================
        _write_window(70, "PRIME_WINDOW_A.bin", [1000, 1010])
        _write_window(70, "PRIME_WINDOW_B.bin", [1020, 1030])
        _write_window(70, "PRIME_WINDOW_C.bin", [1040, 1042])  # twin hit at 1040

        legacy_path = cf2._checkpoint_path(70)
        os.makedirs(os.path.dirname(legacy_path), exist_ok=True)
        with open(legacy_path, "w", encoding="utf-8") as f:
            f.write("last_processed_file=PRIME_WINDOW_B.bin\n")
            f.write("updated_at=2026-09-01 00:00:00 UTC\n")

        names_70 = [w[0] for w in cf2.list_source_windows(70)]
        check(cf2.resolve_done_names(70, names_70) == {"PRIME_WINDOW_A.bin", "PRIME_WINDOW_B.bin"},
              f"a legacy v1 checkpoint naming B is read as 'A and B done, C is not' "
              f"(got {cf2.resolve_done_names(70, names_70)!r})")

        remaining_70 = cf2.process_floor(70)
        check(remaining_70 == 0,
              f"only the genuinely new window (C) needs processing "
              f"(got remaining={remaining_70!r})")
        check(_read_hits(70, 2, 1) == [1040],
              f"C's own hit is found on this first v2 run after migrating from a v1 "
              f"checkpoint (got {_read_hits(70, 2, 1)!r})")
        check(cf2.read_checkpoint(70) == "PRIME_WINDOW_C.bin",
              f"read_checkpoint() (the v1-compatible 'how far has this floor gotten' "
              f"view) still works after migrating to the v2 format "
              f"(got {cf2.read_checkpoint(70)!r})")
        done_ranges_70 = cf2.read_done_ranges(70)
        check(len(done_ranges_70) == 1 and done_ranges_70[0] == ("PRIME_WINDOW_A.bin", "PRIME_WINDOW_C.bin"),
              f"CHECKPOINT.txt now carries a native v2 done_range covering all three "
              f"windows (got {done_ranges_70!r})")

        if failures:
            print(f"\n{len(failures)} FAILURE(S)")
            return 1
        print("\nALL CHECKS PASSED")
        return 0
    finally:
        shutil.rmtree(tmp_portal, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
