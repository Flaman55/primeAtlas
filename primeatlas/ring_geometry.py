"""
ring_geometry.py -- pure numpy port of Structural Sieve's drum/ring geometry
(js/core/SieveModel.js + js/render/DrumRenderer.js in the RelationalMathematics
repo), independent of the browser app. This is the math half only: given a
sorted array of primes and a step N, compute where every ring's single "hit
tooth" sits in 2D space. No rendering, no I/O, no tkinter dependency -- same
convention as every other module in this package except settings_tab.py/
benchmark_tab.py/primes_tab.py/widgets.py (see this package's __init__.py's
own docstring) -- see primeatlas/ring_viz/renderer.py for the GPU-rendered
interactive consumer of this module's output.

Why this exists: Artur's proposal (2026-09-04) is that PrimeAtlas's own prime
storage ("magazyn") plus native compute/GPU could drive this same ring
visualization at a scale a browser tab never could. A standalone feasibility
prototype (structural_rings_poc.py, this file's original form before landing
in this package -- see PLAN.md's "Feasibility already confirmed" section)
was built and run on Artur's real hardware BEFORE this plan was written: 20
million rings, loaded in 0.27s, pan/zoom held 50+ fps even at a fast scroll,
N-change rebuild ~1.3s. This module is the "port the math correctly" half of
that already-proven result; get this wrong and nothing built on top of it
means anything.

Ported formulas (see SieveModel.js/DrumRenderer.js for the original JS +
Artur's own design-history comments on each -- not reproduced here to avoid
two copies drifting apart; this file trusts that one as the reference and
just translates it):

  - Ring i (0-indexed, ascending prime order) among `count` active rings has
    radius = max_radius * ((i+1)/count) ** 0.85               (DrumRenderer.draw)
  - Its single drawn "tooth" sits at phase = n % prime, angle =
    phase * 2*pi/prime - pi/2                                  (DrumRenderer.#drawRingTeeth)
  - "Active" rings at step n = every prime <= n (sequential mode -- the only
    mode this module ports; SieveModel.js's "range" mode, a fixed already-
    loaded slice, is a trivial special case of "the caller decides which
    primes array to pass in", so it needs no separate code path here).
  - Bertrand window: primeValue in (floor(n/2), n]              (isBertrandWindowMember)
  - Legendre level k: floor(sqrt(n-1)) for n>=2, else 0          (legendreLevelAt)
  - Legendre window: primeValue in (k*k, n]                      (isLegendreWindowMember)
  - General Law tent factor: piecewise-linear, 0 at theta=0.1,
    1 at theta=0.5, 0 at theta=1                                 (#generalLawTentFactor)
  - General Law window (stepped mode): lo = n - (n - k*k)*factor,
    clamped to lo < n; (sliding mode): lo = max(0, n - n**theta)
    (generalLawWindowBounds)

All functions below are vectorized (numpy arrays in, numpy arrays out) so they
stay cheap at the ring counts this feature exists to push (millions to tens
of millions) -- a Python-level loop per ring would defeat the entire point of
the GPU-scale ring count already proven feasible.
"""

import math
import re

import numpy as np

UINT64_MAX = (1 << 64) - 1


def to_prime_array(values):
    """[ADDED 2026-09-12, Artur's report: a real magazyn floor (10p25/10p27,
    ~10**25-10**27 in magnitude) overflowed the old hardcoded `dtype=np.int64`
    cast every one of this module's (and renderer.py's) prime-handling
    functions used to do independently] Converts an ascending sequence of
    nonnegative prime values into the cheapest numpy dtype that holds every
    value EXACTLY:

      - `uint64` (native, vectorized, same speed as the old `int64` path for
        anything that actually fits -- doubles int64's own ~9.2e18 ceiling to
        ~1.8e19 for free, purely by dropping the sign bit primes never used)
        when the largest value fits.
      - plain-Python-int `object` dtype otherwise -- exact at any magnitude
        (a real piętro 25/27 prime included), just slower per-element (numpy
        dispatches object-dtype ufuncs through Python's own int arithmetic
        instead of native SIMD) since there is no fixed-width integer type
        that could hold a 25+-digit value at all.

    Artur's own ask (2026-09-12): default to the fast path, only pay the
    slow path's cost for the specific data that actually needs it -- so this
    is checked ONCE here (via the last element, since callers always pass an
    ascending sequence) rather than every downstream function re-deciding
    it independently. Already-canonical input (an ndarray already dtype
    uint64 or object) is returned as-is, no re-copy -- this function is cheap
    to call at the top of every function that used to hardcode the int64
    cast, including ones that will see the SAME array call after call.

    An already-array `values` that is neither uint64 nor object is (e.g. the
    old default int64, or a plain Python list) re-cast the slow way (`int(x)`
    per element) only when its own dtype can't cheaply prove every element
    fits uint64 -- negligible cost next to the actual load/render work this
    feeds into."""
    if isinstance(values, np.ndarray) and values.dtype in (np.uint64, object):
        return values
    n = len(values)
    if n == 0:
        return np.empty(0, dtype=np.uint64)
    last = values[-1]
    last = int(last) if not isinstance(last, np.integer) else int(last)
    if 0 <= last <= UINT64_MAX:
        return np.asarray(values, dtype=np.uint64)
    return np.asarray([int(v) for v in values], dtype=object)


_PARSE_INT_RE = re.compile(r'^[+-]?\d+$')
# Mantissa is OPTIONAL (defaults to 1) so a bare "10**25"/"10^25" (Artur's
# own shorthand for "piętro 25 starts here") parses the same as "1*10**25".
_PARSE_POW_RE = re.compile(r'^(?:([+-]?\d+)\s*\*\s*)?10\s*(?:\*\*|\^)\s*([+-]?\d+)$')
_PARSE_SCI_RE = re.compile(r'^([+-]?\d+)(?:\.(\d+))?\s*[eE]\s*([+-]?\d+)$')


