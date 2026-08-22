import ctypes
import datetime
import numpy as np
import time
import os
import math
import concurrent.futures
from concurrent.futures import ProcessPoolExecutor


MAX_WORKERS = 24
ZONE_A_SEGMENTS = 200     # geometric chunks for sieving primes <= combined_size (expensive marking loops)
ZONE_B_SEGMENTS = 96      # equal-width chunks for sieving primes > combined_size (cheap single marks)
BATCHES_PER_WORKER = 2    # how many batches (bundles of segments) per worker -- balance vs IPC overhead

# ==========================================================================================
# prime_sieve_v1.py
#
# Prime sieve scanner: generates sieving primes on the fly via primesieve and marks
# composite positions across windows of the number line, writing the surviving (prime)
# candidates to disk in PGS2 binary format (gap+varint-encoded prime lists -- see
# write_prime_window()/read_prime_window() below for the exact layout and rationale).
#
# Segment-cost estimation (_cost_zone_a) uses Mertens' second theorem to approximate the
# marking cost of sieving primes in (a, b] as combined_size * (ln ln b - ln ln a). The
# domain floor for the inner log-log helper must be clamped at x=2.0 (the smallest real
# prime), not higher: clamping at x=3.0 instead would make mert(2) == mert(3), silently
# erasing prime 2's marking cost from the estimate. Since sieving with p=2 alone marks HALF
# of combined_size -- by far the single most expensive segment -- underestimating its cost
# lets the LPT packer bury it inside an otherwise "light" batch instead of giving it its own
# slot, turning that batch into a hidden straggler (visible as an "Occupied: 0/N" stall in
# the first few progress prints of a run, while correctly-estimated batches finish around
# it). mert(2) itself is a normal finite value (ln ln 2 =~ -0.367); no clamping is needed
# above x=2.
# ==========================================================================================

_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prime_sieve_engine_v1.so")
_lib = None  # lazily loaded, SEPARATELY in each worker process

_POPCOUNT_TABLE = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint32)


def _load_lib():
    global _lib
    if _lib is None:
        if not os.path.exists(_LIB_PATH):
            raise RuntimeError(
                f"Missing {_LIB_PATH} -- build it first: gcc -O3 -shared -fPIC "
                f"prime_sieve_engine_v1.c -o prime_sieve_engine_v1.so -lprimesieve -lstdc++ -lm")
        lib = ctypes.CDLL(_LIB_PATH)
        lib.generate_and_sieve_segment_bits.argtypes = [
            ctypes.c_uint64,                  # start
            ctypes.c_uint64,                  # stop
            ctypes.c_uint64,                  # distance_hi
            ctypes.c_uint64,                  # distance_lo
            ctypes.c_uint64,                  # window_m
            ctypes.POINTER(ctypes.c_ubyte),   # out_dense_bits
        ]
        lib.generate_and_sieve_segment_bits.restype = ctypes.c_int
        lib.count_sieving_primes.argtypes = [ctypes.c_uint64]
        lib.count_sieving_primes.restype = ctypes.c_uint64
        _lib = lib
    return _lib


def count_sieving_primes(limit):
    """Benchmark metric: how many distinct sieving primes p in [2, limit] were used to sieve
    the combined window (limit = L_final, see main_batch_scanner()). Delegates to
    libprimesieve's own fast COUNTING algorithm via the C wrapper (count_sieving_primes() in
    prime_sieve_engine_v1.c) -- negligible cost, no need to reuse/track values from the actual
    sieve pass (which never held a running total anyway; primesieve_iterator just streams)."""
    lib = _load_lib()
    return int(lib.count_sieving_primes(limit))


# Result buffer, BIT-PACKED -- PER WORKER PROCESS, reused across calls.
_bit_buffer = None
_bit_buffer_cap = 0


def _get_buffer(n_bytes):
    global _bit_buffer, _bit_buffer_cap
    if _bit_buffer is None or _bit_buffer_cap < n_bytes:
        _bit_buffer = np.zeros(n_bytes, dtype=np.uint8)
        _bit_buffer_cap = n_bytes
    else:
        _bit_buffer[:n_bytes] = 0
    return _bit_buffer


