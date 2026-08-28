"""marking_poc.py -- host-side harness for marking_poc.cu (fourth-step GPU PoC: real MARKING,
not just phase computation -- see that file's own header for the full design rationale and the
load-balancing fix it implements).

TWO INDEPENDENT MODES, run one after the other by default:

  EXACT mode -- the real verification. Compiles (if needed) the ACTUAL, UNMODIFIED
  prime_sieve_engine_v4.c from this same prime_sieve/ directory (the exact file production
  uses), calls its generate_and_sieve_segment_bits() via ctypes as ground truth, and compares
  the GPU kernel's output BYTE-FOR-BYTE against it. This is the strongest verification
  available for this PoC series: not "matches my own re-derivation of the algorithm" but
  "matches the real shipped engine, called unmodified, on the same input."

  A set of small-to-medium test cases specifically includes the self-elimination-guard edge
  cases (distance=0, distance exactly a multiple of a sieving prime, etc.) that a 2026-08-28
  sandbox-only investigation (Python-only, no real GPU) initially seemed to flag as a bug in
  this guard logic -- an extensive re-check (211 randomized + hand-picked edge cases) found
  that re-check's own throwaway test script had an off-by-one in its *test harness* (an
  L_final+1 vs L_final boundary), not a bug in the guard itself; the guard as written in
  marking_poc.cu already matches the real engine exactly. These test cases exist here to keep
  that re-verified confidence in place going forward, on the one thing a sandbox without a GPU
  could not check at all: whether the real CUDA kernel (grid/block launch, the byte-level
  atomicOr, the cooperative MARK_THREADS-way stride) reproduces the same guard logic correctly
  once actually compiled and run on real hardware.

  THROUGHPUT mode -- one realistic-shaped batch (matching a single one of production's ~48
  equal-cost batches at floor 25 scale -- see prime_sieve_v4_1.py's own _build_equal_cost_batches()
  and main_batch_scanner()), timed on real GPU hardware. This is NOT a full floor-25
  extrapolation (that composite CPU-generation + GPU-marking pipeline benchmark is a separate,
  later integration step -- see README.md) -- it answers a narrower question: how fast is ONE
  block-per-prime marking kernel at a realistic prime-count/combined-size shape.

Usage (inside WSL2, after building marking_poc via build_and_run_marking.sh):
    python3 marking_poc.py [--binary ./marking_poc] [--engine-so ../prime_sieve_engine_v4.so]
                            [--mode exact|throughput|both]
"""
import ctypes
import math
import os
import struct
import subprocess
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PRIME_SIEVE_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PRIME_SIEVE_DIR)

import prime_sieve_primesieve as cpu_primesieve  # noqa: E402

MAX_SAFE_PRIME_BITS = 50
MASK64 = (1 << 64) - 1
DEFAULT_ENGINE_SO = os.path.join(_PRIME_SIEVE_DIR, "prime_sieve_engine_v4.so")
DEFAULT_BINARY = os.path.join(_SCRIPT_DIR, "marking_poc")


# -------------------------------------------------------------------------------------------
# GPU binary I/O (matches marking_poc.cu's own documented input/output format exactly).
# -------------------------------------------------------------------------------------------

def write_gpu_input(path, primes, distance_hi, distance_lo, combined_size):
    n_primes = len(primes)
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", n_primes))
        if hasattr(primes, "tobytes"):
            f.write(primes.astype("<u8", copy=False).tobytes())
        else:
            f.write(struct.pack(f"<{n_primes}Q", *primes))
        f.write(struct.pack("<QQQ", distance_hi, distance_lo, combined_size))


def read_gpu_output(path):
    with open(path, "rb") as f:
        (combined_bytes,) = struct.unpack("<Q", f.read(8))
        bits = f.read(combined_bytes)
        timings = struct.unpack("<dddd", f.read(32))
    return bits, timings


def run_gpu(binary, primes, distance_hi, distance_lo, combined_size, tag):
    in_path = os.path.join(_SCRIPT_DIR, f"_marking_input_{tag}.bin")
    out_path = os.path.join(_SCRIPT_DIR, f"_marking_output_{tag}.bin")
    write_gpu_input(in_path, primes, distance_hi, distance_lo, combined_size)
    result = subprocess.run([binary, in_path, out_path], capture_output=True, text=True)
    print(result.stderr, end="")
    os.remove(in_path)
    if result.returncode != 0:
        raise RuntimeError(f"GPU binary exited with code {result.returncode}")
    bits, timings = read_gpu_output(out_path)
    os.remove(out_path)
    return bits, timings


# -------------------------------------------------------------------------------------------
# Ground truth: the real, unmodified production engine, called via ctypes.
# -------------------------------------------------------------------------------------------

