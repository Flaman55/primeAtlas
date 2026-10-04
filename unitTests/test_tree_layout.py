"""
test_tree_layout.py -- spec tests for primeatlas/visualization/tree/tree_layout.py, the
pure arithmetic of the sieve-lane tree (no numpy GL data, no GL).

Spec:
  A. Lanes: a lane is (residue, modulus); its node sits at the first lane value >= a
     (the window start, the session's N). Applying prime p splits a lane into one
     occupied child (multiples of p) and p-1 free children, each mod modulus*p.
  B. Representatives: a node shows at most K free children -- the K with the lowest
     values on the n axis, in ascending order -- and reports the hidden ones as a count
     plus the exact number of terminal lanes they would expand to.
  C. Counts are exact by formula: leaves_below = prod(p-1) over the deeper levels, and
     for every node shown leaves + hidden leaves == leaves_below.
  D. Fixed slice: the tree's shape (node count, slots, depths) does not depend on a;
     moving along n only changes the values.
  E. Prime columns, divisors and stripes: every multiple of p in the root lane is on
     p's column; a multiple whose least prime factor is smaller than p is hollow;
     stripes are the DISTINCT view primes dividing a value, ascending.
  F. Density: prod(1-1/p) exactly, and the coprime count in a window matches brute
     force.
  G. Zoom: parent_lane inverts a zoom into a child lane.
  H. Caps: levels are cut so the drawn node count stays within max_nodes; the window
     is shrunk so the line-point count stays within max_points.
  I. Big integers: a = 10**25 works with exact values.

Usage:
    python unitTests/test_tree_layout.py
"""
import os
import sys
from fractions import Fraction
from math import gcd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)
        print(f"FAIL: {message}")
    else:
        print(f"ok:   {message}")


def _lpf(n):
    d = 2
    while d * d <= n:
        if n % d == 0:
            return d
        d += 1
    return n


def section_a_lanes():
    print("\n--- A: lanes, first values, splits ---")
    from primeatlas.visualization.tree.tree_layout import (
        first_primes, lane_first_value, split_lane,
    )
    check(first_primes(6) == [2, 3, 5, 7, 11, 13], f"first_primes(6) (got {first_primes(6)})")
    check(first_primes(0) == [], "first_primes(0) is empty")
    for a in (0, 1, 5, 6, 7, 100, 211):
        for residue, modulus in ((0, 1), (1, 2), (5, 6), (1, 6), (7, 30)):
            v = lane_first_value(a, residue, modulus)
            ok = v >= a and v % modulus == residue % modulus and v - modulus < a
            check(ok, f"lane_first_value({a}, {residue}, {modulus}) = {v} is the first lane value >= a")
    occupied, free = split_lane(1, 2, 3)
    check(occupied == 3 and sorted(free) == [1, 5], f"split of 1 mod 2 by 3: occupied 3, free 1,5 (got {occupied}, {free})")
    occupied, free = split_lane(0, 1, 2)
    check(occupied == 0 and free == [1], f"split of the root by 2: occupied 0 (evens), free 1 (got {occupied}, {free})")
    occupied, free = split_lane(7, 30, 7)
    check(occupied % 7 == 0 and occupied % 30 == 7 and len(free) == 6
          and all(f % 30 == 7 and f % 7 != 0 for f in free),
          f"split of 7 mod 30 by 7: one occupied (multiple of 7), six free children (got {occupied}, {free})")


def section_b_representatives():
    print("\n--- B: K lowest representatives, hidden counts ---")
    from primeatlas.visualization.tree.tree_layout import build_view_tree, lane_first_value, split_lane
    primes = [2, 3, 5, 7]
    for a in (1, 50, 1234):
        view = build_view_tree(a, 0, 1, 0, primes, 3)
        bad = []
        for node in view.nodes:
            if node.level == len(primes):
                if node.children or node.occupied is not None:
                    bad.append(("terminal has children", node.residue, node.modulus))
                continue
            p = primes[node.level]
            occ, free = split_lane(node.residue, node.modulus, p)
            child_mod = node.modulus * p
            all_values = sorted(lane_first_value(a, r, child_mod) for r in free)
            shown = [c.value for c in node.children]
            if shown != all_values[:3]:
                bad.append(("not the K lowest", node.residue, node.modulus, shown, all_values))
            if node.hidden_count != len(free) - len(shown):
                bad.append(("hidden count", node.residue, node.modulus))
            if node.occupied is None or node.occupied.prime != p or node.occupied.value % p != 0:
                bad.append(("occupied child", node.residue, node.modulus))
            elif node.occupied.value != lane_first_value(a, occ, child_mod):
                bad.append(("occupied value", node.residue, node.modulus))
            for c in node.children:
                if c.value < node.value or c.value % node.modulus != node.residue % node.modulus:
                    bad.append(("child not above parent / not in parent lane", c.residue, c.modulus))
        check(not bad, f"a={a}: every node shows the K=3 lowest free children with exact hidden "
                       f"counts and its occupied child (problems: {bad[:3]})")
    view = build_view_tree(1, 0, 1, 0, primes, 3)
    shape = [len(view.nodes_at_level(l)) for l in range(len(primes) + 1)]
    check(shape == [1, 1, 2, 6, 18], f"K=3 over 2,3,5,7: drawn free nodes per level 1,1,2,6,18 (got {shape})")


