"""
test_generation_window_arithmetic.py -- characterization tests for the pure floor/window
arithmetic that plans WHERE on disk a generation run writes, WITHOUT launching any real
sieve/WSL subprocess. Written for the refactor branch's Faza 3 Generation-tab extraction
(task #390): before touching that tab's ~2650 lines of UI code, this suite pins down the
exact behavior of the functions responsible for its three worst historical production
incidents (see each test's own docstring for the specific bug it targets):

  1. MemoryError on floor 25 -- a starting point deep into an empty floor caused
     target_idx to be built from 0, producing a Python list with hundreds of quadrillions
     of entries.
  2. The "floor-7-with-130-million-range-numbers" bug -- a requested range that crossed a
     floor's own [10**N, 10**(N+1)) boundary silently wrote the NEXT floor's numbers into
     the current floor's folder.
  3. The "1001 windows for a Width=1000 request" off-by-one -- rounding both ends of a
     non-window-aligned starting point outward (instead of only the far end) silently
     added one extra window beyond what a width BUDGET asked for.

These target primeatlas/generation.py, not the compiled C sieve engine itself -- see this
file's own module docstring reasoning for why: the engine (prime_sieve_engine_v*.so,
ctypes-loaded, linked against libprimesieve.so.12) cannot run in a plain Linux sandbox
without that exact shared library, which is not installable here without root.
This suite instead targets the layer that decides what to hand the engine -- which is
exactly where all three bugs above actually lived -- using real temporary directories
seeded with EMPTY, correctly-named PRIME_WINDOW_*.bin files (list_source_filenames() only
ever reads a file's NAME via a regex, never its contents -- see primeatlas/storage.py's
own docstring -- so an empty file at the right name is indistinguishable from a real one
to every function tested here).

Every check() call states the SPECIFIC expected vs. actual value in its message, not just
pass/fail, so a future regression points straight at what went wrong instead of just
"something in Generation broke" (this was Artur's explicit request when asking for this
suite: tests must "wyłapały i wyświetliły co faktycznie powoduje błąd" -- catch it AND
show what actually caused it).

Updated during the Generation-tab extraction itself (Faza 3, 2026-08-23): these functions
moved from prime_atlas_v1.py into primeatlas/generation.py (see that module's own
docstring) -- this suite now imports from there directly instead of through
prime_atlas_v1, and no longer needs tkinter/Xvfb at all (generation.py has no GUI
dependency of its own).

Usage (Windows, real Python -- no Tk/display dependency, these are plain functions):
    python unitTests\\test_generation_window_arithmetic.py

Usage (this sandbox, headless -- plain python3, no Xvfb needed anymore):
    python3 unitTests/test_generation_window_arithmetic.py
"""
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "constellation"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _touch_window(portal, floor, target_idx, window_m=10_000_000):
    """Creates an EMPTY PRIME_WINDOW_*.bin at the given floor/target_idx -- every function
    under test here reads only the FILENAME (via _offset_from_filename's regex), never the
    file's contents, so this is a safe, fast, real-filesystem stand-in for a genuinely
    generated window (see this module's own docstring).

    source_primes/ is sharded into shard_NNNNN subfolders (see window_sharding.py, task
    #405) -- placed via window_sharding.shard_dir() with the real target_idx as
    window_index (target_idx IS the window's 0-based generation-order index, matching
    every real writer's own offset // window_m math)."""
    import window_sharding
    offset = target_idx * window_m
    source_dir = os.path.join(portal, f"10p{floor}", "source_primes")
    shard_dir = window_sharding.shard_dir(source_dir, target_idx)
    os.makedirs(shard_dir, exist_ok=True)
    suffix = f"{offset // 1_000_000}M" if offset and offset % 1_000_000 == 0 else str(offset)
    name = f"PRIME_WINDOW_10p{floor}_off_{suffix}.bin"
    open(os.path.join(shard_dir, name), "wb").close()