def format_offset(n):
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
# PGS1 -- "Prime Gap Stream v1": binary, gap-delta + LEB128-varint prime storage format.
#
# WHY this format:
#   - Storing a window's primes as gaps between consecutive primes instead of full values
#     is the standard trick for this exact problem (see e.g. the "prime gap" literature and
#     Tab Atkins' "Compactly Encoding All Primes via Gaps" write-up) -- gaps stay tiny (avg
#     ~40 at 10^18, ~170 at 10^75) while the primes themselves are 20-76+ decimal digits.
#   - Encoding each gap as a LEB128-style unsigned varint (7 data bits/byte, high bit =
#     continuation flag) is the same technique used for delta-encoded integer lists in
#     search-engine postings lists, Protocol Buffers, and SQLite -- well-established,
#     unbounded (no arbitrary escape-value cliff), and trivial to implement correctly.
#   - The one worked academic precedent for "the" canonical prime-gap file format --
#     primegap-list-project.github.io (successor to Thomas Nicely's gap tables, the same
#     project family behind pzktupel.de-style record-keeping) -- uses a SQL/text schema,
#     but that project stores a SPARSE list of record-setting gaps with rich metadata
#     (discoverer, certification, merit...), not a DENSE encoding of every prime in a
#     window for fast k-tuple scanning. Different problem, so its format doesn't transfer
#     directly -- gap+varint is the right tool for OUR problem (bulk dense storage,
#     optimized for sequential reconstruction + numpy vectorized matching downstream).
#
# Layout (all multi-byte integer HEADER fields are big-endian):
#   magic        4 bytes   b"PGS2"
#   base_len     1 byte    length in bytes of the base-prime big-endian encoding (0 if
#                          the window contains zero primes)
#   base_prime   base_len bytes   the FIRST prime in the window, as a big-endian unsigned
#                          integer (arbitrary precision -- handles any floor depth)
#   count        4 bytes   uint32, total number of primes in the window (including the
#                          base prime)
#   generated_at 4 bytes   uint32, unix epoch seconds (UTC) when this window was written --
#                          lets every result file self-document when it was generated
#                          (visible via read_prime_window_header()), useful both as a quick
#                          sanity check and as raw material for tracking how generation cost
#                          grows with floor depth over time.
#   gaps         (count-1) LEB128 unsigned varints, each = primes[i] - primes[i-1]
#
# Reconstructing absolute values is a single cumulative sum from base_prime; reconstructing
# window-relative offsets is `absolute - window_start`, computed once when loading, not
# stored redundantly per entry.
#
# The magic bytes identify the format version so a reader never silently misinterprets an
# older layout (e.g. one without the generated_at field) as the current one.
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
    """NEW in PGS2 support: reads ONLY the header (base prime, count, generation
    timestamp) WITHOUT decoding the gap stream -- a fast metadata peek for tooling
    (benchmarking, portal/website listing pages, sanity checks) that doesn't need the
    full prime list. Returns a dict: base_prime, count, generated_at (unix seconds),
    generated_at_iso (human-readable UTC string)."""
    with open(path, "rb") as f:
        header = f.read(4 + 1 + 255 + 4 + 4)  # generous upper bound, base_len <= 255
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
    pos += 4  # generated_at (unix timestamp) -- not needed for prime reconstruction,
              # see read_prime_window_header() to retrieve it
    primes = [base]
    prev = base
    for _ in range(count - 1):
        gap, pos = decode_varint(data, pos)
        prev += gap
        primes.append(prev)
    return primes


