"""Wheel-30 buffer layout of engine v6 (prime_sieve_engine_v6.c), and the window unpacking
prime_sieve_v6.py does on it.

Byte b of the buffer covers the 30 numbers [base + 30*b, base + 30*b + 30); its bit j
(bitorder little) stands for base + 30*b + RESIDUES[j], the eight residues coprime to 30.
base is the combined range's start rounded down to a multiple of 30. A set bit means
composite. That is 8 bits per 30 numbers, against 15 for an odd-only buffer, so the same
memory holds a run 1.875 times as long. 2, 3 and 5 have no bit: a window containing them
gets them added here; 1 has a bit that is never set and is dropped here.
"""
import numpy as np

WHEEL = 30
RESIDUES = (1, 7, 11, 13, 17, 19, 23, 29)
SMALL_PRIMES = (2, 3, 5)
_RESIDUES = np.array(RESIDUES, dtype=np.int64)


def buffer_base(combined_lo):
    """First number of byte 0: combined_lo rounded down to a multiple of WHEEL."""
    return combined_lo - combined_lo % WHEEL


def buffer_bytes(combined_lo, combined_hi):
    """Bytes covering [combined_lo, combined_hi) (0 for an empty range)."""
    if combined_hi <= combined_lo:
        return 0
    return (combined_hi - buffer_base(combined_lo) + WHEEL - 1) // WHEEL


def _byte_span(base, lo, hi):
    """(b0, b1): the bytes [b0, b1) covering [lo, hi)."""
    return (lo - base) // WHEEL, (hi - 1 - base) // WHEEL + 1


def _edge_unmarked(buf, base, lo, hi, b):
    """rel offsets n - lo of the unmarked numbers of byte b that lie in [lo, hi), except 1."""
    byte = int(buf[b])
    first = base + WHEEL * b
    return [first + r - lo for j, r in enumerate(RESIDUES)
            if not (byte >> j) & 1 and lo <= first + r < hi and first + r != 1]


def window_prime_offsets(buf, base, lo, hi):
    """Ascending primes of [lo, hi) as an int64 array of p - lo. Only the unmarked bits of
    the bytes covering [lo, hi) are turned into numbers; the two edge bytes are filtered to
    the window."""
    small = [p - lo for p in SMALL_PRIMES if lo <= p < hi]
    if hi <= lo:
        return np.empty(0, dtype=np.int64)
    b0, b1 = _byte_span(base, lo, hi)
    parts = [np.array(small, dtype=np.int64), np.array(_edge_unmarked(buf, base, lo, hi, b0),
                                                       dtype=np.int64)]
    if b1 - b0 > 2:
        bits = np.unpackbits(buf[b0 + 1:b1 - 1], bitorder='little')
        free = np.flatnonzero(bits == 0)
        parts.append((base - lo + WHEEL * (b0 + 1)) + WHEEL * (free >> 3).astype(np.int64)
                     + _RESIDUES[free & 7])
    if b1 - b0 > 1:
        parts.append(np.array(_edge_unmarked(buf, base, lo, hi, b1 - 1), dtype=np.int64))
    return np.concatenate(parts)


def window_prime_count(buf, base, lo, hi):
    """len(window_prime_offsets(...)) without building the array: unmarked bits of the inner
    bytes by popcount, the two edge bytes bit by bit."""
    count = sum(1 for p in SMALL_PRIMES if lo <= p < hi)
    if hi <= lo:
        return count
    b0, b1 = _byte_span(base, lo, hi)
    count += len(_edge_unmarked(buf, base, lo, hi, b0))
    if b1 - b0 > 2:
        inner = buf[b0 + 1:b1 - 1]
        count += 8 * len(inner) - int(np.bitwise_count(inner).sum(dtype=np.int64))
    if b1 - b0 > 1:
        count += len(_edge_unmarked(buf, base, lo, hi, b1 - 1))
    return count
