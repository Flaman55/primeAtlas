"""WSL test: prime_sieve_v7_0.py produces exactly what prime_sieve_v6_1.py (v6.1) produces.

Two levels:
  - engine calls: sieve_wheel_bucketed() of prime_sieve_engine_v7_0.so with the jump gear on
    against v6.1's .so on the same pieces. The gear also marks the multiples of composite q;
    such a number has a prime factor >= 7 below sqrt(top), so it is marked whenever every
    sieving prime is. Hence two kinds of input:
      - full: the pieces cover every prime from 7 to sqrt(top) (floors 13-19), the whole
        output buffer is compared bit for bit;
      - partial: pieces just below the gear's lowest prime (classic), at it, far above it and
        at sqrt(top), floors 16 to 30 (first / q from 2^20 to 2^62); v7.0 must mark every bit
        v6.1 marks, and every further bit must be a composite number (Miller-Rabin).
    Both use block factors 0.05 (short blocks), 0.5 (the default) and 2 (too wide for the
    candidate search, every j checked), buckets from 16 slots per region (a round ends mid
    block) to all hits in one round, 1, 3 and 8 threads;
  - whole runs: both scanners on the cases of test_engine_v6_identity, each into its own
    empty portal, every output file compared byte for byte (PGS2 timestamp zeroed) and the
    handoff's result fields; v7.0 runs them with the threshold at 1 % (the gear takes every
    bucketed prime from its lower limits up) and at the default.
A comparison that cannot fail does not pass: BROKEN_CHECK drops one jump piece from the v7.0
call and expects the comparison to report it.

Run inside WSL from the repo root:
    python3 unitTests/test_engine_v7_0_identity.py
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

REFERENCE, CANDIDATE = "prime_sieve_v6_1.py", "prime_sieve_v7_0.py"
REFERENCE_SO, CANDIDATE_SO = "prime_sieve_engine_v6_1.so", "prime_sieve_engine_v7_0.so"
JUMP_ON_ENV = {"PRIMEATLAS_V7_JUMP_PCT": "1"}
# v6.1 reads PRIMEATLAS_V6_*, v7.0 PRIMEATLAS_V7_*: the small-segment cases set both.
SMALL_SEGMENT_ENV = {**v6_cases.SMALL_SEGMENT_ENV,
                     **{k.replace("_V6_", "_V7_"): v for k, v in
                        v6_cases.SMALL_SEGMENT_ENV.items()}}


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
        passed &= check(len(ref_files) > 0, f"{label}: v6.1 wrote output files")
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
    ref = ctypes.CDLL(os.path.join(SIEVE_DIR, REFERENCE_SO))
    ref.sieve_wheel_bucketed.argtypes = [ctypes.POINTER(U64), ctypes.POINTER(U64)] + \
        [U64] * 7 + [ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(U64)]
    ref.sieve_wheel_bucketed.restype = ctypes.c_int
    new = ctypes.CDLL(os.path.join(SIEVE_DIR, CANDIDATE_SO))
    new.sieve_wheel_bucketed.argtypes = [ctypes.POINTER(U64), ctypes.POINTER(U64)] + \
        [U64] * 8 + [ctypes.c_double, ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(U64)]
    new.sieve_wheel_bucketed.restype = ctypes.c_int
    return ref, new


def bucketed(lib, pieces, base, n_bits, region_bits, threads, bucket_bytes, jump=None):
    """(rc, buffer bytes); jump = (jump_from, block_factor) calls the v7.0 signature."""
    buf = (ctypes.c_ubyte * ((n_bits + 7) // 8 + 8))()
    lo = (U64 * len(pieces))(*[a for a, _ in pieces])
    hi = (U64 * len(pieces))(*[b for _, b in pieces])
    done = (U64 * 1)(0)
    args = [lo, hi, len(pieces), base >> 64, base & (2 ** 64 - 1), n_bits, region_bits,
            threads, bucket_bytes]
    if jump is not None:
        args += list(jump)
    rc = lib.sieve_wheel_bucketed(*args, buf, done)
    return rc, bytes(buf)


def gear_lowest(base, n_bits):
    """The lowest prime the v7.0 engine lets the gear take (prime_sieve_engine_v7_0.c)."""
    span = 30 * ((n_bits + 7) // 8)
    return max(2 * span, (base >> 62) + 1)


def is_probable_prime(n):
    """Miller-Rabin with the first 20 primes as bases: never calls a prime composite."""
    if n < 2:
        return False
    small = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71)
    for p in small:
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for a in small:
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def marked_numbers(buf, base, n_bits):
    """{number} of the set bits of a wheel buffer (byte b = base + 30 b, bit j = residue j)."""
    residues = (1, 7, 11, 13, 17, 19, 23, 29)
    out = set()
    for b in range((n_bits + 7) // 8):
        v = buf[b]
        while v:
            j = (v & -v).bit_length() - 1
            v &= v - 1
            if 8 * b + j < n_bits:
                out.add(base + 30 * b + residues[j])
    return out


def full_cases(rng):
    """Cases whose pieces cover every prime from 7 to sqrt(top), cut at the gear's limit."""
    cases = []
    for floor in (13, 16, 19):
        for n_bits in (1000, 8192 * 8 * 5 + 3):
            base = (10 ** floor // 30) * 30 + 30 * rng.randrange(10 ** 6)
            limit = math.isqrt(base + 30 * ((n_bits + 7) // 8)) + 1
            jf = gear_lowest(base, n_bits)
            if jf >= limit:
                continue
            cuts = sorted({7, jf, limit} | {rng.randrange(7, jf) for _ in range(2)}
                          | {rng.randrange(jf, limit) for _ in range(5)})
            for (threads, bucket_bytes), factor in zip(
                    rng.sample([(1, 1 << 16), (3, 1 << 20), (8, 1 << 28)], 3),
                    rng.sample([0.05, 0.5, 2.0], 3)):
                cases.append((list(zip(cuts, cuts[1:])), base, n_bits,
                              rng.choice([8192 * 8, 1 << 20]), threads, bucket_bytes, jf, factor))
    return cases


def jump_cases(rng):
    """(pieces, base, n_bits, region_bits, threads, bucket_bytes, jump_from, block_factor)."""
    cases = []
    for floor in (16, 19, 22, 25, 28, 30):
        for n_bits in (1000, 8192 * 8 * 5 + 3, 8192 * 8 * 200):
            base = (10 ** floor // 30) * 30 + 30 * rng.randrange(10 ** 6)
            limit = math.isqrt(base + 30 * ((n_bits + 7) // 8)) + 1
            jf = gear_lowest(base, n_bits)
            width = min(2 * 10 ** 7, jf // 2)
            if jf + width >= limit:
                continue
            spots = [jf - width, jf, rng.randrange(jf, limit - width), limit - width]
            pieces = sorted({(max(7, a), min(limit, a + width)) for a in spots})
            for (threads, bucket_bytes), factor in zip(
                    rng.sample([(1, 1 << 16), (3, 1 << 20), (8, 1 << 28)], 3),
                    rng.sample([0.05, 0.5, 2.0], 3)):
                region_bits = rng.choice([8192 * 8, 1 << 20])
                cases.append((pieces, base, n_bits, region_bits, threads, bucket_bytes, jf,
                              factor))
    return cases


def run_pair(ref, new, case):
    pieces, base, n_bits, region_bits, threads, bucket_bytes, jf, factor = case
    want = bucketed(ref, pieces, base, n_bits, region_bits, threads, bucket_bytes)
    got = bucketed(new, pieces, base, n_bits, region_bits, threads, bucket_bytes, (jf, factor))
    return want, got


def compare_engine_calls(ref, new):
    rng = random.Random(70)
    passed = True
    cases = full_cases(rng)
    differing = []
    for case in cases:
        want, got = run_pair(ref, new, case)
        if want[0] != 0 or want != got:
            differing.append(case[1:])
    if differing:
        print(f"       first differing full inputs: {differing[:3]}")
    passed &= check(len(cases) >= 12 and not differing,
                    f"full coverage: {len(cases)} inputs bit-identical to v6.1")

    cases = jump_cases(rng)
    jump_pieces = extra = 0
    bad = []
    for case in cases:
        (rc_w, want), (rc_g, got) = run_pair(ref, new, case)
        jump_pieces += sum(1 for lo, _ in case[0] if lo >= case[6])
        base, n_bits = case[1], case[2]
        missing = any(w & ~g for w, g in zip(want, got))
        more = marked_numbers(bytes(g & ~w for w, g in zip(want, got)), base, n_bits)
        extra += len(more)
        primes = [n for n in more if is_probable_prime(n)]
        if rc_w or rc_g or missing or primes:
            bad.append((base, n_bits, case[4], case[5], case[7], missing, primes[:3]))
    if bad:
        print(f"       first bad partial inputs: {bad[:3]}")
    passed &= check(len(cases) >= 20 and jump_pieces >= 2 * len(cases),
                    f"partial: {len(cases)} inputs, {jump_pieces} of their pieces on the gear")
    return passed & check(not bad, f"partial: every v6.1 bit marked, the {extra} further bits "
                                   f"all composite")


def broken_check(ref, new):
    """The comparison sees a wrong engine: the v7.0 call with one jump piece dropped misses
    bits v6.1 marks on all pieces (the dropped q range lands in the buffer), and a prime set
    as composite is caught by the primality check."""
    rng = random.Random(71)
    for pieces, base, n_bits, region_bits, threads, bucket_bytes, jf, factor in jump_cases(rng):
        if n_bits < 8192 * 8 * 200:
            continue
        jumped = [p for p in pieces if p[0] >= jf]
        if not jumped:
            continue
        fewer = [p for p in pieces if p != jumped[0]]
        want = bucketed(ref, pieces, base, n_bits, region_bits, threads, bucket_bytes)
        got = bucketed(new, fewer, base, n_bits, region_bits, threads, bucket_bytes,
                       (jf, factor))
        lost = any(w & ~g for w, g in zip(want[1], got[1]))
        return check(lost and is_probable_prime(2 ** 89 - 1)
                     and not is_probable_prime((2 ** 31 - 1) * (2 ** 61 - 1)),
                     "an engine that skips one jump piece is reported; the primality check "
                     "tells a prime from a composite")
    return check(False, "a broken-check input exists")


def main():
    passed = True
    for name in (REFERENCE_SO, CANDIDATE_SO):
        passed &= check(os.path.exists(os.path.join(SIEVE_DIR, name)), f"{name} is built")
    if passed:
        ref, new = load_engines()
        passed &= broken_check(ref, new)
        passed &= compare_engine_calls(ref, new)
    tmp = tempfile.mkdtemp(prefix="engine_v7_0_identity_")
    try:
        for case in v6_cases.CASES:
            passed &= compare_runs(tmp, case[0] + " gear 1 %", *case[1:], extra_env=JUMP_ON_ENV)
        for case in v6_cases.CASES[:3]:
            passed &= compare_runs(tmp, *case)
        for case in v6_cases.SMALL_SEGMENT_CASES:
            passed &= compare_runs(tmp, *case, extra_env={**SMALL_SEGMENT_ENV, **JUMP_ON_ENV})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    import engine_v7_lib
    from _native_skip import exit_if_skipped
    exit_if_skipped([engine_v7_lib.load_lib])
    raise SystemExit(main())
