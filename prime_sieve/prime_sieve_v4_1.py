import ctypes
import datetime
import mmap
import multiprocessing
import numpy as np
import time
import os
import math
import concurrent.futures
from concurrent.futures import ProcessPoolExecutor


VERSION = "v4.1"   # bump this whenever this file changes, so console output alone identifies
                    # exactly which iteration of the code produced it.

MAX_WORKERS = 24
BATCHES_PER_WORKER = 2    # how many contiguous cost-equal batches per worker -- same meaning
                          # as prime_sieve_v3.py, unchanged

# count_sieving_primes(L_final) is a PURE diagnostic/benchmark statistic (pi(L_final) -- how
# many primes were used AS the sieving tool) -- it is NOT used anywhere in the actual sieve
# computation or in total_primes_found (the real result). At extreme depth it is NOT cheap:
# at floor-scale L_final values (order 10^13 and beyond) this single call can take minutes,
# comparable to the parallel sieve pass itself, and it runs BEFORE t_sieve/t_start, so its
# cost would otherwise be invisible in the "Batch sieve done" timing. Defaulting this OFF
# keeps normal runs fast; pass compute_sieving_primes_count=True (main_batch_scanner) / CLI
# position 7 / "1" to compute it exactly when pi(L_final) is actually wanted (e.g. for the
# benchmark_log.csv column). See count_sieving_primes_cached() below for the per-floor caching
# layer that makes repeat requests on the same floor far cheaper than the first one.
COMPUTE_SIEVING_PRIMES_COUNT = False

# ==========================================================================================
# prime_sieve_v4_1.py
#
# LINEAGE: prime_sieve_v4.py (this folder), with ONE addition on top of v4's own two changes
# (see "WHAT CHANGED"/"ALSO ADDED" below, both unchanged from v4, still describing v3->v4):
#
# ALSO ADDED (v4 -> v4.1, purely additive, touches no sieve/marking logic at all): direct
# timing for the three phases benchmark_log.csv previously had NO breakdown for. v4.py already
# measured t_count (base-prime count, "Active sieving primes used") and t_sieve (the parallel
# sieve pass, "Batch sieve done in Xs") -- but only ever PRINTED them; neither reached
# write_scan_metrics_handoff()'s JSON, so orchestrator_v3.py's benchmark_log.csv only ever saw
# ONE combined total_seconds per run, with no way to tell how much of a slow run was sieving
# vs. writing PGS2 files to disk vs. building the sieving-prime base. v4.1 adds a THIRD timer
# (t_write, wrapping the unpack-and-write-PGS2-files phase that follows the sieve pass -- the
# only phase of the three that had no timer of any kind before) and a bytes-written counter
# (os.path.getsize() summed over every window actually written this run, 0 in count-only mode),
# then threads all four numbers (base_gen_seconds, sieve_seconds, write_seconds, bytes_written)
# through write_scan_metrics_handoff() into the JSON handoff so orchestrator_v3.py can log them.
# See that file's own BENCHMARK_FIELDNAMES for where they land in benchmark_log.csv.
#
# Kept as a SEPARATE file rather than edited into prime_sieve_v4.py directly, same reasoning
# as v3 vs v4 themselves (see that lineage note below) -- v4.py is the currently-relied-on
# production engine and this additive-only change hasn't been run against real libprimesieve
# yet (the timing/handoff logic itself has no libprimesieve dependency and was exercised with
# synthetic data instead -- see this repo's own test notes for that run). Switch
# orchestrator_v3.py's SCANNER_VERSION to "v4.1" once confirmed, exactly like any other engine
# swap this project already supports.
#
# EVERYTHING BELOW THIS POINT is byte-for-byte v4.py except the four small, clearly-marked
# timing/write-loop edits inside main_batch_scanner() and write_scan_metrics_handoff() --
# original v4.py lineage note preserved verbatim for context:
#
# LINEAGE: prime_sieve_v3.py (this folder), with TWO changes -- see "WHAT CHANGED" and "ALSO
# ADDED" below. Everything else (PGS2 format, read/write/append functions, the equal-cost
# batching model, the shared-mmap/atomic-OR mechanism, the per-window unpacking/file-writing
# tail of main_batch_scanner()) is copied unchanged from v3. v1/v2/v3 are untouched and remain
# independently runnable.
#
# WHAT CHANGED: the per-sieving-prime phase computation inside the C engine
# (prime_sieve_engine_v4.c). For every sieving prime p, the engine needs distance mod p
# (distance is the combined window's start, a 128-bit value; p is 64-bit). Disassembly of the
# v3 engine build showed this compiling to a call into libgcc's __umodti3 for EVERY sieving
# prime -- a genuine function-call cost paid inside the single hottest loop in the program.
# v4's engine inlines the common case (dividend's high 64 bits below the divisor, which
# guarantees the quotient fits in 64 bits) down to a single hardware `divq` instruction at the
# call site, with the full u128 division kept as a fallback for the rare case where that
# guarantee doesn't hold. Verified bit-for-bit identical to v3's output across a battery of
# differential tests (fast-path and fallback-path cases, both engine variants). MEASURED END TO
# END against real libprimesieve (floor 18, both 10 and 1000 windows): no measurable wall-clock
# difference from v3 at that depth -- an isolated microbenchmark of the phase computation alone
# had shown ~1.1x-1.5x faster per call, but that gain is not the bottleneck of this engine, so
# it does not show up in real runs. Kept as an available alternative engine, not the default.
#
# ALSO ADDED (independent of the above, does not touch the sieve/marking path at all):
# count_sieving_primes_cached(), a per-floor cache for the pi(L_final) diagnostic stat, built
# on the engine's new additive count_sieving_primes_range(start, stop). Unlike the modulo
# change, this targets a cost that WAS confirmed real and significant (see the
# COMPUTE_SIEVING_PRIMES_COUNT comment above -- "can take minutes at extreme depth"): repeat
# calls on the same floor recount the ENTIRE [0, L_final] range from scratch every time even
# though L_final barely moves between consecutive runs. Caching the last counted (L, count) per
# floor and counting only the new sliver above it on subsequent calls should cut that repeat
# cost roughly in proportion to how little L_final actually grows -- not yet measured at real
# floor depth, that is the next thing to benchmark.
#
# ALSO ADDED (later, purely additive, doesn't touch anything above): low-floor completion,
# ported verbatim from prime_sieve_v3.py -- see that file's header for the full rationale.
# window_m's smallest value is 10,000,000, but floors below 7 are each narrower than that
# (floor 6 = [10**6, 10**7) is only 9,000,000 numbers). _low_floor_segments() + the branch at
# the top of main_batch_scanner's write step split a low-floor batch by REAL floor boundary,
# writing each floor that's fully contained in the generated range as its own complete file
# under its own 10p{floor}/ -- and since floors 0-6 together are exactly 9,999,999 numbers, one
# minimum-width request against any floor in that range completes ALL of them in a single pass.
# A floor only partially covered is left out entirely rather than written half-finished.
#
# Nothing about batching, the shared buffer, output format, or CLI changed from v3; this file
# exists so v3 and v4 can be run side by side on the same floor for a direct comparison.
# ==========================================================================================

