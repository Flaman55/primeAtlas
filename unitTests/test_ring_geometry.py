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


def main():
    _test_legendre_level_at()
    _test_ring_radii()
    _test_ring_positions()
    _test_bertrand_legendre_membership()
    _test_general_law()

    if failures:
        print(f"\n{len(failures)} FAILURE(S)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
