"""prime_sieve/wheel30_writer.py: the v6 write phase (native window encoder, parallel writer)
against the NumPy path it replaces.

encode_window() must return exactly pgs2_header() + encode_varints() of the gaps of
wheel30_layout.window_prime_offsets() for any buffer contents (random bytes, all marked = an
empty window, none marked), for windows that cut bytes at both ends, lie inside one byte,
hold one number, start at 0..7 (2, 3, 5 and 1 handled by the NumPy fallback), and lie above
2^64. write_windows() writes every window to its path (creating each shard folder), with the
same bytes as encode_window(), returns the total bytes and prime count, prints progress
lines, and gives the same files with 1 and with several threads. WSL only (native library):
    python3 unitTests/test_wheel30_writer.py
"""
import os
import random
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "prime_sieve"))


def check(value, message):
    print(("ok:   " if value else "FAIL: ") + message)
    return bool(value)


def reference(buf, base, lo, hi, generated_at):
    import numpy as np
    import wheel30_layout as wl
    from pgs2_vector import encode_varints, pgs2_header
    offsets = wl.window_prime_offsets(buf, base, lo, hi)
    count = len(offsets)
    first = lo + int(offsets[0]) if count else 0
    gaps = np.diff(offsets).astype(np.uint64) if count > 1 else np.empty(0, dtype=np.uint64)
    return pgs2_header(first, count, generated_at) + encode_varints(gaps)


def check_encode():
    import numpy as np
    import wheel30_layout as wl
    import wheel30_writer as ww
    rng = random.Random(7)
    passed = True
    cases = []
    for lo0 in (0, 1, 31, 10 ** 12 + 7, 2 ** 64 + 11, 10 ** 29 + 3):
        hi0 = lo0 + 30 * 400 + 17
        base = wl.buffer_base(lo0)
        n = wl.buffer_bytes(lo0, hi0)
        for kind in ("random", "all marked", "none marked"):
            if kind == "random":
                buf = np.frombuffer(bytes(rng.getrandbits(8) for _ in range(n)), dtype=np.uint8)
            else:
                buf = np.full(n, 0xFF if kind == "all marked" else 0, dtype=np.uint8)
            windows = [(lo0, hi0), (lo0, lo0 + 1), (lo0 + 3, lo0 + 29), (lo0 + 29, lo0 + 61),
                       (lo0 + 100, lo0 + 100 + 30 * 50), (lo0 + 7, lo0 + 8)]
            windows += [(a, a + rng.randrange(1, 3000)) for a in
                        (lo0 + rng.randrange(0, 9000) for _ in range(20))]
            cases += [(kind, buf, base, a, min(b, hi0)) for a, b in windows]
    bad = []
    for kind, buf, base, a, b in cases:
        want = reference(buf, base, a, b, 1234)
        got, count = ww.encode_window(buf, base, a, b, 1234)
        if got != want or count != len(wl.window_prime_offsets(buf, base, a, b)):
            bad.append((kind, a, b))
    passed &= check(not bad, f"encode_window equals the NumPy path on {len(cases)} windows "
                             f"(mismatches: {bad[:3]})")
    return passed


def check_write():
    import numpy as np
    import wheel30_layout as wl
    import wheel30_writer as ww
    rng = random.Random(11)
    lo0 = 10 ** 19 + 30 * 1000 + 13
    width = 30 * 37 + 1
    n_windows = 60
    base = wl.buffer_base(lo0)
    n = wl.buffer_bytes(lo0, lo0 + width * n_windows)
    buf = np.frombuffer(bytes(rng.getrandbits(8) | 0x11 for _ in range(n)), dtype=np.uint8)
    passed = True
    trees = []
    for threads in (1, 6):
        root = tempfile.mkdtemp(prefix="wheel30_writer_test_")
        jobs = [(os.path.join(root, f"shard_{i // 25:05d}", f"w{i}.bin"),
                 lo0 + i * width, lo0 + (i + 1) * width) for i in range(n_windows)]
        lines = []
        total_bytes, total_primes = ww.write_windows(
            buf, base, jobs, generated_at=99, n_threads=threads, progress=lines.append)
        files = {}
        for path, a, b in jobs:
            with open(path, "rb") as f:
                files[os.path.relpath(path, root)] = f.read()
        want = {os.path.relpath(p, root): ww.encode_window(buf, base, a, b, 99)[0]
                for p, a, b in jobs}
        passed &= check(files == want, f"{threads} thread(s): every window written as encoded")
        passed &= check(total_bytes == sum(len(v) for v in files.values()),
                        f"{threads} thread(s): total bytes {total_bytes}")
        passed &= check(total_primes == sum(len(wl.window_prime_offsets(buf, base, a, b))
                                            for _p, a, b in jobs),
                        f"{threads} thread(s): total primes {total_primes}")
        passed &= check(lines and all(line.startswith("[*] Writing windows:") for line in lines)
                        and f"{n_windows}/{n_windows}" in lines[-1],
                        f"{threads} thread(s): progress lines ({lines[-1] if lines else None})")
        trees.append(files)
        shutil.rmtree(root, ignore_errors=True)
    passed &= check(trees[0] == trees[1], "1 and 6 threads write the same files")
    return passed


def main():
    if sys.platform == "win32":
        print("SKIPPED (WSL-only): needs prime_sieve_engine_v6.so")
        return 0
    passed = check_encode()
    passed &= check_write()
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
