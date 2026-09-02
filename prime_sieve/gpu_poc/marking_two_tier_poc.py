"""marking_two_tier_poc.py -- host harness for marking_two_tier_poc.cu (seventh-step GPU PoC).

Direct follow-up to marking_chunked_parallel_poc's real-hardware result (TOTAL=580.386s,
generate_wall and gpu_wall nearly equal at ~579s -- confirming the pipeline had become purely
GPU-kernel-bound, with no more pipelining/parallel-generation gains available). Reading the
REAL production engine (prime_sieve_engine_v4.c) directly showed it already splits primes into
two cost tiers: `p_val >= window_m` does a single O(1) write, `p_val < window_m` does a
multi-hit marking loop. At real floor-25 scale, ~99.6% of the ~113.8 billion sieving primes fall
into the O(1) tier -- but this codebase's GPU kernel was launching a full 256-thread cooperative
block per prime regardless of tier, which is very likely the real bottleneck (measured
~4.69 ns/block from marking_overhead_poc's own post-fix numbers; 113.8e9 blocks * 4.69ns ~=
534s, matching the measured kernel time almost exactly).

This harness drives marking_two_tier_poc.cu's two-kernel design: `marking_kernel` (dense,
unchanged, one block/prime) for primes < combined_size, `sparse_kernel` (new, one thread/prime,
flat grid) for primes >= combined_size -- mirroring prime_sieve_engine_v4.c's own branch.

THREE MODES (same split as marking_chunked_parallel_poc.py):

  EXACT mode -- correctness, with cases specifically exercising: dense-only (combined_size >
  l_final, sparse phase empty), sparse-heavy (small combined_size relative to l_final), a mixed
  case, and a boundary case where combined_size is set to an actual prime value (to test the
  p == combined_size edge of the tier split). Each case's output is compared byte-for-byte
  against a single unchunked, single-threaded call to the real, unmodified
  prime_sieve_engine_v4.c.

  STRESS mode -- the same moderate-scale run as the prior two files (l_final=20,000,000,000),
  for a direct three-way comparison (serial -> parallel -> two-tier).

  FULL mode -- the real floor-25 scale. This is the number that answers whether the two-tier
  split actually closes the gap with production's 176.018s.

Usage (inside WSL2, after building via build_and_run_two_tier_marking.sh):
    python3 marking_two_tier_poc.py [--binary ./marking_two_tier_poc]
                                     [--engine-so ../prime_sieve_engine_v4.so]
                                     [--mode exact|stress|full|both]
                                     [--gen-threads N]   (default: os.cpu_count())
"""
import ctypes
import os
import struct
import subprocess
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PRIME_SIEVE_DIR = os.path.dirname(_SCRIPT_DIR)

MASK64 = (1 << 64) - 1
DEFAULT_ENGINE_SO = os.path.join(_PRIME_SIEVE_DIR, "prime_sieve_engine_v4.so")
DEFAULT_BINARY = os.path.join(_SCRIPT_DIR, "marking_two_tier_poc")


def write_input(path, l_final, distance_hi, distance_lo, combined_size, chunk_size,
                 num_gen_threads):
    with open(path, "wb") as f:
        f.write(struct.pack("<QQQQQQ", l_final, distance_hi, distance_lo, combined_size,
                             chunk_size, num_gen_threads))


def read_output(path):
    with open(path, "rb") as f:
        (combined_bytes,) = struct.unpack("<Q", f.read(8))
        bits = f.read(combined_bytes)
        (total_primes, n_dense_primes, n_sparse_primes, n_dense_chunks, n_sparse_chunks,
         n_gen_threads_used) = struct.unpack("<QQQQQQ", f.read(48))
        timings = struct.unpack("<dddddd", f.read(48))
    return bits, {
        "total_primes": total_primes,
        "n_dense_primes": n_dense_primes,
        "n_sparse_primes": n_sparse_primes,
        "n_dense_chunks": n_dense_chunks,
        "n_sparse_chunks": n_sparse_chunks,
        "n_gen_threads_used": n_gen_threads_used,
    }, timings


def run_gpu(binary, l_final, distance_hi, distance_lo, combined_size, chunk_size,
            num_gen_threads, tag):
    in_path = os.path.join(_SCRIPT_DIR, f"_two_tier_input_{tag}.bin")
    out_path = os.path.join(_SCRIPT_DIR, f"_two_tier_output_{tag}.bin")
    write_input(in_path, l_final, distance_hi, distance_lo, combined_size, chunk_size,
                num_gen_threads)
    result = subprocess.run([binary, in_path, out_path], capture_output=True, text=True)
    print(result.stderr, end="")
    try:
        os.remove(in_path)
    except OSError:
        pass
    if result.returncode != 0:
        raise RuntimeError(f"GPU binary exited with code {result.returncode}")
    bits, counts, timings = read_output(out_path)
    try:
        os.remove(out_path)
    except OSError:
        pass
    return bits, counts, timings


# -------------------------------------------------------------------------------------------
# Ground truth
# -------------------------------------------------------------------------------------------

