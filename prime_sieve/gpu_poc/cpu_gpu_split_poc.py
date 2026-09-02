"""cpu_gpu_split_poc.py -- eleventh-step PoC: split the RANGE between CPU and GPU instead of
splitting the WORK on one shared buffer.

Direct follow-up to phase_stream_parallel_poc's real-hardware result: even with 24 CPU marker
threads decoupled behind a bounded queue, the queue sat pinned at its max depth the whole run and
the extrapolated total (~25 min for real floor-25 scale) came out WORSE than phase_stream_poc's
already-disappointing single-threaded-marking result (677.942s). The common thread across every
design tried in this whole series (bucketing, phase-streaming, thread-pool marking): CPU and GPU
always end up writing into the SAME shared bit buffer, which means contention -- either GPU atomic
writes competing with each other (the original bottleneck), or now multiple CPU threads' atomic
writes competing with each other on the SAME cache lines (this file's own likely explanation for
why 24 marker threads didn't scale).

Artur's new idea, in his own words (paraphrased): since CPU alone (176.018s, sieve+write) and GPU
alone (169.623s, marking only, via marking_two_tier_poc) are already in the same rough order of
magnitude, why not have BOTH devices work at once on the SAME real problem, each on its OWN
disjoint slice of the `combined_size` range -- e.g. CPU takes the first half of a 10-billion-number
window, GPU takes the second half -- so in not much more time than either alone takes today, the
combined system covers roughly TWICE the range. This sidesteps the entire class of problem this
series has been fighting: CPU's slice and GPU's slice write to DIFFERENT, non-overlapping regions
of the final bitmap, so there is ZERO shared-buffer contention and ZERO cross-device
synchronization needed DURING the run -- only a one-time split-the-work-up-front and a trivial
concatenate-two-adjacent-byte-ranges step at the end.

WHY THIS IS LOW RISK, NOT JUST LOW COMPLEXITY: splitting `combined_size` into two adjacent
sub-windows and computing each independently with its own correctly-shifted local `distance` is
NOT a new kind of decomposition -- it's exactly what production's own orchestrator already does
today for its 1000 separate 10-million-wide windows (each window is one independent call to
`generate_and_sieve_segment_bits` with its own `distance`). This file just assigns one such
adjacent "window" to the CPU engine (unmodified, ctypes call to prime_sieve_engine_v4.c) and the
other to the best proven GPU-only marking pipeline (marking_two_tier_poc, reused via its own
already-verified binary and I/O format, unmodified), then runs both AT ONCE via a thread each (a
ctypes call into C releases the GIL for its duration, and the GPU side is a genuinely separate OS
process via subprocess -- so the two genuinely overlap in wall-clock time, not just in code
structure) and measures whether wall time actually comes out closer to max(cpu, gpu) than their
sum.

WHAT THIS SIMPLIFIES vs. a "fully optimal" split: both sides compute phases against the SAME
`l_final` (derived from the FULL original window, not either sub-window individually) -- a smaller
side's true sqrt-of-local-upper-bound is always <= the shared l_final, so this is definitely
correct (a strict superset of the sieving primes truly needed for that smaller sub-window), just a
little more generation/phase work than the theoretical minimum for whichever side got the smaller
slice. Kept this way deliberately, to keep the first prototype's correctness argument as simple as
possible: two adjacent windows, each computed exactly the way a single window is computed today.

THREE MODES (same split as every prior file in this series):

  EXACT mode -- the split-then-concatenate result compared byte-for-byte against a single
  unchunked, unsplit call to the real, unmodified engine over the FULL original window. Cases
  cover: an even 50/50 split, cpu_fraction=0.0 (all GPU, exercises the CPU-side-empty branch),
  cpu_fraction=1.0 (all GPU-side-empty branch, i.e. the reverse), a nonzero `distance` (tests the
  distance-shift arithmetic for the GPU's sub-window, not just the trivial distance=0 case), the
  distance_hi != 0 (u128) branch, an uneven split fraction to exercise the align-to-64 rounding,
  and a tiny combined_size to sanity-check at small scale.

  STRESS mode -- moderate scale (same l_final/combined_size shape as every prior STRESS mode in
  this series), for a like-for-like read.

  FULL mode -- the real floor-25 scale. The number that matters: does real wall time land close to
  max(cpu_elapsed, gpu_total) (true overlap) rather than their sum, and does that wall time beat
  both devices' own solo numbers (176.018s CPU-with-write, 169.623s GPU-marking-only) -- i.e. does
  running both devices on HALF the range each, concurrently, actually cover the FULL range faster
  than either device covering it all alone.

Usage (inside WSL2, after building via build_and_run_cpu_gpu_split.sh, which builds
marking_two_tier_poc's binary since this file calls it unmodified):
    python3 cpu_gpu_split_poc.py [--engine-so ../prime_sieve_engine_v4.so]
                                  [--gpu-binary ./marking_two_tier_poc]
                                  [--mode exact|stress|full|both]
                                  [--cpu-fraction F]    (default 0.5 -- fraction of combined_size
                                                          given to the CPU side; sweep this, since
                                                          CPU-with-write and GPU-marking-only are
                                                          not necessarily equally fast per number.
                                                          Give a comma-separated list, e.g.
                                                          --cpu-fraction 0.6,0.65,0.7, to run a
                                                          load-balance sweep at a FIXED
                                                          combined_size instead of one run --
                                                          see run_fraction_sweep_mode())
                                  [--gpu-gen-threads N] (default 12 -- CPU threads used by the GPU
                                                          side's OWN prime generation, independent
                                                          of --cpu-workers below since both run
                                                          concurrently on the same machine)
                                  [--gpu-chunk-size N]  (default 20000000, matches
                                                          marking_two_tier_poc's own FULL-mode
                                                          default)
                                  [--cpu-workers N]      (default 24, matches production's
                                                          MAX_WORKERS -- STRESS/FULL mode only;
                                                          EXACT mode always stays single-threaded.
                                                          >1 switches the CPU side from
                                                          run_cpu_side() to the real multi-process
                                                          architecture, see
                                                          prepare_cpu_side_parallel()'s docstring)
                                  [--cpu-batches-per-worker N] (default 2, matches production's
                                                          BATCHES_PER_WORKER)
                                  [--cpu-bonus-fraction F] (default 0.0 -- Artur's 'CPU bonus
                                                          round' idea, 2026-08-29: a slice of
                                                          combined_size, on top of --cpu-fraction's
                                                          own split of the remainder, that CPU
                                                          picks up right after its first round
                                                          finishes, reusing the SAME already-forked
                                                          worker pool -- no second fork, so it's
                                                          safe even while the GPU thread is still
                                                          printing. FULL mode only, single value
                                                          only (no sweep support yet). See
                                                          run_split_three_way()'s docstring for the
                                                          full architecture and
                                                          run_full_scale_mode_three_way() for the
                                                          FULL-mode entry point this dispatches to)
"""
import concurrent.futures
import ctypes
import math
import mmap
import multiprocessing
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PRIME_SIEVE_DIR = os.path.dirname(_SCRIPT_DIR)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
import marking_two_tier_poc as gpu_mod  # reuses its exact, already-verified binary I/O format

MASK64 = (1 << 64) - 1
DEFAULT_ENGINE_SO = os.path.join(_PRIME_SIEVE_DIR, "prime_sieve_engine_v4.so")
DEFAULT_DUAL_ENGINE_SO = os.path.join(_SCRIPT_DIR, "dual_window_engine_poc.so")
DEFAULT_GPU_BINARY = os.path.join(_SCRIPT_DIR, "marking_two_tier_poc")
DEFAULT_GPU_CHUNK_SIZE = 20_000_000
DEFAULT_CPU_WORKERS = 24              # matches production's MAX_WORKERS (prime_sieve_v4_1.py)
DEFAULT_CPU_BATCHES_PER_WORKER = 2    # matches production's BATCHES_PER_WORKER

# Module-level globals for the multi-worker CPU path (prepare_cpu_side_parallel() /
# process_batch_cpu() / wait_cpu_side_parallel() below) -- module-level because forked worker
# processes inherit them via fork(), not via function arguments (mmap objects and loaded ctypes
# CDLL handles aren't picklable, so they can't cross a process boundary any other way). Mirrors
# prime_sieve_v4_1.py's own _shm_mmap/_shm_size/_lib module globals exactly.
_shm_mmap = None
_shm_size = 0
_cpu_worker_lib = None
_CPU_ENGINE_SO_PATH = None

# Same reasoning, for the dual-window engine (dual_window_engine_poc.c/.so -- see
# run_split_dual_window()'s docstring): a SEPARATE .so from the plain single-window engine above,
# since it exports a different function (generate_and_sieve_dual_window_atomic), so it needs its
# own module-level path/handle pair that forked workers inherit the same way.
_dual_worker_lib = None
_DUAL_ENGINE_SO_PATH = None


def to_hi_lo(distance):
    return distance >> 64, distance & MASK64


# -------------------------------------------------------------------------------------------
# CPU side: the real, unmodified engine, called directly via ctypes (no subprocess -- this
# genuinely runs concurrently with the GPU subprocess launched from another thread, since ctypes
# releases the GIL for the duration of a CDLL call).
# -------------------------------------------------------------------------------------------

def load_engine(engine_so_path):
    gpu_mod.build_engine_so_if_missing(engine_so_path)
    lib = ctypes.CDLL(engine_so_path)
    lib.generate_and_sieve_segment_bits.argtypes = [
        ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64,
        ctypes.c_uint64, ctypes.POINTER(ctypes.c_ubyte)
    ]
    lib.generate_and_sieve_segment_bits.restype = ctypes.c_int
    return lib


def run_cpu_side(lib, l_final, distance_hi, distance_lo, combined_size):
    """Calls the real, unmodified generate_and_sieve_segment_bits(). IMPORTANT: its real C
    signature (prime_sieve_engine_v4.c) is `(start, stop, distance_hi, distance_lo, window_m,
    out_dense_bits)` -- the first argument is the sieving-prime range's LOWER BOUND (always must
    be 2), NOT a thread count. This function has no parallelism at all (its own comment: "non-
    atomic variant, for single-threaded/ground-truth callers"). An earlier version of this file
    passed a configurable `cpu_threads` value (default 12 for STRESS/FULL mode) into this exact
    slot, which would have silently started sieving from prime 12 instead of 2 -- dropping
    2/3/5/7/11 from the CPU side's output. EXACT mode's own cases always happened to use the value
    2 for that parameter, so this bug never showed up there; it would only have corrupted
    STRESS/FULL mode's CPU-side results. Fixed by dropping the parameter entirely and always
    passing the literal 2 the real sieving start requires.

    This function is genuinely single-threaded, unlike production's real 24-worker-process
    architecture (generate_and_sieve_segment_bits_atomic) -- that gap is now addressed by
    prepare_cpu_side_parallel()/process_batch_cpu()/wait_cpu_side_parallel() below, used by
    run_split() whenever cpu_workers > 1. This single-threaded function is kept and still used
    for EXACT mode (small ranges, correctness is what matters there, not speed) and as the
    direct ground-truth call (run_engine_ground_truth() below) -- multiprocessing overhead would
    be pure waste for either of those.
    """
    n_bytes = (combined_size + 7) // 8
    buf = (ctypes.c_ubyte * n_bytes)()
    t0 = time.perf_counter()
    ret = lib.generate_and_sieve_segment_bits(2, l_final, distance_hi, distance_lo,
                                               combined_size, buf)
    elapsed = time.perf_counter() - t0
    if ret != 0:
        raise RuntimeError(f"CPU engine returned error code {ret}")
    return bytes(buf), elapsed


def load_dual_engine(dual_engine_so_path):
    """Loads dual_window_engine_poc.so (see that file's header) -- a SEPARATE, purely additive
    engine variant from load_engine()'s prime_sieve_engine_v4.so, built specifically for
    run_split_dual_window()'s single-pass CPU bonus round. Unlike load_engine(), there is no
    build_engine_so_if_missing() equivalent here (the .so is a PoC file, not part of production --
    build it explicitly via `gcc -O3 -shared -fPIC dual_window_engine_poc.c -o
    dual_window_engine_poc.so -lprimesieve -lstdc++ -lm`, or let
    build_and_run_cpu_gpu_split.sh do it)."""
    lib = ctypes.CDLL(dual_engine_so_path)
    argtypes = [
        ctypes.c_uint64, ctypes.c_uint64,
        ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64, ctypes.POINTER(ctypes.c_ubyte),
        ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64, ctypes.POINTER(ctypes.c_ubyte),
    ]
    lib.generate_and_sieve_dual_window.argtypes = argtypes
    lib.generate_and_sieve_dual_window.restype = ctypes.c_int
    lib.generate_and_sieve_dual_window_atomic.argtypes = argtypes
    lib.generate_and_sieve_dual_window_atomic.restype = ctypes.c_int
    return lib


def run_cpu_side_dual(lib_dual, l_final, dh1, dl1, window_m1, dh2, dl2, window_m2):
    """Single-threaded, non-atomic dual-window call -- the direct correctness/ground-truth-style
    counterpart of run_cpu_side(), used by EXACT mode (cpu_workers<=1) and by the sandbox test
    harness to verify dual_window_engine_poc.c's marking logic against two INDEPENDENT
    single-window run_engine_ground_truth() calls at the SAME (l_final, distance, window_m) pairs
    -- see run_exact_mode_dual_window()."""
    n_bytes1 = (window_m1 + 7) // 8
    n_bytes2 = (window_m2 + 7) // 8
    buf1 = (ctypes.c_ubyte * n_bytes1)() if window_m1 > 0 else None
    buf2 = (ctypes.c_ubyte * n_bytes2)() if window_m2 > 0 else None
    t0 = time.perf_counter()
    ret = lib_dual.generate_and_sieve_dual_window(2, l_final, dh1, dl1, window_m1, buf1,
                                                   dh2, dl2, window_m2, buf2)
    elapsed = time.perf_counter() - t0
    if ret != 0:
        raise RuntimeError(f"dual-window CPU engine returned error code {ret}")
    bits1 = bytes(buf1) if buf1 is not None else b""
    bits2 = bytes(buf2) if buf2 is not None else b""
    return bits1, bits2, elapsed


def run_engine_ground_truth(lib, l_final, distance_hi, distance_lo, combined_size):
    n_bytes = (combined_size + 7) // 8
    buf = (ctypes.c_ubyte * n_bytes)()
    ret = lib.generate_and_sieve_segment_bits(2, l_final, distance_hi, distance_lo,
                                               combined_size, buf)
    if ret != 0:
        raise RuntimeError(f"engine returned error code {ret}")
    return bytes(buf)


# -------------------------------------------------------------------------------------------
# CPU side, multi-worker: mirrors production's REAL parallel architecture
# (prime_sieve_v4_1.py's process_batch()/main_batch_scanner()), not just the single-threaded
# ground-truth call above. Needed because run_cpu_side() is genuinely single-threaded and gives
# an unfairly slow CPU number for STRESS/FULL mode -- production uses 24 OS processes, each
# atomically OR-ing into ONE shared mmap buffer, sharded by an equal-COST (not equal-count)
# split of the sieving-prime range [2, l_final), since a prime's marking cost is wildly
# non-uniform (p < window_m costs a whole marking loop, p >= window_m costs one O(1) write).
#
# The cost-model functions below (_cost_zone_a/_cost_zone_b/_cumulative_cost/
# _build_equal_cost_batches) are copied verbatim from prime_sieve_v4_1.py rather than imported,
# to keep this PoC file self-contained -- importing the real production module would also pull
# in its window_sharding/storage/benchmark-logging dependencies, which have nothing to do with
# this PoC and aren't guaranteed importable from this folder.
# -------------------------------------------------------------------------------------------

def _cost_zone_a(a, b, combined_size):
    def mert(x):
        x = max(x, 2.0)
        return math.log(math.log(x))
    return combined_size * max(mert(b) - mert(a), 1e-6)


def _cost_zone_b(a, b):
    def li_approx(x):
        x = max(x, 3.0)
        return x / math.log(x)
    return max(li_approx(b) - li_approx(a), 1.0)


def _cumulative_cost(x, threshold, combined_size):
    x = max(2.0, min(float(x), float(threshold if x <= threshold else x)))
    if x <= threshold:
        return _cost_zone_a(2, x, combined_size)
    return _cost_zone_a(2, threshold, combined_size) + _cost_zone_b(threshold, x)


