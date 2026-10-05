"""
test_tree_layout.py -- spec tests for primeatlas/visualization/tree/tree_layout.py, the
arithmetic of the prime tree: consecutive primes p_0 < p_1 < ... starting at the largest
prime <= n; every node at level i is a copy of p_i, with up to `branches` children (copies
of p_{i+1}) drawn out of its p_i - 1 free branches, the rest counted as hidden; every
copy of p also feeds p's one column of multiples. No GL.

Spec:
  A. prev_prime(n) is the largest prime <= n (n < 2 gives 2); next_prime(n) the
     smallest prime > n. Both work past uint64.
  B. Levels: build_tree(n, depth, ...) has `depth` levels from prev_prime(n); level i
     holds prod_{j<i} min(p_j - 1, branches) copies of p_i (n=1, branches=3: 1, 1, 2, 6,
     18) and reports the exact copy count of the full tree, prod_{j<i} (p_j - 1).
  C. Hidden branches: a node below the last drawn level shows min(p-1, branches)
     children and hides the rest (2: 0, 3: 0, 5: 1, 7: 3, 11: 7); a node on the last
     drawn level shows none and hides all p-1.
  D. Node cap: levels are drawn while the total node count stays <= max_nodes (always
     at least one level); a cut tree reports levels_cut.
  E. Slots: the drawn leaves take consecutive slots 0..L-1, every inner node sits at
     the mean slot of its children.
  F. Axis choice: "real" and "multiples" are taken as given; "auto" picks the real n
     axis while the drawn primes' doubles fit a short window (n=2) and the multiples
     axis otherwise (n=1000, n=10**6).
  G. Real axis: the window runs from the start prime to max(start + ceil(height *
     (next prime after the last level - start)), 2 * last level prime); a value's
     position is its offset from the start; column p holds k*p for 2 <= k <= top // p.
  H. Multiples axis: the axis values are the sorted distinct k*p (1 <= k <= multiples)
     over the drawn level primes; a value's position is its rank; column p holds k*p
     for 2 <= k <= multiples.
  I. Columns: a multiple k*p is hollow when k has a prime factor smaller than p;
     divisor flags mark the level primes dividing a column value.

Usage:
    python unitTests/test_tree_layout.py
"""
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "prime_sieve"))

import numpy as np

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


def _build(n=1, depth=5, **kw):
    from primeatlas.visualization.tree.tree_layout import build_tree
    return build_tree(n, depth=depth, **kw)


def section_a_prev_next():
    print("\n--- A: prev_prime / next_prime ---")
    from primeatlas.visualization.tree.tree_layout import prev_prime, next_prime
    for n, expected in ((0, 2), (1, 2), (2, 2), (3, 3), (4, 3), (10, 7), (11, 11), (12, 11), (100, 97)):
        check(prev_prime(n) == expected, f"prev_prime({n}) = {expected} (got {prev_prime(n)})")
    for n, expected in ((0, 2), (1, 2), (2, 3), (3, 5), (7, 11), (13, 17), (97, 101)):
        check(next_prime(n) == expected, f"next_prime({n}) = {expected} (got {next_prime(n)})")
    check(prev_prime(2 ** 64) == 2 ** 64 - 59, "prev_prime(2^64) = 2^64-59")
    check(next_prime(2 ** 64) == 2 ** 64 + 13, "next_prime(2^64) = 2^64+13")


def section_b_levels():
    print("\n--- B: levels ---")
    t = _build(1, depth=5, branches=3)
    check(t.start == 2 and [lv.p for lv in t.levels] == [2, 3, 5, 7, 11],
          f"n=1: levels 2,3,5,7,11 (got {[lv.p for lv in t.levels]})")
    counts = [len(t.nodes_at(i)) for i in range(5)]
    check(counts == [1, 1, 2, 6, 18], f"copies per level 1,1,2,6,18 (got {counts})")
    check([lv.total_copies for lv in t.levels] == [1, 1, 2, 8, 48],
          f"full-tree copies prod(p_j - 1): 1,1,2,8,48 (got {[lv.total_copies for lv in t.levels]})")
    check(all(node.p == t.levels[node.level].p for node in t.nodes), "every node is a copy of its level's prime")
    check(all(node.parent is None if node.level == 0 else node.parent.level == node.level - 1 for node in t.nodes),
          "every non-root node hangs under a node of the level below")
    t = _build(100, depth=3, branches=3, axis="multiples")
    check([lv.p for lv in t.levels] == [97, 101, 103], f"a composite n=100 starts at 97 (got {[lv.p for lv in t.levels]})")
    t = _build(10 ** 20, depth=2, axis="multiples")
    check(t.start <= 10 ** 20 < t.levels[1].p, "a tree past uint64 builds")


def section_c_hidden():
    print("\n--- C: hidden branches ---")
    t = _build(1, depth=6, branches=3, max_nodes=10 ** 6)
    got = [(n.p, len(n.children), n.hidden) for n in (t.nodes_at(i)[0] for i in range(6))]
    check(got == [(2, 1, 0), (3, 2, 0), (5, 3, 1), (7, 3, 3), (11, 3, 7), (13, 0, 12)],
          f"children/hidden per level, last level hides all p-1 (got {got})")
    t = _build(1, depth=4, branches=1)
    got = [(len(n.children), n.hidden) for n in (t.nodes_at(i)[0] for i in range(4))]
    check(got == [(1, 0), (1, 1), (1, 3), (0, 6)], f"branches=1 (got {got})")


