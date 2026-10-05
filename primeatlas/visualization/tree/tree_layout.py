"""
tree_layout.py -- the arithmetic of the prime tree: consecutive primes p_0 < p_1 < ...
starting at the largest prime <= n. Every node at level i is a copy of p_i. Prime p
leaves p-1 residues mod p free, so a copy of p has p-1 branches to the next prime: up to
`branches` of them are drawn as child copies, the rest are counted as hidden. Every copy
of p also feeds p's one column of multiples p, 2p, 3p, ...

The vertical axis is either the real n axis (a window over the integers) or, where the
multiples of the drawn primes lie too far apart for one window, the multiples axis: the
sorted values k*p (1 <= k <= multiples) placed at equal steps. Pure Python/numpy, no
GL; every value is an exact int, also past uint64.
"""

import math

import numpy as np

from primeatlas.primality.primality import miller_rabin_test

AXIS_AUTO = "auto"
AXIS_REAL = "real"
AXIS_MULTIPLES = "multiples"
AXIS_KINDS = (AXIS_AUTO, AXIS_REAL, AXIS_MULTIPLES)

# "auto" keeps the real axis while the window reaching the last level's 2p is at most
# this many times the levels' own span (start to the next prime after the last level).
_AUTO_REAL_SPAN_RATIO = 8


def is_prime(n):
    return n >= 2 and miller_rabin_test(n)[0]


def prev_prime(n):
    """The largest prime <= n; 2 for n < 2."""
    if n <= 2:
        return 2
    candidate = n if n % 2 else n - 1
    while not is_prime(candidate):
        candidate -= 2
    return candidate


def next_prime(n):
    """The smallest prime > n."""
    if n < 2:
        return 2
    candidate = n + 1 if n % 2 == 0 else n + 2
    while not is_prime(candidate):
        candidate += 2
    return candidate


class TreeLevel:
    """Level `index` of the tree: copies of prime `p`. `total_copies`: the copies of p in
    the full tree, prod_{j<i} (p_j - 1)."""

    def __init__(self, p, index, total_copies):
        self.p = p
        self.index = index
        self.total_copies = total_copies


class TreeNode:
    """One drawn copy of `p` at `level`. `hidden`: its branches to the next prime that
    are not drawn. `slot`: horizontal position (leaves 0..L-1, inner nodes at the mean of
    their children); `leaf_span`: the slots its subtree covers."""

    __slots__ = ("level", "p", "parent", "children", "hidden", "slot", "leaf_span")

    def __init__(self, level, p, parent):
        self.level = level
        self.p = p
        self.parent = parent
        self.children = []
        self.hidden = 0
        self.slot = 0.0
        self.leaf_span = 1


class RealAxis:
    """The real n axis over [bottom, top]; a value's position is its offset from bottom."""

    kind = AXIS_REAL

    def __init__(self, bottom, top):
        self.bottom = bottom
        self.top = top

    @property
    def length(self):
        return self.top - self.bottom

    def position(self, value):
        return value - self.bottom

    def last_multiplier(self, p):
        return self.top // p


class MultiplesAxis:
    """The sorted distinct values k*p (1 <= k <= multiples) of the level primes; a value's
    position is its rank."""

    kind = AXIS_MULTIPLES

    def __init__(self, primes, multiples):
        self.multiples = multiples
        self.values = sorted({k * p for p in primes for k in range(1, multiples + 1)})
        self._rank = {v: i for i, v in enumerate(self.values)}
        self.bottom = self.values[0]
        self.top = self.values[-1]

    @property
    def length(self):
        return len(self.values) - 1

    def position(self, value):
        return self._rank[value]

    def last_multiplier(self, p):
        return self.multiples


class PrimeTree:
    """The drawn tree: `levels`, `nodes` (level order, nodes[0] is the root), the
    vertical `axis`, `slot_count` (drawn leaves) and `levels_cut` (levels left out by the
    node cap). `capped`: the real window was shrunk to the marker cap."""

    def __init__(self, levels, nodes, axis, slot_count, levels_cut, capped):
        self.levels = levels
        self.nodes = nodes
        self.axis = axis
        self.slot_count = slot_count
        self.levels_cut = levels_cut
        self.capped = capped
        self._by_level = {}
        for node in nodes:
            self._by_level.setdefault(node.level, []).append(node)

    @property
    def start(self):
        return self.levels[0].p

    @property
    def primes(self):
        return [level.p for level in self.levels]

    def nodes_at(self, level):
        return self._by_level.get(level, [])


def _drawn_level_count(primes, branches, max_nodes):
    total = 0
    copies = 1
    for i, p in enumerate(primes):
        if i and total + copies > max_nodes:
            return i
        total += copies
        copies *= min(p - 1, branches)
    return len(primes)


