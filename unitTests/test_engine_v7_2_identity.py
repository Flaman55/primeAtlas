"""WSL test: prime_sieve_v7_2.py produces exactly what prime_sieve_v6_1.py (v6.1) produces.

Two levels, as test_engine_v7_0_identity.py:
  - engine calls: sieve_wheel_bucketed() of prime_sieve_engine_v7_2.so with the jump gear on a
    virtual gear span of 1, 7 and 100 times the buffer span (1 = v7.0's gear) against v6.1's
    .so on the same pieces:
      - full: the pieces cover every prime from 7 to sqrt(top) (floors 13-19), the whole
        output buffer is compared bit for bit;
      - partial: pieces at the gear's lowest prime (2 * gear span), far above it and at
        sqrt(top), floors 16 to 30; v7.2 must mark every bit v6.1 marks, and every further
        bit must be a composite number (Miller-Rabin). No landing of the virtual part may show
        up: the buffer's padding bytes past n_bits stay zero;
  - whole runs: both scanners on the cases of test_engine_v6_identity, each into its own
    empty portal, every output file compared byte for byte (PGS2 timestamp zeroed) and the
    handoff's result fields; v7.2 runs them with the gear on every bucketed prime and a gear
    span of the model (about 10 to 100 times the buffer on floors 19-22), with the gear span
    switched off (0 %), at the defaults, and with small segments.
A comparison that cannot fail does not pass: one jump piece dropped from the v7.2 call must
be reported.

Run inside WSL from the repo root:
    python3 unitTests/test_engine_v7_2_identity.py
"""
import ctypes
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_engine_v6_identity as v6_cases  # noqa: E402
import test_engine_v7_0_identity as v7_0  # noqa: E402

SIEVE_DIR = v6_cases.SIEVE_DIR
check = v6_cases.check
U64 = ctypes.c_uint64

CANDIDATE = "prime_sieve_v7_2.py"
REFERENCE_SO, CANDIDATE_SO = "prime_sieve_engine_v6_1.so", "prime_sieve_engine_v7_2.so"
GEAR_FACTORS = (1, 7, 100)
# Gear on every bucketed prime from its lower limits up, gear span = the model's V* with a = 1
# and b = 0.01: about 10 x the buffer on floor 19 with 3 windows of 10^6, 100 x on floor 22.
VIRTUAL_ENV = {"PRIMEATLAS_V7_JUMP_MODEL_PCT": "1", "PRIMEATLAS_V7_JUMP_BLOCK_COST": "1",
               "PRIMEATLAS_V7_JUMP_LANDING_COST_PCT": "1", "PRIMEATLAS_V7_GEAR_SPAN_PCT": "100"}
SPAN_OFF_ENV = {**VIRTUAL_ENV, "PRIMEATLAS_V7_GEAR_SPAN_PCT": "0"}
PADDING = 8


def load_engines():
    ref = ctypes.CDLL(os.path.join(SIEVE_DIR, REFERENCE_SO))
    ref.sieve_wheel_bucketed.argtypes = [ctypes.POINTER(U64), ctypes.POINTER(U64)] + \
        [U64] * 7 + [ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(U64)]
    ref.sieve_wheel_bucketed.restype = ctypes.c_int
    new = ctypes.CDLL(os.path.join(SIEVE_DIR, CANDIDATE_SO))
    new.sieve_wheel_bucketed.argtypes = [ctypes.POINTER(U64), ctypes.POINTER(U64)] + \
        [U64] * 9 + [ctypes.c_double, ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(U64)]
    new.sieve_wheel_bucketed.restype = ctypes.c_int
    return ref, new


