"""
test_ring_geometry.py -- checks primeatlas/rings/ring_geometry.py against the SAME
invariants already pinned down in the JS reference's own test suite
(_test_legendre_window.mjs /
_test_general_law_window.mjs in RelationalMathematics/apps/interactive_visuals/
structural_sieve/), rather than running the JS side by side (no Node needed
here). Not a port of those test files line-for-line -- just enough
independent checks on the SAME formulas to catch a transcription error before
ring_geometry.py is trusted as the base for the ring-visualization feature
(see PLAN.md).

Usage (Windows, real Python):
    python unitTests\\test_ring_geometry.py

Usage (this sandbox, headless):
    python3 unitTests/test_ring_geometry.py
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
    from primeatlas.rings.ring_geometry import legendre_level_at

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
    from primeatlas.rings.ring_geometry import ring_radii

    r = ring_radii(4, 100.0)
    expected = [100.0 * ((i + 1) / 4) ** 0.85 for i in range(4)]
    check(np.allclose(r, expected), "ring_radii(4,100) matches closed-form t**0.85")
    check(math.isclose(r[-1], 100.0), "ring_radii last ring reaches max_radius exactly")
    check(len(ring_radii(0, 100.0)) == 0, "ring_radii(0, 100) is empty")


def _test_ring_positions():
    from primeatlas.rings.ring_geometry import ring_positions

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
    from primeatlas.rings.ring_geometry import to_prime_array, UINT64_MAX

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
    from primeatlas.rings.ring_geometry import parse_big_int

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
    from primeatlas.rings.ring_geometry import ring_positions

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
    from primeatlas.rings.ring_geometry import is_bertrand_member, is_legendre_member

    check(list(is_bertrand_member(np.array([5, 6, 10]), 10)) == [False, True, True],
          "is_bertrand_member: (n/2, n] excludes n/2 itself, includes n")
    check(
        list(is_legendre_member(np.array([9, 11, 13, 16, 17]), 16)) == [False, True, True, True, False],
        "is_legendre_member at n=16 (level 3, window (9,16]): includes 11,13, excludes 9",
    )


def _test_general_law():
    from primeatlas.rings.ring_geometry import (
        general_law_tent_factor,
        general_law_window_bounds,
        legendre_level_at,
        is_general_law_member,
    )

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

    # [ADDED 2026-09-26, ported from RelationalMathematics's
    # _test_general_law_window.mjs Part 9] Two new RIGID modes -- theta
    # ignored entirely, bounds exactly match is_bertrand_member/
    # is_legendre_member's own lo, for a spread of n and any theta value.
    from primeatlas.rings.ring_geometry import is_bertrand_member, is_legendre_member
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
    """is_legendre_highlighted (the "sticky" grace-period variant this test
    used to cover) is gone -- see compute_highlight_colors' own doc-comment
    for why: enabling ONLY Legendre showed green dots as wide as Bertrand's
    own (n/2, n] window, traced back to that function's sticky formula
    reproducing almost exactly a 2x-multiple window by coincidence.
    Legendre's highlight test is now simply is_legendre_member -- this just
    re-confirms that function's own strict behavior still holds now that
    it's the ONLY test in play."""
    from primeatlas.rings.ring_geometry import is_legendre_member

    # n=30: level k = floor(sqrt(29)) = 5, window (25,30] -> strict member: 29 only.
    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29], dtype=np.int64)
    strict = is_legendre_member(primes, 30)
    check(list(strict) == [False] * 9 + [True],
          "is_legendre_member at n=30: only 29 strictly in (25,30]")


def _test_anchor_functions():
    from primeatlas.rings.ring_geometry import bertrand_anchor_at, legendre_anchor_at, general_law_anchor_at

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29], dtype=np.int64)
    # bertrand_anchor_at replays the freeze/jump chain from scratch (see
    # SieveModel.js's bertrandAnchorAt doc-comment): anchor starts at 2, and
    # jumps to the largest active prime < 2*anchor whenever n >= 2*anchor.
    # At n=30 the chain is 2->3->5->7->13->23 (2*13=26<=30 triggers one more
    # jump to 23; 2*23=46>30 stops it there).
    check(bertrand_anchor_at(primes, 30) == 23,
          "bertrand_anchor_at(30): freeze/jump chain 2->3->5->7->13->23 (2*23=46 > 30 stops the chain)")
    check(legendre_anchor_at(primes, 30) == 23,
          "legendre_anchor_at(30): level k=5, largest prime < 25 is 23 (coincides with bertrand here)")
    check(bertrand_anchor_at(np.array([], dtype=np.int64), 30) is None,
          "bertrand_anchor_at with no primes returns None")
    check(general_law_anchor_at(primes, 30, 0.5, "stepped") == legendre_anchor_at(primes, 30),
          "general_law_anchor_at @theta=0.5 stepped matches legendre_anchor_at exactly")

    # [ADDED 2026-09-26] 'bertrand'/'legendre' modes delegate DIRECTLY to
    # bertrand_anchor_at/legendre_anchor_at -- not the generic lo-based
    # recompute. n=10 is the sharpest proof for bertrand: floor(10/2)=5
    # (largest active prime <=5 would be 5), but the real freeze/jump chain
    # (2->3->5->7, since 10>=2*5 triggers one more jump) lands on 7.
    primes_10 = np.array([2, 3, 5, 7], dtype=np.int64)
    check(bertrand_anchor_at(primes_10, 10) == 7, "sanity: bertrand_anchor_at(primes_10, 10) == 7 (chain 2->3->5->7)")
    check(general_law_anchor_at(primes_10, 10, 1, "bertrand") == 7,
          "general_law_anchor_at('bertrand') at n=10 is 7, the real chain result, NOT floor(10/2)=5")
    check(general_law_anchor_at(primes, 30, 1, "bertrand") == bertrand_anchor_at(primes, 30),
          "general_law_anchor_at('bertrand') matches bertrand_anchor_at exactly at n=30")
    check(general_law_anchor_at(primes, 30, 0.5, "legendre") == legendre_anchor_at(primes, 30),
          "general_law_anchor_at('legendre') matches legendre_anchor_at exactly at n=30")

    # n=40 is where Bertrand and Legendre anchors genuinely diverge (used by
    # _test_compute_tracked_colors below to exercise a real two-family blend
    # rather than a coincidental tie).
    primes_40 = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37], dtype=np.int64)
    check(bertrand_anchor_at(primes_40, 40) == 23,
          "bertrand_anchor_at(40): chain 2->3->5->7->13->23 (2*23=46 > 40 stops the chain)")
    check(legendre_anchor_at(primes_40, 40) == 31,
          "legendre_anchor_at(40): level k=6, largest prime < 36 is 31")