def _test_compute_totals_bumps_from_new_rows():
    """compute_totals_bumps_from_new_rows() -- the pure row-filtering logic behind
    GenerationTab._bump_totals_from_finished_run() (added 2026-08-27, see storage.py's
    own module docstring for the persisted-totals feature this belongs to). No temp
    directory needed -- this function only ever looks at plain row dicts, the exact
    shape read_benchmark_log()/csv.DictReader hands back, never touching disk itself."""
    import primeatlas.generation as m

    rows = [
        {"base_exponent": "5", "total_primes": "100", "windows_written": "1",
         "bytes_written": "800", "write_files": "1"},  # row 0: pre-existing, before_count skips it
        {"base_exponent": "7", "total_primes": "40", "windows_written": "2",
         "bytes_written": "500", "write_files": "1"},  # row 1: NEW, real write
        {"base_exponent": "7", "total_primes": "999", "windows_written": "3",
         "bytes_written": "9999", "write_files": "0"},  # row 2: NEW but count-only, must be skipped
        {"base_exponent": "9", "total_primes": "bogus", "windows_written": "1",
         "bytes_written": "10", "write_files": "1"},  # row 3: NEW but malformed, must be skipped
        {"base_exponent": "5", "total_primes": "0", "windows_written": "0",
         "bytes_written": "0", "write_files": "1"},  # row 4: NEW but genuinely zero, must be skipped
        {"base_exponent": "5", "total_primes": "12", "windows_written": "1",
         "bytes_written": "96", "write_files": "1"},  # row 5: NEW, real write, SAME floor as row 0
    ]
    bumps = m.compute_totals_bumps_from_new_rows(rows, before_count=1)
    check(bumps == [(7, 40, 2, 500), (5, 12, 1, 96)],
          f"compute_totals_bumps_from_new_rows skips the pre-existing row (index 0, "
          f"before before_count=1), the count-only row (write_files='0'), the malformed "
          f"row (non-numeric total_primes), and the genuinely-zero row, keeping only the "
          f"two real new writes in order (got {bumps!r})")

    check(m.compute_totals_bumps_from_new_rows(rows, before_count=len(rows)) == [],
          "before_count == len(rows) (nothing written since the snapshot) returns an "
          "empty list, not an error")
    check(m.compute_totals_bumps_from_new_rows([], before_count=0) == [],
          "an empty benchmark_log.csv returns an empty list")

    legacy_row = [{"base_exponent": "3", "total_primes": "5", "windows_written": "1"}]
    # No "write_files" key at all -- a genuinely ancient row from before that column
    # existed (see orchestrator_v3.py's own BENCHMARK_FIELDNAMES comment: "Rows written
    # before this column existed have it blank"). row.get("write_files") returns None,
    # which never equals the string "1", so this is skipped -- the SAFE default (never
    # silently trust an unmarked-legacy row as a confirmed real write).
    check(m.compute_totals_bumps_from_new_rows(legacy_row, before_count=0) == [],
          "a legacy row with no write_files column at all is treated as NOT a confirmed "
          "real write (skipped), not silently trusted")


