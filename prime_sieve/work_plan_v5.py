"""Work plan of one v5 sieve run: how the odd-only buffer and the sieving primes are split
into worker jobs.

Two job kinds cover the run together:
  - segmented slices: a word-aligned bit range of the buffer, sieved in cache-sized segments
    by every odd prime below small_prime_stop() (sieve_odd_segmented() in
    prime_sieve_engine_v5.c);
  - atomic batches: a contiguous range of the remaining sieving primes
    [small_prime_stop(), L_final), each prime striding the whole buffer
    (sieve_odd_bits_atomic()), split by the Mertens/li cost model below.

The segment size is the perf knob of the segmented path (environment variable
PRIMEATLAS_V5_SEGMENT_KB; the default is arbitrary, sized for a per-core L2 cache shared by
two SMT threads).
"""
import math

SEGMENT_KB_ENV = "PRIMEATLAS_V5_SEGMENT_KB"
DEFAULT_SEGMENT_KB = 128


def segment_kb_from_env(environ):
    """Segment size in KiB from `environ` (a mapping), DEFAULT_SEGMENT_KB when unset.
    Raises ValueError unless the value is a positive integer."""
    raw = environ.get(SEGMENT_KB_ENV)
    if raw is None:
        return DEFAULT_SEGMENT_KB
    try:
        kb = int(raw)
    except ValueError:
        raise ValueError(f"{SEGMENT_KB_ENV} must be a positive integer (KiB), got {raw!r}")
    if kb < 1:
        raise ValueError(f"{SEGMENT_KB_ENV} must be a positive integer (KiB), got {raw!r}")
    return kb


def segment_bits(segment_kb):
    return segment_kb * 1024 * 8


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
