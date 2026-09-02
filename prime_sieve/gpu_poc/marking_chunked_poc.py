"""marking_chunked_poc.py -- host harness for marking_chunked_poc.cu (fifth-step GPU PoC:
combining chunked/streaming prime generation with the real, fixed marking kernel into one
VRAM-bounded, single-process pipeline -- see that file's own header for the full design
rationale, and why this needed a new file rather than reusing phase_mod_chunked_poc.py's
separate-process-per-chunk approach).

THREE MODES:

  EXACT mode -- correctness. Several small-to-medium cases, each run with a DELIBERATELY small
  `chunk_size` (as low as 50) so even a tiny prime range gets split into several chunks,
  exercising the multi-chunk accumulation path. Each case's final, chunked-and-accumulated
  output is compared byte-for-byte against calling the real, unmodified
  prime_sieve_engine_v4.c's generate_and_sieve_segment_bits() ONCE over the full [2, l_final)
  range -- the strongest available check that splitting into chunks changes nothing about the
  result. Includes the same guard-exercising edge cases used throughout this PoC series.

  STRESS mode -- one large-scale run: a big enough `l_final` that hundreds of millions of real
  sieving primes get generated and processed, with `chunk_size` fixed at 20,000,000 (matching
  the scale established in earlier steps). This is the first test in the whole PoC series that
  actually exercises the ORIGINAL motivating problem directly: a real floor-25 batch's full
  sieving-prime range does not fit in 12 GB VRAM, and this proves the chunked design keeps GPU
  memory usage flat regardless of how many total primes are processed (see the binary's own
  stderr output for the "allocated once, resident for the whole run" line -- confirms VRAM use
  is bounded by chunk_size, not total_primes, exactly once, right after allocation, not
  re-measured per chunk since it does not change).

  FULL mode -- (added 2026-08-28) the actual, real floor-25 scale, not a smaller stand-in range.
  distance=10**25, combined_size=10**10 (matching the real production benchmark span: 1000
  windows x 10**7), l_final = isqrt(distance+combined_size)+1 ~= 3.16*10**12, ~113.8 billion
  real sieving primes expected. Explicitly opt-in (`--mode full`, not part of "both") since this
  is expected to take real minutes -- see run_full_scale_mode()'s own docstring for the full
  rationale, the honest pre-run time estimate, and why a naive extrapolation from STRESS mode's
  own numbers would be unreliable.

Usage (inside WSL2, after building via build_and_run_chunked_marking.sh):
    python3 marking_chunked_poc.py [--binary ./marking_chunked_poc]
                                    [--engine-so ../prime_sieve_engine_v4.so]
                                    [--mode exact|stress|full|both]
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
DEFAULT_BINARY = os.path.join(_SCRIPT_DIR, "marking_chunked_poc")


def write_input(path, l_final, distance_hi, distance_lo, combined_size, chunk_size):
    with open(path, "wb") as f:
        f.write(struct.pack("<QQQQQ", l_final, distance_hi, distance_lo, combined_size,
                             chunk_size))


def read_output(path):
    with open(path, "rb") as f:
        (combined_bytes,) = struct.unpack("<Q", f.read(8))
        bits = f.read(combined_bytes)
        total_primes, n_chunks = struct.unpack("<QQ", f.read(16))
        timings = struct.unpack("<ddddd", f.read(40))
    return bits, total_primes, n_chunks, timings


def run_gpu(binary, l_final, distance_hi, distance_lo, combined_size, chunk_size, tag):
    in_path = os.path.join(_SCRIPT_DIR, f"_chunked_marking_input_{tag}.bin")
    out_path = os.path.join(_SCRIPT_DIR, f"_chunked_marking_output_{tag}.bin")
    write_input(in_path, l_final, distance_hi, distance_lo, combined_size, chunk_size)
    result = subprocess.run([binary, in_path, out_path], capture_output=True, text=True)
    print(result.stderr, end="")
    try:
        os.remove(in_path)
    except OSError:
        pass  # known FUSE-mount quirk on some Windows-mounted dev folders -- harmless
    if result.returncode != 0:
        raise RuntimeError(f"GPU binary exited with code {result.returncode}")
    bits, total_primes, n_chunks, timings = read_output(out_path)
    try:
        os.remove(out_path)
    except OSError:
        pass
    return bits, total_primes, n_chunks, timings


# -------------------------------------------------------------------------------------------
# Ground truth: the real, unmodified production engine, called via ctypes (same helper pattern
# as marking_poc.py -- see that file for why this is the strongest available check).
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
               chunk_size):
    gpu_bits, total_primes, n_chunks, timings = run_gpu(
        binary, l_final, distance_hi, distance_lo, combined_size, chunk_size, tag)
    truth_bits = run_engine_ground_truth(lib, l_final, distance_hi, distance_lo, combined_size)

    n_bytes = (combined_size + 7) // 8
    gpu_bits = gpu_bits[:n_bytes]
    mismatches = sum(1 for a, b in zip(gpu_bits, truth_bits) if a != b)
    status = "PASS" if mismatches == 0 else f"FAIL ({mismatches} mismatched bytes)"
    print(f"    [{name}] {status}  ({total_primes:,} primes across {n_chunks} chunks "
          f"of up to {chunk_size:,}, combined_size={combined_size:,})")
    return mismatches == 0


def run_exact_mode(binary, engine_so_path):
    print("=" * 78)
    print("EXACT mode -- chunked+accumulated output vs. a single unchunked real-engine call")
    print("=" * 78)
    lib = load_engine(engine_so_path)

    cases = [
        # (tag, name, l_final, distance_hi, distance_lo, combined_size, chunk_size)
        ("case1", "distance=0, self-elim guard, forced into ~4 tiny chunks",
         1000, 0, 0, 10_000, 50),
        ("case2", "medium range, forced into ~13 chunks",
         10_000, 0, 10 ** 9, 10 ** 6, 100),
        ("case3", "realistic floor-9-like batch, forced into ~7 chunks",
         31_781, 0, 10 ** 9, 10 ** 7, 500),
        ("case4", "distance_hi != 0 (u128 branch), forced into ~7 chunks",
         31_781, 1, 12_345, 10 ** 7, 500),
        ("case5", "chunk_size larger than total primes (single chunk, degenerate case)",
         1000, 0, 0, 10_000, 10_000),
    ]
    all_pass = True
    for tag, name, l_final, dh, dl, cs, chunk in cases:
        ok = exact_case(binary, lib, tag, name, l_final, dh, dl, cs, chunk)
        all_pass = all_pass and ok
    return all_pass


# -------------------------------------------------------------------------------------------
# STRESS mode
# -------------------------------------------------------------------------------------------

def run_stress_mode(binary):
    print()
    print("=" * 78)
    print("STRESS mode -- large-scale real sieving-prime range, VRAM-bounded streaming")
    print("=" * 78)
    floor = 25
    distance = 10 ** floor
    distance_hi, distance_lo = distance >> 64, distance & MASK64
    l_final = 20_000_000_000       # pi(2*10^10) ~ 8.8*10^8 real sieving primes
    combined_size = 10 ** 8
    chunk_size = 20_000_000

    print(f"[*] l_final={l_final:,} (expect roughly 8-9*10^8 real primes -- exact count is "
          f"whatever the binary's own stderr reports, not assumed here)")
    print(f"    combined_size={combined_size:,}  chunk_size={chunk_size:,} "
          f"(VRAM for the primes buffer should stay at ~{chunk_size * 8 / 1e6:.1f} MB "
          f"regardless of total chunks processed -- see the binary's own 'allocated once' "
          f"line above)")

    bits, total_primes, n_chunks, timings = run_gpu(
        binary, l_final, distance_hi, distance_lo, combined_size, chunk_size, "stress")
    t_generate, t_upload, t_kernel, t_download, t_total = timings

    total_bits_set = int.from_bytes(bits, "little").bit_count()
    density = total_bits_set / combined_size

    print()
    print(f"  total primes processed: {total_primes:,} across {n_chunks} chunks")
    print(f"  generate (CPU, cumulative):  {t_generate:.3f}s")
    print(f"  upload (GPU, cumulative):    {t_upload:.3f}s")
    print(f"  kernel (GPU, cumulative):    {t_kernel:.3f}s")
    print(f"  download (single, at end):   {t_download:.3f}s")
    print(f"  TOTAL:                       {t_total:.3f}s")
    print(f"  marked-composite density: {density:.4%} (sanity check -- should be close to "
          f"100% at this scale, since l_final now covers the REAL sieving-prime range, not a "
          f"small sample as in earlier steps' throughput tests)")


def run_full_scale_mode(binary):
    """FULL mode (2026-08-28, added after STRESS mode's success): the actual real floor-25
    scale, not just "large enough to prove VRAM stays flat" -- Artur explicitly asked for the
    real number here rather than the earlier extrapolation (which flagged that generation cost
    scales with the SWEPT NUMERIC RANGE, not linearly with prime count, since primesieve's cost
    is ~O(n loglog n) -- true floor 25 sweeps a ~158x larger range than STRESS mode's
    l_final=2*10^10 despite "only" ~129x more primes, so naive linear scaling from STRESS
    mode's own numbers would have been unreliable; this mode measures the real thing instead).

    l_final = isqrt(distance + combined_size) + 1, matching production's own main_batch_
    scanner() convention (see prime_sieve_v4_1.py). combined_size=10**10 matches the real
    "10 billion numbers" floor-25 benchmark span this whole PoC series has been comparing
    against throughout (see benchmark_report_20260816_120741.pdf's floor 25 row: 113.352s
    sieve + 62.666s write = 176.018s total -- THIS run's TOTAL is the first number in the
    entire series directly comparable to that, at the real scale, not a sample or a smaller
    range).

    Expected scale: ~1.138*10^11 real sieving primes (pi(3.16*10^12) via x/(ln(x)-1)), ~5691
    chunks at chunk_size=20,000,000 -- NOT run as part of --mode both, since this is
    expected to take real minutes (rough pre-run estimate from STRESS mode's own numbers,
    scaled by swept-range for generation and by prime-count for kernel: ~9 minutes generate +
    ~9 minutes kernel, order-of-magnitude only, not a promise -- that uncertainty is exactly
    why this mode exists instead of trusting the estimate)."""
    print()
    print("=" * 78)
    print("FULL mode -- REAL floor-25 scale (not a sample, not a smaller range)")
    print("=" * 78)
    import math
    floor = 25
    distance = 10 ** floor
    distance_hi, distance_lo = distance >> 64, distance & MASK64
    combined_size = 10 ** 10
    l_final = math.isqrt(distance + combined_size) + 1
    chunk_size = 20_000_000

    approx_pi = l_final / (math.log(l_final) - 1)
    print(f"[*] floor={floor}  l_final={l_final:,} (isqrt(distance+combined_size)+1, matching "
          f"production's own L_final convention)")
    print(f"    combined_size={combined_size:,} (matches the real floor-25 benchmark span: "
          f"1000 windows x 10^7)")
    print(f"    chunk_size={chunk_size:,}  ~{approx_pi:,.0f} primes expected "
          f"(~{approx_pi / chunk_size:,.0f} chunks)")
    print(f"    this WILL take real minutes -- see the module docstring for the honest, "
          f"clearly-uncertain pre-run estimate")

    bits, total_primes, n_chunks, timings = run_gpu(
        binary, l_final, distance_hi, distance_lo, combined_size, chunk_size, "full")
    t_generate, t_upload, t_kernel, t_download, t_total = timings

    # NOTE (2026-08-28): at this mode's real scale, `bits` is ~1.25 GB (combined_size=10**10).
    # The naive `sum(bin(b).count("1") for b in bits)` used in run_stress_mode is fine at
    # STRESS mode's ~12.5 MB, but would cost real extra minutes of pure-Python per-byte looping
    # here on top of an already-long GPU run. `int.from_bytes(...).bit_count()` does the same
    # popcount via CPython's C-level bigint code and finishes in ~2s even at this size.
    total_bits_set = int.from_bytes(bits, "little").bit_count()
    density = total_bits_set / combined_size

    print()
    print(f"  total primes processed: {total_primes:,} across {n_chunks} chunks")
    print(f"  generate (CPU, cumulative):  {t_generate:.3f}s")
    print(f"  upload (GPU, cumulative):    {t_upload:.3f}s")
    print(f"  kernel (GPU, cumulative):    {t_kernel:.3f}s")
    print(f"  download (single, at end):   {t_download:.3f}s")
    print(f"  TOTAL:                       {t_total:.3f}s")
    print(f"  marked-composite density: {density:.4%}")
    print()
    print(f"  DIRECT COMPARISON -- the real 2026-08-16 floor-25 benchmark at this exact same "
          f"combined_size (1000 windows x 10^7): 113.352s sieve + 62.666s write = 176.018s "
          f"total (CPU, single-threaded-per-batch across 24 workers). This run's TOTAL "
          f"({t_total:.3f}s) is GPU marking + single-threaded CPU generation on ONE thread -- "
          f"not yet including write-to-disk, and not yet using the CPU-parallel-generation "
          f"axis (still deferred, see README) -- so this is a meaningful checkpoint, not a "
          f"final apples-to-apples number yet.")


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
    if mode in ("stress", "both"):
        run_stress_mode(binary)
    if mode == "full":
        # deliberately NOT part of "both" -- this is the real floor-25 scale, expected to take
        # real minutes, so it must be explicitly requested (see run_full_scale_mode's own
        # docstring for the full rationale)
        run_full_scale_mode(binary)

    print()
    print("=" * 78)
    print("RESULT:", "PASS" if ok else "FAIL -- see mismatches above")
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
