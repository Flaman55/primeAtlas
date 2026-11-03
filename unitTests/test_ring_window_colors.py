"""
test_ring_window_colors.py -- window anchors (ring_window_anchors.py: anchor functions,
cyclic window anchors, anchor primes) and window colors (ring_window_colors.py,
ring_windows.py: family blending, strict/sticky highlight precedence, tracked colors,
label colors, nested shells, Bertrand swallowing Legendre), checked against the same
invariants as the JS reference (see test_ring_geometry.py).

Usage: python unitTests\\test_ring_window_colors.py
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


def _test_anchor_functions():
    from primeatlas.visualization.rings.ring.ring_window_anchors import (
        bertrand_anchor_at, general_law_anchor_at, legendre_anchor_at)

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

    # 'bertrand'/'legendre' modes delegate DIRECTLY to
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
    from primeatlas.visualization.rings.ring.ring_window_colors import _blend_family_colors
    from primeatlas.visualization.rings.ring.ring_windows import WINDOW_FAMILY_COLORS

    masks = {
        "bertrand": np.array([True, False, True]),
        "legendre": np.array([True, True, False]),
    }
    colors, matched = _blend_family_colors(masks)
    # AVERAGE, not sum-then-clip -- see _blend_family_colors' doc-comment
    # (sum-then-clip washes toward white for 2-3 already-saturated colors).
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
    """n=30: level 5, window (25,30] (live member: 29 only); previous level 4,
    window (16,25] ({17,19,23}). With Legendre's current-level count m=1 (only
    29 is live so far), is_legendre_highlighted retires the OLDEST
    previous-level member (17) and keeps the other two (19,23) fading.

    With Bertrand ALSO enabled: 17/19/23 are all strictly inside Bertrand's
    (15,30] window too, so the two-tier precedence rule (see
    compute_highlight_colors' doc-comment) lets Bertrand's STRICT match win
    outright for all three -- Legendre's fade-only match on 19/23 is excluded
    from the blend (pure Bertrand pink). Ring 29 is a strict/strict match for
    BOTH families, so it blends.

    With ONLY Legendre enabled (no Bertrand to out-rank it), 19 and 23
    (Legendre's fading previous-level remnants) are highlighted, while 17
    (already retired -- rank 0 < m=1) is not."""
    from primeatlas.visualization.rings.ring.ring_window_colors import compute_highlight_colors
    from primeatlas.visualization.rings.ring.ring_windows import WINDOW_FAMILY_COLORS

    primes = np.array([2, 3, 5, 7, 11, 13, 17, 19, 23, 29], dtype=np.int64)
    colors, matched = compute_highlight_colors(primes, 30, {"bertrand", "legendre"})

    def idx(p):
        return int(np.where(primes == p)[0][0])

    for p in (17, 19, 23):
        check(np.allclose(colors[idx(p)], WINDOW_FAMILY_COLORS["bertrand"]),
              f"compute_highlight_colors: ring {p} is pure Bertrand pink -- Bertrand strictly matches "
              f"(in (15,30]) and Legendre no longer has any sticky fallback to blend in with")

    # AVERAGE, not sum-then-clip -- see _blend_family_colors' doc-comment.
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

    # Enabling ONLY Legendre (no Bertrand) fades 19/23 (previous
    # level's own surviving members, per is_legendre_highlighted -- see this
    # test's own module doc-comment) while 17 (already retired) stays dark.
    colors_legendre_only, matched_legendre_only = compute_highlight_colors(primes, 30, {"legendre"})
    check(bool(matched_legendre_only[idx(17)]) is False,
          "compute_highlight_colors: with only legendre enabled, ring 17 is NOT highlighted -- "
          "already retired from the fade queue (rank 0 < m=1)")
    for p in (19, 23):
        check(bool(matched_legendre_only[idx(p)]) is True and np.allclose(colors_legendre_only[idx(p)], WINDOW_FAMILY_COLORS["legendre"]),
              f"compute_highlight_colors: with only legendre enabled, ring {p} IS highlighted -- "
              f"a surviving fading remnant of the previous level (17,25], in legendre's own solid color "
              f"(fade contributes the SAME color, never a blend with itself)")
    check(bool(matched_legendre_only[idx(29)]) is True and np.allclose(colors_legendre_only[idx(29)], WINDOW_FAMILY_COLORS["legendre"]),
          "compute_highlight_colors: with only legendre enabled, ring 29 (the one genuine strict "
          "member of (25,30]) still gets legendre's own color")


def _test_compute_tracked_colors():
    from primeatlas.visualization.rings.ring.ring_window_anchors import (
        bertrand_anchor_at, legendre_anchor_at)
    from primeatlas.visualization.rings.ring.ring_window_colors import compute_tracked_colors
    from primeatlas.visualization.rings.ring.ring_windows import WINDOW_FAMILY_COLORS

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
    """Covers ring_window_anchors.cyclic_window_anchor_at -- the replacement
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
    from primeatlas.visualization.rings.ring.ring_window_anchors import cyclic_window_anchor_at
    from primeatlas.visualization.rings.ring.ring_windows import (
        general_law_window_bounds, legendre_level_at)

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

    # --- generalLaw's own rigid 'bertrand'/'legendre'
    # modes bypass this function's freeze/cadence logic entirely, delegating
    # straight to bertrand_anchor_at/legendre_anchor_at -- proving General
    # Law set to Bertrand/Legendre is a true drop-in of the standalone
    # family's own tracked anchor, at every n, not merely visually similar. ---
    from primeatlas.visualization.rings.ring.ring_window_anchors import (
        bertrand_anchor_at as _bertrand_anchor_at_direct)
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

    # Guard: with Legendre AND General Law both on and theta != 0.5 (stepped
    # mode), the two window ranges differ (e.g. Legendre (1156,1199], General
    # Law theta=0.3 (1177,1199]), so the anchors must too. Only theta=0.5 (tent
    # factor==1, General Law's `lo` literally IS Legendre's) takes the
    # level-keyed branch; any other theta takes the numeric-creep branch
    # "sliding" mode uses.
    # This test uses level 4 (n=17..25, legendre lo=16 constant) with
    # theta=0.3 (tent factor 0.5) so General Law's own lo = (n+16)/2 creeps
    # from 16.5 to 20.5 across the level -- clearly not constant like
    # Legendre's.
    from primeatlas.visualization.rings.ring.ring_windows import general_law_tent_factor
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
    from primeatlas.visualization.rings.ring.ring_window_anchors import (
        bertrand_anchor_at, general_law_anchor_at, legendre_anchor_at, window_anchor_primes)
    from primeatlas.visualization.rings.ring.ring_windows import WINDOW_FAMILY_COLORS

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
    # loop instead of the plain
    # legendre_anchor_at/general_law_anchor_at recomputation. A family
    # PRESENT in the dict must use that value verbatim, even if it differs
    # from what ANCHOR_FUNCTIONS would have computed; a family ABSENT from
    # it must fall back to ANCHOR_FUNCTIONS (already
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
    WINDOW_FAMILY_COLORS entry, unconditionally -- no blending here at all:
    Bertrand's line stays solidly pink, Legendre's green, General Law's
    purple, even when no ring shows that pure color (Bertrand's window always
    contains Legendre's/General Law's). A label says "this is Legendre";
    blended colors are named by nested_shell_colors' legend lines instead (see
    _test_nested_shell_colors)."""
    from primeatlas.visualization.rings.ring.ring_windows import (
        WINDOW_FAMILY_COLORS, window_label_colors)

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
        f"n=2,520,000 theta=0.4: all three HUD labels keep their own "
        f"distinct solid color (got {result_all3!r})"
    )

    # Unknown/unrecognized family ids are silently skipped, not an error.
    result_unknown = window_label_colors({"bertrand", "not-a-real-family"}, 100)
    check(result_unknown == {"bertrand": WINDOW_FAMILY_COLORS["bertrand"]},
          f"an unrecognized family id in enabled_ids is silently ignored (got {result_unknown!r})")

    # Empty enabled_ids -> empty result, not an error.
    check(window_label_colors(set(), 100) == {}, "no enabled families -> empty dict")


def _test_compute_highlight_colors_bertrand_swallows_legendre_regression():
    """At n=2,520,000, theta=0.4 (stepped), Legendre's window is
    (2,518,569, 2,520,000] and General Law's is (2,518,926, 2,520,000]; 18 real
    primes sit strictly inside Legendre's window but outside General Law's
    (first=2518577, last=2518913).

    Those 18 primes are ALSO inside Bertrand's much wider (1,260,000,
    2,520,000] window, so with all three families enabled a sum-then-clip
    blend would render them washed-out near-white (255,255,224). With
    averaging (see _blend_family_colors' doc-comment) they get the two-family
    (Bertrand+Legendre, NOT General Law) average, clearly distinct from both
    pure white and pure Legendre green."""
    from primeatlas.visualization.rings.ring.ring_window_colors import compute_highlight_colors
    from primeatlas.visualization.rings.ring.ring_windows import (
        WINDOW_FAMILY_COLORS, general_law_window_bounds, legendre_level_at)

    n = 2520000
    theta = 0.4
    mode = "stepped"
    legendre_lo = legendre_level_at(n) ** 2
    gl_lo, _hi, _k, _factor = general_law_window_bounds(n, theta, mode)
    check(legendre_lo < gl_lo < n, f"sanity: legendre_lo={legendre_lo} < gl_lo={gl_lo} < n={n} (fixture assumption)")

    # Real data: first=2518577, last=2518913, both strictly
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
    """Every window family shares the same right edge n (see
    nested_shell_colors' doc-comment), so enabled families are always totally
    ordered by containment (sorted by `lo`) -- giving len(distinct lo values)
    - 1 legend entries, not every 2^k-1 subset or every C(k,2) pair: 3
    families with 3 distinct `lo` values give exactly 2 entries, not 3."""
    from primeatlas.visualization.rings.ring.ring_windows import (
        WINDOW_FAMILY_COLORS, nested_shell_colors)

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

    # All three enabled, three DISTINCT lo values (n=141, theta!=0.5) ->
    # exactly TWO shells (Bertrand+Legendre,
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

    # n=2,520,000, theta=0.4 (stepped) -- exactly 2 shells, Bertrand+Legendre
    # then +General Law.
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


def main():
    _test_anchor_functions()
    _test_cyclic_window_anchor_at()
    _test_window_anchor_primes()
    _test_window_label_colors()
    _test_compute_highlight_colors_bertrand_swallows_legendre_regression()
    _test_nested_shell_colors()
    _test_blend_family_colors()
    _test_compute_highlight_colors_strict_sticky_precedence()
    _test_compute_tracked_colors()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
