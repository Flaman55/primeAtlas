"""WSL test: engine pt2 (partial sieve + primality proof, prime_sieve_pt2.py).

Checks:
  - the proof alone (pt2_prove()): every odd n of ranges near 10^12, 10^18 and 10^23 agrees
    with the 13 Miller-Rabin bases (a proof there); numbers that fool weaker tests are
    composite: Carmichael numbers, strong pseudoprimes to the bases 2..23 and 2..37, and
    3317044064679887385961981, a strong pseudoprime to all 13 bases 2..41; a prime = 1 (mod 8)
    with +1 from every base up to 43 (10001584849) is prime; squares of primes are composite;
    n / s at or past L_373 is refused (-2);
  - the table bounds: pt2_bases() switches from k to k + 1 bases exactly at top / s = L_p, is 0
    past L_373; pt2_min_s() is the smallest s with top / s < L_373;
  - engine calls (pt2_sieve_odd()): the pseudosquares path on floors 12-24 bit-identical to
    pt1's 13-base call, on floors 25-33 to pt1's BPSW call; the 13-base path identical to pt1's;
    a call whose top / B reaches the bases' L_p is refused;
  - whole runs, each into its own empty portal: floors 10-22 (13 bases) byte-identical to
    v6.1; floors 25, 29 and 33 (pseudosquares) hold the primes of pt1's P files, written to the
    D store; a run across MR_DET_BOUND on floor 24 uses both proofs; count-only totals equal;
    floors 6 and 34 refused with no file;
  - a comparison that cannot fail does not pass: a pt1 P file with one byte changed differs;
  - through orchestrator_v3.py: D windows, benchmark rows named pt2, auto-continue from the D
    store, and pt2's D window proving pt1's P window of the same offset.

Run inside WSL from the repo root:
    python3 unitTests/test_engine_pt2.py
"""
import ctypes
import os
import random
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_engine_v6_identity as v6_cases  # noqa: E402

SIEVE_DIR = v6_cases.SIEVE_DIR
sys.path.insert(0, SIEVE_DIR)
check = v6_cases.check
U64 = ctypes.c_uint64
M64 = 2 ** 64 - 1
MR_DET_BOUND = 3_317_044_064_679_887_385_961_981
L_373 = 4_235_025_223_080_597_503_519_329
MR_BASES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41)


def mr_det(n):
    """13-base strong probable prime test: a proof below MR_DET_BOUND."""
    if n < 2:
        return False
    for p in MR_BASES:
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while d % 2 == 0:
        d, s = d // 2, s + 1
    for a in MR_BASES:
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def load():
    pt2 = ctypes.CDLL(os.path.join(SIEVE_DIR, "prime_sieve_engine_pt2.so"))
    pt1 = ctypes.CDLL(os.path.join(SIEVE_DIR, "prime_sieve_engine_pt1.so"))
    for lib, name in ((pt2, "pt2"), (pt1, "pt1")):
        getattr(lib, f"{name}_ctx_new").argtypes = [U64]
        getattr(lib, f"{name}_ctx_new").restype = ctypes.c_void_p
        getattr(lib, f"{name}_ctx_free").argtypes = [ctypes.c_void_p]
        getattr(lib, f"{name}_sieve_odd").argtypes = [ctypes.c_void_p, U64, U64, U64, ctypes.c_int,
                                                      U64, U64, ctypes.POINTER(ctypes.c_ubyte),
                                                      ctypes.POINTER(U64)]
        getattr(lib, f"{name}_sieve_odd").restype = ctypes.c_int
    pt2.pt2_prove.argtypes = [U64, U64, U64]
    pt2.pt2_prove.restype = ctypes.c_int
    pt2.pt2_bases.argtypes = [U64, U64, U64]
    pt2.pt2_bases.restype = ctypes.c_int
    pt2.pt2_min_s.argtypes = [U64, U64]
    pt2.pt2_min_s.restype = U64
    return pt2, pt1


def prove(pt2, n, s=1):
    return pt2.pt2_prove(n >> 64, n & M64, s)