def _build_equal_cost_batches(l_final, combined_size, n_batches):
    """Splits [2, l_final) into n_batches contiguous sieving-prime sub-ranges of roughly equal
    marking COST (not equal count), via binary search over the cost model above. Copied
    verbatim from prime_sieve_v4_1.py -- see that file's header for the full rationale."""
    threshold = min(combined_size, l_final)
    n = max(1, n_batches)

    def cost_upto(x):
        return _cumulative_cost(x, threshold, combined_size)

    total = cost_upto(l_final)
    if total <= 0 or l_final <= 2:
        return [[(2, max(3, l_final))]]

    boundaries = [2]
    lo = 2
    for i in range(1, n):
        target = total * i / n
        a, b = lo, l_final
        while a < b:
            mid = (a + b) // 2
            if cost_upto(mid) < target:
                a = mid + 1
            else:
                b = mid
        boundaries.append(a)
        lo = a
    boundaries.append(l_final)

    boundaries = sorted(set(g for g in boundaries if 2 <= g <= l_final))
    batches = []
    for a, b in zip(boundaries[:-1], boundaries[1:]):
        if a >= b:
            continue
        batches.append([(a, b)])
    if not batches:
        batches = [[(2, l_final)]]
    return batches


def _init_shared_cpu_buffer(n_bytes):
    """Allocates the ONE shared output buffer for the multi-worker CPU side. MUST complete
    BEFORE the ProcessPoolExecutor is created -- forked workers inherit the mapping via fork(),
    see prime_sieve_v4_1.py's _init_shared_buffer() docstring for the same requirement in
    production."""
    global _shm_mmap, _shm_size
    _shm_mmap = mmap.mmap(-1, n_bytes, flags=mmap.MAP_SHARED)
    _shm_size = n_bytes
    return _shm_mmap


def _load_cpu_worker_lib():
    global _cpu_worker_lib
    if _cpu_worker_lib is None:
        lib = ctypes.CDLL(_CPU_ENGINE_SO_PATH)
        lib.generate_and_sieve_segment_bits_atomic.argtypes = [
            ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64,
            ctypes.c_uint64, ctypes.POINTER(ctypes.c_ubyte)
        ]
        lib.generate_and_sieve_segment_bits_atomic.restype = ctypes.c_int
        _cpu_worker_lib = lib
    return _cpu_worker_lib


def process_batch_cpu(start_stop_list, distance, window_m, out_byte_offset=0):
    """Runs inside a forked worker process. Writes ATOMICALLY straight into the ONE shared
    buffer (module-level _shm_mmap/_shm_size, inherited via fork() -- see
    _init_shared_cpu_buffer()). Mirrors prime_sieve_v4_1.py's process_batch() verbatim.

    `out_byte_offset` (2026-08-29, added for run_split_three_way()'s CPU bonus round): lets
    multiple logically-separate "rounds" share ONE physically-allocated buffer at different byte
    offsets, instead of needing a second mmap -- important because a second mmap created in the
    PARENT process after the worker pool has already forked would NOT be visible to the
    already-running worker processes (they only inherited the ORIGINAL mapping at fork time).
    Writing into a different offset of the SAME already-inherited buffer sidesteps that
    entirely -- no new mmap, no new fork, just a different `window_m`/`distance` (both already
    per-call parameters, not fork-time globals) and a shifted output pointer."""
    lib = _load_cpu_worker_lib()
    buf_ctypes = (ctypes.c_ubyte * _shm_size).from_buffer(_shm_mmap)
    out_ptr = ctypes.cast(ctypes.byref(buf_ctypes, out_byte_offset), ctypes.POINTER(ctypes.c_ubyte))
    distance_hi = distance >> 64
    distance_lo = distance & MASK64

    had_error = False
    for start, stop in start_stop_list:
        code = lib.generate_and_sieve_segment_bits_atomic(start, stop, distance_hi,
                                                            distance_lo, window_m, out_ptr)
        if code != 0:
            had_error = True
    return had_error


def _load_dual_worker_lib():
    global _dual_worker_lib
    if _dual_worker_lib is None:
        _dual_worker_lib = load_dual_engine(_DUAL_ENGINE_SO_PATH)
    return _dual_worker_lib


def process_batch_cpu_dual(start_stop_list, distance1, window_m1, out_byte_offset1,
                            distance2, window_m2, out_byte_offset2):
    """Dual-window counterpart of process_batch_cpu() -- runs inside a forked worker process,
    walking its assigned sieving-prime sub-ranges via dual_window_engine_poc.c's
    generate_and_sieve_dual_window_atomic(), which marks BOTH (distance, window_m) targets per
    prime found in a SINGLE primesieve pass. This is the whole point of the dual-window engine
    (see that file's header): run_split_three_way()'s round1/round2 approach called
    process_batch_cpu() TWICE over the same [2, l_final) range -- once per round -- duplicating
    the dominant generation cost; this function calls the dual-window engine ONCE per batch,
    covering both windows in the same walk, so that cost is paid exactly once regardless of how
    many logical CPU "rounds" get folded in.

    Both windows share the SAME physical buffer (module-level _shm_mmap/_shm_size, inherited via
    fork()), at their own byte offsets -- same layout as process_batch_cpu()'s out_byte_offset,
    just two of them here instead of one. `window_m2=0` (bonus round empty) degenerates correctly
    -- see dual_window_engine_poc.c's mark_one()."""
    lib = _load_dual_worker_lib()
    buf_ctypes = (ctypes.c_ubyte * _shm_size).from_buffer(_shm_mmap)
    out_ptr1 = ctypes.cast(ctypes.byref(buf_ctypes, out_byte_offset1),
                            ctypes.POINTER(ctypes.c_ubyte))
    out_ptr2 = ctypes.cast(ctypes.byref(buf_ctypes, out_byte_offset2),
                            ctypes.POINTER(ctypes.c_ubyte))
    d1_hi, d1_lo = distance1 >> 64, distance1 & MASK64
    d2_hi, d2_lo = distance2 >> 64, distance2 & MASK64

    had_error = False
    for start, stop in start_stop_list:
        code = lib.generate_and_sieve_dual_window_atomic(start, stop, d1_hi, d1_lo, window_m1,
                                                           out_ptr1, d2_hi, d2_lo, window_m2,
                                                           out_ptr2)
        if code != 0:
            had_error = True
    return had_error


def _create_cpu_executor(engine_so_path, total_n_bytes, max_workers):
    """Allocates the shared buffer (sized `total_n_bytes` -- may cover MORE than one round's own
    combined_size, see run_split_three_way()) and fork()s the worker pool, WITHOUT submitting any
    work yet. Split out of prepare_cpu_side_parallel() (2026-08-29) so run_split_three_way() can
    create one pool and submit to it multiple times (multiple "rounds") without a second fork."""
    global _CPU_ENGINE_SO_PATH, _cpu_worker_lib
    _CPU_ENGINE_SO_PATH = engine_so_path
    _cpu_worker_lib = None  # reset so a fresh call always re-loads against the right .so
    _init_shared_cpu_buffer(total_n_bytes)
    ctx = multiprocessing.get_context("fork")  # REQUIRED, not spawn/forkserver -- see
                                                # _init_shared_cpu_buffer()'s docstring
    return ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx)


def _submit_cpu_round(executor, l_final, distance, combined_size, max_workers, batches_per_worker,
                       out_byte_offset=0):
    """Submits ONE round's batches to an ALREADY-CREATED executor (from _create_cpu_executor()) --
    does NOT fork. `combined_size<=0` submits nothing and returns an empty future list (a round
    with no work, e.g. cpu_fraction=0.0's round 1)."""
    if combined_size <= 0:
        return []
    n_batches = max(1, max_workers * batches_per_worker)
    batches = _build_equal_cost_batches(l_final, combined_size, n_batches)
    return [executor.submit(process_batch_cpu, batch, distance, combined_size, out_byte_offset)
            for batch in batches]


def _create_dual_cpu_executor(dual_engine_so_path, total_n_bytes, max_workers):
    """Dual-window counterpart of _create_cpu_executor() -- same shared-buffer-then-fork
    mechanics, but sets up the DUAL engine's module-level path/handle pair
    (_DUAL_ENGINE_SO_PATH/_dual_worker_lib) instead of the single-window one, so forked workers
    load dual_window_engine_poc.so via _load_dual_worker_lib()."""
    global _DUAL_ENGINE_SO_PATH, _dual_worker_lib
    _DUAL_ENGINE_SO_PATH = dual_engine_so_path
    _dual_worker_lib = None  # reset so a fresh call always re-loads against the right .so
    _init_shared_cpu_buffer(total_n_bytes)
    ctx = multiprocessing.get_context("fork")
    return ProcessPoolExecutor(max_workers=max_workers, mp_context=ctx)


def _submit_cpu_round_dual(executor, l_final, distance1, window_m1, out_byte_offset1,
                            distance2, window_m2, out_byte_offset2, max_workers,
                            batches_per_worker):
    """Builds ONE set of equal-cost batches over [2, l_final) and submits them ONCE to an
    already-created executor, each batch calling process_batch_cpu_dual() -- marking BOTH windows
    in the SAME primesieve walk per worker, instead of run_split_three_way()'s two separate
    sequential submission rounds (which duplicated the dominant generation cost -- see
    dual_window_engine_poc.c's header for the real-hardware numbers that motivated this).

    Batching threshold uses max(window_m1, window_m2) as an approximation for the equal-COST
    split -- this only affects how evenly work is spread among the worker processes (some workers
    might get a slightly cost-imbalanced share if window_m1 and window_m2 differ a lot), NOT
    correctness: each batch still calls the dual engine with BOTH windows' own real (distance,
    window_m) values, so every prime is checked against its true marking rule regardless of which
    batch happened to process it."""
    threshold_size = max(window_m1, window_m2)
    n_batches = max(1, max_workers * batches_per_worker)
    batches = _build_equal_cost_batches(l_final, threshold_size, n_batches)
    return [executor.submit(process_batch_cpu_dual, batch, distance1, window_m1, out_byte_offset1,
                             distance2, window_m2, out_byte_offset2)
            for batch in batches]


def _wait_batches(futures):
    """Waits for an already-submitted set of futures, raising if any batch reported an error.
    Does not read the buffer or shut down the executor -- see wait_cpu_side_parallel() for the
    single-round version that does both, and run_split_three_way() for the multi-round version
    that defers both until the LAST round finishes."""
    errors = 0
    for fut in concurrent.futures.as_completed(futures):
        if fut.result():
            errors += 1
    if errors:
        raise RuntimeError(f"CPU parallel engine: {errors} batch(es) returned an error code")


def prepare_cpu_side_parallel(engine_so_path, l_final, distance, combined_size, max_workers,
                               batches_per_worker, total_n_bytes=None, out_byte_offset=0):
    """PHASE 1 of the multi-worker CPU side -- MUST be called before any other thread in this
    process starts doing its own work (concretely: before run_split() starts the GPU worker
    thread, which streams its subprocess's stderr via constant print() calls). Allocates the
    shared buffer and fork()s all worker processes via ProcessPoolExecutor, submitting every
    batch up front.

    WHY THIS ORDERING MATTERS: fork() in a multi-threaded process only clones the CALLING
    thread -- any OTHER thread's in-progress work (including a Python-level lock it happens to
    be holding at that exact instant, e.g. the stdout lock a concurrent print() call holds) is
    simply gone in the child, frozen mid-acquisition. If a forked worker process (or any later
    fork() call) ever needs that same lock, it deadlocks forever. run_split() runs the GPU side
    in its own Python thread that calls print() constantly (streaming its subprocess's stderr
    live -- see run_gpu_side()), so doing the CPU side's forking DURING that concurrent printing
    would be a genuine, real hazard, not a hypothetical one. Splitting into a prepare/wait pair
    sidesteps it entirely: every fork() this ever does happens here, called from run_split()
    itself before the GPU thread is started; the second phase (wait_cpu_side_parallel) only
    WAITS on already-created futures and does no further forking, so it's safe to run
    concurrently with the GPU thread's printing.

    `total_n_bytes`/`out_byte_offset` (2026-08-29): thin passthrough to
    _create_cpu_executor()/_submit_cpu_round() for run_split_three_way()'s benefit -- unused by
    the plain 2-way run_split(), which leaves both at their defaults (buffer sized exactly to
    this call's own combined_size, written at offset 0), preserving this function's original
    behavior exactly.
    """
    n_bytes = total_n_bytes if total_n_bytes is not None else (combined_size + 7) // 8
    executor = _create_cpu_executor(engine_so_path, n_bytes, max_workers)
    futures = _submit_cpu_round(executor, l_final, distance, combined_size, max_workers,
                                 batches_per_worker, out_byte_offset)
    return executor, futures, n_bytes, len(futures)


def wait_cpu_side_parallel(executor, futures, n_bytes, t_start):
    """PHASE 2: waits for all already-submitted batches (from prepare_cpu_side_parallel) to
    finish, reads the shared buffer out to a plain bytes object, and cleans up. Does NOT fork --
    safe to run concurrently with the GPU worker thread's printing."""
    errors = 0
    for fut in concurrent.futures.as_completed(futures):
        if fut.result():
            errors += 1
    executor.shutdown(wait=True)
    elapsed = time.perf_counter() - t_start
    bits = bytes(_shm_mmap[:n_bytes])
    _shm_mmap.close()
    if errors:
        raise RuntimeError(f"CPU parallel engine: {errors} batch(es) returned an error code")
    return bits, elapsed


# -------------------------------------------------------------------------------------------
# GPU side: reuses marking_two_tier_poc's binary I/O format unchanged, but streams its stderr
# live instead of capturing it silently -- learned the hard way earlier today that a captured,
# only-shown-at-exit subprocess makes a genuinely slow (but fine) run indistinguishable from a
# real hang.
# -------------------------------------------------------------------------------------------

def run_gpu_side(binary, l_final, distance_hi, distance_lo, combined_size, chunk_size,
                  num_gen_threads, tag):
    in_path = os.path.join(_SCRIPT_DIR, f"_split_gpu_input_{tag}.bin")
    out_path = os.path.join(_SCRIPT_DIR, f"_split_gpu_output_{tag}.bin")
    gpu_mod.write_input(in_path, l_final, distance_hi, distance_lo, combined_size, chunk_size,
                         num_gen_threads)
    proc = subprocess.Popen([binary, in_path, out_path], stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE, text=True, bufsize=1)
    for line in proc.stderr:
        print("[gpu] " + line, end="", flush=True)
    proc.wait()
    try:
        os.remove(in_path)
    except OSError:
        pass
    if proc.returncode != 0:
        raise RuntimeError(f"GPU binary exited with code {proc.returncode}")
    bits, counts, timings = gpu_mod.read_output(out_path)
    try:
        os.remove(out_path)
    except OSError:
        pass
    return bits, counts, timings


# -------------------------------------------------------------------------------------------
# The split itself
# -------------------------------------------------------------------------------------------

def split_window(distance, combined_size, cpu_fraction, l_final=None, align=64):
    """Splits [distance, distance+combined_size) into a CPU sub-window
    [distance, distance+split) and a GPU sub-window [distance+split, distance+combined_size).
    `split` is rounded to the nearest multiple of `align` bits so each independently-computed
    piece's own byte/padding boundary lines up exactly with a plain concatenation -- no bit
    shifting needed to stitch the two outputs back together.

    If `l_final` is not given, it is derived from the FULL original window
    (isqrt(distance+combined_size)+1) -- correct for STRESS/FULL mode, where this models a real
    floor and l_final genuinely depends on the whole window's magnitude. EXACT mode passes
    l_final explicitly instead: it uses a huge `distance` in one case specifically to exercise the
    distance_hi != 0 (u128) branch, and deriving l_final from THAT distance would blow it up to
    ~2^32 (since isqrt(2^64) = 2^32) regardless of how small combined_size is, generating ~200
    million real sieving primes for what should be a near-instant correctness check -- exactly
    the kind of test-design bug that turned a should-be-instant EXACT case into one that took
    several real minutes on real hardware. Every prior file in this series avoids this by keeping
    l_final an independent, explicitly-chosen small value in its own EXACT cases; this function
    now supports the same pattern.
    """
    if l_final is None:
        l_final = math.isqrt(distance + combined_size) + 1
    # cpu_fraction<=0.0 / >=1.0 must give an EXACT 0 or EXACT combined_size split -- the
    # align-rounding below can otherwise leave a nonzero remainder on the "empty" side whenever
    # combined_size isn't itself a multiple of `align` (e.g. combined_size=5000, align=64:
    # round(5000/64)*64 = 4992, not 5000), silently breaking the cpu_fraction=0.0/1.0 edge cases
    # that exist specifically to exercise the empty-side code path.
    if cpu_fraction <= 0.0:
        split = 0
    elif cpu_fraction >= 1.0:
        split = combined_size
    else:
        split = int(round(combined_size * cpu_fraction / align)) * align
        split = max(0, min(combined_size, split))
    combined_size_cpu = split
    combined_size_gpu = combined_size - split
    distance_cpu = distance
    distance_gpu = distance + split
    return l_final, distance_cpu, combined_size_cpu, distance_gpu, combined_size_gpu


