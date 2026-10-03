"""
line_geometry.py -- "line" viz-mode geometry: a fixed row of real primes (--load-range)
with an optional k-tuple pattern slid along it by N. Axis layouts (straight, bent into a
ring, spiral), pattern matching, and the wheel of residues a pattern anchor can take.
Independent of the ring/gear math in rings/ring/ring_geometry.py. No rendering, no I/O.
"""

import bisect
import math

import numpy as np

from primeatlas.visualization.shared.bigint import to_prime_array


def _is_prime_trial_division(x):
    """Plain trial division -- fine at the moderate magnitudes the manual
    Pattern-seed GUI field takes (an exploratory input, not an
    archive-scale primality tool; see prime_sieve/ for that)."""
    if x < 2:
        return False
    if x < 4:
        return True
    if x % 2 == 0:
        return False
    i = 3
    while i * i <= x:
        if x % i == 0:
            return False
        i += 2
    return True


def next_prime_at_or_above(x):
    """Smallest real prime >= x."""
    x = max(int(x), 2)
    while not _is_prime_trial_division(x):
        x += 1
    return x


def pattern_offsets_from_seed(k, p0):
    """Offsets (ascending, first always 0) for the k-tuple pattern literally
    realized by the first k real primes >= p0 -- e.g.
    pattern_offsets_from_seed(7, 11) == [0, 2, 6, 8, 12, 18, 20], the exact
    shape of constellation/pattern_catalog_v1.py's k=7 id=1 entry, because
    that catalog pattern's own smallest realization IS the run
    11,13,17,19,23,29,31.

    Any pattern built this way is automatically admissible (never forced to
    zero by covering all residues mod some small prime p): it already
    occurred once as real primes, which is only possible if it wasn't
    forced composite at every n -- see the shift-correlation experiment
    (constellation/shift_correlation_experiment_v1.py) this is a direct
    extension of.

    `p0` need not itself be prime -- treated as a lower bound. Requires
    `p0 > 2` (a pattern seeded at 2 always degenerates to the trivial
    parity case: every other member has a different parity from 2, so at
    most one further member can ever be prime) and `k >= 2` (a "pattern" of
    one point is meaningless here)."""
    if k < 2:
        raise ValueError(f"pattern_offsets_from_seed: k must be >= 2, got {k}")
    if p0 <= 2:
        raise ValueError(f"pattern_offsets_from_seed: p0 must be > 2, got {p0}")
    primes = []
    candidate = p0
    while len(primes) < k:
        candidate = next_prime_at_or_above(candidate)
        primes.append(candidate)
        candidate += 1
    first = primes[0]
    return [p - first for p in primes]


def line_positions(primes, world_width=1600.0):
    """Maps a sorted array of real primes onto a horizontal line in world
    space: x linearly spans [-world_width/2, world_width/2] from the
    smallest to the largest value, y=0 for every point. Pure numpy, mirrors
    ring_positions' contract shape (a dict of parallel arrays) but for
    line mode's linear layout instead of that function's polar one.

    Returns {"x": ndarray, "y": ndarray, "lo": int, "span": int} -- `lo`/
    `span` are exposed so a caller can map an arbitrary OTHER value (e.g. a
    pattern-member position that isn't itself in `primes`) through the
    exact same scale via value_to_line_x, without re-deriving it.

    Subtracts `lo` BEFORE converting to float: casting to float64 first loses
    precision once values exceed float64's ~15-17 significant digits (floor-25+
    primes have ~26 digits) -- each value's rounding error (up to ~value * 2**-52) can
    exceed the whole window's span, collapsing distinct points onto the same pixels
    (e.g. a k=3 pattern's 3 members drawn as 2). `primes_arr - lo` stays EXACT
    (object-dtype minus a Python int is bigint arithmetic; uint64/int64 minus a scalar
    of the same dtype is exact too) and is bounded by `span`, so only then is it cast
    to float64."""
    primes_arr = to_prime_array(primes)
    lo = int(primes_arr[0])
    hi = int(primes_arr[-1])
    span = max(hi - lo, 1)
    x = (primes_arr - lo).astype(np.float64) / span * world_width - world_width / 2.0
    y = np.zeros(len(primes_arr), dtype=np.float64)
    return {"x": x, "y": y, "lo": lo, "span": span}


