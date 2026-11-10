"""prime_sieve_pt1.py -- batch scanner for engine pt1 (partial sieve + primality test),
driven by orchestrator_v3.py when SCANNER_VERSION = "pt1". Same CLI and metrics handoff as
prime_sieve_v5.py.

Each window is sieved only by the primes 3..B and its survivors are tested in
prime_sieve_engine_pt1.c (see pt1_plan.py for B, the chunk knob and the slab grouping). A
window wholly below storage_kinds.MR_DET_BOUND is tested with 13 Miller-Rabin bases and
written to the D store (byte-identical to v5's output; unitTests/test_engine_pt1.py checks
that); any other window is tested with BPSW and written to the P store
(10p{N}/source_primes_P/, filenames ending in _P.bin).

The batch loop (slabs, progress, overlapped write, metrics) is pt_scan.py's, shared with pt2.
Floors 0..6 (the scanners' low-floor path) and floors above 37 (n >= 2^127) are refused.
"""
import ctypes
import datetime
import os
import sys
import time

import pt1_plan
import pt_scan
import storage_kinds
from prime_sieve_v5 import (SCAN_METRICS_FILENAME, format_offset,  # noqa: F401
                            read_prime_window_header)

VERSION = "pt1"
MAX_WORKERS = 24

_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prime_sieve_engine_pt1.so")
_lib = None


def _load_lib():
    global _lib
    if _lib is None:
        if not os.path.exists(_LIB_PATH):
            raise RuntimeError(
                f"Missing {_LIB_PATH} -- build it first: gcc -O3 -Wall -shared -fPIC "
                f"prime_sieve_engine_pt1.c -o prime_sieve_engine_pt1.so -lprimesieve "
                f"-lpthread -lm")
        lib = ctypes.CDLL(_LIB_PATH)
        lib.pt1_ctx_new.argtypes = [ctypes.c_uint64]
        lib.pt1_ctx_new.restype = ctypes.c_void_p
        lib.pt1_ctx_count.argtypes = [ctypes.c_void_p]
        lib.pt1_ctx_count.restype = ctypes.c_uint64
        lib.pt1_ctx_free.argtypes = [ctypes.c_void_p]
        lib.pt1_ctx_free.restype = None
        lib.pt1_sieve_odd.argtypes = [
            ctypes.c_void_p,                  # ctx (sieving primes)
            ctypes.c_uint64,                  # first_odd_hi
            ctypes.c_uint64,                  # first_odd_lo
            ctypes.c_uint64,                  # n_odd
            ctypes.c_int,                     # det (13 MR bases) or BPSW
            ctypes.c_uint64,                  # n_threads
            ctypes.c_uint64,                  # chunk_odd
            ctypes.POINTER(ctypes.c_ubyte),   # out_bits
            ctypes.POINTER(ctypes.c_uint64),  # chunks_done (progress counter)
        ]
        lib.pt1_sieve_odd.restype = ctypes.c_int
        _lib = lib
    return _lib


