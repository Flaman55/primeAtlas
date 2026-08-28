"""marking_overhead_poc.py -- host harness for marking_overhead_poc.cu (cost-decomposition
follow-up to marking_poc.py's real-hardware throughput numbers, 2026-08-28).

WHY THIS EXISTS: marking_poc.py's THROUGHPUT mode collected exactly two (n_primes,
combined_size) points on real hardware:
    3,417 primes      / combined_size=10,000,000  -> kernel 2.97ms
    20,000,000 primes / combined_size=100,000,000 -> kernel 366.5ms
n_primes grew ~5854x, kernel time grew only ~123x. That comparison changed TWO variables at
once (n_primes AND combined_size), so it cannot say whether the cost is dominated by block
count (launch/scheduling overhead -- one block per prime, so more primes means more blocks),
by real marking work (which scales with combined_size/p, summed over primes), or by a third
effect: marking_kernel computes phase_mod_gpu + the self-elimination guard REDUNDANTLY on all
256 threads per block (not just thread 0), which is wasted work whenever a block's prime has
few or no real hits.

This script drives two clean, ONE-variable-at-a-time sweeps against marking_overhead_poc's
three kernel variants (null / phase_only / full marking_kernel, all on the SAME uploaded
primes per case, so the comparison isn't confounded by re-uploading or re-generating primes
between variants):

  SWEEP A -- fixed combined_size=10**8 (matching the real 20M-prime data point), n_primes
             sweeping 3,417 / 20,000 / 200,000 / 2,000,000 / 20,000,000 (includes both
             original real data points' primes counts for continuity). Isolates whether cost
             scales with block count.

  SWEEP B -- fixed n_primes=20,000,000 (matching the real throughput-mode sample), combined_size
             sweeping 10**6 / 10**7 / 10**8. Isolates whether cost scales with per-block real
             marking work (which should grow with combined_size, since more small-prime hits
             land in a bigger window) independent of block count.

Usage (inside WSL2, after building via build_and_run_overhead.sh):
    python3 marking_overhead_poc.py [--binary ./marking_overhead_poc]
"""
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
DEFAULT_BINARY = os.path.join(_SCRIPT_DIR, "marking_overhead_poc")

_prime_cache = {}


def build_sample_primes(sample_n):
    """Cached (by sample_n) so SWEEP A/B don't regenerate the same 20,000,000-prime sample
    multiple times -- generation itself takes a couple seconds and is unrelated to what this
    script is trying to measure."""
    if sample_n in _prime_cache:
        return _prime_cache[sample_n]
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
    max_prime = max(primes) if primes else 0
    if max_prime >= (1 << MAX_SAFE_PRIME_BITS):
        primes = [p for p in primes if p < (1 << MAX_SAFE_PRIME_BITS)]
        print(f"[!] Truncated to {len(primes):,} primes below the "
              f"2^{MAX_SAFE_PRIME_BITS} safe limit.")
    _prime_cache[sample_n] = primes
    return primes


def write_input(path, cases):
    """cases: list of (primes_list, distance_hi, distance_lo, combined_size)."""
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(cases)))
        for primes, dh, dl, cs in cases:
            f.write(struct.pack("<Q", len(primes)))
            f.write(struct.pack(f"<{len(primes)}Q", *primes))
            f.write(struct.pack("<QQQ", dh, dl, cs))


def read_output(path, n_cases):
    results = []
    with open(path, "rb") as f:
        (n_cases_out,) = struct.unpack("<Q", f.read(8))
        assert n_cases_out == n_cases
        for _ in range(n_cases):
            n_primes, combined_size = struct.unpack("<QQ", f.read(16))
            null_ms, phase_ms, mark_ms = struct.unpack("<ddd", f.read(24))
            results.append((n_primes, combined_size, null_ms, phase_ms, mark_ms))
    return results


def run_sweep(binary, tag, cases):
    in_path = os.path.join(_SCRIPT_DIR, f"_overhead_input_{tag}.bin")
    out_path = os.path.join(_SCRIPT_DIR, f"_overhead_output_{tag}.bin")
    write_input(in_path, cases)
    result = subprocess.run([binary, in_path, out_path], capture_output=True, text=True)
    print(result.stderr, end="")
    try:
        os.remove(in_path)
    except OSError:
        pass  # known FUSE-mount quirk on some Windows-mounted dev folders -- harmless
    if result.returncode != 0:
        raise RuntimeError(f"GPU binary exited with code {result.returncode}")
    results = read_output(out_path, len(cases))
    try:
        os.remove(out_path)
    except OSError:
        pass
    return results


def print_table(results):
    print(f"{'n_primes':>12} {'combined_size':>14} {'null(ms)':>10} {'phase_only(ms)':>15} "
          f"{'full(ms)':>10} {'redundant_phase':>16} {'real_marking':>13}")
    for n_primes, combined_size, null_ms, phase_ms, mark_ms in results:
        print(f"{n_primes:>12,} {combined_size:>14,} {null_ms:>10.4f} {phase_ms:>15.4f} "
              f"{mark_ms:>10.4f} {phase_ms - null_ms:>16.4f} {mark_ms - phase_ms:>13.4f}")


def main():
    binary = DEFAULT_BINARY
    if "--binary" in sys.argv:
        binary = sys.argv[sys.argv.index("--binary") + 1]

    floor = 25
    distance = 10 ** floor
    distance_hi, distance_lo = distance >> 64, distance & MASK64

    print("=" * 88)
    print("SWEEP A -- fixed combined_size=10**8, varying n_primes (isolates block-count cost)")
    print("=" * 88)
    n_primes_values = [3_417, 20_000, 200_000, 2_000_000, 20_000_000]
    combined_size_a = 10 ** 8
    cases_a = []
    for n in n_primes_values:
        primes = build_sample_primes(n)
        cases_a.append((primes, distance_hi, distance_lo, combined_size_a))
    results_a = run_sweep(binary, "sweepA", cases_a)
    print()
    print_table(results_a)

    print()
    print("=" * 88)
    print("SWEEP B -- fixed n_primes=20,000,000, varying combined_size (isolates per-block work)")
    print("=" * 88)
    combined_size_values = [10 ** 6, 10 ** 7, 10 ** 8]
    primes_20m = build_sample_primes(20_000_000)
    cases_b = [(primes_20m, distance_hi, distance_lo, cs) for cs in combined_size_values]
    results_b = run_sweep(binary, "sweepB", cases_b)
    print()
    print_table(results_b)

    print()
    print("=" * 88)
    print("INTERPRETATION GUIDE (read the two tables above together):")
    print("  - If 'null(ms)' in SWEEP A grows roughly with n_primes -> launch/scheduling")
    print("    overhead is real and scales with block count. This is the GPU's own per-block")
    print("    dispatch cost, not something marking_kernel's code can remove.")
    print("  - If 'redundant_phase' in SWEEP A grows with n_primes but 'real_marking' stays")
    print("    small -> the 256x-redundant phase_mod_gpu computation (all threads in a block")
    print("    compute the same value) is a real, FIXABLE cost -- worth changing to compute")
    print("    once in thread 0, __syncthreads(), broadcast via shared memory.")
    print("  - If 'real_marking' in SWEEP B grows with combined_size while null/phase_only")
    print("    stay flat -> confirms the actual stride-marking loop cost scales as expected")
    print("    with window size, independent of the other two effects.")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    sys.exit(main())
