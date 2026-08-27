"""phase_mod_poc.py -- host-side harness for phase_mod_poc.cu.

IMPORTANT SCALE NOTE (read this before running at a floor above ~16): the TRUE number of
sieving primes needed for a real floor-F run is pi(L_final) where L_final = isqrt(10**F) + 1
(see prime_sieve_v4.py's own L_final formula, which this harness reuses exactly). That count
grows enormously with F -- pi(L_final) is already ~5.76 million at floor 16 (matches the real
`Active sieving primes used (pi(L_final)): 5,761,455` line PrimeAtlas itself has printed
before), but reaches roughly ~1*10^8 at floor 20 and an estimated ~1*10^11 at floor 25.
Materializing that many actual prime VALUES (8 bytes each) is not something any machine can do
in memory at floor 25 (it would be on the order of 800+ GB) -- and this harness does not try
to. Instead it generates a bounded, real SAMPLE of the smallest N primes (--sample-n, default
20,000,000) via primesieve, runs the GPU kernel and the Python reference on that sample, and
SEPARATELY reports the true estimated pi(L_final) for the requested floor (via
count_primes_in_range(), which counts without materializing -- still a real sieve pass, so it
is skipped by default above floor 18 unless you pass --count-true-total; see that flag's own
note below) purely for context, so you can see both "does the branch-free math check out and
what's the per-prime throughput" (from the sample) and "how many of these would a real run at
this floor actually need" (the true total) side by side, without this script trying to do
something physically impossible.

Per-prime cost in the GPU kernel does NOT depend on the prime's magnitude (see phase_mod_poc.cu
-- the instruction sequence is the same fixed length for every thread regardless of p or
distance), so a sample of the smallest N primes is just as representative of per-prime
throughput as sampling near the top of L_final would be; only the correctness check benefits
from using real primes at all (vs. arbitrary uint64 test values), which this harness does.

Usage (inside WSL2, after building phase_mod_poc via build_and_run.sh):
    python3 phase_mod_poc.py <floor> [--binary ./phase_mod_poc] [--sample-n N]
                              [--count-true-total]

Example:
    python3 phase_mod_poc.py 16
    python3 phase_mod_poc.py 25 --sample-n 50000000
    python3 phase_mod_poc.py 25 --count-true-total   # WARNING: can take real time at this
                                                       # floor -- see count_primes_in_range()'s
                                                       # own docstring in prime_sieve_primesieve.py

Exits 0 if every phase matched exactly, 1 otherwise.
"""
import math
import os
import struct
import subprocess
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PRIME_SIEVE_DIR = os.path.dirname(_SCRIPT_DIR)   # prime_sieve/, one level up from gpu_poc/
sys.path.insert(0, _PRIME_SIEVE_DIR)

import prime_sieve_primesieve as cpu_primesieve  # noqa: E402

MAX_SAFE_PRIME_BITS = 50   # must match PHASE_MOD_MAX_SAFE_PRIME_BITS in phase_mod_poc.cu
DEFAULT_SAMPLE_N = 20_000_000
# Above this floor, --count-true-total is refused unless explicitly forced, matching the same
# caution prime_sieve_v4.py's own count_sieving_primes() call site takes ("SKIPPED" print,
# see that file) -- this single count call is a real sieve pass over the whole [0, L_final]
# range, not an O(1) lookup.
COUNT_TRUE_TOTAL_FLOOR_WARN = 18


def l_final_for_floor(floor):
    """Exactly prime_sieve_v4.py's own formula: L_final = isqrt(combined_hi) + 1, with
    combined_hi approximated here as 10**floor (the window's own width is negligible next to
    10**floor for any floor this project runs at -- see that file's own comment on L_final
    growing far slower than the floor's windows do)."""
    return math.isqrt(10 ** floor) + 1


def build_sample_primes(sample_n):
    """The smallest `sample_n` real primes, via primesieve. Fast and small regardless of
    floor -- see module docstring for why this is a valid stand-in for a full floor's sieving
    primes when it comes to testing per-prime GPU throughput."""
    # Rough upper bound for the sample_n-th prime via the prime number theorem, with generous
    # headroom, then trimmed to exactly sample_n after generation.
    if sample_n < 10:
        upper = 30
    else:
        upper = int(sample_n * (math.log(sample_n) + math.log(math.log(sample_n)))) + 1000
    print(f"[*] Generating the smallest {sample_n:,} primes via primesieve "
          f"(upper bound guess: {upper:,})...")
    t0 = time.perf_counter()
    primes = cpu_primesieve.generate_primes_in_range(2, upper)
    while len(primes) < sample_n:
        upper *= 2
        primes = cpu_primesieve.generate_primes_in_range(2, upper)
    primes = primes[:sample_n]
    dt = time.perf_counter() - t0
    print(f"    -> {len(primes):,} primes in {dt:.3f}s")
    return primes


def write_input_file(path, distance_hi, distance_lo, primes):
    with open(path, "wb") as f:
        f.write(struct.pack("<QQQ", distance_hi, distance_lo, len(primes)))
        f.write(struct.pack(f"<{len(primes)}Q", *primes))


def read_output_file(path, n):
    with open(path, "rb") as f:
        (n_out,) = struct.unpack("<Q", f.read(8))
        assert n_out == n, f"output n mismatch: expected {n}, got {n_out}"
        phases = struct.unpack(f"<{n}Q", f.read(8 * n))
        kernel_seconds, total_gpu_seconds = struct.unpack("<dd", f.read(16))
    return list(phases), kernel_seconds, total_gpu_seconds