def _test_blend_family_colors():
    from primeatlas.rings.ring_geometry import _blend_family_colors, WINDOW_FAMILY_COLORS

    masks = {
        "bertrand": np.array([True, False, True]),
        "legendre": np.array([True, True, False]),
    }
    colors, matched = _blend_family_colors(masks)
    # [CHANGED 2026-09-26] AVERAGE, not sum-then-clip -- see _blend_family_
    # colors' own doc-comment for why (Artur's real bug report: sum-then-
    # clip washes toward white for 2-3 already-saturated colors).
    expected_ring0 = (
        np.array(WINDOW_FAMILY_COLORS["bertrand"], dtype=np.float64)
        + np.array(WINDOW_FAMILY_COLORS["legendre"], dtype=np.float64)
    ) / 2
    check(np.allclose(colors[0], expected_ring0), "_blend_family_colors: ring 0 averages both families' colors")
    check(np.allclose(colors[1], WINDOW_FAMILY_COLORS["legendre"]), "_blend_family_colors: ring 1 is pure legendre")
    check(np.allclose(colors[2], WINDOW_FAMILY_COLORS["bertrand"]), "_blend_family_colors: ring 2 is pure bertrand")
    check(list(matched) == [True, True, True], "_blend_family_colors: matched True wherever any family contributed")

    empty_colors, empty_matched = _blend_family_colors({})
    check(empty_colors.shape == (0, 3) and empty_matched.shape == (0,),
          "_blend_family_colors: no families gives empty arrays")


def _test_compute_highlight_colors_strict_sticky_precedence():
    """Name kept even though the sticky variant it originally covered is
    gone -- see compute_highlight_colors' own doc-comment -- this scenario
    (n=30, Bertrand ON, Legendre ON) still exercises the SAME multi-family
    blend it always did; only the reasoning for rings 17/19/23 changed (they
    used to be pure Bertrand pink because Bertrand's strict match beat
    Legendre's sticky-only match; now it's simply because Legendre doesn't
    match them at all -- is_legendre_member(17/19/23, 30) is False, no
    sticky fallback left to kick in)."""
    from primeatlas.rings.ring_geometry import compute_highlight_colors, WINDOW_FAMILY_COLORS

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29], dtype=np.int64)
    colors, matched = compute_highlight_colors(primes, 30, {"bertrand", "legendre"})

    def idx(p):
        return int(np.where(primes == p)[0][0])

    for p in (17, 19, 23):
        check(np.allclose(colors[idx(p)], WINDOW_FAMILY_COLORS["bertrand"]),
              f"compute_highlight_colors: ring {p} is pure Bertrand pink -- Bertrand strictly matches "
              f"(in (15,30]) and Legendre no longer has any sticky fallback to blend in with")

    # [CHANGED 2026-09-26] AVERAGE, not sum-then-clip -- see _blend_family_
    # colors' own doc-comment.
    expected_29 = (
        np.array(WINDOW_FAMILY_COLORS["bertrand"], dtype=np.float64)
        + np.array(WINDOW_FAMILY_COLORS["legendre"], dtype=np.float64)
    ) / 2
    check(np.allclose(colors[idx(29)], expected_29),
          "compute_highlight_colors: ring 29 is a genuine Bertrand+Legendre blend (both strictly match)")

    for p in (2, 3, 5, 7, 11, 13):
        check(bool(matched[idx(p)]) is False,
              f"compute_highlight_colors: ring {p} matches neither family (outside both strict windows)")

    # No enabled families -> nothing matches, empty-but-correctly-shaped output.
    empty_colors, empty_matched = compute_highlight_colors(primes, 30, set())
    check(empty_colors.shape == (10, 3) and not empty_matched.any(),
          "compute_highlight_colors: empty enabled_ids matches nothing but keeps ring count")

    # Regression guard: enabling ONLY Legendre (no Bertrand) must NOT color
    # rings 17/19/23 at all -- those are exactly the rings the old
    # is_legendre_highlighted sticky formula falsely lit up green (a band as
    # wide as Bertrand's own window), even though none of them are in
    # Legendre's own (25,30] strict window at n=30.
    colors_legendre_only, matched_legendre_only = compute_highlight_colors(primes, 30, {"legendre"})
    for p in (17, 19, 23):
        check(bool(matched_legendre_only[idx(p)]) is False,
              f"compute_highlight_colors: with ONLY legendre enabled, ring {p} is NOT highlighted -- "
              f"it is outside Legendre's own (25,30] window and there is no sticky fallback left to "
              f"falsely light it up (this guards against green dots as wide as "
              f"Bertrand's own window while only Legendre was on)")
    check(bool(matched_legendre_only[idx(29)]) is True and np.allclose(colors_legendre_only[idx(29)], WINDOW_FAMILY_COLORS["legendre"]),
          "compute_highlight_colors: with only legendre enabled, ring 29 (the one genuine strict "
          "member of (25,30]) still gets legendre's own color")


