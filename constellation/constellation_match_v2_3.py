"""
constellation_match_v2_3.py -- vectorized k-tuple pattern matching over one window's
primes (numpy masks per unique offset). No file I/O.
"""
import numpy as np


def match_patterns_vectorized(candidates, local_set, active_patterns):
    """Computes a presence MASK (numpy, vectorized) once per UNIQUE offset used by ANY
    tracked pattern, instead of once per (pattern, candidate, offset) triple. Matching a
    specific pattern is then a bitwise AND of its offsets' precomputed masks.

    candidates      -- Python-int list, from the CURRENT window only (each candidate is
                        used as a pattern's "base" exactly once, in its own window).
    local_set       -- Python-int set: candidates + the peeked head of the next window
                        (possible targets for p+d).
    active_patterns -- catalog entries to check (includes k=2, see file header).

    Returns {(k, id): [[p, p+d2, ..., p+dk], ...]} -- full (absolute) values.

    Computes on LOCAL offsets relative to min(candidates), not absolute values: numpy
    int64 cannot hold magnitudes from floor 19 up.
    """
    if not candidates or not local_set:
        return {}

    base = min(candidates)
    candidates_local = np.fromiter((p - base for p in candidates), dtype=np.int64, count=len(candidates))
    local_sorted = np.fromiter(sorted(v - base for v in local_set), dtype=np.int64, count=len(local_set))

    unique_offsets = sorted(set(d for w in active_patterns for d in w["offsets"]))
    masks = {}
    for d in unique_offsets:
        shifted = candidates_local + d
        idx = np.searchsorted(local_sorted, shifted)
        idx_safe = np.clip(idx, 0, len(local_sorted) - 1)
        masks[d] = local_sorted[idx_safe] == shifted

    results = {}
    for pattern in active_patterns:
        offsets = pattern["offsets"]
        mask = masks[offsets[0]].copy()
        for d in offsets[1:]:
            mask &= masks[d]
        if not mask.any():
            continue
        key = (pattern["k"], pattern["id"])
        for i in np.nonzero(mask)[0]:
            p = candidates[int(i)]  # full-precision value from the original list
            results.setdefault(key, []).append([p + d for d in offsets])
    return results
