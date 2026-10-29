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

import window_sharding
import work_plan_v5
from pgs2_vector import PGS_MAGIC, write_prime_window_offsets


VERSION = "v5"     # bump this whenever this file changes, so console output alone identifies
                    # exactly which iteration of the code produced it.

MAX_WORKERS = 24
BATCHES_PER_WORKER = 2    # how many contiguous cost-equal batches per worker

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
# prime_sieve_v5.py
#
# Batch scanner for engine v5 (prime_sieve_engine_v5.c), driven by orchestrator_v3.py when
# SCANNER_VERSION = "v5". Output (PGS2 files, metrics handoff, benchmark_log.csv columns) is
# byte-identical to prime_sieve_v4_1.py apart from the PGS2 generation timestamp;
# unitTests/test_engine_v5_identity.py checks that.
#
# Pipeline:
#   - Odd-only shared buffer (prime_sieve_engine_v5.c): bit i stands for the odd number
#     first_odd + 2*i of the combined range, so the buffer is half the size of a bit per
#     number and p = 2 is never sieved; _odd_window_marks() maps a window back onto it, and
#     the prime 2 is added where a window contains it.
#   - Phase computation (prime_sieve_engine_v5.c): first_odd mod p via an inlined 128/64
#     `divq` fast path with the full u128 division as fallback.
#   - Two job kinds per run (work_plan_v5.py): segmented slices of the buffer, sieved in
#     cache-sized segments by the small primes, and equal-cost batches of the remaining
#     sieving primes, each striding the whole buffer with atomic ORs.
#   - count_sieving_primes_cached(): per-floor cache for pi(L_final), counting only the
#     sliver between the cached L and the new L_final.
#   - Shared mmap output buffer with atomic-OR marking, per-window unpacking read straight
#     from the mapping (no copy of the whole buffer), and low-floor splitting by real floor
#     boundary (see prime_sieve_v3.py's header).
#   - Window output as NumPy arrays end to end: _window_prime_offsets() gives p - lo as
#     int64, and pgs2_vector encodes the gap stream in one vectorized pass per window.
#   - Timers for base-prime generation, the parallel sieve pass and the unpack-and-write
#     phase, plus a bytes-written counter, reported through write_scan_metrics_handoff().
# ==========================================================================================

_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prime_sieve_engine_v5.so")
_lib = None  # lazily loaded, SEPARATELY in each worker process

_POPCOUNT_TABLE = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint32)

# The shared mmap output buffer -- MUST be set as a module-level
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
                f"prime_sieve_engine_v5.c -o prime_sieve_engine_v5.so -lprimesieve -lstdc++ -lm")
        lib = ctypes.CDLL(_LIB_PATH)
        lib.sieve_odd_bits_atomic.argtypes = [
            ctypes.c_uint64,                  # start
            ctypes.c_uint64,                  # stop
            ctypes.c_uint64,                  # first_odd_hi
            ctypes.c_uint64,                  # first_odd_lo
            ctypes.c_uint64,                  # n_bits
            ctypes.POINTER(ctypes.c_ubyte),   # out_odd_bits (SHARED buffer, not private)
        ]
        lib.sieve_odd_bits_atomic.restype = ctypes.c_int
        lib.sieve_odd_segmented.argtypes = [
            ctypes.c_uint64,                  # stop (segmented primes are 3..stop-1)
            ctypes.c_uint64,                  # first_odd_hi
            ctypes.c_uint64,                  # first_odd_lo
            ctypes.c_uint64,                  # bit_lo (multiple of 64)
            ctypes.c_uint64,                  # bit_hi
            ctypes.c_uint64,                  # segment_words
            ctypes.POINTER(ctypes.c_uint64),  # out_words (SHARED buffer)
        ]
        lib.sieve_odd_segmented.restype = ctypes.c_int
        lib.count_sieving_primes.argtypes = [ctypes.c_uint64]
        lib.count_sieving_primes.restype = ctypes.c_uint64
        lib.count_sieving_primes_range.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
        lib.count_sieving_primes_range.restype = ctypes.c_uint64
        _lib = lib
    return _lib


def count_sieving_primes(limit):
    """pi(limit): how many sieving primes p in [2, limit] (limit = L_final) were used to
    sieve the combined window, counted by libprimesieve via the C engine."""
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

