"""
test_ring_geometry.py -- the pure ring math in primeatlas/visualization/rings/ring/
ring_geometry.py and ring_windows.py (radii, positions beyond uint64, Bertrand/Legendre
membership, the general law and its highlight rules) plus shared/bigint.py, checked
against the SAME invariants already pinned down in the JS reference's own test suite
(_test_legendre_window.mjs / _test_general_law_window.mjs in
RelationalMathematics/apps/interactive_visuals/structural_sieve/), rather than running
the JS side by side (no Node needed here). Window anchors and colors are in
test_ring_window_colors.py, resonance in test_ring_resonance.py.

Usage: python unitTests\\test_ring_geometry.py
"""
import math
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))
# primeatlas/__init__.py itself imports .manifest, which does a bare
# `import window_sharding` (see storage.py's own module docstring for why
# prime_sieve_v1.py/window_sharding.py live outside this package) -- so the
# prime_sieve dir must be on sys.path before `from primeatlas import ...`
# below, exactly like unitTests/test_storage.py's own setup.

import numpy as np

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _test_legendre_level_at():
    from primeatlas.visualization.rings.ring.ring_windows import legendre_level_at

    # The off-by-one edge case for the N=9/15/16 sequence, see
    # SieveModel.js's isLegendreWindowMember doc-comment.
    check(legendre_level_at(0) == 0, "legendre_level_at(0) == 0")
    check(legendre_level_at(1) == 0, "legendre_level_at(1) == 0")
    check(legendre_level_at(4) == 1, "legendre_level_at(4) == floor(sqrt(3)) == 1")
    check(legendre_level_at(9) == 2,
          "legendre_level_at(9) == 2 (perfect square stays in CLOSING level, not opening)")
    check(legendre_level_at(10) == 3, "legendre_level_at(10) == 3 (window just reopened)")
    check(legendre_level_at(15) == 3, "legendre_level_at(15) == 3")
    check(legendre_level_at(16) == 3,
          "legendre_level_at(16) == 3 (closing edge of level 3, NOT opening of level 4)")
    check(legendre_level_at(17) == 4, "legendre_level_at(17) == 4")

    # At floor-25 scale (N ~ 10**25), the old np.sqrt(n - 1) crashed with
    # "TypeError: loop of ufunc does not support argument 0 of type int
    # which has no callable sqrt method" -- a Python int this far outside
    # float64's representable range. math.isqrt is exact and
    # arbitrary-precision, so this must both NOT raise and match
    # floor(sqrt(n-1)) computed independently via math.isqrt itself, as a
    # sanity cross-check.
    huge_n = 12345678901234567890000023
    huge_level = legendre_level_at(huge_n)
    check(huge_level == math.isqrt(huge_n - 1),
          f"a real floor-25-scale N no longer crashes, and matches math.isqrt(n-1) directly (got {huge_level})")
    check(huge_level * huge_level < huge_n <= (huge_level + 1) * (huge_level + 1),
          f"the returned k still satisfies k*k < n <= (k+1)*(k+1) at this magnitude (got k={huge_level})")


def _test_ring_radii():
    from primeatlas.visualization.rings.ring.ring_geometry import ring_radii

    r = ring_radii(4, 100.0)
    expected = [100.0 * ((i + 1) / 4) ** 0.85 for i in range(4)]
    check(np.allclose(r, expected), "ring_radii(4,100) matches closed-form t**0.85")
    check(math.isclose(r[-1], 100.0), "ring_radii last ring reaches max_radius exactly")
    check(len(ring_radii(0, 100.0)) == 0, "ring_radii(0, 100) is empty")