def check_proof(pt2):
    passed = True
    rng = random.Random(2)
    for lo in (10 ** 12 + 1, 10 ** 18 + 1, 10 ** 23 + 1, MR_DET_BOUND - 20001):
        bad = [n for n in range(lo, lo + 20000, 2)
               if any(n % p == 0 for p in (3, 5, 7)) is False and prove(pt2, n) != mr_det(n)]
        passed &= check(not bad, f"proof agrees with 13 MR bases on 10000 odd numbers from "
                                 f"{lo:.3e} ({bad[:3]})")
    for _ in range(300):
        n = rng.randrange(10 ** 20, MR_DET_BOUND) | 1
        if any(n % p == 0 for p in (3, 5, 7)):
            continue
        if prove(pt2, n) != mr_det(n):
            passed &= check(False, f"random {n}: proof {prove(pt2, n)} vs MR {mr_det(n)}")
            break
    fools = {"Carmichael 1909001": 1_909_001,
             "Carmichael 9585541": 9_585_541,
             "spsp 2..23": 3_825_123_056_546_413_051,
             "spsp 2..37": 318_665_857_834_031_151_167_461,
             "spsp 2..41 (MR_DET_BOUND)": MR_DET_BOUND,
             "square of 1000003": 1_000_003 ** 2,
             "square of 10^12 + 39": (10 ** 12 + 39) ** 2}
    for label, n in fools.items():
        passed &= check(prove(pt2, n) == 0, f"{label} is composite")
    passed &= check(mr_det(MR_DET_BOUND), "MR_DET_BOUND fools the 13 MR bases (control)")
    passed &= check(prove(pt2, 10_001_584_849) == 1,
                    "10001584849 (= 1 mod 8, +1 from every base up to 43) is prime")
    passed &= check(prove(pt2, L_373) == -2 and prove(pt2, L_373 - 2) != -2
                    and prove(pt2, 10 ** 30 + 57, 10 ** 5) == -2,
                    "n / s at or past L_373 refused (-2)")
    return passed


def check_table(pt2):
    l_281, l_283 = 208_936_365_799_044_975_961, 533_552_663_339_828_203_681
    s = 1000
    k = pt2.pt2_bases(*divmod(l_281 * s - 1, 2 ** 64), s)
    k_next = pt2.pt2_bases(*divmod(l_281 * s, 2 ** 64), s)
    passed = check(k == 60 and k_next == 61, f"bases: top / s just below L_281 -> 60 "
                                              f"(p = 281), at it -> 61 ({k}, {k_next})")
    passed &= check(pt2.pt2_bases(*divmod(l_283 * s, 2 ** 64), s) == 62,
                    "bases: top / s = L_283 -> 62 (L_293 > L_283)")
    passed &= check(pt2.pt2_bases(*divmod(L_373 * 7, 2 ** 64), 7) == 0, "bases: past L_373 -> 0")
    for top in (10 ** 30, 10 ** 34 - 1, L_373 * 5):
        s_min = pt2.pt2_min_s(*divmod(top, 2 ** 64))
        passed &= check(top // s_min < L_373 and top // (s_min - 1) >= L_373,
                        f"min s for top {top:.3e} is {s_min:,}")
    return passed


