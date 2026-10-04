"""
tree_layout.py -- the arithmetic of the sieve-lane tree, with no drawing and no GL.

A lane is an arithmetic progression {residue + t*modulus}. Applying prime p to a lane
splits it into p child lanes mod modulus*p: exactly one is occupied (made only of
multiples of p) and p-1 are free. Starting from the root lane (0 mod 1, every integer)
and applying the primes in increasing order, the free lanes at depth d are the residues
coprime to the first d primes.

Real n axis: a lane's node sits at the lane's first value >= a, where a is the window
start (the session's N). A child lane is a subset of its parent, so a child's value is
never below its parent's.

Scale: a node draws at most K free children -- the K with the lowest values -- and
reports the others as a hidden count plus the exact number of terminal lanes they
would expand to. By CRT every free lane at one depth has the same subtree shape, so
counts are products of (p-1) and the full tree is never built. The drawn shape (node
count, slots, depths) depends only on the primes and K, never on a: moving along n
changes only the values.

A view starts at any free lane (the root; zooming into a subtree moves it) and spans
the next primes (`level_primes`). Every free view root is coprime to the primes before
it, so the least prime factor of a value in the view is decided by the view primes.
"""

from dataclasses import dataclass, field
from fractions import Fraction
from itertools import combinations

import numpy as np


def first_primes(count):
    """The first `count` primes, ascending."""
    primes = []
    candidate = 2
    while len(primes) < count:
        if all(candidate % p for p in primes if p * p <= candidate):
            primes.append(candidate)
        candidate += 1
    return primes


def lane_first_value(a, residue, modulus):
    """Smallest v >= a with v = residue (mod modulus)."""
    return a + (residue - a) % modulus


def split_lane(residue, modulus, p):
    """Splits lane `residue` mod `modulus` by prime p into (occupied_residue,
    [free_residues]), every residue taken mod modulus*p. The occupied child is the
    one whose values are all multiples of p."""
    child_modulus = modulus * p
    children = [(residue + k * modulus) % child_modulus for k in range(p)]
    occupied = next(c for c in children if c % p == 0)
    return occupied, [c for c in children if c != occupied]


def leaves_if_expanded(level_primes):
    """Number of terminal free lanes one lane expands to over `level_primes`:
    prod(p - 1)."""
    total = 1
    for p in level_primes:
        total *= p - 1
    return total


def count_drawn_nodes(level_primes, k):
    """Free nodes drawn (root included) with at most k free children per node."""
    total = 1
    width = 1
    for p in level_primes:
        width *= min(p - 1, k)
        total += width
    return total


def levels_within_cap(level_primes, k, max_nodes):
    """Largest number of leading levels whose drawn node count stays within
    max_nodes; at least 1."""
    levels = 1
    for count in range(2, len(level_primes) + 1):
        if count_drawn_nodes(level_primes[:count], k) > max_nodes:
            break
        levels = count
    return min(levels, len(level_primes))


@dataclass
class OccupiedLane:
    """The occupied child of a node: the multiples of `prime` inside the node's lane."""
    prime: int
    residue: int
    modulus: int
    value: int


@dataclass(eq=False)
class TreeNode:
    """One drawn free lane. `depth` counts the primes applied since the top root;
    `level` counts them since the view root. `slot` is the horizontal position in
    leaf-slot units."""
    depth: int
    level: int
    residue: int
    modulus: int
    value: int
    leaves_below: int
    parent: "TreeNode" = None
    children: list = field(default_factory=list)
    occupied: OccupiedLane = None
    hidden_count: int = 0
    hidden_leaves: int = 0
    slot: float = 0.0
    leaf_span: int = 1


@dataclass
class TreeView:
    """A built view: the root node, every drawn node in breadth-first order, and the
    slot count (drawn terminal nodes)."""
    a: int
    root: TreeNode
    nodes: list
    level_primes: list
    slot_count: int

    def nodes_at_level(self, level):
        return [n for n in self.nodes if n.level == level]

    @property
    def leaf_modulus(self):
        return self.root.modulus * _product(self.level_primes)


def _product(values):
    total = 1
    for v in values:
        total *= v
    return total


def build_view_tree(a, root_residue, root_modulus, root_depth, level_primes, k):
    """Builds the drawn tree under lane `root_residue` mod `root_modulus` (depth
    `root_depth`) over `level_primes`, showing at most `k` free children per node (the
    lowest values, ascending), and assigns slots."""
    level_primes = list(level_primes)
    root = TreeNode(depth=root_depth, level=0, residue=root_residue % root_modulus, modulus=root_modulus,
                    value=lane_first_value(a, root_residue, root_modulus),
                    leaves_below=leaves_if_expanded(level_primes))
    nodes = [root]
    frontier = [root]
    for level, p in enumerate(level_primes):
        next_frontier = []
        deeper_leaves = leaves_if_expanded(level_primes[level + 1:])
        for node in frontier:
            child_modulus = node.modulus * p
            occupied, free = split_lane(node.residue, node.modulus, p)
            node.occupied = OccupiedLane(p, occupied, child_modulus, lane_first_value(a, occupied, child_modulus))
            ranked = sorted((lane_first_value(a, r, child_modulus), r) for r in free)
            for value, residue in ranked[:k]:
                child = TreeNode(depth=node.depth + 1, level=level + 1, residue=residue, modulus=child_modulus,
                                 value=value, leaves_below=deeper_leaves, parent=node)
                node.children.append(child)
                next_frontier.append(child)
            node.hidden_count = len(free) - len(node.children)
            node.hidden_leaves = node.hidden_count * deeper_leaves
        nodes.extend(next_frontier)
        frontier = next_frontier
    slot_count = _assign_slots(root)
    return TreeView(a=a, root=root, nodes=nodes, level_primes=level_primes, slot_count=slot_count)