def build_engine_so_if_missing(engine_so_path):
    if os.path.isfile(engine_so_path):
        return
    engine_c = os.path.join(_PRIME_SIEVE_DIR, "prime_sieve_engine_v4.c")
    print(f"[*] {engine_so_path} not found -- building it now...")
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


def run_engine_ground_truth(lib, l_final, distance_hi, distance_lo, combined_size):
    n_bytes = (combined_size + 7) // 8
    buf = (ctypes.c_ubyte * n_bytes)()
    ret = lib.generate_and_sieve_segment_bits(2, l_final, distance_hi, distance_lo,
                                               combined_size, buf)
    if ret != 0:
        raise RuntimeError(f"engine returned error code {ret}")
    return bytes(buf)


# -------------------------------------------------------------------------------------------
# EXACT mode
# -------------------------------------------------------------------------------------------

def exact_case(binary, lib, tag, name, l_final, distance_hi, distance_lo, combined_size,
               chunk_size, gen_threads):
    gpu_bits, counts, timings = run_gpu(
        binary, l_final, distance_hi, distance_lo, combined_size, chunk_size, gen_threads, tag)
    truth_bits = run_engine_ground_truth(lib, l_final, distance_hi, distance_lo, combined_size)

    n_bytes = (combined_size + 7) // 8
    gpu_bits = gpu_bits[:n_bytes]
    mismatches = sum(1 for a, b in zip(gpu_bits, truth_bits) if a != b)
    status = "PASS" if mismatches == 0 else f"FAIL ({mismatches} mismatched bytes)"
    print(f"    [{name}] {status}  (dense={counts['n_dense_primes']:,} "
          f"sparse={counts['n_sparse_primes']:,} primes, "
          f"combined_size={combined_size:,}, l_final={l_final:,})")
    return mismatches == 0


def run_exact_mode(binary, engine_so_path):
    print("=" * 78)
    print("EXACT mode -- two-tier (dense+sparse kernel) output vs. a single unchunked,")
    print("single-threaded real-engine call")
    print("=" * 78)
    lib = load_engine(engine_so_path)

    cases = [
        # (tag, name, l_final, distance_hi, distance_lo, combined_size, chunk_size, gen_threads)
        ("case1", "dense-only (combined_size > l_final, sparse phase empty)",
         1000, 0, 0, 10_000, 50, 2),
        ("case2", "sparse-heavy (combined_size small vs l_final)",
         10_000, 0, 10 ** 9, 100, 100, 4),
        ("case3", "mixed, realistic floor-9-like magnitude",
         31_781, 0, 10 ** 9, 5_000, 500, 4),
        ("case4", "distance_hi != 0 (u128 branch), mixed",
         31_781, 1, 12_345, 5_000, 500, 4),
        ("case5", "boundary: combined_size == an actual prime (97)",
         200, 0, 0, 97, 20, 2),
        ("case6", "requested gen-threads (16) larger than either tier's range width",
         200, 0, 0, 97, 20, 16),
        ("case7", "chunk_size larger than total primes in both tiers (degenerate)",
         1000, 0, 0, 500, 10_000, 8),
    ]
    all_pass = True
    for tag, name, l_final, dh, dl, cs, chunk, gt in cases:
        ok = exact_case(binary, lib, tag, name, l_final, dh, dl, cs, chunk, gt)
        all_pass = all_pass and ok
    return all_pass


# -------------------------------------------------------------------------------------------
# STRESS mode
# -------------------------------------------------------------------------------------------

def run_stress_mode(binary, gen_threads):
    print()
    print("=" * 78)
    print("STRESS mode -- moderate scale, two-tier kernel, for a 3-way before/after read")
    print("(serial marking_chunked_poc -> parallel marking_chunked_parallel_poc -> this)")
    print("=" * 78)
    floor = 25
    distance = 10 ** floor
    distance_hi, distance_lo = distance >> 64, distance & MASK64
    l_final = 20_000_000_000
    combined_size = 10 ** 8
    chunk_size = 20_000_000

    print(f"[*] l_final={l_final:,}  combined_size={combined_size:,}  chunk_size={chunk_size:,}"
          f"  gen_threads={gen_threads}")

    bits, counts, timings = run_gpu(
        binary, l_final, distance_hi, distance_lo, combined_size, chunk_size, gen_threads,
        "stress")
    (t_dense_gen, t_dense_gpu, t_sparse_gen, t_sparse_gpu, t_download, t_total) = timings

    total_bits_set = int.from_bytes(bits, "little").bit_count()
    density = total_bits_set / combined_size

    print()
    print(f"  primes: {counts['total_primes']:,} total "
          f"({counts['n_dense_primes']:,} dense + {counts['n_sparse_primes']:,} sparse)")
    print(f"  dense:  generate_wall={t_dense_gen:.3f}s  gpu_wall={t_dense_gpu:.3f}s")
    print(f"  sparse: generate_wall={t_sparse_gen:.3f}s  gpu_wall={t_sparse_gpu:.3f}s")
    print(f"  download: {t_download:.3f}s")
    print(f"  TOTAL:    {t_total:.3f}s")
    print(f"  marked-composite density: {density:.4%}")