def _test_ring_positions():
    from primeatlas.visualization.rings.ring.ring_geometry import ring_positions

    primes = np.array([2, 3, 5, 7], dtype=np.int64)
    pos = ring_positions(primes, n=9, max_radius=100.0)
    check(list(pos["phase"]) == [1, 0, 4, 2], "ring_positions phase matches n%%p")
    check(list(pos["is_hit"]) == [False, True, False, False],
          "ring_positions is_hit matches phase==0")
    expected_r1 = 100.0 * ((2 / 4) ** 0.85)
    check(math.isclose(pos["radius"][1], expected_r1),
          "ring_positions radius for ring i=1 matches closed form")
    check(math.isclose(pos["angle"][1], -math.pi / 2),
          "ring_positions angle at phase=0 is exactly -pi/2")
    check(
        math.isclose(pos["x"][1], 0.0 + pos["radius"][1] * math.cos(pos["angle"][1]), abs_tol=1e-9)
        and math.isclose(pos["y"][1], 0.0 + pos["radius"][1] * math.sin(pos["angle"][1]), abs_tol=1e-9),
        "ring_positions x/y consistent with radius*cos/sin(angle)",
    )

    big_n = 2_000_000
    big_primes = np.array(
        [p for p in range(2, 2000) if all(p % d for d in range(2, int(p ** 0.5) + 1))],
        dtype=np.int64,
    )
    big_pos = ring_positions(big_primes, n=big_n, max_radius=500.0)
    check(big_pos["phase"][10] == big_n % big_primes[10],
          "ring_positions large-N phase matches direct n%%p for a spot-checked ring")
    check(np.all(np.isfinite(big_pos["x"])) and np.all(np.isfinite(big_pos["y"])),
          "ring_positions returns finite coordinates only")


def _test_to_prime_array():
    """At floor-25/floor-27 scale (~10**25-10**27 magnitude), the old
    hardcoded `dtype=np.int64` cast raised OverflowError. to_prime_array is
    the shared fix every prime-handling function in this module (and
    renderer.py) now routes through -- see its own doc-comment for the
    uint64-fast-path/object-fallback design."""
    from primeatlas.visualization.shared.bigint import to_prime_array, UINT64_MAX

    small = to_prime_array([2, 3, 5, 7])
    check(small.dtype == np.uint64,
          "to_prime_array: values well under the uint64 ceiling use the fast uint64 dtype")
    check(list(small) == [2, 3, 5, 7], "to_prime_array: values round-trip exactly on the fast path")

    at_ceiling = to_prime_array([UINT64_MAX])
    check(at_ceiling.dtype == np.uint64,
          "to_prime_array: a value exactly AT the uint64 ceiling still fits the fast path")

    # A value past the uint64 ceiling, at floor-25 scale.
    huge = [10 ** 25, 10 ** 25 + 3, 10 ** 25 + 7]
    big = to_prime_array(huge)
    check(big.dtype == object, "to_prime_array: a value past the uint64 ceiling falls back to object dtype")
    check(list(big) == huge, "to_prime_array: object-dtype values round-trip EXACTLY (no float rounding)")

    just_past = to_prime_array([UINT64_MAX + 1])
    check(just_past.dtype == object, "to_prime_array: one past the uint64 ceiling already falls back")

    empty = to_prime_array([])
    check(len(empty) == 0 and empty.dtype == np.uint64, "to_prime_array: empty input returns an empty uint64 array")

    already_object = np.array([10 ** 30], dtype=object)
    check(to_prime_array(already_object) is already_object,
          "to_prime_array: an already-object-dtype ndarray is returned as-is (no needless re-copy)")

    already_uint64 = np.array([2, 3, 5], dtype=np.uint64)
    check(to_prime_array(already_uint64) is already_uint64,
          "to_prime_array: an already-uint64-dtype ndarray is returned as-is too")


