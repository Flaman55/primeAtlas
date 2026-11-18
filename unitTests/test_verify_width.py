"""
test_verify_width.py -- primeatlas/generation/verify_width.py: the island Section D verifies
and the width of its verification windows. No tkinter.

Checks:
  - file width: the smallest gap between the floor's P offsets; one file (or none) gives the
    default 10^7;
  - island: the first run of P files on the file width's grid, each one file width after the
    previous, from the smallest n; a gap, a missing (D) file or an off-grid file ends it; the
    islands after it never count; the store's own island (D files, other floors ignored);
  - a first file wider than the guess (21): its last prime lies past the guessed width; its
    width is the smallest multiple of the guess past that prime that divides its offset, and
    it is an island of its own; the store's 10^8 file among 10^7 ones;
  - the v7.3 cap: half the free RAM x 30 numbers, whole files, at least one file; no reading
    gives the default 10^11;
  - the width range: one file up to the island, for v7.3 up to the cap too;
  - a typed width: any notation, below the minimum -> the minimum, above the maximum -> the
    maximum, between -> rounded down to whole files; text that is no number (or below 1) ->
    None;
  - windows: ceil(island / width), the last one holding the rest; the files of the first k
    windows never pass the island; each window's numbers;
  - the split (how many windows the island splits into) gives the width: ceil(files / split)
    files each, the split fitted to what whole files allow; the arrows step to the next split
    that changes the width and stop at both ends;
  - the short width text (1e7, 9e7, 2.5e8): exact, read back as the same width; never three
    digits after the point (read as a thousands group too): 83.34e9, not 8.334e10;
  - Auto: pt1.1 one file (the most windows); v7.3 the fewest windows the cap allows, split
    evenly (whole files, never above the cap); the same answer twice.

Usage:
    python unitTests/test_verify_width.py
"""
import os
import shutil
import sys
import tempfile

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

import storage_kinds  # noqa: E402
from primeatlas.generation import verify_plan, verify_width  # noqa: E402

failures = []
M7 = 10 ** 7
PROOF = verify_plan.METHOD_PROOF
SIEVE = verify_plan.METHOD_SIEVE


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _touch(portal, floor, offset, kind=storage_kinds.KIND_P):
    path = storage_kinds.window_path(portal, floor, offset, M7, f"{offset // 1_000_000}M", kind)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()


def _island(start, file_width, files):
    return verify_width.Island(start=start, file_width=file_width, files=files)


def _test_file_width():
    fw = verify_width.file_width
    check(fw([0, M7, 2 * M7]) == M7, "three files 10^7 apart: 10^7")
    check(fw([0, 10 ** 8, 2 * 10 ** 8, 21 * M7]) == M7,
          "the smallest gap counts (10^8 files, one 10^7 gap): 10^7")
    check(fw([5 * M7]) == verify_width.DEFAULT_FILE_WIDTH == M7, "one file: the default 10^7")
    check(fw([]) == M7, "no file: the default 10^7")
    check(fw([2 * M7, 0, M7]) == M7, "offsets in any order")


def _test_first_island():
    first = verify_width.first_island
    check(first([]) is None, "no file: no island")
    island = first([M7, 2 * M7, 3 * M7])
    check(island == _island(M7, M7, 3) and island.numbers == 3 * M7,
          f"three adjacent files: one island of 3 * 10^7 ({island})")
    island = first([0, M7, 2 * M7, 5 * M7, 6 * M7])
    check(island == _island(0, M7, 3), f"a gap ends the island, the next never counts ({island})")
    island = first([5 * M7, 6 * M7, 0, M7])
    check(island == _island(0, M7, 2), f"the island of the smallest n, any order ({island})")
    island = first([4 * M7])
    check(island == _island(4 * M7, M7, 1), f"one file: an island of one file ({island})")
    island = first([0, 10 ** 8, 2 * 10 ** 8])
    check(island == _island(0, 10 ** 8, 3), f"files of 10^8: width 10^8 ({island})")
    island = first([5_000_000, 3 * M7, 4 * M7])
    check(island == _island(3 * M7, M7, 2),
          f"an off-grid file is skipped, the island starts on the grid ({island})")
    island = first([0, 15_000_000, 2 * M7, 3 * M7])
    check(island == _island(0, 5_000_000, 1),
          f"a 5 * 10^6 gap makes the width 5 * 10^6 ({island})")


