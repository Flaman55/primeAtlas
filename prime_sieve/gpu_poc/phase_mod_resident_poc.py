"""phase_mod_resident_poc.py -- host-side harness for phase_mod_resident_poc.cu.

Follow-up to phase_mod_poc.py's real-hardware result (RTX 5070, 2026-08-28): that first PoC's
kernel-only throughput was enormous (5-6.6 billion primes/s) but wall time was ~97% PCIe
transfer, because it re-uploads the full sieving-prime sample on every single call. This
harness tests Artur's fix: upload the sample ONCE, then compute phases for MANY windows
against that same resident array in a single kernel launch, and see whether the amortized
per-window cost actually drops enough to matter.

SCALE: floor 25, window width 10**7, 1000 windows -- 1000 * 10**7 = 10**10 numbers, matching
the real "10 billion numbers in 3 minutes" floor-25 benchmark scale (see
benchmark_report_20260816_120741.pdf, floor 25 row: 113.352s sieve, 62.666s write), so the
GPU total this script reports is directly comparable to that same real run, not an arbitrary
size picked for convenience.

Correctness checking (see phase_mod_resident_poc.cu's own header for why the full
windows x primes matrix -- 160 GB at this scale -- is never materialized at all):
  1. A handful of CAPTURE_WINDOWS (first, middle, last) get their FULL phase array returned
     and checked byte-exact against Python's arbitrary-precision `%`.
  2. A random sample of CHECKSUM_VERIFY_WINDOWS additional windows gets its GPU checksum
     (unsigned 64-bit wraparound sum over all sample primes) checked against the same sum
     computed in Python -- cheap to verify many windows this way without transferring their
     full phase arrays.
  3. All remaining windows' checksums are reported but not independently verified (would mean
     doing the same expensive Python computation for all 1000 windows -- redundant once (1)
     and (2) already give strong, randomly-distributed confidence in the same kernel code path).

Usage (inside WSL2, after building via build_and_run_resident.sh):
    python3 phase_mod_resident_poc.py [--binary ./phase_mod_resident_poc]
                                       [--n-windows 1000] [--sample-n 20000000]
"""
import os
import random
import struct
import subprocess
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PRIME_SIEVE_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PRIME_SIEVE_DIR)

import prime_sieve_primesieve as cpu_primesieve  # noqa: E402

MAX_SAFE_PRIME_BITS = 50
DEFAULT_SAMPLE_N = 20_000_000
FLOOR = 25
WINDOW_WIDTH = 10 ** 7
DEFAULT_N_WINDOWS = 1000
MASK64 = (1 << 64) - 1

CAPTURE_WINDOWS = None       # set in main(): [0, n_windows // 2, n_windows - 1]
N_CHECKSUM_VERIFY = 20       # additional random windows, checksum-only verification


def build_sample_primes(sample_n):
    import math
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


def write_input_file(path, primes, distances, capture_windows):
    """`primes` may be a plain Python list/tuple of ints (struct.pack path, fine up to a few
    million elements) OR a numpy uint64 array (used by phase_mod_chunked_poc.py once it
    switched to iterator_chunk_gen.c's fill_chunk() for real streaming speed -- unpacking
    millions of individual Python ints through struct.pack's *args is itself a real cost at
    that scale, so numpy's own .tobytes() is used instead when available; same little-endian
    uint64 layout either way, byte-for-byte identical output)."""
    n_primes = len(primes)
    n_windows = len(distances)
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", n_primes))
        if hasattr(primes, "tobytes"):
            # numpy array -- MUST be uint64, little-endian, to match struct's own "<Q" layout
            f.write(primes.astype("<u8", copy=False).tobytes())
        else:
            f.write(struct.pack(f"<{n_primes}Q", *primes))
        f.write(struct.pack("<Q", n_windows))
        f.write(struct.pack(f"<{n_windows}Q", *[d >> 64 for d in distances]))
        f.write(struct.pack(f"<{n_windows}Q", *[d & MASK64 for d in distances]))
        f.write(struct.pack("<Q", len(capture_windows)))
        for w in capture_windows:
            f.write(struct.pack("<q", w))


def read_output_file(path, n_primes, n_windows, n_capture):
    with open(path, "rb") as f:
        (n_windows_out,) = struct.unpack("<Q", f.read(8))
        assert n_windows_out == n_windows
        checksums = struct.unpack(f"<{n_windows}Q", f.read(8 * n_windows))
        (n_capture_out,) = struct.unpack("<Q", f.read(8))
        assert n_capture_out == n_capture
        full_output = []
        if n_capture > 0:
            flat = struct.unpack(f"<{n_capture * n_primes}Q", f.read(8 * n_capture * n_primes))
            for c in range(n_capture):
                full_output.append(flat[c * n_primes:(c + 1) * n_primes])
        timings = struct.unpack("<dddddd", f.read(48))
    return list(checksums), full_output, timings