def _test_parse_big_int():
    """parse_big_int accepts plain digits, a*10**b, a*10^b, and scientific
    notation as compact alternatives to typing out floor-25+-scale values
    digit by digit -- always via exact integer arithmetic, never float(),
    so such a value never silently rounds."""
    from primeatlas.visualization.shared.bigint import parse_big_int

    check(parse_big_int("12345") == 12345, "parse_big_int: plain digits")
    check(parse_big_int("1_000_000") == 1_000_000, "parse_big_int: underscore digit grouping")
    check(parse_big_int("6*10**20") == 6 * 10 ** 20, "parse_big_int: a*10**b form")
    check(parse_big_int("6*10^20") == 6 * 10 ** 20, "parse_big_int: a*10^b form (caret means power here, not XOR)")
    check(parse_big_int(" 6 * 10 ^ 20 ") == 6 * 10 ** 20, "parse_big_int: tolerates internal whitespace")
    check(parse_big_int("10**25") == 10 ** 25, "parse_big_int: bare 10**b (mantissa defaults to 1)")
    check(parse_big_int("10^25") == 10 ** 25, "parse_big_int: bare 10^b (mantissa defaults to 1)")
    check(parse_big_int("6e20") == 6 * 10 ** 20, "parse_big_int: scientific notation")
    check(parse_big_int("6E20") == 6 * 10 ** 20, "parse_big_int: scientific notation, uppercase E")
    check(parse_big_int("1.5e25") == 15 * 10 ** 24, "parse_big_int: decimal mantissa in scientific notation stays exact")

    for bad in ("not a number", "", "   ", "10**5+3"):
        try:
            parse_big_int(bad)
            check(False, f"parse_big_int({bad!r}) should raise ValueError")
        except ValueError:
            check(True, f"parse_big_int({bad!r}) raises ValueError as expected")


def _test_ring_positions_beyond_uint64():
    """At floor-25/floor-27 scale, the old int64-hardcoded ring_positions
    crashed. Confirms the fix at that magnitude, AND the separate latent bug
    the fix also caught along the way: the OLD `n_int % (1 << 63)`
    pre-reduction was mathematically WRONG (not just imprecise) for any
    n >= 2**63 -- see ring_positions' own doc-comment."""
    from primeatlas.visualization.rings.ring.ring_geometry import ring_positions

    primes = np.array([10 ** 25 + 3, 10 ** 25 + 7, 10 ** 25 + 13], dtype=object)
    n = 10 ** 25 + 20
    pos = ring_positions(primes, n=n, max_radius=100.0)
    expected_phase = [n % p for p in primes]
    check(list(pos["phase"]) == expected_phase,
          f"ring_positions: exact phase at floor-25 magnitude (got {list(pos['phase'])!r})")
    check(list(pos["is_hit"]) == [False, False, False],
          "ring_positions: is_hit correct at floor-25 magnitude")
    check(np.all(np.isfinite(pos["x"])) and np.all(np.isfinite(pos["y"])),
          "ring_positions: finite coordinates even at floor-25 magnitude (visual precision loss here is expected/OK)")

    hit_n = 10 ** 25 + 7  # exactly equal to primes[1] -> that ring's phase is 0
    pos_hit = ring_positions(primes, n=hit_n, max_radius=100.0)
    check(list(pos_hit["is_hit"]) == [False, True, False],
          "ring_positions: is_hit fires exactly when n equals one of the huge primes")

    # The specific historical bug: n beyond uint64 but primes still uint64-
    # sized -- the OLD `n_int % (1<<63)` reduction silently gave the WRONG
    # phase here (nothing makes 2**63, or any other fixed power of two,
    # a multiple of an arbitrary prime).
    small_primes = np.array([7, 11, 13], dtype=np.uint64)
    huge_n = (1 << 64) + 5
    pos_uint64_primes = ring_positions(small_primes, n=huge_n, max_radius=50.0)
    expected = [huge_n % 7, huge_n % 11, huge_n % 13]
    got = [int(v) for v in pos_uint64_primes["phase"]]
    check(got == expected,
          f"ring_positions: n beyond uint64 still gives the mathematically correct phase against small "
          f"primes (got {got!r}, expected {expected!r})")


def _test_bertrand_legendre_membership():
    from primeatlas.visualization.rings.ring.ring_windows import (
        is_bertrand_member, is_legendre_member)

    check(list(is_bertrand_member(np.array([5, 6, 10]), 10)) == [False, True, True],
          "is_bertrand_member: (n/2, n] excludes n/2 itself, includes n")
    check(
        list(is_legendre_member(np.array([9, 11, 13, 16, 17]), 16)) == [False, True, True, True, False],
        "is_legendre_member at n=16 (level 3, window (9,16]): includes 11,13, excludes 9",
    )