def run_full_scale_mode(binary, gen_threads):
    """FULL mode (2026-08-28) -- the real floor-25 scale, now with the two-tier dense/sparse
    kernel split mirroring prime_sieve_engine_v4.c's own branch. Direct follow-up to
    marking_chunked_parallel_poc.py's FULL-mode result: TOTAL=580.386s, with generate_wall
    (579.141s) and gpu_wall (579.019s) nearly equal, confirming the pipeline had become purely
    GPU-kernel-bound with no more pipelining gains available. This is the real test of whether
    matching production's own O(1)-vs-loop tier split on the GPU actually helps.
    """
    print()
    print("=" * 78)
    print("FULL mode -- REAL floor-25 scale, two-tier dense/sparse kernel")
    print("=" * 78)
    import math
    floor = 25
    distance = 10 ** floor
    distance_hi, distance_lo = distance >> 64, distance & MASK64
    combined_size = 10 ** 10
    l_final = math.isqrt(distance + combined_size) + 1
    chunk_size = 20_000_000

    approx_pi = l_final / (math.log(l_final) - 1)
    approx_pi_dense = combined_size / (math.log(combined_size) - 1)  # rough estimate only
    print(f"[*] floor={floor}  l_final={l_final:,}  combined_size={combined_size:,}  "
          f"chunk_size={chunk_size:,}  gen_threads={gen_threads}")
    print(f"    ~{approx_pi:,.0f} primes expected total, of which ~{approx_pi_dense:,.0f} "
          f"(~{100 * approx_pi_dense / approx_pi:.2f}%) are dense-tier (< combined_size) and "
          f"the rest (~{100 * (1 - approx_pi_dense / approx_pi):.2f}%) are sparse-tier")
    print(f"    prior results for direct comparison: serial TOTAL=1316.729s, "
          f"parallel(no tier split) TOTAL=580.386s (generate_wall=579.141s, "
          f"gpu_wall=579.019s)")

    bits, counts, timings = run_gpu(
        binary, l_final, distance_hi, distance_lo, combined_size, chunk_size, gen_threads,
        "full")
    (t_dense_gen, t_dense_gpu, t_sparse_gen, t_sparse_gpu, t_download, t_total) = timings

    total_bits_set = int.from_bytes(bits, "little").bit_count()
    density = total_bits_set / combined_size

    print()
    print(f"  primes: {counts['total_primes']:,} total "
          f"({counts['n_dense_primes']:,} dense + {counts['n_sparse_primes']:,} sparse), "
          f"{counts['n_dense_chunks']} dense chunks + {counts['n_sparse_chunks']} sparse chunks, "
          f"{counts['n_gen_threads_used']} generator thread(s)")
    print(f"  dense:  generate_wall={t_dense_gen:.3f}s  gpu_wall={t_dense_gpu:.3f}s")
    print(f"  sparse: generate_wall={t_sparse_gen:.3f}s  gpu_wall={t_sparse_gpu:.3f}s")
    print(f"  download: {t_download:.3f}s")
    print(f"  TOTAL:    {t_total:.3f}s")
    print(f"  marked-composite density: {density:.4%}")
    print()
    print(f"  DIRECT COMPARISON -- production's real 2026-08-16 floor-25 benchmark: 113.352s "
          f"sieve + 62.666s write = 176.018s total (CPU, 24 workers, same combined_size). "
          f"This run's TOTAL ({t_total:.3f}s) vs. the no-tier-split parallel result (580.386s): "
          f"{580.386 / t_total:.2f}x if faster. vs. production (176.018s): "
          f"{t_total / 176.018:.2f}x slower (or faster, if < 1.0).")


def main():
    binary = DEFAULT_BINARY
    engine_so = DEFAULT_ENGINE_SO
    mode = "both"
    gen_threads = os.cpu_count() or 4
    if "--binary" in sys.argv:
        binary = sys.argv[sys.argv.index("--binary") + 1]
    if "--engine-so" in sys.argv:
        engine_so = sys.argv[sys.argv.index("--engine-so") + 1]
    if "--mode" in sys.argv:
        mode = sys.argv[sys.argv.index("--mode") + 1]
    if "--gen-threads" in sys.argv:
        gen_threads = int(sys.argv[sys.argv.index("--gen-threads") + 1])

    print(f"[*] os.cpu_count()={os.cpu_count()} -- using --gen-threads={gen_threads} for "
          f"STRESS/FULL modes (EXACT mode uses its own small, fixed per-case values)")

    ok = True
    if mode in ("exact", "both"):
        ok = run_exact_mode(binary, engine_so) and ok
    if mode in ("stress", "both"):
        run_stress_mode(binary, gen_threads)
    if mode == "full":
        run_full_scale_mode(binary, gen_threads)

    print()
    print("=" * 78)
    print("RESULT:", "PASS" if ok else "FAIL -- see mismatches above")
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