def build_engine_so_if_missing(engine_so_path):
    if os.path.isfile(engine_so_path):
        return
    engine_c = os.path.join(_PRIME_SIEVE_DIR, "prime_sieve_engine_v4.c")
    print(f"[*] {engine_so_path} not found -- building it now (same command "
          f"prime_sieve_v4_1.py's own _load_lib() documents)...")
    cmd = ["gcc", "-O3", "-shared", "-fPIC", engine_c, "-o", engine_so_path,
           "-lprimesieve", "-lstdc++", "-lm"]
    subprocess.run(cmd, check=True, cwd=_PRIME_SIEVE_DIR)
    print(f"[*] Built {engine_so_path}")


def load_engine(engine_so_path):
    build_engine_so_if_missing(engine_so_path)
    lib = ctypes.CDLL(engine_so_path)
    lib.generate_and_sieve_segment_bits.argtypes = [
        ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64,
        ctypes.c_uint64, ctypes.POINTER(ctypes.c_ubyte)
    ]
    lib.generate_and_sieve_segment_bits.restype = ctypes.c_int
    return lib


def run_engine_ground_truth(lib, start, stop, distance_hi, distance_lo, combined_size):
    """start/stop is the SIEVING-PRIME range (i.e. [2, L_final) -- NOT the marked-number
    range, which is [distance, distance+combined_size)); this mirrors
    generate_and_sieve_segment_bits()'s own parameter meaning exactly (see that function's
    own primesieve_jump_to(&it, start, stop) call)."""
    n_bytes = (combined_size + 7) // 8
    buf = (ctypes.c_ubyte * n_bytes)()
    ret = lib.generate_and_sieve_segment_bits(start, stop, distance_hi, distance_lo,
                                               combined_size, buf)
    if ret != 0:
        raise RuntimeError(f"engine returned error code {ret}")
    return bytes(buf)


# -------------------------------------------------------------------------------------------
# EXACT mode
# -------------------------------------------------------------------------------------------

def exact_case(binary, lib, tag, name, l_final, distance_hi, distance_lo, combined_size):
    """l_final is the EXCLUSIVE upper bound of the sieving-prime range [2, l_final) -- same
    convention generate_and_sieve_segment_bits() itself uses via primesieve_next_prime()'s
    `< stop` loop condition. Sieving primes are generated once here and fed identically to
    both the GPU kernel and the ground-truth engine call, so any difference in the output can
    only come from a genuine algorithmic mismatch, not from different input primes."""
    primes = cpu_primesieve.generate_primes_in_range(2, l_final)
    primes = [p for p in primes if 2 <= p < l_final]
    max_prime = max(primes) if primes else 0
    if max_prime >= (1 << MAX_SAFE_PRIME_BITS):
        print(f"    [{name}] SKIPPED -- largest sieving prime {max_prime} exceeds the "
              f"2^{MAX_SAFE_PRIME_BITS} safe limit for this PoC's phase_mod_gpu")
        return True

    gpu_bits, timings = run_gpu(binary, primes, distance_hi, distance_lo, combined_size, tag)
    truth_bits = run_engine_ground_truth(lib, 2, l_final, distance_hi, distance_lo, combined_size)

    n_bytes = (combined_size + 7) // 8
    gpu_bits = gpu_bits[:n_bytes]
    mismatches = sum(1 for a, b in zip(gpu_bits, truth_bits) if a != b)
    status = "PASS" if mismatches == 0 else f"FAIL ({mismatches} mismatched bytes)"
    print(f"    [{name}] {status}  ({len(primes):,} sieving primes, combined_size={combined_size:,}, "
          f"kernel={timings[1]*1000:.3f}ms)")
    return mismatches == 0


def run_exact_mode(binary, engine_so_path):
    print("=" * 78)
    print("EXACT mode -- byte-for-byte vs. the real, unmodified production engine")
    print("=" * 78)
    lib = load_engine(engine_so_path)

    cases = [
        # (tag, name, l_final, distance_hi, distance_lo, combined_size)
        ("case1", "distance=0, guard fires on L_final itself (self-elim edge case)",
         318, 0, 0, 100_000),
        ("case2", "distance=0, L_final excludes itself as sieving prime",
         317, 0, 0, 100_000),
        ("case3", "distance = p exactly (p=97)", 100, 0, 97, 1_000),
        ("case4", "distance = p-1 (p=97)", 100, 0, 96, 1_000),
        ("case5", "distance = p+1 (p=97)", 100, 0, 98, 1_000),
        ("case6", "distance = 2p exactly (p=97)", 100, 0, 194, 1_000),
        ("case7", "realistic floor-9-like batch", 31_781, 0, 10 ** 9, 10 ** 7),
        ("case8", "distance_hi != 0 (u128 branch, no guard should fire)",
         31_781, 1, 12_345, 10 ** 7),
    ]
    all_pass = True
    for tag, name, l_final, dh, dl, cs in cases:
        ok = exact_case(binary, lib, tag, name, l_final, dh, dl, cs)
        all_pass = all_pass and ok
    return all_pass