_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prime_sieve_engine_v4.so")
_lib = None  # lazily loaded, SEPARATELY in each worker process

_POPCOUNT_TABLE = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint32)

# The shared mmap output buffer for the v3/v4 mechanism -- MUST be set as a module-level
# global BEFORE the ProcessPoolExecutor is created / before any task is submitted, so forked
# worker processes (mp_context "fork", set explicitly below -- see main_batch_scanner())
# inherit it via fork()'s whole-process-image duplication. Each worker looks this global up
# directly rather than receiving it as a submitted argument (mmap objects aren't picklable,
# and don't need to be -- that's the whole point).
_shm_mmap = None
_shm_size = 0


def _load_lib():
    global _lib
    if _lib is None:
        if not os.path.exists(_LIB_PATH):
            raise RuntimeError(
                f"Missing {_LIB_PATH} -- build it first: gcc -O3 -shared -fPIC "
                f"prime_sieve_engine_v4.c -o prime_sieve_engine_v4.so -lprimesieve -lstdc++ -lm")
        lib = ctypes.CDLL(_LIB_PATH)
        lib.generate_and_sieve_segment_bits_atomic.argtypes = [
            ctypes.c_uint64,                  # start
            ctypes.c_uint64,                  # stop
            ctypes.c_uint64,                  # distance_hi
            ctypes.c_uint64,                  # distance_lo
            ctypes.c_uint64,                  # window_m
            ctypes.POINTER(ctypes.c_ubyte),   # out_dense_bits (SHARED buffer, not private)
        ]
        lib.generate_and_sieve_segment_bits_atomic.restype = ctypes.c_int
        lib.count_sieving_primes.argtypes = [ctypes.c_uint64]
        lib.count_sieving_primes.restype = ctypes.c_uint64
        lib.count_sieving_primes_range.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
        lib.count_sieving_primes_range.restype = ctypes.c_uint64
        _lib = lib
    return _lib


def count_sieving_primes(limit):
    """Unchanged from prime_sieve_v3.py -- see that file's docstring."""
    lib = _load_lib()
    return int(lib.count_sieving_primes(limit))


def count_sieving_primes_range(start, stop):
    """pi(stop) - pi(start) -- primes in (start, stop]. Thin wrapper over the engine's
    additive count_sieving_primes_range(), used by count_sieving_primes_cached() below to
    count only the NEW territory between a cached L and a larger one, instead of recounting
    from 0 every time."""
    lib = _load_lib()
    return int(lib.count_sieving_primes_range(start, stop))


SIEVING_PRIMES_COUNT_CACHE_FILENAME = "sieving_primes_count_cache.json"


