"""phase_mod_chunked_poc.py -- third-step proof of concept: "kubełkowanie" (bucketing/
chunking, Artur's own framing, 2026-08-28) to push an arbitrarily large total sieving-prime
count through the GPU's fixed VRAM budget, the way primesieve itself streams segments through
a fixed-size sieve buffer internally rather than ever materializing "all primes up to N" at
once.

WHY THIS IS NEEDED (found by the previous step, phase_mod_resident_poc.py): floor 25's TRUE
sieving-prime count is pi(3,162,277,660,169) =~ 1.1*10^11. At 8 bytes each that's ~880 GB --
does not fit in the RTX 5070's 12 GB VRAM no matter what, even alone with nothing else
resident. The resident-primes PoC could only ever test a small sample (20,000,000 primes,
~160 MB) for exactly this reason.

UPDATE (2026-08-28, after the first run of this script): the first version generated each
chunk via prime_sieve_primesieve.py's generate_primes_in_range() (libprimesieve's
"materialize a full array" API) and measured ~2.7s to generate 20,000,000 primes per chunk --
extrapolated to the true floor-25 scale (~550x more primes), that would be HOURS, seemingly
worse than today's 113s CPU sieve. Artur pointed out this couldn't be right, since the real
engine already handles the true scale in 113s total, and asked me to go read
prime_sieve_engine_v4.c instead of guessing. It does NOT materialize sieving primes as a list
at all: generate_and_sieve_segment_bits() uses primesieve_iterator directly (primesieve_init /
primesieve_jump_to / primesieve_next_prime -- one prime at a time, zero array allocation),
fused in the same loop as phase computation and marking. THAT is why the real engine is fast.
This script now uses the SAME iterator mechanism, via iterator_chunk_gen.c's fill_chunk() (a
new, small, standalone helper -- NOT a change to the production engine -- that streams primes
into a buffer the same way, for shipping to the GPU instead of marking in the same C loop).
See iterator_chunk_gen.c's own header for the full story.

This PoC does NOT try to reach the full 1.1*10^11 in one run (see this project's own
established methodology: prove the MECHANISM cheaply first, then scale it up once trusted).
Instead, it reuses the exact same, already real-hardware-verified `phase_mod_resident_poc`
binary UNCHANGED, invoking it once per CHUNK (each chunk is a fresh, disjoint slice of the
smallest-to-largest primes, generated on demand via the fast iterator path above), summing
each chunk's per-window checksum into a running total (correct under plain uint64 wraparound
addition -- disjoint prime subsets' phase sums simply add), and verifying a handful of windows
per chunk against Python ground truth for THAT chunk's own primes (chunk-local correctness is
exhaustive, since phase_mod's correctness never depended on which primes were used -- already
proven by the resident PoC's own capture+checksum verification).

Default: 10 chunks x 20,000,000 primes = 200,000,000 primes total (1.6 GB of prime data --
technically would still squeeze into 12 GB as one resident block; this default run's job is to
prove the STREAMING MECHANISM itself is correct and to measure its real overhead, not to prove
necessity at this size). Pass --n-chunks higher (e.g. 700+ to cross the ~1.1*10^11-prime,
880 GB true floor-25 scale, or even just a few thousand to comfortably exceed the 12 GB ceiling
directly) once this default passes, to see the mechanism actually being load-bearing rather
than just correct.

KNOWN SIMPLIFICATION (flagged, not hidden): each chunk is a SEPARATE process invocation of
phase_mod_resident_poc (its own CUDA context init, its own cudaMalloc/cudaFree). A real v5
engine would keep one persistent CUDA context and stream chunks in-process, likely overlapping
chunk N+1's upload with chunk N's compute (async, double-buffered) to hide transfer latency
entirely -- neither of those optimizations is tested here. The per-chunk overhead numbers
below will be pessimistic vs. what a real in-process streaming engine could achieve; that's
the next honest step after this one, once basic streaming correctness is established.

Usage (inside WSL2; both phase_mod_resident_poc AND iterator_chunk_gen.so must already be
built -- build_and_run_chunked.sh does both automatically):
    python3 phase_mod_chunked_poc.py [--n-chunks 10] [--chunk-size 20000000]
                                      [--binary ./phase_mod_resident_poc]
"""
import ctypes
import importlib.util
import os
import subprocess
import sys
import time

import numpy as np

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PRIME_SIEVE_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PRIME_SIEVE_DIR)

# Reuse write_input_file/read_output_file from phase_mod_resident_poc.py directly rather than
# duplicating them -- same binary I/O format, this is just a different driver loop around it.
_spec = importlib.util.spec_from_file_location(
    "phase_mod_resident_poc", os.path.join(_SCRIPT_DIR, "phase_mod_resident_poc.py"))
_resident = importlib.util.module_from_spec(_spec)
sys.modules["phase_mod_resident_poc"] = _resident
_spec.loader.exec_module(_resident)