def _test_compute_tracked_colors():
    from primeatlas.rings.ring_geometry import (
        compute_tracked_colors,
        bertrand_anchor_at,
        legendre_anchor_at,
        WINDOW_FAMILY_COLORS,
    )

    # n=40, not n=30: at n=30 both anchors happen to coincide at 23 (see
    # _test_anchor_functions), which would make this test pass even if the
    # two-family separation were broken. n=40 is confirmed (by direct
    # computation, not hand arithmetic) to give genuinely different anchors.
    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37], dtype=np.int64)
    b_anchor = bertrand_anchor_at(primes, 40)
    l_anchor = legendre_anchor_at(primes, 40)
    check(b_anchor != l_anchor, "sanity: bertrand and legendre anchors differ at n=40 (23 vs 31)")

    colors, matched = compute_tracked_colors(primes, 40, {"bertrand", "legendre"})

    def idx(p):
        return int(np.where(primes == p)[0][0])

    check(np.allclose(colors[idx(b_anchor)], WINDOW_FAMILY_COLORS["bertrand"]),
          "compute_tracked_colors: the Bertrand anchor ring gets pure Bertrand color")
    check(np.allclose(colors[idx(l_anchor)], WINDOW_FAMILY_COLORS["legendre"]),
          "compute_tracked_colors: the Legendre anchor ring gets pure Legendre color (different ring from Bertrand)")
    check(int(matched.sum()) == 2,
          "compute_tracked_colors: exactly 2 rings matched (one per distinct anchor)")

    # anchor_overrides -- same hook as window_anchor_primes' own (see
    # _test_window_anchor_primes), exercised here for the OUTLINE COLOR path
    # instead of the tracked-set path: a family present in the dict colors
    # whichever ring that override names, not whatever ANCHOR_FUNCTIONS
    # would have picked.
    override_anchor = 17
    check(override_anchor != l_anchor,
          "sanity: the override value below is a genuinely different ring from legendre's own real anchor")
    colors_ov, matched_ov = compute_tracked_colors(
        primes, 40, {"bertrand", "legendre"}, anchor_overrides={"legendre": override_anchor}
    )
    check(np.allclose(colors_ov[idx(override_anchor)], WINDOW_FAMILY_COLORS["legendre"]),
          "compute_tracked_colors: anchor_overrides colors the OVERRIDDEN ring with legendre's color")
    check(not np.allclose(colors_ov[idx(l_anchor)], WINDOW_FAMILY_COLORS["legendre"]),
          "compute_tracked_colors: legendre's own real (non-overridden) anchor ring no longer gets "
          "legendre's color once overridden elsewhere")
    check(int(matched_ov.sum()) == 2,
          "compute_tracked_colors: still exactly 2 matched rings with an override in play")