def count_sieving_primes_cached(portal_folder, base_power, limit):
    """pi(limit), reusing a per-floor cache instead of recomputing from 0 every call.

    Motivation: repeat calls to this diagnostic on the SAME floor almost always ask for a
    limit that is equal to, or only marginally larger than, the previous call's limit --
    L_final = isqrt(combined_hi) grows far slower than the floor's own windows do (going
    another 10 windows deeper at floor 20 nudges L_final by single digits out of ~10^10).
    Counting that tiny sliver via count_sieving_primes_range(cached_l, limit) is dramatically
    cheaper than recounting the whole [0, limit] range from scratch, which is exactly what the
    plain count_sieving_primes() path (and every version before this one) does on every call.

    Cache is a single small JSON file per floor: {"l_final": <largest L counted to>,
    "count": <pi(that L)>}. Three cases:
      - no cache yet for this floor              -> full count(0, limit), cache it
      - limit == cached l_final                   -> return the cached count, NO primesieve
                                                       call at all
      - limit >  cached l_final                   -> cached count + count_range(cached_l, limit),
                                                       cache the new (limit, count) pair
      - limit <  cached l_final (rare -- exploring
        a SMALLER limit than before on this floor) -> falls back to a full recount, since the
                                                       cache only ever stores a running total up
                                                       to its largest L, not a queryable prefix
                                                       count at arbitrary smaller points.
    Returns (count, mode) where mode is one of "cold" / "cache_hit" / "incremental" / "shrink"
    -- purely informational, used by main_batch_scanner()'s timing print so a benchmark run can
    show which path was actually taken.
    """
    import json
    cache_dir = os.path.join(portal_folder, f"10p{base_power}")
    cache_path = os.path.join(cache_dir, SIEVING_PRIMES_COUNT_CACHE_FILENAME)

    cached = None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
    except (OSError, ValueError):
        cached = None

    if cached is None or "l_final" not in cached or "count" not in cached:
        count = count_sieving_primes(limit)
        mode = "cold"
    elif limit == cached["l_final"]:
        return cached["count"], "cache_hit"
    elif limit > cached["l_final"]:
        count = cached["count"] + count_sieving_primes_range(cached["l_final"], limit)
        mode = "incremental"
    else:
        count = count_sieving_primes(limit)
        mode = "shrink"

    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"l_final": limit, "count": count}, f)
    except OSError as e:
        print(f"[!] WARNING: could not write sieving-primes-count cache ({e})")

    return count, mode


def format_offset(n):
    """Unchanged from prime_sieve_v3.py."""
    if n == 0:
        return "0"
    if n % 1_000_000 == 0:
        return f"{n // 1_000_000}M"
    if n % 1_000 == 0:
        return f"{n // 1_000}k"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.6f}M".rstrip('0').rstrip('.')
    if n >= 1_000:
        return f"{n / 1_000:.3f}k".rstrip('0').rstrip('.')
    return str(n)


# ------------------------------------------------------------------------------------------
# PGS2 -- "Prime Gap Stream v2": binary, gap-delta + LEB128-varint prime storage format.
# Unchanged from prime_sieve_v3.py -- see prime_sieve_v1.py for the full format rationale.
# The ON-DISK format is completely independent of how the sieve gets computed -- so
# PGS_MAGIC stays "PGS2", not bumped to match this file's own version.
# ------------------------------------------------------------------------------------------

PGS_MAGIC = b"PGS2"


def encode_varint(value):
    """LEB128 unsigned varint: 7 data bits per byte, MSB = continuation flag."""
    if value < 0:
        raise ValueError("encode_varint requires a non-negative value")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def decode_varint(buf, pos):
    """Returns (value, new_pos)."""
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


