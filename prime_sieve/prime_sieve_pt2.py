"""prime_sieve_pt2.py -- batch scanner for engine pt2 (partial sieve + primality proof),
driven by orchestrator_v3.py when SCANNER_VERSION = "pt2". Same CLI and metrics handoff as
prime_sieve_v5.py.

Each window is sieved only by the primes 3..B and every survivor is proven in
prime_sieve_engine_pt2.c: 13 Miller-Rabin bases below storage_kinds.MR_DET_BOUND, the
pseudosquares test from there on (see pt2_plan.py for B and the knobs). Every window goes to
the D store. The batch loop is pt_scan.py's, shared with pt1.
Floors 0..6 (the scanners' low-floor path) and floors above 33 (top / B would reach the
largest known pseudosquare) are refused.
"""
import ctypes
import datetime
import os
import sys
import time

import pt2_plan
import pt_scan
import storage_kinds
from prime_sieve_v5 import (SCAN_METRICS_FILENAME, format_offset,  # noqa: F401
                            read_prime_window_header)

VERSION = "pt2"
MAX_WORKERS = 24
_U64 = 0xFFFFFFFFFFFFFFFF

_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prime_sieve_engine_pt2.so")
_lib = None


def _load_lib():
    global _lib
    if _lib is None:
        if not os.path.exists(_LIB_PATH):
            raise RuntimeError(
                f"Missing {_LIB_PATH} -- build it first: gcc -O3 -Wall -shared -fPIC "
                f"prime_sieve_engine_pt2.c -o prime_sieve_engine_pt2.so -lprimesieve "
                f"-lpthread -lm")
        lib = ctypes.CDLL(_LIB_PATH)
        u64 = ctypes.c_uint64
        lib.pt2_ctx_new.argtypes = [u64]
        lib.pt2_ctx_new.restype = ctypes.c_void_p
        lib.pt2_ctx_count.argtypes = [ctypes.c_void_p]
        lib.pt2_ctx_count.restype = u64
        lib.pt2_ctx_free.argtypes = [ctypes.c_void_p]
        lib.pt2_ctx_free.restype = None
        lib.pt2_bases.argtypes = [u64, u64, u64]
        lib.pt2_bases.restype = ctypes.c_int
        lib.pt2_min_s.argtypes = [u64, u64]
        lib.pt2_min_s.restype = u64
        lib.pt2_prove.argtypes = [u64, u64, u64]
        lib.pt2_prove.restype = ctypes.c_int
        lib.pt2_sieve_odd.argtypes = [
            ctypes.c_void_p,                  # ctx (sieving primes)
            u64, u64,                         # first_odd hi, lo
            u64,                              # n_odd
            ctypes.c_int,                     # n_bases: 0 = 13 MR bases, else pseudosquares
            u64,                              # n_threads
            u64,                              # chunk_odd
            ctypes.POINTER(ctypes.c_ubyte),   # out_bits
            ctypes.POINTER(u64),              # chunks_done (progress counter)
        ]
        lib.pt2_sieve_odd.restype = ctypes.c_int
        _lib = lib
    return _lib


def bases_for(top, b):
    """Pseudosquare bases the proof needs for numbers up to `top` with sieve bound b (0 when
    the table is too short)."""
    return _load_lib().pt2_bases(top >> 64, top & _U64, b)


def min_s(top):
    """Smallest sieve bound with top / s below the largest known pseudosquare."""
    return _load_lib().pt2_min_s(top >> 64, top & _U64)