# KNOWN_PI_10N -- exact pi(10^n) values for n=1..29, taken from the "x, pi(x)" table on
# Wikipedia's Prime-counting function page (see KNOWN_PI_SOURCE_URL). That page in turn
# cites the primary sources for each value (Meissel/Lehmer-method computations by Buethe/
# Franke/Jost/Kleinjung and Platt up to 10^24-25, Staple for 10^26, and Baugh/Walisch for
# 10^27-29 -- see the Wikipedia article's own footnotes for full citations).
#
# count_sieving_primes_cached() below already avoids recounting a floor's ENTIRE
# [0, L_final] range on every call once a cache exists for that floor (see that function's
# own docstring) -- but the very FIRST call on a floor still pays the full
# count_sieving_primes(0, L_final) cost from scratch: at floor-scale L_final (order 10^13+)
# that alone can take minutes. Since L_final = isqrt(combined_hi) is itself only ~half as
# many digits as the floor it belongs to, a floor most people would ever reach (order 10^58
# or below) has an L_final at or below 10^29 -- squarely inside this table's range. Seeding
# the cold-start count from the largest known pi(10^n) <= L_final and counting only the
# remaining sliver via count_sieving_primes_range() turns that first-ever call into the
# same cheap "incremental" shape every SUBSEQUENT call on that floor already gets, instead
# of a full from-zero recount.
#
# This table is used ONLY when use_known_pi_seed=True is explicitly passed through (default
# False everywhere -- see COMPUTE_SIEVING_PRIMES_COUNT's own comment for the sibling "off by
# default" reasoning). Even if a transcription error ever crept into a single entry here, the
# worst case is a wrong number in one benchmark_log.csv diagnostic column -- sieving_primes_
# count is never read by the sieve/marking logic itself (see this file's very first comment
# block above), so this table carries zero correctness risk for the actual generated primes.
KNOWN_PI_SOURCE_URL = "https://en.wikipedia.org/wiki/Prime-counting_function"

KNOWN_PI_10N = {
    1: 4,
    2: 25,
    3: 168,
    4: 1229,
    5: 9592,
    6: 78498,
    7: 664579,
    8: 5761455,
    9: 50847534,
    10: 455052511,
    11: 4118054813,
    12: 37607912018,
    13: 346065536839,
    14: 3204941750802,
    15: 29844570422669,
    16: 279238341033925,
    17: 2623557157654233,
    18: 24739954287740860,
    19: 234057667276344607,
    20: 2220819602560918840,
    21: 21127269486018731928,
    22: 201467286689315906290,
    23: 1925320391606803968923,
    24: 18435599767349200867866,
    25: 176846309399143769411680,
    26: 1699246750872437141327603,
    27: 16352460426841680446427399,
    28: 157589269275973410412739598,
    29: 1520698109714272166094258063,
}


def _seed_from_known_pi(limit):
    """Returns (seed_l, seed_count, source_url) for the LARGEST 10**n <= limit that
    KNOWN_PI_10N has an entry for, or None if limit < 10 (no known power of ten fits) or
    limit is small enough that seeding wouldn't save anything anyway. Pure function, no
    ctypes/primesieve dependency -- deliberately kept that way so it's unit-testable without
    the compiled engine .so being present (see this repo's unitTests/ for that test)."""
    best_n = None
    for n in KNOWN_PI_10N:
        if 10 ** n <= limit and (best_n is None or n > best_n):
            best_n = n
    if best_n is None:
        return None
    return 10 ** best_n, KNOWN_PI_10N[best_n], KNOWN_PI_SOURCE_URL


