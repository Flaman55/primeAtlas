"""
ktuple_locations_v2_1.py -- where ktuple_sieve_v2_1.py scans: the floor geometry,
the striding shared by even/concentrated/manual_step, the one-shot manual_list,
and the nested digit sweep. Returns absolute window base positions only; scanning
and checkpointing live in ktuple_sieve_v2_1.py and ktuple_hit_store_v2_1.py.
"""
from ktuple_wheel_v2_1 import recommended_fragment_width


# ------------------------------------------------------------------------------------------
# Location striding -- every strategy except manual_list (a genuine one-shot, see
# manual_list_locations() below) reduces to the SAME mechanism: n_locations windows,
# window_m wide, spaced `step` apart, starting at a floor-relative `start_offset`. The
# strategies differ only in how `step` is computed (see step_for_even()/
# step_for_concentrated() below) and in that this offset/step pair is CHECKPOINTED
# (ktuple_hit_store_v2_1.read_ktuple_checkpoint()/write_ktuple_checkpoint()) so a
# later run -- or another loop of the SAME run under auto=True, see
# ktuple_sieve_v2_1.run_ktuple_job() -- continues from where the
# last one left off instead of re-scanning the same span.
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
    start -- no checkpoint, no striding (its own strategy alongside manual_step,
    for precisely-chosen/irregular positions that a fixed step can't express)."""
    if not manual_offsets:
        raise ValueError("manual_list strategy requires a non-empty manual_offsets list")
    floor_base = 10 ** base_exponent
    return sorted(floor_base + off for off in manual_offsets)


# ------------------------------------------------------------------------------------------
# Digit sweep -- strategy=digit_sweep. A floor N (== [10**N, 10**(N+1))) is N+1 digits
# wide. A linear crawl (even/concentrated/manual_step, however wide a step) only ever
# examines numbers that share the SAME leading digits as wherever the crawl currently
# is -- reaching a genuinely different magnitude neighborhood (e.g. one starting with a
# "7" instead of a "1") takes an enormous number of steps. Instead, since a batch has a
# fixed budget of windows, that budget is split across the floor's own digit POSITIONS
# rather than across one linear span, so a single batch's windows touch every magnitude
# neighborhood of the floor at once.
#
# Mechanics, worked through on an example (floor = 5-digit numbers, 10000..99999,
# base_exponent=4):
#   position p=4 (the floor's own leading digit, values 1..9): sample near 10000,
#       20000, ..., 90000 -- one sub-scan per leading digit.
#   position p=3 (values 0..9): NOT independent of the first position -- it continues
#       from 11000, 12000, ..., 19000, i.e. it STAYS inside the branch already
#       committed to at position 4 (leading digit "1") and only varies position 3.
#       This is nested drilling into ONE path, not an independent sweep of every
#       position from the floor's own base -- so after position p is swept, it gets
#       FIXED at a committed digit (pass_counter=0 commits every position to "1")
#       before the next, finer position is swept. See the PATH VARIETY note below for
#       how later passes (pass_counter=1, 2, ...) vary this per position instead of
#       repeating one digit.
#   position p=2: 11100, 11200, ..., 11900 -- same pattern, now inside the "11" branch.
#   ...continues down to the finest position whose place value is still >= window_m
#       (see digit_sweep_positions()) -- below that a single window already covers
#       everything remaining, drilling further would add positions but no coverage.
#
# Budget per position beyond one window per digit value: extra windows are placed
# back-to-back (no gaps) starting right at that digit's own offset, densifying coverage
# at the START of that fragment rather than spreading thin across its whole width.
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
    Always 0 in current use -- see CONTINUATION in run_ktuple_job()'s own
    docstring for why a floor-offset shift is unsafe for this strategy; kept as a
    parameter only so a caller with its own use case can still express one.

    `pass_counter` -- which pass this is (0, 1, 2, ...); drives the digit each
    position commits to before drilling into the next, finer one -- see PATH
    VARIETY below. pass_counter=0 commits every position to digit "1".

    PATH VARIETY: committing EVERY position to the SAME digit for a whole pass (pass
    0 -> all "1"s, pass 1 -> all "2"s, ...) would make the explored branches purely
    repdigit-shaped (111...1, 222...2, ...) instead of genuinely mixed. Each position
    instead derives ITS OWN committed digit from pass_counter via
    _commit_digit_for_position() -- a different small step per position index means
    different positions cycle through 1..9 at different rates, so as pass_counter
    increases the combined path across all positions looks mixed rather than
    uniform, while staying fully deterministic (same pass_counter always reproduces
    the same path -- useful for reasoning about what's already been covered from a
    log).

    Two edge cases handled here:
    (1) a digit value's own sub-interval is exactly `place` (=10**p) wide -- at the
    FINEST swept position, place == window_m, so at most ONE window fits per digit
    value at all; without a cap, extra budget there would produce a contiguous block
    that runs straight past the digit's own single-window sub-interval and into the
    NEXT digit value's territory, silently degenerating the tail of a batch from a
    0..9 digit sweep into a plain linear crawl. Guarded by capping windows_per_digit at
    `place // window_m` (always >= 1 for every position digit_sweep_positions()
    returns, by that function's own p_min search).
    (2) a position's OWN committed branch (digit_value == that
    position's own committed digit) still starts at EXACTLY the offset the next,
    finer position's own committed-digit branch starts at too (that's the whole
    point of "committing" -- the next position continues from there) -- so if that
    branch got more than one contiguous window at THIS level, those extra windows
    would duplicate ones the NEXT level is about to explore anyway (and in more
    depth). Guarded by capping the committed branch to exactly one window (the anchor
    point itself) at every position except the LAST -- only the finest position,
    with nothing deeper to hand off to, spends its full per-digit budget on every
    digit value including its own committed one."""
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