def section_d_cap():
    print("\n--- D: node cap ---")
    t = _build(1, depth=6, branches=3, max_nodes=10)
    check(len(t.levels) == 4 and len(t.nodes) == 10 and t.levels_cut,
          f"max_nodes=10 draws 1+1+2+6 (levels {len(t.levels)}, nodes {len(t.nodes)}, cut {t.levels_cut})")
    check(all(n.hidden == 6 and not n.children for n in t.nodes_at(3)), "the cut level hides all of its branches")
    t = _build(1, depth=3, max_nodes=1)
    check(len(t.levels) == 1, "at least one level is drawn")
    t = _build(1, depth=3, max_nodes=10 ** 6)
    check(not t.levels_cut, "an uncut tree reports levels_cut=False")


def section_e_slots():
    print("\n--- E: slots ---")
    t = _build(1, depth=5, branches=3)
    leaves = sorted(n.slot for n in t.nodes if not n.children)
    check(leaves == list(range(len(leaves))), f"leaves take slots 0..L-1 (got {leaves[:6]}...)")
    bad = [n for n in t.nodes if n.children and abs(n.slot - np.mean([c.slot for c in n.children])) > 1e-9]
    check(not bad, "inner nodes sit at the mean of their children")
    check(t.slot_count == len(leaves), "slot_count is the leaf count")


def section_f_axis_choice():
    print("\n--- F: axis choice ---")
    check(_build(2, depth=4).axis.kind == "real", "auto: n=2 uses the real axis")
    check(_build(1000, depth=4).axis.kind == "multiples", "auto: n=1000 uses the multiples axis")
    check(_build(10 ** 6, depth=4).axis.kind == "multiples", "auto: n=10**6 uses the multiples axis")
    check(_build(2, depth=4, axis="multiples").axis.kind == "multiples", "an explicit multiples axis is kept")
    check(_build(1000, depth=2, axis="real").axis.kind == "real", "an explicit real axis is kept")


def section_g_real_axis():
    print("\n--- G: real axis ---")
    from primeatlas.visualization.tree.tree_layout import column_values
    t = _build(2, depth=4, height=1.5, axis="real")
    check(t.axis.bottom == 2 and t.axis.top == 16, f"window [2, max(2 + ceil(1.5 * 9), 14)] = [2, 16] (got {t.axis.bottom}, {t.axis.top})")
    t = _build(2, depth=4, height=1.0, axis="real")
    check(t.axis.top == 14, f"the window reaches 2 * 7 = 14 (got {t.axis.top})")
    check(t.axis.position(9) - t.axis.position(2) == 7, "a real position is the offset from the start")
    ks = column_values(t, 3)
    check(list(ks * 3) == [6, 9, 12], f"column 3 holds 6..12 (got {list(ks * 3)})")


def section_h_multiples_axis():
    print("\n--- H: multiples axis ---")
    from primeatlas.visualization.tree.tree_layout import column_values
    t = _build(97, depth=3, multiples=4, axis="multiples")
    expected = [97, 101, 103, 194, 202, 206, 291, 303, 309, 388, 404, 412]
    check(list(t.axis.values) == expected, f"axis values (got {list(t.axis.values)})")
    check([t.axis.position(v) for v in (97, 101, 194, 412)] == [0, 1, 3, 11], "a position is the value's rank")
    check(list(column_values(t, 101) * 101) == [202, 303, 404], "column 101 holds 2p..4p")
    t = _build(2, depth=3, multiples=4, axis="multiples")
    check(list(t.axis.values) == [2, 3, 4, 5, 6, 8, 9, 10, 12, 15, 20], f"shared values appear once (got {list(t.axis.values)})")


def section_i_columns():
    print("\n--- I: hollow and divisor flags ---")
    from primeatlas.visualization.tree.tree_layout import hollow_flags, divisor_flags
    for p in (2, 3, 5, 7):
        ks = np.arange(1, 60 // p + 1, dtype=np.int64)
        check(list(map(bool, hollow_flags(p, ks))) == [_lpf(int(k) * p) < p for k in ks],
              f"column {p}: hollow = least prime factor below p")
    chain = [2, 3, 5, 7]
    ks = np.arange(1, 11, dtype=np.int64)
    flags = divisor_flags(1, ks, chain)
    check(all(list(map(bool, row)) == [int(k) * 3 % q == 0 for q in chain] for row, k in zip(flags, ks)),
          "column 3 flags = level primes dividing each value")
    big = [10 ** 20 + 39, 10 ** 20 + 129]
    flags = divisor_flags(0, np.array([1, 2], dtype=np.int64), big)
    check(flags.tolist() == [[True, False], [True, False]], "a level prime above the value never flags it")


if __name__ == "__main__":
    for section in (section_a_prev_next, section_b_levels, section_c_hidden, section_d_cap, section_e_slots,
                    section_f_axis_choice, section_g_real_axis, section_h_multiples_axis, section_i_columns):
        try:
            section()
        except Exception as e:  # noqa: BLE001
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
