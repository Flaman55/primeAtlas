"""
tree_hud.py -- the sieve-lane tree's HUD lines: the view root, the window, the scale
caps, and one density line per level (exact prod(1-1/p) against the share actually
found in the window).
"""

from primeatlas.visualization.tree.tree_layout import exact_density, lane_coprime_count, lane_values_in_window

# Inclusion-exclusion over the view primes costs 2^levels terms per level; past this
# many levels the in-window share is not computed.
_MAX_COUNTED_LEVELS = 16


def _percent(fraction):
    return f"{100.0 * float(fraction):.3f}%"


def tree_hud_lines(view, h, h_requested, all_primes, levels_capped, branches, layer_lines=()):
    """HUD lines for one built view over the window [view.a, view.a + h)."""
    root = view.root
    a = view.a
    ancestors = all_primes[:root.depth]
    lines = [
        f"Root lane: {root.residue:,} mod {root.modulus:,} (depth {root.depth})"
        + (f", coprime to {', '.join(map(str, ancestors))}" if ancestors else ", every integer"),
        f"Window: n in [{a:,}, {a + h:,})" + ("  (shrunk to the max points cap)" if h < h_requested else ""),
        f"Branches per node: {branches}   levels: {len(view.level_primes)}"
        + ("  (cut to the max nodes cap)" if levels_capped else "")
        + f"   terminal lanes if expanded: {root.leaves_below:,}",
    ]
    lane_total = lane_values_in_window(a, h, root.residue, root.modulus)[1]
    counted = []
    for p in view.level_primes:
        counted.append(p)
        in_lane = exact_density(counted)
        overall = exact_density(ancestors + counted)
        line = f"p={p}: prod(1-1/p) = {_percent(in_lane)} of the root lane"
        if ancestors:
            line += f" ({_percent(overall)} of all n)"
        if lane_total and len(counted) <= _MAX_COUNTED_LEVELS:
            found = lane_coprime_count(a, h, root.residue, root.modulus, counted)
            line += f", window {_percent(found / lane_total)}"
        lines.append(line)
    lines.extend(layer_lines)
    return lines
