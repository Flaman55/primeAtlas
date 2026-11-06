"""parallel_window_writer writes PGS2 window files with a thread pool (engines v5.2 and v6).

Checks: every job's file holds exactly encode(lo, hi)'s bytes; each shard folder is
created; the returned bytes and primes are the sums over the jobs; more than one thread
encodes at a time when n_threads > 1 (encodes overlap) and one at a time with n_threads=1;
the progress lines start with PROGRESS_PREFIX and the last one reports total/total;
an empty job list writes nothing and returns (0, 0); a failing encode raises instead of
being swallowed. pgs2_vector.encode_prime_window_offsets() gives the bytes
write_prime_window_offsets() writes. Pure Python + NumPy:
    python unitTests/test_parallel_window_writer.py
"""
import os
import shutil
import sys
import tempfile
import threading
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def _jobs(folder, n):
    return [(os.path.join(folder, f"shard_{i % 3:05d}", f"w{i}.bin"), i * 10, i * 10 + 10)
            for i in range(n)]


def check_writes():
    import parallel_window_writer as pw
    passed = True
    folder = tempfile.mkdtemp(prefix="pww_")
    try:
        jobs = _jobs(folder, 12)
        lines = []
        size, primes = pw.write_jobs(jobs, lambda lo, hi: (bytes([lo % 256]) * (hi - lo), lo),
                                     4, progress=lines.append)
        passed &= check(all(open(p, "rb").read() == bytes([lo % 256]) * (hi - lo)
                            for p, lo, hi in jobs), "every file holds its encoded bytes")
        passed &= check(size == 12 * 10 and primes == sum(lo for _p, lo, _h in jobs),
                        f"bytes and primes summed ({size}, {primes})")
        passed &= check(lines and all(ln.startswith(pw.PROGRESS_PREFIX) for ln in lines)
                        and "12/12" in lines[-1], f"progress lines ({lines[-1] if lines else None})")
        passed &= check(pw.write_jobs([], lambda lo, hi: (b"", 0), 4) == (0, 0),
                        "no jobs -> (0, 0)")
        try:
            pw.write_jobs(_jobs(folder, 2), lambda lo, hi: 1 / 0, 2, progress=lambda _l: None)
            passed &= check(False, "a failing encode raises")
        except ZeroDivisionError:
            passed &= check(True, "a failing encode raises")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return passed


def _peak_concurrency(n_threads):
    import parallel_window_writer as pw
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}

    def encode(lo, hi):
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.02)
        with lock:
            state["now"] -= 1
        return b"x", 0

    folder = tempfile.mkdtemp(prefix="pww_threads_")
    try:
        pw.write_jobs(_jobs(folder, 16), encode, n_threads, progress=lambda _l: None)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return state["peak"]


def check_threads():
    passed = check(_peak_concurrency(4) > 1, "four threads encode concurrently")
    passed &= check(_peak_concurrency(1) == 1, "one thread encodes one window at a time")
    return passed


def check_pgs2_bytes():
    import pgs2_vector
    folder = tempfile.mkdtemp(prefix="pww_pgs2_")
    try:
        offsets = np.array([1, 3, 7, 9, 13], dtype=np.int64)
        path = os.path.join(folder, "w.bin")
        pgs2_vector.write_prime_window_offsets(path, 10 ** 12, offsets, generated_at=123)
        data = pgs2_vector.encode_prime_window_offsets(10 ** 12, offsets, generated_at=123)
        passed = check(open(path, "rb").read() == data,
                       "encode_prime_window_offsets = the bytes write_prime_window_offsets writes")
        empty = pgs2_vector.encode_prime_window_offsets(10 ** 12, np.empty(0, np.int64), 5)
        passed &= check(empty == pgs2_vector.pgs2_header(0, 0, 5), "an empty window is its header")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return passed


def main():
    passed = check_writes()
    passed &= check_threads()
    passed &= check_pgs2_bytes()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
