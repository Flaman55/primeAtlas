"""
sphere_hud.py -- the HUD lines of the sphere's rings mode (under the shared header).
"""

# Ring factors listed in the node line at most.
_HUD_FACTORS = 24


def sphere_hud_lines(n, moving, factors, prime_state, rings, active, prev_prime, next_prime, has_storage):
    """`factors`: the ring primes dividing N (whole N only); `prime_state`: N's primality
    from the storage (True/False, None = unknown); `prev_prime`/`next_prime`: the stored
    neighbors of N (None when unknown)."""
    lines = []
    ring_max = rings[-1]
    if moving:
        lines.append(f"N {n:,} -> {n + 1:,}: the points move along their rings")
    elif prime_state is True:
        own = " -- its own ring is at the node" if n <= ring_max else ""
        lines.append(f"{n:,} is prime: a new prime{own}")
    else:
        proper = [p for p in factors if p < n]
        if proper:
            shown = " · ".join(f"{p:,}" for p in proper[:_HUD_FACTORS])
            extra = len(proper) - _HUD_FACTORS
            lines.append(f"Node: {shown}" + (f" (+{extra} more)" if extra > 0 else ""))
        elif prime_state is False:
            lines.append(f"No ring divides N: its smallest factor is > {ring_max:,}")
        if prime_state is None and not proper:
            reason = "N is outside the storage" if has_storage else "no storage loaded"
            lines.append(f"Primality unknown: {reason}")
    lines.append(f"Rings: 2 .. {ring_max:,} ({len(rings):,}), taking part: {active:,}")
    if prev_prime is not None or next_prime is not None:
        prev_text = f"{prev_prime:,}" if prev_prime is not None else "-"
        next_text = f"{next_prime:,}" if next_prime is not None else "-"
        lines.append(f"Stored primes around N: {prev_text} | {next_text}")
    return lines