def read_prime_window_head(path, threshold):
    """Reads primes from `path` in order, stopping as soon as a value EXCEEDS `threshold`
    (a value equal to threshold IS included). Used to cheaply "peek" a handful of entries
    into the next window during streaming k-tuple pattern matching, where only a small,
    bounded number of values is ever needed -- decoding the whole file just for that would
    be wasteful for large windows."""
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
    """Appends new values to a growing cumulative hit file (e.g. per-(k,variant) constellation
    hits, which grow by a handful of entries at a time across many runs) without re-decoding
    and re-writing the whole file on every call. Re-encoding via write_prime_window() on every
    append would cost O(existing count) each time, making a run that accumulates hits across
    many windows O(final size^2) overall. This function instead patches the count/generated_at
    header fields in place via seek+overwrite and APPENDS freshly gap-encoded bytes for the
    new values at the end of the file -- no rewrite of the existing gap stream.

    `known_last_value`, if given, is trusted as the file's current last stored value instead
    of decoding the whole existing gap stream to find it -- callers that make many appends to
    the SAME growing file within one run should track this themselves and pass it in, since
    doing so makes each append O(len(new_sorted_values)) regardless of how large the file has
    already grown, rather than O(current file size) if the last value has to be rediscovered
    by decoding on every call.

    `new_sorted_values` must be sorted ascending and strictly greater than the file's
    current last value (true by construction here, since windows are always processed in
    increasing order). Creates the file fresh (via write_prime_window) if it doesn't exist
    yet, or exists but is empty (count=0)."""
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
        f.write(int(generated_at).to_bytes(4, "big"))  # generated_at = last-modified time
        f.seek(0, os.SEEK_END)
        prev = known_last_value
        for v in new_sorted_values:
            f.write(encode_varint(v - prev))
            prev = v


# ------------------------------------------------------------------------------------------
# Segment-cost estimation -- analytical (Mertens' theorems / prime density formulas),
# WITHOUT calling primesieve. Only used as WEIGHT for LPT packing, does not need to be
# exact -- just needs to correctly reflect PROPORTIONS between segments.
# ------------------------------------------------------------------------------------------

def _cost_zone_a(a, b, combined_size):
    """Cost of the marking loop for sieving primes p in (a,b]: sum_{a<p<=b} combined_size/p
    =~ combined_size*(ln ln b - ln ln a) (Mertens' second theorem, the constant cancels in
    the difference). Parameter is combined_size (the actual size of the buffer being
    marked), NOT window_m (a single window's size) -- using window_m here previously
    underestimated zone-A cost by ~combined_size/window_m times."""
    def mert(x):
        x = max(x, 2.0)   # smallest real prime is 2 -- ln ln 2 =~ -0.367 is a normal,
        return math.log(math.log(x))   # finite value, no further clamping needed above it
    return combined_size * max(mert(b) - mert(a), 1e-6)


def _cost_zone_b(a, b):
    """Cost of single marks for sieving primes p in (a,b]: ~ pi(b)-pi(a) =~ b/ln(b) - a/ln(a)."""
    def li_approx(x):
        x = max(x, 3.0)
        return x / math.log(x)
    return max(li_approx(b) - li_approx(a), 1.0)