def bucketed(lib, pieces, base, n_bits, region_bits, threads, bucket_bytes, jump=None):
    """(rc, buffer bytes incl. PADDING bytes past the last one); jump = (jump_from, gear_span,
    block_factor) calls the v7.2 signature."""
    n_bytes = (n_bits + 7) // 8
    buf = (ctypes.c_ubyte * (n_bytes + PADDING))()
    lo = (U64 * len(pieces))(*[a for a, _ in pieces])
    hi = (U64 * len(pieces))(*[b for _, b in pieces])
    done = (U64 * 1)(0)
    args = [lo, hi, len(pieces), base >> 64, base & (2 ** 64 - 1), n_bits, region_bits,
            threads, bucket_bytes]
    if jump is not None:
        args += list(jump)
    rc = lib.sieve_wheel_bucketed(*args, buf, done)
    return rc, bytes(buf)


def gear_lowest(base, gear):
    """The lowest prime the v7.2 engine lets the gear take for a gear span `gear`."""
    return max(2 * gear, (base >> 62) + 1)


def _cases(rng, floors, sizes, full):
    cases = []
    for floor in floors:
        for n_bits in sizes:
            span = 30 * ((n_bits + 7) // 8)
            base = (10 ** floor // 30) * 30 + 30 * rng.randrange(10 ** 6)
            limit = math.isqrt(base + span) + 1
            for factor in GEAR_FACTORS:
                gear = span * factor
                jf = gear_lowest(base, gear)
                if full:
                    if jf >= limit:
                        continue
                    cuts = sorted({7, jf, limit} | {rng.randrange(7, jf) for _ in range(2)}
                                  | {rng.randrange(jf, limit) for _ in range(3)})
                    pieces = list(zip(cuts, cuts[1:]))
                else:
                    width = min(2 * 10 ** 7, jf // 2)
                    if jf + width >= limit:
                        continue
                    spots = [jf, rng.randrange(jf, limit - width), limit - width]
                    pieces = sorted({(a, min(limit, a + width)) for a in spots})
                threads, bucket_bytes = rng.choice([(1, 1 << 16), (3, 1 << 20), (8, 1 << 28)])
                cases.append((pieces, base, n_bits, rng.choice([8192 * 8, 1 << 20]), threads,
                              bucket_bytes, jf, gear, rng.choice([0.05, 0.5, 2.0])))
    return cases


def run_pair(ref, new, case, pieces=None):
    p, base, n_bits, region_bits, threads, bucket_bytes, jf, gear, block = case
    want = bucketed(ref, p, base, n_bits, region_bits, threads, bucket_bytes)
    got = bucketed(new, pieces or p, base, n_bits, region_bits, threads, bucket_bytes,
                   (jf, gear, block))
    return want, got


def compare_engine_calls(ref, new):
    rng = random.Random(72)
    passed = True
    cases = _cases(rng, (13, 16, 19), (1000, 8192 * 8 * 5 + 3), full=True)
    differing = []
    for case in cases:
        want, got = run_pair(ref, new, case)
        if want[0] != 0 or want != got:
            differing.append(case[1:])
    if differing:
        print(f"       first differing full inputs: {differing[:3]}")
    virtual = sum(1 for c in cases if c[7] > 30 * ((c[2] + 7) // 8))
    passed &= check(len(cases) >= 12 and virtual >= 6 and not differing,
                    f"full coverage: {len(cases)} inputs ({virtual} on a virtual gear span) "
                    f"bit-identical to v6.1")

    cases = _cases(rng, (16, 19, 22, 25, 28, 30), (1000, 8192 * 8 * 5 + 3, 8192 * 8 * 200),
                   full=False)
    extra, bad = 0, []
    for case in cases:
        (rc_w, want), (rc_g, got) = run_pair(ref, new, case)
        base, n_bits = case[1], case[2]
        n_bytes = (n_bits + 7) // 8
        missing = any(w & ~g for w, g in zip(want[:n_bytes], got[:n_bytes]))
        spill = any(got[n_bytes:])
        more = v7_0.marked_numbers(bytes(g & ~w for w, g in zip(want, got)), base, n_bits)
        extra += len(more)
        primes = [n for n in more if v7_0.is_probable_prime(n)]
        if rc_w or rc_g or missing or spill or primes:
            bad.append((base, n_bits, case[7], case[8], missing, spill, primes[:3]))
    if bad:
        print(f"       first bad partial inputs: {bad[:3]}")
    virtual = sum(1 for c in cases if c[7] > 30 * ((c[2] + 7) // 8))
    passed &= check(len(cases) >= 30 and virtual >= 20,
                    f"partial: {len(cases)} inputs, {virtual} on a virtual gear span")
    return passed & check(not bad, f"partial: every v6.1 bit marked, nothing past the buffer, "
                                   f"the {extra} further bits all composite")


def broken_check(ref, new):
    """The comparison sees a wrong engine: one jump piece dropped from a call on a virtual gear
    span misses bits v6.1 marks."""
    rng = random.Random(73)
    for case in _cases(rng, (19, 22), (8192 * 8 * 200,), full=False):
        if case[7] == 30 * ((case[2] + 7) // 8):
            continue
        fewer = case[0][1:]
        (_, want), (_, got) = run_pair(ref, new, case, pieces=fewer)
        if fewer:
            return check(any(w & ~g for w, g in zip(want, got)),
                         "a v7.2 call with one jump piece dropped is reported")
    return check(False, "a broken-check input exists")


def check_console(tmp):
    """The gear line of a run on a virtual gear span names it and its gain."""
    portal = os.path.join(tmp, "console")
    os.makedirs(portal)
    env = dict(os.environ, CONSTELLATION_PORTAL_DIR=portal, **VIRTUAL_ENV)
    cmd = [sys.executable, CANDIDATE, "19", "0", "2", str(v6_cases.WORKERS), "2", "0", "0",
           str(10 ** 6)]
    proc = subprocess.run(cmd, cwd=SIEVE_DIR, env=env, capture_output=True, text=True)
    out = proc.stdout + proc.stderr
    m = re.search(r"gear span ([\d,]+) = ([\d.]+) x the buffer \(100 % of the model\), "
                  r"([\d.]+) x cheaper per q", out)
    passed = check(proc.returncode == 0, "console run exits 0")
    passed &= check(m is not None and float(m.group(2)) > 1 and float(m.group(3)) > 1,
                    f"the gear line names a virtual gear span and its gain "
                    f"({m.group(0) if m else 'missing'})")
    if not passed:
        print(out[-3000:])
    return passed


def main():
    passed = True
    for name in (REFERENCE_SO, CANDIDATE_SO):
        passed &= check(os.path.exists(os.path.join(SIEVE_DIR, name)), f"{name} is built")
    if passed:
        ref, new = load_engines()
        passed &= broken_check(ref, new)
        passed &= compare_engine_calls(ref, new)
    tmp = tempfile.mkdtemp(prefix="engine_v7_2_identity_")
    try:
        passed &= check_console(tmp)
        for case in v6_cases.CASES:
            passed &= v7_0.compare_runs(tmp, case[0] + " virtual gear span", *case[1:],
                                        extra_env=VIRTUAL_ENV, candidate=CANDIDATE)
        for case in v6_cases.CASES[-4:]:
            passed &= v7_0.compare_runs(tmp, case[0] + " gear span off", *case[1:],
                                        extra_env=SPAN_OFF_ENV, candidate=CANDIDATE)
        for case in v6_cases.CASES[:3]:
            passed &= v7_0.compare_runs(tmp, *case, candidate=CANDIDATE)
        for case in v6_cases.SMALL_SEGMENT_CASES:
            passed &= v7_0.compare_runs(tmp, *case,
                                        extra_env={**v7_0.SMALL_SEGMENT_ENV, **VIRTUAL_ENV},
                                        candidate=CANDIDATE)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    import engine_v7_2_lib
    from _native_skip import exit_if_skipped
    exit_if_skipped([engine_v7_2_lib.load_lib])
    raise SystemExit(main())
