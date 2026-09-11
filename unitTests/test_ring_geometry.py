"""
test_ring_geometry.py -- checks primeatlas/ring_geometry.py against the SAME
invariants already pinned down (and hand-verified by Artur) in the JS
reference's own test suite (_test_legendre_window.mjs /
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
    from primeatlas.ring_geometry import legendre_level_at

    # The exact off-by-one case Artur caught by eye (N=9/15/16 sequence, see
    # SieveModel.js's isLegendreWindowMember doc-comment).
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


def _test_ring_radii():
    from primeatlas.ring_geometry import ring_radii

    r = ring_radii(4, 100.0)
    expected = [100.0 * ((i + 1) / 4) ** 0.85 for i in range(4)]
    check(np.allclose(r, expected), "ring_radii(4,100) matches closed-form t**0.85")
    check(math.isclose(r[-1], 100.0), "ring_radii last ring reaches max_radius exactly")
    check(len(ring_radii(0, 100.0)) == 0, "ring_radii(0, 100) is empty")


def _test_ring_positions():
    from primeatlas.ring_geometry import ring_positions

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


def _test_bertrand_legendre_membership():
    from primeatlas.ring_geometry import is_bertrand_member, is_legendre_member

    check(list(is_bertrand_member(np.array([5, 6, 10]), 10)) == [False, True, True],
          "is_bertrand_member: (n/2, n] excludes n/2 itself, includes n")
    check(
        list(is_legendre_member(np.array([9, 11, 13, 16, 17]), 16)) == [False, True, True, True, False],
        "is_legendre_member at n=16 (level 3, window (9,16]): includes 11,13, excludes 9",
    )


def _test_general_law():
    from primeatlas.ring_geometry import (
        general_law_tent_factor,
        general_law_window_bounds,
        legendre_level_at,
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


def _test_legendre_highlighted_sticky():
    from primeatlas.ring_geometry import is_legendre_highlighted, is_legendre_member

    # n=30: level k = floor(sqrt(29)) = 5, window (25,30] -> strict member: 29 only.
    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29], dtype=np.int64)
    strict = is_legendre_member(primes, 30)
    check(list(strict) == [False] * 9 + [True],
          "is_legendre_member at n=30: only 29 strictly in (25,30]")

    # Sticky test uses each RING's OWN prime value, not n=30. For ring=23:
    # legendre_level_at(23) = floor(sqrt(22)) = 4, close_edge = 5^2 = 25,
    # next_crossing = (25 // 23 + 1) * 23 = (1+1)*23 = 46 > 30 -> still sticky-highlighted.
    sticky = is_legendre_highlighted(primes, 30)
    check(bool(sticky[primes == 23][0]) is True,
          "is_legendre_highlighted: ring 23 still sticky-green at n=30 (own window not yet re-crossed)")
    check(bool(sticky[primes == 29][0]) is True,
          "is_legendre_highlighted: ring 29 (strict member) is also sticky-highlighted")
    # Small primes cycle out of sticky status fast: legendre_level_at(2)=1,
    # closeEdge=(1+1)^2=4, nextCrossing=(4//2+1)*2=6 -- by n=30 ring 2's own
    # sticky window closed long ago (verified against SieveModel.js's
    # isLegendreHighlighted directly, not hand-derived -- see this test
    # file's own note on why hand-derived anchor expectations were wrong
    # twice before this fix).
    check(bool(is_legendre_highlighted(np.array([2]), 30)[0]) is False,
          "is_legendre_highlighted: ring 2's own sticky window (closed at n=6) has long since lapsed by n=30")


def _test_anchor_functions():
    from primeatlas.ring_geometry import bertrand_anchor_at, legendre_anchor_at, general_law_anchor_at

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

    # n=40 is where Bertrand and Legendre anchors genuinely diverge (used by
    # _test_compute_tracked_colors below to exercise a real two-family blend
    # rather than a coincidental tie).
    primes_40 = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37], dtype=np.int64)
    check(bertrand_anchor_at(primes_40, 40) == 23,
          "bertrand_anchor_at(40): chain 2->3->5->7->13->23 (2*23=46 > 40 stops the chain)")
    check(legendre_anchor_at(primes_40, 40) == 31,
          "legendre_anchor_at(40): level k=6, largest prime < 36 is 31")


def _test_blend_family_colors():
    from primeatlas.ring_geometry import _blend_family_colors, WINDOW_FAMILY_COLORS

    masks = {
        "bertrand": np.array([True, False, True]),
        "legendre": np.array([True, True, False]),
    }
    colors, matched = _blend_family_colors(masks)
    expected_ring0 = np.clip(
        np.array(WINDOW_FAMILY_COLORS["bertrand"], dtype=np.float64)
        + np.array(WINDOW_FAMILY_COLORS["legendre"], dtype=np.float64),
        0, 255,
    )
    check(np.allclose(colors[0], expected_ring0), "_blend_family_colors: ring 0 additively sums both families, clamped")
    check(np.allclose(colors[1], WINDOW_FAMILY_COLORS["legendre"]), "_blend_family_colors: ring 1 is pure legendre")
    check(np.allclose(colors[2], WINDOW_FAMILY_COLORS["bertrand"]), "_blend_family_colors: ring 2 is pure bertrand")
    check(list(matched) == [True, True, True], "_blend_family_colors: matched True wherever any family contributed")

    empty_colors, empty_matched = _blend_family_colors({})
    check(empty_colors.shape == (0, 3) and empty_matched.shape == (0,),
          "_blend_family_colors: no families gives empty arrays")


def _test_compute_highlight_colors_strict_sticky_precedence():
    from primeatlas.ring_geometry import compute_highlight_colors, WINDOW_FAMILY_COLORS

    # Hand-derived scenario (n=30, Bertrand ON window (15,30], Legendre ON
    # strict window (25,30] containing only 29): rings 17/19/23 are
    # Bertrand-strict AND Legendre-sticky (see _test_legendre_highlighted_sticky
    # for why 23 is sticky), but the two-tier strict/sticky rule must resolve
    # them to PURE Bertrand pink, since Bertrand strictly matches those rings
    # and sticky-only Legendre must NOT blend in once any family strictly
    # matches. Ring 29 is strict for BOTH families and must be a genuine blend.
    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29], dtype=np.int64)
    colors, matched = compute_highlight_colors(primes, 30, {"bertrand", "legendre"})

    def idx(p):
        return int(np.where(primes == p)[0][0])

    for p in (17, 19, 23):
        check(np.allclose(colors[idx(p)], WINDOW_FAMILY_COLORS["bertrand"]),
              f"compute_highlight_colors: ring {p} is pure Bertrand pink (strict wins over Legendre's sticky-only match)")

    expected_29 = np.clip(
        np.array(WINDOW_FAMILY_COLORS["bertrand"], dtype=np.float64)
        + np.array(WINDOW_FAMILY_COLORS["legendre"], dtype=np.float64),
        0, 255,
    )
    check(np.allclose(colors[idx(29)], expected_29),
          "compute_highlight_colors: ring 29 is a genuine Bertrand+Legendre blend (both strictly match)")

    for p in (2, 3, 5, 7, 11, 13):
        check(bool(matched[idx(p)]) is False,
              f"compute_highlight_colors: ring {p} matches neither family (outside both windows, not sticky either)")

    # No enabled families -> nothing matches, empty-but-correctly-shaped output.
    empty_colors, empty_matched = compute_highlight_colors(primes, 30, set())
    check(empty_colors.shape == (10, 3) and not empty_matched.any(),
          "compute_highlight_colors: empty enabled_ids matches nothing but keeps ring count")


def _test_compute_tracked_colors():
    from primeatlas.ring_geometry import (
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


def _test_window_anchor_primes():
    from primeatlas.ring_geometry import (
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


def _test_window_label_colors():
    """[ADDED, see Artur's 2026-09-10 report: "daj kolory podpisow w hud
    zgodnie z kolorem pierscieni dla okien... i oby zmienialy na wspolny
    tak jak pierscien zmienia gdy zakres okna sie pokrywa"] window_label_
    colors' own docstring: solid per-family color normally, additive blend
    when two+ enabled families' windows have the EXACT SAME (lo, hi) bounds
    at this N -- not merely "overlap" (every window shares the same right
    edge n, so that would trivially always fire)."""
    from primeatlas.ring_geometry import window_label_colors, WINDOW_FAMILY_COLORS

    # Single family on -> its own solid color, untouched.
    result = window_label_colors({"bertrand"}, 100)
    check(result == {"bertrand": WINDOW_FAMILY_COLORS["bertrand"]},
          f"a single enabled family keeps its own plain WINDOW_FAMILY_COLORS entry (got {result!r})")

    # n=141 (matches Artur's own screenshot): Bertrand=(70,141], Legendre
    # k=11=(121,141] -- different bounds, so both keep their own solid color.
    result_diff = window_label_colors({"bertrand", "legendre"}, 141)
    check(result_diff["bertrand"] == WINDOW_FAMILY_COLORS["bertrand"],
          f"Bertrand and Legendre windows differ at n=141 -- Bertrand keeps its own color (got {result_diff!r})")
    check(result_diff["legendre"] == WINDOW_FAMILY_COLORS["legendre"],
          f"Bertrand and Legendre windows differ at n=141 -- Legendre keeps its own color (got {result_diff!r})")
    check(result_diff["bertrand"] != result_diff["legendre"],
          "differing windows never end up sharing a color by accident")

    # General Law stepped mode at theta=0.5 is provably identical to
    # Legendre's own window (task #577) -- enabling both together must
    # collapse their two labels to ONE shared additively-blended color.
    result_coincide = window_label_colors({"legendre", "generalLaw"}, 141, theta=0.5, mode="stepped")
    check(result_coincide["legendre"] == result_coincide["generalLaw"],
          f"Legendre and General Law(theta=0.5, stepped) windows coincide exactly -- "
          f"both labels get the SAME blended color (got {result_coincide!r})")
    expected_blend = tuple(
        min(255, a + b) for a, b in zip(WINDOW_FAMILY_COLORS["legendre"], WINDOW_FAMILY_COLORS["generalLaw"])
    )
    check(result_coincide["legendre"] == expected_blend,
          f"the coincidence color is the additive-RGB sum (clamped to 255) of both families' "
          f"own colors, same arithmetic as the ring highlight blend (got {result_coincide['legendre']!r}, "
          f"expected {expected_blend!r})")

    # All three enabled but only two coincide (legendre+generalLaw at
    # theta=0.5) -- Bertrand must NOT be pulled into that blend just for
    # being enabled at the same time.
    result_mixed = window_label_colors({"bertrand", "legendre", "generalLaw"}, 141, theta=0.5, mode="stepped")
    check(result_mixed["bertrand"] == WINDOW_FAMILY_COLORS["bertrand"],
          f"a family whose window doesn't coincide with anyone else's keeps its own solid "
          f"color even while other families ARE blending together (got {result_mixed!r})")
    check(result_mixed["legendre"] == result_mixed["generalLaw"] == expected_blend,
          f"the other two still blend together correctly in the same call (got {result_mixed!r})")

    # Unknown/unrecognized family ids are silently skipped, not an error.
    result_unknown = window_label_colors({"bertrand", "not-a-real-family"}, 100)
    check(result_unknown == {"bertrand": WINDOW_FAMILY_COLORS["bertrand"]},
          f"an unrecognized family id in enabled_ids is silently ignored (got {result_unknown!r})")

    # Empty enabled_ids -> empty result, not an error.
    check(window_label_colors(set(), 100) == {}, "no enabled families -> empty dict")


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
    from primeatlas.ring_geometry import resonance_events_in_range

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


def _test_resonance_log_lines():
    from primeatlas.ring_geometry import resonance_log_lines, resonance_events_in_range

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
    from primeatlas.ring_geometry import format_log_panel_text, LOG_PANEL_TRUNCATE_THRESHOLD

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
    _test_bertrand_legendre_membership()
    _test_general_law()
    _test_legendre_highlighted_sticky()
    _test_anchor_functions()
    _test_window_anchor_primes()
    _test_window_label_colors()
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