def value_to_line_x(value, lo, span, world_width=1600.0):
    """Same linear map line_positions uses internally, for a single scalar
    value not necessarily present in the array line_positions was called
    with (e.g. one pattern-member position)."""
    return (value - lo) / span * world_width - world_width / 2.0


#: Above this loaded-window span (in absolute prime VALUE units, not
#: pixels), line_positions' whole-window linear map is no longer safe once
#: cast to the GPU's own float32 vertex buffer -- see line_view_bounds'
#: own doc-comment for the exact float32 mechanism this guards against.
#: Chosen with a large safety margin: at this span, a k-tuple's smallest
#: realistic offset gap (2, the twin-prime case) still maps to a world-x
#: delta roughly 3 orders of magnitude bigger than float32's own ULP at
#: world_width/2 -- see that doc-comment for the arithmetic.
LINE_PRECISION_SAFE_SPAN = 20_000

#: Half-width (in absolute VALUE units) of the local, anchor-centered
#: viewport line_view_bounds falls back to once the loaded window's own
#: span exceeds LINE_PRECISION_SAFE_SPAN -- see that function's own
#: doc-comment. 5,000 gives ample float32 headroom (a delta of 2 maps to
#: ~0.32 world-x units at world_width=1600, ~3,000x float32's own ULP
#: there) while still showing hundreds of real primes of context even at
#: real archive density (~1 prime per ln(N) integers).
LINE_LOCAL_VIEW_RADIUS = 5_000


def line_view_bounds(range_lo, range_hi, anchor, offsets=()):
    """Decides which (lo, span) line_positions_windowed/value_to_line_x
    should map "line" viz-mode's world-x coordinates through THIS frame:
    either the whole loaded window's own [range_lo, range_hi] (small
    enough that float32 can resolve every point distinctly), or a FIXED-
    width slice centered on the current pattern anchor `anchor` (wrapping the axis
    into a local coordinate around the anchor).

    This addresses a float32 limit downstream of the float64 one line_positions
    handles: even with `(value - lo)` computed exactly, casting the result to float32
    for the GPU vertex buffer (build_line_vertex_data's (count, 5) float32 array)
    loses precision when the mapped world-x magnitude (~world_width/2, e.g. 800) is
    large relative to the smallest delta a pattern's offsets need resolved (e.g. 2, 4,
    6 for k=4). float32's ULP near x=800 is ~800 * 2**-23 ~= 9.5e-5; with a loaded span
    of ~1e8+ and offsets in the low tens, a value-delta of 2 maps to a world-x delta of
    `2 / span * world_width`, below that ULP, so several offsets collapse onto the
    same float32 x (a k=4 pattern [0,2,6,8] drawn as evenly spaced dots).

    Local mode re-centers the very same linear map on the anchor instead
    of the loaded window's own edges: lo = anchor -
    LINE_LOCAL_VIEW_RADIUS, span = 2 * LINE_LOCAL_VIEW_RADIUS -- always a
    SMALL, FIXED span regardless of how astronomically large `anchor`
    itself is, exactly mirroring how ring mode's own phase (n % p) stays
    bounded regardless of n's magnitude: there, the huge quotient n // p
    is thrown away and only the small remainder kept; here, the huge "how
    far into the whole loaded window am I" is thrown away and only the
    small "how far from the anchor am I" kept. A caller filters which
    loaded primes fall inside [lo, lo+span] separately (see
    line_positions_windowed) -- this function only decides the coordinate
    mapping itself, so it stays a plain O(1) pure function regardless of
    how large the loaded array is.

    `offsets` -- the active pattern's own offsets (empty/default for "no
    pattern set yet"), used only to make sure the local viewport is wide
    enough to hold the WHOLE pattern comfortably (4x its own diameter, so
    the pattern is never clipped by an accidentally-too-narrow local
    window) -- LINE_LOCAL_VIEW_RADIUS already covers every realistic
    k-tuple by a wide margin, this is just a safety floor for an
    unusually wide one.

    Returns (mode, lo, span) -- mode is "full" or "local", purely for a
    caller/HUD to report which one is active; lo/span are always valid
    inputs to line_positions_windowed/value_to_line_x's own math either
    way."""
    full_span = max(range_hi - range_lo, 1)
    if full_span <= LINE_PRECISION_SAFE_SPAN:
        return "full", range_lo, full_span
    diameter = offsets[-1] if offsets else 0
    radius = max(LINE_LOCAL_VIEW_RADIUS, diameter * 4)
    return "local", anchor - radius, 2 * radius