def run_split(lib, gpu_binary, gpu_gen_threads, gpu_chunk_size,
              distance, combined_size, cpu_fraction, tag, l_final=None,
              engine_so_path=None, cpu_workers=1, cpu_batches_per_worker=2):
    """cpu_workers=1 (the default, used by EXACT mode) keeps the original single-threaded
    run_cpu_side() path. cpu_workers>1 (used by STRESS/FULL mode) switches to the multi-worker
    prepare_cpu_side_parallel()/wait_cpu_side_parallel() path -- see that pair's own docstrings
    for why ALL of that path's fork()-ing must happen here, in this function, BEFORE the GPU
    worker thread (which prints constantly) is started below."""
    l_final, distance_cpu, cs_cpu, distance_gpu, cs_gpu = split_window(
        distance, combined_size, cpu_fraction, l_final=l_final)
    dh_cpu, dl_cpu = to_hi_lo(distance_cpu)
    dh_gpu, dl_gpu = to_hi_lo(distance_gpu)

    result = {}
    errors = []

    # PHASE 1 of the multi-worker CPU path (if enabled): must run here, before t_gpu is started
    # below -- see prepare_cpu_side_parallel()'s docstring for why.
    cpu_parallel_ctx = None
    if cs_cpu > 0 and cpu_workers > 1:
        if not engine_so_path:
            raise ValueError("cpu_workers > 1 requires engine_so_path")
        t_cpu_start = time.perf_counter()
        executor, futures, n_bytes, n_batches = prepare_cpu_side_parallel(
            engine_so_path, l_final, distance_cpu, cs_cpu, cpu_workers, cpu_batches_per_worker)
        print(f"[cpu] parallel: {n_batches} equal-cost batches submitted to {cpu_workers} "
              f"forked worker processes (cs_cpu={cs_cpu:,})", flush=True)
        cpu_parallel_ctx = (executor, futures, n_bytes, t_cpu_start)

    def cpu_worker():
        try:
            if cs_cpu == 0:
                result["cpu_bits"] = b""
                result["cpu_elapsed"] = 0.0
                return
            if cpu_parallel_ctx is not None:
                executor, futures, n_bytes, t_cpu_start = cpu_parallel_ctx
                bits, elapsed = wait_cpu_side_parallel(executor, futures, n_bytes, t_cpu_start)
                print(f"[cpu] parallel done: cs_cpu={cs_cpu:,} elapsed={elapsed:.4f}s "
                      f"({cpu_workers} workers)", flush=True)
            else:
                bits, elapsed = run_cpu_side(lib, l_final, dh_cpu, dl_cpu, cs_cpu)
                print(f"[cpu] done: cs_cpu={cs_cpu:,} elapsed={elapsed:.4f}s", flush=True)
            result["cpu_bits"] = bits
            result["cpu_elapsed"] = elapsed
        except Exception as e:
            errors.append(("cpu", e))

    def gpu_worker():
        try:
            if cs_gpu == 0:
                result["gpu_bits"] = b""
                result["gpu_counts"] = {}
                result["gpu_timings"] = (0.0,) * 6
                return
            bits, counts, timings = run_gpu_side(
                gpu_binary, l_final, dh_gpu, dl_gpu, cs_gpu, gpu_chunk_size, gpu_gen_threads, tag)
            result["gpu_bits"] = bits
            result["gpu_counts"] = counts
            result["gpu_timings"] = timings
        except Exception as e:
            errors.append(("gpu", e))

    t_wall_start = time.perf_counter()
    t_cpu = threading.Thread(target=cpu_worker)
    t_gpu = threading.Thread(target=gpu_worker)
    t_cpu.start()
    t_gpu.start()
    t_cpu.join()
    t_gpu.join()
    t_wall = time.perf_counter() - t_wall_start

    if errors:
        for who, e in errors:
            print(f"[{who} ERROR] {e}", file=sys.stderr)
        raise RuntimeError("split run failed -- see errors above")

    n_bytes_cpu = cs_cpu // 8  # exact: cs_cpu is a multiple of `align` (>=8), so no remainder
    n_bytes_gpu = (cs_gpu + 7) // 8
    combined_bits = result["cpu_bits"][:n_bytes_cpu] + result["gpu_bits"][:n_bytes_gpu]

    return {
        "l_final": l_final,
        "cs_cpu": cs_cpu, "cs_gpu": cs_gpu,
        "combined_bits": combined_bits,
        "cpu_elapsed": result.get("cpu_elapsed", 0.0),
        "gpu_counts": result.get("gpu_counts", {}),
        "gpu_timings": result.get("gpu_timings", (0.0,) * 6),
        "t_wall": t_wall,
    }


# -------------------------------------------------------------------------------------------
# THREE-WAY split: CPU round 1 + GPU + CPU "bonus" round 2 (Artur's idea, 2026-08-29)
# -------------------------------------------------------------------------------------------
# Motivation (see gpu_poc/README.md's "The real fix, not yet built" section for the full writeup):
# the load-balance sweep found plain 50/50 already near-optimal for a SINGLE fixed split, because
# CPU's own marking cost grows superlinearly with its own share -- giving CPU a bigger up-front
# slice just makes CPU itself the new long pole. But GPU is consistently the long pole at 50/50
# (its fixed sieving-prime-generation cost dominates), and CPU reliably finishes its round well
# before GPU does. Artur's idea: instead of a single fixed split, give CPU a SECOND, smaller
# "bonus" slice of the range to pick up the instant its first slice is done, using its own spare
# capacity while GPU is still working -- shrinking GPU's own share (and therefore its wall time)
# without ever growing CPU's SINGLE round large enough to make CPU the new long pole.
#
# This is a restricted, concrete version of the full "shared work queue" idea Artur and I discussed
# (many small fragments, either device pulls the next one the instant it's free) -- just ONE extra
# CPU round instead of N, but built on the same key mechanical fact that makes it safe: a
# ProcessPoolExecutor's forked worker processes stay alive across multiple .submit() calls, so the
# bonus round's batches can be submitted to the SAME already-forked pool from round 1 -- no second
# fork, so no risk of forking during the GPU thread's concurrent stderr-printing (see
# prepare_cpu_side_parallel()'s docstring for why that would be a real hazard).


def split_window_three_way(distance, combined_size, cpu_fraction, cpu_bonus_fraction,
                            l_final=None, align=64):
    """Splits [distance, distance+combined_size) into THREE disjoint, contiguous sub-windows,
    laid out back-to-back with no gaps or overlaps:

        [distance,                distance+cs_cpu1)              -- CPU round 1
        [distance+cs_cpu1,        distance+cs_cpu1+cs_gpu)       -- GPU
        [distance+cs_cpu1+cs_gpu, distance+combined_size)        -- CPU round 2 ("bonus")

    `cpu_bonus_fraction` is a fraction of the FULL combined_size, carved out first as the round-2
    slice; `cpu_fraction` then splits what's LEFT (combined_size - bonus) between CPU round 1 and
    GPU, exactly like split_window() does for the plain 2-way case. cpu_bonus_fraction=0.0
    degenerates to split_window()'s own split exactly (cs_cpu2=0, no round 2 at all).

    Every boundary is rounded to the nearest multiple of `align` bits first, same reasoning as
    split_window(): each independently-computed piece's own byte boundary then lines up exactly
    for a plain three-way concatenation, no bit-shifting needed."""
    if l_final is None:
        l_final = math.isqrt(distance + combined_size) + 1

    def _round_align(x):
        return int(round(x / align)) * align

    if cpu_bonus_fraction <= 0.0:
        bonus = 0
    else:
        bonus = _round_align(combined_size * cpu_bonus_fraction)
        bonus = max(0, min(combined_size, bonus))
    remaining = combined_size - bonus

    if cpu_fraction <= 0.0:
        split = 0
    elif cpu_fraction >= 1.0:
        split = remaining
    else:
        split = _round_align(remaining * cpu_fraction)
        split = max(0, min(remaining, split))

    cs_cpu1 = split
    cs_gpu = remaining - split
    cs_cpu2 = bonus

    return {
        "l_final": l_final,
        "cs_cpu1": cs_cpu1, "cs_gpu": cs_gpu, "cs_cpu2": cs_cpu2,
        "distance_cpu1": distance,
        "distance_gpu": distance + cs_cpu1,
        "distance_cpu2": distance + cs_cpu1 + cs_gpu,
    }


def run_split_three_way(lib, gpu_binary, gpu_gen_threads, gpu_chunk_size,
                         distance, combined_size, cpu_fraction, cpu_bonus_fraction, tag,
                         l_final=None, engine_so_path=None, cpu_workers=1,
                         cpu_batches_per_worker=2):
    """Three-way version of run_split(): CPU round 1 and GPU run concurrently (same as the plain
    2-way split); the moment CPU round 1 finishes, it submits a SECOND ("bonus") batch of work to
    the SAME already-forked worker pool, covering the round-2 window carved out by
    split_window_three_way(), while GPU is (typically) still working on its own, now-smaller
    share. cpu_bonus_fraction=0.0 makes this behave identically to run_split().

    cpu_workers=1 (EXACT mode) runs both CPU rounds sequentially via the original single-threaded
    run_cpu_side(), matching run_split()'s own cpu_workers=1 fallback -- correctness only here,
    not speed (a real "bonus round" only pays off with the multi-process path, since single-
    threaded round 2 would just serialize after round 1 with no pipelining benefit at all).

    REAL-HARDWARE RESULT (2026-08-29): NEGATIVE -- confirmed correct (EXACT mode, 14/14 cases)
    but SLOWER than a plain 2-way split at the same total combined_size (see
    run_full_scale_mode_three_way()'s own docstring for the numbers and root cause). Reusing the
    same forked executor for round 2 avoids re-forking, but each round still independently walks
    the full [2, l_final) sieving-prime range to build its own batches -- the actual dominant
    cost in this whole file -- so round 2 duplicates most of round 1's generation cost instead of
    avoiding it. This function is being kept (and its correctness is real) as the necessary first
    step toward a proper fix: a single-pass, dual-window marking primitive would need this exact
    three-window bookkeeping (offsets, distances, byte layout) as its foundation."""
    split = split_window_three_way(distance, combined_size, cpu_fraction, cpu_bonus_fraction,
                                    l_final=l_final)
    l_final = split["l_final"]
    cs_cpu1, cs_gpu, cs_cpu2 = split["cs_cpu1"], split["cs_gpu"], split["cs_cpu2"]
    distance_cpu1 = split["distance_cpu1"]
    distance_gpu = split["distance_gpu"]
    distance_cpu2 = split["distance_cpu2"]
    dh_cpu1, dl_cpu1 = to_hi_lo(distance_cpu1)
    dh_gpu, dl_gpu = to_hi_lo(distance_gpu)
    dh_cpu2, dl_cpu2 = to_hi_lo(distance_cpu2)

    n_bytes_cpu1 = cs_cpu1 // 8  # exact: align (>=8) guarantees no remainder, same as split_window()
    n_bytes_cpu2 = cs_cpu2 // 8

    result = {}
    errors = []

    # PHASE 1 of the multi-worker CPU path (if enabled): must run here, before t_gpu starts below
    # -- same ordering requirement as run_split(), see prepare_cpu_side_parallel()'s docstring.
    # The buffer is sized for BOTH CPU rounds up front (round 2 writes at byte offset
    # n_bytes_cpu1 of the SAME buffer -- see process_batch_cpu()'s docstring for why a second
    # mmap created later would NOT be visible to the already-forked workers).
    cpu_parallel_ctx = None
    if (cs_cpu1 > 0 or cs_cpu2 > 0) and cpu_workers > 1:
        if not engine_so_path:
            raise ValueError("cpu_workers > 1 requires engine_so_path")
        t_cpu_start = time.perf_counter()
        total_n_bytes = n_bytes_cpu1 + n_bytes_cpu2
        executor = _create_cpu_executor(engine_so_path, total_n_bytes, cpu_workers)
        if cs_cpu1 > 0:
            # Normal case: round 1 submitted now (also forces the pool to fully spin up its
            # worker processes safely, before the GPU thread starts printing); round 2 is
            # submitted later, from inside the CPU thread, once round 1's futures resolve.
            futures_first = _submit_cpu_round(executor, l_final, distance_cpu1, cs_cpu1,
                                               cpu_workers, cpu_batches_per_worker,
                                               out_byte_offset=0)
            print(f"[cpu] round 1: {len(futures_first)} equal-cost batches submitted to "
                  f"{cpu_workers} forked worker processes (cs_cpu1={cs_cpu1:,})", flush=True)
            cpu_parallel_ctx = ("normal", executor, futures_first, total_n_bytes, t_cpu_start)
        else:
            # cs_cpu1 == 0 (e.g. cpu_fraction=0.0): there's no separate round 1 to wait for, so
            # submit round 2's real work directly here instead -- this ALSO safely forces the
            # pool to spin up before the GPU thread starts, avoiding a fork-during-concurrent-
            # printing hazard on what would otherwise be this pool's very first submit() call.
            futures_only = _submit_cpu_round(executor, l_final, distance_cpu2, cs_cpu2,
                                              cpu_workers, cpu_batches_per_worker,
                                              out_byte_offset=n_bytes_cpu1)
            print(f"[cpu] round 2 (bonus, no separate round 1): {len(futures_only)} equal-cost "
                  f"batches submitted to {cpu_workers} forked worker processes "
                  f"(cs_cpu2={cs_cpu2:,})", flush=True)
            cpu_parallel_ctx = ("bonus_only", executor, futures_only, total_n_bytes, t_cpu_start)

    def cpu_worker():
        try:
            if cs_cpu1 == 0 and cs_cpu2 == 0:
                result["cpu1_bits"] = b""
                result["cpu2_bits"] = b""
                result["cpu1_elapsed"] = 0.0
                result["cpu2_elapsed"] = 0.0
                return
            if cpu_parallel_ctx is not None:
                mode, executor, futures_first, total_n_bytes, t_cpu_start = cpu_parallel_ctx
                if mode == "normal":
                    _wait_batches(futures_first)
                    cpu1_elapsed = time.perf_counter() - t_cpu_start
                    print(f"[cpu] round 1 done: cs_cpu1={cs_cpu1:,} elapsed={cpu1_elapsed:.4f}s "
                          f"({cpu_workers} workers)", flush=True)

                    t_cpu2_start = time.perf_counter()
                    futures2 = _submit_cpu_round(executor, l_final, distance_cpu2, cs_cpu2,
                                                  cpu_workers, cpu_batches_per_worker,
                                                  out_byte_offset=n_bytes_cpu1)
                    if futures2:
                        print(f"[cpu] round 2 (bonus): {len(futures2)} equal-cost batches "
                              f"submitted to the SAME {cpu_workers} worker processes "
                              f"(cs_cpu2={cs_cpu2:,}, no new fork)", flush=True)
                        _wait_batches(futures2)
                    cpu2_elapsed = time.perf_counter() - t_cpu2_start
                    if cs_cpu2 > 0:
                        print(f"[cpu] round 2 done: cs_cpu2={cs_cpu2:,} "
                              f"elapsed={cpu2_elapsed:.4f}s", flush=True)
                else:  # "bonus_only" -- cs_cpu1 was 0, everything already submitted up front
                    _wait_batches(futures_first)
                    cpu1_elapsed = 0.0
                    cpu2_elapsed = time.perf_counter() - t_cpu_start
                    print(f"[cpu] round 2 (bonus, no separate round 1) done: "
                          f"cs_cpu2={cs_cpu2:,} elapsed={cpu2_elapsed:.4f}s", flush=True)

                executor.shutdown(wait=True)
                full_bits = bytes(_shm_mmap[:total_n_bytes])
                _shm_mmap.close()
                result["cpu1_bits"] = full_bits[:n_bytes_cpu1]
                result["cpu2_bits"] = full_bits[n_bytes_cpu1:n_bytes_cpu1 + n_bytes_cpu2]
                result["cpu1_elapsed"] = cpu1_elapsed
                result["cpu2_elapsed"] = cpu2_elapsed
            else:
                # cpu_workers<=1: sequential single-threaded rounds, correctness-only (EXACT mode)
                bits1, elapsed1 = (run_cpu_side(lib, l_final, dh_cpu1, dl_cpu1, cs_cpu1)
                                    if cs_cpu1 > 0 else (b"", 0.0))
                bits2, elapsed2 = (run_cpu_side(lib, l_final, dh_cpu2, dl_cpu2, cs_cpu2)
                                    if cs_cpu2 > 0 else (b"", 0.0))
                result["cpu1_bits"] = bits1
                result["cpu2_bits"] = bits2
                result["cpu1_elapsed"] = elapsed1
                result["cpu2_elapsed"] = elapsed2
        except Exception as e:
            errors.append(("cpu", e))

    def gpu_worker():
        try:
            if cs_gpu == 0:
                result["gpu_bits"] = b""
                result["gpu_counts"] = {}
                result["gpu_timings"] = (0.0,) * 6
                return
            bits, counts, timings = run_gpu_side(
                gpu_binary, l_final, dh_gpu, dl_gpu, cs_gpu, gpu_chunk_size, gpu_gen_threads, tag)
            result["gpu_bits"] = bits
            result["gpu_counts"] = counts
            result["gpu_timings"] = timings
        except Exception as e:
            errors.append(("gpu", e))

    t_wall_start = time.perf_counter()
    t_cpu = threading.Thread(target=cpu_worker)
    t_gpu = threading.Thread(target=gpu_worker)
    t_cpu.start()
    t_gpu.start()
    t_cpu.join()
    t_gpu.join()
    t_wall = time.perf_counter() - t_wall_start

    if errors:
        for who, e in errors:
            print(f"[{who} ERROR] {e}", file=sys.stderr)
        raise RuntimeError("three-way split run failed -- see errors above")

    n_bytes_gpu = (cs_gpu + 7) // 8
    combined_bits = (result.get("cpu1_bits", b"")[:n_bytes_cpu1] +
                      result.get("gpu_bits", b"")[:n_bytes_gpu] +
                      result.get("cpu2_bits", b"")[:n_bytes_cpu2])

    return {
        "l_final": l_final,
        "cs_cpu1": cs_cpu1, "cs_gpu": cs_gpu, "cs_cpu2": cs_cpu2,
        "combined_bits": combined_bits,
        "cpu1_elapsed": result.get("cpu1_elapsed", 0.0),
        "cpu2_elapsed": result.get("cpu2_elapsed", 0.0),
        "gpu_counts": result.get("gpu_counts", {}),
        "gpu_timings": result.get("gpu_timings", (0.0,) * 6),
        "t_wall": t_wall,
    }


