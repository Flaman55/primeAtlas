"""Write phase of engine v6: turns the finished wheel-30 buffer into PGS2 window files.

encode_window() builds one window's file bytes. The gap stream comes from the native
wheel_window_gaps() (prime_sieve_engine_v6.c), one pass over the window's bytes; a window
starting below 7 (2, 3 and 5 have no bit, 1 is never marked) goes through the NumPy path of
wheel30_layout.py and pgs2_vector.py. Both give the same bytes as pgs2_vector's writer.

write_windows() writes many windows with a thread pool: the native call and the file write
both release the GIL, so encoding and the per-file latency of WSL's /mnt drives (about 13 ms
a file on drvfs, against a fraction of that on ext4) overlap across threads. Each shard folder
is created once, before the threads start, and the written size comes from the encoded bytes,
so a window costs one open, write and close. Progress lines go to `progress` as the windows
complete.
"""
import ctypes
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

import engine_v6_lib
import wheel30_layout
from pgs2_vector import encode_varints, pgs2_header

PROGRESS_PREFIX = "[*] Writing windows:"
_PROGRESS_SECONDS = 2.0
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
    for folder in {os.path.dirname(path) for path, _lo, _hi in jobs}:
        os.makedirs(folder, exist_ok=True)

    def _write(path, lo, hi):
        data, count = encode_window(buf, base, lo, hi, generated_at)
        with open(path, "wb") as f:
            f.write(data)
        return len(data), count

    total = len(jobs)
    total_bytes = total_primes = done = 0
    t_start = last = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, n_threads)) as pool:
        futures = [pool.submit(_write, *job) for job in jobs]
        for future in as_completed(futures):
            size, count = future.result()
            total_bytes += size
            total_primes += count
            done += 1
            now = time.perf_counter()
            if done == total or now - last >= _PROGRESS_SECONDS:
                last = now
                progress(f"{PROGRESS_PREFIX} {done}/{total} ({100 * done / total:.1f}%) | "
                         f"time: {now - t_start:.1f}s")
    return total_bytes, total_primes
