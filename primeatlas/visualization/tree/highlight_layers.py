"""
highlight_layers.py -- pluggable highlight layers for the sieve-lane tree. A layer looks
at every drawn point and picks the ones it marks; tree_draw.py draws one highlight ring
per picked point, under the point itself. Adding a layer means one HighlightLayer
subclass plus one LAYERS entry; the tree, the renderer CLI (--tree-highlight) and the
Tree tab's checkboxes all read LAYERS.
"""

from primeatlas.primality.primality import miller_rabin_test
from primeatlas.visualization.tree.tree_colors import HIGHLIGHT_PRIME_RGB

POINT_NODE = "node"
POINT_LANE = "lane"
POINT_COLUMN = "column"


class HighlightLayer:
    """One highlight layer. `name` is its CLI/registry id, `rgb` its ring color."""

    name = None
    rgb = (1.0, 1.0, 1.0)

    def picks(self, value, kind, column_prime):
        """True when the point (its `value`, its `kind` -- POINT_NODE / POINT_LANE /
        POINT_COLUMN -- and for a column point the column's prime) is highlighted."""
        raise NotImplementedError

    def picks_column(self, p, first, step, count):
        """Indices t of the picked points first + t*step on p's column."""
        return [t for t in range(count) if self.picks(first + t * step, POINT_COLUMN, p)]

    def hud_line(self, count):
        return f"Highlight {self.name}: {count:,} points"


class PrimesLayer(HighlightLayer):
    """Marks the real primes among the drawn points. A column point is a multiple of
    its column's prime, so it is prime only when it IS that prime."""

    name = "primes"
    rgb = HIGHLIGHT_PRIME_RGB

    def picks(self, value, kind, column_prime):
        if kind == POINT_COLUMN:
            return value == column_prime
        return miller_rabin_test(value)[0]

    def picks_column(self, p, first, step, count):
        if first <= p < first + count * step and (p - first) % step == 0:
            return [(p - first) // step]
        return []

    def hud_line(self, count):
        return f"Primes highlighted: {count:,}"


LAYERS = {
    PrimesLayer.name: PrimesLayer,
}


def make_layers(names):
    """Instances of the named layers, in the given order. Raises ValueError on an
    unknown name."""
    unknown = [n for n in names if n not in LAYERS]
    if unknown:
        raise ValueError(f"unknown highlight layer(s) {unknown}; known: {sorted(LAYERS)}")
    return [LAYERS[n]() for n in names]