def _marker_count(primes, top):
    return sum(top // p for p in primes)


def _real_axis(primes, next_after, height, max_points):
    start = primes[0]
    floor_top = max(next_after, 2 * primes[-1])
    top = max(floor_top, start + math.ceil(height * (next_after - start)))
    capped = False
    if _marker_count(primes, top) > max_points and top > floor_top:
        capped = True
        lo, hi = floor_top, top
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if _marker_count(primes, mid) <= max_points:
                lo = mid
            else:
                hi = mid - 1
        top = lo
    return RealAxis(start, top), capped


def _assign_slots(root):
    next_slot = 0
    stack = [(root, False)]
    while stack:
        node, done = stack.pop()
        if not node.children:
            node.slot = float(next_slot)
            node.leaf_span = 1
            next_slot += 1
        elif done:
            node.slot = sum(c.slot for c in node.children) / len(node.children)
            node.leaf_span = sum(c.leaf_span for c in node.children)
        else:
            stack.append((node, True))
            stack.extend((c, False) for c in reversed(node.children))
    return next_slot


def build_tree(n, depth, branches=3, max_nodes=2000, height=1.5, max_points=500_000, multiples=4,
               axis=AXIS_AUTO):
    """The tree of `depth` consecutive primes from prev_prime(n), cut to max_nodes drawn
    copies, and its vertical axis (`axis`: AXIS_AUTO, AXIS_REAL or AXIS_MULTIPLES)."""
    primes = [prev_prime(n)]
    while len(primes) < depth:
        primes.append(next_prime(primes[-1]))
    drawn = _drawn_level_count(primes, branches, max_nodes)
    levels_cut = drawn < len(primes)
    primes = primes[:drawn]

    levels = []
    total = 1
    for i, p in enumerate(primes):
        levels.append(TreeLevel(p, i, total))
        total *= p - 1

    root = TreeNode(0, primes[0], None)
    nodes = [root]
    frontier = [root]
    for i in range(1, drawn):
        shown = min(primes[i - 1] - 1, branches)
        next_frontier = []
        for parent in frontier:
            parent.hidden = primes[i - 1] - 1 - shown
            for _ in range(shown):
                child = TreeNode(i, primes[i], parent)
                parent.children.append(child)
                next_frontier.append(child)
        nodes.extend(next_frontier)
        frontier = next_frontier
    for node in frontier:
        node.hidden = primes[-1] - 1
    slot_count = _assign_slots(root)

    next_after = next_prime(primes[-1])
    if axis == AXIS_AUTO:
        span = next_after - primes[0]
        axis = AXIS_REAL if 2 * primes[-1] - primes[0] <= _AUTO_REAL_SPAN_RATIO * span else AXIS_MULTIPLES
    capped = False
    if axis == AXIS_REAL:
        tree_axis, capped = _real_axis(primes, next_after, height, max_points)
    else:
        tree_axis = MultiplesAxis(primes, multiples)
    return PrimeTree(levels, nodes, tree_axis, slot_count, levels_cut, capped)


def column_values(tree, p):
    """The multipliers k >= 2 of the multiples k*p drawn on p's column."""
    return np.arange(2, tree.axis.last_multiplier(p) + 1, dtype=np.int64)


def _smallest_factors(limit):
    """spf[k] = the smallest prime factor of k, for 0 <= k <= limit (spf[0] = spf[1] = 0)."""
    spf = np.zeros(limit + 1, dtype=np.int64)
    for q in range(2, int(limit ** 0.5) + 1):
        if spf[q] == 0:
            block = spf[q * q::q]
            block[block == 0] = q
    rest = np.arange(limit + 1, dtype=np.int64)
    unset = spf == 0
    spf[unset] = rest[unset]
    spf[:2] = 0
    return spf


def hollow_flags(p, ks):
    """True for each multiple k*p already sieved out by a smaller prime: k has a prime
    factor below p."""
    if len(ks) == 0:
        return np.zeros(0, dtype=bool)
    spf = _smallest_factors(int(ks.max()))[ks]
    return (ks >= 2) & (spf < p)


def divisor_flags(column_index, ks, level_primes):
    """(len(ks), len(level_primes)) bool: level prime j divides the value
    ks[t] * level_primes[column_index]."""
    flags = np.zeros((len(ks), len(level_primes)), dtype=bool)
    kmax = int(ks.max()) if len(ks) else 0
    for j, q in enumerate(level_primes):
        if j == column_index:
            flags[:, j] = True
        elif q <= kmax:
            flags[:, j] = ks % q == 0
    return flags


def chain_density(primes):
    """prod(1 - 1/p) over `primes`, as a float."""
    density = 1.0
    for p in primes:
        density *= 1.0 - 1.0 / p
    return density