def run_split_dual_window(lib, gpu_binary, gpu_gen_threads, gpu_chunk_size,
                           distance, combined_size, cpu_fraction, cpu_bonus_fraction, tag,
                           l_final=None, engine_so_path=None, dual_engine_so_path=None,
                           cpu_workers=1, cpu_batches_per_worker=2):
    """Second attempt at Artur's 'CPU bonus round' idea (2026-08-29), after run_split_three_way()
    was measured on real hardware to be a net LOSS (see that function's own docstring): instead
    of CPU doing two SEQUENTIAL sub-invocations (round 1, then round 2 on the same pool -- each
    independently re-walking [2, l_final)), this version submits ONE set of batches that each
    mark BOTH windows in a SINGLE primesieve pass, via dual_window_engine_poc.c's
    generate_and_sieve_dual_window_atomic(). The window/offset LAYOUT is identical to
    run_split_three_way() (reuses split_window_three_way() verbatim) -- only the CPU-side
    EXECUTION mechanism changes, from two rounds to one dual-marking pass.

    WORTH READING BEFORE trusting this to be a win: giving CPU a bigger TOTAL share
    (cs_cpu1+cs_cpu2, whether as one window or two) is mathematically close to just raising
    cpu_fraction directly in the plain 2-way run_split() -- and run_fraction_sweep_mode() already
    found that skewing cpu_fraction above 0.5 makes wall time monotonically WORSE (CPU's own
    dense-tier marking cost grows faster than what it saves GPU). What this function actually
    tests, that the fraction sweep didn't, is whether removing the DOUBLE generation-cost bug
    (the actual, confirmed root cause of run_split_three_way()'s 298.712s result) is enough to
    let a CPU-heavier split at least match the plain 50/50 baseline (~233s at 13.5B),
    or whether CPU-heavier splits lose for the same fundamental cost-shape reason the fraction
    sweep already found, independent of the double-generation bug. Both outcomes are informative;
    neither should be assumed going in.

    REAL-HARDWARE RESULT (2026-09-02, combined_size=13.5*10**9, cpu_fraction=0.5,
    cpu_bonus_fraction=0.15, cpu_workers=12, gpu_gen_threads=12): the double-generation-cost bug
    IS fixed -- cs_cpu1=5,737,500,032 + cs_cpu2=2,025,000,000 marked in ONE dual pass took
    cpu_elapsed=250.181s, vs. 296.723s (172.034s+124.689s) for the same two windows under
    run_split_three_way()'s two SEPARATE passes -- a real 46.5s / 15.7% CPU-side improvement, and
    t_wall=251.981s vs. 298.712s (46.7s / 15.6% faster overall). BUT it still does not match the
    plain 50/50 baseline (~233.2s interpolated at this scale) -- 251.981s is ~8.1% SLOWER. So both
    outcomes documented above turned out to be true at once: removing the double-generation bug was
    real and worth doing (this mechanism should always be preferred over run_split_three_way()'s
    round-based one whenever cpu_bonus_fraction>0), but it was not the WHOLE story -- CPU's own
    dense-tier marking cost growing faster than what it saves GPU (run_fraction_sweep_mode()'s
    finding) also holds here, independent of which mechanism assembles the CPU-heavier split. A
    CPU-heavier split (effective ~57.5% CPU share here) still loses to plain 50/50 even with the
    generation-duplication bug gone.

    cpu_workers=1 (EXACT mode) uses run_cpu_side_dual() -- the single-threaded, non-atomic dual
    call -- directly, matching run_split()/run_split_three_way()'s own cpu_workers=1 fallback
    pattern (correctness only, not speed)."""
    split = split_window_three_way(distance, combined_size, cpu_fraction, cpu_bonus_fraction,
                                    l_final=l_final)
    l_final = split["l_final"]
    cs_cpu1, cs_gpu, cs_cpu2 = split["cs_cpu1"], split["cs_gpu"], split["cs_cpu2"]
    distance_cpu1 = split["distance_cpu1"]
    distance_gpu = split["distance_gpu"]
    distance_cpu2 = split["distance_cpu2"]
    dh_cpu1, dl_cpu1 = to_hi_lo(distance_cpu1)
    dh_gpu, dl_gpu = to_hi_lo(distance_gpu)
    dh_cpu2, dl_cpu2 = to_hi_lo(distance_cpu2)

    n_bytes_cpu1 = cs_cpu1 // 8
    n_bytes_cpu2 = cs_cpu2 // 8

    result = {}
    errors = []

    cpu_parallel_ctx = None
    if (cs_cpu1 > 0 or cs_cpu2 > 0) and cpu_workers > 1:
        if not dual_engine_so_path:
            raise ValueError("cpu_workers > 1 requires dual_engine_so_path")
        t_cpu_start = time.perf_counter()
        total_n_bytes = n_bytes_cpu1 + n_bytes_cpu2
        executor = _create_dual_cpu_executor(dual_engine_so_path, total_n_bytes, cpu_workers)
        futures = _submit_cpu_round_dual(executor, l_final, distance_cpu1, cs_cpu1, 0,
                                          distance_cpu2, cs_cpu2, n_bytes_cpu1, cpu_workers,
                                          cpu_batches_per_worker)
        print(f"[cpu] dual-window pass: {len(futures)} equal-cost batches submitted to "
              f"{cpu_workers} forked worker processes, each marking BOTH windows in one "
              f"primesieve walk (cs_cpu1={cs_cpu1:,} cs_cpu2={cs_cpu2:,})", flush=True)
        cpu_parallel_ctx = (executor, futures, total_n_bytes, t_cpu_start)

    def cpu_worker():
        try:
            if cs_cpu1 == 0 and cs_cpu2 == 0:
                result["cpu1_bits"] = b""
                result["cpu2_bits"] = b""
                result["cpu_elapsed"] = 0.0
                return
            if cpu_parallel_ctx is not None:
                executor, futures, total_n_bytes, t_cpu_start = cpu_parallel_ctx
                _wait_batches(futures)
                cpu_elapsed = time.perf_counter() - t_cpu_start
                print(f"[cpu] dual-window pass done: cs_cpu1={cs_cpu1:,} cs_cpu2={cs_cpu2:,} "
                      f"elapsed={cpu_elapsed:.4f}s ({cpu_workers} workers)", flush=True)
                executor.shutdown(wait=True)
                full_bits = bytes(_shm_mmap[:total_n_bytes])
                _shm_mmap.close()
                result["cpu1_bits"] = full_bits[:n_bytes_cpu1]
                result["cpu2_bits"] = full_bits[n_bytes_cpu1:n_bytes_cpu1 + n_bytes_cpu2]
                result["cpu_elapsed"] = cpu_elapsed
            else:
                lib_dual = load_dual_engine(dual_engine_so_path)
                bits1, bits2, elapsed = run_cpu_side_dual(
                    lib_dual, l_final, dh_cpu1, dl_cpu1, cs_cpu1, dh_cpu2, dl_cpu2, cs_cpu2)
                print(f"[cpu] dual-window (single-threaded) done: cs_cpu1={cs_cpu1:,} "
                      f"cs_cpu2={cs_cpu2:,} elapsed={elapsed:.4f}s", flush=True)
                result["cpu1_bits"] = bits1
                result["cpu2_bits"] = bits2
                result["cpu_elapsed"] = elapsed
        except Exception as e:
            errors.append(("cpu", e))

    def gpu_worker():
        try:
            if cs_gpu == 0:
                result["gpu_bits"] = b""
                result["gpu_counts"] = {}
                result["gpu_timings"] = (0.0,) * 6
                return
            bits, counts, timings = run_gpu_side(
                gpu_binary, l_final, dh_gpu, dl_gpu, cs_gpu, gpu_chunk_size, gpu_gen_threads, tag)
            result["gpu_bits"] = bits
            result["gpu_counts"] = counts
            result["gpu_timings"] = timings
        except Exception as e:
            errors.append(("gpu", e))

    t_wall_start = time.perf_counter()
    t_cpu = threading.Thread(target=cpu_worker)
    t_gpu = threading.Thread(target=gpu_worker)
    t_cpu.start()
    t_gpu.start()
    t_cpu.join()
    t_gpu.join()
    t_wall = time.perf_counter() - t_wall_start

    if errors:
        for who, e in errors:
            print(f"[{who} ERROR] {e}", file=sys.stderr)
        raise RuntimeError("dual-window split run failed -- see errors above")

    n_bytes_gpu = (cs_gpu + 7) // 8
    combined_bits = (result.get("cpu1_bits", b"")[:n_bytes_cpu1] +
                      result.get("gpu_bits", b"")[:n_bytes_gpu] +
                      result.get("cpu2_bits", b"")[:n_bytes_cpu2])

    return {
        "l_final": l_final,
        "cs_cpu1": cs_cpu1, "cs_gpu": cs_gpu, "cs_cpu2": cs_cpu2,
        "combined_bits": combined_bits,
        "cpu_elapsed": result.get("cpu_elapsed", 0.0),
        "gpu_counts": result.get("gpu_counts", {}),
        "gpu_timings": result.get("gpu_timings", (0.0,) * 6),
        "t_wall": t_wall,
    }


# -------------------------------------------------------------------------------------------
# EXACT mode
# -------------------------------------------------------------------------------------------

def exact_case(lib, gpu_binary, tag, name, distance, combined_size, cpu_fraction, l_final,
               gpu_gen_threads, gpu_chunk_size):
    split = run_split(lib, gpu_binary, gpu_gen_threads, gpu_chunk_size,
                       distance, combined_size, cpu_fraction, tag, l_final=l_final)
    dh, dl = to_hi_lo(distance)
    truth_bits = run_engine_ground_truth(lib, split["l_final"], dh, dl, combined_size)
    n_bytes = (combined_size + 7) // 8
    got = split["combined_bits"][:n_bytes]
    truth = truth_bits[:n_bytes]
    mismatches = sum(1 for a, b in zip(got, truth) if a != b)
    ok = mismatches == 0 and len(got) == len(truth)
    status = "PASS" if ok else \
        f"FAIL ({mismatches} mismatched bytes, len got={len(got)} vs truth={len(truth)})"
    print(f"    [{name}] {status}  (cs_cpu={split['cs_cpu']:,} cs_gpu={split['cs_gpu']:,}, "
          f"cpu={split['cpu_elapsed']:.4f}s gpu_total={split['gpu_timings'][-1]:.4f}s "
          f"wall={split['t_wall']:.4f}s)")
    if not ok:
        # Bit-level dump so a real mismatch can be localized to the CPU segment, the GPU segment,
        # or the boundary between them, rather than just knowing "N bytes differ".
        cs_cpu = split["cs_cpu"]
        print(f"      DEBUG: combined_size={combined_size}  cs_cpu={cs_cpu}  "
              f"cs_gpu={split['cs_gpu']}  l_final={split['l_final']}")
        for byte_idx in range(min(len(got), len(truth))):
            if got[byte_idx] != truth[byte_idx]:
                bit_lo, bit_hi = byte_idx * 8, byte_idx * 8 + 7
                side = "CPU" if bit_hi < cs_cpu else ("GPU" if bit_lo >= cs_cpu else "BOUNDARY")
                print(f"      byte {byte_idx:3d} (bits {bit_lo}-{bit_hi}, {side}): "
                      f"got=0b{got[byte_idx]:08b}  truth=0b{truth[byte_idx]:08b}  "
                      f"xor=0b{got[byte_idx] ^ truth[byte_idx]:08b}")
    return ok


def exact_case_three_way(lib, gpu_binary, tag, name, distance, combined_size, cpu_fraction,
                          cpu_bonus_fraction, l_final, gpu_gen_threads, gpu_chunk_size):
    """Three-way counterpart of exact_case(): verifies CPU-round-1 + GPU + CPU-round-2-bonus,
    split-then-concatenated, matches a single unsplit, unchunked, single-threaded real-engine
    call over the full window byte-for-byte -- same discipline as the plain 2-way split's own
    EXACT cases, applied to the new three-window layout before ever touching real hardware."""
    split = run_split_three_way(lib, gpu_binary, gpu_gen_threads, gpu_chunk_size,
                                 distance, combined_size, cpu_fraction, cpu_bonus_fraction, tag,
                                 l_final=l_final)
    dh, dl = to_hi_lo(distance)
    truth_bits = run_engine_ground_truth(lib, split["l_final"], dh, dl, combined_size)
    n_bytes = (combined_size + 7) // 8
    got = split["combined_bits"][:n_bytes]
    truth = truth_bits[:n_bytes]
    mismatches = sum(1 for a, b in zip(got, truth) if a != b)
    ok = mismatches == 0 and len(got) == len(truth)
    status = "PASS" if ok else \
        f"FAIL ({mismatches} mismatched bytes, len got={len(got)} vs truth={len(truth)})"
    print(f"    [{name}] {status}  (cs_cpu1={split['cs_cpu1']:,} cs_gpu={split['cs_gpu']:,} "
          f"cs_cpu2={split['cs_cpu2']:,}, cpu1={split['cpu1_elapsed']:.4f}s "
          f"cpu2={split['cpu2_elapsed']:.4f}s gpu_total={split['gpu_timings'][-1]:.4f}s "
          f"wall={split['t_wall']:.4f}s)")
    if not ok:
        cs_cpu1, cs_gpu = split["cs_cpu1"], split["cs_gpu"]
        boundary2 = cs_cpu1 + cs_gpu
        print(f"      DEBUG: combined_size={combined_size}  cs_cpu1={cs_cpu1}  cs_gpu={cs_gpu}  "
              f"cs_cpu2={split['cs_cpu2']}  l_final={split['l_final']}")
        for byte_idx in range(min(len(got), len(truth))):
            if got[byte_idx] != truth[byte_idx]:
                bit_lo, bit_hi = byte_idx * 8, byte_idx * 8 + 7
                if bit_hi < cs_cpu1:
                    side = "CPU1"
                elif bit_lo >= boundary2:
                    side = "CPU2"
                elif bit_lo >= cs_cpu1 and bit_hi < boundary2:
                    side = "GPU"
                else:
                    side = "BOUNDARY"
                print(f"      byte {byte_idx:3d} (bits {bit_lo}-{bit_hi}, {side}): "
                      f"got=0b{got[byte_idx]:08b}  truth=0b{truth[byte_idx]:08b}  "
                      f"xor=0b{got[byte_idx] ^ truth[byte_idx]:08b}")
    return ok


