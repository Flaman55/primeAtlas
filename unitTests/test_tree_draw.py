"""
test_tree_draw.py -- spec tests for primeatlas/visualization/tree/tree_draw.py (world-space
draw data for the prime tree), tree_colors.py and highlight_layers.py. No GL.

Spec:
  A. Vertical axis: world y falls as the axis position grows (larger values higher on
     screen); the window fits inside [-R, R]; the real axis is linear in the value,
     the multiples axis puts consecutive axis values at equal steps; exact past uint64.
  B. Nodes: every copy has a node-sized marker at (x_of_slot(slot), y_of(p)) and is
     pickable with its prime.
  C. Edges: every parent/child pair is joined by a segment.
  D. Columns: one column per level prime, right of the tree, in level order; every copy
     of p -- 2 and 3 included -- has a merge line from its own position to p's column
     at 2p. The column holds one marker per k*p, 2 <= k <= the axis' last k (real:
     top // p, multiples: --multiples); hollow when k has a prime factor below p;
     stripes = distinct level primes dividing the value, ascending, in level colors;
     more divisors than max_stripes: the first max_stripes-1 colors plus white.
  E. Hidden branches: every copy with hidden > 0 has one dashed stub and a "+hidden"
     label; a copy without has none. A copy with drawn children points its stub at the
     next position of its fan (one child spacing right of the last child, at the
     children's height), stopping short of it.
  F. Real axis: a value on several columns gets one horizontal link spanning them
     (6: 2..3, 30: 2..5). Multiples axis: a "+gap" label between consecutive axis values.
  G. Highlight layers come from a registry; the "primes" layer adds one marker per
     drawn point whose value is prime.
  H. Colors: level index i gets default palette color i (distinct for the first 12),
     overridable per prime by a "p=#rrggbb" map; a prime past uint64 colors instantly;
     malformed or non-prime map entries raise ValueError.

Usage:
    python unitTests/test_tree_draw.py
"""
import os
import sys
import time

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
NODE = 11.0
POINT = 7.0


def _is_prime(n):
    if n < 2:
        return False
    d = 2
    while d * d <= n:
        if n % d == 0:
            return False
        d += 1
    return True


def _lpf(n):
    d = 2
    while d * d <= n:
        if n % d == 0:
            return d
        d += 1
    return n


def _build(n=2, depth=4, branches=3, height=4.0, axis="real", multiples=4, max_stripes=4, layers=(),
           colors=None):
    from primeatlas.visualization.tree.tree_layout import build_tree
    from primeatlas.visualization.tree.tree_draw import TreeStyle, build_tree_draw_data
    tree = build_tree(n, depth=depth, branches=branches, height=height, axis=axis, multiples=multiples)
    style = TreeStyle(node_size=NODE, point_size=POINT, max_stripes=max_stripes, colors=colors)
    return tree, build_tree_draw_data(tree, R, style, layers=layers)


def _rows_at(markers, x, y, tol=1e-3):
    return markers[(np.abs(markers[:, 0] - x) < tol) & (np.abs(markers[:, 1] - y) < tol)]


def _has_segment(seg, p0, p1, tol=1e-3):
    a, b = seg[0::2, :2], seg[1::2, :2]
    hit = ((np.abs(a - p0) < tol).all(axis=1) & (np.abs(b - p1) < tol).all(axis=1)) | \
          ((np.abs(a - p1) < tol).all(axis=1) & (np.abs(b - p0) < tol).all(axis=1))
    return bool(hit.any())


def section_a_axis():
    print("\n--- A: vertical axis ---")
    tree, data = _build()
    ys = [data.y_of(v) for v in (2, 10, 20, tree.axis.top)]
    check(ys == sorted(ys, reverse=True), f"larger values are higher on screen (got {ys})")
    check(-R <= data.y_of(tree.axis.top) and data.y_of(2) <= R, "the window fits inside [-R, R]")
    check(abs((data.y_of(20) - data.y_of(10)) - (data.y_of(30) - data.y_of(20))) < 1e-9, "the real axis is linear")
    tree, data = _build(n=97, depth=3, axis="multiples")
    steps = np.diff([data.y_of(v) for v in tree.axis.values])
    check(np.allclose(steps, steps[0]) and steps[0] < 0, "the multiples axis has equal steps")
    big_tree, big = _build(n=10 ** 25, depth=3, axis="multiples")
    vals = big_tree.axis.values
    check(big.y_of(vals[1]) < big.y_of(vals[0]), "the multiples axis works past uint64")