def main():
    import primeatlas.generation as m
    from primeatlas.storage import digit_count_floor

    _test_compute_totals_bumps_from_new_rows()

    # === Hybrid argv contract: pure GUI-to-WSL command construction =====================
    # The backend itself lands in a later phase.  Pin the argument order now so neither
    # side can silently reinterpret k_adv as the old fixed-window Width multiplier.
    hybrid_argv = m.build_hybrid_argv(
        17, 3, 10_000, True,
        script_path=r"C:\PrimeAtlas\prime_sieve\hybrid_sieve.py")
    check(hybrid_argv == [
        "python3", "-u", "/mnt/c/PrimeAtlas/prime_sieve/hybrid_sieve.py",
        "17", "3", "10000", "1",
    ], f"build_hybrid_argv keeps the fixed CLI contract "
       f"<floor> <iterations> <filter_prime_count> <write_files>, got {hybrid_argv!r}")
    hybrid_count_only_argv = m.build_hybrid_argv(
        21, 1, 7, False,
        script_path=r"D:\work\hybrid_sieve.py")
    check(hybrid_count_only_argv[-4:] == ["21", "1", "7", "0"],
          f"build_hybrid_argv preserves a small explicit k_adv and count-only flag "
          f"without adding window-width arguments, got {hybrid_count_only_argv!r}")

    portal = tempfile.mkdtemp(prefix="primeatlas_gen_arith_test_")
    try:
        W = 10_000_000

        # === _round_range_to_window: plain floor/ceil rounding =========================
        check(m._round_range_to_window(12_000_000, 309_000_000) == (10_000_000, 310_000_000),
              "round_range_to_window widens a mid-window span out to whole windows")
        check(m._round_range_to_window(10_000_000, 20_000_000) == (10_000_000, 20_000_000),
              "round_range_to_window leaves an already-aligned span untouched")
        check(m._round_range_to_window(0, 1) == (0, 10_000_000),
              "round_range_to_window rounds a tiny span up to one full window, never zero")

        # === _floor_window_count: LOW_FLOOR_CUTOFF boundary + exact division ===========
        check(m._floor_window_count(6) is None,
              f"floor 6 (below LOW_FLOOR_CUTOFF={m.LOW_FLOOR_CUTOFF}) has no window-count "
              f"concept (got {m._floor_window_count(6)!r}, expected None)")
        check(m._floor_window_count(7) == 9,
              f"floor 7 = [10**7, 10**8), width 9*10**7 = 9 windows of 10**7 each "
              f"(got {m._floor_window_count(7)!r})")
        check(m._floor_window_count(8) == 90,
              f"floor 8 = [10**8, 10**9), width 9*10**8 = 90 windows "
              f"(got {m._floor_window_count(8)!r})")

        # === find_continuation_target_idx / count_existing_windows / gap detection =====
        _touch_window(portal, 10, 0)
        _touch_window(portal, 10, 1)
        _touch_window(portal, 10, 2)
        check(m.find_continuation_target_idx(portal, 10, W) == 3,
              "continuation target_idx is highest existing + 1 on a contiguous floor")
        check(m.count_existing_windows(portal, 10) == 3,
              "count_existing_windows is the real file count on a contiguous floor")
        check(m.find_first_gap_target_idx(portal, 10, W) == 3,
              "first-gap target_idx equals continuation target_idx when there is no gap")

        _touch_window(portal, 11, 0)
        _touch_window(portal, 11, 1)
        _touch_window(portal, 11, 4)  # windows 2,3 missing -- an interior gap
        check(m.find_continuation_target_idx(portal, 11, W) == 5,
              "continuation target_idx follows the HIGHEST file even past an interior gap")
        check(m.count_existing_windows(portal, 11) == 3,
              "count_existing_windows is the real file COUNT (3), not the continuation "
              "position (5) -- these must diverge once an interior gap exists (see "
              "count_existing_windows's own docstring on the 234-quintillion display bug "
              "this distinction was added to fix)")
        check(m.find_first_gap_target_idx(portal, 11, W) == 2,
              "first-gap target_idx finds the FIRST missing window (2), not the last (5)")

        # === _trim_existing_from_target_idx_range: edge trimming only ==================
        # floor 11 has windows {0,1,4}; request [0,6) should trim the front run {0,1} but
        # leave the interior gap (2,3) and the tail's already-existing window (4)
        # untouched in the MIDDLE -- trimming is edge-only by design (see the function's
        # own docstring: an interior overlap is harmlessly rewritten, not skipped).
        trimmed_start, trimmed_count = m._trim_existing_from_target_idx_range(
            portal, 11, 0, 6, W)
        check((trimmed_start, trimmed_count) == (2, 4),
              f"trim skips the front run {{0,1}} (start 0->2) but does NOT skip past the "
              f"interior gap at 2/3 or shrink the tail below the request's own end "
              f"(got start={trimmed_start}, count={trimmed_count}, expected start=2, "
              f"count=4 i.e. covering [2,6))")
        # request fully inside the existing front run -> nothing left to generate
        trimmed_start2, trimmed_count2 = m._trim_existing_from_target_idx_range(
            portal, 11, 0, 2, W)
        check(trimmed_count2 == 0,
              f"a request fully covered by existing windows trims to count=0 "
              f"(got start={trimmed_start2}, count={trimmed_count2})")
        # empty floor: nothing to trim
        trimmed_start3, trimmed_count3 = m._trim_existing_from_target_idx_range(
            portal, 99, 5, 3, W)
        check((trimmed_start3, trimmed_count3) == (5, 3),
              f"an empty floor trims nothing (got start={trimmed_start3}, "
              f"count={trimmed_count3}, expected start=5, count=3 unchanged)")

        # === digit_count_floor: power-of-10 boundaries (primeatlas.storage, unchanged by
        # the Generation-tab extraction -- imported separately here) ====================
        check(digit_count_floor(1) == 0, "digit_count_floor(1) == floor 0")
        check(digit_count_floor(9) == 0, "digit_count_floor(9) == floor 0 (still 1 digit)")
        check(digit_count_floor(10) == 1, "digit_count_floor(10) == floor 1 (rolls over)")
        check(digit_count_floor(100_000_000) == 8,
              "digit_count_floor(10**8) == floor 8 (the floor-7/floor-8 boundary itself)")

        if failures:
            print(f"\n{len(failures)} FAILURE(S)")
            return 1
        print("\nALL CHECKS PASSED")
        return 0
    finally:
        shutil.rmtree(portal, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
