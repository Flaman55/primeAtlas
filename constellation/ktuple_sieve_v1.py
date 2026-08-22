"""
ktuple_sieve_v1.py -- targeted k-tuple ("constellation") candidate sieve, complementary
to constellation_finder_v1.py.

WHY THIS EXISTS: constellation_finder_v1.py finds k-tuples by pattern-matching against
windows that prime_sieve_v1/prime_sieve_primesieve.py have ALREADY fully sieved (every
prime in the window, via primesieve). That's the right tool when you already want every
prime in a range for other reasons, but it's the wrong tool for hunting a single sparse
pattern deep in a wide floor: a k=15 pattern's singular-series density at floor ~25 is on
the order of 1e-21..1e-22 per integer, so fully sieving a range wide enough to have a
realistic chance of a hit (~1e20-1e21 wide) would take a FULL prime sieve engine
centuries even at this app's own measured floor-25 throughput -- the bottleneck isn't the
per-window sieve cost (that's genuinely cheap, ~0.18s/1e7-window even at floor 25), it's
that there are simply too many windows to visit at all.

This module instead builds a small explicit residue WHEEL (via CRT over a handful of
small primes) for the pattern's own offsets: for each wheel prime p, at least one of the
k members is FORCED divisible by p for most residues of the window's starting position n
mod p (since k=15's offsets already span most residues mod any small p -- see
build_wheel()'s own docstring), so the overwhelming majority of positions can be
DIRECTLY SKIPPED (via striding by the wheel modulus) rather than ever touched. What
survives the wheel is filtered further by incremental trial division (early-exit) against
deeper primes, and only the tiny remainder -- individual integers, not whole windows --
gets real primality-tested (Miller-Rabin; numbers in play here are a few dozen to ~100
bits, trivially cheap to test individually regardless of how many survive).

This is deterministic and exact at every stage before the final Miller-Rabin call: a
position is only ever ELIMINATED because one of its k members is PROVABLY divisible by a
small prime (hence composite, barring the trivial n+d==p edge case, guarded for
explicitly) -- so no true k-tuple is ever silently skipped by the wheel or trial-division
stages. Only the final Miller-Rabin step is probabilistic (standard rounds=40 default,
error probability < 4**-40), same trust level the rest of this app already uses
elsewhere (see primeatlas/primality.py's own miller_rabin_test, which this deliberately
mirrors in miniature -- duplicated rather than imported since this script runs standalone
inside WSL, same self-contained pattern as constellation_finder_v1.py/prime_sieve_v1.py,
with no dependency on the primeatlas/ Windows-side package).

Because this mode never needs a pre-existing PRIME_WINDOW_*.bin for the locations it
scans (it works directly off raw integer ranges), it's independent of prime_sieve's own
generation pipeline and CHECKPOINT.txt -- confirmed hits are written into the SAME
per-(k,variant) hit-file format constellation_finder_v1.py uses (via that module's own
hit_file_path()/_append_hits_deduped()), so the rest of the portal (browsing, search)
needs no changes at all to pick these up.

CHECKPOINTING (added 2026-08-19, at Artur's request): every strategy except manual_list
reduces to the same striding mechanism (see stride_locations()) -- n_locations windows
spaced `step` apart, starting at a floor-relative offset persisted per (floor, k,
variant) in its own KTUPLE_CHECKPOINT_*.txt file (read_ktuple_checkpoint()/
write_ktuple_checkpoint()). A plain run (auto=False) scans one batch and updates the
checkpoint, so the next run continues rather than re-scanning; run_ktuple_job(auto=True)
keeps looping batch after batch, checkpointing after each, until a confirmed hit turns
up, the caller's should_stop() fires, or the floor is exhausted.

DIGIT SWEEP (added 2026-08-19, at Artur's request): a 5th location strategy alongside
even/concentrated/manual_step/manual_list -- see digit_sweep_locations() for the full
design note. In one sentence: instead of crawling the floor linearly, it drills through
the floor's own digit positions (coarsest first) so a single n_locations-sized batch
samples the ENTIRE magnitude range of the floor at once, nesting deeper into one
committed digit branch (default: always "...1") at each successive, finer position --
exactly mirroring Artur's own worked example (10000, 20000, ..., 90000, then 11000,
12000, ..., 19000, then 11100, 11200, ..., 11900, ...). Extra per-position budget beyond
one window per digit value is spent as a CONTIGUOUS block right at that digit's own
offset (denser, not wider, coverage there), per his own follow-up clarification.
Continuation between batches does NOT shift a floor-relative offset the way the other
three strategies do (that corrupted the digit alignment -- see run_ktuple_job()'s own
docstring for the incident and fix) -- instead a pass_counter increments by 1 each
batch, and each position derives ITS OWN committed digit from it (a different small
step per position -- see digit_sweep_locations()'s PATH VARIETY note), so the explored
path looks mixed/scrambled (e.g. "53254553452543") rather than a single repeated digit,
while staying fully deterministic and always starting from a clean, unshifted anchor.
"""
import math
import random


# ------------------------------------------------------------------------------------------
# Miller-Rabin -- minimal standalone copy of primeatlas/primality.py's own
# miller_rabin_test(), trimmed to just the True/False verdict (no certainty label needed
# here). See this module's own docstring for why it's duplicated rather than imported.
# ------------------------------------------------------------------------------------------

_MR_DETERMINISTIC_WITNESSES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37]
_MR_DETERMINISTIC_LIMIT = 3317044064679887385961981  # ~3.3e24 -- see primality.py