def section_b_nodes():
    print("\n--- B: nodes ---")
    from primeatlas.visualization.tree.tree_draw import MARKER_FLOATS
    tree, data = _build()
    check(data.markers.dtype == np.float32 and data.markers.shape[1] == MARKER_FLOATS,
          f"markers are float32 rows of MARKER_FLOATS columns (got {data.markers.shape})")
    missing = [n.p for n in tree.nodes
               if not np.any(np.abs(_rows_at(data.markers, *data.node_xy(n))[:, 2] - NODE) < 1e-6)]
    check(not missing, f"every copy has a node-sized marker (missing {missing[:5]})")
    check(abs(data.node_xy(tree.nodes[0])[1] - data.y_of(2)) < 1e-9, "a copy sits at its prime's height")
    check(sorted(p for _x, _y, p in data.pickables) == sorted(n.p for n in tree.nodes), "every copy is pickable")


def section_c_edges():
    print("\n--- C: edges ---")
    tree, data = _build()
    seg = data.segments
    check(seg.dtype == np.float32 and seg.shape[1] == 6 and seg.shape[0] % 2 == 0, "segments are float32 pairs")
    missing = [(n.parent.p, n.p) for n in tree.nodes if n.parent is not None
               and not _has_segment(seg, data.node_xy(n.parent), data.node_xy(n))]
    check(not missing, f"every parent/child pair has an edge (missing {missing[:4]})")