def count_sieving_primes_cached(portal_folder, base_power, limit, use_known_pi_seed=False):
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

    use_known_pi_seed (default False): when the "no cache yet"/"smaller limit" cases above
    would otherwise fall back to a full count_sieving_primes(0, limit) recount, try
    _seed_from_known_pi(limit) first -- if it finds a known pi(10^n) at or below limit (see
    KNOWN_PI_10N above), seed from THAT instead of 0 and only actually count the sliver from
    there up to limit via count_sieving_primes_range(). Turns what would otherwise be the
    single most expensive call this function ever makes into the same cheap shape as every
    later "incremental" call. When a seed is used, the cache also records which one
    (seeded_from: {power_of_ten, value, source}) so the number's provenance stays visible to
    anyone inspecting the cache file directly.

    Returns (count, mode) where mode is one of "cold" / "cache_hit" / "incremental" / "shrink"
    / "seeded" -- purely informational, used by main_batch_scanner()'s timing print so a
    benchmark run can show which path was actually taken.
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

    seeded_from = None
    if cached is None or "l_final" not in cached or "count" not in cached:
        seed = _seed_from_known_pi(limit) if use_known_pi_seed else None
        if seed is not None:
            seed_l, seed_count, source = seed
            count = seed_count + count_sieving_primes_range(seed_l, limit)
            mode = "seeded"
            seeded_from = {"power_of_ten": len(str(seed_l)) - 1, "value": seed_count,
                            "source": source}
        else:
            count = count_sieving_primes(limit)
            mode = "cold"
    elif limit == cached["l_final"]:
        return cached["count"], "cache_hit"
    elif limit > cached["l_final"]:
        count = cached["count"] + count_sieving_primes_range(cached["l_final"], limit)
        mode = "incremental"
    else:
        seed = _seed_from_known_pi(limit) if use_known_pi_seed else None
        if seed is not None:
            seed_l, seed_count, source = seed
            count = seed_count + count_sieving_primes_range(seed_l, limit)
            mode = "seeded"
            seeded_from = {"power_of_ten": len(str(seed_l)) - 1, "value": seed_count,
                            "source": source}
        else:
            count = count_sieving_primes(limit)
            mode = "shrink"

    try:
        os.makedirs(cache_dir, exist_ok=True)
        cache_entry = {"l_final": limit, "count": count}
        if seeded_from is not None:
            cache_entry["seeded_from"] = seeded_from
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache_entry, f)
    except OSError as e:
        print(f"[!] WARNING: could not write sieving-primes-count cache ({e})")

    return count, mode


def format_offset(n):
    """Compact offset label for window filenames: exact multiples of 1,000,000 / 1,000 as
    "<n>M" / "<n>k", otherwise a trimmed decimal M/k form or the plain integer."""
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
# See prime_sieve_v1.py for the format writeup. The on-disk format is independent of how
# the sieve is computed, so PGS_MAGIC stays "PGS2". Writing goes through pgs2_vector.
# ------------------------------------------------------------------------------------------


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
    lo = primes[0] if primes else 0
    offsets = np.array([p - lo for p in primes], dtype=np.int64)
    write_prime_window_offsets(path, lo, offsets, generated_at=generated_at)


def read_prime_window_header(path):
    """Reads ONLY the header (base prime, count, generation timestamp) WITHOUT decoding the
    gap stream."""
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
    """Inverse of write_prime_window(); returns the full sorted list of primes (ints)."""
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
    """Reads primes from `path` in order, stopping as soon as a value EXCEEDS `threshold`
    (a value equal to threshold IS included). Used to peek a bounded number of entries
    into the next window during streaming k-tuple matching without decoding the whole
    file."""
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
    """Appends `new_sorted_values` to a growing PGS2 file without rewriting it: patches the
    count/generated_at header fields in place and appends freshly gap-encoded bytes at the
    end, so each append costs O(len(new_sorted_values)) instead of O(existing count).

    `known_last_value`, if given, is trusted as the file's current last value instead of
    decoding the whole gap stream to find it. `new_sorted_values` must be sorted ascending
    and strictly greater than that last value. Creates the file (write_prime_window()) if
    it doesn't exist yet or is empty."""
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


