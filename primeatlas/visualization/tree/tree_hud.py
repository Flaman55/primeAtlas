"""
tree_hud.py -- the prime tree's HUD lines: the start prime, the axis, and one line per
level (drawn copies against the full tree's copies, the drawn and hidden branches per
copy, the gap to the next level and -- for a tree starting at 2 -- the share
prod(1-1/p) of the integers no level prime up to p divides).
"""

from primeatlas.core import number_format
from primeatlas.visualization.tree.tree_layout import AXIS_REAL, chain_density


# Counts with more digits than this are shown as d.dd e<exponent>.
_MAX_PLAIN_DIGITS = 12


def count_text(count):
    digits = str(count)
    if len(digits) <= _MAX_PLAIN_DIGITS:
        return number_format.whole(count)
    return f"{digits[0]}.{digits[1:3]}e{len(digits) - 1}"


def tree_hud_lines(tree, n, layer_lines=()):
    """HUD lines for one built tree; `n` is the session's N the start was rounded from."""
    start = tree.start
    axis = tree.axis
    if axis.kind == AXIS_REAL:
        axis_line = f"Axis: real n in [{number_format.whole(axis.bottom)}, {number_format.whole(axis.top)}]"
        if tree.capped:
            axis_line += "  (shrunk to the max points cap)"
    else:
        axis_line = f"Axis: multiples p..{axis.multiples}p of each level, {len(axis.values)} values"
    lines = [
        f"Start: p = {number_format.whole(start)}" + ("" if n == start else f"  (largest prime <= {number_format.whole(n)})"),
        axis_line,
    ]
    for level in tree.levels:
        copies = tree.nodes_at(level.index)
        sample = copies[0]
        line = f"p={number_format.whole(level.p)}: {number_format.whole(len(copies))} of {count_text(level.total_copies)} copies, {len(sample.children)} drawn"
        if sample.hidden:
            line += f" +{number_format.whole(sample.hidden)} hidden"
        if level.index + 1 < len(tree.levels):
            line += f", gap {number_format.whole(tree.levels[level.index + 1].p - level.p)}"
        if start == 2:
            line += f", prod(1-1/p) {number_format.decimal(100.0 * chain_density(tree.primes[:level.index + 1]), 3)}%"
        lines.append(line)
    if tree.levels_cut:
        lines.append("Deeper levels cut by the max nodes cap")
    lines.extend(layer_lines)
    return lines