def section_d_columns():
    print("\n--- D: columns ---")
    from primeatlas.visualization.tree.tree_colors import prime_color
    tree, data = _build(height=4.0)
    primes = [lv.p for lv in tree.levels]
    xs = [data.column_x[p] for p in primes]
    tree_right = max(data.node_xy(n)[0] for n in tree.nodes)
    check(xs == sorted(xs) and xs[0] > tree_right, f"columns run right of the tree in level order (got {xs})")
    missing = [n.p for n in tree.nodes
               if not _has_segment(data.segments, data.node_xy(n), (data.column_x[n.p], data.y_of(2 * n.p)))]
    check(not missing, f"every copy (2 and 3 included) has a merge line to its column at 2p (missing {missing[:5]})")
    for p in primes:
        col = data.markers[(np.abs(data.markers[:, 0] - data.column_x[p]) < 1e-3)
                           & (np.abs(data.markers[:, 2] - POINT) < 1e-6)]
        expected = tree.axis.top // p - 1
        bad = [k * p for k in range(2, tree.axis.top // p + 1)
               if not len(_rows_at(col, data.column_x[p], data.y_of(k * p)))
               or _rows_at(col, data.column_x[p], data.y_of(k * p))[0][3] != float(_lpf(k) < p)]
        check(len(col) == expected and not bad, f"column {p}: {expected} markers 2p..top, hollow by lpf (bad {bad[:4]})")

    def marker(p, value):
        rows = _rows_at(data.markers, data.column_x[p], data.y_of(value))
        return rows[0] if len(rows) else None

    c2, c3 = prime_color(2, index=0), prime_color(3, index=1)
    m6 = marker(3, 6)
    check(m6 is not None and m6[3] == 1.0 and int(m6[4]) == 2 and np.allclose(m6[5:8], c2)
          and np.allclose(m6[8:11], c3), "6 on column 3: hollow, the 2 stripe then the 3 stripe")
    m4 = marker(2, 4)
    check(m4 is not None and m4[3] == 0.0 and int(m4[4]) == 1, "4: filled, one stripe")
    _, narrow = _build(height=4.0, max_stripes=2)
    rows = _rows_at(narrow.markers, narrow.column_x[2], narrow.y_of(30))
    check(len(rows) and int(rows[0][4]) == 2 and np.allclose(rows[0][8:11], (1.0, 1.0, 1.0)),
          "30 with max_stripes=2 ends in a white overflow stripe")
    tree, data = _build(n=97, depth=3, axis="multiples", multiples=4)
    col = data.markers[(np.abs(data.markers[:, 0] - data.column_x[101]) < 1e-3)
                       & (np.abs(data.markers[:, 2] - POINT) < 1e-6)]
    check(len(col) == 3, f"multiples axis: column 101 holds 202, 303, 404 (got {len(col)})")


def section_e_hidden():
    print("\n--- E: hidden branches ---")
    tree, data = _build(depth=5)
    texts = [label.text for label in data.labels]
    with_hidden = [n for n in tree.nodes if n.hidden]
    check(len(data.hidden_stubs) == len(with_hidden), f"one stub per copy with hidden branches "
                                                       f"({len(data.hidden_stubs)} vs {len(with_hidden)})")
    check(all(f"+{n.hidden}" in texts for n in with_hidden), "each stub has its '+hidden' label")
    stubs = {id(node): (start, end) for node, start, end in data.hidden_stub_nodes}
    bad = []
    for n in with_hidden:
        if not n.children:
            continue
        xs = [data.node_xy(c)[0] for c in n.children]
        spacing = xs[1] - xs[0] if len(xs) > 1 else data.slot_world
        virtual = np.array([xs[-1] + spacing, data.node_xy(n.children[-1])[1]])
        start, end = (np.asarray(v) for v in stubs[id(n)])
        a, b = virtual - start, end - start
        if abs(a[0] * b[1] - a[1] * b[0]) > 1e-6 * np.dot(a, a) or np.dot(a, b) <= 0 or np.dot(b, b) >= np.dot(a, a):
            bad.append(n.p)
    check(not bad, f"a stub points at the next fan position, short of it (bad {bad[:4]})")


def section_f_axis_extras():
    print("\n--- F: shared links and gap labels ---")
    tree, data = _build(height=4.0)
    links = {value: (x0, x1) for value, x0, x1 in data.shared_links}
    check(6 in links and np.allclose(links[6], (data.column_x[2], data.column_x[3])), "6 links columns 2..3")
    check(30 in links and np.allclose(links[30], (data.column_x[2], data.column_x[5])), "30 links columns 2..5")
    check(9 not in links, "9 (column 3 only) has no link")
    tree, data = _build(n=97, depth=3, axis="multiples")
    texts = [label.text for label in data.labels]
    check("+4" in texts and "+91" in texts, "gap labels between axis values (97->101: +4, 103->194: +91)")


def section_g_layers():
    print("\n--- G: highlight layers ---")
    from primeatlas.visualization.tree.highlight_layers import LAYERS, make_layers
    check("primes" in LAYERS, f"the registry has a 'primes' layer (got {sorted(LAYERS)})")
    try:
        make_layers(["nope"])
        check(False, "an unknown layer name raises ValueError")
    except ValueError:
        check(True, "an unknown layer name raises ValueError")
    _, plain = _build()
    _, lit = _build(layers=make_layers(["primes"]))
    expected = len([v for v in plain.point_values if _is_prime(v)])
    check(len(plain.point_values) == len(plain.markers), "point_values lists one value per marker")
    check(expected > 0 and lit.layer_counts.get("primes") == expected,
          f"the primes layer counts every drawn prime ({lit.layer_counts} vs {expected})")
    check(len(lit.markers) == len(plain.markers) + expected, "one extra marker per highlighted point")


def section_h_colors():
    print("\n--- H: colors ---")
    from primeatlas.visualization.tree.tree_colors import prime_color, parse_color_map
    check(len({tuple(prime_color(0, index=i)) for i in range(12)}) == 12, "12 distinct default colors")
    t0 = time.perf_counter()
    prime_color(10 ** 20 + 39, index=3)
    check(time.perf_counter() - t0 < 0.05, "a prime past uint64 gets its color instantly")
    overrides = parse_color_map("2=#ff0000, 3=00ff00")
    check(overrides == {2: (1.0, 0.0, 0.0), 3: (0.0, 1.0, 0.0)}, f"parse_color_map (got {overrides})")
    _, data = _build(colors=overrides)
    m = _rows_at(data.markers, data.column_x[2], data.y_of(4))
    check(len(m) and np.allclose(m[0][5:8], (1.0, 0.0, 0.0)), "the draw data uses the override")
    check(parse_color_map("") == {}, "an empty map is no override")
    for bad in ("2=#zzzzzz", "4=#ff0000", "2", "x=#ff0000"):
        try:
            parse_color_map(bad)
            check(False, f"parse_color_map({bad!r}) raises ValueError")
        except ValueError:
            check(True, f"parse_color_map({bad!r}) raises ValueError")


if __name__ == "__main__":
    for section in (section_a_axis, section_b_nodes, section_c_edges, section_d_columns, section_e_hidden,
                    section_f_axis_extras, section_g_layers, section_h_colors):
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