def _test_general_law():
    from primeatlas.visualization.rings.ring.ring_windows import (
        general_law_tent_factor, general_law_window_bounds, is_general_law_member,
        legendre_level_at)

    check(math.isclose(general_law_tent_factor(0.1), 0.0, abs_tol=1e-12),
          "general_law_tent_factor(0.1) == 0")
    check(math.isclose(general_law_tent_factor(0.5), 1.0, abs_tol=1e-12),
          "general_law_tent_factor(0.5) == 1")
    check(math.isclose(general_law_tent_factor(1.0), 0.0, abs_tol=1e-12),
          "general_law_tent_factor(1.0) == 0")

    n_test = 20
    lo_gl, hi_gl, k_gl, factor_gl = general_law_window_bounds(n_test, 0.5, "stepped")
    k_leg = legendre_level_at(n_test)
    lo_leg = k_leg * k_leg
    check(math.isclose(lo_gl, lo_leg, abs_tol=1e-9),
          "General Law stepped @theta=0.5 matches Legendre lo exactly")
    check(math.isclose(factor_gl, 1.0, abs_tol=1e-12),
          "General Law stepped @theta=0.5 has factor==1")

    # Invariant from SieveModel.js's own doc-comment: width(n,theta) <=
    # width_legendre(n) for EVERY theta in [0.1,1], equality only at theta=0.5.
    n_sweep = [5, 9, 16, 20, 100, 1000, 100003]
    all_within = True
    for nn in n_sweep:
        k = legendre_level_at(nn)
        if k == 0:
            continue
        width_legendre = nn - k * k
        for theta in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            lo, hi, _k, _f = general_law_window_bounds(nn, theta, "stepped")
            width = hi - lo
            if width > width_legendre + 1e-9:
                all_within = False
                print(f"  violation at n={nn} theta={theta}: width={width} > legendre={width_legendre}")
    check(all_within, "General Law stepped width never exceeds Legendre width (any theta, sweep of n)")

    lo_slide, hi_slide, k_slide, factor_slide = general_law_window_bounds(50, 1.0, "sliding")
    check(math.isclose(lo_slide, 0.0, abs_tol=1e-9),
          "Sliding mode theta=1 gives lo=0 (trivial (0,n])")
    check(k_slide is None and factor_slide is None,
          "Sliding mode k/factor are None (no level concept)")

    # Ported from RelationalMathematics's _test_general_law_window.mjs Part 9: two
    # RIGID modes -- theta
    # ignored entirely, bounds exactly match is_bertrand_member/
    # is_legendre_member's own lo, for a spread of n and any theta value.
    from primeatlas.visualization.rings.ring.ring_windows import (
        is_bertrand_member, is_legendre_member)
    for nn in (0, 1, 2, 5, 9, 16, 17, 100, 4999):
        for theta in (1, 0.7, 0.1):
            lo_b, hi_b, k_b, factor_b = general_law_window_bounds(nn, theta, "bertrand")
            check(lo_b == nn // 2 and hi_b == nn,
                  f"bertrand mode n={nn} theta={theta}: window ({nn // 2},{nn}] (got ({lo_b},{hi_b}])")
            check(k_b is None and factor_b is None,
                  f"bertrand mode n={nn} theta={theta}: k and factor both None (got k={k_b}, factor={factor_b})")
        for theta in (0.5, 0.9, 0.1):
            k = legendre_level_at(nn)
            lo_l, hi_l, k_l, factor_l = general_law_window_bounds(nn, theta, "legendre")
            check(lo_l == k * k and hi_l == nn,
                  f"legendre mode n={nn} theta={theta}: window ({k * k},{nn}] (got ({lo_l},{hi_l}])")
            check(k_l == k, f"legendre mode n={nn} theta={theta}: bounds k={k} (got {k_l})")
            check(factor_l is None, f"legendre mode n={nn} theta={theta}: factor is None (got {factor_l})")

    primes_9 = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29], dtype=np.int64)
    all_bertrand_match = True
    all_legendre_match = True
    for nn in (10, 21, 30):
        for p in primes_9:
            if p > nn:
                continue
            if bool(is_general_law_member(np.array([p]), nn, 1, "bertrand")[0]) != bool(is_bertrand_member(np.array([p]), nn)[0]):
                all_bertrand_match = False
            if bool(is_general_law_member(np.array([p]), nn, 0.5, "legendre")[0]) != bool(is_legendre_member(np.array([p]), nn)[0]):
                all_legendre_match = False
    check(all_bertrand_match, "is_general_law_member(...,'bertrand') agrees with is_bertrand_member exactly")
    check(all_legendre_match, "is_general_law_member(...,'legendre') agrees with is_legendre_member exactly")