def _miller_rabin_round(n, a, d, r):
    x = pow(a, d, n)
    if x == 1 or x == n - 1:
        return True
    for _ in range(r - 1):
        x = pow(x, 2, n)
        if x == n - 1:
            return True
    return False


def is_probable_prime(n, rounds=40):
    if n < 2:
        return False
    for p in _MR_DETERMINISTIC_WITNESSES:
        if n == p:
            return True
        if n % p == 0:
            return False
    d = n - 1
    r = 0
    while d % 2 == 0:
        d //= 2
        r += 1
    if n < _MR_DETERMINISTIC_LIMIT:
        for a in _MR_DETERMINISTIC_WITNESSES:
            if a >= n:
                continue
            if not _miller_rabin_round(n, a, d, r):
                return False
        return True
    for _ in range(rounds):
        a = random.randrange(2, n - 1)
        if not _miller_rabin_round(n, a, d, r):
            return False
    return True


# ------------------------------------------------------------------------------------------
# Small prime generation (pure Python sieve -- deep_prime_limit is at most a few million,
# instant either way, no external dependency needed).
# ------------------------------------------------------------------------------------------

def primes_upto(limit):
    """Simple sieve of Eratosthenes, ascending list of primes <= limit."""
    if limit < 2:
        return []
    sieve = bytearray([1]) * (limit + 1)
    sieve[0] = sieve[1] = 0
    for p in range(2, math.isqrt(limit) + 1):
        if sieve[p]:
            sieve[p * p::p] = bytearray(len(sieve[p * p::p]))
    return [i for i, is_p in enumerate(sieve) if is_p]


# ------------------------------------------------------------------------------------------
# Wheel construction (CRT over a handful of small primes).
# ------------------------------------------------------------------------------------------

def _crt_pair(r1, m1, r2, m2):
    """x == r1 (mod m1), x == r2 (mod m2), 0 <= x < m1*m2 -- m1, m2 coprime."""
    m1_inv = pow(m1, -1, m2)
    return (r1 + m1 * ((r2 - r1) * m1_inv % m2)) % (m1 * m2)


def build_wheel(offsets, wheel_primes):
    """For each wheel prime p, a residue r (mod p) is BAD if some offset d makes
    (r + d) % p == 0 -- i.e. starting at n === r (mod p) forces member n+d divisible by
    p. Since k=15-style patterns already span most residues mod small p (their offsets
    are spread across [0, 56] -- for p > 56 every offset is automatically distinct mod
    p, and even for p <= 56 most are), only a small fraction of residues mod p survive.
    Combining survivors across several small primes via CRT compounds this fast (e.g.
    for k15 variant 4: mod 2 alone already halves the space, mod 2*3*5*7*11*13=30030
    leaves ~1 in 30030). Returns (M, sorted_surviving_residues)."""
    M = 1
    residues = [0]
    for p in wheel_primes:
        bad = set((-d) % p for d in offsets)
        good_mod_p = [r for r in range(p) if r not in bad]
        new_residues = [_crt_pair(r, M, gp, p) for r in residues for gp in good_mod_p]
        residues = new_residues
        M *= p
    residues.sort()
    return M, residues


def default_wheel_primes(offsets, max_M=100_000):
    """Greedily picks small primes (2, 3, 5, 7, ...) to include in the explicit wheel,
    stopping just before the combined modulus M would exceed max_M -- keeps the
    surviving-residue table (len(residues), used to stride every window) small enough
    to build/iterate cheaply, while still capturing most of the wheel's benefit (see
    build_wheel()'s own docstring -- returns diminish fast past the first several
    primes, per Mertens' theorem)."""
    chosen = []
    M = 1
    for p in primes_upto(97):
        if M * p > max_M:
            break
        chosen.append(p)
        M *= p
    return chosen


# ------------------------------------------------------------------------------------------
# Per-window candidate extraction.
# ------------------------------------------------------------------------------------------

def _survives_trial_division(n, offsets, deep_primes):
    for p in deep_primes:
        r = n % p
        for d in offsets:
            if (r + d) % p == 0 and n + d != p:  # n+d==p guard: trivial, never hit at the
                return False                      # magnitudes this module targets, kept
                                                    # for correctness at any scale anyway
    return True


def scan_window_for_candidates(base, window_m, offsets, wheel_M, wheel_residues, deep_primes):
    """Scans [base, base+window_m) for positions n surviving both the wheel and the
    deep-prime trial-division filter. Returns a list of surviving n (still need real
    primality verification of all k members -- see verify_candidates())."""
    candidates = []
    for r in wheel_residues:
        n = base + ((r - base) % wheel_M)
        while n < base + window_m:
            if _survives_trial_division(n, offsets, deep_primes):
                candidates.append(n)
            n += wheel_M
    candidates.sort()
    return candidates


def verify_candidates(candidates, offsets, rounds=40):
    """Real primality verification of survivors -- returns the sorted subset of
    `candidates` for which EVERY member (n+d for d in offsets) is prime."""
    hits = []
    for n in candidates:
        if all(is_probable_prime(n + d, rounds=rounds) for d in offsets):
            hits.append(n)
    return hits


# ------------------------------------------------------------------------------------------
# Hardy-Littlewood density -- used only to size a SUGGESTED fragment for the
# "concentrated" location strategy (select_locations() below); never affects
# correctness of the sieve itself, only how wide a slice is worth searching for a
# reasonable chance of a hit.
# ------------------------------------------------------------------------------------------

