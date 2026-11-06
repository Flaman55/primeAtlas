"""Write phase of engine v6: turns the finished wheel-30 buffer into PGS2 window files.

encode_window() builds one window's file bytes. The gap stream comes from the native
wheel_window_gaps() (prime_sieve_engine_v6.c), one pass over the window's bytes; a window
starting below 7 (2, 3 and 5 have no bit, 1 is never marked) goes through the NumPy path of
wheel30_layout.py and pgs2_vector.py. Both give the same bytes as pgs2_vector's writer.

write_windows() writes many windows through parallel_window_writer.write_jobs(), the
thread pool v5.2 shares: the native call and the file write both release the GIL, so encoding
and the per-file latency of WSL's /mnt drives overlap across threads.
"""
import ctypes
import threading

import numpy as np

import engine_v6_lib
import parallel_window_writer
import wheel30_layout
from parallel_window_writer import PROGRESS_PREFIX  # noqa: F401 -- part of this module's API
from pgs2_vector import encode_varints, pgs2_header

_local = threading.local()


def _out_buffer(size):
    buf = getattr(_local, "out", None)
    if buf is None or len(buf) < size:
        buf = _local.out = ctypes.create_string_buffer(size)
    return buf


def _numpy_window(buf, base, lo, hi, generated_at):
    offsets = wheel30_layout.window_prime_offsets(buf, base, lo, hi)
    count = len(offsets)
    first = lo + int(offsets[0]) if count else 0
    gaps = np.diff(offsets).astype(np.uint64) if count > 1 else np.empty(0, dtype=np.uint64)
    return pgs2_header(first, count, generated_at) + encode_varints(gaps), count


def encode_window(buf, base, lo, hi, generated_at):
    """(PGS2 file bytes, prime count) of the window [lo, hi) of `buf` (a uint8 array whose
    byte 0 starts at `base`)."""
    if lo < 7 or hi <= lo:
        return _numpy_window(buf, base, lo, hi, generated_at)
    lib = engine_v6_lib.load_lib()
    b0 = (lo - base) // wheel30_layout.WHEEL
    b1 = (hi - 1 - base) // wheel30_layout.WHEEL + 1
    n_bytes = b1 - b0
    first_rel = base + wheel30_layout.WHEEL * b0 - lo
    count = ctypes.c_uint64()
    first = ctypes.c_uint64()
    address = buf.ctypes.data + b0
    # Two bytes per gap cover gaps below 2^14; a window with larger gaps retries with room
    # for the longest varint of its span.
    for per_gap in (2, ((hi - lo).bit_length() + 6) // 7):
        cap = 8 * n_bytes * per_gap + 16
        out = _out_buffer(cap)
        written = lib.wheel_window_gaps(address, n_bytes, first_rel, hi - lo, out, cap,
                                        ctypes.byref(count), ctypes.byref(first))
        if written >= 0:
            break
    n = count.value
    header = pgs2_header(lo + first.value if n else 0, n, generated_at)
    return header + out.raw[:written], n


def write_windows(buf, base, jobs, generated_at, n_threads, progress=print):
    """Writes every (path, lo, hi) of `jobs` as a PGS2 file with `n_threads` threads;
    returns (bytes written, primes written)."""
    return parallel_window_writer.write_jobs(
        jobs, lambda lo, hi: encode_window(buf, base, lo, hi, generated_at), n_threads,
        progress=progress)