def _test_wider_first_file():
    first = verify_width.first_island
    b = 10 ** 9
    offsets = [5 * b, 51 * 10 ** 8, 511 * M7]       # a 10^8 file, then two of 10^7
    last = {5 * b: 10 ** 8 - 23, 51 * 10 ** 8: M7 - 9, 511 * M7: M7 - 49}
    island = first(offsets, last.get)
    check(island == _island(5 * b, 10 ** 8, 1),
          f"21: the first file's last prime past 10^7: a 10^8 file, alone ({island})")
    check(first(offsets) == _island(5 * b, M7, 1),
          "21: without reading the file: the guessed 10^7 (as before)")
    check(first([0, M7, 2 * M7], {0: M7 - 3}.get) == _island(0, M7, 3),
          "21: a last prime within the width: the island as guessed")
    check(first([0, 5 * 10 ** 8, 6 * 10 ** 8], {0: 2 * 10 ** 8 - 11}.get)
          == _island(0, 2 * 10 ** 8, 1),
          "21: offset 0: the smallest multiple past the last prime (2 * 10^8)")
    check(first([9 * 10 ** 8, 10 ** 9], {9 * 10 ** 8: 2 * 10 ** 8 - 11}.get)
          == _island(9 * 10 ** 8, 3 * 10 ** 8, 1),
          "21: the width divides the offset: 9 * 10^8 takes 3 * 10^8, not 2 * 10^8")
    check(first([0, M7], {0: None}.get) == _island(0, M7, 2),
          "21: an empty first file: the island as guessed")


def _write_window(portal, floor, offset, width, kind=storage_kinds.KIND_P):
    """A real PGS2 file whose primes stand in near the start and the end of `width`."""
    import numpy as np
    import pgs2_vector
    path = storage_kinds.window_path(portal, floor, offset, width,
                                     f"{offset // 1_000_000}M", kind)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pgs2_vector.write_prime_window_offsets(path, 10 ** floor + offset,
                                           np.array([1, 7, width - 3], dtype=np.int64))
    return path


def _test_store_wider_first_file():
    portal = tempfile.mkdtemp(prefix="primeatlas_verify_width_test_")
    try:
        b = 10 ** 9
        wide = _write_window(portal, 31, 5 * b, 10 ** 8)
        _write_window(portal, 31, 51 * 10 ** 8, M7)
        _write_window(portal, 31, 511 * M7, M7)
        island = verify_width.store_island(portal, 31)
        check(island == _island(5 * b, 10 ** 8, 1),
              f"21: the store's 10^8 file among 10^7 ones: its own island of 10^8 ({island})")
        os.remove(wide)
        island = verify_width.store_island(portal, 31)
        check(island == _island(51 * 10 ** 8, M7, 2),
              f"21: once it is gone, the two 10^7 files ({island})")
        _write_window(portal, 32, 0, 10 ** 8)
        _write_window(portal, 32, 10 ** 8, 10 ** 8)
        island = verify_width.store_island(portal, 32)
        check(island == _island(0, 10 ** 8, 2),
              f"21: 10^8 files whose gaps tell the width: no change ({island})")
    finally:
        shutil.rmtree(portal, ignore_errors=True)


def _test_store_island():
    portal = tempfile.mkdtemp(prefix="primeatlas_verify_width_test_")
    try:
        for offset in (M7, 2 * M7, 4 * M7, 5 * M7):
            _touch(portal, 29, offset)
        _touch(portal, 29, 3 * M7, storage_kinds.KIND_D)
        _touch(portal, 29, 0, storage_kinds.KIND_D)
        _touch(portal, 30, 0)
        island = verify_width.store_island(portal, 29)
        check(island == _island(M7, M7, 2),
              f"the store: a D file between ends the island, D files never count ({island})")
        check(verify_width.store_island(portal, 30) == _island(0, M7, 1),
              "floor 30 has its own island")
        check(verify_width.store_island(portal, 31) is None, "a floor without a folder: None")
        check(verify_width.store_island(portal, None) is None, "no floor: None")
        check(verify_width.store_island("", 29) is None, "no storage folder: None")
    finally:
        shutil.rmtree(portal, ignore_errors=True)