def line_positions_windowed(primes, lo, span, world_width=1600.0):
    """Same output shape as line_positions (x, y, lo, span), but FILTERS
    `primes` (ascending, any dtype to_prime_array accepts) down to only
    the values inside [lo, lo+span] first, and maps them using the
    CALLER-SUPPLIED lo/span instead of deriving it from the array's own
    min/max -- see line_view_bounds for why a caller sometimes wants a
    coordinate mapping anchored elsewhere than "the whole array's own
    extent" (line viz-mode's local, anchor-centered viewport at real
    archive scale).

    The two window edges are found via np.searchsorted (binary search),
    not a full scan or Python-level filter, so this stays cheap even when
    `primes` is the ENTIRE loaded --load-range array (potentially millions
    of entries at real archive scale) and only a small local slice of it
    actually falls inside [lo, lo+span] -- exactly the case this function
    exists for (called once per N-change from build_line_vertex_data).

    Same exact-integer-subtraction-before-cast precision discipline as
    line_positions (see that function's own doc-comment) -- `windowed -
    lo` stays exact (object-dtype minus a Python int, or same-dtype minus
    a scalar that fits) and is bounded by `span` (always small by
    construction here), so only THEN is it safe to cast to float64."""
    primes_arr = to_prime_array(primes)
    hi = lo + span
    start = int(np.searchsorted(primes_arr, lo, side="left"))
    end = int(np.searchsorted(primes_arr, hi, side="right"))
    windowed = primes_arr[start:end]
    x = (windowed - lo).astype(np.float64) / span * world_width - world_width / 2.0
    y = np.zeros(len(windowed), dtype=np.float64)
    return {"x": x, "y": y, "lo": lo, "span": span}


def value_to_ring_axis_xy(value, lo, span, radius=800.0, cx=0.0, cy=0.0):
    """Maps a single scalar value the same way value_to_line_x does (a
    linear position `t = (value - lo) / span` in [0, 1] along the loaded
    window), but places it on a CIRCLE instead of a straight line. A purely visual
    change to how "line" viz-mode's axis is drawn: values keep their exact linear
    ORDER around the circle; only the on-screen shape bends from a row into a ring.

    Same angle convention ring_geometry.ring_positions already uses
    (`angle = phase * 2*pi/prime - pi/2`, DrumRenderer's own convention):
    t=0 (the window's own `lo`) sits at angle -pi/2 -- "12 o'clock",
    directly above the center for the y-axis convention this whole module
    already uses (y increases downward on screen, see VERTEX_SHADER's own
    `ndc.y = -ndc.y` flip; sin(-pi/2) = -1 there ends up rendering at the
    TOP). t=1 (the window's own `lo+span`, one full turn later) maps to
    angle -pi/2 + 2*pi, which is the exact same angle as -pi/2 (sin/cos
    are 2*pi-periodic) -- i.e. the window's start and end coincide at the
    SAME point on the circle. That coincidence is the seam a
    non-cyclic loaded range needs marked, since (unlike ring mode's own
    n % p, which is genuinely periodic) `lo` and `lo+span` are NOT the
    same value -- see the boundary marker line
    (line_draw.axis_boundary_marker_vertices) drawn through this exact
    point, in red, so the seam is never mistaken for a real wraparound."""
    t = (value - lo) / span
    angle = -math.pi / 2.0 + t * 2.0 * math.pi
    x = cx + radius * math.cos(angle)
    y = cy + radius * math.sin(angle)
    return x, y


