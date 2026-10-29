"""Vectorized PGS2 writer: encodes a whole window's gap stream with NumPy instead of one
Python call per prime. Output is byte-identical to write_prime_window() in the scanner
modules (format writeup: prime_sieve_v1.py).

A window is given as its lower bound `lo` (Python int, may exceed 2**64) plus the ascending
prime offsets p - lo as an int64 array, so no per-prime Python int is ever built.
"""
import time

import numpy as np

PGS_MAGIC = b"PGS2"

_SEVEN = np.uint64(7)
_LOW7 = np.uint64(0x7F)


def encode_varints(values):
    """Concatenated LEB128 unsigned varints of a uint64 array: 7 data bits per byte,
    MSB = continuation flag."""
    v = np.asarray(values, dtype=np.uint64)
    if v.size == 0:
        return b""
    n_bytes = np.ones(v.size, dtype=np.int64)
    rest = v >> _SEVEN
    while True:
        more = rest != 0
        if not more.any():
            break
        n_bytes += more
        rest >>= _SEVEN
    starts = np.cumsum(n_bytes) - n_bytes
    out = np.empty(int(n_bytes.sum()), dtype=np.uint8)
    for j in range(int(n_bytes.max())):
        sel = np.nonzero(n_bytes > j)[0]
        byte = ((v[sel] >> np.uint64(7 * j)) & _LOW7).astype(np.uint8)
        byte[n_bytes[sel] > j + 1] |= 0x80
        out[starts[sel] + j] = byte
    return out.tobytes()


def pgs2_header(base, count, generated_at):
    """PGS2 header: magic, 1-byte base length L, L big-endian base bytes, 4-byte count,
    4-byte generated_at. An empty window stores L = 0 and no base."""
    if count == 0:
        return PGS_MAGIC + bytes([0]) + (0).to_bytes(4, "big") + int(generated_at).to_bytes(4, "big")
    base_bytes = base.to_bytes(max(1, (base.bit_length() + 7) // 8), "big")
    if len(base_bytes) > 255:
        raise ValueError(f"base prime too large for 1-byte length prefix: {base}")
    return (PGS_MAGIC + bytes([len(base_bytes)]) + base_bytes + count.to_bytes(4, "big")
            + int(generated_at).to_bytes(4, "big"))


def write_prime_window_offsets(path, lo, offsets, generated_at=None):
    """Writes the primes lo + offsets (offsets: ascending int64 array) to `path` in PGS2
    format with one write call. `generated_at` defaults to now (unix seconds)."""
    if generated_at is None:
        generated_at = int(time.time())
    count = len(offsets)
    base = lo + int(offsets[0]) if count else 0
    gaps = np.diff(offsets).astype(np.uint64) if count > 1 else np.empty(0, dtype=np.uint64)
    with open(path, "wb") as f:
        f.write(pgs2_header(base, count, generated_at) + encode_varints(gaps))