def _test_legendre_member_strict_only():
    """is_legendre_member itself is the plain STRICT mathematical membership
    test ((k*k, n]) -- unaffected by is_legendre_highlighted's fade-continuity
    layer on top of it (see that function's doc-comment). This re-confirms the
    strict test's behavior on its own terms."""
    from primeatlas.visualization.rings.ring.ring_windows import is_legendre_member

    # n=30: level k = floor(sqrt(29)) = 5, window (25,30] -> strict member: 29 only.
    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29], dtype=np.int64)
    strict = is_legendre_member(primes, 30)
    check(list(strict) == [False] * 9 + [True],
          "is_legendre_member at n=30: only 29 strictly in (25,30]")


def _test_is_legendre_highlighted():
    """The RENDERING variant of Legendre membership -- is_legendre_member
    (above) stays the strict mathematical test. Without it, when a level
    closes ALL of that level's highlighted primes go dark in the SAME step the
    level advances, before the new level has produced a single member of its
    own (Bertrand's wide window never empties out all at once).

    Rule: the previous level's members form a queue, oldest (smallest) first.
    For every member the CURRENT level has produced so far (count `m`), retire
    exactly one -- the smallest surviving -- member of the previous level's
    queue. A member of the previous level is therefore still highlighted iff
    its rank among the previous level's members (sorted ascending) is >= m. A
    PURE function of n (no per-tick queue/state -- both "the previous level's
    full membership" and "how many members the current level has produced so
    far" are recomputable from n and the prime list), so it stays consistent
    under rewind/backward steps.

    Test data: real primes -- level 11 (121,144] = {127,131,137,139}, level 12
    (144,169] = {149,151,157,163,167}."""
    from primeatlas.visualization.rings.ring.ring_windows import is_legendre_highlighted

    primes = np.array(
        [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61,
         67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109, 113, 127, 131, 137,
         139, 149, 151, 157, 163, 167],
        dtype=np.int64,
    )

    def highlighted_set(n):
        primes_here = primes[primes <= n]
        mask = is_legendre_highlighted(primes_here, n)
        return set(primes_here[mask].tolist())

    # n=121: level JUST advanced to 10 (window (100,121]), zero members of
    # its own yet -- ALL 5 of level 9's own members ((81,100] = {83,89,97}...
    # wait, level 9 is (81,100], real members {83,89,97} -- verified directly
    # against the implementation, not hand-derived) stay highlighted.
    check(highlighted_set(121) == {101, 103, 107, 109, 113},
          "n=121: level 10 window (100,121] has produced its own 5 members already (100<n<=121 spans "
          "most of the level in one jump from n=120->121 since 121=11^2) -- level 9's own remnants "
          "(83,89,97) have ALL already been retired by this point (m=5 >= old_count=3)")

    # n=127..139: level 11 itself producing its own members one at a time
    # (127,131,137,139) -- each new arrival retires exactly one of level
    # 10's own remnants (101,103,107,109,113), oldest first. Verified
    # directly against the implementation (not hand-derived) for the full
    # progression:
    check(highlighted_set(127) == {103, 107, 109, 113, 127}, "n=127: m=1 -- 101 retired")
    check(highlighted_set(131) == {107, 109, 113, 127, 131}, "n=131: m=2 -- 103 retired")
    check(highlighted_set(137) == {109, 113, 127, 131, 137}, "n=137: m=3 -- 107 retired")
    check(highlighted_set(139) == {113, 127, 131, 137, 139}, "n=139: m=4 -- 109 retired")

    # n=144: still level 11 (window (121,144]), m stays at 4 (no 5th member
    # of level 11 exists) -- so 113 (level 10's own last survivor, m=4 <
    # old_count=5) is STILL fading, alongside level 11's own 4 live members.
    # This is the real, verified state at N=144
    # -- not "just 4 plain members" as a naive read of the window bounds
    # alone would suggest; the fade layer is continuously active, not only
    # right at a transition.
    check(highlighted_set(144) == {113, 127, 131, 137, 139},
          "n=144: level 11's own 4 live members PLUS 113, level 10's last still-fading remnant")

    # n=145: level JUST advanced to 12 (window (144,145]), which has
    # produced ZERO members of its own yet (145 = 5*29, not prime) -- so
    # all 4 of level 11's own members stay highlighted, none go dark.
    check(highlighted_set(145) == {127, 131, 137, 139},
          "n=145: level just closed, m=0 -- ALL 4 old members still highlighted, none go dark")

    # n=149: level 12 has now produced its FIRST member (149) -- exactly ONE
    # of level 11's own members retires: the OLDEST (smallest), 127.
    check(highlighted_set(149) == {131, 137, 139, 149},
          "n=149: m=1 -- oldest old member (127) retired, 3 old + 1 new")

    # n=151: second new member (151) arrives -- second-oldest old member
    # (131) retires.
    check(highlighted_set(151) == {137, 139, 149, 151},
          "n=151: m=2 -- next-oldest old member (131) retired, 2 old + 2 new")

    # n=157: third new member -- 137 retires.
    check(highlighted_set(157) == {139, 149, 151, 157},
          "n=157: m=3 -- 137 retired, 1 old + 3 new")

    # n=163: fourth new member -- last old member (139) retires. Exactly
    # old_count (4) new members have now arrived, so no old members remain.
    check(highlighted_set(163) == {149, 151, 157, 163},
          "n=163: m=4 == old_count -- last old member (139) retired, 0 old + 4 new")

    # n=167: fifth new member -- old queue was already fully retired at
    # n=163, so this is now identical to plain strict membership (no old
    # members left to protect).
    check(highlighted_set(167) == {149, 151, 157, 163, 167},
          "n=167: old queue exhausted -- matches plain is_legendre_member exactly")

    # Small-n edge case: k<2 means no previous level exists at all (only
    # reachable while the window itself is still extremely narrow) -- must
    # simply equal is_legendre_member, no crash, no fabricated "previous
    # level".
    from primeatlas.visualization.rings.ring.ring_windows import is_legendre_member
    small_primes = np.array([2, 3], dtype=np.int64)
    check(list(is_legendre_highlighted(small_primes, 3)) == list(is_legendre_member(small_primes, 3)),
          "k<2 (n=3): is_legendre_highlighted matches plain is_legendre_member, no previous level to fade from")


