"""Work plan of one v5 sieve run: how the odd-only buffer and the sieving primes are split
into worker jobs.

Two job kinds cover the run together:
  - segmented slices: a word-aligned bit range of the buffer, sieved in cache-sized segments
    by every odd prime below small_prime_stop() (sieve_odd_segmented() in
    prime_sieve_engine_v5.c);
  - bucketed pieces: contiguous ranges of the remaining sieving primes
    [small_prime_stop(), L_final), split by the Mertens/li cost model below and marked by one
    multi-threaded sieve_odd_bucketed() call, which buckets the hits by buffer region.

Perf knobs (environment variables; the defaults are arbitrary, picked by measurement):
  - PRIMEATLAS_V5_SEGMENT_KB: segment size, sized for a per-core L2 cache shared by two SMT
    threads;
  - PRIMEATLAS_V5_REGION_KB: bucket region size. Larger regions mean fewer buckets per
    thread, so the scatter's open bucket lines stay in cache; smaller regions keep the
    apply step's ORs inside L2/L3;
  - PRIMEATLAS_V5_BUCKET_MB: bucket memory of all threads together; more memory means more
    hits per region per round, so fewer rounds.
"""
import math

SEGMENT_KB_ENV = "PRIMEATLAS_V5_SEGMENT_KB"
DEFAULT_SEGMENT_KB = 128
REGION_KB_ENV = "PRIMEATLAS_V5_REGION_KB"
DEFAULT_REGION_KB = 1024
BUCKET_MB_ENV = "PRIMEATLAS_V5_BUCKET_MB"
DEFAULT_BUCKET_MB = 1024
PIECES_PER_THREAD = 16   # claimed one at a time: the last pieces even out thread speeds


def _positive_int_from_env(environ, name, default, unit):
    raw = environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be a positive integer ({unit}), got {raw!r}")
    if value < 1:
        raise ValueError(f"{name} must be a positive integer ({unit}), got {raw!r}")
    return value


def segment_kb_from_env(environ):
    """Segment size in KiB from `environ` (a mapping), DEFAULT_SEGMENT_KB when unset.
    Raises ValueError unless the value is a positive integer."""
    return _positive_int_from_env(environ, SEGMENT_KB_ENV, DEFAULT_SEGMENT_KB, "KiB")


def region_kb_from_env(environ):
    """Bucket region size in KiB from `environ` (a mapping), DEFAULT_REGION_KB when unset.
    Raises ValueError unless the value is a positive integer."""
    return _positive_int_from_env(environ, REGION_KB_ENV, DEFAULT_REGION_KB, "KiB")


def bucket_mb_from_env(environ):
    """Bucket memory in MiB from `environ` (a mapping), DEFAULT_BUCKET_MB when unset.
    Raises ValueError unless the value is a positive integer."""
    return _positive_int_from_env(environ, BUCKET_MB_ENV, DEFAULT_BUCKET_MB, "MiB")


def segment_bits(segment_kb):
    return segment_kb * 1024 * 8


def region_bits(region_kb):
    return region_kb * 1024 * 8


def small_prime_stop(seg_bits, L_final):
    """End (exclusive) of the segmented prime range [3, stop): primes striding less than one
    segment hit every segment, so they are cheaper with a stored next offset than as a
    full-buffer stride. Never above L_final, never below 3."""
    return max(3, min(seg_bits, L_final))


def plan_slices(n_bits, n_slices):
    """Splits bits [0, n_bits) into at most n_slices contiguous (bit_lo, bit_hi) ranges of
    near-equal size; every bit_lo is a multiple of 64, so each slice owns whole 64-bit words
    except where the last one ends at n_bits."""
    if n_bits <= 0:
        return []
    n_words = (n_bits + 63) // 64
    n = max(1, min(n_slices, n_words))
    bounds = [(n_words * i // n) * 64 for i in range(n)] + [n_bits]
    return [(lo, hi) for lo, hi in zip(bounds[:-1], bounds[1:]) if lo < hi]


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


def build_equal_cost_batches(L_final, combined_size, n_batches, lo=2):
    """Splits the sieving-prime range [lo, L_final) into `n_batches` contiguous batches of
    roughly equal marking cost (Mertens-based estimate, see _cumulative_cost()), so every
    worker gets a similar amount of work. Empty when lo >= L_final (no prime is left for
    the atomic path)."""
    if lo >= L_final and lo > 2:
        return []
    threshold = min(combined_size, L_final)
    n = max(1, n_batches)

    def cost_upto(x):
        return _cumulative_cost(x, threshold, combined_size)

    base = cost_upto(lo) if lo > 2 else 0.0
    total = cost_upto(L_final) - base
    if total <= 0 or L_final <= 2:
        return [[(lo, max(lo + 1, L_final))]]

    boundaries = [lo]
    left = lo
    for i in range(1, n):
        target = total * i / n
        a, b = left, L_final
        while a < b:
            mid = (a + b) // 2
            if cost_upto(mid) - base < target:
                a = mid + 1
            else:
                b = mid
        boundaries.append(a)
        left = a
    boundaries.append(L_final)

    boundaries = sorted(set(g for g in boundaries if lo <= g <= L_final))
    batches = [[(a, b)] for a, b in zip(boundaries[:-1], boundaries[1:]) if a < b]
    return batches or [[(lo, L_final)]]


def plan_pieces(L_final, combined_size, lo, n_threads):
    """Ascending, contiguous (piece_lo, piece_hi) ranges covering the bucketed primes
    [lo, L_final), n_threads * PIECES_PER_THREAD of them at most, of equal estimated cost.
    sieve_odd_bucketed() threads claim them in order. Empty when lo >= L_final."""
    if lo >= L_final:
        return []
    batches = build_equal_cost_batches(L_final, combined_size,
                                       max(1, n_threads) * PIECES_PER_THREAD, lo=lo)
    return [r for batch in batches for r in batch]
