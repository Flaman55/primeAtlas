"""
test_tree_draw.py -- spec tests for primeatlas/visualization/tree/tree_draw.py (world-space
draw data for the sieve-lane tree), tree_colors.py and highlight_layers.py. No GL.

Spec:
  A. Real n axis: world y is a linear function of the value; a sits at the bottom
     (+max_radius, screen y grows downward) and a + h at the top (-max_radius).
  B. Every drawn free node has one marker at its own position, node-sized.
  C. Prime columns: one column per view prime, one marker per multiple of p in the
     root lane inside the window; hollow when a smaller view prime divides the value;
     stripe colors = distinct view prime divisors ascending, each in its prime's color.
     More divisors than max_stripes: the first max_stripes-1 colors plus a white stripe.
  D. Segments: GL_LINES pairs; parent->free child edges and node->occupied child edges
     (in the prime's color) exist.
  E. Labels: a node with hidden children carries "+hidden" and the exact hidden leaf
     count; every column has a "p=..." header.
  F. Highlight layers come from a registry; the "primes" layer adds one marker per
     drawn point whose value is prime.
  G. Colors: a distinct default color per prime, overridable by a "p=#rrggbb" map;
     malformed or non-prime entries raise ValueError.

Usage:
    python unitTests/test_tree_draw.py
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


R = 450.0
PRIMES = [2, 3, 5, 7]


def _is_prime(n):
    if n < 2:
        return False
    d = 2
    while d * d <= n:
        if n % d == 0:
            return False
        d += 1
    return True


def _build(a=1, h=420, k=3, max_stripes=4, layers=()):
    from primeatlas.visualization.tree.tree_layout import build_view_tree
    from primeatlas.visualization.tree.tree_draw import TreeStyle, build_tree_draw_data
    view = build_view_tree(a, 0, 1, 0, PRIMES, k)
    style = TreeStyle(node_size=11.0, point_size=7.0, max_stripes=max_stripes)
    return view, build_tree_draw_data(view, h, R, style, layers=layers)


def _rows_at(markers, x, y, tol=1e-3):
    return markers[(np.abs(markers[:, 0] - x) < tol) & (np.abs(markers[:, 1] - y) < tol)]


def section_a_axis():
    print("\n--- A: real n axis ---")
    view, data = _build()
    check(abs(data.y_of(1) - R) < 1e-6, f"value a sits at world y = +R (got {data.y_of(1)})")
    check(abs(data.y_of(421) + R) < 1e-6, f"value a+h sits at world y = -R (got {data.y_of(421)})")
    check(data.y_of(100) > data.y_of(200), "a larger value is higher on screen (smaller world y)")
    mid = data.y_of(211)
    check(abs(mid) < 1e-6, f"the window midpoint is at y = 0 (got {mid})")
    big_view, big = _build(a=10**25, h=420)
    check(abs(big.y_of(10**25 + 210)) < 1e-6, "the axis stays exact at a = 10**25")


def section_b_nodes():
    print("\n--- B: one marker per free node ---")
    from primeatlas.visualization.tree.tree_draw import MARKER_FLOATS
    view, data = _build()
    check(data.markers.dtype == np.float32 and data.markers.shape[1] == MARKER_FLOATS,
          f"markers are float32 rows of MARKER_FLOATS columns (got {data.markers.shape})")
    missing = []
    for node in view.nodes:
        x, y = data.node_xy(node)
        rows = _rows_at(data.markers, x, y)
        if not len(rows) or not np.any(np.abs(rows[:, 2] - 11.0) < 1e-6 if node.level else rows[:, 2] >= 11.0):
            missing.append((node.level, node.value))
    check(not missing, f"every free node has a node-sized marker at its position (missing: {missing[:5]})")
    check(len(data.pickables) == len(view.nodes), "every free node is pickable")


def section_c_columns():
    print("\n--- C: prime columns, hollow, stripes ---")
    from primeatlas.visualization.tree.tree_colors import prime_color
    view, data = _build(a=1, h=420)
    for p in PRIMES:
        x = data.column_x[p]
        col = data.markers[np.abs(data.markers[:, 0] - x) < 1e-3]
        expected = len([v for v in range(1, 421) if v % p == 0])
        check(len(col) == expected, f"column {p} has one marker per multiple of {p} in the window "
                                    f"({len(col)} vs {expected})")

    def marker(p, value):
        rows = _rows_at(data.markers, data.column_x[p], data.y_of(value))
        return rows[0] if len(rows) else None

    m6_2, m6_3 = marker(2, 6), marker(3, 6)
    check(m6_2 is not None and m6_3 is not None, "6 is on both the 2 and the 3 column, at the same height")
    if m6_2 is not None and m6_3 is not None:
        check(m6_2[3] == 0.0 and m6_3[3] == 1.0, "6 is filled on the 2 column and hollow on the 3 column")
        check(int(m6_3[4]) == 2, "6 has two stripes")
        check(np.allclose(m6_3[5:8], prime_color(2)) and np.allclose(m6_3[8:11], prime_color(3)),
              "6's stripes are the 2 color then the 3 color")
    m12 = marker(2, 12)
    check(m12 is not None and int(m12[4]) == 2, "12 has two stripes (exponents ignored)")
    m4 = marker(2, 4)
    check(m4 is not None and int(m4[4]) == 1 and np.allclose(m4[5:8], prime_color(2)), "4 has only the 2 stripe")
    _, narrow = _build(a=1, h=420, max_stripes=2)
    rows = _rows_at(narrow.markers, narrow.column_x[2], narrow.y_of(30))
    check(len(rows) and int(rows[0][4]) == 2 and np.allclose(rows[0][5:8], prime_color(2))
          and np.allclose(rows[0][8:11], (1.0, 1.0, 1.0)),
          "30 with max_stripes=2: the 2 color then a white overflow stripe")


def section_d_segments():
    print("\n--- D: segments ---")
    from primeatlas.visualization.tree.tree_colors import prime_color
    view, data = _build()
    seg = data.segments
    check(seg.dtype == np.float32 and seg.shape[1] == 6 and seg.shape[0] % 2 == 0,
          f"segments are float32 (x,y,r,g,b,a) rows in pairs (got {seg.shape})")

    def has_segment(p0, p1, rgb=None):
        for i in range(0, len(seg), 2):
            a, b = seg[i], seg[i + 1]
            if np.allclose(a[:2], p0, atol=1e-3) and np.allclose(b[:2], p1, atol=1e-3):
                if rgb is None or np.allclose(a[2:5], rgb, atol=1e-3):
                    return True
        return False

    root = view.root
    child = root.children[0]
    check(has_segment(data.node_xy(root), data.node_xy(child)), "an edge joins the root to its free child")
    occ = root.occupied
    check(has_segment(data.node_xy(root), (data.column_x[2], data.y_of(occ.value)), prime_color(2)),
          "an edge in the 2 color joins the root to its occupied child on the 2 column")


def section_e_labels():
    print("\n--- E: labels ---")
    view, data = _build(k=2)
    texts = [label.text for label in data.labels]
    hidden_nodes = [n for n in view.nodes if n.hidden_count]
    check(hidden_nodes, "K=2 over 2,3,5,7 hides some children")
    missing = [n.value for n in hidden_nodes
               if not any(f"+{n.hidden_count}" in t and f"{n.hidden_leaves:,}" in t for t in texts)]
    check(not missing, f"every node with hidden children has a '+N' label with the hidden leaf count "
                       f"(missing for values {missing[:5]})")
    for p in PRIMES:
        check(any(t == f"p={p}" for t in texts), f"column {p} has a 'p={p}' header label")


def section_f_layers():
    print("\n--- F: highlight layers ---")
    from primeatlas.visualization.tree.highlight_layers import LAYERS, make_layers
    check("primes" in LAYERS, f"the registry has a 'primes' layer (got {sorted(LAYERS)})")
    try:
        make_layers(["nope"])
        check(False, "an unknown layer name raises ValueError")
    except ValueError:
        check(True, "an unknown layer name raises ValueError")
    view, plain = _build()
    _, lit = _build(layers=make_layers(["primes"]))
    # One entry per drawn point: a value drawn twice (a free node that is also its own
    # occupied child's first multiple, e.g. 5) is two points.
    expected = len([v for v in plain.point_values if _is_prime(v)])
    check(len(plain.point_values) == len(plain.markers), "point_values lists one value per marker")
    check(lit.layer_counts.get("primes") == expected,
          f"the primes layer counts every prime among the drawn points ({lit.layer_counts} vs {expected})")
    check(len(lit.markers) == len(plain.markers) + expected,
          "the primes layer adds exactly one marker per highlighted point")


def section_g_colors():
    print("\n--- G: colors ---")
    from primeatlas.visualization.tree.tree_colors import prime_color, parse_color_map
    from primeatlas.visualization.tree.tree_layout import first_primes
    colors = [tuple(prime_color(p)) for p in first_primes(12)]
    check(len(set(colors)) == 12, "the first 12 primes get 12 distinct default colors")
    overrides = parse_color_map("2=#ff0000, 3=00ff00")
    check(overrides == {2: (1.0, 0.0, 0.0), 3: (0.0, 1.0, 0.0)}, f"parse_color_map (got {overrides})")
    check(tuple(prime_color(2, overrides)) == (1.0, 0.0, 0.0) and tuple(prime_color(5, overrides)) == tuple(prime_color(5)),
          "an override replaces only its own prime's color")
    check(parse_color_map("") == {}, "an empty map is no override")
    for bad in ("2=#zzzzzz", "4=#ff0000", "2", "x=#ff0000"):
        try:
            parse_color_map(bad)
            check(False, f"parse_color_map({bad!r}) raises ValueError")
        except ValueError:
            check(True, f"parse_color_map({bad!r}) raises ValueError")


if __name__ == "__main__":
    for section in (section_a_axis, section_b_nodes, section_c_columns, section_d_segments,
                    section_e_labels, section_f_layers, section_g_colors):
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