def run_exact_mode_three_way(gpu_binary, engine_so_path):
    print("=" * 78)
    print("EXACT mode (three-way) -- CPU round1 + GPU + CPU round2 bonus vs. a single unsplit,")
    print("unchunked, single-threaded real-engine call over the full window")
    print("=" * 78)
    lib = load_engine(engine_so_path)

    # (tag, name, distance, combined_size, cpu_fraction, cpu_bonus_fraction, l_final) -- same
    # distance!=0 discipline as run_exact_mode()'s own cases (see that function's long comment
    # for why distance=0 is avoided here: prime_sieve_engine_v4.c's self-elimination guard has a
    # real quirk at distance=0 that only a split -- now with a THIRD window's own boundary --
    # would expose).
    cases = [
        ("case1", "balanced three-way, dense-only tier",
         10 ** 6, 10_000, 0.5, 0.2, 2_000),
        ("case2", "cpu_bonus_fraction=0.0 -- must degenerate to the plain 2-way split exactly",
         10 ** 6, 5_000, 0.5, 0.0, 31_781),
        ("case3", "cpu_fraction=0.0 (no round 1) + nonzero bonus -- exercises the "
         "'bonus_only' pool-startup path",
         10 ** 6, 5_000, 0.0, 0.3, 31_781),
        ("case4", "cpu_fraction=1.0 (GPU side empty) + nonzero bonus",
         10 ** 6, 5_000, 1.0, 0.2, 31_781),
        ("case5", "distance_hi != 0 (u128 branch), three-way mixed split",
         (1 << 64) + 12_345, 5_000, 0.4, 0.25, 31_781),
        ("case6", "uneven fractions (0.37 / 0.15) + oversized gen-threads",
         10 ** 6, 97, 0.37, 0.15, 200),
        ("case7", "tiny combined_size, sanity check at small scale",
         10 ** 6, 256, 0.5, 0.25, 1_000),
    ]
    all_pass = True
    for i, (tag, name, distance, cs, frac, bonus_frac, l_final) in enumerate(cases):
        gpu_gen_threads = 2 if i != 5 else 8  # case6 also exercises oversized gen-threads
        gpu_chunk_size = 50
        ok = exact_case_three_way(lib, gpu_binary, tag, name, distance, cs, frac, bonus_frac,
                                   l_final, gpu_gen_threads, gpu_chunk_size)
        all_pass = all_pass and ok
    return all_pass


def exact_case_dual_window(lib, gpu_binary, tag, name, distance, combined_size, cpu_fraction,
                            cpu_bonus_fraction, l_final, gpu_gen_threads, gpu_chunk_size,
                            dual_engine_so_path, cpu_workers=1, cpu_batches_per_worker=2):
    """Dual-window counterpart of exact_case_three_way() -- same window LAYOUT (reuses
    split_window_three_way() via run_split_dual_window()), same "single unsplit call over the
    full window" ground truth, but exercises run_split_dual_window()'s single-pass CPU
    mechanism (dual_window_engine_poc.c) instead of run_split_three_way()'s two-round mechanism.
    Runs with BOTH cpu_workers=1 (tests generate_and_sieve_dual_window(), the single-threaded
    non-atomic path) and cpu_workers>1 (tests generate_and_sieve_dual_window_atomic() via the
    real multi-process pool) depending on the `cpu_workers` argument -- callers should exercise
    both, not just one, since they're genuinely different code paths in dual_window_engine_poc.c
    and in this file's own orchestration."""
    split = run_split_dual_window(lib, gpu_binary, gpu_gen_threads, gpu_chunk_size,
                                   distance, combined_size, cpu_fraction, cpu_bonus_fraction, tag,
                                   l_final=l_final, dual_engine_so_path=dual_engine_so_path,
                                   cpu_workers=cpu_workers,
                                   cpu_batches_per_worker=cpu_batches_per_worker)
    dh, dl = to_hi_lo(distance)
    truth_bits = run_engine_ground_truth(lib, split["l_final"], dh, dl, combined_size)
    n_bytes = (combined_size + 7) // 8
    got = split["combined_bits"][:n_bytes]
    truth = truth_bits[:n_bytes]
    mismatches = sum(1 for a, b in zip(got, truth) if a != b)
    ok = mismatches == 0 and len(got) == len(truth)
    status = "PASS" if ok else \
        f"FAIL ({mismatches} mismatched bytes, len got={len(got)} vs truth={len(truth)})"
    print(f"    [{name}] {status}  (cs_cpu1={split['cs_cpu1']:,} cs_gpu={split['cs_gpu']:,} "
          f"cs_cpu2={split['cs_cpu2']:,}, cpu_workers={cpu_workers}, "
          f"cpu_elapsed={split['cpu_elapsed']:.4f}s "
          f"gpu_total={split['gpu_timings'][-1]:.4f}s wall={split['t_wall']:.4f}s)")
    if not ok:
        cs_cpu1, cs_gpu = split["cs_cpu1"], split["cs_gpu"]
        boundary2 = cs_cpu1 + cs_gpu
        print(f"      DEBUG: combined_size={combined_size}  cs_cpu1={cs_cpu1}  cs_gpu={cs_gpu}  "
              f"cs_cpu2={split['cs_cpu2']}  l_final={split['l_final']}  "
              f"cpu_workers={cpu_workers}")
        for byte_idx in range(min(len(got), len(truth))):
            if got[byte_idx] != truth[byte_idx]:
                bit_lo, bit_hi = byte_idx * 8, byte_idx * 8 + 7
                if bit_hi < cs_cpu1:
                    side = "CPU1"
                elif bit_lo >= boundary2:
                    side = "CPU2"
                elif bit_lo >= cs_cpu1 and bit_hi < boundary2:
                    side = "GPU"
                else:
                    side = "BOUNDARY"
                print(f"      byte {byte_idx:3d} (bits {bit_lo}-{bit_hi}, {side}): "
                      f"got=0b{got[byte_idx]:08b}  truth=0b{truth[byte_idx]:08b}  "
                      f"xor=0b{got[byte_idx] ^ truth[byte_idx]:08b}")
    return ok


def run_exact_mode_dual_window(gpu_binary, engine_so_path, dual_engine_so_path):
    print("=" * 78)
    print("EXACT mode (dual-window) -- CPU marks BOTH windows in ONE primesieve pass, vs. a")
    print("single unsplit, unchunked, single-threaded real-engine call over the full window")
    print("=" * 78)
    lib = load_engine(engine_so_path)

    # Same case set and distance!=0 discipline as run_exact_mode_three_way()'s own cases (see
    # run_exact_mode()'s long comment for the distance=0 self-elimination-guard quirk this
    # avoids) -- reused here so the two mechanisms (round-based vs single-pass) are exercised
    # against the SAME window layouts, making any behavioral difference easy to attribute to the
    # mechanism change rather than to different test inputs.
    cases = [
        ("case1", "balanced dual-window, dense-only tier", 10 ** 6, 10_000, 0.5, 0.2, 2_000),
        ("case2", "cpu_bonus_fraction=0.0 -- must degenerate to the plain 2-way split exactly",
         10 ** 6, 5_000, 0.5, 0.0, 31_781),
        ("case3", "cpu_fraction=0.0 (window1 empty) + nonzero window2",
         10 ** 6, 5_000, 0.0, 0.3, 31_781),
        ("case4", "cpu_fraction=1.0 (GPU side empty) + nonzero window2",
         10 ** 6, 5_000, 1.0, 0.2, 31_781),
        ("case5", "distance_hi != 0 (u128 branch), dual-window mixed split",
         (1 << 64) + 12_345, 5_000, 0.4, 0.25, 31_781),
        ("case6", "uneven fractions (0.37 / 0.15) + oversized gen-threads",
         10 ** 6, 97, 0.37, 0.15, 200),
        ("case7", "tiny combined_size, sanity check at small scale",
         10 ** 6, 256, 0.5, 0.25, 1_000),
    ]
    all_pass = True
    for i, (tag, name, distance, cs, frac, bonus_frac, l_final) in enumerate(cases):
        gpu_gen_threads = 2 if i != 5 else 8
        gpu_chunk_size = 50
        # cpu_workers=1 exercises the single-threaded non-atomic dual call directly.
        ok1 = exact_case_dual_window(lib, gpu_binary, tag + "-single", name + " [single-thread]",
                                      distance, cs, frac, bonus_frac, l_final, gpu_gen_threads,
                                      gpu_chunk_size, dual_engine_so_path, cpu_workers=1)
        # cpu_workers=4 exercises the real multi-process atomic path (small worker count is
        # plenty to prove correctness at these tiny EXACT-mode sizes -- speed isn't the point
        # here, see FULL mode for that).
        ok4 = exact_case_dual_window(lib, gpu_binary, tag + "-multi", name + " [4 workers]",
                                      distance, cs, frac, bonus_frac, l_final, gpu_gen_threads,
                                      gpu_chunk_size, dual_engine_so_path, cpu_workers=4,
                                      cpu_batches_per_worker=2)
        all_pass = all_pass and ok1 and ok4
    return all_pass


def run_exact_mode(gpu_binary, engine_so_path):
    print("=" * 78)
    print("EXACT mode -- CPU+GPU disjoint range split vs. a single unsplit, unchunked,")
    print("single-threaded real-engine call over the full window")
    print("=" * 78)
    lib = load_engine(engine_so_path)

    # (tag, name, distance, combined_size, cpu_fraction, l_final) -- l_final is ALWAYS given
    # explicitly here, independent of `distance`, per split_window()'s own docstring: deriving it
    # from a huge `distance` (case5's whole point) would blow it up to ~2^32, turning a
    # should-be-instant case into one that takes real minutes. Values otherwise mirror
    # marking_two_tier_poc.py's own proven-safe EXACT cases -- EXCEPT cases 5/6/7 below, which
    # deliberately do NOT copy that file's distance=0, for a subtle reason found via real-hardware
    # failures on this exact PoC (see the long comment right before this list closes).
    #
    # IMPORTANT, found by debugging real case5/6/7 FAILs: prime_sieve_engine_v4.c's own
    # self-elimination guard (`if (distance + start_pos <= p_val) start_pos += p_val;`) has a
    # latent quirk specifically at distance=0 -- since start_pos starts at 0, the check
    # `0 + 0 <= p_val` is ALWAYS true for any positive prime, so it unconditionally jumps
    # start_pos to p_val, i.e. it self-marks EVERY prime p < window_m as composite at its own
    # position. This is invisible at real floor scale (distance=10^25 always dwarfs every sieving
    # prime, so the guard never fires this way) and was even invisible in marking_two_tier_poc.py's
    # own EXACT tests, because there BOTH sides of the byte-for-byte comparison (ground truth and
    # the unsplit GPU kernel) run at the SAME distance=0 and reproduce the identical quirk, so they
    # agree and "pass" despite being wrong in an absolute number-theory sense. This split PoC is
    # the first place that actually exposes it: the split shifts the GPU sub-window's distance away
    # from 0 (distance_gpu = split), so ITS guard correctly stops self-marking primes that live
    # past the split boundary, while ground truth (still one unsplit distance=0 call over the whole
    # window) keeps marking them -- a real, reproducible divergence exactly at primes between the
    # split boundary and l_final. Confirmed by the bit-level diagnostic dump: the mismatched bytes
    # were EXACTLY at the true prime positions in that gap (67/71/73/79/83/89 for case5/6; the
    # primes in [128,256) for case7), always in the GPU segment, always got=0 (correctly left
    # prime) vs truth=1 (incorrectly self-marked composite) -- i.e. the SPLIT result was the
    # numerically CORRECT one, and the single-call "ground truth" was the one exhibiting the bug.
    # Fix here: give cases 5/6/7 a small nonzero distance (still << their own l_final is NOT
    # required -- just nonzero is enough to avoid the guard's `0+0<=p_val` special case), which
    # keeps each case's actual point (dense/sparse tier boundary, uneven split fraction, small
    # combined_size) fully intact while sidestepping the unrelated distance=0 quirk. This does NOT
    # fix the underlying quirk itself (out of scope for this split PoC -- it lives in the shared
    # production engine and only matters for windows starting exactly at 0, which real floor-25+
    # generation never does).
    cases = [
        ("case1", "even 50/50 split, dense-only tier", 0, 10_000, 0.5, 1_000),
        ("case2", "sparse-heavy tier, cpu_fraction=0.0 (all GPU, CPU side empty)",
         10 ** 9, 100, 0.0, 10_000),
        ("case3", "mixed tier, cpu_fraction=1.0 (all CPU, GPU side empty)",
         10 ** 9, 5_000, 1.0, 31_781),
        ("case4", "distance_hi != 0 (u128 branch), mixed split",
         (1 << 64) + 12_345, 5_000, 0.5, 31_781),
        ("case5", "boundary: combined_size == an actual prime (97)", 10 ** 6, 97, 0.5, 200),
        ("case6", "uneven split fraction (0.37) + oversized gen-threads",
         10 ** 6, 97, 0.37, 200),
        ("case7", "tiny combined_size, sanity check at small scale", 10 ** 6, 256, 0.5, 1_000),
    ]
    all_pass = True
    for i, (tag, name, distance, cs, frac, l_final) in enumerate(cases):
        gpu_gen_threads = 2 if i != 5 else 8  # case6 also exercises oversized gen-threads
        gpu_chunk_size = 50
        ok = exact_case(lib, gpu_binary, tag, name, distance, cs, frac, l_final,
                         gpu_gen_threads, gpu_chunk_size)
        all_pass = all_pass and ok
    return all_pass


# -------------------------------------------------------------------------------------------
# STRESS mode
# -------------------------------------------------------------------------------------------

def run_stress_mode(gpu_binary, engine_so_path, cpu_fraction, gpu_gen_threads,
                     gpu_chunk_size, cpu_workers, cpu_batches_per_worker):
    print()
    print("=" * 78)
    print("STRESS mode -- moderate scale, CPU+GPU disjoint range split")
    print("=" * 78)
    lib = load_engine(engine_so_path)
    floor = 25
    distance = 10 ** floor
    combined_size = 10 ** 8

    print(f"[*] distance=10^{floor}  combined_size={combined_size:,}  "
          f"cpu_fraction={cpu_fraction}  "
          f"gpu_gen_threads={gpu_gen_threads}  gpu_chunk_size={gpu_chunk_size:,}  "
          f"cpu_workers={cpu_workers}  cpu_batches_per_worker={cpu_batches_per_worker}")

    split = run_split(lib, gpu_binary, gpu_gen_threads, gpu_chunk_size,
                       distance, combined_size, cpu_fraction, "stress",
                       engine_so_path=engine_so_path, cpu_workers=cpu_workers,
                       cpu_batches_per_worker=cpu_batches_per_worker)
    _report_split(split)


