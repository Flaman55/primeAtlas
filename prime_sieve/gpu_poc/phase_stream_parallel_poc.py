"""phase_stream_parallel_poc.py -- host harness for phase_stream_parallel_poc.cu (tenth-step
GPU PoC).

Direct follow-up to phase_stream_poc's real-hardware FULL-mode result: TOTAL=677.942s, with
cpu_mark_wall=568.427s (84% of total) as the clearly dominant cost -- single-threaded CPU marking,
not GPU phase computation, was the bottleneck. Artur's own read: with a single marking thread
already only ~3.8x slower than production's real 176.018s benchmark (which uses 24 workers for
its own marking step), there is real room to close that gap by parallelizing CPU marking to match.

This build keeps phase_stream_poc's GPU-phase-only kernel (no atomics, no combined_size/tier
logic on the GPU side) completely unchanged, and turns the previous single-threaded, in-lockstep
marking step into a THREE-STAGE decoupled pipeline: CPU generator threads -> [prime batch queue]
-> GPU phase kernel (single driver thread, ping-pong pinned+mapped buffers) -> [mark job queue]
-> a POOL of CPU marker threads doing atomic-OR marking, mirroring production's own
`__atomic_fetch_or`/`__ATOMIC_RELAXED` mechanism (confirmed by reading prime_sieve_engine_v4.c's
generate_and_sieve_segment_bits_atomic() directly). The marker-thread count is independently
tunable from the generator-thread count via --marker-threads, since generation is now known-cheap
(~54.5s total per generation_balance_poc) and the right split of a 24-core machine between
generation / GPU-driving / marking is an empirical question, not something to guess.

THREE MODES (same split as every prior file in this series):

  EXACT mode -- correctness vs. a single unchunked, single-threaded call to the real, unmodified
  prime_sieve_engine_v4.c. Reuses phase_stream_poc's 7 cases essentially unchanged (the underlying
  per-prime phase math and marking branch are byte-identical to phase_stream_poc -- only the
  concurrency structure around them changed), with a small --marker-threads value per case so the
  atomic marker-pool path is actually exercised even at tiny scale.

  STRESS mode -- the same moderate-scale run as every prior file, for a like-for-like read.

  FULL mode -- the real floor-25 scale. The number that matters: does parallelizing CPU marking
  close phase_stream_poc's 677.942s down toward (or past) 169.623s (best result in this series so
  far), and how close does marker_busy_total/n_marker_threads get to the raw generation floor?

Usage (inside WSL2, after building via build_and_run_phase_stream_parallel.sh):
    python3 phase_stream_parallel_poc.py [--binary ./phase_stream_parallel_poc]
                                          [--engine-so ../prime_sieve_engine_v4.so]
                                          [--mode exact|stress|full|both]
                                          [--gen-threads N]     (default: os.cpu_count())
                                          [--marker-threads N]  (default: os.cpu_count() -- tune
                                                                  independently from --gen-threads;
                                                                  sweep this to find the right
                                                                  split of a 24-core machine)
                                          [--chunk-size N]      (default: 2000000 -- same ping-pong
                                                                  segment size meaning as
                                                                  phase_stream_poc)
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
DEFAULT_BINARY = os.path.join(_SCRIPT_DIR, "phase_stream_parallel_poc")
DEFAULT_CHUNK_SIZE = 2_000_000


def write_input(path, l_final, distance_hi, distance_lo, combined_size, chunk_size,
                 num_gen_threads, num_marker_threads):
    with open(path, "wb") as f:
        f.write(struct.pack("<QQQQQQQ", l_final, distance_hi, distance_lo, combined_size,
                             chunk_size, num_gen_threads, num_marker_threads))


def read_output(path):
    with open(path, "rb") as f:
        (combined_bytes,) = struct.unpack("<Q", f.read(8))
        bits = f.read(combined_bytes)
        (total_primes, n_loop_primes, n_single_primes, n_chunks,
         n_gen_threads_used, n_marker_threads_used) = struct.unpack("<QQQQQQ", f.read(48))
        timings = struct.unpack("<dddd", f.read(32))
    return bits, {
        "total_primes": total_primes,
        "n_loop_primes": n_loop_primes,
        "n_single_primes": n_single_primes,
        "n_chunks": n_chunks,
        "n_gen_threads_used": n_gen_threads_used,
        "n_marker_threads_used": n_marker_threads_used,
    }, timings


def run_gpu(binary, l_final, distance_hi, distance_lo, combined_size, chunk_size,
            num_gen_threads, num_marker_threads, tag):
    in_path = os.path.join(_SCRIPT_DIR, f"_phase_stream_parallel_input_{tag}.bin")
    out_path = os.path.join(_SCRIPT_DIR, f"_phase_stream_parallel_output_{tag}.bin")
    write_input(in_path, l_final, distance_hi, distance_lo, combined_size, chunk_size,
                num_gen_threads, num_marker_threads)
    # Stream the binary's stderr live instead of capturing it and dumping it only after the
    # process exits (subprocess.run(capture_output=True) does the latter -- it hides ALL output,
    # including the [phase-stream-parallel] periodic progress line printed every 200 chunks,
    # until the whole run finishes, making a genuinely slow FULL-mode run indistinguishable from a
    # real hang. This matters here specifically: a real floor-25 run legitimately took 677.942s
    # (~11.3 min) to complete in phase_stream_poc, so silence for a few minutes is not by itself
    # evidence of a deadlock.
    proc = subprocess.Popen([binary, in_path, out_path], stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE, text=True, bufsize=1)
    for line in proc.stderr:
        print(line, end="", flush=True)
    proc.wait()
    try:
        os.remove(in_path)
    except OSError:
        pass
    if proc.returncode != 0:
        raise RuntimeError(f"GPU binary exited with code {proc.returncode}")
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
               chunk_size, gen_threads, marker_threads):
    gpu_bits, counts, timings = run_gpu(
        binary, l_final, distance_hi, distance_lo, combined_size, chunk_size, gen_threads,
        marker_threads, tag)
    truth_bits = run_engine_ground_truth(lib, l_final, distance_hi, distance_lo, combined_size)

    n_bytes = (combined_size + 7) // 8
    gpu_bits = gpu_bits[:n_bytes]
    mismatches = sum(1 for a, b in zip(gpu_bits, truth_bits) if a != b)
    status = "PASS" if mismatches == 0 else f"FAIL ({mismatches} mismatched bytes)"
    print(f"    [{name}] {status}  (loop-style={counts['n_loop_primes']:,} "
          f"single-write-style={counts['n_single_primes']:,} primes, "
          f"marker_threads_used={counts['n_marker_threads_used']}, "
          f"combined_size={combined_size:,}, l_final={l_final:,})")
    return mismatches == 0


def run_exact_mode(binary, engine_so_path):
    print("=" * 78)
    print("EXACT mode -- phase-stream-parallel (GPU phase-only, CPU marker POOL) vs. a single")
    print("unchunked, single-threaded real-engine call")
    print("=" * 78)
    lib = load_engine(engine_so_path)

    cases = [
        # (tag, name, l_final, distance_hi, distance_lo, combined_size, chunk_size, gen_threads,
        #  marker_threads)
        ("case1", "small, mostly loop-style (combined_size large vs l_final)",
         1000, 0, 0, 10_000, 50, 2, 2),
        ("case2", "mostly single-write-style (combined_size small vs l_final)",
         10_000, 0, 10 ** 9, 100, 100, 4, 3),
        ("case3", "mixed, realistic floor-9-like magnitude",
         31_781, 0, 10 ** 9, 5_000, 500, 4, 4),
        ("case4", "distance_hi != 0 (u128 branch), mixed",
         31_781, 1, 12_345, 5_000, 500, 4, 2),
        ("case5", "boundary: combined_size == an actual prime (97)",
         200, 0, 0, 97, 20, 2, 2),
        ("case6", "requested gen-threads (16) larger than range width",
         200, 0, 0, 97, 20, 16, 8),
        ("case7", "chunk_size larger than total primes (degenerate, single chunk), "
                   "marker_threads > chunks available",
         1000, 0, 0, 500, 10_000, 8, 6),
    ]
    all_pass = True
    for tag, name, l_final, dh, dl, cs, chunk, gt, mt in cases:
        ok = exact_case(binary, lib, tag, name, l_final, dh, dl, cs, chunk, gt, mt)
        all_pass = all_pass and ok
    return all_pass


# -------------------------------------------------------------------------------------------
# STRESS mode
# -------------------------------------------------------------------------------------------

def run_stress_mode(binary, gen_threads, marker_threads, chunk_size):
    print()
    print("=" * 78)
    print("STRESS mode -- moderate scale, phase-stream-parallel architecture")
    print("=" * 78)
    floor = 25
    distance = 10 ** floor
    distance_hi, distance_lo = distance >> 64, distance & MASK64
    l_final = 20_000_000_000
    combined_size = 10 ** 8

    print(f"[*] l_final={l_final:,}  combined_size={combined_size:,}  chunk_size={chunk_size:,}"
          f"  gen_threads={gen_threads}  marker_threads={marker_threads}")

    bits, counts, timings = run_gpu(
        binary, l_final, distance_hi, distance_lo, combined_size, chunk_size, gen_threads,
        marker_threads, "stress")
    (t_gen, t_gpu, t_marker_busy_total, t_total) = timings

    total_bits_set = int.from_bytes(bits, "little").bit_count()
    density = total_bits_set / combined_size

    print()
    print(f"  primes: {counts['total_primes']:,} total "
          f"({counts['n_loop_primes']:,} loop-style + {counts['n_single_primes']:,} "
          f"single-write-style), {counts['n_chunks']} chunks, "
          f"{counts['n_gen_threads_used']} generator thread(s), "
          f"{counts['n_marker_threads_used']} marker thread(s)")
    print(f"  generate_wall={t_gen:.3f}s  gpu_wall={t_gpu:.3f}s  "
          f"marker_busy_total={t_marker_busy_total:.3f}s "
          f"(avg={t_marker_busy_total / max(1, counts['n_marker_threads_used']):.3f}s/thread, "
          f"overlaps with gpu_wall by design)")
    print(f"  TOTAL:    {t_total:.3f}s")
    print(f"  marked-composite density: {density:.4%}")


def run_full_scale_mode(binary, gen_threads, marker_threads, chunk_size):
    """FULL mode (2026-08-28) -- the real floor-25 scale, phase-stream-parallel architecture.
    Direct test of whether decoupling CPU marking into an independently-sized thread pool closes
    phase_stream_poc's 677.942s (dominated 84% by single-threaded cpu_mark_wall=568.427s) toward
    the best prior result in this series (unbucketed two-tier, TOTAL=169.623s), and how close
    marker_busy_total/n_marker_threads gets to generation_balance_poc's ~54.5s raw-generation
    floor.
    """
    print()
    print("=" * 78)
    print("FULL mode -- REAL floor-25 scale, phase-stream-parallel architecture")
    print("=" * 78)
    import math
    floor = 25
    distance = 10 ** floor
    distance_hi, distance_lo = distance >> 64, distance & MASK64
    combined_size = 10 ** 10
    l_final = math.isqrt(distance + combined_size) + 1

    print(f"[*] floor={floor}  l_final={l_final:,}  combined_size={combined_size:,}  "
          f"chunk_size={chunk_size:,}  gen_threads={gen_threads}  marker_threads={marker_threads}")
    print(f"    prior results for direct comparison: serial TOTAL=1316.729s, "
          f"parallel(no tier split)=580.386s, two-tier(unbucketed)=169.623s (best so far), "
          f"two-tier+bucketed sparse=196.448s (regression), "
          f"phase-stream single-marker=677.942s (cpu_mark_wall=568.427s, 84% of total), "
          f"raw generation only (generation_balance_poc)=~54.5s")

    bits, counts, timings = run_gpu(
        binary, l_final, distance_hi, distance_lo, combined_size, chunk_size, gen_threads,
        marker_threads, "full")
    (t_gen, t_gpu, t_marker_busy_total, t_total) = timings

    total_bits_set = int.from_bytes(bits, "little").bit_count()
    density = total_bits_set / combined_size

    print()
    print(f"  primes: {counts['total_primes']:,} total "
          f"({counts['n_loop_primes']:,} loop-style + {counts['n_single_primes']:,} "
          f"single-write-style), {counts['n_chunks']} chunks, "
          f"{counts['n_gen_threads_used']} generator thread(s), "
          f"{counts['n_marker_threads_used']} marker thread(s)")
    print(f"  generate_wall={t_gen:.3f}s  gpu_wall={t_gpu:.3f}s  "
          f"marker_busy_total={t_marker_busy_total:.3f}s "
          f"(avg={t_marker_busy_total / max(1, counts['n_marker_threads_used']):.3f}s/thread -- "
          f"if this avg is well below TOTAL, the marker pool itself isn't the bottleneck anymore)")
    print(f"  TOTAL:    {t_total:.3f}s")
    print(f"  marked-composite density: {density:.4%}")
    print()
    print(f"  DIRECT COMPARISON -- best prior result (unbucketed two-tier): 169.623s. "
          f"This run's TOTAL ({t_total:.3f}s): {169.623 / t_total:.2f}x if faster. "
          f"vs. single-marker phase-stream (677.942s): {677.942 / t_total:.2f}x if faster. "
          f"vs. production's full benchmark (176.018s): {t_total / 176.018:.2f}x slower "
          f"(or faster, if < 1.0). vs. raw-generation floor (~54.5s): "
          f"{t_total / 54.5:.2f}x that floor.")


def main():
    binary = DEFAULT_BINARY
    engine_so = DEFAULT_ENGINE_SO
    mode = "both"
    gen_threads = os.cpu_count() or 4
    marker_threads = os.cpu_count() or 4
    chunk_size = DEFAULT_CHUNK_SIZE
    if "--binary" in sys.argv:
        binary = sys.argv[sys.argv.index("--binary") + 1]
    if "--engine-so" in sys.argv:
        engine_so = sys.argv[sys.argv.index("--engine-so") + 1]
    if "--mode" in sys.argv:
        mode = sys.argv[sys.argv.index("--mode") + 1]
    if "--gen-threads" in sys.argv:
        gen_threads = int(sys.argv[sys.argv.index("--gen-threads") + 1])
    if "--marker-threads" in sys.argv:
        marker_threads = int(sys.argv[sys.argv.index("--marker-threads") + 1])
    if "--chunk-size" in sys.argv:
        chunk_size = int(sys.argv[sys.argv.index("--chunk-size") + 1])

    print(f"[*] os.cpu_count()={os.cpu_count()} -- using --gen-threads={gen_threads} "
          f"--marker-threads={marker_threads} --chunk-size={chunk_size} for STRESS/FULL modes "
          f"(EXACT mode uses its own small, fixed per-case values)")

    ok = True
    if mode in ("exact", "both"):
        ok = run_exact_mode(binary, engine_so) and ok
    if mode in ("stress", "both"):
        run_stress_mode(binary, gen_threads, marker_threads, chunk_size)
    if mode == "full":
        run_full_scale_mode(binary, gen_threads, marker_threads, chunk_size)

    print()
    print("=" * 78)
    print("RESULT:", "PASS" if ok else "FAIL -- see mismatches above")
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