def parse_big_int(text):
    """[ADDED 2026-09-12, Artur's own ask: "pisanie 25 zer nie jest
    przyjemne"] Parses a Python int from `text`, accepting whichever of these
    forms is most convenient to type for a value at a real magazyn floor's
    magnitude (piętro 25 alone needs 26 digits):

      - plain digits, optionally with `_` group separators (Python's own
        integer-literal convention, e.g. "1_000_000") -- reproduces bare
        `int()` behavior for anything that already parses that way.
      - `a*10**b` or `a*10^b` ("mathematical/informatyczna" exponent forms
        Artur named directly) -- e.g. "6*10**20", "6 * 10 ^ 20".
      - scientific notation `aEb` / `a.fEb` -- e.g. "6e20", "1.5E25".

    Always computed with exact Python integer arithmetic (`int(...) *
    10**exponent`, decimal-point cases shift digits instead of dividing) --
    NEVER via `float(text)`, which would silently round a value like this at
    the 15-17th significant digit, exactly where a piętro-25+ value's own
    precision matters. Raises ValueError (naming the rejected text, same
    contract as `int()` itself) for anything else, so existing "invalid
    field" handling around a bare `int()`/`.isdigit()` call needs no change
    beyond swapping in this function."""
    s = text.strip().replace('_', '')
    if not s:
        raise ValueError(f"parse_big_int: empty value {text!r}")
    if _PARSE_INT_RE.match(s):
        return int(s)
    m = _PARSE_POW_RE.match(s)
    if m:
        mantissa = int(m.group(1)) if m.group(1) is not None else 1
        exponent = int(m.group(2))
        if exponent < 0:
            raise ValueError(f"parse_big_int: negative exponent in {text!r}")
        return mantissa * (10 ** exponent)
    m = _PARSE_SCI_RE.match(s)
    if m:
        int_part, frac_part, exponent = m.group(1), m.group(2) or '', int(m.group(3))
        exponent -= len(frac_part)
        if exponent < 0:
            raise ValueError(f"parse_big_int: {text!r} is not a whole number")
        return int(int_part + frac_part) * (10 ** exponent)
    raise ValueError(
        f"parse_big_int: not a recognized integer (plain digits, a*10**b, a*10^b, "
        f"or aEb expected): {text!r}"
    )


def ring_radii(count, max_radius):
    """radius array for `count` rings, ring i (0-indexed) at
    max_radius * ((i+1)/count) ** 0.85 -- see DrumRenderer.draw's `radius` line.
    Returns an empty array for count == 0 (no division-by-zero: numpy just
    returns an empty result for an empty `idx`)."""
    if count == 0:
        return np.empty(0, dtype=np.float64)
    idx = np.arange(1, count + 1, dtype=np.float64)
    t = idx / count
    return max_radius * np.power(t, 0.85)


def ring_positions(primes, n, max_radius, cx=0.0, cy=0.0):
    """Vectorized port of DrumRenderer's per-frame ring-position computation.

    `primes` -- ascending 1-D array (any int dtype) of every ACTIVE prime at
        step n (i.e. already filtered to primes <= n by the caller -- this
        function does not filter, so a caller keeping the full sorted array
        in memory should slice it first, the same way SieveModel.js's
        `primesUpTo(n)` already returns a pre-filtered ascending view rather
        than this module re-deriving it).
    `n` -- the current step (Python int, may exceed float64 precision for
        very large N -- see the phase computation note below).
    `max_radius`, `cx`, `cy` -- same meaning as DrumRenderer.draw's
        `maxRadius`/`cx`/`cy` (already resolved from canvas size * zoomValue
        and pan offset by the caller; this function has no opinion on camera).

    Returns a dict of same-length numpy arrays: x, y (position of each ring's
    single hit tooth), phase (n % prime), is_hit (phase == 0, i.e. this ring's
    tooth currently sits exactly at its "top" -- DrumRenderer's gold/orange
    dot case), radius, angle. Caller decides colors/highlighting on top of
    this (kept out of this module -- see module docstring: this is geometry
    only, same split as DrumRenderer.js deliberately not importing SieveModel.js).

    Phase precision note: `n % primes` needs EXACT integer modulo, not a
    float64 approximation, for `is_hit` (phase == 0) to ever be correct at
    real magazyn scale -- see to_prime_array's own doc-comment for why
    `primes_arr` itself is uint64 (fast, native, the common case, good for
    primes up to ~1.8e19) or `object` (exact Python ints, the slower
    fallback a real piętro 25+ value needs; see that function's own
    doc-comment for why the cost is only ever paid when actually needed).

    [FIXED 2026-09-12, found by Artur's own report of a magazyn floor
    (10p25/10p27) crash while testing today's arbitrary-range feature] The
    OLD code here unconditionally reduced n via `n_int % (1 << 63)` before
    ever taking it mod a prime -- silently WRONG (not just imprecise) for
    any `n >= 2**63`, since `(n % 2**63) % p != n % p` in general (nothing
    makes 2**63 a multiple of an arbitrary prime p). That reduction was only
    ever a no-op safety net for n already < 2**63 (this project's entire use
    of ring_viz until real high-floor data existed) -- never a valid
    shortcut for n at or past it, which real piętro 25+ viewing needs `n`
    to reach. Replaced below with a dtype-aware branch: `primes_arr` uint64
    AND `n` fits uint64 keeps the exact old fast vectorized `np.mod` path
    (unchanged cost, unchanged result for every case that already worked);
    anything past either ceiling routes through one `object`-dtype `np.mod`
    call (numpy dispatches this via Python's own exact int `%` per element
    -- correct at any magnitude, paid only in this branch)."""
    count = len(primes)
    if count == 0:
        empty = np.empty(0, dtype=np.float64)
        return {
            "x": empty, "y": empty, "phase": empty.astype(np.uint64),
            "is_hit": empty.astype(bool), "radius": empty, "angle": empty,
        }

    primes_arr = to_prime_array(primes)
    radius = ring_radii(count, max_radius)

    n_int = int(n)
    if primes_arr.dtype == object or n_int > UINT64_MAX:
        phase = np.mod(n_int, primes_arr.astype(object) if primes_arr.dtype != object else primes_arr)
        if primes_arr.dtype != object:
            # primes all fit uint64 (only n itself was the oversized operand
            # above) -- phase < prime <= UINT64_MAX always, so it is safe (and
            # keeps every downstream consumer, e.g. build_vertex_data's own
            # `primes_arr >= 11` comparisons, on the cheap native dtype) to
            # bring the RESULT back down once the exact object-dtype mod
            # above has already done the actual work correctly.
            phase = phase.astype(np.uint64)
    else:
        phase = np.mod(np.uint64(n_int), primes_arr)

    angle = phase.astype(np.float64) * (2.0 * np.pi) / primes_arr.astype(np.float64) - (np.pi / 2.0)
    x = cx + radius * np.cos(angle)
    y = cy + radius * np.sin(angle)
    is_hit = phase == 0

    return {"x": x, "y": y, "phase": phase, "is_hit": is_hit, "radius": radius, "angle": angle}


def legendre_level_at(n):
    """k such that k*k < n <= (k+1)*(k+1); 0 for n <= 1.
    Ports SieveModel.legendreLevelAt (see its own doc-comment for the
    off-by-one-at-perfect-squares history -- floor(sqrt(n-1)), NOT
    floor(sqrt(n)))."""
    if n <= 1:
        return 0
    return int(np.floor(np.sqrt(n - 1)))