def main():
    n_windows = DEFAULT_N_WINDOWS
    sample_n = DEFAULT_SAMPLE_N
    binary = "./phase_mod_resident_poc"
    if "--n-windows" in sys.argv:
        n_windows = int(sys.argv[sys.argv.index("--n-windows") + 1])
    if "--sample-n" in sys.argv:
        sample_n = int(sys.argv[sys.argv.index("--sample-n") + 1])
    if "--binary" in sys.argv:
        binary = sys.argv[sys.argv.index("--binary") + 1]

    capture_windows = sorted(set([0, n_windows // 2, n_windows - 1]))
    base = FLOOR
    distances = [10 ** base + w * WINDOW_WIDTH for w in range(n_windows)]

    print(f"[*] floor={FLOOR}  window_width={WINDOW_WIDTH:,}  n_windows={n_windows:,}  "
          f"total span={n_windows * WINDOW_WIDTH:,} numbers")
    print(f"    capture (full verification) windows: {capture_windows}")

    primes = build_sample_primes(sample_n)
    max_prime = max(primes) if primes else 0
    if max_prime >= (1 << MAX_SAFE_PRIME_BITS):
        primes = [p for p in primes if p < (1 << MAX_SAFE_PRIME_BITS)]
        print(f"[!] Truncated sample to {len(primes):,} primes below the "
              f"2^{MAX_SAFE_PRIME_BITS} safe limit.")
    n_primes = len(primes)

    est_capture_mb = len(capture_windows) * n_primes * 8 / 1e6
    print(f"[*] Full-capture output size: {est_capture_mb:.1f} MB "
          f"({len(capture_windows)} windows x {n_primes:,} primes x 8 bytes)")

    in_path = os.path.join(_SCRIPT_DIR, "_resident_input.bin")
    out_path = os.path.join(_SCRIPT_DIR, "_resident_output.bin")
    write_input_file(in_path, primes, distances, capture_windows)

    print(f"[*] Running GPU kernel ({binary})...")
    result = subprocess.run([binary, in_path, out_path], capture_output=True, text=True)
    print(result.stderr, end="")
    if result.returncode != 0:
        print(f"[!] GPU binary exited with code {result.returncode}")
        return 1

    checksums, full_output, timings = read_output_file(out_path, n_primes, n_windows,
                                                          len(capture_windows))
    (t_primes_up, t_dist_up, t_kernel, t_checksum_down, t_full_down, t_total) = timings

    failures = []

    print(f"\n[*] Verifying {len(capture_windows)} captured windows byte-exact against "
          f"Python ground truth...")
    for slot, w in enumerate(capture_windows):
        t0 = time.perf_counter()
        truth = [distances[w] % p for p in primes]
        dt = time.perf_counter() - t0
        gpu_vals = full_output[slot]
        mismatches = sum(1 for i in range(n_primes) if gpu_vals[i] != truth[i])
        status = "PASS" if mismatches == 0 else f"FAIL ({mismatches:,} mismatches)"
        print(f"    window {w}: {status}  (Python ref computed in {dt:.3f}s)")
        if mismatches:
            failures.append(f"window {w} full-array mismatch")
        # cross-check the checksum for this same window too, as a consistency check between
        # the two output paths (full array vs. reduction) within the kernel itself
        truth_checksum = sum(truth) & MASK64
        if truth_checksum != checksums[w]:
            failures.append(f"window {w} checksum mismatch (gpu={checksums[w]}, "
                             f"truth={truth_checksum}) -- inconsistent with its own full array!")
            print(f"    window {w}: checksum MISMATCH vs its own full array's sum -- "
                  f"reduction bug")

    random.seed(1234)
    remaining = [w for w in range(n_windows) if w not in capture_windows]
    sample_windows = random.sample(remaining, min(N_CHECKSUM_VERIFY, len(remaining)))
    print(f"\n[*] Checksum-verifying {len(sample_windows)} additional random windows...")
    for w in sample_windows:
        truth_checksum = (sum(distances[w] % p for p in primes)) & MASK64
        status = "PASS" if truth_checksum == checksums[w] else "FAIL"
        if status == "FAIL":
            failures.append(f"window {w} checksum mismatch")
        print(f"    window {w}: {status}")

    print()
    print("=" * 78)
    print(f"floor {FLOOR}, {n_windows:,} windows x {n_primes:,} primes "
          f"({n_windows * n_primes:,} total phase computations)")
    print(f"  primes upload (ONE-TIME):     {t_primes_up:.6f}s")
    print(f"  distances upload:             {t_dist_up:.6f}s")
    print(f"  kernel:                       {t_kernel:.6f}s")
    print(f"  checksum download:            {t_checksum_down:.6f}s")
    print(f"  full-output download ({len(capture_windows)} windows): {t_full_down:.6f}s")
    print(f"  TOTAL:                        {t_total:.6f}s")
    amortized = (t_total - t_primes_up) / n_windows
    print(f"  amortized per-window (excl. one-time primes upload): {amortized * 1000:.4f}ms")
    print(f"  -> extrapolated to a real floor-25 run's {n_windows:,}-window span: "
          f"{t_total:.1f}s total GPU time (vs. {113.352:.1f}s CPU sieve + {62.666:.1f}s "
          f"write = {113.352+62.666:.1f}s from the real 2026-08-16 benchmark at this exact "
          f"floor/span)")
    if failures:
        print(f"\n  FAIL: {len(failures)} verification failures:")
        for f in failures:
            print(f"    - {f}")
    else:
        print(f"\n  PASS: all captured windows exact, all checksum-verified windows matched.")
    print("=" * 78)

    os.remove(in_path)
    os.remove(out_path)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