MAX_SAFE_PRIME_BITS = 50
DEFAULT_CHUNK_SIZE = 20_000_000
DEFAULT_N_CHUNKS = 10
FLOOR = 25
WINDOW_WIDTH = 10 ** 7
N_WINDOWS = 1000
MASK64 = (1 << 64) - 1
CAPTURE_PER_CHUNK = 1          # full-array verification windows per chunk
CHECKSUM_VERIFY_PER_CHUNK = 5  # additional checksum-only verification windows per chunk

_ITER_LIB_PATH = os.path.join(_SCRIPT_DIR, "iterator_chunk_gen.so")
_iter_lib = None


def _load_iter_lib():
    global _iter_lib
    if _iter_lib is None:
        if not os.path.isfile(_ITER_LIB_PATH):
            raise RuntimeError(
                f"Missing {_ITER_LIB_PATH} -- build it first: gcc -O3 -shared -fPIC "
                f"iterator_chunk_gen.c -o iterator_chunk_gen.so -lprimesieve")
        lib = ctypes.CDLL(_ITER_LIB_PATH)
        lib.fill_chunk.argtypes = [ctypes.c_uint64, ctypes.c_uint64,
                                    ctypes.POINTER(ctypes.c_uint64),
                                    ctypes.POINTER(ctypes.c_uint64)]
        lib.fill_chunk.restype = ctypes.c_int64
        _iter_lib = lib
    return _iter_lib


def next_chunk(next_lo, chunk_size):
    """The next `chunk_size` primes starting at/after `next_lo`, plus the lo to resume from
    for the FOLLOWING chunk -- via iterator_chunk_gen.c's fill_chunk(), which streams via
    libprimesieve's primesieve_iterator (the SAME mechanism prime_sieve_engine_v4.c's own
    production sieve loop uses -- see this module's own docstring for why the earlier,
    generate_primes_in_range()-based version of this function was replaced).

    Returns a numpy uint64 ARRAY, not a Python list -- avoiding materializing millions of
    individual Python int objects is itself part of why this is fast. Callers doing exact
    arithmetic against the huge `distance` values (which exceed uint64) MUST wrap each
    element in int(...) first -- see this file's own verification code below for where that
    matters and why (numpy would otherwise try to coerce the Python int operand into a numpy
    dtype and silently misbehave on values that don't fit in 64 bits)."""
    lib = _load_iter_lib()
    buf = np.empty(chunk_size, dtype=np.uint64)
    next_start_after = ctypes.c_uint64(0)
    n = lib.fill_chunk(ctypes.c_uint64(next_lo), ctypes.c_uint64(chunk_size),
                        buf.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)),
                        ctypes.byref(next_start_after))
    if n < 0:
        raise RuntimeError("fill_chunk() reported a primesieve internal error "
                            "(it.is_error) -- see iterator_chunk_gen.c")
    if n != chunk_size:
        raise RuntimeError(f"fill_chunk() returned {n} primes, expected {chunk_size} -- "
                            f"should never happen (primes never run out)")
    return buf, next_start_after.value