def cpu_reference_phases(distance, primes):
    """Ground truth: Python's own arbitrary-precision modulo. ALSO timed as a rough CPU
    baseline -- see README.md's 'What this does NOT prove' section for why this is not a fair
    apples-to-apples comparison against the C engine's phase_mod()."""
    t0 = time.perf_counter()
    phases = [distance % p for p in primes]
    dt = time.perf_counter() - t0
    return phases, dt


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    floor = int(sys.argv[1])
    binary = "./phase_mod_poc"
    if "--binary" in sys.argv:
        binary = sys.argv[sys.argv.index("--binary") + 1]
    sample_n = DEFAULT_SAMPLE_N
    if "--sample-n" in sys.argv:
        sample_n = int(sys.argv[sys.argv.index("--sample-n") + 1])
    count_true_total = "--count-true-total" in sys.argv

    distance = 10 ** floor
    distance_hi = distance >> 64
    distance_lo = distance & ((1 << 64) - 1)
    l_final = l_final_for_floor(floor)
    print(f"[*] floor={floor}  distance=10^{floor}={distance:,}")
    print(f"    distance_hi={distance_hi}  distance_lo={distance_lo}")
    print(f"    L_final (true sieving-prime ceiling for this floor) = {l_final:,}")

    if count_true_total:
        if floor > COUNT_TRUE_TOTAL_FLOOR_WARN:
            print(f"[!] floor {floor} > {COUNT_TRUE_TOTAL_FLOOR_WARN}: counting pi(L_final) is "
                  f"a real sieve pass over [0, {l_final:,}] and can take real wall-clock time "
                  f"(minutes, per prime_sieve_v4.py's own comment on this same call) -- "
                  f"proceeding anyway since --count-true-total was explicitly passed.")
        print(f"[*] Counting true pi(L_final) via count_primes_in_range() "
              f"(this does NOT materialize the primes, but is still a real sieve pass)...")
        t0 = time.perf_counter()
        true_total = cpu_primesieve.count_primes_in_range(0, l_final)
        dt = time.perf_counter() - t0
        print(f"    -> true pi(L_final) = {true_total:,}  (counted in {dt:.3f}s)")
    else:
        true_total = None
        print(f"[*] Skipping true pi(L_final) count (pass --count-true-total to get it) -- "
              f"using sample_n={sample_n:,} for the actual GPU/CPU test below.")

    primes = build_sample_primes(sample_n)
    max_prime = max(primes) if primes else 0
    safe_limit = 1 << MAX_SAFE_PRIME_BITS
    if max_prime >= safe_limit:
        # Sample primes are always the SMALLEST N primes (see build_sample_primes), so this
        # should never trigger in practice for any reasonable --sample-n -- kept as a guard
        # rather than silently trusting that assumption forever.
        over = [p for p in primes if p >= safe_limit]
        print(f"[!] {len(over):,} of {len(primes):,} sample primes are >= 2^{MAX_SAFE_PRIME_BITS}"
              f" -- see phase_mod_poc.cu's own 'VALIDATED RANGE' comment. Truncating.")
        primes = [p for p in primes if p < safe_limit]
        if not primes:
            print("[!] No primes left after truncation.")
            return 1

    in_path = os.path.join(_SCRIPT_DIR, f"_poc_input_floor{floor}.bin")
    out_path = os.path.join(_SCRIPT_DIR, f"_poc_output_floor{floor}.bin")
    write_input_file(in_path, distance_hi, distance_lo, primes)

    print(f"[*] Running GPU kernel ({binary}) on {len(primes):,} sample primes...")
    result = subprocess.run([binary, in_path, out_path], capture_output=True, text=True)
    print(result.stderr, end="")
    if result.returncode != 0:
        print(f"[!] GPU binary exited with code {result.returncode}")
        return 1

    gpu_phases, kernel_seconds, total_gpu_seconds = read_output_file(out_path, len(primes))

    print("[*] Computing CPU reference (Python arbitrary-precision %) on the same sample...")
    cpu_phases, cpu_seconds = cpu_reference_phases(distance, primes)

    mismatches = [(i, p, gpu_phases[i], cpu_phases[i])
                  for i, p in enumerate(primes) if gpu_phases[i] != cpu_phases[i]]

    print()
    print("=" * 78)
    print(f"floor {floor}: sample of {len(primes):,} primes "
          f"(true pi(L_final) for this floor = "
          f"{'{:,}'.format(true_total) if true_total is not None else 'not counted, see above'})")
    print(f"  GPU kernel-only:       {kernel_seconds:.6f}s  "
          f"({len(primes) / max(kernel_seconds, 1e-9):,.0f} primes/s)")
    print(f"  GPU incl. PCIe xfer:   {total_gpu_seconds:.6f}s  "
          f"({len(primes) / max(total_gpu_seconds, 1e-9):,.0f} primes/s)")
    print(f"  CPU (Python, ref):     {cpu_seconds:.6f}s  "
          f"({len(primes) / max(cpu_seconds, 1e-9):,.0f} primes/s)")
    if true_total is not None:
        est_gpu = true_total / max(len(primes) / max(total_gpu_seconds, 1e-9), 1e-9)
        print(f"  -> extrapolated (sample throughput x true pi(L_final)): "
              f"~{est_gpu:.1f}s of GPU phase-computation for a real floor-{floor} run "
              f"(GPU-transfer-inclusive rate; naive linear extrapolation, see README.md for "
              f"caveats)")
    if mismatches:
        print(f"\n  FAIL: {len(mismatches):,} / {len(primes):,} phases did not match Python's "
              f"ground truth. First 5 mismatches (prime, gpu_phase, cpu_phase):")
        for i, p, g, c in mismatches[:5]:
            print(f"    prime={p}  gpu={g}  cpu={c}")
    else:
        print(f"\n  PASS: all {len(primes):,} GPU phases matched Python's ground truth exactly.")
    print("=" * 78)

    os.remove(in_path)
    os.remove(out_path)

    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