def singular_series_constant(offsets, k, limit=200_000):
    """C_k for this specific pattern: product over primes p of
    (1 - w(p)/p) / (1 - 1/p)**k, where w(p) = number of distinct residues the offsets
    occupy mod p. Converges quickly (grows/shrinks by ever-smaller factors past the
    first few hundred primes) -- limit=200_000 is already good to ~4-5 significant
    figures for k=15-sized patterns; raise it for more precision at real compute cost
    (primes_upto() is O(limit), one-off, cheap even at limit=2_000_000)."""
    log_c = 0.0
    for p in primes_upto(limit):
        w = len(set(o % p for o in offsets))
        if w >= p:
            return 0.0  # inadmissible pattern -- every residue mod p is bad
        log_c += math.log((1 - w / p) / (1 - 1 / p) ** k)
    return math.exp(log_c)


def recommended_fragment_width(offsets, k, floor_exponent, target_expected=1.0, limit=200_000):
    """Width W (as an int) such that the Hardy-Littlewood expected count of this
    pattern with its base in a W-wide slice near 10**floor_exponent is approximately
    target_expected. Uses ln(10**floor_exponent) as a single representative log(x) --
    good enough for sizing a search fragment (not a precision research estimate) since
    ln(x) barely moves across even a couple of orders of magnitude at these depths."""
    C_k = singular_series_constant(offsets, k, limit=limit)
    if C_k <= 0:
        raise ValueError("pattern is inadmissible (or C_k underflowed to 0) -- cannot size a fragment")
    ln_x = floor_exponent * math.log(10)
    density = C_k / ln_x ** k
    return max(1, round(target_expected / density))


# ------------------------------------------------------------------------------------------
# Imports that need this file's own location on disk (sys.path insertion), same pattern
# constellation_finder_v1.py itself uses for prime_sieve_v1 -- placed here (not at the
# top of the file) only because they're not needed by anything above this point.
# ------------------------------------------------------------------------------------------

import os  # noqa: E402
import sys  # noqa: E402
import datetime  # noqa: E402
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)  # constellation_finder_v1.py, pattern_catalog_v1.py (same folder)
from constellation_finder_v1 import PORTAL_FOLDER, _append_hits_deduped  # noqa: E402
from pattern_catalog_v1 import PATTERN_CATALOG  # noqa: E402


# ------------------------------------------------------------------------------------------
# Location striding -- every strategy except manual_list (a genuine one-shot, see
# manual_list_locations() below) reduces to the SAME mechanism: n_locations windows,
# window_m wide, spaced `step` apart, starting at a floor-relative `start_offset`. The
# strategies differ only in how `step` is computed (see step_for_even()/
# step_for_concentrated() below) and in that this offset/step pair is now CHECKPOINTED
# (read_ktuple_checkpoint()/write_ktuple_checkpoint()) so a later run -- or another loop
# of the SAME run under auto=True, see run_ktuple_job() -- continues from where the
# last one left off instead of re-scanning the same span. Requested 2026-08-19 by
# Artur, who noticed that without this, re-running always re-scanned the exact same
# locations: "brakuje mi pliku ktory jest tworzony by zapisywal na danym pietrze co
# bylo skanowane [...] niech przesuwa sie o jakas wartosc [step] [...] zeby [...]
# przeczesywalo az cos znajdzie albo proces zostanie zatrzymany albo dojdzie do konca
# pietra."
# ------------------------------------------------------------------------------------------

FLOOR_WIDTH_MULTIPLIER = 9  # floor N covers [10**N, 10**(N+1)) -- width = 9 * 10**N


def floor_width(base_exponent):
    return FLOOR_WIDTH_MULTIPLIER * 10 ** base_exponent


def stride_locations(base_exponent, n_locations, window_m, start_offset, step):
    """Up to n_locations absolute base positions
    (10**base_exponent + start_offset + i*step, i = 0..n_locations-1), CLIPPED the
    moment a window would no longer fully fit before the floor's own upper boundary
    (10**(base_exponent+1)) -- so a caller can tell "ran out of floor" apart from
    "scanned the requested count" just by comparing len(result) against n_locations,
    without a separate exhaustion check. Returns (locations, next_offset) -- next_offset
    is where the FOLLOWING batch should start (start_offset + len(locations)*step),
    valid as a checkpoint value even when this batch came up short."""
    floor_base = 10 ** base_exponent
    width = floor_width(base_exponent)
    locations = []
    offset = start_offset
    for _ in range(n_locations):
        if offset < 0 or offset + window_m > width:
            break
        locations.append(floor_base + offset)
        offset += step
    return locations, offset


def step_for_even(window_m):
    """Dense, contiguous sweep -- no gaps, no overlap between successive windows."""
    return window_m


