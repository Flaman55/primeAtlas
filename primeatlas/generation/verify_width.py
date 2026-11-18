"""
verify_width.py -- the island Generation Section D verifies and the width of its verification
windows. No tkinter.

A P file's name holds its offset only, not its width, so the file width of a floor is the
smallest gap between its P offsets (DEFAULT_FILE_WIDTH, the narrowest width the engines write,
for a single file). The island is the first run of P files on that width's grid, each one file
width after the previous, from the smallest n: a gap, a file moved to D or a file of another
width ends it. The store verifiers take the floor's P windows on the grid in offset order, so
the first files they take are the island's.

The smallest gap can belong to narrower files further on (a 10^8 file followed by 10^7 ones),
so the island's first file is read: when its last prime lies past the guessed width, the file
is wider. A file starts on its own width's grid (offset = index x width), so its width is the
smallest multiple of the guess past that prime that divides its offset, and it is an island of
its own: the files after it cannot be told apart by their names. A file wider than the guess
in the middle of an island is skipped by the verification (store_verify.settle()) and becomes
the next island's first file. One file is read per recount, remembered by path and mtime.

A verification window is a whole number of files, from one file up to the island; for the v7.3
sieve also up to its RAM cap (its wheel buffer takes 1 byte per 30 numbers, given a
run_budget.DEFAULT_SAFETY_FRACTION share of the free RAM, the rest left to v7.2's buckets).
The island splits into ceil(island / width) windows, the last one holding the rest. Auto picks
the width: pt1.1 one file (the most windows: its time hardly depends on the width, and small
portions can be verified one at a time); v7.3 the fewest windows under the cap, split evenly.
"""
import math
import os
from dataclasses import dataclass

import prime_sieve_v1
import run_verify
import storage_kinds

from . import run_budget
from ..core.number_text import plain_number

DEFAULT_FILE_WIDTH = 10_000_000
DEFAULT_SIEVE_CAP = run_verify.DEFAULT_PASS_NUMBERS
NUMBERS_PER_BYTE = 30


@dataclass(frozen=True)
class Island:
    start: int
    file_width: int
    files: int

    @property
    def numbers(self):
        return self.files * self.file_width


def width_text(numbers):
    """`numbers` in the short exact form the Width field shows: 1e7, 9e7, 2.5e8. Three digits
    after the point read as a thousands group too (core.number_text: 8.334 or 8334), so such a
    number keeps two digits before the point instead: 83.34e9."""
    digits = str(numbers)
    significant = digits.rstrip("0")
    lead = 2 if len(significant) == 4 else 1
    mantissa = significant[:lead] + ("." + significant[lead:] if len(significant) > lead else "")
    return f"{mantissa}e{len(digits) - lead}"


def file_width(offsets):
    """The smallest gap between `offsets` (any order), DEFAULT_FILE_WIDTH for fewer than two."""
    ordered = sorted(set(offsets))
    gaps = [b - a for a, b in zip(ordered, ordered[1:])]
    return min(gaps) if gaps else DEFAULT_FILE_WIDTH