def _test_cyclic_window_anchor_at():
    """Covers ring_geometry.cyclic_window_anchor_at -- the replacement
    anchor rule for Legendre/General Law's own tracked-ring outline (see
    that function's own doc-comment for the full rationale: Bertrand's
    2x-doubling freeze/jump doesn't fire sensibly on Legendre/General Law's
    much narrower window). Two genuinely different code paths to cover, per
    that doc-comment:
      - "legendre" (and General Law "stepped", which shares the same level
        concept) resets in one discrete jump exactly at each Legendre
        level boundary.
      - General Law "sliding" has no level at all -- its own numeric `lo`
        creeps up on every single n, so the freeze/jump condition is a
        plain numeric comparison instead.
    """
    from primeatlas.rings.ring_geometry import (
        cyclic_window_anchor_at,
        legendre_level_at,
        general_law_window_bounds,
    )

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47], dtype=np.int64)

    # --- "legendre": level-keyed. legendre_level_at(17..25) == 4 (constant
    # -- see _test_legendre_level_at's own n=17 case), legendre_level_at(26)
    # == 5 (a fresh level opens in one jump, not a numeric creep). ---
    check(legendre_level_at(17) == 4 and legendre_level_at(25) == 4 and legendre_level_at(26) == 5,
          "sanity: level 4 spans n=17..25, level 5 opens at n=26 (fixture assumption for this test)")

    state = {}
    check(cyclic_window_anchor_at(state, "legendre", primes, 17) == 17,
          "cyclic_window_anchor_at: first call (n=17, level 4) anchors at the window's own right "
          "edge -- largest active prime <= 17 is 17 itself")
    check(cyclic_window_anchor_at(state, "legendre", primes, 18) == 17,
          "cyclic_window_anchor_at: still level 4 at n=18 -- anchor stays frozen at 17")
    check(cyclic_window_anchor_at(state, "legendre", primes, 25) == 17,
          "cyclic_window_anchor_at: level 4 lasts through n=25 -- anchor still frozen at 17")
    check(cyclic_window_anchor_at(state, "legendre", primes, 26) == 23,
          "cyclic_window_anchor_at: level 5 opens at n=26 -- anchor jumps to the NEW right edge "
          "(largest active prime <= 26, i.e. 23, since 26 itself isn't prime)")
    check(cyclic_window_anchor_at(state, "legendre", primes, 26) == 23,
          "cyclic_window_anchor_at: a second call at the SAME n=26 is idempotent, no double-jump")
    check(cyclic_window_anchor_at(state, "legendre", primes, 30) == 23,
          "cyclic_window_anchor_at: level 5 continues through n=30 -- anchor still frozen at 23")

    # --- General Law "stepped" @theta=0.5 shares Legendre's own level
    # concept exactly (see general_law_window_bounds's own doc-comment /
    # the pre-existing "General Law stepped @theta=0.5 matches Legendre lo
    # exactly" invariant) -- same jump points, independent state dict. ---
    state_gl_stepped = {}
    check(cyclic_window_anchor_at(state_gl_stepped, "generalLaw", primes, 17, 0.5, "stepped") == 17,
          "cyclic_window_anchor_at: generalLaw/stepped @theta=0.5 matches legendre's own n=17 anchor")
    check(cyclic_window_anchor_at(state_gl_stepped, "generalLaw", primes, 25, 0.5, "stepped") == 17,
          "cyclic_window_anchor_at: generalLaw/stepped stays frozen through level 4, same as legendre")
    check(cyclic_window_anchor_at(state_gl_stepped, "generalLaw", primes, 26, 0.5, "stepped") == 23,
          "cyclic_window_anchor_at: generalLaw/stepped jumps at the same level boundary as legendre")

    # --- General Law "sliding" @theta=0.5: no level, lo = n - sqrt(n)
    # creeps up every step -- jump points computed independently below and
    # cross-checked against general_law_window_bounds directly, since
    # sliding mode's jump condition is this function's OTHER code path. ---
    for check_n in (18, 21, 22, 23, 24):
        lo, _hi, k, _factor = general_law_window_bounds(check_n, 0.5, "sliding")
        check(k is None, f"sanity: sliding mode has no level concept (n={check_n})")
    lo21, _, _, _ = general_law_window_bounds(21, 0.5, "sliding")
    lo22, _, _, _ = general_law_window_bounds(22, 0.5, "sliding")
    check(lo21 < 17 <= lo22,
          f"sanity: lo creeps past the n=17 anchor (17) between n=21 ({lo21:.3f}) and n=22 ({lo22:.3f}) "
          f"-- fixture assumption for this test")
    lo23, _, _, _ = general_law_window_bounds(23, 0.5, "sliding")
    lo24, _, _, _ = general_law_window_bounds(24, 0.5, "sliding")
    check(lo23 < 19 <= lo24,
          f"sanity: lo creeps past the n=22 anchor (19) between n=23 ({lo23:.3f}) and n=24 ({lo24:.3f}) "
          f"-- fixture assumption for this test")

    state_gl_sliding = {}
    check(cyclic_window_anchor_at(state_gl_sliding, "generalLaw", primes, 17, 0.5, "sliding") == 17,
          "cyclic_window_anchor_at: generalLaw/sliding first call anchors at n=17's own right edge")
    check(cyclic_window_anchor_at(state_gl_sliding, "generalLaw", primes, 18, 0.5, "sliding") == 17,
          "cyclic_window_anchor_at: generalLaw/sliding frozen at n=18 (lo hasn't crept up to 17 yet)")
    check(cyclic_window_anchor_at(state_gl_sliding, "generalLaw", primes, 21, 0.5, "sliding") == 17,
          "cyclic_window_anchor_at: generalLaw/sliding still frozen at n=21 (lo just under 17)")
    check(cyclic_window_anchor_at(state_gl_sliding, "generalLaw", primes, 22, 0.5, "sliding") == 19,
          "cyclic_window_anchor_at: generalLaw/sliding jumps at n=22 once lo creeps past 17 -- new "
          "right edge (largest active prime <= 22) is 19")
    check(cyclic_window_anchor_at(state_gl_sliding, "generalLaw", primes, 22, 0.5, "sliding") == 19,
          "cyclic_window_anchor_at: generalLaw/sliding is idempotent on a second n=22 call")
    check(cyclic_window_anchor_at(state_gl_sliding, "generalLaw", primes, 23, 0.5, "sliding") == 19,
          "cyclic_window_anchor_at: generalLaw/sliding still frozen at n=23 (lo just under 19)")
    check(cyclic_window_anchor_at(state_gl_sliding, "generalLaw", primes, 24, 0.5, "sliding") == 23,
          "cyclic_window_anchor_at: generalLaw/sliding jumps again at n=24 once lo creeps past 19")

    check(cyclic_window_anchor_at({}, "legendre", np.array([], dtype=np.int64), 30) is None,
          "cyclic_window_anchor_at: no active primes yet -> anchor is None, not a crash")

    # --- [ADDED 2026-09-26] generalLaw's own rigid 'bertrand'/'legendre'
    # modes bypass this function's freeze/cadence logic entirely, delegating
    # straight to bertrand_anchor_at/legendre_anchor_at -- proving General
    # Law set to Bertrand/Legendre is a true drop-in of the standalone
    # family's own tracked anchor, at every n, not merely visually similar. ---
    from primeatlas.rings.ring_geometry import bertrand_anchor_at as _bertrand_anchor_at_direct
    all_gl_bertrand_match = True
    for check_n in range(2, 48):
        state_gl_bertrand = {}
        if cyclic_window_anchor_at(state_gl_bertrand, "generalLaw", primes, check_n, 1, "bertrand") != _bertrand_anchor_at_direct(primes, check_n):
            all_gl_bertrand_match = False
    check(all_gl_bertrand_match,
          "cyclic_window_anchor_at: generalLaw/bertrand matches bertrand_anchor_at exactly, for every n in 2..47")

    state_legendre_cmp = {}
    state_gl_legendre_cmp = {}
    all_gl_legendre_match = True
    for check_n in range(2, 48):
        a_legendre = cyclic_window_anchor_at(state_legendre_cmp, "legendre", primes, check_n)
        a_gl_legendre = cyclic_window_anchor_at(state_gl_legendre_cmp, "generalLaw", primes, check_n, 0.5, "legendre")
        if a_legendre != a_gl_legendre:
            all_gl_legendre_match = False
    check(all_gl_legendre_match,
          "cyclic_window_anchor_at: generalLaw/legendre matches the standalone legendre family's own "
          "cadence exactly (same state-machine timing), for every n in 2..47")

    # Regression guard: with Legendre AND General Law both on and theta !=
    # 0.5 (stepped mode), the HUD showed two clearly DIFFERENT window ranges
    # (e.g. Legendre (1156,1199], General Law theta=0.3 (1177,1199]) but
    # only ONE ring appeared. Root cause: the level-keyed branch used to
    # fire for EVERY "stepped" mode call regardless of theta, so General
    # Law's anchor was computed by the exact same legendre_level_at(n)-keyed
    # formula as Legendre's own -- identical output for ANY theta, not just
    # 0.5. Fixed: only theta=0.5 (tent factor==1, General Law's own `lo`
    # literally IS Legendre's) takes the level-keyed branch; any other theta
    # now takes the same numeric-creep branch "sliding" mode already used.
    # This test uses level 4 (n=17..25, legendre lo=16 constant) with
    # theta=0.3 (tent factor 0.5) so General Law's own lo = (n+16)/2 creeps
    # from 16.5 to 20.5 across the level -- clearly not constant like
    # Legendre's.
    from primeatlas.rings.ring_geometry import general_law_tent_factor
    check(math.isclose(general_law_tent_factor(0.3), 0.5),
          "sanity: theta=0.3's own tent factor is 0.5, not 1 -- General Law's lo genuinely "
          "creeps within level 4, unlike Legendre's own constant lo=16 (fixture assumption)")

    state_legendre_divergence = {}
    state_gl_theta03 = {}
    anchors_legendre = []
    anchors_gl = []
    for check_n in range(17, 26):
        anchors_legendre.append(cyclic_window_anchor_at(state_legendre_divergence, "legendre", primes, check_n))
        anchors_gl.append(cyclic_window_anchor_at(state_gl_theta03, "generalLaw", primes, check_n, 0.3, "stepped"))

    check(anchors_legendre == [17] * 9,
          f"cyclic_window_anchor_at: legendre stays frozen at 17 through all of level 4 (got {anchors_legendre})")
    check(anchors_gl != anchors_legendre,
          f"cyclic_window_anchor_at: generalLaw theta=0.3 stepped must NOT track legendre's identical "
          f"anchor sequence -- its own lo genuinely differs within the level (got legendre={anchors_legendre}, "
          f"generalLaw={anchors_gl})")
    check(len(set(anchors_gl)) > 1,
          f"cyclic_window_anchor_at: generalLaw theta=0.3 stepped's anchor actually CHANGES within "
          f"level 4 (its own lo creeps continuously, unlike legendre's constant lo) -- got {anchors_gl}")

    # theta=0.5 exactly must still coincide EXACTLY with legendre (the
    # additive-blend case) -- this is the invariant the fix must not break.
    state_legendre_05 = {}
    state_gl_theta05 = {}
    anchors_legendre_05 = [cyclic_window_anchor_at(state_legendre_05, "legendre", primes, n) for n in range(17, 26)]
    anchors_gl_05 = [
        cyclic_window_anchor_at(state_gl_theta05, "generalLaw", primes, n, 0.5, "stepped") for n in range(17, 26)
    ]
    check(anchors_gl_05 == anchors_legendre_05,
          f"cyclic_window_anchor_at: theta=0.5 stepped still coincides EXACTLY with legendre at every "
          f"step (got legendre={anchors_legendre_05}, generalLaw={anchors_gl_05})")

    try:
        cyclic_window_anchor_at({}, "bertrand", primes, 30)
        check(False, "cyclic_window_anchor_at must reject family_id='bertrand' (no cyclic state of its own)")
    except ValueError:
        check(True, "cyclic_window_anchor_at rejects family_id='bertrand' with ValueError")