def run_full_scale_mode(gpu_binary, engine_so_path, cpu_fraction, gpu_gen_threads,
                         gpu_chunk_size, cpu_workers, cpu_batches_per_worker,
                         combined_size=10 ** 10):
    """FULL mode (2026-08-28, extended 2026-08-28 with a combined_size override) -- the real
    floor-25 scale. Direct test of Artur's range-split idea: does running CPU on its own
    sub-window and GPU on its own disjoint sub-window, CONCURRENTLY, cover the full
    combined_size-number range faster than either device covering it all alone -- sidestepping
    every shared-buffer-contention problem this whole series has hit so far, since the two sides
    never touch the same bytes.

    FIRST REAL RESULT (combined_size=10**10, the original default, cpu_fraction=0.5,
    cpu_workers=24): t_wall=230.508s -- SLOWER than either device alone on the SAME 10-billion
    range (176.018s production CPU, 169.623s GPU solo), 1.31x/1.36x worse. Root cause, visible
    directly in the GPU timing breakdown: dense (gen=4.739s gpu=4.520s, the genuinely
    window-size-dependent marking work) vs sparse (gen=219.381s gpu=218.970s, dominated by
    enumerating sieving primes up to l_final via primesieve) -- generation of the sieving-prime
    base costs ~219s out of 225.7s total, and CRUCIALLY that cost depends on l_final (i.e. on
    `distance`), NOT on window size (combined_size). Splitting the WINDOW in half does NOT split
    this dominant cost -- both CPU and GPU must independently walk the ENTIRE [2, l_final) prime
    range to know which primes might hit their own sub-window, so the split DUPLICATES the
    dominant cost rather than dividing it; only the small window-size-dependent marking cost
    (~4.5s of ~230s) actually gets divided by the split.

    HYPOTHESIS this parameter tests: since l_final barely changes with combined_size at this
    distance (isqrt(10**25 + X) for X in the 10**9..10**11 range is the same to ~15+ significant
    figures), the dominant ~219s generation cost should stay roughly FIXED as combined_size
    grows, while only the small marking cost grows (still tiny either way) -- meaning the split's
    THROUGHPUT (numbers covered per second) should improve significantly at larger combined_size,
    since the fixed generation cost gets amortized over more marked numbers. If true, running at
    e.g. combined_size=2*10**10 or 3*10**10 should take only slightly longer than the 10**10 run
    above (not 2x/3x longer), which would make the split a net win over running production
    sequentially N times to cover the same total range (N * 176.018s).

    CONFIRMED (2026-08-28, real hardware, cpu_fraction=0.5, cpu_workers=24) -- SWEEP across four
    scales via run_full_sweep_mode(), advantage widening monotonically as predicted:
        combined_size=1*10**10: t_wall=230.508s -- 1.31x/1.36x SLOWER than either solo device.
        combined_size=2*10**10: t_wall=268.349s -- 0.76x/0.79x of 2x sequential (24%/21% FASTER).
        combined_size=3*10**10: t_wall=312.617s (cpu_elapsed=276.387s, gpu_total=298.169s) --
            0.59x/0.61x of 3x sequential (41%/39% FASTER). A rough 2-point linear projection
            made from just the first two points predicted ~300s here -- actual 312.617s, close,
            validating that extrapolation approach.
        combined_size=4*10**10: t_wall=349.470s (cpu_elapsed=323.074s, gpu_total=330.204s) --
            0.50x/0.52x of 4x sequential (50%/48% FASTER -- literally half the time).
    Marginal cost between the 3*10**10 and 4*10**10 points: only 3.69s per extra billion numbers
    covered (36.852s extra wall time for 10 billion extra numbers) -- the curve is genuinely
    flattening as predicted, not just a one-off. The fixed-generation-cost hypothesis is
    confirmed: the bigger the single combined_size given to one split run, the bigger the win
    over running production/GPU sequentially that many times.

    BREAK-EVEN BISECTION (2026-08-29, still cpu_workers=24, gpu_gen_threads=12 -- see the
    CORRECTED section below before trusting these numbers): a finer sweep across
    10/12/13/14/15/16/18*10**9 pinned the crossover (both vs-seq ratios flip from >1.0x to <1.0x)
    at roughly combined_size~=14.7-14.8*10**9 -- 14*10**9 still measured slightly SLOWER on the
    CPU reference (0.98x) and slightly slower on GPU (1.02x); 15*10**9 was the first point faster
    on both.

    CPU-CORE CONTENTION BUG FOUND AND FIXED (2026-08-29): while chasing the load-balance question
    (does skewing cpu_fraction away from 0.5 help), noticed gpu_total INCREASING as cpu_fraction
    rose even though cs_gpu was SHRINKING -- backwards for two supposedly independent devices.
    Root cause: this whole break-even sweep ran with the DEFAULT cpu_workers=24 (real CPU
    marking processes) simultaneously with gpu_gen_threads=12 (GPU's OWN host-side prime
    generation threads) -- 36 total OS threads/processes on Artur's 24-logical-core machine, a
    real 1.5x oversubscription. The two "independent" devices were fighting over physical cores
    the whole time, and every number in this whole file up to this point was measured under that
    oversubscription.

    CORRECTED BREAK-EVEN (2026-08-29, cpu_workers=12, gpu_gen_threads=12 -- sums to exactly 24,
    Artur's real core count), full 10-15*10**9 sweep re-run for a clean before/after comparison:
        combined_size=1.0*10**10: t_wall=220.085s (was 230.508s) -- 1.25x/1.30x SLOWER.
        combined_size=1.2*10**10: t_wall=232.575s (was 241.951s) -- 1.10x/1.14x SLOWER.
        combined_size=1.3*10**10: t_wall=232.847s (was 244.847s) -- 1.02x/1.06x SLOWER.
        combined_size=1.4*10**10: t_wall=233.541s (was 241.246s) -- 0.95x/0.98x FASTER.
        combined_size=1.5*10**10: t_wall=240.693s (was 251.293s) -- 0.91x/0.95x FASTER.
    Every single point landed 8-12s faster than the SAME combined_size measured under the
    oversubscribed 24+12 budget -- a real, consistent effect, not noise. The break-even crossover
    itself moved down accordingly: vs seq CPU crosses between 1.3*10**10 (1.02x) and 1.4*10**10
    (0.95x) -- linear estimate ~1.325*10**10; vs seq GPU crosses between the same two points --
    linear estimate ~1.377*10**10. So the real, corrected break-even is roughly combined_size~=
    1.33-1.38*10**10, noticeably lower than the ~1.47-1.48*10**10 measured under the
    oversubscribed thread budget. Lesson for any future sweep in this file: cpu_workers +
    gpu_gen_threads should sum to <= the real logical core count, or the measurement itself
    becomes the bottleneck being studied.

    LOAD-BALANCE SWEEP FINDING (2026-08-29, run_fraction_sweep_mode(), combined_size=1.2*10**10,
    corrected cpu_workers=12/gpu_gen_threads=12 budget): tried cpu_fraction in {0.5, 0.6, 0.7,
    0.8, 0.9} expecting a skewed split to beat 50/50 (GPU was the visible "long pole" at 0.5).
    Result: 0.5 was the FASTEST of the five (233.803s), and t_wall got monotonically WORSE as
    cpu_fraction rose (290.956s at 0.9) -- shifting share toward CPU doesn't help here, because
    CPU's own per-share marking cost grows faster than what it saves on GPU's side. The naive
    "GPU is idle longer so give it less" intuition doesn't hold once CPU's own super-linear cost
    growth (dense-tier marking work grows with cs_cpu*ln(ln(cs_cpu)), not linearly) is accounted
    for. Simple fraction-skewing is not the lever; see the shared-work-queue idea discussed with
    Artur (dynamic per-fragment assignment instead of one static a-priori ratio) for the
    architecture that would actually realize further gains here, gated on solving the
    fixed-generation-cost-per-invocation problem first (see run_fraction_sweep_mode()'s own
    docstring).
    """
    print()
    print("=" * 78)
    print("FULL mode -- REAL floor-25 scale, CPU+GPU disjoint range split")
    print("=" * 78)
    lib = load_engine(engine_so_path)
    floor = 25
    distance = 10 ** floor
    n_10b_units = combined_size / 10 ** 10

    print(f"[*] floor={floor}  combined_size={combined_size:,} ({n_10b_units:.2f}x the original "
          f"10-billion baseline)  cpu_fraction={cpu_fraction}  "
          f"gpu_gen_threads={gpu_gen_threads}  "
          f"gpu_chunk_size={gpu_chunk_size:,}  cpu_workers={cpu_workers}  "
          f"cpu_batches_per_worker={cpu_batches_per_worker}")
    print(f"    solo reference points (all measured at the 10-billion baseline scale): "
          f"production CPU (sieve+write) = 176.018s, GPU two-tier marking-only = 169.623s, "
          f"phase_stream_poc (single CPU marker) = 677.942s, phase_stream_parallel_poc "
          f"(24 marker threads, extrapolated) ~1500s. Prior split results (see this function's "
          f"own docstring for the full analysis): combined_size=10**10 -> t_wall=230.508s "
          f"(1.31x/1.36x SLOWER than either solo device covering the same 10B alone); "
          f"combined_size=2*10**10 -> t_wall=268.349s, which is 0.76x/0.79x of running "
          f"production/GPU SEQUENTIALLY TWICE to cover the same 20B total (i.e. FASTER, "
          f"confirming the fixed-generation-cost hypothesis).")
    if cpu_workers <= 1:
        print(f"    [!] cpu_workers={cpu_workers} -- CPU side will run the SINGLE-THREADED "
              f"ground-truth path, far slower than production's real 24-process architecture. "
              f"Pass --cpu-workers 24 (the default) for a fair CPU timing.")

    split = run_split(lib, gpu_binary, gpu_gen_threads, gpu_chunk_size,
                       distance, combined_size, cpu_fraction, "full",
                       engine_so_path=engine_so_path, cpu_workers=cpu_workers,
                       cpu_batches_per_worker=cpu_batches_per_worker)
    _report_split(split)

    gpu_total = split["gpu_timings"][-1] if split["gpu_timings"] else 0.0
    ideal = max(split["cpu_elapsed"], gpu_total)
    print()
    print(f"  overlap check: t_wall={split['t_wall']:.3f}s vs. ideal max(cpu,gpu)={ideal:.3f}s "
          f"(closer to ideal = better real concurrency) vs. naive sum="
          f"{split['cpu_elapsed'] + gpu_total:.3f}s (no overlap at all)")
    # Two different fairness questions, both worth asking:
    # (1) vs. a SINGLE production/GPU run covering the SAME combined_size in one go (only a
    #     fair comparison for combined_size close to their own 10-billion baseline -- scaled up
    #     naively here by n_10b_units purely for a same-ballpark reference, NOT a measured number).
    # (2) vs. running production SEQUENTIALLY n_10b_units times to cover the same TOTAL range
    #     (Artur's original framing: "2 iterations of 176s to cover 20 billion") -- this is the
    #     comparison that actually matters for "is the split worth it", since it answers the real
    #     question of throughput per unit of total range covered.
    seq_cpu_naive = 176.018 * n_10b_units
    seq_gpu_naive = 169.623 * n_10b_units
    print(f"  DIRECT COMPARISON -- this run covers the FULL {combined_size:,}-number range "
          f"({n_10b_units:.2f}x the 10-billion baseline).")
    print(f"    vs. production CPU run SEQUENTIALLY {n_10b_units:.2f}x to cover the same total "
          f"range ({n_10b_units:.2f} * 176.018s = {seq_cpu_naive:.1f}s, naive linear scaling): "
          f"{split['t_wall'] / seq_cpu_naive:.2f}x" +
          (" (FASTER)" if split['t_wall'] < seq_cpu_naive else " (still slower)"))
    print(f"    vs. GPU two-tier run SEQUENTIALLY {n_10b_units:.2f}x to cover the same total "
          f"range ({n_10b_units:.2f} * 169.623s = {seq_gpu_naive:.1f}s, naive linear scaling): "
          f"{split['t_wall'] / seq_gpu_naive:.2f}x" +
          (" (FASTER)" if split['t_wall'] < seq_gpu_naive else " (still slower)"))
    print(f"    Note neither this run's CPU-side marking-only timing nor GPU's includes a disk "
          f"write step, matching every prior marking-focused PoC in this series -- only "
          f"production's own 176.018s reference includes write.")

    return {
        "combined_size": combined_size,
        "n_10b_units": n_10b_units,
        "t_wall": split["t_wall"],
        "cpu_elapsed": split["cpu_elapsed"],
        "gpu_total": gpu_total,
        "seq_cpu_naive": seq_cpu_naive,
        "seq_gpu_naive": seq_gpu_naive,
        "vs_seq_cpu": split["t_wall"] / seq_cpu_naive,
        "vs_seq_gpu": split["t_wall"] / seq_gpu_naive,
    }


def run_full_scale_mode_three_way(gpu_binary, engine_so_path, cpu_fraction, cpu_bonus_fraction,
                                   gpu_gen_threads, gpu_chunk_size, cpu_workers,
                                   cpu_batches_per_worker, combined_size=10 ** 10):
    """Three-way counterpart of run_full_scale_mode() -- adds a CPU 'bonus round' on top of the
    plain 2-way split (see run_split_three_way()'s docstring for the full architecture). Reports
    the same DIRECT COMPARISON block as the 2-way FULL mode, plus a breakdown of cpu1/cpu2/gpu so
    the bonus round's actual effect on gpu_total (should shrink, since cs_gpu shrinks) and on
    t_wall (the real question: does the bonus round's own cost stay hidden under GPU's remaining
    work, or does it become visible as extra wall time once GPU finishes first) can be read
    directly off one run, before committing to a specific cpu_bonus_fraction value.

    REAL-HARDWARE RESULT (2026-08-29, first and so far only run: combined_size=13.5*10**9,
    cpu_fraction=0.5, cpu_bonus_fraction=0.15, cpu_workers=12, gpu_gen_threads=12) -- NEGATIVE.
    EXACT mode passed all 14 cases (7 plain 2-way + 7 three-way) byte-for-byte first, confirming
    the split/concatenate mechanism itself is correct. But the FULL run came back WORSE than a
    plain 50/50 split at the same scale: t_wall=298.712s, vs. ~233s interpolated from the
    corrected 13B/14B sweep points in run_full_scale_mode()'s own docstring (roughly 28% SLOWER,
    not faster).

    ROOT CAUSE: reusing the SAME already-forked ProcessPoolExecutor for round 2 (no new fork())
    only avoids re-paying the process-STARTUP cost -- it does nothing about the actual dominant
    cost this whole file has been chasing since its first FULL run, which is each worker walking
    the sieving-prime range from 2 up to l_final (here 3.16*10**12) to find which primes even
    need checking. That walk is genuinely re-done, in full, for round 2: cs_cpu1=5.7375*10**9
    took cpu1_elapsed=172.034s, and cs_cpu2=2.025*10**9 -- a window only 35% as big -- still took
    cpu2_elapsed=124.689s (73% as long), because the dominant sparse-tier generation cost from
    threshold up to l_final barely depends on where `threshold` (=~combined_size for that
    invocation) sits when l_final is this much bigger than either window. Submitting a second
    batch of tasks to the SAME live worker pool was never going to fix this -- the duplicated
    cost lives in _build_equal_cost_batches()+process_batch_cpu() being invoked TWICE over the
    same [2, l_final) range, once per round, regardless of whether the OS processes doing the
    work are freshly forked or already warm.

    WHAT WOULD ACTUALLY FIX IT (not yet built): a single primesieve walk per worker that marks
    into BOTH windows' output buffers in the SAME pass -- i.e. a new engine function taking two
    (distance, window_m, byte_offset) tuples instead of one, checking both per prime found,
    so the expensive part (walking to l_final) is paid exactly once no matter how many logical
    "rounds" of CPU work get folded into it. That requires a new C function (this PoC's engine
    changes so far have all been additive -- see marking_two_tier_poc.cu's own precedent -- so
    this would follow the same pattern, not modify prime_sieve_engine_v4.c itself), a real step
    up in scope from this pool-reuse attempt. See run_split_three_way()'s own docstring for the
    (now confirmed insufficient) reasoning that motivated the pool-reuse-only approach."""
    print()
    print("=" * 78)
    print("FULL mode (three-way) -- REAL floor-25 scale, CPU round1 + GPU + CPU bonus round2")
    print("=" * 78)
    lib = load_engine(engine_so_path)
    floor = 25
    distance = 10 ** floor
    n_10b_units = combined_size / 10 ** 10

    print(f"[*] floor={floor}  combined_size={combined_size:,} ({n_10b_units:.2f}x the original "
          f"10-billion baseline)  cpu_fraction={cpu_fraction}  "
          f"cpu_bonus_fraction={cpu_bonus_fraction}  gpu_gen_threads={gpu_gen_threads}  "
          f"gpu_chunk_size={gpu_chunk_size:,}  cpu_workers={cpu_workers}  "
          f"cpu_batches_per_worker={cpu_batches_per_worker}")
    if cpu_workers <= 1:
        print(f"    [!] cpu_workers={cpu_workers} -- CPU side will run the SINGLE-THREADED "
              f"sequential-rounds path, far slower than the real multi-process architecture and "
              f"with NO pipelining benefit from the bonus round at all. Pass --cpu-workers 12 "
              f"(or whatever sums to your real core count with --gpu-gen-threads) for a fair "
              f"timing.")

    split = run_split_three_way(lib, gpu_binary, gpu_gen_threads, gpu_chunk_size,
                                 distance, combined_size, cpu_fraction, cpu_bonus_fraction,
                                 "full3", engine_so_path=engine_so_path, cpu_workers=cpu_workers,
                                 cpu_batches_per_worker=cpu_batches_per_worker)
    _report_split_three_way(split)

    gpu_total = split["gpu_timings"][-1] if split["gpu_timings"] else 0.0
    cpu_total = split["cpu1_elapsed"] + split["cpu2_elapsed"]
    ideal = max(cpu_total, gpu_total)
    print()
    print(f"  overlap check: t_wall={split['t_wall']:.3f}s vs. ideal max(cpu1+cpu2,gpu)="
          f"{ideal:.3f}s vs. naive sum={cpu_total + gpu_total:.3f}s (no overlap at all)")
    seq_cpu_naive = 176.018 * n_10b_units
    seq_gpu_naive = 169.623 * n_10b_units
    print(f"  DIRECT COMPARISON -- this run covers the FULL {combined_size:,}-number range "
          f"({n_10b_units:.2f}x the 10-billion baseline).")
    print(f"    vs. production CPU run SEQUENTIALLY {n_10b_units:.2f}x to cover the same total "
          f"range ({n_10b_units:.2f} * 176.018s = {seq_cpu_naive:.1f}s, naive linear scaling): "
          f"{split['t_wall'] / seq_cpu_naive:.2f}x" +
          (" (FASTER)" if split['t_wall'] < seq_cpu_naive else " (still slower)"))
    print(f"    vs. GPU two-tier run SEQUENTIALLY {n_10b_units:.2f}x to cover the same total "
          f"range ({n_10b_units:.2f} * 169.623s = {seq_gpu_naive:.1f}s, naive linear scaling): "
          f"{split['t_wall'] / seq_gpu_naive:.2f}x" +
          (" (FASTER)" if split['t_wall'] < seq_gpu_naive else " (still slower)"))

    return {
        "combined_size": combined_size,
        "n_10b_units": n_10b_units,
        "t_wall": split["t_wall"],
        "cpu1_elapsed": split["cpu1_elapsed"],
        "cpu2_elapsed": split["cpu2_elapsed"],
        "gpu_total": gpu_total,
        "seq_cpu_naive": seq_cpu_naive,
        "seq_gpu_naive": seq_gpu_naive,
        "vs_seq_cpu": split["t_wall"] / seq_cpu_naive,
        "vs_seq_gpu": split["t_wall"] / seq_gpu_naive,
    }


