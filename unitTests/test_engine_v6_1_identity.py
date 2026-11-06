"""WSL test: prime_sieve_v6_1.py produces exactly what prime_sieve_v6.py (v6.0) produces.

Two levels:
  - whole runs: both scanners on the cases of test_engine_v6_identity (low floors split
    across floor boundaries, top of a floor, odd widths, count-only, small segments and
    buckets), each into its own empty portal, every output file compared byte for byte
    (PGS2 timestamp zeroed) and the handoff's result fields;
  - engine calls: sieve_wheel_segmented() and sieve_wheel_bucketed() of
    prime_sieve_engine_v6_1.so against v6.0's .so on the same inputs, the whole output
    buffer compared bit for bit. The inputs aim at what v6.1 changes: the unrolled wheel
    loop (a prime's marks cut by a segment end mid wheel turn, primes just below and above
    the unroll limit, segments of one to a few words, slices whose length is not a whole
    byte or word, bit_lo past 0) and the staged bucket writes (buckets that fill mid line,
    many rounds, 1, 3 and 8 threads, one-piece and many-piece prime lists, floor 0 where
    the buffer holds the sieving primes themselves).
A reference whose output differs is caught: BROKEN_CHECK flips one bit of v6.0's output and
expects the comparison to report it, so a comparison that cannot fail does not pass.

Run inside WSL from the repo root:
    python3 unitTests/test_engine_v6_1_identity.py
"""
import ctypes
import math
import os
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_engine_v6_identity as v6_cases  # noqa: E402

SIEVE_DIR = v6_cases.SIEVE_DIR
check = v6_cases.check
U64 = ctypes.c_uint64

REFERENCE, CANDIDATE = "prime_sieve_v6.py", "prime_sieve_v6_1.py"
REFERENCE_SO, CANDIDATE_SO = "prime_sieve_engine_v6.so", "prime_sieve_engine_v6_1.so"


def compare_runs(tmp, label, floor, idx_lo, idx_hi, window_m, write_files, extra_env=None):
    passed = True
    snaps = []
    for script in (REFERENCE, CANDIDATE):
        if not os.path.exists(os.path.join(SIEVE_DIR, script)):
            return check(False, f"{label}: {script} exists")
        portal = os.path.join(tmp, f"{label.replace(' ', '_')}_{script}")
        os.makedirs(portal)
        rc, tail = v6_cases.run_scanner(script, portal, floor, idx_lo, idx_hi, window_m,
                                        write_files, extra_env or {})
        if rc != 0:
            print(tail)
        passed &= check(rc == 0, f"{label}: {script} exits 0")
        snaps.append(v6_cases.snapshot(portal))
    (ref_files, ref_metrics), (new_files, new_metrics) = snaps
    if write_files:
        passed &= check(len(ref_files) > 0, f"{label}: v6.0 wrote output files")
    passed &= check(sorted(new_files) == sorted(ref_files),
                    f"{label}: same file set ({len(ref_files)} files)")
    differing = [p for p in ref_files if new_files.get(p) != ref_files[p]]
    if differing:
        print(f"       differing files: {differing[:5]}")
    passed &= check(not differing, f"{label}: every file byte-identical")
    passed &= check(ref_metrics.get("total_primes_found") is not None
                    and new_metrics == ref_metrics,
                    f"{label}: handoff result fields equal "
                    f"(total_primes_found={ref_metrics.get('total_primes_found')})")
    return passed


def load_engines():
    libs = []
    for name in (REFERENCE_SO, CANDIDATE_SO):
        lib = ctypes.CDLL(os.path.join(SIEVE_DIR, name))
        lib.sieve_wheel_segmented.argtypes = [U64] * 6 + [ctypes.POINTER(U64)]
        lib.sieve_wheel_segmented.restype = ctypes.c_int
        lib.sieve_wheel_bucketed.argtypes = [ctypes.POINTER(U64), ctypes.POINTER(U64)] + \
            [U64] * 7 + [ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(U64)]
        lib.sieve_wheel_bucketed.restype = ctypes.c_int
        libs.append(lib)
    return libs