def _test_window_anchor_primes():
    from primeatlas.rings.ring_geometry import (
        window_anchor_primes,
        bertrand_anchor_at,
        legendre_anchor_at,
        general_law_anchor_at,
        WINDOW_FAMILY_COLORS,
    )

    check(window_anchor_primes(np.array([2, 3, 5], dtype=np.int64), 30, set()) == [],
          "window_anchor_primes: no enabled families -> empty list, regardless of n/primes")

    # n=40 (same fixture as _test_compute_tracked_colors): Bertrand and
    # Legendre anchors genuinely differ (23 vs 31) -- a real two-family case,
    # not a coincidental tie.
    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37], dtype=np.int64)
    b_anchor = bertrand_anchor_at(primes, 40)
    l_anchor = legendre_anchor_at(primes, 40)
    check(b_anchor != l_anchor, "sanity: bertrand and legendre anchors differ at n=40 (23 vs 31)")

    anchors_both = window_anchor_primes(primes, 40, {"bertrand", "legendre"})
    check(anchors_both == [b_anchor, l_anchor],
          f"window_anchor_primes: both families on returns [bertrand_anchor, legendre_anchor] in registry order "
          f"(bertrand first, matching WINDOW_FAMILY_COLORS' own key order), got {anchors_both}")

    check(window_anchor_primes(primes, 40, {"legendre", "bertrand"}) == anchors_both,
          "window_anchor_primes: output order follows the fixed registry, not enabled_ids' own (set) iteration order")

    check(window_anchor_primes(primes, 40, {"bertrand"}) == [b_anchor],
          "window_anchor_primes: only Bertrand on returns just its own anchor")
    check(window_anchor_primes(primes, 40, {"legendre"}) == [l_anchor],
          "window_anchor_primes: only Legendre on returns just its own anchor")

    gl_anchor = general_law_anchor_at(primes, 30, 0.5, "stepped")
    check(window_anchor_primes(primes, 30, {"generalLaw"}, 0.5, "stepped") == [gl_anchor],
          "window_anchor_primes: General Law anchor is threaded through theta/mode correctly")

    # n=30 (see _test_anchor_functions): bertrand_anchor_at and
    # legendre_anchor_at both resolve to 23 -- the SAME prime from two
    # different families must be deduplicated to a single entry, exactly
    # like the JS's `if (a !== null && !anchors.includes(a)) anchors.push(a)`.
    primes_30 = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29], dtype=np.int64)
    check(bertrand_anchor_at(primes_30, 30) == legendre_anchor_at(primes_30, 30) == 23,
          "sanity: at n=30 bertrand and legendre anchors coincide at 23")
    dedup = window_anchor_primes(primes_30, 30, {"bertrand", "legendre"})
    check(dedup == [23],
          f"window_anchor_primes: a prime that is simultaneously two families' own anchor appears exactly once, got {dedup}")

    check(window_anchor_primes(np.array([], dtype=np.int64), 30, {"bertrand", "legendre"}) == [],
          "window_anchor_primes: no active primes yet -> every anchor is None -> empty list, not [None, None]")

    check(list(WINDOW_FAMILY_COLORS.keys())[0] == "bertrand",
          "sanity: WINDOW_FAMILY_COLORS' own key order starts with bertrand -- this is what window_anchor_primes "
          "relies on for its deterministic output order")

    # anchor_overrides -- renderer.py's own hook for feeding
    # cyclic_window_anchor_at's stateful result through this same collection
    # loop instead of the plain (now legacy-for-this-purpose)
    # legendre_anchor_at/general_law_anchor_at recomputation. A family
    # PRESENT in the dict must use that value verbatim, even if it differs
    # from what ANCHOR_FUNCTIONS would have computed; a family ABSENT from
    # it must fall back to ANCHOR_FUNCTIONS exactly as before (already
    # exercised by every check above, none of which pass anchor_overrides).
    override_anchor = 17  # a real active prime, deliberately != l_anchor (31) at n=40
    check(override_anchor != l_anchor,
          "sanity: the override value below is a genuinely different ring from legendre's own real anchor")
    overridden = window_anchor_primes(primes, 40, {"bertrand", "legendre"}, anchor_overrides={"legendre": override_anchor})
    check(overridden == [b_anchor, override_anchor],
          f"window_anchor_primes: a family present in anchor_overrides uses that value verbatim, not "
          f"ANCHOR_FUNCTIONS' own recomputation (got {overridden})")
    check(window_anchor_primes(primes, 40, {"bertrand", "legendre"}, anchor_overrides={}) == anchors_both,
          "window_anchor_primes: an anchor_overrides dict with no matching keys falls back to "
          "ANCHOR_FUNCTIONS for every family, same as anchor_overrides=None")