def line_positions_windowed_ring(primes, lo, span, radius=800.0, cx=0.0, cy=0.0):
    """Circular-layout counterpart of line_positions_windowed: same
    binary-search filter down to [lo, lo+span], but each surviving value
    is placed via value_to_ring_axis_xy's own angle math instead of a
    straight line's y=0 row -- see that function's own doc-comment for the
    full rationale (a purely visual "curved axis" mode, values keep their
    exact linear order, only the on-screen shape changes).

    Returns the same {"x", "y", "lo", "span"} shape line_positions_windowed
    does, so a caller (build_line_vertex_data) can switch between the two
    layouts without touching anything else about how the result is used."""
    primes_arr = to_prime_array(primes)
    hi = lo + span
    start = int(np.searchsorted(primes_arr, lo, side="left"))
    end = int(np.searchsorted(primes_arr, hi, side="right"))
    windowed = primes_arr[start:end]
    t = (windowed - lo).astype(np.float64) / span
    angle = -np.pi / 2.0 + t * 2.0 * np.pi
    x = cx + radius * np.cos(angle)
    y = cy + radius * np.sin(angle)
    return {"x": x, "y": y, "lo": lo, "span": span}


def value_to_spiral_xy(value, lo, period, base_radius=800.0, pitch=800.0, cx=0.0, cy=0.0):
    """Spiral-layout counterpart of value_to_ring_axis_xy: instead of normalizing
    the WHOLE loaded window onto one circle (forcing `lo` and `lo+span` to coincide
    at the seam regardless of how many wheel periods the window spans), each
    `period`-sized chunk of the axis (`period` = the pattern's CRT wheel modulus from
    pattern_wheel_residues -- the smallest repeat cycle of matching residues) gets its
    OWN full lap of the circle, each lap at a bigger radius than the previous one:
    the start value sits innermost, the end value outermost, periodicity preserved.

    `lap = (value - lo) // period` (0 for the first period past `lo`, 1
    for the next, ...); `phase = (value - lo) % period` places the value
    within its own lap exactly like value_to_ring_axis_xy places a value
    within the whole window (t = phase/period, same -pi/2-based angle
    convention) -- so EVERY lap's own phase-zero point (value ≡ lo mod
    period) lands at the identical angle -pi/2, just at that lap's own, bigger
    radius -- so a single straight radial line (see
    spiral_outer_radius/line_draw.axis_boundary_marker_vertices) marks phase
    zero for every lap at once, without a separate per-lap marker.

    `pitch` -- the EXTRA radius each successive lap adds; a purely VISUAL choice
    with NO effect on precision: for a fixed `period`, the ratio of the smallest
    value-delta's world-space arc length to float32's ULP at a lap's radius is
    `(value_delta / period) * 2*pi / FLOAT32_EPS` -- arc length and ULP both scale
    linearly with radius, so radius cancels out. E.g. a k=4 pattern (period=30,030,
    value_delta=2) has a ~3,500x margin at every lap, regardless of `pitch` or the
    number of laps.

    `period<=0` degenerates the same way an empty pattern_wheel_residues
    modulus would -- callers (build_line_vertex_data) only take this path
    when a real wheel (`modulus > 1`) is active, so this is not expected
    to be hit in practice, but division by a non-positive period would
    otherwise raise/misbehave silently; no special-casing is added here
    since the contract is "only call this with a real period" (same
    convention next_wheel_n's own callers already follow for `modulus`)."""
    lap = (value - lo) // period
    phase = (value - lo) % period
    t = phase / period
    angle = -math.pi / 2.0 + t * 2.0 * math.pi
    radius = base_radius + lap * pitch
    x = cx + radius * math.cos(angle)
    y = cy + radius * math.sin(angle)
    return x, y


def line_positions_windowed_spiral(primes, lo, span, period, base_radius=800.0, pitch=800.0, cx=0.0, cy=0.0):
    """Spiral-layout counterpart of line_positions_windowed_ring: same
    binary-search filter down to [lo, lo+span], but each surviving value
    is placed via value_to_spiral_xy's own lap+phase math instead of a
    single circle's plain span-normalized angle -- see that function's
    own doc-comment for the full rationale. Vectorized floordiv/mod on
    the (possibly object-dtype, real-archive-scale) filtered array, same
    "exact integer arithmetic first, cast to float64 only for the small
    per-lap phase/lap values" discipline line_positions itself uses.

    Returns the same {"x", "y", "lo", "span"} shape the other line_
    positions_windowed_* variants do."""
    primes_arr = to_prime_array(primes)
    hi = lo + span
    start = int(np.searchsorted(primes_arr, lo, side="left"))
    end = int(np.searchsorted(primes_arr, hi, side="right"))
    windowed = primes_arr[start:end]
    delta = windowed - lo
    lap = delta // period
    phase = delta % period
    t = phase.astype(np.float64) / period
    angle = -np.pi / 2.0 + t * 2.0 * np.pi
    radius = base_radius + lap.astype(np.float64) * pitch
    x = cx + radius * np.cos(angle)
    y = cy + radius * np.sin(angle)
    return {"x": x, "y": y, "lo": lo, "span": span}