def segmented(lib, stop, base, bit_lo, n_bits, segment_words):
    words = (U64 * ((bit_lo + n_bits + 63) // 64))()
    rc = lib.sieve_wheel_segmented(stop, base >> 64, base & (2 ** 64 - 1), bit_lo,
                                   bit_lo + n_bits, segment_words, words)
    return rc, bytes(words)


def bucketed(lib, pieces, base, n_bits, region_bits, threads, bucket_bytes):
    buf = (ctypes.c_ubyte * ((n_bits + 7) // 8 + 8))()
    lo = (U64 * len(pieces))(*[a for a, _ in pieces])
    hi = (U64 * len(pieces))(*[b for _, b in pieces])
    done = (U64 * 1)(0)
    rc = lib.sieve_wheel_bucketed(lo, hi, len(pieces), base >> 64, base & (2 ** 64 - 1), n_bits,
                                  region_bits, threads, bucket_bytes, buf, done)
    return rc, bytes(buf)


def floor_base(rng, floor):
    """A multiple of 30 at the start of `floor` plus a random step (0 for floor 0)."""
    if floor == 0:
        return 0
    return (10 ** floor // 30) * 30 + 30 * rng.randrange(10 ** 6)


def segmented_cases(rng):
    """(stop, base, bit_lo, n_bits, segment_words): the unroll limit is a segment's numbers / 32
    (segment_words * 64 / 8 * 30 / 32), so the stops sit below, at and above it."""
    cases = []
    for floor in (0, 5, 13, 19, 22, 25, 29):
        for segment_words in (1, 3, 16, 1024, 32768):
            limit = segment_words * 64 // 8 * 30 // 32
            for stop in (7, 20, limit, limit + 1, 2 * limit + 13, 300_000):
                sizes = [1, 63, 64 * 3 + 5, 8192 * 8 * 3 + 17]
                if segment_words >= 1024:
                    sizes.append(8192 * 8 * 41)   # many segments of tiny ones would be slow
                n_bits = rng.choice(sizes)
                bit_lo = 64 * rng.randrange(0, 4)
                cases.append((max(7, stop), floor_base(rng, floor), bit_lo, n_bits,
                              segment_words))
    return cases


def bucketed_cases(rng):
    """(pieces, base, n_bits, region_bits, threads, bucket_bytes). Bucket sizes are chosen so
    the per-region slots run from the 16-slot minimum (a round ends after one staging line)
    to all hits in one round; primes start at 100,000 on the long buffers, as in production,
    where the small primes go to the segmented path."""
    cases = []
    for floor in (0, 10, 13, 16, 18):
        for n_bits in (1000, 8192 * 8 * 5 + 3, 8192 * 8 * 200, 8192 * 8 * 1500):
            base = floor_base(rng, floor)
            limit = math.isqrt(base + 30 * ((n_bits + 7) // 8)) + 1
            lo = 7 if n_bits <= 8192 * 8 * 5 + 3 else min(100_000, limit - 2)
            if lo >= limit - 1:
                continue
            for threads, bucket_bytes in ((1, 1 << 16), (3, 1 << 20), (8, 1 << 28)):
                cuts = sorted({lo, limit} | {rng.randrange(lo, limit)
                                             for _ in range(rng.choice([0, 3, 17]))})
                region_bits = rng.choice([8192 * 8, 1 << 20, 1 << 23])
                cases.append((list(zip(cuts, cuts[1:])), base, n_bits, region_bits, threads,
                              bucket_bytes))
    return cases


def compare_engine_calls(ref, new):
    rng = random.Random(61)
    passed = True
    for name, cases, call in (("sieve_wheel_segmented", segmented_cases(rng), segmented),
                              ("sieve_wheel_bucketed", bucketed_cases(rng), bucketed)):
        differing = []
        for case in cases:
            want, got = call(ref, *case), call(new, *case)
            if want[0] != 0 or want != got:
                differing.append(case if name != "sieve_wheel_bucketed" else case[1:])
        if differing:
            print(f"       first differing {name} inputs: {differing[:3]}")
        passed &= check(not differing, f"{name}: {len(cases)} inputs bit-identical to v6.0")
    return passed


def broken_check(ref):
    """The inputs see a wrong engine: v6.0 with one sieving prime fewer (stop 1009 instead of
    1010, so 1009 marks nothing) differs from v6.0 itself on a buffer 1009 hits."""
    args = (10 ** 19 // 30 * 30, 0, 8192 * 8 * 3 + 17, 1024)
    return check(segmented(ref, 1009, *args) != segmented(ref, 1010, *args),
                 "an engine that skips one prime is reported as differing")


def main():
    passed = True
    for name in (REFERENCE_SO, CANDIDATE_SO):
        passed &= check(os.path.exists(os.path.join(SIEVE_DIR, name)), f"{name} is built")
    if passed:
        ref, new = load_engines()
        passed &= broken_check(ref)
        passed &= compare_engine_calls(ref, new)
    tmp = tempfile.mkdtemp(prefix="engine_v6_1_identity_")
    try:
        for case in v6_cases.CASES:
            passed &= compare_runs(tmp, *case)
        for case in v6_cases.SMALL_SEGMENT_CASES:
            passed &= compare_runs(tmp, *case, extra_env=v6_cases.SMALL_SEGMENT_ENV)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    import engine_v6_lib
    from _native_skip import exit_if_skipped
    exit_if_skipped([engine_v6_lib.load_lib])
    raise SystemExit(main())
