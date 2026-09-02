"""phase_stream_poc.py -- host harness for phase_stream_poc.cu (ninth-step GPU PoC).

Builds Artur's proposed architecture: GPU computes ONLY the phase (start_pos) for each sieving
prime -- no atomics, no combined_size/tier logic, no shared 1.25 GB output buffer on GPU at all
-- and streams results directly to CPU via pinned + mapped ("zero-copy") host memory, in small
ping-pong segments sized to `chunk_size`. CPU marks each chunk's results (single-threaded here,
matching production's exact per-prime branch) while GPU computes the NEXT chunk's phases,
achieving real overlap without ever materializing a giant contended write buffer on the GPU side.

Direct follow-up to two findings this same day: (1) marking_bucketed_poc's FULL-mode regression
(196.448s, worse than the unbucketed two-tier's 169.623s) confirmed bucketing's isolated win
didn't survive losing upload/kernel overlap; (2) generation_balance_poc proved raw CPU-side
prime generation is fast (54.5s for the whole real sparse range, 24 threads) and unaffected by
generator-thread load balance -- meaning the ~186s "generate_wall" measured in every prior
pipeline was mostly generator threads BLOCKED on a slow GPU consumer's backpressure, not real
generation cost. CPU has real throughput headroom; this design tests whether GPU can be made fast
and lean enough (phase-only, no atomics) to actually keep up with it.

THREE MODES (same split as every prior file in this series):

  EXACT mode -- correctness vs. a single unchunked, single-threaded call to the real, unmodified
  prime_sieve_engine_v4.c. Also reports n_loop_primes/n_single_primes (dense-style vs sparse-
  style CPU branch counts) as a sanity check that both code paths are actually being exercised.

  STRESS mode -- the same moderate-scale run as every prior file, for a like-for-like read.

  FULL mode -- the real floor-25 scale. The number that matters: does this architecture beat
  169.623s (best result in this series so far), and how close does it get to the ~54.5s raw
  generation floor found by generation_balance_poc (the theoretical best case if GPU phase
  computation and CPU marking were both free and fully hidden behind generation)?

Usage (inside WSL2, after building via build_and_run_phase_stream.sh):
    python3 phase_stream_poc.py [--binary ./phase_stream_poc]
                                 [--engine-so ../prime_sieve_engine_v4.so]
                                 [--mode exact|stress|full|both]
                                 [--gen-threads N]   (default: os.cpu_count())
                                 [--chunk-size N]    (default: 2000000 -- the ping-pong segment
                                                       size; smaller = tighter lookahead per
                                                       Artur's "not so large CPU alone would beat
                                                       it" constraint, larger = more amortized
                                                       kernel-launch overhead. Sweep this.)
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
DEFAULT_BINARY = os.path.join(_SCRIPT_DIR, "phase_stream_poc")
DEFAULT_CHUNK_SIZE = 2_000_000


def write_input(path, l_final, distance_hi, distance_lo, combined_size, chunk_size,
                 num_gen_threads):
    with open(path, "wb") as f:
        f.write(struct.pack("<QQQQQQ", l_final, distance_hi, distance_lo, combined_size,
                             chunk_size, num_gen_threads))


def read_output(path):
    with open(path, "rb") as f:
        (combined_bytes,) = struct.unpack("<Q", f.read(8))
        bits = f.read(combined_bytes)
        (total_primes, n_loop_primes, n_single_primes, n_chunks,
         n_gen_threads_used) = struct.unpack("<QQQQQ", f.read(40))
        timings = struct.unpack("<dddd", f.read(32))
    return bits, {
        "total_primes": total_primes,
        "n_loop_primes": n_loop_primes,
        "n_single_primes": n_single_primes,
        "n_chunks": n_chunks,
        "n_gen_threads_used": n_gen_threads_used,
    }, timings


def run_gpu(binary, l_final, distance_hi, distance_lo, combined_size, chunk_size,
            num_gen_threads, tag):
    in_path = os.path.join(_SCRIPT_DIR, f"_phase_stream_input_{tag}.bin")
    out_path = os.path.join(_SCRIPT_DIR, f"_phase_stream_output_{tag}.bin")
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
    print(f"    [{name}] {status}  (loop-style={counts['n_loop_primes']:,} "
          f"single-write-style={counts['n_single_primes']:,} primes, "
          f"combined_size={combined_size:,}, l_final={l_final:,})")
    return mismatches == 0


def run_exact_mode(binary, engine_so_path):
    print("=" * 78)
    print("EXACT mode -- phase-stream (GPU phase-only, CPU marks) vs. a single unchunked,")
    print("single-threaded real-engine call")
    print("=" * 78)
    lib = load_engine(engine_so_path)

    cases = [
        # (tag, name, l_final, distance_hi, distance_lo, combined_size, chunk_size, gen_threads)
        ("case1", "small, mostly loop-style (combined_size large vs l_final)",
         1000, 0, 0, 10_000, 50, 2),
        ("case2", "mostly single-write-style (combined_size small vs l_final)",
         10_000, 0, 10 ** 9, 100, 100, 4),
        ("case3", "mixed, realistic floor-9-like magnitude",
         31_781, 0, 10 ** 9, 5_000, 500, 4),
        ("case4", "distance_hi != 0 (u128 branch), mixed",
         31_781, 1, 12_345, 5_000, 500, 4),
        ("case5", "boundary: combined_size == an actual prime (97)",
         200, 0, 0, 97, 20, 2),
        ("case6", "requested gen-threads (16) larger than range width",
         200, 0, 0, 97, 20, 16),
        ("case7", "chunk_size larger than total primes (degenerate, single chunk)",
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

def run_stress_mode(binary, gen_threads, chunk_size):
    print()
    print("=" * 78)
    print("STRESS mode -- moderate scale, phase-stream architecture")
    print("=" * 78)
    floor = 25
    distance = 10 ** floor
    distance_hi, distance_lo = distance >> 64, distance & MASK64
    l_final = 20_000_000_000
    combined_size = 10 ** 8

    print(f"[*] l_final={l_final:,}  combined_size={combined_size:,}  chunk_size={chunk_size:,}"
          f"  gen_threads={gen_threads}")

    bits, counts, timings = run_gpu(
        binary, l_final, distance_hi, distance_lo, combined_size, chunk_size, gen_threads,
        "stress")
    (t_gen, t_gpu, t_cpu_mark, t_total) = timings

    total_bits_set = int.from_bytes(bits, "little").bit_count()
    density = total_bits_set / combined_size

    print()
    print(f"  primes: {counts['total_primes']:,} total "
          f"({counts['n_loop_primes']:,} loop-style + {counts['n_single_primes']:,} "
          f"single-write-style), {counts['n_chunks']} chunks, "
          f"{counts['n_gen_threads_used']} generator thread(s)")
    print(f"  generate_wall={t_gen:.3f}s  gpu_wall={t_gpu:.3f}s  "
          f"cpu_mark_wall={t_cpu_mark:.3f}s (overlaps with gpu_wall by design)")
    print(f"  TOTAL:    {t_total:.3f}s")
    print(f"  marked-composite density: {density:.4%}")


def run_full_scale_mode(binary, gen_threads, chunk_size):
    """FULL mode (2026-08-28) -- the real floor-25 scale, phase-stream architecture. Direct
    test of whether GPU-phase-only + CPU-marks (no atomics, no shared GPU write buffer) beats
    the best prior result in this series (unbucketed two-tier, TOTAL=169.623s), and how close it
    gets to generation_balance_poc's measured ~54.5s raw-generation floor.
    """
    print()
    print("=" * 78)
    print("FULL mode -- REAL floor-25 scale, phase-stream architecture")
    print("=" * 78)
    import math
    floor = 25
    distance = 10 ** floor
    distance_hi, distance_lo = distance >> 64, distance & MASK64
    combined_size = 10 ** 10
    l_final = math.isqrt(distance + combined_size) + 1

    print(f"[*] floor={floor}  l_final={l_final:,}  combined_size={combined_size:,}  "
          f"chunk_size={chunk_size:,}  gen_threads={gen_threads}")
    print(f"    prior results for direct comparison: serial TOTAL=1316.729s, "
          f"parallel(no tier split)=580.386s, two-tier(unbucketed)=169.623s (best so far), "
          f"two-tier+bucketed sparse=196.448s (regression), "
          f"raw generation only (generation_balance_poc)=~54.5s")

    bits, counts, timings = run_gpu(
        binary, l_final, distance_hi, distance_lo, combined_size, chunk_size, gen_threads,
        "full")
    (t_gen, t_gpu, t_cpu_mark, t_total) = timings

    total_bits_set = int.from_bytes(bits, "little").bit_count()
    density = total_bits_set / combined_size

    print()
    print(f"  primes: {counts['total_primes']:,} total "
          f"({counts['n_loop_primes']:,} loop-style + {counts['n_single_primes']:,} "
          f"single-write-style), {counts['n_chunks']} chunks, "
          f"{counts['n_gen_threads_used']} generator thread(s)")
    print(f"  generate_wall={t_gen:.3f}s  gpu_wall={t_gpu:.3f}s  "
          f"cpu_mark_wall={t_cpu_mark:.3f}s (overlaps with gpu_wall by design -- if TOTAL is "
          f"close to max(gpu_wall, generate_wall) rather than their sum, overlap is working)")
    print(f"  TOTAL:    {t_total:.3f}s")
    print(f"  marked-composite density: {density:.4%}")
    print()
    print(f"  DIRECT COMPARISON -- best prior result (unbucketed two-tier): 169.623s. "
          f"This run's TOTAL ({t_total:.3f}s): {169.623 / t_total:.2f}x if faster. "
          f"vs. production's full benchmark (176.018s): {t_total / 176.018:.2f}x slower "
          f"(or faster, if < 1.0). vs. raw-generation floor (~54.5s): "
          f"{t_total / 54.5:.2f}x that floor.")


def main():
    binary = DEFAULT_BINARY
    engine_so = DEFAULT_ENGINE_SO
    mode = "both"
    gen_threads = os.cpu_count() or 4
    chunk_size = DEFAULT_CHUNK_SIZE
    if "--binary" in sys.argv:
        binary = sys.argv[sys.argv.index("--binary") + 1]
    if "--engine-so" in sys.argv:
        engine_so = sys.argv[sys.argv.index("--engine-so") + 1]
    if "--mode" in sys.argv:
        mode = sys.argv[sys.argv.index("--mode") + 1]
    if "--gen-threads" in sys.argv:
        gen_threads = int(sys.argv[sys.argv.index("--gen-threads") + 1])
    if "--chunk-size" in sys.argv:
        chunk_size = int(sys.argv[sys.argv.index("--chunk-size") + 1])

    print(f"[*] os.cpu_count()={os.cpu_count()} -- using --gen-threads={gen_threads} "
          f"--chunk-size={chunk_size} for STRESS/FULL modes (EXACT mode uses its own small, "
          f"fixed per-case values)")

    ok = True
    if mode in ("exact", "both"):
        ok = run_exact_mode(binary, engine_so) and ok
    if mode in ("stress", "both"):
        run_stress_mode(binary, gen_threads, chunk_size)
    if mode == "full":
        run_full_scale_mode(binary, gen_threads, chunk_size)

    print()
    print("=" * 78)
    print("RESULT:", "PASS" if ok else "FAIL -- see mismatches above")
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