def run_full_scale_mode_dual_window(gpu_binary, engine_so_path, dual_engine_so_path,
                                     cpu_fraction, cpu_bonus_fraction, gpu_gen_threads,
                                     gpu_chunk_size, cpu_workers, cpu_batches_per_worker,
                                     combined_size=10 ** 10):
    """Dual-window counterpart of run_full_scale_mode_three_way() -- same window layout, but the
    CPU side marks BOTH windows in ONE primesieve pass per worker (run_split_dual_window())
    instead of two sequential rounds. Built specifically to test whether removing the double
    generation-cost bug (see run_full_scale_mode_three_way()'s own docstring for the confirmed
    root cause of that approach's 298.712s real-hardware result) makes a CPU-heavier split
    competitive with -- or even better than -- the plain 50/50 baseline.

    IMPORTANT CAVEAT (read before over-interpreting a win here): giving CPU a bigger TOTAL share
    of combined_size, whether as one window or two, is close in COST to just raising
    `cpu_fraction` directly in the plain 2-way split -- and run_fraction_sweep_mode() already
    found that skewing cpu_fraction above 0.5 makes wall time monotonically WORSE there. If this
    run ALSO comes back worse than 50/50, that's consistent with CPU's own dense-tier marking
    cost being the real limiter (not the double-generation bug) -- i.e., the fraction sweep's
    finding would extend here too, independent of which mechanism assembles the CPU-heavier
    split. If this run comes back BETTER than run_split_three_way()'s 298.712s AND competitive
    with the 50/50 baseline, that isolates the double-generation-cost bug as the specific reason
    the round-based approach failed, without yet proving CPU-heavier splits are worth pursuing in
    general.

    REAL-HARDWARE RESULT (2026-09-02, combined_size=13.5*10**9, cpu_fraction=0.5,
    cpu_bonus_fraction=0.15, cpu_workers=12, gpu_gen_threads=12): BOTH of the caveat's predicted
    outcomes landed at once. cpu_elapsed=250.181s (one dual pass) vs. 296.723s for the same two
    windows under run_split_three_way()'s two separate passes -- BETTER than the round-based
    298.712s by 46.7s / 15.6% (t_wall=251.981s vs. 298.712s), confirming the double-generation-cost
    bug was real and is now fixed. But t_wall=251.981s is still NOT competitive with the plain
    50/50 baseline (~233.2s interpolated at 13.5B) -- ~8.1% SLOWER (1.06x vs. sequential-CPU
    reference, 1.10x vs. sequential-GPU reference, both printed as 'still slower' by this
    function). So the double-generation bug was A reason for the round-based loss, but not the
    ONLY one -- CPU's own dense-tier marking cost (run_fraction_sweep_mode()'s finding, effective
    cpu share here ~57.5%) still dominates and still loses to plain 50/50, independent of
    mechanism. CONCLUSION: this dual-window engine is a strict improvement over
    run_split_three_way() whenever a CPU bonus round is used at all, but a CPU-heavier split is
    not, on this evidence, a path to beating plain 50/50 -- the shared work-queue idea (see
    README's 'real fix, not yet built' section) remains the more promising direction for actually
    improving on 50/50, since it would let the FASTER device naturally do more work without ever
    over-committing a fixed a-priori share to the slower one."""
    print()
    print("=" * 78)
    print("FULL mode (dual-window) -- REAL floor-25 scale, CPU marks both windows in one pass")
    print("=" * 78)
    lib = load_engine(engine_so_path)
    floor = 25
    distance = 10 ** floor
    n_10b_units = combined_size / 10 ** 10

    print(f"[*] floor={floor}  combined_size={combined_size:,} ({n_10b_units:.2f}x the original "
          f"10-billion baseline)  cpu_fraction={cpu_fraction}  "
          f"cpu_bonus_fraction={cpu_bonus_fraction}  gpu_gen_threads={gpu_gen_threads}  "
          f"gpu_chunk_size={gpu_chunk_size:,}  cpu_workers={cpu_workers}  "
          f"cpu_batches_per_worker={cpu_batches_per_worker}")
    if cpu_workers <= 1:
        print(f"    [!] cpu_workers={cpu_workers} -- CPU side will run the SINGLE-THREADED "
              f"non-atomic dual call, far slower than the real multi-process architecture. Pass "
              f"--cpu-workers 12 (or whatever sums to your real core count with "
              f"--gpu-gen-threads) for a fair timing.")

    split = run_split_dual_window(lib, gpu_binary, gpu_gen_threads, gpu_chunk_size,
                                   distance, combined_size, cpu_fraction, cpu_bonus_fraction,
                                   "fulldual", engine_so_path=engine_so_path,
                                   dual_engine_so_path=dual_engine_so_path,
                                   cpu_workers=cpu_workers,
                                   cpu_batches_per_worker=cpu_batches_per_worker)
    _report_split_dual_window(split)

    gpu_total = split["gpu_timings"][-1] if split["gpu_timings"] else 0.0
    cpu_total = split["cpu_elapsed"]
    ideal = max(cpu_total, gpu_total)
    print()
    print(f"  overlap check: t_wall={split['t_wall']:.3f}s vs. ideal max(cpu,gpu)={ideal:.3f}s "
          f"vs. naive sum={cpu_total + gpu_total:.3f}s (no overlap at all)")
    seq_cpu_naive = 176.018 * n_10b_units
    seq_gpu_naive = 169.623 * n_10b_units
    print(f"  DIRECT COMPARISON -- this run covers the FULL {combined_size:,}-number range "
          f"({n_10b_units:.2f}x the 10-billion baseline).")
    print(f"    vs. production CPU run SEQUENTIALLY {n_10b_units:.2f}x to cover the same total "
          f"range ({n_10b_units:.2f} * 176.018s = {seq_cpu_naive:.1f}s, naive linear scaling): "
          f"{split['t_wall'] / seq_cpu_naive:.2f}x" +
          (" (FASTER)" if split['t_wall'] < seq_cpu_naive else " (still slower)"))
    print(f"    vs. GPU two-tier run SEQUENTIALLY {n_10b_units:.2f}x to cover the same total "
          f"range ({n_10b_units:.2f} * 169.623s = {seq_gpu_naive:.1f}s, naive linear scaling): "
          f"{split['t_wall'] / seq_gpu_naive:.2f}x" +
          (" (FASTER)" if split['t_wall'] < seq_gpu_naive else " (still slower)"))
    print(f"    vs. run_split_three_way()'s round-based result at 13.5B/0.5/0.15 (298.712s, "
          f"cpu_workers=12): compare directly only if this run used the SAME combined_size/"
          f"cpu_fraction/cpu_bonus_fraction/cpu_workers -- otherwise use the 50/50 baseline "
          f"above as the fairer reference.")

    return {
        "combined_size": combined_size,
        "n_10b_units": n_10b_units,
        "t_wall": split["t_wall"],
        "cpu_elapsed": cpu_total,
        "gpu_total": gpu_total,
        "seq_cpu_naive": seq_cpu_naive,
        "seq_gpu_naive": seq_gpu_naive,
        "vs_seq_cpu": split["t_wall"] / seq_cpu_naive,
        "vs_seq_gpu": split["t_wall"] / seq_gpu_naive,
    }


def _report_split_dual_window(split):
    counts = split["gpu_counts"]
    timings = split["gpu_timings"]
    print()
    print(f"  l_final={split['l_final']:,}  cs_cpu1={split['cs_cpu1']:,}  "
          f"cs_gpu={split['cs_gpu']:,}  cs_cpu2={split['cs_cpu2']:,}")
    print(f"  cpu_elapsed={split['cpu_elapsed']:.3f}s (single dual-window pass, no round split)")
    if counts:
        (t_dense_gen, t_dense_gpu, t_sparse_gen, t_sparse_gpu, t_download, t_gpu_total) = timings
        print(f"  gpu: {counts.get('total_primes', 0):,} primes "
              f"({counts.get('n_dense_primes', 0):,} dense + "
              f"{counts.get('n_sparse_primes', 0):,} sparse)  "
              f"dense(gen={t_dense_gen:.3f}s gpu={t_dense_gpu:.3f}s)  "
              f"sparse(gen={t_sparse_gen:.3f}s gpu={t_sparse_gpu:.3f}s)  "
              f"download={t_download:.3f}s  gpu_total={t_gpu_total:.3f}s")
    print(f"  WALL (both devices concurrent): {split['t_wall']:.3f}s")
    total_bits_set = int.from_bytes(split["combined_bits"], "little").bit_count()
    combined_size = split["cs_cpu1"] + split["cs_gpu"] + split["cs_cpu2"]
    if combined_size > 0:
        density = total_bits_set / combined_size
        print(f"  marked-composite density: {density:.4%}")


def run_full_sweep_mode(gpu_binary, engine_so_path, cpu_fraction, gpu_gen_threads,
                         gpu_chunk_size, cpu_workers, cpu_batches_per_worker,
                         combined_sizes):
    """Runs run_full_scale_mode() once per combined_size in `combined_sizes`, back to back in a
    single process invocation, then prints one summary table comparing every run -- built for
    exactly this: testing the fixed-generation-cost/growing-marking-cost hypothesis (see
    run_full_scale_mode()'s own docstring) across MULTIPLE scales in one sitting, rather than
    requiring a separate manual invocation (and separate wait) per data point."""
    print()
    print("=" * 78)
    print(f"FULL SWEEP mode -- {len(combined_sizes)} back-to-back FULL-mode runs: "
          f"{', '.join(f'{cs:,}' for cs in combined_sizes)}")
    print("=" * 78)

    results = []
    for i, combined_size in enumerate(combined_sizes):
        print()
        print(f"[sweep {i + 1}/{len(combined_sizes)}] combined_size={combined_size:,}")
        result = run_full_scale_mode(gpu_binary, engine_so_path, cpu_fraction, gpu_gen_threads,
                                      gpu_chunk_size, cpu_workers, cpu_batches_per_worker,
                                      combined_size=combined_size)
        results.append(result)

    print()
    print("=" * 78)
    print("FULL SWEEP SUMMARY")
    print("=" * 78)
    header = (f"{'combined_size':>16}  {'x10B':>6}  {'t_wall':>10}  {'cpu_elapsed':>12}  "
              f"{'gpu_total':>10}  {'vs seq CPU':>12}  {'vs seq GPU':>12}")
    print(header)
    print("-" * len(header))
    for r in results:
        vs_cpu_tag = "FASTER" if r["vs_seq_cpu"] < 1.0 else "slower"
        vs_gpu_tag = "FASTER" if r["vs_seq_gpu"] < 1.0 else "slower"
        print(f"{r['combined_size']:>16,}  {r['n_10b_units']:>6.2f}  {r['t_wall']:>9.3f}s  "
              f"{r['cpu_elapsed']:>11.3f}s  {r['gpu_total']:>9.3f}s  "
              f"{r['vs_seq_cpu']:>9.2f}x {vs_cpu_tag:>3}  {r['vs_seq_gpu']:>9.2f}x {vs_gpu_tag:>3}")
    print()
    print("  'vs seq CPU/GPU' = t_wall / (n_10b_units * solo-reference-time) -- how this run's "
          "wall time compares to running production CPU (176.018s) / GPU (169.623s) "
          "SEQUENTIALLY n_10b_units times to cover the same total range. <1.0x = split wins.")
    if len(results) >= 2:
        first, last = results[0], results[-1]
        d_combined = last["combined_size"] - first["combined_size"]
        d_wall = last["t_wall"] - first["t_wall"]
        marginal_rate = d_wall / d_combined if d_combined else float("nan")
        print(f"  Marginal cost between the smallest and largest run in this sweep: "
              f"{d_wall:.3f}s extra wall time for {d_combined:,} extra numbers covered "
              f"({marginal_rate * 1e9:.4f}s per billion numbers) -- the flatter this is, the "
              f"more strongly the fixed-generation-cost hypothesis is confirmed.")

    # Break-even (crossover) detection: find the consecutive pair of sweep points where
    # vs_seq_cpu / vs_seq_gpu cross 1.0x (split flips from a loss to a win, or vice versa), and
    # linearly interpolate the combined_size at which the ratio would equal exactly 1.0. This is
    # only a linear interpolation between two real measured points, not a new measurement --
    # treat it as "narrow the next sweep around here," not as a final answer, until a real run
    # actually lands close to it.
    print()
    print("  Break-even (vs seq ratio == 1.0x) search across this sweep's points:")
    found_any_crossing = False
    for key, label, ref_time in (("vs_seq_cpu", "vs seq CPU", 176.018),
                                  ("vs_seq_gpu", "vs seq GPU", 169.623)):
        crossing_reported = False
        for a, b in zip(results, results[1:]):
            ra, rb = a[key], b[key]
            if (ra - 1.0) * (rb - 1.0) < 0:  # opposite sides of 1.0x -> a real crossing
                frac = (1.0 - ra) / (rb - ra)
                cs_cross = a["combined_size"] + frac * (b["combined_size"] - a["combined_size"])
                print(f"    {label}: crosses 1.0x between combined_size={a['combined_size']:,} "
                      f"({ra:.2f}x) and {b['combined_size']:,} ({rb:.2f}x) -- linear estimate: "
                      f"~{cs_cross:,.0f} ({cs_cross / 1e9:.2f} billion)")
                crossing_reported = True
                found_any_crossing = True
        if not crossing_reported:
            all_above = all(r[key] >= 1.0 for r in results)
            all_below = all(r[key] < 1.0 for r in results)
            if all_above:
                print(f"    {label}: every point in this sweep is still >=1.0x (SLOWER) -- "
                      f"break-even is above the largest combined_size tried "
                      f"({results[-1]['combined_size']:,}), not bracketed yet.")
            elif all_below:
                print(f"    {label}: every point in this sweep is already <1.0x (FASTER) -- "
                      f"break-even is below the smallest combined_size tried "
                      f"({results[0]['combined_size']:,}), not bracketed yet.")
    if not found_any_crossing and len(results) >= 2:
        print("    (no crossing inside this sweep's range -- pick a combined_size outside the "
              "range above, on the side break-even is expected to be, for the next sweep.)")

    return results