def section_c_exact_counts():
    print("\n--- C: exact leaf counts ---")
    from primeatlas.visualization.tree.tree_layout import build_view_tree, leaves_if_expanded
    primes = [2, 3, 5, 7, 11]
    check(leaves_if_expanded(primes) == 1 * 2 * 4 * 6 * 10, "leaves_if_expanded = prod(p-1)")
    check(leaves_if_expanded([]) == 1, "leaves_if_expanded of no levels is 1 (the lane itself)")
    view = build_view_tree(17, 0, 1, 0, primes, 2)
    bad = []
    for node in view.nodes:
        expected = leaves_if_expanded(primes[node.level:])
        if node.leaves_below != expected:
            bad.append(("leaves_below", node.level, node.leaves_below, expected))
        if node.children:
            total = sum(c.leaves_below for c in node.children) + node.hidden_leaves
            if total != node.leaves_below:
                bad.append(("sum", node.level, total, node.leaves_below))
    check(not bad, f"every node: shown leaves + hidden leaves == prod(p-1) below it (problems: {bad[:3]})")
    check(view.root.leaves_below == 480, f"root of 2..11 expands to 480 terminal lanes (got {view.root.leaves_below})")


def section_d_fixed_slice():
    print("\n--- D: fixed slice -- shape independent of a ---")
    from primeatlas.visualization.tree.tree_layout import build_view_tree
    primes = [2, 3, 5, 7]

    def shape(view):
        return [(n.level, n.slot, len(n.children), n.hidden_count) for n in view.nodes], view.slot_count

    base = shape(build_view_tree(1, 0, 1, 0, primes, 4))
    others = [shape(build_view_tree(a, 0, 1, 0, primes, 4)) for a in (0, 2, 97, 210, 211, 10**6 + 3)]
    check(all(o == base for o in others), "node levels, slots and child counts are the same for every a")
    v1 = [n.value for n in build_view_tree(1, 0, 1, 0, primes, 4).nodes]
    v2 = [n.value for n in build_view_tree(500, 0, 1, 0, primes, 4).nodes]
    check(v1 != v2 and all(v >= 500 for v in v2), "the values change with a and stay >= a")
    view = build_view_tree(1, 0, 1, 0, primes, 4)
    leaves = [n for n in view.nodes if not n.children]
    check(sorted(n.slot for n in leaves) == list(range(view.slot_count)),
          "terminal nodes occupy consecutive slots 0..slot_count-1")
    inner = [n for n in view.nodes if n.children]
    check(all(abs(n.slot - sum(c.slot for c in n.children) / len(n.children)) < 1e-9 for n in inner),
          "an inner node sits at the mean slot of its shown children")


def section_e_columns_and_stripes():
    print("\n--- E: prime columns, hollow points, stripes ---")
    import numpy as np
    from primeatlas.visualization.tree.tree_layout import (
        column_lane, lane_values_in_window, prime_divisor_flags, stripe_primes, is_hollow,
    )
    primes = [2, 3, 5, 7]
    for p in primes:
        residue, modulus = column_lane(0, 1, p)
        first, count = lane_values_in_window(1, 30, residue, modulus)
        values = [first + t * modulus for t in range(count)]
        check(values == [v for v in range(1, 31) if v % p == 0],
              f"column {p} over the root holds every multiple of {p} in [1, 31) (got {values})")
    residue, modulus = column_lane(1, 6, 5)
    check(residue % 6 == 1 and residue % 5 == 0 and modulus == 30,
          f"column 5 inside lane 1 mod 6 is 25 mod 30 (got {residue} mod {modulus})")
    check(stripe_primes(6, primes) == [2, 3], "6 has stripes 2,3")
    check(stripe_primes(12, primes) == [2, 3], "12 has stripes 2,3 (exponents ignored)")
    check(stripe_primes(4, primes) == [2], "4 has only the 2 stripe")
    check(stripe_primes(210, primes) == [2, 3, 5, 7], "210 has all four stripes")
    check(stripe_primes(11, primes) == [], "11 has no stripe among 2,3,5,7")
    check(not is_hollow(6, 2, primes), "6 on the 2 column is filled (lpf 2)")
    check(is_hollow(6, 3, primes), "6 on the 3 column is hollow (caught by 2)")
    check(not is_hollow(15, 3, primes) and is_hollow(15, 5, primes), "15: filled on 3, hollow on 5")
    check(not is_hollow(49, 7, primes), "49 on the 7 column is filled")
    flags = prime_divisor_flags(6, 6, 5, primes)
    expected = np.array([[v % q == 0 for q in primes] for v in (6, 12, 18, 24, 30)])
    check(flags.shape == (5, 4) and bool((flags == expected).all()),
          "prime_divisor_flags matches v % q == 0 for every point and prime")
    big = 10**25 + 1
    flags_big = prime_divisor_flags(big, 7, 4, primes)
    expected_big = np.array([[(big + 7 * t) % q == 0 for q in primes] for t in range(4)])
    check(bool((flags_big == expected_big).all()), "prime_divisor_flags is exact for a 26-digit start")