def is_bertrand_member(primes, n):
    """Vectorized port of isBertrandWindowMember: primeValue in (floor(n/2), n]."""
    primes_arr = np.asarray(primes)
    lo = n // 2
    return (primes_arr > lo) & (primes_arr <= n)


def is_legendre_member(primes, n):
    """Vectorized port of isLegendreWindowMember: primeValue in (k*k, n]."""
    primes_arr = np.asarray(primes)
    k = legendre_level_at(n)
    lo = k * k
    return (primes_arr > lo) & (primes_arr <= n)


def general_law_tent_factor(theta):
    """Piecewise-linear tent: 0 at theta=0.1, 1 at theta=0.5, 0 at theta=1.
    Ports SieveModel.#generalLawTentFactor exactly (see that method's own
    doc-comment for why the two legs are not symmetric in raw theta units)."""
    if theta >= 0.5:
        return (1 - theta) / 0.5
    return (theta - 0.1) / 0.4


def general_law_window_bounds(n, theta, mode):
    """Ports SieveModel.generalLawWindowBounds. Returns (lo, hi, k, factor)
    with the same null-as-None conventions as the JS version (k/factor are
    None where the JS returns null)."""
    k = None
    factor = None
    if mode == "stepped":
        legendre_k = legendre_level_at(n)
        k = legendre_k
        if legendre_k == 0:
            lo = 0.0
        else:
            legendre_lo = legendre_k * legendre_k
            factor = general_law_tent_factor(theta)
            lo = n - (n - legendre_lo) * factor
            if lo >= n:
                lo = n - 1
    else:
        lo = n - (n ** theta)
        if lo < 0:
            lo = 0.0
    return lo, n, k, factor


def is_general_law_member(primes, n, theta, mode):
    """Vectorized port of isGeneralLawWindowMember."""
    primes_arr = np.asarray(primes)
    lo, hi, _k, _factor = general_law_window_bounds(n, theta, mode)
    return (primes_arr > lo) & (primes_arr <= hi)


# ---------------------------------------------------------------------------
# Highlight-color blending -- [ADDED Faza 1, PLAN.md] ports
# StructuralSieveApp.js's #windowHighlightFamilies / #computeHighlightColor /
# #computeTrackedColor / #activeWindowCount into vectorized numpy form. See
# that file for the full design rationale (Artur's own quotes on why the
# blend is additive-RGB). Legendre's own highlight test USED to be a
# separate "sticky" variant (is_legendre_highlighted, since removed -- see
# compute_highlight_colors' own 2026-09-11 doc-comment for why: it produced
# a false-positive green band nearly as wide as Bertrand's own window).
# The JS versions operate per single (n, prime) pair, called once per ring
# per animation tick; this module instead computes highlight color for EVERY
# active ring at once (a whole-frame batch), which is what the ring-count
# scale this feature exists for actually needs -- a Python-level loop over
# millions of rings would defeat that scale the same way it would for
# ring_positions() above.
# ---------------------------------------------------------------------------

#: Same three families, same colors, as StructuralSieveApp.js's
#: #windowHighlightFamilies registry (bertrand=#ff33cc, legendre=#39ff14,
#: generalLaw=#a855f7). A caller enables a subset via `enabled_ids` on the
#: functions below -- this list itself never needs to change to add/remove a
#: family from a given render, only to add an entirely new family type.
WINDOW_FAMILY_COLORS = {
    "bertrand": (255, 51, 204),
    "legendre": (57, 255, 20),
    "generalLaw": (168, 85, 247),
}


