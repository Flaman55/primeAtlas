"""Work plan of one pt1 run (partial sieve + primality test, prime_sieve_pt1.py).

pt1 sieves the odd numbers of a window only by the primes 3..B and tests every survivor:
Miller-Rabin to the 13 bases 2..41 for a D window (wholly below
storage_kinds.MR_DET_BOUND, where that is a proof), BPSW for a P window. Its work per number
does not depend on the floor beyond the test's word size, so it needs no run-sized buffer:
windows are processed in slabs of consecutive windows of the same kind, each slab one
odd-only bitmap.

Perf knobs (environment variables; the defaults are arbitrary):
  - PRIMEATLAS_PT1_B: the sieve limit B. 0 or unset = floor(N^(1/4)) for the top N of the
    run: the primes up to N^(1/4) do the dense part of the sieving, larger ones remove few
    numbers each. B is clamped to isqrt of the run's lowest number, so the sieve never
    removes a prime of the window itself, and must stay below 2^32;
  - PRIMEATLAS_PT1_CHUNK_KB: odd numbers per thread task, in KiB of the per-thread flag
    array (one byte per odd number); every chunk computes one phase per sieving prime.
"""
import math

B_ENV = "PRIMEATLAS_PT1_B"
CHUNK_KB_ENV = "PRIMEATLAS_PT1_CHUNK_KB"
DEFAULT_CHUNK_KB = 4096
MAX_B = 2 ** 32 - 1
MIN_FLOOR = 7    # floors 0..6 take the scanners' low-floor single-window path
MAX_FLOOR = 37   # Montgomery arithmetic with R = 2^128 needs n < 2^127; 10^38 < 2^127
CHUNKS_PER_THREAD_PER_SLAB = 4


def b_from_env(environ, name=B_ENV):
    """B from `environ` (a mapping) under `name`: 0 (= default_b()) when unset or blank.
    Raises ValueError unless the value is an integer in 0..MAX_B."""
    raw = environ.get(name)
    if raw is None or str(raw).strip() == "":
        return 0
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name} must be an integer in 0..{MAX_B}, got {raw!r}")
    if not 0 <= value <= MAX_B:
        raise ValueError(f"{name} must be an integer in 0..{MAX_B}, got {raw!r}")
    return value


def chunk_kb_from_env(environ, name=CHUNK_KB_ENV):
    """Chunk size in KiB from `environ` under `name`, DEFAULT_CHUNK_KB when unset. Raises
    ValueError unless the value is a positive integer."""
    raw = environ.get(name)
    if raw is None:
        return DEFAULT_CHUNK_KB
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        raise ValueError(f"{name} must be a positive integer (KiB), got {raw!r}")
    return value


def default_b(top):
    """floor(top^(1/4))."""
    return math.isqrt(math.isqrt(top))


def effective_b(requested, run_lo, run_hi):
    """The B a run uses: `requested`, or default_b(run_hi - 1) for 0, clamped to
    isqrt(run_lo) and MAX_B."""
    b = requested if requested else default_b(run_hi - 1)
    return min(b, math.isqrt(run_lo), MAX_B)


def chunk_odd(chunk_kb):
    return chunk_kb * 1024


def plan_slabs(windows, kinds, slab_numbers):
    """Groups `windows` ([(lo, hi)], adjacent, ascending) into slabs: runs of consecutive
    windows of the same kind (kinds[i] for windows[i]) spanning at most slab_numbers
    numbers, but always at least one window. Returns [(kind, [window indices])]."""
    slabs = []
    for i, (lo, hi) in enumerate(windows):
        if slabs:
            kind, idxs = slabs[-1]
            if kind == kinds[i] and hi - windows[idxs[0]][0] <= slab_numbers:
                idxs.append(i)
                continue
        slabs.append((kinds[i], [i]))
    return slabs


def slab_numbers(n_threads, chunk_kb):
    """Numbers per slab: enough chunks for every thread to claim several."""
    return 2 * chunk_odd(chunk_kb) * max(1, n_threads) * CHUNKS_PER_THREAD_PER_SLAB
