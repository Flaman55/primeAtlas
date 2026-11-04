"""Work plan of one v6 sieve run: the job split of work_plan_v5.py on the wheel-30 buffer.

Slices and bucketed pieces are planned by v5's planners (plan_slices(), plan_pieces(), the
Mertens/li cost model); slices are bit ranges of the wheel buffer, 30 numbers per 8 bits.
What differs is where the segmented primes end (small_prime_stop()) and the perf knobs,
v6's own (their best values need not match v5's):
  - PRIMEATLAS_V6_SEGMENT_KB: segment size;
  - PRIMEATLAS_V6_REGION_KB: bucket region size;
  - PRIMEATLAS_V6_BUCKET_MB: bucket memory of all threads together (run_budget.py lowers it
    when RAM is short);
  - PRIMEATLAS_V6_PIECES_PER_THREAD: bucketed prime pieces per thread;
  - PRIMEATLAS_V6_WRITE_THREADS: threads of the write phase (wheel30_writer.py).
The defaults are arbitrary, picked by measurement (floor 25, 3.75e11 numbers per run):
segments of 1024-2048 KiB, regions of 1024-2048 KiB within 4 % of each other, 4096 KiB
segments +20 %, 4096 MiB of buckets +4 % against 8192 MiB. Write threads: picked by
measurement on 1,000 windows at floor 19 written to a /mnt drive (1 thread 7.6 s, 4-8
threads 2.3 s, more no faster).
"""
from work_plan_v5 import (_positive_int_from_env, plan_pieces, plan_slices,  # noqa: F401
                          region_bits, segment_bits)

SEGMENT_KB_ENV = "PRIMEATLAS_V6_SEGMENT_KB"
DEFAULT_SEGMENT_KB = 2048
REGION_KB_ENV = "PRIMEATLAS_V6_REGION_KB"
DEFAULT_REGION_KB = 1024
BUCKET_MB_ENV = "PRIMEATLAS_V6_BUCKET_MB"
DEFAULT_BUCKET_MB = 8192
PIECES_PER_THREAD_ENV = "PRIMEATLAS_V6_PIECES_PER_THREAD"
DEFAULT_PIECES_PER_THREAD = 16
WRITE_THREADS_ENV = "PRIMEATLAS_V6_WRITE_THREADS"
DEFAULT_WRITE_THREADS = 8
NUMBERS_PER_BYTE = 30


def segment_kb_from_env(environ):
    return _positive_int_from_env(environ, SEGMENT_KB_ENV, DEFAULT_SEGMENT_KB, "KiB")


def region_kb_from_env(environ):
    return _positive_int_from_env(environ, REGION_KB_ENV, DEFAULT_REGION_KB, "KiB")


def bucket_mb_from_env(environ):
    return _positive_int_from_env(environ, BUCKET_MB_ENV, DEFAULT_BUCKET_MB, "MiB")


def pieces_per_thread_from_env(environ):
    return _positive_int_from_env(environ, PIECES_PER_THREAD_ENV, DEFAULT_PIECES_PER_THREAD,
                                  "pieces")


def write_threads_from_env(environ):
    return _positive_int_from_env(environ, WRITE_THREADS_ENV, DEFAULT_WRITE_THREADS, "threads")


def segment_numbers(seg_bits):
    """Numbers one segment of seg_bits wheel bits covers."""
    return seg_bits // 8 * NUMBERS_PER_BYTE


def small_prime_stop(seg_bits, L_final):
    """End (exclusive) of the segmented prime range [7, stop): as in v5, the primes up to
    half a segment's numbers, which hit every segment at least once. Never above L_final,
    never below 7."""
    return max(7, min(segment_numbers(seg_bits) // 2, L_final))
