"""sparse_bucketed_poc.py -- host harness for sparse_bucketed_poc.cu.

Tests whether bucket-sorting sparse-tier primes' target write positions by which shard of the
`d_bits` buffer they land in -- before doing the actual atomic writes -- improves throughput
relative to the naive scattered approach. Direct follow-up to sparse_overhead_poc's real-hardware
finding that the atomic write is 85.3% of the sparse kernel's cost (at ~19.4 GB/s effective
bandwidth, far below the GPU's likely peak, consistent with cache-hostile random access).

Sweeps a few shard sizes (in bits of the combined range) since the GPU's real L2 cache size on
Artur's hardware isn't assumed -- we let the real numbers say what shard size (if any) helps.

Usage (inside WSL2, after building via build_and_run_sparse_bucketed.sh):
    python3 sparse_bucketed_poc.py [--binary ./sparse_bucketed_poc] [--n-primes 50000000]
"""
import math
import os
import struct
import subprocess
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BINARY = os.path.join(_SCRIPT_DIR, "sparse_bucketed_poc")
MASK64 = (1 << 64) - 1

# shard sizes to sweep, in BITS of the combined [0, combined_size) range.
# First real-hardware sweep (2026-08-28, n=50M) was monotonic: EVERY component (compute,
# scatter, write) got cheaper as shard size shrank across all four sizes tried, with the
# smallest (128 KB/shard) winning by the largest margin (2.35x vs. naive). That result was
# reported BEFORE the host round-trip cost was separately timed (an earlier version of this file
# left it untimed on an unverified "negligible" assumption) -- fixed now, see sparse_bucketed_
# poc.cu's t_roundtrip. Since going smaller kept winning and we don't yet know where the
# roundtrip cost (which grows with n_buckets) starts to bite, this sweep now pushes further down
# to find the real turnover point, plus keeps the two best sizes from the first sweep as anchors.
DEFAULT_SHARD_SIZES_BITS = [
    1 << 14,   # 2 KB/shard    -> ~610,352 shards at combined_size=1e10
    1 << 16,   # 8 KB/shard    -> ~152,588 shards
    1 << 18,   # 32 KB/shard   -> ~38,147 shards
    1 << 20,   # 128 KB/shard  -> ~9,537 shards  (best from the first sweep: 2.35x)
    1 << 23,   # 1 MB/shard    -> ~1,192 shards  (second-best from the first sweep: 1.85x)
]


def write_input(path, n_primes, distance_hi, distance_lo, combined_size, sparse_lo, sparse_hi,
                 shard_sizes):
    with open(path, "wb") as f:
        f.write(struct.pack("<QQQQQQQ", n_primes, distance_hi, distance_lo, combined_size,
                             sparse_lo, sparse_hi, len(shard_sizes)))
        f.write(struct.pack(f"<{len(shard_sizes)}Q", *shard_sizes))


def read_output(path, n_shard_sizes):
    with open(path, "rb") as f:
        (naive_ms,) = struct.unpack("<d", f.read(8))
        rows = []
        for _ in range(n_shard_sizes):
            shard_size, n_buckets = struct.unpack("<QQ", f.read(16))
            t_compute, t_roundtrip, t_scatter, t_write, t_total = struct.unpack(
                "<ddddd", f.read(40))
            rows.append({
                "shard_size": shard_size, "n_buckets": n_buckets, "t_compute": t_compute,
                "t_roundtrip": t_roundtrip, "t_scatter": t_scatter, "t_write": t_write,
                "t_total": t_total,
            })
    return naive_ms, rows


def main():
    binary = DEFAULT_BINARY
    n_primes = 50_000_000
    shard_sizes = list(DEFAULT_SHARD_SIZES_BITS)
    if "--binary" in sys.argv:
        binary = sys.argv[sys.argv.index("--binary") + 1]
    if "--n-primes" in sys.argv:
        n_primes = int(sys.argv[sys.argv.index("--n-primes") + 1])

    # real floor-25 parameters, same as sparse_overhead_poc.py / marking_two_tier_poc.py FULL mode
    floor = 25
    distance = 10 ** floor
    distance_hi, distance_lo = distance >> 64, distance & MASK64
    combined_size = 10 ** 10
    l_final = math.isqrt(distance + combined_size) + 1
    sparse_lo, sparse_hi = combined_size, l_final

    print("=" * 78)
    print("sparse_bucketed_poc -- does bucket-sorting writes by shard improve locality?")
    print("=" * 78)
    print(f"[*] sampling up to {n_primes:,} real primes from [{sparse_lo:,}, {sparse_hi:,})")
    print(f"    shard sizes to sweep (bits): {shard_sizes}")

    in_path = os.path.join(_SCRIPT_DIR, "_sparse_bucketed_input.bin")
    out_path = os.path.join(_SCRIPT_DIR, "_sparse_bucketed_output.bin")
    write_input(in_path, n_primes, distance_hi, distance_lo, combined_size, sparse_lo, sparse_hi,
                shard_sizes)
    result = subprocess.run([binary, in_path, out_path], capture_output=True, text=True)
    print(result.stderr, end="")
    try:
        os.remove(in_path)
    except OSError:
        pass
    if result.returncode != 0:
        print(f"[ABORT] binary exited with code {result.returncode}")
        return 1
    naive_ms, rows = read_output(out_path, len(shard_sizes))
    try:
        os.remove(out_path)
    except OSError:
        pass

    print()
    print(f"  naive scattered write (baseline): {naive_ms:.3f} ms")
    print()
    print(f"  {'shard bits':>12}  {'shard MB':>9}  {'n_buckets':>9}  {'compute':>9}  "
          f"{'roundtrip':>9}  {'scatter':>9}  {'write':>9}  {'TOTAL':>9}  {'speedup':>8}")
    best_row = None
    for row in rows:
        speedup = naive_ms / row["t_total"]
        if best_row is None or row["t_total"] < best_row["t_total"]:
            best_row = row
        print(f"  {row['shard_size']:>12}  {row['shard_size'] / 8.0 / 1e6:>9.3f}  "
              f"{row['n_buckets']:>9}  {row['t_compute']:>9.3f}  {row['t_roundtrip']:>9.3f}  "
              f"{row['t_scatter']:>9.3f}  {row['t_write']:>9.3f}  {row['t_total']:>9.3f}  "
              f"{speedup:>7.2f}x")

    print()
    if best_row["t_total"] < naive_ms:
        print(f"  BEST: shard_size={best_row['shard_size']} bits "
              f"({best_row['shard_size'] / 8.0 / 1e6:.3f} MB) -- "
              f"{naive_ms / best_row['t_total']:.2f}x faster than naive scattered write.")
        print("  Bucketing helps -- worth integrating into marking_two_tier_poc's sparse phase.")
    else:
        print("  No shard size beat the naive scattered write. The compute+scatter overhead of "
              "the bucket-sort pipeline outweighs whatever locality gain the grouped writes get "
              "-- the atomic-write cost is likely dominated by something bucketing doesn't fix "
              "(e.g. contention on the same cache line across many concurrent warps, not cold "
              "DRAM misses), or the shard sizes tried don't match the real L2 behavior.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