def main_batch_scanner(base_power, target_idx_list, window_m, write_files=True,
                        compute_sieving_primes_count=False, requested_b=0,
                        chunk_kb=pt1_plan.DEFAULT_CHUNK_KB):
    """Returns 0, or 2 when the floor or B is outside pt1's range."""
    if not pt1_plan.MIN_FLOOR <= base_power <= pt1_plan.MAX_FLOOR:
        print(f"[-] ERROR: pt1 covers floors {pt1_plan.MIN_FLOOR}..{pt1_plan.MAX_FLOOR}, "
              f"got {base_power}; use v5 for this floor.")
        return 2
    target_idx_list = sorted(target_idx_list)
    windows = pt_scan.adjacent_windows(base_power, target_idx_list, window_m)
    combined_lo, combined_hi = windows[0][0], windows[-1][1]
    if combined_hi > 2 ** 127:
        print(f"[-] ERROR: pt1 needs every number below 2^127, the range ends at {combined_hi:,}.")
        return 2
    b = pt1_plan.effective_b(requested_b, combined_lo, combined_hi)
    kinds = [storage_kinds.written_kind(VERSION, lo, hi) for lo, hi in windows]
    chunk_odd = pt1_plan.chunk_odd(chunk_kb)
    slabs = pt1_plan.plan_slabs(windows, kinds, pt1_plan.slab_numbers(MAX_WORKERS, chunk_kb))

    print("\n" + "=" * 70)
    print(f"[*] BATCH {VERSION} (partial sieve to B + primality test, PGS2 binary output): "
          f"{len(windows)} windows (target_idx {target_idx_list[0]}..{target_idx_list[-1]}), "
          f"level 10^{base_power}")
    print(f"[*] Combined range: [{combined_lo:,}, {combined_hi:,})  "
          f"size={combined_hi - combined_lo:,}")
    print(f"[*] Sieve limit B = {b:,}" + (" (default floor(N^(1/4)))" if not requested_b else
                                          f" (requested {requested_b:,})"))
    n_d = kinds.count(storage_kinds.KIND_D)
    print(f"[*] Windows: {n_d} D (13 Miller-Rabin bases, proven), {len(windows) - n_d} P "
          f"(BPSW, probable) | {len(slabs)} slabs, {chunk_kb} KiB chunks, {MAX_WORKERS} threads")
    if not write_files:
        print("[*] WRITE_FILES=False -- no PGS2 files will be written this run; only "
              "aggregate prime counts will be reported.")
    print("=" * 70)

    t_base = time.perf_counter()
    lib = _load_lib()
    ctx = lib.pt1_ctx_new(b)
    if not ctx:
        print("[-] ERROR: could not allocate the sieving primes.")
        return 1
    sieving_primes_count = lib.pt1_ctx_count(ctx)
    base_gen_seconds = time.perf_counter() - t_base
    print(f"[*] Sieving primes 3..B: {sieving_primes_count:,} ({base_gen_seconds:.3f}s)")

    def _slab_call(kind):
        det = 1 if kind == storage_kinds.KIND_D else 0
        return lambda first_odd, n_odd, bits, done: lib.pt1_sieve_odd(
            ctx, first_odd >> 64, first_odd & 0xFFFFFFFFFFFFFFFF, n_odd, det, MAX_WORKERS,
            chunk_odd, bits, done)

    try:
        return pt_scan.run_slabs(
            version=VERSION, portal=BASE_STORAGE_10PN, base_power=base_power, windows=windows,
            window_m=window_m, slabs=slabs, store_kind=lambda kind: kind, slab_call=_slab_call,
            chunk_odd=chunk_odd, b=b, sieving_primes_count=sieving_primes_count,
            base_gen_seconds=base_gen_seconds, write_files=write_files,
            compute_sieving_primes_count=compute_sieving_primes_count)
    finally:
        lib.pt1_ctx_free(ctx)


if __name__ == "__main__":
    # The GUI redirects stdout to a log file: line buffering lets each progress line reach
    # it (and the progress bar) when printed, not when an 8 KiB block fills.
    sys.stdout.reconfigure(line_buffering=True)
    print("=" * 70)
    print(f"[*] PRIME SIEVE -- {VERSION} (partial sieve + Miller-Rabin / BPSW, PGS2 binary "
          f"output)")
    print("=" * 70)
    # CONSTELLATION_PORTAL_DIR and the positional CLI: as in prime_sieve_v5.py. Position 5
    # (batches per worker) is accepted and unused: pt1 has no worker batches.
    env_override = os.environ.get("CONSTELLATION_PORTAL_DIR")
    BASE_STORAGE_10PN = env_override or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "CONSTELLATION_PORTAL"))
    print(f"[*] Windows written to: {BASE_STORAGE_10PN}\\10p{{N}}\\source_primes(_P)\\")

    base_exponent = int(sys.argv[1])
    target_idx_list = list(range(int(sys.argv[2]), int(sys.argv[3]) + 1))
    if len(sys.argv) > 4:
        MAX_WORKERS = int(sys.argv[4])
    WRITE_FILES = bool(int(sys.argv[6])) if len(sys.argv) > 6 else True
    COMPUTE_SIEVING_PRIMES_COUNT = bool(int(sys.argv[7])) if len(sys.argv) > 7 else False
    WINDOW_M = int(sys.argv[8]) if len(sys.argv) > 8 else 10 ** 7
    try:
        REQUESTED_B = pt1_plan.b_from_env(os.environ)
        CHUNK_KB = pt1_plan.chunk_kb_from_env(os.environ)
    except ValueError as e:
        print(f"[-] ERROR: {e}")
        sys.exit(2)

    print("Start time:", datetime.datetime.now().strftime("%H:%M:%S"))
    sys.exit(main_batch_scanner(base_exponent, target_idx_list, WINDOW_M, write_files=WRITE_FILES,
                                compute_sieving_primes_count=COMPUTE_SIEVING_PRIMES_COUNT,
                                requested_b=REQUESTED_B, chunk_kb=CHUNK_KB))