def _build_segments(L_final, combined_size, window_m):
    """Returns a list of (start, stop, estimated_cost) covering the whole axis [2, L_final]."""
    threshold = min(combined_size, L_final)
    segments = []

    if threshold > 2:
        n = max(1, ZONE_A_SEGMENTS)
        log2, logp = math.log(2), math.log(max(threshold, 3))
        bounds = [2]
        for i in range(1, n):
            bounds.append(int(round(math.exp(log2 + (logp - log2) * i / n))))
        bounds.append(threshold)
        bounds = sorted(set(g for g in bounds if 2 <= g <= threshold))
        for a, b in zip(bounds[:-1], bounds[1:]):
            if a >= b:
                continue
            segments.append((a, b, _cost_zone_a(a, b, combined_size)))

    if L_final > threshold:
        n = max(1, ZONE_B_SEGMENTS)
        width = max(1, (L_final - threshold) // n)
        a = threshold
        while a < L_final:
            b = min(a + width, L_final)
            segments.append((a, b, _cost_zone_b(a, b)))
            a = b

    return segments


def _pack_into_batches(segments, n_batches):
    """LPT (Longest Processing Time first): sorts segments descending by cost, assigns each
    to the CURRENTLY least-loaded batch. Guarantees <= 4/3 of optimal makespan."""
    sorted_segments = sorted(segments, key=lambda s: s[2], reverse=True)
    batches = [[] for _ in range(n_batches)]
    load = [0.0] * n_batches
    for (a, b, cost) in sorted_segments:
        idx = min(range(n_batches), key=lambda i: load[i])
        batches[idx].append((a, b))
        load[idx] += cost
    return [b for b in batches if b]


def process_batch(start_stop_list, distance, window_m, n_bytes):
    """Processes a LIST of segments IN ONE PROCESS, accumulating marks into ONE buffer
    (the C function only SETS bits, never clears them -- repeated calls naturally OR
    together). Returns ONE buffer copy for the WHOLE batch -- this is the fix for IPC
    overhead from fine-grained zone-A segmentation."""
    lib = _load_lib()
    buf = _get_buffer(n_bytes)
    out_ptr = buf.ctypes.data_as(ctypes.POINTER(ctypes.c_ubyte))
    distance_hi = distance >> 64
    distance_lo = distance & 0xFFFFFFFFFFFFFFFF

    had_error = False
    for start, stop in start_stop_list:
        code = lib.generate_and_sieve_segment_bits(start, stop, distance_hi, distance_lo,
                                                     window_m, out_ptr)
        if code != 0:
            had_error = True

    if had_error:
        return (None, True)
    return (buf.copy(), False)


def main_batch_scanner(base_power, target_idx_list, window_m, write_files=True):
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
    print(f"[*] BATCH v1 (primesieve, bit buffer, LPT balancing, PGS1 binary output): "
          f"{N} windows (target_idx {target_idx_list[0]}..{target_idx_list[-1]}), "
          f"level 10^{base_power}")
    print(f"[*] Combined range: [{combined_lo:,}, {combined_hi:,})  "
          f"size={combined_size:,}  ({combined_bytes/1e6:.1f} MB bit-packed)")
    if not write_files:
        print(f"[*] WRITE_FILES=False -- no PGS2 files will be written this run; only "
              f"aggregate prime counts will be reported.")
    print("=" * 70)

    L_final = math.isqrt(combined_hi) + 1
    print(f"[*] L_final (sieving-prime base limit): {L_final:,}")
    sieving_primes_count = count_sieving_primes(L_final)
    print(f"[*] Active sieving primes used (pi(L_final)): {sieving_primes_count:,}")

    segments = _build_segments(L_final, combined_size, window_m)
    n_batches = max(1, MAX_WORKERS * BATCHES_PER_WORKER)
    batches = _pack_into_batches(segments, n_batches)

    peak_ram_estimate_mb = combined_bytes / 1e6 * MAX_WORKERS
    print(f"[*] Segments (zone A geom. + zone B equal-width): {len(segments)} "
          f"-> packed LPT into {len(batches)} batches ({MAX_WORKERS} parallel processes)")
    print(f"[*] Estimated peak RAM for worker buffers: ~{peak_ram_estimate_mb/1000:.2f} GB "
          f"({MAX_WORKERS} processes x {combined_bytes/1e6:.1f} MB) + main buffer "
          f"{combined_bytes/1e6:.1f} MB")

    window_occupied_bits = np.zeros(combined_bytes, dtype=np.uint8)
    errors = 0

    print_interval = max(1, len(batches) // 30) if batches else 1

    t_start = time.perf_counter()
    t_last_print = t_start
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
        batches_iter = iter(batches)
        in_flight = {}

        def _submit_next():
            try:
                batch = next(batches_iter)
            except StopIteration:
                return False
            fut = executor.submit(process_batch, batch, combined_lo, combined_size,
                                   combined_bytes)
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
                batch_bits, had_error = fut.result()
                if had_error:
                    errors += 1
                else:
                    np.bitwise_or(window_occupied_bits, batch_bits, out=window_occupied_bits)
                del batch_bits
                done_count += 1
                _submit_next()

            if done_count % print_interval == 0 or not in_flight:
                t_now = time.perf_counter()
                progress = done_count / len(batches) * 100
                occupied = int(_POPCOUNT_TABLE[window_occupied_bits].sum())
                print_delta = t_now - t_last_print
                rate = done_count / (t_now - t_start) if (t_now - t_start) > 0 else 0
                remaining = (len(batches) - done_count) / rate if rate > 0 else float("inf")
                print(f"[+] Progress: {progress:.2f}% ({done_count}/{len(batches)} batches) | "
                      f"Occupied: {occupied}/{combined_size:,} | "
                      f"time: {t_now - t_start:.2f}s (+{print_delta:.2f}s since last print) | "
                      f"ETA ~{remaining:.0f}s" + (f" | ERRORS={errors}" if errors else ""))
                t_last_print = t_now
    t_sieve = time.perf_counter() - t_start

    print(f"\n[*] Batch sieve done in {t_sieve:.2f}s. Unpacking result and writing windows...")
    if errors:
        print(f"[!] WARNING: {errors} batches returned a primesieve error -- results INCOMPLETE.")

    window_occupied = np.unpackbits(window_occupied_bits, count=combined_size,
                                     bitorder='little').astype(bool)

    # PGS2 windows are written directly under BASE_STORAGE_10PN/10p{N}/source_primes/,
    # matching the CONSTELLATION_PORTAL folder layout (floor -> source_primes / constellations).
    # write_files=False (write-toggle feature): candidates are still computed in full (needed
    # to know the count), but write_prime_window() is skipped -- no PGS2 files land on disk,
    # only the aggregate count is kept (total_primes_found below), handed back to the caller
    # via write_scan_metrics_handoff() since there are no files left for it to read counts
    # back from otherwise.
    floor_folder = os.path.join(BASE_STORAGE_10PN, f"10p{base_power}", "source_primes")
    if write_files:
        os.makedirs(floor_folder, exist_ok=True)

    total_primes_found = 0
    for wi, (distance, w) in enumerate(windows):
        lo_rel = distance - combined_lo
        hi_rel = lo_rel + w
        segment = window_occupied[lo_rel:hi_rel]

        offset = distance - BASE
        target_tag = f"10p{base_power}_off_{format_offset(offset)}"
        window_path = os.path.join(floor_folder, f"PRIME_WINDOW_{target_tag}.bin")
        generated_at = int(time.time())

        if write_files:
            # Need the actual candidate VALUES to write to disk -- builds the full Python
            # list (per-candidate big-int arithmetic + conversion).
            free_locally = np.nonzero(~segment)[0]
            candidates = [distance + int(k) for k in free_locally if (distance + int(k)) > 1]
            total_primes_found += len(candidates)
            write_prime_window(window_path, candidates, generated_at=generated_at)
            # No per-window print here -- it would be redundant once run via
            # orchestrator_loop_v2.py, which already reports the true written range from disk
            # state before/after the session. The batch-level "[+] Progress: ..." prints
            # (above) and the final per-run summary still give full liveness/result visibility.
        else:
            # Count-only mode: skip building the candidate VALUE list entirely -- at these
            # window sizes (10^7) and depths, that list is ~300k+ Python big-ints per window,
            # 500x per run, purely to throw away everything but its length. A vectorized
            # count of unmarked positions (numpy, no per-candidate object/bignum churn) gets
            # the same total essentially instantly instead.
            count = int(np.count_nonzero(~segment))
            if distance == 1 and w > 0 and not segment[0]:
                # Edge case: the write_files=True branch excludes candidate value 1 (not
                # prime) via its "> 1" filter -- only reachable at base_power=0, never at the
                # floor depths this project actually runs, but kept exact rather than
                # silently approximate.
                count -= 1
            total_primes_found += count
            # No per-window print here (unlike the write_files=True branch above, which logs
            # one line per file actually written) -- pure console-I/O overhead with no disk
            # action behind it, confirmed measurably slowing down real concurrent-instance
            # runs (hundreds of these lines interleaving from multiple processes on the same
            # terminal). The batch-level "[+] Progress: ..." prints (from the sieve itself,
            # above) and the "[*] TOTAL PRIMES FOUND" line below still give full liveness/
            # result visibility.

    print(f"\n[*] TOTAL PRIMES FOUND this run: {total_primes_found:,} across {N} windows"
          + ("" if write_files else "  (NO FILES WRITTEN -- count-only mode)"))

    write_scan_metrics_handoff(BASE_STORAGE_10PN, L_final, sieving_primes_count,
                                total_primes_found=total_primes_found, windows_processed=N,
                                write_files=write_files)

    print("=" * 70)


SCAN_METRICS_FILENAME = "last_scan_metrics.json"


def write_scan_metrics_handoff(portal_folder, l_final, sieving_primes_count,
                                total_primes_found=None, windows_processed=None,
                                write_files=None):
    """Hands a couple of batch-level metrics back to whatever launched this scanner
    subprocess (orchestrator_v1.py) -- there's no other channel for this: orchestrator
    deliberately does NOT capture this process's stdout (subprocess.run(cmd) with no
    capture_output=True), so progress prints stream straight to the console live instead of
    being buffered/hidden until the whole batch finishes. A small JSON file at a fixed,
    well-known path is a simple alternative that doesn't disturb that.

    OVERWRITTEN on every call (once per batch, i.e. usually once per orchestrator run -- see
    BATCH_SIZE in orchestrator_v1.py). If an orchestrator run does span multiple batches, the
    LAST batch's L_final is always the largest (windows are processed in increasing order),
    so "whatever's in the file when the orchestrator's loop finishes" is exactly the value
    worth recording for that run.

    total_primes_found/windows_processed/write_files are NEW fields (write-toggle feature):
    total_primes_found is the sum of len(candidates) across every window this run processed,
    computed in-memory BEFORE the (possibly skipped) write_prime_window() call -- so it's
    available even when write_files=False and there are no PGS2 files on disk to read counts
    back from. The orchestrator uses these instead of scanning source_primes/ for headers
    when it's running in no-write mode (see print_benchmark_summary() in orchestrator_v1.py)."""
    import json
    path = os.path.join(portal_folder, SCAN_METRICS_FILENAME)
    data = {"l_final": l_final, "sieving_primes_count": sieving_primes_count}
    if total_primes_found is not None:
        data["total_primes_found"] = total_primes_found
    if windows_processed is not None:
        data["windows_processed"] = windows_processed
    if write_files is not None:
        data["write_files"] = write_files
    try:
        os.makedirs(portal_folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError as e:
        print(f"[!] WARNING: could not write scan metrics handoff ({e})")


if __name__ == "__main__":
    import sys

    print("=" * 70)
    print("[*] PRIME SIEVE -- v1 (primesieve, LPT + geometric zone A, PGS1 binary output)")
    print("=" * 70)

    if os.name == "nt":
        BASE_STORAGE_10PN = os.environ.get("CONSTELLATION_PORTAL_DIR", r"C:\CONSTELLATION_PORTAL")
    else:
        BASE_STORAGE_10PN = os.environ.get("CONSTELLATION_PORTAL_DIR", "/mnt/c/CONSTELLATION_PORTAL")
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

    # WRITE_FILES (write-toggle feature): position 6, optional, default True (matches
    # existing behavior exactly when omitted). 0 = count-only mode, no PGS2 files written --
    # see main_batch_scanner()'s write_files param and write_scan_metrics_handoff() for how
    # the aggregate count still gets reported/handed back without any files on disk.
    WRITE_FILES = True
    if len(sys.argv) > 6:
        WRITE_FILES = bool(int(sys.argv[6]))

    WINDOW_M = 10 ** 7
    target_idx_list = list(range(target_idx_start, target_idx_stop + 1))

    print("Start time:", datetime.datetime.now().strftime("%H:%M:%S"))
    main_batch_scanner(base_exponent, target_idx_list, WINDOW_M, write_files=WRITE_FILES)