def main():
    n_chunks = DEFAULT_N_CHUNKS
    chunk_size = DEFAULT_CHUNK_SIZE
    binary = "./phase_mod_resident_poc"
    if "--n-chunks" in sys.argv:
        n_chunks = int(sys.argv[sys.argv.index("--n-chunks") + 1])
    if "--chunk-size" in sys.argv:
        chunk_size = int(sys.argv[sys.argv.index("--chunk-size") + 1])
    if "--binary" in sys.argv:
        binary = sys.argv[sys.argv.index("--binary") + 1]

    total_primes_target = n_chunks * chunk_size
    peak_chunk_bytes = chunk_size * 8
    total_data_bytes = total_primes_target * 8
    print(f"[*] n_chunks={n_chunks}  chunk_size={chunk_size:,}  "
          f"total_primes={total_primes_target:,}")
    print(f"    peak VRAM for prime data (one chunk resident at a time): "
          f"{peak_chunk_bytes/1e9:.3f} GB")
    print(f"    total prime DATA across all chunks (never resident all at once): "
          f"{total_data_bytes/1e9:.3f} GB "
          f"({'exceeds' if total_data_bytes > 12e9 else 'would still fit in'} a 12 GB card "
          f"if attempted as one resident block)")

    distances = [10 ** FLOOR + w * WINDOW_WIDTH for w in range(N_WINDOWS)]
    capture_windows_pool = list(range(N_WINDOWS))

    combined_checksum = [0] * N_WINDOWS
    failures = []
    next_lo = 2
    total_gen_seconds = 0.0
    total_gpu_seconds = 0.0
    total_primes_generated = 0

    for c in range(n_chunks):
        print(f"\n--- chunk {c+1}/{n_chunks} (primes starting at {next_lo:,}) ---")
        t0 = time.perf_counter()
        chunk_primes, next_lo = next_chunk(next_lo, chunk_size)
        gen_dt = time.perf_counter() - t0
        total_gen_seconds += gen_dt
        total_primes_generated += len(chunk_primes)
        print(f"    generated {len(chunk_primes):,} primes in {gen_dt:.3f}s "
              f"(range ended at {next_lo-1:,})")

        safe_limit = 1 << MAX_SAFE_PRIME_BITS
        max_p = int(chunk_primes[-1])   # numpy array is sorted ascending (iterator streams in
                                         # increasing order), so the last element is the max --
                                         # cast to a plain Python int for the comparison below
        if max_p >= safe_limit:
            over = int(np.count_nonzero(chunk_primes >= safe_limit))
            print(f"[!] chunk {c}: {over:,} primes >= 2^{MAX_SAFE_PRIME_BITS} safe limit -- "
                  f"truncating this chunk (see phase_mod_resident_poc.cu's own "
                  f"'VALIDATED RANGE'). This will start happening once chunks reach primes "
                  f"near 1.1*10^15.")
            chunk_primes = chunk_primes[chunk_primes < safe_limit]
            if len(chunk_primes) == 0:
                print("[!] chunk fully truncated, skipping.")
                continue

        capture_windows = sorted(set(
            [capture_windows_pool[(c * 37) % N_WINDOWS] for _ in range(CAPTURE_PER_CHUNK)]))

        in_path = os.path.join(_SCRIPT_DIR, f"_chunked_input_{c}.bin")
        out_path = os.path.join(_SCRIPT_DIR, f"_chunked_output_{c}.bin")
        _resident.write_input_file(in_path, chunk_primes, distances, capture_windows)

        result = subprocess.run([binary, in_path, out_path], capture_output=True, text=True)
        if result.returncode != 0:
            print(result.stderr, end="")
            print(f"[!] chunk {c}: GPU binary exited with code {result.returncode}")
            failures.append(f"chunk {c} GPU failure")
            os.remove(in_path)
            continue

        checksums, full_output, timings = _resident.read_output_file(
            out_path, len(chunk_primes), N_WINDOWS, len(capture_windows))
        t_total_chunk = timings[5]
        total_gpu_seconds += t_total_chunk
        print(f"    GPU: {t_total_chunk:.3f}s  (primes_upload={timings[0]:.3f}s "
              f"kernel={timings[2]:.3f}s)")

        for i in range(N_WINDOWS):
            combined_checksum[i] = (combined_checksum[i] + checksums[i]) & MASK64

        # chunk-local verification: full array for the capture window(s), checksum for a
        # few more random windows -- see module docstring for why chunk-local is sufficient.
        # NOTE: `p` MUST be cast to a plain Python int before `distances[w] % p` -- distances[w]
        # can be up to ~10^25, far past uint64 range, and mixing a huge Python int with a
        # numpy.uint64 operand in `%` risks numpy silently coercing/mishandling the Python
        # int side instead of doing correct arbitrary-precision arithmetic. See next_chunk()'s
        # own docstring for the same warning.
        for slot, w in enumerate(capture_windows):
            truth = [distances[w] % int(p) for p in chunk_primes]
            mismatches = sum(1 for i in range(len(chunk_primes))
                              if full_output[slot][i] != truth[i])
            if mismatches:
                failures.append(f"chunk {c} window {w}: {mismatches} full-array mismatches")
                print(f"    window {w}: FAIL ({mismatches} mismatches)")
            else:
                print(f"    window {w}: full-array PASS")
            truth_checksum = sum(truth) & MASK64
            if truth_checksum != checksums[w]:
                failures.append(f"chunk {c} window {w}: checksum inconsistent with full array")

        import random
        random.seed(1000 + c)
        for w in random.sample(range(N_WINDOWS), CHECKSUM_VERIFY_PER_CHUNK):
            truth_checksum = (sum(distances[w] % int(p) for p in chunk_primes)) & MASK64
            if truth_checksum != checksums[w]:
                failures.append(f"chunk {c} window {w}: checksum-verify FAIL")

        os.remove(in_path)
        os.remove(out_path)

    print()
    print("=" * 78)
    print(f"floor {FLOOR}, {n_chunks} chunks x up to {chunk_size:,} primes "
          f"({total_primes_generated:,} primes actually processed, "
          f"{N_WINDOWS:,} windows, {N_WINDOWS * WINDOW_WIDTH:,} numbers/chunk span)")
    print(f"  total CPU-side prime generation (streaming, one chunk in memory at a time): "
          f"{total_gen_seconds:.3f}s")
    print(f"  total GPU time (sum of {n_chunks} separate process invocations, includes "
          f"per-process CUDA context overhead -- see module docstring's 'KNOWN "
          f"SIMPLIFICATION'): {total_gpu_seconds:.3f}s")
    print(f"  total wall (generation + GPU, sequential, no overlap): "
          f"{total_gen_seconds + total_gpu_seconds:.3f}s")
    print(f"  peak VRAM for prime data stayed at ~{peak_chunk_bytes/1e9:.3f} GB regardless of "
          f"n_chunks (this is the actual 'kubełkowanie' claim being tested -- rerun with a "
          f"much higher --n-chunks to push total_primes past the 12 GB ceiling and confirm "
          f"this number does not grow)")
    if failures:
        print(f"\n  FAIL: {len(failures)} verification failures:")
        for f in failures[:20]:
            print(f"    - {f}")
    else:
        print(f"\n  PASS: every chunk-local verification (full-array + checksum) matched "
              f"Python ground truth across all {n_chunks} chunks.")
    print("=" * 78)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