def main_batch_scanner(base_power, target_idx_list, window_m, write_files=True,
                       compute_sieving_primes_count=False, requested_b=0,
                       chunk_kb=pt2_plan.DEFAULT_CHUNK_KB):
    """Returns 0, or 2 when the floor or B is outside pt2's range."""
    if not pt2_plan.MIN_FLOOR <= base_power <= pt2_plan.MAX_FLOOR:
        print(f"[-] ERROR: pt2 covers floors {pt2_plan.MIN_FLOOR}..{pt2_plan.MAX_FLOOR}, "
              f"got {base_power}; use v7 for this floor.")
        return 2
    target_idx_list = sorted(target_idx_list)
    windows = pt_scan.adjacent_windows(base_power, target_idx_list, window_m)
    combined_lo, combined_hi = windows[0][0], windows[-1][1]
    proofs = [pt2_plan.proof_for_window(lo, hi) for lo, hi in windows]
    needs_pss = pt2_plan.PROOF_PSS in proofs
    floor_s = min_s(combined_hi - 1) if needs_pss else 0
    b = pt2_plan.effective_b(requested_b, combined_lo, combined_hi, floor_s)
    if b is None:
        print(f"[-] ERROR: the proof needs a sieve limit of at least {floor_s:,}, above "
              f"isqrt of the run's lowest number and 2^32; use v7 for this range.")
        return 2
    n_bases = bases_for(combined_hi - 1, b) if needs_pss else 0
    chunk_odd = pt2_plan.chunk_odd(chunk_kb)
    slabs = pt2_plan.plan_slabs(windows, proofs, pt2_plan.slab_numbers(MAX_WORKERS, chunk_kb))

    print("\n" + "=" * 70)
    print(f"[*] BATCH {VERSION} (partial sieve to B + primality proof, PGS2 binary output): "
          f"{len(windows)} windows (target_idx {target_idx_list[0]}..{target_idx_list[-1]}), "
          f"level 10^{base_power}")
    print(f"[*] Combined range: [{combined_lo:,}, {combined_hi:,})  "
          f"size={combined_hi - combined_lo:,}")
    origin = " (default floor(N^(1/4)))" if not requested_b else f" (requested {requested_b:,})"
    if b > pt2_plan.effective_b(requested_b, combined_lo, combined_hi, 0):
        origin += ", raised to the proof's minimum"
    print(f"[*] Sieve limit B = {b:,}{origin}")
    n_mr = proofs.count(pt2_plan.PROOF_MR)
    print(f"[*] Windows: {n_mr} by 13 Miller-Rabin bases, {len(windows) - n_mr} by the "
          f"pseudosquares test" + (f" ({n_bases} bases)" if needs_pss else "")
          + f", all D | {len(slabs)} slabs, {chunk_kb} KiB chunks, {MAX_WORKERS} threads")
    if not write_files:
        print("[*] WRITE_FILES=False -- no PGS2 files will be written this run; only "
              "aggregate prime counts will be reported.")
    print("=" * 70)

    t_base = time.perf_counter()
    lib = _load_lib()
    ctx = lib.pt2_ctx_new(b)
    if not ctx:
        print("[-] ERROR: could not allocate the sieving primes.")
        return 1
    sieving_primes_count = lib.pt2_ctx_count(ctx)
    base_gen_seconds = time.perf_counter() - t_base
    print(f"[*] Sieving primes 3..B: {sieving_primes_count:,} ({base_gen_seconds:.3f}s)")

    def _slab_call(proof):
        bases = n_bases if proof == pt2_plan.PROOF_PSS else 0
        return lambda first_odd, n_odd, bits, done: lib.pt2_sieve_odd(
            ctx, first_odd >> 64, first_odd & _U64, n_odd, bases, MAX_WORKERS, chunk_odd,
            bits, done)

    try:
        return pt_scan.run_slabs(
            version=VERSION, portal=BASE_STORAGE_10PN, base_power=base_power, windows=windows,
            window_m=window_m, slabs=slabs, store_kind=lambda proof: storage_kinds.KIND_D,
            slab_call=_slab_call, chunk_odd=chunk_odd, b=b,
            sieving_primes_count=sieving_primes_count, base_gen_seconds=base_gen_seconds,
            write_files=write_files, compute_sieving_primes_count=compute_sieving_primes_count)
    except RuntimeError:
        print("[-] ERROR: pt2 engine error (a survivor the pseudosquares table cannot decide, "
              "or allocation failure); no window of the failed slab was written.")
        return 1
    finally:
        lib.pt2_ctx_free(ctx)


if __name__ == "__main__":
    # The GUI redirects stdout to a log file: line buffering lets each progress line reach
    # it (and the progress bar) when printed, not when an 8 KiB block fills.
    sys.stdout.reconfigure(line_buffering=True)
    print("=" * 70)
    print(f"[*] PRIME SIEVE -- {VERSION} (partial sieve + Miller-Rabin / pseudosquares proof, "
          f"PGS2 binary output)")
    print("=" * 70)
    # CONSTELLATION_PORTAL_DIR and the positional CLI: as in prime_sieve_v5.py. Position 5
    # (batches per worker) is accepted and unused: pt2 has no worker batches.
    env_override = os.environ.get("CONSTELLATION_PORTAL_DIR")
    BASE_STORAGE_10PN = env_override or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "CONSTELLATION_PORTAL"))
    print(f"[*] Windows written to: {BASE_STORAGE_10PN}\\10p{{N}}\\source_primes\\")

    base_exponent = int(sys.argv[1])
    target_idx_list = list(range(int(sys.argv[2]), int(sys.argv[3]) + 1))
    if len(sys.argv) > 4:
        MAX_WORKERS = int(sys.argv[4])
    WRITE_FILES = bool(int(sys.argv[6])) if len(sys.argv) > 6 else True
    COMPUTE_SIEVING_PRIMES_COUNT = bool(int(sys.argv[7])) if len(sys.argv) > 7 else False
    WINDOW_M = int(sys.argv[8]) if len(sys.argv) > 8 else 10 ** 7
    try:
        REQUESTED_B = pt2_plan.b_from_env(os.environ)
        CHUNK_KB = pt2_plan.chunk_kb_from_env(os.environ)
    except ValueError as e:
        print(f"[-] ERROR: {e}")
        sys.exit(2)

    print("Start time:", datetime.datetime.now().strftime("%H:%M:%S"))
    sys.exit(main_batch_scanner(base_exponent, target_idx_list, WINDOW_M, write_files=WRITE_FILES,
                                compute_sieving_primes_count=COMPUTE_SIEVING_PRIMES_COUNT,
                                requested_b=REQUESTED_B, chunk_kb=CHUNK_KB))