def section_f_density():
    print("\n--- F: density ---")
    from primeatlas.visualization.tree.tree_layout import exact_density, coprime_count
    check(exact_density([2, 3, 5, 7]) == Fraction(48, 210), "prod(1-1/p) over 2,3,5,7 is 48/210")
    check(exact_density([]) == 1, "empty product is 1")
    for a, b in ((1, 211), (0, 1), (5, 5), (1000, 1777), (10**12, 10**12 + 500)):
        brute = sum(1 for v in range(a, b) if all(v % p for p in (2, 3, 5, 7)))
        got = coprime_count(a, b, [2, 3, 5, 7])
        check(got == brute, f"coprime_count({a}, {b}) = {got} matches brute force {brute}")


def section_g_zoom():
    print("\n--- G: zoom parent lane ---")
    from primeatlas.visualization.tree.tree_layout import parent_lane, first_primes, split_lane
    all_primes = first_primes(10)
    occ, free = split_lane(1, 6, 5)
    for r in free:
        check(parent_lane(r, 30, 3, all_primes) == (1, 6, 2), f"parent of {r} mod 30 is 1 mod 6 at depth 2")
    check(parent_lane(1, 2, 1, all_primes) == (0, 1, 0), "parent of 1 mod 2 is the root")
    check(parent_lane(0, 1, 0, all_primes) is None, "the top root has no parent")


def section_h_caps():
    print("\n--- H: node and point caps ---")
    from primeatlas.visualization.tree.tree_layout import (
        count_drawn_nodes, levels_within_cap, line_point_count, effective_window,
    )
    check(count_drawn_nodes([2, 3, 5, 7], 3) == 1 + 1 + 2 + 6 + 18, "count_drawn_nodes K=3 over 2..7")
    check(levels_within_cap([2, 3, 5, 7], 3, 1000) == 4, "a generous cap keeps every level")
    check(levels_within_cap([2, 3, 5, 7], 3, 10) == 3, "max_nodes=10 cuts to 3 levels (1+1+2+6=10)")
    check(levels_within_cap([2, 3, 5, 7], 3, 1) == 1, "at least one level always stays")
    primes = [2, 3, 5, 7]
    h_req = 2 * 210
    full = line_point_count(h_req, 1, primes, 48)
    check(effective_window(h_req, 1, primes, 48, full + 10) == h_req, "no shrink when within max_points")
    h_eff = effective_window(h_req, 1, primes, 48, 100)
    check(1 <= h_eff < h_req and line_point_count(h_eff, 1, primes, 48) <= 100,
          f"the window shrinks so the point count fits max_points (h={h_eff})")


def section_i_bigints():
    print("\n--- I: big integers ---")
    from primeatlas.visualization.tree.tree_layout import build_view_tree
    a = 10**25
    view = build_view_tree(a, 0, 1, 0, [2, 3, 5, 7, 11], 3)
    ok = all(n.value >= a and n.value - a < n.modulus and n.value % n.modulus == n.residue for n in view.nodes)
    check(ok, "every node value at a = 10**25 is the exact first lane value >= a")
    leaves = [n for n in view.nodes if not n.children]
    check(all(gcd(n.value, 2310) == 1 for n in leaves), "terminal values at 10**25 are coprime to 2310")
    zoom = build_view_tree(a, 1, 6, 2, [5, 7, 11], 2)
    check(all(n.value % 6 == 1 for n in zoom.nodes), "a zoomed root (1 mod 6) keeps every node inside its lane")
    check(all(_lpf(n.occupied.value) == n.occupied.prime for n in build_view_tree(1, 0, 1, 0, [2, 3, 5, 7], 6).nodes
              if n.occupied is not None),
          "every occupied child's first value has least prime factor = its prime")


if __name__ == "__main__":
    for section in (section_a_lanes, section_b_representatives, section_c_exact_counts,
                    section_d_fixed_slice, section_e_columns_and_stripes, section_f_density,
                    section_g_zoom, section_h_caps, section_i_bigints):
        try:
            section()
        except Exception as e:  # noqa: BLE001 -- a crash in one section is a failure, not an abort
            import traceback
            traceback.print_exc()
            check(False, f"{section.__name__} raised {type(e).__name__}: {e}")
    print(f"\n{'=' * 78}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