def _test_sieve_cap():
    cap = verify_width.sieve_cap
    gib = 1024 ** 3
    want = int(8 * gib * 0.5 * 30) // M7 * M7
    check(cap(8 * gib, M7) == want, f"8 GiB free: half of it x 30, whole files ({cap(8 * gib, M7)})")
    check(cap(None, M7) == verify_width.DEFAULT_SIEVE_CAP == 10 ** 11,
          "no reading: the default 10^11")
    check(cap(0, M7) == 10 ** 11, "a zero reading: the default 10^11")
    check(cap(100, M7) == M7, "too little RAM still gives one file")
    check(cap(None, 3 * M7) == 3333 * 3 * M7,
          "the default rounds down to whole files of 3 * 10^7")


def _test_width_range():
    rng = verify_width.width_range
    island = _island(0, M7, 30)
    check(rng(island, PROOF, 10 ** 8) == (M7, 3 * 10 ** 8), "pt1.1: one file up to the island")
    check(rng(island, SIEVE, 10 ** 8) == (M7, 10 ** 8), "v7.3: up to the RAM cap")
    check(rng(island, SIEVE, 10 ** 11) == (M7, 3 * 10 ** 8),
          "v7.3 with a cap above the island: up to the island")


def _test_fit_width():
    fit = verify_width.fit_width
    island = _island(0, M7, 30)
    check(fit("1e8", island, PROOF, 10 ** 11) == 10 ** 8, "1e8 as typed")
    check(fit("100 000 000", island, PROOF, 10 ** 11) == 10 ** 8, "100 000 000 as typed")
    check(fit("10^8", island, PROOF, 10 ** 11) == 10 ** 8, "10^8 as typed")
    check(fit("1000", island, PROOF, 10 ** 11) == M7, "below one file: one file")
    check(fit("1e12", island, PROOF, 10 ** 11) == 3 * 10 ** 8, "above the island: the island")
    check(fit("2e8", island, SIEVE, 10 ** 8) == 10 ** 8, "v7.3 above the cap: the cap")
    check(fit("25000000", island, PROOF, 10 ** 11) == 2 * M7,
          "between: rounded down to whole files")
    check(fit("29999999", island, PROOF, 10 ** 11) == 2 * M7, "just below 3 files: 2 files")
    for text in ("", "abc", "0", "1,5", "-5", None):
        check(fit(text, island, PROOF, 10 ** 11) is None, f"{text!r} is no width")


def _test_windows():
    island = _island(0, M7, 25)
    total = verify_width.window_total
    check(total(island, M7) == 25, "25 files, width one file: 25 windows")
    check(total(island, 10 ** 8) == 3, "25 files, width 10 files: 3 windows (10 + 10 + 5)")
    check(total(island, 25 * M7) == 1, "the whole island: 1 window")
    files = verify_width.files_for
    check(files(island, 10 ** 8, 1) == 10, "the first window: 10 files")
    check(files(island, 10 ** 8, 2) == 20, "two windows: 20 files")
    check(files(island, 10 ** 8, 3) == 25, "every window: the island's 25, not 30")
    check(files(island, 10 ** 8, 7) == 25, "more windows than there are: the island")
    sizes = verify_width.window_sizes
    check(sizes(island, 10 ** 8, 3) == [10 ** 8, 10 ** 8, 5 * M7],
          "window numbers: the last holds the rest")
    check(sizes(island, 10 ** 8, 1) == [10 ** 8], "the first window only")
    check(sizes(None, 10 ** 8, 3) == [] and total(None, 10 ** 8) == 0, "no island: nothing")