def step_for_concentrated(offsets, k, base_exponent, n_locations, window_m,
                           target_expected=1.0, hl_limit=200_000, fragment_width=None):
    """Spacing wide enough that n_locations samples spread this way cover a span whose
    Hardy-Littlewood expected hit count is ~target_expected (see
    recommended_fragment_width()) -- this shapes the SPACING only, not a cap on how far
    scanning eventually goes: once a batch is done, the next one just keeps striding by
    this same step past that original span (see run_ktuple_job()), for as many batches
    as auto=True keeps running."""
    if fragment_width is None:
        fragment_width = recommended_fragment_width(
            offsets, k, base_exponent, target_expected=target_expected, limit=hl_limit)
    return max(window_m, fragment_width // max(1, n_locations))


def manual_list_locations(base_exponent, manual_offsets):
    """strategy=manual_list: an explicit, one-shot list of offsets from the floor's own
    start -- no checkpoint, no striding, exactly what was there before this module
    grew the checkpoint/step mechanism (kept as its own strategy alongside
    manual_step, at Artur's request, for precisely-chosen/irregular positions that a
    fixed step can't express)."""
    if not manual_offsets:
        raise ValueError("manual_list strategy requires a non-empty manual_offsets list")
    floor_base = 10 ** base_exponent
    return sorted(floor_base + off for off in manual_offsets)


# ------------------------------------------------------------------------------------------
# Digit sweep -- strategy=digit_sweep. A floor N (== [10**N, 10**(N+1))) is N+1 digits
# wide. A linear crawl (even/concentrated/manual_step, however wide a step) only ever
# examines numbers that share the SAME leading digits as wherever the crawl currently
# is -- reaching a genuinely different magnitude neighborhood (e.g. one starting with a
# "7" instead of a "1") takes an enormous number of steps. Artur's own proposal: since a
# batch already has ~1000 windows of budget, split that budget across the floor's own
# digit POSITIONS instead of across one linear span, so a single batch's ~1000 windows
# touch every magnitude neighborhood of the floor at once.
#
# Mechanics, worked through on his own example (floor = 5-digit numbers, 10000..99999,
# base_exponent=4):
#   position p=4 (the floor's own leading digit, values 1..9): sample near 10000,
#       20000, ..., 90000 -- one sub-scan per leading digit.
#   position p=3 (values 0..9): NOT independent of the first position -- his example
#       continues from 11000, 12000, ..., 19000, i.e. it STAYS inside the branch it
#       already committed to at position 4 (leading digit "1") and only varies position
#       3. This is nested drilling into ONE path, not an independent sweep of every
#       position from the floor's own base (that alternative was proposed and
#       explicitly rejected in favor of this one, 2026-08-19) -- so after position p is
#       swept, it gets FIXED at a committed digit (pass_counter=0 reproduces his own
#       example verbatim, i.e. every position commits to "1") before the next, finer
#       position is swept. See the PATH VARIETY note below for how later passes
#       (pass_counter=1, 2, ...) vary this per position instead of repeating one digit.
#   position p=2: 11100, 11200, ..., 11900 -- same pattern, now inside the "11" branch.
#   ...continues down to the finest position whose place value is still >= window_m
#       (see digit_sweep_positions()) -- below that a single window already covers
#       everything remaining, drilling further would add positions but no coverage.
#
# Budget per position beyond one window per digit value: Artur's own follow-up
# ("rozkladamy rownomiernie az skoncza sie okna a jesli jest ich wiecej niz
# poszczegolnych cyfr do obsadzenia to tworza spojna szerokosc zwiekszajac predkosc na
# danym fragmencie", 2026-08-19) -- extra windows are placed back-to-back (no gaps)
# starting right at that digit's own offset, densifying coverage at the START of that
# fragment rather than spreading thin across its whole width.
# ------------------------------------------------------------------------------------------

def digit_sweep_positions(base_exponent, window_m):
    """Digit positions to sweep, coarsest (base_exponent itself -- the place where
    floor_base's own leading digit lives) down to the finest position p_min whose
    place value (10**p_min) is the smallest power of ten still >= window_m. Returns a
    descending list of positions, e.g. base_exponent=25, window_m=10_000_000 ->
    [25, 24, 23, ..., 7] (19 positions).

    p_min found by direct search (not log10 -- avoids float-precision edge cases
    right at a power of ten) so that 10**p_min is GUARANTEED >= window_m -- this
    matters for digit_sweep_locations()'s own overlap guard (place // window_m must
    never floor to 0 for a swept position, or a digit's own contiguous block could
    spill into the next digit's territory)."""
    p_min = 0
    while 10 ** p_min < window_m:
        p_min += 1
    positions = [base_exponent] + list(range(base_exponent - 1, p_min - 1, -1))
    return [p for p in positions if p >= 0]


# Per-position digit steps for the varied ("scrambled", not a repdigit) committed
# path -- see digit_sweep_locations()'s own docstring, PATH VARIETY note, for why
# this exists. Each position advances its own committed digit at a different pace
# (its own coprime-ish step mod 9) as pass_counter increments, so the combined path
# across many positions looks mixed (e.g. "53254553452543") rather than a single
# digit repeated at every position. Plain ascending small primes (plus 1) -- nothing
# deeper than "different small step per position" is needed here, this has no
# bearing on correctness, only on which branches get explored deeper across
# successive passes.
_DIGIT_SWEEP_STEP_PRIMES = [1, 2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47,
                            53, 59, 61, 67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109]


def _commit_digit_for_position(pass_counter, position_index):
    """The digit (1-9) position `position_index` commits to during pass
    `pass_counter` -- see digit_sweep_locations()'s PATH VARIETY note."""
    step = _DIGIT_SWEEP_STEP_PRIMES[position_index % len(_DIGIT_SWEEP_STEP_PRIMES)]
    return ((pass_counter * step) % 9) + 1


def digit_sweep_locations(base_exponent, n_locations, window_m, anchor_offset=0, pass_counter=0):
    """strategy=digit_sweep -- see the module-section docstring above for the full
    design. Returns a list of absolute base positions (floor_base + offset), coarsest
    position's sub-scans first, already clipped to the floor's own upper boundary.

    `anchor_offset` shifts the WHOLE nested pattern by a fixed floor-relative amount.
    Always 0 in current use -- see CONTINUATION FIX in run_ktuple_job()'s own
    docstring for why a floor-offset shift is unsafe for this strategy; kept as a
    parameter only so a caller with its own use case can still express one.

    `pass_counter` -- which pass this is (0, 1, 2, ...); drives the digit each
    position commits to before drilling into the next, finer one -- see PATH
    VARIETY below. pass_counter=0 reproduces Artur's own original worked example
    exactly (every position commits to digit "1").

    PATH VARIETY (added 2026-08-19, at Artur's request): the first version of this
    continuation scheme committed EVERY position to the SAME digit for a whole pass
    (pass 0 -> all "1"s, pass 1 -> all "2"s, ...), so the explored branches were
    repdigit-shaped (111...1, 222...2, ...) -- Artur asked for genuinely mixed,
    scrambled-looking paths instead (his own example: "53254553452543"), not a
    symmetric ascending sequence. Each position now derives ITS OWN committed digit
    from pass_counter via _commit_digit_for_position() -- a different small step per
    position index means different positions cycle through 1..9 at different rates,
    so as pass_counter increases the combined path across all positions looks mixed
    rather than uniform, while staying fully deterministic (same pass_counter always
    reproduces the same path -- useful for reasoning about what's already been
    covered from a log).

    BUG FIXED 2026-08-19, TWO PARTS (found by Artur from a real run's log tail):
    (1) a digit value's own sub-interval is exactly `place` (=10**p) wide -- at the
    FINEST swept position, place == window_m, so at most ONE window fits per digit
    value at all; without a cap, extra budget there produced a contiguous block that
    ran straight past the digit's own single-window sub-interval and into the NEXT
    digit value's territory, so the tail of a batch silently degenerated from a 0..9
    digit sweep into a plain linear crawl (an offset contribution of "23" at a
    position that can only ever hold a single digit 0..9). Fixed by capping
    windows_per_digit at `place // window_m` (always >= 1 for every position
    digit_sweep_positions() returns, by that function's own p_min search).
    (2) even with (1) fixed, a position's OWN committed branch (digit_value == that
    position's own committed digit) still starts at EXACTLY the offset the next,
    finer position's own committed-digit branch starts at too (that's the whole
    point of "committing" -- the next position continues from there) -- so if that
    branch got more than one contiguous window at THIS level, those extra windows
    silently duplicated ones the NEXT level was about to explore anyway (and in more
    depth). Fixed by capping the committed branch to exactly one window (the anchor
    point itself, matching Artur's own worked example, which explicitly re-lists it)
    at every position except the LAST -- only the finest position, with nothing
    deeper to hand off to, spends its full per-digit budget on every digit value
    including its own committed one."""
    floor_base = 10 ** base_exponent
    width = floor_width(base_exponent)
    positions = digit_sweep_positions(base_exponent, window_m)
    if not positions:
        return []

    n_positions = len(positions)
    per_position = [n_locations // n_positions] * n_positions
    for i in range(n_locations % n_positions):
        per_position[i] += 1  # remainder spread across the coarsest positions first

    locations = []
    committed = anchor_offset
    for idx, p in enumerate(positions):
        is_last = (idx == n_positions - 1)
        is_leading = (p == base_exponent)
        digit_values = range(1, 10) if is_leading else range(0, 10)
        place = 10 ** p
        max_fit = max(1, place // window_m)  # windows that fit in ONE digit's own
                                              # place-wide sub-interval without
                                              # spilling into the next digit's
        windows_per_digit = max(1, min(per_position[idx] // len(digit_values), max_fit))
        position_commit_digit = _commit_digit_for_position(pass_counter, idx)
        for digit_value in digit_values:
            d = digit_value - 1 if is_leading else digit_value  # d=0 at the leading
            digit_offset = committed + d * place                # position IS digit "1"
            this_branch_windows = windows_per_digit
            if not is_last and digit_value == position_commit_digit:
                this_branch_windows = 1  # deferred to the next, finer position --
                                          # see part (2) of the docstring note above
            for i in range(this_branch_windows):                # -- floor_base's own
                off = digit_offset + i * window_m                # leading digit, free
                if off + window_m <= width:
                    locations.append(floor_base + off)
        d_commit = position_commit_digit - 1 if is_leading else position_commit_digit
        committed += d_commit * place

    return locations


# ------------------------------------------------------------------------------------------
# Checkpoint -- one file per (floor, k, variant), living alongside that pattern's own
# hit file (constellation_finder_v1.hit_file_path's own folder), storing only where the
# NEXT batch should start plus enough context to show in a status line. Never blocks on
# a strategy/window_m/step mismatch against a previous run (same "informational, not a
# hard stop" philosophy as constellation_finder_v1.check_floor_boundary's own
# unresolved-boundary note) -- next_offset alone is authoritative; the rest is just
# provenance for whoever's watching the log.
# ------------------------------------------------------------------------------------------

def _ktuple_checkpoint_path(base_exponent, k, variant_id):
    return os.path.join(
        PORTAL_FOLDER, f"10p{base_exponent}", "constellations", f"k{k}", f"variant{variant_id}",
        f"KTUPLE_CHECKPOINT_10p{base_exponent}_k{k}_v{variant_id}.txt")


def read_ktuple_checkpoint(base_exponent, k, variant_id):
    """Returns {"next_offset", "step", "window_m", "strategy"} (ints/str) or None if no
    checkpoint exists yet, or if the file is missing/corrupt -- treated as "start
    fresh" either way, never raises."""
    path = _ktuple_checkpoint_path(base_exponent, k, variant_id)
    if not os.path.exists(path):
        return None
    values = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if "=" not in line:
                    continue
                key, _, val = line.strip().partition("=")
                values[key] = val
        return {"next_offset": int(values["next_offset"]), "step": int(values["step"]),
                "window_m": int(values["window_m"]), "strategy": values.get("strategy", "")}
    except (OSError, KeyError, ValueError):
        return None


def write_ktuple_checkpoint(base_exponent, k, variant_id, next_offset, step, window_m, strategy):
    path = _ktuple_checkpoint_path(base_exponent, k, variant_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(f"next_offset={next_offset}\n")
        f.write(f"step={step}\n")
        f.write(f"window_m={window_m}\n")
        f.write(f"strategy={strategy}\n")
        f.write(f"updated_at={datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
    os.replace(tmp_path, path)


def clear_ktuple_checkpoint(base_exponent, k, variant_id):
    """Explicit reset -- also reachable via run_ktuple_job(reset_checkpoint=True),
    which ignores rather than deletes an existing checkpoint (deleting only matters if
    something else wants to observe "no checkpoint" afterward, e.g. a UI's own status
    line -- run_ktuple_job's own in-process ignore-and-overwrite is enough for its own
    correctness either way)."""
    try:
        os.remove(_ktuple_checkpoint_path(base_exponent, k, variant_id))
    except OSError:
        pass


# ------------------------------------------------------------------------------------------
# Top-level drivers.
# ------------------------------------------------------------------------------------------

def scan_locations(base_exponent, pattern, locations, window_m,
                    wheel_primes=None, deep_prime_limit=2000, mr_rounds=40,
                    progress_cb=None, should_stop=None):
    """Scans each of `locations` (absolute base positions, each a window_m-wide range)
    for pattern's k-tuple, writing confirmed hits into the pattern's own cumulative hit
    file (constellation_finder_v1.hit_file_path/_append_hits_deduped). Used directly
    (no checkpoint) for strategy=manual_list; run_ktuple_job() below builds its own
    locations per batch via stride_locations() and calls the same per-window scan-and-
    verify logic inline (needs to inspect per-location hits to decide whether to keep
    auto-looping, which a single boolean return here doesn't expose).

    `progress_cb(index, total, location, candidates_found, confirmed_count)` -- called
    after each location finishes. `should_stop()` -- checked before each location.
    Returns {"locations_done": n, "cancelled": bool, "total_candidates": n,
    "total_confirmed": n}."""
    offsets = pattern["offsets"]
    k = pattern["k"]
    variant_id = pattern["id"]

    if wheel_primes is None:
        wheel_primes = default_wheel_primes(offsets)
    wheel_M, wheel_residues = build_wheel(offsets, wheel_primes)
    deep_primes = [p for p in primes_upto(deep_prime_limit) if p not in wheel_primes]

    total_candidates = 0
    total_confirmed = 0
    locations_done = 0
    cancelled = False

    for i, base in enumerate(locations):
        if should_stop is not None and should_stop():
            cancelled = True
            break
        candidates = scan_window_for_candidates(
            base, window_m, offsets, wheel_M, wheel_residues, deep_primes)
        confirmed = verify_candidates(candidates, offsets, rounds=mr_rounds)
        if confirmed:
            _append_hits_deduped(base_exponent, k, variant_id, sorted(confirmed))
        total_candidates += len(candidates)
        total_confirmed += len(confirmed)
        locations_done += 1
        if progress_cb is not None:
            progress_cb(i, len(locations), base, len(candidates), len(confirmed))

    return {"locations_done": locations_done, "cancelled": cancelled,
            "total_candidates": total_candidates, "total_confirmed": total_confirmed}


def run_ktuple_job(base_exponent, pattern, window_m, strategy, n_locations,
                    step=None, start_offset=None, fragment_width=None,
                    target_expected=1.0, hl_limit=200_000, wheel_primes=None,
                    deep_prime_limit=2000, mr_rounds=40, auto=False,
                    reset_checkpoint=False, pass_counter=0, progress_cb=None, should_stop=None):
    """Checkpointed driver for strategy in ("even", "concentrated", "manual_step",
    "digit_sweep") -- manual_list has no checkpoint concept, see
    manual_list_locations()/scan_locations() above instead.

    `step`, if given, overrides the strategy's own formula for even/concentrated/
    manual_step (manual_step has no formula of its own -- an explicit step is required
    for it; digit_sweep ignores `step` entirely, see digit_sweep_locations() instead).
    `start_offset`, if given, is only used the very FIRST time (no checkpoint exists
    yet, or reset_checkpoint=True) -- every batch after that continues from the
    checkpoint regardless of what was passed in here; digit_sweep ignores it too (see
    `pass_counter` below instead -- a floor-relative offset has no meaning for it).

    `pass_counter` -- digit_sweep only, the STARTING pass (0, 1, 2, ..., default 0)
    used only the very first time (no checkpoint yet, or reset_checkpoint=True); every
    batch after that continues from the checkpoint's own pass_counter regardless of
    what's passed in here. CONTINUATION FIX 2026-08-19 (found by Artur -- a
    checkpointed anchor_offset that isn't a multiple of 10**base_exponent corrupts the
    digit sweep: every position's own d=0..9 loop assumes committed starts CLEAN at
    that position, i.e. anchor's own digit there is 0, so a nonzero leftover from a
    previous "shift the whole pattern by 10**p_min" scheme -- what this used to do --
    would add on TOP of that, overflowing past a single digit and producing nonsense
    offsets, exactly like the tail-corruption bug fixed earlier). Fixed by NEVER
    shifting the anchor at all for digit_sweep (it stays 0, always clean) -- instead,
    each batch after the first just increments pass_counter by 1, persisted in the
    checkpoint's own next_offset field (repurposed to hold the next pass_counter for
    this one strategy, since a floor offset is meaningless here).

    PATH VARIETY 2026-08-19 (also found/requested by Artur): pass_counter alone drove
    ONE digit, shared by every swept position for the whole pass -- pass 0 explored
    the "111...1" branch, pass 1 "222...2", etc., a repdigit progression Artur pointed
    out looked nothing like the scrambled, "53254553452543"-style variety he actually
    wanted. digit_sweep_locations() now derives a DIFFERENT digit per position from
    the SAME pass_counter (see its own PATH VARIETY note) -- pass_counter itself still
    just increments by 1 each batch, but the resulting explored path is mixed rather
    than uniform.

    auto=False (default): scans exactly one batch of up to n_locations windows, updates
    the checkpoint, and returns -- the shape a plain "Run" click wants (repeat by
    clicking Run again, each click a fresh continuation).
    auto=True: keeps scanning batch after batch (checkpointing after each) until one
    of -- a confirmed hit appears in some batch (stop_reason="hit_found"),
    should_stop() returns True (stop_reason="cancelled"), or the next batch would have
    zero locations because the floor is exhausted (stop_reason="floor_exhausted" --
    for digit_sweep this can only happen if window_m itself leaves no positions to
    sweep at all, checked up front below; a normal digit_sweep run simply keeps
    incrementing pass_counter forever until a hit or should_stop()).

    Returns {"batches_done", "locations_scanned", "total_candidates",
    "total_confirmed", "stop_reason", "next_offset"}."""
    if strategy not in ("even", "concentrated", "manual_step", "digit_sweep"):
        raise ValueError(f"run_ktuple_job() strategy must be 'even', 'concentrated', "
                          f"'manual_step', or 'digit_sweep' (got {strategy!r}) -- use "
                          f"manual_list_locations()+scan_locations() for strategy='manual_list'")

    offsets = pattern["offsets"]
    k = pattern["k"]
    variant_id = pattern["id"]

    if wheel_primes is None:
        wheel_primes = default_wheel_primes(offsets)
    wheel_M, wheel_residues = build_wheel(offsets, wheel_primes)
    deep_primes = [p for p in primes_upto(deep_prime_limit) if p not in wheel_primes]

    checkpoint = None if reset_checkpoint else read_ktuple_checkpoint(base_exponent, k, variant_id)

    if strategy == "digit_sweep":
        drill_positions = digit_sweep_positions(base_exponent, window_m)
        if not drill_positions:
            raise ValueError("window_m leaves no digit positions to sweep at this floor "
                              "-- window_m is too wide relative to the floor's own width")
        # next_offset here holds the NEXT pass_counter, not a floor offset -- see
        # the docstring's CONTINUATION FIX note above. Falls back to the
        # caller-given pass_counter if the checkpoint is missing/reset/negative.
        current_offset = checkpoint["next_offset"] if checkpoint is not None else pass_counter
        if current_offset < 0:
            current_offset = pass_counter
    else:
        current_offset = checkpoint["next_offset"] if checkpoint is not None else (start_offset or 0)
        if step is None:
            if strategy == "even":
                step = step_for_even(window_m)
            elif strategy == "concentrated":
                step = step_for_concentrated(
                    offsets, k, base_exponent, n_locations, window_m,
                    target_expected=target_expected, hl_limit=hl_limit, fragment_width=fragment_width)
            else:  # manual_step
                raise ValueError("strategy='manual_step' requires an explicit step")

    total_candidates = 0
    total_confirmed = 0
    total_scanned = 0
    batches_done = 0
    stop_reason = "single_batch_done"

    while True:
        if strategy == "digit_sweep":
            locations = digit_sweep_locations(
                base_exponent, n_locations, window_m,
                anchor_offset=0, pass_counter=current_offset)
            next_offset = current_offset + 1  # next pass -- see PATH VARIETY note
        else:
            locations, next_offset = stride_locations(
                base_exponent, n_locations, window_m, current_offset, step)
        if not locations:
            stop_reason = "floor_exhausted"
            break

        batch_confirmed_any = False
        batch_cancelled = False
        for i, base in enumerate(locations):
            if should_stop is not None and should_stop():
                batch_cancelled = True
                break
            candidates = scan_window_for_candidates(
                base, window_m, offsets, wheel_M, wheel_residues, deep_primes)
            confirmed = verify_candidates(candidates, offsets, rounds=mr_rounds)
            if confirmed:
                _append_hits_deduped(base_exponent, k, variant_id, sorted(confirmed))
                batch_confirmed_any = True
            total_candidates += len(candidates)
            total_confirmed += len(confirmed)
            total_scanned += 1
            if progress_cb is not None:
                progress_cb(batches_done, i, len(locations), base, len(candidates), len(confirmed))

        batches_done += 1
        # for digit_sweep, `current_offset` just used for this batch is the
        # pass_counter ABOUT to be superseded -- record it as `step` too
        # (informational only, so a status line can show which pass this batch just
        # finished) before overwriting current_offset with the next pass_counter.
        checkpoint_step = current_offset if strategy == "digit_sweep" else step
        current_offset = next_offset
        write_ktuple_checkpoint(base_exponent, k, variant_id, current_offset, checkpoint_step, window_m, strategy)

        if batch_cancelled:
            stop_reason = "cancelled"
            break
        if batch_confirmed_any:
            stop_reason = "hit_found"
            break
        if not auto:
            stop_reason = "single_batch_done"
            break
        # auto=True, no hit this batch, not stopped, floor not exhausted -- loop again

    return {"batches_done": batches_done, "locations_scanned": total_scanned,
            "total_candidates": total_candidates, "total_confirmed": total_confirmed,
            "stop_reason": stop_reason, "next_offset": current_offset}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Targeted k-tuple candidate sieve (wheel + trial division + Miller-Rabin) "
                    "for a single catalog pattern, checkpointed per (floor, k, variant).")
    parser.add_argument("base_exponent", type=int, help="floor N (searches near 10**N)")
    parser.add_argument("k", type=int, help="pattern k (e.g. 15)")
    parser.add_argument("variant_id", type=int, help="pattern variant id within k (see pattern_catalog_v1.py)")
    parser.add_argument("--n-locations", type=int, default=1000)
    parser.add_argument("--window-m", type=int, default=10_000_000)
    parser.add_argument("--strategy",
                         choices=["even", "concentrated", "manual_list", "manual_step", "digit_sweep"],
                         default="concentrated")
    parser.add_argument("--step", type=int, default=None,
                         help="explicit stride override for even/concentrated/manual_step "
                              "(required for manual_step; ignored by digit_sweep)")
    parser.add_argument("--fragment-width", type=int, default=None)
    parser.add_argument("--fragment-start", type=int, default=None,
                         help="initial offset used only when no checkpoint exists yet "
                              "(or --reset-checkpoint) -- default 0")
    parser.add_argument("--manual-offsets", type=int, nargs="*", default=None,
                         help="strategy=manual_list only")
    parser.add_argument("--pass-counter", type=int, default=0,
                         help="strategy=digit_sweep only -- starting pass (0, 1, 2, ...) "
                              "used only when no checkpoint exists yet or --reset-checkpoint "
                              "(default 0 -- matches the original worked example exactly)")
    parser.add_argument("--deep-prime-limit", type=int, default=2000)
    parser.add_argument("--mr-rounds", type=int, default=40)
    parser.add_argument("--auto", action="store_true",
                         help="keep scanning batch after batch until a hit, --stop, or the floor is exhausted")
    parser.add_argument("--reset-checkpoint", action="store_true",
                         help="ignore any existing checkpoint and start from --fragment-start (default 0)")
    args = parser.parse_args()

    pattern = next((w for w in PATTERN_CATALOG if w["k"] == args.k and w["id"] == args.variant_id), None)
    if pattern is None:
        print(f"[!] No pattern k={args.k} id={args.variant_id} in PATTERN_CATALOG.")
        sys.exit(1)

    print(f"[KTUPLE SIEVE v1] 10^{args.base_exponent} pattern k={args.k} v={args.variant_id} "
          f"({pattern['discoverer']}, {pattern['date']}) -- strategy={args.strategy}, "
          f"n_locations={args.n_locations}, window_m={args.window_m:,}, auto={args.auto}")

    if args.reset_checkpoint and args.strategy != "manual_list":
        clear_ktuple_checkpoint(args.base_exponent, args.k, args.variant_id)
        print("[KTUPLE SIEVE v1] Checkpoint reset -- starting from "
              f"--fragment-start={args.fragment_start or 0}.")

    if args.strategy == "manual_list":
        locations = manual_list_locations(args.base_exponent, args.manual_offsets)
        print(f"[KTUPLE SIEVE v1] {len(locations)} manual location(s) (one-shot, no checkpoint).")

        def progress_list(i, total, base, n_cand, n_conf):
            extra = f" -- {n_conf} CONFIRMED HIT(S)!" if n_conf else ""
            print(f"[KTUPLE SIEVE v1] {i+1}/{total}: base={base} candidates={n_cand}{extra}")

        result = scan_locations(args.base_exponent, pattern, locations, args.window_m,
                                 deep_prime_limit=args.deep_prime_limit, mr_rounds=args.mr_rounds,
                                 progress_cb=progress_list)
        print(f"\n[KTUPLE SIEVE v1] Done. locations_done={result['locations_done']} "
              f"total_candidates={result['total_candidates']} "
              f"total_confirmed={result['total_confirmed']}")
    else:
        def progress_batch(batch_idx, i, total, base, n_cand, n_conf):
            extra = f" -- {n_conf} CONFIRMED HIT(S)!" if n_conf else ""
            print(f"[KTUPLE SIEVE v1] batch {batch_idx+1}, {i+1}/{total}: base={base} "
                  f"candidates={n_cand}{extra}")

        result = run_ktuple_job(
            args.base_exponent, pattern, args.window_m, args.strategy, args.n_locations,
            step=args.step, start_offset=args.fragment_start,
            fragment_width=args.fragment_width, deep_prime_limit=args.deep_prime_limit,
            mr_rounds=args.mr_rounds, auto=args.auto, reset_checkpoint=args.reset_checkpoint,
            pass_counter=args.pass_counter, progress_cb=progress_batch)
        print(f"\n[KTUPLE SIEVE v1] Done. batches_done={result['batches_done']} "
              f"locations_scanned={result['locations_scanned']} "
              f"total_candidates={result['total_candidates']} "
              f"total_confirmed={result['total_confirmed']} "
              f"stop_reason={result['stop_reason']} next_offset={result['next_offset']}")