def _test_window_label_colors():
    """window_label_colors: each enabled family ALWAYS gets its own plain
    WINDOW_FAMILY_COLORS entry, unconditionally -- no blending here at all.

    [REDESIGNED 2026-09-26, TWICE the same day -- see this function's own
    doc-comment for the full back-and-forth] The first redesign (average +
    real-overlap grouping) fixed the ring-highlight-color bug but ALSO made
    these text LABELS blend together -- Artur's own live correction, after
    actually watching it render: Bertrand's line should stay solidly pink
    (that's its real color), Legendre's stay green, General Law's stay
    purple, even when no ring anywhere shows that pure color (Bertrand
    always swallows Legendre/General Law's window whole) -- the label's job
    is to say "this is Legendre", not to describe what a ring's blended
    color happens to look like right now. That job moved entirely to
    nested_shell_colors' own dedicated legend lines instead (see its own
    test, _test_nested_shell_colors)."""
    from primeatlas.rings.ring_geometry import window_label_colors, WINDOW_FAMILY_COLORS

    # Single family on -> its own solid color.
    result = window_label_colors({"bertrand"}, 100)
    check(result == {"bertrand": WINDOW_FAMILY_COLORS["bertrand"]},
          f"a single enabled family keeps its own plain WINDOW_FAMILY_COLORS entry (got {result!r})")

    # Two families whose windows genuinely overlap (Legendre nested inside
    # Bertrand at n=141) -- BOTH still keep their OWN distinct solid color,
    # never blended.
    result_overlap = window_label_colors({"bertrand", "legendre"}, 141)
    check(result_overlap["bertrand"] == WINDOW_FAMILY_COLORS["bertrand"],
          f"Bertrand keeps its own solid color even though Legendre's window is nested inside it "
          f"(got {result_overlap!r})")
    check(result_overlap["legendre"] == WINDOW_FAMILY_COLORS["legendre"],
          f"Legendre keeps its own solid color too (got {result_overlap!r})")
    check(result_overlap["bertrand"] != result_overlap["legendre"], "the two never share a color")

    # Even an EXACT coincidence (General Law at theta=0.5, provably
    # identical to Legendre's own window) does not blend the labels anymore
    # -- each still gets its own plain color.
    result_coincide = window_label_colors({"legendre", "generalLaw"}, 141, theta=0.5, mode="stepped")
    check(result_coincide["legendre"] == WINDOW_FAMILY_COLORS["legendre"],
          f"Legendre keeps its own color even when General Law's window exactly coincides "
          f"(got {result_coincide!r})")
    check(result_coincide["generalLaw"] == WINDOW_FAMILY_COLORS["generalLaw"],
          f"General Law keeps its own color too (got {result_coincide!r})")

    # All three enabled -> all three keep their own distinct solid colors,
    # regardless of theta/mode or real overlap at this n.
    result_all3 = window_label_colors({"bertrand", "legendre", "generalLaw"}, 2520000, theta=0.4, mode="stepped")
    check(
        result_all3 == {
            "bertrand": WINDOW_FAMILY_COLORS["bertrand"],
            "legendre": WINDOW_FAMILY_COLORS["legendre"],
            "generalLaw": WINDOW_FAMILY_COLORS["generalLaw"],
        },
        f"n=2,520,000 theta=0.4 (Artur's own real scenario): all three HUD labels keep their own "
        f"distinct solid color (got {result_all3!r})"
    )

    # Unknown/unrecognized family ids are silently skipped, not an error.
    result_unknown = window_label_colors({"bertrand", "not-a-real-family"}, 100)
    check(result_unknown == {"bertrand": WINDOW_FAMILY_COLORS["bertrand"]},
          f"an unrecognized family id in enabled_ids is silently ignored (got {result_unknown!r})")

    # Empty enabled_ids -> empty result, not an error.
    check(window_label_colors(set(), 100) == {}, "no enabled families -> empty dict")


def _test_compute_highlight_colors_bertrand_swallows_legendre_regression():
    """[ADDED 2026-09-26] Artur's own real bug report: at n=2,520,000,
    theta=0.4 (stepped), Legendre's window is (2,518,569, 2,520,000] and
    General Law's is (2,518,926, 2,520,000] -- he looked up the real portal
    data and confirmed 18 real primes sit strictly inside Legendre's window
    but outside General Law's (first=2518577, last=2518913).

    The bug: those 18 primes are ALSO inside Bertrand's own much wider
    (1,260,000, 2,520,000] window, so with all three families enabled they
    used to render as a washed-out near-white (255,255,224) -- a sum-then-
    clip artifact (Bertrand+Legendre summed and clamped), not a real "this
    is unhighlighted" white. Fixed by averaging (see _blend_family_colors'
    own doc-comment): the same primes now get the genuine two-family
    (Bertrand+Legendre, NOT General Law) average, clearly distinct from
    both pure white and pure Legendre green."""
    from primeatlas.rings.ring_geometry import (
        compute_highlight_colors,
        general_law_window_bounds,
        legendre_level_at,
        WINDOW_FAMILY_COLORS,
    )

    n = 2520000
    theta = 0.4
    mode = "stepped"
    legendre_lo = legendre_level_at(n) ** 2
    gl_lo, _hi, _k, _factor = general_law_window_bounds(n, theta, mode)
    check(legendre_lo < gl_lo < n, f"sanity: legendre_lo={legendre_lo} < gl_lo={gl_lo} < n={n} (fixture assumption)")

    # Artur's own real find: first=2518577, last=2518913, both strictly
    # inside Legendre's window but outside General Law's (legendre_lo=
    # 2518569 < p <= floor(gl_lo)=2518926).
    for p_legendre_only in (2518577, 2518913):
        check(legendre_lo < p_legendre_only <= int(np.floor(gl_lo)),
              f"sanity: {p_legendre_only} is strictly inside Legendre's window but outside General "
              f"Law's (legendre_lo={legendre_lo}, floor(gl_lo)={int(np.floor(gl_lo))})")

        primes = np.array([p_legendre_only], dtype=np.int64)
        colors, matched = compute_highlight_colors(primes, n, {"bertrand", "legendre", "generalLaw"}, theta, mode)
        expected = tuple(
            round((a + b) / 2) for a, b in zip(WINDOW_FAMILY_COLORS["bertrand"], WINDOW_FAMILY_COLORS["legendre"])
        )
        check(bool(matched[0]) is True, f"{p_legendre_only} matches at least one enabled family")
        check(tuple(int(round(c)) for c in colors[0]) == expected,
              f"{p_legendre_only} (Bertrand+Legendre, NOT General Law) gets the genuine two-family "
              f"average (got {tuple(colors[0])!r}, expected {expected!r}) -- NOT the old washed-out "
              f"near-white (255,255,224) sum-then-clip artifact")
        check(tuple(int(round(c)) for c in colors[0]) != (255, 255, 255),
              f"{p_legendre_only}'s color is not pure white (the old bug's failure mode) "
              f"(got {tuple(colors[0])!r})")