def _test_width_text():
    text = verify_width.width_text
    for width, want in ((M7, "1e7"), (10 ** 8, "1e8"), (9 * M7, "9e7"),
                        (25 * M7, "2.5e8"), (8334 * M7, "83.34e9"), (1234 * M7, "12.34e9"), (5_000_000, "5e6"),
                        (10 ** 11, "1e11"), (123_456_789, "1.23456789e8"), (7, "7e0")):
        shown = text(width)
        check(shown == want and verify_width.fit_width(
            shown, _island(0, 1, 10 ** 12), PROOF, 10 ** 12) == width,
              f"width_text({width}) = {want}, read back exactly ({shown!r})")


def _test_split():
    split = verify_width.width_for_split
    island = _island(0, M7, 10)
    check(split("2", island, PROOF, 10 ** 11) == 5 * M7, "split 2 of 10 files: 5 files each")
    check(split("3", island, PROOF, 10 ** 11) == 4 * M7, "split 3: 4 files each (4 + 4 + 2)")
    check(split("10", island, PROOF, 10 ** 11) == M7, "split 10: one file each")
    check(split("1", island, PROOF, 10 ** 11) == 10 * M7, "split 1: the whole island")
    check(split("50", island, PROOF, 10 ** 11) == M7, "a split above the files: one file each")
    width = split("6", island, PROOF, 10 ** 11)
    check(width == 2 * M7 and verify_width.window_total(island, width) == 5,
          f"split 6 of 10 files cannot be made: 2 files each, 5 windows ({width})")
    check(split("1", island, SIEVE, 3 * M7) == 3 * M7
          and verify_width.window_total(island, 3 * M7) == 4,
          "v7.3, a cap of 3 files: split 1 becomes the fewest the cap allows (4)")
    check(split("1e1", island, PROOF, 10 ** 11) == M7, "any notation: 1e1 = 10")
    for text in ("", "abc", "0", "1,5", None):
        check(split(text, island, PROOF, 10 ** 11) is None, f"split {text!r} is no split")

    step = verify_width.step_split
    totals = []
    width = 10 * M7
    for _ in range(11):
        width = step(island, width, 1, PROOF, 10 ** 11)
        totals.append(verify_width.window_total(island, width))
    check(totals == [2, 3, 4, 5, 10, 10, 10, 10, 10, 10, 10],
          f"split up from 1: every step a new split, no stand-still, stops at 10 ({totals})")
    totals = []
    for _ in range(6):
        width = step(island, width, -1, PROOF, 10 ** 11)
        totals.append(verify_width.window_total(island, width))
    check(totals == [5, 4, 3, 2, 1, 1], f"split down from 10, stops at 1 ({totals})")
    width = step(island, 3 * M7, -1, SIEVE, 3 * M7)
    check(width == 3 * M7, f"v7.3: down at the cap's split stays ({width})")


def _test_auto_width():
    auto = verify_width.auto_width
    island = _island(0, M7, 25_000)       # 2.5 * 10^11 numbers
    check(auto(island, PROOF, 10 ** 11) == M7, "pt1.1: one file, the most windows")
    width = auto(island, SIEVE, 10 ** 11)
    check(width == 8334 * M7 and verify_width.window_total(island, width) == 3,
          f"v7.3: 2.5 * 10^11 with a cap of 10^11: 3 even windows of 8334 files ({width})")
    check(auto(island, SIEVE, 10 ** 11) == width, "the same answer twice")
    small = _island(0, M7, 7)
    check(auto(small, SIEVE, 10 ** 11) == 7 * M7, "v7.3, the island under the cap: one window")
    odd = _island(0, M7, 10)
    width = auto(odd, SIEVE, 3 * M7)
    check(width == 3 * M7 and verify_width.window_total(odd, width) == 4,
          f"v7.3, 10 files, a cap of 3: 4 windows of 3 files, never above the cap ({width})")
    check(auto(None, SIEVE, 10 ** 11) is None, "no island: no width")


def main():
    _test_file_width()
    _test_first_island()
    _test_store_island()
    _test_wider_first_file()
    _test_store_wider_first_file()
    _test_sieve_cap()
    _test_width_range()
    _test_fit_width()
    _test_windows()
    _test_width_text()
    _test_split()
    _test_auto_width()
    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
