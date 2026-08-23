"""
research_goldbach.py -- pure-logic (no tkinter) storage-bridging layer for the
Research tab's Goldbach sub-tab, extracted from prime_atlas_v1.py during the refactor
branch's Faza 3 (tab-by-tab backend/UI split, 2026-08-23), alongside the tab's own UI
split (see research_goldbach_tab.py's own docstring).

This module holds ONLY the piece that turns on-disk floor storage into an is_prime
array for goldbach_window.py's pure math functions to consume -- goldbach_window.py
itself (check_window/window_rows/all_decompositions/both_base_window_rows/
sieve_is_prime/largest_prime_le) is untouched and stays exactly where it was; nothing
here duplicates it.
"""
import prime_sieve_v1

from .storage import list_source_filenames, _offset_from_filename

QUICK_GEN_MAX_WINDOW_WIDTH = 10_000_000
"""Window width storage files are split into -- duplicated from prime_atlas_v1.py's own
module-level constant of the same name (see that file's own comment on why it's
duplicated rather than imported: this module must not import back from
prime_atlas_v1.py, which would be circular). Safe as long as window_m stays at its
default value everywhere it's independently defined (as in DEFAULT_GENERATION_SETTINGS)
-- same known limitation as the original."""


def _safe_prime_gap_margin(x):
    """Generous upper bound on the largest prime gap below x, used only to decide
    whether a storage window's sweep plausibly reached x -- real maximal gaps are much
    smaller (see e.g. Tomas Oliveira e Silva's maximal-gap tables: 34 below 10**5, 148
    below 10**7, 282 below 10**9); these constants are deliberately generous, not tight,
    since erring "too strict" only costs an extra generate-more-data prompt, while erring
    "too loose" would silently trust incomplete data (exactly the bug this function
    exists to prevent -- see read_is_prime_from_storage's own docstring)."""
    for threshold, margin in (
        (100, 10), (1_000, 20), (10_000, 40), (100_000, 80),
        (1_000_000, 150), (10_000_000, 250), (2 ** 63, 400),
    ):
        if x < threshold:
            return margin
    return 400


class MissingStorageRangeError(Exception):
    """Raised by read_is_prime_from_storage when floor `floor` does not (yet) hold
    verified data up to `needed_upto`. Carries both fields as attributes so the caller
    can build a message naming the SPECIFIC floor that's short, rather than a generic
    "storage is missing" message pointing at floor 0 regardless of which floor is
    actually the problem (see read_is_prime_from_storage's own docstring for the bug
    this replaced)."""

    def __init__(self, floor, needed_upto):
        self.floor = floor
        self.needed_upto = needed_upto
        super().__init__(f"floor {floor} missing data up to {needed_upto}")


def read_is_prime_from_storage(portal_folder, limit):
    """Builds an is_prime bytearray covering [0, limit] purely from already-generated
    floor storage (10p{N}/source_primes/PRIME_WINDOW_*.bin, PGS2 format -- see
    prime_sieve_v1.py's own format header) instead of running a fresh sieve. Used by
    the Goldbach tab's Wizualizacja feature (see research_goldbach_tab.py's
    _on_goldbach_visualize), per Artur's explicit instruction that this computation
    should read from the magazyn rather than recompute -- the per-n witness search
    itself still runs the exact same algorithm as goldbach_window.py's window_rows(),
    only the SOURCE of is_prime changes.

    Floors are NOT one continuous span starting at floor 0 -- each floor N covers only
    its own natural range [10**N, 10**(N+1)) (width 9*10**N), the same boundary
    enforced elsewhere by _floor_window_count()/the range-clamping logic around
    "floor_boundary = 10 ** (floor_lo + 1)", and by prime_sieve_v4_1._low_floor_
    segments(). floor 0 = [1,10) (4 primes: 2,3,5,7), floor 1 = [10,100) (21 primes),
    floor 2 = [100,1000) (143 primes), and so on -- this matches the real counts
    Artur's own storage reports. An EARLIER version of this function wrongly treated
    floor 0 alone as extending indefinitely in QUICK_GEN_MAX_WINDOW_WIDTH-wide chunks
    (i.e. as if floor 0 covered [1,10_000_001)), so e.g. limit=200 was checked
    entirely against floor 0's single tiny file and failed even though floors 0-2 were
    each genuinely complete -- Artur caught this ("piętro zero nigdy nie będzie miało
    100... wartość 100 jest na piętrze 2"). This version instead walks floor 0, 1, 2,
    ... up to whichever floor's base exceeds limit, reading each floor's OWN files
    (possibly split into QUICK_GEN_MAX_WINDOW_WIDTH-wide window files only when a
    floor's natural width exceeds that, per prime_sieve_v1.main_batch_scanner()) and
    stitching their primes into one array.

    A window FILE existing on disk at the right offset does not by itself prove it
    actually covers the range needed -- a partial/test/interrupted-generation file can
    sit at offset 0 with only a handful of primes in it (this happened: Artur's
    storage_path at the time had exactly such a file, and an earlier version of this
    function trusted its mere existence, silently building an is_prime array that read
    as "mostly composite" above the file's real content and rendered a Wizualizacja
    diagram full of "?" instead of an honest error). So for every window needed, this
    also checks that the MAXIMUM prime actually found in that file reaches within
    _safe_prime_gap_margin() of the range it's relied on for -- short of that, the
    window is treated as not-yet-generated, same as if the file were simply missing.

    Returns an is_prime bytearray of length limit+1 if every floor needed to cover
    [0, limit] is present AND actually reaches far enough within itself; raises
    MissingStorageRangeError(floor, needed_upto) naming the SPECIFIC short floor
    otherwise -- never partially or silently truncates (a silent gap would make a
    "covered" verdict meaningless)."""
    window_m = QUICK_GEN_MAX_WINDOW_WIDTH
    if limit < 2:
        return bytearray(limit + 1)

    is_prime = bytearray(limit + 1)
    floor = 0
    while 10 ** floor <= limit:
        base = 10 ** floor
        floor_boundary = 10 ** (floor + 1)  # exclusive natural ceiling of this floor
        needed_here_top = min(limit, floor_boundary - 1)
        highest_needed_idx = (needed_here_top - base) // window_m

        files_by_idx = {}
        for name, path in list_source_filenames(portal_folder, floor):
            offset = _offset_from_filename(name)
            if offset is None:
                continue
            files_by_idx[offset // window_m] = path

        for idx in range(highest_needed_idx + 1):
            if idx not in files_by_idx:
                raise MissingStorageRangeError(floor, needed_here_top)

        for idx in range(highest_needed_idx + 1):
            window_end = base + (idx + 1) * window_m  # exclusive nominal upper bound
            needed_here = min(needed_here_top, window_end - 1)
            window_max_prime = 0
            for p in prime_sieve_v1.read_prime_window(files_by_idx[idx]):
                if p > window_max_prime:
                    window_max_prime = p
                if p <= limit:
                    is_prime[p] = 1
            margin = _safe_prime_gap_margin(max(needed_here, 2))
            if window_max_prime < needed_here - margin:
                raise MissingStorageRangeError(floor, needed_here_top)

        floor += 1
    return is_prime