def _test_nested_shell_colors():
    """[ADDED 2026-09-26, REPLACES the same-day pairwise_family_colors] The
    key insight (see nested_shell_colors' own doc-comment): every window
    family here shares the same right edge n, so enabled families are
    always totally ordered by containment (sorted by `lo`) -- giving
    len(distinct lo values) - 1 legend entries, not every 2^k-1 subset or
    every C(k,2) pair. Artur's own live correction after seeing the wrong
    (all-pairwise) design rendered: 3 families with 3 distinct `lo` values
    should give exactly 2 entries, not 3."""
    from primeatlas.rings.ring_geometry import nested_shell_colors, WINDOW_FAMILY_COLORS

    # Fewer than 2 enabled families -> no shells at all (nothing to blend).
    check(nested_shell_colors(set(), 100) == {}, "no enabled families -> no shells")
    check(nested_shell_colors({"bertrand"}, 100) == {}, "only one enabled family -> no shells")

    # Two enabled, distinct `lo` (Legendre nested inside Bertrand at n=141)
    # -> exactly one shell, the average of both.
    result_two = nested_shell_colors({"bertrand", "legendre"}, 141)
    expected_bl = tuple(
        round((a + b) / 2) for a, b in zip(WINDOW_FAMILY_COLORS["bertrand"], WINDOW_FAMILY_COLORS["legendre"])
    )
    check(result_two == {frozenset(("bertrand", "legendre")): expected_bl},
          f"two enabled families with distinct lo -> exactly one shell, averaged (got {result_two!r}, "
          f"expected {{frozenset(('bertrand','legendre')): {expected_bl!r}}})")

    # Two enabled families whose `lo` ties EXACTLY (Legendre and General Law
    # at theta=0.5, provably identical windows) -> still exactly one shell
    # (there's no boundary BETWEEN two windows that are the same set).
    result_tied = nested_shell_colors({"legendre", "generalLaw"}, 141, theta=0.5, mode="stepped")
    expected_lg = tuple(
        round((a + b) / 2) for a, b in zip(WINDOW_FAMILY_COLORS["legendre"], WINDOW_FAMILY_COLORS["generalLaw"])
    )
    check(result_tied == {frozenset(("legendre", "generalLaw")): expected_lg},
          f"two enabled families with an EXACTLY tied lo -> one shell, not zero (got {result_tied!r})")

    # All three enabled, three DISTINCT lo values (n=141, theta!=0.5, the
    # real case Artur actually saw) -> exactly TWO shells (Bertrand+Legendre,
    # then +General Law), NOT three pairs and NOT one triple-only entry.
    result_three = nested_shell_colors({"bertrand", "legendre", "generalLaw"}, 141, theta=0.4, mode="stepped")
    check(len(result_three) == 2,
          f"three enabled families with three distinct lo values -> exactly 2 shells, not 3 "
          f"(got {len(result_three)}: {result_three!r})")
    check(frozenset(("bertrand", "legendre")) in result_three,
          f"the outer two families form their own shell (got {result_three!r})")
    check(frozenset(("bertrand", "legendre", "generalLaw")) in result_three,
          f"the innermost shell includes all three (got {result_three!r})")
    check(frozenset(("bertrand", "generalLaw")) not in result_three,
          f"Bertrand+GeneralLaw alone (skipping Legendre) is never a real shell here -- Legendre is "
          f"always the middle nesting level, never skippable (got {result_three!r})")

    # Artur's own real scenario: n=2,520,000, theta=0.4 (stepped) -- exactly
    # 2 shells, Bertrand+Legendre then +General Law, matching what he
    # actually saw rendered.
    result_regression = nested_shell_colors({"bertrand", "legendre", "generalLaw"}, 2520000, theta=0.4, mode="stepped")
    expected_triple = tuple(
        round(sum(c) / 3) for c in zip(
            WINDOW_FAMILY_COLORS["bertrand"], WINDOW_FAMILY_COLORS["legendre"], WINDOW_FAMILY_COLORS["generalLaw"]
        )
    )
    check(len(result_regression) == 2, f"n=2,520,000 theta=0.4: exactly 2 shells (got {result_regression!r})")
    check(result_regression[frozenset(("bertrand", "legendre"))] == expected_bl,
          "n=2,520,000: Bertrand+Legendre shell matches the plain two-color average")
    check(result_regression[frozenset(("bertrand", "legendre", "generalLaw"))] == expected_triple,
          "n=2,520,000: the innermost (all-three) shell matches the plain three-color average")

    # Unknown/unrecognized family ids are silently skipped, not an error.
    result_unknown = nested_shell_colors({"bertrand", "legendre", "not-a-real-family"}, 141)
    check(result_unknown == {frozenset(("bertrand", "legendre")): expected_bl},
          f"an unrecognized family id is silently ignored, not an error (got {result_unknown!r})")


def _brute_resonance_at(primes_arr, n):
    """Independent, unvectorized reimplementation of the SAME formula
    resonance_events_in_range is supposed to compute in bulk (mirrors
    SieveModel.js's getStepState per-n resonance test directly, not the bulk
    marking-pass algorithm) -- used ONLY as a cross-check in the test below,
    deliberately NOT sharing any code with the module under test, after two
    hand-derived expectations elsewhere in this file turned out wrong on
    first pass. If this and resonance_events_in_range disagree, at least one
    of the two independent derivations has a bug worth finding, rather than
    trusting either one blind."""
    factors = []
    primorial = 1
    max_resonance = 0
    still_growing = True
    for p in primes_arr:
        p = int(p)
        if p > n:
            break
        if n % p == 0:
            factors.append(p)
        if still_growing:
            primorial *= p
            if primorial > n:
                still_growing = False
            else:
                max_resonance += 1
    active = max_resonance > 0 and len(factors) >= max_resonance
    return active, factors