def run_fraction_sweep_mode(gpu_binary, engine_so_path, gpu_gen_threads, gpu_chunk_size,
                             cpu_workers, cpu_batches_per_worker, combined_size, cpu_fractions):
    """Load-balance sweep (2026-08-29, Artur's follow-up to the combined_size break-even sweep):
    at a FIXED combined_size, run run_full_scale_mode() once per cpu_fraction in `cpu_fractions`,
    to find the split ratio that actually minimizes wall time -- as opposed to the break-even
    sweep above, which held cpu_fraction=0.5 fixed and varied combined_size.

    Why this is a genuinely different question: the 50/50 runs in the combined_size sweep showed
    CPU and GPU finishing at very different times for the SAME nominal share (e.g. at
    combined_size=18*10**9, cs_cpu=cs_gpu=9*10**9: cpu_elapsed=164.124s but gpu_total=245.430s --
    CPU sits idle for ~80s waiting on GPU). Since wall time for two concurrent, non-overlapping-
    buffer devices is bounded below by max(cpu_elapsed, gpu_total), an UNBALANCED split wastes the
    faster device's spare capacity -- shifting some of GPU's share to CPU should let both finish
    closer to the same time, pulling wall time down toward that lower bound. This is a real,
    separate lever from "is splitting worth it at all" (the break-even sweep's question) -- it
    answers "how much better can any given combined_size get if we stop assuming 50/50."

    Finds the fraction where cpu_elapsed and gpu_total cross (linear interpolation between the
    two bracketing measured points, same technique as run_full_sweep_mode()'s break-even search)
    and reports the fastest fraction actually measured in this sweep as the real, hardware-
    confirmed answer -- the interpolated crossing is only a hint for where to sample next if it
    isn't already bracketed tightly.
    """
    print()
    print("=" * 78)
    print(f"CPU-FRACTION LOAD-BALANCE SWEEP -- combined_size={combined_size:,} fixed, "
          f"{len(cpu_fractions)} back-to-back FULL-mode runs at cpu_fraction="
          f"{', '.join(f'{f:.3f}' for f in cpu_fractions)}")
    print("=" * 78)

    results = []
    for i, frac in enumerate(cpu_fractions):
        print()
        print(f"[fraction-sweep {i + 1}/{len(cpu_fractions)}] cpu_fraction={frac:.4f}")
        result = run_full_scale_mode(gpu_binary, engine_so_path, frac, gpu_gen_threads,
                                      gpu_chunk_size, cpu_workers, cpu_batches_per_worker,
                                      combined_size=combined_size)
        result["cpu_fraction"] = frac
        results.append(result)

    results.sort(key=lambda r: r["cpu_fraction"])

    print()
    print("=" * 78)
    print("CPU-FRACTION SWEEP SUMMARY")
    print("=" * 78)
    header = (f"{'cpu_fraction':>12}  {'~cs_cpu':>16}  {'~cs_gpu':>16}  {'t_wall':>10}  "
              f"{'cpu_elapsed':>12}  {'gpu_total':>10}  {'imbalance':>12}")
    print(header)
    print("-" * len(header))
    for r in results:
        cs_cpu_approx = combined_size * r["cpu_fraction"]
        cs_gpu_approx = combined_size - cs_cpu_approx
        imbalance = r["cpu_elapsed"] - r["gpu_total"]
        print(f"{r['cpu_fraction']:>12.4f}  {cs_cpu_approx:>16,.0f}  {cs_gpu_approx:>16,.0f}  "
              f"{r['t_wall']:>9.3f}s  {r['cpu_elapsed']:>11.3f}s  {r['gpu_total']:>9.3f}s  "
              f"{imbalance:>+11.3f}s")
    print()
    print("  'imbalance' = cpu_elapsed - gpu_total. Positive = CPU is the long pole (give it LESS "
          "of the range next); negative = GPU is the long pole (give it LESS of the range next). "
          "The fraction where this crosses zero is the load-balanced split for this combined_size.")

    best = min(results, key=lambda r: r["t_wall"])
    print(f"  Fastest measured in this sweep: cpu_fraction={best['cpu_fraction']:.4f} -> "
          f"t_wall={best['t_wall']:.3f}s (vs seq CPU={best['vs_seq_cpu']:.2f}x, "
          f"vs seq GPU={best['vs_seq_gpu']:.2f}x)")

    print()
    print("  Load-balance point (imbalance == 0) search across this sweep's points:")
    found_crossing = False
    for a, b in zip(results, results[1:]):
        ia = a["cpu_elapsed"] - a["gpu_total"]
        ib = b["cpu_elapsed"] - b["gpu_total"]
        if (ia) * (ib) < 0:  # opposite sides of zero -> a real crossing
            frac_cross = a["cpu_fraction"] + (0 - ia) / (ib - ia) * (b["cpu_fraction"] -
                                                                      a["cpu_fraction"])
            print(f"    crosses zero imbalance between cpu_fraction={a['cpu_fraction']:.4f} "
                  f"({ia:+.3f}s) and {b['cpu_fraction']:.4f} ({ib:+.3f}s) -- linear estimate: "
                  f"~{frac_cross:.4f}")
            found_crossing = True
    if not found_crossing:
        all_cpu_long = all((r["cpu_elapsed"] - r["gpu_total"]) > 0 for r in results)
        all_gpu_long = all((r["cpu_elapsed"] - r["gpu_total"]) < 0 for r in results)
        if all_cpu_long:
            print(f"    every point in this sweep still has CPU as the long pole -- try a "
                  f"SMALLER cpu_fraction than {results[0]['cpu_fraction']:.4f} next.")
        elif all_gpu_long:
            print(f"    every point in this sweep still has GPU as the long pole -- try a "
                  f"LARGER cpu_fraction than {results[-1]['cpu_fraction']:.4f} next.")
        print("    (linear estimate only -- confirm with a real run at the estimated fraction "
              "before trusting it as final.)")

    return results


def _report_split(split):
    counts = split["gpu_counts"]
    timings = split["gpu_timings"]
    print()
    print(f"  l_final={split['l_final']:,}  cs_cpu={split['cs_cpu']:,}  cs_gpu={split['cs_gpu']:,}")
    print(f"  cpu_elapsed={split['cpu_elapsed']:.3f}s")
    if counts:
        (t_dense_gen, t_dense_gpu, t_sparse_gen, t_sparse_gpu, t_download, t_gpu_total) = timings
        print(f"  gpu: {counts.get('total_primes', 0):,} primes "
              f"({counts.get('n_dense_primes', 0):,} dense + "
              f"{counts.get('n_sparse_primes', 0):,} sparse)  "
              f"dense(gen={t_dense_gen:.3f}s gpu={t_dense_gpu:.3f}s)  "
              f"sparse(gen={t_sparse_gen:.3f}s gpu={t_sparse_gpu:.3f}s)  "
              f"download={t_download:.3f}s  gpu_total={t_gpu_total:.3f}s")
    print(f"  WALL (both devices concurrent): {split['t_wall']:.3f}s")
    total_bits_set = int.from_bytes(split["combined_bits"], "little").bit_count()
    combined_size = split["cs_cpu"] + split["cs_gpu"]
    if combined_size > 0:
        density = total_bits_set / combined_size
        print(f"  marked-composite density: {density:.4%}")


def _report_split_three_way(split):
    counts = split["gpu_counts"]
    timings = split["gpu_timings"]
    print()
    print(f"  l_final={split['l_final']:,}  cs_cpu1={split['cs_cpu1']:,}  "
          f"cs_gpu={split['cs_gpu']:,}  cs_cpu2={split['cs_cpu2']:,}")
    print(f"  cpu1_elapsed={split['cpu1_elapsed']:.3f}s  cpu2_elapsed={split['cpu2_elapsed']:.3f}s"
          f"  cpu_total={split['cpu1_elapsed'] + split['cpu2_elapsed']:.3f}s")
    if counts:
        (t_dense_gen, t_dense_gpu, t_sparse_gen, t_sparse_gpu, t_download, t_gpu_total) = timings
        print(f"  gpu: {counts.get('total_primes', 0):,} primes "
              f"({counts.get('n_dense_primes', 0):,} dense + "
              f"{counts.get('n_sparse_primes', 0):,} sparse)  "
              f"dense(gen={t_dense_gen:.3f}s gpu={t_dense_gpu:.3f}s)  "
              f"sparse(gen={t_sparse_gen:.3f}s gpu={t_sparse_gpu:.3f}s)  "
              f"download={t_download:.3f}s  gpu_total={t_gpu_total:.3f}s")
    print(f"  WALL (both devices concurrent): {split['t_wall']:.3f}s")
    total_bits_set = int.from_bytes(split["combined_bits"], "little").bit_count()
    combined_size = split["cs_cpu1"] + split["cs_gpu"] + split["cs_cpu2"]
    if combined_size > 0:
        density = total_bits_set / combined_size
        print(f"  marked-composite density: {density:.4%}")


def main():
    gpu_binary = DEFAULT_GPU_BINARY
    engine_so = DEFAULT_ENGINE_SO
    dual_engine_so = DEFAULT_DUAL_ENGINE_SO
    mode = "both"
    cpu_fractions = [0.5]
    gpu_gen_threads = 12
    gpu_chunk_size = DEFAULT_GPU_CHUNK_SIZE
    cpu_workers = DEFAULT_CPU_WORKERS
    cpu_batches_per_worker = DEFAULT_CPU_BATCHES_PER_WORKER
    full_combined_sizes = [10 ** 10]
    cpu_bonus_fraction = 0.0
    dual_window = "--dual-window" in sys.argv
    if "--gpu-binary" in sys.argv:
        gpu_binary = sys.argv[sys.argv.index("--gpu-binary") + 1]
    if "--engine-so" in sys.argv:
        engine_so = sys.argv[sys.argv.index("--engine-so") + 1]
    if "--dual-engine-so" in sys.argv:
        dual_engine_so = sys.argv[sys.argv.index("--dual-engine-so") + 1]
    if "--mode" in sys.argv:
        mode = sys.argv[sys.argv.index("--mode") + 1]
    if "--cpu-fraction" in sys.argv:
        # Comma-separated list allowed: --cpu-fraction 0.6,0.7,0.8 runs a load-balance sweep at a
        # FIXED combined_size (the first value in --combined-size, or the default) instead of the
        # usual single-fraction FULL run -- see run_fraction_sweep_mode()'s own docstring.
        raw = sys.argv[sys.argv.index("--cpu-fraction") + 1]
        cpu_fractions = [float(x) for x in raw.split(",") if x.strip()]
    if "--gpu-gen-threads" in sys.argv:
        gpu_gen_threads = int(sys.argv[sys.argv.index("--gpu-gen-threads") + 1])
    if "--gpu-chunk-size" in sys.argv:
        gpu_chunk_size = int(sys.argv[sys.argv.index("--gpu-chunk-size") + 1])
    if "--cpu-workers" in sys.argv:
        cpu_workers = int(sys.argv[sys.argv.index("--cpu-workers") + 1])
    if "--cpu-batches-per-worker" in sys.argv:
        cpu_batches_per_worker = int(sys.argv[sys.argv.index("--cpu-batches-per-worker") + 1])
    if "--combined-size" in sys.argv:
        # Comma-separated list allowed: --combined-size 30000000000,40000000000 runs FULL mode
        # once per value, back to back in this same invocation, then prints one summary table
        # comparing all of them (run_full_sweep_mode()) -- built for exactly Artur's request to
        # sweep multiple scales in one sitting rather than one manual invocation per data point.
        raw = sys.argv[sys.argv.index("--combined-size") + 1]
        full_combined_sizes = [int(x) for x in raw.split(",") if x.strip()]
    if "--cpu-bonus-fraction" in sys.argv:
        # CPU 'bonus round' (2026-08-29, Artur's idea): a slice of combined_size, on top of
        # --cpu-fraction's own split of the remainder, that CPU picks up AFTER its first round
        # finishes, reusing the same already-forked worker pool -- see run_split_three_way()'s
        # docstring. Only applies to FULL mode, and only when neither --cpu-fraction nor
        # --combined-size was ALSO given a multi-value (sweep) list -- see the dispatch below.
        cpu_bonus_fraction = float(sys.argv[sys.argv.index("--cpu-bonus-fraction") + 1])

    print(f"[*] cpu_fraction(s)={', '.join(f'{f:.4f}' for f in cpu_fractions)}  "
          f"cpu_bonus_fraction={cpu_bonus_fraction:.4f}  dual_window={dual_window}  "
          f"gpu_gen_threads={gpu_gen_threads}  gpu_chunk_size={gpu_chunk_size:,}  "
          f"cpu_workers={cpu_workers}  cpu_batches_per_worker={cpu_batches_per_worker}  "
          f"combined_size(s)(FULL only)={', '.join(f'{cs:,}' for cs in full_combined_sizes)} "
          f"(EXACT mode uses its own small, fixed per-case values and always stays "
          f"single-threaded -- cpu_workers/cpu_batches_per_worker/combined_size only apply to "
          f"STRESS/FULL, and --combined-size only to FULL; give a comma-separated list to sweep "
          f"multiple scales in one run; give --cpu-fraction a comma-separated list instead to "
          f"run a load-balance sweep at a FIXED combined_size -- see run_fraction_sweep_mode(); "
          f"--dual-window switches the CPU bonus mechanism from run_split_three_way()'s two "
          f"rounds (confirmed a net loss on real hardware, 2026-08-29) to run_split_dual_window()'s "
          f"single dual-marking pass -- only meaningful together with --cpu-bonus-fraction > 0)")

    ok = True
    if mode in ("exact", "both"):
        ok = run_exact_mode(gpu_binary, engine_so) and ok
        ok = run_exact_mode_three_way(gpu_binary, engine_so) and ok
        ok = run_exact_mode_dual_window(gpu_binary, engine_so, dual_engine_so) and ok
    if mode in ("stress", "both"):
        run_stress_mode(gpu_binary, engine_so, cpu_fractions[0], gpu_gen_threads,
                         gpu_chunk_size, cpu_workers, cpu_batches_per_worker)
    if mode == "full":
        if cpu_bonus_fraction > 0.0 and dual_window:
            if len(cpu_fractions) > 1 or len(full_combined_sizes) > 1:
                print(f"[!] --cpu-bonus-fraction/--dual-window does not yet support sweeps -- "
                      f"running a single dual-window FULL run at cpu_fraction={cpu_fractions[0]}, "
                      f"combined_size={full_combined_sizes[0]:,}, ignoring any other values in "
                      f"either list.")
            run_full_scale_mode_dual_window(gpu_binary, engine_so, dual_engine_so,
                                             cpu_fractions[0], cpu_bonus_fraction,
                                             gpu_gen_threads, gpu_chunk_size, cpu_workers,
                                             cpu_batches_per_worker,
                                             combined_size=full_combined_sizes[0])
        elif cpu_bonus_fraction > 0.0:
            if len(cpu_fractions) > 1 or len(full_combined_sizes) > 1:
                print(f"[!] --cpu-bonus-fraction does not yet support sweeps -- running a single "
                      f"three-way FULL run at cpu_fraction={cpu_fractions[0]}, "
                      f"combined_size={full_combined_sizes[0]:,}, ignoring any other values in "
                      f"either list.")
            run_full_scale_mode_three_way(gpu_binary, engine_so, cpu_fractions[0],
                                           cpu_bonus_fraction, gpu_gen_threads, gpu_chunk_size,
                                           cpu_workers, cpu_batches_per_worker,
                                           combined_size=full_combined_sizes[0])
        elif len(cpu_fractions) > 1:
            if len(full_combined_sizes) > 1:
                print(f"[!] both --cpu-fraction and --combined-size were given comma-separated "
                      f"lists -- running the fraction sweep at only the FIRST combined_size "
                      f"({full_combined_sizes[0]:,}), ignoring the rest of that list.")
            run_fraction_sweep_mode(gpu_binary, engine_so, gpu_gen_threads, gpu_chunk_size,
                                     cpu_workers, cpu_batches_per_worker,
                                     full_combined_sizes[0], cpu_fractions)
        elif len(full_combined_sizes) > 1:
            run_full_sweep_mode(gpu_binary, engine_so, cpu_fractions[0], gpu_gen_threads,
                                 gpu_chunk_size, cpu_workers, cpu_batches_per_worker,
                                 full_combined_sizes)
        else:
            run_full_scale_mode(gpu_binary, engine_so, cpu_fractions[0], gpu_gen_threads,
                                 gpu_chunk_size, cpu_workers, cpu_batches_per_worker,
                                 combined_size=full_combined_sizes[0])

    print()
    print("=" * 78)
    print("RESULT:", "PASS" if ok else "FAIL -- see mismatches above")
    print("=" * 78)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