# -------------------------------------------------------------------------------------------
# THROUGHPUT mode
# -------------------------------------------------------------------------------------------

def build_sample_primes(sample_n):
    if sample_n < 10:
        upper = 30
    else:
        upper = int(sample_n * (math.log(sample_n) + math.log(math.log(sample_n)))) + 1000
    print(f"[*] Generating the smallest {sample_n:,} primes via primesieve...")
    t0 = time.perf_counter()
    primes = cpu_primesieve.generate_primes_in_range(2, upper)
    while len(primes) < sample_n:
        upper *= 2
        primes = cpu_primesieve.generate_primes_in_range(2, upper)
    primes = primes[:sample_n]
    print(f"    -> {len(primes):,} primes in {time.perf_counter() - t0:.3f}s")
    return primes


def run_throughput_mode(binary, sample_n=20_000_000, combined_size=10 ** 8):
    print()
    print("=" * 78)
    print("THROUGHPUT mode -- one realistic-shaped batch (NOT a full floor extrapolation --")
    print("that composite CPU-gen + GPU-mark pipeline number is a later integration step)")
    print("=" * 78)
    floor = 25
    distance = 10 ** floor
    distance_hi, distance_lo = distance >> 64, distance & MASK64

    primes = build_sample_primes(sample_n)
    max_prime = max(primes)
    if max_prime >= (1 << MAX_SAFE_PRIME_BITS):
        primes = [p for p in primes if p < (1 << MAX_SAFE_PRIME_BITS)]
        print(f"[!] Truncated sample to {len(primes):,} primes below the "
              f"2^{MAX_SAFE_PRIME_BITS} safe limit.")

    print(f"[*] floor={floor}  n_primes={len(primes):,}  combined_size={combined_size:,}")
    bits, timings = run_gpu(binary, primes, distance_hi, distance_lo, combined_size, "throughput")
    t_upload, t_kernel, t_download, t_total = timings

    total_bits_set = sum(bin(b).count("1") for b in bits)
    density = total_bits_set / combined_size

    print()
    print(f"  primes upload:   {t_upload:.6f}s")
    print(f"  kernel:          {t_kernel:.6f}s")
    print(f"  bits download:   {t_download:.6f}s")
    print(f"  TOTAL:           {t_total:.6f}s")
    print(f"  marked-composite density: {density:.4%} "
          f"(sanity check only -- not necessarily close to the true prime density at this "
          f"floor, since sample_n primes is a small prefix of the real sieving-prime range up "
          f"to sqrt(distance+combined_size); mainly useful to confirm the kernel marked "
          f"*something* plausible rather than all-zero or all-one bits)")

    # FIX (2026-08-28): the previous version of this line reported
    # `len(primes) * combined_size / t_kernel` as "work-units/s", which assumes every one of
    # the 256 threads per block walks the FULL combined_size range for every prime -- wildly
    # wrong, since real per-prime work is ~combined_size/p (huge for small p, often 0-1 for
    # primes near/above combined_size, as most of a large sample are). That number was flagged
    # as bogus after Artur's real-hardware run and replaced with two honest metrics below:
    # actual estimated marking work (computed directly from the real primes list, cheap on
    # CPU), and raw block-dispatch rate (informative on its own re: the marking_overhead_poc.py
    # cost-decomposition finding that block count, not real work, dominated at this scale
    # before the 2026-08-28 shared-memory-broadcast fix to marking_kernel).
    estimated_marks = sum(combined_size // p for p in primes if p < combined_size)
    print(f"  estimated real marking work: ~{estimated_marks:,} position-marks "
          f"(sum of combined_size//p over the sample -- a much smaller, honest number vs. the "
          f"old wrong 'work-units' metric this line used to report)")
    print(f"  estimated real-work rate: {estimated_marks / t_kernel / 1e9:.4f} billion "
          f"marks/s [kernel-only]")
    print(f"  block-dispatch rate: {len(primes) / t_kernel / 1e9:.4f} billion blocks/s "
          f"[kernel-only] -- one block launched per sieving prime in the sample")


def main():
    binary = DEFAULT_BINARY
    engine_so = DEFAULT_ENGINE_SO
    mode = "both"
    if "--binary" in sys.argv:
        binary = sys.argv[sys.argv.index("--binary") + 1]
    if "--engine-so" in sys.argv:
        engine_so = sys.argv[sys.argv.index("--engine-so") + 1]
    if "--mode" in sys.argv:
        mode = sys.argv[sys.argv.index("--mode") + 1]

    ok = True
    if mode in ("exact", "both"):
        ok = run_exact_mode(binary, engine_so) and ok
    if mode in ("throughput", "both"):
        run_throughput_mode(binary)

    print()
    print("=" * 78)
    print("RESULT:", "PASS" if ok else "FAIL -- see mismatches above")
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
