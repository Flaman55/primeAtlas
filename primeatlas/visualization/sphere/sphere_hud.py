"""
sphere_hud.py -- the HUD lines of the sphere's rings mode (under the shared header).
"""

from primeatlas.core import number_format

# Ring factors listed in the node line at most.
_HUD_FACTORS = 24


def sphere_hud_lines(n, moving, factors, prime_state, rings, active, prev_prime, next_prime, has_storage,
                     target=None):
    """`factors`: the ring primes dividing N (whole N only); `prime_state`: N's primality
    from the storage (True/False, None = unknown); `prev_prime`/`next_prime`: the stored
    neighbors of N (None when unknown); `target`: where the current glide ends (N + 1 when
    None)."""
    lines = []
    ring_max = rings[-1]
    if moving:
        end = n + 1 if target is None else target
        lines.append(f"N {number_format.whole(n)} -> {number_format.whole(end)}: the points move along their rings")
    elif prime_state is True:
        own = " -- its own ring is at the node" if n <= ring_max else ""
        lines.append(f"{number_format.whole(n)} is prime: a new prime{own}")
    else:
        proper = [p for p in factors if p < n]
        if proper:
            shown = " · ".join(number_format.whole(p) for p in proper[:_HUD_FACTORS])
            extra = len(proper) - _HUD_FACTORS
            lines.append(f"Node: {shown}" + (f" (+{extra} more)" if extra > 0 else ""))
        elif prime_state is False:
            lines.append(f"No ring divides N: its smallest factor is > {number_format.whole(ring_max)}")
        if prime_state is None and not proper:
            reason = "N is outside the storage" if has_storage else "no storage loaded"
            lines.append(f"Primality unknown: {reason}")
    lines.append(f"Rings: 2 .. {number_format.whole(ring_max)} ({number_format.whole(len(rings))}), taking part: {number_format.whole(active)}")
    if prev_prime is not None or next_prime is not None:
        prev_text = number_format.whole(prev_prime) if prev_prime is not None else "-"
        next_text = number_format.whole(next_prime) if next_prime is not None else "-"
        lines.append(f"Stored primes around N: {prev_text} | {next_text}")
    return lines
