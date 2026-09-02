"""marking_chunked_parallel_poc.py -- host harness for marking_chunked_parallel_poc.cu (sixth-
step GPU PoC, built directly off marking_chunked_poc's real-hardware FULL-mode result: TOTAL=
1316.729s vs production's 176.018s, ~7.5x slower, with single-threaded CPU generation (670.5s)
as the single biggest cost and ZERO overlap between generate/upload/kernel. Rather than leave
that as speculation ("if we parallelized generation and pipelined it, maybe..."), this harness
drives the new .cu file that actually does both -- see that file's own header for the full
design. This is the real, finished attempt Artur asked for, not an estimate.

THREE MODES (same split as marking_chunked_poc.py):

  EXACT mode -- correctness, INCLUDING cases that specifically exercise multiple generator
  threads (not just multiple GPU chunks, which marking_chunked_poc.py's EXACT mode already
  covered). Each case's final output is compared byte-for-byte against calling the real,
  unmodified prime_sieve_engine_v4.c's generate_and_sieve_segment_bits() ONCE over the full
  [2, l_final) range.

  STRESS mode -- the same moderate-scale run as before (l_final=20,000,000,000), now using real
  parallel generation + pipelined GPU, to see the speedup at a scale that finishes in seconds
  rather than minutes before committing to the real FULL-scale run.

  FULL mode -- the real floor-25 scale (same parameters as marking_chunked_poc.py's FULL mode:
  distance=10**25, combined_size=10**10, l_final=isqrt(distance+combined_size)+1). This is the
  real number Artur asked to see, using real parallel CPU generation (--gen-threads, default
  os.cpu_count()) and the double-buffered GPU pipeline.

Usage (inside WSL2, after building via build_and_run_chunked_marking_parallel.sh):
    python3 marking_chunked_parallel_poc.py [--binary ./marking_chunked_parallel_poc]
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
DEFAULT_BINARY = os.path.join(_SCRIPT_DIR, "marking_chunked_parallel_poc")


def write_input(path, l_final, distance_hi, distance_lo, combined_size, chunk_size,
                 num_gen_threads):
    with open(path, "wb") as f:
        f.write(struct.pack("<QQQQQQ", l_final, distance_hi, distance_lo, combined_size,
                             chunk_size, num_gen_threads))


def read_output(path):
    with open(path, "rb") as f:
        (combined_bytes,) = struct.unpack("<Q", f.read(8))
        bits = f.read(combined_bytes)
        total_primes, n_chunks, n_gen_threads_used = struct.unpack("<QQQ", f.read(24))
        timings = struct.unpack("<dddd", f.read(32))
    return bits, total_primes, n_chunks, n_gen_threads_used, timings


def run_gpu(binary, l_final, distance_hi, distance_lo, combined_size, chunk_size,
            num_gen_threads, tag):
    in_path = os.path.join(_SCRIPT_DIR, f"_chunked_parallel_input_{tag}.bin")
    out_path = os.path.join(_SCRIPT_DIR, f"_chunked_parallel_output_{tag}.bin")
    write_input(in_path, l_final, distance_hi, distance_lo, combined_size, chunk_size,
                num_gen_threads)
    result = subprocess.run([binary, in_path, out_path], capture_output=True, text=True)
    print(result.stderr, end="")
    try:
        os.remove(in_path)
    except OSError:
        pass  # known FUSE-mount quirk on some Windows-mounted dev folders -- harmless
    if result.returncode != 0:
        raise RuntimeError(f"GPU binary exited with code {result.returncode}")
    bits, total_primes, n_chunks, n_gen_threads_used, timings = read_output(out_path)
    try:
        os.remove(out_path)
    except OSError:
        pass
    return bits, total_primes, n_chunks, n_gen_threads_used, timings


# -------------------------------------------------------------------------------------------
# Ground truth: the real, unmodified production engine, called via ctypes.
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
    gpu_bits, total_primes, n_chunks, n_gen_used, timings = run_gpu(
        binary, l_final, distance_hi, distance_lo, combined_size, chunk_size, gen_threads, tag)
    truth_bits = run_engine_ground_truth(lib, l_final, distance_hi, distance_lo, combined_size)

    n_bytes = (combined_size + 7) // 8
    gpu_bits = gpu_bits[:n_bytes]
    mismatches = sum(1 for a, b in zip(gpu_bits, truth_bits) if a != b)
    status = "PASS" if mismatches == 0 else f"FAIL ({mismatches} mismatched bytes)"
    print(f"    [{name}] {status}  ({total_primes:,} primes across {n_chunks} chunks "
          f"of up to {chunk_size:,}, requested {gen_threads} gen-thread(s), actually used "
          f"{n_gen_used}, combined_size={combined_size:,})")
    return mismatches == 0


def run_exact_mode(binary, engine_so_path):
    print("=" * 78)
    print("EXACT mode -- chunked+accumulated, MULTI-THREADED-generation output vs. a single")
    print("unchunked, single-threaded real-engine call")
    print("=" * 78)
    lib = load_engine(engine_so_path)

    cases = [
        # (tag, name, l_final, distance_hi, distance_lo, combined_size, chunk_size, gen_threads)
        ("case1", "distance=0, self-elim guard, forced into ~4 tiny chunks, 1 gen-thread",
         1000, 0, 0, 10_000, 50, 1),
        ("case2", "medium range, forced into ~13 chunks, 2 gen-threads",
         10_000, 0, 10 ** 9, 10 ** 6, 100, 2),
        ("case3", "realistic floor-9-like batch, ~7 chunks, 4 gen-threads",
         31_781, 0, 10 ** 9, 10 ** 7, 500, 4),
        ("case4", "distance_hi != 0 (u128 branch), ~7 chunks, 4 gen-threads",
         31_781, 1, 12_345, 10 ** 7, 500, 4),
        ("case5", "chunk_size larger than total primes (degenerate), 8 gen-threads",
         1000, 0, 0, 10_000, 10_000, 8),
        ("case6", "requested gen-threads (16) larger than range width -- exercises the "
         "internal clamp",
         200, 0, 0, 2_000, 50, 16),
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
    print("STRESS mode -- large-scale real sieving-prime range, parallel generation + pipelined")
    print("GPU (same scale as marking_chunked_poc.py's STRESS mode, for a direct before/after)")
    print("=" * 78)
    floor = 25
    distance = 10 ** floor
    distance_hi, distance_lo = distance >> 64, distance & MASK64
    l_final = 20_000_000_000
    combined_size = 10 ** 8
    chunk_size = 20_000_000

    print(f"[*] l_final={l_final:,}  combined_size={combined_size:,}  chunk_size={chunk_size:,}"
          f"  gen_threads={gen_threads}")

    bits, total_primes, n_chunks, n_gen_used, timings = run_gpu(
        binary, l_final, distance_hi, distance_lo, combined_size, chunk_size, gen_threads,
        "stress")
    t_generate_wall, t_gpu_wall, t_download, t_total = timings

    total_bits_set = int.from_bytes(bits, "little").bit_count()
    density = total_bits_set / combined_size

    print()
    print(f"  total primes processed: {total_primes:,} across {n_chunks} chunks, "
          f"{n_gen_used} generator thread(s) actually used")
    print(f"  generate (CPU, parallel wall-clock): {t_generate_wall:.3f}s")
    print(f"  gpu (upload+kernel, pipelined wall-clock): {t_gpu_wall:.3f}s")
    print(f"  download (single, at end):   {t_download:.3f}s")
    print(f"  TOTAL:                       {t_total:.3f}s")
    print(f"  marked-composite density: {density:.4%}")


def run_full_scale_mode(binary, gen_threads):
    """FULL mode (2026-08-28) -- the real floor-25 scale, now with parallel CPU generation and
    a double-buffered GPU pipeline instead of the fully-serial single-thread version. This is
    the direct follow-up to marking_chunked_poc.py's FULL mode, whose real-hardware result
    (TOTAL=1316.729s: generate=670.486s single-threaded + upload=68.251s + kernel=576.403s +
    download=1.027s, fully serialized with zero overlap) was ~7.5x slower than production's
    176.018s at the same combined_size. Artur's explicit direction: finish the attempt for
    real and report the real number, not a "would probably be faster if..." estimate.
    """
    print()
    print("=" * 78)
    print("FULL mode -- REAL floor-25 scale, parallel generation + pipelined GPU")
    print("=" * 78)
    import math
    floor = 25
    distance = 10 ** floor
    distance_hi, distance_lo = distance >> 64, distance & MASK64
    combined_size = 10 ** 10
    l_final = math.isqrt(distance + combined_size) + 1
    chunk_size = 20_000_000

    approx_pi = l_final / (math.log(l_final) - 1)
    print(f"[*] floor={floor}  l_final={l_final:,}  combined_size={combined_size:,}  "
          f"chunk_size={chunk_size:,}  gen_threads={gen_threads}")
    print(f"    ~{approx_pi:,.0f} primes expected (~{approx_pi / chunk_size:,.0f} chunks)")
    print(f"    prior (single-threaded, serial) FULL-mode result for direct comparison: "
          f"TOTAL=1316.729s (generate=670.486s + upload=68.251s + kernel=576.403s + "
          f"download=1.027s, fully serialized)")

    bits, total_primes, n_chunks, n_gen_used, timings = run_gpu(
        binary, l_final, distance_hi, distance_lo, combined_size, chunk_size, gen_threads,
        "full")
    t_generate_wall, t_gpu_wall, t_download, t_total = timings

    # NOTE: at this mode's real scale, `bits` is ~1.25 GB -- int.from_bytes(...).bit_count()
    # avoids the many extra minutes a naive per-byte Python loop would add here (see
    # marking_chunked_poc.py's same fix for the full rationale).
    total_bits_set = int.from_bytes(bits, "little").bit_count()
    density = total_bits_set / combined_size

    print()
    print(f"  total primes processed: {total_primes:,} across {n_chunks} chunks, "
          f"{n_gen_used} generator thread(s) actually used")
    print(f"  generate (CPU, parallel wall-clock): {t_generate_wall:.3f}s")
    print(f"  gpu (upload+kernel, pipelined wall-clock): {t_gpu_wall:.3f}s")
    print(f"  download (single, at end):   {t_download:.3f}s")
    print(f"  TOTAL:                       {t_total:.3f}s")
    print(f"  marked-composite density: {density:.4%}")
    print()
    print(f"  DIRECT COMPARISON -- production's real 2026-08-16 floor-25 benchmark at this exact "
          f"same combined_size (1000 windows x 10^7): 113.352s sieve + 62.666s write = 176.018s "
          f"total (CPU, 24 workers). This run's TOTAL ({t_total:.3f}s) is GPU marking + "
          f"parallel CPU generation on {n_gen_used} thread(s) -- still not including "
          f"write-to-disk. Compare against the prior single-threaded/serial FULL-mode result "
          f"(1316.729s) to see what parallel generation + pipelining actually bought "
          f"({1316.729 / t_total:.2f}x if faster, or the honest ratio either way).")


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
        # deliberately NOT part of "both" -- this is the real floor-25 scale, must be requested
        # explicitly (see run_full_scale_mode's own docstring)
        run_full_scale_mode(binary, gen_threads)

    print()
    print("=" * 78)
    print("RESULT:", "PASS" if ok else "FAIL -- see mismatches above")
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