def _wider_width(offset, last_prime, guess):
    """The smallest multiple of `guess` past last_prime that divides `offset` (0: any)."""
    width = (last_prime // guess + 1) * guess
    while offset and offset % width:
        width += guess
    return width


def first_island(offsets, last_prime_of=None):
    """The Island of `offsets` (P file offsets, any order), None without one.
    last_prime_of(offset): the last prime of that file as an offset from its start (None for
    an empty file); without it the guessed width stands."""
    width = file_width(offsets)
    on_grid = sorted({offset for offset in offsets if offset % width == 0})
    if not on_grid:
        return None
    last = last_prime_of(on_grid[0]) if last_prime_of is not None else None
    if last is not None and last >= width:
        return Island(start=on_grid[0], file_width=_wider_width(on_grid[0], last, width),
                      files=1)
    files = 1
    while files < len(on_grid) and on_grid[files] == on_grid[0] + files * width:
        files += 1
    return Island(start=on_grid[0], file_width=width, files=files)


_last_prime_cache = {}


def _last_prime_offset(path, lo):
    """The last prime of the window file at `path` minus lo; None for an empty or unreadable
    file (the guessed width stands, the verification reports the file)."""
    try:
        key = (path, os.path.getmtime(path))
        if key not in _last_prime_cache:
            primes = prime_sieve_v1.read_prime_window(path)
            _last_prime_cache[key] = primes[-1] - lo if primes else None
    except (OSError, ValueError):
        return None
    return _last_prime_cache[key]


def store_island(portal_folder, base_exponent):
    """first_island() of the floor's P store, its first file read; None without a floor, a
    store or a P file."""
    if base_exponent is None or not portal_folder:
        return None
    paths = {}
    for name, path in storage_kinds.list_window_files(portal_folder, base_exponent,
                                                      storage_kinds.KIND_P):
        offset = storage_kinds.offset_from_name(name)
        if offset is not None:
            paths[offset] = path
    base = 10 ** base_exponent
    return first_island(list(paths),
                        lambda offset: _last_prime_offset(paths[offset], base + offset))


def sieve_cap(free_ram_bytes, width_of_file):
    """The widest v7.3 window the free RAM allows, in whole files of width_of_file, at least
    one; DEFAULT_SIEVE_CAP (whole files) without a reading."""
    if free_ram_bytes and free_ram_bytes > 0:
        numbers = int(free_ram_bytes * run_budget.DEFAULT_SAFETY_FRACTION * NUMBERS_PER_BYTE)
    else:
        numbers = DEFAULT_SIEVE_CAP
    return sieve_cap_files(numbers, width_of_file)


def width_range(island, method, cap):
    """(minimum, maximum) width of `island`'s windows: one file up to the island, for the v7.3
    sieve not above `cap` (numbers) either."""
    maximum = island.numbers
    if method == run_verify.METHOD_SIEVE:
        maximum = min(maximum, sieve_cap_files(cap, island.file_width))
    return island.file_width, maximum


def sieve_cap_files(cap, width_of_file):
    """`cap` numbers rounded down to whole files, at least one."""
    return max(width_of_file, cap // width_of_file * width_of_file)


def fit_width(text, island, method, cap):
    """The width a typed text stands for: below the range its minimum, above it its maximum,
    between rounded down to whole files. None for text that is no whole number >= 1."""
    text = plain_number(text or "")
    if not text.isdigit() or int(text) < 1:
        return None
    minimum, maximum = width_range(island, method, cap)
    return max(minimum, min(maximum, int(text) // island.file_width * island.file_width))


def split_range(island, method, cap):
    """(fewest, most) windows the island can split into: the widest window, one file each."""
    _minimum, maximum = width_range(island, method, cap)
    return window_total(island, maximum), island.files


def _even_width(island, split):
    return math.ceil(island.files / split) * island.file_width


def width_for_split(text, island, method, cap):
    """The width a typed split (how many windows) stands for: ceil(files / split) files each,
    the split taken into its range first. None for text that is no whole number >= 1."""
    text = plain_number(text or "")
    if not text.isdigit() or int(text) < 1:
        return None
    fewest, most = split_range(island, method, cap)
    return _even_width(island, max(fewest, min(most, int(text))))


def step_split(island, width, direction, method, cap):
    """An arrow on the split (+1 more windows, -1 fewer): the width of the next split that
    changes the window count; `width` itself at either end."""
    fewest, most = split_range(island, method, cap)
    current = window_total(island, width)
    split = current + direction
    while fewest <= split <= most:
        stepped = _even_width(island, split)
        if window_total(island, stepped) != current:
            return stepped
        split += direction
    return width


def window_total(island, width):
    """How many windows of `width` numbers the island splits into (0 without an island)."""
    if island is None:
        return 0
    return math.ceil(island.files / (width // island.file_width))


def files_for(island, width, windows):
    """The files of the first `windows` windows, never more than the island holds."""
    return min(island.files, windows * (width // island.file_width))


def window_sizes(island, width, windows):
    """The numbers of each of the first `windows` windows ([] without an island)."""
    if island is None:
        return []
    per_window = width // island.file_width
    sizes = []
    left = files_for(island, width, windows)
    while left > 0:
        files = min(per_window, left)
        sizes.append(files * island.file_width)
        left -= files
    return sizes


def auto_width(island, method, cap):
    """Auto's width: one file for the pt1.1 proof; for the v7.3 sieve the fewest windows under
    the cap, split evenly in whole files. None without an island."""
    if island is None:
        return None
    if method != run_verify.METHOD_SIEVE:
        return island.file_width
    _minimum, maximum = width_range(island, method, cap)
    windows = math.ceil(island.files / (maximum // island.file_width))
    return math.ceil(island.files / windows) * island.file_width
