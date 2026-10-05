"""
assembly_hud.py -- the assembly animation's HUD lines: the step, its prime q and phase,
the period and lanes before -> after, the removed class (per copy, when enumerated and
short), the next prime read off the new level with its square, and the density L / M.
"""

from primeatlas.visualization.assembly.assembly_layout import PHASES
from primeatlas.visualization.tree.tree_hud import count_text

# The per-copy removals are listed for at most this many copies.
_MAX_LISTED_COPIES = 23


def assembly_hud_lines(steps, step_index, phase, base, detail_step=None):
    st = steps[step_index]
    q = st.q
    lines = [
        f"Step {step_index + 1}/{len(steps)}: q = {q:,}, phase: {PHASES[phase]}",
        f"Period {count_text(st.period_before)} -> {count_text(st.period_after)}  ({q:,} copies)",
        f"Lanes {count_text(st.lanes_before)} -> {count_text(st.lanes_after)} = "
        f"{count_text(st.lanes_before)} x ({q:,}-1)",
        f"Removed: the multiples of {q:,}, one of the {q:,} copies of each lane",
    ]
    if st.removed_per_copy is not None and q <= _MAX_LISTED_COPIES:
        lines.append("Removed per copy: " + ", ".join(str(d) for d in st.removed_per_copy))
    lines.append(f"Next prime: {st.next_prime:,} (smallest survivor > 1); "
                 f"every survivor < {st.square:,} is prime")
    lines.append(f"Density: {100.0 * st.lanes_after / st.period_after:.4f}% of the integers")
    if base:
        lines.append(f"Values from {base:,}")
    if detail_step is not None:
        lines.append(f"Grid: step {detail_step + 1} (q = {steps[detail_step].q:,}); Backspace returns")
    return lines
