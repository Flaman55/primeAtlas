"""sparse_overhead_poc.py -- host harness for sparse_overhead_poc.cu.

Decomposes the sparse_kernel's real per-prime cost (from marking_two_tier_poc.cu) into
dispatch overhead / phase computation (old vs. the 2026-08-28 fast-path fix) / atomic write,
at real floor-25 sparse-tier scale -- built to directly answer Artur's question about where the
GPU kernel still adds overhead relative to the CPU's single-`divq`-instruction phase_mod.

Usage (inside WSL2, after building via build_and_run_sparse_overhead.sh):
    python3 sparse_overhead_poc.py [--binary ./sparse_overhead_poc] [--n-primes 50000000]
"""
import math
import os
import struct
import subprocess
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BINARY = os.path.join(_SCRIPT_DIR, "sparse_overhead_poc")
MASK64 = (1 << 64) - 1


def write_input(path, n_primes, distance_hi, distance_lo, combined_size, sparse_lo, sparse_hi):
    with open(path, "wb") as f:
        f.write(struct.pack("<QQQQQQ", n_primes, distance_hi, distance_lo, combined_size,
                             sparse_lo, sparse_hi))


def read_output(path):
    with open(path, "rb") as f:
        null_ms, phase_old_ms, phase_new_ms, full_ms = struct.unpack("<dddd", f.read(32))
        (actual_n,) = struct.unpack("<Q", f.read(8))
    return null_ms, phase_old_ms, phase_new_ms, full_ms, actual_n


def main():
    binary = DEFAULT_BINARY
    n_primes = 50_000_000
    if "--binary" in sys.argv:
        binary = sys.argv[sys.argv.index("--binary") + 1]
    if "--n-primes" in sys.argv:
        n_primes = int(sys.argv[sys.argv.index("--n-primes") + 1])

    # real floor-25 parameters, same as marking_two_tier_poc.py's FULL mode
    floor = 25
    distance = 10 ** floor
    distance_hi, distance_lo = distance >> 64, distance & MASK64
    combined_size = 10 ** 10
    l_final = math.isqrt(distance + combined_size) + 1
    sparse_lo, sparse_hi = combined_size, l_final

    print("=" * 78)
    print("sparse_kernel cost decomposition -- real floor-25 sparse-tier primes")
    print("=" * 78)
    print(f"[*] sampling up to {n_primes:,} real primes from [{sparse_lo:,}, {sparse_hi:,})")
    print(f"    distance_hi={distance_hi}  distance_lo={distance_lo}  "
          f"combined_size={combined_size:,}")

    in_path = os.path.join(_SCRIPT_DIR, "_sparse_overhead_input.bin")
    out_path = os.path.join(_SCRIPT_DIR, "_sparse_overhead_output.bin")
    write_input(in_path, n_primes, distance_hi, distance_lo, combined_size, sparse_lo, sparse_hi)
    result = subprocess.run([binary, in_path, out_path], capture_output=True, text=True)
    print(result.stderr, end="")
    try:
        os.remove(in_path)
    except OSError:
        pass
    if result.returncode != 0:
        print(f"[ABORT] binary exited with code {result.returncode}")
        return 1
    null_ms, phase_old_ms, phase_new_ms, full_ms, actual_n = read_output(out_path)
    try:
        os.remove(out_path)
    except OSError:
        pass

    print()
    print(f"  actual primes used: {actual_n:,}")
    print(f"  null (dispatch only):        {null_ms:.3f} ms")
    print(f"  phase_old (pre-fix formula): {phase_old_ms:.3f} ms")
    print(f"  phase_new (post-fix formula):{phase_new_ms:.3f} ms")
    print(f"  full (phase_new + write):    {full_ms:.3f} ms")
    print()
    dispatch = null_ms
    phase_cost_old = phase_old_ms - null_ms
    phase_cost_new = phase_new_ms - null_ms
    fix_saved = phase_old_ms - phase_new_ms
    write_cost = full_ms - phase_new_ms
    print("  DECOMPOSITION (of the full per-run cost):")
    print(f"    dispatch/launch overhead: {dispatch:.3f} ms "
          f"({100 * dispatch / full_ms:.1f}% of full)")
    print(f"    phase computation (new):  {phase_cost_new:.3f} ms "
          f"({100 * phase_cost_new / full_ms:.1f}% of full)")
    print(f"    atomic write:             {write_cost:.3f} ms "
          f"({100 * write_cost / full_ms:.1f}% of full)")
    print(f"    2026-08-28 fast-path fix saved: {fix_saved:.3f} ms "
          f"({100 * fix_saved / phase_old_ms:.1f}% of the OLD phase cost) -- this is the "
          f"per-prime win from skipping the wasted distance_hi %% p division")
    print(f"  per-prime rate (full, post-fix): {actual_n / (full_ms / 1000.0) / 1e9:.4f} "
          f"billion primes/s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