def _assign_slots(root):
    """Terminal nodes get consecutive slots in depth-first order; an inner node sits
    at the mean slot of its children. Returns the slot count."""
    next_slot = 0
    stack = [(root, False)]
    while stack:
        node, expanded = stack.pop()
        if not node.children:
            node.slot = float(next_slot)
            node.leaf_span = 1
            next_slot += 1
        elif expanded:
            node.slot = sum(c.slot for c in node.children) / len(node.children)
            node.leaf_span = sum(c.leaf_span for c in node.children)
        else:
            stack.append((node, True))
            for child in reversed(node.children):
                stack.append((child, False))
    return next_slot


def parent_lane(residue, modulus, depth, all_primes):
    """The lane one level above `residue` mod `modulus` (depth `depth`), as
    (residue, modulus, depth); None for the top root."""
    if depth == 0:
        return None
    parent_modulus = modulus // all_primes[depth - 1]
    return residue % parent_modulus, parent_modulus, depth - 1


def column_lane(root_residue, root_modulus, p):
    """The multiples of p inside lane root_residue mod root_modulus, as (residue,
    modulus*p). p does not divide root_modulus (the view primes come after it)."""
    modulus = root_modulus * p
    for k in range(p):
        candidate = root_residue + k * root_modulus
        if candidate % p == 0:
            return candidate % modulus, modulus
    raise ValueError(f"{p} divides the lane modulus {root_modulus}")


def lane_values_in_window(a, h, residue, modulus):
    """(first value, count) of the lane's values inside [a, a + h)."""
    first = lane_first_value(a, residue, modulus)
    if first >= a + h:
        return first, 0
    return first, (a + h - 1 - first) // modulus + 1


def prime_divisor_flags(first, step, count, primes):
    """(count, len(primes)) bool array: entry [t, j] is whether primes[j] divides
    first + t*step. Exact for arbitrarily large `first`/`step` (only residues mod each
    prime reach numpy)."""
    t = np.arange(count, dtype=np.int64)
    flags = np.empty((count, len(primes)), dtype=bool)
    for j, q in enumerate(primes):
        flags[:, j] = ((first % q) + t * (step % q)) % q == 0
    return flags


def stripe_primes(value, primes):
    """The distinct primes of `primes` dividing value, ascending (exponents ignored)."""
    return [q for q in sorted(primes) if value % q == 0]


def is_hollow(value, p, primes):
    """True when a multiple of p on p's column was already caught by a smaller prime
    (its least prime factor among `primes` is below p)."""
    return any(value % q == 0 for q in primes if q < p)


def exact_density(primes):
    """prod(1 - 1/p): the share of integers coprime to every prime in `primes`."""
    density = Fraction(1)
    for p in primes:
        density *= Fraction(p - 1, p)
    return density


def _lane_multiples_residue(residue, modulus, d):
    """The values of lane residue mod modulus divisible by d (d coprime to modulus),
    as a residue mod modulus*d."""
    if d == 1:
        return residue % modulus
    k = (-residue * pow(modulus, -1, d)) % d
    return (residue + k * modulus) % (modulus * d)


def lane_coprime_count(a, h, residue, modulus, primes):
    """How many values of lane residue mod modulus inside [a, a + h) are coprime to
    every prime in `primes` (none of which divides modulus), by inclusion-exclusion
    over the squarefree divisors."""
    if h <= 0:
        return 0
    total = 0
    primes = list(primes)
    for size in range(len(primes) + 1):
        sign = -1 if size % 2 else 1
        for combo in combinations(primes, size):
            d = _product(combo)
            sub_residue = _lane_multiples_residue(residue, modulus, d)
            total += sign * lane_values_in_window(a, h, sub_residue, modulus * d)[1]
    return total


def coprime_count(a, b, primes):
    """How many integers in [a, b) are coprime to every prime in `primes`."""
    return lane_coprime_count(a, b - a, 0, 1, primes)


def line_point_count(h, root_modulus, level_primes, leaf_count):
    """Upper bound on the markers the vertical lines carry in a window of height h:
    every prime column plus every drawn terminal lane."""
    total = 0
    for p in level_primes:
        total += h // (root_modulus * p) + 1
    leaf_modulus = root_modulus * _product(level_primes)
    total += leaf_count * (h // leaf_modulus + 1)
    return total


def effective_window(h_requested, root_modulus, level_primes, leaf_count, max_points):
    """The requested window height, shrunk (never below 1) until line_point_count
    fits max_points."""
    h = h_requested
    while h > 1 and line_point_count(h, root_modulus, level_primes, leaf_count) > max_points:
        count = line_point_count(h, root_modulus, level_primes, leaf_count)
        h = max(1, min(h - 1, h * max_points // count))
    return h
