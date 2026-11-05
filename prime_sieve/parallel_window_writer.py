"""Thread-pool write phase shared by engines v5.2 and v6: turns (path, lo, hi) jobs into PGS2
window files.

write_jobs() runs encode(lo, hi) -> (file bytes, prime count) and the file write for every job
on `n_threads` threads. On WSL's /mnt drives every file costs about 13 ms of filesystem latency
(drvfs; a fraction of that on ext4); the file write releases the GIL, and so do the native and
NumPy encoders for most of their work, so the threads overlap that latency. Each shard folder is
created once, before the threads start, and the written size comes from the encoded bytes, so a
window costs one open, write and close. Progress lines go to `progress` as the windows complete.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

PROGRESS_PREFIX = "[*] Writing windows:"
_PROGRESS_SECONDS = 2.0


def write_jobs(jobs, encode, n_threads, progress=print):
    """Writes every (path, lo, hi) of `jobs` as the bytes encode(lo, hi) returns, with
    `n_threads` threads; returns (bytes written, primes written). An encode or write error
    propagates."""
    for folder in {os.path.dirname(path) for path, _lo, _hi in jobs}:
        os.makedirs(folder, exist_ok=True)

    def _write(path, lo, hi):
        data, count = encode(lo, hi)
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