def _init_shared_buffer(n_bytes):
    """Allocates the ONE shared output buffer. MUST be called BEFORE the
    ProcessPoolExecutor is created / before the first task is submitted (see
    main_batch_scanner()) so forked workers inherit the mapping. The size is rounded up to
    whole 64-bit words for the segmented path's word-wide ORs."""
    global _shm_mmap, _shm_size
    n_bytes = max(8, (n_bytes + 7) // 8 * 8)
    _shm_mmap = mmap.mmap(-1, n_bytes, flags=mmap.MAP_SHARED)
    _shm_size = n_bytes
    return _shm_mmap


def process_batch(start_stop_list, first_odd, n_bits):
    """Writes ATOMICALLY straight into the ONE shared odd-only buffer (module-level
    _shm_mmap/_shm_size, inherited via fork())."""
    lib = _load_lib()
    buf_ctypes = (ctypes.c_ubyte * _shm_size).from_buffer(_shm_mmap)
    out_ptr = ctypes.cast(buf_ctypes, ctypes.POINTER(ctypes.c_ubyte))
    first_odd_hi = first_odd >> 64
    first_odd_lo = first_odd & 0xFFFFFFFFFFFFFFFF

    had_error = False
    for start, stop in start_stop_list:
        code = lib.sieve_odd_bits_atomic(start, stop, first_odd_hi, first_odd_lo, n_bits,
                                         out_ptr)
        if code != 0:
            had_error = True

    return had_error


def process_slice(bit_lo, bit_hi, first_odd, small_stop, segment_words):
    """Sieves bits [bit_lo, bit_hi) of the shared buffer with the primes 3..small_stop-1
    (sieve_odd_segmented()); returns True on an engine error."""
    lib = _load_lib()
    words = (ctypes.c_uint64 * (_shm_size // 8)).from_buffer(_shm_mmap)
    out_ptr = ctypes.cast(words, ctypes.POINTER(ctypes.c_uint64))
    code = lib.sieve_odd_segmented(small_stop, first_odd >> 64, first_odd & 0xFFFFFFFFFFFFFFFF,
                                   bit_lo, bit_hi, segment_words, out_ptr)
    return code != 0


def _odd_window_marks(odd_bits, first_odd, lo, hi):
    """(fo, marked) for the odd numbers of [lo, hi): fo is the first of them and marked[k]
    is True when fo + 2*k is composite. odd_bits is the odd-only buffer whose bit 0 stands
    for first_odd; only the bytes covering [lo, hi) are unpacked."""
    fo = lo | 1
    count = max(0, (hi - fo + 1) // 2)
    bit0 = (fo - first_odd) // 2
    byte_lo, shift = bit0 >> 3, bit0 & 7
    raw = odd_bits[byte_lo:byte_lo + (shift + count + 7) // 8]
    marked = np.unpackbits(raw, bitorder='little')[shift:shift + count].astype(bool)
    return fo, marked


def _window_prime_offsets(odd_bits, first_odd, lo, hi):
    """Ascending primes of [lo, hi) as an int64 array of p - lo: 2 when the window contains
    it, then every unmarked odd number above 1."""
    fo, marked = _odd_window_marks(odd_bits, first_odd, lo, hi)
    offsets = (fo - lo) + 2 * np.flatnonzero(~marked).astype(np.int64)
    if fo == 1 and offsets.size and offsets[0] == 1 - lo:
        offsets = offsets[1:]  # 1 is odd and never marked, but not prime
    if lo <= 2 < hi:
        offsets = np.concatenate((np.array([2 - lo], dtype=np.int64), offsets))
    return offsets


def _window_prime_count(odd_bits, first_odd, lo, hi):
    """len(_window_prime_offsets(...)) without building the array."""
    fo, marked = _odd_window_marks(odd_bits, first_odd, lo, hi)
    count = int(np.count_nonzero(~marked))
    if fo == 1 and len(marked) and not marked[0]:
        count -= 1  # 1 is odd and never marked, but not prime
    if lo <= 2 < hi:
        count += 1
    return count


LOW_FLOOR_CUTOFF = 7  # floors 0..6 are each narrower than the smallest supported window_m
                      # (10,000,000): floor 6 = [10**6, 10**7) is only 9,000,000 numbers.
                      # 10**7 is the first floor boundary that's an exact multiple of that
                      # width, so from floor 7 on a window can never straddle a floor
                      # boundary -- see _low_floor_segments()'s docstring for what floors
                      # below this cutoff need instead.


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
                        compute_sieving_primes_count=True, use_known_pi_seed=False,
                        segment_kb=work_plan_v5.DEFAULT_SEGMENT_KB):
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
    first_odd = combined_lo | 1
    n_odd = max(0, (combined_hi - first_odd + 1) // 2)
    combined_bytes = (n_odd + 7) // 8

    print("\n" + "=" * 70)
    print(f"[*] BATCH {VERSION} (primesieve, SHARED mmap buffer, atomic OR, inlined phase "
          f"modulo, PGS2 binary output): {N} windows (target_idx {target_idx_list[0]}.."
          f"{target_idx_list[-1]}), level 10^{base_power}")
    print(f"[*] Combined range: [{combined_lo:,}, {combined_hi:,})  "
          f"size={combined_size:,}  ({combined_bytes/1e6:.1f} MB, one bit per odd number)")
    if not write_files:
        print(f"[*] WRITE_FILES=False -- no PGS2 files will be written this run; only "
              f"aggregate prime counts will be reported.")
    print("=" * 70)

    L_final = math.isqrt(combined_hi) + 1
    print(f"[*] L_final (sieving-prime base limit): {L_final:,}")
    if compute_sieving_primes_count:
        t_count_start = time.perf_counter()
        sieving_primes_count, count_mode = count_sieving_primes_cached(
            BASE_STORAGE_10PN, base_power, L_final, use_known_pi_seed=use_known_pi_seed)
        t_count = time.perf_counter() - t_count_start
        base_gen_seconds = t_count   # reported through write_scan_metrics_handoff()
        mode_note = {
            "cold": "full count, no cache yet for this floor",
            "cache_hit": "cache hit, L_final unchanged since last run on this floor",
            "incremental": "incremental -- reused cached count below the previous L_final",
            "shrink": "full count -- requested L_final smaller than the cached one",
            "seeded": f"seeded from a known pi(10^n) value (source: {KNOWN_PI_SOURCE_URL}), "
                      f"only the remaining sliver up to L_final was actually counted",
        }[count_mode]
        print(f"[*] Active sieving primes used (pi(L_final)): {sieving_primes_count:,} "
              f"(computed in {t_count:.3f}s -- {mode_note})")
    else:
        sieving_primes_count = None
        base_gen_seconds = None   # not measured: None (blank in the CSV), not 0.0, which
                                   # would claim it was free
        print(f"[*] Active sieving primes count (pi(L_final)): SKIPPED "
              f"(compute_sieving_primes_count=False, the default -- pure diagnostic stat, not "
              f"used by the sieve itself; can take minutes at extreme depth). Pass 1 as CLI "
              f"position 7 to compute it.")

    n_batches = max(1, MAX_WORKERS * BATCHES_PER_WORKER)
    seg_bits = work_plan_v5.segment_bits(segment_kb)
    small_stop = work_plan_v5.small_prime_stop(seg_bits, L_final)
    slices = work_plan_v5.plan_slices(n_odd, n_batches)
    batches = work_plan_v5.build_equal_cost_batches(L_final, combined_size, n_batches,
                                                    lo=small_stop)
    jobs = ([(process_slice, (lo, hi, first_odd, small_stop, seg_bits // 64))
             for lo, hi in slices]
            + [(process_batch, (batch, first_odd, n_odd)) for batch in batches])

    print(f"[*] Segmented slices: {len(slices)} ({segment_kb} KiB segments, primes "
          f"3..{small_stop - 1:,}); equal-cost atomic batches: {len(batches)} (primes "
          f"{small_stop:,}..{L_final - 1:,}); {MAX_WORKERS} parallel processes")
    print(f"[*] Shared output buffer: {combined_bytes/1e6:.1f} MB, ONE COPY TOTAL (see "
          f"prime_sieve_v3.py's header for why).")

    # Allocate the SHARED buffer BEFORE creating the ProcessPoolExecutor -- workers fork()
    # after this point and inherit the mapping (see _init_shared_buffer()'s docstring).
    _init_shared_buffer(combined_bytes)
    ctx = multiprocessing.get_context("fork")  # explicit, not relying on the platform default
                                                # -- correctness of the shared-mmap-before-
                                                # fork trick REQUIRES fork(), not spawn/
                                                # forkserver (see prime_sieve_v3.py header)

    errors = 0
    print_interval = max(1, len(jobs) // 30) if jobs else 1

    t_start = time.perf_counter()
    t_last_print = t_start
    with ProcessPoolExecutor(max_workers=MAX_WORKERS, mp_context=ctx) as executor:
        jobs_iter = iter(jobs)
        in_flight = {}

        def _submit_next():
            try:
                fn, args = next(jobs_iter)
            except StopIteration:
                return False
            fut = executor.submit(fn, *args)
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
                progress = done_count / len(jobs) * 100
                print_delta = t_now - t_last_print
                rate = done_count / (t_now - t_start) if (t_now - t_start) > 0 else 0
                remaining = (len(jobs) - done_count) / rate if rate > 0 else float("inf")
                print(f"[+] Progress: {progress:.2f}% ({done_count}/{len(jobs)} jobs) | "
                      f"time: {t_now - t_start:.2f}s (+{print_delta:.2f}s since last print) | "
                      f"ETA ~{remaining:.0f}s" + (f" | ERRORS={errors}" if errors else ""))
                t_last_print = t_now
    t_sieve = time.perf_counter() - t_start

    print(f"\n[*] Batch sieve done in {t_sieve:.2f}s. Unpacking result and writing windows...")
    if errors:
        print(f"[!] WARNING: {errors} jobs returned an engine error -- results INCOMPLETE.")

    # Everything from here to each branch's write_scan_metrics_handoff() call below is
    # timed as ONE "write" phase (unpack bits -> prime offsets -> PGS2 file write).
    # bytes_written sums os.path.getsize() over every window actually
    # written this run (stays 0 in count-only mode, where nothing is written).
    t_write_start = time.perf_counter()
    bytes_written = 0

    odd_bits = np.frombuffer(_shm_mmap, dtype=np.uint8, count=combined_bytes)

    low_floor_segments = _low_floor_segments(base_power, combined_lo, combined_hi)
    if low_floor_segments:
        # base_power < LOW_FLOOR_CUTOFF: this combined range spans several REAL floors at
        # once (see _low_floor_segments' docstring) -- write each complete one under its
        # own 10p{floor}/ folder instead of the single 10p{base_power}/ the normal path
        # below would use, and skip the write loop entirely once done.
        total_primes_found = 0
        floor_counts = []
        for floor, floor_lo, floor_hi in low_floor_segments:
            # Sharded (see window_sharding.py) -- a low floor always writes
            # its one window at offset 0, so it always lands in shard_00000.
            this_floor_folder = os.path.join(BASE_STORAGE_10PN, f"10p{floor}", "source_primes")
            this_shard_folder = window_sharding.shard_dir(this_floor_folder, 0)
            window_path = os.path.join(this_shard_folder, f"PRIME_WINDOW_10p{floor}_off_0.bin")
            generated_at = int(time.time())

            if write_files:
                os.makedirs(this_shard_folder, exist_ok=True)
                offsets = _window_prime_offsets(odd_bits, first_odd, floor_lo, floor_hi)
                count = len(offsets)
                write_prime_window_offsets(window_path, floor_lo, offsets,
                                           generated_at=generated_at)
                bytes_written += os.path.getsize(window_path)
            else:
                count = _window_prime_count(odd_bits, first_odd, floor_lo, floor_hi)
            total_primes_found += count
            floor_counts.append((floor, count))

        del odd_bits  # the mapping cannot close while a NumPy view still exports it
        _shm_mmap.close()

        skipped_floor = low_floor_segments[-1][0] + 1
        print(f"\n[*] Low-floor batch: floor(s) {low_floor_segments[0][0]}-"
              f"{low_floor_segments[-1][0]} written complete, each as its own 10p{{N}} "
              f"window -- floor {skipped_floor} would be cut off by this batch's range, so "
              f"it was skipped (not written partially).")
        for floor, count in floor_counts:
            print(f"    10p{floor}: {count:,} primes")
        t_write = time.perf_counter() - t_write_start
        print(f"\n[*] TOTAL PRIMES FOUND this run: {total_primes_found:,} across "
              f"{len(low_floor_segments)} floor(s)"
              + ("" if write_files else "  (NO FILES WRITTEN -- count-only mode)"))

        write_scan_metrics_handoff(BASE_STORAGE_10PN, L_final, sieving_primes_count,
                                    total_primes_found=total_primes_found,
                                    windows_processed=len(low_floor_segments),
                                    write_files=write_files,
                                    base_gen_seconds=base_gen_seconds, sieve_seconds=t_sieve,
                                    write_seconds=t_write, bytes_written=bytes_written,
                                    numbers_processed=combined_size)
        print("=" * 70)
        return

    # Sharded (see window_sharding.py): no single directory ever holds more
    # than SHARD_SIZE window files, regardless of floor size -- floor_folder itself is
    # therefore never created/listed directly, only its shard_NNNNN subfolders are.
    floor_folder = os.path.join(BASE_STORAGE_10PN, f"10p{base_power}", "source_primes")

    # Per-window unpacking: peak memory for this step is O(window_m), not O(combined_size)
    # (see prime_sieve_v3.py's header), for any window_m.
    total_primes_found = 0
    for wi, (distance, w) in enumerate(windows):
        offset = distance - BASE
        target_tag = f"10p{base_power}_off_{format_offset(offset)}"
        window_index = window_sharding.shard_index_for_offset(offset, window_m)
        shard_folder = window_sharding.shard_dir(floor_folder, window_index)
        window_path = os.path.join(shard_folder, f"PRIME_WINDOW_{target_tag}.bin")
        generated_at = int(time.time())

        if write_files:
            offsets = _window_prime_offsets(odd_bits, first_odd, distance, distance + w)
            total_primes_found += len(offsets)
            os.makedirs(shard_folder, exist_ok=True)
            write_prime_window_offsets(window_path, distance, offsets, generated_at=generated_at)
            bytes_written += os.path.getsize(window_path)
        else:
            total_primes_found += _window_prime_count(odd_bits, first_odd, distance, distance + w)

    del odd_bits  # the mapping cannot close while a NumPy view still exports it
    _shm_mmap.close()
    t_write = time.perf_counter() - t_write_start
    print(f"\n[*] TOTAL PRIMES FOUND this run: {total_primes_found:,} across {N} windows"
          + ("" if write_files else "  (NO FILES WRITTEN -- count-only mode)"))

    write_scan_metrics_handoff(BASE_STORAGE_10PN, L_final, sieving_primes_count,
                                total_primes_found=total_primes_found, windows_processed=N,
                                write_files=write_files,
                                base_gen_seconds=base_gen_seconds, sieve_seconds=t_sieve,
                                write_seconds=t_write, bytes_written=bytes_written,
                                    numbers_processed=combined_size)

    print("=" * 70)


SCAN_METRICS_FILENAME = "last_scan_metrics.json"


def write_scan_metrics_handoff(portal_folder, l_final, sieving_primes_count,
                                total_primes_found=None, windows_processed=None,
                                write_files=None, base_gen_seconds=None, sieve_seconds=None,
                                write_seconds=None, bytes_written=None, numbers_processed=None):
    """Writes the one JSON file orchestrator_v3.py reads back (read_scan_metrics_handoff())
    to log a benchmark_log.csv row without needing to re-derive anything itself, including
    the timing/size fields base_gen_seconds, sieve_seconds, write_seconds and bytes_written.
    Each optional field is included only if not None (e.g. a
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
    if numbers_processed is not None:
        data["numbers_processed"] = numbers_processed
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
    # Optional CLI position 8. Default 10_000_000 when omitted.
    WINDOW_M = int(sys.argv[8]) if len(sys.argv) > 8 else 10 ** 7
    target_idx_list = list(range(target_idx_start, target_idx_stop + 1))

    # PRIMEATLAS_USE_KNOWN_PI_SEED: same env-var mechanism as CONSTELLATION_PORTAL_DIR above
    # (not a CLI position) -- this process is normally launched as a subprocess three hops
    # down from the GUI (Generation tab -> orchestrator_loop_v2.py -> orchestrator_v3.py's
    # run_batch() -> here), and every hop in that chain launches its child with the default
    # subprocess env (no env= override anywhere in that chain), so a value set once in the
    # GUI's own build_wsl_logged_command() env_prefix reaches all the way down here for free,
    # with no new positional CLI argument threaded through three separate scripts' argv
    # parsing. See count_sieving_primes_cached()'s own docstring for what this flag does.
    USE_KNOWN_PI_SEED = bool(int(os.environ.get("PRIMEATLAS_USE_KNOWN_PI_SEED", "0")))
    # PRIMEATLAS_V5_SEGMENT_KB: segmented-path segment size, same env-var route.
    SEGMENT_KB = work_plan_v5.segment_kb_from_env(os.environ)

    print("Start time:", datetime.datetime.now().strftime("%H:%M:%S"))
    main_batch_scanner(base_exponent, target_idx_list, WINDOW_M, write_files=WRITE_FILES,
                        compute_sieving_primes_count=COMPUTE_SIEVING_PRIMES_COUNT,
                        use_known_pi_seed=USE_KNOWN_PI_SEED, segment_kb=SEGMENT_KB)