def _test_resonance_events_in_range():
    from primeatlas.rings.ring_geometry import resonance_events_in_range

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47], dtype=np.int64)
    from_n, to_n = 0, 60

    events = resonance_events_in_range(primes, from_n, to_n)
    event_by_n = {e["n"]: e["factors"] for e in events}

    brute_ns = []
    mismatches = []
    for n in range(from_n, to_n + 1):
        active, factors = _brute_resonance_at(primes, n)
        if active:
            brute_ns.append(n)
            if n not in event_by_n:
                mismatches.append(f"n={n}: brute says active, resonance_events_in_range missed it")
            elif sorted(event_by_n[n]) != sorted(factors):
                mismatches.append(f"n={n}: factor mismatch, brute={sorted(factors)} vs ported={sorted(event_by_n[n])}")
    for n in event_by_n:
        if n not in brute_ns:
            mismatches.append(f"n={n}: resonance_events_in_range flagged it, brute says not active")

    check(not mismatches,
          "resonance_events_in_range matches an independent per-n brute-force reimplementation over n in [0,60]"
          + ("" if not mismatches else f" -- {mismatches[:3]}"))
    check(len(brute_ns) > 0,
          "sanity: this prime list + range actually contains at least one resonance event (a vacuous pass would be a weak test)")

    check(resonance_events_in_range(primes, 10, 5) == [],
          "resonance_events_in_range returns [] when to_n < from_n")
    # n=0 with to_n=0: the smallest active prime (2) already exceeds to_n, so
    # no threshold is ever reached (max_resonance stays 0 for every n in
    # range) -- the honest "not enough range to have a resonance yet" case,
    # not a crash or an off-by-one.
    check(resonance_events_in_range(primes, 0, 0) == [],
          "resonance_events_in_range(primes, 0, 0) correctly finds no event (to_n=0 is below the smallest active prime)")

    # A floor-25-scale range-mode tick has active primes ~10**25 and (for a
    # long while) to_n only ~10**21 -- the smallest active prime already
    # exceeds to_n, so no resonance is possible ANYWHERE in the span; this
    # must return [] WITHOUT ever attempting the old
    # `np.zeros(to_n - from_n + 1, ...)` allocation, which raised
    # "ValueError: Maximum allowed dimension exceeded" at this magnitude.
    huge_primes = np.array([12345678901234567890000023, 12345678901234567890000127], dtype=object)
    huge_to_n = 1234567890123456789009  # ~10**21, four orders of magnitude below the primes above
    check(resonance_events_in_range(huge_primes, 1, huge_to_n) == [],
          "resonance_events_in_range at real storage-floor-25 scale (huge primes, a merely-large "
          "to_n well below them) returns [] instead of crashing on the old dense array allocation")

    # A second, independent guard for any combination that reaches a huge
    # span even with small-enough primes to pass the check above: a hard
    # cap on the span itself, past which the marking-pass algorithm could
    # never finish regardless of memory.
    from primeatlas.rings.ring_geometry import _RESONANCE_SCAN_MAX_SIZE
    small_primes = np.array([2, 3, 5], dtype=np.int64)
    huge_span_to_n = _RESONANCE_SCAN_MAX_SIZE + 1_000_000
    check(resonance_events_in_range(small_primes, 0, huge_span_to_n) == [],
          f"resonance_events_in_range returns [] for a span past _RESONANCE_SCAN_MAX_SIZE "
          f"({_RESONANCE_SCAN_MAX_SIZE:,}), even with small, otherwise-relevant primes, instead "
          f"of attempting an infeasible allocation")


def _test_resonance_log_lines():
    from primeatlas.rings.ring_geometry import resonance_log_lines, resonance_events_in_range

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47], dtype=np.int64)
    from_n, to_n = 0, 60

    lines = resonance_log_lines(primes, from_n, to_n)
    events = resonance_events_in_range(primes, from_n, to_n)
    expected = [f"{e['n']} = {' × '.join(str(f) for f in e['factors'])}" for e in events]
    check(lines == expected,
          "resonance_log_lines formats every resonance_events_in_range event as 'N = f1 × f2 × ...', "
          "same order, same content, no independent formatting drift")
    check(len(lines) > 0,
          "sanity: this range actually produces at least one resonance log line")
    check(all(" × " in line or " = " in line for line in lines),
          "every resonance_log_lines entry contains the 'N = ...' separator")

    check(resonance_log_lines(primes, 10, 5) == [],
          "resonance_log_lines returns [] for an empty (to_n < from_n) range, same as resonance_events_in_range")


def _test_format_log_panel_text():
    from primeatlas.rings.ring_geometry import format_log_panel_text, LOG_PANEL_TRUNCATE_THRESHOLD

    count, text = format_log_panel_text([])
    check(count == 0 and text == "-",
          "format_log_panel_text([]) -> (0, '-') for an empty list")

    small = [2, 3, 5, 7, 11]
    count, text = format_log_panel_text(small)
    check(count == 5 and text == "2, 3, 5, 7, 11",
          f"format_log_panel_text of a short list is fully joined by ', ' with no truncation (got {text!r})")

    check(LOG_PANEL_TRUNCATE_THRESHOLD == 50,
          "LOG_PANEL_TRUNCATE_THRESHOLD mirrors StructuralSieveApp.js's own threshold (50)")

    exact = list(range(LOG_PANEL_TRUNCATE_THRESHOLD))
    count, text = format_log_panel_text(exact)
    check(count == LOG_PANEL_TRUNCATE_THRESHOLD and "more" not in text,
          "a list with EXACTLY threshold items is shown in full, not truncated (JS: only ABOVE threshold collapses)")

    over = list(range(LOG_PANEL_TRUNCATE_THRESHOLD + 7))
    count, text = format_log_panel_text(over)
    check(count == LOG_PANEL_TRUNCATE_THRESHOLD + 7,
          "format_log_panel_text reports the TRUE total count even when the text itself is truncated")
    check(text.endswith("(+7 more)"),
          f"a list 7 over threshold is truncated with a trailing '(+7 more)' marker (got {text!r})")
    check(text.startswith("0, 1, 2"),
          "the truncated text still starts with the list's own first items, in order")
    check(len(text.split(" (+")[0].split(", ")) == LOG_PANEL_TRUNCATE_THRESHOLD,
          "the truncated text shows exactly `threshold` items before the '(+K more)' marker")

    # Custom threshold, so the test doesn't only ever exercise the default 50.
    count, text = format_log_panel_text([1, 2, 3, 4, 5], threshold=3)
    check(text == "1, 2, 3 (+2 more)",
          f"a custom threshold=3 truncates at 3 items (got {text!r})")


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
    _test_anchor_functions()
    _test_cyclic_window_anchor_at()
    _test_window_anchor_primes()
    _test_window_label_colors()
    _test_compute_highlight_colors_bertrand_swallows_legendre_regression()
    _test_nested_shell_colors()
    _test_blend_family_colors()
    _test_compute_highlight_colors_strict_sticky_precedence()
    _test_compute_tracked_colors()
    _test_resonance_events_in_range()
    _test_resonance_log_lines()
    _test_format_log_panel_text()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