def sieve_call(lib, name, b, lo, n_odd, mode, threads=3, chunk=4096):
    ctx = getattr(lib, f"{name}_ctx_new")(b)
    bits = (ctypes.c_ubyte * ((n_odd + 7) // 8))()
    done = (U64 * 1)(0)
    rc = getattr(lib, f"{name}_sieve_odd")(ctx, lo >> 64, lo & M64, n_odd, mode, threads, chunk,
                                            bits, done)
    getattr(lib, f"{name}_ctx_free")(ctx)
    return rc, bytes(bits)


def check_engine_calls(pt2, pt1):
    passed = True
    rng = random.Random(3)
    for floor in (12, 16, 20, 24, 25, 27, 29, 31, 33):
        lo = (10 ** floor + rng.randrange(10 ** 9)) | 1
        n_odd = 100_003
        top = lo + 2 * (n_odd - 1)
        b = max(1000, top // L_373 + 1)
        nb = pt2.pt2_bases(top >> 64, top & M64, b)
        rc, got = sieve_call(pt2, "pt2", b, lo, n_odd, nb)
        ref_mode = 1 if top < MR_DET_BOUND else 0     # pt1: 13 MR bases or BPSW
        rc_r, want = sieve_call(pt1, "pt1", b, lo, n_odd, ref_mode)
        primes = n_odd - sum(bin(x).count("1") for x in got)   # padding bits stay 0
        passed &= check(rc == 0 and rc_r == 0 and got == want,
                        f"floor {floor}: pseudosquares ({nb} bases, B {b:,}) bit-identical to "
                        f"pt1 {'MR' if ref_mode else 'BPSW'} ({primes} primes)")
    lo = (10 ** 18 + 12345) | 1
    rc, got = sieve_call(pt2, "pt2", 1000, lo, 50_001, 0)
    rc_r, want = sieve_call(pt1, "pt1", 1000, lo, 50_001, 1)
    passed &= check(rc == 0 and got == want, "13-base path bit-identical to pt1's")
    lo = (10 ** 29) | 1
    top = lo + 2 * 999
    nb_ok = pt2.pt2_bases(top >> 64, top & M64, 10 ** 6)
    rc, _ = sieve_call(pt2, "pt2", 10 ** 6, lo, 1000, nb_ok - 1)
    passed &= check(rc == -1, f"call with {nb_ok - 1} bases (top / B reaches their L_p) refused")
    rc, _ = sieve_call(pt2, "pt2", 10 ** 6, lo, 1000, nb_ok)
    passed &= check(rc == 0, f"same call with {nb_ok} bases accepted")
    return passed


def run(script, portal, floor, idx_lo, idx_hi, window_m, write_files=True, extra_env=None):
    os.makedirs(portal, exist_ok=True)
    return v6_cases.run_scanner(script, portal, floor, idx_lo, idx_hi, window_m, write_files,
                                extra_env or {})


def primes_by_window(portal):
    """{window name without the _P suffix and store: gap-stream bytes} of every PGS2 file."""
    files, metrics = v6_cases.snapshot(portal)
    out = {}
    for path, data in files.items():
        name = os.path.basename(path).replace("_P.bin", ".bin")
        out[name] = data
    return out, files, metrics


def compare_with(tmp, label, ref_script, floor, idx_lo, idx_hi, window_m, write_files=True,
                 drop_one=False):
    """pt2 and ref_script on one case: the same windows with the same primes, pt2's all in
    the D store; equal totals."""
    p_ref, p_new = (os.path.join(tmp, f"{label.replace(' ', '_')}_{s}") for s in ("ref", "pt2"))
    rc_r, tail_r = run(ref_script, p_ref, floor, idx_lo, idx_hi, window_m, write_files)
    rc_n, tail_n = run("prime_sieve_pt2.py", p_new, floor, idx_lo, idx_hi, window_m, write_files)
    if rc_r or rc_n:
        print(tail_r if rc_r else tail_n)
    ref, ref_files, ref_m = primes_by_window(p_ref)
    new, new_files, new_m = primes_by_window(p_new)
    if drop_one and ref:
        name = sorted(ref)[0]
        data = bytearray(ref[name])
        data[-1] ^= 0xFF
        ref[name] = bytes(data)
    passed = check(rc_r == 0 and rc_n == 0, f"{label}: {ref_script} and pt2 exit 0")
    if write_files:
        passed &= check(len(new) > 0 and all(os.sep + "source_primes" + os.sep in p
                                              for p in new_files),
                        f"{label}: pt2 wrote {len(new)} windows, all in the D store")
    same = sorted(ref) == sorted(new) and all(ref[k] == new[k] for k in ref)
    keys = ("total_primes_found", "windows_processed", "numbers_processed", "bytes_written")
    same &= all(ref_m.get(k) == new_m.get(k) for k in keys)
    if drop_one:
        return check(not same, f"{label}: a changed reference file is reported")
    return passed & check(same, f"{label}: same windows, same primes, equal totals "
                                f"({new_m.get('total_primes_found')})")


def check_runs(tmp):
    passed = True
    for label, floor, a, b, w, wf in (("floor 10", 10, 0, 2, 10 ** 6, True),
                                      ("floor 13 odd width", 13, 0, 3, 1_000_001, True),
                                      ("floor 19 count-only", 19, 3, 5, 10 ** 6, False),
                                      ("floor 22 top end", 22, 89_999_999_999_999_997,
                                       89_999_999_999_999_999, 10 ** 6, True)):
        passed &= compare_with(tmp, label, "prime_sieve_v6_1.py", floor, a, b, w, wf)
    for label, floor, a, b, w, wf in (("floor 25", 25, 0, 1, 10 ** 6, True),
                                      ("floor 29", 29, 7, 7, 10 ** 6, True),
                                      ("floor 33 count-only", 33, 0, 0, 10 ** 6, False),
                                      ("floor 33", 33, 3, 3, 10 ** 6, True)):
        passed &= compare_with(tmp, label, "prime_sieve_pt1.py", floor, a, b, w, wf)
    idx = (MR_DET_BOUND - 10 ** 24) // 10 ** 6
    passed &= compare_with(tmp, "floor 24 across MR_DET_BOUND", "prime_sieve_pt1.py", 24,
                           idx - 1, idx, 10 ** 6)
    portal = os.path.join(tmp, "both_proofs")
    rc, out = run("prime_sieve_pt2.py", portal, 24, idx - 1, idx, 10 ** 6)
    passed &= check(rc == 0 and "1 by 13 Miller-Rabin bases, 1 by the pseudosquares test" in out,
                    "floor 24 across MR_DET_BOUND: one window per proof")
    passed &= compare_with(tmp, "broken check", "prime_sieve_pt1.py", 25, 2, 2, 10 ** 6,
                           drop_one=True)
    for floor in (6, 34):
        portal = os.path.join(tmp, f"refused_{floor}")
        rc, _ = run("prime_sieve_pt2.py", portal, floor, 0, 0, 10 ** 6)
        files = [n for _r, _d, ns in os.walk(portal) for n in ns if n.endswith(".bin")]
        passed &= check(rc == 2 and not files, f"floor {floor} refused (rc={rc}, {len(files)} files)")
    return passed


def check_orchestrator(tmp):
    """orchestrator_v3.py with pt2 on floor 25: D windows, a benchmark row named pt2, auto
    continue from the D store, and pt2's D window proves pt1's P window of the same offset."""
    import csv
    import storage_kinds as sk
    portal = os.path.join(tmp, "orch")
    os.makedirs(portal)
    w = 10 ** 6

    def orch(engine, count, auto, start):
        env = dict(os.environ, CONSTELLATION_PORTAL_DIR=portal, PRIMEATLAS_SCANNER_VERSION=engine)
        cmd = [sys.executable, "orchestrator_v3.py", "25", str(count), auto, str(start), "1", "0",
               "4", "2", str(w)]
        proc = subprocess.run(cmd, cwd=SIEVE_DIR, env=env, capture_output=True, text=True)
        return proc.returncode, proc.stdout + proc.stderr

    rc, out = orch("pt1", 1, "0", 3)                  # P window 3
    p3 = sk.window_path(portal, 25, 3 * w, w, "3M", sk.KIND_P)
    passed = check(rc == 0 and os.path.exists(p3), "orchestrator pt1 wrote P window 3")
    rc, out = orch("pt2", 2, "0", 0)                  # D windows 0, 1
    passed &= check(rc == 0 and all(os.path.exists(sk.window_path(portal, 25, i * w, w, lbl))
                                    for i, lbl in ((0, "0"), (1, "1M"))),
                    "orchestrator pt2 floor 25 wrote D windows 0 and 1")
    rc, out = orch("pt2", 1, "1", 0)                  # auto: continues at window 2
    passed &= check(rc == 0 and os.path.exists(sk.window_path(portal, 25, 2 * w, w, "2M")),
                    "pt2 auto-continues floor 25 from its D store")
    rc, out = orch("pt2", 1, "0", 3)                  # D window 3 proves P window 3
    passed &= check(rc == 0 and not os.path.exists(p3)
                    and "PRIME_WINDOW_10p25_off_3M" in sk.read_proven_tags(portal, 25),
                    "pt2's D window 3 proves pt1's P window 3 (P removed, listed as D/P)")
    with open(os.path.join(portal, "benchmark_log.csv"), encoding="utf-8") as f:
        engines = [row.get("engine") for row in csv.DictReader(f)]
    passed &= check(engines.count("pt2") == 3, f"benchmark rows name the engine pt2 ({engines})")
    return passed


def main():
    passed = True
    for name in ("prime_sieve_engine_pt2.so", "prime_sieve_engine_pt1.so"):
        passed &= check(os.path.exists(os.path.join(SIEVE_DIR, name)), f"{name} is built")
    if passed:
        pt2, pt1 = load()
        passed &= check_proof(pt2)
        passed &= check_table(pt2)
        passed &= check_engine_calls(pt2, pt1)
    tmp = tempfile.mkdtemp(prefix="engine_pt2_")
    try:
        passed &= check_runs(tmp)
        passed &= check_orchestrator(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    from _native_skip import exit_if_skipped
    exit_if_skipped([lambda: ctypes.CDLL(os.path.join(SIEVE_DIR, "prime_sieve_engine_pt2.so"))])
    raise SystemExit(main())