def spiral_outer_radius(span, period, base_radius=800.0, pitch=800.0):
    """The radius of the OUTERMOST lap a window of `span` (range_hi -
    range_lo, or the currently rendered slice's own span) reaches under
    value_to_spiral_xy/line_positions_windowed_spiral's own lap math --
    `span // period` is the highest lap index any value in [lo, lo+span]
    can land on (mirrors that function's own `lap = (value - lo) //
    period`, evaluated at the window's own far edge). Used to size the
    curved-axis boundary marker (line_draw.axis_boundary_marker_
    vertices) so the single red radial line reaches all the way out to
    the last lap actually drawn -- see value_to_spiral_xy's own doc-
    comment for why one straight line at a fixed angle already crosses
    every lap's own phase-zero point, without a separate marker per lap.

    `span <= 0` (a degenerate/empty window) returns `base_radius` alone
    (lap 0, the innermost/only circle) rather than raising."""
    if span <= 0:
        return base_radius
    max_lap = span // period
    return base_radius + max_lap * pitch


def pattern_positions_and_match(n, offsets, primes_window_set):
    """positions = [n+o for o in offsets]; hit_flags[i] = positions[i] is a
    member of `primes_window_set`; all_match = every offset hit (False,
    not vacuously True, when `offsets` is empty -- there is no pattern to
    have matched)."""
    positions = [n + o for o in offsets]
    hit_flags = [p in primes_window_set for p in positions]
    all_match = bool(hit_flags) and all(hit_flags)
    return positions, hit_flags, all_match


#: Shared with session.py's founding-coincidence check (whether one of these small
#: primes is ITSELF a real match this wheel would otherwise exclude) -- one definition
#: so the two never drift apart.
DEFAULT_WHEEL_PRIMES = (2, 3, 5, 7, 11, 13)


def pattern_wheel_residues(offsets, wheel_primes=DEFAULT_WHEEL_PRIMES):
    """The residue-class "wheel" for a k-tuple pattern: which values of
    n mod M (M = product of the wheel primes that actually exclude
    something) can EVER produce a match, purely from small-prime
    divisibility -- no primality test involved. For each prime p in
    `wheel_primes`, a residue r is excluded if any offset lands on a
    multiple of p (n+offset ≡ 0 mod p, hence composite for any n past p
    itself); primes that exclude nothing are dropped from the wheel
    entirely (they'd only inflate M for no filtering benefit).

    Returns (modulus, sorted_residues). `sorted_residues` can be EMPTY --
    that is not a bug, it means every residue mod some wheel prime is
    forced composite, i.e. this exact offset pattern can never repeat
    again past its own founding coincidence (see
    pattern_offsets_from_seed(3, 3)'s own [0, 2, 4] case: 3,5,7 works
    once only, because 3 itself is the forced multiple of 3 -- prime, not
    composite -- an exception pure residue arithmetic can't see). A
    pattern built by pattern_offsets_from_seed is otherwise guaranteed at
    least one surviving residue per prime (it already occurred once for
    real), and CRT guarantees a nonempty COMBINED residue set whenever
    every individual prime has at least one -- see this function's own
    call site in RenderSession for how a caller distinguishes "empty on
    purpose" (this docstring's exception) from "no filtering possible"
    (modulus == 1, nothing in `wheel_primes` excluded anything)."""
    used_primes = []
    per_prime_allowed = []
    for p in wheel_primes:
        allowed = [r for r in range(p) if not any((r + o) % p == 0 for o in offsets)]
        if len(allowed) < p:
            used_primes.append(p)
            per_prime_allowed.append(allowed)
    if not used_primes:
        return 1, [0]
    modulus = 1
    for p in used_primes:
        modulus *= p
    residues = [
        r for r in range(modulus)
        if all(r % p in allowed for p, allowed in zip(used_primes, per_prime_allowed))
    ]
    return modulus, residues