def write_prime_window(path, primes, generated_at=None):
    """Writes a sorted list of primes (ints, ascending) to `path` in PGS2 format.
    `generated_at` is a unix epoch timestamp (seconds, UTC) recorded in the header --
    defaults to "now" (time.time()) if not given."""
    if generated_at is None:
        generated_at = int(time.time())
    count = len(primes)
    with open(path, "wb") as f:
        f.write(PGS_MAGIC)
        if count == 0:
            f.write(bytes([0]))
            f.write((0).to_bytes(4, "big"))
            f.write(int(generated_at).to_bytes(4, "big"))
            return
        base = primes[0]
        base_bytes = base.to_bytes(max(1, (base.bit_length() + 7) // 8), "big")
        if len(base_bytes) > 255:
            raise ValueError(f"base prime too large for 1-byte length prefix: {base}")
        f.write(bytes([len(base_bytes)]))
        f.write(base_bytes)
        f.write(count.to_bytes(4, "big"))
        f.write(int(generated_at).to_bytes(4, "big"))
        prev = base
        for p in primes[1:]:
            f.write(encode_varint(p - prev))
            prev = p


def read_prime_window_header(path):
    """Reads ONLY the header (base prime, count, generation timestamp) WITHOUT decoding the
    gap stream. Unchanged from prime_sieve_v3.py."""
    with open(path, "rb") as f:
        header = f.read(4 + 1 + 255 + 4 + 4)
    if header[:4] != PGS_MAGIC:
        raise ValueError(f"{path}: not a PGS2 file (bad magic bytes)")
    pos = 4
    base_len = header[pos]
    pos += 1
    base_prime = int.from_bytes(header[pos:pos + base_len], "big") if base_len else None
    pos += base_len
    count = int.from_bytes(header[pos:pos + 4], "big")
    pos += 4
    generated_at = int.from_bytes(header[pos:pos + 4], "big")
    generated_at_iso = datetime.datetime.utcfromtimestamp(generated_at).strftime(
        "%Y-%m-%d %H:%M:%S UTC")
    return {
        "base_prime": base_prime,
        "count": count,
        "generated_at": generated_at,
        "generated_at_iso": generated_at_iso,
    }


def read_prime_window(path):
    """Inverse of write_prime_window(); returns the full sorted list of primes (ints).
    Unchanged from prime_sieve_v3.py."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != PGS_MAGIC:
        raise ValueError(f"{path}: not a PGS2 file (bad magic bytes)")
    pos = 4
    base_len = data[pos]
    pos += 1
    if base_len == 0:
        return []
    base = int.from_bytes(data[pos:pos + base_len], "big")
    pos += base_len
    count = int.from_bytes(data[pos:pos + 4], "big")
    pos += 4
    pos += 4  # generated_at
    primes = [base]
    prev = base
    for _ in range(count - 1):
        gap, pos = decode_varint(data, pos)
        prev += gap
        primes.append(prev)
    return primes


def read_prime_window_head(path, threshold):
    """Unchanged from prime_sieve_v3.py -- see that file for the docstring."""
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != PGS_MAGIC:
        raise ValueError(f"{path}: not a PGS2 file (bad magic bytes)")
    pos = 4
    base_len = data[pos]
    pos += 1
    if base_len == 0:
        return []
    base = int.from_bytes(data[pos:pos + base_len], "big")
    pos += base_len
    count = int.from_bytes(data[pos:pos + 4], "big")
    pos += 4
    pos += 4  # generated_at
    if base > threshold:
        return []
    result = [base]
    prev = base
    for _ in range(count - 1):
        gap, pos = decode_varint(data, pos)
        prev += gap
        if prev > threshold:
            break
        result.append(prev)
    return result


def append_prime_window(path, new_sorted_values, generated_at=None, known_last_value=None):
    """Unchanged from prime_sieve_v3.py -- see that file for the full docstring."""
    if not new_sorted_values:
        return
    if generated_at is None:
        generated_at = int(time.time())

    file_exists = os.path.exists(path)
    if known_last_value is None:
        existing = read_prime_window(path) if file_exists else []
        if not existing:
            write_prime_window(path, new_sorted_values, generated_at=generated_at)
            return
        known_last_value = existing[-1]
    elif not file_exists:
        write_prime_window(path, new_sorted_values, generated_at=generated_at)
        return

    if new_sorted_values[0] <= known_last_value:
        raise ValueError(
            f"append_prime_window: new values must be strictly greater than the file's "
            f"last stored value ({known_last_value}); got {new_sorted_values[0]} first")

    with open(path, "r+b") as f:
        header = f.read(4 + 1 + 255 + 4 + 4)
        base_len = header[4]
        count_pos = 4 + 1 + base_len
        old_count = int.from_bytes(header[count_pos:count_pos + 4], "big")
        new_count = old_count + len(new_sorted_values)
        f.seek(count_pos)
        f.write(new_count.to_bytes(4, "big"))
        f.write(int(generated_at).to_bytes(4, "big"))
        f.seek(0, os.SEEK_END)
        prev = known_last_value
        for v in new_sorted_values:
            f.write(encode_varint(v - prev))
            prev = v


# ------------------------------------------------------------------------------------------
# Segment-cost estimation -- UNCHANGED from prime_sieve_v3.py (same Mertens/li_approx
# analytical model, same equal-cost contiguous batching). v4's change is ENTIRELY in the
# engine's per-prime phase computation -- not in how batches are chosen.
# ------------------------------------------------------------------------------------------

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


def _build_equal_cost_batches(L_final, combined_size, n_batches):
    """Unchanged from prime_sieve_v3.py -- see that file's docstring for the full
    rationale."""
    threshold = min(combined_size, L_final)
    n = max(1, n_batches)

    def cost_upto(x):
        return _cumulative_cost(x, threshold, combined_size)

    total = cost_upto(L_final)
    if total <= 0 or L_final <= 2:
        return [[(2, max(3, L_final))]]

    boundaries = [2]
    lo = 2
    for i in range(1, n):
        target = total * i / n
        a, b = lo, L_final
        while a < b:
            mid = (a + b) // 2
            if cost_upto(mid) < target:
                a = mid + 1
            else:
                b = mid
        boundaries.append(a)
        lo = a
    boundaries.append(L_final)

    boundaries = sorted(set(g for g in boundaries if 2 <= g <= L_final))
    batches = []
    for a, b in zip(boundaries[:-1], boundaries[1:]):
        if a >= b:
            continue
        batches.append([(a, b)])
    if not batches:
        batches = [[(2, L_final)]]
    return batches


def _init_shared_buffer(n_bytes):
    """Unchanged from prime_sieve_v3.py -- allocates the ONE shared output buffer, MUST be
    called BEFORE the ProcessPoolExecutor is created / before the first task is submitted
    (see main_batch_scanner()) so forked workers inherit the mapping."""
    global _shm_mmap, _shm_size
    _shm_mmap = mmap.mmap(-1, n_bytes, flags=mmap.MAP_SHARED)
    _shm_size = n_bytes
    return _shm_mmap


def process_batch(start_stop_list, distance, window_m):
    """Unchanged from prime_sieve_v3.py -- writes ATOMICALLY straight into the ONE shared
    buffer (module-level _shm_mmap/_shm_size, inherited via fork())."""
    lib = _load_lib()
    buf_ctypes = (ctypes.c_ubyte * _shm_size).from_buffer(_shm_mmap)
    out_ptr = ctypes.cast(buf_ctypes, ctypes.POINTER(ctypes.c_ubyte))
    distance_hi = distance >> 64
    distance_lo = distance & 0xFFFFFFFFFFFFFFFF

    had_error = False
    for start, stop in start_stop_list:
        code = lib.generate_and_sieve_segment_bits_atomic(start, stop, distance_hi,
                                                            distance_lo, window_m, out_ptr)
        if code != 0:
            had_error = True

    return had_error


LOW_FLOOR_CUTOFF = 7  # floors 0..6 are each narrower than the smallest supported window_m
                      # (10,000,000): floor 6 = [10**6, 10**7) is only 9,000,000 numbers.
                      # 10**7 is the first floor boundary that's an exact multiple of that
                      # width, so from floor 7 on a window can never straddle a floor
                      # boundary -- see _low_floor_segments()'s docstring for what floors
                      # below this cutoff need instead. Ported verbatim from
                      # prime_sieve_v3.py -- see that file's header for the full rationale.


def _low_floor_segments(base_power, combined_lo, combined_hi):
    """For base_power < LOW_FLOOR_CUTOFF, a single combined window can span MULTIPLE
    actual digit-based floors at once (e.g. requesting floor 0 with the default
    window_m=10,000,000 produces a combined range covering all of floors 0 through 6,
    plus one leftover number that's just the start of floor 7). Returns a list of
    (floor, floor_lo, floor_hi) triples -- one per floor FULLY contained in
    [combined_lo, combined_hi) -- for the caller to write each as its own complete,
    self-contained window under its own 10p{floor}/ folder (a low floor never needs
    more than one file, since its whole width is always < window_m). Any floor only
    PARTIALLY covered -- the trailing one, cut off by wherever this batch's generated
    range happens to end -- is simply left out, so it's never written complete OR
    truncated; a later request that generates far enough picks it up cleanly in one
    pass instead of this one leaving a half-finished file behind.

    Returns [] (meaning: caller should fall back to the ordinary per-target_idx write
    path, unchanged) if base_power is already >= LOW_FLOOR_CUTOFF, or if combined_lo
    doesn't actually align with base_power's own floor start (10**base_power) -- the
    split only applies to the ordinary "first request for this low floor" shape;
    anything else is left to the existing logic rather than guessed at."""
    if base_power >= LOW_FLOOR_CUTOFF or combined_lo != 10 ** base_power:
        return []
    segments = []
    floor = base_power
    while True:
        floor_lo = 10 ** floor
        floor_hi = 10 ** (floor + 1)
        if floor_hi > combined_hi:
            break
        segments.append((floor, floor_lo, floor_hi))
        floor += 1
    return segments


def main_batch_scanner(base_power, target_idx_list, window_m, write_files=True,
                        compute_sieving_primes_count=True):
    target_idx_list = sorted(target_idx_list)
    BASE = 10 ** base_power
    windows = [(BASE + idx * window_m, window_m) for idx in target_idx_list]
    for i in range(1, len(windows)):
        assert windows[i][0] == windows[i - 1][0] + window_m, (
            f"Batch mode requires ADJACENT windows (consecutive target_idx) -- gap between "
            f"window {i-1} (target_idx={target_idx_list[i-1]}) and {i} "
            f"(target_idx={target_idx_list[i]})")

    combined_lo = windows[0][0]
    combined_hi = windows[-1][0] + window_m
    N = len(windows)
    combined_size = combined_hi - combined_lo
    combined_bytes = (combined_size + 7) // 8

    print("\n" + "=" * 70)
    print(f"[*] BATCH {VERSION} (primesieve, SHARED mmap buffer, atomic OR, inlined phase "
          f"modulo, PGS2 binary output): {N} windows (target_idx {target_idx_list[0]}.."
          f"{target_idx_list[-1]}), level 10^{base_power}")
    print(f"[*] Combined range: [{combined_lo:,}, {combined_hi:,})  "
          f"size={combined_size:,}  ({combined_bytes/1e6:.1f} MB bit-packed)")
    if not write_files:
        print(f"[*] WRITE_FILES=False -- no PGS2 files will be written this run; only "
              f"aggregate prime counts will be reported.")
    print("=" * 70)

    L_final = math.isqrt(combined_hi) + 1
    print(f"[*] L_final (sieving-prime base limit): {L_final:,}")
    if compute_sieving_primes_count:
        t_count_start = time.perf_counter()
        sieving_primes_count, count_mode = count_sieving_primes_cached(
            BASE_STORAGE_10PN, base_power, L_final)
        t_count = time.perf_counter() - t_count_start
        base_gen_seconds = t_count   # v4.1: was print-only in v4.py, now threaded through to
                                      # write_scan_metrics_handoff() -- see this file's header
        mode_note = {
            "cold": "full count, no cache yet for this floor",
            "cache_hit": "cache hit, L_final unchanged since last run on this floor",
            "incremental": "incremental -- reused cached count below the previous L_final",
            "shrink": "full count -- requested L_final smaller than the cached one",
        }[count_mode]
        print(f"[*] Active sieving primes used (pi(L_final)): {sieving_primes_count:,} "
              f"(computed in {t_count:.3f}s -- {mode_note})")
    else:
        sieving_primes_count = None
        base_gen_seconds = None   # v4.1: genuinely not measured (this stat was skipped
                                   # entirely) -- left as None (blank in the CSV) rather than
                                   # 0.0, which would misleadingly claim it was free
        print(f"[*] Active sieving primes count (pi(L_final)): SKIPPED "
              f"(compute_sieving_primes_count=False, the default -- pure diagnostic stat, not "
              f"used by the sieve itself; can take minutes at extreme depth). Pass 1 as CLI "
              f"position 7 to compute it.")

    n_batches = max(1, MAX_WORKERS * BATCHES_PER_WORKER)
    batches = _build_equal_cost_batches(L_final, combined_size, n_batches)

    print(f"[*] Equal-cost contiguous batches: {len(batches)} "
          f"({MAX_WORKERS} parallel processes, {len(batches)} total jump_to() bootstrap "
          f"calls)")
    print(f"[*] Shared output buffer: {combined_bytes/1e6:.1f} MB, ONE COPY TOTAL (unchanged "
          f"from v3 -- see that file's header for why).")

    # Allocate the SHARED buffer BEFORE creating the ProcessPoolExecutor -- workers fork()
    # after this point and inherit the mapping (see _init_shared_buffer()'s docstring).
    _init_shared_buffer(combined_bytes)
    ctx = multiprocessing.get_context("fork")  # explicit, not relying on the platform default
                                                # -- correctness of the shared-mmap-before-
                                                # fork trick REQUIRES fork(), not spawn/
                                                # forkserver (see prime_sieve_v3.py header)

    errors = 0
    print_interval = max(1, len(batches) // 30) if batches else 1

    t_start = time.perf_counter()
    t_last_print = t_start
    with ProcessPoolExecutor(max_workers=MAX_WORKERS, mp_context=ctx) as executor:
        batches_iter = iter(batches)
        in_flight = {}

        def _submit_next():
            try:
                batch = next(batches_iter)
            except StopIteration:
                return False
            fut = executor.submit(process_batch, batch, combined_lo, combined_size)
            in_flight[fut] = True
            return True

        for _ in range(MAX_WORKERS):
            if not _submit_next():
                break

        done_count = 0
        while in_flight:
            done_set, _ = concurrent.futures.wait(
                in_flight.keys(), return_when=concurrent.futures.FIRST_COMPLETED)
            for fut in done_set:
                del in_flight[fut]
                had_error = fut.result()
                if had_error:
                    errors += 1
                done_count += 1
                _submit_next()

            if done_count % print_interval == 0 or not in_flight:
                t_now = time.perf_counter()
                progress = done_count / len(batches) * 100
                print_delta = t_now - t_last_print
                rate = done_count / (t_now - t_start) if (t_now - t_start) > 0 else 0
                remaining = (len(batches) - done_count) / rate if rate > 0 else float("inf")
                print(f"[+] Progress: {progress:.2f}% ({done_count}/{len(batches)} batches) | "
                      f"time: {t_now - t_start:.2f}s (+{print_delta:.2f}s since last print) | "
                      f"ETA ~{remaining:.0f}s" + (f" | ERRORS={errors}" if errors else ""))
                t_last_print = t_now
    t_sieve = time.perf_counter() - t_start

    print(f"\n[*] Batch sieve done in {t_sieve:.2f}s. Unpacking result and writing windows...")
    if errors:
        print(f"[!] WARNING: {errors} batches returned a primesieve error -- results INCOMPLETE.")

    # v4.1: everything from here to each branch's write_scan_metrics_handoff() call below is
    # timed as ONE "write" phase (unpack bits -> build candidate lists -> PGS2 file write) --
    # the one phase of the three (base-gen/sieve/write) that had NO timer at all in v4.py, see
    # this file's header. bytes_written sums os.path.getsize() over every window actually
    # written this run (stays 0 in count-only mode, where nothing is written).
    t_write_start = time.perf_counter()
    bytes_written = 0

    window_occupied_bits = np.frombuffer(_shm_mmap, dtype=np.uint8, count=combined_bytes).copy()
    _shm_mmap.close()

    low_floor_segments = _low_floor_segments(base_power, combined_lo, combined_hi)
    if low_floor_segments:
        # base_power < LOW_FLOOR_CUTOFF: this combined range spans several REAL floors at
        # once (see _low_floor_segments' docstring) -- write each complete one under its
        # own 10p{floor}/ folder instead of the single 10p{base_power}/ the normal path
        # below would use, and skip the write loop entirely once done. Ported verbatim
        # from prime_sieve_v3.py.
        full_unpacked = np.unpackbits(window_occupied_bits, count=combined_size,
                                       bitorder='little').astype(bool)
        total_primes_found = 0
        floor_counts = []
        for floor, floor_lo, floor_hi in low_floor_segments:
            w = floor_hi - floor_lo
            lo_rel = floor_lo - combined_lo
            segment = full_unpacked[lo_rel:lo_rel + w]

            this_floor_folder = os.path.join(BASE_STORAGE_10PN, f"10p{floor}", "source_primes")
            window_path = os.path.join(this_floor_folder, f"PRIME_WINDOW_10p{floor}_off_0.bin")
            generated_at = int(time.time())

            if write_files:
                os.makedirs(this_floor_folder, exist_ok=True)
                free_locally = np.nonzero(~segment)[0]
                candidates = [floor_lo + int(k) for k in free_locally if (floor_lo + int(k)) > 1]
                count = len(candidates)
                write_prime_window(window_path, candidates, generated_at=generated_at)
                bytes_written += os.path.getsize(window_path)   # v4.1
            else:
                count = int(np.count_nonzero(~segment))
                if floor_lo == 1 and w > 0 and not segment[0]:
                    count -= 1  # exclude "1" itself -- not prime, but ~segment[0] counts it
            total_primes_found += count
            floor_counts.append((floor, count))

        skipped_floor = low_floor_segments[-1][0] + 1
        print(f"\n[*] Low-floor batch: floor(s) {low_floor_segments[0][0]}-"
              f"{low_floor_segments[-1][0]} written complete, each as its own 10p{{N}} "
              f"window -- floor {skipped_floor} would be cut off by this batch's range, so "
              f"it was skipped (not written partially).")
        for floor, count in floor_counts:
            print(f"    10p{floor}: {count:,} primes")
        t_write = time.perf_counter() - t_write_start   # v4.1
        print(f"\n[*] TOTAL PRIMES FOUND this run: {total_primes_found:,} across "
              f"{len(low_floor_segments)} floor(s)"
              + ("" if write_files else "  (NO FILES WRITTEN -- count-only mode)"))

        write_scan_metrics_handoff(BASE_STORAGE_10PN, L_final, sieving_primes_count,
                                    total_primes_found=total_primes_found,
                                    windows_processed=len(low_floor_segments),
                                    write_files=write_files,
                                    base_gen_seconds=base_gen_seconds, sieve_seconds=t_sieve,
                                    write_seconds=t_write, bytes_written=bytes_written)
        print("=" * 70)
        return

    floor_folder = os.path.join(BASE_STORAGE_10PN, f"10p{base_power}", "source_primes")
    if write_files:
        os.makedirs(floor_folder, exist_ok=True)

    # Per-window unpacking -- unchanged from prime_sieve_v3.py (see that file's header for the
    # full rationale: cuts peak memory for this step from O(combined_size) to O(window_m)).
    use_fast_unpack = (window_m % 8 == 0)
    if use_fast_unpack:
        bytes_per_window = window_m // 8
    else:
        window_occupied_full = np.unpackbits(window_occupied_bits, count=combined_size,
                                              bitorder='little').astype(bool)

    total_primes_found = 0
    for wi, (distance, w) in enumerate(windows):
        lo_rel = distance - combined_lo
        if use_fast_unpack:
            byte_start = lo_rel // 8
            segment = np.unpackbits(window_occupied_bits[byte_start:byte_start + bytes_per_window],
                                     count=w, bitorder='little').astype(bool)
        else:
            hi_rel = lo_rel + w
            segment = window_occupied_full[lo_rel:hi_rel]

        offset = distance - BASE
        target_tag = f"10p{base_power}_off_{format_offset(offset)}"
        window_path = os.path.join(floor_folder, f"PRIME_WINDOW_{target_tag}.bin")
        generated_at = int(time.time())

        if write_files:
            free_locally = np.nonzero(~segment)[0]
            candidates = [distance + int(k) for k in free_locally if (distance + int(k)) > 1]
            total_primes_found += len(candidates)
            write_prime_window(window_path, candidates, generated_at=generated_at)
            bytes_written += os.path.getsize(window_path)   # v4.1
        else:
            count = int(np.count_nonzero(~segment))
            if distance == 1 and w > 0 and not segment[0]:
                count -= 1
            total_primes_found += count

    t_write = time.perf_counter() - t_write_start   # v4.1
    print(f"\n[*] TOTAL PRIMES FOUND this run: {total_primes_found:,} across {N} windows"
          + ("" if write_files else "  (NO FILES WRITTEN -- count-only mode)"))

    write_scan_metrics_handoff(BASE_STORAGE_10PN, L_final, sieving_primes_count,
                                total_primes_found=total_primes_found, windows_processed=N,
                                write_files=write_files,
                                base_gen_seconds=base_gen_seconds, sieve_seconds=t_sieve,
                                write_seconds=t_write, bytes_written=bytes_written)

    print("=" * 70)


SCAN_METRICS_FILENAME = "last_scan_metrics.json"


def write_scan_metrics_handoff(portal_folder, l_final, sieving_primes_count,
                                total_primes_found=None, windows_processed=None,
                                write_files=None, base_gen_seconds=None, sieve_seconds=None,
                                write_seconds=None, bytes_written=None):
    """Same role as prime_sieve_v3.py/v4.py's version -- writes the one JSON file
    orchestrator_v3.py reads back (read_scan_metrics_handoff()) to log a benchmark_log.csv
    row without needing to re-derive anything itself. v4.1 ADDS the four timing/size fields
    (base_gen_seconds, sieve_seconds, write_seconds, bytes_written) -- see this file's own
    header for why they exist now when they didn't in v3/v4. Each is included only if not
    None, same pattern the pre-existing optional fields already use (e.g. a
    compute_sieving_primes_count=False run has no base_gen_seconds to report, and this
    key simply won't be in the JSON at all rather than being written as a misleading 0)."""
    import json
    path = os.path.join(portal_folder, SCAN_METRICS_FILENAME)
    data = {"l_final": l_final, "sieving_primes_count": sieving_primes_count}
    if total_primes_found is not None:
        data["total_primes_found"] = total_primes_found
    if windows_processed is not None:
        data["windows_processed"] = windows_processed
    if write_files is not None:
        data["write_files"] = write_files
    if base_gen_seconds is not None:
        data["base_gen_seconds"] = base_gen_seconds
    if sieve_seconds is not None:
        data["sieve_seconds"] = sieve_seconds
    if write_seconds is not None:
        data["write_seconds"] = write_seconds
    if bytes_written is not None:
        data["bytes_written"] = bytes_written
    try:
        os.makedirs(portal_folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError as e:
        print(f"[!] WARNING: could not write scan metrics handoff ({e})")


if __name__ == "__main__":
    import sys

    print("=" * 70)
    print(f"[*] PRIME SIEVE -- {VERSION} (primesieve, shared mmap buffer, atomic OR, inlined "
          f"phase modulo, base/sieve/write timing + bytes-written, PGS2 binary output)")
    print("    lineage: prime_sieve_v4.py (this folder) -- see this file's header for what changed")
    print("=" * 70)

    # CONSTELLATION_PORTAL_DIR: the GUI's Settings tab lets the user point the whole portal
    # at a different disk/folder (so bases can live in different places). When it launches
    # this script as a WSL subprocess it sets this env var; if unset, falls back to a
    # CONSTELLATION_PORTAL folder next to the application root, matching
    # AppSettings.default_storage_path.
    env_override = os.environ.get("CONSTELLATION_PORTAL_DIR")
    if env_override:
        BASE_STORAGE_10PN = env_override
    else:
        BASE_STORAGE_10PN = os.path.abspath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "CONSTELLATION_PORTAL"))
    print(f"[*] Windows written to: {BASE_STORAGE_10PN}\\10p{{N}}\\source_primes\\")

    if len(sys.argv) > 4:
        base_exponent = int(sys.argv[1])
        target_idx_start = int(sys.argv[2])
        target_idx_stop = int(sys.argv[3])
        MAX_WORKERS = int(sys.argv[4])
    else:
        base_exponent = 25
        target_idx_start = 49
        target_idx_stop = 52
        MAX_WORKERS = 24

    if len(sys.argv) > 5:
        BATCHES_PER_WORKER = int(sys.argv[5])

    WRITE_FILES = True
    if len(sys.argv) > 6:
        WRITE_FILES = bool(int(sys.argv[6]))

    if len(sys.argv) > 7:
        COMPUTE_SIEVING_PRIMES_COUNT = bool(int(sys.argv[7]))

    # WINDOW_M: how many numbers each target_idx step covers. The same constant also exists
    # in orchestrator_v3.py/orchestrator_loop_helpers.py -- all copies must be kept in sync.
    # Optional CLI position 8. Default unchanged (10_000_000) when omitted.
    WINDOW_M = int(sys.argv[8]) if len(sys.argv) > 8 else 10 ** 7
    target_idx_list = list(range(target_idx_start, target_idx_stop + 1))

    print("Start time:", datetime.datetime.now().strftime("%H:%M:%S"))
    main_batch_scanner(base_exponent, target_idx_list, WINDOW_M, write_files=WRITE_FILES,
                        compute_sieving_primes_count=COMPUTE_SIEVING_PRIMES_COUNT)