def _window_bounds_for_label(family_id, n, theta, mode):
    """[ADDED 2026-09-10] The (lo, hi) integer bounds of `family_id`'s own
    window at this N -- used only for GROUPING window HUD labels by
    coincidence (see window_label_colors below), NOT the source of truth
    for the HUD text itself (that stays in renderer.py's hud_lines_for_n,
    computed independently -- duplicated on purpose, same "small
    self-contained function over a shared derivation" tradeoff already
    made for window_anchor_primes above, so a bug here can't silently
    corrupt the printed window-range text)."""
    if family_id == "bertrand":
        return (n // 2, n)
    if family_id == "legendre":
        k = legendre_level_at(n)
        return (k * k, n)
    if family_id == "generalLaw":
        lo, hi, _k, _factor = general_law_window_bounds(n, theta, mode)
        return (int(np.floor(lo)), int(hi))
    raise ValueError(f"unknown window family id {family_id!r}")


def window_label_colors(enabled_ids, n, theta=0.5, mode="stepped"):
    """[ADDED 2026-09-10, see Artur's report: "daj kolory podpisow w hud
    zgodnie z kolorem pierscieni dla okien... i oby zmienialy na wspolny
    tak jak pierscien zmienia gdy zakres okna sie pokrywa"] Colors for the
    HUD's window-range text lines (e.g. "Bertrand window: (70, 141]"),
    mirroring compute_highlight_colors' additive-RGB blend but applied to
    whole TEXT LABELS instead of individual rings: each enabled family's
    label normally gets that family's own WINDOW_FAMILY_COLORS entry, so
    the color alone tells you which line is which -- but when two or more
    enabled families' windows are the exact same (lo, hi) range at this N,
    their labels collapse to ONE shared additively-blended color instead,
    the same visual cue a ring itself gets when it strictly matches more
    than one family (see compute_highlight_colors).

    Grouping is by EXACT bound equality, not "any overlap": every enabled
    family's window always ends at n, so a naive overlap test would
    trivially fire for any 2+ enabled families and defeat the whole point
    (telling them apart). Exact equality is the real, meaningful
    coincidence -- e.g. General Law at theta=0.5 in stepped mode is
    *provably* identical to Legendre's own window (general_law_window_
    bounds' own doc-comment / task #577), so enabling both together merges
    their two labels into one blended color; Bertrand's much wider
    (n//2, n] window essentially never coincides with either, so it stays
    solid pink on its own.

    Returns dict family_id -> (r, g, b) int 0-255 tuple, one entry per id
    in `enabled_ids` that is a real WINDOW_FAMILY_COLORS key (unknown ids
    are silently skipped, same permissive convention window_anchor_primes
    uses)."""
    groups = {}
    for family_id in enabled_ids:
        if family_id not in WINDOW_FAMILY_COLORS:
            continue
        bounds = _window_bounds_for_label(family_id, n, theta, mode)
        groups.setdefault(bounds, []).append(family_id)

    result = {}
    for family_ids in groups.values():
        if len(family_ids) == 1:
            result[family_ids[0]] = tuple(int(c) for c in WINDOW_FAMILY_COLORS[family_ids[0]])
        else:
            summed = np.zeros(3, dtype=np.float64)
            for fid in family_ids:
                summed += np.asarray(WINDOW_FAMILY_COLORS[fid], dtype=np.float64)
            np.clip(summed, 0, 255, out=summed)
            blended = tuple(int(round(c)) for c in summed)
            for fid in family_ids:
                result[fid] = blended
    return result


def _largest_below(sorted_arr, bound):
    """Largest element of ascending `sorted_arr` strictly less than `bound`,
    or None if none exists. Ports SieveModel's private #largestBelow binary
    search via np.searchsorted (equivalent asymptotics, no Python-level loop)."""
    if len(sorted_arr) == 0:
        return None
    idx = np.searchsorted(sorted_arr, bound, side="left")
    return int(sorted_arr[idx - 1]) if idx > 0 else None


def bertrand_anchor_at(primes, n):
    """Ports SieveModel.bertrandAnchorAt: the frozen/jumping Bertrand witness
    at step n (see that method's own doc-comment for the freeze/jump rule).
    Returns a single int or None (no active primes yet)."""
    primes_arr = to_prime_array(primes)
    if len(primes_arr) == 0:
        return None
    anchor = int(primes_arr[0])
    while n >= 2 * anchor:
        candidate = _largest_below(primes_arr, 2 * anchor)
        if candidate is None or candidate <= anchor:
            break
        anchor = candidate
    return anchor


def legendre_anchor_at(primes, n):
    """Ports SieveModel.legendreAnchorAt: largest active prime strictly below
    the current level's own opening edge k*k. Returns None if none exists
    (k in {0,1})."""
    primes_arr = to_prime_array(primes)
    if len(primes_arr) == 0:
        return None
    k = legendre_level_at(n)
    return _largest_below(primes_arr, k * k)


def general_law_anchor_at(primes, n, theta, mode):
    """Ports SieveModel.generalLawAnchorAt: largest active prime at or below
    the window's own current opening edge `lo` (computed as "strictly below
    floor(lo)+1", equivalent for integer primes -- see the JS method's own
    doc-comment)."""
    primes_arr = to_prime_array(primes)
    if len(primes_arr) == 0:
        return None
    lo, _hi, _k, _factor = general_law_window_bounds(n, theta, mode)
    return _largest_below(primes_arr, int(np.floor(lo)) + 1)


ANCHOR_FUNCTIONS = {
    "bertrand": lambda primes, n, theta, mode: bertrand_anchor_at(primes, n),
    "legendre": lambda primes, n, theta, mode: legendre_anchor_at(primes, n),
    "generalLaw": lambda primes, n, theta, mode: general_law_anchor_at(primes, n, theta, mode),
}


def cyclic_window_anchor_at(anchor_state, family_id, primes, n, theta=0.5, mode="stepped"):
    """[ADDED 2026-09-11] Legendre/General Law's own tracked-ring anchor --
    NOT a port of anything in SieveModel.js, a new design of Artur's that
    REPLACES legendre_anchor_at/general_law_anchor_at for this purpose
    (those two functions and ANCHOR_FUNCTIONS above are untouched and still
    used for Bertrand, and still exist in their own right -- only the
    renderer.py call sites that feed the tracked-ring OUTLINE now use this
    function instead for "legendre"/"generalLaw").

    Artur's report, 2026-09-11: Bertrand's freeze/jump rule (jump only once
    n >= 2*anchor) gives a clean "wait for every pink prime below the
    tracked ring to reach the vertical red line, then jump" effect on its
    own wide (n/2, n] window -- but Legendre/General Law's window is only a
    few dozen points wide near the start of the axis (and narrows further
    as N grows), too narrow for that same 2x-doubling condition to ever
    fire sensibly. legendre_anchor_at/general_law_anchor_at's plain
    per-call recomputation (whatever prime currently sits at the window's
    own edge) was a first attempt at mimicking Bertrand's effect there, but
    it does not actually hold the tracked ring still long enough to show
    anything -- it can select a different ring almost every step.

    New rule (Artur's own words, kept close to verbatim): "nowe okno to
    aktualne n i ono ma ten swoj pierscien i on nie zmienia sie gdy nie
    stanie sie skrajna lewa strona okna i w nastepnym kroku wpada na swoja
    skrajna wartosc prawej strony okna i znow leci w lewa strone i cykl sie
    powtarza" -- the anchor freezes at the window's own RIGHT edge (the
    largest active prime <= n) the moment a new window opens, and stays
    frozen there for as long as that SAME window is still open, drifting
    toward the window's own left side only in the sense that newer, bigger
    rings keep entering to its right while it stays put; once the window
    closes (a NEW one opens) the anchor re-freezes at the new window's own
    right edge, and the cycle repeats.

    What "a new window opens" means differs by family, because Legendre's
    own `lo` (= k*k) is CONSTANT for the whole level, jumping in one
    discrete step only at each perfect-square level boundary -- there,
    "a new window opens" means legendre_level_at(n) itself changed.
    General Law's `lo` (general_law_window_bounds) is NOT constant per
    level in general: "sliding" mode has no level concept at all (`lo = n
    - n**theta` creeps up on every single n), and "stepped" mode's own
    `lo = n - (n - legendre_lo) * factor` (factor = general_law_tent_factor
    (theta)) reduces to Legendre's own constant-per-level `lo` ONLY at the
    exact tent peak theta=0.5 (factor == 1) -- for ANY other theta, factor
    < 1, so `lo` still creeps up continuously WITHIN a level (just slower
    than n itself, scaled by (1 - factor)), not just at level boundaries.

    [FIXED 2026-09-11, Artur's report: with Legendre AND General Law both
    on (theta != 0.5, stepped mode), the HUD showed two clearly DIFFERENT
    window ranges (e.g. Legendre (1156,1199], General Law theta=0.3
    (1177,1199]) yet only ONE ring appeared, in the additively-blended
    color, as if both anchors had coincided -- "mimo ze sa dwa rozne punkty
    startowe to jest tylko jeden pierscien". Root cause: this function used
    to route EVERY "stepped"-mode General Law call through the SAME level-
    keyed branch as Legendre, regardless of theta -- since that branch's
    re-anchor trigger only looks at legendre_level_at(n) (never at General
    Law's own, theta-dependent `lo`), it produced the EXACT SAME anchor
    value as Legendre for every theta, not just theta=0.5. Fixed below: the
    level-keyed branch is now used for General Law only when its `lo`
    genuinely IS piecewise-constant per level (factor == 1.0, i.e.
    theta==0.5 exactly); any other theta in "stepped" mode now takes the
    same numeric-creep branch "sliding" mode already correctly used.]

      - family_id == "legendre", or "generalLaw" with mode == "stepped"
        AND theta == 0.5 exactly (factor == 1.0, `lo` piecewise-constant
        per level, identical to Legendre's own): keyed on
        legendre_level_at(n) -- re-anchor at the window's own right edge
        exactly when the level differs from the level the currently-frozen
        anchor was picked under (this is also why an immediate re-freeze
        right after re-anchoring is NOT a bug here: the newly-picked
        anchor's own level always matches the level that was just entered,
        so the very next call at the same level leaves it untouched).
      - family_id == "generalLaw" with mode == "sliding", OR "stepped" with
        any theta != 0.5: keyed on the numeric `lo` from
        general_law_window_bounds -- re-anchor whenever the frozen anchor
        is <= the CURRENT call's `lo` (which, since it creeps up by a
        little on every single n in both these cases, is what makes the
        anchor eventually "become the window's own left edge").

    `anchor_state` is a plain per-family-id dict the CALLER owns and keeps
    across rebuild_buffer calls (renderer.py's run() holds one, same
    convention as its own orbit_state/resonance_log_state dicts) -- this
    function is otherwise a pure function of (state, n). Calling it twice
    in a row with the same n is idempotent (the re-anchor condition, re-
    evaluated against the just-updated state, no longer holds). Calling it
    after an arbitrary FORWARD jump in n (goto/load range, not just a live-
    playback tick) self-corrects on that very call, since both the level
    and `lo` are always recomputed fresh from the actual current n rather
    than accumulated incrementally step by step.

    family_id must be "legendre" or "generalLaw" -- Bertrand has no cyclic
    state of its own and keeps using bertrand_anchor_at (via
    ANCHOR_FUNCTIONS) directly."""
    primes_arr = to_prime_array(primes)
    if family_id not in ("legendre", "generalLaw"):
        raise ValueError(f"cyclic_window_anchor_at does not support family_id {family_id!r}")

    if family_id == "legendre":
        # Legendre proper has no separate sliding variant (mirrors
        # ANCHOR_FUNCTIONS["legendre"] itself ignoring mode/theta) -- always
        # level-keyed.
        level_keyed = True
    else:
        # generalLaw: level-keyed ONLY when its own `lo` is provably
        # identical to Legendre's constant-per-level `lo` (see this
        # function's own 2026-09-11 doc-comment for why any other theta
        # must NOT take this branch).
        level_keyed = mode == "stepped" and general_law_tent_factor(theta) == 1.0

    entry = anchor_state.setdefault(family_id, {"anchor": None, "level": None})
    if level_keyed:
        level = legendre_level_at(n)
        if entry["anchor"] is None or entry["level"] != level:
            entry["anchor"] = _largest_below(primes_arr, n + 1)
            entry["level"] = level
    else:
        lo, _hi, _k, _factor = general_law_window_bounds(n, theta, mode)
        if entry["anchor"] is None or entry["anchor"] <= lo:
            entry["anchor"] = _largest_below(primes_arr, n + 1)
    return entry["anchor"]


def _blend_family_colors(masks_by_family):
    """Shared additive-RGB blend core used by both compute_highlight_colors
    and compute_tracked_colors below -- ports the summation half of
    #computeHighlightColor / #computeTrackedColor (channel sum, clamp to
    255), factored out because both JS methods do exactly this arithmetic
    and differ only in HOW each family's per-ring participation mask is
    derived (strict window membership for highlight color; plain anchor-
    equality for tracked color -- see the two callers below).

    `masks_by_family` -- dict of family_id -> boolean numpy array (same
    length, one entry per ring): True where that family contributes its
    color to that ring.

    Returns (colors, matched) -- colors is an (N, 3) float64 array (channel
    values already clamped to [0, 255], NOT yet cast to uint8 so a caller can
    still do further math before quantizing for a GPU buffer -- see
    build_vertex_data's own float32 buffer for why this module leaves that
    choice to the renderer), matched is an (N,) boolean array, True where at
    least one family contributed (the null/None case in the JS version)."""
    if not masks_by_family:
        n = 0
    else:
        n = len(next(iter(masks_by_family.values())))
    colors = np.zeros((n, 3), dtype=np.float64)
    matched = np.zeros(n, dtype=bool)
    for family_id, mask in masks_by_family.items():
        color = np.asarray(WINDOW_FAMILY_COLORS[family_id], dtype=np.float64)
        colors[mask] += color
        matched |= mask
    np.clip(colors, 0, 255, out=colors)
    return colors, matched


def compute_highlight_colors(primes, n, enabled_ids, theta=0.5, mode="stepped"):
    """Vectorized port of #computeHighlightColor for every ring in `primes`
    at once. `enabled_ids` is an iterable of family ids from
    WINDOW_FAMILY_COLORS currently toggled on (e.g. {"bertrand", "legendre"}).

    [CHANGED 2026-09-11, Artur's report: enabling ONLY Legendre showed green
    dots across a range as wide as Bertrand's own (n/2, n] window, even
    though the Legendre HUD label advertised a much narrower (k*k, n] range
    -- confirmed the culprit was is_legendre_highlighted's own "sticky"
    grace period (kept a ring green until it crossed its next self-multiple,
    which for most primes past the midpoint of their own level works out to
    almost exactly 2x their value -- i.e. reproducing Bertrand's own window
    shape by coincidence). That function is gone; Legendre's own highlight
    test is now exactly its strict membership test, same as Bertrand and
    General Law already were. With no family left having a distinct sticky
    variant, the strict/sticky two-tier precedence this function used to
    implement (see #computeHighlightColor in the JS reference for where
    that rule came from) had become a pure no-op, so it is gone too -- this
    now just blends whichever families STRICTLY match each ring.]

    Returns (colors, matched) -- see _blend_family_colors's own docstring for
    the exact shape; `matched[i] is False` is this function's counterpart to
    the JS version returning null for ring i."""
    primes_arr = to_prime_array(primes)
    count = len(primes_arr)

    strict_by_family = {}
    for family_id in enabled_ids:
        if family_id == "bertrand":
            strict = is_bertrand_member(primes_arr, n)
        elif family_id == "legendre":
            strict = is_legendre_member(primes_arr, n)
        elif family_id == "generalLaw":
            strict = is_general_law_member(primes_arr, n, theta, mode)
        else:
            raise ValueError(f"unknown window family id {family_id!r}")
        strict_by_family[family_id] = strict

    if not strict_by_family:
        return np.zeros((count, 3), dtype=np.float64), np.zeros(count, dtype=bool)

    return _blend_family_colors(strict_by_family)


def compute_tracked_colors(primes, n, enabled_ids, theta=0.5, mode="stepped", anchor_overrides=None):
    """Vectorized port of #computeTrackedColor: for each ring, sums the
    colors of every enabled family whose OWN anchor (bertrand_anchor_at /
    legendre_anchor_at / general_law_anchor_at, or `anchor_overrides` below)
    is exactly that ring's prime. Deliberately a DIFFERENT question from
    compute_highlight_colors (window membership) -- see that JS method's own
    doc-comment for the exact bug this distinction fixes (two different
    anchors collapsing to the same blended color because both happened to
    satisfy each other's window-membership test).

    `anchor_overrides` -- [ADDED 2026-09-11] optional {family_id: anchor}
    dict; when a family_id is a key here (even with value None), its value
    is used directly instead of calling ANCHOR_FUNCTIONS[family_id] -- this
    is how renderer.py feeds in cyclic_window_anchor_at's own stateful
    "legendre"/"generalLaw" anchors (see that function's own doc-comment)
    while Bertrand keeps resolving through ANCHOR_FUNCTIONS as before. A
    family_id absent from this dict falls back to ANCHOR_FUNCTIONS exactly
    as it always has, so passing None (the default) reproduces the old
    behavior unchanged.

    Returns (colors, matched) -- same shape as compute_highlight_colors."""
    primes_arr = to_prime_array(primes)
    count = len(primes_arr)

    masks = {}
    for family_id in enabled_ids:
        if anchor_overrides is not None and family_id in anchor_overrides:
            anchor = anchor_overrides[family_id]
        else:
            anchor = ANCHOR_FUNCTIONS[family_id](primes_arr, n, theta, mode)
        masks[family_id] = (primes_arr == anchor) if anchor is not None else np.zeros(count, dtype=bool)

    if not masks:
        return np.zeros((count, 3), dtype=np.float64), np.zeros(count, dtype=bool)
    return _blend_family_colors(masks)


def window_anchor_primes(primes, n, enabled_ids, theta=0.5, mode="stepped", anchor_overrides=None):
    """[ADDED 2026-09-10] Ports #renderFrame's anchor-collection loop:

        const anchors = [];
        for (const family of this.#windowHighlightFamilies) {
          if (!family.isOn()) continue;
          const a = family.anchorAt(this.#n);
          if (a !== null && !anchors.includes(a)) anchors.push(a);
        }
        this.#trackedPrimes = anchors;

    i.e. the deduplicated, order-preserving list of every ENABLED family's own
    anchor prime at n, in WINDOW_FAMILY_COLORS' own registry order (bertrand,
    legendre, generalLaw -- a plain dict preserves insertion order, same as
    the JS's #windowHighlightFamilies array order). This is what the JS
    unconditionally overwrites #trackedPrimes with whenever ANY window family
    is on (see that method's own doc-comment) -- ring_geometry.py had
    bertrand_anchor_at/legendre_anchor_at/general_law_anchor_at and
    compute_tracked_colors (the per-ring OUTLINE COLOR once a ring is already
    tracked) since Faza 1, but nothing yet computed WHICH rings should be
    tracked in the first place when a window family -- rather than a manual
    --track-primes list or auto-orbit -- is what's naming the anchor. Artur
    caught this gap directly: "pierscienie sa dla sledzonych i dla auto orbit
    ale nie ma dla bertranda legendre i dla general law" -- Bertrand/Legendre/
    General Law's own highlight color rendered fine (Faza 1), but their own
    anchor ring never got the gray/colored OUTLINE CIRCLE tracked rings and
    auto-orbit's current ring both get, because nothing ever added that
    anchor to the tracked set. See renderer.py's rebuild_buffer for the
    caller that wires this into effective_track_primes with the correct
    precedence (window anchors, when any family is on, take over from BOTH
    auto-orbit and a launch-time --track-primes list -- exactly like the JS's
    own `if (anyWindowOn) {...}` block runs unconditionally ahead of, and
    instead of, #advanceAutoOrbit).

    Returns [] if enabled_ids is empty -- caller falls back to whatever OTHER
    trackedPrimes source applies, mirroring the JS's own `if (anyWindowOn)`
    gate (no families on: this function contributes nothing, same as the JS
    block simply not running that turn).

    `anchor_overrides` -- [ADDED 2026-09-11] same {family_id: anchor} dict
    compute_tracked_colors accepts (see that function's own doc-comment) --
    a family_id present here (even with value None) uses that value
    directly instead of calling ANCHOR_FUNCTIONS[family_id], so renderer.py
    can feed cyclic_window_anchor_at's stateful "legendre"/"generalLaw"
    anchors through the exact same collection loop Bertrand still resolves
    through ANCHOR_FUNCTIONS."""
    if not enabled_ids:
        return []
    primes_arr = to_prime_array(primes)
    anchors = []
    for family_id in WINDOW_FAMILY_COLORS:
        if family_id not in enabled_ids:
            continue
        if anchor_overrides is not None and family_id in anchor_overrides:
            anchor = anchor_overrides[family_id]
        else:
            anchor = ANCHOR_FUNCTIONS[family_id](primes_arr, n, theta, mode)
        if anchor is not None and anchor not in anchors:
            anchors.append(anchor)
    return anchors


def active_window_count(enabled_ids):
    """Ports #activeWindowCount: trivial here since `enabled_ids` already IS
    the set of currently-on families (the JS version derives this by
    checking each family's isOn() closure; this module's callers pass the
    already-resolved set directly), kept as a named function purely so a
    caller mirrors the JS call site 1:1 rather than inlining `len(...)`."""
    return len(enabled_ids)


# ---------------------------------------------------------------------------
# Resonance -- [ADDED Faza 1, PLAN.md] ports SieveModel.resonanceEventsInRange,
# the bulk "goto catch-up" resonance-flash finder used by
# StructuralSieveApp's resonance log. See that JS method's own extensive
# doc-comment (SieveModel.js) for the full algorithm rationale and the
# long-standing toy bug it fixes (goto silently skipping every resonance
# event strictly before the jumped-to n). Ported here as a near-literal
# translation rather than further-vectorized, because the JS algorithm is
# itself already the efficient form (a marking pass, not O(range * primes)
# trial division) -- the one place numpy helps is the per-prime multiple
# marking (a slice increment instead of a per-multiple Python loop).
# ---------------------------------------------------------------------------

#: [ADDED 2026-09-12] Hard ceiling on resonance_events_in_range's own
#: O(to_n-from_n) marking-pass array -- 20M int64 entries is ~160MB, a
#: reasonable bound for a single scan; well past this, the algorithm's own
#: approach (dense per-n marking) is no longer viable regardless of memory,
#: see that function's own 2026-09-12 doc-comment for the real-world case
#: (a real magazyn-floor-scale range/tick) this actually guards against.
_RESONANCE_SCAN_MAX_SIZE = 20_000_000


def resonance_events_in_range(primes, from_n, to_n):
    """Every "resonance" step n in [from_n, to_n] (inclusive): n is a
    resonance step when every prime whose leading primorial product still
    fits under n also divides n (getStepState's own doc-comment has the
    full definition; this is the BULK finder for a whole span at once, not
    a per-n test).

    Returns a list of {"n": int, "factors": [int, ...]} dicts in ascending n
    order, factors listing every dividing prime for that n (same shape as
    the JS version's plain objects).

    [FIXED 2026-09-12, Artur's crash report: `ValueError: Maximum allowed
    dimension exceeded` at real magazyn-floor-25 scale] This function's own
    marking pass is O(to_n - from_n) by design (see the module comment just
    above it) -- fine at the small N/gaps this module was built around, but
    tick_next_n's own 2026-09-12 `range_step` fix (see that function's
    doc-comment) means a single range-mode tick's gap can now itself be
    ~10**21-sized once real magazyn-floor primes are loaded, which a dense
    `np.zeros(size, ...)` array can never hold. TWO guards below, cheapest
    first:
      1. A resonance step needs `primorial(smallest active prime) <= to_n`
         (see `thresholds` below) -- if even the SMALLEST active prime
         already exceeds to_n, NO resonance is possible ANYWHERE in this
         span, full stop, so this returns immediately without ever
         allocating anything. This is the exact case a real high-floor range
         hits on literally every tick (active primes ~10**25, to_n only
         ~10**21 for a long while) -- an O(1) check covers it for free.
      2. A hard cap on `size` itself, for any other combination that still
         slips past guard 1 (e.g. small-enough primes but an enormous gap
         some other way) -- past this, resonance events genuinely cannot be
         found by this algorithm's approach at all; returning [] (silently
         "nothing found," same contract as the to_n<from_n case just above)
         is correct behavior here, not a workaround -- a marking-pass scan
         over a span this size was never going to finish in this session
         regardless of memory, so there is no slower-but-correct fallback
         worth reaching for."""
    if to_n < from_n:
        return []
    primes_arr = to_prime_array(primes)
    if len(primes_arr) == 0 or int(primes_arr[0]) > to_n:
        return []
    size = to_n - from_n + 1
    if size > _RESONANCE_SCAN_MAX_SIZE:
        return []
    factor_count = np.zeros(size, dtype=np.int64)

    # Marking pass: for each active prime p, bump every multiple of p inside
    # [from_n, to_n] by 1 (a numpy slice add instead of the JS version's own
    # per-multiple loop -- same O((to_n-from_n) log log to_n) shape overall).
    for p in primes_arr:
        p_int = int(p)
        if p_int > to_n:
            break
        m = max(from_n, p_int)
        m += (p_int - (m % p_int)) % p_int  # round m up to the next multiple of p
        if m > to_n:
            continue
        start = m - from_n
        factor_count[start::p_int] += 1

    # maxResonance(n) only changes at the handful of n where the running
    # primorial crosses n (Python ints here, not int64, so this stays exact
    # well past where a naive int64 accumulator would silently overflow --
    # a correctness improvement over the JS version's plain float64 numbers,
    # though not one expected to matter at the N scale this module targets).
    thresholds = []
    primorial = 1
    for p in primes_arr:
        primorial *= int(p)
        if primorial > to_n:
            break
        thresholds.append(primorial)

    events = []
    threshold_idx = 0
    for offset in range(size):
        n = from_n + offset
        while threshold_idx < len(thresholds) and thresholds[threshold_idx] <= n:
            threshold_idx += 1
        max_resonance = threshold_idx
        count = int(factor_count[offset])
        if max_resonance > 0 and count >= max_resonance:
            factors = []
            for p in primes_arr:
                p_int = int(p)
                if p_int > n or len(factors) >= count:
                    break
                if n % p_int == 0:
                    factors.append(p_int)
            events.append({"n": n, "factors": factors})
    return events


# ---------------------------------------------------------------------------
# Resonance log + surviving-primes panel text -- [ADDED Faza 11, PLAN.md]
# ports StructuralSieveApp.js's #resonanceLog formatting and #renderLogPanel's
# text-truncation rules to plain strings for renderer.py's console-pane
# prints (NOT the on-canvas HUD/HUD_STATE path -- PLAN.md's Faza 11 entry is
# explicit this is a console-pane port, same precedent as the plain print()
# HUD lines Faza 4/7B already emit). No new math: resonance_log_lines is a
# thin formatter over resonance_events_in_range above; format_log_panel_text
# is generic and used for both the resonance-log lines and the raw
# surviving-primes list.
# ---------------------------------------------------------------------------

LOG_PANEL_TRUNCATE_THRESHOLD = 50  # mirrors JS's own LOG_PANEL_TRUNCATE_THRESHOLD


def resonance_log_lines(primes, from_n, to_n):
    """Ports #resonanceLog's own entry format exactly (`${e.n} = ${e.factors
    .join(" × ")}`) -- turns resonance_events_in_range's structured events
    for [from_n, to_n] into the same human-readable strings the HTML
    reference's Resonances panel shows, one per resonance step, ascending n
    order (resonance_events_in_range's own order, unchanged)."""
    events = resonance_events_in_range(primes, from_n, to_n)
    return [f"{e['n']} = {' × '.join(str(f) for f in e['factors'])}" for e in events]


def format_log_panel_text(items, threshold=LOG_PANEL_TRUNCATE_THRESHOLD):
    """Ports StructuralSieveApp.js's #renderLogPanel text-formatting rules
    (see that method's own doc-comment for the full rationale) for a plain
    console-pane line rather than a DOM panel with a live collapse/expand
    toggle: the console pane is a scrolling text stream, not an interactive
    widget, so there is nothing to click here -- this always renders the
    COLLAPSED view once a list exceeds `threshold` items (JS's own default
    state for a freshly rendered long panel), which is strictly more useful
    for a scrollback than dumping a potentially huge comma-separated line.

    Returns a (count, text) tuple: `count` is len(items) (for the caller's
    own "(count)" header, matching JS's `els.count.textContent`); `text` is
    "-" for an empty list, the full ", "-joined list at or below
    `threshold` items, or the first `threshold` items joined by ", "
    followed by " (+K more)" above it -- K is the omitted remainder,
    mirroring JS's own "+N more" wording (ss-log-panel-truncated)."""
    count = len(items)
    if count == 0:
        return count, "-"
    if count <= threshold:
        return count, ", ".join(str(x) for x in items)
    shown = items[:threshold]
    remaining = count - threshold
    return count, ", ".join(str(x) for x in shown) + f" (+{remaining} more)"


# ---------------------------------------------------------------------------
# Tracked primes -- [ADDED Faza 6, PLAN.md] foundation shared by Faza 7 (LCM/
# resonance HUD) and Faza 8 (tracked-ring outline circles/flash overlays).
# Ports the filtering half of StructuralSieveApp.js's #trackedResonanceState
# (see that method's own doc-comment): "which of the primes the user asked
# to track are actually active (born) yet at the current N". Deliberately
# does NOT port the LCM/phase/to-resonance computation itself -- that's
# Faza 7's own scope, kept separate so this foundation stays a pure,
# single-purpose filter usable by both later phases without either one
# depending on the other's math.
# ---------------------------------------------------------------------------

def filter_active_tracked(tracked, active_primes):
    """Which of `tracked` (an iterable of prime values, in whatever order the
    user entered them) are present in `active_primes` (the ring array's
    current active/born set at this N).

    Mirrors `#trackedResonanceState`'s own `tracked.filter((p) =>
    activePrimes.includes(p))` line exactly: preserves `tracked`'s original
    order (NOT sorted, NOT deduplicated beyond whatever duplicates the user
    typed) rather than active_primes's order, since the tracked list is a
    small, user-authored sequence where "the order Artur typed them in" is
    itself meaningful (e.g. for a future Track-P text field round-trip).

    Returns a plain list of ints -- deliberately not a numpy array, since
    the tracked list is always small (user-typed or capped, see Faza 7's
    own max_tracked) and every caller (HUD text formatting, LCM product)
    wants plain Python ints, not numpy scalars.
    """
    active_set = {int(p) for p in active_primes}
    return [int(p) for p in tracked if int(p) in active_set]


def tracked_ring_mask(primes, tracked):
    """Boolean mask into `primes` (an active ring array, same array
    ring_positions()/build_vertex_data() were called with) marking every
    ring whose OWN prime literally appears in `tracked`.

    Ports DrumRenderer's own per-ring `ring.tracked = trackedSet.has(r.prime)`
    (see StructuralSieveApp.js's per-frame ring-state construction) -- plain
    list membership, a DIFFERENT and narrower question from
    filter_active_tracked above: that function answers "which tracked VALUES
    are active" (used for the LCM/resonance HUD block, order-preserving,
    plain list); this one answers "which RING INDICES are tracked" so a
    caller can index a position/radius/color array (e.g.
    ring_geometry.ring_positions()'s own "radius" array) directly to draw
    something at each tracked ring's location -- see Faza 8 (tracked-ring
    outline circles) in PLAN.md for the caller.

    Returns an all-False bool array (length len(primes)) when `tracked` is
    empty, matching np.isin's own behavior against an empty second operand
    -- no special-casing needed, but spelled out here since an empty
    `tracked` is the common "nothing tracked yet" case."""
    primes_arr = to_prime_array(primes)
    if len(primes_arr) == 0 or not tracked:
        return np.zeros(len(primes_arr), dtype=bool)
    tracked_arr = to_prime_array(sorted(tracked))
    return np.isin(primes_arr, tracked_arr)


# ---------------------------------------------------------------------------
# Tracked-primes LCM/resonance -- [ADDED Faza 7A, PLAN.md] pure port of
# StructuralSieveApp.js's #trackedResonanceState / SieveModel.js's
# lcmOfListBig / #formatBig. See PLAN.md's own design note: the JS's
# bitmask/lookup-table idea does NOT apply here (its own cap defaults to
# 500 tracked primes, only tractable in the teens/twenties for a real
# lookup table) -- this is a straight product-based LCM port instead.
#
# Python has no Number/BigInt split -- `int` is already arbitrary-precision
# -- so unlike the JS (which keeps lcmOfList/lcmOfListBig as two separate
# implementations for a plain-Number fast path vs. an exact BigInt path)
# there is only one lcm_of_list here, and it is exact by construction.
# ---------------------------------------------------------------------------

def lcm_of_list(values):
    """LCM of a list of positive ints, or 0 for an empty list -- mirrors
    SieveModel.js's lcmOfList/lcmOfListBig (both return 0/0n for an empty
    list, not 1, so callers can use `lcm <= 0` as the same "nothing to
    show" signal the JS uses)."""
    values = [int(v) for v in values]
    if not values:
        return 0
    return math.lcm(*values)


def tracked_resonance_state(tracked, active_primes, n, auto_orbit=False,
                             max_tracked_for_exact_lcm=500):
    """Port of StructuralSieveApp.js's #trackedResonanceState -- the single
    computation behind both the HUD's tracked/LCM/phase/to-resonance lines
    and (in the JS) the live chime trigger.

    Returns None under the same conditions the JS returns null: auto_orbit
    is on, `tracked` is empty, or none of `tracked` is active yet at this N
    (via filter_active_tracked above -- same filtering, not reimplemented).
    Returns `{"too_large": True, "tracked": [...], "limit": ...}` when the
    tracked-and-active count exceeds max_tracked_for_exact_lcm (mirrors the
    JS's own device-calibrated cap, passed in here rather than calibrated,
    since there is no equivalent "how fast is this specific machine" probe
    on this side yet -- callers pick a value, see renderer.py's own default).
    Otherwise returns `{"tracked": [...], "lcm": int, "phase": int,
    "to_resonance": int}` -- plain Python ints throughout, no BigInt/Number
    distinction needed (see lcm_of_list's own doc-comment)."""
    if auto_orbit or not tracked:
        return None
    tracked_active = filter_active_tracked(tracked, active_primes)
    if not tracked_active:
        return None
    if len(tracked_active) > max_tracked_for_exact_lcm:
        return {"too_large": True, "tracked": tracked_active, "limit": max_tracked_for_exact_lcm}
    lcm = lcm_of_list(tracked_active)
    if lcm <= 0:
        return None
    n_int = int(n)
    phase = n_int % lcm
    to_resonance = 0 if phase == 0 else lcm - phase
    return {"tracked": tracked_active, "lcm": lcm, "phase": phase, "to_resonance": to_resonance}


def format_big(value, digit_threshold=15):
    """Port of StructuralSieveApp.js's #formatBig: below digit_threshold
    digits (JS default 15, ~Number.MAX_SAFE_INTEGER's own digit count),
    the plain digit string; past it, "mantissa×10^exponent (N digits)"
    since NWW/Faza/Do-rezonancy can genuinely reach hundreds or thousands
    of digits once dozens of pairwise-coprime primes are multiplied
    together, and printing all of them would be noise, not information.
    English-only wording (unlike the JS's #t()-localized string) since
    this is a console/HUD diagnostic string on the Python side, not
    user-facing app chrome with its own PL/EN locale files."""
    value = int(value)
    negative = value < 0
    s = str(-value if negative else value)
    if len(s) <= digit_threshold:
        return ("-" if negative else "") + s
    mantissa = f"{s[0]}.{s[1:5]}"
    exponent = len(s) - 1
    return ("-" if negative else "") + f"{mantissa}×10^{exponent} ({len(s)} digits)"