def next_wheel_n(n, is_right, modulus, residues, lo, hi):
    """The next wheel-compatible position strictly beyond `n` -- smallest
    such position if `is_right`, largest if not -- clamped to [lo, hi].
    "Wheel-compatible" means `position % modulus` is one of `residues`
    (pattern_wheel_residues' own output, sorted ascending).

    `lo`/`hi` are ONLY the search window's bounds, never a phase
    reference: `residues` are ABSOLUTE `n mod p` conditions (a member is
    forced divisible by p because of n's own real value, nothing to do
    with wherever the loaded window happens to start), so checking
    `(n - lo) % modulus` instead of plain `n % modulus` would silently
    shift the whole candidate sequence by `lo` -- wrong the moment `lo`
    isn't itself a multiple of `modulus` (which it essentially never is, e.g.
    `lo=2` from a Load Range starting at 1); for k=2 the candidates must follow the
    twin-prime CRT condition "n == 5 mod 6" in absolute terms.

    Returns `n` UNCHANGED (never raises) when there is no such position:
    either the window edge was reached, or `residues` is empty -- the
    pattern's own wheel proved it can never repeat at all (see
    pattern_wheel_residues' own doc-comment) -- in which case every call
    ever returns `n` unchanged, same as being permanently at the edge.

    O(log len(residues)) via bisect (`residues` is already sorted) rather than a
    linear scan -- RenderSession's seek (_pattern_seek) can call this many times in
    a single frame hunting for the next MATCH! or non-match."""
    if not residues:
        return n
    period_pos = n % modulus
    base = n - period_pos
    if is_right:
        idx = bisect.bisect_right(residues, period_pos)
        candidate = base + residues[idx] if idx < len(residues) else base + modulus + residues[0]
    else:
        idx = bisect.bisect_left(residues, period_pos)
        candidate = base + residues[idx - 1] if idx > 0 else base - modulus + residues[-1]
    if candidate < lo or candidate > hi:
        return n
    return candidate


def resolve_pattern_anchor(seed_prime, offsets, lo, hi):
    """Where "line" viz-mode's pattern anchor should start, given
    `--pattern-seed-start`'s resolved occurrence (`seed_prime`, from
    next_prime_at_or_above) and the loaded window's own bounds
    (`lo`/`hi` -- range_primes[0] and range_primes[-1] - offsets[-1]).

    `--pattern-seed-start` only picks the pattern's SHAPE (which offset
    variant) -- a small seed like 7 or 11 works identically whether
    `--load-range` is a tiny local span or a real archive-scale window
    (e.g. [10**22, 10**23]) nowhere near it. If the seed's own occurrence
    genuinely falls inside [lo, hi], start there -- an immediate,
    guaranteed real MATCH! (pattern_offsets_from_seed built the offsets
    FROM this exact occurrence). Otherwise, DON'T just clamp to `lo` --
    that is an arbitrary value with no guarantee of being wheel-
    compatible at all. Compute the phase (pattern_wheel_residues) and jump straight
    to the first wheel-compatible candidate at or past `lo`, via next_wheel_n, so
    scrubbing from there on is phase-aligned from the first frame."""
    if lo <= seed_prime <= hi:
        return seed_prime
    modulus, residues = pattern_wheel_residues(offsets)
    if modulus <= 1:
        return lo
    return next_wheel_n(lo - 1, True, modulus, residues, lo, hi)


def clamp_pattern_anchor(n, range_from, range_to, offsets):
    """Keeps the pattern's anchor `n` inside [range_from, range_to -
    offsets[-1]] so the pattern's own last member never scrubs past the
    loaded line-mode window -- there is no real prime data beyond it to
    check against, so a position out there would otherwise render as a
    fabricated miss. No-op (returns `n` unchanged) when `offsets` is
    empty -- there is no diameter to keep inside the window."""
    if not offsets:
        return n
    hi = range_to - offsets[-1]
    return max(range_from, min(n, hi))