def _test_is_general_law_highlighted():
    """General Law's rendering-highlight test, same role as
    is_legendre_highlighted for Legendre:

      - 'legendre' mode: delegates STRAIGHT to is_legendre_highlighted --
        exact reproduction of the Legendre checkbox, fade included, the point
        of a RIGID mode.
      - 'bertrand'/'sliding': exactly is_general_law_member, no fade layer --
        their raw membership tests already creep smoothly by construction (see
        is_general_law_member/general_law_window_bounds).
      - 'stepped' mode: the SAME fade queue as 'legendre', paced by Legendre's
        (monotonic) exposure count rather than stepped's (possibly flickering)
        live count -- see is_general_law_highlighted's 'stepped' doc-comment
        for why that substitution is exact."""
    from primeatlas.visualization.rings.ring.ring_windows import (
        is_general_law_highlighted, is_general_law_member, is_legendre_highlighted)

    primes = np.array(
        [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61,
         67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109, 113, 127, 131, 137,
         139, 149, 151, 157, 163, 167],
        dtype=np.int64,
    )

    # 'legendre' mode: exact delegation, re-using the same real level-11/12
    # transition as _test_is_legendre_highlighted above.
    for n in [144, 145, 149, 151, 157, 163, 167]:
        primes_here = primes[primes <= n]
        got = is_general_law_highlighted(primes_here, n, 0.5, "legendre")
        expected = is_legendre_highlighted(primes_here, n)
        check(list(got) == list(expected),
              f"GL 'legendre' mode matches is_legendre_highlighted exactly at n={n}")

    # 'stepped' mode, THE FIX ITSELF: theta=0.3 (narrower than Legendre) over
    # the SAME real level-11/12 transition. Verified directly against the
    # implementation (not hand-derived) before writing this test -- see
    # is_general_law_highlighted's own 'stepped' doc-comment for the
    # exposure-count substitution this depends on.
    def highlighted_set_stepped(n):
        primes_here = primes[primes <= n]
        mask = is_general_law_highlighted(primes_here, n, 0.3, "stepped")
        return set(primes_here[mask].tolist())

    # n=144: level 11 still open. Legendre-style exposure so far = 4 (all of
    # 127,131,137,139 have been "born" already, even though stepped's own
    # narrower live window has already flickered 127 and 131 back out by
    # this point) -- level 10's queue (101,103,107,109,113) is fully
    # retired (exposure 4 < 5, so rank-4 survivor 113 remains), same
    # boundary-carryover shape _test_is_legendre_highlighted's own n=144
    # case documents.
    check(highlighted_set_stepped(144) == {113, 137, 139},
          "stepped theta=0.3, n=144: 113 (level 10's last survivor) + stepped's own currently-live 137,139 "
          "(127,131 already flickered out of stepped's OWN narrower window, unrelated to the fade)")

    # n=145: level just closed, stepped's own live set is empty (145 isn't
    # prime, and its window is razor-narrow) -- Legendre-style exposure=0,
    # so ALL FOUR of level 11's own members survive untouched.
    check(highlighted_set_stepped(145) == {127, 131, 137, 139},
          "stepped theta=0.3, n=145: exposure=0 -- all 4 of level 11's own members survive, "
          "identical to real Legendre's own fade at this exact n")

    # n=149: Legendre-style exposure=1 (149 born) -- retires the oldest (127).
    check(highlighted_set_stepped(149) == {131, 137, 139, 149},
          "stepped theta=0.3, n=149: exposure=1 -- 127 retired")

    # n=151: exposure=2 -- 131 retires too.
    check(highlighted_set_stepped(151) == {137, 139, 149, 151},
          "stepped theta=0.3, n=151: exposure=2 -- 131 retired")

    # n=157: exposure=3 -- 137 retires. stepped's OWN live window has by now
    # also flickered 149 back out (unrelated to the fade), so only
    # 151/157 are live, plus survivor 139.
    check(highlighted_set_stepped(157) == {139, 151, 157},
          "stepped theta=0.3, n=157: exposure=3 -- 137 retired; 149 separately flickered out of "
          "stepped's own narrower live window")

    # n=163: exposure=4 == old_count -- last survivor (139) retires too.
    check(highlighted_set_stepped(163) == {157, 163},
          "stepped theta=0.3, n=163: exposure=4 == old_count -- queue fully drained")

    # n=167: queue long since drained -- matches stepped's own plain live
    # membership exactly, no fade contribution left.
    check(highlighted_set_stepped(167) == {157, 163, 167},
          "stepped theta=0.3, n=167: queue exhausted -- matches plain stepped membership")

    # 'bertrand'/'sliding': no fade layer -- exactly is_general_law_member,
    # spot-checked at the SAME n=145 transition (where 'legendre'/'stepped'
    # above visibly differ from plain membership) to prove these two modes
    # deliberately do NOT pick up any fade behavior.
    primes_145 = primes[primes <= 145]
    for mode, theta in [("bertrand", 1), ("sliding", 0.5)]:
        got = is_general_law_highlighted(primes_145, 145, theta, mode)
        expected = is_general_law_member(primes_145, 145, theta, mode)
        check(list(got) == list(expected),
              f"GL '{mode}' mode: no fade layer, matches is_general_law_member exactly at n=145")


def main():
    _test_legendre_level_at()
    _test_ring_radii()
    _test_ring_positions()
    _test_to_prime_array()
    _test_parse_big_int()
    _test_ring_positions_beyond_uint64()
    _test_bertrand_legendre_membership()
    _test_general_law()
    _test_legendre_member_strict_only()
    _test_is_legendre_highlighted()
    _test_is_general_law_highlighted()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
